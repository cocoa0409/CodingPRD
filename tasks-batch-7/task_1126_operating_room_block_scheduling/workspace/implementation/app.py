"""Flask application entry point: error handlers + route registration."""

import os

from flask import Flask

from errors import ApiError
from response import error_response, meta


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.service_lines import bp as service_lines_bp
    from routes.surgeons import bp as surgeons_bp
    from routes.rooms import bp as rooms_bp
    from routes.blocks import bp as blocks_bp
    from routes.cases import bp as cases_bp
    from routes.coverages import bp as coverages_bp
    from routes.slots import bp as slots_bp
    from routes.requests import bp as requests_bp
    from routes.ops import bp as ops_bp
    from routes.reviews import bp as reviews_bp
    from routes.clock import bp as clock_bp

    for bp in (
        service_lines_bp,
        surgeons_bp,
        rooms_bp,
        blocks_bp,
        cases_bp,
        coverages_bp,
        slots_bp,
        requests_bp,
        ops_bp,
        reviews_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        body = {
            "meta": meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_NOT_FOUND",
                "message": "The requested resource was not found",
            },
        }
        from flask import jsonify

        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        from flask import jsonify

        body = {
            "meta": meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_NOT_FOUND",
                "message": "The requested resource was not found",
            },
        }
        return jsonify(body), 404

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        from flask import jsonify

        if isinstance(err, ApiError):
            return error_response(err)
        body = {
            "meta": meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_INTERNAL",
                "message": f"Internal server error: {err}",
            },
        }
        return jsonify(body), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
