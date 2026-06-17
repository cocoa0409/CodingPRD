"""Online Course Marketplace API — Flask entry point.

Registers all route blueprints, installs the standard error envelope, and runs
the server on 0.0.0.0:$PORT in the foreground. The in-memory store starts EMPTY
on every boot — no seeding.
"""
import os

from flask import Flask, request

import clock
import response
from errors import ApiError

from routes.accounts import bp as accounts_bp
from routes.courses import bp as courses_bp
from routes.lessons import bp as lessons_bp
from routes.coupons import bp as coupons_bp
from routes.bundles import bp as bundles_bp
from routes.enrollments import bp as enrollments_bp
from routes.lesson_completions import bp as lesson_completions_bp
from routes.certificates import bp as certificates_bp
from routes.reviews import bp as reviews_bp
from routes.payouts import bp as payouts_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Reset the logical clock to wall-time on each fresh boot.
    clock.reset()

    for bp in (accounts_bp, courses_bp, lessons_bp, coupons_bp, bundles_bp,
               enrollments_bp, lesson_completions_bp, certificates_bp,
               reviews_bp, payouts_bp, clock_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return response.error(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> standard ERR_NOT_FOUND envelope.
        return response.error("ERR_NOT_FOUND", "Resource or route not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return response.error("ERR_NOT_FOUND", "Method not allowed for this route.", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return response.error("ERR_INVALID_REQUEST", "Malformed request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Surface unexpected failures as a generic invalid-request rather than a
        # bare HTML 500, so the envelope is always well-formed.
        if isinstance(e, ApiError):
            return response.error(e.error_id, e.message, e.http_status)
        import traceback
        traceback.print_exc()
        return response.error("ERR_INVALID_REQUEST", "Internal error.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
