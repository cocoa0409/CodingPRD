"""Cash Assistance & Work Participation API.

Flask application factory and entry point.  All state lives in process memory
(see store.py) and is empty on every boot: nothing is seeded.
"""

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError  # noqa: E402
from respond import error_response  # noqa: E402
from routes.applications import bp as applications_bp  # noqa: E402
from routes.cases import bp as cases_bp  # noqa: E402
from routes.clock import bp as clock_bp  # noqa: E402
from routes.compliance import bp as compliance_bp  # noqa: E402
from routes.households import bp as households_bp  # noqa: E402
from routes.overpayments import bp as overpayments_bp  # noqa: E402
from routes.reporting import bp as reporting_bp  # noqa: E402
from routes.supportive import bp as supportive_bp  # noqa: E402
from routes.work import bp as work_bp  # noqa: E402

BLUEPRINTS = (households_bp, applications_bp, cases_bp, work_bp, compliance_bp,
              supportive_bp, overpayments_bp, reporting_bp, clock_bp)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(error):
        body = error_response(error.error_id, error.message)
        return body, error.http_status

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return error_response("ERR_NOT_FOUND", "No such resource."), 404
        if error.code == 405:
            return error_response("ERR_INVALID_REQUEST",
                                  "The method is not allowed for this path."), 405
        if error.code in (400, 415):
            return error_response("ERR_INVALID_REQUEST",
                                  "The request could not be parsed."), 400
        return error_response("ERR_INVALID_REQUEST",
                              error.description or "Request failed"), error.code

    @app.errorhandler(Exception)
    def _unexpected(error):
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error."), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True,
            use_reloader=False)
