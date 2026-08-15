"""Hydrant Flow Testing & Flushing Program API — Flask entry point.

In-memory only: all state lives in module-level dicts inside db.store. Nothing
is seeded, preloaded, or hardcoded at startup; the store is empty on every
process boot. The harness re-launches start.sh before every test, so each test
sees a pristine store."""
import os

from flask import Flask

from errors import ApiError
from response import error_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.catalog import bp as catalog_bp
    from routes.clock import bp as clock_bp
    from routes.complaints import bp as complaints_bp
    from routes.flow_tests import bp as flow_tests_bp
    from routes.flush_sequences import bp as flush_sequences_bp
    from routes.hydrants import bp as hydrants_bp
    from routes.inspections import bp as inspections_bp
    from routes.iso_snapshots import bp as iso_snapshots_bp
    from routes.outages import bp as outages_bp
    from routes.programs import bp as programs_bp
    from routes.work_orders import bp as work_orders_bp

    for bp in (
        programs_bp,
        catalog_bp,
        hydrants_bp,
        inspections_bp,
        flow_tests_bp,
        flush_sequences_bp,
        complaints_bp,
        outages_bp,
        work_orders_bp,
        iso_snapshots_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_body(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_body("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_body("ERR_NOT_FOUND", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_body("ERR_INTERNAL", "Internal server error: %s" % err, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
