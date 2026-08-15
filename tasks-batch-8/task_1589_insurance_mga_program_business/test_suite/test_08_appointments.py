"""TPA appointments: closed-window 30-day gap rule, window-closed gating,
suspend/revoke referral cascades, reinstatement, and expiry via run-daily."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_appointment,
    create_carrier,
    create_claim_under_review,
    create_issued_policy,
    create_program,
    create_tpa,
    get_claim_fresh,
    make_carrier_underwriter_headers,
    make_tpa_adjuster_headers,
    report_claim,
    run_daily,
    set_clock,
    setup_active_program,
    setup_program_with_issued_policy_and_tpa,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["mga_underwriter_headers"]


class TestAppointmentGapRule:
    def test_gap_29_days_rejected_30_days_accepted(self, api):
        """PRD §3.6: "Activation (`PENDING → ACTIVE`) requires ... a
        thirty-day separation from every other appointment of the same
        program, claim type, and TPA in `ACTIVE` or `SUSPENDED` status: the
        new window must begin at least thirty days after the other's
        `effective_to` ... Any smaller separation — including windows that
        merely abut — is a conflict rejected with
        `ERR_APPOINTMENT_WINDOW_GAP`."

        Design: Difficulty/resource_temporal_overlap/appointment_gap_closed_interval_buffer
        """
        carrier, program, _g, _a, _f = setup_active_program()
        tpa = create_tpa()
        cu = make_carrier_underwriter_headers(carrier["id"])
        appt_a = create_active_appointment(
            program, tpa, effective_from="2026-08-01T00:00:00Z",
            effective_to="2027-08-01T00:00:00Z")

        # B starts 29 days after A's end -> conflict.
        appt_b = validate_success(api.create_appointment(program["id"], {
            "tpa_id": tpa["id"], "claim_type": "LIABILITY",
            "authority_limit_cents": 50000,
            "effective_from": "2027-08-30T00:00:00Z",
            "effective_to": "2028-08-01T00:00:00Z"}, cu), expected_status=201)
        conflict = api.activate_appointment(appt_b["id"], cu)
        validate_error(conflict, ApiErrorId.ERR_APPOINTMENT_WINDOW_GAP)
        fresh_b = validate_success(api.get_appointment(appt_b["id"], cu))
        assert fresh_b["status"] == "PENDING"

        # C starts exactly 30 days after A's end -> accepted.
        appt_c = validate_success(api.create_appointment(program["id"], {
            "tpa_id": tpa["id"], "claim_type": "LIABILITY",
            "authority_limit_cents": 60000,
            "effective_from": "2027-08-31T00:00:00Z",
            "effective_to": "2028-08-01T00:00:00Z"}, cu), expected_status=201)
        activated = validate_success(api.activate_appointment(appt_c["id"], cu))
        assert activated["status"] == "ACTIVE", "gap boundary is inclusive at 30 days"

    def test_gap_rule_scoped_per_tpa(self, api):
        """PRD §3.6: "a thirty-day separation from every other appointment of
        the same program, claim type, and TPA" and "Distinct TPAs, however,
        may hold concurrent `ACTIVE` appointments for the same scope; the
        claim-time selector ranks among them."

        Design: Difficulty/resource_temporal_overlap/appointment_gap_closed_interval_buffer
        """
        carrier, program, _g, _a, _f = setup_active_program()
        tpa_a = create_tpa()
        tpa_b = create_tpa()
        create_active_appointment(
            program, tpa_a, effective_from="2026-08-01T00:00:00Z",
            effective_to="2027-08-01T00:00:00Z")
        # Same scope, overlapping window, but a DIFFERENT TPA: no gap conflict.
        appt_b = create_active_appointment(
            program, tpa_b, authority_limit_cents=80000,
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2027-08-01T00:00:00Z")
        assert appt_b["status"] == "ACTIVE"


class TestAppointmentWindowClosed:
    def test_activate_after_effective_to_rejected(self, api):
        """PRD §3.6: "Activation (`PENDING → ACTIVE`) requires ... the clock
        to be no later than `effective_to` (`ERR_APPOINTMENT_WINDOW_CLOSED`)."

        Design: Corner/validations/appointment_activate_after_window_closed_rejected
        """
        carrier = create_carrier()
        program = create_program(carrier)
        tpa = create_tpa()
        cu = make_carrier_underwriter_headers(carrier["id"])
        appt = validate_success(api.create_appointment(program["id"], {
            "tpa_id": tpa["id"], "claim_type": "LIABILITY",
            "authority_limit_cents": 100000,
            "effective_from": "2026-08-01T00:00:00Z",
            "effective_to": "2026-08-15T00:00:00Z"}, cu), expected_status=201)

        set_clock("2026-08-16T00:00:00Z")
        resp = api.activate_appointment(appt["id"], cu)
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_WINDOW_CLOSED)
        fresh = validate_success(api.get_appointment(appt["id"], cu))
        assert fresh["status"] == "PENDING"


class TestAppointmentSuspensionCascade:
    def test_suspended_appointment_blocks_start_review_until_reinstated(self, api):
        """PRD §3.6: "Starting review moves `REPORTED → UNDER_REVIEW` and
        requires the appointment under which the claim was assigned to be
        `ACTIVE`, failing with `ERR_APPOINTMENT_NOT_ACTIVE` otherwise."
        PRD §3.6: "Reinstating (`SUSPENDED → ACTIVE`) requires the program to
        be `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE`) and the appointment window
        still open (`ERR_APPOINTMENT_WINDOW_CLOSED`)."

        Design: Difficulty/cross_entity_state_dependency/claim_review_requires_appointment_active
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa()
        claim = report_claim(policy, occurrence_date="2026-08-10T00:00:00Z",
                             amount_claimed_cents=50000)
        cu = make_carrier_underwriter_headers(carrier["id"])
        tpa_h = make_tpa_adjuster_headers(tpa["id"])

        validate_success(api.suspend_appointment(appt["id"], cu))
        blocked = api.start_claim_review(claim["id"], tpa_h)
        validate_error(blocked, ApiErrorId.ERR_APPOINTMENT_NOT_ACTIVE)
        assert get_claim_fresh(claim["id"])["status"] == "REPORTED"

        validate_success(api.reinstate_appointment(appt["id"], cu))
        started = validate_success(api.start_claim_review(claim["id"], tpa_h))
        assert started["status"] == "UNDER_REVIEW"

    def test_suspend_refers_under_review_claims(self, api):
        """PRD §3.6: "Suspending (`ACTIVE → SUSPENDED`) — by direct carrier
        action or by the program-suspension cascade of §2.10 — refers every
        claim assigned to that TPA in `UNDER_REVIEW` to `REFERRED` with
        `referral_reason` recorded as `APPOINTMENT_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/claim_review_requires_appointment_active
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa()
        claim = create_claim_under_review(program, policy, tpa,
                                          occurrence_date="2026-08-10T00:00:00Z",
                                          amount_claimed_cents=50000)
        cu = make_carrier_underwriter_headers(carrier["id"])
        suspended = validate_success(api.suspend_appointment(appt["id"], cu))
        assert suspended["status"] == "SUSPENDED"

        fresh = get_claim_fresh(claim["id"])
        assert fresh["status"] == "REFERRED"
        assert fresh["referral_reason"] == "APPOINTMENT_SUSPENDED"

    def test_revoke_refers_under_review_claims(self, api):
        """PRD §3.6: "Revoking an appointment (from `ACTIVE` or `SUSPENDED` to
        `REVOKED`) is terminal: claims still in `REPORTED` under that TPA
        remain `REPORTED` but can never start review
        (`ERR_APPOINTMENT_NOT_ACTIVE`), and revoking from `ACTIVE` additionally
        refers its `UNDER_REVIEW` claims to `REFERRED` with
        `APPOINTMENT_SUSPENDED` as the reason."

        Design: Corner/state_machines/appointment_revoke_refers_under_review_claims
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa()
        claim = create_claim_under_review(program, policy, tpa,
                                          occurrence_date="2026-08-01T00:00:00Z",
                                          amount_claimed_cents=30000)
        cu = make_carrier_underwriter_headers(carrier["id"])
        revoked = validate_success(api.revoke_appointment(appt["id"], cu))
        assert revoked["status"] == "REVOKED"

        fresh = get_claim_fresh(claim["id"])
        assert fresh["status"] == "REFERRED"
        assert fresh["referral_reason"] == "APPOINTMENT_SUSPENDED"


