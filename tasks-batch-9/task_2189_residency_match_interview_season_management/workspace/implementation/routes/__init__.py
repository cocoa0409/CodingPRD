"""HTTP surface: one blueprint per aggregate group."""

from routes.applicants import bp as applicants_bp
from routes.applications import bp as applications_bp
from routes.comms import bp as comms_bp
from routes.contracts import bp as contracts_bp
from routes.faculty import bp as faculty_bp
from routes.match import bp as match_bp
from routes.programs import bp as programs_bp
from routes.ranklists import bp as ranklists_bp
from routes.scorecards import bp as scorecards_bp
from routes.waves import bp as waves_bp

BLUEPRINTS = (
    programs_bp,
    applicants_bp,
    applications_bp,
    faculty_bp,
    waves_bp,
    scorecards_bp,
    ranklists_bp,
    match_bp,
    contracts_bp,
    comms_bp,
)
