"""Blueprint registration."""


def register_routes(app):
    from routes import (
        assessment_schedules,
        associations,
        audit_engagements,
        clock_route,
        components,
        defect_claims,
        directors,
        lots,
        records_items,
        reserve_studies,
        subsidy_entries,
        turnover_cases,
        vendor_contracts,
    )

    for module in (
        associations,
        lots,
        components,
        turnover_cases,
        directors,
        records_items,
        subsidy_entries,
        audit_engagements,
        reserve_studies,
        defect_claims,
        vendor_contracts,
        assessment_schedules,
        clock_route,
    ):
        app.register_blueprint(module.bp)
