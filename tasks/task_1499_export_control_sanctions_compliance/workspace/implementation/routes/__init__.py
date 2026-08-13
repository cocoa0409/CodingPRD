from routes import (
    products,
    classifications,
    parties,
    screening_list,
    screening_results,
    orders,
    licenses,
    shipments,
    tcps,
    grants,
    violations,
    audit,
    clock,
)

BLUEPRINTS = [
    products.bp,
    classifications.bp,
    parties.bp,
    screening_list.bp,
    screening_results.bp,
    orders.bp,
    licenses.bp,
    shipments.bp,
    tcps.bp,
    grants.bp,
    violations.bp,
    audit.bp,
    clock.bp,
]


def register_routes(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
