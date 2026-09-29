"""Logical clock, statutory reference data and party registration."""

from flask import Blueprint, request

import calc
from core import (
    add_months,
    clock_now,
    created,
    db,
    err,
    fmt_date,
    fmt_dt,
    get_body,
    new_row,
    ok,
    parse_date_str,
    render_list,
    require_auth,
    set_clock,
    v_date,
    v_enum,
    v_int,
    v_money,
    v_str,
    v_datetime,
)
import domain
from domain import must, rows

bp = Blueprint("reference", __name__)

ALL_ROLES = ["BoardAdmin", "LicensingAnalyst", "Investigator", "HearingOfficer",
             "FundAdjudicator", "Licensee", "Consumer"]


# ---------------------------------------------------------------- clock -----
@bp.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    body = get_body()
    dt = v_datetime(body, "current_utc")
    set_clock(dt)
    return ok({"current_utc": fmt_dt(clock_now())})


# ------------------------------------------------- trade classifications ----
@bp.route("/licensing/trade-classifications", methods=["POST"])
def create_classification():
    require_auth(["BoardAdmin"])
    body = get_body()
    code = v_str(body, "code")
    if len(code) < 2 or len(code) > 8:
        err("ERR_INVALID_REQUEST", "code must be between 2 and 8 characters")
    name = v_str(body, "name")
    hazard_tier = v_int(body, "hazard_tier")
    if hazard_tier not in (1, 2, 3):
        err("ERR_INVALID_REQUEST", "hazard_tier must be 1, 2 or 3")
    min_experience_months = v_int(body, "min_experience_months", minv=0)
    min_net_worth_cents = v_money(body, "min_net_worth_cents")
    required_bond_amount_cents = v_money(body, "required_bond_amount_cents")
    required_ce_hours = v_int(body, "required_ce_hours", minv=0)
    renewal_base_fee_cents = v_money(body, "renewal_base_fee_cents")
    mediation_required = body.get("mediation_required", True)
    if mediation_required is None:
        mediation_required = True
    if not isinstance(mediation_required, bool):
        err("ERR_INVALID_REQUEST", "mediation_required must be a boolean")

    for existing in rows("trade_classifications"):
        if existing["code"] == code:
            err("ERR_INVALID_REQUEST", "code must be unique")

    row = new_row()
    row.update({
        "code": code,
        "name": name,
        "hazard_tier": hazard_tier,
        "min_experience_months": min_experience_months,
        "min_net_worth_cents": min_net_worth_cents,
        "required_bond_amount_cents": required_bond_amount_cents,
        "required_ce_hours": required_ce_hours,
        "renewal_base_fee_cents": renewal_base_fee_cents,
        "mediation_required": mediation_required,
    })
    db.trade_classifications[row["id"]] = row
    return created(domain.ser_classification(row))


@bp.route("/licensing/trade-classifications/<rid>", methods=["GET"])
def get_classification(rid):
    require_auth(ALL_ROLES)
    return ok(domain.ser_classification(must("trade_classifications", rid)))


# ------------------------------------------------- recovery fund accounts ---
@bp.route("/licensing/recovery-fund-accounts", methods=["POST"])
def create_fund_account():
    require_auth(["BoardAdmin"])
    body = get_body()
    fiscal_year = v_int(body, "fiscal_year")
    initial_balance_cents = v_money(body, "initial_balance_cents")
    per_claim_cap_cents = v_money(body, "per_claim_cap_cents")
    per_license_aggregate_cap_cents = v_money(body, "per_license_aggregate_cap_cents")

    for existing in rows("recovery_fund_accounts"):
        if existing["fiscal_year"] == fiscal_year:
            err("ERR_INVALID_REQUEST", "fiscal_year must be unique")

    row = new_row()
    row.update({
        "fiscal_year": fiscal_year,
        "initial_balance_cents": initial_balance_cents,
        "per_claim_cap_cents": per_claim_cap_cents,
        "per_license_aggregate_cap_cents": per_license_aggregate_cap_cents,
    })
    db.recovery_fund_accounts[row["id"]] = row
    return created(domain.ser_fund_account(row))


@bp.route("/licensing/recovery-fund-accounts/<rid>", methods=["GET"])
def get_fund_account(rid):
    require_auth(["BoardAdmin", "FundAdjudicator", "LicensingAnalyst"])
    return ok(domain.ser_fund_account(must("recovery_fund_accounts", rid)))


