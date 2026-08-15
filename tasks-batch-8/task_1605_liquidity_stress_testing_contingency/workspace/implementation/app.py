"""Entry point: Flask app, error handlers, blueprint registration."""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from responses import err


def create_app():
    app = Flask(__name__)

    import routes_core
    import routes_risk
    import routes_playbooks

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_risk.bp)
    app.register_blueprint(routes_playbooks.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return err(ERR_NOT_FOUND, 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(e):
        return err(ERR_NOT_FOUND, 404, "Resource not found.")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return err("ERR_INTERNAL", 500, f"Internal server error: {e}")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
