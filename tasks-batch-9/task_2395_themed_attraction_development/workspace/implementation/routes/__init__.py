"""Blueprint registration."""

from routes import commercial, packages, projects, rides, show


def register_all(app):
    app.register_blueprint(projects.bp)
    app.register_blueprint(rides.bp)
    app.register_blueprint(show.bp)
    app.register_blueprint(packages.bp)
    app.register_blueprint(commercial.bp)
