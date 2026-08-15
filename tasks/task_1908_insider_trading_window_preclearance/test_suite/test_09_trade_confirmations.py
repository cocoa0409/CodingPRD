"""Trade confirmation ingestion: matching lanes, rounding order, void release."""
import pytest

from test_helpers import (
    ApiErrorId,
    admin_headers,
    api_client,
    as_officer,
    assert_quantity_conservation,
    assert_same_instant,
    create_approved_request,
    create_current_person,
    create_event_window,
    create_officer,
    create_under_review_request,
    decide_request,
    get_success_data,
    ingest_confirmation,
    run_sweep,
    set_logical_clock,
    validate_success,
)


def _setup_provisional_then_void(api, officer_email, person_email):
    """Request approved against the calendar known at decision time; a window
    created after decided_at later activates over the proposed trade date."""
    set_logical_clock("2026-08-01T00:00:00Z")
    officer = create_officer(officer_email)
    person = create_current_person("Insider A", person_email)
    approved = create_approved_request(
        person, officer, quantity=100, ticker="ACME", side="BUY",
        proposed_trade_date="2026-08-02T00:00:00Z",
    )
    set_logical_clock("2026-08-01T06:00:00Z")
    create_event_window(officer, "ACME", "2026-08-01T12:00:00Z", "2026-08-04T00:00:00Z")
    set_logical_clock("2026-08-02T00:00:00Z")
    run_sweep(officer)
    return officer, person, approved


class TestProvisionalVsFinalValidity:
    def test_provisional_approval_voided_by_later_window_activation(self, api):
        """PRD §3.4: "Approval screens the calendar only as known at decision time,
        and a window created after `decided_at` cannot retroactively block the
        decision; but when such a later-created window later activates, the sweep's
        activation cascade re-evaluates. Every `APPROVED` request whose
        `proposed_trade_date` falls inside the activating window's half-open
        interval, and to which that window applies, moves to `VOIDED`".

        Design: Difficulty/dual_variant_calc/approval_validity_provisional_vs_final
        """
        officer, person, approved = _setup_provisional_then_void(
            api, "officer1@x.com", "insider_a@x.com"
        )
        fresh = get_success_data(
            api.get_preclearance_request(approved["id"], admin_headers())
        )
        assert fresh["status"] == "VOIDED"
        assert_same_instant(
            fresh["approval_valid_until"], "2026-08-03T00:00:00Z",
            "approval_valid_until",
        )

    def test_voided_approval_confirmation_flagged_blackout_trade(self, api):
        """PRD §3.7: "If an `ACTIVE` blackout window applicable to the ticker covers
        the `trade_date`, `flagged_reason` is `BLACKOUT_TRADE`; otherwise, if an
        `ACTIVE` restricted-list entry matches the ticker, `flagged_reason` is
        `RESTRICTED_LIST`; otherwise it is `NO_PRECLEARANCE`." PRD §3.4: "Every
        `APPROVED` request whose `proposed_trade_date` falls inside the activating
        window's half-open interval, and to which that window applies, moves to
        `VOIDED`".

        Design: Difficulty/dual_variant_calc/approval_validity_provisional_vs_final
        """
        officer, person, approved = _setup_provisional_then_void(
            api, "officer1b@x.com", "insider_a2@x.com"
        )
        voided = get_success_data(
            api.get_preclearance_request(approved["id"], admin_headers())
        )
        assert voided["status"] == "VOIDED"

        conf = ingest_confirmation(
            officer, person, ticker="ACME", side="BUY", quantity=100, price=10.00,
            trade_date="2026-08-02T00:00:00Z", broker_ref="BR-D1",
        )
        assert conf["status"] == "FLAGGED"
        assert conf["flagged_reason"] == "BLACKOUT_TRADE"


