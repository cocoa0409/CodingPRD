"""Entry point: Flask app assembly, error handlers, route registration."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError, ERR_NOT_FOUND
from routes import billing, fleet, pickups, plans, subscribers, subscriptions


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(plans.bp)
    app.register_blueprint(subscribers.bp)
    app.register_blueprint(subscriptions.bp)
    app.register_blueprint(fleet.bp)
    app.register_blueprint(pickups.bp)
    app.register_blueprint(billing.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return response.err(e.error_id, e.message, e.status)

    @app.errorhandler(HTTPException)
    def handle_http_error(e):
        return response.err(ERR_NOT_FOUND, e.description, e.code or 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return response.err("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
