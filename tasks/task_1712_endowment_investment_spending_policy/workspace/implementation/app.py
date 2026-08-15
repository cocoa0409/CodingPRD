import os

from flask import Flask

from errors import ApiError
from response import error as error_response

from routes.pools import bp as pools_bp
from routes.policies import bp as policies_bp
from routes.valuations import bp as valuations_bp
from routes.donors import bp as donors_bp
from routes.funds import bp as funds_bp
from routes.gifts import bp as gifts_bp
from routes.distributions import bp as distributions_bp
from routes.exceptions import bp as exceptions_bp
from routes.payouts import bp as payouts_bp
from routes.allocations import bp as allocations_bp
from routes.managers import bp as managers_bp
from routes.manager_reports import bp as manager_reports_bp
from routes.reports import bp as reports_bp
from routes.ledger import bp as ledger_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (
    pools_bp,
    policies_bp,
    valuations_bp,
    donors_bp,
    funds_bp,
    gifts_bp,
    distributions_bp,
    exceptions_bp,
    payouts_bp,
    allocations_bp,
    managers_bp,
    manager_reports_bp,
    reports_bp,
    ledger_bp,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response(
        "ERR_NOT_FOUND", "Method not allowed on this resource", 405
    )


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response("ERR_INVALID_REQUEST", str(err), 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
