"""Entry point: Flask app, error handlers, blueprint registration."""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import error_response

app = Flask(__name__)

import routes_admin
import routes_evaluations
import routes_petitions
import routes_pla
import routes_students
import routes_transcripts

app.register_blueprint(routes_admin.bp)
app.register_blueprint(routes_students.bp)
app.register_blueprint(routes_transcripts.bp)
app.register_blueprint(routes_evaluations.bp)
app.register_blueprint(routes_petitions.bp)
app.register_blueprint(routes_pla.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(Exception)
def handle_generic(err):
    return error_response("ERR_INTERNAL", 500, str(err))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
