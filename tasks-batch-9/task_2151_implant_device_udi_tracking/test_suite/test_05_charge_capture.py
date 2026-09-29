"""Charge capture: the two pricings, the pinned rounding order and the ledger."""

from test_helpers import (
    ApiErrorId,
    CC,
    RI,
    add_unit,
    create_case,
    create_catalog_item,
    create_charge,
    create_lot,
    create_patient,
    create_vendor,
    document_implant,
    get_case,
    get_charge,
    post_charge,
    release_lot,
    setup_posted_charge,
    setup_verified_implant,
    set_clock,
    start_case,
    validate_error,
    validate_success,
    verify_record,
)

HIGH_COST_STEM = {
    "device_identifier": "00812345678905",
    "description": "Ti Femoral Stem",
    "category": "HIGH_COST_IMPLANT",
    "list_charge_cents": 1_240_000,
    "charge_code": "CDM-77140",
}


class TestProvisionalVersusFinalPricing:
    def test_final_variant_reprices_from_acquisition_cost_and_writes_the_variance(
        self, api
    ):
        """PRD §3.6: "Both pricings run the same four-step ladder and differ only in
        **which base they start from**. The provisional pricing starts from the
        catalog item's `list_charge_cents` — the chargemaster list. The final
        pricing starts from the device unit's `acquisition_cost_cents` — what this
        exact serial cost. From that base, a markup percentage is selected from a
        tier ladder whose lower bounds are inclusive and whose upper bounds are
        exclusive: a base below 50,000 cents takes 60 percent; a base of at least
        50,000 cents and below 250,000 cents takes 45 percent; a base of at least
        250,000 cents and below 1,000,000 cents takes 32 percent; a base of
        1,000,000 cents or more takes 22 percent."
        PRD §3.6: "Finalizing a posted line reruns the pricing under the final
        variant, writes `final_charge_cents`, writes `variance_cents` as the line's
        `provisional_charge_cents` minus its `final_charge_cents` — provisional
        first, final second, so an over-priced provisional yields a positive
        variance — and sets `capture_variant` to `FINAL`."

        Design: Difficulty/dual_variant_calc/implant_charge_provisional_list_vs_final_acquisition
        """
        world = setup_posted_charge(
            unit_cost=462_500,
            consigned=True,
            catalog_overrides=HIGH_COST_STEM,
            lot_overrides={"lot_number": "L-4401", "expiration_date": "2027-06-30"},
        )
        assert world["charge"]["provisional_charge_cents"] == 1_512_800

        finalized = validate_success(api.finalize_charge(world["charge"]["id"], RI), 200)
        assert finalized["final_charge_cents"] == 610_500
        assert finalized["variance_cents"] == 902_300
        assert finalized["capture_variant"] == "FINAL"
        assert finalized["effective_charge_cents"] == 610_500

    def test_a_high_cost_variance_forks_the_line_into_correction_required(self, api):
        """PRD §3.6: "It then **forks on the computed numbers alone, never on any
        request field**: when the catalog item's `category` is `HIGH_COST_IMPLANT`
        and the absolute value of `variance_cents` is at least 25,000 cents, the
        line moves `POSTED → CORRECTION_REQUIRED`; in every other case — a smaller
        absolute variance, or any non-high-cost category regardless of variance —
        it moves `POSTED → FINALIZED`."
        PRD §3.11: "Otherwise, if any charge line belonging to this case's records
        has a `status` of `DRAFT`, `POSTED` or `CORRECTION_REQUIRED`, the posture is
        `BLOCKED_CHARGE`."

        Design: Difficulty/dual_variant_calc/implant_charge_provisional_list_vs_final_acquisition
        """
        world = setup_posted_charge(
            unit_cost=462_500,
            consigned=True,
            catalog_overrides=HIGH_COST_STEM,
            lot_overrides={"lot_number": "L-4401", "expiration_date": "2027-06-30"},
        )

        finalized = validate_success(api.finalize_charge(world["charge"]["id"], RI), 200)
        assert finalized["status"] == "CORRECTION_REQUIRED"

        case = get_case(world["case"]["id"])
        assert case["total_posted_charge_cents"] == 610_500
        assert case["readiness_status"] == "BLOCKED_CHARGE"


