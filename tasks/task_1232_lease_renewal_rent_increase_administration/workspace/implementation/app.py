"""Flask entrypoint — registers all blueprints and the global error handler."""

import os
from flask import Flask, jsonify

from errors import ApiError
from response import error_response
from routes import clock, policies, properties, units, residents, leases, offers, concessions, notices, documents


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock.bp)
    app.register_blueprint(policies.bp)
    app.register_blueprint(properties.bp)
    app.register_blueprint(units.bp)
    app.register_blueprint(residents.bp)
    app.register_blueprint(leases.bp)
    app.register_blueprint(offers.bp)
    app.register_blueprint(concessions.bp)
    app.register_blueprint(notices.bp)
    app.register_blueprint(documents.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "route not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        import traceback
        traceback.print_exc()
        return error_response("ERR_INTERNAL", 500, str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
