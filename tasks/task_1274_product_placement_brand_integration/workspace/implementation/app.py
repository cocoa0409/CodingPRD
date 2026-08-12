"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

import errors
import response
from routes import brands, series, clearances, proposals, contracts, shipments, airing, extras

app = Flask(__name__, static_folder=None)

app.register_blueprint(brands.bp)
app.register_blueprint(series.bp)
app.register_blueprint(clearances.bp)
app.register_blueprint(proposals.bp)
app.register_blueprint(contracts.bp)
app.register_blueprint(shipments.bp)
app.register_blueprint(airing.bp)
app.register_blueprint(extras.bp)


@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return response.error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_not_found(e):
    return response.error_response(errors.ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return response.error_response(errors.ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return handle_api_error(e)
    return response.error_response("ERR_INTERNAL", 500, str(e))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
