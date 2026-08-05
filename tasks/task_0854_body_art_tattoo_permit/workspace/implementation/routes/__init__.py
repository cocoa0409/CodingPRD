from routes.establishments import bp as establishments_bp
from routes.artists import bp as artists_bp
from routes.plan_reviews import bp as plan_reviews_bp
from routes.inspections import bp as inspections_bp
from routes.violations import bp as violations_bp
from routes.sterilization import bp as sterilization_bp
from routes.consents import bp as consents_bp
from routes.procedure_logs import bp as procedure_logs_bp
from routes.complaints import bp as complaints_bp
from routes.infections import bp as infections_bp
from routes.enforcement import bp as enforcement_bp
from routes.renewals import bp as renewals_bp
from routes.clock import bp as clock_bp

ALL_BLUEPRINTS = [
    establishments_bp,
    artists_bp,
    plan_reviews_bp,
    inspections_bp,
    violations_bp,
    sterilization_bp,
    consents_bp,
    procedure_logs_bp,
    complaints_bp,
    infections_bp,
    enforcement_bp,
    renewals_bp,
    clock_bp,
]
