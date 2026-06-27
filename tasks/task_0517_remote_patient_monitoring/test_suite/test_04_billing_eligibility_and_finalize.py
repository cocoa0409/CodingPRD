"""Billing-period finalization: CPT eligibility, the device-day and care-time floors,
the 99453 setup accrual, and the temporal / state guards on finalize.

Covers difficulty rules boundary_precision_check (nothing-to-claim) and the
finalize side of priority_pair_validation_conflict, plus corner claims for the
99454 device-day floor, the once-per-device 99453 accrual, the finalize-before-month
guard, and the device-day-bump endpoint side effect.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    get_success_data, create_vitals_payload, finalize_payload, TEST_USERS,
    ApiErrorId, set_clock,
    setup_enrolled_patient, setup_enrolled_patient_with_active_device,
    create_billing_period, create_device, activate_device,
    transmit_distinct_device_days, log_care_activity, finalize_period,
    setup_finalized_eligible_period,
)

CLIN = TEST_USERS["clinician_headers"]
CC = TEST_USERS["care_coordinator_headers"]
BILL = TEST_USERS["billing_specialist_headers"]


def test_sixteen_device_days_accrues_99454(api):
    """PRD §3.8: "The 99454 device-supply unit is eligible if and only if
    `distinct_device_days` is at least 16 — exactly 16 distinct days qualifies, 15 does
    not."
    PRD §3.8: "For each eligible code the system creates a `BillingLineItem` with
    `cpt_code` set to `CPT_99454` or `CPT_99457` respectively, `units` of 1, and
    `amount_cents` snapshotting the payer's rate for that code (`rate_99454_cents` or
    `rate_99457_cents`)."

    Design: Corner/calculations/device_day_floor_16_accrues_99454
    """
    # 16 device-days, <20 care minutes -> 99454 accrues (plus in-period 99453), no 99457.
    ctx = setup_finalized_eligible_period(
        mrn="M-CA1-1", serial_number="SN-CA1-1", device_type="BP_CUFF",
        care_minutes=0, device_day_count=16, device_day_start=1)
    period = ctx["finalized_period"]
    assert period["distinct_device_days"] == 16
    items = get_success_data(api.list_line_items(ctx["period"]["id"], BILL))
    by_code = {it["cpt_code"]: it for it in items}
    assert "CPT_99454" in by_code, "16 device-days accrues a 99454 line item"
    assert by_code["CPT_99454"]["amount_cents"] == 4774
    assert "CPT_99457" not in by_code, "under 20 care minutes -> no 99457"
    # in-period 99453 (1965) + 99454 (4774) = 6739
    assert period["finalized_total_cents"] == 6739


def test_device_activation_in_open_period_accrues_one_99453(api):
    """PRD §3.4: "if the device's `setup_billed` is still false, the system resolves the
    patient's `OPEN` billing period for the activation month ... If such an open period
    exists, a billing line item is created with `cpt_code` of `CPT_99453`, `units` of 1,
    and `amount_cents` equal to the payer's `rate_99453_cents`, and `setup_billed` is set
    true so the device can never accrue a second setup charge."

    Design: Corner/calculations/setup_99453_accrued_once_per_device
    """
    ctx = setup_enrolled_patient(mrn="M-CA3-1", consent_type="RPM")
    pid = ctx["patient"]["id"]
    period = create_billing_period(pid, 2026, 6)
    set_clock("2026-06-05T00:00:00Z")
    device = create_device(pid, serial_number="SN-CA3-1")
    device = activate_device(pid, device["id"])
    assert device["setup_billed"] is True
    items = get_success_data(api.list_line_items(period["id"], BILL))
    setup_items = [it for it in items if it["cpt_code"] == "CPT_99453"]
    assert len(setup_items) == 1, "exactly one 99453 accrued on activation"
    assert setup_items[0]["amount_cents"] == 1965


def test_nothing_to_claim_when_zero_eligible_line_items(api):
    """PRD §3.9: "A period whose `finalized_total_cents` is zero — no eligible CPT line
    items — cannot be claimed, and the attempt is refused with `ERR_NOTHING_TO_CLAIM`."
    PRD §3.8: "The 99454 device-supply unit is eligible if and only if
    `distinct_device_days` is at least 16 — exactly 16 distinct days qualifies, 15 does
    not."
    PRD §3.8: "The 99457 care-management block is eligible if and only if
    `finalized_total_minutes` is at least 20 — exactly 20 minutes qualifies, 19 does not."

    Design: Difficulty/boundary_precision_check/nothing_to_claim_on_zero_eligible_line_items
    """
    # Device activated in a PRIOR month (May) so no in-period 99453; 15 device-days
    # (< 16) and 19 finalized minutes (< 20) => zero eligible line items.
    ctx = setup_enrolled_patient(mrn="M-B2-1", consent_type="BOTH",
                                 consent_effective_at="2026-04-01T00:00:00Z",
                                 payer_overrides={"requires_active_consent": False})
    pid = ctx["patient"]["id"]
    set_clock("2026-05-15T00:00:00Z", CC)
    device = create_device(pid, serial_number="SN-B2-1")
    device = activate_device(pid, device["id"])  # May activation: no June 99453
    period = create_billing_period(pid, 2026, 6)
    set_clock("2026-06-20T00:00:00Z")
    log_care_activity(pid, period["id"], 19, "2026-06-02T10:00:00Z", clinician_user_id="clin-4")
    transmit_distinct_device_days(pid, device["id"], 15, year=2026, month=6, start_day=1)
    set_clock("2026-07-01T00:00:00Z")
    fin = finalize_period(period["id"])
    assert fin["finalized_total_cents"] == 0, "no eligible CPT line items"
    resp = api.submit_claim(period["id"], BILL)
    validate_error(resp, ApiErrorId.ERR_NOTHING_TO_CLAIM.value)


def test_fifteen_device_days_and_nineteen_minutes_accrue_zero_cents(api):
    """PRD §3.8: "The 99454 device-supply unit is eligible if and only if
    `distinct_device_days` is at least 16 — exactly 16 distinct days qualifies, 15 does
    not."
    PRD §3.8: "The 99457 care-management block is eligible if and only if
    `finalized_total_minutes` is at least 20 — exactly 20 minutes qualifies, 19 does not."

    Design: Difficulty/boundary_precision_check/nothing_to_claim_on_zero_eligible_line_items
    """
    ctx = setup_enrolled_patient(mrn="M-B2-2", consent_type="BOTH",
                                 consent_effective_at="2026-04-01T00:00:00Z",
                                 payer_overrides={"requires_active_consent": False})
    pid = ctx["patient"]["id"]
    set_clock("2026-05-15T00:00:00Z", CC)
    device = create_device(pid, serial_number="SN-B2-2")
    device = activate_device(pid, device["id"])  # May activation: no June 99453
    period = create_billing_period(pid, 2026, 6)
    set_clock("2026-06-20T00:00:00Z")
    log_care_activity(pid, period["id"], 19, "2026-06-02T10:00:00Z", clinician_user_id="clin-4b")
    transmit_distinct_device_days(pid, device["id"], 15, year=2026, month=6, start_day=1)
    set_clock("2026-07-01T00:00:00Z")
    fin = finalize_period(period["id"])
    assert fin["distinct_device_days"] == 15, "15 device-days is below the 16 floor"
    assert fin["finalized_total_minutes"] == 19, "19 minutes is below the 20 floor"
    assert fin["finalized_total_cents"] == 0, "neither floor met -> zero eligible cents"
    items = get_success_data(api.list_line_items(period["id"], BILL))
    assert items == [], "no CPT line items accrued"


def test_finalize_before_month_elapsed_rejected(api):
    """PRD §3.8: "requires that the calendar month identified by `period_year` and
    `period_month` has fully elapsed relative to the logical clock — finalizing before
    the month has closed is refused with `ERR_PERIOD_NOT_CLOSED`."

    Design: Corner/validations/finalize_before_month_elapsed_rejected
    """
    payer = get_success_data(api.create_payer(
        {"name": "P-V3", "payer_type": "MEDICARE", "rate_99453_cents": 1965,
         "rate_99454_cents": 4774, "rate_99457_cents": 4877}, BILL))
    patient = get_success_data(api.create_patient(
        {"payer_id": payer["id"], "mrn": "M-V3-1", "full_name": "Val Three"}, CC))
    period = create_billing_period(patient["id"], 2026, 6)
    set_clock("2026-06-20T00:00:00Z")  # month not yet elapsed
    bp = get_success_data(api.get_billing_period(period["id"], BILL))
    resp = api.finalize_billing_period(period["id"], finalize_payload(bp["version"]), BILL)
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CLOSED.value)


def test_finalize_claimed_period_with_current_version_is_invalid_state(api):
    """PRD §3.8: "Finalization seals the month. It requires the period to be `OPEN`."
    PRD §2.5: "State-transition legality (`ERR_INVALID_STATE`) is evaluated ... when the
    target entity is not in a state from which the requested transition is defined."

    Design: Difficulty/priority_pair_validation_conflict/finalize_invalid_state_beats_stale_version
    """
    # Reach CLAIMED, then finalize again with the period's CURRENT (correct) version so
    # only the state precondition can fail -> ERR_INVALID_STATE is uniquely derivable.
    ctx = setup_finalized_eligible_period(
        mrn="M-FS-A", serial_number="SN-FS-A", device_type="BP_CUFF",
        care_minutes=20, device_day_count=0)
    period_id = ctx["period"]["id"]
    get_success_data(api.submit_claim(period_id, BILL))  # -> CLAIMED
    claimed = get_success_data(api.get_billing_period(period_id, BILL))
    assert claimed["status"] == "CLAIMED"
    resp = api.finalize_billing_period(period_id, finalize_payload(claimed["version"]), BILL)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_finalize_claimed_period_with_stale_version_state_or_occ(api):
    """PRD §3.8: "Finalization seals the month. It requires the period to be `OPEN`."
    PRD §2.7: "The finalize request must carry `expected_billing_period_version` ... The
    server compares it to the period's current `version`. If they differ, the finalize is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    The PRD lists both requirements without committing to which is checked first when a
    CLAIMED period is finalized with a stale version, so either error is faithful.

    Design: Difficulty/priority_pair_validation_conflict/finalize_invalid_state_beats_stale_version
    """
    ctx = setup_finalized_eligible_period(
        mrn="M-FS-B", serial_number="SN-FS-B", device_type="BP_CUFF",
        care_minutes=20, device_day_count=0)
    period_id = ctx["period"]["id"]
    # Capture a version from BEFORE the final claim mutation -> stale once CLAIMED.
    stale_version = ctx["finalized_period"]["version"]
    get_success_data(api.submit_claim(period_id, BILL))  # bumps version, -> CLAIMED
    resp = api.finalize_billing_period(period_id, finalize_payload(stale_version), BILL)
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_STALE_VERSION.value])


def test_non_breaching_vitals_bumps_distinct_device_day(api):
    """PRD §3.5: "The system recomputes the period's `distinct_device_days` — the count
    of distinct `service_date` values across the patient's devices within the period's
    month — and when a transmission introduces a new device-day, the period is mutated
    and `BillingPeriod.version` increments."
    PRD §2.9: "If the reading enters any breach band the system sets `breach_flag` to
    true; otherwise it is false."

    Design: Corner/endpoints/vitals_breach_creates_alert_and_bumps_device_day
    """
    ctx = setup_enrolled_patient(mrn="M-EP2-1", consent_type="RPM")
    pid = ctx["patient"]["id"]
    period = create_billing_period(pid, 2026, 6)
    set_clock("2026-06-05T00:00:00Z")
    device = create_device(pid, serial_number="SN-EP2-1")
    activate_device(pid, device["id"])
    reading = validate_success(api.create_vitals(
        pid, create_vitals_payload(device["id"], 118, "2026-06-05T08:00:00Z",
                                   secondary_value=76), CLIN), 201)
    assert reading["breach_flag"] is False
    bp = get_success_data(api.get_billing_period(period["id"], BILL))
    assert bp["distinct_device_days"] == 1, "one device-day after one transmission"
    alerts = get_success_data(api.list_alerts(CLIN, params={"patient_id": pid}))
    assert alerts == [], "non-breaching reading creates no alert"
