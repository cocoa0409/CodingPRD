"""Route registration."""


def register_routes(app):
    from routes.rooms import bp as rooms_bp
    from routes.tour_routes import bp as tour_routes_bp
    from routes.scripts import bp as scripts_bp
    from routes.slots import bp as slots_bp
    from routes.docents import bp as docents_bp
    from routes.shifts import bp as shifts_bp
    from routes.members import bp as members_bp
    from routes.bookings import bp as bookings_bp
    from routes.surveys import bp as surveys_bp
    from routes.incidents import bp as incidents_bp
    from routes.ops import bp as ops_bp

    app.register_blueprint(rooms_bp)
    app.register_blueprint(tour_routes_bp)
    app.register_blueprint(scripts_bp)
    app.register_blueprint(slots_bp)
    app.register_blueprint(docents_bp)
    app.register_blueprint(shifts_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(surveys_bp)
    app.register_blueprint(incidents_bp)
    app.register_blueprint(ops_bp)
