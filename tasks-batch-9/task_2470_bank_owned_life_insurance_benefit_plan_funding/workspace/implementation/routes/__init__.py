"""Blueprint modules, one per domain area."""

from routes.assessments import bp as assessments_bp
from routes.capital import bp as capital_bp
from routes.carriers import bp as carriers_bp
from routes.claims import bp as claims_bp
from routes.clock import bp as clock_bp
from routes.consents import bp as consents_bp
from routes.diligence import bp as diligence_bp
from routes.dispositions import bp as dispositions_bp
from routes.employees import bp as employees_bp
from routes.nqdc import bp as nqdc_bp
from routes.policies import bp as policies_bp
from routes.products import bp as products_bp
from routes.purchase_requests import bp as purchase_requests_bp

ALL_BLUEPRINTS = (
    clock_bp,
    capital_bp,
    carriers_bp,
    products_bp,
    diligence_bp,
    employees_bp,
    consents_bp,
    purchase_requests_bp,
    policies_bp,
    nqdc_bp,
    claims_bp,
    dispositions_bp,
    assessments_bp,
)
