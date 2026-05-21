"""Blueprint registration. All routes mount under the /housing-voucher prefix."""

from flask import Flask

from app.routes.applicants import bp as applicants_bp
from app.routes.vouchers import bp as vouchers_bp
from app.routes.units import bp as units_bp
from app.routes.payment_standards import bp as ps_bp
from app.routes.tenancies import bp as tenancies_bp
from app.routes.inspections import bp as inspections_bp
from app.routes.rent_reasonableness import bp as rrr_bp
from app.routes.annual_reviews import bp as ar_bp
from app.routes.portability import bp as pr_bp
from app.routes.hap import bp as hap_bp
from app.routes.clock_sweeps import bp as clock_bp


def register_blueprints(app: Flask, api_prefix: str) -> None:
    blueprints = (
        applicants_bp,
        vouchers_bp,
        units_bp,
        ps_bp,
        tenancies_bp,
        inspections_bp,
        rrr_bp,
        ar_bp,
        pr_bp,
        hap_bp,
        clock_bp,
    )
    for bp in blueprints:
        app.register_blueprint(bp, url_prefix=api_prefix)
