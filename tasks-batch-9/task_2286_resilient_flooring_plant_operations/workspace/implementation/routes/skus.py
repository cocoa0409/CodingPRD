"""Product SKUs: the twin certification and commercial dimensions (PRD 3.4)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import cascades
from db import db, new_row, now, ordered, serialize as _ser, touch
from errors import ApiError
from middleware import authorize, find, user_id
from response import enum_filter, list_response, object_response, string_filter
from support import STATUS_CREATED, body, license_active_check, license_term_check, unique
from support import film_available_check
from validate import field as F
from validate import invalid, validate

bp = Blueprint("skus", __name__)

CONSTRUCTION_TYPE = ("GLUE_DOWN", "LOOSE_LAY", "CLICK_LOCK_SPC", "CLICK_LOCK_WPC")
UNDERLAYMENT = ("NONE", "IXPE_1MM", "EVA_1_5MM", "CORK_2MM")
PROFILE_FAMILY = ("NONE", "UNILIN_5G", "VALINGE_2G", "DROP_LOCK")
CERTIFICATION_STATUS = ("UNCERTIFIED", "TESTING", "PROVISIONAL", "CERTIFIED",
                        "SUSPENDED", "DECERTIFIED")
COMMERCIAL_STATUS = ("DEVELOPMENT", "RELEASED", "HOLD", "DISCONTINUED")

SKU_READERS = ("PlantAdmin", "Formulator", "TechnicalDirector", "QaTechnician",
               "ProductionPlanner", "Distributor")

MILLING_FIELDS = ("tongue_thickness_target_mm", "tolerance_plus_mm", "tolerance_minus_mm",
                  "target_lock_shear_n_per_mm")

SKU_CREATE = [
    F("sku_code", "string", required=True),
    F("formulation_id", "string", required=True),
    F("print_film_id", "string", required=True),
    F("construction_type", "string", required=True, enum=CONSTRUCTION_TYPE),
    F("wear_layer_mil", "number", required=True, exclusive_min=0, max=40, decimals=1),
    F("overall_thickness_mm", "number", required=True, exclusive_min=0, max=12, decimals=2),
    F("royalty_basis_price_cents_per_sqm", "integer", required=True, min=1),
    F("waterproof_rated", "boolean", default=False),
    F("attached_underlayment_type", "string", enum=UNDERLAYMENT, default="NONE"),
    F("profile_family", "string", enum=PROFILE_FAMILY, default="NONE"),
    F("tongue_thickness_target_mm", "number"),
    F("tolerance_plus_mm", "number", exclusive_min=0),
    F("tolerance_minus_mm", "number", exclusive_min=0),
    F("target_lock_shear_n_per_mm", "number"),
    F("target_margin_bps", "integer", min=0, max=9000, default=3500),
]


@bp.post("/product-skus")
def create_sku():
    authorize("PlantAdmin")
    data = validate(SKU_CREATE, body())

    # V-REQ-2: the milling quartet is all-or-nothing, driven by profile_family
    milling_present = [data[name] is not None for name in MILLING_FIELDS]
    if data["profile_family"] != "NONE":
        if not all(milling_present):
            invalid()
    else:
        if any(milling_present):
            invalid()
        if data["construction_type"] in calc.CLICK_LOCK:
            invalid()

    formulation = find("formulations", data["formulation_id"])
    film = find("print_films", data["print_film_id"])
    unique("product_skus", "sku_code", data["sku_code"])

    if data["profile_family"] != "NONE":
        if data["tolerance_minus_mm"] >= data["tongue_thickness_target_mm"]:
            raise ApiError("ERR_TOLERANCE_BAND_INVALID")
        if data["tolerance_plus_mm"] + data["tolerance_minus_mm"] > Decimal("0.50"):
            raise ApiError("ERR_TOLERANCE_BAND_INVALID")

    row = new_row()
    row.update(data)
    row.update({
        "formulation_id": formulation["id"],
        "print_film_id": film["id"],
        "certification_status": "UNCERTIFIED",
        "commercial_status": "DEVELOPMENT",
        "pinned_formulation_version": None,
        "pinned_print_film_version": None,
        "pin_stale": False,
        "standard_cost_cents_per_sqm": None,
        "list_price_cents_per_sqm": None,
        "certified_at": None,
        "certified_by_user_id": None,
    })
    residential, commercial = calc.sku_warranty_terms(row)
    row["warranty_years"] = residential
    row["light_commercial_warranty_years"] = commercial
    db.product_skus[row["id"]] = row
    return object_response(_ser(row), STATUS_CREATED)


@bp.get("/product-skus")
def list_skus():
    authorize(*SKU_READERS)
    certification = enum_filter(request.args, "certification_status", CERTIFICATION_STATUS)
    commercial = enum_filter(request.args, "commercial_status", COMMERCIAL_STATUS)
    formulation_id = string_filter(request.args, "formulation_id")
    film_id = string_filter(request.args, "print_film_id")
    construction = enum_filter(request.args, "construction_type", CONSTRUCTION_TYPE)
    rows = [r for r in db.product_skus.values()
            if (certification is None or r["certification_status"] == certification)
            and (commercial is None or r["commercial_status"] == commercial)
            and (formulation_id is None or r["formulation_id"] == formulation_id)
            and (film_id is None or r["print_film_id"] == film_id)
            and (construction is None or r["construction_type"] == construction)]
    return list_response(rows, request.args, _ser)


@bp.get("/product-skus/<row_id>")
def read_sku(row_id):
    authorize(*SKU_READERS)
    return object_response(_ser(find("product_skus", row_id)))


@bp.get("/product-skus/<row_id>/cost-summary")
def sku_cost_summary(row_id):
    authorize("PlantAdmin", "TechnicalDirector", "Formulator")
    sku = find("product_skus", row_id)
    summary = calc.cost_summary(sku)
    return object_response(_ser(summary) if summary is not None else None)


# ---------------------------------------------------------------------------
# certification dimension
# ---------------------------------------------------------------------------

def _panels_of(sku, status=None):
    rows = [p for p in db.test_panels.values() if p["sku_id"] == sku["id"]]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    return ordered(rows)


def qualifying_results(sku):
    """The PASS results at the current attempt of every PASSED panel of this SKU."""
    required = calc.sku_required_test_types(sku)
    by_type = {}
    for panel in _panels_of(sku, "PASSED"):
        for result in ordered([r for r in db.test_results.values()
                               if r["test_panel_id"] == panel["id"]
                               and r["attempt_no"] == panel["attempt_no"]
                               and r["outcome"] == "PASS"]):
            if result["test_type"] in required:
                by_type.setdefault(result["test_type"], []).append(result)
    return required, by_type


@bp.post("/product-skus/<row_id>/begin-testing")
def begin_testing(row_id):
    authorize("QaTechnician")
    sku = find("product_skus", row_id)
    if sku["certification_status"] not in ("UNCERTIFIED", "SUSPENDED"):
        raise ApiError("ERR_INVALID_SKU_CERTIFICATION_STATE")
    if sku["commercial_status"] == "DISCONTINUED":
        raise ApiError("ERR_SKU_NOT_PRODUCIBLE")
    for run in db.production_runs.values():
        if run["sku_id"] == sku["id"] and run["run_status"] in ("SETUP", "RUNNING"):
            raise ApiError("ERR_SKU_NOT_PRODUCIBLE")

    film = calc.film_of(sku)
    license_row = calc.license_of_film(film)
    if license_row is not None:
        license_term_check(license_row, now())

    formulation = db.formulations.get(sku["formulation_id"])
    if formulation is None or formulation["status"] != "APPROVED":
        raise ApiError("ERR_FORMULATION_NOT_APPROVED")
    film_available_check(film)
    license_active_check(license_row)

    sku["certification_status"] = "TESTING"
    sku["pin_stale"] = False
    sku["pinned_formulation_version"] = None
    sku["pinned_print_film_version"] = None
    sku["standard_cost_cents_per_sqm"] = None
    sku["list_price_cents_per_sqm"] = None
    sku["certified_at"] = None
    sku["certified_by_user_id"] = None
    touch(sku)
    return object_response(_ser(sku))


@bp.post("/product-skus/<row_id>/certify")
def certify_sku(row_id):
    authorize("TechnicalDirector")
    sku = find("product_skus", row_id)
    if sku["certification_status"] not in ("TESTING", "PROVISIONAL"):
        raise ApiError("ERR_INVALID_SKU_CERTIFICATION_STATE")

    required, by_type = qualifying_results(sku)
    for test_type in required:
        for result in by_type.get(test_type, []):
            if result["recorded_by_user_id"] == user_id():
                raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    for test_type in required:
        if not by_type.get(test_type):
            raise ApiError("ERR_TEST_COVERAGE_INCOMPLETE")

    formulation = db.formulations.get(sku["formulation_id"])
    if formulation is None or formulation["status"] != "APPROVED":
        raise ApiError("ERR_FORMULATION_NOT_APPROVED")
    film = calc.film_of(sku)
    license_active_check(calc.license_of_film(film))

    standard, list_price, _parts = calc.sku_standard_cost(sku, "PINNED_BASIS")
    sku["certification_status"] = "CERTIFIED"
    sku["pinned_formulation_version"] = formulation["version"]
    sku["pinned_print_film_version"] = film["version"]
    sku["standard_cost_cents_per_sqm"] = standard
    sku["list_price_cents_per_sqm"] = list_price
    sku["pin_stale"] = False
    sku["certified_at"] = now()
    sku["certified_by_user_id"] = user_id()
    touch(sku)
    return object_response(_ser(sku))


# ---------------------------------------------------------------------------
# commercial dimension
# ---------------------------------------------------------------------------

COMMERCIAL_FROM = {
    "RELEASED": ("DEVELOPMENT", "HOLD"),
    "HOLD": ("RELEASED",),
    "DISCONTINUED": ("DEVELOPMENT", "RELEASED", "HOLD"),
}


@bp.post("/product-skus/<row_id>/commercial-status")
def commercial_status(row_id):
    authorize("PlantAdmin")
    data = validate([F("to_status", "string", required=True, enum=COMMERCIAL_STATUS)], body())
    to_status = data["to_status"]
    sku = find("product_skus", row_id)
    if sku["commercial_status"] not in COMMERCIAL_FROM.get(to_status, ()):
        raise ApiError("ERR_INVALID_COMMERCIAL_STATE")
    if to_status == "RELEASED":
        if sku["certification_status"] != "CERTIFIED" or sku["pin_stale"]:
            raise ApiError("ERR_SKU_NOT_PRODUCIBLE")

    if to_status == "DISCONTINUED":
        cascades.discontinue_sku(sku)
    elif to_status == "HOLD":
        sku["commercial_status"] = "HOLD"
        touch(sku)
        cascades.hold_sku_batches(sku, void_lines=False)
    else:
        sku["commercial_status"] = "RELEASED"
        touch(sku)
    return object_response(_ser(sku))


__all__ = ["bp"]
