"""Flask application entry point."""
import os
from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)

# Register blueprints
from routes.clock import clock_bp
from routes.issuers import issuers_bp
from routes.blackout_windows import blackout_bp
from routes.reporting_persons import persons_bp
from routes.transactions import transactions_bp
from routes.filings import filings_bp
from routes.trading_plans import plans_bp
from routes.beneficial_holders import holders_bp
from routes.annual_sweeps import sweeps_bp
from routes.filing_agent_authorizations import auth_bp

app.register_blueprint(clock_bp)
app.register_blueprint(issuers_bp)
app.register_blueprint(blackout_bp)
app.register_blueprint(persons_bp)
app.register_blueprint(transactions_bp)
app.register_blueprint(filings_bp)
app.register_blueprint(plans_bp)
app.register_blueprint(holders_bp)
app.register_blueprint(sweeps_bp)
app.register_blueprint(auth_bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 405)


@app.errorhandler(500)
def handle_500(e):
    return error_response("ERR_INTERNAL", "Internal server error.", 500)


if __name__ == "__main__":
    import time

    port = int(os.environ.get("PORT", "10000"))
    # Under per-test-server isolation the runner kill -9s the previous server
    # and immediately spawns a new one; under parallel load the old listener
    # can take a moment to release the port, so retry the bind instead of
    # dying with EADDRINUSE (the runner polls for readiness the whole time).
    for _attempt in range(60):
        try:
            app.run(host="0.0.0.0", port=port, debug=False)
            break
        except OSError:
            time.sleep(0.5)
