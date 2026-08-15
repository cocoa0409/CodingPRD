"""Debate & Speech Tournament Management API — Flask entrypoint."""
import os
import traceback

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, db, error_response, make_meta

app = Flask(__name__)

import routes_a  # noqa: E402  (tournaments, clock, schools, divisions)
import routes_b  # noqa: E402  (entries, judges, judge-conflicts, rooms)
import routes_c  # noqa: E402  (rounds, pairings, pairing-entries)
import routes_d  # noqa: E402  (ballots, hired-judge-contracts, logistics-orders)

app.register_blueprint(routes_a.bp)
app.register_blueprint(routes_b.bp)
app.register_blueprint(routes_c.bp)
app.register_blueprint(routes_d.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(HTTPException)
def handle_http_error(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": err.description or "Not found"},
    }
    return jsonify(body), err.code or 404


@app.errorhandler(Exception)
def handle_unexpected(err):
    traceback.print_exc()
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": "Internal server error"},
    }
    return jsonify(body), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
