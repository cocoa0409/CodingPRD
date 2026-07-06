"""Ceremony-script revision loop, venue conflict semantics (half-open, unbuffered),
and the rehearsal-confirm cross-entity gate on script approval (PRD Sections 2.9,
3.4, 3.5).
"""
from test_helpers import (
    fixtures as fx,
    validate_success, validate_error,
    ApiErrorId,
    create_rehearsal_payload,
    make_coordinator_headers, make_couple_headers, make_officiant_headers,
)

COORD = make_coordinator_headers()


def test_two_revision_loops_leave_script_submitted_with_count_two(api):
    """PRD §3.4: "The couple submits it for review, moving `DRAFT → SUBMITTED` or
    `CHANGES_REQUESTED → SUBMITTED`; resubmitting from `CHANGES_REQUESTED`
    increments `revision_count` by one, so the count records how many times the
    script has re-entered review after changes were requested."

    Design: Difficulty/non_linear_state_machine/ceremony_script_revision_loop
    """
    ref = fx.setup_reference(api)
    booking = fx.create_booking(api, ref.officiant, ref.couple, ref.package, ref.venue)
    script = fx.create_script(api, booking, ref.couple)
    fx.submit_script(api, script, ref.couple)                                   # SUBMITTED
    fx.decide_script(api, script, ref.officiant, "REQUEST_CHANGES", "Trim opening")  # CHANGES_REQUESTED
    fx.patch_script(api, script, ref.couple, opening_remarks="Welcome all")
    fx.submit_script(api, script, ref.couple)                                   # SUBMITTED (count 1)
    fx.decide_script(api, script, ref.officiant, "REQUEST_CHANGES", "Add a reading")  # CHANGES_REQUESTED
    resp = api.submit_ceremony_script(script["id"], make_couple_headers(ref.couple["id"]))  # SUBMITTED (count 2)
    data = validate_success(resp, 200)
    assert data["status"] == "SUBMITTED"
    assert data["revision_count"] == 2


def test_single_revision_loop_increments_count_to_one(api):
    """PRD §3.4: "resubmitting from `CHANGES_REQUESTED` increments `revision_count`
    by one, so the count records how many times the script has re-entered review
    after changes were requested."

    Design: Difficulty/non_linear_state_machine/ceremony_script_revision_loop
    """
    ref = fx.setup_reference(api)
    booking = fx.create_booking(api, ref.officiant, ref.couple, ref.package, ref.venue)
    script = fx.create_script(api, booking, ref.couple)
    fx.submit_script(api, script, ref.couple)                                   # SUBMITTED
    fx.decide_script(api, script, ref.officiant, "REQUEST_CHANGES")             # CHANGES_REQUESTED
    resp = api.submit_ceremony_script(script["id"], make_couple_headers(ref.couple["id"]))  # SUBMITTED (count 1)
    data = validate_success(resp, 200)
    assert data["status"] == "SUBMITTED"
    assert data["revision_count"] == 1


