"""Blueprint registration for all route groups."""

from . import admin, students, plans, apps, recs, wbl, audit


def register_blueprints(app):
    app.register_blueprint(admin.bp)
    app.register_blueprint(students.bp)
    app.register_blueprint(plans.bp)
    app.register_blueprint(apps.bp)
    app.register_blueprint(recs.bp)
    app.register_blueprint(wbl.bp)
    app.register_blueprint(audit.bp)
