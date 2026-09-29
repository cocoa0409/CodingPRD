"""Conference Revenue Distribution & Membership Change API.

A single Flask process holding all state in memory (PRD section 2.1).  Every
boot starts with an empty store: no conference, no members, no pools.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from db import db
from errors import ApiError
from routes.actions import bp as actions_bp
from routes.audits import bp as audits_bp
from routes.bowls import bp as bowls_bp
from routes.budgets import bp as budgets_bp
from routes.core import bp as core_bp
from routes.events import bp as events_bp
from routes.members import bp as members_bp
from routes.pools import bp as pools_bp
from routes.runs import bp as runs_bp
from routes.schedule import bp as schedule_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        core_bp,
        members_bp,
        pools_bp,
        runs_bp,
        bowls_bp,
        actions_bp,
        budgets_bp,
        schedule_bp,
        events_bp,
        audits_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return response.error_body(err.error_id, err.message), err.http_status

    @app.errorhandler(HTTPException)
    def _http_error(err):
        # Unroutable paths and unsupported methods keep the declared envelope.
        return (
            response.error_body("ERR_INVALID_REQUEST", err.description),
            err.code or 400,
        )

    @app.errorhandler(Exception)
    def _unexpected(err):  # pragma: no cover - defensive
        return response.error_body("ERR_INVALID_REQUEST", str(err)), 500

    # A fresh process starts with a completely empty store; nothing is seeded.
    db.reset()
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
