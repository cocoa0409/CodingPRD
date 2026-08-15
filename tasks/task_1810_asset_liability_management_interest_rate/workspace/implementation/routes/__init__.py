"""Importing this package registers every endpoint on the shared blueprint."""

from routes.common import bp  # noqa: F401

from routes import (  # noqa: F401  (import side effects register routes)
    assumptions,
    backtests,
    books,
    breaches,
    clock,
    hedges,
    limits,
    reports,
    runs,
    scenarios,
)
