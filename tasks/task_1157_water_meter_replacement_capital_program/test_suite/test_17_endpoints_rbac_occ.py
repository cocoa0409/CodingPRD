"""Corner coverage — endpoints, RBAC segregation, and the optimistic
concurrency layer (PRD 2.1, 2.4, 2.5, 3.5)."""
import pytest

from test_helpers import (
    ApiErrorId, NON_EXISTENT_ID, TEST_USERS, api_client, assign_contractor,
    book_appointment, complete_appointment, create_account_payload,
    create_contractor, create_installed_account, create_meter, create_program,
    create_wave, create_work_order, fc, get_success_data,
    make_field_contractor_headers, send_and_deliver_notification,
    setup_program_wave_contractor, setup_work_order_completed_visit,
    swap_work_order, validate_error, validate_paginated, validate_success,
)

PM = TEST_USERS["program_manager_headers"]
SCHED = TEST_USERS["scheduler_headers"]
AUDITOR = TEST_USERS["quality_auditor_headers"]


def test_completion_report_forbidden_for_scheduler(api):
    """PRD §3.1: "A program-manager-only completion report returns
    `completed_meter_count`, `target_meter_count`, the `completion_pct`
    derived from completed against target meters"
    PRD §2.1: "A request whose role is authenticated but not permitted on the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/endpoints/completion_report_forbidden_for_scheduler
    """
    prog = create_program(budget_total_cents=1000000, target_meter_count=100)
    resp = api.get_completion_report(prog["id"], SCHED)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


def test_swap_side_effects_bundle(api):
    """PRD §3.5: "The swap then lands its full cascade at once: the old meter
    moves `INSTALLED` → `REMOVED` with its `service_account_id` cleared; the
    new meter moves `IN_STOCK` → `INSTALLED` with `service_account_id` set to
    the account and `installed_read_value` set to the declared
    `initial_read_value`; the work order records `new_meter_id`; the account
    moves `IN_PROGRAM` → `REPLACED`; and the work order moves `SCHEDULED` →
    `SWAPPED`."

    Design: Corner/endpoints/swap_side_effects_bundle
    """
    prog, wave, contr = setup_program_wave_contractor(
        budget_total_cents=1000000, target_meter_count=100)
    ctx = setup_work_order_completed_visit(contr["id"], program=prog, wave=wave)
    newm = create_meter(technology="AMI")
    wo = swap_work_order(ctx["work_order"]["id"], newm["id"], contr["id"],
                         final_read_value=1060, initial_read_value=0)
    assert wo["lifecycle_status"] == "SWAPPED"
    assert wo["new_meter_id"] == newm["id"]
    old_meter = get_success_data(api_client.get_meter(ctx["old_meter"]["id"], SCHED))
    assert old_meter["status"] == "REMOVED"
    assert old_meter["service_account_id"] is None
    new_meter = get_success_data(api_client.get_meter(newm["id"], SCHED))
    assert new_meter["status"] == "INSTALLED"
    assert new_meter["service_account_id"] == ctx["account"]["id"]
    assert new_meter["installed_read_value"] == 0
    acct = get_success_data(api_client.get_account(ctx["account"]["id"], SCHED))
    assert acct["status"] == "REPLACED"


