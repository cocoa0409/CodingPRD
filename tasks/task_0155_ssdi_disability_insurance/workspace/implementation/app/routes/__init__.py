"""Route registration. All blueprints are mounted at root."""

from flask import Flask

from app.routes.claimants import bp as claimants_bp
from app.routes.quarter_credits import bp as qc_bp
from app.routes.medical_evidence import bp as evidence_bp
from app.routes.applications import bp as applications_bp
from app.routes.hearing_slots import bp as hearing_slots_bp
from app.routes.child_auxiliaries import bp as child_aux_bp
from app.routes.ssi_supplements import bp as ssi_bp
from app.routes.cdr_reviews import bp as cdr_bp
from app.routes.clock_admin import bp as clock_bp


def register_blueprints(app: Flask) -> None:
    blueprints = (
        claimants_bp,
        qc_bp,
        evidence_bp,
        applications_bp,
        hearing_slots_bp,
        child_aux_bp,
        ssi_bp,
        cdr_bp,
        clock_bp,
    )
    for bp in blueprints:
        app.register_blueprint(bp)
