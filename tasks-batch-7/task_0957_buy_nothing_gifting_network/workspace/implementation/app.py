import os

from flask import Flask

from errors import ApiError, ERROR_HTTP
from response import error_response, ok
from routes import (
    members, groups, memberships, gift_posts, claims, pickup_plans,
    wishlists, curb_alerts, reports, moderation, reputation, clock,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (members, groups, memberships, gift_posts, claims,
                   pickup_plans, wishlists, curb_alerts, reports, moderation,
                   reputation, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_response(ApiError("ERR_NOT_FOUND", ERROR_HTTP["ERR_NOT_FOUND"],
                                       "resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_response(ApiError("ERR_NOT_FOUND", ERROR_HTTP["ERR_NOT_FOUND"],
                                       "method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(ApiError("ERR_VALIDATION", 400, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
