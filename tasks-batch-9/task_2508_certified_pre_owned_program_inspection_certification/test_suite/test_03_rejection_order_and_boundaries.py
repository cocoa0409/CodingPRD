"""Which rejection wins when several apply, and what happens exactly at the edge.

A request that breaks three rules at once may only be told about one of them, so
the programme fixes a single ascending ladder and the first failing rung answers.
Three pairings are pinned here: the concurrency guard ahead of the title screen,
the age ceiling ahead of the technician's calendar, and the title screen ahead of
the documentation audit. The rest of the file walks the edges themselves — the
inclusive age ceiling to the day, the inclusive probation threshold to the second
decimal, and the audit run that draws from nothing at all.
"""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    active_certification,
    approve_certification,
    approve_claim,
    assert_instant_equals,
    audit_samples_of,
    complete_reconditioning,
    create_certification_payload,
    create_inspection_payload,
    create_vehicle,
    decertify,
    document,
    documents_without_reconditioning,
    draw_audit_run,
    file_claim,
    get_success_data,
    open_inspection_for,
    passed_inspection,
    read_certification,
    read_dealer,
    read_inspection,
    read_vehicle,
    reconditioning_item_for,
    record_history_event,
    record_results,
    result_row,
    retune_config,
    set_clock,
    set_privilege,
    submit_certification,
    submit_inspection,
    submitted_certification,
    validate_error,
    validate_success,
    vehicle_version,
)

# A worksheet date that is comfortably before the epoch clock, so that a
# `started_at` on it is never a future-dated worksheet.
WORKSHEET_DAY = "2026-07-31"

# Read against a `started_at` on WORKSHEET_DAY these in-service dates give day
# counts of 2189, 2190 and 2191 — one inside the ceiling, one exactly on it, and
# one past it.
IN_SERVICE_2189_DAYS = "2020-08-02"
IN_SERVICE_2190_DAYS = "2020-08-01"
IN_SERVICE_2191_DAYS = "2020-07-31"


def _open_attempt(api, program, vehicle_id, started_at, **overrides):
    """The raw open-inspection call, so a rejection can be inspected."""
    return api.create_inspection(
        create_inspection_payload(
            vehicle_id,
            program.technician_id,
            program.template_id,
            started_at=started_at,
            **overrides,
        ),
        program.dealer_headers,
    )


def _submission(api, program, walk, expected_vehicle_version, documents):
    """The raw submit-certification call with an explicit guard and document set."""
    return api.create_certification(
        create_certification_payload(
            walk.vehicle_id,
            walk.inspection_id,
            expected_vehicle_version,
            documents=documents,
        ),
        program.dealer_headers,
    )


def _passed_inspection_with_one_repair(api, program, vehicle=None):
    """Drive a car to `PASSED` through one repair, so the invoice becomes mandatory."""
    walk = open_inspection_for(api, program, vehicle=vehicle)
    record_results(
        api,
        walk.inspection_id,
        program.technician_headers,
        [
            result_row("P1", "PASS"),
            result_row("S1", "FAIL"),
            result_row("B1", "PASS", measured_value=8.0),
        ],
    )
    submit_inspection(api, walk.inspection_id, program.dealer_headers)
    complete_reconditioning(
        api,
        reconditioning_item_for(api, walk.inspection_id, "S1")["id"],
        100000,
        program.other_technician_headers,
    )
    record_results(
        api,
        walk.inspection_id,
        program.technician_headers,
        [
            result_row("P1", "PASS"),
            result_row("S1", "PASS"),
            result_row("B1", "PASS", measured_value=8.0),
        ],
    )
    walk.inspection = submit_inspection(api, walk.inspection_id, program.dealer_headers)
    assert walk.inspection["status"] == "PASSED"
    return walk


def _certifications_of(api, vehicle_id):
    return validate_success(
        api.list_certifications(ADMIN, params={"vehicle_id": vehicle_id})
    )


# ───────── the concurrency guard answers before the title screen does ────────

