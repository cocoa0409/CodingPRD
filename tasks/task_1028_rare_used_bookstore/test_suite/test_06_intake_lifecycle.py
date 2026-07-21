"""Intake lot settlement and rejection cascade."""
from test_helpers import validate_success, validate_error, TEST_USERS
from test_helpers.fixtures import (
    make_appraised_book, make_graded_book, new_intake_lot,
)

MANAGER = TEST_USERS["manager_headers"]


def test_reject_lot_withdraws_books(api):
    """PRD §3.2: "Rejecting a lot moves it to `REJECTED` and drives a two-hop cascade:
    first, every book in the lot that is not already `SOLD` transitions to
    `WITHDRAWN`; second, for each such withdrawn book, every appraisal with that
    `book_item_id` still in `ISSUED` status is set to `VOIDED` and the book's
    `appraised_value_cents` is cleared to null."

    Design: Difficulty/transitive_cascade/intake_reject_depth2_book_withdrawn_appraisal_voided
    """
    ctx = make_appraised_book(condition_grade="GOOD", comp_median_cents=5000, title="Pomes Penyeach")
    lot = validate_success(api.reject_lot(ctx["lot"]["id"], MANAGER), 200)
    assert lot["status"] == "REJECTED"
    book = validate_success(api.get_book_item(ctx["book"]["id"], MANAGER), 200)
    assert book["status"] == "WITHDRAWN"


def test_reject_lot_voids_appraisal_and_clears_value(api):
    """PRD §3.2: "Rejecting a lot moves it to `REJECTED` and drives a two-hop cascade:
    first, every book in the lot that is not already `SOLD` transitions to
    `WITHDRAWN`; second, for each such withdrawn book, every appraisal with that
    `book_item_id` still in `ISSUED` status is set to `VOIDED` and the book's
    `appraised_value_cents` is cleared to null."

    Design: Difficulty/transitive_cascade/intake_reject_depth2_book_withdrawn_appraisal_voided
    """
    ctx = make_appraised_book(condition_grade="GOOD", comp_median_cents=5000, title="Pomes Penyeach")
    appraisal_id = ctx["appraisal"]["id"]
    validate_success(api.reject_lot(ctx["lot"]["id"], MANAGER), 200)
    book = validate_success(api.get_book_item(ctx["book"]["id"], MANAGER), 200)
    assert book["appraised_value_cents"] is None
    appraisals, _ = _get_appraisals(api, ctx["book"]["id"])
    match = [a for a in appraisals if a["id"] == appraisal_id]
    assert match and match[0]["status"] == "VOIDED"


def _get_appraisals(api, book_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_appraisals(book_id, MANAGER))


def test_settle_empty_lot_rejected(api):
    """PRD §3.2: "Settling a lot moves it to `SETTLED`; it requires the lot to hold at
    least one book (otherwise `ERR_EMPTY_LOT`) and every book whose `intake_lot_id` is
    this lot to be in `APPRAISED` status (otherwise `ERR_LOT_ITEMS_NOT_APPRAISED`)."

    Design: Corner/errors/settle_empty_lot_returns_409
    """
    lot = new_intake_lot(acquisition_channel="PURCHASE")
    res = api.settle_lot(lot["id"], MANAGER)
    validate_error(res, "ERR_EMPTY_LOT", expected_status=409)


def test_settle_lot_with_unappraised_item_rejected(api):
    """PRD §3.2: "Settling a lot moves it to `SETTLED`; it requires the lot to hold at
    least one book (otherwise `ERR_EMPTY_LOT`) and every book whose `intake_lot_id` is
    this lot to be in `APPRAISED` status (otherwise `ERR_LOT_ITEMS_NOT_APPRAISED`)."

    Design: Corner/errors/settle_lot_items_not_appraised_returns_409
    """
    ctx = make_graded_book(condition_grade="GOOD", comp_median_cents=2600, title="A Mother")
    res = api.settle_lot(ctx["lot"]["id"], MANAGER)
    validate_error(res, "ERR_LOT_ITEMS_NOT_APPRAISED", expected_status=409)
