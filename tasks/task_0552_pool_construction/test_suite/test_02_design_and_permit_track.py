"""Design rendering, the permit track, the revision loop, and design-plan listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_design_plan_payload,
    setup_project_with_design, setup_owner_approved_design, create_permitted_project,
)


def test_submit_permit_before_owner_approved_rejected(api, designer_headers):
    """PRD §3.2: "The Designer submits for permit, which requires the design status to be
    OWNER_APPROVED — otherwise ERR_DESIGN_NOT_APPROVED — and moves permit_status from NONE to
    SUBMITTED, recording the permitting authority in the jurisdiction field."

    Design: Corner/state_machines/submit_permit_before_owner_approved_rejected
    """
    project, dp = setup_project_with_design()  # DRAFT, never approved
    res = api.transition_design_plan(dp["id"], {"action": "SUBMIT_PERMIT", "jurisdiction": "City"},
                                     designer_headers)
    validate_error(res, ApiErrorId.ERR_DESIGN_NOT_APPROVED)


def test_second_design_plan_rejected(api, designer_headers):
    """PRD §3.2: "At most one design plan may exist per project; a second attempt is rejected with
    ERR_DESIGN_ALREADY_EXISTS."

    Design: Corner/state_machines/duplicate_design_plan_rejected
    """
    project, dp = setup_project_with_design()
    res = api.create_design_plan(create_design_plan_payload(project["id"], length_ft=20,
                                                            width_ft=10, avg_depth_ft=4),
                                 designer_headers)
    validate_error(res, ApiErrorId.ERR_DESIGN_ALREADY_EXISTS)


def test_design_status_reconciles_to_permitted_after_issue(api, builder_headers):
    """PRD §3.2: "When the plan is OWNER_APPROVED and its permit_status is ISSUED, design_status
    rolls all the way up to PERMITTED."

    Design: Corner/entities/design_status_reconciled_to_permitted_after_issue
    """
    project, dp = create_permitted_project()
    fresh = validate_success(api.get_pool_project(project["id"], builder_headers), 200)
    assert fresh["design_status"] == "PERMITTED"


def test_list_design_plans_filtered_by_project(api, builder_headers):
    """PRD §2.3: "Design plans, phase gates, change orders, punch items, and draw requests each
    accept an optional pool_project_id filter".
    PRD §2.3: "The pagination fields limit, offset, total_count, and has_more are returned inside
    the meta object of a list response, where total_count reflects the full count of matching
    resources before the limit/offset window is applied and has_more is true when resources remain
    beyond the current window."

    Design: Corner/endpoints/list_design_plans_pagination_envelope
    """
    project, dp = setup_project_with_design()
    data, meta = validate_paginated(
        api.list_design_plans(builder_headers, params={"pool_project_id": project["id"],
                                                       "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == dp["id"]
    assert meta["has_more"] is False


def test_full_revision_cycle_returns_to_draft_twice(api, designer_headers, owner_headers):
    """PRD §3.2: "A revision request from RENDERED_3D returns the plan to DRAFT and adds one to
    revision_count. The homeowner may also request a revision of an already-approved plan, returning
    OWNER_APPROVED to DRAFT and again adding one to revision_count — but only while the plan's
    permit_status is NONE or REJECTED;"

    Design: Difficulty/non_linear_state_machine/design_plan_revision_cycle
    """
    project, dp = setup_owner_approved_design()  # OWNER_APPROVED, permit NONE
    # OWNER_APPROVED -> DRAFT (revision 1)
    r1 = validate_success(api.transition_design_plan(dp["id"], {"action": "REQUEST_REVISION"},
                                                     owner_headers), 200)
    assert r1["status"] == "DRAFT"
    assert r1["revision_count"] == 1
    # DRAFT -> RENDERED_3D
    validate_success(api.transition_design_plan(dp["id"], {"action": "RENDER"}, designer_headers), 200)
    # RENDERED_3D -> DRAFT (revision 2)
    r2 = validate_success(api.transition_design_plan(dp["id"], {"action": "REQUEST_REVISION"},
                                                     owner_headers), 200)
    assert r2["status"] == "DRAFT"
    assert r2["revision_count"] == 2


def test_revision_from_owner_approved_increments_count(api, owner_headers):
    """PRD §3.2: "The homeowner may also request a revision of an already-approved plan, returning
    OWNER_APPROVED to DRAFT and again adding one to revision_count — but only while the plan's
    permit_status is NONE or REJECTED;"

    Design: Difficulty/non_linear_state_machine/design_plan_revision_cycle
    """
    project, dp = setup_owner_approved_design()
    assert dp["revision_count"] == 0
    revised = validate_success(api.transition_design_plan(dp["id"], {"action": "REQUEST_REVISION"},
                                                          owner_headers), 200)
    assert revised["status"] == "DRAFT"
    assert revised["revision_count"] == 1
