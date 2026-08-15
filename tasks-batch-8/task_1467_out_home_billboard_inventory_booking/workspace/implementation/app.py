"""Out-of-Home Billboard Booking API — Flask entry point."""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body
from routes import clock_routes, rate_cards, faces, permits, work_orders, \
    advertisers, campaigns, flights, artwork, postings, make_goods


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_routes.bp)
    app.register_blueprint(rate_cards.bp)
    app.register_blueprint(faces.bp)
    app.register_blueprint(permits.bp)
    app.register_blueprint(work_orders.bp)
    app.register_blueprint(advertisers.bp)
    app.register_blueprint(campaigns.bp)
    app.register_blueprint(flights.bp)
    app.register_blueprint(artwork.bp)
    app.register_blueprint(postings.bp)
    app.register_blueprint(make_goods.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify(error_body(err.error_id, err.message)), err.http_status

    @app.errorhandler(404)
    def handle_404(err):
        body = error_body("ERR_INVALID_REQUEST", "Resource path not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(err):
        body = error_body("ERR_INVALID_REQUEST", "Method not allowed")
        return jsonify(body), 405

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        body = error_body("ERR_INVALID_REQUEST", "Unexpected error: %s" % err)
        return jsonify(body), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
