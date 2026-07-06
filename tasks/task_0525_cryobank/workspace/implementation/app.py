import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.donors import bp as donors_bp
from routes.screening import bp as screening_bp
from routes.specimens import bp as specimens_bp
from routes.inventories import bp as inventories_bp
from routes.recipients import bp as recipients_bp
from routes.consents import bp as consents_bp
from routes.reservations import bp as reservations_bp
from routes.shipments import bp as shipments_bp
from routes.storage import bp as storage_bp
from routes.sibling import bp as sibling_bp
from routes.scheduling import bp as scheduling_bp
from routes.reports import bp as reports_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        donors_bp, screening_bp, specimens_bp, inventories_bp, recipients_bp,
        consents_bp, reservations_bp, shipments_bp, storage_bp, sibling_bp,
        scheduling_bp, reports_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_uncaught(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % e, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
