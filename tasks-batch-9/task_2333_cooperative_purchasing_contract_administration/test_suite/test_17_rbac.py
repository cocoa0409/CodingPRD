"""Role-based access control: the five roles, the two entity bindings and the duty split."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_INTAKE,
    ADMIN_REVIEW,
    ADMIN_REVIEW_ID,
    ApiErrorId,
    AUDITOR,
    OFFICER_AWARDER,
    OFFICER_AWARDER_ID,
    OFFICER_CONDUCTOR,
    OFFICER_CONDUCTOR_ID,
    assert_cents,
    assert_score,
    make_member_headers,
    make_supplier_headers,
)
from test_helpers.constants import SKU_DISPENSER, SKU_PAPER
from test_helpers.factories import (
    OK_RULE,
    TX_RULE,
    complaint_payload,
    contract_usage_payload,
    line_item_payload,
    member_agency_payload,
    solicitation_payload,
    state_law_rule_payload,
    usage_report_payload,
)
from test_helpers.fixtures import (
    create_state_law_rule,
    read_analysis,
    read_complaint,
    read_contract,
    read_line_item,
    read_member,
    read_solicitation,
    read_supplier,
    read_usage,
    record_usage,
    setup_active_contract,
    setup_authorised_member,
    setup_evaluated_solicitation,
)

AUSTIN = dict(
    legal_name="City of Austin",
    state_code="TX",
    member_category="CITY",
    annual_spend_ceiling_cents=5000000,
    governing_body_resolution_number="RES-2026-208",
)
TULSA = dict(
    legal_name="Tulsa Public Schools",
    state_code="OK",
    member_category="K12_DISTRICT",
    annual_spend_ceiling_cents=3000000,
    governing_body_resolution_number="RES-2026-401",
)
PAPER_LINE = dict(
    sku=SKU_PAPER,
    item_description="Copy paper, letter, 92 bright, case of 10 reams",
    unit_of_measure="CASE",
    base_unit_price_cents=4500,
    price_floor_cents=3800,
)
PAPER_SOLICITATION_NUMBER = "COOP-2026-021"
DISPENSER_ORDER_TOTAL_CENTS = 12750


def _authorised_world(api):
    """One ACTIVE contract with a live dispenser line and one authorised member."""
    world = setup_active_contract(api)
    member, analysis = setup_authorised_member(api, world)
    world["member"] = member
    world["analysis"] = analysis
    world["line"] = world["lines"][SKU_DISPENSER]
    return world


def _two_member_world(api):
    """The same contract with two authorised members, each on its own opinion."""
    world = _authorised_world(api)
    austin, austin_analysis = setup_authorised_member(api, world, **AUSTIN)
    world["austin"] = austin
    world["austin_analysis"] = austin_analysis
    return world


def _scored_world(api):
    """A solicitation in EVALUATION whose two responses are RESPONSIVE and scored."""
    world = setup_evaluated_solicitation(api)
    for key, score in (("response_a", 88.00), ("response_b", 95.00)):
        world[key] = validate_success(
            api.response_review(
                world[key]["id"],
                {"action": "MARK_RESPONSIVE", "technical_score": score},
                OFFICER_CONDUCTOR,
            )
        )
    return world


def _lifecycle(api, solicitation_id, action, headers):
    return api.solicitation_lifecycle(solicitation_id, {"action": action}, headers)


def _usage_payload(world, member=None, analysis=None):
    member = member or world["member"]
    analysis = analysis or world["analysis"]
    return contract_usage_payload(
        world["contract"]["id"], member["id"], world["line"]["id"], analysis["id"]
    )


class TestMemberAuditorReadOnlySurface:
    def test_01_the_auditor_reads_every_route_needed_to_rebuild_an_audit_file(self, api):
        """PRD §2.1: "`MemberAuditor` is strictly read-only: it holds no write operation anywhere
        in the API, and every `GET` endpoint in the system admits it — including the responses
        list of a solicitation, the usage-report list of a contract, and the price-quote
        computation." PRD §2.9: "Entity-backed actor scope — `ERR_ACTOR_SCOPE_MISMATCH`, 403, on
        every write endpoint whose role list contains `SupplierRepresentative` or
        `MemberRepresentative`: `POST /coop/solicitation-responses`,
        `POST /coop/solicitation-responses/{id}/submission`, `POST /coop/usage-reports`,
        `POST /coop/usage-reports/{id}/submission`,
        `POST /coop/usage-reports/{id}/fee-remittance`, `POST /coop/contract-amendments`,
        `POST /coop/contract-amendments/{id}/withdrawal`, `POST /coop/complaints/{id}/appeal`,
        `POST /coop/piggyback-analyses`, `POST /coop/contract-usages`,
        `POST /coop/contract-usages/{id}/disposition` and `POST /coop/complaints`. Read endpoints
        are never scope-checked."

        Design: Corner/RBAC/member_auditor_may_read_the_whole_audit_file_and_write_nothing
        """
        world = _authorised_world(api)

        responses = api.list_responses_of_solicitation(world["solicitation"]["id"], AUDITOR)
        reports = api.list_usage_reports_of_contract(world["contract"]["id"], AUDITOR)
        analyses = api.list_piggyback_analyses(
            AUDITOR, {"contract_id": world["contract"]["id"]}
        )

        response_rows, response_meta = validate_paginated(responses)
        assert response_meta["total_count"] == 2
        assert {row["status"] for row in response_rows} == {"RESPONSIVE"}
        _, report_meta = validate_paginated(reports)
        assert report_meta["total_count"] == 0
        analysis_rows, analysis_meta = validate_paginated(analyses)
        assert analysis_meta["total_count"] == 1
        assert analysis_rows[0]["id"] == world["analysis"]["id"]

    def test_02_four_auditor_writes_across_four_entities_all_answer_the_same_way(self, api):
        """PRD §2.1: "`MemberAuditor` is strictly read-only: it holds no write operation anywhere
        in the API, and every `GET` endpoint in the system admits it — including the responses
        list of a solicitation, the usage-report list of a contract, and the price-quote
        computation." PRD §2.9: "The endpoint's role list contains `X-User-Role` —
        `ERR_UNAUTHORIZED`, 403, on every endpoint." PRD §2.1: "A scope violation by an
        entity-backed role — a supplier representative writing against another supplier's
        resource, or a member representative writing against another member's — is rejected with
        `ERR_ACTOR_SCOPE_MISMATCH` (HTTP 403)."

        Design: Corner/RBAC/member_auditor_may_read_the_whole_audit_file_and_write_nothing
        """
        world = _authorised_world(api)

        attempts = (
            api.create_state_law_rule(state_law_rule_payload(**TX_RULE), AUDITOR),
            api.solicitation_audit_package(
                world["solicitation"]["id"], {"action": "ASSEMBLE"}, AUDITOR
            ),
            api.contract_award_status(
                world["contract"]["id"], {"action": "SUSPEND"}, AUDITOR
            ),
            api.create_contract_usage(_usage_payload(world), AUDITOR),
        )

        for attempt in attempts:
            validate_error(attempt, ApiErrorId.ERR_UNAUTHORIZED, 403)
            assert (
                attempt.json()["data"]["error_id"]
                != ApiErrorId.ERR_ACTOR_SCOPE_MISMATCH.value
            )
        solicitation = read_solicitation(api, world["solicitation"]["id"])
        assert solicitation["audit_package_status"] == "NOT_ASSEMBLED"
        assert read_contract(api, world["contract"]["id"])["status"] == "ACTIVE"
        assert_cents(
            read_member(api, world["member"]["id"])["committed_spend_cents"],
            0,
            "committed_spend_cents",
        )
        _, usage_meta = validate_paginated(api.list_contract_usages(ADMIN_REVIEW))
        assert usage_meta["total_count"] == 0


class TestPeerEntityRoles:
    def test_03_neither_entity_role_may_stand_on_the_others_reporting_route(self, api):
        """PRD §2.1: "`SupplierRepresentative` acts for a single bidding or awarded supplier."
        PRD §2.1: "`MemberRepresentative` acts for a single participating agency." PRD §2.1: "If
        both headers are well formed but the role is not among the roles the target endpoint
        admits, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/RBAC/supplier_and_member_roles_cannot_borrow_each_others_write_surface
        """
        world = _authorised_world(api)
        supplier_headers = make_supplier_headers(world["contract"]["supplier_id"])
        member_headers = make_member_headers(world["member"]["id"])

        supplier_order = api.create_contract_usage(_usage_payload(world), supplier_headers)
        member_report = api.create_usage_report(
            usage_report_payload(world["contract"]["id"]), member_headers
        )

        validate_error(supplier_order, ApiErrorId.ERR_UNAUTHORIZED, 403)
        validate_error(member_report, ApiErrorId.ERR_UNAUTHORIZED, 403)
        _, usage_meta = validate_paginated(api.list_contract_usages(ADMIN_REVIEW))
        assert usage_meta["total_count"] == 0
        _, report_meta = validate_paginated(api.list_usage_reports(ADMIN_REVIEW))
        assert report_meta["total_count"] == 0
        assert_cents(
            read_member(api, world["member"]["id"])["committed_spend_cents"],
            0,
            "committed_spend_cents",
        )

    def test_04_a_supplier_may_neither_complain_nor_move_its_own_standing(self, api):
        """PRD §2.1: "`CoopAdministrator` is the cooperative purchasing organization's own staff:
        they run the membership desk, register state law configuration and suppliers, determine
        and void piggyback authority, move contract execution status, run the delinquency sweep,
        review and reconcile usage reports, decide amendments, adjudicate complaints, and drive
        the logical clock." PRD §2.9: "The endpoint's role list contains `X-User-Role` —
        `ERR_UNAUTHORIZED`, 403, on every endpoint."

        Design: Corner/RBAC/supplier_and_member_roles_cannot_borrow_each_others_write_surface
        """
        world = _authorised_world(api)
        supplier_id = world["contract"]["supplier_id"]
        supplier_headers = make_supplier_headers(supplier_id)

        filed_by_supplier = api.create_complaint(
            complaint_payload(
                world["contract"]["id"],
                world["member"]["id"],
                severity="MINOR",
                category="SERVICE",
                narrative="Filed by the wrong party on purpose",
            ),
            supplier_headers,
        )
        self_suspension = api.supplier_qualification(
            supplier_id, {"action": "SUSPEND"}, supplier_headers
        )

        validate_error(filed_by_supplier, ApiErrorId.ERR_UNAUTHORIZED, 403)
        validate_error(self_suspension, ApiErrorId.ERR_UNAUTHORIZED, 403)
        _, complaint_meta = validate_paginated(api.list_complaints(ADMIN_REVIEW))
        assert complaint_meta["total_count"] == 0
        assert read_supplier(api, supplier_id)["qualification_status"] == "QUALIFIED"


class TestEntityBackedScope:
    def test_05_a_foreign_supplier_may_read_the_contract_but_not_report_on_it(self, api):
        """PRD §2.1: "When `X-User-Role` is `SupplierRepresentative`, `X-User-ID` is the `id` of
        the acting `Supplier`." PRD §2.1: "A scope violation by an entity-backed role — a
        supplier representative writing against another supplier's resource, or a member
        representative writing against another member's — is rejected with
        `ERR_ACTOR_SCOPE_MISMATCH` (HTTP 403). Read endpoints are not scope-checked: any role
        listed on a `GET` endpoint may read any row it returns."

        Design: Corner/RBAC/entity_backed_actors_are_pinned_to_their_own_row_in_both_directions
        """
        world = _authorised_world(api)
        foreign_headers = make_supplier_headers(world["supplier_b"]["id"])

        foreign_report = api.create_usage_report(
            usage_report_payload(world["contract"]["id"]), foreign_headers
        )
        foreign_read = api.get_master_contract(world["contract"]["id"], foreign_headers)

        validate_error(foreign_report, ApiErrorId.ERR_ACTOR_SCOPE_MISMATCH, 403)
        contract = validate_success(foreign_read)
        assert contract["id"] == world["contract"]["id"]
        assert contract["supplier_id"] == world["supplier_a"]["id"]
        _, report_meta = validate_paginated(api.list_usage_reports(ADMIN_REVIEW))
        assert report_meta["total_count"] == 0

    def test_06_a_foreign_member_may_neither_order_nor_confirm_on_another_members_row(self, api):
        """PRD §2.1: "When `X-User-Role` is `MemberRepresentative`, `X-User-ID` is the `id` of the
        acting `MemberAgency`. Ownership checks compare `X-User-ID` against the
        `member_agency_id` reachable from the target resource — the `member_agency_id` on a
        `ContractUsage` or `MemberComplaint`, or the `member_agency_id` supplied in the request
        body." PRD §2.9: "Entity-backed actor scope — `ERR_ACTOR_SCOPE_MISMATCH`, 403, on every
        write endpoint whose role list contains `SupplierRepresentative` or
        `MemberRepresentative`: `POST /coop/solicitation-responses`,
        `POST /coop/solicitation-responses/{id}/submission`, `POST /coop/usage-reports`,
        `POST /coop/usage-reports/{id}/submission`,
        `POST /coop/usage-reports/{id}/fee-remittance`, `POST /coop/contract-amendments`,
        `POST /coop/contract-amendments/{id}/withdrawal`, `POST /coop/complaints/{id}/appeal`,
        `POST /coop/piggyback-analyses`, `POST /coop/contract-usages`,
        `POST /coop/contract-usages/{id}/disposition` and `POST /coop/complaints`. Read endpoints
        are never scope-checked."

        Design: Corner/RBAC/entity_backed_actors_are_pinned_to_their_own_row_in_both_directions
        """
        world = _two_member_world(api)
        austin_headers = make_member_headers(world["austin"]["id"])

        foreign_order = api.create_contract_usage(_usage_payload(world), austin_headers)
        validate_error(foreign_order, ApiErrorId.ERR_ACTOR_SCOPE_MISMATCH, 403)

        own_order = record_usage(
            api,
            world["contract"]["id"],
            world["member"]["id"],
            world["line"]["id"],
            world["analysis"]["id"],
        )
        assert own_order["status"] == "RECORDED"
        assert_cents(own_order["total_cents"], DISPENSER_ORDER_TOTAL_CENTS, "total_cents")

        foreign_confirmation = api.usage_disposition(
            own_order["id"], {"action": "CONFIRM"}, austin_headers
        )

        validate_error(foreign_confirmation, ApiErrorId.ERR_ACTOR_SCOPE_MISMATCH, 403)
        assert read_usage(api, own_order["id"])["status"] == "RECORDED"
        assert_cents(
            read_member(api, world["austin"]["id"])["committed_spend_cents"],
            0,
            "committed_spend_cents",
        )
        assert_cents(
            read_member(api, world["member"]["id"])["committed_spend_cents"],
            DISPENSER_ORDER_TOTAL_CENTS,
            "committed_spend_cents",
        )


class TestSegregationOfDuties:
    def test_07_the_recommending_officer_is_refused_on_the_award_itself(self, api):
        """PRD §2.5: "The officer who recommends an award may not sign it. The `RECOMMEND_AWARD`
        action stamps `recommended_by_user_id`; the later `AWARD` action requires that the acting
        `X-User-ID` differ from that stored value." PRD §2.5: "Any of those collisions is rejected
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." PRD §2.9: "Segregation of duties —
        `ERR_SEGREGATION_OF_DUTIES`, 403, on `POST /coop/solicitations/{id}/lifecycle`,
        `POST /coop/complaints/{id}/investigation`, `POST /coop/complaints/{id}/decision` and
        `POST /coop/complaints/{id}/appeal-decision`."

        Design: Corner/RBAC/the_officer_who_recommends_an_award_may_not_be_the_officer_who_makes_it
        """
        world = _scored_world(api)
        solicitation_id = world["solicitation"]["id"]

        recommended = validate_success(
            _lifecycle(api, solicitation_id, "RECOMMEND_AWARD", OFFICER_CONDUCTOR)
        )
        assert recommended["status"] == "AWARD_PENDING"
        assert recommended["recommended_by_user_id"] == OFFICER_CONDUCTOR_ID

        self_award = _lifecycle(api, solicitation_id, "AWARD", OFFICER_CONDUCTOR)

        validate_error(self_award, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        assert self_award.json()["data"]["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value
        blocked = read_solicitation(api, solicitation_id)
        assert blocked["status"] == "AWARD_PENDING"
        assert blocked["awarded_by_user_id"] is None

    def test_08_a_second_officer_completes_the_identical_award_call(self, api):
        """PRD §2.5: "Two of the cooperative's control objectives are enforced *within* a role
        rather than between roles, by comparing `X-User-ID` values recorded on the resource:" PRD
        §3.2: "On success it stamps `awarded_by_user_id` and unlocks master-contract creation for
        that rank-1 supplier's `supplier_id`." PRD §2.1: "When `X-User-Role` is
        `CoopAdministrator`, `LeadAgencyOfficer` or `MemberAuditor`, `X-User-ID` is an opaque
        operator identifier not tied to any persisted entity."

        Design: Corner/RBAC/the_officer_who_recommends_an_award_may_not_be_the_officer_who_makes_it
        """
        world = _scored_world(api)
        solicitation_id = world["solicitation"]["id"]
        validate_success(_lifecycle(api, solicitation_id, "RECOMMEND_AWARD", OFFICER_CONDUCTOR))
        validate_error(
            _lifecycle(api, solicitation_id, "AWARD", OFFICER_CONDUCTOR),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        awarded = validate_success(
            _lifecycle(api, solicitation_id, "AWARD", OFFICER_AWARDER)
        )

        assert awarded["status"] == "AWARDED"
        assert awarded["awarded_by_user_id"] == OFFICER_AWARDER_ID
        assert awarded["recommended_by_user_id"] == OFFICER_CONDUCTOR_ID
        stored = read_solicitation(api, solicitation_id)
        assert stored["status"] == "AWARDED"
        assert stored["awarded_by_user_id"] == OFFICER_AWARDER_ID


class TestAdministratorExclusiveSurface:
    def test_09_only_the_administrator_publishes_a_state_law_configuration(self, api):
        """PRD §2.1: "`CoopAdministrator` is the cooperative purchasing organization's own staff:
        they run the membership desk, register state law configuration and suppliers, determine
        and void piggyback authority, move contract execution status, run the delinquency sweep,
        review and reconcile usage reports, decide amendments, adjudicate complaints, and drive
        the logical clock." PRD §2.9: "The endpoint's role list contains `X-User-Role` —
        `ERR_UNAUTHORIZED`, 403, on every endpoint."

        Design: Corner/RBAC/coop_administrator_owns_the_registry_and_the_contract_administration_surface
        """
        _authorised_world(api)

        officer_attempt = api.create_state_law_rule(
            state_law_rule_payload(**OK_RULE), OFFICER_CONDUCTOR
        )
        validate_error(officer_attempt, ApiErrorId.ERR_UNAUTHORIZED, 403)
        _, before = validate_paginated(api.list_state_law_rules(ADMIN_REVIEW))
        assert before["total_count"] == 2

        published = validate_success(
            api.create_state_law_rule(state_law_rule_payload(**OK_RULE), ADMIN_INTAKE), 201
        )

        assert published["state_code"] == "OK"
        _, after = validate_paginated(api.list_state_law_rules(ADMIN_REVIEW))
        assert after["total_count"] == 3

    def test_10_only_the_administrator_registers_and_verifies_a_member(self, api):
        """PRD §3.4: "The cooperative's membership desk is staffed by `CoopAdministrator`s." PRD
        §3.4: "On success `verified_at` is stamped with the current logical instant and
        `verified_by_user_id` with the acting `X-User-ID`." PRD §2.9: "The endpoint's role list
        contains `X-User-Role` — `ERR_UNAUTHORIZED`, 403, on every endpoint."

        Design: Corner/RBAC/coop_administrator_owns_the_registry_and_the_contract_administration_surface
        """
        _authorised_world(api)
        create_state_law_rule(api, **OK_RULE)

        officer_attempt = api.create_member_agency(
            member_agency_payload(**TULSA), OFFICER_CONDUCTOR
        )
        validate_error(officer_attempt, ApiErrorId.ERR_UNAUTHORIZED, 403)

        registered = validate_success(
            api.create_member_agency(member_agency_payload(**TULSA), ADMIN_INTAKE), 201
        )
        assert registered["registration_status"] == "PENDING_VERIFICATION"
        verified = validate_success(
            api.member_registration(registered["id"], {"action": "VERIFY"}, ADMIN_REVIEW)
        )

        assert verified["registration_status"] == "ACTIVE"
        assert verified["verified_by_user_id"] == ADMIN_REVIEW_ID
        stored = read_member(api, registered["id"])
        assert stored["registration_status"] == "ACTIVE"
        assert stored["verified_by_user_id"] == ADMIN_REVIEW_ID

    def test_11_only_the_administrator_moves_the_contract_execution_dimension(self, api):
        """PRD §3.3: "`SUSPEND` moves `ACTIVE → SUSPENDED`, voids every `DETERMINED` opinion on
        this contract with `voided_reason` `CONTRACT_SUSPENDED`, and blocks new usage." PRD §2.9:
        "The endpoint's role list contains `X-User-Role` — `ERR_UNAUTHORIZED`, 403, on every
        endpoint." PRD §3.3: "`TERMINATE` is reachable from `PENDING_EXECUTION`, `ACTIVE` and
        `SUSPENDED`; in every case it sets every line item of the contract to `WITHDRAWN`, and
        from `ACTIVE` or `SUSPENDED` it additionally voids the contract's `DETERMINED` opinions
        with `voided_reason` `CONTRACT_TERMINATED`."

        Design: Corner/RBAC/coop_administrator_owns_the_registry_and_the_contract_administration_surface
        """
        world = _authorised_world(api)
        contract_id = world["contract"]["id"]

        officer_attempt = api.contract_award_status(
            contract_id, {"action": "SUSPEND"}, OFFICER_AWARDER
        )
        validate_error(officer_attempt, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert read_contract(api, contract_id)["status"] == "ACTIVE"
        assert read_analysis(api, world["analysis"]["id"])["status"] == "DETERMINED"

        suspended = validate_success(
            api.contract_award_status(
                contract_id,
                {"action": "SUSPEND", "note": "performance review pending"},
                ADMIN_REVIEW,
            )
        )

        assert suspended["status"] == "SUSPENDED"
        analysis = read_analysis(api, world["analysis"]["id"])
        assert analysis["status"] == "VOIDED"
        assert analysis["voided_reason"] == "CONTRACT_SUSPENDED"
        assert read_line_item(api, world["line"]["id"])["status"] == "ACTIVE"


class TestOfficerExclusiveSurface:
    def test_12_the_administrator_may_not_conduct_a_solicitation_or_publish_a_price_sheet(
        self, api
    ):
        """PRD §2.1: "`LeadAgencyOfficer` is the procurement officer of the lead agency conducting
        the solicitation on the cooperative's behalf: they create and drive solicitations,
        evaluate responses, award and publish the master contract price sheet, and assemble and
        certify the documentation package." PRD §2.9: "The endpoint's role list contains
        `X-User-Role` — `ERR_UNAUTHORIZED`, 403, on every endpoint." PRD §3.2: "A new
        solicitation lands in `status` `DRAFT` and `audit_package_status` `NOT_ASSEMBLED`, with
        `addenda_count` and `responsive_response_count` both 0 and `posted_at`, `notice_days` and
        `audit_completeness_pct` all null."

        Design: Corner/RBAC/lead_agency_officer_owns_the_solicitation_and_the_audit_package_and_nothing_else
        """
        world = _authorised_world(api)
        solicitation_id = world["solicitation"]["id"]

        attempts = (
            api.create_solicitation(
                solicitation_payload(
                    title="Office Paper",
                    solicitation_number=PAPER_SOLICITATION_NUMBER,
                    response_due_at="2026-10-01T00:00:00Z",
                    specification_document_ref=None,
                    method_justification_ref=None,
                ),
                ADMIN_REVIEW,
            ),
            api.solicitation_audit_package(
                solicitation_id, {"action": "ASSEMBLE"}, ADMIN_REVIEW
            ),
            api.create_line_item(
                world["contract"]["id"], line_item_payload(**PAPER_LINE), ADMIN_REVIEW
            ),
        )

        for attempt in attempts:
            validate_error(attempt, ApiErrorId.ERR_UNAUTHORIZED, 403)
        rows, meta = validate_paginated(api.list_solicitations(ADMIN_REVIEW))
        assert meta["total_count"] == 1
        assert all(row["solicitation_number"] != PAPER_SOLICITATION_NUMBER for row in rows)
        assert read_solicitation(api, solicitation_id)["audit_package_status"] == "NOT_ASSEMBLED"
        _, line_meta = validate_paginated(
            api.list_line_items_of_contract(world["contract"]["id"], ADMIN_REVIEW)
        )
        assert line_meta["total_count"] == 1

    def test_13_the_officer_assembles_the_package_and_adds_the_catalogue_line(self, api):
        """PRD §3.2: "`ASSEMBLE` is reachable from `NOT_ASSEMBLED`, from `ASSEMBLED` (re-assembly
        is legal and idempotent in shape though not in value — the recomputed percentage may
        differ) and from `STALE`; in all three cases it requires `posted_at` to be non-null." PRD
        §3.3: "A published line starts with `origin` `AWARD`, `status` `ACTIVE`,
        `price_change_count` 0, `last_price_change_at` null, and `price_effective_from`
        initialised to the contract's `base_term_start`." PRD §2.9: "No other operation is gated
        on contract status: opening a usage report and filing a complaint are deliberately
        permitted against a non-`ACTIVE` contract."

        Design: Corner/RBAC/lead_agency_officer_owns_the_solicitation_and_the_audit_package_and_nothing_else
        """
        world = _authorised_world(api)
        contract_id = world["contract"]["id"]

        assembled = validate_success(
            api.solicitation_audit_package(
                world["solicitation"]["id"], {"action": "ASSEMBLE"}, OFFICER_CONDUCTOR
            )
        )
        added = validate_success(
            api.create_line_item(contract_id, line_item_payload(**PAPER_LINE), OFFICER_AWARDER),
            201,
        )

        assert assembled["audit_package_status"] == "ASSEMBLED"
        assert added["origin"] == "AWARD"
        assert added["status"] == "ACTIVE"
        assert added["sku"] == SKU_PAPER
        stored = read_line_item(api, added["id"])
        assert stored["status"] == "ACTIVE"
        assert stored["origin"] == "AWARD"
        _, line_meta = validate_paginated(
            api.list_line_items_of_contract(contract_id, ADMIN_REVIEW)
        )
        assert line_meta["total_count"] == 2


class TestMemberRepresentativeSurface:
    def test_14_the_roster_is_closed_to_members_while_a_single_row_is_open(self, api):
        """PRD §2.9: "The endpoint's role list contains `X-User-Role` — `ERR_UNAUTHORIZED`, 403,
        on every endpoint." PRD §2.1: "Read endpoints are not scope-checked: any role listed on a
        `GET` endpoint may read any row it returns." PRD §2.1: "`MemberRepresentative` acts for a
        single participating agency."

        Design: Corner/RBAC/member_representatives_read_widely_but_write_only_on_their_own_row
        """
        world = _two_member_world(api)
        member_headers = make_member_headers(world["member"]["id"])

        roster = api.list_member_agencies(member_headers, {"state_code": "CA"})
        own_row = api.get_member_agency(world["member"]["id"], member_headers)
        other_row = api.get_member_agency(world["austin"]["id"], member_headers)

        validate_error(roster, ApiErrorId.ERR_UNAUTHORIZED, 403)
        own = validate_success(own_row)
        assert own["legal_name"] == "Riverside Unified School District"
        other = validate_success(other_row)
        assert other["id"] == world["austin"]["id"]
        assert other["legal_name"] == AUSTIN["legal_name"]

    def test_15_a_member_orders_and_complains_on_its_own_row_but_investigates_nothing(self, api):
        """PRD §3.6: "A `MemberRepresentative` records a purchase against a contract line by
        naming `contract_id`, `member_agency_id`, `line_item_id` and the `piggyback_analysis_id`
        of the opinion it relies on, a `quantity` of at least 1, and optionally the
        `add_on_codes` it elects." PRD §2.9: "The endpoint's role list contains `X-User-Role` —
        `ERR_UNAUTHORIZED`, 403, on every endpoint." PRD §3.9: "A new complaint starts in
        `status` `INTAKE` with `points_reversed` false and `deduction_points`,
        `investigator_user_id`, `adjudicator_user_id`, `substantiated_at`, `appeal_filed_at` and
        `appeal_deadline_at` all null."

        Design: Corner/RBAC/member_representatives_read_widely_but_write_only_on_their_own_row
        """
        world = _authorised_world(api)
        member_headers = make_member_headers(world["member"]["id"])

        order = validate_success(
            api.create_contract_usage(_usage_payload(world), member_headers), 201
        )
        complaint = validate_success(
            api.create_complaint(
                complaint_payload(
                    world["contract"]["id"],
                    world["member"]["id"],
                    severity="MINOR",
                    category="DELIVERY",
                    narrative="Dispenser arrived without mounting hardware",
                    related_usage_id=order["id"],
                ),
                member_headers,
            ),
            201,
        )
        self_assignment = api.complaint_investigation(
            complaint["id"],
            {"action": "OPEN_INVESTIGATION", "note": "self-assignment attempt"},
            member_headers,
        )

        assert order["status"] == "RECORDED"
        assert_cents(order["total_cents"], DISPENSER_ORDER_TOTAL_CENTS, "total_cents")
        assert complaint["status"] == "INTAKE"
        assert complaint["related_usage_id"] == order["id"]
        validate_error(self_assignment, ApiErrorId.ERR_UNAUTHORIZED, 403)
        stored = read_complaint(api, complaint["id"])
        assert stored["status"] == "INTAKE"
        assert stored["investigator_user_id"] is None
        assert_score(
            read_supplier(api, world["contract"]["supplier_id"])["deduction_points_total"],
            0.00,
            "deduction_points_total",
        )
