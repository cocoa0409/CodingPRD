"""Real Estate Commission Licensing & Discipline API - entry point.

In-memory only: every dict in store.py lives in this process and dies with it,
so a fresh `bash start.sh` starts from an empty register (plus the mandatory
RecoveryFund singleton of PRD 2.4, which is system initialisation and not
entity seeding).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import routes_discipline
import routes_education
import routes_fund
import routes_licensing
import routes_read
import routes_trust
import store
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_read.bp)
app.register_blueprint(routes_licensing.bp)
app.register_blueprint(routes_trust.bp)
app.register_blueprint(routes_discipline.bp)
app.register_blueprint(routes_fund.bp)
app.register_blueprint(routes_education.bp)


@app.errorhandler(ApiError)
def _api_error(exc):
    return envelope.error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _http_error(exc):
    if exc.code == 404:
        return envelope.error("ERR_NOT_FOUND", "No such route.", 404)
    if exc.code == 405:
        return envelope.error("ERR_METHOD_NOT_ALLOWED",
                              "Method not allowed on this route.", 405)
    if exc.code == 400:
        return envelope.error("ERR_INVALID_REQUEST",
                              "The request body could not be parsed.", 400)
    return envelope.error("ERR_INVALID_REQUEST", str(exc), exc.code or 400)


@app.errorhandler(Exception)
def _unhandled(exc):
    return envelope.error("ERR_INVALID_REQUEST", "%s: %s" % (type(exc).__name__, exc), 400)


store.bootstrap()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
