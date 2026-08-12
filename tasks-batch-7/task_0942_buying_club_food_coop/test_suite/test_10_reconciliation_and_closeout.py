"""Drop reconciliation: drafting, superseding, segregation of duties, posting,
and the global write gate a closed cycle activates."""

from test_helpers import (
    ApiErrorId,
    FINANCE_POSTER_HEADERS,
    FINANCE_PREPARER_HEADERS,
    FINANCE_PREPARER_USER_ID,
    FINANCE_POSTER_USER_ID,
    FINANCE_SECOND_PREPARER_HEADERS,
    FINANCE_SECOND_PREPARER_USER_ID,
    TEST_USERS,
    assert_drop_reconciliation,
    assert_ledger_identity_holds,
    canonical_world,
    create_drop_reconciliation_payload,
    draft_and_balance_reconciliation,
    drop_run_version,
    refund_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["club_admin_headers"]
FINANCE = TEST_USERS["finance_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


def test_posting_a_reconciliation_before_delivery_returns_invalid_cycle_state(api):
    """PRD §3.9: "Posting closes the drop's books. It requires the reconciliation
    to be `BALANCED`, requires the parent cycle to have status `DELIVERED` — otherwise
    `ERR_INVALID_CYCLE_STATE` — and requires the acting `X-User-ID` to differ from the
    `prepared_by_user_id` that drafted it, failing with `ERR_SEGREGATION_OF_DUTIES`
    when it does not."
    PRD §3.9: "`commission_cents` is the `net_cents` of this drop run's commission
    accrual, or 0 when there is none."
    PRD §2.11: "**Drop ledger balances at post.** After a held variance is resolved,
    the reconciliation's ledger identity holds exactly and its `variance_cents` is 0;
    `member_charges_cents` is then equal to the sum of `supplier_cost_cents`,
    `freight_alloc_cents`, `reefer_alloc_cents`, `commission_cents` and
    `club_margin_cents`."

    Design: Corner/validations/posting_a_reconciliation_before_delivery_returns_invalid_cycle_state
    """
    w = canonical_world(api, "captured")
    reconciliation = draft_and_balance_reconciliation(api, w)

    assert_drop_reconciliation(reconciliation)
    assert reconciliation["status"] == "BALANCED"
    assert reconciliation["commission_cents"] == 0
    assert reconciliation["club_margin_cents"] == 4690
    assert_ledger_identity_holds(reconciliation)

    body = validate_error(
        api.post_drop_reconciliation(reconciliation["id"], FINANCE_POSTER_HEADERS),
        ApiErrorId.ERR_INVALID_CYCLE_STATE.value,
    )
    assert body["error_id"] != ApiErrorId.ERR_INVALID_RECONCILIATION_STATE.value

    assert validate_success(api.get_cycle(w.cycle_id, ADMIN))["status"] == "CONSOLIDATED"
    stored = validate_success(
        api.get_drop_reconciliation(reconciliation["id"], FINANCE)
    )
    assert stored["status"] == "BALANCED"
    assert stored["posted_by_user_id"] is None


def test_the_preparer_of_a_reconciliation_cannot_post_it(api):
    """PRD §2.1: "the only comparison ever made against it is a comparison between
    those two values: segregation of duties is enforced on `X-User-ID`, not on role,
    so the officer who drafted a reconciliation may not be the one who posts it even
    though both actions sit inside the same role."
    PRD §3.9: "Posting moves the reconciliation `BALANCED → POSTED`, writes
    `posted_by_user_id` and stamps `posted_at` with the clock reading, and activates
    the posted-ledger gate at rung 12 for this drop run: refunds, receipt lines,
    commission payouts, volunteer verification and further reconciliation drafts on it
    are all thereafter refused with `ERR_RECONCILIATION_POSTED`."

    Design: Corner/rbac/the_preparer_of_a_reconciliation_cannot_post_it
    """
    w = canonical_world(api, "recon_balanced")

    validate_error(
        api.post_drop_reconciliation(w.reconciliation_id, FINANCE_PREPARER_HEADERS),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    posted = validate_success(
        api.post_drop_reconciliation(w.reconciliation_id, FINANCE_POSTER_HEADERS)
    )
    assert posted["status"] == "POSTED"
    assert posted["prepared_by_user_id"] == FINANCE_PREPARER_USER_ID
    assert posted["posted_by_user_id"] == FINANCE_POSTER_USER_ID


def test_a_second_reconciliation_draft_supersedes_and_voids_the_first(api):
    """PRD §3.9: "Drafting first voids any existing reconciliation on the same drop
    run whose status is `BALANCED` or `VARIANCE_HELD`, moving it to `VOID`;
    superseding is a normal operation, which is exactly why the drop run's `version`
    is the only guard against a caller working from a stale picture."
    PRD §3.9: "The new draft records `prepared_by_user_id` from the acting
    `X-User-ID`, leaves `posted_by_user_id` and `posted_at` null, and computes six
    figures:"

    Design: Corner/cross_cutting_complexity_layers/a_second_reconciliation_draft_supersedes_and_voids_the_first
    """
    w = canonical_world(api, "recon_drafted")
    first_id = w.reconciliation_id

    second = validate_success(
        api.create_drop_reconciliation(
            create_drop_reconciliation_payload(
                w.drop_run_id, drop_run_version(api, w, w.drop_run_id)
            ),
            FINANCE_SECOND_PREPARER_HEADERS,
        ),
        201,
    )

    assert (
        validate_success(api.get_drop_reconciliation(first_id, FINANCE))["status"] == "VOID"
    )
    assert second["prepared_by_user_id"] == FINANCE_SECOND_PREPARER_USER_ID
    assert second["posted_by_user_id"] is None

    _, meta = validate_paginated(
        api.list_drop_reconciliations(FINANCE, params={"drop_run_id": w.drop_run_id})
    )
    assert meta["total_count"] == 2


def test_reconciling_a_cycle_with_an_unposted_drop_returns_incomplete(api):
    """PRD §3.9: "A finance officer or administrator reconciles a `DELIVERED`
    cycle, moving it `DELIVERED → RECONCILED`, but only once every drop run on it with
    status `SETTLED` carries a reconciliation with status `POSTED`; otherwise the
    attempt is refused with `ERR_DROP_RECONCILIATION_INCOMPLETE`."

    Design: Corner/validations/reconciling_a_cycle_with_an_unposted_drop_returns_incomplete
    """
    w = canonical_world(api, "recon_balanced")

    validate_error(
        api.reconcile_cycle(w.cycle_id, FINANCE),
        ApiErrorId.ERR_DROP_RECONCILIATION_INCOMPLETE.value,
    )

    assert validate_success(api.get_cycle(w.cycle_id, ADMIN))["status"] == "DELIVERED"
    assert (
        validate_success(api.get_drop_reconciliation(w.reconciliation_id, FINANCE))["status"]
        == "BALANCED"
    )


def test_a_closed_cycle_refuses_every_further_transition(api):
    """PRD §3.5: "Once a cycle has reached `RECONCILED`, a club administrator closes
    it: every member order with status `DELIVERED` moves `DELIVERED → CLOSED`, and the
    global write gate at rung 9 activates, so that from then on every mutating request
    whose target resolves to this cycle fails with `ERR_CYCLE_CLOSED` before any other
    business rule is even considered."

    Design: Corner/state_machines/a_closed_cycle_refuses_every_further_transition
    """
    w = canonical_world(api, "cycle_closed")

    body = validate_error(
        api.cancel_cycle(w.cycle_id, ADMIN), ApiErrorId.ERR_CYCLE_CLOSED.value
    )
    assert body["error_id"] != ApiErrorId.ERR_INVALID_CYCLE_STATE.value

    assert validate_success(api.get_cycle(w.cycle_id, ADMIN))["status"] == "CLOSED"
    assert validate_success(api.get_member_order(w.order_mara, ADMIN))["status"] == "CLOSED"
    assert validate_success(api.get_member_order(w.order_ben, ADMIN))["status"] == "CLOSED"


# -------------------------------------------------- the global write gate ---
def test_closed_cycle_gate_beats_the_refund_ceiling_check(api):
    """PRD §2.9: "**Rung 9 — GLOBAL WRITE GATE.** The cycle that the target
    resource resolves to does not have status `CLOSED`. The target resolves to a cycle
    directly for a cycle action, and indirectly through a route run, drop run, member
    order, order line, case aggregate, receipt line, substitution offer, pallet,
    payment, drop reconciliation, commission accrual or volunteer shift. This rung
    pre-empts every rung from 10 downwards, including all state, ownership,
    concurrency and fiscal checks."
    PRD §2.9: "**Rung 53** — `amount_cents` is at least 1 and at most the order's
    `captured_cents` less its `refunded_cents`. Applies to refunding a member order.
    Failure: `ERR_REFUND_EXCEEDS_CAPTURE`, HTTP 422."

    Design: Difficulty/priority_pair_validation_conflict/closed_cycle_gate_beats_the_refund_ceiling_check
    """
    w = canonical_world(api, "cycle_closed")

    body = validate_error(
        api.refund_member_order(w.order_mara, refund_payload(999999, "CARD"), FINANCE),
        ApiErrorId.ERR_CYCLE_CLOSED.value,
    )
    assert body["error_id"] != ApiErrorId.ERR_REFUND_EXCEEDS_CAPTURE.value
    assert body["error_id"] != ApiErrorId.ERR_RECONCILIATION_POSTED.value

    order = validate_success(api.get_member_order(w.order_mara, FINANCE))
    assert order["refunded_cents"] == 0
    assert order["payment_status"] == "CAPTURED"


def test_closed_cycle_gate_beats_the_posted_ledger_gate_and_the_concurrency_rung(api):
    """PRD §2.9: "**Rung 9 — GLOBAL WRITE GATE.** The cycle that the target
    resource resolves to does not have status `CLOSED`. The target resolves to a cycle
    directly for a cycle action, and indirectly through a route run, drop run, member
    order, order line, case aggregate, receipt line, substitution offer, pallet,
    payment, drop reconciliation, commission accrual or volunteer shift. This rung
    pre-empts every rung from 10 downwards, including all state, ownership,
    concurrency and fiscal checks."
    PRD §2.9: "**Rung 12 — POSTED LEDGER GATE.** The drop run in scope has no drop
    reconciliation with status `POSTED`. It pre-empts the whole money family below it.
    Applies to refunding a member order, recording a receipt line, drafting a drop
    reconciliation, resolving a held variance, and verifying a volunteer shift.
    Failure: `ERR_RECONCILIATION_POSTED`, HTTP 409."

    Design: Difficulty/priority_pair_validation_conflict/closed_cycle_gate_beats_the_refund_ceiling_check
    """
    w = canonical_world(api, "cycle_closed")

    body = validate_error(
        api.create_drop_reconciliation(
            create_drop_reconciliation_payload(w.drop_run_id, 1),
            FINANCE_PREPARER_HEADERS,
        ),
        ApiErrorId.ERR_CYCLE_CLOSED.value,
    )
    assert body["error_id"] != ApiErrorId.ERR_RECONCILIATION_POSTED.value
    assert body["error_id"] != ApiErrorId.ERR_STALE_VERSION.value

    _, meta = validate_paginated(
        api.list_drop_reconciliations(FINANCE, params={"drop_run_id": w.drop_run_id})
    )
    assert meta["total_count"] == 1, "no further draft may be created on a closed cycle"
