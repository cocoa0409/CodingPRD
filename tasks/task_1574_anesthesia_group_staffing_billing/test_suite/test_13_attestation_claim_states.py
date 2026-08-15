"""Attestation and claim state-machine gates: invalid transitions and
terminal lockdowns (PRD §3.5, §3.7)."""
from test_helpers import (
    BILLING,
    SCHED,
    ApiErrorId,
    all_tefra_steps_true,
    create_case,
    create_fee_schedule,
    create_physician,
    create_published_roster,
    create_site,
    get_success_data,
    make_physician_headers,
    setup_completed_solo_case,
    setup_locked_roster_with_ready_claim,
    setup_site_fee_roster,
    validate_error,
    api_client,
)


def _attestation_fixture(api):
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


class TestAttestationStateGates:
    def test_verify_before_submit_rejected(self, api):
        """PRD §3.5: "Both review actions require the attestation to be
        `SUBMITTED` (else `ERR_ATTESTATION_NOT_SUBMITTED`)."

        Design: Corner/state_machines/attestation_verify_before_submit_rejected
        """
        director, peer, att = _attestation_fixture(api)
        resp = api.verify_attestation(att["id"], make_physician_headers(peer["id"]))
        validate_error(resp, ApiErrorId.ERR_ATTESTATION_NOT_SUBMITTED)
        after = get_success_data(api.get_attestation(att["id"], SCHED))
        assert after["status"] == "IN_PROGRESS"

    def test_verified_terminal_submit_rejected(self, api):
        """PRD §3.5: "is available from either `IN_PROGRESS` or `REJECTED`
        (any other status yields `ERR_ATTESTATION_NOT_SUBMITTABLE`)."

        Design: Corner/state_machines/attestation_submit_after_verify_terminal_lockdown
        """
        director, peer, att = _attestation_fixture(api)
        get_success_data(api.submit_attestation(
            att["id"], all_tefra_steps_true(),
            make_physician_headers(director["id"])))
        get_success_data(api.verify_attestation(
            att["id"], make_physician_headers(peer["id"])))
        resp = api.submit_attestation(att["id"], all_tefra_steps_true(),
                                      make_physician_headers(director["id"]))
        validate_error(resp, ApiErrorId.ERR_ATTESTATION_NOT_SUBMITTABLE)

    def test_verified_terminal_verify_rejected(self, api):
        """PRD §3.5: "Verification moves `SUBMITTED → VERIFIED`, the terminal
        state".
        PRD §3.5: "Both review actions require the attestation to be
        `SUBMITTED` (else `ERR_ATTESTATION_NOT_SUBMITTED`)."

        Design: Corner/state_machines/attestation_submit_after_verify_terminal_lockdown
        """
        director, peer, att = _attestation_fixture(api)
        submitted = get_success_data(api.submit_attestation(
            att["id"], all_tefra_steps_true(),
            make_physician_headers(director["id"])))
        get_success_data(api.verify_attestation(
            att["id"], make_physician_headers(peer["id"])))
        resp = api.verify_attestation(att["id"], make_physician_headers(peer["id"]))
        validate_error(resp, ApiErrorId.ERR_ATTESTATION_NOT_SUBMITTED)
        after = get_success_data(api.get_attestation(att["id"], SCHED))
        assert after["status"] == "VERIFIED"
        assert after["submitted_count"] == submitted["submitted_count"]


