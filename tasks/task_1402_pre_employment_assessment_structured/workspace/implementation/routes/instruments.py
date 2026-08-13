"""Instruments and validation evidence (PRD §3.2)."""
import db
import serializers
import util
from errors import (api_err, err_invalid_request, err_not_found,
                    err_ref_not_found, err_ownership)
from flask import Blueprint
from middleware import authenticate, require_roles
from response import success_object
from util import (bump, filter_params, new_id, next_seq, paginate, parse_dt,
                  req_enum, req_int, req_string, sort_records)

bp = Blueprint("instruments", __name__)

TYPES = ["COGNITIVE_ABILITY", "PERSONALITY", "SKILLS_SIMULATION", "JOB_KNOWLEDGE"]
EVIDENCE_TYPES = ["CRITERION", "CONTENT", "CONSTRUCT"]


def _get_instrument_or_404(iid):
    inst = db.stores["instruments"].get(iid)
    if inst is None:
        raise err_not_found("Instrument not found")
    return inst


def _vendor_gate(inst):
    v = db.stores["vendors"].get(inst["vendor_id"])
    if v is None or v["status"] != "ACTIVE":
        raise api_err("ERR_VENDOR_NOT_ACTIVE", "Vendor must be ACTIVE")
    return v


@bp.post("/talent/instruments")
def create_instrument():
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    body = util.get_body()
    # Body FK resolution (priority 4)
    vendor_id = body.get("vendor_id")
    if not isinstance(vendor_id, str):
        raise err_invalid_request("vendor_id is required")
    vendor = db.stores["vendors"].get(vendor_id)
    if vendor is None:
        raise err_ref_not_found("vendor_id does not resolve")
    code = req_string(body, "code")
    itype = req_enum(body, "instrument_type", TYPES)
    title = req_string(body, "title")
    max_score = req_int(body, "max_score", lo=1)
    pass_floor = req_int(body, "pass_floor", lo=0)
    if pass_floor >= max_score:
        raise err_invalid_request("pass_floor must be strictly below max_score")
    aim = body.get("adverse_impact_monitor_enabled", True)
    if not isinstance(aim, bool):
        raise err_invalid_request("adverse_impact_monitor_enabled must be a boolean")
    # Business safety: vendor must be ACTIVE (tier 9)
    if vendor["status"] != "ACTIVE":
        raise api_err("ERR_VENDOR_NOT_ACTIVE", "Vendor must be ACTIVE")
    # Uniqueness (vendor_id, code) (tier 10)
    for other in db.stores["instruments"].values():
        if other["vendor_id"] == vendor_id and other["code"] == code:
            raise api_err("ERR_DUPLICATE_INSTRUMENT_CODE",
                          "code already registered under this vendor")
    now = db.get_now()
    rec = {
        "id": new_id(),
        "vendor_id": vendor_id,
        "code": code,
        "instrument_type": itype,
        "title": title,
        "max_score": max_score,
        "pass_floor": pass_floor,
        "validation_status": "DRAFT",
        "validity_expires_at": None,
        "vendor_suspended": False,
        "adverse_impact_monitor_enabled": aim,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created": now,
        "_seq": next_seq(),
    }
    db.stores["instruments"][rec["id"]] = rec
    return success_object(serializers.instrument(rec), 201)


@bp.get("/talent/instruments")
def list_instruments():
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin", "ComplianceOfficer",
                        "VendorRepresentative", "HiringManager"])
    filters = filter_params(["vendor_id", "validation_status"])
    recs = []
    for inst in sort_records(list(db.stores["instruments"].values())):
        if "vendor_id" in filters and inst["vendor_id"] != filters["vendor_id"]:
            continue
        if ("validation_status" in filters
                and inst["validation_status"] != filters["validation_status"]):
            continue
        recs.append(serializers.instrument(inst))
    return paginate(recs)


@bp.get("/talent/instruments/<iid>")
def get_instrument(iid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin", "ComplianceOfficer",
                        "VendorRepresentative", "HiringManager"])
    inst = _get_instrument_or_404(iid)
    return success_object(serializers.instrument(inst))


