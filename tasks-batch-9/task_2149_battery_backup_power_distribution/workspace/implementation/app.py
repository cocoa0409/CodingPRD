"""Battery Backup Distribution API — entry point."""
import os
import sys
import traceback

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from common import ApiError, err_body
import routes_ref
import routes_inv
import routes_order
import routes_ship
import routes_core
import routes_warranty
import routes_contract
import routes_storm
import routes_manifest


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    for module in (routes_ref, routes_inv, routes_order, routes_ship, routes_core,
                   routes_warranty, routes_contract, routes_storm, routes_manifest):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(err_body(exc.error_id, exc.message)), exc.status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        return jsonify(err_body("ERR_INVALID_REQUEST", exc.description or "invalid request")), exc.code

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        traceback.print_exc(file=sys.stderr)
        return jsonify(err_body("ERR_INVALID_REQUEST", "unexpected server error: %s" % exc)), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
