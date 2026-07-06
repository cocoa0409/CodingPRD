"""Faith Congregation Church Management API — Flask entry point."""

import os
import logging
from flask import Flask

from errors import ApiError
from common import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    # Route registration — import each module and register its blueprint.
    from routes.household import bp as household_bp
    from routes.member import bp as member_bp
    from routes.pledge_campaign import bp as pc_bp
    from routes.pledge import bp as pledge_bp
    from routes.donation import bp as donation_bp
    from routes.year_end_statement import bp as yes_bp
    from routes.facility import bp as facility_bp
    from routes.facility_booking import bp as fb_bp
    from routes.event import bp as event_bp
    from routes.volunteer_assignment import bp as va_bp
    from routes.small_group import bp as sg_bp
    from routes.group_membership import bp as gm_bp
    from routes.child_checkin import bp as cc_bp
    from routes.admin import bp as admin_bp

    for bp in [
        household_bp, member_bp, pc_bp, pledge_bp, donation_bp, yes_bp,
        facility_bp, fb_bp, event_bp, va_bp, sg_bp, gm_bp, cc_bp, admin_bp,
    ]:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(_e):
        return error_response("ERR_NOT_FOUND", 404, "Route not found")

    @app.errorhandler(405)
    def handle_405(_e):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(400)
    def handle_400(_e):
        return error_response("ERR_INVALID_REQUEST", 400, "Bad request")

    @app.errorhandler(Exception)
    def handle_500(e):
        # Fallback — should not happen once validation is complete.
        return error_response("ERR_INVALID_REQUEST", 400, f"Unhandled: {e!r}")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