class TestCaseLedgerRounding:
    def test_each_line_is_rounded_before_the_case_total_sums_them(self, api):
        """PRD §3.6: "The arithmetic order is pinned. First the per-unit amount is
        computed as the base multiplied by one plus the markup percentage, and that
        per-unit amount is rounded half up to a whole cent **before** anything else
        happens."
        PRD §2.9: "At the case level, each charge line is already a whole-cent
        integer, and the case total is the plain integer sum of those
        already-rounded lines; summing unrounded per-line products and rounding once
        at the end is incorrect."

        Design: Difficulty/combinatorial_formula/case_total_rounds_each_charge_line_before_summing
        """
        world = _two_line_case()

        assert world["charge_a"]["provisional_charge_cents"] == 87_015
        assert world["charge_b"]["provisional_charge_cents"] == 87_044

        post_charge(world["charge_a"]["id"])
        post_charge(world["charge_b"]["id"])

        assert get_case(world["case"]["id"])["total_posted_charge_cents"] == 174_059

    def test_the_case_total_is_not_the_rounded_sum_of_unrounded_products(self, api):
        """PRD §2.9: "Rounding **order** is pinned everywhere it could plausibly be
        reordered, and reordering produces different, wrong answers."
        PRD §2.9: "At the case level, each charge line is already a whole-cent
        integer, and the case total is the plain integer sum of those
        already-rounded lines; summing unrounded per-line products and rounding once
        at the end is incorrect."

        Design: Difficulty/combinatorial_formula/case_total_rounds_each_charge_line_before_summing
        """
        world = _two_line_case()
        post_charge(world["charge_a"]["id"])
        post_charge(world["charge_b"]["id"])

        total = get_case(world["case"]["id"])["total_posted_charge_cents"]
        assert total != 174_058, (
            "174058 is the answer produced by summing unrounded per-line products "
            "and rounding once at the end, which the PRD forbids"
        )
        assert total == 174_059

    def test_quantity_multiplies_only_after_the_per_unit_amount_is_rounded(self, api):
        """PRD §3.6: "Only then is the rounded per-unit amount multiplied by the
        line's `quantity` to give the line amount."
        PRD §3.6: "The line is created in `DRAFT` with its `charge_code` copied from
        the catalog item reached through the implanted unit and its lot, with
        `capture_variant` set to `PROVISIONAL`, with `final_charge_cents` and
        `variance_cents` null, and with `provisional_charge_cents` computed
        immediately."
        PRD §3.6: "Lines for `STANDARD_IMPLANT` and `ACCESSORY` items are never
        capped."

        Design: Corner/calculations/charge_quantity_multiplies_after_per_unit_rounding
        """
        world = setup_verified_implant(
            unit_cost=40_000,
            catalog_overrides={
                "device_identifier": "00812345678929",
                "description": "Bone Screw A",
                "category": "STANDARD_IMPLANT",
                "list_charge_cents": 60_010,
                "charge_code": "CDM-77161",
            },
            lot_overrides={"lot_number": "L-A1", "expiration_date": "2027-06-30"},
        )

        charge = validate_success(
            api.create_charge(world["record"]["id"], {"quantity": 3}, RI), 201
        )
        assert charge["provisional_charge_cents"] == 261_045
        assert charge["provisional_charge_cents"] != 261_044
        assert charge["charge_code"] == "CDM-77161"
        assert charge["capture_variant"] == "PROVISIONAL"
        assert charge["final_charge_cents"] is None
        assert charge["variance_cents"] is None

        post_charge(charge["id"])
        assert get_case(world["case"]["id"])["total_posted_charge_cents"] == 261_045


