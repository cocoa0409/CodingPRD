"""Multifamily Acquisition Due Diligence API — Flask entry point."""

import os
from flask import Flask, request

import clock
import db
import services
from errors import ApiError, raise_error
import errors as E
from middleware import get_caller, require_role
from response import success_object, success_list, error_response

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_NOT_FOUND", 404, "route not found")


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_NOT_FOUND", 404, "method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(err):
    import traceback
    traceback.print_exc()
    return error_response("ERR_INTERNAL", 500, str(err))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def body():
    if request.data:
        try:
            return request.get_json(force=True, silent=False) or {}
        except Exception:
            raise_error(E.ERR_INVALID_REQUEST, "invalid JSON body")
    return {}


def require_field(data, name):
    if name not in data or data[name] is None:
        raise_error(E.ERR_INVALID_REQUEST, f"missing required field: {name}")
    return data[name]


def opt_field(data, name, default=None):
    return data.get(name, default)


def require_enum(value, allowed, field_name):
    if value not in allowed:
        raise_error(E.ERR_INVALID_ENUM, f"invalid value for {field_name}: {value}")
    return value


def require_int(value, field_name, *, non_negative=False):
    if not isinstance(value, int) or isinstance(value, bool):
        raise_error(E.ERR_INVALID_REQUEST, f"{field_name} must be an integer")
    if non_negative and value < 0:
        raise_error(E.ERR_INVALID_REQUEST, f"{field_name} must be non-negative")
    return value


def require_str(value, field_name):
    if not isinstance(value, str):
        raise_error(E.ERR_INVALID_REQUEST, f"{field_name} must be a string")
    return value


def require_bool(value, field_name):
    if not isinstance(value, bool):
        raise_error(E.ERR_INVALID_REQUEST, f"{field_name} must be a boolean")
    return value


def parse_iso_field(value, field_name):
    try:
        return clock.parse_iso(value)
    except Exception:
        raise_error(E.ERR_INVALID_REQUEST, f"{field_name} must be a valid ISO 8601 datetime")


def parse_date_range(start_v, end_v, start_name, end_name):
    s = parse_iso_field(start_v, start_name)
    e = parse_iso_field(end_v, end_name)
    if e < s:
        raise_error(E.ERR_INVALID_DATE_RANGE, f"{end_name} precedes {start_name}")
    return s, e


def get_pagination():
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
    except Exception:
        raise_error(E.ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(offset_raw)
    except Exception:
        raise_error(E.ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_error(E.ERR_INVALID_REQUEST, "limit out of range")
    if offset < 0:
        raise_error(E.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items):
    """items: list sorted by created_at ASC. Returns a Flask response."""
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Serializers (return a dict with all fields of an entity)
# ---------------------------------------------------------------------------

def serialize(entity):
    return dict(entity)


# ---------------------------------------------------------------------------
# GET helpers
# ---------------------------------------------------------------------------

def get_acquisition_or_404(acq_id):
    a = db.acquisitions.get(acq_id)
    if a is None:
        raise_error(E.ERR_ACQUISITION_NOT_FOUND, f"acquisition {acq_id} not found")
    return a


def get_unit_or_404(unit_id):
    u = db.units.get(unit_id)
    if u is None:
        raise_error(E.ERR_UNIT_NOT_FOUND, f"unit {unit_id} not found")
    return u


def get_lease_or_404(lease_id):
    l = db.lease_files.get(lease_id)
    if l is None:
        raise_error(E.ERR_LEASE_FILE_NOT_FOUND, f"lease file {lease_id} not found")
    return l


def get_concession_or_404(cid):
    c = db.concessions.get(cid)
    if c is None:
        raise_error(E.ERR_CONCESSION_NOT_FOUND, f"concession {cid} not found")
    return c


def get_inspection_or_404(iid):
    i = db.inspections.get(iid)
    if i is None:
        raise_error(E.ERR_INSPECTION_NOT_FOUND, f"inspection {iid} not found")
    return i


def get_finding_or_404(fid):
    f = db.findings.get(fid)
    if f is None:
        raise_error(E.ERR_FINDING_NOT_FOUND, f"finding {fid} not found")
    return f


def get_utility_record_or_404(rid):
    r = db.utility_records.get(rid)
    if r is None:
        raise_error(E.ERR_UTILITY_RECORD_NOT_FOUND, f"utility record {rid} not found")
    return r


def get_tax_projection_or_404(pid):
    p = db.tax_projections.get(pid)
    if p is None:
        raise_error(E.ERR_TAX_PROJECTION_NOT_FOUND, f"tax projection {pid} not found")
    return p


def get_deposit_or_404(did):
    d = db.deposits.get(did)
    if d is None:
        raise_error(E.ERR_DEPOSIT_NOT_FOUND, f"deposit {did} not found")
    return d


def get_decision_or_404(did):
    d = db.employee_decisions.get(did)
    if d is None:
        raise_error(E.ERR_EMPLOYEE_DECISION_NOT_FOUND, f"employee decision {did} not found")
    return d


def get_contract_or_404(cid):
    c = db.service_contracts.get(cid)
    if c is None:
        raise_error(E.ERR_SERVICE_CONTRACT_NOT_FOUND, f"service contract {cid} not found")
    return c


def get_policy_or_404(pid):
    p = db.insurance_policies.get(pid)
    if p is None:
        raise_error(E.ERR_INSURANCE_POLICY_NOT_FOUND, f"insurance policy {pid} not found")
    return p


def get_statement_or_404(sid):
    s = db.proration_statements.get(sid)
    if s is None:
        raise_error(E.ERR_PRORATION_STATEMENT_NOT_FOUND, f"proration statement {sid} not found")
    return s


def get_adjustment_or_404(aid):
    a = db.post_closing_adjustments.get(aid)
    if a is None:
        raise_error(E.ERR_ADJUSTMENT_NOT_FOUND, f"adjustment {aid} not found")
    return a


def unit_acquisition(unit):
    return db.acquisitions.get(unit["acquisition_id"])


def lease_acquisition(lease):
    unit = db.units.get(lease["unit_id"])
    if unit is None:
        return None
    return db.acquisitions.get(unit["acquisition_id"])


def inspection_acquisition(insp):
    unit = db.units.get(insp["unit_id"])
    if unit is None:
        return None
    return db.acquisitions.get(unit["acquisition_id"])


def deposit_acquisition(entry):
    return lease_acquisition(db.lease_files.get(entry["lease_file_id"]) or {})


def _reject_terminal_acquisition(acq):
    if acq["status"] in ("SETTLED", "TERMINATED"):
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "acquisition is terminal")


# ===========================================================================
# Clock endpoint
# ===========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = get_caller()
    require_role(role, ["PlatformAdmin"])
    data = body()
    to_iso = require_field(data, "to_iso8601")
    new_dt = parse_iso_field(to_iso, "to_iso8601")
    new_current = clock.set_current_utc(to_iso)
    # Auto-renew sweep: IDENTIFIED/UNDER_REVIEW contracts with auto_renew and decision_deadline < new clock
    for contract in list(db.service_contracts.values()):
        if contract["status"] in ("IDENTIFIED", "UNDER_REVIEW") and contract.get("auto_renew"):
            dd = clock.parse_iso(contract["decision_deadline"])
            if new_dt > dd:
                contract["status"] = "AUTO_RENEWED"
                services.touch(contract)
    return success_object({"current_utc": new_current}, 200)


# ===========================================================================
# Acquisitions
# ===========================================================================

ALL_ROLES = ["PlatformAdmin", "AcquisitionsAnalyst", "UnderwritingManager",
             "PropertyOperationsLead", "HRPartner", "VendorManager", "EscrowOfficer"]


@app.route("/acquisitions", methods=["POST"])
def create_acquisition():
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    data = body()
    property_name = require_str(require_field(data, "property_name"), "property_name")
    address = require_str(require_field(data, "address"), "address")
    price = require_int(require_field(data, "agreed_purchase_price_cents"), "agreed_purchase_price_cents", non_negative=True)
    earnest = require_int(require_field(data, "earnest_money_cents"), "earnest_money_cents", non_negative=True)
    closing_date = require_field(data, "closing_date")
    diligence_deadline = require_field(data, "diligence_deadline")
    parse_iso_field(closing_date, "closing_date")
    parse_iso_field(diligence_deadline, "diligence_deadline")
    assessment_ratio = require_field(data, "assessment_ratio")
    millage_rate = require_field(data, "millage_rate")
    prior_tax = require_int(require_field(data, "prior_year_tax_cents"), "prior_year_tax_cents", non_negative=True)
    true_up = opt_field(data, "true_up_window_days", 90)
    require_int(true_up, "true_up_window_days", non_negative=True)
    meb = opt_field(data, "maintenance_estimate_basis", "INSPECTOR_BASIS")
    require_enum(meb, ["INSPECTOR_BASIS", "SELLER_BASIS"], "maintenance_estimate_basis")
    iam = opt_field(data, "interest_accrual_method", "DAILY_ACCRUAL")
    require_enum(iam, ["SIMPLE_ANNUAL", "DAILY_ACCRUAL"], "interest_accrual_method")

    acq_id = db.new_id()
    ts = db.now_iso()
    acq = {
        "id": acq_id,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "property_name": property_name,
        "address": address,
        "agreed_purchase_price_cents": price,
        "earnest_money_cents": earnest,
        "closing_date": closing_date,
        "diligence_deadline": diligence_deadline,
        "true_up_window_days": true_up,
        "assessment_ratio": assessment_ratio,
        "millage_rate": millage_rate,
        "prior_year_tax_cents": prior_tax,
        "maintenance_estimate_basis": meb,
        "interest_accrual_method": iam,
        "status": "DRAFT",
        "readiness_posture": "ON_TRACK",
        "deferred_maintenance_total_cents": 0,
        "rent_roll_variance_cents": 0,
        "deposit_variance_cents": 0,
        "payroll_accrual_cents": 0,
        "net_proration_cents": 0,
        "closing_executed_at": None,
    }
    db.acquisitions[acq_id] = acq
    return success_object(serialize(acq), 201)


@app.route("/acquisitions", methods=["GET"])
def list_acquisitions():
    get_caller()
    items = list(db.acquisitions.values())
    status_filter = request.args.get("status")
    if status_filter:
        items = [a for a in items if a["status"] == status_filter]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    return paginate([serialize(a) for a in items])


@app.route("/acquisitions/<acq_id>", methods=["GET"])
def get_acquisition(acq_id):
    get_caller()
    acq = get_acquisition_or_404(acq_id)
    return success_object(serialize(acq), 200)


@app.route("/acquisitions/<acq_id>", methods=["PATCH"])
def patch_acquisition(acq_id):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    acq = get_acquisition_or_404(acq_id)
    _reject_terminal_acquisition(acq)
    if acq["status"] not in ("DRAFT", "IN_DILIGENCE"):
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "amendments allowed only while DRAFT or IN_DILIGENCE")
    data = body()
    basis_changed = False
    if "closing_date" in data and data["closing_date"] is not None:
        parse_iso_field(data["closing_date"], "closing_date")
        acq["closing_date"] = data["closing_date"]
    if "maintenance_estimate_basis" in data and data["maintenance_estimate_basis"] is not None:
        new_basis = data["maintenance_estimate_basis"]
        require_enum(new_basis, ["INSPECTOR_BASIS", "SELLER_BASIS"], "maintenance_estimate_basis")
        if new_basis != acq["maintenance_estimate_basis"]:
            basis_changed = True
            acq["maintenance_estimate_basis"] = new_basis
    if "interest_accrual_method" in data and data["interest_accrual_method"] is not None:
        iam = data["interest_accrual_method"]
        require_enum(iam, ["SIMPLE_ANNUAL", "DAILY_ACCRUAL"], "interest_accrual_method")
        acq["interest_accrual_method"] = iam
    if basis_changed:
        # Re-derive verified_cost_cents for every finding currently VERIFIED under this acquisition
        for f in db.findings.values():
            insp = db.inspections.get(f["inspection_id"])
            if insp is None:
                continue
            unit = db.units.get(insp["unit_id"])
            if unit is None or unit["acquisition_id"] != acq["id"]:
                continue
            if f["status"] == "VERIFIED":
                f["verified_cost_cents"] = services.compute_verified_cost(acq, f)
                services.touch(f)
        services.recompute_deferred_maintenance(acq)
        acq["readiness_posture"] = services.compute_posture(acq)
    services.touch(acq)
    return success_object(serialize(acq), 200)


