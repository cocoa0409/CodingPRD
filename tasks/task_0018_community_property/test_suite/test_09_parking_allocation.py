"""Parking applications, approvals, and the FIXED quota check (PRD §3.9).

Covers:
- Owner files application → starts PENDING.
- Owner-delinquency block on application → ERR_OWNER_DELINQUENT.
- Approval gates: parking space AVAILABLE → ERR_PARKING_SPACE_TAKEN, kind match
  → ERR_PARKING_KIND_MISMATCH, quota → ERR_PARKING_QUOTA_EXCEEDED.
- Difficulty-design instance: parking_space_exclusive_allocation (kind: resource
  temporal-overlap; capacity=1, exclusive lock semantics).
- Difficulty-design instance: parking_application_approve_requires_property_quota_room.
- Termination releases the parking space.
"""

import pytest

from test_helpers import (
    api_client,
    approve_parking_application,
    approve_parking_application_payload,
    assert_parking_application,
    assert_parking_space,
    create_owner_with_property,
    create_parking_application_payload,
    create_parking_space,
    fetch_owner,
    make_owner_headers,
    setup_overdue_bill,
    setup_parking_application_pending,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestParkingApplicationCreation:
    def test_owner_files_application_starts_pending(self, api):
        """PRD §3.9: "the application opens in status PENDING."

        Claim: POST /parking-applications returns status==PENDING.
        """
        owner, prop = create_owner_with_property()
        headers = make_owner_headers(owner["id"])
        payload = create_parking_application_payload(prop["id"], requested_kind="FIXED")
        res = api.create_parking_application(payload, headers)
        data = validate_success(res, 201)
        assert_parking_application(data)
        assert data["status"] == "PENDING"

    def test_delinquent_owner_blocked_from_application(self, api):
        """PRD §3.9: "Owners with any fee bill in OVERDUE are blocked from filing
        parking applications with ERR_OWNER_DELINQUENT."

        Claim: with the owner sitting on an OVERDUE bill, POST /parking-applications →
        ERR_OWNER_DELINQUENT.
        """
        owner, prop, _rule, overdue = setup_overdue_bill(days_past_due=10)
        assert overdue["status"] == "OVERDUE"
        headers = make_owner_headers(owner["id"])
        payload = create_parking_application_payload(prop["id"], requested_kind="TEMPORARY")
        res = api.create_parking_application(payload, headers)
        validate_error(res, "ERR_OWNER_DELINQUENT")


class TestApprovalGates:
    def test_kind_mismatch_returns_kind_mismatch(self, api, property_manager_headers):
        """PRD §3.9: "the parking space's kind must match the application's
        requested_kind (otherwise ERR_PARKING_KIND_MISMATCH)."

        Claim: approving with a TEMPORARY space against a FIXED application →
        ERR_PARKING_KIND_MISMATCH.
        """
        _owner, _prop, app = setup_parking_application_pending(requested_kind="FIXED")
        # Create a TEMPORARY space — wrong kind.
        space = create_parking_space(kind="TEMPORARY", monthly_fee=0.0)
        res = api.approve_parking_application(
            app["id"], approve_parking_application_payload(space["id"]), property_manager_headers
        )
        validate_error(res, "ERR_PARKING_KIND_MISMATCH")

    def test_quota_exceeded_for_second_fixed_application(self, api, property_manager_headers):
        """PRD §3.9: "when requested_kind is FIXED, the count of currently-APPROVED
        FIXED applications already bound to the same property must be strictly less
        than the property's parking_quota (otherwise ERR_PARKING_QUOTA_EXCEEDED)."

        Setup (per recipe): Property P with parking_quota=1; one existing APPROVED
        FIXED ParkingApplication on P; create AVAILABLE FIXED ParkingSpace S2;
        attempt approval of a second FIXED PENDING application against P with S2.

        Claim: server returns 422 ERR_PARKING_QUOTA_EXCEEDED — the ParkingApplication
        transition was blocked by the Property's quota state.

        # difficulty: cross_entity_state_dependency/parking_application_approve_requires_property_quota_room
        """
        owner, prop = create_owner_with_property(parking_quota=1)
        space1 = create_parking_space(kind="FIXED", monthly_fee=100.0)
        owner_headers = make_owner_headers(owner["id"])
        # First FIXED application — approved, fills the quota.
        app1 = validate_success(
            api.create_parking_application(
                create_parking_application_payload(prop["id"], requested_kind="FIXED"),
                owner_headers,
            ),
            201,
        )
        approve_parking_application(app1, space1)
        # Second FIXED application — must hit quota.
        space2 = create_parking_space(kind="FIXED", monthly_fee=100.0)
        app2 = validate_success(
            api.create_parking_application(
                create_parking_application_payload(prop["id"], requested_kind="FIXED"),
                owner_headers,
            ),
            201,
        )
        res = api.approve_parking_application(
            app2["id"], approve_parking_application_payload(space2["id"]), property_manager_headers
        )
        validate_error(res, "ERR_PARKING_QUOTA_EXCEEDED")


class TestParkingSpaceExclusiveAllocation:
    """Difficulty-design instance: parking_space_exclusive_allocation."""

    def test_second_approval_against_same_space_returns_taken(self, api, property_manager_headers):
        """PRD §3.9: "the chosen parking space must exist and have status of
        AVAILABLE at approval time (otherwise ERR_PARKING_SPACE_TAKEN)."
        PRD §2.9: "When two parking applications race to claim the same ParkingSpace,
        exactly one approval succeeds and the loser receives ERR_PARKING_SPACE_TAKEN
        (HTTP 409); serialization is first-writer-wins on the parking space's status
        flip from AVAILABLE to ALLOCATED."

        Setup: ParkingSpace S kind=FIXED, status=AVAILABLE; two PENDING applications
        PA1 and PA2 (each on a separate property to avoid quota cross-talk) both
        targeting S. Approve PA1 first — succeeds; approve PA2 against the (now
        ALLOCATED) S — must fail with ERR_PARKING_SPACE_TAKEN.

        Claim: second approval against the same already-ALLOCATED space →
        ERR_PARKING_SPACE_TAKEN.

        # difficulty: resource_temporal_overlap/parking_space_exclusive_allocation
        """
        space = create_parking_space(kind="FIXED", monthly_fee=100.0)
        # Two distinct property+owner pairs, both filing FIXED applications.
        owner1, prop1 = create_owner_with_property(parking_quota=1)
        owner2, prop2 = create_owner_with_property(parking_quota=1)
        h1 = make_owner_headers(owner1["id"])
        h2 = make_owner_headers(owner2["id"])
        app1 = validate_success(
            api.create_parking_application(
                create_parking_application_payload(prop1["id"], requested_kind="FIXED"), h1
            ),
            201,
        )
        app2 = validate_success(
            api.create_parking_application(
                create_parking_application_payload(prop2["id"], requested_kind="FIXED"), h2
            ),
            201,
        )
        # First approval — must succeed and flip space to ALLOCATED.
        approve_parking_application(app1, space)
        # Second approval against the same space — must fail.
        res = api.approve_parking_application(
            app2["id"], approve_parking_application_payload(space["id"]), property_manager_headers
        )
        validate_error(res, "ERR_PARKING_SPACE_TAKEN")


class TestApprovalSideEffects:
    def test_approval_flips_parking_space_to_allocated(self, api, property_manager_headers):
        """PRD §3.9: "On successful approval the application's allocated_space_id
        is set, started_at is set to the current time, and the parking space's
        status flips from AVAILABLE to ALLOCATED."

        Claim: after approval, application.status==APPROVED with non-null
        allocated_space_id and started_at; ParkingSpace.status==ALLOCATED is
        observable via the next approval failing (we just verify the application
        side here; the cross-space verification is in the exclusive-allocation test).
        """
        _owner, _prop, app = setup_parking_application_pending(requested_kind="FIXED")
        space = create_parking_space(kind="FIXED", monthly_fee=200.0)
        approved = approve_parking_application(app, space)
        assert approved["status"] == "APPROVED"
        assert approved.get("allocated_space_id") == space["id"]
        assert approved.get("started_at"), "started_at must be set on APPROVED"


class TestTerminationReleasesSpace:
    def test_terminate_returns_space_to_available(self, api, property_manager_headers):
        """PRD §3.9: "A PropertyManager may terminate an APPROVED allocation,
        advancing APPROVED → TERMINATED; on termination the parking space's status
        flips back to AVAILABLE."

        Claim: terminate on APPROVED → application.status==TERMINATED; the parking
        space is then available for a new approval (we approve a second application
        against it as the cross-check).
        """
        _owner, _prop, app = setup_parking_application_pending(requested_kind="FIXED")
        space = create_parking_space(kind="FIXED", monthly_fee=150.0)
        approved = approve_parking_application(app, space)
        assert approved["status"] == "APPROVED"
        terminated_res = api.terminate_parking_application(approved["id"], property_manager_headers)
        terminated = validate_success(terminated_res, 200)
        assert terminated["status"] == "TERMINATED"
        # Space should be allocatable again — second app on a different property.
        owner2, prop2 = create_owner_with_property(parking_quota=1)
        h2 = make_owner_headers(owner2["id"])
        app2 = validate_success(
            api.create_parking_application(
                create_parking_application_payload(prop2["id"], requested_kind="FIXED"),
                h2,
            ),
            201,
        )
        approved2 = approve_parking_application(app2, space)
        assert approved2["status"] == "APPROVED"
