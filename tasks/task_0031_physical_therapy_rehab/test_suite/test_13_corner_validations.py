"""Corner Coverage — validations section.

Capped POC blocks finalize; goals-inconsistent referential; recert-window;
visit-out-of-window; VA visit-cap.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    set_clock,
    setup_active_va_poc,
    setup_poc_with_grant,
    setup_recert_due_poc,
    setup_active_poc,
    create_grant,
    schedule_visit,
    complete_visit,
    finalize_visit,
    create_visit_payload,
    create_discharge_assessment_payload,
    recertify_plan_payload,
    finalize_visit_payload,
    make_therapist_headers,
    TEST_USERS,
)


def test_capped_poc_exceeded_blocks_visit_finalize(api):
    """PRD §3.5: "the plan's `capped_status` is not `EXCEEDED` at the instant of finalize
    (otherwise `ERR_CAPPED_POC_EXCEEDED` is raised with HTTP 409)."

    Setup: drive MEDICARE POC (cap=20000¢) past EXCEEDED, then attempt to finalize a
    further COMPLETED visit.

    Design: Corner/validations/capped_poc_exceeded_blocks_visit_finalize
    """
    ctx = setup_poc_with_grant(
        insurance_type="MEDICARE", medicare_enrolled=True,
        total_units_granted=60,
    )
    gid = ctx["grant"]["id"]
    th = ctx["therapist"]["id"]
    poc_id = ctx["poc"]["id"]
    # MEDICARE cap = 20000¢ (PRD §2.7). Each 90-minute CPT_97110 visit bills
    # 11200¢ (6 units: 3200 + 5×1600). Two finalizes total 22400¢ > 20000 → EXCEEDED.
    # The third finalize at the same priority would be blocked by the EXCEEDED gate
    # — which is the assertion under test — so only two finalizes are used in setup.
    for date in ("2026-06-02", "2026-06-03"):
        v = schedule_visit(
            gid, th, f"{date}T09:00:00Z", f"{date}T10:30:00Z",
            planned_minutes=90, cpt_code="CPT_97110_THER_EX",
        )
        complete_visit(v["id"], th, actual_minutes=90)
        finalize_visit(v["id"], poc_id)
    poc_excd = get_success_data(api.get_plan_of_care(poc_id, TEST_USERS["billing_clerk_headers"]))
    assert poc_excd["capped_status"] == "EXCEEDED"
    # Third visit: schedule + complete → finalize should be rejected.
    v3 = schedule_visit(
        gid, th, "2026-06-04T09:00:00Z", "2026-06-04T09:30:00Z",
        planned_minutes=30, cpt_code="CPT_97110_THER_EX",
    )
    complete_visit(v3["id"], th, actual_minutes=30)
    poc_v = get_success_data(api.get_plan_of_care(poc_id, TEST_USERS["billing_clerk_headers"]))["version"]
    res = api.finalize_visit(
        v3["id"], finalize_visit_payload(expected_plan_of_care_version=poc_v),
        TEST_USERS["billing_clerk_headers"],
    )
    validate_error(res, "ERR_CAPPED_POC_EXCEEDED", expected_status=409)


def test_discharge_assessment_goals_inconsistent(api):
    """PRD §3.8: "A payload where `goals_met_count` exceeds `total_goals_count` is
    rejected with `ERR_GOALS_INCONSISTENT` (HTTP 422)."

    Design: Corner/validations/discharge_assessment_goals_inconsistent
    """
    ctx = setup_active_poc(insurance_type="COMMERCIAL")
    res = api.create_discharge_assessment(
        create_discharge_assessment_payload(
            plan_of_care_id=ctx["poc"]["id"],
            assessing_therapist_id=ctx["therapist"]["id"],
            final_functional_score=70,
            goals_met_count=8,
            total_goals_count=5,  # goals_met > total_goals → inconsistent
            assessed_on="2026-06-15",
        ),
        make_therapist_headers(ctx["therapist"]["id"]),
    )
    validate_error(res, "ERR_GOALS_INCONSISTENT", expected_status=422)


def test_recertify_window_exceeds_90_days_returns_error(api):
    """PRD §3.6: "the new `certified_end_date` must be on or before the old
    `certified_end_date` plus ninety days (a violation surfaces
    `ERR_RECERT_WINDOW_EXCEEDED` with HTTP 422)."

    Design: Corner/validations/recertify_window_exceeds_90_days_returns_error
    """
    ctx = setup_recert_due_poc(
        certified_start_date="2026-06-01",
        certified_end_date="2026-06-08",
    )
    th = ctx["therapist"]["id"]
    # Old end = 2026-06-08, +90 days = 2026-09-06. New end 2026-12-31 exceeds.
    payload = recertify_plan_payload(
        expected_plan_of_care_version=ctx["poc"]["version"],
        certified_start_date="2026-06-01",
        certified_end_date="2026-12-31",
    )
    res = api.recertify_plan_of_care(ctx["poc"]["id"], payload, make_therapist_headers(th))
    validate_error(res, "ERR_RECERT_WINDOW_EXCEEDED", expected_status=422)


def test_visit_out_of_window_rejected_outside_grant_dates(api):
    """PRD §3.5: "both `scheduled_start_utc` and `scheduled_end_utc` must fall within
    both the grant's `[effective_from, effective_to]` window and the parent plan's
    `[certified_start_date, certified_end_date]` window; a visit that escapes either
    window is rejected with `ERR_VISIT_OUT_OF_WINDOW` (HTTP 422)."

    Design: Corner/validations/visit_out_of_window_rejected_outside_grant_dates
    """
    ctx = setup_active_poc(
        insurance_type="COMMERCIAL",
        certified_start_date="2026-06-01",
        certified_end_date="2026-07-31",
    )
    grant = create_grant(
        ctx["poc"]["id"], total_units_granted=10,
        effective_from="2026-06-15", effective_to="2026-07-15",
    )
    # Visit on 2026-06-10 is BEFORE grant.effective_from=2026-06-15 → out of window.
    res = api.create_visit(
        create_visit_payload(
            authorization_grant_id=grant["id"],
            therapist_id=ctx["therapist"]["id"],
            scheduled_start_utc="2026-06-10T09:00:00Z",
            scheduled_end_utc="2026-06-10T10:00:00Z",
            planned_minutes=60, cpt_code="CPT_97110_THER_EX",
        ),
        make_therapist_headers(ctx["therapist"]["id"]),
    )
    validate_error(res, "ERR_VISIT_OUT_OF_WINDOW", expected_status=422)


def test_va_visit_cap_exceeded_after_max_visits(api):
    """PRD §3.5: "when the parent patient's plan is backed by a veteran referral, the
    count of visits already linked through any grant to that referral plus this new
    visit must not exceed the referral's `max_authorized_visits`; a violation surfaces
    `ERR_VA_VISIT_CAP_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/va_visit_cap_exceeded_after_max_visits
    """
    ctx = setup_active_va_poc(
        is_veteran=True,
        max_authorized_visits=1,
        referral_expires_on="2026-12-31",
    )
    grant = create_grant(
        ctx["poc"]["id"], total_units_granted=10,
        effective_from="2026-06-01", effective_to="2026-07-31",
        veteran_referral_id=ctx["referral"]["id"],
    )
    th = ctx["therapist"]["id"]
    # First visit is fine (count goes 0 → 1, equals cap).
    v1 = schedule_visit(grant["id"], th, "2026-06-05T09:00:00Z",
                        "2026-06-05T09:30:00Z", planned_minutes=30,
                        cpt_code="CPT_97110_THER_EX")
    assert v1["status"] == "SCHEDULED"
    # Second visit exceeds the referral cap of 1.
    res = api.create_visit(
        create_visit_payload(
            authorization_grant_id=grant["id"],
            therapist_id=th,
            scheduled_start_utc="2026-06-06T09:00:00Z",
            scheduled_end_utc="2026-06-06T09:30:00Z",
            planned_minutes=30, cpt_code="CPT_97110_THER_EX",
        ),
        make_therapist_headers(th),
    )
    validate_error(res, "ERR_VA_VISIT_CAP_EXCEEDED", expected_status=409)
