"""Coffee Roasting Plant & Green Coffee Contracts API — Flask entry point."""

import os

from flask import Flask, g

from db import DB
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False


# Serialize requests through one global lock: single-writer semantics make
# OCC races deterministic (one writer wins, the other sees ERR_STALE_VERSION).
@app.before_request
def _acquire_store_lock():
    DB.lock.acquire()
    g._store_lock_held = True


@app.teardown_request
def _release_store_lock(exc):
    if g.pop("_store_lock_held", False):
        DB.lock.release()


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ERR_NOT_FOUND, "Route not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response(ERR_INVALID_REQUEST, "Method not allowed", 405)


@app.errorhandler(500)
def handle_500(e):
    return error_response(ERR_INVALID_REQUEST, f"Internal error: {e}", 500)


from routes.counterparties import bp as counterparties_bp
from routes.contracts import bp as contracts_bp
from routes.shipments import bp as shipments_bp
from routes.green_lots import bp as green_lots_bp
from routes.financing import bp as financing_bp
from routes.profiles_products import bp as profiles_products_bp
from routes.recipes import bp as recipes_bp
from routes.roast_batches import bp as roast_batches_bp
from routes.cupping import bp as cupping_bp
from routes.finished_goods import bp as finished_goods_bp
from routes.fulfillment import bp as fulfillment_bp
from routes.hedges import bp as hedges_bp
from routes.clock_admin import bp as clock_bp

app.register_blueprint(counterparties_bp)
app.register_blueprint(contracts_bp)
app.register_blueprint(shipments_bp)
app.register_blueprint(green_lots_bp)
app.register_blueprint(financing_bp)
app.register_blueprint(profiles_products_bp)
app.register_blueprint(recipes_bp)
app.register_blueprint(roast_batches_bp)
app.register_blueprint(cupping_bp)
app.register_blueprint(finished_goods_bp)
app.register_blueprint(fulfillment_bp)
app.register_blueprint(hedges_bp)
app.register_blueprint(clock_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
