from core import (store, authorize, get_body, require_string, respond_object,
                  base_common, serialize)


def register(app):

    @app.route("/inspectors", methods=["POST"])
    def create_inspector():
        authorize(["ProgramAdmin"])
        body = get_body(optional=False)
        full_name = require_string(body, "full_name")
        badge_number = require_string(body, "badge_number")
        region = body.get("region")
        if region is None or region == "":
            region = "UNASSIGNED"
        elif not isinstance(region, str):
            from core import ApiError
            raise ApiError("ERR_VALIDATION", "region must be a string")
        insp = base_common("Inspector")
        insp.update({
            "full_name": full_name,
            "badge_number": badge_number,
            "region": region,
        })
        store.inspectors[insp["id"]] = insp
        return respond_object(serialize(insp), 201)
