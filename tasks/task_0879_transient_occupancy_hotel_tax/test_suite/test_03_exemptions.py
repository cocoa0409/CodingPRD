"""Exemption claims: long-term night boundary, verify/reject transitions, the
receipts partition invariant, and the over-claim guard on filing."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_exemption_claim, assert_receipts_partition,
    TEST_USERS, make_operator_headers,
    single_line, setup_operator_with_property,
    create_draft_return, create_exemption, verify_exemption, file_return,
)

ADMIN = TEST_USERS["taxadmin_headers"]


# ============================================================
# Difficulty: boundary_precision_check/exemption_30_night_inclusive_boundary
# ============================================================
def _draft_with_two_lt_claims(api):
    base = setup_operator_with_property(api, jur_overrides={"exemption_min_stay_nights": 30})
    op, prop = base["operator"], base["property"]
    ret = create_draft_return(api, op["id"], single_line(prop["id"], 1000000))
    ex30 = create_exemption(api, ret["id"], "LONG_TERM_30DAY", 100000, guest_ref="G-30", stay_nights=30)
    ex29 = create_exemption(api, ret["id"], "LONG_TERM_30DAY", 100000, guest_ref="G-29", stay_nights=29)
    return ex30, ex29


def test_stay_at_minimum_verifies(api):
    """PRD 3.5: "Verification requires that the parent return is not `SUPERSEDED`,
    and, for a `LONG_TERM_30DAY` claim, that `stay_nights` is at least the
    jurisdiction's `exemption_min_stay_nights`; a long-term claim below that minimum
    is rejected with `ERR_EXEMPTION_INELIGIBLE`."

    Design: Difficulty/boundary_precision_check/exemption_30_night_inclusive_boundary
    """
    ex30, _ = _draft_with_two_lt_claims(api)
    data = validate_success(api.verify_exemption(ex30["id"], ADMIN), 200)
    assert_exemption_claim(data)
    assert data["status"] == "VERIFIED"


def test_stay_below_minimum_rejected_and_stays_claimed(api):
    """PRD 3.5: "for a `LONG_TERM_30DAY` claim, that `stay_nights` is at least the
    jurisdiction's `exemption_min_stay_nights`; a long-term claim below that minimum
    is rejected with `ERR_EXEMPTION_INELIGIBLE`."

    Design: Difficulty/boundary_precision_check/exemption_30_night_inclusive_boundary
    """
    _, ex29 = _draft_with_two_lt_claims(api)
    resp = api.verify_exemption(ex29["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_EXEMPTION_INELIGIBLE.value)
    assert validate_success(api.get_exemption(ex29["id"], ADMIN), 200)["status"] == "CLAIMED"


# ============================================================
# Difficulty: compensating_invariant/receipts_partition_on_exemption_reject
# ============================================================
def _filed_with_verified_gov_exemption(api):
    base = setup_operator_with_property(api)
    op, prop = base["operator"], base["property"]
    ret = create_draft_return(api, op["id"], single_line(prop["id"], 1000000))
    ex = create_exemption(api, ret["id"], "GOVERNMENT", 300000, guest_ref="G-3")
    verify_exemption(api, ex["id"])
    ret = file_return(api, ret["id"], op["id"])
    return op, ret, ex


def test_reject_moves_exempt_to_taxable_partition_holds(api):
    """PRD 3.5: "the rejected amount moves out of the exempt bucket and into the
    taxable bucket, so `taxable_receipts_cents` increases by `amount_cents` and
    `exempt_receipts_cents` decreases by the same `amount_cents`, leaving
    `gross_receipts_cents` unchanged (the partition invariant holds)."

    Design: Difficulty/compensating_invariant/receipts_partition_on_exemption_reject
    """
    op, ret, ex = _filed_with_verified_gov_exemption(api)
    rejected = validate_success(api.reject_exemption(ex["id"], ADMIN), 200)
    assert rejected["status"] == "REJECTED"
    after = validate_success(api.get_return(ret["id"], ADMIN), 200)
    assert after["gross_receipts_cents"] == 1000000
    assert after["taxable_receipts_cents"] == 1000000
    assert after["exempt_receipts_cents"] == 0
    assert_receipts_partition(after)


def test_reject_recomputes_tax_due(api):
    """PRD 3.5: "The server then recomputes `tax_due_cents` and posts an `ADJUSTMENT`
    ledger entry for the resulting tax delta, cascading to the operator's balance."

    Design: Difficulty/compensating_invariant/receipts_partition_on_exemption_reject
    """
    op, ret, ex = _filed_with_verified_gov_exemption(api)
    api.reject_exemption(ex["id"], ADMIN)
    after = validate_success(api.get_return(ret["id"], ADMIN), 200)
    # Taxable back to 1,000,000 -> tax 120,000 (was 700,000 -> 84,000).
    assert after["tax_due_cents"] == 120000


# ---- Corner: validations/exemptions_exceeding_gross_rejected_on_file ----
def test_exemptions_exceeding_gross_rejected_on_file(api):
    """PRD 3.4: "the guard's real job is to reject an over-claimed exempt total that
    would drive the taxable base negative (the honored exemptions exceeding gross
    receipts), which is rejected with `ERR_RECEIPTS_MISMATCH`."

    Design: Corner/validations/exemptions_exceeding_gross_rejected_on_file
    """
    base = setup_operator_with_property(api)
    op, prop = base["operator"], base["property"]
    ret = create_draft_return(api, op["id"], single_line(prop["id"], 1000000))
    create_exemption(api, ret["id"], "GOVERNMENT", 1200000, guest_ref="G-1")
    resp = api.file_return(ret["id"], make_operator_headers(op["id"]))
    validate_error(resp, ApiErrorId.ERR_RECEIPTS_MISMATCH.value)
    assert validate_success(api.get_return(ret["id"], ADMIN), 200)["filing_status"] == "DRAFT"


# ---- Corner: state_machines/verify_after_reject_returns_invalid_state ----
def test_verify_after_reject_invalid_state(api):
    """PRD 3.5: "A `TaxAdmin` may instead reject a claim, moving it from either
    `CLAIMED` or `VERIFIED` to `REJECTED`, which is terminal."
    PRD 3.5: "A `TaxAdmin` verifies a claim, moving it from `CLAIMED` to `VERIFIED`."

    Design: Corner/state_machines/verify_after_reject_returns_invalid_state
    """
    base = setup_operator_with_property(api)
    op, prop = base["operator"], base["property"]
    ret = create_draft_return(api, op["id"], single_line(prop["id"], 1000000))
    ex = create_exemption(api, ret["id"], "GOVERNMENT", 100000, guest_ref="G-1")
    api.reject_exemption(ex["id"], ADMIN)
    resp = api.verify_exemption(ex["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert validate_success(api.get_exemption(ex["id"], ADMIN), 200)["status"] == "REJECTED"
