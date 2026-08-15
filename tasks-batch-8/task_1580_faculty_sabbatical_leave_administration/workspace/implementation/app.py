"""Entry point: registers all routes and runs the server.

Boots with a completely empty in-memory store; the logical clock reads
exactly 2026-08-01T00:00:00Z until moved via POST /_clock/set_current_utc.
"""
import os

from flask_app import app

# Route modules register themselves against `app` on import.
import routes_org  # noqa: F401,E402
import routes_cycle  # noqa: F401,E402
import routes_exec  # noqa: F401,E402

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    app.run(host='0.0.0.0', port=port)
