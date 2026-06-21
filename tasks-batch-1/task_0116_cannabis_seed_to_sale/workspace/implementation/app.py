"""Cannabis Seed-to-Sale Compliance API entry point.

In-memory storage only; no seeding at startup. The test harness relaunches this
process before every test, so every dict in db.py starts empty on each boot."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.licenses import bp as licenses_bp
from routes.plant_batches import bp as plant_batches_bp
from routes.harvests import bp as harvests_bp
from routes.packages import bp as packages_bp
from routes.lab_results import bp as lab_results_bp
from routes.manifests import bp as manifests_bp
from routes.customers import bp as customers_bp
from routes.sales import bp as sales_bp
from routes.reconciliation_counts import bp as reconciliation_counts_bp
from routes.waste_events import bp as waste_events_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(licenses_bp)
    app.register_blueprint(plant_batches_bp)
    app.register_blueprint(harvests_bp)
    app.register_blueprint(packages_bp)
    app.register_blueprint(lab_results_bp)
    app.register_blueprint(manifests_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(reconciliation_counts_bp)
    app.register_blueprint(waste_events_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Bad request.", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Map any other HTTP error into the standard envelope.
        code = e.code or 500
        if code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if code == 400:
            return error_response("ERR_INVALID_REQUEST", "Bad request.", 400)
        return error_response("ERR_INVALID_REQUEST", e.description or "Error", code)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % str(e), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
