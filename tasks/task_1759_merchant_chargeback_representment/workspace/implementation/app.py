"""Entry point: Flask app, error handlers, blueprint registration.

Store starts empty on every boot (module-level in db.py); nothing is seeded.
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    from routes.merchants import bp as merchants_bp
    from routes.rules import bp as rules_bp
    from routes.transactions import bp as transactions_bp
    from routes.chargebacks import bp as chargebacks_bp
    from routes.evidence import bp as evidence_bp
    from routes.representments import bp as representments_bp
    from routes.fees import bp as fees_bp
    from routes.reserves import bp as reserves_bp
    from routes.enrollments import bp as enrollments_bp
    from routes.plans import bp as plans_bp
    from routes.alerts import bp as alerts_bp
    from routes.education import bp as education_bp
    from routes.analytics import bp as analytics_bp
    from routes.ops import bp as ops_bp

    for bp in (merchants_bp, rules_bp, transactions_bp, chargebacks_bp, evidence_bp,
               representments_bp, fees_bp, reserves_bp, enrollments_bp, plans_bp,
               alerts_bp, education_bp, analytics_bp, ops_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return jsonify(error_body(e.error_id, e.message)), e.http_status

    @app.errorhandler(404)
    def handle_not_found(e):
        return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return jsonify(error_body("ERR_NOT_FOUND", "Method not allowed")), 405

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return jsonify(error_body("ERR_INVALID_REQUEST", "Unexpected error: %s" % e)), 400

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
