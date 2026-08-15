"""SalvageManifest and SalvageItem endpoints: dual-variant valuation,
finalize/amend cycle, and the net-credit invariant."""

from flask import Blueprint

from db import store, now, new_record, touch
from errors import (err, ERR_VALIDATION, ERR_INVALID_STATE, ERR_MANIFEST_EMPTY)
from middleware import require_roles, body
from response import success, list_response
from serializers import ser_salvage_manifest, ser_salvage_item
from services import get_project, get_salvage_manifest, children
from util import req_str, req_enum, req_int

bp = Blueprint("salvage", __name__)

VALUATION_POLICIES = ("OPTIMISTIC", "CONSERVATIVE")
MATERIALS = ("STEEL", "COPPER", "BRICK", "TIMBER", "CONCRETE", "FIXTURES")
UNITS = ("TON", "LB", "EACH", "CU_YD")
SALVAGE_READ_ROLES = ("ContractorAdmin", "SiteSupervisor", "SalvageEstimator")
MANIFEST_ACTIONS = ("FINALIZE", "AMEND")


def _manifest_items(manifest_id):
    return children(store.salvage_items, "salvage_manifest_id", manifest_id)


def _recompute_totals(manifest):
    """Both totals shadow each other at all times over ALL items (amendment
    lines included with signed quantities). Integer cents; no rounding."""
    items = _manifest_items(manifest["id"])
    manifest["optimistic_total_cents"] = sum(i["quantity"] * i["high_unit_value_cents"] for i in items)
    manifest["conservative_total_cents"] = sum(i["quantity"] * i["low_unit_value_cents"] for i in items)


def _policy_total(manifest):
    if manifest["valuation_policy"] == "OPTIMISTIC":
        return manifest["optimistic_total_cents"]
    return manifest["conservative_total_cents"]


def _recompute_net_credit(manifest):
    manifest["net_credit_cents"] = _policy_total(manifest) - manifest["processing_fee_cents"]


@bp.post("/demolition/projects/<pid>/salvage-manifests")
@require_roles("SalvageEstimator")
def create_manifest(pid):
    b = body()
    policy = req_enum(b, "valuation_policy", VALUATION_POLICIES)
    fee = req_int(b, "processing_fee_cents", minimum=0)
    project = get_project(pid)

    rec = new_record()
    rec.update({
        "project_id": project["id"],
        "valuation_policy": policy,
        "processing_fee_cents": fee,
        "status": "DRAFT",
        "optimistic_total_cents": 0,
        "conservative_total_cents": 0,
        "net_credit_cents": 0,
        "amendment_count": 0,
        "finalized_at": None,
    })
    store.salvage_manifests[rec["id"]] = rec
    return success(ser_salvage_manifest(rec), status=201)


@bp.get("/demolition/projects/<pid>/salvage-manifests")
@require_roles(*SALVAGE_READ_ROLES)
def list_manifests(pid):
    project = get_project(pid)
    return list_response(children(store.salvage_manifests, "project_id", project["id"]),
                         ser_salvage_manifest)


@bp.get("/demolition/salvage-manifests/<mid>")
@require_roles(*SALVAGE_READ_ROLES)
def get_one_manifest(mid):
    return success(ser_salvage_manifest(get_salvage_manifest(mid)))


@bp.post("/demolition/salvage-manifests/<mid>/items")
@require_roles("SalvageEstimator")
def add_item(mid):
    b = body()
    material = req_enum(b, "material", MATERIALS)
    description = req_str(b, "description")
    unit = req_enum(b, "unit", UNITS)
    low = req_int(b, "low_unit_value_cents", minimum=0)
    high = req_int(b, "high_unit_value_cents", minimum=0)
    if high < low:
        raise err(ERR_VALIDATION, "high_unit_value_cents must be >= low_unit_value_cents")
    quantity = req_int(b, "quantity")

    manifest = get_salvage_manifest(mid)
    if manifest["status"] == "DRAFT":
        if quantity <= 0:
            raise err(ERR_VALIDATION, "quantity must be positive on a normal salvage line")
        is_amendment = False
    elif manifest["status"] == "AMENDED":
        is_amendment = True
    else:
        raise err(ERR_INVALID_STATE, "items can only be added while DRAFT or AMENDED")

    rec = new_record()
    unit_value = high if manifest["valuation_policy"] == "OPTIMISTIC" else low
    rec.update({
        "salvage_manifest_id": manifest["id"],
        "material": material,
        "description": description,
        "quantity": quantity,
        "unit": unit,
        "low_unit_value_cents": low,
        "high_unit_value_cents": high,
        "is_amendment_line": is_amendment,
        "extended_value_cents": quantity * unit_value,
    })
    store.salvage_items[rec["id"]] = rec

    _recompute_totals(manifest)
    # net_credit_cents recomputes on FINALIZE and on each AMENDED item add;
    # while DRAFT it stays at its last finalized value.
    if manifest["status"] == "AMENDED":
        _recompute_net_credit(manifest)
    touch(manifest)
    return success(ser_salvage_item(rec), status=201)


@bp.get("/demolition/salvage-manifests/<mid>/items")
@require_roles(*SALVAGE_READ_ROLES)
def list_items(mid):
    manifest = get_salvage_manifest(mid)
    return list_response(_manifest_items(manifest["id"]), ser_salvage_item)


@bp.post("/demolition/salvage-manifests/<mid>/transition")
@require_roles("SalvageEstimator")
def manifest_transition(mid):
    b = body()
    action = b.get("action")
    if not isinstance(action, str) or action not in MANIFEST_ACTIONS:
        raise err(ERR_VALIDATION, "invalid action")
    manifest = get_salvage_manifest(mid)
    status = manifest["status"]

    if action == "FINALIZE":
        if status not in ("DRAFT", "AMENDED"):
            raise err(ERR_INVALID_STATE, "FINALIZE requires DRAFT or AMENDED")
        if not _manifest_items(manifest["id"]):
            raise err(ERR_MANIFEST_EMPTY, "cannot finalize an empty manifest")
        _recompute_totals(manifest)
        _recompute_net_credit(manifest)
        manifest["finalized_at"] = now()
        manifest["status"] = "FINALIZED"
    else:  # AMEND
        if status != "FINALIZED":
            raise err(ERR_INVALID_STATE, "AMEND requires FINALIZED")
        manifest["status"] = "AMENDED"
        manifest["amendment_count"] += 1

    touch(manifest)
    return success(ser_salvage_manifest(manifest))
