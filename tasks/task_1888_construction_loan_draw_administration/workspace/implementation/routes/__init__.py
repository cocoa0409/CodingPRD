from routes import (
    borrowers,
    budget_lines,
    conversion_reviews,
    draw_documents,
    draw_line_items,
    draws,
    inspections,
    loans,
    reallocation_requests,
    retainage_releases,
)

ALL_BLUEPRINTS = [
    borrowers.bp,
    loans.bp,
    budget_lines.bp,
    draws.bp,
    draw_line_items.bp,
    draw_documents.bp,
    inspections.bp,
    reallocation_requests.bp,
    retainage_releases.bp,
    conversion_reviews.bp,
]


def register_blueprints(app):
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)
