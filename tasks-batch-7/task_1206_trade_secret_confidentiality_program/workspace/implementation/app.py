"""Trade Secret & Confidentiality Program API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000) per INSTRUCTION.md. Storage is in-memory
and starts empty on every boot (no seed data).
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes_program import bp as program_bp
    from routes_assets import bp as assets_bp
    from routes_nda import bp as nda_bp
    from routes_people import bp as people_bp
    from routes_access import bp as access_bp
    from routes_legal import bp as legal_bp
    from routes_audits import bp as audits_bp

    for bp in (program_bp, assets_bp, nda_bp, people_bp, access_bp, legal_bp, audits_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        from errors import err_not_found

        return error_response(err_not_found("resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        from errors import err_not_found

        return error_response(err_not_found("method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Never leak a bare 500 HTML page; surface as a generic 400 envelope.
        from errors import err_invalid_request

        return error_response(err_invalid_request(str(err)))

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
