import os
import time

from flask import Flask, jsonify

from errors import ApiError
from response import error_body

from routes.venues import bp as venues_bp
from routes.rooms import bp as rooms_bp
from routes.pricing_rules import bp as pricing_rules_bp
from routes.game_masters import bp as game_masters_bp
from routes.time_slots import bp as time_slots_bp
from routes.customers import bp as customers_bp
from routes.bookings import bp as bookings_bp
from routes.participants import bp as participants_bp
from routes.gift_cards import bp as gift_cards_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(venues_bp)
    app.register_blueprint(rooms_bp)
    app.register_blueprint(pricing_rules_bp)
    app.register_blueprint(game_masters_bp)
    app.register_blueprint(time_slots_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(participants_bp)
    app.register_blueprint(gift_cards_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        body = error_body(e.error_id, e.message)
        return jsonify(body), e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        body = error_body("ERR_NOT_FOUND", "Resource not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(e):
        body = error_body("ERR_NOT_FOUND", "Method not allowed")
        return jsonify(body), 404

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return handle_api_error(e)
        body = error_body("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e))
        return jsonify(body), 422

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Under per-test-server isolation the runner kills the prior server (kill -9)
    # and immediately reboots us on the same port. kill -9 is async, so the old
    # socket can linger in the kernel for a brief window, making the fresh
    # app.run() bind fail with OSError: [Errno 48] Address already in use and
    # the process exit with code 1 -> ServerStartError. Under the 8x concurrent
    # stability sweep this race widens. Retry the bind for a short window so a
    # transient EADDRINUSE during rapid restarts does not kill the boot.
    deadline = time.time() + 20.0
    while True:
        try:
            app.run(host="0.0.0.0", port=port, threaded=True)
            break
        except OSError:
            if time.time() >= deadline:
                raise
            time.sleep(0.25)
