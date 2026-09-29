"""Binder formulations: drafting, emissions certification and the revision loop."""

from decimal import Decimal

from flask import Blueprint

import calc
import ledger
from db import clock_iso, new_row, store, touch
from errors import fail
from middleware import authenticate
from refs import apply_filters, get_binder
from response import created_response, list_response, object_response
from validate import absent, body, bool_field, dec_field, present, str_field

bp = Blueprint("binders", __name__)

READ_ROLES = ("CorporateOps", "QualityEngineer", "CertificationOfficer", "EnvironmentalCompliance")
CHEMISTRY_FIELDS = ("formaldehyde_free", "formaldehyde_ppm", "voc_g_per_kg",
                    "min_cure_temp_f", "min_dwell_s", "loi_target_pct")


def _check_claim(formaldehyde_free, formaldehyde_ppm):
    """PRD 3.2 — symmetric formaldehyde-free claim check (ladder rung 10)."""
    if formaldehyde_free:
        if Decimal(formaldehyde_ppm) != 0:
            fail("ERR_FORMALDEHYDE_FREE_CLAIM_INVALID",
                 "a formaldehyde-free formulation must declare formaldehyde_ppm of exactly 0")
    else:
        if not Decimal(formaldehyde_ppm) > 0:
            fail("ERR_FORMALDEHYDE_FREE_CLAIM_INVALID",
                 "a formulation that is not formaldehyde-free must declare a positive formaldehyde_ppm")


def _check_limits(formaldehyde_ppm, voc_g_per_kg):
    if Decimal(formaldehyde_ppm) > calc.FORMALDEHYDE_CERT_LIMIT_PPM or \
            Decimal(voc_g_per_kg) > calc.VOC_CERT_LIMIT_G_PER_KG:
        fail("ERR_FORMALDEHYDE_LIMIT_EXCEEDED",
             "measured emissions exceed the certification ceilings")


def _read_chemistry(payload):
    formaldehyde_free = bool_field(payload, "formaldehyde_free")
    formaldehyde_ppm = dec_field(payload, "formaldehyde_ppm", ge=0)
    voc_g_per_kg = dec_field(payload, "voc_g_per_kg", ge=0)
    min_cure_temp_f = dec_field(payload, "min_cure_temp_f", gt=0)
    min_dwell_s = dec_field(payload, "min_dwell_s", gt=0)
    loi_target_pct = dec_field(payload, "loi_target_pct", gt=0)
    return {
        "formaldehyde_free": formaldehyde_free,
        "formaldehyde_ppm": formaldehyde_ppm,
        "voc_g_per_kg": voc_g_per_kg,
        "min_cure_temp_f": min_cure_temp_f,
        "min_dwell_s": min_dwell_s,
        "loi_target_pct": loi_target_pct,
    }


@bp.post("/binder-formulations")
def create_binder():
    authenticate(("QualityEngineer",))
    payload = body()
    code = str_field(payload, "code")
    chemistry = _read_chemistry(payload)
    for existing in store.binders.values():
        if existing["code"] == code:
            fail("ERR_INVALID_REQUEST", "code %s is already registered" % code)
    _check_claim(chemistry["formaldehyde_free"], chemistry["formaldehyde_ppm"])

    row = new_row()
    row["code"] = code
    row.update(chemistry)
    row.update({
        "status": "DRAFT",
        "revision_count": 0,
        "emissions_cert_id": None,
        "lab_reference": None,
        "revision_notes": None,
        "certified_at": None,
    })
    store.binders[row["id"]] = row
    return created_response(row)


@bp.get("/binder-formulations/<binder_id>")
def read_binder(binder_id):
    authenticate(READ_ROLES)
    return object_response(get_binder(binder_id))


@bp.get("/binder-formulations")
def list_binders():
    authenticate(READ_ROLES)
    rows = apply_filters(store.binders.values(), {
        "status": ("status", "str"),
        "formaldehyde_free": ("formaldehyde_free", "bool"),
    })
    return list_response(rows)


