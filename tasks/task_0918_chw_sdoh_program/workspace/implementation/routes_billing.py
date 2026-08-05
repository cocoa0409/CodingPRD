"""Payer claims, grant awards and grant charge lines (PRD §3.8, §3.9)."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import store
import validate as v
from clockutil import clock, elapsed_days
from envelope import created, listing, ok
from errors import (
    ApiError, ERR_APPEAL_WINDOW_CLOSED, ERR_ENCOUNTER_NOT_ALLOWABLE,
    ERR_GRANT_BUDGET_EXCEEDED, ERR_GRANT_PERIOD_OVERLAP, ERR_INVALID_STATE,
    ERR_MINUTES_ALREADY_FUNDED, ERR_MINUTE_THRESHOLD_NOT_MET, ERR_PATIENT_NOT_FOUND,
    ERR_RESOURCE_NOT_FOUND, ERR_STALE_GRANT_VERSION,
)
from ladder import ALL_ROLES, BILLING, Endpoint, PROGRAM_ADMIN, run
from serial import dump, dump_all

bp = Blueprint("billing", __name__)

EP_CLAIM_CREATE = Endpoint("claim.create", [BILLING], gated=True)
EP_CLAIM_READ = Endpoint("claim.read", ALL_ROLES, path=[("claim_id", "claim")])
EP_CLAIM_LIST = Endpoint("claim.list", ALL_ROLES)
EP_CLAIM_ADJUDICATE = Endpoint("claim.adjudicate", [BILLING], path=[("claim_id", "claim")])
EP_CLAIM_APPEAL = Endpoint("claim.appeal", [BILLING], path=[("claim_id", "claim")])
EP_CLAIM_APPEAL_DECISION = Endpoint("claim.appeal_decision", [BILLING],
                                    path=[("claim_id", "claim")])
EP_AWARD_CREATE = Endpoint("award.create", [PROGRAM_ADMIN])
EP_AWARD_READ = Endpoint("award.read", ALL_ROLES, path=[("award_id", "award")])
EP_AWARD_CLOSE = Endpoint("award.close", [PROGRAM_ADMIN], path=[("award_id", "award")])
EP_LINE_CREATE = Endpoint("chargeline.create", [BILLING], gated=True)
EP_LINE_READ = Endpoint("chargeline.read", ALL_ROLES, path=[("line_id", "chargeline")])
EP_LINE_LIST = Endpoint("chargeline.list", ALL_ROLES)
EP_LINE_REVERSE = Endpoint("chargeline.reverse", [BILLING], path=[("line_id", "chargeline")])

BASES = ("PROVISIONAL", "FINAL")
ADJUDICATION_OUTCOMES = ("PAID", "DENIED")
APPEAL_DECISIONS = ("OVERTURNED", "UPHELD")
COST_CATEGORIES = ("DIRECT", "INDIRECT", "DOCUMENTATION")
BLOCKING_CLAIM_STATUSES = ("SUBMITTED", "PAID", "APPEALED", "OVERTURNED")


def _claim_input_set(patient_id, service_month, basis):
    allowed = ("DRAFT", "SUBMITTED") if basis == "PROVISIONAL" else ("SUBMITTED",)
    rows = []
    for encounter in store.all_rows("encounter"):
        if encounter.get("patient_id") != patient_id:
            continue
        if encounter.get("service_month") != service_month:
            continue
        if encounter.get("funding_source") != "UNFUNDED":
            continue
        if encounter.get("status") not in allowed:
            continue
        rows.append(encounter)
    return rows


# ------------------------------------------------------------- payer claims
@bp.post("/chw/payer-claims")
def create_claim():
    def payload(ctx):
        s = ctx.state
        s["patient_id"] = v.req_str(ctx.body, "patient_id")
        s["service_month"] = v.req_month(ctx.body, "service_month")
        s["basis"] = v.req_enum(ctx.body, "basis", BASES)

    def body_refs(ctx):
        patient = store.get("patient", ctx.state["patient_id"])
        if patient is None:
            raise ApiError(ERR_PATIENT_NOT_FOUND, "patient_id does not resolve")
        ctx.state["patient"] = patient

    def funding_exclusivity(ctx):
        s = ctx.state
        if s["basis"] != "FINAL":
            return
        for encounter in store.all_rows("encounter"):
            if encounter.get("patient_id") != s["patient"]["id"]:
                continue
            if encounter.get("service_month") != s["service_month"]:
                continue
            if encounter.get("funding_source") == "GRANT":
                raise ApiError(ERR_MINUTES_ALREADY_FUNDED,
                               "The month already carries grant-funded minutes")
        for claim in store.all_rows("claim"):
            if claim.get("patient_id") != s["patient"]["id"]:
                continue
            if claim.get("service_month") != s["service_month"]:
                continue
            if claim.get("basis") != "FINAL":
                continue
            if claim.get("status") in BLOCKING_CLAIM_STATUSES:
                raise ApiError(ERR_MINUTES_ALREADY_FUNDED,
                               "A prior FINAL claim already covers this month")

    def threshold(ctx):
        s = ctx.state
        encounters = _claim_input_set(s["patient"]["id"], s["service_month"], s["basis"])
        claimed_minutes, count = calc.monthly_rollup(encounters)
        if claimed_minutes < calc.CM_CODE_MINUTE_THRESHOLD:
            raise ApiError(ERR_MINUTE_THRESHOLD_NOT_MET,
                           "claimed_minutes is below the 60-minute threshold")
        s["encounters"] = encounters
        s["claimed_minutes"] = claimed_minutes
        s["claimed_encounter_count"] = count

    ctx = run(EP_CLAIM_CREATE, steps={
        5: [payload], 6: [body_refs], 15: [funding_exclusivity], 17: [threshold],
    })
    s = ctx.state
    units, allowed_amount = calc.claim_money(s["claimed_minutes"])
    row = store.insert("claim", {
        "patient_id": s["patient"]["id"],
        "service_month": s["service_month"],
        "basis": s["basis"],
        "claimed_minutes": s["claimed_minutes"],
        "claimed_encounter_count": s["claimed_encounter_count"],
        "billing_code": calc.billing_code_for(s["claimed_minutes"]),
        "units": units,
        "allowed_amount_cents": allowed_amount,
        "status": "SUBMITTED",
        "denial_reason": None,
        "denied_at": None,
        "appealed_at": None,
    })
    if s["basis"] == "FINAL":
        for encounter in s["encounters"]:
            encounter["status"] = "LOCKED"
            encounter["funding_source"] = "PAYER"
            encounter["funding_claim_id"] = row["id"]
            store.touch(encounter)
    return created(dump(row))


@bp.get("/chw/payer-claims/<claim_id>")
def read_claim(claim_id):
    ctx = run(EP_CLAIM_READ, {"claim_id": claim_id})
    return ok(dump(ctx.row("claim_id")))


@bp.get("/chw/payer-claims")
def list_claims():
    def pagination(ctx):
        ctx.state["page"] = v.pagination(ctx.args)

    ctx = run(EP_CLAIM_LIST, steps={5: [pagination]})
    limit, offset = ctx.state["page"]
    rows = store.all_rows("claim")
    for key in ("patient_id", "service_month", "status", "basis"):
        wanted = ctx.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r.get(key) == wanted]
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all(page), limit, offset, total)


@bp.post("/chw/payer-claims/<claim_id>/adjudicate")
def adjudicate_claim(claim_id):
    def payload(ctx):
        ctx.state["outcome"] = v.req_enum(ctx.body, "outcome", ADJUDICATION_OUTCOMES)
        ctx.state["denial_reason"] = v.opt_str(ctx.body, "denial_reason")

    def target_state(ctx):
        claim = ctx.row("claim_id")
        if claim["status"] != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE, "Only a SUBMITTED claim may be adjudicated")
        if claim["basis"] != "FINAL":
            raise ApiError(ERR_INVALID_STATE, "Only a FINAL claim may be adjudicated")

    ctx = run(EP_CLAIM_ADJUDICATE, {"claim_id": claim_id},
              steps={5: [payload], 8: [target_state]})
    claim = ctx.row("claim_id")
    if ctx.state["outcome"] == "PAID":
        claim["status"] = "PAID"
    else:
        claim["status"] = "DENIED"
        claim["denial_reason"] = ctx.state["denial_reason"]
        claim["denied_at"] = clock.now_raw()
    store.touch(claim)
    return ok(dump(claim))


@bp.post("/chw/payer-claims/<claim_id>/appeal")
def appeal_claim(claim_id):
    def target_state(ctx):
        claim = ctx.row("claim_id")
        if claim["status"] != "DENIED":
            raise ApiError(ERR_INVALID_STATE, "Only a DENIED claim may be appealed")
        if claim["basis"] != "FINAL":
            raise ApiError(ERR_INVALID_STATE, "Only a FINAL claim may be appealed")

    def window(ctx):
        claim = ctx.row("claim_id")
        elapsed = elapsed_days(claim.get("denied_at"), clock.now_raw())
        if elapsed is None or elapsed > Decimal(calc.CLAIM_APPEAL_WINDOW_DAYS):
            raise ApiError(ERR_APPEAL_WINDOW_CLOSED, "The 60-day appeal window is closed")

    ctx = run(EP_CLAIM_APPEAL, {"claim_id": claim_id},
              steps={8: [target_state], 14: [window]})
    claim = ctx.row("claim_id")
    claim["status"] = "APPEALED"
    claim["appealed_at"] = clock.now_raw()
    store.touch(claim)
    return ok(dump(claim))


@bp.post("/chw/payer-claims/<claim_id>/appeal-decision")
def appeal_decision(claim_id):
    def payload(ctx):
        ctx.state["decision"] = v.req_enum(ctx.body, "decision", APPEAL_DECISIONS)

    def target_state(ctx):
        claim = ctx.row("claim_id")
        if claim["status"] != "APPEALED":
            raise ApiError(ERR_INVALID_STATE, "Only an APPEALED claim may be decided")
        if claim["basis"] != "FINAL":
            raise ApiError(ERR_INVALID_STATE, "Only a FINAL claim may be decided")

    ctx = run(EP_CLAIM_APPEAL_DECISION, {"claim_id": claim_id},
              steps={5: [payload], 8: [target_state]})
    claim = ctx.row("claim_id")
    if ctx.state["decision"] == "OVERTURNED":
        claim["status"] = "OVERTURNED"
        store.touch(claim)
    else:
        claim["status"] = "UPHELD"
        store.touch(claim)
        for encounter in store.all_rows("encounter"):
            if encounter.get("funding_claim_id") == claim["id"] and encounter.get("status") == "LOCKED":
                cascades.unlock_encounter(encounter)
    return ok(dump(claim))


# ------------------------------------------------------------- grant awards
@bp.post("/chw/grant-awards")
def create_award():
    def payload(ctx):
        s = ctx.state
        s["funder_name"] = v.req_str(ctx.body, "funder_name")
        s["period_start"] = v.req_date(ctx.body, "period_start")
        s["period_end"] = v.req_date(ctx.body, "period_end")
        if s["period_end"] < s["period_start"]:
            v.bad("period_end must be on or after period_start")
        s["budget_cap_cents"] = v.req_int(ctx.body, "budget_cap_cents", minimum=1)
        s["indirect_rate_pct"] = v.opt_num(ctx.body, "indirect_rate_pct",
                                           calc.DEFAULT_GRANT_INDIRECT_RATE_PCT,
                                           minimum=0, maximum=100)
        categories = v.opt_list(ctx.body, "allowable_cost_categories", list(COST_CATEGORIES))
        if not categories:
            v.bad("allowable_cost_categories must be a non-empty subset")
        for item in categories:
            if not isinstance(item, str):
                v.bad("allowable_cost_categories entries must be strings")
            v.enum_value("allowable_cost_categories", item, COST_CATEGORIES)
        s["allowable_cost_categories"] = categories

    def overlap(ctx):
        s = ctx.state
        for award in store.all_rows("award"):
            if award.get("funder_name") != s["funder_name"]:
                continue
            if award.get("status") != "OPEN":
                continue
            if s["period_start"] <= award["period_end"] and award["period_start"] <= s["period_end"]:
                raise ApiError(ERR_GRANT_PERIOD_OVERLAP,
                               "The award period collides with an existing OPEN award")

    ctx = run(EP_AWARD_CREATE, steps={5: [payload], 13: [overlap]})
    s = ctx.state
    row = store.insert("award", {
        "funder_name": s["funder_name"],
        "period_start": s["period_start"],
        "period_end": s["period_end"],
        "budget_cap_cents": s["budget_cap_cents"],
        "indirect_rate_pct": s["indirect_rate_pct"],
        "allowable_cost_categories": s["allowable_cost_categories"],
        "committed_cents": 0,
        "remaining_budget_cents": s["budget_cap_cents"],
        "status": "OPEN",
    })
    return created(dump(row))


@bp.get("/chw/grant-awards/<award_id>")
def read_award(award_id):
    ctx = run(EP_AWARD_READ, {"award_id": award_id})
    return ok(dump(ctx.row("award_id")))


@bp.post("/chw/grant-awards/<award_id>/close")
def close_award(award_id):
    def target_state(ctx):
        if ctx.row("award_id")["status"] != "OPEN":
            raise ApiError(ERR_INVALID_STATE, "Only an OPEN award may be closed")

    ctx = run(EP_AWARD_CLOSE, {"award_id": award_id}, steps={8: [target_state]})
    award = ctx.row("award_id")
    award["status"] = "CLOSED"
    store.touch(award)
    return ok(dump(award))


# -------------------------------------------------------- grant charge lines
@bp.post("/chw/grant-charge-lines")
def create_charge_line():
    def payload(ctx):
        s = ctx.state
        s["grant_award_id"] = v.req_str(ctx.body, "grant_award_id")
        s["encounter_id"] = v.req_str(ctx.body, "encounter_id")
        s["expected_grant_award_version"] = v.req_int(ctx.body, "expected_grant_award_version")

    def body_refs(ctx):
        s = ctx.state
        award = store.get("award", s["grant_award_id"])
        if award is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND, "grant_award_id does not resolve")
        encounter = store.get("encounter", s["encounter_id"])
        if encounter is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND, "encounter_id does not resolve")
        s["award"] = award
        s["encounter"] = encounter

    def occ(ctx):
        if ctx.state["expected_grant_award_version"] != ctx.state["award"]["version"]:
            raise ApiError(ERR_STALE_GRANT_VERSION, "expected_grant_award_version is stale")

    def target_state(ctx):
        if ctx.state["encounter"]["status"] in ("DRAFT", "VOIDED"):
            raise ApiError(ERR_INVALID_STATE, "Only a SUBMITTED encounter may be charged")

    def cross_entity(ctx):
        if ctx.state["award"]["status"] != "OPEN":
            raise ApiError(ERR_INVALID_STATE, "A CLOSED award accepts no charge lines")

    def funding(ctx):
        s = ctx.state
        if s["encounter"]["funding_source"] != "UNFUNDED":
            raise ApiError(ERR_MINUTES_ALREADY_FUNDED,
                           "The encounter's minutes are already funded")
        award = s["award"]
        encounter = s["encounter"]
        date = encounter["encounter_date"]
        if date < award["period_start"] or date > award["period_end"]:
            raise ApiError(ERR_ENCOUNTER_NOT_ALLOWABLE,
                           "encounter_date lies outside the award's period")
        category_minutes = {
            "DIRECT": encounter["direct_minutes"],
            "INDIRECT": encounter["indirect_minutes"],
            "DOCUMENTATION": encounter["documentation_minutes"],
        }
        allowable = award["allowable_cost_categories"]
        if not any(category_minutes.get(name, 0) > 0 for name in allowable):
            raise ApiError(ERR_ENCOUNTER_NOT_ALLOWABLE,
                           "The encounter carries no minutes in an allowable category")

    def fiscal(ctx):
        s = ctx.state
        award = s["award"]
        charged_minutes = s["encounter"]["billable_minutes"]
        rate, direct, indirect, total = calc.grant_line_amounts(
            charged_minutes, award["committed_cents"], award["indirect_rate_pct"])
        if award["committed_cents"] + total > award["budget_cap_cents"]:
            raise ApiError(ERR_GRANT_BUDGET_EXCEEDED, "The line would breach the budget cap")
        s["amounts"] = (charged_minutes, rate, direct, indirect, total)

    ctx = run(EP_LINE_CREATE, steps={
        5: [payload], 6: [body_refs], 7: [occ], 8: [target_state], 9: [cross_entity],
        15: [funding], 17: [fiscal],
    })
    s = ctx.state
    award = s["award"]
    encounter = s["encounter"]
    charged_minutes, rate, direct, indirect, total = s["amounts"]
    row = store.insert("chargeline", {
        "grant_award_id": award["id"],
        "encounter_id": encounter["id"],
        "charged_minutes": charged_minutes,
        "hourly_rate_cents": rate,
        "direct_amount_cents": direct,
        "indirect_amount_cents": indirect,
        "total_amount_cents": total,
        "reversed_at": None,
        "reversal_reason": None,
        "status": "POSTED",
    })
    award["committed_cents"] += total
    award["remaining_budget_cents"] = award["budget_cap_cents"] - award["committed_cents"]
    store.touch(award)
    encounter["status"] = "LOCKED"
    encounter["funding_source"] = "GRANT"
    store.touch(encounter)
    return created(dump(row))


@bp.get("/chw/grant-charge-lines/<line_id>")
def read_charge_line(line_id):
    ctx = run(EP_LINE_READ, {"line_id": line_id})
    return ok(dump(ctx.row("line_id")))


@bp.get("/chw/grant-charge-lines")
def list_charge_lines():
    def pagination(ctx):
        ctx.state["page"] = v.pagination(ctx.args)

    ctx = run(EP_LINE_LIST, steps={5: [pagination]})
    limit, offset = ctx.state["page"]
    rows = store.all_rows("chargeline")
    for key in ("grant_award_id", "encounter_id", "status"):
        wanted = ctx.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r.get(key) == wanted]
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all(page), limit, offset, total)


@bp.post("/chw/grant-charge-lines/<line_id>/reverse")
def reverse_charge_line(line_id):
    def payload(ctx):
        ctx.state["reversal_reason"] = v.opt_str(ctx.body, "reversal_reason", "MANUAL_REVERSAL")

    def target_state(ctx):
        if ctx.row("line_id")["status"] != "POSTED":
            raise ApiError(ERR_INVALID_STATE, "Only a POSTED line may be reversed")

    ctx = run(EP_LINE_REVERSE, {"line_id": line_id}, steps={5: [payload], 8: [target_state]})
    line = ctx.row("line_id")
    cascades.reverse_charge_line(line, ctx.state["reversal_reason"])
    encounter = store.get("encounter", line.get("encounter_id"))
    if encounter is not None and encounter.get("status") == "LOCKED":
        cascades.unlock_encounter(encounter)
    return ok(dump(line))
