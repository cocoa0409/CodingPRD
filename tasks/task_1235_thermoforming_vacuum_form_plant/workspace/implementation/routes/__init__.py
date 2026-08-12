from flask import Blueprint

bp = Blueprint("api", __name__)

# Import route modules for registration side effects.
from routes import (  # noqa: E402,F401
    lots,
    regrind,
    tools,
    specs,
    orders,
    allocations,
    resources,
    runs,
    scrap,
    inspections,
    tasks,
    certs,
    clock,
)