class TestAppointmentExpiry:
    def test_run_daily_expires_appointment_and_flags_overdue_bordereau(self, api):
        """PRD §2.5: "expires every appointment in `ACTIVE` whose
        `effective_to` has passed (moving it to `EXPIRED`); and flags every
        bordereau still in `DRAFT` whose `due_date` has passed by setting its
        `overdue` flag to true. The run's response enumerates exactly what it
        touched, as `cancelled_policy_ids`, `expired_policy_ids`,
        `withdrawn_quote_ids`, `expired_appointment_ids`, and
        `flagged_bordereau_ids`."

        Design: Corner/endpoints/run_daily_flags_overdue_bordereau_and_expires_appointment
        """
        carrier, program, _g, _a, _f = setup_active_program()
        tpa = create_tpa()
        appt = create_active_appointment(
            program, tpa, effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-12-31T00:00:00Z")
        bor = validate_success(api.create_bordereau(program["id"], {
            "bordereau_type": "PREMIUM", "period_label": "2026-08",
            "due_date": "2026-09-15T00:00:00Z"}, TEST_USERS["mga_finance_headers"]),
            expected_status=201)

        set_clock("2027-01-05T00:00:00Z")
        result = run_daily()
        assert appt["id"] in result["expired_appointment_ids"]
        assert bor["id"] in result["flagged_bordereau_ids"]

        fresh_appt = validate_success(api.get_appointment(
            appt["id"], make_carrier_underwriter_headers(carrier["id"])))
        assert fresh_appt["status"] == "EXPIRED"
        fresh_bor = validate_success(api.get_bordereau(
            bor["id"], TEST_USERS["mga_finance_headers"]))
        assert fresh_bor["overdue"] is True
        assert fresh_bor["status"] == "DRAFT", "overdue is a flag, not a transition"
