from routes import (agreements, certificates, clients, clock_routes, equipment,
                    facilities, findings, holiday_windows, ingredients,
                    invoices, products, visits)

BLUEPRINTS = [
    clock_routes.bp,
    clients.bp,
    facilities.bp,
    equipment.bp,
    ingredients.bp,
    products.bp,
    visits.bp,
    findings.bp,
    agreements.bp,
    invoices.bp,
    certificates.bp,
    holiday_windows.bp,
]
