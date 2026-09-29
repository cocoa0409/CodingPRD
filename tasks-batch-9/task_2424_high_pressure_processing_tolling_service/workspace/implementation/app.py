"""HPP Tolling Service API.

Flask application factory and error plumbing.  All state lives in process
memory (see db.py) and the store is empty on every boot: nothing is seeded.
"""
import os

from flask import Flask

import api_contracts
import api_cycles
import api_deviations
import api_loads
import api_lots
import api_money
import api_qualifications
import api_reference
import errors
import response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (api_reference, api_qualifications, api_contracts, api_lots,
                   api_cycles, api_loads, api_deviations, api_money):
        app.register_blueprint(module.bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return response.error_response("ERR_INVALID_REQUEST",
                                       "No such route.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return response.error_response("ERR_INVALID_REQUEST",
                                       "Method not allowed on this route.", 405)

    @app.errorhandler(400)
    def handle_400(exc):
        return response.error_response("ERR_INVALID_REQUEST",
                                       "Malformed request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return response.error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return response.error_response("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            debug=False, threaded=True)
