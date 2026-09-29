"""The weighted clause score of a processing contract.

The score's rounding order is normative: each clause product is rounded on its
own before the four figures are summed.
"""

from test_helpers import (
    VENDOR_MANAGER,
    assert_two_decimal_value,
    create_program,
    create_vendor,
    create_vendor_contract,
    read_contract,
    validate_success,
)


def test_clause_products_are_rounded_individually_then_summed_to_85_51(api):
    """A fully compliant contract at a requested attestation scores 85.51.

    PRD §3.2: "**Each of those four products is rounded half-up to two decimal
    places individually, and only then are the four rounded figures summed.**
    Summing the raw products and rounding once at the end produces a different
    cent figure and is not the specified behaviour."

    The four clause values 35, 25, 30 and 10 are multiplied by the `REQUESTED`
    attestation factor 0.855, giving 29.925, 21.375, 25.65 and 8.55; rounded
    individually they are 29.93, 21.38, 25.65 and 8.55, which sum to 85.51. The
    forbidden shortcut of summing the raw products would yield 85.50.

    Design: Difficulty/combinatorial_formula/contract_score_rounds_per_clause_then_sums_yielding_85_51
    """
    program = create_program(api)
    vendor = create_vendor(api, program["id"])
    contract = create_vendor_contract(api, vendor["id"])

    assert_two_decimal_value(contract["compliance_score"], 71.51, "compliance_score at NOT_REQUESTED")

    validate_success(
        api.record_attestation(vendor["id"], {"attestation_status": "REQUESTED"}, VENDOR_MANAGER)
    )

    repriced = read_contract(api, contract["id"])
    assert_two_decimal_value(repriced["compliance_score"], 85.51, "compliance_score at REQUESTED")
    assert repriced["compliance_score"] != 85.50, (
        "85.50 is the figure produced by rounding only the final sum"
    )
    assert repriced["status"] == "DRAFT", "recording an attestation does not move the contract"


def test_requesting_an_attestation_reprices_the_vendor_risk_score_to_30(api):
    """A clean processor awaiting its attestation scores 30 risk points.

    PRD §3.2: "The attestation itself contributes 20 points while
    `NOT_REQUESTED`, 10 points while `REQUESTED`, nothing once `RECEIVED`, and a
    punitive 35 points when `REJECTED`."

    ClockPoint Systems admits no sale, discloses no subprocessor, commits to a
    15-day deletion SLA and has completed its subprocessor disclosure, so its
    only points beyond the base of 20 are the 10 carried by a requested
    attestation.

    Design: Difficulty/combinatorial_formula/contract_score_rounds_per_clause_then_sums_yielding_85_51
    """
    program = create_program(api)
    vendor = create_vendor(api, program["id"])

    assert vendor["risk_score"] == 40, "20 base + 20 for an unrequested attestation"
    assert vendor["attestation_status"] == "NOT_REQUESTED"

    updated = validate_success(
        api.record_attestation(vendor["id"], {"attestation_status": "REQUESTED"}, VENDOR_MANAGER)
    )

    assert updated["attestation_status"] == "REQUESTED"
    assert updated["risk_score"] == 30, "20 base + 10 for a requested attestation"
    assert updated["version"] == vendor["version"] + 1, "recording an attestation mutates the vendor"
