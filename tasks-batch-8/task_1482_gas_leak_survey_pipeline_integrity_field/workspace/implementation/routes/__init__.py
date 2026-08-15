from flask import Blueprint

bp = Blueprint("integrity_program", __name__, url_prefix="/integrity-program")

# noqa: E402,F401 -- imported for route registration side effects
from . import segments  # noqa
from . import instruments  # noqa
from . import people  # noqa
from . import crews  # noqa
from . import survey_routes  # noqa
from . import survey_runs  # noqa
from . import leaks  # noqa
from . import orders  # noqa
from . import cp_readings  # noqa
from . import snapshots  # noqa
from . import reports  # noqa
from . import clock  # noqa
