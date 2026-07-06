"""Prior-auth revision cycle, claim-line appeal dimension, cross-entity cascades, and
ledger/open-auth conservation invariants.

Covers Queue A (Difficulty) instances: non_linear_state_machine, transitive_cascade,
cross_entity_state_dependency, compensating_invariant.
"""
from test_helpers import validate_success, validate_error
from test_helpers.assertions import assert_same_instant
from test_helpers.test_users import TEST_USERS, make_practitioner_headers
from test_helpers.fixtures import (
    setup_pended_prior_auth, setup_denied_appealed_line, setup_order_auth_pending,
)


# ─── Queue A: non_linear_state_machine ───────────────────────────────

def test_priorauth_resubmit_returns_to_submitted(api):
    """PRD §3.4: "A `BillingSpecialist` resubmits a pended authorization, advancing it
    from `PENDED` back to `SUBMITTED`; resubmission requires that the authorization
    currently be `PENDED` and is guarded by optimistic concurrency control as described
    in §2.6."

    Design: Difficulty/non_linear_state_machine/prior_auth_pend_resubmit_cycle
    """
    cast, pa = setup_pended_prior_auth()
    resubmitted = validate_success(
        api.resubmit_prior_auth(
            pa["id"], {"expected_prior_auth_version": pa["version"]},
            TEST_USERS["billing_headers"]), 200)
    assert resubmitted["status"] == "SUBMITTED"


def test_priorauth_resubmit_increments_round_and_resets_deadline(api):
    """PRD §3.4: "Resubmission increments `submission_round` by 1, resets
    `decision_deadline` to the logical clock plus fourteen days, and increments the
    authorization's `version`."

    Design: Difficulty/non_linear_state_machine/prior_auth_pend_resubmit_cycle
    """
    # Clock is 2026-06-01; resubmit resets decision_deadline to clock + 14d = 2026-06-15.
    cast, pa = setup_pended_prior_auth()
    resubmitted = validate_success(
        api.resubmit_prior_auth(
            pa["id"], {"expected_prior_auth_version": pa["version"]},
            TEST_USERS["billing_headers"]), 200)
    assert resubmitted["submission_round"] == 2
    assert_same_instant(resubmitted["decision_deadline"], "2026-06-15T00:00:00Z")


def test_appeal_overturn_drives_adjudication_back_to_adjudicated(api):
    """PRD §3.6: "An overturned appeal sets `appeal_status` to `APPEAL_OVERTURNED` and,
    for a line whose `adjudication_status` is `DENIED` and `appeal_status` is `APPEALED`,
    moves `adjudication_status` from `DENIED` back to `ADJUDICATED`, recomputes the
    line's `allowed_cents`, recomputes the order's `allowed_total_cents`, and increments
    the line's `version`."

    Design: Difficulty/non_linear_state_machine/claim_line_parallel_adjudication_appeal_dimensions
    """
    cast, cl = setup_denied_appealed_line(fee_schedule_cents=30000)
    decided = validate_success(
        api.appeal_decision(cl["id"], {"outcome": "OVERTURNED"}, TEST_USERS["compliance_headers"]),
        200)
    assert decided["adjudication_status"] == "ADJUDICATED"
    assert decided["appeal_status"] == "APPEAL_OVERTURNED"


def test_appeal_overturn_recomputes_line_allowed(api):
    """PRD §3.6: "An overturned appeal sets `appeal_status` to `APPEAL_OVERTURNED` and,
    for a line whose `adjudication_status` is `DENIED` and `appeal_status` is `APPEALED`,
    moves `adjudication_status` from `DENIED` back to `ADJUDICATED`, recomputes the
    line's `allowed_cents`, recomputes the order's `allowed_total_cents`, and increments
    the line's `version`."

    Design: Difficulty/non_linear_state_machine/claim_line_parallel_adjudication_appeal_dimensions
    """
    cast, cl = setup_denied_appealed_line(fee_schedule_cents=30000)
    decided = validate_success(
        api.appeal_decision(cl["id"], {"outcome": "OVERTURNED"}, TEST_USERS["compliance_headers"]),
        200)
    # NONE modifier: allowed_cents == base == 30000 after overturn-recompute.
    assert decided["allowed_cents"] == 30000


# ─── Queue A: transitive_cascade ─────────────────────────────────────

