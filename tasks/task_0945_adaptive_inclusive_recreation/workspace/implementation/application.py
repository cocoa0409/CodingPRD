"""Flask application factory.

The store starts empty on every boot: nothing here seeds, preloads, registers
or hardcodes any entity row.
"""

from flask import Flask

from envelope import error_response
from errors import ApiError
from store import begin_request


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.admin import bp as admin_bp
    from routes.intake import bp as intake_bp
    from routes.enrollments import bp as enrollments_bp
    from routes.staffing import bp as staffing_bp
    from routes.equipment import bp as equipment_bp
    from routes.transport import bp as transport_bp
    from routes.funding import bp as funding_bp
    from routes.goals import bp as goals_bp

    for blueprint in (
        admin_bp,
        intake_bp,
        enrollments_bp,
        staffing_bp,
        equipment_bp,
        transport_bp,
        funding_bp,
        goals_bp,
    ):
        app.register_blueprint(blueprint)

    @app.before_request
    def _begin():
        begin_request()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error_response("ERR_VALIDATION", "Unknown route.", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return error_response("ERR_VALIDATION", "Method not allowed.", 405)

    return app
