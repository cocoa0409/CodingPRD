"""The normative rounding order of a contract score, and the floor it must clear.

A contract whose clause set is complete but whose deletion deadline is too long, so
the whole score hangs on the vendor's attestation factor.
"""

from test_helpers import (
    VENDOR_MANAGER,
    ApiErrorId,
    assert_two_decimal_value,
    attestation_payload,
    create_program,
    create_vendor,
    create_vendor_contract,
    read_contract,
    read_vendor,
    validate_error,
    validate_success,
)

LONG_DELETION_DEADLINE_DAYS = 45


def test_each_clause_is_rounded_before_the_sum_and_the_floor_blocks_execution(api):
    """Per-clause rounding gives 64.36, not the 64.35 a single final rounding gives.

    PRD §3.2: "Four clauses carry point values: thirty-five points for
    `prohibits_sale`, twenty-five points for `restricts_disclosure`, thirty points for
    `requires_deletion_on_termination`, and ten points for a deletion deadline that is
    at most thirty days."

    PRD §3.2: "Each clause's point value is then multiplied by the vendor's attestation
    factor, which is 0.715 while the attestation is `NOT_REQUESTED`, 0.855 while
    `REQUESTED`, 1.000 once `RECEIVED`, and 0.000 when `REJECTED`."

    PRD §3.2: "**Each of those four products is rounded half-up to two decimal places
    individually, and only then are the four rounded figures summed.**"

    PRD §3.2: "Execution is refused if any other contract for the same vendor is
    already `EXECUTED` (`ERR_DUPLICATE_EXECUTED_CONTRACT`) — a vendor may carry at most
    one executed contract at a time — and refused if `compliance_score` is below 82.50
    (`ERR_CONTRACT_SCORE_BELOW_FLOOR`)."

    The forty-five-day deletion deadline zeroes the fourth clause, so the three
    surviving products are 25.025, 17.875 and 21.45; rounding each first yields
    25.03 + 17.88 + 21.45 = 64.36, while summing first and rounding once would yield
    64.35. That score is far below the floor, so the refused execution leaves the
    contract sitting in `APPROVED`.

    Design: Corner/calculations/contract_score_rounds_each_clause_then_sums_gating_execution_at_the_floor
    """
    program = create_program(api)
    vendor = create_vendor(api, program["id"])
    assert vendor["attestation_status"] == "NOT_REQUESTED"

    contract = create_vendor_contract(
        api,
        vendor["id"],
        target_status="APPROVED",
        deletion_deadline_days=LONG_DELETION_DEADLINE_DAYS,
    )

    assert_two_decimal_value(contract["compliance_score"], 64.36, "compliance_score")
    assert contract["status"] == "APPROVED"

    refused = api.transition_vendor_contract(
        contract["id"], {"to_status": "EXECUTED"}, VENDOR_MANAGER
    )

    validate_error(refused, ApiErrorId.CONTRACT_SCORE_BELOW_FLOOR)

    unchanged = read_contract(api, contract["id"])
    assert unchanged["status"] == "APPROVED"
    assert_two_decimal_value(unchanged["compliance_score"], 64.36, "compliance_score")


def test_advancing_the_attestation_reprices_the_contract_up_to_the_floor(api):
    """The same clause set clears the floor once the attestation is in hand.

    PRD §3.2: "It increments the vendor's `version` by 1, recomputes the vendor's
    `risk_score`, and recomputes the compliance score of every one of that vendor's
    contracts whose status is not `VOID` and not `CLOSED_OUT`: a contract that has been
    voided or closed out is frozen, and later attestation movement never re-prices
    it."

    PRD §3.2: "The attestation itself contributes 20 points while `NOT_REQUESTED`, 10
    points while `REQUESTED`, nothing once `RECEIVED`, and a punitive 35 points when
    `REJECTED`."

    PRD §3.2: "Execution recomputes `compliance_score` once more."

    Requesting the attestation lifts the same three clauses to
    29.93 + 21.38 + 25.65 = 76.96, still short of 82.50; receiving it takes the factor
    to 1.000 and the score to the unweighted 90.00, which clears the floor and lets the
    contract execute. Each step also strips the attestation's own risk points, so the
    clean processor falls 40, 30, 20.

    Design: Corner/calculations/contract_score_rounds_each_clause_then_sums_gating_execution_at_the_floor
    """
    program = create_program(api)
    vendor = create_vendor(api, program["id"])
    contract = create_vendor_contract(
        api,
        vendor["id"],
        target_status="APPROVED",
        deletion_deadline_days=LONG_DELETION_DEADLINE_DAYS,
    )
    assert vendor["risk_score"] == 40

    requested = validate_success(
        api.record_attestation(vendor["id"], attestation_payload("REQUESTED"), VENDOR_MANAGER)
    )
    assert requested["attestation_status"] == "REQUESTED"
    assert requested["risk_score"] == 30
    assert_two_decimal_value(
        read_contract(api, contract["id"])["compliance_score"], 76.96, "compliance_score"
    )

    received = validate_success(
        api.record_attestation(vendor["id"], attestation_payload("RECEIVED"), VENDOR_MANAGER)
    )
    assert received["attestation_status"] == "RECEIVED"
    assert received["risk_score"] == 20
    assert_two_decimal_value(
        read_contract(api, contract["id"])["compliance_score"], 90.00, "compliance_score"
    )

    executed = validate_success(
        api.transition_vendor_contract(contract["id"], {"to_status": "EXECUTED"}, VENDOR_MANAGER)
    )
    assert executed["status"] == "EXECUTED"
    assert_two_decimal_value(executed["compliance_score"], 90.00, "compliance_score")
    assert read_vendor(api, vendor["id"])["risk_score"] == 20
