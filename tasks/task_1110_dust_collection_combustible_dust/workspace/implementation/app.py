"""Flask application entry point for the Dust Compliance API."""
import os

from flask import Flask, jsonify

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes import (
        sites,
        dust_samples,
        collectors,
        dhas,
        housekeeping,
        hot_work,
        inspections,
        retrofit,
        incidents,
    )

    app.register_blueprint(sites.bp)
    app.register_blueprint(dust_samples.bp)
    app.register_blueprint(collectors.bp)
    app.register_blueprint(dhas.bp)
    app.register_blueprint(housekeeping.bp)
    app.register_blueprint(hot_work.bp)
    app.register_blueprint(inspections.bp)
    app.register_blueprint(retrofit.bp)
    app.register_blueprint(incidents.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_INVALID_REQUEST, "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_generic(err):
        # Let ApiError pass through via its own handler
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
