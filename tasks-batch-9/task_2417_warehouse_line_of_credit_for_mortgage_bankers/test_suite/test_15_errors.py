"""Error corners: which code wins, and which collection it names.

Each family here pins a code that a generic implementation collapses into a
neighbour — the two auth codes that outrank existence, the per-collection
not-found codes, the two "wrong lifecycle state" codes that share a shape, and
the three fiscal bucket codes that must each name their own bucket at exactly
zero headroom.
"""

import pytest

from test_helpers import (
    COLLATERAL_ANALYST,
    CREDIT_OFFICER,
    NON_EXISTENT_UUID,
    SECOND_CREDIT_OFFICER,
    WIRE_OPERATOR,
    ApiErrorId,
    api_client,
    make_borrower_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as asserts
from test_helpers import factories as make
from test_helpers import fixtures as fx

#: A dry-only product with no per-product cap, so priority 42 stays disabled.
DRY_SCRATCH_AND_DENT_ROW = {
    "product_code": "SCRATCH_AND_DENT",
    "advance_rate": 0.85,
    "wet_funding_allowed": False,
    "dwell_limit_days": 20,
    "product_sublimit_cents": None,
}

_HEADERS_WITHOUT_ROLE = {"Content-Type": "application/json", "X-User-ID": "co_1"}
_HEADERS_WITHOUT_ID = {"Content-Type": "application/json", "X-User-Role": "CreditOfficer"}
_HEADERS_WITH_EMPTY_ID = {
    "Content-Type": "application/json",
    "X-User-ID": "",
    "X-User-Role": "CreditOfficer",
}


# ─── The two rules that outrank existence ─────────────────────────────────────

class TestAuthenticationThenAuthorisationThenExistence:
    def test_a_missing_header_beats_a_bad_path_and_a_bad_role_beats_both(self):
        """403 never leaks whether the addressed identifier exists.

        PRD 2.1: "If either header is absent or empty, the request fails with
        `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."

        PRD 2.1: "This check runs before the path is resolved, so a request that
        both omits a header and addresses a non-existent identifier returns 401,
        never 404."

        PRD 2.1: "If the supplied role is not among the roles authorised for the
        addressed endpoint in §4, the request fails with `ERR_UNAUTHORIZED` (HTTP
        403) — and role authorisation likewise precedes existence, so a
        `CollateralAnalyst` attempting a facility approval receives 403 even when
        the facility identifier does not exist."

        PRD 2.1: "For all three, a supplied `X-User-ID` that does not resolve to
        a row of the backing entity at all is itself an authorisation failure and
        yields `ERR_UNAUTHORIZED`; an identity that resolves but addresses a row
        belonging to a different aggregate yields `ERR_RESOURCE_MISMATCH` with
        HTTP 404, deliberately reported as a not-found so that the existence of
        another counterparty's data is never disclosed."

        Design: Corner/errors/corner_err_auth_headers_then_role_then_existence
        """
        facility = fx.create_active_facility()
        facility_id = facility["id"]
        version_before = facility["version"]

        for headers in (
            _HEADERS_WITHOUT_ROLE,
            _HEADERS_WITHOUT_ID,
            _HEADERS_WITH_EMPTY_ID,
        ):
            validate_error(
                api_client.get_facility(facility_id, headers),
                ApiErrorId.ERR_MISSING_AUTH_HEADERS,
            )

        # Authentication is resolved before the path is, so this is 401 not 404.
        validate_error(
            api_client.get_facility(NON_EXISTENT_UUID, _HEADERS_WITHOUT_ROLE),
            ApiErrorId.ERR_MISSING_AUTH_HEADERS,
        )

        # The baseline that the two 403 arms below must override.
        validate_error(
            api_client.approve_facility(NON_EXISTENT_UUID, SECOND_CREDIT_OFFICER),
            ApiErrorId.ERR_FACILITY_NOT_FOUND,
        )
        # The identical request under an unauthorised role hides the 404.
        validate_error(
            api_client.approve_facility(NON_EXISTENT_UUID, COLLATERAL_ANALYST),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        # And it hides the 409 the already-approved facility would otherwise give.
        validate_error(
            api_client.approve_facility(facility_id, COLLATERAL_ANALYST),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

        # Booking is exclusive to the analyst and the borrower.
        custodian = fx.register_custodian(facility_id)
        validate_error(
            api_client.create_advance(
                make.advance_payload(
                    facility_id, custodian["id"], fx.facility_version(facility_id)
                ),
                WIRE_OPERATOR,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

        # An entity-backed identity that resolves to no facility row at all.
        validate_error(
            api_client.get_facility(facility_id, make_borrower_headers("ca_1")),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        # The same role and endpoint succeed once the identity is the caller's own row.
        own_read = validate_success(
            api_client.get_facility(facility_id, make_borrower_headers(facility_id))
        )
        asserts.assert_facility(own_read)
        assert own_read["id"] == facility_id

        # No rejected request mutated anything.
        assert own_read["status"] == "ACTIVE"
        assert own_read["version"] == version_before


# ─── One unresolvable identifier, seven collections ───────────────────────────

class TestNotFoundCodeFollowsTheAddressedCollection:
    def test_each_collection_answers_with_its_own_code(self):
        """The code comes from the URL segment, never from the body.

        PRD 2.8: "Every path-parameter identifier resolves to an existing row of
        the addressed collection, failing with 404 and the code that matches the
        addressed collection segment: a facility segment yields
        `ERR_FACILITY_NOT_FOUND`, an advance segment `ERR_ADVANCE_NOT_FOUND`, an
        investor segment `ERR_INVESTOR_NOT_FOUND`, a custodian segment
        `ERR_CUSTODIAN_NOT_FOUND`, a commitment segment
        `ERR_COMMITMENT_NOT_FOUND`, a margin-call segment
        `ERR_MARGIN_CALL_NOT_FOUND`, a wire-instruction segment
        `ERR_WIRE_INSTRUCTION_NOT_FOUND`, a receipt segment
        `ERR_RECEIPT_NOT_FOUND`, a covenant-test segment
        `ERR_COVENANT_TEST_NOT_FOUND`, and a repurchase-demand segment
        `ERR_REPURCHASE_DEMAND_NOT_FOUND`."

        Design: Corner/errors/corner_err_not_found_code_follows_the_addressed_collection
        """
        # A non-empty database, so every arm below is a genuine lookup.
        facility = fx.create_active_facility()

        validate_error(
            api_client.withdraw_commitment(
                NON_EXISTENT_UUID,
                {"reason": "Probe for the commitment collection's not-found code"},
                CREDIT_OFFICER,
            ),
            ApiErrorId.ERR_COMMITMENT_NOT_FOUND,
        )
        validate_error(
            api_client.waive_covenant_test(
                NON_EXISTENT_UUID,
                {"reason": "Probe for the covenant-test collection's not-found code"},
                CREDIT_OFFICER,
            ),
            ApiErrorId.ERR_COVENANT_TEST_NOT_FOUND,
        )
        # A perfectly valid cure body: the answer still names the receipt segment.
        validate_error(
            api_client.cure_receipt(
                NON_EXISTENT_UUID,
                make.receipt_cure_payload(["UNSIGNED_ASSIGNMENT"]),
                COLLATERAL_ANALYST,
            ),
            ApiErrorId.ERR_RECEIPT_NOT_FOUND,
        )
        validate_error(
            api_client.escalate_repurchase_demand(NON_EXISTENT_UUID, CREDIT_OFFICER),
            ApiErrorId.ERR_REPURCHASE_DEMAND_NOT_FOUND,
        )
        validate_error(
            api_client.decide_wire_instruction(
                NON_EXISTENT_UUID,
                make.wire_decision_payload("VERIFY", callback_reference="CB-404"),
                WIRE_OPERATOR,
            ),
            ApiErrorId.ERR_WIRE_INSTRUCTION_NOT_FOUND,
        )
        validate_error(
            api_client.get_advance(NON_EXISTENT_UUID, COLLATERAL_ANALYST),
            ApiErrorId.ERR_ADVANCE_NOT_FOUND,
        )
        validate_error(
            api_client.get_margin_call(NON_EXISTENT_UUID, CREDIT_OFFICER),
            ApiErrorId.ERR_MARGIN_CALL_NOT_FOUND,
        )

        untouched = fx.read_facility(facility["id"])
        assert untouched["status"] == "ACTIVE"
        assert untouched["version"] == facility["version"]
        assert untouched["outstanding_principal_cents"] == 0


# ─── A wire is decided exactly once ───────────────────────────────────────────

class TestWireDecisionIsSingleShot:
    def test_all_four_re_decision_combinations_are_refused(self):
        """Neither a verification nor a block can be revisited or reversed.

        PRD 2.8: "The addressed wire instruction is `PENDING_VERIFICATION`,
        failing with `ERR_WIRE_INSTRUCTION_NOT_PENDING` (409). A wire is decided
        exactly once; `VERIFIED` and `BLOCKED` accept no further decision."

        PRD 3.3: "The wire moves `PENDING_VERIFICATION → BLOCKED` with
        `block_reason` stored and `decided_by_user_id` stamped, and the paired
        advance moves `REQUESTED → REJECTED` with `rejected_reason` set to
        `WIRE_BLOCKED`."

        PRD 2.8: "`funding_status` permits the trigger: `REQUESTED` for funding;
        `FUNDED` or `SHIPPED` for shipment, valuation, repurchase and raising a
        repurchase demand; `SHIPPED` for purchase; and `REQUESTED`, `FUNDED` or
        `SHIPPED` for filing a receipt."

        Design: Corner/errors/corner_err_wire_decision_is_single_shot_in_both_directions
        """
        scenario = fx.setup_requested_advance()
        verified = fx.verify_wire(scenario.wire["id"], "CB-301")
        assert verified["status"] == "VERIFIED"

        blocked_advance = fx.book_advance(
            scenario.facility["id"],
            scenario.custodian["id"],
            investor_commitment_id=scenario.commitment["id"],
            loan_amount_cents=300_000_000,
            note_rate=0.0700,
        )
        blocked_wire = fx.wire_for_advance(blocked_advance["id"])
        blocked = fx.block_wire(blocked_wire["id"], "OPERATOR_BLOCK")
        assert blocked["status"] == "BLOCKED"

        for wire_id, payload in (
            (verified["id"], make.wire_decision_payload("VERIFY", callback_reference="CB-830")),
            (verified["id"], {"decision": "BLOCK", "block_reason": "OPERATOR_BLOCK"}),
            (blocked["id"], {"decision": "BLOCK", "block_reason": "OPERATOR_BLOCK"}),
            (blocked["id"], make.wire_decision_payload("VERIFY", callback_reference="CB-831")),
        ):
            validate_error(
                api_client.decide_wire_instruction(wire_id, payload, WIRE_OPERATOR),
                ApiErrorId.ERR_WIRE_INSTRUCTION_NOT_PENDING,
            )

        still_verified = fx.wire_for_advance(scenario.advance["id"])
        assert still_verified["status"] == "VERIFIED"
        assert still_verified["decided_by_user_id"] == "wo_1"
        # The original decision's reference stands.
        assert still_verified["callback_reference"] == "CB-301"
        assert still_verified["version"] == verified["version"]

        still_blocked = fx.wire_for_advance(blocked_advance["id"])
        assert still_blocked["status"] == "BLOCKED"
        assert still_blocked["block_reason"] == "OPERATOR_BLOCK"
        assert still_blocked["version"] == blocked["version"]

        # The block already terminated the advance, and priority 11 outranks the
        # wire-verified rule at priority 19, so this is the funding-axis code.
        validate_error(
            api_client.fund_advance(blocked_advance["id"], COLLATERAL_ANALYST),
            ApiErrorId.ERR_ADVANCE_INVALID_STATE,
        )
        rejected = fx.read_advance(blocked_advance["id"])
        assert rejected["funding_status"] == "REJECTED"
        assert rejected["rejected_reason"] == "WIRE_BLOCKED"
        assert fx.read_facility(scenario.facility["id"])[
            "outstanding_principal_cents"
        ] == 0


# ─── Two closed-lifecycle gates that must not be collapsed ────────────────────

class TestClosedCallAndPassingTestRefuseDifferently:
    def test_a_cured_call_and_a_passing_test_name_their_own_codes(self):
        """Both mean there is nothing left to do, and the codes still differ.

        PRD 2.8: "The addressed call is `ISSUED` or `PARTIALLY_CURED`, failing
        both cure payments and waiver with `ERR_MARGIN_CALL_NOT_OPEN` (409).
        `CURED`, `WAIVED` and `DEFAULTED` calls accept no payment and cannot be
        waived."

        PRD 2.8: "The addressed test is in `BREACH`, failing waiver with
        `ERR_COVENANT_TEST_NOT_BREACHED` (409). A `PASS` test has nothing to
        waive and a `WAIVED` test cannot be waived twice."

        Design: Corner/errors/corner_err_closed_margin_call_and_passing_covenant_test_gates
        """
        scenario = fx.setup_funded_dry_advance()
        facility_id = scenario.facility["id"]

        call = fx.raise_manual_margin_call(facility_id)
        assert call["call_amount_cents"] == 196_000_000
        fx.post_cure_payment(call["id"], facility_id, 196_000_000)

        cured = fx.read_margin_call(call["id"])
        assert cured["status"] == "CURED"
        assert cured["cured_amount_cents"] == 196_000_000
        assert cured["version"] > call["version"]
        assert fx.read_facility(facility_id)["status"] == "ACTIVE"

        covenant_test = fx.certify_covenants(facility_id, "2026-06-30")
        assert covenant_test["status"] == "PASS"

        # The current version is supplied, so priority 8 cannot be the failure.
        validate_error(
            api_client.create_cure_payment(
                call["id"],
                make.cure_payment_payload(1_000_000, cured["version"]),
                make_borrower_headers(facility_id),
            ),
            ApiErrorId.ERR_MARGIN_CALL_NOT_OPEN,
        )
        # Waiver shares the same open-state gate as the cure payment.
        validate_error(
            api_client.waive_margin_call(
                call["id"],
                {"reason": "Attempt to waive an already-cured call"},
                SECOND_CREDIT_OFFICER,
            ),
            ApiErrorId.ERR_MARGIN_CALL_NOT_OPEN,
        )
        # A different code for the covenant gate: there is nothing to forgive.
        validate_error(
            api_client.waive_covenant_test(
                covenant_test["id"],
                {"reason": "Attempt to waive a passing test"},
                CREDIT_OFFICER,
            ),
            ApiErrorId.ERR_COVENANT_TEST_NOT_BREACHED,
        )

        tests, test_meta = validate_paginated(
            api_client.list_covenant_tests(facility_id, CREDIT_OFFICER)
        )
        assert test_meta["total_count"] == 1
        assert tests[0]["status"] == "PASS"
        assert tests[0]["waived_by_user_id"] is None

        payments, payment_meta = validate_paginated(
            api_client.list_cure_payments(call["id"], CREDIT_OFFICER)
        )
        # The rejected payment created no row.
        assert payment_meta["total_count"] == 1
        assert payments[0]["applied_to_principal_cents"] == 196_000_000

        assert fx.read_advance(scenario.advance["id"])[
            "outstanding_balance_cents"
        ] == 1_764_000_000
        assert fx.read_facility(facility_id)["accrued_fee_balance_cents"] == 0


# ─── Custodian suspension is forward-looking only ─────────────────────────────

class TestSuspendedCustodianBlocksAssignmentAndReceipts:
    def test_the_same_code_covers_both_and_the_own_state_code_is_different(self):
        """New collateral and new receipts stop; settled work is untouched.

        PRD 2.8: "The document custodian's `status` is `APPROVED`, failing advance
        creation and receipt filing with `ERR_CUSTODIAN_NOT_ACTIVE` (422). A
        suspended custodian can neither be assigned new collateral nor file new
        receipts."

        PRD 2.8: "`DocumentCustodian.status` is `APPROVED`, failing suspension
        with `ERR_CUSTODIAN_INVALID_STATE` (409). `SUSPENDED` is terminal for a
        custodian, so a second suspension is rejected rather than re-stamping the
        row."

        Design: Corner/errors/corner_err_suspended_custodian_blocks_assignment_and_receipts
        """
        scenario = fx.setup_funded_dry_advance()
        facility_id = scenario.facility["id"]
        custodian_id = scenario.custodian["id"]

        unreceipted = fx.book_advance(
            facility_id,
            custodian_id,
            investor_commitment_id=scenario.commitment["id"],
            loan_amount_cents=300_000_000,
            note_rate=0.0700,
        )
        version_after_booking = fx.facility_version(facility_id)

        suspended = fx.suspend_custodian(
            custodian_id, "Custodian failed its annual document-control audit"
        )
        assert suspended["status"] == "SUSPENDED"

        validate_error(
            api_client.create_receipt(
                unreceipted["id"],
                make.receipt_payload(custodian_id, document_types=["NOTE", "MORTGAGE"]),
                COLLATERAL_ANALYST,
            ),
            ApiErrorId.ERR_CUSTODIAN_NOT_ACTIVE,
        )
        # Assignment is blocked by the same rule and reports the same code.
        validate_error(
            api_client.create_advance(
                make.advance_payload(
                    facility_id,
                    custodian_id,
                    version_after_booking,
                    investor_commitment_id=scenario.commitment["id"],
                    loan_amount_cents=200_000_000,
                    note_rate=0.0700,
                ),
                COLLATERAL_ANALYST,
            ),
            ApiErrorId.ERR_CUSTODIAN_NOT_ACTIVE,
        )
        # The own-entity state code, distinct from the 422 above.
        validate_error(
            api_client.suspend_custodian(
                custodian_id,
                {"reason": "Second suspension attempt on the same custodian"},
                CREDIT_OFFICER,
            ),
            ApiErrorId.ERR_CUSTODIAN_INVALID_STATE,
        )

        # Suspension is not retroactive.
        receipts, receipt_meta = validate_paginated(
            api_client.list_advance_receipts(scenario.advance["id"], CREDIT_OFFICER)
        )
        assert receipt_meta["total_count"] == 1
        assert receipts[0]["status"] == "CLEAR"
        settled = fx.read_advance(scenario.advance["id"])
        assert settled["custody_status"] == "RECEIVED_CLEAR"
        assert settled["funding_status"] == "FUNDED"
        assert settled["outstanding_balance_cents"] == 1_960_000_000

        still_waiting = fx.read_advance(unreceipted["id"])
        assert still_waiting["custody_status"] == "PENDING_RECEIPT"
        assert still_waiting["funding_status"] == "REQUESTED"

        facility = fx.read_facility(facility_id)
        # The rejected booking did not advance the facility any further.
        assert facility["version"] == version_after_booking
        # Custodian suspension raises no call and no restriction of its own.
        assert facility["status"] == "ACTIVE"
        assert facility["open_margin_call_count"] == 0


# ─── Each fiscal bucket names itself at exactly zero headroom ─────────────────

def _facility_with_both_buckets_exactly_exhausted():
    """AW1 fills the 960,000,000 wet bucket; AS1 fills the 425,000,000 S&D bucket.

    AW2 and AS2 are left booked and wire-verified so that each can be funded
    against a bucket whose headroom is exactly zero.
    """
    scenario = fx.setup_facility_panel(
        facility_overrides={
            "borrower_legal_name": "Meridian Residential Funding LLC",
            "wet_sublimit_cents": 960_000_000,
            "scratch_and_dent_sublimit_cents": 425_000_000,
        },
        extra_rate_rows=[DRY_SCRATCH_AND_DENT_ROW],
        custodian_overrides={"custodian_name": "Cornerstone Document Custody NA"},
        investor_overrides={"investor_name": "Atlas Whole Loan Trust"},
    )
    scenario.wet_advance = fx.book_and_fund_additional_advance(
        scenario,
        investor_commitment_id=scenario.commitment["id"],
        callback_reference="CB-840",
        product_code="CONFORMING",
        loan_amount_cents=1_000_000_000,
        note_rate=0.0625,
        funding_type="WET",
    )
    scenario.second_wet_advance = fx.book_advance_ready_to_fund(
        scenario,
        investor_commitment_id=scenario.commitment["id"],
        callback_reference="CB-841",
        product_code="CONFORMING",
        loan_amount_cents=500_000_000,
        note_rate=0.0625,
        funding_type="WET",
    )
    scenario.scratch_advance = fx.book_and_fund_additional_advance(
        scenario,
        callback_reference="CB-842",
        product_code="SCRATCH_AND_DENT",
        loan_amount_cents=500_000_000,
        note_rate=0.0950,
    )
    scenario.second_scratch_advance = fx.book_advance_ready_to_fund(
        scenario,
        callback_reference="CB-843",
        product_code="SCRATCH_AND_DENT",
        loan_amount_cents=100_000_000,
        note_rate=0.0950,
    )
    return scenario


class TestWetAndScratchAndDentBucketCodes:
    def test_each_bucket_reports_itself_rather_than_the_minimum_advance_rule(self):
        """Zero headroom in a bucket is that bucket's error, not a sizing error.

        PRD 2.8: "When `funding_type` is `WET`, `wet_sublimit_cents` less
        `wet_outstanding_cents` is strictly greater than zero, failing with
        `ERR_WET_SUBLIMIT_EXCEEDED` (422). Same semantics as priority 38,
        restricted to the wet bucket."

        PRD 2.8: "When `product_code` is `SCRATCH_AND_DENT`,
        `scratch_and_dent_outstanding_cents` is strictly less than
        `scratch_and_dent_sublimit_cents`, failing with
        `ERR_SCRATCH_AND_DENT_SUBLIMIT_EXCEEDED` (422)."

        PRD 2.8: "When the rate row declares a `product_sublimit_cents`, that
        sublimit less the product's current outstanding is strictly greater than
        zero, failing with `ERR_PRODUCT_SUBLIMIT_EXCEEDED` (422). A null
        `product_sublimit_cents` disables the rule entirely."

        Design: Corner/errors/corner_err_wet_and_scratch_and_dent_sublimit_codes
        """
        scenario = _facility_with_both_buckets_exactly_exhausted()
        facility_id = scenario.facility["id"]

        # floor(1,000,000,000 * (0.98 - 0.02)) is the whole wet sublimit.
        assert scenario.wet_advance["advance_amount_cents"] == 960_000_000
        # floor(500,000,000 * 0.85): the orphan cap of 0.85 leaves the rate alone.
        assert scenario.scratch_advance["advance_amount_cents"] == 425_000_000
        assert scenario.scratch_advance["effective_advance_rate"] == pytest.approx(
            0.85, abs=1e-6
        )
        assert scenario.scratch_advance["investor_commitment_id"] is None

        before = fx.read_facility(facility_id)
        assert before["wet_outstanding_cents"] == 960_000_000
        assert before["scratch_and_dent_outstanding_cents"] == 425_000_000
        assert before["availability_cents"] == 18_615_000_000

        # 960,000,000 less 960,000,000 is not strictly greater than zero, so the
        # wet bucket refuses even though the whole line still has headroom.
        validate_error(
            api_client.fund_advance(
                scenario.second_wet_advance["id"], COLLATERAL_ANALYST
            ),
            ApiErrorId.ERR_WET_SUBLIMIT_EXCEEDED,
        )
        # 425,000,000 < 425,000,000 is false, and the dry-only product declares
        # no per-product cap, so the scratch-and-dent bucket names itself.
        validate_error(
            api_client.fund_advance(
                scenario.second_scratch_advance["id"], COLLATERAL_ANALYST
            ),
            ApiErrorId.ERR_SCRATCH_AND_DENT_SUBLIMIT_EXCEEDED,
        )

        for advance_id in (
            scenario.second_wet_advance["id"],
            scenario.second_scratch_advance["id"],
        ):
            refused = fx.read_advance(advance_id)
            assert refused["funding_status"] == "REQUESTED"
            assert refused["advance_amount_cents"] == 0
            assert fx.wire_for_advance(advance_id)["status"] == "VERIFIED"

        after = fx.read_facility(facility_id)
        assert after["outstanding_principal_cents"] == 1_385_000_000
        # A fiscal rejection raises no restriction.
        assert after["status"] == "ACTIVE"


# ─── The aged bucket blocks the whole facility ─────────────────────────────────

def _facility_whose_aged_bucket_is_over_its_sublimit():
    """One aged advance of 1,950,000,000 against a 1,000,000,000 aged sublimit.

    Curing the aging run's own margin call is what returns the facility to
    `ACTIVE` while leaving the advance aged.
    """
    scenario = fx.setup_funded_dry_advance(
        facility_overrides={
            "borrower_legal_name": "Northgate Mortgage Bankers Inc",
            "aged_sublimit_cents": 1_000_000_000,
            "scratch_and_dent_sublimit_cents": 1_000_000_000,
        }
    )
    fx.set_clock("2026-09-05T00:00:00Z")
    scenario.aging_run = fx.run_aging(scenario.facility["id"])
    call = fx.first_open_margin_call(scenario.facility["id"])
    scenario.cure_payment = fx.post_cure_payment(
        call["id"], scenario.facility["id"], 31_058_333
    )
    scenario.margin_call = fx.read_margin_call(call["id"])
    scenario.second_advance = fx.book_advance_ready_to_fund(
        scenario,
        investor_commitment_id=scenario.commitment["id"],
        callback_reference="CB-851",
        loan_amount_cents=100_000_000,
        note_rate=0.0700,
    )
    return scenario


class TestAgedBucketOverSublimitBlocksNewFunding:
    def test_an_active_facility_still_refuses_while_the_aged_bucket_is_over(self):
        """Aged is not default: the cure lifts the restriction and the block remains.

        PRD 2.8: "`aged_outstanding_cents` is at most `aged_sublimit_cents`,
        failing with `ERR_AGED_SUBLIMIT_EXCEEDED` (422). This is an aggregate rule
        measured on *other* advances: no single advance is individually at fault,
        but once the facility's aged bucket has passed its sublimit no new advance
        funds until the aged collateral is curtailed or repurchased."

        PRD 3.6: "When that bucket passes `aged_sublimit_cents` the aging run
        itself raises no error, because it is a system job, but every subsequent
        funding attempt on the facility fails with `ERR_AGED_SUBLIMIT_EXCEEDED`
        until the excess is cured or the aged collateral is repurchased."

        Design: Corner/errors/corner_err_aged_bucket_over_sublimit_blocks_new_funding
        """
        scenario = _facility_whose_aged_bucket_is_over_its_sublimit()
        facility_id = scenario.facility["id"]
        aged_advance_id = scenario.advance["id"]

        assert scenario.aging_run["fee_accrual_cents"] == 21_058_333
        assert scenario.aging_run["margin_calls_issued"] == 1
        # The advance was never shipped, so no letter existed to expire.
        assert scenario.aging_run["bailee_letters_expired"] == 0
        assert scenario.aging_run["repurchase_demands_raised"] == 0

        # 21,058,333 of fees first, then the whole 10,000,000 call.
        assert scenario.cure_payment["applied_to_fees_cents"] == 21_058_333
        assert scenario.cure_payment["applied_to_principal_cents"] == 10_000_000
        assert scenario.margin_call["status"] == "CURED"

        aged_advance = fx.read_advance(aged_advance_id)
        assert aged_advance["dwell_days"] == 35
        assert aged_advance["is_aged"] is True
        assert aged_advance["effective_advance_rate"] == pytest.approx(0.975, abs=1e-6)
        assert aged_advance["eligible_collateral_value_cents"] == 1_950_000_000
        assert aged_advance["outstanding_balance_cents"] == 1_950_000_000

        before = fx.read_facility(facility_id)
        assert before["aged_outstanding_cents"] == 1_950_000_000
        assert before["aged_sublimit_cents"] == 1_000_000_000
        assert before["accrued_fee_balance_cents"] == 0
        assert before["open_margin_call_count"] == 0
        # The cure lifted the restriction, which is what makes the rule reachable.
        assert before["status"] == "ACTIVE"

        validate_error(
            api_client.fund_advance(scenario.second_advance["id"], COLLATERAL_ANALYST),
            ApiErrorId.ERR_AGED_SUBLIMIT_EXCEEDED,
        )
        assert fx.read_advance(scenario.second_advance["id"])[
            "funding_status"
        ] == "REQUESTED"
        assert fx.read_facility(facility_id)[
            "outstanding_principal_cents"
        ] == 1_950_000_000

        # Repurchasing the aged collateral empties the bucket, and the block goes.
        fx.repurchase_advance(aged_advance_id, 1_950_000_000)
        cleared = fx.read_facility(facility_id)
        assert cleared["aged_outstanding_cents"] == 0
        assert cleared["outstanding_principal_cents"] == 0

        funded = fx.fund_advance(scenario.second_advance["id"])
        assert funded["advance_amount_cents"] == 98_000_000
        assert funded["funding_status"] == "FUNDED"
        after = fx.read_facility(facility_id)
        assert after["outstanding_principal_cents"] == 98_000_000
        assert after["availability_cents"] == 19_902_000_000
        assert after["aged_outstanding_cents"] == 0
        assert after["status"] == "ACTIVE"
