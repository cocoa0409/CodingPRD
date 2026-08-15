"""Rate-table endpoints (PRD 3.2): DRAFT → PUBLISHED → SUPERSEDED."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_DATE_RANGE, ERR_INVALID_STATE,
    ERR_RATE_TABLE_OVERLAP,
)
from middleware import require_roles
from response import success_object, success_list
from routes.common import resolve_carrier, resolve_rate_table
from serializers import rate_table_view
from util import (
    get_json_body, reject_unknown_fields, require_string, require_int,
    require_enum, require_datetime, optional_datetime, optional_string,
    optional_int, parse_pagination, paginate, sort_created, query_arg, dt,
)

bp = Blueprint("rate_tables", __name__)

ALL_ROLES = ("PlatformAdmin", "Underwriter", "Policyholder", "Adjuster", "ClaimsApprover")
SPECIES = {"CATTLE", "SWINE", "POULTRY", "EQUINE", "SHEEP"}

CREATE_FIELDS = {
    "rating_kind", "county_code", "crop_code", "species",
    "value_band_floor_cents", "value_band_ceiling_cents",
    "rate_per_100_cents_of_liability", "effective_from", "effective_to",
}


def _windows_overlap(a_from: str, a_to, b_from: str, b_to) -> bool:
    """Overlap of half-open [from, to) windows; None means open-ended."""
    if b_to is not None and not (dt(a_from) < dt(b_to)):
        return False
    if a_to is not None and not (dt(b_from) < dt(a_to)):
        return False
    return True


def _bands_overlap(a_floor, a_ceil, b_floor, b_ceil) -> bool:
    return a_floor < b_ceil and b_floor < a_ceil


@bp.route("/carriers/<carrierId>/rate-tables", methods=["POST"])
@require_roles("Underwriter")
def create_rate_table(carrierId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    rating_kind = require_enum(body, "rating_kind", {"CROP_HAIL", "LIVESTOCK_MORTALITY"})

    county_code = optional_string(body, "county_code")
    crop_code = optional_string(body, "crop_code")
    species = None
    if "species" in body and body["species"] is not None:
        species = require_enum(body, "species", SPECIES)
    floor = optional_int(body, "value_band_floor_cents", minimum=0)
    ceiling = optional_int(body, "value_band_ceiling_cents", minimum=0)

    if rating_kind == "CROP_HAIL":
        if county_code is None or county_code == "":
            raise_err(ERR_INVALID_REQUEST, "county_code is required for CROP_HAIL rows")
        if crop_code is None or crop_code == "":
            raise_err(ERR_INVALID_REQUEST, "crop_code is required for CROP_HAIL rows")
        if species is not None or floor is not None or ceiling is not None:
            raise_err(
                ERR_INVALID_REQUEST,
                "species and value band fields must be absent for CROP_HAIL rows",
            )
    else:
        if species is None:
            raise_err(ERR_INVALID_REQUEST, "species is required for LIVESTOCK_MORTALITY rows")
        if floor is None or ceiling is None:
            raise_err(ERR_INVALID_REQUEST,
                      "value band floor and ceiling are required for LIVESTOCK_MORTALITY rows")
        if ceiling <= floor:
            raise_err(ERR_INVALID_REQUEST,
                      "value_band_ceiling_cents must exceed value_band_floor_cents")
        if county_code is not None or crop_code is not None:
            raise_err(
                ERR_INVALID_REQUEST,
                "county_code and crop_code must be absent for LIVESTOCK_MORTALITY rows",
            )

    rate = require_int(body, "rate_per_100_cents_of_liability", minimum=0)
    effective_from = require_datetime(body, "effective_from")
    effective_to = optional_datetime(body, "effective_to")
    if effective_to is not None and dt(effective_to) <= dt(effective_from):
        raise_err(ERR_INVALID_DATE_RANGE,
                  "effective_to must fall after effective_from")

    row = db.stamp_new({
        "carrier_id": carrier["id"],
        "rating_kind": rating_kind,
        "county_code": county_code if rating_kind == "CROP_HAIL" else None,
        "crop_code": crop_code if rating_kind == "CROP_HAIL" else None,
        "species": species if rating_kind == "LIVESTOCK_MORTALITY" else None,
        "value_band_floor_cents": floor if rating_kind == "LIVESTOCK_MORTALITY" else None,
        "value_band_ceiling_cents": ceiling if rating_kind == "LIVESTOCK_MORTALITY" else None,
        "rate_per_100_cents_of_liability": rate,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "DRAFT",
    }, carrier["current_utc"])
    db.rate_tables[row["id"]] = row
    return success_object(rate_table_view(row), 201)


@bp.route("/carriers/<carrierId>/rate-tables", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_rate_tables(carrierId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    items = [r for r in db.rate_tables.values() if r["carrier_id"] == carrier["id"]]
    rating_kind = query_arg("rating_kind")
    status = query_arg("status")
    if rating_kind is not None:
        items = [r for r in items if r["rating_kind"] == rating_kind]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([rate_table_view(r) for r in page], limit, offset, total)


@bp.route("/carriers/<carrierId>/rate-tables/<rateTableId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_rate_table(carrierId: str, rateTableId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    row = resolve_rate_table(carrier["id"], rateTableId)
    return success_object(rate_table_view(row))


@bp.route("/carriers/<carrierId>/rate-tables/<rateTableId>/publish", methods=["POST"])
@require_roles("Underwriter")
def publish_rate_table(carrierId: str, rateTableId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    row = resolve_rate_table(carrier["id"], rateTableId)
    body = get_json_body()
    reject_unknown_fields(body, set())

    if row["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "publish requires the rate row to be DRAFT")

    for other in db.rate_tables.values():
        if other["id"] == row["id"]:
            continue
        if other["carrier_id"] != carrier["id"] or other["status"] != "PUBLISHED":
            continue
        if other["rating_kind"] != row["rating_kind"]:
            continue
        if row["rating_kind"] == "CROP_HAIL":
            if (other["county_code"] != row["county_code"]
                    or other["crop_code"] != row["crop_code"]):
                continue
        else:
            if other["species"] != row["species"]:
                continue
            if not _bands_overlap(
                row["value_band_floor_cents"], row["value_band_ceiling_cents"],
                other["value_band_floor_cents"], other["value_band_ceiling_cents"],
            ):
                continue
        if _windows_overlap(
            row["effective_from"], row["effective_to"],
            other["effective_from"], other["effective_to"],
        ):
            raise_err(
                ERR_RATE_TABLE_OVERLAP,
                "A PUBLISHED row with the same rating axis and an overlapping window exists",
            )

    row["status"] = "PUBLISHED"
    db.touch(row, carrier["current_utc"])
    return success_object(rate_table_view(row))


@bp.route("/carriers/<carrierId>/rate-tables/<rateTableId>/supersede", methods=["POST"])
@require_roles("Underwriter")
def supersede_rate_table(carrierId: str, rateTableId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    row = resolve_rate_table(carrier["id"], rateTableId)
    body = get_json_body()
    reject_unknown_fields(body, set())

    if row["status"] != "PUBLISHED":
        raise_err(ERR_INVALID_STATE, "supersede requires the rate row to be PUBLISHED")
    row["status"] = "SUPERSEDED"
    db.touch(row, carrier["current_utc"])
    return success_object(rate_table_view(row))
