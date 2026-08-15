"""Cyclic state machines: attestation revision loop and claim denial /
resubmission loop (PRD §3.5, §3.7)."""
from test_helpers import (
    BILLING,
    SCHED,
    all_tefra_steps_true,
    assert_version_incremented,
    create_case,
    create_fee_schedule,
    create_physician,
    create_published_roster,
    create_site,
    get_success_data,
    make_physician_headers,
    setup_completed_solo_case,
    setup_locked_roster_with_ready_claim,
    api_client,
)


def _attestation_fixture(api):
    """Site + fee + physicians D/D2 + PUBLISHED roster + case + attestation."""
    site = create_site()
    create_fee_schedule("P100", 5)
    director = create_physician("Dr. Direct")
    peer = create_physician("Dr. Peer")
    roster = create_published_roster(site["id"], required_primary_slots=0,
                                     scheduled_day_end_minute=1020)
    case = create_case(roster["id"], scheduled_start_minute=540,
                       scheduled_end_minute=600)
    att = get_success_data(api.create_attestation(
        {"case_id": case["id"], "physician_id": director["id"]}, SCHED))
    return director, peer, att


class TestAttestationRevisionLoop:
    def test_rejected_attestation_resubmits_and_verifies(self, api):
        """PRD §3.5: "Rejection moves `SUBMITTED → REJECTED`, records the
        supplied `rejection_reason`, and returns the attestation to the
        physician, who may revise and resubmit — each such resubmission again
        increments `submitted_count`."
        PRD §3.5: "Each successful submission moves the attestation to
        `SUBMITTED`, increments `submitted_count` by one, clears any prior
        `rejection_reason` to null, and increments `version`."

        Design: Difficulty/non_linear_state_machine/attestation_rejection_revision_loop
        """
        director, peer, att = _attestation_fixture(api)
        first = get_success_data(api.submit_attestation(
            att["id"], all_tefra_steps_true(),
            make_physician_headers(director["id"])))
        assert first["status"] == "SUBMITTED"
        assert first["submitted_count"] == 1
        rejected = get_success_data(api.reject_attestation(
            att["id"], {"rejection_reason": "MISSING_INDUCTION_DETAIL"},
            make_physician_headers(peer["id"])))
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "MISSING_INDUCTION_DETAIL"
        resubmitted = get_success_data(api.submit_attestation(
            att["id"], all_tefra_steps_true(),
            make_physician_headers(director["id"])))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["submitted_count"] == 2, (
            f"second pass through the revision loop must increment "
            f"submitted_count to 2, got {resubmitted['submitted_count']}")
        assert resubmitted["rejection_reason"] is None, \
            "rejection_reason must be cleared on resubmit"
        verified = get_success_data(api.verify_attestation(
            att["id"], make_physician_headers(peer["id"])))
        assert verified["status"] == "VERIFIED"

    def test_submission_increments_version_and_count_together(self, api):
        """PRD §3.5: "Each successful submission moves the attestation to
        `SUBMITTED`, increments `submitted_count` by one, clears any prior
        `rejection_reason` to null, and increments `version`."

        Design: Difficulty/non_linear_state_machine/attestation_rejection_revision_loop
        """
        director, peer, att = _attestation_fixture(api)
        submitted = get_success_data(api.submit_attestation(
            att["id"], all_tefra_steps_true(),
            make_physician_headers(director["id"])))
        assert_version_incremented(att["version"], submitted["version"],
                                   "attestation submit")
        rejected = get_success_data(api.reject_attestation(
            att["id"], {"rejection_reason": "INCOMPLETE_PLAN"},
            make_physician_headers(peer["id"])))
        assert_version_incremented(submitted["version"], rejected["version"],
                                   "attestation reject")
        resubmitted = get_success_data(api.submit_attestation(
            att["id"], all_tefra_steps_true(),
            make_physician_headers(director["id"])))
        assert_version_incremented(rejected["version"], resubmitted["version"],
                                   "attestation resubmit")
        assert resubmitted["submitted_count"] == submitted["submitted_count"] + 1


