"""Route blueprints, all mounted under the /ladder-ops prefix."""

from routes import (
    consumers,
    design_revisions,
    incidents,
    lab,
    listings,
    product_documents,
    production,
    products,
    recalls,
)

BLUEPRINTS = (
    products.bp,
    design_revisions.bp,
    product_documents.bp,
    lab.bp,
    production.bp,
    listings.bp,
    consumers.bp,
    incidents.bp,
    recalls.bp,
)
