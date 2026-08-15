"""Entry point: registers all routes on the shared Flask app and serves it."""
import os

from server import app  # noqa: F401
import routes_a  # noqa: F401  clock, landowners, seed zones, seed lots, crop batches
import routes_b  # noqa: F401  seedling orders, allocations
import routes_c  # noqa: F401  storage units, storage placements
import routes_d  # noqa: F401  planting contracts, crews, crew assignments
import routes_e  # noqa: F401  shipments, survival surveys, cost-share enrollments

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
