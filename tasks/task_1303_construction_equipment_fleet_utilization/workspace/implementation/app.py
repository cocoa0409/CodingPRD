import os

from flask import Flask

from errors import ApiError
from response import err, ok
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e)

    @app.errorhandler(404)
    def handle_404(e):
        return err(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return err(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_generic(e):
        if isinstance(e, ApiError):
            return err(e)
        return err(ApiError("ERR_INTERNAL", 500, str(e)))

    @app.get("/")
    def root():
        return ok({"service": "equipment-fleet", "status": "up"}, "object", 200)

    register_routes(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
