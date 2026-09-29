"""Corner coverage for the entity layer of the dynamic-discounting contract.

These tests cover the entity layer end to end: creation echoes, retrieval,
list pagination and ordering, entity-specific not-found identifiers, required-field and
type-constraint rejections, declared defaults, server-stamped system fields,
append-only immutability and parent scoping of child rows.

The harness restarts the API server before every test, so each test below
starts from an empty database and builds all of its state through the public
API using ``test_helpers``.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_INVALID_REQUEST, ERR_SUPPLIER_NOT_FOUND
from test_helpers.assertions import (
    assert_append_only_common_fields,
    assert_buyer,
    assert_created_at_ascending,
    assert_invoice,
    assert_pagination_meta,
    assert_program,
    assert_two_decimal_percentage,
    ids_of,
)
from test_helpers.constants import (
    DEFAULT_CLOCK_UTC,
    DEFAULT_CONCENTRATION_CAP_PCT,
    DEFAULT_FUNDING_POLICY,
    DEFAULT_MIN_DAYS_EARLY,
    DEFAULT_RECLASS_APR_THRESHOLD_BPS,
    DEFAULT_RECLASS_DAYS_THRESHOLD,
)
from test_helpers.test_users import (
    PLATFORM_OPS_HEADERS,
    make_buyer_admin_headers,
    make_buyer_treasury_headers,
)


def test_buyer_creation_echoes_declared_and_defaulted_fields():
    """The POST /buyers response itself already carries the server-assigned id
    plus the computed system fields, inside the declared success envelope.

    PRD §3.1: "A freshly registered buyer opens in `status` `ACTIVE` with `credit_used_cents` at 0, and the two buyer states are `ACTIVE` and `SUSPENDED`."
    PRD §2.4: "Most resources additionally carry `updated_at`, refreshed to the current instant on every mutation of that row, and `version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

    Design: Corner/entities/buyer_creation_echoes_declared_and_defaulted_fields
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)

    payload = f.buyer_payload(
        legal_name="Cascade Grocers Holdings",
        tax_id="301112223",
        credit_limit_cents=5_000_000,
        self_funding_enabled=True,
        reclass_days_threshold=45,
        reclass_apr_threshold_bps=1100,
    )
    response = api_client.create_buyer(payload, PLATFORM_OPS_HEADERS)

    buyer = validate_success(response, expected_status=201)
    assert response.json()["response_type"] == "object", (
        "a single created resource is returned with response_type 'object', got {!r}".format(
            response.json()["response_type"]
        )
    )

    # The declared inputs are echoed verbatim and the system fields are stamped.
    assert_buyer(
        buyer,
        legal_name="Cascade Grocers Holdings",
        tax_id="301112223",
        credit_limit_cents=5_000_000,
        self_funding_enabled=True,
        reclass_days_threshold=45,
        reclass_apr_threshold_bps=1100,
        credit_used_cents=0,
        status="ACTIVE",
        version=1,
    )


