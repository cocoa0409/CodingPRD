"""Clock, jurisdictions, product classes, tax rates, rate-change notices."""
from flask import Blueprint

import errors
from errors import raise_err
from store import DB
from auth import (
    require_roles, ALL_READ_ROLES, body_dict, req_str, req_int, req_enum, req_dt,
    opt_dt, new_entity, touch, get_or_404, public, paginate,
)
from response import success_object, success_list
from utiltime import fmt_dt, now_dt, parse_dt
import services

bp = Blueprint("config", __name__)

JUR_FIELDS = ["code", "name", "level", "return_frequency", "deposit_frequency", "status"]
PC_FIELDS = ["code", "description", "base_unit", "status"]
RATE_FIELDS = ["jurisdiction_id", "product_class_id", "rate_millicents_per_unit",
               "effective_from", "effective_to", "source_notice_id",
               "supersedes_rate_id", "status"]
NOTICE_FIELDS = ["jurisdiction_id", "product_class_id", "new_rate_millicents_per_unit",
                 "announced_effective_from", "source_reference", "detected_at",
                 "applied_rate_id", "status"]


def ser_jurisdiction(j):
    return public(j, JUR_FIELDS)


def ser_product_class(p):
    return public(p, PC_FIELDS)


def ser_rate(r):
    return public(r, RATE_FIELDS)


def ser_notice(n):
    return public(n, NOTICE_FIELDS)


# ------------------------------------------------------------------ clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles(["ComplianceAdmin"])
    body = body_dict()
    target = req_dt(body, "to_iso8601")
    if target < now_dt():
        raise_err(errors.ERR_INVALID_REQUEST, "The logical clock cannot move backwards")
    DB.clock = target
    services.run_sweep()
    return success_object({"current_utc": fmt_dt(DB.clock)})


# ------------------------------------------------------------------ jurisdictions
@bp.post("/jurisdictions")
def create_jurisdiction():
    require_roles(["ComplianceAdmin"])
    body = body_dict()
    code = req_str(body, "code")
    name = req_str(body, "name")
    level = req_enum(body, "level", {"FEDERAL", "STATE", "LOCAL"})
    return_frequency = req_enum(body, "return_frequency", {"MONTHLY", "QUARTERLY"})
    deposit_frequency = req_enum(body, "deposit_frequency", {"SEMI_MONTHLY", "MONTHLY"})
    if return_frequency == "QUARTERLY" and deposit_frequency == "SEMI_MONTHLY":
        raise_err(errors.ERR_INVALID_REQUEST,
                  "A QUARTERLY jurisdiction must use MONTHLY deposit frequency")
    if any(j["code"] == code for j in DB.jurisdictions.values()):
        raise_err(errors.ERR_DUPLICATE_CODE, f"Jurisdiction code '{code}' already exists")
    jur = new_entity({
        "code": code,
        "name": name,
        "level": level,
        "return_frequency": return_frequency,
        "deposit_frequency": deposit_frequency,
        "status": "ACTIVE",
    })
    DB.jurisdictions[jur["id"]] = jur
    return success_object(ser_jurisdiction(jur), 201)


@bp.get("/jurisdictions/<jid>")
def get_jurisdiction(jid):
    require_roles(ALL_READ_ROLES)
    jur = get_or_404(DB.jurisdictions, jid, "Jurisdiction")
    return success_object(ser_jurisdiction(jur))


# ------------------------------------------------------------------ product classes
@bp.post("/product-classes")
def create_product_class():
    require_roles(["ComplianceAdmin"])
    body = body_dict()
    code = req_str(body, "code")
    description = req_str(body, "description")
    base_unit = req_enum(body, "base_unit", {"GALLON", "PROOF_GALLON", "PACK", "UNIT"})
    if any(p["code"] == code for p in DB.product_classes.values()):
        raise_err(errors.ERR_DUPLICATE_CODE, f"Product class code '{code}' already exists")
    pc = new_entity({
        "code": code,
        "description": description,
        "base_unit": base_unit,
        "status": "ACTIVE",
    })
    DB.product_classes[pc["id"]] = pc
    return success_object(ser_product_class(pc), 201)


@bp.get("/product-classes/<pid>")
def get_product_class(pid):
    require_roles(ALL_READ_ROLES)
    pc = get_or_404(DB.product_classes, pid, "ProductClass")
    return success_object(ser_product_class(pc))


