"""Direct payments, the append-only ledger, and the payment waterfall."""
import pytest

from test_helpers import (
    ST,
    TEST_USERS,
    ApiErrorId,
    assert_ledger_entry,
    create_member_payload,
    create_payment_payload,
    get_member,
    get_success_data,
    make_assessment_run,
    make_member,
    make_member_headers,
    make_payment,
    run_period,
    set_clock,
    setup_flat_local_with_journeyman,
    validate_error,
    validate_success,
)


def test_ledger_entry_system_generated_fields(api):
    """PRD section on money and the ledger: "a signed `amount_cents` in which
    charges are positive and credits are negative", and the payment workflow:
    "A successful payment posts a `DIRECT_PAYMENT` credit of `amount_cents`
    against the current clock period".

    Design: Corner/entities/ledger_entry_system_generated_fields
    """
    local, cls = setup_flat_local_with_journeyman()
    member = make_member(local["id"], cls["id"], full_name="Ledger Lou", member_number="M-001")
    run_period(local["id"], "2026-05")
    run_period(local["id"], "2026-06")
    set_clock("2026-08-01T00:00:00Z")
    resp = api.create_payment(member["id"], create_payment_payload(4000), make_member_headers(member["id"]))
    entry = validate_success(resp, 201)
    assert_ledger_entry(entry)
    assert entry["entry_type"] == "DIRECT_PAYMENT", "entry type is system-assigned"
    assert entry["amount_cents"] == -4000, "credits carry a negative signed amount"
    assert entry["period"] == "2026-08", "posted against the current clock period"
    assert entry["member_id"] == member["id"]


def test_payment_zero_amount_rejected(api):
    """PRD section on the member ledger: "The amount must be positive; a zero
    or negative amount is rejected with `ERR_PAYMENT_INVALID_AMOUNT`."

    Design: Corner/errors/payment_zero_amount_rejected
    """
    local, cls = setup_flat_local_with_journeyman()
    member = make_member(local["id"], cls["id"], full_name="Zero Zoe", member_number="M-001")
    set_clock("2026-08-01T00:00:00Z")
    resp = api.create_payment(member["id"], create_payment_payload(0), make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_PAYMENT_INVALID_AMOUNT)


def test_payment_waterfall_oldest_period_first(api):
    """PRD section on the member ledger: "each credit entry fills the earliest
    open bucket until the credit is exhausted, and each charge entry opens or
    increases its own bucket", with assessments "ordered by `period` ascending
    with ties broken by `created_at` ascending". A 7000 credit against two
    5000 periods fills 2026-05 fully and leaves 2000 on 2026-06.

    Design: Corner/calculations/payment_waterfall_oldest_period_first
    """
    local, cls = setup_flat_local_with_journeyman()
    member = make_member(local["id"], cls["id"], full_name="Falls Fred", member_number="M-001")
    run_period(local["id"], "2026-05")
    run_period(local["id"], "2026-06")
    make_payment(member["id"], 7000)
    a05 = get_success_data(api.list_member_assessments(member["id"], ST, params={"period": "2026-05"}))
    a06 = get_success_data(api.list_member_assessments(member["id"], ST, params={"period": "2026-06"}))
    assert len(a05) == 1 and len(a06) == 1
    assert a05[0]["assessed_cents"] == 5000 and a05[0]["paid_cents"] == 5000, (
        "oldest period bucket filled first"
    )
    assert a06[0]["assessed_cents"] == 5000 and a06[0]["paid_cents"] == 2000, (
        "remainder overflows into the next bucket"
    )
    member_after = get_member(member["id"])
    assert member_after["arrears_cents"] == 3000, "10000 charged minus 7000 paid"


def test_credit_balance_drained_by_next_charge(api):
    """PRD section on money and the ledger: "any credit balance is consumed
    immediately by later charges before arrears are allowed to grow again."
    A 1000 overpayment parks as credit; the next 5000 charge drains it,
    leaving arrears 4000.

    Design: Corner/cross_cutting_layers/credit_balance_drained_by_next_charge
    """
    local, cls = setup_flat_local_with_journeyman()
    member = make_member(local["id"], cls["id"], full_name="Credit Cathy", member_number="M-001")
    set_clock("2026-08-01T00:00:00Z")
    make_payment(member["id"], 1000)
    before = get_member(member["id"])
    assert before["credit_balance_cents"] == 1000 and before["arrears_cents"] == 0
    make_assessment_run(local["id"], "2026-08")
    after = get_member(member["id"])
    assert after["credit_balance_cents"] == 0, "stored credit drained by the new charge"
    assert after["arrears_cents"] == 4000, "5000 charge minus the 1000 stored credit"


def test_immediate_read_after_write_consistency(api):
    """PRD section on money and the ledger: "Because both fields are recomputed
    from the full entry stream on every posting and every read that needs them,
    they are always mutually consistent". A 2000 payment against a 5000 charge
    reads back as arrears 3000 in the immediately following read.

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    local, cls = setup_flat_local_with_journeyman()
    member = make_member(local["id"], cls["id"], full_name="Sync Sandy", member_number="M-001")
    set_clock("2026-08-01T00:00:00Z")
    make_assessment_run(local["id"], "2026-08")
    make_payment(member["id"], 2000)
    after = get_member(member["id"])
    assert after["arrears_cents"] == 3000, "write is visible in the very next read"


def test_member_version_increments_on_mutation(api):
    """PRD section on common properties: "The `version` field is an integer
    that starts at 1 at creation and increments by one on every mutation of
    the resource, including mutations driven by cascades originating on other
    resources." Registration yields 1; an assessment run ("the `version` of
    every assessed or finalized member increments") and a payment ("increments
    the member's `version`") raise it to exactly 3.

    Design: Corner/cross_cutting_layers/member_version_increments_on_mutation
    """
    local, cls = setup_flat_local_with_journeyman()
    resp = api.create_member(
        create_member_payload(local["id"], cls["id"], full_name="Vic Version", member_number="M-001"),
        TEST_USERS["office_clerk_headers"],
    )
    member = validate_success(resp, 201)
    assert member["version"] == 1
    set_clock("2026-08-01T00:00:00Z")
    make_assessment_run(local["id"], "2026-08")
    make_payment(member["id"], 1000)
    after = get_member(member["id"])
    assert after["version"] == 3, "run + payment = two mutations, each +1"


def test_member_cannot_pay_for_other_member(api):
    """PRD section on roles: "A `Member` caller may therefore record a payment,
    withdraw, file an objector case, initiate a transfer, appeal an issued
    rebate, or cancel a transfer only for the member whose `id` matches their
    `X-User-ID`; acting on another member's resources is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/member_cannot_pay_for_other_member
    """
    local, cls = setup_flat_local_with_journeyman()
    m1 = make_member(local["id"], cls["id"], full_name="Owner One", member_number="M-001")
    m2 = make_member(local["id"], cls["id"], full_name="Other Two", member_number="M-002")
    set_clock("2026-08-01T00:00:00Z")
    resp = api.create_payment(m1["id"], create_payment_payload(1000), make_member_headers(m2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)
