"""Student, Parent, and ParentChildLink workflows.

Covers PRD §3.3: student registration (ADULT/MINOR), parent
registration, child-link auto-creation, link approve and revoke,
parent capacity cap, and MINOR-action gating.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    approve_link,
    assert_parent,
    assert_parent_child_link,
    assert_student,
    create_adult_student,
    create_minor_student,
    create_parent,
    create_student_payload,
    iso_now,
    make_parent_headers,
    make_student_headers,
    setup_active_parent_child,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Student create
# ===========================================================================
class TestStudentCreate:
    def test_create_adult_student(self, api):
        """PRD §3.3: "For an ADULT student the parent_id must be null".

        Claim: POST /tutoring/students with account_type=ADULT,
        parent_id=null succeeds and returns the row.
        """
        student = create_adult_student()
        assert_student(student)
        assert student["account_type"] == "ADULT"
        assert student["parent_id"] in (None, "")
        assert student["credit_balance_cents"] == 0

    def test_create_adult_student_with_parent_id_rejected(self, api,
                                                          admin_headers):
        """PRD §3.3: "An ADULT student carrying a non-null parent_id is
        also rejected with ERR_MINOR_REQUIRES_PARENT at registration
        time."

        Claim: ADULT student with parent_id set returns
        ERR_MINOR_REQUIRES_PARENT.
        """
        parent = create_parent()
        res = api.create_student(
            create_student_payload(
                account_type="ADULT", parent_id=parent["id"],
            ),
            admin_headers,
        )
        validate_error(res, "ERR_MINOR_REQUIRES_PARENT")

    def test_create_minor_student_auto_creates_link(self, api):
        """PRD §3.3: "When a MINOR student is created with a parent_id,
        the server automatically creates a ParentChildLink carrying
        parent_id, student_id, a link_status of PENDING_PARENT_APPROVAL".

        Claim: POST /students MINOR creates a link in
        PENDING_PARENT_APPROVAL.
        """
        parent = create_parent()
        student, link = create_minor_student(parent=parent)
        assert_student(student)
        assert student["account_type"] == "MINOR"
        assert student["parent_id"] == parent["id"]
        assert_parent_child_link(link)
        assert link["link_status"] == "PENDING_PARENT_APPROVAL"
        assert link["parent_id"] == parent["id"]
        assert link["student_id"] == student["id"]
        assert link.get("approved_at") in (None, "")

    def test_create_minor_student_with_unknown_parent_id_404(self, api,
                                                             admin_headers):
        """PRD §2.5: "if any FK in the body does not resolve to an
        existing row, the request is rejected with ERR_NOT_FOUND."

        Claim: MINOR student with parent_id=unknown UUID returns
        ERR_NOT_FOUND.
        """
        res = api.create_student(
            create_student_payload(
                account_type="MINOR", parent_id=NON_EXISTENT_UUID,
            ),
            admin_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# Parent create
# ===========================================================================
class TestParentCreate:
    def test_create_parent_initial_state(self, api):
        """PRD §3.3: "The parent row carries a computed
        managed_child_count (starting at 0)".

        Claim: POST /parents returns a parent with managed_child_count=0.
        """
        parent = create_parent()
        assert_parent(parent)
        assert parent["managed_child_count"] == 0


# ===========================================================================
# ParentChildLink approval
# ===========================================================================
class TestParentChildLinkApproval:
    def test_approve_link_moves_to_active_and_bumps_count(self, api):
        """PRD §3.3: "The owning parent approves the link, which moves
        it PENDING_PARENT_APPROVAL → ACTIVE, sets approved_at to the
        current clock, and increments the parent's managed_child_count
        by 1."

        Claim: parent /approve transitions link to ACTIVE, populates
        approved_at, and parent.managed_child_count increments by 1.

        # difficulty: compensating_invariant/parent_child_count_invariant_on_link_revoke
        """
        parent = create_parent()
        student, link = create_minor_student(parent=parent)
        active_link = approve_link(parent=parent, link=link)
        assert active_link["link_status"] == "ACTIVE"
        assert active_link.get("approved_at") not in (None, "")
        # Re-fetch parent.
        refreshed_parent = validate_success(
            api.get_parent(parent["id"], make_parent_headers(parent["id"])),
        )
        assert refreshed_parent["managed_child_count"] == 1

    def test_approve_link_requires_acting_parent(self, api):
        """PRD §3.3: "The approve action requires the acting parent's
        X-User-ID to equal the link's parent_id".

        Claim: approval by a different parent returns
        ERR_NOT_AUTHORIZED_FOR_RESOURCE.
        """
        owner = create_parent()
        intruder = create_parent()
        student, link = create_minor_student(parent=owner)
        res = api.approve_link(
            owner["id"], link["id"], make_parent_headers(intruder["id"]),
        )
        validate_error(res, "ERR_NOT_AUTHORIZED_FOR_RESOURCE")

    def test_child_limit_exceeded_on_11th_approval(self, api):
        """PRD §3.3: "A parent may manage at most 10 children; an
        approval that would push managed_child_count past 10 is
        rejected with ERR_CHILD_LIMIT_EXCEEDED."

        Claim: approving the 11th child link returns
        ERR_CHILD_LIMIT_EXCEEDED.
        """
        parent = create_parent()
        for _ in range(10):
            _student, link = create_minor_student(parent=parent)
            approve_link(parent=parent, link=link)
        # 11th: create + try to approve.
        _student11, link11 = create_minor_student(parent=parent)
        res = api.approve_link(
            parent["id"], link11["id"], make_parent_headers(parent["id"]),
        )
        validate_error(res, "ERR_CHILD_LIMIT_EXCEEDED")

    def test_approve_already_active_link_invalid_state(self, api):
        """PRD §1.2 ParentChildLink state machine: from ACTIVE you
        cannot re-approve. PRD §2.6 priority 5: "Target entity in a
        state where the requested transition is defined" otherwise
        ERR_INVALID_STATE.

        Claim: approving an ACTIVE link returns ERR_INVALID_STATE.
        """
        parent, _student, active_link = setup_active_parent_child()
        res = api.approve_link(
            parent["id"], active_link["id"],
            make_parent_headers(parent["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# ParentChildLink revoke
# ===========================================================================
class TestParentChildLinkRevoke:
    def test_revoke_active_link_returns_204(self, api):
        """PRD §3.3: "Either the owning parent or a PlatformAdmin may
        revoke an ACTIVE link, which transitions it ACTIVE → REVOKED,
        decrements the parent's managed_child_count by 1".
        PRD §4 endpoint table: DELETE returns 204 No Content.

        Claim: DELETE on ACTIVE link returns 204 and decrements
        managed_child_count.
        """
        parent, _student, active_link = setup_active_parent_child()
        res = api.revoke_link(
            parent["id"], active_link["id"],
            make_parent_headers(parent["id"]),
        )
        assert res.status_code == 204, (
            f"DELETE link must return 204, got {res.status_code}"
        )
        refreshed_parent = validate_success(
            api.get_parent(parent["id"], make_parent_headers(parent["id"])),
        )
        assert refreshed_parent["managed_child_count"] == 0


# ===========================================================================
# List parent links
# ===========================================================================
class TestListLinks:
    def test_list_links_filter_by_status(self, api):
        """PRD §3.9: "a parent may list their own ParentChildLink rows
        filtered by link_status."

        Claim: listing with link_status=ACTIVE returns only ACTIVE links.
        """
        parent = create_parent()
        # Create two PENDING and approve one.
        _s1, l1 = create_minor_student(parent=parent)
        _s2, l2 = create_minor_student(parent=parent)
        approve_link(parent=parent, link=l1)
        resp = api.list_parent_links(
            parent["id"], make_parent_headers(parent["id"]),
            params={"link_status": "ACTIVE"},
        )
        data, _meta = validate_paginated(resp)
        statuses = {ln["link_status"] for ln in data}
        assert statuses == {"ACTIVE"}, (
            f"expected only ACTIVE links, got {statuses}"
        )
