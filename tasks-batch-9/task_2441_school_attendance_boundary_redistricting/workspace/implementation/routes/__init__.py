from routes.setup import bp as setup_bp
from routes.planning import bp as planning_bp
from routes.implementation import bp as implementation_bp
from routes.clock import bp as clock_bp

BLUEPRINTS = (setup_bp, planning_bp, implementation_bp, clock_bp)
