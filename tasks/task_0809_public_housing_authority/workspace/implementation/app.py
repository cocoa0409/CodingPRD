"""Flask entry point: blueprint registration, error handling, request
serialization, and the foreground server bound to 0.0.0.0:$PORT."""
import os

from flask import Flask, g

import db
from core import ApiError, error_response
from routes_applicants import bp as applicants_bp
from routes_waitlists import bp as waitlists_bp
from routes_units_offers import bp as units_offers_bp
from routes_tenancy_certs import bp as tenancy_certs_bp
from routes_interim_grievance import bp as interim_grievance_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(applicants_bp)
    app.register_blueprint(waitlists_bp)
    app.register_blueprint(units_offers_bp)
    app.register_blueprint(tenancy_certs_bp)
    app.register_blueprint(interim_grievance_bp)

    # Serialize all requests so multi-resource cascades settle atomically.
    @app.before_request
    def _lock():
        db.LOCK.acquire()
        g._locked = True

    @app.teardown_request
    def _unlock(exc):
        if g.pop("_locked", False):
            try:
                db.LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
