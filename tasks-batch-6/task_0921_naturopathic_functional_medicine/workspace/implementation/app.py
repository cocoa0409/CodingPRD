"""Naturopathic & Functional-Medicine Practice API.

In-memory only. The store is empty on every boot: no entity is seeded,
preloaded, registered or hardcoded at startup.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

from envelope import error_response  # noqa: E402
from errors import ApiError  # noqa: E402
from routes.dispensary import bp as dispensary_bp  # noqa: E402
from routes.encounters import bp as encounters_bp  # noqa: E402
from routes.lab_orders import bp as lab_orders_bp  # noqa: E402
from routes.memberships import bp as memberships_bp  # noqa: E402
from routes.patients import bp as patients_bp  # noqa: E402
from routes.practitioners import bp as practitioners_bp  # noqa: E402
from routes.protocol_items import bp as protocol_items_bp  # noqa: E402
from routes.protocols import bp as protocols_bp  # noqa: E402
from routes.referrals import bp as referrals_bp  # noqa: E402
from routes.superbills import bp as superbills_bp  # noqa: E402
from routes.system import bp as system_bp  # noqa: E402
from routes.threads import bp as threads_bp  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in (
        system_bp,
        practitioners_bp,
        patients_bp,
        memberships_bp,
        lab_orders_bp,
        protocols_bp,
        protocol_items_bp,
        dispensary_bp,
        encounters_bp,
        threads_bp,
        superbills_bp,
        referrals_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_response(
            "ERR_RESOURCE_NOT_FOUND", "Resource not found.", 404
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_response(
            "ERR_RESOURCE_NOT_FOUND", "Resource not found.", 404
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            status = exc.code or 400
            error_id = "ERR_RESOURCE_NOT_FOUND" if status in (404, 405) else "ERR_VALIDATION"
            return error_response(error_id, exc.description, 404 if status == 405 else status)
        return error_response("ERR_VALIDATION", str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
