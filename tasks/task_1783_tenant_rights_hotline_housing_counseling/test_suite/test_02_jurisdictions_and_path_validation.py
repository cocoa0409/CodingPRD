"""Jurisdiction hierarchy and path/existence validation (PRD §2.8, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_jurisdiction,
    create_jurisdiction,
    validate_error,
    validate_success,
)


def test_jurisdiction_level_chain_valid(api):
    """PRD §3.1: "The hierarchy is anchored through `parent_jurisdiction_id`: a
    `STATE` has a null parent, a `COUNTY`'s parent must be a `STATE`, and a `CITY`'s
    parent must be a `COUNTY`; any mismatch is rejected with
    `ERR_JURISDICTION_LEVEL_MISMATCH` (HTTP 422). The level of a child is always
    exactly one deeper than its parent, and because the hierarchy is create-only —
    no re-parenting endpoint exists — cycles are structurally impossible."

    Design: Corner/entities/jurisdiction_level_chain_valid
    """
    state = validate_success(api.create_jurisdiction(
        {"code": "CA", "name": "California", "level": "STATE",
         "eviction_notice_days": 3, "habitability_repair_days": 14,
         "deposit_cap_months": 1.0, "deposit_interest_required": False,
         "deposit_interest_rate_pct": 0.0},
        TEST_USERS["agency_admin_headers"],
    ), expected_status=201)
    assert_jurisdiction(state)
    assert state["level"] == "STATE"
    assert state.get("parent_jurisdiction_id") is None

    county = validate_success(api.create_jurisdiction(
        {"parent_jurisdiction_id": state["id"], "code": "CA-LA",
         "name": "Los Angeles County", "level": "COUNTY",
         "eviction_notice_days": 3, "habitability_repair_days": 14,
         "deposit_cap_months": 1.0, "deposit_interest_required": False,
         "deposit_interest_rate_pct": 0.0},
        TEST_USERS["agency_admin_headers"],
    ), expected_status=201)
    assert county["level"] == "COUNTY"
    assert county["parent_jurisdiction_id"] == state["id"]

    city = validate_success(api.create_jurisdiction(
        {"parent_jurisdiction_id": county["id"], "code": "CA-LA-001",
         "name": "Los Angeles", "level": "CITY",
         "eviction_notice_days": 3, "habitability_repair_days": 14,
         "deposit_cap_months": 1.0, "deposit_interest_required": False,
         "deposit_interest_rate_pct": 0.0},
        TEST_USERS["agency_admin_headers"],
    ), expected_status=201)
    assert city["level"] == "CITY"
    assert city["parent_jurisdiction_id"] == county["id"]

    # Readback confirms the anchored hierarchy persisted as created.
    fetched = validate_success(
        api.get_jurisdiction(city["id"], TEST_USERS["agency_admin_headers"])
    )
    assert fetched["parent_jurisdiction_id"] == county["id"]
    assert fetched["level"] == "CITY"


def test_jurisdiction_wrong_level_parent_rejected(api):
    """PRD §3.1: "The hierarchy is anchored through `parent_jurisdiction_id`: a
    `STATE` has a null parent, a `COUNTY`'s parent must be a `STATE`, and a `CITY`'s
    parent must be a `COUNTY`; any mismatch is rejected with
    `ERR_JURISDICTION_LEVEL_MISMATCH` (HTTP 422)."

    Design: Corner/entities/jurisdiction_wrong_level_parent_rejected
    """
    state = create_jurisdiction()
    resp = api.create_jurisdiction(
        {"parent_jurisdiction_id": state["id"], "code": "CA-001",
         "name": "Direct City", "level": "CITY",
         "eviction_notice_days": 3, "habitability_repair_days": 14,
         "deposit_cap_months": 1.0, "deposit_interest_required": False,
         "deposit_interest_rate_pct": 0.0},
        TEST_USERS["agency_admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_JURISDICTION_LEVEL_MISMATCH)


def test_entity_not_found_returns_404(api):
    """PRD §2.8: "The system confirms each path identifier in sequence —
    jurisdiction, caller, session, case, note parent, follow-up, organization,
    referral, script, resource, counselor, interpreter, consent, policy, or purge
    job — and rejects the request immediately with `ERR_NOT_FOUND` (HTTP 404) at the
    first identifier that does not correspond to an existing resource, before
    evaluating any later identifier or any business rule."

    Design: Corner/entities/entity_not_found_returns_404
    """
    resp = api.get_case(NON_EXISTENT_UUID, TEST_USERS["supervisor_headers"])
    error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert isinstance(error_data.get("message"), str) and error_data["message"].strip()


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request whose role header is missing or names an undeclared role,
    or whose `X-User-ID` is missing where required, is rejected with
    `ERR_UNAUTHENTICATED`."
    PRD §2.10: "When several checks could reject the same request, the server
    evaluates them in a fixed priority order and the first failing check determines
    the error returned; ordering matters because an early rejection masks later
    ones."

    Design: Corner/validations/missing_auth_headers_unauthenticated
    """
    # No X-User-Role / X-User-ID at all: authentication outranks existence, so
    # even a non-existent case id must surface 401, not 404.
    resp = api.get_case(NON_EXISTENT_UUID, headers=None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_patch_missing_case_not_found_priority(api):
    """PRD §2.8: "The system confirms each path identifier in sequence —
    jurisdiction, caller, session, case, note parent, follow-up, organization,
    referral, script, resource, counselor, interpreter, consent, policy, or purge
    job — and rejects the request immediately with `ERR_NOT_FOUND` (HTTP 404) at the
    first identifier that does not correspond to an existing resource, before
    evaluating any later identifier or any business rule."

    Design: Corner/validations/patch_missing_case_not_found_priority
    """
    resp = api.update_case(
        NON_EXISTENT_UUID, {"eviction_notice_date": "2026-08-06"},
        TEST_USERS["supervisor_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
