"""Lot reservations, closings, the lot pricing engine, and ownership gates."""
from test_helpers import (
    DEV,
    LENDER,
    ApiErrorId,
    assert_closing,
    create_active_agreement,
    create_builder,
    finalize_closing,
    get_closing,
    get_lot,
    make_builder_rep_headers,
    open_closing,
    reserve_and_open_closing,
    reserve_lot,
    setup_selling_scenario,
    setup_two_agreement_pricing_scenario,
    validate_error,
    validate_success,
)


class TestLotPricingEngine:
    def test_closing_price_compounds_quarterly_escalator(self, api):
        """PRD §3.4: "First, it counts the quarters elapsed since the agreement's `effective_date` at the current logical clock: whole elapsed months are twelve times the difference in calendar years plus the difference in calendar months, reduced by one when the clock's day-of-month falls earlier than the effective date's day-of-month; elapsed quarters are that whole-month count divided by three and rounded down, never below zero. Second, the escalated price is the `base_lot_price_cents` multiplied by one plus the quarterly escalator rate (the basis-point rate over ten thousand), that factor raised to the power of the elapsed-quarters count — the escalator compounds quarterly."
        PRD §3.4: "Fourth, a volume discount is selected from the agreement's `closed_lot_count` at that moment: ten or more closed lots earns a 500-basis-point discount, five through nine closed lots earns 250 basis points, and four or fewer earns none. Fifth, the capped price is reduced by the selected discount fraction, and the result is rounded half-up to whole cents — this is the only rounding step in the entire calculation — and frozen as the closing's `contract_price_cents`."

        Design: Difficulty/combinatorial_formula/lot_price_escalator_cap_tier
        """
        scenario = setup_two_agreement_pricing_scenario()
        closing = open_closing(scenario["lots"][0]["id"],
                               scenario["agreement"]["id"],
                               scenario["builder"]["id"])
        assert_closing(closing)
        # two quarters elapsed (2026-01-01 -> 2026-08-01): 5000000 * 1.03^2,
        # under the 120% cap of 6000000, zero closed lots -> no tier discount
        assert closing["contract_price_cents"] == 5304500
        # §3.5: release price frozen at the loan's 8000 bp floor of contract
        assert closing["release_price_cents"] == 4243600

    def test_closing_price_pinned_by_cap(self, api):
        """PRD §3.4: "Third, the cap is the base price multiplied by `price_cap_bp` over ten thousand, and the escalated figure is taken at the lesser of itself and the cap."

        Design: Difficulty/combinatorial_formula/lot_price_escalator_cap_tier
        """
        scenario = setup_two_agreement_pricing_scenario()
        closing = open_closing(scenario["lots"][1]["id"],
                               scenario["agreement_b"]["id"],
                               scenario["builder_b"]["id"])
        # uncapped 5000000 * 1.15^2 = 6612500 is pinned down by min() to the
        # 120% cap 6000000 even though both agreements share base, effective
        # date, and quarter count
        assert closing["contract_price_cents"] == 6000000


class TestLotParallelDimensions:
    def test_reserve_moves_only_sales_dimension(self, api):
        """PRD §3.2: "A lot carries two independent state dimensions throughout its life: `sales_status` walks `PLATTED`, `RESERVED`, `UNDER_CONTRACT`, and terminal `CLOSED`, while `lien_status` walks `ENCUMBERED`, `RELEASE_PENDING`, and terminal `RELEASED`; the two dimensions evolve independently but share the triggers described in §3.5, and a lot's `reserved_agreement_id` is null whenever it sits unreserved in `PLATTED`."
        PRD §3.5: "The closing starts `PENDING` with `payment_applied_cents` at zero and `finalized_at` null, and its creation advances the lot on both dimensions at once — `sales_status` from `RESERVED` to `UNDER_CONTRACT` and `lien_status` from `ENCUMBERED` to `RELEASE_PENDING`."

        Design: Difficulty/non_linear_state_machine/lot_parallel_sales_lien_dimensions
        """
        scenario = setup_selling_scenario(num_lots=3)
        lot = scenario["lots"][0]
        builder_id = scenario["builder"]["id"]
        agreement_id = scenario["agreement"]["id"]

        reserved = reserve_lot(lot["id"], agreement_id, builder_id)
        assert reserved["sales_status"] == "RESERVED"
        assert reserved["lien_status"] == "ENCUMBERED"  # lien dimension untouched
        assert reserved["reserved_agreement_id"] == agreement_id

        open_closing(lot["id"], agreement_id, builder_id)
        under_contract = get_lot(lot["id"])
        assert under_contract["sales_status"] == "UNDER_CONTRACT"
        assert under_contract["lien_status"] == "RELEASE_PENDING"

    def test_closing_cancel_reverts_both_dimensions(self, api):
        """PRD §3.5: "Alternatively, a `PENDING` closing may be cancelled — by the `BuilderRep` whose builder owns the agreement, or by a `DeveloperOperator` — moving it to terminal `CANCELLED` and reverting the lot: `sales_status` returns from `UNDER_CONTRACT` to `RESERVED` (the reservation stands) and `lien_status` returns from `RELEASE_PENDING` to `ENCUMBERED`."

        Design: Difficulty/non_linear_state_machine/lot_parallel_sales_lien_dimensions
        """
        scenario = setup_selling_scenario(num_lots=3)
        lot = scenario["lots"][0]
        builder_id = scenario["builder"]["id"]
        agreement_id = scenario["agreement"]["id"]

        closing = reserve_and_open_closing(lot["id"], agreement_id, builder_id)
        cancelled = validate_success(api.cancel_closing(
            closing["id"], make_builder_rep_headers(builder_id)))
        assert cancelled["status"] == "CANCELLED"
        reverted = get_lot(lot["id"])
        assert reverted["sales_status"] == "RESERVED"
        assert reverted["lien_status"] == "ENCUMBERED"
        # the reservation stands
        assert reverted["reserved_agreement_id"] == agreement_id


