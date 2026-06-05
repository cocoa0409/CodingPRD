"""Charge-line pricing and visit billing totals.

Covers the tiered E/M multiplier, the round-per-line-then-sum total, the
provisional-vs-final divergence, and the per-patient ledger reconciliation.
"""
import pytest
from test_helpers import (
    validate_success,
    make_provider_headers,
    TEST_USERS,
    create_provider,
    create_patient,
    create_cpt_code,
    create_visit_in_progress,
    create_coded_visit,
    add_charge_line,
)

FD = TEST_USERS["frontdesk_headers"]
BILLER = TEST_USERS["biller_headers"]


# ─── Queue A: dual_variant_calc / visit_billed_total_provisional_vs_final_diverge ───

def test_visit_provisional_total_is_plain_sum_at_code(api):
    """PRD §3.5: "The **provisional** total — written when the visit is coded — is
    the plain sum of the charge lines' already-rounded `amount_cents`. No
    contractual adjustment is applied to the provisional total; it is the straight
    sum of per-line-rounded amounts."

    Design: Difficulty/dual_variant_calc/visit_billed_total_provisional_vs_final_diverge
    """
    provider, patient, cpt, visit = create_coded_visit(
        cpt_overrides={"category": "EM", "base_fee_cents": 8000, "requires_em_level": True},
        charge_overrides={"units": 1, "em_level": 3},
    )
    # base 8000 * 1.0 (em_level 3) * 1 = 8000 provisional
    assert visit["status"] == "CODED"
    assert visit["billed_total_cents"] == 8000, (
        f"provisional total must be the plain per-line sum 8000, got {visit['billed_total_cents']}"
    )


def test_visit_final_total_applies_contractual_writedown(api):
    """PRD §3.5: "it multiplies the provisional sum by the quantity one minus the
    contractual adjustment rate of 0.10 (that is, by 0.90), then rounds the result
    half up to whole cents once."

    Design: Difficulty/dual_variant_calc/visit_billed_total_provisional_vs_final_diverge
    """
    provider, patient, cpt, visit = create_coded_visit(
        cpt_overrides={"category": "EM", "base_fee_cents": 8000, "requires_em_level": True},
        charge_overrides={"units": 1, "em_level": 3},
    )
    assert visit["billed_total_cents"] == 8000
    finalized = validate_success(api.finalize_visit(visit["id"], BILLER), 200)
    # final = round(8000 * 0.90) = 7200
    assert finalized["billed_total_cents"] == 7200, (
        f"final total must be the provisional sum written down by 10%, got {finalized['billed_total_cents']}"
    )


# ─── Queue A: combinatorial_formula / em_level_tiered_multiplier_mode_a ───

def test_charge_line_em_level_four_multiplier(api):
    """PRD §3.3: "level 1 maps to a multiplier of 0.5, level 2 to 0.8, level 3 to
    1.0, level 4 to 1.4, and level 5 to 2.0. The raw amount is the base multiplied
    by this multiplier and then by the number of `units`."

    Design: Difficulty/combinatorial_formula/em_level_tiered_multiplier_mode_a
    """
    provider, patient, visit = create_visit_in_progress()
    cpt = create_cpt_code(category="EM", base_fee_cents=10000, requires_em_level=True)
    line = add_charge_line(visit["id"], provider["id"], cpt["code"], units=1, em_level=4)
    # 10000 * 1.4 * 1 = 14000
    assert line["amount_cents"] == 14000, (
        f"em_level 4 multiplier 1.4 on base 10000 must yield 14000, got {line['amount_cents']}"
    )


def test_charge_line_em_level_one_half_multiplier(api):
    """PRD §3.3: "level 1 maps to a multiplier of 0.5, level 2 to 0.8, level 3 to
    1.0, level 4 to 1.4, and level 5 to 2.0. The raw amount is the base multiplied
    by this multiplier and then by the number of `units`."

    Design: Difficulty/combinatorial_formula/em_level_tiered_multiplier_mode_a
    """
    provider, patient, visit = create_visit_in_progress()
    cpt = create_cpt_code(category="EM", base_fee_cents=10000, requires_em_level=True)
    line = add_charge_line(visit["id"], provider["id"], cpt["code"], units=1, em_level=1)
    # 10000 * 0.5 * 1 = 5000
    assert line["amount_cents"] == 5000, (
        f"em_level 1 multiplier 0.5 on base 10000 must yield 5000, got {line['amount_cents']}"
    )


# ─── Queue A: combinatorial_formula / visit_total_round_per_line_then_sum_mode_b ───

def test_charge_line_rounds_half_up_per_line(api):
    """PRD §2.7: "A charge line is rounded to whole cents at the line level, when
    the line amount is computed."

    Design: Difficulty/combinatorial_formula/visit_total_round_per_line_then_sum_mode_b
    """
    provider, patient, visit = create_visit_in_progress()
    cpt = create_cpt_code(category="EM", base_fee_cents=8123, requires_em_level=True)
    # 8123 * 0.8 = 6498.4 -> round_half_up -> 6498
    line = add_charge_line(visit["id"], provider["id"], cpt["code"], units=1, em_level=2)
    assert line["amount_cents"] == 6498, (
        f"per-line round_half_up of 6498.4 must be 6498, got {line['amount_cents']}"
    )


