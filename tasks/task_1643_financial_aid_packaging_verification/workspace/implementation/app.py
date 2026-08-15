"""Financial Aid Packaging & Verification API — Flask entry point."""
import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config["JSON_SORT_KEYS"] = False

    from routes import (
        clock, aid_years, fund_types, students, isir, verification, conflicts,
        pj, packages, lines, disbursements, external_aid, overaward,
        reconciliation,
    )
    for mod in (
        clock, aid_years, fund_types, students, isir, verification, conflicts,
        pj, packages, lines, disbursements, external_aid, overaward,
        reconciliation,
    ):
        app.register_blueprint(mod.bp, url_prefix="/api")

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        import traceback
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", f"unexpected error: {err}", 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
