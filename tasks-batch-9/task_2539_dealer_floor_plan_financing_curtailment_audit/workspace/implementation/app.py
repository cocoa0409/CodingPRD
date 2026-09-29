"""Dealer Floorplan Curtailment Audit API -- application entry point.

The in-memory store starts completely empty on every boot: no entity is seeded,
preloaded or hardcoded anywhere.  Every dealership, line, unit, advance,
obligation, audit, incident, remittance, covenant test and remedy comes into
existence through the declared API surface.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (
    advances,
    audits,
    clock,
    credit_lines,
    dealers,
    obligations,
    remedies,
    remittances,
    units,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover -- older Flask
        app.config["JSON_SORT_KEYS"] = False

    for module in (
        clock,
        dealers,
        credit_lines,
        units,
        advances,
        obligations,
        audits,
        remittances,
        remedies,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        body = response.error_body("ERR_INVALID_REQUEST", err.description or err.name)
        return jsonify(body), err.code

    @app.errorhandler(Exception)
    def handle_unexpected(err):  # pragma: no cover -- safety net
        body = response.error_body("ERR_INVALID_REQUEST", "Unhandled server error: %s" % err)
        return jsonify(body), 500

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
