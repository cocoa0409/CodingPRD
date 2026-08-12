"""Employer creation, plan activation, tier replacement, and OCC on tiers."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_employer,
    create_employer,
    create_employer_payload,
    create_draft_plan,
    create_active_plan,
    get_success_data,
    is_valid_uuid,
    tier_payload,
    put_tiers_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["benefits_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_create_employer_returns_201_with_fields(api):
    """PRD §4: "Operations that create a new resource — an employer, plan,
    member, dependent, provider, enrollment, visit, claim, funding account,
    deposit (which creates a ledger entry), or statement — return
    `201 Created`."
    PRD §3.1: "Employers begin `ACTIVE`"

    Design: Corner/entities/create_employer_returns_201_with_fields
    """
    resp = api.create_employer(create_employer_payload(name="ACME", funding_model="PREFUNDED"), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_employer(data)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1
    assert data["name"] == "ACME"
    assert data["funding_model"] == "PREFUNDED"


def test_put_tiers_duplicate_tier_code_rejected(api):
    """PRD §3.1: "a `tier_code` of `INDIVIDUAL`, `COUPLE`, or `FAMILY` —
    unique per plan, so a repeated `tier_code` in the payload is rejected
    with `ERR_DUPLICATE_TIER_CODE`"

    Design: Corner/entities/put_tiers_duplicate_tier_code_rejected
    """
    employer = create_employer()
    plan = create_draft_plan(employer["id"])
    dup = [tier_payload(), tier_payload(annual_allowance_cents=99999)]
    resp = api.put_plan_tiers(plan["id"], put_tiers_payload(dup, plan["version"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TIER_CODE)

    tiers, _ = validate_paginated(api.list_plan_tiers(plan["id"], ADMIN))
    assert tiers == [], f"rejected replacement must leave no tier rows, got {tiers}"


def test_plan_activate_twice_rejected(api):
    """PRD §3.1: "Activation moves it `DRAFT → ACTIVE` and is permitted only
    while the plan is `DRAFT` (any other state yields `ERR_PLAN_NOT_DRAFT`)
    and only once at least one tier exists."

    Design: Corner/validations/plan_activate_twice_rejected
    """
    employer = create_employer()
    plan = create_active_plan(employer["id"])
    resp = api.activate_plan(plan["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_DRAFT)


def test_plan_tier_amendment_stale_version_rejected(api):
    """PRD §2.7: "Replacing a plan's tier set via
    `PUT /api/benefit-plans/{id}/tiers` requires the request to carry
    `expected_plan_version`, the caller's last observed `version` of the
    plan."
    PRD §2.7: "In both cases, if the supplied expectation does not match the
    resource's current `version` — because a previously accepted amendment has
    already advanced it — the write is rejected with `ERR_STALE_VERSION`
    (HTTP 412) and no replacement occurs."

    Design: Corner/cross_cutting_complexity_layers/plan_tier_amendment_stale_version_rejected
    """
    employer = create_employer()
    plan = create_draft_plan(employer["id"])
    stale_version = plan["version"]

    first = api.put_plan_tiers(plan["id"], put_tiers_payload([tier_payload()], stale_version), ADMIN)
    updated = validate_success(first)
    assert updated["version"] == stale_version + 1

    second = api.put_plan_tiers(
        plan["id"],
        put_tiers_payload([tier_payload(annual_allowance_cents=99999)], stale_version),
        ADMIN,
    )
    validate_error(second, ApiErrorId.ERR_STALE_VERSION)


def test_auditor_cannot_create_employer(api):
    """PRD §2.1: "A caller whose role is not listed for the endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "An `Auditor` has read-only oversight across all employers."

    Design: Corner/rbac/auditor_cannot_create_employer
    """
    resp = api.create_employer(create_employer_payload(name="SNEAKY"), AUDITOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
