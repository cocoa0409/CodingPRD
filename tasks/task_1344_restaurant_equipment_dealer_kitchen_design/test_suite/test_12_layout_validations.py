"""Layout structural and safety validations at submit time."""
from test_helpers import (
    TEST_USERS,
    add_equipment_item,
    create_customer,
    create_layout,
    create_project,
    validate_error,
)

KD = TEST_USERS["kitchen_designer_headers"]


def test_hood_spec_inconsistent_submit_rejected(api):
    """PRD §3.2: "And if `hood_required` is true, at least one item on the
    layout must carry `requires_hood` true — a hood design with nothing under
    it is a spec error, rejected with `ERR_HOOD_SPEC_INCONSISTENT`."

    Design: Corner/validations/hood_spec_inconsistent_submit_rejected
    """
    customer = create_customer()
    project = create_project(customer["id"])
    layout = create_layout(project["id"], hood_required=True)
    add_equipment_item(
        project["id"], layout["id"], model_no="A", requires_hood=False
    )

    res = api.submit_layout(project["id"], layout["id"], KD)
    validate_error(res, "ERR_HOOD_SPEC_INCONSISTENT", expected_status=422)


def test_hood_spec_consistent_submit_accepted(api):
    """PRD §3.2: "And if `hood_required` is true, at least one item on the
    layout must carry `requires_hood` true". With a hood item present the
    safety check passes.

    Design: Corner/validations/hood_spec_inconsistent_submit_rejected
    """
    from test_helpers import get_success_data, validate_success

    customer = create_customer()
    project = create_project(customer["id"])
    layout = create_layout(project["id"], hood_required=True)
    add_equipment_item(
        project["id"], layout["id"], model_no="RANGE", requires_hood=True
    )

    submitted = validate_success(
        api.submit_layout(project["id"], layout["id"], KD), 200
    )
    assert submitted["status"] == "SUBMITTED"


def test_layout_empty_constraint_beats_credit_fiscal_check(api):
    """PRD §3.2: "It must reference at least one equipment item, or the call
    fails with `ERR_LAYOUT_EMPTY`."

    Design: Difficulty/priority_pair_validation_conflict/layout_empty_constraint_beats_credit_fiscal_check
    """
    # Deliberately tiny credit limit; the submit path never reaches fiscal
    # checks — the structural constraint owns the failure.
    customer = create_customer(credit_limit_cents=1)
    project = create_project(customer["id"], project_name="Tiny")
    layout = create_layout(project["id"])

    res = api.submit_layout(project["id"], layout["id"], KD)
    validate_error(res, "ERR_LAYOUT_EMPTY", expected_status=422)


def test_layout_empty_submit_rejected_plain(api):
    """PRD §3.2: "It must reference at least one equipment item, or the call
    fails with `ERR_LAYOUT_EMPTY`."

    Design: Difficulty/priority_pair_validation_conflict/layout_empty_constraint_beats_credit_fiscal_check
    """
    customer = create_customer()
    project = create_project(customer["id"])
    layout = create_layout(project["id"], hood_required=False)

    res = api.submit_layout(project["id"], layout["id"], KD)
    validate_error(res, "ERR_LAYOUT_EMPTY", expected_status=422)
