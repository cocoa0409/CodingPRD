"""Optimistic concurrency on the four shared parents (PRD §2.7)."""

from test_helpers import (
    CMRA_OPERATOR,
    ApiErrorId,
    activate_box,
    box_version,
    check_payload,
    create_box,
    create_plan_tier,
    deposit_batch_version,
    forward_shipment_payload,
    log_and_match_flat,
    log_and_match_letter,
    log_check,
    lodge_disposition,
    make_box_holder_headers,
    open_deposit_batch,
    plan_change_payload,
    read_deposit_batch,
    read_mail_item,
    setup_releasable_box,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_plan_change_carrying_a_stale_box_version_is_rejected(api):
    """PRD §2.7: "`POST /boxes/{id}/plan-change` requires `expected_box_version`,
    carrying the client's last observed `version` of the mailbox."
    PRD §2.7: "If the value supplied does not equal the parent row's current `version`,
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_expected_box_version_on_plan_change
    """
    plus = create_plan_tier()
    business = create_plan_tier(
        tier_code="BUSINESS",
        name="Business",
        rank=3,
        monthly_fee_cents=9000,
        included_recipients=6,
        included_scan_pages=100,
        included_forwards=4,
        overage_scan_page_cents=20,
        overage_forward_cents=800,
        overage_storage_day_cents=25,
        overage_recipient_cents=400,
    )
    box = create_box("Z-7001", plus["id"], holder_name="Cy Stale", holder_email="cy@example.com")
    activated = activate_box(box["id"])
    holder = make_box_holder_headers(box["id"])

    stale = api.change_plan(
        box["id"],
        plan_change_payload(business["id"], activated["version"] - 1),
        holder,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)

    fresh = validate_success(
        api.change_plan(
            box["id"], plan_change_payload(business["id"], activated["version"]), holder
        )
    )
    assert fresh["plan_tier_id"] == business["id"]
    assert fresh["pending_plan_tier_id"] is None


def test_a_cheque_carrying_a_stale_batch_version_is_rejected(api):
    """PRD §2.7: "`POST /deposit-batches/{id}/checks` requires
    `expected_deposit_batch_version`, carrying the client's last observed `version` of
    the deposit batch."
    PRD §2.9 rung 13: "The supplied `expected_mail_item_version`, `expected_box_version`
    or `expected_deposit_batch_version` equals the parent's current `version`. Otherwise
    `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_expected_deposit_batch_version_on_check_add
    """
    ctx = setup_releasable_box("Z-7002", "Dot Batch", holder_email="dot@example.com")
    first_item = log_and_match_letter(ctx)
    second_item = log_and_match_letter(ctx)
    batch = open_deposit_batch(ctx["box_id"], "2026-05-01")
    observed = batch["version"]
    log_check(batch["id"], first_item["id"], "Dot Batch", 6000)

    stale = api.create_check_deposit(
        batch["id"],
        check_payload(second_item["id"], "Dot Batch", 4000, observed, True),
        CMRA_OPERATOR,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)

    fresh = validate_success(
        api.create_check_deposit(
            batch["id"],
            check_payload(
                second_item["id"], "Dot Batch", 4000, deposit_batch_version(batch["id"]), True
            ),
            CMRA_OPERATOR,
        ),
        201,
    )
    assert fresh["status"] == "MATCHED"

    reread = read_deposit_batch(batch["id"])
    assert reread["check_count"] == 2
    assert reread["received_amount_cents"] == 10000
    assert reread["held_amount_cents"] == 10000


def test_a_consolidation_carrying_a_stale_box_version_writes_nothing(api):
    """PRD §2.7: "`POST /boxes/{id}/forward-shipments` requires `expected_box_version`,
    carrying the client's last observed `version` of the mailbox."
    PRD §2.7: "If the value supplied does not equal the parent row's current `version`,
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_expected_box_version_on_forward_shipment_create
    """
    ctx = setup_releasable_box("Z-7003", "Eve Ship", holder_email="eve@example.com")
    item = log_and_match_flat(ctx)
    lodge_disposition(ctx, item["id"], "FORWARD")
    observed = box_version(ctx["box_id"])

    response = api.create_forward_shipment(
        ctx["box_id"],
        forward_shipment_payload("ECONOMY", "3 Stale Way", [item["id"]], observed - 1),
        ctx["holder_headers"],
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)

    _, meta = validate_paginated(
        api.list_box_forward_shipments(ctx["box_id"], CMRA_OPERATOR)
    )
    assert meta["total_count"] == 0
    assert read_mail_item(item["id"])["forward_shipment_id"] is None
    assert box_version(ctx["box_id"]) == observed
