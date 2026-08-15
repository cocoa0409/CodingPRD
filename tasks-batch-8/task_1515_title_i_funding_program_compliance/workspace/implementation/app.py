"""Title I Program Compliance API — Flask entry point.

In-memory only; the store starts empty on every boot. The evaluator contract is
`bash start.sh`: the server listens on $PORT (default 10000), binds 0.0.0.0,
and runs in the foreground.
"""

import os

from flask import Flask

import errors
import response
from routes import (
    allocations,
    amendments,
    clock,
    consultations,
    expenditures,
    grants,
    monitoring,
    schools,
    set_asides,
    snapshots,
    sns,
)

API_PREFIX = "/title-i"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (
        grants, schools, snapshots, allocations, set_asides, sns,
        consultations, expenditures, amendments, monitoring, clock,
    ):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return response.error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return response.error_response(errors.ERR_NOT_FOUND, 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return response.error_response(errors.ERR_NOT_FOUND, 404, "Resource not found.")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return response.error_response(
            errors.ERR_INVALID_REQUEST, 400, "Unexpected error: %s" % err
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
