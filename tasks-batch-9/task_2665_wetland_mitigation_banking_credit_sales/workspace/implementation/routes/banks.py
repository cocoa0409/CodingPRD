"""Bank site registration, lifecycle writes and the bank-scoped projections."""
from decimal import Decimal

import auth
import calc
import ledger
import lookup
import serialize
import store
from errors import ApiError
from flask import Blueprint
from response import list_response, object_response
from util import fmt_ts, now, num
from validation import (HUC8_RE, bad_request, json_body, filter_enum, filter_string,
                        pagination, paginate, v_enum, v_huc8, v_int, v_string)

bp = Blueprint("banks", __name__)

BANK_STATUSES = ("DRAFT", "PROSPECTUS_REVIEW", "INSTRUMENT_EXECUTED", "MONITORING",
                 "SUSPENDED", "CLOSED")
POSTURES = ("OPEN", "RESTRICTED", "SOLD_OUT", "FROZEN")
ENTRY_TYPES = ("GENERATED", "RELEASED", "HOLD_PLACED", "HOLD_RELEASED", "SOLD",
               "SALE_REVERSED", "ASSIGNED")


def bank_state_invalid(message="The mitigation bank is not in a state that admits this operation."):
    return ApiError("ERR_BANK_STATE_INVALID", message)


def require_open_bank(bank):
    """A CLOSED bank is terminal and accepts no further writes of any kind."""
    if bank["status"] == "CLOSED":
        raise bank_state_invalid("A closed mitigation bank accepts no further writes.")


# ------------------------------------------------------------------- creation
@bp.post("/mitigation/banks")
def create_bank():
    actor = auth.authenticate("Sponsor")
    body = json_body()
    sponsor_id = v_string(body, "sponsor_id")
    site_name = v_string(body, "site_name", max_len=160)
    site_huc8 = v_huc8(body, "site_huc8_code")
    codes = body.get("service_area_huc8_codes")
    if not isinstance(codes, list) or not 1 <= len(codes) <= 8:
        raise bad_request("service_area_huc8_codes must be an array of 1 through 8 HUC-8 codes.")
    for code in codes:
        if not isinstance(code, str) or not HUC8_RE.match(code):
            raise bad_request("Every service_area_huc8_codes entry must be eight decimal digits.")
    if len(set(codes)) != len(codes):
        raise bad_request("service_area_huc8_codes may not repeat a watershed code.")
    hgm_class = v_enum(body, "hgm_class", calc.HGM_CLASSES)
    annual = v_int(body, "annual_stewardship_cost_cents", minimum=1)

    sponsor = lookup.sponsor(sponsor_id)
    if actor.user_id != sponsor["id"]:
        raise ApiError("ERR_NOT_BANK_SPONSOR",
                       "A sponsor may only register a bank site under its own identity.")
    if site_huc8 not in codes:
        raise ApiError("ERR_SERVICE_AREA_MISSING_SITE_HUC",
                       "The service area must contain the site's own watershed code.")
    row = store.new_row({
        "sponsor_id": sponsor["id"],
        "site_name": site_name,
        "site_huc8_code": site_huc8,
        "service_area_huc8_codes": list(codes),
        "hgm_class": hgm_class,
        "annual_stewardship_cost_cents": annual,
        "status": "DRAFT",
        "total_authorized_credits": Decimal("0.00"),
        "stewardship_required_cents": calc.stewardship_endowment_requirement(annual),
        "stewardship_funded_cents": 0,
        "easement_recorded": False,
        "easement_recorded_at": None,
        "easement_deed_reference": None,
        "deferral_count": 0,
        "instrument_executed_at": None,
        "closed_at": None,
    })
    store.banks[row["id"]] = row
    return object_response(serialize.bank(row), 201)


