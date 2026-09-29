"""
The two expected-version writes, exercised across a whole accept-refuse-retry cycle.

PRD 2.9 declares exactly two of them - the oversell-allowance write against the
allotment's own version, and promotion creation against its parent sailing's version -
and PRD 2.10 places both at tier 9, above every state and calendar rule.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ERR_STALE_INVENTORY_VERSION,
    ERR_STALE_SAILING_VERSION,
    REVENUE_MANAGER,
    assert_capacity_identity,
    assert_version_is,
    factories as f,
    fixtures as fx,
)


def test_the_same_allotment_version_is_accepted_once_and_then_never_again(api):
    """One version, one write: the refusal hands back the only value that still works.

    PRD 2.9: "Re-setting an allotment's oversell allowance requires
    `expected_inventory_version` in the request body, carrying the client's last observed
    `version` of the target allotment row. If that value does not equal the allotment's
    current `version`, the request is rejected with `ERR_STALE_INVENTORY_VERSION` and HTTP
    412." PRD 3.1: "A `RevenueManager` re-sets `oversell_allowance` on an allotment,
    supplying the new value together with the `expected_inventory_version` guard described
    in §2.9; on success the allotment's `effective_oversell_cabins` and `available_cabins`
    are recomputed and its `version` is incremented by 1."

    Design: Corner/cross_cutting_complexity_layers/oversell_patch_with_the_current_version_succeeds_and_bumps_it
    """
    fx.set_clock(api)
    category = fx.make_guarantee_category(api)
    sailing = fx.make_sailing(api, voyage_code="OCC-2701")
    inventory = fx.make_inventory(
        api, sailing["id"], category["id"], physical_cabins=60, oversell_allowance=4
    )
    first_version = inventory["version"]

    raised = validate_success(
        api.patch_sailing_inventory(
            inventory["id"],
            {"oversell_allowance": 6, "expected_inventory_version": first_version},
            REVENUE_MANAGER,
        )
    )
    assert raised["oversell_allowance"] == 6
    # min(6, ceil(60 x 0.10) == 6) is 6, so the whole appetite is usable.
    assert raised["effective_oversell_cabins"] == 6
    assert raised["available_cabins"] == 66
    assert raised["version"] == first_version + 1
    assert_capacity_identity(raised)
    second_version = raised["version"]

    # The same observed version cannot authorise a second decision.
    validate_error(
        api.patch_sailing_inventory(
            inventory["id"],
            {"oversell_allowance": 3, "expected_inventory_version": first_version},
            REVENUE_MANAGER,
        ),
        ERR_STALE_INVENTORY_VERSION,
        412,
    )
    unmoved = fx.read_inventory(api, inventory["id"])
    # A 412 writes nothing at all - not even the version.
    assert unmoved["oversell_allowance"] == 6
    assert unmoved["effective_oversell_cabins"] == 6
    assert unmoved["available_cabins"] == 66
    assert_version_is(unmoved, second_version)

    lowered = validate_success(
        api.patch_sailing_inventory(
            inventory["id"],
            {"oversell_allowance": 3, "expected_inventory_version": second_version},
            REVENUE_MANAGER,
        )
    )
    assert lowered["oversell_allowance"] == 3
    assert lowered["effective_oversell_cabins"] == 3
    assert lowered["available_cabins"] == 63
    assert lowered["version"] == second_version + 1
    assert_capacity_identity(lowered)

    # Three attempts, two accepted writes, exactly two version bumps.
    assert lowered["version"] == first_version + 2


def test_the_first_campaign_kills_the_version_the_second_one_was_drafted_against(api):
    """The parent bumps itself as a side effect of the child create, so the retry must re-read.

    PRD 2.9: "Creating a promotion requires `expected_sailing_version` in the request
    body, carrying the client's last observed `version` of the parent sailing. If that
    value does not equal the sailing's current `version`, the request is rejected with
    `ERR_STALE_SAILING_VERSION` and HTTP 412." PRD 3.2: "The campaign is created in
    `SCHEDULED` with `redemption_count` at 0 and `withdraw_reason` null, and creating it
    increments the parent sailing's `version` by 1." The calendar rule is not what
    refuses here: "A new campaign's closed interval must be separated from the closed
    interval of every existing non-`WITHDRAWN` campaign on the same sailing by at least 7
    whole days", and PRD 2.10 puts that check at tier 16, well below tier 9.

    Design: Corner/cross_cutting_complexity_layers/promotion_creation_with_a_superseded_sailing_version_is_refused
    """
    world = fx.simple_world(api, voyage_code="PRM-2701")
    opened_version = world.sailing["version"]

    first = validate_success(
        api.create_promotion(
            f.promotion_payload(
                world.sailing["id"],
                opened_version,
                code="EARLYBIRD",
                discount_pct=0.15,
                starts_on="2026-08-01T00:00:00Z",
                ends_on="2026-08-05T00:00:00Z",
                max_redemptions=10,
            ),
            REVENUE_MANAGER,
        ),
        201,
    )
    assert first["status"] == "SCHEDULED"
    assert first["redemption_count"] == 0

    after_first = fx.read_sailing(api, world.sailing["id"])
    assert after_first["version"] == opened_version + 1
    current_version = after_first["version"]

    late_august = {
        "code": "LATEAUGUST",
        "discount_pct": 0.1,
        "starts_on": "2026-08-13T00:00:00Z",
        "ends_on": "2026-08-20T00:00:00Z",
        "max_redemptions": 5,
    }
    # 2026-08-05 to 2026-08-13 is 8 whole days, so the calendar rule would have passed;
    # the version guard answers first.
    validate_error(
        api.create_promotion(
            f.promotion_payload(world.sailing["id"], opened_version, **late_august),
            REVENUE_MANAGER,
        ),
        ERR_STALE_SAILING_VERSION,
        412,
    )
    _, meta = validate_paginated(
        api.list_promotions(REVENUE_MANAGER, params={"sailing_id": world.sailing["id"]})
    )
    assert meta["total_count"] == 1
    # The rejected create bumped nothing.
    assert_version_is(fx.read_sailing(api, world.sailing["id"]), current_version)

    second = validate_success(
        api.create_promotion(
            f.promotion_payload(world.sailing["id"], current_version, **late_august),
            REVENUE_MANAGER,
        ),
        201,
    )
    assert second["status"] == "SCHEDULED"
    assert fx.read_sailing(api, world.sailing["id"])["version"] == current_version + 1

    both, both_meta = validate_paginated(
        api.list_promotions(REVENUE_MANAGER, params={"sailing_id": world.sailing["id"]})
    )
    assert both_meta["total_count"] == 2
    assert sorted(row["code"] for row in both) == ["EARLYBIRD", "LATEAUGUST"]
