"""Validation translations: authentication, segregation of duties, temporal
windows, uniqueness, fiscal caps, match bounds, frozen-ledger protections, and
terminal/invalid-state guards."""
from test_helpers import ApiErrorId, add_audit_case, add_certified_classification, add_claim, advance_audit, onboard_client, onboard_client_b, set_clock, setup_approved_claim, setup_draft_claim_with_line, setup_filed_claim, setup_trade_scenario, setup_two_paid_claims, TEST_USERS, make_analyst_headers, make_broker_headers, validate_error, validate_paginated, validate_success
from test_helpers.factories import create_client_payload, create_import_entry_payload

ADMIN = TEST_USERS["firm_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
BROKER = TEST_USERS["broker_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
NO_AUTH = {"Content-Type": "application/json"}


def test_client_create_missing_auth_returns_unauthenticated(api):
    """PRD 2.1: "A request that omits either header, or that presents a role
    outside this enumeration, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD 2.7: "Authentication comes first: missing or malformed headers surface
    `ERR_UNAUTHENTICATED` before anything else is examined."

    Design: Corner/validations/client_create_missing_auth_returns_unauthenticated
    """
    res = api.create_client(create_client_payload(), NO_AUTH)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_segregation_claim_filer_equals_preparer(api):
    """PRD 2.1: "Filing a drawback claim must be performed by a different
    `X-User-ID` than the one captured as the claim's `prepared_by_user_id`, and
    certifying a classification must be performed by a different `X-User-ID`
    than the one captured as the classification's `submitted_by_user_id`. Either
    violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/segregation_claim_filer_equals_preparer
    """
    ctx = setup_draft_claim_with_line(matched_quantity=40)

    # File with the LicensedBroker ROLE but the SAME X-User-ID that prepared.
    res = api.file_claim(ctx["claim"]["id"], make_broker_headers("u_an1"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    claim = validate_success(api.get_claim(ctx["claim"]["id"], ANALYST))
    assert claim["status"] == "DRAFT"


def test_segregation_classification_certifier_equals_submitter(api):
    """PRD 2.1: "Filing a drawback claim must be performed by a different
    `X-User-ID` than the one captured as the claim's `prepared_by_user_id`, and
    certifying a classification must be performed by a different `X-User-ID`
    than the one captured as the classification's `submitted_by_user_id`. Either
    violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 3.2: "A `decision` of `CERTIFY` moves it to `CERTIFIED` and stamps
    `certified_by_user_id` — but only if the certifying broker is not the same
    individual who submitted it; a self-certification is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/segregation_classification_certifier_equals_submitter
    """
    client = onboard_client()
    cls = validate_success(
        api.create_classification(
            {
                "client_id": client["id"],
                "product_sku": "PANT-01",
                "hts_code": "6203.42.4011",
                "country_of_origin": "CN",
                "duty_rate_bps": 1650,
                "declared_unit_value_cents": 5000,
            },
            make_analyst_headers("u_an1"),
        ),
        201,
    )
    validate_success(api.submit_classification(cls["id"], make_analyst_headers("u_an1")))

    # Same X-User-ID as the submitter, presented under the broker role.
    res = api.review_classification(
        cls["id"], {"decision": "CERTIFY"}, make_broker_headers("u_an1")
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    certified = validate_success(
        api.review_classification(
            cls["id"], {"decision": "CERTIFY"}, make_broker_headers("u_br2")
        )
    )
    assert certified["status"] == "CERTIFIED"


def test_claim_create_inverted_period_rejected(api):
    """PRD 3.4: "The period is a closed interval — both bounds inclusive — and
    `period_end` must be on or after `period_start` (`ERR_INVALID_WINDOW`
    otherwise)."

    Design: Corner/validations/claim_create_inverted_period_rejected
    """
    client = onboard_client()
    res = api.create_claim(
        {
            "client_id": client["id"],
            "claim_type": "DIRECT_IDENTIFICATION",
            "period_start": "2026-06-30T00:00:00Z",
            "period_end": "2026-01-01T00:00:00Z",
        },
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_WINDOW)


def test_duplicate_entry_number_rejected(api):
    """PRD 3.3: "the CBP `entry_number`, which must be unique within the client
    (`ERR_DUPLICATE_ENTRY_NUMBER` on collision)"

    Design: Corner/validations/duplicate_entry_number_rejected
    """
    client_a = onboard_client()
    client_b = onboard_client_b()
    cls_a = add_certified_classification(client_a["id"])
    cls_b = add_certified_classification(client_b["id"])

    validate_success(
        api.create_import_entry(
            create_import_entry_payload(client_a["id"], cls_a["id"]), ANALYST
        ),
        201,
    )

    # Same client, same entry_number: rejected.
    res = api.create_import_entry(
        create_import_entry_payload(
            client_a["id"], cls_a["id"],
            entry_date="2026-03-11T00:00:00Z", line_quantity=50,
            entered_value_cents=250000, duty_paid_cents=41250,
        ),
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_ENTRY_NUMBER)

    # Different client, same entry_number: accepted.
    entry_b = validate_success(
        api.create_import_entry(
            create_import_entry_payload(
                client_b["id"], cls_b["id"],
                entry_date="2026-03-11T00:00:00Z", line_quantity=50,
                entered_value_cents=250000, duty_paid_cents=41250,
            ),
            ANALYST,
        ),
        201,
    )
    assert entry_b["entry_number"] == "E100"


def test_approved_exceeds_claimed_rejected(api):
    """PRD 3.5: "An `outcome` of `APPROVED` requires `approved_duty_cents` to be
    present and no greater than the frozen `claimed_duty_cents` — CBP may allow
    less than was claimed but never more, and an excess is
    `ERR_APPROVED_EXCEEDS_CLAIMED`."

    Design: Corner/validations/approved_exceeds_claimed_rejected
    """
    ctx = setup_filed_claim(matched_quantity=40)

    res = api.review_claim(
        ctx["claim"]["id"],
        {"outcome": "APPROVED", "approved_duty_cents": 32671},
        BROKER,
    )
    validate_error(res, ApiErrorId.ERR_APPROVED_EXCEEDS_CLAIMED)

    claim = validate_success(api.get_claim(ctx["claim"]["id"], ANALYST))
    assert claim["status"] == "FILED", "the rejected review leaves the claim FILED"

    # The exact claimed amount is the accepted boundary.
    approved = validate_success(
        api.review_claim(
            ctx["claim"]["id"],
            {"outcome": "APPROVED", "approved_duty_cents": 32670},
            BROKER,
        )
    )
    assert approved["status"] == "APPROVED"


def test_paid_amount_mismatch_rejected(api):
    """PRD 3.5: "The `paid_duty_cents` supplied must equal `approved_duty_cents`
    exactly — partial recoveries are not modeled, and a mismatch is
    `ERR_PAID_AMOUNT_MISMATCH`."

    Design: Corner/validations/paid_amount_mismatch_rejected
    """
    ctx = setup_approved_claim(approved_duty_cents=32670)

    res = api.record_payment(ctx["claim"]["id"], {"paid_duty_cents": 32669}, ADMIN)
    validate_error(res, ApiErrorId.ERR_PAID_AMOUNT_MISMATCH)

    claim = validate_success(api.get_claim(ctx["claim"]["id"], ANALYST))
    assert claim["status"] == "APPROVED"

    _, meta = validate_paginated(
        api.list_invoices(ADMIN, params={"claim_id": ctx["claim"]["id"]})
    )
    assert meta["total_count"] == 0, "no invoice may be created by the mismatch"


def test_match_quantity_exceeds_remaining_rejected(api):
    """PRD 3.4: "Quantity is bounded by availability on both sides:
    `matched_quantity` may not exceed the entry's remaining unmatched units or
    the shipment's remaining unmatched units, and a violation is
    `ERR_MATCH_QUANTITY_EXCEEDED`."

    Design: Corner/validations/match_quantity_exceeds_remaining_rejected
    """
    ctx = setup_trade_scenario(export_overrides={"quantity": 200})
    claim = add_claim(ctx["client"]["id"])

    res = api.add_claim_line(
        claim["id"],
        {
            "import_entry_id": ctx["entry"]["id"],
            "export_shipment_id": ctx["export"]["id"],
            "matched_quantity": 101,
        },
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_MATCH_QUANTITY_EXCEEDED)

    line = validate_success(
        api.add_claim_line(
            claim["id"],
            {
                "import_entry_id": ctx["entry"]["id"],
                "export_shipment_id": ctx["export"]["id"],
                "matched_quantity": 100,
            },
            ANALYST,
        ),
        201,
    )
    assert line["drawback_amount_cents"] == 81675
    entry = validate_success(api.get_import_entry(ctx["entry"]["id"], ANALYST))
    assert entry["status"] == "MATCHED"


def test_direct_match_incompatible_hts_rejected(api):
    """PRD 3.4: "Under `DIRECT_IDENTIFICATION`, the exported article must be the
    very same kind of merchandise that was imported, so the shipment's
    `hts_code` must equal the entry's `hts_code` — a mismatch is
    `ERR_MATCH_INCOMPATIBLE`. Under `SUBSTITUTION`, different but substitutable
    merchandise may be matched, and no such HTS equality is required."

    Design: Corner/validations/direct_match_incompatible_hts_rejected
    """
    ctx = setup_trade_scenario(
        export_overrides={"hts_code": "6109.10.0010"}
    )
    claim_direct = add_claim(ctx["client"]["id"], claim_type="DIRECT_IDENTIFICATION")
    claim_sub = add_claim(ctx["client"]["id"], claim_type="SUBSTITUTION")

    res = api.add_claim_line(
        claim_direct["id"],
        {
            "import_entry_id": ctx["entry"]["id"],
            "export_shipment_id": ctx["export"]["id"],
            "matched_quantity": 40,
        },
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_MATCH_INCOMPATIBLE)

    # The identical pair is accepted under SUBSTITUTION: substitute unit duty
    # 1650 * 480000 / (10000 * 100) = 792, min(825, 792) = 792,
    # round_half_up(0.99 * 792 * 40) = 31363.
    line = validate_success(
        api.add_claim_line(
            claim_sub["id"],
            {
                "import_entry_id": ctx["entry"]["id"],
                "export_shipment_id": ctx["export"]["id"],
                "matched_quantity": 40,
            },
            ANALYST,
        ),
        201,
    )
    assert line["drawback_amount_cents"] == 31363


def test_substitution_line_beyond_fob_pool_rejected(api):
    """PRD 3.4: "Substitution lines carry one further guard: the raw refund must
    not exceed the shipment's current `value_pool_remaining_cents`, the FOB pool
    cap, and an overrun is rejected with `ERR_EXPORT_VALUE_POOL_EXCEEDED`."

    Design: Corner/validations/substitution_line_beyond_fob_pool_rejected
    """
    ctx = setup_trade_scenario(
        export_overrides={
            "quantity": 100,
            "fob_value_cents": 70000,
            "substituted_duty_rate_bps": 11000,
        }
    )
    claim = add_claim(ctx["client"]["id"], claim_type="SUBSTITUTION")

    # substitute unit = 11000*70000/(10000*100) = 770 < import unit 825, so the
    # raw refund is 0.99 * 770 * 100 = 76230 against a 70000-cent pool:
    # rejected, not clamped.
    res = api.add_claim_line(
        claim["id"],
        {
            "import_entry_id": ctx["entry"]["id"],
            "export_shipment_id": ctx["export"]["id"],
            "matched_quantity": 100,
        },
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_EXPORT_VALUE_POOL_EXCEEDED)

    export = validate_success(api.get_export_shipment(ctx["export"]["id"], ANALYST))
    assert export["value_pool_remaining_cents"] == 70000, "the pool is unchanged"


def test_measure_blocked_by_active_claim_lines(api):
    """PRD 3.3: "A new measure is also rejected with
    `ERR_MEASURE_BLOCKED_BY_CLAIM_LINES` if its window would reduce the eligible
    duty of any entry already referenced by `ACTIVE` claim lines."

    Design: Corner/validations/measure_blocked_by_active_claim_lines
    """
    ctx = setup_draft_claim_with_line(matched_quantity=40)

    res = api.create_tariff_measure(
        {
            "hts_code_prefix": "6203",
            "measure_type": "SECTION_301",
            "surcharge_bps": 500,
            "effective_from": "2026-01-01T00:00:00Z",
        },
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_MEASURE_BLOCKED_BY_CLAIM_LINES)

    # A measure on a disjoint prefix touches no claimed entry: accepted.
    measure = validate_success(
        api.create_tariff_measure(
            {
                "hts_code_prefix": "8479",
                "measure_type": "SECTION_301",
                "surcharge_bps": 500,
                "effective_from": "2026-01-01T00:00:00Z",
            },
            ADMIN,
        ),
        201,
    )
    assert measure["status"] == "ACTIVE"


def test_entry_correction_locked_by_filed_claim(api):
    """PRD 2.9: "An import entry referenced by any `ACTIVE` claim line belonging
    to a claim that is not in `DRAFT` cannot be corrected; the attempt is
    rejected with `ERR_ENTRY_LOCKED_BY_FILED_CLAIM`."

    Design: Corner/validations/entry_correction_locked_by_filed_claim
    """
    ctx = setup_filed_claim(matched_quantity=40)

    entry = validate_success(api.get_import_entry(ctx["entry"]["id"], ANALYST))
    res = api.correct_import_entry(
        ctx["entry"]["id"],
        {"duty_paid_cents": 41250,
         "expected_import_entry_version": entry["version"]},
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_ENTRY_LOCKED_BY_FILED_CLAIM)

    entry_after = validate_success(api.get_import_entry(ctx["entry"]["id"], ANALYST))
    assert entry_after["duty_paid_cents"] == 82500, "the locked entry is unchanged"


def test_audit_response_past_due_boundary(api):
    """PRD 3.8: "From `EVIDENCE_GATHERING`, `FILE_RESPONSE` moves it to
    `RESPONSE_FILED` — but only if the logical clock has not passed `due_date`;
    the deadline is inclusive, so a response at the exact due second is
    permitted, and a later attempt is `ERR_RESPONSE_PAST_DUE`."

    Design: Corner/validations/audit_response_past_due_boundary
    """
    client = onboard_client()
    case = add_audit_case(client["id"], due_date="2026-06-01T00:00:00Z")
    advance_audit(case["id"], "START_EVIDENCE")

    # At the exact due second: permitted.
    set_clock("2026-06-01T00:00:00Z")
    case = advance_audit(case["id"], "FILE_RESPONSE")
    assert case["status"] == "RESPONSE_FILED"

    # Reopen, then one second past the due date: rejected.
    advance_audit(case["id"], "REQUEST_MORE")
    set_clock("2026-06-01T00:00:01Z")
    res = api.advance_audit(case["id"], {"action": "FILE_RESPONSE"}, COMPLIANCE)
    validate_error(res, ApiErrorId.ERR_RESPONSE_PAST_DUE)

    case_after = validate_success(api.get_audit_case(case["id"], COMPLIANCE))
    assert case_after["status"] == "EVIDENCE_GATHERING"


def test_measure_invalid_window_rejected(api):
    """PRD 3.3: "Creating a measure requires `effective_to`, when present, to be
    strictly after `effective_from` (`ERR_INVALID_WINDOW` otherwise)."

    Design: Corner/validations/measure_invalid_window_rejected
    """
    res = api.create_tariff_measure(
        {
            "hts_code_prefix": "6203",
            "measure_type": "AD_CVD",
            "surcharge_bps": 5000,
            "effective_from": "2026-06-01T00:00:00Z",
            "effective_to": "2026-06-01T00:00:00Z",
        },
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_WINDOW)


def test_line_add_to_filed_claim_returns_invalid_state(api):
    """PRD 3.4: "The substance of a claim is its `ClaimLine` records, each
    matching some units of one import entry against one export shipment. Adding
    a line to a `DRAFT` claim requires `import_entry_id`, `export_shipment_id`,
    and a positive `matched_quantity`, and both referenced resources must belong
    to the same client as the claim (`ERR_CROSS_CLIENT_REFERENCE` otherwise)."
    PRD 3.4: "Filing freezes everything."

    Design: Corner/validations/line_add_to_filed_claim_returns_invalid_state
    """
    ctx = setup_filed_claim(matched_quantity=40)

    res = api.add_claim_line(
        ctx["claim"]["id"],
        {
            "import_entry_id": ctx["entry"]["id"],
            "export_shipment_id": ctx["export"]["id"],
            "matched_quantity": 10,
        },
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_invoice_void_with_payments_rejected(api):
    """PRD 3.7: "A `ComplianceManager` may void an invoice, but only while no
    payment has ever been recorded against it — `amount_paid_cents` must be
    zero, otherwise `ERR_INVOICE_HAS_PAYMENTS` — moving it from `ISSUED` to the
    terminal `VOID`."

    Design: Corner/validations/invoice_void_with_payments_rejected
    """
    ctx = setup_two_paid_claims()
    inv_a = ctx["invoice_a"]
    inv_b = ctx["invoice_b"]

    validate_success(api.pay_invoice(inv_a["id"], {"amount_cents": 1000}, ADMIN))

    res = api.void_invoice(inv_a["id"], COMPLIANCE)
    validate_error(res, ApiErrorId.ERR_INVOICE_HAS_PAYMENTS)

    voided = validate_success(api.void_invoice(inv_b["id"], COMPLIANCE))
    assert voided["status"] == "VOID"
