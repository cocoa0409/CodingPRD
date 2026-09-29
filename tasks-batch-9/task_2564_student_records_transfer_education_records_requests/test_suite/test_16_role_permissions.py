"""Each role reaches exactly its own operations and no others.

Five roles drive their own exclusive calls to a 2xx in one chain, six calls made
by the wrong role are turned away before anything is inspected, and the one
same-operator bar in the contract is shown to cover a single decision pair.
"""
from test_helpers import (
    ADMIN,
    CLERK,
    COMPLIANCE,
    LEGAL,
    OFFICER_1,
    amendment_decision_payload,
    api_client,
    assert_amendment_request,
    assert_cumulative_file,
    assert_file_component,
    assert_legal_demand,
    assert_records_request,
    assert_student,
    assert_withdrawal,
    certify_component_payload,
    collect_component,
    collect_component_payload,
    create_amendment,
    create_district,
    create_hearing_officer,
    create_state_rule,
    create_student,
    decide_amendment,
    district_payload,
    get_components,
    get_cumulative_file_id,
    get_file,
    hold_payload,
    legal_demand_payload,
    make_parent_headers,
    make_receiving_registrar_headers,
    mark_ready_request,
    request_hearing,
    schedule_hearing,
    set_clock,
    state_rule_payload,
    student_payload,
    validate_error,
    validate_request,
    validate_success,
    withdrawal_payload,
)

CA_RULE = dict(
    transfer_response_days=10,
    discipline_inclusion_mode="SUSPENSIONS_AND_EXPULSIONS",
    discipline_min_days_removed=10,
    include_pending_investigations=False,
    sped_requires_consent=True,
    amendment_hearing_days=30,
    destruction_min_age_years=5,
    directory_optout_grace_days=14,
    notification_wait_days=7,
)
TX_RULE = dict(
    transfer_response_days=30,
    discipline_inclusion_mode="ALL_INCIDENTS",
    discipline_min_days_removed=10,
    include_pending_investigations=True,
    sped_requires_consent=False,
    amendment_hearing_days=45,
    destruction_min_age_years=7,
    directory_optout_grace_days=10,
    notification_wait_days=3,
)


def _one_chain_driven_by_five_roles():
    """Every call below is issued by the single role the contract names for it,
    and the response of each is kept so its status code can be read."""
    rule = api_client.create_state_rule(state_rule_payload("CA", **CA_RULE), ADMIN)
    district = api_client.create_district(
        district_payload(name="Sending Unified", district_code="SEND01", state_code="CA"),
        ADMIN,
    )
    district_id = validate_success(district, 201)["id"]
    student = api_client.create_student(
        student_payload(
            district_id,
            first_name="Cyrus",
            last_name="Nagy",
            dob="2012-06-30",
            grade_level=9,
            has_iep=False,
            guardian_user_id="guardian-cyrus",
        ),
        CLERK,
    )
    student_id = validate_success(student, 201)["id"]
    withdrawal = api_client.create_withdrawal(
        student_id,
        withdrawal_payload(
            effective_date="2026-08-14",
            destination_district_code="TXD-9",
            withdrawal_reason="TRANSFER_OUT",
        ),
        CLERK,
    )
    withdrawal_id = validate_success(withdrawal, 201)["id"]
    placed = api_client.place_withdrawal_hold(
        withdrawal_id, hold_payload("LIBRARY_FINE"), CLERK
    )
    released = api_client.release_withdrawal_hold(
        withdrawal_id, hold_payload("LIBRARY_FINE"), CLERK
    )
    completed = api_client.complete_withdrawal(withdrawal_id, OFFICER_1)
    demand = api_client.create_legal_demand(
        student_id,
        legal_demand_payload(
            demand_type="JUDICIAL_SUBPOENA",
            issuing_authority="Superior Court of CA",
            case_reference="CV-2026-5555",
            production_scope=["ACADEMIC"],
        ),
        LEGAL,
    )
    sweep = api_client.run_compliance_sweep(COMPLIANCE)
    return dict(
        rule=rule,
        district=district,
        student=student,
        withdrawal=withdrawal,
        placed=placed,
        released=released,
        completed=completed,
        demand=demand,
        sweep=sweep,
        student_id=student_id,
        withdrawal_id=withdrawal_id,
    )


