import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body
from routes.consignors import bp as consignors_bp
from routes.schedules import bp as schedules_bp
from routes.agreements import bp as agreements_bp
from routes.batches import bp as batches_bp
from routes.items import bp as items_bp
from routes.reviews import bp as reviews_bp
from routes.sales import bp as sales_bp
from routes.settlements import bp as settlements_bp
from routes.misc import bp as misc_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(consignors_bp)
    app.register_blueprint(schedules_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(batches_bp)
    app.register_blueprint(items_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(misc_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return jsonify(error_body(e.error_id, e.message)), e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404

    @app.errorhandler(405)
    def handle_405(e):
        return jsonify(error_body("ERR_NOT_FOUND", "Method not allowed")), 404

    @app.errorhandler(400)
    def handle_400(e):
        return jsonify(error_body("ERR_INVALID_REQUEST", "Malformed request")), 400

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return handle_api_error(e)
        # Surface unexpected errors as a generic invalid-request rather than a
        # bare HTML 500 so the envelope contract holds.
        return jsonify(error_body("ERR_INVALID_REQUEST", "Internal error: %s" % e)), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
