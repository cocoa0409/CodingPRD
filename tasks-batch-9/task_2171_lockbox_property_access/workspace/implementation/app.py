"""Lockbox Property Access API — entry point."""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response, _meta
import routes_association
import routes_member
import routes_contractor
import routes_lockbox
import routes_listing
import routes_placement
import routes_credential
import routes_grant
import routes_showing
import routes_event
import routes_review
import routes_billing


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (
        routes_association, routes_member, routes_contractor, routes_lockbox,
        routes_listing, routes_placement, routes_credential, routes_grant,
        routes_showing, routes_event, routes_review, routes_billing,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST",
                "message": err.description or "Request could not be processed.",
            },
        }
        return jsonify(body), err.code

    @app.errorhandler(Exception)
    def handle_unexpected(err):  # pragma: no cover - safety net
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST",
                "message": "Unexpected server error: %s" % err,
            },
        }
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
