"""Temporal overlap on two resources with deliberately different interval
semantics.

A Partner's engagement-quality-review capacity counts overlapping half-open
intervals in aggregate with no buffer, while a PeerReviewer's on-site window is
tested pairwise with a 5-day travel buffer added to the existing window's end
only.
"""
from datetime import datetime

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_errors import (
    ERR_EQR_CAPACITY_EXCEEDED,
    ERR_REVIEWER_WINDOW_CONFLICT,
)
from test_helpers.assertions import assert_fields, created_entity, read_entity
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.test_users import (
    make_committee_headers,
    make_engagement_partner_headers,
    make_eq_reviewer_headers,
    make_qc_director_headers,
    make_system_admin_headers,
)

CLOSING_CLOCK = "2026-08-10T00:00:00Z"


def _instant(value):
    assert value is not None, "expected an instant, got None"
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _assert_same_instant(actual, expected):
    """Compare two ISO-8601 UTC instants regardless of fractional-digit form."""
    assert _instant(actual) == _instant(expected), (
        f"expected instant {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Partner aggregate EQR capacity over half-open intervals
# ---------------------------------------------------------------------------
def _reviewer_holding_two_open_and_two_closed_reviews(api):
    """One EQ reviewer with four reviews: two whose concluded_at closes their
    interval (CONCURRED and WITHDRAWN) and two still open (ASSIGNED and
    IN_PROGRESS)."""
    fixtures.set_clock(api, DEFAULT_CLOCK)
    admin = make_system_admin_headers()
    firm = created_entity(
        api.create_firm(
            f.firm_payload(
                legal_name="Barrowfield Kyle LLP",
                state_code="CA",
                aa_hours_last_year=400,
                peer_review_year_end="2026-12-31",
            ),
            headers=admin,
        )
    )
    ep = created_entity(
        api.create_partner(
            firm["id"],
            f.partner_payload(
                full_name="Ines Vale",
                cpa_license_state="CA",
                designations=["ENGAGEMENT_PARTNER"],
                cpe_hours_last_3y=200,
            ),
            headers=admin,
        )
    )
    qc = created_entity(
        api.create_partner(
            firm["id"],
            f.partner_payload(
                full_name="Quinn Cade",
                cpa_license_state="CA",
                designations=["QC_DIRECTOR"],
                cpe_hours_last_3y=200,
            ),
            headers=admin,
        )
    )
    reviewer = created_entity(
        api.create_partner(
            firm["id"],
            f.partner_payload(
                full_name="Odile Frey",
                cpa_license_state="CA",
                designations=["EQ_REVIEWER"],
                cpe_hours_last_3y=240,
            ),
            headers=admin,
        )
    )
    ep_headers = make_engagement_partner_headers(ep["id"])
    qc_headers = make_qc_director_headers(qc["id"])
    reviewer_headers = make_eq_reviewer_headers(reviewer["id"])

    engagements = {}
    for key, client_name in (
        ("e1", "Alder Freight"),
        ("e2", "Bramble Dairy"),
        ("e3", "Cobble Press"),
        ("e4", "Dunlin Foods"),
        ("e5", "Ember Mills"),
        ("e6", "Fallow Glass"),
    ):
        engagement = created_entity(
            api.create_engagement(
                f.engagement_payload(
                    firm["id"],
                    ep["id"],
                    client_name=client_name,
                    engagement_type="AUDIT",
                    period_end="2026-06-30",
                    is_public_interest=False,
                ),
                headers=ep_headers,
            )
        )
        engagements[key] = read_entity(
            api.create_workflow_transition(
                engagement["id"], f.workflow_transition_payload("FIELDWORK"),
                headers=ep_headers,
            )
        )

    def assign(engagement):
        return created_entity(
            api.assign_quality_review(
                engagement["id"],
                f.quality_review_assignment_payload(
                    reviewer["id"], engagement["version"]
                ),
                headers=qc_headers,
            )
        )

    # Two reviews that will be closed: one concurred, one withdrawn.
    eqr_a = assign(engagements["e1"])
    read_entity(
        api.create_quality_review_transition(
            eqr_a["id"], f.quality_review_transition_payload("IN_PROGRESS"),
            headers=reviewer_headers,
        )
    )
    eqr_b = assign(engagements["e2"])

    fixtures.set_clock(api, CLOSING_CLOCK)
    eqr_a = read_entity(
        api.create_quality_review_transition(
            eqr_a["id"], f.quality_review_transition_payload("CONCURRED"),
            headers=reviewer_headers,
        )
    )
    eqr_b = read_entity(
        api.create_quality_review_transition(
            eqr_b["id"], f.quality_review_transition_payload("WITHDRAWN"),
            headers=admin,
        )
    )

    # Two reviews that stay open, so exactly two intervals overlap a candidate.
    eqr_c = assign(engagements["e3"])
    eqr_d = assign(engagements["e4"])
    read_entity(
        api.create_quality_review_transition(
            eqr_d["id"], f.quality_review_transition_payload("IN_PROGRESS"),
            headers=reviewer_headers,
        )
    )
    return {
        "firm": firm,
        "reviewer": reviewer,
        "qc_headers": qc_headers,
        "ep_headers": ep_headers,
        "engagements": engagements,
        "eqr_a": eqr_a,
        "eqr_b": eqr_b,
        "eqr_c": eqr_c,
        "eqr_d": eqr_d,
    }


def test_eqr_assignment_succeeds_because_closed_intervals_do_not_count(api):
    """Reviews with a non-null concluded_at close their half-open interval, so
    a reviewer holding two open reviews may take a third.

    "Reviews that reached `CONCURRED` or `WITHDRAWN` have a non-null
    `concluded_at` and therefore close their interval."

    Design: Difficulty/resource_temporal_overlap/partner_eqr_aggregate_capacity_counts_only_intervals_still_open
    """
    ctx = _reviewer_holding_two_open_and_two_closed_reviews(api)

    _assert_same_instant(ctx["eqr_a"]["concluded_at"], CLOSING_CLOCK)
    _assert_same_instant(ctx["eqr_b"]["concluded_at"], CLOSING_CLOCK)

    response = api.assign_quality_review(
        ctx["engagements"]["e5"]["id"],
        f.quality_review_assignment_payload(
            ctx["reviewer"]["id"], ctx["engagements"]["e5"]["version"]
        ),
        headers=ctx["qc_headers"],
    )
    eqr_e = created_entity(response)
    assert_fields(
        eqr_e, state="ASSIGNED", reviewer_partner_id=ctx["reviewer"]["id"]
    )

    reviewer = read_entity(
        api.get_partner(ctx["reviewer"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(reviewer, open_eqr_count=3)


def test_eqr_assignment_refused_when_three_intervals_are_still_open(api):
    """A partner may hold at most three concurrent open engagement quality
    reviews; a fourth overlapping assignment is refused.

    "If three or more existing intervals overlap, the assignment is refused
    with `ERR_EQR_CAPACITY_EXCEEDED` - a partner may hold at most three
    concurrent open engagement quality reviews."

    Design: Difficulty/resource_temporal_overlap/partner_eqr_aggregate_capacity_counts_only_intervals_still_open
    """
    ctx = _reviewer_holding_two_open_and_two_closed_reviews(api)

    created_entity(
        api.assign_quality_review(
            ctx["engagements"]["e5"]["id"],
            f.quality_review_assignment_payload(
                ctx["reviewer"]["id"], ctx["engagements"]["e5"]["version"]
            ),
            headers=ctx["qc_headers"],
        )
    )

    response = api.assign_quality_review(
        ctx["engagements"]["e6"]["id"],
        f.quality_review_assignment_payload(
            ctx["reviewer"]["id"], ctx["engagements"]["e6"]["version"]
        ),
        headers=ctx["qc_headers"],
    )
    validate_error(response, ERR_EQR_CAPACITY_EXCEEDED, expected_status=409)

    engagement = read_entity(
        api.get_engagement(
            ctx["engagements"]["e6"]["id"], headers=ctx["ep_headers"]
        )
    )
    assert_fields(engagement, workflow_state="FIELDWORK")
    reviewer = read_entity(
        api.get_partner(ctx["reviewer"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(reviewer, open_eqr_count=3)


# ---------------------------------------------------------------------------
# PeerReviewer pairwise window collision with a one-sided travel buffer
# ---------------------------------------------------------------------------
def _roster_reviewer_with_one_occupied_window(api):
    """One roster reviewer already holding 2026-09-01..2026-09-15 in PLANNING,
    plus three unassigned reviews probing the shape of the collision test."""
    fixtures.set_clock(api, DEFAULT_CLOCK)
    admin = make_system_admin_headers()
    committee = make_committee_headers()

    firms = {}
    for key, legal_name in (
        ("a", "Marlow Quill LLP"),
        ("b", "Ossary Bent LLP"),
        ("c", "Pellamy Rook LLP"),
        ("d", "Quarrenden Ash LLP"),
    ):
        firms[key] = created_entity(
            api.create_firm(
                f.firm_payload(
                    legal_name=legal_name,
                    state_code="CA",
                    aa_hours_last_year=400,
                    peer_review_year_end="2026-12-31",
                ),
                headers=admin,
            )
        )

    reviewer = created_entity(
        api.create_peer_reviewer(
            f.peer_reviewer_payload(
                reviewer_firm_name="Sennet Peer Review PC",
                license_state="CA",
                qualified_categories=[],
                max_concurrent_reviews=3,
                experience_hours=5000,
            ),
            headers=committee,
        )
    )

    def schedule(firm, start, end):
        return created_entity(
            api.create_peer_review(
                firm["id"],
                f.peer_review_payload(
                    review_type="SYSTEM_REVIEW",
                    year_end="2026-12-31",
                    scheduled_window_start=start,
                    scheduled_window_end=end,
                ),
                headers=committee,
            )
        )

    reviews = {
        "a": schedule(firms["a"], "2026-09-01", "2026-09-15"),
        "b": schedule(firms["b"], "2026-09-15", "2026-09-25"),
        "c": schedule(firms["c"], "2026-09-20", "2026-09-30"),
        "d": schedule(firms["d"], "2026-08-20", "2026-09-01"),
    }
    occupied = read_entity(
        api.assign_peer_reviewer(
            reviews["a"]["id"], f.reviewer_assignment_payload(reviewer["id"]),
            headers=committee,
        )
    )
    assert_fields(
        occupied, state="PLANNING", assigned_reviewer_id=reviewer["id"]
    )
    return {
        "committee": committee,
        "firms": firms,
        "reviewer": reviewer,
        "reviews": reviews,
    }


def test_window_starting_on_the_existing_end_date_conflicts(api):
    """The 5-day travel buffer extends the existing window's end, so a window
    starting on that end date still collides.

    "A new window starting exactly on an existing window's end date therefore
    collides, while one starting exactly 5 days after that end date does not."

    Design: Difficulty/resource_temporal_overlap/peer_reviewer_travel_buffer_extends_only_the_existing_window_end
    """
    ctx = _roster_reviewer_with_one_occupied_window(api)

    response = api.assign_peer_reviewer(
        ctx["reviews"]["b"]["id"],
        f.reviewer_assignment_payload(ctx["reviewer"]["id"]),
        headers=ctx["committee"],
    )
    validate_error(response, ERR_REVIEWER_WINDOW_CONFLICT, expected_status=409)

    review = read_entity(
        api.get_peer_review(ctx["reviews"]["b"]["id"], headers=ctx["committee"])
    )
    assert_fields(review, state="SCHEDULED", assigned_reviewer_id=None)

    firm = read_entity(
        api.get_firm(ctx["firms"]["b"]["id"], headers=ctx["committee"])
    )
    assert_fields(firm, unassigned_review_flag=False)

    reviewer = read_entity(
        api.get_peer_reviewer(ctx["reviewer"]["id"], headers=ctx["committee"])
    )
    assert_fields(reviewer, active_review_count=1)


def test_window_starting_five_days_after_the_existing_end_does_not_conflict(api):
    """A window starting exactly the buffer length after the existing end is
    clear, because the comparison against the extended end is strict.

    "one starting exactly 5 days after that end date does not"

    Design: Difficulty/resource_temporal_overlap/peer_reviewer_travel_buffer_extends_only_the_existing_window_end
    """
    ctx = _roster_reviewer_with_one_occupied_window(api)

    assigned = read_entity(
        api.assign_peer_reviewer(
            ctx["reviews"]["c"]["id"],
            f.reviewer_assignment_payload(ctx["reviewer"]["id"]),
            headers=ctx["committee"],
        )
    )
    assert_fields(
        assigned, state="PLANNING", assigned_reviewer_id=ctx["reviewer"]["id"]
    )

    review = read_entity(
        api.get_peer_review(ctx["reviews"]["c"]["id"], headers=ctx["committee"])
    )
    assert_fields(
        review, state="PLANNING", assigned_reviewer_id=ctx["reviewer"]["id"]
    )
    reviewer = read_entity(
        api.get_peer_reviewer(ctx["reviewer"]["id"], headers=ctx["committee"])
    )
    assert_fields(reviewer, active_review_count=2)


def test_window_ending_on_the_existing_start_date_does_not_conflict(api):
    """The buffer is one-sided: the clause comparing the existing start to the
    new window's end carries no buffer at all.

    "the second clause r.scheduled_window_start < new.scheduled_window_end has
    no buffer at all"

    Design: Difficulty/resource_temporal_overlap/peer_reviewer_travel_buffer_extends_only_the_existing_window_end
    """
    ctx = _roster_reviewer_with_one_occupied_window(api)

    read_entity(
        api.assign_peer_reviewer(
            ctx["reviews"]["c"]["id"],
            f.reviewer_assignment_payload(ctx["reviewer"]["id"]),
            headers=ctx["committee"],
        )
    )

    assigned = read_entity(
        api.assign_peer_reviewer(
            ctx["reviews"]["d"]["id"],
            f.reviewer_assignment_payload(ctx["reviewer"]["id"]),
            headers=ctx["committee"],
        )
    )
    assert_fields(
        assigned, state="PLANNING", assigned_reviewer_id=ctx["reviewer"]["id"]
    )

    review = read_entity(
        api.get_peer_review(ctx["reviews"]["d"]["id"], headers=ctx["committee"])
    )
    assert_fields(review, state="PLANNING")
    reviewer = read_entity(
        api.get_peer_reviewer(ctx["reviewer"]["id"], headers=ctx["committee"])
    )
    assert_fields(reviewer, active_review_count=3)
