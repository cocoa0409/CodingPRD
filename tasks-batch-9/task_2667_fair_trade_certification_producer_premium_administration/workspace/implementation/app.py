"""Fair Trade Certification & Producer Premium Administration API.

Every endpoint is mounted beneath the /fairtrade prefix (PRD 2.0). Storage is
in-memory only and starts completely empty on every boot: nothing is seeded,
preloaded or hardcoded here.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import routes_audits
import routes_committees
import routes_holders
import routes_marks
import routes_nodes
import routes_proposals
import routes_reports
import routes_system
import routes_transactions
from errors import ApiError
from response import error_body

PREFIX = "/fairtrade"

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

for module in (routes_holders, routes_nodes, routes_committees,
               routes_transactions, routes_reports, routes_proposals,
               routes_audits, routes_marks, routes_system):
    app.register_blueprint(module.bp, url_prefix=PREFIX)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    if exc.code == 404:
        return jsonify(error_body("ERR_NOT_FOUND", "no such route")), 404
    if exc.code == 405:
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  "method not allowed on this route")), 405
    if exc.code in (400, 415):
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  "malformed request")), 400
    return jsonify(error_body("ERR_INTERNAL", exc.description or "error")), \
        exc.code or 500


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return jsonify(error_body("ERR_INTERNAL", "%s" % exc)), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
