"""Freelancer Contract Marketplace API — entry point and error handling.

In-memory only: all state lives in db.py module dicts, wiped on every process
start. Nothing is seeded at startup.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
from errors import ApiError
from response import error
from routes.clients import bp as clients_bp
from routes.contracts import bp as contracts_bp
from routes.disputes import bp as disputes_bp
from routes.freelancers import bp as freelancers_bp
from routes.job_postings import bp as job_postings_bp
from routes.milestones import bp as milestones_bp
from routes.payouts import bp as payouts_bp
from routes.proposals import bp as proposals_bp
from routes.reviews import bp as reviews_bp
from routes.tax_records import bp as tax_records_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (
    clients_bp,
    freelancers_bp,
    job_postings_bp,
    proposals_bp,
    contracts_bp,
    disputes_bp,
    payouts_bp,
    milestones_bp,
    reviews_bp,
    tax_records_bp,
):
    app.register_blueprint(bp)


# Serialize every request under the global store lock so that no two handlers
# ever interleave their non-atomic shared-state mutations (read-version →
# compare → write-version on the OCC path, multi-step escrow ledger writes,
# etc.). waitress runs the WSGI app on a worker-thread pool; under the per-test
# 8x-concurrent reboot sweep this guarantees single-threaded mutation semantics
# (identical observable behavior to the sequential test client) and removes any
# residual TOCTOU/interleaving as a source of flakiness. db.LOCK is a reentrant
# RLock, and teardown_request always fires, so the lock is released even when a
# handler raises.
@app.before_request
def _acquire_store_lock():
    db.LOCK.acquire()


@app.teardown_request
def _release_store_lock(exc=None):
    try:
        db.LOCK.release()
    except RuntimeError:
        # Lock was not held by this thread (e.g. before_request never ran);
        # nothing to release.
        pass


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    # Unmatched route — no specific entity context.
    return error("ERR_INVALID_REQUEST", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(exc):
    return error("ERR_INVALID_REQUEST", "Method not allowed", 405)


@app.errorhandler(HTTPException)
def handle_http(exc):
    # Malformed JSON etc. surface as 400 ERR_INVALID_REQUEST.
    status = exc.code or 500
    if status == 400:
        return error("ERR_INVALID_REQUEST", "Bad request", 400)
    return error("ERR_INVALID_REQUEST", exc.description or "Error", status)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return error("ERR_INVALID_REQUEST", "Internal error: " + str(exc), 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve the same WSGI app through waitress (a production-grade pure-Python
    # WSGI server) instead of the Werkzeug development server. The dev server
    # races under concurrent load + HTTP keep-alive socket reuse, surfacing as
    # BadStatusLine / "Connection aborted" on the client. waitress closes
    # connections cleanly and is robust under the per-test-server reboot sweep.
    # This is a pure transport change: the WSGI `app` — every endpoint,
    # response, header, validation, calculation, and in-memory state — is
    # identical to before.
    from waitress import serve

    serve(app, host="0.0.0.0", port=port, threads=8)
