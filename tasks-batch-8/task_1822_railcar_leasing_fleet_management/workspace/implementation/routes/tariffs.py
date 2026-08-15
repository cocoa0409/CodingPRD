"""Tariff administration (PRD 3.13)."""
from flask import Blueprint, request

import domain
from envelope import ok, ok_list
from errors import ApiError, not_found, validation
from http_util import (
    CAR_TYPES, RATE_KINDS, get_body, parse_pagination, require_roles,
    v_date, v_enum, v_int,
)
from store import db, new_entity, touch

bp_tariffs = Blueprint("tariffs", __name__)

READ_ROLES = ("SystemAdmin", "LeaseAdmin", "FleetPlanner", "BillingAnalyst", "ComplianceOfficer")


def _load_tariff(tariff_id):
    t = db.tariffs.get(tariff_id)
    if t is None:
        # no domain 404 variant exists for tariffs -> generic ERR_NOT_FOUND
        raise not_found("ERR_NOT_FOUND", f"Tariff rate {tariff_id} not found")
    return t


def _check_window(car_type, rate_kind, frm, to, exclude_id=None):
    if to <= frm:
        raise ApiError(
            "ERR_INVALID_DATE_RANGE", 422,
            "effective_to must be strictly after effective_from",
        )
    if domain.tariff_overlaps(car_type, rate_kind, frm, to, exclude_id=exclude_id):
        raise ApiError(
            "ERR_TARIFF_WINDOW_OVERLAP", 422,
            "Tariff window overlaps an existing window for the same car_type and rate_kind",
        )


@bp_tariffs.route("/tariff-rates", methods=["POST"])
@require_roles("LeaseAdmin")
def create_tariff():
    body = get_body()
    car_type = v_enum(body, "car_type", CAR_TYPES)
    rate_kind = v_enum(body, "rate_kind", RATE_KINDS)
    frm = v_date(body, "effective_from")
    to = v_date(body, "effective_to")
    rate = v_int(body, "unit_rate_cents", min=1)
    _check_window(car_type, rate_kind, frm, to)
    t = new_entity(
        {
            "car_type": car_type,
            "rate_kind": rate_kind,
            "effective_from": frm,
            "effective_to": to,
            "unit_rate_cents": rate,
        }
    )
    db.tariffs[t["id"]] = t
    return ok(domain.serialize_tariff(t), status=201)


@bp_tariffs.route("/tariff-rates", methods=["GET"])
@require_roles(*READ_ROLES)
def list_tariffs():
    limit, offset = parse_pagination()
    items = sorted(db.tariffs.values(), key=lambda t: (t["created_at"], t["_created_seq"]))
    car_type = request.args.get("car_type")
    rate_kind = request.args.get("rate_kind")
    if car_type is not None:
        items = [t for t in items if t["car_type"] == car_type]
    if rate_kind is not None:
        items = [t for t in items if t["rate_kind"] == rate_kind]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.serialize_tariff(t) for t in page], limit, offset, total)


@bp_tariffs.route("/tariff-rates/<tariff_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_tariff(tariff_id):
    return ok(domain.serialize_tariff(_load_tariff(tariff_id)))


@bp_tariffs.route("/tariff-rates/<tariff_id>", methods=["PUT"])
@require_roles("LeaseAdmin")
def amend_tariff(tariff_id):
    t = _load_tariff(tariff_id)
    body = get_body()
    expected = v_int(body, "expected_tariff_version")
    new_rate = v_int(body, "unit_rate_cents", required=False, min=1)
    new_from = v_date(body, "effective_from", required=False)
    new_to = v_date(body, "effective_to", required=False)
    if expected != t["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412,
            f"expected_tariff_version {expected} does not match current version {t['version']}",
        )
    frm = new_from if new_from is not None else t["effective_from"]
    to = new_to if new_to is not None else t["effective_to"]
    _check_window(t["car_type"], t["rate_kind"], frm, to, exclude_id=t["id"])
    if new_rate is not None:
        t["unit_rate_cents"] = new_rate
    t["effective_from"] = frm
    t["effective_to"] = to
    touch(t)
    return ok(domain.serialize_tariff(t))
