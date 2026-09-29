"""Food Manager Certification & Exam Proctoring API.

Flask application factory and wiring. All state lives in process memory and
starts empty on every boot: nothing is seeded, preloaded or hardcoded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from store import store

from routes_core import core_bp
from routes_people import people_bp
from routes_codes import codes_bp
from routes_accommodations import accommodations_bp
from routes_sessions import sessions_bp
from routes_scoring import scoring_bp
from routes_registrations import registrations_bp
from routes_incidents import incidents_bp

BLUEPRINTS = (core_bp, people_bp, codes_bp, accommodations_bp, sessions_bp,
              scoring_bp, registrations_bp, incidents_bp)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _begin():
        store.begin_request()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST",
                                  "the requested route does not exist", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST",
                                  "the method is not allowed on this route",
                                  405)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  "the request could not be parsed", 400)
        return error_response("ERR_INVALID_REQUEST",
                              exc.description or "request rejected",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        app.logger.exception("unhandled error: %s", exc)
        return error_response("ERR_INVALID_REQUEST", str(exc) or "server error",
                              400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
