"""Operating expense endpoints."""
from flask import request

from db import DB, new_id, now_dt, now_iso
from errors import ApiError
from middleware import auth, READ_ROLES
from response import ok, ok_list
from util import (
    get_property,
    json_body,
    opex_view,
    paginate,
    parse_bool_field,
    parse_enum_field,
    parse_int_field,
    parse_pagination,
    touch,
)

CATEGORIES = [
    "TAXES",
    "INSURANCE",
    "UTILITIES",
    "REPAIRS",
    "MANAGEMENT",
    "PAYROLL",
    "MARKETING",
    "OTHER",
]


def register(app):
    @app.post("/re-underwriting/properties/<prop_id>/operating-expenses")
    def create_opex(prop_id):
        _user_id, _role = auth(allowed=["Analyst"])
        prop = get_property(prop_id)
        body = json_body()
        period_year = parse_int_field(body, "period_year")
        category = parse_enum_field(body, "category", CATEGORIES)
        amount_cents = parse_int_field(body, "amount_cents")
        if amount_cents < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "amount_cents must be >= 0")
        is_recoverable = parse_bool_field(body, "is_recoverable", default=False)

        # duplicate (property_id, period_year, category)
        for o in DB["operating_expenses"].values():
            if (
                o["property_id"] == prop_id
                and o["period_year"] == period_year
                and o["category"] == category
            ):
                raise ApiError(
                    "ERR_DUPLICATE_PERIOD",
                    409,
                    "OperatingExpense already exists for this property, year, and category",
                )

        # future year check against logical clock
        current_year = now_dt().year
        if period_year > current_year:
            raise ApiError(
                "ERR_FUTURE_PERIOD",
                422,
                "period_year is in the future relative to the server's logical clock",
            )

        rec = {
            "id": new_id(),
            "property_id": prop_id,
            "period_year": period_year,
            "category": category,
            "amount_cents": amount_cents,
            "is_recoverable": is_recoverable,
            "created_at": now_iso(),
        }
        DB["operating_expenses"][rec["id"]] = rec
        touch(prop)
        return ok(opex_view(rec), status=201)

    @app.get("/re-underwriting/properties/<prop_id>/operating-expenses")
    def list_opex(prop_id):
        auth(allowed=READ_ROLES)
        get_property(prop_id)
        limit, offset = parse_pagination()
        period_year = request.args.get("period_year")
        category = request.args.get("category")
        items = [
            o for o in DB["operating_expenses"].values() if o["property_id"] == prop_id
        ]
        if period_year is not None:
            try:
                py = int(period_year)
            except ValueError:
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "period_year must be an integer"
                )
            items = [o for o in items if o["period_year"] == py]
        if category is not None:
            items = [o for o in items if o["category"] == category]
        items.sort(key=lambda o: o["created_at"])
        page, total = paginate(items, limit, offset)
        return ok_list([opex_view(o) for o in page], total, limit, offset)
