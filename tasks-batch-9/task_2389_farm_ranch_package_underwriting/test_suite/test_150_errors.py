"""The fiscal rung of the ladder, walked one refusal at a time: the three guards
that stand in front of a rating, the utilization that aborts one outright, and the
producer's limit that is read at the moment of binding."""

from test_helpers import (
    ApiErrorId,
    UW,
    add_scheduled_item,
    bind_policy,
    bind_policy_ok,
    bootstrap_zone,
    open_account,
    open_policy,
    open_pool,
    patch_agent_ok,
    patch_pool,
    rate_policy,
    rate_policy_ok,
    read_ledger,
    read_policy,
    read_pool,
    reservation_by_peril,
    setup_rated_dwelling_policy,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_three_rating_guards_speak_in_their_declared_order(api):
    """"Business fiscal, in this order: `ERR_CAT_POOL_NOT_CONFIGURED` (422), then
    `ERR_NO_RATEABLE_EXPOSURE` (422), then `ERR_POOL_FROZEN` (409), then
    `ERR_CAT_CAPACITY_EXCEEDED` (409), then `ERR_AGENT_AUTHORITY_EXCEEDED` (422)."
    A zone missing its wildfire pool reports the pool first even though the policy
    has nothing rateable either — "the account's `cat_zone_code` must have a
    configured pool for each of `HAIL`, `WIND` and `WILDFIRE`, or the call fails
    with `ERR_CAT_POOL_NOT_CONFIGURED`." Then "the policy must offer something
    rateable — at least one scheduled item whose `status` is `ACTIVE`, or at least
    one livestock group — so that `exposed_tiv_cents` will come out above zero;
    otherwise `ERR_NO_RATEABLE_EXPOSURE`." Then "all three pools must be `OPEN`, or
    `ERR_POOL_FROZEN` — a frozen pool is refused before its utilization is even
    computed." Three refusals leave the policy at version 1 with no reservation
    behind them.

    Design: Corner/errors/corner_rating_fiscal_guards_fire_in_priority_order
    """
    scenario = bootstrap_zone(
        zone_code="ZN-7",
        perils=("HAIL", "WIND"),
        account_overrides={"legal_name": "Sandhill Ridge Ranch", "county_name": "Barber"},
    )
    assert set(scenario.pools) == {"HAIL", "WIND"}

    missing_pool = rate_policy(scenario.policy_id)
    validate_error(missing_pool, ApiErrorId.ERR_CAT_POOL_NOT_CONFIGURED.value, 422)

    wildfire = open_pool("ZN-7", "WILDFIRE")
    assert float(wildfire["participation_pct"]) == 0.20
    assert wildfire["version"] == 1

    nothing_rateable = rate_policy(scenario.policy_id)
    validate_error(nothing_rateable, ApiErrorId.ERR_NO_RATEABLE_EXPOSURE.value, 422)

    add_scheduled_item(scenario.agent_headers, scenario.policy_id)
    frozen = validate_success(patch_pool(scenario.hail_pool["id"], status="FROZEN"))
    assert frozen["status"] == "FROZEN"
    assert frozen["version"] == 2

    pool_shut = rate_policy(scenario.policy_id)
    validate_error(pool_shut, ApiErrorId.ERR_POOL_FROZEN.value, 409)

    still_draft = read_policy(scenario.policy_id)
    assert still_draft["uw_status"] == "DRAFT"
    assert still_draft["version"] == 1
    _, no_rows = validate_paginated(
        api.list_cat_reservations(UW, params={"policy_id": scenario.policy_id})
    )
    assert no_rows["total_count"] == 0

    reopened = validate_success(patch_pool(scenario.hail_pool["id"], status="OPEN"))
    assert reopened["status"] == "OPEN"

    rated = rate_policy_ok(scenario.policy_id)

    assert rated["uw_status"] == "RATED"
    assert rated["property_premium_cents"] == 144_000
    assert rated["cat_load_cents"] == 125_200
    assert rated["total_premium_cents"] == 269_200
    assert rated["version"] == 2
    _, three_rows = validate_paginated(
        api.list_cat_reservations(UW, params={"policy_id": scenario.policy_id})
    )
    assert three_rows["total_count"] == 3


def test_an_overfull_hail_pool_refuses_the_whole_rating(api):
    """"`scarcity_factor` is selected from that ratio in four bands: at most 0.50
    gives 1.00, above 0.50 and at most 0.75 gives 1.15, above 0.75 and at most 0.90
    gives 1.35, above 0.90 and at most 1.00 gives 1.60; a ratio strictly greater
    than 1.00 aborts the entire rating call with `ERR_CAT_CAPACITY_EXCEEDED` and
    leaves no reservation behind for any peril." In a hail pool of only 30000000 the
    first policy lands at two thirds of capacity and pays the 1.15 band; the second
    would need 1.333333 of it and is refused outright, so the wind and wildfire
    pools — sized normally and never in doubt — still hold nothing but the first
    policy's amounts. "`cat_load_cents` is then the sum of the three `load_cents`."

    Design: Corner/errors/corner_cat_capacity_exceeded_writes_no_partial_reservation
    """
    scenario = bootstrap_zone(
        zone_code="ZN-8",
        hail_capacity_cents=30_000_000,
        with_policy=False,
        account_overrides={"legal_name": "Thin Pool Farms A", "county_name": "Pratt"},
    )
    headers = scenario.agent_headers
    policy_a = open_policy(headers, scenario.account["id"])
    add_scheduled_item(headers, policy_a["id"])
    account_b = open_account(
        headers, legal_name="Thin Pool Farms B", county_name="Pratt", cat_zone_code="ZN-8"
    )
    policy_b = open_policy(headers, account_b["id"])
    add_scheduled_item(headers, policy_b["id"])

    rated_a = rate_policy_ok(policy_a["id"])

    assert rated_a["uw_status"] == "RATED"
    reservations_a = reservation_by_peril(policy_a["id"])
    assert reservations_a["HAIL"]["amount_cents"] == 20_000_000
    assert float(reservations_a["HAIL"]["utilization_at_rating"]) == 0.666667
    assert float(reservations_a["HAIL"]["scarcity_factor"]) == 1.15
    assert reservations_a["HAIL"]["load_cents"] == 73_600
    assert reservations_a["WIND"]["load_cents"] == 25_200
    assert reservations_a["WILDFIRE"]["load_cents"] == 36_000
    assert rated_a["cat_load_cents"] == 134_800
    assert rated_a["total_premium_cents"] == 278_800

    refused = rate_policy(policy_b["id"])

    validate_error(refused, ApiErrorId.ERR_CAT_CAPACITY_EXCEEDED.value, 409)
    _, none_for_b = validate_paginated(
        api.list_cat_reservations(UW, params={"policy_id": policy_b["id"]})
    )
    assert none_for_b["total_count"] == 0

    assert read_pool(scenario.wind_pool["id"])["reserved_cents"] == 12_000_000
    assert read_pool(scenario.wildfire_pool["id"])["reserved_cents"] == 8_000_000
    assert read_pool(scenario.hail_pool["id"])["reserved_cents"] == 20_000_000

    untouched = read_policy(policy_b["id"])
    assert untouched["uw_status"] == "DRAFT"
    assert untouched["version"] == 1
    for field in (
        "property_premium_cents",
        "livestock_premium_cents",
        "liability_premium_cents",
        "endorsement_premium_cents",
        "base_premium_cents",
        "cat_load_cents",
        "total_premium_cents",
        "exposed_tiv_cents",
    ):
        assert untouched[field] == 0
    assert read_ledger(policy_b["id"]) == []


def test_the_producer_limit_is_read_at_the_bind_and_nowhere_else(api):
    """"Finally `total_premium_cents` must not exceed the producer's
    `authority_limit_cents`, or `ERR_AGENT_AUTHORITY_EXCEEDED`." Cutting the limit
    to 100000 after the 269200 quote was struck therefore refuses the bind without
    disturbing the quote, because "the implementer should assume nothing cascades
    that §3 does not say cascades — in particular, changing a producer's appointment
    standing or authority limit never revisits policies already bound, and
    deactivating an inspector never disturbs inspections already on the calendar."
    The policy keeps its version, so the same expected version binds once the limit
    is restored, and "no premium figure changes on bind."

    Design: Corner/errors/corner_agent_authority_limit_blocks_the_bind
    """
    scenario = setup_rated_dwelling_policy()
    rated = read_policy(scenario.policy_id)
    assert rated["total_premium_cents"] == 269_200

    lowered = patch_agent_ok(scenario.agent_id, authority_limit_cents=100_000)
    assert lowered["authority_limit_cents"] == 100_000

    refused = bind_policy(scenario.policy_id)

    validate_error(refused, ApiErrorId.ERR_AGENT_AUTHORITY_EXCEEDED.value, 422)
    held = read_policy(scenario.policy_id)
    assert held["uw_status"] == "RATED"
    assert held["version"] == rated["version"]
    assert held["total_premium_cents"] == 269_200
    assert held["bound_at"] is None
    assert {row["status"] for row in reservation_by_peril(scenario.policy_id).values()} == {
        "RESERVED"
    }

    restored = patch_agent_ok(scenario.agent_id, authority_limit_cents=5_000_000)
    assert restored["authority_limit_cents"] == 5_000_000

    bound = bind_policy_ok(scenario.policy_id)

    assert bound["uw_status"] == "BOUND"
    assert bound["total_premium_cents"] == 269_200
    assert bound["cat_load_cents"] == 125_200
    assert bound["version"] == rated["version"] + 1
    assert {row["status"] for row in reservation_by_peril(scenario.policy_id).values()} == {
        "COMMITTED"
    }
