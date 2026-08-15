"""Quote pricing, the submit-revise cycle, expiry, and acceptance gates."""
from test_helpers import (
    ApiErrorId,
    get_customer,
    get_quote,
    get_unit,
    make_certified_operator,
    make_customer,
    make_draft_quote,
    make_submitted_quote,
    make_unit,
    set_clock,
    validate_error,
    validate_success,
)


class TestQuotePricingRoundingOrder:
    def test_quote_level_discount_rounding(self, api, sales_rep_headers):
        """PRD §3.2: "The discount is computed exactly once, at the quote level,
        as the subtotal times the tier fraction rounded half up to whole cents,
        and stored as `discount_cents`; rounding the discount per line and
        summing those roundings is a different algorithm and is not the
        specification. (To see the difference, consider three lines extending
        99980, 10, and 10 cents: the quote-level discount is 5000 cents, while
        per-line rounding would yield 5001.)"

        Design: Difficulty/combinatorial_formula/quote_discount_rounding_order
        """
        customer = make_customer(name="Quote Co")
        quote = make_draft_quote(customer["id"], lines=(
            ("Base truck configuration", 1, 99980),
            ("Sideshifter", 1, 10),
            ("Fork extension pair", 1, 10),
        ))
        data = validate_success(api.get_quote(quote["id"], sales_rep_headers))
        assert data["subtotal_cents"] == 100000
        assert data["discount_cents"] == 5000, \
            "quote-level rounding gives 5000; per-line rounding would give 5001"

    def test_tax_and_total_after_discount(self, api, sales_rep_headers):
        """PRD §3.2: "Next, `tax_cents` is the discounted amount — subtotal
        minus discount — times eight percent, rounded half up to whole cents.
        Finally `total_cents` is the subtotal minus the discount plus the tax."
        For subtotal 100000 with the 5% tier: tax 7600, total 102600.

        Design: Difficulty/combinatorial_formula/quote_discount_rounding_order
        """
        customer = make_customer(name="Quote Co")
        quote = make_draft_quote(customer["id"], lines=(
            ("Base truck configuration", 1, 99980),
            ("Sideshifter", 1, 10),
            ("Fork extension pair", 1, 10),
        ))
        data = validate_success(api.get_quote(quote["id"], sales_rep_headers))
        assert data["tax_cents"] == 7600
        assert data["total_cents"] == 102600


class TestSubmitReviseCycle:
    def test_revise_increments_revision_count(self, api, sales_rep_headers):
        """PRD §3.2: "A submitted quote can be pulled back for revision at any
        time — revising returns it from `SUBMITTED` to `DRAFT`, increments
        `revision_count` by 1, and clears `submitted_at` back to null — and
        this submit–revise loop may repeat any number of times."

        Design: Difficulty/non_linear_state_machine/quote_submit_revise_cycle
        """
        customer = make_customer(name="Cycle Co")
        make_certified_operator(customer["id"])
        quote = make_submitted_quote(customer["id"],
                                     lines=(("Reach truck", 1, 100000),))
        assert quote["status"] == "SUBMITTED"
        revised = validate_success(api.revise_quote(quote["id"], sales_rep_headers))
        assert revised["status"] == "DRAFT"
        assert revised["revision_count"] == 1
        assert revised["submitted_at"] is None
        resubmitted = validate_success(api.submit_quote(quote["id"],
                                                        sales_rep_headers))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_count"] == 1

    def test_accept_after_cycle_posts_total(self, api, sales_rep_headers):
        """PRD §3.2: "Acceptance is the point of no return, moving a `SUBMITTED`
        quote to `ACCEPTED`." and "On success, the quote's `total_cents` is
        posted to the customer's `outstanding_balance_cents`, which may in turn
        flip the account to `CREDIT_HOLD` per §2.10." A cycled quote keeps
        `revision_count` 1 and prices 100000 -> total 102600.

        Design: Difficulty/non_linear_state_machine/quote_submit_revise_cycle
        """
        customer = make_customer(name="Cycle Co")
        make_certified_operator(customer["id"])
        quote = make_submitted_quote(customer["id"],
                                     lines=(("Reach truck", 1, 100000),))
        validate_success(api.revise_quote(quote["id"], sales_rep_headers))
        validate_success(api.submit_quote(quote["id"], sales_rep_headers))
        accepted = validate_success(api.accept_quote(quote["id"], sales_rep_headers))
        assert accepted["status"] == "ACCEPTED"
        assert accepted["revision_count"] == 1
        assert accepted["total_cents"] == 102600
        assert get_customer(customer["id"])["outstanding_balance_cents"] == 102600


