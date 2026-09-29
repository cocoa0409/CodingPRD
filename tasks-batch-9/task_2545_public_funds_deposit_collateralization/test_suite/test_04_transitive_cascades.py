"""Two four-hop cascades: regulatory suspension and substitution settlement."""

from test_helpers import assertions, fixtures, get_success_data, validate_paginated
from test_helpers.fixtures import OFFICER, REGULATOR
from test_helpers.test_users import make_public_unit_treasurer_headers

HORIZON_START = "2026-08-01T00:00:00Z"
HORIZON_END = "2026-08-31T00:00:00Z"


def _approved_bank_with_a_forecast(client):
    """An approved bank with one funded county demand account and one open forecast on it."""
    fixtures.set_clock(client)
    public_unit = fixtures.create_public_unit(client)
    depository = fixtures.create_approved_depository(client)
    account = fixtures.create_funded_account(
        client, depository["id"], public_unit["id"], 100_000_000
    )
    forecast = fixtures.file_forecast(
        client,
        account["id"],
        public_unit["id"],
        HORIZON_START,
        HORIZON_END,
        fixtures.contiguous_windows([HORIZON_START, HORIZON_END], [100_000_000]),
    )
    assert forecast["status"] == "OPEN"
    assert forecast["requires_reforecast"] is False
    return {
        "public_unit_id": public_unit["id"],
        "depository_id": depository["id"],
        "account_id": account["id"],
        "forecast_id": forecast["id"],
    }


def test_one_suspension_reaches_the_open_forecast_four_hops_away(client):
    """A single suspend call walks the chain end to end: the bank goes SUSPENDED, its account
    goes RESTRICTED for DEPOSITORY_SUSPENDED, the owning unit goes ESCALATED, and the open
    forecast — reachable only through those two intermediate hops — goes STALE and asks to be
    reforecast.

    PRD: "Hop one sets the depository's `approval_status` to `SUSPENDED` and increments its
    `version`."
    PRD: "Hop two, caused by hop one, moves every deposit account of that depository whose
    `funding_status` is `PENDING_FUNDING` or `FUNDED` to `RESTRICTED`, records
    `restricted_reason` as `DEPOSITORY_SUSPENDED` on each, and increments each account's
    `version`; a restricted account's `required_collateral_cents` is *not* zeroed, because a
    restricted balance still has to be collateralised."
    PRD: "Hop three, caused by hop two, recomputes `exposure_status` for every public unit that
    owns an account which just became restricted, and each such unit becomes `ESCALATED`."
    PRD: "Hop four, caused by hop three, moves every runoff forecast in `OPEN` status whose
    `deposit_account_id` belongs to one of those escalated units to `STALE` and sets its
    `requires_reforecast` flag to true."

    Design: Difficulty/transitive_cascade/depository_suspension_depth4_cascade_to_runoff_forecast
    """
    world = _approved_bank_with_a_forecast(client)

    suspended = fixtures.suspend_depository(client, world["depository_id"])
    assert suspended["approval_status"] == "SUSPENDED"

    account = get_success_data(
        client.get_deposit_account(world["account_id"], OFFICER), 200
    )
    assert account["funding_status"] == "RESTRICTED"
    assert account["restricted_reason"] == "DEPOSITORY_SUSPENDED"

    unit = get_success_data(client.get_public_unit(world["public_unit_id"], REGULATOR), 200)
    assert unit["exposure_status"] == "ESCALATED"

    forecast = get_success_data(
        client.get_runoff_forecast(world["forecast_id"], REGULATOR), 200
    )
    assert forecast["status"] == "STALE"
    assert forecast["requires_reforecast"] is True

    listed, _meta = validate_paginated(
        client.list_account_runoff_forecasts(
            world["account_id"], make_public_unit_treasurer_headers(world["public_unit_id"])
        )
    )
    assert len(listed) == 1
    assert listed[0]["status"] == "STALE"


