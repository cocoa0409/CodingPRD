"""Tree Nut Huller Processor API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The store starts empty on every boot.
Lazy fumigation clearance (PRD §2.5) is evaluated before every request, so a
bin never stays locked past its clearance instant merely because no client
advanced the clock.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from services import cascade

app = Flask(__name__)

from routes.core import bp as core_bp
from routes.lots import bp as lots_bp
from routes.processing import bp as processing_bp
from routes.storage import bp as storage_bp
from routes.commercial import bp as commercial_bp

app.register_blueprint(core_bp)
app.register_blueprint(lots_bp)
app.register_blueprint(processing_bp)
app.register_blueprint(storage_bp)
app.register_blueprint(commercial_bp)


@app.before_request
def _lazy_clearance_hook():
    cascade.lazy_clearance()


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return response.err(e.error_id, e.status, e.message)


@app.errorhandler(HTTPException)
def _handle_http_error(e):
    if e.code == 404:
        return response.err("ERR_NOT_FOUND", 404, "Resource not found")
    if e.code == 405:
        return response.err("ERR_NOT_FOUND", 405, "Method not allowed")
    return response.err("ERR_NOT_FOUND", e.code or 500, e.description)


@app.errorhandler(Exception)
def _handle_unexpected(e):
    return response.err("ERR_INTERNAL", 500, "Internal server error: %s" % e)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
