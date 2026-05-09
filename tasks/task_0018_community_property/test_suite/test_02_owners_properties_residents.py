"""Owners, Properties, Residents lifecycle tests (PRD §3.1).

Covers:
- Owner creation and uniqueness on id_card_no
- Property creation and uniqueness on (building_no, unit_no) → ERR_DUPLICATE_PROPERTY
- Property area_sqm > 0 constraint
- Resident creation by relation_kind FAMILY vs TENANT
- Move-in / move-out lifecycle and Property.occupancy_status recompute
- Tenant move-in requires lease_end_at > now()
- Tenant move-in blocked if Owner has any FeeBill in OVERDUE → ERR_OWNER_DELINQUENT
"""

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    advance_clock_to,
    api_client,
    assert_owner,
    assert_property,
    assert_resident,
    create_owner,
    create_owner_payload,
    create_owner_with_property,
    create_property_for_owner,
    create_property_payload,
    create_resident_payload,
    create_tenant_resident,
    create_family_resident,
    fetch_property,
    iso_utc,
    issue_single_bill_for_property,
    move_in_resident,
    move_out_resident,
    setup_overdue_bill,
    setup_property_with_active_rule,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestOwnerCreation:
    """PRD §3.1: registering an owner."""

    def test_create_owner_returns_eligible_voting_status(self, api, property_manager_headers):
        """PRD §3.1: "the new owner starts with voting_status set to ELIGIBLE."

        Claim: POST /owners returns voting_status == ELIGIBLE on a fresh row.
        """
        res = api.create_owner(create_owner_payload(), property_manager_headers)
        data = validate_success(res, expected_status=201)
        assert_owner(data)
        assert data["voting_status"] == "ELIGIBLE", (
            f"Expected ELIGIBLE for fresh owner, got {data['voting_status']!r}"
        )

    def test_owner_id_card_no_must_be_unique(self, api, property_manager_headers):
        """PRD §3.1: "The id_card_no must be unique across the community —
        duplicates are rejected."

        Claim: a second POST /owners with the same id_card_no is rejected. PRD does
        not bind a specific error_id to "duplicate id_card_no" so we accept any 4xx
        envelope error and assert the request fails — see Silence-pattern note in
        the suite report.
        """
        payload = create_owner_payload(id_card_no="ID-DUPLICATE-FIXED-XYZ")
        first = api.create_owner(payload, property_manager_headers)
        validate_success(first, expected_status=201)
        second = api.create_owner(payload, property_manager_headers)
        # PRD does not name a specific error_id for owner id_card_no duplicates.
        # It only states "duplicates are rejected", so we just verify the call fails.
        assert 400 <= second.status_code < 500, (
            f"Duplicate id_card_no must be rejected per PRD §3.1; got HTTP {second.status_code}"
        )


class TestPropertyCreation:
    """PRD §3.1: registering a property."""

    def test_create_property_starts_vacant(self, api, property_manager_headers):
        """PRD §3.1: "New properties start with occupancy_status of VACANT."

        Claim: POST /properties returns occupancy_status == VACANT.
        """
        owner = create_owner()
        res = api.create_property(
            create_property_payload(owner["id"]), property_manager_headers
        )
        data = validate_success(res, expected_status=201)
        assert_property(data)
        assert data["occupancy_status"] == "VACANT", (
            f"Fresh property must be VACANT, got {data['occupancy_status']!r}"
        )

    def test_create_property_default_parking_quota_is_one(self, api, property_manager_headers):
        """PRD §3.1: "an optional parking_quota (which defaults to 1 if omitted)."

        Claim: omitting parking_quota yields parking_quota == 1.
        """
        owner = create_owner()
        payload = create_property_payload(owner["id"])
        payload.pop("parking_quota", None)
        res = api.create_property(payload, property_manager_headers)
        data = validate_success(res, expected_status=201)
        assert data["parking_quota"] == 1

    def test_duplicate_building_unit_rejected(self, api, property_manager_headers):
        """PRD §3.1: "re-registering an already-registered unit is rejected with
        ERR_DUPLICATE_PROPERTY."

        Claim: a second POST /properties with the same (building_no, unit_no) returns
        ERR_DUPLICATE_PROPERTY.
        """
        owner = create_owner()
        payload = create_property_payload(
            owner["id"], building_no="B-DUP-1", unit_no="U-DUP-1"
        )
        validate_success(api.create_property(payload, property_manager_headers), 201)
        # Re-register — uniqueness is on (building_no, unit_no) per PRD §3.1.
        owner2 = create_owner()
        payload2 = create_property_payload(
            owner2["id"], building_no="B-DUP-1", unit_no="U-DUP-1"
        )
        res = api.create_property(payload2, property_manager_headers)
        validate_error(res, "ERR_DUPLICATE_PROPERTY")

    def test_property_area_sqm_must_be_positive(self, api, property_manager_headers):
        """PRD §3.1: "The area_sqm must be strictly greater than zero."

        Claim: area_sqm <= 0 is rejected. PRD does not name a specific error_id for
        this validation; we therefore assert the request returns a 4xx envelope error.
        """
        owner = create_owner()
        payload = create_property_payload(owner["id"], area_sqm=0)
        res = api.create_property(payload, property_manager_headers)
        assert 400 <= res.status_code < 500, (
            f"area_sqm=0 must be rejected per PRD §3.1; got HTTP {res.status_code}"
        )

    def test_create_property_unknown_owner_id_returns_reference_not_found(
        self, api, property_manager_headers
    ):
        """PRD §2.5: "Body fields that name foreign-key references — property_id,
        owner_id, ... — are checked next; any reference to a non-existent entity
        yields ERR_REFERENCE_NOT_FOUND (HTTP 404)."

        Claim: POST /properties with a non-existent owner_id returns ERR_REFERENCE_NOT_FOUND.
        """
        payload = create_property_payload(owner_id=NON_EXISTENT_UUID)
        res = api.create_property(payload, property_manager_headers)
        validate_error(res, "ERR_REFERENCE_NOT_FOUND")


