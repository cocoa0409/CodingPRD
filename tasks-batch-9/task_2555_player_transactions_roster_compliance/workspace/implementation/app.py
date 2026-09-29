"""Player transactions and roster compliance service.

Entry point: registers every blueprint and installs the PRD 2.2 error envelope.
The store starts empty on every boot; nothing is seeded here.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import r_clock
import r_compliance
import r_contracts
import r_medical
import r_players
import r_teams
import r_tenders
import r_trades
import r_transactions
import r_waivers
from envelope import error_body
from errors import ApiError

BLUEPRINTS = (
    r_clock.bp,
    r_teams.bp,
    r_players.bp,
    r_transactions.bp,
    r_contracts.bp,
    r_waivers.bp,
    r_trades.bp,
    r_tenders.bp,
    r_medical.bp,
    r_compliance.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_body(exc.error_id, exc.message), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_body("ERR_INVALID_REQUEST", "unknown route"), 404
        if exc.code == 405:
            return error_body("ERR_INVALID_REQUEST", "method not allowed"), 405
        if exc.code in (400, 415):
            return error_body("ERR_INVALID_REQUEST", "malformed request"), 400
        return error_body("ERR_INVALID_REQUEST", exc.name), exc.code

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return error_body("ERR_INVALID_REQUEST", str(exc)), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=False,
        debug=False,
    )
