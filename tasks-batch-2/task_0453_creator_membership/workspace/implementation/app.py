"""Creator Membership API — Flask entry point.

Wires the response envelope, error handling, and all route blueprints.
In-memory store only; no seeding at startup (the store is empty on every boot).
"""
import os

from flask import Flask

import errors
import response
from routes.creators import bp as creators_bp
from routes.tiers import bp as tiers_bp
from routes.patrons import bp as patrons_bp
from routes.pledges import bp as pledges_bp
from routes.charges import bp as charges_bp
from routes.posts import bp as posts_bp
from routes.conversations import bp as conversations_bp
from routes.messages import bp as messages_bp
from routes.payouts import bp as payouts_bp
from routes.win_back_offers import bp as offers_bp
from routes.admin import bp as admin_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(creators_bp)
    app.register_blueprint(tiers_bp)
    app.register_blueprint(patrons_bp)
    app.register_blueprint(pledges_bp)
    app.register_blueprint(charges_bp)
    app.register_blueprint(posts_bp)
    app.register_blueprint(conversations_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(payouts_bp)
    app.register_blueprint(offers_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route — no body contract is defined; return the envelope.
        return response.error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return response.error("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return response.error(exc.error_id, exc.message, exc.http_status)
        # Surface unexpected errors as a generic 500 in the envelope shape.
        return response.error("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
