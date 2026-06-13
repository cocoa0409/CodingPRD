"""Entity creation, required-field, type-constraint, and computed-field tests.

Covers plan/member/call creation echoes, TOW drop-off requirement, the at-creation
provisional estimate (covered non-tow and uncovered non-tow), invalid-enum and
missing-required rejections, and not-found retrieval.
"""
from test_helpers import (
    validate_success, validate_error,
    assert_membership_plan,
    set_clock, create_plan, create_member,
    ApiErrorId, TEST_USERS, make_member_headers, NON_EXISTENT_UUID,
)

OP = TEST_USERS["dispatch_operator_headers"]


def test_create_membership_plan_returns_201_with_all_fields(api):
    """PRD §3.1: "Each plan is created with a `tier` — one of `BASIC`, `PLUS`, or
    `PREMIER`, and no two plans may share the same tier — together with the benefit
    parameters that the rest of the system reads."
    PRD §2.4: "a `version` integer that begins at the resource's creation"

    Design: Corner/entities/create_membership_plan_returns_201_with_all_fields
    """
    resp = api.create_membership_plan(
        {"tier": "PREMIER", "annual_service_limit": 10, "per_incident_mileage_cap_miles": 100,
         "overage_rate_cents_per_mile": 150, "priority_weight": 30,
         "covered_service_types": ["TOW", "JUMP", "LOCKOUT", "FUEL", "TIRE"], "base_service_fee_cents": 0},
        OP,
    )
    data = validate_success(resp, 201)
    assert_membership_plan(data)
    assert data["tier"] == "PREMIER", f"expected PREMIER, got {data['tier']}"
    assert data["annual_service_limit"] == 10, f"expected 10, got {data['annual_service_limit']}"
    assert data["version"] == 1, f"version must start at 1, got {data['version']}"


def test_create_member_missing_plan_id_rejected(api):
    """PRD §3.2: "A new member is created with `plan_id` naming the plan they enroll on,
    a `full_name`, and a home location given as `home_lat` and `home_lng` in decimal
    degrees."

    plan_id is a required input with no default; omitting it is an invalid request.

    Design: Corner/entities/create_member_missing_required_plan_id_returns_invalid_request
    """
    resp = api.create_member({"full_name": "No Plan", "home_lat": 0.0, "home_lng": 0.0}, OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_tow_call_without_dropoff_rejected(api):
    """PRD §3.5: "When `service_type` is `TOW`, the drop-off location given as
    `dropoff_lat` and `dropoff_lng` is required; for any other service type the drop-off
    coordinates are ignored. A tow request that omits drop-off coordinates is an invalid
    request."

    Design: Corner/entities/create_tow_call_without_dropoff_returns_invalid_request
    """
    set_clock()
    plan = create_plan()
    member = create_member(plan["id"])
    resp = api.create_service_call(
        {"member_id": member["id"], "service_type": "TOW", "breakdown_lat": 0.0, "breakdown_lng": 0.0},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_covered_non_tow_call_computes_zero_estimate_and_defaults(api):
    """PRD §3.5: "the call is created in `DISPATCHING` status — the initial state of
    every call — with `dispatch_attempts` set to 0 and `assigned_provider_id` null."
    PRD §3.5: "for non-tow service `tow_distance_miles` is 0."
    PRD §3.5: "The base component is the plan's `base_service_fee_cents` when the
    requested `service_type` is not among the plan's `covered_service_types`, and 0
    when it is covered. The overage component is 0 for any non-tow call"

    JUMP is covered: estimate is 0, status DISPATCHING, dispatch_attempts 0,
    tow_distance_miles 0.

    Design: Corner/entities/create_service_call_computes_estimate_and_defaults
    """
    set_clock()
    plan = create_plan()
    member = create_member(plan["id"])
    resp = api.create_service_call(
        {"member_id": member["id"], "service_type": "JUMP", "breakdown_lat": 0.0, "breakdown_lng": 0.0},
        make_member_headers(member["id"]),
    )
    data = validate_success(resp, 201)
    assert data["estimated_cost_cents"] == 0, f"covered JUMP estimate should be 0, got {data['estimated_cost_cents']}"
    assert data["status"] == "DISPATCHING", f"expected DISPATCHING, got {data['status']}"
    assert data["dispatch_attempts"] == 0, f"expected 0 attempts, got {data['dispatch_attempts']}"
    assert data["tow_distance_miles"] == 0, f"non-tow distance should be 0, got {data['tow_distance_miles']}"


def test_uncovered_non_tow_call_charges_base_fee_estimate(api):
    """PRD §3.5: "an uncovered non-tow contributes only the base fee."
    PRD §3.1: "The `base_service_fee_cents` is the out-of-pocket base fee, in cents
    (at least 0), charged when a member requests a service type that is not in the
    plan's covered list."

    BASIC plan covers only [JUMP,TIRE] with base 9000; a LOCKOUT (uncovered, non-tow)
    call estimates to 9000.

    Design: Corner/entities/uncovered_service_charges_base_fee_estimate
    """
    set_clock()
    plan = create_plan(tier="BASIC", annual_service_limit=2, per_incident_mileage_cap_miles=3,
                       overage_rate_cents_per_mile=300, priority_weight=5,
                       covered_service_types=["JUMP", "TIRE"], base_service_fee_cents=9000)
    member = create_member(plan["id"], full_name="Basic Bob")
    resp = api.create_service_call(
        {"member_id": member["id"], "service_type": "LOCKOUT", "breakdown_lat": 0.0, "breakdown_lng": 0.0},
        make_member_headers(member["id"]),
    )
    data = validate_success(resp, 201)
    assert data["estimated_cost_cents"] == 9000, \
        f"uncovered LOCKOUT estimate should be the 9000 base fee, got {data['estimated_cost_cents']}"


def test_get_nonexistent_member_returns_not_found(api):
    """PRD §2.8: "The first identifier that does not resolve to an existing resource
    causes the request to be rejected immediately with `ERR_NOT_FOUND`, before any
    deeper validation runs."

    Design: Corner/entities/get_member_nonexistent_returns_not_found
    """
    resp = api.get_member(NON_EXISTENT_UUID, OP)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_plan_with_invalid_tier_enum_rejected(api):
    """PRD §3.1: "Each plan is created with a `tier` — one of `BASIC`, `PLUS`, or
    `PREMIER`"

    A tier of 'GOLD' is outside the allowed enum and is an invalid request.

    Design: Corner/entities/member_create_invalid_enum_tier_on_plan_returns_invalid_request
    """
    resp = api.create_membership_plan(
        {"tier": "GOLD", "annual_service_limit": 4, "per_incident_mileage_cap_miles": 5,
         "overage_rate_cents_per_mile": 200, "priority_weight": 20,
         "covered_service_types": ["TOW"], "base_service_fee_cents": 0},
        OP,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
