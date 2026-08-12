"""Redemption and reinstatement quotes: variant pricing, pinned per-diem
rounding order, supersession with a fixed deadline, OCC, and the accept
precondition cascade including the complaint-freeze expiry path."""
from test_helpers import (
    ApiErrorId,
    accept_quote,
    create_complaint_payload,
    file_complaint,
    issue_quote,
    list_quotes,
    make_borrower_headers,
    make_compliance_officer_headers,
    parse_instant,
    resolve_complaint,
    rm_headers,
    set_clock,
    setup_case_collateral_secured,
    setup_case_redemption_open,
    validate_error,
    validate_success,
)

CO = make_compliance_officer_headers("co_1")


class TestQuotePricing:
    def test_reinstatement_quote_excludes_principal_and_per_diem(self, api):
        """PRD §3.5: "A `REINSTATEMENT` quote prices arrears only: the missed
        installments times the monthly payment, plus the late fees, plus the
        recovery-costs total — with no principal acceleration and no per-diem
        interest at all, which is why a reinstatement quote's `per_diem_cents`
        snapshot is 0 while a redemption quote's carries the computed daily
        figure."

        Design: Corner/calculations/reinstatement_quote_excludes_principal_and_per_diem
        """
        ctx = setup_case_collateral_secured(
            borrower_overrides={"full_name": "RQ", "email": "rq@x.com"},
            loan_overrides={"vin": "VIN00000000000055"})
        resp = api.create_redemption_quote(
            ctx["case"]["id"],
            {"quote_type": "REINSTATEMENT",
             "expected_recovery_case_version": ctx["case"]["version"]},
            rm_headers())
        quote = validate_success(resp, expected_status=201)
        # 3 x 45,000 missed + 12,000 late fees + 39,500 costs = 186,500c.
        assert quote["quoted_amount_cents"] == 186_500
        assert quote["per_diem_cents"] == 0

    def test_per_diem_rounding_order_pinned_value(self, api):
        """PRD §2.6: "Per-diem interest is always rounded to whole cents first
        and only then multiplied by the number of days — computing the interest
        for the whole period in a single shot and rounding once at the end
        produces a different, non-conformant number."
        PRD §3.5: "the principal balance is multiplied by the APR in basis
        points, divided by ten thousand, divided by 365, and the result rounded
        half up to whole cents — that daily figure is then multiplied by the
        number of calendar days between the case's `created_at` date and the
        quote's `valid_until` date"

        Design: Difficulty/combinatorial_formula/per_diem_rounding_order_pinned
        """
        ctx = setup_case_collateral_secured(
            borrower_overrides={"full_name": "PD", "email": "pd@x.com"},
            loan_overrides={"vin": "VIN0000000000000C"})
        resp = api.create_redemption_quote(
            ctx["case"]["id"],
            {"quote_type": "REDEMPTION",
             "expected_recovery_case_version": ctx["case"]["version"]},
            rm_headers())
        quote = validate_success(resp, expected_status=201)
        # round_half_up(2,000,000 x 0.12 / 365) = 658c, pinned before multiplying.
        assert quote["per_diem_cents"] == 658

    def test_per_diem_rounding_order_pinned_quote_total(self, api):
        """PRD §3.5: "A `REDEMPTION` quote prices the full payoff: the loan's
        `total_outstanding_cents`, plus the per-diem amount times those
        interest days, plus the case's recovery-costs total."
        PRD §2.6: "Per-diem interest is always rounded to whole cents first and
        only then multiplied by the number of days — computing the interest for
        the whole period in a single shot and rounding once at the end produces
        a different, non-conformant number."

        Design: Difficulty/combinatorial_formula/per_diem_rounding_order_pinned
        """
        ctx = setup_case_collateral_secured(
            borrower_overrides={"full_name": "PD", "email": "pd@x.com"},
            loan_overrides={"vin": "VIN0000000000000C"})
        quote = issue_quote(ctx["case"]["id"], "REDEMPTION")
        # Case opened 2026-05-01, valid_until 2026-05-26 -> 25 interest days:
        # 2,072,000 + 658 x 25 + 39,500 = 2,127,950c. The single-shot order
        # would yield 2,127,938c and is non-conformant.
        assert quote["quoted_amount_cents"] == 2_127_950
        assert quote["quoted_amount_cents"] != 2_127_938