def test_the_branding_that_made_the_view_stale_is_reported_as_staleness_first(
    api, program
):
    """The 412 guard fires on the branded car before the 422 title screen does.

    PRD §2.10: "9. The optimistic concurrency guard of §2.8 — otherwise the
    stale-version identifier for the parent entity."
    PRD §2.10: "10. Title-brand eligibility — otherwise
    `ERR_BRANDED_TITLE_INELIGIBLE`."
    PRD §2.8: "If that value does not equal the vehicle's current `version`, the
    submission is rejected with `ERR_STALE_VEHICLE_VERSION` (HTTP 412)."
    PRD §3.6: "The eligibility screens of §3.3 are re-run here against the
    vehicle's *current* facts, so a car whose title was branded between
    inspection and submission is rejected with `ERR_BRANDED_TITLE_INELIGIBLE`"

    Design: Difficulty/priority_pair_validation_conflict/stale_vehicle_version_412_precedes_branded_title_422
    """
    walk = passed_inspection(api, program)
    stale = vehicle_version(api, walk.vehicle_id)
    record_history_event(api, walk.vehicle_id, "TITLE_BRANDED", title_brand="SALVAGE")
    fresh = vehicle_version(api, walk.vehicle_id)
    assert fresh == stale + 1

    guarded = _submission(
        api, program, walk, stale, documents_without_reconditioning("1")
    )
    validate_error(guarded, ApiErrorId.ERR_STALE_VEHICLE_VERSION)

    branded = _submission(
        api, program, walk, fresh, documents_without_reconditioning("1")
    )
    validate_error(branded, ApiErrorId.ERR_BRANDED_TITLE_INELIGIBLE)

    assert _certifications_of(api, walk.vehicle_id) == []
    assert read_dealer(api, program.dealer_id)["lifetime_submitted_count"] == 0
    vehicle = read_vehicle(api, walk.vehicle_id)
    assert vehicle["title_brand"] == "SALVAGE"
    assert vehicle["cpo_state"] == "CERTIFICATION_PENDING"
    assert vehicle["active_certification_count"] == 0
    assert vehicle["version"] == fresh, "a refused submission advances nothing"


def test_a_successful_submission_makes_the_next_blind_one_stale(api, program):
    """The guard bites on the supersede path, and only then does the title screen.

    PRD §2.8: "both guarded operations *advance* the parent's `version` as part of
    their own success — a certification submission increments the vehicle's
    `version`, and a syndication increments the certification's `version` — so a
    client that wants to write twice in a row must re-read the parent between the
    two writes."
    PRD §3.6: "A vehicle holding a single still-`SUBMITTED` certification is a
    different matter: the new submission legitimately **supersedes** it, provided
    the concurrency guard passes."
    PRD §2.10: "Requests are validated in a strict, single ascending ladder, and
    the **first** failing rung determines the response."

    Design: Difficulty/priority_pair_validation_conflict/stale_vehicle_version_412_precedes_branded_title_422
    """
    walk = passed_inspection(api, program)
    observed = vehicle_version(api, walk.vehicle_id)

    first = get_success_data(
        _submission(api, program, walk, observed, documents_without_reconditioning("1")),
        expected_status=201,
    )
    assert first["status"] == "SUBMITTED"
    assert vehicle_version(api, walk.vehicle_id) == observed + 1

    blind = _submission(
        api, program, walk, observed, documents_without_reconditioning("2")
    )
    validate_error(blind, ApiErrorId.ERR_STALE_VEHICLE_VERSION)
    assert read_certification(api, first["id"])["status"] == "SUBMITTED"

    record_history_event(api, walk.vehicle_id, "TITLE_BRANDED", title_brand="FLOOD")
    current = vehicle_version(api, walk.vehicle_id)
    branded = _submission(
        api, program, walk, current, documents_without_reconditioning("3")
    )
    validate_error(branded, ApiErrorId.ERR_BRANDED_TITLE_INELIGIBLE)

    assert read_dealer(api, program.dealer_id)["lifetime_submitted_count"] == 1
    assert len(_certifications_of(api, walk.vehicle_id)) == 1


# ──────── the age ceiling answers before the technician's calendar does ───────

