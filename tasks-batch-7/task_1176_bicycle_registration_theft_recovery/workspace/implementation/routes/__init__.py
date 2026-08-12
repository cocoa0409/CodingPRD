from routes.clock import bp as clock_bp
from routes.owners import bp as owners_bp
from routes.partner_orgs import bp as partner_orgs_bp
from routes.bicycles import bp as bicycles_bp
from routes.transfers import bp as transfers_bp
from routes.theft_reports import bp as theft_reports_bp
from routes.intakes import bp as intakes_bp
from routes.matches import bp as matches_bp
from routes.claims import bp as claims_bp
from routes.auctions import bp as auctions_bp
from routes.events import bp as events_bp
from routes.duplicate_flags import bp as duplicate_flags_bp
from routes.ledger import bp as ledger_bp
from routes.notifications import bp as notifications_bp

ALL_BLUEPRINTS = [
    clock_bp,
    owners_bp,
    partner_orgs_bp,
    bicycles_bp,
    transfers_bp,
    theft_reports_bp,
    intakes_bp,
    matches_bp,
    claims_bp,
    auctions_bp,
    events_bp,
    duplicate_flags_bp,
    ledger_bp,
    notifications_bp,
]