@app.route("/acquisitions/<acq_id>/kickoff", methods=["POST"])
def kickoff(acq_id):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    acq = get_acquisition_or_404(acq_id)
    if acq["status"] != "DRAFT":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "kickoff requires DRAFT")
    acq["status"] = "IN_DILIGENCE"
    acq["readiness_posture"] = services.compute_posture(acq)
    services.touch(acq)
    return success_object(serialize(acq), 200)


@app.route("/acquisitions/<acq_id>/complete-diligence", methods=["POST"])
def complete_diligence(acq_id):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    acq = get_acquisition_or_404(acq_id)
    if acq["status"] != "IN_DILIGENCE":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "complete-diligence requires IN_DILIGENCE")
    # Recompute everything to be safe
    services.recompute_acquisition(acq)
    if acq["readiness_posture"] == "BLOCKED":
        raise_error(E.ERR_ACQUISITION_BLOCKED, "readiness posture is BLOCKED")
    # No lease for non-EXCLUDED unit in UPLOADED or DISCREPANCY_FLAGGED
    for lf in db.lease_files.values():
        unit = db.units.get(lf["unit_id"])
        if unit is None or unit["acquisition_id"] != acq["id"]:
            continue
        if unit["status"] == "EXCLUDED":
            continue
        if lf["status"] in ("UPLOADED", "DISCREPANCY_FLAGGED"):
            raise_error(E.ERR_UNRESOLVED_AUDIT_ITEMS, "lease file remains UPLOADED or DISCREPANCY_FLAGGED")
    # No deposit entry RECORDED or DISPUTED
    for entry in db.deposits.values():
        lf = db.lease_files.get(entry["lease_file_id"])
        if lf is None:
            continue
        unit = db.units.get(lf["unit_id"])
        if unit is None or unit["acquisition_id"] != acq["id"]:
            continue
        if entry["status"] in ("RECORDED", "DISPUTED"):
            raise_error(E.ERR_UNRESOLVED_AUDIT_ITEMS, "deposit entry remains RECORDED or DISPUTED")
    # Every non-EXCLUDED unit must be VERIFIED
    for unit in db.units.values():
        if unit["acquisition_id"] != acq["id"]:
            continue
        if unit["status"] == "EXCLUDED":
            continue
        if unit["status"] != "VERIFIED":
            raise_error(E.ERR_UNRESOLVED_AUDIT_ITEMS, "unit not VERIFIED")
    acq["status"] = "DILIGENCE_COMPLETE"
    services.touch(acq)
    return success_object(serialize(acq), 200)


@app.route("/acquisitions/<acq_id>/advance-to-pre-closing", methods=["POST"])
def advance_to_pre_closing(acq_id):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    acq = get_acquisition_or_404(acq_id)
    if acq["status"] != "DILIGENCE_COMPLETE":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "advance-to-pre-closing requires DILIGENCE_COMPLETE")
    approved_draft = None
    for s in db.proration_statements.values():
        if s["acquisition_id"] == acq["id"] and s["statement_type"] == "DRAFT_CLOSING" and s["status"] == "APPROVED":
            approved_draft = s
            break
    if approved_draft is None:
        raise_error(E.ERR_NO_APPROVED_DRAFT_STATEMENT, "an APPROVED DRAFT_CLOSING statement is required")
    acq["status"] = "PRE_CLOSING"
    services.touch(acq)
    return success_object(serialize(acq), 200)


@app.route("/acquisitions/<acq_id>/execute-closing", methods=["POST"])
def execute_closing(acq_id):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    acq = get_acquisition_or_404(acq_id)
    if acq["status"] != "PRE_CLOSING":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "execute-closing requires PRE_CLOSING")
    # Gate order per PRD: final approved stmt, deposits queued, no PROPOSED decisions, no IDENTIFIED/UNDER_REVIEW contracts
    final_stmt = None
    for s in db.proration_statements.values():
        if s["acquisition_id"] == acq["id"] and s["statement_type"] == "FINAL_CLOSING" and s["status"] == "APPROVED":
            final_stmt = s
            break
    if final_stmt is None:
        raise_error(E.ERR_NO_APPROVED_FINAL_STATEMENT, "an APPROVED FINAL_CLOSING statement is required")
    for entry in db.deposits.values():
        lf = db.lease_files.get(entry["lease_file_id"])
        if lf is None:
            continue
        unit = db.units.get(lf["unit_id"])
        if unit is None or unit["acquisition_id"] != acq["id"]:
            continue
        if entry["status"] not in ("ESCROW_QUEUED", "TRANSFERRED"):
            raise_error(E.ERR_DEPOSITS_NOT_QUEUED, "every deposit must be ESCROW_QUEUED or TRANSFERRED")
    for d in db.employee_decisions.values():
        if d["acquisition_id"] == acq["id"] and d["status"] == "PROPOSED":
            raise_error(E.ERR_OPEN_DECISIONS_REMAIN, "an employee decision is still PROPOSED")
    for c in db.service_contracts.values():
        if c["acquisition_id"] == acq["id"] and c["status"] in ("IDENTIFIED", "UNDER_REVIEW"):
            raise_error(E.ERR_OPEN_SERVICE_CONTRACTS_REMAIN, "a service contract is still IDENTIFIED or UNDER_REVIEW")

    # Stamp closing_executed_at from logical clock
    acq["closing_executed_at"] = clock.get_current_utc()
    acq["status"] = "CLOSED"

    # Cascade hop 1: deposits ESCROW_QUEUED -> TRANSFERRED
    for entry in db.deposits.values():
        lf = db.lease_files.get(entry["lease_file_id"])
        if lf is None:
            continue
        unit = db.units.get(lf["unit_id"])
        if unit is None or unit["acquisition_id"] != acq["id"]:
            continue
        if entry["status"] == "ESCROW_QUEUED":
            entry["status"] = "TRANSFERRED"
            services.touch(entry)

    # Cascade hop 2: regenerate DEPOSIT_TRANSFER GENERATED line on FINAL_CLOSING statement
    deposit_lines = [
        l for l in db.proration_lines.values()
        if l["statement_id"] == final_stmt["id"]
        and l["source_kind"] == "GENERATED"
        and l["line_type"] == "DEPOSIT_TRANSFER"
    ]
    new_total = 0
    has_transferred = False
    for entry in db.deposits.values():
        if entry["status"] != "TRANSFERRED":
            continue
        lf = db.lease_files.get(entry["lease_file_id"])
        if lf is None:
            continue
        unit = db.units.get(lf["unit_id"])
        if unit is None or unit["acquisition_id"] != acq["id"]:
            continue
        has_transferred = True
        new_total += (entry.get("verified_amount_cents") or 0) + (entry.get("accrued_interest_cents") or 0)
    if deposit_lines:
        line = deposit_lines[0]
        if has_transferred:
            if line["amount_cents"] != new_total:
                line["amount_cents"] = new_total
        else:
            # No transferred entries -> remove the line
            del db.proration_lines[line["id"]]
    else:
        if has_transferred:
            lid = db.new_id()
            db.proration_lines[lid] = {
                "id": lid,
                "created_at": db.now_iso(),
                "statement_id": final_stmt["id"],
                "line_type": "DEPOSIT_TRANSFER",
                "direction": "CREDIT_BUYER",
                "amount_cents": new_total,
                "source_kind": "GENERATED",
                "source_ref_type": "DEPOSIT_ENTRY",
                "source_ref_id": None,
                "memo": None,
            }

    # Cascade hop 3: statement totals + acquisition net recompute
    services.recompute_statement_totals(final_stmt)
    services.touch(final_stmt)
    services.recompute_net_proration(acq)

    # Parallel cascade: ASSUMED contracts/policies -> TRANSFERRED
    for c in db.service_contracts.values():
        if c["acquisition_id"] == acq["id"] and c["status"] == "ASSUMED":
            c["status"] = "TRANSFERRED"
            services.touch(c)
    for p in db.insurance_policies.values():
        if p["acquisition_id"] == acq["id"] and p["status"] == "ASSUMED":
            p["status"] = "TRANSFERRED"
            services.touch(p)

    services.touch(acq)
    return success_object(serialize(acq), 200)


@app.route("/acquisitions/<acq_id>/settle", methods=["POST"])
def settle_acquisition(acq_id):
    user_id, role = get_caller()
    require_role(role, ["EscrowOfficer"])
    acq = get_acquisition_or_404(acq_id)
    if acq["status"] != "CLOSED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "settle requires CLOSED")
    now = clock.now_clock_dt()
    closing_dt = clock.parse_iso(acq["closing_executed_at"])
    window_end = closing_dt + __import__("datetime").timedelta(days=acq["true_up_window_days"])
    if not (now > window_end):
        raise_error(E.ERR_TRUE_UP_WINDOW_OPEN, "true-up window still open")
    final_stmt = None
    for s in db.proration_statements.values():
        if s["acquisition_id"] == acq["id"] and s["statement_type"] == "FINAL_CLOSING":
            # There should be exactly one; find latest by created_at
            if final_stmt is None or s["created_at"] > final_stmt["created_at"]:
                final_stmt = s
    if final_stmt is None or final_stmt["status"] != "SETTLED":
        raise_error(E.ERR_FINAL_STATEMENT_NOT_SETTLED, "FINAL_CLOSING statement must be SETTLED")
    for s in db.proration_statements.values():
        if s["acquisition_id"] == acq["id"] and s["statement_type"] == "POST_CLOSING_TRUEUP":
            if s["status"] != "SETTLED":
                raise_error(E.ERR_TRUEUP_STATEMENT_NOT_SETTLED, "POST_CLOSING_TRUEUP statement must be SETTLED")
    for adj in db.post_closing_adjustments.values():
        if adj["acquisition_id"] == acq["id"] and adj["status"] in (
            "ASSERTED", "EVIDENCED", "ACCEPTED", "DISPUTED", "RESOLVED"
        ):
            raise_error(E.ERR_OPEN_ADJUSTMENTS_REMAIN, "an adjustment is not yet APPLIED")
    acq["status"] = "SETTLED"
    services.touch(acq)
    return success_object(serialize(acq), 200)


@app.route("/acquisitions/<acq_id>/terminate", methods=["POST"])
def terminate_acquisition(acq_id):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    acq = get_acquisition_or_404(acq_id)
    if acq["status"] in ("SETTLED", "TERMINATED"):
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "acquisition is terminal")
    if acq["status"] == "CLOSED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "cannot terminate after closing")
    if acq["status"] not in ("DRAFT", "IN_DILIGENCE", "DILIGENCE_COMPLETE", "PRE_CLOSING"):
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "cannot terminate from current state")
    prior_status = acq["status"]
    acq["status"] = "TERMINATED"
    # Rescind APPROVED/NOTIFIED decisions
    for d in db.employee_decisions.values():
        if d["acquisition_id"] == acq["id"] and d["status"] in ("APPROVED", "NOTIFIED"):
            d["status"] = "RESCINDED"
            services.touch(d)
    services.recompute_payroll_accrual(acq)
    if prior_status == "PRE_CLOSING":
        for c in db.service_contracts.values():
            if c["acquisition_id"] == acq["id"] and c["status"] in ("ASSUMED", "NOTICE_SENT"):
                c["status"] = "CANCELLED_EFFECTIVE"
                services.touch(c)
    services.touch(acq)
    return success_object(serialize(acq), 200)


# ===========================================================================
# Units
# ===========================================================================

