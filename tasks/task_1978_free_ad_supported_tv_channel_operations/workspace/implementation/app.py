"""Fast Channel Ops API — Flask entry point.

Storage is in-memory only; the store starts empty on every boot. The logical
clock starts at exactly 2026-08-01T00:00:00Z and is advanced exclusively via
POST /v1/_clock/set-current-utc.
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body

from routes.channels import bp as channels_bp
from routes.content import bp as content_bp
from routes.loops import bp as loops_bp
from routes.decisions import bp as decisions_bp
from routes.campaigns import bp as campaigns_bp
from routes.house_ads import bp as house_ads_bp
from routes.platforms import bp as platforms_bp
from routes.reports import bp as reports_bp
from routes.events import bp as events_bp
from routes.snapshots import bp as snapshots_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        channels_bp,
        content_bp,
        loops_bp,
        decisions_bp,
        campaigns_bp,
        house_ads_bp,
        platforms_bp,
        reports_bp,
        events_bp,
        snapshots_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify(error_body(err.error_id, err.message)), err.http_status

    @app.errorhandler(404)
    def handle_404(err):
        body = error_body("ERR_NOT_FOUND", "Resource not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(err):
        body = error_body("ERR_NOT_FOUND", "Resource not found")
        return jsonify(body), 404

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        body = error_body("ERR_INVALID_REQUEST", "Unexpected error: %s" % err)
        return jsonify(body), 400

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