def test_suspension_leaves_the_collateral_dimension_and_the_balance_alone(client):
    """The cascade is confined to the funding dimension: after suspension the account is still
    UNSECURED, still holds 100,000,000 cents and still owes 78,750,000 cents of collateral.

    PRD: "Note what suspension does *not* touch: an account's `collateral_status` is an
    independent dimension and is left exactly as it was."
    PRD: "The account's second status dimension, `collateral_status`, is a pure function of
    that ratio and of whether any collateral is assigned at all, and it moves entirely
    independently of `funding_status` — a `RESTRICTED` account still travels between
    `UNSECURED`, `SECURED` and `DEFICIENT`, and a `FUNDED` account's collateral status changes
    without any funding transition."
    PRD: "An account whose `funding_status` is `PENDING_FUNDING`, `FUNDED` or `RESTRICTED` all
    carry a requirement; restriction confers no exemption."

    Design: Difficulty/transitive_cascade/depository_suspension_depth4_cascade_to_runoff_forecast
    """
    world = _approved_bank_with_a_forecast(client)

    before = get_success_data(client.get_deposit_account(world["account_id"], OFFICER), 200)
    assert before["collateral_status"] == "UNSECURED"

    fixtures.suspend_depository(client, world["depository_id"])

    after = get_success_data(client.get_deposit_account(world["account_id"], OFFICER), 200)
    assert after["collateral_status"] == "UNSECURED"
    assert after["ledger_balance_cents"] == 100_000_000
    assert after["insured_amount_cents"] == 25_000_000
    assert after["uninsured_amount_cents"] == 75_000_000
    assert after["required_collateral_cents"] == 78_750_000
    assertions.assert_insured_plus_uninsured_reconciles(after)


def _exactly_secured_arrangement_awaiting_settlement(client):
    """An account covered to exactly 10000 basis points by a single full-par treasury pledge,
    with a substitution already approved and acknowledged, and the incoming security repriced
    downwards while the request waited."""
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    outgoing_asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        asset_type="US_TREASURY",
        par_value_cents=80_357_143,
        market_price_bps=10000,
    )
    allocation = fixtures.create_allocation(
        client, perimeter["agreement_id"], outgoing_asset["id"], 80_357_143
    )
    assert allocation["allocated_collateral_value_cents"] == 78_750_000

    incoming_asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        asset_type="US_TREASURY",
        par_value_cents=100_000_000,
        market_price_bps=10000,
    )
    request = fixtures.create_substitution_request(
        client,
        perimeter["agreement_id"],
        allocation["id"],
        incoming_asset["id"],
        80_500_000,
    )
    approved = fixtures.compliance_approve(client, request["id"])
    assert approved["value_adequacy_delta_cents"] == 140_000
    fixtures.custodian_ack(client, request["id"], perimeter["custodian_id"])
    fixtures.post_price(client, incoming_asset["id"], 9500)

    perimeter.update(
        {
            "outgoing_asset_id": outgoing_asset["id"],
            "incoming_asset_id": incoming_asset["id"],
            "allocation_id": allocation["id"],
            "request_id": request["id"],
        }
    )
    return perimeter


