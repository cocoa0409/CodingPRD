"""Plating bath endpoints: create/read, titrations, doses, quarantine lifecycle,
dump/renew, and bath-scoped load-run listing."""
from flask import Blueprint

from db import store
from errors import (
    ERR_BATH_NOT_ACTIVE,
    ERR_BATH_NOT_DOSABLE,
    ERR_BATH_NOT_DUMPABLE,
    ERR_BATH_NOT_DUMPED,
    ERR_BATH_NOT_QUARANTINED,
    ERR_BATH_OCCUPIED,
    ERR_BATH_CONCENTRATION_OUT_OF_BAND,
    ERR_DISCHARGE_EXCEEDANCE_HOLD,
    ERR_DOSE_NOT_NEEDED,
    ERR_DOSE_VERIFICATION_PENDING,
    ERR_INVALID_REQUEST,
    ERR_MANIFEST_NOT_DRAFT,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
    raise_err,
)
from helpers import (
    body_json,
    check_array,
    check_enum,
    check_number,
    check_string,
    get_or_404,
    is_int,
    is_number,
    paginate,
    parse_pagination,
    stamp_event,
    stamp_new,
    touch,
)
from middleware import require_roles, STAFF_ROLES
from response import success_list, success_object
from serializers import (
    bath_view,
    dose_view,
    load_run_view,
    titration_view,
    manifest_line_item_view,
)
from services import chemistry
from services.cascades import (
    cascade_bath_dumped,
    cascade_bath_quarantine,
    cascade_bath_released_to_active,
    permit_blocks_chemistry,
)

bp = Blueprint("baths", __name__)

CHEMISTRY_FAMILIES = {"SULFURIC", "CHROMIC", "NICKEL", "ZINC", "COPPER", "CYANIDE"}
PROCESS_TYPES = {"ANODIZE", "PLATE"}
ROUTING_MODES = {"RACK", "BARREL"}


@bp.route("/baths", methods=["POST"])
def create_bath():
    user_id, role = require_roles({"ShopManager"})
    data = body_json()
    bath_code = check_string(data, "bath_code", required=True)
    process_type = check_enum(data, "process_type", PROCESS_TYPES, required=True)
    chemistry_family = check_enum(data, "chemistry_family", CHEMISTRY_FAMILIES, required=True)
    routing_modes_supported = check_array(data, "routing_modes_supported", required=True, min_len=1)
    for m in routing_modes_supported:
        if m not in ROUTING_MODES:
            raise_err(ERR_INVALID_REQUEST, "routing_modes_supported must be a non-empty subset of [RACK, BARREL]")
    volume_liters = check_number(data, "volume_liters", required=True, gt=0)
    target = check_number(data, "target_concentration_g_l", required=True, gt=0)
    low = check_number(data, "low_concentration_g_l", required=True, gt=0)
    high = check_number(data, "high_concentration_g_l", required=True)
    amp_hour_capacity = check_number(data, "amp_hour_capacity", required=True, gt=0)
    if not (low < target):
        raise_err(ERR_INVALID_REQUEST, "low_concentration_g_l must be < target_concentration_g_l")
    if not (high > target):
        raise_err(ERR_INVALID_REQUEST, "high_concentration_g_l must be > target_concentration_g_l")

    for b in store.baths.values():
        if b["bath_code"] == bath_code:
            raise_err(ERR_INVALID_REQUEST, "bath_code must be unique")

    bath = stamp_new({
        "bath_code": bath_code,
        "process_type": process_type,
        "chemistry_family": chemistry_family,
        "routing_modes_supported": list(routing_modes_supported),
        "volume_liters": volume_liters,
        "target_concentration_g_l": target,
        "low_concentration_g_l": low,
        "high_concentration_g_l": high,
        "amp_hour_capacity": amp_hour_capacity,
        "current_concentration_g_l": None,
        "amp_hour_used": 0.0,
        "amp_hour_reserved": 0.0,
        "active_load_run_id": None,
        "dose_verification_pending": False,
        "quarantine_cause": None,
        "status": "ACTIVE",
    })
    store.baths[bath["id"]] = bath
    return success_object(bath_view(bath), status=201)


@bp.route("/baths/<bath_id>", methods=["GET"])
def get_bath(bath_id):
    user_id, role = require_roles(STAFF_ROLES)
    bath = get_or_404(store.baths, bath_id)
    return success_object(bath_view(bath))


