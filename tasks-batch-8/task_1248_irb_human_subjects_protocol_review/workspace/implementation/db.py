"""In-memory data store. Empty at every boot — nothing is seeded."""

# Entity tables: id -> dict
investigators = {}
irb_members = {}
protocols = {}
consent_documents = {}
review_assignments = {}
conflict_declarations = {}
board_meetings = {}
agenda_items = {}
modifications = {}
continuing_reviews = {}
adverse_events = {}
non_compliance_cases = {}
reliance_agreements = {}


def reset_all():
    for tbl in (
        investigators, irb_members, protocols, consent_documents,
        review_assignments, conflict_declarations, board_meetings,
        agenda_items, modifications, continuing_reviews, adverse_events,
        non_compliance_cases, reliance_agreements,
    ):
        tbl.clear()
