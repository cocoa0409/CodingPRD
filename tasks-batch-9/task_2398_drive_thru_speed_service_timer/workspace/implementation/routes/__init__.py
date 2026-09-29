from routes.clock import bp as clock_bp
from routes.restaurants import bp as restaurants_bp
from routes.tier_policies import bp as tier_policies_bp
from routes.dayparts import bp as dayparts_bp
from routes.staff import bp as staff_bp
from routes.deployments import bp as deployments_bp
from routes.timer_loops import bp as timer_loops_bp
from routes.merge_slots import bp as merge_slots_bp
from routes.pull_forwards import bp as pull_forwards_bp
from routes.incidents import bp as incidents_bp
from routes.reports import bp as reports_bp
from routes.coaching import bp as coaching_bp
from routes.overrides import bp as overrides_bp

BLUEPRINTS = (
    clock_bp,
    restaurants_bp,
    tier_policies_bp,
    dayparts_bp,
    staff_bp,
    deployments_bp,
    timer_loops_bp,
    merge_slots_bp,
    pull_forwards_bp,
    incidents_bp,
    reports_bp,
    coaching_bp,
    overrides_bp,
)
