"""Disposal request workflow: revision loop, from-state guards, terminal
lockdown, and type-conditional field validation."""
from test_helpers import (
    ACCT,
    CTRL,
    ApiErrorId,
    create_and_post_disposal,
    create_asset,
    create_class,
    create_disposal_request,
    create_in_service_asset,
    setup_asset_with_posted_runs,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_disposal_reject_resubmit_state_path(api):
    """PRD §3.5: "Rejection moves it from `REQUESTED` to `REJECTED`, optionally
    carrying a free-text `reason`. A rejected request is not the end: the
    `AssetAccountant` may resubmit it with corrected `proceeds_cents`,
    `effective_date`, or `transfer_to_cost_center` values, which replace the
    prior values and are re-validated against the same field rules; the disposal
    returns from `REJECTED` to `REQUESTED`, provided the asset is still
    `IN_SERVICE` or `FULLY_DEPRECIATED` (else `ERR_ALREADY_DISPOSED`)."
    PRD §3.5: "Approval moves the disposal from `REQUESTED` to `APPROVED` and
    records the approver's `X-User-ID` as `approved_by_user_id`"

    Design: Difficulty/non_linear_state_machine/disposal_reject_resubmit_revision_cycle
    """
    cls = create_class(tax_method="MACRS_7YR")
    asset, _runs = setup_asset_with_posted_runs(
        ["2026-01", "2026-02"], asset_class_id=cls["id"], asset_tag="A-300",
        description="Van", acquisition_cost_cents=600000,
        in_service_date="2026-01-05",
    )
    disposal = create_disposal_request(
        asset["id"], disposal_type="SALE", proceeds_cents=400000,
        effective_date="2026-03-20",
    )
    assert disposal["status"] == "REQUESTED"

    rejected = validate_success(
        api.reject_disposal(disposal["id"], {"reason": "price too low"}, CTRL),
        200,
    )
    assert rejected["status"] == "REJECTED"

    resubmitted = validate_success(
        api.resubmit_disposal(
            disposal["id"],
            {"proceeds_cents": 450000, "effective_date": "2026-03-20"},
            ACCT,
        ),
        200,
    )
    assert resubmitted["status"] == "REQUESTED"
    assert resubmitted["proceeds_cents"] == 450000

    approved = validate_success(api.approve_disposal(disposal["id"], CTRL), 200)
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "u_ctrl_1"

    posted = validate_success(api.post_disposal(disposal["id"], ACCT), 200)
    assert posted["status"] == "POSTED"


def test_resubmitted_proceeds_drive_final_gain_loss(api):
    """PRD §3.5: "the `AssetAccountant` may resubmit it with corrected
    `proceeds_cents`, `effective_date`, or `transfer_to_cost_center` values,
    which replace the prior values and are re-validated against the same field
    rules"
    PRD §3.5: "**Step two — book gain/loss:** `book_gain_loss_cents` is
    `proceeds_cents` minus the net book carrying amount, that is, minus
    (`acquisition_cost_cents` − `accumulated_book_cents` −
    `impairment_total_cents`)."

    Design: Difficulty/non_linear_state_machine/disposal_reject_resubmit_revision_cycle
    """
    cls = create_class(tax_method="MACRS_7YR")
    asset, _runs = setup_asset_with_posted_runs(
        ["2026-01", "2026-02"], asset_class_id=cls["id"], asset_tag="A-300",
        description="Van", acquisition_cost_cents=600000,
        in_service_date="2026-01-05",
    )
    disposal = create_disposal_request(
        asset["id"], disposal_type="SALE", proceeds_cents=400000,
        effective_date="2026-03-20",
    )
    validate_success(
        api.reject_disposal(disposal["id"], {"reason": "price too low"}, CTRL),
        200,
    )
    validate_success(
        api.resubmit_disposal(
            disposal["id"],
            {"proceeds_cents": 450000, "effective_date": "2026-03-20"},
            ACCT,
        ),
        200,
    )
    validate_success(api.approve_disposal(disposal["id"], CTRL), 200)

    posted = validate_success(api.post_disposal(disposal["id"], ACCT), 200)
    # Resubmitted proceeds 450000, not the original 400000, drive the result:
    # March final BOOK entry of 10000 applies (day 20 >= 15), so
    # 450000 - (600000 - 30000 - 0) = -120000.
    assert posted["book_gain_loss_cents"] == -120000

    after = validate_success(api.get_fixed_asset(asset["id"], ACCT), 200)
    assert after["status"] == "DISPOSED"


def test_disposal_request_on_draft_asset_rejected(api):
    """PRD §3.5: "The asset must be `IN_SERVICE` or `FULLY_DEPRECIATED`: a
    `DRAFT` asset yields `ERR_ASSET_NOT_IN_SERVICE` and a `DISPOSED` asset yields
    `ERR_ALREADY_DISPOSED`."

    Design: Difficulty/cross_entity_state_dependency/disposal_create_requires_asset_in_service
    """
    cls = create_class()
    asset = create_asset(
        cls["id"], asset_tag="A-950", description="Draft asset",
        acquisition_cost_cents=400000,
    )
    assert asset["status"] == "DRAFT"

    resp = api.create_disposal(
        {"asset_id": asset["id"], "disposal_type": "SALE",
         "proceeds_cents": 100000, "effective_date": "2026-03-01"},
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_ASSET_NOT_IN_SERVICE, 409)


def test_rejected_disposal_request_leaves_asset_draft(api):
    """PRD §3.5: "The asset must be `IN_SERVICE` or `FULLY_DEPRECIATED`: a
    `DRAFT` asset yields `ERR_ASSET_NOT_IN_SERVICE` and a `DISPOSED` asset yields
    `ERR_ALREADY_DISPOSED`."
    PRD §3.5: "Disposals can be listed and filtered by `asset_id` or `status`."

    Design: Difficulty/cross_entity_state_dependency/disposal_create_requires_asset_in_service
    """
    cls = create_class()
    asset = create_asset(
        cls["id"], asset_tag="A-950", description="Draft asset",
        acquisition_cost_cents=400000,
    )
    resp = api.create_disposal(
        {"asset_id": asset["id"], "disposal_type": "SALE",
         "proceeds_cents": 100000, "effective_date": "2026-03-01"},
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_ASSET_NOT_IN_SERVICE, 409)

    after = validate_success(api.get_fixed_asset(asset["id"], ACCT), 200)
    assert after["status"] == "DRAFT"
    rows, meta = validate_paginated(
        api.list_disposals(ACCT, params={"asset_id": asset["id"]})
    )
    assert meta["total_count"] == 0 and rows == [], "no Disposal row created"


def test_terminal_lockdown_disposed_asset(api):
    """PRD §3.2: "Placing an asset that is not `DRAFT` in service is rejected
    with `ERR_INVALID_STATE`."
    PRD §3.5: "The asset must be `IN_SERVICE` or `FULLY_DEPRECIATED`: a `DRAFT`
    asset yields `ERR_ASSET_NOT_IN_SERVICE` and a `DISPOSED` asset yields
    `ERR_ALREADY_DISPOSED`."

    Design: Corner/state_machines/terminal_lockdown_disposed_asset
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-022", description="Terminal asset",
        acquisition_cost_cents=500000,
    )
    posted = create_and_post_disposal(
        asset["id"], disposal_type="SCRAP", effective_date="2026-02-20",
    )
    assert posted["status"] == "POSTED"

    place = api.place_in_service(
        asset["id"], {"in_service_date": "2026-03-01"}, ACCT
    )
    validate_error(place, ApiErrorId.ERR_INVALID_STATE, 409)

    again = api.create_disposal(
        {"asset_id": asset["id"], "disposal_type": "SALE",
         "proceeds_cents": 1000, "effective_date": "2026-03-01"},
        ACCT,
    )
    validate_error(again, ApiErrorId.ERR_ALREADY_DISPOSED, 409)

    after = validate_success(api.get_fixed_asset(asset["id"], ACCT), 200)
    assert after["status"] == "DISPOSED"


def test_invalid_disposal_field_combinations_rejected(api):
    """PRD §3.5: "A `SALE` requires an explicit `proceeds_cents` of zero or
    more."
    PRD §3.5: "A `TRANSFER` is an inter-cost-center move: it requires
    `transfer_to_cost_center`, forbids it for the other two types, and demands
    `proceeds_cents` equal to zero."
    PRD §3.5: "the type-specific field combinations, as well as an
    `effective_date` earlier than the asset's `in_service_date`, are rejected
    with `ERR_INVALID_DISPOSAL_FIELDS` (HTTP 422)."

    Design: Corner/validations/invalid_disposal_field_combinations_rejected
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], in_service_date="2026-02-10", asset_tag="A-043",
        description="Disposal fields", acquisition_cost_cents=500000,
    )

    sale_missing_proceeds = api.create_disposal(
        {"asset_id": asset["id"], "disposal_type": "SALE",
         "effective_date": "2026-03-01"},
        ACCT,
    )
    validate_error(sale_missing_proceeds, ApiErrorId.ERR_INVALID_DISPOSAL_FIELDS,
                   422)

    transfer_with_proceeds_no_destination = api.create_disposal(
        {"asset_id": asset["id"], "disposal_type": "TRANSFER",
         "effective_date": "2026-03-01", "proceeds_cents": 5},
        ACCT,
    )
    validate_error(transfer_with_proceeds_no_destination,
                   ApiErrorId.ERR_INVALID_DISPOSAL_FIELDS, 422)

    predates_in_service = api.create_disposal(
        {"asset_id": asset["id"], "disposal_type": "SCRAP",
         "effective_date": "2026-01-15"},
        ACCT,
    )
    validate_error(predates_in_service, ApiErrorId.ERR_INVALID_DISPOSAL_FIELDS,
                   422)

    rows, meta = validate_paginated(
        api.list_disposals(ACCT, params={"asset_id": asset["id"]})
    )
    assert meta["total_count"] == 0 and rows == [], (
        "no Disposal rows persisted for the asset"
    )


def test_disposal_into_closed_period_rejected(api):
    """PRD §2.7: "The effective period must be **later than** the latest `POSTED`
    run period; this rule is checked when the disposal is requested and
    re-validated when the disposal is posted. A disposal whose effective period
    is on or before the latest posted period is rejected with
    `ERR_PERIOD_CLOSED` (HTTP 409)."

    Design: Corner/validations/disposal_into_closed_period_rejected
    """
    cls = create_class()
    asset, _runs = setup_asset_with_posted_runs(
        ["2026-01"], asset_class_id=cls["id"], asset_tag="A-045",
        description="Closed period", acquisition_cost_cents=500000,
    )
    resp = api.create_disposal(
        {"asset_id": asset["id"], "disposal_type": "SALE",
         "proceeds_cents": 100000, "effective_date": "2026-01-20"},
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_CLOSED, 409)

    rows, meta = validate_paginated(
        api.list_disposals(ACCT, params={"asset_id": asset["id"]})
    )
    assert meta["total_count"] == 0 and rows == [], "no Disposal persisted"
