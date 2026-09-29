"""Two ledgers that must be restored exactly when a decision is reversed.

The money mirror is `accrued_liability_cents`; the inventory mirror is
`reman_available_count` with its derived `reman_stock_state`. Each is proved by
driving a dispute to a downgrade and reading the mirror afterwards — and, for the
inventory, by re-issuing the very request the depleted pool had refused.
"""

from test_helpers import (
    CANONICAL_SNAPSHOTS,
    ApiErrorId,
    add_assessment,
    add_claim,
    add_sibling_vehicle,
    adjudicate,
    adjudicate_payload,
    assert_lab_deviation,
    assert_reman_stock,
    assert_settlement_waterfall,
    file_dispute,
    make_adjudicator_headers,
    read_claim,
    read_pack,
    read_program,
    record_lab_result,
    resolve_dispute,
    resolve_payload,
    setup_adjudicated_claim_world,
    setup_submitted_claim_world,
    stock_reman_packs,
    validate_error,
    validate_success,
    ADJUDICATOR_1_ID,
    ADJUDICATOR_2_ID,
)


def _sibling_claim(api, world, vin: str, serial_number: str) -> dict:
    """A second identically telemetered vehicle carried to a SUBMITTED claim."""
    sibling = add_sibling_vehicle(
        api,
        world,
        vin=vin,
        serial_number=serial_number,
        snapshots=CANONICAL_SNAPSHOTS,
    )
    add_assessment(api, sibling, module_fault_positions=[3, 7])
    add_claim(api, sibling)
    return sibling


class TestLiabilityLedgerReversal:
    """The accrual must fall by exactly the reversed claim's own booked total."""

    def test_a_downgrade_removes_one_of_two_identical_accruals_and_only_once(self, api):
        """741184 becomes 370592, not zero and not 741184, and a second resolve is refused.

        PRD 3.9: "`RESOLVED_DOWNGRADED` on an `APPROVED_MODULE` claim collapses it to
        `DENIED`: the claim's `oem_total_cents` is subtracted from
        `accrued_liability_cents`, then `remedy_cost_cents`, `owner_share_cents`,
        `oem_share_cents` and `oem_total_cents` are all set to zero and
        `denial_reason` is set to `DISPUTE_DOWNGRADE`."

        PRD 3.9: "In every reversal the ledger correction is a
        subtract-then-recompute-then-add sequence, never an in-place adjustment of the
        difference, so the program's `accrued_liability_cents` always equals the sum of
        the current `oem_total_cents` of every accruing claim."

        Design: Difficulty/compensating_invariant/accrued_liability_ledger_reverses_exactly_on_dispute_downgrade
        """
        first = setup_adjudicated_claim_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000091"},
            pack_overrides={"serial_number": "PK-0091"},
            adjudicator_id=ADJUDICATOR_1_ID,
        )
        second = _sibling_claim(api, first, "5YJ3E1EA7KF000092", "PK-0092")
        adjudicate(api, second, "MODULE_REPLACEMENT", adjudicator_id=ADJUDICATOR_1_ID)

        assert first["claim"]["oem_total_cents"] == 370592
        assert second["claim"]["oem_total_cents"] == 370592
        assert read_program(api, first["program_id"])["accrued_liability_cents"] == 741184

        dispute = file_dispute(
            api,
            second,
            lab_name="Cascade Cell Labs",
            owner_statement="capacity measured higher than the OEM figure",
        )
        assert dispute["dispute_status"] == "LAB_ASSIGNED"
        assert dispute["nominal_basis_kwh"] == 80.000
        assert dispute["oem_retention_pct"] == 70.00

        # 58.400 / 80.000 is 73.00 %, three points above the frozen OEM figure and
        # therefore outside the 2.00-point tolerance: one retest is mandatory.
        first_result = record_lab_result(
            api, second, 58.400, lab_report_reference="CCL-2026-0801"
        )
        assert first_result["lab_retention_pct"] == 73.00
        assert first_result["deviation_pct"] == 3.00
        assert_lab_deviation(first_result)
        assert first_result["retest_count"] == 1
        assert first_result["dispute_status"] == "LAB_ASSIGNED"
        assert read_program(api, first["program_id"])["accrued_liability_cents"] == 741184

        retest = record_lab_result(
            api, second, 58.400, lab_report_reference="CCL-2026-0801-RETEST"
        )
        assert retest["dispute_status"] == "LAB_RESULT_RECEIVED"
        assert retest["deviation_pct"] == 3.00

        resolved = resolve_dispute(
            api,
            second,
            adjudicator_id=ADJUDICATOR_2_ID,
            resolution_note="lab exceeds OEM by more than tolerance",
        )
        assert resolved["dispute_status"] == "RESOLVED_DOWNGRADED"

        denied = read_claim(api, second["claim_id"])
        assert denied["adjudication_status"] == "DENIED"
        assert denied["denial_reason"] == "DISPUTE_DOWNGRADE"
        assert denied["remedy_cost_cents"] == 0
        assert denied["owner_share_cents"] == 0
        assert denied["oem_share_cents"] == 0
        # PRD 3.9's DISPUTE_DOWNGRADE collapse zeroes exactly `remedy_cost_cents`,
        # `owner_share_cents`, `oem_share_cents` and `oem_total_cents` -- unlike the two
        # other denial paths it does not name `admin_fee_cents`, so it is unasserted.
        assert denied["oem_total_cents"] == 0

        # Exactly claim two's booking left the ledger, and claim one is untouched.
        assert read_program(api, first["program_id"])["accrued_liability_cents"] == 370592
        untouched = read_claim(api, first["claim_id"])
        assert untouched["adjudication_status"] == "APPROVED_MODULE"
        assert untouched["oem_total_cents"] == 370592

        validate_error(
            api.resolve_dispute(
                second["dispute_id"],
                resolve_payload("attempted second resolution"),
                make_adjudicator_headers(ADJUDICATOR_2_ID),
            ),
            ApiErrorId.ERR_DISPUTE_RESOLVED.value,
            expected_status=409,
        )
        assert read_program(api, first["program_id"])["accrued_liability_cents"] == 370592


