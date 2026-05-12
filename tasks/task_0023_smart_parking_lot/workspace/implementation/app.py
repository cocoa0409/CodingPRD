"""Smart Parking Lot API — Flask entrypoint."""
import os
import logging

from flask import Flask, jsonify

from errors import APIError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    # Strict path matching: don't auto-redirect trailing-slash variations.
    app.url_map.strict_slashes = False

    # Register blueprints
    from routes.lots import bp as lots_bp
    from routes.vehicles import bp as vehicles_bp
    from routes.cards import bp as cards_bp
    from routes.reservations import bp as reservations_bp
    from routes.sessions import bp as sessions_bp
    from routes.violations import bp as violations_bp
    from routes.payments import bp as payments_bp
    from routes.audit import bp as audit_bp
    from routes.system import bp as system_bp

    for bp in (lots_bp, vehicles_bp, cards_bp, reservations_bp, sessions_bp,
               violations_bp, payments_bp, audit_bp, system_bp):
        app.register_blueprint(bp)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Route or resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_BAD_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_exc(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        # Last-resort handler — log and return generic bad request
        logging.exception("unhandled exception")
        return error_response("ERR_BAD_REQUEST", str(e) or "Internal error", 400)

    @app.route("/healthz", methods=["GET"])
    def healthz():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
