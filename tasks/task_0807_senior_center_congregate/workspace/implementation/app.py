"""Senior Center & Congregate Programs API — Flask entry point.

Fresh, empty, in-memory store on every boot. No seeding. Binds 0.0.0.0:$PORT.
"""
import os

from flask import Flask

from core import ApiError, error_response

import r_people
import r_funding
import r_activities
import r_transport
import r_meals
import r_wellness


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(r_people.bp)
    app.register_blueprint(r_funding.bp)
    app.register_blueprint(r_activities.bp)
    app.register_blueprint(r_transport.bp)
    app.register_blueprint(r_meals.bp)
    app.register_blueprint(r_wellness.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ApiError("ERR_VALIDATION", "Resource path not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ApiError("ERR_VALIDATION", "Method not allowed"))

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(ApiError("ERR_VALIDATION", "Malformed request"))

    @app.errorhandler(500)
    def handle_500(e):
        return error_response(ApiError("ERR_VALIDATION", "Internal error"))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
