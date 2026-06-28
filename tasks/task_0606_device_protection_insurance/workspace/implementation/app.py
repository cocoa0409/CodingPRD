import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body
from routes.reference import bp as reference_bp
from routes.enrollments import bp as enrollments_bp
from routes.claims import bp as claims_bp
from routes.logistics import bp as logistics_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(reference_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(logistics_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        body = error_body(e.error_id, e.message)
        return jsonify(body), e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        body = error_body("ERR_NOT_FOUND", "Resource not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(e):
        body = error_body("ERR_NOT_FOUND", "Method not allowed")
        return jsonify(body), 404

    @app.errorhandler(Exception)
    def handle_uncaught(e):
        if isinstance(e, ApiError):
            return handle_api_error(e)
        body = error_body("ERR_VALIDATION", str(e))
        return jsonify(body), 422

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
