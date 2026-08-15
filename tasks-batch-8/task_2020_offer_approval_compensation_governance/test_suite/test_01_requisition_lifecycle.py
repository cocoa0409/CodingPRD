"""Requisition intake, review stages, and creation defaults."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, assert_requisition,
    create_requisition_payload, create_draft_requisition, create_open_requisition,
)

HM = TEST_USERS["hm_headers"]
HM2 = TEST_USERS["hm2_headers"]
REC = TEST_USERS["recruiter_headers"]
CA = TEST_USERS["comp_analyst_headers"]
FIN = TEST_USERS["finance_headers"]


def test_requisition_creation_defaults(api):
    """PRD §3.1: "The system stamps the creator's `X-User-ID` into
    `hiring_manager_id`, starts the requisition in `DRAFT`, and initializes
    `headcount_filled` to zero, `committed_budget_cents` to zero, and
    `close_reason` to null."

    Design: Corner/entities/requisition_creation_defaults
    """
    resp = api.create_requisition(create_requisition_payload(headcount_authorized=2), HM)
    data = validate_success(resp, expected_status=201)
    assert_requisition(data)
    assert data["status"] == "DRAFT"
    assert data["headcount_filled"] == 0
    assert data["committed_budget_cents"] == 0
    assert data["close_reason"] is None
    assert data["version"] == 1
    assert data["hiring_manager_id"] == "hm-1", (
        f"hiring_manager_id must be captured from X-User-ID, got {data['hiring_manager_id']}"
    )
    # GET returns the identical persisted field set
    fetched = validate_success(api.get_requisition(data["id"], REC))
    assert fetched["id"] == data["id"]
    assert fetched["status"] == "DRAFT"
    assert fetched["hiring_manager_id"] == "hm-1"
    assert fetched["headcount_filled"] == 0
    assert fetched["committed_budget_cents"] == 0


def test_requisition_invalid_role_level_rejected(api):
    """PRD §3.1: "the `role_level` band — one of `L3`, `L4`, `L5`, `L6`, or `L7`".
    PRD §2.10: "types and enum membership valid ... else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/requisition_invalid_enum_role_level_returns_invalid_request
    """
    resp = api.create_requisition(create_requisition_payload(role_level="L9"), HM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_requisition_with_system_fields_rejected(api):
    """PRD §2.10: "Required fields present, unknown fields rejected ... else
    `ERR_INVALID_REQUEST`." PRD §3.1: the server "starts the requisition in
    `DRAFT`" — status is system-owned, not an accepted input.

    Design: Corner/entities/create_requisition_with_system_fields_returns_invalid_request
    """
    payload = create_requisition_payload()
    payload["status"] = "OPEN"
    resp = api.create_requisition(payload, HM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_requisition_double_submit_rejected(api):
    """PRD §3.1: "Submission moves the requisition `DRAFT → BUDGET_REVIEW`".
    PRD §2.10: "requisition-state violations draw `ERR_REQUISITION_INVALID_STATE`".

    Design: Corner/state_machines/requisition_double_submit_returns_invalid_state
    """
    req = create_draft_requisition(HM)
    validate_success(api.submit_requisition(req["id"], HM))
    resp = api.submit_requisition(req["id"], HM)
    validate_error(resp, ApiErrorId.ERR_REQUISITION_INVALID_STATE)
    after = validate_success(api.get_requisition(req["id"], REC))
    assert after["status"] == "BUDGET_REVIEW"


def test_recruiter_cannot_review_decision(api):
    """PRD §3.1: "At the `BUDGET_REVIEW` stage only a `FinanceController` may
    record a review decision; at the `RANGE_APPROVAL` stage only a `CompAnalyst`
    may." PRD §2.10: "Endpoint role membership ... else `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/validations/recruiter_cannot_review_decision
    """
    req = create_draft_requisition(HM)
    validate_success(api.submit_requisition(req["id"], HM))
    resp = api.review_decision_requisition(req["id"], {"decision": "APPROVE"}, REC)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    after = validate_success(api.get_requisition(req["id"], REC))
    assert after["status"] == "BUDGET_REVIEW"


def test_review_decision_stage_role_mismatch(api):
    """PRD §3.1: "At the `BUDGET_REVIEW` stage only a `FinanceController` may
    record a review decision; at the `RANGE_APPROVAL` stage only a `CompAnalyst`
    may." PRD §2.10: "the requisition review decision demands a
    `FinanceController` at the budget stage and a `CompAnalyst` at the range
    stage — else `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/review_decision_stage_role_mismatch
    """
    req = create_draft_requisition(HM)
    validate_success(api.submit_requisition(req["id"], HM))
    # CompAnalyst cannot decide the BUDGET_REVIEW stage
    e1 = api.review_decision_requisition(req["id"], {"decision": "APPROVE"}, CA)
    validate_error(e1, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    # FinanceController advances BUDGET_REVIEW -> RANGE_APPROVAL
    st1 = validate_success(api.review_decision_requisition(req["id"], {"decision": "APPROVE"}, FIN))
    assert st1["status"] == "RANGE_APPROVAL"
    # FinanceController cannot decide the RANGE_APPROVAL stage
    e2 = api.review_decision_requisition(req["id"], {"decision": "APPROVE"}, FIN)
    validate_error(e2, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    # CompAnalyst advances RANGE_APPROVAL -> OPEN
    st2 = validate_success(api.review_decision_requisition(req["id"], {"decision": "APPROVE"}, CA))
    assert st2["status"] == "OPEN"


def test_hm_cannot_pause_others_requisition(api):
    """PRD §3.1: "The owner may pause intake, moving `OPEN → PAUSED` by
    recording a hold `action` of `PAUSE`". PRD §2.10: "a HiringManager confined
    to requisitions they own — else `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/validations/hm_cannot_pause_others_requisition
    """
    req = create_open_requisition(HM)
    resp = api.hold_requisition(req["id"], {"action": "PAUSE"}, HM2)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    after = validate_success(api.get_requisition(req["id"], REC))
    assert after["status"] == "OPEN"


def test_salary_range_incoherent_rejected(api):
    """PRD §3.1: "the band minimum must be positive and strictly below the
    midpoint, the midpoint must not exceed the maximum, the budget must be
    positive, and the authorized headcount must be at least one. Any violation
    is rejected with `ERR_SALARY_RANGE_INVALID`."

    Design: Corner/validations/salary_range_incoherent_rejected
    """
    resp = api.create_requisition(
        create_requisition_payload(salary_min_cents=18000000, salary_mid_cents=15000000), HM
    )
    validate_error(resp, ApiErrorId.ERR_SALARY_RANGE_INVALID)


def test_occ_requisition_patch_stale_version(api):
    """PRD §2.7: "`PATCH /api/requisitions/{id}` — editing a requisition —
    requires `expected_requisition_version` matching the requisition's current
    `version`; a mismatch is rejected with `ERR_STALE_REQUISITION_VERSION`
    (HTTP 412)".
    PRD §3.1: "each successful edit increments the requisition's `version`."

    Design: Corner/complexity_layers/occ_requisition_patch_stale_version
    """
    req = create_draft_requisition(HM, title="Original")
    rv1 = req["version"]
    first = validate_success(
        api.patch_requisition(req["id"], {"expected_requisition_version": rv1, "title": "Second"}, HM)
    )
    assert first["version"] == rv1 + 1
    # Stale replay with the pre-mutation version
    resp = api.patch_requisition(req["id"], {"expected_requisition_version": rv1, "title": "Third"}, HM)
    validate_error(resp, ApiErrorId.ERR_STALE_REQUISITION_VERSION)
    # Fresh version chains forward
    third = validate_success(
        api.patch_requisition(
            req["id"], {"expected_requisition_version": first["version"], "title": "Third"}, HM
        )
    )
    assert third["version"] == first["version"] + 1
    assert third["title"] == "Third"
