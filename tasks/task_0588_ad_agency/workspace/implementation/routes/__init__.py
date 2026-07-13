from routes.campaigns import bp as campaigns_bp
from routes.deliverables import bp as deliverables_bp
from routes.invoices import bp as invoices_bp
from routes.media import bp as media_bp
from routes.reference import bp as reference_bp
from routes.retainers import bp as retainers_bp
from routes.sows import bp as sows_bp
from routes.time_entries import bp as time_entries_bp
from routes.vendor_costs import bp as vendor_costs_bp

BLUEPRINTS = (
    reference_bp,
    retainers_bp,
    sows_bp,
    campaigns_bp,
    deliverables_bp,
    time_entries_bp,
    vendor_costs_bp,
    media_bp,
    invoices_bp,
)