class TestEachRoleDrivesItsOwnOperations:
    def test_the_five_role_chain_answers_two_hundred_one_or_two_hundred_throughout(self):
        """Nothing in the chain is refused: the four calls that bring a new resource
        into existence answer 201 and the five that act on an existing one answer
        200, each from the single role the contract admits.

        PRD: "Endpoints that bring a new resource into existence answer with HTTP 201 on success; every other successful call answers with HTTP 200."

        Design: Corner/rbac/each_role_performs_its_own_exclusive_operation
        """
        chain = _one_chain_driven_by_five_roles()

        for name in ("rule", "district", "student", "withdrawal"):
            assert chain[name].status_code == 201, (
                f"{name} brings a new resource into existence, got "
                f"{chain[name].status_code}"
            )
        for name in ("placed", "released", "completed", "demand", "sweep"):
            expected = 201 if name == "demand" else 200
            assert chain[name].status_code == expected, (
                f"{name} answers {expected}, got {chain[name].status_code}"
            )

        docketed = validate_success(chain["demand"], 201)
        assert_legal_demand(docketed)
        assert docketed["status"] == "RECEIVED"

    def test_the_clerk_clears_the_holds_and_the_officer_alone_closes_the_exit(self):
        """The clerk's hold and hold-release leave the withdrawal cleared for the
        officer, whose completion is what exits the student and seals the exit
        anchor; only one withdrawal row was ever created.

        PRD: "Completes a cleared withdrawal, exiting the student, sealing the exit anchor, and minting the retention schedule."

        Design: Corner/rbac/each_role_performs_its_own_exclusive_operation
        """
        chain = _one_chain_driven_by_five_roles()

        on_hold = validate_success(chain["placed"])
        assert_withdrawal(on_hold)
        assert on_hold["status"] == "HOLD"
        assert on_hold["active_hold_types"] == ["LIBRARY_FINE"]

        cleared = validate_success(chain["released"])
        assert cleared["status"] == "CLEARED"
        assert cleared["hold_count"] == 0

        closed = validate_success(chain["completed"])
        assert_withdrawal(closed)
        assert closed["status"] == "COMPLETED"
        assert closed["completed_at"] == "2026-08-01T00:00:00.000Z"

        exited = validate_success(api_client.get_student(chain["student_id"], CLERK))
        assert_student(exited)
        assert exited["enrollment_status"] == "WITHDRAWN"
        assert exited["exit_effective_date"] == "2026-08-14"
        assert exited["records_disposition_date"] == "2031-08-14T00:00:00.000Z"

        rows = validate_success(
            api_client.list_student_withdrawals(chain["student_id"], CLERK)
        )
        assert len(rows) == 1
        assert rows[0]["id"] == chain["withdrawal_id"]


def _dara_with_an_open_withdrawal():
    """A cleared withdrawal, an untouched cumulative file, and the single CA rule
    the admin registered — all created by their proper roles."""
    create_state_rule("CA", **CA_RULE)
    district = create_district("SEND01", state_code="CA", name="Sending Unified")
    student = create_student(
        district["id"],
        first_name="Dara",
        last_name="Okonkwo",
        dob="2012-07-31",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-dara",
    )
    withdrawal = validate_success(
        api_client.create_withdrawal(
            student["id"],
            withdrawal_payload(
                effective_date="2026-08-14",
                destination_district_code="TXD-9",
                withdrawal_reason="TRANSFER_OUT",
            ),
            CLERK,
        ),
        201,
    )
    file_id = get_cumulative_file_id(student["id"])
    return dict(
        district=district,
        student=student,
        withdrawal=withdrawal,
        file_id=file_id,
        academic_id=get_components(file_id)["ACADEMIC"]["id"],
    )