@bp.route("/baths/<bath_id>/titrations", methods=["POST"])
def create_titration(bath_id):
    user_id, role = require_roles({"LabChemist", "ShopManager"})
    bath = get_or_404(store.baths, bath_id)
    data = body_json()
    titrant_volume_ml = check_number(data, "titrant_volume_ml", required=True, gt=0)
    titrant_normality = check_number(data, "titrant_normality", required=True, gt=0)
    sample_volume_ml = check_number(data, "sample_volume_ml", required=True, gt=0)

    # Tier 7 state: bath must be ACTIVE or QUARANTINED
    if bath["status"] not in ("ACTIVE", "QUARANTINED"):
        raise_err(ERR_BATH_NOT_DOSABLE, "titration requires bath status ACTIVE or QUARANTINED")

    measured = chemistry.titration_concentration(
        bath["chemistry_family"], titrant_volume_ml, titrant_normality, sample_volume_ml
    )
    titration = stamp_event({
        "bath_id": bath["id"],
        "titrant_volume_ml": titrant_volume_ml,
        "titrant_normality": titrant_normality,
        "sample_volume_ml": sample_volume_ml,
        "measured_concentration_g_l": measured,
    })
    store.titrations[titration["id"]] = titration
    bath["current_concentration_g_l"] = measured
    bath["dose_verification_pending"] = False
    touch(bath)
    return success_object(titration_view(titration), status=201)


