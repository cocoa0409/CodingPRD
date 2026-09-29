"""Health Information Exchange participation and record locator API."""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body

from routes.breakglass import bp as breakglass_bp
from routes.clock import bp as clock_bp
from routes.conformance import bp as conformance_bp
from routes.directives import bp as directives_bp
from routes.feeds import bp as feeds_bp
from routes.governance import bp as governance_bp
from routes.invoices import bp as invoices_bp
from routes.locator import bp as locator_bp
from routes.participants import bp as participants_bp
from routes.records import bp as records_bp
from routes.subscriptions import bp as subscriptions_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        participants_bp,
        conformance_bp,
        governance_bp,
        records_bp,
        directives_bp,
        locator_bp,
        breakglass_bp,
        feeds_bp,
        subscriptions_bp,
        invoices_bp,
        clock_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_not_found(exc):
        return jsonify(error_body("ERR_INVALID_REQUEST", "No such route.")), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return (
            jsonify(error_body("ERR_INVALID_REQUEST", "Method not allowed.")),
            405,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        import traceback

        traceback.print_exc()
        return (
            jsonify(error_body("ERR_INVALID_REQUEST", "Unhandled server error.")),
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
