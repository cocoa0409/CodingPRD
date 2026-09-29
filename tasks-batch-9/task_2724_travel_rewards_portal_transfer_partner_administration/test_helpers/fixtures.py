"""
Composite state builders that drive the system under test through its endpoints.

Nothing here touches a database. Every builder walks the declared HTTP surface,
so the state a test starts from is state the contract itself admits. The harness
restarts the server before each test, so each builder starts from an empty
database with the clock at its §2.4 start-up instant.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from . import factories as f
from .api_client import canonical_timestamp
from .test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    APPROVER_HEADERS,
    make_agency_headers,
    make_cardholder_headers,
)
from .types import PRODUCT_CORE

# ─── Instant arithmetic (§2.5) ────────────────────────────────────────

_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _parse(instant: str) -> datetime:
    return datetime.strptime(canonical_timestamp(instant), _FORMAT)


def _format(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def plus_days(instant: str, days: int) -> str:
    """"exact calendar-day addition ... applied to a UTC instant" (§2.5)."""
    return _format(_parse(instant) + timedelta(days=days))


def plus_hours(instant: str, hours: int) -> str:
    """"exact addition of hours to a UTC instant" (§2.5)."""
    return _format(_parse(instant) + timedelta(hours=hours))


def plus_millis(instant: str, millis: int) -> str:
    """The smallest observable step, for at-or-after boundary probes."""
    return _format(_parse(instant) + timedelta(milliseconds=millis))


# ─── The logical clock and the sweep ──────────────────────────────────


def set_clock(api, instant: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Move the logical clock to `instant`."""
    response = api.set_clock(f.clock_payload(instant), headers or ADMIN_HEADERS)
    return get_success_data(response)


