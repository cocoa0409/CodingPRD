"""Professional Engineering Licensure & Comity — API entry point.

Storage is entirely in memory (see db.py) and nothing is seeded: every boot of
this process starts with an empty board register and the logical clock parked at
its epoch.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes import (applications, clock, cpc, enforcement, exams, experience,
                    firms, roster)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in (clock.bp, roster.bp, applications.bp, experience.bp,
                      exams.bp, firms.bp, cpc.bp, enforcement.bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 404:
            error_id = "ERR_NOT_FOUND"
        elif status == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        else:
            error_id = "ERR_INVALID_REQUEST"
        return jsonify(error_body(error_id, exc.description or "request rejected")), status

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return jsonify(error_body("ERR_INTERNAL", str(exc))), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