class TestMatchedQuantityRoundingOrder:
    def _setup_20_02_request(self, api, officer_email, person_email):
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer(officer_email)
        person = create_current_person("Insider C", person_email)
        approved = create_approved_request(
            person, officer, quantity=20.02, ticker="ACME", side="BUY",
            proposed_trade_date="2026-08-02T00:00:00Z",
        )
        return officer, person, approved

    def test_per_line_rounding_accumulates_20_02_and_closes(self, api):
        """PRD §3.7: "the applied amount is the smaller of the confirmation's
        `quantity` and the request's `remaining_quantity`, rounded half up to two
        decimal places before any accumulation; the request's `matched_quantity` then
        increases by the applied amount and its `remaining_quantity` decreases by the
        applied amount, each re-rounded half up to two decimal places. The order is
        load-bearing — two confirmations of 10.005 shares each accumulate a
        `matched_quantity` of 20.02 under this rule, where summing the raw quantities
        and rounding once at the end would yield 20.01. When consumption drives
        `remaining_quantity` to zero, the request moves from `APPROVED` to `CLOSED`."

        Design: Difficulty/combinatorial_formula/matched_quantity_per_line_rounding_order
        """
        officer, person, approved = self._setup_20_02_request(
            api, "officer4@x.com", "insider_c@x.com"
        )
        ingest_confirmation(
            officer, person, quantity=10.005, price=50.00,
            trade_date="2026-08-02T00:00:00Z", broker_ref="BR-D4-1",
        )
        ingest_confirmation(
            officer, person, quantity=10.005, price=50.00,
            trade_date="2026-08-02T00:00:00Z", broker_ref="BR-D4-2",
        )
        fresh = get_success_data(
            api.get_preclearance_request(approved["id"], admin_headers())
        )
        assert fresh["matched_quantity"] == pytest.approx(20.02, abs=1e-9)
        assert fresh["remaining_quantity"] == pytest.approx(0, abs=1e-9)
        assert fresh["status"] == "CLOSED"

    def test_each_confirmation_matched_against_request(self, api):
        """PRD §3.7: "On a match, the confirmation records the request in
        `match_preclearance_id` and the request consumes quantity with a pinned
        rounding order".

        Design: Difficulty/combinatorial_formula/matched_quantity_per_line_rounding_order
        """
        officer, person, approved = self._setup_20_02_request(
            api, "officer4b@x.com", "insider_c2@x.com"
        )
        conf1 = ingest_confirmation(
            officer, person, quantity=10.005, price=50.00,
            trade_date="2026-08-02T00:00:00Z", broker_ref="BR-D4-1",
        )
        conf2 = ingest_confirmation(
            officer, person, quantity=10.005, price=50.00,
            trade_date="2026-08-02T00:00:00Z", broker_ref="BR-D4-2",
        )
        for conf in (conf1, conf2):
            assert conf["status"] == "MATCHED_PRECLEARANCE"
            assert conf["match_preclearance_id"] == approved["id"]


