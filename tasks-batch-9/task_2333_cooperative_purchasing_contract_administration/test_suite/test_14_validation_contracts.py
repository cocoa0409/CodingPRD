"""Validation rungs that are conditional on a category, a state rule or a clock."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_PIGGYBACK,
    ADMIN_REVIEW,
    ADMIN_REVIEW_ID,
    ApiErrorId,
    assert_cents,
    assert_deduction_detail,
    assert_instant,
    assert_score,
    make_supplier_headers,
)
from test_helpers.constants import (
    BASE_TERM_END,
    BASE_TERM_START,
    CLOCK_NOV_29,
    CLOCK_NOV_30,
    CLOCK_REGISTRY,
    CLOCK_TERM_START,
    SKU_DISPENSER,
)
from test_helpers.factories import (
    CA_RULE,
    NV_RULE,
    OMIT,
    TX_RULE,
    expansion_amendment_payload,
    price_adjustment_amendment_payload,
    renewal_amendment_payload,
)
from test_helpers.fixtures import (
    create_member,
    open_analysis,
    read_amendment,
    read_analysis,
    read_contract,
    read_line_item,
    read_member,
    seed_state_law_rules,
    set_clock,
    setup_active_contract,
    setup_active_member,
    setup_pending_contract,
)

MOP_ENTRY = dict(
    sku="JAN-MOP-200",
    item_description="Wet mop head, 20 ounce, cotton",
    unit_of_measure="EACH",
    base_unit_price_cents=4000,
    price_floor_cents=3000,
)
DISPENSER_ENTRY = dict(
    sku=SKU_DISPENSER,
    item_description="Wall dispenser, 500 sheet, second listing",
    unit_of_measure="EACH",
    base_unit_price_cents=12600,
    price_floor_cents=9000,
)
SPARKS = dict(
    legal_name="City of Sparks",
    state_code="NV",
    member_category="CITY",
    annual_spend_ceiling_cents=5000000,
    governing_body_resolution_number="RES-SP-2026-12",
)


def _registry(api, rules):
    set_clock(api, CLOCK_REGISTRY)
    return seed_state_law_rules(api, rules=rules)


def _verify(api, member_id):
    return api.member_registration(member_id, {"action": "VERIFY"}, ADMIN_REVIEW)


def _amendment_world(api):
    """An ACTIVE contract with one awarded line and no amendment history."""
    world = setup_active_contract(api)
    world["contract"] = read_contract(api, world["contract"]["id"])
    world["line"] = world["lines"][SKU_DISPENSER]
    world["headers"] = make_supplier_headers(world["contract"]["supplier_id"])
    return world


def _version(api, world):
    return read_contract(api, world["contract"]["id"])["version"]


def _propose_expansion(api, world, entries, overlap_pct):
    return api.create_contract_amendment(
        expansion_amendment_payload(
            world["contract"]["id"], _version(api, world), entries, overlap_pct
        ),
        world["headers"],
    )


def _propose_price(api, world, new_unit_price_cents, index_change_pct=0.0450):
    return api.create_contract_amendment(
        price_adjustment_amendment_payload(
            world["contract"]["id"],
            _version(api, world),
            world["line"]["id"],
            new_unit_price_cents,
            price_index="CPI_U",
            index_change_pct=index_change_pct,
        ),
        world["headers"],
    )


def _decide(api, amendment_id, note="approved on review"):
    return api.amendment_decision(
        amendment_id, {"action": "APPROVE", "decision_note": note}, ADMIN_REVIEW
    )


class TestMemberEligibilityRungs:
    def test_01_a_government_category_is_refused_without_its_own_resolution(self, api):
        """PRD §3.4: "It then requires evidence matching the asserted category: a member whose
        `member_category` is `NONPROFIT_501C3` must have a non-null
        `irs_determination_letter_number`, failing which the rejection is
        `ERR_NONPROFIT_EVIDENCE_MISSING`; a member in any other category must have a non-null
        `governing_body_resolution_number`, failing which the rejection is
        `ERR_GOVERNING_RESOLUTION_MISSING`."

        Design: Corner/Validations/member_eligibility_evidence_is_checked_per_category_then_against_state_law
        """
        _registry(api, (TX_RULE, NV_RULE))
        member = create_member(
            api,
            legal_name="Lakeside School District",
            state_code="TX",
            member_category="K12_DISTRICT",
            governing_body_resolution_number=OMIT,
        )

        refused = _verify(api, member["id"])

        validate_error(refused, ApiErrorId.ERR_GOVERNING_RESOLUTION_MISSING, 422)
        stored = read_member(api, member["id"])
        assert stored["registration_status"] == "PENDING_VERIFICATION"
        assert stored["verified_at"] is None
        assert stored["verified_by_user_id"] is None

    def test_02_a_nonprofit_reports_a_different_code_on_the_same_rung(self, api):
        """PRD §3.4: "Evidence numbers may be supplied at registration or later:
        `governing_body_resolution_number` is the resolution by which the member's governing body
        joined the cooperative, and `irs_determination_letter_number` is the IRS 501(c)(3)
        determination letter number."

        Design: Corner/Validations/member_eligibility_evidence_is_checked_per_category_then_against_state_law
        """
        _registry(api, (TX_RULE, NV_RULE))
        member = create_member(
            api,
            legal_name="Austin Community Trust",
            state_code="TX",
            member_category="NONPROFIT_501C3",
            governing_body_resolution_number=OMIT,
        )

        refused = _verify(api, member["id"])

        validate_error(refused, ApiErrorId.ERR_NONPROFIT_EVIDENCE_MISSING, 422)
        assert read_member(api, member["id"])["registration_status"] == (
            "PENDING_VERIFICATION"
        )

    def test_03_a_documented_nonprofit_then_meets_the_state_law_rung(self, api):
        """PRD §3.4: "Beyond evidence, a `NONPROFIT_501C3` member may only be verified when its
        state's `allows_nonprofit_participation` is true; a nonprofit in a state that forbids
        nonprofit participation is refused with `ERR_NONPROFIT_NOT_PERMITTED`." PRD §3.4: "On
        success `verified_at` is stamped with the current logical instant and
        `verified_by_user_id` with the acting `X-User-ID`."

        Design: Corner/Validations/member_eligibility_evidence_is_checked_per_category_then_against_state_law
        """
        _registry(api, (TX_RULE, NV_RULE))
        forbidden = create_member(
            api,
            legal_name="Silver State Community Fund",
            state_code="NV",
            member_category="NONPROFIT_501C3",
            governing_body_resolution_number=OMIT,
            irs_determination_letter_number="IRS-NV-501C3-2019-88",
        )
        permitted = create_member(
            api,
            legal_name="Hill Country Food Bank",
            state_code="TX",
            member_category="NONPROFIT_501C3",
            governing_body_resolution_number=OMIT,
            irs_determination_letter_number="IRS-TX-501C3-2018-14",
        )

        refused = _verify(api, forbidden["id"])
        verified = validate_success(_verify(api, permitted["id"]))

        validate_error(refused, ApiErrorId.ERR_NONPROFIT_NOT_PERMITTED, 422)
        stored = read_member(api, forbidden["id"])
        assert stored["registration_status"] == "PENDING_VERIFICATION"
        assert stored["verified_at"] is None
        assert stored["verified_by_user_id"] is None
        assert verified["registration_status"] == "ACTIVE"
        assert_instant(verified["verified_at"], CLOCK_REGISTRY, "verified_at")
        assert verified["verified_by_user_id"] == ADMIN_REVIEW_ID
        assert_cents(verified["committed_spend_cents"], 0, "committed_spend_cents")


class TestConditionalWaiverRung:
    def test_04_the_waiver_rung_fires_only_for_the_state_that_demands_one(self, api):
        """PRD §3.5: "`DETERMINE` moves `PENDING → DETERMINED` and requires the member to be
        `ACTIVE`, the contract to be `ACTIVE`, and — when the member's state sets
        `requires_local_solicitation_waiver` to true — a non-null `waiver_reference`, which the
        request may supply if it was not supplied at creation; a missing waiver is
        `ERR_LOCAL_WAIVER_REQUIRED`."

        Design: Corner/Validations/a_waiver_state_refuses_determination_without_a_reference_and_then_lands_conditional
        """
        world = setup_active_contract(api, rules=(TX_RULE, CA_RULE, NV_RULE))
        sparks = setup_active_member(api, **SPARKS)
        austin = setup_active_member(
            api,
            legal_name="City of Austin",
            state_code="TX",
            member_category="CITY",
            governing_body_resolution_number="RES-2026-208",
        )
        nevada = open_analysis(api, sparks["id"], world["contract"]["id"])
        texan = open_analysis(api, austin["id"], world["contract"]["id"])

        refused = api.analysis_determination(
            nevada["id"], {"action": "DETERMINE"}, ADMIN_PIGGYBACK
        )
        allowed = validate_success(
            api.analysis_determination(texan["id"], {"action": "DETERMINE"}, ADMIN_PIGGYBACK)
        )

        validate_error(refused, ApiErrorId.ERR_LOCAL_WAIVER_REQUIRED, 422)
        stored = read_analysis(api, nevada["id"])
        assert stored["status"] == "PENDING"
        assert stored["determination"] is None
        assert stored["authority_score"] is None
        assert allowed["status"] == "DETERMINED"
        assert allowed["determination"] == "AUTHORIZED"
        assert allowed["local_waiver_required"] is False

    def test_05_the_liberal_doctrine_charges_fifteen_and_a_capped_ten(self, api):
        """PRD §3.5: "Under `RECIPROCITY_LIBERAL` the same four tests fire in the same sequence
        but score differently, and the first one changes shape: if the solicitation's
        `lead_agency_state_code` differs from the member's `state_code` *and* is not listed in
        the state's `reciprocity_state_codes`, append `OUT_OF_STATE_LEAD` worth 15.00 — a lead
        state that appears in the reciprocity list costs nothing at all, and
        `requires_lead_agency_in_state` is not consulted." PRD §3.5: "A notice shortfall appends
        `SHORT_NOTICE` worth the smaller of 10.00 and two points for each day of shortfall." PRD
        §3.5: "`local_waiver_required` is frozen to the state's
        `requires_local_solicitation_waiver`."

        Design: Corner/Validations/a_waiver_state_refuses_determination_without_a_reference_and_then_lands_conditional
        """
        world = setup_active_contract(api, rules=(TX_RULE, CA_RULE, NV_RULE))
        sparks = setup_active_member(api, **SPARKS)
        first = open_analysis(api, sparks["id"], world["contract"]["id"])
        validate_error(
            api.analysis_determination(first["id"], {"action": "DETERMINE"}, ADMIN_PIGGYBACK),
            ApiErrorId.ERR_LOCAL_WAIVER_REQUIRED,
            422,
        )
        second = open_analysis(
            api,
            sparks["id"],
            world["contract"]["id"],
            waiver_reference="SPARKS-CC-2026-77",
        )

        determined = validate_success(
            api.analysis_determination(second["id"], {"action": "DETERMINE"}, ADMIN_PIGGYBACK)
        )

        superseded = read_analysis(api, first["id"])
        assert superseded["status"] == "VOIDED"
        assert superseded["voided_reason"] == "SUPERSEDED_BY_NEWER_ANALYSIS"
        assert determined["status"] == "DETERMINED"
        assert determined["doctrine_applied"] == "RECIPROCITY_LIBERAL"
        assert_score(determined["authority_score"], 75.00, "authority_score")
        assert determined["determination"] == "CONDITIONAL"
        assert determined["local_waiver_required"] is True
        assert determined["waiver_reference"] == "SPARKS-CC-2026-77"
        assert_deduction_detail(
            determined["deduction_detail"],
            [("OUT_OF_STATE_LEAD", 15.00), ("SHORT_NOTICE", 10.00)],
        )
        assert_instant(determined["determined_at"], CLOCK_TERM_START, "determined_at")
        assert_instant(determined["expires_on"], BASE_TERM_END, "expires_on")


class TestSuspensionBetweenAwardAndExecution:
    def test_06_a_contract_may_be_papered_for_a_supplier_that_is_already_suspended(self, api):
        """PRD §2.9: "The `Supplier` is `QUALIFIED` — `ERR_SUPPLIER_NOT_QUALIFIED`, 409, on
        `POST /coop/solicitation-responses`, `POST /coop/solicitation-responses/{id}/review`,
        `POST /coop/master-contracts/{id}/award-status`, `POST /coop/contract-amendments` and
        `POST /coop/contract-amendments/{id}/decision`." PRD §3.3: "A new contract starts in `status`
        `PENDING_EXECUTION` with `compliance_posture` `COMPLIANT`, `current_term_end` initialised
        to `base_term_end`, `renewals_used` 0, and every ledger total —
        `usage_chargeable_cents_total`, `fee_assessed_cents_total`, `fee_remitted_cents_total`,
        `fee_outstanding_cents` and `delinquent_report_count` — at 0."

        Design: Corner/Validations/a_suspension_between_award_and_execution_blocks_execution_but_not_contract_creation
        """
        world = setup_pending_contract(api)
        supplier_id = world["contract"]["supplier_id"]

        suspended = validate_success(
            api.supplier_qualification(
                supplier_id,
                {"action": "SUSPEND", "note": "audit finding under review"},
                ADMIN_REVIEW,
            )
        )

        assert suspended["qualification_status"] == "SUSPENDED"
        contract = read_contract(api, world["contract"]["id"])
        assert contract["status"] == "PENDING_EXECUTION"
        assert contract["compliance_posture"] == "COMPLIANT"
        assert_instant(contract["current_term_end"], BASE_TERM_END, "current_term_end")
        assert read_line_item(api, world["lines"][SKU_DISPENSER]["id"])["status"] == "ACTIVE"

    def test_07_the_gate_bites_at_execution_and_lifts_on_reinstatement(self, api):
        """PRD §3.1: "`REINSTATE` moves `SUSPENDED → QUALIFIED` and is refused while
        `performance_tier` is `PROBATION`; it deliberately leaves the contracts `SUSPENDED` —
        each must be reinstated explicitly on its own execution dimension — and it does not
        revive the voided opinions." PRD §3.3: "`EXECUTE` moves `PENDING_EXECUTION → ACTIVE` and
        requires the supplier to be `QUALIFIED`, the solicitation to be `AWARDED`, at least one
        `ACTIVE` line on the price sheet (otherwise `ERR_NO_ACTIVE_LINE_ITEMS`), and the logical
        clock to be strictly before `base_term_end`; it sets `price_effective_from` to
        `base_term_start` on every `ACTIVE` line and sets `current_term_end` to `base_term_end`
        if that field is still null."

        Design: Corner/Validations/a_suspension_between_award_and_execution_blocks_execution_but_not_contract_creation
        """
        world = setup_pending_contract(api)
        contract_id = world["contract"]["id"]
        supplier_id = world["contract"]["supplier_id"]
        validate_success(
            api.supplier_qualification(
                supplier_id, {"action": "SUSPEND", "note": "audit finding"}, ADMIN_REVIEW
            )
        )
        set_clock(api, CLOCK_TERM_START)

        refused = api.contract_award_status(contract_id, {"action": "EXECUTE"}, ADMIN_REVIEW)

        validate_error(refused, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIED, 409)
        assert read_contract(api, contract_id)["status"] == "PENDING_EXECUTION"
        reinstated = validate_success(
            api.supplier_qualification(
                supplier_id, {"action": "REINSTATE", "note": "finding closed"}, ADMIN_REVIEW
            )
        )
        assert reinstated["qualification_status"] == "QUALIFIED"
        assert reinstated["performance_tier"] == "PREFERRED"
        executed = validate_success(
            api.contract_award_status(contract_id, {"action": "EXECUTE"}, ADMIN_REVIEW)
        )
        assert executed["status"] == "ACTIVE"
        assert_instant(executed["current_term_end"], BASE_TERM_END, "current_term_end")
        line = read_line_item(api, world["lines"][SKU_DISPENSER]["id"])
        assert_instant(line["price_effective_from"], BASE_TERM_START, "price_effective_from")


class TestAmendmentPayloadBlocks:
    def test_08_a_foreign_field_or_a_missing_one_is_the_same_refusal(self, api):
        """PRD §3.8: "The payload block must match the type exactly, and a mismatch in either
        direction — a missing required field or a field belonging to a different type being
        present — is `ERR_AMENDMENT_PAYLOAD_MISMATCH`." PRD §3.8: "A `PRICE_ADJUSTMENT` requires
        `target_line_item_id`, `new_unit_price_cents`, `price_index` (either `CPI_U` or
        `PPI_COMMODITY`) and `index_change_pct` (a four-decimal fraction between 0.0000 and
        1.0000), and forbids `requested_term_end`, `new_line_items` and
        `expansion_scope_overlap_pct`." PRD §3.8: "A `PRODUCT_LINE_EXPANSION` requires a
        non-empty `new_line_items` array — each entry an object of `sku`, `item_description`,
        `unit_of_measure`, `base_unit_price_cents` and `price_floor_cents` — together with
        `expansion_scope_overlap_pct`, a four-decimal fraction between 0.0000 and 1.0000
        declaring what share of the requested lines falls inside the original solicitation's
        specification scope, and nothing else."

        Design: Corner/Validations/each_amendment_type_admits_exactly_its_own_payload_block
        """
        world = _amendment_world(api)
        version = _version(api, world)

        renewal_with_price = api.create_contract_amendment(
            renewal_amendment_payload(
                world["contract"]["id"],
                version,
                "2028-09-01T00:00:00Z",
                new_unit_price_cents=13000,
            ),
            world["headers"],
        )
        price_without_index = api.create_contract_amendment(
            price_adjustment_amendment_payload(
                world["contract"]["id"],
                version,
                world["line"]["id"],
                13000,
                price_index=OMIT,
            ),
            world["headers"],
        )
        expansion_without_lines = api.create_contract_amendment(
            expansion_amendment_payload(
                world["contract"]["id"], version, OMIT, 0.9000
            ),
            world["headers"],
        )

        for response in (renewal_with_price, price_without_index, expansion_without_lines):
            validate_error(response, ApiErrorId.ERR_AMENDMENT_PAYLOAD_MISMATCH, 422)
        _, meta = validate_paginated(
            api.list_contract_amendments(ADMIN_REVIEW, {"contract_id": world["contract"]["id"]})
        )
        assert meta["total_count"] == 0

    def test_09_the_clean_renewal_is_admitted_and_moves_no_contract_field(self, api):
        """PRD §3.8: "A `RENEWAL` requires `requested_term_end` and nothing else." PRD §3.8: "A
        new amendment starts in `status` `PROPOSED` with `proposed_by_user_id` set to the acting
        `X-User-ID`, and `effective_from` and `decided_by_user_id` null." PRD §3.8:
        "`price_ceiling_cents` stays null on amendments of the other two types."

        Design: Corner/Validations/each_amendment_type_admits_exactly_its_own_payload_block
        """
        world = _amendment_world(api)

        amendment = validate_success(
            api.create_contract_amendment(
                renewal_amendment_payload(
                    world["contract"]["id"], _version(api, world), "2028-09-01T00:00:00Z"
                ),
                world["headers"],
            ),
            201,
        )

        assert amendment["status"] == "PROPOSED"
        assert amendment["amendment_type"] == "RENEWAL"
        assert_instant(
            amendment["requested_term_end"], "2028-09-01T00:00:00Z", "requested_term_end"
        )
        assert amendment["proposed_by_user_id"] == world["contract"]["supplier_id"]
        assert amendment["effective_from"] is None
        assert amendment["decided_by_user_id"] is None
        assert amendment["price_ceiling_cents"] is None
        contract = read_contract(api, world["contract"]["id"])
        assert_instant(contract["current_term_end"], BASE_TERM_END, "current_term_end")
        assert contract["renewals_used"] == 0
        _, meta = validate_paginated(
            api.list_contract_amendments(ADMIN_REVIEW, {"contract_id": contract["id"]})
        )
        assert meta["total_count"] == 1


class TestExpansionScopeAndSku:
    def test_10_the_scope_floor_is_inclusive_at_eighty_percent(self, api):
        """PRD §3.8: "A `PRODUCT_LINE_EXPANSION` requires `expansion_scope_overlap_pct` to be at
        least 0.8000 — that is, at least eighty percent of the requested lines must fall inside
        the competitively solicited scope." PRD §3.8: "A lower share is
        `ERR_EXPANSION_OUT_OF_SCOPE`, checked both at proposal and at approval."

        Design: Corner/Validations/expansion_scope_floor_is_checked_at_proposal_and_sku_uniqueness_only_at_approval
        """
        world = _amendment_world(api)

        below = _propose_expansion(api, world, [dict(MOP_ENTRY)], 0.7500)
        exactly = validate_success(
            _propose_expansion(api, world, [dict(MOP_ENTRY)], 0.8000), 201
        )

        validate_error(below, ApiErrorId.ERR_EXPANSION_OUT_OF_SCOPE, 422)
        assert exactly["status"] == "PROPOSED"
        assert exactly["amendment_type"] == "PRODUCT_LINE_EXPANSION"
        _, meta = validate_paginated(
            api.list_line_items_of_contract(world["contract"]["id"], ADMIN_REVIEW)
        )
        assert meta["total_count"] == 1

    def test_11_approval_creates_the_expansion_line_beside_the_awarded_one(self, api):
        """PRD §3.8: "The `PRODUCT_LINE_EXPANSION` branch creates one new price-sheet line per
        `new_line_items` entry, each with `origin` `EXPANSION` and `status` `ACTIVE`, and each
        subject to the same within-contract `sku` uniqueness rule as an awarded line
        (`ERR_DUPLICATE_SKU`)." PRD §3.8: "Approval stamps `effective_from` with the current
        logical instant and `decided_by_user_id` with the acting `X-User-ID`, then mutates
        whichever target its type selects."

        Design: Corner/Validations/expansion_scope_floor_is_checked_at_proposal_and_sku_uniqueness_only_at_approval
        """
        world = _amendment_world(api)
        proposed = validate_success(
            _propose_expansion(api, world, [dict(MOP_ENTRY)], 0.8000), 201
        )

        approved = validate_success(_decide(api, proposed["id"], "in scope on review"))

        assert approved["status"] == "APPROVED"
        assert_instant(approved["effective_from"], CLOCK_TERM_START, "effective_from")
        assert approved["decided_by_user_id"] == ADMIN_REVIEW_ID
        rows, meta = validate_paginated(
            api.list_line_items_of_contract(world["contract"]["id"], ADMIN_REVIEW)
        )
        assert meta["total_count"] == 2
        by_sku = {row["sku"]: row for row in rows}
        assert by_sku["JAN-MOP-200"]["origin"] == "EXPANSION"
        assert by_sku["JAN-MOP-200"]["status"] == "ACTIVE"
        assert_cents(
            by_sku["JAN-MOP-200"]["base_unit_price_cents"], 4000, "base_unit_price_cents"
        )
        assert by_sku[SKU_DISPENSER]["origin"] == "AWARD"

    def test_12_a_duplicate_sku_passes_the_proposal_and_fails_the_decision(self, api):
        """PRD §3.8: "`APPROVE` additionally requires the contract to still be `ACTIVE` and the
        supplier still `QUALIFIED`, and re-runs every type-specific check above." PRD §2.9:
        "Catalogue numbers are unique within a contract — `ERR_DUPLICATE_SKU`, 409, on `POST
        /coop/master-contracts/{id}/line-items` and `POST
        /coop/contract-amendments/{id}/decision`."

        Design: Corner/Validations/expansion_scope_floor_is_checked_at_proposal_and_sku_uniqueness_only_at_approval
        """
        world = _amendment_world(api)
        first = validate_success(_propose_expansion(api, world, [dict(MOP_ENTRY)], 0.8000), 201)
        validate_success(_decide(api, first["id"], "in scope on review"))

        duplicate = validate_success(
            _propose_expansion(api, world, [dict(DISPENSER_ENTRY)], 0.9000), 201
        )
        refused = _decide(api, duplicate["id"], "second listing of the same sku")

        assert duplicate["status"] == "PROPOSED"
        validate_error(refused, ApiErrorId.ERR_DUPLICATE_SKU, 409)
        assert read_amendment(api, duplicate["id"])["status"] == "PROPOSED"
        _, meta = validate_paginated(
            api.list_line_items_of_contract(world["contract"]["id"], ADMIN_REVIEW)
        )
        assert meta["total_count"] == 2


class TestPriceStabilityWindow:
    def test_13_the_first_approval_moves_the_price_and_starts_the_window(self, api):
        """PRD §3.8: "The `PRICE_ADJUSTMENT` branch sets the target line's
        `base_unit_price_cents` to `new_unit_price_cents`, sets both its `price_effective_from`
        and its `last_price_change_at` to `effective_from`, and increments its
        `price_change_count` by 1."

        Design: Corner/Validations/price_stability_window_is_inclusive_at_exactly_ninety_days
        """
        world = _amendment_world(api)
        proposed = validate_success(_propose_price(api, world, 13000), 201)

        approved = validate_success(_decide(api, proposed["id"], "index adjustment allowed"))

        assert_cents(proposed["price_ceiling_cents"], 13000, "price_ceiling_cents")
        assert approved["status"] == "APPROVED"
        line = read_line_item(api, world["line"]["id"])
        assert_cents(line["base_unit_price_cents"], 13000, "base_unit_price_cents")
        assert_instant(line["last_price_change_at"], CLOCK_TERM_START, "last_price_change_at")
        assert_instant(line["price_effective_from"], CLOCK_TERM_START, "price_effective_from")
        assert line["price_change_count"] == 1

    def test_14_the_second_ceiling_is_recomputed_from_the_new_base(self, api):
        """PRD §3.8: "For a `PRICE_ADJUSTMENT` the server computes and stores
        `price_ceiling_cents` at proposal time and recomputes it at approval."

        Design: Corner/Validations/price_stability_window_is_inclusive_at_exactly_ninety_days
        """
        world = _amendment_world(api)
        first = validate_success(_propose_price(api, world, 13000), 201)
        validate_success(_decide(api, first["id"], "index adjustment allowed"))

        second = validate_success(_propose_price(api, world, 13520), 201)

        assert_cents(second["price_ceiling_cents"], 13520, "price_ceiling_cents")
        assert second["status"] == "PROPOSED"

    def test_15_eighty_nine_days_is_too_soon_and_ninety_days_is_enough(self, api):
        """PRD §3.8: "A `PRICE_ADJUSTMENT` approval carries one further temporal gate: the
        target line's price may only move again once the price-stability window has elapsed,
        meaning `last_price_change_at` is null or the logical clock has reached or passed ninety
        days after `last_price_change_at`." PRD §3.8: "Exactly ninety days later is permitted;
        eighty-nine days is `ERR_PRICE_WINDOW_TOO_SOON`."

        Design: Corner/Validations/price_stability_window_is_inclusive_at_exactly_ninety_days
        """
        world = _amendment_world(api)
        first = validate_success(_propose_price(api, world, 13000), 201)
        validate_success(_decide(api, first["id"], "index adjustment allowed"))
        second = validate_success(_propose_price(api, world, 13520), 201)
        set_clock(api, CLOCK_NOV_29)

        too_soon = _decide(api, second["id"], "second adjustment")

        validate_error(too_soon, ApiErrorId.ERR_PRICE_WINDOW_TOO_SOON, 409)
        assert read_amendment(api, second["id"])["status"] == "PROPOSED"
        held = read_line_item(api, world["line"]["id"])
        assert_cents(held["base_unit_price_cents"], 13000, "base_unit_price_cents")
        assert held["price_change_count"] == 1
        set_clock(api, CLOCK_NOV_30)
        approved = validate_success(_decide(api, second["id"], "window has elapsed"))
        assert approved["status"] == "APPROVED"
        assert_instant(approved["effective_from"], CLOCK_NOV_30, "effective_from")
        moved = read_line_item(api, world["line"]["id"])
        assert_cents(moved["base_unit_price_cents"], 13520, "base_unit_price_cents")
        assert_instant(moved["last_price_change_at"], CLOCK_NOV_30, "last_price_change_at")
        assert moved["price_change_count"] == 2
