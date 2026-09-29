"""Rejections, and what a rejection must leave behind.

The Certified Pre-Owned programme is meant to turn a quiet compliance failure
into a loud refusal, so this module works the refusal surface: the eligibility
screens that keep a rental car out of the programme, the credential gate that is
re-read on every recording, the all-or-nothing checklist batch, the conditional
documentation set, the disclosure standard that is measured against the live
rulebook rather than the pinned one, the natural keys and the scopes they are
unique inside, and the temporal windows that guard a re-inspection, a coverage
interval and a warranty claim.

Two threads run through every test. The first is precedence: a request that
breaks two rules at once may only report the earlier one, so the expected
identifier is chosen from the single ascending ladder rather than from whichever
rule looks more interesting. The second is that a refusal must be inert — the
inspection that was not opened, the result rows that were not written, the fee
that was not billed and the counters that did not move are asserted alongside
the error identifier. The closing test walks the satisfaction side of five
inclusive bounds end to end, because a service that guards those bounds with
strict comparisons refuses requests it is obliged to accept.
"""

from test_helpers import (
    ADMIN,
    CLAIM_PER_CLAIM_CAP_CENTS,
    CLOCK_EPOCH,
    INSPECTION_SLOT_MINUTES,
    LISTING_REQUIRED_DISCLOSURE_FIELDS,
    MAX_ODOMETER_MILES,
    RECON_REIMBURSEMENT_CAP_CENTS,
    REINSPECTION_DEADLINE_DAYS,
    WARRANTY_TOTAL_CAP_MILES,
    WARRANTY_TOTAL_CAP_MONTHS,
    ApiErrorId,
    add_item,
    adjudication_payload,
    approve_certification,
    assert_certification_number,
    assert_instant_equals,
    build_user_headers,
    checklist_item_payload,
    claims_of,
    clean_attempt_rows,
    complete_reconditioning,
    complete_reconditioning_payload,
    create_certification_payload,
    create_claim_payload,
    create_dealer,
    create_dealer_payload,
    create_inspection_payload,
    create_listing,
    create_listing_payload,
    create_published_template,
    create_technician,
    create_technician_payload,
    create_template,
    create_template_payload,
    create_vehicle,
    create_vehicle_payload,
    days_between,
    document,
    documents_with_reconditioning,
    documents_without_reconditioning,
    file_claim,
    file_complaint,
    get_success_data,
    iso_shift,
    item_p1_payload,
    listings_of,
    make_dealer_principal_headers,
    make_inspection_technician_headers,
    open_inspection,
    open_inspection_for,
    passed_inspection,
    read_certification,
    read_complaint,
    read_config,
    read_dealer,
    read_inspection,
    read_vehicle,
    reconditioning_item_for,
    reconditioning_items,
    record_results,
    reimbursable_for,
    result_row,
    results_payload,
    retune_config,
    set_clock,
    submit_certification,
    submit_inspection,
    syndicate_listing,
    syndicate_payload,
    unique_franchise_code,
    unique_vin,
    validate_error,
    validate_paginated,
    validate_success,
    vehicle_version,
)


def test_missing_or_unknown_identity_headers_are_unauthenticated(api):
    """Authentication is decided before the body is even parsed.

    PRD §2.1: "the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)"
    PRD §2.10: "Requests are validated in a strict, single ascending ladder"

    Design: Corner/validations/missing_identity_headers_unauthenticated
    """
    json_only = {"Content-Type": "application/json"}
    without_role = dict(json_only, **{"X-User-ID": ADMIN["X-User-ID"]})
    without_id = dict(json_only, **{"X-User-Role": ADMIN["X-User-Role"]})
    payload = create_dealer_payload(franchise_code=unique_franchise_code())

    validate_error(
        api.create_dealer(payload, without_role), ApiErrorId.ERR_UNAUTHENTICATED
    )
    validate_error(
        api.create_dealer(payload, without_id), ApiErrorId.ERR_UNAUTHENTICATED
    )
    undeclared_role = build_user_headers("mgr-1", "SalesManager")
    validate_error(
        api.get_program_config(undeclared_role), ApiErrorId.ERR_UNAUTHENTICATED
    )

    # The fourth attempt also omits the required `name`, yet authentication
    # answers first: rung 1 precedes the schema rung.
    malformed = {"franchise_code": payload["franchise_code"]}
    validate_error(
        api.create_dealer(malformed, json_only), ApiErrorId.ERR_UNAUTHENTICATED
    )

    # None of the four wrote a dealer: the franchise code is still free, and the
    # configuration the undeclared role asked for is readable by a real one.
    enrolled = create_dealer(api, franchise_code=payload["franchise_code"])
    assert enrolled["franchise_code"] == payload["franchise_code"]
    assert enrolled["privilege_status"] == "ACTIVE"
    assert enrolled["lifetime_submitted_count"] == 0
    assert read_config(api)["max_odometer_miles"] == MAX_ODOMETER_MILES


