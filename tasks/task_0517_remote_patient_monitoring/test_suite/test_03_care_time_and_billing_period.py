"""Care-time accounting: provisional vs finalized totals, the daily cap, and the
period version that the finalize OCC guard watches.

Covers difficulty rules dual_variant_calc (care-time divergence) and
combinatorial_formula (daily-cap waterfall), plus corner claims for the computed
billing-period read, immediate consistency, and per-mutation version increments.
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_care_activity_payload, create_billing_period_payload,
    finalize_payload, TEST_USERS, set_clock,
    setup_enrolled_patient, create_billing_period, log_care_activity,
)

CLIN = TEST_USERS["clinician_headers"]
BILL = TEST_USERS["billing_specialist_headers"]


def test_provisional_total_reflects_only_activities_logged_so_far(api):
    """PRD §2.8: "The **provisional** view, `provisional_total_minutes`, is a running
    figure recomputed every time a care-management activity is logged into an open
    period; it reflects only the activities present so far and is never frozen."

    Design: Difficulty/dual_variant_calc/care_time_provisional_vs_finalized_diverges_on_billing_period
    """
    ctx = setup_enrolled_patient(mrn="M-DV-1", consent_type="BOTH")
    pid = ctx["patient"]["id"]
    period = create_billing_period(pid, 2026, 6)
    set_clock("2026-06-10T00:00:00Z")
    log_care_activity(pid, period["id"], 12, "2026-06-05T09:00:00Z", clinician_user_id="clin-1")
    bp = get_success_data(api.get_billing_period(period["id"], BILL))
    assert bp["provisional_total_minutes"] == 12, "provisional reflects only the first activity"


def test_finalized_total_freezes_sum_over_all_activities(api):
    """PRD §2.8: "The **finalized** view, `finalized_total_minutes`, is computed exactly
    once at finalize-time, over the activities then present, and is thereafter frozen
    — it starts as null and remains null until the period reaches `FINALIZED`."
    PRD §3.7: "The period total is the sum of `counted_minutes` over all care activities
    whose `performed_at` falls within the billing month and whose `billing_period_id`
    is the period."

    Design: Difficulty/dual_variant_calc/care_time_provisional_vs_finalized_diverges_on_billing_period
    """
    ctx = setup_enrolled_patient(mrn="M-DV-2", consent_type="BOTH")
    pid = ctx["patient"]["id"]
    period = create_billing_period(pid, 2026, 6)
    set_clock("2026-06-10T00:00:00Z")
    log_care_activity(pid, period["id"], 12, "2026-06-05T09:00:00Z", clinician_user_id="clin-1")
    log_care_activity(pid, period["id"], 8, "2026-06-06T09:00:00Z", clinician_user_id="clin-1")
    log_care_activity(pid, period["id"], 10, "2026-06-07T09:00:00Z", clinician_user_id="clin-1")
    bp = get_success_data(api.get_billing_period(period["id"], BILL))
    assert bp["provisional_total_minutes"] == 30, "provisional after all three activities"
    set_clock("2026-07-01T00:00:00Z")
    fin = validate_success(
        api.finalize_billing_period(period["id"], finalize_payload(bp["version"]), BILL), 200)
    assert fin["status"] == "FINALIZED"
    assert fin["finalized_total_minutes"] == 30, "finalized total over all three (12+8+10)"


def test_daily_cap_waterfall_allocates_in_performed_at_order(api):
    """PRD §3.7: "When a day's logged minutes exceed 60, the 60-minute allowance is
    allocated to that day's activities in ascending `performed_at` order, with ties
    broken by ascending `created_at`, filling the earliest activities first; once the
    day's allowance is exhausted, later activities on that day receive zero
    `counted_minutes`."

    Design: Difficulty/combinatorial_formula/care_time_daily_cap_ordered_allocation
    """
    ctx = setup_enrolled_patient(mrn="M-CAP-1", consent_type="BOTH")
    pid = ctx["patient"]["id"]
    period = create_billing_period(pid, 2026, 6)
    set_clock("2026-06-12T00:00:00Z")
    ca1 = log_care_activity(pid, period["id"], 30, "2026-06-03T09:00:00Z", clinician_user_id="clin-1")
    ca2 = log_care_activity(pid, period["id"], 25, "2026-06-03T11:00:00Z", clinician_user_id="clin-1")
    ca3 = log_care_activity(pid, period["id"], 20, "2026-06-03T14:00:00Z", clinician_user_id="clin-1")
    assert ca1["counted_minutes"] == 30, "earliest gets full 30"
    assert ca2["counted_minutes"] == 25, "second gets full 25 (30+25=55 <= 60)"
    assert ca3["counted_minutes"] == 5, "third gets only the remaining 5 of the 60-min cap"


def test_daily_cap_period_total_is_sixty(api):
    """PRD §3.7: "Each activity's `counted_minutes` is derived under a per-calendar-day
    cap of 60 minutes."
    PRD §3.7: "After each care-activity create the system recomputes and writes the
    period's `provisional_total_minutes` over the rows present so far (the provisional
    view of §2.8)."

    Design: Difficulty/combinatorial_formula/care_time_daily_cap_ordered_allocation
    """
    ctx = setup_enrolled_patient(mrn="M-CAP-2", consent_type="BOTH")
    pid = ctx["patient"]["id"]
    period = create_billing_period(pid, 2026, 6)
    set_clock("2026-06-12T00:00:00Z")
    log_care_activity(pid, period["id"], 30, "2026-06-03T09:00:00Z", clinician_user_id="clin-1")
    log_care_activity(pid, period["id"], 25, "2026-06-03T11:00:00Z", clinician_user_id="clin-1")
    log_care_activity(pid, period["id"], 20, "2026-06-03T14:00:00Z", clinician_user_id="clin-1")
    bp = get_success_data(api.get_billing_period(period["id"], BILL))
    assert bp["provisional_total_minutes"] == 60, "30+25+5 capped to the 60-min daily allowance"


def test_care_activity_returns_counted_minutes_in_same_response(api):
    """PRD §2.6: "the system applies all such cascades immediately and consistently."
    PRD §3.7: "Each activity's `counted_minutes` is derived under a per-calendar-day
    cap of 60 minutes."

    Design: Corner/consistency_model/immediate_consistency_provisional_visible_same_request
    """
    ctx = setup_enrolled_patient(mrn="M-CM1-1", consent_type="BOTH")
    pid = ctx["patient"]["id"]
    period = create_billing_period(pid, 2026, 6)
    set_clock("2026-06-12T00:00:00Z")
    ca = validate_success(api.create_care_activity(
        pid, create_care_activity_payload(period["id"], "clin-14", 15, "2026-06-04T10:00:00Z"),
        CLIN), 201)
    assert ca["counted_minutes"] == 15, "single 15-min activity counts in full, returned immediately"


def test_billing_period_summary_read_shows_live_provisional(api):
    """PRD §2.8: "The **provisional** view, `provisional_total_minutes`, is a running
    figure recomputed every time a care-management activity is logged into an open
    period."
    PRD §3.8: "A new period begins with `status` of `OPEN`, `provisional_total_minutes`
    of 0, `distinct_device_days` of 0."

    Design: Corner/endpoints/computed_read_billing_period_summary
    """
    ctx = setup_enrolled_patient(mrn="M-EP3-1", consent_type="BOTH")
    pid = ctx["patient"]["id"]
    period = create_billing_period(pid, 2026, 6)
    set_clock("2026-06-12T00:00:00Z")
    log_care_activity(pid, period["id"], 28, "2026-06-04T10:00:00Z", clinician_user_id="clin-11")
    bp = validate_success(api.get_billing_period(period["id"], BILL), 200)
    assert bp["provisional_total_minutes"] == 28
    assert bp["distinct_device_days"] == 0, "no vitals transmitted, so zero device-days"


def test_period_version_increments_on_each_care_activity(api):
    """PRD §2.4: "`version` — an integer that begins at its initial value and increments
    by one on every mutation."
    PRD §3.7: "After each care-activity create the system recomputes and writes the
    period's `provisional_total_minutes` over the rows present so far ..., mutating the
    period and incrementing `BillingPeriod.version`."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_period_mutation
    """
    ctx = setup_enrolled_patient(mrn="M-CC1-1", consent_type="BOTH")
    pid = ctx["patient"]["id"]
    period = create_billing_period(pid, 2026, 6)
    assert period["version"] == 1, "version begins at 1 on create"
    set_clock("2026-06-12T00:00:00Z")
    log_care_activity(pid, period["id"], 15, "2026-06-04T10:00:00Z", clinician_user_id="clin-13")
    bp = get_success_data(api.get_billing_period(period["id"], BILL))
    assert bp["version"] == 2, "one care-activity recompute bumps version to 2"
