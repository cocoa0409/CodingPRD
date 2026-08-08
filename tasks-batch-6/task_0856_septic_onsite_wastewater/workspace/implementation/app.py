"""Septic & On-Site Wastewater Permit API -- application entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError

from routes.parcels import bp as parcels_bp
from routes.contractors import bp as contractors_bp
from routes.wells import bp as wells_bp
from routes.site_evaluations import bp as site_evaluations_bp
from routes.system_designs import bp as system_designs_bp
from routes.construction_permits import bp as construction_permits_bp
from routes.inspections import bp as inspections_bp
from routes.operating_permits import bp as operating_permits_bp
from routes.pumping_records import bp as pumping_records_bp
from routes.repair_orders import bp as repair_orders_bp
from routes.transfer_inspections import bp as transfer_inspections_bp
from routes.misc import bp as misc_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (parcels_bp, contractors_bp, wells_bp, site_evaluations_bp,
                      system_designs_bp, construction_permits_bp, inspections_bp,
                      operating_permits_bp, pumping_records_bp, repair_orders_bp,
                      transfer_inspections_bp, misc_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error("ERR_INVALID_REQUEST", "Unknown route.", 404)
        if exc.code == 405:
            return response.error("ERR_INVALID_REQUEST",
                                  "Method not allowed for this route.", 405)
        return response.error("ERR_INVALID_REQUEST",
                              exc.description or "Malformed request.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return response.error("ERR_INVALID_REQUEST", str(exc), 500)

    @app.after_request
    def close_connection(resp):
        # Avoid werkzeug keep-alive RemoteDisconnected flakiness under the
        # per-test-server harness, which reboots the server before every test.
        resp.headers["Connection"] = "close"
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