class TestClaimInvalidTransitions:
    def test_submit_from_draft_rejected(self, api):
        """PRD §3.7: "a claim not `READY` is `ERR_CLAIM_NOT_SUBMITTABLE`."

        Design: Corner/state_machines/claim_invalid_transitions_rejected
        """
        ctx = setup_completed_solo_case(provider_type="ANESTHESIOLOGIST")
        get_success_data(api.lock_roster(ctx["roster"]["id"], SCHED))
        claim_id = ctx["claims"][0]["id"]
        resp = api.submit_claim(claim_id, BILLING)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SUBMITTABLE)

    def test_write_off_from_draft_rejected(self, api):
        """PRD §3.7: "Settlement actions against a claim that is not
        `SUBMITTED` — or a write-off against a claim that is neither
        `SUBMITTED` nor `DENIED` — are rejected with
        `ERR_CLAIM_NOT_SETTLABLE`."

        Design: Corner/state_machines/claim_invalid_transitions_rejected
        """
        ctx = setup_completed_solo_case(provider_type="ANESTHESIOLOGIST")
        get_success_data(api.lock_roster(ctx["roster"]["id"], SCHED))
        claim_id = ctx["claims"][0]["id"]
        resp = api.write_off_claim(claim_id, BILLING)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SETTLABLE)

    def test_record_payment_from_ready_rejected(self, api):
        """PRD §3.7: "Settlement actions against a claim that is not
        `SUBMITTED` — or a write-off against a claim that is neither
        `SUBMITTED` nor `DENIED` — are rejected with
        `ERR_CLAIM_NOT_SETTLABLE`."

        Design: Corner/state_machines/claim_invalid_transitions_rejected
        """
        ctx = setup_locked_roster_with_ready_claim(
            provider_type="ANESTHESIOLOGIST")
        resp = api.record_claim_payment(ctx["claim"]["id"],
                                        {"paid_amount_cents": 72000}, BILLING)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SETTLABLE)

    def test_mark_ready_from_submitted_rejected(self, api):
        """PRD §3.7: "Marking from any status other than `DRAFT` or `DENIED`
        is `ERR_CLAIM_NOT_READYABLE`."

        Design: Corner/state_machines/claim_invalid_transitions_rejected
        """
        ctx = setup_locked_roster_with_ready_claim(
            provider_type="ANESTHESIOLOGIST")
        claim_id = ctx["claim"]["id"]
        get_success_data(api.submit_claim(claim_id, BILLING))
        resp = api.mark_claim_ready(claim_id, BILLING)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_READYABLE)
        after = get_success_data(api.get_claim(claim_id, BILLING))
        assert after["status"] == "SUBMITTED"


class TestClaimPaidTerminalLockdown:
    def test_paid_claim_rejects_record_denial(self, api):
        """PRD §3.7: "`PAID` and `WRITTEN_OFF` are terminal".
        PRD §3.7: "Settlement actions against a claim that is not `SUBMITTED`
        — or a write-off against a claim that is neither `SUBMITTED` nor
        `DENIED` — are rejected with `ERR_CLAIM_NOT_SETTLABLE`."

        Design: Corner/state_machines/claim_paid_terminal_lockdown
        """
        ctx = setup_locked_roster_with_ready_claim(
            provider_type="ANESTHESIOLOGIST")
        claim_id = ctx["claim"]["id"]
        get_success_data(api.submit_claim(claim_id, BILLING))
        get_success_data(api.record_claim_payment(
            claim_id, {"paid_amount_cents": 72000}, BILLING))
        resp = api.record_claim_denial(claim_id, {"denial_reason": "TOO_LATE"},
                                       BILLING)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SETTLABLE)

    def test_paid_claim_rejects_write_off(self, api):
        """PRD §3.7: "`PAID` and `WRITTEN_OFF` are terminal".
        PRD §3.7: "Settlement actions against a claim that is not `SUBMITTED`
        — or a write-off against a claim that is neither `SUBMITTED` nor
        `DENIED` — are rejected with `ERR_CLAIM_NOT_SETTLABLE`."

        Design: Corner/state_machines/claim_paid_terminal_lockdown
        """
        ctx = setup_locked_roster_with_ready_claim(
            provider_type="ANESTHESIOLOGIST")
        claim_id = ctx["claim"]["id"]
        get_success_data(api.submit_claim(claim_id, BILLING))
        paid = get_success_data(api.record_claim_payment(
            claim_id, {"paid_amount_cents": 72000}, BILLING))
        assert paid["status"] == "PAID"
        resp = api.write_off_claim(claim_id, BILLING)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SETTLABLE)
        after = get_success_data(api.get_claim(claim_id, BILLING))
        assert after["status"] == "PAID"
        assert after["paid_amount_cents"] == 72000
