"""Optimistic concurrency on inventory adjustments and immediate read consistency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_inventory,
    assert_version_incremented,
    create_adjustment_payload,
    create_agency,
    init_inventory,
    size_entry,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["bank_admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_manager_headers"]


class TestInventoryOptimisticConcurrency:
    def test_inventory_adjustment_occ_stale_version(self, api):
        """PRD §2.12: "The adjustment request must carry `expected_inventory_version`, a non-optional field holding the client-adjusted value of the inventory's `version` as last observed. The absolute correction in the request is computed from that observed state, so if any other write — an intake post, a void, a recount, a fulfillment, a publish — has advanced the inventory's `version` since the client last read it, the request's absolute value is stale and the adjustment is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing a fresh read and a recomputed correction."
        PRD §3.2: "A successful adjustment sets that size's `on_hand_units` to the supplied absolute value and increments the inventory's `version`."

        Design: Corner/cross_cutting_layers/inventory_adjustment_occ_stale_version
        """
        inventory = init_inventory()
        observed_version = inventory["version"]

        # First adjustment succeeds against the observed version.
        first = validate_success(
            api.create_inventory_adjustment(
                create_adjustment_payload("SIZE_1", 1000, "cycle count",
                                          observed_version),
                WAREHOUSE,
            ),
            200,
        )
        assert_inventory(first)
        assert_version_incremented(first["version"], observed_version)
        assert size_entry(first, "SIZE_1")["on_hand_units"] == 1000
        fresh_version = first["version"]

        # Replaying the pre-write version is stale: rejected with 412.
        resp = api.create_inventory_adjustment(
            create_adjustment_payload("SIZE_1", 900, "recount", observed_version),
            WAREHOUSE,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        current = validate_success(api.get_inventory(WAREHOUSE), 200)
        assert size_entry(current, "SIZE_1")["on_hand_units"] == 1000, (
            "A stale adjustment applies no correction"
        )
        assert current["version"] == fresh_version

        # A fresh read plus a recomputed correction succeeds.
        retried = validate_success(
            api.create_inventory_adjustment(
                create_adjustment_payload("SIZE_1", 900, "recount",
                                          current["version"]),
                WAREHOUSE,
            ),
            200,
        )
        assert size_entry(retried, "SIZE_1")["on_hand_units"] == 900
        assert_version_incremented(retried["version"], fresh_version)


class TestImmediateConsistency:
    def test_immediate_read_after_patch(self, api):
        """PRD §1: "The consistency model is immediate: every mutation is atomically visible in its own response, and every derived counter described in this document is reconciled in the same request that invalidates it."
        PRD §3.1: "Enrollment values are not immutable: a `BankAdmin` may update an agency's `children_served_monthly`, `storage_capacity_units`, or `contact_email`, and each such update increments the agency's `version`."

        Design: Corner/consistency_model/immediate_read_after_patch
        """
        agency = create_agency(children_served_monthly=100)
        created_version = agency["version"]

        patched = validate_success(
            api.patch_agency(agency["id"], {"children_served_monthly": 450}, ADMIN),
            200,
        )
        assert patched["children_served_monthly"] == 450

        fetched = validate_success(api.get_agency(agency["id"], ADMIN), 200)
        assert fetched["children_served_monthly"] == 450, (
            "The very next read observes the mutation"
        )
        assert fetched["version"] == created_version + 1, (
            "Exactly one modification has occurred since creation"
        )
