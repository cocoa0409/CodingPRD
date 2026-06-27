"""Temporal and interval guards on periods, claims, and care activities: month
overlap, consent containment, timely filing, and out-of-period activities.

Covers difficulty rule resource_temporal_overlap (both instances), plus corner
claims for timely-filing expiry and out-of-period care activities.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId, set_clock,
    create_payer, create_patient, create_billing_period,
    setup_enrolled_patient, setup_finalized_eligible_period, log_care_activity,
    create_care_plan, activate_care_plan, create_consent, create_device,
    activate_device, finalize_period,
)

CC = TEST_USERS["care_coordinator_headers"]
CLIN = TEST_USERS["clinician_headers"]
BILL = TEST_USERS["billing_specialist_headers"]


def test_duplicate_billing_period_same_month_rejected(api):
    """PRD §3.8: "A new period must not collide with an existing non-`REOPENED` period
    for the same patient on the same year-and-month ... and two periods collide when
    their month intervals are identical. A collision is refused with `ERR_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/duplicate_billing_period_same_month_rejected
    """
    payer = create_payer(name="P-OV1")
    patient = create_patient(payer["id"], mrn="M-OV1-1")
    create_billing_period(patient["id"], 2026, 6)
    resp = api.create_billing_period(patient["id"], {"period_year": 2026, "period_month": 6}, BILL)
    validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP.value)


def test_distinct_month_billing_period_allowed(api):
    """PRD §3.8: "A new period must not collide with an existing non-`REOPENED` period
    for the same patient on the same year-and-month ... two periods collide when their
    month intervals are identical."

    Design: Difficulty/resource_temporal_overlap/duplicate_billing_period_same_month_rejected
    """
    payer = create_payer(name="P-OV1b")
    patient = create_patient(payer["id"], mrn="M-OV1-2")
    create_billing_period(patient["id"], 2026, 6)
    # A different month does not collide.
    other = validate_success(
        api.create_billing_period(patient["id"], {"period_year": 2026, "period_month": 7}, BILL), 201)
    assert other["period_month"] == 7
    assert other["status"] == "OPEN"


def test_billing_consent_gap_when_consent_starts_mid_month(api):
    """PRD §3.9: "if the payer's `requires_active_consent` is set, an `ACTIVE` consent
    interval running from its `effective_at` up to but not including its `revoked_at`
    must fully contain the billing month: a consent whose `effective_at` is after the
    month start, or whose `revoked_at` is before the month end, leaves an uncovered gap
    and the submission is refused with `ERR_BILLING_CONSENT_GAP`."

    Design: Difficulty/resource_temporal_overlap/billing_consent_gap_when_consent_starts_mid_month
    """
    payer = create_payer(name="P-OV2", requires_active_consent=True)
    patient = create_patient(payer["id"], mrn="M-OV2-1")
    create_consent(patient["id"], consent_type="BOTH", effective_at="2026-06-15T00:00:00Z")
    plan = create_care_plan(patient["id"])
    activate_care_plan(patient["id"], plan["id"])
    set_clock("2026-06-16T00:00:00Z", CC)
    get_success_data(api.enroll_patient(patient["id"], CC))
    period = create_billing_period(patient["id"], 2026, 6)
    device = create_device(patient["id"], serial_number="SN-OV2-1")
    activate_device(patient["id"], device["id"])
    log_care_activity(patient["id"], period["id"], 20, "2026-06-16T10:00:00Z",
                      clinician_user_id="clin-5")
    set_clock("2026-07-01T00:00:00Z")
    finalize_period(period["id"])
    resp = api.submit_claim(period["id"], BILL)
    validate_error(resp, ApiErrorId.ERR_BILLING_CONSENT_GAP.value)


def test_billing_consent_gap_leaves_period_unclaimed(api):
    """PRD §3.9: "if the payer's `requires_active_consent` is set, an `ACTIVE` consent
    interval running from its `effective_at` up to but not including its `revoked_at`
    must fully contain the billing month: a consent whose `effective_at` is after the
    month start ... leaves an uncovered gap and the submission is refused with
    `ERR_BILLING_CONSENT_GAP`."
    PRD §3.9: "A claim may only be submitted on a `FINALIZED` period."

    Design: Difficulty/resource_temporal_overlap/billing_consent_gap_when_consent_starts_mid_month
    """
    payer = create_payer(name="P-OV2b", requires_active_consent=True)
    patient = create_patient(payer["id"], mrn="M-OV2-2")
    create_consent(patient["id"], consent_type="BOTH", effective_at="2026-06-15T00:00:00Z")
    plan = create_care_plan(patient["id"])
    activate_care_plan(patient["id"], plan["id"])
    set_clock("2026-06-16T00:00:00Z", CC)
    get_success_data(api.enroll_patient(patient["id"], CC))
    period = create_billing_period(patient["id"], 2026, 6)
    device = create_device(patient["id"], serial_number="SN-OV2-2")
    activate_device(patient["id"], device["id"])
    log_care_activity(patient["id"], period["id"], 20, "2026-06-16T10:00:00Z",
                      clinician_user_id="clin-5b")
    set_clock("2026-07-01T00:00:00Z")
    finalize_period(period["id"])
    # The period is finalized with eligible cents, so the refusal is specifically the
    # consent gap (not nothing-to-claim); the period must stay FINALIZED, no claim made.
    resp = api.submit_claim(period["id"], BILL)
    validate_error(resp, ApiErrorId.ERR_BILLING_CONSENT_GAP.value)
    after = get_success_data(api.get_billing_period(period["id"], BILL))
    assert after["status"] == "FINALIZED", "rejected submission leaves the period FINALIZED"
    claims = get_success_data(api.list_period_claims(period["id"], BILL))
    assert claims == [], "no Claim created when the consent gap blocks submission"


def test_timely_filing_expired_claim_rejected(api):
    """PRD §3.9: "The claim's submission instant must fall within the payer's
    `timely_filing_days` of the period's last calendar day, otherwise it is refused with
    `ERR_TIMELY_FILING_EXPIRED`."

    Design: Corner/validations/timely_filing_expired_claim_rejected
    """
    ctx = setup_finalized_eligible_period(
        payer_overrides={"requires_active_consent": False, "timely_filing_days": 90},
        mrn="M-V5-1", serial_number="SN-V5-1", device_type="BP_CUFF",
        care_minutes=20, device_day_count=0)
    # 2026-10-01 is more than 90 days after the period's last day (2026-06-30).
    set_clock("2026-10-01T00:00:00Z")
    resp = api.submit_claim(ctx["period"]["id"], BILL)
    validate_error(resp, ApiErrorId.ERR_TIMELY_FILING_EXPIRED.value)


def test_care_activity_out_of_period_rejected(api):
    """PRD §3.7: "The `performed_at` instant must fall inside the billing period's
    calendar month, otherwise the log is refused with `ERR_ACTIVITY_OUT_OF_PERIOD`."

    Design: Corner/validations/care_activity_out_of_period_rejected
    """
    ctx = setup_enrolled_patient(mrn="M-V4-1", consent_type="BOTH")
    pid = ctx["patient"]["id"]
    period = create_billing_period(pid, 2026, 6)
    set_clock("2026-06-10T00:00:00Z")
    resp = api.create_care_activity(
        pid,
        {"billing_period_id": period["id"], "clinician_user_id": "clin-8",
         "activity_type": "REVIEW", "minutes": 10, "performed_at": "2026-05-30T10:00:00Z"},
        CLIN)
    validate_error(resp, ApiErrorId.ERR_ACTIVITY_OUT_OF_PERIOD.value)
