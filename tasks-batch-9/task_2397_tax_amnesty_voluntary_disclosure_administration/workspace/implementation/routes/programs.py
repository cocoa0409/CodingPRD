"""Program design, the eligible tax type terms, and the program lifecycle."""

from flask import Blueprint

import calc
import clock
import db
import middleware as mw
import response
import services
import validate
from errors import err
from middleware import COMPLIANCE_AUDITOR, EVERY_ROLE, PROGRAM_ADMINISTRATOR

bp = Blueprint("programs", __name__)


@bp.post("/amnesty/programs")
def create_program():
    mw.identity([PROGRAM_ADMINISTRATOR])
    body = validate.get_body()

    name = validate.vstr(body, "name")
    open_raw, open_dt = validate.vtimestamp(body, "window_open_at")
    close_raw, close_dt = validate.vtimestamp(body, "window_close_at")
    lookback_months = validate.vint(body, "lookback_months", minimum=1, maximum=120)
    base_penalty = validate.vpct(body, "base_penalty_waiver_pct")
    base_interest = validate.vpct(body, "base_interest_waiver_pct")
    multiplier = validate.vnumber(body, "post_program_penalty_multiplier", minimum=1, maximum=3)
    forecast = validate.vint(body, "revenue_forecast_cents", minimum=1)
    compliance_months = validate.vint(body, "prospective_compliance_months", required=False,
                                      default=36, minimum=12, maximum=120)
    installment_max = validate.vint(body, "installment_max_count", required=False,
                                    default=12, minimum=1, maximum=24)

    if not open_dt < close_dt:
        raise err("ERR_INVALID_PROGRAM_WINDOW")

    rec = db.insert(db.programs, {
        "name": name,
        "window_open_at": open_raw,
        "window_close_at": close_raw,
        "lookback_months": lookback_months,
        "base_penalty_waiver_pct": base_penalty,
        "base_interest_waiver_pct": base_interest,
        "post_program_penalty_multiplier": multiplier,
        "prospective_compliance_months": compliance_months,
        "revenue_forecast_cents": forecast,
        "installment_max_count": installment_max,
        "status": "DRAFT",
        "closed_at": None,
        "final_realization_pct": None,
        "_open_dt": open_dt,
        "_close_dt": close_dt,
        "_nonparticipant_ids": set(),
    })
    return response.created(services.program_out(rec))


@bp.get("/amnesty/programs")
def list_programs():
    mw.identity(EVERY_ROLE)
    limit, offset = response.pagination()
    rows = mw.filter_equals(db.ordered(list(db.programs.values())), "status")
    return response.paginate(rows, limit, offset, services.program_out)


@bp.get("/amnesty/programs/<program_id>")
def read_program(program_id):
    mw.identity(EVERY_ROLE)
    program = mw.find(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    return response.ok(services.program_out(program))


@bp.post("/amnesty/programs/<program_id>/tax-type-terms")
def create_term(program_id):
    mw.identity([PROGRAM_ADMINISTRATOR])
    program = mw.find(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    body = validate.get_body()

    tax_type = validate.venum(body, "tax_type", validate.TAX_TYPES)
    start = validate.vdate(body, "eligible_period_start")
    end = validate.vdate(body, "eligible_period_end")
    min_liability = validate.vint(body, "min_liability_cents", minimum=0)
    penalty_pct = validate.vpct(body, "penalty_waiver_pct", required=False)
    interest_pct = validate.vpct(body, "interest_waiver_pct", required=False)
    requires_nonfiler = validate.vbool(body, "requires_prior_nonfiler", required=False, default=False)

    if program["status"] != "DRAFT":
        raise err("ERR_PROGRAM_NOT_DRAFT")

    # half-open windows: touching endpoints do not overlap
    for existing in services.terms_for_tax_type(program_id, tax_type):
        other_start = clock.parse_date(existing["eligible_period_start"])
        other_end = clock.parse_date(existing["eligible_period_end"])
        if start < other_end and other_start < end:
            raise err("ERR_TAX_TYPE_TERM_WINDOW_OVERLAP")

    rec = db.insert(db.tax_type_terms, {
        "program_id": program_id,
        "tax_type": tax_type,
        "eligible_period_start": body["eligible_period_start"],
        "eligible_period_end": body["eligible_period_end"],
        "penalty_waiver_pct": penalty_pct,
        "interest_waiver_pct": interest_pct,
        "min_liability_cents": min_liability,
        "requires_prior_nonfiler": requires_nonfiler,
    })
    return response.created(services.term_out(rec))


@bp.get("/amnesty/programs/<program_id>/tax-type-terms")
def list_terms(program_id):
    mw.identity(EVERY_ROLE)
    mw.find(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    limit, offset = response.pagination()
    rows = mw.filter_equals(services.program_terms(program_id), "tax_type")
    return response.paginate(rows, limit, offset, services.term_out)


@bp.get("/amnesty/tax-type-terms/<term_id>")
def read_term(term_id):
    mw.identity(EVERY_ROLE)
    term = mw.find(db.tax_type_terms, term_id, "ERR_TAX_TYPE_TERM_NOT_FOUND")
    return response.ok(services.term_out(term))


@bp.post("/amnesty/programs/<program_id>/open")
def open_program(program_id):
    mw.identity([PROGRAM_ADMINISTRATOR])
    program = mw.find(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    if program["status"] != "DRAFT":
        raise err("ERR_PROGRAM_NOT_DRAFT")
    if not services.program_terms(program_id):
        raise err("ERR_NO_ELIGIBLE_TAX_TYPE_TERMS")
    if clock.now() >= program["_close_dt"]:
        raise err("ERR_PROGRAM_WINDOW_CLOSED")
    program["status"] = "OPEN"
    db.touch(program)
    return response.ok(services.program_out(program))


@bp.post("/amnesty/programs/<program_id>/close")
def close_program(program_id):
    mw.identity([PROGRAM_ADMINISTRATOR])
    program = mw.find(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    if program["status"] != "OPEN":
        raise err("ERR_PROGRAM_NOT_OPEN")
    if clock.now() < program["_close_dt"]:
        raise err("ERR_PROGRAM_WINDOW_NOT_ELAPSED")
    services.close_program_cascade(program)
    return response.ok(services.program_out(program))


@bp.post("/amnesty/programs/<program_id>/reconcile")
def reconcile_program(program_id):
    mw.identity([PROGRAM_ADMINISTRATOR])
    program = mw.find(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    if program["status"] != "CLOSED":
        raise err("ERR_PROGRAM_NOT_CLOSED")
    collected = services.program_collected_cents(program)
    program["final_realization_pct"] = calc.pct_out(
        calc.realization_pct(collected, program["revenue_forecast_cents"]))
    program["status"] = "RECONCILED"
    db.touch(program)
    return response.ok(services.program_out(program))


@bp.post("/amnesty/programs/<program_id>/installment-sweep")
def sweep_program(program_id):
    mw.identity([PROGRAM_ADMINISTRATOR])
    program = mw.find(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    return response.ok(services.installment_sweep(program))


@bp.get("/amnesty/programs/<program_id>/revenue-summary")
def revenue_summary(program_id):
    mw.identity([PROGRAM_ADMINISTRATOR, COMPLIANCE_AUDITOR])
    program = mw.find(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    return response.ok(services.program_revenue_realization(program))


@bp.post("/_clock/set_current_utc")
def set_clock():
    mw.identity([PROGRAM_ADMINISTRATOR])
    body = validate.get_body()
    raw, parsed = validate.vtimestamp(body, "to_iso8601")
    clock.set_now(parsed)
    return response.ok({"current_utc": raw})
