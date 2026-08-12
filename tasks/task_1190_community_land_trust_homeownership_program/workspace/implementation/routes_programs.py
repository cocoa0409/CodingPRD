"""Clock and CLTProgram endpoints."""
from flask import Blueprint, jsonify

import db
import engine
from auth import ALL_ROLES, require
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from scope import get_program_or_404
from util import (
    body, bump, iso, new_entity, ok_object, opt_int, opt_num, opt_str,
    paginated, req_dt, req_enum, req_int, req_num, req_str, ser_program,
)

bp = Blueprint("programs", __name__)

RESALE_FORMULA_KINDS = {"APPRAISAL_BASED", "INDEXED"}

READ_ROLES = ALL_ROLES  # every role may read programs


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@require(["PlatformAdmin", "ProgramAdmin"])
def set_current_utc():
    data = body()
    to = req_dt(data, "to_iso8601")
    db.set_now(to)
    engine.run_time_pass(to)
    return jsonify(ok_object({"now_iso8601": iso(to)})), 200


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------

@bp.post("/programs")
@require(["PlatformAdmin"])
def create_program():
    data = body()
    name = req_str(data, "name")
    ami_eff = req_dt(data, "ami_table_effective_date")
    area_median = req_int(data, "area_median_income_cents")
    max_elig = req_num(data, "max_eligibility_ami_pct")
    base_fee = req_int(data, "ground_lease_base_fee_cents")
    kind = req_enum(data, "resale_formula_kind", RESALE_FORMULA_KINDS)

    p = new_entity()
    p.update({
        "name": name,
        "ami_table_effective_date": ami_eff,
        "area_median_income_cents": area_median,
        "max_eligibility_ami_pct": max_elig,
        "ground_lease_term_years": opt_int(data, "ground_lease_term_years", 99),
        "ground_lease_base_fee_cents": base_fee,
        "low_income_fee_reduction_pct": opt_num(data, "low_income_fee_reduction_pct", 0.5),
        "resale_formula_kind": kind,
        "indexed_annual_appreciation_pct": opt_num(data, "indexed_annual_appreciation_pct", 0.015),
        "appraisal_seller_share_pct": opt_num(data, "appraisal_seller_share_pct", 0.25),
        "max_refi_ltv_pct": opt_num(data, "max_refi_ltv_pct", 0.95),
        "max_equity_withdrawal_cents": opt_int(data, "max_equity_withdrawal_cents", 0),
        "default_cure_window_days": opt_int(data, "default_cure_window_days", 30),
        "inspection_cycle_months": opt_int(data, "inspection_cycle_months", 24),
        "status": "ACTIVE",
    })
    db.store.programs[p["id"]] = p
    return jsonify(ok_object(ser_program(p))), 201


@bp.get("/programs")
@require(READ_ROLES)
def list_programs():
    return jsonify(paginated(list(db.store.programs.values()), ser_program)), 200


@bp.get("/programs/<pid>")
@require(READ_ROLES)
def get_program(pid):
    return jsonify(ok_object(ser_program(get_program_or_404(pid)))), 200