@app.route("/acquisitions/units", methods=["POST"])
def create_unit():
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    data = body()
    acquisition_id = require_field(data, "acquisition_id")
    acq = get_acquisition_or_404(acquisition_id)
    _reject_terminal_acquisition(acq)
    unit_number = require_str(require_field(data, "unit_number"), "unit_number")
    floor_plan = require_str(require_field(data, "floor_plan"), "floor_plan")
    sqft = require_int(require_field(data, "sqft"), "sqft", non_negative=True)
    market_rent = require_int(require_field(data, "market_rent_cents"), "market_rent_cents", non_negative=True)
    # uniqueness
    for u in db.units.values():
        if u["acquisition_id"] == acquisition_id and u["unit_number"] == unit_number:
            raise_error(E.ERR_DUPLICATE_UNIT_NUMBER, "unit_number already exists in this acquisition")
    uid = db.new_id()
    ts = db.now_iso()
    unit = {
        "id": uid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "acquisition_id": acquisition_id,
        "unit_number": unit_number,
        "floor_plan": floor_plan,
        "sqft": sqft,
        "market_rent_cents": market_rent,
        "status": "REGISTERED",
        "lease_audited": False,
        "walk_accepted": False,
        "deposit_reconciled": False,
    }
    db.units[uid] = unit
    return success_object(serialize(unit), 201)


@app.route("/acquisitions/units", methods=["GET"])
def list_units():
    get_caller()
    items = list(db.units.values())
    acq_filter = request.args.get("acquisition_id")
    status_filter = request.args.get("status")
    if acq_filter:
        items = [u for u in items if u["acquisition_id"] == acq_filter]
    if status_filter:
        items = [u for u in items if u["status"] == status_filter]
    items.sort(key=lambda u: (u["created_at"], u["id"]))
    return paginate([serialize(u) for u in items])


@app.route("/acquisitions/units/<unit_id>", methods=["GET"])
def get_unit(unit_id):
    get_caller()
    unit = get_unit_or_404(unit_id)
    return success_object(serialize(unit), 200)


@app.route("/acquisitions/units/<unit_id>/exclude", methods=["POST"])
def exclude_unit(unit_id):
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    unit = get_unit_or_404(unit_id)
    if unit["status"] == "EXCLUDED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "unit already EXCLUDED")
    if unit["status"] not in ("REGISTERED", "CLEARING"):
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "exclude requires REGISTERED or CLEARING")
    unit["status"] = "EXCLUDED"
    services.touch(unit)
    acq = unit_acquisition(unit)
    if acq is not None:
        services.recompute_acquisition(acq)
    return success_object(serialize(unit), 200)


# ===========================================================================
# Lease files
# ===========================================================================

@app.route("/acquisitions/lease-files", methods=["POST"])
def create_lease_file():
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    data = body()
    unit_id = require_field(data, "unit_id")
    unit = get_unit_or_404(unit_id)
    acq = unit_acquisition(unit)
    if acq is not None:
        _reject_terminal_acquisition(acq)
    resident_name = require_str(require_field(data, "resident_name"), "resident_name")
    lease_start = require_field(data, "lease_start_date")
    lease_end = require_field(data, "lease_end_date")
    parse_date_range(lease_start, lease_end, "lease_start_date", "lease_end_date")
    contract_rent = require_int(require_field(data, "contract_rent_cents"), "contract_rent_cents", non_negative=True)
    term_months = require_int(require_field(data, "term_months"), "term_months", non_negative=True)
    deposit_amount = require_int(require_field(data, "deposit_amount_cents"), "deposit_amount_cents", non_negative=True)
    supersedes_id = opt_field(data, "supersedes_lease_id")

    current = services.current_lease(unit_id)
    if current is not None:
        if supersedes_id is None:
            raise_error(E.ERR_ACTIVE_LEASE_EXISTS, "unit already has a current lease")
        if supersedes_id not in db.lease_files:
            raise_error(E.ERR_LEASE_FILE_NOT_FOUND, "supersedes_lease_id not found")
        if supersedes_id != current["id"]:
            raise_error(E.ERR_SUPERSEDE_TARGET_NOT_CURRENT, "supersedes_lease_id does not name the unit's current lease")
    elif supersedes_id is not None:
        if supersedes_id not in db.lease_files:
            raise_error(E.ERR_LEASE_FILE_NOT_FOUND, "supersedes_lease_id not found")
        raise_error(E.ERR_SUPERSEDE_TARGET_NOT_CURRENT, "supersedes_lease_id does not name the unit's current lease")

    lid = db.new_id()
    ts = db.now_iso()
    lease = {
        "id": lid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "unit_id": unit_id,
        "resident_name": resident_name,
        "lease_start_date": lease_start,
        "lease_end_date": lease_end,
        "contract_rent_cents": contract_rent,
        "term_months": term_months,
        "deposit_amount_cents": deposit_amount,
        "supersedes_lease_id": supersedes_id,
        "status": "UPLOADED",
        "variance_cents": None,
        "audit_result": "PENDING",
        "net_effective_rent_cents": None,
        "waived_variance_cents": 0,
    }
    services.recompute_net_effective_rent(lease)
    db.lease_files[lid] = lease

    if current is not None:
        old_status = current["status"]
        current["status"] = "SUPERSEDED"
        services.touch(current)

    services.recompute_unit(unit)
    return success_object(serialize(lease), 201)


@app.route("/acquisitions/lease-files", methods=["GET"])
def list_lease_files():
    get_caller()
    items = list(db.lease_files.values())
    unit_filter = request.args.get("unit_id")
    status_filter = request.args.get("status")
    supersedes_filter = request.args.get("supersedes_lease_id")
    if unit_filter:
        items = [l for l in items if l["unit_id"] == unit_filter]
    if status_filter:
        items = [l for l in items if l["status"] == status_filter]
    if supersedes_filter:
        items = [l for l in items if l.get("supersedes_lease_id") == supersedes_filter]
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    return paginate([serialize(l) for l in items])


@app.route("/acquisitions/lease-files/<lease_id>", methods=["GET"])
def get_lease(lease_id):
    get_caller()
    lease = get_lease_or_404(lease_id)
    return success_object(serialize(lease), 200)


@app.route("/acquisitions/units/<unit_id>/lease-files", methods=["GET"])
def list_unit_lease_files(unit_id):
    get_caller()
    unit = get_unit_or_404(unit_id)
    items = [l for l in db.lease_files.values() if l["unit_id"] == unit_id]
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    return paginate([serialize(l) for l in items])


@app.route("/acquisitions/lease-files/<lease_id>/audit", methods=["POST"])
def audit_lease(lease_id):
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    lease = get_lease_or_404(lease_id)
    if lease["status"] != "UPLOADED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "audit requires UPLOADED")
    unit = get_unit_or_404(lease["unit_id"])
    acq = unit_acquisition(unit)
    # Find rent roll entry
    entry = None
    for e in db.rent_roll_entries.values():
        if e["unit_id"] == unit["id"]:
            entry = e
            break
    if entry is None:
        raise_error(E.ERR_RENT_ROLL_ENTRY_MISSING, "no rent roll entry for the unit")
    variance = entry["reported_rent_cents"] - lease["contract_rent_cents"]
    lease["variance_cents"] = variance
    if abs(variance) >= services.RENT_VARIANCE_THRESHOLD_CENTS:
        lease["status"] = "DISCREPANCY_FLAGGED"
        entry["verification_status"] = "MISMATCHED"
        lease["audit_result"] = "OVERSTATED" if entry["reported_rent_cents"] > lease["contract_rent_cents"] else "UNDERSTATED"
    else:
        lease["status"] = "AUDITED"
        entry["verification_status"] = "VERIFIED"
        lease["audit_result"] = "MATCH"
    services.touch(lease)
    services.recompute_unit(unit)
    return success_object(serialize(lease), 200)


@app.route("/acquisitions/lease-files/<lease_id>/flag", methods=["POST"])
def flag_lease(lease_id):
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    lease = get_lease_or_404(lease_id)
    if lease["status"] not in ("AUDITED", "RESOLVED"):
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "flag requires AUDITED or RESOLVED")
    data = body()
    require_str(require_field(data, "reason"), "reason")
    lease["status"] = "DISCREPANCY_FLAGGED"
    # Recompute variance against current contract rent
    services.recompute_lease_variance(lease)
    unit = get_unit_or_404(lease["unit_id"])
    entry = None
    for e in db.rent_roll_entries.values():
        if e["unit_id"] == unit["id"]:
            entry = e
            break
    if entry is not None:
        entry["verification_status"] = "MISMATCHED"
    services.touch(lease)
    services.recompute_unit(unit)
    return success_object(serialize(lease), 200)


@app.route("/acquisitions/lease-files/<lease_id>/resolve", methods=["POST"])
def resolve_lease(lease_id):
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    lease = get_lease_or_404(lease_id)
    if lease["status"] != "DISCREPANCY_FLAGGED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "resolve requires DISCREPANCY_FLAGGED")
    data = body()
    require_str(require_field(data, "resolution_note"), "resolution_note")
    corrected = opt_field(data, "corrected_contract_rent_cents")
    if corrected is not None:
        require_int(corrected, "corrected_contract_rent_cents", non_negative=True)
        lease["contract_rent_cents"] = corrected
        services.recompute_lease_variance(lease)
        services.recompute_net_effective_rent(lease)
    lease["status"] = "RESOLVED"
    unit = get_unit_or_404(lease["unit_id"])
    entry = None
    for e in db.rent_roll_entries.values():
        if e["unit_id"] == unit["id"]:
            entry = e
            break
    if entry is not None:
        entry["verification_status"] = "VERIFIED"
    services.touch(lease)
    services.recompute_unit(unit)
    return success_object(serialize(lease), 200)


@app.route("/acquisitions/lease-files/<lease_id>/waive", methods=["POST"])
def waive_lease(lease_id):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    lease = get_lease_or_404(lease_id)
    if lease["status"] != "DISCREPANCY_FLAGGED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "waive requires DISCREPANCY_FLAGGED")
    data = body()
    require_str(require_field(data, "waiver_note"), "waiver_note")
    lease["waived_variance_cents"] = lease.get("variance_cents") or 0
    lease["status"] = "WAIVED"
    services.touch(lease)
    unit = get_unit_or_404(lease["unit_id"])
    services.recompute_unit(unit)
    return success_object(serialize(lease), 200)


# ===========================================================================
# Rent roll entries
# ===========================================================================

@app.route("/acquisitions/rent-roll-entries", methods=["POST"])
def create_rent_roll_entry():
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    data = body()
    unit_id = require_field(data, "unit_id")
    unit = get_unit_or_404(unit_id)
    acq = unit_acquisition(unit)
    if acq is not None:
        _reject_terminal_acquisition(acq)
    resident_name = require_str(require_field(data, "reported_resident_name"), "reported_resident_name")
    reported_rent = require_int(require_field(data, "reported_rent_cents"), "reported_rent_cents", non_negative=True)
    reported_concession = require_int(require_field(data, "reported_concession_cents"), "reported_concession_cents", non_negative=True)
    reported_deposit = require_int(require_field(data, "reported_deposit_cents"), "reported_deposit_cents", non_negative=True)
    move_in = require_field(data, "move_in_date")
    parse_iso_field(move_in, "move_in_date")
    for e in db.rent_roll_entries.values():
        if e["unit_id"] == unit_id:
            raise_error(E.ERR_RENT_ROLL_ENTRY_EXISTS, "rent roll entry already exists for this unit")
    rid = db.new_id()
    entry = {
        "id": rid,
        "created_at": db.now_iso(),
        "unit_id": unit_id,
        "reported_resident_name": resident_name,
        "reported_rent_cents": reported_rent,
        "reported_concession_cents": reported_concession,
        "reported_deposit_cents": reported_deposit,
        "move_in_date": move_in,
        "verification_status": "UNVERIFIED",
    }
    db.rent_roll_entries[rid] = entry
    return success_object(serialize(entry), 201)


