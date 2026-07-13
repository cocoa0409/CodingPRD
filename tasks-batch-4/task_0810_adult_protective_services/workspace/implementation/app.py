"""Adult Protective Services API — entry point, clock endpoint, error handling."""
import os

from flask import Flask, jsonify

from store import store
from errors import ApiError
from envelope import success, error_body
from helpers import authenticate, authorize, get_body, require_str, parse_dt

from bp_reports import bp as reports_bp
from bp_clients import bp as clients_bp
from bp_accounts import bp as accounts_bp
from bp_cases import bp as cases_bp
from bp_investigations import bp as investigations_bp
from bp_placements import bp as placements_bp
from bp_freezes import bp as freezes_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for _bp in (reports_bp, clients_bp, accounts_bp, cases_bp, investigations_bp,
            placements_bp, freezes_bp):
    app.register_blueprint(_bp)


@app.post("/_clock/set_current_utc")
def set_clock():
    uid, role = authenticate()
    authorize(role, {"Admin"})
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    store.clock = parse_dt(to_iso, "to_iso8601")
    return jsonify(success({}, "object")), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


@app.errorhandler(404)
def handle_404(_err):
    return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(405)
def handle_405(_err):
    return jsonify(error_body("ERR_METHOD_NOT_ALLOWED", "Method not allowed")), 405


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
