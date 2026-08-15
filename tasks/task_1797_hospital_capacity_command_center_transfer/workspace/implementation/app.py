import os

from flask import Flask, jsonify

import errors
from envelope import error_body, success
from routes import bp

app = Flask(__name__)
app.register_blueprint(bp)


@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return jsonify(error_body(e.error_id, e.message)), e.status


@app.errorhandler(404)
def handle_not_found(e):
    return jsonify(error_body(errors.ERR_INVALID_REQUEST, "Resource not found")), 404


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return jsonify(error_body(errors.ERR_INVALID_REQUEST, "Method not allowed")), 405


@app.errorhandler(500)
def handle_internal(e):
    return jsonify(error_body(errors.ERR_INVALID_REQUEST, "Internal server error")), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
