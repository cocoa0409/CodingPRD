"""Book Publishing Royalties API — entry point.

In-memory store, fresh on every process boot. No seeding.
"""
import os

from flask import Flask

import errors
from response import error_response
from routes.parties import bp as parties_bp
from routes.contracts import bp as contracts_bp
from routes.catalogue import bp as catalogue_bp
from routes.periods import bp as periods_bp
from routes.rights import bp as rights_bp
from routes.statements import bp as statements_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(parties_bp)
app.register_blueprint(contracts_bp)
app.register_blueprint(catalogue_bp)
app.register_blueprint(periods_bp)
app.register_blueprint(rights_bp)
app.register_blueprint(statements_bp)


@app.errorhandler(errors.ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response(errors.ERR_NOT_FOUND, "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response(errors.ERR_NOT_FOUND, "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, errors.ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response("ERR_INTERNAL", "Internal server error: %s" % err, 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