class TestApprovalWindowBoundary:
    def test_trade_date_equal_to_valid_until_matches(self, api):
        """PRD §3.7: "a qualifying request shares the confirmation's
        `covered_person_id`, `security_ticker`, and `trade_side`; is `APPROVED`; has
        an approval window containing the `trade_date` — that is, `trade_date` no
        earlier than the request's `decided_at` and no later than its
        `approval_valid_until`, both ends inclusive". PRD §3.7: "When consumption
        drives `remaining_quantity` to zero, the request moves from `APPROVED` to
        `CLOSED`."

        Design: Difficulty/boundary_precision_check/approval_valid_until_inclusive_match_boundary
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer11@x.com")
        person = create_current_person("Insider J", "insider_j@x.com")
        approved = create_approved_request(
            person, officer, quantity=100, ticker="ACME", side="BUY",
            proposed_trade_date="2026-08-02T00:00:00Z",
        )
        conf = ingest_confirmation(
            officer, person, ticker="ACME", side="BUY", quantity=100, price=10.00,
            trade_date="2026-08-03T00:00:00Z", broker_ref="BR-D11-1",
        )
        assert conf["status"] == "MATCHED_PRECLEARANCE"
        fresh = get_success_data(
            api.get_preclearance_request(approved["id"], admin_headers())
        )
        assert fresh["status"] == "CLOSED"

    def test_one_second_past_valid_until_flagged(self, api):
        """PRD §3.7: "has an approval window containing the `trade_date` — that is,
        `trade_date` no earlier than the request's `decided_at` and no later than its
        `approval_valid_until`, both ends inclusive". PRD §3.7: "otherwise it is
        `NO_PRECLEARANCE`."

        Design: Difficulty/boundary_precision_check/approval_valid_until_inclusive_match_boundary
        """
        set_logical_clock("2026-08-04T00:00:00Z")
        officer = create_officer("officer11b@x.com")
        person = create_current_person("Insider J2", "insider_j2@x.com")
        approved = create_approved_request(
            person, officer, quantity=50, ticker="ACME", side="BUY",
            proposed_trade_date="2026-08-05T00:00:00Z",
        )
        assert_same_instant(
            approved["approval_valid_until"], "2026-08-06T00:00:00Z",
            "approval_valid_until",
        )
        conf = ingest_confirmation(
            officer, person, ticker="ACME", side="BUY", quantity=50, price=10.00,
            trade_date="2026-08-06T00:00:01Z", broker_ref="BR-D11-2",
        )
        assert conf["status"] == "FLAGGED"
        assert conf["flagged_reason"] == "NO_PRECLEARANCE"


class TestQuantityConservation:
    def test_match_draws_down_remaining_quantity(self, api):
        """PRD §3.7: "the request's `matched_quantity` then increases by the applied
        amount and its `remaining_quantity` decreases by the applied amount, each
        re-rounded half up to two decimal places." PRD §3.4: "initializes
        `remaining_quantity` to the full `quantity`".

        Design: Difficulty/compensating_invariant/approval_quantity_conserved_through_match_and_void
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer16@x.com")
        person = create_current_person("Insider O", "insider_o@x.com")
        approved = create_approved_request(
            person, officer, quantity=100, ticker="ACME", side="BUY",
            proposed_trade_date="2026-08-02T00:00:00Z",
        )
        assert approved["quantity"] == 100
        assert approved["matched_quantity"] == 0
        assert approved["remaining_quantity"] == 100
        assert_quantity_conservation(approved)

        ingest_confirmation(
            officer, person, ticker="ACME", side="BUY", quantity=40, price=10.00,
            trade_date="2026-08-02T00:00:00Z", broker_ref="BR-D17",
        )
        fresh = get_success_data(
            api.get_preclearance_request(approved["id"], admin_headers())
        )
        assert fresh["matched_quantity"] == pytest.approx(40, abs=1e-9)
        assert fresh["remaining_quantity"] == pytest.approx(60, abs=1e-9)
        assert_quantity_conservation(fresh)

    def test_void_restores_full_quantity_and_releases_match(self, api):
        """PRD §3.4: "Voiding unwinds consumption: each confirmation matched to the
        request returns to `RECEIVED` with its `match_preclearance_id` cleared, while
        the request's `matched_quantity` resets to zero and its `remaining_quantity`
        is restored to the full `quantity`."

        Design: Difficulty/compensating_invariant/approval_quantity_conserved_through_match_and_void
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer16b@x.com")
        person = create_current_person("Insider O2", "insider_o2@x.com")
        approved = create_approved_request(
            person, officer, quantity=100, ticker="ACME", side="BUY",
            proposed_trade_date="2026-08-02T00:00:00Z",
        )
        conf = ingest_confirmation(
            officer, person, ticker="ACME", side="BUY", quantity=40, price=10.00,
            trade_date="2026-08-02T00:00:00Z", broker_ref="BR-D17",
        )
        assert conf["status"] == "MATCHED_PRECLEARANCE"

        set_logical_clock("2026-08-01T06:00:00Z")
        create_event_window(officer, "ACME", "2026-08-02T00:00:00Z",
                            "2026-08-05T00:00:00Z")
        set_logical_clock("2026-08-02T00:00:00Z")
        run_sweep(officer)

        voided = get_success_data(
            api.get_preclearance_request(approved["id"], admin_headers())
        )
        assert voided["status"] == "VOIDED"
        assert voided["matched_quantity"] == pytest.approx(0, abs=1e-9)
        assert voided["remaining_quantity"] == pytest.approx(100, abs=1e-9)
        assert_quantity_conservation(voided)

        released = get_success_data(
            api.get_trade_confirmation(conf["id"], as_officer(officer))
        )
        # PRD §3.4 pins the link clearing ("match_preclearance_id cleared") and
        # the request-side unwind above. The observable post-sweep status is NOT
        # uniquely derivable: §2.10 step 8 re-runs the matching pass over "every
        # trade confirmation resting in RECEIVED" (same-sweep re-match -> the
        # now-ACTIVE window flags it BLACKOUT_TRADE), while §3.7 calls a released
        # match "eligible for re-matching on the next sweep" (stays RECEIVED until
        # a later sweep). Both readings are PRD-faithful, so only the cleared
        # link — identical under both — is asserted here.
        assert released["match_preclearance_id"] is None


class TestRequestConfirmationsSubresource:
    def test_request_confirmations_subresource_lists_match(self, api):
        """PRD §4: "List confirmations matched to a request". PRD §3.7: "On a match,
        the confirmation records the request in `match_preclearance_id`".

        Design: Corner/endpoints/get_request_trade_confirmations_subresource
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer_e1@x.com")
        person = create_current_person("Insider E1", "insider_e1@x.com")
        approved = create_approved_request(
            person, officer, quantity=100, ticker="ACME", side="BUY",
            proposed_trade_date="2026-08-02T00:00:00Z",
        )
        conf = ingest_confirmation(
            officer, person, ticker="ACME", side="BUY", quantity=40, price=10.00,
            trade_date="2026-08-02T00:00:00Z", broker_ref="BR-C-E1",
        )
        data = get_success_data(
            api.list_request_trade_confirmations(approved["id"], as_officer(officer))
        )
        assert isinstance(data, list) and len(data) == 1
        assert data[0]["id"] == conf["id"]
        assert data[0]["match_preclearance_id"] == approved["id"]
