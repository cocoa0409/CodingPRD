"""Route blueprints."""
from .clock_routes import bp as clock_bp
from .segments import bp as segments_bp
from .residents import bp as residents_bp
from .requests import bp as requests_bp
from .signatures import bp as signatures_bp
from .studies import bp as studies_bp
from .plans import bp as plans_bp
from .cycles import bp as cycles_bp
from .ballots import bp as ballots_bp
from .workorders import bp as workorders_bp
from .removals import bp as removals_bp

ALL_BLUEPRINTS = [
    clock_bp, segments_bp, residents_bp, requests_bp, signatures_bp,
    studies_bp, plans_bp, cycles_bp, ballots_bp, workorders_bp, removals_bp,
]
