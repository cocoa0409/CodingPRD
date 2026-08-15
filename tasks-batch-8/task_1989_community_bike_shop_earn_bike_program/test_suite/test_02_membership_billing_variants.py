"""Membership billing dual-variant tests (queue A: dual_variant_calc) plus the
session no-show billing-input filtering corner."""
from test_helpers import (
    api_client, validate_success,
    make_membership, book_session, start_and_close_session,
    set_clock, TEST_USERS, make_member_headers,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def _membership_with_sessions(tier: str, day_hours):
    """One membership with len(day_hours) BOOKED sessions on stand 1 in 2026-08,
    then all started+closed at clock 2026-08-20.

    day_hours: list of (day, hour) tuples.
    """
    m = make_membership(member_name=f"M {tier}", member_email=f"m{tier.lower()}@x.org",
                        tier=tier, end_date="2026-12-31")
    ids = []
    for day, hour in day_hours:
        s = book_session(
            m["id"], 1,
            f"2026-08-{day:02d}T{hour:02d}:00:00Z",
            f"2026-08-{day:02d}T{hour + 1:02d}:00:00Z",
        )
        ids.append(s["id"])
    set_clock("2026-08-20T00:00:00Z")
    for sid in ids:
        start_and_close_session(sid, m["id"])
    return m, ids


def test_billing_basic_per_session_cap_binds():
    """PRD §3.12: "Under the `BASIC` tier's per-session variant, the bill is 400
    cents per billable session, capped at 3000 cents for the month."

    Design: Difficulty/dual_variant_calc/membership_billing_tier_variants_diverge
    """
    m, _ = _membership_with_sessions("BASIC", [(d, 10) for d in range(2, 10)])
    data = validate_success(
        api_client.get_membership_billing(m["id"], DIRECTOR, params={"month": "2026-08"})
    )
    assert data["session_count"] == 8
    assert data["tier"] == "BASIC"
    # min(8 * 400, 3000) -> cap binds
    assert data["amount_cents"] == 3000


def test_billing_pro_flat_monthly_diverges_for_same_sessions():
    """PRD §3.12: "Under the `PRO` tier's flat-monthly variant, the bill is 2500
    cents regardless of session count."

    Design: Difficulty/dual_variant_calc/membership_billing_tier_variants_diverge
    """
    m, _ = _membership_with_sessions("PRO", [(d, 12) for d in range(2, 10)])
    data = validate_success(
        api_client.get_membership_billing(m["id"], DIRECTOR, params={"month": "2026-08"})
    )
    assert data["session_count"] == 8
    assert data["tier"] == "PRO"
    assert data["amount_cents"] == 2500


def test_billing_excludes_no_show_and_cancelled_sessions():
    """PRD §3.12: "`BOOKED`, `CANCELLED`, and `NO_SHOW` sessions never bill."
    PRD §3.12: "Under the `BASIC` tier's per-session variant, the bill is 400
    cents per billable session, capped at 3000 cents for the month."

    Design: Corner/state_machines/session_noshow_excluded_from_billing
    """
    m = make_membership(member_name="M B", member_email="mb@x.org", tier="BASIC",
                        end_date="2026-12-31")
    s1 = book_session(m["id"], 1, "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")
    s2 = book_session(m["id"], 1, "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
    s3 = book_session(m["id"], 1, "2026-08-04T10:00:00Z", "2026-08-04T11:00:00Z")
    s4 = book_session(m["id"], 1, "2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z")
    api_client.cancel_session(s4["id"], make_member_headers(m["id"]))
    set_clock("2026-08-20T00:00:00Z")
    start_and_close_session(s2["id"], m["id"])
    start_and_close_session(s3["id"], m["id"])
    sweep = validate_success(api_client.run_sweep(COORD))
    assert sweep["sessions_marked_no_show"] == 1
    s1_after = validate_success(api_client.get_session(s1["id"], COORD))
    assert s1_after["status"] == "NO_SHOW"

    billing = validate_success(
        api_client.get_membership_billing(m["id"], DIRECTOR, params={"month": "2026-08"})
    )
    assert billing["session_count"] == 2
    assert billing["amount_cents"] == 800
