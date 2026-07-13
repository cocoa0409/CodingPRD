"""Permit fee calculation (estimated vs final variants, rounding order),
fee conservation on revoke, and fee-gated / immediately-visible issuance.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_submitted_application, create_corrections_cycle_application,
    create_approved_application, create_paid_approved_application,
    create_issued_permit_scenario,
    approve_all_disciplines, pay_application_fee, issue_permit,
    get_application, get_property,
    make_applicant_headers, get_success_data,
    TEST_USERS,
)

FIRE_MARSHAL = TEST_USERS["fire_marshal_headers"]


# ─── Difficulty/dual_variant_calc/permit_fee_estimated_vs_final ────────────
def test_estimated_fee_frozen_at_submit_with_zero_resubmits(api):
    """PRD §3.3: "computed at submission and stored frozen in `estimated_fee_cents`,
    treats the effective resubmission count as zero, so its surcharge is zero."

    Design: Difficulty/dual_variant_calc/permit_fee_estimated_vs_final
    """
    _prop, app, _pr = create_submitted_application(applicant_user_id="app-1")
    assert app["estimated_fee_cents"] == 20640, \
        f"estimated_fee_cents expected 20640, got {app['estimated_fee_cents']}"


def test_final_fee_uses_actual_resubmit_count(api):
    """PRD §3.3: "computed at permit issuance and stored in `final_fee_cents`, uses
    the application's actual `resubmit_count`."

    Design: Difficulty/dual_variant_calc/permit_fee_estimated_vs_final
    """
    _prop, app, pr = create_corrections_cycle_application(applicant_user_id="app-1b")
    # Resubmit corrections -> resubmit_count becomes 1.
    get_success_data(api_client.resubmit_corrections(pr["id"], make_applicant_headers("app-1b")))
    approve_all_disciplines(pr["id"])
    pay_application_fee(app["id"], "app-1b", 25640)
    issue_permit(app["id"])
    final_app = get_application(app["id"])
    assert final_app["final_fee_cents"] == 25640, \
        f"final_fee_cents expected 25640 (one resubmit), got {final_app['final_fee_cents']}"
    assert final_app["final_fee_cents"] != final_app["estimated_fee_cents"], \
        "final fee must differ from the frozen estimated fee after a resubmit"


# ─── Difficulty/combinatorial_formula/permit_fee_rounding_order ────────────
def test_final_fee_rounds_each_component_before_summing(api):
    """PRD §3.3: "Each of these three components is rounded to whole cents with
    round-half-up individually, before any summation."

    Design: Difficulty/combinatorial_formula/permit_fee_rounding_order
    """
    _prop, app, _pr = create_paid_approved_application(applicant_user_id="app-2", amount_cents=20640)
    issue_permit(app["id"])
    final_app = get_application(app["id"])
    assert final_app["final_fee_cents"] == 20640, \
        f"final_fee_cents expected 20640 (per-component rounding), got {final_app['final_fee_cents']}"


def test_final_fee_is_not_sum_then_round(api):
    """PRD §2.5: "each rate-derived component is rounded to whole cents **first**, and
    only the already-rounded components are summed. Summing the raw products and rounding
    once at the end is not equivalent and is not permitted."

    Design: Difficulty/combinatorial_formula/permit_fee_rounding_order
    """
    _prop, app, _pr = create_paid_approved_application(applicant_user_id="app-2b", amount_cents=20640)
    issue_permit(app["id"])
    final_app = get_application(app["id"])
    # sum-then-round would yield 20641; per-component rounding yields 20640.
    assert final_app["final_fee_cents"] != 20641, \
        "sum-then-round (20641) is explicitly not permitted"


# ─── Difficulty/compensating_invariant/fee_balance_conserved_on_revoke ─────
def test_property_fees_paid_returns_to_pre_issuance_value_on_revoke(api):
    """PRD §3.5: "it adds the `final_fee_cents` to the property's `fees_paid_cents`."
    PRD §3.5: "the property's `fees_paid_cents` decreases by the same `final_fee_cents`"

    Design: Difficulty/compensating_invariant/fee_balance_conserved_on_revoke
    """
    prop, _app, permit = create_issued_permit_scenario(applicant_user_id="app-8", amount_cents=20640)
    before = get_property(prop["id"])
    assert before["fees_paid_cents"] == 20640, \
        f"fees_paid_cents expected 20640 after issuance, got {before['fees_paid_cents']}"
    validate_success(api.revoke_permit(permit["id"], FIRE_MARSHAL), 200)
    after = get_property(prop["id"])
    assert after["fees_paid_cents"] == 0, \
        f"fees_paid_cents expected 0 after revoke, got {after['fees_paid_cents']}"


def test_refunded_cents_recorded_on_revoke(api):
    """PRD §3.5: "the application's `refunded_cents` increases by the permit's
    `final_fee_cents`"

    Design: Difficulty/compensating_invariant/fee_balance_conserved_on_revoke
    """
    _prop, app, permit = create_issued_permit_scenario(applicant_user_id="app-8b", amount_cents=20640)
    validate_success(api.revoke_permit(permit["id"], FIRE_MARSHAL), 200)
    final_app = get_application(app["id"])
    assert final_app["refunded_cents"] == 20640, \
        f"refunded_cents expected 20640 after revoke, got {final_app['refunded_cents']}"


# ─── Corner/validations/corner_issue_permit_fee_unpaid_returns_402 ─────────
def test_issue_permit_with_unpaid_fee_rejected(api):
    """PRD §3.5: "the application's `amount_paid_cents` must be at least that
    `final_fee_cents`, otherwise issuance is rejected with `ERR_FEE_UNPAID`."

    Design: Corner/validations/corner_issue_permit_fee_unpaid_returns_402
    """
    _prop, app, _pr = create_approved_application(applicant_user_id="app-11")
    res = api.create_permit({"application_id": app["id"]}, FIRE_MARSHAL)
    validate_error(res, "ERR_FEE_UNPAID", expected_status=402)


# ─── Corner/consistency_model/corner_permit_issuance_visible_in_same_response
def test_permit_issuance_immediately_visible(api):
    """PRD §3.5: "it advances the application from `APPROVED` to `ISSUED`; and it adds
    the `final_fee_cents` to the property's `fees_paid_cents`."

    Design: Corner/consistency_model/corner_permit_issuance_visible_in_same_response
    """
    prop, app, permit = create_issued_permit_scenario(applicant_user_id="app-14", amount_cents=20640)
    final_app = get_application(app["id"])
    assert final_app["status"] == "ISSUED"
    assert final_app["final_fee_cents"] == 20640
    final_prop = get_property(prop["id"])
    assert final_prop["fees_paid_cents"] == 20640