class TestResidentCreation:
    """PRD §3.1: registering residents."""

    def test_create_family_resident_starts_pending_move_in(
        self, api, property_manager_headers
    ):
        """PRD §3.1: "New residents start in lifecycle_status PENDING_MOVE_IN."

        Claim: POST /residents returns lifecycle_status == PENDING_MOVE_IN.
        """
        _owner, prop = create_owner_with_property()
        res = api.create_resident(
            create_resident_payload(prop["id"], "FAMILY"), property_manager_headers
        )
        data = validate_success(res, expected_status=201)
        assert_resident(data)
        assert data["lifecycle_status"] == "PENDING_MOVE_IN"
        assert data["relation_kind"] == "FAMILY"


class TestResidentMoveLifecycle:
    """PRD §3.1: move-in / move-out and Property.occupancy_status cascade."""

    def test_family_move_in_makes_property_owner_occupied(self, api):
        """PRD §3.1: "if any resident currently in RESIDING is a tenant the property
        becomes TENANT_OCCUPIED; otherwise if any owner or family resident is in
        RESIDING the property becomes OWNER_OCCUPIED; otherwise VACANT."

        Claim: moving in a single FAMILY resident → Property.occupancy_status == OWNER_OCCUPIED.
        """
        _owner, prop = create_owner_with_property()
        family = create_family_resident(prop)
        moved = move_in_resident(family)
        assert moved["lifecycle_status"] == "RESIDING"
        refreshed = fetch_property(prop["id"])
        assert refreshed["occupancy_status"] == "OWNER_OCCUPIED"

    def test_tenant_move_in_makes_property_tenant_occupied(self, api):
        """PRD §3.1: "if any resident currently in RESIDING is a tenant the property
        becomes TENANT_OCCUPIED."

        Claim: moving in a TENANT resident → Property.occupancy_status == TENANT_OCCUPIED.
        """
        _owner, prop = create_owner_with_property()
        tenant = create_tenant_resident(prop)
        move_in_resident(tenant)
        refreshed = fetch_property(prop["id"])
        assert refreshed["occupancy_status"] == "TENANT_OCCUPIED"

    def test_move_out_returns_property_to_vacant(self, api):
        """PRD §3.1: "A move-out transition advances lifecycle_status from RESIDING
        to MOVED_OUT, sets move_out_at to the current time, recomputes
        occupancy_status again."

        Claim: moving out the only RESIDING resident → Property.occupancy_status == VACANT.
        """
        _owner, prop = create_owner_with_property()
        family = create_family_resident(prop)
        move_in_resident(family)
        moved_out = move_out_resident(family)
        assert moved_out["lifecycle_status"] == "MOVED_OUT"
        assert moved_out.get("move_out_at"), "move_out_at must be set on MOVED_OUT"
        refreshed = fetch_property(prop["id"])
        assert refreshed["occupancy_status"] == "VACANT"

    def test_tenant_move_in_requires_future_lease_end(self, api, property_manager_headers):
        """PRD §3.1: "For tenants the move-in additionally requires that lease_end_at
        be strictly later than now()."

        Claim: tenant whose lease_end_at is in the past cannot move in. PRD does not
        name a specific error_id for this validation; we accept any 4xx envelope error.
        """
        _owner, prop = create_owner_with_property()
        past_iso = iso_utc(datetime.now(timezone.utc) - timedelta(days=10))
        tenant = create_tenant_resident(prop, lease_end_at=past_iso)
        res = api.move_in_resident(tenant["id"], property_manager_headers)
        assert 400 <= res.status_code < 500, (
            f"Tenant move-in with past lease_end_at must be rejected; got HTTP {res.status_code}"
        )

    def test_tenant_move_in_blocked_when_owner_delinquent(self, api, property_manager_headers):
        """PRD §3.1: "Attempting to move in a tenant while the relevant owner has
        any FeeBill in OVERDUE is rejected with ERR_OWNER_DELINQUENT."

        Claim: with the owner sitting on an OVERDUE bill, POST /residents/{id}/move-in
        on a TENANT returns ERR_OWNER_DELINQUENT.
        """
        owner, prop, _rule, overdue = setup_overdue_bill(days_past_due=20)
        assert overdue["status"] == "OVERDUE"
        # Now attempt to move in a tenant — the owner has an OVERDUE bill on prop.
        tenant = create_tenant_resident(prop)
        res = api.move_in_resident(tenant["id"], property_manager_headers)
        validate_error(res, "ERR_OWNER_DELINQUENT")
