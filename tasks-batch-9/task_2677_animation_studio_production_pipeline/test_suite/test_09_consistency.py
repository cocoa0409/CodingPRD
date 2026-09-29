"""Consistency test: derived reuse credit is visible to descendants with no lag."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_two_decimal
from test_helpers.constants import LIBRARY_APPROVED, LIBRARY_CANDIDATE
from test_helpers.test_users import ARTIST_HEADERS, SUPERVISOR_HEADERS, SUPERVISOR_USER_ID


class TestReuseCreditVisibility:
    def test_an_ancestor_library_approval_is_credited_on_the_next_descendant_read(
        self, client
    ):
        """A descendant of a mere candidate earns nothing; the instant the ancestor is approved
        the descendant's own read already carries the discount, with no write to that row.

        PRD: "The discount is zero — `reuse_discount_pct` of 0.00 — in any of three cases: the
        depth is 0; the asset's **immediate** source has a `library_status` other than
        `LIBRARY_APPROVED`; or the asset's `reuse_source_stale` flag is true."
        PRD: "Because the chain is walked rather than cached, two guards keep the walk finite."

        Design: Corner/consistency_model/ancestor_library_approval_is_visible_to_descendants_immediately
        """
        production = fx.open_production(
            client, title="Aurora Drift", production_code="AD01"
        )
        ancestor = fx.create_asset(
            client,
            production["id"],
            asset_code="AD01_CHAR_HERO",
            asset_type="CHARACTER_MODEL",
            base_complexity_points=300.00,
        )
        fx.publish_asset(client, ancestor["id"])
        nominated = validate_success(
            client.library_submit_asset(ancestor["id"], {}, ARTIST_HEADERS)
        )
        assert nominated["library_status"] == LIBRARY_CANDIDATE

        descendant = fx.create_asset(
            client,
            production["id"],
            asset_code="AD01_CHAR_RIVAL",
            asset_type="CHARACTER_MODEL",
            base_complexity_points=200.00,
            derived_from_asset_id=ancestor["id"],
        )
        assert descendant["reuse_depth"] == 1
        assert_two_decimal(descendant["reuse_discount_pct"], 0.00, "reuse_discount_pct")
        assert_two_decimal(
            descendant["effective_complexity_points"], 200.00, "effective_complexity_points"
        )

        decided = validate_success(
            client.library_decide_asset(
                ancestor["id"], f.library_decision_payload("APPROVED"), SUPERVISOR_HEADERS
            )
        )
        assert decided["library_status"] == LIBRARY_APPROVED
        assert decided["library_decided_by_user_id"] == SUPERVISOR_USER_ID
        assert_two_decimal(
            decided["effective_complexity_points"], 300.00, "effective_complexity_points"
        )

        credited = fx.read_asset(client, descendant["id"], ARTIST_HEADERS)
        assert_two_decimal(credited["reuse_discount_pct"], 0.40, "reuse_discount_pct")
        assert_two_decimal(
            credited["effective_complexity_points"], 120.00, "effective_complexity_points"
        )
        assert credited["reuse_source_stale"] is False
        assert credited["version"] == 1

        rows, meta = validate_paginated(
            client.list_assets(
                ARTIST_HEADERS,
                {
                    "production_id": production["id"],
                    "derived_from_asset_id": ancestor["id"],
                },
            )
        )
        assert meta["total_count"] == 1
        assert_two_decimal(
            rows[0]["effective_complexity_points"], 120.00, "effective_complexity_points"
        )