def test_meter_reverse_reachability_from_account(api):
    """PRD §2.3: "List endpoints also accept filter parameters that share
    names with resource fields" — for meters: "accounts by `status`,
    `meter_location`, and `priority_tier`; meters by `service_account_id`,
    `status`, and `technology`".

    Design: Corner/endpoints/meter_reverse_reachability_from_account
    """
    acct, oldm = create_installed_account(last_billed_read_value=500,
                                          last_billed_read_at="2026-04-01T00:00:00Z")
    data, meta = validate_paginated(api.list_meters(
        SCHED, params={"service_account_id": acct["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == oldm["id"]
    data, meta = validate_paginated(api.list_meters(
        SCHED, params={"service_account_id": NON_EXISTENT_ID}))
    assert meta["total_count"] == 0
    assert data == []


def test_error_invalid_request_on_missing_field(api):
    """PRD §2.7: "Payload schema — required fields are present, types are
    valid, enum members are valid, and ranges hold (budgets and capacities
    strictly positive, read values zero or greater, and so on); otherwise
    `ERR_VALIDATION`."

    Design: Corner/errors/error_invalid_request_on_missing_field
    """
    payload = create_account_payload(service_address="37 Test Way",
                                     customer_name="Bo",
                                     customer_phone="555-0037")
    payload.pop("account_number")  # required field omitted
    resp = api.create_account(payload, SCHED)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


def test_segregation_contractor_vs_auditor(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted on
    the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.7: "Role authorization — the role is permitted on this endpoint;
    otherwise `ERR_FORBIDDEN`." (stage 2, before existence at stage 4)

    Design: Corner/rbac/segregation_contractor_vs_auditor
    """
    prog = create_program(budget_total_cents=1000000, target_meter_count=100)
    contr = create_contractor(prog["id"])
    # A FieldContractor cannot create quality audits (role check precedes
    # existence, so even a non-existent work order yields 403).
    resp = api.create_quality_audit(
        {"work_order_id": NON_EXISTENT_ID, "audit_type": "FOR_CAUSE"},
        make_field_contractor_headers(contr["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
    # A QualityAuditor cannot perform swaps.
    resp = api.swap_work_order(NON_EXISTENT_ID, {
        "expected_work_order_version": 1,
        "new_meter_id": NON_EXISTENT_ID,
        "final_read_value": 1,
        "initial_read_value": 0}, AUDITOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


def test_field_contractor_shared_read_access(api):
    """PRD §2.1: "All six roles may call every list and detail read endpoint."

    Design: Corner/rbac/field_contractor_shared_read_access
    """
    prog = create_program(budget_total_cents=1000000, target_meter_count=100)
    contr = create_contractor(prog["id"], name="AquaWorks")
    headers = make_field_contractor_headers(contr["id"])
    data = validate_success(api.get_contractor(contr["id"], headers))
    assert data["name"] == "AquaWorks"
    resp = api.list_work_orders(headers)
    assert resp.status_code == 200
    assert resp.json()["response_type"] == "array"


def test_occ_version_increments_on_each_mutation(api):
    """PRD §2.4: "Mutable resources additionally carry `updated_at`, refreshed
    to the current clock on every mutation, and `version`, an integer that
    increments by exactly one on every mutation of the resource."
    PRD §2.5: "Five write operations require the caller to supply
    `expected_work_order_version`, carrying the `version` of the work order as
    the client last observed it: assigning a contractor to a work order,
    booking an appointment, recording a swap, reconciling a swap, and
    submitting rework."

    Design: Corner/complexity_layers/occ_version_increments_on_each_mutation
    """
    prog, wave, contr = setup_program_wave_contractor(
        budget_total_cents=1000000, target_meter_count=100)
    acct, oldm = create_installed_account()
    wo = create_work_order(wave["id"], acct["id"])
    assert wo["version"] == 1
    created_stamp = wo["created_at"]
    # Assign with the clock moved forward: version 2, updated_at follows clock.
    get_success_data(api_client.set_clock("2026-05-02T00:00:00Z", PM))
    wo = validate_success(api.assign_work_order(wo["id"], {
        "contractor_id": contr["id"], "expected_work_order_version": 1}, SCHED))
    assert wo["version"] == 2
    assert wo["updated_at"].startswith("2026-05-02")
    # First DELIVERED notification drives CREATED -> NOTIFIED: version 3.
    get_success_data(api_client.set_clock("2026-05-03T00:00:00Z", PM))
    send_and_deliver_notification(wo["id"], delivered_at="2026-05-03T10:00:00Z")
    wo = get_success_data(api_client.get_work_order(wo["id"], SCHED))
    assert wo["version"] == 3
    assert wo["lifecycle_status"] == "NOTIFIED"
    assert wo["updated_at"].startswith("2026-05-03")
    # Booking: version 4.
    get_success_data(api_client.set_clock("2026-05-04T00:00:00Z", PM))
    resp = api.create_appointment({
        "work_order_id": wo["id"], "slot_date": "2026-05-06", "window": "AM",
        "expected_work_order_version": 3}, SCHED)
    validate_success(resp, expected_status=201)
    wo = get_success_data(api_client.get_work_order(wo["id"], SCHED))
    assert wo["version"] == 4
    assert wo["lifecycle_status"] == "SCHEDULED"
    assert wo["updated_at"].startswith("2026-05-04")
