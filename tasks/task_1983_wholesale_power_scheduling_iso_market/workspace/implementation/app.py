"""Wholesale Power ISO Settlement API — Flask entry point."""
import os

from flask import Flask

from envelope import error_response
from errors import ApiError, ERR_NOT_FOUND

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(_err):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "resource not found"))


@app.errorhandler(500)
def handle_500(_err):
    return error_response(ApiError("ERR_INTERNAL", 500, "internal server error"))


from routes import (clock, participants, generators, operating_days, offers,
                    telemetry, outages, statements, disputes, awards,
                    obligations, events, postings, margin_calls)

for module in (clock, participants, generators, operating_days, offers,
               telemetry, outages, statements, disputes, awards, obligations,
               events, postings, margin_calls):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
