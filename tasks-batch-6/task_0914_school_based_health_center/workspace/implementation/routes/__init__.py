"""Blueprint registry — one module per resource group."""

from routes.charges import bp as charges_bp
from routes.clearances import bp as clearances_bp
from routes.clinicians import bp as clinicians_bp
from routes.consents import bp as consents_bp
from routes.enrollments import bp as enrollments_bp
from routes.immunizations import bp as immunizations_bp
from routes.notifications import bp as notifications_bp
from routes.ops import bp as ops_bp
from routes.referrals import bp as referrals_bp
from routes.reports import bp as reports_bp
from routes.schools import bp as schools_bp
from routes.screenings import bp as screenings_bp
from routes.students import bp as students_bp
from routes.telehealth import bp as telehealth_bp
from routes.visits import bp as visits_bp

BLUEPRINTS = [
    ops_bp,
    schools_bp,
    clinicians_bp,
    students_bp,
    enrollments_bp,
    consents_bp,
    visits_bp,
    clearances_bp,
    immunizations_bp,
    screenings_bp,
    referrals_bp,
    charges_bp,
    notifications_bp,
    telehealth_bp,
    reports_bp,
]
