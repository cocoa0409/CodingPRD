"""University Technology Transfer & Licensing API — entry point."""
import os

from flask import Flask

from util import ApiError, error_response
from routes import admin, disclosures, patents, startups, licenses, royalties, compliance


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (admin, disclosures, patents, startups, licenses, royalties, compliance):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ApiError("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError("ERR_INTERNAL", 500, "Internal server error"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
