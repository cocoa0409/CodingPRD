"""Product lines (SKUs): definition, packaging economics and certification verdict."""

from decimal import Decimal

from flask import Blueprint

import calc
import ledger
from calc import D0_2, q2
from db import new_row, ordered, store, touch
from errors import fail
from middleware import actor, authenticate
from refs import apply_filters, get_binder, get_plant, get_product_line, get_program
from response import created_response, list_response, object_response
from validate import body, dec_field, int_field, present, str_field

bp = Blueprint("product_lines", __name__)

READ_ROLES = ("CorporateOps", "PlantOperator", "QualityEngineer", "CertificationOfficer",
              "ChannelManager", "ChannelBuyer")
FORMS = ("BATT", "ROLL")
FACINGS = ("UNFACED", "KRAFT", "FSK", "FOIL")
WIDTHS = (15, 16, 23, 24)
PACKAGING_STATUSES = ("DRAFT", "PENDING_CERTIFICATION", "CERTIFIED", "DERATED")


def _apply_packaging(product_line):
    figures = calc.packaging_economics(
        product_line["compression_ratio"],
        product_line["bale_volume_ft3"],
        product_line["bale_mass_kg"],
        product_line["bag_sqft"],
        product_line["facing_type"],
    )
    product_line.update(figures)


def _check_segregation(product_line, user_id):
    """PRD 2.10 (ladder rung 10)."""
    for test in ledger.product_line_tests(product_line["id"]):
        if test.get("recorded_by_user_id") is not None and \
                str(test["recorded_by_user_id"]) == str(user_id):
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "this operator recorded a thermal measurement on this SKU")
    current = product_line.get("certified_by_user_id")
    if current is not None and str(current) == str(user_id):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "this operator already signed a certification decision on this SKU")


@bp.post("/product-lines")
def create_product_line():
    authenticate(("CorporateOps",))
    payload = body()
    sku = str_field(payload, "sku")
    form = str_field(payload, "form", allowed=FORMS)
    density = dec_field(payload, "density_pcf", gt=0)
    facing = str_field(payload, "facing_type", allowed=FACINGS)
    width = int_field(payload, "width_in")
    if width not in WIDTHS:
        fail("ERR_INVALID_REQUEST", "width_in must be one of 15, 16, 23 or 24")
    thickness = dec_field(payload, "thickness_in", gt=0)
    declared_r = dec_field(payload, "declared_r_value", gt=0)
    bag_sqft = dec_field(payload, "bag_sqft", gt=0)
    bale_volume = dec_field(payload, "bale_volume_ft3", gt=0)
    bale_mass = dec_field(payload, "bale_mass_kg", gt=0)
    mass_rate = dec_field(payload, "mass_rate_kg_per_min", gt=0)
    ratio = dec_field(payload, "compression_ratio", required=False,
                      ge=Decimal("1.0"), le=Decimal("8.0"), default=None)
    ratio = calc.q(ratio, 1) if ratio is not None else calc.DEFAULT_COMPRESSION_RATIO
    for existing in store.product_lines.values():
        if existing["sku"] == sku:
            fail("ERR_INVALID_REQUEST", "sku %s already exists" % sku)

    plant = get_plant(payload.get("plant_id")) if present(payload, "plant_id") else None
    if plant is None:
        fail("ERR_INVALID_REQUEST", "plant_id is required")
    binder = get_binder(payload.get("binder_formulation_id")) \
        if present(payload, "binder_formulation_id") else None
    if binder is None:
        fail("ERR_INVALID_REQUEST", "binder_formulation_id is required")
    program = get_program(payload.get("certification_program_id")) \
        if present(payload, "certification_program_id") else None
    if program is None:
        fail("ERR_INVALID_REQUEST", "certification_program_id is required")

    row = new_row()
    row.update({
        "sku": sku,
        "plant_id": plant["id"],
        "binder_formulation_id": binder["id"],
        "certification_program_id": program["id"],
        "form": form,
        "density_pcf": q2(density),
        "facing_type": facing,
        "width_in": width,
        "thickness_in": thickness,
        "declared_r_value": calc.q(declared_r, 1),
        "bag_sqft": bag_sqft,
        "bale_volume_ft3": bale_volume,
        "bale_mass_kg": bale_mass,
        "mass_rate_kg_per_min": mass_rate,
        "compression_ratio": ratio,
        "certification_status": "DRAFT",
        "nonconformance_count": 0,
        "effective_declared_r_value": None,
        "certified_by_user_id": None,
    })
    _apply_packaging(row)
    store.product_lines[row["id"]] = row
    return created_response(row)


