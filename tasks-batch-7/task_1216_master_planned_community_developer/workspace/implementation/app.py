"""Master-Planned Community Developer Operations API — Flask entry point."""
import os

from flask import Flask

from core import ApiError, error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Route not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INTERNAL", 500, str(e))

    import routes_core
    import routes_agreements
    import routes_finance
    import routes_district
    import routes_design
    import routes_lifestyle

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_agreements.bp)
    app.register_blueprint(routes_finance.bp)
    app.register_blueprint(routes_district.bp)
    app.register_blueprint(routes_design.bp)
    app.register_blueprint(routes_lifestyle.bp)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
