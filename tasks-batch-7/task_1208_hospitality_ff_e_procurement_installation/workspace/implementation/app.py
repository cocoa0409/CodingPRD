"""Entry point: Flask app, error handlers, route registration."""
import os
import threading

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False

_request_lock = threading.RLock()


@app.before_request
def _acquire_lock():
    _request_lock.acquire()


@app.teardown_request
def _release_lock(exc):
    _request_lock.release()


@app.errorhandler(ApiError)
def _api_error(e):
    return error_response(e.error_id, e.message, e.status)


@app.errorhandler(404)
def _not_found(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def _method_not_allowed(e):
    return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)


@app.errorhandler(Exception)
def _unexpected(e):
    return error_response("ERR_INTERNAL", str(e), 500)


from routes.projects import bp as projects_bp
from routes.specs_bids import bp as specs_bids_bp
from routes.purchase_orders import bp as purchase_orders_bp
from routes.shipments import bp as shipments_bp
from routes.claims import bp as claims_bp
from routes.installation import bp as installation_bp
from routes.change_orders import bp as change_orders_bp

for _bp in (projects_bp, specs_bids_bp, purchase_orders_bp, shipments_bp,
            claims_bp, installation_bp, change_orders_bp):
    app.register_blueprint(_bp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
