"""Inspection lifecycle, property spacing, and the report/inspection state gate."""
from test_helpers import (
    validate_error, validate_success, validate_paginated,
    TEST_USERS, make_field_adjuster_headers,
    create_inspection_payload, create_report_payload,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["licensing_admin_headers"]
DESK = TEST_USERS["desk_examiner_headers"]


def test_complete_already_completed_inspection(api):
    """PRD 3.4: "Completing an in-progress inspection moves it IN_PROGRESS ->
    COMPLETED, requiring the IN_PROGRESS state (otherwise ERR_INSPECTION_NOT_IN_PROGRESS)
    and assignment ownership."

    Design: Corner/state_machines/complete_already_completed_inspection
    """
    ctx = fx.setup_completed_inspection(api)
    resp = api.complete_inspection(ctx["insp_id"], make_field_adjuster_headers(ctx["adj_id"]))
    validate_error(resp, "ERR_INSPECTION_NOT_IN_PROGRESS")


# --------------------------------------------------------------------------
# Difficulty: inspection spacing buffer on the same claim
# --------------------------------------------------------------------------
def _accepted_with_first_inspection(api):
    ctx = fx.setup_accepted_assignment(api, loss_state="FL", peril_type="HAIL", policy_type="ACV")
    i1 = fx.create_inspection(api, ctx["asg_id"], ctx["claim_id"], ctx["adj_id"],
                              scheduled_start="2026-07-02T09:00:00Z",
                              scheduled_end="2026-07-02T10:00:00Z")
    ctx["i1"] = i1
    return ctx


def test_inspection_spacing_too_close_rejected(api):
    """PRD 3.4: "the new [scheduled_start, scheduled_end) window must be separated from
    every other non-terminal inspection on the same claim by at least 240 minutes —
    that is, four hours — of clearance. ... anything closer is rejected with
    ERR_INSPECTION_SPACING_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/inspection_spacing_buffer_on_claim
    """
    ctx = _accepted_with_first_inspection(api)
    # I1 ends 10:00; a window opening 10:30 leaves only a 30-minute gap (< 240).
    payload = create_inspection_payload(ctx["asg_id"], ctx["claim_id"],
                                        scheduled_start="2026-07-02T10:30:00Z",
                                        scheduled_end="2026-07-02T11:30:00Z")
    resp = api.create_inspection(payload, make_field_adjuster_headers(ctx["adj_id"]))
    validate_error(resp, "ERR_INSPECTION_SPACING_CONFLICT")


def test_inspection_spacing_conflict_does_not_persist_second(api):
    """PRD 3.4: "a spacing rule governs creation ... anything closer is rejected with
    ERR_INSPECTION_SPACING_CONFLICT." A rejected create must not persist the inspection.

    Design: Difficulty/resource_temporal_overlap/inspection_spacing_buffer_on_claim
    """
    ctx = _accepted_with_first_inspection(api)
    payload = create_inspection_payload(ctx["asg_id"], ctx["claim_id"],
                                        scheduled_start="2026-07-02T10:30:00Z",
                                        scheduled_end="2026-07-02T11:30:00Z")
    api.create_inspection(payload, make_field_adjuster_headers(ctx["adj_id"]))
    _, meta = validate_paginated(api.list_inspections(DESK))
    assert meta["total_count"] == 1, "only the first inspection should persist"


def test_inspection_spacing_exact_gap_allowed(api):
    """PRD 3.4: "the new window starts at least 240 minutes after another inspection
    ends, or the new window ends at least 240 minutes before another begins."

    Design: Difficulty/resource_temporal_overlap/inspection_spacing_buffer_on_claim
    """
    ctx = _accepted_with_first_inspection(api)
    # I1 ends 10:00; a window opening exactly 14:00 is 240 minutes after (>= 240 clearance).
    payload = create_inspection_payload(ctx["asg_id"], ctx["claim_id"],
                                        scheduled_start="2026-07-02T14:00:00Z",
                                        scheduled_end="2026-07-02T15:00:00Z")
    data = validate_success(api.create_inspection(payload, make_field_adjuster_headers(ctx["adj_id"])), 201)
    assert data["status"] == "SCHEDULED"


# --------------------------------------------------------------------------
# Difficulty: report submit gated on inspection COMPLETED
# --------------------------------------------------------------------------
def _report_draft_on_in_progress_inspection(api):
    ctx = fx.setup_accepted_assignment(api, loss_state="FL", peril_type="HAIL", policy_type="ACV")
    insp = fx.create_inspection(api, ctx["asg_id"], ctx["claim_id"], ctx["adj_id"])
    fx.start_inspection(api, insp["id"], ctx["adj_id"])  # IN_PROGRESS, not COMPLETED
    rpt = fx.create_report(api, insp["id"], ctx["asg_id"], ctx["adj_id"], photo_count=3)
    ctx["insp_id"] = insp["id"]
    ctx["rpt_id"] = rpt["id"]
    return ctx


def test_report_submit_requires_inspection_completed(api):
    """PRD 3.5: "Submission is heavily gated: the acting adjuster must own the
    assignment; the parent inspection must be COMPLETED (otherwise
    ERR_INSPECTION_NOT_COMPLETED); an APPROVED estimate must exist for that same parent
    inspection (otherwise ERR_ESTIMATE_NOT_APPROVED); and the report's photo_count must
    be at least 1 (otherwise ERR_REPORT_NO_PHOTOS)."

    Design: Difficulty/cross_entity_state_dependency/report_submit_requires_inspection_completed
    """
    ctx = _report_draft_on_in_progress_inspection(api)
    resp = api.submit_report(ctx["rpt_id"], make_field_adjuster_headers(ctx["adj_id"]))
    validate_error(resp, "ERR_INSPECTION_NOT_COMPLETED")


def test_report_submit_on_incomplete_inspection_leaves_draft(api):
    """PRD 3.5: "Submitting a report moves it to SUBMITTED ... the parent inspection
    must be COMPLETED (otherwise ERR_INSPECTION_NOT_COMPLETED)." A rejected submit
    leaves the report in DRAFT.

    Design: Difficulty/cross_entity_state_dependency/report_submit_requires_inspection_completed
    """
    ctx = _report_draft_on_in_progress_inspection(api)
    api.submit_report(ctx["rpt_id"], make_field_adjuster_headers(ctx["adj_id"]))
    data = validate_success(api.get_report(ctx["rpt_id"], DESK))
    assert data["status"] == "DRAFT"
