"""Reunion events, committees, memberships, and publications (PRD §3.3, §3.8)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_reunion_event,
    assert_membership,
    assert_publication,
    create_record,
    create_event,
    create_committee,
    create_tier,
    invite_member,
    accept_membership,
    set_clock,
    setup_event_with_chair,
    setup_committee_formed_event,
    setup_open_event,
    create_publication_for_event,
    current_event,
    TEST_USERS,
    make_committee_volunteer_headers,
)

STAFF = TEST_USERS["staff_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def test_event_initial_state_planning_and_gated_posture(api):
    """PRD §3.3: "A reunion event is born in `PLANNING` when staff create it"
    and "A fresh event has `committee_count` of 0, `total_revenue_cents` of 0,
    and a derived `posture` of `GATED`."

    Design: Corner/state_machines/event_initial_state_planning_and_gated_posture
    """
    resp = api.create_event(
        {
            "class_year": 2001,
            "title": "R",
            "event_date": "2026-09-01T18:00:00Z",
            "committee_quorum_required": 3,
        },
        STAFF,
    )
    data = validate_success(resp, 201)
    assert_reunion_event(data)
    assert data["status"] == "PLANNING"
    assert data["posture"] == "GATED"
    assert data["committee_count"] == 0
    assert data["total_revenue_cents"] == 0


def test_open_registration_without_quorum_rejected(api):
    """PRD §3.3: "Opening registration moves it `COMMITTEE_FORMED →
    OPEN_FOR_REGISTRATION` under two checks: `committee_count` must be at
    least `committee_quorum_required` (else `ERR_QUORUM_NOT_MET`)".

    Design: Corner/state_machines/open_registration_without_quorum_rejected
    """
    ctx = setup_committee_formed_event(
        event_overrides={"committee_quorum_required": 3}
    )
    event_id = ctx["event"]["id"]
    assert ctx["event"]["committee_count"] == 1

    resp = api.open_registration(event_id, STAFF)
    validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET)

    event = validate_success(api.get_event(event_id, STAFF))
    assert event["status"] == "COMMITTEE_FORMED"


def test_err_chair_exists_triggerable(api):
    """PRD §3.3: "if the accepted `role` is `CHAIR`, the committee's
    `chair_membership_id` is set to this membership, and only one `ACTIVE`
    CHAIR may exist per committee — a second acceptance as CHAIR while
    another CHAIR is active fails with `ERR_CHAIR_EXISTS`."

    Design: Corner/errors/err_chair_exists_triggerable
    """
    chair_a = create_record(full_name="HA", primary_email="ha@x.com")
    chair_b = create_record(full_name="HB", primary_email="hb@x.com")
    event = create_event()
    committee = create_committee(event["id"])
    mem_a = invite_member(committee["id"], chair_a["id"], role="CHAIR")
    mem_b = invite_member(committee["id"], chair_b["id"], role="CHAIR")
    accept_membership(mem_a["id"], chair_a["id"])

    resp = api.accept_membership(mem_b["id"], make_committee_volunteer_headers(chair_b["id"]))
    validate_error(resp, ApiErrorId.ERR_CHAIR_EXISTS)

    membership = validate_success(api.get_membership(mem_b["id"], STAFF))
    assert membership["status"] == "INVITED"


def test_err_duplicate_child_second_committee(api):
    """PRD §3.3: "Exactly one `ReunionCommittee` may exist per event; staff
    create it with a display `name`, and a second attempt fails with
    `ERR_DUPLICATE_CHILD`."

    Design: Corner/errors/err_duplicate_child_second_committee
    """
    event = create_event()
    create_committee(event["id"], name="C1")

    resp = api.create_committee(event["id"], {"name": "C2"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CHILD)


def test_membership_accept_on_locked_committee_rejected(api):
    """PRD §3.3: "Acceptance also requires the parent committee's `locked`
    flag to be false (`ERR_COMMITTEE_LOCKED`)" and "Opening locks the
    committee — `locked` becomes true and all membership mutations are
    thereafter rejected".

    Design: Corner/state_machines/membership_accept_on_locked_committee_rejected
    """
    ctx = setup_committee_formed_event(
        event_overrides={"event_date": "2026-09-01T18:00:00Z"},
    )
    volunteer = create_record(full_name="LVol", primary_email="lvol@x.com")
    # The invitation must exist BEFORE opening: per PRD §3.3, opening locks
    # the committee and "all membership mutations are thereafter rejected",
    # so inviting after the lock is itself rejected.
    invited = invite_member(ctx["committee"]["id"], volunteer["id"], role="MEMBER")
    create_tier(
        ctx["event"]["id"],
        name="GA", base_price_cents=1000, capacity=0,
        sales_start="2026-05-01T00:00:00Z", sales_end="2026-09-01T00:00:00Z",
    )
    set_clock("2026-06-01T00:00:00Z")
    validate_success(api.open_registration(ctx["event"]["id"], STAFF))

    resp = api.accept_membership(
        invited["id"], make_committee_volunteer_headers(volunteer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_COMMITTEE_LOCKED)

    membership = validate_success(api.get_membership(invited["id"], STAFF))
    assert membership["status"] == "INVITED"


def test_publication_review_loop_increments_review_round(api):
    """PRD §3.8: "returning the draft for edits moves `IN_REVIEW → DRAFT` and
    increments `review_round` by one each time".

    Design: Corner/state_machines/publication_review_loop_increments_review_round
    """
    event = create_event()
    pub = create_publication_for_event(
        event["id"], title="Memory Book", class_notes_body="Notes..."
    )
    assert pub["review_round"] == 0

    submitted = validate_success(api.submit_review(pub["id"], STAFF))
    assert submitted["status"] == "IN_REVIEW"

    returned = validate_success(api.return_for_edits(pub["id"], DIRECTOR))
    assert_publication(returned)
    assert returned["status"] == "DRAFT"
    assert returned["review_round"] == 1


def test_deceased_cascade_ends_membership_with_reason(api):
    """PRD §3.1: "every committee membership in `INVITED` or `ACTIVE` moves
    to `ENDED` with `ended_reason` of `ALUMNUS_DECEASED`".

    Design: Difficulty/transitive_cascade/alumnus_deceased_cascade_depth2_membership_to_posture
    """
    ctx = setup_committee_formed_event(
        event_overrides={"event_date": "2026-09-15T18:00:00Z",
                         "committee_quorum_required": 1},
        chair_overrides={"full_name": "Chair Seven", "primary_email": "chair7@x.com"},
    )
    chair_id = ctx["chair"]["id"]
    membership_id = ctx["membership"]["id"]

    record = validate_success(api.mark_deceased(chair_id, STAFF))
    assert record["status"] == "DECEASED"

    membership = validate_success(api.get_membership(membership_id, STAFF))
    assert_membership(membership)
    assert membership["status"] == "ENDED"
    assert membership["ended_reason"] == "ALUMNUS_DECEASED"


def test_deceased_cascade_decrements_committee_count_and_flips_posture(api):
    """PRD §3.1: "each such ending itself decrementing the event's
    `committee_count` and potentially flipping its posture to `GATED`".
    PRD §3.4: "When the event's `status` is anything other than
    `OPEN_FOR_REGISTRATION`, posture is `CLOSED` if the status is `HELD`,
    `RECONCILED`, or `CANCELLED`, and `GATED` otherwise."

    Design: Difficulty/transitive_cascade/alumnus_deceased_cascade_depth2_membership_to_posture
    """
    ctx = setup_committee_formed_event(
        event_overrides={"event_date": "2026-09-15T18:00:00Z",
                         "committee_quorum_required": 1},
        chair_overrides={"full_name": "Chair Seven", "primary_email": "chair7b@x.com"},
    )
    assert ctx["event"]["committee_count"] == 1

    validate_success(api.mark_deceased(ctx["chair"]["id"], STAFF))

    event = validate_success(api.get_event(ctx["event"]["id"], STAFF))
    assert event["committee_count"] == 0
    assert event["posture"] == "GATED", (
        "0 ACTIVE members is below quorum 1, so a COMMITTEE_FORMED event is GATED"
    )