@app.route("/acquisitions/units/<unit_id>/rent-roll-entries", methods=["GET"])
def list_unit_rent_roll_entries(unit_id):
    get_caller()
    get_unit_or_404(unit_id)
    items = [e for e in db.rent_roll_entries.values() if e["unit_id"] == unit_id]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    return paginate([serialize(e) for e in items])


# ===========================================================================
# Concessions
# ===========================================================================

CONCESSION_TYPES = ["RECURRING_MONTHLY", "ONE_TIME_CREDIT", "FREE_MONTH_AMORTIZED"]


@app.route("/acquisitions/concessions", methods=["POST"])
def create_concession():
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    data = body()
    lease_file_id = require_field(data, "lease_file_id")
    lease = get_lease_or_404(lease_file_id)
    ctype = require_enum(require_field(data, "concession_type"), CONCESSION_TYPES, "concession_type")
    value = require_int(require_field(data, "value_cents"), "value_cents", non_negative=True)
    start = require_field(data, "coverage_start_date")
    end = require_field(data, "coverage_end_date")
    s_dt, e_dt = parse_date_range(start, end, "coverage_start_date", "coverage_end_date")
    # overlap with sibling PENDING/VERIFIED concessions (closed intervals)
    for c in db.concessions.values():
        if c["lease_file_id"] != lease_file_id:
            continue
        if c["verification_status"] not in ("PENDING", "VERIFIED"):
            continue
        cs = clock.parse_iso(c["coverage_start_date"]).date()
        ce = clock.parse_iso(c["coverage_end_date"]).date()
        ns = s_dt.date()
        ne = e_dt.date()
        # closed-interval overlap: share at least one day
        if ns <= ce and cs <= ne:
            raise_error(E.ERR_CONCESSION_OVERLAP, "concession coverage overlaps an existing concession")
    cid = db.new_id()
    ts = db.now_iso()
    concession = {
        "id": cid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "lease_file_id": lease_file_id,
        "concession_type": ctype,
        "value_cents": value,
        "coverage_start_date": start,
        "coverage_end_date": end,
        "verification_status": "PENDING",
        "verified_value_cents": None,
    }
    db.concessions[cid] = concession
    acq = lease_acquisition(lease)
    if acq is not None:
        services.recompute_acquisition(acq)
    return success_object(serialize(concession), 201)


@app.route("/acquisitions/lease-files/<lease_id>/concessions", methods=["GET"])
def list_lease_concessions(lease_id):
    get_caller()
    get_lease_or_404(lease_id)
    items = [c for c in db.concessions.values() if c["lease_file_id"] == lease_id]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    return paginate([serialize(c) for c in items])


@app.route("/acquisitions/concessions/<cid>/verify", methods=["POST"])
def verify_concession(cid):
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    c = get_concession_or_404(cid)
    if c["verification_status"] != "PENDING":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "verify requires PENDING")
    data = body()
    verified_value = require_int(require_field(data, "verified_value_cents"), "verified_value_cents", non_negative=True)
    c["verified_value_cents"] = verified_value
    c["verification_status"] = "VERIFIED"
    services.touch(c)
    lease = get_lease_or_404(c["lease_file_id"])
    services.recompute_net_effective_rent(lease)
    services.touch(lease)
    acq = lease_acquisition(lease)
    if acq is not None:
        services.recompute_acquisition(acq)
    return success_object(serialize(c), 200)


@app.route("/acquisitions/concessions/<cid>/reject", methods=["POST"])
def reject_concession(cid):
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    c = get_concession_or_404(cid)
    if c["verification_status"] != "PENDING":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "reject requires PENDING")
    c["verification_status"] = "REJECTED"
    services.touch(c)
    lease = get_lease_or_404(c["lease_file_id"])
    services.recompute_net_effective_rent(lease)
    services.touch(lease)
    acq = lease_acquisition(lease)
    if acq is not None:
        services.recompute_acquisition(acq)
    return success_object(serialize(c), 200)


# ===========================================================================
# Inspections
# ===========================================================================

@app.route("/acquisitions/inspections", methods=["POST"])
def create_inspection():
    user_id, role = get_caller()
    require_role(role, ["PropertyOperationsLead"])
    data = body()
    unit_id = require_field(data, "unit_id")
    unit = get_unit_or_404(unit_id)
    acq = unit_acquisition(unit)
    if acq is not None:
        _reject_terminal_acquisition(acq)
    inspector_ref = require_str(require_field(data, "inspector_ref"), "inspector_ref")
    walk_start = require_field(data, "walk_start")
    walk_end = require_field(data, "walk_end")
    ws, we = parse_date_range(walk_start, walk_end, "walk_start", "walk_end")
    if we <= ws:
        raise_error(E.ERR_INVALID_DATE_RANGE, "walk_end must be after walk_start")
    # overlap check: half-open [ws, we) against other non-terminal inspections of same inspector
    for i in db.inspections.values():
        if i["inspector_ref"] != inspector_ref:
            continue
        if i["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        is_start = clock.parse_iso(i["walk_start"])
        is_end = clock.parse_iso(i["walk_end"])
        # overlap iff ws < is_end AND is_start < we
        if ws < is_end and is_start < we:
            raise_error(E.ERR_INSPECTOR_DOUBLE_BOOKED, "inspector window overlaps an existing inspection")
    iid = db.new_id()
    ts = db.now_iso()
    insp = {
        "id": iid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "unit_id": unit_id,
        "inspector_ref": inspector_ref,
        "walk_start": walk_start,
        "walk_end": walk_end,
        "condition_rating": None,
        "no_findings_declared": None,
        "completed_by_user_id": None,
        "reschedule_count": 0,
        "status": "SCHEDULED",
    }
    db.inspections[iid] = insp
    return success_object(serialize(insp), 201)


@app.route("/acquisitions/inspections/<iid>", methods=["GET"])
def get_inspection(iid):
    get_caller()
    insp = get_inspection_or_404(iid)
    return success_object(serialize(insp), 200)


@app.route("/acquisitions/units/<unit_id>/inspections", methods=["GET"])
def list_unit_inspections(unit_id):
    get_caller()
    get_unit_or_404(unit_id)
    items = [i for i in db.inspections.values() if i["unit_id"] == unit_id]
    items.sort(key=lambda i: (i["created_at"], i["id"]))
    return paginate([serialize(i) for i in items])


@app.route("/acquisitions/inspections/<iid>/complete", methods=["POST"])
def complete_inspection(iid):
    user_id, role = get_caller()
    require_role(role, ["PropertyOperationsLead"])
    insp = get_inspection_or_404(iid)
    if insp["status"] != "SCHEDULED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "complete requires SCHEDULED")
    data = body()
    rating = require_int(require_field(data, "condition_rating"), "condition_rating")
    if rating < 1 or rating > 5:
        raise_error(E.ERR_INVALID_REQUEST, "condition_rating must be 1-5")
    no_findings = require_bool(require_field(data, "no_findings_declared"), "no_findings_declared")
    insp["condition_rating"] = rating
    insp["no_findings_declared"] = no_findings
    insp["completed_by_user_id"] = user_id
    insp["status"] = "COMPLETED"
    services.touch(insp)
    return success_object(serialize(insp), 200)


@app.route("/acquisitions/inspections/<iid>/qa-accept", methods=["POST"])
def qa_accept_inspection(iid):
    user_id, role = get_caller()
    require_role(role, ["PropertyOperationsLead"])
    insp = get_inspection_or_404(iid)
    if insp["status"] != "COMPLETED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "qa-accept requires COMPLETED")
    if user_id == insp.get("completed_by_user_id"):
        raise_error(E.ERR_SOD_VIOLATION, "QA caller must differ from completer")
    if insp.get("no_findings_declared") is False:
        has_finding = any(f["inspection_id"] == iid for f in db.findings.values())
        if not has_finding:
            raise_error(E.ERR_FINDINGS_REQUIRED, "at least one finding is required")
    insp["status"] = "QA_ACCEPTED"
    services.touch(insp)
    # Cascade: OPEN findings -> VERIFIED
    unit = get_unit_or_404(insp["unit_id"])
    acq = unit_acquisition(unit)
    for f in db.findings.values():
        if f["inspection_id"] == iid and f["status"] == "OPEN":
            f["status"] = "VERIFIED"
            if acq is not None:
                f["verified_cost_cents"] = services.compute_verified_cost(acq, f)
            services.touch(f)
    services.recompute_unit(unit)
    return success_object(serialize(insp), 200)


@app.route("/acquisitions/inspections/<iid>/qa-reject", methods=["POST"])
def qa_reject_inspection(iid):
    user_id, role = get_caller()
    require_role(role, ["PropertyOperationsLead"])
    insp = get_inspection_or_404(iid)
    if insp["status"] != "COMPLETED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "qa-reject requires COMPLETED")
    data = body()
    require_str(require_field(data, "reason"), "reason")
    if user_id == insp.get("completed_by_user_id"):
        raise_error(E.ERR_SOD_VIOLATION, "QA caller must differ from completer")
    insp["status"] = "QA_REJECTED"
    services.touch(insp)
    unit = get_unit_or_404(insp["unit_id"])
    acq = unit_acquisition(unit)
    if acq is not None:
        services.recompute_acquisition(acq)
    return success_object(serialize(insp), 200)


@app.route("/acquisitions/inspections/<iid>/reschedule", methods=["POST"])
def reschedule_inspection(iid):
    user_id, role = get_caller()
    require_role(role, ["PropertyOperationsLead"])
    insp = get_inspection_or_404(iid)
    if insp["status"] != "QA_REJECTED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "reschedule requires QA_REJECTED")
    data = body()
    walk_start = require_field(data, "walk_start")
    walk_end = require_field(data, "walk_end")
    ws, we = parse_date_range(walk_start, walk_end, "walk_start", "walk_end")
    if we <= ws:
        raise_error(E.ERR_INVALID_DATE_RANGE, "walk_end must be after walk_start")
    # overlap check again
    for i in db.inspections.values():
        if i["id"] == iid:
            continue
        if i["inspector_ref"] != insp["inspector_ref"]:
            continue
        if i["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        is_start = clock.parse_iso(i["walk_start"])
        is_end = clock.parse_iso(i["walk_end"])
        if ws < is_end and is_start < we:
            raise_error(E.ERR_INSPECTOR_DOUBLE_BOOKED, "inspector window overlaps an existing inspection")
    insp["walk_start"] = walk_start
    insp["walk_end"] = walk_end
    insp["status"] = "SCHEDULED"
    insp["reschedule_count"] = (insp.get("reschedule_count") or 0) + 1
    insp["condition_rating"] = None
    insp["no_findings_declared"] = None
    insp["completed_by_user_id"] = None
    services.touch(insp)
    unit = get_unit_or_404(insp["unit_id"])
    acq = unit_acquisition(unit)
    if acq is not None:
        services.recompute_acquisition(acq)
    return success_object(serialize(insp), 200)


# ===========================================================================
# Findings
# ===========================================================================

FINDING_CATEGORIES = ["LIFE_SAFETY", "MAJOR_SYSTEMS", "CODE_COMPLIANCE", "COSMETIC"]


@app.route("/acquisitions/findings", methods=["POST"])
def create_finding():
    user_id, role = get_caller()
    require_role(role, ["PropertyOperationsLead"])
    data = body()
    inspection_id = require_field(data, "inspection_id")
    insp = get_inspection_or_404(inspection_id)
    category = require_enum(require_field(data, "category"), FINDING_CATEGORIES, "category")
    severity = require_int(require_field(data, "severity"), "severity")
    if severity < 1 or severity > 5:
        raise_error(E.ERR_INVALID_REQUEST, "severity must be 1-5")
    seller_est = require_int(require_field(data, "seller_estimate_cents"), "seller_estimate_cents", non_negative=True)
    inspector_est = require_int(require_field(data, "inspector_estimate_cents"), "inspector_estimate_cents", non_negative=True)
    if insp["status"] != "COMPLETED":
        raise_error(E.ERR_INSPECTION_NOT_COMPLETED, "findings may only be recorded on a COMPLETED inspection")
    fid = db.new_id()
    ts = db.now_iso()
    finding = {
        "id": fid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "inspection_id": inspection_id,
        "category": category,
        "severity": severity,
        "seller_estimate_cents": seller_est,
        "inspector_estimate_cents": inspector_est,
        "verified_cost_cents": None,
        "status": "OPEN",
    }
    db.findings[fid] = finding
    return success_object(serialize(finding), 201)


@app.route("/acquisitions/inspections/<iid>/findings", methods=["GET"])
def list_inspection_findings(iid):
    get_caller()
    get_inspection_or_404(iid)
    items = [f for f in db.findings.values() if f["inspection_id"] == iid]
    items.sort(key=lambda f: (f["created_at"], f["id"]))
    return paginate([serialize(f) for f in items])


@app.route("/acquisitions/findings/<fid>/verify", methods=["POST"])
def verify_finding(fid):
    user_id, role = get_caller()
    require_role(role, ["PropertyOperationsLead"])
    f = get_finding_or_404(fid)
    if f["status"] not in ("OPEN", "DISPUTED"):
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "verify requires OPEN or DISPUTED")
    insp = get_inspection_or_404(f["inspection_id"])
    unit = get_unit_or_404(insp["unit_id"])
    acq = unit_acquisition(unit)
    if acq is not None:
        f["verified_cost_cents"] = services.compute_verified_cost(acq, f)
    f["status"] = "VERIFIED"
    services.touch(f)
    if acq is not None:
        services.recompute_acquisition(acq)
    return success_object(serialize(f), 200)


@app.route("/acquisitions/findings/<fid>/dispute", methods=["POST"])
def dispute_finding(fid):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    f = get_finding_or_404(fid)
    if f["status"] != "VERIFIED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "dispute requires VERIFIED")
    data = body()
    require_str(require_field(data, "reason"), "reason")
    f["status"] = "DISPUTED"
    services.touch(f)
    insp = get_inspection_or_404(f["inspection_id"])
    unit = get_unit_or_404(insp["unit_id"])
    acq = unit_acquisition(unit)
    if acq is not None:
        services.recompute_acquisition(acq)
    return success_object(serialize(f), 200)


@app.route("/acquisitions/findings/<fid>/exclude", methods=["POST"])
def exclude_finding(fid):
    user_id, role = get_caller()
    require_role(role, ["PropertyOperationsLead"])
    f = get_finding_or_404(fid)
    if f["status"] not in ("OPEN", "DISPUTED"):
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "exclude requires OPEN or DISPUTED")
    data = body()
    require_str(require_field(data, "reason"), "reason")
    f["status"] = "EXCLUDED"
    services.touch(f)
    insp = get_inspection_or_404(f["inspection_id"])
    unit = get_unit_or_404(insp["unit_id"])
    acq = unit_acquisition(unit)
    if acq is not None:
        services.recompute_acquisition(acq)
    return success_object(serialize(f), 200)


