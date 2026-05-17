"""Route registration entry point."""

from flask import g, request
from middleware import require_auth


def register_routes(app):
    # Auth gate for every request.
    @app.before_request
    def _before():
        require_auth()

    from routes.plans import plans_bp
    from routes.participants import participants_bp
    from routes.contributions import contributions_bp
    from routes.vesting import vesting_bp
    from routes.loans import loans_bp
    from routes.hardships import hardships_bp
    from routes.rmds import rmds_bp

    app.register_blueprint(plans_bp)
    app.register_blueprint(participants_bp)
    app.register_blueprint(contributions_bp)
    app.register_blueprint(vesting_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(hardships_bp)
    app.register_blueprint(rmds_bp)
