"""EquipmentKit CRUD per PRD §3.2."""
from __future__ import annotations

from typing import Any, Dict

from flask import Flask, request

from ._common import (
    ANY_ROLE,
    ApiError,
    DB,
    GLOBAL_LOCK,
    append_audit,
    check_if_match,
    equipment_kit_peak_demand_for_kit,
    get_json_body,
    if_match_header,
    list_by_predicate,
    make_blueprint,
    optional_str,
    paginate_list,
    require_int,
    require_role,
    require_str,
    resolve_festival,
    stamp_create,
    stamp_update,
    success_envelope,
)


bp = make_blueprint("equipment_kits")


def _payload(k: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": k["id"],
        "festival_id": k.get("festival_id"),
        "kit_code": k.get("kit_code"),
        "total_units": k.get("total_units"),
        "description": k.get("description", ""),
        "created_at": k.get("created_at"),
        "updated_at": k.get("updated_at"),
        "version": k.get("version"),
    }


def _resolve(festival_id: str, kit_id: str) -> Dict[str, Any]:
    resolve_festival(festival_id)
    k = DB.equipment_kits.get(kit_id)
    if k is None:
        raise ApiError(
            "ERR_EQUIPMENT_KIT_NOT_FOUND", f"equipment kit {kit_id} not found"
        )
    if k.get("festival_id") != festival_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT",
            "equipment kit belongs to a different festival",
        )
    return k


@bp.route("/festivals/<festival_id>/equipment-kits", methods=["POST"])
def create_kit(festival_id: str):
    require_role(["StageManager", "FestivalProducer"])
    body = get_json_body()
    with GLOBAL_LOCK:
        resolve_festival(festival_id)
        code = require_str(body, "kit_code")
        # Uniqueness within the festival.
        for existing in DB.equipment_kits.values():
            if (
                existing.get("festival_id") == festival_id
                and existing.get("kit_code") == code
            ):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE",
                    f"kit_code {code!r} already exists in this festival",
                )
        total_units = require_int(body, "total_units", non_negative=True)
        description = optional_str(body, "description", default="") or ""

        row = {
            "festival_id": festival_id,
            "kit_code": code,
            "total_units": total_units,
            "description": description,
        }
        stamp_create(row)
        DB.equipment_kits[row["id"]] = row
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="EquipmentKit",
            subject_entity_id=row["id"],
            payload_summary=f"equipment kit {code!r} registered with {total_units} units",
        )
        out = _payload(row)
    return success_envelope(out, http_status=201)


@bp.route("/festivals/<festival_id>/equipment-kits", methods=["GET"])
def list_kits(festival_id: str):
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        resolve_festival(festival_id)
        rows = list_by_predicate(
            DB.equipment_kits, lambda r: r.get("festival_id") == festival_id
        )
        page, meta = paginate_list(rows, request.args)
        out = [_payload(r) for r in page]
    return success_envelope(out, pagination=meta)


@bp.route("/festivals/<festival_id>/equipment-kits/<kit_id>", methods=["GET"])
def read_kit(festival_id: str, kit_id: str):
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        k = _resolve(festival_id, kit_id)
        out = _payload(k)
    return success_envelope(out)


@bp.route("/festivals/<festival_id>/equipment-kits/<kit_id>", methods=["PATCH"])
def patch_kit(festival_id: str, kit_id: str):
    require_role(["StageManager", "FestivalProducer"])
    body = get_json_body()
    with GLOBAL_LOCK:
        k = _resolve(festival_id, kit_id)
        check_if_match(k, if_match_header())

        if "total_units" in body:
            new_total = body["total_units"]
            if (
                isinstance(new_total, bool)
                or not isinstance(new_total, int)
                or new_total < 0
            ):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE", "total_units must be non-negative integer"
                )
            # Disbursed-floor: the new total must not drop below the festival-wide
            # peak concurrent demand for this kit_code.
            peak = equipment_kit_peak_demand_for_kit(festival_id, k["kit_code"])
            if int(new_total) < int(peak):
                raise ApiError(
                    "ERR_EXPOSURE_CATALOG_BELOW_DISBURSED",
                    f"new total_units {new_total} below peak demand {peak} for kit "
                    f"{k['kit_code']!r}",
                )
            k["total_units"] = int(new_total)

        if "description" in body:
            d = body["description"]
            if d is None:
                d = ""
            if not isinstance(d, str):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE", "description must be a string"
                )
            k["description"] = d

        stamp_update(k)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="EquipmentKit",
            subject_entity_id=kit_id,
            payload_summary="equipment kit fields patched",
        )
        out = _payload(k)
    return success_envelope(out)


def register(app: Flask) -> None:
    app.register_blueprint(bp)
