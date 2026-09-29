"""
The authorisation ladder of §2.1: absent headers, unrecognised roles, role lists,
the two entity-backed ownership scopes, and the four segregated operator pairings.
"""

from prd_bench_local_runner.testing import build_user_headers, validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACCOUNT_OWNERSHIP_REQUIRED,
    ERR_AGENCY_SCOPE_VIOLATION,
    ERR_MISSING_AUTH_HEADERS,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNKNOWN_ROLE,
)
from test_helpers.assertions import assert_account_aggregates, assert_page
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    ANALYST_HEADERS,
    ANALYST_USER_ID,
    APPROVER_2_HEADERS,
    APPROVER_2_USER_ID,
    APPROVER_HEADERS,
    EMPTY_USER_ID_HEADERS,
    NO_HEADERS,
    UNKNOWN_ROLE_HEADERS,
    make_agency_headers,
    make_cardholder_headers,
)
from test_helpers.types import (
    CATEGORY_GROCERY,
    CHANGE_BENEFIT_REMOVAL,
    FULFILLMENT_CONFIRMED,
    FULFILLMENT_TICKETED,
    METHOD_FAIR_VALUE,
    NOTICE_ANNOUNCED,
    NOTICE_PENDING_APPROVAL,
    POSTURE_CLEAR,
    PRODUCT_PREMIER,
    ROLE_PROGRAM_APPROVER,
    SETTLEMENT_AGENCY_INVOICED,
    TRANSFER_HELD,
    TRANSFER_SUBMITTED,
)

GROCERY_MCC = "5411"


def _grocery(api):
    """The 1.0x grocery mapping funding purchases ride on."""
    return fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=GROCERY_MCC,
        display_name="Grocery Stores",
        base_category=CATEGORY_GROCERY,
        base_multiplier=1.0,
        is_fallback=False,
    )


