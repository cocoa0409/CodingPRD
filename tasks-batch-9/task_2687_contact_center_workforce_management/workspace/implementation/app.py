"""Contact-centre workforce management API (PRD-driven, in-memory).

Storage lives in plain Python dicts inside this process; nothing is seeded, and a
fresh process therefore starts with an empty world and the logical clock at its
default instant.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response
import routes_planning
import routes_demand
import routes_roster
import routes_bidding
import routes_shifts
import routes_intraday
import routes_partners


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(routes_planning.bp)
    app.register_blueprint(routes_demand.bp)
    app.register_blueprint(routes_roster.bp)
    app.register_blueprint(routes_bidding.bp)
    app.register_blueprint(routes_shifts.bp)
    app.register_blueprint(routes_intraday.bp)
    app.register_blueprint(routes_partners.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response_raw("ERR_NOT_FOUND", "No such route", 404)
        if exc.code == 405:
            return error_response_raw("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)
        if exc.code in (400, 415):
            return error_response("ERR_VALIDATION", "Malformed request")
        return error_response_raw("ERR_INTERNAL", exc.name, exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response_raw("ERR_INTERNAL", str(exc), 500)

    return app


def error_response_raw(error_id, message, status):
    from core import envelope
    return envelope({"error_id": error_id, "message": message}, "error", status)


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
