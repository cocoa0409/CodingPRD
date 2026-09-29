"""Flask entry point.  Boots an entirely empty in-memory store every time.

The harness relaunches this process before every single test, so there is
deliberately no persistence of any kind and no seed data whatsoever.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, _meta, error_response
from routes import blueprints


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in blueprints:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST" if err.code in (400, 405, 415)
                            else "ERR_NOT_FOUND",
                "message": err.description or "Request could not be served.",
            },
        }
        return jsonify(body), err.code

    @app.errorhandler(Exception)
    def _unhandled(err):
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
        }
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False)
