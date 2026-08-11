"""Platform: entity defaults, validation pipeline, envelope/pagination,
filters, sub-resource reachability, RBAC, OCC, dormancy, consistency."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_employer,
    create_approved_assessment,
    create_agreement,
    create_quoted_agreement,
    create_signed_agreement,
    create_venue_for_mode,
    create_cohort_under,
    create_session_on,
    create_instructor,
    propose_and_confirm,
    enroll_participants,
    setup_launched_cohort,
    api_client,
    TEST_USERS,
    make_employer_contact_headers,
    make_instructor_headers,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["admin_headers"]
CRED = TEST_USERS["credential_officer_headers"]
GRANT = TEST_USERS["grant_officer_headers"]


class TestEmployerCreationDefaults:
    def test_new_employer_is_prospect_with_zero_rollups(self, api):
        """PRD §3.1: "New employers start as `PROSPECT`, with both rollup
        figures — `lifetime_billed_cents` and `follow_on_pipeline_cents` — at
        zero." PRD §2.4: "`id` is a server-minted UUID with no type prefix."
        PRD §2.4: "`version` is an integer maintained per resource: it
        increments by one on every mutation of that resource".

        Design: Corner/entities/employer_creation_applies_defaults
        """
        emp = create_employer(legal_name="NewCo", industry_code="111110",
                              contact_email="hr@newco.example")
        assert emp["status"] == "PROSPECT"
        assert emp["lifetime_billed_cents"] == 0
        assert emp["follow_on_pipeline_cents"] == 0
        assert emp["version"] == 1
        fetched = get_success_data(api_client.get_employer(emp["id"], COORD))
        assert fetched["id"] == emp["id"]
        assert fetched["created_at"]


class TestValidationPipeline:
    def test_missing_role_header_returns_400_before_not_found(self, api):
        """PRD §2.8: "Incoming requests are validated in a fixed priority
        order, and the first failing check produces the error response"
        beginning with "Presence and well-formedness of `X-User-ID` and
        `X-User-Role` (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`)" ahead of
        existence (`ERR_NOT_FOUND`). PRD §2.8: "a call with a missing role
        header and a stale version reports
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, never
        `ERR_STALE_VERSION`."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api_client.get_employer(NON_EXISTENT_UUID, headers={"X-User-ID": "wc-01"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_unknown_id_returns_not_found(self, api):
        """PRD §2.8 item 3: "Existence of every path identifier, validated
        left-to-right along the URL — on a nested path such as an employer's
        child resource, the employer is verified first, then the child, and
        the first missing link produces `ERR_NOT_FOUND`."

        Design: Corner/entities/entity_get_unknown_id_returns_not_found
        """
        resp = api_client.get_employer(NON_EXISTENT_UUID, COORD)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_employer_create_missing_contact_email_rejected(self, api):
        """PRD §3.1: an employer is created "from its `legal_name`,
        `industry_code`, and `contact_email`"; PRD §2.8 item 4: "Request-body
        shape: required fields present, types valid, enum values inside their
        domain, `end_at` strictly after `start_at`, recorded attendance hours
        no greater than the session's `hours`, counts positive
        (`ERR_INVALID_REQUEST`)".

        Design: Corner/entities/employer_create_missing_required_field_returns_invalid_request
        """
        resp = api_client.create_employer(
            {"legal_name": "NoMail", "industry_code": "111110"}, COORD
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_invalid_pricing_model_enum_rejected(self, api):
        """PRD §2.8 item 4: "Request-body shape: required fields present,
        types valid, enum values inside their domain, `end_at` strictly after
        `start_at`, recorded attendance hours no greater than the session's
        `hours`, counts positive (`ERR_INVALID_REQUEST`)"; PRD §3.2 names the
        `pricing_model` domain as (`PER_PARTICIPANT` or `FLAT_COHORT`).

        Design: Corner/entities/invalid_enum_on_agreement_create_rejected
        """
        emp = create_employer(legal_name="EnumCo", industry_code="213112",
                              contact_email="hr@enum.example")
        na = create_approved_assessment(emp["id"])
        resp = api_client.create_training_agreement(
            emp["id"],
            {"needs_assessment_id": na["id"], "pricing_model": "PER_HEAD",
             "delivery_mode": "ON_SITE", "est_participant_count": 2,
             "est_delivery_hours": 2, "target_start_date": "2026-06-15T00:00:00Z",
             "max_cohorts": 2},
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAssessmentLifecycle:
    def test_initial_draft_then_submit(self, api):
        """PRD §3.1: "The assessment starts in `DRAFT` with `revision_round`
        at zero. Submission by a `WorkforceCoordinator` moves it to
        `SUBMITTED`".

        Design: Corner/state_machines/assessment_initial_state_and_submit_transition
        """
        emp = create_employer(legal_name="InitCo", industry_code="111199",
                              contact_email="hr@init.example")
        na = get_success_data(
            api_client.create_needs_assessment(
                emp["id"],
                {"title": "T", "skill_gaps": ["t"], "target_roles": ["r"],
                 "curriculum_modules": [{"code": "T-1", "hours": 2,
                                         "required_credential_codes": []}]},
                COORD,
            )
        )
        assert na["status"] == "DRAFT"
        submitted = validate_success(api_client.submit_needs_assessment(na["id"], COORD))
        assert submitted["status"] == "SUBMITTED"


class TestCohortComputedFields:
    def test_enrolled_count_is_computed(self, api):
        """PRD §3.4: "A new cohort starts with `delivery_status` `SCHEDULED`
        and `billing_status` `UNBILLED`, with `enrolled_count` and
        `completer_count` both at zero." PRD §3.4: "Each enrollment starts the
        participant's `completion_status` at `ENROLLED`, with `attended_hours`
        and `attendance_pct` at zero, and increments the cohort's
        `enrolled_count` by one."

        Design: Corner/entities/cohort_computed_enrolled_count_ignores_input
        """
        emp = create_employer(legal_name="CompCo", industry_code="213111",
                              contact_email="hr@comp.example")
        na = create_approved_assessment(emp["id"])
        agr = create_signed_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT")
        coh = create_cohort_under(agr["id"], min_enrollment=1)
        assert coh["enrolled_count"] == 0
        enroll_participants(coh["id"], ["C01"])
        after = get_success_data(api_client.get_cohort(coh["id"], COORD))
        assert after["enrolled_count"] == 1


class TestPaginationAndFilters:
    def _three_agreements(self, api):
        emp = create_employer(legal_name="PageCo", industry_code="111183",
                              contact_email="hr@page.example")
        na = create_approved_assessment(emp["id"])
        for ov in (dict(est_participant_count=2, pricing_model="FLAT_COHORT"),
                   dict(est_participant_count=5, pricing_model="PER_PARTICIPANT",
                        est_delivery_hours=4, target_start_date="2026-07-15T00:00:00Z"),
                   dict(est_participant_count=8, pricing_model="FLAT_COHORT",
                        delivery_mode="ON_CAMPUS", est_delivery_hours=6,
                        target_start_date="2026-08-15T00:00:00Z")):
            ov.setdefault("max_cohorts", 1)
            create_agreement(emp["id"], na["id"], **ov)
        return emp, na

    def test_limit_offset_has_more_and_envelope_meta(self, api):
        """PRD §2.3: "The `meta` object of a list response carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`".
        PRD §2.2: "`api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`" and
        "`api_request_timestamp` is a server-generated ISO 8601 UTC
        timestamp".

        Design: Corner/endpoints/list_pagination_limit_offset_has_more
        """
        emp, _ = self._three_agreements(api)
        page1 = api_client.list_training_agreements(
            COORD, params={"employer_id": emp["id"], "limit": 2, "offset": 0}
        )
        data1, meta1 = validate_paginated(page1)
        assert len(data1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2 = api_client.list_training_agreements(
            COORD, params={"employer_id": emp["id"], "limit": 2, "offset": 2}
        )
        data2, meta2 = validate_paginated(page2)
        assert len(data2) == 1
        assert meta2["has_more"] is False

        body1 = page1.json()
        assert body1["meta"]["api_request_id"].startswith("req_")
        assert body1["meta"]["api_request_timestamp"]
        body2 = page2.json()
        assert body2["meta"]["api_request_id"].startswith("req_")
        assert body2["meta"]["api_request_timestamp"]

    def test_filter_by_contract_status(self, api):
        """PRD §4: "List agreements with optional filters
        `needs_assessment_id`, `employer_id`, `contract_status`, paginated".

        Design: Corner/endpoints/list_filter_by_contract_status
        """
        emp = create_employer(legal_name="FiltCo", industry_code="111182",
                              contact_email="hr@filt.example")
        na = create_approved_assessment(emp["id"])
        a1 = create_agreement(emp["id"], na["id"], max_cohorts=1)
        create_agreement(emp["id"], na["id"], est_participant_count=3, max_cohorts=1)
        create_agreement(emp["id"], na["id"], est_participant_count=4, max_cohorts=1)
        validate_success(api_client.quote_training_agreement(a1["id"], COORD))

        resp = api_client.list_training_agreements(
            COORD, params={"employer_id": emp["id"], "contract_status": "DRAFT"}
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        for row in data:
            assert row["contract_status"] == "DRAFT"


class TestSubResourceReachability:
    def test_cohort_sessions_scoped_to_parent(self, api):
        """PRD §4: "List a cohort's sessions, paginated" under
        `GET /ct/cohorts/{id}/sessions` — the listing is scoped to the
        addressed cohort.

        Design: Corner/endpoints/fk_reverse_reachability_subresource
        """
        emp = create_employer(legal_name="FKCo", industry_code="111181",
                              contact_email="hr@fk.example")
        na = create_approved_assessment(emp["id"], curriculum_modules=[
            {"code": "T-1", "hours": 4, "required_credential_codes": []}])
        agr = create_signed_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT",
                                      est_delivery_hours=4, max_cohorts=3)
        ven = create_venue_for_mode("ON_SITE", name="FK Site", capacity=8)
        ca = create_cohort_under(agr["id"], min_enrollment=1,
                                 end_date="2026-06-16T00:00:00Z", venue_id=ven["id"])
        cb = create_cohort_under(agr["id"], min_enrollment=1,
                                 start_date="2026-07-15T00:00:00Z",
                                 end_date="2026-07-16T00:00:00Z", venue_id=ven["id"])
        create_session_on(ca["id"], ven["id"],
                          "2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")
        create_session_on(ca["id"], ven["id"],
                          "2026-06-16T09:00:00Z", "2026-06-16T11:00:00Z")

        data_a, _ = validate_paginated(api_client.list_cohort_sessions(ca["id"], COORD))
        assert len(data_a) == 2
        resp_b = api_client.list_cohort_sessions(cb["id"], COORD)
        data_b, _ = validate_paginated(resp_b)
        assert len(data_b) == 0
        assert resp_b.json()["response_type"] == "array"


class TestRbac:
    def test_employer_contact_cannot_create_cohort(self, api):
        """PRD §2.1: "Once the headers are accepted, the caller's role must be
        listed among the roles authorized for the target endpoint, and any
        entity-backed ownership rule must hold; a failure here is rejected
        with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."; PRD §4 lists
        `POST /ct/training-agreements/{id}/cohorts` as
        WorkforceCoordinator-only.

        Design: Corner/rbac/employer_contact_cannot_create_cohort_returns_403
        """
        emp = create_employer(legal_name="RbacCo", industry_code="111177",
                              contact_email="hr@rbac.example")
        na = create_approved_assessment(emp["id"])
        agr = create_signed_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT")
        resp = api_client.create_cohort(
            agr["id"],
            {"delivery_mode": "ON_SITE", "min_enrollment": 1,
             "start_date": "2026-06-15T00:00:00Z", "end_date": "2026-06-15T00:00:00Z"},
            make_employer_contact_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_instructor_close_attendance_ownership(self, api):
        """PRD §2.1: "When `X-User-Role` is `Instructor`, `X-User-ID` is the
        `id` of the acting `Instructor`; the attendance-closure check compares
        the `instructor_id` of a confirmed assignment on the session to
        `X-User-ID`"; a mismatch is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

        Design: Corner/rbac/instructor_close_attendance_ownership_enforced
        """
        ctx = setup_launched_cohort(num_participants=1, min_enrollment=1,
                                    participant_prefix="O")
        other = create_instructor(full_name="Bo Instructor")
        resp = api_client.close_attendance(
            ctx["session_ids"][0],
            {"attendance": [{"external_employee_ref": "O01", "attended_hours": 2}]},
            make_instructor_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestOcc:
    def test_revise_with_stale_version_returns_412(self, api):
        """PRD §2.6: "If that value does not match the agreement's current
        `version` — because another writer has advanced it since the caller
        last read it — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_revise_stale_version_returns_412
        """
        emp = create_employer(legal_name="OccCo", industry_code="111173",
                              contact_email="hr@occ.example")
        na = create_approved_assessment(emp["id"])
        agr = create_quoted_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT",
                                      est_participant_count=5)
        ec = make_employer_contact_headers(emp["id"])
        validate_success(api_client.negotiate_training_agreement(agr["id"], ec))
        observed = get_success_data(api_client.get_training_agreement(agr["id"], COORD))["version"]

        first = validate_success(
            api_client.revise_training_agreement(
                agr["id"], {"expected_agreement_version": observed,
                            "est_participant_count": 6}, COORD)
        )
        assert first["negotiation_round"] == 1

        validate_success(api_client.negotiate_training_agreement(agr["id"], ec))
        resp = api_client.revise_training_agreement(
            agr["id"], {"expected_agreement_version": observed,
                        "est_participant_count": 7}, COORD)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_grant_create_with_stale_cohort_version_returns_412(self, api):
        """PRD §2.6: "The grant-application creation endpoint
        (`POST /ct/cohorts/{id}/grant-applications`) requires the request body
        to carry `expected_cohort_version`, holding the caller's last-observed
        `version` of the cohort. A mismatch with the cohort's current
        `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.4: "Each enrollment starts the participant's
        `completion_status` at `ENROLLED`, with `attended_hours` and
        `attendance_pct` at zero, and increments the cohort's
        `enrolled_count` by one" (a mutation, which per §2.4 increments
        `version`).

        Design: Corner/cross_cutting_layers/occ_grant_create_stale_cohort_version_returns_412
        """
        from test_helpers import create_grant_program
        gp = create_grant_program(code="GP-O2")
        emp = create_employer(legal_name="Occ2Co", industry_code="111172",
                              contact_email="hr@occ2.example")
        na = create_approved_assessment(emp["id"])
        agr = create_signed_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT",
                                      est_participant_count=3, max_cohorts=1)
        coh = create_cohort_under(agr["id"], min_enrollment=1)
        stale_v = coh["version"]
        enroll_participants(coh["id"], ["OC1"])  # bumps cohort version

        resp = api_client.create_grant_application(
            coh["id"],
            {"program_id": gp["id"], "requested_cents": 10000,
             "expected_cohort_version": stale_v},
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh_v = get_success_data(api_client.get_cohort(coh["id"], COORD))["version"]
        ok = validate_success(
            api_client.create_grant_application(
                coh["id"],
                {"program_id": gp["id"], "requested_cents": 10000,
                 "expected_cohort_version": fresh_v},
                COORD,
            ),
            201,
        )
        assert ok["status"] == "DRAFT"


class TestStateBeatsOccPriority:
    def test_revise_on_draft_reports_invalid_state_not_stale_version(self, api):
        """PRD §2.8: "Incoming requests are validated in a fixed priority
        order, and the first failing check produces the error response", with
        item 5 "Generic state legality: the target entity must be in a state
        from which the requested transition exists (`ERR_INVALID_STATE`)"
        ordered before item 9 "Reference integrity: `ERR_STALE_ASSESSMENT`,
        `ERR_STALE_VERSION`, `ERR_DUPLICATE_PARTICIPANT`,
        `ERR_DELIVERY_MODE_MISMATCH`". PRD §3.2: "A successful revision moves
        the agreement from `NEGOTIATING` back to `QUOTED`" — revision exists
        only from `NEGOTIATING`.

        Design: Corner/validations/state_before_request_shape_priority
        """
        emp = create_employer(legal_name="PrioCo", industry_code="111190",
                              contact_email="hr@prio.example")
        na = create_approved_assessment(emp["id"])
        agr = create_agreement(emp["id"], na["id"])  # stays DRAFT
        resp = api_client.revise_training_agreement(
            agr["id"], {"expected_agreement_version": agr["version"] + 7}, COORD
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestEmployerDormancySweep:
    def test_dormancy_then_reactivation_on_signature(self, api):
        """PRD §3.9: "the dormancy sweep moves an `ACTIVE` employer to
        `DORMANT` if no cohort of any of its agreements reached `CREDENTIALED`
        within the trailing 365 days and none of its agreements sits in
        `QUOTED`, `NEGOTIATING`, `SIGNED`, or `IN_DELIVERY`." PRD §3.1: "The
        employer's `status` later moves to `ACTIVE` on the first signature of
        any of its agreements, can fall to `DORMANT` through the clock sweep
        of §3.9, and returns to `ACTIVE` on any subsequent signature."

        Design: Corner/cross_cutting_layers/employer_dormancy_and_reactivation_via_clock
        """
        emp = create_employer(legal_name="DormCo", industry_code="111170",
                              contact_email="hr@dorm.example")
        na = create_approved_assessment(emp["id"])
        agr = create_signed_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT")
        validate_success(api_client.cancel_training_agreement(agr["id"], ADMIN))

        validate_success(api_client.set_clock({"to_iso8601": "2027-05-03T00:00:00Z"}, ADMIN))
        dormant = get_success_data(api_client.get_employer(emp["id"], COORD))
        assert dormant["status"] == "DORMANT"

        agr2 = create_quoted_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT",
                                       target_start_date="2027-07-01T00:00:00Z",
                                       max_cohorts=1)
        validate_success(
            api_client.sign_training_agreement(agr2["id"],
                                               make_employer_contact_headers(emp["id"]))
        )
        active = get_success_data(api_client.get_employer(emp["id"], COORD))
        assert active["status"] == "ACTIVE"


class TestImmediateConsistency:
    def test_launch_visible_immediately_across_roles(self, api):
        """PRD §3.6: "A launched cohort lands in `LAUNCHED`, and when it is
        the agreement's first launch the agreement moves from `SIGNED` to
        `IN_DELIVERY`." A read issued immediately after the mutation observes
        both.

        Design: Corner/consistency_model/immediate_visibility_of_mutation_in_same_read
        """
        ctx = setup_launched_cohort(num_participants=1, min_enrollment=1,
                                    participant_prefix="IM")
        coh = get_success_data(api_client.get_cohort(ctx["cohort"]["id"], GRANT))
        assert coh["delivery_status"] == "LAUNCHED"
        agr = get_success_data(api_client.get_training_agreement(ctx["agreement"]["id"], GRANT))
        assert agr["contract_status"] == "IN_DELIVERY"


class TestDeliveryModeMismatch:
    def test_cohort_mode_differing_from_agreement_rejected(self, api):
        """PRD §2.9: "Any inconsistency between a cohort's mode and its
        agreement's mode, or between a session's venue kind and its cohort's
        mode, is rejected with `ERR_DELIVERY_MODE_MISMATCH`."

        Design: Corner/validations/delivery_mode_mismatch_rejected
        """
        emp = create_employer(legal_name="ModeCo", industry_code="111184",
                              contact_email="hr@mode.example")
        na = create_approved_assessment(emp["id"])
        agr = create_signed_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT",
                                      delivery_mode="ON_SITE")
        ven = create_venue_for_mode("ON_CAMPUS", name="Campus Lab", capacity=20,
                                    hourly_cost_cents=5000)
        resp = api_client.create_cohort(
            agr["id"],
            {"delivery_mode": "ON_CAMPUS", "min_enrollment": 1,
             "start_date": "2026-06-15T00:00:00Z", "end_date": "2026-06-15T00:00:00Z",
             "venue_id": ven["id"]},
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_DELIVERY_MODE_MISMATCH)


class TestDuplicateParticipant:
    def test_duplicate_ref_same_cohort_rejected_other_cohort_ok(self, api):
        """PRD §3.4: "the same `external_employee_ref` may not be held by
        another `ENROLLED` participant of the same cohort (otherwise
        `ERR_DUPLICATE_PARTICIPANT`)" — uniqueness is per-cohort.

        Design: Corner/validations/duplicate_participant_ref_rejected
        """
        emp = create_employer(legal_name="DupCo", industry_code="111185",
                              contact_email="hr@dup.example")
        na = create_approved_assessment(emp["id"])
        agr = create_signed_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT",
                                      est_participant_count=4, max_cohorts=3)
        ca = create_cohort_under(agr["id"], min_enrollment=1)
        cb = create_cohort_under(agr["id"], min_enrollment=1,
                                 start_date="2026-06-22T00:00:00Z",
                                 end_date="2026-06-22T00:00:00Z")
        enroll_participants(ca["id"], ["E01"])

        resp = api_client.create_participant(
            ca["id"], {"external_employee_ref": "E01", "full_name": "E Duplicate"}, COORD
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PARTICIPANT)

        ok = validate_success(
            api_client.create_participant(
                cb["id"], {"external_employee_ref": "E01", "full_name": "E One"}, COORD
            ),
            201,
        )
        assert ok["external_employee_ref"] == "E01"


class TestVenueTurnoverBuffer:
    def _venue_with_booking(self, api):
        emp = create_employer(legal_name="Phi Co", industry_code="611430",
                              contact_email="hr@phi.example")
        na = create_approved_assessment(emp["id"])
        agr = create_signed_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT",
                                      delivery_mode="ON_CAMPUS", est_delivery_hours=3)
        ven = create_venue_for_mode("ON_CAMPUS", name="Phi Lab", capacity=30,
                                    hourly_cost_cents=5000)
        coh = create_cohort_under(agr["id"], delivery_mode="ON_CAMPUS",
                                  min_enrollment=1, venue_id=ven["id"])
        create_session_on(coh["id"], ven["id"],
                          "2026-06-15T09:00:00Z", "2026-06-15T10:00:00Z")
        return coh, ven

    def test_start_inside_buffer_rejected(self, api):
        """PRD §2.9: "A new session conflicts with an existing booking of the
        same venue when the new session's `start_at` falls before the existing
        booking's `end_at` plus the buffer; starting exactly at the end of the
        buffer — precisely thirty minutes after the previous end — is allowed.
        Conflicts are rejected with `ERR_VENUE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/venue_closed_interval_turnover_buffer
        """
        coh, ven = self._venue_with_booking(api)
        resp = api_client.create_session(
            coh["id"],
            {"venue_id": ven["id"], "start_at": "2026-06-15T10:15:00Z",
             "end_at": "2026-06-15T11:00:00Z"},
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_VENUE_OVERLAP)

    def test_start_exactly_at_buffer_end_allowed(self, api):
        """PRD §2.9: "starting exactly at the end of the buffer — precisely
        thirty minutes after the previous end — is allowed."

        Design: Difficulty/resource_temporal_overlap/venue_closed_interval_turnover_buffer
        """
        coh, ven = self._venue_with_booking(api)
        ok = validate_success(
            api_client.create_session(
                coh["id"],
                {"venue_id": ven["id"], "start_at": "2026-06-15T10:30:00Z",
                 "end_at": "2026-06-15T11:30:00Z"},
                COORD,
            ),
            201,
        )
        assert ok["status"] == "PLANNED"


class TestOutcomeReporting:
    def test_placement_pct_rounding_and_submit(self, api):
        """PRD §3.8: "the total completers are the sum of `completer_count`
        over the agreement's `CREDENTIALED` cohorts, and the percentage is one
        hundred times `completers_employed_90d` divided by that total, rounded
        half up to two decimal places."

        Design: Corner/calculations/placement_pct_precision_and_input_set
        """
        from test_helpers import setup_credentialed_cohort
        ctx = setup_credentialed_cohort(
            num_participants=4, min_enrollment=4,
            agreement_overrides={"pricing_model": "FLAT_COHORT",
                                 "est_participant_count": 4,
                                 "est_delivery_hours": 2,
                                 "max_cohorts": 2},
            venue_overrides={"capacity": 8},
            participant_prefix="P",
        )
        rep = validate_success(
            api_client.create_outcome_report(
                ctx["agreement"]["id"],
                {"completers_employed_90d": 3, "satisfaction_avg": 4.5,
                 "follow_on_opportunity_cents": 250000},
                COORD,
            ),
            201,
        )
        submitted = validate_success(api_client.submit_outcome_report(rep["id"], COORD))
        assert submitted["placement_pct"] == 75.00
        assert submitted["status"] == "SUBMITTED"
