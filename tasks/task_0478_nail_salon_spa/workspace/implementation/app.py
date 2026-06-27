"""Nail Salon & Spa Services API — Flask entry point.

In-memory only. The store starts EMPTY on every boot; no entity is seeded.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response

from routes.technicians import bp as technicians_bp
from routes.stations import bp as stations_bp
from routes.sanitation_logs import bp as sanitation_logs_bp
from routes.menu_items import bp as menu_items_bp
from routes.add_ons import bp as add_ons_bp
from routes.clients import bp as clients_bp
from routes.appointments import bp as appointments_bp
from routes.appointment_add_ons import bp as appointment_add_ons_bp
from routes.gift_cards import bp as gift_cards_bp
from routes.commission_statements import bp as commission_statements_bp
from routes.admin import bp as admin_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        technicians_bp, stations_bp, sanitation_logs_bp, menu_items_bp,
        add_ons_bp, clients_bp, appointments_bp, appointment_add_ons_bp,
        gift_cards_bp, commission_statements_bp, admin_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        resp = jsonify(error_response(e.error_id, e.message))
        resp.status_code = e.http_status
        return resp

    @app.errorhandler(404)
    def handle_404(e):
        resp = jsonify(error_response("ERR_NOT_FOUND", "Resource not found"))
        resp.status_code = 404
        return resp

    @app.errorhandler(405)
    def handle_405(e):
        # Method not allowed on a known path -> treat as not found per catalogue.
        resp = jsonify(error_response("ERR_NOT_FOUND", "Method not allowed"))
        resp.status_code = 404
        return resp

    @app.errorhandler(400)
    def handle_400(e):
        resp = jsonify(error_response("ERR_INVALID_REQUEST", "Malformed request"))
        resp.status_code = 400
        return resp

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return handle_api_error(e)
        resp = jsonify(error_response("ERR_INVALID_REQUEST", f"Unexpected error: {e}"))
        resp.status_code = 400
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
