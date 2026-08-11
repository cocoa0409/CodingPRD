import os

from flask import Flask

from errors import ApiError
from response import err_resp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import all_blueprints
    for bp in all_blueprints():
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err_resp(e.error_id, e.message, e.status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return err_resp("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return err_resp("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return err_resp("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