def _six_calls_by_the_wrong_role(scenario):
    """One call per operation, each issued by a role the endpoint does not list."""
    return (
        (
            "a clerk writing statutory reference data",
            api_client.create_state_rule(state_rule_payload("NY", **TX_RULE), CLERK),
        ),
        (
            "an officer running the compliance sweep",
            api_client.run_compliance_sweep(OFFICER_1),
        ),
        (
            "a compliance officer completing a withdrawal",
            api_client.complete_withdrawal(scenario["withdrawal"]["id"], COMPLIANCE),
        ),
        (
            "a legal affairs officer collecting a component",
            api_client.update_file_component(
                scenario["file_id"],
                scenario["academic_id"],
                collect_component_payload(10, 0),
                LEGAL,
            ),
        ),
        (
            "a registrar filing a parent's inspection request",
            api_client.create_inspection_request(
                scenario["student"]["id"],
                {"requested_categories": ["ACADEMIC"], "copies_requested": False},
                make_receiving_registrar_headers(scenario["district"]["id"]),
            ),
        ),
        (
            "a parent docketing a subpoena",
            api_client.create_legal_demand(
                scenario["student"]["id"],
                legal_demand_payload(
                    demand_type="JUDICIAL_SUBPOENA",
                    issuing_authority="Superior Court of CA",
                    case_reference="CV-2026-6666",
                    production_scope=["ACADEMIC"],
                ),
                make_parent_headers("guardian-dara"),
            ),
        ),
    )


class TestOperationsOfOtherRolesAreUnauthorized:
    def test_all_six_wrong_role_calls_are_refused_with_the_same_code(self):
        """Holding a role somewhere in the service is not holding it here: each of
        the six calls names an endpoint that does not list the acting role, and each
        is refused identically.

        PRD: "The Authorized Role(s) column lists exactly the roles whose `X-User-Role` header is accepted; any other role is refused with `ERR_UNAUTHORIZED` and HTTP 403 after path existence has been confirmed."

        Design: Corner/rbac/other_roles_exclusive_operations_are_unauthorized
        """
        scenario = _dara_with_an_open_withdrawal()

        for description, response in _six_calls_by_the_wrong_role(scenario):
            assert response.status_code == 403, (
                f"{description} is a 403, got {response.status_code}"
            )
            validate_error(response, "ERR_UNAUTHORIZED", 403)

    def test_none_of_the_six_refusals_left_a_trace(self):
        """Role authorization runs before any payload field is read, so none of the
        six bodies was ever applied: no second state rule exists, the withdrawal is
        still cleared, the component still holds no pages, and neither the
        inspection docket nor the legal docket has a row.

        PRD: "Role authorization is the second gate a request passes, immediately after path resolution, and it is checked before any payload field is inspected."

        Design: Corner/rbac/other_roles_exclusive_operations_are_unauthorized
        """
        scenario = _dara_with_an_open_withdrawal()
        for _description, _response in _six_calls_by_the_wrong_role(scenario):
            pass

        rules = validate_success(api_client.list_state_rules(ADMIN))
        assert [rule["state_code"] for rule in rules] == ["CA"]

        withdrawal = validate_success(
            api_client.get_withdrawal(scenario["withdrawal"]["id"], OFFICER_1)
        )
        assert_withdrawal(withdrawal)
        assert withdrawal["status"] == "CLEARED"

        student = validate_success(api_client.get_student(scenario["student"]["id"], CLERK))
        assert student["enrollment_status"] == "WITHDRAWAL_PENDING"

        component = get_components(scenario["file_id"])["ACADEMIC"]
        assert_file_component(component)
        assert component["status"] == "PENDING"
        assert component["page_count"] == 0

        file_read = get_file(scenario["file_id"])
        assert_cumulative_file(file_read)
        assert file_read["total_page_count"] == 0

        inspections = validate_success(
            api_client.list_student_inspection_requests(scenario["student"]["id"], CLERK)
        )
        assert inspections == []

        demands = validate_success(
            api_client.list_student_legal_demands(scenario["student"]["id"], LEGAL)
        )
        assert demands == []


