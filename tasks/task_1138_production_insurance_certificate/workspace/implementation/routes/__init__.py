"""API blueprint and route-module registration."""

from flask import Blueprint

bp = Blueprint("api", __name__)

# Route modules attach their handlers to bp on import.
from routes import (  # noqa: E402,F401
    clock,
    productions,
    policies,
    cast,
    certificates,
    claims,
    clearances,
    bond,
    travel,
    audits,
    flat,
)
