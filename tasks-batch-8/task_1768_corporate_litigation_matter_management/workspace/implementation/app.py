"""Corporate Litigation Matters API — Flask entry point."""
import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import err_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return err_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return err_response(ERR_NOT_FOUND[0], 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(err):
        return err_response(ERR_NOT_FOUND[0], 404, "Resource not found.")

    @app.errorhandler(400)
    def handle_400(err):
        return err_response(ERR_INVALID_REQUEST[0], 400, "Malformed request.")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return err_response(ERR_INVALID_REQUEST[0], 400, "Malformed request.")

    import routes_a
    import routes_b
    import routes_c
    import routes_d
    import routes_e

    routes_a.register(app)
    routes_b.register(app)
    routes_c.register(app)
    routes_d.register(app)
    routes_e.register(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
