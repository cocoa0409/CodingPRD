"""Auth / RBAC, cross-entity and temporal validations, and the not-found / state error
catalogue surface.

Queue B (Corner): validations, rbac, errors.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_inspector, create_establishment, create_permitted_establishment,
    create_establishment_with_approved_plan,
    setup_inspection_in_progress, open_enforcement_case, setup_case_hearing_scheduled,
    schedule_inspection, set_clock,
    create_establishment_payload, create_plan_review_payload, create_permit_payload,
    create_violation_payload,
    TEST_USERS, make_inspector_headers,
)

CLERK = TEST_USERS["permit_clerk_headers"]
DIRECTOR = TEST_USERS["health_director_headers"]
OFFICER = TEST_USERS["enforcement_officer_headers"]
INSPECTOR_SHARED = TEST_USERS["inspector_headers"]


# ─── validations ─────────────────────────────────────────────────────────────
def test_missing_user_context_rejected(api):
    """PRD §2.1: "If either header is missing or empty, the request is rejected with
    `ERR_MISSING_USER_CONTEXT`."

    Design: Corner/validations/val_missing_user_context_header
    """
    res = api.create_establishment(
        create_establishment_payload(name="Diner E1", address="1 Main St", seating_capacity=40),
        headers={})
    validate_error(res, "ERR_MISSING_USER_CONTEXT", expected_status=401)


def test_reinspection_target_must_be_finalized(api):
    """PRD §3.4: "A reinspection must additionally name a `reinspection_of_id`, and that
    referenced inspection must be a prior `FINALIZED` inspection of the same establishment;
    if it is not, scheduling is rejected with `ERR_INVALID_REINSPECTION_TARGET`."

    A REINSPECTION whose reinspection_of_id points at a still-SCHEDULED inspection is
    rejected.

    Design: Corner/validations/val_reinspection_target_must_be_same_establishment_finalized
    """
    inspector = create_inspector()
    est, _, _ = create_permitted_establishment()
    routine = schedule_inspection(est["id"], inspector["id"], 0, "ROUTINE")
    res = api.create_inspection(
        {"establishment_id": est["id"], "inspector_id": inspector["id"],
         "inspection_type": "REINSPECTION", "scheduled_index": 1,
         "reinspection_of_id": routine["id"]}, CLERK)
    validate_error(res, "ERR_INVALID_REINSPECTION_TARGET", expected_status=409)


def test_hearing_in_past_rejected(api):
    """PRD §3.10: "scheduling requires the case to be `OPENED` (otherwise
    `ERR_CASE_NOT_OPENED`) and requires the `hearing_index` to be no earlier than the
    current clock index (otherwise `ERR_HEARING_IN_PAST`)."

    Scheduling a hearing at index 250 while the clock is at 300 is rejected.

    Design: Corner/validations/val_hearing_in_past_rejected
    """
    set_clock(300)
    est, _, _ = create_permitted_establishment()
    case = open_enforcement_case(est["id"], 10000)
    res = api.schedule_hearing(case["id"], {"hearing_index": 250}, OFFICER)
    validate_error(res, "ERR_HEARING_IN_PAST", expected_status=409)


def test_permit_requires_approved_plan_review(api):
    """PRD §3.3: "It requires that the establishment currently be `PRELICENSE` (otherwise
    `ERR_ESTABLISHMENT_NOT_PRELICENSE`) and that the referenced plan review both belong to
    this establishment and be in the `APPROVED` status (otherwise
    `ERR_PLAN_REVIEW_NOT_APPROVED`)."

    Issuing a permit against a SUBMITTED (not yet APPROVED) plan review is rejected; the
    establishment stays PRELICENSE.

    Design: Corner/validations/val_permit_requires_approved_plan_review
    """
    est = create_establishment()
    pr = validate_success(api.create_plan_review(create_plan_review_payload(est["id"]), CLERK), 201)
    res = api.create_permit(create_permit_payload(est["id"], pr["id"]), CLERK)
    validate_error(res, "ERR_PLAN_REVIEW_NOT_APPROVED", expected_status=409)
    after = validate_success(api.get_establishment(est["id"], CLERK), 200)
    assert after["status"] == "PRELICENSE", f"establishment stays PRELICENSE, got {after['status']}"


def test_reject_plan_review_requires_reason(api):
    """PRD §3.2: "requires a non-empty `rejection_reason` in the request, which is recorded
    on the plan review — a missing or empty reason yields `ERR_MISSING_REJECTION_REASON`."

    Rejecting with an empty rejection_reason is rejected; the plan review stays SUBMITTED.

    Design: Corner/validations/val_reject_requires_rejection_reason
    """
    est = create_establishment()
    pr = validate_success(api.create_plan_review(create_plan_review_payload(est["id"]), CLERK), 201)
    res = api.reject_plan_review(pr["id"], {"rejection_reason": ""}, CLERK)
    validate_error(res, "ERR_MISSING_REJECTION_REASON", expected_status=400)
    after = validate_success(api.get_plan_review(pr["id"], CLERK), 200)
    assert after["status"] == "SUBMITTED", f"plan review stays SUBMITTED, got {after['status']}"


# ─── rbac ─────────────────────────────────────────────────────────────────────
def test_inspector_cannot_create_establishment(api):
    """PRD §2.1: "When a syntactically valid request is made by a role that is not
    permitted to perform the requested operation, the system responds with
    `ERR_FORBIDDEN_ROLE`."
    PRD §2.1: "A `PermitClerk` is the front-office operator: it creates and updates
    establishments".

    An Inspector calling POST /establishments (a PermitClerk operation) is forbidden.

    Design: Corner/rbac/rbac_inspector_cannot_create_establishment
    """
    inspector = create_inspector()
    res = api.create_establishment(
        create_establishment_payload(name="Diner E1", address="1 Main St", seating_capacity=40),
        make_inspector_headers(inspector["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_permit_clerk_cannot_rule_hearing(api):
    """PRD §2.1: "When a syntactically valid request is made by a role that is not
    permitted to perform the requested operation, the system responds with
    `ERR_FORBIDDEN_ROLE`."
    PRD §3.10: "Once the scheduled day has arrived, the `HealthDirector` issues a `ruling`".

    A PermitClerk calling POST /enforcement-cases/{id}/rule (a HealthDirector operation) is
    forbidden.

    Design: Corner/rbac/rbac_permit_clerk_cannot_rule_hearing
    """
    est, case = setup_case_hearing_scheduled(alleged_penalty_cents=10000, hearing_index=405, open_index=400)
    set_clock(405)
    res = api.rule_enforcement_case(case["id"], {"ruling": "UPHELD"}, CLERK)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_inspector_must_be_assigned_to_start(api):
    """PRD §2.1: "only the inspector whose `id` equals an inspection's `inspector_id` may
    start that inspection; a mismatch is rejected with `ERR_NOT_ASSIGNED_INSPECTOR`."

    Inspector i2 cannot start an inspection assigned to i1.

    Design: Corner/rbac/rbac_inspector_must_be_assigned_to_start
    """
    i1 = create_inspector(full_name="Ivy One", badge_number="B-001")
    i2 = create_inspector(full_name="Ike Two", badge_number="B-002")
    est, _, _ = create_permitted_establishment()
    inspection = schedule_inspection(est["id"], i1["id"], 0, "ROUTINE")
    res = api.start_inspection(inspection["id"], make_inspector_headers(i2["id"]))
    validate_error(res, "ERR_NOT_ASSIGNED_INSPECTOR", expected_status=403)
    after = validate_success(api.get_inspection(inspection["id"], CLERK), 200)
    assert after["status"] == "SCHEDULED", f"rejected start leaves SCHEDULED, got {after['status']}"


# ─── errors ─────────────────────────────────────────────────────────────────
def test_violation_unknown_code_not_found(api):
    """PRD §2.5: "Foreign keys supplied in a request body — `fda_code_id`, ... — must
    reference existing rows; an unknown body foreign key yields the matching not-found
    error with HTTP status 404."
    PRD §2.5: "an unknown identifier yields the corresponding not-found error (for example
    ... `ERR_CODE_NOT_FOUND` ...)."

    Recording a violation citing an unknown fda_code_id is rejected with ERR_CODE_NOT_FOUND.

    Design: Corner/errors/err_code_not_found_on_violation_create
    """
    est, inspector, inspection = setup_inspection_in_progress(scheduled_index=0)
    res = api.create_violation(
        create_violation_payload(inspection["id"], "00000000-0000-4000-8000-0000000000aa",
                                 corrected_on_site=False),
        make_inspector_headers(inspector["id"]))
    validate_error(res, "ERR_CODE_NOT_FOUND", expected_status=404)


def test_rule_before_hearing_reached_rejected(api):
    """PRD §3.10: "ruling requires the case to be `HEARING_SCHEDULED` (otherwise
    `ERR_CASE_NOT_SCHEDULED`), requires the current clock index to have reached the
    `hearing_index` (otherwise `ERR_HEARING_NOT_REACHED`)".

    Ruling on a HEARING_SCHEDULED case at index 500 while the clock is still 450 is
    rejected with ERR_HEARING_NOT_REACHED.

    Design: Corner/errors/err_hearing_not_reached_on_rule
    """
    est, case = setup_case_hearing_scheduled(alleged_penalty_cents=10000, hearing_index=500, open_index=450)
    # Clock is still at 450 (open_index) — below the hearing_index.
    res = api.rule_enforcement_case(case["id"], {"ruling": "UPHELD"}, DIRECTOR)
    validate_error(res, "ERR_HEARING_NOT_REACHED", expected_status=409)
    after = validate_success(api.get_enforcement_case(case["id"], DIRECTOR), 200)
    assert after["status"] == "HEARING_SCHEDULED", f"status unchanged, got {after['status']}"
