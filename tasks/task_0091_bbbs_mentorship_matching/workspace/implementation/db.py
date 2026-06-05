"""In-memory data store. Starts EMPTY on every boot — no seeding.

Per-test-server isolation re-launches the process before every test, so the
store must come up empty and tests build all state through the API surface.
"""

# One dict per entity type, keyed by id.
volunteers = {}
background_checks = {}
guardians = {}
children = {}
match_proposals = {}
matches = {}
match_meetings = {}
activity_logs = {}
supervision_contacts = {}
exit_transitions = {}
outcome_surveys = {}


def reset():
    """Wipe all state (used only for completeness / fresh boot)."""
    for d in (
        volunteers,
        background_checks,
        guardians,
        children,
        match_proposals,
        matches,
        match_meetings,
        activity_logs,
        supervision_contacts,
        exit_transitions,
        outcome_surveys,
    ):
        d.clear()
