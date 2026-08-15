"""USDA-Inspected Meat Processing & HACCP API — Flask entry point."""

import os
from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)

# Register blueprints
from routes.plants import bp as plants_bp
from routes.haccp import bp as haccp_bp
from routes.observations_deviations import bp as obs_dev_bp
from routes.shifts_days import bp as shifts_days_bp
from routes.lots import bp as lots_bp
from routes.labels import bp as labels_bp
from routes.finished_lots import bp as finished_lots_bp
from routes.audits_nrs_recalls import bp as audits_nrs_recalls_bp
from routes.clock import bp as clock_bp

app.register_blueprint(plants_bp)
app.register_blueprint(haccp_bp)
app.register_blueprint(obs_dev_bp)
app.register_blueprint(shifts_days_bp)
app.register_blueprint(lots_bp)
app.register_blueprint(labels_bp)
app.register_blueprint(finished_lots_bp)
app.register_blueprint(audits_nrs_recalls_bp)
app.register_blueprint(clock_bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(err):
    from errors import ERR_NOT_FOUND
    return error_response(ApiError(ERR_NOT_FOUND[0], "Resource not found", ERR_NOT_FOUND[1]))


@app.errorhandler(405)
def handle_method_not_allowed(err):
    from errors import ERR_NOT_FOUND
    return error_response(ApiError(ERR_NOT_FOUND[0], "Resource not found", ERR_NOT_FOUND[1]))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    # Surface unexpected errors as a generic 400 to avoid leaking internals
    from errors import ERR_INVALID_REQUEST
    return error_response(ApiError(ERR_INVALID_REQUEST[0], str(err), ERR_INVALID_REQUEST[1]))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
