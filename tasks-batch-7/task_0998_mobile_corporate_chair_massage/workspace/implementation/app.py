"""Mobile Corporate Chair Massage API — Flask entry point."""
import os

from flask import Flask, jsonify

import auth
import errors
import respond
from errors import ApiError
from routes import (bookings, chair_slots, clock_routes, corporate_accounts,
                    invoices, licenses, misc, regions, slot_claims,
                    therapists, wellness_programs)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _auth_gate():
        return auth.gate_request()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(respond.error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def _not_found(exc):
        return jsonify(respond.error_body(
            errors.ERR_NOT_FOUND, "Path id references a non-existent entity")), 404

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return jsonify(respond.error_body(
            errors.ERR_NOT_FOUND, "Path id references a non-existent entity")), 404

    @app.errorhandler(400)
    def _bad_request(exc):
        if isinstance(exc, ApiError):
            return jsonify(respond.error_body(exc.error_id, exc.message)), exc.http_status
        return jsonify(respond.error_body(
            errors.ERR_INVALID_REQUEST, "Malformed request")), 400

    @app.errorhandler(Exception)
    def _internal(exc):
        return jsonify(respond.error_body(
            errors.ERR_INVALID_REQUEST, f"Internal error: {exc}")), 500

    for module in (clock_routes, regions, corporate_accounts, wellness_programs,
                   therapists, licenses, bookings, chair_slots, slot_claims,
                   misc, invoices):
        app.register_blueprint(module.bp)

    @app.get("/")
    def health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
