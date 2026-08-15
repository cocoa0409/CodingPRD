"""Withholding elections: creation, snapshot, overlap halves, validation guards,
scheduled activation/expiry, ownership, and OCC on the Employee version."""
from test_helpers import (
    DIRECTOR,
    ApiErrorId,
    create_employee,
    create_employee_election,
    create_employer,
    create_pa_nj_active_agreement,
    create_registration,
    create_state_withholding_agency,
    create_work_location,
    get_employer,
    get_success_data,
    make_employee_headers,
    open_nexus_case,
    recompute_nexus_case,
    confirm_nexus_case,
    set_clock,
    setup_employee_at_location,
    submit_registration,
    activate_registration,
    validate_error,
    validate_success,
)


def _fresh_employee(api, employee_id):
    return get_success_data(api.get_employee(employee_id, DIRECTOR))


class TestElectionCreation:
    def test_election_initial_state_submitted(self, api):
        """PRD §3.5: "At creation the employee's `resident_state_code` is snapshotted
        onto the election, `submitted_by_user_id` records the creator, and the election
        starts `SUBMITTED`."

        Design: Corner/state_machines/election_initial_state_submitted
        """
        scenario = setup_employee_at_location(work_state="NJ", resident_state="PA",
                                              employee_ref="E-2102")
        employee = scenario["employee"]
        res = create_employee_election(employee, work_state_code="NJ")
        election = validate_success(res, 201)
        assert election["status"] == "SUBMITTED"

    def test_election_resident_state_snapshotted(self, api):
        """PRD §3.5: "At creation the employee's `resident_state_code` is snapshotted
        onto the election, `submitted_by_user_id` records the creator, and the election
        starts `SUBMITTED`."

        Design: Corner/state_machines/election_initial_state_submitted
        """
        scenario = setup_employee_at_location(work_state="NJ", resident_state="PA",
                                              employee_ref="E-2102")
        employee = scenario["employee"]
        res = create_employee_election(
            employee, work_state_code="NJ", certificate_form_code="NJ-165",
        )
        election = validate_success(res, 201)
        assert election["resident_state_code"] == "PA", (
            "server-side snapshot of the employee's resident state, not client input"
        )
        assert election["submitted_by_user_id"] == employee["id"]


class TestElectionScheduledTransitions:
    def test_election_validate_future_effective_lands_validated(self, api, nexus_analyst_headers):
        """PRD §3.5: "When `effective_from` lies strictly in the future the election
        lands `VALIDATED` and the scheduled sweep moves it to `ACTIVE` once the clock
        reaches that date"

        Design: Corner/state_machines/election_validated_activates_on_clock_sweep
        """
        create_pa_nj_active_agreement()
        scenario = setup_employee_at_location(work_state="NJ", resident_state="PA",
                                              employee_ref="E-2103")
        employee = scenario["employee"]
        election = validate_success(
            create_employee_election(
                employee, work_state_code="NJ",
                effective_from="2026-09-01T00:00:00Z",
                certificate_form_code="NJ-165",
            ),
            201,
        )
        res = api.validate_election(election["id"], nexus_analyst_headers)
        validated = validate_success(res, 200)
        assert validated["status"] == "VALIDATED", (
            "effective_from 2026-09-01 is strictly future at the default clock 2026-08-01"
        )

    def test_election_validated_activates_on_clock_sweep(self, api, nexus_analyst_headers,
                                                         tax_director_headers):
        """PRD §3.5: "When `effective_from` lies strictly in the future the election
        lands `VALIDATED` and the scheduled sweep moves it to `ACTIVE` once the clock
        reaches that date"

        Design: Corner/state_machines/election_validated_activates_on_clock_sweep
        """
        create_pa_nj_active_agreement()
        scenario = setup_employee_at_location(work_state="NJ", resident_state="PA",
                                              employee_ref="E-2103")
        employee = scenario["employee"]
        election = validate_success(
            create_employee_election(
                employee, work_state_code="NJ",
                effective_from="2026-09-01T00:00:00Z",
                certificate_form_code="NJ-165",
            ),
            201,
        )
        get_success_data(api.validate_election(election["id"], nexus_analyst_headers))
        set_clock("2026-09-01T00:00:00Z")
        after = get_success_data(
            api.get_withholding_election(election["id"], tax_director_headers)
        )
        assert after["status"] == "ACTIVE"

    def test_election_validate_past_effective_lands_active(self, api, nexus_analyst_headers):
        """PRD §3.5: "when `effective_from` has already been reached, validation lands
        the election `ACTIVE` directly, with every guard of the `SUBMITTED`-to-
        `VALIDATED` path applied identically."

        Design: Corner/state_machines/election_active_expires_after_effective_to
        """
        create_pa_nj_active_agreement()
        scenario = setup_employee_at_location(work_state="NJ", resident_state="PA",
                                              employee_ref="E-2104")
        employee = scenario["employee"]
        set_clock("2026-08-20T00:00:00Z")
        election = validate_success(
            create_employee_election(
                employee, work_state_code="NJ",
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2026-09-30T00:00:00Z",
                certificate_form_code="NJ-165",
            ),
            201,
        )
        res = api.validate_election(election["id"], nexus_analyst_headers)
        validated = validate_success(res, 200)
        assert validated["status"] == "ACTIVE", (
            "effective_from 2026-08-01 was already reached at clock 2026-08-20"
        )

    def test_election_active_expires_after_effective_to(self, api, nexus_analyst_headers,
                                                        tax_director_headers):
        """PRD §3.5: "The sweep expires elections: a `VALIDATED` or `ACTIVE` election
        whose `effective_to` is set and has passed moves to terminal `EXPIRED`."

        Design: Corner/state_machines/election_active_expires_after_effective_to
        """
        create_pa_nj_active_agreement()
        scenario = setup_employee_at_location(work_state="NJ", resident_state="PA",
                                              employee_ref="E-2104")
        employee = scenario["employee"]
        set_clock("2026-08-20T00:00:00Z")
        election = validate_success(
            create_employee_election(
                employee, work_state_code="NJ",
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2026-09-30T00:00:00Z",
                certificate_form_code="NJ-165",
            ),
            201,
        )
        get_success_data(api.validate_election(election["id"], nexus_analyst_headers))
        set_clock("2026-10-01T00:00:00Z")
        after = get_success_data(
            api.get_withholding_election(election["id"], tax_director_headers)
        )
        assert after["status"] == "EXPIRED", (
            "effective_to 2026-09-30 has passed at clock 2026-10-01"
        )


