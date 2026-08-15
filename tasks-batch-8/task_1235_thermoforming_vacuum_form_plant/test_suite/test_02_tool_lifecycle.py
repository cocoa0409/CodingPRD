"""Tool lifecycle: draft intake, qualification gate, production approval, and
the revision cycle (PRD §3.3)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_tool,
    create_approve_production_payload,
    create_tool_draft,
    create_tool_production,
    create_tool_prototype,
    create_tool_payload,
    get_success_data,
    get_tool,
    validate_error,
    validate_success,
)

_ENGINEER = TEST_USERS["tooling_engineer_headers"]


def test_tool_created_in_draft_initial_state(api):
    """PRD §3.3: "A `ToolingEngineer` registers a tool in `DRAFT` with its
    `tool_code`, the `part_number` it forms, a `tool_type` of `FORM_MOLD`,
    `TRIM_FIXTURE`, or `MATCHED_SET`, the gauge window it is built for as
    `min_gauge_mm` and `max_gauge_mm` (the maximum no less than the minimum),
    the highest product grade the tool is validated for as `cleanliness_grade`,
    and the positive `prototype_cost` of building the prototype."
    PRD §3.3: "A new tool starts with `drawing_revision` at 1 and `shots_used`
    at 0."

    Design: Corner/state_machines/tool_created_in_draft_initial_state
    """
    res = api.create_tool(
        create_tool_payload(
            tool_code="T-S1", part_number="P-S1", tool_type="MATCHED_SET",
            cleanliness_grade="MEDICAL", prototype_cost=3000.00,
        ),
        _ENGINEER,
    )
    tool = validate_success(res, 201)
    assert_tool(tool)
    assert tool["status"] == "DRAFT", f"new tool must be DRAFT, got {tool['status']}"
    assert tool["drawing_revision"] == 1, (
        f"drawing_revision must start at 1, got {tool['drawing_revision']}"
    )
    assert tool["shots_used"] == 0, f"shots_used must start at 0, got {tool['shots_used']}"


def test_approve_production_from_draft_rejected(api):
    """PRD §3.3: "It requires the tool to be in `QUALIFICATION` (otherwise
    `ERR_INVALID_TOOL_TRANSITION`) and it is gated on cleanliness: a currently
    valid certificate must exist with `subject_type` `TOOL` and `subject_id`
    naming the tool, at a `grade` at least the tool's `cleanliness_grade`,
    otherwise `ERR_CERTIFICATE_INVALID`."

    Design: Corner/state_machines/approve_production_from_draft_rejected
    """
    tool = create_tool_draft(tool_code="T-S2", part_number="P-S2")
    res = api.approve_production(
        tool["id"],
        create_approve_production_payload(production_cost=8000.00, rated_lifetime_shots=80000),
        _ENGINEER,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_TOOL_TRANSITION)
    tool_after = get_tool(tool["id"])
    assert tool_after["status"] == "DRAFT", (
        f"rejected approve-production must not move the tool, got {tool_after['status']}"
    )


def test_approve_production_without_cert_rejected(api):
    """PRD §3.3: "It requires the tool to be in `QUALIFICATION` (otherwise
    `ERR_INVALID_TOOL_TRANSITION`) and it is gated on cleanliness: a currently
    valid certificate must exist with `subject_type` `TOOL` and `subject_id`
    naming the tool, at a `grade` at least the tool's `cleanliness_grade`,
    otherwise `ERR_CERTIFICATE_INVALID`."

    Design: Corner/validations/approve_production_without_cert_rejected
    """
    tool = create_tool_prototype(tool_code="T-V12", part_number="P-V12", cleanliness_grade="FOOD")
    tool = get_success_data(api.submit_qualification(tool["id"], _ENGINEER))
    assert tool["status"] == "QUALIFICATION"
    res = api.approve_production(
        tool["id"],
        create_approve_production_payload(production_cost=8000.00, rated_lifetime_shots=80000),
        _ENGINEER,
    )
    validate_error(res, ApiErrorId.ERR_CERTIFICATE_INVALID)


def test_tool_revision_cycle_status_path(api):
    """PRD §3.3: "Revising moves `PRODUCTION` → `UNDER_REVISION` (legal only
    from `PRODUCTION`, else `ERR_INVALID_TOOL_TRANSITION`), increments
    `drawing_revision` by one, and advances the tool's `version` — and then it
    cascades two hops outward."
    PRD §3.3: "Submitting for qualification moves the tool to `QUALIFICATION`
    and is legal from either `PROTOTYPE` or `UNDER_REVISION`; from anywhere
    else it is `ERR_INVALID_TOOL_TRANSITION`."

    Design: Difficulty/non_linear_state_machine/tool_revision_cycle_requalification
    """
    tool = create_tool_production(
        tool_code="TC", part_number="P-C", tool_type="MATCHED_SET",
        cleanliness_grade="FOOD", prototype_cost=2200.00,
        production_cost=12000.00, rated_lifetime_shots=120000,
    )
    assert tool["status"] == "PRODUCTION" and tool["drawing_revision"] == 1

    revised = validate_success(api.revise_tool(tool["id"], _ENGINEER), 200)
    assert revised["status"] == "UNDER_REVISION", (
        f"revise must move PRODUCTION -> UNDER_REVISION, got {revised['status']}"
    )
    assert revised["drawing_revision"] == 2, (
        f"revise must increment drawing_revision to 2, got {revised['drawing_revision']}"
    )

    qualified = validate_success(api.submit_qualification(tool["id"], _ENGINEER), 200)
    assert qualified["status"] == "QUALIFICATION", (
        f"the cycle must re-enter QUALIFICATION from UNDER_REVISION, got {qualified['status']}"
    )


def test_tool_revision_cycle_repins_qualified_drawing(api):
    """PRD §3.3: "Approval pins the drawing: `qualified_drawing_revision` is
    set to the tool's current `drawing_revision`, capturing exactly which
    revision was qualified."
    PRD §3.3: "If the tool is later revised and re-qualified, a fresh approval
    re-pins `qualified_drawing_revision` to whatever `drawing_revision` is
    current at that re-approval."

    Design: Difficulty/non_linear_state_machine/tool_revision_cycle_requalification
    """
    tool = create_tool_production(
        tool_code="TC2", part_number="P-C2", tool_type="MATCHED_SET",
        cleanliness_grade="FOOD", prototype_cost=2200.00,
        production_cost=12000.00, rated_lifetime_shots=120000,
    )
    assert tool["qualified_drawing_revision"] == 1, (
        f"first approval must pin qualified_drawing_revision to 1, got "
        f"{tool['qualified_drawing_revision']}"
    )

    get_success_data(api.revise_tool(tool["id"], _ENGINEER))
    get_success_data(api.submit_qualification(tool["id"], _ENGINEER))
    reapproved = validate_success(
        api.approve_production(
            tool["id"],
            create_approve_production_payload(production_cost=12500.00, rated_lifetime_shots=120000),
            _ENGINEER,
        ),
        200,
    )
    assert reapproved["status"] == "PRODUCTION"
    assert reapproved["qualified_drawing_revision"] == 2, (
        f"re-approval must re-pin qualified_drawing_revision to the current revision 2, "
        f"got {reapproved['qualified_drawing_revision']}"
    )
    assert reapproved["production_cost"] == 12500.00, (
        f"re-approval stores the new production_cost, got {reapproved['production_cost']}"
    )
