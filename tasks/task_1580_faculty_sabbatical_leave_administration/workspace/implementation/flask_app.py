"""Flask application object, error handlers, and the lazy status sweep."""
from flask import Flask

from services import sweep_overdue_and_defaults
from util import ApiError, err_body

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.before_request
def _lazy_time_sweep():
    # DUE->OVERDUE and ACTIVE->DEFAULTED are evaluated on the clock sweep and
    # lazily whenever resources are read or acted upon (PRD section 2.5).
    sweep_overdue_and_defaults()


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return err_body(e.error_id, e.message, e.http)


@app.errorhandler(404)
def _handle_404(e):
    return err_body('ERR_INVALID_REQUEST', 'The requested path does not exist.', 404)


@app.errorhandler(405)
def _handle_405(e):
    return err_body('ERR_INVALID_REQUEST', 'Method not allowed for this path.', 405)


@app.errorhandler(Exception)
def _handle_unexpected(e):
    return err_body('ERR_INVALID_REQUEST', 'Unexpected server error.', 500)