def test_a_cardholder_may_not_enrol_an_account_however_perfect_the_body(api):
    """
    "If the role is recognised but is not among the roles listed for the addressed
    endpoint in §4, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    §4: "| POST | `/rewards/accounts` | Enroll a card account. | `ProgramAdmin` |"

    Design: Corner/rbac/cardholder_creating_an_account_forbidden
    """
    account = fx.new_account(
        api,
        ADMIN_HEADERS,
        cardholder_name="Nora Bianchi",
        email="nora@example.com",
        enrolled_at="2025-01-18T00:00:00.000Z",
    )

    validate_error(
        api.create_account(
            f.account_payload(
                cardholder_name="Self Enrolled",
                email="self@example.com",
                card_product_code=PRODUCT_PREMIER,
                enrolled_at="2026-08-01T00:00:00.000Z",
            ),
            make_cardholder_headers(account["id"]),
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    assert_page(api.list_accounts(ADMIN_HEADERS), total_count=1, length=1)


def test_a_cardholder_reads_its_own_account_and_only_its_own(api):
    """
    "A `Cardholder` may read its own account, and may address only its own redemption
    orders, transfer requests and benefit entitlements. Any attempt to read another
    account or to write against a resource whose `account_id` differs from
    `X-User-ID` is rejected with `ERR_ACCOUNT_OWNERSHIP_REQUIRED` (HTTP 403)."

    Design: Corner/rbac/cardholder_reading_another_cardholders_account_forbidden
    """
    owen = fx.new_account(
        api,
        ADMIN_HEADERS,
        cardholder_name="Owen Pike",
        email="owen@example.com",
        enrolled_at="2025-01-19T00:00:00.000Z",
    )
    pia = fx.new_account(
        api,
        ADMIN_HEADERS,
        cardholder_name="Pia Rossi",
        email="pia@example.com",
        card_product_code=PRODUCT_PREMIER,
        enrolled_at="2025-01-20T00:00:00.000Z",
    )
    owen_headers = fx.account_holder(owen)

    validate_error(
        api.get_account(pia["id"], owen_headers),
        ERR_ACCOUNT_OWNERSHIP_REQUIRED,
        403,
    )

    own = validate_success(api.get_account(owen["id"], owen_headers))
    assert own["id"] == owen["id"]
    assert own["cardholder_name"] == "Owen Pike"


def test_only_the_agency_behind_the_offer_may_ticket_the_order(api):
    """
    "for a redemption order they compare the `agency_partner_id` of the offer behind
    the order. An agency writing against inventory or a ticket belonging to another
    agency is rejected with `ERR_AGENCY_SCOPE_VIOLATION` (HTTP 403). This check guards
    five operations: publishing an offer, resyncing an offer, withdrawing an offer,
    ticketing a redemption order, and refunding a redemption order."

    Design: Corner/rbac/agency_ticketing_another_agencys_order_forbidden
    """
    _grocery(api)
    account, cardholder = fx.funded_account(
        api, 0, cardholder_name="Quinn Adler", email="quinn@example.com"
    )
    fx.fund_account(api, account["id"], 10000, mcc_code=GROCERY_MCC)
    owner, offer, owner_headers = fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={
            "name": "Agency One",
            "contracted_markup_bps": 0,
            "parity_tolerance_bps": 0,
        },
        itinerary_code="PHL-BCN-39",
        depart_at="2026-10-22T19:00:00.000Z",
        return_at="2026-10-30T09:00:00.000Z",
        net_rate_cents=10000,
        agency_public_price_cents=10000,
        agency_public_seats=2,
        portal_seats=2,
        tax_cents=0,
    )
    rival = fx.new_agency(
        api,
        ADMIN_HEADERS,
        name="Agency Two",
        contracted_markup_bps=0,
        parity_tolerance_bps=0,
    )

    order = fx.book(api, offer, account["id"], cardholder, traveler_name="Quinn Adler")
    fx.confirm(api, order["id"], cardholder)

    validate_error(
        api.ticket_order(
            order["id"],
            f.ticket_payload("TKT-RIVAL-1"),
            make_agency_headers(rival["id"]),
        ),
        ERR_AGENCY_SCOPE_VIOLATION,
        403,
    )

    untouched = validate_success(api.get_order(order["id"], ADMIN_HEADERS))
    assert untouched["fulfillment_status"] == FULFILLMENT_CONFIRMED
    assert untouched["ticket_number"] is None
    assert (
        validate_success(api.get_agency_partner(rival["id"], ADMIN_HEADERS))[
            "payable_cents"
        ]
        == 0
    )

    ticketed = validate_success(
        api.ticket_order(order["id"], f.ticket_payload("TKT-OWNER-1"), owner_headers)
    )
    assert ticketed["fulfillment_status"] == FULFILLMENT_TICKETED
    assert ticketed["ticket_number"] == "TKT-OWNER-1"
    assert ticketed["settlement_status"] == SETTLEMENT_AGENCY_INVOICED
    assert (
        validate_success(api.get_agency_partner(owner["id"], ADMIN_HEADERS))[
            "payable_cents"
        ]
        == 10000
    )


def test_both_headers_are_mandatory_on_reads_and_writes_alike(api):
    """
    "Every request to every endpoint — reads included — must carry two headers:
    `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the
    capacity in which it acts. If either header is absent or present but empty, the
    request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."

    Design: Corner/rbac/request_with_missing_auth_headers_rejected
    """
    validate_error(api.get_clock(NO_HEADERS), ERR_MISSING_AUTH_HEADERS, 401)
    validate_error(
        api.create_account(
            f.account_payload(
                cardholder_name="Headerless Hank",
                email="hank@example.com",
                enrolled_at="2025-01-22T00:00:00.000Z",
            ),
            EMPTY_USER_ID_HEADERS,
        ),
        ERR_MISSING_AUTH_HEADERS,
        401,
    )

    assert_page(api.list_accounts(ADMIN_HEADERS), total_count=0, length=0)


def test_an_unrecognised_role_is_a_401_before_any_endpoint_role_list_is_consulted(api):
    """
    "If `X-User-Role` carries any string other than the five role names below, the
    request is rejected with `ERR_UNKNOWN_ROLE` (HTTP 401)."

    Design: Corner/rbac/request_with_unknown_role_header_rejected
    """
    validate_error(api.get_clock(UNKNOWN_ROLE_HEADERS), ERR_UNKNOWN_ROLE, 401)


def test_segregation_of_duties_compares_operator_ids_not_roles(api):
    """
    "The acting `X-User-ID` must differ from the opposing operator identifier already
    recorded on the row: from `PartnerAgreement.submitted_by_user_id` when approving or
    reinstating an agreement, from `ProgramChangeNotice.drafted_by_user_id` when
    announcing a notice, from `FraudCase.opened_by_user_id` when confirming or clearing
    a case, and from `TransferRequest.held_by_user_id` when releasing a hold. A match
    rejects the request with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/segregation_of_duties_blocks_the_same_operator_on_both_halves
    """
    _grocery(api)
    notice = fx.draft_notice(
        api,
        ADMIN_HEADERS,
        notice_code="SOD-2026-11",
        change_type=CHANGE_BENEFIT_REMOVAL,
        effective_at="2026-11-01T00:00:00.000Z",
        grandfather_window_days=30,
        cohort_enrolled_before="2025-01-01T00:00:00.000Z",
    )
    validate_success(api.submit_notice(notice["id"], {}, ADMIN_HEADERS))

    account, cardholder = fx.funded_account(
        api, 0, cardholder_name="Rhea Kapoor", email="rhea@example.com"
    )
    fx.fund_account(api, account["id"], 10000, mcc_code=GROCERY_MCC)
    agreement = fx.active_agreement(
        api,
        ADMIN_HEADERS,
        APPROVER_HEADERS,
        partner_name="Skyward Miles",
        partner_program_code="SKYW",
        transfer_latency_hours=48,
        reversal_window_hours=72,
        settlement_cost_cents_per_1k=900,
    )
    transfer = fx.submit_transfer(api, account["id"], agreement["id"], 4000, cardholder)
    fx.hold_transfer(api, transfer["id"], ANALYST_HEADERS)

    drafter_as_approver = build_user_headers(ADMIN_USER_ID, ROLE_PROGRAM_APPROVER)
    holder_as_approver = build_user_headers(ANALYST_USER_ID, ROLE_PROGRAM_APPROVER)

    validate_error(
        api.announce_notice(notice["id"], {}, drafter_as_approver),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    assert fx.read_notice(api, notice["id"])["status"] == NOTICE_PENDING_APPROVAL

    validate_error(
        api.release_transfer(transfer["id"], {}, holder_as_approver),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    held = fx.read_transfer(api, transfer["id"])
    assert held["status"] == TRANSFER_HELD
    assert held["held_by_user_id"] == ANALYST_USER_ID

    announced = validate_success(
        api.announce_notice(notice["id"], {}, APPROVER_2_HEADERS)
    )
    assert announced["status"] == NOTICE_ANNOUNCED
    assert announced["approved_by_user_id"] == APPROVER_2_USER_ID

    released = validate_success(
        api.release_transfer(transfer["id"], {}, APPROVER_2_HEADERS)
    )
    assert released["status"] == TRANSFER_SUBMITTED
    assert released["released_by_user_id"] == APPROVER_2_USER_ID
    assert released["hold_reason"] == "MANUAL_REVIEW"
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        transfer_hold_count=1,
        fraud_posture=POSTURE_CLEAR,
    )


def test_the_fraud_analysts_read_surface_is_enumerated_not_global(api):
    """
    §4: "| GET | `/rewards/accounts` | List accounts, filterable by lifecycle, posture
    and governing notice. | `ProgramAdmin`, `ProgramApprover`, `FraudAnalyst` |",
    "| GET | `/rewards/liability-snapshots` | List liability snapshots by method. |
    `ProgramAdmin`, `ProgramApprover` |" and "| GET | `/rewards/agency-partners` | List
    agencies. | `ProgramAdmin`, `ProgramApprover`, `AgencySupplier` |"

    Design: Corner/rbac/fraud_analyst_listing_liability_snapshots_forbidden
    """
    account = fx.new_account(
        api,
        ADMIN_HEADERS,
        cardholder_name="Sami Toure",
        email="sami@example.com",
        enrolled_at="2025-01-24T00:00:00.000Z",
    )
    fx.new_agency(
        api,
        ADMIN_HEADERS,
        name="Northwind Travel",
        contracted_markup_bps=2000,
        parity_tolerance_bps=1000,
        invoice_terms_days=30,
    )
    fx.new_snapshot(
        api, "2026-08-01T00:00:00.000Z", ADMIN_HEADERS, method=METHOD_FAIR_VALUE
    )

    assert_page(api.list_accounts(ANALYST_HEADERS), total_count=1, length=1)
    assert_page(
        api.list_fraud_cases(ANALYST_HEADERS, {"account_id": account["id"]}),
        total_count=0,
        length=0,
    )
    validate_error(
        api.list_snapshots(ANALYST_HEADERS), ERR_ROLE_NOT_PERMITTED, 403
    )
    validate_error(
        api.list_agency_partners(ANALYST_HEADERS), ERR_ROLE_NOT_PERMITTED, 403
    )
