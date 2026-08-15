"""StoragePlacement endpoints: activate, list by item/vault, manual release."""

from flask import Blueprint

from db import store
from errors import (
    invalid_transition,
    item_terminal,
    item_not_salvageable,
    hazmat_storage_forbidden,
    climate_incompatible,
    vault_capacity_exceeded,
    specialty_required,
    not_found,
)
from helpers import (
    get_body,
    require_string,
    make_common_fields,
    get_item,
    get_vault,
    get_placement,
    touch,
    job_of_item,
    active_placement_of_item,
    placements_of_item,
)
from middleware import require_roles
from response import success_object, success
from services.recompute import (
    recompute_vault,
    recompute_provisional_statements_for_job,
    recompute_job_accrued,
    recompute_room,
)

bp = Blueprint("placements", __name__)

CLIMATE_REQUIRED_CATEGORIES = {"TEXTILE", "DOCUMENT", "ARTWORK", "ELECTRONICS"}
TERMINAL_ITEM_STATUSES = {"DISPOSED", "DELIVERED", "CLAIM_SETTLED"}


def serialize_placement(p):
    return dict(p)


@bp.route("/api/items/<item_id>/placements", methods=["POST"])
def create_placement(item_id):
    user_id, role = require_roles("InventoryTechnician")
    from helpers import get_body as _gb
    body = _gb()
    vault_id = body.get("vault_id")
    if vault_id is None:
        from errors import validation
        raise validation("vault_id is required")
    if not isinstance(vault_id, str):
        from errors import validation
        raise validation("vault_id must be a string")

    item = get_item(item_id)
    vault = get_vault(vault_id)  # existence of body-referenced resource

    # Priority 7 state checks
    if item["processing_status"] in TERMINAL_ITEM_STATUSES:
        raise item_terminal()
    if item["condition_triage"] != "SALVAGEABLE":
        raise item_not_salvageable()
    if item["processing_status"] != "CLEANED":
        raise invalid_transition("Item processing_status must be CLEANED")

    # Priority 8 business safety
    if item["hazmat_flag"]:
        raise hazmat_storage_forbidden()
    if item["item_category"] in CLIMATE_REQUIRED_CATEGORIES and vault["climate_class"] != "CLIMATE_CONTROLLED":
        raise climate_incompatible()

    # Priority 9 business constraints
    if vault["occupied_cu_ft"] + item["volume_cu_ft"] > vault["capacity_cu_ft"]:
        raise vault_capacity_exceeded()

    # Priority 11 business referential: high-value gate
    if item["is_high_value"]:
        has_accepted = any(
            r["item_id"] == item["id"] and r["status"] == "QA_ACCEPTED"
            for r in store.referrals.values()
        )
        if not has_accepted:
            raise specialty_required("High-value item requires a QA_ACCEPTED specialty referral")

    placement = make_common_fields()
    placement.update({
        "item_id": item["id"],
        "vault_id": vault["id"],
        "placed_on": store.today_str(),
        "released_on": None,
        "release_reason": None,
        "monthly_rate_cents": item["volume_cu_ft"] * vault["monthly_rate_cents_per_cu_ft"],
        "status": "ACTIVE",
    })
    store.placements[placement["id"]] = placement

    item["processing_status"] = "IN_STORAGE"
    touch(item)
    recompute_vault(vault)
    job = job_of_item(item)
    if job is not None:
        recompute_provisional_statements_for_job(job["id"])
        recompute_job_accrued(job)
    room = store.rooms.get(item["room_id"])
    if room is not None:
        recompute_room(room)
        touch(room)
    return success_object(serialize_placement(placement), status=201)


@bp.route("/api/items/<item_id>/placements", methods=["GET"])
def list_placements_of_item(item_id):
    user_id, role = require_roles("ProjectManager", "InventoryTechnician", "BillingClerk")
    item = get_item(item_id)
    placements = placements_of_item(item["id"])
    placements.sort(key=lambda p: p["created_at"])
    return success([serialize_placement(p) for p in placements], status=200, response_type="array")


@bp.route("/api/vaults/<vault_id>/placements", methods=["GET"])
def list_placements_of_vault(vault_id):
    user_id, role = require_roles("ProjectManager", "InventoryTechnician", "BillingClerk")
    vault = get_vault(vault_id)
    placements = [p for p in store.placements.values() if p["vault_id"] == vault["id"]]
    placements.sort(key=lambda p: p["created_at"])
    return success([serialize_placement(p) for p in placements], status=200, response_type="array")


@bp.route("/api/storage-placements/<placement_id>/release", methods=["POST"])
def release_placement(placement_id):
    user_id, role = require_roles("InventoryTechnician")
    placement = get_placement(placement_id)
    if placement["status"] != "ACTIVE":
        raise invalid_transition("Placement is not ACTIVE")
    placement["status"] = "RELEASED"
    placement["released_on"] = store.today_str()
    placement["release_reason"] = "MANUAL"
    touch(placement)
    vault = store.vaults.get(placement["vault_id"])
    if vault is not None:
        recompute_vault(vault)
    item = store.items.get(placement["item_id"])
    if item is not None:
        item["processing_status"] = "CLEANED"
        touch(item)
        room = store.rooms.get(item["room_id"])
        if room is not None:
            recompute_room(room)
            touch(room)
    job = job_of_item(item) if item is not None else None
    if job is not None:
        recompute_provisional_statements_for_job(job["id"])
        recompute_job_accrued(job)
    return success_object(serialize_placement(placement))
