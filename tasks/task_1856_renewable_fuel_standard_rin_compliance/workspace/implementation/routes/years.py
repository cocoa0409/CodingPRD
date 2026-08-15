"""ObligationYear endpoints: create, get, list, close-volume, finalize."""
from flask import Blueprint, request

import db
from errors import (
    invalid_request, not_found, reference_not_found, invalid_state,
    year_not_finalizable,
)
from middleware import require_roles, json_body
from response import ok_object, ok_list, parse_pagination, paginate
from serializers import year_view
from services import calculations

bp = Blueprint("years", __name__)


def _get_year(year_id):
    year = db.obligation_years.get(year_id)
    if year is None:
        raise not_found("Obligation year not found")
    return year


@bp.route("/rfs/obligation-years", methods=["POST"])
def create_year():
    require_roles("ComplianceManager")
    body = json_body()

    # --- Request shape (priority 5) ---
    account_id = body.get("account_id")
    year_val = body.get("year")
    projected = body.get("projected_volume_gal")
    std_cell = body.get("std_cellulosic_pct")
    std_bbd = body.get("std_biomass_diesel_pct")
    std_adv = body.get("std_advanced_pct")
    std_total = body.get("std_total_pct")

    for field, value in (("account_id", account_id), ("year", year_val),
                         ("projected_volume_gal", projected),
                         ("std_cellulosic_pct", std_cell), ("std_biomass_diesel_pct", std_bbd),
                         ("std_advanced_pct", std_adv), ("std_total_pct", std_total)):
        if value is None:
            raise invalid_request(f"{field} is required")

    if not isinstance(year_val, int) or isinstance(year_val, bool):
        raise invalid_request("year must be an integer")
    if not isinstance(projected, int) or isinstance(projected, bool) or projected <= 0:
        raise invalid_request("projected_volume_gal must be a positive integer")
    for name, pct in (("std_cellulosic_pct", std_cell), ("std_biomass_diesel_pct", std_bbd),
                      ("std_advanced_pct", std_adv), ("std_total_pct", std_total)):
        if not isinstance(pct, (int, float)) or isinstance(pct, bool) or pct < 0:
            raise invalid_request(f"{name} must be a non-negative number")
    # Monotonically non-decreasing: cellulosic <= bbd <= advanced <= total
    if not (std_cell <= std_bbd <= std_adv <= std_total):
        raise invalid_request("Standard percentages must be monotonically non-decreasing")

    # --- Referential integrity (priority 6) ---
    account = db.compliance_accounts.get(account_id)
    if account is None:
        raise reference_not_found("Referenced account does not exist")

    # --- Uniqueness (priority 10): (account_id, year) unique ---
    for existing in db.obligation_years.values():
        if existing["account_id"] == account_id and existing["year"] == year_val:
            raise invalid_request("An obligation year already exists for this account and year")

    now = db.now_utc()
    row = {
        "id": db.new_id(),
        "account_id": account_id,
        "year": year_val,
        "projected_volume_gal": projected,
        "actual_volume_gal": None,
        "std_cellulosic_pct": std_cell,
        "std_biomass_diesel_pct": std_bbd,
        "std_advanced_pct": std_adv,
        "std_total_pct": std_total,
        "status": "OPEN",
        "provisional_rvo_cellulosic_rins": None,
        "provisional_rvo_biomass_diesel_rins": None,
        "provisional_rvo_advanced_rins": None,
        "provisional_rvo_total_rins": None,
        "final_rvo_cellulosic_rins": None,
        "final_rvo_biomass_diesel_rins": None,
        "final_rvo_advanced_rins": None,
        "final_rvo_total_rins": None,
        "retired_cellulosic_rins": 0,
        "retired_biomass_diesel_rins": 0,
        "retired_advanced_rins": 0,
        "retired_total_rins": 0,
        "retired_prior_cellulosic_rins": 0,
        "retired_prior_biomass_diesel_rins": 0,
        "retired_prior_advanced_rins": 0,
        "retired_prior_total_rins": 0,
        "compliance_posture": "ON_TRACK",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    calculations.compute_provisional_rvos(row)
    db.obligation_years[row["id"]] = row
    return ok_object(year_view(row), status=201)


@bp.route("/rfs/obligation-years/<year_id>", methods=["GET"])
def get_year(year_id):
    require_roles("OpsAdmin", "ComplianceManager", "Trader", "Auditor")
    return ok_object(year_view(_get_year(year_id)))


@bp.route("/rfs/obligation-years", methods=["GET"])
def list_years():
    require_roles("OpsAdmin", "ComplianceManager", "Trader", "Auditor")
    limit, offset = parse_pagination(request.args)
    account_id = request.args.get("account_id")
    rows = list(db.obligation_years.values())
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return ok_list([year_view(r) for r in page], limit, offset, total)


@bp.route("/rfs/obligation-years/<year_id>/close-volume", methods=["POST"])
def close_volume(year_id):
    require_roles("ComplianceManager")
    year = _get_year(year_id)
    body = json_body()
    actual = body.get("actual_volume_gal")
    if not isinstance(actual, int) or isinstance(actual, bool) or actual <= 0:
        raise invalid_request("actual_volume_gal must be a positive integer")
    if year["status"] != "OPEN":
        raise invalid_state("Obligation year is not OPEN")

    year["actual_volume_gal"] = actual
    year["status"] = "VOLUME_CLOSED"
    calculations.compute_final_rvos(year)
    calculations.rederive_posture(year)
    year["version"] += 1
    year["updated_at"] = db.now_utc()
    return ok_object(year_view(year))


@bp.route("/rfs/obligation-years/<year_id>/finalize", methods=["POST"])
def finalize_year(year_id):
    require_roles("ComplianceManager")
    year = _get_year(year_id)
    if year["status"] != "VOLUME_CLOSED":
        if year["status"] == "OPEN":
            raise year_not_finalizable("Year must be VOLUME_CLOSED to finalize")
        raise invalid_state("Obligation year is not in a finalizable state")

    # Requires an ANNUAL report with status ACCEPTED
    has_accepted_annual = any(
        r["obligation_year_id"] == year["id"] and r["report_type"] == "ANNUAL" and r["status"] == "ACCEPTED"
        for r in db.compliance_reports.values()
    )
    # Requires an attest engagement with status CLOSED_CLEAN
    has_clean_attest = any(
        e["obligation_year_id"] == year["id"] and e["status"] == "CLOSED_CLEAN"
        for e in db.attest_engagements.values()
    )
    if not (has_accepted_annual and has_clean_attest):
        raise year_not_finalizable("Finalize requires an ACCEPTED annual report and a CLOSED_CLEAN attest engagement")

    year["status"] = "FINALIZED"
    year["version"] += 1
    year["updated_at"] = db.now_utc()
    return ok_object(year_view(year))
