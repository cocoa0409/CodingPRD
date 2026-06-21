"""School Meal Eligibility API — Flask entrypoint."""
import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

# Route modules
from routes.households import bp as households_bp
from routes.students import bp as students_bp
from routes.applications import bp as applications_bp
from routes.eligibility import bp as eligibility_bp
from routes.menu_items import bp as menu_items_bp
from routes.parent_accounts import bp as parent_accounts_bp
from routes.service_transactions import bp as service_transactions_bp
from routes.reimbursement_claims import bp as reimbursement_claims_bp
from routes.admin import bp as admin_bp


def create_app() -> Flask:
    app = Flask(__name__)
    # Strict JSON parsing — never assume incoming JSON.
    app.url_map.strict_slashes = False

    app.register_blueprint(households_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(eligibility_bp)
    app.register_blueprint(menu_items_bp)
    app.register_blueprint(parent_accounts_bp)
    app.register_blueprint(service_transactions_bp)
    app.register_blueprint(reimbursement_claims_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        eid, status = ERR_NOT_FOUND
        return error_response(eid, "route not found", status)

    @app.errorhandler(405)
    def handle_405(exc):
        eid, status = ERR_NOT_FOUND
        return error_response(eid, "method not allowed", status)

    @app.errorhandler(400)
    def handle_400(exc):
        eid, status = ERR_INVALID_REQUEST
        msg = getattr(exc, "description", "bad request") if isinstance(exc, HTTPException) else "bad request"
        return error_response(eid, str(msg), status)

    @app.errorhandler(Exception)
    def handle_uncaught(exc):
        # Surface uncaught server errors as INVALID_REQUEST-equivalent generic to keep envelope shape.
        # In production we'd 500. For benchmark surface useful info but maintain the envelope.
        import traceback
        print("Uncaught exception:", repr(exc), file=sys.stderr)
        traceback.print_exc()
        eid = "ERR_INTERNAL"
        return error_response(eid, "internal error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
