"""Retail Site Selection & Trade Area Analysis API — Flask entry point."""

import os

from flask import Flask, jsonify

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.markets import bp as markets_bp
    from routes.sites import bp as sites_bp
    from routes.models import bp as models_bp
    from routes.visits import bp as visits_bp
    from routes.forecasts import bp as forecasts_bp
    from routes.committee import bp as committee_bp
    from routes.deals import bp as deals_bp
    from routes.build import bp as build_bp
    from routes.snapshots import bp as snapshots_bp
    from routes.clock import bp as clock_bp

    for bp in (markets_bp, sites_bp, models_bp, visits_bp, forecasts_bp,
               committee_bp, deals_bp, build_bp, snapshots_bp, clock_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify(error_body(err.error_id, err.message)), err.http_status

    @app.errorhandler(404)
    def handle_404(_err):
        return jsonify(error_body(ERR_NOT_FOUND, "Resource not found")), 404

    @app.errorhandler(405)
    def handle_405(_err):
        return jsonify(error_body(ERR_NOT_FOUND, "Resource not found")), 404

    @app.errorhandler(400)
    def handle_400(_err):
        return jsonify(error_body(ERR_INVALID_REQUEST, "Bad request")), 400

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
