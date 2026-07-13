from core import (store, authorize, get_body, require_fields, respond_object,
                  parse_iso)


def register(app):

    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        authorize(["ProgramAdmin"])
        body = get_body(optional=False)
        require_fields(body, ["to_iso8601"])
        store.clock = parse_iso(body["to_iso8601"])
        return respond_object({}, 200)