def test_settlement_swaps_the_par_and_restates_the_agreement(client):
    """Settling moves the outgoing allocation to SUBSTITUTED and mints an 80,500,000-cent
    replacement now worth only 74,945,500 cents, and the agreement restates its totals from
    the already-rounded per-allocation values while the frozen approval-time delta of 140,000
    cents is left untouched.

    PRD: "**Hop one** moves the outgoing allocation from `ACTIVE` to `SUBSTITUTED`, stamps its
    `released_at` from the clock, sets its `release_reason` to `SUBSTITUTION_SETTLED`,
    increments its `version`, and reduces the outgoing asset's `pledged_par_cents` by that
    allocation's `allocated_par_cents`."
    PRD: "The two legs are deliberately equal and opposite, so total par in the system is
    conserved."
    PRD: "A depository's `total_pledged_collateral_value_cents` is the sum of
    `total_collateral_value_cents` over its agreements in `EXECUTED` status."

    Design: Difficulty/transitive_cascade/substitution_settlement_depth4_cascade_to_public_unit_watch
    """
    world = _exactly_secured_arrangement_awaiting_settlement(client)

    fixtures.settle_substitution(client, world["request_id"], world["custodian_id"])

    request = get_success_data(
        client.get_substitution_request(world["request_id"], OFFICER), 200
    )
    assert request["status"] == "SETTLED"
    assert request["value_adequacy_delta_cents"] == 140_000

    outgoing_allocation = get_success_data(
        client.get_pledge_allocation(world["allocation_id"], OFFICER), 200
    )
    assert outgoing_allocation["status"] == "SUBSTITUTED"

    minted, _meta = validate_paginated(
        client.list_pledge_allocations(
            OFFICER, {"created_by_substitution_id": world["request_id"]}
        )
    )
    assert len(minted) == 1
    assert minted[0]["status"] == "ACTIVE"
    assert minted[0]["allocated_par_cents"] == 80_500_000
    assert minted[0]["allocated_collateral_value_cents"] == 74_945_500

    outgoing_asset = get_success_data(
        client.get_collateral_asset(world["outgoing_asset_id"], OFFICER), 200
    )
    assert outgoing_asset["pledged_par_cents"] == 0
    assert outgoing_asset["available_par_cents"] == 80_357_143
    assertions.assert_asset_par_conservation(outgoing_asset)

    incoming_asset = get_success_data(
        client.get_collateral_asset(world["incoming_asset_id"], OFFICER), 200
    )
    assert incoming_asset["pledged_par_cents"] == 80_500_000
    assert incoming_asset["available_par_cents"] == 19_500_000
    assertions.assert_asset_par_conservation(incoming_asset)

    agreement = get_success_data(
        client.get_pledge_agreement(world["agreement_id"], OFFICER), 200
    )
    assert agreement["total_collateral_value_cents"] == 74_945_500
    assert agreement["total_pledged_par_cents"] == 80_500_000
    assert agreement["active_allocation_count"] == 1

    depository = get_success_data(
        client.get_depository(world["depository_id"], REGULATOR), 200
    )
    assert depository["total_pledged_collateral_value_cents"] == 74_945_500
    assert depository["total_pledged_par_cents"] == 80_500_000


def test_settlement_carries_the_account_deficient_and_the_unit_onto_watch(client):
    """The account starts exactly secured and its unit normal; the swap drops coverage to 9516
    basis points, so the account turns DEFICIENT and its unit lands on WATCH, while the
    funding dimension stays FUNDED throughout.

    PRD: "**Hop three**, caused by hop two, has every participant deposit account whose
    `assigned_collateral_value_cents` changed recompute `coverage_ratio_bps` and
    `collateral_status`, so an account slips `SECURED → DEFICIENT` when its ratio drops below
    10000."
    PRD: "**Hop four**, caused by hop three, has every public unit owning an account that just
    became `DEFICIENT` recompute `exposure_status` to `WATCH`, provided that unit holds no
    `RESTRICTED` account."
    PRD: "`SECURED → DEFICIENT` when the ratio falls below 10000 while
    `assigned_collateral_value_cents` remains greater than zero — the ordinary consequence of a
    price drop, a requirement increase, an allocation release or a substitution settlement."

    Design: Difficulty/transitive_cascade/substitution_settlement_depth4_cascade_to_public_unit_watch
    """
    world = _exactly_secured_arrangement_awaiting_settlement(client)

    before_account = get_success_data(
        client.get_deposit_account(world["account_id"], OFFICER), 200
    )
    assert before_account["assigned_collateral_value_cents"] == 78_750_000
    assert before_account["coverage_ratio_bps"] == 10000
    assert before_account["collateral_status"] == "SECURED"

    before_unit = get_success_data(
        client.get_public_unit(world["public_unit_id"], REGULATOR), 200
    )
    assert before_unit["exposure_status"] == "NORMAL"

    fixtures.settle_substitution(client, world["request_id"], world["custodian_id"])

    account = get_success_data(client.get_deposit_account(world["account_id"], OFFICER), 200)
    assert account["assigned_collateral_value_cents"] == 74_945_500
    assert account["coverage_ratio_bps"] == 9516
    assert account["collateral_status"] == "DEFICIENT"
    assert account["funding_status"] == "FUNDED"
    assertions.assert_coverage_ratio_floored(account)

    unit = get_success_data(client.get_public_unit(world["public_unit_id"], REGULATOR), 200)
    assert unit["exposure_status"] == "WATCH"
