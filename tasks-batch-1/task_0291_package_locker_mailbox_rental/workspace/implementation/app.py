"""Package Locker & Mailbox Rental API — Flask entry point.

In-memory storage only; the store starts empty on every boot (no seeding).
"""
import os

from flask import Flask, request

from errors import ApiError
from response import error_response
from middleware import authenticate

from routes.facilities import bp as facilities_bp
from routes.lockers import bp as lockers_bp
from routes.mailboxes import bp as mailboxes_bp
from routes.customers import bp as customers_bp
from routes.forms import bp as forms_bp
from routes.agreements import bp as agreements_bp
from routes.packages import bp as packages_bp
from routes.mail import bp as mail_bp
from routes.billing import bp as billing_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (facilities_bp, lockers_bp, mailboxes_bp, customers_bp, forms_bp,
           agreements_bp, packages_bp, mail_bp, billing_bp):
    app.register_blueprint(bp)


@app.before_request
def _auth():
    # Authentication runs first for every API request (PRD §2.10).
    if request.method == "OPTIONS":
        return None
    try:
        authenticate()
    except ApiError as e:
        return error_response(e.error_id, e.http_status, e.message)
    return None


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def _handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def _handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    return error_response("ERR_INVALID_REQUEST", 422, str(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
