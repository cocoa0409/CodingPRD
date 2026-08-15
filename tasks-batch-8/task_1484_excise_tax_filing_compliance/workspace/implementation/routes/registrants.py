"""Registrants, registrations (lifecycle, bond status, purge), bonds."""
from flask import Blueprint, request

import errors
from errors import raise_err
from store import DB
from auth import (
    require_roles, ALL_READ_ROLES, body_dict, req_str, req_int, req_enum, req_dt,
    new_entity, touch, get_or_404, public, paginate,
)
from response import success_object, success_list
from utiltime import (
    fmt_dt, now_dt, valid_period_key, period_bounds, add_years_safe,
)
import services

bp = Blueprint("registrants", __name__)

REGISTRANT_FIELDS = ["legal_name", "fein", "status", "aggregate_open_liability_cents",
                     "overpayment_balance_cents"]
REGISTRATION_FIELDS = ["registrant_id", "jurisdiction_id", "registration_number",
                       "deposit_method", "status", "bond_required_cents",
                       "bond_coverage_cents", "requirement_variant"]
BOND_FIELDS = ["registration_id", "surety_name", "principal_amount_cents",
               "effective_from", "effective_to", "status"]


def ser_registrant(r):
    return public(r, REGISTRANT_FIELDS)


def ser_registration(r):
    return public(r, REGISTRATION_FIELDS)


def ser_bond(b):
    return public(b, BOND_FIELDS)


# ------------------------------------------------------------------ registrants
@bp.post("/registrants")
def create_registrant():
    require_roles(["ComplianceAdmin"])
    body = body_dict()
    legal_name = req_str(body, "legal_name")
    fein = req_str(body, "fein")
    if any(r["fein"] == fein for r in DB.registrants.values()):
        raise_err(errors.ERR_DUPLICATE_FEIN, f"fein '{fein}' is already registered")
    reg = new_entity({
        "legal_name": legal_name,
        "fein": fein,
        "status": "ACTIVE",
        "aggregate_open_liability_cents": 0,
        "overpayment_balance_cents": 0,
    })
    DB.registrants[reg["id"]] = reg
    return success_object(ser_registrant(reg), 201)


@bp.get("/registrants/<rid>")
def get_registrant(rid):
    require_roles(ALL_READ_ROLES)
    reg = get_or_404(DB.registrants, rid, "Registrant")
    return success_object(ser_registrant(reg))


# ------------------------------------------------------------------ registrations
@bp.post("/registrations")
def create_registration():
    require_roles(["ComplianceAdmin"])
    body = body_dict()
    registrant_id = req_str(body, "registrant_id")
    jurisdiction_id = req_str(body, "jurisdiction_id")
    deposit_method = req_enum(body, "deposit_method", {"SAFE_HARBOR", "ACTUAL"})
    get_or_404(DB.registrants, registrant_id, "Registrant")
    get_or_404(DB.jurisdictions, jurisdiction_id, "Jurisdiction")
    for r in DB.registrations.values():
        if (r["registrant_id"] == registrant_id
                and r["jurisdiction_id"] == jurisdiction_id
                and r["status"] != "REVOKED"):
            raise_err(errors.ERR_DUPLICATE_REGISTRATION,
                      "A non-REVOKED registration already exists for this registrant/jurisdiction")
    reg = new_entity({
        "registrant_id": registrant_id,
        "jurisdiction_id": jurisdiction_id,
        "registration_number": None,
        "deposit_method": deposit_method,
        "status": "PENDING",
        "bond_required_cents": 0,
        "bond_coverage_cents": 0,
        "requirement_variant": "STANDARD",
        "_bond_deficient_since": None,
    })
    DB.registrations[reg["id"]] = reg
    services.recompute_bond_requirement(reg)
    return success_object(ser_registration(reg), 201)


@bp.get("/registrations/<rid>")
def get_registration(rid):
    require_roles(ALL_READ_ROLES)
    reg = get_or_404(DB.registrations, rid, "Registration")
    return success_object(ser_registration(reg))


