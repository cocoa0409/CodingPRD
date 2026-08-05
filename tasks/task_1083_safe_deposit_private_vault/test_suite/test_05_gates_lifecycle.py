"""Activation gates, delinquency boundary, segregation of duties, and optimistic
concurrency (Difficulty queue A + Corner queue B).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_compliance_officer_headers,
)
from test_helpers import factories as F
from test_helpers import fixtures as X

ADMIN = TEST_USERS["vault_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / activate_requires_box_available
# ---------------------------------------------------------------------------
def test_activate_second_rental_on_rented_box_rejected(api):
    """PRD §3.3: "Third, the target box must be `AVAILABLE`, else
    `ERR_BOX_NOT_AVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/activate_requires_box_available
    """
    ctx = X.setup_shared_box_two_rentals(api)   # rentalA ACTIVE (box RENTED), rentalB PENDING
    resp = api.activate_rental(ctx["rentalB"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_BOX_NOT_AVAILABLE.value, 409)
    rental_b = validate_success(api.get_rental(ctx["rentalB"]["id"], ADMIN), 200)
    assert rental_b["status"] == "PENDING"


def test_activate_on_available_box_rents_it(api):
    """PRD §3.3: "When all three hold, the rental transitions to `ACTIVE`, its
    `start_date` is set from the logical clock, the box cascades from
    `AVAILABLE` to `RENTED`".

    Design: Difficulty/cross_entity_state_dependency/activate_requires_box_available
    """
    ctx = X.setup_pending_rental(api)
    data = validate_success(api.activate_rental(ctx["rental"]["id"], ADMIN), 200)
    assert data["status"] == "ACTIVE"
    box = validate_success(api.get_box(ctx["box"]["id"], ADMIN), 200)
    assert box["status"] == "RENTED"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / delinquency_boundary_15_days
# ---------------------------------------------------------------------------
def test_delinquency_at_exactly_grace_days(api):
    """PRD §3.4: "When the maximum days-past-due across its open invoices reaches
    the delinquency grace period of 15 days, it moves from `PAST_DUE` to
    `DELINQUENT`, stamps `delinquent_since` from the clock, and cascades its box
    from `RENTED` to `DELINQUENT`."

    Design: Difficulty/boundary_precision_check/delinquency_boundary_15_days
    """
    ctx = X.setup_delinquent_rental(api, clock_iso="2026-06-15T00:00:00Z")  # dpd == 15
    assert ctx["rental"]["status"] == "DELINQUENT"
    assert ctx["box"]["status"] == "DELINQUENT"


def test_below_grace_days_stays_past_due(api):
    """PRD §3.4: "When an `ACTIVE` rental has an `OPEN` invoice whose due date has
    passed and a positive balance, it moves to `PAST_DUE`."
    PRD §3.4: "When the maximum days-past-due across its open invoices reaches the
    delinquency grace period of 15 days, it moves from `PAST_DUE` to
    `DELINQUENT`".

    Design: Difficulty/boundary_precision_check/delinquency_boundary_15_days
    """
    ctx = X.setup_active_rental(api)
    X.set_clock(api, "2026-06-14T00:00:00Z")   # dpd == 14 (< 15)
    validate_success(api.run_billing_cycle(ADMIN), 200)
    rental = validate_success(api.get_rental(ctx["rental"]["id"], ADMIN), 200)
    box = validate_success(api.get_box(ctx["box"]["id"], ADMIN), 200)
    assert rental["status"] == "PAST_DUE"
    assert box["status"] == "RENTED"


# ---------------------------------------------------------------------------
# Corner: state_machines / decommission_rented_box_invalid_state
# ---------------------------------------------------------------------------
def test_decommission_rented_box_rejected(api):
    """PRD §3.1: "taking an `AVAILABLE` box out of service moves it to
    `OUT_OF_SERVICE` (rejected with `ERR_BOX_NOT_AVAILABLE` if it is not
    `AVAILABLE`)".

    Design: Corner/state_machines/decommission_rented_box_invalid_state
    """
    ctx = X.setup_active_rental(api)   # box RENTED
    resp = api.decommission_box(ctx["box"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_BOX_NOT_AVAILABLE.value, 409)
    box = validate_success(api.get_box(ctx["box"]["id"], ADMIN), 200)
    assert box["status"] == "RENTED"


# ---------------------------------------------------------------------------
# Corner: state_machines / compliance_clear_restores_standing
# ---------------------------------------------------------------------------
def test_clearing_only_hold_restores_good_standing(api):
    """PRD §3.10: "Opening a `HOLD`-severity case freezes the renter — it sets
    the renter's `standing` to `FROZEN`". PRD §3.10: "A case may be cleared from
    either `OPEN` or `ESCALATED`, which stamps `resolved_on`, moves it to
    `CLEARED`, and — provided no other `HOLD` case remains open for that renter —
    restores the renter's `standing` to `GOOD`."

    Design: Corner/state_machines/compliance_clear_restores_standing
    """
    renter = X.create_renter(api, verified=False)
    case = validate_success(api.create_compliance_case(
        F.create_compliance_case_payload(renter["id"], case_type="SAR", severity="HOLD"),
        COMPLIANCE), 201)
    frozen = validate_success(api.get_renter(renter["id"], ADMIN), 200)
    assert frozen["standing"] == "FROZEN"
    data = validate_success(api.clear_compliance_case(case["id"], COMPLIANCE), 200)
    assert data["status"] == "CLEARED"
    restored = validate_success(api.get_renter(renter["id"], ADMIN), 200)
    assert restored["standing"] == "GOOD"


# ---------------------------------------------------------------------------
# Corner: validations / drill_not_eligible_on_active_rental
# ---------------------------------------------------------------------------
def test_drill_request_on_active_rental_not_eligible(api):
    """PRD §3.9: "For `ABANDONMENT` and `DELINQUENCY` reasons, drilling is only
    eligible when the box's rental is `DELINQUENT` and past the abandonment
    window; a request that fails this eligibility yields `ERR_DRILL_NOT_ELIGIBLE`."

    Design: Corner/validations/drill_not_eligible_on_active_rental
    """
    ctx = X.setup_active_rental(api)   # rental ACTIVE, not DELINQUENT
    resp = api.create_drilling_order(
        F.create_drilling_order_payload(ctx["box"]["id"], ctx["rental"]["id"], "DELINQUENCY"),
        X.DRILL_REQUESTER)
    validate_error(resp, ApiErrorId.ERR_DRILL_NOT_ELIGIBLE.value, 409)


# ---------------------------------------------------------------------------
# Corner: errors / drilling_approve_by_requester_sod
# ---------------------------------------------------------------------------
def test_drilling_approval_by_requester_rejected(api):
    """PRD §2.9: "Approval must be performed by a *different* operator: if the
    approving `X-User-ID` equals `requested_by_ref`, the approval is rejected
    with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/drilling_approve_by_requester_sod
    """
    ctx = X.setup_delinquent_rental(api, clock_iso="2026-07-10T00:00:00Z")
    order = validate_success(api.create_drilling_order(
        F.create_drilling_order_payload(ctx["box"]["id"], ctx["rental"]["id"], "DELINQUENCY"),
        X.DRILL_REQUESTER), 201)   # requested_by_ref = admin-1
    resp = api.approve_drilling_order(order["id"], make_compliance_officer_headers("admin-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)


# ---------------------------------------------------------------------------
# Corner: errors / activate_before_kyc_verified
# ---------------------------------------------------------------------------
def test_activate_before_kyc_verified_rejected(api):
    """PRD §3.3: "First, the renter's `kyc_status` must be `VERIFIED`, else
    `ERR_KYC_NOT_VERIFIED`."

    Design: Corner/errors/activate_before_kyc_verified
    """
    ctx = X.setup_pending_rental(api, verified=False)
    resp = api.activate_rental(ctx["rental"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_KYC_NOT_VERIFIED.value, 409)
    rental = validate_success(api.get_rental(ctx["rental"]["id"], ADMIN), 200)
    assert rental["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / rental_adjust_plan_stale_version_conflict
# ---------------------------------------------------------------------------
def test_adjust_plan_with_stale_version_rejected(api):
    """PRD §2.8: "Before applying the change, the server compares that value to
    the rental's current `version`. If they differ — because a prior adjustment,
    a billing escalation, or a cure cascade has already advanced the version
    since the client read it — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412), and no field is modified."

    Design: Corner/cross_cutting_complexity_layers/rental_adjust_plan_stale_version_conflict
    """
    ctx = X.setup_active_rental(api)
    rental_id = ctx["rental"]["id"]
    rv1 = ctx["rental"]["version"]
    validate_success(api.adjust_plan(
        rental_id, {"autopay_enabled": True, "expected_rental_version": rv1}, ADMIN), 200)
    # Second write still carries the pre-bump version → stale
    resp = api.adjust_plan(
        rental_id, {"autopay_enabled": False, "expected_rental_version": rv1}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)
