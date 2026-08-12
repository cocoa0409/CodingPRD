def register_routes(app):
    from . import (allergens, changeovers, clock, findings, incidents, lines,
                   matrix, procedures, products, recons, reworks, runs,
                   swabs, technicians)
    for mod in (allergens, changeovers, clock, findings, incidents, lines,
                matrix, procedures, products, recons, reworks, runs,
                swabs, technicians):
        app.register_blueprint(mod.bp)
