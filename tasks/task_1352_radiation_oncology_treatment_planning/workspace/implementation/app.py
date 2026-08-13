"""Radiation Oncology Treatment Planning & Dosimetry API — entry point.

Flask app wiring: blueprints per resource group, ApiError handling, and
fallback handlers that keep the error envelope shape on 404/405/500.
The store starts empty on every boot; nothing is seeded at startup.
"""
import os

from flask import Flask

from errors import ApiError
from response import api_error_response, error_body
from flask import jsonify


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.patients import bp as patients_bp
    from routes.courses import bp as courses_bp
    from routes.simulations import bp as sims_bp
    from routes.contours import bp as contours_bp
    from routes.plans import bp as plans_bp
    from routes.fractions import bp as fractions_bp
    from routes.machines import bp as machines_bp
    from routes.interruptions import bp as interruptions_bp
    from routes.reviews import bp as reviews_bp
    from routes.claims import bp as claims_bp
    from routes.clock import bp as clock_bp

    for bp in (patients_bp, courses_bp, sims_bp, contours_bp, plans_bp,
               fractions_bp, machines_bp, interruptions_bp, reviews_bp,
               claims_bp, clock_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return api_error_response(e)

    @app.errorhandler(404)
    def _not_found(e):
        body = error_body("ERR_NOT_FOUND", "resource not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _method_not_allowed(e):
        body = error_body("ERR_NOT_FOUND", "method not allowed")
        return jsonify(body), 405

    @app.errorhandler(Exception)
    def _internal(e):
        body = error_body("ERR_INTERNAL", str(e))
        return jsonify(body), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