class TestRemanInventoryRelease:
    """The inventory mirror is proved restored by re-issuing the refused approval."""

    def test_the_downgrade_returns_the_pack_and_the_refused_approval_then_succeeds(
        self, api
    ):
        """One pack, two pack approvals: the second only fits once the first is reversed.

        PRD 3.9: "`RESOLVED_DOWNGRADED` on an `APPROVED_PACK` claim collapses it to
        `APPROVED_MODULE`: the reserved pack returns from `RESERVED` to `STOCK`, the
        program's `reman_available_count` rises by one, `reman_stock_state` becomes
        `AVAILABLE` because the count is now above zero, the claim's
        `replacement_pack_id` is cleared, and the ledger is corrected by subtracting
        the old `oem_total_cents`, recomputing the settlement for a module
        replacement, and adding the new `oem_total_cents`."

        PRD 3.5: "If the remanufactured pool is empty, the program's
        `allow_new_pack_substitution` decides what happens. When it is false, the
        adjudication is refused with `ERR_NO_REMAN_PACK_AVAILABLE`."

        Design: Difficulty/compensating_invariant/reman_inventory_count_released_by_dispute_downgrade_unblocks_refused_approval
        """
        # PRD 3.5 makes a pack approval conditional on "the center of record's
        # `hv_certification_level` be exactly `L3` and its `has_pack_lift` be true", and
        # PRD 3.1 defaults `has_pack_lift` to false, so the centre of record is
        # registered pack-capable. The sibling below shares this same centre.
        first = setup_submitted_claim_world(
            api,
            center_overrides={"hv_certification_level": "L3", "has_pack_lift": True},
            vehicle_overrides={"vin": "5YJ3E1EA7KF000101"},
            pack_overrides={"serial_number": "PK-0101"},
        )
        second = _sibling_claim(api, first, "5YJ3E1EA7KF000102", "PK-0102")

        reman = stock_reman_packs(
            api, [{"serial_number": "PK-RM-01", "refurb_soh_pct": 92.00}]
        )[0]
        assert reman["status"] == "STOCK"
        assert_reman_stock(read_program(api, first["program_id"]), 1, "AVAILABLE")

        # A pack replacement over a module recommendation is an upgrade, so the safety
        # lock of PRD 3.5 permits it -- but PRD 3.5 also requires that "When
        # `approved_remedy` differs from the claim's `recommended_remedy`, an
        # `override_justification` must be present", whichever direction the departure
        # runs, so the justification travels with the decision.
        approved_pack = validate_success(
            api.adjudicate_claim(
                first["claim_id"],
                adjudicate_payload(
                    "PACK_REPLACEMENT",
                    override_justification="escalated to a whole-pack replacement",
                    decision_note="first pack approval",
                ),
                make_adjudicator_headers(ADJUDICATOR_1_ID),
            )
        )
        assert approved_pack["adjudication_status"] == "APPROVED_PACK"
        assert approved_pack["replacement_pack_id"] == reman["id"]
        assert approved_pack["remedy_cost_cents"] == 1040497
        assert approved_pack["admin_fee_cents"] == 15000
        assert approved_pack["oem_total_cents"] == 1055497
        assert_settlement_waterfall(approved_pack)
        assert read_pack(api, reman["id"])["status"] == "RESERVED"
        program = read_program(api, first["program_id"])
        assert_reman_stock(program, 0, "DEPLETED")
        assert program["accrued_liability_cents"] == 1055497

        # The pool is empty and the programme will not fall back on factory-new stock.
        retry_payload = adjudicate_payload(
            "PACK_REPLACEMENT",
            override_justification="escalated to a whole-pack replacement",
            decision_note="second pack approval",
        )
        validate_error(
            api.adjudicate_claim(
                second["claim_id"], retry_payload, make_adjudicator_headers(ADJUDICATOR_1_ID)
            ),
            ApiErrorId.ERR_NO_REMAN_PACK_AVAILABLE.value,
            expected_status=409,
        )
        assert read_claim(api, second["claim_id"])["adjudication_status"] == "SUBMITTED"
        assert_reman_stock(read_program(api, first["program_id"]), 0, "DEPLETED")

        file_dispute(
            api,
            first,
            lab_name="Cascade Cell Labs",
            owner_statement="a pack swap is not warranted",
        )
        bounced = record_lab_result(
            api, first, 58.400, lab_report_reference="CCL-2026-0802"
        )
        assert bounced["deviation_pct"] == 3.00
        assert bounced["retest_count"] == 1
        assert bounced["dispute_status"] == "LAB_ASSIGNED"
        confirmed = record_lab_result(
            api, first, 58.400, lab_report_reference="CCL-2026-0802-RETEST"
        )
        assert confirmed["dispute_status"] == "LAB_RESULT_RECEIVED"
        resolved = resolve_dispute(
            api,
            first,
            adjudicator_id=ADJUDICATOR_2_ID,
            resolution_note="downgrade the pack approval to a module remedy",
        )
        assert resolved["dispute_status"] == "RESOLVED_DOWNGRADED"

        collapsed = read_claim(api, first["claim_id"])
        assert collapsed["adjudication_status"] == "APPROVED_MODULE"
        assert collapsed["replacement_pack_id"] is None
        assert collapsed["remedy_cost_cents"] == 363092
        assert collapsed["admin_fee_cents"] == 7500
        assert collapsed["oem_total_cents"] == 370592
        assert_settlement_waterfall(collapsed)

        released = read_pack(api, reman["id"])
        assert released["status"] == "STOCK"
        assert released["installed_vehicle_id"] is None
        program = read_program(api, first["program_id"])
        assert_reman_stock(program, 1, "AVAILABLE")
        assert program["accrued_liability_cents"] == 370592

        # The byte-identical retry of the refused approval now lands.
        approved_again = validate_success(
            api.adjudicate_claim(
                second["claim_id"], retry_payload, make_adjudicator_headers(ADJUDICATOR_1_ID)
            )
        )
        assert approved_again["adjudication_status"] == "APPROVED_PACK"
        assert approved_again["replacement_pack_id"] == reman["id"]
        assert approved_again["oem_total_cents"] == 1055497
        program = read_program(api, first["program_id"])
        assert_reman_stock(program, 0, "DEPLETED")
        assert program["accrued_liability_cents"] == 1426089
