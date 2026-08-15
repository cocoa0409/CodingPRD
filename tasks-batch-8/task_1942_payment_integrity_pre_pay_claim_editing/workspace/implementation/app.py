"""Payment Integrity Editing API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes import (
        claims,
        clock,
        disputes,
        edit_hits,
        edits,
        ibr,
        inpatient_reviews,
        providers,
        review_tasks,
        savings_periods,
        vendor_edits,
    )

    app.register_blueprint(providers.bp)
    app.register_blueprint(edits.bp)
    app.register_blueprint(vendor_edits.bp)
    app.register_blueprint(claims.bp)
    app.register_blueprint(edit_hits.bp)
    app.register_blueprint(review_tasks.bp)
    app.register_blueprint(disputes.bp)
    app.register_blueprint(ibr.bp)
    app.register_blueprint(inpatient_reviews.bp)
    app.register_blueprint(savings_periods.bp)
    app.register_blueprint(clock.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response("ERR_INVALID_REQUEST", 404, "Route not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response("ERR_INVALID_REQUEST", 405, "Method not allowed")

    @app.errorhandler(500)
    def handle_internal(err):
        return error_response("ERR_INVALID_REQUEST", 500, "Internal error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
