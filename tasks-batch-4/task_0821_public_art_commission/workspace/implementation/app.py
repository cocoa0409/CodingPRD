"""Public Art Commission API — Flask entry point."""
import os

from flask import Flask

from util import ApiError, err_response
from routes_budget import bp as budget_bp
from routes_selection import bp as selection_bp
from routes_registry import bp as registry_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(budget_bp)
app.register_blueprint(selection_bp)
app.register_blueprint(registry_bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return err_response(exc.error_id, exc.message)


@app.errorhandler(404)
def handle_404(_exc):
    return err_response("ERR_VALIDATION", "resource not found")


@app.errorhandler(405)
def handle_405(_exc):
    return err_response("ERR_VALIDATION", "method not allowed")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