def test_buyer_program_retrieval_returns_the_stored_configuration():
    """Reading back a DRAFT FIXED_RATE programme returns exactly the stored
    configuration plus the untouched analytics block: the GET recomputes nothing.

    PRD §3.1: "A new programme is persisted in `status` `DRAFT` with every analytics counter at zero — `eligible_invoice_count` and `adopted_invoice_count` at 0, `adoption_rate_pct` at 0.00, `weighted_avg_accepted_apr_bps` at 0 — and `rate_posture` at `DISCOVERY`."
    PRD §3.1: "Under `FIXED_RATE`, `fixed_apr_bps` is mandatory and must lie between 1 and 5000 basis points, every offer on the programme must carry exactly that APR, and there is nothing to negotiate."

    Design: Corner/entities/buyer_program_retrieval_returns_the_stored_configuration
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)

    buyer = fx.new_buyer(legal_name="Fixed Rate Buyer Inc", credit_limit_cents=9_000_000)
    admin = make_buyer_admin_headers(buyer["id"])

    created = fx.new_program(
        buyer["id"],
        name="Fixed 700 Programme",
        program_type="FIXED_RATE",
        fixed_apr_bps=700,
        max_acceptable_apr_bps=1200,
        min_days_early=10,
        concentration_cap_pct=55.50,
        funding_policy="FUNDER_ONLY",
    )

    program = validate_success(api_client.get_program(created["id"], admin))

    assert program["id"] == created["id"], (
        "the read must return the same programme row that was created"
    )
    assert_program(
        program,
        buyer_id=buyer["id"],
        name="Fixed 700 Programme",
        program_type="FIXED_RATE",
        fixed_apr_bps=700,
        max_acceptable_apr_bps=1200,
        min_days_early=10,
        funding_policy="FUNDER_ONLY",
        status="DRAFT",
        eligible_invoice_count=0,
        adopted_invoice_count=0,
        weighted_avg_accepted_apr_bps=0,
        rate_posture="DISCOVERY",
    )
    assert_two_decimal_percentage(program["concentration_cap_pct"], 55.50)
    assert_two_decimal_percentage(program["adoption_rate_pct"], 0.00)


def test_buyer_programs_list_paginates_in_created_at_ascending_order():
    """Three programmes read two at a time come back in creation order with
    total_count counting the whole filtered set, not the page.

    PRD §2.3: "List results are ordered by `created_at` ascending. Ordering never uses `id`."
    PRD §2.3: "For list responses, the envelope's `meta` object carries `limit` and `offset` as applied, plus `total_count` — the number of rows matching the request's filters before pagination — and `has_more`, which is true when rows remain beyond the current page."

    Design: Corner/entities/buyer_programs_list_paginates_in_created_at_ascending_order
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)

    buyer = fx.new_buyer(legal_name="Three Programme Buyer", credit_limit_cents=9_000_000)
    buyer_id = buyer["id"]
    admin = make_buyer_admin_headers(buyer_id)

    # The logical clock is moved between the three creates so that the three
    # created_at instants are strictly ordered and the ascending order the PRD
    # mandates is observable without relying on any tie-break.
    program_a = fx.new_program(
        buyer_id, name="Programme A", program_type="SUPPLIER_NAMED", max_acceptable_apr_bps=1000
    )
    fx.set_clock("2026-08-01T01:00:00Z")
    program_b = fx.new_program(
        buyer_id, name="Programme B", program_type="SUPPLIER_NAMED", max_acceptable_apr_bps=1100
    )
    fx.set_clock("2026-08-01T02:00:00Z")
    program_c = fx.new_program(
        buyer_id, name="Programme C", program_type="SUPPLIER_NAMED", max_acceptable_apr_bps=1200
    )

    first_page_resp = api_client.list_buyer_programs(buyer_id, admin, limit=2, offset=0)
    first_page, first_meta = validate_paginated(first_page_resp)
    assert first_page_resp.json()["response_type"] == "array", (
        "a list endpoint answers with response_type 'array', got {!r}".format(
            first_page_resp.json()["response_type"]
        )
    )
    assert len(first_page) == 2, (
        "limit 2 must return exactly 2 of the 3 programmes, got {}".format(len(first_page))
    )
    assert ids_of(first_page) == [program_a["id"], program_b["id"]], (
        "page one must be the first two programmes by created_at ascending, got {}".format(
            [row["name"] for row in first_page]
        )
    )
    assert_created_at_ascending(first_page)
    assert_pagination_meta(
        first_meta, expected_limit=2, expected_offset=0, expected_total=3, expected_has_more=True
    )

    second_page, second_meta = validate_paginated(
        api_client.list_buyer_programs(buyer_id, admin, limit=2, offset=2)
    )
    assert len(second_page) == 1, (
        "offset 2 leaves exactly 1 remaining programme, got {}".format(len(second_page))
    )
    assert second_page[0]["id"] == program_c["id"], (
        "the tail of the collection is the last-created programme, got {!r}".format(
            second_page[0]["name"]
        )
    )
    assert_pagination_meta(
        second_meta, expected_limit=2, expected_offset=2, expected_total=3, expected_has_more=False
    )


