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
from routes.fields import bp as fields_bp
from routes.kilns import bp as kilns_bp
from routes.planting_plans import bp as planting_plans_bp
from routes.contracts import bp as contracts_bp
from routes.harvest_lots import bp as harvest_lots_bp
from routes.lab_tests import bp as lab_tests_bp
from routes.pellet_lots import bp as pellet_lots_bp
from routes.allocations import bp as allocations_bp
from routes.spot_sales import bp as spot_sales_bp
from routes.samples import bp as samples_bp
from routes.insurance_claims import bp as insurance_claims_bp
from routes.ops import bp as ops_bp

app.register_blueprint(fields_bp)
app.register_blueprint(kilns_bp)
app.register_blueprint(planting_plans_bp)
app.register_blueprint(contracts_bp)
app.register_blueprint(harvest_lots_bp)
app.register_blueprint(lab_tests_bp)
app.register_blueprint(pellet_lots_bp)
app.register_blueprint(allocations_bp)
app.register_blueprint(spot_sales_bp)
app.register_blueprint(samples_bp)
app.register_blueprint(insurance_claims_bp)
app.register_blueprint(ops_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
