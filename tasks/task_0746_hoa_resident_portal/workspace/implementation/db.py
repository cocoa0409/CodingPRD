"""In-memory data store. All dicts are reset every process boot; nothing is seeded."""

# Primary tables keyed by id
homeowners = {}
properties = {}
assessments = {}
payments = {}
autopay_mandates = {}
arc_requests = {}
arc_reviews = {}
violations = {}
amenities = {}
amenity_reservations = {}
motions = {}
ballots = {}
work_orders = {}
documents = {}

# Community-wide configuration
community_config = {
    "grace_policy": "STRICT",
}

# Logical clock — starts at 2026-03-01T00:00:00Z per PRD §2.9; never falls back to wall clock.
# Stored as ISO 8601 UTC "YYYY-MM-DDTHH:MM:SS.sssZ".
current_utc_iso = "2026-03-01T00:00:00.000Z"


def reset():
    """Wipe every store — used only if the process is somehow reused (harness normally
    kills and re-spawns, but this is defensive)."""
    for d in (
        homeowners, properties, assessments, payments, autopay_mandates,
        arc_requests, arc_reviews, violations, amenities, amenity_reservations,
        motions, ballots, work_orders, documents,
    ):
        d.clear()
    community_config["grace_policy"] = "STRICT"
    global current_utc_iso
    current_utc_iso = "2026-03-01T00:00:00.000Z"