def test_get_unknown_supplier_id_returns_supplier_not_found():
    """A syntactically valid but unknown supplier path id resolves to the
    entity-specific 404 identifier, not a generic 404 and not a shape error.

    PRD §2.7: "**Path-parameter existence** — every path parameter resolves to a live row, validated left to right along the path. The first segment that fails to resolve decides the error identifier, chosen from `ERR_BUYER_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_BANK_ACCOUNT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_FUNDER_NOT_FOUND` and `ERR_EARLY_PAYMENT_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/get_unknown_supplier_id_returns_supplier_not_found
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)

    response = api_client.get_supplier(NON_EXISTENT_UUID, PLATFORM_OPS_HEADERS)

    error = validate_error(response, ERR_SUPPLIER_NOT_FOUND, expected_status=404)
    assert response.json()["response_type"] == "error", (
        "the error envelope carries response_type 'error'"
    )
    assert error["message"].strip(), "data.message must be a non-empty explanation"


def test_payable_file_missing_declared_total_cents_is_rejected():
    """Omitting the mandatory control total is a shape failure reported before
    the programme-state check, so a DRAFT programme still answers 400.

    PRD §3.3: "A programme owner submits an extract from the buyer's accounts-payable system against a programme that must currently be `OPEN`, naming the target `program_id`, a buyer-supplied `filename` between 1 and 200 characters, the control totals `declared_row_count` — at least 1 — and `declared_total_cents` — at least 1 — and a `rows` array."
    PRD §2.7: "**Request shape** — every required body field is present, types are correct, enum values are within range, integers declared non-negative are non-negative, ISO 8601 timestamps parse, and every declared window has its start strictly before its end. This check runs before any database lookup. Otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."

    Design: Corner/entities/payable_file_missing_declared_total_cents_is_rejected
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)

    buyer = fx.new_buyer(legal_name="Shape Check Buyer", credit_limit_cents=9_000_000)
    buyer_id = buyer["id"]
    admin = make_buyer_admin_headers(buyer_id)

    # Deliberately left in DRAFT: priority 3 must outrank the priority-8 check.
    program = fx.new_program(
        buyer_id,
        name="Draft Programme",
        program_type="SUPPLIER_NAMED",
        max_acceptable_apr_bps=1200,
    )
    program_id = program["id"]
    assert program["status"] == "DRAFT", "the programme must still be DRAFT for this probe"

    supplier = fx.new_supplier(legal_name="Shape Check Supplier")

    payload = f.payable_file_payload(
        program_id,
        [
            f.payable_row(
                supplier["id"],
                invoice_number="NT-1",
                approval_date="2026-07-20T00:00:00Z",
                net_due_date="2026-09-30T00:00:00Z",
                line_amount_cents=100_000,
            )
        ],
        filename="AP-NO-TOTAL.csv",
        declared_row_count=1,
    )
    payload.pop("declared_total_cents")
    assert "declared_total_cents" not in payload, "the probe must omit the control total"

    response = api_client.create_payable_file(payload, admin)
    validate_error(response, ERR_INVALID_REQUEST, expected_status=400)

    # Nothing was persisted and no counter moved.
    files, files_meta = validate_paginated(
        api_client.list_program_payable_files(program_id, admin)
    )
    assert files_meta["total_count"] == 0, (
        "a rejected submission persists no ApprovedPayableFile, got total_count {}".format(
            files_meta["total_count"]
        )
    )
    assert files == [], "no payable-file row may exist, got {}".format(files)

    invoices, invoices_meta = validate_paginated(
        api_client.list_invoices(admin, program_id=program_id)
    )
    assert invoices_meta["total_count"] == 0, (
        "no row was priced, so no Invoice may exist, got total_count {}".format(
            invoices_meta["total_count"]
        )
    )

    unchanged = validate_success(api_client.get_program(program_id, admin))
    assert_program(unchanged, status="DRAFT", version=1, eligible_invoice_count=0)


