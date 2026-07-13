import os

from flask import Flask, jsonify

from core import ApiError, respond_error, _make_meta

import routes_establishments
import routes_inspectors
import routes_devices
import routes_inspections
import routes_complaints
import routes_seals
import routes_condemnations
import routes_penalties
import routes_fee_invoices
import routes_clock


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    for mod in (
        routes_establishments,
        routes_inspectors,
        routes_devices,
        routes_inspections,
        routes_complaints,
        routes_seals,
        routes_condemnations,
        routes_penalties,
        routes_fee_invoices,
        routes_clock,
    ):
        mod.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return respond_error(err)

    @app.errorhandler(404)
    def handle_404(_e):
        return respond_error(ApiError("ERR_NOT_FOUND", "Resource not found"))

    @app.errorhandler(405)
    def handle_405(_e):
        return respond_error(ApiError("ERR_NOT_FOUND", "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_uncaught(err):
        if isinstance(err, ApiError):
            return respond_error(err)
        body = {
            "meta": _make_meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
        }
        return jsonify(body), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
