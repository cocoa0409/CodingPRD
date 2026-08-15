"""Community Garden & Urban Farm Volunteer Program API — Flask entry point."""
import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.system import bp as system_bp
    from routes.volunteers import bp as volunteers_bp
    from routes.certifications import bp as certifications_bp
    from routes.seasons import bp as seasons_bp
    from routes.beds import bp as beds_bp
    from routes.crop_plans import bp as crop_plans_bp
    from routes.slots import bp as slots_bp
    from routes.signups import bp as signups_bp
    from routes.bookings import bp as bookings_bp
    from routes.keys import bp as keys_bp
    from routes.tools import bp as tools_bp
    from routes.checkouts import bp as checkouts_bp
    from routes.harvests import bp as harvests_bp
    from routes.recipients import bp as recipients_bp
    from routes.allocations import bp as allocations_bp
    from routes.irrigation import bp as irrigation_bp

    for bp in (
        system_bp, volunteers_bp, certifications_bp, seasons_bp, beds_bp,
        crop_plans_bp, slots_bp, signups_bp, bookings_bp, keys_bp, tools_bp,
        checkouts_bp, harvests_bp, recipients_bp, allocations_bp, irrigation_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_not_found(_):
        return error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(_):
        return error_response("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        return error_response("ERR_INTERNAL", 500, str(exc))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
