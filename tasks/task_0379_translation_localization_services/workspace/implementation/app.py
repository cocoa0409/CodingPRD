"""Translation & Localization Services API — Flask entry point.

In-memory store starts empty on every boot. No seeding.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body

from routes.clients import bp as clients_bp
from routes.linguists import bp as linguists_bp
from routes.rate_cards import bp as rate_cards_bp
from routes.projects import bp as projects_bp
from routes.jobs import bp as jobs_bp
from routes.assignments import bp as assignments_bp
from routes.qa_reports import bp as qa_reports_bp
from routes.invoices import bp as invoices_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clients_bp)
    app.register_blueprint(linguists_bp)
    app.register_blueprint(rate_cards_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(qa_reports_bp)
    app.register_blueprint(invoices_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        body = error_body(e.error_id, e.message)
        return jsonify(body), e.http_status

    @app.errorhandler(404)
    def handle_404(_e):
        body = error_body("ERR_NOT_FOUND", "Resource not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(_e):
        body = error_body("ERR_NOT_FOUND", "Method not allowed")
        return jsonify(body), 404

    @app.errorhandler(400)
    def handle_400(_e):
        body = error_body("ERR_INVALID_REQUEST", "Bad request")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return handle_api_error(e)
        body = error_body("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e))
        return jsonify(body), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Prefer waitress: a production-grade, multithreaded WSGI server that handles the
    # per-test-server restart window far more gracefully than Flask's dev server (clean
    # connection teardown, no keep-alive reuse against a freshly-restarted worker), which
    # eliminates the sporadic ConnectionReset/BadStatusLine flakes seen under the 8x
    # concurrent restart load. Falls back to Flask's built-in server if waitress is absent.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8,
              connection_limit=200, channel_timeout=60)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
