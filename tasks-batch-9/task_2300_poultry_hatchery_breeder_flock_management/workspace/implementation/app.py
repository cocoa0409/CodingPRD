"""Poultry Hatchery & Breeder Flock API — Flask application entry point.

State lives only in process memory (see store.py); nothing is seeded at boot and
nothing is written to disk, so every fresh process starts from an empty hatchery.
"""

import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from helpers import error_response
from routes import (config_routes, egg_routes, flock_routes, grower_routes,
                    hatch_routes, lab_routes, setter_routes)

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

for module in (config_routes, flock_routes, egg_routes, setter_routes, hatch_routes,
               grower_routes, lab_routes):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(HTTPException)
def handle_http_error(err):
    return error_response(ApiError("ERR_INVALID_REQUEST", err.code or 400,
                                   err.description or "Request could not be served."))


@app.errorhandler(Exception)
def handle_unexpected(err):  # pragma: no cover - defensive
    return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(err)))


# One request at a time: the domain rules read and write many records per call and
# the conservation invariants of PRD §2.10 must hold after every mutation.
_serialize = threading.Lock()
_inner_wsgi_app = app.wsgi_app


def _locked_wsgi_app(environ, start_response):
    with _serialize:
        return _inner_wsgi_app(environ, start_response)


app.wsgi_app = _locked_wsgi_app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
