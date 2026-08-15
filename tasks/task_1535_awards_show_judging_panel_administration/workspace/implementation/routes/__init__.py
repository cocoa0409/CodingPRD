"""Blueprint registration."""
from . import (
    clock_route, seasons, categories, entrants, entries, invoices, judges,
    rounds, finalists, ceremonies, fulfillment, appeals,
)

BLUEPRINTS = [
    clock_route.bp,
    seasons.bp,
    categories.bp,
    entrants.bp,
    entries.bp,
    invoices.bp,
    judges.bp,
    rounds.bp,
    finalists.bp,
    ceremonies.bp,
    fulfillment.bp,
    appeals.bp,
]
