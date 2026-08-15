"""Magazine Publishing & Subscription Fulfillment API — entry point.

In-memory Flask server. The process is re-launched via start.sh before every
test, so all state lives in module-level dicts and starts empty on each boot.
"""

import os

from flask import Flask

from errors import ApiError
from util import error_body, make_meta
from flask import jsonify

import routes_pub
import routes_subs
import routes_mail
import routes_orders
import routes_audits


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_pub.bp)
    app.register_blueprint(routes_subs.bp)
    app.register_blueprint(routes_mail.bp)
    app.register_blueprint(routes_orders.bp)
    app.register_blueprint(routes_audits.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_body(e)

    @app.errorhandler(404)
    def handle_not_found(e):
        body = {
            "meta": make_meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST",
                "message": "The requested resource does not exist",
            },
        }
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        body = {
            "meta": make_meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST",
                "message": "Method not allowed",
            },
        }
        return jsonify(body), 405

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_body(e)
        body = {
            "meta": make_meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST",
                "message": f"Unexpected error: {e}",
            },
        }
        return jsonify(body), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