# ===========================================================================
# Utility records & expense summary
# ===========================================================================

UTILITY_CATEGORIES = ["ELECTRIC", "GAS", "WATER_SEWER", "TRASH", "OTHER"]
UTILITY_SOURCES = ["SELLER_T12", "BILL_AUDIT", "ESTIMATE"]


@app.route("/acquisitions/utility-records", methods=["POST"])
def create_utility_record():
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    data = body()
    acquisition_id = require_field(data, "acquisition_id")
    acq = get_acquisition_or_404(acquisition_id)
    _reject_terminal_acquisition(acq)
    period_month = require_str(require_field(data, "period_month"), "period_month")
    category = require_enum(require_field(data, "category"), UTILITY_CATEGORIES, "category")
    amount = require_int(require_field(data, "amount_cents"), "amount_cents", non_negative=True)
    source = require_enum(require_field(data, "source"), UTILITY_SOURCES, "source")
    for r in db.utility_records.values():
        if (r["acquisition_id"] == acquisition_id
                and r["period_month"] == period_month
                and r["category"] == category):
            raise_error(E.ERR_UTILITY_RECORD_EXISTS, "a record exists for this (acquisition, period_month, category)")
    rid = db.new_id()
    ts = db.now_iso()
    record = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "acquisition_id": acquisition_id,
        "period_month": period_month,
        "category": category,
        "amount_cents": amount,
        "source": source,
        "is_outlier": False,
        "normalized_amount_cents": amount,
    }
    db.utility_records[rid] = record
    services.compute_utility_outlier(acquisition_id, record)
    return success_object(serialize(record), 201)


@app.route("/acquisitions/utility-records", methods=["GET"])
def list_utility_records():
    get_caller()
    items = list(db.utility_records.values())
    acq_filter = request.args.get("acquisition_id")
    cat_filter = request.args.get("category")
    month_filter = request.args.get("period_month")
    if acq_filter:
        items = [r for r in items if r["acquisition_id"] == acq_filter]
    if cat_filter:
        items = [r for r in items if r["category"] == cat_filter]
    if month_filter:
        items = [r for r in items if r["period_month"] == month_filter]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    return paginate([serialize(r) for r in items])


@app.route("/acquisitions/utility-records/<rid>", methods=["GET"])
def get_utility_record(rid):
    get_caller()
    r = get_utility_record_or_404(rid)
    return success_object(serialize(r), 200)


@app.route("/acquisitions/<acq_id>/expense-summary", methods=["GET"])
def get_expense_summary(acq_id):
    get_caller()
    get_acquisition_or_404(acq_id)
    summary = services.expense_summary(acq_id)
    return success_object(summary, 200)


# ===========================================================================
# Tax reassessment projections
# ===========================================================================

TAX_METHODS = ["PURCHASE_PRICE_ANCHORED", "INCOME_APPROACH"]


@app.route("/acquisitions/<acq_id>/tax-projections", methods=["POST"])
def create_tax_projection(acq_id):
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    acq = get_acquisition_or_404(acq_id)
    _reject_terminal_acquisition(acq)
    data = body()
    method = require_enum(require_field(data, "method"), TAX_METHODS, "method")
    cap_rate = opt_field(data, "cap_rate")
    noi_t12 = opt_field(data, "noi_t12_cents")
    if method == "INCOME_APPROACH":
        if cap_rate is None:
            raise_error(E.ERR_INVALID_REQUEST, "cap_rate required for INCOME_APPROACH")
        if noi_t12 is None:
            raise_error(E.ERR_INVALID_REQUEST, "noi_t12_cents required for INCOME_APPROACH")
        require_int(noi_t12, "noi_t12_cents", non_negative=True)
    expected_version = require_field(data, "expected_acquisition_version")
    require_int(expected_version, "expected_acquisition_version")
    if expected_version != acq["version"]:
        raise_error(E.ERR_STALE_VERSION, "expected_acquisition_version does not match current version")

    # Supersede any currently APPROVED projection
    for p in db.tax_projections.values():
        if p["acquisition_id"] == acq_id and p["status"] == "APPROVED":
            p["status"] = "SUPERSEDED"
            services.touch(p)

    pid = db.new_id()
    ts = db.now_iso()
    proj = {
        "id": pid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "acquisition_id": acq_id,
        "method": method,
        "cap_rate": cap_rate,
        "noi_t12_cents": noi_t12,
        "status": "DRAFT",
        "projected_value_cents": None,
        "projected_assessed_value_cents": None,
        "projected_annual_tax_cents": None,
        "delta_vs_prior_cents": None,
    }
    db.tax_projections[pid] = proj
    # create increments acquisition version by 1
    services.touch(acq)
    return success_object(serialize(proj), 201)


@app.route("/acquisitions/tax-projections", methods=["GET"])
def list_tax_projections():
    get_caller()
    items = list(db.tax_projections.values())
    acq_filter = request.args.get("acquisition_id")
    status_filter = request.args.get("status")
    if acq_filter:
        items = [p for p in items if p["acquisition_id"] == acq_filter]
    if status_filter:
        items = [p for p in items if p["status"] == status_filter]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    return paginate([serialize(p) for p in items])


@app.route("/acquisitions/tax-projections/<pid>", methods=["GET"])
def get_tax_projection(pid):
    get_caller()
    p = get_tax_projection_or_404(pid)
    return success_object(serialize(p), 200)


@app.route("/acquisitions/tax-projections/<pid>/compute", methods=["POST"])
def compute_tax_projection_endpoint(pid):
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    p = get_tax_projection_or_404(pid)
    if p["status"] != "DRAFT":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "compute requires DRAFT")
    acq = get_acquisition_or_404(p["acquisition_id"])
    services.compute_tax_projection(acq, p)
    p["status"] = "COMPUTED"
    services.touch(p)
    return success_object(serialize(p), 200)


@app.route("/acquisitions/tax-projections/<pid>/approve", methods=["POST"])
def approve_tax_projection(pid):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    p = get_tax_projection_or_404(pid)
    if p["status"] != "COMPUTED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "approve requires COMPUTED")
    # supersede other APPROVED projections of the same acquisition
    for other in db.tax_projections.values():
        if other["acquisition_id"] == p["acquisition_id"] and other["id"] != p["id"] and other["status"] == "APPROVED":
            other["status"] = "SUPERSEDED"
            services.touch(other)
    p["status"] = "APPROVED"
    services.touch(p)
    return success_object(serialize(p), 200)


@app.route("/acquisitions/tax-projections/<pid>/revise", methods=["POST"])
def revise_tax_projection(pid):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    p = get_tax_projection_or_404(pid)
    if p["status"] != "COMPUTED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "revise requires COMPUTED")
    p["status"] = "DRAFT"
    p["projected_value_cents"] = None
    p["projected_assessed_value_cents"] = None
    p["projected_annual_tax_cents"] = None
    p["delta_vs_prior_cents"] = None
    services.touch(p)
    return success_object(serialize(p), 200)


# ===========================================================================
# Deposits
# ===========================================================================

@app.route("/acquisitions/deposits", methods=["POST"])
def create_deposit():
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    data = body()
    lease_file_id = require_field(data, "lease_file_id")
    lease = get_lease_or_404(lease_file_id)
    acq = lease_acquisition(lease)
    if acq is not None:
        _reject_terminal_acquisition(acq)
    seller_stated = require_int(require_field(data, "seller_stated_amount_cents"), "seller_stated_amount_cents", non_negative=True)
    interest_required = require_bool(require_field(data, "interest_required"), "interest_required")
    annual_rate = opt_field(data, "annual_interest_rate", 0)
    did = db.new_id()
    ts = db.now_iso()
    entry = {
        "id": did,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "lease_file_id": lease_file_id,
        "seller_stated_amount_cents": seller_stated,
        "interest_required": interest_required,
        "annual_interest_rate": annual_rate,
        "verified_amount_cents": None,
        "accrued_interest_cents": None,
        "variance_cents": None,
        "status": "RECORDED",
    }
    db.deposits[did] = entry
    return success_object(serialize(entry), 201)


@app.route("/acquisitions/lease-files/<lease_id>/deposits", methods=["GET"])
def list_lease_deposits(lease_id):
    get_caller()
    get_lease_or_404(lease_id)
    items = [d for d in db.deposits.values() if d["lease_file_id"] == lease_id]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    return paginate([serialize(d) for d in items])


@app.route("/acquisitions/deposits/<did>/reconcile", methods=["POST"])
def reconcile_deposit(did):
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    entry = get_deposit_or_404(did)
    if entry["status"] != "RECORDED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "reconcile requires RECORDED")
    lease = get_lease_or_404(entry["lease_file_id"])
    if lease["status"] not in ("AUDITED", "RESOLVED", "WAIVED"):
        raise_error(E.ERR_LEASE_NOT_AUDITED, "lease must be AUDITED, RESOLVED, or WAIVED")
    unit = get_unit_or_404(lease["unit_id"])
    acq = unit_acquisition(unit)
    entry["verified_amount_cents"] = lease["deposit_amount_cents"]
    services.compute_deposit_fields(acq, entry)
    if entry["variance_cents"] == 0:
        entry["status"] = "RECONCILED"
    else:
        entry["status"] = "DISPUTED"
    services.touch(entry)
    services.recompute_unit(unit)
    return success_object(serialize(entry), 200)


