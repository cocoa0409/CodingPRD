"""Rejection-ladder precedence when one request breaks two rules at once."""

from test_helpers import fixtures, get_success_data, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import DEFAULT_CLOCK_UTC, clock_stamp
from test_helpers.factories import create_pledge_allocation_payload
from test_helpers.fixtures import OFFICER, REGULATOR

LATER_CLOCK = "2026-08-04T00:00:00Z"


def _agreement_with_three_probe_assets(client):
    """One executed agreement at custodian A, plus three registered securities: a revenue bond
    at custodian B (both rules broken), a treasury at custodian B (only the alignment rule) and
    a revenue bond at custodian A (only the type rule)."""
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    other_custodian = fixtures.create_approved_custodian(
        client,
        name="Second Custody Bank",
        custodian_type="FEDERAL_RESERVE",
        tri_party_capable=True,
        concentration_limit_bps=10000,
    )
    perimeter["both_asset_id"] = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        other_custodian["id"],
        asset_type="MUNI_REVENUE",
        par_value_cents=90_000_000,
        market_price_bps=10000,
    )["id"]
    perimeter["custodian_only_asset_id"] = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        other_custodian["id"],
        asset_type="US_TREASURY",
        par_value_cents=90_000_000,
        market_price_bps=10000,
    )["id"]
    perimeter["type_only_asset_id"] = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        asset_type="MUNI_REVENUE",
        par_value_cents=90_000_000,
        market_price_bps=10000,
    )["id"]
    return perimeter


def _attempt_allocation(client, agreement_id, asset_id, allocated_par_cents, effective_from):
    payload = create_pledge_allocation_payload(
        agreement_id,
        asset_id,
        allocated_par_cents,
        fixtures.agreement_version(client, agreement_id),
        effective_from=effective_from,
    )
    return client.create_pledge_allocation(payload, OFFICER)


def test_ineligible_collateral_type_is_reported_before_the_custodian_mismatch(client):
    """A revenue bond held at the wrong custodian breaks the collateral-type rung and the
    tri-party alignment rung in one request, and the type rung reports first; nothing is
    written, so the agreement's version and totals are untouched.

    PRD: "When a single request violates more than one rule, the response is determined by the
    **first** rule that fails in the ordering below, not by the most severe violation."
    PRD: "**Collateral type eligibility** — the asset's `asset_type` is a type the state accepts
    for public funds and its `eligibility_status` is `ELIGIBLE`, else
    `ERR_COLLATERAL_TYPE_INELIGIBLE` (HTTP 422)."
    PRD: "**Custodian alignment** — the asset's `custodian_id` equals the agreement's
    `custodian_id`, else `ERR_CUSTODIAN_MISMATCH` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/ineligible_collateral_type_outranks_custodian_mismatch
    """
    perimeter = _agreement_with_three_probe_assets(client)
    version_before = fixtures.agreement_version(client, perimeter["agreement_id"])

    response = _attempt_allocation(
        client,
        perimeter["agreement_id"],
        perimeter["both_asset_id"],
        80_000_000,
        DEFAULT_CLOCK_UTC,
    )
    validate_error(response, ApiErrorId.ERR_COLLATERAL_TYPE_INELIGIBLE.value, 422)

    allocations, meta = validate_paginated(
        client.list_pledge_allocations(
            OFFICER, {"pledge_agreement_id": perimeter["agreement_id"]}
        )
    )
    assert allocations == []
    assert meta["total_count"] == 0

    agreement = get_success_data(
        client.get_pledge_agreement(perimeter["agreement_id"], OFFICER), 200
    )
    assert agreement["version"] == version_before
    assert agreement["total_collateral_value_cents"] == 0


def test_each_of_the_two_rungs_still_fires_on_its_own(client):
    """The precedence is genuine, not a masking artefact: a well-typed security at the wrong
    custodian reports the alignment failure, and a revenue bond at the right custodian reports
    the type failure.

    PRD: "`MUNI_REVENUE` occupies a special position: its haircut is defined for completeness,
    but revenue bonds are **not** an eligible collateral type for public funds in this
    jurisdiction, so any attempt to pledge one, to substitute into one, or to credit one against
    a margin call is refused with `ERR_COLLATERAL_TYPE_INELIGIBLE` — as is any attempt involving
    an asset whose own `eligibility_status` has been set to `INELIGIBLE`."
    PRD: "The asset's `custodian_id` must equal the agreement's `custodian_id`, else
    `ERR_CUSTODIAN_MISMATCH`; and the asset's `depository_id` must equal the agreement's
    `depository_id`, else `ERR_DEPOSITORY_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/ineligible_collateral_type_outranks_custodian_mismatch
    """
    perimeter = _agreement_with_three_probe_assets(client)

    custodian_only = _attempt_allocation(
        client,
        perimeter["agreement_id"],
        perimeter["custodian_only_asset_id"],
        80_000_000,
        DEFAULT_CLOCK_UTC,
    )
    validate_error(custodian_only, ApiErrorId.ERR_CUSTODIAN_MISMATCH.value, 422)

    type_only = _attempt_allocation(
        client,
        perimeter["agreement_id"],
        perimeter["type_only_asset_id"],
        80_000_000,
        DEFAULT_CLOCK_UTC,
    )
    validate_error(type_only, ApiErrorId.ERR_COLLATERAL_TYPE_INELIGIBLE.value, 422)


