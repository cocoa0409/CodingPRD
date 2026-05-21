from flask import Flask

from .business_entities import bp as entities_bp
from .registered_agents import bp as agents_bp
from .operating_agreements import bp as agreements_bp
from .ein_applications import bp as ein_bp
from .annual_reports import bp as annual_bp
from .tax_assessments import bp as tax_bp
from .foreign_qualifications import bp as fq_bp
from .boi import bp as boi_bp
from .clock import bp as clock_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(entities_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(ein_bp)
    app.register_blueprint(annual_bp)
    app.register_blueprint(tax_bp)
    app.register_blueprint(fq_bp)
    app.register_blueprint(boi_bp)
    app.register_blueprint(clock_bp)
