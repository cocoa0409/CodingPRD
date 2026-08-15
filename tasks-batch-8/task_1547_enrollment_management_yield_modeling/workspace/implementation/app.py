"""Enrollment Yield API — Flask entry point."""
import os
from flask import Flask, request

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response
from routes.cycles import bp as cycles_bp
from routes.programs import bp as programs_bp
from routes.applicants import bp as applicants_bp
from routes.applications import bp as applications_bp
from routes.reviews import bp as reviews_bp
from routes.aid_offers import bp as aid_offers_bp
from routes.deposits import bp as deposits_bp
from routes.waitlist import bp as waitlist_bp
from routes.interventions import bp as interventions_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(cycles_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(applicants_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(aid_offers_bp)
    app.register_blueprint(deposits_bp)
    app.register_blueprint(waitlist_bp)
    app.register_blueprint(interventions_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "Not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_INVALID_REQUEST, "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_exception(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        import traceback
        traceback.print_exc()
        return error_response(ERR_INVALID_REQUEST, f"Internal error: {err}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
