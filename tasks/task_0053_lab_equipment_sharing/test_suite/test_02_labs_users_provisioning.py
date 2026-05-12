"""Lab and User provisioning, identity-verified event ingest idempotency.

PRD §3.1 (Lab and User creation), §3.8 (event ingest, idempotency),
§2.11 (event-ingest idempotency).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_lab,
    assert_user,
    create_lab_payload,
    create_lab_with_owner,
    create_user,
    create_user_payload,
    create_verified_user,
    api_client,
    get_success_data,
    identity_verified_payload,
    validate_error,
    validate_success,
    verify_user_identity,
)


# ===========================================================================
# POST /labs (PRD §3.1)
# ===========================================================================
class TestCreateLab:
    """PRD §3.1: 'A PlatformAdmin registers a Lab by supplying a display
    name, an institution code identifying the parent school or institute,
    a department code (later used by the inter-department cost-transfer
    ledger), the contact_user_id of the User who will administer the lab,
    and a revenue_share_bps figure between 0 and 10000 inclusive that
    represents the owner-lab's share of the equipment-fee subtotal in
    basis points. At creation the lab's settlement_balance_cents and
    lifetime_settled_cents are both initialised to 0.'
    """

    def test_create_lab_initialises_balances_to_zero(self, api, admin_headers):
        """PRD §3.1: 'At creation the lab's settlement_balance_cents and
        lifetime_settled_cents are both initialised to 0.'"""
        owner = create_verified_user()
        res = api.create_lab(
            create_lab_payload(
                contact_user_id=owner["id"], revenue_share_bps=7000,
            ),
            admin_headers,
        )
        lab = validate_success(res, 201)
        assert_lab(lab)
        assert lab["settlement_balance_cents"] == 0
        assert lab["lifetime_settled_cents"] == 0

    def test_create_lab_records_revenue_share_bps(self, api, admin_headers):
        """PRD §3.1: 'a revenue_share_bps figure between 0 and 10000
        inclusive that represents the owner-lab's share of the
        equipment-fee subtotal in basis points'."""
        owner = create_verified_user()
        lab = validate_success(api.create_lab(
            create_lab_payload(
                contact_user_id=owner["id"], revenue_share_bps=6500,
            ), admin_headers,
        ), 201)
        assert lab["revenue_share_bps"] == 6500


# ===========================================================================
# POST /users (PRD §3.1)
# ===========================================================================
class TestCreateUser:
    """PRD §3.1: 'A freshly provisioned user is unverified —
    identity_verified is false until the identity-verification system
    asynchronously emits a VERIFIED event ingested by the platform-admin
    -only identity-verified event hook.'
    """

    def test_create_user_identity_verified_false(self, api, admin_headers):
        """PRD §3.1: 'identity_verified is false initially (gated by
        /_events/identity-verified)'."""
        res = api.create_user(create_user_payload(), admin_headers)
        u = validate_success(res, 201)
        assert_user(u)
        assert u["identity_verified"] is False

    def test_create_user_records_affiliation(self, api, admin_headers):
        """PRD §3.1: 'an affiliation chosen from WITHIN_SCHOOL,
        INTER_SCHOOL, or EXTERNAL'."""
        u = validate_success(api.create_user(
            create_user_payload(affiliation="INTER_SCHOOL"),
            admin_headers,
        ), 201)
        assert u["affiliation"] == "INTER_SCHOOL"


# ===========================================================================
# Identity-verified event hook (PRD §3.1, §3.8, §2.11)
# ===========================================================================
class TestIdentityVerifiedEvent:
    """PRD §3.1: 'The ingest is idempotent on external_user_id: a second
    VERIFIED event for the same user is a no-op success; a contradictory
    payload yields ERR_IDEMPOTENCY_CONFLICT.'
    """

    def test_identity_verified_event_sets_flag_true(self, api, admin_headers):
        """PRD §3.1: 'identity_verified is false until the
        identity-verification system asynchronously emits a VERIFIED
        event ingested by the platform-admin-only identity-verified
        event hook.'"""
        u = create_user()
        verified = verify_user_identity(u)
        assert verified["identity_verified"] is True

    def test_identity_verified_event_is_idempotent(self, api, admin_headers):
        """PRD §3.1: 'a second VERIFIED event for the same user is a no-op
        success'."""
        u = create_user()
        verify_user_identity(u)
        # Same external_user_id, same outcome → no-op success.
        res = api.deliver_identity_verified(
            identity_verified_payload(
                external_user_id=u["external_user_id"],
            ),
            admin_headers,
        )
        validate_success(res, 200)


# ===========================================================================
# create_lab_with_owner happy path (used widely downstream)
# ===========================================================================
class TestCreateLabWithOwner:
    """Sanity check on the create_lab_with_owner fixture sequence: the
    created Lab's contact_user_id must equal the LabOwner User.id so that
    subsequent LabOwner-role calls pass the PRD §2.1 ownership check.
    """

    def test_lab_contact_matches_owner_user_id(self, api, admin_headers):
        """PRD §2.1: 'ownership checks on any Lab compare the lab's
        contact_user_id to X-User-ID'."""
        lab, owner = create_lab_with_owner()
        assert lab["contact_user_id"] == owner["id"]
