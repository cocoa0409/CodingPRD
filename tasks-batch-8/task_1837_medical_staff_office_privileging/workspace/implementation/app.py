"""Medical Staff Privileging API — Flask entry point."""
import os

from flask import Flask, jsonify

import errors
from errors import ApiError
from response import err_body
from routes import (agenda, applications, cases, clock, credentials, criteria,
                    delineations, grants, members, metrics, npdb, panels,
                    reviews, temp, verification)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (clock.bp, criteria.bp, members.bp, applications.bp,
               verification.bp, delineations.bp, grants.bp, reviews.bp,
               metrics.bp, credentials.bp, temp.bp, cases.bp, panels.bp,
               npdb.bp, agenda.bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(err_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_404(_exc):
        return jsonify(err_body(errors.ERR_NOT_FOUND,
                                "Resource not found")), 404

    @app.errorhandler(405)
    def handle_405(_exc):
        return jsonify(err_body(errors.ERR_NOT_FOUND,
                                "Method not allowed")), 404

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        app.logger.exception("Unhandled error: %s", exc)
        return jsonify(err_body(errors.ERR_INVALID_REQUEST,
                                "Internal error")), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
