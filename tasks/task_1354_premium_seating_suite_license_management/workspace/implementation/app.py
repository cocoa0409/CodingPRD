"""Premium Seating & Suite Licensing API — Flask entry point."""
import os

from flask import Flask

import errors
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.core import bp as core_bp
    from routes.finance import bp as finance_bp
    from routes.ops import bp as ops_bp
    from routes.sales import bp as sales_bp
    for bp in (core_bp, finance_bp, ops_bp, sales_bp):
        app.register_blueprint(bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(errors.err_not_found())

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(errors.err_not_found())

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, errors.ApiError):
            return error_response(err)
        app.logger.exception("unexpected error")
        return error_response(errors.err_invalid_request(str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