class TestQuoteSupersession:
    def test_second_quote_supersedes_first_without_extending_deadline(self, api):
        """PRD §3.5: "The very first quote on a case moves it from
        `COLLATERAL_SECURED` to `REDEMPTION_OPEN` and fixes the case's
        `redemption_deadline` at the quote's `issued_at` plus ten days; that
        deadline is set once and is never extended by any later quote."
        PRD §3.5: "Issuing a replacement quote supersedes the live one: the
        prior `ISSUED` quote moves to `SUPERSEDED` with its `superseded_by_id`
        pointing at the newcomer, the new quote is created `ISSUED` with a
        freshly computed `quoted_amount_cents`, the case's
        `current_redemption_quote_id` is repointed, and the case `version`
        increments."

        Design: Corner/state_machines/second_quote_supersedes_first_without_extending_deadline
        """
        ctx = setup_case_redemption_open(
            quote_type="REDEMPTION",
            borrower_overrides={"full_name": "SQ", "email": "sq@x.com"},
            loan_overrides={"vin": "VIN00000000000049"})
        case = ctx["case"]
        quote1 = ctx["quote"]

        quote2 = issue_quote(case["id"], "REINSTATEMENT")
        # REINSTATEMENT: 3 x 45,000 + 12,000 + 39,500 = 186,500c, no per-diem.
        assert quote2["quoted_amount_cents"] == 186_500
        assert quote2["per_diem_cents"] == 0
        assert quote2["status"] == "ISSUED"
        # Deadline pinned by the first quote (issued 05-16 + 10 days).
        assert parse_instant(quote2["valid_until"]) == parse_instant("2026-05-26T00:00:00Z")

        quotes = {q["id"]: q for q in list_quotes(case["id"])}
        assert quotes[quote1["id"]]["status"] == "SUPERSEDED"
        assert quotes[quote1["id"]]["superseded_by_id"] == quote2["id"]

        case_after = validate_success(api.get_recovery_case(case["id"], rm_headers()))
        assert case_after["status"] == "REDEMPTION_OPEN"
        assert case_after["current_redemption_quote_id"] == quote2["id"]
        assert parse_instant(case_after["redemption_deadline"]) == parse_instant("2026-05-26T00:00:00Z")
        assert case_after["version"] == case["version"] + 1


