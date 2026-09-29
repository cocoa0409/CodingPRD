"""Wrestling Weight Certification & Descent Plan API.

Flask application factory and process entry point.  Storage is entirely
in-memory (see store.py); the process starts with a completely empty store on
every boot and never seeds, preloads or hardcodes any entity data.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error
from errors import ApiError
from routes.assess import bp as assess_bp
from routes.compete import bp as compete_bp
from routes.core import bp as core_bp
from routes.people import bp as people_bp
from routes.plans import bp as plans_bp
from routes.safety import bp as safety_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for blueprint in (core_bp, people_bp, assess_bp, plans_bp, compete_bp, safety_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error("ERR_NOT_FOUND", "No route matches the requested path.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return error("ERR_METHOD_NOT_ALLOWED",
                     "That method is not allowed for this path.", 405)

    @app.errorhandler(400)
    def _bad_request(exc):
        return error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(HTTPException)
    def _http_exception(exc):
        return error("ERR_INVALID_REQUEST", exc.description or "Request refused.",
                     exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error("ERR_INVALID_REQUEST",
                     "Unhandled server condition: %s" % (exc,), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
