"""RBAC, segregation of duties, ownership, authentication, validation priority
ordering, and OCC stale-version rejections."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_gift_officer_headers, build_user_headers,
    create_prospect, create_fundraiser, rate_prospect, assign_prospect,
    move_prospect, get_prospect, get_fundraiser, get_proposal,
    create_proposal_for, create_submitted_proposal, setup_active_pledge,
    create_assessment_payload, create_assignment_payload,
    create_campaign_payload, create_fundraiser_payload, create_write_off_payload,
    create_gift_payment_payload, create_proposal_payload,
    setup_rated_assigned_prospect,
    assert_iso_instant_equal,
)

RES = TEST_USERS["researcher_headers"]
DIR = TEST_USERS["director_headers"]
VP = TEST_USERS["vp_headers"]
DRO = TEST_USERS["dro_headers"]
FIN = TEST_USERS["finance_headers"]

UNKNOWN = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestAuthentication:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming their operational
        capacity. A request missing either header, or whose `X-User-Role` does
        not name one of the declared roles, is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        resp = api.get_prospect(UNKNOWN, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleAuthorization:
    def test_exclusive_operation_denied_across_roles(self, api):
        """PRD §2.1: "Each endpoint declares which roles may invoke it (see §4);
        a caller whose role is not listed for that endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/exclusive_operation_denied_across_roles
        """
        f = create_fundraiser()
        officer = make_gift_officer_headers(f["id"])

        # Researcher creating a campaign.
        validate_error(
            api.create_campaign(create_campaign_payload(), RES),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        )
        # GiftOfficer executing an agreement.
        validate_error(
            api.execute_agreement(UNKNOWN, officer),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        )
        # FinanceSteward sending a reminder.
        validate_error(
            api.remind_installment(UNKNOWN, FIN),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        )
        # VPAdvancement recording a payment.
        validate_error(
            api.create_gift_payment(
                create_gift_payment_payload(UNKNOWN, amount_cents=100, payment_method="CHECK"), VP,
            ),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        )
        # AdvancementDirector creating a fundraiser.
        validate_error(
            api.create_fundraiser(
                create_fundraiser_payload(display_name="Officer Two", email="o2@x.edu",
                                          max_prospect_count=5, max_open_ask_cents=1000),
                DIR,
            ),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        )

    def test_shared_get_endpoints_allow_all_roles(self, api):
        """PRD §4: "Get a prospect including giving aggregates and recognition
        society | All roles"."

        Design: Corner/rbac/shared_get_endpoints_allow_all_roles
        """
        p = create_prospect()
        officer_headers = build_user_headers("officer-placeholder", "GiftOfficer")
        expected_id = p["id"]
        for headers in [officer_headers, RES, DIR, VP, DRO, FIN]:
            data = validate_success(api.get_prospect(expected_id, headers))
            assert data["id"] == expected_id
            assert data["full_name"] == p["full_name"]


class TestValidationPriority:
    def test_role_check_precedes_schema_validation(self, api):
        """PRD §2.10: "Every request is validated against an ordered chain of
        checks, and **the first failing check wins**: once an earlier check
        fires, later checks are not evaluated, so the returned error is always
        the highest-priority failure present."
        PRD §2.10: "2. **Role authorization.** The acting role is listed for the
        endpoint; otherwise `ERR_UNAUTHORIZED_ROLE`."
        PRD §2.10: "3. **Request shape.** The body is well-formed: required
        fields present, types correct, enum values within their declared sets,
        integer money fields positive, unknown fields rejected, and split
        structures well-formed; otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/validations/role_check_precedes_schema_validation
        """
        resp = api.create_campaign({"name": "Bad"}, RES)  # missing goal_cents etc.
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_existence_check_precedes_ownership(self, api):
        """PRD §2.10: "Every request is validated against an ordered chain of
        checks, and **the first failing check wins**: once an earlier check
        fires, later checks are not evaluated, so the returned error is always
        the highest-priority failure present."
        PRD §2.10: "4. **Path and reference existence.** Identifiers resolve left
        to right per §2.8; otherwise the corresponding 404."
        PRD §2.10: "5. **Portfolio ownership.** Where the acting `GiftOfficer`
        must own the prospect, `X-User-ID` must equal the `fundraiser_id` of an
        `ACTIVE` assignment for that prospect; otherwise
        `ERR_NOT_PROSPECT_OWNER`."

        Design: Corner/validations/existence_check_precedes_ownership
        """
        f = create_fundraiser()
        officer = make_gift_officer_headers(f["id"])
        resp = api.move_prospect(UNKNOWN, {"target_stage": "CULTIVATION"}, officer)
        validate_error(resp, ApiErrorId.ERR_PROSPECT_NOT_FOUND)

    def test_sod_check_precedes_state_check(self, api):
        """PRD §2.10: "Every request is validated against an ordered chain of
        checks, and **the first failing check wins**: once an earlier check
        fires, later checks are not evaluated, so the returned error is always
        the highest-priority failure present."
        PRD §2.10: "6. **Segregation of duties.** The reviewer or decider differs
        from the resource's originator; otherwise `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.10: "8. **Entity state preconditions.** The target entity is in a
        state that permits the operation per its state machine."

        Design: Corner/validations/sod_check_precedes_state_check
        """
        p = create_prospect()
        # res-1 creates the assessment; dir-1 approves it (now APPROVED).
        a = rate_prospect(p["id"])
        # res-1 (the creator) attempts a review under the director role: both
        # segregation and state fail; segregation fires first.
        resp = api.review_assessment(a["id"], {"decision": "REJECT"},
                                     build_user_headers("res-1", "AdvancementDirector"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestOwnership:
    def test_officer_cannot_act_on_unassigned_prospect(self, api):
        """PRD §3.3: "Every move is performed by a `GiftOfficer` who must hold an
        `ACTIVE` assignment for the prospect — `X-User-ID` equal to the
        assignment's `fundraiser_id` — or the request fails with
        `ERR_NOT_PROSPECT_OWNER`."

        Design: Corner/rbac/officer_cannot_act_on_unassigned_prospect
        """
        f1 = create_fundraiser()
        f2 = create_fundraiser(display_name="Officer Two", email="o2@x.edu")
        p = create_prospect()
        assign_prospect(f1["id"], p["id"])

        officer2 = make_gift_officer_headers(f2["id"])
        resp = api.move_prospect(p["id"], {"target_stage": "CULTIVATION"}, officer2)
        validate_error(resp, ApiErrorId.ERR_NOT_PROSPECT_OWNER)
        assert get_prospect(p["id"])["moves_stage"] == "QUALIFICATION"


class TestSegregationOfDuties:
    def test_assessment_self_review_denied(self, api):
        """PRD §3.2: "the reviewer's `X-User-ID` must differ from the
        assessment's `created_by` (otherwise `ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/rbac/assessment_self_review_denied
        """
        p = create_prospect()
        resp = api.create_assessment(p["id"], create_assessment_payload(), RES)
        a = validate_success(resp, expected_status=201)

        # res-1 created it; the same operator id reviews under the director role.
        resp = api.review_assessment(
            a["id"], {"decision": "APPROVE"},
            build_user_headers("res-1", "AdvancementDirector"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        rows, _ = validate_paginated(api.list_prospect_assessments(p["id"], RES))
        assert rows[0]["status"] == "SUBMITTED"
        assert rows[0]["reviewed_by"] is None

    def test_proposal_self_review_denied(self, api):
        """PRD §3.4: "The reviewer must differ from `submitted_by` (otherwise
        `ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/rbac/proposal_self_review_denied
        """
        f, p, _ = setup_rated_assigned_prospect(move_to="CULTIVATION")
        prop = create_submitted_proposal(p["id"], f["id"], 1000000)

        # The submitting officer's id reviews under the director role.
        resp = api.review_proposal(
            prop["id"], {"decision": "APPROVE"},
            build_user_headers(f["id"], "AdvancementDirector"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_proposal(prop["id"])["status"] == "UNDER_REVIEW"

    def test_writeoff_self_review_denied(self, api):
        """PRD §3.6: "is reviewable by an `AdvancementDirector` — who must differ
        from `requested_by` (otherwise `ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/rbac/writeoff_self_review_denied
        """
        ctx = setup_active_pledge(100, installment_count=1, frequency="ANNUAL",
                                  first_due_date="2026-12-01T00:00:00Z")
        resp = api.create_write_off(
            ctx["pledge"]["id"], create_write_off_payload(amount_cents=50), FIN,
        )
        wo = validate_success(resp, expected_status=201)

        # fin-1 requested it; the same id reviews under the director role.
        resp = api.review_write_off(
            wo["id"], {"decision": "APPROVE"},
            build_user_headers("fin-1", "AdvancementDirector"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        rows, _ = validate_paginated(api.list_write_offs(ctx["pledge"]["id"], FIN))
        assert rows[0]["status"] == "PENDING"


class TestOptimisticConcurrency:
    def test_occ_proposal_create_stale_version_rejected(self, api):
        """PRD §2.7: "creating a proposal requires the request body to carry
        `expected_prospect_version`, a non-optional field holding the `version`
        of the target prospect as the client last read it. If the prospect's
        current `version` differs — because, for instance, a new assessment
        approval changed the capacity band, or a moves-stage change landed since
        the client read the record — the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.4: "A new proposal starts as `DRAFT`, and its creation advances
        the prospect's `version` by 1."

        Design: Corner/cross_cutting_layers/occ_proposal_create_stale_version_rejected
        """
        f, p, _ = setup_rated_assigned_prospect(move_to="CULTIVATION")
        officer = make_gift_officer_headers(f["id"])
        p_now = get_prospect(p["id"], officer)

        prop1 = api.create_proposal(
            create_proposal_payload(p["id"], p_now["version"], designation_purpose="First"),
            officer,
        )
        validate_success(prop1, expected_status=201)

        # Replay the same captured version: the first create advanced it.
        resp = api.create_proposal(
            create_proposal_payload(p["id"], p_now["version"], ask_amount_cents=2000000,
                                    designation_purpose="Stale second"),
            officer,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_occ_assignment_create_stale_version_rejected(self, api):
        """PRD §2.7: "creating a portfolio assignment requires the request body
        to carry `expected_fundraiser_version`, a non-optional field holding the
        `version` of the target fundraiser as the client last read it. If another
        writer has advanced the fundraiser's version since that read — for
        example by assigning or releasing a prospect, which mutates
        `current_prospect_count` and `current_open_ask_cents` — the create is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_assignment_create_stale_version_rejected
        """
        f = create_fundraiser()
        p1 = create_prospect(full_name="P1", contact_email="p1@x.com")
        p2 = create_prospect(full_name="P2", contact_email="p2@x.com")

        resp = api.create_assignment(
            f["id"], create_assignment_payload(p1["id"], f["version"]), DIR,
        )
        validate_success(resp, expected_status=201)

        # Replay the creation-time version: the first assignment advanced it.
        resp = api.create_assignment(
            f["id"], create_assignment_payload(p2["id"], f["version"]), DIR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        assert get_fundraiser(f["id"])["current_prospect_count"] == 1

    def test_version_increments_once_per_mutation(self, api):
        """PRD §2.4: "`version` (integer): a system-managed integer that
        increments by exactly 1 on every mutation, including mutations caused by
        system-driven sweeps, cascades from another resource, and recomputation
        of derived counters."

        Design: Corner/cross_cutting_layers/version_increments_once_per_mutation
        """
        f, p, _ = setup_rated_assigned_prospect(move_to="CULTIVATION")
        officer = make_gift_officer_headers(f["id"])
        prop = create_proposal_for(p["id"], f["id"], 1000000)
        assert prop["version"] == 1

        d1 = validate_success(api.patch_proposal(prop["id"], {"designation_purpose": "Programs v2"}, officer))
        assert d1["version"] == 2
        d2 = validate_success(api.patch_proposal(prop["id"], {"ask_amount_cents": 1500000}, officer))
        assert d2["version"] == 3
        assert d2["updated_at"] >= d1["updated_at"]


class TestClock:
    def test_clock_set_echo_and_monotonic_guard(self, api):
        """PRD §2.5: "An administrator capability, available to
        `AdvancementDirector` and `VPAdvancement`, advances the logical clock to
        a supplied `to_iso8601` instant and returns the resulting `current_utc`.
        The target must be strictly later than the current logical time; a target
        equal to or earlier than the current logical time is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/endpoints/clock_set_echo_and_monotonic_guard
        """
        resp = api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, DIR)
        data = validate_success(resp)
        assert_iso_instant_equal(data["current_utc"], "2026-08-02T00:00:00Z")

        # Not strictly later than the current logical time.
        resp = api.set_clock({"to_iso8601": "2026-08-01T12:00:00Z"}, DIR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestNotFoundResolution:
    def test_not_found_errors_across_entities(self, api):
        """PRD §2.8: "The not-found errors are resource-specific:
        `ERR_PROSPECT_NOT_FOUND` for an unresolvable prospect segment or a
        `prospect_id` body reference, `ERR_FUNDRAISER_NOT_FOUND` for a fundraiser
        segment, `ERR_PROPOSAL_NOT_FOUND` for a proposal segment,
        `ERR_AGREEMENT_NOT_FOUND` for an agreement segment or an `agreement_id`
        body reference, `ERR_PLEDGE_NOT_FOUND` for a pledge segment or a
        `pledge_id` body reference, `ERR_PAYMENT_NOT_FOUND` for a payment
        segment, `ERR_FUND_NOT_FOUND` for a fund segment or a `fund_id` body
        reference, and `ERR_CAMPAIGN_NOT_FOUND` for a campaign segment or a
        `campaign_id` body reference. All other addressable resources —
        assessments, assignments, installments, write-offs, stewardship reports,
        naming opportunities, and recognition societies — report
        `ERR_RESOURCE_NOT_FOUND` when their identifier does not resolve."

        Design: Corner/errors/not_found_errors_across_entities
        """
        f = create_fundraiser()
        officer = make_gift_officer_headers(f["id"])

        validate_error(api.review_assessment(UNKNOWN, {"decision": "APPROVE"}, DIR),
                       ApiErrorId.ERR_RESOURCE_NOT_FOUND)
        validate_error(api.get_fundraiser(UNKNOWN, VP),
                       ApiErrorId.ERR_FUNDRAISER_NOT_FOUND)
        validate_error(api.review_proposal(UNKNOWN, {"decision": "APPROVE"}, VP),
                       ApiErrorId.ERR_PROPOSAL_NOT_FOUND)
        validate_error(api.disburse_fund(UNKNOWN, {"amount_cents": 1, "purpose_note": "probe"}, FIN),
                       ApiErrorId.ERR_FUND_NOT_FOUND)
        validate_error(api.reverse_gift_payment(UNKNOWN, FIN),
                       ApiErrorId.ERR_PAYMENT_NOT_FOUND)
        validate_error(api.activate_campaign(UNKNOWN, VP),
                       ApiErrorId.ERR_CAMPAIGN_NOT_FOUND)
        validate_error(api.present_agreement(UNKNOWN, officer),
                       ApiErrorId.ERR_AGREEMENT_NOT_FOUND)
        validate_error(api.create_write_off(UNKNOWN, {"amount_cents": 1, "reason": "OTHER"}, FIN),
                       ApiErrorId.ERR_PLEDGE_NOT_FOUND)


class TestAssignmentUniqueness:
    def test_prospect_double_assignment_rejected(self, api):
        """PRD §3.1: "Creation is refused when the fundraiser is not `ACTIVE`
        (`ERR_FUNDRAISER_INACTIVE`), when the prospect already has an `ACTIVE`
        assignment to any fundraiser (`ERR_PROSPECT_ALREADY_ASSIGNED`)."

        Design: Corner/validations/prospect_double_assignment_rejected
        """
        f1 = create_fundraiser()
        f2 = create_fundraiser(display_name="Officer Two", email="o2@x.edu")
        p = create_prospect()
        assign_prospect(f1["id"], p["id"])

        f2_now = get_fundraiser(f2["id"])
        resp = api.create_assignment(
            f2["id"], create_assignment_payload(p["id"], f2_now["version"]), DIR,
        )
        validate_error(resp, ApiErrorId.ERR_PROSPECT_ALREADY_ASSIGNED)

        rows, meta = validate_paginated(
            api.list_prospect_assignments(p["id"], DIR, params={"status": "ACTIVE"}),
        )
        assert len(rows) == 1 and meta["total_count"] == 1
