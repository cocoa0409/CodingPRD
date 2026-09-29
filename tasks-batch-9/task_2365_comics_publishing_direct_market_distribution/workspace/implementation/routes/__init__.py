"""Blueprint registry."""

from routes.catalogs import catalogs_bp, solicitations_bp
from routes.finance import clock_bp, revenue_bp, statements_bp
from routes.production import (
    issues_bp,
    print_runs_bp,
    stages_bp,
    title_issues_bp,
)
from routes.retail import orders_bp, retailers_bp
from routes.roster import assignments_bp, creators_bp, titles_bp

blueprints = [
    clock_bp,
    creators_bp,
    titles_bp,
    title_issues_bp,
    assignments_bp,
    issues_bp,
    stages_bp,
    catalogs_bp,
    solicitations_bp,
    retailers_bp,
    orders_bp,
    print_runs_bp,
    revenue_bp,
    statements_bp,
]

__all__ = ["blueprints"]
