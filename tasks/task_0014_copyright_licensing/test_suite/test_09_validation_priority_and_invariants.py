"""Validation priority ordering and PRD invariants:
- state vs business_referential precedence on terminate
- ownership-share invariant under PATCH
- external-event idempotency
(PRD §2.10, §2.8, §2.11, §3.1, §3.6)
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_rights_holder,
    create_two_rights_holders,
    create_registered_work,
    create_draft_work,
    create_offered_license,
    setup_effective_license,
    patch_work_payload,
    emit_event_payload,
    unique_event_id,
    make_rights_holder_headers,
    ADMIN_HEADERS,
)


# ---------------------------------------------------------------------------
# Validation priority — state precedes business_referential
# ---------------------------------------------------------------------------

class TestValidationPriorityState:
    """PRD §2.10: priority 5 (state eligibility / ERR_INVALID_STATE) precedes
    priority 6 (business referential / ERR_FORBIDDEN ownership). When both
    fail, ERR_INVALID_STATE is reported.

    PRD §2.10: "Lower-numbered checks short-circuit higher-numbered ones."
    """

    def test_terminate_offered_license_by_non_licensor_returns_invalid_state(self, api):
        """PRD §2.10: state eligibility (priority 5) fires before
        business_referential ownership (priority 6).

        # difficulty: priority_pair_validation_conflict/state_vs_business_referential_on_license_termination
        """
        licensor, licensee = create_two_rights_holders(api)
        work, _ = create_registered_work(api, owner=licensor)
        license_data = create_offered_license(api, work, licensor, licensee)
        # License is OFFERED (state=OFFERED is invalid for terminate, which
        # requires EFFECTIVE) AND caller is licensee, not licensor (would be
        # ERR_FORBIDDEN). Per PRD §2.10, ERR_INVALID_STATE wins.
        headers = make_rights_holder_headers(licensee["id"])
        resp = api.terminate_license(license_data["id"], headers,
                                       payload={"version": license_data["version"]})
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_terminate_offered_license_third_party_state_short_circuits(self, api):
        """PRD §2.10: 'Lower-numbered checks short-circuit higher-numbered
        ones — a request with a state error and a payload-amount mismatch
        surfaces as ERR_INVALID_STATE.'

        Variant: even a third-party caller (neither licensor nor licensee)
        sees ERR_INVALID_STATE because state precedence applies before the
        business_referential ownership check.

        # difficulty: priority_pair_validation_conflict/state_vs_business_referential_on_license_termination
        """
        licensor, licensee = create_two_rights_holders(api)
        third = create_rights_holder(api, legal_name="Third")
        work, _ = create_registered_work(api, owner=licensor)
        license_data = create_offered_license(api, work, licensor, licensee)
        headers = make_rights_holder_headers(third["id"])
        resp = api.terminate_license(license_data["id"], headers,
                                       payload={"version": license_data["version"]})
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Validation priority — exclusive over territory_term
# ---------------------------------------------------------------------------

class TestValidationPriorityBusinessSafety:
    """PRD §2.10: priority 7 (business_safety / ERR_EXCLUSIVE_LICENSE_VIOLATION)
    fires before priority 8 (business_temporal / ERR_TERRITORY_TERM_OVERLAP).
    """

    def test_accept_world_territory_overlap_returns_exclusive_error(self, api):
        """PRD §3.4: 'Territory overlap is true when ... either side's
        territory contains the token WORLD.'
        PRD §2.10: priority 7 (ERR_EXCLUSIVE_LICENSE_VIOLATION) wins over
        priority 8 (ERR_TERRITORY_TERM_OVERLAP).

        Two EXCLUSIVE licenses, incumbent territory=['WORLD'], candidate
        territory=['US']. Both territory and term and media overlap →
        candidate ACCEPT must be rejected with ERR_EXCLUSIVE_LICENSE_VIOLATION
        (priority 7), not ERR_TERRITORY_TERM_OVERLAP.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_on_license_accept
        """
        licensor = create_rights_holder(api, legal_name="L")
        rh_b = create_rights_holder(api, legal_name="B")
        rh_c = create_rights_holder(api, legal_name="C")
        bundle = setup_effective_license(
            api, licensor=licensor, licensee=rh_b,
            term_start="2099-01-01T00:00:00.000Z",
            term_end="2099-12-31T00:00:00.000Z",
            effective_date_target="2099-01-01T00:00:00.000Z",
            territory=["WORLD"], media_types=["DIGITAL"], exclusivity="EXCLUSIVE",
        )
        work = bundle["work"]
        candidate = create_offered_license(
            api, work, licensor, rh_c,
            term_start="2099-06-01T00:00:00.000Z",
            term_end="2099-12-01T00:00:00.000Z",
            territory=["US"], media_types=["DIGITAL"], exclusivity="EXCLUSIVE",
        )
        from test_helpers import round_payload
        headers = make_rights_holder_headers(rh_c["id"])
        resp = api.submit_round(candidate["id"],
                                  round_payload(action="ACCEPT",
                                                  version=candidate["version"]),
                                  headers)
        validate_error(resp, ApiErrorId.ERR_EXCLUSIVE_LICENSE_VIOLATION.value)

    def test_accept_with_exclusive_incumbent_returns_exclusive_error(self, api):
        """PRD §2.10: priority 7 wins over priority 8.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_on_license_accept
        """
        licensor = create_rights_holder(api, legal_name="L")
        rh_b = create_rights_holder(api, legal_name="B")
        rh_c = create_rights_holder(api, legal_name="C")
        bundle = setup_effective_license(
            api, licensor=licensor, licensee=rh_b,
            term_start="2099-01-01T00:00:00.000Z",
            term_end="2099-12-31T00:00:00.000Z",
            effective_date_target="2099-01-01T00:00:00.000Z",
            territory=["US", "CA"], media_types=["DIGITAL"], exclusivity="EXCLUSIVE",
        )
        work = bundle["work"]
        candidate = create_offered_license(
            api, work, licensor, rh_c,
            term_start="2099-06-01T00:00:00.000Z",
            term_end="2099-12-01T00:00:00.000Z",
            territory=["CA"], media_types=["DIGITAL"], exclusivity="EXCLUSIVE",
        )
        from test_helpers import round_payload
        headers = make_rights_holder_headers(rh_c["id"])
        resp = api.submit_round(candidate["id"],
                                  round_payload(action="ACCEPT",
                                                  version=candidate["version"]),
                                  headers)
        validate_error(resp, ApiErrorId.ERR_EXCLUSIVE_LICENSE_VIOLATION.value)


# ---------------------------------------------------------------------------
# Ownership-share invariant under PATCH
# ---------------------------------------------------------------------------

class TestOwnershipShareInvariantUnderPatch:
    """PRD §3.1: 'the sum of primary_share_bps and every share_bps in
    co_owners must equal exactly 10000 basis points ... A duplicated
    co-owner is rejected with ERR_DUPLICATE_CO_OWNER; a basis-point sum that
    is not exactly 10000 ... is rejected with ERR_OWNERSHIP_SHARES_INVALID.'
    """

    def test_patch_uncompensated_increase_rejected(self, api):
        """PRD §3.1: PATCH that pushes total above 10000 → ERR_OWNERSHIP_SHARES_INVALID.

        # difficulty: compensating_invariant/ownership_share_total_invariant_under_patch
        """
        rh_a = create_rights_holder(api, legal_name="A")
        rh_b = create_rights_holder(api, legal_name="B")
        # Start with primary_share_bps=10000, no co-owners.
        work = create_draft_work(api, rh_a, primary_share_bps=10000, co_owners=[])
        headers = make_rights_holder_headers(rh_a["id"])
        # Add co-owner with 1000 bps WITHOUT decreasing primary → total=11000.
        body = patch_work_payload(
            primary_share_bps=10000,
            co_owners=[{"rights_holder_id": rh_b["id"], "share_bps": 1000}],
            version=work["version"],
        )
        resp = api.patch_work(work["id"], body, headers)
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_SHARES_INVALID.value)

    def test_patch_compensated_split_succeeds(self, api):
        """PRD §3.1: PATCH that keeps total at 10000 succeeds.

        # difficulty: compensating_invariant/ownership_share_total_invariant_under_patch
        """
        rh_a = create_rights_holder(api, legal_name="A")
        rh_b = create_rights_holder(api, legal_name="B")
        work = create_draft_work(api, rh_a, primary_share_bps=10000, co_owners=[])
        headers = make_rights_holder_headers(rh_a["id"])
        body = patch_work_payload(
            primary_share_bps=9000,
            co_owners=[{"rights_holder_id": rh_b["id"], "share_bps": 1000}],
            version=work["version"],
        )
        resp = api.patch_work(work["id"], body, headers)
        data = validate_success(resp)
        assert data["primary_share_bps"] == 9000
        co_owners = data["co_owners"]
        assert len(co_owners) == 1
        assert co_owners[0]["rights_holder_id"] == rh_b["id"]
        assert co_owners[0]["share_bps"] == 1000
        total = data["primary_share_bps"] + sum(co["share_bps"] for co in co_owners)
        assert total == 10000


# ---------------------------------------------------------------------------
# External-event idempotency
# ---------------------------------------------------------------------------

class TestExternalEventIdempotency:
    """PRD §2.11: "The pair (source, external_event_id) must be unique;
    resubmitting an event with a (source, external_event_id) that already
    exists with a different payload is rejected with
    ERR_DUPLICATE_EXTERNAL_EVENT, while a byte-equal replay returns the
    original outcome and does not re-run side effects."
    """

    def test_duplicate_event_id_with_different_payload_rejected(self, api):
        """PRD §2.11: same (source, external_event_id) with different payload
        → ERR_DUPLICATE_EXTERNAL_EVENT."""
        from test_helpers import setup_royalty_dual_variant_scenario
        bundle = setup_royalty_dual_variant_scenario(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]
        # Create + emit a payment.
        from test_helpers import create_final_statement
        s = create_final_statement(
            api, license_data, licensor,
            period_start_at="2026-01-01T00:00:00.000Z",
            period_end_at="2026-02-01T00:00:00.000Z",
            gross_revenue_cents=1_000_000,
        )
        ext_id = unique_event_id("dup-test")
        first = emit_event_payload(
            source="PAYMENT",
            event_type="PAYMENT_RECEIVED",
            ref_entity="RoyaltyStatement",
            ref_id=s["id"],
            payload={"amount_cents": s["net_payable_cents"], "currency": "USD"},
            external_event_id=ext_id,
        )
        resp = api.emit_event(first, ADMIN_HEADERS)
        validate_success(resp)

        # Same (source, external_event_id), different payload.
        bad = emit_event_payload(
            source="PAYMENT",
            event_type="PAYMENT_RECEIVED",
            ref_entity="RoyaltyStatement",
            ref_id=s["id"],
            payload={"amount_cents": s["net_payable_cents"] + 1, "currency": "USD"},
            external_event_id=ext_id,
        )
        resp = api.emit_event(bad, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EXTERNAL_EVENT.value)
