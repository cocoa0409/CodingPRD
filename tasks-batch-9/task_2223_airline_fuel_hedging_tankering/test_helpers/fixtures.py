"""Composite setup helpers.

Two layers live here. The lower layer is one thin ``do_x`` function per write
endpoint, each of which validates leniently with ``get_success_data`` and hands
back the created row, plus ``read_x`` helpers for the version-refresh idiom the
three parented creates force on any client. The upper layer stitches those into
the whole scenario prefixes the tests need — a sized programme over a
season-weighted basis, an active programme with an executed trade, a priced
station pair with a live flight leg — so a test body contains only the trigger
and the assertions.

Nothing here asserts business outcomes; that is the tests' job.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    ACCOUNTANT,
    ADMIN,
    ANALYST,
    ANALYST_USER_ID,
    OPS,
    TREASURY,
    TRM_USER_ID,
    make_analyst_headers,
    make_treasury_headers,
)

# ─── Logical clock ────────────────────────────────────

def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the server's logical clock to a fixed instant."""
    return get_success_data(api.set_clock(current_utc, headers=ADMIN))


#: The instant every tankering scenario runs at: inside the baseline supply
#: contract term and before the baseline leg's departure date.
TANKERING_CLOCK = "2027-02-10T00:00:00Z"

#: The instant the hedge-accounting scenarios run at.
ACCOUNTING_CLOCK = "2027-02-28T00:00:00Z"


# ─── Reads (used for the version-refresh idiom) ────────

def read_policy(api: ApiClient, policy_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_hedge_policy(policy_id, headers=ADMIN))


def read_counterparty(api: ApiClient, counterparty_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_counterparty(counterparty_id, headers=ADMIN))


def read_station(api: ApiClient, station_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_station(station_id, headers=ADMIN))


def read_program(api: ApiClient, program_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_hedge_program(program_id, headers=ANALYST))


def read_instrument(api: ApiClient, instrument_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_hedge_instrument(instrument_id, headers=ADMIN))


def read_mtm_run(api: ApiClient, run_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_mtm_run(run_id, headers=ACCOUNTANT))


def read_flight_leg(api: ApiClient, leg_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_flight_leg(leg_id, headers=ANALYST))


def read_directive(api: ApiClient, directive_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_tankering_directive(directive_id, headers=OPS))


def read_exception(api: ApiClient, exception_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_policy_exception(exception_id, headers=ADMIN))


def list_exceptions(api: ApiClient, **filters: Any) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_policy_exceptions(headers=ADMIN, params=filters or None)
    )


def list_instrument_postings(
    api: ApiClient, instrument_id: str, **filters: Any
) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_instrument_collateral_postings(
            instrument_id, headers=ADMIN, params=filters or None
        )
    )


def list_counterparty_postings(
    api: ApiClient, counterparty_id: str, **filters: Any
) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_counterparty_collateral_postings(
            counterparty_id, headers=ADMIN, params=filters or None
        )
    )


# ─── Reference data ───────────────────────────────────

def do_create_policy(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_hedge_policy(f.hedge_policy_payload(**overrides), headers=ADMIN)
    )


def do_create_counterparty(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_counterparty(f.counterparty_payload(**overrides), headers=ADMIN)
    )


def do_credit_review(
    api: ApiClient,
    counterparty_id: str,
    credit_rating: str,
    review_note: str = "Annual review completed.",
    credit_limit_usd: Optional[float] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.record_credit_review(
            counterparty_id,
            f.credit_review_payload(credit_rating, review_note, credit_limit_usd),
            headers=TREASURY,
        )
    )


def do_create_station(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_station(f.station_payload(**overrides), headers=ADMIN)
    )


def do_create_contract(
    api: ApiClient, station_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_supply_contract(
            station_id, f.supply_contract_payload(**overrides), headers=ADMIN
        )
    )


def do_adjust_inventory(
    api: ApiClient,
    station_id: str,
    delta_gallons: float,
    reason: str = "Barge delivery received.",
    consortium_pool_gallons: Optional[float] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.adjust_station_inventory(
            station_id,
            f.inventory_adjustment_payload(
                delta_gallons, reason, consortium_pool_gallons
            ),
            headers=headers or OPS,
        )
    )


