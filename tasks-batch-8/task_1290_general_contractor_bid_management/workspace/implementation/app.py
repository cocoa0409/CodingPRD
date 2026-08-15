import os

from flask import Flask

import errors as err_mod
from response import error_response
from routes import (
    clock, bid_packages, subcontractors, prequal, invitations,
    addendums, bids, leveling, interviews, recommendations, feedbacks,
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock.bp)
    app.register_blueprint(bid_packages.bp)
    app.register_blueprint(subcontractors.bp)
    app.register_blueprint(prequal.bp)
    app.register_blueprint(invitations.bp)
    app.register_blueprint(addendums.bp)
    app.register_blueprint(bids.bp)
    app.register_blueprint(leveling.bp)
    app.register_blueprint(interviews.bp)
    app.register_blueprint(recommendations.bp)
    app.register_blueprint(feedbacks.bp)

    @app.errorhandler(err_mod.ApiError)
    def handle_api_error(exc: err_mod.ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_):
        return error_response("ERR_RESOURCE_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_):
        return error_response("ERR_RESOURCE_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(500)
    def handle_500(exc):
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
