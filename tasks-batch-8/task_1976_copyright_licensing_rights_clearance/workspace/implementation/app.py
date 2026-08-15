"""Entry point: registers all routes and runs the server.

Storage is in-memory only and starts empty on every boot — no seeding,
no disk persistence, no caches. The logical clock reads exactly
2026-08-01T00:00:00Z before any clock-setting call (PRD 2.5).
"""
import os

from state import app  # noqa: F401
import routes_core  # noqa: F401  (clock, holders, assets, diligence, retire)
import routes_requests  # noqa: F401  (clearance requests, rounds, grant)
import routes_usage  # noqa: F401  (licenses, reservations, events, payments, alerts)
import routes_fairuse_takedown  # noqa: F401  (fair-use, takedowns)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
