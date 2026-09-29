"""Plants: registration, cullet ledger reads, emissions reports, posture review."""

import re
from decimal import Decimal

from flask import Blueprint

import calc
import ledger
from calc import D0_2, D0_4, q2, q4
from db import clock_now, new_row, store, touch
from errors import fail
from middleware import authenticate
from refs import apply_filters, get_plant
from response import created_response, list_response, object_response
from validate import absent, body, dec_field, instant_field, int_field, present, str_field

bp = Blueprint("plants", __name__)

SITE_CODE_RE = re.compile(r"^[A-Z0-9]{3,8}$")
READ_ONE_ROLES = ("CorporateOps", "PlantOperator", "QualityEngineer",
                  "EnvironmentalCompliance", "ChannelManager")
READ_LIST_ROLES = ("CorporateOps", "EnvironmentalCompliance", "ChannelManager")


@bp.post("/plants")
def create_plant():
    authenticate(("CorporateOps",))
    payload = body()
    name = str_field(payload, "name")
    site_code = str_field(payload, "site_code")
    if not SITE_CODE_RE.match(site_code):
        fail("ERR_INVALID_REQUEST", "site_code must be 3-8 uppercase letters and digits")
    oven_zone_count = int_field(payload, "oven_zone_count", minimum=1)
    oven_length_ft = dec_field(payload, "oven_length_ft", gt=0)
    production_line_count = int_field(payload, "production_line_count", minimum=1)
    permit_number = str_field(payload, "permit_number")
    formaldehyde_allowance = dec_field(payload, "formaldehyde_allowance_kg", gt=0)
    voc_allowance = dec_field(payload, "voc_allowance_kg", gt=0)

    max_cullet = dec_field(payload, "max_cullet_fraction", required=False,
                           gt=0, le=Decimal("0.5"), default=None)
    max_cullet = calc.q2(max_cullet) if max_cullet is not None else calc.DEFAULT_MAX_CULLET_FRACTION
    restrict = dec_field(payload, "cullet_restrict_fraction", required=False,
                         gt=0, le=max_cullet, default=None)
    restrict = calc.q2(restrict) if restrict is not None else calc.DEFAULT_CULLET_RESTRICT_FRACTION
    max_width_change = dec_field(payload, "max_width_change_in", required=False, gt=0, default=None)
    if max_width_change is None:
        max_width_change = calc.DEFAULT_MAX_WIDTH_CHANGE_IN

    for existing in store.plants.values():
        if existing["site_code"] == site_code:
            fail("ERR_INVALID_REQUEST", "site_code %s is already registered" % site_code)

    row = new_row()
    row.update({
        "name": name,
        "site_code": site_code,
        "oven_zone_count": oven_zone_count,
        "oven_length_ft": oven_length_ft,
        "production_line_count": production_line_count,
        "permit_number": permit_number,
        "formaldehyde_allowance_kg": calc.q(formaldehyde_allowance, 3),
        "voc_allowance_kg": voc_allowance,
        "max_cullet_fraction": max_cullet,
        "cullet_restrict_fraction": restrict,
        "max_width_change_in": max_width_change,
        "melt_posture": "OPEN",
        "posture_reason": None,
        "override_reason": None,
        "emissions_status": "COMPLIANT",
        "cullet_received_kg_ytd": D0_2,
        "cullet_charged_kg_ytd": D0_2,
        "cullet_rejected_kg_ytd": D0_2,
        "cullet_on_hand_kg": D0_2,
        "total_charge_kg_ytd": D0_2,
        "cullet_fraction_ytd": D0_4,
        "reported_formaldehyde_kg": D0_4,
        "reported_voc_kg": D0_4,
        "reported_period_start": None,
        "reported_period_end": None,
    })
    store.plants[row["id"]] = row
    return created_response(row)


@bp.get("/plants/<plant_id>")
def read_plant(plant_id):
    authenticate(READ_ONE_ROLES)
    return object_response(get_plant(plant_id))


@bp.get("/plants")
def list_plants():
    authenticate(READ_LIST_ROLES)
    rows = apply_filters(store.plants.values(), {
        "melt_posture": ("melt_posture", "str"),
        "emissions_status": ("emissions_status", "str"),
    })
    return list_response(rows)


@bp.post("/plants/<plant_id>/emissions-report")
def emissions_report(plant_id):
    authenticate(("EnvironmentalCompliance",))
    plant = get_plant(plant_id)
    payload = body()
    start_raw, start_dt = instant_field(payload, "period_start")
    end_raw, end_dt = instant_field(payload, "period_end")
    if not end_dt > start_dt:
        fail("ERR_INVALID_REQUEST", "period_end must be strictly later than period_start")
    if end_dt > clock_now():
        fail("ERR_EMISSIONS_PERIOD_INVALID", "the reporting period has not closed yet")

    formaldehyde = Decimal(0)
    voc = Decimal(0)
    for run in ledger.plant_runs(plant["id"]):
        if run["run_status"] not in ("CURING", "PACKAGED", "CLOSED"):
            continue
        started = run.get("_scheduled_start_dt")
        if started is None or started < start_dt or started > end_dt:
            continue
        if run.get("formaldehyde_kg") is not None:
            formaldehyde += Decimal(run["formaldehyde_kg"])
        if run.get("voc_kg") is not None:
            voc += Decimal(run["voc_kg"])
    reported_formaldehyde = q4(formaldehyde)
    reported_voc = q4(voc)

    plant["reported_formaldehyde_kg"] = reported_formaldehyde
    plant["reported_voc_kg"] = reported_voc
    plant["reported_period_start"] = start_raw
    plant["reported_period_end"] = end_raw

    exceeded = (reported_formaldehyde > Decimal(plant["formaldehyde_allowance_kg"]) or
                reported_voc > Decimal(plant["voc_allowance_kg"]))
    if exceeded:
        plant["emissions_status"] = "EXCEEDANCE"
        ledger.freeze_plant_cascade(plant)
    else:
        plant["emissions_status"] = "REPORTED"
    touch(plant)
    return object_response(plant)


@bp.post("/plants/<plant_id>/posture-review")
def posture_review(plant_id):
    authenticate(("EnvironmentalCompliance",))
    plant = get_plant(plant_id)
    payload = body()
    decision = str_field(payload, "decision", allowed=("RECOMPUTE", "OVERRIDE_TO_OPEN"))
    if decision == "RECOMPUTE":
        absent(payload, "override_reason", "override_reason must be omitted on a RECOMPUTE")
        if plant["melt_posture"] != "RESTRICTED":
            fail("ERR_INVALID_STATE", "melt posture is not RESTRICTED")
        if not Decimal(plant["cullet_fraction_ytd"]) < Decimal(plant["cullet_restrict_fraction"]):
            fail("ERR_INVALID_STATE",
                 "cullet_fraction_ytd has not fallen below cullet_restrict_fraction")
        plant["melt_posture"] = "OPEN"
        plant["posture_reason"] = None
    else:
        override_reason = str_field(payload, "override_reason")
        if plant["melt_posture"] != "FROZEN":
            fail("ERR_INVALID_STATE", "melt posture is not FROZEN")
        plant["melt_posture"] = "OPEN"
        plant["posture_reason"] = "MANUAL_OVERRIDE"
        plant["override_reason"] = override_reason
    touch(plant)
    return object_response(plant)
