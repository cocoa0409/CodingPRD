"""Exam Anti-Cheating API — Flask entrypoint."""
import os

from flask import Flask

from errors import APIError
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Register blueprints
    from routes.exams import bp as exams_bp
    from routes.questions import bp as questions_bp
    from routes.registrations import bp as registrations_bp
    from routes.attempts import bp as attempts_bp
    from routes.abnormal_events import bp as abnormal_bp
    from routes.grading_assignments import bp as grading_bp
    from routes.appeals import bp as appeals_bp
    from routes.audit_log import bp as audit_bp
    from routes.clock_advance import bp as clock_bp

    for bp in (exams_bp, questions_bp, registrations_bp, attempts_bp,
               abnormal_bp, grading_bp, appeals_bp, audit_bp, clock_bp):
        app.register_blueprint(bp)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_EXAM_NOT_FOUND",
                              "Route or resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                              "Method not allowed", 400)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                              "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_exc(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        # Fallback: log and return a generic 400 — tests should never trip this.
        import traceback
        traceback.print_exc()
        return error_response("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                              str(e) or "Internal error", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
