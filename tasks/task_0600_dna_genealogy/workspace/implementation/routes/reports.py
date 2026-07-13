"""Ancestry and health reports (PRD §3.7)."""
from flask import Blueprint, request

import calc
import db
import services as S
from auth import endpoint, require_owner
from errors import ApiError
from response import ok, paginate
from routes.common import body, require_int

bp = Blueprint("reports", __name__)

REPORT_TYPES = ("ETHNICITY", "HEALTH_TRAIT")
VARIANTS = ("PROVISIONAL", "FINAL")


@bp.post("/dna/customers/<customer_id>/reports")
@endpoint(["Customer"])
def generate_report(customer_id):
    customer = S.get("customers", customer_id)
    require_owner(customer["id"])

    payload = body()
    S.require_fields(payload, ["report_type", "variant", "expected_customer_version"])
    report_type = payload["report_type"]
    variant = payload["variant"]
    S.require_enum(report_type, REPORT_TYPES, "report_type")
    S.require_enum(variant, VARIANTS, "variant")
    expected = require_int(payload["expected_customer_version"], "expected_customer_version")

    if expected != customer["version"]:
        raise ApiError("ERR_STALE_VERSION")

    S.require_not_purged(customer)

    sample = S.source_sample(customer["id"])
    if sample is None:
        raise ApiError("ERR_DNA_NOT_READY")

    if report_type == "HEALTH_TRAIT" and not S.has_live_consent(customer["id"], "HEALTH_TRAITS"):
        raise ApiError("ERR_CONSENT_REQUIRED")
    if variant == "FINAL" and not S.has_live_consent(customer["id"], "RESEARCH"):
        raise ApiError("ERR_CONSENT_REQUIRED")

    if S.access_status_of(customer["id"]) not in ("ACTIVE", "GRACE"):
        raise ApiError("ERR_SUBSCRIPTION_LOCKED")
    if report_type == "HEALTH_TRAIT" and S.tier_of(customer["id"]) not in calc.TIER_HEALTH_REPORTS:
        raise ApiError("ERR_SUBSCRIPTION_LOCKED")

    composition = []
    residual_population = None
    trait_count = 0
    if report_type == "ETHNICITY":
        composition, residual_population = calc.ethnicity_composition(
            sample["population_scores"], variant
        )
    else:
        trait_count = calc.health_trait_count(sample["genotype_markers"])

    report = db.new_record(
        {
            "customer_id": customer["id"],
            "sample_id": sample["id"],
            "report_type": report_type,
            "variant": variant,
            "status": "DRAFT",
            "composition": composition,
            "residual_population": residual_population,
            "trait_count": trait_count,
            "generated_at": None,
        }
    )
    db.db.reports[report["id"]] = report

    # A newer report of the same report_type supersedes the prior PUBLISHED one.
    for other in db.db.reports.values():
        if (
            other["id"] != report["id"]
            and other["customer_id"] == customer["id"]
            and other["report_type"] == report_type
            and other["status"] == "PUBLISHED"
        ):
            other["status"] = "SUPERSEDED"
            db.touch(other)

    report["status"] = "PUBLISHED"
    report["generated_at"] = db.now()

    db.touch(customer)
    return ok(S.report_json(report), 201)


@bp.get("/dna/reports/<report_id>")
@endpoint(["Customer", "PlatformAdmin"])
def read_report(report_id):
    report = S.get("reports", report_id)
    require_owner(report["customer_id"])
    return ok(S.report_json(report))


@bp.get("/dna/reports")
@endpoint(["Customer", "PlatformAdmin"])
def list_reports():
    records = S.all_of("reports")
    customer_id = request.args.get("customer_id")
    sample_id = request.args.get("sample_id")
    report_type = request.args.get("report_type")
    status = request.args.get("status")
    if customer_id:
        records = [r for r in records if r["customer_id"] == customer_id]
    if sample_id:
        records = [r for r in records if r["sample_id"] == sample_id]
    if report_type:
        records = [r for r in records if r["report_type"] == report_type]
    if status:
        records = [r for r in records if r["status"] == status]
    return paginate(records, S.report_json)
