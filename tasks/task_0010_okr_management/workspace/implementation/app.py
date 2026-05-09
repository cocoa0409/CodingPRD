"""Application entry point."""

import os
from flask import Flask, g, request

import db
from auth import authenticate
from envelope import error_response, request_meta, gen_request_id
from errors import ApiError
from clock import now, format_ts


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    @app.before_request
    def before():
        g.api_request_id = gen_request_id()
        g.api_request_timestamp = format_ts(now())
        # Auth-exempt routes: none — all endpoints require auth headers.
        # Skip auth for health-style endpoints (none defined). Run auth.
        if request.method == "OPTIONS":
            return
        try:
            authenticate()
        except ApiError as e:
            return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(ApiError)
    def handle_api_error(e: ApiError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Path not matching any route
        return error_response("ERR_INVALID_REQUEST", "endpoint not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_INVALID_REQUEST", "method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Don't suppress ApiError — that has its own handler above
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        # Fallback
        return error_response("ERR_INVALID_REQUEST", f"internal error: {e!s}", 500)

    # Register blueprints
    from routes.departments import bp as bp_dept
    from routes.users import bp as bp_users
    from routes.cycles import bp as bp_cycles
    from routes.objectives import bp as bp_obj
    from routes.key_results import bp as bp_kr
    from routes.alignment import bp as bp_align
    from routes.co_owners import bp as bp_co
    from routes.reviews import bp as bp_rev
    from routes.access_grants import bp as bp_grant
    from routes.external_events import bp as bp_ev
    from routes.audit_logs import bp as bp_audit
    from routes.admin import bp as bp_admin

    for bp in (bp_dept, bp_users, bp_cycles, bp_obj, bp_kr, bp_align,
               bp_co, bp_rev, bp_grant, bp_ev, bp_audit, bp_admin):
        app.register_blueprint(bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
