"""Tariff endpoints (PRD section 3.2).

Tariff windows are HALF-OPEN [effective_from, effective_to); adjacency is not
an intersection. Publish is SoD-guarded (publisher != draft creator).
"""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TARIFF_INVALID_STATE,
    ERR_TARIFF_MISMATCH,
    ERR_TARIFF_NOT_FOUND,
    ERR_TARIFF_WINDOW_OVERLAP,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from util import (
    apply_filters,
    get_json_body,
    has_field,
    optional_enum,
    optional_field,
    optional_string,
    paginate,
    parse_pagination,
    pub,
    require_enum,
    require_int,
    require_string,
    require_ts,
    sort_by_created_at,
)

bp = Blueprint("tariffs", __name__)

COMMODITY_TYPES = {"GENERAL", "REEFER", "HAZMAT"}
MODES = {"FCL", "LCL"}
CONTAINER_TYPES = {"20GP", "40GP", "40HC", "40RF"}


def tariff_key(t: dict) -> tuple:
    return (
        t["origin_port"],
        t["destination_port"],
        t["commodity_type"],
        t["mode"],
        t.get("container_type"),
    )


def _get_tariff(tariff_id: str) -> dict:
    tariff = db.tariffs.get(tariff_id)
    if tariff is None:
        raise_err(ERR_TARIFF_NOT_FOUND, "Tariff id does not exist")
    return tariff


@bp.route("/freight/tariffs", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_tariff(_user_id: str, _role: str):
    body = get_json_body()
    tariff_code = require_string(body, "tariff_code")
    origin_port = require_string(body, "origin_port")
    destination_port = require_string(body, "destination_port")
    commodity_type = require_enum(body, "commodity_type", COMMODITY_TYPES)
    mode = require_enum(body, "mode", MODES)
    rate_per_unit_cents = require_int(body, "rate_per_unit_cents", minimum=1)
    minimum_charge_cents = optional_field(body, "minimum_charge_cents", 0)
    if isinstance(minimum_charge_cents, bool) or not isinstance(minimum_charge_cents, int) or minimum_charge_cents < 0:
        raise_err(ERR_INVALID_REQUEST, "minimum_charge_cents must be an integer >= 0")
    effective_from = require_ts(body, "effective_from")
    effective_to = require_ts(body, "effective_to")

    # Conditional field rule: container_type required iff mode == FCL.
    container_type = optional_enum(body, "container_type", CONTAINER_TYPES)
    if mode == "FCL" and container_type is None:
        raise_err(ERR_INVALID_REQUEST, "container_type is required when mode is FCL")
    if mode == "LCL" and has_field(body, "container_type"):
        raise_err(ERR_INVALID_REQUEST, "container_type is forbidden when mode is LCL")

    if not (effective_from < effective_to):
        raise_err(ERR_INVALID_REQUEST, "effective_from must be strictly before effective_to")

    tariff = {
        "tariff_code": tariff_code,
        "origin_port": origin_port,
        "destination_port": destination_port,
        "commodity_type": commodity_type,
        "mode": mode,
        "container_type": container_type,
        "rate_per_unit_cents": rate_per_unit_cents,
        "minimum_charge_cents": minimum_charge_cents,
        "effective_from": db.format_iso(effective_from),
        "effective_to": db.format_iso(effective_to),
        "status": "DRAFT",
        "created_by_user_id": _user_id,
        "published_by_user_id": None,
    }
    db.stamp_new(tariff)
    db.tariffs[tariff["id"]] = tariff
    return success_object(pub(tariff), 201)


@bp.route("/freight/tariffs", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_tariffs(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.tariffs.values()))
    items = apply_filters(items, ["status", "origin_port", "destination_port"])
    page, total = paginate(items, limit, offset)
    return success_list([pub(t) for t in page], limit, offset, total)


@bp.route("/freight/tariffs/<tariff_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_tariff(tariff_id: str, _user_id: str, _role: str):
    return success_object(pub(_get_tariff(tariff_id)))


@bp.route("/freight/tariffs/<tariff_id>/publish", methods=["POST"])
@require_roles("ComplianceOfficer")
def publish_tariff(tariff_id: str, _user_id: str, _role: str):
    tariff = _get_tariff(tariff_id)
    body = get_json_body()

    # Band 3: optional supersedes FK must exist.
    supersede_target = None
    supersedes_tariff_id = optional_string(body, "supersedes_tariff_id")
    if supersedes_tariff_id is not None:
        supersede_target = db.tariffs.get(supersedes_tariff_id)
        if supersede_target is None:
            raise_err(ERR_TARIFF_NOT_FOUND, "supersedes_tariff_id does not exist")

    # Band 4: segregation of duties — publisher != draft creator.
    if _user_id == tariff["created_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Tariff publisher must differ from draft creator")

    # Band 5: window validity.
    if not (db.parse_iso(tariff["effective_from"]) < db.parse_iso(tariff["effective_to"])):
        raise_err(ERR_INVALID_REQUEST, "effective_from must be strictly before effective_to")

    # Band 6: state.
    if tariff["status"] != "DRAFT":
        raise_err(ERR_TARIFF_INVALID_STATE, "Tariff must be DRAFT to publish")

    # Supersede target sanity: must be PUBLISHED with the same key tuple.
    if supersede_target is not None:
        if supersede_target["status"] != "PUBLISHED":
            raise_err(ERR_TARIFF_INVALID_STATE, "supersedes_tariff_id must name a PUBLISHED tariff")
        if tariff_key(supersede_target) != tariff_key(tariff):
            raise_err(ERR_TARIFF_MISMATCH, "supersedes_tariff_id must share the same key tuple")

    # Band 11: half-open window overlap against OTHER PUBLISHED tariffs with an
    # identical key tuple. Adjacency (a.effective_to == b.effective_from) is NOT
    # an intersection.
    t_from = db.parse_iso(tariff["effective_from"])
    t_to = db.parse_iso(tariff["effective_to"])
    for other in db.tariffs.values():
        if other["id"] == tariff["id"] or other["id"] == (supersedes_tariff_id or ""):
            continue
        if other["status"] != "PUBLISHED":
            continue
        if tariff_key(other) != tariff_key(tariff):
            continue
        o_from = db.parse_iso(other["effective_from"])
        o_to = db.parse_iso(other["effective_to"])
        if t_from < o_to and o_from < t_to:
            raise_err(
                ERR_TARIFF_WINDOW_OVERLAP,
                "Another PUBLISHED tariff with the same key has an intersecting window",
            )

    tariff["status"] = "PUBLISHED"
    tariff["published_by_user_id"] = _user_id
    db.touch(tariff)
    if supersede_target is not None:
        supersede_target["status"] = "SUPERSEDED"
        db.touch(supersede_target)
    return success_object(pub(tariff))


@bp.route("/freight/tariffs/<tariff_id>/retire", methods=["POST"])
@require_roles("ComplianceOfficer")
def retire_tariff(tariff_id: str, _user_id: str, _role: str):
    tariff = _get_tariff(tariff_id)
    if tariff["status"] != "PUBLISHED":
        raise_err(ERR_TARIFF_INVALID_STATE, "Tariff must be PUBLISHED to retire")
    tariff["status"] = "RETIRED"
    db.touch(tariff)
    return success_object(pub(tariff))
