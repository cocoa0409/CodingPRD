"""Entity-shape corners of the Deposit Insurance Resolution API.

Every test here pins one declared entity behaviour: the fields a create echoes
back, the defaults an omitted optional input takes, the values a client may not
write for itself, the not-found code each collection answers with, and the
referential rules that bind an account to the institution its depositor belongs
to.  Each test builds its own rows against an empty database whose logical clock
reads the instant the service started at.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_ACCOUNT_NOT_FOUND,
    ERR_DEPOSITOR_INSTITUTION_MISMATCH,
    ERR_INSTITUTION_NOT_FOUND,
    ERR_INVALID_REQUEST,
)
from test_helpers.assertions import (
    assert_account_dimensions,
    assert_audit_fields,
    assert_cents,
    assert_fields_equal,
    assert_immutable_record_fields,
    assert_page,
    total_count,
)
from test_helpers.test_users import (
    CLAIMS_AGENT,
    CLOSING_MANAGER,
    RECEIVERSHIP_TRUSTEE,
)

# Syntactically valid UUIDs that no row will ever carry, since ids are minted by
# the server and never reused.
UNKNOWN_ACCOUNT_ID = "00000000-0000-0000-0000-0000000000ff"
UNKNOWN_INSTITUTION_ID = "00000000-0000-0000-0000-0000000000aa"


def _assert_not_recorded(row, *fields):
    """Every named field is still unrecorded on the row."""
    for field in fields:
        assert row.get(field) is None, (
            f"{field} must not be recorded yet, got {row.get(field)!r}"
        )


def test_institution_created_with_all_required_fields_returns_201(client):
    """Registering a troubled institution echoes every declared input and opens the
    row under pre-failure monitoring with every derived counter at zero.

    PRD: "A newly registered institution opens at `status` `PRE_FAILURE_MONITORING`, with `readiness_standardized` false, `franchise_marketing_status` `NOT_STARTED`, `least_cost_status` `NOT_STARTED`, and no `failure_datetime`, `bid_deadline_at`, `least_cost_test_variant`, `liquidation_baseline_cents` or `resolution_method` yet recorded."

    Design: Corner/entities/institution_created_with_all_required_fields_returns_201
    """
    X.open_at_setup_clock(client)

    response = client.create_institution(
        F.institution_payload(
            cert_number="60001",
            legal_name="Kootenai Pioneer Bank",
            charter_state="ID",
            book_asset_value_cents=40000000,
            estimated_liquidation_recovery_cents=30000000,
        ),
        CLOSING_MANAGER,
    )
    institution = validate_success(response, 201)
    assert response.json()["response_type"] == "object", response.text

    assert_fields_equal(
        institution,
        {
            "cert_number": "60001",
            "legal_name": "Kootenai Pioneer Bank",
            "charter_state": "ID",
            "book_asset_value_cents": 40000000,
            "estimated_liquidation_recovery_cents": 30000000,
            "status": "PRE_FAILURE_MONITORING",
            "franchise_marketing_status": "NOT_STARTED",
            "least_cost_status": "NOT_STARTED",
            "readiness_standardized": False,
            "total_deposit_balance_cents": 0,
            "depositor_record_count": 0,
            "aggregate_insured_cents": 0,
            "aggregate_certificate_face_cents": 0,
            "uninsured_claim_count": 0,
            "receivership_cash_cents": 0,
        },
    )
    _assert_not_recorded(
        institution,
        "failure_datetime",
        "bid_deadline_at",
        "least_cost_test_variant",
        "liquidation_baseline_cents",
        "resolution_method",
    )
    assert_audit_fields(institution)
    assert institution["version"] == 1, institution["version"]


def test_institution_get_by_id_returns_stored_values(client):
    """Reading one institution back returns exactly what registration stored, and a
    read is not a mutation so the version stays at 1.

    PRD: "The `version` of a resource starts at 1 and increments by one on every server-side mutation of that resource"

    Design: Corner/entities/institution_get_by_id_returns_stored_values
    """
    X.open_at_setup_clock(client)
    created = X.new_institution(
        client,
        cert_number="60002",
        legal_name="Bannock Savings",
        charter_state="ID",
        book_asset_value_cents=12000000,
        estimated_liquidation_recovery_cents=9000000,
    )

    institution = validate_success(
        client.get_institution(created["id"], RECEIVERSHIP_TRUSTEE), 200
    )

    assert_fields_equal(
        institution,
        {
            "id": created["id"],
            "cert_number": "60002",
            "legal_name": "Bannock Savings",
            "charter_state": "ID",
            "book_asset_value_cents": 12000000,
            "estimated_liquidation_recovery_cents": 9000000,
            "status": "PRE_FAILURE_MONITORING",
            "version": 1,
        },
    )


def test_institution_list_pagination_reports_total_count_and_has_more(client):
    """The institution list pages through its rows while reporting the total that
    matches the request's filters, and honours the charter-state filter.

    PRD: "`total_count` counts every resource matching the request's filters — not merely those on the returned page"

    Design: Corner/entities/institution_list_pagination_reports_total_count_and_has_more
    """
    X.open_at_setup_clock(client)
    X.new_institution(
        client,
        cert_number="60003",
        legal_name="Alpha Bank",
        charter_state="WA",
        book_asset_value_cents=1000000,
        estimated_liquidation_recovery_cents=500000,
    )
    X.new_institution(
        client,
        cert_number="60004",
        legal_name="Beta Bank",
        charter_state="WA",
        book_asset_value_cents=2000000,
        estimated_liquidation_recovery_cents=900000,
    )
    X.new_institution(
        client,
        cert_number="60005",
        legal_name="Gamma Bank",
        charter_state="OR",
        book_asset_value_cents=3000000,
        estimated_liquidation_recovery_cents=1200000,
    )

    first_page = client.list_institutions(CLOSING_MANAGER, params={"limit": 2, "offset": 0})
    rows, meta = assert_page(first_page, expected_total=3)
    assert first_page.json()["response_type"] == "array", first_page.text
    assert len(rows) == 2, rows
    assert_fields_equal(meta, {"limit": 2, "offset": 0, "has_more": True})

    rows, meta = assert_page(
        client.list_institutions(CLOSING_MANAGER, params={"limit": 2, "offset": 2}),
        expected_total=3,
    )
    assert len(rows) == 1, rows
    assert_fields_equal(meta, {"offset": 2, "has_more": False})

    rows, meta = assert_page(
        client.list_institutions(CLOSING_MANAGER, params={"charter_state": "WA"}),
        expected_total=2,
    )
    assert len(rows) == 2, rows
    assert [row["charter_state"] for row in rows] == ["WA", "WA"], rows
    assert_fields_equal(meta, {"limit": C.LIMIT_DEFAULT, "has_more": False})


def test_deposit_account_get_with_unknown_id_returns_not_found(client):
    """Reading a deposit account that does not exist answers with the account
    collection's own not-found code, never an empty success.

    PRD: "`ERR_ACCOUNT_NOT_FOUND` for a deposit account"

    Design: Corner/entities/deposit_account_get_with_unknown_id_returns_not_found
    """
    X.open_at_setup_clock(client)

    validate_error(
        client.get_deposit_account(UNKNOWN_ACCOUNT_ID, CLAIMS_AGENT),
        ERR_ACCOUNT_NOT_FOUND,
        404,
    )


def test_institution_create_missing_required_charter_state_returns_invalid_request(client):
    """Registering an institution without its chartered state is a request-shape
    failure and persists no institution at all.

    PRD: "**Request shape** — every required field present, every type correct, every enum member recognized, and every integer inside its declared range, else `ERR_INVALID_REQUEST` with HTTP 400."

    Design: Corner/entities/institution_create_missing_required_charter_state_returns_invalid_request
    """
    X.open_at_setup_clock(client)
    payload = F.institution_payload(
        cert_number="60006",
        legal_name="Missing Field Bank",
        book_asset_value_cents=1000000,
        estimated_liquidation_recovery_cents=500000,
    )
    payload.pop("charter_state")

    validate_error(
        client.create_institution(payload, CLOSING_MANAGER), ERR_INVALID_REQUEST, 400
    )

    assert total_count(client.list_institutions(CLOSING_MANAGER)) == 0


def test_deposit_account_omitted_optional_fields_take_declared_defaults(client):
    """A single-ownership account loaded without accrued interest or the brokered
    pair opens with zero accrued interest, no broker of record, and all three of
    its independent dimensions at their starting values.

    PRD: "`accrued_interest_cents`, the interest accrued and unposted as of the failure date, which defaults to 0 when omitted"

    Design: Corner/entities/deposit_account_omitted_optional_fields_take_declared_defaults
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="60007",
        legal_name="Defaults Bank",
        charter_state="WA",
        book_asset_value_cents=1000000,
        estimated_liquidation_recovery_cents=500000,
    )
    depositor = X.new_depositor(
        client,
        institution["id"],
        tin_hash="TIN-PRIYA-60007",
        legal_name="Priya Menon",
        depositor_type="NATURAL_PERSON",
        contact_email="priya@example.com",
    )

    payload = F.deposit_account_payload(
        institution["id"],
        depositor["id"],
        account_number="P-0001",
        ownership_category="SINGLE",
        balance_cents=500000,
        opened_at="2024-01-15T00:00:00Z",
    )
    payload.pop("accrued_interest_cents")
    assert "broker_name" not in payload and "recordkeeping_status" not in payload, payload

    account = validate_success(client.create_deposit_account(payload, CLAIMS_AGENT), 201)

    assert_fields_equal(
        account, {"balance_cents": 500000, "accrued_interest_cents": 0}
    )
    assert_cents(account["accrued_interest_cents"])
    _assert_not_recorded(account, "broker_name", "recordkeeping_status")
    assert_account_dimensions(
        account,
        "PENDING",
        "NONE",
        "PENDING",
        held_amount_cents=0,
        attributed_amount_cents=0,
    )


