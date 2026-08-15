from routes import (assignments, classes, clock, damage, equipment, lowboys,
                    mechanics, projects, readings, transport, workorders)


def register_routes(app):
    for mod in (clock, classes, equipment, readings, projects, assignments,
                workorders, mechanics, lowboys, transport, damage):
        app.register_blueprint(mod.bp)