class TestClaimDenialResubmissionLoop:
    def test_denied_claim_loops_back_to_ready_then_paid(self, api):
        """PRD §3.7: "`PAID` and `WRITTEN_OFF` are terminal; `DENIED` loops
        back through mark-ready."
        PRD §3.7: "A resubmitted claim increments `resubmission_count` by one
        and clears `denial_reason` to null, without recomputing its charge."

        Design: Difficulty/non_linear_state_machine/claim_denial_resubmission_loop
        """
        # P400 base 4; actual 90 min -> 6.0 time units -> 10.0 units;
        # PERSONAL 80000.
        ctx = setup_locked_roster_with_ready_claim(
            provider_type="ANESTHESIOLOGIST", procedure_code="P400",
            base_units=4, scheduled_start_minute=540, scheduled_end_minute=600,
            start_iso="2026-08-10T09:00:00Z", end_iso="2026-08-10T10:30:00Z")
        claim_id = ctx["claim"]["id"]
        assert ctx["claim"]["charge_cents"] == 80000
        get_success_data(api.submit_claim(claim_id, BILLING))
        denied = get_success_data(api.record_claim_denial(
            claim_id, {"denial_reason": "MISSING_DOCUMENTATION"}, BILLING))
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "MISSING_DOCUMENTATION"
        resubmitted = get_success_data(api.mark_claim_ready(claim_id, BILLING))
        assert resubmitted["status"] == "READY"
        assert resubmitted["resubmission_count"] == 1
        assert resubmitted["denial_reason"] is None
        assert resubmitted["charge_cents"] == 80000, \
            "resubmission must not recompute charge_cents"
        get_success_data(api.submit_claim(claim_id, BILLING))
        paid = get_success_data(api.record_claim_payment(
            claim_id, {"paid_amount_cents": 80000}, BILLING))
        assert paid["status"] == "PAID"
        assert paid["paid_amount_cents"] == 80000

    def test_resubmission_count_increments_on_each_denied_to_ready(self, api):
        """PRD §3.7: "marking a claim ready moves `DRAFT → READY` (or, on
        resubmission, `DENIED → READY`)".
        PRD §3.7: "A resubmitted claim increments `resubmission_count` by one
        and clears `denial_reason` to null, without recomputing its charge."

        Design: Difficulty/non_linear_state_machine/claim_denial_resubmission_loop
        """
        ctx = setup_locked_roster_with_ready_claim(
            provider_type="ANESTHESIOLOGIST", procedure_code="P100",
            base_units=5, scheduled_start_minute=540, scheduled_end_minute=600)
        claim_id = ctx["claim"]["id"]
        # First pass: DRAFT -> READY is not a resubmission.
        assert ctx["claim"]["resubmission_count"] == 0
        get_success_data(api.submit_claim(claim_id, BILLING))
        get_success_data(api.record_claim_denial(
            claim_id, {"denial_reason": "TIMELY_FILING"}, BILLING))
        first_loop = get_success_data(api.mark_claim_ready(claim_id, BILLING))
        assert first_loop["resubmission_count"] == 1
        get_success_data(api.submit_claim(claim_id, BILLING))
        get_success_data(api.record_claim_denial(
            claim_id, {"denial_reason": "SECOND_DENIAL"}, BILLING))
        second_loop = get_success_data(api.mark_claim_ready(claim_id, BILLING))
        assert second_loop["resubmission_count"] == 2, (
            f"each DENIED -> READY pass increments resubmission_count, got "
            f"{second_loop['resubmission_count']}")
        assert second_loop["denial_reason"] is None


class TestClaimDenialConservesFiscalFields:
    def _paid_path_to_submitted(self, api):
        """P600 base 6; actual 75 min -> 5.0 time units -> 11.0 units;
        PERSONAL 88000. Claim submitted, ready for settlement."""
        ctx = setup_locked_roster_with_ready_claim(
            provider_type="ANESTHESIOLOGIST", procedure_code="P600",
            base_units=6, scheduled_start_minute=540, scheduled_end_minute=600,
            start_iso="2026-08-10T09:00:00Z", end_iso="2026-08-10T10:15:00Z")
        claim = ctx["claim"]
        assert claim["charge_cents"] == 88000
        assert claim["units_total"] == 11.0
        assert claim["modifier_code"] == "PERSONAL"
        get_success_data(api.submit_claim(claim["id"], BILLING))
        return ctx

    def test_denial_then_resubmission_leaves_fiscal_triple_unchanged(self, api):
        """PRD §3.7: "A resubmitted claim increments `resubmission_count` by
        one and clears `denial_reason` to null, without recomputing its
        charge."
        PRD §3.7: "recording a denial moves it to `DENIED` and stores the
        supplied `denial_reason`".

        Design: Difficulty/compensating_invariant/claim_denial_resubmission_conserves_fiscal_fields
        """
        ctx = self._paid_path_to_submitted(api)
        claim_id = ctx["claim"]["id"]
        denied = get_success_data(api.record_claim_denial(
            claim_id, {"denial_reason": "TIMELY_FILING"}, BILLING))
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "TIMELY_FILING"
        resubmitted = get_success_data(api.mark_claim_ready(claim_id, BILLING))
        assert resubmitted["status"] == "READY"
        assert resubmitted["denial_reason"] is None
        assert resubmitted["resubmission_count"] == 1
        assert resubmitted["charge_cents"] == 88000
        assert resubmitted["units_total"] == 11.0
        assert resubmitted["modifier_code"] == "PERSONAL"

    def test_denial_round_trip_moves_only_lifecycle_fields(self, api):
        """PRD §3.7: "manual creation requires the case to be `COMPLETED` ...
        and it recomputes `modifier_code`, `units_total`, and `charge_cents`
        identically to the completion cascade" — while resubmission acts
        "without recomputing its charge."

        Design: Difficulty/compensating_invariant/claim_denial_resubmission_conserves_fiscal_fields
        """
        ctx = self._paid_path_to_submitted(api)
        claim_id = ctx["claim"]["id"]
        before = get_success_data(api.get_claim(claim_id, BILLING))
        get_success_data(api.record_claim_denial(
            claim_id, {"denial_reason": "TIMELY_FILING"}, BILLING))
        after = get_success_data(api.mark_claim_ready(claim_id, BILLING))
        for field in ("charge_cents", "units_total", "modifier_code",
                      "case_id", "provider_id"):
            assert after[field] == before[field], (
                f"fiscal field {field} must survive the denial/resubmission "
                f"round trip ({before[field]} != {after[field]})")
        # Lifecycle fields are the only movers.
        assert after["resubmission_count"] == before["resubmission_count"] + 1
        assert after["status"] == "READY"
