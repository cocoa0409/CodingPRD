from flask import Blueprint

bp = Blueprint("ecoat", __name__)

# Route modules register themselves on this blueprint at import time.
from . import master_data  # noqa: E402,F401
from . import chemistry  # noqa: E402,F401
from . import lots  # noqa: E402,F401
from . import run_slots  # noqa: E402,F401
from . import quality  # noqa: E402,F401
from . import emissions  # noqa: E402,F401
