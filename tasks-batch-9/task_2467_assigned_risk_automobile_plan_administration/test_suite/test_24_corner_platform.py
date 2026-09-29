"""Platform corners: envelopes, role bindings, version pins and immediate propagation."""
from test_helpers import (
    ATLAS,
    BEACON,
    EXAMINER_ONE_USER_ID,
    EXAMINER_TWO_USER_ID,
    NON_EXISTENT_UUID,
    PLAN_ADMINISTRATOR_USER_ID,
    T02_ADULT_CLEAN,
    ApiErrorId,
    accept_assignment,
    api_client,
    assert_applicant,
    assert_carrier,
    assert_deposit_ledger_conserved,
    assert_pagination_meta,
    assert_policy,
    assert_premium_lines_sum_to_final_premium,
    assert_quota_reconciliation,
    assert_total_annual_charge,
    assert_vehicle,
    assignment_for_application,
    assignments_for_application,
    bootstrap_plan,
    bring_application_to_certified,
    create_applicant_with_vehicle,
    create_cancellation_payload,
    create_complaint_payload,
    create_exit_notice_payload,
    create_licensing_amendment_payload,
    create_non_renewal_payload,
    create_policy_payload,
    create_quota_reconciliation_payload,
    create_reclassification_payload,
    create_resolution_payload,
    docket_complaint,
    enrol_carrier,
    is_valid_uuid,
    issue_policy,
    make_compliance_examiner_headers,
    make_headers,
    make_plan_administrator_headers,
    make_producer_agent_headers,
    make_servicing_carrier_headers,
    read_applicant,
    read_application,
    read_assignment,
    read_carrier,
    read_complaint,
    read_plan_period,
    read_policy,
    record_findings,
    register_producer,
    resolve_complaint,
    run_cycle,
    schedule_cycle,
    set_clock,
    setup_policy_in_force,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = make_plan_administrator_headers()
EXAMINER_ONE_HEADERS = make_compliance_examiner_headers(EXAMINER_ONE_USER_ID)

ATLAS_TWO_TERRITORIES = dict(ATLAS, licensed_territories=["T02", "T03"])
ATLAS_T01_T02 = dict(ATLAS, licensed_territories=["T01", "T02"])
ATLAS_DOMINANT = dict(ATLAS, voluntary_market_share_bps=9000)
BEACON_MINOR = dict(BEACON, voluntary_market_share_bps=1000)


# ==========================================================================
# endpoints / every_write_is_readable_and_no_row_is_editable_in_place
# ==========================================================================
def _one_carrier_one_producer_and_one_risk_description():
    """Enrol Atlas in two territories and describe one risk. No period, no application."""
    set_clock("2026-09-01T00:00:00Z")
    carrier = enrol_carrier(**ATLAS_TWO_TERRITORIES)
    producer = register_producer()
    applicant, vehicle = create_applicant_with_vehicle()
    return {"carrier": carrier, "producer": producer,
            "applicant": applicant, "vehicle": vehicle}


def test_the_carrier_read_returns_the_filed_set_plus_every_field_the_caller_never_sent():
    """One POST, then a read by a different role returns the whole stored row.

    The enrolment body carried four fields. The read — taken by the examiner rather
    than by the administrator that wrote it — has to answer with those four intact,
    including the licensed territories in the order they were filed, plus the whole
    server-owned half of the row: the enrolment ordinal, the standing fields and
    every quota counter, none of which the caller could have supplied.

    PRD: "A newly enrolled carrier starts with `status` `ACTIVE`, `performance_score`
    100 and `posture` `OPEN`, receives the next `enrollment_sequence`, and — because
    the apportionment denominator has just grown — triggers recomputation of
    `quota_target_units` for every `ACTIVE` carrier."
    Design: Corner/endpoints/every_write_is_readable_and_no_row_is_editable_in_place
    """
    world = _one_carrier_one_producer_and_one_risk_description()

    carrier = validate_success(
        api_client.get_carrier(world["carrier"]["id"], EXAMINER_ONE_HEADERS))

    assert_carrier(carrier)
    assert carrier["id"] == world["carrier"]["id"]
    assert carrier["name"] == "Atlas Mutual"
    assert carrier["naic_code"] == "11111"
    assert carrier["voluntary_market_share_bps"] == 6000
    assert carrier["licensed_territories"] == ["T02", "T03"]
    assert carrier["enrollment_sequence"] == 1
    assert carrier["status"] == "ACTIVE"
    assert carrier["posture"] == "OPEN"
    assert carrier["performance_score"] == 100
    assert carrier["version"] == 1
    assert carrier["assigned_risk_count"] == 0
    assert carrier["quota_target_units"] == 0
    assert carrier["voluntary_credit_units"] == 0
    assert carrier["penalty_balance_cents"] == 0
    assert carrier["upheld_complaint_count"] == 0


def test_both_list_reads_answer_with_an_array_envelope_and_the_full_pagination_meta():
    """The plan list and the nested vehicle list report the same four meta fields.

    Each list holds exactly one row, so `total_count` is 1 and `has_more` is false at
    the default page size. The nested list is addressed under its parent applicant and
    returns that applicant's vehicle with the class, territory and model year as filed.

    PRD: "Every list response reports `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object, where `total_count` is the number of rows matching the
    filters before pagination is applied and `has_more` indicates whether rows remain
    beyond the current page."
    Design: Corner/endpoints/every_write_is_readable_and_no_row_is_editable_in_place
    """
    world = _one_carrier_one_producer_and_one_risk_description()

    carrier_response = api_client.list_carriers(
        make_producer_agent_headers(world["producer"]["id"]),
        params={"limit": 10, "offset": 0})
    vehicle_response = api_client.list_vehicles(
        world["applicant"]["id"], EXAMINER_ONE_HEADERS)

    carriers, carrier_meta = validate_paginated(carrier_response)
    assert carrier_response.json()["response_type"] == "array"
    assert_pagination_meta(carrier_meta, expected_total=1, expected_limit=10,
                           expected_offset=0)
    assert carrier_meta["has_more"] is False
    assert [row["id"] for row in carriers] == [world["carrier"]["id"]]

    vehicles, vehicle_meta = validate_paginated(vehicle_response)
    assert_pagination_meta(vehicle_meta, expected_total=1)
    assert vehicle_meta["has_more"] is False
    assert len(vehicles) == 1
    assert_vehicle(vehicles[0])
    assert vehicles[0]["applicant_id"] == world["applicant"]["id"]
    assert vehicles[0]["vin"] == "1HGCM82633A004360"
    assert vehicles[0]["vehicle_class_code"] == "PLEASURE"
    assert vehicles[0]["garaging_territory_code"] == "T02"
    assert vehicles[0]["model_year"] == 2019
    assert is_valid_uuid(vehicles[0]["id"])
    assert vehicles[0]["id"] != world["applicant"]["id"]


def test_the_applicant_read_carries_the_intake_state_derived_at_creation():
    """Creation seeds three fields the caller never sent, and the read shows them.

    The applicant posted a name, a licence number, a territory, a class and a first
    licensed date. The read adds the rehabilitation clock: the chargeable-event date
    seeded from the first licensed date, the clean years measured against the plan
    clock and capped at five, and voluntary-market eligibility still false because no
    policy of this applicant has left the plan.

    PRD: "At creation, the applicant's `last_chargeable_event_date` is initialised to
    `first_licensed_date` and `clean_years_credited` is computed against the clock;
    `voluntary_market_eligible` starts false and turns true only when a policy of this
    applicant leaves the plan for the voluntary market."
    Design: Corner/endpoints/every_write_is_readable_and_no_row_is_editable_in_place
    """
    world = _one_carrier_one_producer_and_one_risk_description()

    applicant = validate_success(api_client.get_applicant(
        world["applicant"]["id"],
        make_servicing_carrier_headers(world["carrier"]["id"])))

    assert_applicant(applicant)
    assert applicant["full_name"] == "Owen Pike"
    assert applicant["driver_license_number"] == "D-99011"
    assert applicant["territory_code"] == "T02"
    assert applicant["driver_class"] == "ADULT"
    assert applicant["last_chargeable_event_date"] == applicant["first_licensed_date"]
    assert applicant["clean_years_credited"] == 5
    assert applicant["voluntary_market_eligible"] is False
    assert applicant["version"] == 1


# ==========================================================================
# endpoints / a_licensing_amendment_replaces_the_filed_set_wholesale
# ==========================================================================
def test_the_licensing_amendment_replaces_the_filed_territories_instead_of_merging_them():
    """Filing T03 over T01 and T02 leaves the carrier writable in T03 alone.

    The amendment is a wholesale replacement, so neither of the two territories the
    carrier was enrolled with survives it. The row is mutated, so its version moves by
    exactly one, but nothing else in the plan does: the carrier keeps posture OPEN and
    a quota target of zero, and the second carrier's own filed set and version are
    untouched by another carrier's filing.

    PRD: "It replaces the carrier's `licensed_territories` wholesale with the supplied
    set, and is admissible only while the carrier's `status` is `ACTIVE`; a withdrawing
    carrier is refused with `ERR_CARRIER_NOT_ACTIVE`."
    Design: Corner/endpoints/a_licensing_amendment_replaces_the_filed_set_wholesale
    """
    env = bootstrap_plan(carriers=[ATLAS_T01_T02, BEACON])
    atlas, beacon = env["carriers"]
    atlas_before = read_carrier(atlas["id"])
    beacon_before = read_carrier(beacon["id"])
    assert atlas_before["licensed_territories"] == ["T01", "T02"]

    amended = validate_success(api_client.file_carrier_licensing_amendment(
        atlas["id"], create_licensing_amendment_payload(["T03"]), ADMIN_HEADERS))

    assert amended["licensed_territories"] == ["T03"]
    assert amended["version"] == atlas_before["version"] + 1
    assert amended["posture"] == "OPEN"
    assert amended["quota_target_units"] == 0
    assert read_carrier(atlas["id"])["licensed_territories"] == ["T03"]
    beacon_after = read_carrier(beacon["id"])
    assert beacon_after["licensed_territories"] == ["T02"]
    assert beacon_after["version"] == beacon_before["version"]
    assert beacon_after["quota_target_units"] == 0


def test_a_withdrawing_carrier_may_not_amend_its_licensed_territories_at_all():
    """The filing is admissible only while the carrier is ACTIVE.

    Once notice of withdrawal is on file the carrier is EXIT_NOTICED, and the narrow
    territory filing is refused outright rather than recorded against a carrier on its
    way out. The refused call leaves the enrolled set exactly as it was.

    PRD: "It replaces the carrier's `licensed_territories` wholesale with the supplied
    set, and is admissible only while the carrier's `status` is `ACTIVE`; a withdrawing
    carrier is refused with `ERR_CARRIER_NOT_ACTIVE`."
    Design: Corner/endpoints/a_licensing_amendment_replaces_the_filed_set_wholesale
    """
    env = bootstrap_plan(carriers=[ATLAS_T01_T02, BEACON])
    beacon = env["carriers"][1]
    withdrawing = validate_success(api_client.file_carrier_exit_notice(
        beacon["id"], create_exit_notice_payload("2026-12-14T00:00:00Z"), ADMIN_HEADERS))
    assert withdrawing["status"] == "EXIT_NOTICED"

    response = api_client.file_carrier_licensing_amendment(
        beacon["id"], create_licensing_amendment_payload(["T01"]), ADMIN_HEADERS)

    validate_error(response, ApiErrorId.ERR_CARRIER_NOT_ACTIVE, 409)
    refused = read_carrier(beacon["id"])
    assert refused["licensed_territories"] == ["T02"]
    assert refused["status"] == "EXIT_NOTICED"


def test_the_amendment_leaves_the_book_the_carrier_already_services_exactly_where_it_is():
    """A carrier can end up servicing a risk garaged in a territory it may no longer write.

    Atlas is servicing a T02 policy when its filing is narrowed to T01 alone. The plan
    deliberately does not reassign that book: the policy keeps its carrier and stays in
    force, the assignment stays where it is, and the carrier keeps the headcount. Only a
    future candidate pool would notice the amendment.

    PRD: "Deliberately, the plan does *not* reassign the book: existing assignment and
    policy rows are left exactly where they are, so a carrier can end up servicing a risk
    garaged in a territory it may no longer write, and only *future* candidate filtering
    reflects the amendment."
    Design: Corner/endpoints/a_licensing_amendment_replaces_the_filed_set_wholesale
    """
    env = setup_policy_in_force(policy_number="AR-100014")
    atlas = env["carrier"]
    assert env["vehicle"]["garaging_territory_code"] == "T02"

    amended = validate_success(api_client.file_carrier_licensing_amendment(
        atlas["id"], create_licensing_amendment_payload(["T01"]), ADMIN_HEADERS))

    assert amended["licensed_territories"] == ["T01"]
    policy = read_policy(env["policy"]["id"])
    assert policy["carrier_id"] == atlas["id"]
    assert policy["policy_status"] == "IN_FORCE"
    assignment = read_assignment(env["assignment"]["id"])
    assert assignment["carrier_id"] == atlas["id"]
    assert assignment["status"] == "POLICY_ISSUED"
    assert read_carrier(atlas["id"])["assigned_risk_count"] == 1


# ==========================================================================
# endpoints / one_run_places_what_it_can_and_defers_the_rest_without_failing
# ==========================================================================
def _two_certified_risks_one_of_them_unwritable():
    """Two certified risks, one in T02 that both carriers may write and one in T03 that
    neither may. The cycle is scheduled but not yet run."""
    env = bootstrap_plan(carriers=[ATLAS, BEACON])
    inside = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Owen Pike", "driver_license_number": "D-99011",
                             "territory_code": "T02"},
        vehicle_overrides={"vin": "1HGCM82633A004360"},
        document_prefix="DEC-40")
    outside = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Nadia Frost", "driver_license_number": "D-99012",
                             "territory_code": "T03"},
        vehicle_overrides={"vin": "1HGCM82633A004361"},
        document_prefix="DEC-41")
    period = read_plan_period(env["plan_period"]["id"])
    assert period["total_assignable_units"] == 2
    assert read_carrier(env["carriers"][0]["id"])["quota_target_units"] == 1
    assert read_carrier(env["carriers"][1]["id"])["quota_target_units"] == 1
    env["cycle"] = schedule_cycle(env["plan_period"]["id"])
    env["inside"] = inside["application"]
    env["outside"] = outside["application"]
    return env


