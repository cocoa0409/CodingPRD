"""Home-charging reimbursement: dual-variant pricing, committed-money
conservation, budget gate, review/pay lifecycle, OCC, and segregation of duties.

Difficulty (queue A): estimated-vs-final claim amount, committed-cents invariant.
Corner (queue B): over-budget submit, review-of-approved, submit OCC stale,
SoD pay-by-approver, positive pay-by-other-finance, cross-driver ownership.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    fm_headers, make_driver_headers, make_finance_headers,
)
import test_helpers.factories as fac
import test_helpers.fixtures as fx


# ---------------------------------------------------------------------------
# Difficulty: dual-variant claim reimbursement (estimated vs final)
# ---------------------------------------------------------------------------

def test_claim_estimated_amount_from_claimed_kwh(api):
    """PRD §3.7: "At submission the claim's **estimated amount** is priced from
    the driver's own figures: `estimated_amount_cents` is the `kwh_claimed`
    multiplied by the driver's `home_tariff_cents_per_kwh`, rounded half up to
    whole cents."

    Design: Difficulty/dual_variant_calc/claim_reimbursement_estimated_vs_final
    """
    _, _, claim = fx.submitted_claim(api, driver_overrides={"home_tariff_cents_per_kwh": 15},
                                     claim_overrides={"kwh_claimed": 100})
    assert claim["estimated_amount_cents"] == 1500, f"100 kWh * 15c = 1500, got {claim['estimated_amount_cents']}"


def test_claim_final_amount_from_verified_kwh_diverges(api):
    """PRD §3.7: "Approval prices the **final amount** from the verified quantity
    at the same tariff: `final_amount_cents` is `metered_kwh_verified` multiplied
    by the driver's `home_tariff_cents_per_kwh`, rounded half up to whole cents."
    PRD §3.7: "The final amount diverges from the estimate whenever the verified
    kilowatt-hours differ from those claimed."

    Design: Difficulty/dual_variant_calc/claim_reimbursement_estimated_vs_final
    """
    _, _, claim = fx.submitted_claim(api, driver_overrides={"home_tariff_cents_per_kwh": 15},
                                     claim_overrides={"kwh_claimed": 100})
    approved = fx.review_claim(api, claim["id"], "APPROVE", metered_kwh_verified=80, finance_user_id="fin-1")
    assert approved["final_amount_cents"] == 1200, f"80 kWh * 15c = 1200, got {approved['final_amount_cents']}"
    assert approved["final_amount_cents"] != approved["estimated_amount_cents"], "final must diverge from estimate"


# ---------------------------------------------------------------------------
# Difficulty: committed-money conservation across submit then reject
# ---------------------------------------------------------------------------

def test_claim_submit_debits_committed_budget(api):
    """PRD §3.7: "That estimate becomes the claim's `committed_amount_cents`, and
    the depot's `reimbursement_committed_cents` is debited by it."

    Design: Difficulty/compensating_invariant/reimbursement_committed_conserved_submit_then_reject
    """
    depot, _, _ = fx.submitted_claim(api, driver_overrides={"home_tariff_cents_per_kwh": 15},
                                     claim_overrides={"kwh_claimed": 100})
    assert fx.get_depot(api, depot["id"])["reimbursement_committed_cents"] == 1500


def test_claim_reject_credits_committed_back_to_zero(api):
    """PRD §3.7: "When instead the `decision` is `REJECT`, the claim moves
    `SUBMITTED → REJECTED`: the depot's `reimbursement_committed_cents` is
    credited back by the claim's `committed_amount_cents`, which is then reset to
    0, releasing the money."

    Design: Difficulty/compensating_invariant/reimbursement_committed_conserved_submit_then_reject
    """
    depot, _, claim = fx.submitted_claim(api, driver_overrides={"home_tariff_cents_per_kwh": 15},
                                         claim_overrides={"kwh_claimed": 100})
    rejected = fx.review_claim(api, claim["id"], "REJECT", finance_user_id="fin-1")
    assert rejected["status"] == "REJECTED"
    assert fx.get_depot(api, depot["id"])["reimbursement_committed_cents"] == 0, "submit +1500 then reject -1500 => 0"


# ---------------------------------------------------------------------------
# Corner: budget gate, invalid review, OCC, SoD, ownership
# ---------------------------------------------------------------------------

def test_claim_submit_over_budget_returns_exceeded(api):
    """PRD §3.7: "the depot's current `reimbursement_committed_cents` plus this
    claim's `estimated_amount_cents` must be no greater than the depot's
    `reimbursement_budget_cents`, or the claim is rejected with
    `ERR_REIMBURSEMENT_BUDGET_EXCEEDED` (HTTP 409)".

    Design: Corner/validations/claim_submit_over_budget_returns_exceeded
    """
    depot = fx.new_depot(api, reimbursement_budget_cents=2000)
    driver = fx.new_driver(api, depot["id"], home_tariff_cents_per_kwh=15)
    payload = fac.create_claim_payload(driver["id"], depot["id"], fx.depot_version(api, depot["id"]),
                                       kwh_claimed=200, odometer_start=1000, odometer_end=2000)
    resp = api.create_claim(payload, make_driver_headers(driver["id"]))  # 200*15=3000 > 2000
    validate_error(resp, ApiErrorId.ERR_REIMBURSEMENT_BUDGET_EXCEEDED.value)


def test_review_already_approved_claim_returns_not_submitted(api):
    """PRD §3.7: "A `FinanceManager` reviews a `SUBMITTED` claim by supplying a
    `decision`, whose value is either `APPROVE` or `REJECT`; a claim not in
    `SUBMITTED` is rejected with `ERR_CLAIM_NOT_SUBMITTED` (HTTP 409)."

    Design: Corner/state_machines/review_already_approved_claim_returns_not_submitted
    """
    _, _, claim = fx.approved_claim(api, metered_kwh_verified=90, approver="fin-1",
                                    driver_overrides={"home_tariff_cents_per_kwh": 15})
    resp = api.review_claim(claim["id"], {"decision": "APPROVE", "metered_kwh_verified": 80},
                            make_finance_headers("fin-1"))
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED.value)


def test_claim_submit_stale_depot_version_returns_stale(api):
    """PRD §2.9: "If the supplied `expected_depot_version` does not match the
    depot's current `version`, the write is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/claim_submit_stale_depot_version_returns_stale
    """
    depot = fx.new_depot(api)
    stale_version = depot["version"]  # version 1
    driver = fx.new_driver(api, depot["id"], home_tariff_cents_per_kwh=15)
    # Claim A advances Depot.version to 2.
    fx.submit_claim(api, driver["id"], depot["id"], stale_version, period_month="2026-05",
                    kwh_claimed=10, odometer_start=1000, odometer_end=1100)
    # Claim B still carries stale version 1.
    payload = fac.create_claim_payload(driver["id"], depot["id"], stale_version, period_month="2026-06",
                                       kwh_claimed=10, odometer_start=2000, odometer_end=2100)
    resp = api.create_claim(payload, make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_claim_pay_by_approver_returns_segregation_of_duties(api):
    """PRD §3.7: "the paying `FinanceManager`'s `X-User-ID` must differ from the
    claim's `approved_by_user_id`, or the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — the person who approved a claim may
    not also pay it."

    Design: Corner/rbac/claim_pay_by_approver_returns_segregation_of_duties
    """
    _, _, claim = fx.approved_claim(api, metered_kwh_verified=100, approver="fin-1",
                                    driver_overrides={"home_tariff_cents_per_kwh": 15})
    resp = api.pay_claim(claim["id"], make_finance_headers("fin-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_claim_pay_by_different_finance_user_succeeds(api):
    """PRD §3.7: "Paying an approved claim moves it `APPROVED → PAID`."
    PRD §3.7: "On payment the depot's `reimbursement_committed_cents` is credited
    by the claim's `committed_amount_cents`, which is reset to 0, since the money
    has now left the committed pool."

    Design: Corner/rbac/claim_pay_by_different_finance_user_succeeds
    """
    depot, _, claim = fx.approved_claim(api, metered_kwh_verified=100, approver="fin-1",
                                        driver_overrides={"home_tariff_cents_per_kwh": 15})
    paid = validate_success(api.pay_claim(claim["id"], make_finance_headers("fin-2")), 200)
    assert paid["status"] == "PAID"
    assert fx.get_depot(api, depot["id"])["reimbursement_committed_cents"] == 0


def test_claim_submit_for_other_driver_returns_unauthorized(api):
    """PRD §2.1: "Any reimbursement claim a driver submits or acts upon must
    reference that same driver — the claim's `driver_id` must equal the caller's
    `X-User-ID` — and a driver acting on a claim owned by a different driver is
    rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/claim_submit_for_other_driver_returns_unauthorized
    """
    depot = fx.new_depot(api)
    dr1 = fx.new_driver(api, depot["id"], name="DR1", email="dr1@x.com", home_tariff_cents_per_kwh=15)
    dr2 = fx.new_driver(api, depot["id"], name="DR2", email="dr2@x.com", home_tariff_cents_per_kwh=15)
    payload = fac.create_claim_payload(dr1["id"], depot["id"], fx.depot_version(api, depot["id"]),
                                       kwh_claimed=10, odometer_start=1000, odometer_end=1100)
    # Acting driver X-User-ID = DR2, but claim.driver_id = DR1.
    resp = api.create_claim(payload, make_driver_headers(dr2["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