def test_appeal_overturn_cascades_to_order_ledger_depth3(api):
    """PRD §2.5: "When a claim line is adjudicated, denied, or has a denial overturned on
    appeal, the owning order's `allowed_total_cents` ledger is recomputed."
    PRD §3.6: "An overturned appeal sets `appeal_status` to `APPEAL_OVERTURNED` and, for
    a line whose `adjudication_status` is `DENIED` and `appeal_status` is `APPEALED`,
    moves `adjudication_status` from `DENIED` back to `ADJUDICATED`, recomputes the
    line's `allowed_cents`, recomputes the order's `allowed_total_cents`, and increments
    the line's `version`."

    Design: Difficulty/transitive_cascade/appeal_overturn_cascade_depth3
    """
    cast, cl = setup_denied_appealed_line(fee_schedule_cents=30000)
    order_before = validate_success(
        api.get_device_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    assert order_before["allowed_total_cents"] == 0  # line still DENIED
    decided = validate_success(
        api.appeal_decision(cl["id"], {"outcome": "OVERTURNED"}, TEST_USERS["compliance_headers"]),
        200)
    assert decided["adjudication_status"] == "ADJUDICATED"
    assert decided["allowed_cents"] == 30000
    order_after = validate_success(
        api.get_device_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    assert order_after["allowed_total_cents"] == 30000


def test_appeal_overturn_bumps_line_version(api):
    """PRD §3.6: "An overturned appeal sets `appeal_status` to `APPEAL_OVERTURNED` and,
    for a line whose `adjudication_status` is `DENIED` and `appeal_status` is `APPEALED`,
    moves `adjudication_status` from `DENIED` back to `ADJUDICATED`, recomputes the
    line's `allowed_cents`, recomputes the order's `allowed_total_cents`, and increments
    the line's `version`."

    Design: Difficulty/transitive_cascade/appeal_overturn_cascade_depth3
    """
    cast, cl = setup_denied_appealed_line(fee_schedule_cents=30000)
    before_version = cl["version"]
    decided = validate_success(
        api.appeal_decision(cl["id"], {"outcome": "OVERTURNED"}, TEST_USERS["compliance_headers"]),
        200)
    assert decided["version"] > before_version


def test_cancel_cascades_priorauth_to_denied_depth2(api):
    """PRD §3.3: "If a prior authorization for the order is currently in `SUBMITTED` or
    `PENDED`, cancellation cascades to set that authorization to `DENIED`."

    Design: Difficulty/transitive_cascade/order_cancel_cascade_depth2
    """
    cast = setup_order_auth_pending()
    cancelled = validate_success(
        api.cancel_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    assert cancelled["status"] == "CANCELLED"
    pa = validate_success(api.get_prior_auth(cast["pa_id"], TEST_USERS["compliance_headers"]), 200)
    assert pa["status"] == "DENIED"


def test_cancel_cascades_pended_priorauth_to_denied(api):
    """PRD §3.3: "Cancellation is available to a `BillingSpecialist` while the order is in
    either `INTAKE` or `AUTH_PENDING`, moving it to the terminal `CANCELLED` state and
    incrementing the order's `version`. If a prior authorization for the order is
    currently in `SUBMITTED` or `PENDED`, cancellation cascades to set that authorization
    to `DENIED`."

    Design: Difficulty/transitive_cascade/order_cancel_cascade_depth2
    """
    # Distinct branch: the covering auth is PENDED (not SUBMITTED) when cancel fires.
    cast = setup_order_auth_pending()
    api.pend_prior_auth(cast["pa_id"], TEST_USERS["compliance_headers"])
    cancelled = validate_success(
        api.cancel_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    assert cancelled["status"] == "CANCELLED"
    pa = validate_success(api.get_prior_auth(cast["pa_id"], TEST_USERS["compliance_headers"]), 200)
    assert pa["status"] == "DENIED"


# ─── Queue A: cross_entity_state_dependency ──────────────────────────

def test_priorauth_approval_bubbles_order_to_fabrication(api):
    """PRD §2.5: "When a prior authorization is approved, the order it covers advances
    from `AUTH_PENDING` to `FABRICATION`."
    PRD §3.4: "Approval stamps an `auth_number`, increments the authorization's
    `version`, and — provided at least one fabrication milestone exists for the order —
    cascades the order from `AUTH_PENDING` to `FABRICATION`."

    Design: Difficulty/cross_entity_state_dependency/order_fabrication_requires_priorauth_approved
    """
    cast = setup_order_auth_pending(add_milestone_first=True)
    # While the auth is SUBMITTED the order stays AUTH_PENDING.
    before = validate_success(api.get_device_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    assert before["status"] == "AUTH_PENDING"
    approved = validate_success(
        api.approve_prior_auth(cast["pa_id"], TEST_USERS["compliance_headers"]), 200)
    assert approved["status"] == "APPROVED"
    after = validate_success(api.get_device_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    assert after["status"] == "FABRICATION"


def test_priorauth_approval_stamps_auth_number(api):
    """PRD §3.4: "Approval stamps an `auth_number`, increments the authorization's
    `version`, and — provided at least one fabrication milestone exists for the order —
    cascades the order from `AUTH_PENDING` to `FABRICATION`."

    Design: Difficulty/cross_entity_state_dependency/order_fabrication_requires_priorauth_approved
    """
    cast = setup_order_auth_pending(add_milestone_first=True)
    approved = validate_success(
        api.approve_prior_auth(cast["pa_id"], TEST_USERS["compliance_headers"]), 200)
    assert approved["status"] == "APPROVED"
    assert approved["auth_number"] is not None


def test_priorauth_approval_requires_accredited_supplier(api):
    """PRD §3.4: "From `SUBMITTED`, a compliance officer may approve the authorization,
    advancing it to the terminal `APPROVED` state; approval is permitted only when the
    covering order's supplier `accreditation_status` is `ACCREDITED`, otherwise it is
    rejected with `ERR_SUPPLIER_NOT_ACCREDITED`."

    Design: Difficulty/cross_entity_state_dependency/priorauth_approve_requires_supplier_accredited
    """
    # Supplier accreditation_expiry 2026-04-01 with clock 2026-06-01 -> LAPSED.
    cast = setup_order_auth_pending(
        supplier_overrides={"legal_name": "Lapsed O&P",
                            "accreditation_expiry": "2026-04-01T00:00:00Z",
                            "surety_bond_active": True})
    res = api.approve_prior_auth(cast["pa_id"], TEST_USERS["compliance_headers"])
    validate_error(res, "ERR_SUPPLIER_NOT_ACCREDITED")
    pa = validate_success(api.get_prior_auth(cast["pa_id"], TEST_USERS["compliance_headers"]), 200)
    assert pa["status"] == "SUBMITTED"  # unchanged


def test_priorauth_approval_unaccredited_supplier_no_auth_number(api):
    """PRD §3.4: "approval is permitted only when the covering order's supplier
    `accreditation_status` is `ACCREDITED`, otherwise it is rejected with
    `ERR_SUPPLIER_NOT_ACCREDITED`."

    Design: Difficulty/cross_entity_state_dependency/priorauth_approve_requires_supplier_accredited
    """
    # Supplier never accredited (accreditation_expiry null -> UNACCREDITED).
    cast = setup_order_auth_pending(
        supplier_overrides={"legal_name": "Unaccred O&P", "accreditation_expiry": None,
                            "surety_bond_active": True})
    res = api.approve_prior_auth(cast["pa_id"], TEST_USERS["compliance_headers"])
    validate_error(res, "ERR_SUPPLIER_NOT_ACCREDITED")
    pa = validate_success(api.get_prior_auth(cast["pa_id"], TEST_USERS["compliance_headers"]), 200)
    assert pa["auth_number"] is None  # never stamped since approval was blocked


# ─── Queue A: compensating_invariant ─────────────────────────────────

def test_ledger_conserved_under_adjudicate_deny_overturn(api):
    """PRD §3.6: "The order's `allowed_total_cents` is the exact sum of `allowed_cents`
    over only those claim lines whose `adjudication_status` is `ADJUDICATED`; lines in
    `DRAFT`, `SUBMITTED`, or `DENIED` are excluded, and the sum involves no rounding."
    PRD §3.6: "An overturned appeal sets `appeal_status` to `APPEAL_OVERTURNED` and, for
    a line whose `adjudication_status` is `DENIED` and `appeal_status` is `APPEALED`,
    moves `adjudication_status` from `DENIED` back to `ADJUDICATED`, recomputes the
    line's `allowed_cents`, recomputes the order's `allowed_total_cents`, and increments
    the line's `version`."

    Design: Difficulty/compensating_invariant/ledger_conserved_under_deny_then_overturn
    """
    from test_helpers.fixtures import setup_delivered_no_auth_with_lines
    cast, lines = setup_delivered_no_auth_with_lines(
        [{"l_code": "L1960", "modifier": "NONE", "billed_units": 1, "fee_schedule_cents": 30000}])
    cl = lines[0]
    # The line is SUBMITTED after delivery. PRD §3.6 permits denying a SUBMITTED line
    # ("A `BillingSpecialist` may instead deny a `SUBMITTED` line"); deny zeroes the line's
    # allowed_cents and recomputes the ledger -> 0.
    api.deny_claim_line(cl["id"], TEST_USERS["billing_headers"])
    mid = validate_success(api.get_device_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    assert mid["allowed_total_cents"] == 0
    # appeal -> overturn -> ledger restored to exactly 30000
    api.appeal_claim_line(cl["id"], TEST_USERS["compliance_headers"])
    decided = validate_success(
        api.appeal_decision(cl["id"], {"outcome": "OVERTURNED"}, TEST_USERS["compliance_headers"]),
        200)
    assert decided["adjudication_status"] == "ADJUDICATED"
    assert decided["allowed_cents"] == 30000
    order = validate_success(api.get_device_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    assert order["allowed_total_cents"] == 30000


def test_line_adjudication_status_conserved_after_deny_then_overturn(api):
    """PRD §3.6: "An overturned appeal sets `appeal_status` to `APPEAL_OVERTURNED` and,
    for a line whose `adjudication_status` is `DENIED` and `appeal_status` is `APPEALED`,
    moves `adjudication_status` from `DENIED` back to `ADJUDICATED`, recomputes the
    line's `allowed_cents`, recomputes the order's `allowed_total_cents`, and increments
    the line's `version`."

    Design: Difficulty/compensating_invariant/ledger_conserved_under_deny_then_overturn
    """
    from test_helpers.fixtures import setup_delivered_no_auth_with_lines
    cast, lines = setup_delivered_no_auth_with_lines(
        [{"l_code": "L1960", "modifier": "NONE", "billed_units": 1, "fee_schedule_cents": 30000}])
    cl = lines[0]
    # PRD §3.6 denies a SUBMITTED line, files an appeal on the DENIED line, then the
    # OVERTURNED decision moves it DENIED -> ADJUDICATED and recomputes allowed_cents.
    api.deny_claim_line(cl["id"], TEST_USERS["billing_headers"])
    api.appeal_claim_line(cl["id"], TEST_USERS["compliance_headers"])
    api.appeal_decision(cl["id"], {"outcome": "OVERTURNED"}, TEST_USERS["compliance_headers"])
    # The line's own allowed_cents is restored to the full base 30000 — conserved.
    final = validate_success(api.get_claim_line(cl["id"], TEST_USERS["billing_headers"]), 200)
    assert final["adjudication_status"] == "ADJUDICATED"
    assert final["allowed_cents"] == 30000


def test_open_auth_count_conserved_under_submit_then_cancel(api):
    """PRD §3.4: "Submission cascades the creation of a `PriorAuth` in `SUBMITTED` status
    whose `device_order_id` is the order, with `submission_round` of 1 and a
    `decision_deadline` set to the logical clock plus fourteen days, and it increments
    the order's `version`."
    PRD §3.3: "If a prior authorization for the order is currently in `SUBMITTED` or
    `PENDED`, cancellation cascades to set that authorization to `DENIED`."

    Design: Difficulty/compensating_invariant/open_auth_count_conserved_under_submit_then_cancel
    """
    from test_helpers.fixtures import setup_order_at_intake
    cast = setup_order_at_intake(device_category="LOWER_LIMB_PROSTHETIC",
                                 diagnosis="Z89.511", medicare=True)
    pa = validate_success(api.submit_auth(cast["ord_id"], TEST_USERS["billing_headers"]), 201)
    cancelled = validate_success(
        api.cancel_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    assert cancelled["status"] == "CANCELLED"
    # The single open auth is denied — open-auth count back to 0 (DENIED is terminal).
    pa_after = validate_success(api.get_prior_auth(pa["id"], TEST_USERS["compliance_headers"]), 200)
    assert pa_after["status"] == "DENIED"
    open_auths = validate_success(
        api.list_prior_auths(TEST_USERS["billing_headers"],
                             params={"device_order_id": cast["ord_id"]}), 200)
    non_terminal = [p for p in open_auths if p["status"] in ("SUBMITTED", "PENDED", "APPROVED")]
    assert len(non_terminal) == 0


def test_cancelled_order_holds_no_open_auth_after_cancel(api):
    """PRD §3.3: "Cancellation is available to a `BillingSpecialist` while the order is in
    either `INTAKE` or `AUTH_PENDING`, moving it to the terminal `CANCELLED` state and
    incrementing the order's `version`. If a prior authorization for the order is
    currently in `SUBMITTED` or `PENDED`, cancellation cascades to set that authorization
    to `DENIED`."

    Design: Difficulty/compensating_invariant/open_auth_count_conserved_under_submit_then_cancel
    """
    # Distinct observable facet: the order itself ends CANCELLED with its version bumped,
    # and the previously-open auth is the only auth on the order and is now terminal.
    from test_helpers.fixtures import setup_order_at_intake
    cast = setup_order_at_intake(device_category="LOWER_LIMB_PROSTHETIC",
                                 diagnosis="Z89.511", medicare=True)
    created_version = cast["order"]["version"]
    pa = validate_success(api.submit_auth(cast["ord_id"], TEST_USERS["billing_headers"]), 201)
    cancelled = validate_success(
        api.cancel_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    assert cancelled["version"] > created_version
    auths = validate_success(
        api.list_prior_auths(TEST_USERS["billing_headers"],
                             params={"device_order_id": cast["ord_id"]}), 200)
    assert len(auths) == 1
    assert auths[0]["status"] == "DENIED"
