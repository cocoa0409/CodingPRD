"""Farm Stand & U-Pick Operation API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding). The harness
re-launches start.sh before every test, so module-level dicts in db.py are the
entire database.
"""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from helpers import error_body, ok_object
from routes import (
    addons,
    crops,
    fields,
    harvest_lines,
    misc,
    offline_batches,
    payments,
    policies,
    sales_days,
    seasons,
    sessions,
    waivers,
    windows,
)


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    for module in (
        seasons,
        crops,
        fields,
        windows,
        policies,
        waivers,
        sessions,
        harvest_lines,
        addons,
        payments,
        sales_days,
        offline_batches,
        misc,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_body(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_body(ApiError(ERR_NOT_FOUND[0], "Resource not found", 404))

    @app.errorhandler(405)
    def handle_405(err):
        return error_body(ApiError(ERR_NOT_FOUND[0], "Resource not found", 404))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_body(ApiError("ERR_INTERNAL", "Internal server error", 500))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
