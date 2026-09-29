"""Cross-entity lookups, derived aggregates and cascade helpers."""

from decimal import Decimal

import calc
from calc import ZERO, dec, r2
from db import clock_date, db, now_iso, rows_in_order
from errors import fail
from middleware import new_row, touch
from validators import parse_date

SYSTEM_BREACH_JUSTIFICATION = (
    "Auto-raised: undesignated mark-to-market exceeds policy earnings volatility limit."
)


# ------------------------------------------------------------------- lookups

def active_policy():
    """PRD 2.9: the policy in force is the row whose status is ACTIVE."""
    candidates = [p for p in rows_in_order(db.policies) if p["status"] == "ACTIVE"]
    if not candidates:
        return None
    return candidates[-1]


def governing_policy(program):
    return db.policies.get(program["policy_id"])


def program_instruments(program_id):
    return [i for i in rows_in_order(db.instruments) if i["hedge_program_id"] == program_id]


def instrument_postings(instrument_id):
    return [p for p in rows_in_order(db.postings) if p["hedge_instrument_id"] == instrument_id]


def counterparty_postings(counterparty_id):
    return [p for p in rows_in_order(db.postings) if p["counterparty_id"] == counterparty_id]


def counterparty_instruments(counterparty_id):
    return [i for i in rows_in_order(db.instruments) if i["counterparty_id"] == counterparty_id]


def instrument_tests(instrument_id):
    return [t for t in rows_in_order(db.tests) if t["hedge_instrument_id"] == instrument_id]


def station_contracts(station_id):
    return [c for c in rows_in_order(db.contracts) if c["station_id"] == station_id]


def leg_directives(flight_leg_id):
    return [d for d in rows_in_order(db.directives) if d["flight_leg_id"] == flight_leg_id]


# --------------------------------------------------------- derived aggregates

def contract_status(contract):
    """Derived from the logical clock on every read and consultation."""
    today = clock_date()
    start = parse_date(contract["term_start_date"])
    end = parse_date(contract["term_end_date"])
    if today < start:
        return "SCHEDULED"
    if today <= end:
        return "ACTIVE"
    return "EXPIRED"


def contract_all_in_price(contract):
    station = db.stations.get(contract["station_id"])
    fee = station["into_plane_fee_usd_per_gal"] if station else ZERO
    return calc.r4(contract["index_price_usd_per_gal"]
                   + contract["differential_usd_per_gal"] + fee)


def single_active_contract(station_id):
    """Exactly one ACTIVE contract or nothing (scaffold validation priority 14)."""
    actives = [c for c in station_contracts(station_id) if contract_status(c) == "ACTIVE"]
    if len(actives) != 1:
        return None
    return actives[0]


def station_derived(station):
    policy = active_policy()
    min_days = policy["min_days_cover"] if policy else None
    return calc.station_supply(station, min_days)


def leg_uplift_cap(leg):
    policy = active_policy()
    max_uplift = policy["max_tankering_uplift_gallons"] if policy else None
    return calc.uplift_cap(leg, max_uplift)


def counterparty_ledgers(counterparty):
    utilized = ZERO
    for inst in counterparty_instruments(counterparty["id"]):
        if inst["trade_status"] == "EXECUTED":
            utilized += inst["margin_requirement_usd"]
    posted = ZERO
    open_calls = 0
    for posting in counterparty_postings(counterparty["id"]):
        if posting["status"] == "POSTED":
            posted += posting["posted_amount_usd"]
        elif posting["status"] == "REQUIRED":
            open_calls += 1
    utilized = r2(utilized)
    posted = r2(posted)
    pct = calc.utilization_pct(utilized, counterparty["credit_limit_usd"])
    return utilized, posted, open_calls, pct, calc.credit_posture(pct)


def instrument_collateral_posted(instrument):
    total = ZERO
    for posting in instrument_postings(instrument["id"]):
        if posting["status"] == "POSTED":
            total += posting["posted_amount_usd"]
    return r2(total)


def instrument_delta_adjusted(instrument):
    return r2(instrument["notional_gallons"] * calc.INSTRUMENT_DELTA[instrument["instrument_type"]])


def program_coverage(program):
    """calculations.hedge_coverage_ratio - three measures over one basis."""
    basis = program["consumption_basis_gallons"]
    hedged = ZERO
    delta_executed = ZERO
    planned_delta = ZERO
    open_count = 0
    for inst in program_instruments(program["id"]):
        delta_adj = inst["delta_adjusted_gallons"]
        if inst["trade_status"] == "EXECUTED":
            hedged += inst["notional_gallons"]
            delta_executed += delta_adj
        if inst["trade_status"] in ("PROPOSED", "EXECUTED"):
            planned_delta += delta_adj
            open_count += 1
    zero = r2(0)
    if basis == 0:
        cov_notional = zero
        cov_delta = zero
        planned_pct = zero
    else:
        cov_notional = r2(hedged / basis * Decimal(100))
        cov_delta = r2(delta_executed / basis * Decimal(100))
        planned_pct = r2(planned_delta / basis * Decimal(100))
    return {
        "hedged_gallons": r2(hedged),
        "delta_adjusted_gallons": r2(delta_executed),
        "coverage_pct_notional": cov_notional,
        "coverage_pct_delta": cov_delta,
        "planned_coverage_pct_delta": planned_pct,
        "open_instrument_count": open_count,
        "_delta_executed_raw": delta_executed,
    }


