import os
from flask import Flask, jsonify
from errors import ApiError
from response import error_response

from routes.participants import bp as participants_bp
from routes.projects import bp as projects_bp
from routes.financing import bp as financing_bp
from routes.interconnection import bp as interconnection_bp
from routes.srecs import bp as srecs_bp
from routes.netmeter import bp as netmeter_bp
from routes.warranty import bp as warranty_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(participants_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(financing_bp)
    app.register_blueprint(interconnection_bp)
    app.register_blueprint(srecs_bp)
    app.register_blueprint(netmeter_bp)
    app.register_blueprint(warranty_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return jsonify(error_response(e.error_id, e.message)), e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        return jsonify(error_response("ERR_NOT_FOUND", "Resource not found.")), 404

    @app.errorhandler(405)
    def handle_405(e):
        return jsonify(error_response("ERR_NOT_FOUND", "Method not allowed.")), 404

    @app.errorhandler(400)
    def handle_400(e):
        return jsonify(error_response("ERR_INVALID_REQUEST", "Bad request.")), 400

    @app.errorhandler(Exception)
    def handle_generic(e):
        if isinstance(e, ApiError):
            return jsonify(error_response(e.error_id, e.message)), e.http_status
        return jsonify(error_response("ERR_INVALID_REQUEST", str(e))), 400

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