def test_omitted_optional_fields_receive_their_declared_defaults():
    """Creating a buyer and a programme with only the required keys materialises
    the declared defaults rather than nulls or zeroes.

    PRD §3.1: "Three optional inputs shape later behaviour: `self_funding_enabled`, which defaults to true and which, when false, forbids the buyer from ever using its own balance sheet as a funding source; `reclass_days_threshold`, defaulting to 30 days and constrained to zero or greater; and `reclass_apr_threshold_bps`, defaulting to 900 basis points and likewise constrained to zero or greater."
    PRD §3.1: "Three further inputs are optional: `min_days_early`, defaulting to 5 and at least 1, is the minimum number of days early a payment must achieve to be executable; `concentration_cap_pct`, defaulting to 60.00 percent and constrained between 0.01 and 100.00 with two decimals, caps the share of programme face value that one supplier may hold; and `funding_policy`, defaulting to `SELF_THEN_FUNDER`, is one of `SELF_ONLY`, `FUNDER_ONLY` or `SELF_THEN_FUNDER` and determines which balance sheets may pay and in which order."
    PRD §3.1: "Under `SUPPLIER_NAMED`, suppliers propose their own rates and the buyer may negotiate; `fixed_apr_bps` must be null on such a programme."

    Design: Corner/entities/omitted_optional_fields_receive_their_declared_defaults
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)

    buyer_payload = f.buyer_payload(
        legal_name="Minimal Payload Buyer", credit_limit_cents=7_000_000
    )
    assert set(buyer_payload) == {"legal_name", "tax_id", "credit_limit_cents"}, (
        "the buyer probe must carry only the three mandatory keys, got {}".format(
            sorted(buyer_payload)
        )
    )
    buyer = validate_success(
        api_client.create_buyer(buyer_payload, PLATFORM_OPS_HEADERS), expected_status=201
    )
    buyer_id = buyer["id"]
    admin = make_buyer_admin_headers(buyer_id)

    assert_buyer(
        buyer,
        self_funding_enabled=True,
        reclass_days_threshold=DEFAULT_RECLASS_DAYS_THRESHOLD,
        reclass_apr_threshold_bps=DEFAULT_RECLASS_APR_THRESHOLD_BPS,
        credit_used_cents=0,
        status="ACTIVE",
    )

    program_payload = f.minimal_program_payload(buyer_id, name="Minimal Programme")
    assert set(program_payload) == {
        "buyer_id",
        "name",
        "program_type",
        "max_acceptable_apr_bps",
    }, "the programme probe must carry only the four mandatory keys, got {}".format(
        sorted(program_payload)
    )
    program = validate_success(
        api_client.create_program(program_payload, admin), expected_status=201
    )

    assert_program(
        program,
        program_type="SUPPLIER_NAMED",
        max_acceptable_apr_bps=1200,
        min_days_early=DEFAULT_MIN_DAYS_EARLY,
        funding_policy=DEFAULT_FUNDING_POLICY,
        status="DRAFT",
        eligible_invoice_count=0,
        adopted_invoice_count=0,
        rate_posture="DISCOVERY",
    )
    assert_two_decimal_percentage(
        program["concentration_cap_pct"], DEFAULT_CONCENTRATION_CAP_PCT
    )
    assert program["fixed_apr_bps"] is None, (
        "fixed_apr_bps must be null on a SUPPLIER_NAMED programme, got {!r}".format(
            program["fixed_apr_bps"]
        )
    )


def test_invoice_system_fields_are_stamped_from_the_file_not_the_row():
    """The submitted row supplies no linkage and no state: file_id, program_id,
    the resolved supplier_id, the opening status and the face ledger are all
    written by the server.

    PRD §3.3: "Each created invoice records the `file_id` of the ingestion event that produced it, the `program_id` copied from that file, and the `supplier_id` resolved from the row."
    PRD §3.3: "It opens with `face_covered_cents` at 0 — so `remaining_face_cents` equals `face_amount_cents` — with `accepted_apr_bps`, `provisional_discount_cents`, `final_discount_cents` and `discount_true_up_cents` all at 0, and with `dispute_suppressed` false."
    PRD §3.3: "Rows without the flag, or with it set to false, produce invoices in `ELIGIBLE`."

    Design: Corner/entities/invoice_system_fields_are_stamped_from_the_file_not_the_row
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)

    buyer = fx.new_buyer(legal_name="Stamped Fields Buyer", credit_limit_cents=9_000_000)
    buyer_id = buyer["id"]
    admin = make_buyer_admin_headers(buyer_id)
    program = fx.new_open_program(
        buyer_id,
        name="Stamping Programme",
        program_type="SUPPLIER_NAMED",
        max_acceptable_apr_bps=1200,
    )
    program_id = program["id"]
    supplier = fx.new_supplier(legal_name="Stamped Supply Co")
    supplier_id = supplier["id"]

    row = f.payable_row(
        supplier_id,
        invoice_number="ST-1",
        approval_date="2026-07-20T00:00:00Z",
        net_due_date="2026-09-30T00:00:00Z",
        line_amount_cents=100_000,
        tax_rate_bps=0,
    )
    assert set(row) == {
        "invoice_number",
        "approval_date",
        "net_due_date",
        "supplier_id",
        "lines",
    }, "the row carries no linkage and no status of its own, got {}".format(sorted(row))

    payable_file = validate_success(
        api_client.create_payable_file(
            f.payable_file_payload(
                program_id,
                [row],
                filename="AP-STAMP.csv",
                declared_row_count=1,
                declared_total_cents=100_000,
            ),
            admin,
        ),
        expected_status=201,
    )
    file_id = payable_file["id"]
    assert payable_file["ingest_status"] == "ACCEPTED", (
        "a file with no rejected rows is ACCEPTED, got {!r}".format(
            payable_file["ingest_status"]
        )
    )
    assert payable_file["rejected_row_count"] == 0, (
        "no row failed validation, got rejected_row_count {}".format(
            payable_file["rejected_row_count"]
        )
    )
    assert payable_file["accepted_row_count"] == 1, (
        "the single row produced one invoice, got accepted_row_count {}".format(
            payable_file["accepted_row_count"]
        )
    )
    assert payable_file["computed_total_cents"] == 100_000, (
        "computed_total_cents is the accepted face, got {}".format(
            payable_file["computed_total_cents"]
        )
    )

    invoices, meta = validate_paginated(api_client.list_invoices(admin, file_id=file_id))
    assert meta["total_count"] == 1, (
        "exactly one invoice was created by the file, got total_count {}".format(
            meta["total_count"]
        )
    )
    invoice = invoices[0]

    assert_invoice(
        invoice,
        file_id=file_id,
        program_id=program_id,
        supplier_id=supplier_id,
        invoice_number="ST-1",
        status="ELIGIBLE",
        dispute_suppressed=False,
        face_amount_cents=100_000,
        face_covered_cents=0,
        remaining_face_cents=100_000,
        accepted_apr_bps=0,
        provisional_discount_cents=0,
        final_discount_cents=0,
        discount_true_up_cents=0,
        version=1,
    )


