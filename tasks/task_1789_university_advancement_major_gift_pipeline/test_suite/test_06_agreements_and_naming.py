"""Gift agreements: drafting gates, naming reservation half-open window,
execute/rescind effects, retirement, parallel signature/compliance dimensions."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_gift_officer_headers,
    create_prospect, rate_prospect, assign_prospect, move_prospect,
    get_prospect, get_agreement, get_fund, find_fund_for_agreement,
    create_fundraiser, create_naming_opportunity,
    create_proposal_for, create_submitted_proposal, create_approved_proposal,
    create_executed_agreement, setup_executed_agreement, setup_endowed_fund_active,
    create_payment, create_report_payload, set_clock,
    create_agreement_payload,
    assert_iso_instant_equal,
)

DIR = TEST_USERS["director_headers"]
VP = TEST_USERS["vp_headers"]
DRO = TEST_USERS["dro_headers"]
FIN = TEST_USERS["finance_headers"]


class TestAgreementDrafting:
    def test_agreement_create_on_unapproved_proposal_rejected(self, api):
        """PRD §3.5: "The owning `GiftOfficer` drafts an agreement from a
        proposal that is `APPROVED` — a proposal in any other state, including
        `EXPIRED` and `SUPERSEDED`, fails with `ERR_PROPOSAL_NOT_APPROVED`."

        Design: Corner/state_machines/agreement_create_on_unapproved_proposal_rejected
        """
        from test_helpers import setup_rated_assigned_prospect
        f, p, _ = setup_rated_assigned_prospect(move_to="CULTIVATION")
        # A fresh under-review proposal is not yet APPROVED.
        prop2 = create_submitted_proposal(p["id"], f["id"], 1000000)
        officer = make_gift_officer_headers(f["id"])
        resp = api.create_agreement(
            prop2["id"],
            create_agreement_payload(agreement_amount_cents=1000000),
            officer,
        )
        validate_error(resp, ApiErrorId.ERR_PROPOSAL_NOT_APPROVED)
        rows, meta = validate_paginated(api.list_agreements(VP, params={"proposal_id": prop2["id"]}))
        assert rows == [] and meta["total_count"] == 0

    def test_agreement_amount_mismatch_rejected(self, api):
        """PRD §3.5: "a positive integer `agreement_amount_cents` that must equal
        the approved proposal's `ask_amount_cents` exactly (any difference is
        rejected with `ERR_AGREEMENT_AMOUNT_MISMATCH`)."

        Design: Corner/validations/agreement_amount_mismatch_rejected
        """
        from test_helpers import setup_rated_assigned_prospect
        f, p, _ = setup_rated_assigned_prospect(move_to="CULTIVATION")
        prop = create_approved_proposal(p["id"], f["id"], 1000000)
        officer = make_gift_officer_headers(f["id"])
        resp = api.create_agreement(
            prop["id"],
            create_agreement_payload(agreement_amount_cents=999999),
            officer,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_AMOUNT_MISMATCH)
        rows, meta = validate_paginated(api.list_agreements(VP, params={"proposal_id": prop["id"]}))
        assert rows == [] and meta["total_count"] == 0

    def test_below_naming_floor_rejected(self, api):
        """PRD §3.5: "The price floor is enforced at draft time: when a naming
        claim is present, `agreement_amount_cents` below the opportunity's
        `price_floor_cents` is rejected with `ERR_BELOW_NAMING_FLOOR`."

        Design: Corner/validations/below_naming_floor_rejected
        """
        from test_helpers import setup_rated_assigned_prospect
        opp = create_naming_opportunity(price_floor_cents=3000000)
        f, p, _ = setup_rated_assigned_prospect(move_to="CULTIVATION")
        prop = create_approved_proposal(p["id"], f["id"], 2000000)
        officer = make_gift_officer_headers(f["id"])
        resp = api.create_agreement(
            prop["id"],
            create_agreement_payload(
                agreement_amount_cents=2000000, naming_opportunity_id=opp["id"],
            ),
            officer,
        )
        validate_error(resp, ApiErrorId.ERR_BELOW_NAMING_FLOOR)
        opp_after = validate_success(api.get_naming_opportunity(opp["id"], VP))
        assert opp_after["status"] == "AVAILABLE"


class TestAgreementExecution:
    def test_agreement_execute_establishes_fund_and_moves_stewardship(self, api):
        """PRD §3.5: "for `RESTRICTED_CURRENT_USE` or `ENDOWED` agreements the
        system establishes a **restricted fund** carrying the `agreement_id`, the
        agreement's `purpose_code`, an `is_endowed` flag true exactly when the
        agreement is `ENDOWED`, a `balance_cents` of zero, a
        `minimum_activation_cents` of $25,000 (2500000 cents) copied from the
        system constant at establishment, an empty `trailing_market_values` list,
        and `status` `PENDING_MINIMUM`; and the prospect's `moves_stage` moves to
        `STEWARDSHIP` from `CULTIVATION`, `SOLICITATION`, or `NEGOTIATION` — the
        only path into that stage — with the prospect's `version` advancing by 1."

        Design: Corner/state_machines/agreement_execute_establishes_fund_and_moves_stewardship
        """
        ctx = setup_executed_agreement(
            3000000, proposal_type="OUTRIGHT",
            restriction_type="ENDOWED", purpose_code="GEN_ENDOW",
        )
        agr = get_agreement(ctx["agr"]["id"])
        assert agr["signature_status"] == "EXECUTED"

        fund = ctx["fund"]
        assert fund["status"] == "PENDING_MINIMUM"
        assert fund["balance_cents"] == 0
        assert fund["is_endowed"] is True
        assert fund["minimum_activation_cents"] == 2500000

        p_after = get_prospect(ctx["p"]["id"])
        assert p_after["moves_stage"] == "STEWARDSHIP"

    def test_agreement_execute_from_draft_rejected(self, api):
        """PRD §3.5: "A `VPAdvancement` executes an agreement in
        `PENDING_SIGNATURE` (otherwise `ERR_AGREEMENT_INVALID_STATE`)."

        Design: Corner/state_machines/agreement_execute_from_draft_rejected
        """
        from test_helpers import setup_rated_assigned_prospect
        f, p, _ = setup_rated_assigned_prospect(move_to="CULTIVATION")
        prop = create_approved_proposal(p["id"], f["id"], 1000000)
        officer = make_gift_officer_headers(f["id"])
        resp = api.create_agreement(
            prop["id"], create_agreement_payload(agreement_amount_cents=1000000), officer,
        )
        agr = validate_success(resp, expected_status=201)

        resp = api.execute_agreement(agr["id"], VP)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_INVALID_STATE)
        assert get_agreement(agr["id"])["signature_status"] == "DRAFT"

    def test_agreement_rescind_blocked_then_succeeds_after_reversal(self, api):
        """PRD §3.5: "A `VPAdvancement` may rescind from `DRAFT`,
        `PENDING_SIGNATURE`, or `EXECUTED` (an already `RESCINDED` agreement
        rejects with `ERR_AGREEMENT_INVALID_STATE`), but only while no
        non-reversed gift payment references the agreement's pledge or its fund —
        otherwise `ERR_RESCIND_BLOCKED_BY_PAYMENTS`."
        PRD §3.5: "the established restricted fund, if any, closes — which
        requires its `balance_cents` to be zero."

        Design: Corner/state_machines/agreement_rescind_blocked_then_succeeds_after_reversal
        """
        ctx = setup_executed_agreement(
            3000000, proposal_type="OUTRIGHT",
            restriction_type="ENDOWED", purpose_code="GEN_ENDOW",
        )
        pay = create_payment(ctx["p"]["id"], 1000000, fund_id=ctx["fund"]["id"])

        resp = api.rescind_agreement(ctx["agr"]["id"], VP)
        validate_error(resp, ApiErrorId.ERR_RESCIND_BLOCKED_BY_PAYMENTS)

        validate_success(api.reverse_gift_payment(pay["id"], FIN))
        resp = api.rescind_agreement(ctx["agr"]["id"], VP)
        data = validate_success(resp)
        assert data["signature_status"] == "RESCINDED"
        assert get_fund(ctx["fund"]["id"])["status"] == "CLOSED"


class TestNamingReservationHalfOpen:
    """Queue A: resource_temporal_overlap / naming_reservation_half_open_window."""

    def _two_claimants(self, api):
        """Opportunity + two approved 2000000 proposals whose agreements both
        claim it; agreement A presented at the default clock."""
        opp = create_naming_opportunity(price_floor_cents=1500000)
        f = create_fundraiser()

        def _side(name):
            p = create_prospect(full_name=name, contact_email=f"{name.replace(' ', '').lower()}@x.com")
            rate_prospect(p["id"])
            assign_prospect(f["id"], p["id"])
            move_prospect(p["id"], f["id"], "CULTIVATION")
            prop = create_approved_proposal(p["id"], f["id"], 2000000)
            officer = make_gift_officer_headers(f["id"])
            resp = api.create_agreement(
                prop["id"],
                create_agreement_payload(
                    agreement_amount_cents=2000000, naming_opportunity_id=opp["id"],
                ),
                officer,
            )
            return validate_success(resp, expected_status=201)

        agr_a = _side("Donor A")
        officer = make_gift_officer_headers(f["id"])
        validate_success(api.present_agreement(agr_a["id"], officer))
        agr_b = _side("Donor B")
        return f, opp, agr_a, agr_b, officer

    def test_present_inside_window_rejected_and_at_window_end_allowed(self, api):
        """PRD §3.5: "The hold is **half-open**: it covers the interval from the
        presentation instant up to but not including `reserved_until`, so the
        reservation is free again at exactly `reserved_until`."
        PRD §3.5: "the opportunity must be `AVAILABLE` (otherwise
        `ERR_NAMING_OPPORTUNITY_UNAVAILABLE`), and on success it becomes
        `RESERVED` with `reserved_by_agreement_id` set to the agreement and
        `reserved_until` set to the current logical time plus 14 days."

        Design: Difficulty/resource_temporal_overlap/naming_reservation_half_open_window
        """
        f, opp, agr_a, agr_b, officer = self._two_claimants(api)

        opp0 = validate_success(api.get_naming_opportunity(opp["id"], VP))
        assert opp0["status"] == "RESERVED"
        assert_iso_instant_equal(opp0["reserved_until"], "2026-08-15T00:00:00Z")  # default clock + 14 days

        # One second before the half-open end: still held.
        set_clock("2026-08-14T23:59:59Z")
        resp = api.present_agreement(agr_b["id"], officer)
        validate_error(resp, ApiErrorId.ERR_NAMING_OPPORTUNITY_UNAVAILABLE)

        # At exactly reserved_until: the hold is released, re-presentation succeeds.
        set_clock("2026-08-15T00:00:00Z")
        resp = api.present_agreement(agr_b["id"], officer)
        validate_success(resp)

        opp1 = validate_success(api.get_naming_opportunity(opp["id"], VP))
        assert opp1["status"] == "RESERVED"
        assert opp1["reserved_by_agreement_id"] == agr_b["id"]
        assert_iso_instant_equal(opp1["reserved_until"], "2026-08-29T00:00:00Z")  # new 14-day window

    def test_reservation_released_by_sweep_at_reserved_until(self, api):
        """PRD §3.5: "Independently of rescission, the clock sweep releases any
        `RESERVED` opportunity whose `reserved_until` instant has been reached,
        clearing both reservation fields."
        PRD §3.5: "The hold is **half-open**: it covers the interval from the
        presentation instant up to but not including `reserved_until`, so the
        reservation is free again at exactly `reserved_until`."

        Design: Difficulty/resource_temporal_overlap/naming_reservation_half_open_window
        """
        f, opp, agr_a, agr_b, officer = self._two_claimants(api)

        # Just before the end: the reservation is still held by agreement A.
        set_clock("2026-08-14T23:59:59Z")
        opp_mid = validate_success(api.get_naming_opportunity(opp["id"], VP))
        assert opp_mid["status"] == "RESERVED"
        assert opp_mid["reserved_by_agreement_id"] == agr_a["id"]

        # At exactly reserved_until the sweep frees the half-open window's end.
        set_clock("2026-08-15T00:00:00Z")
        opp_end = validate_success(api.get_naming_opportunity(opp["id"], VP))
        assert opp_end["status"] == "AVAILABLE"
        assert opp_end["reserved_by_agreement_id"] is None
        assert opp_end["reserved_until"] is None

        # Agreement B can now claim it with a fresh 14-day window.
        validate_success(api.present_agreement(agr_b["id"], officer))
        opp_claimed = validate_success(api.get_naming_opportunity(opp["id"], VP))
        assert opp_claimed["status"] == "RESERVED"
        assert opp_claimed["reserved_by_agreement_id"] == agr_b["id"]
        assert_iso_instant_equal(opp_claimed["reserved_until"], "2026-08-29T00:00:00Z")

    def test_reservation_expired_execute_rejected(self, api):
        """PRD §3.5: "the opportunity must still be `RESERVED`, the reservation
        must be held by this very agreement, and the current logical time must
        still be earlier than `reservation_expires_at`; a lapsed window fails
        with `ERR_RESERVATION_EXPIRED`."
        PRD §3.5: "the clock sweep releases any `RESERVED` opportunity whose
        `reserved_until` instant has been reached, clearing both reservation
        fields."

        Design: Corner/validations/reservation_expired_execute_rejected
        """
        opp = create_naming_opportunity(price_floor_cents=1500000)
        ctx = None
        from test_helpers import setup_rated_assigned_prospect
        f, p, _ = setup_rated_assigned_prospect(move_to="CULTIVATION")
        prop = create_approved_proposal(p["id"], f["id"], 2000000)
        officer = make_gift_officer_headers(f["id"])
        resp = api.create_agreement(
            prop["id"],
            create_agreement_payload(agreement_amount_cents=2000000, naming_opportunity_id=opp["id"]),
            officer,
        )
        agr = validate_success(resp, expected_status=201)
        validate_success(api.present_agreement(agr["id"], officer))

        # Sweep past the reservation end.
        set_clock("2026-08-16T00:00:00Z")
        resp = api.execute_agreement(agr["id"], VP)
        validate_error(resp, ApiErrorId.ERR_RESERVATION_EXPIRED)

        opp_after = validate_success(api.get_naming_opportunity(opp["id"], VP))
        assert opp_after["status"] == "AVAILABLE"  # released by the sweep
        assert get_agreement(agr["id"])["signature_status"] == "PENDING_SIGNATURE"


class TestNamingRetirement:
    def test_naming_retire_releases_claim_and_blocks_execute(self, api):
        """PRD §3.5: "When a `RESERVED` opportunity is retired, the holding
        agreement keeps its `signature_status` but loses its claim — a later
        execution attempt then fails with `ERR_NAMING_OPPORTUNITY_UNAVAILABLE`,
        since the opportunity is no longer held for it."

        Design: Corner/state_machines/naming_retire_releases_claim_and_blocks_execute
        """
        from test_helpers import setup_rated_assigned_prospect
        opp = create_naming_opportunity(price_floor_cents=1500000)
        f, p, _ = setup_rated_assigned_prospect(move_to="CULTIVATION")
        prop = create_approved_proposal(p["id"], f["id"], 2000000)
        officer = make_gift_officer_headers(f["id"])
        resp = api.create_agreement(
            prop["id"],
            create_agreement_payload(agreement_amount_cents=2000000, naming_opportunity_id=opp["id"]),
            officer,
        )
        agr = validate_success(resp, expected_status=201)
        validate_success(api.present_agreement(agr["id"], officer))

        validate_success(api.retire_naming_opportunity(opp["id"], VP))
        opp_after = validate_success(api.get_naming_opportunity(opp["id"], VP))
        assert opp_after["status"] == "RETIRED"
        # Note: PRD §3.5 states the holding agreement "loses its claim" but does
        # not state whether retirement clears the reservation fields (contrast
        # rescission's explicit "cleared" and execution's "kept for audit"), so
        # no field-level assertion is made here — the observable consequences
        # (RETIRED status, failed execution, preserved signature status) are
        # asserted instead.

        resp = api.execute_agreement(agr["id"], VP)
        validate_error(resp, ApiErrorId.ERR_NAMING_OPPORTUNITY_UNAVAILABLE)
        assert get_agreement(agr["id"])["signature_status"] == "PENDING_SIGNATURE"


class TestAgreementParallelDimensions:
    """Queue A: non_linear_state_machine / agreement_parallel_signature_compliance_dimensions."""

    def _frozen_setup(self, api):
        """ENDOWED agreement executed; fund ACTIVE; report overdue after sweep."""
        ctx = setup_endowed_fund_active(balance_cents=3000000)
        resp = api.create_report(
            ctx["fund"]["id"],
            create_report_payload(period_start="2025-01-01T00:00:00Z",
                                  period_end="2025-06-30T00:00:00Z"),
            DRO,
        )
        report = validate_success(resp, expected_status=201)
        ctx["report"] = report
        return ctx

    def test_compliance_lapses_and_recovers_independently_of_signature(self, api):
        """PRD §2.9: "A gift agreement has a `signature_status` (`DRAFT`,
        `PENDING_SIGNATURE`, `EXECUTED`, `RESCINDED`) and a `compliance_status`
        (`COMPLIANT`, `STEWARDSHIP_LAPSED`); stewardship lapses freeze spending
        without touching the signature dimension."
        PRD §3.8: "the fund moves from `ACTIVE` to `SPENDING_FROZEN` — a fund
        still `PENDING_MINIMUM` is not frozen — and the establishing agreement's
        `compliance_status` becomes `STEWARDSHIP_LAPSED`."
        PRD §3.8: "when the overdue report reaches `DELIVERED` and no other
        report of the fund remains `OVERDUE`, the fund returns from
        `SPENDING_FROZEN` to `ACTIVE` and the agreement's `compliance_status`
        returns to `COMPLIANT`."

        Design: Difficulty/non_linear_state_machine/agreement_parallel_signature_compliance_dimensions
        """
        ctx = self._frozen_setup(api)
        # due_date = 2025-06-30 + 90 days = 2025-09-28; sweep at 2026-08-02.
        set_clock("2026-08-02T00:00:00Z")

        agr_mid = get_agreement(ctx["agr"]["id"])
        assert agr_mid["signature_status"] == "EXECUTED"  # undisturbed
        assert agr_mid["compliance_status"] == "STEWARDSHIP_LAPSED"
        assert get_fund(ctx["fund"]["id"])["status"] == "SPENDING_FROZEN"

        validate_success(api.submit_report(ctx["report"]["id"], DRO))
        validate_success(api.deliver_report(ctx["report"]["id"], DRO))

        agr_end = get_agreement(ctx["agr"]["id"])
        assert agr_end["signature_status"] == "EXECUTED"
        assert agr_end["compliance_status"] == "COMPLIANT"
        assert get_fund(ctx["fund"]["id"])["status"] == "ACTIVE"

    def test_report_becomes_overdue_under_clock_sweep(self, api):
        """PRD §3.8: "When the clock sweep finds a `DRAFT` report whose
        `due_date` is strictly before the current logical time, the report
        becomes `OVERDUE`, and two cascades fire: the fund moves from `ACTIVE` to
        `SPENDING_FROZEN` — a fund still `PENDING_MINIMUM` is not frozen — and
        the establishing agreement's `compliance_status` becomes
        `STEWARDSHIP_LAPSED`, each touched resource advancing its `version`."

        Design: Difficulty/non_linear_state_machine/agreement_parallel_signature_compliance_dimensions
        """
        ctx = self._frozen_setup(api)
        rows_before, _ = validate_paginated(api.list_fund_reports(ctx["fund"]["id"], DRO))
        assert rows_before[0]["status"] == "DRAFT"
        assert_iso_instant_equal(rows_before[0]["due_date"], "2025-09-28T00:00:00Z")

        set_clock("2026-08-02T00:00:00Z")

        rows_after, _ = validate_paginated(api.list_fund_reports(ctx["fund"]["id"], DRO))
        assert rows_after[0]["status"] == "OVERDUE"
        assert get_fund(ctx["fund"]["id"])["status"] == "SPENDING_FROZEN"
        assert get_agreement(ctx["agr"]["id"])["compliance_status"] == "STEWARDSHIP_LAPSED"
