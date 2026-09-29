from routes.facilities import bp as facilities_bp
from routes.infants import bp as infants_bp
from routes.encounters import bp as encounters_bp
from routes.followup import bp as followup_bp
from routes.diagnostics import bp as diagnostics_bp
from routes.navigation import bp as navigation_bp
from routes.compliance import bp as compliance_bp

BLUEPRINTS = (
    facilities_bp,
    infants_bp,
    encounters_bp,
    followup_bp,
    diagnostics_bp,
    navigation_bp,
    compliance_bp,
)
