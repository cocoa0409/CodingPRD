"""Lease endpoints."""

from flask import Blueprint, request

import db
from middleware import authenticate, require_role
from response import success_object, success_list
from util import (body_json, check_unknown_fields, require_fields, as_int, as_str,
                  as_bool, as_enum, as_number, parse_date, clock_date, d,
                  parse_pagination, paginate)
from errors import (raise_err, ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE,
                    ERR_STALE_VERSION, ERR_OUTSIDE_PRODUCTION_WINDOW,
                    ERR_ORGANIC_AUDIT_REQUIRED, ERR_LEASE_CONFLICT)
from services import core
from decimal import Decimal

bp = Blueprint("leases", __name__)

ALL_ROLES = {"SugarhouseManager", "FieldCrew", "SugarMaker", "CertInspector"}
MGR = {"SugarhouseManager"}


def get_lease_or_404(lid):
    l = db.leases.get(lid)
    if not l:
        raise_err(ERR_NOT_FOUND, f"lease {lid} not found")
    return l


def _validate_royalty_fields(royalty_basis, per_tap_cents, share_pct):
    """Conditional requiredness (PRD §3.4)."""
    if royalty_basis == "PER_TAP":
        if per_tap_cents is None:
            raise_err(ERR_VALIDATION, "per_tap_cents required when royalty_basis=PER_TAP")
        if share_pct is not None:
            raise_err(ERR_VALIDATION, "share_pct must be null when royalty_basis=PER_TAP")
        if isinstance(per_tap_cents, bool) or not isinstance(per_tap_cents, int) or per_tap_cents <= 0:
            raise_err(ERR_VALIDATION, "per_tap_cents must be an integer > 0")
    elif royalty_basis == "SHARE_OF_SYRUP":
        if share_pct is None:
            raise_err(ERR_VALIDATION, "share_pct required when royalty_basis=SHARE_OF_SYRUP")
        if per_tap_cents is not None:
            raise_err(ERR_VALIDATION, "per_tap_cents must be null when royalty_basis=SHARE_OF_SYRUP")
        v = as_number(share_pct, "share_pct")
        if v <= 0 or v > Decimal("50"):
            raise_err(ERR_VALIDATION, "share_pct must be > 0 and <= 50")
    else:
        raise_err(ERR_VALIDATION, "royalty_basis must be PER_TAP or SHARE_OF_SYRUP")


@bp.post("/sugarhouse/leases")
def create_lease():
    caller = authenticate()
    require_role(caller, MGR)
    data = body_json()
    allowed = {"sugarbush_id", "landowner_name", "royalty_basis", "per_tap_cents",
               "share_pct", "certified_organic_required", "term_start", "term_end"}
    check_unknown_fields(data, allowed)
    require_fields(data, ["sugarbush_id", "landowner_name", "royalty_basis",
                          "term_start", "term_end"])
    sugarbush_id = as_str(data["sugarbush_id"], "sugarbush_id")
    landowner_name = as_str(data["landowner_name"], "landowner_name")
    royalty_basis = as_enum(data["royalty_basis"], "royalty_basis",
                            {"PER_TAP", "SHARE_OF_SYRUP"})
    per_tap_cents = data.get("per_tap_cents")
    share_pct = data.get("share_pct")
    certified_organic_required = data.get("certified_organic_required", False)
    if not isinstance(certified_organic_required, bool):
        raise_err(ERR_VALIDATION, "certified_organic_required must be a boolean")
    term_start = as_str(data["term_start"], "term_start")
    term_end = as_str(data["term_end"], "term_end")
    try:
        ts = parse_date(term_start)
        te = parse_date(term_end)
    except Exception:
        raise_err(ERR_VALIDATION, "term_start/term_end must be YYYY-MM-DD dates")
    if te <= ts:
        raise_err(ERR_VALIDATION, "term_end must be after term_start")
    _validate_royalty_fields(royalty_basis, per_tap_cents, share_pct)

    bush = db.sugarbushes.get(sugarbush_id)
    if not bush:
        raise_err(ERR_NOT_FOUND, f"sugarbush {sugarbush_id} not found")
    # Priority 5: state gate
    if bush["status"] not in ("PREP", "TAPPING"):
        raise_err(ERR_INVALID_STATE,
                  f"sugarbush is {bush['status']}, expected PREP or TAPPING")
    # Priority 8: one lease per bush in {DRAFT, PENDING_AUDIT, ACTIVE}
    for other in db.leases.values():
        if (other["sugarbush_id"] == sugarbush_id
                and other["status"] in ("DRAFT", "PENDING_AUDIT", "ACTIVE")):
            raise_err(ERR_LEASE_CONFLICT,
                      "sugarbush already has a lease in DRAFT, PENDING_AUDIT or ACTIVE")

    lease = core.new_lease(
        sugarbush_id=sugarbush_id,
        landowner_name=landowner_name,
        royalty_basis=royalty_basis,
        per_tap_cents=per_tap_cents,
        share_pct=(d(share_pct) if share_pct is not None else None),
        certified_organic_required=certified_organic_required,
        term_start=term_start,
        term_end=term_end,
    )
    db.leases[lease["id"]] = lease
    return success_object(core.ser_lease(lease), status=201)


