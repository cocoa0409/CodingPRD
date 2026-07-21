"""Vendor invoice pricing (tiered rate + clamps), expense-limit gate, owner-only submission,
and the depth-3 claim-close -> assignment-cancel -> invoice-void cascade.

Translates combinatorial_formula (vendor invoice) and transitive_cascade (close cascade)
difficulty instances plus vendor-invoice corner instances.
"""
from test_helpers import (
    validate_success, validate_error, TEST_USERS, make_vendor_headers,
    setup_assigned_claim, create_vendor, create_vendor_assignment,
    submit_vendor_invoice, submit_and_approve_invoice, advance_claim, get_claim,
    create_vendor_invoice_payload,
)

CM = TEST_USERS["claims_manager_headers"]


# --------------------------------------------------------------------------- #
# Tiered pricing (mode a): DEFENSE_ATTORNEY rate + rounded components + clamp
# --------------------------------------------------------------------------- #
def test_defense_attorney_invoice_amount_computed(api):
    """PRD §3.6: "The labor component is `hours` multiplied by that rate, rounded half up; the
    mileage component is `miles` multiplied by 55 cents, rounded half up; these two rounded
    components are then added to `materials_cents` to form a subtotal."

    Design: Difficulty/combinatorial_formula/vendor_invoice_amount_tiered_clamp
    """
    env = setup_assigned_claim(api, account_overrides={"account_code": "CF1"})
    vendor = create_vendor(api, vendor_type="DEFENSE_ATTORNEY", credentialed_coverages=["PROPERTY"])
    vasg = create_vendor_assignment(api, env["claim"]["id"], vendor["id"], env["adj_headers"],
                                    scope="DEFENSE")
    invoice = submit_vendor_invoice(api, env["claim"]["id"], vasg["id"], vendor["id"],
                                    hours=10, miles=100, materials_cents=20000)
    # 35000*10 = 350000 ; round(100*55) = 5500 ; + 20000 materials = 375500 (below cap).
    assert invoice["amount_cents"] == 375500


def test_defense_attorney_invoice_starts_submitted(api):
    """PRD §3.6: "A submitted invoice starts in `SUBMITTED`."

    Design: Difficulty/combinatorial_formula/vendor_invoice_amount_tiered_clamp
    """
    env = setup_assigned_claim(api, account_overrides={"account_code": "CF1b"})
    vendor = create_vendor(api, vendor_type="DEFENSE_ATTORNEY", credentialed_coverages=["PROPERTY"])
    vasg = create_vendor_assignment(api, env["claim"]["id"], vendor["id"], env["adj_headers"],
                                    scope="DEFENSE")
    invoice = submit_vendor_invoice(api, env["claim"]["id"], vasg["id"], vendor["id"],
                                    hours=10, miles=100, materials_cents=20000)
    assert invoice["amount_cents"] == 375500
    assert invoice["status"] == "SUBMITTED"


def test_vendor_invoice_below_minimum_is_floored(api):
    """PRD §3.6: "The final `amount_cents` is that subtotal, but never less than a 5000-cent
    minimum and never more than a 2,000,000-cent cap — a subtotal below 5000 is raised to 5000,
    and one above 2,000,000 is lowered to 2,000,000."

    Design: Corner/calculations/vendor_invoice_min_floor_applied
    """
    env = setup_assigned_claim(api, account_overrides={"account_code": "C-MF"})
    vendor = create_vendor(api, vendor_type="INDEPENDENT_ADJUSTER", credentialed_coverages=["PROPERTY"])
    vasg = create_vendor_assignment(api, env["claim"]["id"], vendor["id"], env["adj_headers"],
                                    scope="DESK_REVIEW")
    invoice = submit_vendor_invoice(api, env["claim"]["id"], vasg["id"], vendor["id"],
                                    hours=0, miles=0, materials_cents=1000)
    assert invoice["amount_cents"] == 5000