@bp.post("/binder-formulations/<binder_id>/submit")
def submit_binder(binder_id):
    authenticate(("QualityEngineer",))
    binder = get_binder(binder_id)
    if binder["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "only a DRAFT formulation may be submitted")
    if binder["formaldehyde_free"] and Decimal(binder["formaldehyde_ppm"]) != 0:
        fail("ERR_INVALID_STATE", "a formaldehyde-free claim requires zero measured content")
    binder["status"] = "SUBMITTED"
    touch(binder)
    return object_response(binder)


@bp.post("/binder-formulations/<binder_id>/emissions-test")
def emissions_test(binder_id):
    authenticate(("CertificationOfficer",))
    binder = get_binder(binder_id)
    payload = body()
    formaldehyde_ppm = dec_field(payload, "formaldehyde_ppm", ge=0)
    voc_g_per_kg = dec_field(payload, "voc_g_per_kg", ge=0)
    lab_reference = str_field(payload, "lab_reference")

    if binder["status"] not in ("SUBMITTED", "SUSPENDED"):
        fail("ERR_INVALID_STATE", "the formulation is not awaiting an emissions measurement")
    if binder["status"] == "SUSPENDED":
        for product_line in ledger.binder_product_lines(binder["id"]):
            plant = store.plants.get(product_line["plant_id"])
            if plant is not None and plant["melt_posture"] == "FROZEN":
                fail("ERR_INVALID_STATE", "the plant that suspended this formulation is still FROZEN")
    _check_limits(formaldehyde_ppm, voc_g_per_kg)

    binder["formaldehyde_ppm"] = formaldehyde_ppm
    binder["voc_g_per_kg"] = voc_g_per_kg
    binder["lab_reference"] = lab_reference
    binder["emissions_cert_id"] = None
    binder["certified_at"] = None
    binder["status"] = "EMISSIONS_TESTING"
    touch(binder)
    return object_response(binder)


@bp.post("/binder-formulations/<binder_id>/certification-decision")
def binder_decision(binder_id):
    authenticate(("CertificationOfficer",))
    binder = get_binder(binder_id)
    payload = body()
    decision = str_field(payload, "decision",
                         allowed=("CERTIFY", "REQUEST_REVISION", "SUSPEND", "WITHDRAW"))
    emissions_cert_id = None
    revision_notes = None
    if decision == "CERTIFY":
        emissions_cert_id = str_field(payload, "emissions_cert_id", required=False, default=None)
    elif decision == "REQUEST_REVISION":
        revision_notes = str_field(payload, "revision_notes")

    if decision == "CERTIFY":
        if binder["status"] != "EMISSIONS_TESTING":
            fail("ERR_INVALID_STATE", "only a formulation under test may be certified")
        _check_limits(binder["formaldehyde_ppm"], binder["voc_g_per_kg"])
        binder["status"] = "CERTIFIED"
        binder["emissions_cert_id"] = emissions_cert_id
        binder["certified_at"] = clock_iso()
    elif decision == "REQUEST_REVISION":
        if binder["status"] != "EMISSIONS_TESTING":
            fail("ERR_INVALID_STATE", "only a formulation under test may be sent back for revision")
        binder["status"] = "REVISION_REQUIRED"
        binder["revision_notes"] = revision_notes
    elif decision == "SUSPEND":
        if binder["status"] != "CERTIFIED":
            fail("ERR_INVALID_STATE", "only a CERTIFIED formulation may be suspended")
        binder["status"] = "SUSPENDED"
    else:
        if binder["status"] not in ("CERTIFIED", "SUSPENDED", "REVISION_REQUIRED"):
            fail("ERR_INVALID_STATE", "this formulation may not be withdrawn")
        binder["status"] = "WITHDRAWN"
    touch(binder)
    if decision in ("SUSPEND", "WITHDRAW"):
        ledger.cascade_binder_suspension(binder)
    return object_response(binder)


@bp.post("/binder-formulations/<binder_id>/revise")
def revise_binder(binder_id):
    authenticate(("QualityEngineer",))
    binder = get_binder(binder_id)
    payload = body()
    decision = str_field(payload, "decision", allowed=("REVISE", "WITHDRAW"))
    if decision == "REVISE":
        chemistry = _read_chemistry(payload)
        if binder["status"] not in ("REVISION_REQUIRED", "SUSPENDED"):
            fail("ERR_INVALID_STATE", "only a REVISION_REQUIRED or SUSPENDED formulation may be revised")
        _check_claim(chemistry["formaldehyde_free"], chemistry["formaldehyde_ppm"])
        if not binder["revision_count"] < calc.MAX_BINDER_REVISIONS:
            fail("ERR_BINDER_REVISION_LIMIT_REACHED", "the revision limit has been reached")
        binder.update(chemistry)
        binder["status"] = "DRAFT"
        binder["revision_count"] = binder["revision_count"] + 1
        binder["emissions_cert_id"] = None
        binder["lab_reference"] = None
        binder["certified_at"] = None
        binder["revision_notes"] = None
        touch(binder)
        return object_response(binder)

    for field in CHEMISTRY_FIELDS:
        absent(payload, field, "%s must be omitted on a WITHDRAW" % field)
    if binder["status"] != "REVISION_REQUIRED":
        fail("ERR_INVALID_STATE", "only a REVISION_REQUIRED formulation may be withdrawn here")
    binder["status"] = "WITHDRAWN"
    touch(binder)
    ledger.cascade_binder_suspension(binder)
    return object_response(binder)
