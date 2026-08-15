"""Rent roll endpoints."""
from flask import request

from db import DB, new_id, now_iso
from errors import ApiError
from middleware import auth, READ_ROLES
from response import ok, ok_list
from services import latest_rent_roll, recompute_occupancy
from util import (
    get_property,
    json_body,
    paginate,
    parse_int_field,
    parse_pagination,
    parse_str_field,
    rent_roll_view,
    touch,
)


def register(app):
    @app.post("/re-underwriting/properties/<prop_id>/rent-roll")
    def append_rent_roll(prop_id):
        _user_id, _role = auth(allowed=["Analyst"])
        prop = get_property(prop_id)
        body = json_body()
        period_month = parse_str_field(body, "period_month")
        occupied_units = parse_int_field(body, "occupied_units")
        if occupied_units < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "occupied_units must be >= 0")
        total_units = parse_int_field(body, "total_units")
        if total_units < 1:
            raise ApiError("ERR_INVALID_REQUEST", 400, "total_units must be >= 1")
        gpr = parse_int_field(body, "gross_potential_rent_cents")
        if gpr < 0:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "gross_potential_rent_cents must be >= 0"
            )
        collected = parse_int_field(body, "collected_rent_cents")
        if collected < 0:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "collected_rent_cents must be >= 0"
            )
        concessions = body.get("concessions_cents", 0)
        if isinstance(concessions, bool) or not isinstance(concessions, int):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "concessions_cents must be an integer"
            )
        if concessions < 0:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "concessions_cents must be >= 0"
            )
        source_doc_ref = parse_str_field(body, "source_doc_ref")

        # duplicate (property_id, period_month)
        for r in DB["rent_roll_periods"].values():
            if r["property_id"] == prop_id and r["period_month"] == period_month:
                raise ApiError(
                    "ERR_DUPLICATE_PERIOD",
                    409,
                    "RentRollPeriod already exists for this property and month",
                )

        # monotonic: period_month strictly greater than latest existing
        latest = latest_rent_roll(prop_id)
        if latest is not None and period_month <= latest["period_month"]:
            raise ApiError(
                "ERR_NONMONOTONIC_PERIOD",
                422,
                "period_month must be strictly greater than the latest existing period_month",
            )

        rec = {
            "id": new_id(),
            "property_id": prop_id,
            "period_month": period_month,
            "occupied_units": occupied_units,
            "total_units": total_units,
            "gross_potential_rent_cents": gpr,
            "collected_rent_cents": collected,
            "concessions_cents": concessions,
            "source_doc_ref": source_doc_ref,
            "created_at": now_iso(),
        }
        DB["rent_roll_periods"][rec["id"]] = rec
        recompute_occupancy(prop)
        touch(prop)
        return ok(rent_roll_view(rec), status=201)

    @app.get("/re-underwriting/properties/<prop_id>/rent-roll")
    def list_rent_roll(prop_id):
        auth(allowed=READ_ROLES)
        get_property(prop_id)
        limit, offset = parse_pagination()
        period_month = request.args.get("period_month")
        items = [
            r for r in DB["rent_roll_periods"].values() if r["property_id"] == prop_id
        ]
        if period_month is not None:
            items = [r for r in items if r["period_month"] == period_month]
        items.sort(key=lambda r: r["created_at"])
        page, total = paginate(items, limit, offset)
        return ok_list([rent_roll_view(r) for r in page], total, limit, offset)
