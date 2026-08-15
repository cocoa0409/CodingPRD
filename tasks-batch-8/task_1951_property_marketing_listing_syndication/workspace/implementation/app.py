"""Property Marketing & Listing Syndication API — entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.agents import bp as agents_bp
    from routes.listings import bp as listings_bp
    from routes.media import bp as media_bp
    from routes.compliance import bp as compliance_bp
    from routes.portals import bp as portals_bp
    from routes.subscriptions import bp as subscriptions_bp
    from routes.feed_events import bp as feed_events_bp
    from routes.showings import bp as showings_bp
    from routes.admin import bp as admin_bp

    for module_bp in (agents_bp, listings_bp, media_bp, compliance_bp,
                      portals_bp, subscriptions_bp, feed_events_bp,
                      showings_bp, admin_bp):
        app.register_blueprint(module_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        status = err.code or 500
        error_id = ERR_INVALID_REQUEST if status == 400 else "ERR_INTERNAL"
        return error_response(error_id, err.description, status)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
