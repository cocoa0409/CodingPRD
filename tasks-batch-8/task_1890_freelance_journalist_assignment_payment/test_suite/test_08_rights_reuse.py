"""Rights purchases: ONE_TIME reuse royalties, the ALL buyout uplift entering
the invoice fee basis, and reuse gating on rights kind."""
from test_helpers import (
    ApiErrorId,
    get_contributor,
    get_rights_purchase_for_assignment,
    get_success_data,
    make_finance_headers,
    setup_accepted_assignment,
    submit_invoice,
    validate_error,
    validate_success,
    verify_invoice,
)
from test_helpers import api_client as _api
from test_helpers.test_users import TEST_USERS

EDITOR = TEST_USERS["editor_headers"]


def test_one_time_reuse_accrues_royalty_and_first_rights_rejects(api):
    """PRD section 3.6: "The royalty is the assignment's `final_fee_cents`
    multiplied by the desk's `reuse_royalty_pct_num` (default 25) and divided
    by 100, floor-divided. Recording a reuse increments `reuse_count` by one,
    adds the royalty to `reuse_fee_cents_total`, and posts a
    `REUSE_ROYALTY_CREDIT` ledger entry immediately, which feeds the
    year-to-date gross aggregation."
    PRD section 3.6: "It is permitted only when `rights_kind` is `ONE_TIME`
    and the assignment is `ACCEPTED_FOR_PUBLICATION`; a reuse attempt against
    `FIRST` or `ALL` rights, a `REVERTED` purchase, or an assignment in any
    other editorial state is rejected with `ERR_RIGHTS_NOT_REUSABLE` (HTTP
    409)."

    Design: Corner/calculations/reuse_royalty_accumulates_and_rights_gating
    """
    _c_rob, _a_rob, accepted_rob = setup_accepted_assignment(
        legal_name="Reuse Rob", email="rob@x.com", pricing_mode="FLAT",
        flat_fee_cents=50000, rights_default="ONE_TIME")
    _c_fran, _a_fran, accepted_fran = setup_accepted_assignment(
        legal_name="First Fran", email="fran@x.com", pricing_mode="FLAT",
        flat_fee_cents=50000, rights_default="FIRST", bootstrap=False)
    rp_rob = get_rights_purchase_for_assignment(accepted_rob["id"])
    rp_fran = get_rights_purchase_for_assignment(accepted_fran["id"])
    assert rp_rob["rights_kind"] == "ONE_TIME"
    assert rp_fran["rights_kind"] == "FIRST"

    first = validate_success(_api.record_reuse(rp_rob["id"], EDITOR))
    assert first["reuse_count"] == 1
    assert first["reuse_fee_cents_total"] == 12500, (
        "floor(50000 * 25 / 100)")
    second = validate_success(_api.record_reuse(rp_rob["id"], EDITOR))
    assert second["reuse_count"] == 2
    assert second["reuse_fee_cents_total"] == 25000

    resp = _api.record_reuse(rp_fran["id"], EDITOR)
    validate_error(resp, ApiErrorId.ERR_RIGHTS_NOT_REUSABLE, 409)

    entries = get_success_data(
        _api.list_contributor_ledger_entries(
            _c_rob["id"], make_finance_headers("fin-1")))
    royalties = [e for e in entries
                 if e["entry_kind"] == "REUSE_ROYALTY_CREDIT"]
    assert sorted(e["amount_cents"] for e in royalties) == [12500, 12500]
    contributor = get_contributor(_c_rob["id"])
    assert contributor["ytd_gross_cents"] == 25000, (
        "royalties feed the year-to-date gross aggregation")


def test_all_rights_uplift_enters_invoice_fee_basis(api):
    """PRD section 3.6: "`buyout_uplift_cents` is the `final_fee_cents`
    multiplied by the desk's `all_rights_uplift_pct_num` (default 35) and
    divided by 100, floor-divided."
    PRD section 3.6: "when the assignment's rights are `ALL`, the invoice's
    `fee_claim_cents` must equal `final_fee_cents` plus
    `buyout_uplift_cents`, and invoice verification checks exactly that sum."

    Design: Corner/calculations/all_rights_uplift_invoice_basis
    """
    contributor, _agr, accepted = setup_accepted_assignment(
        legal_name="All Ali", email="ali@x.com", pricing_mode="FLAT",
        flat_fee_cents=100000, rights_default="ALL")
    assert accepted["final_fee_cents"] == 100000
    rights = get_rights_purchase_for_assignment(accepted["id"])
    assert rights["rights_kind"] == "ALL"
    assert rights["buyout_uplift_cents"] == 35000, (
        "floor(100000 * 35 / 100) recorded at acceptance")

    # Claiming the bare final fee omits the uplift and must fail.
    invoice = submit_invoice(accepted["id"], contributor["id"], 100000, 0)
    resp = _api.verify_invoice(invoice["id"], {"decision": "VERIFY"},
                               make_finance_headers("fin-1"))
    validate_error(resp, ApiErrorId.ERR_CLAIM_MISMATCH, 422)

    # Reject the mismatched invoice so the payment dimension reopens, then
    # the composed basis (final fee + uplift) verifies cleanly.
    verify_invoice(invoice["id"], "REJECT")
    correct = submit_invoice(accepted["id"], contributor["id"], 135000, 0)
    verified = verify_invoice(correct["id"], "VERIFY")
    assert verified["status"] == "VERIFIED"
    assert verified["fee_claim_cents"] == 135000
