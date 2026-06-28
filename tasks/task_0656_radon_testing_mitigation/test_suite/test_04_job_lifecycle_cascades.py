"""Mitigation-job non-linear lifecycle (RETEST_PENDING→REWORK→SCHEDULED loop),
the warranty's parallel coverage × claim dimensions, and the multi-entity
clear/open-claim cascades.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_installed_job, setup_cleared_job_with_warranty,
    place_post_mitigation_retest, set_clock, get_property,
    create_radon_test_payload, retrieve_short_term_payload, schedule_payload,
    create_payment_payload, create_crew,
    make_inspector_headers, make_client_contact_headers,
    DESIGNER, COMPLIANCE, TEST_USERS,
)


def test_failing_retest_drives_rework_then_reschedule_back_to_scheduled(api):
    """PRD §3.3: "an `ACTION_RECOMMENDED` result drives the job's
    `RETEST_PENDING → REWORK` transition."
    PRD §3.5: "A `MitigationDesigner` schedules a job out of `REWORK` back to
    `SCHEDULED` using the same schedule action."

    Design: Difficulty/non_linear_state_machine/nlsm_job_retest_rework_reschedule_cycle
    """
    inspector, prop, _, job, crew, _ = setup_installed_job(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    # POST_MITIGATION retest reads high (5.0 >= 4.0) → drives REWORK.
    post = place_post_mitigation_retest(prop, inspector, job["id"], lab_result=5.0)
    assert post["action_outcome"] == "ACTION_RECOMMENDED"
    job_after = validate_success(api.get_mitigation_job(job["id"], DESIGNER), 200)
    assert job_after["status"] == "REWORK"

    prop_now = get_property(prop["id"])
    rescheduled = validate_success(api.schedule_job(
        job["id"],
        schedule_payload(crew["id"], "2026-04-05T08:00:00Z",
                         "2026-04-05T12:00:00Z", prop_now["version"]),
        DESIGNER), 200)
    assert rescheduled["status"] == "SCHEDULED"


def test_rework_reschedule_requires_no_additional_deposit(api):
    """PRD §3.5: "No additional deposit is required, because rework is free under
    the guarantee."

    Design: Difficulty/non_linear_state_machine/nlsm_job_retest_rework_reschedule_cycle
    """
    inspector, prop, _, job, crew, _ = setup_installed_job(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    deposit_before = validate_success(
        api.get_mitigation_job(job["id"], DESIGNER), 200)["deposit_paid_cents"]
    place_post_mitigation_retest(prop, inspector, job["id"], lab_result=5.0)
    prop_now = get_property(prop["id"])
    rescheduled = validate_success(api.schedule_job(
        job["id"],
        schedule_payload(crew["id"], "2026-04-05T08:00:00Z",
                         "2026-04-05T12:00:00Z", prop_now["version"]),
        DESIGNER), 200)
    assert rescheduled["status"] == "SCHEDULED"
    # No extra deposit was charged for the rework reschedule.
    assert rescheduled["deposit_paid_cents"] == deposit_before
    assert deposit_before == 45000


def _arm_recurring_high_retest(api, inspector, prop, warranty, schedule):
    """Advance to a RECURRING retest reading 2.5 (>= ceiling 2.0) so the
    property's latest_result qualifies a claim."""
    insp = make_inspector_headers(inspector["id"])
    client = make_client_contact_headers(prop["id"])
    # Fire the due retest at 2028-04-03 (>= next_due 2028-04-02). The fire places
    # a fresh RECURRING test with a 48h placement window, so advance the clock
    # +48h to 2028-04-05 before retrieving it.
    set_clock("2028-04-03T00:00:00Z")
    validate_success(api.fire_due(schedule["id"], COMPLIANCE), 200)
    rec_tests = api.list_radon_tests(
        insp, params={"property_id": prop["id"], "purpose": "RECURRING"}).json()["data"]
    rec = rec_tests[0]
    set_clock("2028-04-05T00:00:00Z")
    validate_success(
        api.retrieve_radon_test(rec["id"], retrieve_short_term_payload(2.5), insp), 200)
    get_success_data(api.record_result(rec["id"], insp))


