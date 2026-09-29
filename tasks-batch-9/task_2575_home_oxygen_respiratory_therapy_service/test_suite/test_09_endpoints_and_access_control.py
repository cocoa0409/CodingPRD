"""Endpoint surface, identity headers and the role authorisation matrix.

Four threads run through this file:

* the three computed reads, which persist nothing and publish values no write
  response ever returns — the losing risk variant, both cap counting bases for a
  month that has never been posted, and the route's live PLANNED count;
* the equipment-assignment junction, whose unit side the server chooses and
  which is therefore navigable only through the placement list;
* the two partial-update shapes — the certificate correction, which is a state
  transition that re-derives the documentation score, against the field-scoped
  patient and branch updates;
* the identity and authorisation ladder: absent headers, an unrecognised role
  name, segregation of duties on certificate approval, and the per-endpoint
  authorised-role whitelists.

Every test builds its own state.  The API server is restarted before each one,
so the database is empty and the logical clock reads its startup default of
2026-08-01T00:00:00Z.
"""

from test_helpers import (
    BILLING_SPECIALIST,
    BRANCH_MANAGER,
    COMPLIANCE_AUDITOR,
    DELIVERY_DRIVER,
    INTAKE_COORDINATOR,
    NON_EXISTENT_UUID,
    PHYSICIAN,
    RESPIRATORY_THERAPIST,
    ApiErrorId,
    api_client,
    assert_cap_summary_read,
    assert_pagination_meta,
    assert_patient,
    assert_placement,
    assert_request_meta,
    assert_risk_assessment_read,
    assert_route_manifest_read,
    complete_in_home_setup,
    complete_setup_payload,
    create_branch_payload,
    create_equipment_assignment_payload,
    create_recall_notice_payload,
    dispatch_route,
    headers_without_auth,
    is_iso8601_timestamp,
    lock_route,
    make_branch,
    make_cmn,
    make_compliance_auditor_headers,
    make_delivery_route,
    make_headers,
    make_patient,
    make_qualifying_test,
    make_route_stop,
    placements_for_contract,
    post_billing_month_payload,
    read_cmn,
    read_contract,
    read_equipment_unit,
    read_patient,
    read_placement,
    return_cmn_for_correction,
    set_clock_payload,
    setup_contract_in_service,
    setup_drafted_cmn,
    setup_open_contract,
    sign_cmn,
    submit_cmn,
    update_branch_payload,
    update_cmn_payload,
    update_patient_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# A single 5.0 lpm stationary concentrator: the only unit the branch owns in the
# recipes that need exactly one candidate for the primary role.
STATIONARY_ONLY = [
    {
        "serial_number": "SC-1001",
        "model_code": "CONC-5L",
        "equipment_class": "STATIONARY_CONCENTRATOR",
        "max_continuous_lpm": 5.0,
        "max_pulse_setting": 0,
        "pm_interval_days": 365,
        "next_pm_due_date": "2027-06-01",
    }
]

# The same stationary unit alongside a 3.0 lpm portable concentrator, so the
# primary and portable roles resolve to two different physical units.
STATIONARY_AND_PORTABLE = STATIONARY_ONLY + [
    {
        "serial_number": "PC-2001",
        "model_code": "POC-3L",
        "equipment_class": "PORTABLE_CONCENTRATOR",
        "max_continuous_lpm": 3.0,
        "max_pulse_setting": 5,
        "pm_interval_days": 365,
        "next_pm_due_date": "2027-06-01",
    },
]


def test_computed_reads_publish_both_variants_and_agree_with_the_stored_rows():
    """The three computed reads persist nothing and publish intermediate values no write returns.

    PRD: "It returns `patient_id`, the five factors as `factor_smoking`, `factor_electrical`, `factor_teachback`, `factor_flow` and `factor_incident`, **both** scores evaluated over that same factor vector as `initial_assessment_score` and `ongoing_surveillance_score`, and the currently stored posture as `persisted_score`, `persisted_variant` and `compliance_hold`."

    Design: Corner/endpoints/restricted_computed_reads_agree_with_stored_rows
    """
    scenario = setup_contract_in_service(
        unit_specs=STATIONARY_ONLY,
        patient_overrides={"mrn": "MRN-0730", "mobility_profile": "HOMEBOUND"},
        setup_overrides={"patient_teachback_score": 4},
    )
    patient_id = scenario["patient"]["id"]
    contract_id = scenario["contract"]["id"]
    route_id = scenario["route"]["id"]

    # ── The risk read: five factors plus both variants over the same vector ──
    risk_response = api_client.get_patient_risk_assessment(
        patient_id, RESPIRATORY_THERAPIST
    )
    risk = validate_success(risk_response)
    assert_request_meta(risk_response)
    assert_risk_assessment_read(risk)

    assert float(risk["factor_smoking"]) == 0, "no smoking was found in the home"
    assert float(risk["factor_electrical"]) == 0, "the electrical inspection passed"
    assert float(risk["factor_teachback"]) == 20, (
        "a teach-back score of 4 misses one step of five, so (5 - 4) * 20 is 20"
    )
    assert float(risk["factor_flow"]) == 20, (
        "3.0 litres per minute is above 2.0 and at most 4.0, which scores 20"
    )
    assert float(risk["factor_incident"]) == 0, "no malfunction has been reported"

    assert float(risk["initial_assessment_score"]) == 9.00, (
        "the weighted average is 0.15 * 20 + 0.30 * 20 = 9.00"
    )
    assert float(risk["ongoing_surveillance_score"]) == 25.00, (
        "the harsher variant takes the largest factor, 20, and adds one 5-point "
        "step for the second non-zero factor"
    )

    assert float(risk["persisted_score"]) == 9.00
    assert risk["persisted_variant"] == "INITIAL_ASSESSMENT", (
        "the in-home assessment applied the initial-assessment variant"
    )
    assert risk["compliance_hold"] is False

    patient = validate_success(api_client.get_patient(patient_id, RESPIRATORY_THERAPIST))
    assert_patient(patient)
    assert float(patient["oxygen_safety_risk_score"]) == float(risk["persisted_score"])
    assert patient["risk_variant_applied"] == risk["persisted_variant"]
    assert patient["compliance_hold"] is risk["compliance_hold"]

    # ── The cap read: both bases, for a month that has never been posted ──
    cap = validate_success(api_client.get_cap_summary(contract_id, BILLING_SPECIALIST))
    assert_cap_summary_read(cap)
    assert cap["candidate_service_month"] == "2026-08", (
        "with an empty ledger the candidate month is the first service month"
    )
    assert cap["service_month_basis_position"] == 1
    assert cap["paid_month_basis_position"] == 1, (
        "no posted element precedes the candidate month, so the paid basis is 1"
    )
    assert cap["variant_applied"] == "SERVICE_MONTH_BASIS", (
        "a competitive-bid single-payment contract counts elapsed calendar months"
    )
    assert cap["effective_position"] == 1
    assert cap["months_remaining"] == 35
    assert cap["monthly_allowable_cents"] == 5590, (
        "one stationary concentrator in the primary role: "
        "7752 * 1.00 * 0.7358 * 0.98 rounded half up"
    )
    assert cap["lifetime_paid_cents"] == 0
    assert cap["posted_month_count"] == 0

    # ── The manifest: a live PLANNED count next to the completed history ──
    manifest = validate_success(api_client.get_route_manifest(route_id, BRANCH_MANAGER))
    assert_route_manifest_read(manifest)
    assert manifest["route_id"] == route_id
    assert manifest["status"] == "COMPLETED", (
        "every stop on the route is terminal, so completion bubbled up"
    )
    assert manifest["completed_stop_count"] == 1
    assert manifest["planned_stop_count"] == 0, (
        "the field counts stops still in PLANNED rather than accumulating them"
    )
    assert manifest["missed_stop_count"] == 0
    assert manifest["cancelled_stop_count"] == 0
    assert manifest["refill_slots_used"] == 0
    assert manifest["refill_capacity_per_day"] == 4, (
        "the manifest echoes the branch's daily refill capacity for comparison"
    )
    assert manifest["total_o2_liters_committed"] == 0, (
        "a setup delivery requesting zero E-cylinders commits no litres"
    )

    # The reads persisted nothing: the stored posture is unchanged afterwards.
    assert read_patient(patient_id)["version"] == patient["version"]
    assert read_contract(contract_id)["version"] == scenario["contract"]["version"]


def test_equipment_assignment_junction_is_navigable_from_both_sides():
    """Assigning equipment by role writes a junction row carrying both the contract and the server-selected unit.

    PRD: "The placement records the `contract_id` it belongs to, the `equipment_unit_id` the selection chose (a field the client may never supply), and the `role` requested."

    Design: Corner/endpoints/equipment_assignment_links_contract_and_unit_both_ways
    """
    scenario = setup_open_contract(
        unit_specs=STATIONARY_AND_PORTABLE,
        patient_overrides={"mrn": "MRN-0740", "mobility_profile": "LIMITED_AMBULATORY"},
        cmn_overrides={"portable_prescribed": True},
    )
    contract_id = scenario["contract"]["id"]
    stationary_unit_id = scenario["stationary_unit"]["id"]
    portable_unit_id = scenario["portable_unit"]["id"]

    primary_response = api_client.create_equipment_assignment(
        contract_id,
        create_equipment_assignment_payload("PRIMARY_STATIONARY"),
        RESPIRATORY_THERAPIST,
    )
    primary = validate_success(primary_response, 201)
    assert_request_meta(primary_response)
    assert_placement(primary)
    assert primary["contract_id"] == contract_id, (
        "the junction carries the contract side even though the body named only a role"
    )
    assert primary["equipment_unit_id"] == stationary_unit_id, (
        "the server chose the only unit the primary role admits"
    )
    assert primary["role"] == "PRIMARY_STATIONARY"
    assert primary["status"] == "RESERVED"

    assert read_equipment_unit(stationary_unit_id)["status"] == "RESERVED", (
        "creating the link moves the unit out of the branch's in-stock pool"
    )

    portable = validate_success(
        api_client.create_equipment_assignment(
            contract_id,
            create_equipment_assignment_payload("PORTABLE"),
            RESPIRATORY_THERAPIST,
        ),
        201,
    )
    assert portable["equipment_unit_id"] == portable_unit_id, (
        "the portable role admits portable concentrators, liquid portables and "
        "compressed cylinders, so the stationary unit is excluded entirely"
    )

    # Forward navigation: by contract.
    forward_rows, forward_meta = validate_paginated(
        api_client.list_placements(
            RESPIRATORY_THERAPIST, params={"contract_id": contract_id}
        )
    )
    assert_pagination_meta(forward_meta, 10, 0, 2)
    assert [row["id"] for row in forward_rows] == [primary["id"], portable["id"]], (
        "the list is ordered by created_at ascending"
    )
    assert forward_rows[0]["role"] == "PRIMARY_STATIONARY"
    assert forward_rows[0]["status"] == "RESERVED"

    # Reverse navigation: by equipment unit, without knowing the contract.
    reverse_rows, reverse_meta = validate_paginated(
        api_client.list_placements(
            RESPIRATORY_THERAPIST, params={"equipment_unit_id": portable_unit_id}
        )
    )
    assert_pagination_meta(reverse_meta, 10, 0, 1)
    assert reverse_rows[0]["role"] == "PORTABLE"
    assert reverse_rows[0]["contract_id"] == contract_id, (
        "the association is navigable from the equipment side"
    )

    # The path side of the link is resolved before any unit is selected.
    missing = api_client.create_equipment_assignment(
        NON_EXISTENT_UUID,
        create_equipment_assignment_payload("BACKUP"),
        RESPIRATORY_THERAPIST,
    )
    validate_error(missing, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value)
    still_two, _ = validate_paginated(
        api_client.list_placements(
            RESPIRATORY_THERAPIST, params={"contract_id": contract_id}
        )
    )
    assert len(still_two) == 2, "the failed call reserved nothing"


def test_releasing_a_reservation_is_available_only_before_setup_places_the_unit():
    """A reserved placement can be released back into the branch pool, but a placed one cannot.

    PRD: "It requires the placement to be `RESERVED` and the referenced unit to be `RESERVED`."

    Design: Corner/endpoints/placement_release_is_conditional_on_reserved_status
    """
    scenario = setup_open_contract(
        unit_specs=STATIONARY_ONLY,
        patient_overrides={"mrn": "MRN-0750", "mobility_profile": "HOMEBOUND"},
    )
    branch_id = scenario["branch"]["id"]
    contract_id = scenario["contract"]["id"]
    unit_id = scenario["stationary_unit"]["id"]

    first = validate_success(
        api_client.create_equipment_assignment(
            contract_id,
            create_equipment_assignment_payload("PRIMARY_STATIONARY"),
            RESPIRATORY_THERAPIST,
        ),
        201,
    )

    released = validate_success(
        api_client.release_placement(first["id"], RESPIRATORY_THERAPIST)
    )
    assert released["status"] == "REMOVED"
    assert released["removal_reason"] == "RELEASED"
    assert is_iso8601_timestamp(released["removed_at"])
    assert released["removed_at"].startswith("2026-08-01T00:00:00"), (
        "the removal is stamped from the logical clock, still at its startup reading"
    )

    assert read_equipment_unit(unit_id)["status"] == "IN_STOCK", (
        "the compensating pair returns the unit to its owning branch's pool"
    )

    # Because the unit is back in stock, the selection rule can pick it again.
    second = validate_success(
        api_client.create_equipment_assignment(
            contract_id,
            create_equipment_assignment_payload("PRIMARY_STATIONARY"),
            RESPIRATORY_THERAPIST,
        ),
        201,
    )
    assert second["equipment_unit_id"] == unit_id

    route = make_delivery_route(branch_id)
    stop = make_route_stop(route["id"], contract_id)
    lock_route(route["id"])
    dispatch_route(route["id"])
    complete_in_home_setup(stop["id"])
    assert read_placement(second["id"])["status"] == "PLACED"

    refused = api_client.release_placement(second["id"], RESPIRATORY_THERAPIST)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE.value)

    assert read_equipment_unit(unit_id)["status"] == "DEPLOYED", (
        "the refused release changed nothing: equipment in the home leaves "
        "through a pickup stop instead"
    )
    assert read_contract(contract_id)["monthly_allowable_cents"] == 5590, (
        "the allowable still counts the one placed stationary concentrator"
    )

    surviving = [
        row
        for row in placements_for_contract(contract_id, role="PRIMARY_STATIONARY")
        if row["status"] not in ("REMOVED", "RECALLED_OUT_OF_SERVICE")
    ]
    assert [row["id"] for row in surviving] == [second["id"]], (
        "three assignment attempts touched the primary role, yet only one "
        "placement for it is non-terminal at any time"
    )