def _thinly_capitalised_asset_gone_stale(client):
    """One tiny 1,000,000-cent treasury registered on 1 August, with the clock then wound
    forward three days so its price observation is 72 hours old."""
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        asset_type="US_TREASURY",
        par_value_cents=1_000_000,
        market_price_bps=10000,
    )
    assert asset["priced_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    fixtures.set_clock(client, LATER_CLOCK)
    perimeter["asset_id"] = asset["id"]
    return perimeter


def test_a_stale_price_is_reported_before_the_oversubscription(client):
    """Pledging twice an asset's par against a price observed 72 hours ago breaks both the
    freshness rung and the capacity rung; the freshness rung reports first even though the
    capacity breach is the larger economic error.

    PRD: "Because a stale price is not evidence of value, an asset whose `priced_at` is more
    than 48 hours behind the logical clock may not back a new pledge or a new substitution, and
    the attempt is refused with `ERR_STALE_COLLATERAL_PRICE`."
    PRD: "**Price freshness** — `ERR_STALE_COLLATERAL_PRICE` (HTTP 422) on creating a pledge
    allocation or a substitution request against an asset whose last price observation is too
    old."
    PRD: "**Par capacity** — `ERR_ALLOCATION_OVERSUBSCRIBED` (HTTP 409) when a pledge would
    commit more of an asset's par than the asset has, at some instant of the requested interval."

    Design: Difficulty/priority_pair_validation_conflict/stale_collateral_price_outranks_allocation_oversubscription
    """
    perimeter = _thinly_capitalised_asset_gone_stale(client)

    response = _attempt_allocation(
        client, perimeter["agreement_id"], perimeter["asset_id"], 2_000_000, LATER_CLOCK
    )
    validate_error(response, ApiErrorId.ERR_STALE_COLLATERAL_PRICE.value, 422)

    _allocations, meta = validate_paginated(
        client.list_pledge_allocations(
            OFFICER, {"pledge_agreement_id": perimeter["agreement_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_fresh_price_uncovers_the_capacity_breach_underneath(client):
    """Re-posting the same price re-stamps the observation without changing it, after which the
    byte-identical pledge finally reports the capacity breach, and a pledge cut back to exactly
    the asset's par succeeds and carries the account to a 124 basis point coverage.

    PRD: "A `SystemOperator` or a `BankCollateralOfficer` posts a new `market_price_bps`, which
    must be strictly positive, against an asset whose `eligibility_status` is still `ELIGIBLE`;
    the asset self-loops in `ELIGIBLE`, its `priced_at` is re-stamped from the clock, and its
    `market_value_cents` and `collateral_value_cents` are recomputed."
    PRD: "Considering every instant inside the requested half-open interval, the sum of
    `allocated_par_cents` of the asset's `ACTIVE` allocations that overlap that instant, plus the
    newly requested `allocated_par_cents`, must not exceed the asset's `par_value_cents`."
    PRD: "From `pledged_par_cents` the service also derives `pledge_status`: `UNPLEDGED` when
    nothing is pledged, `PARTIALLY_PLEDGED` when some but not all of the par is pledged, and
    `FULLY_PLEDGED` when the pledged par equals `par_value_cents` exactly."

    Design: Difficulty/priority_pair_validation_conflict/stale_collateral_price_outranks_allocation_oversubscription
    """
    perimeter = _thinly_capitalised_asset_gone_stale(client)

    repriced = fixtures.post_price(client, perimeter["asset_id"], 10000)
    assert repriced["priced_at"] == clock_stamp(LATER_CLOCK)
    assert repriced["market_price_bps"] == 10000

    oversubscribed = _attempt_allocation(
        client, perimeter["agreement_id"], perimeter["asset_id"], 2_000_000, LATER_CLOCK
    )
    validate_error(oversubscribed, ApiErrorId.ERR_ALLOCATION_OVERSUBSCRIBED.value, 409)

    allocation = fixtures.create_allocation(
        client,
        perimeter["agreement_id"],
        perimeter["asset_id"],
        1_000_000,
        effective_from=LATER_CLOCK,
    )
    assert allocation["allocated_par_cents"] == 1_000_000
    assert allocation["allocated_collateral_value_cents"] == 980_000

    asset = get_success_data(
        client.get_collateral_asset(perimeter["asset_id"], REGULATOR), 200
    )
    assert asset["pledged_par_cents"] == 1_000_000
    assert asset["available_par_cents"] == 0
    assert asset["pledge_status"] == "FULLY_PLEDGED"

    account = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert account["assigned_collateral_value_cents"] == 980_000
    assert account["coverage_ratio_bps"] == 124
    assert account["collateral_status"] == "DEFICIENT"
