"""Queue B (breadth) — business validation rules: FMR band, bedroom fit, same
region port, rent reasonableness, rent burden, mobility area.
"""
from test_helpers import (
    api_client, validate_success, validate_error, set_clock,
    create_region, create_landlord, create_unit, create_passed_initial_inspection,
    make_eligible_household, issue_voucher, create_payment_standard,
    request_portability_move,
    create_payment_standard_payload, create_hap_contract_payload,
    create_special_mobility_grant_payload, create_portability_move_payload,
    ADMIN, CASEWORKER, COORDINATOR,
)


def test_payment_standard_below_band_rejected():
    """PRD §3.1: "amount_cents must be at least 90 percent of fmr_cents and at
    most 110 percent of fmr_cents, with both ends of the band inclusive. An
    amount below 90 percent or above 110 percent of the published Fair Market
    Rent is rejected with ERR_PAYMENT_STANDARD_OUT_OF_BAND (HTTP 422)." 80,000
    is below 90% of 100,000.

    Design: Corner/validations/payment_standard_below_band_rejected
    """
    region = create_region(code="BAND_R")
    payload = create_payment_standard_payload(
        region["id"], bedroom_size=1, amount_cents=80000, fmr_cents=100000
    )
    validate_error(
        api_client.create_payment_standard(payload, ADMIN),
        "ERR_PAYMENT_STANDARD_OUT_OF_BAND", 422,
    )


def test_payment_standard_at_lower_band_succeeds():
    """PRD §3.1: "amount_cents must be at least 90 percent of fmr_cents ... with
    both ends of the band inclusive." 90,000 is exactly 90% of 100,000 and
    passes.

    Design: Corner/validations/payment_standard_within_band_succeeds
    """
    region = create_region(code="BAND_OK")
    ps = validate_success(
        api_client.create_payment_standard(
            create_payment_standard_payload(
                region["id"], bedroom_size=1, amount_cents=90000, fmr_cents=100000
            ),
            ADMIN,
        ),
        201,
    )
    assert ps["amount_cents"] == 90000


def _ready_unit_for_leaseup(region_code, *, ps_bedroom, ps_amount, ps_fmr,
                            unit_bedroom, asking, comparable, family_size=3,
                            annual_income_cents=1800000, dependents_count=2):
    set_clock("2026-06-01T00:00:00Z")
    region = create_region(code=region_code)
    create_payment_standard(
        region["id"], bedroom_size=ps_bedroom, amount_cents=ps_amount, fmr_cents=ps_fmr
    )
    hh_kwargs = {"family_size": family_size, "annual_income_cents": annual_income_cents}
    if dependents_count is not None:
        hh_kwargs["dependents_count"] = dependents_count
    household = make_eligible_household(region["id"], **hh_kwargs)
    voucher = issue_voucher(household["id"])
    landlord = create_landlord()
    unit = create_unit(
        landlord["id"], region["id"], bedroom_size=unit_bedroom,
        asking_rent_cents=asking, comparable_rent_cents=comparable,
    )
    create_passed_initial_inspection(unit["id"])
    return voucher, unit


def test_bedroom_mismatch_rejected_at_leaseup():
    """PRD §3.5: "the unit's bedroom_size must be greater than or equal to the
    voucher's bedroom_size, since the program forbids over-housing beyond the
    standard, and a unit smaller than the voucher's bedroom size is rejected with
    ERR_BEDROOM_MISMATCH (HTTP 422)." Voucher (family 3) needs 2 bedrooms; unit
    has 1.

    Design: Corner/validations/bedroom_mismatch_rejected_at_leaseup
    """
    voucher, unit = _ready_unit_for_leaseup(
        "BM_REG", ps_bedroom=2, ps_amount=95000, ps_fmr=100000,
        unit_bedroom=1, asking=90000, comparable=90000,
    )
    resp = api_client.create_hap_contract(
        create_hap_contract_payload(voucher["id"], unit["id"], 90000, voucher["version"]),
        CASEWORKER,
    )
    validate_error(resp, "ERR_BEDROOM_MISMATCH", 422)


def test_same_region_portability_rejected():
    """PRD §3.7: "The receiving region must differ from the voucher's issuing
    region; a request naming the same region the voucher was issued in is
    rejected with ERR_SAME_REGION_PORT (HTTP 422)."

    Design: Corner/validations/same_region_portability_rejected
    """
    home = create_region(code="SR_HOME")
    household = make_eligible_household(home["id"], family_size=2, annual_income_cents=1500000)
    voucher = issue_voucher(household["id"])
    resp = api_client.create_portability_move(
        create_portability_move_payload(voucher["id"], home["id"]), COORDINATOR
    )
    validate_error(resp, "ERR_SAME_REGION_PORT", 422)


def test_rent_not_reasonable_rejected_at_leaseup():
    """PRD §3.5: "the contract_rent_cents must be less than or equal to the
    unit's comparable_rent_cents, with the boundary inclusive, and a contract
    rent above the comparable rent is rejected with ERR_RENT_NOT_REASONABLE
    (HTTP 422)." Contract 100,000 > comparable 90,000.

    Design: Corner/validations/rent_not_reasonable_rejected_at_leaseup
    """
    voucher, unit = _ready_unit_for_leaseup(
        "RR_REG", ps_bedroom=2, ps_amount=110000, ps_fmr=110000,
        unit_bedroom=2, asking=100000, comparable=90000,
    )
    resp = api_client.create_hap_contract(
        create_hap_contract_payload(voucher["id"], unit["id"], 100000, voucher["version"]),
        CASEWORKER,
    )
    validate_error(resp, "ERR_RENT_NOT_REASONABLE", 422)


def test_rent_burden_exceeded_at_initial_leaseup():
    """PRD §3.5: "Lease-up passes the gate when the computed tenant_rent_burden_cents
    is less than or equal to that maximum, with the boundary inclusive ... and a
    burden above forty percent fails with ERR_RENT_BURDEN_EXCEEDED." Studio
    adjusted 600,000 (cap 20,000); ps 30,000 caps subsidy so burden 45,000.

    Design: Corner/validations/rent_burden_exceeded_at_initial_leaseup
    """
    voucher, unit = _ready_unit_for_leaseup(
        "RB_REG", ps_bedroom=0, ps_amount=30000, ps_fmr=30000,
        unit_bedroom=0, asking=60000, comparable=60000,
        family_size=1, annual_income_cents=600000, dependents_count=None,
    )
    resp = api_client.create_hap_contract(
        create_hap_contract_payload(voucher["id"], unit["id"], 60000, voucher["version"]),
        CASEWORKER,
    )
    validate_error(resp, "ERR_RENT_BURDEN_EXCEEDED", 422)


def test_special_mobility_non_opportunity_region_rejected():
    """PRD §3.8: "The target region must be a region whose is_special_mobility_area
    flag is true; a grant naming a non-opportunity region is rejected with
    ERR_NOT_MOBILITY_AREA (HTTP 422)."

    Design: Corner/validations/special_mobility_non_opportunity_region_rejected
    """
    home = create_region(code="SMN_HOME")
    dest = create_region(code="SMN_DEST", is_special_mobility_area=False)
    household = make_eligible_household(home["id"], family_size=2, annual_income_cents=1500000)
    voucher = issue_voucher(household["id"])
    resp = api_client.create_special_mobility_grant(
        create_special_mobility_grant_payload(voucher["id"], dest["id"]), COORDINATOR
    )
    validate_error(resp, "ERR_NOT_MOBILITY_AREA", 422)
