"""DustSample endpoints."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_NOT_FOUND
from middleware import require_roles
from response import success_object
from services import calculations as calc
from services.common import (
    get_flat_or_404,
    get_site_or_404,
    init_common,
    paginate,
    parse_body,
    require_fields,
    serialize,
    touch,
    validate_number,
    validate_str,
)

bp = Blueprint("dust_samples", __name__)

READ_ROLES = ("ComplianceEngineer", "ComplianceManager", "InspectorUser")


def _get_sample(site_id, sample_id):
    site = get_site_or_404(site_id)
    sample = db.dust_samples.get(sample_id)
    if sample is None or sample["site_id"] != site["id"]:
        raise ApiError(ERR_NOT_FOUND, f"DustSample {sample_id} not found", 404)
    return site, sample


@bp.route("/api/sites/<id>/dust-samples", methods=["POST"])
def create_sample(id):
    require_roles("ComplianceEngineer")
    site = get_site_or_404(id)
    body = parse_body()
    require_fields(body, ["material_name", "kst_bar_m_per_s", "pmax_bar_g", "mie_mj", "lab_report_ref"])
    validate_str(body, "material_name")
    validate_str(body, "lab_report_ref")
    validate_number(body, "kst_bar_m_per_s", ge=0)
    validate_number(body, "pmax_bar_g", gt=0)
    validate_number(body, "mie_mj", gt=0)

    sample = {
        "site_id": site["id"],
        "material_name": body["material_name"],
        "kst_bar_m_per_s": body["kst_bar_m_per_s"],
        "pmax_bar_g": body["pmax_bar_g"],
        "mie_mj": body["mie_mj"],
        "lab_report_ref": body["lab_report_ref"],
    }
    init_common(sample)
    calc.kst_classify(sample, site)
    db.dust_samples[sample["id"]] = sample
    return success_object(serialize(sample), 201)


@bp.route("/api/sites/<id>/dust-samples", methods=["GET"])
def list_samples(id):
    require_roles(*READ_ROLES)
    site = get_site_or_404(id)
    items = [s for s in db.dust_samples.values() if s["site_id"] == site["id"]]
    filters = {}
    if request.args.get("sample_class") is not None:
        filters["sample_class"] = "sample_class"
    return paginate(items, filters)


@bp.route("/api/sites/<id>/dust-samples/<sample_id>", methods=["GET"])
def get_sample(id, sample_id):
    require_roles(*READ_ROLES)
    _, sample = _get_sample(id, sample_id)
    return success_object(serialize(sample), 200)


@bp.route("/api/sites/<id>/dust-samples/<sample_id>", methods=["PATCH"])
def update_sample(id, sample_id):
    require_roles("ComplianceEngineer")
    site, sample = _get_sample(id, sample_id)
    body = parse_body()
    validate_str(body, "material_name")
    validate_str(body, "lab_report_ref")
    validate_number(body, "kst_bar_m_per_s", ge=0)
    validate_number(body, "pmax_bar_g", gt=0)
    validate_number(body, "mie_mj", gt=0)

    changed = False
    for f in ("material_name", "kst_bar_m_per_s", "pmax_bar_g", "mie_mj", "lab_report_ref"):
        if f in body and body[f] is not None:
            sample[f] = body[f]
            changed = True
    if changed:
        calc.kst_classify(sample, site)
        touch(sample)
        # Recompute explosion protection design on referencing collectors
        for col in db.collectors.values():
            if col.get("dust_sample_id") == sample["id"]:
                calc.explosion_protection_design(col, sample)
                touch(col)
        # Recompute rollup/risk on linking DHAs
        for dha_id, sample_ids in db.dha_samples.items():
            if sample["id"] in sample_ids:
                dha = db.dhas.get(dha_id)
                if dha:
                    calc.dha_kst_rollup(dha)
                    calc.dha_risk_score(dha, site)
                    touch(dha)
    return success_object(serialize(sample), 200)


# ----- Flat GET -----
@bp.route("/api/dust-samples/<id>", methods=["GET"])
def get_sample_flat(id):
    require_roles(*READ_ROLES)
    sample = get_flat_or_404(db.dust_samples, id, "DustSample")
    return success_object(serialize(sample), 200)


@bp.route("/api/dust-samples/<id>/collectors", methods=["GET"])
def list_sample_collectors(id):
    require_roles(*READ_ROLES)
    sample = get_flat_or_404(db.dust_samples, id, "DustSample")
    items = [c for c in db.collectors.values() if c.get("dust_sample_id") == sample["id"]]
    return paginate(items)