def test_visit_total_rounds_per_line_then_sums(api):
    """PRD §2.7: "A visit's billed total is then formed by **summing the
    already-rounded line amounts** — the system rounds per line first and then sums,
    never the reverse."

    Design: Difficulty/combinatorial_formula/visit_total_round_per_line_then_sum_mode_b
    """
    provider, patient, visit = create_visit_in_progress()
    cpt = create_cpt_code(category="EM", base_fee_cents=8123, requires_em_level=True)
    prov_hdr = make_provider_headers(provider["id"])
    # two lines, each 8123 * 0.8 = 6498.4 -> 6498; sum = 12996 (not sum-then-round 12997)
    add_charge_line(visit["id"], provider["id"], cpt["code"], units=1, em_level=2)
    add_charge_line(visit["id"], provider["id"], cpt["code"], units=1, em_level=2)
    coded = validate_success(api.code_visit(visit["id"], prov_hdr), 200)
    assert coded["billed_total_cents"] == 12996, (
        f"round-per-line-then-sum must be 12996, not 12997 sum-then-round; "
        f"got {coded['billed_total_cents']}"
    )


# ─── Queue B: entities / charge_line_amount_input_ignored_computed ───

def test_charge_line_amount_is_computed_not_supplied(api):
    """PRD §3.3: "The line's `amount_cents` is always computed by the system; any
    client-supplied amount is ignored."

    Design: Corner/entities/charge_line_amount_input_ignored_computed
    """
    provider, patient, visit = create_visit_in_progress()
    cpt = create_cpt_code(category="VACCINE_ADMIN", base_fee_cents=5000, requires_em_level=False)
    prov_hdr = make_provider_headers(provider["id"])
    # supply a bogus amount_cents; it must be ignored, and 5000 * 1.0 * 2 = 10000
    res = api.create_charge_line(
        visit["id"], {"cpt_code": cpt["code"], "units": 2, "amount_cents": 999999}, prov_hdr
    )
    line = validate_success(res, 201)
    assert line["amount_cents"] == 10000, (
        f"computed amount 5000*1.0*2 must be 10000, client value ignored; got {line['amount_cents']}"
    )


# ─── Queue B: consistency_model / finalize_response_reflects_charges_immediately ───

def test_finalize_response_carries_final_total_immediately(api):
    """PRD §3.6: "First, the visit's `billed_total_cents` is set to the final variant
    of the total and the charge-line amounts are locked."

    Design: Corner/consistency_model/finalize_response_reflects_charges_immediately
    """
    provider, patient, cpt, visit = create_coded_visit(
        cpt_overrides={"category": "EM", "base_fee_cents": 8000, "requires_em_level": True},
        charge_overrides={"units": 1, "em_level": 3},
    )
    finalized = validate_success(api.finalize_visit(visit["id"], BILLER), 200)
    assert finalized["status"] == "FINALIZED"
    assert finalized["billed_total_cents"] == 7200, (
        f"finalize response itself must carry final total 7200, got {finalized['billed_total_cents']}"
    )


# ─── Queue B: cross_cutting / lifetime_charges_derived_field_reconciliation ───

def test_lifetime_charges_sums_finalized_visits(api):
    """PRD §3.2: "`lifetime_charges_cents` is the running sum of `billed_total_cents`
    across this patient's `FINALIZED` visits."

    Design: Corner/cross_cutting/lifetime_charges_derived_field_reconciliation
    """
    provider = create_provider()
    patient = create_patient()
    # Visit A: EM base 8000 em3 -> provisional 8000 -> final 7200
    _, _, _, visit_a = create_coded_visit(
        provider=provider, patient=patient,
        cpt_overrides={"category": "EM", "base_fee_cents": 8000, "requires_em_level": True},
        charge_overrides={"units": 1, "em_level": 3},
    )
    validate_success(api.finalize_visit(visit_a["id"], BILLER), 200)
    # Visit B: PREVENTIVE base 12000 -> provisional 12000 -> final 10800
    _, _, _, visit_b = create_coded_visit(
        provider=provider, patient=patient,
        cpt_overrides={"category": "PREVENTIVE", "base_fee_cents": 12000, "requires_em_level": False},
        charge_overrides={"units": 1},
        visit_overrides={"visit_type": "PHYSICAL",
                         "scheduled_start": "2026-06-01T10:00:00Z",
                         "scheduled_end": "2026-06-01T10:30:00Z"},
    )
    validate_success(api.finalize_visit(visit_b["id"], BILLER), 200)

    refreshed = validate_success(api.get_patient(patient["id"], FD), 200)
    assert refreshed["lifetime_charges_cents"] == 18000, (
        f"lifetime charges must sum FINALIZED totals 7200 + 10800 = 18000, "
        f"got {refreshed['lifetime_charges_cents']}"
    )
