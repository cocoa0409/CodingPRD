"""Route blueprints, all mounted under /lease-buyouts."""

from routes.portfolios import bp as portfolios_bp
from routes.facilities import bp as facilities_bp
from routes.assets import bp as assets_bp
from routes.streams import bp as streams_bp
from routes.deals import bp as deals_bp
from routes.title import bp as title_bp
from routes.servicing import bp as servicing_bp
from routes.admin import bp as admin_bp

BLUEPRINTS = (
    portfolios_bp,
    facilities_bp,
    assets_bp,
    streams_bp,
    deals_bp,
    title_bp,
    servicing_bp,
    admin_bp,
)
