"""Transitive cascade chains: enrollment discharge -> plan closure -> visit cancellation
-> slot release, and flagged med-reconciliation -> plan revision -> enrollment flags."""
from test_helpers import (
    setup_enrollment_with_active_plan, setup_med_rec_pending,
    schedule_home_visit, refetch_program, refetch_enrollment,
    refetch_care_plan, refetch_home_visit,
)


def test_discharge_cascades_plan_closure_and_visit_cancellation(api):
    """PRD 3.8: "It also drives the full closure cascade of Section 2.10: each care plan on
    the enrollment that is in DRAFT, ACTIVE, or UNDER_REVISION is transitioned to CLOSED, and
    each such closure in turn cancels that plan's still-SCHEDULED home visits."

    Design: Difficulty/transitive_cascade/discharge_closes_plan_cancels_visit_releases_provider
    """
    ctx = setup_enrollment_with_active_plan(api)
    org, enr_id, cp_id = ctx["org"], ctx["enrollment_id"], ctx["care_plan_id"]
    hv = schedule_home_visit(api, org, enr_id, cp_id,
                             "2026-03-10T10:00:00Z", "2026-03-10T11:00:00Z")
    api.discharge_enrollment(enr_id, org["coord_headers"])
    assert refetch_enrollment(api, org, enr_id)["status"] == "DISCHARGED"
    assert refetch_care_plan(api, org, cp_id)["status"] == "CLOSED"
    assert refetch_home_visit(api, org, hv["id"])["status"] == "CANCELLED"


def test_discharge_releases_program_slot(api):
    """PRD 3.8: "Discharge ... releases the program slot by decrementing the program's
    active_enrollment_count and recomputing remaining_slots."
    A discharge of the only enrollment returns active_enrollment_count to 0.

    Design: Difficulty/transitive_cascade/discharge_closes_plan_cancels_visit_releases_provider
    """
    ctx = setup_enrollment_with_active_plan(api)
    org, enr_id, cp_id = ctx["org"], ctx["enrollment_id"], ctx["care_plan_id"]
    schedule_home_visit(api, org, enr_id, cp_id,
                        "2026-03-10T10:00:00Z", "2026-03-10T11:00:00Z")
    api.discharge_enrollment(enr_id, org["coord_headers"])
    program = refetch_program(api, org)
    assert program["active_enrollment_count"] == 0, (
        f"expected active_enrollment_count 0, got {program['active_enrollment_count']}")


def test_flagged_med_rec_sends_active_plan_under_revision(api):
    """PRD 3.6: "A FLAGGED outcome moves it PENDING_REVIEW -> FLAGGED and triggers the safety
    cascade: the enrollment's single ACTIVE care plan (there is at most one) is sent ACTIVE
    -> UNDER_REVISION, which - as in Section 3.4 - increments the enrollment's revision_count
    and sets needs_review to true."

    Design: Difficulty/transitive_cascade/medrec_flag_revises_plan_flags_enrollment
    """
    ctx = setup_med_rec_pending(api)
    org, mr_id, cp_id = ctx["org"], ctx["med_reconciliation_id"], ctx["care_plan_id"]
    resp = api.review_med_reconciliation(mr_id, {"review_outcome": "FLAGGED"}, org["clin_headers"])
    assert resp.status_code == 200, f"review failed: {resp.status_code} {resp.text}"
    assert refetch_care_plan(api, org, cp_id)["status"] == "UNDER_REVISION"


def test_flagged_med_rec_flags_enrollment_needs_review(api):
    """PRD 3.6: "the enrollment's single ACTIVE care plan ... is sent ACTIVE -> UNDER_REVISION,
    which - as in Section 3.4 - increments the enrollment's revision_count and sets
    needs_review to true."

    Design: Difficulty/transitive_cascade/medrec_flag_revises_plan_flags_enrollment
    """
    ctx = setup_med_rec_pending(api)
    org, mr_id, enr_id = ctx["org"], ctx["med_reconciliation_id"], ctx["enrollment_id"]
    api.review_med_reconciliation(mr_id, {"review_outcome": "FLAGGED"}, org["clin_headers"])
    enrollment = refetch_enrollment(api, org, enr_id)
    assert enrollment["needs_review"] is True, "needs_review must be set true on flag cascade"
    assert enrollment["revision_count"] == 1, (
        f"expected revision_count 1, got {enrollment['revision_count']}")