def test_partial_updates_range_from_a_state_transition_to_field_scoped_writes():
    """Correcting a returned certificate re-derives its score and clears the submitter, while patient and branch updates only touch their own row.

    PRD: "Applying corrections then closes the cycle: an `IntakeCoordinator` may revise `prescribed_lpm`, `hours_per_day`, `portable_prescribed`, `length_of_need_months` and `narrative_element_count` on a certificate in `RETURNED_FOR_CORRECTION`, which advances it `RETURNED_FOR_CORRECTION → DRAFT`, recomputes the documentation score over the edited values, clears `submitted_by_user_id` back to null, mirrors `DRAFT` onto the patient when this is the newest certificate, and increments the certificate's `version` by 1."

    Design: Corner/endpoints/patch_endpoints_recompute_derived_fields_and_bump_version
    """
    branch = make_branch()
    patient = make_patient(
        branch["id"],
        mrn="MRN-0760",
        full_name="Caius Delamare",
        mobility_profile="HOMEBOUND",
    )
    admitted_version = patient["version"]
    qualifying_test = make_qualifying_test(patient["id"])
    cmn = make_cmn(patient, qualifying_test["id"])

    assert float(cmn["documentation_score"]) == 100.00, (
        "a complete certificate scores 30 + 20 + 15 + 20 + 10 + 5"
    )
    assert cmn["version"] == 1
    submitted = submit_cmn(cmn["id"])
    returned = return_cmn_for_correction(
        cmn["id"],
        "Narrative overstates the trial of conservative therapy; reduce to the "
        "single documented element.",
    )
    assert returned["version"] == 3, "creation, submission and return are three writes"
    assert returned["revision_round"] == 1

    # The shape check fires before the state check and leaves nothing behind.
    out_of_range = api_client.update_cmn(
        cmn["id"], update_cmn_payload(narrative_element_count=4), INTAKE_COORDINATOR
    )
    validate_error(out_of_range, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert read_cmn(cmn["id"])["version"] == 3, "the rejected update wrote nothing"

    corrected = validate_success(
        api_client.update_cmn(
            cmn["id"], update_cmn_payload(narrative_element_count=1), INTAKE_COORDINATOR
        )
    )
    assert float(corrected["documentation_score"]) == 86.67, (
        "the narrative component becomes 20 * 1/3, and the single final "
        "rounding lands on 86.67"
    )
    assert corrected["status"] == "DRAFT", "the update is a transition, not an inert write"
    assert corrected["version"] == 4
    assert float(corrected["prescribed_lpm"]) == 3.0, "omitted fields survive"
    assert corrected["hours_per_day"] == 24
    assert corrected["revision_round"] == 1, "the revision counter is not re-bumped"
    assert corrected["correction_notes"] == returned["correction_notes"], (
        "the auditor's note stays on the record"
    )
    assert submitted["submitted_by_user_id"] == "u-intake-1"
    assert corrected["submitted_by_user_id"] is None, (
        "the correction discards the prior submission's identity"
    )

    mirrored = read_patient(patient["id"])
    assert mirrored["current_cmn_status"] == "DRAFT"
    assert mirrored["version"] > admitted_version, (
        "the certificate update reaches the patient row through the status mirror"
    )

    resubmitted = submit_cmn(cmn["id"])
    assert resubmitted["status"] == "SUBMITTED", (
        "86.67 clears the documentation gate the certificate has to pass"
    )
    assert float(resubmitted["documentation_score"]) == 86.67
    assert resubmitted["version"] == 5

    wrong_state = api_client.update_cmn(
        cmn["id"], update_cmn_payload(length_of_need_months=6), INTAKE_COORDINATOR
    )
    validate_error(wrong_state, ApiErrorId.ERR_INVALID_STATE.value)

    # The patient update is field-scoped: it moves one row by one version.
    before_patient_update = read_patient(patient["id"])
    updated_patient = validate_success(
        api_client.update_patient(
            patient["id"],
            update_patient_payload(mobility_profile="ACTIVE_AMBULATORY", altitude_feet=9000),
            INTAKE_COORDINATOR,
        )
    )
    assert updated_patient["version"] == before_patient_update["version"] + 1
    assert updated_patient["mobility_profile"] == "ACTIVE_AMBULATORY"
    assert updated_patient["altitude_feet"] == 9000
    assert updated_patient["mrn"] == patient["mrn"], (
        "the unique business key is not reachable through a partial update"
    )
    assert updated_patient["branch_id"] == patient["branch_id"]
    assert updated_patient["status"] == before_patient_update["status"], (
        "the lifecycle state is not reachable either"
    )

    updated_branch = validate_success(
        api_client.update_branch(
            branch["id"], update_branch_payload(refill_capacity_per_day=1), BRANCH_MANAGER
        )
    )
    assert updated_branch["version"] == 2
    assert updated_branch["refill_capacity_per_day"] == 1
    assert updated_branch["tank_exchange_buffer_minutes"] == 30, "untouched fields hold"
    assert updated_branch["liquid_oxygen_certified"] is False
    assert updated_branch["competitive_bid_area"] is True


def test_requests_without_identity_headers_are_rejected_before_any_other_check():
    """A request that carries no operator identity is refused whatever it asks for.

    PRD: "If either header is absent or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_or_unknown_auth_header_returns_401
    """
    anonymous = headers_without_auth()

    # A read that every declared role is allowed to perform.
    validate_error(
        api_client.list_branches(anonymous), ApiErrorId.ERR_UNAUTHENTICATED.value
    )

    # A write whose body is also missing four required fields.
    incomplete_body = api_client.create_branch(
        {"name": "Tampa Bay", "state_code": "FL"}, anonymous
    )
    anonymous_error = validate_error(
        incomplete_body, ApiErrorId.ERR_UNAUTHENTICATED.value
    )
    assert anonymous_error["message"].strip(), (
        "the rejection carries a human-readable message"
    )

    # A body that cannot even be parsed as the endpoint's shape.
    malformed = api_client.set_clock(set_clock_payload("not-a-timestamp"), anonymous)
    validate_error(malformed, ApiErrorId.ERR_UNAUTHENTICATED.value)

    # The same write with a real identity succeeds, so the headers alone caused
    # the refusals above.
    created = validate_success(
        api_client.create_branch(create_branch_payload(), BRANCH_MANAGER), 201
    )
    assert created["name"] == "Tampa Bay"


def test_an_unrecognised_role_name_is_distinguished_from_a_missing_header():
    """A role name outside the seven the service knows is refused as an unknown role, not as an anonymous caller.

    PRD: "If `X-User-Role` carries a value that is not one of the seven recognised role names, the rejection is `ERR_UNKNOWN_ROLE` (HTTP 401)."

    Design: Corner/errors/missing_or_unknown_auth_header_returns_401
    """
    clerk = make_headers("u-mgr-1", "OxygenClerk")

    validate_error(
        api_client.list_branches(clerk), ApiErrorId.ERR_UNKNOWN_ROLE.value
    )

    # Neither the authorisation matrix nor the body's references are consulted:
    # both identifiers below are absent and the pricing basis is not an enum
    # member, yet the unknown role still decides the answer.
    write_attempt = api_client.create_rental_contract(
        {
            "patient_id": NON_EXISTENT_UUID,
            "cmn_id": NON_EXISTENT_UUID,
            "pricing_basis": "CASH",
        },
        clerk,
    )
    validate_error(write_attempt, ApiErrorId.ERR_UNKNOWN_ROLE.value)

    created = validate_success(
        api_client.create_branch(create_branch_payload(), BRANCH_MANAGER), 201
    )
    assert created["version"] == 1


def test_the_operator_who_submitted_or_signed_may_not_also_approve():
    """Compliance approval bars the submitting and the signing identities individually, and the role check answers first.

    PRD: "A `ComplianceAuditor` approving a certificate must present an `X-User-ID` that differs from *both* the certificate's stored `submitted_by_user_id` and its stored `signed_by_user_id`."

    Design: Corner/rbac/auditor_who_submitted_or_signed_cannot_approve
    """
    scenario = setup_drafted_cmn(
        unit_specs=[],
        patient_overrides={
            "mrn": "MRN-0770",
            "full_name": "Domenica Falkenrath",
            "mobility_profile": "HOMEBOUND",
        },
    )
    cmn_id = scenario["cmn"]["id"]

    submitted = submit_cmn(cmn_id)
    signed = sign_cmn(cmn_id)
    assert submitted["submitted_by_user_id"] == "u-intake-1"
    assert signed["signed_by_user_id"] == "u-phys-1"
    assert signed["status"] == "PHYSICIAN_SIGNED"

    # The submitting identity, wearing the authorised role.
    as_submitter = api_client.approve_cmn(
        cmn_id, make_compliance_auditor_headers("u-intake-1")
    )
    submitter_error = validate_error(
        as_submitter, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value
    )
    assert submitter_error["message"].strip(), (
        "the role and the state were both correct; only the identity was wrong"
    )

    # The signing identity is barred by an independent leg of the same rule.
    as_signer = api_client.approve_cmn(
        cmn_id, make_compliance_auditor_headers("u-phys-1")
    )
    validate_error(as_signer, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    # The same offending identity under a role that cannot approve at all is
    # refused for the role, which fixes the ordering between the two refusals.
    as_coordinator = api_client.approve_cmn(cmn_id, INTAKE_COORDINATOR)
    validate_error(as_coordinator, ApiErrorId.ERR_UNAUTHORIZED.value)

    midway = validate_success(
        api_client.get_cmn(cmn_id, make_compliance_auditor_headers("u-audit-1"))
    )
    assert midway["status"] == "PHYSICIAN_SIGNED", "no refusal advanced the certificate"
    assert midway["audited_by_user_id"] is None, "and none recorded an auditor"

    approved = validate_success(
        api_client.approve_cmn(cmn_id, make_compliance_auditor_headers("u-audit-1"))
    )
    assert approved["status"] == "ACTIVE", (
        "a third distinct identity under the same role approves the identical request"
    )
    assert approved["audited_by_user_id"] == "u-audit-1"
    assert approved["initial_date"] == "2026-08-01", (
        "the effective date is stamped from the logical clock"
    )


def test_write_verbs_owned_by_one_role_are_refused_to_the_others_before_any_lookup():
    """Each write verb belongs to one role, and the refusal comes before the referenced row is looked up.

    PRD: "If the role is recognised but is not among the roles authorised for the endpoint being called — as listed in the Authorized Role(s) column of §4 — the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role
    """
    # Signing belongs to the physician; the identical call from the coordinator
    # who drafts certificates never reaches the lookup.
    validate_error(
        api_client.sign_cmn(NON_EXISTENT_UUID, INTAKE_COORDINATOR),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.sign_cmn(NON_EXISTENT_UUID, PHYSICIAN),
        ApiErrorId.ERR_CMN_NOT_FOUND.value,
    )

    # Signing and approving are owned by different roles.
    validate_error(
        api_client.approve_cmn(NON_EXISTENT_UUID, PHYSICIAN),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    # Equipment selection belongs to the clinician, not to revenue cycle.
    assignment = create_equipment_assignment_payload("PRIMARY_STATIONARY")
    validate_error(
        api_client.create_equipment_assignment(
            NON_EXISTENT_UUID, assignment, BILLING_SPECIALIST
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.create_equipment_assignment(
            NON_EXISTENT_UUID, assignment, RESPIRATORY_THERAPIST
        ),
        ApiErrorId.ERR_CONTRACT_NOT_FOUND.value,
    )

    # The manager who owns routes and the clock cannot post money.
    validate_error(
        api_client.post_billing_month(
            NON_EXISTENT_UUID, post_billing_month_payload("2026-08"), BRANCH_MANAGER
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    # Both field roles act on route stops, but on different verbs.
    setup_body = complete_setup_payload(
        education_topics_covered=["EQUIPMENT_OPERATION"]
    )
    validate_error(
        api_client.complete_setup(NON_EXISTENT_UUID, setup_body, DELIVERY_DRIVER),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.complete_setup(NON_EXISTENT_UUID, setup_body, RESPIRATORY_THERAPIST),
        ApiErrorId.ERR_ROUTE_STOP_NOT_FOUND.value,
    )
    validate_error(
        api_client.complete_route_stop(NON_EXISTENT_UUID, RESPIRATORY_THERAPIST),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    # Releasing a reservation is the therapist's verb alone.
    validate_error(
        api_client.release_placement(NON_EXISTENT_UUID, INTAKE_COORDINATOR),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.release_placement(NON_EXISTENT_UUID, RESPIRATORY_THERAPIST),
        ApiErrorId.ERR_PLACEMENT_NOT_FOUND.value,
    )

    # The auditor publishes recalls but cannot reassess a patient; the manager
    # remediates recalls but cannot publish them.
    validate_error(
        api_client.create_risk_reassessment(NON_EXISTENT_UUID, {}, COMPLIANCE_AUDITOR),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.create_recall_notice(
            create_recall_notice_payload(
                severity="CLASS_II",
                remediation_deadline_utc="2026-09-01T00:00:00Z",
            ),
            BRANCH_MANAGER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    # The logical clock is a single-role instrument.
    advance = set_clock_payload("2026-08-02T00:00:00Z")
    validate_error(
        api_client.set_clock(advance, RESPIRATORY_THERAPIST),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    moved = validate_success(api_client.set_clock(advance, BRANCH_MANAGER))
    assert moved["current_utc"].startswith("2026-08-02T00:00:00"), (
        "the identical call from the owning role is accepted"
    )


def test_read_access_is_carved_out_per_endpoint_rather_than_by_privilege_tier():
    """The reads several roles share are shared by a different set of roles at each endpoint.

    PRD: "The authorized-roles column is exhaustive: a role absent from a row is rejected as described in §2.1."

    Design: Corner/rbac/shared_read_access_is_not_uniform_across_roles
    """
    # The safety read: the auditor is inside it, intake and billing are outside.
    validate_error(
        api_client.get_patient_risk_assessment(NON_EXISTENT_UUID, BILLING_SPECIALIST),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.get_patient_risk_assessment(NON_EXISTENT_UUID, INTAKE_COORDINATOR),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.get_patient_risk_assessment(NON_EXISTENT_UUID, COMPLIANCE_AUDITOR),
        ApiErrorId.ERR_PATIENT_NOT_FOUND.value,
    )

    # The cap read admits exactly the role the safety read excludes.
    validate_error(
        api_client.get_cap_summary(NON_EXISTENT_UUID, INTAKE_COORDINATOR),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.get_cap_summary(NON_EXISTENT_UUID, DELIVERY_DRIVER),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.get_cap_summary(NON_EXISTENT_UUID, BILLING_SPECIALIST),
        ApiErrorId.ERR_CONTRACT_NOT_FOUND.value,
    )

    # The manifest is the computed read the auditor cannot see and the driver can.
    validate_error(
        api_client.get_route_manifest(NON_EXISTENT_UUID, COMPLIANCE_AUDITOR),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.get_route_manifest(NON_EXISTENT_UUID, DELIVERY_DRIVER),
        ApiErrorId.ERR_ROUTE_NOT_FOUND.value,
    )

    # Whole entities are invisible to some roles, not merely computed fields:
    # the physician reads clinical documentation but no rental contract.
    validate_error(
        api_client.get_rental_contract(NON_EXISTENT_UUID, PHYSICIAN),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.get_cmn(NON_EXISTENT_UUID, PHYSICIAN),
        ApiErrorId.ERR_CMN_NOT_FOUND.value,
    )

    # The driver reads the logistics half of the model and none of the clinical
    # documentation, though patients are on its whitelist.
    validate_error(
        api_client.get_cmn(NON_EXISTENT_UUID, DELIVERY_DRIVER),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api_client.get_patient(NON_EXISTENT_UUID, DELIVERY_DRIVER),
        ApiErrorId.ERR_PATIENT_NOT_FOUND.value,
    )

    # The refusals above are endpoint-scoped, not a blanket read ban.
    rows, meta = validate_paginated(api_client.list_branches(PHYSICIAN))
    assert rows == [], "the instance starts with no branches registered"
    assert_pagination_meta(meta, 10, 0, 0)
