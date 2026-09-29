"""Student Government Election API — Flask entry point.

In-memory only: the store is empty on every process boot.  Nothing is seeded,
preloaded or hardcoded; every row is created by a client through the declared
API surface.  Time comes from the logical election clock, never from the host.
"""
import os
from decimal import Decimal

from flask import Flask
from flask.json.provider import DefaultJSONProvider

import db
import errors
from response import error_response
from routes.appeals import bp as appeals_bp
from routes.ballots import bp as ballots_bp
from routes.campaign_expenses import bp as campaign_expenses_bp
from routes.candidacies import bp as candidacies_bp
from routes.clock import bp as clock_bp
from routes.compliance_cases import bp as compliance_cases_bp
from routes.elections import bp as elections_bp
from routes.offices import bp as offices_bp
from routes.petition_signatures import bp as petition_signatures_bp
from routes.referenda import bp as referenda_bp
from routes.students import bp as students_bp
from routes.votes import bp as votes_bp


class ElectionJSONProvider(DefaultJSONProvider):
    """Percentages and other decimals are emitted as JSON numbers."""

    @staticmethod
    def default(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return DefaultJSONProvider.default(obj)


def create_app():
    app = Flask(__name__)
    app.json = ElectionJSONProvider(app)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    for blueprint in (
        clock_bp, elections_bp, offices_bp, students_bp, candidacies_bp,
        petition_signatures_bp, campaign_expenses_bp, compliance_cases_bp,
        referenda_bp, ballots_bp, votes_bp, appeals_bp,
    ):
        app.register_blueprint(blueprint)

    @app.before_request
    def _serialise_requests():
        # One request at a time: every handler mutates the shared in-memory
        # store and no reader may observe a half-applied cascade.
        db.store.lock.acquire()

    @app.teardown_request
    def _release_request_lock(_exc=None):
        try:
            db.store.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_unknown_route(_exc):
        return error_response("ERR_NOT_FOUND", "Unknown route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_response("ERR_NOT_FOUND", "Unknown route.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
