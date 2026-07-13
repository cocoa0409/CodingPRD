import os

from flask import Flask, jsonify

from util import ApiError, error_response
from routes.connections import bp as connections_bp
from routes.devices import bp as devices_bp
from routes.testers import bp as testers_bp
from routes.appointments import bp as appointments_bp
from routes.reports import bp as reports_bp
from routes.surveys import bp as surveys_bp
from routes.notices import bp as notices_bp
from routes.repairs import bp as repairs_bp
from routes.misc import bp as misc_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (connections_bp, devices_bp, testers_bp, appointments_bp,
               reports_bp, surveys_bp, notices_bp, repairs_bp, misc_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        body, status = error_response(err)
        return jsonify(body), status

    @app.errorhandler(404)
    def handle_404(err):
        body, status = error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))
        return jsonify(body), status

    @app.errorhandler(405)
    def handle_405(err):
        body, status = error_response(ApiError("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed"))
        return jsonify(body), status

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            body, status = error_response(err)
            return jsonify(body), status
        body, status = error_response(ApiError("ERR_INTERNAL", 500, str(err)))
        return jsonify(body), status

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