class TestQuoteEmptyBoundary:
    def test_submit_zero_lines_rejected(self, api, sales_rep_headers):
        """PRD §3.2: "a quote with zero lines cannot be submitted and is
        rejected with `ERR_QUOTE_EMPTY`."

        Design: Difficulty/boundary_precision_check/quote_submit_zero_lines
        """
        customer = make_customer(name="Empty Co")
        quote = make_draft_quote(customer["id"], lines=())
        resp = api.submit_quote(quote["id"], sales_rep_headers)
        validate_error(resp, ApiErrorId.ERR_QUOTE_EMPTY, 422)
        assert get_quote(quote["id"])["status"] == "DRAFT"

    def test_submit_with_first_line_succeeds(self, api, sales_rep_headers):
        """PRD §3.2: "Submitting moves the quote from `DRAFT` to `SUBMITTED` and
        stamps `submitted_at` with the logical clock" — adding the first line
        clears the zero-line boundary and the identical call succeeds.

        Design: Difficulty/boundary_precision_check/quote_submit_zero_lines
        """
        customer = make_customer(name="Empty Co")
        quote = make_draft_quote(customer["id"], lines=())
        validate_error(api.submit_quote(quote["id"], sales_rep_headers),
                       ApiErrorId.ERR_QUOTE_EMPTY, 422)
        validate_success(api.create_quote_line(
            quote["id"], {"description": "One attachment", "qty": 1,
                          "unit_price_cents": 5000}, sales_rep_headers), 201)
        data = validate_success(api.submit_quote(quote["id"], sales_rep_headers))
        assert data["status"] == "SUBMITTED"
        assert data["subtotal_cents"] == 5000
        assert data["submitted_at"] is not None


