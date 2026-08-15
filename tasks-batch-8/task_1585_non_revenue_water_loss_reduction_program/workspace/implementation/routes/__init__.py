from flask import Blueprint


def make_bp(name):
    return Blueprint(name, __name__)


# Imported for registration in app.py
from routes import clock, dmas, water_balance, night_flow, surveys, leaks, meters, cases, pressure, proposals, benchmarks, audit  # noqa: E402,F401
