"""Allocation uniqueness, quota boundary, initial status, and OCC versioning."""
from test_helpers import (
    ApiErrorId,
    TERM_END,
    TERM_START,
    assert_lot_allocation,
    assert_permit,
    assert_permit_fee_consistency,
    create_allocation,
    create_lot,
    create_patron,
    get_allocation,
    purchase_permit,
    validate_error,
    validate_success,
)


def _allocation_payload(lot_id, **overrides):
    payload = {
        "lot_id": lot_id,
        "permit_code": "GEN",
        "eligible_roles": ["STUDENT"],
        "residency_rule": "ANY",
        "base_fee_cents": 80000,
        "proration_policy": "PRORATED_WEEKLY",
        "term_start": TERM_START,
        "term_end": TERM_END,
        "quota": 5,
    }
    payload.update(overrides)
    return payload


class TestAllocationUniqueness:
    def test_create_allocation_rejects_duplicate_code_per_lot(self, api, admin_headers):
        """PRD §3.2: "The pair (`lot_id`, `permit_code`) is unique — creating
        a second allocation with the same pair is rejected with
        `ERR_DUPLICATE_ALLOCATION_CODE` (HTTP 409)."

        Design: Corner/entities/create_allocation_rejects_duplicate_code_per_lot
        """
        lot_1 = create_lot(lot_code="L1", name="Lot 1")
        lot_2 = create_lot(lot_code="L2", name="Lot 2", zone="REMOTE")
        create_allocation(lot_1["id"], permit_code="GEN", eligible_roles=["STUDENT"], quota=5)

        dup = api.create_allocation(
            _allocation_payload(lot_1["id"], eligible_roles=["STAFF"], base_fee_cents=90000,
                                proration_policy="FLAT_HALF_TERM", quota=3),
            admin_headers,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_ALLOCATION_CODE, 409)

        ok = api.create_allocation(
            _allocation_payload(lot_2["id"], eligible_roles=["STAFF"], base_fee_cents=90000,
                                proration_policy="FLAT_HALF_TERM", quota=3),
            admin_headers,
        )
        data = validate_success(ok, 201)
        assert data["permit_code"] == "GEN", (
            "the same permit_code on a different lot must be accepted"
        )


class TestAllocationInitialStatus:
    def test_allocation_zero_quota_starts_waitlisting(self, api, admin_headers):
        """PRD §3.2: "The allocation's `status` is `OPEN` when created with
        `quota > 0`, else `WAITLISTING`."

        Design: Corner/state_machines/allocation_zero_quota_starts_waitlisting
        """
        lot = create_lot(lot_code="LZ", name="Lot Z", zone="REMOTE")
        resp = api.create_allocation(
            _allocation_payload(lot["id"], permit_code="ZERO", quota=0), admin_headers
        )
        data = validate_success(resp, 201)
        assert_lot_allocation(data)
        assert data["status"] == "WAITLISTING", (
            f"quota-0 allocation must start WAITLISTING, got {data['status']}"
        )
        assert data["allocated_count"] == 0
        assert data["offers_outstanding"] == 0


