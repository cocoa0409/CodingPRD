"""Calculation translations: exclusion input-set filtering, audit penalty
exposure tiers and scopes, and the tiered invoice fee straddle."""
from test_helpers import add_audit_case, add_certified_classification, add_claim, add_claim_line, add_import_entry, add_measure, advance_audit, approve_claim, file_claim, get_invoice_for_claim, onboard_client, record_payment, setup_paid_claim, TEST_USERS, validate_success
from test_helpers.factories import create_import_entry_payload

ADMIN = TEST_USERS["firm_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def test_measure_surcharge_then_exclusion_recomputes_entry(api):
    """PRD 3.3: "For each matching measure it computes a per-measure
    non-drawbackable amount, rounded half up to integer cents individually and
    then summed into the entry's `non_drawbackable_cents`: an `EXCLUSION`
    measure contributes zero; a `SECTION_301` measure contributes zero whenever
    any matching `EXCLUSION` is also present (the exclusion neutralizes it);
    every other matching measure contributes the entered value multiplied by its
    `surcharge_bps` and divided by 10000, rounded half up."

    Design: Corner/calculations/measure_surcharge_then_exclusion_recomputes_entry
    """
    client = onboard_client()
    cls = add_certified_classification(client["id"])
    add_measure(
        hts_code_prefix="6203", measure_type="SECTION_301", surcharge_bps=500,
        effective_from="2026-01-01T00:00:00Z",
    )

    entry = validate_success(
        api.create_import_entry(
            create_import_entry_payload(client["id"], cls["id"]), ANALYST
        ),
        201,
    )
    # round_half_up(500000 * 500 / 10000) = 25000 excluded from drawback.
    assert entry["non_drawbackable_cents"] == 25000
    assert entry["drawback_eligible_duty_cents"] == 57500

    # An overlapping ACTIVE EXCLUSION removes SECTION_301 from the input set.
    add_measure(
        hts_code_prefix="6203", measure_type="EXCLUSION", surcharge_bps=0,
        effective_from="2026-01-01T00:00:00Z",
    )

    entry_after = validate_success(api.get_import_entry(entry["id"], ANALYST))
    assert entry_after["non_drawbackable_cents"] == 0
    assert entry_after["drawback_eligible_duty_cents"] == 82500
    assert entry_after["unclaimed_duty_cents"] == 82500


def test_audit_penalty_negligence_on_scoped_claim(api):
    """PRD 3.8: "`CLOSE_SUSTAINED` — CBP's finding stood — requires a
    `culpability_level` of `NONE`, `NEGLIGENCE`, `GROSS_NEGLIGENCE`, or
    `FRAUD` (its absence is `ERR_INVALID_REQUEST`) and computes the firm's
    `penalty_exposure_cents`: the scope total is the linked claim's
    `paid_duty_cents` when `claim_id` is set and that claim is `PAID`, otherwise
    the sum of `paid_duty_cents` over all of the client's `PAID` claims; the
    applicable rate is 0 basis points for `NONE`, 500 for `NEGLIGENCE`, 2000
    for `GROSS_NEGLIGENCE`, and 10000 for `FRAUD`; and the exposure is the
    scope total multiplied by that rate and divided by 10000, rounded half up
    to integer cents."
    PRD 3.1: "`open_audit_count` is the number of the client's audit cases
    currently in `OPENED`, `EVIDENCE_GATHERING`, or `RESPONSE_FILED`."

    Design: Corner/calculations/audit_penalty_negligence_on_scoped_claim
    """
    ctx = setup_paid_claim(approved_duty_cents=32670)
    case = add_audit_case(
        ctx["client"]["id"],
        claim_id=ctx["claim"]["id"],
        opened_reason="POST_PAYMENT_AUDIT",
        due_date="2026-06-01T00:00:00Z",
    )
    advance_audit(case["id"], "START_EVIDENCE")
    advance_audit(case["id"], "FILE_RESPONSE")

    closed = advance_audit(case["id"], "CLOSE_SUSTAINED", culpability_level="NEGLIGENCE")
    assert closed["status"] == "CLOSED_SUSTAINED"
    # round_half_up(32670 * 500 / 10000) = round_half_up(1633.5) = 1634
    assert closed["penalty_exposure_cents"] == 1634

    client = validate_success(api.get_client(ctx["client"]["id"], ADMIN))
    assert client["open_audit_count"] == 0


def test_audit_penalty_fraud_full_recovery_client_scope(api):
    """PRD 3.8: "`CLOSE_SUSTAINED` — CBP's finding stood — requires a
    `culpability_level` of `NONE`, `NEGLIGENCE`, `GROSS_NEGLIGENCE`, or
    `FRAUD` (its absence is `ERR_INVALID_REQUEST`) and computes the firm's
    `penalty_exposure_cents`: the scope total is the linked claim's
    `paid_duty_cents` when `claim_id` is set and that claim is `PAID`, otherwise
    the sum of `paid_duty_cents` over all of the client's `PAID` claims; the
    applicable rate is 0 basis points for `NONE`, 500 for `NEGLIGENCE`, 2000
    for `GROSS_NEGLIGENCE`, and 10000 for `FRAUD`; and the exposure is the
    scope total multiplied by that rate and divided by 10000, rounded half up
    to integer cents."

    Design: Corner/calculations/audit_penalty_fraud_full_recovery_client_scope
    """
    ctx = setup_paid_claim(approved_duty_cents=32670)
    case = add_audit_case(
        ctx["client"]["id"],
        opened_reason="FOCUSED_ASSESSMENT",
        due_date="2026-06-01T00:00:00Z",
    )
    advance_audit(case["id"], "START_EVIDENCE")
    advance_audit(case["id"], "FILE_RESPONSE")

    closed = advance_audit(case["id"], "CLOSE_SUSTAINED", culpability_level="FRAUD")
    # 10000 bps over the client-scope PAID total 32670 -> full recovery.
    assert closed["penalty_exposure_cents"] == 32670


def test_invoice_tier2_fee_straddling(api):
    """PRD 3.7: "For any recovered amount and fee rate, the tiered fee is: the
    first tier base is the lesser of the recovered amount and 1000000 cents —
    that is, the first ten thousand dollars; the second tier base is whatever
    remains above that threshold, or zero if none does; the first tier's fee is
    the first tier base multiplied by the fee rate in basis points and divided
    by 10000, rounded half up to integer cents; the second tier's fee is the
    second tier base multiplied by the fee rate and by 8000 basis points — the
    rate after a 2000-basis-point marginal discount, i.e. the second tier bills
    at 80% of the agreed rate — divided by 100000000, also rounded half up; and
    the invoice fee is the integer sum of the two rounded tier fees. Each tier
    is rounded independently before summing; rounding only the combined fee is
    forbidden."

    Design: Corner/calculations/invoice_tier2_fee_straddling
    """
    client = onboard_client()
    cls = add_certified_classification(
        client["id"], product_sku="MACH-01", hts_code="8479.89.9599",
        country_of_origin="DE", duty_rate_bps=3000, declared_unit_value_cents=30000,
    )
    entry = add_import_entry(
        client["id"], cls["id"], entry_number="M100",
        line_quantity=100, entered_value_cents=10000000, duty_paid_cents=3000000,
    )
    export = validate_success(
        api.create_export_shipment(
            {
                "client_id": client["id"],
                "export_date": "2026-04-01T00:00:00Z",
                "hts_code": "8479.89.9599",
                "quantity": 100,
                "fob_value_cents": 9000000,
                "dest_country": "CA",
                "substituted_duty_rate_bps": 3000,
            },
            ANALYST,
        ),
        201,
    )
    claim = add_claim(client["id"])
    line = add_claim_line(claim["id"], entry["id"], export["id"], matched_quantity=100)
    # 0.99 * 30000 * 100 = 2970000, so claimed >= approved holds.
    assert line["drawback_amount_cents"] == 2970000

    file_claim(claim["id"])
    approve_claim(claim["id"], 2500000)
    record_payment(claim["id"], 2500000)

    invoice = get_invoice_for_claim(claim["id"])
    # tier1 round_half_up(1000000 * 2500/10000) = 250000
    # tier2 round_half_up(1500000 * 2500 * 8000/100000000) = 300000
    assert invoice["fee_cents"] == 550000, (
        f"marginal tiering must give 550000, not the flat 625000; "
        f"got {invoice['fee_cents']}"
    )