class TestElectionOverlapHalves:
    def test_election_adjacent_to_prior_end_allowed(self, api):
        """PRD §3.5: "Without `supersede_existing`, a new election whose half-open
        interval intersects a same-type election of the same employee in `SUBMITTED`,
        `VALIDATED`, or `ACTIVE` is rejected with `ERR_ELECTION_OVERLAP`; adjacency is
        allowed, so a new election starting exactly at the prior election's end does
        not overlap."

        Design: Difficulty/resource_temporal_overlap/election_half_open_adjacency_vs_overlap
        """
        scenario = setup_employee_at_location(work_state="NJ", resident_state="PA",
                                              employee_ref="E-1201")
        employee = scenario["employee"]
        first = validate_success(
            create_employee_election(
                employee, work_state_code="NJ",
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2026-12-31T00:00:00Z",
            ),
            201,
        )
        assert first["id"]
        employee = _fresh_employee(api, employee["id"])
        second = validate_success(
            create_employee_election(
                employee, work_state_code="NJ",
                effective_from="2026-12-31T00:00:00Z",
            ),
            201,
        )
        assert second["id"] != first["id"], (
            "half-open [from, to): starting exactly at the prior effective_to is adjacent"
        )

    def test_election_one_day_overlap_rejected(self, api):
        """PRD §3.5: "Without `supersede_existing`, a new election whose half-open
        interval intersects a same-type election of the same employee in `SUBMITTED`,
        `VALIDATED`, or `ACTIVE` is rejected with `ERR_ELECTION_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/election_half_open_adjacency_vs_overlap
        """
        scenario = setup_employee_at_location(work_state="NJ", resident_state="PA",
                                              employee_ref="E-1201")
        employee = scenario["employee"]
        validate_success(
            create_employee_election(
                employee, work_state_code="NJ",
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2026-12-31T00:00:00Z",
            ),
            201,
        )
        employee = _fresh_employee(api, employee["id"])
        res = create_employee_election(
            employee, work_state_code="NJ",
            effective_from="2026-12-30T00:00:00Z",
        )
        validate_error(res, ApiErrorId.ERR_ELECTION_OVERLAP)


