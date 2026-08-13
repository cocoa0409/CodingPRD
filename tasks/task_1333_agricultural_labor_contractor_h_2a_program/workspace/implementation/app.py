"""H-2A Labor Contractor API — Flask entry point."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from common import ApiError, error_response, invalid
from routes import ALL_BLUEPRINTS

app = Flask(__name__)
app.json.sort_keys = False

for bp in ALL_BLUEPRINTS:
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, HTTPException):
        return err
    return error_response(invalid(str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
