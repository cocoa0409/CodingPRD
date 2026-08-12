"""In-memory data store. Starts empty on every boot — no seeding."""

# Entity stores keyed by id
sellers = {}
agents = {}
listings = {}
verification_cases = {}
blackout_windows = {}
showing_requests = {}
access_credentials = {}
feedback_requests = {}
strike_records = {}
activity_events = {}


def reset_all():
    """Clear every store (used only in tests/defensive resets; never called at boot
    with data — stores simply start empty as module-level dicts)."""
    for store in (sellers, agents, listings, verification_cases, blackout_windows,
                  showing_requests, access_credentials, feedback_requests,
                  strike_records, activity_events):
        store.clear()
