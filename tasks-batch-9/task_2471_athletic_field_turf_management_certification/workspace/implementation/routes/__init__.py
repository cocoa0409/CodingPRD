"""Route registration. Importing this package attaches every endpoint."""

from routes.blueprint import bp, clock_bp  # noqa: F401
from routes import fields  # noqa: F401,E402
from routes import staff  # noqa: F401,E402
from routes import maintenance  # noqa: F401,E402
from routes import safety  # noqa: F401,E402
from routes import remediation  # noqa: F401,E402
from routes import bookings  # noqa: F401,E402
from routes import ledger  # noqa: F401,E402
from routes import certification  # noqa: F401,E402
from routes import capital  # noqa: F401,E402
from routes import clock  # noqa: F401,E402