def _the_whole_transfer_chain_driven_by_officer_one():
    """One RecordsOfficer, officer-1, certifies all three required components and
    then files, validates, snapshots and releases the request without help."""
    create_state_rule("CA", **CA_RULE)
    create_state_rule("TX", **TX_RULE)
    responding = create_district("SEND01", state_code="CA", name="Sending Unified")
    requesting = create_district("RECV01", state_code="TX", name="Receiving Unified")
    hearing_officer = create_hearing_officer("Marion Vetter", "DISTRICT_DESIGNEE")
    student = create_student(
        responding["id"],
        first_name="Elin",
        last_name="Vasquez",
        dob="2012-08-01",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-elin",
    )
    file_id = get_cumulative_file_id(student["id"])
    components = get_components(file_id)
    for component_type, pages in (("ACADEMIC", 10), ("HEALTH", 20), ("DISCIPLINE", 30)):
        collect_component(file_id, components[component_type]["id"], pages, 0)

    certifications = [
        api_client.update_file_component(
            file_id, components[component_type]["id"], certify_component_payload(), OFFICER_1
        )
        for component_type in ("ACADEMIC", "HEALTH", "DISCIPLINE")
    ]
    filing = api_client.create_records_request(
        {
            "student_id": student["id"],
            "requesting_district_id": requesting["id"],
            "responding_district_id": responding["id"],
            "authorization_reference": "ENR-2026-9090",
        },
        OFFICER_1,
    )
    request_id = validate_success(filing, 201)["id"]
    validate_request(request_id, headers=OFFICER_1)
    ready = mark_ready_request(request_id, file_id, headers=OFFICER_1)
    release = api_client.release_records_request(
        request_id, {"transmission_method": "ENCRYPTED_EMAIL"}, OFFICER_1
    )
    return dict(
        student=student,
        file_id=file_id,
        components=components,
        hearing_officer=hearing_officer,
        certifications=certifications,
        filing=filing,
        request_id=request_id,
        ready=ready,
        release=release,
    )


def _amendment_denied_by_officer_one_and_heard(scenario):
    """officer-1 denies the challenge to the ACADEMIC component, the parent
    exercises the hearing right, and the hearing window closes at 10:00."""
    challenge = create_amendment(
        scenario["student"]["id"],
        scenario["components"]["ACADEMIC"]["id"],
        make_parent_headers("guardian-elin"),
        contested_field="gpa",
        requested_change="Restate term GPA as 3.75",
        rationale="Rubric misapplied",
    )
    denied = decide_amendment(
        challenge["id"], "DENY", headers=OFFICER_1, decision_note="Rubric confirmed"
    )
    assert denied["status"] == "DENIED"
    assert denied["initial_decided_by_user_id"] == "officer-1"
    request_hearing(challenge["id"], make_parent_headers("guardian-elin"))
    schedule_hearing(
        challenge["id"],
        scenario["hearing_officer"]["id"],
        "2026-08-20T09:00:00Z",
        "2026-08-20T10:00:00Z",
        headers=OFFICER_1,
    )
    set_clock("2026-08-20T10:00:00Z")
    return challenge


