import os

from flask import Flask, jsonify

import envelope
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.reference import bp as reference_bp
    from routes.referrals import bp as referrals_bp
    from routes.episodes import bp as episodes_bp
    from routes.risk import bp as risk_bp
    from routes.contacts import bp as contacts_bp
    from routes.visits import bp as visits_bp
    from routes.medrec import bp as medrec_bp
    from routes.barriers import bp as barriers_bp
    from routes.redflags import bp as redflags_bp
    from routes.readmissions import bp as readmissions_bp
    from routes.claims import bp as claims_bp
    from routes.handoffs import bp as handoffs_bp

    for blueprint in (
        reference_bp,
        referrals_bp,
        episodes_bp,
        risk_bp,
        contacts_bp,
        visits_bp,
        medrec_bp,
        barriers_bp,
        redflags_bp,
        readmissions_bp,
        claims_bp,
        handoffs_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return envelope.error("ERR_RESOURCE_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return envelope.error("ERR_RESOURCE_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return envelope.error(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return jsonify(
            {
                "meta": {},
                "response_type": "error",
                "data": {"error_id": "ERR_INTERNAL", "message": str(exc)},
            }
        ), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
