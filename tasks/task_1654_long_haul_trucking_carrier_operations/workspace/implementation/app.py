"""Long-Haul Trucking Carrier Operations API — Flask entry point."""
import os

from flask import Flask

from common import ApiError, error_response, meta
from flask import jsonify
from store import store


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return jsonify({"meta": meta(), "response_type": "error",
                        "data": {"error_id": "ERR_NOT_FOUND",
                                 "message": "Route not found"}}), 404

    @app.errorhandler(405)
    def handle_405(e):
        return jsonify({"meta": meta(), "response_type": "error",
                        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED",
                                 "message": "Method not allowed"}}), 405

    @app.errorhandler(500)
    def handle_500(e):
        return jsonify({"meta": meta(), "response_type": "error",
                        "data": {"error_id": "ERR_INTERNAL",
                                 "message": "Internal server error"}}), 500

    import routes_fleet
    import routes_ops
    import routes_money
    app.register_blueprint(routes_fleet.bp)
    app.register_blueprint(routes_ops.bp)
    app.register_blueprint(routes_money.bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
