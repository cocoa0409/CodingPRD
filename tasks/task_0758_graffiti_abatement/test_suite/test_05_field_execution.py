"""Field execution: photos, start/complete gating, the completion cascade, and the
recall / cancel revision arms.

Queue A (Difficulty): non_linear_state_machine (revision cycle, recall fork),
transitive_cascade (completion depth-3 chain).
Queue B (Corner): validations (photo prerequisites), state_machines (terminal lockdown),
endpoints (nested photo listing).
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    setup_dispatched, setup_in_progress, setup_completed,
    create_photo_payload,
)

COORD = TEST_USERS["coordinator_headers"]


# --------------------------------------------------------------------------
# non_linear_state_machine / report_revision_cycle_in_progress_back_to_triaged
# --------------------------------------------------------------------------
def test_recall_returns_report_to_triaged(api):
    """PRD §3.4: "Recall is defined only while the work order is `IN_PROGRESS`; it accepts an optional
    `reason`, advances the work order `IN_PROGRESS → RECALLED`, and returns the report
    `IN_PROGRESS → TRIAGED` so it can be re-dispatched — the non-linear revision cycle that carries a
    report from `TRIAGED` through `DISPATCHED` and `IN_PROGRESS` back to `TRIAGED`."

    Design: Difficulty/non_linear_state_machine/report_revision_cycle_in_progress_back_to_triaged
    """
    scn = setup_in_progress(api, ownership_type="PUBLIC", with_material=False, reserve_qty=None)
    validate_success(api.recall_work_order(scn["work_order_id"], {"reason": "wrong site"}, COORD), 200)
    report = validate_success(api.get_report(scn["report_id"], COORD), 200)
    assert report["status"] == "TRIAGED"


def test_recall_sets_work_order_recalled(api):
    """PRD §3.4: "advances the work order `IN_PROGRESS → RECALLED`, and returns the report
    `IN_PROGRESS → TRIAGED` so it can be re-dispatched".

    Design: Difficulty/non_linear_state_machine/report_revision_cycle_in_progress_back_to_triaged
    """
    scn = setup_in_progress(api, ownership_type="PUBLIC", with_material=False, reserve_qty=None)
    wo = validate_success(api.recall_work_order(scn["work_order_id"], {"reason": "wrong site"}, COORD), 200)
    assert wo["status"] == "RECALLED"


# --------------------------------------------------------------------------
# non_linear_state_machine / workorder_branch_fork_recall_vs_complete_divergent_effects
# --------------------------------------------------------------------------
def test_recall_arm_voids_cost_recovery(api):
    """PRD §3.4: "It frees the crew `DISPATCHED → AVAILABLE`, voids the cost recovery
    `PENDING → VOID`, and appends a `RemovalLog` entry with `action` `RECALLED`."

    Design: Difficulty/non_linear_state_machine/workorder_branch_fork_recall_vs_complete_divergent_effects
    """
    scn = setup_in_progress(api, ownership_type="PRIVATE", reserve_qty=2.0, est_labor=2.0)
    validate_success(api.recall_work_order(scn["work_order_id"], {"reason": "abort"}, COORD), 200)
    cr = validate_success(api.get_cost_recovery(scn["cost_recovery_id"], COORD), 200)
    assert cr["status"] == "VOID"


def test_recall_arm_reverts_report_and_workorder(api):
    """PRD §3.4: "advances the work order `IN_PROGRESS → RECALLED`, and returns the report
    `IN_PROGRESS → TRIAGED` so it can be re-dispatched".

    Design: Difficulty/non_linear_state_machine/workorder_branch_fork_recall_vs_complete_divergent_effects
    """
    scn = setup_in_progress(api, ownership_type="PRIVATE", reserve_qty=2.0, est_labor=2.0)
    wo = validate_success(api.recall_work_order(scn["work_order_id"], {"reason": "abort"}, COORD), 200)
    assert wo["status"] == "RECALLED"
    report = validate_success(api.get_report(scn["report_id"], COORD), 200)
    assert report["status"] == "TRIAGED"


# --------------------------------------------------------------------------
# transitive_cascade / completion_cascade_workorder_report_costrecovery_site
# --------------------------------------------------------------------------
def test_completion_remediates_report_and_assesses_recovery(api):
    """PRD §3.4: "it advances the report `IN_PROGRESS → REMEDIATED`; it advances the cost recovery
    `PENDING → ASSESSED`; it recomputes the site's `hotspot_severity_index_confirmed` and
    `open_report_count`; and it appends a `RemovalLog` entry with `action` `COMPLETED`."

    Design: Difficulty/transitive_cascade/completion_cascade_workorder_report_costrecovery_site
    """
    scn = setup_completed(api, ownership_type="PRIVATE", est_labor=2.5, reserve_qty=3.0,
                          actual_labor=3.0, unit_cost_cents=1200, quantity_available=10.0)
    report = validate_success(api.get_report(scn["report_id"], COORD), 200)
    assert report["status"] == "REMEDIATED"
    cr = validate_success(api.get_cost_recovery(scn["cost_recovery_id"], COORD), 200)
    assert cr["status"] == "ASSESSED"


def test_completion_credits_site_outstanding_ledger(api):
    """PRD §3.4: "Assessment then credits the site's `outstanding_recovery_cents` by the recovery's
    `recoverable_cents`."

    Design: Difficulty/transitive_cascade/completion_cascade_workorder_report_costrecovery_site
    """
    scn = setup_completed(api, ownership_type="PRIVATE", est_labor=2.5, reserve_qty=3.0,
                          actual_labor=3.0, unit_cost_cents=1200, quantity_available=10.0)
    site = validate_success(api.get_site(scn["site_id"], COORD), 200)
    assert site["outstanding_recovery_cents"] == 26565


# --------------------------------------------------------------------------
# Corner: validations / photo prerequisites
# --------------------------------------------------------------------------
def test_start_without_before_photo_rejected(api):
    """PRD §3.4: "only if at least one `BEFORE` photo already exists for the work order — a missing
    before-photo is rejected with `ERR_BEFORE_PHOTO_REQUIRED` (HTTP 422)."

    Design: Corner/validations/start_without_before_photo_returns_before_photo_required
    """
    scn = setup_dispatched(api, ownership_type="PUBLIC", with_material=False, reserve_qty=None,
                           est_labor=2.0)
    resp = api.start_work_order(scn["work_order_id"], scn["crew_headers"])
    validate_error(resp, ApiErrorId.ERR_BEFORE_PHOTO_REQUIRED)


def test_complete_without_after_photo_rejected(api):
    """PRD §3.4: "completion is defined only while the report is `IN_PROGRESS`, requires that at least
    one `AFTER` photo exist (otherwise `ERR_AFTER_PHOTO_REQUIRED`, HTTP 422), and requires crew
    ownership."

    Design: Corner/validations/complete_without_after_photo_returns_after_photo_required
    """
    scn = setup_in_progress(api, ownership_type="PUBLIC", with_material=False, reserve_qty=None,
                            est_labor=2.0)
    resp = api.complete_work_order(scn["work_order_id"], {"actual_labor_hours": 2.0}, scn["crew_headers"])
    validate_error(resp, ApiErrorId.ERR_AFTER_PHOTO_REQUIRED)


# --------------------------------------------------------------------------
# Corner: state_machines / cancel_completed_workorder_returns_invalid_state
# --------------------------------------------------------------------------
def test_cancel_completed_work_order_returns_invalid_state(api):
    """PRD §2.10: "Sixth is the generic state guard: if the target resource is not in a state from
    which the requested transition is defined, the request is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."
    PRD §3.4: "a coordinator may cancel a work order still in `SCHEDULED` (with an optional `reason`),
    which advances the work order `SCHEDULED → CANCELLED`".

    Design: Corner/state_machines/cancel_completed_workorder_returns_invalid_state
    """
    scn = setup_completed(api, ownership_type="PRIVATE", est_labor=2.0, reserve_qty=None,
                          actual_labor=2.0, with_material=False)
    resp = api.cancel_work_order(scn["work_order_id"], {"reason": "late"}, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# --------------------------------------------------------------------------
# Corner: endpoints / list_workorder_photos
# --------------------------------------------------------------------------
def test_list_work_order_photos_returns_uploaded(api):
    """PRD §3.4: "Photos, removal logs, and material reservations for a work order can each be listed
    through their nested collections."

    Design: Corner/endpoints/list_workorder_photos_returns_uploaded
    """
    scn = setup_dispatched(api, ownership_type="PUBLIC", with_material=False, reserve_qty=None,
                           est_labor=2.0)
    validate_success(api.upload_photo(scn["work_order_id"],
                                      create_photo_payload("BEFORE", "http://p/b.jpg"),
                                      scn["crew_headers"]), 201)
    data, meta = validate_paginated(api.list_photos(scn["work_order_id"], COORD))
    assert meta["total_count"] == 1