def test_an_overage_car_reports_its_age_even_inside_an_occupied_slot(api, program):
    """The rung-12 age ceiling outranks the rung-28 calendar conflict.

    PRD §2.10: "12. Vehicle age ceiling — otherwise `ERR_VEHICLE_AGE_EXCEEDED`."
    PRD §2.10: "28. Technician slot availability — otherwise
    `ERR_TECHNICIAN_SLOT_CONFLICT`."
    PRD §3.3: "the whole number of days between its `in_service_date` and the
    calendar date of `started_at` must be at most the programme's age ceiling,
    which defaults to six years counted as 2190 days, and the bound is inclusive
    — a car exactly at 2190 days is still eligible, one at 2191 days is rejected
    with `ERR_VEHICLE_AGE_EXCEEDED`"

    Design: Difficulty/priority_pair_validation_conflict/vehicle_age_422_precedes_technician_slot_409
    """
    occupied = open_inspection_for(
        api, program, started_at=f"{WORKSHEET_DAY}T09:00:00Z"
    )
    assert_instant_equals(
        occupied.inspection["slot_end_at"], f"{WORKSHEET_DAY}T11:00:00Z", "slot_end_at"
    )

    overage = create_vehicle(api, in_service_date=IN_SERVICE_2191_DAYS)
    aged = _open_attempt(api, program, overage["id"], f"{WORKSHEET_DAY}T10:00:00Z")
    validate_error(aged, ApiErrorId.ERR_VEHICLE_AGE_EXCEEDED)

    eligible = create_vehicle(api)
    clashing = _open_attempt(api, program, eligible["id"], f"{WORKSHEET_DAY}T10:00:00Z")
    validate_error(clashing, ApiErrorId.ERR_TECHNICIAN_SLOT_CONFLICT)

    assert read_vehicle(api, overage["id"])["cpo_state"] == "NOT_CERTIFIED"
    assert read_vehicle(api, eligible["id"])["cpo_state"] == "NOT_CERTIFIED"
    booked = validate_success(
        api.list_inspections(ADMIN, params={"technician_id": program.technician_id})
    )
    assert len(booked) == 1
    assert booked[0]["id"] == occupied.inspection_id


def test_age_outranks_the_calendar_even_when_the_slots_merely_touch(api, program):
    """One day over the ceiling beats a conflict that is only one instant wide.

    PRD §3.3: "an inspection begun at 09:00 buffers to the closed interval from
    08:30 to 11:30; a second inspection by the same technician begun at 12:00
    buffers to the closed interval from 11:30 to 14:30, touches the first at
    11:30, and is rejected with `ERR_TECHNICIAN_SLOT_CONFLICT`, while one begun at
    12:01 buffers from 11:31 and is accepted."
    PRD §2.12: "A technician's inspection slot, by contrast, is **closed on both
    ends** after a buffer is applied at each end, and **adjacency is forbidden**:
    two buffered slots that touch at a single instant do conflict."
    PRD §2.10: "Requests are validated in a strict, single ascending ladder, and
    the **first** failing rung determines the response."

    Design: Difficulty/priority_pair_validation_conflict/vehicle_age_422_precedes_technician_slot_409
    """
    open_inspection_for(api, program, started_at=f"{WORKSHEET_DAY}T09:00:00Z")
    overage = create_vehicle(api, in_service_date=IN_SERVICE_2191_DAYS)
    eligible = create_vehicle(api)

    touching_and_overage = _open_attempt(
        api, program, overage["id"], f"{WORKSHEET_DAY}T12:00:00Z"
    )
    validate_error(touching_and_overage, ApiErrorId.ERR_VEHICLE_AGE_EXCEEDED)

    touching_only = _open_attempt(
        api, program, eligible["id"], f"{WORKSHEET_DAY}T12:00:00Z"
    )
    validate_error(touching_only, ApiErrorId.ERR_TECHNICIAN_SLOT_CONFLICT)

    # One minute later the calendar is clear, and the age screen still answers.
    clear_and_overage = _open_attempt(
        api, program, overage["id"], f"{WORKSHEET_DAY}T12:01:00Z"
    )
    validate_error(clear_and_overage, ApiErrorId.ERR_VEHICLE_AGE_EXCEEDED)

    accepted = get_success_data(
        _open_attempt(api, program, eligible["id"], f"{WORKSHEET_DAY}T12:01:00Z"),
        expected_status=201,
    )
    assert accepted["status"] == "DRAFT"
    assert_instant_equals(
        accepted["slot_end_at"], f"{WORKSHEET_DAY}T14:01:00Z", "slot_end_at"
    )
    booked = validate_success(
        api.list_inspections(ADMIN, params={"technician_id": program.technician_id})
    )
    assert len(booked) == 2