@bp.get("/registrations")
def list_registrations():
    require_roles(ALL_READ_ROLES)
    items = list(DB.registrations.values())
    for param in ("registrant_id", "jurisdiction_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    data, limit, offset, total = paginate(items, ser_registration)
    return success_list(data, limit, offset, total)


@bp.post("/registrations/<rid>/activate")
def activate_registration(rid):
    require_roles(["ComplianceAdmin"])
    body_dict(require=False)
    reg = get_or_404(DB.registrations, rid, "Registration")
    if reg["status"] != "PENDING":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Registration in status {reg['status']} cannot be activated")
    services.recompute_bond_coverage(reg)
    services.recompute_bond_requirement(reg)
    if reg["bond_coverage_cents"] < reg["bond_required_cents"]:
        raise_err(errors.ERR_BOND_INSUFFICIENT,
                  "Bond coverage is below the required amount")
    jur = DB.jurisdictions[reg["jurisdiction_id"]]
    seq = DB.reg_number_seq.get(jur["id"], 0) + 1
    DB.reg_number_seq[jur["id"]] = seq
    reg["registration_number"] = f"REG-{jur['code']}-{seq}"
    reg["status"] = "ACTIVE"
    touch(reg)
    return success_object(ser_registration(reg))


@bp.post("/registrations/<rid>/suspend")
def suspend_registration(rid):
    require_roles(["ComplianceAdmin"])
    body_dict(require=False)
    reg = get_or_404(DB.registrations, rid, "Registration")
    if reg["status"] != "ACTIVE":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Registration in status {reg['status']} cannot be suspended")
    reg["status"] = "SUSPENDED"
    touch(reg)
    return success_object(ser_registration(reg))


@bp.post("/registrations/<rid>/reinstate")
def reinstate_registration(rid):
    require_roles(["ComplianceAdmin"])
    body_dict(require=False)
    reg = get_or_404(DB.registrations, rid, "Registration")
    if reg["status"] not in ("SUSPENDED", "BOND_DEFICIENT"):
        raise_err(errors.ERR_INVALID_STATE,
                  f"Registration in status {reg['status']} cannot be reinstated")
    if reg["status"] == "SUSPENDED":
        registrant = DB.registrants[reg["registrant_id"]]
        if registrant["status"] != "ACTIVE":
            raise_err(errors.ERR_INVALID_STATE,
                      "Registrant must be ACTIVE to reinstate a suspended registration")
    services.recompute_bond_coverage(reg)
    services.recompute_bond_requirement(reg)
    if reg["bond_coverage_cents"] < reg["bond_required_cents"]:
        raise_err(errors.ERR_BOND_INSUFFICIENT,
                  "Bond coverage is below the required amount")
    reg["status"] = "ACTIVE"
    reg["_bond_deficient_since"] = None
    touch(reg)
    services.check_registrant_recovery(DB.registrants[reg["registrant_id"]])
    return success_object(ser_registration(reg))


@bp.post("/registrations/<rid>/revoke")
def revoke_registration(rid):
    require_roles(["ComplianceAdmin"])
    body_dict(require=False)
    reg = get_or_404(DB.registrations, rid, "Registration")
    if reg["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(errors.ERR_INVALID_STATE,
                  f"Registration in status {reg['status']} cannot be revoked")
    if reg["status"] == "ACTIVE":
        # audit records hold blocks revocation from ACTIVE
        jurisdiction = DB.jurisdictions[reg["jurisdiction_id"]]
        for case in DB.audit_cases.values():
            if (case["registration_id"] == reg["id"]
                    and case["jurisdiction_id"] == reg["jurisdiction_id"]
                    and case["status"] in services.HOLD_STATUSES):
                raise_err(errors.ERR_AUDIT_HOLD,
                          "An audit records hold blocks revocation")
    open_return = any(
        r["registration_id"] == reg["id"]
        and (r["filing_status"] in ("DRAFT", "SUBMITTED")
             or (r["filing_status"] == "FILED" and r["settlement_status"] == "AWAITING_PAYMENT"))
        for r in DB.returns.values()
    )
    if open_return:
        raise_err(errors.ERR_REG_HAS_OPEN_LIABILITY,
                  "Registration has open returns or unsettled filed liability")
    reg["status"] = "REVOKED"
    reg["_bond_deficient_since"] = None
    touch(reg)
    # Cascade: unverified/active certificates -> REVOKED; open movements ->
    # DEFAULTED for the full quantity with the default-assessment cascade suppressed.
    for c in DB.certificates.values():
        if c["registration_id"] == reg["id"] and c["status"] in ("PENDING_VERIFICATION", "ACTIVE"):
            c["status"] = "REVOKED"
            touch(c)
    for m in DB.movements.values():
        if m["registration_id"] == reg["id"] and m["status"] in ("INITIATED", "IN_TRANSIT"):
            m["status"] = "DEFAULTED"
            m["defaulted_quantity_units"] = m["quantity_units"]
            m["_defaulted_at"] = now_dt()
            touch(m)
    services.recompute_rollup(reg["registrant_id"])
    services.check_registrant_recovery(DB.registrants[reg["registrant_id"]])
    services.check_registrant_cancellation(DB.registrants[reg["registrant_id"]])
    return success_object(ser_registration(reg))


@bp.get("/registrations/<rid>/bond-status")
def bond_status(rid):
    require_roles(ALL_READ_ROLES)
    reg = get_or_404(DB.registrations, rid, "Registration")
    services.recompute_bond_coverage(reg)
    services.recompute_bond_requirement(reg)
    return success_object({
        "registration_id": reg["id"],
        "bond_required_cents": reg["bond_required_cents"],
        "bond_coverage_cents": reg["bond_coverage_cents"],
        "requirement_variant": reg["requirement_variant"],
        "deficient": reg["bond_coverage_cents"] < reg["bond_required_cents"],
    })


@bp.post("/registrations/<rid>/purge-expired-records")
def purge_expired_records(rid):
    require_roles(["ComplianceAdmin"])
    body = body_dict()
    period = req_str(body, "period")
    reg = get_or_404(DB.registrations, rid, "Registration")
    jurisdiction = DB.jurisdictions[reg["jurisdiction_id"]]
    if not valid_period_key(period, jurisdiction["return_frequency"]):
        raise_err(errors.ERR_INVALID_REQUEST,
                  "period must match the jurisdiction's period-key shape")
    if services.audit_hold_blocks(reg["id"], reg["jurisdiction_id"], period,
                                  jurisdiction["return_frequency"]):
        raise_err(errors.ERR_AUDIT_HOLD,
                  "An audit records hold covers this period")
    # Retention anchor: filed_at of the latest non-superseded FILED return of
    # the period, else the period end.
    filed = [
        r for r in DB.returns.values()
        if r["registration_id"] == reg["id"]
        and r["period"] == period
        and r["filing_status"] == "FILED"
    ]
    if filed:
        latest = max(filed, key=lambda r: (r["amendment_sequence"], r["_seq"]))
        anchor = parse_dt_or(latest["filed_at"])
    else:
        _start, end = period_bounds(period, jurisdiction["return_frequency"])
        anchor = end
    eligible_from = add_years_safe(anchor, services.RETENTION_YEARS)
    if now_dt() < eligible_from:
        raise_err(errors.ERR_RETENTION_NOT_ELAPSED,
                  "The period's retention anchor has not aged seven years")
    voided = [
        e for e in DB.events.values()
        if e["registration_id"] == reg["id"] and e["period"] == period
        and e["status"] == "VOIDED"
    ]
    superseded = [
        r for r in DB.returns.values()
        if r["registration_id"] == reg["id"] and r["period"] == period
        and r["filing_status"] == "SUPERSEDED"
    ]
    for e in voided:
        del DB.events[e["id"]]
    for r in superseded:
        del DB.returns[r["id"]]
    return success_object({
        "purged_event_count": len(voided),
        "purged_return_count": len(superseded),
    })


def parse_dt_or(value):
    from utiltime import parse_dt
    dt = parse_dt(value)
    return dt if dt is not None else now_dt()


# ------------------------------------------------------------------ bonds
@bp.post("/bonds")
def create_bond():
    require_roles(["ComplianceAdmin"])
    body = body_dict()
    registration_id = req_str(body, "registration_id")
    surety_name = req_str(body, "surety_name")
    principal = req_int(body, "principal_amount_cents", minimum=1)
    effective_from = req_dt(body, "effective_from")
    effective_to = req_dt(body, "effective_to")
    get_or_404(DB.registrations, registration_id, "Registration")
    bond = new_entity({
        "registration_id": registration_id,
        "surety_name": surety_name,
        "principal_amount_cents": principal,
        "effective_from": fmt_dt(effective_from),
        "effective_to": fmt_dt(effective_to),
        "status": "DRAFT",
        "_effective_from": effective_from,
        "_effective_to": effective_to,
    })
    DB.bonds[bond["id"]] = bond
    return success_object(ser_bond(bond), 201)


@bp.get("/bonds/<bid>")
def get_bond(bid):
    require_roles(ALL_READ_ROLES)
    bond = get_or_404(DB.bonds, bid, "Bond")
    return success_object(ser_bond(bond))


@bp.get("/bonds")
def list_bonds():
    require_roles(ALL_READ_ROLES)
    items = list(DB.bonds.values())
    for param in ("registration_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [b for b in items if b.get(param) == v]
    data, limit, offset, total = paginate(items, ser_bond)
    return success_list(data, limit, offset, total)


@bp.post("/bonds/<bid>/activate")
def activate_bond(bid):
    require_roles(["ComplianceAdmin"])
    body_dict(require=False)
    bond = get_or_404(DB.bonds, bid, "Bond")
    if bond["status"] != "DRAFT":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Bond in status {bond['status']} cannot be activated")
    reg = DB.registrations[bond["registration_id"]]
    if reg["status"] not in ("PENDING", "ACTIVE", "BOND_DEFICIENT", "SUSPENDED"):
        raise_err(errors.ERR_INVALID_STATE,
                  f"Registration in status {reg['status']} cannot accept an active bond")
    if bond["_effective_to"] < now_dt():
        raise_err(errors.ERR_BOND_WINDOW_ELAPSED,
                  "The bond's coverage window has fully elapsed")
    bond["status"] = "ACTIVE"
    touch(bond)
    services.recompute_bond_coverage(reg)
    services.recompute_bond_requirement(reg)
    services.refresh_deficiency(reg)
    services.check_registrant_recovery(DB.registrants[reg["registrant_id"]])
    return success_object(ser_bond(bond))


@bp.post("/bonds/<bid>/cancel")
def cancel_bond(bid):
    require_roles(["ComplianceAdmin"])
    body_dict(require=False)
    bond = get_or_404(DB.bonds, bid, "Bond")
    if bond["status"] != "ACTIVE":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Bond in status {bond['status']} cannot be cancelled")
    bond["status"] = "CANCELLED"
    touch(bond)
    reg = DB.registrations[bond["registration_id"]]
    services.recompute_bond_coverage(reg)
    services.recompute_bond_requirement(reg)
    services.refresh_deficiency(reg)
    return success_object(ser_bond(bond))