class TestElectionDateSanityPriority:
    def test_inverted_range_beats_reciprocity_at_create(self, api):
        """PRD §2.9: "When several checks could reject the same request, the server
        evaluates them in a fixed order and reports the first failure."
        PRD §2.9: "5. **Date sanity.** Date pairs and deadlines are coherent —
        `effective_from` strictly earlier than `effective_to`, a contribution's
        `decision_deadline` strictly in the future, a notice's `response_due_date` no
        earlier than its `received_date` — else `ERR_INVALID_DATE_RANGE` (HTTP 400)."

        Design: Difficulty/priority_pair_validation_conflict/election_create_daterange_beats_reciprocity
        """
        scenario = setup_employee_at_location(work_state="NJ", resident_state="OR",
                                              employee_ref="E-911")
        employee = scenario["employee"]
        res = create_employee_election(
            employee, work_state_code="NJ",
            effective_from="2026-09-01T00:00:00Z",
            effective_to="2026-08-01T00:00:00Z",
        )
        # No OR-NJ agreement exists, so reciprocity coverage (tier 11) would also
        # fail; the tier-5 date-sanity failure must be reported first.
        validate_error(res, ApiErrorId.ERR_INVALID_DATE_RANGE)

    def test_equal_effective_dates_rejected(self, api):
        """PRD §2.9: "Date pairs and deadlines are coherent — `effective_from` strictly
        earlier than `effective_to`, a contribution's `decision_deadline` strictly in
        the future, a notice's `response_due_date` no earlier than its `received_date`
        — else `ERR_INVALID_DATE_RANGE` (HTTP 400)."

        Design: Difficulty/priority_pair_validation_conflict/election_create_daterange_beats_reciprocity
        """
        scenario = setup_employee_at_location(work_state="NJ", resident_state="OR",
                                              employee_ref="E-911")
        employee = scenario["employee"]
        res = create_employee_election(
            employee, work_state_code="NJ",
            effective_from="2026-09-01T00:00:00Z",
            effective_to="2026-09-01T00:00:00Z",
        )
        validate_error(res, ApiErrorId.ERR_INVALID_DATE_RANGE)


class TestCourtesyElectionRegistrationGate:
    def _setup_courtesy_scenario(self):
        """NY-WH agency; NY + NJ locations; employee A resident/working NY (drives the
        NY nexus); employee B resident NY working NJ; NY case CONFIRMED; B's
        COURTESY_RESIDENT election in SUBMITTED."""
        employer = create_employer()
        agency = create_state_withholding_agency(
            state_code="NY", agency_name="NY DTF", withholding_rate_bp=600,
        )
        wl_ny = create_work_location("NY")
        wl_nj = create_work_location("NJ")
        create_employee(wl_ny["id"], employee_ref="E-1121", full_name="Y One",
                        resident_state_code="NY", annual_wage_cents=3_000_000)
        employee_b = create_employee(
            wl_nj["id"], employee_ref="E-1122", full_name="Y Two",
            resident_state_code="NY", annual_wage_cents=3_000_000,
        )
        case = open_nexus_case("NY")
        set_clock("2026-08-20T00:00:00Z")
        recompute_nexus_case(case["id"])
        confirm_nexus_case(case["id"])
        election = validate_success(
            create_employee_election(
                employee_b, election_type="COURTESY_RESIDENT", work_state_code="NJ",
                effective_from="2026-09-01T00:00:00Z",
            ),
            201,
        )
        return employer, agency, election

    def test_courtesy_validate_without_active_registration_rejected(self, api, nexus_analyst_headers):
        """PRD §3.5: "A `COURTESY_RESIDENT` election requires an `ACTIVE` registration
        whose agency is a `STATE_WITHHOLDING` agency of the resident state; a
        `COURTESY_WORK` election requires the same for the work state; each is
        otherwise rejected with `ERR_REGISTRATION_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/courtesy_election_requires_active_registration
        """
        _employer, _agency, election = self._setup_courtesy_scenario()
        res = api.validate_election(election["id"], nexus_analyst_headers)
        validate_error(res, ApiErrorId.ERR_REGISTRATION_NOT_ACTIVE)

    def test_courtesy_validate_after_registration_active_succeeds(self, api, nexus_analyst_headers):
        """PRD §3.5: "A `COURTESY_RESIDENT` election requires an `ACTIVE` registration
        whose agency is a `STATE_WITHHOLDING` agency of the resident state"
        PRD §3.5: "When `effective_from` lies strictly in the future the election lands
        `VALIDATED`"

        Design: Difficulty/cross_entity_state_dependency/courtesy_election_requires_active_registration
        """
        employer, agency, election = self._setup_courtesy_scenario()
        err = api.validate_election(election["id"], nexus_analyst_headers)
        validate_error(err, ApiErrorId.ERR_REGISTRATION_NOT_ACTIVE)
        employer = get_employer(employer["id"])
        registration = create_registration(agency["id"], 1_000_000, employer["version"])
        submit_registration(registration["id"])
        activate_registration(registration["id"], "NY-00000001")
        res = api.validate_election(election["id"], nexus_analyst_headers)
        validated = validate_success(res, 200)
        assert validated["status"] == "VALIDATED", (
            "effective_from 2026-09-01 is strictly future at clock 2026-08-20"
        )


