"""Open Source License Compliance API — Flask entry point."""

import os
import traceback

from flask import Flask

from errors import ApiError, err, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND
from response import error_resp

from routes.products import bp as products_bp
from routes.components import bp as components_bp
from routes.scans import bp as scans_bp
from routes.boms import bp as boms_bp
from routes.approvals import bp as approvals_bp
from routes.tickets import bp as tickets_bp
from routes.vulnerabilities import bp as vulns_bp
from routes.gates import bp as gates_bp
from routes.plans import bp as plans_bp
from routes.engagements import bp as engagements_bp
from routes.admin import bp as admin_bp
from routes.standalone import bp as standalone_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (products_bp, components_bp, scans_bp, boms_bp, approvals_bp,
               tickets_bp, vulns_bp, gates_bp, plans_bp, engagements_bp,
               admin_bp, standalone_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_resp(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_resp(ERR_RESOURCE_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_resp(ERR_INVALID_REQUEST, "Method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(e):
        return error_resp(ERR_INVALID_REQUEST, "General request format error", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        traceback.print_exc()
        return error_resp("ERR_SCAN_WORKER_ERROR", str(e), 500)

    return app


app = create_app()

if __name__ == "__main__":
    # threaded=True: the parallel stability sweep runs 8 suites in lockstep
    # against fresh server boots; the single-threaded Werkzeug server can
    # reset a reused keep-alive connection under that load. Thread-per-request
    # avoids the head-of-line race without changing any API behavior.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
