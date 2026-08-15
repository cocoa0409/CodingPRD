"""Entry point: Flask app, error handlers, route registration."""
import os
from flask import Flask
import db
import errors
from errors import ApiError
from response import error_response

from routes.asset_classes import bp as asset_classes_bp
from routes.capital_projects import bp as capital_projects_bp
from routes.fixed_assets import bp as fixed_assets_bp
from routes.depreciation_runs import bp as depreciation_runs_bp
from routes.disposals import bp as disposals_bp
from routes.inventory_runs import bp as inventory_runs_bp
from routes.impairment_reviews import bp as impairment_reviews_bp
from routes.external_schedules import bp as external_schedules_bp

app = Flask(__name__)

# Guarantee the store is empty on every fresh boot
db.reset_all()

app.register_blueprint(asset_classes_bp)
app.register_blueprint(capital_projects_bp)
app.register_blueprint(fixed_assets_bp)
app.register_blueprint(depreciation_runs_bp)
app.register_blueprint(disposals_bp)
app.register_blueprint(inventory_runs_bp)
app.register_blueprint(impairment_reviews_bp)
app.register_blueprint(external_schedules_bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    e = errors.not_found("Route not found")
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(405)
def handle_405(err):
    e = errors.not_found("Method not allowed")
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    e = errors.invalid_request(str(err))
    return error_response(e.error_id, e.message, 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
