"""LabSample and GuaranteedAnalysisReport endpoints."""

from flask import Blueprint

import errors
from db import store
from middleware import (require_roles, get_json_body, require_enum,
                        require_number, parse_pagination, paginate)
from response import success_object, success_list
from services.calculations import (stamp_new, serialize, serialize_list,
                                   compute_per_sample_verdict,
                                   compute_ga_composite, compute_deviation_index,
                                   SAMPLE_TYPE_ORDER)
from routes.production_batches import _get_batch

bp = Blueprint("lab_ga", __name__)

SAMPLE_TYPES = {"FIRST", "MIDDLE", "LAST", "COMPOSITE"}


def _latest_profile_for_formula(formula_id):
    profiles = [p for p in store.nutrient_profiles.values() if p["formula_id"] == formula_id]
    if not profiles:
        return None
    profiles.sort(key=lambda e: (e["_created_at_dt"], e["id"]))
    return profiles[-1]


@bp.route("/production-batches/<id>/lab-samples", methods=["POST"])
def create_lab_sample(id):
    require_roles("QualityAnalyst")
    batch = _get_batch(id)
    body = get_json_body()
    sample_type = require_enum(body, "sample_type", SAMPLE_TYPES)
    measured_protein_pct = require_number(body, "measured_protein_pct")
    measured_fat_pct = require_number(body, "measured_fat_pct")
    measured_fiber_pct = require_number(body, "measured_fiber_pct")
    measured_moisture_pct = require_number(body, "measured_moisture_pct")

    sample = {
        "batch_id": id,
        "sample_type": sample_type,
        "measured_protein_pct": measured_protein_pct,
        "measured_fat_pct": measured_fat_pct,
        "measured_fiber_pct": measured_fiber_pct,
        "measured_moisture_pct": measured_moisture_pct,
        "verdict": "PENDING",
    }
    stamp_new(sample)
    profile = _latest_profile_for_formula(batch["formula_id"])
    sample["verdict"] = compute_per_sample_verdict(sample, profile)
    store.lab_samples[sample["id"]] = sample
    return success_object(serialize(sample), 201)


@bp.route("/production-batches/<id>/lab-samples", methods=["GET"])
def list_lab_samples(id):
    require_roles("PlatformAdmin", "QualityAnalyst", "QAApprover")
    _get_batch(id)
    limit, offset = parse_pagination()
    items = [s for s in store.lab_samples.values() if s["batch_id"] == id]
    items.sort(key=lambda e: (SAMPLE_TYPE_ORDER[e["sample_type"]],
                              e["_created_at_dt"], e["id"]))
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total, 200)


@bp.route("/production-batches/<id>/ga-reports", methods=["POST"])
def create_ga_report(id):
    require_roles("QualityAnalyst")
    batch = _get_batch(id)
    samples = [s for s in store.lab_samples.values()
               if s["batch_id"] == id and s["verdict"] != "PENDING"]
    if not samples:
        raise errors.sample_pending()
    samples.sort(key=lambda e: (SAMPLE_TYPE_ORDER[e["sample_type"]],
                                e["_created_at_dt"], e["id"]))

    composites = compute_ga_composite(samples)
    formula = store.formulas.get(batch["formula_id"])
    profile = _latest_profile_for_formula(batch["formula_id"]) if formula else None
    if profile is not None:
        deviation_index, label_compliance = compute_deviation_index(composites, profile)
    else:
        from decimal import Decimal
        deviation_index, label_compliance = Decimal("0.00"), "COMPLIANT"

    report = {
        "batch_id": id,
        "composite_protein_pct": composites["composite_protein_pct"],
        "composite_fat_pct": composites["composite_fat_pct"],
        "composite_fiber_pct": composites["composite_fiber_pct"],
        "composite_moisture_pct": composites["composite_moisture_pct"],
        "label_compliance": label_compliance,
        "deviation_index": deviation_index,
    }
    stamp_new(report)
    store.ga_reports[report["id"]] = report
    return success_object(serialize(report), 201)


@bp.route("/production-batches/<id>/ga-reports", methods=["GET"])
def list_ga_reports(id):
    require_roles("PlatformAdmin", "QualityAnalyst", "QAApprover")
    _get_batch(id)
    limit, offset = parse_pagination()
    items = [r for r in store.ga_reports.values() if r["batch_id"] == id]
    items.sort(key=lambda e: (e["_created_at_dt"], e["id"]))
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total, 200)
