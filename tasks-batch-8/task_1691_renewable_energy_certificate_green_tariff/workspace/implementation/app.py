"""Green power registry API — entry point.

In-memory only: every store lives in process memory, so a fresh process
starts with completely empty state. The logical clock starts at exactly
2026-08-01T00:00:00Z and only moves via POST /greenpower/_clock/set_current_utc.
"""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from util import error_response, _meta

app = Flask(__name__)

from routes.generators import bp as generators_bp
from routes.readings import bp as readings_bp
from routes.accounts import bp as accounts_bp
from routes.certificates import bp as certificates_bp
from routes.trades import bp as trades_bp
from routes.programs import bp as programs_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.bills import bp as bills_bp
from routes.retirements import bp as retirements_bp
from routes.obligations import bp as obligations_bp
from routes.reports import bp as reports_bp
from routes.clock import bp as clock_bp

for bp in (generators_bp, readings_bp, accounts_bp, certificates_bp, trades_bp,
           programs_bp, subscriptions_bp, bills_bp, retirements_bp,
           obligations_bp, reports_bp, clock_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": ERR_NOT_FOUND[0], "message": "Resource not found"},
    }
    from flask import jsonify
    return jsonify(body), 404


@app.errorhandler(400)
def handle_400(err):
    # Malformed JSON or bad request at the Flask layer.
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": ERR_VALIDATION[0], "message": "Bad request"},
    }
    from flask import jsonify
    return jsonify(body), 400


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": ERR_NOT_FOUND[0], "message": "Method not allowed"},
    }
    from flask import jsonify
    return jsonify(body), 404


@app.errorhandler(Exception)
def handle_unexpected(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": ERR_VALIDATION[0],
                 "message": "Unexpected server error: %s" % err},
    }
    from flask import jsonify
    return jsonify(body), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
