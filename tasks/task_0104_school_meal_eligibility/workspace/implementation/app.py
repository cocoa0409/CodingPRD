"""K-12 School Meal Eligibility API — Flask entry point.

PRD: workspace/PRD.md
SCAFFOLD: SCAFFOLD.yaml

Listens on PORT env (default 10000), binds 0.0.0.0.
"""

import os
import traceback
from flask import Flask, request

from core.auth import parse_auth
from core.envelope import error_response
from core.errors import APIError

from routes.districts import bp as districts_bp
from routes.parent_accounts import bp as parent_accounts_bp
from routes.students import bp as students_bp
from routes.allergy_entries import bp as allergy_entries_bp
from routes.frl_applications import bp as frl_applications_bp
from routes.menu_items import bp as menu_items_bp
from routes.meal_servings import bp as meal_servings_bp
from routes.usda_claims import bp as usda_claims_bp
from routes.system import bp as system_bp


def _build_app() -> Flask:
    app = Flask(__name__)
    app.config["TRAP_HTTP_EXCEPTIONS"] = False

    @app.before_request
    def _auth_gate():
        # Skip auth for OPTIONS/preflight.
        if request.method == "OPTIONS":
            return None
        # Skip auth for the test-harness reset path.
        if request.path.startswith("/__test__/"):
            return None
        parse_auth()
        return None

    @app.errorhandler(APIError)
    def _api_err(e):
        return error_response(e)

    @app.errorhandler(404)
    def _not_found(_e):
        return error_response(APIError("ERR_NOT_FOUND", "Resource not found", 404))

    @app.errorhandler(405)
    def _method(_e):
        return error_response(APIError("ERR_VALIDATION", "Method not allowed", 422))

    @app.errorhandler(400)
    def _bad_request(_e):
        return error_response(APIError("ERR_VALIDATION", "Bad request", 422))

    @app.errorhandler(Exception)
    def _unhandled(e):
        traceback.print_exc()
        if isinstance(e, APIError):
            return error_response(e)
        return error_response(APIError("ERR_VALIDATION", str(e) or "Internal error", 422))

    # Register blueprints.
    app.register_blueprint(districts_bp)
    app.register_blueprint(parent_accounts_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(allergy_entries_bp)
    app.register_blueprint(frl_applications_bp)
    app.register_blueprint(menu_items_bp)
    app.register_blueprint(meal_servings_bp)
    app.register_blueprint(usda_claims_bp)
    app.register_blueprint(system_bp)

    return app


app = _build_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
