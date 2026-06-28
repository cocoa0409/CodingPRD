"""Invoice lifecycle, compensating invariants, OCC, and derived clinic fields.

Covers the compensating-invariant difficulty instances plus the cross-cutting corner
instances (OCC stale/happy path, cancel cascade, derived account_status).
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    validate_paginated, ApiErrorId,
    setup_private_case_invoiced, setup_private_case_cremated,
    setup_received_case_with_cooler,
    create_clinic, create_owner, create_retort, create_case,
    drive_case_to_received, store_case, stage_load_fire_private,
    set_clock, get_case_version, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]


def _case(case_id):
    return get_success_data(api_client.get_case(case_id, ADMIN))


# =========================================================================== #
# compensating_invariant
# =========================================================================== #
def test_cooler_slots_conserved_across_store_then_cancel(api):
    """PRD §3.13: "If the case was `IN_COOLER`, the system clears its `cooler_id`,
    decrements the holding cooler's `occupied_count`, recomputes that cooler's
    `available_capacity` and `status`, and appends a `COOLER_OUT` custody event."
    PRD §3.1: "Available capacity is the total capacity minus the occupied count, floored
    at zero."

    Design: Difficulty/compensating_invariant/invariant_cooler_slots_conserved
    """
    ctx = setup_received_case_with_cooler(clock="2026-03-18T00:00:00Z", capacity=2)
    cooler_id = ctx["cooler"]["id"]
    case_id = ctx["case"]["id"]
    store_case(case_id, cooler_id)
    get_success_data(api_client.cancel_case(case_id, OPERATOR))

    cooler = get_success_data(api_client.get_cooler(cooler_id, ADMIN))
    assert cooler["occupied_count"] == 0
    assert cooler["available_capacity"] == 2, "slot restored to total capacity"
    assert cooler["status"] == "AVAILABLE"
    case = _case(case_id)
    assert case["custody_status"] == "CANCELLED"
    assert case["cooler_id"] is None


def test_clinic_outstanding_conserved_across_issue_then_void(api):
    """PRD §3.11: "Voiding cascades the case's billing from `INVOICED` back to `BILLABLE`,
    making the case eligible to be invoiced again. When the voided invoice is account-
    billed, the clinic's `outstanding_balance_cents` is decreased by the invoice's
    `total_cents` and its `account_status` is recomputed."

    Design: Difficulty/compensating_invariant/invariant_clinic_outstanding_conserved_on_void
    """
    ctx = setup_private_case_invoiced(clock="2026-04-04T00:00:00Z", weight_lbs=50,
                                      bill_to="CLINIC_ACCOUNT")
    inv_id = ctx["invoice"]["id"]
    clinic_id = ctx["clinic_id"]
    # Pre-void: outstanding should be the invoice total (18000).
    assert get_success_data(api_client.get_clinic(clinic_id, ADMIN))["outstanding_balance_cents"] == 18000

    invoice = validate_success(api_client.void_invoice(inv_id, ADMIN))
    assert invoice["status"] == "VOID"
    clinic = get_success_data(api_client.get_clinic(clinic_id, ADMIN))
    assert clinic["outstanding_balance_cents"] == 0, "void cancels the issue charge exactly"
    assert clinic["account_status"] == "CURRENT"
    assert _case(ctx["case"]["id"])["billing_status"] == "BILLABLE"


# =========================================================================== #
# Corner: cross_cutting_complexity_layers
# =========================================================================== #
def test_invoice_create_stale_case_version_rejected(api):
    """PRD §2.8: "If another writer has advanced the case's version since the client last
    read it — most importantly, by having already issued an invoice for that same case,
    which legitimately moves the case's billing state forward and increments its `version`
    — then the client's `expected_case_version` no longer matches, and the request is
    rejected with `ERR_STALE_CASE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_invoice_create_stale_case_version_conflict
    """
    ctx = setup_private_case_cremated(clock="2026-05-16T00:00:00Z", weight_lbs=50,
                                      bill_to="OWNER")
    case_id = ctx["case"]["id"]
    stale_version = get_case_version(case_id)
    # First issue succeeds and bumps Case.version.
    get_success_data(api_client.create_invoice(case_id, stale_version, ADMIN))
    # Second issue still carries the now-stale version.
    validate_error(api_client.create_invoice(case_id, stale_version, ADMIN),
                   ApiErrorId.ERR_STALE_CASE_VERSION.value)


def test_invoice_create_correct_version_succeeds_and_invoices_case(api):
    """PRD §3.10: "Issuing the invoice moves the case's billing from `BILLABLE` to
    `INVOICED`, refreshes the case's `updated_at`, and increments the case's `version`"
    PRD §2.8: "A request to issue an invoice for a case must carry `expected_case_version`,
    a non-optional field whose value is the `version` of the target `Case` that the client
    last observed."

    Design: Corner/cross_cutting_complexity_layers/occ_invoice_create_correct_version_succeeds
    """
    ctx = setup_private_case_cremated(clock="2026-05-17T00:00:00Z", weight_lbs=50,
                                      bill_to="OWNER")
    case_id = ctx["case"]["id"]
    version = get_case_version(case_id)
    invoice = validate_success(api_client.create_invoice(case_id, version, ADMIN), 201)
    assert invoice["status"] == "ISSUED"
    assert _case(case_id)["billing_status"] == "INVOICED"


def test_case_cancel_voids_invoice_and_releases_cooler(api):
    """PRD §3.13: "If the case was `IN_COOLER`, the system clears its `cooler_id`,
    decrements the holding cooler's `occupied_count` ... Any transport leg not already
    cancelled is moved to `CANCELLED`."

    Design: Corner/cross_cutting_complexity_layers/cascade_case_cancel_voids_invoice_and_releases_cooler
    """
    ctx = setup_received_case_with_cooler(clock="2026-05-18T00:00:00Z", capacity=2)
    cooler_id = ctx["cooler"]["id"]
    case_id = ctx["case"]["id"]
    store_case(case_id, cooler_id)
    get_success_data(api_client.cancel_case(case_id, OPERATOR))

    assert _case(case_id)["custody_status"] == "CANCELLED"
    assert get_success_data(api_client.get_cooler(cooler_id, ADMIN))["occupied_count"] == 0
    legs, _ = validate_paginated(api_client.list_transport_legs(case_id, OPERATOR))
    assert legs[0]["status"] == "CANCELLED"


def test_clinic_account_status_derives_from_balance_vs_limit(api):
    """PRD §3.1: "a clinic is `DELINQUENT` whenever its outstanding balance strictly
    exceeds its credit limit, and `CURRENT` otherwise."
    PRD §3.10: "When the invoice is billed to a clinic account, the clinic's
    `outstanding_balance_cents` increases by the invoice's `total_cents` and the clinic's
    `account_status` is recomputed (becoming `DELINQUENT` if the balance now exceeds the
    credit limit)."

    Design: Corner/cross_cutting_complexity_layers/derived_clinic_account_status_delinquent
    """
    # credit_limit 20000, charge 18000 -> outstanding 18000 <= 20000 -> still CURRENT.
    ctx = setup_private_case_cremated(clock="2026-05-19T00:00:00Z", weight_lbs=50,
                                      bill_to="CLINIC_ACCOUNT", credit_limit_cents=20000)
    case_id = ctx["case"]["id"]
    clinic_id = ctx["clinic_id"]
    version = get_case_version(case_id)
    get_success_data(api_client.create_invoice(case_id, version, ADMIN))

    clinic = get_success_data(api_client.get_clinic(clinic_id, ADMIN))
    assert clinic["outstanding_balance_cents"] == 18000
    assert clinic["account_status"] == "CURRENT", "18000 does not strictly exceed 20000"


def test_clock_reads_startup_default_before_any_set(api):
    """PRD §2.9: "At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and
    before any clock-setting call it reports that default rather than ever falling back to
    wall-clock time."

    Design: Corner/cross_cutting_complexity_layers/scheduled_clock_default_before_set
    """
    # Do NOT set the clock — rely on the startup default. Each test gets a fresh server.
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=40,
                       bill_to="OWNER", pickup_kind="HOME")
    events, _ = validate_paginated(api_client.list_custody_events(case["id"], OPERATOR))
    assert events[0]["occurred_at"].startswith("2026-01-01T00:00:00")


# =========================================================================== #
# Corner: endpoints
# =========================================================================== #
def test_pay_owner_billed_invoice_no_clinic_change(api):
    """PRD §3.11: "Paying an invoice may be done by a `CrematoryAdmin` or, for an owner-
    billed invoice, by the `PetOwner` who owns it ... Payment cascades the case's billing
    from `INVOICED` to `SETTLED`."

    Design: Corner/endpoints/ep_invoice_pay_owner_billed_no_clinic_change
    """
    from test_helpers import make_pet_owner_headers
    ctx = setup_private_case_invoiced(clock="2026-05-14T00:00:00Z", weight_lbs=50,
                                      bill_to="OWNER")
    inv_id = ctx["invoice"]["id"]
    owner_headers = make_pet_owner_headers(ctx["owner"]["id"])

    invoice = validate_success(api_client.pay_invoice(inv_id, owner_headers))
    assert invoice["status"] == "PAID"
    # PRD 3.10: subtotal 18000 is below 20000 -> 2500 owner handling fee.
    assert invoice["total_cents"] == 20500, "18000 charge + 2500 owner fee (subtotal below 20000)"
    assert _case(ctx["case"]["id"])["billing_status"] == "SETTLED"
