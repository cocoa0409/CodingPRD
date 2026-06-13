"""Route blueprints registry."""
from routes.salons import bp as salons_bp
from routes.stylists import bp as stylists_bp
from routes.resources import bp as resources_bp
from routes.services import bp as services_bp
from routes.clients import bp as clients_bp
from routes.membership_plans import bp as membership_plans_bp
from routes.memberships import bp as memberships_bp
from routes.packages import bp as packages_bp
from routes.package_purchases import bp as package_purchases_bp
from routes.product_skus import bp as product_skus_bp
from routes.appointments import bp as appointments_bp
from routes.checkouts import bp as checkouts_bp
from routes.product_sales import bp as product_sales_bp

ALL_BLUEPRINTS = [
    salons_bp,
    stylists_bp,
    resources_bp,
    services_bp,
    clients_bp,
    membership_plans_bp,
    memberships_bp,
    packages_bp,
    package_purchases_bp,
    product_skus_bp,
    appointments_bp,
    checkouts_bp,
    product_sales_bp,
]
