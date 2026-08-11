"""Entry point: Flask app assembly, error handlers, route registration.

Storage is in-memory only (Python dicts in db.store) and starts completely
empty on every process boot — nothing is seeded, preloaded, or hardcoded.
"""

import os

from flask import Flask

from errors import ApiError, err_validation
from response import error_response, ok

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(_exc):
    return error_response("ERR_VALIDATION", "Route not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    return error_response("ERR_VALIDATION", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    app.logger.exception("unexpected error: %s", exc)
    return error_response("ERR_VALIDATION", "Internal error: %s" % exc, 500)


import routes_accounts  # noqa: E402
import routes_cases  # noqa: E402
import routes_disbursements  # noqa: E402
import routes_docs  # noqa: E402
import routes_execution  # noqa: E402
import routes_loans  # noqa: E402
import routes_ops  # noqa: E402
import routes_participants  # noqa: E402
import routes_plans  # noqa: E402
import routes_redeposits  # noqa: E402
import routes_taxforms  # noqa: E402

for module in (
    routes_plans,
    routes_participants,
    routes_accounts,
    routes_loans,
    routes_cases,
    routes_execution,
    routes_docs,
    routes_disbursements,
    routes_redeposits,
    routes_taxforms,
    routes_ops,
):
    app.register_blueprint(module.bp)


@app.get("/v1/_health")
def health():
    return ok({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
