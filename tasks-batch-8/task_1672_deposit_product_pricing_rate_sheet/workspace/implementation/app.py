"""Entry point: Flask app, error handlers, route registration."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import error_body
from routes import ALL_BLUEPRINTS

app = Flask(__name__)

for bp in ALL_BLUEPRINTS:
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_body(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_body(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_body(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(e):
    return error_body("ERR_INTERNAL", 500, str(e))


@app.get("/")
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