# ------------------------------------------------------------ lifecycle writes
@bp.post("/mitigation/banks/<row_id>/execute-instrument")
def execute_instrument(row_id):
    auth.authenticate("IRTChair")
    bank = lookup.bank(row_id)
    if bank["status"] != "PROSPECTUS_REVIEW":
        raise bank_state_invalid("Instrument execution is admissible only from PROSPECTUS_REVIEW.")
    approved_prospectus = [p for p in store.prospectuses.values()
                           if p["bank_id"] == bank["id"] and p["status"] == "APPROVED"]
    if not approved_prospectus:
        raise ApiError("ERR_PROSPECTUS_NOT_APPROVED",
                       "The bank has no prospectus in APPROVED status.")
    approved_plans = [w for w in store.work_plans.values()
                      if w["bank_id"] == bank["id"] and w["status"] == "APPROVED"]
    if not approved_plans:
        raise ApiError("ERR_WORK_PLAN_MISSING", "The bank has no work plan in APPROVED status.")
    sponsor = store.sponsors.get(bank["sponsor_id"])
    bond = sponsor["performance_bond_cents"] if sponsor else 0
    if bond < calc.MIN_PERFORMANCE_BOND_CENTS:
        raise ApiError("ERR_PERFORMANCE_BOND_INSUFFICIENT",
                       "The sponsor's posted performance assurance is below the minimum.")

    plan = store.ordered(approved_plans)[0]
    bank["status"] = "INSTRUMENT_EXECUTED"
    bank["total_authorized_credits"] = plan["total_planned_credits"]
    bank["stewardship_required_cents"] = calc.stewardship_endowment_requirement(
        bank["annual_stewardship_cost_cents"])
    bank["instrument_executed_at"] = now()
    ledger.append_entry(bank["id"], "GENERATED", Decimal("0.00"), "MITIGATION_BANK", bank["id"],
                        "INSTRUMENT EXECUTED authorized=%s" % bank["total_authorized_credits"])
    store.touch(bank)
    return object_response(serialize.bank(bank))


@bp.post("/mitigation/banks/<row_id>/conservation-easement")
def record_easement(row_id):
    actor = auth.authenticate("Sponsor")
    body = json_body()
    deed_reference = v_string(body, "deed_reference", max_len=200)
    bank = lookup.bank(row_id)
    auth.require_bank_sponsor(actor, bank)
    require_open_bank(bank)
    bank["easement_recorded"] = True
    bank["easement_recorded_at"] = now()
    bank["easement_deed_reference"] = deed_reference
    store.touch(bank)
    return object_response(serialize.bank(bank))


@bp.post("/mitigation/banks/<row_id>/stewardship-contributions")
def contribute_stewardship(row_id):
    actor = auth.authenticate("Sponsor")
    body = json_body()
    amount = v_int(body, "amount_cents", minimum=0)
    bank = lookup.bank(row_id)
    auth.require_bank_sponsor(actor, bank)
    require_open_bank(bank)
    bank["stewardship_funded_cents"] += amount
    store.touch(bank)
    return object_response(serialize.bank(bank))


@bp.post("/mitigation/banks/<row_id>/close")
def close_bank(row_id):
    auth.authenticate("IRTChair")
    bank = lookup.bank(row_id)
    if bank["status"] != "MONITORING":
        raise bank_state_invalid("Closure is admissible only from MONITORING.")
    if not bank["easement_recorded"]:
        raise ApiError("ERR_EASEMENT_NOT_RECORDED",
                       "The conservation easement has not been recorded for this site.")
    milestones = ledger.bank_milestones(bank["id"])
    if any(m["status"] != "APPROVED" for m in milestones):
        raise ApiError("ERR_MILESTONES_INCOMPLETE",
                       "Every release milestone of the bank must stand in APPROVED.")
    for action in ledger.bank_remedial_actions(bank["id"]):
        if action["status"] in ledger.NON_TERMINAL_REMEDIAL:
            raise ApiError("ERR_MILESTONES_INCOMPLETE",
                           "A remedial action of the bank is still standing.")
    if bank["stewardship_funded_cents"] < bank["stewardship_required_cents"]:
        raise ApiError("ERR_STEWARDSHIP_UNDERFUNDED",
                       "The stewardship endowment is not funded in full.")
    bank["status"] = "CLOSED"
    bank["closed_at"] = now()
    ledger.cancel_open_sales(bank, "SPONSOR_WITHDREW")
    store.touch(bank)
    return object_response(serialize.bank(bank))


