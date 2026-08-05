"""Liens: the strict-inequality threshold boundary, the depth-4 clear-settles-and-
releases cascade, and the optimistic-concurrency check on the record endpoint."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_lien,
    TEST_USERS,
    setup_delinquent_with_return, create_remittance, get_operator,
)

ADMIN = TEST_USERS["taxadmin_headers"]


# ============================================================
# Difficulty: boundary_precision_check/lien_threshold_strictly_above
# ============================================================
def test_balance_exactly_at_threshold_rejected(api):
    """PRD 3.7: "then by a threshold: the operator's delinquent balance must strictly
    exceed the jurisdiction's `lien_threshold_cents`, or the request is rejected with
    `ERR_BELOW_LIEN_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/lien_threshold_strictly_above
    """
    # gross 4,166,667 * 12% -> 500,000 exactly == threshold.
    bundle = setup_delinquent_with_return(api, gross=4166667, lien_threshold_cents=500000)
    op = bundle["operator"]
    assert op["account_balance_cents"] == 500000
    resp = api.record_lien(op["id"], {"expected_operator_version": op["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_BELOW_LIEN_THRESHOLD.value)


def test_balance_one_above_threshold_records_snapshot(api):
    """PRD 3.7: "On success the lien snapshots the operator's current
    `account_balance_cents` into its own `amount_cents`, sets its `status` to
    `RECORDED`, stamps `recorded_at` from the logical clock, and increments the
    operator's `version` by exactly one."

    Design: Difficulty/boundary_precision_check/lien_threshold_strictly_above
    """
    # gross 4,166,675 * 12% -> 500,001 == threshold + 1.
    bundle = setup_delinquent_with_return(api, gross=4166675, lien_threshold_cents=500000)
    op = bundle["operator"]
    assert op["account_balance_cents"] == 500001
    data = validate_success(api.record_lien(op["id"], {"expected_operator_version": op["version"]}, ADMIN), 201)
    assert_lien(data)
    assert data["status"] == "RECORDED"
    assert data["amount_cents"] == 500001


# ============================================================
# Difficulty: transitive_cascade/remittance_clear_settles_and_releases_lien
# ============================================================
def _delinquent_with_lien_and_remittance(api):
    bundle = setup_delinquent_with_return(api, gross=5000000, lien_threshold_cents=500000)
    op, ret = bundle["operator"], bundle["return"]  # tax 600,000, balance 600,000, DELINQUENT
    lien = validate_success(
        api.record_lien(op["id"], {"expected_operator_version": op["version"]}, ADMIN), 201
    )
    rem = create_remittance(api, ret["id"], 600000)  # RECEIVED
    return op, ret, lien, rem


def test_clear_settles_balance_and_reactivates_operator(api):
    """PRD 3.6: "On clearing, the server posts a `REMITTANCE` ledger entry for the
    negative of the amount (a credit that reduces what the operator owes), which
    cascades to the balance and can return a `DELINQUENT` operator to `ACTIVE` with
    the attendant lien release".

    Design: Difficulty/transitive_cascade/remittance_clear_settles_and_releases_lien
    """
    op, ret, lien, rem = _delinquent_with_lien_and_remittance(api)
    validate_success(api.clear_remittance(rem["id"], ADMIN), 200)
    after_op = get_operator(api, op["id"])
    assert after_op["account_balance_cents"] == 0
    assert after_op["status"] == "ACTIVE"


def test_clear_releases_lien_and_marks_return_paid(api):
    """PRD 2.7: "A `DELINQUENT` operator whose balance returns to zero or below (after
    a cleared remittance, a paid refund, or an abatement) moves back to `ACTIVE`, and
    every `RECORDED` lien for that operator is cascaded to `RELEASED`."
    PRD 3.6: "if it reaches or exceeds `total_due_cents` the return is `PAID`."

    Design: Difficulty/transitive_cascade/remittance_clear_settles_and_releases_lien
    """
    op, ret, lien, rem = _delinquent_with_lien_and_remittance(api)
    api.clear_remittance(rem["id"], ADMIN)
    liens = validate_success(api.list_operator_liens(op["id"], ADMIN), 200)
    released = next(l for l in liens if l["id"] == lien["id"])
    assert released["status"] == "RELEASED"
    after_ret = validate_success(api.get_return(ret["id"], ADMIN), 200)
    assert after_ret["settlement_status"] == "PAID"


# ---- Corner: cross_cutting_complexity_layers/occ_stale_operator_version_on_lien_record ----
def test_stale_operator_version_on_lien_record_rejected(api):
    """PRD 2.8: "If that value does not match the operator's current `version` — for
    instance because an intervening cleared remittance posted a partial payment,
    lowering the balance while the operator remained `DELINQUENT` — the write is
    rejected with `ERR_STALE_OPERATOR_VERSION` (HTTP 412), even though the delinquency
    precondition still holds."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_operator_version_on_lien_record
    """
    bundle = setup_delinquent_with_return(api, gross=5000000, lien_threshold_cents=500000)
    op, ret = bundle["operator"], bundle["return"]
    stale_version = op["version"]
    # Intervening partial remittance bumps the operator version.
    rem = create_remittance(api, ret["id"], 50000)
    validate_success(api.clear_remittance(rem["id"], ADMIN), 200)
    resp = api.record_lien(op["id"], {"expected_operator_version": stale_version}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_OPERATOR_VERSION.value)
