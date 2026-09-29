"""Private Road Association Maintenance & Assessment API.

A single Flask process holding all state in memory. The store starts empty on
every boot: nothing is seeded, preloaded or read from disk.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response as R
from errors import ApiError
from routes import (assessment_charges, assessment_rolls, associations, ballots,
                    clock, connection_requests, contractor_bids,
                    delinquency_actions, members, parcels, projects, proposals,
                    road_segments)

BLUEPRINTS = (
    associations.bp,
    road_segments.bp,
    parcels.bp,
    members.bp,
    assessment_rolls.bp,
    assessment_charges.bp,
    delinquency_actions.bp,
    proposals.bp,
    ballots.bp,
    projects.bp,
    contractor_bids.bp,
    connection_requests.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return R.error_body(error.error_id, error.message), error.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if error.code == 404:
            return R.error_body("ERR_INVALID_REQUEST", "No such route."), 404
        if error.code == 405:
            return R.error_body("ERR_INVALID_REQUEST", "Method not allowed."), 405
        if error.code in (400, 415):
            return R.error_body("ERR_INVALID_REQUEST", "The request could not be parsed."), 400
        return R.error_body("ERR_INVALID_REQUEST", error.description or "Request failed."), error.code

    @app.errorhandler(Exception)
    def handle_unexpected(error):  # pragma: no cover - defensive
        return R.error_body("ERR_INVALID_REQUEST", "Unexpected server error: %s" % (error,)), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
