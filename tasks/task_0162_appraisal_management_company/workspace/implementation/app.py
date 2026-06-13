"""Appraisal Management Company API — entry point and error handlers."""
import os

from flask import Flask, jsonify

import errors
import response
from routes import (appraisers, assignments, clock_route, compliance_reviews,
                    lenders, orders, properties, reconsiderations, reports)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(lenders.bp)
    app.register_blueprint(appraisers.bp)
    app.register_blueprint(properties.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(assignments.bp)
    app.register_blueprint(reports.bp)
    app.register_blueprint(compliance_reviews.bp)
    app.register_blueprint(reconsiderations.bp)
    app.register_blueprint(clock_route.bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        body = response.error_response(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def handle_404(_exc):
        body = response.error_response(errors.ERR_NOT_FOUND, "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(_exc):
        body = response.error_response(errors.ERR_NOT_FOUND, "Method not allowed.")
        return jsonify(body), 404

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return handle_api_error(exc)
        body = response.error_response("ERR_INTERNAL", "Internal server error: %s" % exc)
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
