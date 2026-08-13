"""Flask application entry point."""
import os
from flask import Flask, jsonify
from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from response import error as error_response

from routes.accounts import bp as accounts_bp
from routes.products import bp as products_bp
from routes.trucks import bp as trucks_bp
from routes.projects import bp as projects_bp
from routes.takeoffs import bp as takeoffs_bp
from routes.orders import bp as orders_bp
from routes.draws import bp as draws_bp
from routes.returns import bp as returns_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(accounts_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(trucks_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(takeoffs_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(draws_bp)
    app.register_blueprint(returns_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ERR_NOT_FOUND, "Not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_exception(e):
        import traceback
        traceback.print_exc()
        return error_response(ERR_VALIDATION, f"Internal error: {e}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    import time

    port = int(os.environ.get("PORT", "10000"))
    # Under per-test-server isolation the runner SIGKILLs the previous server
    # and immediately spawns a new one on the same port. If the killed process
    # has not been reaped yet, the first bind attempt hits EADDRINUSE; retry
    # for a bounded window instead of crashing (which surfaces as a spurious
    # "could not be restarted" after the runner's poll window expires).
    for _attempt in range(60):  # up to ~30s
        try:
            app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
            break
        except OSError:
            time.sleep(0.5)
    else:
        raise SystemExit(f"Could not bind port {port} after retries")