@bp.route("/baths/<bath_id>/titrations", methods=["GET"])
def list_titrations(bath_id):
    user_id, role = require_roles(STAFF_ROLES)
    bath = get_or_404(store.baths, bath_id)
    limit, offset = parse_pagination()
    items = [t for t in store.titrations.values() if t["bath_id"] == bath["id"]]
    items.sort(key=lambda t: (t["created_at"], t["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([titration_view(t) for t in page], limit, offset, total)


@bp.route("/baths/<bath_id>/doses", methods=["POST"])
def create_dose(bath_id):
    user_id, role = require_roles({"LabChemist", "ShopManager"})
    bath = get_or_404(store.baths, bath_id)
    data = body_json()
    chemical_code = check_string(data, "chemical_code", required=True)
    quantity_g = check_number(data, "quantity_g", required=True, gt=0)
    expected_bath_version = data.get("expected_bath_version")
    if expected_bath_version is None or not is_int(expected_bath_version):
        raise_err(ERR_INVALID_REQUEST, "expected_bath_version is required and must be an integer")

    # Tier 6: OCC before any state/business logic
    if expected_bath_version != bath["version"]:
        raise_err(ERR_STALE_VERSION, "expected_bath_version does not match the bath's current version")

    # Tier 7: bath must be ACTIVE or QUARANTINED
    if bath["status"] not in ("ACTIVE", "QUARANTINED"):
        raise_err(ERR_BATH_NOT_DOSABLE, "dose requires bath status ACTIVE or QUARANTINED")

    # Tier 10: dose necessity — current below target
    current = bath["current_concentration_g_l"]
    if current is not None and not (chemistry._d(current) < chemistry._d(bath["target_concentration_g_l"])):
        raise_err(ERR_DOSE_NOT_NEEDED, "current concentration is already at or above target")

    new_conc = chemistry.dose_resulting_concentration(
        current if current is not None else 0, quantity_g, bath["volume_liters"]
    )
    dose = stamp_event({
        "bath_id": bath["id"],
        "chemical_code": chemical_code,
        "quantity_g": quantity_g,
        "resulting_concentration_g_l": new_conc,
    })
    store.doses[dose["id"]] = dose
    bath["current_concentration_g_l"] = new_conc
    bath["dose_verification_pending"] = True
    touch(bath)
    return success_object(dose_view(dose), status=201)


@bp.route("/baths/<bath_id>/doses", methods=["GET"])
def list_doses(bath_id):
    user_id, role = require_roles(STAFF_ROLES)
    bath = get_or_404(store.baths, bath_id)
    limit, offset = parse_pagination()
    items = [d for d in store.doses.values() if d["bath_id"] == bath["id"]]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([dose_view(d) for d in page], limit, offset, total)


@bp.route("/baths/<bath_id>/quarantine", methods=["POST"])
def quarantine_bath(bath_id):
    user_id, role = require_roles({"EHSOfficer", "ShopManager"})
    bath = get_or_404(store.baths, bath_id)
    # Tier 7: bath must be ACTIVE
    if bath["status"] != "ACTIVE":
        raise_err(ERR_BATH_NOT_ACTIVE, "quarantine requires bath status ACTIVE")
    cascade_bath_quarantine(bath, "MANUAL")
    return success_object(bath_view(bath))


@bp.route("/baths/<bath_id>/release-quarantine", methods=["POST"])
def release_quarantine(bath_id):
    user_id, role = require_roles({"EHSOfficer", "ShopManager"})
    bath = get_or_404(store.baths, bath_id)

    # Tier 7: bath must be QUARANTINED
    if bath["status"] != "QUARANTINED":
        raise_err(ERR_BATH_NOT_QUARANTINED, "release-quarantine requires bath status QUARANTINED")

    # Tier 8 (safety): dose verification, concentration band, exceedance hold
    if bath["dose_verification_pending"]:
        raise_err(ERR_DOSE_VERIFICATION_PENDING, "a dose is awaiting verification by titration")
    if not chemistry.concentration_in_band(bath):
        raise_err(ERR_BATH_CONCENTRATION_OUT_OF_BAND, "current concentration is outside the control band")
    if bath["quarantine_cause"] == "DISCHARGE_EXCEEDANCE":
        if permit_blocks_chemistry(bath["chemistry_family"]):
            raise_err(
                ERR_DISCHARGE_EXCEEDANCE_HOLD,
                "a discharge permit still has an active exceedance over this bath's chemistry",
            )

    # Capacity gate at release: used >= capacity -> EXHAUSTED instead of ACTIVE
    if chemistry._d(bath["amp_hour_used"]) >= chemistry._d(bath["amp_hour_capacity"]):
        bath["status"] = "EXHAUSTED"
        bath["quarantine_cause"] = None
        touch(bath)
    else:
        bath["status"] = "ACTIVE"
        bath["quarantine_cause"] = None
        touch(bath)
        cascade_bath_released_to_active(bath)
    return success_object(bath_view(bath))


@bp.route("/baths/<bath_id>/dump", methods=["POST"])
def dump_bath(bath_id):
    user_id, role = require_roles({"ShopManager"})
    bath = get_or_404(store.baths, bath_id)
    data = body_json()
    manifest_id = data.get("manifest_id")
    if manifest_id is None or not isinstance(manifest_id, str):
        raise_err(ERR_INVALID_REQUEST, "manifest_id is required")
    decommission = data.get("decommission", False)
    if not isinstance(decommission, bool):
        raise_err(ERR_INVALID_REQUEST, "decommission must be a boolean")
    # Tier 4: body FK existence
    manifest = store.manifests.get(manifest_id)
    if manifest is None:
        raise_err(ERR_NOT_FOUND, "manifest not found")

    # Tier 7 state checks
    if bath["status"] in ("DUMPED", "DECOMMISSIONED"):
        raise_err(ERR_BATH_NOT_DUMPABLE, "bath cannot be dumped from status %s" % bath["status"])
    if bath["active_load_run_id"] is not None:
        raise_err(ERR_BATH_OCCUPIED, "a load run is RUNNING on this bath")
    if manifest["status"] != "DRAFT":
        raise_err(ERR_MANIFEST_NOT_DRAFT, "manifest must be DRAFT")

    # Create the manifest line item (F006, BATH_DUMP)
    from decimal import Decimal
    from services.manifest_calc import line_mass_kg, recompute_manifest_total

    line = stamp_new({
        "manifest_id": manifest["id"],
        "waste_code": "F006",
        "source_type": "BATH_DUMP",
        "description": "Bath dump: %s" % bath["bath_code"],
        "volume_liters": bath["volume_liters"],
        "mass_kg": line_mass_kg("BATH_DUMP", bath["volume_liters"]),
        "origin_bath_id": bath["id"],
    })
    store.manifest_line_items[line["id"]] = line
    recompute_manifest_total(manifest)
    touch(manifest)

    bath["status"] = "DECOMMISSIONED" if decommission else "DUMPED"
    bath["quarantine_cause"] = None
    touch(bath)
    cascade_bath_dumped(bath)
    return success_object(bath_view(bath))


@bp.route("/baths/<bath_id>/renew", methods=["POST"])
def renew_bath(bath_id):
    user_id, role = require_roles({"ShopManager"})
    bath = get_or_404(store.baths, bath_id)
    data = body_json()
    titrant_volume_ml = check_number(data, "titrant_volume_ml", required=True, gt=0)
    titrant_normality = check_number(data, "titrant_normality", required=True, gt=0)
    sample_volume_ml = check_number(data, "sample_volume_ml", required=True, gt=0)

    # Tier 7: bath must be DUMPED
    if bath["status"] != "DUMPED":
        raise_err(ERR_BATH_NOT_DUMPED, "renew requires bath status DUMPED")

    measured = chemistry.titration_concentration(
        bath["chemistry_family"], titrant_volume_ml, titrant_normality, sample_volume_ml
    )
    titration = stamp_event({
        "bath_id": bath["id"],
        "titrant_volume_ml": titrant_volume_ml,
        "titrant_normality": titrant_normality,
        "sample_volume_ml": sample_volume_ml,
        "measured_concentration_g_l": measured,
    })
    store.titrations[titration["id"]] = titration

    bath["status"] = "ACTIVE"
    bath["current_concentration_g_l"] = measured
    bath["amp_hour_used"] = 0.0
    bath["amp_hour_reserved"] = 0.0
    bath["dose_verification_pending"] = False
    bath["quarantine_cause"] = None
    touch(bath)
    cascade_bath_released_to_active(bath)
    return success_object(bath_view(bath))


@bp.route("/baths/<bath_id>/load-runs", methods=["GET"])
def list_bath_load_runs(bath_id):
    user_id, role = require_roles(STAFF_ROLES)
    bath = get_or_404(store.baths, bath_id)
    limit, offset = parse_pagination()
    items = [r for r in store.load_runs.values() if r["bath_id"] == bath["id"]]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([load_run_view(r) for r in page], limit, offset, total)