def test_open_claim_advances_claim_dimension_coverage_stays_active(api):
    """PRD §3.6: "Opening a claim leaves `coverage_status` untouched but sets the
    parent mitigation job to `REWORK`, because the guarantee triggers a free
    re-mitigation, and it advances the warranty `version`."

    Design: Difficulty/non_linear_state_machine/nlsm_warranty_parallel_coverage_and_claim_dimensions
    """
    inspector, prop, job, warranty, schedule, _ = setup_cleared_job_with_warranty(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    _arm_recurring_high_retest(api, inspector, prop, warranty, schedule)
    client = make_client_contact_headers(prop["id"])
    opened = validate_success(api.open_claim(warranty["id"], client), 200)
    assert opened["claim_status"] == "CLAIM_OPEN"
    assert opened["coverage_status"] == "ACTIVE"


def test_open_claim_forces_parent_job_to_rework(api):
    """PRD §3.6: "Opening a claim leaves `coverage_status` untouched but sets the
    parent mitigation job to `REWORK`, because the guarantee triggers a free
    re-mitigation, and it advances the warranty `version`."

    Design: Difficulty/non_linear_state_machine/nlsm_warranty_parallel_coverage_and_claim_dimensions
    """
    inspector, prop, job, warranty, schedule, _ = setup_cleared_job_with_warranty(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    _arm_recurring_high_retest(api, inspector, prop, warranty, schedule)
    client = make_client_contact_headers(prop["id"])
    validate_success(api.open_claim(warranty["id"], client), 200)
    job_after = validate_success(api.get_mitigation_job(job["id"], DESIGNER), 200)
    assert job_after["status"] == "REWORK"


def test_clearing_retest_issues_warranty_and_arms_schedule(api):
    """PRD §3.5: "Clearing sets `retest_passed` to true and fans out a
    depth-three cascade: it issues a `Warranty` (with `coverage_status` `ACTIVE`
    and `claim_status` `NONE`) that snapshots `covered_system_price_cents` from
    the job's `quote_total_cents`, `term_days` from `warranty_term_days`,
    `guarantee_ceiling_pci_l` from `warranty_guarantee_ceiling_pci_l`, and
    `refund_method` from `warranty_refund_method`, and stamps `started_at_utc`
    from the logical clock."

    Design: Difficulty/transitive_cascade/tc_clear_job_issues_warranty_arms_schedule_depth3
    """
    inspector, prop, job, warranty, schedule, _ = setup_cleared_job_with_warranty(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    assert job["status"] == "CLEARED"
    assert job["retest_passed"] is True
    assert warranty["coverage_status"] == "ACTIVE"
    assert warranty["claim_status"] == "NONE"
    # The post-mit result was recorded at the 48h-advanced clock (2026-04-03).
    assert warranty["started_at_utc"].startswith("2026-04-03T00:00:00")


def test_clearing_cascade_arms_schedule_and_clears_property(api):
    """PRD §3.5: "warranty issuance in turn arms a `RetestSchedule` with
    `interval_days` taken from `retest_interval_days` and `next_due_utc` set to
    the warranty's `started_at_utc` plus `interval_days` days; and finally the
    property posture is set to `CLEARED`."

    Design: Difficulty/transitive_cascade/tc_clear_job_issues_warranty_arms_schedule_depth3
    """
    inspector, prop, job, warranty, schedule, _ = setup_cleared_job_with_warranty(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    assert schedule["status"] == "ARMED"
    # started_at 2026-04-03 + 730 days = 2028-04-02.
    assert schedule["next_due_utc"].startswith("2028-04-02T00:00:00")
    prop_now = get_property(prop["id"])
    assert prop_now["posture"] == "CLEARED"


def test_open_claim_depth2_cascade_to_job_rework(api):
    """PRD §3.6: "A `ClientContact` opens a guarantee claim, moving `claim_status`
    from `NONE` to `CLAIM_OPEN`, provided the coverage is still live."
    PRD §3.6: "Opening a claim leaves `coverage_status` untouched but sets the
    parent mitigation job to `REWORK`, because the guarantee triggers a free
    re-mitigation, and it advances the warranty `version`."

    Design: Difficulty/transitive_cascade/tc_open_claim_forces_job_rework_depth2
    """
    inspector, prop, job, warranty, schedule, _ = setup_cleared_job_with_warranty(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    _arm_recurring_high_retest(api, inspector, prop, warranty, schedule)
    client = make_client_contact_headers(prop["id"])
    opened = validate_success(api.open_claim(warranty["id"], client), 200)
    assert opened["claim_status"] == "CLAIM_OPEN"
    job_after = validate_success(api.get_mitigation_job(job["id"], DESIGNER), 200)
    assert job_after["status"] == "REWORK"


def test_open_claim_depth2_leaves_coverage_active(api):
    """PRD §3.6: "Opening a claim leaves `coverage_status` untouched but sets the
    parent mitigation job to `REWORK`, because the guarantee triggers a free
    re-mitigation, and it advances the warranty `version`."

    Design: Difficulty/transitive_cascade/tc_open_claim_forces_job_rework_depth2
    """
    inspector, prop, job, warranty, schedule, _ = setup_cleared_job_with_warranty(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    _arm_recurring_high_retest(api, inspector, prop, warranty, schedule)
    client = make_client_contact_headers(prop["id"])
    opened = validate_success(api.open_claim(warranty["id"], client), 200)
    assert opened["coverage_status"] == "ACTIVE"
    assert opened["claim_status"] == "CLAIM_OPEN"
