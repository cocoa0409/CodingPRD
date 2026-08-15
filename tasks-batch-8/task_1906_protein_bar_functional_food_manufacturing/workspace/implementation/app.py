"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError
from response import error_body
from routes import catalog, commercial, formulas, lines, runs, studies

app = Flask(__name__)

app.register_blueprint(catalog.bp)
app.register_blueprint(commercial.bp)
app.register_blueprint(formulas.bp)
app.register_blueprint(lines.bp)
app.register_blueprint(runs.bp)
app.register_blueprint(studies.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_body(err)


@app.errorhandler(404)
def handle_404(_err):
    return error_body(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(_err):
    return error_body(ApiError("ERR_METHOD_NOT_ALLOWED", 405,
                               "Method not allowed"))


@app.errorhandler(500)
def handle_500(err):
    return error_body(ApiError("ERR_INTERNAL", 500, "Internal server error"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
