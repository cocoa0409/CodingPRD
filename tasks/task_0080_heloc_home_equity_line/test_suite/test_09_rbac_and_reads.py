"""Corner coverage: RBAC role gating, reverse-reachability reads, OCC success,
derived-field reconciliation, and immediate consistency (Queue B: rbac, endpoints,
cross_cutting_complexity_layers, consistency_model)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    setup_active_line,
    create_borrower,
    create_property,
    set_clock,
    book_draw,
    ApiErrorId,
    TEST_USERS,
    make_borrower_headers,
    make_loan_servicer_headers,
)
from prd_bench_local_runner.testing import build_user_headers

OFFICER = TEST_USERS["loan_officer_headers"]
SERVICER = TEST_USERS["loan_servicer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# --- rbac section -----------------------------------------------------------

def test_borrower_cannot_create_heloc(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE
    (HTTP 403)."
    PRD §4: POST /helocs is authorized for LoanOfficer only.

    Design: Corner/rbac/borrower_cannot_create_heloc
    """
    bor = create_borrower()
    prop = create_property()
    resp = api.create_heloc(
        {
            "borrower_id": bor["id"],
            "property_id": prop["id"],
            "lien_position": "FIRST",
            "credit_limit_cents": 50000000,
            "margin_bps": 150,
            "rate_ceiling_bps": 1800,
            "origination_date": "2026-01-01T00:00:00Z",
        },
        make_borrower_headers(bor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_loan_officer_cannot_book_draw(api):
    """PRD §2.1: "the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."
    PRD §4: POST /helocs/{id}/draws is authorized for LoanServicer only.

    Design: Corner/rbac/loan_officer_cannot_book_draw
    """
    ctx = setup_active_line()
    resp = api.create_draw(ctx["heloc"]["id"], {"amount_cents": 100000}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or X-User-Role does not name a known role,
    the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_helocs({})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# --- endpoints section ------------------------------------------------------

def test_list_draws_by_heloc(api):
    """PRD §4: "GET /helocs/{id}/draws — List draws for a HELOC (filter by status)."
    PRD §3.4: "Draws of a line may be listed and filtered by status."

    Two BOOKED draws are returned as a Draw[] of length 2.

    Design: Corner/endpoints/list_draws_by_heloc_reverse_reachability
    """
    ctx = setup_active_line()
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 150000)
    book_draw(hl_id, 250000)
    data, meta = validate_paginated(api.list_draws(hl_id, SERVICER, params={"status": "BOOKED"}))
    assert len(data) == 2
    assert meta["total_count"] == 2


def test_default_events_listed_by_covenant(api):
    """PRD §3.10: "Default events ... may also be listed by the covenant that triggered
    them."
    PRD §4: "GET /covenants/{id}/default-events — List default events triggered by this
    covenant."

    After a default declared on a breached MAX_CLTV covenant, the covenant's
    default-events list has length 1.

    Design: Corner/endpoints/default_events_reverse_reachability_by_covenant
    """
    ctx = setup_active_line(
        cltv_threshold=8500,
        dscr_threshold=100,
        delinquency_threshold=60,
        heloc_overrides={"credit_limit_cents": 95000000},
        activate_user_id="officer-A",
    )
    hl_id = ctx["heloc"]["id"]
    cov_id = ctx["covenants"]["MAX_CLTV"]["id"]
    book_draw(hl_id, 90000000)
    validate_success(api.evaluate_covenant(hl_id, cov_id, SERVICER))
    servicer_b = make_loan_servicer_headers("servicer-B")
    validate_success(api.declare_default(hl_id, {"covenant_id": cov_id}, servicer_b))
    data, meta = validate_paginated(api.list_covenant_default_events(cov_id, AUDITOR))
    assert len(data) == 1
    assert meta["total_count"] == 1


# --- cross_cutting_complexity_layers section --------------------------------

def test_occ_correct_version_supersede_succeeds(api):
    """PRD §2.7: "A request to supersede an IndexRate must carry expected_indexrate_version,
    a non-optional field holding the client's last observed version of the target
    IndexRate."
    PRD §3.2: "The supersede increments the superseded row's version by 1."
    PRD §3.2: "On publication of a new value, any prior index rate with the same
    index_name and an earlier effective_date is marked superseded."

    A supersede with the matching version succeeds, advances the row's version to 2, and
    marks it superseded.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_supersede_succeeds
    """
    set_clock("2026-01-01T00:00:00Z")
    idx = validate_success(
        api.create_index_rate(
            {"index_name": "PRIME", "rate_bps": 850, "effective_date": "2026-01-01T00:00:00Z"},
            SERVICER,
        ),
        201,
    )
    validate_success(
        api.supersede_index_rate(
            idx["id"],
            {"rate_bps": 900, "effective_date": "2026-02-01T00:00:00Z", "expected_indexrate_version": idx["version"]},
            SERVICER,
        ),
        201,
    )
    after = validate_success(api.get_index_rate(idx["id"], SERVICER))
    assert after["version"] == 2, f"superseded row version must advance to 2, got {after['version']}"
    assert after["superseded"] is True


def test_available_credit_reconciled_after_draw_and_payment(api):
    """PRD §3.4: "Available credit is always recomputed as the credit limit minus the
    current balance, floored at 0."
    PRD §3.6: "Posting a payment ... reduces accrued_interest_cents and
    current_balance_cents by their respective buckets, recomputes available_credit_cents ..."

    Draw 300000 then a 100000 principal payment (APR 0) -> balance 200000, available
    49800000 (50000000 - 200000).

    Design: Corner/cross_cutting_complexity_layers/derived_available_credit_reconciled_after_draw_and_payment
    """
    ctx = setup_active_line(
        heloc_overrides={"credit_limit_cents": 50000000, "margin_bps": 0},
        index_rate_bps=0,
    )
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 300000)
    validate_success(api.create_payment(hl_id, {"amount_cents": 100000}, SERVICER), 201)
    heloc = validate_success(api.get_heloc(hl_id, SERVICER))
    assert heloc["current_balance_cents"] == 200000
    assert heloc["available_credit_cents"] == 49800000


# --- consistency_model section ----------------------------------------------

def test_draw_immediately_visible_in_heloc_read(api):
    """PRD §3.4: "Booking a draw debits the line's current_balance_cents by the advance,
    recomputes available_credit_cents ..."
    PRD §3.5: "Reading a line recomputes available_credit_cents and current_apr_bps so
    that the returned figures are reconciled."

    A 200000 draw is immediately reflected as current_balance_cents 200000 in the next
    heloc read.

    Design: Corner/consistency_model/immediate_consistency_draw_visible_in_response
    """
    ctx = setup_active_line(
        heloc_overrides={"credit_limit_cents": 50000000, "margin_bps": 0},
        index_rate_bps=0,
    )
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 200000)
    heloc = validate_success(api.get_heloc(hl_id, SERVICER))
    assert heloc["current_balance_cents"] == 200000
