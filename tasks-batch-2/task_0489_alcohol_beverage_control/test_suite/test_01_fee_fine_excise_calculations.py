"""Monetary calculations: fee assessment (initial vs renewal), the three-input
non-linear fine assessment, and the tiered excise with its excise-keyed rebate.

All amounts are whole cents (PRD section 2.6). Expected literals are copied from
the design index, which pre-computed them against the pinned formulas.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    make_applicant_headers,
    setup_reference_data,
    create_submitted_application,
    setup_issued_license,
    advance_to_protest_period,
    approve_and_issue,
    file_violation,
    sustain_violation,
)

DIRECTOR = TEST_USERS["director_headers"]


# ─── Queue A: combinatorial_formula ───────────────────────────────────────
def test_fee_rounding_order_per_component_then_sum(api):
    """PRD §3.2: "each surcharge is computed as its percentage of the base and
    rounded to whole cents independently first, and only then are the base and
    the two rounded surcharges summed to give `fee_quoted_cents`."

    MFR_99 base 50006 with requires_zoning=true: zoning surcharge round(5000.6)=5001,
    manufacturer surcharge round(12501.5)=12502, sum = 50006+5001+12502 = 67509
    (the forbidden sum-then-round path would give 67508).

    Design: Difficulty/combinatorial_formula/fee_rounding_order_per_component_vs_sum_then_round
    """
    ref = setup_reference_data(
        class_overrides={
            "code": "MFR_99", "premise_type": "MANUFACTURER", "quota_managed": False,
            "base_fee_cents": 50006, "renewal_cycle_months": 12,
            "requires_zoning": True, "max_servers_per_license": 0,
        },
        applicant_overrides={"legal_name": "Brewery Co"},
    )
    owner = make_applicant_headers(ref["owner_id"])
    app = get_success_data(api.create_application(
        {"applicant_id": ref["owner_id"], "premise_id": ref["premise"]["id"],
         "license_class_code": "MFR_99"}, owner))
    # quota_managed=false -> no expected_region_version required.
    submitted = validate_success(api.submit_application(app["id"], {}, owner))
    assert submitted["fee_quoted_cents"] == 67509, (
        f"expected 67509 under per-component rounding, got {submitted['fee_quoted_cents']}"
    )
    assert submitted["status"] == "SUBMITTED"


def test_fine_assessment_three_input_nonlinear_recidivism(api):
    """PRD §3.9: "A recidivism multiplier is then chosen from the prior
    `demerit_points` snapshot: a multiplier of one when the prior points are
    below four, one-and-one-half when the prior points are at least four and at
    most eight, and two when the prior points exceed eight."
    PRD §3.9: "a `SUSPENSION` halves the raw amount, rounded half up to whole
    cents, because the suspension itself is the primary penalty"

    A second EGREGIOUS violation sustained as SUSPENSION while prior
    demerit_points=4 (mid recidivism 1.5): round(200000*1.5*0.5) = 150000.

    Design: Difficulty/combinatorial_formula/fine_assessment_three_input_nonlinear_recidivism
    """
    bundle = setup_issued_license()
    lic_id = bundle["license"]["id"]
    # First SERIOUS sustained as FINE -> demerit_points 4, outstanding 75000.
    v1 = file_violation(lic_id, severity="SERIOUS")
    sustain_violation(v1["id"], action_type="FINE")
    # Second EGREGIOUS sustained as SUSPENSION at prior demerit_points=4.
    v2 = file_violation(lic_id, severity="EGREGIOUS")
    sustained = validate_success(
        api.sustain_violation(
            v2["id"], {"action_type": "SUSPENSION", "suspension_days": 10},
            TEST_USERS["adjudication_officer_headers"]))
    action = get_success_data(api.get_administrative_action(sustained["action_id"], DIRECTOR))
    assert action["fine_cents"] == 150000, f"expected 150000, got {action['fine_cents']}"
    lic = get_success_data(api.get_license(lic_id, DIRECTOR))
    assert lic["demerit_points"] == 10, f"expected demerit_points 10, got {lic['demerit_points']}"
    assert lic["outstanding_fine_cents"] == 225000, (
        f"expected outstanding 225000 (75000+150000), got {lic['outstanding_fine_cents']}"
    )


def test_excise_circular_rebate_keyed_on_excise_tier_supplier_double(api):
    """PRD §3.11: "a rebate tier is determined from that **excise** total (not from
    sales): an excise of fifty thousand cents or less earns no rebate; an excise
    from fifty thousand and one through two hundred thousand earns a rebate base
    of five percent of the excise, rounded half up; and an excise above two
    hundred thousand earns a rebate base of ten percent of the excise, rounded
    half up."
    PRD §3.11: "`SUPPLIER` doubles the rebate base, `WHOLESALER` takes it at face
    value, and `RETAILER` earns no rebate at all"

    gross_sales 6000000, SUPPLIER: excise = round(1M*.02)+round(4M*.04)+round(1M*.06)
    = 20000+160000+60000 = 240000; rebate_base = round(240000*.10)=24000, doubled
    to 48000; excise_due = 240000-48000 = 192000.

    Design: Difficulty/combinatorial_formula/excise_circular_rebate_keyed_on_excise_tier_evaluation_order
    """
    bundle = setup_issued_license()
    owner = make_applicant_headers(bundle["ref"]["owner_id"])
    report = validate_success(api.create_compliance_report(
        {"license_id": bundle["license"]["id"], "tier": "SUPPLIER",
         "period_code": "2026-Q1", "gross_sales_cents": 6000000}, owner), expected_status=201)
    assert report["excise_due_cents"] == 192000, (
        f"expected 192000 for SUPPLIER, got {report['excise_due_cents']}"
    )


# ─── Queue A: dual_variant_calc ───────────────────────────────────────────
def test_initial_fee_quoted_with_surcharges_frozen_on_submit(api):
    """PRD §3.2: "A zoning surcharge of ten percent of the base applies when the
    class requires zoning, and zero otherwise."
    PRD §3.2: "It runs the fee assessment and freezes the result into
    `fee_quoted_cents`."

    ON_47 base 100000, requires_zoning -> zoning surcharge 10000, no manufacturer
    surcharge: fee_quoted_cents == 110000 frozen at SUBMITTED.

    Design: Difficulty/dual_variant_calc/fee_initial_vs_renewal_variant_on_application_and_license
    """
    ref, app = create_submitted_application()
    fetched = get_success_data(api.get_application(app["id"], DIRECTOR))
    assert fetched["fee_quoted_cents"] == 110000, (
        f"expected initial fee_quoted_cents 110000, got {fetched['fee_quoted_cents']}"
    )
    assert fetched["status"] == "SUBMITTED"


def test_renewal_fee_charges_base_only_no_surcharges_reapplied(api):
    """PRD §3.8: "Unlike the initial quote, renewal charges the class's
    `base_fee_cents` only — the zoning and manufacturer surcharges are one-time
    charges levied at first issuance and are never re-charged on renewal."
    PRD §3.8: "and `renewal_count` increments by one."

    The initial fee was 110000 (base 100000 + 10000 zoning surcharge), but renewal
    is accepted paying base-only 100000 and rolls the term, renewal_count -> 1.

    Design: Difficulty/dual_variant_calc/fee_initial_vs_renewal_variant_on_application_and_license
    """
    bundle = setup_issued_license()
    lic_id = bundle["license"]["id"]
    owner = make_applicant_headers(bundle["ref"]["owner_id"])
    # Term [2026-02-01, 2027-02-01]; renewal window opens 2026-12-03. Move into it.
    get_success_data(api.set_clock("2026-12-15T00:00:00Z", DIRECTOR))
    get_success_data(api.check_renewal_window(lic_id, TEST_USERS["examiner_headers"]))
    renewed = validate_success(api.renew_license(lic_id, {"renewal_fee_paid_cents": 100000}, owner))
    assert renewed["status"] == "ACTIVE", f"expected ACTIVE after renew, got {renewed['status']}"
    assert renewed["renewal_count"] == 1, f"expected renewal_count 1, got {renewed['renewal_count']}"


def test_sustain_serious_fine_and_demerit_dual_outputs(api):
    """PRD §3.9: "A severity base is selected — twenty-five thousand cents for
    `MINOR`, seventy-five thousand cents for `SERIOUS`, two hundred thousand cents
    for `EGREGIOUS`."
    PRD §3.9: "a `SERIOUS` adds four"

    Sustaining one SERIOUS violation (prior demerit_points=0, FINE) produces two
    independent outputs: AdministrativeAction.fine_cents == 75000 and
    License.demerit_points += 4.

    Design: Difficulty/dual_variant_calc/fine_vs_demerit_dual_output_on_violation_and_license
    """
    bundle = setup_issued_license()
    lic_id = bundle["license"]["id"]
    vio = file_violation(lic_id, severity="SERIOUS")
    sustained = validate_success(api.sustain_violation(
        vio["id"], {"action_type": "FINE"}, TEST_USERS["adjudication_officer_headers"]))
    assert sustained["status"] == "SUSTAINED"
    action = get_success_data(api.get_administrative_action(sustained["action_id"], DIRECTOR))
    assert action["fine_cents"] == 75000, f"expected fine 75000, got {action['fine_cents']}"
    lic = get_success_data(api.get_license(lic_id, DIRECTOR))
    assert lic["demerit_points"] == 4, f"expected demerit_points 4, got {lic['demerit_points']}"
    assert lic["outstanding_fine_cents"] == 75000, (
        f"expected outstanding 75000, got {lic['outstanding_fine_cents']}"
    )


# ─── Queue B: calculations ────────────────────────────────────────────────
def test_excise_retailer_tier_no_rebate(api):
    """PRD §3.11: "Third, the rebate base is scaled by a tier multiplier —
    `SUPPLIER` doubles the rebate base, `WHOLESALER` takes it at face value, and
    `RETAILER` earns no rebate at all"

    gross_sales 6000000 RETAILER: excise 240000, rebate 0 -> excise_due 240000.

    Design: Corner/calculations/excise_retailer_no_rebate_correct_result
    """
    bundle = setup_issued_license()
    owner = make_applicant_headers(bundle["ref"]["owner_id"])
    report = validate_success(api.create_compliance_report(
        {"license_id": bundle["license"]["id"], "tier": "RETAILER",
         "period_code": "2026-Q2", "gross_sales_cents": 6000000}, owner), expected_status=201)
    assert report["excise_due_cents"] == 240000, (
        f"expected 240000 for RETAILER (no rebate), got {report['excise_due_cents']}"
    )


def test_quota_status_computed_read_cap_used_available(api):
    """PRD §3.6: "the **cap** is the region's `population` divided by its
    `persons_per_license`, taking the floor (integer division)."
    PRD §3.6: "The per-class cap, used, and available figures are also exposed as
    a computed read against a region, which takes the `license_class_code` of
    interest and returns the `region_code`, `license_class_code`, `cap`, `used`,
    and `available`."

    CTY_LA pop 50000 / ppl 25000 -> cap 2; one SUBMITTED holder -> used 1,
    available 1.

    Design: Corner/calculations/quota_status_computed_read_cap_used_available
    """
    ref, app = create_submitted_application()
    status = get_success_data(api.quota_status(
        ref["region"]["id"], DIRECTOR, params={"license_class_code": "ON_47"}))
    assert status["cap"] == 2, f"expected cap 2, got {status['cap']}"
    assert status["used"] == 1, f"expected used 1, got {status['used']}"
    assert status["available"] == 1, f"expected available 1, got {status['available']}"
