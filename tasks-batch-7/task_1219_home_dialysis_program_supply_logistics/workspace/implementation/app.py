"""Home Dialysis Supply Logistics API — Flask entry point.

In-memory only; the store starts empty on every boot. Logical clock default:
2026-05-01T00:00:00Z (never falls back to wall-clock time).
"""
import os

from flask import Flask, jsonify

import errors as errmod
from response import error as error_response

import routes_programs
import routes_machines
import routes_orders
import routes_clinical
import routes_slots_waste
import routes_transitions


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_programs.bp)
    app.register_blueprint(routes_machines.bp)
    app.register_blueprint(routes_orders.bp)
    app.register_blueprint(routes_clinical.bp)
    app.register_blueprint(routes_slots_waste.bp)
    app.register_blueprint(routes_transitions.bp)

    @app.errorhandler(errmod.ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(errmod.err_not_found())

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(errmod.err_not_found())

    @app.errorhandler(Exception)
    def handle_generic(e):
        if isinstance(e, errmod.ApiError):
            return error_response(e)
        return error_response(errmod.ApiError("ERR_INVALID_REQUEST", 400, str(e)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
