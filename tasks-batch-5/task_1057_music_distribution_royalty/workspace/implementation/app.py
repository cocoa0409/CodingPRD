"""Music Distribution & Royalty API — Flask entry point.

Storage is in-memory only and starts empty on every boot; nothing is seeded.
"""

import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.catalogue import bp as catalogue_bp
from routes.collaborators import bp as collaborators_bp
from routes.deliveries import bp as deliveries_bp
from routes.payouts import bp as payouts_bp
from routes.releases import bp as releases_bp
from routes.royalty import bp as royalty_bp
from routes.splits import bp as splits_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.tax_forms import bp as tax_forms_bp
from routes.tracks import bp as tracks_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in (
        catalogue_bp,
        subscriptions_bp,
        releases_bp,
        tracks_bp,
        collaborators_bp,
        splits_bp,
        deliveries_bp,
        royalty_bp,
        payouts_bp,
        tax_forms_bp,
    ):
        app.register_blueprint(blueprint)

    # Every request runs to completion before the next begins, so a multi-hop
    # cascade (close, takedown) is observed atomically.
    request_lock = threading.RLock()

    @app.before_request
    def _acquire():
        request_lock.acquire()
        g._holds_lock = True

    @app.teardown_request
    def _release(_exc=None):
        if g.pop("_holds_lock", False):
            request_lock.release()

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            return error_response(
                "ERR_RESOURCE_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_RESOURCE_NOT_FOUND", "Method not allowed for this resource.", 404
            )
        if exc.code == 400:
            return error_response("ERR_VALIDATION", "The request could not be parsed.", 400)
        return error_response("ERR_VALIDATION", exc.description or "Request failed.", exc.code)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_VALIDATION", "Unexpected server error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