class TestQuoteStateGates:
    def test_accept_draft_quote_returns_invalid_state(self, api,
                                                      sales_rep_headers):
        """PRD §3.2: acceptance is "moving a `SUBMITTED` quote to `ACCEPTED`"
        and "The checks run in the ladder order of §2.6: the quote must be in a
        state that permits acceptance" — a DRAFT quote is not, so the accept
        fails the state-validity rung with `ERR_INVALID_STATE` (PRD §5:
        HTTP 409).

        Design: Corner/state_machines/accept_draft_quote_returns_invalid_state
        """
        customer = make_customer(name="SM Co")
        make_certified_operator(customer["id"], cert_class="SIT_DOWN")
        quote = make_draft_quote(customer["id"], lines=(("Line", 1, 5000),))
        resp = api.accept_quote(quote["id"], sales_rep_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert get_quote(quote["id"])["status"] == "DRAFT"

    def test_quote_expiry_sweep_on_clock_advance(self, api, sales_rep_headers):
        """PRD §2.9: "Advancing the clock fires two time-based sweeps: every
        quote still `SUBMITTED` whose `valid_until` has been passed transitions
        to `EXPIRED`". PRD §3.2: "the expiry sweep moves it to `EXPIRED`
        instead, and it is no longer acceptable. Both `ACCEPTED` and `EXPIRED`
        are terminal."

        Design: Corner/state_machines/quote_expiry_sweep_on_clock_advance
        """
        customer = make_customer(name="Expiry Co")
        quote = make_submitted_quote(customer["id"], lines=(("Line", 1, 5000),),
                                     valid_until="2026-09-01")
        set_clock("2026-09-02T00:00:00Z")
        data = get_quote(quote["id"])
        assert data["status"] == "EXPIRED", \
            "clock advance past valid_until must sweep SUBMITTED -> EXPIRED"
        resp = api.accept_quote(quote["id"], sales_rep_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestAcceptanceBusinessGates:
    def test_accept_without_certified_operator_rejected(self, api,
                                                        sales_rep_headers):
        """PRD §3.2: "the customer must have at least one operator holding a
        certification with status `ACTIVE`, otherwise the accept is rejected
        with `ERR_NO_CERTIFIED_OPERATOR`".

        Design: Corner/validations/quote_accept_without_certified_operator_rejected
        """
        customer = make_customer(name="NoCert Co")
        quote = make_submitted_quote(customer["id"], lines=(("Line", 1, 5000),))
        resp = api.accept_quote(quote["id"], sales_rep_headers)
        validate_error(resp, ApiErrorId.ERR_NO_CERTIFIED_OPERATOR, 422)
        assert get_quote(quote["id"])["status"] == "SUBMITTED"

    def test_accept_expired_quote_returns_quote_expired(self, api,
                                                        sales_rep_headers):
        """PRD §3.2: "the logical clock must be on or before `valid_until`,
        otherwise `ERR_QUOTE_EXPIRED`". With the default clock
        2026-08-01T00:00:00Z (PRD §2.9) past valid_until 2026-07-01 and no sweep
        having run, the accept raises the temporal error and the quote remains
        SUBMITTED.

        Design: Corner/validations/accept_expired_quote_returns_quote_expired
        """
        customer = make_customer(name="Expired Q")
        make_certified_operator(customer["id"])
        quote = make_submitted_quote(customer["id"], lines=(("Line", 1, 5000),),
                                     valid_until="2026-07-01")
        resp = api.accept_quote(quote["id"], sales_rep_headers)
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED, 422)
        assert get_quote(quote["id"])["status"] == "SUBMITTED"

    def test_used_sale_accept_requires_listed_unit(self, api, sales_rep_headers):
        """PRD §3.2: "for a `USED_UNIT_SALE` quote the referenced unit must
        currently be `LISTED`, otherwise `ERR_UNIT_NOT_LISTED`" — a used unit
        still `AVAILABLE` (no reconditioning) blocks acceptance. The §5
        catalogue omits ERR_UNIT_NOT_LISTED, so only the error_id is pinned
        (no HTTP-status assertion).

        Design: Corner/validations/used_sale_accept_requires_listed_unit
        """
        customer = make_customer(name="Used Co")
        make_certified_operator(customer["id"])
        unit = make_unit(serial_number="SN-V5", disposition="USED_SALE")
        quote = make_submitted_quote(
            customer["id"], lines=(("Used truck", 1, 2500000),),
            kind="USED_UNIT_SALE", unit_id=unit["id"])
        resp = api.accept_quote(quote["id"], sales_rep_headers)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_LISTED)
        assert get_unit(unit["id"])["availability_status"] == "AVAILABLE"


class TestLogicalClockDefault:
    def test_clock_default_before_first_set(self, api, sales_rep_headers):
        """PRD §2.9: "At server startup, before any explicit adjustment, the
        logical clock reads exactly 2026-08-01T00:00:00Z." PRD §3.2: submitting
        "stamps `submitted_at` with the logical clock" — so a quote submitted
        without ever touching the clock is stamped 2026-08-01T00:00:00Z.

        Design: Corner/complexity_layers/cl_clock_default_before_first_set
        """
        customer = make_customer(name="Clock Co")
        quote = make_submitted_quote(customer["id"], lines=(("Line", 1, 5000),),
                                     valid_until="2026-12-31")
        submitted_at = quote["submitted_at"]
        assert submitted_at is not None
        assert submitted_at.startswith("2026-08-01T00:00:00"), (
            f"submitted_at must read the default logical clock, got "
            f"{submitted_at}")
