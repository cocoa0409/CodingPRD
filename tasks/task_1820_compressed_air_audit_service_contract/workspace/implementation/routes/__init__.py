"""Blueprint registry."""

from routes.clock import bp as clock_bp
from routes.facilities import bp as facilities_bp
from routes.compressors import bp as compressors_bp
from routes.demand_profiles import bp as demand_profiles_bp
from routes.leaks import bp as leaks_bp
from routes.maintenance import bp as maintenance_bp
from routes.retrofits import bp as retrofits_bp
from routes.savings import bp as savings_bp
from routes.contracts import bp as contracts_bp
from routes.tickets import bp as tickets_bp
from routes.rentals import bp as rentals_bp
from routes.certificates import bp as certificates_bp
from routes.credits import bp as credits_bp

ALL_BLUEPRINTS = [
    clock_bp,
    facilities_bp,
    compressors_bp,
    demand_profiles_bp,
    leaks_bp,
    maintenance_bp,
    retrofits_bp,
    savings_bp,
    contracts_bp,
    tickets_bp,
    rentals_bp,
    certificates_bp,
    credits_bp,
]
