"""Research Core Facility Scheduling & Recharge API — entry point.

In-memory only; every process boot starts with a completely empty store.
"""

import os
from flask import Flask

from errors import ApiError
from util import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes.users import bp as users_bp
    from routes.instruments import bp as instruments_bp
    from routes.training import bp as training_bp
    from routes.grants import bp as grants_bp
    from routes.ratesets import bp as ratesets_bp
    from routes.bookings import bp as bookings_bp
    from routes.usagelogs import bp as usagelogs_bp
    from routes.billing import bp as billing_bp
    from routes.subsidies import bp as subsidies_bp
    from routes.ops import bp as ops_bp

    for bp in (users_bp, instruments_bp, training_bp, grants_bp, ratesets_bp,
               bookings_bp, usagelogs_bp, billing_bp, subsidies_bp, ops_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(500)
    def handle_500(err):
        return error_response("ERR_INVALID_REQUEST", 400, "Internal error: %s" % err)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