def test_invalid_program_enum_and_apr_range_rejected():
    """Three distinct shape failures on POST /buyer-programs all collapse to the
    same 400 identifier and persist nothing.

    PRD §3.1: "Programme creation belongs to the buyer's own programme owner and takes a `buyer_id` naming the funding buyer, a `name` between 1 and 120 characters that suppliers will see, and a `program_type` that is either `SUPPLIER_NAMED` or `FIXED_RATE`."
    PRD §3.1: "Every programme also carries `max_acceptable_apr_bps`, between 200 and 5000 basis points, as the upper bound on any rate named, countered or accepted."
    PRD §3.1: "Under `FIXED_RATE`, `fixed_apr_bps` is mandatory and must lie between 1 and 5000 basis points, every offer on the programme must carry exactly that APR, and there is nothing to negotiate."

    Design: Corner/entities/invalid_program_enum_and_apr_range_rejected
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)

    buyer = fx.new_buyer(legal_name="Constraint Probe Buyer", credit_limit_cents=9_000_000)
    buyer_id = buyer["id"]
    admin = make_buyer_admin_headers(buyer_id)

    out_of_enum = api_client.create_program(
        f.minimal_program_payload(buyer_id, name="Bad Enum", program_type="AUCTION"),
        admin,
    )
    validate_error(out_of_enum, ERR_INVALID_REQUEST, expected_status=400)

    below_floor = api_client.create_program(
        f.minimal_program_payload(
            buyer_id, name="Below Floor", max_acceptable_apr_bps=199
        ),
        admin,
    )
    validate_error(below_floor, ERR_INVALID_REQUEST, expected_status=400)

    fixed_without_rate = f.minimal_program_payload(
        buyer_id, name="Fixed Without Rate", program_type="FIXED_RATE"
    )
    assert "fixed_apr_bps" not in fixed_without_rate, (
        "the third probe must omit the mandatory discriminator field"
    )
    validate_error(
        api_client.create_program(fixed_without_rate, admin),
        ERR_INVALID_REQUEST,
        expected_status=400,
    )

    programs, meta = validate_paginated(api_client.list_buyer_programs(buyer_id, admin))
    assert meta["total_count"] == 0, (
        "all three rejected creates persist nothing, got total_count {}".format(
            meta["total_count"]
        )
    )
    assert programs == [], "no BuyerProgram row may exist, got {}".format(programs)


def test_remittance_advice_row_is_immutable_and_carries_no_version():
    """The single advice minted by execution exposes id and created_at but no
    version and no updated_at, and its money fields are a frozen snapshot that a
    later settlement recomputation does not touch.

    PRD §2.4: "Three resource kinds are deliberately narrower: an approved-payables file, an invoice line, and a remittance advice are immutable records of something that happened, and they carry only `id` and `created_at` — neither `updated_at` nor `version` exists on them at all, and no operation in this specification mutates them after creation."
    PRD §3.8: "It snapshots the invoice's `face_amount_cents` into `gross_face_cents`, the payment's `discount_amount_cents` — the pay-date-basis figure — into `discount_cents`, its `funder_fee_cents` into `fee_cents`, its `net_payment_cents` into `net_paid_cents`, and its `value_date` into the advice's own `value_date`."
    PRD §3.8: "Its `delivery_status` is `SENT` when the supplier had a non-null `remittance_email` at the moment of execution and `BOUNCED` otherwise — so a supplier registered without a remittance address receives no advice, and every advice raised for it is recorded as bounced."

    Design: Corner/entities/remittance_advice_row_is_immutable_and_carries_no_version
    """
    ctx = fx.build_deployed_payment(
        execute_at="2026-08-05T00:00:00Z",
        offered_apr_bps=800,
        requested_pay_date="2026-08-05T00:00:00Z",
        acceptance_deadline="2026-08-20T00:00:00Z",
        face_cents=100_000,
        net_due_date="2026-09-30T00:00:00Z",
        approval_date="2026-07-22T00:00:00Z",
        advance_clock_to="2026-08-02T00:00:00Z",
        supplier_overrides={
            "legal_name": "Advice Supply Ltd",
            "remittance_email": "ar@advice.example",
            "account_last4": "4321",
        },
    )
    treasury = make_buyer_treasury_headers(ctx.buyer_id)

    # Pay-date basis: 2026-09-30 minus the 2026-08-05 execution date is 56 days.
    expected_discount = f.expected_discount_cents(100_000, 800, 56)
    assert expected_discount == 1244, (
        "the pay-date-basis discount on this fixture is 1244 cents, computed {}".format(
            expected_discount
        )
    )

    advices, meta = validate_paginated(
        api_client.list_remittance_advices(ctx.payment_id, treasury)
    )
    assert meta["total_count"] == 1, (
        "execution produces exactly one remittance advice, got total_count {}".format(
            meta["total_count"]
        )
    )
    advice = advices[0]

    # An append-only audit row: id and created_at only.
    assert_append_only_common_fields(advice)

    assert advice["early_payment_id"] == ctx.payment_id, (
        "the advice belongs to the executed payment, got {!r}".format(
            advice["early_payment_id"]
        )
    )
    expected_number = "RA-{}-01".format(ctx.invoice["invoice_number"])
    assert advice["advice_number"] == expected_number, (
        "advice_number is 'RA-' + invoice_number + '-01' for the first advice, "
        "expected {!r}, got {!r}".format(expected_number, advice["advice_number"])
    )
    assert advice["supplier_legal_name"] == "Advice Supply Ltd", (
        "supplier_legal_name is snapshotted, got {!r}".format(
            advice["supplier_legal_name"]
        )
    )
    assert advice["supplier_account_last4"] == "4321", (
        "supplier_account_last4 is the verified account last4, got {!r}".format(
            advice["supplier_account_last4"]
        )
    )
    assert advice["gross_face_cents"] == 100_000, (
        "gross_face_cents snapshots the invoice face, got {}".format(
            advice["gross_face_cents"]
        )
    )
    assert advice["discount_cents"] == 1244, (
        "discount_cents snapshots the pay-date-basis discount 1244, got {}".format(
            advice["discount_cents"]
        )
    )
    assert advice["fee_cents"] == 0, (
        "a BUYER_SELF payment carries no funder fee, got {}".format(advice["fee_cents"])
    )
    assert advice["net_paid_cents"] == 98_756, (
        "net_paid_cents is 100000 - 1244 - 0, got {}".format(advice["net_paid_cents"])
    )
    assert str(advice["value_date"]).startswith("2026-08-07"), (
        "value_date is the 2026-08-05 execution date plus the two-day lag, got {!r}".format(
            advice["value_date"]
        )
    )
    assert advice["delivery_status"] == "SENT", (
        "the supplier has a remittance_email, so delivery_status is SENT, got {!r}".format(
            advice["delivery_status"]
        )
    )

    # Confirming settlement rewrites the payment's discount onto the value-date
    # basis (54 days -> 1200 cents); the advice row must not follow it.
    fx.set_clock("2026-08-07T00:00:00Z")
    settled = fx.confirm_settlement(ctx.payment_id, ctx.buyer_id)
    assert settled["discount_amount_cents"] == 1200, (
        "the value-date-basis discount over 54 days is 1200 cents, got {}".format(
            settled["discount_amount_cents"]
        )
    )

    after, after_meta = validate_paginated(
        api_client.list_remittance_advices(ctx.payment_id, treasury)
    )
    assert after_meta["total_count"] == 1, (
        "settlement mints no second advice, got total_count {}".format(
            after_meta["total_count"]
        )
    )
    unchanged = after[0]
    assert_append_only_common_fields(unchanged)
    assert unchanged["id"] == advice["id"], "the same advice row must be returned"
    assert unchanged["discount_cents"] == 1244, (
        "no operation mutates an advice after creation, so discount_cents stays 1244, "
        "got {}".format(unchanged["discount_cents"])
    )
    assert unchanged["net_paid_cents"] == 98_756, (
        "net_paid_cents stays the execution-time snapshot 98756, got {}".format(
            unchanged["net_paid_cents"]
        )
    )
    assert unchanged["created_at"] == advice["created_at"], (
        "created_at is recorded once and never refreshed"
    )


def test_invoice_lines_are_scoped_to_their_parent_invoice():
    """Two invoices ingested from one file do not share lines: each nested lines
    collection returns only its own parent's rows, in ascending line_no order.

    PRD §2.9: "Nesting in the URL space appears for exactly two reasons — reverse-reachability reads, where a nested collection lists the children of a parent by foreign key, and action sub-paths, where a verb hangs off the resource it acts on."
    PRD §3.3: "A line's `tax_rate_bps` lies between 0 and 3000 basis points, and each line records the `invoice_id` it belongs to plus a `line_no` that is at least 1, unique within the invoice, and contiguous from 1 upward — the line order in the submitted row is the pinned iteration order, and the stored lines are read back in that same order."
    PRD §3.3: "For each line, compute `line_tax_cents` as the line's `line_amount_cents` multiplied by its `tax_rate_bps`, divided by ten thousand, and rounded half up to a whole cent. Then compute `line_total_cents` as `line_amount_cents` plus `line_tax_cents`."

    Design: Corner/entities/invoice_lines_are_scoped_to_their_parent_invoice
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)

    buyer = fx.new_buyer(legal_name="Line Scope Buyer", credit_limit_cents=9_000_000)
    buyer_id = buyer["id"]
    admin = make_buyer_admin_headers(buyer_id)
    program = fx.new_open_program(
        buyer_id,
        name="Line Scope Programme",
        program_type="SUPPLIER_NAMED",
        max_acceptable_apr_bps=1200,
    )
    supplier = fx.new_supplier(legal_name="Line Scope Supply")

    row_a = f.payable_row(
        supplier["id"],
        invoice_number="INV-A",
        approval_date="2026-07-20T00:00:00Z",
        net_due_date="2026-09-30T00:00:00Z",
        lines=[f.invoice_line(1, 33_333, 875), f.invoice_line(2, 66_667, 0)],
    )
    row_b = f.payable_row(
        supplier["id"],
        invoice_number="INV-B",
        approval_date="2026-07-20T00:00:00Z",
        net_due_date="2026-09-30T00:00:00Z",
        lines=[f.invoice_line(1, 50_000, 1000)],
    )
    payable_file = validate_success(
        api_client.create_payable_file(
            f.payable_file_payload(
                program["id"],
                [row_a, row_b],
                filename="AP-LINES.csv",
                declared_row_count=2,
                declared_total_cents=157_917,
            ),
            admin,
        ),
        expected_status=201,
    )

    invoices, meta = validate_paginated(
        api_client.list_invoices(admin, file_id=payable_file["id"])
    )
    assert meta["total_count"] == 2, (
        "the two-row file created two invoices, got total_count {}".format(
            meta["total_count"]
        )
    )
    assert [inv["invoice_number"] for inv in invoices] == ["INV-A", "INV-B"], (
        "the invoices of one file appear in submitted-row order, got {}".format(
            [inv["invoice_number"] for inv in invoices]
        )
    )
    invoice_a, invoice_b = invoices[0], invoices[1]

    # 33333 at 875 bps rounds half up to 2917 cents of tax, so the face of the
    # two-line invoice is 36250 + 66667.
    assert_invoice(invoice_a, face_amount_cents=102_917, status="ELIGIBLE")
    assert_invoice(invoice_b, face_amount_cents=55_000, status="ELIGIBLE")

    lines_a, lines_a_meta = validate_paginated(
        api_client.list_invoice_lines(invoice_a["id"], admin)
    )
    assert lines_a_meta["total_count"] == 2, (
        "INV-A owns exactly its own two lines, got total_count {}".format(
            lines_a_meta["total_count"]
        )
    )
    assert [line["line_no"] for line in lines_a] == [1, 2], (
        "lines are read back in ascending line_no order, got {}".format(
            [line["line_no"] for line in lines_a]
        )
    )
    for line in lines_a:
        assert line["invoice_id"] == invoice_a["id"], (
            "every line of the nested read belongs to INV-A, got invoice_id {!r}".format(
                line["invoice_id"]
            )
        )
        assert_append_only_common_fields(line)
    assert lines_a[0]["line_amount_cents"] == 33_333, (
        "line 1 keeps its submitted amount, got {}".format(lines_a[0]["line_amount_cents"])
    )
    assert lines_a[0]["tax_rate_bps"] == 875, (
        "line 1 keeps its submitted rate, got {}".format(lines_a[0]["tax_rate_bps"])
    )
    assert lines_a[0]["line_tax_cents"] == 2917, (
        "33333 * 875 / 10000 rounds half up to 2917, got {}".format(
            lines_a[0]["line_tax_cents"]
        )
    )
    assert lines_a[0]["line_total_cents"] == 36_250, (
        "line 1 total is 33333 + 2917, got {}".format(lines_a[0]["line_total_cents"])
    )
    assert lines_a[1]["line_tax_cents"] == 0, (
        "a 0 bps line carries no tax, got {}".format(lines_a[1]["line_tax_cents"])
    )
    assert lines_a[1]["line_total_cents"] == 66_667, (
        "line 2 total is its untaxed amount, got {}".format(
            lines_a[1]["line_total_cents"]
        )
    )

    lines_b, lines_b_meta = validate_paginated(
        api_client.list_invoice_lines(invoice_b["id"], admin)
    )
    assert lines_b_meta["total_count"] == 1, (
        "INV-B owns exactly one line and none of INV-A's, got total_count {}".format(
            lines_b_meta["total_count"]
        )
    )
    assert lines_b[0]["invoice_id"] == invoice_b["id"], (
        "the nested read is filtered by invoice_id, not by file, got {!r}".format(
            lines_b[0]["invoice_id"]
        )
    )
    assert lines_b[0]["line_no"] == 1, (
        "line numbering is contiguous from 1 inside each invoice, got {}".format(
            lines_b[0]["line_no"]
        )
    )
    assert lines_b[0]["line_tax_cents"] == 5_000, (
        "50000 * 1000 / 10000 is 5000, got {}".format(lines_b[0]["line_tax_cents"])
    )
    assert lines_b[0]["line_total_cents"] == 55_000, (
        "line total is 50000 + 5000, got {}".format(lines_b[0]["line_total_cents"])
    )


