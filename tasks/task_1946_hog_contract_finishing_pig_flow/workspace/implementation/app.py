"""Entry point: Flask app, error handlers, request serialization, route registration.

Boots with an empty in-memory store and the logical clock at exactly
2026-08-01T00:00:00Z (PRD §2.4); no entity is seeded at startup.
"""

import os
from flask import Flask

from db import store
from errors import ApiError, ERR_NOT_FOUND, ERR_MALFORMED_FIELD
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False


# Serialize all requests through one lock: cascades touch many resources per
# call and must never interleave with another request (§2.8 atomicity).
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
    return error_response(ERR_MALFORMED_FIELD, 400, "Bad request")


@app.errorhandler(Exception)
def handle_exception(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.http_status, err.message)
    import traceback
    traceback.print_exc()
    return error_response(ERR_MALFORMED_FIELD, 400, f"Unhandled error: {err}")


# register blueprints
from routes.ops import bp as ops_bp
from routes.sites import bp as sites_bp
from routes.growers import bp as growers_bp
from routes.contracts import bp as contracts_bp
from routes.barns import bp as barns_bp
from routes.pig_groups import bp as pig_groups_bp
from routes.feed_orders import bp as feed_orders_bp
from routes.packer_slots import bp as packer_slots_bp
from routes.market_loads import bp as market_loads_bp
from routes.truck_washes import bp as truck_washes_bp
from routes.barn_washes import bp as barn_washes_bp
from routes.manure_plans import bp as manure_plans_bp
from routes.manure_applications import bp as manure_applications_bp
from routes.maintenance_tickets import bp as maintenance_tickets_bp
from routes.settlements import bp as settlements_bp

app.register_blueprint(ops_bp)
app.register_blueprint(sites_bp)
app.register_blueprint(growers_bp)
app.register_blueprint(contracts_bp)
app.register_blueprint(barns_bp)
app.register_blueprint(pig_groups_bp)
app.register_blueprint(feed_orders_bp)
app.register_blueprint(packer_slots_bp)
app.register_blueprint(market_loads_bp)
app.register_blueprint(truck_washes_bp)
app.register_blueprint(barn_washes_bp)
app.register_blueprint(manure_plans_bp)
app.register_blueprint(manure_applications_bp)
app.register_blueprint(maintenance_tickets_bp)
app.register_blueprint(settlements_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
