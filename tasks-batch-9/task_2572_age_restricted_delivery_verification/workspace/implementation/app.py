"""Age-Restricted Delivery Verification and Compliance API.

Entry point. The store is empty on every boot -- nothing is seeded.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes.attempts import bp as attempts_bp
from routes.compliance import bp as compliance_bp
from routes.customers import bp as customers_bp
from routes.orders import bp as orders_bp
from routes.partners import bp as partners_bp
from routes.reference import bp as reference_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(reference_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(partners_bp)
    app.register_blueprint(attempts_bp)
    app.register_blueprint(compliance_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return jsonify(error_body("ERR_VALIDATION", "no such route")), 404
        if exc.code == 405:
            return jsonify(error_body("ERR_VALIDATION", "method not allowed")), 405
        if exc.code == 400:
            return jsonify(error_body("ERR_VALIDATION", "malformed request")), 400
        return jsonify(error_body("ERR_VALIDATION", exc.description or "request failed")), exc.code

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error")
        return jsonify(error_body("ERR_VALIDATION", "unexpected server error: %s" % exc)), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
