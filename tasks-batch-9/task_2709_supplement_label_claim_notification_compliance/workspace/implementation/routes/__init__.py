"""Blueprint registry for the supplement label compliance API."""

from routes import (
    aers,
    claims,
    clock,
    coas,
    dossiers,
    ingredients,
    lines,
    lots,
    ndi,
    panels,
    products,
    suppliers,
)

BLUEPRINTS = (
    ingredients.bp,
    ndi.bp,
    products.bp,
    lines.bp,
    claims.bp,
    dossiers.bp,
    panels.bp,
    aers.bp,
    suppliers.bp,
    lots.bp,
    coas.bp,
    clock.bp,
)
