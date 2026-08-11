"""Entry point: Flask app, error handlers, route registration."""

import os

from flask import Flask

from errors import ApiError, ERR_VALIDATION
from response import error_body
from routes import (
    physicians, cases, offers, credentials, training, templates,
    panels, campaigns, guarantees, milestones, mentorship, snapshots, ops,
)

app = Flask(__name__)

for module in (
    physicians, cases, offers, credentials, training, templates,
    panels, campaigns, guarantees, milestones, mentorship, snapshots, ops,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_body(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(_exc):
    return error_body(ERR_VALIDATION, "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    return error_body(ERR_VALIDATION, "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return error_body(ERR_VALIDATION, "Unexpected server error: %s" % exc, 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
