"""Vessel Agency Port Calls API — Flask entry point."""
import os

from flask import Flask

from errors import ApiError
from response import error_body

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_body(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_body("ERR_NOT_FOUND", "The requested resource does not exist", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_body("ERR_NOT_FOUND", "The requested resource does not exist", 405)


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_body("ERR_INVALID_REQUEST", "Unexpected error: %s" % err, 400)


from routes import (berth_windows, cargo_documents, clock, cost_disputes,  # noqa: E402
                    crew_changes, disbursement_accounts, funding_advances,
                    husbandry_cases, notifications, port_calls, principals,
                    purchase_orders, service_orders, tariffs, vendors)

for module in (principals, port_calls, notifications, berth_windows, service_orders,
               crew_changes, vendors, purchase_orders, cargo_documents, tariffs,
               disbursement_accounts, funding_advances, cost_disputes, husbandry_cases,
               clock):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