@app.route("/acquisitions/deposits/<did>/resolve-dispute", methods=["POST"])
def resolve_deposit_dispute(did):
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    entry = get_deposit_or_404(did)
    if entry["status"] != "DISPUTED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "resolve-dispute requires DISPUTED")
    data = body()
    adjusted = require_int(require_field(data, "adjusted_verified_amount_cents"), "adjusted_verified_amount_cents", non_negative=True)
    entry["verified_amount_cents"] = adjusted
    lease = get_lease_or_404(entry["lease_file_id"])
    unit = get_unit_or_404(lease["unit_id"])
    acq = unit_acquisition(unit)
    # recompute accrued interest with new verified amount; reset verified temporarily
    entry["verified_amount_cents"] = adjusted
    services.compute_deposit_fields(acq, entry)
    if entry["variance_cents"] != 0:
        raise_error(E.ERR_DEPOSIT_VARIANCE_UNRESOLVED, "recomputed variance is not zero")
    entry["status"] = "RECONCILED"
    services.touch(entry)
    services.recompute_unit(unit)
    return success_object(serialize(entry), 200)


@app.route("/acquisitions/deposits/<did>/queue-escrow", methods=["POST"])
def queue_escrow_deposit(did):
    user_id, role = get_caller()
    require_role(role, ["EscrowOfficer"])
    entry = get_deposit_or_404(did)
    if entry["status"] != "RECONCILED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "queue-escrow requires RECONCILED")
    lease = get_lease_or_404(entry["lease_file_id"])
    unit = get_unit_or_404(lease["unit_id"])
    acq = unit_acquisition(unit)
    if acq is None or acq["status"] != "PRE_CLOSING":
        raise_error(E.ERR_ACQUISITION_NOT_PRE_CLOSING, "acquisition must be PRE_CLOSING")
    entry["status"] = "ESCROW_QUEUED"
    services.touch(entry)
    return success_object(serialize(entry), 200)


# ===========================================================================
# Employee decisions
# ===========================================================================

DECISION_TYPES = ["RETAIN", "TERMINATE", "TRANSFER"]


@app.route("/acquisitions/employee-decisions", methods=["POST"])
def create_employee_decision():
    user_id, role = get_caller()
    require_role(role, ["HRPartner"])
    data = body()
    acquisition_id = require_field(data, "acquisition_id")
    acq = get_acquisition_or_404(acquisition_id)
    _reject_terminal_acquisition(acq)
    employee_ref = require_str(require_field(data, "employee_ref"), "employee_ref")
    position = require_str(require_field(data, "position"), "position")
    hire_date = require_field(data, "hire_date")
    parse_iso_field(hire_date, "hire_date")
    annual_salary = require_int(require_field(data, "annual_salary_cents"), "annual_salary_cents", non_negative=True)
    accrued_pto = require_field(data, "accrued_pto_hours")
    decision = require_enum(require_field(data, "decision"), DECISION_TYPES, "decision")
    notice_date = require_field(data, "notice_date")
    effective_date = require_field(data, "effective_date")
    parse_iso_field(notice_date, "notice_date")
    parse_iso_field(effective_date, "effective_date")
    required_notice = opt_field(data, "required_notice_days", 14)
    require_int(required_notice, "required_notice_days", non_negative=True)
    did = db.new_id()
    ts = db.now_iso()
    d = {
        "id": did,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "acquisition_id": acquisition_id,
        "employee_ref": employee_ref,
        "position": position,
        "hire_date": hire_date,
        "annual_salary_cents": annual_salary,
        "accrued_pto_hours": accrued_pto,
        "decision": decision,
        "notice_date": notice_date,
        "effective_date": effective_date,
        "required_notice_days": required_notice,
        "proposed_by_user_id": user_id,
        "approved_by_user_id": None,
        "severance_cents": None,
        "pto_payout_cents": None,
        "assumed_pto_liability_cents": None,
        "status": "PROPOSED",
    }
    db.employee_decisions[did] = d
    return success_object(serialize(d), 201)


@app.route("/acquisitions/employee-decisions", methods=["GET"])
def list_employee_decisions():
    get_caller()
    items = list(db.employee_decisions.values())
    acq_filter = request.args.get("acquisition_id")
    status_filter = request.args.get("status")
    if acq_filter:
        items = [d for d in items if d["acquisition_id"] == acq_filter]
    if status_filter:
        items = [d for d in items if d["status"] == status_filter]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    return paginate([serialize(d) for d in items])


@app.route("/acquisitions/employee-decisions/<did>", methods=["GET"])
def get_employee_decision(did):
    get_caller()
    d = get_decision_or_404(did)
    return success_object(serialize(d), 200)


@app.route("/acquisitions/employee-decisions/<did>/approve", methods=["POST"])
def approve_employee_decision(did):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    d = get_decision_or_404(did)
    if d["status"] != "PROPOSED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "approve requires PROPOSED")
    acq = get_acquisition_or_404(d["acquisition_id"])
    if acq["status"] != "IN_DILIGENCE":
        raise_error(E.ERR_ACQUISITION_NOT_IN_DILIGENCE, "acquisition must be IN_DILIGENCE")
    if user_id == d.get("proposed_by_user_id"):
        raise_error(E.ERR_SOD_VIOLATION, "approver must differ from proposer")
    notice_dt = clock.parse_iso(d["notice_date"])
    effective_dt = clock.parse_iso(d["effective_date"])
    if clock.calendar_days_between(notice_dt, effective_dt) < d["required_notice_days"]:
        raise_error(E.ERR_NOTICE_PERIOD_INSUFFICIENT, "notice period is insufficient")
    services.compute_compensation(d)
    d["approved_by_user_id"] = user_id
    d["status"] = "APPROVED"
    services.touch(d)
    services.recompute_payroll_accrual(acq)
    return success_object(serialize(d), 200)


@app.route("/acquisitions/employee-decisions/<did>/reject", methods=["POST"])
def reject_employee_decision(did):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    d = get_decision_or_404(did)
    if d["status"] != "PROPOSED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "reject requires PROPOSED")
    d["status"] = "REJECTED"
    services.touch(d)
    return success_object(serialize(d), 200)


@app.route("/acquisitions/employee-decisions/<did>/notify", methods=["POST"])
def notify_employee_decision(did):
    user_id, role = get_caller()
    require_role(role, ["HRPartner"])
    d = get_decision_or_404(did)
    if d["status"] != "APPROVED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "notify requires APPROVED")
    d["status"] = "NOTIFIED"
    services.touch(d)
    return success_object(serialize(d), 200)


@app.route("/acquisitions/employee-decisions/<did>/mark-effective", methods=["POST"])
def mark_effective_employee_decision(did):
    user_id, role = get_caller()
    require_role(role, ["HRPartner"])
    d = get_decision_or_404(did)
    if d["status"] != "NOTIFIED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "mark-effective requires NOTIFIED")
    now = clock.now_clock_dt()
    eff = clock.parse_iso(d["effective_date"])
    if now < eff:
        raise_error(E.ERR_NOT_YET_EFFECTIVE, "effective_date not yet reached")
    d["status"] = "EFFECTIVE"
    services.touch(d)
    acq = db.acquisitions.get(d["acquisition_id"])
    if acq is not None:
        services.recompute_payroll_accrual(acq)
    return success_object(serialize(d), 200)


@app.route("/acquisitions/employee-decisions/<did>/rescind", methods=["POST"])
def rescind_employee_decision(did):
    user_id, role = get_caller()
    require_role(role, ["HRPartner"])
    d = get_decision_or_404(did)
    if d["status"] not in ("APPROVED", "NOTIFIED"):
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "rescind requires APPROVED or NOTIFIED")
    d["status"] = "RESCINDED"
    services.touch(d)
    acq = db.acquisitions.get(d["acquisition_id"])
    if acq is not None:
        services.recompute_payroll_accrual(acq)
    return success_object(serialize(d), 200)


# ===========================================================================
# Service contracts
# ===========================================================================

SERVICE_TYPES = ["ELEVATOR", "LAUNDRY", "LANDSCAPING", "PEST_CONTROL", "SECURITY", "OTHER"]


@app.route("/acquisitions/service-contracts", methods=["POST"])
def create_service_contract():
    user_id, role = get_caller()
    require_role(role, ["VendorManager"])
    data = body()
    acquisition_id = require_field(data, "acquisition_id")
    acq = get_acquisition_or_404(acquisition_id)
    _reject_terminal_acquisition(acq)
    vendor_name = require_str(require_field(data, "vendor_name"), "vendor_name")
    service_type = require_enum(require_field(data, "service_type"), SERVICE_TYPES, "service_type")
    monthly_cost = require_int(require_field(data, "monthly_cost_cents"), "monthly_cost_cents", non_negative=True)
    term_end = require_field(data, "term_end_date")
    term_end_dt = parse_iso_field(term_end, "term_end_date")
    auto_renew = require_bool(require_field(data, "auto_renew"), "auto_renew")
    notice_days = require_int(require_field(data, "cancellation_notice_days"), "cancellation_notice_days", non_negative=True)
    penalty = require_int(require_field(data, "cancellation_penalty_cents"), "cancellation_penalty_cents", non_negative=True)
    prepaid_through = opt_field(data, "prepaid_through_date")
    if prepaid_through is not None:
        parse_iso_field(prepaid_through, "prepaid_through_date")
    import datetime as _dt
    decision_deadline_dt = term_end_dt - _dt.timedelta(days=notice_days)
    decision_deadline = clock.format_iso(decision_deadline_dt)
    cid = db.new_id()
    ts = db.now_iso()
    contract = {
        "id": cid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "acquisition_id": acquisition_id,
        "vendor_name": vendor_name,
        "service_type": service_type,
        "monthly_cost_cents": monthly_cost,
        "term_end_date": term_end,
        "auto_renew": auto_renew,
        "cancellation_notice_days": notice_days,
        "cancellation_penalty_cents": penalty,
        "prepaid_through_date": prepaid_through,
        "decision_deadline": decision_deadline,
        "cancellation_effective_date": None,
        "status": "IDENTIFIED",
    }
    db.service_contracts[cid] = contract
    return success_object(serialize(contract), 201)


@app.route("/acquisitions/service-contracts", methods=["GET"])
def list_service_contracts():
    get_caller()
    items = list(db.service_contracts.values())
    acq_filter = request.args.get("acquisition_id")
    status_filter = request.args.get("status")
    if acq_filter:
        items = [c for c in items if c["acquisition_id"] == acq_filter]
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    return paginate([serialize(c) for c in items])


@app.route("/acquisitions/service-contracts/<cid>", methods=["GET"])
def get_service_contract(cid):
    get_caller()
    c = get_contract_or_404(cid)
    return success_object(serialize(c), 200)


@app.route("/acquisitions/service-contracts/<cid>/begin-review", methods=["POST"])
def begin_review_contract(cid):
    user_id, role = get_caller()
    require_role(role, ["VendorManager"])
    c = get_contract_or_404(cid)
    if c["status"] != "IDENTIFIED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "begin-review requires IDENTIFIED")
    c["status"] = "UNDER_REVIEW"
    services.touch(c)
    return success_object(serialize(c), 200)


@app.route("/acquisitions/service-contracts/<cid>/assume", methods=["POST"])
def assume_contract(cid):
    user_id, role = get_caller()
    require_role(role, ["VendorManager"])
    c = get_contract_or_404(cid)
    if c["status"] != "UNDER_REVIEW":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "assume requires UNDER_REVIEW")
    c["status"] = "ASSUMED"
    services.touch(c)
    return success_object(serialize(c), 200)


