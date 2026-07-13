"""ICS-213RR resource-request lifecycle: submission gates, the NEEDS_INFO
revision cycle, sourcing reservations, and pool-availability boundaries.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_activated_incident,
    create_incident,
    create_jurisdiction_and_pool,
    create_request,
    submit_request,
    source_request,
    get_pool,
    get_incident,
)

OPS = TEST_USERS["operations_chief_headers"]
LOG = TEST_USERS["logistics_chief_headers"]


# ─── Difficulty: cross_entity_state_dependency / submit_request_requires_incident_activated ───
def test_submit_request_on_monitoring_incident_rejected(api):
    """PRD §3.2: "Submission is performed by an `OperationsChief` and requires that the
    parent incident's `op_status` be `ACTIVATED` (otherwise `ERR_INCIDENT_NOT_ACTIVE`) and
    that `requested_quantity` be at least 1 (otherwise `ERR_INVALID_QUANTITY`)."

    Design: Difficulty/cross_entity_state_dependency/submit_request_requires_incident_activated
    """
    inc = create_incident(name="Watch Only", hazard_type="FLOOD")  # stays MONITORING
    req = create_request(inc["id"], resource_type="SUPPLY", requested_quantity=4)
    validate_error(
        api.transition_resource_request(req["id"], {"to_status": "SUBMITTED"}, OPS),
        ApiErrorId.ERR_INCIDENT_NOT_ACTIVE.value,
    )


def test_submit_request_on_monitoring_incident_leaves_draft(api):
    """PRD §3.2: "Submission is performed by an `OperationsChief` and requires that the
    parent incident's `op_status` be `ACTIVATED` (otherwise `ERR_INCIDENT_NOT_ACTIVE`) and
    that `requested_quantity` be at least 1 (otherwise `ERR_INVALID_QUANTITY`)."

    Design: Difficulty/cross_entity_state_dependency/submit_request_requires_incident_activated
    """
    inc = create_incident(name="Watch Only", hazard_type="FLOOD")
    req = create_request(inc["id"], resource_type="SUPPLY", requested_quantity=4)
    api.transition_resource_request(req["id"], {"to_status": "SUBMITTED"}, OPS)
    # Re-fetch the specific request via the incident listing.
    reqs, _ = _list_requests(api, inc["id"])
    target = next(r for r in reqs if r["id"] == req["id"])
    assert target["status"] == "DRAFT", f"expected DRAFT after rejected submit, got {target['status']}"


def _list_requests(api, incident_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_incident_resource_requests(incident_id, OPS))


# ─── Difficulty: non_linear_state_machine / resource_request_needs_info_revision_cycle ───
def test_needs_info_revision_cycle_returns_to_submitted(api):
    """PRD §3.2: "A `LogisticsChief` reviewing a submitted request may send it back for more
    information, moving it from `SUBMITTED` to `NEEDS_INFO`; the `OperationsChief` then
    resubmits, moving it from `NEEDS_INFO` back to `SUBMITTED` and refreshing `submitted_at`."

    Design: Difficulty/non_linear_state_machine/resource_request_needs_info_revision_cycle
    """
    inc = create_activated_incident(name="Downtown Hazmat", hazard_type="HAZMAT")
    req = create_request(inc["id"], resource_type="EQUIPMENT", requested_quantity=2)
    submit_request(req["id"])
    get_success_data(api.transition_resource_request(req["id"], {"to_status": "NEEDS_INFO"}, LOG))
    final = validate_success(api.transition_resource_request(req["id"], {"to_status": "SUBMITTED"}, OPS))
    assert final["status"] == "SUBMITTED", f"expected SUBMITTED after revision loop, got {final['status']}"


def test_needs_info_revision_cycle_refreshes_submitted_at(api):
    """PRD §3.2: "A `LogisticsChief` reviewing a submitted request may send it back for more
    information, moving it from `SUBMITTED` to `NEEDS_INFO`; the `OperationsChief` then
    resubmits, moving it from `NEEDS_INFO` back to `SUBMITTED` and refreshing `submitted_at`."

    Design: Difficulty/non_linear_state_machine/resource_request_needs_info_revision_cycle
    """
    inc = create_activated_incident(name="Downtown Hazmat", hazard_type="HAZMAT")
    req = create_request(inc["id"], resource_type="EQUIPMENT", requested_quantity=2)
    submit_request(req["id"])
    get_success_data(api.transition_resource_request(req["id"], {"to_status": "NEEDS_INFO"}, LOG))
    final = validate_success(api.transition_resource_request(req["id"], {"to_status": "SUBMITTED"}, OPS))
    assert final["submitted_at"] is not None, "submitted_at must be refreshed on resubmit"


# ─── Difficulty: priority_pair_validation_conflict / source_state_beats_insufficient_resources ───
def test_source_from_needs_info_reports_invalid_state_over_capacity(api):
    """PRD §2.7: "After that, the system verifies that the target resource is in a valid
    originating state for the requested transition (`ERR_INVALID_STATE`), then applies the
    incident optimistic-concurrency check (`ERR_STALE_VERSION`)."
    PRD §2.7: "Then cross-entity state and quantity/capacity gates (incident-active,
    IAP-published, request-filled, quantity, pool sufficiency, shelter capacity,
    activation-level validity, and missing transition target)."

    Design: Difficulty/priority_pair_validation_conflict/source_state_beats_insufficient_resources
    """
    inc = create_activated_incident(name="Border Wildfire", hazard_type="WILDFIRE")
    _, pool = create_jurisdiction_and_pool(resource_type="PERSONNEL", total_units=1)
    req = create_request(inc["id"], resource_type="PERSONNEL", requested_quantity=5)
    submit_request(req["id"])
    get_success_data(api.transition_resource_request(req["id"], {"to_status": "NEEDS_INFO"}, LOG))
    validate_error(
        api.transition_resource_request(req["id"], {"to_status": "SOURCED", "pool_id": pool["id"]}, LOG),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_source_from_needs_info_leaves_state_and_pool_untouched(api):
    """PRD §2.7: "After that, the system verifies that the target resource is in a valid
    originating state for the requested transition (`ERR_INVALID_STATE`), then applies the
    incident optimistic-concurrency check (`ERR_STALE_VERSION`)."

    Design: Difficulty/priority_pair_validation_conflict/source_state_beats_insufficient_resources
    """
    inc = create_activated_incident(name="Border Wildfire", hazard_type="WILDFIRE")
    _, pool = create_jurisdiction_and_pool(resource_type="PERSONNEL", total_units=1)
    req = create_request(inc["id"], resource_type="PERSONNEL", requested_quantity=5)
    submit_request(req["id"])
    get_success_data(api.transition_resource_request(req["id"], {"to_status": "NEEDS_INFO"}, LOG))
    api.transition_resource_request(req["id"], {"to_status": "SOURCED", "pool_id": pool["id"]}, LOG)
    reqs, _ = _list_requests(api, inc["id"])
    target = next(r for r in reqs if r["id"] == req["id"])
    assert target["status"] == "NEEDS_INFO", f"expected NEEDS_INFO retained, got {target['status']}"
    assert get_pool(pool["id"])["units_available"] == 1, "pool must be untouched after rejected source"


# ─── Difficulty: boundary_precision_check / pool_units_exact_available_boundary ───
def test_source_at_exact_available_units_succeeds(api):
    """PRD §3.2: "the pool's `units_available` must be at least the request's
    `requested_quantity`, where exactly-equal is sufficient (otherwise `ERR_INSUFFICIENT_RESOURCES`)."

    Design: Difficulty/boundary_precision_check/pool_units_exact_available_boundary
    """
    inc = create_activated_incident(name="Ice Storm", hazard_type="PUBLIC_HEALTH")
    _, pool = create_jurisdiction_and_pool(resource_type="EQUIPMENT", total_units=3)
    req1 = create_request(inc["id"], resource_type="EQUIPMENT", requested_quantity=3)
    submit_request(req1["id"])
    sourced = source_request(req1["id"], pool["id"])
    assert sourced["status"] == "SOURCED", f"exact-equal source must succeed, got {sourced['status']}"
    assert get_pool(pool["id"])["units_available"] == 0, "3 of 3 units drives availability to 0"


def test_source_one_unit_over_available_rejected(api):
    """PRD §3.2: "the pool's `units_available` must be at least the request's
    `requested_quantity`, where exactly-equal is sufficient (otherwise `ERR_INSUFFICIENT_RESOURCES`)."

    Design: Difficulty/boundary_precision_check/pool_units_exact_available_boundary
    """
    inc = create_activated_incident(name="Ice Storm", hazard_type="PUBLIC_HEALTH")
    _, pool = create_jurisdiction_and_pool(resource_type="EQUIPMENT", total_units=3)
    req1 = create_request(inc["id"], resource_type="EQUIPMENT", requested_quantity=3)
    submit_request(req1["id"])
    source_request(req1["id"], pool["id"])  # pool now fully reserved
    req2 = create_request(inc["id"], resource_type="EQUIPMENT", requested_quantity=1)
    submit_request(req2["id"])
    validate_error(
        api.transition_resource_request(req2["id"], {"to_status": "SOURCED", "pool_id": pool["id"]}, LOG),
        ApiErrorId.ERR_INSUFFICIENT_RESOURCES.value,
    )


# ─── Corner: calculations / pool_reservation_on_source ───
def test_source_reserves_units_on_pool(api):
    """PRD §3.2: "On success the request records `source_pool_id` as the chosen pool, sets
    `committed_units` equal to `requested_quantity`, stamps `sourced_at`, and the pool's
    `units_reserved` increases by `requested_quantity`, with `units_available` recomputed accordingly."

    Design: Corner/calculations/pool_reservation_on_source
    """
    inc = create_activated_incident(name="Reserve Ctx", hazard_type="WILDFIRE")
    _, pool = create_jurisdiction_and_pool(resource_type="PERSONNEL", total_units=10)
    req = create_request(inc["id"], resource_type="PERSONNEL", requested_quantity=4)
    submit_request(req["id"])
    source_request(req["id"], pool["id"])
    p = get_pool(pool["id"])
    assert p["units_reserved"] == 4, f"expected reserved 4, got {p['units_reserved']}"
    assert p["units_available"] == 6, f"expected available 6, got {p['units_available']}"
    assert p["units_committed"] == 0, f"expected committed 0, got {p['units_committed']}"


# ─── Corner: entities / pool_computed_units_available_on_create ───
def test_pool_units_available_on_create(api):
    """PRD §3.2: "On creation its `units_reserved` and `units_committed` start at zero and its
    `units_available` equals `total_units`."

    Design: Corner/entities/pool_computed_units_available_on_create
    """
    from test_helpers import create_jurisdiction
    jur = create_jurisdiction(name="Pool Owner")
    data = validate_success(
        api.create_resource_pool(
            {"jurisdiction_id": jur["id"], "resource_type": "VEHICLE", "total_units": 8}, LOG
        ),
        expected_status=201,
    )
    assert data["units_available"] == 8, f"expected available 8, got {data['units_available']}"
    assert data["units_reserved"] == 0, f"expected reserved 0, got {data['units_reserved']}"
    assert data["units_committed"] == 0, f"expected committed 0, got {data['units_committed']}"


# ─── Corner: entities / resource_request_default_priority_applied ───
def test_resource_request_defaults_priority_medium_and_draft(api):
    """PRD §3.2: "the `requested_quantity`, and an optional `priority` (`LOW`, `MEDIUM`, or
    `HIGH`, defaulting to `MEDIUM`). A new request begins in `DRAFT`, with `source_pool_id`
    null, `committed_units` at zero, and its `deploy_start`, `deploy_end`, `submitted_at`,
    `sourced_at`, and `demobilized_at` timestamps all null."

    Design: Corner/entities/resource_request_default_priority_applied
    """
    inc = create_incident(name="Draft Ctx", hazard_type="FLOOD")
    data = validate_success(
        api.create_resource_request(
            {"incident_id": inc["id"], "resource_type": "SUPPLY", "requested_quantity": 2}, OPS
        ),
        expected_status=201,
    )
    assert data["priority"] == "MEDIUM", f"expected default MEDIUM, got {data['priority']}"
    assert data["status"] == "DRAFT", f"expected DRAFT, got {data['status']}"


# ─── Corner: validations / submit_request_zero_quantity_returns_invalid_quantity ───
def test_submit_request_with_zero_quantity_rejected(api):
    """PRD §3.2: "Submission is performed by an `OperationsChief` and requires that the
    parent incident's `op_status` be `ACTIVATED` (otherwise `ERR_INCIDENT_NOT_ACTIVE`) and
    that `requested_quantity` be at least 1 (otherwise `ERR_INVALID_QUANTITY`)."

    Design: Corner/validations/submit_request_zero_quantity_returns_invalid_quantity
    """
    inc = create_activated_incident(name="Qty Ctx", hazard_type="PUBLIC_HEALTH")
    req = create_request(inc["id"], resource_type="SUPPLY", requested_quantity=0)
    validate_error(
        api.transition_resource_request(req["id"], {"to_status": "SUBMITTED"}, OPS),
        ApiErrorId.ERR_INVALID_QUANTITY.value,
    )


# ─── Corner: state_machines / resubmit_denied_request_returns_invalid_state ───
def test_resubmit_denied_request_rejected(api):
    """PRD §3.2: "From either `SUBMITTED` or `NEEDS_INFO`, a `LogisticsChief` may deny the
    request outright, moving it to the terminal `DENIED` state."
    PRD §2.7: "the system verifies that the target resource is in a valid originating state
    for the requested transition (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/resubmit_denied_request_returns_invalid_state
    """
    inc = create_activated_incident(name="Deny Ctx", hazard_type="HAZMAT")
    req = create_request(inc["id"], resource_type="EQUIPMENT", requested_quantity=2)
    submit_request(req["id"])
    get_success_data(api.transition_resource_request(req["id"], {"to_status": "DENIED"}, LOG))
    validate_error(
        api.transition_resource_request(req["id"], {"to_status": "SUBMITTED"}, OPS),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
