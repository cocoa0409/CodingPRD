"""Route blueprints, one module per resource family."""

from routes.projects import bp as projects_bp
from routes.deliverables import bp as deliverables_bp
from routes.talent import bp as talent_bp
from routes.physical import bp as physical_bp
from routes.compliance import bp as compliance_bp
from routes.crew import bp as crew_bp
from routes.clock import bp as clock_bp

ALL_BLUEPRINTS = (
    projects_bp,
    deliverables_bp,
    talent_bp,
    physical_bp,
    compliance_bp,
    crew_bp,
    clock_bp,
)
