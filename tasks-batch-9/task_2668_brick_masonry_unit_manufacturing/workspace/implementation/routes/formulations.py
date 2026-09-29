"""Body formulation drafting, component appends and qualification."""

from decimal import Decimal

import calc
import response
import services as svc
from auth import ALL_ROLES, endpoint
from errors import ApiError
from routes import apply_filters
from store import clock_str, db, new_row, touch
from validation import COLOR_FAMILIES, bad, body, v_enum, v_id, v_int, v_num, v_str

from flask import Blueprint

bp = Blueprint("formulations", __name__)

D = Decimal
HUNDRED = D("100.00")


@bp.get("/formulations/<fid>")
@endpoint(ALL_ROLES)
def get_formulation(fid):
    return response.entity(svc.formulation_or_404(fid))


@bp.get("/formulations")
@endpoint(ALL_ROLES)
def list_formulations():
    rows = apply_filters(
        db.formulations.values(),
        {
            "plant_id": "plant_id",
            "supersedes_formulation_id": "supersedes_formulation_id",
            "status": "status",
            "target_color_family": "target_color_family",
        },
    )
    return response.collection(rows)


# --------------------------------------------------------------------------
# POST /formulations
# --------------------------------------------------------------------------
@bp.post("/formulations")
@endpoint(["BodyEngineer"])
def create_formulation():
    payload = body()
    plant_id = v_id(payload, "plant_id")
    formulation_code = v_str(payload, "formulation_code")
    color_family = v_enum(payload, "target_color_family", COLOR_FAMILIES)
    target_cdi = v_num(payload, "target_cdi", 2, minv="5.00", maxv="60.00")
    target_soak = v_num(payload, "target_soak_hours", 1, minv="0.5", maxv="24.0")
    tons_per_k = v_num(payload, "clay_tons_per_thousand_units", 2, minv="0.01")
    supersedes_id = v_id(payload, "supersedes_formulation_id", required=False)

    plant = svc.plant_or_404(plant_id)
    predecessor = svc.formulation_or_404(supersedes_id) if supersedes_id else None
    if predecessor is not None and predecessor["plant_id"] != plant_id:
        raise bad("supersedes_formulation_id must name a formulation of the same plant.")

    svc.require_plant_active(plant)
    svc.require_unique(db.formulations, "formulation_code", formulation_code)

    row = new_row(
        plant_id=plant_id,
        supersedes_formulation_id=supersedes_id,
        formulation_code=formulation_code,
        target_color_family=color_family,
        target_cdi=target_cdi,
        target_soak_hours=target_soak,
        clay_tons_per_thousand_units=tons_per_k,
        components=[],
        component_share_total_pct=D("0.00"),
        blend_iron_oxide_pct=None,
        blend_lime_pct=None,
        shale_share_pct=None,
        absorption_index=None,
        computed_durability_grade=None,
        status="DRAFT",
        qualified_at=None,
        dequalified_count=0,
    )
    db.formulations[row["id"]] = row

    if predecessor is not None and predecessor["status"] == "QUALIFIED":
        predecessor["status"] = "RETIRED"
        touch(predecessor)
    return response.entity_created(row)


# --------------------------------------------------------------------------
# POST /formulations/{id}/components
# --------------------------------------------------------------------------
@bp.post("/formulations/<fid>/components")
@endpoint(["BodyEngineer"])
def append_component(fid):
    formulation = svc.formulation_or_404(fid)
    payload = body()
    pit_id = v_id(payload, "pit_id")
    share_pct = v_num(payload, "share_pct", 2, minv="0.00")
    expected = v_int(payload, "expected_formulation_version")

    pit = svc.pit_or_404(pit_id)

    if expected != int(formulation["version"]):
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_formulation_version does not match the formulation's current version.",
        )

    svc.require_plant_active(db.plants.get(formulation["plant_id"]))
    if formulation["status"] != "DRAFT":
        raise ApiError("ERR_FORMULATION_NOT_DRAFT", "The body formulation is not DRAFT.")
    if pit["plant_id"] != formulation["plant_id"]:
        raise ApiError(
            "ERR_PIT_PLANT_MISMATCH",
            "The appended clay pit belongs to a different plant than the formulation.",
        )

    components = formulation["components"]
    if any(c["pit_id"] == pit_id for c in components):
        raise ApiError(
            "ERR_COMPONENT_SHARE_TOTAL_INVALID",
            "The same clay pit may not appear twice in one formulation.",
        )
    running = D("0.00")
    for comp in components:
        running += D(comp["share_pct"])
    if running + D(share_pct) > HUNDRED:
        raise ApiError(
            "ERR_COMPONENT_SHARE_TOTAL_INVALID",
            "The running component share total may not exceed 100.00.",
        )

    components.append({"pit_id": pit_id, "share_pct": share_pct})
    svc.recompute_chemistry(formulation)
    touch(formulation)
    return response.entity(formulation)


# --------------------------------------------------------------------------
# POST /formulations/{id}/qualify
# --------------------------------------------------------------------------
@bp.post("/formulations/<fid>/qualify")
@endpoint(["BodyEngineer"])
def qualify_formulation(fid):
    formulation = svc.formulation_or_404(fid)
    svc.require_plant_active(db.plants.get(formulation["plant_id"]))

    for comp in formulation["components"]:
        pit = db.clay_pits.get(comp["pit_id"])
        if pit is None or pit["status"] != "OPEN":
            raise ApiError(
                "ERR_CLAY_PIT_SUSPENDED",
                "A contributing clay pit is not OPEN.",
            )
    if formulation["status"] != "DRAFT":
        raise ApiError("ERR_FORMULATION_NOT_DRAFT", "The body formulation is not DRAFT.")

    total = D("0.00")
    for comp in formulation["components"]:
        total += D(comp["share_pct"])
    if total != HUNDRED:
        raise ApiError(
            "ERR_COMPONENT_SHARE_TOTAL_INVALID",
            "Component shares must sum to exactly 100.00 to qualify.",
        )

    svc.recompute_chemistry(formulation)
    formulation["status"] = "QUALIFIED"
    formulation["qualified_at"] = clock_str()
    touch(formulation)
    return response.entity(formulation)
