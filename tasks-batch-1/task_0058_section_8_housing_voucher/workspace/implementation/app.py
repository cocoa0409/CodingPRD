"""Section 8 Housing Choice Voucher API — single-file Flask app.

In-memory store, starts empty on every boot. See PRD.md / SCAFFOLD.yaml for
the full contract. start.sh launches this with PORT/0.0.0.0/foreground.
"""

import os
import re

from flask import Flask, request

import db
import services as svc
from errors import (
    APIError, fail,
    ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE, ERR_NOT_FOUND, ERR_VALIDATION,
    ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_BEDROOM_MISMATCH,
    ERR_VOUCHER_EXPIRED, ERR_INSPECTION_NOT_PASSED, ERR_RENT_NOT_REASONABLE,
    ERR_RENT_BURDEN_EXCEEDED, ERR_PAYMENT_STANDARD_OUT_OF_BAND,
    ERR_SAME_REGION_PORT, ERR_CURE_DEADLINE_PASSED, ERR_NOT_MOBILITY_AREA,
    ERR_DUPLICATE_PAYMENT_STANDARD, ERR_HOUSEHOLD_NOT_ELIGIBLE,
    ERR_VOUCHER_NOT_AVAILABLE,
)
from response import ok, ok_list, err

ROLES = {"ProgramAdmin", "Caseworker", "Inspector", "PortabilityCoordinator", "Landlord"}

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False
app.url_map.strict_slashes = False


