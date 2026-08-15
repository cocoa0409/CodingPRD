"""Dual Enrollment & Concurrent Credit API — Flask entry point.

In-memory only: the store (db.py) starts empty on every process boot; nothing
is seeded. The evaluator runs `bash start.sh`, which execs this module.
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from response import error_response


def create_app():
    app = Flask(__name__)
    try:
        app.json.sort_keys = False
    except Exception:
        pass

    from routes import (
        articulation_agreements,
        clock,
        courses,
        credential_applications,
        enrollments,
        funding_agreements,
        high_schools,
        instructors,
        invoices,
        offerings,
        placement_records,
        prerequisites,
        students,
        terms,
        transcript_entries,
    )

    for mod in (
        high_schools,
        terms,
        students,
        courses,
        prerequisites,
        placement_records,
        instructors,
        credential_applications,
        offerings,
        enrollments,
        transcript_entries,
        funding_agreements,
        invoices,
        articulation_agreements,
        clock,
    ):
        app.register_blueprint(mod.bp, url_prefix="/dual-credit")

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND[0], "resource not found", ERR_NOT_FOUND[1])

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND[0], "method not allowed", ERR_NOT_FOUND[1])

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        import traceback

        traceback.print_exc()
        return error_response(ERR_VALIDATION[0], f"unexpected error: {err}", ERR_VALIDATION[1])

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
