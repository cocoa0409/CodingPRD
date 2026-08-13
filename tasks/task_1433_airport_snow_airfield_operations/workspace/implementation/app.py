"""Entry point: Flask app, route registration, error handlers."""

import os

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


@app.errorhandler(ApiError)
def handle_api_error(e: ApiError):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_generic(e):
    # Pass-through HTTPExceptions already handled above
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return error_response("ERR_HTTP", e.code or 500, e.description or "")
    return error_response("ERR_INTERNAL", 500, str(e))


# Register blueprints
from routes.snow_events import bp as snow_events_bp
from routes.airfield_surfaces import bp as surfaces_bp
from routes.condition_reports import bp as reports_bp
from routes.friction_assessments import bp as assessments_bp
from routes.notams import bp as notams_bp
from routes.chemical_products import bp as products_bp
from routes.chemical_applications import bp as applications_bp
from routes.equipment_units import bp as equipment_bp
from routes.operator_shifts import bp as shifts_bp
from routes.clock import bp as clock_bp

app.register_blueprint(snow_events_bp)
app.register_blueprint(surfaces_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(assessments_bp)
app.register_blueprint(notams_bp)
app.register_blueprint(products_bp)
app.register_blueprint(applications_bp)
app.register_blueprint(equipment_bp)
app.register_blueprint(shifts_bp)
app.register_blueprint(clock_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
