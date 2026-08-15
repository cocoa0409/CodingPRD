"""Entry point: Flask app, error handlers, route registration.

Infection Prevention & Healthcare-Associated Infection Surveillance API.
Storage is in-memory only; the store starts empty on every boot.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.errorhandler(ApiError)
    def _api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _not_found(err):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def _unhandled(err):
        # Surface as a clean 500 rather than an HTML error page.
        import traceback
        traceback.print_exc()
        return error_response("ERR_INTERNAL", str(err), 500)

    from routes.admin import bp as admin_bp
    from routes.census import bp as census_bp
    from routes.devices_procedures import bp as devices_bp
    from routes.cases import bp as cases_bp
    from routes.denominators import bp as denominators_bp
    from routes.outbreak import bp as outbreak_bp
    from routes.isolation import bp as isolation_bp
    from routes.hygiene import bp as hygiene_bp
    from routes.exposures import bp as exposures_bp
    from routes.caps import bp as caps_bp

    for bp in (
        admin_bp,
        census_bp,
        devices_bp,
        cases_bp,
        denominators_bp,
        outbreak_bp,
        isolation_bp,
        hygiene_bp,
        exposures_bp,
        caps_bp,
    ):
        app.register_blueprint(bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
