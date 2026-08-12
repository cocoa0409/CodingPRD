"""Products, label approvals, licenses, excise reports, compliance events."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_DUPLICATE_LABEL_MARKET,
    ERR_DUPLICATE_SKU,
    ERR_LABEL_NOT_APPROVED,
    ERR_PERIOD_NOT_CLOSED,
    ERR_DUPLICATE_REPORT,
    invalid_state,
    not_found,
    validation,
)
from middleware import require_roles
from response import paginate, parse_ts, success_object
from services import (
    LICENSE_KINDS,
    MARKETS,
    PRODUCT_STYLES,
    REGULATORS,
    emit_event,
    expired,
    period_bounds,
    recompute_excise_report,
    ser_compliance_event,
    ser_excise_report,
    ser_label_approval,
    ser_license,
    ser_product,
)

bp = Blueprint("compliance", __name__, url_prefix="/cidery")


def body():
    return request.get_json(silent=True) or {}


def _get_product(productId):
    rec = db.store["products"].get(productId)
    if rec is None:
        raise not_found("product")
    return rec


def _get_label(label_id):
    rec = db.store["label_approvals"].get(label_id)
    if rec is None:
        raise not_found("label approval")
    return rec


def _get_license(license_id):
    rec = db.store["licenses"].get(license_id)
    if rec is None:
        raise not_found("license")
    return rec


def _get_report(report_id):
    rec = db.store["excise_reports"].get(report_id)
    if rec is None:
        raise not_found("excise report")
    return rec


# --- CiderProduct ----------------------------------------------------------------
@bp.post("/products")
@require_roles("ComplianceOfficer")
def create_product():
    b = body()
    style = b.get("style")
    if style is not None and style not in PRODUCT_STYLES:
        raise validation(f"style must be one of {sorted(PRODUCT_STYLES)}")
    sku = b.get("sku")
    if any(p["sku"] == sku for p in db.store["products"].values()):
        raise ApiError(ERR_DUPLICATE_SKU, "sku already in use", 409)
    rec = {
        "sku": sku,
        "name": b.get("name"),
        "style": style,
        "target_abv_pct": b.get("target_abv_pct"),
        "abv_tolerance_pct": b.get("abv_tolerance_pct", 0.3),
        "vintage_year": b.get("vintage_year"),
        "status": "DRAFT",
    }
    db.stamp_new(rec)
    db.store["products"][rec["id"]] = rec
    return success_object(ser_product(rec), 201)


@bp.get("/products/<productId>")
@require_roles("ComplianceOfficer", "SalesRep", "PackagingOperator", "PlatformAdmin")
def get_product(productId):
    return success_object(ser_product(_get_product(productId)))


@bp.get("/products")
@require_roles("ComplianceOfficer", "SalesRep", "PackagingOperator", "PlatformAdmin")
def list_products():
    items = list(db.store["products"].values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(items, ser_product)


def _has_approved_federal_label(product_id):
    return any(
        la["product_id"] == product_id
        and la["market"] == "FEDERAL_TTB"
        and la["status"] == "APPROVED"
        and not expired(la)
        for la in db.store["label_approvals"].values()
    )


@bp.post("/products/<productId>/activate")
@require_roles("ComplianceOfficer")
def activate_product(productId):
    product = _get_product(productId)
    if product["status"] not in ("DRAFT", "RETIRED"):
        raise invalid_state("product cannot be activated from its current state")
    if not _has_approved_federal_label(product["id"]):
        raise ApiError(
            ERR_LABEL_NOT_APPROVED,
            "no APPROVED FEDERAL_TTB label approval for product",
            409,
        )
    if product["status"] == "DRAFT":
        target = product["target_abv_pct"]
        if target is None or not (target > 0.5 and target <= 8.5):
            raise invalid_state("target_abv_pct outside the cider tax class (0.5, 8.5]")
    before = {"status": product["status"]}
    product["status"] = "ACTIVE"
    db.bump(product)
    if before["status"] == "DRAFT":
        emit_event(
            "CiderProduct", product["id"], "PRODUCT_ACTIVATED",
            before, {"status": "ACTIVE"},
        )
    return success_object(ser_product(product))


@bp.post("/products/<productId>/retire")
@require_roles("ComplianceOfficer")
def retire_product(productId):
    product = _get_product(productId)
    if product["status"] != "ACTIVE":
        raise invalid_state("product is not ACTIVE")
    if any(
        r["product_id"] == product["id"] and r["status"] == "SCHEDULED"
        for r in db.store["packaging_runs"].values()
    ):
        raise invalid_state("product has a SCHEDULED packaging run")
    if any(
        o["product_id"] == product["id"] and o["status"] in ("DRAFT", "CONFIRMED")
        for o in db.store["orders"].values()
    ):
        raise invalid_state("product has open sales orders")
    product["status"] = "RETIRED"
    db.bump(product)
    return success_object(ser_product(product))


# --- LabelApproval ---------------------------------------------------------------
@bp.post("/products/<productId>/label-approvals")
@require_roles("ComplianceOfficer")
def create_label_approval(productId):
    product = _get_product(productId)
    b = body()
    market = b.get("market")
    if market is not None and market not in MARKETS:
        raise validation(f"market must be one of {sorted(MARKETS)}")
    if any(
        la["product_id"] == product["id"] and la["market"] == market
        for la in db.store["label_approvals"].values()
    ):
        raise ApiError(
            ERR_DUPLICATE_LABEL_MARKET,
            "label approval already exists for (product, market)",
            409,
        )
    try:
        expires_at = parse_ts(b.get("expires_at"))
    except (TypeError, ValueError):
        raise validation("expires_at must be an ISO8601 timestamp")
    rec = {
        "product_id": product["id"],
        "market": market,
        "application_number": b.get("application_number"),
        "submitted_at": db.now(),
        "approved_at": None,
        "expires_at": expires_at,
        "status": "SUBMITTED",
    }
    db.stamp_new(rec)
    db.store["label_approvals"][rec["id"]] = rec
    return success_object(ser_label_approval(rec), 201)


@bp.get("/label-approvals/<id>")
@require_roles("ComplianceOfficer", "PackagingOperator", "PlatformAdmin")
def get_label_approval(id):
    return success_object(ser_label_approval(_get_label(id)))


@bp.get("/products/<productId>/label-approvals")
@require_roles("ComplianceOfficer", "PackagingOperator", "SalesRep", "PlatformAdmin")
def list_product_label_approvals(productId):
    product = _get_product(productId)
    items = [
        la for la in db.store["label_approvals"].values()
        if la["product_id"] == product["id"]
    ]
    status = request.args.get("status")
    if status is not None:
        items = [la for la in items if la["status"] == status]
    return paginate(items, ser_label_approval)


@bp.get("/label-approvals")
@require_roles("ComplianceOfficer", "PackagingOperator", "SalesRep", "PlatformAdmin")
def list_label_approvals():
    items = list(db.store["label_approvals"].values())
    product_id = request.args.get("product_id")
    if product_id is not None:
        items = [la for la in items if la["product_id"] == product_id]
    market = request.args.get("market")
    if market is not None:
        items = [la for la in items if la["market"] == market]
    status = request.args.get("status")
    if status is not None:
        items = [la for la in items if la["status"] == status]
    return paginate(items, ser_label_approval)


@bp.post("/label-approvals/<id>/approve")
@require_roles("ComplianceOfficer")
def approve_label(id):
    la = _get_label(id)
    if la["status"] != "SUBMITTED":
        raise invalid_state("label approval is not SUBMITTED")
    if not la.get("application_number"):
        raise invalid_state("application_number must be non-empty")
    la["status"] = "APPROVED"
    la["approved_at"] = db.now()
    db.bump(la)
    return success_object(ser_label_approval(la))


@bp.post("/label-approvals/<id>/reject")
@require_roles("ComplianceOfficer")
def reject_label(id):
    la = _get_label(id)
    if la["status"] != "SUBMITTED":
        raise invalid_state("label approval is not SUBMITTED")
    la["status"] = "REJECTED"
    db.bump(la)
    return success_object(ser_label_approval(la))


@bp.post("/label-approvals/<id>/resubmit")
@require_roles("ComplianceOfficer")
def resubmit_label(id):
    la = _get_label(id)
    if la["status"] != "REJECTED":
        raise invalid_state("label approval is not REJECTED")
    b = body()
    app_no = b.get("application_number")
    if not app_no:
        raise validation("application_number is required for resubmission")
    la["application_number"] = app_no
    la["status"] = "SUBMITTED"
    la["submitted_at"] = db.now()
    db.bump(la)
    return success_object(ser_label_approval(la))


# --- LicensePermit -----------------------------------------------------------------
@bp.post("/licenses")
@require_roles("ComplianceOfficer")
def create_license():
    b = body()
    kind = b.get("kind")
    if kind is not None and kind not in LICENSE_KINDS:
        raise validation(f"kind must be one of {sorted(LICENSE_KINDS)}")
    try:
        issued_at = parse_ts(b.get("issued_at"))
        expires_at = parse_ts(b.get("expires_at"))
    except (TypeError, ValueError):
        raise validation("issued_at and expires_at must be ISO8601 timestamps")
    rec = {
        "kind": kind,
        "license_number": b.get("license_number"),
        "issued_at": issued_at,
        "expires_at": expires_at,
        "scope_states": b.get("scope_states") or [],
        "annual_volume_cap_liters": b.get("annual_volume_cap_liters", 0),
        "volume_used_liters": 0,
        "status": "ACTIVE",
    }
    db.stamp_new(rec)
    db.store["licenses"][rec["id"]] = rec
    return success_object(ser_license(rec), 201)


@bp.get("/licenses/<id>")
@require_roles("ComplianceOfficer", "PackagingOperator", "SalesRep", "PlatformAdmin")
def get_license(id):
    return success_object(ser_license(_get_license(id)))


@bp.get("/licenses")
@require_roles("ComplianceOfficer", "PackagingOperator", "SalesRep", "PlatformAdmin")
def list_licenses():
    items = list(db.store["licenses"].values())
    status = request.args.get("status")
    if status is not None:
        items = [x for x in items if x["status"] == status]
    kind = request.args.get("kind")
    if kind is not None:
        items = [x for x in items if x["kind"] == kind]
    return paginate(items, ser_license)


@bp.post("/licenses/<id>/suspend")
@require_roles("ComplianceOfficer")
def suspend_license(id):
    lic = _get_license(id)
    if lic["status"] not in ("ACTIVE", "REINSTATED"):
        raise invalid_state("license cannot be suspended from its current state")
    lic["status"] = "SUSPENDED"
    db.bump(lic)
    return success_object(ser_license(lic))


@bp.post("/licenses/<id>/reinstate")
@require_roles("ComplianceOfficer")
def reinstate_license(id):
    lic = _get_license(id)
    if lic["status"] != "SUSPENDED":
        raise invalid_state("license is not SUSPENDED")
    lic["status"] = "REINSTATED"
    db.bump(lic)
    return success_object(ser_license(lic))


# --- ExciseReport --------------------------------------------------------------------
@bp.post("/excise-reports")
@require_roles("ComplianceOfficer")
def create_excise_report():
    b = body()
    regulator = b.get("regulator")
    if regulator is not None and regulator not in REGULATORS:
        raise validation(f"regulator must be one of {sorted(REGULATORS)}")
    year = b.get("period_year")
    month = b.get("period_month")
    if not isinstance(year, int) or not isinstance(month, int) or not (1 <= month <= 12):
        raise validation("period_year must be an int and period_month in 1..12")
    if any(
        r["period_year"] == year and r["period_month"] == month
        and r["regulator"] == regulator and r["status"] == "OPEN"
        for r in db.store["excise_reports"].values()
    ):
        raise ApiError(
            ERR_DUPLICATE_REPORT,
            "an OPEN report already exists for (period_year, period_month, regulator)",
            409,
        )
    rec = {
        "period_year": year,
        "period_month": month,
        "regulator": regulator,
        "taxable_liters": 0,
        "taxable_cents": 0,
        "filed_at": None,
        "status": "OPEN",
    }
    db.stamp_new(rec)
    db.store["excise_reports"][rec["id"]] = rec
    return success_object(ser_excise_report(rec), 201)


@bp.get("/excise-reports/<id>")
@require_roles("ComplianceOfficer", "PlatformAdmin")
def get_excise_report(id):
    rep = _get_report(id)
    if rep["status"] == "OPEN":
        recompute_excise_report(rep)
    return success_object(ser_excise_report(rep))


@bp.get("/excise-reports")
@require_roles("ComplianceOfficer", "PlatformAdmin")
def list_excise_reports():
    items = list(db.store["excise_reports"].values())
    for rep in items:
        if rep["status"] == "OPEN":
            recompute_excise_report(rep)
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    regulator = request.args.get("regulator")
    if regulator is not None:
        items = [r for r in items if r["regulator"] == regulator]
    return paginate(items, ser_excise_report)


@bp.post("/excise-reports/<id>/file")
@require_roles("ComplianceOfficer")
def file_excise_report(id):
    rep = _get_report(id)
    if rep["status"] != "OPEN":
        raise invalid_state("excise report is not OPEN")
    _, end = period_bounds(rep["period_year"], rep["period_month"])
    if db.now() < end:
        raise ApiError(
            ERR_PERIOD_NOT_CLOSED,
            "reporting period has not closed",
            409,
        )
    recompute_excise_report(rep)
    before = {
        "status": "OPEN",
        "taxable_cents": rep["taxable_cents"],
        "taxable_liters": rep["taxable_liters"],
    }
    rep["status"] = "FILED"
    rep["filed_at"] = db.now()
    db.bump(rep)
    emit_event(
        "ExciseReport", rep["id"], "REPORT_FILED", before,
        {
            "status": "FILED",
            "taxable_cents": rep["taxable_cents"],
            "taxable_liters": rep["taxable_liters"],
        },
    )
    return success_object(ser_excise_report(rep))


@bp.post("/excise-reports/<id>/amend")
@require_roles("ComplianceOfficer")
def amend_excise_report(id):
    rep = _get_report(id)
    if rep["status"] != "FILED":
        raise invalid_state("only a FILED report can be amended")
    b = body()
    reason = b.get("reason")
    if not reason:
        raise validation("reason is required")
    amended_cents = b.get("amended_taxable_cents")
    amended_liters = b.get("amended_taxable_liters")
    if amended_cents is None or amended_liters is None:
        raise validation("amended_taxable_cents and amended_taxable_liters are required")
    before = {
        "status": "FILED",
        "taxable_cents": rep["taxable_cents"],
        "taxable_liters": rep["taxable_liters"],
    }
    rep["taxable_cents"] = amended_cents
    rep["taxable_liters"] = amended_liters
    rep["status"] = "AMENDED"
    rep["_amend_reason"] = reason
    db.bump(rep)
    emit_event(
        "ExciseReport", rep["id"], "REPORT_AMENDED", before,
        {
            "status": "AMENDED",
            "taxable_cents": rep["taxable_cents"],
            "taxable_liters": rep["taxable_liters"],
            "delta_cents": rep["taxable_cents"] - before["taxable_cents"],
            "delta_liters": rep["taxable_liters"] - before["taxable_liters"],
        },
    )
    return success_object(ser_excise_report(rep))


# --- ComplianceEvent (read-only audit) -----------------------------------------------
@bp.get("/compliance-events")
@require_roles("ComplianceOfficer", "PlatformAdmin")
def list_compliance_events():
    items = list(db.store["compliance_events"].values())
    entity_type = request.args.get("entity_type")
    if entity_type is not None:
        items = [e for e in items if e["entity_type"] == entity_type]
    entity_id = request.args.get("entity_id")
    if entity_id is not None:
        items = [e for e in items if e["entity_id"] == entity_id]
    action = request.args.get("action")
    if action is not None:
        items = [e for e in items if e["action"] == action]
    return paginate(items, ser_compliance_event)


@bp.get("/compliance-events/<id>")
@require_roles("ComplianceOfficer", "PlatformAdmin")
def get_compliance_event(id):
    rec = db.store["compliance_events"].get(id)
    if rec is None:
        raise not_found("compliance event")
    return success_object(ser_compliance_event(rec))
