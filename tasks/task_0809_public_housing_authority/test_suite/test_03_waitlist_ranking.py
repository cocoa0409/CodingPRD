"""Waitlist enrollment, lottery draw, preliminary vs final ranking, and purge."""
from test_helpers import (
    validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_applicant, create_waitlist, enroll, draw,
    claim_preference, verify_claim,
)

IC = TEST_USERS["intake_clerk_headers"]


def _entries_by_id(api, waitlist_id):
    data, _meta = validate_paginated(api.list_entries(waitlist_id, IC))
    return {e["id"]: e for e in data}


def test_preliminary_rank_orders_by_application_date(api):
    """PRD §3.3: "Before the draw — while the waitlist's lottery_drawn is false — the
    ranking is preliminary: the pool is the waitlist's PENDING entries, ordered
    solely by their applicant's application_date earliest-first, with preference
    points deliberately ignored because they are not yet locked in."

    Design: Difficulty/dual_variant_calc/waitlist_preliminary_vs_final_rank
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    a1 = create_applicant(api, "A1")
    set_clock(api, "2026-03-02T00:00:00Z")
    a2 = create_applicant(api, "A2")
    set_clock(api, "2026-03-03T00:00:00Z")
    a3 = create_applicant(api, "A3")
    wl = create_waitlist(api, bedroom_size=2)
    e1 = enroll(api, wl["id"], a1["id"])
    e2 = enroll(api, wl["id"], a2["id"])
    e3 = enroll(api, wl["id"], a3["id"])
    # A2 and A3 carry verified points, but preliminary ranking must ignore them.
    verify_claim(api, claim_preference(api, a2["id"], "VETERAN")["id"], "VERIFY")
    verify_claim(api, claim_preference(api, a3["id"], "INVOLUNTARY_DISPLACEMENT")["id"], "VERIFY")

    entries = _entries_by_id(api, wl["id"])
    assert entries[e1["id"]]["effective_rank"] == 1
    assert entries[e2["id"]]["effective_rank"] == 2
    assert entries[e3["id"]]["effective_rank"] == 3, \
        "preliminary rank must follow application_date ASC, not points"


def test_final_rank_orders_by_points_after_draw(api):
    """PRD §3.3: "After the draw — when lottery_drawn is true — the ranking is final:
    the pool is the waitlist's ACTIVE entries, ordered by total_points highest-first
    and, for equal points, by lottery_number lowest-first." PRD §3.2: "a VETERAN
    preference is worth 50 points, INVOLUNTARY_DISPLACEMENT 40".

    Design: Difficulty/dual_variant_calc/waitlist_preliminary_vs_final_rank
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    a1 = create_applicant(api, "A1")
    set_clock(api, "2026-03-02T00:00:00Z")
    a2 = create_applicant(api, "A2")
    set_clock(api, "2026-03-03T00:00:00Z")
    a3 = create_applicant(api, "A3")
    wl = create_waitlist(api, bedroom_size=2)
    e1 = enroll(api, wl["id"], a1["id"])
    e2 = enroll(api, wl["id"], a2["id"])
    e3 = enroll(api, wl["id"], a3["id"])
    verify_claim(api, claim_preference(api, a2["id"], "VETERAN")["id"], "VERIFY")
    verify_claim(api, claim_preference(api, a3["id"], "INVOLUNTARY_DISPLACEMENT")["id"], "VERIFY")

    draw(api, wl["id"])
    entries = _entries_by_id(api, wl["id"])
    assert entries[e2["id"]]["total_points"] == 50
    assert entries[e3["id"]]["total_points"] == 40
    assert entries[e1["id"]]["total_points"] == 0
    assert entries[e2["id"]]["effective_rank"] == 1, "A2 (50 pts) outranks earlier applicants after the draw"
    assert entries[e3["id"]]["effective_rank"] == 2
    assert entries[e1["id"]]["effective_rank"] == 3


def test_enroll_on_closed_waitlist_rejected(api):
    """PRD §3.3: "Enrollment is only permitted while the waitlist is OPEN; enrolling
    onto a CLOSED waitlist is rejected with ERR_WAITLIST_CLOSED."

    Design: Corner/validations/waitlist_closed_rejects_entry
    """
    app = create_applicant(api, "WLC")
    wl = create_waitlist(api, bedroom_size=2, status="CLOSED")
    resp = api.create_entry(wl["id"], {"applicant_id": app["id"]}, IC)
    validate_error(resp, ApiErrorId.ERR_WAITLIST_CLOSED)


def test_purge_removes_entry_stale_by_exactly_90_days(api):
    """PRD §3.3: "every ACTIVE entry whose last_contact_at is at least 90 days before
    the current logical time — that is, the whole-day difference between now and
    last_contact_at is 90 or more — transitions from ACTIVE to PURGED and is removed
    from the ranking".

    Design: Corner/endpoints/waitlist_purge_removes_stale_entry_at_90_days
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    app = create_applicant(api, "Stale")
    wl = create_waitlist(api, bedroom_size=2)
    entry = enroll(api, wl["id"], app["id"])
    draw(api, wl["id"])
    set_clock(api, "2026-05-30T00:00:00Z")  # exactly 90 days after last_contact_at
    api.purge_waitlist(wl["id"], IC)
    entries = _entries_by_id(api, wl["id"])
    # A purged entry leaves the ranking pool but is still fetchable via the list.
    assert entries[entry["id"]]["status"] == "PURGED", \
        "an entry stale by exactly 90 days must be PURGED"


def test_list_entries_pagination_envelope(api):
    """PRD §2.3: "Every list response includes limit, offset, total_count, and
    has_more inside the meta object of the envelope, where total_count reflects the
    full number of matching resources before the limit and offset are applied and
    has_more indicates whether further pages remain."

    Design: Corner/endpoints/list_entries_pagination_envelope
    """
    a1 = create_applicant(api, "P1")
    a2 = create_applicant(api, "P2")
    wl = create_waitlist(api, bedroom_size=2)
    enroll(api, wl["id"], a1["id"])
    enroll(api, wl["id"], a2["id"])
    data, meta = validate_paginated(api.list_entries(wl["id"], IC))
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False, "two entries fit the default page, so has_more is false"
    assert len(data) == 2
