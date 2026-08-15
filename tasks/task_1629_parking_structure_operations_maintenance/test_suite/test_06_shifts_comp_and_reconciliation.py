"""Shifts, cash control, comps, refunds, and reconciliation theft controls."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    close_shift_payload,
    create_facility,
    create_shift_payload,
    enter_vehicle,
    enter_vehicle_at,
    get_facility,
    get_success_data,
    make_gate_device_headers,
    open_shift,
    pay_session_cash,
    quote_session_at,
    set_clock,
    setup_card_settled_session,
    setup_closed_shift_with_recon,
    setup_entry_ready_facility,
    setup_shift_with_cash_settlement,
    setup_variance_review_recon,
    validate_error,
    validate_paginated,
    validate_success,
)

FM = TEST_USERS["facility_manager_headers"]
ATT = TEST_USERS["parking_attendant_headers"]  # X-User-ID "att-1"
ATT2 = build_user_headers("att-2", "ParkingAttendant")
AUD = TEST_USERS["revenue_auditor_headers"]  # X-User-ID "aud-1"


def test_pay_cash_without_shift_rejected(api):
    """PRD: "Payment in `CASH` additionally requires a `shift_id` naming an
    `OPEN` shift at the same facility whose `attendant_user_id` equals the
    caller — otherwise `ERR_SHIFT_NOT_OPEN`."

    Design: Corner/errors/pay_cash_without_shift_rejected
    """
    facility, schedule, gate = setup_entry_ready_facility(name="PS Fac")
    session = enter_vehicle_at(facility["id"], gate, "PS-1", "2026-08-01T10:00:00Z")
    set_clock("2026-08-01T11:00:00Z")
    res = api.pay_session(session["id"], {"tender_type": "CASH"}, ATT)
    validate_error(res, ApiErrorId.ERR_SHIFT_NOT_OPEN)
    after = get_success_data(api.get_parking_session(session["id"], FM))
    assert after["billing_state"] == "OPEN"


def test_shift_already_open_per_attendant(api):
    """PRD: "One attendant holds at most one `OPEN` shift per facility — a
    second open attempt fails with `ERR_SHIFT_ALREADY_OPEN`."

    Design: Corner/validations/shift_already_open_per_attendant
    """
    facility = create_facility(name="SO Fac")
    open_shift(facility["id"], attendant_headers=ATT)
    res = api.create_shift(create_shift_payload(facility["id"], opening_float_cents=5000),
                           ATT)
    validate_error(res, ApiErrorId.ERR_SHIFT_ALREADY_OPEN)
    second = validate_success(api.create_shift(
        create_shift_payload(facility["id"], opening_float_cents=5000), ATT2), 201)
    assert second["shift_status"] == "OPEN", "constraint is per attendant, not per facility"


def test_comp_cap_enforced_at_shift_level(api):
    """PRD: "it is capped: the shift's `comp_total_cents` plus the fee being
    waived must not exceed a per-shift ceiling of 5,000 cents, or the request
    fails with `ERR_COMP_LIMIT_EXCEEDED` (HTTP 422)."
    PRD: "the shift's `comp_total_cents` grows by the waived fee's value."

    Design: Corner/calculations/comp_cap_enforced_at_shift_level
    """
    facility, schedule, gate = setup_entry_ready_facility(name="CC Fac")
    shift = open_shift(facility["id"])
    set_clock("2026-08-01T09:00:00Z")
    s1 = enter_vehicle(facility["id"], gate, "CC-1")
    s2 = enter_vehicle(facility["id"], gate, "CC-2")
    set_clock("2026-08-01T16:30:00Z")
    s3 = enter_vehicle(facility["id"], gate, "CC-3")
    set_clock("2026-08-01T18:00:00Z")
    get_success_data(api.comp_session(s1["id"], {"reason": "VIP", "shift_id": shift["id"]}, ATT))
    get_success_data(api.comp_session(s2["id"], {"reason": "VIP", "shift_id": shift["id"]}, ATT))

    res = api.comp_session(s3["id"], {"reason": "VIP", "shift_id": shift["id"]}, ATT)
    validate_error(res, ApiErrorId.ERR_COMP_LIMIT_EXCEEDED)

    shift_after = get_success_data(api.get_shift(shift["id"], FM))
    assert shift_after["comp_total_cents"] == 4800, (
        "two 9h comps waived 2400 each (capped at daily max)")
    s3_after = get_success_data(api.get_parking_session(s3["id"], FM))
    assert s3_after["billing_state"] == "OPEN", "rejected comp leaves billing untouched"


def test_refund_exceeds_collected_rejected(api):
    """PRD: "The amount must not exceed the session's `settled_fee_cents`,
    else the refund fails with `ERR_REFUND_EXCEEDS_COLLECTED` (HTTP 422)."

    Design: Corner/validations/refund_exceeds_collected_rejected
    """
    facility, schedule, gate, session = setup_card_settled_session(name="RE Fac")
    res = api.refund_session(session["id"], {"amount_cents": 600, "reason": "too much"}, AUD)
    validate_error(res, ApiErrorId.ERR_REFUND_EXCEEDS_COLLECTED)
    after = get_success_data(api.get_parking_session(session["id"], FM))
    assert after["billing_state"] == "SETTLED"


class TestRefundOnRefundedSession:
    """State-vs-fiscal pair: refunding a REFUNDED session reports the state
    failure even when the amount also exceeds the settled figure."""

    def _build(self, api):
        facility, schedule, gate, session = setup_card_settled_session(name="PC1 Fac")
        refunded = get_success_data(api.refund_session(
            session["id"], {"amount_cents": 500, "reason": "full"}, AUD))
        assert refunded["billing_state"] == "REFUNDED"
        return facility, session

    def test_state_error_wins_over_amount_error(self, api):
        """PRD: "the target resource's current state permits the requested
        transition; this covers wrong-from-state actions, terminal-state
        lockdown, and repeat runs such as a second close-of-business for one
        business date, else `ERR_INVALID_STATE_TRANSITION`."
        PRD: "Only after all eleven generic stages pass do endpoint-specific
        business checks fire"

        Design: Difficulty/priority_pair_validation_conflict/refund_already_refunded_vs_amount_exceeds_state_wins
        """
        facility, session = self._build(api)
        res = api.refund_session(session["id"],
                                 {"amount_cents": 99999, "reason": "dual failure"}, AUD)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_refunded_state_preserved_after_rejected_retry(self, api):
        """PRD: "A recorded refund moves billing to the terminal `REFUNDED`,
        stores `refunded_cents` equal to the refunded amount, stamps
        `refunded_at`, and subtracts the amount from the facility's
        `cumulative_collected_cents` — the compensating pair to settlement."

        Design: Difficulty/priority_pair_validation_conflict/refund_already_refunded_vs_amount_exceeds_state_wins
        """
        facility, session = self._build(api)
        validate_error(api.refund_session(
            session["id"], {"amount_cents": 99999, "reason": "dual failure"}, AUD),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api.get_parking_session(session["id"], FM))
        assert after["billing_state"] == "REFUNDED"
        assert after["refunded_cents"] == 500


class TestPaySettledSessionWithBadShiftRef:
    """Existence-vs-state pair: a nonexistent shift_id on an already-SETTLED
    session reports the body-reference failure first."""

    def test_reference_not_found_wins_over_state(self, api):
        """PRD: "Identifiers carried in the request body — `facility_id`,
        `shift_id`, `agreement_id`, `charger_id`, `credential_id`,
        `inspection_id`, `patrol_round_id`, `reconciliation_id`,
        `duplicate_of_incident_id`, `incident_id`, and
        `supersedes_schedule_id` — must each name an existing resource, or the
        request fails with `ERR_REFERENCE_NOT_FOUND` (HTTP 404)"
        PRD: "Incoming requests are checked in a fixed pipeline order, and
        when several checks could fail, the earliest failure is the one
        reported."

        Design: Difficulty/priority_pair_validation_conflict/pay_nonexistent_shift_vs_already_settled_existence_wins
        """
        facility, schedule, gate, session = setup_card_settled_session(name="PC3 Fac")
        res = api.pay_session(
            session["id"], {"tender_type": "CASH", "shift_id": NON_EXISTENT_UUID}, ATT)
        validate_error(res, ApiErrorId.ERR_REFERENCE_NOT_FOUND)

    def test_settled_state_preserved_after_rejected_repay(self, api):
        """PRD: "On settlement the billing moves to `SETTLED`,
        `settled_fee_cents` records the computed amount, `tender_type` is
        stored"

        Design: Difficulty/priority_pair_validation_conflict/pay_nonexistent_shift_vs_already_settled_existence_wins
        """
        facility, schedule, gate, session = setup_card_settled_session(name="PC3 Fac")
        validate_error(api.pay_session(
            session["id"], {"tender_type": "CASH", "shift_id": NON_EXISTENT_UUID}, ATT),
            ApiErrorId.ERR_REFERENCE_NOT_FOUND)
        after = get_success_data(api.get_parking_session(session["id"], FM))
        assert after["billing_state"] == "SETTLED"
        assert after["settled_fee_cents"] == 500


class TestCashPayRefundConservation:
    """Settle CASH 500 then refund 500: both ledgers return to baseline."""

    def test_settle_grows_cumulative_collected(self, api):
        """PRD: "On settlement the billing moves to `SETTLED`,
        `settled_fee_cents` records the computed amount, `tender_type` is
        stored, the facility's `cumulative_collected_cents` grows by the
        settled amount"

        Design: Difficulty/compensating_invariant/cash_pay_then_refund_conserves_collected
        """
        facility, gate, shift, session = setup_shift_with_cash_settlement(
            name="Inv1 Fac", pay_at="2026-08-01T11:00:00Z")
        after = get_facility(facility["id"])
        assert after["cumulative_collected_cents"] == 500, "1h CASH settle of 500"

    def test_refund_restores_both_ledgers_to_baseline(self, api):
        """PRD: "A recorded refund moves billing to the terminal `REFUNDED`,
        stores `refunded_cents` equal to the refunded amount, stamps
        `refunded_at`, and subtracts the amount from the facility's
        `cumulative_collected_cents` — the compensating pair to settlement.
        When the refunded session had been settled in `CASH` and the
        collecting shift is not yet `RECONCILED`, that shift's expected-cash
        derivation loses the refunded amount"

        Design: Difficulty/compensating_invariant/cash_pay_then_refund_conserves_collected
        """
        facility, gate, shift, session = setup_shift_with_cash_settlement(
            name="Inv1 Fac", pay_at="2026-08-01T11:00:00Z")
        refunded = validate_success(api.refund_session(
            session["id"], {"amount_cents": 500, "reason": "chargeback avoidance"}, AUD), 200)
        assert refunded["billing_state"] == "REFUNDED"
        assert refunded["refunded_cents"] == 500

        after = get_facility(facility["id"])
        assert after["cumulative_collected_cents"] == 0, "invariant restored exactly"
        shift_after = get_success_data(api.get_shift(shift["id"], FM))
        assert shift_after["expected_cash_cents"] == 10000, (
            "float restored; refund applied because the shift is not RECONCILED")


def test_segregation_of_duties_submit_and_approve(api):
    """PRD: "Segregation of duties runs through the revenue chain: the auditor
    who opens, submits, or approves a reconciliation must differ from the
    attendant whose drawer is under review, and a violation is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/segregation_of_duties_submit_and_approve
    """
    # Clean variance: float 10000 + 500 cash fee (1h) = 10500 expected.
    facility, shift, session, recon = setup_closed_shift_with_recon(
        name="SD Fac", pay_at="2026-08-01T11:00:00Z", counted_cash_cents=10500)
    attendant_as_auditor = build_user_headers("att-1", "RevenueAuditor")

    res = api.submit_reconciliation(recon["id"], attendant_as_auditor)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    submitted = validate_success(api.submit_reconciliation(recon["id"], AUD), 200)
    assert submitted["reconciliation_status"] == "SUBMITTED"
    assert submitted["variance_cents"] == 0

    res = api.approve_reconciliation(recon["id"], {}, attendant_as_auditor)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestVarianceThresholdBoundary:
    """Exactly -2000 breaches (inclusive); -1999 stays auto-approvable."""

    def test_exactly_minus_2000_routes_to_variance_review(self, api):
        """PRD: "A variance at or below a shortage of 2,000 cents — exactly
        −2,000 breaches — or at or above an overage of 5,000 cents — exactly
        +5,000 breaches — routes the record to `VARIANCE_REVIEW`; anything
        strictly between those lines lands in `SUBMITTED`."
        PRD: "The `VARIANCE_REVIEW` route also auto-creates an incident: an
        `IncidentReport` of `incident_type` `CASH_VARIANCE` whose
        `reconciliation_id` names this record, `auto_created` true, standing
        `OPEN`, with severity `HIGH` when the absolute variance reaches 10,000
        cents and `MEDIUM` below that."

        Design: Difficulty/boundary_precision_check/variance_threshold_exactly_2000_triggers_review
        """
        # float 10000 + 2400 cash (9h capped) = 12400 expected; counted 10400.
        facility, shift, session, recon = setup_closed_shift_with_recon(
            name="Var Fac", counted_cash_cents=10400)
        submitted = validate_success(api.submit_reconciliation(recon["id"], AUD), 200)
        assert submitted["variance_cents"] == -2000
        assert submitted["reconciliation_status"] == "VARIANCE_REVIEW", (
            "inclusive boundary breaches")

        incidents, meta = validate_paginated(api.list_incidents(
            AUD, params={"reconciliation_id": recon["id"]}))
        assert len(incidents) == 1
        assert incidents[0]["incident_type"] == "CASH_VARIANCE"
        assert incidents[0]["auto_created"] is True
        assert incidents[0]["severity"] == "MEDIUM", "ABS 2000 < 10000"
        assert incidents[0]["incident_status"] == "OPEN"

    def test_minus_1999_stays_submitted_and_approvable(self, api):
        """PRD: "anything strictly between those lines lands in `SUBMITTED`."
        PRD: "Approving a `SUBMITTED` record moves it to the terminal
        `APPROVED` and moves its shift from `CLOSED` or `FORCE_CLOSED` to
        `RECONCILED`."

        Design: Difficulty/boundary_precision_check/variance_threshold_exactly_2000_triggers_review
        """
        # float 10000 + 500 cash (1h) = 10500 expected; counted 8501.
        facility, gate, shift, session = setup_shift_with_cash_settlement(
            name="Var2 Fac", pay_at="2026-08-01T11:00:00Z")
        closed = get_success_data(api.close_shift(
            shift["id"], close_shift_payload(8501), ATT))
        recon = get_success_data(api.create_reconciliation({"shift_id": shift["id"]}, AUD))

        submitted = validate_success(api.submit_reconciliation(recon["id"], AUD), 200)
        assert submitted["variance_cents"] == -1999
        assert submitted["reconciliation_status"] == "SUBMITTED", "-1999 > -2000"

        approved = validate_success(api.approve_reconciliation(recon["id"], {}, AUD), 200)
        assert approved["reconciliation_status"] == "APPROVED"
        shift_after = get_success_data(api.get_shift(shift["id"], FM))
        assert shift_after["shift_status"] == "RECONCILED"


def test_variance_review_approve_requires_investigating_incident(api):
    """PRD: "Approving from `VARIANCE_REVIEW` additionally requires an
    `incident_id` naming the linked incident — one whose `reconciliation_id`
    is this record, whose `incident_type` is `CASH_VARIANCE`, and whose
    `incident_status` stands `INVESTIGATING`; without it the approval fails
    with `ERR_VARIANCE_INCIDENT_REQUIRED`."

    Design: Corner/validations/variance_review_approve_requires_investigating_incident
    """
    facility, shift, recon, incident_id = setup_variance_review_recon(name="VR Fac")
    assert recon["reconciliation_status"] == "VARIANCE_REVIEW"
    get_success_data(api.investigate_incident(incident_id, AUD))
    res = api.approve_reconciliation(recon["id"], {}, AUD)
    validate_error(res, ApiErrorId.ERR_VARIANCE_INCIDENT_REQUIRED)


def test_variance_review_full_approval_path(api):
    """PRD: "That approval resolves the linked incident (`INVESTIGATING` to
    `RESOLVED`) in the same act and reconciles the shift."
    PRD: "Both `CLOSED` and `FORCE_CLOSED` reach the terminal `RECONCILED`
    only through an approved reconciliation."

    Design: Corner/validations/variance_review_full_approval_path
    """
    facility, shift, recon, incident_id = setup_variance_review_recon(name="VF Fac")
    get_success_data(api.investigate_incident(incident_id, AUD))
    approved = validate_success(api.approve_reconciliation(
        recon["id"], {"incident_id": incident_id}, AUD), 200)
    assert approved["reconciliation_status"] == "APPROVED"

    incident = get_success_data(api.get_incident(incident_id, AUD))
    assert incident["incident_status"] == "RESOLVED"
    shift_after = get_success_data(api.get_shift(shift["id"], FM))
    assert shift_after["shift_status"] == "RECONCILED"
