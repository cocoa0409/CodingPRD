"""DNI carry-out boundary precision, termination GST-event generation, and GST tax.

Covers Difficulty queue rule boundary_precision_check and the GST-tax / GST-event corner
instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    setup_active_trust, setup_filed_account, allocate_gst_exemption,
    create_paid_distribution, create_approved_distribution, make_trustee_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["trust_admin_headers"]


# ─────────────────────────────────────────────────────────────
# Rule boundary_precision_check — DNI carryout cap at exactly DNI
# ─────────────────────────────────────────────────────────────

def _pay_single_mandatory(api, dni_cents, amount_cents):
    ctx = setup_active_trust(
        contribution_cents=5_000_000, income_receipts=[(dni_cents, "INTEREST")],
        num_trustees=2, capital_gains_to_income=False)
    g_id = ctx["grantor"]["id"]
    t_prop, t_appr = ctx["trustees"][0]["id"], ctx["trustees"][1]["id"]
    ben_a = get_success_data(api.create_beneficiary(
        {"full_name": "Ben A", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    return create_paid_distribution(ctx["account"]["id"], ben_a["id"], amount_cents,
                                    t_prop, t_appr, "MANDATORY")


def test_carryout_at_amount_equal_to_dni_carries_full(api):
    """PRD §3.6: "each distribution's dni_carried_amount_cents is set to the lesser of its
    amount_cents and the remaining pool, and that amount is then subtracted from the pool."

    Design: Difficulty/boundary_precision_check/dni_carryout_cap_at_exactly_dni
    """
    paid = _pay_single_mandatory(api, dni_cents=1_000_000, amount_cents=1_000_000)
    assert paid["dni_carried_amount_cents"] == 1_000_000


def test_carryout_below_dni_carries_full_amount(api):
    """PRD §3.6: "each distribution's dni_carried_amount_cents is set to the lesser of its
    amount_cents and the remaining pool, and that amount is then subtracted from the pool."

    Design: Difficulty/boundary_precision_check/dni_carryout_cap_at_exactly_dni
    """
    # amount (999999) < DNI (1000000): carries its full amount (the lesser).
    paid = _pay_single_mandatory(api, dni_cents=1_000_000, amount_cents=999_999)
    assert paid["dni_carried_amount_cents"] == 999_999


def test_carryout_above_dni_capped_at_dni(api):
    """PRD §3.6: "each distribution's dni_carried_amount_cents is set to the lesser of its
    amount_cents and the remaining pool, and that amount is then subtracted from the pool."

    Design: Difficulty/boundary_precision_check/dni_carryout_cap_at_exactly_dni
    """
    # amount (1000001) > DNI (1000000): capped at remaining pool (1000000).
    paid = _pay_single_mandatory(api, dni_cents=1_000_000, amount_cents=1_000_001)
    assert paid["dni_carried_amount_cents"] == 1_000_000


# ─────────────────────────────────────────────────────────────
# Rule boundary_precision_check — empty skip set → zero termination events
# ─────────────────────────────────────────────────────────────

def test_terminate_finalize_with_no_skip_beneficiaries_emits_no_events(api):
    """PRD §3.9: "Its cascade creates, for each skip-person beneficiary, a GST event of type
    TAXABLE_TERMINATION whose taxable_amount_cents is that beneficiary's pro-rata share of
    the trust's principal_balance_cents".

    Design: Difficulty/boundary_precision_check/empty_skip_beneficiary_set_yields_zero_gst_events_on_terminate
    """
    # Non-grantor trust with only a non-skip (generation 1) beneficiary; drive it to
    # TERMINATING with its single account FILED, then finalize.
    ctx = setup_active_trust(contribution_cents=5_000_000, num_trustees=1,
                             is_grantor_trust=False)
    g_id = ctx["grantor"]["id"]
    trust_id = ctx["trust"]["id"]
    get_success_data(api.create_beneficiary(
        {"full_name": "Ben NonSkip", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    validate_success(api.terminate_trust(trust_id, ADMIN), 200)  # cascades account to CLOSED
    filing = get_success_data(api.create_filing(ctx["account"]["id"], {}, ADMIN))
    validate_success(api.file_filing(filing["id"], ADMIN), 200)
    finalized = validate_success(api.finalize_termination(trust_id, ADMIN), 200)
    assert finalized["status"] == "TERMINATED"
    data, meta = validate_paginated(api.list_trust_gst_events(trust_id, ADMIN))
    assert meta["total_count"] == 0, f"expected zero GST events, got {meta['total_count']}"


def test_terminate_finalize_reaches_terminated(api):
    """PRD §3.9: "Finalizing termination moves the trust from TERMINATING to the terminal
    TERMINATED state; it is permitted only while the trust is TERMINATING and only when
    every period on the trust is FILED."

    Design: Difficulty/boundary_precision_check/empty_skip_beneficiary_set_yields_zero_gst_events_on_terminate
    """
    ctx = setup_active_trust(contribution_cents=5_000_000, num_trustees=1,
                             is_grantor_trust=False)
    trust_id = ctx["trust"]["id"]
    validate_success(api.terminate_trust(trust_id, ADMIN), 200)
    filing = get_success_data(api.create_filing(ctx["account"]["id"], {}, ADMIN))
    validate_success(api.file_filing(filing["id"], ADMIN), 200)
    finalized = validate_success(api.finalize_termination(trust_id, ADMIN), 200)
    assert finalized["status"] == "TERMINATED"


# ─────────────────────────────────────────────────────────────
# Corner / calculations — GST tax with inclusion ratio
# ─────────────────────────────────────────────────────────────

def test_gst_tax_on_skip_distribution(api):
    """PRD §3.9: "It equals the event's taxable_amount_cents multiplied by the trust's
    inclusion_ratio at event time (the value captured in inclusion_ratio_snapshot, carried
    to six decimal places) multiplied by the GST rate of 0.40, with the product rounded half
    up to whole cents and recorded in gst_tax_cents."

    Design: Corner/calculations/gst_tax_inclusion_ratio_rounding
    """
    # principal 5000000, income 1500000, 2000000 exemption allocated => inclusion_ratio 0.6.
    ctx = setup_active_trust(
        contribution_cents=5_000_000, income_receipts=[(1_500_000, "INTEREST")],
        num_trustees=2, is_grantor_trust=False)
    g_id = ctx["grantor"]["id"]
    trust_id = ctx["trust"]["id"]
    t_prop, t_appr = ctx["trustees"][0]["id"], ctx["trustees"][1]["id"]
    skip = get_success_data(api.create_beneficiary(
        {"full_name": "Grandchild", "grantor_id": g_id, "generation_level": 2}, ADMIN))
    allocate_gst_exemption(trust_id, g_id, 2_000_000, ctx["trust"]["version"])
    paid = create_paid_distribution(ctx["account"]["id"], skip["id"], 1_000_000,
                                    t_prop, t_appr, "MANDATORY")
    data, _ = validate_paginated(
        api.list_gst_events(ADMIN, params={"distribution_id": paid["id"]}))
    assert len(data) == 1
    event = data[0]
    assert event["event_type"] == "TAXABLE_DISTRIBUTION"
    assert event["inclusion_ratio_snapshot"] == pytest.approx(0.6, abs=1e-6)
    # round(1000000 * 0.6 * 0.40) = 240000
    assert event["gst_tax_cents"] == 240000
