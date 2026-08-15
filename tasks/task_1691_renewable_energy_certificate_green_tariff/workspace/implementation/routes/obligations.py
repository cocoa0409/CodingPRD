"""Compliance obligation endpoints: create, true-up amendment, annual close."""

from flask import Blueprint, request

from errors import raise_err, ERR_VALIDATION, ERR_STALE_VERSION, \
    ERR_OBLIGATION_NOT_OPEN
from store import STORE, new_id, next_seq, now_ts
from util import auth, require_role, ok_object, body_json, req_str, req_int, \
    opt_int, get_or_404
from services import obligation_covered_mwh, touch
from routes.generators import list_with_serializer

bp = Blueprint("obligations", __name__)

DEFAULT_PENALTY_RATE = 5000


def serialize_obligation(o):
    out = {k: v for k, v in o.items() if not k.startswith("_")}
    out["covered_mwh"] = obligation_covered_mwh(o["id"])
    return out


@bp.post("/greenpower/compliance-obligations")
def create_obligation():
    uid, role = auth()
    require_role(role, "ComplianceOfficer")
    body = body_json()
    lse_name = req_str(body, "lse_name")
    year = req_int(body, "year")
    region_code = req_str(body, "region_code")
    required_mwh = req_int(body, "required_mwh")
    if required_mwh <= 0:
        raise_err(ERR_VALIDATION, "required_mwh must be a positive integer")
    penalty_rate = opt_int(body, "penalty_rate_cents_per_mwh", DEFAULT_PENALTY_RATE)
    if penalty_rate < 0:
        raise_err(ERR_VALIDATION,
                  "penalty_rate_cents_per_mwh must be a non-negative integer")
    now = now_ts()
    ob = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "lse_name": lse_name,
        "year": year,
        "region_code": region_code,
        "required_mwh": required_mwh,
        "penalty_rate_cents_per_mwh": penalty_rate,
        "status": "OPEN",
        "penalty_cents": None,
        "_seq": next_seq(),
    }
    STORE["obligations"][ob["id"]] = ob
    return ok_object(serialize_obligation(ob), 201)


@bp.get("/greenpower/compliance-obligations")
def list_obligations():
    auth()
    filters = {
        "year": request.args.get("year"),
        "status": request.args.get("status"),
        "region_code": request.args.get("region_code"),
    }
    return list_with_serializer(list(STORE["obligations"].values()), filters,
                                serialize_obligation)


@bp.get("/greenpower/compliance-obligations/<oid>")
def get_obligation(oid):
    auth()
    ob = get_or_404(STORE["obligations"], oid, "ComplianceObligation")
    return ok_object(serialize_obligation(ob))


@bp.patch("/greenpower/compliance-obligations/<oid>")
def patch_obligation(oid):
    uid, role = auth()
    require_role(role, "ComplianceOfficer")
    body = body_json()
    expected = req_int(body, "expected_obligation_version")
    updates = {}
    if "required_mwh" in body and body["required_mwh"] is not None:
        v = req_int(body, "required_mwh")
        if v <= 0:
            raise_err(ERR_VALIDATION, "required_mwh must be a positive integer")
        updates["required_mwh"] = v
    if "penalty_rate_cents_per_mwh" in body and body["penalty_rate_cents_per_mwh"] is not None:
        v = req_int(body, "penalty_rate_cents_per_mwh")
        if v < 0:
            raise_err(ERR_VALIDATION,
                      "penalty_rate_cents_per_mwh must be a non-negative integer")
        updates["penalty_rate_cents_per_mwh"] = v

    ob = get_or_404(STORE["obligations"], oid, "ComplianceObligation")
    if expected != ob["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_obligation_version does not match the current obligation version")
    if ob["status"] not in ("OPEN", "MET"):
        raise_err(ERR_OBLIGATION_NOT_OPEN,
                  "Only an OPEN or MET obligation may be amended")

    # Pinned evaluation order: freeze coverage, apply the amendment, then
    # re-derive MET/OPEN, then persist — one atomic mutation, one version bump.
    covered = obligation_covered_mwh(oid)
    for key, value in updates.items():
        ob[key] = value
    ob["status"] = "MET" if covered >= ob["required_mwh"] else "OPEN"
    touch(ob)
    return ok_object(serialize_obligation(ob))


@bp.post("/greenpower/compliance-obligations/<oid>/close")
def close_obligation(oid):
    uid, role = auth()
    require_role(role, "ComplianceOfficer")
    ob = get_or_404(STORE["obligations"], oid, "ComplianceObligation")
    if ob["status"] not in ("OPEN", "MET"):
        raise_err(ERR_OBLIGATION_NOT_OPEN,
                  "Only an OPEN or MET obligation may be closed")
    covered = obligation_covered_mwh(oid)
    if covered >= ob["required_mwh"]:
        ob["status"] = "CLOSED_MET"
        ob["penalty_cents"] = 0
    else:
        ob["status"] = "CLOSED_SHORTFALL"
        ob["penalty_cents"] = (ob["required_mwh"] - covered) * ob["penalty_rate_cents_per_mwh"]
    touch(ob)
    return ok_object(serialize_obligation(ob))
