"""Publisher returns: returnable guard, credit snapshot at submit, accept vs
reject branches, stock conservation on reject, and OCC stale-version on submit."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    create_publisher_return_payload, create_title_payload,
    make_title, receive_stock,
    setup_draft_return, setup_submitted_return,
)

INVMGR = TEST_USERS["inventory_manager_headers"]


def test_submit_nonreturnable_title_rejected(api):
    """PRD §3.8: "A return submitted against a non-returnable title is rejected
    with `ERR_TITLE_NOT_RETURNABLE` (HTTP 422)".

    Design: Difficulty/cross_entity_state_dependency/publisher_return_submit_requires_returnable_title
    """
    ctx = setup_draft_return(stock_qty=5, return_qty=1, returnable=False,
                             list_price_cents=1000)
    pr = ctx["publisher_return"]
    resp = api.submit_publisher_return(
        pr["id"], {"expected_publisher_return_version": pr["version"]}, INVMGR
    )
    validate_error(resp, ApiErrorId.ERR_TITLE_NOT_RETURNABLE)


def test_submit_returnable_title_succeeds(api):
    """PRD §3.8: "A submit is allowed only when the return is `DRAFT`, only when
    the title is returnable (its `returnable` is true), and only when the title
    has at least `quantity` copies `AVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/publisher_return_submit_requires_returnable_title
    """
    ctx = setup_draft_return(stock_qty=5, return_qty=1, returnable=True,
                             list_price_cents=1000)
    pr = ctx["publisher_return"]
    submitted = validate_success(
        api.submit_publisher_return(
            pr["id"], {"expected_publisher_return_version": pr["version"]}, INVMGR)
    )
    assert submitted["state"] == "SUBMITTED"


def test_reject_restores_available_stock(api):
    """PRD §3.8: "**Rejecting** a submitted return moves it from `SUBMITTED` to
    `REJECTED` as the compensating branch: the return's reserved copies are
    released back to `AVAILABLE`, the `credit_total_cents` is zeroed out because no
    credit is realized on rejection, the title's `on_hand_qty` and `reserved_qty`
    are recomputed".

    Design: Difficulty/compensating_invariant/publisher_return_reject_restores_available_stock_conserved
    """
    ctx = setup_submitted_return(stock_qty=5, return_qty=2, list_price_cents=1000)
    title_id = ctx["title"]["id"]
    pr = ctx["publisher_return"]
    mid = validate_success(api.get_title(title_id, INVMGR))
    assert mid["on_hand_qty"] == 3, "submit reserves 2 of 5 -> on_hand 3"
    rejected = validate_success(api.reject_publisher_return(pr["id"], INVMGR))
    assert rejected["state"] == "REJECTED"
    final_title = validate_success(api.get_title(title_id, INVMGR))
    assert final_title["on_hand_qty"] == 5, \
        "reject releases reserved copies back to AVAILABLE -> on_hand returns to 5"


def test_reject_zeroes_credit_total(api):
    """PRD §3.8: "the `credit_total_cents` is zeroed out because no credit is
    realized on rejection".

    Design: Difficulty/compensating_invariant/publisher_return_reject_restores_available_stock_conserved
    """
    ctx = setup_submitted_return(stock_qty=5, return_qty=2, list_price_cents=1000)
    rejected = validate_success(
        api.reject_publisher_return(ctx["publisher_return"]["id"], INVMGR)
    )
    assert rejected["credit_total_cents"] == 0


def test_return_credit_snapshot_at_submit(api):
    """PRD §3.8: "The **return-credit** calculation snapshots the per-copy credit
    as the title's `list_price_cents` multiplied by a publisher credit rate of
    fifty hundredths, rounded half-up to whole cents, stored in `credit_unit_cents`;
    the `credit_total_cents` is that per-unit credit multiplied by the return's
    `quantity`."

    Design: Corner/calculations/return_credit_snapshot_at_submit
    """
    ctx = setup_draft_return(stock_qty=5, return_qty=2, returnable=True,
                             list_price_cents=1000)
    pr = ctx["publisher_return"]
    submitted = validate_success(
        api.submit_publisher_return(
            pr["id"], {"expected_publisher_return_version": pr["version"]}, INVMGR)
    )
    # credit_unit = round(1000*0.50)=500; credit_total = 500*2 = 1000.
    assert submitted["credit_unit_cents"] == 500
    assert submitted["credit_total_cents"] == 1000


def test_accept_removes_copies_permanently(api):
    """PRD §3.8: "**Accepting** a submitted return moves it from `SUBMITTED` to
    `ACCEPTED`: the return's reserved copies leave inventory permanently, flipping
    from `RESERVED` to `RETURNED_TO_PUBLISHER`, after which the title's
    `reserved_qty` is recomputed".

    Design: Corner/state_machines/publisher_return_accept_removes_copies_permanently
    """
    ctx = setup_submitted_return(stock_qty=5, return_qty=2, list_price_cents=1000)
    pr = ctx["publisher_return"]
    accepted = validate_success(api.accept_publisher_return(pr["id"], INVMGR))
    assert accepted["state"] == "ACCEPTED"
    title = validate_success(api.get_title(ctx["title"]["id"], INVMGR))
    assert title["on_hand_qty"] == 3
    assert title["reserved_qty"] == 0


def test_submit_stale_version_rejected(api):
    """PRD §2.10: "Submitting a publisher return requires the request body to
    carry `expected_publisher_return_version`, set to the client's last-observed
    `version` of that `PublisherReturn`. If another writer has advanced the
    return's `version` since the client read it ... the submit is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_submit_stale_version_returns_412
    """
    ctx = setup_draft_return(stock_qty=5, return_qty=1, returnable=True,
                             list_price_cents=1000)
    pr = ctx["publisher_return"]
    stale_version = pr["version"] - 1
    resp = api.submit_publisher_return(
        pr["id"], {"expected_publisher_return_version": stale_version}, INVMGR
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