@app.route("/acquisitions/service-contracts/<cid>/send-notice", methods=["POST"])
def send_notice_contract(cid):
    user_id, role = get_caller()
    require_role(role, ["VendorManager"])
    c = get_contract_or_404(cid)
    if c["status"] != "UNDER_REVIEW":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "send-notice requires UNDER_REVIEW")
    data = body()
    cancel_eff = require_field(data, "cancellation_effective_date")
    parse_iso_field(cancel_eff, "cancellation_effective_date")
    # Phase gate
    acq = get_acquisition_or_404(c["acquisition_id"])
    if acq["status"] not in ("IN_DILIGENCE", "DILIGENCE_COMPLETE", "PRE_CLOSING"):
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "acquisition phase does not allow send-notice")
    # Window check: logical clock <= decision_deadline
    now = clock.now_clock_dt()
    dd = clock.parse_iso(c["decision_deadline"])
    if now > dd:
        raise_error(E.ERR_NOTICE_WINDOW_MISSED, "decision deadline has passed")
    c["cancellation_effective_date"] = cancel_eff
    c["status"] = "NOTICE_SENT"
    services.touch(c)
    return success_object(serialize(c), 200)


@app.route("/acquisitions/service-contracts/<cid>/mark-cancelled", methods=["POST"])
def mark_cancelled_contract(cid):
    user_id, role = get_caller()
    require_role(role, ["VendorManager"])
    c = get_contract_or_404(cid)
    if c["status"] != "NOTICE_SENT":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "mark-cancelled requires NOTICE_SENT")
    now = clock.now_clock_dt()
    ced = clock.parse_iso(c["cancellation_effective_date"])
    if now < ced:
        raise_error(E.ERR_CANCELLATION_NOT_YET_EFFECTIVE, "cancellation_effective_date not yet reached")
    c["status"] = "CANCELLED_EFFECTIVE"
    services.touch(c)
    return success_object(serialize(c), 200)


@app.route("/acquisitions/service-contracts/<cid>/renew", methods=["POST"])
def renew_contract(cid):
    user_id, role = get_caller()
    require_role(role, ["VendorManager"])
    c = get_contract_or_404(cid)
    if c["status"] != "UNDER_REVIEW":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "renew requires UNDER_REVIEW")
    c["status"] = "RENEWED"
    services.touch(c)
    return success_object(serialize(c), 200)


# ===========================================================================
# Insurance policies
# ===========================================================================

POLICY_TYPES = ["PROPERTY", "GENERAL_LIABILITY", "UMBRELLA", "FLOOD", "OTHER"]


@app.route("/acquisitions/insurance-policies", methods=["POST"])
def create_insurance_policy():
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    data = body()
    acquisition_id = require_field(data, "acquisition_id")
    acq = get_acquisition_or_404(acquisition_id)
    _reject_terminal_acquisition(acq)
    policy_type = require_enum(require_field(data, "policy_type"), POLICY_TYPES, "policy_type")
    carrier = require_str(require_field(data, "carrier_name"), "carrier_name")
    premium = require_int(require_field(data, "annual_premium_cents"), "annual_premium_cents", non_negative=True)
    expiration = require_field(data, "expiration_date")
    parse_iso_field(expiration, "expiration_date")
    prepaid = require_field(data, "prepaid_through_date")
    parse_iso_field(prepaid, "prepaid_through_date")
    loss_run_total = require_int(require_field(data, "loss_run_total_cents"), "loss_run_total_cents", non_negative=True)
    open_claims = require_int(require_field(data, "open_claims_count"), "open_claims_count", non_negative=True)
    pid = db.new_id()
    ts = db.now_iso()
    policy = {
        "id": pid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "acquisition_id": acquisition_id,
        "policy_type": policy_type,
        "carrier_name": carrier,
        "annual_premium_cents": premium,
        "expiration_date": expiration,
        "prepaid_through_date": prepaid,
        "loss_run_total_cents": loss_run_total,
        "open_claims_count": open_claims,
        "loss_ratio": None,
        "risk_tier": None,
        "status": "DOCUMENTED",
    }
    db.insurance_policies[pid] = policy
    return success_object(serialize(policy), 201)


@app.route("/acquisitions/insurance-policies", methods=["GET"])
def list_insurance_policies():
    get_caller()
    items = list(db.insurance_policies.values())
    acq_filter = request.args.get("acquisition_id")
    status_filter = request.args.get("status")
    if acq_filter:
        items = [p for p in items if p["acquisition_id"] == acq_filter]
    if status_filter:
        items = [p for p in items if p["status"] == status_filter]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    return paginate([serialize(p) for p in items])


@app.route("/acquisitions/insurance-policies/<pid>", methods=["GET"])
def get_insurance_policy(pid):
    get_caller()
    p = get_policy_or_404(pid)
    return success_object(serialize(p), 200)


@app.route("/acquisitions/insurance-policies/<pid>/review-loss-runs", methods=["POST"])
def review_loss_runs(pid):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    p = get_policy_or_404(pid)
    if p["status"] != "DOCUMENTED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "review-loss-runs requires DOCUMENTED")
    services.compute_loss_ratio(p)
    p["status"] = "LOSS_RUNS_REVIEWED"
    services.touch(p)
    return success_object(serialize(p), 200)


@app.route("/acquisitions/insurance-policies/<pid>/assume", methods=["POST"])
def assume_insurance_policy(pid):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    p = get_policy_or_404(pid)
    if p["status"] != "LOSS_RUNS_REVIEWED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "assume requires LOSS_RUNS_REVIEWED")
    data = body()
    override = opt_field(data, "override_high_risk", False)
    if p.get("risk_tier") == "HIGH" and not override:
        raise_error(E.ERR_HIGH_RISK_POLICY_REQUIRES_OVERRIDE, "HIGH risk policy requires override_high_risk=true")
    p["status"] = "ASSUMED"
    services.touch(p)
    return success_object(serialize(p), 200)


@app.route("/acquisitions/insurance-policies/<pid>/exclude", methods=["POST"])
def exclude_insurance_policy(pid):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    p = get_policy_or_404(pid)
    if p["status"] not in ("DOCUMENTED", "LOSS_RUNS_REVIEWED"):
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "exclude requires DOCUMENTED or LOSS_RUNS_REVIEWED")
    p["status"] = "EXCLUDED"
    services.touch(p)
    return success_object(serialize(p), 200)


# ===========================================================================
# Proration statements
# ===========================================================================

STATEMENT_TYPES = ["DRAFT_CLOSING", "FINAL_CLOSING", "POST_CLOSING_TRUEUP"]
DAY_COUNT_METHODS = ["ACTUAL_365", "BANKERS_30_360"]
LINE_TYPES = ["RENT", "TAX", "PREPAID_EXPENSE", "DEPOSIT_TRANSFER", "PAYROLL", "ADJUSTMENT"]
LINE_DIRECTIONS = ["CREDIT_BUYER", "CREDIT_SELLER"]


@app.route("/acquisitions/<acq_id>/proration-statements", methods=["POST"])
def generate_proration_statement(acq_id):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    acq = get_acquisition_or_404(acq_id)
    _reject_terminal_acquisition(acq)
    data = body()
    statement_type = require_enum(require_field(data, "statement_type"), STATEMENT_TYPES, "statement_type")
    day_count_method = require_enum(require_field(data, "day_count_method"), DAY_COUNT_METHODS, "day_count_method")
    expected_version = require_field(data, "expected_acquisition_version")
    require_int(expected_version, "expected_acquisition_version")

    # Phase gate
    phase = acq["status"]
    allowed = False
    if statement_type == "DRAFT_CLOSING" and phase in ("DILIGENCE_COMPLETE", "PRE_CLOSING"):
        allowed = True
    elif statement_type == "FINAL_CLOSING" and phase == "PRE_CLOSING":
        allowed = True
    elif statement_type == "POST_CLOSING_TRUEUP" and phase == "CLOSED":
        allowed = True
    if not allowed:
        raise_error(E.ERR_STATEMENT_TYPE_NOT_ALLOWED_FOR_PHASE,
                    f"{statement_type} not allowed in phase {phase}")

    if expected_version != acq["version"]:
        raise_error(E.ERR_STALE_VERSION, "expected_acquisition_version does not match current version")

    # TAX line requires APPROVED projection — but only when there are any non-EXCLUDED units / data needing tax?
    # The TAX line is conditional on having an approved projection; if missing, generation must fail.
    approved_proj = None
    for p in db.tax_projections.values():
        if p["acquisition_id"] == acq_id and p["status"] == "APPROVED":
            approved_proj = p
            break
    if approved_proj is None:
        raise_error(E.ERR_TAX_PROJECTION_NOT_APPROVED, "an APPROVED TaxReassessmentProjection is required")

    # Supersede cascade: a new FINAL_CLOSING supersedes the APPROVED DRAFT_CLOSING
    if statement_type == "FINAL_CLOSING":
        for s in db.proration_statements.values():
            if s["acquisition_id"] == acq_id and s["statement_type"] == "DRAFT_CLOSING" and s["status"] == "APPROVED":
                s["status"] = "SUPERSEDED"
                services.touch(s)

    sid = db.new_id()
    ts = db.now_iso()
    stmt = {
        "id": sid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "acquisition_id": acq_id,
        "statement_type": statement_type,
        "day_count_method": day_count_method,
        "status": "DRAFT",
        "created_by_user_id": user_id,
        "reviewed_by_user_id": None,
        "approved_by_user_id": None,
        "total_buyer_credits_cents": 0,
        "total_seller_credits_cents": 0,
        "net_amount_cents": 0,
    }
    db.proration_statements[sid] = stmt

    # Generate lines
    lines = services.generate_statement_lines(acq, stmt)
    for line_data in lines:
        lid = db.new_id()
        line = {
            "id": lid,
            "created_at": db.now_iso(),
            "statement_id": sid,
            **line_data,
        }
        db.proration_lines[lid] = line

    services.recompute_statement_totals(stmt)

    # Increment acquisition version
    services.touch(acq)
    return success_object(serialize(stmt), 201)


@app.route("/acquisitions/proration-statements", methods=["GET"])
def list_proration_statements():
    get_caller()
    items = list(db.proration_statements.values())
    acq_filter = request.args.get("acquisition_id")
    status_filter = request.args.get("status")
    type_filter = request.args.get("statement_type")
    if acq_filter:
        items = [s for s in items if s["acquisition_id"] == acq_filter]
    if status_filter:
        items = [s for s in items if s["status"] == status_filter]
    if type_filter:
        items = [s for s in items if s["statement_type"] == type_filter]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    return paginate([serialize(s) for s in items])


@app.route("/acquisitions/proration-statements/<sid>", methods=["GET"])
def get_proration_statement(sid):
    get_caller()
    s = get_statement_or_404(sid)
    return success_object(serialize(s), 200)


@app.route("/acquisitions/proration-statements/<sid>/lines", methods=["POST"])
def append_statement_line(sid):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    stmt = get_statement_or_404(sid)
    if stmt["status"] != "DRAFT":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "lines may only be appended while statement is DRAFT")
    data = body()
    expected_version = require_field(data, "expected_statement_version")
    require_int(expected_version, "expected_statement_version")
    if expected_version != stmt["version"]:
        raise_error(E.ERR_STALE_VERSION, "expected_statement_version does not match current version")
    line_type = require_enum(require_field(data, "line_type"), LINE_TYPES, "line_type")
    direction = require_enum(require_field(data, "direction"), LINE_DIRECTIONS, "direction")
    amount = require_int(require_field(data, "amount_cents"), "amount_cents")
    memo = opt_field(data, "memo")
    lid = db.new_id()
    line = {
        "id": lid,
        "created_at": db.now_iso(),
        "statement_id": sid,
        "line_type": line_type,
        "direction": direction,
        "amount_cents": amount,
        "source_kind": "MANUAL",
        "source_ref_type": None,
        "source_ref_id": None,
        "memo": memo,
    }
    db.proration_lines[lid] = line
    services.recompute_statement_totals(stmt)
    services.touch(stmt)
    return success_object(serialize(line), 201)


