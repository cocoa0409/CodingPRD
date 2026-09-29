"""Blueprint registry."""

from routes.cohorts import bp as cohorts_bp
from routes.counselors import bp as counselors_bp
from routes.enrollments import bp as enrollments_bp
from routes.events import bp as events_bp
from routes.grants import bp as grants_bp
from routes.ops import bp as ops_bp
from routes.outreach import bp as outreach_bp
from routes.participants import bp as participants_bp
from routes.referrals import bp as referrals_bp
from routes.spaces import bp as spaces_bp
from routes.volunteers import bp as volunteers_bp

BLUEPRINTS = [
    ops_bp,
    referrals_bp,
    participants_bp,
    outreach_bp,
    spaces_bp,
    cohorts_bp,
    enrollments_bp,
    counselors_bp,
    volunteers_bp,
    events_bp,
    grants_bp,
]
