"""Entry point: Flask app, error handlers, blueprint registration.

The store starts empty on every boot. No seeding, no preloading, no disk
persistence of any kind — restarting the process wipes all state.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)

    from routes.nurses import bp as nurses_bp
    from routes.criteria import bp as criteria_bp
    from routes.participation import bp as participation_bp
    from routes.certifications import bp as certifications_bp
    from routes.applications import bp as applications_bp
    from routes.reviews import bp as reviews_bp
    from routes.budget import bp as budget_bp
    from routes.ops import bp as ops_bp

    app.register_blueprint(nurses_bp)
    app.register_blueprint(criteria_bp)
    app.register_blueprint(participation_bp)
    app.register_blueprint(certifications_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(budget_bp)
    app.register_blueprint(ops_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INVALID_REQUEST", str(err), 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
