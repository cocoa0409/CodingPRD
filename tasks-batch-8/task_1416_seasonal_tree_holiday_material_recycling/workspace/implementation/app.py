"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from http_util import ApiError, err


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    from routes_a import bp as bp_core
    from routes_b import bp as bp_ops

    app.register_blueprint(bp_core)
    app.register_blueprint(bp_ops)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return err("ERR_NOT_FOUND", 404, "Referenced resource does not exist")

    @app.errorhandler(405)
    def handle_405(e):
        return err("ERR_NOT_FOUND", 404, "Referenced resource does not exist")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return err("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
