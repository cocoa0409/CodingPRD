from routes.projects import bp as projects_bp
from routes.trades import bp as trades_bp
from routes.walks import bp as walks_bp
from routes.items import bp as items_bp
from routes.docs import bp as docs_bp
from routes.sessions import bp as sessions_bp
from routes.releases import bp as releases_bp
from routes.warranty import bp as warranty_bp
from routes.clock import bp as clock_bp

ALL_BLUEPRINTS = [
    projects_bp, trades_bp, walks_bp, items_bp, docs_bp, sessions_bp,
    releases_bp, warranty_bp, clock_bp,
]
