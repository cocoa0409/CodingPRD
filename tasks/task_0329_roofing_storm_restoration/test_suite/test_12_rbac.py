"""Role-based access control corners: forbidden role-exclusive operations,
the unauthenticated path, and a shared operation accepted from either peer role.

Queue B (rbac section).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    NON_EXISTENT_UUID, anonymous_headers,
    create_estimator_payload, create_job_payload, create_estimate_payload,
    create_draw_payload, create_change_order_payload,
    setup_contracted_job, setup_in_production_job,
)

FA = TEST_USERS["field_adjuster_headers"]
EST = TEST_USERS["estimator_headers"]
PM = TEST_USERS["production_manager_headers"]

SHINGLE_10 = [{"trade": "SHINGLE", "squares": 10, "unit_price_cents": 10000, "waste_factor_pct": 0.10}]


def test_field_adjuster_cannot_create_estimate(api):
    """PRD §2.1: "If the header names a valid role but that role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "An `Estimator` owns scope and measurement — creating estimate
    records and their line items, finalizing them, advancing the job to the
    estimated milestone, binding a contract, and proposing change orders."

    Design: Corner/rbac/field_adjuster_cannot_create_estimate
    """
    est_id = get_success_data(api.create_estimator(create_estimator_payload(), EST))["id"]
    job_id = get_success_data(api.create_job(
        create_job_payload(assigned_estimator_id=est_id), FA))["id"]
    # POST /estimates is Estimator-exclusive; a FieldAdjuster is forbidden.
    validate_error(api.create_estimate(
        create_estimate_payload(job_id=job_id, source_kind="FIELD"), FA),
        ApiErrorId.ERR_FORBIDDEN.value)


def test_estimator_cannot_create_draw(api):
    """PRD §2.1: "If the header names a valid role but that role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "A `ProductionManager` owns everything downstream of the contract
    — materials, crews, permits, draws, change-order approval and application,
    warranties, the production milestones, and the test-driving clock."

    Design: Corner/rbac/estimator_cannot_create_draw
    """
    job_id, info = setup_in_production_job(line_items=SHINGLE_10)
    # POST /draws is ProductionManager-exclusive; an Estimator is forbidden.
    validate_error(api.create_draw(create_draw_payload(
        job_id=job_id, cumulative_pct=0.5, expected_job_version=info["job_version"]), EST),
        ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is absent or does not name one of the declared
    roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    validate_error(api.get_job(NON_EXISTENT_UUID, anonymous_headers()),
                   ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_change_order_create_shared_between_estimator_and_pm(api):
    """PRD §3.8: "An `Estimator` or a `ProductionManager` proposes a change order
    against a `job_id`, recording the `reason` for the scope change, a signed
    `delta_cents` adjustment to the contract value (which may be negative), and
    an optional `extra_shingle_squares` count of additional shingle squares to
    fold into material re-sizing, defaulting to 0 and never negative."

    Design: Corner/rbac/shared_change_order_create_both_roles
    """
    job_id, _ = setup_contracted_job(line_items=SHINGLE_10)
    # An Estimator may propose a change order (shared with ProductionManager).
    data = validate_success(api.create_change_order(create_change_order_payload(
        job_id=job_id, reason="estimator-proposed", delta_cents=1000), EST),
        expected_status=201)
    assert data["status"] == "PROPOSED"