class TestQuotaBoundary:
    def _setup(self):
        patrons = [
            create_patron(full_name=f"U{i}", campus_role="STUDENT",
                          residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
            for i in (1, 2, 3)
        ]
        lot = create_lot(lot_code="LQ", name="Lot Q")
        allocation = create_allocation(lot["id"], eligible_roles=["STUDENT"], quota=2)
        return patrons, allocation

    def test_quota_exact_fill_flips_to_waitlisting(self, api, admin_headers):
        """PRD §3.2: "Thereafter the status is system-managed: after any
        mutation that leaves `allocated_count + offers_outstanding` greater
        than or equal to `quota`, the allocation flips to `WAITLISTING`; after
        any mutation that leaves the sum strictly below `quota`, it flips back
        to `OPEN`."

        Design: Difficulty/boundary_precision_check/quota_boundary_exact_fill_then_reject
        """
        patrons, allocation = self._setup()
        p1 = purchase_permit(patrons[0]["id"], allocation["id"], "U111")
        assert p1["status"] == "ACTIVE"
        mid = get_allocation(allocation["id"])
        assert mid["status"] == "OPEN", (
            f"one of two seats filled must keep the allocation OPEN, got {mid['status']}"
        )

        p2 = purchase_permit(patrons[1]["id"], allocation["id"], "U222")
        assert p2["status"] == "ACTIVE", (
            "the purchase that fills the last seat must succeed (equality with quota)"
        )
        full = get_allocation(allocation["id"])
        assert full["allocated_count"] == 2, (
            f"allocated_count must be exactly 2, got {full['allocated_count']}"
        )
        assert full["status"] == "WAITLISTING", (
            f"allocated_count == quota must flip status to WAITLISTING, got {full['status']}"
        )

    def test_purchase_beyond_full_quota_rejected(self, api, admin_headers):
        """PRD §3.2: "New permit purchases against a `WAITLISTING` allocation
        are rejected with `ERR_ALLOCATION_NOT_OPEN` (HTTP 409); waitlist joins
        against an `OPEN` allocation are rejected with
        `ERR_ALLOCATION_NOT_WAITLISTING` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/quota_boundary_exact_fill_then_reject
        """
        patrons, allocation = self._setup()
        purchase_permit(patrons[0]["id"], allocation["id"], "U111")
        purchase_permit(patrons[1]["id"], allocation["id"], "U222")

        version = get_allocation(allocation["id"])["version"]
        resp = api.create_permit(
            {
                "patron_id": patrons[2]["id"],
                "allocation_id": allocation["id"],
                "plate_number": "U333",
                "expected_allocation_version": version,
            },
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_OPEN, 409)
        after = get_allocation(allocation["id"])
        assert after["allocated_count"] == 2, "rejected purchase must not consume a seat"


class TestAllocationOcc:
    def test_occ_quota_adjust_stale_version_rejected(self, api, admin_headers):
        """PRD §2.6: "If `expected_allocation_version` does not match the
        allocation's current `version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412). The canonical read before any such
        write is `GET /parking/allocations/{allocationId}`, which returns the
        allocation's current `version`."

        Design: Corner/cross_cutting_complexity_layers/occ_quota_adjust_stale_version_rejected
        """
        lot = create_lot(lot_code="LQ", name="Lot Q")
        allocation = create_allocation(lot["id"], eligible_roles=["STUDENT"], quota=5)
        observed_version = allocation["version"]

        first = api.patch_allocation(
            allocation["id"],
            {"quota": 7, "expected_allocation_version": observed_version},
            admin_headers,
        )
        first_data = validate_success(first, 200)
        assert first_data["quota"] == 7, f"quota must update to 7, got {first_data['quota']}"
        assert first_data["version"] == observed_version + 1, (
            f"a mutation must increment version by 1, got {first_data['version']}"
        )

        stale = api.patch_allocation(
            allocation["id"],
            {"quota": 9, "expected_allocation_version": observed_version},
            admin_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
        after = get_allocation(allocation["id"])
        assert after["quota"] == 7, f"stale adjustment must not apply; quota is {after['quota']}"

    def test_version_increments_on_each_mutation(self, api, admin_headers):
        """PRD §2.4: "`version` — an integer starting at `1` on creation and
        incremented by exactly `1` on every mutation of that entity."
        PRD §3.3: "On successful purchase the permit is created `ACTIVE`, the
        allocation's `allocated_count` increments by `1`, the allocation's
        `status` is re-evaluated, the allocation's `version` increments, the
        transportation fund's `permit_revenue_cents` increases by
        `fee_paid_cents`, and any applied incentive credit is debited from the
        patron's incentive account."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
        """
        patron = create_patron(full_name="A", campus_role="STUDENT",
                               residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        lot = create_lot(lot_code="LV", name="Lot V")
        allocation = create_allocation(lot["id"], eligible_roles=["STUDENT"], quota=5)
        assert allocation["version"] == 1, (
            f"creation version must be 1, got {allocation['version']}"
        )

        patched = api.patch_allocation(
            allocation["id"], {"quota": 8, "expected_allocation_version": 1}, admin_headers
        )
        patched_data = validate_success(patched, 200)
        assert patched_data["version"] == 2, (
            f"quota adjustment must increment version to 2, got {patched_data['version']}"
        )

        resp = api.create_permit(
            {
                "patron_id": patron["id"],
                "allocation_id": allocation["id"],
                "plate_number": "A111",
                "expected_allocation_version": 2,
            },
            admin_headers,
        )
        validate_success(resp, 201)
        after = get_allocation(allocation["id"])
        assert after["version"] == 3, (
            f"permit purchase must increment allocation version to 3, got {after['version']}"
        )


class TestImmediateConsistency:
    def test_purchase_response_immediately_reflects_state(self, api, admin_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.3: "On successful purchase the permit is created `ACTIVE`, the
        allocation's `allocated_count` increments by `1`, the allocation's
        `status` is re-evaluated, the allocation's `version` increments, the
        transportation fund's `permit_revenue_cents` increases by
        `fee_paid_cents`, and any applied incentive credit is debited from the
        patron's incentive account."

        Design: Corner/consistency_model/purchase_response_immediately_reflects_state
        """
        patron = create_patron(full_name="A", campus_role="STUDENT",
                               residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        lot = create_lot(lot_code="LC", name="Lot C")
        allocation = create_allocation(lot["id"], eligible_roles=["STUDENT"], quota=5)
        version = allocation["version"]

        resp = api.create_permit(
            {
                "patron_id": patron["id"],
                "allocation_id": allocation["id"],
                "plate_number": "A111",
                "expected_allocation_version": version,
            },
            admin_headers,
        )
        permit = validate_success(resp, 201)
        assert_permit(permit)
        assert_permit_fee_consistency(permit)
        assert permit["status"] == "ACTIVE", (
            f"write response must carry the final ACTIVE status, got {permit['status']}"
        )
        assert permit["fee_total_cents"] == 84000, (
            f"full-term fee at the default clock must be 84000, got {permit['fee_total_cents']}"
        )

        after = get_allocation(allocation["id"])
        assert after["allocated_count"] == 1, (
            f"the immediately following read must show allocated_count 1, "
            f"got {after['allocated_count']}"
        )
