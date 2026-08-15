"""Entry point: Flask app, error handlers, route registration.

Store starts empty on every boot — no seeding (per benchmark contract).
"""

import os

from flask import Flask

import response
from errors import ApiError
from routes.donors_memberships import bp as donors_bp
from routes.drives import bp as drives_bp
from routes.levels_premiums import bp as levels_bp
from routes.nffs_clock import bp as nffs_bp
from routes.pledges import bp as pledges_bp
from routes.reservations import bp as reservations_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(levels_bp)
app.register_blueprint(donors_bp)
app.register_blueprint(drives_bp)
app.register_blueprint(pledges_bp)
app.register_blueprint(reservations_bp)
app.register_blueprint(nffs_bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return response.error(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return response.error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return response.error("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_exception(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return response.error("ERR_INVALID_REQUEST", str(err), 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