# ------------------------------------------------------------------ tax rates
@bp.post("/tax-rates")
def create_tax_rate():
    require_roles(["ComplianceAdmin"])
    body = body_dict()
    jurisdiction_id = req_str(body, "jurisdiction_id")
    product_class_id = req_str(body, "product_class_id")
    rate_mc = req_int(body, "rate_millicents_per_unit", minimum=0)
    effective_from = req_dt(body, "effective_from")
    effective_to = opt_dt(body, "effective_to")
    if effective_to is not None and effective_to <= effective_from:
        raise_err(errors.ERR_INVALID_REQUEST,
                  "effective_to must lie after effective_from")
    jur = get_or_404(DB.jurisdictions, jurisdiction_id, "Jurisdiction")
    get_or_404(DB.product_classes, product_class_id, "ProductClass")
    for r in DB.tax_rates.values():
        if (r["jurisdiction_id"] == jurisdiction_id
                and r["product_class_id"] == product_class_id
                and r["status"] != "SUPERSEDED"
                and services.rates_overlap(effective_from, effective_to,
                                           r["_effective_from"], r["_effective_to"])):
            raise_err(errors.ERR_RATE_WINDOW_OVERLAP,
                      "Rate window overlaps an existing rate for this jurisdiction/product class")
    rate = new_entity({
        "jurisdiction_id": jurisdiction_id,
        "product_class_id": product_class_id,
        "rate_millicents_per_unit": rate_mc,
        "effective_from": fmt_dt(effective_from),
        "effective_to": fmt_dt(effective_to) if effective_to else None,
        "source_notice_id": None,
        "supersedes_rate_id": None,
        "status": services.rate_status_for(effective_from, effective_to),
        "_effective_from": effective_from,
        "_effective_to": effective_to,
    })
    DB.tax_rates[rate["id"]] = rate
    touch(jur)  # creating a rate bumps the jurisdiction version
    return success_object(ser_rate(rate), 201)


@bp.get("/tax-rates/<rid>")
def get_tax_rate(rid):
    require_roles(ALL_READ_ROLES)
    rate = get_or_404(DB.tax_rates, rid, "TaxRate")
    return success_object(ser_rate(rate))


