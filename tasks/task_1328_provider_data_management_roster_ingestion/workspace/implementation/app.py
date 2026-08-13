"""Entry point: Flask app, error handlers, route registration."""

import os

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(_err):
    from errors import ApiError, ERR_NOT_FOUND
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(_err):
    from errors import ApiError, ERR_NOT_FOUND
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


from routes import clock, roster_sources, roster_files, roster_rows  # noqa: E402
from routes import providers, attributes, aliases, conflicts  # noqa: E402
from routes import distribution, attestation, quality, merges  # noqa: E402

for bp in (
    clock.bp,
    roster_sources.bp,
    roster_files.bp,
    roster_rows.bp,
    providers.bp,
    attributes.bp,
    aliases.bp,
    conflicts.bp,
    distribution.bp,
    attestation.bp,
    quality.bp,
    merges.bp,
):
    app.register_blueprint(bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