# =========================================================================
# Auth / RBAC
# =========================================================================
def get_identity():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        fail(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header.")
    return uid, role


def require_roles(allowed):
    uid, role = get_identity()
    if role not in allowed:
        fail(ERR_FORBIDDEN_ROLE, "Role '%s' is not permitted for this operation." % role)
    return uid, role


# =========================================================================
# Body / field helpers
# =========================================================================
def get_body():
    if request.data:
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            data = None
    else:
        data = None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        fail(ERR_VALIDATION, "Request body must be a JSON object.")
    return data


def req_str(body, name):
    if name not in body or body[name] is None:
        fail(ERR_VALIDATION, "Missing required field '%s'." % name)
    v = body[name]
    if not isinstance(v, str) or v == "":
        fail(ERR_VALIDATION, "Field '%s' must be a non-empty string." % name)
    return v


def req_int(body, name, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        fail(ERR_VALIDATION, "Missing required field '%s'." % name)
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        fail(ERR_VALIDATION, "Field '%s' must be an integer." % name)
    if minimum is not None and v < minimum:
        fail(ERR_VALIDATION, "Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and v > maximum:
        fail(ERR_VALIDATION, "Field '%s' must be <= %s." % (name, maximum))
    return v


def opt_int(body, name, default, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return req_int(body, name, minimum, maximum)


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        fail(ERR_VALIDATION, "Field '%s' must be a boolean." % name)
    return v


def req_enum(body, name, allowed):
    v = req_str(body, name)
    if v not in allowed:
        fail(ERR_VALIDATION, "Field '%s' must be one of %s." % (name, sorted(allowed)))
    return v


def req_datetime(body, name):
    if name not in body or body[name] is None:
        fail(ERR_VALIDATION, "Missing required field '%s'." % name)
    try:
        return svc.parse_dt(body[name])
    except (ValueError, TypeError):
        fail(ERR_VALIDATION, "Field '%s' must be an ISO 8601 datetime." % name)


# =========================================================================
# Existence helpers (ERR_NOT_FOUND)
# =========================================================================
def find_or_404(store, _id):
    rec = store.get(_id)
    if rec is None:
        fail(ERR_NOT_FOUND, "Referenced resource '%s' does not exist." % _id)
    return rec


def fk_or_404(store, _id):
    if _id not in store:
        fail(ERR_NOT_FOUND, "Referenced resource '%s' does not exist." % _id)
    return store[_id]


# =========================================================================
# Pagination
# =========================================================================
def paginate(items):
    limit = request.args.get("limit", None)
    offset = request.args.get("offset", None)
    try:
        limit_v = 10 if limit is None else int(limit)
    except (ValueError, TypeError):
        fail(ERR_VALIDATION, "limit must be an integer.")
    try:
        offset_v = 0 if offset is None else int(offset)
    except (ValueError, TypeError):
        fail(ERR_VALIDATION, "offset must be an integer.")
    if limit_v < 1:
        limit_v = 1
    if limit_v > 100:
        limit_v = 100
    if offset_v < 0:
        offset_v = 0
    ordered = sorted(items, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset_v:offset_v + limit_v]
    return page, limit_v, offset_v, total


# =========================================================================
# Serializers (strip internal keys)
# =========================================================================
def pub(record, fields):
    out = {"id": record["id"], "created_at": record["created_at"]}
    if "updated_at" in record:
        out["updated_at"] = record["updated_at"]
    if "version" in record:
        out["version"] = record["version"]
    for f in fields:
        out[f] = record.get(f)
    return out


REGION_FIELDS = ["code", "name", "fmr_year", "is_special_mobility_area"]
PS_FIELDS = ["region_id", "bedroom_size", "amount_cents", "fmr_cents"]
HOUSEHOLD_FIELDS = ["head_name", "family_size", "annual_income_cents",
                    "dependents_count", "elderly_or_disabled", "childcare_expense_cents",
                    "region_id", "adjusted_annual_income_cents", "status"]
VOUCHER_FIELDS = ["household_id", "issuing_region_id", "bedroom_size", "issued_date",
                  "expiration_date", "term_days", "status"]
UNIT_FIELDS = ["landlord_id", "region_id", "bedroom_size", "asking_rent_cents",
               "comparable_rent_cents", "status"]
LANDLORD_FIELDS = ["name", "payee_account"]
HAP_FIELDS = ["voucher_id", "unit_id", "contract_rent_cents", "administering_region_id",
              "total_tenant_payment_cents", "hap_subsidy_cents", "tenant_rent_burden_cents",
              "status"]
INSPECTION_FIELDS = ["unit_id", "hap_contract_id", "inspection_type", "scheduled_date",
                     "cure_deadline", "status"]
RRD_FIELDS = ["unit_id", "requested_rent_cents", "comparable_rent_cents", "outcome"]
PORT_FIELDS = ["voucher_id", "receiving_region_id", "billing_mode", "status"]
REVIEW_FIELDS = ["hap_contract_id", "new_annual_income_cents", "effective_date",
                 "new_total_tenant_payment_cents", "new_hap_subsidy_cents", "status"]
GRANT_FIELDS = ["voucher_id", "target_region_id", "term_extension_days", "status"]


def s_region(r):
    return pub(r, REGION_FIELDS)


def s_ps(r):
    return pub(r, PS_FIELDS)


def s_household(r):
    return pub(r, HOUSEHOLD_FIELDS)


def s_voucher(r):
    out = pub(r, VOUCHER_FIELDS)
    out["issued_date"] = svc.fmt_dt(r["issued_date"])
    out["expiration_date"] = svc.fmt_dt(r["expiration_date"])
    return out


def s_unit(r):
    return pub(r, UNIT_FIELDS)


def s_landlord(r):
    return pub(r, LANDLORD_FIELDS)


def s_hap(r):
    return pub(r, HAP_FIELDS)


def s_inspection(r):
    out = pub(r, INSPECTION_FIELDS)
    out["scheduled_date"] = svc.fmt_dt(r["scheduled_date"])
    out["cure_deadline"] = svc.fmt_dt(r["cure_deadline"])
    return out


def s_rrd(r):
    # immutable: only id + created_at common fields
    out = {"id": r["id"], "created_at": r["created_at"]}
    for f in RRD_FIELDS:
        out[f] = r.get(f)
    return out


def s_port(r):
    return pub(r, PORT_FIELDS)


def s_review(r):
    out = pub(r, REVIEW_FIELDS)
    out["effective_date"] = svc.fmt_dt(r["effective_date"])
    return out


def s_grant(r):
    return pub(r, GRANT_FIELDS)


# =========================================================================
# Regions
# =========================================================================
CODE_RE = re.compile(r"^[A-Z_]+$")


@app.post("/regions")
def create_region():
    require_roles({"ProgramAdmin"})
    body = get_body()
    code = req_str(body, "code")
    if not CODE_RE.match(code) or not (3 <= len(code) <= 40):
        fail(ERR_VALIDATION, "code must be uppercase A-Z/underscore, 3-40 chars.")
    for r in db.regions.values():
        if r["code"] == code:
            fail(ERR_VALIDATION, "code must be unique across all regions.")
    name = req_str(body, "name")
    fmr_year = req_int(body, "fmr_year")
    is_sma = opt_bool(body, "is_special_mobility_area", False)
    rec = {"code": code, "name": name, "fmr_year": fmr_year,
           "is_special_mobility_area": is_sma}
    svc.stamp_new(rec)
    db.regions[rec["id"]] = rec
    return ok(s_region(rec), 201)


@app.get("/regions/<rid>")
def get_region(rid):
    require_roles(ROLES)
    rec = find_or_404(db.regions, rid)
    return ok(s_region(rec))


@app.get("/regions")
def list_regions():
    require_roles(ROLES)
    items = list(db.regions.values())
    flag = request.args.get("is_special_mobility_area")
    if flag is not None:
        want = flag.lower() == "true"
        items = [r for r in items if r["is_special_mobility_area"] == want]
    page, limit, offset, total = paginate(items)
    return ok_list([s_region(r) for r in page], limit, offset, total)


# =========================================================================
# Payment Standards
# =========================================================================
@app.post("/payment-standards")
def create_payment_standard():
    require_roles({"ProgramAdmin"})
    body = get_body()
    region_id = req_str(body, "region_id")
    bedroom_size = req_int(body, "bedroom_size", minimum=0, maximum=6)
    amount_cents = req_int(body, "amount_cents", minimum=0)
    fmr_cents = req_int(body, "fmr_cents", minimum=0)
    # Existence (priority 3) before business rules.
    fk_or_404(db.regions, region_id)
    # Duplicate check (ERR_DUPLICATE_PAYMENT_STANDARD, 409, priority 17).
    for ps in db.payment_standards.values():
        if ps["region_id"] == region_id and ps["bedroom_size"] == bedroom_size:
            fail(ERR_DUPLICATE_PAYMENT_STANDARD,
                 "A payment standard already exists for that region and bedroom size.")
    # FMR band 90%-110% inclusive (priority 11).
    from decimal import Decimal
    lo = Decimal("0.90") * Decimal(fmr_cents)
    hi = Decimal("1.10") * Decimal(fmr_cents)
    if not (lo <= Decimal(amount_cents) <= hi):
        fail(ERR_PAYMENT_STANDARD_OUT_OF_BAND,
             "amount_cents must be within 90%-110% of fmr_cents.")
    rec = {"region_id": region_id, "bedroom_size": bedroom_size,
           "amount_cents": amount_cents, "fmr_cents": fmr_cents}
    svc.stamp_new(rec)
    db.payment_standards[rec["id"]] = rec
    return ok(s_ps(rec), 201)


@app.get("/payment-standards/<pid>")
def get_payment_standard(pid):
    require_roles({"ProgramAdmin", "Caseworker", "PortabilityCoordinator"})
    rec = find_or_404(db.payment_standards, pid)
    return ok(s_ps(rec))


@app.get("/payment-standards")
def list_payment_standards():
    require_roles({"ProgramAdmin", "Caseworker", "PortabilityCoordinator"})
    items = list(db.payment_standards.values())
    region_id = request.args.get("region_id")
    if region_id is not None:
        items = [p for p in items if p["region_id"] == region_id]
    bs = request.args.get("bedroom_size")
    if bs is not None:
        try:
            bs_v = int(bs)
        except ValueError:
            fail(ERR_VALIDATION, "bedroom_size must be an integer.")
        items = [p for p in items if p["bedroom_size"] == bs_v]
    page, limit, offset, total = paginate(items)
    return ok_list([s_ps(p) for p in page], limit, offset, total)


# =========================================================================
# Households
# =========================================================================
@app.post("/households")
def create_household():
    require_roles({"Caseworker"})
    body = get_body()
    head_name = req_str(body, "head_name")
    family_size = req_int(body, "family_size", minimum=1)
    annual_income_cents = req_int(body, "annual_income_cents", minimum=0)
    region_id = req_str(body, "region_id")
    dependents_count = opt_int(body, "dependents_count", 0, minimum=0)
    elderly = opt_bool(body, "elderly_or_disabled", False)
    childcare = opt_int(body, "childcare_expense_cents", 0, minimum=0)
    fk_or_404(db.regions, region_id)
    rec = {
        "head_name": head_name, "family_size": family_size,
        "annual_income_cents": annual_income_cents, "region_id": region_id,
        "dependents_count": dependents_count, "elderly_or_disabled": elderly,
        "childcare_expense_cents": childcare,
        "adjusted_annual_income_cents": None, "status": "APPLIED",
    }
    svc.stamp_new(rec)
    db.households[rec["id"]] = rec
    return ok(s_household(rec), 201)


@app.get("/households/<hid>")
def get_household(hid):
    require_roles({"Caseworker", "ProgramAdmin"})
    rec = find_or_404(db.households, hid)
    return ok(s_household(rec))


@app.get("/households")
def list_households():
    require_roles({"Caseworker", "ProgramAdmin"})
    items = list(db.households.values())
    region_id = request.args.get("region_id")
    if region_id is not None:
        items = [h for h in items if h["region_id"] == region_id]
    status = request.args.get("status")
    if status is not None:
        items = [h for h in items if h["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_list([s_household(h) for h in page], limit, offset, total)


@app.post("/households/<hid>/determine-eligibility")
def determine_eligibility(hid):
    require_roles({"Caseworker"})
    h = find_or_404(db.households, hid)
    if h["status"] != "APPLIED":
        fail(ERR_INVALID_STATE, "Household is not in APPLIED status.")
    adj = svc.adjusted_income(h["annual_income_cents"], h["dependents_count"],
                              h["elderly_or_disabled"], h["childcare_expense_cents"])
    limit = svc.income_limit_cents(h["family_size"])
    h["adjusted_annual_income_cents"] = adj
    h["status"] = "ELIGIBLE" if adj <= limit else "INELIGIBLE"
    svc.touch(h)
    return ok(s_household(h))


# =========================================================================
# Vouchers
# =========================================================================
@app.post("/vouchers")
def issue_voucher():
    require_roles({"Caseworker"})
    body = get_body()
    household_id = req_str(body, "household_id")
    term_days = opt_int(body, "term_days", svc.DEFAULT_TERM_DAYS, minimum=1)
    h = fk_or_404(db.households, household_id)
    if h["status"] != "ELIGIBLE":
        fail(ERR_HOUSEHOLD_NOT_ELIGIBLE, "Household is not in ELIGIBLE status.")
    issued = db.current_utc()
    from datetime import timedelta
    expiration = issued + timedelta(days=term_days)
    bedroom = svc.occupancy_bedroom_size(h["family_size"])
    rec = {
        "household_id": household_id, "issuing_region_id": h["region_id"],
        "bedroom_size": bedroom, "issued_date": issued, "expiration_date": expiration,
        "term_days": term_days, "status": "ISSUED",
    }
    svc.stamp_new(rec)
    db.vouchers[rec["id"]] = rec
    h["status"] = "VOUCHER_ISSUED"
    svc.touch(h)
    return ok(s_voucher(rec), 201)


@app.get("/vouchers/<vid>")
def get_voucher(vid):
    require_roles({"Caseworker", "ProgramAdmin", "PortabilityCoordinator"})
    rec = find_or_404(db.vouchers, vid)
    return ok(s_voucher(rec))


@app.get("/vouchers")
def list_vouchers():
    require_roles({"Caseworker", "ProgramAdmin", "PortabilityCoordinator"})
    items = list(db.vouchers.values())
    hh = request.args.get("household_id")
    if hh is not None:
        items = [v for v in items if v["household_id"] == hh]
    ir = request.args.get("issuing_region_id")
    if ir is not None:
        items = [v for v in items if v["issuing_region_id"] == ir]
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_list([s_voucher(v) for v in page], limit, offset, total)


@app.post("/vouchers/<vid>/expire")
def expire_voucher(vid):
    require_roles({"ProgramAdmin"})
    v = find_or_404(db.vouchers, vid)
    if v["status"] != "ISSUED":
        fail(ERR_INVALID_STATE, "Voucher is not in ISSUED status.")
    if db.current_utc() < v["expiration_date"]:
        fail(ERR_INVALID_STATE, "Voucher term has not elapsed.")
    v["status"] = "EXPIRED"
    svc.touch(v)
    h = db.households.get(v["household_id"])
    if h is not None and h["status"] == "VOUCHER_ISSUED":
        h["status"] = "TERMINATED"
        svc.touch(h)
    return ok(s_voucher(v))


# =========================================================================
# Landlords & Units
# =========================================================================
@app.post("/landlords")
def create_landlord():
    require_roles({"ProgramAdmin", "Landlord"})
    body = get_body()
    name = req_str(body, "name")
    payee = req_str(body, "payee_account")
    rec = {"name": name, "payee_account": payee}
    svc.stamp_new(rec)
    db.landlords[rec["id"]] = rec
    return ok(s_landlord(rec), 201)


@app.get("/landlords/<lid>")
def get_landlord(lid):
    require_roles({"ProgramAdmin", "Landlord", "Caseworker"})
    rec = find_or_404(db.landlords, lid)
    return ok(s_landlord(rec))


@app.post("/units")
def create_unit():
    require_roles({"Landlord", "ProgramAdmin"})
    body = get_body()
    landlord_id = req_str(body, "landlord_id")
    region_id = req_str(body, "region_id")
    bedroom_size = req_int(body, "bedroom_size", minimum=0, maximum=6)
    asking = req_int(body, "asking_rent_cents", minimum=0)
    comparable = req_int(body, "comparable_rent_cents", minimum=0)
    fk_or_404(db.landlords, landlord_id)
    fk_or_404(db.regions, region_id)
    rec = {
        "landlord_id": landlord_id, "region_id": region_id, "bedroom_size": bedroom_size,
        "asking_rent_cents": asking, "comparable_rent_cents": comparable, "status": "LISTED",
    }
    svc.stamp_new(rec)
    db.units[rec["id"]] = rec
    return ok(s_unit(rec), 201)


@app.get("/units/<uid>")
def get_unit(uid):
    require_roles({"Landlord", "ProgramAdmin", "Caseworker", "Inspector"})
    rec = find_or_404(db.units, uid)
    return ok(s_unit(rec))


@app.get("/units")
def list_units():
    require_roles({"Landlord", "ProgramAdmin", "Caseworker", "Inspector"})
    items = list(db.units.values())
    ll = request.args.get("landlord_id")
    if ll is not None:
        items = [u for u in items if u["landlord_id"] == ll]
    region_id = request.args.get("region_id")
    if region_id is not None:
        items = [u for u in items if u["region_id"] == region_id]
    status = request.args.get("status")
    if status is not None:
        items = [u for u in items if u["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_list([s_unit(u) for u in page], limit, offset, total)


# =========================================================================
# Rent reasonableness
# =========================================================================
@app.post("/rent-reasonableness")
def create_rrd():
    require_roles({"Caseworker"})
    body = get_body()
    unit_id = req_str(body, "unit_id")
    requested = req_int(body, "requested_rent_cents", minimum=0)
    u = fk_or_404(db.units, unit_id)
    comparable = u["comparable_rent_cents"]
    outcome = "REASONABLE" if requested <= comparable else "NOT_REASONABLE"
    rec = {"unit_id": unit_id, "requested_rent_cents": requested,
           "comparable_rent_cents": comparable, "outcome": outcome}
    svc.stamp_new(rec, with_version=False)
    db.rent_reasonableness[rec["id"]] = rec
    return ok(s_rrd(rec), 201)


@app.get("/rent-reasonableness/<rid>")
def get_rrd(rid):
    require_roles({"Caseworker", "ProgramAdmin"})
    rec = find_or_404(db.rent_reasonableness, rid)
    return ok(s_rrd(rec))


@app.get("/rent-reasonableness")
def list_rrd():
    require_roles({"Caseworker", "ProgramAdmin"})
    items = list(db.rent_reasonableness.values())
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        items = [r for r in items if r["unit_id"] == unit_id]
    page, limit, offset, total = paginate(items)
    return ok_list([s_rrd(r) for r in page], limit, offset, total)


# =========================================================================
# Inspections
# =========================================================================
@app.post("/inspections")
def create_inspection():
    require_roles({"Inspector", "Caseworker"})
    body = get_body()
    unit_id = req_str(body, "unit_id")
    inspection_type = req_enum(body, "inspection_type", {"INITIAL", "ANNUAL"})
    scheduled_date = req_datetime(body, "scheduled_date")
    hap_contract_id = body.get("hap_contract_id")
    if hap_contract_id is not None and not isinstance(hap_contract_id, str):
        fail(ERR_VALIDATION, "hap_contract_id must be a string.")
    fk_or_404(db.units, unit_id)
    if hap_contract_id is not None:
        fk_or_404(db.hap_contracts, hap_contract_id)
    rec = {
        "unit_id": unit_id, "hap_contract_id": hap_contract_id,
        "inspection_type": inspection_type, "scheduled_date": scheduled_date,
        "cure_deadline": None, "status": "SCHEDULED",
    }
    svc.stamp_new(rec)
    db.inspections[rec["id"]] = rec
    return ok(s_inspection(rec), 201)


@app.get("/inspections/<iid>")
def get_inspection(iid):
    require_roles({"Inspector", "Caseworker", "ProgramAdmin"})
    rec = find_or_404(db.inspections, iid)
    return ok(s_inspection(rec))


@app.get("/inspections")
def list_inspections():
    require_roles({"Inspector", "Caseworker", "ProgramAdmin"})
    items = list(db.inspections.values())
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        items = [i for i in items if i["unit_id"] == unit_id]
    hc = request.args.get("hap_contract_id")
    if hc is not None:
        items = [i for i in items if i["hap_contract_id"] == hc]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_list([s_inspection(i) for i in page], limit, offset, total)


@app.post("/inspections/<iid>/pass")
def pass_inspection(iid):
    require_roles({"Inspector"})
    insp = find_or_404(db.inspections, iid)
    if insp["status"] != "SCHEDULED":
        fail(ERR_INVALID_STATE, "Inspection is not in SCHEDULED status.")
    insp["status"] = "PASSED"
    svc.touch(insp)
    if insp["inspection_type"] == "INITIAL":
        u = db.units.get(insp["unit_id"])
        if u is not None:
            u["status"] = "UNDER_CONTRACT"
            svc.touch(u)
    return ok(s_inspection(insp))


@app.post("/inspections/<iid>/fail")
def fail_inspection(iid):
    require_roles({"Inspector"})
    insp = find_or_404(db.inspections, iid)
    if insp["status"] != "SCHEDULED":
        fail(ERR_INVALID_STATE, "Inspection is not in SCHEDULED status.")
    from datetime import timedelta
    insp["status"] = "FAILED"
    insp["cure_deadline"] = insp["scheduled_date"] + timedelta(days=svc.CURE_WINDOW_DAYS)
    svc.touch(insp)
    # Annual fail of an ACTIVE contract -> abatement cascade.
    if insp["inspection_type"] == "ANNUAL" and insp["hap_contract_id"]:
        hc = db.hap_contracts.get(insp["hap_contract_id"])
        if hc is not None and hc["status"] == "ACTIVE":
            hc["status"] = "ABATED"
            hc["hap_subsidy_cents"] = 0
            svc.touch(hc)
            u = db.units.get(hc["unit_id"])
            if u is not None:
                u["status"] = "OFF_MARKET"
                svc.touch(u)
    return ok(s_inspection(insp))


@app.post("/inspections/<iid>/cure")
def cure_inspection(iid):
    require_roles({"Inspector"})
    insp = find_or_404(db.inspections, iid)
    if insp["status"] != "FAILED":
        fail(ERR_INVALID_STATE, "Inspection is not in FAILED status.")
    if db.current_utc() > insp["cure_deadline"]:
        fail(ERR_CURE_DEADLINE_PASSED, "Cure attempted after the cure deadline.")
    insp["status"] = "CURED"
    svc.touch(insp)
    # Restoration cascade if linked contract is ABATED.
    if insp["hap_contract_id"]:
        hc = db.hap_contracts.get(insp["hap_contract_id"])
        if hc is not None and hc["status"] == "ABATED":
            hc["status"] = "ACTIVE"
            v = db.vouchers.get(hc["voucher_id"])
            bedroom = v["bedroom_size"] if v else None
            ps_amount = svc.lookup_payment_standard_amount(
                hc["administering_region_id"], bedroom)
            if ps_amount is None:
                ps_amount = 0
            subsidy, burden = svc.subsidy_fields(
                hc["contract_rent_cents"], ps_amount, hc["total_tenant_payment_cents"])
            hc["hap_subsidy_cents"] = subsidy
            hc["tenant_rent_burden_cents"] = burden
            svc.touch(hc)
            u = db.units.get(hc["unit_id"])
            if u is not None:
                u["status"] = "UNDER_CONTRACT"
                svc.touch(u)
    return ok(s_inspection(insp))


@app.post("/inspections/<iid>/fail-cure")
def fail_cure_inspection(iid):
    require_roles({"ProgramAdmin"})
    insp = find_or_404(db.inspections, iid)
    if insp["status"] != "FAILED":
        fail(ERR_INVALID_STATE, "Inspection is not in FAILED status.")
    if db.current_utc() <= insp["cure_deadline"]:
        fail(ERR_INVALID_STATE, "Cure deadline has not passed.")
    insp["status"] = "ABATED"
    svc.touch(insp)
    # Termination cascade: contract ABATED->TERMINATED, voucher + household TERMINATED.
    if insp["hap_contract_id"]:
        hc = db.hap_contracts.get(insp["hap_contract_id"])
        if hc is not None and hc["status"] == "ABATED":
            hc["status"] = "TERMINATED"
            svc.touch(hc)
            v = db.vouchers.get(hc["voucher_id"])
            if v is not None:
                v["status"] = "TERMINATED"
                svc.touch(v)
                h = db.households.get(v["household_id"])
                if h is not None:
                    h["status"] = "TERMINATED"
                    svc.touch(h)
    return ok(s_inspection(insp))


# =========================================================================
# HAP contracts (lease-up)
# =========================================================================
@app.post("/hap-contracts")
def create_hap_contract():
    require_roles({"Caseworker"})
    body = get_body()
    voucher_id = req_str(body, "voucher_id")
    unit_id = req_str(body, "unit_id")
    contract_rent = req_int(body, "contract_rent_cents", minimum=0)
    expected_version = req_int(body, "expected_voucher_version")
    # Existence (priority 3): body FKs left to right.
    v = fk_or_404(db.vouchers, voucher_id)
    u = fk_or_404(db.units, unit_id)
    # OCC (priority 5).
    if expected_version != v["version"]:
        fail(ERR_STALE_VERSION, "expected_voucher_version does not match voucher version.")
    # Business gates in PRD §3.5 order:
    # 1. voucher availability
    if v["status"] not in ("ISSUED", "PORTING_OUT"):
        fail(ERR_VOUCHER_NOT_AVAILABLE, "Voucher is not available for lease-up.")
    # 2. bedroom fit
    if u["bedroom_size"] < v["bedroom_size"]:
        fail(ERR_BEDROOM_MISMATCH, "Unit is smaller than the voucher's bedroom size.")
    # 3. not expired (strictly before expiration)
    if db.current_utc() >= v["expiration_date"]:
        fail(ERR_VOUCHER_EXPIRED, "Voucher has expired.")
    # 4. passed initial inspection for the unit
    has_passed_initial = any(
        i["unit_id"] == unit_id and i["inspection_type"] == "INITIAL"
        and i["status"] == "PASSED" for i in db.inspections.values())
    if not has_passed_initial:
        fail(ERR_INSPECTION_NOT_PASSED, "Unit has no passed INITIAL inspection.")
    # 5. rent reasonableness (inclusive)
    if contract_rent > u["comparable_rent_cents"]:
        fail(ERR_RENT_NOT_REASONABLE, "Contract rent exceeds comparable rent.")
    # Administering region: receiving region if ported under billing, else issuing.
    administering_region_id = v["issuing_region_id"]
    if v["status"] == "PORTING_OUT":
        pm = _latest_billing_port_for_voucher(voucher_id)
        if pm is not None:
            administering_region_id = pm["receiving_region_id"]
    # TTP
    h = db.households.get(v["household_id"])
    adj = h["adjusted_annual_income_cents"] if h else 0
    gross = h["annual_income_cents"] if h else 0
    ttp = svc.ttp_cents(adj, gross)
    # Subsidy
    ps_amount = svc.lookup_payment_standard_amount(
        administering_region_id, v["bedroom_size"])
    if ps_amount is None:
        ps_amount = 0
    subsidy, burden = svc.subsidy_fields(contract_rent, ps_amount, ttp)
    # 6. initial rent-burden gate (inclusive at 40%)
    if burden > svc.max_burden_cents(adj):
        fail(ERR_RENT_BURDEN_EXCEEDED, "Tenant rent burden exceeds 40% of monthly adjusted income.")
    # Commit
    rec = {
        "voucher_id": voucher_id, "unit_id": unit_id, "contract_rent_cents": contract_rent,
        "administering_region_id": administering_region_id,
        "total_tenant_payment_cents": ttp, "hap_subsidy_cents": subsidy,
        "tenant_rent_burden_cents": burden, "status": "ACTIVE",
    }
    svc.stamp_new(rec)
    db.hap_contracts[rec["id"]] = rec
    # Cascades
    v["status"] = "LEASED"
    svc.touch(v)  # this is the +1 version bump
    if h is not None:
        h["status"] = "LEASED"
        svc.touch(h)
    u["status"] = "UNDER_CONTRACT"
    svc.touch(u)
    # Special mobility grant consumption.
    for g in db.special_mobility_grants.values():
        if (g["voucher_id"] == voucher_id and g["status"] == "GRANTED"
                and g["target_region_id"] == u["region_id"]):
            g["status"] = "CONSUMED"
            svc.touch(g)
    return ok(s_hap(rec), 201)


def _latest_billing_port_for_voucher(voucher_id):
    candidates = [pm for pm in db.portability_moves.values()
                  if pm["voucher_id"] == voucher_id
                  and pm["billing_mode"] == "BILLING"
                  and pm["status"] == "APPROVED"]
    if not candidates:
        return None
    return sorted(candidates, key=lambda r: r["_seq"])[-1]


@app.get("/hap-contracts/<cid>")
def get_hap_contract(cid):
    require_roles({"Caseworker", "ProgramAdmin", "Landlord"})
    rec = find_or_404(db.hap_contracts, cid)
    return ok(s_hap(rec))


@app.get("/hap-contracts")
def list_hap_contracts():
    require_roles({"Caseworker", "ProgramAdmin", "Landlord"})
    items = list(db.hap_contracts.values())
    vid = request.args.get("voucher_id")
    if vid is not None:
        items = [c for c in items if c["voucher_id"] == vid]
    uid = request.args.get("unit_id")
    if uid is not None:
        items = [c for c in items if c["unit_id"] == uid]
    ar = request.args.get("administering_region_id")
    if ar is not None:
        items = [c for c in items if c["administering_region_id"] == ar]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_list([s_hap(c) for c in page], limit, offset, total)


@app.post("/hap-contracts/<cid>/terminate")
def terminate_hap_contract(cid):
    require_roles({"Caseworker"})
    hc = find_or_404(db.hap_contracts, cid)
    if hc["status"] != "ACTIVE":
        fail(ERR_INVALID_STATE, "HAP contract is not in ACTIVE status.")
    hc["status"] = "TERMINATED"
    svc.touch(hc)
    v = db.vouchers.get(hc["voucher_id"])
    if v is not None:
        v["status"] = "TERMINATED"
        svc.touch(v)
        h = db.households.get(v["household_id"])
        if h is not None:
            h["status"] = "TERMINATED"
            svc.touch(h)
    u = db.units.get(hc["unit_id"])
    if u is not None:
        u["status"] = "OFF_MARKET"
        svc.touch(u)
    return ok(s_hap(hc))


# =========================================================================
# Portability
# =========================================================================
@app.post("/portability-moves")
def create_portability_move():
    require_roles({"PortabilityCoordinator", "Caseworker"})
    body = get_body()
    voucher_id = req_str(body, "voucher_id")
    receiving_region_id = req_str(body, "receiving_region_id")
    v = fk_or_404(db.vouchers, voucher_id)
    receiving = fk_or_404(db.regions, receiving_region_id)
    if receiving_region_id == v["issuing_region_id"]:
        fail(ERR_SAME_REGION_PORT, "Receiving region must differ from the issuing region.")
    billing_mode = "ABSORPTION" if receiving["is_special_mobility_area"] else "BILLING"
    rec = {"voucher_id": voucher_id, "receiving_region_id": receiving_region_id,
           "billing_mode": billing_mode, "status": "REQUESTED"}
    svc.stamp_new(rec)
    db.portability_moves[rec["id"]] = rec
    return ok(s_port(rec), 201)


@app.get("/portability-moves/<pid>")
def get_portability_move(pid):
    require_roles({"PortabilityCoordinator", "Caseworker", "ProgramAdmin"})
    rec = find_or_404(db.portability_moves, pid)
    return ok(s_port(rec))


@app.get("/portability-moves")
def list_portability_moves():
    require_roles({"PortabilityCoordinator", "Caseworker", "ProgramAdmin"})
    items = list(db.portability_moves.values())
    vid = request.args.get("voucher_id")
    if vid is not None:
        items = [p for p in items if p["voucher_id"] == vid]
    rr = request.args.get("receiving_region_id")
    if rr is not None:
        items = [p for p in items if p["receiving_region_id"] == rr]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_list([s_port(p) for p in page], limit, offset, total)


@app.post("/portability-moves/<pid>/approve")
def approve_portability_move(pid):
    require_roles({"PortabilityCoordinator"})
    pm = find_or_404(db.portability_moves, pid)
    if pm["status"] != "REQUESTED":
        fail(ERR_INVALID_STATE, "Portability move is not in REQUESTED status.")
    v = db.vouchers.get(pm["voucher_id"])
    if v is None:
        fail(ERR_NOT_FOUND, "Linked voucher does not exist.")
    if v["status"] != "ISSUED":
        fail(ERR_INVALID_STATE, "Linked voucher is not in ISSUED status.")
    if pm["receiving_region_id"] == v["issuing_region_id"]:
        fail(ERR_SAME_REGION_PORT, "Receiving region must differ from the issuing region.")
    # Re-read billing mode from the receiving region (deterministic).
    receiving = db.regions.get(pm["receiving_region_id"])
    mode = "ABSORPTION" if (receiving and receiving["is_special_mobility_area"]) else "BILLING"
    pm["billing_mode"] = mode
    if mode == "BILLING":
        pm["status"] = "APPROVED"
        v["status"] = "PORTING_OUT"
        svc.touch(v)
    else:
        pm["status"] = "ABSORBED"
        v["status"] = "ABSORBED"
        v["issuing_region_id"] = pm["receiving_region_id"]
        svc.touch(v)
    svc.touch(pm)
    return ok(s_port(pm))


@app.post("/portability-moves/<pid>/deny")
def deny_portability_move(pid):
    require_roles({"PortabilityCoordinator"})
    pm = find_or_404(db.portability_moves, pid)
    if pm["status"] != "REQUESTED":
        fail(ERR_INVALID_STATE, "Portability move is not in REQUESTED status.")
    pm["status"] = "DENIED"
    svc.touch(pm)
    return ok(s_port(pm))


# =========================================================================
# Annual reviews
# =========================================================================
@app.post("/annual-reviews")
def create_annual_review():
    require_roles({"Caseworker"})
    body = get_body()
    hap_contract_id = req_str(body, "hap_contract_id")
    new_income = req_int(body, "new_annual_income_cents", minimum=0)
    effective_date = req_datetime(body, "effective_date")
    fk_or_404(db.hap_contracts, hap_contract_id)
    rec = {"hap_contract_id": hap_contract_id, "new_annual_income_cents": new_income,
           "effective_date": effective_date, "new_total_tenant_payment_cents": None,
           "new_hap_subsidy_cents": None, "status": "DRAFT"}
    svc.stamp_new(rec)
    db.annual_reviews[rec["id"]] = rec
    return ok(s_review(rec), 201)


@app.get("/annual-reviews/<rid>")
def get_annual_review(rid):
    require_roles({"Caseworker", "ProgramAdmin"})
    rec = find_or_404(db.annual_reviews, rid)
    return ok(s_review(rec))


@app.get("/annual-reviews")
def list_annual_reviews():
    require_roles({"Caseworker", "ProgramAdmin"})
    items = list(db.annual_reviews.values())
    hc = request.args.get("hap_contract_id")
    if hc is not None:
        items = [r for r in items if r["hap_contract_id"] == hc]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_list([s_review(r) for r in page], limit, offset, total)


@app.post("/annual-reviews/<rid>/finalize")
def finalize_annual_review(rid):
    require_roles({"Caseworker"})
    body = get_body()
    expected_version = req_int(body, "expected_hap_contract_version")
    review = find_or_404(db.annual_reviews, rid)
    if review["status"] != "DRAFT":
        fail(ERR_INVALID_STATE, "Annual review is not in DRAFT status.")
    hc = db.hap_contracts.get(review["hap_contract_id"])
    if hc is None:
        fail(ERR_NOT_FOUND, "Linked HAP contract does not exist.")
    if hc["status"] != "ACTIVE":
        fail(ERR_INVALID_STATE, "Linked HAP contract is not ACTIVE.")
    if expected_version != hc["version"]:
        fail(ERR_STALE_VERSION, "expected_hap_contract_version does not match contract version.")
    v = db.vouchers.get(hc["voucher_id"])
    h = db.households.get(v["household_id"]) if v else None
    if h is None:
        fail(ERR_NOT_FOUND, "Linked household does not exist.")
    # Recompute adjusted income from new gross income (same deductions).
    adj = svc.adjusted_income(review["new_annual_income_cents"], h["dependents_count"],
                              h["elderly_or_disabled"], h["childcare_expense_cents"])
    h["adjusted_annual_income_cents"] = adj
    svc.touch(h)
    ttp = svc.ttp_cents(adj, review["new_annual_income_cents"])
    ps_amount = svc.lookup_payment_standard_amount(
        hc["administering_region_id"], v["bedroom_size"])
    if ps_amount is None:
        ps_amount = 0
    subsidy, burden = svc.subsidy_fields(hc["contract_rent_cents"], ps_amount, ttp)
    review["new_total_tenant_payment_cents"] = ttp
    review["new_hap_subsidy_cents"] = subsidy
    review["status"] = "FINALIZED"
    svc.touch(review)
    hc["total_tenant_payment_cents"] = ttp
    hc["hap_subsidy_cents"] = subsidy
    hc["tenant_rent_burden_cents"] = burden
    svc.touch(hc)  # +1 version bump
    return ok(s_review(review))


# =========================================================================
# Special mobility grants
# =========================================================================
@app.post("/special-mobility-grants")
def create_grant():
    require_roles({"PortabilityCoordinator"})
    body = get_body()
    voucher_id = req_str(body, "voucher_id")
    target_region_id = req_str(body, "target_region_id")
    term_ext = opt_int(body, "term_extension_days", svc.DEFAULT_TERM_EXTENSION_DAYS, minimum=1)
    v = fk_or_404(db.vouchers, voucher_id)
    target = fk_or_404(db.regions, target_region_id)
    if not target["is_special_mobility_area"]:
        fail(ERR_NOT_MOBILITY_AREA, "Target region is not a special mobility area.")
    rec = {"voucher_id": voucher_id, "target_region_id": target_region_id,
           "term_extension_days": term_ext, "status": "GRANTED"}
    svc.stamp_new(rec)
    db.special_mobility_grants[rec["id"]] = rec
    from datetime import timedelta
    v["expiration_date"] = v["expiration_date"] + timedelta(days=term_ext)
    svc.touch(v)
    return ok(s_grant(rec), 201)


@app.get("/special-mobility-grants/<gid>")
def get_grant(gid):
    require_roles({"PortabilityCoordinator", "Caseworker", "ProgramAdmin"})
    rec = find_or_404(db.special_mobility_grants, gid)
    return ok(s_grant(rec))


@app.get("/special-mobility-grants")
def list_grants():
    require_roles({"PortabilityCoordinator", "Caseworker", "ProgramAdmin"})
    items = list(db.special_mobility_grants.values())
    vid = request.args.get("voucher_id")
    if vid is not None:
        items = [g for g in items if g["voucher_id"] == vid]
    tr = request.args.get("target_region_id")
    if tr is not None:
        items = [g for g in items if g["target_region_id"] == tr]
    status = request.args.get("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_list([s_grant(g) for g in page], limit, offset, total)


@app.post("/special-mobility-grants/<gid>/revoke")
def revoke_grant(gid):
    require_roles({"PortabilityCoordinator"})
    g = find_or_404(db.special_mobility_grants, gid)
    if g["status"] != "GRANTED":
        fail(ERR_INVALID_STATE, "Grant is not in GRANTED status.")
    g["status"] = "REVOKED"
    svc.touch(g)
    v = db.vouchers.get(g["voucher_id"])
    if v is not None:
        from datetime import timedelta
        v["expiration_date"] = v["expiration_date"] - timedelta(days=g["term_extension_days"])
        svc.touch(v)
    return ok(s_grant(g))


# =========================================================================
# Test-driving clock
# =========================================================================
@app.post("/_clock/set_current_utc")
def set_clock():
    require_roles({"ProgramAdmin"})
    body = get_body()
    to_iso = req_str(body, "to_iso8601")
    try:
        dt = svc.parse_dt(to_iso)
    except (ValueError, TypeError):
        fail(ERR_VALIDATION, "to_iso8601 must be an ISO 8601 datetime.")
    db.set_current_utc(dt)
    return ok({})


# =========================================================================
# Error handlers
# =========================================================================
@app.errorhandler(APIError)
def handle_api_error(e):
    return err(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(_e):
    return err("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(_e):
    return err("ERR_VALIDATION", "Method not allowed for this path.", 400)


@app.errorhandler(400)
def handle_400(_e):
    return err("ERR_VALIDATION", "Malformed request.", 400)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, APIError):
        return err(e.error_id, e.message, e.http_status)
    code = getattr(e, "code", None)
    if code == 404:
        return err("ERR_NOT_FOUND", "Resource not found.", 404)
    if code in (400, 405, 415):
        return err("ERR_VALIDATION", "Malformed request.", 400)
    return err("ERR_VALIDATION", "Unhandled server error.", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=False)
