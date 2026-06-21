"""Hardware checkout/repair cycle, checkout preconditions, disposal segregation
of duties + state precedence, assignment limits, and uniqueness controls.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_vendor, create_hardware, create_employee,
    setup_employee_and_asset, open_checkout,
    submit_disposal, submit_and_approve_disposal,
    make_asset_manager_headers, make_compliance_officer_headers,
)

MGR = TEST_USERS["asset_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ─── non_linear_state_machine / hardware_cyclic_checkout_return_repair_loop ───

def test_hardware_checkout_then_return_cycles_back_to_in_stock(api):
    """PRD 3.3: "on return the checkout's `status` becomes `RETURNED`, its
    `returned_at` is stamped with the server clock, the holding employee's
    `open_checkout_count` is decreased by one, and the asset returns to
    `IN_STOCK`."

    Design: Difficulty/non_linear_state_machine/hardware_cyclic_checkout_return_repair_loop
    """
    vendor, employee, asset = setup_employee_and_asset(
        emp_overrides={"email": "alice@x.com"},
        asset_overrides={"asset_tag": "TAG-CYC", "category": "LAPTOP"},
    )
    checkout = open_checkout(asset["id"], employee["id"])
    validate_success(api.return_checkout(checkout["id"], MGR))
    after = validate_success(api.get_hardware(asset["id"], MGR))
    assert after["status"] == "IN_STOCK"  # ASSIGNED → IN_STOCK closes the loop


def test_hardware_repair_loop_returns_to_in_stock(api):
    """PRD 3.2: "An asset moves between `IN_STOCK` and `IN_REPAIR` through a
    transition supplying `to_status`: a stock asset may go into repair, and an
    asset in repair may return to stock".

    Design: Difficulty/non_linear_state_machine/hardware_cyclic_checkout_return_repair_loop
    """
    vendor, employee, asset = setup_employee_and_asset(
        emp_overrides={"email": "alice2@x.com"},
        asset_overrides={"asset_tag": "TAG-CYC2", "category": "LAPTOP"},
    )
    # Full cycle: into repair then back to stock.
    validate_success(api.transition_hardware(asset["id"], "IN_REPAIR", MGR))
    back = validate_success(api.transition_hardware(asset["id"], "IN_STOCK", MGR))
    assert back["status"] == "IN_STOCK"


# ─── cross_entity_state_dependency / checkout_requires_asset_in_stock ───

def test_checkout_rejected_when_asset_in_repair(api):
    """PRD 3.3: "The asset must currently be `IN_STOCK`; if it is not, the
    request is rejected with `ERR_ASSET_NOT_AVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/checkout_requires_asset_in_stock
    """
    vendor, employee, asset = setup_employee_and_asset(
        emp_overrides={"email": "bob@x.com"},
        asset_overrides={"asset_tag": "TAG-CE2", "category": "LAPTOP"},
    )
    validate_success(api.transition_hardware(asset["id"], "IN_REPAIR", MGR))
    resp = api.checkout_hardware(
        asset["id"],
        {
            "employee_id": employee["id"],
            "checkout_at": "2025-02-01T00:00:00.000Z",
            "expected_return_at": "2025-02-10T00:00:00.000Z",
        },
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_ASSET_NOT_AVAILABLE.value)


def test_checkout_succeeds_when_asset_in_stock(api):
    """PRD 3.3: "The asset must currently be `IN_STOCK`; if it is not, the
    request is rejected with `ERR_ASSET_NOT_AVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/checkout_requires_asset_in_stock
    """
    vendor, employee, asset = setup_employee_and_asset(
        emp_overrides={"email": "bob2@x.com"},
        asset_overrides={"asset_tag": "TAG-CE2B", "category": "LAPTOP"},
    )
    # Asset is IN_STOCK → checkout passes the availability gate.
    checkout = validate_success(
        api.checkout_hardware(
            asset["id"],
            {
                "employee_id": employee["id"],
                "checkout_at": "2025-02-01T00:00:00.000Z",
                "expected_return_at": "2025-02-10T00:00:00.000Z",
            },
            MGR,
        ),
        201,
    )
    assert checkout["status"] == "OPEN"


# ─── priority_pair_validation_conflict / segregation_beats_state_on_disposal_approve ───

def test_reapprove_approved_disposal_by_submitter_returns_state(api):
    """PRD 2.8: "Only after all four pass does the system evaluate state legality
    (fifth), then optimistic-concurrency staleness (sixth), then the
    domain-specific business rules." PRD 3.6: "approval requires the request to
    be `SUBMITTED` (else `ERR_INVALID_STATE`)".

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_state_on_disposal_approve
    """
    vendor = create_vendor(vendor_type="HARDWARE", name="HW Corp")
    asset = create_hardware(
        vendor["id"], asset_tag="TAG-SG", category="LAPTOP",
        purchase_cost_cents=100000, in_service_date="2025-01-01T00:00:00.000Z",
    )
    # Submitted by mgr-1, approved by co-1 (now APPROVED).
    submit_and_approve_disposal(
        asset["id"], reason="END_OF_LIFE", submitter_id="mgr-1", approver_id="co-1"
    )
    request_id = validate_success(
        api.list_disposal_requests(MGR, params={"hardware_asset_id": asset["id"]})
    )[0]["id"]
    # The original submitter's id (mgr-1), now acting as a ComplianceOfficer,
    # attempts approve again. State (already APPROVED, p5) is evaluated before
    # the segregation safety check (p7), so ERR_INVALID_STATE wins even though
    # the approver id equals the submitter id.
    resp = api.approve_disposal(request_id, make_compliance_officer_headers("mgr-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_reapprove_approved_disposal_is_invalid_state_independent_of_actor(api):
    """PRD 3.6: "approval requires the request to be `SUBMITTED` (else
    `ERR_INVALID_STATE`)". PRD 2.8: "the system evaluate state legality (fifth),
    then optimistic-concurrency staleness (sixth), then the domain-specific
    business rules."

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_state_on_disposal_approve
    """
    vendor = create_vendor(vendor_type="HARDWARE", name="HW Corp")
    asset = create_hardware(
        vendor["id"], asset_tag="TAG-SG2", category="LAPTOP",
        purchase_cost_cents=100000, in_service_date="2025-01-01T00:00:00.000Z",
    )
    submit_and_approve_disposal(
        asset["id"], reason="END_OF_LIFE", submitter_id="mgr-1", approver_id="co-1"
    )
    request_id = validate_success(
        api.list_disposal_requests(MGR, params={"hardware_asset_id": asset["id"]})
    )[0]["id"]
    # A distinct officer (co-1) re-approving the already-APPROVED request still
    # gets ERR_INVALID_STATE — confirming the state check fires regardless.
    resp = api.approve_disposal(request_id, make_compliance_officer_headers("co-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─── validations / assignment_limit_reached_blocks_extra_checkout ───

def test_assignment_limit_reached_blocks_extra_checkout(api):
    """PRD 3.3: "The employee's `open_checkout_count` must be strictly less than
    their `max_assigned_assets`; if accepting the checkout would not leave room
    — that is, the count is already at or above the cap — the request is
    rejected with `ERR_ASSIGNMENT_LIMIT_REACHED`."

    Design: Corner/validations/assignment_limit_reached_blocks_extra_checkout
    """
    vendor = create_vendor(vendor_type="HARDWARE", name="HW Corp")
    employee = create_employee(email="eve@x.com", max_assigned_assets=1)
    asset1 = create_hardware(vendor["id"], asset_tag="TAG-L1", category="LAPTOP")
    asset2 = create_hardware(vendor["id"], asset_tag="TAG-L2", category="LAPTOP")
    open_checkout(asset1["id"], employee["id"])
    # Employee already holds 1 open checkout at cap 1 → a second is rejected.
    resp = api.checkout_hardware(
        asset2["id"],
        {
            "employee_id": employee["id"],
            "checkout_at": "2025-02-01T00:00:00.000Z",
            "expected_return_at": "2025-02-10T00:00:00.000Z",
        },
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_LIMIT_REACHED.value)


# ─── validations / duplicate_asset_tag_among_active_returns_conflict ───

def test_duplicate_asset_tag_among_active_returns_conflict(api):
    """PRD 3.2: "The `asset_tag` must be unique among all assets that are not
    `DISPOSED`; a duplicate is rejected with `ERR_DUPLICATE_KEY`."

    Design: Corner/validations/duplicate_asset_tag_among_active_returns_conflict
    """
    vendor = create_vendor(vendor_type="HARDWARE", name="HW Corp")
    create_hardware(vendor["id"], asset_tag="TAG-DUP", category="LAPTOP")
    resp = api.create_hardware(
        {
            "vendor_id": vendor["id"], "asset_tag": "TAG-DUP", "category": "DESKTOP",
            "purchase_cost_cents": 200000, "in_service_date": "2025-01-01T00:00:00.000Z",
        },
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value)


# ─── state_machines / initial_state_disposal_request_is_submitted ───

def test_initial_state_disposal_request_is_submitted(api):
    """PRD 3.6: "On submission the request's `status` is `SUBMITTED`, and the
    submitting user's `X-User-ID` is captured into `submitted_by_user_id`."

    Design: Corner/state_machines/initial_state_disposal_request_is_submitted
    """
    vendor = create_vendor(vendor_type="HARDWARE", name="HW Corp")
    asset = create_hardware(
        vendor["id"], asset_tag="TAG-INIT", category="LAPTOP",
        purchase_cost_cents=100000, in_service_date="2025-01-01T00:00:00.000Z",
    )
    headers = make_asset_manager_headers("mgr-7")
    request = validate_success(
        api.create_disposal_request(
            {"hardware_asset_id": asset["id"], "reason": "LOST"}, headers
        ),
        201,
    )
    assert request["status"] == "SUBMITTED"
    assert request["submitted_by_user_id"] == "mgr-7"
