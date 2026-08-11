"""Rejections, reprints, transaction control numbers and the retroactive lapse sweep."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_same_instant,
    check_in,
    fee_assessments,
    finalize_card,
    new_applicant,
    new_appointment,
    only_fee_assessment,
    open_card,
    pass_positions,
    post_result,
    score_position,
    set_clock,
    setup_checked_in_appointment,
    setup_mobile_registry,
    setup_registry,
    setup_transmitted_submission,
    transmit_card,
    validate_error,
    validate_paginated,
    validate_success,
)

VA = TEST_USERS["vendor_admin_headers"]
TECH = TEST_USERS["technician_headers"]
SUP = TEST_USERS["supervisor_headers"]


# ---------------------------------------------------------------------------
# The retroactive calibration sweep
# ---------------------------------------------------------------------------

def _onsite_transmission_then_lapse_audit(audit=True):
    world = setup_mobile_registry(
        clock_start="2026-06-02T08:00:00Z",
        agency_overrides={"name": "Rural County"},
        event_overrides={"name": "County Yard Day", "min_billable_prints": 1},
    )
    setup_checked_in_appointment(
        world,
        scheduled_start="2026-06-02T10:00:00Z",
        checkin_clock="2026-06-02T09:55:00Z",
        site_key="event_site",
        applicant_overrides={"full_name": "Hana Ito"},
    )
    world["card"] = open_card(world["appointment"]["id"], world["device"]["id"])
    pass_positions(world["card"]["id"], 82)
    world["card"] = finalize_card(world["card"]["id"])
    world["submission"] = transmit_card(world["card"]["id"], world["card"]["version"])
    post_result(
        world["submission"]["id"], "STATE", "ACCEPTED", record_count=0, disqualifying_offense_count=0
    )
    world["billable_before"] = validate_success_site(world["event_site"]["id"])["billable_print_count"]
    if audit:
        set_clock("2026-06-10T00:00:00Z")
        world["device"] = validate_success_audit(world["device"]["id"], "2025-11-01T00:00:00Z")
    return world


def validate_success_site(site_id):
    from test_helpers import api_client

    return validate_success(api_client.get_site(site_id, VA), 200)


def validate_success_audit(device_id, corrected):
    from test_helpers import api_client

    return validate_success(api_client.run_calibration_audit(device_id, corrected, VA), 200)


def test_the_audit_quarantines_the_device_and_revokes_its_roster(api):
    """PRD 3.8: "1. The device's `last_calibrated_at` is rewritten to
    `corrected_last_calibrated_at`, its `calibration_expires_at` is recomputed as that instant plus
    180 days, and its `calibration_status` moves `CALIBRATED → QUARANTINED`."
    PRD 3.8: "2. Because the device is quarantined, every roster entry on it whose `status` is
    `SCHEDULED` or `ACTIVE` moves to `REVOKED_TAINTED`."

    Design: Difficulty/transitive_cascade/calibration_lapse_audit_cascades_to_vendor_borne_credit
    """
    world = _onsite_transmission_then_lapse_audit()

    assert world["device"]["calibration_status"] == "QUARANTINED"
    assert_same_instant(
        world["device"]["calibration_expires_at"], "2026-04-30T00:00:00Z", "calibration_expires_at"
    )

    assignment = validate_success(api.get_device_assignment(world["assignment"]["id"], SUP), 200)
    assert assignment["status"] == "REVOKED_TAINTED"


def test_the_sweep_supersedes_the_card_and_its_response(api):
    """PRD 3.8: "3. Because those roster entries are revoked, every fingerprint card on this device
    whose `first_capture_at` is **strictly after** the newly recomputed `calibration_expires_at`, and
    whose `status` is `OPEN`, `CAPTURING`, `READY_FOR_SUBMISSION`, `SUBMITTED`, `CLOSED` or
    `REJECTED_CLOSED`, moves to `SUPERSEDED` with a `taint_reason` of `CALIBRATION_LAPSE`."
    PRD 3.8: "4. Because those cards are void, every criminal-history response belonging to their
    submissions moves to `SUPERSEDED`, from `RECEIVED` or from `ROUTED` alike, and can no longer
    support any fitness determination."

    Design: Difficulty/transitive_cascade/calibration_lapse_audit_cascades_to_vendor_borne_credit
    """
    world = _onsite_transmission_then_lapse_audit()

    card = validate_success(api.get_card(world["card"]["id"], TECH), 200)
    assert card["status"] == "SUPERSEDED"
    assert card["taint_reason"] == "CALIBRATION_LAPSE"

    rows, meta = validate_paginated(api.list_submission_responses(world["submission"]["id"], VA))
    assert meta["total_count"] == 1
    assert rows[0]["routing_status"] == "SUPERSEDED"


def test_the_sweep_credits_the_transmission_fee_in_full(api):
    """PRD 3.8: "5. Because the prints must be redone at vendor cost, every `SUBMISSION`-kind or
    `REPRINT`-kind fee assessment of those cards' submissions whose `status` is `ASSESSED` or
    `INVOICED` moves to `CREDITED` with `credited_cents` set equal to its `total_cents`, so the
    applicant or agency owes exactly nothing."
    PRD 3.9: "`trip_surcharge_cents` is 500 cents when the capture site's `site_kind` is
    `MOBILE_EVENT` and the row is a `SUBMISSION` or `REPRINT`, and 0 otherwise."

    Design: Difficulty/transitive_cascade/calibration_lapse_audit_cascades_to_vendor_borne_credit
    """
    world = _onsite_transmission_then_lapse_audit()

    assessment = only_fee_assessment(submission_id=world["submission"]["id"])

    assert assessment["status"] == "CREDITED"
    assert assessment["total_cents"] == 6368
    assert assessment["credited_cents"] == 6368
    assert assessment["trip_surcharge_cents"] == 500


def _two_cards_five_minutes_apart():
    world = setup_registry(clock_start="2026-06-01T09:00:00Z")
    first_applicant = new_applicant(full_name="Lena Ott", id_document_expires_on="2030-02-02")
    second_applicant = new_applicant(full_name="Milo Vance", id_document_expires_on="2030-03-03")
    appt_a = new_appointment(
        first_applicant["id"], world["site"]["id"], world["service_type"]["id"], "2026-06-02T10:00:00Z"
    )
    appt_b = new_appointment(
        second_applicant["id"], world["site"]["id"], world["service_type"]["id"], "2026-06-02T10:05:00Z"
    )
    set_clock("2026-06-02T09:55:00Z")
    check_in(appt_a["id"])
    check_in(appt_b["id"])
    card_a = open_card(appt_a["id"], world["device"]["id"])
    card_b = open_card(appt_b["id"], world["device"]["id"])

    set_clock("2026-06-02T10:00:00Z")
    score_position(card_a["id"], "R_THUMB", 80)
    set_clock("2026-06-02T10:05:00Z")
    score_position(card_b["id"], "R_THUMB", 80)

    set_clock("2026-06-10T00:00:00Z")
    world["card_a"] = card_a
    world["card_b"] = card_b
    world["device"] = validate_success_audit(world["device"]["id"], "2025-12-04T10:00:00Z")
    return world


def test_a_capture_exactly_at_the_corrected_expiry_survives(api):
    """PRD 3.8: "Two exclusions are exact and load-bearing: a card whose `first_capture_at` is null —
    the exception-only card of §3.4, which was never scored — is never swept, and a card whose
    `first_capture_at` equals the recomputed expiry exactly is **not** tainted, because the
    comparison is strictly after."

    Design: Difficulty/boundary_precision_check/taint_sweep_excludes_capture_exactly_at_corrected_expiry
    """
    world = _two_cards_five_minutes_apart()

    assert_same_instant(
        world["device"]["calibration_expires_at"], "2026-06-02T10:00:00Z", "calibration_expires_at"
    )

    survivor = validate_success(api.get_card(world["card_a"]["id"], TECH), 200)
    assert_same_instant(survivor["first_capture_at"], "2026-06-02T10:00:00Z", "first_capture_at")
    assert survivor["status"] == "CAPTURING"
    assert survivor["taint_reason"] is None


def test_a_capture_five_minutes_later_is_swept(api):
    """PRD 3.8: "3. Because those roster entries are revoked, every fingerprint card on this device
    whose `first_capture_at` is **strictly after** the newly recomputed `calibration_expires_at`, and
    whose `status` is `OPEN`, `CAPTURING`, `READY_FOR_SUBMISSION`, `SUBMITTED`, `CLOSED` or
    `REJECTED_CLOSED`, moves to `SUPERSEDED` with a `taint_reason` of `CALIBRATION_LAPSE`."
    PRD 3.8: "Finally the device's `tainted_card_count` is set to the number of cards hop 3 moved."

    Design: Difficulty/boundary_precision_check/taint_sweep_excludes_capture_exactly_at_corrected_expiry
    """
    world = _two_cards_five_minutes_apart()

    swept = validate_success(api.get_card(world["card_b"]["id"], TECH), 200)
    assert swept["status"] == "SUPERSEDED"
    assert swept["taint_reason"] == "CALIBRATION_LAPSE"

    device = validate_success(api.get_device(world["device"]["id"], VA), 200)
    assert device["tainted_card_count"] == 1
    assert device["calibration_status"] == "QUARANTINED"


def test_the_audit_moves_the_print_from_billable_to_tainted(api):
    """PRD 2.11: "**Billable print conservation.** For each capture site, the site's
    `billable_print_count` plus the sum of `tainted_print_count` over every device assignment at that
    site equals the number of fingerprint cards at that site whose `status` is `SUBMITTED`, `CLOSED`
    or `REJECTED_CLOSED`, together with those whose `status` is `SUPERSEDED` with a `taint_reason` of
    `CALIBRATION_LAPSE`."
    PRD 3.8: "6. Because the billable set has shrunk, each affected capture site's
    `billable_print_count` is recomputed and each revoked roster entry's `tainted_print_count` is set
    to the number of cards swept on that device at that site."

    Design: Difficulty/compensating_invariant/lapse_audit_moves_prints_from_billable_to_tainted_without_losing_any
    """
    world = _onsite_transmission_then_lapse_audit()

    assert world["billable_before"] == 1

    site = validate_success(api.get_site(world["event_site"]["id"], VA), 200)
    assignment = validate_success(api.get_device_assignment(world["assignment"]["id"], SUP), 200)

    assert site["billable_print_count"] == 0
    assert assignment["tainted_print_count"] == 1
    assert site["billable_print_count"] + assignment["tainted_print_count"] == 1


def test_an_audit_before_reconciliation_manufactures_a_shortfall(api):
    """PRD 3.8: "First, because a superseded card no longer counts toward a site's billable prints, a
    lapse audit run after a mobile event has been reconciled cannot revise that event's charge, but
    an audit run *before* reconciliation can push a comfortably-over-minimum event into a shortfall."
    PRD 3.2: "An event with a `min_billable_prints` of 25 that produced 18 billable cards is charged
    seven times 2200, that is 15400 cents."

    Design: Difficulty/compensating_invariant/lapse_audit_moves_prints_from_billable_to_tainted_without_losing_any
    """
    world = _onsite_transmission_then_lapse_audit()

    reconciled = validate_success(api.reconcile_event(world["event_site"]["id"], VA), 200)

    assert reconciled["shortfall_charge_cents"] == 2200
    assert reconciled["reconciliation_status"] == "RECONCILED"

    shortfall = only_fee_assessment(
        agency_id=world["agency"]["id"], assessment_kind="ONSITE_SHORTFALL"
    )
    assert shortfall["total_cents"] == 2200


# ---------------------------------------------------------------------------
# Reprints
# ---------------------------------------------------------------------------

def _technically_rejected_submission(retention_requested=False):
    world = setup_transmitted_submission(
        clock_start="2026-06-01T09:00:00Z",
        score=80,
        transmit_clock="2026-06-01T10:05:00Z",
        retention_requested=retention_requested,
    )
    set_clock("2026-07-11T10:05:00Z")
    post_result(world["submission"]["id"], "STATE", "REJECTED_TECHNICAL", rejection_reason="smudged")
    world["submission"] = post_result(
        world["submission"]["id"], "FBI", "REJECTED_TECHNICAL", rejection_reason="smudged"
    )
    return world


def test_the_free_window_runs_thirty_days_from_the_rejection(api):
    """PRD 3.8: "A reprint is free when three things hold together: at least one destination returned
    `REJECTED_TECHNICAL`; the logical clock is at or before the anchor instant plus 30 days, the
    boundary inclusive so that a reprint exactly 30 days after the rejection is still free; and the
    submission's `free_reprint_count` is below 2."
    PRD 3.8: "The anchor is the result timestamp of the earliest destination that returned a
    technical rejection, and when both destinations returned one it is `state_resulted_at`, because
    the state axis is evaluated first."

    Design: Corner/calculations/reprint_entitlement_and_tcn_windows_disagree_across_three_authorizations
    """
    world = _technically_rejected_submission()
    assert world["submission"]["composite_disposition"] == "REJECTED"
    submission_id = world["submission"]["id"]
    device_id = world["device"]["id"]

    set_clock("2026-07-21T10:05:00Z")
    first = validate_success(api.authorize_reprint(submission_id, device_id, SUP), 201)
    assert first["free_reprint_granted"] is True

    set_clock("2026-08-15T10:05:00Z")
    second = validate_success(api.authorize_reprint(submission_id, device_id, SUP), 201)
    assert second["free_reprint_granted"] is False

    set_clock("2026-09-10T10:05:00Z")
    third = validate_success(api.authorize_reprint(submission_id, device_id, SUP), 201)
    assert third["free_reprint_granted"] is False


def test_a_fourth_reprint_authorization_exhausts_the_budget(api):
    """PRD 3.8: "and the submission's `reprint_count` must be below 3, failing which the answer is
    `ERR_REPRINT_LIMIT_REACHED`."
    PRD 3.8: "It moves the original card `SUBMITTED → REJECTED_CLOSED` when that card is still
    `SUBMITTED` — on the second and third reprint of the same submission that leg is a no-op, because
    the card is already `REJECTED_CLOSED` — and in every case re-points the original card's
    `superseded_by_card_id` at the **newest** replacement."

    Design: Corner/calculations/reprint_entitlement_and_tcn_windows_disagree_across_three_authorizations
    """
    world = _technically_rejected_submission()
    submission_id = world["submission"]["id"]
    device_id = world["device"]["id"]

    set_clock("2026-07-21T10:05:00Z")
    first = validate_success(api.authorize_reprint(submission_id, device_id, SUP), 201)
    set_clock("2026-08-15T10:05:00Z")
    validate_success(api.authorize_reprint(submission_id, device_id, SUP), 201)
    set_clock("2026-09-10T10:05:00Z")
    third = validate_success(api.authorize_reprint(submission_id, device_id, SUP), 201)

    fourth = api.authorize_reprint(submission_id, device_id, SUP)
    validate_error(fourth, ApiErrorId.ERR_REPRINT_LIMIT_REACHED.value)

    submission = validate_success(api.get_submission(submission_id, TECH), 200)
    assert submission["reprint_count"] == 3
    assert submission["free_reprint_count"] == 1

    original = validate_success(api.get_card(world["card"]["id"], TECH), 200)
    assert original["status"] == "REJECTED_CLOSED"
    assert original["superseded_by_card_id"] == third["id"]

    assert first["reprint_of_submission_id"] == submission_id
    assert first["status"] == "OPEN"

    _rows, meta = validate_paginated(
        api.list_cards(TECH, {"reprint_of_submission_id": submission_id})
    )
    assert meta["total_count"] == 3


def _finalized_free_replacement_card():
    world = _technically_rejected_submission(retention_requested=False)
    set_clock("2026-07-21T10:05:00Z")
    replacement = validate_success_reprint(world["submission"]["id"], world["device"]["id"])
    pass_positions(replacement["id"], 80)
    world["replacement"] = finalize_card(replacement["id"])
    return world


def validate_success_reprint(submission_id, device_id):
    from test_helpers import api_client

    return validate_success(api_client.authorize_reprint(submission_id, device_id, SUP), 201)


def test_a_replacement_card_may_not_change_the_retention_election(api):
    """PRD 3.7: "The election is irrevocable — there is no operation that changes it — and when a
    replacement card from a reprint is later transmitted, it must carry exactly the same
    `retention_requested` value as its original submission, or the transmission is refused with
    `ERR_RETENTION_IMMUTABLE`."

    Design: Corner/calculations/free_reprint_inside_tcn_window_extends_the_root_and_keeps_the_election
    """
    world = _finalized_free_replacement_card()

    response = api.create_submission(
        {
            "card_id": world["replacement"]["id"],
            "retention_requested": True,
            "expected_card_version": world["replacement"]["version"],
        },
        TECH,
    )

    validate_error(response, ApiErrorId.ERR_RETENTION_IMMUTABLE.value)


def test_a_preserved_root_takes_suffix_one_and_consumes_nothing(api):
    """PRD 3.5: "If both hold, the reprint **preserves** the root: it copies the original's
    `tcn_root`, takes that next suffix, and consumes no new allocation at all, leaving
    `tcn_consumed_count` untouched."
    PRD 3.5: "The submission also records `reprint_sequence`, which is 0 on a first print and
    otherwise equals that same next-suffix number — 1, then 2, then 3 for the third reprint — and
    `original_submission_id`, which is null on a first print and otherwise names the chain head."
    PRD 3.9: "Now reprint that submission at a fixed site under `APPLICANT_PAID`: with
    `free_reprint_granted` true the statutory components vanish and the total is 995 plus 72, that is
    1067; with `free_reprint_granted` false the total is 3289 plus 1350 plus 162 plus 995 plus 72
    plus 1800, that is 7668."

    Design: Corner/calculations/free_reprint_inside_tcn_window_extends_the_root_and_keeps_the_election
    """
    world = _finalized_free_replacement_card()
    original_tcn_root = world["submission"]["tcn_root"]

    reprint_submission = validate_success(
        api.create_submission(
            {
                "card_id": world["replacement"]["id"],
                "retention_requested": False,
                "expected_card_version": world["replacement"]["version"],
            },
            TECH,
        ),
        201,
    )

    assert reprint_submission["tcn_root"] == original_tcn_root
    assert reprint_submission["tcn_suffix"] == 1
    assert reprint_submission["tcn_full"] == f"{original_tcn_root}-1"
    assert reprint_submission["reprint_sequence"] == 1
    assert reprint_submission["original_submission_id"] == world["submission"]["id"]

    ori = validate_success(api.get_ori(world["ori"]["id"], VA), 200)
    assert ori["tcn_consumed_count"] == 2, "the preserved root consumed nothing new"

    reprint_rows = fee_assessments(
        appointment_id=world["appointment"]["id"], assessment_kind="REPRINT"
    )
    assert len(reprint_rows) == 1
    assessment = reprint_rows[0]
    assert assessment["state_fee_cents"] == 0
    assert assessment["federal_fee_cents"] == 0
    assert assessment["reprint_fee_cents"] == 0
    assert assessment["total_cents"] == 1067
