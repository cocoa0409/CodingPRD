from . import (
    batches,
    certificates,
    clock_routes,
    contracts,
    flavorings,
    leaf_lots,
    lines,
    recipes,
    runs,
    suppliers,
)

BLUEPRINTS = [
    suppliers.bp,
    leaf_lots.bp,
    flavorings.bp,
    recipes.bp,
    batches.bp,
    lines.bp,
    runs.bp,
    contracts.bp,
    certificates.bp,
    clock_routes.bp,
]