@bp.put("/programs/<pid>")
@require(["ProgramAdmin"])
def update_program(pid):
    p = get_program_or_404(pid)
    data = body()

    old_ami = p["area_median_income_cents"]
    old_base = p["ground_lease_base_fee_cents"]
    old_reduction = p["low_income_fee_reduction_pct"]

    if "name" in data and data["name"] is not None:
        p["name"] = req_str(data, "name")
    if "ami_table_effective_date" in data and data["ami_table_effective_date"] is not None:
        p["ami_table_effective_date"] = req_dt(data, "ami_table_effective_date")
    if "area_median_income_cents" in data and data["area_median_income_cents"] is not None:
        p["area_median_income_cents"] = req_int(data, "area_median_income_cents")
    if "max_eligibility_ami_pct" in data and data["max_eligibility_ami_pct"] is not None:
        p["max_eligibility_ami_pct"] = req_num(data, "max_eligibility_ami_pct")
    if "ground_lease_term_years" in data and data["ground_lease_term_years"] is not None:
        p["ground_lease_term_years"] = req_int(data, "ground_lease_term_years")
    if "ground_lease_base_fee_cents" in data and data["ground_lease_base_fee_cents"] is not None:
        p["ground_lease_base_fee_cents"] = req_int(data, "ground_lease_base_fee_cents")
    if "low_income_fee_reduction_pct" in data and data["low_income_fee_reduction_pct"] is not None:
        p["low_income_fee_reduction_pct"] = req_num(data, "low_income_fee_reduction_pct")
    if "resale_formula_kind" in data and data["resale_formula_kind"] is not None:
        p["resale_formula_kind"] = req_enum(data, "resale_formula_kind", RESALE_FORMULA_KINDS)
    if "indexed_annual_appreciation_pct" in data and data["indexed_annual_appreciation_pct"] is not None:
        p["indexed_annual_appreciation_pct"] = req_num(data, "indexed_annual_appreciation_pct")
    if "appraisal_seller_share_pct" in data and data["appraisal_seller_share_pct"] is not None:
        p["appraisal_seller_share_pct"] = req_num(data, "appraisal_seller_share_pct")
    if "max_refi_ltv_pct" in data and data["max_refi_ltv_pct"] is not None:
        p["max_refi_ltv_pct"] = req_num(data, "max_refi_ltv_pct")
    if "max_equity_withdrawal_cents" in data and data["max_equity_withdrawal_cents"] is not None:
        p["max_equity_withdrawal_cents"] = req_int(data, "max_equity_withdrawal_cents")
    if "default_cure_window_days" in data and data["default_cure_window_days"] is not None:
        p["default_cure_window_days"] = req_int(data, "default_cure_window_days")
    if "inspection_cycle_months" in data and data["inspection_cycle_months"] is not None:
        p["inspection_cycle_months"] = req_int(data, "inspection_cycle_months")

    bump(p)

    now = db.get_now()
    if p["area_median_income_cents"] != old_ami:
        # Every household ami_pct recomputed from its latest approved cert.
        for h in db.store.households.values():
            if h["program_id"] != p["id"]:
                continue
            cert = engine.latest_approved_cert(h["id"])
            if cert is not None:
                h["ami_pct"] = engine.compute_ami_pct(
                    cert["verified_annual_income_cents"],
                    p["area_median_income_cents"],
                    cert["household_size_at_cert"],
                )
                bump(h)
        engine.refresh_program_waitlist_scores(p["id"], now)
    if (p["area_median_income_cents"] != old_ami
            or p["ground_lease_base_fee_cents"] != old_base
            or p["low_income_fee_reduction_pct"] != old_reduction):
        engine.recompute_program_fees(p, now)

    return jsonify(ok_object(ser_program(p))), 200


@bp.post("/programs/<pid>/suspend")
@require(["ProgramAdmin"])
def suspend_program(pid):
    p = get_program_or_404(pid)
    if p["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ACTIVE program can be suspended")
    p["status"] = "SUSPENDED"
    bump(p)
    return jsonify(ok_object(ser_program(p))), 200


@bp.post("/programs/<pid>/reinstate")
@require(["ProgramAdmin"])
def reinstate_program(pid):
    p = get_program_or_404(pid)
    if p["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a SUSPENDED program can be reinstated")
    p["status"] = "ACTIVE"
    bump(p)
    return jsonify(ok_object(ser_program(p))), 200


@bp.post("/programs/<pid>/close")
@require(["ProgramAdmin"])
def close_program(pid):
    p = get_program_or_404(pid)
    if p["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ACTIVE or SUSPENDED program can be closed")
    for lease in db.store.leases.values():
        unit = db.store.units.get(lease["unit_id"])
        if unit and unit["program_id"] == pid and lease["status"] in (
                "ACTIVE", "IN_DEFAULT", "CURE_PERIOD"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Program has live ground leases and cannot be closed")
    for listing in db.store.listings.values():
        unit = db.store.units.get(listing["unit_id"])
        if unit and unit["program_id"] == pid and listing["status"] in (
                "OPEN", "MATCHED", "UNDER_CONTRACT"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Program has open resale listings and cannot be closed")
    p["status"] = "CLOSED"
    bump(p)
    # Remaining ACTIVE waitlist entries in this program expire.
    for entry in db.store.waitlist.values():
        h = db.store.households.get(entry["household_id"])
        if h and h["program_id"] == pid and entry["status"] == "ACTIVE":
            entry["status"] = "EXPIRED"
            bump(entry)
            if h["waitlist_entry_id"] == entry["id"]:
                h["waitlist_entry_id"] = None
                bump(h)
    return jsonify(ok_object(ser_program(p))), 200
