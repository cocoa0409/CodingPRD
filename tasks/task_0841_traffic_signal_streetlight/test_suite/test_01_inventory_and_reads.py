"""Inventory creation, computed-field reads, not-found, validation, pagination,
and reporting reads.

Corner-design (queue B) translations for the entities / endpoints / consistency
sections.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_device, assert_intersection, assert_pole,
    create_device_payload, create_intersection_payload, create_pole_payload,
    NON_EXISTENT_UUID,
)
from test_helpers.fixtures import new_intersection, new_device


def test_device_creation_returns_system_fields(api, admin_headers):
    """PRD §3.1: "A device enters service as `IN_SERVICE`, carries no `last_pm_at`
    until its first preventive-maintenance or lamp job completes, and, upon
    creation, triggers a recomputation of its intersection's posture."
    PRD §3.1: "each device declares its `device_type` (one of `SIGNAL_CONTROLLER`,
    `SIGNAL_HEAD`, `PED_SIGNAL`, `DETECTOR`, or `STREETLIGHT`), its `criticality`
    (`CRITICAL`, `STANDARD`, or `LOW`, which later feeds ticket priority)".

    Design: Corner/entities/device_creation_returns_all_fields
    """
    inter = new_intersection()
    res = api.create_device(
        create_device_payload(intersection_id=inter["id"], device_type="SIGNAL_HEAD",
                              criticality="STANDARD", model="M9"),
        admin_headers)
    device = validate_success(res, 201)
    assert_device(device)
    assert device["status"] == "IN_SERVICE", f"expected IN_SERVICE, got {device['status']}"
    assert device["criticality"] == "STANDARD"


def test_device_not_found_returns_404(api, admin_headers):
    """PRD §2.8: "the first identifier that does not resolve to an existing
    resource yields the corresponding not-found error for that resource type (for
    example `ERR_INTERSECTION_NOT_FOUND`, `ERR_POLE_NOT_FOUND`,
    `ERR_DEVICE_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
    `ERR_WORK_ORDER_NOT_FOUND`, `ERR_ATTACHMENT_NOT_FOUND`, `ERR_TCR_NOT_FOUND`,
    `ERR_LOCATE_NOT_FOUND`, or `ERR_WARRANTY_NOT_FOUND`), each carrying HTTP 404."

    Design: Corner/entities/device_not_found_returns_404
    """
    res = api.get_device(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, "ERR_DEVICE_NOT_FOUND", expected_status=404)


def test_device_missing_required_field_rejected(api, admin_headers):
    """PRD §2.9: "Request-body validity — required fields present and correctly
    typed, enum members valid, and `reported_severity` between 1 and 5 inclusive,
    else `ERR_VALIDATION` (422)."

    Design: Corner/entities/device_missing_required_field_rejected
    """
    inter = new_intersection()
    payload = create_device_payload(intersection_id=inter["id"], model="M9")
    del payload["criticality"]
    res = api.create_device(payload, admin_headers)
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_pole_available_load_computed_on_create(api, admin_headers):
    """PRD §3.1: "A pole starts life `STANDING` with `committed_load_units` at 0,
    so its `available_load_units` equals its full `load_capacity_units`."

    Design: Corner/entities/pole_available_load_computed_on_create
    """
    res = api.create_pole(create_pole_payload(label="P50", load_capacity_units=50), admin_headers)
    pole = validate_success(res, 201)
    assert_pole(pole)
    assert pole["committed_load_units"] == 0
    assert pole["available_load_units"] == 50


def test_intersection_system_fields_on_create(api, admin_headers):
    """PRD §3.1: "A newly created intersection begins with `operational_posture`
    of `NORMAL`, an `active_plan_revision` of 0, and `active_cycle_length_sec` and
    `active_offset_sec` both at 0; these active-plan fields are later overwritten
    only when a timing change is approved (see §3.6)."

    Design: Corner/entities/system_fields_generated_on_create
    """
    res = api.create_intersection(create_intersection_payload(name="Vine & 19th", district="D2"),
                                  admin_headers)
    inter = validate_success(res, 201)
    assert_intersection(inter)
    assert inter["operational_posture"] == "NORMAL"
    assert inter["active_plan_revision"] == 0


def test_list_devices_pagination(api, admin_headers):
    """PRD §2.3: "For every list response, the `meta` object carries `limit`,
    `offset`, `total_count` (the number of records matching the filter before
    pagination), and `has_more` (true when records remain beyond the current page)."

    Design: Corner/endpoints/list_devices_pagination
    """
    inter = new_intersection()
    new_device(inter["id"], device_type="SIGNAL_HEAD", criticality="STANDARD")
    new_device(inter["id"], device_type="STREETLIGHT", criticality="LOW")

    res = api.list_devices(admin_headers, params={"intersection_id": inter["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(data) == 1


def test_intersection_summary_computed_read(api, admin_headers, dispatcher_headers):
    """PRD §3.9: "An intersection summary returns that intersection's
    `intersection_id`, its current `operational_posture`, its `device_count`, its
    `out_of_service_count`, and its `open_ticket_count`."
    PRD §2.10: "If any of those devices is `KNOCKED_DOWN`, the posture is
    `EMERGENCY`; otherwise, if any is `OUT_OF_SERVICE` or `UNDER_MAINTENANCE`, the
    posture is `DEGRADED`; otherwise it is `NORMAL`."

    Design: Corner/endpoints/intersection_summary_computed_read
    """
    inter = new_intersection()
    new_device(inter["id"], device_type="SIGNAL_HEAD", criticality="STANDARD")
    res = api.get_intersection_summary(inter["id"], dispatcher_headers)
    summary = validate_success(res, 200)
    assert summary["operational_posture"] == "NORMAL"
    assert summary["device_count"] == 1
    assert summary["out_of_service_count"] == 0


def test_device_status_immediately_visible_on_create(api, admin_headers):
    """PRD §3.1: "A device enters service as `IN_SERVICE`, carries no `last_pm_at`
    until its first preventive-maintenance or lamp job completes, and, upon
    creation, triggers a recomputation of its intersection's posture."

    Design: Corner/consistency_model/immediate_visibility_on_create
    """
    inter = new_intersection()
    res = api.create_device(
        create_device_payload(intersection_id=inter["id"], device_type="PED_SIGNAL",
                              criticality="STANDARD", model="M9"),
        admin_headers)
    device = validate_success(res, 201)
    assert device["status"] == "IN_SERVICE"

    get_res = api.get_device(device["id"], admin_headers)
    fetched = validate_success(get_res, 200)
    assert fetched["status"] == "IN_SERVICE"
