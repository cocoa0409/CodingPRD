"""Holiday Toy Drive API — Flask entry point."""

import os
import re

from flask import Flask, jsonify

from errors import ApiError, err_not_found, err_invalid_request
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_campaigns
import routes_intake
import routes_adoptions
import routes_backfill
import routes_distribution
import routes_notes

for module in (
    routes_campaigns,
    routes_intake,
    routes_adoptions,
    routes_backfill,
    routes_distribution,
    routes_notes,
):
    app.register_blueprint(module.bp, url_prefix="/toy-drive")


# ---------------------------------------------------------------------------
# lazy time-based transitions (PRD §2.5): evaluated on the next read or write
# after the logical clock moves. The two endpoints whose dedicated temporal
# errors (ERR_PLEDGE_EXPIRED / ERR_OUTSIDE_SLOT_WINDOW) must take precedence
# over the lazy flip perform their own explicit checks instead.
# ---------------------------------------------------------------------------

_SWEEP_EXEMPT = [
    re.compile(r"^/toy-drive/adoptions/[^/]+/confirm/?$"),
    re.compile(r"^/toy-drive/distribution-slots/[^/]+/check-in/?$"),
]


@app.before_request
def _lazy_sweep():
    from flask import request
    from domain import lazy_time_sweep
    for pat in _SWEEP_EXEMPT:
        if pat.match(request.path):
            return None
    lazy_time_sweep()
    return None


@app.errorhandler(ApiError)
def _api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _http_404(err):
    return error_response(err_not_found("Resource not found"))


@app.errorhandler(405)
def _http_405(err):
    return error_response(err_not_found("Method not allowed"))


@app.errorhandler(Exception)
def _http_500(err):
    if isinstance(err, ApiError):
        return error_response(err)
    import traceback
    traceback.print_exc()
    return error_response(err_invalid_request("Unhandled server error: %s" % err))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
