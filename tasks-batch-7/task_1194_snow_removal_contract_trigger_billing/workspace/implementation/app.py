"""Main Flask application entry point."""
import os
from flask import Flask
from errors import ApiError
from response import error_response

app = Flask(__name__)

# Register blueprints
from routes.clock import bp as clock_bp
from routes.clients import bp as clients_bp
from routes.sites import bp as sites_bp
from routes.contracts import bp as contracts_bp
from routes.contract_sites import bp as contract_sites_bp
from routes.amendments import bp as amendments_bp
from routes.storm_events import bp as storm_events_bp
from routes.observations import bp as observations_bp
from routes.visits import bp as visits_bp
from routes.materials import bp as materials_bp
from routes.photos import bp as photos_bp
from routes.invoices import bp as invoices_bp
from routes.disputes import bp as disputes_bp
from routes.claims import bp as claims_bp
from routes.subcontractors import bp as subcontractors_bp
from routes.coverage import bp as coverage_bp
from routes.true_ups import bp as true_ups_bp

app.register_blueprint(clock_bp)
app.register_blueprint(clients_bp)
app.register_blueprint(sites_bp)
app.register_blueprint(contracts_bp)
app.register_blueprint(contract_sites_bp)
app.register_blueprint(amendments_bp)
app.register_blueprint(storm_events_bp)
app.register_blueprint(observations_bp)
app.register_blueprint(visits_bp)
app.register_blueprint(materials_bp)
app.register_blueprint(photos_bp)
app.register_blueprint(invoices_bp)
app.register_blueprint(disputes_bp)
app.register_blueprint(claims_bp)
app.register_blueprint(subcontractors_bp)
app.register_blueprint(coverage_bp)
app.register_blueprint(true_ups_bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_not_found(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(500)
def handle_internal_error(e):
    return error_response("ERR_INVALID_REQUEST", str(e), 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
