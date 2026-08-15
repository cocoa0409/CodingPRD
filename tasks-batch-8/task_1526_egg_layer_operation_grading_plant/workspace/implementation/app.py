"""Entry point: Flask app, error handlers, blueprint registration.

The store is in-memory only and starts empty on every boot (PRD build
contract: per-test-server isolation re-launches start.sh before every test).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INTERNAL
from response import err_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.core import bp as core_bp
    from routes.flocks import bp as flocks_bp
    from routes.production import bp as production_bp
    from routes.grading import bp as grading_bp
    from routes.contracts import bp as contracts_bp
    from routes.compliance import bp as compliance_bp
    from routes.dispositions import bp as dispositions_bp

    for bp in (core_bp, flocks_bp, production_bp, grading_bp,
               contracts_bp, compliance_bp, dispositions_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return err_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return err_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return err_response(ERR_INTERNAL, 500, str(e))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