def test_invoice_approval_over_expense_limit_rejected(api):
    """PRD §3.6: "A `ClaimsManager` approves an invoice, moving it `SUBMITTED → APPROVED`, but
    only if it fits the claim's expense budget: `amount_cents` plus the claim's
    `paid_expense_cents` plus its `expense_reserve_cents` must be no greater than the policy's
    `per_claim_expense_limit_cents`, else `ERR_EXPENSE_LIMIT_EXCEEDED`."

    Design: Corner/validations/expense_limit_exceeded_on_approve
    """
    env = setup_assigned_claim(
        api, account_overrides={"account_code": "C-EL"},
        policy_overrides={"per_claim_expense_limit_cents": 100000})
    vendor = create_vendor(api, vendor_type="INDEPENDENT_ADJUSTER", credentialed_coverages=["PROPERTY"])
    vasg = create_vendor_assignment(api, env["claim"]["id"], vendor["id"], env["adj_headers"])
    invoice = submit_vendor_invoice(api, env["claim"]["id"], vasg["id"], vendor["id"],
                                    hours=0, miles=0, materials_cents=200000)
    validate_error(api.transition_vendor_invoice(invoice["id"], "APPROVED", CM),
                   "ERR_EXPENSE_LIMIT_EXCEEDED")


def test_vendor_cannot_invoice_another_vendors_assignment(api):
    """PRD §3.6: "Only a `Vendor` submits one, and only against an assignment it owns — the
    assignment's copied `vendor_id` must equal the submitter's `X-User-ID`, else
    `ERR_UNAUTHORIZED`."

    Design: Corner/validations/vendor_invoice_wrong_owner_rejected
    """
    env = setup_assigned_claim(api, account_overrides={"account_code": "C-WO"})
    vendor_a = create_vendor(api, name="VA", vendor_type="APPRAISER", credentialed_coverages=["PROPERTY"])
    vendor_b = create_vendor(api, name="VB", vendor_type="APPRAISER", credentialed_coverages=["PROPERTY"])
    vasg = create_vendor_assignment(api, env["claim"]["id"], vendor_a["id"], env["adj_headers"])
    payload = create_vendor_invoice_payload(env["claim"]["id"], vasg["id"], hours=2)
    resp = api.create_vendor_invoice(payload, make_vendor_headers(vendor_b["id"]))
    validate_error(resp, "ERR_UNAUTHORIZED")


# --------------------------------------------------------------------------- #
# Depth-3 close cascade
# --------------------------------------------------------------------------- #
def _setup_close_cascade(api, account_code):
    env = setup_assigned_claim(api, account_overrides={"account_code": account_code})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    vendor = create_vendor(api, vendor_type="INDEPENDENT_ADJUSTER", credentialed_coverages=["PROPERTY"])
    vasg = create_vendor_assignment(api, claim_id, vendor["id"], adj)
    invoice = submit_and_approve_invoice(api, claim_id, vasg["id"], vendor["id"],
                                         hours=0, miles=0, materials_cents=300000)
    advance_claim(api, claim_id, adj, "INVESTIGATING", "EVALUATED")
    validate_success(api.transition_claim(claim_id, "CLOSED", adj), 200)
    return env, vasg, invoice


def test_close_cascade_voids_approved_vendor_invoice(api):
    """PRD §3.3: "Cancelling an assignment — whether requested directly or performed by the
    system during claim closure — cascades: every vendor invoice on that assignment whose
    status is `SUBMITTED` or `APPROVED` is voided (each such void running its own release
    cascade described in §3.6)."

    Design: Difficulty/transitive_cascade/claim_close_cancels_assignment_voids_vendor_invoice
    """
    env, vasg, invoice = _setup_close_cascade(api, "TC1")
    assert get_claim(api, env["claim"]["id"], env["adj_headers"])["status"] == "CLOSED"
    assert validate_success(api.get_vendor_invoice(invoice["id"], CM), 200)["status"] == "VOID"


def test_close_cascade_cancels_all_active_assignments(api):
    """PRD §3.9: "When those pass, closure cascades: every `ACTIVE` assignment on the claim is
    cancelled (each firing its own vendor-invoice void cascade from §3.3 and §3.6), both
    `indemnity_reserve_cents` and `expense_reserve_cents` are set to zero, the claim's
    `gross_incurred_cents` and `net_incurred_cents` are recomputed, the assigned adjuster's
    `open_claim_count` is decremented, and the account roll-up is refreshed."

    Design: Difficulty/transitive_cascade/claim_close_cancels_assignment_voids_vendor_invoice
    """
    env, vasg, invoice = _setup_close_cascade(api, "TC1b")
    adj = env["adj_headers"]
    assert validate_success(api.get_assignment(vasg["id"], adj), 200)["status"] == "CANCELLED"
    assert validate_success(api.get_assignment(env["assignment"]["id"], adj), 200)["status"] == "CANCELLED"
