"""Error selection: which identifier a failing request earns, and what the
refused request must leave behind."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import (
    ERR_ABATEMENT_ORDER_NOT_FOUND,
    ERR_ACCESS_DENIAL_LIMIT_REACHED,
    ERR_APN_ALREADY_REGISTERED,
    ERR_CERTIFICATE_NOT_FOUND,
    ERR_COMMUNITY_NOT_FOUND,
    ERR_COMMUNITY_THRESHOLD_NOT_MET,
    ERR_CONTRACTOR_INSURANCE_LAPSED,
    ERR_CONTRACTOR_NOT_FOUND,
    ERR_CONTRACTOR_NOT_LICENSED,
    ERR_COST_SHARE_CAP_EXCEEDED,
    ERR_CYCLE_NOT_ACTIVE,
    ERR_CYCLE_NOT_FOUND,
    ERR_DUPLICATE_ENROLLMENT,
    ERR_ENROLLMENT_NOT_FOUND,
    ERR_FINDING_NOT_FOUND,
    ERR_INSPECTION_NOT_FOUND,
    ERR_INSPECTOR_NOT_FOUND,
    ERR_INVALID_TIME_WINDOW,
    ERR_NOTICE_NOT_FOUND,
    ERR_PARCEL_NOT_FOUND,
    ERR_PAYMENT_EXCEEDS_OUTSTANDING,
    ERR_PAYMENT_NOT_FOUND,
    ERR_PROGRAM_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_ZONE_ALREADY_EVALUATED,
    ERR_ZONE_EVALUATION_NOT_FOUND,
    PROGRAM_TYPE_CHIPPER,
    PROGRAM_TYPE_GRANT,
    access_denial_payload,
    activate_cycle,
    add_zone,
    assert_award,
    assert_end_of_day,
    assert_hours,
    assert_program_capacity,
    authorized_world,
    award_payload,
    cancel_enrollment,
    community_metrics,
    contractor_patch,
    create_community,
    create_contractor,
    create_cycle,
    create_inspector,
    create_parcel,
    create_program,
    enroll,
    enrollment_payload,
    get_community,
    get_contractor,
    get_cycle,
    get_inspection,
    get_order,
    get_parcel,
    get_program,
    ids_of,
    inspection_payload,
    invoiced_world,
    list_enrollments,
    list_inspections,
    list_notices,
    list_parcels,
    list_payments,
    list_zone_evaluations,
    open_cycle,
    parcel_payload,
    payment_payload,
    record_payment,
    reschedule_payload,
    schedule_inspection,
    serve_notice,
    submit_certification_payload,
    support_program_payload,
    zone_payload,
)
from test_helpers.test_users import (
    FIRE_MARSHAL_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    TITLE_AGENT_HEADERS,
    blank_headers,
    make_community_organizer_headers,
    make_inspector_headers,
    no_headers,
    unknown_role_headers,
)


class TestNotFoundIdentifiers:
    """Fourteen collections, fourteen separate not-found identifiers."""

    def test_each_collection_names_itself_and_the_body_keys_resolve_in_order(
        self, client
    ):
        """Every unknown id answers with its own 404 code, and a request whose cycle
        and parcel are both unknown blames the cycle.

        PRD: "Each missing referent has its own error identifier and all of them answer
        with HTTP 404: ERR_CYCLE_NOT_FOUND, ERR_PARCEL_NOT_FOUND,
        ERR_COMMUNITY_NOT_FOUND, ERR_INSPECTOR_NOT_FOUND, ERR_CONTRACTOR_NOT_FOUND,
        ERR_INSPECTION_NOT_FOUND, ERR_ZONE_EVALUATION_NOT_FOUND, ERR_FINDING_NOT_FOUND,
        ERR_NOTICE_NOT_FOUND, ERR_ABATEMENT_ORDER_NOT_FOUND, ERR_PAYMENT_NOT_FOUND,
        ERR_PROGRAM_NOT_FOUND, ERR_ENROLLMENT_NOT_FOUND and ERR_CERTIFICATE_NOT_FOUND."

        PRD: "Once every path segment resolves, foreign keys supplied in the request
        body are validated in a fixed declaration order: cycle_id, then parcel_id, then
        community_id, then inspector_id, then contractor_id, then inspection_id, then
        violation_notice_id, then support_program_id."

        PRD: "Existence - every path referent resolves left to right, then every body
        foreign key resolves in the declaration order given in section 2.6. Applies to
        every endpoint. Failure: the matching not-found identifier (404)."

        Design: Corner/errors/every_unknown_id_returns_its_own_not_found_code
        """
        reads = (
            (client.get_cycle, ERR_CYCLE_NOT_FOUND),
            (client.get_community, ERR_COMMUNITY_NOT_FOUND),
            (client.get_parcel, ERR_PARCEL_NOT_FOUND),
            (client.get_inspector, ERR_INSPECTOR_NOT_FOUND),
            (client.get_contractor, ERR_CONTRACTOR_NOT_FOUND),
            (client.get_inspection, ERR_INSPECTION_NOT_FOUND),
            (client.get_zone_evaluation, ERR_ZONE_EVALUATION_NOT_FOUND),
            (client.get_hardening_finding, ERR_FINDING_NOT_FOUND),
            (client.get_notice, ERR_NOTICE_NOT_FOUND),
            (client.get_order, ERR_ABATEMENT_ORDER_NOT_FOUND),
            (client.get_payment, ERR_PAYMENT_NOT_FOUND),
            (client.get_support_program, ERR_PROGRAM_NOT_FOUND),
            (client.get_enrollment, ERR_ENROLLMENT_NOT_FOUND),
            (client.get_certificate, ERR_CERTIFICATE_NOT_FOUND),
        )
        assert len(reads) == 14
        seen = []
        for read, expected_error in reads:
            validate_error(
                read(NON_EXISTENT_UUID, headers=PROGRAM_ADMIN_HEADERS),
                expected_error,
                404,
            )
            seen.append(expected_error)
        assert len(set(seen)) == 14, "no two collections may share an identifier"

        # cycle_id is declared before parcel_id, so it is blamed first.
        validate_error(
            client.create_inspection(
                inspection_payload(
                    NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_CYCLE_NOT_FOUND,
            404,
        )


class TestAuthenticationOutranksEverything:
    """The first rung of the ladder answers before existence or shape."""

    def test_absent_blank_and_unrecognised_identities_are_all_401(self, client):
        """No headers, blank headers and an undeclared role all answer 401, even on an
        id that does not exist, while a declared role reaches the row.

        PRD: "Both must be present and non-blank on every endpoint; a request missing
        either header, carrying a blank value, or naming a role outside the seven
        declared below is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        PRD: "A syntactically valid role that is simply not permitted to invoke the
        requested operation is a different failure and is rejected with
        ERR_FORBIDDEN_ROLE (HTTP 403)."

        PRD: "Requests are screened by a fixed ladder of gates, and the ladder is
        strictly ordered: the first gate that fails determines the response, and no
        later gate is evaluated."

        PRD: "Authentication - both auth headers present, and X-User-Role one of the
        seven declared roles. Applies to every endpoint. Failure: ERR_UNAUTHENTICATED
        (401)."

        Design: Corner/errors/missing_auth_headers_returns_401_unauthenticated
        """
        parcel = create_parcel(client)

        validate_error(
            client.get_parcel(parcel["id"], headers=no_headers()),
            ERR_UNAUTHENTICATED,
            401,
        )
        validate_error(
            client.get_parcel(parcel["id"], headers=blank_headers()),
            ERR_UNAUTHENTICATED,
            401,
        )
        # Auditor is not one of the seven declared roles, so this is 401, not 403.
        validate_error(
            client.get_parcel(parcel["id"], headers=unknown_role_headers()),
            ERR_UNAUTHENTICATED,
            401,
        )
        # Authentication sits above existence: the unknown id is never looked up.
        validate_error(
            client.get_parcel(NON_EXISTENT_UUID, headers=no_headers()),
            ERR_UNAUTHENTICATED,
            401,
        )

        reachable = validate_success(
            client.get_parcel(parcel["id"], headers=TITLE_AGENT_HEADERS)
        )
        assert reachable["id"] == parcel["id"]


class TestWindowOrientation:
    """A window must have strictly positive length."""

    def test_a_zero_length_window_is_refused_and_one_second_is_enough(self, client):
        """End equal to start is a 422 on both the inspection and the programme
        surface; one second of length is accepted.

        PRD: "Window orientation - scheduled_end_utc strictly later than
        scheduled_start_utc on inspection scheduling and rescheduling, work_end_utc
        strictly later than work_start_utc on abatement award, and
        service_window_end_utc strictly later than service_window_start_utc on
        support-program creation. An end equal to its start is a violation. Failure:
        ERR_INVALID_TIME_WINDOW (422)."

        Design: Corner/errors/window_end_at_or_before_start_rejected
        """
        cycle = open_cycle(client)
        inspector = create_inspector(client)
        parcel = create_parcel(client)

        def attempt(end):
            return client.create_inspection(
                inspection_payload(
                    parcel["id"],
                    cycle["id"],
                    inspector["id"],
                    scheduled_start_utc="2026-08-20T15:00:00Z",
                    scheduled_end_utc=end,
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            )

        validate_error(
            attempt("2026-08-20T15:00:00Z"), ERR_INVALID_TIME_WINDOW, 422
        )
        _rows, meta = list_inspections(client, cycle_id=cycle["id"])
        assert meta["total_count"] == 0, "nothing was scheduled"

        validate_error(
            attempt("2026-08-20T14:00:00Z"), ERR_INVALID_TIME_WINDOW, 422
        )

        scheduled = validate_success(attempt("2026-08-20T15:00:01Z"), 201)
        assert scheduled["status"] == "SCHEDULED"

        validate_error(
            client.create_support_program(
                support_program_payload(
                    cycle["id"],
                    service_window_start_utc="2026-08-01T00:00:00Z",
                    service_window_end_utc="2026-08-01T00:00:00Z",
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_INVALID_TIME_WINDOW,
            422,
        )


class TestNaturalKeyUniqueness:
    """The parcel conflict is keyed on the APN and nothing else."""

    def test_a_reused_apn_is_refused_even_when_every_other_field_differs(self, client):
        """The incumbent row is left exactly as it was, and the same payload under a
        fresh APN is accepted.

        PRD: "Natural-key uniqueness - Parcel.apn, Contractor.business_name,
        Community.name and InspectionCycle.season_year are each unique across their
        collection. Applies to parcel creation, contractor creation, community creation
        and inspection-cycle creation. Failure: ERR_APN_ALREADY_REGISTERED (409) for all
        four collections."

        Design: Corner/errors/duplicate_apn_registration_rejected
        """
        incumbent = create_parcel(
            client, parcel_payload("APN-5301", owner_name="Ann Reyes")
        )
        assert incumbent["apn"] == "APN-5301"

        clashing = parcel_payload(
            "APN-5301",
            owner_name="Ben Ortiz",
            owner_email="ben@example.com",
            situs_address="99 Canyon Way",
            roof_class="CLASS_A",
            vegetation_type="GRASS",
            slope_pct=10,
            lot_area_sqft=20000,
            hazard_zone="MODERATE",
            access_constraint="NONE",
        )
        validate_error(
            client.create_parcel(clashing, headers=PROGRAM_ADMIN_HEADERS),
            ERR_APN_ALREADY_REGISTERED,
            409,
        )

        _rows, meta = list_parcels(client)
        assert meta["total_count"] == 1
        survivor = get_parcel(client, incumbent["id"])
        assert survivor["version"] == 1
        assert survivor["owner_name"] == "Ann Reyes"

        clashing["apn"] = "APN-5302"
        accepted = validate_success(
            client.create_parcel(clashing, headers=PROGRAM_ADMIN_HEADERS), 201
        )
        assert accepted["apn"] == "APN-5302"


class TestZoneUniquenessIsScopedToTheInspection:
    """One evaluation per zone per visit, and the endpoint is not an upsert."""

    def test_a_repeated_zone_is_refused_without_overwriting_the_first_measurement(
        self, client
    ):
        """The second ZONE_1 row is refused, the stored measurement stays at 15.0 feet,
        and a different zone on the same visit is accepted.

        PRD: "ERR_ZONE_ALREADY_EVALUATED when a zone already carries an evaluation on
        the same inspection"

        PRD: "Completion refuses to run unless all three zones - ZONE_0_EMBER, ZONE_1
        and ZONE_2 - carry exactly one evaluation each on this inspection"

        PRD: "deficit_ratio expresses that shortfall as a fraction of the requirement -
        the deficit divided by the required clearance, rounded half up to four decimal
        places."

        Design: Corner/errors/duplicate_zone_evaluation_rejected
        """
        cycle = open_cycle(client)
        inspector = create_inspector(client)
        parcel = create_parcel(client)
        inspection = serve_notice(
            client,
            schedule_inspection(
                client, parcel["id"], cycle["id"], inspector["id"]
            )["id"],
        )

        first = add_zone(client, inspection["id"], inspector["id"], "ZONE_1", 15.0)
        assert first["measured_clearance_ft"] == 15.0

        validate_error(
            client.create_zone_evaluation(
                inspection["id"],
                zone_payload("ZONE_1", 40.0),
                headers=make_inspector_headers(inspector["id"]),
            ),
            ERR_ZONE_ALREADY_EVALUATED,
            409,
        )

        stored = validate_success(
            client.get_zone_evaluation(first["id"], headers=PROGRAM_ADMIN_HEADERS)
        )
        assert stored["measured_clearance_ft"] == 15.0, "no upsert may happen"
        assert stored["deficit_ft"] == first["deficit_ft"]
        assert stored["deficit_ratio"] == first["deficit_ratio"]
        assert stored["deficiency_severity"] == first["deficiency_severity"]
        assert stored["points"] == first["points"]

        _rows, meta = list_zone_evaluations(client, inspection_id=inspection["id"])
        assert meta["total_count"] == 1

        other_zone = add_zone(
            client, inspection["id"], inspector["id"], "ZONE_2", 118.0
        )
        assert other_zone["zone"] == "ZONE_2"


class TestCycleActivityGate:
    """A PLANNING cycle refuses cycle-scoped writes with its own identifier."""

    def test_a_planning_cycle_answers_cycle_not_active_and_activation_unblocks_it(
        self, client
    ):
        """Scheduling and programme creation both answer ERR_CYCLE_NOT_ACTIVE, and the
        identical scheduling request succeeds once the cycle is ACTIVE.

        PRD: "Cycle activity - the governing inspection cycle has status ACTIVE.
        Applies to nine operations: inspection scheduling, owner-notice service,
        zone-evaluation recording, hardening-finding recording, inspection completion,
        support-program creation, support-enrollment creation, cycle advance and cycle
        close. Failure: ERR_CYCLE_NOT_ACTIVE (409)."

        PRD: "A newly created cycle opens in PLANNING with its epoch counter at 0 and
        its activated_at_utc and closed_at_utc both null."

        Design: Corner/errors/scheduling_on_planning_cycle_returns_cycle_not_active
        """
        cycle = create_cycle(client)
        assert cycle["status"] == "PLANNING"
        assert cycle["activated_at_utc"] is None
        inspector = create_inspector(client)
        parcel = create_parcel(client)
        payload = inspection_payload(
            parcel["id"],
            cycle["id"],
            inspector["id"],
            scheduled_start_utc="2026-08-20T15:00:00Z",
            scheduled_end_utc="2026-08-20T17:00:00Z",
        )

        validate_error(
            client.create_inspection(payload, headers=PROGRAM_ADMIN_HEADERS),
            ERR_CYCLE_NOT_ACTIVE,
            409,
        )
        _rows, meta = list_inspections(client, cycle_id=cycle["id"])
        assert meta["total_count"] == 0

        validate_error(
            client.create_support_program(
                support_program_payload(cycle["id"]), headers=PROGRAM_ADMIN_HEADERS
            ),
            ERR_CYCLE_NOT_ACTIVE,
            409,
        )

        activate_cycle(client, cycle["id"])
        assert get_cycle(client, cycle["id"])["status"] == "ACTIVE"
        scheduled = validate_success(
            client.create_inspection(payload, headers=PROGRAM_ADMIN_HEADERS), 201
        )
        assert scheduled["status"] == "SCHEDULED"


class TestEnrollmentUniquenessIsAPair:
    """The unique key is the programme and the parcel together."""

    def test_the_same_parcel_may_join_another_programme_but_not_the_same_one_twice(
        self, client
    ):
        """The repeat enrollment is refused and reserves nothing; a second programme
        accepts the parcel; cancelling frees the pair again.

        PRD: "And a parcel may hold only one live enrollment per program: a second
        attempt while an enrollment for the same program and parcel already stands in
        REQUESTED, APPROVED, WAITLISTED, COMPLETED or REIMBURSED is refused with
        ERR_DUPLICATE_ENROLLMENT, while a CANCELLED or NO_SHOW enrollment leaves the
        parcel free to try again."

        PRD: "Approval sets reserved_amount_cents to award_cents for a grant, debits the
        program's budget_remaining_cents by that same amount, increments reserved_slots
        by 1, leaves waitlist_position null, and advances the program's version by 1."

        Design: Corner/errors/duplicate_enrollment_rejected
        """
        cycle = open_cycle(client)
        parcel = create_parcel(client)
        first_program = create_program(
            client,
            cycle["id"],
            PROGRAM_TYPE_CHIPPER,
            budget_total_cents=0,
            capacity_slots=2,
        )
        second_program = create_program(
            client,
            cycle["id"],
            PROGRAM_TYPE_CHIPPER,
            budget_total_cents=0,
            capacity_slots=2,
        )

        incumbent = enroll(
            client, first_program["id"], parcel["id"], first_program["version"]
        )
        assert incumbent["status"] == "APPROVED"
        held = get_program(client, first_program["id"])
        assert held["version"] == 2
        assert held["reserved_slots"] == 1

        validate_error(
            client.create_enrollment(
                enrollment_payload(
                    first_program["id"], parcel["id"], held["version"]
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_DUPLICATE_ENROLLMENT,
            409,
        )
        unchanged = get_program(client, first_program["id"])
        assert unchanged["reserved_slots"] == 1
        assert unchanged["version"] == 2

        _rows, meta = list_enrollments(client, parcel_id=parcel["id"])
        assert meta["total_count"] == 1

        # A different programme is a different pair.
        elsewhere = enroll(
            client, second_program["id"], parcel["id"], second_program["version"]
        )
        assert elsewhere["status"] == "APPROVED"

        cancel_enrollment(client, incumbent["id"], reason="Owner rescheduled")
        again = enroll(
            client,
            first_program["id"],
            parcel["id"],
            get_program(client, first_program["id"])["version"],
        )
        assert again["status"] == "APPROVED"


class TestCostShareInvoiceCeiling:
    """The invoice ceiling is an eligibility gate, not a truncation."""

    def test_an_invoice_at_the_ceiling_is_matched_and_one_cent_over_is_refused(
        self, client
    ):
        """1,000,000 cents is eligible and yields an award computed off the 250,000
        truncation; 1,000,001 cents is refused outright.

        PRD: "An invoice above the district's cost-share invoice ceiling of 1,000,000
        cents - four times the per-parcel award cap - is refused outright with
        ERR_COST_SHARE_CAP_EXCEEDED rather than being clamped down to the cap."

        PRD: "The eligible cost is the lesser of the submitted vendor_invoice_cents and
        the per-parcel award cap of 250,000 cents, that is 2,500 dollars."

        PRD: "hardship_bonus_cents is award_before_bonus_cents multiplied by bonus_pct,
        rounded half up to a whole cent, but only when the parcel's owner_hardship_flag
        is true; where the flag is false the bonus is exactly 0."

        PRD: "Cost-share invoice cap - vendor_invoice_cents may not exceed the
        district's cost-share invoice ceiling. Applies to support-enrollment creation.
        Failure: ERR_COST_SHARE_CAP_EXCEEDED (422)."

        Design: Corner/errors/cost_share_invoice_above_cap_rejected
        """
        cycle = open_cycle(client)
        program = create_program(
            client,
            cycle["id"],
            PROGRAM_TYPE_GRANT,
            budget_total_cents=500000,
            capacity_slots=3,
        )
        first_parcel = create_parcel(client, owner_hardship_flag=False)
        second_parcel = create_parcel(client, owner_hardship_flag=False)

        # 250000 eligible, matched at 0.60 for a HIGH parcel, no hardship bonus.
        admitted = enroll(
            client,
            program["id"],
            first_parcel["id"],
            program["version"],
            vendor_invoice_cents=1000000,
        )
        assert admitted["status"] == "APPROVED"
        assert_award(admitted, 150000, 0.05, 0, 150000, reserved=150000)
        funded = get_program(client, program["id"])
        assert_program_capacity(funded, 350000, reserved_slots=1)
        assert funded["version"] == 2

        validate_error(
            client.create_enrollment(
                enrollment_payload(
                    program["id"],
                    second_parcel["id"],
                    funded["version"],
                    vendor_invoice_cents=1000001,
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_COST_SHARE_CAP_EXCEEDED,
            422,
        )
        after = get_program(client, program["id"])
        assert_program_capacity(after, 350000, reserved_slots=1)
        assert after["version"] == 2


class TestContractorLicensingAndInsurance:
    """One rung, two identifiers, and insurance is keyed on the work start."""

    def test_a_suspended_licence_and_a_lapsed_policy_answer_differently(self, client):
        """The SUSPENDED contractor answers ERR_CONTRACTOR_NOT_LICENSED, a policy
        expiring exactly at the work start answers ERR_CONTRACTOR_INSURANCE_LAPSED, and
        one second of cover makes the award land.

        PRD: "Contractor licensing and insurance - license_status is ACTIVE, and
        work_start_utc falls strictly before insurance_expiry_utc. Applies to abatement
        award. Failure: ERR_CONTRACTOR_NOT_LICENSED or ERR_CONTRACTOR_INSURANCE_LAPSED
        (409)."

        PRD: "The contractor's license_status must be ACTIVE, and a SUSPENDED or
        REVOKED licence answers ERR_CONTRACTOR_NOT_LICENSED."

        PRD: "The work_start_utc must fall strictly before the contractor's
        insurance_expiry_utc; a start at or after that instant answers
        ERR_CONTRACTOR_INSURANCE_LAPSED."

        Design: Corner/errors/award_to_unlicensed_or_uninsured_contractor_rejected
        """
        world = authorized_world(client, authorize_at="2026-10-01T00:00:00Z")
        order = world["order"]
        assert order["status"] == "AUTHORIZED"

        unlicensed = create_contractor(client, license_status="SUSPENDED")
        assert unlicensed["license_status"] == "SUSPENDED"
        uninsured = create_contractor(
            client, insurance_expiry_utc="2026-10-05T08:00:00Z"
        )
        assert uninsured["license_status"] == "ACTIVE"

        validate_error(
            client.award_order(
                order["id"],
                award_payload(
                    unlicensed["id"],
                    12.5,
                    "2026-10-05T08:00:00Z",
                    "2026-10-05T18:00:00Z",
                ),
                headers=FIRE_MARSHAL_HEADERS,
            ),
            ERR_CONTRACTOR_NOT_LICENSED,
            409,
        )

        # insurance_expiry_utc == work_start_utc is already lapsed.
        validate_error(
            client.award_order(
                order["id"],
                award_payload(
                    uninsured["id"],
                    12.5,
                    "2026-10-05T08:00:00Z",
                    "2026-10-05T18:00:00Z",
                ),
                headers=FIRE_MARSHAL_HEADERS,
            ),
            ERR_CONTRACTOR_INSURANCE_LAPSED,
            409,
        )

        held = get_order(client, order["id"])
        assert held["status"] == "AUTHORIZED"
        assert held["contractor_id"] is None
        assert held["crew_hours"] is None
        assert_hours(get_contractor(client, unlicensed["id"])["committed_crew_hours"], 0)
        assert_hours(get_contractor(client, uninsured["id"])["committed_crew_hours"], 0)

        validate_success(
            client.update_contractor(
                uninsured["id"],
                contractor_patch(insurance_expiry_utc="2026-10-05T08:00:01Z"),
                headers=PROGRAM_ADMIN_HEADERS,
            )
        )
        awarded = validate_success(
            client.award_order(
                order["id"],
                award_payload(
                    uninsured["id"],
                    12.5,
                    "2026-10-05T08:00:00Z",
                    "2026-10-05T18:00:00Z",
                ),
                headers=FIRE_MARSHAL_HEADERS,
            )
        )
        assert awarded["status"] == "AWARDED"
        assert awarded["contractor_id"] == uninsured["id"]


class TestCommunitySubmissionFloors:
    """Two independent floors guard a certification application."""

    def test_a_two_parcel_neighbourhood_cannot_buy_its_way_in_with_outreach(
        self, client
    ):
        """Forty doors cannot substitute for the third member parcel, and an outreach
        count below the member count is refused just the same.

        PRD: "Three conditions must hold: the community must stand in ORGANIZING, the
        acting CommunityOrganizer's X-User-ID must equal the community's id, and the
        neighbourhood must have at least 3 member parcels while the supplied
        parcels_outreached_count is at least as large as that member-parcel count - a
        neighbourhood cannot claim to have reached more households than it contains, nor
        fewer."

        PRD: "Falling short of either the member-parcel floor or the outreach floor
        answers ERR_COMMUNITY_THRESHOLD_NOT_MET."

        PRD: "A successful submission records parcels_outreached_count, recomputes
        compliance_rate_pct under the community-scoped metric, moves the community
        ORGANIZING -> SUBMITTED, and advances its version by 1."

        Design: Corner/errors/community_submit_below_member_floor_rejected
        """
        community = create_community(client)
        create_parcel(client, community_id=community["id"])
        create_parcel(client, community_id=community["id"])
        organizer = make_community_organizer_headers(community["id"])

        metrics = community_metrics(client, community["id"])
        assert metrics["member_parcel_count"] == 2
        assert metrics["compliance_rate_pct"] is None

        validate_error(
            client.submit_certification(
                community["id"],
                headers=organizer,
                payload=submit_certification_payload(40),
            ),
            ERR_COMMUNITY_THRESHOLD_NOT_MET,
            422,
        )
        held = get_community(client, community["id"])
        assert held["status"] == "ORGANIZING"
        assert held["parcels_outreached_count"] == 0
        assert held["version"] == 1

        create_parcel(client, community_id=community["id"])
        # Three members now, but two knocked doors is fewer than three parcels.
        validate_error(
            client.submit_certification(
                community["id"],
                headers=organizer,
                payload=submit_certification_payload(2),
            ),
            ERR_COMMUNITY_THRESHOLD_NOT_MET,
            422,
        )
        assert get_community(client, community["id"])["status"] == "ORGANIZING"

        submitted = validate_success(
            client.submit_certification(
                community["id"],
                headers=organizer,
                payload=submit_certification_payload(3),
            )
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["parcels_outreached_count"] == 3
        assert submitted["compliance_rate_pct"] is None


class TestThirdAccessDenial:
    """The denial counter is not reset by a rebooking."""

    def test_a_third_denial_is_refused_by_the_ceiling_not_by_the_state(self, client):
        """Two denials with a reschedule between them reach ABANDONED, and the third
        attempt answers ERR_ACCESS_DENIAL_LIMIT_REACHED without raising a second
        citation.

        PRD: "First denial. With access_denial_count standing at 0, the count is
        incremented to 1 and the inspection moves NOTICED -> ACCESS_DENIED."

        PRD: "Second denial. With access_denial_count already standing at 1 - one short
        of the district's ceiling of two denials per inspection - the count is
        incremented to 2 and the inspection moves NOTICED -> ABANDONED instead of to
        ACCESS_DENIED."

        PRD: "The system therefore raises a violation notice against parcel_id with
        severity forced to CRITICAL and notice_method forced to CERTIFIED_MAIL,
        resolving supersedes_notice_id exactly as the notice-creation rules in section
        3.6 prescribe."

        PRD: "A third denial attempt has nowhere to go and is refused with
        ERR_ACCESS_DENIAL_LIMIT_REACHED, as is any denial recorded against an inspection
        already sitting in ABANDONED. ABANDONED is terminal."

        Design: Corner/errors/third_access_denial_after_abandoned_rejected
        """
        cycle = open_cycle(client)
        inspector = create_inspector(client)
        parcel = create_parcel(client)
        inspection = serve_notice(
            client,
            schedule_inspection(
                client,
                parcel["id"],
                cycle["id"],
                inspector["id"],
                scheduled_start_utc="2026-08-20T15:00:00Z",
                scheduled_end_utc="2026-08-20T17:00:00Z",
            )["id"],
        )
        inspector_headers = make_inspector_headers(inspector["id"])

        def deny():
            return client.record_access_denial(
                inspection["id"],
                headers=inspector_headers,
                payload=access_denial_payload(),
            )

        first = validate_success(deny())
        assert first["status"] == "ACCESS_DENIED"
        assert first["access_denial_count"] == 1

        rebooked = validate_success(
            client.reschedule_inspection(
                inspection["id"],
                reschedule_payload("2026-09-10T15:00:00Z", "2026-09-10T17:00:00Z"),
                headers=PROGRAM_ADMIN_HEADERS,
            )
        )
        assert rebooked["status"] == "SCHEDULED"
        assert rebooked["access_denial_count"] == 1, "a rebooking forgives nothing"

        serve_notice(client, inspection["id"])
        second = validate_success(deny())
        assert second["status"] == "ABANDONED"
        assert second["access_denial_count"] == 2

        validate_error(deny(), ERR_ACCESS_DENIAL_LIMIT_REACHED, 409)
        frozen = get_inspection(client, inspection["id"])
        assert frozen["access_denial_count"] == 2
        assert frozen["status"] == "ABANDONED"

        rows, meta = list_notices(client, parcel_id=parcel["id"])
        assert meta["total_count"] == 1, "the refused denial cited nobody"
        assert rows[0]["severity"] == "CRITICAL"
        assert rows[0]["notice_method"] == "CERTIFIED_MAIL"


class TestPaymentCeiling:
    """The bar is the outstanding balance as it stands at request time."""

    def test_one_cent_above_outstanding_creates_no_payment_row(self, client):
        """After a 60,000 part-payment on a 152,461 invoice, 92,462 is refused and
        leaves no row behind, while 92,461 closes the order.

        PRD: "The payment may not exceed the outstanding balance, that is
        total_recoverable_cents minus paid_cents, and an over-payment is refused with
        ERR_PAYMENT_EXCEEDS_OUTSTANDING."

        PRD: "When the order stands in INVOICED and the payment brings paid_cents to
        exactly total_recoverable_cents, the order moves INVOICED -> PAID."

        PRD: "Payments themselves are immutable and are readable individually or as a
        list filtered by abatement_order_id and by method."

        Design: Corner/errors/payment_above_outstanding_balance_rejected
        """
        world = invoiced_world(client)
        order = world["order"]
        assert order["status"] == "INVOICED"
        assert order["total_recoverable_cents"] == 152461
        assert_end_of_day(order["invoice_due_utc"], "2026-11-20")

        part_payment = record_payment(client, order["id"], 60000)
        partly_paid = get_order(client, order["id"])
        assert partly_paid["paid_cents"] == 60000
        assert partly_paid["status"] == "INVOICED"

        # 152461 - 60000 is 92461, so 92462 is exactly one cent too much.
        validate_error(
            client.record_payment(
                order["id"], payment_payload(92462, "ACH"), headers=PROGRAM_ADMIN_HEADERS
            ),
            ERR_PAYMENT_EXCEEDS_OUTSTANDING,
            422,
        )
        untouched = get_order(client, order["id"])
        assert untouched["paid_cents"] == 60000
        assert untouched["status"] == "INVOICED"
        assert untouched["lien_amount_cents"] == 0

        rows, meta = list_payments(client, abatement_order_id=order["id"])
        assert meta["total_count"] == 1, "a refused payment records nothing"
        assert ids_of(rows) == [part_payment["id"]]

        record_payment(client, order["id"], 92461)
        settled = get_order(client, order["id"])
        assert settled["paid_cents"] == 152461
        assert settled["status"] == "PAID"
