"""Entry point: Flask app, blueprint registration, error handlers."""
import os

from flask import Flask, jsonify

from core import ApiError, envelope_error
import routes_years
import routes_students
import routes_money
import routes_waivers_refunds
import routes_collections
import routes_alias


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_years.bp)
    app.register_blueprint(routes_students.bp)
    app.register_blueprint(routes_money.bp)
    app.register_blueprint(routes_waivers_refunds.bp)
    app.register_blueprint(routes_collections.bp)
    app.register_blueprint(routes_alias.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        resp = jsonify(envelope_error(e.error_id, e.message))
        resp.status_code = e.status
        return resp

    @app.errorhandler(404)
    def handle_404(e):
        resp = jsonify(envelope_error(
            "ERR_NOT_FOUND", "The requested resource does not exist."))
        resp.status_code = 404
        return resp

    @app.errorhandler(405)
    def handle_405(e):
        resp = jsonify(envelope_error(
            "ERR_NOT_FOUND", "The requested resource does not exist."))
        resp.status_code = 404
        return resp

    @app.errorhandler(400)
    def handle_400(e):
        resp = jsonify(envelope_error(
            "ERR_INVALID_REQUEST", "The request body could not be parsed."))
        resp.status_code = 400
        return resp

    @app.errorhandler(Exception)
    def handle_500(e):
        resp = jsonify(envelope_error(
            "ERR_INVALID_REQUEST", f"Unexpected server error: {e}"))
        resp.status_code = 400
        return resp

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
