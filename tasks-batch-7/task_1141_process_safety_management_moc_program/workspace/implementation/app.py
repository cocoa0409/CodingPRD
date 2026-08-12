"""Process Safety MOC API — Flask entry point."""
import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from helpers import error_response

app = Flask(__name__)

from routes_core import bp as core_bp
from routes_moc import bp as moc_bp
from routes_pha import bp as pha_bp
from routes_pssr import bp as pssr_bp
from routes_actions import bp as actions_bp
from routes_safety import bp as safety_bp
from routes_training import bp as training_bp
from routes_extensions import bp as extensions_bp

for bp in (core_bp, moc_bp, pha_bp, pssr_bp, actions_bp, safety_bp, training_bp, extensions_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError(ERR_INVALID_REQUEST, "Route not found", 404))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError(ERR_INVALID_REQUEST, "Method not allowed", 405))


@app.errorhandler(500)
def handle_500(err):
    return error_response(ApiError(ERR_INVALID_REQUEST, "Internal server error", 500))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
