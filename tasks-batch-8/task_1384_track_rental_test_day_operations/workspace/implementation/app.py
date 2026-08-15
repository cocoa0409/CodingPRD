"""Track Rental & Test Day Operations API — Flask entry point."""

import os

from flask import Flask

import errors as err
import response
import routes_bookings
import routes_core
import routes_flat
import routes_ops
import routes_tracks

app = Flask(__name__)

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_tracks.bp)
app.register_blueprint(routes_bookings.bp)
app.register_blueprint(routes_ops.bp)
app.register_blueprint(routes_flat.bp)


@app.errorhandler(err.ApiError)
def handle_api_error(e):
    return response.error(e)


@app.errorhandler(404)
def handle_not_found(e):
    return response.error(err.not_found("resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return response.error(err.not_found("resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, err.ApiError):
        return response.error(e)
    return response.error(err.ApiError("ERR_INTERNAL", 500, str(e)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
