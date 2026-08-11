"""Plant Turnaround API — Flask entry point.

In-memory store, deterministic logical clock, standard response envelope.
Boots cleanly from a fresh process on every invocation; no state is seeded
or persisted.
"""
import os

from flask import Flask

from errors import ApiError
from response import err as err_response
from routes import (assignments, clock_routes, contractors, discoveries,
                    isolations, laydown, permits, punch, reports, shifts,
                    turnarounds, workers, work_items)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for module in (turnarounds, work_items, contractors, workers, shifts,
                   assignments, isolations, permits, discoveries, laydown,
                   reports, punch, clock_routes):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_not_found(e):
        return err_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return err_response("ERR_NOT_FOUND", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_internal(e):
        return err_response("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