@bp.post("/talent/instruments/<iid>/submit-validation-review")
def submit_validation_review(iid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    inst = _get_instrument_or_404(iid)
    if inst["validation_status"] != "DRAFT":
        raise api_err("ERR_INVALID_STATE",
                      "Instrument must be DRAFT to submit for validation review")
    _vendor_gate(inst)
    has_any = any(e["instrument_id"] == iid for e in db.stores["evidence"].values())
    if not has_any:
        raise api_err("ERR_EVIDENCE_TYPE_MISSING",
                      "At least one ValidationEvidence must be filed")
    inst["validation_status"] = "VALIDATION_REVIEW"
    bump(inst)
    return success_object(serializers.instrument(inst))


def _current_evidence(inst_id, etype, now):
    """Evidence of a type that is current: effective_from <= now AND
    effective_until > now (closed start, open end)."""
    out = []
    for e in db.stores["evidence"].values():
        if e["instrument_id"] != inst_id or e["evidence_type"] != etype:
            continue
        if e["effective_from"] <= now and e["effective_until"] > now:
            out.append(e)
    return out


def _typed_evidence(inst_id, etype):
    return [e for e in db.stores["evidence"].values()
            if e["instrument_id"] == inst_id and e["evidence_type"] == etype]


@bp.post("/talent/instruments/<iid>/validate")
def validate_instrument(iid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    inst = _get_instrument_or_404(iid)
    if inst["validation_status"] not in ("VALIDATION_REVIEW", "REVALIDATION"):
        raise api_err("ERR_INVALID_STATE",
                      "Instrument must be VALIDATION_REVIEW or REVALIDATION")
    _vendor_gate(inst)
    now = db.get_now()
    # Tier order: expired-but-present (tier 11) surfaces before entirely
    # missing (tier 13) when both types fail simultaneously.
    expired_types = []
    missing_types = []
    for etype in ("CRITERION", "CONTENT"):
        typed = _typed_evidence(iid, etype)
        if not typed:
            missing_types.append(etype)
        elif not _current_evidence(iid, etype, now):
            expired_types.append(etype)
    if expired_types:
        raise api_err("ERR_EVIDENCE_EXPIRED",
                      f"No current {expired_types[0]} evidence")
    if missing_types:
        raise api_err("ERR_EVIDENCE_TYPE_MISSING",
                      f"No {missing_types[0]} evidence filed")
    current_all = (_current_evidence(iid, "CRITERION", now)
                   + _current_evidence(iid, "CONTENT", now))
    inst["validity_expires_at"] = min(e["effective_until"] for e in current_all)
    inst["validation_status"] = "VALIDATED"
    bump(inst)
    return success_object(serializers.instrument(inst))


@bp.post("/talent/instruments/<iid>/begin-revalidation")
def begin_revalidation(iid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    inst = _get_instrument_or_404(iid)
    if inst["validation_status"] != "EXPIRED":
        raise api_err("ERR_INVALID_STATE", "Instrument must be EXPIRED")
    # at least 1 CRITERION evidence with filed_at > validity_expires_at
    ok = any(
        e["instrument_id"] == iid and e["evidence_type"] == "CRITERION"
        and inst["validity_expires_at"] is not None
        and e["filed_at"] > inst["validity_expires_at"]
        for e in db.stores["evidence"].values()
    )
    if not ok:
        raise api_err("ERR_EVIDENCE_TYPE_MISSING",
                      "No CRITERION evidence filed after validity_expires_at")
    inst["validation_status"] = "REVALIDATION"
    bump(inst)
    return success_object(serializers.instrument(inst))


@bp.post("/talent/instruments/<iid>/retire")
def retire_instrument(iid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    inst = _get_instrument_or_404(iid)
    if inst["validation_status"] == "RETIRED":
        raise api_err("ERR_INVALID_STATE", "Instrument already RETIRED")
    if inst["validation_status"] == "VALIDATED":
        raise api_err("ERR_INVALID_STATE",
                      "Retire admitted only from DRAFT, VALIDATION_REVIEW, REVALIDATION, EXPIRED")
    # blocked while any non-CLOSED cycle references it
    for cyc in db.stores["cycles"].values():
        if cyc["instrument_id"] == iid and cyc["posture"] != "CLOSED":
            raise api_err("ERR_INVALID_STATE",
                          "A non-CLOSED cycle references this instrument")
    inst["validation_status"] = "RETIRED"
    bump(inst)
    return success_object(serializers.instrument(inst))


@bp.post("/talent/instruments/<iid>/evidence")
def file_evidence(iid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin", "VendorRepresentative"])
    inst = _get_instrument_or_404(iid)
    if ctx.role == "VendorRepresentative" and ctx.user_id != inst["vendor_id"]:
        raise err_ownership("VendorRepresentative may only file for own vendor")
    body = util.get_body()
    etype = req_enum(body, "evidence_type", EVIDENCE_TYPES)
    title = req_string(body, "title")
    issuer = req_string(body, "issuer")
    effective_from = parse_dt(body.get("effective_from"), "effective_from")
    effective_until = parse_dt(body.get("effective_until"), "effective_until")
    if effective_until <= effective_from:
        raise err_invalid_request("effective_until must be strictly after effective_from")
    now = db.get_now()
    rec = {
        "id": new_id(),
        "instrument_id": iid,
        "evidence_type": etype,
        "title": title,
        "issuer": issuer,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "filed_at": now,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created": now,
        "_seq": next_seq(),
    }
    db.stores["evidence"][rec["id"]] = rec
    return success_object(serializers.evidence(rec), 201)


@bp.get("/talent/instruments/<iid>/evidence")
def list_evidence(iid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin", "ComplianceOfficer", "VendorRepresentative"])
    inst = _get_instrument_or_404(iid)
    if ctx.role == "VendorRepresentative" and ctx.user_id != inst["vendor_id"]:
        raise err_ownership("VendorRepresentative may only read own vendor's evidence")
    recs = [serializers.evidence(e) for e in sort_records(
        [e for e in db.stores["evidence"].values() if e["instrument_id"] == iid])]
    return paginate(recs)
