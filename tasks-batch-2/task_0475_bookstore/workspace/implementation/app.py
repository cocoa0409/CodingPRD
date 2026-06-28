"""Bookstore API — Flask entry point."""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response

from routes.clock_routes import bp as clock_bp
from routes.members import bp as members_bp
from routes.titles import bp as titles_bp
from routes.stock_items import bp as stock_items_bp
from routes.sales_orders import bp as sales_orders_bp
from routes.order_lines import bp as order_lines_bp
from routes.special_orders import bp as special_orders_bp
from routes.publisher_returns import bp as publisher_returns_bp
from routes.buybacks import bp as buybacks_bp
from routes.buyback_lines import bp as buyback_lines_bp
from routes.author_events import bp as author_events_bp
from routes.event_tickets import bp as event_tickets_bp
from routes.consignment import bp as consignment_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp, members_bp, titles_bp, stock_items_bp, sales_orders_bp,
        order_lines_bp, special_orders_bp, publisher_returns_bp, buybacks_bp,
        buyback_lines_bp, author_events_bp, event_tickets_bp, consignment_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        body = error_response(e.error_id, e.message)
        resp = jsonify(body)
        resp.status_code = e.http_status
        return resp

    @app.errorhandler(404)
    def handle_404(e):
        body = error_response("ERR_NOT_FOUND", "Resource not found")
        resp = jsonify(body)
        resp.status_code = 404
        return resp

    @app.errorhandler(405)
    def handle_405(e):
        body = error_response("ERR_NOT_FOUND", "Method not allowed")
        resp = jsonify(body)
        resp.status_code = 404
        return resp

    @app.errorhandler(400)
    def handle_400(e):
        body = error_response("ERR_INVALID_REQUEST", "Malformed request")
        resp = jsonify(body)
        resp.status_code = 400
        return resp

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return handle_api_error(e)
        body = error_response("ERR_INVALID_REQUEST", f"Unexpected error: {e}")
        resp = jsonify(body)
        resp.status_code = 400
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
