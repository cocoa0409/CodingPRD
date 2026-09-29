"""Blueprint package. Every blueprint is mounted under the /cpo prefix."""
from routes.audit import bp as audit_bp
from routes.catalog import bp as catalog_bp
from routes.certifications import bp as certifications_bp
from routes.claims import bp as claims_bp
from routes.complaints import bp as complaints_bp
from routes.config_clock import bp as config_bp
from routes.inspections import bp as inspections_bp
from routes.marketing import bp as marketing_bp
from routes.participants import bp as participants_bp

BLUEPRINTS = (
    config_bp,
    catalog_bp,
    participants_bp,
    inspections_bp,
    certifications_bp,
    audit_bp,
    marketing_bp,
    claims_bp,
    complaints_bp,
)
