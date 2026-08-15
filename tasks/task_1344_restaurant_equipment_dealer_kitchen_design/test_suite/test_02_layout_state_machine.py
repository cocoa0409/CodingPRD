"""KitchenLayout lifecycle: initial state, revision loop, RBAC."""
from test_helpers import (
    TEST_USERS,
    add_equipment_item,
    assert_layout,
    create_customer,
    create_layout,
    create_project,
    get_success_data,
    validate_error,
    validate_success,
)

PM = TEST_USERS["project_manager_headers"]
KD = TEST_USERS["kitchen_designer_headers"]


def test_layout_initial_state_draft(api):
    """PRD §3.2: "Each layout is born in `DRAFT` with `revision_no` 1."

    Design: Corner/state_machines/layout_initial_state_draft
    """
    customer = create_customer()
    project = create_project(customer["id"])
    layout = validate_success(
        api.create_layout(
            project["id"],
            {"layout_label": "Rev-A", "drawing_ref": "DWG-I"},
            KD,
        ),
        201,
    )
    assert_layout(layout)
    assert layout["status"] == "DRAFT"
    assert layout["revision_no"] == 1


def test_layout_revision_loop_return_drops_to_draft_and_increments(api):
    """PRD §3.2: "Alternatively the PM can return a `SUBMITTED` layout for
    revision: it drops back to `DRAFT`, its `revision_no` increments by 1, and
    the design loop repeats — the same not-submitted guard
    (`ERR_LAYOUT_NOT_SUBMITTED`) applies."

    Design: Difficulty/non_linear_state_machine/kitchen_layout_revision_loop
    """
    customer = create_customer()
    project = create_project(customer["id"])
    layout = create_layout(project["id"])
    add_equipment_item(project["id"], layout["id"])
    submitted = get_success_data(api.submit_layout(project["id"], layout["id"], KD))
    assert submitted["revision_no"] == 1

    returned = validate_success(
        api.return_layout_for_revision(project["id"], layout["id"], PM), 200
    )
    assert returned["status"] == "DRAFT"
    assert returned["revision_no"] == 2


def test_layout_revision_loop_resubmits_to_complete_cycle(api):
    """PRD §3.2: "it drops back to `DRAFT`, its `revision_no` increments by 1,
    and the design loop repeats — the same not-submitted guard
    (`ERR_LAYOUT_NOT_SUBMITTED`) applies."

    Design: Difficulty/non_linear_state_machine/kitchen_layout_revision_loop
    """
    customer = create_customer()
    project = create_project(customer["id"])
    layout = create_layout(project["id"])
    add_equipment_item(project["id"], layout["id"])
    get_success_data(api.submit_layout(project["id"], layout["id"], KD))
    get_success_data(api.return_layout_for_revision(project["id"], layout["id"], PM))

    resubmitted = validate_success(
        api.submit_layout(project["id"], layout["id"], KD), 200
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_no"] == 2


def test_salesrep_cannot_approve_layout(api):
    """PRD §2.1: "`ProjectManager` is the dealer-side PM and owns project
    creation, project cancellation, punch-list close, project completion,
    layout approval and return-for-revision, shop-drawing approval, and
    punch-item verification and voiding". "When the supplied role is not
    authorized for the attempted operation the request fails with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/roles/salesrep_cannot_approve_layout
    """
    customer = create_customer()
    project = create_project(customer["id"])
    layout = create_layout(project["id"])
    add_equipment_item(project["id"], layout["id"])
    get_success_data(api.submit_layout(project["id"], layout["id"], KD))

    res = api.approve_layout(
        project["id"], layout["id"], TEST_USERS["sales_rep_headers"]
    )
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_layout_approve_supersedes_siblings(api):
    """PRD §3.2: "Approving a `SUBMITTED` layout moves it to `APPROVED` and
    immediately supersedes every sibling layout on the same project that is
    currently `SUBMITTED` or `APPROVED` — at most one layout is ever live for
    pricing."

    Design: Difficulty/non_linear_state_machine/kitchen_layout_revision_loop
    """
    customer = create_customer()
    project = create_project(customer["id"])
    layout_a = create_layout(project["id"], layout_label="Rev-A")
    add_equipment_item(project["id"], layout_a["id"])
    get_success_data(api.submit_layout(project["id"], layout_a["id"], KD))
    approved_a = get_success_data(api.approve_layout(project["id"], layout_a["id"], PM))
    assert approved_a["status"] == "APPROVED"

    layout_b = create_layout(project["id"], layout_label="Rev-B")
    add_equipment_item(project["id"], layout_b["id"])
    get_success_data(api.submit_layout(project["id"], layout_b["id"], KD))
    approved_b = validate_success(
        api.approve_layout(project["id"], layout_b["id"], PM), 200
    )
    assert approved_b["status"] == "APPROVED"

    layout_a_after = get_success_data(
        api.get_layout(project["id"], layout_a["id"], PM)
    )
    assert layout_a_after["status"] == "SUPERSEDED"
