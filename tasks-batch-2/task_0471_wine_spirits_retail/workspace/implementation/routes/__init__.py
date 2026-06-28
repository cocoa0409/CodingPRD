"""Route registration. Importing this package registers all endpoints on the
Flask app (each submodule decorates handlers with @app.route at import time)."""
from . import clock        # noqa: F401
from . import customers    # noqa: F401
from . import id_scans     # noqa: F401
from . import catalog      # noqa: F401
from . import state_rules  # noqa: F401
from . import orders       # noqa: F401
from . import shipments    # noqa: F401
from . import club         # noqa: F401
from . import special_orders  # noqa: F401
