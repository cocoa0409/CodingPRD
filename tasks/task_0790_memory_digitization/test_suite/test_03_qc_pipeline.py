"""Quality-control pipeline: the QC_FAIL -> SCANNING revision loop, the
attempt counter, and the rescan attempt cap."""
from test_helpers import (
    ApiErrorId, validate_error, validate_paginated, TEST_USERS,
    rescan_item, get_item_admin,
    setup_item_qc_failed,
)


# ===========================================================================
# non_linear_state_machine / mediaitem_qc_revision_cycle
# ===========================================================================
def test_rescan_returns_failed_item_to_scanning(api):
    """PRD §3.5: "Rescanning is permitted only when the item's `status` is
    `QC_FAIL` and its `qc_attempts` is below the maximum of 3 attempts; it
    returns the item from `QC_FAIL` to `SCANNING` so it can be scanned and
    reviewed again."

    After one failing review (qc_attempts 1), a rescan cycles the item back to
    SCANNING while the attempt count is preserved.

    Design: Difficulty/non_linear_state_machine/mediaitem_qc_revision_cycle
    """
    base = setup_item_qc_failed(api, times=1, customer_email="qc-cyc1@x.com")
    item = get_item_admin(api, base["item_id"])
    assert item["status"] == "QC_FAIL" and item["qc_attempts"] == 1, item
    rescanned = rescan_item(api, base["item_id"])
    assert rescanned["status"] == "SCANNING", rescanned
    assert get_item_admin(api, base["item_id"])["qc_attempts"] == 1


def test_failing_review_lands_item_in_qc_fail_with_attempt_recorded(api):
    """PRD §3.5: "A `FAIL` always lands the item in `QC_FAIL`, regardless of how
    many attempts remain."
    PRD §3.5: "That review carries its `media_item_id`, the `decision`, the
    reviewer's `notes`, and an `attempt_number` equal to the item's
    `qc_attempts` after the increment (the 1-based ordinal of this review)."

    The first failing review leaves the item at QC_FAIL (qc_attempts 1) and
    writes a QCReview with attempt_number 1 and decision FAIL.

    Design: Difficulty/non_linear_state_machine/mediaitem_qc_revision_cycle
    """
    base = setup_item_qc_failed(api, times=1, customer_email="qc-cyc2@x.com")
    item = get_item_admin(api, base["item_id"])
    assert item["status"] == "QC_FAIL", item
    assert item["qc_attempts"] == 1, item
    reviews, _meta = validate_paginated(
        api.list_qc_reviews(base["item_id"], TEST_USERS["lab_headers"])
    )
    assert len(reviews) == 1, reviews
    assert reviews[0]["decision"] == "FAIL", reviews[0]
    assert reviews[0]["attempt_number"] == 1, reviews[0]


# ===========================================================================
# state_machines / rescan_at_max_attempts_returns_qc_attempts_exceeded (corner)
# ===========================================================================
def test_rescan_at_max_attempts_rejected(api):
    """PRD §3.5: "Once an item has accumulated 3 QC attempts, a further rescan is
    refused with `ERR_QC_ATTEMPTS_EXCEEDED` (HTTP 409) and the item remains in
    `QC_FAIL` — the attempt cap, not an automatic write-off, enforces the limit,
    and such an item is resolved later through a lost-and-damage claim."

    After three failing reviews (qc_attempts 3, status QC_FAIL) a rescan is
    refused.

    Design: Corner/state_machines/rescan_at_max_attempts_returns_qc_attempts_exceeded
    """
    base = setup_item_qc_failed(api, times=3, customer_email="qc-max@x.com")
    item = get_item_admin(api, base["item_id"])
    assert item["qc_attempts"] == 3 and item["status"] == "QC_FAIL", item
    resp = api.rescan(base["item_id"], TEST_USERS["lab_headers"])
    validate_error(resp, ApiErrorId.ERR_QC_ATTEMPTS_EXCEEDED)
    assert get_item_admin(api, base["item_id"])["qc_attempts"] == 3
