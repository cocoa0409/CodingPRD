"""SurveyVendor endpoints."""
from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import mint_common_fields, serialize, sorted_rows
from util import as_positive_int, as_str, body, pagination_args, required


def register(app):
    @app.route("/api/survey-vendors", methods=["POST"])
    def create_vendor():
        auth(["SurveyCoordinator"])
        data = body()
        name = as_str(required(data, "name"), "name")
        max_concurrent_waves = as_positive_int(
            required(data, "max_concurrent_waves"), "max_concurrent_waves"
        )
        for v in DB["survey_vendors"].values():
            if v["name"] == name:
                raise ApiError(
                    "ERR_INVALID_REQUEST", 409, "Survey vendor name must be unique"
                )
        vendor = {"name": name, "max_concurrent_waves": max_concurrent_waves}
        mint_common_fields(vendor)
        DB["survey_vendors"][vendor["id"]] = vendor
        return ok(serialize(vendor), 201)

    @app.route("/api/survey-vendors", methods=["GET"])
    def list_vendors():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        rows = sorted_rows(DB["survey_vendors"].values())
        total = len(rows)
        page = rows[offset : offset + limit]
        return ok_list([serialize(r) for r in page], total, limit, offset)
