"""Appointment templates (PRD 3.4)."""

from flask import Blueprint

from db import must, new_row, rows, touch
from middleware import authenticate
from response import created, ok
from routes.common import paged
from services import present
from validators import bad, body, opt_bool, opt_enum, q_enum, q_str, req_enum, req_str

bp = Blueprint("templates", __name__)

TIERS = ("LOW", "MID", "HIGH")
STATUSES = ("ACTIVE", "RETIRED")
READERS = ("Scheduler", "InfusionNurse", "Pharmacist", "MedicalDirector")


def snapshot(drug, center, dose_tier):
    acuity = int(drug["acuity_points"]) + (1 if dose_tier == "HIGH" else 0)
    grid = int(center["stagger_grid_minutes"])
    stagger = grid * 2 if acuity >= 4 else grid
    return {
        "base_admin_minutes": int(drug["base_administration_minutes"]),
        "min_admin_minutes": int(drug["min_administration_minutes"]),
        "premed_minutes": int(drug["premedication_minutes"]),
        "observation_minutes_first": int(drug["observation_minutes_first_dose"]),
        "observation_minutes_subsequent": int(drug["observation_minutes_subsequent"]),
        "acuity_points": acuity,
        "stagger_offset_minutes": stagger,
    }


@bp.post("/appointment-templates")
def create_template():
    authenticate("Scheduler", "Pharmacist")
    data = body()
    center_id = req_str(data, "center_id", 1, None)
    drug_id = req_str(data, "drug_id", 1, None)
    dose_tier = req_enum(data, "dose_tier", TIERS)
    center = must("centers", center_id)
    drug = must("drugs", drug_id)
    for template in rows("templates"):
        if (
            template["status"] == "ACTIVE"
            and template["center_id"] == center_id
            and template["drug_id"] == drug_id
            and template["dose_tier"] == dose_tier
        ):
            bad("An ACTIVE template already exists for this center, drug and dose tier.")
    fields = {"center_id": center_id, "drug_id": drug_id, "dose_tier": dose_tier}
    fields.update(snapshot(drug, center, dose_tier))
    fields["status"] = "ACTIVE"
    row = new_row("templates", fields)
    return created(present.plain(row))


@bp.get("/appointment-templates/<template_id>")
def read_template(template_id):
    authenticate(*READERS)
    return ok(present.plain(must("templates", template_id)))


@bp.get("/appointment-templates")
def list_templates():
    authenticate(*READERS)
    center_id = q_str("center_id")
    drug_id = q_str("drug_id")
    dose_tier = q_enum("dose_tier", TIERS)
    status = q_enum("status", STATUSES)
    items = []
    for template in rows("templates"):
        if center_id is not None and template["center_id"] != center_id:
            continue
        if drug_id is not None and template["drug_id"] != drug_id:
            continue
        if dose_tier is not None and template["dose_tier"] != dose_tier:
            continue
        if status is not None and template["status"] != status:
            continue
        items.append(template)
    return paged("templates", items)


@bp.patch("/appointment-templates/<template_id>")
def patch_template(template_id):
    authenticate("Scheduler", "Pharmacist")
    data = body()
    status = opt_enum(data, "status", STATUSES)
    resnapshot = opt_bool(data, "resnapshot", False)
    template = must("templates", template_id)
    changed = False
    if status is not None:
        if template["status"] != status:
            changed = True
        template["status"] = status
    if resnapshot:
        center = must("centers", template["center_id"])
        drug = must("drugs", template["drug_id"])
        template.update(snapshot(drug, center, template["dose_tier"]))
        # Re-snapshotting always advances the version: pinned bookings must go stale.
        changed = True
    if changed:
        touch(template)
    return ok(present.plain(template))
