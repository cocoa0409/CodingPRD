"""Emergency contacts and parental authorizations.

These tests cover PRD §3.2 (emergency contacts, parental
authorizations) and PRD §2.8 (authorization state projection onto
Child.medical_authorization_status / pickup_authorization_status).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    add_emergency_contact,
    assert_authorization,
    assert_emergency_contact,
    create_authorization,
    create_authorization_payload,
    create_child,
    create_emergency_contact_payload,
    create_family,
    iso_offset,
    make_guardian_headers,
    re_get_child,
    setup_family_with_primary_guardian,
    validate_error,
    validate_success,
)


# ===========================================================================
# EmergencyContact creation + count derivation
# ===========================================================================
class TestEmergencyContacts:
    def test_create_emergency_contact_bumps_child_count(self, api):
        """PRD §3.2: "Adding a contact increments
        Child.emergency_contact_count; archiving a contact via
        deletion decrements it."

        Claim: after one POST /camp/children/{id}/emergency-contacts,
        the child's emergency_contact_count is 1.
        """
        family, guardian = setup_family_with_primary_guardian()
        child = create_child(family=family)
        assert child["emergency_contact_count"] == 0
        contact = add_emergency_contact(child=child, priority=1)
        assert_emergency_contact(contact)
        refreshed = re_get_child(child["id"])
        assert refreshed["emergency_contact_count"] == 1

    def test_duplicate_priority_rejected(self, api):
        """PRD §3.2: "Each (child_id, priority) pair must be unique
        among the child's non-archived contacts; an attempt to add a
        contact at a priority that is already in use is rejected with
        ERR_EMERGENCY_CONTACT_PRIORITY_TAKEN."

        Claim: a second POST at the same priority returns
        ERR_EMERGENCY_CONTACT_PRIORITY_TAKEN.
        """
        family, _ = setup_family_with_primary_guardian()
        child = create_child(family=family)
        add_emergency_contact(child=child, priority=2)
        res = api.create_emergency_contact(
            child["id"],
            create_emergency_contact_payload(priority=2),
            TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_EMERGENCY_CONTACT_PRIORITY_TAKEN")

    def test_archived_contact_decrements_count(self, api):
        """PRD §3.2: "archiving a contact via deletion decrements it."

        Claim: after DELETE /camp/emergency-contacts/{id} on a fresh
        contact, the child's emergency_contact_count drops by 1.
        """
        family, _ = setup_family_with_primary_guardian()
        child = create_child(family=family)
        contact = add_emergency_contact(child=child, priority=1)
        assert re_get_child(child["id"])["emergency_contact_count"] == 1
        api.delete_emergency_contact(
            contact["id"], TEST_USERS["admin_headers"],
        )
        assert re_get_child(child["id"])["emergency_contact_count"] == 0

    def test_archived_priority_is_reusable(self, api):
        """PRD §3.2: "Each (child_id, priority) pair must be unique
        among the child's non-archived contacts."

        Claim: after archiving the priority-1 contact, a new contact
        at priority 1 succeeds (archived rows do not count).
        """
        family, _ = setup_family_with_primary_guardian()
        child = create_child(family=family)
        first = add_emergency_contact(child=child, priority=1)
        api.delete_emergency_contact(
            first["id"], TEST_USERS["admin_headers"],
        )
        # Now priority 1 should be available again.
        res = api.create_emergency_contact(
            child["id"],
            create_emergency_contact_payload(priority=1),
            TEST_USERS["admin_headers"],
        )
        validate_success(res, 201)


# ===========================================================================
# Authorization creation + projection
# ===========================================================================
class TestAuthorizationCreation:
    def test_create_authorization_projects_active_status(self, api):
        """PRD §3.2: "New authorizations start in ACTIVE state, and
        the side effect of creation is a re-projection of the child's
        medical_authorization_status or pickup_authorization_status
        per the projection rules in §2.8."
        PRD §2.8: "the status is ACTIVE if there exists at least one
        Authorization belonging to that child with that kind, with
        status equal to ACTIVE, whose effective_at is at or before
        the current clock and whose expires_at is strictly after the
        current clock."

        Claim: after creating an ACTIVE MEDICAL Authorization on a
        child, the child's medical_authorization_status is ACTIVE.
        """
        family, guardian = setup_family_with_primary_guardian()
        child = create_child(family=family)
        auth = create_authorization(
            child=child, guardian=guardian, kind="MEDICAL",
        )
        assert_authorization(auth)
        assert auth["status"] == "ACTIVE"
        refreshed = re_get_child(child["id"])
        assert refreshed["medical_authorization_status"] == "ACTIVE"

    def test_authorization_with_inverted_time_range_rejected(self, api):
        """PRD §3.2: "an expires_at instant strictly greater than
        effective_at. A request where expires_at is at or before
        effective_at is rejected with ERR_INVALID_TIME_RANGE."

        Claim: posting an Authorization with expires_at == effective_at
        returns ERR_INVALID_TIME_RANGE.
        """
        family, guardian = setup_family_with_primary_guardian()
        child = create_child(family=family)
        same = iso_offset(days=1)
        payload = create_authorization_payload(
            guardian_id=guardian["id"], kind="MEDICAL",
            effective_at=same, expires_at=same,
        )
        res = api.create_authorization(
            child["id"], payload, TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_INVALID_TIME_RANGE")

    def test_authorization_cross_family_guardian_rejected(self, api):
        """PRD §3.2: "guardian_id pointing at the guardian granting
        the permission (who must belong to the same family as the
        child, otherwise the request is rejected with
        ERR_FAMILY_MISMATCH)".

        Claim: an Authorization whose guardian_id is from a different
        family than the child is rejected with ERR_FAMILY_MISMATCH.
        """
        family_a, guardian_a = setup_family_with_primary_guardian()
        family_b, guardian_b = setup_family_with_primary_guardian()
        child_a = create_child(family=family_a)
        # guardian_b is from family_b but child_a is from family_a.
        payload = create_authorization_payload(
            guardian_id=guardian_b["id"], kind="MEDICAL",
        )
        res = api.create_authorization(
            child_a["id"], payload, TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_FAMILY_MISMATCH")


# ===========================================================================
# Authorization revoke + projection cascade
# ===========================================================================
class TestAuthorizationRevoke:
    def test_revoke_active_authorization_moves_to_revoked(self, api):
        """PRD §3.2: "Either a Guardian of the family or a
        ProgramAdmin can also revoke an authorization that is
        currently ACTIVE, moving it to REVOKED and recording the
        current clock as revoked_at."

        Claim: revoking an ACTIVE Authorization returns it in REVOKED
        state with revoked_at set.
        """
        family, guardian = setup_family_with_primary_guardian()
        child = create_child(family=family)
        auth = create_authorization(
            child=child, guardian=guardian, kind="MEDICAL",
        )
        res = api.revoke_authorization(
            auth["id"], TEST_USERS["admin_headers"],
        )
        revoked = validate_success(res, 200)
        assert revoked["status"] == "REVOKED"
        assert revoked.get("revoked_at") is not None

    def test_revoke_non_active_authorization_rejected(self, api):
        """PRD §3.2: "Revoking an authorization that is not ACTIVE
        (already EXPIRED or already REVOKED) is rejected with
        ERR_INVALID_STATE."

        Claim: a second revoke on the same Authorization returns
        ERR_INVALID_STATE.
        """
        family, guardian = setup_family_with_primary_guardian()
        child = create_child(family=family)
        auth = create_authorization(
            child=child, guardian=guardian, kind="MEDICAL",
        )
        api.revoke_authorization(auth["id"], TEST_USERS["admin_headers"])
        res = api.revoke_authorization(
            auth["id"], TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_revoke_last_medical_auth_flips_child_status_to_expired(
        self, api,
    ):
        """PRD §3.2: "this transition recomputes the parent child's
        derived status fields and, if no remaining ACTIVE row of
        that kind exists for the child, the corresponding child
        status flips to EXPIRED."
        PRD §2.8: "the status is EXPIRED if no such currently-active
        row exists but at least one Authorization of that kind has
        ever existed for the child."

        Claim: after revoking the only ACTIVE MEDICAL Authorization,
        the child's medical_authorization_status flips to EXPIRED.
        """
        family, guardian = setup_family_with_primary_guardian()
        child = create_child(family=family)
        auth = create_authorization(
            child=child, guardian=guardian, kind="MEDICAL",
        )
        assert re_get_child(child["id"])[
            "medical_authorization_status"
        ] == "ACTIVE"
        api.revoke_authorization(auth["id"], TEST_USERS["admin_headers"])
        refreshed = re_get_child(child["id"])
        assert refreshed["medical_authorization_status"] == "EXPIRED"


# ===========================================================================
# Authorization projection independence — medical vs pickup
# ===========================================================================
class TestAuthorizationProjectionIndependence:
    def test_medical_and_pickup_status_are_independent(self, api):
        """PRD §2.8: "The two derived fields medical_authorization_status
        and pickup_authorization_status are independent — a child may
        be ACTIVE for one kind and EXPIRED for the other."

        Claim: a child with an ACTIVE MEDICAL but no PICKUP
        Authorization has medical_authorization_status=="ACTIVE" and
        pickup_authorization_status=="NONE".
        """
        family, guardian = setup_family_with_primary_guardian()
        child = create_child(family=family)
        create_authorization(
            child=child, guardian=guardian, kind="MEDICAL",
        )
        refreshed = re_get_child(child["id"])
        assert refreshed["medical_authorization_status"] == "ACTIVE"
        assert refreshed["pickup_authorization_status"] == "NONE"
