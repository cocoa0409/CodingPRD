"""Co-Signer & Lease-Guarantor Service — Flask entry point."""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from responses import error_body

from routes.misc import bp as misc_bp
from routes.applicants import bp as applicants_bp
from routes.guarantees import bp as guarantees_bp
from routes.agreements import bp as agreements_bp
from routes.claims import bp as claims_bp
from routes.recovery import bp as recovery_bp
from routes.compliance import bp as compliance_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(misc_bp)
    app.register_blueprint(applicants_bp)
    app.register_blueprint(guarantees_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(recovery_bp)
    app.register_blueprint(compliance_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_not_found(exc):
        return jsonify(error_body("ERR_NOT_FOUND", "Resource not found.")), 404

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # Fallback for unmatched methods/paths etc.
        return jsonify(error_body("ERR_INVALID_REQUEST", exc.description or "")), exc.code

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