@bp.get("/product-lines/<product_line_id>")
def read_product_line(product_line_id):
    authenticate(READ_ROLES)
    return object_response(get_product_line(product_line_id))


@bp.get("/product-lines")
def list_product_lines():
    authenticate(READ_ROLES)
    rows = apply_filters(store.product_lines.values(), {
        "plant_id": ("plant_id", "str"),
        "binder_formulation_id": ("binder_formulation_id", "str"),
        "certification_program_id": ("certification_program_id", "str"),
        "form": ("form", "str"),
        "facing_type": ("facing_type", "str"),
        "certification_status": ("certification_status", "str"),
    })
    return list_response(rows)


@bp.patch("/product-lines/<product_line_id>/packaging")
def patch_packaging(product_line_id):
    authenticate(("CorporateOps",))
    product_line = get_product_line(product_line_id)
    payload = body()
    ratio = dec_field(payload, "compression_ratio", required=False,
                      ge=Decimal("1.0"), le=Decimal("8.0"), default=None)
    bale_volume = dec_field(payload, "bale_volume_ft3", required=False, gt=0, default=None)
    bale_mass = dec_field(payload, "bale_mass_kg", required=False, gt=0, default=None)
    bag_sqft = dec_field(payload, "bag_sqft", required=False, gt=0, default=None)

    if product_line["certification_status"] not in PACKAGING_STATUSES:
        fail("ERR_INVALID_STATE", "packaging may not be re-tuned in this certification status")

    if ratio is not None:
        product_line["compression_ratio"] = calc.q(ratio, 1)
    if bale_volume is not None:
        product_line["bale_volume_ft3"] = bale_volume
    if bale_mass is not None:
        product_line["bale_mass_kg"] = bale_mass
    if bag_sqft is not None:
        product_line["bag_sqft"] = bag_sqft
    _apply_packaging(product_line)
    touch(product_line)
    return object_response(product_line)


