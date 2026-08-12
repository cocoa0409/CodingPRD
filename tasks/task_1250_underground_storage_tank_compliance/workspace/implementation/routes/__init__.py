from routes.clock import bp as clock_bp
from routes.facilities import bp as facilities_bp
from routes.tanks import bp as tanks_bp
from routes.components import bp as components_bp
from routes.technicians import bp as technicians_bp
from routes.orders import bp as orders_bp
from routes.results import bp as results_bp
from routes.deficiencies import bp as deficiencies_bp
from routes.submissions import bp as submissions_bp
from routes.records import bp as records_bp
from routes.operators import bp as operators_bp
from routes.training import bp as training_bp
from routes.releases import bp as releases_bp
from routes.claims import bp as claims_bp

ALL_BLUEPRINTS = [
    clock_bp, facilities_bp, tanks_bp, components_bp, technicians_bp,
    orders_bp, results_bp, deficiencies_bp, submissions_bp, records_bp,
    operators_bp, training_bp, releases_bp, claims_bp,
]
