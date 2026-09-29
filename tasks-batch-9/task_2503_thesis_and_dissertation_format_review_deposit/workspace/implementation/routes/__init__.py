"""Blueprint registration."""


def register_routes(app):
    from routes import (
        committees,
        defense,
        deposits,
        embargo,
        integrity,
        permissions,
        reference,
        reviews,
        theses,
    )

    for module in (
        reference,
        theses,
        committees,
        defense,
        reviews,
        permissions,
        embargo,
        integrity,
        deposits,
    ):
        app.register_blueprint(module.bp)
