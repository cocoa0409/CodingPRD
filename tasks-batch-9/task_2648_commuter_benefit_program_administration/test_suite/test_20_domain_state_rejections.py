"""Domain-state rejections on the election, card-spend and substantiation paths.

Each test drives the service into one specific posture and then attempts the one
operation that posture forbids: amending an election whose money side is already
closed, filing while a repayment receivable is outstanding, electing a media
product withdrawn from the catalogue, swiping past the conserved benefit balance,
approving a claim whose document disagrees with the swipe, and reopening a swipe
that has already been audited to the loop bound.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    PROGRAM_ADMIN,
    assert_account_conservation,
    assert_ledger_matches_account,
    assert_ledger_sequence,
    assert_unchanged,
    factories,
    fixtures,
    make_compliance_reviewer_headers,
    make_order_desk_headers,
)
from test_helpers.api_errors import (
    ERR_CLAIM_AMOUNT_MISMATCH,
    ERR_ELECTION_ALREADY_FUNDED,
    ERR_INSUFFICIENT_BENEFIT_BALANCE,
    ERR_REOPEN_LIMIT_EXCEEDED,
    ERR_SUBSTANTIATION_HOLD_ACTIVE,
    ERR_TRANSIT_MEDIA_DISCONTINUED,
)
from test_helpers.constants import REGION_AUS


def test_01_amending_a_cancelled_election_is_closed_to_amendment(api):
    """PRD 2.7: "A `REVERSED`, `SETTLED` or `CANCELLED` election is closed to amendment and the employee
    must file a fresh election instead — `ERR_ELECTION_ALREADY_FUNDED` (HTTP 409)."
    PRD 3.3: "The election's `funding_status` must be `PENDING`, `HELD` or `FUNDED`; a `REVERSED`,
    `SETTLED` or `CANCELLED` election is closed to amendment and returns `ERR_ELECTION_ALREADY_FUNDED`."

    Design: Corner/errors/amending_a_cancelled_election_returns_election_already_funded
    """
    base = fixtures.make_program_with_participant(api, region_code=REGION_AUS)
    election = fixtures.make_election(
        api,
        base["employee"]["id"],
        base["window"]["id"],
        base["category"]["id"],
        base["account"]["id"],
        pretax_amount_cents=5000,
        posttax_amount_cents=0,
    )
    cancelled = validate_success(api.cancel_election(election["id"], PROGRAM_ADMIN))
    assert cancelled["funding_status"] == "CANCELLED", cancelled["funding_status"]

    # The window is still OPEN and the logical clock is still inside its cutoff, so the
    # only closed door is the election's own money posture.
    window = fixtures.read_window(api, base["window"]["id"])
    assert window["status"] == "OPEN", window["status"]

    before = fixtures.read_election(api, election["id"])
    response = api.patch_election(
        election["id"], {"pretax_amount_cents": 4000}, PROGRAM_ADMIN
    )
    validate_error(response, ERR_ELECTION_ALREADY_FUNDED)

    after = fixtures.read_election(api, election["id"])
    assert after["funding_status"] == "CANCELLED", after["funding_status"]
    assert after["change_count"] == 0, (
        f"a refused amendment must not count as a change, got {after['change_count']}"
    )
    assert_unchanged(before, after, "pretax_amount_cents", "change_count", "funding_status")


def test_02_substantiation_hold_blocks_filing_a_new_election(api):
    """PRD 3.3: "An employee whose `substantiation_hold` is true — meaning an unresolved repayment
    receivable is outstanding — may neither file nor amend an election, and is refused with
    `ERR_SUBSTANTIATION_HOLD_ACTIVE`."
    PRD 3.7: "`repayment_due_cents` on the employee increases by the credited amount,
    `substantiation_hold` is set to true exactly when `repayment_due_cents` is greater than zero, and
    `Employee.version` advances by 1."
    PRD 3.7: "every election of that employee whose `funding_status` is `PENDING` is driven
    `PENDING → HELD`."

    Design: Corner/errors/substantiation_hold_blocks_a_new_election_and_is_rejected
    """
    base = fixtures.make_denied_transaction(
        api,
        deny_user_id="rev-deny",
        amount_cents=3000,
        opening_rollover_cents=10000,
        pretax_amount_cents=5000,
    )
    assert base["transaction"]["substantiation_status"] == "INELIGIBLE", (
        base["transaction"]["substantiation_status"]
    )

    employee = fixtures.read_employee(api, base["employee"]["id"])
    assert employee["substantiation_hold"] is True, employee["substantiation_hold"]
    assert employee["repayment_due_cents"] == 3000, employee["repayment_due_cents"]
    assert fixtures.read_election(api, base["election"]["id"])["funding_status"] == "HELD"

    # 1000 cents is comfortably inside every limit the program declares; only the
    # outstanding receivable stands in the way.
    response = api.create_election(
        factories.election_payload(
            base["employee"]["id"],
            base["window"]["id"],
            base["category"]["id"],
            fixtures.current_account_version(api, base["account"]["id"]),
            pretax_amount_cents=1000,
            posttax_amount_cents=0,
        ),
        PROGRAM_ADMIN,
    )
    validate_error(response, ERR_SUBSTANTIATION_HOLD_ACTIVE)

    # The refused create superseded nothing: the held election is untouched.
    still_held = fixtures.read_election(api, base["election"]["id"])
    assert still_held["funding_status"] == "HELD", still_held["funding_status"]


def test_03_discontinued_catalogue_product_blocks_a_new_election(api):
    """PRD 3.3: "when a `transit_media_id` is named, that product must still be `ACTIVE` in the
    catalogue (otherwise `ERR_TRANSIT_MEDIA_DISCONTINUED`)"
    PRD 3.5: "Discontinuing one moves it `ACTIVE → DISCONTINUED`, which is terminal and blocks new
    elections and new media lines against it, but leaves every existing media order alone"

    Design: Corner/errors/discontinued_media_on_a_new_election_is_rejected
    """
    base = fixtures.make_program_with_participant(api, region_code=REGION_AUS)
    desk = make_order_desk_headers("desk-catalog")

    # The product's region and eligible category both match the electing employee and
    # the elected category, so regional eligibility cannot be the failing gate.
    media = fixtures.make_transit_media(
        api,
        desk_user_id="desk-catalog",
        sku="AUS-DC",
        media_type="PAPER_PASS",
        region_code=REGION_AUS,
        eligible_category_type="TRANSIT_PASS",
        unit_price_cents=3000,
    )
    assert media["status"] == "ACTIVE", media["status"]
    withdrawn = validate_success(api.discontinue_transit_media(media["id"], desk))
    assert withdrawn["status"] == "DISCONTINUED", withdrawn["status"]

    response = api.create_election(
        factories.election_payload(
            base["employee"]["id"],
            base["window"]["id"],
            base["category"]["id"],
            fixtures.current_account_version(api, base["account"]["id"]),
            pretax_amount_cents=3000,
            posttax_amount_cents=0,
            transit_media_id=media["id"],
            media_quantity=1,
        ),
        PROGRAM_ADMIN,
    )
    validate_error(response, ERR_TRANSIT_MEDIA_DISCONTINUED)

    filed, meta = validate_paginated(
        api.list_elections(PROGRAM_ADMIN, {"employee_id": base["employee"]["id"]})
    )
    assert filed == [], f"the refused create must persist no election, got {filed}"
    assert meta["total_count"] == 0, meta["total_count"]


def _thin_balance_participant(api, opening_rollover_cents=3000, pretax_amount_cents=3000):
    """An ACTIVE program whose single participant holds exactly one carried-in
    balance and one PENDING election in the OPEN window."""
    base = fixtures.make_program_with_participant(
        api,
        region_code=REGION_AUS,
        account_overrides={"opening_rollover_cents": opening_rollover_cents},
    )
    base["election"] = fixtures.make_election(
        api,
        base["employee"]["id"],
        base["window"]["id"],
        base["category"]["id"],
        base["account"]["id"],
        pretax_amount_cents=pretax_amount_cents,
        posttax_amount_cents=0,
    )
    return base


def test_04_swipe_above_available_balance_is_refused(api):
    """PRD 3.7: "Because benefit dollars cannot be overdrawn, a swipe whose merchant category is inside
    the permitted set is admitted only when its `amount_cents` is no greater than the benefit account's
    current `available_balance_cents`; a larger swipe is refused with
    `ERR_INSUFFICIENT_BENEFIT_BALANCE` (HTTP 402)."
    PRD 2.9: "Second, `available_balance_cents` equals the signed sum of `amount_cents` over every
    ledger entry whose `benefit_account_id` is this account"

    Design: Corner/errors/swipe_above_available_balance_is_rejected_with_payment_required
    """
    base = _thin_balance_participant(api)
    opened = fixtures.read_account(api, base["account"]["id"])
    assert opened["available_balance_cents"] == 3000, opened["available_balance_cents"]
    assert opened["ledger_entry_count"] == 1, opened["ledger_entry_count"]

    response = api.create_card_transaction(
        factories.card_transaction_payload(
            base["election"]["id"],
            amount_cents=5000,
            merchant_category_code=4111,
            merchant_name="Austin Metro Rail",
            transaction_at="2026-08-02T08:00:00Z",
        ),
        PROGRAM_ADMIN,
    )
    validate_error(response, ERR_INSUFFICIENT_BENEFIT_BALANCE)

    # The refused swipe posted nothing at all: no spend, no ledger row.
    after = fixtures.read_account(api, base["account"]["id"])
    assert after["available_balance_cents"] == 3000, after["available_balance_cents"]
    assert after["spent_cents"] == 0, after["spent_cents"]
    assert after["ledger_entry_count"] == 1, after["ledger_entry_count"]
    assert_account_conservation(after)
    assert_ledger_matches_account(after, fixtures.read_ledger(api, base["account"]["id"]))


def test_05_swipe_exactly_at_available_balance_is_posted(api):
    """PRD 3.7: "a swipe whose merchant category is inside the permitted set is admitted only when its
    `amount_cents` is no greater than the benefit account's current `available_balance_cents`"
    PRD 3.7: "and a larger swipe is created in `PENDING_DOCS` awaiting documentation. In both of those
    cases `posted_spend_cents` equals the full `amount_cents`."
    PRD 3.7: "one ledger entry is appended with `entry_type` `SPEND` and a negative `amount_cents` equal
    to the posted spend"

    Design: Corner/errors/swipe_above_available_balance_is_rejected_with_payment_required
    """
    base = _thin_balance_participant(api)

    swipe = validate_success(
        api.create_card_transaction(
            factories.card_transaction_payload(
                base["election"]["id"],
                amount_cents=3000,
                merchant_category_code=4111,
                merchant_name="Austin Metro Rail",
                transaction_at="2026-08-02T09:00:00Z",
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    assert swipe["substantiation_status"] == "PENDING_DOCS", swipe["substantiation_status"]
    assert swipe["posted_spend_cents"] == 3000, swipe["posted_spend_cents"]

    after = fixtures.read_account(api, base["account"]["id"])
    assert after["available_balance_cents"] == 0, after["available_balance_cents"]
    assert after["spent_cents"] == 3000, after["spent_cents"]
    assert after["ledger_entry_count"] == 2, after["ledger_entry_count"]
    assert_account_conservation(after)
    ledger = fixtures.read_ledger(api, base["account"]["id"])
    assert_ledger_sequence(
        ledger, [("ROLLOVER_IN", 3000, 3000), ("SPEND", -3000, 0)]
    )
    assert_ledger_matches_account(after, ledger)


def test_06_claim_amount_below_the_swipe_cannot_be_approved(api):
    """PRD 3.7: "A `ComplianceReviewer` approves a claim only when three things hold: the claim's
    `status` is `SUBMITTED`, the underlying transaction's `substantiation_status` is `PENDING_DOCS`, and
    the claim's `claimed_amount_cents` equals the transaction's `amount_cents` exactly."
    PRD 3.7: "An amount disagreement must be rejected rather than approved, and an approval attempt
    against a mismatched amount returns `ERR_CLAIM_AMOUNT_MISMATCH`."

    Design: Corner/errors/claim_amount_that_differs_from_the_swipe_cannot_be_approved
    """
    base = fixtures.make_submitted_claim(
        api,
        claimed_amount_cents=2500,
        doc_type="RECEIPT",
        amount_cents=3000,
        opening_rollover_cents=10000,
        pretax_amount_cents=5000,
    )
    assert base["transaction"]["substantiation_status"] == "PENDING_DOCS", (
        base["transaction"]["substantiation_status"]
    )
    assert base["transaction"]["posted_spend_cents"] == 3000, (
        base["transaction"]["posted_spend_cents"]
    )
    assert base["claim"]["status"] == "SUBMITTED", base["claim"]["status"]

    response = api.approve_substantiation_claim(
        base["claim"]["id"], make_compliance_reviewer_headers("rev-approve")
    )
    validate_error(response, ERR_CLAIM_AMOUNT_MISMATCH)

    # Neither side of the pair moved: the claim is still awaiting review and the swipe
    # is still awaiting documentation.
    claim_after = fixtures.read_claim(api, base["claim"]["id"])
    assert claim_after["status"] == "SUBMITTED", claim_after["status"]
    transaction_after = fixtures.read_transaction(api, base["transaction"]["id"])
    assert transaction_after["substantiation_status"] == "PENDING_DOCS", (
        transaction_after["substantiation_status"]
    )
    assert transaction_after["posted_spend_cents"] == 3000, (
        transaction_after["posted_spend_cents"]
    )


def test_07_claim_amount_equal_to_the_swipe_approves_and_moves_no_money(api):
    """PRD 3.7: "On approval the claim moves `SUBMITTED → APPROVED` with `reviewed_by_user_id` recording
    the acting `X-User-ID`, and the underlying swipe moves `PENDING_DOCS → SUBSTANTIATED` with
    `approved_by_user_id` recording that same acting `X-User-ID`."
    PRD 3.7: "Approval deliberately moves no money: `posted_spend_cents` and the benefit account are
    left exactly as they were, because the spend was already posted at ingestion."

    Design: Corner/errors/claim_amount_that_differs_from_the_swipe_cannot_be_approved
    """
    base = fixtures.make_submitted_claim(
        api,
        claimed_amount_cents=3000,
        doc_type="RECEIPT",
        amount_cents=3000,
        opening_rollover_cents=10000,
        pretax_amount_cents=5000,
    )

    approved = validate_success(
        api.approve_substantiation_claim(
            base["claim"]["id"], make_compliance_reviewer_headers("rev-approve")
        )
    )
    assert approved["status"] == "APPROVED", approved["status"]
    assert approved["reviewed_by_user_id"] == "rev-approve", (
        approved["reviewed_by_user_id"]
    )

    transaction_after = fixtures.read_transaction(api, base["transaction"]["id"])
    assert transaction_after["substantiation_status"] == "SUBSTANTIATED", (
        transaction_after["substantiation_status"]
    )
    assert transaction_after["approved_by_user_id"] == "rev-approve", (
        transaction_after["approved_by_user_id"]
    )
    assert transaction_after["posted_spend_cents"] == 3000, (
        transaction_after["posted_spend_cents"]
    )

    account = fixtures.read_account(api, base["account"]["id"])
    assert account["spent_cents"] == 3000, account["spent_cents"]
    assert account["available_balance_cents"] == 7000, account["available_balance_cents"]
    assert account["ledger_entry_count"] == 2, account["ledger_entry_count"]
    assert_account_conservation(account)
    assert_ledger_matches_account(account, fixtures.read_ledger(api, base["account"]["id"]))


def test_08_third_reopen_of_one_swipe_hits_the_audit_limit(api):
    """PRD 3.7: "Every reopen requires `reopen_count` to be strictly below the reopen allowance of 2, and
    a third attempt is refused with `ERR_REOPEN_LIMIT_EXCEEDED`."
    PRD 3.7: "Reopening from `AUTO_SUBSTANTIATED` or from `SUBSTANTIATED` additionally requires the
    acting `X-User-ID` to differ from the transaction's recorded `approved_by_user_id`: the reviewer who
    blessed a swipe may not be the reviewer who reopens it."
    PRD 3.7: "Reopening from either of those two postures does nothing but set `substantiation_status`
    to `PENDING_DOCS`, increment `reopen_count` by 1 and advance `CardTransaction.version` by 1 — no
    money moves, because none had moved on approval."

    Design: Corner/errors/third_reopen_of_one_swipe_is_rejected_at_the_audit_limit
    """
    base = fixtures.make_program_with_participant(
        api,
        region_code=REGION_AUS,
        account_overrides={"opening_rollover_cents": 10000},
    )
    election = fixtures.make_election(
        api,
        base["employee"]["id"],
        base["window"]["id"],
        base["category"]["id"],
        base["account"]["id"],
        pretax_amount_cents=5000,
        posttax_amount_cents=0,
    )
    swipe = validate_success(
        api.create_card_transaction(
            factories.card_transaction_payload(
                election["id"],
                amount_cents=2000,
                merchant_category_code=4111,
                merchant_name="Austin Metro Rail",
                transaction_at="2026-08-04T08:00:00Z",
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    assert swipe["substantiation_status"] == "AUTO_SUBSTANTIATED", (
        swipe["substantiation_status"]
    )
    assert swipe["reopen_count"] == 0, swipe["reopen_count"]

    # The auditor and the approver are deliberately different reviewers, because a
    # reopen out of a substantiated posture may not be requested by the reviewer whose
    # identifier is recorded on the swipe.
    auditor = make_compliance_reviewer_headers("rev-audit")
    approver = make_compliance_reviewer_headers("rev-approver")

    first = validate_success(
        api.reopen_card_transaction(swipe["id"], {"reason": "audit sample"}, auditor)
    )
    assert first["substantiation_status"] == "PENDING_DOCS", first["substantiation_status"]
    assert first["reopen_count"] == 1, first["reopen_count"]

    for round_index in (1, 2):
        claim = validate_success(
            api.create_substantiation_claim(
                factories.substantiation_claim_payload(swipe["id"], 2000),
                PROGRAM_ADMIN,
            ),
            expected_status=201,
        )
        blessed = validate_success(api.approve_substantiation_claim(claim["id"], approver))
        assert blessed["status"] == "APPROVED", blessed["status"]
        if round_index == 1:
            second = validate_success(
                api.reopen_card_transaction(
                    swipe["id"], {"reason": "audit sample"}, auditor
                )
            )
            assert second["substantiation_status"] == "PENDING_DOCS", (
                second["substantiation_status"]
            )
            assert second["reopen_count"] == 2, second["reopen_count"]

    # reopen_count now sits at the allowance, so the third attempt is refused.
    response = api.reopen_card_transaction(
        swipe["id"], {"reason": "audit sample"}, auditor
    )
    validate_error(response, ERR_REOPEN_LIMIT_EXCEEDED)

    final = fixtures.read_transaction(api, swipe["id"])
    assert final["substantiation_status"] == "SUBSTANTIATED", (
        final["substantiation_status"]
    )
    assert final["reopen_count"] == 2, final["reopen_count"]

    # Reopens out of a substantiated posture move no money.
    account = fixtures.read_account(api, base["account"]["id"])
    assert account["spent_cents"] == 2000, account["spent_cents"]
    assert account["available_balance_cents"] == 8000, account["available_balance_cents"]
    assert_account_conservation(account)
