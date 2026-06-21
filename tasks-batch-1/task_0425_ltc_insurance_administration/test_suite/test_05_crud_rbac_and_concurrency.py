"""CRUD/input validation, RBAC, reverse-reachability links, and OCC concurrency.

Queue B (Corner): entities, rbac, endpoints, cross_cutting_complexity_layers.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    create_policyholder,
    create_policy,
    create_issued_policy,
    create_eligible_provider,
    author_and_activate_care_plan,
    open_claim,
    add_lines,
    setup_active_claimable_policy,
    read_partnership_disregard,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]
CE = TEST_USERS["claims_examiner_headers"]
CA = TEST_USERS["care_assessor_headers"]
REG = TEST_USERS["regulator_headers"]


# ===========================================================================
# Corner/entities
# ===========================================================================
def test_create_policy_returns_201_with_initial_fields(api):
    """PRD 3.1: "A freshly created policy sits in `coverage_status` `APPLIED` and
    `premium_status` `PENDING`, with `inflation_years_elapsed` at 0."
    PRD 2.4: "a `version` (an integer that starts at 1 and increments by 1 on each
    mutation)."

    Design: Corner/entities/create_policy_returns_201_with_all_fields
    """
    ph = create_policyholder(full_name="Cre Ate")
    res = api.create_policy(
        {"policyholder_id": ph["id"], "product_mode": "REIMBURSEMENT",
         "daily_benefit_max_cents": 20000, "monthly_benefit_max_cents": 600000,
         "initial_pool_cents": 10000000, "inflation_rider": "NONE",
         "elimination_period_days": 90}, UW)
    policy = validate_success(res, 201)
    assert policy["coverage_status"] == "APPLIED", policy
    assert policy["premium_status"] == "PENDING", policy
    assert policy["version"] == 1, policy


def test_get_policy_not_found(api):
    """PRD 2.7: "The first identifier in the path that does not resolve to an
    existing resource produces `ERR_NOT_FOUND`."

    Design: Corner/entities/get_policy_not_found_returns_404
    """
    res = api.get_policy(NON_EXISTENT_UUID, UW)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_policy_missing_required_field(api):
    """PRD 3.13: "Request-shape validation comes fourth: a body missing a required
    field, carrying an out-of-range enum, or carrying a negative integer where a
    non-negative one is required yields `ERR_INVALID_REQUEST`"

    Omitting the required product_mode -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_policy_missing_required_field_returns_invalid_request
    """
    ph = create_policyholder(full_name="Miss Field")
    res = api.create_policy(
        {"policyholder_id": ph["id"], "daily_benefit_max_cents": 20000,
         "monthly_benefit_max_cents": 600000, "initial_pool_cents": 10000000,
         "inflation_rider": "NONE", "elimination_period_days": 90}, UW)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_policy_invalid_inflation_rider_enum(api):
    """PRD 3.1: "The `inflation_rider` is one of `NONE`, `COMPOUND_3PCT`, or
    `COMPOUND_5PCT`."
    PRD 3.13: "a body missing a required field, carrying an out-of-range enum, or
    carrying a negative integer where a non-negative one is required yields
    `ERR_INVALID_REQUEST`"

    Design: Corner/entities/create_policy_invalid_enum_inflation_rider_returns_invalid_request
    """
    ph = create_policyholder(full_name="Bad Enum")
    res = api.create_policy(
        {"policyholder_id": ph["id"], "product_mode": "REIMBURSEMENT",
         "daily_benefit_max_cents": 20000, "monthly_benefit_max_cents": 600000,
         "initial_pool_cents": 10000000, "inflation_rider": "COMPOUND_7PCT",
         "elimination_period_days": 90}, UW)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_non_partnership_policy_has_no_disregard(api):
    """PRD 3.1: "an optional `is_partnership_policy` flag that defaults to false."
    PRD 3.1: "If the application is marked as a partnership policy, the system also
    creates a `PartnershipDisregard` record for it in `disregard_status`
    `ACCRUING` with `protected_asset_cents` at 0."

    Omitting is_partnership_policy leaves it false and creates no disregard.

    Design: Corner/entities/create_policy_defaults_is_partnership_false
    """
    ph = create_policyholder(full_name="Def Ault")
    policy = create_policy(ph["id"])  # factory omits is_partnership_policy
    assert policy["is_partnership_policy"] is False, policy

    disregards, meta = read_partnership_disregard(policy["id"], headers=UW)
    assert meta["total_count"] == 0, meta
    assert disregards == [], disregards


def test_system_fields_minted_on_create(api):
    """PRD 3.1: "A freshly created policy sits in `coverage_status` `APPLIED`"
    PRD 2.4: "a `version` (an integer that starts at 1 and increments by 1 on each
    mutation)."

    Design: Corner/entities/system_fields_minted_on_create_input_ignored
    """
    ph = create_policyholder(full_name="Sys Fld")
    policy = create_policy(ph["id"], product_mode="INDEMNITY")
    assert policy["coverage_status"] == "APPLIED", policy
    assert policy["version"] == 1, policy


def test_list_policies_paginated_envelope(api):
    """PRD 2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD 2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_policies_paginated_envelope
    """
    ph = create_policyholder(full_name="Lis Ter")
    create_policy(ph["id"], product_mode="REIMBURSEMENT")
    create_policy(ph["id"], product_mode="INDEMNITY")

    data, meta = validate_paginated(api.list_policies(UW, params={"policyholder_id": ph["id"]}))
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is False, meta
    assert len(data) == 2, data


# ===========================================================================
# Corner/rbac
# ===========================================================================
def test_claims_examiner_cannot_issue_policy(api):
    """PRD 2.1: "If the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."
    PRD 4 (endpoint table): "POST `/policies/{id}/issue` ... Underwriter".

    Design: Corner/rbac/claims_examiner_cannot_issue_policy
    """
    ph = create_policyholder(full_name="Rb Ac")
    policy = create_policy(ph["id"])
    res = api.issue_policy(policy["id"], CE)
    validate_error(res, "ERR_UNAUTHORIZED")


def test_underwriter_cannot_adjudicate_filing(api):
    """PRD 2.1: "If the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."
    PRD 4 (endpoint table): "POST `/rate-filings/{id}/adjudicate` ... Regulator".

    Design: Corner/rbac/underwriter_cannot_adjudicate_rate_filing
    """
    ph = create_policyholder(full_name="Uw Adj")
    policy = create_issued_policy(ph["id"])
    filing = get_success_data(api.create_rate_filing(
        {"policy_id": policy["id"], "requested_increase_pct": 40, "effective_period_index": 1}, UW))
    version = validate_success(api.get_policy(policy["id"], UW))["version"]
    res = api.adjudicate_rate_filing(
        filing["id"], {"granted_pct": 40, "expected_policy_version": version}, UW)
    validate_error(res, "ERR_UNAUTHORIZED")


def test_missing_auth_headers_unauthenticated(api):
    """PRD 2.1: "Every request must be authenticated through two mandatory HTTP
    headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`,
    which declares the operational capacity in which they act. If either header is
    missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.list_policies({})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ===========================================================================
# Corner/endpoints — reverse-reachability links
# ===========================================================================
def test_list_claim_lines_returns_added_line(api):
    """PRD 3.5: "Lines can be listed for a claim."

    GET /claims/{id}/lines returns the claim's lines as an array including the
    added line.

    Design: Corner/endpoints/fk_claim_lines_reverse_reachable
    """
    ctx = setup_active_claimable_policy()
    claim = open_claim(ctx["pol_id"], ctx["cp_id"], service_month="2026-03")
    line = get_success_data(api.add_claim_line(
        claim["id"], {"service_date": "2026-03-01", "billed_charge_cents": 15000}, CE))

    data, _ = validate_paginated(api.list_claim_lines(claim["id"], CE))
    matches = [l for l in data if l["id"] == line["id"]]
    assert len(matches) == 1, data
    assert matches[0]["service_date"] == "2026-03-01", matches[0]


def test_list_certifications_filtered_by_supersedes(api):
    """PRD 3.3: "They can be listed for a policy newest-first, read individually,
    or listed across the system filtered by `policy_id` and by `supersedes_id`."

    GET /trigger-certifications?supersedes_id=cert1 returns the superseding cert2.

    Design: Corner/endpoints/fk_trigger_certifications_supersedes_filtered_list
    """
    ph = create_policyholder(full_name="Sup Cert")
    policy = create_issued_policy(ph["id"])
    cert1 = get_success_data(api.create_trigger_certification(
        policy["id"], {"adl_deficiencies": ["BATHING", "DRESSING"], "cognitive_impairment": False}, CA))
    cert2 = get_success_data(api.create_trigger_certification(
        policy["id"],
        {"adl_deficiencies": ["BATHING", "DRESSING", "EATING"], "cognitive_impairment": False,
         "supersedes_id": cert1["id"]}, CA))

    data, _ = validate_paginated(api.list_trigger_certifications(CA, params={"supersedes_id": cert1["id"]}))
    ids = [c["id"] for c in data]
    assert cert2["id"] in ids, data


def test_create_claim_unknown_policy_not_found(api):
    """PRD 2.7: "After the path is validated, any foreign-key identifiers supplied
    in the body are checked for existence in the same way, and a missing referent
    likewise yields `ERR_NOT_FOUND`."

    A claim referencing a non-existent policy_id -> ERR_NOT_FOUND (FK existence
    before the OCC version check).

    Design: Corner/endpoints/create_claim_unknown_policy_returns_not_found
    """
    ph = create_policyholder(full_name="Bad Pol")
    provider = create_eligible_provider()
    policy = create_issued_policy(ph["id"])
    plan = author_and_activate_care_plan(policy["id"], provider["id"])

    res = api.create_claim(
        {"policy_id": "00000000-0000-4000-8000-000000000abc", "care_plan_id": plan["id"],
         "service_month": "2026-03", "expected_policy_version": policy["version"]}, CE)
    validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# Corner/cross_cutting_complexity_layers — OCC
# ===========================================================================
def test_open_claim_with_stale_version_rejected(api):
    """PRD 2.5: "A claim-open request must carry `expected_policy_version` holding
    the client's last observed `version` of the target `Policy`. If another writer
    has advanced the policy's `version` since that read ... the open is rejected
    with `ERR_STALE_VERSION` at HTTP 412."

    Capture version v, advance it via apply-anniversary, then open a claim with the
    stale v -> ERR_STALE_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_stale_policy_version_on_claim_open
    """
    ctx = setup_active_claimable_policy(policy_overrides={"inflation_rider": "COMPOUND_3PCT"})
    stale = validate_success(api.get_policy(ctx["pol_id"], CE))["version"]
    get_success_data(api.apply_anniversary(ctx["pol_id"], UW))  # advances version past stale

    res = api.create_claim(
        {"policy_id": ctx["pol_id"], "care_plan_id": ctx["cp_id"],
         "service_month": "2026-03", "expected_policy_version": stale}, CE)
    validate_error(res, "ERR_STALE_VERSION")


def test_approve_with_correct_version_increments_policy(api):
    """PRD 3.7: "If the recomputed `remaining_pool_cents` reaches exactly 0 ...
    Otherwise, if no other non-terminal claim remains, coverage returns from
    `CLAIM_OPEN` to `IN_FORCE`. The policy's `version` is incremented."

    Approving with the correct expected_policy_version succeeds (claim APPROVED)
    and the policy's version increases by exactly 1.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_increments_on_claim_approve
    """
    ctx = setup_active_claimable_policy()
    claim = open_claim(ctx["pol_id"], ctx["cp_id"], service_month="2026-03")
    add_lines(claim["id"], [("2026-03-01", 15000)])
    get_success_data(api.start_review(claim["id"], CE))

    pre = validate_success(api.get_policy(ctx["pol_id"], CE))["version"]
    approved = get_success_data(api.approve_claim(
        claim["id"], {"expected_policy_version": pre}, CE))
    assert approved["status"] == "APPROVED", approved

    post = validate_success(api.get_policy(ctx["pol_id"], CE))["version"]
    assert post == pre + 1, f"expected {pre + 1}, got {post}"
