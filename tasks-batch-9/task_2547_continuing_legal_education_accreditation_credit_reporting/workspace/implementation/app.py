"""Continuing Legal Education Accreditation & Credit Reporting API."""
import os

from flask import Flask, jsonify

import db
import response
from errors import ApiError
from routes.attorneys import bp as attorneys_bp
from routes.audits import bp as audits_bp
from routes.clock import bp as clock_bp
from routes.complaints import bp as complaints_bp
from routes.courses import bp as courses_bp
from routes.credits import bp as credits_bp
from routes.cycles import bp as cycles_bp
from routes.fees import bp as fees_bp
from routes.providers import bp as providers_bp
from routes.reciprocity import bp as reciprocity_bp
from routes.sweeps import bp as sweeps_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for blueprint in (
    clock_bp,
    providers_bp,
    courses_bp,
    attorneys_bp,
    cycles_bp,
    credits_bp,
    reciprocity_bp,
    audits_bp,
    complaints_bp,
    fees_bp,
    sweeps_bp,
):
    app.register_blueprint(blueprint)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return jsonify(response.error_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(404)
def handle_404(_exc):
    return jsonify(response.error_body("ERR_INVALID_REQUEST", "Unknown route.")), 404


@app.errorhandler(405)
def handle_405(_exc):
    return jsonify(response.error_body("ERR_INVALID_REQUEST", "Method not allowed.")), 405


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    return (
        jsonify(response.error_body("ERR_INVALID_REQUEST", "Unhandled error: %s" % exc)),
        422,
    )


if __name__ == "__main__":
    db.reset()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
