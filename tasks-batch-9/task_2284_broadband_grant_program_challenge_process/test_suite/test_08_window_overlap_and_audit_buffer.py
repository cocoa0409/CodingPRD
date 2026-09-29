"""Two interval regimes: half-open construction windows and closed audit windows."""

from test_helpers import (
    ApiErrorId,
    api_client,
    create_application,
    create_compliance_audit_payload,
    create_location_claim_payload,
    claim_location,
    make_subgrantee_headers,
    read_application,
    schedule_compliance_audit,
    setup_challenge_open_program,
    setup_construction_authorized_award,
    setup_disbursed_milestone,
    setup_qualified_subgrantee,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, AUDITOR_OTHER


def _three_drafts_over_one_location():
    """One UNSERVED location already claimed by a draft whose construction window
    runs 2026-10-01 to 2027-10-01, plus two further drafts: one starting inside
    that window and one starting exactly at its end."""
    ctx = setup_challenge_open_program(("L3",))
    contested = ctx["location_ids"]["L3"]
    subgrantee = setup_qualified_subgrantee(ctx["program_id"])
    owner = make_subgrantee_headers(subgrantee["id"])

    holder = create_application(ctx["program_id"], subgrantee["id"])
    overlapping = create_application(
        ctx["program_id"],
        subgrantee["id"],
        proposed_construction_start="2027-04-01T00:00:00Z",
        proposed_construction_end="2028-04-01T00:00:00Z",
    )
    touching = create_application(
        ctx["program_id"],
        subgrantee["id"],
        proposed_construction_start="2027-10-01T00:00:00Z",
        proposed_construction_end="2028-10-01T00:00:00Z",
    )

    held_claim = claim_location(holder["id"], contested, subgrantee["id"])
    assert held_claim["claim_state"] == "CLAIMED_ELIGIBLE"

    ctx.update(
        {
            "contested": contested,
            "subgrantee_id": subgrantee["id"],
            "owner": owner,
            "holder": holder,
            "overlapping": overlapping,
            "touching": touching,
            "held_claim": held_claim,
        }
    )
    return ctx


def test_a_claim_whose_construction_window_overlaps_a_live_claim_is_refused():
    """The second application's window opens inside the first's, which is a
    genuine overlap on the same location, so the claim is refused and the
    refusing application keeps no claim at all.

    PRD 3.5: "Because two applications cannot build the same location at the same
    time, a new claim's construction window — taken from its application as
    `proposed_construction_start` through `proposed_construction_end`, half-open
    — must not overlap the window of any other non-`RELEASED` claim on the same
    location; touching endpoints, where one window's end instant equals the
    other's start instant, are allowed, and a genuine overlap is refused with
    `ERR_LOCATION_CLAIM_WINDOW_CONFLICT`."
    PRD 2.12: "28. **Priority 69 — claim window overlap** →
    `ERR_LOCATION_CLAIM_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/location_claim_half_open_construction_window_overlap
    """
    ctx = _three_drafts_over_one_location()

    refused = api_client.create_location_claim(
        create_location_claim_payload(ctx["overlapping"]["id"], ctx["contested"]),
        ctx["owner"],
    )
    validate_error(refused, ApiErrorId.ERR_LOCATION_CLAIM_WINDOW_CONFLICT)

    rows, meta = validate_paginated(
        api_client.list_application_location_claims(ctx["overlapping"]["id"], ADMIN)
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert read_application(ctx["overlapping"]["id"])["claim_count"] == 0

    on_location, location_meta = validate_paginated(
        api_client.list_location_claims_of_location(ctx["contested"], ADMIN)
    )
    assert location_meta["total_count"] == 1
    assert on_location[0]["id"] == ctx["held_claim"]["id"]


def test_a_claim_whose_window_starts_at_the_held_window_end_is_accepted():
    """The windows are half-open, so a second application beginning at the exact
    instant the first ends merely touches it and the claim is admitted alongside
    the first.

    PRD 3.5: "Finally `proposed_construction_start` and
    `proposed_construction_end` bound the proposed construction window, half-open
    with the start inside and the end outside, and the start must be strictly
    before the end."
    PRD 3.5: "Because two applications cannot build the same location at the same
    time, a new claim's construction window — taken from its application as
    `proposed_construction_start` through `proposed_construction_end`, half-open
    — must not overlap the window of any other non-`RELEASED` claim on the same
    location; touching endpoints, where one window's end instant equals the
    other's start instant, are allowed, and a genuine overlap is refused with
    `ERR_LOCATION_CLAIM_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/location_claim_half_open_construction_window_overlap
    """
    ctx = _three_drafts_over_one_location()

    accepted = validate_success(
        api_client.create_location_claim(
            create_location_claim_payload(ctx["touching"]["id"], ctx["contested"]),
            ctx["owner"],
        ),
        201,
    )
    assert accepted["claim_state"] == "CLAIMED_ELIGIBLE"
    assert read_application(ctx["touching"]["id"])["claim_count"] == 1
    assert read_application(ctx["holder"]["id"])["claim_count"] == 1

    on_location, location_meta = validate_paginated(
        api_client.list_location_claims_of_location(ctx["contested"], ADMIN)
    )
    assert location_meta["total_count"] == 2
    assert {c["id"] for c in on_location} == {ctx["held_claim"]["id"], accepted["id"]}
    assert {c["claim_state"] for c in on_location} == {"CLAIMED_ELIGIBLE"}


def _award_under_audit():
    """An IN_CONSTRUCTION award carrying one SCHEDULED audit over the closed
    observation window 2027-01-05 through 2027-01-10."""
    ctx = setup_construction_authorized_award()
    setup_disbursed_milestone(ctx, milestone_location_keys=("L2",), sequence_no=1)
    ctx["audit"] = schedule_compliance_audit(
        ctx["award_id"],
        "SERVICE_AVAILABILITY",
        "2027-01-05T00:00:00Z",
        "2027-01-10T00:00:00Z",
    )
    return ctx


def test_a_second_audit_window_inside_the_buffer_is_refused():
    """A window that does not overlap at all but sits twenty-three hours after the
    existing window still collides, because the scheduling rule pads each live
    window; a comfortably separated window schedules normally.

    PRD 3.9: "The start must be strictly before the end, and the new window must
    neither overlap nor sit within twenty-four hours of the window of any existing
    non-terminal audit on the same award; a violation is refused with
    `ERR_AUDIT_WINDOW_BUFFER_CONFLICT`."
    PRD 2.12: "27. **Priority 68 — audit window buffer** →
    `ERR_AUDIT_WINDOW_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/compliance_audit_closed_window_24h_buffer
    """
    ctx = _award_under_audit()
    assert ctx["audit"]["audit_state"] == "SCHEDULED"

    inside_buffer = api_client.create_compliance_audit(
        ctx["award_id"],
        create_compliance_audit_payload(
            "SPEED_TEST", "2027-01-10T23:00:00Z", "2027-01-15T00:00:00Z"
        ),
        AUDITOR_OTHER,
    )
    validate_error(inside_buffer, ApiErrorId.ERR_AUDIT_WINDOW_BUFFER_CONFLICT)

    rows, meta = validate_paginated(
        api_client.list_compliance_audits(ctx["award_id"], ADMIN)
    )
    assert meta["total_count"] == 1
    assert rows[0]["audit_state"] == "SCHEDULED"

    clear_of_buffer = validate_success(
        api_client.create_compliance_audit(
            ctx["award_id"],
            create_compliance_audit_payload(
                "SPEED_TEST", "2027-01-20T00:00:00Z", "2027-01-25T00:00:00Z"
            ),
            AUDITOR_OTHER,
        ),
        201,
    )
    assert clear_of_buffer["audit_state"] == "SCHEDULED"
    assert clear_of_buffer["window_start"].startswith("2027-01-20T00:00:00")

    _, after_meta = validate_paginated(
        api_client.list_compliance_audits(ctx["award_id"], ADMIN)
    )
    assert after_meta["total_count"] == 2


def test_the_closed_observation_window_collides_on_a_shared_endpoint():
    """Unlike a construction window, the observation window includes both of its
    endpoints, so a second audit beginning at the exact instant the first ends
    overlaps it, and a window nested inside the first collides too.

    PRD 3.9: "Unlike the program and construction windows, the observation window
    is a **closed** interval: both endpoints are inside it."
    PRD 3.9: "The start must be strictly before the end, and the new window must
    neither overlap nor sit within twenty-four hours of the window of any existing
    non-terminal audit on the same award; a violation is refused with
    `ERR_AUDIT_WINDOW_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/compliance_audit_closed_window_24h_buffer
    """
    ctx = _award_under_audit()

    shared_endpoint = api_client.create_compliance_audit(
        ctx["award_id"],
        create_compliance_audit_payload(
            "SPEED_TEST", "2027-01-10T00:00:00Z", "2027-01-14T00:00:00Z"
        ),
        AUDITOR_OTHER,
    )
    validate_error(shared_endpoint, ApiErrorId.ERR_AUDIT_WINDOW_BUFFER_CONFLICT)

    nested = api_client.create_compliance_audit(
        ctx["award_id"],
        create_compliance_audit_payload(
            "COMBINED", "2027-01-06T00:00:00Z", "2027-01-08T00:00:00Z"
        ),
        AUDITOR_OTHER,
    )
    validate_error(nested, ApiErrorId.ERR_AUDIT_WINDOW_BUFFER_CONFLICT)

    rows, meta = validate_paginated(
        api_client.list_compliance_audits(ctx["award_id"], ADMIN)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["audit"]["id"]
    assert rows[0]["audit_state"] == "SCHEDULED"
