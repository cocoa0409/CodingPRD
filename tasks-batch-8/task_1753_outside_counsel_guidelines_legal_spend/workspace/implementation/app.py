"""Outside Counsel Spend API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). Store starts empty on every boot.
"""

import os

from flask import Flask

from errors import ApiError
import errors as err
import response as resp
from routes import (
    departments,
    panel_firms,
    guidelines,
    matters,
    rate_cards,
    timekeepers,
    invoices,
    accruals,
    scorecards,
    clock,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        departments.bp,
        panel_firms.bp,
        guidelines.bp,
        matters.bp,
        rate_cards.bp,
        timekeepers.bp,
        invoices.bp,
        accruals.bp,
        scorecards.bp,
        clock.bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return resp.error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return resp.error_response(err.not_found())

    @app.errorhandler(405)
    def handle_405(e):
        return resp.error_response(err.not_found())

    @app.errorhandler(500)
    def handle_500(e):
        return resp.error_response(ApiError(
            err.ERR_INVALID_STATE, f"Internal error: {getattr(e, 'description', e)}", 500
        ))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
