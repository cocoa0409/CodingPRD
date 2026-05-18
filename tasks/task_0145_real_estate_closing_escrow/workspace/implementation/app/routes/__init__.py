"""Aggregate the per-resource blueprints onto the Flask app."""
from __future__ import annotations

from flask import Flask

from app.routes.parties import bp as parties_bp
from app.routes.properties import bp as properties_bp
from app.routes.escrow_files import bp as escrow_files_bp
from app.routes.earnest_money import bp as emd_bp
from app.routes.title_searches import bp as title_searches_bp
from app.routes.title_policies import bp as title_policies_bp
from app.routes.ccr_disclosures import bp as ccr_bp
from app.routes.closing_disclosures import bp as cd_bp
from app.routes.wire_instructions import bp as wires_bp
from app.routes.disbursements import bp as disb_bp
from app.routes.exchanges import bp as exch_bp
from app.routes.clock import bp as clock_bp


def register_routes(app: Flask) -> None:
    app.register_blueprint(parties_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(escrow_files_bp)
    app.register_blueprint(emd_bp)
    app.register_blueprint(title_searches_bp)
    app.register_blueprint(title_policies_bp)
    app.register_blueprint(ccr_bp)
    app.register_blueprint(cd_bp)
    app.register_blueprint(wires_bp)
    app.register_blueprint(disb_bp)
    app.register_blueprint(exch_bp)
    app.register_blueprint(clock_bp)
