"""Blueprint registry — every collection is mounted at the service root."""

from routes.change_orders import bp as change_orders_bp
from routes.claims import bp as claims_bp
from routes.clock import bp as clock_bp
from routes.crews import bp as crews_bp
from routes.disclosures import bp as disclosures_bp
from routes.insurance import bp as insurance_bp
from routes.laboratories import bp as laboratories_bp
from routes.nfa_letters import bp as nfa_letters_bp
from routes.permits import bp as permits_bp
from routes.projects import bp as projects_bp
from routes.properties import bp as properties_bp
from routes.soil_samples import bp as soil_samples_bp
from routes.work_orders import bp as work_orders_bp

BLUEPRINTS = (
    properties_bp,
    projects_bp,
    disclosures_bp,
    permits_bp,
    crews_bp,
    work_orders_bp,
    laboratories_bp,
    soil_samples_bp,
    change_orders_bp,
    claims_bp,
    nfa_letters_bp,
    insurance_bp,
    clock_bp,
)