# ────── the title screen answers before the documentation audit does ─────

def test_a_branded_car_reports_its_title_before_a_missing_disclosure(api, program):
    """Rung 10 answers a submission that is also short a required document.

    PRD §2.10: "22. Required documentation present — otherwise
    `ERR_DOCUMENTATION_INCOMPLETE`."
    PRD §3.6: "Three of them are unconditionally required."
    PRD §3.6: "Omitting any required document type — including the invoice on an
    inspection that generated repairs — is rejected with
    `ERR_DOCUMENTATION_INCOMPLETE`."
    PRD §3.3: "a branded car is permanently outside the programme, and the
    rejection is `ERR_BRANDED_TITLE_INELIGIBLE`"

    Design: Difficulty/priority_pair_validation_conflict/branded_title_422_precedes_documentation_incomplete_422
    """
    short_body = [
        document("TITLE_HISTORY_REPORT", "THR-9"),
        document("INSPECTION_WORKSHEET", "IW-9"),
    ]

    branded_walk = passed_inspection(api, program)
    record_history_event(
        api, branded_walk.vehicle_id, "TITLE_BRANDED", title_brand="LEMON"
    )
    branded = _submission(
        api,
        program,
        branded_walk,
        vehicle_version(api, branded_walk.vehicle_id),
        short_body,
    )
    validate_error(branded, ApiErrorId.ERR_BRANDED_TITLE_INELIGIBLE)

    clean_walk = passed_inspection(api, program)
    incomplete = _submission(
        api,
        program,
        clean_walk,
        vehicle_version(api, clean_walk.vehicle_id),
        short_body,
    )
    validate_error(incomplete, ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE)

    assert read_dealer(api, program.dealer_id)["lifetime_submitted_count"] == 0
    assert _certifications_of(api, branded_walk.vehicle_id) == []
    assert _certifications_of(api, clean_walk.vehicle_id) == []