class TestReciprocityValidationGuards:
    def test_reciprocity_validate_without_agreement_rejected(self, api, nexus_analyst_headers):
        """PRD §3.5: "A `RECIPROCITY_EXEMPTION` election requires an `ACTIVE`
        ReciprocityAgreement covering the unordered pair of work and resident states
        and covering `effective_from` — without one, validation fails with
        `ERR_RECIPROCITY_NOT_AVAILABLE`"

        Design: Corner/validations/reciprocity_validate_without_agreement_rejected
        """
        scenario = setup_employee_at_location(work_state="NJ", resident_state="OR",
                                              employee_ref="E-4108")
        employee = scenario["employee"]
        election = validate_success(
            create_employee_election(employee, work_state_code="NJ"),
            201,
        )
        res = api.validate_election(election["id"], nexus_analyst_headers)
        validate_error(res, ApiErrorId.ERR_RECIPROCITY_NOT_AVAILABLE)

    def test_reciprocity_certificate_mismatch_rejected(self, api, nexus_analyst_headers):
        """PRD §3.5: "when that agreement declares a `certificate_form_code`, the
        election's `certificate_form_code` must match it (else `ERR_INVALID_REQUEST`)."

        Design: Corner/validations/reciprocity_certificate_mismatch_rejected
        """
        create_pa_nj_active_agreement(certificate_form_code="NJ-165")
        scenario = setup_employee_at_location(work_state="NJ", resident_state="PA",
                                              employee_ref="E-4109")
        employee = scenario["employee"]
        election = validate_success(
            create_employee_election(
                employee, work_state_code="NJ", certificate_form_code="XX-999",
            ),
            201,
        )
        res = api.validate_election(election["id"], nexus_analyst_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestElectionOwnershipAndOcc:
    def test_employee_cannot_file_election_for_other_employee(self, api):
        """PRD §2.1: "When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the
        acting Employee; ownership checks on any resource that references an Employee
        compare the resource's `employee_id` foreign-key field to `X-User-ID`, and a
        mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/validations/employee_cannot_file_election_for_other_employee
        """
        location = create_work_location("NJ")
        employee_a = create_employee(location["id"], employee_ref="E-4001",
                                     full_name="AO One", resident_state_code="PA")
        employee_b = create_employee(location["id"], employee_ref="E-4002",
                                     full_name="AO Two", resident_state_code="PA")
        res = api.create_withholding_election(
            {
                "employee_id": employee_b["id"],
                "election_type": "RECIPROCITY_EXEMPTION",
                "work_state_code": "NJ",
                "effective_from": "2026-08-01T00:00:00Z",
                "expected_employee_version": employee_b["version"],
            },
            make_employee_headers(employee_a["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    def test_occ_election_create_stale_employee(self, api):
        """PRD §2.8: "Creating a WithholdingElection (`POST /etax/withholding-elections`)
        requires `expected_employee_version` matching the Employee's current `version`,
        since the creation may legitimately supersede the employee's current same-type
        election."
        PRD §2.8: "if that value does not match the parent entity's current `version`,
        the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_election_create_stale_employee
        """
        scenario = setup_employee_at_location(work_state="NJ", resident_state="PA",
                                              employee_ref="E-7001")
        employee = scenario["employee"]
        observed_version = employee["version"]
        first = create_employee_election(employee, work_state_code="NJ")
        validate_success(first, 201)
        fresh = _fresh_employee(api, employee["id"])
        assert fresh["version"] == observed_version + 1, (
            "PRD §3.5: election creation 'increments the employee's `version` by one'"
        )
        stale = api.create_withholding_election(
            {
                "employee_id": employee["id"],
                "election_type": "RECIPROCITY_EXEMPTION",
                "work_state_code": "NJ",
                "effective_from": "2026-08-01T00:00:00Z",
                "supersede_existing": True,
                "expected_employee_version": observed_version,
            },
            make_employee_headers(employee["id"]),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
