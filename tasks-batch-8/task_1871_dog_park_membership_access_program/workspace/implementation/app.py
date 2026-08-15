"""Dog Park Membership & Access API — entry point.

In-memory store only; every fresh process boots with an empty store and the
logical clock at 2026-08-01T00:00:00Z. No seeding, no disk persistence.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import register_routes

app = Flask(__name__)
register_routes(app)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
