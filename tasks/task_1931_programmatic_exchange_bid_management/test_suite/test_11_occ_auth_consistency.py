"""Optimistic concurrency on commercial edits, authentication/authorization
basics, unknown-id existence failures, and immediate read-after-write."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_deal,
    create_deal_for,
    create_package_for,
    create_package_payload,
    create_partner,
    create_publisher,
    get_deal,
    make_publisher_manager_headers,
    setup_active_deal,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["exchange_admin_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


class TestOptimisticConcurrency:
    def test_occ_stale_version_on_deal_put(self, api):
        """PRD §2.7: "Editing a deal's commercial terms requires the request to
        carry `expected_deal_version` equal to the deal's current `version`. ...
        if another writer has advanced the entity's version since the client
        last read it, the write is rejected with `ERR_STALE_VERSION` (HTTP 412),
        forcing the client to re-read before overwriting changes it has not
        observed."

        Design: Corner/cross_cutting/occ_stale_version_on_deal_put
        """
        pub = create_publisher()
        sc = setup_active_deal()
        pkg = create_package_for(pub["id"])
        mgr = make_publisher_manager_headers(pub["id"])
        deal = create_deal_for(pub["id"], pkg["id"], sc["partner"]["id"])
        observed_version = deal["version"]

        edited = validate_success(api.update_deal(
            deal["id"],
            {"expected_deal_version": observed_version,
             "floor_cpm_micros": 700000},
            mgr))
        assert edited["version"] == observed_version + 1
        assert edited["floor_cpm_micros"] == 700000

        resp = api.update_deal(
            deal["id"],
            {"expected_deal_version": observed_version,
             "floor_cpm_micros": 900000},
            mgr)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = get_deal(deal["id"])
        assert after["floor_cpm_micros"] == 700000, (
            "The stale write is rejected; the first writer's floor survives")

    def test_occ_stale_version_on_package_put(self, api):
        """PRD §2.7: "Editing an inventory package requires
        `expected_package_version` equal to the package's current `version`."
        PRD §2.7: "the write is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting/occ_stale_version_on_package_put
        """
        pub = create_publisher()
        mgr = make_publisher_manager_headers(pub["id"])
        pkg = validate_success(
            api.create_package(
                create_package_payload(base_floor_cpm_micros=1000000), mgr), 201)
        observed_version = pkg["version"]

        edited = validate_success(api.update_package(
            pkg["id"],
            {"expected_package_version": observed_version,
             "base_floor_cpm_micros": 1500000},
            mgr))
        assert edited["version"] == observed_version + 1
        assert edited["effective_floor_cpm_micros"] == 1500000, (
            "The floor recomputes from the new base (no covering window)")

        resp = api.update_package(
            pkg["id"],
            {"expected_package_version": observed_version,
             "base_floor_cpm_micros": 3000000},
            mgr)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(api.get_package(pkg["id"], ADMIN))
        assert after["effective_floor_cpm_micros"] == 1500000

    def test_occ_stale_version_on_demand_partner_put(self, api):
        """PRD §2.7: "Retuning a demand partner's capacity requires
        `expected_demand_partner_version` equal to the partner's current
        `version`."
        PRD §2.7: "the write is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting/occ_stale_version_on_demand_partner_put
        """
        partner = create_partner(max_qps=10)
        observed_version = partner["version"]

        edited = validate_success(api.update_demand_partner(
            partner["id"],
            {"expected_demand_partner_version": observed_version,
             "max_qps": 50},
            ADMIN))
        assert edited["version"] == observed_version + 1
        assert edited["max_qps"] == 50

        resp = api.update_demand_partner(
            partner["id"],
            {"expected_demand_partner_version": observed_version,
             "max_qps": 99},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(api.get_demand_partner(partner["id"], ADMIN))
        assert after["max_qps"] == 50, "The newer retune survives the stale write"


class TestAuthAndExistence:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, identifying the capacity
        in which they act. ... A request with either header missing or malformed
        is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/missing_auth_headers_unauthenticated
        """
        create_publisher("Seed", "seed.com")
        resp = api.list_publishers({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_unknown_ids_return_not_found(self, api):
        """PRD §2.8: "5. Existence: every path identifier and every body foreign
        key resolves, validated left to right — a deal before its report, a
        batch before its line — else `ERR_NOT_FOUND`."

        Design: Corner/errors/unknown_ids_return_not_found
        """
        create_publisher("Seed", "seed.com")
        resp = api.get_publisher(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        resp = api.get_reconciliation_report(NON_EXISTENT_UUID, FINANCE)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestImmediateConsistency:
    def test_immediate_read_after_write_visibility(self, api):
        """PRD §2.6: "`version` is an integer that starts at creation and
        increments by one on every mutation"
        PRD §3.3: "the version-guarded edit described in §2.7, which increments
        the deal's `version`."
        PRD §3.3: "both the listing and the single-deal read apply the lazy
        expiry sweep before responding" (reads reflect the current state).

        Design: Corner/consistency_model/immediate_read_after_write_visibility
        """
        pub = create_publisher()
        sc = setup_active_deal()
        pkg = create_package_for(pub["id"])
        mgr = make_publisher_manager_headers(pub["id"])
        deal = create_deal_for(pub["id"], pkg["id"], sc["partner"]["id"],
                               floor_cpm_micros=500000)

        fetched = validate_success(api.get_deal(deal["id"], ADMIN))
        assert_deal(fetched)
        assert fetched["status"] == "DRAFT"
        assert fetched["floor_cpm_micros"] == 500000
        assert fetched["version"] == deal["version"], (
            "The very next read reflects the creation values")

        validate_success(api.update_deal(
            deal["id"],
            {"expected_deal_version": deal["version"],
             "floor_cpm_micros": 800000},
            mgr))
        reread = validate_success(api.get_deal(deal["id"], ADMIN))
        assert reread["floor_cpm_micros"] == 800000, (
            "The edit is visible on the immediate re-read")
        assert reread["version"] == deal["version"] + 1
