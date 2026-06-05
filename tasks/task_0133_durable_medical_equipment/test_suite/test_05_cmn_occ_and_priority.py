"""CMN activation: optimistic concurrency, supersede invariant, and the two
deliberate validation-priority orderings on certificate / order endpoints.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    fixtures,
    factories as f,
)
from test_helpers.test_users import make_supplier_headers, TEST_USERS

PHYSICIAN = TEST_USERS["physician_headers"]


# ─── Difficulty: priority_pair_validation_conflict ────
def test_state_beats_cmn_required_on_mark_ready(api):
    """PRD §2.8: "then the generic state precondition for the requested transition
    (ERR_INVALID_STATE); then the domain-specific business rules."
    PRD §3.6: "Moving an order from DRAFT to READY_FOR_DELIVERY ... requires the
    order to be in DRAFT status (ERR_INVALID_STATE otherwise)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_cmn_required_on_mark_ready
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "requires_cmn": True},
    )
    cmn, _ = fixtures.activate_cmn_for_order(order, supplier, signed_date="2025-12-15")
    sup_headers = make_supplier_headers(supplier["id"])
    # Order reaches READY_FOR_DELIVERY with an ACTIVE CMN.
    get_success_data(api.mark_ready(order["id"], sup_headers))
    # Revoke the CMN so the CMN gate would now fail; order is still READY.
    get_success_data(api.revoke_cmn(cmn["id"], PHYSICIAN))

    # mark-ready again: order is not DRAFT -> state check (409) beats CMN gate (422).
    resp = api.mark_ready(order["id"], sup_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_business_temporal_beats_occ_on_cmn_activate(api):
    """PRD §3.3: "The signed-date check is evaluated before the version check, so
    that a certificate signed after the order surfaces ERR_CMN_SIGNED_AFTER_ORDER
    even in the case where the supplied version is also stale."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_beats_occ_on_cmn_activate
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "requires_cmn": True},
        ordered_at_utc="2026-01-01T00:00:00Z",
    )
    order_v0 = order["version"]
    # CMN#1 signed before order, activated -> bumps order version (v0 now stale).
    fixtures.activate_cmn_for_order(order, supplier, signed_date="2025-12-15")
    # CMN#2 signed AFTER the order; activate with the stale pre-supersede version.
    cmn2 = get_success_data(
        api.create_cmn(
            f.create_cmn_payload(order["id"], signed_date="2026-02-01",
                                 length_of_need_months=24),
            PHYSICIAN,
        )
    )
    resp = api.activate_cmn(cmn2["id"], order_v0, PHYSICIAN)
    # Signed-after-order (422) is reported, not the stale-version (412).
    validate_error(resp, ApiErrorId.ERR_CMN_SIGNED_AFTER_ORDER.value)


def test_state_check_beats_cmn_required_via_double_mark_ready_path(api):
    """PRD §3.6: "requires the order to be in DRAFT status (ERR_INVALID_STATE
    otherwise) and then enforces three business gates."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_cmn_required_on_mark_ready
    """
    # Second test for the same instance: a CMN-required order driven past DRAFT
    # whose CMN is then revoked still yields ERR_INVALID_STATE on re-mark-ready,
    # confirming the state precondition pre-empts the business CMN gate.
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "requires_cmn": True},
    )
    cmn, _ = fixtures.activate_cmn_for_order(order, supplier, signed_date="2025-12-15")
    sup_headers = make_supplier_headers(supplier["id"])
    delivered_order, _ = fixtures.drive_order_to_delivered(
        order, supplier, with_cmn=False, pod_signature_name="X"
    )
    get_success_data(api.revoke_cmn(cmn["id"], PHYSICIAN))
    resp = api.mark_ready(order["id"], sup_headers)  # order is DELIVERED, not DRAFT
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_business_temporal_beats_occ_pure_signed_after_still_rejects(api):
    """PRD §3.3: "the certificate's signed_date must be on or before the calendar
    date of the order's ordered_at_utc; a certificate signed after the order was
    placed is rejected with ERR_CMN_SIGNED_AFTER_ORDER."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_beats_occ_on_cmn_activate
    """
    # Second test for the same instance: even at the order's current (correct)
    # version, a CMN signed after the order is rejected on the temporal rule.
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "requires_cmn": True},
        ordered_at_utc="2026-01-01T00:00:00Z",
    )
    cmn = get_success_data(
        api.create_cmn(f.create_cmn_payload(order["id"], signed_date="2026-02-01"), PHYSICIAN)
    )
    resp = api.activate_cmn(cmn["id"], order["version"], PHYSICIAN)
    validate_error(resp, ApiErrorId.ERR_CMN_SIGNED_AFTER_ORDER.value)


# ─── Difficulty: compensating_invariant (CMN count) ───
def test_cmn_supersede_sets_superseded_fields(api):
    """PRD §3.3: "that prior certificate is superseded — its superseded_by_id is set
    to the id of the newly activated certificate and its status moves from ACTIVE to
    the terminal SUPERSEDED state."

    Design: Difficulty/compensating_invariant/cmn_supersede_active_count_conserved
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "requires_cmn": True},
        ordered_at_utc="2026-12-01T00:00:00Z",
    )
    cmn1, _ = fixtures.activate_cmn_for_order(order, supplier, signed_date="2026-11-20")
    sup_headers = make_supplier_headers(supplier["id"])
    cur = get_success_data(api.get_order(order["id"], sup_headers))
    cmn2 = get_success_data(
        api.create_cmn(
            f.create_cmn_payload(order["id"], signed_date="2026-11-25",
                                 length_of_need_months=24),
            PHYSICIAN,
        )
    )
    get_success_data(api.activate_cmn(cmn2["id"], cur["version"], PHYSICIAN))

    cmn1_after = get_success_data(api.get_cmn(cmn1["id"], PHYSICIAN))
    assert cmn1_after["status"] == "SUPERSEDED"
    assert cmn1_after["superseded_by_id"] == cmn2["id"]


