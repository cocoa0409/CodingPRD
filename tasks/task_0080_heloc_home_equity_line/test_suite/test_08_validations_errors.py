"""Corner coverage: validation violation->error paths and the error catalogue entries
not owned by a difficulty instance (Queue B: validations, errors)."""
from test_helpers import (
    validate_success,
    validate_error,
    setup_active_line,
    setup_application_line,
    book_draw,
    set_clock,
    create_property,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    make_loan_servicer_headers,
)

OFFICER = TEST_USERS["loan_officer_headers"]
SERVICER = TEST_USERS["loan_servicer_headers"]


# --- validations section ----------------------------------------------------

def test_overpayment_exceeds_total_owed_rejected(api):
    """PRD §3.6: "If any amount remains after principal, the payment is an overpayment
    and is rejected with ERR_OVERPAYMENT (HTTP 422) — the payment is not booked.
    Equivalently, the remittance must not exceed the sum of outstanding fees, accrued
    interest, and current principal."

    Draw 200000, clock 2026-01-31, APR 1000 -> accrued 1644, owed 201644; a 201645
    payment is rejected and the balance is unchanged.

    Design: Corner/validations/overpayment_exceeds_total_owed_rejected
    """
    ctx = setup_active_line(heloc_overrides={"credit_limit_cents": 50000000})
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 200000)
    set_clock("2026-01-31T00:00:00Z")
    resp = api.create_payment(hl_id, {"amount_cents": 201645}, SERVICER)
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)
    heloc = validate_success(api.get_heloc(hl_id, SERVICER))
    assert heloc["current_balance_cents"] == 200000, "balance must be unchanged after rejected overpayment"


def test_reversal_underflow_rejected(api):
    """PRD §3.4: "It additionally requires that the line's current_balance_cents be at
    least the draw's amount_cents, so that the reversal cannot drive principal below
    zero; a reversal that would underflow the balance is rejected with
    ERR_REVERSAL_UNDERFLOW (HTTP 422)."

    Draws 200000 + 100000 (balance 300000), pay 250000 principal -> balance 50000;
    reversing the 200000 draw (> 50000) underflows.

    Design: Corner/validations/reversal_underflow_rejected
    """
    ctx = setup_active_line(
        heloc_overrides={"credit_limit_cents": 50000000, "margin_bps": 0},
        index_rate_bps=0,
    )
    hl_id = ctx["heloc"]["id"]
    draw_a = book_draw(hl_id, 200000)
    book_draw(hl_id, 100000)
    validate_success(api.create_payment(hl_id, {"amount_cents": 250000}, SERVICER), 201)
    resp = api.reverse_draw(hl_id, draw_a["id"], SERVICER)
    validate_error(resp, ApiErrorId.ERR_REVERSAL_UNDERFLOW)