class TestQuoteAcceptance:
    def test_redemption_quote_occ_stale_version(self, api):
        """PRD §2.8: "Two operations create documents that supersede their
        predecessor on a case: issuing a right-to-cure notice, and issuing a
        redemption or reinstatement quote. Both require the request to carry
        `expected_recovery_case_version` as a non-optional input field, holding
        the `version` of the `RecoveryCase` as the client last observed it. If
        the case's current `version` does not match — because another write has
        advanced the case since the client's last read — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412), and nothing is created or
        superseded."

        Design: Corner/complexity_layers/redemption_quote_occ_stale_version
        """
        ctx = setup_case_collateral_secured(
            borrower_overrides={"full_name": "OQ", "email": "oq@x.com"},
            loan_overrides={"vin": "VIN00000000000073"})
        case = ctx["case"]
        observed_version = case["version"]

        first = api.create_redemption_quote(
            case["id"],
            {"quote_type": "REINSTATEMENT",
             "expected_recovery_case_version": observed_version},
            rm_headers())
        quote1 = validate_success(first, expected_status=201)

        replay = api.create_redemption_quote(
            case["id"],
            {"quote_type": "REINSTATEMENT",
             "expected_recovery_case_version": observed_version},
            rm_headers())
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

        quotes = list_quotes(case["id"])
        issued = [q for q in quotes if q["status"] == "ISSUED"]
        assert [q["id"] for q in issued] == [quote1["id"]]

    def test_accept_expired_quote_invalid_quote_state(self, api):
        """PRD §2.7: "the state of the resource named in the request path is
        evaluated before any cross-entity precondition. An accept attempted on
        a quote that is already `EXPIRED` therefore yields
        `ERR_INVALID_QUOTE_STATE` even when the owning case has itself moved on
        to `CONSIGNMENT_PENDING` — the quote's own staleness is reported, not
        the case's."

        Design: Corner/state_machines/accept_expired_quote_invalid_quote_state
        """
        ctx = setup_case_redemption_open(
            quote_type="REDEMPTION",
            borrower_overrides={"full_name": "EQ", "email": "eq@x.com"},
            loan_overrides={"vin": "VIN00000000000080"})
        case = ctx["case"]
        quote = ctx["quote"]
        set_clock("2026-05-27T00:00:00Z")  # past redemption_deadline 2026-05-26

        resp = api.accept_redemption_quote(
            quote["id"], {"payment_amount_cents": 2_127_950},
            make_borrower_headers(ctx["borrower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_QUOTE_STATE)

        quote_after = [q for q in list_quotes(case["id"]) if q["id"] == quote["id"]][0]
        assert quote_after["status"] == "EXPIRED"
        case_after = validate_success(api.get_recovery_case(case["id"], rm_headers()))
        assert case_after["status"] == "CONSIGNMENT_PENDING"

    def test_quote_accept_after_dismissal_past_deadline_expired(self, api):
        """PRD §3.5: "the logical clock must be on or before the quote's
        `valid_until` (`ERR_QUOTE_EXPIRED`, HTTP 422 — a rejection reachable
        precisely in the complaint scenario, because a quote whose case sat
        frozen past the deadline was never auto-expired, and accepting it after
        a dismissal restores the case therefore fails this temporal check)"
        PRD §2.5: "quote and case expiry fire only while the case is still
        `REDEMPTION_OPEN`; a case frozen in `COMPLAINT_REVIEW` and its quote
        are left untouched by the clock."

        Design: Corner/validations/quote_accept_after_dismissal_past_deadline_expired
        """
        ctx = setup_case_redemption_open(
            quote_type="REDEMPTION",
            borrower_overrides={"full_name": "QE", "email": "qe@x.com"},
            loan_overrides={"vin": "VIN00000000000078"})
        case = ctx["case"]
        quote = ctx["quote"]
        set_clock("2026-05-20T00:00:00Z")
        complaint = file_complaint(case["id"], ctx["borrower"]["id"],
                                   category="NOTICE_DEFECT", description="address")
        set_clock("2026-05-30T00:00:00Z")  # past valid_until, but the case is frozen
        resolve_complaint(complaint["id"], "DISMISSED")

        case_after = validate_success(api.get_recovery_case(case["id"], rm_headers()))
        assert case_after["status"] == "REDEMPTION_OPEN"
        quote_after = [q for q in list_quotes(case["id"]) if q["id"] == quote["id"]][0]
        assert quote_after["status"] == "ISSUED", "frozen cases keep their quote ISSUED"

        resp = api.accept_redemption_quote(
            quote["id"], {"payment_amount_cents": 2_127_950},
            make_borrower_headers(ctx["borrower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)

        # Once restored to REDEMPTION_OPEN, the next clock advance expires both.
        set_clock("2026-05-31T00:00:00Z")
        quote_late = [q for q in list_quotes(case["id"]) if q["id"] == quote["id"]][0]
        assert quote_late["status"] == "EXPIRED"
        case_late = validate_success(api.get_recovery_case(case["id"], rm_headers()))
        assert case_late["status"] == "CONSIGNMENT_PENDING"


class TestComplaintInteraction:
    def test_complaint_dismissed_restores_prior_state(self, api):
        """PRD §3.8: "A `DISMISSED` outcome closes the complaint and restores
        the case verbatim to its `pre_complaint_state` — whatever
        complaint-eligible state it was frozen from."
        PRD §3.8: "Filing freezes the case: the case's status at that instant
        is captured verbatim into `pre_complaint_state`, the case moves to
        `COMPLAINT_REVIEW`, and if any consignment of the case is currently
        `LISTED`, that consignment is withdrawn to `WITHDRAWN` in the same
        atomic act."

        Design: Corner/state_machines/complaint_dismissed_restores_prior_state
        """
        ctx = setup_case_redemption_open(
            quote_type="REDEMPTION",
            borrower_overrides={"full_name": "CD", "email": "cd@x.com"},
            loan_overrides={"vin": "VIN00000000000052"})
        case = ctx["case"]
        quote = ctx["quote"]
        set_clock("2026-05-20T00:00:00Z")
        complaint = file_complaint(case["id"], ctx["borrower"]["id"],
                                   category="NOTICE_DEFECT", description="wrong address")
        frozen = validate_success(api.get_recovery_case(case["id"], rm_headers()))
        assert frozen["status"] == "COMPLAINT_REVIEW"
        assert frozen["pre_complaint_state"] == "REDEMPTION_OPEN"

        resolved = resolve_complaint(complaint["id"], "DISMISSED")
        assert resolved["status"] == "DISMISSED"
        case_after = validate_success(api.get_recovery_case(case["id"], rm_headers()))
        assert case_after["status"] == "REDEMPTION_OPEN"
        quote_after = [q for q in list_quotes(case["id"]) if q["id"] == quote["id"]][0]
        assert quote_after["status"] == "ISSUED", "the freeze leaves the quote untouched"

    def test_complaint_from_redeemed_is_invalid_state(self, api):
        """PRD §3.8: "the case must stand in one of the complaint-eligible
        states: `REPO_ACTIVE`, `COLLATERAL_SECURED`, `REDEMPTION_OPEN`,
        `CONSIGNMENT_PENDING`, `IN_AUCTION`, `SALE_CONFIRMED`, or
        `DEFICIENCY_NOTICED` (`ERR_INVALID_CASE_STATE` otherwise)."
        PRD §3.5: "accepting a `REDEMPTION` quote moves the case to `REDEEMED`
        and the loan to `REDEEMED_PAID`"

        Design: Corner/state_machines/complaint_from_redeemed_is_invalid_state
        """
        ctx = setup_case_redemption_open(
            quote_type="REDEMPTION",
            borrower_overrides={"full_name": "CR", "email": "cr@x.com"},
            loan_overrides={"vin": "VIN00000000000054"})
        case = ctx["case"]
        quote = ctx["quote"]
        set_clock("2026-05-20T00:00:00Z")
        accept_quote(quote["id"], ctx["borrower"]["id"], 2_127_950)

        case_after = validate_success(api.get_recovery_case(case["id"], rm_headers()))
        assert case_after["status"] == "REDEEMED"
        loan_after = validate_success(api.get_loan_account(ctx["loan"]["id"], rm_headers()))
        assert loan_after["status"] == "REDEEMED_PAID"
        assert loan_after["paid_to_date_cents"] == 2_127_950

        resp = api.create_complaint(
            case["id"],
            create_complaint_payload(description="too late"),
            make_borrower_headers(ctx["borrower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE)
        complaints = validate_success(api.list_case_complaints(case["id"], rm_headers()))
        assert complaints == []