def test_a_branded_car_reports_its_title_before_a_missing_repair_invoice(api, program):
    """The same order holds against the conditionally required invoice.

    PRD §3.6: "The reconditioning invoice is **conditionally** required, and the
    condition cuts both ways: it is mandatory exactly when the backing inspection
    produced at least one reconditioning item, and it is *forbidden* when the
    inspection produced none."
    PRD §2.10: "10. Title-brand eligibility — otherwise
    `ERR_BRANDED_TITLE_INELIGIBLE`."
    PRD §2.10: "This matters because many requests violate several rules at once,
    and only one error identifier can be returned."

    Design: Difficulty/priority_pair_validation_conflict/branded_title_422_precedes_documentation_incomplete_422
    """
    branded_walk = _passed_inspection_with_one_repair(api, program)
    record_history_event(
        api, branded_walk.vehicle_id, "TITLE_BRANDED", title_brand="REBUILT"
    )
    branded = _submission(
        api,
        program,
        branded_walk,
        vehicle_version(api, branded_walk.vehicle_id),
        documents_without_reconditioning("A"),
    )
    validate_error(branded, ApiErrorId.ERR_BRANDED_TITLE_INELIGIBLE)

    clean_walk = _passed_inspection_with_one_repair(api, program)
    missing_invoice = _submission(
        api,
        program,
        clean_walk,
        vehicle_version(api, clean_walk.vehicle_id),
        documents_without_reconditioning("B"),
    )
    validate_error(missing_invoice, ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE)

    complete_body = documents_without_reconditioning("B") + [
        document("RECONDITIONING_INVOICE", "RI-B")
    ]
    accepted = get_success_data(
        _submission(
            api,
            program,
            clean_walk,
            vehicle_version(api, clean_walk.vehicle_id),
            complete_body,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "SUBMITTED"
    assert accepted["document_count"] == 4
    assert read_dealer(api, program.dealer_id)["lifetime_submitted_count"] == 1


# ───────────────────── the inclusive age ceiling, to the day ─────────────────

def test_the_age_ceiling_admits_exactly_two_thousand_one_hundred_and_ninety_days(
    api, program
):
    """2189 and 2190 days are eligible; 2191 is not.

    PRD §3.3: "a car exactly at 2190 days is still eligible, one at 2191 days is
    rejected with `ERR_VEHICLE_AGE_EXCEEDED`"
    PRD §3.3: "Two derived snapshots are frozen at this moment and never
    recomputed: `slot_end_at`, described above, and
    `vehicle_age_days_at_inspection`, the whole number of days between the
    vehicle's `in_service_date` and the calendar date of `started_at`."
    PRD §2.6: "Eligibility: `max_age_days` is 2190 and must be at least 1"

    Design: Difficulty/boundary_precision_check/vehicle_age_days_at_max_age_boundary
    """
    inside = get_success_data(
        _open_attempt(
            api,
            program,
            create_vehicle(api, in_service_date=IN_SERVICE_2189_DAYS)["id"],
            f"{WORKSHEET_DAY}T05:00:00Z",
        ),
        expected_status=201,
    )
    assert inside["vehicle_age_days_at_inspection"] == 2189

    at_the_bound = get_success_data(
        _open_attempt(
            api,
            program,
            create_vehicle(api, in_service_date=IN_SERVICE_2190_DAYS)["id"],
            f"{WORKSHEET_DAY}T09:00:00Z",
        ),
        expected_status=201,
    )
    assert at_the_bound["vehicle_age_days_at_inspection"] == 2190

    over_the_bound = create_vehicle(api, in_service_date=IN_SERVICE_2191_DAYS)
    refused = _open_attempt(
        api, program, over_the_bound["id"], f"{WORKSHEET_DAY}T13:00:00Z"
    )
    validate_error(refused, ApiErrorId.ERR_VEHICLE_AGE_EXCEEDED)
    assert read_vehicle(api, over_the_bound["id"])["cpo_state"] == "NOT_CERTIFIED"

    booked = validate_success(
        api.list_inspections(ADMIN, params={"technician_id": program.technician_id})
    )
    assert len(booked) == 2


def test_the_frozen_age_snapshot_and_the_priced_age_are_measured_differently(
    api, program
):
    """The snapshot never moves, while the fee re-reads the age at activation.

    PRD §2.5: "Moving the clock is a purely forward-looking act. It never
    rewrites a stored timestamp and never recomputes a window that has already
    been persisted"
    PRD §3.7: "The vehicle's age in whole days is the number of days between its
    `in_service_date` and the calendar date of `activated_at`; whole age years
    are that day count divided by 365 and rounded down."
    PRD §3.7: "An absolute cap date is the vehicle's `in_service_date` advanced
    by the total coverage cap in calendar months, 84 months (seven years) by
    default. `warranty_end_date` is the earlier of those two dates."

    Design: Difficulty/boundary_precision_check/vehicle_age_days_at_max_age_boundary
    """
    vehicle = create_vehicle(api, in_service_date=IN_SERVICE_2190_DAYS)
    walk = open_inspection_for(
        api, program, vehicle=vehicle, started_at=f"{WORKSHEET_DAY}T09:00:00Z"
    )
    assert walk.inspection["vehicle_age_days_at_inspection"] == 2190

    record_results(
        api,
        walk.inspection_id,
        program.technician_headers,
        [
            result_row("P1", "PASS"),
            result_row("S1", "PASS"),
            result_row("B1", "PASS", measured_value=8.0),
        ],
    )
    submit_inspection(api, walk.inspection_id, program.dealer_headers)
    walk.certification = submit_certification(
        api, program.dealer_headers, walk.vehicle_id, walk.inspection_id
    )

    set_clock(api, "2027-01-01T00:00:00Z")
    assert read_inspection(api, walk.inspection_id)[
        "vehicle_age_days_at_inspection"
    ] == 2190

    certification = approve_certification(api, walk.certification["id"])
    assert certification["status"] == "ACTIVE"
    assert_instant_equals(
        certification["activated_at"], "2027-01-01T00:00:00Z", "activated_at"
    )
    # 2344 days by the activation date is six whole years, three of them
    # chargeable, so the raw surcharge of 55500 is trimmed to the 31465 cap.
    assert certification["fee_surcharge_cents"] == 31465
    assert certification["fee_charged_cents"] == 121365
    assert certification["warranty_anchor_variant"] == "CERTIFICATION_ANCHORED"
    assert certification["warranty_start_date"] == "2027-01-01"
    # The 84-month absolute cap lands on 2027-08-01, earlier than the raw
    # 12-month extension end of 2028-01-01.
    assert certification["warranty_end_date"] == "2027-08-01"
    assert certification["warranty_end_miles"] == 74000
    assert certification["retention_expires_at"] == "2034-08-01"


# ──────────────── the inclusive probation threshold, to the cent ─────────────

def test_a_ratio_exactly_at_the_probation_threshold_trips_probation(api, program):
    """0.50 against a 0.50 threshold is a crossing, because the bound is inclusive.

    PRD §3.9: "Otherwise, when it is at or above the probation threshold of 0.25,
    `privilege_status` becomes `PROBATION` with `privilege_reason`
    `CLAIM_RATIO_PROBATION`."
    PRD §3.9: "Third, the share is selected from the snapshot: when
    `dealer_ratio_snapshot_before` is at or above the programme's probation
    threshold of 0.25, the share is the programme's probation claim share of
    0.80, and otherwise the share is 1.00"
    PRD §3.9: "Sixth — and only after that — the privilege thresholds are
    re-evaluated against the post-claim ratio."

    Design: Difficulty/boundary_precision_check/claim_ratio_exactly_at_probation_threshold
    """
    retune_config(
        api,
        claim_ratio_probation_threshold=0.5,
        claim_ratio_suspension_threshold=0.9,
    )
    first = active_certification(api, program)
    second = active_certification(api, program)

    claim = approve_claim(
        api, file_claim(api, program.dealer_headers, first.certification_id)["id"]
    )
    # The snapshot was read before the claim counted, so it bought the full share.
    assert claim["dealer_ratio_snapshot_before"] == 0.00
    assert claim["approved_amount_cents"] == 100000

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["claim_ratio_effective"] == 0.50
    assert dealer["privilege_status"] == "PROBATION"
    assert dealer["privilege_reason"] == "CLAIM_RATIO_PROBATION"
    assert dealer["risk_score"] == 30

    # Probation is not suspension: both certifications stay live.
    assert read_certification(api, first.certification_id)["status"] == "ACTIVE"
    assert read_certification(api, second.certification_id)["status"] == "ACTIVE"


def test_a_ratio_one_hundredth_below_the_threshold_leaves_privilege_alone(
    api, program
):
    """0.50 against a 0.51 threshold is not a crossing, and nothing moves.

    PRD §3.9: "Otherwise the privilege is left unchanged."
    PRD §3.9: "Under `LIFETIME_CUMULATIVE`, `claim_ratio_effective` is
    `approved_claim_count_lifetime` divided by `lifetime_activated_count`, with 1
    substituted when that count is zero, rounded half up to 2 decimals"
    PRD §3.2: "A newly enrolled dealer begins with `privilege_status` of
    `ACTIVE`, `privilege_reason` null, `claim_ratio_variant` of
    `LIFETIME_CUMULATIVE`, and every counter at zero."

    Design: Difficulty/boundary_precision_check/claim_ratio_exactly_at_probation_threshold
    """
    retune_config(
        api,
        claim_ratio_probation_threshold=0.51,
        claim_ratio_suspension_threshold=0.9,
    )
    first = active_certification(api, program)
    active_certification(api, program)

    claim = approve_claim(
        api, file_claim(api, program.dealer_headers, first.certification_id)["id"]
    )
    assert claim["approved_amount_cents"] == 100000

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["claim_ratio_variant"] == "LIFETIME_CUMULATIVE"
    assert dealer["claim_ratio_effective"] == 0.50
    assert dealer["privilege_status"] == "ACTIVE"
    assert dealer["privilege_reason"] is None
    assert dealer["risk_score"] == 30


# ──────────────────── the audit run that draws from nothing ──────────────────

def test_an_audit_run_over_an_empty_pool_is_a_successful_run(api, program):
    """Zero eligible certifications yields a 201 with nothing selected.

    PRD §3.10: "An empty pool is not an error: a pool size of zero yields a
    `selected_count` of 0, creates no audit samples at all, and still returns a
    successful 201 Created response."
    PRD §3.10: "The `audit_run_id` is a deterministic run label built as the
    literal prefix `AR-` followed by the 1-based count of audit runs executed so
    far, so the first run is `AR-1`"
    PRD §3.10: "Certifications that are `SUBMITTED`, `UNDER_AUDIT`, `REJECTED`,
    `SUPERSEDED`, or `DECERTIFIED` are excluded, as are those belonging to a
    `SUSPENDED` dealer."

    Design: Difficulty/boundary_precision_check/audit_run_empty_pool_selects_zero
    """
    empty = draw_audit_run(api)
    assert empty["audit_run_id"] == "AR-1"
    assert empty["pool_size"] == 0
    assert empty["selected_count"] == 0
    assert empty["selected_certification_ids"] == []

    pending = submitted_certification(api, program)
    still_empty = draw_audit_run(api)
    assert still_empty["audit_run_id"] == "AR-2"
    assert still_empty["pool_size"] == 0
    assert still_empty["selected_count"] == 0
    assert still_empty["selected_certification_ids"] == []

    certification = read_certification(api, pending.certification_id)
    assert certification["status"] == "SUBMITTED"
    assert certification["audit_sampled"] is False
    assert certification["audit_sample_count"] == 0
    assert audit_samples_of(api, pending.certification_id) == []
    assert read_dealer(api, program.dealer_id)["audit_sample_count"] == 0


def test_decertified_and_suspended_rows_empty_the_pool_without_failing_the_run(
    api, program, peer_program
):
    """Live certifications can exist and the pool still be empty.

    PRD §3.10: "The eligible pool is every certification that is `ACTIVE`, whose
    `audit_sampled` flag is still false, whose `activated_at` is at or before the
    logical clock, and whose dealer's `privilege_status` is `ACTIVE` or
    `PROBATION`."
    PRD §3.10: "The number drawn is the smaller of the pool size and the greater
    of the programme's per-run minimum (1 by default) and the programme's
    sampling fraction (20 percent by default) multiplied by the pool size and
    rounded **up** to a whole number."
    PRD §3.9: "A manual move to `SUSPENDED` drives exactly the same cascade as a
    threshold-driven one"

    Design: Difficulty/boundary_precision_check/audit_run_empty_pool_selects_zero
    """
    withdrawn = active_certification(api, program)
    decertify(api, withdrawn.certification_id, "ADMIN_ACTION")
    assert read_certification(api, withdrawn.certification_id)["status"] == "DECERTIFIED"

    barred = active_certification(api, peer_program)
    set_privilege(api, peer_program.dealer_id, "SUSPENDED")
    assert read_certification(api, barred.certification_id)["status"] == "ACTIVE"

    run = draw_audit_run(api)
    assert run["audit_run_id"] == "AR-1"
    assert run["pool_size"] == 0
    assert run["selected_count"] == 0
    assert run["selected_certification_ids"] == []

    assert audit_samples_of(api, withdrawn.certification_id) == []
    assert audit_samples_of(api, barred.certification_id) == []
    assert read_certification(api, barred.certification_id)["audit_sampled"] is False
    assert read_dealer(api, peer_program.dealer_id)["audit_sample_count"] == 0
