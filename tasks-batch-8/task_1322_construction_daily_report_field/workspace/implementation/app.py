"""Construction Daily Reports API — Flask entry point."""
import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes.setup_resources import bp as setup_bp
from routes.daily_reports import bp as reports_bp
from routes.field_logs import bp as field_logs_bp
from routes.safety import bp as safety_bp
from routes.evidence import bp as evidence_bp
from routes.commercial import bp as commercial_bp

app.register_blueprint(setup_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(field_logs_bp)
app.register_blueprint(safety_bp)
app.register_blueprint(evidence_bp)
app.register_blueprint(commercial_bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(HTTPException)
def handle_http_error(err):
    api_err = ApiError(
        "ERR_NOT_FOUND", 404, "Resource not found"
    )
    return error_response(api_err)


@app.errorhandler(Exception)
def handle_unexpected(err):
    traceback.print_exc()
    api_err = ApiError("ERR_INTERNAL", 500, str(err))
    return error_response(api_err)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
