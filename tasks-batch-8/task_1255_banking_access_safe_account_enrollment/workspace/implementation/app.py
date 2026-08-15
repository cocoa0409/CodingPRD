"""Flask application entry point.

In-memory store starts empty on every boot. No seeding of any kind.
"""

import os

from flask import Blueprint, Flask, jsonify

from errors import ApiError
from response import error_response
from routes import (
    standards, institutions, reviews, participants, referrals, events,
    applications, barrier_cases, education, checkpoints, grants, reports,
    campaigns, clock,
)

app = Flask(__name__)

api = Blueprint("api", __name__, url_prefix="/api")
for module in (
    standards, institutions, reviews, participants, referrals, events,
    applications, barrier_cases, education, checkpoints, grants, reports,
    campaigns, clock,
):
    module.register(api)
app.register_blueprint(api)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(_exc):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(_exc):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(500)
def handle_500(exc):
    return error_response("ERR_VALIDATION", "Internal error: %s" % exc, 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
