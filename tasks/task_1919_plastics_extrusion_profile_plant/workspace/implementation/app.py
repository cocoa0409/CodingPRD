"""Entry point: registers all routes and runs the server.

Storage is in-memory only and starts empty on every boot — no seeding,
no disk persistence, no caches.
"""
import os

from state import app  # noqa: F401
import routes_part1  # noqa: F401  (registers customer/profile/die/line/lot/formulation routes)
import routes_part2  # noqa: F401  (registers blend-batch / work-order routes)
import routes_part3  # noqa: F401  (registers assignment/run/spc/bundle/purge/index/clock routes)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