def test_rental_prior_use_is_refused_an_inspection_while_lease_is_not(api, program):
    """Prior use is screened when the inspection opens, from a configured list.

    PRD §2.6: "`ineligible_prior_uses` is `RENTAL`, `TAXI`, `DRIVING_SCHOOL`, `POLICE`"
    PRD §3.3: "Its `prior_use` must not appear in the programme's excluded prior-use list"

    Design: Corner/validations/prior_use_ineligible_rejected_at_inspection_creation
    """
    rental = create_vehicle(
        api, in_service_date="2023-05-10", odometer_miles=30000, prior_use="RENTAL"
    )
    leased = create_vehicle(
        api, in_service_date="2023-05-10", odometer_miles=30000, prior_use="LEASE"
    )
    # Registering the rental car succeeded: it may sit in inventory, it simply
    # can never be inspected for the programme.
    assert rental["prior_use"] == "RENTAL"
    assert rental["cpo_state"] == "NOT_CERTIFIED"

    refused = api.create_inspection(
        create_inspection_payload(
            rental["id"],
            program.technician_id,
            program.template_id,
            started_at=program.next_start(),
            odometer_at_inspection=30000,
        ),
        program.dealer_headers,
    )
    validate_error(refused, ApiErrorId.ERR_PRIOR_USE_INELIGIBLE)

    rows, meta = validate_paginated(
        api.list_inspections(
            program.dealer_headers, params={"vehicle_id": rental["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0
    still_out = read_vehicle(api, rental["id"])
    assert still_out["cpo_state"] == "NOT_CERTIFIED"
    assert still_out["version"] == rental["version"]

    accepted = open_inspection(
        api,
        program.dealer_headers,
        leased["id"],
        program.technician_id,
        program.template_id,
        started_at=program.next_start(),
        odometer_at_inspection=30000,
    )
    assert accepted["status"] == "DRAFT"
    assert accepted["purpose"] == "INITIAL"
    assert read_vehicle(api, leased["id"])["cpo_state"] == "CERTIFICATION_PENDING"


def test_odometer_at_inspection_is_bounded_on_both_sides(api, program, vehicle):
    """One identifier guards the programme ceiling and the monotonicity floor.

    PRD §3.3: "`odometer_at_inspection` must be at most the programme's odometer ceiling"
    PRD §3.3: "and at least the vehicle's own recorded `odometer_miles`"

    Design: Corner/validations/mileage_limits_rejected_above_max_and_below_vehicle_odometer
    """
    reading = vehicle["odometer_miles"]

    def attempt(odometer):
        return api.create_inspection(
            create_inspection_payload(
                vehicle["id"],
                program.technician_id,
                program.template_id,
                started_at=program.next_start(),
                odometer_at_inspection=odometer,
            ),
            program.dealer_headers,
        )

    validate_error(
        attempt(MAX_ODOMETER_MILES + 1), ApiErrorId.ERR_MILEAGE_LIMIT_EXCEEDED
    )
    validate_error(attempt(reading - 1), ApiErrorId.ERR_MILEAGE_LIMIT_EXCEEDED)

    _, meta = validate_paginated(
        api.list_inspections(
            program.dealer_headers, params={"vehicle_id": vehicle["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert read_vehicle(api, vehicle["id"])["cpo_state"] == "NOT_CERTIFIED"

    # Equality with the vehicle's own reading is legal, and the two rejected
    # calls left both the vehicle's slot and the technician's calendar free.
    opened = get_success_data(attempt(reading), expected_status=201)
    assert opened["odometer_at_inspection"] == reading
    assert opened["status"] == "DRAFT"
    assert read_vehicle(api, vehicle["id"])["cpo_state"] == "CERTIFICATION_PENDING"


def test_started_at_is_compared_against_the_logical_clock(api, program, vehicle):
    """A worksheet one second ahead of the logical clock is in the future.

    PRD §2.5: "Before any request moves it, the clock reads exactly `2026-08-01T00:00:00Z`"
    PRD §3.3: "The `started_at` instant must not be after the logical clock"

    Design: Corner/validations/inspection_started_at_in_future_rejected
    """
    one_second_late = iso_shift(CLOCK_EPOCH, seconds=1)

    def attempt(started_at, technician_id, **extra):
        return api.create_inspection(
            create_inspection_payload(
                vehicle["id"],
                technician_id,
                program.template_id,
                started_at=started_at,
                odometer_at_inspection=vehicle["odometer_miles"],
                **extra,
            ),
            program.dealer_headers,
        )

    validate_error(
        attempt(one_second_late, program.technician_id),
        ApiErrorId.ERR_INSPECTION_DATE_IN_FUTURE,
    )
    _, meta = validate_paginated(
        api.list_inspections(
            program.dealer_headers, params={"vehicle_id": vehicle["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert read_vehicle(api, vehicle["id"])["cpo_state"] == "NOT_CERTIFIED"

    first = get_success_data(
        attempt(CLOCK_EPOCH, program.technician_id), expected_status=201
    )
    assert_instant_equals(first["started_at"], CLOCK_EPOCH)
    slot_end = iso_shift(CLOCK_EPOCH, minutes=INSPECTION_SLOT_MINUTES)
    assert_instant_equals(first["slot_end_at"], slot_end)

    # Advancing the clock makes the previously illegal instant legal, which no
    # wall-clock implementation reproduces.
    set_clock(api, iso_shift(CLOCK_EPOCH, days=4))
    second = get_success_data(
        attempt(
            one_second_late,
            program.other_technician_id,
            parent_inspection_id=first["id"],
        ),
        expected_status=201,
    )
    assert second["purpose"] == "RE_INSPECTION"
    assert_instant_equals(second["started_at"], one_second_late)
    superseded = read_inspection(api, first["id"])
    assert superseded["status"] == "VOIDED"
    assert superseded["failure_reason"] == "SUPERSEDED_BY_REINSPECTION"


def test_credential_gate_is_re_evaluated_on_every_recording(api, program, vehicle):
    """Status and expiry are a conjunction, and it is re-read at every recording.

    PRD §3.3: "so a credential lapsing at exactly the current instant is already lapsed"
    PRD §3.4: "The technician's credential is re-checked at every recording"

    Design: Corner/validations/technician_credential_not_active_rejected
    """
    tomorrow = iso_shift(CLOCK_EPOCH, days=1)
    revoked = create_technician(
        api,
        program.dealer_id,
        name="Rev Tech",
        credential_status="REVOKED",
        credential_expires_at="2027-01-01T00:00:00Z",
    )
    lapsing = create_technician(
        api, program.dealer_id, name="Edge Tech", credential_expires_at=CLOCK_EPOCH
    )
    working = create_technician(
        api, program.dealer_id, name="Ok Tech", credential_expires_at=tomorrow
    )

    def attempt(technician_id):
        return api.create_inspection(
            create_inspection_payload(
                vehicle["id"],
                technician_id,
                program.template_id,
                started_at=program.next_start(),
                odometer_at_inspection=vehicle["odometer_miles"],
            ),
            program.dealer_headers,
        )

    # A revoked credential expiring months from now still disqualifies, and so
    # does an active one expiring at exactly the clock instant.
    validate_error(
        attempt(revoked["id"]), ApiErrorId.ERR_TECHNICIAN_CREDENTIAL_EXPIRED
    )
    validate_error(
        attempt(lapsing["id"]), ApiErrorId.ERR_TECHNICIAN_CREDENTIAL_EXPIRED
    )
    opened = get_success_data(attempt(working["id"]), expected_status=201)
    assert opened["status"] == "DRAFT"
    assert opened["attempt_count"] == 0

    set_clock(api, tomorrow)
    refused = api.record_results(
        opened["id"],
        results_payload([result_row("P1", "PASS")]),
        make_inspection_technician_headers(working["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_TECHNICIAN_CREDENTIAL_EXPIRED)

    unchanged = read_inspection(api, opened["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["attempt_count"] == 0
    assert unchanged["recorded_item_count"] == 0
    assert unchanged["version"] == opened["version"]
    rows, meta = validate_paginated(api.list_results(opened["id"], ADMIN))
    assert rows == []
    assert meta["total_count"] == 0
    roster = validate_success(api.list_technicians(program.dealer_id, ADMIN))
    counts = {row["id"]: row["completed_inspection_count"] for row in roster}
    assert counts[working["id"]] == 0


def test_only_a_named_parent_excuses_a_second_open_inspection(api, program, vehicle):
    """The same body is refused or accepted purely on `parent_inspection_id`.

    PRD §3.3: "A vehicle may have only one live inspection at a time"
    PRD §3.3: "the request names exactly that inspection as its `parent_inspection_id`"
    PRD §3.5: "moves to `VOIDED` with a `failure_reason` of `SUPERSEDED_BY_REINSPECTION`"

    Design: Corner/validations/second_open_inspection_for_same_vehicle_rejected
    """
    third = create_technician(api, program.dealer_id, name="Cy Tech")
    first = open_inspection_for(api, program, vehicle=vehicle).inspection
    assert first["status"] == "DRAFT"

    def attempt(technician_id, **extra):
        return api.create_inspection(
            create_inspection_payload(
                vehicle["id"],
                technician_id,
                program.template_id,
                started_at=program.next_start(),
                odometer_at_inspection=vehicle["odometer_miles"],
                **extra,
            ),
            program.dealer_headers,
        )

    # `DRAFT` is one of the three blocking states, and the second technician's
    # own calendar was free, so nothing but the open row explains the refusal.
    validate_error(
        attempt(program.other_technician_id), ApiErrorId.ERR_INSPECTION_ALREADY_OPEN
    )
    _, meta = validate_paginated(
        api.list_inspections(
            program.dealer_headers, params={"vehicle_id": vehicle["id"]}
        )
    )
    assert meta["total_count"] == 1

    second = get_success_data(
        attempt(program.other_technician_id, parent_inspection_id=first["id"]),
        expected_status=201,
    )
    assert second["purpose"] == "RE_INSPECTION"
    assert second["parent_inspection_id"] == first["id"]
    parent = read_inspection(api, first["id"])
    assert parent["status"] == "VOIDED"
    assert parent["failure_reason"] == "SUPERSEDED_BY_REINSPECTION"

    # The replacement is itself blocking now, and naming the already-voided
    # parent does not excuse a third open row.
    validate_error(
        attempt(third["id"], parent_inspection_id=first["id"]),
        ApiErrorId.ERR_INSPECTION_ALREADY_OPEN,
    )
    rows, meta = validate_paginated(
        api.list_inspections(
            program.dealer_headers, params={"vehicle_id": vehicle["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert second["id"] in [row["id"] for row in rows]
    assert read_vehicle(api, vehicle["id"])["cpo_state"] == "CERTIFICATION_PENDING"


def test_unknown_item_code_rejects_the_whole_results_batch(api, program, vehicle):
    """A code that resolves on another template rejects every row beside it.

    PRD §3.4: "a code that resolves to nothing is rejected with `ERR_UNKNOWN_CHECKLIST_ITEM`"
    PRD §3.4: "it increments the inspection's `attempt_count` by exactly 1"

    Design: Corner/validations/unknown_item_code_rejects_whole_results_batch
    """
    # A second published catalogue generation carries `X9`. Its `effective_from`
    # predates the programme template's, so publishing it retires nothing.
    elsewhere = create_published_template(
        api,
        items=[
            checklist_item_payload(
                item_code="X9",
                category="ELECTRICAL",
                pass_criteria="no stored electrical faults",
                reconditioning_allowed=False,
            )
        ],
        effective_from="2025-06-01",
    )
    assert elsewhere["status"] == "PUBLISHED"
    in_use = validate_success(api.get_checklist_template(program.template_id, ADMIN))
    assert in_use["status"] == "PUBLISHED"

    walk = open_inspection_for(api, program, vehicle=vehicle)
    valid_rows = [result_row("P1", "PASS"), result_row("S1", "PASS")]
    refused = api.record_results(
        walk.inspection_id,
        results_payload(valid_rows + [result_row("X9", "PASS")]),
        program.technician_headers,
    )
    validate_error(refused, ApiErrorId.ERR_UNKNOWN_CHECKLIST_ITEM)

    untouched = read_inspection(api, walk.inspection_id)
    assert untouched["status"] == "DRAFT"
    assert untouched["attempt_count"] == 0
    assert untouched["recorded_item_count"] == 0
    assert untouched["version"] == walk.inspection["version"]
    rows, meta = validate_paginated(api.list_results(walk.inspection_id, ADMIN))
    assert rows == []
    assert meta["total_count"] == 0

    # The same batch minus that one row would have been accepted, so the
    # rejection is attributable to it alone.
    accepted = record_results(
        api, walk.inspection_id, program.technician_headers, valid_rows
    )
    assert accepted["status"] == "IN_PROGRESS"
    assert accepted["attempt_count"] == 1
    assert accepted["recorded_item_count"] == 2


def test_measured_points_must_agree_with_their_recorded_outcome(api, program, vehicle):
    """A measured point is contradicted from three directions and passes at both ends.

    PRD §3.4: "a `PASS` requires a reading inside the inclusive band bounded below by"
    PRD §3.4: "a measured point recorded with no reading at all is rejected"
    PRD §3.4: "On an unmeasured point, `measured_value` stays null."

    Design: Corner/validations/measurement_contradicts_outcome_rejected
    """
    walk = open_inspection_for(api, program, vehicle=vehicle)

    def attempt(brake_row):
        return api.record_results(
            walk.inspection_id,
            results_payload(
                [result_row("P1", "PASS"), result_row("S1", "PASS"), brake_row]
            ),
            program.technician_headers,
        )

    validate_error(
        attempt(result_row("B1", "PASS", measured_value=3.9)),
        ApiErrorId.ERR_MEASUREMENT_CONTRADICTS_OUTCOME,
    )
    validate_error(
        attempt(result_row("B1", "FAIL", measured_value=8.0)),
        ApiErrorId.ERR_MEASUREMENT_CONTRADICTS_OUTCOME,
    )
    # The absent reading is not a schema violation, because the field is
    # optional; it is the contradiction with the outcome that refuses the row.
    validate_error(
        attempt(result_row("B1", "PASS")),
        ApiErrorId.ERR_MEASUREMENT_CONTRADICTS_OUTCOME,
    )

    still_draft = read_inspection(api, walk.inspection_id)
    assert still_draft["status"] == "DRAFT"
    assert still_draft["attempt_count"] == 0
    assert still_draft["version"] == walk.inspection["version"]
    _, meta = validate_paginated(api.list_results(walk.inspection_id, ADMIN))
    assert meta["total_count"] == 0

    low = validate_success(attempt(result_row("B1", "PASS", measured_value=4.0)))
    assert low["attempt_count"] == 1
    high = validate_success(attempt(result_row("B1", "PASS", measured_value=12.0)))
    assert high["attempt_count"] == 2
    assert high["recorded_item_count"] == 3

    rows, meta = validate_paginated(api.list_results(walk.inspection_id, ADMIN))
    assert meta["total_count"] == 6
    assert sorted({row["attempt_index"] for row in rows}) == [1, 2]
    unmeasured = [row for row in rows if row["item_code"] == "P1"]
    assert len(unmeasured) == 2
    assert all(row["measured_value"] is None for row in unmeasured)


def test_submit_reports_an_incomplete_checklist_before_an_open_repair(
    api, program, vehicle
):
    """Completeness answers before the outstanding repair does.

    PRD §2.10: "Checklist completeness at submission — otherwise `ERR_INCOMPLETE_CHECKLIST`"
    PRD §3.5: "the inspection's `recorded_item_count` must equal its template's `point_count`"
    PRD §3.5: "A clean attempt still cannot pass while a repair is outstanding."

    Design: Corner/validations/submit_blocked_by_incomplete_checklist_then_by_open_reconditioning
    """
    walk = open_inspection_for(api, program, vehicle=vehicle)
    record_results(
        api,
        walk.inspection_id,
        program.technician_headers,
        [
            result_row("P1", "PASS"),
            result_row("S1", "PASS"),
            result_row("B1", "FAIL", measured_value=2.0),
        ],
    )
    needs_repair = submit_inspection(api, walk.inspection_id, program.dealer_headers)
    assert needs_repair["status"] == "RECONDITIONING_REQUIRED"
    repairs = reconditioning_items(api, walk.inspection_id)
    assert len(repairs) == 1
    assert repairs[0]["item_code"] == "B1"
    assert repairs[0]["status"] == "REQUIRED"

    # Re-recording only the repaired point regresses the attempt to incomplete.
    partial = record_results(
        api,
        walk.inspection_id,
        program.technician_headers,
        [result_row("B1", "PASS", measured_value=8.0)],
    )
    assert partial["status"] == "IN_PROGRESS"
    assert partial["attempt_count"] == 2
    assert partial["recorded_item_count"] == 1

    validate_error(
        api.submit_inspection(walk.inspection_id, program.dealer_headers),
        ApiErrorId.ERR_INCOMPLETE_CHECKLIST,
    )
    blocked = read_inspection(api, walk.inspection_id)
    assert blocked["status"] == "IN_PROGRESS"
    assert blocked["submitted_at"] is None
    assert blocked["version"] == partial["version"]
    assert reconditioning_items(api, walk.inspection_id)[0]["status"] == "REQUIRED"

    complete = record_results(
        api, walk.inspection_id, program.technician_headers, clean_attempt_rows()
    )
    assert complete["attempt_count"] == 3
    assert complete["recorded_item_count"] == 3
    validate_error(
        api.submit_inspection(walk.inspection_id, program.dealer_headers),
        ApiErrorId.ERR_RECONDITIONING_INCOMPLETE,
    )
    assert read_inspection(api, walk.inspection_id)["status"] == "IN_PROGRESS"

    closed = complete_reconditioning(
        api, repairs[0]["id"], 50000, program.other_technician_headers
    )
    assert closed["status"] == "COMPLETED"
    passed = submit_inspection(api, walk.inspection_id, program.dealer_headers)
    assert passed["status"] == "PASSED"
    assert_instant_equals(passed["submitted_at"], CLOCK_EPOCH)
    assert passed["total_recon_cost_cents"] == 50000
    assert passed["total_reimbursable_cents"] == reimbursable_for(50000, 100000)

    roster = validate_success(api.list_technicians(program.dealer_id, ADMIN))
    counts = {row["id"]: row["completed_inspection_count"] for row in roster}
    assert counts[program.technician_id] == 1
    assert counts[program.other_technician_id] == 0


def test_reconditioning_invoice_is_required_exactly_when_repairs_happened(api, program):
    """One documents array is complete for one inspection and illegal for another.

    PRD §3.6: "it is *forbidden* when the inspection produced none"
    PRD §3.6: "supplying the same `doc_type` twice, is rejected with `ERR_DOCUMENT_NOT_APPLICABLE`"

    Design: Corner/validations/certification_document_set_conditional_and_duplicate_rules
    """
    clean = passed_inspection(api, program)
    repaired = open_inspection_for(
        api, program, technician_id=program.other_technician_id
    )
    record_results(
        api,
        repaired.inspection_id,
        program.other_technician_headers,
        [
            result_row("P1", "PASS"),
            result_row("S1", "PASS"),
            result_row("B1", "FAIL", measured_value=2.0),
        ],
    )
    submit_inspection(api, repaired.inspection_id, program.dealer_headers)
    repair = reconditioning_item_for(api, repaired.inspection_id, "B1")
    complete_reconditioning(api, repair["id"], 50000, program.technician_headers)
    record_results(
        api,
        repaired.inspection_id,
        program.other_technician_headers,
        clean_attempt_rows(),
    )
    repaired.inspection = submit_inspection(
        api, repaired.inspection_id, program.dealer_headers
    )
    assert repaired.inspection["status"] == "PASSED"
    assert reconditioning_items(api, clean.inspection_id) == []

    def attempt(walk, documents):
        return api.create_certification(
            create_certification_payload(
                walk.vehicle_id,
                walk.inspection_id,
                vehicle_version(api, walk.vehicle_id),
                documents=documents,
            ),
            program.dealer_headers,
        )

    validate_error(
        attempt(clean, documents_without_reconditioning()[:2]),
        ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE,
    )
    # A superset of every required type, but the invoice is inapplicable here.
    validate_error(
        attempt(clean, documents_with_reconditioning()),
        ApiErrorId.ERR_DOCUMENT_NOT_APPLICABLE,
    )
    duplicated = [
        document("TITLE_HISTORY_REPORT", "THR-C"),
        document("TITLE_HISTORY_REPORT", "THR-C2"),
        document("INSPECTION_WORKSHEET", "IW-C"),
        document("CUSTOMER_DISCLOSURE", "CD-C"),
    ]
    validate_error(
        attempt(clean, duplicated), ApiErrorId.ERR_DOCUMENT_NOT_APPLICABLE
    )
    # The identical three-document array is merely incomplete for the car that
    # was repaired, because the invoice is now conditionally required.
    validate_error(
        attempt(repaired, documents_without_reconditioning("R")),
        ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE,
    )

    _, meta = validate_paginated(
        api.list_certifications(ADMIN, params={"vehicle_id": clean.vehicle_id})
    )
    assert meta["total_count"] == 0

    accepted = get_success_data(
        attempt(repaired, documents_with_reconditioning("R")), expected_status=201
    )
    assert accepted["status"] == "SUBMITTED"
    assert accepted["document_count"] == 4
    # The four refusals never incremented the dealer's submission sequence.
    assert_certification_number(
        accepted["certification_number"], program.dealer["franchise_code"], 1
    )
    assert read_dealer(api, program.dealer_id)["lifetime_submitted_count"] == 1


def test_an_active_certification_blocks_a_further_submission(api, program, passed_walk):
    """A submitted row may be superseded; a live one blocks outright.

    PRD §2.10: "The vehicle's certification slot is free"
    PRD §3.6: "A vehicle holding a single still-`SUBMITTED` certification is a different matter"
    PRD §3.6: "the new submission legitimately **supersedes** it"

    Design: Corner/validations/vehicle_already_certified_blocks_third_submission
    """
    first = submit_certification(
        api,
        program.dealer_headers,
        passed_walk.vehicle_id,
        passed_walk.inspection_id,
        documents=documents_without_reconditioning("1"),
    )
    assert first["status"] == "SUBMITTED"
    second = submit_certification(
        api,
        program.dealer_headers,
        passed_walk.vehicle_id,
        passed_walk.inspection_id,
        documents=documents_without_reconditioning("2"),
    )
    assert second["status"] == "SUBMITTED"
    assert read_certification(api, first["id"])["status"] == "SUPERSEDED"
    assert_certification_number(
        second["certification_number"], program.dealer["franchise_code"], 2
    )
    assert approve_certification(api, second["id"])["status"] == "ACTIVE"

    # The guard value is read immediately before the call, so the refusal is
    # the occupied slot rather than a stale vehicle generation.
    current = vehicle_version(api, passed_walk.vehicle_id)
    refused = api.create_certification(
        create_certification_payload(
            passed_walk.vehicle_id,
            passed_walk.inspection_id,
            current,
            documents=documents_without_reconditioning("3"),
        ),
        program.dealer_headers,
    )
    validate_error(refused, ApiErrorId.ERR_VEHICLE_ALREADY_CERTIFIED)

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["lifetime_submitted_count"] == 2
    assert dealer["active_certification_count"] == 1
    _, meta = validate_paginated(
        api.list_certifications(ADMIN, params={"vehicle_id": passed_walk.vehicle_id})
    )
    assert meta["total_count"] == 2
    car = read_vehicle(api, passed_walk.vehicle_id)
    assert car["version"] == current
    assert car["active_certification_count"] == 1
    assert car["certified_certification_id"] == second["id"]


def test_disclosure_tokens_are_checked_against_the_live_configuration(api, active_walk):
    """The superset test reads the live rulebook on both listing endpoints.

    PRD §3.8: "extra tokens are permitted, but omitting any required one is rejected"
    PRD §3.8: "a certification may hold at most one listing per channel that is not `WITHDRAWN`"
    PRD §3.8: "The disclosure superset rule is re-checked here as well"

    Design: Corner/validations/listing_disclosure_tokens_checked_on_create_and_on_syndicate
    """
    dealer_headers = active_walk.dealer_headers
    certification_id = active_walk.certification_id
    required = list(LISTING_REQUIRED_DISCLOSURE_FIELDS)

    refused = api.create_listing(
        create_listing_payload(certification_id, disclosure_fields=required[:3]),
        dealer_headers,
    )
    validate_error(refused, ApiErrorId.ERR_MARKETING_STANDARD_VIOLATION)
    assert listings_of(api, certification_id) == []

    listing = create_listing(
        api,
        dealer_headers,
        certification_id,
        disclosure_fields=required + ["ONE_OWNER"],
    )
    assert listing["status"] == "DRAFT"
    assert listing["syndicated_at"] is None
    assert listing["syndicated_snapshot_version"] is None

    duplicate = api.create_listing(
        create_listing_payload(certification_id, price_cents=2499000), dealer_headers
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_RESOURCE)
    assert len(listings_of(api, certification_id)) == 1

    # Tightening the live token list makes a legally drafted row unpublishable
    # without touching the row itself.
    retune_config(
        api, listing_required_disclosure_fields=required + ["TITLE_HISTORY_SUMMARY"]
    )
    pinned = read_certification(api, certification_id)["version"]
    stalled = api.syndicate_listing(
        listing["id"], syndicate_payload(pinned), dealer_headers
    )
    validate_error(stalled, ApiErrorId.ERR_MARKETING_STANDARD_VIOLATION)
    still_draft = listings_of(api, certification_id)[0]
    assert still_draft["status"] == "DRAFT"
    assert still_draft["syndicated_at"] is None
    assert still_draft["version"] == listing["version"]
    parked = read_certification(api, certification_id)
    assert parked["listing_syndicated_at"] is None
    assert parked["version"] == pinned

    # Withdrawing the token makes it syndicatable again, and the concurrency
    # token the refused call carried is still current.
    retune_config(api, listing_required_disclosure_fields=required)
    published = syndicate_listing(api, listing["id"], dealer_headers, pinned)
    assert published["status"] == "SYNDICATED"
    assert_instant_equals(published["syndicated_at"], CLOCK_EPOCH)
    live = read_certification(api, certification_id)
    assert live["version"] == pinned + 1
    assert published["syndicated_snapshot_version"] == live["version"]
    assert_instant_equals(live["listing_syndicated_at"], CLOCK_EPOCH)


def test_natural_keys_are_unique_only_inside_their_own_scope(
    api, admin_headers, program
):
    """Three keys are global, two are scoped, and the negative controls prove it.

    PRD §3.1: "an `item_code` such as `B1`, unique within its template"
    PRD §3.2: "The `franchise_code` must be non-empty and unique across all dealers"
    PRD §3.2: "a `vin` of exactly 17 characters and unique across all vehicles"
    PRD §3.2: "must be unique within the employing dealer"

    Design: Corner/validations/duplicate_natural_keys_rejected_within_their_scopes
    """
    peer = create_dealer(api, name="Ridge Motors", region_code="EAST")
    vin = unique_vin()
    original = create_vehicle(api, vin=vin)
    credential = program.technician["credential_id"]

    validate_error(
        api.create_dealer(
            create_dealer_payload(
                name="Copycat Motors",
                region_code="SOUTH",
                franchise_code=program.dealer["franchise_code"],
            ),
            admin_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE,
    )
    # The VIN alone refuses the car, although every other field differs.
    validate_error(
        api.create_vehicle(
            create_vehicle_payload(
                vin=vin,
                in_service_date="2022-03-01",
                odometer_miles=41000,
                owner_count=2,
            ),
            admin_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE,
    )
    validate_error(
        api.create_checklist_template(
            create_template_payload(
                code=program.template["code"], effective_from="2026-06-01"
            ),
            admin_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE,
    )

    draft = create_template(api)
    add_item(api, draft["id"], item_p1_payload())
    validate_error(
        api.add_checklist_item(
            draft["id"],
            item_p1_payload(
                category="BRAKES",
                severity="MAJOR",
                pass_criteria="duplicate code on the same template",
            ),
            admin_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE,
    )
    # Scoped to the template, so the same code is legal on a second one.
    sibling = create_template(api)
    assert add_item(api, sibling["id"], item_p1_payload())["item_code"] == "P1"

    validate_error(
        api.create_technician(
            program.dealer_id,
            create_technician_payload(name="Twin Tech", credential_id=credential),
            admin_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE,
    )
    # Scoped to the employer, so the same credential is legal under a peer.
    far = create_technician(
        api, peer["id"], name="Far Tech", credential_id=credential
    )
    assert far["credential_id"] == credential
    assert far["dealer_id"] == peer["id"]

    # Nothing the five refusals named was overwritten.
    enrolled = read_dealer(api, program.dealer_id)
    assert enrolled["region_code"] == program.dealer["region_code"]
    assert enrolled["name"] == program.dealer["name"]
    unchanged = read_vehicle(api, original["id"])
    assert unchanged["in_service_date"] == original["in_service_date"]
    assert unchanged["odometer_miles"] == original["odometer_miles"]
    assert unchanged["owner_count"] == original["owner_count"]
    assert unchanged["version"] == original["version"]
    kept = validate_success(api.get_checklist_template(draft["id"], admin_headers))
    assert kept["point_count"] == 1
    assert kept["critical_item_count"] == 1
    items, meta = validate_paginated(
        api.list_checklist_items(draft["id"], admin_headers)
    )
    assert [row["item_code"] for row in items] == ["P1"]
    assert meta["total_count"] == 1
    roster = validate_success(api.list_technicians(program.dealer_id, admin_headers))
    assert [row["credential_id"] for row in roster].count(credential) == 1
    peer_roster = validate_success(api.list_technicians(peer["id"], admin_headers))
    assert [row["credential_id"] for row in peer_roster] == [credential]


def test_the_reinspection_window_travels_with_each_complaint(
    api, program, active_walk
):
    """Each complaint carries its own deadline, and equality with it is legal.

    PRD §3.11: "a derived `reinspection_deadline_at` equal to `filed_at` plus five days"
    PRD §3.11: "the bound is inclusive, so an order at exactly the deadline instant is accepted"
    PRD §3.11: "opening a re-inspection leaves the vehicle's `cpo_state` at `CERTIFIED`"

    Design: Corner/validations/reinspection_after_complaint_deadline_rejected
    """
    odometer = active_walk.vehicle["odometer_miles"]
    early = file_complaint(
        api,
        active_walk.certification_id,
        customer_reference="CUST-A",
        category="UNDISCLOSED_DAMAGE",
    )
    deadline = iso_shift(CLOCK_EPOCH, days=REINSPECTION_DEADLINE_DAYS)
    assert_instant_equals(early["filed_at"], CLOCK_EPOCH)
    assert_instant_equals(early["reinspection_deadline_at"], deadline)

    # One second past the deadline, even though `started_at` itself is legal.
    past_deadline = iso_shift(deadline, seconds=1)
    set_clock(api, past_deadline)
    refused = api.create_inspection(
        create_inspection_payload(
            active_walk.vehicle_id,
            program.other_technician_id,
            program.template_id,
            started_at=deadline,
            odometer_at_inspection=odometer,
            complaint_id=early["id"],
        ),
        program.dealer_headers,
    )
    validate_error(refused, ApiErrorId.ERR_REINSPECTION_DEADLINE_PASSED)
    unmoved = read_complaint(api, early["id"])
    assert unmoved["status"] == "OPEN"
    assert unmoved["reinspection_ordered_at"] is None
    assert unmoved["version"] == early["version"]
    _, meta = validate_paginated(
        api.list_inspections(
            program.dealer_headers, params={"complaint_id": early["id"]}
        )
    )
    assert meta["total_count"] == 0

    later = file_complaint(
        api, active_walk.certification_id, customer_reference="CUST-B"
    )
    assert_instant_equals(later["filed_at"], past_deadline)
    own_deadline = iso_shift(past_deadline, days=REINSPECTION_DEADLINE_DAYS)
    assert_instant_equals(later["reinspection_deadline_at"], own_deadline)

    set_clock(api, own_deadline)
    reinspection = open_inspection(
        api,
        program.dealer_headers,
        active_walk.vehicle_id,
        program.other_technician_id,
        program.template_id,
        started_at=own_deadline,
        odometer_at_inspection=odometer,
        complaint_id=later["id"],
    )
    assert reinspection["purpose"] == "RE_INSPECTION"
    assert reinspection["complaint_id"] == later["id"]
    # A fresh pair of eyes, as the complaint-driven path demands.
    assert reinspection["technician_id"] != active_walk.inspection["technician_id"]
    ordered = read_complaint(api, later["id"])
    assert ordered["status"] == "REINSPECTION_ORDERED"
    assert_instant_equals(ordered["reinspection_ordered_at"], own_deadline)
    stale = read_complaint(api, early["id"])
    assert stale["status"] == "OPEN"
    assert stale["reinspection_ordered_at"] is None
    assert read_vehicle(api, active_walk.vehicle_id)["cpo_state"] == "CERTIFIED"


def test_approval_needs_a_non_empty_interval_on_both_axes(
    api, program, submitted_walk
):
    """Emptiness is an "at or below" test on the date axis and on the mileage axis.

    PRD §3.6: "A newly submitted certification carries no financial or coverage content"
    PRD §3.7: "`warranty_end_date` at or before `warranty_start_date`"
    PRD §3.7: "or `warranty_end_miles` at or below the inspection's `odometer_at_inspection`"

    Design: Corner/validations/approval_without_remaining_coverage_rejected
    """
    certification_id = submitted_walk.certification_id

    # 54 months of total cap lands the clamped end date exactly on the start.
    retune_config(api, warranty_total_cap_months=54)
    validate_error(
        api.adjudicate_certification(
            certification_id, adjudication_payload("APPROVE"), ADMIN
        ),
        ApiErrorId.ERR_NO_COVERAGE_REMAINING,
    )
    waiting = read_certification(api, certification_id)
    assert waiting["status"] == "SUBMITTED"
    assert waiting["activated_at"] is None
    assert waiting["program_config_version"] is None
    assert waiting["warranty_start_date"] is None
    assert waiting["warranty_end_date"] is None
    assert waiting["warranty_end_miles"] is None
    assert waiting["fee_charged_cents"] == 0

    # The mileage axis is tested independently, and the same way.
    retune_config(
        api,
        warranty_total_cap_months=WARRANTY_TOTAL_CAP_MONTHS,
        warranty_total_cap_miles=62000,
    )
    validate_error(
        api.adjudicate_certification(
            certification_id, adjudication_payload("APPROVE"), ADMIN
        ),
        ApiErrorId.ERR_NO_COVERAGE_REMAINING,
    )
    assert read_certification(api, certification_id)["status"] == "SUBMITTED"
    before = read_dealer(api, program.dealer_id)
    assert before["lifetime_activated_count"] == 0
    assert before["fee_billed_cents_total"] == 0
    assert before["fee_balance_cents"] == 0

    retune_config(api, warranty_total_cap_miles=WARRANTY_TOTAL_CAP_MILES)
    approved = approve_certification(api, certification_id)
    assert approved["status"] == "ACTIVE"
    assert approved["warranty_anchor_variant"] == "CERTIFICATION_ANCHORED"
    assert approved["warranty_start_date"] == "2026-08-01"
    assert approved["warranty_end_date"] == "2027-08-01"
    assert approved["warranty_end_miles"] == 74000
    assert approved["fee_charged_cents"] == 120400
    assert approved["program_config_version"] == read_config(api)["version"]
    assert_instant_equals(approved["activated_at"], CLOCK_EPOCH)

    after = read_dealer(api, program.dealer_id)
    assert after["lifetime_activated_count"] == 1
    assert after["fee_billed_cents_total"] == 120400
    assert after["fee_balance_cents"] == 120400


def test_the_claim_window_is_checked_before_the_per_claim_cap(api, active_walk):
    """The window answers first, and every bound it draws is tested on both sides.

    PRD §2.10: "Claimed repair inside the coverage window"
    PRD §3.9: "at or after `warranty_start_date` and strictly before `warranty_end_date`"
    PRD §3.9: "`repair_odometer_miles` must be at most `warranty_end_miles`"

    Design: Corner/validations/claim_outside_window_and_above_cap_rejected
    """
    certification = active_walk.certification
    assert certification["warranty_start_date"] == "2026-08-01"
    assert certification["warranty_end_date"] == "2027-08-01"
    assert certification["warranty_end_miles"] == 74000

    def attempt(**overrides):
        return api.create_warranty_claim(
            create_claim_payload(active_walk.certification_id, **overrides),
            active_walk.dealer_headers,
        )

    validate_error(
        attempt(
            component_category="POWERTRAIN",
            repair_date="2026-07-31",
            repair_odometer_miles=62500,
            claimed_amount_cents=50000,
        ),
        ApiErrorId.ERR_OUTSIDE_WARRANTY_WINDOW,
    )
    # The end date is the first uncovered date, so it is outside the interval.
    validate_error(
        attempt(
            repair_date="2027-08-01",
            repair_odometer_miles=70000,
            claimed_amount_cents=50000,
        ),
        ApiErrorId.ERR_OUTSIDE_WARRANTY_WINDOW,
    )
    validate_error(
        attempt(
            repair_date="2026-09-01",
            repair_odometer_miles=74001,
            claimed_amount_cents=50000,
        ),
        ApiErrorId.ERR_OUTSIDE_WARRANTY_WINDOW,
    )
    # Outside the window *and* above the ceiling: the earlier rung answers.
    validate_error(
        attempt(
            repair_date="2027-08-01",
            repair_odometer_miles=74001,
            claimed_amount_cents=CLAIM_PER_CLAIM_CAP_CENTS + 1,
        ),
        ApiErrorId.ERR_OUTSIDE_WARRANTY_WINDOW,
    )
    validate_error(
        attempt(
            repair_date="2026-09-01",
            repair_odometer_miles=70000,
            claimed_amount_cents=CLAIM_PER_CLAIM_CAP_CENTS + 1,
        ),
        ApiErrorId.ERR_CLAIM_AMOUNT_EXCEEDS_CAP,
    )
    assert claims_of(api, active_walk.certification_id) == []

    accepted = file_claim(
        api,
        active_walk.dealer_headers,
        active_walk.certification_id,
        component_category="ELECTRICAL",
        repair_date="2026-08-01",
        repair_odometer_miles=74000,
        claimed_amount_cents=CLAIM_PER_CLAIM_CAP_CENTS,
    )
    assert accepted["status"] == "SUBMITTED"
    assert accepted["approved_amount_cents"] == 0
    assert accepted["dealer_ratio_snapshot_before"] is None
    assert accepted["adjudicated_at"] is None
    # Filing is not an approval.
    live = read_certification(api, active_walk.certification_id)
    assert live["approved_claim_count"] == 0
    assert live["approved_claim_amount_cents"] == 0


def test_reconditioning_cost_ceiling_is_the_points_own_cap(api, program, vehicle):
    """The ceiling resolves through the repaired point, not the programme cap.

    PRD §3.1: "defaulting to 100000 cents, is the per-item ceiling"
    PRD §3.5: "at most the resolved point's `max_reconditioning_cost_cents`"
    PRD §3.5: "round that product half up to whole cents"

    Design: Corner/validations/reconditioning_cost_above_item_cap_rejected
    """
    walk = open_inspection_for(api, program, vehicle=vehicle)
    record_results(
        api,
        walk.inspection_id,
        program.technician_headers,
        [
            result_row("P1", "PASS"),
            result_row("S1", "FAIL"),
            result_row("B1", "FAIL", measured_value=2.0),
        ],
    )
    submit_inspection(api, walk.inspection_id, program.dealer_headers)
    brakes = reconditioning_item_for(api, walk.inspection_id, "B1")
    safety = reconditioning_item_for(api, walk.inspection_id, "S1")
    assert brakes["severity"] == "MAJOR"
    assert safety["severity"] == "CRITICAL"

    refused = api.complete_reconditioning_item(
        brakes["id"],
        complete_reconditioning_payload(100001),
        program.other_technician_headers,
    )
    validate_error(refused, ApiErrorId.ERR_RECONDITIONING_COST_EXCEEDS_CAP)
    untouched = reconditioning_item_for(api, walk.inspection_id, "B1")
    assert untouched["status"] == "REQUIRED"
    assert untouched["actual_cost_cents"] is None
    assert untouched["reimbursable_cents"] == 0
    assert untouched["completed_at"] is None
    assert untouched["closed_by_user_id"] is None
    assert untouched["version"] == brakes["version"]

    # The very same amount is legal on the point whose own cap is 200000.
    generous = complete_reconditioning(
        api, safety["id"], 100001, program.other_technician_headers
    )
    assert generous["status"] == "COMPLETED"
    assert generous["reimbursable_cents"] == reimbursable_for(100001, 200000)
    # And exactly at the cap is legal, because the test is "does not exceed".
    at_cap = complete_reconditioning(
        api, brakes["id"], 100000, program.other_technician_headers
    )
    assert at_cap["status"] == "COMPLETED"
    assert at_cap["reimbursable_cents"] == reimbursable_for(100000, 100000)

    inspection = read_inspection(api, walk.inspection_id)
    expected = reimbursable_for(100001, 200000) + reimbursable_for(100000, 100000)
    assert inspection["total_recon_cost_cents"] == 200001
    assert inspection["total_reimbursable_cents"] == expected
    assert expected < RECON_REIMBURSEMENT_CAP_CENTS


def test_inclusive_boundaries_are_accepted_end_to_end(api):
    """Five inclusive bounds, each pinned to its exact limit, in one pipeline.

    PRD §3.3: "`odometer_at_inspection` must be at most the programme's odometer ceiling"
    PRD §3.3: "`credential_expires_at` must be strictly after the logical clock"
    PRD §3.9: "`repair_odometer_miles` must be at most `warranty_end_miles`"

    Design: Corner/validations/inclusive_boundaries_accepted_end_to_end
    """
    dealer = create_dealer(api)
    dealer_headers = make_dealer_principal_headers(dealer["id"])
    technician = create_technician(
        api,
        dealer["id"],
        name="Edge Tech",
        credential_expires_at=iso_shift(CLOCK_EPOCH, seconds=1),
    )
    template = create_published_template(api, items=[item_p1_payload()])
    car = create_vehicle(
        api, in_service_date="2023-05-10", odometer_miles=MAX_ODOMETER_MILES
    )

    # The worksheet reading equals both the programme ceiling and the vehicle's
    # own odometer, and `started_at` equals the logical clock.
    inspection = open_inspection(
        api,
        dealer_headers,
        car["id"],
        technician["id"],
        template["id"],
        started_at=CLOCK_EPOCH,
        odometer_at_inspection=MAX_ODOMETER_MILES,
    )
    assert inspection["odometer_at_inspection"] == MAX_ODOMETER_MILES
    assert_instant_equals(inspection["started_at"], CLOCK_EPOCH)
    expected_age = days_between("2023-05-10", "2026-08-01")
    assert inspection["vehicle_age_days_at_inspection"] == expected_age

    # The credential expires one second after the clock, which is enough.
    recorded = record_results(
        api,
        inspection["id"],
        make_inspection_technician_headers(technician["id"]),
        [result_row("P1", "PASS")],
    )
    assert recorded["status"] == "IN_PROGRESS"
    passed = submit_inspection(api, inspection["id"], dealer_headers)
    assert passed["status"] == "PASSED"

    certification = submit_certification(
        api, dealer_headers, car["id"], inspection["id"]
    )
    approved = approve_certification(api, certification["id"])
    assert approved["status"] == "ACTIVE"
    assert approved["warranty_anchor_variant"] == "CERTIFICATION_ANCHORED"
    assert approved["warranty_start_date"] == "2026-08-01"
    assert approved["warranty_end_date"] == "2027-08-01"
    assert approved["warranty_end_miles"] == 92000
    # Four whole mileage blocks raise a 36000-cent surcharge, which the cap
    # trims to 31465 before the subtotal is formed.
    assert approved["fee_surcharge_cents"] == 31465
    assert approved["fee_discount_cents"] == 0
    assert approved["fee_charged_cents"] == 121365

    claim = file_claim(
        api,
        dealer_headers,
        certification["id"],
        component_category="POWERTRAIN",
        repair_date="2026-08-01",
        repair_odometer_miles=92000,
        claimed_amount_cents=CLAIM_PER_CLAIM_CAP_CENTS,
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["repair_odometer_miles"] == approved["warranty_end_miles"]
    assert claim["claimed_amount_cents"] == CLAIM_PER_CLAIM_CAP_CENTS
