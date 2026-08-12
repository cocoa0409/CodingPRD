"""TPRM API server — entry point.

In-memory Flask implementation of the Third-Party Vendor Risk Management API.
All state lives in process-local dicts (see core.py); nothing is seeded at
startup, so every fresh boot starts with an empty store.
"""
import os

from core import app  # noqa: F401  (Flask app with error handlers)

# Route modules register their endpoints on the shared app at import time.
import routes_vendor  # noqa: F401,E402
import routes_dd_contract  # noqa: F401,E402
import routes_fp_cycle  # noqa: F401,E402
import routes_incident  # noqa: F401,E402
import routes_risk  # noqa: F401,E402
import routes_clock  # noqa: F401,E402


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')),
            threaded=True)