@bp.post("/product-lines/<product_line_id>/submit-certification")
def submit_certification(product_line_id):
    authenticate(("QualityEngineer",))
    product_line = get_product_line(product_line_id)
    if product_line["certification_status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "only a DRAFT SKU may be submitted for certification")
    binder = store.binders.get(product_line["binder_formulation_id"])
    if binder is None or binder["status"] != "CERTIFIED":
        fail("ERR_BINDER_NOT_CERTIFIED", "the SKU's binder formulation is not CERTIFIED")
    product_line["certification_status"] = "PENDING_CERTIFICATION"
    touch(product_line)
    return object_response(product_line)


@bp.post("/product-lines/<product_line_id>/certification-decision")
def product_line_decision(product_line_id):
    authenticate(("CertificationOfficer",))
    product_line = get_product_line(product_line_id)
    payload = body()
    decision = str_field(payload, "decision",
                         allowed=("CERTIFY", "DERATE", "REJECT", "SUSPEND", "REINSTATE", "WITHDRAW"))
    note = str_field(payload, "decision_note", required=False, default=None)
    status = product_line["certification_status"]
    program = store.programs.get(product_line["certification_program_id"])
    tests = ledger.product_line_tests(product_line["id"])

    # --- rung 8: does the current state permit this decision at all? ---
    if decision == "CERTIFY":
        if status != "PENDING_CERTIFICATION":
            fail("ERR_INVALID_STATE", "only a PENDING_CERTIFICATION SKU may be certified")
        qualifying = [t for t in tests if t["status"] == "COMPLETED"
                      and t.get("conformance_verdict") == "CONFORMING"]
        if not qualifying:
            fail("ERR_INVALID_STATE", "no completed conforming thermal test is on file")
    elif decision == "DERATE":
        if status != "PENDING_CERTIFICATION":
            fail("ERR_INVALID_STATE", "only a PENDING_CERTIFICATION SKU may be derated")
        if not [t for t in tests if t["status"] in ("COMPLETED", "EXHAUSTED")]:
            fail("ERR_INVALID_STATE", "no completed thermal test is on file")
    elif decision == "REJECT":
        if status != "PENDING_CERTIFICATION":
            fail("ERR_INVALID_STATE", "only a PENDING_CERTIFICATION SKU may be rejected")
    elif decision == "SUSPEND":
        if status not in ("CERTIFIED", "DERATED"):
            fail("ERR_INVALID_STATE", "only a CERTIFIED or DERATED SKU may be suspended")
    elif decision == "REINSTATE":
        if status != "SUSPENDED":
            fail("ERR_INVALID_STATE", "only a SUSPENDED SKU may be reinstated")
        binder = store.binders.get(product_line["binder_formulation_id"])
        if binder is None or binder["status"] != "CERTIFIED":
            fail("ERR_INVALID_STATE", "the SKU's binder formulation is not CERTIFIED again")
    else:
        if status != "SUSPENDED":
            fail("ERR_INVALID_STATE", "only a SUSPENDED SKU may be withdrawn")

    # --- rung 10: segregation of duties ---
    _check_segregation(product_line, actor())

    # --- rung 12 and the writes ---
    if decision == "CERTIFY":
        product_line["certification_status"] = "CERTIFIED"
        product_line["effective_declared_r_value"] = product_line["declared_r_value"]
        product_line["certified_by_user_id"] = actor()
    elif decision == "DERATE":
        if program is None or program["derate_allowed"] is not True:
            fail("ERR_DERATE_NOT_PERMITTED", "the certification program does not permit derating")
        latest = tests[-1] if tests else None
        if latest is None or latest["status"] not in ("COMPLETED", "EXHAUSTED") or \
                latest.get("mean_r_value") is None:
            fail("ERR_DERATE_NOT_PERMITTED", "the most recent thermal test cannot support a derate")
        basis_value = latest["min_r_value"] if latest["conformance_basis"] == "PER_SPECIMEN" \
            else latest["mean_r_value"]
        if basis_value is None:
            fail("ERR_DERATE_NOT_PERMITTED", "the most recent thermal test cannot support a derate")
        effective = calc.derated_value(basis_value)
        if not (effective > 0 and effective < Decimal(product_line["declared_r_value"])):
            fail("ERR_DERATE_NOT_PERMITTED",
                 "the derated value must be positive and strictly below the declared value")
        product_line["certification_status"] = "DERATED"
        product_line["effective_declared_r_value"] = effective
        product_line["certified_by_user_id"] = actor()
    elif decision == "REJECT":
        product_line["certification_status"] = "DRAFT"
        product_line["nonconformance_count"] = product_line["nonconformance_count"] + 1
        product_line["effective_declared_r_value"] = None
    elif decision == "REINSTATE":
        product_line["certification_status"] = "PENDING_CERTIFICATION"
        product_line["effective_declared_r_value"] = None
        product_line["certified_by_user_id"] = None
    elif decision == "WITHDRAW":
        product_line["certification_status"] = "WITHDRAWN"

    if note is not None:
        product_line["_decision_note"] = note

    if decision == "SUSPEND":
        ledger.suspend_product_line(product_line, cancel_cycles=True)
    else:
        touch(product_line)
    return object_response(product_line)
