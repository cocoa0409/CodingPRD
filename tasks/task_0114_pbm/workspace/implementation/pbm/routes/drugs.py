"""/pbm/drugs — Drug catalogue."""
from __future__ import annotations

import re

from flask import Blueprint, request

from ..auth import require_roles
from ..envelope import success, list_success
from ..errors import (
    APIError,
    ERR_RESOURCE_NOT_FOUND,
    ERR_VALIDATION,
)
from ..store import STORE
from ..validation import (
    as_bool,
    as_nonneg_int,
    get_json_body,
    paginate,
    parse_pagination,
    require_field,
)

bp = Blueprint("drugs", __name__)

_NDC_RE = re.compile(r"^[0-9]{11}$")


def _serialize(d: dict) -> dict:
    return {
        "id": d["id"],
        "ndc": d["ndc"],
        "generic_name": d["generic_name"],
        "brand_name": d["brand_name"],
        "is_specialty": d["is_specialty"],
        "requires_prior_auth": d["requires_prior_auth"],
        "step_therapy_predecessor_ndc": d["step_therapy_predecessor_ndc"],
        "unit_allowed_cents": d["unit_allowed_cents"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


@bp.post("/pbm/drugs")
@require_roles("PBMAdmin")
def create_drug():
    body = get_json_body()
    ndc = require_field(body, "ndc")
    if not isinstance(ndc, str) or not _NDC_RE.match(ndc):
        raise APIError(ERR_VALIDATION, "ndc must be exactly 11 digits", 422)
    generic_name = require_field(body, "generic_name")
    brand_name = require_field(body, "brand_name")
    unit_allowed = as_nonneg_int(require_field(body, "unit_allowed_cents"), "unit_allowed_cents")
    is_specialty = as_bool(body.get("is_specialty", False), "is_specialty", default=False)
    requires_pa = as_bool(body.get("requires_prior_auth", False), "requires_prior_auth", default=False)
    step_pred = body.get("step_therapy_predecessor_ndc")
    if step_pred is not None:
        if not isinstance(step_pred, str) or not _NDC_RE.match(step_pred):
            raise APIError(ERR_VALIDATION, "step_therapy_predecessor_ndc must be 11 digits", 422)

    with STORE.lock:
        # ndc must be unique among ACTIVE drugs
        for existing in STORE.drugs.values():
            if existing["status"] == "ACTIVE" and existing["ndc"] == ndc:
                raise APIError(ERR_VALIDATION, f"ndc {ndc} already exists among ACTIVE drugs", 422)
        drug = STORE.init_common_fields({
            "ndc": ndc,
            "generic_name": generic_name,
            "brand_name": brand_name,
            "is_specialty": is_specialty,
            "requires_prior_auth": requires_pa,
            "step_therapy_predecessor_ndc": step_pred,
            "unit_allowed_cents": unit_allowed,
            "status": "ACTIVE",
        })
        STORE.drugs[drug["id"]] = drug
    return success(_serialize(drug), status=201)


@bp.get("/pbm/drugs")
@require_roles("PBMAdmin", "ClinicalReviewer", "ClaimsAdjudicator", "Prescriber")
def list_drugs():
    limit, offset = parse_pagination()
    ndc_filter = request.args.get("ndc")
    is_specialty_filter = request.args.get("is_specialty")
    status_filter = request.args.get("status")

    with STORE.lock:
        items = list(STORE.drugs.values())
    if ndc_filter:
        items = [d for d in items if d["ndc"] == ndc_filter]
    if is_specialty_filter is not None:
        flag = str(is_specialty_filter).lower() in {"true", "1", "yes"}
        items = [d for d in items if d["is_specialty"] == flag]
    if status_filter:
        items = [d for d in items if d["status"] == status_filter]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    page, total = paginate(items, limit, offset)
    return list_success([_serialize(d) for d in page], limit=limit, offset=offset, total_count=total)


@bp.get("/pbm/drugs/<did>")
@require_roles("PBMAdmin", "ClinicalReviewer", "ClaimsAdjudicator", "Prescriber")
def get_drug(did: str):
    with STORE.lock:
        drug = STORE.drugs.get(did)
    if drug is None:
        raise APIError(ERR_RESOURCE_NOT_FOUND, f"Drug {did} not found", 404)
    return success(_serialize(drug))