# --------------------------------------------------------------- licensees --
@bp.route("/licensing/licensees", methods=["POST"])
def create_licensee():
    require_auth(["BoardAdmin", "LicensingAnalyst"])
    body = get_body()
    legal_name = v_str(body, "legal_name")
    entity_type = v_enum(body, "entity_type",
                         ["SOLE_PROPRIETOR", "PARTNERSHIP", "CORPORATION", "LLC"])
    contact_email = v_str(body, "contact_email")
    row = new_row()
    row.update({
        "legal_name": legal_name,
        "entity_type": entity_type,
        "contact_email": contact_email,
    })
    db.licensees[row["id"]] = row
    return created(domain.ser_licensee(row))


@bp.route("/licensing/licensees/<rid>", methods=["GET"])
def get_licensee(rid):
    require_auth(["BoardAdmin", "LicensingAnalyst", "Investigator", "HearingOfficer",
                  "FundAdjudicator", "Licensee"])
    return ok(domain.ser_licensee(must("licensees", rid)))


# --------------------------------------------------- qualifying individuals -
@bp.route("/licensing/qualifying-individuals", methods=["POST"])
def create_qi():
    require_auth(["BoardAdmin", "LicensingAnalyst"])
    body = get_body()
    full_name = v_str(body, "full_name")
    verified_experience_months = v_int(body, "verified_experience_months", minv=0)
    row = new_row()
    row.update({
        "full_name": full_name,
        "verified_experience_months": verified_experience_months,
    })
    db.qualifying_individuals[row["id"]] = row
    return created(domain.ser_qualifying_individual(row))


@bp.route("/licensing/qualifying-individuals/<rid>", methods=["GET"])
def get_qi(rid):
    require_auth(["BoardAdmin", "LicensingAnalyst", "Investigator", "HearingOfficer",
                  "Licensee"])
    return ok(domain.ser_qualifying_individual(must("qualifying_individuals", rid)))


@bp.route("/licensing/qualifying-individuals/<rid>/exam-results", methods=["POST"])
def create_exam_result(rid):
    require_auth(["BoardAdmin", "LicensingAnalyst"])
    body = get_body()
    exam_type = v_enum(body, "exam_type", ["TRADE", "LAW_AND_BUSINESS"])
    trade_code = v_str(body, "trade_code", required=False)
    if exam_type == "TRADE" and trade_code is None:
        err("ERR_INVALID_REQUEST", "trade_code is required when exam_type is TRADE")
    if exam_type == "LAW_AND_BUSINESS" and trade_code is not None:
        err("ERR_INVALID_REQUEST",
            "trade_code must be omitted when exam_type is LAW_AND_BUSINESS")
    score = v_int(body, "score", minv=0, maxv=100)
    taken_on = v_date(body, "taken_on")

    qi = must("qualifying_individuals", rid)

    row = new_row(common=False)
    row.update({
        "qualifying_individual_id": qi["id"],
        "exam_type": exam_type,
        "trade_code": trade_code,
        "score": score,
        "passed": score >= calc.EXAM_PASS_SCORE,
        "taken_on": fmt_date(taken_on),
        "expires_on": fmt_date(add_months(taken_on, calc.EXAM_VALIDITY_MONTHS)),
    })
    db.exam_results[row["id"]] = row
    return created(domain.ser_exam_result(row))


@bp.route("/licensing/qualifying-individuals/<rid>/exam-results", methods=["GET"])
def list_exam_results(rid):
    require_auth(["BoardAdmin", "LicensingAnalyst", "Licensee"])
    qi = must("qualifying_individuals", rid)
    items = [e for e in rows("exam_results")
             if e["qualifying_individual_id"] == qi["id"]]
    exam_type = request.args.get("exam_type")
    if exam_type is not None:
        items = [e for e in items if e["exam_type"] == exam_type]
    return render_list(items, domain.ser_exam_result)


# --------------------------------------------------------------- consumers --
@bp.route("/licensing/consumers", methods=["POST"])
def create_consumer():
    require_auth(["BoardAdmin", "LicensingAnalyst"])
    body = get_body()
    full_name = v_str(body, "full_name")
    contact_email = v_str(body, "contact_email")
    mailing_state = v_str(body, "mailing_state")
    row = new_row()
    row.update({
        "full_name": full_name,
        "contact_email": contact_email,
        "mailing_state": mailing_state,
    })
    db.consumers[row["id"]] = row
    return created(domain.ser_consumer(row))


@bp.route("/licensing/consumers/<rid>", methods=["GET"])
def get_consumer(rid):
    require_auth(["BoardAdmin", "LicensingAnalyst", "Investigator", "FundAdjudicator",
                  "Consumer"])
    return ok(domain.ser_consumer(must("consumers", rid)))
