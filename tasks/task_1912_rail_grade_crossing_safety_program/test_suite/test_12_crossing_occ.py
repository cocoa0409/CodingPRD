"""Optimistic concurrency on crossing inventory patches (PRD §2.6, §3.1)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_success_data,
    setup_locality_and_crossing,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]


class TestCrossingInventoryOcc:
    def test_fresh_version_succeeds_and_stale_replay_rejected(
        self, api, admin_headers
    ):
        """PRD §2.6: "Updating a crossing's inventory requires the request to
        carry `expected_crossing_version`, a non-optional field holding the
        `version` the client last observed on that crossing. If another writer
        has advanced the crossing's `version` since — through an inventory patch,
        a closure execution, or any direct write — the values no longer match and
        the update is rejected with `ERR_STALE_VERSION` (HTTP 412)".
        PRD §3.1: "A successful patch increments the crossing's `version` by
        exactly 1 and recomputes `exposure_index`, `projected_exposure_index`,
        `hazard_score`, and `diagnostic_review_due` from the new inputs."

        Design: Corner/complexity_layers/crossing_inventory_occ_stale_version
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-070001"}
        )
        observed_version = crossing["version"]

        patched = get_success_data(
            api.patch_crossing_inventory(
                crossing["id"],
                {"expected_crossing_version": observed_version, "aadt": 6000},
                admin_headers,
            )
        )
        assert patched["version"] == observed_version + 1
        assert patched["aadt"] == 6000
        # (365/365)*6000/1000 = 6.00
        assert patched["exposure_index"] == pytest.approx(6.00, abs=1e-9)

        # Replaying the stale version is rejected and the inventory is untouched.
        resp = api.patch_crossing_inventory(
            crossing["id"],
            {"expected_crossing_version": observed_version, "aadt": 7000},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        after = get_success_data(api.get_crossing(crossing["id"], ADMIN))
        assert after["aadt"] == 6000
        assert after["version"] == observed_version + 1

    def test_version_advanced_by_closure_execution_stales_inventory_patch(
        self, api, admin_headers
    ):
        """PRD §2.6: "If another writer has advanced the crossing's `version`
        since — through an inventory patch, a closure execution, or any direct
        write — the values no longer match and the update is rejected with
        `ERR_STALE_VERSION` (HTTP 412)". PRD §3.5: "a `ProgramAdministrator` moves
        `LOCALITY_RATIFIED` → `EXECUTED`, which flips the crossing `ACTIVE` →
        `CLOSURE_PENDING` and increments the crossing's `version`."

        Design: Corner/complexity_layers/crossing_inventory_occ_stale_version
        """
        from test_helpers import create_executed_agreement

        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-070002"}
        )
        observed_version = crossing["version"]

        # A closure execution advances the crossing version behind the client.
        create_executed_agreement(crossing["id"], locality["id"])

        resp = api.patch_crossing_inventory(
            crossing["id"],
            {"expected_crossing_version": observed_version, "aadt": 7000},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
