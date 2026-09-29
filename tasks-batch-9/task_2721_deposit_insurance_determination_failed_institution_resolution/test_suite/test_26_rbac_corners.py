"""Role-based access-control corners of the Deposit Insurance Resolution API.

Every request carries an acting principal and the capacity it acts in, and the
specification fixes three separate things about that pair: which header shapes
fail authentication outright, which roles are listed for each operation, and how
the two entity-backed roles have their `X-User-ID` compared against the row they
claim to be.  The checks are ordered, so a request that would fail several of
them returns exactly one error, and these tests pin which one.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_BIDDER_MISMATCH,
    ERR_DEPOSITOR_MISMATCH,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import assert_fields_equal, assert_page
from test_helpers.test_users import (
    CLAIMS_AGENT,
    CLAIMS_CERTIFIER,
    CLOSING_MANAGER,
    CLOSING_MANAGER_USER_ID,
    RECEIVERSHIP_TRUSTEE,
    RESOLUTION_ANALYST,
    headers_missing_role,
    headers_missing_user_id,
    headers_no_headers,
    headers_undeclared_role,
    make_bidder_headers,
    make_depositor_headers,
    make_headers,
)

# Syntactically valid UUIDs no row will ever carry, since ids are server-minted.
UNKNOWN_INSTITUTION_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_DETERMINATION_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_BRANCH_ID = "00000000-0000-4000-8000-000000000000"


def test_unauthenticated_when_missing_auth_headers_or_when_the_role_is_undeclared(client):
    """A request that omits either identity header, or declares a role string that is
    not one of the seven, is refused as unauthenticated before any other check runs —
    including before the path identifier is resolved.

    PRD: "A request missing either header, or presenting a role string that is not one of the seven declared roles, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unauthenticated_when_missing_auth_headers_or_when_the_role_is_undeclared
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61079",
        legal_name="Auth Gate Bank",
        charter_state="KY",
        book_asset_value_cents=9000000,
        estimated_liquidation_recovery_cents=3000000,
    )

    # Neither identity header at all.
    validate_error(
        client.get_institution(institution["id"], headers_no_headers()),
        ERR_UNAUTHENTICATED,
    )
    # `X-User-ID` present, `X-User-Role` omitted.
    validate_error(
        client.get_institution(institution["id"], headers_missing_role()),
        ERR_UNAUTHENTICATED,
    )
    # Both headers are required, not just the role.
    validate_error(
        client.get_institution(institution["id"], headers_missing_user_id()),
        ERR_UNAUTHENTICATED,
    )
    # A role that is not one of the seven declared roles is an authentication failure.
    validate_error(
        client.get_institution(institution["id"], headers_undeclared_role()),
        ERR_UNAUTHENTICATED,
    )
    # Authentication is evaluated before the existence of every resource the
    # request names, so an unresolvable id does not turn this into a 404.
    validate_error(
        client.get_institution(UNKNOWN_INSTITUTION_ID, headers_no_headers()),
        ERR_UNAUTHENTICATED,
    )
    # Role strings are matched exactly as the seven roles are spelled.
    validate_error(
        client.create_institution(
            F.institution_payload(cert_number="61080", legal_name="Ghost Bank"),
            make_headers("closingmanager", CLOSING_MANAGER_USER_ID),
        ),
        ERR_UNAUTHENTICATED,
    )

    # The refused create never happened.
    rows, _ = assert_page(client.list_institutions(CLOSING_MANAGER), expected_total=1)
    assert [row["id"] for row in rows] == [institution["id"]], rows


