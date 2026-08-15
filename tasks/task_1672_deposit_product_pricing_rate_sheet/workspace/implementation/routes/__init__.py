from routes.products import bp as products_bp
from routes.sheets import bp as sheets_bp
from routes.deployments import bp as deployments_bp
from routes.scans import bp as scans_bp
from routes.cycles import bp as cycles_bp
from routes.promos import bp as promos_bp
from routes.exceptions import bp as exceptions_bp
from routes.accounts import bp as accounts_bp
from routes.funding import bp as funding_bp
from routes.bundles import bp as bundles_bp
from routes.enrollments import bp as enrollments_bp
from routes.notices import bp as notices_bp
from routes.migrations import bp as migrations_bp
from routes.clock import bp as clock_bp

ALL_BLUEPRINTS = [
    products_bp, sheets_bp, deployments_bp, scans_bp, cycles_bp, promos_bp,
    exceptions_bp, accounts_bp, funding_bp, bundles_bp, enrollments_bp,
    notices_bp, migrations_bp, clock_bp,
]
