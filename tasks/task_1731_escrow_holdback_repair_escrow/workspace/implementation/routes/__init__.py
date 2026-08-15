from flask import Blueprint

bp = Blueprint("escrow", __name__)

# Route modules register themselves on bp at import time.
from . import clock  # noqa: E402,F401
from . import files  # noqa: E402,F401
from . import holdbacks  # noqa: E402,F401
from . import approvals  # noqa: E402,F401
from . import bids  # noqa: E402,F401
from . import workorders  # noqa: E402,F401
from . import inspections  # noqa: E402,F401
from . import draws  # noqa: E402,F401
from . import extensions  # noqa: E402,F401
from . import disputes  # noqa: E402,F401
from . import pledges  # noqa: E402,F401
