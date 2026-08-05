"""Work-order revision loop, owner-approval threshold, and owner-approval authorization."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    create_work_order_payload, make_vendor_headers, fixtures,
)

PM = TEST_USERS["property_manager_headers"]


def _in_progress_work_order(api):
    owner = fixtures.create_owner(api)
    prop = fixtures.create_property(api, owner["id"])
    vendor = fixtures.create_vendor(api, "MAINTENANCE")
    wo = get_success_data(api.create_work_order(create_work_order_payload(prop["id"], 4000, "COMPANY"), PM))
    get_success_data(api.assign_work_order(wo["id"], {"vendor_id": vendor["id"]}, PM))
    get_success_data(api.start_work_order(wo["id"], make_vendor_headers(vendor["id"])))
    return wo["id"], vendor["id"]


def test_work_order_request_info_then_resume(api):
    """PRD §3.7: "From `IN_PROGRESS` the job may be sent to `NEEDS_INFO`, and a property
    manager may resume it from `NEEDS_INFO` back to `ASSIGNED`, forming a revision loop."

    Design: Difficulty/non_linear_state_machine/work_order_needs_info_revision_loop
    """
    wo_id, vendor_id = _in_progress_work_order(api)
    s1 = get_success_data(api.request_info_work_order(wo_id, make_vendor_headers(vendor_id)))
    assert s1["status"] == "NEEDS_INFO", f"got {s1['status']}"
    s2 = get_success_data(api.resume_work_order(wo_id, PM))
    assert s2["status"] == "ASSIGNED", f"got {s2['status']}"


def test_work_order_resumes_to_in_progress_after_loop(api):
    """PRD §3.7: "The assigned vendor starts it (`ASSIGNED → IN_PROGRESS`) and completes it
    (`IN_PROGRESS → COMPLETED`), both requiring the acting vendor to be the work order's
    `vendor_id`."

    Design: Difficulty/non_linear_state_machine/work_order_needs_info_revision_loop
    """
    wo_id, vendor_id = _in_progress_work_order(api)
    get_success_data(api.request_info_work_order(wo_id, make_vendor_headers(vendor_id)))
    get_success_data(api.resume_work_order(wo_id, PM))
    s3 = get_success_data(api.start_work_order(wo_id, make_vendor_headers(vendor_id)))
    assert s3["status"] == "IN_PROGRESS", f"expected re-visited IN_PROGRESS, got {s3['status']}"


def test_owner_approval_not_required_at_threshold(api):
    """PRD §3.7: "it is true only when `billable_to` is `OWNER` **and** the `cost_cents`
    strictly exceeds the owner-approval threshold of five hundred dollars (50,000 cents). The
    boundary is strict — a cost exactly equal to the threshold does not require owner approval."

    Design: Difficulty/boundary_precision_check/owner_approval_cost_threshold_strict_boundary
    """
    owner = fixtures.create_owner(api)
    prop = fixtures.create_property(api, owner["id"])
    resp = api.create_work_order(create_work_order_payload(prop["id"], 50000, "OWNER"), PM)
    data = validate_success(resp, 201)
    assert data["requires_owner_approval"] is False, "cost == threshold must NOT require approval"


def test_owner_approval_required_above_threshold(api):
    """PRD §3.7: "At creation the server computes `requires_owner_approval`: it is true only
    when `billable_to` is `OWNER` **and** the `cost_cents` strictly exceeds the owner-approval
    threshold of five hundred dollars (50,000 cents)."

    Design: Difficulty/boundary_precision_check/owner_approval_cost_threshold_strict_boundary
    """
    owner = fixtures.create_owner(api)
    prop = fixtures.create_property(api, owner["id"])
    resp = api.create_work_order(create_work_order_payload(prop["id"], 50001, "OWNER"), PM)
    data = validate_success(resp, 201)
    assert data["requires_owner_approval"] is True, "cost above threshold must require approval"


def test_over_threshold_owner_wo_approved_by_manager_rejected(api):
    """PRD §3.7: "Approval moves it `COMPLETED → APPROVED`; when the work order's
    `requires_owner_approval` is true, the approving actor must be the `Owner` of the
    property, else `ERR_OWNER_APPROVAL_REQUIRED`."

    Design: Corner/validations/over_threshold_owner_wo_approved_by_manager_rejected
    """
    owner = fixtures.create_owner(api)
    prop = fixtures.create_property(api, owner["id"])
    wo = fixtures.create_completed_owner_work_order(api, prop["id"], cost_cents=60000)
    assert wo["requires_owner_approval"] is True
    resp = api.approve_work_order(wo["id"], PM)  # PropertyManager, not the Owner
    validate_error(resp, ApiErrorId.ERR_OWNER_APPROVAL_REQUIRED.value)
