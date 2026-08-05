from routes.clock import bp as clock_bp
from routes.inmates import bp as inmates_bp
from routes.screenings import bp as screenings_bp
from routes.chronic import bp as chronic_bp
from routes.sickcall import bp as sickcall_bp
from routes.meds import bp as meds_bp
from routes.referrals import bp as referrals_bp
from routes.transport import bp as transport_bp
from routes.trust import bp as trust_bp
from routes.grievances import bp as grievances_bp
from routes.release import bp as release_bp
from routes.reports import bp as reports_bp

BLUEPRINTS = (
    clock_bp, inmates_bp, screenings_bp, chronic_bp, sickcall_bp, meds_bp,
    referrals_bp, transport_bp, trust_bp, grievances_bp, release_bp, reports_bp,
)
