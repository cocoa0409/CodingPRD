"""Payout awards: granting, settlement and the two valuations (PRD §3.5)."""

from flask import Blueprint, request

import calc
from db import apply_changes, insert, now, ordered, store, touch
from errors import ApiError
from middleware import (
    ROLE_CHAIR,
    ROLE_COMP_CONSULTANT,
    ROLE_COUNSEL,
    ROLE_OFFICER,
    authenticate,
)
from response import object_response
from routes.common import body_fk, fetch, paginated
from services import domain
from validation import Body

bp = Blueprint("awards", __name__)

AWARD_VEHICLES = {"ANNUAL_INCENTIVE", "LONG_TERM_PSU", "RSU"}
DISPOSITIONS = {"VEST", "FORFEIT"}


@bp.post("/exec-comp/pay-programs/<pid>/payout-awards")
def grant_award(pid):
    authenticate([ROLE_COMP_CONSULTANT])
    program = fetch("pay_programs", pid)
    body = Body()
    executive = body_fk(body, "executive_id", "executives")
    if executive is None:
        raise ApiError("ERR_INVALID_REQUEST", "executive_id is required")
    vehicle = body.enum("vehicle", AWARD_VEHICLES, required=True)
    units_granted = body.number("units_granted", minimum=0, places=2)
    grant_price_usd = body.number("grant_price_usd", gt=0, places=2)

    if executive["company_id"] != program["issuer_company_id"]:
        raise ApiError(
            "ERR_INVALID_REQUEST", "the officer is not employed by the program's issuer"
        )
    if vehicle == "ANNUAL_INCENTIVE":
        if units_granted is None:
            units_granted = calc.money(0)
        if units_granted != 0:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "units_granted must be exactly 0 for an ANNUAL_INCENTIVE award",
            )
    else:
        if units_granted is None or units_granted <= 0:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "units_granted must be strictly positive for an equity award",
            )

    issuer = store.companies[program["issuer_company_id"]]
    if grant_price_usd is None:
        grant_price_usd = calc.money(issuer["share_price_usd"])
    target_amount = (
        calc.sti_target_usd(executive["base_salary_usd"], executive["sti_target_pct"])
        if vehicle == "ANNUAL_INCENTIVE"
        else calc.money(0)
    )

    award = insert(
        store.payout_awards,
        {
            "pay_program_id": program["id"],
            "executive_id": executive["id"],
            "vehicle": vehicle,
            "units_granted": units_granted,
            "grant_price_usd": grant_price_usd,
            "target_amount_usd": target_amount,
            "certified_factor_pct": None,
            "earned_amount_usd": None,
            "settlement_date": None,
            "vest_price_usd": None,
            "realized_value_usd": calc.money(0),
            "realizable_value_usd": calc.money(0),
            "status": "GRANTED",
        },
    )
    metrics = domain.program_metrics(program["id"], vehicle)
    factor = calc.certified_vehicle_factor(metrics)
    award["certified_factor_pct"] = factor
    if factor is not None and vehicle == "ANNUAL_INCENTIVE":
        award["earned_amount_usd"] = calc.annual_incentive_earned(
            target_amount, factor, program["sti_max_multiple"]
        )
    realized, realizable = calc.award_values(award, issuer["share_price_usd"])
    award["realized_value_usd"] = realized
    award["realizable_value_usd"] = realizable

    before = domain.watched(program)
    domain.recompute_program_alignment(program)
    domain.stale_if_watched_changed(program, before)
    return object_response(award, 201)


def _officer_scope(role, user_id, rows):
    if role != ROLE_OFFICER:
        return rows
    return [r for r in rows if r["executive_id"] == user_id]


@bp.get("/exec-comp/payout-awards")
def list_awards():
    user_id, role = authenticate(
        [ROLE_COMP_CONSULTANT, ROLE_CHAIR, ROLE_COUNSEL, ROLE_OFFICER]
    )
    wanted_executive = request.args.get("executive_id")
    if role == ROLE_OFFICER and wanted_executive is not None and wanted_executive != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    rows = ordered(list(store.payout_awards.values()))
    rows = _officer_scope(role, user_id, rows)
    for field in ("pay_program_id", "executive_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return paginated(rows)


@bp.get("/exec-comp/payout-awards/<aid>")
def read_award(aid):
    user_id, role = authenticate(
        [ROLE_COMP_CONSULTANT, ROLE_CHAIR, ROLE_COUNSEL, ROLE_OFFICER]
    )
    award = fetch("payout_awards", aid)
    if role == ROLE_OFFICER and award["executive_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return object_response(award)


@bp.post("/exec-comp/payout-awards/<aid>/settlement")
def settle_award(aid):
    authenticate([ROLE_COMP_CONSULTANT])
    award = fetch("payout_awards", aid)
    body = Body()
    disposition = body.enum("disposition", DISPOSITIONS, required=True)
    settlement_date = body.instant("settlement_date", required=True)
    vest_price_usd = body.number("vest_price_usd", gt=0, places=2)

    if award["status"] != "GRANTED":
        raise ApiError("ERR_AWARD_NOT_GRANTED")

    program = store.pay_programs[award["pay_program_id"]]
    issuer = store.companies[program["issuer_company_id"]]

    if disposition == "VEST":
        if (
            award["vehicle"] in ("ANNUAL_INCENTIVE", "LONG_TERM_PSU")
            and award["certified_factor_pct"] is None
        ):
            raise ApiError("ERR_METRIC_NOT_CERTIFIED")
        apply_changes(
            award,
            {
                "status": "VESTED",
                "settlement_date": settlement_date,
                "vest_price_usd": vest_price_usd
                if vest_price_usd is not None
                else calc.money(issuer["share_price_usd"]),
            },
        )
        domain.recompute_award_values(award)
        touch(award)
        before = domain.watched(program)
        domain.recompute_program_alignment(program)
        domain.stale_if_watched_changed(program, before)
    else:
        apply_changes(
            award,
            {
                "status": "FORFEITED",
                "settlement_date": now(),
                "realized_value_usd": calc.money(0),
                "realizable_value_usd": calc.money(0),
            },
        )
        touch(award)
        before = domain.watched(program)
        domain.recompute_program_alignment(program, totals_only=True)
        domain.stale_if_watched_changed(program, before)
    return object_response(award)
