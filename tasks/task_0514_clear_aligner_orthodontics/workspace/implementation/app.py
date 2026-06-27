"""Clear-Aligner Orthodontics API — Flask entry point.

In-memory storage only; no entities seeded at startup. Boots fresh on every
start.sh invocation.
"""
import os

from flask import Flask

from errors import ApiError, err
from response import error_response

from routes.patients import bp as patients_bp
from routes.clinicians import bp as clinicians_bp
from routes.cases import bp as cases_bp
from routes.plans import bp as plans_bp
from routes.aligner_steps import bp as steps_bp
from routes.shipments import bp as shipments_bp
from routes.checkins import bp as checkins_bp
from routes.refinements import bp as refinements_bp
from routes.financing import bp as financing_bp
from routes.refunds import bp as refunds_bp
from routes.retainers import bp as retainers_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (patients_bp, clinicians_bp, cases_bp, plans_bp, steps_bp,
               shipments_bp, checkins_bp, refinements_bp, financing_bp,
               refunds_bp, retainers_bp, clock_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(err("ERR_NOT_FOUND", "Resource not found."))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(err("ERR_NOT_FOUND", "Method not allowed."))

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(err("ERR_INVALID_REQUEST", "Bad request."))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e)
        return error_response(err("ERR_VALIDATION", "Unexpected error: %s" % e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
