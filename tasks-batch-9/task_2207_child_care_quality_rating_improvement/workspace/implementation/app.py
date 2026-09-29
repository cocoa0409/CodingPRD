"""Child Care Quality Rating & Improvement API — Flask entry point.

Storage is in-memory only and starts completely empty on every boot.
No entity is seeded, preloaded or hardcoded at startup.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.system import bp as system_bp
    from routes.providers import bp as providers_bp
    from routes.cycles import bp as cycles_bp
    from routes.observation import bp as observation_bp
    from routes.remedy import bp as remedy_bp
    from routes.funding import bp as funding_bp
    from routes.coaching import bp as coaching_bp
    from routes.claims import bp as claims_bp

    for bp in (system_bp, providers_bp, cycles_bp, observation_bp,
               remedy_bp, funding_bp, coaching_bp, claims_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(response.error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_404(exc):
        return jsonify(response.error_body("ERR_VALIDATION", "resource not found")), 404

    @app.errorhandler(405)
    def handle_405(exc):
        return jsonify(response.error_body("ERR_VALIDATION", "method not allowed")), 405

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        if exc.code == 400:
            return jsonify(response.error_body("ERR_VALIDATION", "malformed request")), 422
        return jsonify(response.error_body("ERR_VALIDATION", exc.description or "error")), exc.code

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error")
        return jsonify(response.error_body("ERR_VALIDATION", str(exc))), 422

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