def read_clock(api, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Read the clock's current `current_utc`."""
    return validate_success(api.get_clock(headers or ADMIN_HEADERS))


def ops_run(api, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Invoke the deterministic sweep and return its counter envelope."""
    return get_success_data(api.run_ops(headers or ADMIN_HEADERS))


# ─── Accounts ─────────────────────────────────────────────────────────


def new_account(
    api, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Enrol one card account and return the created row."""
    response = api.create_account(f.account_payload(**overrides), headers or ADMIN_HEADERS)
    return get_success_data(response, 201)


def account_holder(account: Dict[str, Any]) -> Dict[str, str]:
    """The `Cardholder` headers of an account row."""
    return make_cardholder_headers(account["id"])


def read_account(api, account_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Read one account row."""
    return validate_success(api.get_account(account_id, headers or ADMIN_HEADERS))


def account_version(api, account_id: str, headers: Optional[Dict] = None) -> int:
    """The account's current `version`, for `expected_account_version`."""
    return read_account(api, account_id, headers)["version"]


# ─── Merchant categories and purchases ────────────────────────────────


def ensure_mapping(
    api,
    headers: Optional[Dict] = None,
    mcc_code: str = "5999",
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Return the mapping row for `mcc_code`, creating it when the table has none.
    An `mcc_code` "must be globally unique across the mapping table", so a lookup
    by code returns at most one row.
    """
    headers = headers or ADMIN_HEADERS
    rows, _ = validate_paginated(
        api.list_merchant_categories(headers, {"mcc_code": mcc_code, "limit": 100})
    )
    if rows:
        return rows[0]
    return get_success_data(
        api.create_merchant_category(
            f.merchant_category_payload(mcc_code=mcc_code, **overrides), headers
        ),
        201,
    )


def post_purchase(
    api,
    account_id: str,
    amount_cents: int,
    headers: Optional[Dict] = None,
    mcc_code: str = "5999",
    posted_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Post one purchase and return the created row with its earning breakdown."""
    headers = headers or ADMIN_HEADERS
    payload = f.transaction_payload(
        account_id=account_id, mcc_code=mcc_code, amount_cents=amount_cents, **overrides
    )
    if posted_at is not None:
        payload["posted_at"] = posted_at
    return get_success_data(api.create_transaction(payload, headers), 201)


def fund_account(
    api,
    account_id: str,
    points: int,
    headers: Optional[Dict] = None,
    mcc_code: str = "5999",
    posted_at: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Give a `CORE` account exactly `points` points through one purchase.

    With a `base_multiplier` of 1.0 and the `CORE` earn multiplier of 1.0, §3.3
    makes `base_points` equal to the purchase's billable dollars, so a purchase of
    `points * 100` cents earns exactly `points` points. The builder asserts that,
    which fails loudly if it is ever pointed at a non-`CORE` account.
    """
    headers = headers or ADMIN_HEADERS
    ensure_mapping(api, headers, mcc_code=mcc_code, base_multiplier=1.0)
    row = post_purchase(
        api,
        account_id,
        points * 100,
        headers=headers,
        mcc_code=mcc_code,
        posted_at=posted_at,
    )
    assert row["total_points_earned"] == points, (
        f"fund_account expected {points} points, the purchase earned "
        f"{row['total_points_earned']}"
    )
    return row


def funded_account(
    api,
    points: int,
    headers: Optional[Dict] = None,
    card_product_code: str = PRODUCT_CORE,
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """A `CORE` account holding exactly `points` points, with its own headers."""
    headers = headers or ADMIN_HEADERS
    account = new_account(
        api, headers, card_product_code=card_product_code, **overrides
    )
    if points:
        fund_account(api, account["id"], points, headers=headers)
    return read_account(api, account["id"], headers), account_holder(account)


# ─── Agencies and offers ──────────────────────────────────────────────


def new_agency(api, headers: Optional[Dict] = None, **overrides: Any) -> Dict[str, Any]:
    """Onboard one travel agency partner and return the created row."""
    response = api.create_agency_partner(
        f.agency_payload(**overrides), headers or ADMIN_HEADERS
    )
    return get_success_data(response, 201)


def new_offer(
    api, agency_id: str, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Publish one itinerary to the portal as the owning agency."""
    headers = headers or make_agency_headers(agency_id)
    response = api.create_offer(
        f.offer_payload(agency_partner_id=agency_id, **overrides), headers
    )
    return get_success_data(response, 201)


def agency_with_offer(
    api,
    admin: Optional[Dict] = None,
    agency: Optional[Dict[str, Any]] = None,
    **offer_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, str]]:
    """An agency, one offer of that agency, and the agency's own headers."""
    admin = admin or ADMIN_HEADERS
    agency_kwargs = agency or {}
    agency_row = new_agency(api, admin, **agency_kwargs)
    supplier = make_agency_headers(agency_row["id"])
    offer = new_offer(api, agency_row["id"], supplier, **offer_overrides)
    return agency_row, offer, supplier


def read_offer(api, offer_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Read one offer row."""
    return validate_success(api.get_offer(offer_id, headers or ADMIN_HEADERS))


# ─── Redemption orders ────────────────────────────────────────────────


def book(
    api,
    offer: Dict[str, Any],
    account_id: str,
    cardholder: Dict[str, str],
    **overrides: Any,
) -> Dict[str, Any]:
    """Quote a `PORTAL_BOOKING` order against `offer` at its current version."""
    payload = f.book_payload(
        account_id=account_id,
        expected_offer_version=overrides.pop(
            "expected_offer_version", offer["version"]
        ),
        **overrides,
    )
    return get_success_data(api.book_offer(offer["id"], payload, cardholder), 201)


def statement_credit(
    api, account_id: str, cardholder: Dict[str, str], points_requested: int = 2500
) -> Dict[str, Any]:
    """Quote a `STATEMENT_CREDIT` order through the flat order collection."""
    payload = f.statement_credit_payload(
        account_id=account_id, points_requested=points_requested
    )
    return get_success_data(api.create_order(payload, cardholder), 201)


def confirm(api, order_id: str, cardholder: Dict[str, str]) -> Dict[str, Any]:
    """Confirm a quote, turning the reservation into a `REDEEM_DEBIT`."""
    return get_success_data(api.confirm_order(order_id, {}, cardholder))


def ticket(
    api, order_id: str, supplier: Dict[str, str], ticket_number: str = "TKT-0001"
) -> Dict[str, Any]:
    """Record the agency ticketing a confirmed portal booking."""
    return get_success_data(
        api.ticket_order(order_id, f.ticket_payload(ticket_number), supplier)
    )


def settle(
    api,
    order_id: str,
    invoice_amount_cents: int,
    headers: Optional[Dict] = None,
    settlement_adjustment_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """Settle the agency invoice and fill the final cost leg."""
    payload = f.settle_payload(
        invoice_amount_cents=invoice_amount_cents,
        settlement_adjustment_cents=settlement_adjustment_cents,
    )
    return get_success_data(api.settle_order(order_id, payload, headers or ADMIN_HEADERS))


def ticketed_order(
    api,
    points: int = 100000,
    admin: Optional[Dict] = None,
    offer_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    A whole portal booking walked to `TICKETED`: agency, offer, funded account,
    quote, confirmation and ticket. Returns every row a test may need to assert on.
    """
    admin = admin or ADMIN_HEADERS
    agency, offer, supplier = agency_with_offer(api, admin, **(offer_overrides or {}))
    account, cardholder = funded_account(api, points, admin)
    order = book(api, offer, account["id"], cardholder)
    confirm(api, order["id"], cardholder)
    order = ticket(api, order["id"], supplier)
    return {
        "agency": agency,
        "offer": offer,
        "supplier": supplier,
        "account": account,
        "cardholder": cardholder,
        "order": order,
    }


# ─── Partner agreements and promotions ────────────────────────────────


def draft_agreement(
    api, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Draft one transfer partner agreement and return the `DRAFT` row."""
    response = api.create_agreement(
        f.agreement_payload(**overrides), headers or ADMIN_HEADERS
    )
    return get_success_data(response, 201)


def active_agreement(
    api,
    admin: Optional[Dict] = None,
    approver: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Draft, submit and approve one agreement so transfers may name it.

    The submitter and the approver are deliberately different principals, because
    approval "requires that the acting `X-User-ID` differs from the stored
    `submitted_by_user_id`".
    """
    admin = admin or ADMIN_HEADERS
    approver = approver or APPROVER_HEADERS
    agreement = draft_agreement(api, admin, **overrides)
    get_success_data(api.submit_agreement(agreement["id"], {}, admin))
    return get_success_data(api.approve_agreement(agreement["id"], {}, approver))


def suspended_agreement(
    api,
    admin: Optional[Dict] = None,
    approver: Optional[Dict] = None,
    suspended_reason: str = "Partner renegotiation",
    **overrides: Any,
) -> Dict[str, Any]:
    """An agreement walked `ACTIVE` -> `SUSPENDED`."""
    admin = admin or ADMIN_HEADERS
    agreement = active_agreement(api, admin, approver, **overrides)
    return get_success_data(
        api.suspend_agreement(
            agreement["id"], f.offer_suspend_payload(suspended_reason), admin
        )
    )


def new_bonus_event(
    api, agreement_id: str, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Schedule one promotional transfer bonus on an active agreement."""
    response = api.create_bonus_event(
        f.bonus_event_payload(partner_agreement_id=agreement_id, **overrides),
        headers or ADMIN_HEADERS,
    )
    return get_success_data(response, 201)


# ─── Transfer requests ────────────────────────────────────────────────


def submit_transfer(
    api,
    account_id: str,
    agreement_id: str,
    points_out: int,
    cardholder: Dict[str, str],
    expected_account_version: Optional[int] = None,
    admin: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Submit one transfer, reading the account's current `version` when the caller
    does not pin one, since `expected_account_version` is non-optional.
    """
    version = (
        expected_account_version
        if expected_account_version is not None
        else account_version(api, account_id, admin or ADMIN_HEADERS)
    )
    payload = f.transfer_payload(
        account_id=account_id,
        partner_agreement_id=agreement_id,
        points_out=points_out,
        expected_account_version=version,
    )
    return get_success_data(api.create_transfer(payload, cardholder), 201)


def hold_transfer(
    api,
    transfer_id: str,
    analyst: Optional[Dict] = None,
    hold_reason: str = "MANUAL_REVIEW",
) -> Dict[str, Any]:
    """Place a fraud hold on a submitted or queued transfer."""
    return get_success_data(
        api.hold_transfer(
            transfer_id, f.hold_payload(hold_reason), analyst or ANALYST_HEADERS
        )
    )


def clear_screening(
    api, transfer_id: str, analyst: Optional[Dict] = None
) -> Dict[str, Any]:
    """Clear screening and queue the transfer for posting after the latency."""
    return get_success_data(
        api.clear_screening(transfer_id, {}, analyst or ANALYST_HEADERS)
    )


def queued_transfer(
    api,
    account_id: str,
    agreement_id: str,
    points_out: int,
    cardholder: Dict[str, str],
    analyst: Optional[Dict] = None,
) -> Dict[str, Any]:
    """A transfer walked `SUBMITTED` -> `QUEUED`."""
    transfer = submit_transfer(
        api, account_id, agreement_id, points_out, cardholder
    )
    return clear_screening(api, transfer["id"], analyst)


def read_transfer(api, transfer_id: str, headers: Optional[Dict] = None):
    """Read one transfer request row."""
    return validate_success(api.get_transfer(transfer_id, headers or ADMIN_HEADERS))


def list_transfers_of(api, account_id: str, headers: Optional[Dict] = None) -> List[Dict]:
    """Every transfer request of one account, in `created_at` order."""
    rows, _ = validate_paginated(
        api.list_transfers(headers or ADMIN_HEADERS, {"account_id": account_id, "limit": 100})
    )
    return rows


# ─── Fraud cases and postures ─────────────────────────────────────────


def open_case(
    api, account_id: str, analyst: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Open one investigation and return the `OPEN` row with its `instant_score`."""
    response = api.create_fraud_case(
        f.fraud_case_payload(account_id=account_id, **overrides),
        analyst or ANALYST_HEADERS,
    )
    return get_success_data(response, 201)


def review_case(api, case_id: str, analyst: Optional[Dict] = None) -> Dict[str, Any]:
    """Take one case `UNDER_REVIEW`, which computes its `review_score`."""
    return get_success_data(
        api.review_fraud_case(case_id, {}, analyst or ANALYST_HEADERS)
    )


def confirm_case(
    api, case_id: str, approver: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Confirm fraud, locking the account through the §3.9 four-hop cascade."""
    return get_success_data(
        api.confirm_fraud_case(
            case_id, f.resolution_note_payload(**overrides), approver or APPROVER_HEADERS
        )
    )


def clear_case(
    api, case_id: str, approver: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Clear a case, re-running the posture calculation and its recovery branch."""
    return get_success_data(
        api.clear_fraud_case(
            case_id, f.resolution_note_payload(**overrides), approver or APPROVER_HEADERS
        )
    )


def locked_account(
    api,
    points: int = 100000,
    admin: Optional[Dict] = None,
    analyst: Optional[Dict] = None,
    approver: Optional[Dict] = None,
) -> Tuple[Dict[str, Any], Dict[str, str], Dict[str, Any]]:
    """
    A funded account pinned at `LOCKED` by a `CONFIRMED` case.

    "If any case on the account is `CONFIRMED`, the posture is `LOCKED`."
    """
    account, cardholder = funded_account(api, points, admin)
    case = open_case(api, account["id"], analyst)
    review_case(api, case["id"], analyst)
    confirm_case(api, case["id"], approver)
    return read_account(api, account["id"], admin or ADMIN_HEADERS), cardholder, case


# ─── Benefit entitlements ─────────────────────────────────────────────


def grant_entitlement(
    api, account_id: str, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Grant one benefit entitlement and return the `ACTIVE` row."""
    response = api.create_entitlement(
        f.entitlement_payload(account_id=account_id, **overrides),
        headers or ADMIN_HEADERS,
    )
    return get_success_data(response, 201)


def read_entitlement(api, entitlement_id: str, headers: Optional[Dict] = None):
    """Read one entitlement row."""
    return validate_success(api.get_entitlement(entitlement_id, headers or ADMIN_HEADERS))


def entitlements_of(api, account_id: str, headers: Optional[Dict] = None) -> List[Dict]:
    """Every entitlement of one account, in `created_at` order."""
    rows, _ = validate_paginated(
        api.list_entitlements(
            headers or ADMIN_HEADERS, {"account_id": account_id, "limit": 100}
        )
    )
    return rows


# ─── Programme change notices ─────────────────────────────────────────


def draft_notice(api, headers: Optional[Dict] = None, **overrides: Any) -> Dict[str, Any]:
    """Draft one programme change notice."""
    response = api.create_notice(f.notice_payload(**overrides), headers or ADMIN_HEADERS)
    return get_success_data(response, 201)


def announced_notice(
    api,
    admin: Optional[Dict] = None,
    approver: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Draft, submit and announce one notice.

    Announcement "requires that the acting `X-User-ID` differs from
    `drafted_by_user_id`", so the drafter and the announcer differ here too.
    """
    admin = admin or ADMIN_HEADERS
    approver = approver or APPROVER_HEADERS
    notice = draft_notice(api, admin, **overrides)
    get_success_data(api.submit_notice(notice["id"], {}, admin))
    return get_success_data(api.announce_notice(notice["id"], {}, approver))


def read_notice(api, notice_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Read one notice row."""
    return validate_success(api.get_notice(notice_id, headers or ADMIN_HEADERS))


# ─── Liability snapshots ──────────────────────────────────────────────


def new_snapshot(
    api, as_of: str, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Value the outstanding points liability at a cut-off instant."""
    response = api.create_snapshot(
        f.snapshot_payload(as_of=as_of, **overrides), headers or ADMIN_HEADERS
    )
    return get_success_data(response, 201)