class TestChargeLedgerCompensation:
    def test_post_then_void_returns_the_case_total_to_zero(self, api):
        """PRD §3.6: "Because the case total is defined as the sum of
        `effective_charge_cents` over exactly those charge lines of the case's
        records whose `status` is `POSTED`, `CORRECTION_REQUIRED` or `FINALIZED` —
        `DRAFT` and `VOIDED` lines contribute nothing — voiding a posted line
        returns the case total precisely to its pre-posting value."
        PRD §3.6: "Voiding a line is the compensating action and is permitted from
        `DRAFT`, `POSTED` or `CORRECTION_REQUIRED`, all three moving to the terminal
        `VOIDED`; all three re-derive the case's `total_posted_charge_cents` and
        `readiness_status`."

        Design: Difficulty/compensating_invariant/case_charge_ledger_conserved_across_post_void_roundtrip
        """
        world = setup_verified_implant(unit_cost=400_000)
        charge = create_charge(world["record"]["id"])
        assert charge["provisional_charge_cents"] == 792_000
        assert get_case(world["case"]["id"])["total_posted_charge_cents"] == 0

        post_charge(charge["id"])
        assert get_case(world["case"]["id"])["total_posted_charge_cents"] == 792_000

        voided = validate_success(api.void_charge(charge["id"], RI), 200)
        assert voided["status"] == "VOIDED"
        assert get_case(world["case"]["id"])["total_posted_charge_cents"] == 0

    def test_voiding_restores_the_case_readiness_posture(self, api):
        """PRD §3.11: "Otherwise, if any charge line belonging to this case's
        records has a `status` of `DRAFT`, `POSTED` or `CORRECTION_REQUIRED`, the
        posture is `BLOCKED_CHARGE`."
        PRD §3.6: "Posting a draft line moves it `DRAFT → POSTED`, which requires
        that the parent implant record is `VERIFIED` or `AMENDED` — posting against
        an unverified record is rejected with `ERR_INVALID_RECORD_STATE`, and
        posting a line that is not in `DRAFT` with `ERR_INVALID_LIFECYCLE_STATE`.
        Posting re-derives the case's `total_posted_charge_cents` and
        `readiness_status`."

        Design: Difficulty/compensating_invariant/case_charge_ledger_conserved_across_post_void_roundtrip
        """
        world = setup_verified_implant(unit_cost=400_000)
        charge = create_charge(world["record"]["id"])

        post_charge(charge["id"])
        assert get_case(world["case"]["id"])["readiness_status"] == "BLOCKED_CHARGE"

        validate_success(api.void_charge(charge["id"], RI), 200)
        assert get_case(world["case"]["id"])["readiness_status"] == "READY"

        after = get_charge(charge["id"])
        assert after["status"] == "VOIDED"
        assert after["final_charge_cents"] is None
        assert after["variance_cents"] is None


class TestHighCostCapAndCorrection:
    def test_cap_threshold_and_acknowledgement_on_high_cost_lines(self, api):
        """PRD §3.6: "Finally, and only for a catalog item whose `category` is
        `HIGH_COST_IMPLANT`, the line amount is capped: it becomes the lesser of the
        computed line amount and the base plus 750,000 cents. The cap is applied
        *after* the quantity multiply, not before it."
        PRD §3.6: "It then **forks on the computed numbers alone, never on any
        request field**: when the catalog item's `category` is `HIGH_COST_IMPLANT`
        and the absolute value of `variance_cents` is at least 25,000 cents, the
        line moves `POSTED → CORRECTION_REQUIRED`; in every other case — a smaller
        absolute variance, or any non-high-cost category regardless of variance —
        it moves `POSTED → FINALIZED`."
        PRD §3.6: "The analyst supplies `acknowledged_variance_cents`, which must
        equal the line's stored `variance_cents` exactly — same sign, same magnitude
        — or the request is rejected with `ERR_VARIANCE_ACK_MISMATCH`. A correct
        acknowledgement moves the line `CORRECTION_REQUIRED → FINALIZED` and
        re-derives the case's `readiness_status`."
        PRD §3.11: "The close gate then maps each blocked posture to its own error,
        tried in exactly the same top-to-bottom order as the derivation above:
        `BLOCKED_RESERVATION` and `BLOCKED_DOCUMENTATION` both surface as
        `ERR_CASE_READINESS_UNMET`, `BLOCKED_REGISTRY` as `ERR_REGISTRY_OUTSTANDING`,
        and `BLOCKED_CHARGE` as `ERR_CHARGE_VARIANCE_UNRESOLVED`."

        Design: Corner/calculations/high_cost_markup_cap_and_finalize_variance_threshold_branches
        """
        set_clock("2026-09-01T00:00:00Z")
        vendor = create_vendor()
        catalog_cap = create_catalog_item(
            vendor["id"],
            device_identifier="00812345670001",
            description="Custom Megaprosthesis",
            category="HIGH_COST_IMPLANT",
            list_charge_cents=4_000_000,
            charge_code="CDM-77300",
        )
        catalog_var = create_catalog_item(
            vendor["id"],
            device_identifier="00812345670018",
            description="Knee Insert",
            category="HIGH_COST_IMPLANT",
            list_charge_cents=1_000_000,
            charge_code="CDM-77310",
        )

        lot_cap = create_lot(
            catalog_cap["id"], lot_number="LC-1", expiration_date="2027-06-30"
        )
        unit_cap = add_unit(lot_cap["id"], "SN-C1", 4_000_000)
        release_lot(lot_cap["id"])

        lot_var = create_lot(
            catalog_var["id"], lot_number="LV-1", expiration_date="2027-06-30"
        )
        unit_v1 = add_unit(lot_var["id"], "SN-V1", 930_000)
        unit_v2 = add_unit(lot_var["id"], "SN-V2", 905_303)
        release_lot(lot_var["id"])

        patient = create_patient()
        case = create_case(patient["id"], scheduled_end_utc="2026-09-10T14:00:00Z")
        start_case(case["id"])

        record_cap = document_implant(case["id"], unit_cap, anatomic_site="FEMUR_TOTAL")
        record_v1 = document_implant(case["id"], unit_v1, anatomic_site="TIBIA")
        record_v2 = document_implant(
            case["id"], unit_v2, anatomic_site="TIBIA", laterality="RIGHT"
        )
        for record in (record_cap, record_v1, record_v2):
            verify_record(record["id"])

        charge_cap = create_charge(record_cap["id"])
        charge_v1 = create_charge(record_v1["id"])
        charge_v2 = create_charge(record_v2["id"])
        for charge in (charge_cap, charge_v1, charge_v2):
            post_charge(charge["id"])

        # The uncapped 4,000,000 x 1.22 = 4,880,000 exceeds base + 750,000.
        assert charge_cap["provisional_charge_cents"] == 4_750_000
        assert charge_v1["provisional_charge_cents"] == 1_220_000

        finalized_v1 = validate_success(api.finalize_charge(charge_v1["id"], RI), 200)
        assert finalized_v1["final_charge_cents"] == 1_227_600
        assert finalized_v1["variance_cents"] == -7_600
        assert finalized_v1["status"] == "FINALIZED"

        finalized_v2 = validate_success(api.finalize_charge(charge_v2["id"], RI), 200)
        assert finalized_v2["final_charge_cents"] == 1_195_000
        assert finalized_v2["variance_cents"] == 25_000
        assert finalized_v2["status"] == "CORRECTION_REQUIRED"

        validate_error(
            api.close_case(case["id"], CC),
            ApiErrorId.ERR_CHARGE_VARIANCE_UNRESOLVED,
            409,
        )
        validate_error(
            api.correct_charge(
                charge_v2["id"], {"acknowledged_variance_cents": 24_999}, RI
            ),
            ApiErrorId.ERR_VARIANCE_ACK_MISMATCH,
            422,
        )

        corrected = validate_success(
            api.correct_charge(
                charge_v2["id"], {"acknowledged_variance_cents": 25_000}, RI
            ),
            200,
        )
        assert corrected["status"] == "FINALIZED"


