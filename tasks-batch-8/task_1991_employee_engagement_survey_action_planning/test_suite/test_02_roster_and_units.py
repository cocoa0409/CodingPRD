"""Roster and org-unit rules: defaults, required fields, thresholds, tree."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_action_item,
    assert_org_unit,
    get_success_data,
    make_unit,
    setup_cycle_with_field_results,
    api_client,
    add_plan_item,
    make_plan,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, make_unit_manager_headers
from test_helpers.factories import create_action_item_payload

HR_ADMIN = TEST_USERS["hr_admin_headers"]


def test_org_unit_creation_applies_threshold_defaults(api):
    """PRD §3.2: "`min_n_threshold` defaults to 5 and must lie between 3 and 20
    inclusive, while `verbatim_n_threshold` defaults to 10 and must never be
    lower than the unit's own `min_n_threshold`"

    Design: Corner/entities/org_unit_creation_applies_threshold_defaults
    """
    resp = api.create_org_unit(
        {"name": "Defaults Unit", "manager_user_id": "mgr-def"}, HR_ADMIN
    )
    created = validate_success(resp, 201)
    assert_org_unit(created)
    assert created["min_n_threshold"] == 5, "creation-time default min_n_threshold"
    assert created["verbatim_n_threshold"] == 10, "creation-time default verbatim_n_threshold"

    fetched = get_success_data(api.get_org_unit(created["id"], HR_ADMIN))
    assert fetched["min_n_threshold"] == 5, "default must persist, not just echo"
    assert fetched["verbatim_n_threshold"] == 10


def test_employee_missing_required_hired_at_rejected(api):
    """PRD §3.2: "An `HRAdmin` registers each employee with an `external_ref` —
    the unique HRIS reference, where a duplicate is rejected with
    `ERR_DUPLICATE` — the `unit_id` of their current unit, an
    `employment_status` of `ACTIVE`, `LEAVE`, or `TERMINATED`, and a `hired_at`
    timestamp that later gates census eligibility."
    PRD §2.8: "Request-shape validation runs first: required body fields
    present, field types valid, enum members legal, and numeric ranges honored
    — failures yield `ERR_VALIDATION` (HTTP 400)"

    Design: Corner/entities/employee_missing_required_hired_at_rejected
    """
    unit = make_unit("ReqUnit", "mgr-rq")
    resp = api.create_employee(
        {"external_ref": "RQ01", "unit_id": unit["id"], "employment_status": "ACTIVE"},
        HR_ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_threshold_inversion_rejected_on_unit_create(api):
    """PRD §3.2: "`min_n_threshold` defaults to 5 and must lie between 3 and 20
    inclusive, while `verbatim_n_threshold` defaults to 10 and must never be
    lower than the unit's own `min_n_threshold`; an inverted pair is rejected
    with `ERR_THRESHOLD_INVERSION` (HTTP 422) both at creation and on update."

    Design: Corner/validations/threshold_inversion_rejected_on_unit_create
    """
    resp = api.create_org_unit(
        {
            "name": "BadUnit",
            "manager_user_id": "mgr-bad",
            "min_n_threshold": 10,
            "verbatim_n_threshold": 5,
        },
        HR_ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_THRESHOLD_INVERSION)


def test_employee_body_fk_reference_not_found(api):
    """PRD §2.8: "Only after the request is well-formed, authenticated,
    authorized, and fully resolved does the platform consult the state
    machines" — and beforehand, "existence of entity identifiers referenced in
    the request body — `bank_id`, `item_id`, `unit_id`, `employee_id`,
    `cycle_id`, `plan_id` — which surface as `ERR_REFERENCE_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/errors/error_reference_not_found_on_body_fk
    """
    resp = api.create_employee(
        {
            "external_ref": "NF01",
            "unit_id": NON_EXISTENT_UUID,
            "employment_status": "ACTIVE",
            "hired_at": "2026-01-01T00:00:00Z",
        },
        HR_ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


def test_reparent_unit_under_own_descendant_rejected(api):
    """PRD §3.2: "The tree must remain acyclic — neither creating a unit nor
    updating one later may set a `parent_unit_id` that would close a cycle in
    the tree, and such attempts are rejected with `ERR_UNIT_CYCLE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_referential_on_org_unit_reparent
    """
    root = make_unit("RootR", "mgr-r")
    child = make_unit("ChildS", "mgr-s", parent_unit_id=root["id"])

    resp = api.update_org_unit(root["id"], {"parent_unit_id": child["id"]}, HR_ADMIN)
    validate_error(resp, ApiErrorId.ERR_UNIT_CYCLE)

    root_after = get_success_data(api.get_org_unit(root["id"], HR_ADMIN))
    assert root_after["parent_unit_id"] is None, "rejected reparent leaves the tree unchanged"


def test_action_item_target_after_plan_due_rejected(api):
    """PRD §2.5: "Plan and milestone deadlines are checked against the cycle's
    close: an action plan's `due_at` must be strictly after the cycle's
    `closes_at`, and a milestone's `target_at` must be no later than its plan's
    `due_at`. Violations of these temporal rules are rejected with
    `ERR_WINDOW_VIOLATION` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_referential_on_org_unit_reparent
    """
    scenario = setup_cycle_with_field_results(
        unit_name="TempUnit",
        manager_user_id="mgr-temp",
        target_state="REPORTED",
        submitters=3,
    )
    plan = make_plan(
        scenario["cycle"]["id"],
        scenario["unit"]["id"],
        "mgr-temp",
        due_at="2026-12-01T00:00:00Z",
    )
    resp = api.add_action_item(
        plan["id"],
        create_action_item_payload(
            description="late item",
            owner_user_id="mgr-temp",
            target_at="2027-01-15T00:00:00Z",
        ),
        make_unit_manager_headers("mgr-temp"),
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_VIOLATION)

    ok = add_plan_item(
        plan["id"], "mgr-temp", description="timely item", target_at="2026-11-01T00:00:00Z"
    )
    assert_action_item(ok)
    assert ok["status"] == "OPEN"
