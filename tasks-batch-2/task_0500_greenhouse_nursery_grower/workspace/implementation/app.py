import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response
from routes.varieties import bp as varieties_bp
from routes.zones import bp as zones_bp
from routes.batches import bp as batches_bp
from routes.brokers import bp as brokers_bp
from routes.availability import bp as availability_bp
from routes.orders import bp as orders_bp
from routes.phyto import bp as phyto_bp
from routes.shipments import bp as shipments_bp
from routes.ops import bp as ops_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (varieties_bp, zones_bp, batches_bp, brokers_bp, availability_bp,
               orders_bp, phyto_bp, shipments_bp, ops_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        if err.code == 404:
            return error_response("ERR_NOT_FOUND", 404, "Resource not found")
        return error_response("ERR_REQUEST", err.code or 400, err.description or "Request error")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.http_status, err.message)
        return error_response("ERR_INTERNAL", 500, str(err))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