class TestSegregationCoversOnlyTheDecisionPair:
    def test_one_officer_may_drive_the_entire_transfer_alone(self):
        """No rule anywhere makes the certifying official hand the request to a
        colleague: officer-1 certifies every component, files the request even
        though the identifier is not a district id, snapshots sixty pages and
        transmits them.

        PRD: "For the seven remaining roles — `SystemAdmin`, `RecordsClerk`, `RecordsOfficer`, `ComplianceOfficer`, `LegalAffairsOfficer`, `Parent`, and `EligibleStudent` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server never compares it to any entity's `id`."

        Design: Corner/rbac/segregation_scope_is_limited_to_the_amendment_decision_pair
        """
        scenario = _the_whole_transfer_chain_driven_by_officer_one()

        for index, response in enumerate(scenario["certifications"]):
            assert response.status_code == 200, (
                f"certification {index + 1} answers 200, got {response.status_code}"
            )
            assert validate_success(response)["certified_by_user_id"] == "officer-1"

        assert scenario["filing"].status_code == 201
        complete = get_file(scenario["file_id"])
        assert_cumulative_file(complete)
        assert complete["assembly_status"] == "COMPLETE"

        assert_records_request(scenario["ready"])
        assert scenario["ready"]["status"] == "READY_FOR_RELEASE"
        assert scenario["ready"]["packet_page_count"] == 60

        released = validate_success(scenario["release"])
        assert_records_request(released)
        assert released["status"] == "RELEASED"
        assert released["transmission_method"] == "ENCRYPTED_EMAIL"

    def test_the_one_bar_is_the_officer_deciding_their_own_hearing(self):
        """officer-1, who denied the challenge, is the single operator the contract
        keeps out of its post-hearing decision, and the refusal leaves the challenge
        scheduled with no hearing decision recorded.

        PRD: "The challenge must be in `HEARING_SCHEDULED`, the current logical clock instant must be at or after `hearing_end_at` — a decision issued before the hearing has actually been held is refused with `ERR_HEARING_NOT_HELD` — and the acting `X-User-ID` must differ from the stored `initial_decided_by_user_id`, or the decision is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_scope_is_limited_to_the_amendment_decision_pair
        """
        scenario = _the_whole_transfer_chain_driven_by_officer_one()
        challenge = _amendment_denied_by_officer_one_and_heard(scenario)

        response = api_client.create_amendment_decision(
            challenge["id"],
            amendment_decision_payload("DENY", decision_note="Same officer post-hearing"),
            OFFICER_1,
        )

        validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 403)

        held = validate_success(api_client.get_amendment_request(challenge["id"], OFFICER_1))
        assert_amendment_request(held)
        assert held["status"] == "HEARING_SCHEDULED"
        assert held["hearing_decided_by_user_id"] is None
        assert held["initial_decided_by_user_id"] == "officer-1"

    def test_the_bar_is_per_challenge_rather_than_per_officer(self):
        """The stored identifier that officer-1 must differ from belongs to one
        challenge, so the same officer may still take the initial decision on a
        second challenge, and a denial amends nothing.

        PRD: "And the officer who denied an amendment may never decide its hearing: a post-hearing decision whose `X-User-ID` equals the stored `initial_decided_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_scope_is_limited_to_the_amendment_decision_pair
        """
        scenario = _the_whole_transfer_chain_driven_by_officer_one()
        first = _amendment_denied_by_officer_one_and_heard(scenario)

        second = create_amendment(
            scenario["student"]["id"],
            scenario["components"]["HEALTH"]["id"],
            make_parent_headers("guardian-elin"),
            contested_field="immunization_note",
            requested_change="Remove duplicate dose",
            rationale="Clinic double entry",
        )
        decided = validate_success(
            api_client.create_amendment_decision(
                second["id"],
                amendment_decision_payload(
                    "DENY", decision_note="Immunization record verified"
                ),
                OFFICER_1,
            )
        )

        assert_amendment_request(decided)
        assert decided["status"] == "DENIED"
        assert decided["initial_decided_by_user_id"] == "officer-1"
        assert decided["id"] != first["id"]

        components = get_components(scenario["file_id"])
        assert components["ACADEMIC"]["amendment_count"] == 0
        assert components["HEALTH"]["amendment_count"] == 0
