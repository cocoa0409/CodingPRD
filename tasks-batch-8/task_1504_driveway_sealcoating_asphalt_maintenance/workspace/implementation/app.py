"""Driveway Sealcoating & Asphalt Maintenance API — Flask application entry point."""

import os
from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ERR_INVALID_REQUEST, "Route not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response(ERR_INVALID_REQUEST, "Method not allowed", 405)


@app.errorhandler(500)
def handle_500(e):
    return error_response(ERR_INVALID_REQUEST, f"Internal error: {e}", 500)


# Register route blueprints
from routes.customers import bp as customers_bp
from routes.properties import bp as properties_bp
from routes.assessments import bp as assessments_bp
from routes.materials import bp as materials_bp
from routes.material_lots import bp as material_lots_bp
from routes.crews import bp as crews_bp
from routes.route_sheets import bp as route_sheets_bp
from routes.quotes import bp as quotes_bp
from routes.work_orders import bp as work_orders_bp
from routes.displacement_plans import bp as displacement_plans_bp
from routes.invoices import bp as invoices_bp
from routes.warranty import bp as warranty_bp
from routes.weather import bp as weather_bp
from routes.clock_admin import bp as clock_bp

app.register_blueprint(customers_bp)
app.register_blueprint(properties_bp)
app.register_blueprint(assessments_bp)
app.register_blueprint(materials_bp)
app.register_blueprint(material_lots_bp)
app.register_blueprint(crews_bp)
app.register_blueprint(route_sheets_bp)
app.register_blueprint(quotes_bp)
app.register_blueprint(work_orders_bp)
app.register_blueprint(displacement_plans_bp)
app.register_blueprint(invoices_bp)
app.register_blueprint(warranty_bp)
app.register_blueprint(weather_bp)
app.register_blueprint(clock_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