@bp.get("/tax-rates")
def list_tax_rates():
    require_roles(ALL_READ_ROLES)
    from flask import request
    items = list(DB.tax_rates.values())
    for param in ("jurisdiction_id", "product_class_id", "status",
                  "source_notice_id", "supersedes_rate_id"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    data, limit, offset, total = paginate(items, ser_rate)
    return success_list(data, limit, offset, total)


# ------------------------------------------------------------------ rate change notices
@bp.post("/rate-change-notices")
def create_notice():
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body = body_dict()
    jurisdiction_id = req_str(body, "jurisdiction_id")
    product_class_id = req_str(body, "product_class_id")
    new_rate = req_int(body, "new_rate_millicents_per_unit", minimum=0)
    announced_from = req_dt(body, "announced_effective_from")
    source_reference = req_str(body, "source_reference")
    get_or_404(DB.jurisdictions, jurisdiction_id, "Jurisdiction")
    get_or_404(DB.product_classes, product_class_id, "ProductClass")
    notice = new_entity({
        "jurisdiction_id": jurisdiction_id,
        "product_class_id": product_class_id,
        "new_rate_millicents_per_unit": new_rate,
        "announced_effective_from": fmt_dt(announced_from),
        "source_reference": source_reference,
        "detected_at": fmt_dt(now_dt()),
        "applied_rate_id": None,
        "status": "DETECTED",
        "_announced_from": announced_from,
    })
    DB.rate_notices[notice["id"]] = notice
    return success_object(ser_notice(notice), 201)


@bp.get("/rate-change-notices/<nid>")
def get_notice(nid):
    require_roles(ALL_READ_ROLES)
    notice = get_or_404(DB.rate_notices, nid, "RateChangeNotice")
    return success_object(ser_notice(notice))


@bp.get("/rate-change-notices")
def list_notices():
    require_roles(ALL_READ_ROLES)
    from flask import request
    items = list(DB.rate_notices.values())
    for param in ("jurisdiction_id", "product_class_id", "status", "applied_rate_id"):
        v = request.args.get(param)
        if v is not None:
            items = [n for n in items if n.get(param) == v]
    data, limit, offset, total = paginate(items, ser_notice)
    return success_list(data, limit, offset, total)


@bp.post("/rate-change-notices/<nid>/validate")
def validate_notice(nid):
    require_roles(["TaxReviewer", "ComplianceAdmin"])
    body_dict(require=False)
    notice = get_or_404(DB.rate_notices, nid, "RateChangeNotice")
    if notice["status"] != "DETECTED":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Notice in status {notice['status']} cannot be validated")
    notice["status"] = "VALIDATED"
    touch(notice)
    return success_object(ser_notice(notice))


@bp.post("/rate-change-notices/<nid>/reject")
def reject_notice(nid):
    require_roles(["TaxReviewer", "ComplianceAdmin"])
    body_dict(require=False)
    notice = get_or_404(DB.rate_notices, nid, "RateChangeNotice")
    if notice["status"] not in ("DETECTED", "VALIDATED"):
        raise_err(errors.ERR_INVALID_STATE,
                  f"Notice in status {notice['status']} cannot be rejected")
    notice["status"] = "REJECTED"
    touch(notice)
    return success_object(ser_notice(notice))


@bp.post("/rate-change-notices/<nid>/apply")
def apply_notice(nid):
    require_roles(["ComplianceAdmin"])
    body = body_dict()
    expected_version = req_int(body, "expected_jurisdiction_version")
    notice = get_or_404(DB.rate_notices, nid, "RateChangeNotice")
    if notice["status"] != "VALIDATED":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Notice in status {notice['status']} cannot be applied")
    jur = DB.jurisdictions[notice["jurisdiction_id"]]
    if expected_version != jur["version"]:
        raise_err(errors.ERR_STALE_VERSION,
                  "expected_jurisdiction_version does not match the jurisdiction's current version")

    d_from = notice["_announced_from"]
    pair_rates = [
        r for r in DB.tax_rates.values()
        if r["jurisdiction_id"] == notice["jurisdiction_id"]
        and r["product_class_id"] == notice["product_class_id"]
        and r["status"] != "SUPERSEDED"
    ]
    containing = None
    for r in pair_rates:
        if r["_effective_from"] <= d_from and (r["_effective_to"] is None or d_from < r["_effective_to"]):
            containing = r
            break

    if containing is not None:
        new_to = containing["_effective_to"]
        supersedes_id = containing["id"]
        containing["_effective_to"] = d_from
        containing["effective_to"] = fmt_dt(d_from)
        containing["status"] = "SUPERSEDED"
        touch(containing)
    else:
        supersedes_id = None
        later = [r["_effective_from"] for r in pair_rates if r["_effective_from"] > d_from]
        new_to = min(later) if later else None

    # Supersede any remaining window fully covered by the new window.
    for r in pair_rates:
        if containing is not None and r["id"] == containing["id"]:
            continue
        if r["_effective_from"] >= d_from and (new_to is None or r["_effective_from"] < new_to):
            if new_to is None or (r["_effective_to"] is None or r["_effective_to"] <= new_to):
                r["_effective_to"] = r["_effective_from"]
                r["effective_to"] = r["effective_from"]
                r["status"] = "SUPERSEDED"
                touch(r)

    rate = new_entity({
        "jurisdiction_id": notice["jurisdiction_id"],
        "product_class_id": notice["product_class_id"],
        "rate_millicents_per_unit": notice["new_rate_millicents_per_unit"],
        "effective_from": fmt_dt(d_from),
        "effective_to": fmt_dt(new_to) if new_to else None,
        "source_notice_id": notice["id"],
        "supersedes_rate_id": supersedes_id,
        "status": services.rate_status_for(d_from, new_to),
        "_effective_from": d_from,
        "_effective_to": new_to,
    })
    DB.tax_rates[rate["id"]] = rate

    # Retroactive re-rate cascade: RATED events inside the new window whose
    # containing return is DRAFT/SUBMITTED.
    affected_returns = set()
    affected_registrants = set()
    affected_registrations = set()
    for ev in DB.events.values():
        if ev["jurisdiction_id"] != notice["jurisdiction_id"]:
            continue
        if ev["product_class_id"] != notice["product_class_id"]:
            continue
        if ev["status"] != "RATED":
            continue
        if not (d_from <= ev["_event_dt"] and (new_to is None or ev["_event_dt"] < new_to)):
            continue
        ret = DB.returns.get(ev.get("return_id"))
        if ret is None or ret["filing_status"] not in ("DRAFT", "SUBMITTED"):
            continue
        resolved = services.compute_event_tax(ev)
        if resolved is None:
            continue
        new_rate_row, gross, tax = resolved
        ev["gross_tax_cents"] = gross
        ev["tax_cents"] = tax
        ev["_tax_rate_id"] = new_rate_row["id"]
        ev["_rate_millicents_used"] = new_rate_row["rate_millicents_per_unit"]
        touch(ev)
        affected_returns.add(ret["id"])
    for rid in affected_returns:
        ret = DB.returns[rid]
        services.recompute_return(ret)
        reg = DB.registrations[ret["registration_id"]]
        affected_registrants.add(reg["registrant_id"])
        affected_registrations.add(reg["id"])
    for reg_id in affected_registrations:
        reg = DB.registrations[reg_id]
        services.recompute_bond_requirement(reg)
        services.refresh_deficiency(reg)
    for registrant_id in affected_registrants:
        services.recompute_rollup(registrant_id)

    touch(jur)  # notice application bumps the jurisdiction version exactly once
    notice["status"] = "APPLIED"
    notice["applied_rate_id"] = rate["id"]
    touch(notice)
    return success_object(ser_notice(notice))