def test_institution_aggregate_fields_ignored_input_on_create(client):
    """The institution's derived receivership aggregates are the server's to write:
    figures a client puts in the registration body are ignored and both counters
    read zero, while the declared intake inputs are still honoured.

    PRD: "Every derived counter starts at zero: `total_deposit_balance_cents`, `depositor_record_count`, `aggregate_insured_cents`"

    Design: Corner/entities/institution_aggregate_fields_ignored_input_on_create
    """
    X.open_at_setup_clock(client)

    created = validate_success(
        client.create_institution(
            F.institution_payload(
                cert_number="60008",
                legal_name="Computed Bank",
                charter_state="WA",
                book_asset_value_cents=1000000,
                estimated_liquidation_recovery_cents=500000,
                total_deposit_balance_cents=999999,
                aggregate_insured_cents=888888,
            ),
            CLOSING_MANAGER,
        ),
        201,
    )

    institution = validate_success(
        client.get_institution(created["id"], CLOSING_MANAGER), 200
    )
    assert_fields_equal(
        institution,
        {
            "total_deposit_balance_cents": 0,
            "aggregate_insured_cents": 0,
            "book_asset_value_cents": 1000000,
        },
    )


def test_depositor_record_notice_fields_ignored_input_on_create(client):
    """A depositor record always opens with its notice still pending, whatever
    notice state the loading agent tries to assert in the create body.

    PRD: "Depositor records open with `notice_status` `PENDING`, no `notice_template_code`, no `notice_sent_at` and no `acknowledged_at`, and with `attributed_total_cents`, `certified_insured_cents` and `certified_uninsured_cents` all at zero."

    Design: Corner/entities/depositor_record_notice_fields_ignored_input_on_create
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="60009",
        legal_name="System Fields Bank",
        charter_state="WA",
        book_asset_value_cents=1000000,
        estimated_liquidation_recovery_cents=500000,
    )

    depositor = validate_success(
        client.create_depositor_record(
            institution["id"],
            F.depositor_record_payload(
                tin_hash="TIN-SF-60009",
                legal_name="Quinn Alvarez",
                depositor_type="BUSINESS",
                contact_email="quinn@example.com",
                notice_status="ACKNOWLEDGED",
                notice_sent_at="2020-01-01T00:00:00Z",
            ),
            CLAIMS_AGENT,
        ),
        201,
    )

    assert_fields_equal(
        depositor,
        {
            "notice_status": "PENDING",
            "certified_insured_cents": 0,
            "certified_uninsured_cents": 0,
            "attributed_total_cents": 0,
        },
    )
    _assert_not_recorded(
        depositor, "notice_sent_at", "acknowledged_at", "notice_template_code"
    )
    assert_audit_fields(depositor)
    assert depositor["version"] == 1, depositor["version"]


def test_deposit_account_invalid_ownership_category_enum_returns_invalid_request(client):
    """An account whose ownership category is not one of the six declared members,
    or whose principal is negative, is refused as a malformed request and loads
    nothing into the deposit file.

    PRD: "every enum member recognized, and every integer inside its declared range, else `ERR_INVALID_REQUEST` with HTTP 400"

    Design: Corner/entities/deposit_account_invalid_ownership_category_enum_returns_invalid_request
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="60010",
        legal_name="Enum Bank",
        charter_state="WA",
        book_asset_value_cents=1000000,
        estimated_liquidation_recovery_cents=500000,
    )
    depositor = X.new_depositor(
        client,
        institution["id"],
        tin_hash="TIN-RAFI-60010",
        legal_name="Rafi Haddad",
        depositor_type="NATURAL_PERSON",
        contact_email="rafi@example.com",
    )

    validate_error(
        client.create_deposit_account(
            F.deposit_account_payload(
                institution["id"],
                depositor["id"],
                account_number="R-0001",
                ownership_category="CHECKING",
                balance_cents=100000,
                opened_at="2024-01-15T00:00:00Z",
            ),
            CLAIMS_AGENT,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        client.create_deposit_account(
            F.deposit_account_payload(
                institution["id"],
                depositor["id"],
                account_number="R-0002",
                ownership_category="SINGLE",
                balance_cents=-1,
                opened_at="2024-01-15T00:00:00Z",
            ),
            CLAIMS_AGENT,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    assert (
        total_count(
            client.list_deposit_accounts(
                CLAIMS_AGENT, params={"institution_id": institution["id"]}
            )
        )
        == 0
    )


def test_ownership_interest_immutable_carries_no_version_field(client):
    """An ownership interest is an immutable assertion: its create response and its
    list rows expose no version or updated_at at all, and the row read back is
    exactly the row that was attached.

    PRD: "An ownership interest is an immutable historical assertion about who held what share of an account, so it carries only `id` and `created_at`; it has no `updated_at` and no `version`, and there is no operation that modifies one after it is attached."

    Design: Corner/entities/ownership_interest_immutable_carries_no_version_field
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="60011",
        legal_name="Immutable Bank",
        charter_state="WA",
        book_asset_value_cents=40000000,
        estimated_liquidation_recovery_cents=20000000,
    )
    sara = X.new_depositor(
        client,
        institution["id"],
        tin_hash="TIN-SARA-60011",
        legal_name="Sara Bianchi",
        depositor_type="NATURAL_PERSON",
        contact_email="sara@example.com",
    )
    X.new_depositor(
        client,
        institution["id"],
        tin_hash="TIN-TOMAS-60011",
        legal_name="Tomas Bianchi",
        depositor_type="NATURAL_PERSON",
        contact_email="tomas@example.com",
    )
    account = X.new_account(
        client,
        institution["id"],
        sara["id"],
        account_number="J-0001",
        ownership_category="JOINT",
        balance_cents=40000000,
        accrued_interest_cents=0,
        opened_at="2024-02-01T00:00:00Z",
    )

    interest = validate_success(
        client.create_ownership_interest(
            account["id"],
            F.ownership_interest_payload(sara["id"], "CO_OWNER", 5000),
            CLAIMS_AGENT,
        ),
        201,
    )

    assert_fields_equal(
        interest,
        {
            "deposit_account_id": account["id"],
            "depositor_record_id": sara["id"],
            "interest_role": "CO_OWNER",
            "designated_share_bps": 5000,
        },
    )
    assert_immutable_record_fields(interest)

    rows, _ = assert_page(
        client.list_account_ownership_interests(
            account["id"], CLAIMS_AGENT, params={"interest_role": "CO_OWNER"}
        ),
        expected_total=1,
        expected_ids=[interest["id"]],
    )
    assert rows[0] == interest, rows[0]
    assert_immutable_record_fields(rows[0])


def test_depositor_record_create_under_unknown_institution_returns_not_found(client):
    """Loading a depositor under an institution that does not exist resolves the
    path identifier first and answers with the institution's not-found code,
    leaving no orphan depositor behind.

    PRD: "`ERR_INSTITUTION_NOT_FOUND` when an institution id in a path or in an `institution_id` body field does not resolve"

    Design: Corner/entities/depositor_record_create_under_unknown_institution_returns_not_found
    """
    X.open_at_setup_clock(client)

    validate_error(
        client.create_depositor_record(
            UNKNOWN_INSTITUTION_ID,
            F.depositor_record_payload(
                tin_hash="TIN-ORPHAN",
                legal_name="Orphan Depositor",
                depositor_type="NATURAL_PERSON",
                contact_email="orphan@example.com",
            ),
            CLAIMS_AGENT,
        ),
        ERR_INSTITUTION_NOT_FOUND,
        404,
    )

    assert total_count(client.list_depositor_records(CLAIMS_AGENT)) == 0


def test_deposit_account_cross_institution_depositor_reference_rejected(client):
    """An account naming one institution but a titled owner registered at another
    is refused on cross-entity integrity even though both identifiers resolve.

    PRD: "Should the named `primary_depositor_id` belong to a different institution than the account, the load is refused with `ERR_DEPOSITOR_INSTITUTION_MISMATCH`"

    Design: Corner/entities/deposit_account_cross_institution_depositor_reference_rejected
    """
    X.open_at_setup_clock(client)
    home = X.new_institution(
        client,
        cert_number="60012",
        legal_name="Home Institution Bank",
        charter_state="WA",
        book_asset_value_cents=1000000,
        estimated_liquidation_recovery_cents=500000,
    )
    other = X.new_institution(
        client,
        cert_number="60013",
        legal_name="Other Institution Bank",
        charter_state="WA",
        book_asset_value_cents=1000000,
        estimated_liquidation_recovery_cents=500000,
    )
    umi = X.new_depositor(
        client,
        home["id"],
        tin_hash="TIN-UMI-60012",
        legal_name="Umi Tanaka",
        depositor_type="NATURAL_PERSON",
        contact_email="umi@example.com",
    )

    validate_error(
        client.create_deposit_account(
            F.deposit_account_payload(
                other["id"],
                umi["id"],
                account_number="U-0001",
                ownership_category="SINGLE",
                balance_cents=100000,
                opened_at="2024-01-15T00:00:00Z",
            ),
            CLAIMS_AGENT,
        ),
        ERR_DEPOSITOR_INSTITUTION_MISMATCH,
        422,
    )

    for institution_id in (home["id"], other["id"]):
        assert (
            total_count(
                client.list_deposit_accounts(
                    CLAIMS_AGENT, params={"institution_id": institution_id}
                )
            )
            == 0
        )


def test_brokered_pass_through_account_missing_required_recordkeeping_status_rejected(client):
    """The brokered pair is conditionally required: a brokered placement without a
    recordkeeping status is malformed, and so is a single-ownership account that
    supplies the pair anyway.

    PRD: "`broker_name` and `recordkeeping_status` must both be present exactly when `ownership_category` is `BROKERED_PASS_THROUGH`, and must both be absent otherwise."

    Design: Corner/entities/brokered_pass_through_account_missing_required_recordkeeping_status_rejected
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="60014",
        legal_name="Conditional Field Bank",
        charter_state="WA",
        book_asset_value_cents=1000000,
        estimated_liquidation_recovery_cents=500000,
    )
    broker = X.new_depositor(
        client,
        institution["id"],
        tin_hash="TIN-VANTAGE-60014",
        legal_name="Vantage Deposits LLC",
        depositor_type="BROKER",
        contact_email="ops@vantage.example.com",
    )

    brokered_without_recordkeeping = F.deposit_account_payload(
        institution["id"],
        broker["id"],
        account_number="V-0001",
        ownership_category="BROKERED_PASS_THROUGH",
        balance_cents=100000,
        opened_at="2024-01-15T00:00:00Z",
        broker_name="Vantage Deposits LLC",
    )
    brokered_without_recordkeeping.pop("recordkeeping_status")
    validate_error(
        client.create_deposit_account(brokered_without_recordkeeping, CLAIMS_AGENT),
        ERR_INVALID_REQUEST,
        400,
    )

    validate_error(
        client.create_deposit_account(
            F.deposit_account_payload(
                institution["id"],
                broker["id"],
                account_number="V-0002",
                ownership_category="SINGLE",
                balance_cents=100000,
                opened_at="2024-01-15T00:00:00Z",
                broker_name="Vantage Deposits LLC",
                recordkeeping_status="COMPLETE",
            ),
            CLAIMS_AGENT,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    assert (
        total_count(
            client.list_deposit_accounts(
                CLAIMS_AGENT, params={"institution_id": institution["id"]}
            )
        )
        == 0
    )
