"""Budget reallocation: OCC guard, structural rules, floor, conservation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_budget_line,
    create_applied_reallocation,
    create_borrower,
    create_loan,
    create_reallocation,
    create_reallocation_payload,
    get_budget_line,
    get_loan,
    review_decision_payload,
    setup_funded_scenario,
    setup_loan_with_lines,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["lender_admin_headers"]
OFFICER = TEST_USERS["credit_officer_headers"]
SERVICER = TEST_USERS["loan_servicer_headers"]


def _two_line_loan():
    return setup_loan_with_lines(line_specs=(
        ("SITE", "Site work", 40_000_000, False),
        ("FRAM", "Framing", 30_000_000, False),
    ))


class TestOptimisticConcurrency:
    def test_occ_stale_version_rejected(self, api):
        """PRD §2.7: "The request body must carry `expected_loan_version`, a
        non-optional field holding the value of the target loan's `version` that
        the client last observed. If the loan's current `version` no longer matches
        — because any loan-mutating operation has advanced it since the client's
        last read — the create is rejected with `ERR_STALE_LOAN_VERSION`
        (HTTP 412), so the client never drafts a reallocation against a budget
        state it has not observed."
        PRD §3.7: "A drafted request starts `PENDING`, records the presented
        version in `created_loan_version` for audit, and — because drafting itself
        is a loan-mutating operation — increments the loan's `version` by one".

        Design: Corner/cross_cutting_layers/occ_stale_version_rejected
        """
        sc = _two_line_loan()
        observed = get_loan(sc["loan"]["id"])["version"]

        first = validate_success(api.create_reallocation_request(
            create_reallocation_payload(
                sc["loan"]["id"], sc["lines"]["SITE"]["id"],
                sc["lines"]["FRAM"]["id"], observed, amount_cents=1_000_000,
                justification="First"),
            ADMIN,
        ), 201)
        assert first["status"] == "PENDING"
        assert first["created_loan_version"] == observed, (
            "The presented version is recorded for audit"
        )
        assert get_loan(sc["loan"]["id"])["version"] == observed + 1, (
            "Drafting increments the loan's version by one"
        )

        stale = api.create_reallocation_request(
            create_reallocation_payload(
                sc["loan"]["id"], sc["lines"]["SITE"]["id"],
                sc["lines"]["FRAM"]["id"], observed, amount_cents=2_000_000,
                justification="Second with stale version"),
            ADMIN,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_LOAN_VERSION)

        _rows, meta = validate_paginated(api.list_reallocation_requests(
            ADMIN, params={"loan_id": sc["loan"]["id"]}))
        assert meta["total_count"] == 1, "The stale draft must not persist"


class TestStructuralRules:
    def test_reallocation_same_line_rejected(self, api):
        """PRD §3.7: "Source and target must differ — a request whose
        `from_budget_line_id` equals its `to_budget_line_id` is rejected with
        `ERR_REALLOCATION_SAME_LINE` (HTTP 422)".

        Design: Corner/validations/reallocation_same_line_rejected
        """
        sc = setup_loan_with_lines()
        version = get_loan(sc["loan"]["id"])["version"]
        resp = api.create_reallocation_request(
            create_reallocation_payload(
                sc["loan"]["id"], sc["lines"]["SITE"]["id"],
                sc["lines"]["SITE"]["id"], version, amount_cents=1_000_000,
                justification="Same line"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_REALLOCATION_SAME_LINE)

    def test_contingency_direction_violation_rejected(self, api):
        """PRD §3.7: "the direction rule for contingency applies: the target line
        must not be a contingency line, or the request is rejected with
        `ERR_CONTINGENCY_DIRECTION_VIOLATION` (HTTP 422), since contingency may
        fund other lines but may never be topped up itself."

        Design: Corner/validations/contingency_direction_violation_rejected
        """
        sc = setup_loan_with_lines(line_specs=(
            ("SITE", "Site work", 40_000_000, False),
            ("CONT", "Contingency", 10_000_000, True),
        ))
        version = get_loan(sc["loan"]["id"])["version"]
        resp = api.create_reallocation_request(
            create_reallocation_payload(
                sc["loan"]["id"], sc["lines"]["SITE"]["id"],
                sc["lines"]["CONT"]["id"], version, amount_cents=1_000_000,
                justification="Into contingency"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CONTINGENCY_DIRECTION_VIOLATION)


class TestApplyGuards:
    def test_reallocation_apply_before_approval_rejected(self, api):
        """PRD §3.7: "Application belongs to the `LoanServicer`." and §4: "Apply an
        APPROVED reallocation to the budget lines".
        PRD §2.6: "A transition attempted from any other state — including from an
        already-terminal state — is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/reallocation_apply_before_approval_rejected
        """
        sc = _two_line_loan()
        req = create_reallocation(sc, sc["lines"]["SITE"]["id"],
                                  sc["lines"]["FRAM"]["id"], 5_000_000,
                                  justification="Shift")
        assert req["status"] == "PENDING"

        resp = api.apply_reallocation_request(req["id"], SERVICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_budget_line(sc["lines"]["SITE"]["id"])["revised_amount_cents"] == 40_000_000
        assert get_budget_line(sc["lines"]["FRAM"]["id"])["revised_amount_cents"] == 30_000_000

    def test_reallocation_below_floor_at_apply(self, api):
        """PRD §3.7: "The from-line has a floor that protects money already spoken
        for: applying is rejected with `ERR_REALLOCATION_BELOW_FLOOR` (HTTP 422)
        unless the source line's `revised_amount_cents` minus the reallocation
        `amount_cents` remains at least the sum of that line's `disbursed_cents`,
        `retained_cents`, and `approved_unfunded_cents`."

        Design: Corner/validations/reallocation_below_floor_at_apply
        """
        sc = setup_funded_scenario(
            extra_line_specs=(("FRAM", "Framing", 30_000_000, False),))
        line_a = sc["lines"]["SITE"]
        # occupied on BL-A: disbursed 9500000 + retained 500000 = 10000000;
        # 40000000 - 30500000 = 9500000 < 10000000 -> below the floor.
        req = create_reallocation(sc, line_a["id"], sc["lines"]["FRAM"]["id"],
                                  30_500_000, justification="Oversized move")
        get_resp = api.review_reallocation_request(
            req["id"], review_decision_payload("APPROVED"), OFFICER)
        validate_success(get_resp, 200)

        resp = api.apply_reallocation_request(req["id"], SERVICER)
        validate_error(resp, ApiErrorId.ERR_REALLOCATION_BELOW_FLOOR)

        after_req = validate_success(api.get_reallocation_request(req["id"], ADMIN))
        assert after_req["status"] == "APPROVED", (
            "The rejected apply leaves the request APPROVED"
        )
        assert get_budget_line(line_a["id"])["revised_amount_cents"] == 40_000_000


class TestBudgetConservation:
    def _roundtrip_setup(self):
        return setup_loan_with_lines(line_specs=(
            ("SITE", "Site work", 40_000_000, False),
            ("FRAM", "Framing", 30_000_000, False),
            ("CONT", "Contingency", 10_000_000, True),
        ))

    def _revised_sum(self, sc):
        return sum(
            get_budget_line(line["id"])["revised_amount_cents"]
            for line in sc["lines"].values()
        )

    def test_reallocation_forward_apply_moves_budget(self, api):
        """PRD §3.7: "A successful apply subtracts `amount_cents` from the source
        line's `revised_amount_cents` and adds it to the target line's
        `revised_amount_cents`".
        PRD §3.7: "Because a reallocation only moves budget and never creates or
        destroys it, the sum of `revised_amount_cents` across a loan's lines always
        equals the sum of `original_amount_cents`, no matter how many reallocations
        have been applied."

        Design: Difficulty/compensating_invariant/reallocation_roundtrip_budget_conservation
        """
        sc = self._roundtrip_setup()
        applied = create_applied_reallocation(
            sc, sc["lines"]["CONT"]["id"], sc["lines"]["SITE"]["id"], 5_000_000,
            justification="Site overrun")
        assert applied["status"] == "APPLIED"

        assert get_budget_line(sc["lines"]["SITE"]["id"])["revised_amount_cents"] == 45_000_000
        assert get_budget_line(sc["lines"]["CONT"]["id"])["revised_amount_cents"] == 5_000_000
        assert self._revised_sum(sc) == 80_000_000, (
            "The forward move conserves the total revised budget"
        )

    def test_reallocation_roundtrip_restores_originals(self, api):
        """PRD §3.7: "Revised amounts are always derivable from history: a line's
        `revised_amount_cents` equals its `original_amount_cents` plus the
        `amount_cents` of every `APPLIED` reallocation targeting it, minus the
        `amount_cents` of every `APPLIED` reallocation sourced from it. Because a
        reallocation only moves budget and never creates or destroys it, the sum of
        `revised_amount_cents` across a loan's lines always equals the sum of
        `original_amount_cents`, no matter how many reallocations have been
        applied."

        Design: Difficulty/compensating_invariant/reallocation_roundtrip_budget_conservation
        """
        sc = self._roundtrip_setup()
        # Roundtrip between two non-contingency lines: PRD §3.7 forbids any
        # reallocation whose target is a contingency line
        # (ERR_CONTINGENCY_DIRECTION_VIOLATION), so the compensating leg runs
        # FRAM -> SITE rather than SITE -> CONT.
        create_applied_reallocation(
            sc, sc["lines"]["SITE"]["id"], sc["lines"]["FRAM"]["id"], 5_000_000,
            justification="Framing overrun")
        create_applied_reallocation(
            sc, sc["lines"]["FRAM"]["id"], sc["lines"]["SITE"]["id"], 5_000_000,
            justification="Reverse")

        assert get_budget_line(sc["lines"]["SITE"]["id"])["revised_amount_cents"] == 40_000_000, (
            "The compensating reallocation restores the original amount"
        )
        assert get_budget_line(sc["lines"]["FRAM"]["id"])["revised_amount_cents"] == 30_000_000, (
            "The framing line is restored"
        )
        assert get_budget_line(sc["lines"]["CONT"]["id"])["revised_amount_cents"] == 10_000_000, (
            "The contingency line is untouched"
        )
        assert self._revised_sum(sc) == 80_000_000, (
            "sum(revised) == sum(original) at every step"
        )


class TestStateBeatsFiscal:
    def _terminated_loan(self, api):
        borrower = create_borrower()
        loan = create_loan(borrower["id"], commitment_amount_cents=100_000_000,
                           reserve_cents=0)
        terminated = validate_success(api.terminate_loan(loan["id"], ADMIN), 200)
        assert terminated["status"] == "TERMINATED"
        return loan

    def test_budget_line_create_on_terminated_loan_state_beats_fiscal(self, api):
        """PRD §2.8: "When several checks could reject the same request, they run
        in a fixed priority order and the earliest failing check determines the
        error returned."
        PRD §2.8: "6. State validity and loan-open gating. The resource is in a
        valid from-state for the requested transition, and child creation happens
        only under an `OPEN` loan — otherwise `ERR_INVALID_STATE` or
        `ERR_LOAN_NOT_OPEN` (both HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/budget_line_create_state_beats_fiscal
        """
        loan = self._terminated_loan(api)
        # 200000000 would also break the 100000000 commitment ceiling (fiscal,
        # priority 11), but the loan-open gate (priority 6) fires first.
        resp = api.create_budget_line(
            {
                "loan_id": loan["id"],
                "cost_code": "SITE",
                "description": "Site work",
                "original_amount_cents": 200_000_000,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_LOAN_NOT_OPEN)

    def test_budget_line_create_on_terminated_loan_creates_nothing(self, api):
        """PRD §2.6: "While a loan is `OPEN`, the full toolkit is available; once
        it is `CONVERTED` or `TERMINATED`, creating budget lines, draws, draw line
        items, draw documents, inspections, reallocation requests, retainage
        releases, or conversion reviews against it — and running interest accruals
        on it — is rejected with `ERR_LOAN_NOT_OPEN` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/budget_line_create_state_beats_fiscal
        """
        loan = self._terminated_loan(api)
        validate_error(api.create_budget_line(
            {
                "loan_id": loan["id"],
                "cost_code": "SITE",
                "description": "Site work",
                "original_amount_cents": 200_000_000,
            },
            ADMIN,
        ), ApiErrorId.ERR_LOAN_NOT_OPEN)

        _rows, meta = validate_paginated(api.list_budget_lines(
            ADMIN, params={"loan_id": loan["id"]}))
        assert meta["total_count"] == 0, (
            "No budget line is created against a terminated loan"
        )
        assert get_loan(loan["id"])["status"] == "TERMINATED"
