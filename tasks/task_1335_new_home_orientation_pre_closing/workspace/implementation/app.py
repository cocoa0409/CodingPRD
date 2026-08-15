"""Entry point: app factory, request serialization, error handlers,
blueprint registration."""
import os

from flask import Flask

import db
from errors import ApiError, err_not_found
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.clock import bp as clock_bp
    from routes.communities import bp as communities_bp
    from routes.registries import bp as registries_bp
    from routes.homes import bp as homes_bp
    from routes.appointments import bp as appointments_bp
    from routes.attendees import bp as attendees_bp
    from routes.deficiencies import bp as deficiencies_bp
    from routes.visits import bp as visits_bp
    from routes.escrow import bp as escrow_bp
    from routes.signatures import bp as signatures_bp
    from routes.surveys import bp as surveys_bp

    for bp in (clock_bp, communities_bp, registries_bp, homes_bp, appointments_bp,
               attendees_bp, deficiencies_bp, visits_bp, escrow_bp, signatures_bp,
               surveys_bp):
        app.register_blueprint(bp)

    # Serialize request handling: OCC races must resolve deterministically.
    @app.before_request
    def _acquire():
        db.LOCK.acquire()

    @app.teardown_request
    def _release(exc):
        db.LOCK.release()

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(err_not_found())

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(err_not_found())

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        import traceback
        traceback.print_exc()
        return error_response(ApiError("ERR_VALIDATION", 400, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    # Quiet per-request werkzeug logging: under the concurrent stability sweep
    # the per-boot stderr volume is pure I/O contention; errors still surface.
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
