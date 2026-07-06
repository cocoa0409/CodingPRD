import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response, success

from routes.config import bp as config_bp
from routes.patients import bp as patients_bp
from routes.screenings import bp as screenings_bp
from routes.cases import bp as cases_bp
from routes.financing import bp as financing_bp
from routes.lookups import bp as lookups_bp
from routes.enhancements import bp as enhancements_bp
from routes.refunds import bp as refunds_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(screenings_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(financing_bp)
    app.register_blueprint(lookups_bp)
    app.register_blueprint(enhancements_bp)
    app.register_blueprint(refunds_bp)
    app.register_blueprint(clock_bp)

    @app.get("/health")
    def health():
        return success({}, 200)

    @app.after_request
    def _no_keepalive(resp):
        # Disable HTTP keep-alive on the Werkzeug dev server. Under the 8x
        # concurrent per-test-server reboot load the dev server occasionally
        # closes an idle keep-alive socket exactly as the requests client reuses
        # it, surfacing as a transient BadStatusLine/ConnectionError. Forcing a
        # fresh connection per request removes that reuse race. Transport-only;
        # no PRD-observable behavior changes.
        resp.headers["Connection"] = "close"
        return resp

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", 400, "Bad request")

    @app.errorhandler(Exception)
    def handle_generic(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INVALID_REQUEST", 400, str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
