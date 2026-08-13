"""Blueprint registration."""


def register_routes(app):
    from routes import (
        artworks,
        customers,
        dies,
        jobs,
        letters,
        materials,
        measurements,
        presses,
        rolls,
    )

    for module in (
        customers,
        artworks,
        materials,
        dies,
        presses,
        jobs,
        measurements,
        rolls,
        letters,
    ):
        app.register_blueprint(module.bp)