def test_every_exclusive_operation_is_denied_to_all_other_roles_before_any_row_lookup(
    client,
):
    """Each write operation is reserved to the roles listed for it, and the role check
    runs before the request's resources are resolved and before any state
    precondition, so an unlisted role is refused with 403 rather than a 404 or a
    lifecycle conflict — and nothing is mutated.

    PRD: "A request that authenticates successfully but whose role is not listed for the target operation in §4 is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/every_exclusive_operation_is_denied_to_all_other_roles_before_any_row_lookup
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61081",
        legal_name="Role Matrix Bank",
        charter_state="SC",
        book_asset_value_cents=11000000,
        estimated_liquidation_recovery_cents=4000000,
    )
    depositor = X.new_depositor(
        client,
        institution["id"],
        tin_hash="TIN-RB-1",
        legal_name="Viktor Sorokin",
        contact_email="viktor@example.com",
    )
    account = X.new_account(
        client,
        institution["id"],
        depositor["id"],
        account_number="RB-0001",
        ownership_category="SINGLE",
        balance_cents=8000000,
    )
    bidder = X.new_bidder(
        client,
        legal_name="Matrix Federal",
        cert_number="62013",
        tier1_capital_ratio_bps=2000,
        camels_composite=2,
    )
    institution_version = X.institution_version(client, institution["id"], CLOSING_MANAGER)
    depositor_version = X.depositor_version(client, depositor["id"])

    # Closing belongs exclusively to the `ClosingManager`.
    validate_error(
        client.close_institution(institution["id"], CLAIMS_AGENT), ERR_UNAUTHORIZED
    )
    # Opening a determination belongs to the `ClaimsAgent`.
    validate_error(
        client.create_determination(
            F.determination_payload(depositor["id"], depositor_version), CLOSING_MANAGER
        ),
        ERR_UNAUTHORIZED,
    )
    # Authorization outranks the determination lookup: 403, never 404.
    validate_error(
        client.certify_determination(UNKNOWN_DETERMINATION_ID, CLAIMS_AGENT),
        ERR_UNAUTHORIZED,
    )
    validate_error(
        client.prepare_determination(
            UNKNOWN_DETERMINATION_ID, F.prepare_payload(), CLAIMS_CERTIFIER
        ),
        ERR_UNAUTHORIZED,
    )
    # Declaring a dividend round belongs to the `ReceivershipTrustee`.
    validate_error(
        client.declare_dividend(
            institution["id"],
            F.dividend_payload("GENERAL_UNSECURED", 1000, institution_version),
            RESOLUTION_ANALYST,
        ),
        ERR_UNAUTHORIZED,
    )
    # The award belongs to the `ResolutionAnalyst`.
    validate_error(
        client.award_least_cost_test(institution["id"], RECEIVERSHIP_TRUSTEE),
        ERR_UNAUTHORIZED,
    )
    # Submitting a bid belongs to the `Bidder`; acknowledging a notice to the `Depositor`.
    validate_error(
        client.create_bid(
            F.bid_payload(
                institution["id"],
                bidder["id"],
                deposit_premium_bps=100,
                data_room_window_start="2026-08-06T09:00:00Z",
                data_room_window_end="2026-08-06T10:00:00Z",
            ),
            make_depositor_headers(depositor["id"]),
        ),
        ERR_UNAUTHORIZED,
    )
    validate_error(
        client.acknowledge_notice(depositor["id"], make_bidder_headers(bidder["id"])),
        ERR_UNAUTHORIZED,
    )
    # Authorization outranks the state precondition the same call would otherwise hit.
    validate_error(client.release_hold(account["id"], CLAIMS_AGENT), ERR_UNAUTHORIZED)
    validate_error(
        client.reschedule_branch_reopening(
            UNKNOWN_BRANCH_ID,
            F.reschedule_payload("2026-08-10T09:00:00Z", "2026-08-10T17:00:00Z"),
            RESOLUTION_ANALYST,
        ),
        ERR_UNAUTHORIZED,
    )

    # No refused call mutated anything.
    after = X.get_institution(client, institution["id"])
    assert_fields_equal(
        after, {"status": "PRE_FAILURE_MONITORING", "version": institution_version}
    )


def test_shared_read_and_clock_operations_are_open_to_all_seven_roles(client):
    """Every read and the clock-advance capability are shared operations, so the same
    institution read succeeds for all seven roles — including the two entity-backed
    roles acting under their own row ids — and a `Depositor` may advance the clock
    even though every business write is closed to that role.

    PRD: "All seven roles may perform every read operation in §4 and may advance the logical clock."

    Design: Corner/rbac/shared_read_and_clock_operations_are_open_to_all_seven_roles
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61082",
        legal_name="Shared Read Bank",
        charter_state="TN",
        book_asset_value_cents=7000000,
        estimated_liquidation_recovery_cents=3000000,
    )
    depositor = X.new_depositor(
        client,
        institution["id"],
        tin_hash="TIN-SH-1",
        legal_name="Wanda Mbeki",
        contact_email="wanda@example.com",
    )
    bidder = X.new_bidder(
        client,
        legal_name="Shared Federal",
        cert_number="62014",
        tier1_capital_ratio_bps=1900,
        camels_composite=2,
    )

    # The five operator roles plus a `Bidder` acting under its own row id: reads are
    # role-blind and every one of them returns the same institution.
    readers = (
        CLOSING_MANAGER,
        CLAIMS_AGENT,
        CLAIMS_CERTIFIER,
        RESOLUTION_ANALYST,
        RECEIVERSHIP_TRUSTEE,
        make_bidder_headers(bidder["id"]),
    )
    for headers in readers:
        row = validate_success(client.get_institution(institution["id"], headers), 200)
        assert row["id"] == institution["id"], row

    # The computed conservation read is equally open to a `Depositor`.
    summary = validate_success(
        client.get_insurance_summary(
            institution["id"], make_depositor_headers(depositor["id"])
        ),
        200,
    )
    assert summary["institution_id"] == institution["id"], summary

    # The clock is a shared capability for every role.
    advanced = validate_success(
        client.set_clock("2026-08-03T11:00:00Z", make_depositor_headers(depositor["id"])),
        200,
    )
    assert advanced["current_utc"] is not None, advanced

    # A `Bidder` may read the depositor roster of an institution it does not own.
    rows, _ = assert_page(
        client.list_depositor_records(
            make_bidder_headers(bidder["id"]),
            params={"institution_id": institution["id"]},
        ),
        expected_total=1,
    )
    assert [row["id"] for row in rows] == [depositor["id"]], rows


