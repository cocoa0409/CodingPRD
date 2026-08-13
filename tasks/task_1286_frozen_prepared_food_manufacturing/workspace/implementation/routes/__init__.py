from flask import Blueprint

bp = Blueprint("api", __name__)

# Import route modules for registration side effects.
from routes import (  # noqa: E402,F401
    clock,
    recipes,
    customers,
    orders,
    freezer,
    packaging,
    ccp,
    storage,
    complaints,
)
