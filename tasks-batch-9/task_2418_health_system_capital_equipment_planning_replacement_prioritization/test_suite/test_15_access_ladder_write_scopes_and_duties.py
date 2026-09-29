"""Who may call what: the head of the rule ladder, the two write scopes and the split of duties."""

from test_helpers import (
    TEST_USERS,
    UNKNOWN_UUID,
    ApiErrorId,
    UserRole,
    assert_cents,
    assert_decimal,
    blank_user_headers,
    cast_vote,
    close_voting,
    get_success_data,
    live_allocation,
    make_clinical_requester_headers,
    make_committee_member_headers,
    make_department,
    make_facility,
    make_facility_director_headers,
    make_member,
    pin_clock,
    refresh_asset,
    refresh_cycle,
    refresh_request,
    setup_allocated_cycle,
    setup_draft_request,
    setup_scored_request,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
_PLANNER = TEST_USERS["planner_headers"]
_ALLOCATOR = TEST_USERS["planner_alloc_headers"]
_FUNDER = TEST_USERS["planner_fund_headers"]
_AUDITOR = TEST_USERS["auditor_headers"]


def _scored_request_with_one_seated_chair():
    """The canonical SCORED request plus a single unscoped chair."""
    ctx = setup_scored_request()
    ctx["chair"] = make_member("CHAIR", 3, full_name="Dana Okafor")
    return ctx


def _one_request_read_from_two_facilities():
    """An ALLOCATED cycle holding one NRH request, with a second facility that raised nothing."""
    ctx = setup_allocated_cycle(allocation_method="RANK_ORDERED")
    ctx["other_facility"] = make_facility(
        name="South Metro Center", code="SMC", region="SOUTH", max_concurrent_construction=1
    )
    ctx["other_department"] = make_department(
        ctx["other_facility"]["id"], name="Diagnostic Imaging MRI", modality_scope="MRI"
    )
    ctx["chair"] = make_member("CHAIR", 3, full_name="Dana Okafor")
    return ctx


def _draft_request_beside_a_neighbouring_department():
    """A DRAFT request owned by NRH/DEPT-A1 while SMC/DEPT-B1 looks on."""
    ctx = setup_draft_request()
    ctx["other_facility"] = make_facility(
        name="South Metro Center", code="SMC", region="SOUTH", max_concurrent_construction=1
    )
    ctx["other_department"] = make_department(
        ctx["other_facility"]["id"], name="Diagnostic Imaging MRI", modality_scope="MRI"
    )
    return ctx


# ─── The first three rungs ────────────────────────────────────────────


def test_a_blank_identity_a_wrong_role_and_a_missing_row_answer_in_that_order(api):
    """PRD §2.1: "When `X-User-ID` is absent or blank the request is rejected with
    `ERR_USER_CONTEXT_REQUIRED` (HTTP 401)."
    PRD §2.1: "When the acting role is not among the roles the target endpoint authorizes, the
    request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "These two checks precede every other check in the system, in that order."
    PRD §2.11: "1. `X-User-ID` absent or blank, on every endpoint — `ERR_USER_CONTEXT_REQUIRED`,
    401."
    PRD §2.11: "2. Acting role not authorized for the endpoint, on every endpoint —
    `ERR_UNAUTHORIZED`, 403."
    PRD §2.11: "3. A templated path identifier that resolves to no row — that entity's not-found
    error, 404."

    Design: Corner/rbac/identity_then_role_then_existence_is_the_first_three_rungs_of_the_ladder
    """
    pin_clock(CLOCK)

    validate_error(
        api.fund_request(UNKNOWN_UUID, blank_user_headers(UserRole.CAPITAL_PLANNER.value)),
        ApiErrorId.ERR_USER_CONTEXT_REQUIRED.value, 401,
    )
    validate_error(
        api.list_cycles(blank_user_headers(UserRole.COMPLIANCE_AUDITOR.value)),
        ApiErrorId.ERR_USER_CONTEXT_REQUIRED.value, 401,
    )

    rows, meta = validate_paginated(api.list_cycles(_AUDITOR))
    assert rows == []
    assert meta["total_count"] == 0

    validate_error(
        api.fund_request(UNKNOWN_UUID, _AUDITOR),
        ApiErrorId.ERR_UNAUTHORIZED.value, 403,
    )
    validate_error(
        api.fund_request(UNKNOWN_UUID, _FUNDER),
        ApiErrorId.ERR_REQUEST_NOT_FOUND.value, 404,
    )


def test_each_role_is_refused_the_operations_that_belong_to_the_others(api):
    """PRD §2.1: "There are exactly five roles: `CapitalPlanner`, `ClinicalRequester`,
    `FacilityDirector`, `CommitteeMember` and `ComplianceAuditor`."
    PRD §2.1: "When `X-User-Role` is `ComplianceAuditor`, `X-User-ID` is an opaque auditor
    identifier not tied to any persisted entity. The server neither records nor compares it; the
    auditor owns the post-implementation utilization audit and nothing else."
    PRD §2.11: "2. Acting role not authorized for the endpoint, on every endpoint —
    `ERR_UNAUTHORIZED`, 403."
    PRD §2.11: "4. A body-borne reference that resolves to no row — the referenced entity's
    not-found error, 404."
    PRD §2.11: "Nothing later in the order is evaluated, and no side effect is written."

    Design: Corner/rbac/each_role_is_refused_every_other_roles_exclusive_operation
    """
    ctx = _scored_request_with_one_seated_chair()
    scored_version = ctx["request"]["version"]
    requester = make_clinical_requester_headers(ctx["department"]["id"])
    director = make_facility_director_headers(ctx["facility"]["id"])
    member = make_committee_member_headers(ctx["chair"]["id"])
    ballot = {"vote": "APPROVE", "expected_request_version": scored_version}

    refusals = (
        api.fund_request(ctx["request"]["id"], _AUDITOR),
        api.screen_request(ctx["request"]["id"], {"decision": "RETURN"}, requester),
        api.create_vote(ctx["request"]["id"], ballot, director),
        api.create_audit(
            ctx["request"]["id"],
            {"installation_project_id": UNKNOWN_UUID,
             "audit_window_start": "2027-06-01T00:00:00Z",
             "audit_window_end": "2027-12-01T00:00:00Z"},
            member,
        ),
        api.create_service_event(
            ctx["asset"]["id"],
            {"event_date": "2026-07-01T00:00:00Z", "category": "CORRECTIVE",
             "downtime_hours": 4.00},
            director,
        ),
        api.create_vote(ctx["request"]["id"], ballot, _PLANNER),
    )
    for response in refusals:
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    assert get_success_data(api.list_request_votes(ctx["request"]["id"], _AUDITOR)) == []

    asset = get_success_data(api.get_asset(ctx["asset"]["id"], _AUDITOR))
    assert asset["corrective_count_24m"] == 0
    assert_decimal(asset["downtime_hours_24m"], 0.00, "downtime_hours_24m")
    assert_decimal(asset["service_penalty_points"], 0.00, "service_penalty_points")
    assert_decimal(asset["adjusted_ruls_score"], 25.00, "adjusted_ruls_score")
    assert asset["version"] == 1

    request = get_success_data(api.get_request(ctx["request"]["id"], _AUDITOR))
    assert request["status"] == "SCORED"
    assert request["version"] == scored_version


def test_every_role_reads_the_same_rows_with_the_same_payload(api):
    """PRD §2.1: "When `X-User-Role` is `ClinicalRequester`, `X-User-ID` is the `id` of the acting
    `Department`; ownership checks on any resource that references a `Department` compare the
    resource's `department_id` to `X-User-ID`."
    PRD §2.11: "5. A `ClinicalRequester` acting on a request whose `department_id` is not the
    acting `X-User-ID`, on request creation, request patch, request submit and request withdraw —
    `ERR_DEPARTMENT_SCOPE_VIOLATION`, 403."
    PRD §2.11: "6. A `FacilityDirector` acting on a project whose `facility_id` is not the acting
    `X-User-ID`, on project creation, project patch, construction advance, equipment advance and
    go-live — `ERR_FACILITY_SCOPE_VIOLATION`, 403."
    PRD §3.6: "Allocation rows can be read individually and listed filtered by `cycle_id`,
    `facility_id`, `posture` and `contingency_status`."
    PRD §3.5: "The score history of a request is readable in `created_at` ascending order and can
    be filtered by `reason`."

    Design: Corner/rbac/all_five_roles_share_every_get_on_the_same_rows
    """
    ctx = _one_request_read_from_two_facilities()
    foreign_requester = make_clinical_requester_headers(ctx["other_department"]["id"])
    foreign_director = make_facility_director_headers(ctx["other_facility"]["id"])
    member = make_committee_member_headers(ctx["chair"]["id"])

    readings = [
        get_success_data(api.get_request(ctx["request"]["id"], headers))
        for headers in (_PLANNER, foreign_requester, foreign_director, member, _AUDITOR)
    ]
    for reading in readings:
        assert reading == readings[0], "no field is masked or omitted for any role"
    assert readings[0]["id"] == ctx["request"]["id"]
    assert readings[0]["status"] == "SCORED"
    assert_decimal(readings[0]["composite_score"], 39.69, "composite_score")

    allocations = get_success_data(
        api.list_allocations(foreign_requester, params={"cycle_id": ctx["cycle"]["id"]})
    )
    assert len(allocations) == 1
    assert allocations[0]["facility_id"] == ctx["facility"]["id"]
    assert_cents(allocations[0]["allocated_cents"], 100000000, "allocated_cents")

    assets = get_success_data(
        api.list_assets(foreign_director, params={"facility_id": ctx["facility"]["id"]})
    )
    assert len(assets) == 1
    assert assets[0]["id"] == ctx["asset"]["id"]

    scores = get_success_data(api.list_request_scores(ctx["request"]["id"], member))
    assert len(scores) == 1
    assert scores[0]["sequence"] == 1


# ─── The two write scopes ─────────────────────────────────────────────


def test_a_neighbours_write_is_refused_before_its_body_or_the_row_state_is_read(api):
    """PRD §2.1: "A requester acting on a replacement request whose `department_id` differs from
    `X-User-ID` is rejected with `ERR_DEPARTMENT_SCOPE_VIOLATION` (HTTP 403)."
    PRD §2.1: "A director acting on an installation project whose `facility_id` differs from
    `X-User-ID` is rejected with `ERR_FACILITY_SCOPE_VIOLATION` (HTTP 403). On project creation the
    comparison is made against the facility the project will belong to, which is the facility of
    the funded request's department."
    PRD §2.11: "7. A required input absent, a field of the wrong JSON type, an enum value outside
    its declared set, a string outside its length bounds or a number outside its declared range, on
    every write endpoint — `ERR_VALIDATION`, 422."
    PRD §2.11: "16. The replacement request not in the state set the operation requires, on every
    request transition endpoint and on quote creation, installation-project creation and audit
    creation — `ERR_REQUEST_INVALID_STATE`, 409."
    PRD §3.4: "Submission also writes `baseline_year1_opex_cents` as the year-one service cost plus
    the year-one disposables cost of the authoritative variant, which at submission time is the
    budgetary one; this figure is the business-case baseline the post-implementation audit measures
    actual operating cost against."

    Design: Corner/rbac/department_and_facility_write_scopes_outrank_body_shape
    """
    ctx = _draft_request_beside_a_neighbouring_department()
    owner = make_clinical_requester_headers(ctx["department"]["id"])
    neighbour = make_clinical_requester_headers(ctx["other_department"]["id"])
    foreign_director = make_facility_director_headers(ctx["other_facility"]["id"])
    draft_version = ctx["request"]["version"]

    validate_error(
        api.patch_request(
            ctx["request"]["id"],
            {"clinical_justification": "Reassigned to the cath lab programme."},
            neighbour,
        ),
        ApiErrorId.ERR_DEPARTMENT_SCOPE_VIOLATION.value, 403,
    )
    validate_error(
        api.patch_request(ctx["request"]["id"], {"projected_annual_volume": -5}, neighbour),
        ApiErrorId.ERR_DEPARTMENT_SCOPE_VIOLATION.value, 403,
    )
    validate_error(
        api.submit_request(ctx["request"]["id"], neighbour),
        ApiErrorId.ERR_DEPARTMENT_SCOPE_VIOLATION.value, 403,
    )
    validate_error(
        api.create_installation_project(
            ctx["request"]["id"],
            {"downtime_start": "2026-09-01T00:00:00Z", "downtime_end": "2026-09-02T00:00:00Z"},
            foreign_director,
        ),
        ApiErrorId.ERR_FACILITY_SCOPE_VIOLATION.value, 403,
    )

    submitted = validate_success(api.submit_request(ctx["request"]["id"], owner))
    assert submitted["status"] == "SUBMITTED"
    assert_cents(submitted["budgetary_tco_cents"], 160106313, "budgetary_tco_cents")

    validate_error(
        api.withdraw_request(
            ctx["request"]["id"], neighbour, {"withdrawal_reason": "Not our capital."}
        ),
        ApiErrorId.ERR_DEPARTMENT_SCOPE_VIOLATION.value, 403,
    )

    final = refresh_request(ctx["request"]["id"])
    assert final["status"] == "SUBMITTED"
    assert final["clinical_justification"] == ctx["request"]["clinical_justification"]
    assert final["projected_annual_volume"] == 2000
    assert final["revision_count"] == 0
    assert final["version"] == draft_version + 1

    assert get_success_data(
        api.list_installation_projects(_PLANNER, params={"request_id": ctx["request"]["id"]})
    ) == []


def test_the_planner_who_allocated_the_cycle_may_never_draw_from_it(api):
    """PRD §2.9: "The `X-User-ID` recorded in `allocated_by_user_id` when an allocation run
    completes is barred from funding any request in that cycle; such an attempt is rejected with
    `ERR_SOD_ALLOCATOR_CANNOT_FUND` (HTTP 403)."
    PRD §2.1: "When `X-User-Role` is `CapitalPlanner`, `X-User-ID` is an opaque planner identifier
    not tied to any persisted entity."
    PRD §3.9: "The acting planner's `X-User-ID` must differ from the cycle's
    `allocated_by_user_id`."
    PRD §2.11: "32. The allocating planner attempting to fund, on request fund —
    `ERR_SOD_ALLOCATOR_CANNOT_FUND`, 403."
    PRD §2.11: "16. The replacement request not in the state set the operation requires, on every
    request transition endpoint and on quote creation, installation-project creation and audit
    creation — `ERR_REQUEST_INVALID_STATE`, 409."
    PRD §3.9: "Where the draw brings the allocation's `available_cents` exactly to zero, that row's
    `posture` moves to `EXHAUSTED`."

    Design: Corner/rbac/the_planner_who_allocated_the_cycle_cannot_fund_from_it
    """
    ctx = setup_allocated_cycle(allocation_method="RANK_ORDERED")
    chair = make_member("CHAIR", 3, full_name="Dana Okafor")
    assert refresh_cycle(ctx["cycle"]["id"])["allocated_by_user_id"] == "planner-alloc"

    validate_error(
        api.fund_request(ctx["request"]["id"], _ALLOCATOR),
        ApiErrorId.ERR_REQUEST_INVALID_STATE.value, 409,
    )

    cast_vote(ctx["request"]["id"], chair["id"], "APPROVE")
    approved = close_voting(ctx["request"]["id"], chair["id"])
    assert approved["status"] == "APPROVED"

    validate_error(
        api.fund_request(ctx["request"]["id"], _ALLOCATOR),
        ApiErrorId.ERR_SOD_ALLOCATOR_CANNOT_FUND.value, 403,
    )
    barred = refresh_request(ctx["request"]["id"])
    assert barred["status"] == "APPROVED"
    assert_cents(barred["funded_amount_cents"], 0, "funded_amount_cents")

    funded = validate_success(api.fund_request(ctx["request"]["id"], _FUNDER))
    assert funded["status"] == "FUNDED"
    assert_cents(funded["funded_amount_cents"], 100000000, "funded_amount_cents")
    assert refresh_asset(ctx["asset"]["id"])["status"] == "REPLACEMENT_PENDING"

    allocation = live_allocation(ctx["cycle"]["id"], ctx["facility"]["id"])
    assert_cents(allocation["committed_cents"], 100000000, "committed_cents")
    assert_cents(allocation["available_cents"], 0, "available_cents")
    assert allocation["posture"] == "EXHAUSTED"
    assert len(
        get_success_data(api.list_allocations(_PLANNER, params={"cycle_id": ctx["cycle"]["id"]}))
    ) == 1
