"""Property endpoints."""
from db import DB, new_id
from errors import ApiError
from middleware import auth, READ_ROLES
from response import ok, ok_list
from services import deal_properties
from util import (
    get_deal,
    get_property,
    init_common_fields,
    json_body,
    paginate,
    parse_enum_field,
    parse_int_field,
    parse_pagination,
    parse_str_field,
    property_view,
    touch,
)

PROPERTY_TYPES = ["MULTIFAMILY", "OFFICE", "RETAIL", "INDUSTRIAL", "MIXED_USE"]


def register(app):
    @app.post("/re-underwriting/deals/<deal_id>/properties")
    def create_property(deal_id):
        _user_id, _role = auth(allowed=["Analyst"])
        d = get_deal(deal_id)
        if d["status"] not in ("DRAFT", "UNDERWRITING"):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Properties may only be created while deal is DRAFT or UNDERWRITING",
            )
        body = json_body()
        address_line = parse_str_field(body, "address_line")
        market = parse_str_field(body, "market")
        property_type = parse_enum_field(body, "property_type", PROPERTY_TYPES)
        units = parse_int_field(body, "units")
        if units < 1:
            raise ApiError("ERR_INVALID_REQUEST", 400, "units must be >= 1")
        rentable_sqft = parse_int_field(body, "rentable_sqft")
        if rentable_sqft < 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "rentable_sqft must be >= 100")
        year_built = parse_int_field(body, "year_built")
        if not (1800 <= year_built <= 2100):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "year_built must be between 1800 and 2100"
            )

        rec = {
            "id": new_id(),
            "deal_id": deal_id,
            "address_line": address_line,
            "market": market,
            "property_type": property_type,
            "units": units,
            "rentable_sqft": rentable_sqft,
            "year_built": year_built,
            "occupancy_pct": None,
        }
        init_common_fields(rec)
        DB["properties"][rec["id"]] = rec
        touch(d)  # bump parent deal version
        return ok(property_view(rec), status=201)

    @app.get("/re-underwriting/deals/<deal_id>/properties")
    def list_properties(deal_id):
        auth(allowed=READ_ROLES)
        get_deal(deal_id)
        limit, offset = parse_pagination()
        items = sorted(deal_properties(deal_id), key=lambda p: p["created_at"])
        page, total = paginate(items, limit, offset)
        return ok_list([property_view(p) for p in page], total, limit, offset)

    @app.get("/re-underwriting/properties/<prop_id>")
    def get_property_route(prop_id):
        auth(allowed=READ_ROLES)
        p = get_property(prop_id)
        return ok(property_view(p))