def _two_line_case() -> dict:
    """Two STANDARD_IMPLANT models whose list prices both land in the 45 percent
    tier and whose per-unit amounts both fall exactly on a half cent."""
    set_clock("2026-09-01T00:00:00Z")
    vendor = create_vendor()
    catalog_a = create_catalog_item(
        vendor["id"],
        device_identifier="00812345678929",
        description="Bone Screw A",
        category="STANDARD_IMPLANT",
        list_charge_cents=60_010,
        charge_code="CDM-77161",
    )
    catalog_b = create_catalog_item(
        vendor["id"],
        device_identifier="00812345678936",
        description="Bone Screw B",
        category="STANDARD_IMPLANT",
        list_charge_cents=60_030,
        charge_code="CDM-77162",
    )

    lot_a = create_lot(catalog_a["id"], lot_number="L-A1", expiration_date="2027-06-30")
    unit_a = add_unit(lot_a["id"], "SNA-0001", 40_000)
    release_lot(lot_a["id"])

    lot_b = create_lot(catalog_b["id"], lot_number="L-B1", expiration_date="2027-06-30")
    unit_b = add_unit(lot_b["id"], "SNB-0001", 40_000)
    release_lot(lot_b["id"])

    patient = create_patient(mrn="MRN-2002", display_name="Pat Two")
    case = create_case(
        patient["id"],
        case_number="CASE-2",
        or_room_code="OR-5",
        scheduled_start_utc="2026-09-11T08:00:00Z",
        scheduled_end_utc="2026-09-11T10:00:00Z",
        surgeon_code="SURG-4",
    )
    start_case(case["id"])

    record_a = document_implant(case["id"], unit_a, anatomic_site="TIBIA")
    record_b = document_implant(
        case["id"], unit_b, anatomic_site="TIBIA", laterality="RIGHT"
    )
    verify_record(record_a["id"])
    verify_record(record_b["id"])

    return {
        "case": case,
        "charge_a": create_charge(record_a["id"]),
        "charge_b": create_charge(record_b["id"]),
    }
