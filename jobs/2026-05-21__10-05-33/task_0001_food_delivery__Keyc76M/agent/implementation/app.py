"""Flask application entry point.

Routes are organized into resource-specific modules under routes/. This
file wires them together, configures error handlers for 404/405/500, and
starts the server on PORT (default 10000) bound to 0.0.0.0.
"""

import os

from flask import Flask, jsonify, request

import envelope


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Lazily import to keep module-load ordering predictable
    from routes import (
        restaurants as routes_restaurants,
        menu_items as routes_menu_items,
        customers as routes_customers,
        riders as routes_riders,
        orders as routes_orders,
        assignments as routes_assignments,
        returns_ as routes_returns,
        fines as routes_fines,
        work_orders as routes_work_orders,
        clock as routes_clock,
    )

    for bp in (
        routes_restaurants.bp,
        routes_menu_items.bp,
        routes_customers.bp,
        routes_riders.bp,
        routes_orders.bp,
        routes_assignments.bp,
        routes_returns.bp,
        routes_fines.bp,
        routes_work_orders.bp,
        routes_clock.bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(404)
    def _404(_):
        return envelope.not_found("Path does not exist.")

    @app.errorhandler(405)
    def _405(_):
        return envelope.error(404, "ERR_NOT_FOUND", "Method not allowed for this path.")

    @app.errorhandler(400)
    def _400(_):
        return envelope.validation("Malformed JSON body.")

    @app.errorhandler(500)
    def _500(e):
        # Surface as ERR_VALIDATION to satisfy the "no opaque 500s" implicit goal.
        return envelope.error(500, "ERR_INTERNAL", "Unexpected server error.")

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app = create_app()
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
