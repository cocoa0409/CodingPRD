"""Route registration: every request is auth-checked, then dispatched to a blueprint."""

from flask import jsonify

from middleware import require_auth
from response import error
from errors import AppError


def register_routes(app):
    @app.before_request
    def _auth_gate():
        # Apply auth to ALL endpoints (priority 1+2). 404s on unknown paths still go through Flask's
        # default routing; we surface them via the AppError handler in app.py.
        require_auth()

    # Lazy imports to avoid circular deps at module-import time.
    from routes.borrowers import borrowers_bp
    from routes.loan_applications import loan_applications_bp
    from routes.verifications import verifications_bp
    from routes.appraisals import appraisals_bp
    from routes.title_searches import title_searches_bp
    from routes.rate_locks import rate_locks_bp
    from routes.disclosures import disclosures_bp
    from routes.udaap import udaap_bp
    from routes.clock import clock_bp

    app.register_blueprint(borrowers_bp)
    app.register_blueprint(loan_applications_bp)
    app.register_blueprint(verifications_bp)
    app.register_blueprint(appraisals_bp)
    app.register_blueprint(title_searches_bp)
    app.register_blueprint(rate_locks_bp)
    app.register_blueprint(disclosures_bp)
    app.register_blueprint(udaap_bp)
    app.register_blueprint(clock_bp)
