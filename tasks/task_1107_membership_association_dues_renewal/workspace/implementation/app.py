"""Entry point: error handlers, route registration, server boot."""
import os
from flask import Flask

import errors
from response import error as error_response
from routes import reference, schedules, members, invoices, lifecycle_ops

app = Flask(__name__)

app.register_blueprint(reference.bp)
app.register_blueprint(schedules.bp)
app.register_blueprint(members.bp)
app.register_blueprint(invoices.bp)
app.register_blueprint(lifecycle_ops.bp)


@app.errorhandler(errors.ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(errors.ApiError(errors.ERR_NOT_FOUND, "Not found", 404))


@app.errorhandler(405)
def handle_405(err):
    return error_response(errors.ApiError(errors.ERR_NOT_FOUND, "Not found", 404))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, errors.ApiError):
        return error_response(err)
    return error_response(errors.ApiError("ERR_INTERNAL", str(err), 500))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
