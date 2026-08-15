"""Route registration."""
from . import (
    clock,
    dividends,
    enrollments,
    fees,
    notices,
    orders,
    participants,
    plans,
    transfers,
    windows,
)

_MODULES = (
    plans,
    participants,
    enrollments,
    dividends,
    windows,
    orders,
    notices,
    transfers,
    fees,
    clock,
)


def register_routes(app):
    for m in _MODULES:
        app.register_blueprint(m.bp, url_prefix="/drip")
