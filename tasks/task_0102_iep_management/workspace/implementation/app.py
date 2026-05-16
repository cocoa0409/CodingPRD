"""Special Education IEP Management API — Flask entry point.

PRD: workspace/PRD.md. SCAFFOLD: SCAFFOLD.yaml.
Listens on PORT env (default 10000), binds 0.0.0.0.
"""

import os
import traceback

from flask import Flask

from core.errors import APIError
from core.envelope import error_response

from routes.districts import bp as districts_bp
from routes.evaluations import bp as evaluations_bp
from routes.consents import bp as consents_bp
from routes.ieps import bp as ieps_bp
from routes.goals import bp as goals_bp
from routes.related_services import bp as related_services_bp
from routes.transition_plans import bp as transition_plans_bp


def _build_app() -> Flask:
    app = Flask(__name__)
    app.config["TRAP_HTTP_EXCEPTIONS"] = False

    @app.errorhandler(APIError)
    def _api_err(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(_e):
        # Default Flask 404 = unmatched route. Per the PRD this should not occur
        # for hierarchical resource paths (each prefix is matched by a blueprint).
        # But return a sensible fallback in case a totally unknown path is hit.
        return error_response("ERR_DISTRICT_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def _method(_e):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 400)

    @app.errorhandler(400)
    def _bad_req(_e):
        return error_response("ERR_INVALID_REQUEST", "Bad request.", 400)

    @app.errorhandler(Exception)
    def _unhandled(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", str(e) or "Internal error", 400)

    # Register blueprints.
    app.register_blueprint(districts_bp)
    app.register_blueprint(evaluations_bp)
    app.register_blueprint(consents_bp)
    app.register_blueprint(ieps_bp)
    app.register_blueprint(goals_bp)
    app.register_blueprint(related_services_bp)
    app.register_blueprint(transition_plans_bp)

    return app


app = _build_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
