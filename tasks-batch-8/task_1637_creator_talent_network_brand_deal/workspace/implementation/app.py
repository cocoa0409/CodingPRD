"""Creator Talent Network API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The store starts empty on every boot;
all state lives in `db` module dicts and the logical clock starts at
2026-08-01T00:00:00Z.
"""

import os

from flask import Flask

import errors as err
import response as resp
from routes import (brands, briefs, clock, creators, deals, deliverables,
                    disclosure_checks, disputes, invoices, payouts,
                    performance_reports, pitches, reshoots)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (creators.bp, brands.bp, briefs.bp, pitches.bp, deals.bp,
               deliverables.bp, disclosure_checks.bp, performance_reports.bp,
               invoices.bp, payouts.bp, disputes.bp, reshoots.bp, clock.bp):
        app.register_blueprint(bp)

    @app.errorhandler(err.ApiError)
    def handle_api_error(e):
        return resp.error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return resp.error_response(err.not_found("Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return resp.error_response(
            err.ApiError(err.ERR_NOT_FOUND, "Method not allowed", 404))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, err.ApiError):
            return resp.error_response(e)
        app.logger.exception("unexpected error")
        return resp.error_response(
            err.ApiError(err.ERR_VALIDATION, str(e), 400))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
