"""Flask entry point: registers blueprints and the error handler."""
import os

from flask import Flask

import envelope as E
from errors import ApiError
from routes_ref import bp as ref_bp
from routes_inq import bp as inq_bp
from routes_match import bp as match_bp
from routes_place import bp as place_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(ref_bp)
    app.register_blueprint(inq_bp)
    app.register_blueprint(match_bp)
    app.register_blueprint(place_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return E.error(err.error_id, err.http_status, err.message)

    @app.after_request
    def _no_keepalive(resp):
        # Avoid werkzeug keep-alive RemoteDisconnected flakiness under the
        # per-test-server harness, which reboots the server between tests.
        resp.headers["Connection"] = "close"
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
