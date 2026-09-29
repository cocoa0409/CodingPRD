"""Conference Program Committee & Abstract Review API.

Entry point: registers every blueprint and the envelope-shaped error handlers.
The in-memory store starts empty on every boot; nothing is seeded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.abstracts import bp as abstracts_bp
from routes.accreditations import bp as accreditations_bp
from routes.accreditations import disclosures_bp
from routes.authors import bp as authors_bp
from routes.categories import bp as categories_bp
from routes.change_requests import bp as change_requests_bp
from routes.clock import bp as clock_bp
from routes.conferences import bp as conferences_bp
from routes.members import bp as members_bp
from routes.members import declarations_bp
from routes.reviews import bp as reviews_bp
from routes.reviews import cases_bp
from routes.sessions import bp as sessions_bp
from routes.sessions import slots_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in (clock_bp, conferences_bp, categories_bp, authors_bp,
                      abstracts_bp, members_bp, declarations_bp, reviews_bp,
                      cases_bp, sessions_bp, slots_bp, accreditations_bp,
                      disclosures_bp, change_requests_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "The requested route does not exist.", 404)
        if exc.code == 405:
            return error_response("ERR_VALIDATION",
                                  "The HTTP method is not allowed for this route.", 405)
        if exc.code == 400:
            return error_response("ERR_VALIDATION", "The request could not be parsed.", 400)
        return error_response("ERR_VALIDATION", exc.description or "Request failed.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error: %s", exc)
        return error_response("ERR_VALIDATION", "Unexpected server error.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
