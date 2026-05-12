"""Drug catalog (PRD §3.7)."""
from __future__ import annotations

from flask import Blueprint, g, request

import db
from errors import err
from middleware import authenticate, require_roles
from response import success_object
from services.common import bump, init_full
from validators import (
    require_str,
    _DRUG_CODE_RE,
)

bp = Blueprint("drugs", __name__)

VALID_SEVERITIES = {"MILD", "MODERATE", "SEVERE"}


@bp.before_request
def _auth():
    authenticate()


@bp.post("/drugs")
def create_drug():
    require_roles("PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    code = payload.get("code")
    if not isinstance(code, str) or not _DRUG_CODE_RE.match(code):
        raise err("ERR_VALIDATION_FAILED", "code invalid")
    name = require_str(payload, "name", min_len=1, max_len=80)
    controlled = payload.get("controlled", False)
    if not isinstance(controlled, bool):
        raise err("ERR_VALIDATION_FAILED", "controlled must be bool")
    dmin = payload.get("dosage_min_mg_per_kg")
    dmax = payload.get("dosage_max_mg_per_kg")
    if isinstance(dmin, bool) or not isinstance(dmin, (int, float)) or float(dmin) <= 0:
        raise err("ERR_VALIDATION_FAILED", "dosage_min_mg_per_kg must be > 0")
    if isinstance(dmax, bool) or not isinstance(dmax, (int, float)) or float(dmax) < float(dmin):
        raise err("ERR_VALIDATION_FAILED", "dosage_max_mg_per_kg must be >= min")
    interactions = payload.get("interactions", []) or []
    if not isinstance(interactions, list):
        raise err("ERR_VALIDATION_FAILED", "interactions must be a list")
    for ix in interactions:
        if not isinstance(ix, dict):
            raise err("ERR_VALIDATION_FAILED", "interactions entries must be objects")
        with_code = ix.get("with_drug_code")
        sev = ix.get("severity")
        if not isinstance(with_code, str) or not with_code:
            raise err("ERR_VALIDATION_FAILED", "interactions[].with_drug_code required")
        if sev not in VALID_SEVERITIES:
            raise err("ERR_VALIDATION_FAILED", "interactions[].severity invalid")
    stock = payload.get("stock_units", 0)
    if isinstance(stock, bool) or not isinstance(stock, int) or stock < 0:
        raise err("ERR_VALIDATION_FAILED", "stock_units must be >= 0")

    with db.GLOBAL_LOCK:
        if db.drug_by_code(code):
            raise err("ERR_VALIDATION_FAILED", "drug code must be unique")
        d = {
            "code": code,
            "name": name,
            "controlled": controlled,
            "dosage_min_mg_per_kg": float(dmin),
            "dosage_max_mg_per_kg": float(dmax),
            "interactions": [dict(i) for i in interactions],
            "stock_units": int(stock),
        }
        init_full(d)
        db.drugs[d["id"]] = d
        return success_object(drug_view(d), status=201)


@bp.patch("/drugs/<drug_id>")
def update_drug(drug_id):
    require_roles("PlatformAdmin", "Pharmacist")
    payload = request.get_json(silent=True) or {}
    with db.GLOBAL_LOCK:
        d = db.drugs.get(drug_id)
        if not d:
            raise err("ERR_NOT_FOUND", f"Drug {drug_id} not found")
        if "version" in payload:
            v = payload.get("version")
            if not isinstance(v, int) or v != d.get("version"):
                raise err("ERR_STALE_VERSION", "version mismatch")
        if "stock_units" in payload:
            s = payload["stock_units"]
            if isinstance(s, bool) or not isinstance(s, int) or s < 0:
                raise err("ERR_VALIDATION_FAILED", "stock_units invalid")
            d["stock_units"] = int(s)
        if "interactions" in payload:
            ints = payload["interactions"]
            if not isinstance(ints, list):
                raise err("ERR_VALIDATION_FAILED", "interactions must be a list")
            for ix in ints:
                if not isinstance(ix, dict):
                    raise err("ERR_VALIDATION_FAILED", "interactions invalid")
                if not isinstance(ix.get("with_drug_code"), str):
                    raise err("ERR_VALIDATION_FAILED", "with_drug_code required")
                if ix.get("severity") not in VALID_SEVERITIES:
                    raise err("ERR_VALIDATION_FAILED", "severity invalid")
            d["interactions"] = [dict(i) for i in ints]
        bump(d)
        return success_object(drug_view(d))


def drug_view(d):
    return {
        "id": d["id"],
        "code": d["code"],
        "name": d["name"],
        "controlled": d["controlled"],
        "dosage_min_mg_per_kg": d["dosage_min_mg_per_kg"],
        "dosage_max_mg_per_kg": d["dosage_max_mg_per_kg"],
        "interactions": list(d.get("interactions", [])),
        "stock_units": int(d["stock_units"]),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }
