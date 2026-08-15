"""Entry point: Flask app, error handlers, route registration."""

import os
from flask import Flask
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes.ops import bp as ops_bp
    from routes.sites import bp as sites_bp
    from routes.members import bp as members_bp
    from routes.volunteers import bp as volunteers_bp
    from routes.varieties import bp as varieties_bp
    from routes.lots import bp as lots_bp
    from routes.packets import bp as packets_bp
    from routes.checkouts import bp as checkouts_bp
    from routes.swap_events import bp as swap_events_bp
    from routes.intake_items import bp as intake_items_bp
    from routes.packing import bp as packing_bp

    for bp in (ops_bp, sites_bp, members_bp, volunteers_bp, varieties_bp,
               lots_bp, packets_bp, checkouts_bp, swap_events_bp,
               intake_items_bp, packing_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, 404, "Route not found.")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, 404, "Route not found.")

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_INVALID_REQUEST, 400, "Malformed request.")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # never leak a stack trace through the envelope contract
        return error_response("ERR_INTERNAL", 500, f"Internal error: {err}")

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
