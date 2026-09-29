"""Blueprint registration for every endpoint in PRD section 4."""

from routes import (clock, complaints, contract_amendments, contract_usages,
                    line_items, master_contracts, member_agencies,
                    piggyback_analyses, solicitation_responses, solicitations,
                    state_law_rules, suppliers, usage_reports)

BLUEPRINTS = (
    clock.bp,
    state_law_rules.bp,
    solicitations.bp,
    suppliers.bp,
    solicitation_responses.bp,
    master_contracts.bp,
    line_items.bp,
    member_agencies.bp,
    piggyback_analyses.bp,
    contract_usages.bp,
    usage_reports.bp,
    contract_amendments.bp,
    complaints.bp,
)


def register_routes(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
