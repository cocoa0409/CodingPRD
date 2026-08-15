"""Entry point: Flask app, error handlers, route registration."""

import os
from flask import Flask
from errors import ApiError, make_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

app = Flask(__name__)

# Register blueprints
from routes.state_rules import bp as state_rules_bp
from routes.associations import bp as associations_bp
from routes.studies import bp as studies_bp
from routes.components import bp as components_bp
from routes.funding_plans import bp as funding_plans_bp
from routes.site_visits import bp as site_visits_bp
from routes.expenditures import bp as expenditures_bp
from routes.disclosures import bp as disclosures_bp
from routes.clock import bp as clock_bp

app.register_blueprint(state_rules_bp)
app.register_blueprint(associations_bp)
app.register_blueprint(studies_bp)
app.register_blueprint(components_bp)
app.register_blueprint(funding_plans_bp)
app.register_blueprint(site_visits_bp)
app.register_blueprint(expenditures_bp)
app.register_blueprint(disclosures_bp)
app.register_blueprint(clock_bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_not_found(e):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_response(ERR_NOT_FOUND, "Method not allowed", 404)


@app.errorhandler(400)
def handle_bad_request(e):
    return error_response(ERR_INVALID_REQUEST, "Bad request", 400)


@app.errorhandler(500)
def handle_internal_error(e):
    return error_response("ERR_INTERNAL", str(e), 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
