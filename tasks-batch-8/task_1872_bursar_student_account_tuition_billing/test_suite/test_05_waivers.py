"""Waiver/scholarship lifecycle, eligibility, and OCC claims (PRD §3.4, §2.8)."""
from test_helpers import (
    ApiErrorId,
    account_version,
    award_waiver,
    get_success_data,
    make_payment,
    post_waiver,
    read_account,
    read_ledger,
    setup_account_with_enrollment,
    validate_error,
    validate_success,
)


def test_waiver_revoke_from_awarded_posts_nothing(api, bursar_staff_headers):
    """PRD §3.4: "Revoking an `AWARDED` waiver simply moves it to terminal
    `REVOKED` — nothing was ever posted, so no ledger entry is written."

    Design: Corner/state_machines/waiver_revoke_from_awarded_posts_nothing
    """
    ctx = setup_account_with_enrollment(credit_hours=12, external_ref="S-WAV")
    acc = ctx["account_id"]
    waiver = award_waiver(acc, kind="WAIVER", awarded_cents=50000)

    revoked = validate_success(
        api.revoke_waiver(waiver["id"], bursar_staff_headers), 200
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["posted_cents"] == 0

    account = read_account(acc)
    assert account["balance_cents"] == 435000
    assert account["waivers_total_cents"] == 0
    ledger = read_ledger(acc)
    assert not any(
        e["entry_type"] in ("WAIVER", "WAIVER_REVERSAL") for e in ledger
    ), "revoking an AWARDED waiver must not touch the ledger"


def test_waiver_state_and_eligibility_errors(api, bursar_staff_headers):
    """PRD §3.4: "Posting requires the waiver still `AWARDED` — otherwise
    `ERR_WAIVER_STATE_INVALID` (HTTP 409) — and requires at least some eligible
    open charge amount, failing with `ERR_WAIVER_NOTHING_ELIGIBLE` (HTTP 422)
    when nothing the waiver's kind may offset remains open."

    Design: Corner/errors/waiver_state_and_eligibility_errors
    """
    ctx = setup_account_with_enrollment(credit_hours=1, external_ref="S-WER")
    acc = ctx["account_id"]
    # W1 posts 10000 of scholarship against the 50000 assessment.
    w1 = award_waiver(acc, kind="SCHOLARSHIP", awarded_cents=10000)
    post_waiver(w1["id"], acc)
    # A 40000 payment settles the remaining open charges; balance reaches 0.
    make_payment(acc, 40000)
    # W2 is fresh (AWARDED) but nothing eligible remains open.
    w2 = award_waiver(acc, kind="WAIVER", awarded_cents=5000)
    current_version = account_version(acc)

    res = api.post_waiver(
        w1["id"], {"expected_account_version": current_version},
        bursar_staff_headers,
    )
    validate_error(res, ApiErrorId.ERR_WAIVER_STATE_INVALID, expected_status=409)

    res = api.post_waiver(
        w2["id"], {"expected_account_version": current_version},
        bursar_staff_headers,
    )
    validate_error(res, ApiErrorId.ERR_WAIVER_NOTHING_ELIGIBLE, expected_status=422)


def test_waiver_post_with_stale_version_rejected(api, bursar_staff_headers):
    """PRD §2.8: "posting an `AWARDED` waiver requires the same
    `expected_account_version` match; waiver posting is always legitimate
    business-wise while the waiver remains `AWARDED`, so it is the
    stale-version check — not any state precondition — that rejects a second
    posting made from an outdated account view", with rejection "rejected with
    `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/validations/waiver_post_with_stale_version_rejected
    """
    ctx = setup_account_with_enrollment(credit_hours=12, external_ref="S-STW")
    acc = ctx["account_id"]
    waiver = award_waiver(acc, kind="WAIVER", awarded_cents=50000)
    stale_version = account_version(acc)
    # An intervening payment advances the account version.
    make_payment(acc, 1000)

    res = api.post_waiver(
        waiver["id"], {"expected_account_version": stale_version},
        bursar_staff_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    waivers = get_success_data(api.list_account_waivers(acc, bursar_staff_headers))
    w = [w for w in waivers if w["id"] == waiver["id"]][0]
    assert w["status"] == "AWARDED", "rejected posting must not mutate the waiver"
    assert w["posted_cents"] == 0