class TestReservationGates:
    def test_reserve_under_draft_agreement_rejected(self, api):
        """PRD §3.5: "A `BuilderRep` reserves a lot by supplying the `agreement_id` of an agreement their builder owns; the check chain requires the agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise), the lot's phase to be `ACTIVE` (`ERR_PHASE_INVALID_STATE` otherwise), the agreement's parcel to be the same parcel the lot's phase belongs to (`ERR_AGREEMENT_PARCEL_MISMATCH` otherwise), and the lot's `sales_status` to be `PLATTED` (`ERR_LOT_INVALID_STATE` otherwise)."

        Design: Difficulty/cross_entity_state_dependency/reserve_requires_agreement_active
        """
        scenario = setup_selling_scenario(
            num_lots=2, activate=False,
            agreement_overrides={"scheduled_lot_count": 2})
        resp = api.reserve_lot(
            scenario["lots"][0]["id"],
            {"agreement_id": scenario["agreement"]["id"]},
            make_builder_rep_headers(scenario["builder"]["id"]))
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    def test_reserve_succeeds_after_agreement_activation(self, api):
        """PRD §3.5: "A successful reservation moves the lot from `PLATTED` to `RESERVED`, records the holding agreement on `reserved_agreement_id`, decrements the parcel's `lots_available_count` by one, and increments both the lot's `version` and the parcel's `version`."
        PRD §3.4: "Activating it moves it from `DRAFT` to `ACTIVE` and requires the parcel to be `ACQUIRED`, failing otherwise with `ERR_PARCEL_NOT_ACQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/reserve_requires_agreement_active
        """
        scenario = setup_selling_scenario(
            num_lots=2, activate=False,
            agreement_overrides={"scheduled_lot_count": 2})
        validate_success(api.activate_agreement(scenario["agreement"]["id"], DEV))
        reserved = validate_success(api.reserve_lot(
            scenario["lots"][0]["id"],
            {"agreement_id": scenario["agreement"]["id"]},
            make_builder_rep_headers(scenario["builder"]["id"])))
        assert reserved["sales_status"] == "RESERVED"
        assert reserved["reserved_agreement_id"] == scenario["agreement"]["id"]

    def test_reserve_with_other_builders_agreement_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `BuilderRep`, `X-User-ID` is the `id` of the acting `Builder`; ownership checks on any resource that references a builder compare the takedown agreement's `builder_id` to `X-User-ID`, so a builder representative may reserve lots, open closings, cancel closings, or amend pricing terms only under their own builder's agreements."

        Design: Corner/rbac/builder_cannot_reserve_with_other_builders_agreement
        """
        scenario = setup_selling_scenario(
            num_lots=1, agreement_overrides={"scheduled_lot_count": 1},
            builder_license="LIC-O1")
        other_builder = create_builder(
            builder_name="OWB2", license_number="LIC-O2",
            contact_email="o2@example.com")
        resp = api.reserve_lot(
            scenario["lots"][0]["id"],
            {"agreement_id": scenario["agreement"]["id"]},
            make_builder_rep_headers(other_builder["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestClosingCreationGates:
    def test_closing_create_without_active_loan_rejected(self, api):
        """PRD §3.5: "Creation also anchors the closing to the parcel's development loan: the candidate set is the parcel's loans in `ACTIVE` status, at most one of which can exist (§3.6 explains the uniqueness rule), and an empty set is rejected with `ERR_NO_ACTIVE_LOAN`; the selected loan's `id` is recorded on the closing's `loan_id`."

        Design: Corner/errors/error_no_active_loan_on_closing
        """
        scenario = setup_selling_scenario(
            num_lots=1, loan="draft",
            agreement_overrides={"scheduled_lot_count": 2})
        lot = scenario["lots"][0]
        builder_id = scenario["builder"]["id"]
        agreement_id = scenario["agreement"]["id"]
        reserve_lot(lot["id"], agreement_id, builder_id)
        resp = api.create_closing(
            {"lot_id": lot["id"], "agreement_id": agreement_id},
            make_builder_rep_headers(builder_id))
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_LOAN)
        after = get_lot(lot["id"])
        assert after["sales_status"] == "RESERVED"
        assert after["lien_status"] == "ENCUMBERED"

    def test_closing_create_with_wrong_agreement_rejected(self, api):
        """PRD §3.5: "The lot must currently be `RESERVED` under exactly that agreement — a lot whose `reserved_agreement_id` names any other agreement, or that is not reserved at all, is rejected with `ERR_LOT_NOT_RESERVED_BY_AGREEMENT` — and the agreement must still be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise)."

        Design: Corner/errors/error_lot_not_reserved_by_agreement
        """
        scenario = setup_selling_scenario(
            num_lots=1, agreement_overrides={"scheduled_lot_count": 1},
            builder_license="LIC-M1")
        builder_two = create_builder(
            builder_name="MMB2", license_number="LIC-M2",
            contact_email="m2@example.com")
        agreement_two = create_active_agreement(
            scenario["parcel"]["id"], builder_two["id"], scheduled_lot_count=1)
        lot = scenario["lots"][0]
        reserve_lot(lot["id"], scenario["agreement"]["id"],
                    scenario["builder"]["id"])
        resp = api.create_closing(
            {"lot_id": lot["id"], "agreement_id": agreement_two["id"]},
            make_builder_rep_headers(builder_two["id"]))
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_RESERVED_BY_AGREEMENT)


class TestClosingDisposal:
    def test_finalize_twice_rejected(self, api):
        """PRD §3.5: "Finalizing or cancelling a closing that is no longer `PENDING` is rejected with `ERR_CLOSING_INVALID_STATE`."

        Design: Corner/state_machines/closing_finalize_twice_second_returns_invalid_state
        """
        scenario = setup_selling_scenario(
            num_lots=1, agreement_overrides={"scheduled_lot_count": 2})
        closing = reserve_and_open_closing(
            scenario["lots"][0]["id"], scenario["agreement"]["id"],
            scenario["builder"]["id"])
        finalize_closing(closing["id"])
        resp = api.finalize_closing(closing["id"], LENDER)
        validate_error(resp, ApiErrorId.ERR_CLOSING_INVALID_STATE)
        assert get_closing(closing["id"])["status"] == "CLOSED"
        lot = get_lot(scenario["lots"][0]["id"])
        assert lot["sales_status"] == "CLOSED"
        assert lot["lien_status"] == "RELEASED"

    def test_developer_cannot_finalize_closing(self, api):
        """PRD §3.5: "Finalization is the lender's act. A `LenderOfficer` finalizes a `PENDING` closing, moving it to terminal `CLOSED` and firing a seven-link cascade:"
        PRD §2.1: "A request whose role is not permitted for the target endpoint — or that fails an entity-backed ownership check — is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/developer_cannot_finalize_closing_returns_403
        """
        scenario = setup_selling_scenario(
            num_lots=1, agreement_overrides={"scheduled_lot_count": 1})
        closing = reserve_and_open_closing(
            scenario["lots"][0]["id"], scenario["agreement"]["id"],
            scenario["builder"]["id"])
        resp = api.finalize_closing(closing["id"], DEV)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_closing(closing["id"])["status"] == "PENDING"


class TestImmediateConsistency:
    def test_reserve_mutation_visible_immediately(self, api):
        """PRD §2.4: "`version` (integer): a system-managed integer that increments by exactly one on every mutation."
        PRD §3.5: "A successful reservation moves the lot from `PLATTED` to `RESERVED`, records the holding agreement on `reserved_agreement_id`, decrements the parcel's `lots_available_count` by one, and increments both the lot's `version` and the parcel's `version`."

        Design: Corner/consistency_model/immediate_consistency_visible_in_same_response
        """
        scenario = setup_selling_scenario(
            num_lots=1, agreement_overrides={"scheduled_lot_count": 1})
        lot = scenario["lots"][0]
        observed_version = lot["version"]

        reserved = reserve_lot(lot["id"], scenario["agreement"]["id"],
                               scenario["builder"]["id"])
        assert reserved["sales_status"] == "RESERVED"
        assert reserved["reserved_agreement_id"] == scenario["agreement"]["id"]
        assert reserved["version"] == observed_version + 1

        reread = get_lot(lot["id"])
        assert reread["sales_status"] == "RESERVED"
        assert reread["version"] == reserved["version"]
