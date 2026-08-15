"""Container endpoints: create, get, list, move, label, stage, void, inspections."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from core import (
    base_entity,
    bump,
    compute_category,
    now_iso,
    recompute_category_and_reports,
    refresh_container_flags,
)
from db import _parse_iso, clock, iso_utc, store
from errors import (
    ApiError,
    ERR_ACCUMULATION_LIMIT_EXCEEDED,
    ERR_ALREADY_TERMINAL,
    ERR_AREA_TYPE_MISMATCH,
    ERR_CONTAINER_NOT_LABELED,
    ERR_CROSS_SITE_REFERENCE,
    ERR_INSPECTION_NOTE_REQUIRED,
    ERR_INSPECTION_OVERDUE,
    ERR_LABEL_MISSING_HAZARD_TEXT,
    ERR_LABEL_START_DATE_MISMATCH,
    ERR_SOD_SELF_INSPECTION,
    ERR_STREAM_NOT_ACTIVE,
    already_terminal,
    invalid_request,
    invalid_state,
    not_found,
)
from middleware import require_roles
from response import success_list, success_object
from validators import (
    opt_str,
    reject_unknown_fields,
    req_enum,
    req_num,
    req_str,
    require_fields,
    require_object,
)

bp = Blueprint("containers", __name__)

ALL_ROLES = ("EHSManager", "WasteCoordinator", "ComplianceAuditor", "TransporterAgent", "TSDFAgent")

_SATELLITE_LIMIT_GAL = 55.0
_MOVE_GRACE_DAYS = 3
_OPEN_FOR_RETIRE = {
    "ACCUMULATING_AT_SATELLITE",
    "SATELLITE_LIMIT_EXCEEDED",
    "IN_CENTRAL_ACCUMULATION",
    "STAGED_FOR_SHIPMENT",
}


def _parse_pagination():
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (ValueError, TypeError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (ValueError, TypeError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def container_view(c: dict) -> dict:
    # refresh transient flags for read freshness
    refresh_container_flags(c)
    return dict(c)


@bp.route("/hazwaste/containers", methods=["POST"])
def create_container():
    user_id, _ = require_roles("WasteCoordinator")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {"waste_stream_id", "accumulation_area_id", "quantity_gallons", "quantity_kg"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["waste_stream_id", "accumulation_area_id", "quantity_gallons", "quantity_kg"])
    waste_stream_id = req_str(body, "waste_stream_id")
    accumulation_area_id = req_str(body, "accumulation_area_id")
    quantity_gallons = req_num(body, "quantity_gallons")
    quantity_kg = req_num(body, "quantity_kg")
    if quantity_gallons <= 0:
        raise invalid_request("quantity_gallons must be > 0")
    if quantity_kg <= 0:
        raise invalid_request("quantity_kg must be > 0")

    # Existence, left-to-right: stream then area
    stream = store.streams.get(waste_stream_id)
    if stream is None:
        raise not_found("waste stream not found")
    area = store.areas.get(accumulation_area_id)
    if area is None:
        raise not_found("accumulation area not found")

    # Business: stream must be ACTIVE; cross-site check
    if stream["status"] != "ACTIVE":
        raise ApiError(ERR_STREAM_NOT_ACTIVE, 409, "waste stream is not ACTIVE")
    if area["site_id"] != stream["site_id"]:
        raise ApiError(ERR_CROSS_SITE_REFERENCE, 409, "area site != stream site")

    site = store.sites[area["site_id"]]

    c = base_entity()
    c.update(
        {
            "waste_stream_id": waste_stream_id,
            "accumulation_area_id": accumulation_area_id,
            "site_id": area["site_id"],
            "quantity_gallons": quantity_gallons,
            "quantity_kg": quantity_kg,
            "status": "ACCUMULATING_AT_SATELLITE",  # may be rewritten below
            "accumulation_start_date": None,
            "deadline_days": None,
            "accumulation_deadline_at": None,
            "is_accumulation_overdue": False,
            "satellite_exceeded_at": None,
            "move_deadline_at": None,
            "is_move_late": False,
            "is_labeled": False,
            "label_text": None,
            "label_accumulation_start_marked": None,
            "last_inspected_at": None,
            "is_inspection_overdue": False,
            "last_action_user_id": user_id,
            "created_by_user_id": user_id,
            "shipped_manifest_id": None,
        }
    )

    # Hop 1: month total + stream lifetime total
    site["current_month_generated_kg"] = site.get("current_month_generated_kg", 0) + quantity_kg
    bump(site)
    stream["total_generated_kg"] = stream.get("total_generated_kg", 0) + quantity_kg
    bump(stream)

    # Hop 2 (and 3): category + report fee recompute
    recompute_category_and_reports(site)

    # Placement: satellite vs central
    if area["area_type"] == "CENTRAL_90DAY":
        now = clock.now()
        c["status"] = "IN_CENTRAL_ACCUMULATION"
        c["accumulation_start_date"] = iso_utc(now)
        # snapshot deadline_days from CURRENT site category (post-increment)
        cat = site["generator_category"]
        days = 90 if cat == "LQG" else 180
        c["deadline_days"] = days
        c["accumulation_deadline_at"] = iso_utc(now + timedelta(days=days))
    else:
        # SATELLITE placement; check 55-gal limit per (area, stream) including incoming
        c["status"] = "ACCUMULATING_AT_SATELLITE"
        # satellite evaluation happens after insert; we'll do it after storing

    store.containers[c["id"]] = c

    if area["area_type"] == "SATELLITE":
        total_gal = 0.0
        for other in store.containers.values():
            if (
                other["accumulation_area_id"] == accumulation_area_id
                and other["waste_stream_id"] == waste_stream_id
                and other["status"] in ("ACCUMULATING_AT_SATELLITE", "SATELLITE_LIMIT_EXCEEDED")
            ):
                total_gal += other["quantity_gallons"]
        if total_gal > _SATELLITE_LIMIT_GAL:
            now = clock.now()
            c["status"] = "SATELLITE_LIMIT_EXCEEDED"
            c["satellite_exceeded_at"] = iso_utc(now)
            c["move_deadline_at"] = iso_utc(now + timedelta(days=_MOVE_GRACE_DAYS))

    refresh_container_flags(c)
    return success_object(container_view(c), status=201)


@bp.route("/hazwaste/containers", methods=["GET"])
def list_containers():
    require_roles(*ALL_ROLES)
    limit, offset = _parse_pagination()
    waste_stream_id = request.args.get("waste_stream_id")
    accumulation_area_id = request.args.get("accumulation_area_id")
    site_id = request.args.get("site_id")
    shipped_manifest_id = request.args.get("shipped_manifest_id")
    items = list(store.containers.values())
    if waste_stream_id is not None:
        items = [c for c in items if c["waste_stream_id"] == waste_stream_id]
    if accumulation_area_id is not None:
        items = [c for c in items if c["accumulation_area_id"] == accumulation_area_id]
    if site_id is not None:
        items = [c for c in items if c["site_id"] == site_id]
    if shipped_manifest_id is not None:
        items = [c for c in items if c.get("shipped_manifest_id") == shipped_manifest_id]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([container_view(c) for c in page], limit, offset, total)


@bp.route("/hazwaste/containers/<containerId>", methods=["GET"])
def get_container(containerId: str):
    require_roles(*ALL_ROLES)
    c = store.containers.get(containerId)
    if c is None:
        raise not_found("container not found")
    return success_object(container_view(c))


@bp.route("/hazwaste/containers/<containerId>/move", methods=["POST"])
def move_container(containerId: str):
    user_id, _ = require_roles("WasteCoordinator")
    c = store.containers.get(containerId)
    if c is None:
        raise not_found("container not found")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {"target_area_id"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["target_area_id"])
    target_area_id = req_str(body, "target_area_id")

    # Existence
    target = store.areas.get(target_area_id)
    if target is None:
        raise not_found("target area not found")

    # State: must be in satellite statuses
    if c["status"] in ("EMPTIED", "VOIDED"):
        raise already_terminal("container is terminal")
    if c["status"] not in ("ACCUMULATING_AT_SATELLITE", "SATELLITE_LIMIT_EXCEEDED"):
        raise invalid_state(f"cannot move from status {c['status']}")

    # Business
    if target["area_type"] != "CENTRAL_90DAY":
        raise ApiError(ERR_AREA_TYPE_MISMATCH, 409, "target area must be CENTRAL_90DAY")
    if target["site_id"] != c["site_id"]:
        raise ApiError(ERR_CROSS_SITE_REFERENCE, 409, "target area site != container site")

    now = clock.now()
    was_exceeded = c["status"] == "SATELLITE_LIMIT_EXCEEDED"
    is_move_late = False
    if was_exceeded and c.get("move_deadline_at"):
        is_move_late = now > _parse_iso(c["move_deadline_at"])

    site = store.sites[c["site_id"]]
    c["accumulation_area_id"] = target_area_id
    c["status"] = "IN_CENTRAL_ACCUMULATION"
    c["accumulation_start_date"] = iso_utc(now)
    cat = site["generator_category"]
    days = 90 if cat == "LQG" else 180
    c["deadline_days"] = days
    c["accumulation_deadline_at"] = iso_utc(now + timedelta(days=days))
    c["is_move_late"] = is_move_late
    c["last_action_user_id"] = user_id
    refresh_container_flags(c)
    bump(c)
    return success_object(container_view(c))


@bp.route("/hazwaste/containers/<containerId>/label", methods=["POST"])
def label_container(containerId: str):
    user_id, _ = require_roles("WasteCoordinator")
    c = store.containers.get(containerId)
    if c is None:
        raise not_found("container not found")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {"label_text", "label_accumulation_start_marked"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["label_text", "label_accumulation_start_marked"])
    label_text = req_str(body, "label_text")
    label_start_marked = req_str(body, "label_accumulation_start_marked")

    if c["status"] in ("EMPTIED", "VOIDED"):
        raise already_terminal("container is terminal")

    if "Hazardous Waste" not in label_text:
        raise ApiError(ERR_LABEL_MISSING_HAZARD_TEXT, 400, "label_text must contain 'Hazardous Waste'")
    if label_start_marked != c.get("accumulation_start_date"):
        raise ApiError(
            ERR_LABEL_START_DATE_MISMATCH,
            400,
            "label_accumulation_start_marked must equal accumulation_start_date",
        )

    c["is_labeled"] = True
    c["label_text"] = label_text
    c["label_accumulation_start_marked"] = label_start_marked
    bump(c)
    return success_object(container_view(c))


@bp.route("/hazwaste/containers/<containerId>/stage", methods=["POST"])
def stage_container(containerId: str):
    user_id, _ = require_roles("WasteCoordinator")
    c = store.containers.get(containerId)
    if c is None:
        raise not_found("container not found")
    body = request.get_json(silent=True) or {}
    if body:
        require_object(body)
        reject_unknown_fields(body, set())

    if c["status"] in ("EMPTIED", "VOIDED"):
        raise already_terminal("container is terminal")
    if c["status"] != "IN_CENTRAL_ACCUMULATION":
        raise invalid_state(f"cannot stage from status {c['status']}")

    refresh_container_flags(c)
    if not c.get("is_labeled"):
        raise ApiError(ERR_CONTAINER_NOT_LABELED, 409, "container is not labeled")
    if c.get("is_inspection_overdue"):
        raise ApiError(ERR_INSPECTION_OVERDUE, 409, "container inspection overdue")
    if c.get("is_accumulation_overdue"):
        raise ApiError(ERR_ACCUMULATION_LIMIT_EXCEEDED, 409, "container accumulation limit exceeded")

    c["status"] = "STAGED_FOR_SHIPMENT"
    bump(c)
    refresh_container_flags(c)
    return success_object(container_view(c))


@bp.route("/hazwaste/containers/<containerId>/void", methods=["POST"])
def void_container(containerId: str):
    user_id, _ = require_roles("WasteCoordinator")
    c = store.containers.get(containerId)
    if c is None:
        raise not_found("container not found")
    body = request.get_json(silent=True) or {}
    if body:
        require_object(body)
        reject_unknown_fields(body, set())

    if c["status"] in ("EMPTIED", "VOIDED"):
        raise already_terminal("container is terminal")
    if c.get("shipped_manifest_id") is not None:
        raise invalid_state("container already linked to a shipped manifest")
    if c["status"] not in (
        "ACCUMULATING_AT_SATELLITE",
        "SATELLITE_LIMIT_EXCEEDED",
        "IN_CENTRAL_ACCUMULATION",
        "STAGED_FOR_SHIPMENT",
    ):
        raise invalid_state(f"cannot void from status {c['status']}")

    site = store.sites[c["site_id"]]
    stream = store.streams.get(c["waste_stream_id"])

    # Reverse month total when the container was created in the site's current month
    created_key = _parse_iso(c["created_at"]).strftime("%Y-%m")
    if created_key == site["current_month_key"]:
        site["current_month_generated_kg"] = site.get("current_month_generated_kg", 0) - c["quantity_kg"]
        bump(site)

    if stream is not None:
        stream["total_generated_kg"] = stream.get("total_generated_kg", 0) - c["quantity_kg"]
        bump(stream)

    c["status"] = "VOIDED"
    refresh_container_flags(c)
    bump(c)

    recompute_category_and_reports(site)
    return success_object(container_view(c))


@bp.route("/hazwaste/containers/<containerId>/inspections", methods=["POST"])
def create_inspection(containerId: str):
    user_id, _ = require_roles("WasteCoordinator")
    c = store.containers.get(containerId)
    if c is None:
        raise not_found("container not found")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {"result", "deficiency_note"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["result"])
    result = req_enum(body, "result", {"PASS", "FAIL"})
    deficiency_note = opt_str(body, "deficiency_note")

    # shape-band: FAIL requires deficiency_note
    if result == "FAIL" and not deficiency_note:
        raise ApiError(ERR_INSPECTION_NOTE_REQUIRED, 400, "deficiency_note required when result is FAIL")

    # SoD
    if user_id == c.get("last_action_user_id"):
        raise ApiError(ERR_SOD_SELF_INSPECTION, 403, "inspector must differ from last mover")

    insp = base_entity()
    insp.update(
        {
            "container_id": containerId,
            "inspector_user_id": user_id,
            "inspected_at": now_iso(),
            "result": result,
            "deficiency_note": deficiency_note,
        }
    )
    store.inspections[insp["id"]] = insp

    c["last_inspected_at"] = insp["inspected_at"]
    refresh_container_flags(c)
    bump(c)
    return success_object(dict(insp), status=201)


@bp.route("/hazwaste/containers/<containerId>/inspections", methods=["GET"])
def list_inspections(containerId: str):
    require_roles(*ALL_ROLES)
    c = store.containers.get(containerId)
    if c is None:
        raise not_found("container not found")
    limit, offset = _parse_pagination()
    items = [i for i in store.inspections.values() if i["container_id"] == containerId]
    items.sort(key=lambda i: i["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([dict(i) for i in page], limit, offset, total)
