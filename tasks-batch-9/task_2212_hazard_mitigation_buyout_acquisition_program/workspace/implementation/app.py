"""Hazard Mitigation Buyout / Acquisition Program API.

In-memory only: every process boot starts with completely empty tables and the
logical clock at its cold value. No entity data is seeded, preloaded or
hardcoded anywhere in this package.
"""
import os

from flask import Flask

import routes_appraisal
import routes_closing
import routes_demolition
import routes_ledger
import routes_offer
import routes_parcel
import routes_project
import routes_relocation
import routes_restriction
import web
from core import ApiError, fail, parse_datetime, set_clock


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_project.bp)
    app.register_blueprint(routes_parcel.bp)
    app.register_blueprint(routes_appraisal.bp)
    app.register_blueprint(routes_offer.bp)
    app.register_blueprint(routes_relocation.bp)
    app.register_blueprint(routes_closing.bp)
    app.register_blueprint(routes_demolition.bp)
    app.register_blueprint(routes_restriction.bp)
    app.register_blueprint(routes_ledger.bp)

    @app.post("/_clock/set_current_utc")
    def set_current_utc():
        """Outside the business surface: no authentication, no versioning."""
        body = web.get_body()
        raw = body.get("current_utc")
        if raw is None or not isinstance(raw, str) or raw.strip() == "":
            fail("ERR_INVALID_REQUEST", "Field 'current_utc' is required.")
        parsed = parse_datetime(raw)
        if parsed is None:
            fail("ERR_INVALID_REQUEST", "Field 'current_utc' must be an ISO 8601 UTC instant.")
        set_clock(parsed)
        return web.respond_raw({"current_utc": raw})

    @app.errorhandler(ApiError)
    def on_api_error(err):
        return web.error_response(err)

    @app.errorhandler(404)
    def on_not_found(_err):
        return web.raw_error("ERR_NOT_FOUND", 404, "No such route.")

    @app.errorhandler(405)
    def on_method_not_allowed(_err):
        return web.raw_error("ERR_INVALID_REQUEST", 422,
                             "Method not allowed for this resource.")

    @app.errorhandler(400)
    def on_bad_request(_err):
        return web.raw_error("ERR_INVALID_REQUEST", 422, "Request body is not valid JSON.")

    @app.errorhandler(415)
    def on_unsupported_media(_err):
        return web.raw_error("ERR_INVALID_REQUEST", 422, "Request body must be JSON.")

    @app.errorhandler(500)
    def on_internal(_err):
        return web.raw_error("ERR_INVALID_REQUEST", 422, "The request could not be processed.")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
