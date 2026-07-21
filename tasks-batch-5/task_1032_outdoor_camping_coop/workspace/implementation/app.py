import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import core
from core import ApiError, _make_meta

from routes.members import bp as members_bp
from routes.gear import bp as gear_bp
from routes.rentals import bp as rentals_bp
from routes.orders import bp as orders_bp
from routes.tradeins import bp as tradeins_bp
from routes.classtrips import bp as classtrips_bp
from routes.bookings import bp as bookings_bp
from routes.permits import bp as permits_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__, static_folder=None)

    app.register_blueprint(members_bp)
    app.register_blueprint(gear_bp)
    app.register_blueprint(rentals_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(tradeins_bp)
    app.register_blueprint(classtrips_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(permits_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        body = {
            "meta": _make_meta(),
            "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message},
        }
        return jsonify(body), err.http_status

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        # Map framework-level errors into the standard error envelope.
        error_id = "ERR_VALIDATION" if err.code == 400 else "ERR_UNAUTHORIZED"
        if err.code == 404:
            error_id = "ERR_VALIDATION"
        body = {
            "meta": _make_meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": err.description},
        }
        return jsonify(body), err.code

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        body = {
            "meta": _make_meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": str(err)},
        }
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