def test_the_run_defers_the_unwritable_risk_without_failing_the_call():
    """An empty candidate pool is recorded as a fact, not raised as an error.

    No enrolled carrier is licensed in T03, so the second queued risk has nowhere to go.
    The run still answers 200 and still completes: the cycle's two counters split one and
    one, the deferred application lands in DEFERRED_NO_CARRIER and no assignment row is
    written for it at all.

    PRD: "If the candidate pool is empty, the application moves to
    `DEFERRED_NO_CARRIER`, the cycle's `deferred_count` rises by 1, no assignment row is
    created, no error is raised, and the run proceeds to the next application — an empty
    market is a fact to be recorded, not a request failure."
    Design: Corner/endpoints/one_run_places_what_it_can_and_defers_the_rest_without_failing
    """
    env = _two_certified_risks_one_of_them_unwritable()

    completed = validate_success(
        api_client.run_assignment_cycle(env["cycle"]["id"], ADMIN_HEADERS))

    assert completed["status"] == "COMPLETED"
    assert completed["assigned_count"] == 1
    assert completed["deferred_count"] == 1
    assert read_application(env["outside"]["id"])["status"] == "DEFERRED_NO_CARRIER"
    assert assignments_for_application(env["outside"]["id"]) == []


def test_the_placement_half_of_the_same_run_is_fully_committed():
    """Half the batch found no home, and the other half is still written in full.

    The T02 risk is placed on the tie-break: both carriers show a deficit of one unit,
    so the larger market share wins it. The assignment records that deficit and the
    first creation position of the run, its application advances to ASSIGNED, and both
    carriers' quota pictures are re-derived — the winner to a variance of zero, the
    carrier that was never ranked first to minus one.

    PRD: "Each placement writes an assignment row and advances its application
    `CERTIFIED_AWAITING_ASSIGNMENT → ASSIGNED`, while the cycle's `assigned_count`
    rises by 1."
    Design: Corner/endpoints/one_run_places_what_it_can_and_defers_the_rest_without_failing
    """
    env = _two_certified_risks_one_of_them_unwritable()
    atlas, beacon = env["carriers"]

    run_cycle(env["cycle"]["id"])

    rows, meta = validate_paginated(api_client.list_assignments(
        ADMIN_HEADERS, params={"assignment_cycle_id": env["cycle"]["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["application_id"] == env["inside"]["id"]
    assert rows[0]["carrier_id"] == atlas["id"]
    assert rows[0]["assignment_kind"] == "INITIAL"
    assert rows[0]["batch_sequence"] == 1
    assert rows[0]["deficit_score_at_selection"] == 1
    assert rows[0]["status"] == "PENDING_ACCEPTANCE"
    assert read_application(env["inside"]["id"])["status"] == "ASSIGNED"
    winner = read_carrier(atlas["id"])
    assert winner["assigned_risk_count"] == 1
    assert winner["quota_variance_units"] == 0
    assert winner["overallocated"] is False
    assert winner["posture"] == "OPEN"
    loser = read_carrier(beacon["id"])
    assert loser["assigned_risk_count"] == 0
    assert loser["quota_variance_units"] == -1.0
    assert loser["posture"] == "OPEN"


# ==========================================================================
# endpoints / a_complaint_links_two_existing_rows_and_refuses_a_dangling_one
# ==========================================================================
def _two_policies_serviced_by_different_carriers():
    """One T02 risk each: the first goes to Atlas on the tie-break, the second to Beacon."""
    env = bootstrap_plan(carriers=[ATLAS, BEACON])
    atlas, beacon = env["carriers"]
    first = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Owen Pike", "driver_license_number": "D-99011"},
        vehicle_overrides={"vin": "1HGCM82633A004360"},
        document_prefix="DEC-44")
    second = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Nadia Frost", "driver_license_number": "D-99012"},
        vehicle_overrides={"vin": "1HGCM82633A004361"},
        document_prefix="DEC-45")
    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    first_assignment = assignment_for_application(first["application"]["id"])
    second_assignment = assignment_for_application(second["application"]["id"])
    assert first_assignment["carrier_id"] == atlas["id"]
    assert second_assignment["carrier_id"] == beacon["id"]
    accept_assignment(first_assignment["id"], atlas["id"])
    accept_assignment(second_assignment["id"], beacon["id"])
    set_clock("2026-09-15T00:00:00Z")
    env["atlas_policy"] = issue_policy(first_assignment["id"], atlas["id"],
                                       policy_number="AR-100014")
    env["beacon_policy"] = issue_policy(second_assignment["id"], beacon["id"],
                                        policy_number="AR-100015")
    return env


def test_a_complaint_naming_a_row_that_does_not_exist_is_refused_on_the_missing_reference():
    """Both body references are resolved before anything is written.

    The docketing payload carries two foreign keys and neither is in the path. A policy
    identifier that resolves to nothing answers on the policy, a carrier identifier that
    resolves to nothing answers on the carrier, and in both cases the existence check
    outranks the cross-row agreement rule that would otherwise have complained about the
    pairing. No complaint row is created either way.

    PRD: "The first identifier that fails to resolve determines the error: an
    unresolvable carrier yields `ERR_CARRIER_NOT_FOUND`, a producer
    `ERR_PRODUCER_NOT_FOUND`, an applicant `ERR_APPLICANT_NOT_FOUND`, a vehicle
    `ERR_VEHICLE_NOT_FOUND`, an application `ERR_APPLICATION_NOT_FOUND`, a plan period
    `ERR_PLAN_PERIOD_NOT_FOUND`, an assignment cycle `ERR_ASSIGNMENT_CYCLE_NOT_FOUND`,
    an assignment `ERR_ASSIGNMENT_NOT_FOUND`, a policy `ERR_POLICY_NOT_FOUND`, a claim
    `ERR_CLAIM_NOT_FOUND`, a complaint `ERR_COMPLAINT_NOT_FOUND` and a quota
    reconciliation `ERR_QUOTA_RECONCILIATION_NOT_FOUND`."
    Design: Corner/endpoints/a_complaint_links_two_existing_rows_and_refuses_a_dangling_one
    """
    env = _two_policies_serviced_by_different_carriers()
    atlas = env["carriers"][0]

    dangling_policy = api_client.create_complaint(
        create_complaint_payload(NON_EXISTENT_UUID, atlas["id"],
                                 complaint_type="RATING_DISPUTE",
                                 narrative="Dangling policy reference."),
        EXAMINER_ONE_HEADERS)
    dangling_carrier = api_client.create_complaint(
        create_complaint_payload(env["atlas_policy"]["id"], NON_EXISTENT_UUID,
                                 complaint_type="RATING_DISPUTE",
                                 narrative="Dangling carrier reference."),
        EXAMINER_ONE_HEADERS)

    validate_error(dangling_policy, ApiErrorId.ERR_POLICY_NOT_FOUND, 404)
    validate_error(dangling_carrier, ApiErrorId.ERR_CARRIER_NOT_FOUND, 404)
    _, meta = validate_paginated(api_client.list_complaints(ADMIN_HEADERS))
    assert meta["total_count"] == 0


def test_the_docketed_complaint_echoes_both_links_and_opens_its_findings_trail_empty():
    """The valid link is created with both foreign keys and an empty two-examiner trail.

    Docketing answers 201 because a new row comes into existence. The row echoes the
    policy it is about and the carrier it runs against, opens in OPEN at the first
    review round, and carries nothing at all on the findings-and-disposition trail that
    the two examiners will fill in later.

    PRD: "A docketed complaint begins in `OPEN` with `review_round` at 1, and its
    `findings_recorded_by_user_id`, `findings_note`, `resolved_by_user_id` and
    `disposition` all begin null."
    Design: Corner/endpoints/a_complaint_links_two_existing_rows_and_refuses_a_dangling_one
    """
    env = _two_policies_serviced_by_different_carriers()
    atlas = env["carriers"][0]

    complaint = validate_success(api_client.create_complaint(
        create_complaint_payload(env["atlas_policy"]["id"], atlas["id"],
                                 complaint_type="RATING_DISPUTE",
                                 narrative="Surcharge points disputed."),
        ADMIN_HEADERS), 201)

    assert is_valid_uuid(complaint["id"])
    assert complaint["policy_id"] == env["atlas_policy"]["id"]
    assert complaint["carrier_id"] == atlas["id"]
    assert complaint["complaint_type"] == "RATING_DISPUTE"
    assert complaint["narrative"] == "Surcharge points disputed."
    assert complaint["status"] == "OPEN"
    assert complaint["review_round"] == 1
    assert complaint["findings_recorded_by_user_id"] is None
    assert complaint["findings_note"] is None
    assert complaint["resolved_by_user_id"] is None
    assert complaint["disposition"] is None
    assert complaint["version"] == 1


def test_the_link_is_visible_from_the_policy_end_and_only_from_the_policy_complained_about():
    """The freeze appears on the complained-about policy and nowhere else.

    The complaint raises that policy's open counter to one and turns its freeze on, which
    is the protection the insured gets for free. The other carrier's policy, which nobody
    complained about, keeps a zero counter and no freeze, and the carrier's lifetime
    upheld count has not moved because nothing has been resolved yet.

    PRD: "The policy's `open_complaint_count` — the number of that policy's complaints
    whose `status` is `OPEN` or `FINDINGS_RECORDED` — rises by 1, and
    `complaint_freeze_active`, which is true exactly when `open_complaint_count` is
    greater than zero, becomes true."
    Design: Corner/endpoints/a_complaint_links_two_existing_rows_and_refuses_a_dangling_one
    """
    env = _two_policies_serviced_by_different_carriers()
    atlas = env["carriers"][0]
    assert read_policy(env["atlas_policy"]["id"])["open_complaint_count"] == 0

    docket_complaint(env["atlas_policy"]["id"], atlas["id"],
                     complaint_type="RATING_DISPUTE",
                     narrative="Surcharge points disputed.")

    complained_about = read_policy(env["atlas_policy"]["id"])
    assert complained_about["open_complaint_count"] == 1
    assert complained_about["complaint_freeze_active"] is True
    untouched = read_policy(env["beacon_policy"]["id"])
    assert untouched["open_complaint_count"] == 0
    assert untouched["complaint_freeze_active"] is False
    _, meta = validate_paginated(api_client.list_complaints(
        make_servicing_carrier_headers(atlas["id"]),
        params={"policy_id": env["atlas_policy"]["id"]}))
    assert meta["total_count"] == 1
    assert read_carrier(atlas["id"])["upheld_complaint_count"] == 0


# ==========================================================================
# endpoints / the_reconciliation_read_shows_the_derived_variance_and_penalty
# ==========================================================================
def _period_in_reconciliation_with_one_carrier_short():
    """The same two-risk period, closed for reconciliation: Atlas took the T02 risk and
    Beacon was never ranked first, so it holds a target of one and no volume at all."""
    env = _two_certified_risks_one_of_them_unwritable()
    run_cycle(env["cycle"]["id"])
    set_clock("2026-11-30T00:00:00Z")
    period = validate_success(
        api_client.close_plan_period(env["plan_period"]["id"], ADMIN_HEADERS))
    assert period["status"] == "RECONCILING"
    assert period["total_assignable_units"] == 2
    return env


def test_the_carrier_that_took_its_whole_target_reconciles_to_no_variance_and_no_penalty():
    """On the headcount basis Atlas owes one unit and is credited with one.

    Its obligation is simply the apportioned target and its credit is the live headcount
    plus voluntary credit it never earned, so the two cancel: the variance is zero, the
    row is FINAL, and nothing lands on the carrier's penalty balance. Every one of those
    numbers is derived — the filing itself supplied only a carrier, a period, a basis and
    a version token.

    PRD: "On the `POLICY_COUNT` basis — the plan's headcount measure — `obligation_units`
    is simply the carrier's `quota_target_units`, a whole number, and `credited_units` is
    the carrier's live `assigned_risk_count` plus its `voluntary_credit_units`, carried to
    1 decimal place because voluntary credit is granted in halves."
    Design: Corner/endpoints/the_reconciliation_read_shows_the_derived_variance_and_penalty
    """
    env = _period_in_reconciliation_with_one_carrier_short()
    atlas = read_carrier(env["carriers"][0]["id"])
    assert atlas["quota_target_units"] == 1
    assert atlas["assigned_risk_count"] == 1

    filing = validate_success(api_client.create_quota_reconciliation(
        create_quota_reconciliation_payload(atlas["id"], env["plan_period"]["id"],
                                            "POLICY_COUNT", atlas["version"]),
        ADMIN_HEADERS), 201)

    assert_quota_reconciliation(filing)
    assert filing["carrier_id"] == atlas["id"]
    assert filing["plan_period_id"] == env["plan_period"]["id"]
    assert filing["obligation_units"] == 1
    assert filing["credited_units"] == 1
    assert filing["voluntary_credit_units_applied"] == 0
    assert filing["variance_units"] == 0
    assert filing["penalty_cents"] == 0
    assert filing["status"] == "FINAL"
    assert read_carrier(atlas["id"])["penalty_balance_cents"] == 0


def test_the_carrier_that_was_never_ranked_first_reconciles_to_a_deficiency_charge():
    """Beacon owed one unit, took none, and is billed 25000 cents for the shortfall.

    It was licensed for the same territory as the winner and simply lost the tie-break,
    which the reconciliation does not care about: the variance is minus one unit and the
    penalty is one deficient unit at 25000 cents. The charge shows up on the carrier's
    penalty balance, and filtering the list by carrier narrows it to that one row without
    changing any of the figures.

    PRD: "`penalty_cents` is then the shortfall — that is, the negation of
    `variance_units` when the variance is negative, and 0 when it is zero or positive —
    multiplied by 25000 cents per deficient unit and rounded half up to whole cents."
    Design: Corner/endpoints/the_reconciliation_read_shows_the_derived_variance_and_penalty
    """
    env = _period_in_reconciliation_with_one_carrier_short()
    atlas, beacon = (read_carrier(c["id"]) for c in env["carriers"])
    assert beacon["quota_target_units"] == 1
    assert beacon["assigned_risk_count"] == 0

    filing = validate_success(api_client.create_quota_reconciliation(
        create_quota_reconciliation_payload(beacon["id"], env["plan_period"]["id"],
                                            "POLICY_COUNT", beacon["version"]),
        ADMIN_HEADERS), 201)

    assert filing["obligation_units"] == 1
    assert filing["credited_units"] == 0
    assert filing["variance_units"] == -1.0
    assert filing["penalty_cents"] == 25000
    assert filing["status"] == "FINAL"
    assert read_carrier(beacon["id"])["penalty_balance_cents"] == 25000
    assert read_carrier(atlas["id"])["penalty_balance_cents"] == 0
    rows, meta = validate_paginated(api_client.list_quota_reconciliations(
        EXAMINER_ONE_HEADERS, params={"carrier_id": beacon["id"]}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [filing["id"]]
    assert rows[0]["penalty_cents"] == 25000


def test_the_single_row_read_repeats_the_derived_figures_and_the_last_filing_closes_the_period():
    """Reading the row back changes nothing, and the second filing bubbles the period shut.

    The read is taken by a carrier rather than by the administrator that filed, and it
    answers with the identical derived figures — none of which the filer supplied. Once
    both of the plan's ACTIVE carriers hold a FINAL row for the period, the period reaches
    CLOSED without anyone calling anything on it.

    PRD: "Third, when every carrier whose `status` is `ACTIVE` now holds a `FINAL`
    reconciliation for the period, the period bubbles up `RECONCILING → CLOSED`, which is
    terminal, and no further reconciliation row may be created for that period."
    Design: Corner/endpoints/the_reconciliation_read_shows_the_derived_variance_and_penalty
    """
    env = _period_in_reconciliation_with_one_carrier_short()
    atlas, beacon = (read_carrier(c["id"]) for c in env["carriers"])

    first = validate_success(api_client.create_quota_reconciliation(
        create_quota_reconciliation_payload(atlas["id"], env["plan_period"]["id"],
                                            "POLICY_COUNT", atlas["version"]),
        ADMIN_HEADERS), 201)
    assert read_plan_period(env["plan_period"]["id"])["status"] == "RECONCILING"
    second = validate_success(api_client.create_quota_reconciliation(
        create_quota_reconciliation_payload(beacon["id"], env["plan_period"]["id"],
                                            "POLICY_COUNT",
                                            read_carrier(beacon["id"])["version"]),
        ADMIN_HEADERS), 201)

    reread = validate_success(api_client.get_quota_reconciliation(
        first["id"], make_servicing_carrier_headers(atlas["id"])))
    for field in ("obligation_units", "credited_units", "variance_units",
                  "penalty_cents", "voluntary_credit_units_applied", "status"):
        assert reread[field] == first[field], field
    assert second["penalty_cents"] == 25000
    assert read_plan_period(env["plan_period"]["id"])["status"] == "CLOSED"


# ==========================================================================
# errors / the_fourth_non_renewal_of_a_period_is_refused_and_the_cap_resets_at_closure
# ==========================================================================
def _atlas_with_four_policies_and_three_notices_served():
    """Atlas takes all four risks of the period and serves notice on the first three."""
    env = bootstrap_plan(carriers=[ATLAS_DOMINANT, BEACON_MINOR])
    atlas = env["carriers"][0]
    risks = [
        bring_application_to_certified(
            env,
            applicant_overrides={"full_name": f"Insured Number {n}",
                                 "driver_license_number": f"D-9902{n}"},
            vehicle_overrides={"vin": f"1HGCM82633A00437{n}"},
            document_prefix=f"DEC-6{n}")
        for n in range(4)
    ]
    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    assignments = [assignment_for_application(r["application"]["id"]) for r in risks]
    for assignment in assignments:
        assert assignment["carrier_id"] == atlas["id"]
        accept_assignment(assignment["id"], atlas["id"])
    set_clock("2026-09-15T00:00:00Z")
    policies = [issue_policy(assignment["id"], atlas["id"],
                             policy_number=f"AR-10001{n}")
                for n, assignment in enumerate(assignments)]
    carrier_headers = make_servicing_carrier_headers(atlas["id"])
    for policy in policies[:3]:
        served = validate_success(api_client.serve_non_renewal_notice(
            policy["id"], create_non_renewal_payload(), carrier_headers))
        assert served["policy_status"] == "NON_RENEWAL_PENDING"
    standing = read_carrier(atlas["id"])
    assert standing["non_renewal_count_current_period"] == 3
    assert standing["assigned_risk_count"] == 4
    env["atlas"] = atlas
    env["policies"] = policies
    env["carrier_headers"] = carrier_headers
    return env


def test_the_fourth_non_renewal_notice_of_the_period_is_refused_and_writes_nothing():
    """Three notices stand and the fourth is capped.

    The fourth policy is in force, unfrozen, has never been noticed and is well inside
    the notice deadline, so the only rule it fails is the per-carrier per-period cap. The
    refusal leaves the policy in force with a notice count of zero and leaves the
    carrier's running count where it was.

    PRD: "And the carrier's `non_renewal_count_current_period` must be below 3, since the
    plan caps each carrier at three non-renewals per period; a fourth is refused with
    `ERR_NON_RENEWAL_QUOTA_EXCEEDED` and HTTP 409."
    Design: Corner/errors/the_fourth_non_renewal_of_a_period_is_refused_and_the_cap_resets_at_closure
    """
    env = _atlas_with_four_policies_and_three_notices_served()
    fourth = env["policies"][3]

    response = api_client.serve_non_renewal_notice(
        fourth["id"], create_non_renewal_payload("One too many."), env["carrier_headers"])

    validate_error(response, ApiErrorId.ERR_NON_RENEWAL_QUOTA_EXCEEDED, 409)
    refused = read_policy(fourth["id"])
    assert refused["policy_status"] == "IN_FORCE"
    assert refused["non_renewal_notice_count"] == 0
    assert read_carrier(env["atlas"]["id"])["non_renewal_count_current_period"] == 3


def test_the_period_closure_zeroes_the_cap_and_the_very_same_notice_then_succeeds():
    """The cap is a running per-period count, so turning the page releases it.

    Closing the intake side of the period resets the carrier's per-period counters and
    credits the closure recovery, capped at 100. The notice the cap held at three now
    goes through, taking the count back up to one, while the three notices already
    served are untouched — the closure reset the counter, not the notices — and the
    carrier still counts all four risks because none has expired.

    PRD: "It also turns the page for every carrier whose `status` is `ACTIVE`:
    `breach_count_current_period` is reset to 0, `non_renewal_count_current_period` is
    reset to 0, `performance_score` is raised by 10 but never above 100, and `posture` is
    recomputed — which is how a carrier restricted by breaches or by a mediocre score can
    earn its way back to `OPEN`."
    Design: Corner/errors/the_fourth_non_renewal_of_a_period_is_refused_and_the_cap_resets_at_closure
    """
    env = _atlas_with_four_policies_and_three_notices_served()
    fourth = env["policies"][3]
    assert read_policy(fourth["id"])["non_renewal_notice_count"] == 0

    set_clock("2026-11-30T00:00:00Z")
    period = validate_success(
        api_client.close_plan_period(env["plan_period"]["id"], ADMIN_HEADERS))
    turned_page = read_carrier(env["atlas"]["id"])
    assert period["status"] == "RECONCILING"
    assert turned_page["non_renewal_count_current_period"] == 0
    assert turned_page["breach_count_current_period"] == 0
    assert turned_page["performance_score"] == 100

    served = validate_success(api_client.serve_non_renewal_notice(
        fourth["id"], create_non_renewal_payload("One too many."), env["carrier_headers"]))

    assert served["policy_status"] == "NON_RENEWAL_PENDING"
    assert served["non_renewal_notice_count"] == 1
    assert served["non_renewal_effective_date"] == served["expiration_date"]
    after = read_carrier(env["atlas"]["id"])
    assert after["non_renewal_count_current_period"] == 1
    assert after["assigned_risk_count"] == 4
    for earlier in env["policies"][:3]:
        assert read_policy(earlier["id"])["policy_status"] == "NON_RENEWAL_PENDING"


# ==========================================================================
# errors / a_request_with_no_recognised_role_header_is_unauthenticated_before_anything_else
# ==========================================================================
def _one_enrolled_carrier():
    set_clock("2026-09-01T00:00:00Z")
    return enrol_carrier()


def test_a_request_missing_either_authentication_header_is_refused_before_anything_else():
    """Either header absent is authentication, and the target is beside the point.

    The path names a carrier that really exists and the role that is present is a real
    one, but a request without both headers has no principal to act as. Both halves are
    refused the same way, and the same read with both headers present proves the target
    and the path were valid throughout.

    PRD: "If either header is absent, or if `X-User-Role` is not exactly one of the four
    role names the plan recognises, the request is rejected with `ERR_UNAUTHENTICATED`
    and HTTP 401."
    Design: Corner/errors/a_request_with_no_recognised_role_header_is_unauthenticated_before_anything_else
    """
    carrier = _one_enrolled_carrier()

    no_role = api_client.get_carrier(
        carrier["id"], {"X-User-ID": PLAN_ADMINISTRATOR_USER_ID,
                        "Content-Type": "application/json"})
    no_principal = api_client.get_carrier(
        carrier["id"], {"X-User-Role": "PlanAdministrator",
                        "Content-Type": "application/json"})
    neither = api_client.get_carrier(carrier["id"], {"Content-Type": "application/json"})

    for response in (no_role, no_principal, neither):
        error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        assert error["message"].strip()
        assert response.json()["meta"]["api_request_id"].startswith("req_")
    assert validate_success(
        api_client.get_carrier(carrier["id"], EXAMINER_ONE_HEADERS))["id"] == carrier["id"]


def test_a_misspelt_role_is_unauthenticated_ahead_of_authorisation_and_of_existence():
    """A role string outside the four names never reaches the later checks.

    "PlanAdmin" is not one of the four names, so there is no role to compare against the
    endpoint's list: the well-formed enrolment is answered 401 rather than 403, and no
    carrier row comes into existence. The same misspelling on a read of an identifier
    that resolves to nothing is answered 401 rather than 404, because authentication sits
    above existence.

    PRD: "1. **Authentication** — headers present and the role recognised:
    `ERR_UNAUTHENTICATED`, 401."
    Design: Corner/errors/a_request_with_no_recognised_role_header_is_unauthenticated_before_anything_else
    """
    _one_enrolled_carrier()
    misspelt = make_headers(PLAN_ADMINISTRATOR_USER_ID, "PlanAdmin")

    enrolment = api_client.create_carrier(
        {"name": "Ghost Indemnity", "naic_code": "33333",
         "voluntary_market_share_bps": 500, "licensed_territories": ["T02"]}, misspelt)
    unknown_row = api_client.get_application(NON_EXISTENT_UUID, misspelt)

    validate_error(enrolment, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    validate_error(unknown_row, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    _, meta = validate_paginated(api_client.list_carriers(ADMIN_HEADERS))
    assert meta["total_count"] == 1
    assert api_client.get_application(
        NON_EXISTENT_UUID, ADMIN_HEADERS).status_code != 401


# ==========================================================================
# rbac / each_of_the_four_roles_carries_its_own_half_of_the_workflow
# ==========================================================================
def _policy_written_by_all_four_roles():
    """The full chain: administrator enrols and runs, producer files and pays, examiner
    verifies and certifies, carrier accepts and issues. Then the clock moves on."""
    env = setup_policy_in_force(policy_number="AR-100014")
    assert env["policy"]["total_annual_charge_cents"] == 155754
    assert env["policy"]["premium_credited_cents"] == 38939
    set_clock("2026-12-15T00:00:00Z")
    return env


def test_all_four_roles_read_the_shared_policy_and_see_exactly_the_same_row():
    """No single role could have written this policy, and all four may read it.

    The chain only got here because each of the four bindings worked in its own half of
    the workflow. The read is shared by all four, and it is not role-filtered: the
    administrator, the examiner, the servicing carrier bound to this very carrier and the
    producer of record all receive byte-identical payloads.

    PRD: "| GET | `/plan/policies/{id}` | Read one policy including both state axes and
    the premium ledger. | PlanAdministrator, ComplianceExaminer, ServicingCarrier,
    ProducerAgent |"
    Design: Corner/rbac/each_of_the_four_roles_carries_its_own_half_of_the_workflow
    """
    env = _policy_written_by_all_four_roles()
    policy_id = env["policy"]["id"]

    views = [
        validate_success(api_client.get_policy(policy_id, ADMIN_HEADERS)),
        validate_success(api_client.get_policy(policy_id, EXAMINER_ONE_HEADERS)),
        validate_success(api_client.get_policy(
            policy_id, make_servicing_carrier_headers(env["carrier"]["id"]))),
        validate_success(api_client.get_policy(
            policy_id, make_producer_agent_headers(env["producer"]["id"]))),
    ]

    assert_policy(views[0])
    assert views[0]["carrier_id"] == env["carrier"]["id"]
    assert views[0]["policy_status"] == "IN_FORCE"
    for other in views[1:]:
        assert other == views[0]


def test_the_producers_cancellation_settles_the_insureds_own_request_on_the_short_rate_basis():
    """The caller's role is the initiating party, and that alone picks the basis.

    A producer cancels for the insured, so the party is INSURED and the settlement runs
    on the short-rate basis rather than pro rata. Ninety-one whole days of the term have
    run, and the penalty multiplier goes inside the rounding: the earned premium is 42715
    cents, which exceeds the credited deposit, so nothing is refunded and 3776 cents fall
    due at cancellation with the credited deposit left where it is.

    PRD: "Which basis applies is decided by the initiating party and recorded on the
    policy as `refund_basis`: a `cancellation_initiated_by` of `CARRIER` or `PLAN` gives
    `refund_basis` `PRO_RATA`, while `INSURED` gives `SHORT_RATE`."
    Design: Corner/rbac/each_of_the_four_roles_carries_its_own_half_of_the_workflow
    """
    env = _policy_written_by_all_four_roles()

    cancelled = validate_success(api_client.cancel_policy(
        env["policy"]["id"],
        create_cancellation_payload("INSURED_REQUEST", "2026-12-15T00:00:00Z"),
        make_producer_agent_headers(env["producer"]["id"])))

    assert cancelled["policy_status"] == "CANCELLED"
    assert cancelled["cancellation_initiated_by"] == "INSURED"
    assert cancelled["refund_basis"] == "SHORT_RATE"
    assert cancelled["earned_premium_cents"] == 42715
    assert cancelled["refund_paid_cents"] == 0
    assert cancelled["balance_due_cents"] == 3776
    assert cancelled["premium_credited_cents"] == 38939
    assert cancelled["premium_settlement_status"] == "BALANCE_DUE_AT_CANCELLATION"


def test_the_cancellation_closes_the_chain_the_other_three_roles_built():
    """One producer call unwinds the assignment, the application and the headcount.

    The coverage axis moves to CANCELLED and the rows behind it follow inside the same
    request: the assignment the administrator's cycle created closes, the application the
    producer submitted and the examiner certified closes as cancelled, and the carrier
    that accepted and issued gives up the headcount, leaving it one unit short of its
    target. Not a cent is created or lost on the way.

    PRD: "On the coverage axis the policy moves `IN_FORCE → CANCELLED`, its
    `cancellation_reason_code`, `cancellation_effective_date` and
    `cancellation_initiated_by` are recorded, its assignment moves to `CLOSED`, its
    application moves `POLICY_ISSUED → CLOSED_CANCELLED`, and the servicing carrier's
    `assigned_risk_count` falls by 1 with `quota_variance_units`, `overallocated` and
    `posture` recomputed."
    Design: Corner/rbac/each_of_the_four_roles_carries_its_own_half_of_the_workflow
    """
    env = _policy_written_by_all_four_roles()

    cancelled = validate_success(api_client.cancel_policy(
        env["policy"]["id"],
        create_cancellation_payload("INSURED_REQUEST", "2026-12-15T00:00:00Z"),
        make_producer_agent_headers(env["producer"]["id"])))

    assert cancelled["cancellation_reason_code"] == "INSURED_REQUEST"
    assert read_assignment(env["assignment"]["id"])["status"] == "CLOSED"
    application = read_application(env["application"]["id"])
    assert application["status"] == "CLOSED_CANCELLED"
    carrier = read_carrier(env["carrier"]["id"])
    assert carrier["assigned_risk_count"] == 0
    assert carrier["quota_variance_units"] == -1.0
    assert carrier["overallocated"] is False
    assert carrier["posture"] == "OPEN"
    assert_deposit_ledger_conserved(application, [read_policy(env["policy"]["id"])])


# ==========================================================================
# rbac / a_carrier_cannot_reach_another_carriers_rows_and_a_producer_cannot_reach_another_producers
# ==========================================================================
def _one_policy_and_a_second_producer_of_record_on_nothing():
    env = setup_policy_in_force(policy_number="AR-100014")
    env["outsider"] = register_producer(name="Seaside Agency", license_number="PL-5500",
                                        appointed_territories=["T01", "T02", "T03"])
    return env


def test_a_producer_cannot_pay_a_deposit_on_another_producers_application():
    """The scope rule is row-level: the producer of record on the row is the only one.

    The Seaside producer is active and appointed in the applicant's territory, so nothing
    about it is wrong in general — it simply is not the producer of record recorded on
    this application. The deposit is refused and the application's cumulative deposit
    stands exactly where the real producer of record left it.

    PRD: "ownership checks compare the producer of record recorded on the target
    `Application` (or, for a policy, on the application behind it) to `X-User-ID`, and a
    mismatch is refused with `ERR_PRODUCER_SCOPE_FORBIDDEN` and HTTP 403"
    Design: Corner/rbac/a_carrier_cannot_reach_another_carriers_rows_and_a_producer_cannot_reach_another_producers
    """
    env = _one_policy_and_a_second_producer_of_record_on_nothing()

    response = api_client.record_deposit(
        env["application"]["id"], {"amount_cents": 1000},
        make_producer_agent_headers(env["outsider"]["id"]))

    validate_error(response, ApiErrorId.ERR_PRODUCER_SCOPE_FORBIDDEN, 403)
    application = read_application(env["application"]["id"])
    assert application["deposit_paid_total_cents"] == 38939
    assert application["deposit_balance_cents"] == 0


def test_a_carrier_cannot_report_a_loss_on_another_carriers_policy():
    """A claim is scoped through the policy it would be reported under.

    Beacon is an enrolled, active carrier in good standing, but the policy belongs to
    Atlas, so the loss report is refused at ownership scope. The policy ends the test with
    no claims filed under it at all.

    PRD: "Concretely, a `ServicingCarrier` may only act on an `Assignment`, `Policy` or
    `Claim` whose servicing carrier is the carrier the caller is bound to — a `Claim` is
    scoped through the `Policy` it was reported under. A violation is refused with
    `ERR_CARRIER_SCOPE_FORBIDDEN` and HTTP 403."
    Design: Corner/rbac/a_carrier_cannot_reach_another_carriers_rows_and_a_producer_cannot_reach_another_producers
    """
    env = _one_policy_and_a_second_producer_of_record_on_nothing()
    beacon = env["carriers"][1]
    set_clock("2026-09-16T00:00:00Z")

    response = api_client.create_claim(
        {"policy_id": env["policy"]["id"], "loss_date": "2026-09-16T00:00:00Z",
         "at_fault": False, "coverage_line": "PD", "reserve_cents": 50000},
        make_servicing_carrier_headers(beacon["id"]))

    validate_error(response, ApiErrorId.ERR_CARRIER_SCOPE_FORBIDDEN, 403)
    _, meta = validate_paginated(
        api_client.list_claims(env["policy"]["id"], ADMIN_HEADERS))
    assert meta["total_count"] == 0


def test_the_two_carve_outs_in_the_shared_read_sets_are_role_level_rather_than_row_level():
    """Some reads are not shared at all, and those answer on authorisation.

    A servicing carrier is not among the roles listed for reading a producer, and a
    producer is not among those listed for the reconciliation ledger. Neither refusal is
    about whose row it is — both callers are perfectly well authenticated and are naming
    rows that exist — so both are answered as unauthorised rather than as out of scope.

    PRD: "If both headers are well formed but the named role is not among the roles
    authorised for the endpoint being called, the rejection is `ERR_UNAUTHORIZED` with
    HTTP 403."
    Design: Corner/rbac/a_carrier_cannot_reach_another_carriers_rows_and_a_producer_cannot_reach_another_producers
    """
    env = _one_policy_and_a_second_producer_of_record_on_nothing()

    carrier_reads_producer = api_client.get_producer(
        env["producer"]["id"], make_servicing_carrier_headers(env["carrier"]["id"]))
    producer_reads_ledger = api_client.list_quota_reconciliations(
        make_producer_agent_headers(env["producer"]["id"]))

    validate_error(carrier_reads_producer, ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(producer_reads_ledger, ApiErrorId.ERR_UNAUTHORIZED, 403)
    assert validate_success(api_client.get_producer(
        env["producer"]["id"], EXAMINER_ONE_HEADERS))["id"] == env["producer"]["id"]


def test_row_scope_binds_the_four_producer_writes_and_leaves_the_shared_reads_open():
    """The producer that owns nothing may still read the policy it has no part in.

    The producer-scope rule names four write operations and no read. So the Seaside
    producer, which is the producer of record on nothing at all, reads the policy
    successfully, and the row it reads is the one the real producer of record brought in.

    PRD: "The producer-scope rule guards exactly four: filing a market rejection against
    an application, recording a deposit against an application, resubmitting a cured
    application, and policy cancellation."
    Design: Corner/rbac/a_carrier_cannot_reach_another_carriers_rows_and_a_producer_cannot_reach_another_producers
    """
    env = _one_policy_and_a_second_producer_of_record_on_nothing()
    outsider_headers = make_producer_agent_headers(env["outsider"]["id"])
    assert read_application(env["application"]["id"])["producer_id"] == env["producer"]["id"]

    policy = validate_success(api_client.get_policy(env["policy"]["id"], outsider_headers))

    assert policy["id"] == env["policy"]["id"]
    assert policy["carrier_id"] == env["carrier"]["id"]
    assert policy["policy_status"] == "IN_FORCE"
    rows, meta = validate_paginated(api_client.list_applications(
        outsider_headers, params={"producer_id": env["producer"]["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == env["application"]["id"]


# ==========================================================================
# rbac / the_examiner_who_recorded_the_findings_cannot_dispose_of_them
# ==========================================================================
def _complaint_with_findings_recorded_by_the_first_examiner():
    env = setup_policy_in_force(policy_number="AR-100014")
    complaint = docket_complaint(env["policy"]["id"], env["carrier"]["id"],
                                 complaint_type="CLAIM_HANDLING_DELAY",
                                 narrative="Acknowledgement and contact standards not met.")
    recorded = record_findings(complaint["id"], EXAMINER_ONE_USER_ID)
    assert recorded["status"] == "FINDINGS_RECORDED"
    assert recorded["findings_recorded_by_user_id"] == EXAMINER_ONE_USER_ID
    assert recorded["review_round"] == 1
    env["complaint"] = recorded
    return env


def test_the_examiner_who_recorded_the_findings_is_refused_the_disposition():
    """The rule compares the presented identity against the stored investigator.

    The complaint is otherwise perfectly resolvable — it sits in FINDINGS_RECORDED and
    the disposition is a real one — so the only thing wrong is that the examiner
    presenting it is the one whose identity is already stored on the findings. The
    complaint does not move, and the carrier suffers none of the consequences an upheld
    disposition would have brought.

    PRD: "The segregation is enforced literally: if the `X-User-ID` presented on the
    resolution equals the value already stored in `findings_recorded_by_user_id`, the
    request is refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP 409, so one examiner can
    never both investigate and dispose of the same complaint."
    Design: Corner/rbac/the_examiner_who_recorded_the_findings_cannot_dispose_of_them
    """
    env = _complaint_with_findings_recorded_by_the_first_examiner()

    response = api_client.resolve_complaint(
        env["complaint"]["id"], create_resolution_payload("UPHELD"), EXAMINER_ONE_HEADERS)

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)
    complaint = read_complaint(env["complaint"]["id"])
    assert complaint["status"] == "FINDINGS_RECORDED"
    assert complaint["disposition"] is None
    assert complaint["resolved_by_user_id"] is None
    carrier = read_carrier(env["carrier"]["id"])
    assert carrier["performance_score"] == 100
    assert carrier["upheld_complaint_count"] == 0
    assert carrier["posture"] == "OPEN"


def test_a_further_review_round_clears_the_stored_investigator_and_keeps_the_freeze_on():
    """The second examiner sends it back, and the lock moves with the stored identity.

    A further review round is available while the round count is under three, so the
    examiner that did not investigate returns it. The complaint reopens at the next round
    with the investigator identity and note cleared, so a fresh examiner may record
    findings without tripping the segregation rule — and because the policy's open count
    is deliberately left alone, the insured stays protected across the round trip.

    PRD: "`review_round` rises by 1, and both `findings_recorded_by_user_id` and
    `findings_note` are cleared so that a fresh examiner may record findings without
    tripping the segregation rule."
    Design: Corner/rbac/the_examiner_who_recorded_the_findings_cannot_dispose_of_them
    """
    env = _complaint_with_findings_recorded_by_the_first_examiner()

    returned = resolve_complaint(env["complaint"]["id"], "RETURNED_FOR_FURTHER_REVIEW",
                                 EXAMINER_TWO_USER_ID)

    assert returned["status"] == "OPEN"
    assert returned["review_round"] == 2
    assert returned["findings_recorded_by_user_id"] is None
    assert returned["findings_note"] is None
    policy = read_policy(env["policy"]["id"])
    assert policy["open_complaint_count"] == 1
    assert policy["complaint_freeze_active"] is True
    assert read_carrier(env["carrier"]["id"])["performance_score"] == 100


def test_after_the_round_trip_the_examiner_refused_once_is_the_one_who_may_uphold():
    """The stored investigator moved, so the disposition changes hands with it.

    The second examiner records the second-round findings, which makes the first examiner
    — refused this very disposition on this very complaint one round ago — the eligible
    resolver. Its upheld disposition goes through and is the expensive one: twenty points
    off the carrier's score drops it to RESTRICTED, the lifetime upheld count rises, and
    with no complaint of the policy left unresolved the freeze lifts.

    PRD: "A `disposition` of `UPHELD` moves the complaint `FINDINGS_RECORDED →
    RESOLVED_UPHELD` and is the expensive one for the carrier: its
    `upheld_complaint_count` rises by 1, its `performance_score` falls by 20 with a floor
    of 0, and its `posture` is recomputed."
    Design: Corner/rbac/the_examiner_who_recorded_the_findings_cannot_dispose_of_them
    """
    env = _complaint_with_findings_recorded_by_the_first_examiner()
    resolve_complaint(env["complaint"]["id"], "RETURNED_FOR_FURTHER_REVIEW",
                      EXAMINER_TWO_USER_ID)
    second_round = record_findings(env["complaint"]["id"], EXAMINER_TWO_USER_ID)
    assert second_round["findings_recorded_by_user_id"] == EXAMINER_TWO_USER_ID
    assert second_round["status"] == "FINDINGS_RECORDED"
    assert second_round["review_round"] == 2

    upheld = validate_success(api_client.resolve_complaint(
        env["complaint"]["id"], create_resolution_payload("UPHELD"), EXAMINER_ONE_HEADERS))

    assert upheld["status"] == "RESOLVED_UPHELD"
    assert upheld["disposition"] == "UPHELD"
    assert upheld["resolved_by_user_id"] == EXAMINER_ONE_USER_ID
    carrier = read_carrier(env["carrier"]["id"])
    assert carrier["performance_score"] == 80
    assert carrier["upheld_complaint_count"] == 1
    assert carrier["posture"] == "RESTRICTED"
    policy = read_policy(env["policy"]["id"])
    assert policy["open_complaint_count"] == 0
    assert policy["complaint_freeze_active"] is False


# ==========================================================================
# cross_cutting_complexity_layers /
#   a_reconciliation_pinned_to_a_carrier_version_that_has_moved_is_refused
# ==========================================================================
def _period_in_reconciliation_with_atlas_holding_its_single_unit():
    env = bootstrap_plan(carriers=[ATLAS, BEACON])
    atlas = env["carriers"][0]
    risk = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Owen Pike", "driver_license_number": "D-99011"},
        vehicle_overrides={"vin": "1HGCM82633A004360"},
        document_prefix="DEC-70")
    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    assert assignment_for_application(risk["application"]["id"])["carrier_id"] == atlas["id"]
    set_clock("2026-11-30T00:00:00Z")
    period = validate_success(
        api_client.close_plan_period(env["plan_period"]["id"], ADMIN_HEADERS))
    assert period["status"] == "RECONCILING"
    assert period["total_assignable_units"] == 1
    return env


def test_an_unrelated_write_to_the_carrier_row_invalidates_the_reconciliation_token():
    """A licensing amendment the filer never saw is enough to stale the pin.

    The amendment touches nothing the reconciliation measures — the quota target stays at
    one unit — but it does mutate the carrier row, so the version the filer read moments
    earlier no longer matches. The filing is refused before any row is created: the
    ledger is still empty and the carrier's penalty balance is untouched.

    PRD: "If that value does not match the carrier's current `version`, the filing is
    rejected with `ERR_STALE_CARRIER_VERSION` and HTTP 412 — the carrier's
    `assigned_risk_count` or `voluntary_credit_units` moved after the filer read them,
    and computing a variance off that stale volume would misstate the penalty."
    Design: Corner/cross_cutting_complexity_layers/a_reconciliation_pinned_to_a_carrier_version_that_has_moved_is_refused
    """
    env = _period_in_reconciliation_with_atlas_holding_its_single_unit()
    atlas = read_carrier(env["carriers"][0]["id"])
    stale_token = atlas["version"]

    amended = validate_success(api_client.file_carrier_licensing_amendment(
        atlas["id"], create_licensing_amendment_payload(["T02", "T03"]), ADMIN_HEADERS))
    response = api_client.create_quota_reconciliation(
        create_quota_reconciliation_payload(atlas["id"], env["plan_period"]["id"],
                                            "POLICY_COUNT", stale_token),
        ADMIN_HEADERS)

    assert amended["version"] > stale_token
    assert amended["quota_target_units"] == 1
    validate_error(response, ApiErrorId.ERR_STALE_CARRIER_VERSION, 412)
    _, meta = validate_paginated(api_client.list_quota_reconciliations(
        ADMIN_HEADERS, params={"plan_period_id": env["plan_period"]["id"]}))
    assert meta["total_count"] == 0
    assert read_carrier(atlas["id"])["penalty_balance_cents"] == 0


def test_the_re_read_token_is_accepted_and_the_filing_itself_stales_that_token_in_turn():
    """The successful filing consumes its own pin, so a blind retry fails again.

    Re-reading the carrier yields a token that works, and the filing lands with the
    headcount figures the plan derives for it. That success increments the carrier's
    version by exactly one, which is why replaying the very same token — the natural
    thing for a client that did not re-read — is refused a second time.

    PRD: "If that value does not match the carrier's current `version`, the filing is
    rejected with `ERR_STALE_CARRIER_VERSION` and HTTP 412 — the carrier's
    `assigned_risk_count` or `voluntary_credit_units` moved after the filer read them, and
    computing a variance off that stale volume would misstate the penalty. A successful
    filing increments the carrier's `version` by 1."
    Design: Corner/cross_cutting_complexity_layers/a_reconciliation_pinned_to_a_carrier_version_that_has_moved_is_refused
    """
    env = _period_in_reconciliation_with_atlas_holding_its_single_unit()
    atlas_id = env["carriers"][0]["id"]
    validate_success(api_client.file_carrier_licensing_amendment(
        atlas_id, create_licensing_amendment_payload(["T02", "T03"]), ADMIN_HEADERS))
    fresh_token = read_carrier(atlas_id)["version"]

    filing = validate_success(api_client.create_quota_reconciliation(
        create_quota_reconciliation_payload(atlas_id, env["plan_period"]["id"],
                                            "POLICY_COUNT", fresh_token),
        ADMIN_HEADERS), 201)

    assert filing["obligation_units"] == 1
    assert filing["credited_units"] == 1
    assert filing["variance_units"] == 0
    assert filing["penalty_cents"] == 0
    assert filing["status"] == "FINAL"
    assert read_carrier(atlas_id)["version"] == fresh_token + 1
    validate_error(api_client.create_quota_reconciliation(
        create_quota_reconciliation_payload(atlas_id, env["plan_period"]["id"],
                                            "CAR_YEAR_EXPOSURE", fresh_token),
        ADMIN_HEADERS), ApiErrorId.ERR_STALE_CARRIER_VERSION, 412)
    assert read_plan_period(env["plan_period"]["id"])["status"] == "RECONCILING"


# ==========================================================================
# cross_cutting_complexity_layers /
#   a_reclassification_pinned_to_a_policy_version_that_has_moved_is_refused
# ==========================================================================
def _clean_policy_ready_for_reclassification():
    env = setup_policy_in_force(policy_number="AR-100014")
    policy = read_policy(env["policy"]["id"])
    assert policy["final_premium_cents"] == T02_ADULT_CLEAN["final_premium_cents"]
    assert policy["plan_expense_charge_cents"] == T02_ADULT_CLEAN["plan_expense_charge_cents"]
    assert policy["total_annual_charge_cents"] == T02_ADULT_CLEAN["total_annual_charge_cents"]
    assert policy["premium_credited_cents"] == 38939
    assert policy["surcharge_points_applied"] == 0
    assert policy["rating_revision"] == 1
    env["policy"] = policy
    return env


def test_the_first_reclassification_re_rates_the_whole_policy_from_the_new_class_adder():
    """The senior adder alone is one point, which lifts the factor and the whole chain.

    Nothing about the driving record changed: the single point comes from the class adder,
    which moves the factor into the 1.15 band. The per-line rounding then rebuilds the
    premium, the higher premium crosses into the lowest expense-rate tier, and the ledger
    restates what is still owed against the deposit already credited. The revision
    counter and the version both move by one.

    PRD: "On success the policy's `version` increments by 1 and its `rating_revision`
    rises by 1, and `surcharge_points_applied`, `surcharge_factor_applied`,
    `premium_lines`, `final_premium_cents`, `plan_expense_charge_cents` and
    `total_annual_charge_cents` are all recomputed by the §3.4 arithmetic with the new
    driver class substituted into the class adder."
    Design: Corner/cross_cutting_complexity_layers/a_reclassification_pinned_to_a_policy_version_that_has_moved_is_refused
    """
    env = _clean_policy_ready_for_reclassification()

    reclassified = validate_success(api_client.reclassify_policy(
        env["policy"]["id"],
        create_reclassification_payload(env["policy"]["version"], "SENIOR",
                                        "2026-10-01T00:00:00Z"),
        ADMIN_HEADERS))

    assert reclassified["surcharge_points_applied"] == 1
    assert reclassified["surcharge_factor_applied"] == 1.15
    assert reclassified["premium_lines"] == {"BI": 93823, "PD": 51176, "UM": 25588}
    assert reclassified["final_premium_cents"] == 170587
    assert reclassified["plan_expense_charge_cents"] == 6823
    assert reclassified["total_annual_charge_cents"] == 177410
    assert_premium_lines_sum_to_final_premium(reclassified)
    assert_total_annual_charge(reclassified)
    assert reclassified["rating_revision"] == 2
    assert reclassified["version"] == env["policy"]["version"] + 1
    assert reclassified["premium_credited_cents"] == 38939
    assert reclassified["additional_premium_due_cents"] == 138471
    assert reclassified["refund_paid_cents"] == 0
    assert reclassified["policy_status"] == "IN_FORCE"


def test_the_second_reclassification_pinned_to_the_consumed_token_is_refused_before_the_ledger_moves():
    """Two re-ratings in one term are lawful, so the pin is the only replay defence.

    The second filing carries the token the first one consumed. Because a supersession is
    legitimate on its own terms there is no state check to catch it, and the version
    mismatch is what refuses it — before the rating chain or the money axis moves. The
    policy still reads exactly as the first reclassification left it.

    PRD: "If that value does not match the policy's current `version`, the request is
    rejected with `ERR_STALE_POLICY_VERSION` and HTTP 412 — `premium_credited_cents` or
    `surcharge_points_applied` changed after the filer read them, and re-rating from that
    stale base would corrupt the deposit invariant."
    Design: Corner/cross_cutting_complexity_layers/a_reclassification_pinned_to_a_policy_version_that_has_moved_is_refused
    """
    env = _clean_policy_ready_for_reclassification()
    consumed_token = env["policy"]["version"]
    validate_success(api_client.reclassify_policy(
        env["policy"]["id"],
        create_reclassification_payload(consumed_token, "SENIOR", "2026-10-01T00:00:00Z"),
        ADMIN_HEADERS))

    response = api_client.reclassify_policy(
        env["policy"]["id"],
        create_reclassification_payload(consumed_token, "YOUTHFUL_OPERATOR",
                                        "2026-10-01T00:00:00Z"),
        ADMIN_HEADERS)

    validate_error(response, ApiErrorId.ERR_STALE_POLICY_VERSION, 412)
    unchanged = read_policy(env["policy"]["id"])
    assert unchanged["rating_revision"] == 2
    assert unchanged["surcharge_points_applied"] == 1
    assert unchanged["total_annual_charge_cents"] == 177410
    assert unchanged["premium_credited_cents"] == 38939
    assert read_applicant(env["applicant"]["id"])["driver_class"] == "SENIOR"


def test_the_retry_with_a_fresh_token_separates_the_points_from_the_factor():
    """Three points and one point sit in the same band, so only the points move.

    Re-reading the policy yields a token that works, and the youthful adder scores three
    points against the senior adder's one. Both fall inside the 1 through 3 band, so the
    factor, the premium and the term charge are all identical to the previous revision
    while the recorded points are not — and the applicant's own class follows the order.

    PRD: "and by a plan-approved surcharge factor selected as a step function of the
    applied surcharge points: 1.00 at exactly 0 points, 1.15 for 1 through 3 points, 1.35
    for 4 or 5 points, 1.60 for 6 through 9 points, and 1.90 at 10 points or more."
    Design: Corner/cross_cutting_complexity_layers/a_reclassification_pinned_to_a_policy_version_that_has_moved_is_refused
    """
    env = _clean_policy_ready_for_reclassification()
    validate_success(api_client.reclassify_policy(
        env["policy"]["id"],
        create_reclassification_payload(env["policy"]["version"], "SENIOR",
                                        "2026-10-01T00:00:00Z"),
        ADMIN_HEADERS))
    fresh_token = read_policy(env["policy"]["id"])["version"]

    retried = validate_success(api_client.reclassify_policy(
        env["policy"]["id"],
        create_reclassification_payload(fresh_token, "YOUTHFUL_OPERATOR",
                                        "2026-10-01T00:00:00Z"),
        ADMIN_HEADERS))

    assert retried["surcharge_points_applied"] == 3
    assert retried["surcharge_factor_applied"] == 1.15
    assert retried["final_premium_cents"] == 170587
    assert retried["total_annual_charge_cents"] == 177410
    assert retried["rating_revision"] == 3
    assert retried["version"] == fresh_token + 1
    assert retried["premium_settlement_status"] == "PREMIUM_OUTSTANDING"
    assert read_applicant(env["applicant"]["id"])["driver_class"] == "YOUTHFUL_OPERATOR"


# ==========================================================================
# consistency_model / the_issuance_response_already_carries_every_derived_number
# ==========================================================================
def _accepted_assignment_awaiting_its_policy():
    env = bootstrap_plan(carriers=[ATLAS, BEACON])
    atlas = env["carriers"][0]
    risk = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Owen Pike", "driver_license_number": "D-99011"},
        vehicle_overrides={"vin": "1HGCM82633A004360"},
        document_prefix="DEC-90")
    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    assignment = assignment_for_application(risk["application"]["id"])
    assert assignment["carrier_id"] == atlas["id"]
    accept_assignment(assignment["id"], atlas["id"])
    set_clock("2026-09-15T00:00:00Z")
    env.update(risk)
    env["assignment"] = read_assignment(assignment["id"])
    assert read_carrier(atlas["id"])["assigned_risk_count"] == 1
    return env


def _issue_the_awaited_policy(env):
    return validate_success(api_client.create_policy(
        create_policy_payload(env["assignment"]["id"], policy_number="AR-100014"),
        make_servicing_carrier_headers(env["carriers"][0]["id"])), 201)


def test_the_issuance_response_itself_carries_the_whole_rating_chain():
    """One POST returns the finished rating — no follow-up read is needed to see it.

    The 201 body already holds the applied points, the factor they select, the three
    independently rounded coverage lines, their sum, the expense charge chosen from that
    sum before it was added, and the term charge. Nothing about the premium is deferred to
    a later read or a later pass.

    PRD: "each of the three is rounded half up to whole cents independently, and the three
    rounded figures are stored in the policy's `premium_lines` object under the keys `BI`,
    `PD` and `UM`"
    Design: Corner/consistency_model/the_issuance_response_already_carries_every_derived_number
    """
    env = _accepted_assignment_awaiting_its_policy()

    policy = _issue_the_awaited_policy(env)

    assert_policy(policy)
    assert policy["surcharge_points_applied"] == T02_ADULT_CLEAN["surcharge_points"]
    assert policy["surcharge_factor_applied"] == T02_ADULT_CLEAN["surcharge_factor"]
    assert policy["premium_lines"] == T02_ADULT_CLEAN["premium_lines"]
    assert policy["final_premium_cents"] == T02_ADULT_CLEAN["final_premium_cents"]
    assert policy["plan_expense_charge_cents"] == T02_ADULT_CLEAN["plan_expense_charge_cents"]
    assert policy["total_annual_charge_cents"] == T02_ADULT_CLEAN["total_annual_charge_cents"]
    assert_premium_lines_sum_to_final_premium(policy)
    assert_total_annual_charge(policy)
    assert policy["rating_revision"] == 1
    assert policy["version"] == 1
    assert policy["policy_status"] == "IN_FORCE"


def test_the_issuance_response_already_carries_the_swept_ledger_and_the_exposure_figure():
    """The deposit sweep and the exposure figure are inside the same response.

    The whole 38939-cent deposit is below the term charge, so all of it is credited and
    the rest of the charge is restated as still due — both figures present in the creation
    body itself, alongside the money axis they imply. The exposure figure is there too,
    and it is zero: the term opens on the instant the clock reads, so no whole day of it
    has run yet.

    PRD: "The applicant's `deposit_balance_cents` sweeps into the policy's
    `premium_credited_cents`, capped at `total_annual_charge_cents`, per §2.8;
    `additional_premium_due_cents` is restated as whatever remains uncredited."
    Design: Corner/consistency_model/the_issuance_response_already_carries_every_derived_number
    """
    env = _accepted_assignment_awaiting_its_policy()

    policy = _issue_the_awaited_policy(env)

    assert policy["premium_credited_cents"] == 38939
    assert policy["additional_premium_due_cents"] == 116815
    assert policy["refund_paid_cents"] == 0
    assert policy["balance_due_cents"] == 0
    assert policy["premium_settlement_status"] == "PREMIUM_OUTSTANDING"
    assert policy["exposure_car_years_current_period"] == 0
    application = read_application(env["application"]["id"])
    assert application["deposit_paid_total_cents"] == 38939
    assert application["deposit_balance_cents"] == 0
    assert_deposit_ledger_conserved(application, [policy])


def test_every_row_the_issuance_touched_is_already_correct_on_the_very_next_read():
    """No reconciliation pass sits between the write and the reads that follow it.

    The assignment and the application both advance inside the issuance call, so the
    reads taken immediately afterwards see them advanced. The carrier's headcount does not
    move at all, because the placement already counted it at selection, which is why its
    variance is still zero and its posture still open. The applicant's rehabilitation
    clock is likewise already recomputed.

    PRD: "The consistency model is immediate: when one write has consequences for other
    rows, those consequences are applied inside the same request, and a subsequent read
    observes them."
    Design: Corner/consistency_model/the_issuance_response_already_carries_every_derived_number
    """
    env = _accepted_assignment_awaiting_its_policy()

    policy = _issue_the_awaited_policy(env)

    assert read_assignment(env["assignment"]["id"])["status"] == "POLICY_ISSUED"
    assert read_application(env["application"]["id"])["status"] == "POLICY_ISSUED"
    carrier = read_carrier(env["carriers"][0]["id"])
    assert carrier["assigned_risk_count"] == 1
    assert carrier["quota_target_units"] == 1
    assert carrier["quota_variance_units"] == 0
    assert carrier["overallocated"] is False
    assert carrier["posture"] == "OPEN"
    assert read_applicant(env["applicant"]["id"])["clean_years_credited"] == 5
    assert read_policy(policy["id"])["carrier_id"] == env["carriers"][0]["id"]
