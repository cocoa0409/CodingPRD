"""Epoxy Garage-Floor Coating API — Flask entry point.

In-memory only. State is wiped on every fresh process boot. No seeding.
"""
import os

from flask import Flask

from errors import ApiError
from response import error
from routes.catalogs import bp as catalogs_bp
from routes.customers import bp as customers_bp
from routes.projects import bp as projects_bp
from routes.quotes import bp as quotes_bp
from routes.install_jobs import bp as install_jobs_bp
from routes.warranties import bp as warranties_bp
from routes.claims import bp as claims_bp
from routes.referrals import bp as referrals_bp
from routes.clock import bp as clock_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(clock_bp)
app.register_blueprint(catalogs_bp)
app.register_blueprint(customers_bp)
app.register_blueprint(projects_bp)
app.register_blueprint(quotes_bp)
app.register_blueprint(install_jobs_bp)
app.register_blueprint(warranties_bp)
app.register_blueprint(claims_bp)
app.register_blueprint(referrals_bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(400)
def handle_400(e):
    return error("ERR_VALIDATION", 400, "Bad request")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
