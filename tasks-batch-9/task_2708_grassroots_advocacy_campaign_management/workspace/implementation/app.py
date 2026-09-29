"""Grassroots Advocacy Campaign Management API.

Flask application factory and error plumbing.  All state lives in the in-memory
dicts of common.DB, so every fresh process starts completely empty: nothing is
seeded, registered or preloaded here or anywhere else.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import routes_action
import routes_activation
import routes_calendar
import routes_campaign
import routes_coalition
import routes_segment
import routes_story
import routes_supporter
import routes_variant
from common import ApiError, _meta, error_response

BLUEPRINTS = (
    routes_campaign.bp,
    routes_calendar.bp,
    routes_supporter.bp,
    routes_segment.bp,
    routes_variant.bp,
    routes_coalition.bp,
    routes_activation.bp,
    routes_action.bp,
    routes_story.bp,
)


def _envelope(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        return _envelope(
            "ERR_INVALID_REQUEST",
            exc.description or exc.name,
            exc.code or 422,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return _envelope("ERR_INVALID_REQUEST", "unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False,
        threaded=True,
        use_reloader=False,
    )
