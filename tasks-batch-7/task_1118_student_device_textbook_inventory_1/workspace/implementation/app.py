"""Entry point: Flask app assembly, error handlers, route registration."""
import os

from flask import Flask, jsonify

from core import ApiError, error_body
import routes_programs
import routes_assets
import routes_students
import routes_assignments
import routes_fees
import routes_loaners
import routes_sweeps
import routes_flat

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (routes_programs, routes_assets, routes_students,
               routes_assignments, routes_fees, routes_loaners,
               routes_sweeps, routes_flat):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


@app.errorhandler(404)
def handle_404(err):
    return jsonify(error_body("ERR_NOT_FOUND", "The requested resource does not exist")), 404


@app.errorhandler(405)
def handle_405(err):
    return jsonify(error_body("ERR_INVALID_REQUEST", "Method not allowed")), 405


@app.errorhandler(500)
def handle_500(err):
    return jsonify(error_body("ERR_INTERNAL", "Internal server error")), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
