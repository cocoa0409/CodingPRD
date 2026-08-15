"""Aerospace Machining & AS9100 Program API — Flask entry point."""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes.ltas import bp as ltas_bp
from routes.purchase_orders import bp as purchase_orders_bp
from routes.first_articles import bp as first_articles_bp
from routes.work_orders import bp as work_orders_bp
from routes.serials import bp as serials_bp
from routes.sourcing import bp as sourcing_bp
from routes.ncrs import bp as ncrs_bp
from routes.escapes import bp as escapes_bp
from routes.delegations import bp as delegations_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        ltas_bp,
        purchase_orders_bp,
        first_articles_bp,
        work_orders_bp,
        serials_bp,
        sourcing_bp,
        ncrs_bp,
        escapes_bp,
        delegations_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return jsonify(error_body(e.error_id, e.message)), e.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(e):
        error_id = "ERR_NOT_FOUND" if e.code == 404 else "ERR_REQUEST_ERROR"
        return jsonify(error_body(error_id, e.name)), (e.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return jsonify(error_body("ERR_INTERNAL", str(e))), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