# -------------------------------------------------------------------- reads
@bp.get("/mitigation/banks/<row_id>")
def read_bank(row_id):
    auth.authenticate("ProgramAdmin", "Sponsor", "Permittee", "IRTChair", "IRTMember")
    return object_response(serialize.bank(lookup.bank(row_id)))


@bp.get("/mitigation/banks")
def list_banks():
    auth.authenticate("ProgramAdmin", "Sponsor", "Permittee", "IRTChair", "IRTMember")
    limit, offset = pagination()
    sponsor_id = filter_string("sponsor_id")
    status = filter_enum("status", BANK_STATUSES)
    posture = filter_enum("sales_posture", POSTURES)
    rows = store.ordered(list(store.banks.values()))
    if sponsor_id is not None:
        rows = [b for b in rows if b["sponsor_id"] == sponsor_id]
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    if posture is not None:
        rows = [b for b in rows if ledger.sales_posture(b) == posture]
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.bank(b) for b in page], limit, offset, total)


@bp.get("/mitigation/banks/<row_id>/prospectuses")
def list_bank_prospectuses(row_id):
    auth.authenticate("ProgramAdmin", "Sponsor", "IRTChair", "IRTMember")
    bank = lookup.bank(row_id)
    limit, offset = pagination()
    status = filter_enum("status", ("DRAFT", "SUBMITTED", "UNDER_REVIEW",
                                   "REVISION_REQUESTED", "APPROVED", "REJECTED"))
    rows = store.ordered([p for p in store.prospectuses.values()
                          if p["bank_id"] == bank["id"]])
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.prospectus(p) for p in page], limit, offset, total)


@bp.get("/mitigation/banks/<row_id>/work-plans")
def list_bank_work_plans(row_id):
    auth.authenticate("ProgramAdmin", "Sponsor", "IRTChair", "IRTMember")
    bank = lookup.bank(row_id)
    limit, offset = pagination()
    status = filter_enum("status", ("DRAFT", "SUBMITTED", "APPROVED", "RETURNED"))
    rows = store.ordered([w for w in store.work_plans.values()
                          if w["bank_id"] == bank["id"]])
    if status is not None:
        rows = [w for w in rows if w["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.work_plan(w) for w in page], limit, offset, total)


@bp.get("/mitigation/banks/<row_id>/performance-standards")
def list_bank_standards(row_id):
    auth.authenticate("ProgramAdmin", "Sponsor", "IRTChair", "IRTMember")
    bank = lookup.bank(row_id)
    limit, offset = pagination()
    rows = sorted(ledger.bank_standards(bank["id"]),
                  key=lambda s: (s["effective_from_year"], s["standard_code"]))
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.performance_standard(s) for s in page],
                         limit, offset, total)


@bp.get("/mitigation/banks/<row_id>/ledger")
def list_bank_ledger(row_id):
    auth.authenticate("ProgramAdmin", "Sponsor", "IRTChair", "IRTMember")
    bank = lookup.bank(row_id)
    limit, offset = pagination()
    entry_type = filter_enum("entry_type", ENTRY_TYPES)
    rows = sorted(store.bank_ledger(bank["id"]), key=lambda e: e["sequence_number"])
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.ledger_entry(e) for e in page], limit, offset, total)


@bp.get("/mitigation/banks/<row_id>/credit-forecast")
def read_credit_forecast(row_id):
    auth.authenticate("ProgramAdmin", "Sponsor", "IRTChair", "IRTMember")
    bank = lookup.bank(row_id)
    aggregate = ledger.aggregates(bank["id"])
    index, average, horizon, projected = calc.credit_demand_forecast(
        ledger.bank_sales(bank["id"]), now(), aggregate["credits_available"])
    return object_response({
        "demand_index": num(index),
        "trailing_quarter_average_credits": num(average),
        "forecast_horizon_credits": num(horizon),
        "projected_quarters_to_sellout": projected,
        "credits_available": num(aggregate["credits_available"]),
        "credits_released": num(aggregate["credits_released"]),
        "credits_sold": num(aggregate["credits_sold"]),
        "credits_on_hold": num(aggregate["credits_on_hold"]),
    })