def test_entity_backed_identities_are_checked_against_their_own_entity_type(client):
    """A `Bidder` acting under a depositor record's id, and a `Depositor` acting under a
    bidder's id, are both refused on identity: an `X-User-ID` drawn from the wrong
    entity type fails exactly as an id belonging to another peer of the right type
    would, and the identity check is reported ahead of any state precondition.

    PRD: "A mismatch is rejected with `ERR_BIDDER_MISMATCH`. When `X-User-Role` is `Depositor`, `X-User-ID` is the `id` of the acting `DepositorRecord`; a depositor may acknowledge only the notice on its own record, and a mismatch between `X-User-ID` and the depositor record named in the path is rejected with `ERR_DEPOSITOR_MISMATCH`."

    Design: Corner/rbac/entity_backed_identities_are_checked_against_their_own_entity_type
    """
    estate = X.single_account_estate(
        client,
        7000000,
        account_number="IT-0001",
        cert_number="61083",
        legal_name="Identity Type Bank",
        charter_state="AL",
        book_asset_value_cents=10000000,
        estimated_liquidation_recovery_cents=4000000,
        depositor_name="Xiulan Zhou",
    )
    institution_id = estate["institution"]["id"]
    depositor_id = estate["depositor"]["id"]
    X.open_marketing(client, institution_id, "2026-08-12T00:00:00Z")
    bidder = X.new_qualified_bidder(
        client,
        legal_name="Identity Federal",
        cert_number="62015",
        tier1_capital_ratio_bps=2200,
        camels_composite=1,
    )

    bid_payload = F.bid_payload(
        institution_id,
        bidder["id"],
        structure="WHOLE_BANK_PA",
        deposit_premium_bps=150,
        asset_discount_bps=1000,
        asset_retention_pool_cents=0,
        data_room_window_start="2026-08-06T09:00:00Z",
        data_room_window_end="2026-08-06T10:00:00Z",
    )

    # A `Bidder` whose acting id is a depositor record's id owns no bid of that name.
    validate_error(
        client.create_bid(bid_payload, make_bidder_headers(depositor_id)),
        ERR_BIDDER_MISMATCH,
    )
    # The depositor's notice is still `PENDING`, yet the identity mismatch is what is
    # reported: caller identity is settled before the lifecycle guards.
    validate_error(
        client.acknowledge_notice(depositor_id, make_depositor_headers(bidder["id"])),
        ERR_DEPOSITOR_MISMATCH,
    )

    # The same payload succeeds once the acting id is the bidder's own.
    bid = validate_success(
        client.create_bid(bid_payload, make_bidder_headers(bidder["id"])), 201
    )
    assert_fields_equal(bid, {"status": "SUBMITTED", "bidder_id": bidder["id"]})

    rows, _ = assert_page(
        client.list_bids(RESOLUTION_ANALYST, params={"institution_id": institution_id}),
        expected_total=1,
    )
    assert [row["id"] for row in rows] == [bid["id"]], rows