def test_activate_without_active_index_rejected(api):
    """PRD §3.3: "An active, non-superseded PRIME index rate must exist, otherwise the
    request fails with ERR_NO_ACTIVE_INDEX (HTTP 409)."

    Design: Corner/validations/activate_without_active_index_rejected
    """
    ctx = setup_application_line(publish_index_rate=False)
    resp = api.activate_heloc(ctx["heloc"]["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_INDEX)


def test_activate_incomplete_covenant_set_rejected(api):
    """PRD §3.3: "At least one covenant of each of the three types — MAX_CLTV, MIN_DSCR,
    and MAX_DELINQUENCY_DAYS — must already be attached to the line, otherwise the request
    fails with ERR_COVENANT_SET_INCOMPLETE (HTTP 409)."

    Only MAX_CLTV and MIN_DSCR attached (missing MAX_DELINQUENCY_DAYS).

    Design: Corner/validations/activate_incomplete_covenant_set_rejected
    """
    ctx = setup_application_line(attach_covenants=False)
    hl_id = ctx["heloc"]["id"]
    validate_success(api.create_covenant(hl_id, {"covenant_type": "MAX_CLTV", "threshold_value": 9900}, OFFICER), 201)
    validate_success(api.create_covenant(hl_id, {"covenant_type": "MIN_DSCR", "threshold_value": 100}, OFFICER), 201)
    resp = api.activate_heloc(hl_id, OFFICER)
    validate_error(resp, ApiErrorId.ERR_COVENANT_SET_INCOMPLETE)


def test_close_with_outstanding_balance_rejected(api):
    """PRD §3.11: "Closure requires that the line be in DRAW or REPAYMENT, and that both
    current_balance_cents and accrued_interest_cents be exactly 0; a close attempt while
    either is non-zero is rejected with ERR_BALANCE_NOT_ZERO (HTTP 409)."

    Design: Corner/validations/close_with_outstanding_balance_rejected
    """
    ctx = setup_active_line(
        clock="2026-06-01T00:00:00Z",
        index_rate_bps=0,
        index_effective="2026-01-01T00:00:00Z",
        heloc_overrides={"credit_limit_cents": 50000000, "margin_bps": 0},
    )
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 200000)
    resp = api.close_heloc(hl_id, SERVICER)
    validate_error(resp, ApiErrorId.ERR_BALANCE_NOT_ZERO)


def test_heloc_create_bad_borrower_reference_rejected(api):
    """PRD §2.6: "When a create operation names another resource by id in its body — a
    borrower or property on HELOC creation ... — and that reference does not resolve to
    an existing row, the request is rejected with ERR_REFERENCE_NOT_FOUND (HTTP 404)."

    Design: Corner/validations/reference_not_found_on_heloc_create_bad_borrower
    """
    prop = create_property()
    resp = api.create_heloc(
        {
            "borrower_id": NON_EXISTENT_UUID,
            "property_id": prop["id"],
            "lien_position": "FIRST",
            "credit_limit_cents": 50000000,
            "margin_bps": 150,
            "rate_ceiling_bps": 1800,
            "origination_date": "2026-01-01T00:00:00Z",
        },
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


# --- errors section (non-stub instances) ------------------------------------

def test_declare_default_satisfied_covenant_rejected(api):
    """PRD §3.10: "The referenced covenant must currently be BREACHED and must belong to
    this line; otherwise the declaration is rejected with ERR_NO_BREACHED_COVENANT
    (HTTP 409)."

    A distinct servicer (passing segregation) declares default citing a SATISFIED
    covenant -> ERR_NO_BREACHED_COVENANT.

    Design: Corner/errors/error_no_breached_covenant_on_declare_default
    """
    ctx = setup_active_line(activate_user_id="officer-A")
    hl_id = ctx["heloc"]["id"]
    cov_id = ctx["covenants"]["MAX_CLTV"]["id"]
    servicer_b = make_loan_servicer_headers("servicer-B")
    resp = api.declare_default(hl_id, {"covenant_id": cov_id}, servicer_b)
    validate_error(resp, ApiErrorId.ERR_NO_BREACHED_COVENANT)


def test_index_supersede_stale_version_rejected(api):
    """PRD §2.7: "If expected_indexrate_version does not match that IndexRate's current
    version — because another servicer has already published a fresher PRIME value and
    advanced the row's version since the client last read it — the supersede is rejected
    with ERR_STALE_VERSION (HTTP 412)."

    First supersede advances the row's version; a second supersede carrying the original
    (now stale) version is rejected.

    Design: Corner/errors/error_stale_version_on_index_supersede
    """
    set_clock("2026-01-01T00:00:00Z")
    idx = validate_success(
        api.create_index_rate(
            {"index_name": "PRIME", "rate_bps": 850, "effective_date": "2026-01-01T00:00:00Z"},
            SERVICER,
        ),
        201,
    )
    stale_version = idx["version"]
    validate_success(
        api.supersede_index_rate(
            idx["id"],
            {"rate_bps": 900, "effective_date": "2026-02-01T00:00:00Z", "expected_indexrate_version": stale_version},
            SERVICER,
        ),
        201,
    )
    resp = api.supersede_index_rate(
        idx["id"],
        {"rate_bps": 950, "effective_date": "2026-03-01T00:00:00Z", "expected_indexrate_version": stale_version},
        SERVICER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_draw_one_cent_over_available_insufficient_credit(api):
    """PRD §3.4: "The requested amount must not exceed the line's available_credit_cents;
    an over-limit advance is rejected with ERR_INSUFFICIENT_CREDIT (HTTP 422)."

    A draw of 50000001 against available 50000000 (one cent over) is rejected.

    Design: Corner/errors/error_insufficient_credit_on_draw
    """
    ctx = setup_active_line(heloc_overrides={"credit_limit_cents": 50000000})
    hl_id = ctx["heloc"]["id"]
    resp = api.create_draw(hl_id, {"amount_cents": 50000001}, SERVICER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT)
