"""Blueprint registry -- one module per domain area."""
from routes.ops import bp as ops_bp
from routes.setup import bp as setup_bp
from routes.prospectuses import bp as prospectuses_bp
from routes.applications import bp as applications_bp
from routes.permits import bp as permits_bp
from routes.plans import bp as plans_bp
from routes.guides import bp as guides_bp
from routes.assurance import bp as assurance_bp
from routes.reports import bp as reports_bp
from routes.enforcement import bp as enforcement_bp

BLUEPRINTS = [
    ops_bp,
    setup_bp,
    prospectuses_bp,
    applications_bp,
    permits_bp,
    plans_bp,
    guides_bp,
    assurance_bp,
    reports_bp,
    enforcement_bp,
]
