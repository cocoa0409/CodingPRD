"""Flask entrypoint for the corporate renewable PPA origination service.

The store lives in plain Python dicts and is empty on every boot: no entity is
ever seeded, preloaded or hardcoded here.
"""
import os

from flask import Flask

from core import ApiError, error_body
import routes_a
import routes_b
import routes_c


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_a.bp)
    app.register_blueprint(routes_b.bp)
    app.register_blueprint(routes_c.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_body(err)

    @app.errorhandler(404)
    def handle_404(_err):
        return error_body(ApiError("ERR_NOT_FOUND", "no such route", 404))

    @app.errorhandler(405)
    def handle_405(_err):
        return error_body(ApiError("ERR_INVALID_REQUEST",
                                   "method not allowed for this route", 405))

    @app.errorhandler(400)
    def handle_400(_err):
        return error_body(ApiError("ERR_INVALID_REQUEST",
                                   "malformed request body", 400))

    @app.errorhandler(500)
    def handle_500(_err):  # pragma: no cover - defensive
        return error_body(ApiError("ERR_INVALID_REQUEST",
                                   "internal error", 500))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
