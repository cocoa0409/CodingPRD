"""Blueprint registration."""

from routes.retailers import bp as retailers_bp
from routes.principals import bp as principals_bp
from routes.agreements import bp as agreements_bp
from routes.conflict_rules import bp as conflict_rules_bp
from routes.items import bp as items_bp
from routes.reviews import bp as reviews_bp
from routes.presentations import bp as presentations_bp
from routes.deals import bp as deals_bp
from routes.authorizations import bp as authorizations_bp
from routes.snapshots import bp as snapshots_bp
from routes.promotions import bp as promotions_bp
from routes.deductions import bp as deductions_bp
from routes.clock_route import bp as clock_bp

BLUEPRINTS = (
    retailers_bp,
    principals_bp,
    agreements_bp,
    conflict_rules_bp,
    items_bp,
    reviews_bp,
    presentations_bp,
    deals_bp,
    authorizations_bp,
    snapshots_bp,
    promotions_bp,
    deductions_bp,
    clock_bp,
)
