"""Budget cycles: opening, phase advancement, balance certification and close."""

from flask import Blueprint

import auth
import db
import response
from errors import fail
from services import calc
from services import constants as C
from services import core
from validators import body_json, listing, read_enum, read_int, read_iso_date, read_number

bp = Blueprint("budget_cycles", __name__)


@bp.post("/fiscal/budget-cycles")
def open_cycle():
    auth.authenticate((auth.SYSTEM_ADMIN,))
    body = body_json()
    fiscal_year = read_int(body, "fiscal_year")
    if fiscal_year < 2000 or fiscal_year > 2100:
        fail("ERR_INVALID_REQUEST", "fiscal_year must be between 2000 and 2100.")
    read_iso_date(body, "fiscal_year_start_date")
    start_date = body["fiscal_year_start_date"]
    reserve_balance_cents = read_int(body, "reserve_balance_cents")
    if reserve_balance_cents < 0:
        fail("ERR_INVALID_REQUEST", "reserve_balance_cents must be zero or positive.")
    reserve_pct = read_number(body, "constitutional_reserve_pct", required=False, default=0.05)
    if reserve_pct < 0 or reserve_pct > 0.5:
        fail("ERR_INVALID_REQUEST", "constitutional_reserve_pct must be between 0 and 0.5.")

    for existing in db.budget_cycles.values():
        if existing["fiscal_year"] == fiscal_year:
            fail("ERR_DUPLICATE_CODE", "fiscal_year %s is already open." % fiscal_year)

    row = db.new_row()
    row.update(
        {
            "fiscal_year": fiscal_year,
            "fiscal_year_start_date": start_date,
            "phase": "DEVELOPMENT",
            "constitutional_reserve_pct": reserve_pct,
            "reserve_balance_cents": reserve_balance_cents,
            "adopted_general_fund_revenue_cents": 0,
            "total_recommended_cents": 0,
            "required_reserve_cents": 0,
            "balance_certified": False,
            "emergency_granted_cents": 0,
            "total_released_cents": 0,
            "total_expended_cents": 0,
            "total_reverted_cents": 0,
            "total_carryforward_cents": 0,
            "projected_cumulative_cash_cents": 0,
            "cash_utilization_pct": 0,
            "cash_posture": "NORMAL",
        }
    )
    db.budget_cycles[row["id"]] = row
    return response.created(db.serialize(row))


@bp.get("/fiscal/budget-cycles/<cycle_id>")
def read_cycle(cycle_id):
    auth.authenticate(auth.ANY_ROLE)
    cycle = core.get_cycle(cycle_id)
    return response.ok(db.serialize(cycle))


@bp.post("/fiscal/budget-cycles/<cycle_id>/advance-phase")
def advance_phase(cycle_id):
    auth.authenticate((auth.BUDGET_DIRECTOR,))
    cycle = core.get_cycle(cycle_id)
    body = body_json()
    to_phase = read_enum(body, "to_phase", C.PHASES)

    index = C.PHASES.index(cycle["phase"])
    successor = C.PHASES[index + 1] if index + 1 < len(C.PHASES) else None
    if successor is None or successor == "CLOSED" or to_phase != successor:
        fail(
            "ERR_CYCLE_PHASE_INVALID",
            "Only %s may follow %s." % (successor or "no phase", cycle["phase"]),
        )

    if to_phase == "ENACTED":
        for appropriation in core.appropriations_of(cycle):
            if appropriation["authority_status"] not in ("ENACTED", "LAPSED"):
                fail(
                    "ERR_INVALID_STATE",
                    "Appropriation %s is still %s."
                    % (appropriation["id"], appropriation["authority_status"]),
                )
    if to_phase == "EXECUTIVE_PREP" and not core.has_any_adopted_forecast(cycle):
        fail("ERR_NO_ADOPTED_FORECAST", "The cycle has no ADOPTED revenue forecast.")
    if to_phase == "LEGISLATIVE" and not cycle["balance_certified"]:
        fail("ERR_BUDGET_NOT_BALANCED", "The cycle balance has not been certified.")

    core.sync(cycle, cycle_extra={"phase": to_phase}, force_cycle=True)
    return response.ok(db.serialize(cycle))


@bp.post("/fiscal/budget-cycles/<cycle_id>/certify-balance")
def certify_balance(cycle_id):
    auth.authenticate((auth.BUDGET_DIRECTOR,))
    cycle = core.get_cycle(cycle_id)
    core.require_phase(cycle, ("EXECUTIVE_PREP",))

    result = calc.balance_certification(cycle)
    if result["adopted_general_fund_revenue_cents"] <= 0:
        fail("ERR_NO_ADOPTED_FORECAST", "The cycle has no ADOPTED GENERAL revenue forecast.")
    if not result["balanced"]:
        fail(
            "ERR_BUDGET_NOT_BALANCED",
            "Approved recommendations of %d exceed the appropriable %d."
            % (result["total_recommended_cents"], result["appropriable_cents"]),
        )

    core.sync(cycle, cycle_extra={"balance_certified": True}, force_cycle=True)
    return response.ok(db.serialize(cycle))


@bp.post("/fiscal/budget-cycles/<cycle_id>/close")
def close_cycle(cycle_id):
    auth.authenticate((auth.STATE_CONTROLLER,))
    cycle = core.get_cycle(cycle_id)
    core.require_phase(cycle, ("EXECUTION",))
    if not core.cycle_has_ended(cycle):
        fail(
            "ERR_CYCLE_NOT_ENDED",
            "The logical clock has not reached twelve months after the fiscal year start.",
        )

    appr_extra = {}
    swept = []
    for appropriation in core.appropriations_of(cycle):
        if appropriation["authority_status"] not in ("ENACTED", "LAPSED"):
            continue
        carryforward, reverted = calc.carryforward_split(appropriation)
        appr_extra[appropriation["id"]] = {
            "carryforward_cents": carryforward,
            "reverted_cents": reverted,
            "authority_status": "CLOSED",
        }
        swept.append(appropriation["id"])

    core.sync(
        cycle,
        appr_extra=appr_extra,
        cycle_extra={"phase": "CLOSED"},
        force_cycle=True,
    )

    touched_grants = set()
    for appropriation_id in swept:
        for commitment in core.commitments_of_appropriation(appropriation_id):
            if commitment["status"] in ("COMMITTED", "AT_RISK"):
                db.apply_changes(commitment, {"status": "RELEASED_FROM_COMMITMENT"})
                touched_grants.add(commitment["federal_grant_id"])
    core.recompute_grants_and_agencies(touched_grants)

    return response.ok(db.serialize(cycle))


@bp.get("/fiscal/budget-cycles/<cycle_id>/reduction-scenarios")
def list_cycle_scenarios(cycle_id):
    auth.authenticate(auth.ANY_ROLE)
    cycle = core.get_cycle(cycle_id)
    rows = [
        s for s in db.reduction_scenarios.values() if s["budget_cycle_id"] == cycle["id"]
    ]
    data, meta = listing(rows)
    return response.ok_list(data, meta)
