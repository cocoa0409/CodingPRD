"""Municipal Stormwater Permit Program API.

In-memory only: every collection lives in a Python dict keyed by id and dies
with the process. Nothing is seeded at startup.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import (
    accounts,
    annual_reports,
    cases,
    clock,
    construction_sites,
    control_measures,
    credit_applications,
    enforcement_actions,
    facilities,
    inspections,
    observations,
    outfalls,
    permit_terms,
)

API_PREFIX = "/stormwater"

BLUEPRINTS = (
    permit_terms.bp,
    control_measures.bp,
    outfalls.bp,
    observations.bp,
    cases.bp,
    construction_sites.bp,
    facilities.bp,
    inspections.bp,
    enforcement_actions.bp,
    accounts.bp,
    credit_applications.bp,
    annual_reports.bp,
)

HTTP_ERROR_IDS = {
    400: "ERR_VALIDATION",
    404: "ERR_NOT_FOUND",
    405: "ERR_METHOD_NOT_ALLOWED",
    415: "ERR_VALIDATION",
}


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)
    app.register_blueprint(clock.bp)

    @app.before_request
    def _prepare():
        g.touched_rows = set()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        error_id = HTTP_ERROR_IDS.get(exc.code, "ERR_VALIDATION")
        status = exc.code if exc.code else 400
        return error_response(error_id, exc.description or "Request could not be served.", status)

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INTERNAL", str(exc) or "Internal error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
