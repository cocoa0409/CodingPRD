"""Congregation Youth Mission Trips API — entry point.

Boots the Flask app from web.py with all route modules registered.
"""
import os

from web import app  # noqa: F401

import routes_core  # noqa: E402,F401   clock, programs, trips
import routes_people  # noqa: E402,F401  participants, registrations, consent forms
import routes_money  # noqa: E402,F401   payments, fundraising, scholarships
import routes_staff  # noqa: E402,F401   chaperones, checks, assignments, itinerary, lodging


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
