"""Corner tests for validation priority, idempotency, and pagination envelope."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated, get_success_data,
    reset_clock, create_case_payload, create_case, create_triaged_case,
    create_plan_payload,
    build_user_headers,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
MGR = TEST_USERS["manager_headers"]
HR = TEST_USERS["hr_headers"]
GC = TEST_USERS["gc_headers"]
AUD = TEST_USERS["auditor_headers"]
ADMIN = TEST_USERS["admin_headers"]


def test_auth_missing_role_beats_everything(api):
    """PRD §2.8 step 1: "Authentication — `X-User-Role` and `X-User-ID`
    presence and role recognition (`ERR_UNAUTHENTICATED`)."
    PRD §2.1: "Missing or unknown values are rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.8 orders authentication ahead of state-machine legality (step 6).

    Design: Corner/validations/auth_missing_role_beats_everything
    """
    reset_clock()
    case = create_case(title="AuthP", allegation_category="FRAUD",
                       severity="HIGH", department="Finance")
    bad_headers = build_user_headers("u-x", "UnknownRole")
    resp = api.transition_case(case["id"], {"to_status": "CLOSED"}, bad_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_authorization_beats_existence(api):
    """PRD §2.8: "3. **Authorization** — caller role membership in the
    endpoint's role set (`ERR_UNAUTHORIZED_ROLE`)." precedes "4.
    **Existence** — path ids validated left-to-right, then body-referenced
    ids such as `allegation_id`, `subject_id`, `preservation_notice_id`,
    `target_id`, and elements of `evidence_item_ids` (`ERR_NOT_FOUND`)."
    PRD §3.6: "`GeneralCounsel` designates privilege over an artifact of the
    case by creating a `PrivilegeDesignation`..."

    Design: Corner/validations/authorization_beats_existence
    """
    reset_clock()
    # Investigator not allowed on the privilege-designations endpoint at all
    resp = api.create_privilege_designation(
        "00000000-0000-0000-0000-000000000000",
        {"target_type": "INTERVIEW",
         "target_id": "00000000-0000-0000-0000-000000000001",
         "privilege_type": "ACP"},
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)


def test_idempotency_key_missing_rejected(api):
    """PRD §2.5: "Every POST request must carry an `Idempotency-Key` header.
    A request without one is rejected with `ERR_MISSING_IDEMPOTENCY_KEY`
    (HTTP 400)."

    Design: Corner/validations/idempotency_key_missing_rejected
    """
    reset_clock()
    payload = create_case_payload(
        title="NoKey", allegation_category="FRAUD", severity="LOW",
        lead_investigator_id="inv-lead-1",
    )
    resp = api.create_case(payload, IC, skip_idempotency=True)
    validate_error(resp, ApiErrorId.ERR_MISSING_IDEMPOTENCY_KEY, expected_status=400)


def test_idempotency_replay_same_payload_returns_original(api):
    """PRD §2.5: "When the server receives a key it has already seen, it
    compares the request payload against the original: an identical payload
    returns the original response unchanged, while a different payload is
    rejected with `ERR_IDEMPOTENCY_REPLAY_MISMATCH` (HTTP 409)."

    Design: Corner/validations/idempotency_replay_same_payload_returns_original
    """
    reset_clock()
    payload = create_case_payload(
        title="Idem", allegation_category="FRAUD", severity="LOW",
        department="Ops", lead_investigator_id="inv-lead-1",
    )
    headers = dict(IC)
    headers["Idempotency-Key"] = "K-1"
    r1 = api.create_case(payload, headers)
    c1 = validate_success(r1, expected_status=201)
    r2 = api.create_case(payload, headers)
    c2 = validate_success(r2, expected_status=201)
    assert c1["id"] == c2["id"]
    data, meta = validate_paginated(api.list_cases(IC))
    assert meta["total_count"] == 1


def test_idempotency_replay_mismatch_rejected(api):
    """PRD §2.5: "When the server receives a key it has already seen, it
    compares the request payload against the original: an identical payload
    returns the original response unchanged, while a different payload is
    rejected with `ERR_IDEMPOTENCY_REPLAY_MISMATCH` (HTTP 409)."

    Design: Corner/validations/idempotency_replay_mismatch_rejected
    """
    reset_clock()
    headers = dict(IC)
    headers["Idempotency-Key"] = "K-2"
    payload_a = create_case_payload(
        title="IdemA", allegation_category="FRAUD", severity="LOW",
        department="Ops",
    )
    get_success_data(api.create_case(payload_a, headers))
    payload_b = create_case_payload(
        title="IdemB-DIFFERENT", allegation_category="FRAUD", severity="LOW",
        department="Ops",
    )
    resp = api.create_case(payload_b, headers)
    validate_error(resp, ApiErrorId.ERR_IDEMPOTENCY_REPLAY_MISMATCH, expected_status=409)


def test_response_envelope_and_pagination_defaults(api):
    """PRD §2.3: "All list endpoints accept `limit` and `offset` query
    parameters. `limit` defaults to 10, with a minimum of 1 and a maximum
    of 100. `offset` defaults to 0. List results are sorted by `created_at`
    ascending unless a different sort option is explicitly named in §3. The
    `meta` block of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."
    PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body" with
    `meta.api_request_id`, `meta.api_request_timestamp`, `response_type`,
    and `data` fields populated.

    Design: Corner/endpoints/response_envelope_and_pagination_defaults
    """
    reset_clock()
    for i in range(1, 12):
        payload = create_case_payload(
            title=f"P{i}", allegation_category="FRAUD", severity="LOW",
            department="Ops",
        )
        get_success_data(api.create_case(payload, IC))
    resp = api.list_cases(INV)
    assert resp.status_code == 200
    body = resp.json()
    assert body["response_type"] == "array"
    assert "api_request_id" in body["meta"]
    assert "api_request_timestamp" in body["meta"]
    data, meta = validate_paginated(resp)
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 11
    assert meta["has_more"] is True
    assert len(data) == 10
    # Page 2
    resp2 = api.list_cases(INV, params={"offset": 10})
    data2, meta2 = validate_paginated(resp2)
    assert len(data2) == 1
    assert meta2["has_more"] is False


def test_list_filter_by_status_returns_subset(api):
    """PRD §3.16: "The case list additionally accepts `category`, `severity`,
    `department`, and `lead_investigator_id` filters..." (and §3.16's listing
    narrative establishes the `status` filter pattern over every list
    endpoint, including cases).

    Design: Corner/endpoints/list_filter_by_status_returns_subset
    """
    reset_clock()
    get_success_data(api.create_case(
        create_case_payload(title="FA", allegation_category="FRAUD",
                            severity="LOW", department="Ops"),
        IC,
    ))
    case_b = get_success_data(api.create_case(
        create_case_payload(title="FB", allegation_category="FRAUD",
                            severity="LOW", department="Ops"),
        IC,
    ))
    get_success_data(api.transition_case(
        case_b["id"],
        {"to_status": "TRIAGED", "severity": "LOW", "department": "Ops"},
        IC,
    ))
    data, meta = validate_paginated(api.list_cases(INV, params={"status": "TRIAGED"}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == case_b["id"]
    data2, meta2 = validate_paginated(api.list_cases(INV, params={"status": "INTAKE"}))
    assert meta2["total_count"] == 1


def test_clock_default_is_fixed(api):
    """PRD §2.6: "At server startup the clock reads exactly
    `2026-05-01T00:00:00Z`; before any clock-set call it never falls back to
    wall-clock time."
    PRD §3.5: "On success `upjohn_delivered_at` is set to the current logical
    clock."

    Design: Corner/endpoints/clock_default_is_fixed
    """
    # NOTE: deliberately NO reset_clock call — default clock must be active.
    bundle_case = get_success_data(api.create_case(
        create_case_payload(title="ClockDef", allegation_category="HARASSMENT",
                            severity="MEDIUM", department="Ops"),
        IC,
    ))
    get_success_data(api.transition_case(
        bundle_case["id"],
        {"to_status": "TRIAGED", "severity": "MEDIUM", "department": "Ops"},
        IC,
    ))
    case = get_success_data(api.get_case(bundle_case["id"], IC))
    from test_helpers import create_plan_payload, create_interview_payload
    plan = get_success_data(api.create_plan(
        case["id"], create_plan_payload(expected_case_version=case["version"]), INV
    ))
    from test_helpers import make_investigator_headers, make_manager_headers, TEST_DEFAULTS
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    get_success_data(api.transition_plan(plan["id"], {"to_status": "SUBMITTED"}, inv1))
    get_success_data(api.transition_plan(plan["id"], {"to_status": "APPROVED"}, mgr))
    interview = get_success_data(api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-1", interviewer_id="inv-9",
            scheduled_start="2026-05-10T14:00:00Z",
            scheduled_end="2026-05-10T15:00:00Z",
        ),
        INV,
    ))
    resp = api.transition_interview(interview["id"], {"to_status": "UPJOHN_DELIVERED"}, INV)
    after = validate_success(resp, expected_status=200)
    assert after["upjohn_delivered_at"] == "2026-05-01T00:00:00Z"
