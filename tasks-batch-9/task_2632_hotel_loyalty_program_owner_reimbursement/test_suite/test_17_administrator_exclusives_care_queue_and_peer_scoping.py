"""The operations only the programme administrator may perform, the one care-queue step the administrator itself is refused, and the wall between two properties and two members that each hold their own identity header.

Every refusal here is a role or ownership refusal, so each is checked for the
exact error the precedence order names — an owner reaching its own property
through an administrator-only endpoint is unauthorised, not an ownership
violation — and each is followed by proof that the refused call wrote nothing.
"""

from test_helpers import (
    ApiErrorId,
    assert_complaint,
    assert_hotel,
    assert_member,
    assert_purchase,
    factories as fac,
    fixtures as fx,
    make_admin_headers,
    make_auditor_headers,
    make_care_agent_headers,
    make_hotel_owner_headers,
    make_member_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _exclusive_arms_awaiting_the_administrator(api):
    """An ONBOARDING property with a rate plan, a member, and a pending purchase.

    Nothing here has been activated or settled: the two administrator-only
    transitions are left open so the other four roles can be turned away from
    them and the administrator can then walk them through.
    """
    hotel = fx.create_onboarding_hotel(
        api,
        name="Exclusive Arms",
        brand_code="EXA",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=90,
        trailing_12m_occupancy_pct=0.80,
        trailing_12m_adr_cents=25_000,
    )
    rate_plan = fx.add_rate_plan(api, hotel["id"], rate_code="BAR", rate_category="TRANSIENT")
    member = fx.enroll_member(
        api,
        email="ex1@example.com",
        full_name="Dario Conti",
        enrollment_date="2026-02-03",
    )
    purchase = fx.record_purchase(api, member["id"], 20_000, channel="DIRECT_PURCHASE")
    return {
        "hotel_id": hotel["id"],
        "rate_plan_id": rate_plan["id"],
        "member_id": member["id"],
        "purchase_id": purchase["id"],
        "owner_headers": make_hotel_owner_headers(hotel["id"]),
        "member_headers": make_member_headers(member["id"]),
    }


def _a_complaint_taken_under_review_by_the_administrator(api):
    """One complaint filed by the member and reviewed by the administrator.

    The administrator is a legitimate reviewer, so the complaint reaches
    UNDER_REVIEW without a care agent ever touching it. That makes the next
    step — asking the member for more information — the only thing in the
    queue, and it is reserved to the care agent alone.
    """
    member = fx.enroll_member(
        api,
        email="rq1@example.com",
        full_name="Yusuf Demir",
        enrollment_date="2026-02-05",
    )
    member_headers = make_member_headers(member["id"])
    complaint = fx.file_complaint(
        api,
        member["id"],
        subject_type="POINT_SHORTFALL",
        headers=member_headers,
    )
    reviewed = fx.review_complaint(api, complaint["id"], headers=make_admin_headers("op-admin-rq"))
    return {
        "member_id": member["id"],
        "member_headers": member_headers,
        "complaint_id": complaint["id"],
        "reviewed": reviewed,
        "care_headers": make_care_agent_headers("care-rq-01"),
        "admin_headers": make_admin_headers("op-admin-rq"),
    }


def _two_properties_and_two_members_that_must_not_touch(api):
    """Two ACTIVE properties and two members, each with its own identity header.

    Both entity-backed roles are represented twice over, so every ownership
    check has a legitimate caller and an illegitimate peer of the same role.
    """
    alpha = fx.create_active_hotel(
        api,
        name="Peer Alpha",
        brand_code="PEA",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=100,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    bravo = fx.create_active_hotel(
        api,
        name="Peer Bravo",
        brand_code="PEB",
        market_tier="SELECT",
        program_fee_pct=0.04,
        rooms_count=55,
        trailing_12m_occupancy_pct=0.65,
        trailing_12m_adr_cents=11_000,
    )
    one = fx.enroll_member(
        api,
        email="pe1@example.com",
        full_name="Member One",
        enrollment_date="2026-02-07",
    )
    two = fx.enroll_member(
        api,
        email="pe2@example.com",
        full_name="Member Two",
        enrollment_date="2026-02-08",
    )
    return {
        "alpha_id": alpha["hotel"]["id"],
        "bravo_id": bravo["hotel"]["id"],
        "alpha_headers": alpha["owner_headers"],
        "bravo_headers": bravo["owner_headers"],
        "one_id": one["id"],
        "two_id": two["id"],
        "one_headers": make_member_headers(one["id"]),
        "two_headers": make_member_headers(two["id"]),
    }


class TestAdministratorExclusivesAreRefusedToEveryOtherRole:
    """Four other roles, four different administrator-only operations."""

    def test_registering_a_property_is_refused_to_the_owner_the_care_agent_and_the_member(
        self, api
    ):
        """Property registration is administrator-only, so three well-formed callers are turned away.

        PRD: "**Role authorisation** — a role absent from the endpoint's list yields `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/program_administrator_exclusives_are_refused_to_every_other_role
        """
        bundle = _exclusive_arms_awaiting_the_administrator(api)
        payload = fac.create_hotel_payload(
            name="Owner's Own Brand",
            brand_code="OOB",
            market_tier="SELECT",
            program_fee_pct=0.05,
            rooms_count=20,
            trailing_12m_occupancy_pct=0.5,
            trailing_12m_adr_cents=9_000,
        )
        for label, headers in (
            ("hotel owner", bundle["owner_headers"]),
            ("care agent", make_care_agent_headers("care-ex-01")),
            ("member", bundle["member_headers"]),
        ):
            validate_error(
                api.create_hotel(payload, headers),
                ApiErrorId.ERR_UNAUTHORIZED,
            )

    def test_activating_its_own_property_is_still_unauthorized_for_the_owner(self, api):
        """Role authorisation is evaluated before resource ownership, so the owner's own property does not soften the refusal.

        PRD: "**Role authorisation** — a role absent from the endpoint's list yields `ERR_UNAUTHORIZED`. 3. **Resource ownership** — an owner or member reaching someone else's resource yields `ERR_FORBIDDEN_RESOURCE_OWNER`."

        Design: Corner/rbac/program_administrator_exclusives_are_refused_to_every_other_role
        """
        bundle = _exclusive_arms_awaiting_the_administrator(api)
        validate_error(
            api.activate_hotel(bundle["hotel_id"], bundle["owner_headers"]),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        still_onboarding = fx.read_hotel(api, bundle["hotel_id"])
        assert (
            still_onboarding["status"] == "ONBOARDING"
        ), "the refused activation must leave the property in ONBOARDING"
        assert (
            still_onboarding["version"] == 1
        ), "a refused activation must not increment the property's version"

    def test_publishing_award_pricing_is_refused_to_the_owner(self, api):
        """The property may draft blackout windows and register rate plans, but the award price window is the programme's to set.

        PRD: "A `HotelOwner` may post its own stays, record or deny elite benefits, complete or mark no-show on award stays at its own property, refresh its own performance figures, draft blackout windows, register rate plans and open a reimbursement batch"

        Design: Corner/rbac/program_administrator_exclusives_are_refused_to_every_other_role
        """
        bundle = _exclusive_arms_awaiting_the_administrator(api)
        pricing_payload = fac.create_redemption_pricing_payload(
            season="STANDARD",
            window_start_date="2026-09-01",
            window_end_date="2026-09-30",
            points_per_night=15_000,
            cash_copay_cents=0,
            min_tier_required="BASE",
            award_allotment_per_night=5,
        )
        validate_error(
            api.create_redemption_pricing(
                bundle["hotel_id"], pricing_payload, bundle["owner_headers"]
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        rows, meta = validate_paginated(
            api.list_redemption_pricing(
                make_admin_headers(), params={"hotel_id": bundle["hotel_id"]}
            )
        )
        assert meta["total_count"] == 0, "the refused publication must not have created a window"
        assert rows == [], "no award price window may exist at the property"

    def test_settling_a_purchase_is_refused_to_the_care_agent_and_the_member(self, api):
        """The care agent may record and refund a purchase but never settle one, and neither may the buyer.

        PRD: "A `MemberCareAgent` may grant goodwill points and refund a purchase but may never settle a purchase, release a batch, or adjudicate an escalated complaint."

        Design: Corner/rbac/program_administrator_exclusives_are_refused_to_every_other_role
        """
        bundle = _exclusive_arms_awaiting_the_administrator(api)
        for label, headers in (
            ("care agent", make_care_agent_headers("care-ex-01")),
            ("member", bundle["member_headers"]),
        ):
            validate_error(
                api.settle_point_purchase(bundle["purchase_id"], headers),
                ApiErrorId.ERR_UNAUTHORIZED,
            )
        rows, meta = validate_paginated(
            api.list_point_purchases(
                make_admin_headers(), params={"member_id": bundle["member_id"]}
            )
        )
        assert meta["total_count"] == 1, "the member must still hold exactly the one purchase"
        assert_purchase(
            rows[0],
            status="PENDING",
            cash_due_cents=25_000,
            bonus_points=0,
            volume_discount_pct=0.0,
            channel="DIRECT_PURCHASE",
            points_quantity=20_000,
        )
        assert_member(
            fx.read_member(api, bundle["member_id"]),
            point_balance=0,
            lifetime_points_earned=0,
            points_purchased_current_year=20_000,
        )

    def test_registering_a_partner_and_enrolling_a_member_are_refused_to_the_auditor(
        self, api
    ):
        """The auditor reads the books and may force a revaluation; every other state change from that role is refused.

        PRD: "the auditor is a read-only assurance role over the programme's books whose sole non-read capability is forcing a revaluation of the programme fund, and every other state-changing request from this role is refused with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/program_administrator_exclusives_are_refused_to_every_other_role
        """
        _exclusive_arms_awaiting_the_administrator(api)
        auditor = make_auditor_headers("op-auditor-ex")
        validate_error(
            api.create_partner(
                fac.create_partner_payload(
                    name="Auditor's Airline",
                    partner_type="AIRLINE",
                    points_cost_per_1000_cents=900,
                    monthly_cap_points=100_000,
                ),
                auditor,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        validate_error(
            api.create_member(
                fac.create_member_payload(
                    email="ex2@example.com",
                    full_name="Ana Ruiz",
                    enrollment_date="2026-02-04",
                ),
                auditor,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

    def test_the_unscoped_property_list_is_refused_to_the_owner(self, api):
        """Reading its own property is allowed; enumerating the programme's estate is not.

        PRD: "When the headers are well formed but the acting role does not appear in the target endpoint's authorised list"

        Design: Corner/rbac/program_administrator_exclusives_are_refused_to_every_other_role
        """
        bundle = _exclusive_arms_awaiting_the_administrator(api)
        validate_error(
            api.list_hotels(bundle["owner_headers"]),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        own = validate_success(
            api.get_hotel(bundle["hotel_id"], bundle["owner_headers"])
        )
        assert (
            own["id"] == bundle["hotel_id"]
        ), "the owner must still be able to read the property it owns"

    def test_the_administrator_completes_both_operations_the_others_were_refused(self, api):
        """The refusals were about the calling role alone: the same two calls succeed for the administrator.

        PRD: "Moves a property from ONBOARDING to ACTIVE, opening it for stay posting and award redemption."

        Design: Corner/rbac/program_administrator_exclusives_are_refused_to_every_other_role
        """
        bundle = _exclusive_arms_awaiting_the_administrator(api)
        activated = validate_success(
            api.activate_hotel(bundle["hotel_id"], make_admin_headers("op-admin-ex"))
        )
        assert_hotel(
            activated,
            status="ACTIVE",
            fee_ledger_cents=0,
            reimbursement_owed_cents=0,
            benefit_recovery_owed_cents=0,
            benefit_denial_count=0,
            blackout_days_used=0,
            version=2,
        )
        settled = validate_success(
            api.settle_point_purchase(
                bundle["purchase_id"], make_admin_headers("op-admin-ex")
            )
        )
        assert_purchase(
            settled,
            status="SETTLED",
            cash_due_cents=25_000,
            bonus_points=0,
            volume_discount_pct=0.0,
            channel="DIRECT_PURCHASE",
            points_quantity=20_000,
        )
        assert_member(
            fx.read_member(api, bundle["member_id"]),
            point_balance=20_000,
            lifetime_points_earned=20_000,
            points_purchased_current_year=20_000,
        )

    def test_none_of_the_refused_calls_created_a_row(self, api):
        """After every refusal the programme still holds exactly the one property, the one member and no partner.

        PRD: "Partner records are visible only to the `ProgramAdministrator` and the `ProgramAuditor`; neither a property nor a member can enumerate the programme's wholesale price list."

        Design: Corner/rbac/program_administrator_exclusives_are_refused_to_every_other_role
        """
        bundle = _exclusive_arms_awaiting_the_administrator(api)
        admin = make_admin_headers("op-admin-ex")
        api.create_hotel(
            fac.create_hotel_payload(name="Owner's Own Brand", brand_code="OOB"),
            bundle["owner_headers"],
        )
        api.create_partner(
            fac.create_partner_payload(name="Auditor's Airline"),
            make_auditor_headers("op-auditor-ex"),
        )
        api.create_member(
            fac.create_member_payload(email="ex2@example.com", full_name="Ana Ruiz"),
            make_auditor_headers("op-auditor-ex"),
        )
        _, hotel_meta = validate_paginated(api.list_hotels(admin))
        assert hotel_meta["total_count"] == 1, "the owner's refused registration must not persist"
        _, partner_meta = validate_paginated(api.list_partners(admin))
        assert partner_meta["total_count"] == 0, "the auditor's refused partner must not persist"
        _, member_meta = validate_paginated(api.list_members(admin))
        assert member_meta["total_count"] == 1, "the auditor's refused enrolment must not persist"


class TestRequestingInformationBelongsToTheCareAgentAlone:
    """The one step the administrator cannot take, and the one the care agent cannot."""

    def test_requesting_further_information_is_refused_to_the_administrator(self, api):
        """The administrator may file, review, resolve and adjudicate, but it does not run the care queue.

        PRD: "Requesting further information on a complaint is reserved to `MemberCareAgent` alone: the programme administrator adjudicates escalations and does not run the care queue."

        Design: Corner/rbac/care_agents_request_info_is_refused_even_to_the_administrator
        """
        bundle = _a_complaint_taken_under_review_by_the_administrator(api)
        assert (
            bundle["reviewed"]["status"] == "UNDER_REVIEW"
        ), "the administrator is a legitimate reviewer, so the complaint must be UNDER_REVIEW"
        validate_error(
            api.request_complaint_info(bundle["complaint_id"], bundle["admin_headers"]),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        unchanged = fx.read_complaint(api, bundle["complaint_id"])
        assert_complaint(
            unchanged,
            status="UNDER_REVIEW",
            info_request_count=0,
            subject_type="POINT_SHORTFALL",
        )

    def test_the_care_agent_may_request_information_and_the_counter_moves(self, api):
        """The same call from the reserved role is accepted and the complaint waits on the member.

        PRD: "Sends the complaint back to the member for more information. Permitted at most twice per complaint."

        Design: Corner/rbac/care_agents_request_info_is_refused_even_to_the_administrator
        """
        bundle = _a_complaint_taken_under_review_by_the_administrator(api)
        requested = validate_success(
            api.request_complaint_info(bundle["complaint_id"], bundle["care_headers"])
        )
        assert_complaint(
            requested,
            status="INFO_REQUESTED",
            info_request_count=1,
            subject_type="POINT_SHORTFALL",
        )
        assert (
            requested["adjudication_outcome"] is None
        ), "asking for information must not adjudicate anything"

    def test_adjudicating_is_refused_to_the_care_agent_on_the_role_not_the_state(self, api):
        """The complaint is nowhere near ESCALATED, yet the refusal the care agent earns is the role refusal.

        PRD: "**Role authorisation** — a role absent from the endpoint's list yields `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/care_agents_request_info_is_refused_even_to_the_administrator
        """
        bundle = _a_complaint_taken_under_review_by_the_administrator(api)
        validate_error(
            api.adjudicate_complaint(
                bundle["complaint_id"],
                fac.adjudicate_complaint_payload(adjudication_outcome="DELIVERY_ORDERED"),
                bundle["care_headers"],
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

    def test_the_member_answers_and_the_complaint_returns_under_review(self, api):
        """Providing the information is the member's own step, and it hands the complaint back to the queue.

        PRD: "Returns the member's additional information and puts the complaint back under review."

        Design: Corner/rbac/care_agents_request_info_is_refused_even_to_the_administrator
        """
        bundle = _a_complaint_taken_under_review_by_the_administrator(api)
        validate_success(
            api.request_complaint_info(bundle["complaint_id"], bundle["care_headers"])
        )
        answered = validate_success(
            api.provide_complaint_info(
                bundle["complaint_id"],
                fac.provide_complaint_info_payload(),
                bundle["member_headers"],
            )
        )
        assert_complaint(
            answered,
            status="UNDER_REVIEW",
            info_request_count=1,
            subject_type="POINT_SHORTFALL",
        )

    def test_neither_refusal_left_a_trace_on_the_complaint(self, api):
        """After the administrator's refused request and the care agent's refused adjudication the complaint is exactly as reviewed.

        PRD: "Programme adjudication of an escalated complaint: either orders the benefit delivered at the property's cost or upholds the denial for good."

        Design: Corner/rbac/care_agents_request_info_is_refused_even_to_the_administrator
        """
        bundle = _a_complaint_taken_under_review_by_the_administrator(api)
        api.request_complaint_info(bundle["complaint_id"], bundle["admin_headers"])
        api.adjudicate_complaint(
            bundle["complaint_id"],
            fac.adjudicate_complaint_payload(adjudication_outcome="DENIAL_UPHELD"),
            bundle["care_headers"],
        )
        final = fx.read_complaint(api, bundle["complaint_id"])
        assert_complaint(
            final,
            status="UNDER_REVIEW",
            info_request_count=0,
            goodwill_points_granted=0,
            subject_type="POINT_SHORTFALL",
        )
        assert (
            final["adjudication_outcome"] is None
        ), "the refused adjudication must not have recorded an outcome"
        assert final["resolution"] is None, "no resolution text may have been written"
        assert (
            final["version"] == bundle["reviewed"]["version"]
        ), "two refused calls must not increment the complaint's version"


class TestEntityBackedRolesCannotReachAcrossToAPeersRows:
    """Both entity-backed roles are held to the single entity their header names."""

    def test_an_owner_cannot_register_a_rate_plan_at_a_peers_property(self, api):
        """The property is named in the path, so the ownership comparison is made directly against the acting hotel.

        PRD: "When `X-User-Role` is `HotelOwner`, `X-User-ID` is the `id` of the acting `Hotel`; ownership checks on any resource that references a `Hotel` compare the resource's property foreign key to `X-User-ID`"

        Design: Corner/rbac/entity_backed_roles_cannot_reach_across_to_a_peers_rows
        """
        bundle = _two_properties_and_two_members_that_must_not_touch(api)
        validate_error(
            api.create_rate_plan(
                bundle["bravo_id"],
                fac.create_rate_plan_payload(
                    rate_code="CORP", rate_category="CORPORATE_NEGOTIATED"
                ),
                bundle["alpha_headers"],
            ),
            ApiErrorId.ERR_FORBIDDEN_RESOURCE_OWNER,
        )

    def test_an_owner_cannot_read_a_peers_property(self, api):
        """Reading a property is open to the owner role, which makes this refusal an ownership refusal rather than a role one.

        PRD: "In either case, a request that reaches a property or a member other than the one `X-User-ID` names is rejected with `ERR_FORBIDDEN_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/entity_backed_roles_cannot_reach_across_to_a_peers_rows
        """
        bundle = _two_properties_and_two_members_that_must_not_touch(api)
        validate_error(
            api.get_hotel(bundle["bravo_id"], bundle["alpha_headers"]),
            ApiErrorId.ERR_FORBIDDEN_RESOURCE_OWNER,
        )
        own = validate_success(api.get_hotel(bundle["alpha_id"], bundle["alpha_headers"]))
        assert own["name"] == "Peer Alpha", "the owner must still read its own property"

    def test_a_member_cannot_buy_points_for_another_member(self, api):
        """The member reference sits in the request body, and the ownership comparison reaches it there.

        PRD: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's member foreign key to `X-User-ID`"

        Design: Corner/rbac/entity_backed_roles_cannot_reach_across_to_a_peers_rows
        """
        bundle = _two_properties_and_two_members_that_must_not_touch(api)
        validate_error(
            api.create_point_purchase(
                fac.create_point_purchase_payload(
                    bundle["two_id"], points_quantity=5_000, channel="DIRECT_PURCHASE"
                ),
                bundle["one_headers"],
            ),
            ApiErrorId.ERR_FORBIDDEN_RESOURCE_OWNER,
        )

    def test_a_member_cannot_read_another_member(self, api):
        """A member reads its own balance and nobody else's.

        PRD: "**Resource ownership** — an owner or member reaching someone else's resource yields `ERR_FORBIDDEN_RESOURCE_OWNER`."

        Design: Corner/rbac/entity_backed_roles_cannot_reach_across_to_a_peers_rows
        """
        bundle = _two_properties_and_two_members_that_must_not_touch(api)
        validate_error(
            api.get_member(bundle["two_id"], bundle["one_headers"]),
            ApiErrorId.ERR_FORBIDDEN_RESOURCE_OWNER,
        )
        own = validate_success(api.get_member(bundle["one_id"], bundle["one_headers"]))
        assert own["full_name"] == "Member One", "the member must still read its own record"

    def test_the_same_two_calls_inside_their_own_scope_are_accepted(self, api):
        """Neither call is forbidden in itself: each succeeds the moment it addresses the caller's own entity.

        PRD: "Registers a rate plan at the property, declaring its rate category and whether stays on it qualify for points."

        Design: Corner/rbac/entity_backed_roles_cannot_reach_across_to_a_peers_rows
        """
        bundle = _two_properties_and_two_members_that_must_not_touch(api)
        own_plan = validate_success(
            api.create_rate_plan(
                bundle["alpha_id"],
                fac.create_rate_plan_payload(
                    rate_code="CORP", rate_category="CORPORATE_NEGOTIATED"
                ),
                bundle["alpha_headers"],
            ),
            expected_status=201,
        )
        assert own_plan["hotel_id"] == bundle["alpha_id"], "the plan must belong to the caller's own property"
        assert own_plan["rate_code"] == "CORP", "the submitted rate code must be stored"
        own_purchase = validate_success(
            api.create_point_purchase(
                fac.create_point_purchase_payload(
                    bundle["one_id"], points_quantity=5_000, channel="DIRECT_PURCHASE"
                ),
                bundle["one_headers"],
            ),
            expected_status=201,
        )
        assert_purchase(
            own_purchase,
            status="PENDING",
            cash_due_cents=6_250,
            bonus_points=0,
            volume_discount_pct=0.0,
            channel="DIRECT_PURCHASE",
            points_quantity=5_000,
        )

    def test_the_cross_scope_refusals_wrote_nothing_to_the_peer(self, api):
        """The peer property still carries only its original plan and the peer member still has no purchase at all.

        PRD: "Records a co-brand card point purchase, a direct member purchase or a wholesale partner point sale, priced by the volume-tier schedule."

        Design: Corner/rbac/entity_backed_roles_cannot_reach_across_to_a_peers_rows
        """
        bundle = _two_properties_and_two_members_that_must_not_touch(api)
        api.create_rate_plan(
            bundle["bravo_id"],
            fac.create_rate_plan_payload(rate_code="CORP", rate_category="CORPORATE_NEGOTIATED"),
            bundle["alpha_headers"],
        )
        api.create_point_purchase(
            fac.create_point_purchase_payload(
                bundle["two_id"], points_quantity=5_000, channel="DIRECT_PURCHASE"
            ),
            bundle["one_headers"],
        )
        admin = make_admin_headers()
        _, plan_meta = validate_paginated(
            api.list_rate_plans(admin, params={"hotel_id": bundle["bravo_id"]})
        )
        assert plan_meta["total_count"] == 1, "the peer property must still hold only its own rate plan"
        _, purchase_meta = validate_paginated(
            api.list_point_purchases(admin, params={"member_id": bundle["two_id"]})
        )
        assert purchase_meta["total_count"] == 0, "the peer member must hold no purchase"
        assert_member(
            fx.read_member(api, bundle["two_id"]),
            elite_tier="BASE",
            point_balance=0,
            points_purchased_current_year=0,
            version=1,
        )