@bp.get("/sugarhouse/leases/<lid>")
def get_lease(lid):
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    lease = get_lease_or_404(lid)
    return success_object(core.ser_lease(lease))


@bp.get("/sugarhouse/leases")
def list_leases():
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    sugarbush_id = request.args.get("sugarbush_id")
    status = request.args.get("status")
    rows = list(db.leases.values())
    if sugarbush_id is not None:
        rows = [r for r in rows if r["sugarbush_id"] == sugarbush_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(rows, limit, offset)
    return success_list([core.ser_lease(r) for r in page], limit, offset, total)


@bp.patch("/sugarhouse/leases/<lid>")
def amend_lease(lid):
    caller = authenticate()
    require_role(caller, MGR)
    lease = get_lease_or_404(lid)
    data = body_json()
    allowed = {"expected_lease_version", "landowner_name", "royalty_basis",
               "per_tap_cents", "share_pct", "certified_organic_required",
               "term_start", "term_end"}
    check_unknown_fields(data, allowed)
    # OCC (priority 4) — expected_lease_version required; mismatch -> 412
    if "expected_lease_version" not in data:
        raise_err(ERR_VALIDATION, "expected_lease_version is required")
    expected = data["expected_lease_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_VALIDATION, "expected_lease_version must be an integer")
    if expected != lease["version"]:
        raise_err(ERR_STALE_VERSION,
                  f"expected_lease_version {expected} != current {lease['version']}")
    # Priority 5: state gate — only DRAFT or PENDING_AUDIT amendable
    if lease["status"] not in ("DRAFT", "PENDING_AUDIT"):
        raise_err(ERR_INVALID_STATE,
                  f"lease is {lease['status']}, expected DRAFT or PENDING_AUDIT")

    # Apply amendments
    new_basis = lease["royalty_basis"]
    if "royalty_basis" in data:
        new_basis = as_enum(data["royalty_basis"], "royalty_basis",
                            {"PER_TAP", "SHARE_OF_SYRUP"})
    if "landowner_name" in data:
        lease["landowner_name"] = as_str(data["landowner_name"], "landowner_name")
    if "certified_organic_required" in data:
        v = data["certified_organic_required"]
        if not isinstance(v, bool):
            raise_err(ERR_VALIDATION, "certified_organic_required must be a boolean")
        lease["certified_organic_required"] = v
    if "term_start" in data:
        v = as_str(data["term_start"], "term_start")
        try:
            parse_date(v)
        except Exception:
            raise_err(ERR_VALIDATION, "term_start must be a YYYY-MM-DD date")
        lease["term_start"] = v
    if "term_end" in data:
        v = as_str(data["term_end"], "term_end")
        try:
            parse_date(v)
        except Exception:
            raise_err(ERR_VALIDATION, "term_end must be a YYYY-MM-DD date")
        lease["term_end"] = v

    # Conditional-requiredness after basis change: use request's explicit values
    # when present; else retain stored values only if consistent with new basis.
    if new_basis != lease["royalty_basis"]:
        # basis switch: require the new-basis field explicitly in this request
        if new_basis == "PER_TAP":
            if "per_tap_cents" not in data or data["per_tap_cents"] is None:
                raise_err(ERR_VALIDATION,
                          "per_tap_cents required when switching royalty_basis to PER_TAP")
            per_tap = data["per_tap_cents"]
            if isinstance(per_tap, bool) or not isinstance(per_tap, int) or per_tap <= 0:
                raise_err(ERR_VALIDATION, "per_tap_cents must be an integer > 0")
            if data.get("share_pct") is not None and "share_pct" in data:
                raise_err(ERR_VALIDATION,
                          "share_pct must be null when royalty_basis=PER_TAP")
            lease["royalty_basis"] = "PER_TAP"
            lease["per_tap_cents"] = per_tap
            lease["share_pct"] = None
        else:  # SHARE_OF_SYRUP
            if "share_pct" not in data or data["share_pct"] is None:
                raise_err(ERR_VALIDATION,
                          "share_pct required when switching royalty_basis to SHARE_OF_SYRUP")
            v = as_number(data["share_pct"], "share_pct")
            if v <= 0 or v > Decimal("50"):
                raise_err(ERR_VALIDATION, "share_pct must be > 0 and <= 50")
            if data.get("per_tap_cents") is not None and "per_tap_cents" in data:
                raise_err(ERR_VALIDATION,
                          "per_tap_cents must be null when royalty_basis=SHARE_OF_SYRUP")
            lease["royalty_basis"] = "SHARE_OF_SYRUP"
            lease["share_pct"] = v
            lease["per_tap_cents"] = None
    else:
        # basis unchanged: validate any explicit field updates against that basis
        if lease["royalty_basis"] == "PER_TAP":
            if "per_tap_cents" in data:
                v = data["per_tap_cents"]
                if v is None:
                    raise_err(ERR_VALIDATION,
                              "per_tap_cents required when royalty_basis=PER_TAP")
                if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                    raise_err(ERR_VALIDATION, "per_tap_cents must be an integer > 0")
                lease["per_tap_cents"] = v
            if "share_pct" in data and data["share_pct"] is not None:
                raise_err(ERR_VALIDATION,
                          "share_pct must be null when royalty_basis=PER_TAP")
        else:
            if "share_pct" in data:
                v = data["share_pct"]
                if v is None:
                    raise_err(ERR_VALIDATION,
                              "share_pct required when royalty_basis=SHARE_OF_SYRUP")
                v = as_number(v, "share_pct")
                if v <= 0 or v > Decimal("50"):
                    raise_err(ERR_VALIDATION, "share_pct must be > 0 and <= 50")
                lease["share_pct"] = v
            if "per_tap_cents" in data and data["per_tap_cents"] is not None:
                raise_err(ERR_VALIDATION,
                          "per_tap_cents must be null when royalty_basis=SHARE_OF_SYRUP")

    # term_end strictly after term_start
    if parse_date(lease["term_end"]) <= parse_date(lease["term_start"]):
        raise_err(ERR_VALIDATION, "term_end must be after term_start")

    # Revision loop: PENDING_AUDIT -> DRAFT on amendment
    if lease["status"] == "PENDING_AUDIT":
        lease["status"] = "DRAFT"
    core.bump(lease)
    return success_object(core.ser_lease(lease))


@bp.post("/sugarhouse/leases/<lid>/submit-audit")
def submit_audit(lid):
    caller = authenticate()
    require_role(caller, MGR)
    lease = get_lease_or_404(lid)
    if lease["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, f"lease is {lease['status']}, expected DRAFT")
    lease["status"] = "PENDING_AUDIT"
    core.bump(lease)
    return success_object(core.ser_lease(lease))


@bp.post("/sugarhouse/leases/<lid>/activate")
def activate_lease(lid):
    caller = authenticate()
    require_role(caller, MGR)
    lease = get_lease_or_404(lid)
    if lease["status"] != "PENDING_AUDIT":
        raise_err(ERR_INVALID_STATE, f"lease is {lease['status']}, expected PENDING_AUDIT")
    bush = db.sugarbushes.get(lease["sugarbush_id"])
    if not bush:
        raise_err(ERR_NOT_FOUND, f"sugarbush {lease['sugarbush_id']} not found")
    # Priority 5: bush state
    if bush["status"] not in ("PREP", "TAPPING", "LIVE"):
        raise_err(ERR_INVALID_STATE,
                  f"sugarbush is {bush['status']}, expected PREP/TAPPING/LIVE")
    # Priority 6: organic gate
    if lease["certified_organic_required"]:
        latest = core.latest_organic_audit(bush["id"])
        if (not latest or latest["status"] != "RECORDED" or latest["result"] != "PASS"):
            raise_err(ERR_ORGANIC_AUDIT_REQUIRED,
                      "latest ORGANIC audit is not RECORDED with result PASS")
    # Priority 7: temporal term check
    today = clock_date()
    ts = parse_date(lease["term_start"])
    te = parse_date(lease["term_end"])
    if not (ts <= today <= te):
        raise_err(ERR_OUTSIDE_PRODUCTION_WINDOW,
                  "logical clock date outside lease term_start..term_end")

    # Side effects
    lease["taps_snapshot"] = bush["taps_set"]
    bush["active_lease_id"] = lease["id"]
    bush["stand_type"] = "LEASED"
    core.touch(bush)
    if lease["royalty_basis"] == "PER_TAP":
        lease["accrued_royalty_cents"] = lease["taps_snapshot"] * lease["per_tap_cents"]
    lease["status"] = "ACTIVE"
    core.bump(lease)
    return success_object(core.ser_lease(lease))


@bp.post("/sugarhouse/leases/<lid>/terminate")
def terminate_lease(lid):
    caller = authenticate()
    require_role(caller, MGR)
    lease = get_lease_or_404(lid)
    if lease["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, f"lease is {lease['status']}, expected ACTIVE")
    lease["status"] = "TERMINATED"
    bush = db.sugarbushes.get(lease["sugarbush_id"])
    if bush and bush["status"] in ("TAPPING", "LIVE"):
        core.shutdown_bush_cascade(bush, bump_bush=True)
    core.bump(lease)
    return success_object(core.ser_lease(lease))
