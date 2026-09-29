"""Requests that break two rules at once, answered by the higher-precedence one."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADMIN_ADJUDICATOR,
    ADMIN_ADJUDICATOR_ID,
    ADMIN_INVESTIGATOR,
    ADMIN_INVESTIGATOR_ID,
    ADMIN_REVIEW,
    ApiErrorId,
    assert_cents,
    assert_instant,
    assert_score,
    make_member_headers,
)
from test_helpers.constants import CLOCK_AFTER_TERM_END, CLOCK_SEP_02, SKU_DISPENSER
from test_helpers.factories import contract_usage_payload
from test_helpers.fixtures import (
    file_complaint,
    open_investigation,
    read_analysis,
    read_complaint,
    read_contract,
    read_supplier,
    set_clock,
    setup_active_contract,
    setup_authorised_member,
)

TANAGER = dict(
    legal_name="Tanager Falls",
    state_code="TX",
    member_category="CITY",
    annual_spend_ceiling_cents=100000,
    governing_body_resolution_number="RES-TF-2026-003",
)


def _ceiling_world(api):
    """A member whose ceiling is far too small for a quantity-ten dispenser order."""
    world = setup_active_contract(api)
    member, analysis = setup_authorised_member(api, world, **TANAGER)
    world["member"] = member
    world["analysis"] = analysis
    return world


def _order(api, world, **extra):
    return api.create_contract_usage(
        contract_usage_payload(
            world["contract"]["id"],
            world["member"]["id"],
            world["lines"][SKU_DISPENSER]["id"],
            world["analysis"]["id"],
            **extra,
        ),
        make_member_headers(world["member"]["id"]),
    )


def _suspend(api, world):
    return validate_success(
        api.contract_award_status(
            world["contract"]["id"],
            {"action": "SUSPEND", "note": "temporary hold pending audit"},
            ADMIN_REVIEW,
        )
    )


def _expired_authority_world(api):
    """An opinion frozen to the term end, read one day after that instant."""
    world = setup_active_contract(api)
    member, analysis = setup_authorised_member(api, world)
    world["member"] = member
    world["analysis"] = analysis
    set_clock(api, CLOCK_AFTER_TERM_END)
    return world


def _dismissed_complaint_world(api):
    """A complaint investigated by one administrator and dismissed by another."""
    world = setup_active_contract(api)
    member, analysis = setup_authorised_member(api, world)
    world["member"] = member
    world["analysis"] = analysis
    complaint = file_complaint(
        api,
        world["contract"]["id"],
        member["id"],
        severity="MAJOR",
        category="BILLING",
        narrative="Administrative fee appeared on an invoice line",
    )
    open_investigation(api, complaint["id"], ADMIN_INVESTIGATOR)
    world["complaint"] = validate_success(
        api.complaint_investigation(
            complaint["id"],
            {"action": "DISMISS", "note": "billing line traced to member purchase order"},
            ADMIN_ADJUDICATOR,
        )
    )
    return world


def _substantiate(api, world, headers):
    return api.complaint_decision(
        world["complaint"]["id"],
        {"action": "SUBSTANTIATE", "note": "reopening attempt"},
        headers,
    )


class TestContractStateOutranksSpendCeiling:
    def test_01_while_the_contract_is_active_only_the_fiscal_rule_is_broken(self, api):
        """PRD §3.6: "Finally the member's `committed_spend_cents` plus this order's own
        `total_cents` must not exceed its `annual_spend_ceiling_cents`; landing exactly on
        the ceiling is permitted, and exceeding it is `ERR_MEMBER_CEILING_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/contract_state_priority_10_outranks_member_ceiling_priority_61
        """
        world = _ceiling_world(api)
        assert read_contract(api, world["contract"]["id"])["status"] == "ACTIVE"

        response = _order(api, world, quantity=10)

        validate_error(response, ApiErrorId.ERR_MEMBER_CEILING_EXCEEDED, 422)
        member = validate_success(api.get_member_agency(world["member"]["id"], ADMIN_REVIEW))
        assert_cents(member["committed_spend_cents"], 0, "committed_spend_cents")

    def test_02_the_identical_body_switches_answer_once_the_contract_is_suspended(self, api):
        """PRD §2.9: "All checks in the system are evaluated in the following fixed order;
        the first failing check produces the response and no later check runs."

        Design: Difficulty/priority_pair_validation_conflict/contract_state_priority_10_outranks_member_ceiling_priority_61
        """
        world = _ceiling_world(api)
        validate_error(_order(api, world, quantity=10), ApiErrorId.ERR_MEMBER_CEILING_EXCEEDED, 422)

        suspended = _suspend(api, world)
        response = _order(api, world, quantity=10)

        assert suspended["status"] == "SUSPENDED"
        validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE, 409)

    def test_03_the_state_gate_also_outranks_the_authority_it_just_voided(self, api):
        """PRD §2.9: "The `MasterContract` the operation depends on is `ACTIVE` —
        `ERR_CONTRACT_NOT_ACTIVE`, 409, on `POST /coop/contract-usages`, `POST
        /coop/piggyback-analyses/{id}/determination`, `POST /coop/contract-amendments` and
        `POST /coop/contract-amendments/{id}/decision`."

        Design: Difficulty/priority_pair_validation_conflict/contract_state_priority_10_outranks_member_ceiling_priority_61
        """
        world = _ceiling_world(api)
        _suspend(api, world)

        analysis = read_analysis(api, world["analysis"]["id"])
        assert analysis["status"] == "VOIDED"
        assert analysis["voided_reason"] == "CONTRACT_SUSPENDED"
        validate_error(_order(api, world, quantity=1), ApiErrorId.ERR_CONTRACT_NOT_ACTIVE, 409)
        member = validate_success(api.get_member_agency(world["member"]["id"], ADMIN_REVIEW))
        assert_cents(member["committed_spend_cents"], 0, "committed_spend_cents")


class TestExpiredAuthorityOutranksAddOnCatalogue:
    def test_04_the_opinion_expires_on_the_term_end_rather_than_a_year_out(self, api):
        """PRD §3.5: "`determined_at` is stamped with the current logical instant, and
        `expires_on` is frozen as the *earlier* of the contract's `current_term_end` and
        365 days after `determined_at`."

        Design: Difficulty/priority_pair_validation_conflict/expired_authority_priority_31_outranks_unpermitted_add_on_priority_38
        """
        world = _expired_authority_world(api)

        analysis = read_analysis(api, world["analysis"]["id"])
        assert_instant(analysis["expires_on"], "2027-09-01T00:00:00Z", "expires_on")
        assert analysis["status"] == "DETERMINED"
        assert read_contract(api, world["contract"]["id"])["status"] == "ACTIVE"

    def test_05_an_expired_opinion_answers_before_the_add_on_catalogue_is_read(self, api):
        """PRD §2.9: "That analysis has not expired — `ERR_PIGGYBACK_EXPIRED`, 409, on
        `POST /coop/contract-usages`."

        Design: Difficulty/priority_pair_validation_conflict/expired_authority_priority_31_outranks_unpermitted_add_on_priority_38
        """
        world = _expired_authority_world(api)

        response = _order(api, world, quantity=1, add_on_codes=["GIFT_WRAP"])

        validate_error(response, ApiErrorId.ERR_PIGGYBACK_EXPIRED, 409)
        member = validate_success(api.get_member_agency(world["member"]["id"], ADMIN_REVIEW))
        assert_cents(member["committed_spend_cents"], 0, "committed_spend_cents")

    def test_06_the_same_bad_code_answers_for_itself_while_the_opinion_is_live(self, api):
        """PRD §2.9: "Every elected add-on code is in the contract's catalogue —
        `ERR_ADD_ON_NOT_PERMITTED`, 422, on `POST /coop/contract-usages` and `GET
        /coop/master-contracts/{id}/price-quote`."

        Design: Difficulty/priority_pair_validation_conflict/expired_authority_priority_31_outranks_unpermitted_add_on_priority_38
        """
        world = _expired_authority_world(api)
        validate_error(
            _order(api, world, quantity=1, add_on_codes=["GIFT_WRAP"]),
            ApiErrorId.ERR_PIGGYBACK_EXPIRED,
            409,
        )

        set_clock(api, CLOCK_SEP_02)
        response = _order(api, world, quantity=1, add_on_codes=["GIFT_WRAP"])

        validate_error(response, ApiErrorId.ERR_ADD_ON_NOT_PERMITTED, 422)


class TestSegregationOutranksComplaintState:
    def test_07_a_dismissed_complaint_charges_nothing_and_records_both_officials(self, api):
        """PRD §3.9: "`DISMISS` moves `UNDER_INVESTIGATION → DISMISSED` and charges the
        supplier no performance points at all."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_priority_8_outranks_complaint_state_priority_12
        """
        world = _dismissed_complaint_world(api)

        complaint = read_complaint(api, world["complaint"]["id"])
        assert complaint["status"] == "DISMISSED"
        assert complaint["investigator_user_id"] == ADMIN_INVESTIGATOR_ID
        assert complaint["adjudicator_user_id"] == ADMIN_ADJUDICATOR_ID
        supplier = read_supplier(api, world["contract"]["supplier_id"])
        assert_score(supplier["deduction_points_total"], 0.00, "deduction_points_total")
        assert_score(supplier["performance_score"], 100.00, "performance_score")

    def test_08_the_investigator_is_refused_on_duty_grounds_not_on_state_grounds(self, api):
        """PRD §2.9: "Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`, 403, on `POST
        /coop/solicitations/{id}/lifecycle`, `POST /coop/complaints/{id}/investigation`,
        `POST /coop/complaints/{id}/decision` and `POST
        /coop/complaints/{id}/appeal-decision`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_priority_8_outranks_complaint_state_priority_12
        """
        world = _dismissed_complaint_world(api)

        response = _substantiate(api, world, ADMIN_INVESTIGATOR)

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        assert read_complaint(api, world["complaint"]["id"])["status"] == "DISMISSED"

    def test_09_an_uninvolved_administrator_gets_the_state_error_for_the_same_body(self, api):
        """PRD §2.9: "The `MemberComplaint` is in a from-state permitting the requested
        action — `ERR_COMPLAINT_INVALID_STATE`, 409, on `POST
        /coop/complaints/{id}/investigation`, `POST /coop/complaints/{id}/decision`, `POST
        /coop/complaints/{id}/appeal` and `POST /coop/complaints/{id}/appeal-decision`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_priority_8_outranks_complaint_state_priority_12
        """
        world = _dismissed_complaint_world(api)
        validate_error(
            _substantiate(api, world, ADMIN_INVESTIGATOR),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        response = _substantiate(api, world, ADMIN_REVIEW)

        validate_error(response, ApiErrorId.ERR_COMPLAINT_INVALID_STATE, 409)
        supplier = read_supplier(api, world["contract"]["supplier_id"])
        assert_score(supplier["deduction_points_total"], 0.00, "deduction_points_total")
        assert_score(supplier["performance_score"], 100.00, "performance_score")
