"""Flask application object and error handlers.

Routes modules import `app` from here; this module imports the route modules
at the bottom once `app` exists. Keeping the app object out of the __main__
module avoids the double-module-registration trap of `python3 app.py`.
"""

from flask import Flask

from errors import ApiError, err
from helpers import error_response

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(err("ERR_NOT_FOUND", "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(err("ERR_NOT_FOUND", "Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    resp = error_response(err("ERR_MISSING_REQUIRED_FIELD",
                              "Malformed request: %s" % e))
    resp.status_code = 400
    return resp


# Route modules register against `app` on import.
import routes_core  # noqa: E402,F401
import routes_flow  # noqa: E402,F401
import routes_health_discipline  # noqa: E402,F401
