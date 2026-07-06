"""Cost-recovery settlement (pay / waive), the site outstanding ledger, and the
public/private ownership precondition on site creation.

Queue A (Difficulty): compensating_invariant (assess/waive conserves ledger).
Queue B (Corner): cross_cutting (pay reconciliation), validations (ownership precondition).
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    setup_completed, register_owner, create_site_payload,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["program_admin_headers"]


# --------------------------------------------------------------------------
# compensating_invariant / recovery_assess_waive_conserves_outstanding
# --------------------------------------------------------------------------
def test_assessment_credits_site_outstanding(api):
    """PRD §3.5: "The site's `outstanding_recovery_cents` is, at all times, the sum of
    `recoverable_cents` over the site's cost recoveries whose `status` is `ASSESSED`, `DISPUTED`, or
    `LIEN_PENDING`."
    PRD §3.4: "Assessment then credits the site's `outstanding_recovery_cents` by the recovery's
    `recoverable_cents`."

    Design: Difficulty/compensating_invariant/recovery_assess_waive_conserves_outstanding
    """
    scn = setup_completed(api, ownership_type="PRIVATE", est_labor=2.5, reserve_qty=3.0,
                          actual_labor=3.0)
    site = validate_success(api.get_site(scn["site_id"], COORD), 200)
    assert site["outstanding_recovery_cents"] == 26565


def test_waive_debits_site_outstanding_back_to_zero(api):
    """PRD §3.5: "waiver is likewise defined only from `ASSESSED`, accepts an optional `reason`,
    advances the recovery `ASSESSED → WAIVED`, and also debits the site's `outstanding_recovery_cents`
    by the recovery's `recoverable_cents`."

    Design: Difficulty/compensating_invariant/recovery_assess_waive_conserves_outstanding
    """
    scn = setup_completed(api, ownership_type="PRIVATE", est_labor=2.5, reserve_qty=3.0,
                          actual_labor=3.0)
    cr = validate_success(api.waive_cost_recovery(scn["cost_recovery_id"], {"reason": "goodwill"}, ADMIN), 200)
    assert cr["status"] == "WAIVED"
    site = validate_success(api.get_site(scn["site_id"], COORD), 200)
    assert site["outstanding_recovery_cents"] == 0


# --------------------------------------------------------------------------
# Corner: cross_cutting / outstanding_recovery_reconciles_after_pay
# --------------------------------------------------------------------------
def test_pay_reconciles_ledger_and_closes_report(api):
    """PRD §3.5: "payment is defined only from `ASSESSED`, requires that the acting owner own the
    site's property owner, advances the recovery `ASSESSED → PAID`, and debits the site's
    `outstanding_recovery_cents` by the recovery's `recoverable_cents`."
    PRD §3.5: "In both cases, if the recovery's linked report is currently `REMEDIATED`, the settlement
    cascades that report `REMEDIATED → CLOSED`."

    Design: Corner/cross_cutting_complexity_layers/outstanding_recovery_reconciles_after_pay
    """
    scn = setup_completed(api, ownership_type="PRIVATE", est_labor=2.5, reserve_qty=3.0,
                          actual_labor=3.0)
    cr = validate_success(api.pay_cost_recovery(scn["cost_recovery_id"], scn["owner_headers"]), 200)
    assert cr["status"] == "PAID"
    site = validate_success(api.get_site(scn["site_id"], COORD), 200)
    assert site["outstanding_recovery_cents"] == 0
    report = validate_success(api.get_report(scn["report_id"], COORD), 200)
    assert report["status"] == "CLOSED"


# --------------------------------------------------------------------------
# Corner: validations / ownership precondition on site creation
# --------------------------------------------------------------------------
def test_private_site_without_owner_rejected(api):
    """PRD §3.1: "Creating a `PRIVATE` site with no `property_owner_id`, or a `PUBLIC` site with one,
    is rejected with `ERR_PRIVATE_SITE_REQUIRES_OWNER` (HTTP 422)."

    Design: Corner/validations/private_site_without_owner_returns_private_site_requires_owner
    """
    resp = api.create_site(create_site_payload(ownership_type="PRIVATE"), COORD)
    validate_error(resp, ApiErrorId.ERR_PRIVATE_SITE_REQUIRES_OWNER)


def test_public_site_with_owner_rejected(api):
    """PRD §3.1: "Creating a `PRIVATE` site with no `property_owner_id`, or a `PUBLIC` site with one,
    is rejected with `ERR_PRIVATE_SITE_REQUIRES_OWNER` (HTTP 422)."

    Design: Corner/validations/public_site_with_owner_returns_private_site_requires_owner
    """
    owner = register_owner(api)
    resp = api.create_site(
        create_site_payload(ownership_type="PUBLIC", property_owner_id=owner["id"]), COORD)
    validate_error(resp, ApiErrorId.ERR_PRIVATE_SITE_REQUIRES_OWNER)
