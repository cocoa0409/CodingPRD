"""Formulas whose evaluation order is the whole difficulty.

The good-faith estimate can read its surcharge tier from either of two figures and
the settlement can round coinsurance at either of two moments; both orders are
pinned, and both wrong orders produce a plausible but different cent total.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_line_total,
    assert_money_conservation,
    assert_settlement,
)
from test_helpers.factories import (
    make_adjudicate_payload,
    make_claim_payload,
    make_encounter_payload,
)
from test_helpers.fixtures import (
    CLERK,
    OFFICER,
    PAYER,
    acknowledge_disclosure,
    add_resulted_line,
    discharge,
    open_facility,
    protected_nsa_contract,
    register_encounter,
    screen_encounter,
)

ESTIMATE_FACILITY = {
    "name": "Pecan Grove Freestanding ED",
    "observation_bed_count": 4,
    "imaging_scope": ["XRAY", "CT"],
    "lab_scope": ["CBC", "TROPONIN"],
}
ESTIMATE_TEMPLATE = {
    "facility_fee_cents": 115000,
    "observation_hourly_cents": 38000,
    "network_status_statement": "NETWORK_VARIES_BY_PLAN",
}
SETTLEMENT_FACILITY = {
    "observation_bed_count": 4,
    "imaging_scope": ["XRAY", "CT", "ULTRASOUND"],
    "lab_scope": ["CBC", "CHEMISTRY", "TROPONIN"],
}


def _facility_disclosing_a_115000_cent_fee():
    return open_facility(
        facility_overrides=ESTIMATE_FACILITY, template_overrides=ESTIMATE_TEMPLATE
    )


def test_acuity_four_estimate_reads_its_surcharge_tier_from_the_base_subtotal():
    """115000 plus a 130000 allowance sits in the five-percent band, not the nine.

    PRD 3.6: "It is read from the **pre-surcharge subtotal only**." — the base
    subtotal is 245000, which falls in the band PRD 3.6 describes as "a base
    subtotal from 100000 cents up to but not including 250000 cents draws five
    percent", giving a 12250-cent surcharge and a 257250-cent estimate.  PRD 3.6
    spells out the wrong answer too: "reading the tier from the total would select
    nine percent and quote 267050 cents, which is wrong."

    Design: Difficulty/combinatorial_formula/disclosed_estimate_tier_read_from_base_subtotal_not_from_final_total
    """
    context = _facility_disclosing_a_115000_cent_fee()

    registered = validate_success(
        api_client.register_encounter(
            context["facility_id"],
            make_encounter_payload(
                patient_reference="PT-2001",
                acuity_level=4,
                presenting_service_line="CARDIAC",
            ),
            CLERK,
        ),
        expected_status=201,
    )

    assert registered["disclosed_estimate_cents"] == 257250
    assert registered["disclosed_estimate_cents"] != 267050


def test_low_acuity_estimate_uses_its_own_allowance_and_pins_the_same_template():
    """The allowance is keyed on acuity, and the pinned template is keyed on nothing.

    PRD 3.6 gives the table: "the allowance is 15000 cents at acuity 1, 35000 cents
    at acuity 2, 70000 cents at acuity 3, 130000 cents at acuity 4, and 220000
    cents at acuity 5".  An acuity-1 base subtotal is 115000 + 15000 = 130000, still
    in the five-percent band, so the estimate is 136500.  Both registrations pin the
    same document, because PRD 3.6 says "`pinned_disclosure_template_id` is set to
    the facility's `current_published_template_id` and never changes again for the
    life of the encounter".

    Design: Difficulty/combinatorial_formula/disclosed_estimate_tier_read_from_base_subtotal_not_from_final_total
    """
    context = _facility_disclosing_a_115000_cent_fee()

    high_acuity = register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-2001",
        acuity_level=4,
        presenting_service_line="CARDIAC",
    )
    low_acuity = register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-2002",
        acuity_level=1,
        presenting_service_line="GENERAL_MEDICAL",
    )

    assert low_acuity["disclosed_estimate_cents"] == 136500
    assert high_acuity["pinned_disclosure_template_id"] == context["template_id"]
    assert low_acuity["pinned_disclosure_template_id"] == context["template_id"]


def _draft_claim_on_the_canonical_bundle():
    """The ordered line set [145000, 98000, 31000, 8500] under a federal contract."""
    context = open_facility(facility_overrides=SETTLEMENT_FACILITY)
    facility_id = context["facility_id"]
    contract = protected_nsa_contract(facility_id, OFFICER, payer_name="Lone Star Health")
    encounter = register_encounter(
        facility_id,
        CLERK,
        patient_reference="PT-1001",
        acuity_level=3,
        presenting_service_line="CARDIAC",
    )
    acknowledge_disclosure(encounter["id"])
    screen_encounter(encounter["id"], "STABLE")
    lines = [
        add_resulted_line(encounter["id"], "IMAGING", "CT", 2),
        add_resulted_line(encounter["id"], "LABORATORY", "TROPONIN", 2),
        add_resulted_line(encounter["id"], "PHARMACY", "ANALGESIC", 1),
    ]
    discharge(encounter["id"])
    claim = validate_success(
        api_client.create_claim(
            encounter["id"], make_claim_payload(contract["id"]), OFFICER
        ),
        expected_status=201,
    )
    return claim, lines


def test_resulted_lines_freeze_the_billed_figures_the_settlement_allocates_over():
    """Each line is an exact product, and only resulted lines are summed into the claim.

    PRD 3.7: "`line_total_cents` is `unit_charge_cents` multiplied by `quantity` —
    an exact integer product with no rounding".  PRD 3.9: "`billed_ancillary_cents`
    is the sum of `line_total_cents` over the encounter's ancillary orders whose
    `status` is `RESULTED`".  CT x2, TROPONIN x2 and ANALGESIC x1 therefore give
    98000 + 31000 + 8500 = 137500, and the 145000 facility fee brings the billed
    total to 282500.

    Design: Difficulty/combinatorial_formula/claim_coinsurance_rounded_per_line_then_summed_not_summed_then_rounded
    """
    claim, lines = _draft_claim_on_the_canonical_bundle()

    for line in lines:
        assert_line_total(line)
    assert [line["line_total_cents"] for line in lines] == [98000, 31000, 8500]
    assert claim["billed_ancillary_cents"] == 137500
    assert claim["billed_total_cents"] == 282500


def test_coinsurance_rounds_per_line_so_the_cost_share_lands_one_cent_below():
    """Per-line rounding yields 27999 cents of coinsurance, never 28000.

    PRD 3.9 step five: "This order is pinned: summing the post-deductible allowed
    amounts across lines and rounding once at the end produces a different cent
    total and is wrong."  The four post-deductible bases round individually to
    9504 + 13182 + 4170 + 1143 = 27999, so with 50000 cents of deductible absorbed
    the patient owes 77999 rather than the 78000 an aggregate rounding would give.

    Design: Difficulty/combinatorial_formula/claim_coinsurance_rounded_per_line_then_summed_not_summed_then_rounded
    """
    claim, _lines = _draft_claim_on_the_canonical_bundle()

    adjudicated = validate_success(
        api_client.adjudicate_claim(claim["id"], make_adjudicate_payload(), PAYER)
    )

    assert_settlement(
        adjudicated,
        allowed=190000,
        plan_paid=112001,
        patient_responsibility=77999,
        written_off=92500,
    )
    assert adjudicated["patient_responsibility_cents"] != 78000
    assert_money_conservation(adjudicated)
    assert (
        adjudicated["plan_paid_cents"]
        + adjudicated["patient_responsibility_cents"]
        + adjudicated["written_off_cents"]
        == 282500
    )
