"""Blueprint registration."""


def register_routes(app):
    from routes import (
        clock, fiscal_years, legal_entities, agreements, transactions,
        true_up_runs, studies, doc_packages, audit_cases, cash_pools,
    )
    for module in (clock, fiscal_years, legal_entities, agreements, transactions,
                   true_up_runs, studies, doc_packages, audit_cases, cash_pools):
        app.register_blueprint(module.bp)
