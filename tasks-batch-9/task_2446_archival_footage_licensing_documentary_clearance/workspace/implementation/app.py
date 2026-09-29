"""Archival Footage Licensing & Documentary Clearance API.

Flask + in-memory dict storage.  The store is empty on every boot: no seeding,
no fixtures, no persistence of any kind.
"""
import os

from flask import Flask, jsonify

from core import ApiError, _meta, error_response
import routes_archive
import routes_asset
import routes_insurance
import routes_legal
import routes_license
import routes_production
import routes_release


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (routes_production, routes_archive, routes_asset, routes_license,
                   routes_legal, routes_release, routes_insurance):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "The method is not allowed for this route.", 405)

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return error_response("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    @app.get("/_health")
    def health():
        return jsonify({"meta": _meta(), "response_type": "object",
                        "data": {"status": "ok"}}), 200

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
