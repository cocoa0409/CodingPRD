from routes import clock, charters, applications, members, accounts, enrollments, dividends, meetings, reviews


def register_all(app):
    for bp in (clock.bp, charters.bp, applications.bp, members.bp, accounts.bp,
               enrollments.bp, dividends.bp, meetings.bp, reviews.bp):
        app.register_blueprint(bp)
