"""Adult Day Health & PACE Program API — entry point.

In-memory store only; state starts empty on every boot (no seeding). Foreground
Flask server bound to 0.0.0.0:$PORT (default 10000)."""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response
import db

from routes.programs import bp as programs_bp
from routes.participants import bp as participants_bp
from routes.enrollments import bp as enrollments_bp
from routes.loc_assessments import bp as loc_bp
from routes.care_plans import bp as care_plans_bp
from routes.attendance import bp as attendance_bp
from routes.transport import bp as transport_bp
from routes.medications import bp as medications_bp
from routes.capitation import bp as capitation_bp
from routes.disenrollment import bp as disenrollment_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (programs_bp, participants_bp, enrollments_bp, loc_bp,
               care_plans_bp, attendance_bp, transport_bp, medications_bp,
               capitation_bp, disenrollment_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", 400, "Malformed request")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INVALID_REQUEST", 400, str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Prefer waitress (a production-grade WSGI server) over Flask's dev server.
    # Under per-test-server isolation the test client reuses keep-alive
    # connections from a requests.Session pool; the Werkzeug dev server
    # intermittently resets those reused connections under concurrent load,
    # surfacing as BadStatusLine/ConnectionError in the test runner. Waitress
    # handles connection lifecycle robustly and eliminates that flakiness.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8,
              channel_timeout=120, connection_limit=1000)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
