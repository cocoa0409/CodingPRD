"""Register all route blueprints."""
from __future__ import annotations

from flask import Flask


def register_routes(app: Flask) -> None:
    from . import (
        clock as clock_routes,
        claimants as claimant_routes,
        employers as employer_routes,
        claims as claim_routes,
        certifications as cert_routes,
        overpayments as overpayment_routes,
        appeals as appeal_routes,
        pandemic_extensions as ext_routes,
    )
    app.register_blueprint(clock_routes.bp)
    app.register_blueprint(claimant_routes.bp)
    app.register_blueprint(employer_routes.bp)
    app.register_blueprint(claim_routes.bp)
    app.register_blueprint(cert_routes.bp)
    app.register_blueprint(overpayment_routes.bp)
    app.register_blueprint(appeal_routes.bp)
    app.register_blueprint(ext_routes.bp)
