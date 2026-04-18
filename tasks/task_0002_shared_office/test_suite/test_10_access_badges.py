"""Access badge lifecycle tests.

Covers PRD §3.5 (issue, suspend, reactivate, revoke — with preconditions).
"""

import pytest

from test_helpers import (
    TEST_USERS,
    assert_access_badge,
    create_access_badge_payload,
    issue_access_badge,
    setup_tenant_with_member,
    validate_error,
    validate_success,
)


def _setup_member():
    _tenant, member = setup_tenant_with_member()
    return member


def test_issue_badge_enters_active(api, admin_headers):
    """PRD §3.5: "A `PlatformAdmin` issues an `AccessBadge` to a `Member` by
    supplying `member_id` and a `badge_serial` that must be unique across all
    badges. The badge enters `ACTIVE`, with `last_used_at` initially absent."

    Claim: POST /access-badges returns status=ACTIVE, last_used_at is null.
    """
    member = _setup_member()
    badge = issue_access_badge(member)
    assert_access_badge(badge)
    assert badge["status"] == "ACTIVE"
    assert badge.get("last_used_at") is None


def test_duplicate_badge_serial_rejected(api, admin_headers):
    """PRD §3.5: "a `badge_serial` that must be unique across all badges."

    Claim: second badge with same serial must be rejected.
    """
    member_a = _setup_member()
    member_b = _setup_member()
    issue_access_badge(member_a, badge_serial="DUPE-SERIAL-1")
    res = api.create_access_badge(
        create_access_badge_payload(member_b["id"], badge_serial="DUPE-SERIAL-1"),
        admin_headers,
    )
    assert res.status_code >= 400 and res.status_code < 500


def test_suspend_active_badge(api, admin_headers):
    """PRD §3.5: "A `PlatformAdmin` may suspend an `ACTIVE` badge."

    Claim: suspend on ACTIVE → SUSPENDED.
    """
    member = _setup_member()
    badge = issue_access_badge(member)
    res = api.suspend_access_badge(badge["id"], admin_headers)
    suspended = validate_success(res, expected_status=200)
    assert suspended["status"] == "SUSPENDED"


def test_reactivate_suspended_badge(api, admin_headers):
    """PRD §3.5: "move a `SUSPENDED` badge back to `ACTIVE` (which is only allowed
    when the owning tenant's `access_posture` is not `FROZEN` and the member's
    `status` is `ACTIVE`)."

    Claim: reactivate on SUSPENDED under an OPEN tenant → ACTIVE.
    """
    member = _setup_member()
    badge = issue_access_badge(member)
    validate_success(api.suspend_access_badge(badge["id"], admin_headers), expected_status=200)
    res = api.reactivate_access_badge(badge["id"], admin_headers)
    reactivated = validate_success(res, expected_status=200)
    assert reactivated["status"] == "ACTIVE"


def test_revoke_active_badge_is_terminal(api, admin_headers):
    """PRD §3.5: "revoke either an `ACTIVE` or a `SUSPENDED` badge (which is
    terminal)."

    Claim: revoke on ACTIVE → REVOKED.
    """
    member = _setup_member()
    badge = issue_access_badge(member)
    res = api.revoke_access_badge(badge["id"], admin_headers)
    revoked = validate_success(res, expected_status=200)
    assert revoked["status"] == "REVOKED"


def test_reactivate_active_badge_rejected(api, admin_headers):
    """PRD §2.8: "an illegal state transition yields the per-entity state
    error." AccessBadge transitions are documented in PRD §3.5: reactivate
    applies only to SUSPENDED.

    Claim: reactivate on ACTIVE badge → a 4xx rejection (PRD does not name a
    specific error_id for AccessBadge state violations in §5, so this test
    asserts only that the request is rejected).
    """
    member = _setup_member()
    badge = issue_access_badge(member)
    res = api.reactivate_access_badge(badge["id"], admin_headers)
    assert res.status_code >= 400 and res.status_code < 500
