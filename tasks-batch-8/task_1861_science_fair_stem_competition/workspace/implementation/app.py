"""Science Fair API — Flask entry point.

Boots an empty in-memory store (no seeding of any kind), registers all
route blueprints, and serves on 0.0.0.0:$PORT (default 10000).
"""

import os
from flask import Flask, jsonify

import db
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes.clock import bp as clock_bp
from routes.fair_editions import bp as fair_editions_bp
from routes.categories import bp as categories_bp
from routes.mentors import bp as mentors_bp
from routes.projects import bp as projects_bp
from routes.research_plans import bp as research_plans_bp
from routes.judges import bp as judges_bp
from routes.judging import bp as judging_bp
from routes.booths import bp as booths_bp
from routes.awards import bp as awards_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (clock_bp, fair_editions_bp, categories_bp, mentors_bp,
               projects_bp, research_plans_bp, judges_bp, judging_bp,
               booths_bp, awards_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_INVALID_REQUEST, "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Never leak a bare 500 stack trace through the envelope contract
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
