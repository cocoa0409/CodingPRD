"""Blueprint registration."""


def register_routes(app):
    from routes import (
        change_requests,
        clock,
        documentations,
        engagements,
        findings,
        models,
        monitoring,
        reports,
        vendor,
    )

    for module in (
        models,
        documentations,
        change_requests,
        engagements,
        findings,
        monitoring,
        vendor,
        reports,
        clock,
    ):
        app.register_blueprint(module.bp)