def test_payable_file_row_with_unknown_supplier_is_row_rejected():
    """An unresolvable supplier_id nested inside a payable-file row is a
    row-level rejection recorded on the file, never a 404 on the submission.

    PRD §3.3: "A row whose `supplier_id` matches no supplier is rejected with reason `SUPPLIER_UNKNOWN` — note that this is a row-level rejection and never a 404 on the file as a whole."
    PRD §2.7: "One exception is deliberate: a `supplier_id` nested inside a payable-file row is not covered here, because an unresolvable row-level supplier is a row-level rejection carrying reason `SUPPLIER_UNKNOWN` rather than a 404 on the whole file."
    PRD §3.3: "`accepted_row_count` is the number of rows that produced an invoice; `rejected_row_count` is the number that failed row-level validation and produced none; `computed_total_cents` is the sum of the computed face over the accepted rows, so rejected rows contribute nothing to it; and `rejection_reasons` is an ordered array of objects, each pairing a `row_index` — the zero-based position of the failing row inside the submitted `rows` array — with a `reason` drawn from the five values above, sorted by `row_index` ascending."

    Design: Corner/entities/payable_file_row_with_unknown_supplier_is_row_rejected
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)

    buyer = fx.new_buyer(legal_name="Row Reject Buyer", credit_limit_cents=9_000_000)
    buyer_id = buyer["id"]
    admin = make_buyer_admin_headers(buyer_id)
    program = fx.new_open_program(
        buyer_id,
        name="Row Reject Programme",
        program_type="SUPPLIER_NAMED",
        max_acceptable_apr_bps=1200,
    )
    program_id = program["id"]
    supplier = fx.new_supplier(legal_name="Known Supplier Ltd")

    good_row = f.payable_row(
        supplier["id"],
        invoice_number="OK-1",
        approval_date="2026-07-20T00:00:00Z",
        net_due_date="2026-09-30T00:00:00Z",
        line_amount_cents=100_000,
    )
    bad_row = f.payable_row(
        NON_EXISTENT_UUID,
        invoice_number="BAD-1",
        approval_date="2026-07-20T00:00:00Z",
        net_due_date="2026-09-30T00:00:00Z",
        line_amount_cents=250_000,
    )

    response = api_client.create_payable_file(
        f.payable_file_payload(
            program_id,
            [good_row, bad_row],
            filename="AP-UNKNOWN-SUP.csv",
            declared_row_count=1,
            declared_total_cents=100_000,
        ),
        admin,
    )

    # 201, not the 404 an unresolvable top-level foreign key would produce.
    payable_file = validate_success(response, expected_status=201)
    assert_append_only_common_fields(payable_file)
    assert payable_file["ingest_status"] == "PARTIALLY_ACCEPTED", (
        "one accepted and one rejected row make the file PARTIALLY_ACCEPTED, got {!r}".format(
            payable_file["ingest_status"]
        )
    )
    assert payable_file["accepted_row_count"] == 1, (
        "only the known-supplier row produced an invoice, got accepted_row_count {}".format(
            payable_file["accepted_row_count"]
        )
    )
    assert payable_file["rejected_row_count"] == 1, (
        "the unknown-supplier row produced none, got rejected_row_count {}".format(
            payable_file["rejected_row_count"]
        )
    )
    assert payable_file["computed_total_cents"] == 100_000, (
        "the rejected row contributes nothing to computed_total_cents, got {}".format(
            payable_file["computed_total_cents"]
        )
    )

    reasons = payable_file["rejection_reasons"]
    assert isinstance(reasons, list) and len(reasons) == 1, (
        "exactly one row-level rejection is recorded, got {!r}".format(reasons)
    )
    assert reasons[0]["row_index"] == 1, (
        "row_index is the zero-based position of the failing row, got {}".format(
            reasons[0]["row_index"]
        )
    )
    assert reasons[0]["reason"] == "SUPPLIER_UNKNOWN", (
        "an unresolvable row-level supplier is reported as SUPPLIER_UNKNOWN, got {!r}".format(
            reasons[0]["reason"]
        )
    )

    invoices, meta = validate_paginated(
        api_client.list_invoices(admin, program_id=program_id)
    )
    assert meta["total_count"] == 1, (
        "a rejected row produces no invoice at all, got total_count {}".format(
            meta["total_count"]
        )
    )
    assert_invoice(
        invoices[0],
        invoice_number="OK-1",
        face_amount_cents=100_000,
        supplier_id=supplier["id"],
        status="ELIGIBLE",
    )

    reread = validate_success(api_client.get_program(program_id, admin))
    assert_program(reread, eligible_invoice_count=1, adopted_invoice_count=0)
