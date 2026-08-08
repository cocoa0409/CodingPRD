"""Authentication, role scoping, resource ownership and the two four-eyes rules."""

from test_helpers import (
    ADMIN,
    ADMIN_ONE_ID,
    ANON,
    INSPECTOR,
    INSPECTOR_TWO,
    INSPECTOR_TWO_ID,
    PLAN_REVIEWER,
    PLAN_REVIEWER_ONE_ID,
    UNKNOWN_UUIDS,
    ApiErrorId,
    advance_permit_to_under_review,
    apply_for_permit,
    approve_plan_review,
    assert_posture,
    create_facility_payload,
    create_inspection_payload,
    create_staff_assignment_payload,
    make_admin_headers,
    make_headers,
    make_inspector_headers,
    make_operator_headers,
    open_closure_order,
    pay_operator_balance,
    read_closure_order,
    read_facility,
    read_permit,
    read_plan_review,
    register_operator,
    setup_closure_with_pending_reopen,
    setup_operator_and_pool,
    submit_plan_review,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_an_operator_may_not_schedule_an_inspection(api):
    """PRD 2.1: A request that authenticates but whose role is not among the
    roles listed for the target endpoint in Section 4 is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403).
    PRD 2.1: `Inspector` schedules and conducts inspections, records and verifies
    violations, orders closures, decides reopen requests and triages complaints.

    Design: Corner/rbac/operator_cannot_schedule_an_inspection
    """
    ctx = setup_operator_and_pool()

    validate_error(
        api.create_inspection(
            create_inspection_payload(
                ctx["facility_id"],
                scheduled_start_at="2026-05-02T09:00:00Z",
                scheduled_end_at="2026-05-02T10:00:00Z",
            ),
            ctx["op_headers"],
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value, 403,
    )

    rows, meta = validate_paginated(
        api.list_inspections(ADMIN, params={"facility_id": ctx["facility_id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_an_inspector_may_not_advance_a_plan_review(api):
    """PRD 2.1: `PlanReviewer` is the only role that may advance a plan review
    and may touch nothing else that mutates state.
    PRD 2.1: A request that authenticates but whose role is not among the roles
    listed for the target endpoint in Section 4 is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403).

    Design: Corner/rbac/inspector_cannot_decide_a_plan_review
    """
    ctx = setup_operator_and_pool()
    review = submit_plan_review(
        ctx["facility_id"], ctx["op_headers"], project_type="ALTERATION",
        drawing_reference="DR-1",
    )

    validate_error(
        api.transition_plan_review(
            review["id"], {"action": "START_REVIEW"}, INSPECTOR
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value, 403,
    )

    stored = read_plan_review(review["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["reviewer_user_id"] is None


def test_a_plan_reviewer_may_not_drive_the_permit_lifecycle(api):
    """PRD 2.1: `PlanReviewer` is the only role that may advance a plan review
    and may touch nothing else that mutates state.
    PRD 2.1: A request that authenticates but whose role is not among the roles
    listed for the target endpoint in Section 4 is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403).

    Design: Corner/rbac/plan_reviewer_cannot_drive_the_permit_lifecycle
    """
    ctx = setup_operator_and_pool()
    permit = apply_for_permit(ctx["facility_id"], ctx["op_headers"])
    validate_success(
        api.transition_permit(permit["id"], {"action": "SUBMIT"}, ctx["op_headers"])
    )

    validate_error(
        api.transition_permit(permit["id"], {"action": "START_REVIEW"}, PLAN_REVIEWER),
        ApiErrorId.ERR_UNAUTHORIZED.value, 403,
    )

    assert read_permit(permit["id"])["status"] == "SUBMITTED"


def test_an_anonymous_caller_may_not_register_a_facility(api):
    """PRD 2.1: `Anonymous` exists so that a member of the public can register an
    operator account and file a complaint without credentials.
    PRD 2.1: A request that authenticates but whose role is not among the roles
    listed for the target endpoint in Section 4 is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403).

    Design: Corner/rbac/anonymous_cannot_register_a_facility
    """
    operator, op_headers = register_operator()

    validate_error(
        api.create_facility(create_facility_payload(operator["id"]), ANON),
        ApiErrorId.ERR_UNAUTHORIZED.value, 403,
    )

    rows, meta = validate_paginated(
        api.list_facilities(op_headers, params={"operator_id": operator["id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_an_operator_may_not_write_to_another_operators_venue(api):
    """PRD 2.1: When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the
    acting Operator record. Ownership checks on any resource that references an
    operator compare the resource's owning operator to `X-User-ID` — directly
    through `operator_id` on a facility or a ledger posting, and transitively
    through the owning facility for permits, plan reviews, closure orders, staff
    assignments, compliance artifacts, water readings and violations. A mismatch
    is `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

    Design: Corner/rbac/operator_cannot_write_to_another_operators_facility
    """
    ctx = setup_operator_and_pool(
        operator_overrides={"legal_name": "Operator A", "contact_email": "a@example.com"},
        name="A Pool",
    )
    intruder, _ = register_operator(
        legal_name="Operator B", contact_email="b@example.com"
    )
    intruder_headers = make_operator_headers(intruder["id"])

    validate_error(
        api.create_water_reading(
            ctx["facility_id"],
            {
                "sampled_at": "2026-05-01T00:00:00Z",
                "source": "OPERATOR_LOG",
                "free_chlorine_ppm": 2.0,
                "combined_chloramine_ppm": 0.1,
                "ph": 7.4,
                "water_temp_f": 82.0,
            },
            intruder_headers,
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403,
    )

    validate_error(
        api.create_permit(
            {
                "facility_id": ctx["facility_id"],
                "permit_type": "ANNUAL",
                "term_start_date": "2026-05-01",
            },
            intruder_headers,
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403,
    )

    readings, readings_meta = validate_paginated(
        api.list_water_readings(ctx["facility_id"], ADMIN)
    )
    assert readings_meta["total_count"] == 0 and readings == []

    permits, permits_meta = validate_paginated(
        api.list_permits(ADMIN, params={"facility_id": ctx["facility_id"]})
    )
    assert permits_meta["total_count"] == 0 and permits == []


def test_an_unknown_role_or_a_blank_user_id_is_unauthenticated(api):
    """PRD 2.1: A request whose `X-User-Role` header is missing, blank, or a
    string outside the five recognised roles, or whose `X-User-ID` is missing or
    empty on any non-`Anonymous` role, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401).
    PRD 2.1: `X-User-ID` is required and must be a non-empty string for every
    role other than `Anonymous`; for `Anonymous` it is ignored when supplied and
    not required when absent.

    Design: Corner/rbac/unknown_role_header_returns_unauthenticated
    """
    ctx = setup_operator_and_pool()

    unknown_role = api.get_facility(
        ctx["facility_id"], make_headers("Regulator", "reg-1")
    )
    validate_error(unknown_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert unknown_role.json()["response_type"] == "error"

    blank_user_id = api.get_facility(ctx["facility_id"], make_operator_headers(""))
    validate_error(blank_user_id, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert blank_user_id.json()["response_type"] == "error"


def test_the_ordering_inspector_may_not_decide_the_reopen(api):
    """PRD 2.1: The `X-User-ID` deciding a reopen request must differ from the
    `ordered_by_user_id` recorded on that closure order, and the `X-User-ID`
    issuing a permit must differ from the `decided_by_user_id` recorded on the
    plan review that permit relies on. Either breach is
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
    PRD 3.7: Approving and denying both require the order to be in
    `REOPEN_REQUESTED` and both enforce the four-eyes rule — the deciding
    `X-User-ID` must differ from `ordered_by_user_id`.

    Design: Corner/rbac/reopen_decision_by_the_ordering_inspector_rejected
    """
    ctx = setup_closure_with_pending_reopen(order_headers=INSPECTOR)

    validate_error(
        api.decide_reopen(
            ctx["closure_order_id"], {"decision": "APPROVE"}, INSPECTOR
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403,
    )
    assert read_closure_order(ctx["closure_order_id"])["status"] == "REOPEN_REQUESTED"

    cleared = validate_success(
        api.decide_reopen(
            ctx["closure_order_id"], {"decision": "APPROVE"}, INSPECTOR_TWO
        )
    )
    assert cleared["status"] == "CLEARED"
    assert cleared["reopen_decided_by_user_id"] == INSPECTOR_TWO_ID
    assert_posture(read_facility(ctx["facility_id"]), "CLOSED", "PERMIT_MISSING")


def test_the_plan_review_decider_may_not_issue_the_dependent_permit(api):
    """PRD 2.1: The `X-User-ID` deciding a reopen request must differ from the
    `ordered_by_user_id` recorded on that closure order, and the `X-User-ID`
    issuing a permit must differ from the `decided_by_user_id` recorded on the
    plan review that permit relies on. Either breach is
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
    PRD 3.3: the issuing `X-User-ID` must differ from the `decided_by_user_id` of
    the referenced plan review whenever a `plan_review_id` is present, or the
    request fails the four-eyes rule with `ERR_SEGREGATION_OF_DUTIES`

    Design: Corner/rbac/permit_issue_by_the_plan_review_decider_rejected
    """
    ctx = setup_operator_and_pool(
        operator_overrides={
            "legal_name": "Civic Aquatic Center",
            "contact_email": "permits@civic.example",
        },
        name="Civic Pool",
        requires_plan_review=True,
    )
    review = submit_plan_review(
        ctx["facility_id"], ctx["op_headers"], drawing_reference="DR-9"
    )
    approve_plan_review(review["id"], PLAN_REVIEWER)
    permit = apply_for_permit(
        ctx["facility_id"], ctx["op_headers"], plan_review_id=review["id"]
    )
    advance_permit_to_under_review(permit["id"], ctx["op_headers"])
    pay_operator_balance(
        ctx["operator_id"], ctx["op_headers"], 25000, "Plan review fee"
    )

    validate_error(
        api.transition_permit(
            permit["id"], {"action": "ISSUE"},
            make_admin_headers(PLAN_REVIEWER_ONE_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403,
    )

    refused = read_permit(permit["id"])
    assert refused["status"] == "UNDER_REVIEW"
    assert refused["assessed_fee_cents"] == 0

    issued = validate_success(
        api.transition_permit(permit["id"], {"action": "ISSUE"}, ADMIN)
    )
    assert issued["status"] == "ISSUED"
    assert issued["issued_by_user_id"] == ADMIN_ONE_ID


def test_the_remaining_path_ids_surface_their_own_not_found_codes(api):
    """PRD 2.6: Each `{id}` segment of the request path resolves to a stored row,
    checked strictly left to right; the first unresolved segment decides the
    error. The candidates are `ERR_OPERATOR_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_PLAN_REVIEW_NOT_FOUND`,
    `ERR_INSPECTION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
    `ERR_CLOSURE_ORDER_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_STAFF_ASSIGNMENT_NOT_FOUND` and `ERR_LEDGER_ENTRY_NOT_FOUND`, each HTTP
    404.
    PRD 2.6: Foreign keys supplied in the request body resolve to stored rows,
    checked in the order `facility_id`, then `plan_review_id`, then
    `prior_inspection_id`, then `linked_inspection_id`, then
    `verification_reading_id`, yielding `ERR_FACILITY_NOT_FOUND`,
    `ERR_PLAN_REVIEW_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND` or
    `ERR_READING_NOT_FOUND` (all 404).

    Design: Corner/errors/remaining_path_ids_return_their_own_not_found_codes
    """
    ctx = setup_operator_and_pool()
    order = open_closure_order(ctx["facility_id"], INSPECTOR, "CHEMICAL")

    validate_error(
        api.correct_violation(
            UNKNOWN_UUIDS["violation"], {"correction_note": "n/a"}, ctx["op_headers"]
        ),
        ApiErrorId.ERR_VIOLATION_NOT_FOUND.value, 404,
    )
    validate_error(
        api.cancel_staff_assignment(
            UNKNOWN_UUIDS["staff_assignment"], ctx["op_headers"]
        ),
        ApiErrorId.ERR_STAFF_ASSIGNMENT_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_inspection(UNKNOWN_UUIDS["inspection_alt"], INSPECTOR),
        ApiErrorId.ERR_INSPECTION_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_plan_review(UNKNOWN_UUIDS["plan_review_alt"], PLAN_REVIEWER),
        ApiErrorId.ERR_PLAN_REVIEW_NOT_FOUND.value, 404,
    )
    validate_error(
        api.request_reopen(
            order["id"],
            {"verification_reading_id": UNKNOWN_UUIDS["reading"]},
            ctx["op_headers"],
        ),
        ApiErrorId.ERR_READING_NOT_FOUND.value, 404,
    )

    assert read_closure_order(order["id"])["status"] == "OPEN"
