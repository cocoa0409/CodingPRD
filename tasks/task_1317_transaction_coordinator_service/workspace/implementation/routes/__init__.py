def register_routes(app):
    from routes import (roster, templates, subscriptions, files, milestones,
                        deadlines, reminders, documents, communications,
                        amendments, signatures, closing, invoices, clock_routes)
    for mod in (roster, templates, subscriptions, files, milestones, deadlines,
                reminders, documents, communications, amendments, signatures,
                closing, invoices, clock_routes):
        app.register_blueprint(mod.bp)