def open_exception_count(policy):
    total = 0
    for exc in db.exceptions.values():
        if exc["status"] != "REQUESTED":
            continue
        program_id = exc.get("hedge_program_id")
        if not program_id:
            continue
        program = db.programs.get(program_id)
        if program and program["policy_id"] == policy["id"]:
            total += 1
    return total


def has_approved_exception(reason_code, instrument_id=None, directive_id=None):
    for exc in db.exceptions.values():
        if exc["status"] != "APPROVED" or exc["reason_code"] != reason_code:
            continue
        if instrument_id is not None and exc.get("hedge_instrument_id") == instrument_id:
            return True
        if directive_id is not None and exc.get("tankering_directive_id") == directive_id:
            return True
    return False


# ------------------------------------------------------------------- cascades

def refresh_program_compliance(program):
    """Returns True when compliance_posture newly becomes BREACH."""
    policy = governing_policy(program)
    volatility = abs(program["undesignated_mtm_usd"])
    limit = policy["max_earnings_volatility_usd"] if policy else None
    posture = "BREACH" if (limit is not None and volatility > limit) else "COMPLIANT"
    was = program["compliance_posture"]
    program["compliance_posture"] = posture
    return posture == "BREACH" and was != "BREACH"


def raise_system_breach_exception(program, instrument_id=None):
    row = new_row()
    row.update({
        "reason_code": "EARNINGS_VOLATILITY_BREACH",
        "hedge_program_id": program["id"],
        "hedge_instrument_id": instrument_id,
        "tankering_directive_id": None,
        "justification": SYSTEM_BREACH_JUSTIFICATION,
        "requested_limit_value": None,
        "status": "REQUESTED",
        "origin": "SYSTEM_BREACH",
        "requested_by_user_id": None,
        "decided_by_user_id": None,
        "decided_at": None,
    })
    db.exceptions[row["id"]] = row
    policy = governing_policy(program)
    if policy is not None:
        touch(policy)
    return row


def reclassify_out_of_designated(program, instrument):
    """De-designation hop 2: move the trade's mark-to-market to the undesignated bucket."""
    value = instrument["mtm_value_usd"]
    program["designated_mtm_usd"] = r2(program["designated_mtm_usd"] - value)
    program["undesignated_mtm_usd"] = r2(program["undesignated_mtm_usd"] + value)


def reclassify_into_designated(program, instrument):
    value = instrument["mtm_value_usd"]
    program["undesignated_mtm_usd"] = r2(program["undesignated_mtm_usd"] - value)
    program["designated_mtm_usd"] = r2(program["designated_mtm_usd"] + value)


def de_designation_cascade(program, instrument):
    """Hops 2-4 of the effectiveness-test FAIL cascade."""
    reclassify_out_of_designated(program, instrument)
    became_breach = refresh_program_compliance(program)
    touch(program)
    if became_breach:
        raise_system_breach_exception(program, instrument["id"])


def return_posted_collateral(instrument, bump_versions=True):
    """POSTED -> RETURNED for every posting of this trade."""
    touched = []
    for posting in instrument_postings(instrument["id"]):
        if posting["status"] != "POSTED":
            continue
        posting["status"] = "RETURNED"
        posting["returned_at"] = now_iso()
        touch(posting)
        touched.append(posting)
    return touched


def settle_instrument(instrument, run):
    """System transition trade_status EXECUTED -> SETTLED at publication."""
    instrument["trade_status"] = "SETTLED"
    instrument["margin_requirement_usd"] = r2(0)
    touch(instrument)
    program = db.programs.get(instrument["hedge_program_id"])
    if program is not None:
        touch(program)
    counterparty = db.counterparties.get(instrument["counterparty_id"])
    if counterparty is not None:
        touch(counterparty)
    run["settled_instrument_count"] = run["settled_instrument_count"] + 1


def directive_contracts(leg):
    """Validation ladder step 14: exactly one ACTIVE contract at each station."""
    origin = single_active_contract(leg["origin_station_id"])
    destination = single_active_contract(leg["destination_station_id"])
    if origin is None or destination is None:
        fail("ERR_NO_ACTIVE_SUPPLY_CONTRACT",
             "Each of the two stations must have exactly one ACTIVE supply contract.")
    return origin, destination


def apply_planned_basis(directive, leg, origin_contract, destination_contract):
    """Planned-basis burn penalty and economics, priced from live contracts."""
    uplift = directive["requested_uplift_gallons"]
    penalty = calc.burn_penalty(leg, uplift, leg["planned_block_minutes"])
    price_origin = contract_all_in_price(origin_contract)
    price_destination = contract_all_in_price(destination_contract)
    gross, penalty_cost, net = calc.net_savings(uplift, penalty,
                                                price_origin, price_destination)
    directive["planned_burn_penalty_gallons"] = penalty
    directive["planned_gross_savings_usd"] = gross
    directive["planned_penalty_cost_usd"] = penalty_cost
    directive["planned_net_savings_usd"] = net


def compute_margin_for(instrument, counterparty):
    """Steps 1-5 of calculations.margin_requirement_usd."""
    utilized, _posted, _calls, _pct, _posture = counterparty_ledgers(counterparty)
    pre_addon = utilized - instrument["margin_requirement_usd"]
    return calc.margin_requirement(
        instrument["notional_gallons"],
        instrument["instrument_type"],
        instrument["mtm_value_usd"],
        pre_addon,
        counterparty["credit_limit_usd"],
    )