def test_back_to_back_rehearsals_do_not_collide(api):
    """PRD §2.9: "A conflict exists when the candidate rehearsal's start is strictly
    before an existing rehearsal's end and that existing rehearsal's start is
    strictly before the candidate's end. Because the intervals are half-open,
    back-to-back rehearsals where one ends exactly when the next begins do not
    collide."

    Design: Difficulty/resource_temporal_overlap/venue_unavailable_halfopen_adjacency_allowed
    """
    ref = fx.setup_reference(api)
    b1 = fx.create_booking(api, ref.officiant, ref.couple, ref.package, ref.venue,
                           ceremony_start="2026-09-01T15:00:00Z", ceremony_end="2026-09-01T16:00:00Z")
    b2 = fx.create_booking(api, ref.officiant, ref.couple, ref.package, ref.venue,
                           ceremony_start="2026-09-02T15:00:00Z", ceremony_end="2026-09-02T16:00:00Z")
    fx.create_rehearsal(api, b1, ref.couple, ref.venue,
                        rehearsal_start="2026-08-31T18:00:00Z", rehearsal_end="2026-08-31T19:00:00Z")
    resp = api.create_rehearsal(
        create_rehearsal_payload(b2["id"], ref.venue["id"],
                                 rehearsal_start="2026-08-31T19:00:00Z", rehearsal_end="2026-08-31T20:00:00Z"),
        make_couple_headers(ref.couple["id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


def test_overlapping_rehearsal_at_same_venue_rejected(api):
    """PRD §2.9: "A conflict exists when the candidate rehearsal's start is strictly
    before an existing rehearsal's end and that existing rehearsal's start is
    strictly before the candidate's end. ... A conflict is rejected with
    `ERR_VENUE_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/venue_unavailable_halfopen_adjacency_allowed
    """
    ref = fx.setup_reference(api)
    b1 = fx.create_booking(api, ref.officiant, ref.couple, ref.package, ref.venue,
                           ceremony_start="2026-09-01T15:00:00Z", ceremony_end="2026-09-01T16:00:00Z")
    b3 = fx.create_booking(api, ref.officiant, ref.couple, ref.package, ref.venue,
                           ceremony_start="2026-09-03T15:00:00Z", ceremony_end="2026-09-03T16:00:00Z")
    fx.create_rehearsal(api, b1, ref.couple, ref.venue,
                        rehearsal_start="2026-08-31T18:00:00Z", rehearsal_end="2026-08-31T19:00:00Z")
    resp = api.create_rehearsal(
        create_rehearsal_payload(b3["id"], ref.venue["id"],
                                 rehearsal_start="2026-08-31T18:30:00Z", rehearsal_end="2026-08-31T19:30:00Z"),
        make_couple_headers(ref.couple["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VENUE_UNAVAILABLE.value)


def test_rehearsal_confirm_with_unapproved_script_rejected(api):
    """PRD §3.5: "The assigned officiant confirms a scheduled rehearsal, moving
    `SCHEDULED → CONFIRMED`, but only once the booking's ceremony script is
    `APPROVED`; if the script is not yet approved, confirmation is rejected with
    `ERR_SCRIPT_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/rehearsal_confirm_requires_script_approved
    """
    ref = fx.setup_reference(api)
    booking = fx.create_booking(api, ref.officiant, ref.couple, ref.package, ref.venue)
    script = fx.create_script(api, booking, ref.couple)
    fx.submit_script(api, script, ref.couple)  # SUBMITTED, not APPROVED
    rehearsal = fx.create_rehearsal(api, booking, ref.couple, ref.venue,
                                    rehearsal_start="2026-08-31T18:00:00Z", rehearsal_end="2026-08-31T19:00:00Z")
    resp = api.transition_rehearsal(
        rehearsal["id"], {"to_state": "CONFIRMED"}, make_officiant_headers(ref.officiant["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SCRIPT_NOT_APPROVED.value)


def test_rehearsal_stays_scheduled_when_script_not_approved(api):
    """PRD §3.5: "if the script is not yet approved, confirmation is rejected with
    `ERR_SCRIPT_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/rehearsal_confirm_requires_script_approved
    """
    ref = fx.setup_reference(api)
    booking = fx.create_booking(api, ref.officiant, ref.couple, ref.package, ref.venue)
    script = fx.create_script(api, booking, ref.couple)
    fx.submit_script(api, script, ref.couple)
    rehearsal = fx.create_rehearsal(api, booking, ref.couple, ref.venue,
                                    rehearsal_start="2026-08-31T18:00:00Z", rehearsal_end="2026-08-31T19:00:00Z")
    api.transition_rehearsal(
        rehearsal["id"], {"to_state": "CONFIRMED"}, make_officiant_headers(ref.officiant["id"])
    )
    after = fx.get_success_data(api.get_rehearsal(rehearsal["id"], COORD))
    assert after["status"] == "SCHEDULED"
