"""Emission factor lifecycle, approval cascade, version chain (PRD §3.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_emission_factor,
    create_approved_factor,
    create_factor_draft,
    create_factor_payload,
    create_organization,
    setup_org_facility_period,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Factor create + DRAFT initial state (PRD §3.4)
# ---------------------------------------------------------------------------
def test_create_factor_starts_in_draft(api, factor_manager_headers):
    """PRD §3.4: "A factor begins in DRAFT."
    """
    org = create_organization()
    res = api.create_factor(
        org["id"], create_factor_payload(), factor_manager_headers,
    )
    data = validate_success(res, expected_status=201)
    assert_emission_factor(data)
    assert data["status"] == "DRAFT"


def test_first_factor_version_is_one(api, factor_manager_headers):
    """PRD §3.4: "a version integer that is server-assigned starting at 1
    and increases strictly per code."
    """
    org = create_organization()
    res = api.create_factor(
        org["id"], create_factor_payload(code="UNIQUE-CODE-1"),
        factor_manager_headers,
    )
    data = validate_success(res, expected_status=201)
    assert data["version"] == 1


def test_second_draft_for_same_code_gets_version_two(api,
                                                    factor_manager_headers):
    """PRD §3.4: "version integer that is server-assigned starting at 1
    and increases strictly per code."
    Create v1 (and approve so the next is v2), then create v2 DRAFT.
    """
    org = create_organization()
    v1 = create_approved_factor(
        org["id"], code="STRICT-INC-CODE",
        effective_from="2024-12-01T00:00:00.000Z",
    )
    res = api.create_factor(
        org["id"],
        create_factor_payload(
            code="STRICT-INC-CODE",
            effective_from="2025-06-01T00:00:00.000Z",
        ),
        factor_manager_headers,
    )
    data = validate_success(res, expected_status=201)
    assert data["version"] == 2


# ---------------------------------------------------------------------------
# Approval path — DRAFT→ACTIVE (PRD §3.4)
# ---------------------------------------------------------------------------
def test_approve_first_version_sets_active(api, factor_manager_headers):
    """PRD §3.4: "A FactorManager may either approve it, moving it to
    ACTIVE."
    """
    org = create_organization()
    draft = create_factor_draft(org["id"], code="APPROVE-FIRST")
    res = api.approve_factor(org["id"], draft["id"], factor_manager_headers)
    data = validate_success(res)
    assert data["status"] == "ACTIVE"
    assert data["approved_by_user_id"], (
        "approved_by_user_id must be captured on approval (PRD §3.4)"
    )


def test_approve_supersedes_predecessor(api, factor_manager_headers):
    """PRD §3.4: "On a successful approval, the predecessor (if any)
    transitions from ACTIVE to SUPERSEDED and its effective_to is set
    equal to the new version's effective_from."
    """
    org = create_organization()
    v1 = create_approved_factor(
        org["id"], code="SUPERSEDE-CHAIN",
        effective_from="2024-12-01T00:00:00.000Z",
    )
    draft_v2 = create_factor_draft(
        org["id"], code="SUPERSEDE-CHAIN",
        effective_from="2025-06-01T00:00:00.000Z",
    )
    res = api.approve_factor(org["id"], draft_v2["id"], factor_manager_headers)
    v2 = validate_success(res)
    assert v2["status"] == "ACTIVE"

    # Re-fetch v1 via list to confirm SUPERSEDED + effective_to
    res_list = api.list_factors(
        org["id"], factor_manager_headers,
        params={"code": "SUPERSEDE-CHAIN", "limit": 100},
    )
    body = res_list.json()
    v1_after = next(f for f in body["data"] if f["id"] == v1["id"])
    assert v1_after["status"] == "SUPERSEDED"
    # PRD §3.4: predecessor's effective_to is set equal to the new
    # version's effective_from.
    assert v1_after["effective_to"] == "2025-06-01T00:00:00.000Z"


def test_approve_with_equal_effective_from_rejected(api,
                                                    factor_manager_headers):
    """PRD §3.4: "The new version's effective_from must be strictly
    greater than the predecessor ACTIVE version's effective_from for
    the same code — zero-length windows and reverse-time approvals are
    rejected with ERR_FACTOR_EFFECTIVE_FROM_ORDER."
    """
    org = create_organization()
    v1 = create_approved_factor(
        org["id"], code="EFROM-EQUAL",
        effective_from="2025-01-01T00:00:00.000Z",
    )
    draft_v2 = create_factor_draft(
        org["id"], code="EFROM-EQUAL",
        effective_from="2025-01-01T00:00:00.000Z",  # SAME as v1
    )
    res = api.approve_factor(org["id"], draft_v2["id"], factor_manager_headers)
    validate_error(res, ApiErrorId.ERR_FACTOR_EFFECTIVE_FROM_ORDER.value)


def test_approve_with_earlier_effective_from_rejected(api,
                                                     factor_manager_headers):
    """PRD §3.4: an earlier effective_from is also rejected with
    ERR_FACTOR_EFFECTIVE_FROM_ORDER."""
    org = create_organization()
    v1 = create_approved_factor(
        org["id"], code="EFROM-EARLIER",
        effective_from="2025-06-01T00:00:00.000Z",
    )
    draft_v2 = create_factor_draft(
        org["id"], code="EFROM-EARLIER",
        effective_from="2025-01-01T00:00:00.000Z",  # EARLIER than v1
    )
    res = api.approve_factor(org["id"], draft_v2["id"], factor_manager_headers)
    validate_error(res, ApiErrorId.ERR_FACTOR_EFFECTIVE_FROM_ORDER.value)


# ---------------------------------------------------------------------------
# DELETE — only DRAFT, only when no records reference it (PRD §3.4)
# ---------------------------------------------------------------------------
def test_delete_draft_factor_succeeds(api, factor_manager_headers):
    """PRD §3.4: "or delete it, moving it to RETIRED. The delete-to-retire
    path is permitted only when no EmissionRecord references the
    factor; otherwise it is rejected with ERR_INVALID_STATE."
    """
    org = create_organization()
    draft = create_factor_draft(org["id"])
    res = api.delete_factor(org["id"], draft["id"], factor_manager_headers)
    assert res.status_code == 204, (
        f"DELETE factor should return 204 (PRD §4); got {res.status_code}"
    )


def test_delete_active_factor_rejected(api, factor_manager_headers):
    """PRD §3.4: DELETE only applies to DRAFT — an ACTIVE factor cannot
    be deleted. Falls under ERR_INVALID_STATE per PRD §2.8 priority 4.
    """
    org = create_organization()
    v1 = create_approved_factor(
        org["id"], code="DEL-ACTIVE",
        effective_from="2024-12-01T00:00:00.000Z",
    )
    res = api.delete_factor(org["id"], v1["id"], factor_manager_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