# ─── Forecasts ────────────────────────────────────────

def do_create_forecast(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_consumption_forecast(
            f.consumption_forecast_payload(**overrides), headers=ANALYST
        )
    )


def do_publish_forecast(api: ApiClient, forecast_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.publish_consumption_forecast(forecast_id, headers=ANALYST)
    )


def do_create_published_forecast(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    forecast = do_create_forecast(api, **overrides)
    return do_publish_forecast(api, forecast["id"])


# ─── Programmes ───────────────────────────────────────

def do_create_program(api: ApiClient, policy_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_hedge_program(
            f.hedge_program_payload(policy_id, **overrides), headers=ANALYST
        )
    )


def do_size_program(api: ApiClient, program_id: str) -> Dict[str, Any]:
    return get_success_data(api.size_hedge_program(program_id, headers=ANALYST))


def do_submit_program(
    api: ApiClient, program_id: str, user_id: str = ANALYST_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.submit_hedge_program(program_id, headers=make_analyst_headers(user_id))
    )


def do_return_program(
    api: ApiClient,
    program_id: str,
    user_id: str = TRM_USER_ID,
    return_note: str = "Rework the counterparty split before approval.",
) -> Dict[str, Any]:
    return get_success_data(
        api.return_hedge_program(
            program_id,
            f.return_program_payload(return_note),
            headers=make_treasury_headers(user_id),
        )
    )


def do_activate_program(
    api: ApiClient, program_id: str, user_id: str = TRM_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.activate_hedge_program(program_id, headers=make_treasury_headers(user_id))
    )


def do_close_program(api: ApiClient, program_id: str) -> Dict[str, Any]:
    return get_success_data(api.close_hedge_program(program_id, headers=TREASURY))


# ─── Instruments ──────────────────────────────────────

def do_propose_swap(
    api: ApiClient, program_id: str, counterparty_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Re-reads the programme first, because the pin must carry a live version."""
    version = read_program(api, program_id)["version"]
    return get_success_data(
        api.create_hedge_instrument(
            program_id,
            f.swap_payload(counterparty_id, version, **overrides),
            headers=ANALYST,
        )
    )


def do_propose_collar(
    api: ApiClient, program_id: str, counterparty_id: str, **overrides: Any
) -> Dict[str, Any]:
    version = read_program(api, program_id)["version"]
    return get_success_data(
        api.create_hedge_instrument(
            program_id,
            f.collar_payload(counterparty_id, version, **overrides),
            headers=ANALYST,
        )
    )


def do_propose_call_option(
    api: ApiClient, program_id: str, counterparty_id: str, **overrides: Any
) -> Dict[str, Any]:
    version = read_program(api, program_id)["version"]
    return get_success_data(
        api.create_hedge_instrument(
            program_id,
            f.call_option_payload(counterparty_id, version, **overrides),
            headers=ANALYST,
        )
    )


def do_execute_instrument(api: ApiClient, instrument_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.execute_hedge_instrument(instrument_id, headers=TREASURY)
    )


def do_designate_instrument(api: ApiClient, instrument_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.designate_hedge_instrument(instrument_id, headers=ACCOUNTANT)
    )


def do_terminate_instrument(
    api: ApiClient,
    instrument_id: str,
    termination_reason: str = "Unwound at the desk's request.",
) -> Dict[str, Any]:
    return get_success_data(
        api.terminate_hedge_instrument(
            instrument_id, f.terminate_payload(termination_reason), headers=TREASURY
        )
    )


def do_file_effectiveness_test(
    api: ApiClient,
    instrument_id: str,
    period_month: str,
    hedge_change_usd: float,
    hedged_item_change_usd: float,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_effectiveness_test(
            instrument_id,
            f.effectiveness_test_payload(
                period_month, hedge_change_usd, hedged_item_change_usd
            ),
            headers=ACCOUNTANT,
        )
    )


# ─── Collateral ───────────────────────────────────────

def do_create_posting(
    api: ApiClient,
    counterparty_id: str,
    instrument_id: str,
    collateral_type: str = "CASH",
) -> Dict[str, Any]:
    """Re-reads the counterparty first so the version pin is live."""
    version = read_counterparty(api, counterparty_id)["version"]
    return get_success_data(
        api.create_collateral_posting(
            counterparty_id,
            f.collateral_posting_payload(instrument_id, version, collateral_type),
            headers=ADMIN,
        )
    )


def do_post_collateral(
    api: ApiClient, posting_id: str, amount_usd: float
) -> Dict[str, Any]:
    return get_success_data(
        api.post_collateral(posting_id, f.post_collateral_payload(amount_usd), headers=ADMIN)
    )


def do_return_collateral(
    api: ApiClient,
    posting_id: str,
    return_reason: str = "Trade closed out; collateral surplus to requirement.",
) -> Dict[str, Any]:
    return get_success_data(
        api.return_collateral(
            posting_id, f.return_collateral_payload(return_reason), headers=ADMIN
        )
    )


# ─── Mark-to-market runs ──────────────────────────────

def do_open_mtm_run(
    api: ApiClient,
    period_month: str = "2027-02",
    settlement_index_usd_per_gal: float = 2.5000,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_mtm_run(
            f.mtm_run_payload(period_month, settlement_index_usd_per_gal),
            headers=ACCOUNTANT,
        )
    )


def do_compute_mtm_run(api: ApiClient, run_id: str) -> Dict[str, Any]:
    return get_success_data(api.compute_mtm_run(run_id, headers=ACCOUNTANT))


def do_publish_mtm_run(api: ApiClient, run_id: str) -> Dict[str, Any]:
    return get_success_data(api.publish_mtm_run(run_id, headers=ADMIN))


def do_run_published_mtm(
    api: ApiClient,
    period_month: str = "2027-02",
    settlement_index_usd_per_gal: float = 2.5000,
) -> Dict[str, Any]:
    run = do_open_mtm_run(api, period_month, settlement_index_usd_per_gal)
    do_compute_mtm_run(api, run["id"])
    return do_publish_mtm_run(api, run["id"])


# ─── Tankering ────────────────────────────────────────

def do_create_leg(
    api: ApiClient, origin_station_id: str, destination_station_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_flight_leg(
            f.flight_leg_payload(origin_station_id, destination_station_id, **overrides),
            headers=OPS,
        )
    )


def do_propose_directive(
    api: ApiClient, leg_id: str, requested_uplift_gallons: float
) -> Dict[str, Any]:
    """Re-reads the leg first so the version pin is live."""
    version = read_flight_leg(api, leg_id)["version"]
    return get_success_data(
        api.create_tankering_directive(
            leg_id,
            f.tankering_directive_payload(requested_uplift_gallons, version),
            headers=ANALYST,
        )
    )


def do_approve_directive(api: ApiClient, directive_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.approve_tankering_directive(directive_id, headers=OPS)
    )


def do_request_directive_revision(
    api: ApiClient,
    directive_id: str,
    revision_note: str = "Trim the uplift and re-price against today's contracts.",
) -> Dict[str, Any]:
    return get_success_data(
        api.request_directive_revision(
            directive_id, f.request_revision_payload(revision_note), headers=OPS
        )
    )


def do_revise_directive(
    api: ApiClient, directive_id: str, requested_uplift_gallons: float
) -> Dict[str, Any]:
    return get_success_data(
        api.revise_tankering_directive(
            directive_id,
            f.revise_directive_payload(requested_uplift_gallons),
            headers=ANALYST,
        )
    )


def do_load_directive(api: ApiClient, directive_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.execute_tankering_directive(directive_id, headers=OPS)
    )


def do_reconcile_directive(
    api: ApiClient,
    directive_id: str,
    actual_uplift_gallons: float,
    actual_block_minutes: int,
) -> Dict[str, Any]:
    return get_success_data(
        api.reconcile_tankering_directive(
            directive_id,
            f.reconcile_directive_payload(actual_uplift_gallons, actual_block_minutes),
            headers=OPS,
        )
    )


# ─── Policy exceptions ────────────────────────────────

def do_request_exception(
    api: ApiClient,
    reason_code: str,
    justification: str = "Board-approved tolerance for this fiscal quarter only.",
    headers: Optional[Dict[str, str]] = None,
    **refs: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_policy_exception(
            f.policy_exception_payload(reason_code, justification, **refs),
            headers=headers or ANALYST,
        )
    )


def do_approve_exception(
    api: ApiClient, exception_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.approve_policy_exception(
            exception_id, f.decision_payload(), headers=headers or ADMIN
        )
    )


def do_deny_exception(
    api: ApiClient, exception_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.deny_policy_exception(
            exception_id, f.decision_payload(), headers=headers or ADMIN
        )
    )


def find_auto_raised_exception(api: ApiClient, instrument_id: str) -> Dict[str, Any]:
    """Locate the SYSTEM_BREACH row a cascade raised against one instrument."""
    rows = list_exceptions(
        api,
        hedge_instrument_id=instrument_id,
        reason_code="EARNINGS_VOLATILITY_BREACH",
    )
    assert rows, (
        f"expected an auto-raised earnings-volatility exception for instrument "
        f"{instrument_id}, found none"
    )
    return rows[0]


# ══════════════════════════════════════════════════════
# Composite scenario prefixes
# ══════════════════════════════════════════════════════

#: Season-weighted basis of the two-forecast scenario:
#: 4,000,000 x 1.10 + 6,000,000 x 1.10 = 11,000,000 gallons.
DUAL_FORECAST_BASIS_GALLONS = 11000000

#: Season-weighted basis of the single-forecast scenario:
#: 4,000,000 x 1.10 = 4,400,000 gallons.
SINGLE_FORECAST_BASIS_GALLONS = 4400000


def setup_sized_program(
    api: ApiClient,
    policy_overrides: Optional[Dict[str, Any]] = None,
    counterparty_overrides: Optional[Dict[str, Any]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Policy, dealer, two published SUMMER forecasts and a programme sized to
    11,000,000 gallons, left in `SIZING`.

    The forecasts are a 4,000,000-gallon NARROWBODY/DOMESTIC_SHORT and a
    6,000,000-gallon WIDEBODY/TRANSATLANTIC, both running 2027-01 up to (but
    not including) 2027-04; the programme's inclusive window is 2027-01
    through 2027-03 and its route groups cover both forecasts.
    """
    policy = do_create_policy(api, **(policy_overrides or {}))
    counterparty = do_create_counterparty(api, **(counterparty_overrides or {}))
    forecast_narrow = do_create_published_forecast(
        api,
        fleet_type="NARROWBODY",
        route_group="DOMESTIC_SHORT",
        season="SUMMER",
        period_start_month="2027-01",
        period_end_month="2027-04",
        forecast_gallons=4000000,
    )
    forecast_wide = do_create_published_forecast(
        api,
        fleet_type="WIDEBODY",
        route_group="TRANSATLANTIC",
        season="SUMMER",
        period_start_month="2027-01",
        period_end_month="2027-04",
        forecast_gallons=6000000,
    )
    program = do_create_program(api, policy["id"], **(program_overrides or {}))
    program = do_size_program(api, program["id"])
    return {
        "policy": policy,
        "counterparty": counterparty,
        "forecast_narrow": forecast_narrow,
        "forecast_wide": forecast_wide,
        "program": program,
    }


def setup_single_forecast_sized_program(
    api: ApiClient,
    policy_overrides: Optional[Dict[str, Any]] = None,
    counterparty_overrides: Optional[Dict[str, Any]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One published 4,000,000-gallon SUMMER forecast sized to 4,400,000 gallons."""
    policy = do_create_policy(api, **(policy_overrides or {}))
    counterparty = do_create_counterparty(api, **(counterparty_overrides or {}))
    forecast = do_create_published_forecast(
        api,
        fleet_type="NARROWBODY",
        route_group="DOMESTIC_SHORT",
        season="SUMMER",
        period_start_month="2027-01",
        period_end_month="2027-04",
        forecast_gallons=4000000,
    )
    program = do_create_program(api, policy["id"], **(program_overrides or {}))
    program = do_size_program(api, program["id"])
    return {
        "policy": policy,
        "counterparty": counterparty,
        "forecast": forecast,
        "program": program,
    }


def setup_active_program_with_proposed_swap(
    api: ApiClient,
    policy_overrides: Optional[Dict[str, Any]] = None,
    counterparty_overrides: Optional[Dict[str, Any]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
    swap_overrides: Optional[Dict[str, Any]] = None,
    single_forecast: bool = False,
) -> Dict[str, Any]:
    """A sized programme carried all the way to `ACTIVE` with one `PROPOSED` swap.

    Submission is recorded against the analyst and activation against the
    treasury manager, so segregation of duties clears.
    """
    builder = (
        setup_single_forecast_sized_program if single_forecast else setup_sized_program
    )
    ctx = builder(
        api,
        policy_overrides=policy_overrides,
        counterparty_overrides=counterparty_overrides,
        program_overrides=program_overrides,
    )
    instrument = do_propose_swap(
        api,
        ctx["program"]["id"],
        ctx["counterparty"]["id"],
        **(swap_overrides or {}),
    )
    do_submit_program(api, ctx["program"]["id"])
    program = do_activate_program(api, ctx["program"]["id"])
    ctx["instrument"] = instrument
    ctx["program"] = program
    return ctx


def setup_active_program_with_executed_swap(
    api: ApiClient,
    policy_overrides: Optional[Dict[str, Any]] = None,
    counterparty_overrides: Optional[Dict[str, Any]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
    swap_overrides: Optional[Dict[str, Any]] = None,
    single_forecast: bool = False,
) -> Dict[str, Any]:
    """As above, with the swap executed so margin and credit ledgers have moved."""
    ctx = setup_active_program_with_proposed_swap(
        api,
        policy_overrides=policy_overrides,
        counterparty_overrides=counterparty_overrides,
        program_overrides=program_overrides,
        swap_overrides=swap_overrides,
        single_forecast=single_forecast,
    )
    ctx["instrument"] = do_execute_instrument(api, ctx["instrument"]["id"])
    ctx["program"] = read_program(api, ctx["program"]["id"])
    ctx["counterparty"] = read_counterparty(api, ctx["counterparty"]["id"])
    return ctx


def setup_designated_swap_with_published_mtm(
    api: ApiClient,
    policy_overrides: Optional[Dict[str, Any]] = None,
    counterparty_overrides: Optional[Dict[str, Any]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
    swap_overrides: Optional[Dict[str, Any]] = None,
    period_month: str = "2027-02",
    settlement_index_usd_per_gal: float = 2.5000,
) -> Dict[str, Any]:
    """An executed, designated swap revalued by a published mark-to-market run,
    so the programme's designated bucket carries a live mark."""
    ctx = setup_active_program_with_executed_swap(
        api,
        policy_overrides=policy_overrides,
        counterparty_overrides=counterparty_overrides,
        program_overrides=program_overrides,
        swap_overrides=swap_overrides,
    )
    do_designate_instrument(api, ctx["instrument"]["id"])
    ctx["mtm_run"] = do_run_published_mtm(
        api, period_month, settlement_index_usd_per_gal
    )
    ctx["instrument"] = read_instrument(api, ctx["instrument"]["id"])
    ctx["program"] = read_program(api, ctx["program"]["id"])
    ctx["counterparty"] = read_counterparty(api, ctx["counterparty"]["id"])
    return ctx


def setup_priced_station_pair(
    api: ApiClient,
    policy_overrides: Optional[Dict[str, Any]] = None,
    origin_stock_gallons: float = 500000,
    clock: str = TANKERING_CLOCK,
) -> Dict[str, Any]:
    """A cheap origin and an expensive destination, each with one live contract.

    The origin's all-in price is 2.4700 (a 2.4000 index, a 0.0250 differential
    and a 0.0450 into-plane fee) and the destination's is 3.1000 (a 2.9000
    index, a 0.1200 differential and a 0.0800 fee), which is what makes a
    tankering uplift economic. The origin is stocked so its posture is not
    `SHORT`.
    """
    set_clock(api, clock)
    policy = do_create_policy(api, **(policy_overrides or {}))
    origin = get_success_data(
        api.create_station(f.origin_station_payload(), headers=ADMIN)
    )
    destination = get_success_data(
        api.create_station(f.destination_station_payload(), headers=ADMIN)
    )
    origin_contract = do_create_contract(api, origin["id"])
    destination_contract = get_success_data(
        api.create_supply_contract(
            destination["id"], f.destination_contract_payload(), headers=ADMIN
        )
    )
    if origin_stock_gallons:
        origin = do_adjust_inventory(api, origin["id"], origin_stock_gallons)
    return {
        "policy": policy,
        "origin": origin,
        "destination": destination,
        "origin_contract": origin_contract,
        "destination_contract": destination_contract,
    }


def setup_tankering_leg(
    api: ApiClient,
    policy_overrides: Optional[Dict[str, Any]] = None,
    leg_overrides: Optional[Dict[str, Any]] = None,
    origin_stock_gallons: float = 500000,
    clock: str = TANKERING_CLOCK,
) -> Dict[str, Any]:
    """The priced station pair plus a narrowbody leg whose uplift cap is
    10,600.00 gallons — tank capacity 26,000 less a 14,500 planned burn less
    the 900-gallon reserve."""
    ctx = setup_priced_station_pair(
        api,
        policy_overrides=policy_overrides,
        origin_stock_gallons=origin_stock_gallons,
        clock=clock,
    )
    ctx["leg"] = do_create_leg(
        api, ctx["origin"]["id"], ctx["destination"]["id"], **(leg_overrides or {})
    )
    return ctx


def setup_proposed_directive(
    api: ApiClient,
    requested_uplift_gallons: float = 3000,
    policy_overrides: Optional[Dict[str, Any]] = None,
    leg_overrides: Optional[Dict[str, Any]] = None,
    origin_stock_gallons: float = 500000,
    clock: str = TANKERING_CLOCK,
) -> Dict[str, Any]:
    """A live `PROPOSED` directive on the baseline leg.

    At 3,000 gallons the baseline numbers are a 368.9-gallon burn penalty,
    1,890.00 of gross saving, 911.18 of penalty cost and 978.82 net.
    """
    ctx = setup_tankering_leg(
        api,
        policy_overrides=policy_overrides,
        leg_overrides=leg_overrides,
        origin_stock_gallons=origin_stock_gallons,
        clock=clock,
    )
    ctx["directive"] = do_propose_directive(
        api, ctx["leg"]["id"], requested_uplift_gallons
    )
    return ctx


def setup_approved_directive(
    api: ApiClient,
    requested_uplift_gallons: float = 3000,
    policy_overrides: Optional[Dict[str, Any]] = None,
    leg_overrides: Optional[Dict[str, Any]] = None,
    origin_stock_gallons: float = 500000,
    clock: str = TANKERING_CLOCK,
) -> Dict[str, Any]:
    """A directive approved with prices pinned at 2.4700 and 3.1000."""
    ctx = setup_proposed_directive(
        api,
        requested_uplift_gallons=requested_uplift_gallons,
        policy_overrides=policy_overrides,
        leg_overrides=leg_overrides,
        origin_stock_gallons=origin_stock_gallons,
        clock=clock,
    )
    ctx["directive"] = do_approve_directive(api, ctx["directive"]["id"])
    return ctx


def setup_loaded_directive(
    api: ApiClient,
    requested_uplift_gallons: float = 3000,
    policy_overrides: Optional[Dict[str, Any]] = None,
    leg_overrides: Optional[Dict[str, Any]] = None,
    origin_stock_gallons: float = 500000,
    clock: str = TANKERING_CLOCK,
) -> Dict[str, Any]:
    """A directive loaded onto the aircraft, with the origin station debited."""
    ctx = setup_approved_directive(
        api,
        requested_uplift_gallons=requested_uplift_gallons,
        policy_overrides=policy_overrides,
        leg_overrides=leg_overrides,
        origin_stock_gallons=origin_stock_gallons,
        clock=clock,
    )
    ctx["directive"] = do_load_directive(api, ctx["directive"]["id"])
    ctx["origin"] = read_station(api, ctx["origin"]["id"])
    return ctx
