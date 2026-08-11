"""Aircraft Title, Escrow & Registration Service — Flask application entry point."""

import os
import sys

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)

# Register blueprints
from routes.clock import bp as clock_bp
from routes.aircraft import bp as aircraft_bp
from routes.parties import bp as parties_bp
from routes.escrow_files import bp as escrow_files_bp
from routes.title_searches import bp as title_searches_bp
from routes.liens import bp as liens_bp
from routes.releases import bp as releases_bp
from routes.deposits import bp as deposits_bp
from routes.disbursements import bp as disbursements_bp
from routes.filings import bp as filings_bp
from routes.trust_agreements import bp as trust_agreements_bp
from routes.documents import bp as documents_bp

app.register_blueprint(clock_bp)
app.register_blueprint(aircraft_bp)
app.register_blueprint(parties_bp)
app.register_blueprint(escrow_files_bp)
app.register_blueprint(title_searches_bp)
app.register_blueprint(liens_bp)
app.register_blueprint(releases_bp)
app.register_blueprint(deposits_bp)
app.register_blueprint(disbursements_bp)
app.register_blueprint(filings_bp)
app.register_blueprint(trust_agreements_bp)
app.register_blueprint(documents_bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_not_found(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(500)
def handle_internal_error(e):
    return error_response("ERR_INTERNAL", str(e), 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
