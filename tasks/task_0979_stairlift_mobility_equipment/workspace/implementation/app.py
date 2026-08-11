"""Entry point: Flask app, error handlers, route registration."""

import os

try:
    from flask import Flask
except ImportError:  # pragma: no cover - first-boot dependency install
    import subprocess
    import sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-r",
                           os.path.join(os.path.dirname(__file__),
                                        "requirements.txt")])
    from flask import Flask

from errors import ApiError, err_not_found
from response import error_response


def create_app():
    app = Flask(__name__)

    from routes.customers import bp as customers_bp
    from routes.home_assessments import bp as assessments_bp
    from routes.product_models import bp as models_bp
    from routes.equipment_units import bp as units_bp
    from routes.quotes import bp as quotes_bp
    from routes.funding import bp as funding_bp
    from routes.agreements import bp as agreements_bp
    from routes.install_jobs import bp as install_bp
    from routes.service_plans import bp as plans_bp
    from routes.warranty_claims import bp as claims_bp
    from routes.removal_jobs import bp as removal_bp
    from routes.misc import bp as misc_bp

    for bp in (customers_bp, assessments_bp, models_bp, units_bp, quotes_bp,
               funding_bp, agreements_bp, install_bp, plans_bp, claims_bp,
               removal_bp, misc_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(err_not_found("Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(err_not_found("Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Never leak a 500 stack as HTML; normalize to a 400-invalid-request-ish
        # envelope only when truly unexpected. Log to stderr for debugging.
        import traceback
        traceback.print_exc()
        return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