def test_cmn_supersede_active_count_conserved_at_one(api):
    """PRD §3.3: "The system guarantees that an order has at most one active
    certificate at a time ... so that the count of active certificates on the order
    remains exactly one."

    Design: Difficulty/compensating_invariant/cmn_supersede_active_count_conserved
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "requires_cmn": True},
        ordered_at_utc="2026-12-01T00:00:00Z",
    )
    cmn1, _ = fixtures.activate_cmn_for_order(order, supplier, signed_date="2026-11-20")
    sup_headers = make_supplier_headers(supplier["id"])
    cur = get_success_data(api.get_order(order["id"], sup_headers))
    cmn2 = get_success_data(
        api.create_cmn(
            f.create_cmn_payload(order["id"], signed_date="2026-11-25",
                                 length_of_need_months=24),
            PHYSICIAN,
        )
    )
    get_success_data(api.activate_cmn(cmn2["id"], cur["version"], PHYSICIAN))

    active, meta = validate_paginated(
        api.list_cmns(PHYSICIAN, params={"order_id": order["id"], "status": "ACTIVE", "limit": 100})
    )
    assert len(active) == 1
    assert active[0]["id"] == cmn2["id"]


# ─── Corner: §cross_cutting_complexity_layers (OCC) ───
def test_occ_version_increments_on_cmn_activate(api):
    """PRD §3.3: "Activation also increments the order's version by 1."
    PRD §2.9: "Because a successful activation increments the order's version."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_cmn_activate
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "requires_cmn": True},
        ordered_at_utc="2026-01-01T00:00:00Z",
    )
    assert order["version"] == 1
    cmn = get_success_data(
        api.create_cmn(f.create_cmn_payload(order["id"], signed_date="2025-12-15"), PHYSICIAN)
    )
    activated = validate_success(api.activate_cmn(cmn["id"], order["version"], PHYSICIAN), 200)
    assert activated["status"] == "ACTIVE"

    sup_headers = make_supplier_headers(supplier["id"])
    after = get_success_data(api.get_order(order["id"], sup_headers))
    assert after["version"] == 2


def test_occ_stale_version_on_cmn_activate_rejected(api):
    """PRD §2.9: "If that value does not match the target order's current version,
    the activation is rejected with ERR_STALE_ORDER_VERSION (HTTP 412). Because a
    successful activation increments the order's version, a second activation request
    still carrying the previously observed version is necessarily stale and is
    rejected on this rule."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_cmn_activate_rejected
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "requires_cmn": True},
        ordered_at_utc="2026-01-01T00:00:00Z",
    )
    order_v0 = order["version"]
    cmn1 = get_success_data(
        api.create_cmn(f.create_cmn_payload(order["id"], signed_date="2025-12-10"), PHYSICIAN)
    )
    get_success_data(api.activate_cmn(cmn1["id"], order_v0, PHYSICIAN))
    cmn2 = get_success_data(
        api.create_cmn(
            f.create_cmn_payload(order["id"], signed_date="2025-12-12",
                                 length_of_need_months=24),
            PHYSICIAN,
        )
    )
    # CMN#2 carries the stale pre-supersede version.
    resp = api.activate_cmn(cmn2["id"], order_v0, PHYSICIAN)
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION.value)
