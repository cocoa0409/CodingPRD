"""Aviation Fuel Farm & Into-Plane Fueling API — entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, err_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.farms import bp as farms_bp
    from routes.tanks import bp as tanks_bp
    from routes.receipts import bp as receipts_bp
    from routes.assets import bp as assets_bp
    from routes.commercial import bp as commercial_bp
    from routes.orders import bp as orders_bp
    from routes.spills import bp as spills_bp
    from routes.billing import bp as billing_bp

    for bp in (farms_bp, tanks_bp, receipts_bp, assets_bp, commercial_bp,
               orders_bp, spills_bp, billing_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return err_response(exc.error_id, exc.message)

    @app.errorhandler(404)
    def _not_found(exc):
        return err_response("ERR_RESOURCE_NOT_FOUND", "Resource not found")

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return err_response("ERR_RESOURCE_NOT_FOUND", "Method not allowed for this path")

    @app.errorhandler(400)
    def _bad_request(exc):
        return err_response("ERR_INVALID_PAYLOAD", "Malformed request payload")

    @app.errorhandler(HTTPException)
    def _http_exc(exc):
        if exc.code == 404:
            return err_response("ERR_RESOURCE_NOT_FOUND", "Resource not found")
        if exc.code == 405:
            return err_response("ERR_RESOURCE_NOT_FOUND", "Method not allowed for this path")
        return err_response("ERR_INVALID_PAYLOAD", str(exc.description))

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return err_response(exc.error_id, exc.message)
        import traceback
        traceback.print_exc()
        return err_response("ERR_INVALID_PAYLOAD", "Unexpected server error: %s" % exc)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
