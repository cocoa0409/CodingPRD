"""Cost-Segregation & R&D Tax-Credit Service API — Flask entry point."""
import os
from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, err_response
import routes_core
import routes_study
import routes_children
import routes_post

app = Flask(__name__)
app.url_map.strict_slashes = False

routes_core.register(app)
routes_study.register(app)
routes_children.register(app)
routes_post.register(app)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e)


@app.errorhandler(404)
def handle_404(e):
    return err_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return err_response(ApiError("ERR_NOT_FOUND", 404, "Method not allowed"))


@app.errorhandler(400)
def handle_400(e):
    return err_response(ApiError("ERR_VALIDATION", 400, "Malformed request"))


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, HTTPException):
        return err_response(ApiError("ERR_VALIDATION", e.code or 400, str(e)))
    return err_response(ApiError("ERR_VALIDATION", 500, "Internal error"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
