"""Entry point: Flask app, error handlers, request serialization, route registration."""

import os
from flask import Flask

from db import store
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False


# Serialize all requests through one lock: cascades touch many resources per
# call and must never interleave with another request.
@app.before_request
def _acquire_store_lock():
    store.lock.acquire()


@app.teardown_request
def _release_store_lock(exc):
    store.lock.release()


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(400)
def handle_400(err):
    return error_response(ERR_INVALID_REQUEST, 400, "Bad request")


@app.errorhandler(Exception)
def handle_exception(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.http_status, err.message)
    import traceback
    traceback.print_exc()
    return error_response(ERR_INVALID_REQUEST, 400, f"Unhandled error: {err}")


# register blueprints
from routes.clock import bp as clock_bp
from routes.publishers import bp as publishers_bp
from routes.packages import bp as packages_bp
from routes.seasonal_windows import bp as seasonal_windows_bp
from routes.demand_partners import bp as demand_partners_bp
from routes.deals import bp as deals_bp
from routes.supply_chain import bp as supply_chain_bp
from routes.blocklist import bp as blocklist_bp
from routes.auctions import bp as auctions_bp
from routes.reconciliation import bp as reconciliation_bp
from routes.payouts import bp as payouts_bp

app.register_blueprint(clock_bp)
app.register_blueprint(publishers_bp)
app.register_blueprint(packages_bp)
app.register_blueprint(seasonal_windows_bp)
app.register_blueprint(demand_partners_bp)
app.register_blueprint(deals_bp)
app.register_blueprint(supply_chain_bp)
app.register_blueprint(blocklist_bp)
app.register_blueprint(auctions_bp)
app.register_blueprint(reconciliation_bp)
app.register_blueprint(payouts_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