@app.route("/acquisitions/proration-statements/<sid>/lines", methods=["GET"])
def list_statement_lines(sid):
    get_caller()
    get_statement_or_404(sid)
    items = [l for l in db.proration_lines.values() if l["statement_id"] == sid]
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    return paginate([serialize(l) for l in items])


@app.route("/acquisitions/proration-statements/<sid>/submit-review", methods=["POST"])
def submit_statement_review(sid):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    stmt = get_statement_or_404(sid)
    if stmt["status"] != "DRAFT":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "submit-review requires DRAFT")
    if user_id == stmt.get("created_by_user_id"):
        raise_error(E.ERR_SOD_VIOLATION, "reviewer must differ from creator")
    stmt["status"] = "REVIEWED"
    stmt["reviewed_by_user_id"] = user_id
    services.touch(stmt)
    return success_object(serialize(stmt), 200)


@app.route("/acquisitions/proration-statements/<sid>/send-back", methods=["POST"])
def send_back_statement(sid):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    stmt = get_statement_or_404(sid)
    if stmt["status"] != "REVIEWED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "send-back requires REVIEWED")
    stmt["status"] = "DRAFT"
    stmt["reviewed_by_user_id"] = None
    services.touch(stmt)
    return success_object(serialize(stmt), 200)


@app.route("/acquisitions/proration-statements/<sid>/approve", methods=["POST"])
def approve_statement(sid):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    stmt = get_statement_or_404(sid)
    if stmt["status"] != "REVIEWED":
        raise_error(E.ERR_STATEMENT_NOT_REVIEWED, "approve requires REVIEWED")
    if user_id == stmt.get("created_by_user_id") or user_id == stmt.get("reviewed_by_user_id"):
        raise_error(E.ERR_SOD_VIOLATION, "approver must differ from creator and reviewer")
    acq = get_acquisition_or_404(stmt["acquisition_id"])
    # Snapshot drift check
    if services.check_statement_drift(acq, stmt):
        raise_error(E.ERR_STATEMENT_DRIFT, "a GENERATED line no longer matches live data")
    # Approved tax projection gate
    approved_proj = None
    for p in db.tax_projections.values():
        if p["acquisition_id"] == acq["id"] and p["status"] == "APPROVED":
            approved_proj = p
            break
    if approved_proj is None:
        raise_error(E.ERR_TAX_PROJECTION_NOT_APPROVED, "an APPROVED TaxReassessmentProjection is required")
    stmt["status"] = "APPROVED"
    stmt["approved_by_user_id"] = user_id
    services.touch(stmt)
    services.recompute_net_proration(acq)
    return success_object(serialize(stmt), 200)


@app.route("/acquisitions/proration-statements/<sid>/settle", methods=["POST"])
def settle_statement(sid):
    user_id, role = get_caller()
    require_role(role, ["EscrowOfficer"])
    stmt = get_statement_or_404(sid)
    if stmt["status"] != "APPROVED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "settle requires APPROVED")
    if stmt["statement_type"] not in ("FINAL_CLOSING", "POST_CLOSING_TRUEUP"):
        raise_error(E.ERR_STATEMENT_NOT_SETTLABLE, "only FINAL_CLOSING or POST_CLOSING_TRUEUP statements are settlable")
    acq = get_acquisition_or_404(stmt["acquisition_id"])
    if acq["status"] != "CLOSED":
        raise_error(E.ERR_ACQUISITION_NOT_CLOSED, "acquisition must be CLOSED")
    stmt["status"] = "SETTLED"
    services.touch(stmt)
    services.recompute_net_proration(acq)
    return success_object(serialize(stmt), 200)


# ===========================================================================
# Post-closing adjustments
# ===========================================================================

ADJUSTMENT_TYPES = ["COLLECTION_LOSS", "TAX_RECALC", "DEPOSIT_SHORTFALL", "EXPENSE_RECON"]
ADJUSTMENT_DIRECTIONS = ["CREDIT_BUYER", "CREDIT_SELLER"]


@app.route("/acquisitions/adjustments", methods=["POST"])
def create_adjustment():
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    data = body()
    acquisition_id = require_field(data, "acquisition_id")
    acq = get_acquisition_or_404(acquisition_id)
    adj_type = require_enum(require_field(data, "adjustment_type"), ADJUSTMENT_TYPES, "adjustment_type")
    amount = require_int(require_field(data, "amount_cents"), "amount_cents", non_negative=True)
    direction = require_enum(require_field(data, "direction"), ADJUSTMENT_DIRECTIONS, "direction")
    # State gate
    if acq["status"] != "CLOSED":
        raise_error(E.ERR_ACQUISITION_NOT_CLOSED, "acquisition must be CLOSED")
    # True-up window check
    now = clock.now_clock_dt()
    closing_dt = clock.parse_iso(acq["closing_executed_at"])
    import datetime as _dt
    window_end = closing_dt + _dt.timedelta(days=acq["true_up_window_days"])
    if now > window_end:
        raise_error(E.ERR_TRUE_UP_WINDOW_EXPIRED, "true-up window has expired")
    aid = db.new_id()
    ts = db.now_iso()
    adj = {
        "id": aid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "acquisition_id": acquisition_id,
        "adjustment_type": adj_type,
        "amount_cents": amount,
        "direction": direction,
        "evidence_note": None,
        "pre_closing_arrears_cents": None,
        "collections_applied_cents": None,
        "resolved_amount_cents": None,
        "asserted_date": clock.get_current_utc(),
        "status": "ASSERTED",
    }
    db.post_closing_adjustments[aid] = adj
    return success_object(serialize(adj), 201)


@app.route("/acquisitions/adjustments", methods=["GET"])
def list_adjustments():
    get_caller()
    items = list(db.post_closing_adjustments.values())
    acq_filter = request.args.get("acquisition_id")
    status_filter = request.args.get("status")
    if acq_filter:
        items = [a for a in items if a["acquisition_id"] == acq_filter]
    if status_filter:
        items = [a for a in items if a["status"] == status_filter]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    return paginate([serialize(a) for a in items])


@app.route("/acquisitions/adjustments/<aid>", methods=["GET"])
def get_adjustment(aid):
    get_caller()
    a = get_adjustment_or_404(aid)
    return success_object(serialize(a), 200)


@app.route("/acquisitions/adjustments/<aid>/evidence", methods=["POST"])
def evidence_adjustment(aid):
    user_id, role = get_caller()
    require_role(role, ["AcquisitionsAnalyst"])
    adj = get_adjustment_or_404(aid)
    if adj["status"] != "ASSERTED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "evidence requires ASSERTED")
    data = body()
    evidence_note = require_str(require_field(data, "evidence_note"), "evidence_note")
    # Optional corrected amount replaces asserted amount BEFORE cap check
    if "amount_cents" in data and data["amount_cents"] is not None:
        new_amount = require_int(data["amount_cents"], "amount_cents", non_negative=True)
        adj["amount_cents"] = new_amount
    # Optional collection inputs
    if "pre_closing_arrears_cents" in data and data["pre_closing_arrears_cents"] is not None:
        adj["pre_closing_arrears_cents"] = require_int(data["pre_closing_arrears_cents"], "pre_closing_arrears_cents", non_negative=True)
    if "collections_applied_cents" in data and data["collections_applied_cents"] is not None:
        adj["collections_applied_cents"] = require_int(data["collections_applied_cents"], "collections_applied_cents", non_negative=True)
    # COLLECTION_LOSS cap check
    if adj["adjustment_type"] == "COLLECTION_LOSS":
        arrears = adj.get("pre_closing_arrears_cents") or 0
        applied = adj.get("collections_applied_cents") or 0
        cap = min(arrears, applied)
        if adj["amount_cents"] > cap:
            raise_error(E.ERR_ADJUSTMENT_EXCEEDS_CLAIMABLE, "amount exceeds min(pre_closing_arrears, collections_applied)")
    adj["evidence_note"] = evidence_note
    adj["status"] = "EVIDENCED"
    services.touch(adj)
    return success_object(serialize(adj), 200)


@app.route("/acquisitions/adjustments/<aid>/accept", methods=["POST"])
def accept_adjustment(aid):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    adj = get_adjustment_or_404(aid)
    if adj["status"] != "EVIDENCED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "accept requires EVIDENCED")
    adj["status"] = "ACCEPTED"
    services.touch(adj)
    return success_object(serialize(adj), 200)


@app.route("/acquisitions/adjustments/<aid>/dispute", methods=["POST"])
def dispute_adjustment(aid):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    adj = get_adjustment_or_404(aid)
    if adj["status"] != "EVIDENCED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "dispute requires EVIDENCED")
    data = body()
    require_str(require_field(data, "reason"), "reason")
    adj["status"] = "DISPUTED"
    services.touch(adj)
    return success_object(serialize(adj), 200)


@app.route("/acquisitions/adjustments/<aid>/resolve", methods=["POST"])
def resolve_adjustment(aid):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    adj = get_adjustment_or_404(aid)
    if adj["status"] != "DISPUTED":
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "resolve requires DISPUTED")
    data = body()
    resolved = require_int(require_field(data, "resolved_amount_cents"), "resolved_amount_cents", non_negative=True)
    adj["resolved_amount_cents"] = resolved
    adj["status"] = "RESOLVED"
    services.touch(adj)
    return success_object(serialize(adj), 200)


@app.route("/acquisitions/adjustments/<aid>/apply", methods=["POST"])
def apply_adjustment(aid):
    user_id, role = get_caller()
    require_role(role, ["UnderwritingManager"])
    adj = get_adjustment_or_404(aid)
    if adj["status"] not in ("ACCEPTED", "RESOLVED"):
        raise_error(E.ERR_INVALID_STATE_TRANSITION, "apply requires ACCEPTED or RESOLVED")
    amount = adj["amount_cents"] if adj["status"] == "ACCEPTED" else adj["resolved_amount_cents"]
    # Find or create DRAFT POST_CLOSING_TRUEUP statement
    trueup = None
    for s in db.proration_statements.values():
        if (s["acquisition_id"] == adj["acquisition_id"]
                and s["statement_type"] == "POST_CLOSING_TRUEUP"
                and s["status"] == "DRAFT"):
            trueup = s
            break
    if trueup is None:
        # Create one; day_count_method copied from the FINAL_CLOSING statement
        final_stmt = None
        for s in db.proration_statements.values():
            if s["acquisition_id"] == adj["acquisition_id"] and s["statement_type"] == "FINAL_CLOSING":
                if final_stmt is None or s["created_at"] > final_stmt["created_at"]:
                    final_stmt = s
        day_count = final_stmt["day_count_method"] if final_stmt is not None else "ACTUAL_365"
        sid = db.new_id()
        ts = db.now_iso()
        trueup = {
            "id": sid,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "acquisition_id": adj["acquisition_id"],
            "statement_type": "POST_CLOSING_TRUEUP",
            "day_count_method": day_count,
            "status": "DRAFT",
            "created_by_user_id": user_id,
            "reviewed_by_user_id": None,
            "approved_by_user_id": None,
            "total_buyer_credits_cents": 0,
            "total_seller_credits_cents": 0,
            "net_amount_cents": 0,
        }
        db.proration_statements[sid] = trueup
    # Append ADJUSTMENT line
    lid = db.new_id()
    line = {
        "id": lid,
        "created_at": db.now_iso(),
        "statement_id": trueup["id"],
        "line_type": "ADJUSTMENT",
        "direction": adj["direction"],
        "amount_cents": amount,
        "source_kind": "GENERATED",
        "source_ref_type": "ADJUSTMENT",
        "source_ref_id": adj["id"],
        "memo": None,
    }
    db.proration_lines[lid] = line
    services.recompute_statement_totals(trueup)
    services.touch(trueup)
    adj["status"] = "APPLIED"
    services.touch(adj)
    return success_object(serialize(adj), 200)


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
