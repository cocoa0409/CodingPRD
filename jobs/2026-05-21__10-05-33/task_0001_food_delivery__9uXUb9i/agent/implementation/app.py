"""Flask application factory & entrypoint."""
from __future__ import annotations

import os
from flask import Flask, g, request

from errors import ApiError
from envelope import error as err_response
from store import gen_request_id, iso_z, now


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.before_request
    def _attach_request_meta():  # noqa: D401
        g.request_id = gen_request_id()
        g.request_ts = iso_z(now())

    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        return err_response(exc.error_id, exc.message, exc.status)

    @app.errorhandler(404)
    def _handle_404(_):
        return err_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def _handle_405(_):
        return err_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(400)
    def _handle_bad_request(_):
        # Flask raises 400 for malformed JSON before our handlers see it.
        return err_response("ERR_VALIDATION", "Malformed request body.", 422)

    # Register blueprints
    from routes_restaurants import bp as restaurants_bp
    from routes_menu_items import bp as menu_items_bp
    from routes_customers import bp as customers_bp
    from routes_riders import bp as riders_bp
    from routes_orders import bp as orders_bp
    from routes_assignments import bp as assignments_bp
    from routes_returns import bp as returns_bp
    from routes_fines import bp as fines_bp
    from routes_work_orders import bp as work_orders_bp
    from routes_clock import bp as clock_bp

    for bp in (
        restaurants_bp,
        menu_items_bp,
        customers_bp,
        riders_bp,
        orders_bp,
        assignments_bp,
        returns_bp,
        fines_bp,
        work_orders_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", "10000"))
    # Use a single-threaded WSGI server. Werkzeug's dev server is sufficient
    # for this task; we serialize state mutations behind store._lock anyway.
    from werkzeug.serving import make_server

    server = make_server("0.0.0.0", port, app, threaded=True)
    print(f"[server] listening on 0.0.0.0:{port}", flush=True)
    server.serve_forever()
