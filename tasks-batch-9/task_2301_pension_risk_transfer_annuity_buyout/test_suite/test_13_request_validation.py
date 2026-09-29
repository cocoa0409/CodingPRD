"""Request validation: identity before anything else, field ranges, interval
well-formedness, segregation of duties and pagination bounds.

Each test drives one malformed or forbidden request and pins the single error the
contract promises, then re-reads the target to show the rejection changed nothing.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ACTUARY_USER_ID,
    administrator_headers,
    factories,
    fixtures,
    fiduciary_headers,
    opaque_headers,
    sponsor_headers,
)
from test_helpers.api_errors import (
    ERR_INVALID_AMOUNT,
    ERR_INVALID_INTERVAL,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_REQUEST,
    ERR_NOTICE_PERIOD_TOO_SHORT,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import require_by_id
from test_helpers.types import (
    AmendmentScope,
    PlanStatus,
    StrategyStatus,
    StrategyType,
    UserRole,
    WindowStatus,
)


JSON_ONLY = {"Content-Type": "application/json"}


class TestUnidentifiedRequests:
    """Identity is settled before the role list, the path or the body."""

    def test_validation_unidentified_request_returns_401_first(self, api):
        """Requests with absent or unrecognised identity headers are 401 regardless of what else is wrong.

        Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. If either header is absent, or if `X-User-Role` is not one of the eight role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well formed but the declared role does not appear in the target endpoint's authorized-role list (see §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).
        When a single request violates several rules, exactly one error is returned, and which one is fully determined. The families below are evaluated in the order listed; the first family that finds a violation decides the response, and later families are not consulted.
        1. **Header authentication** — both headers present and `X-User-Role` one of the eight roles, else `ERR_UNAUTHENTICATED`. Applies to every endpoint.

        Design: Corner/validations/unidentified_request_returns_401_before_role_and_body_checks
        """
        fixtures.reset_clock(api)

        # A body that also breaks request shape and numeric ranges.
        broken_payload = factories.plan_payload(
            plan_ein=None, discount_rate_bps=9999, plan_assets_cents=-1
        )

        validate_error(
            api.post("/prt/plans", broken_payload, JSON_ONLY), ERR_UNAUTHENTICATED
        )

        validate_error(
            api.post(
                "/prt/plans",
                broken_payload,
                {"Content-Type": "application/json", "X-User-ID": "sponsor-treasury-01"},
            ),
            ERR_UNAUTHENTICATED,
        )

        validate_error(
            api.post(
                "/prt/plans",
                broken_payload,
                {
                    "Content-Type": "application/json",
                    "X-User-ID": "sponsor-treasury-01",
                    "X-User-Role": "PensionOverlord",
                },
            ),
            ERR_UNAUTHENTICATED,
        )

        # Identity outranks path existence too.
        validate_error(
            api.get("/prt/plans/{}".format(NON_EXISTENT_UUID), JSON_ONLY),
            ERR_UNAUTHENTICATED,
        )


class TestPlanEinLength:
    """The employer identification number carries exactly nine digits."""

    def test_validation_plan_ein_of_the_wrong_length_is_rejected(self, api):
        """An eight-digit and a ten-digit employer identification number are both refused.

        A `PlanSponsor` registers a defined benefit plan by supplying the sponsor's `sponsor_name`, the plan's `plan_name`, and its `plan_ein` — the sponsor's employer identification number, which must be exactly nine digits and must be unique across all registered plans.
        7. **Numeric ranges** — money fields at least 0, `discount_rate_bps` within 1 through 2000, `credited_service_months` within 0 through 600, `capital_ratio_bp` within 0 through 20000, `lock_days` within 1 through 180, `quote_valid_days` within 1 through 90, `plan_ein` exactly nine digits, and `remediation_amount_cents` consistent with the responsibility determination; else `ERR_INVALID_AMOUNT` (HTTP 422). Applies to `POST /prt/plans`, `POST /prt/plans/{id}/participants`, `POST /prt/insurers`, `POST /prt/quotes/{id}/submission`, `POST /prt/participants/{id}/benefit-audits`, and `POST /prt/complaints/{id}/resolution`.

        Design: Corner/validations/plan_ein_must_be_exactly_nine_digits
        """
        fixtures.reset_clock(api)

        validate_error(
            api.create_plan(factories.plan_payload(plan_ein="23100455"), sponsor_headers()),
            ERR_INVALID_AMOUNT,
        )
        validate_error(
            api.create_plan(factories.plan_payload(plan_ein="9410045566"), sponsor_headers()),
            ERR_INVALID_AMOUNT,
        )

    def test_validation_plan_ein_of_exactly_nine_digits_is_accepted(self, api):
        """A nine-digit employer identification number registers the plan and is echoed back.

        A `PlanSponsor` registers a defined benefit plan by supplying the sponsor's `sponsor_name`, the plan's `plan_name`, and its `plan_ein` — the sponsor's employer identification number, which must be exactly nine digits and must be unique across all registered plans.
        A new plan starts with a `plan_status` of `ONGOING`, has its `participant_liability_total_cents` set to 0 because it has no participants yet, and has its `accounting_funded_status_bp` derived immediately.

        Design: Corner/validations/plan_ein_must_be_exactly_nine_digits
        """
        fixtures.reset_clock(api)

        plan = validate_success(
            api.create_plan(factories.plan_payload(plan_ein="231004551"), sponsor_headers()),
            201,
        )

        assert plan["plan_ein"] == "231004551"
        assert plan["plan_status"] == PlanStatus.ONGOING.value
        assert plan["participant_liability_total_cents"] == 0


class TestAmendmentEffectiveDate:
    """The amendment may not be back-dated behind the logical clock."""

    @staticmethod
    def _plan_ready_for_both_scopes(api):
        plan = fixtures.create_plan(api)
        strategy = fixtures.create_approved_strategy(
            api, plan["id"], StrategyType.HYBRID_WINDOW_AND_BUYOUT.value
        )
        fixtures.set_clock(api, "2026-08-10T00:00:00Z")
        return plan, strategy

    def test_validation_backdated_amendment_effective_date_is_an_invalid_interval(self, api):
        """An effective date a month behind the clock is refused and the plan stays ongoing.

        The `amendment_effective_date` must be at or after the logical clock, and an earlier date is rejected with `ERR_INVALID_INTERVAL`.
        8. **Interval well-formedness** — a lump-sum window requires `opens_at` strictly before `closes_at`, a quote submission requires `lock_days` of at least 1, and an amendment's `amendment_effective_date` must not precede the logical clock; else `ERR_INVALID_INTERVAL` (HTTP 422).

        Design: Corner/validations/amendment_effective_date_before_the_clock_is_an_invalid_interval
        """
        fixtures.reset_clock(api)
        plan, _strategy = self._plan_ready_for_both_scopes(api)

        validate_error(
            api.post_settlement_amendment(
                plan["id"],
                factories.amendment_adopt_payload(
                    AmendmentScope.BOTH.value, "2026-07-01T00:00:00Z"
                ),
                sponsor_headers(),
            ),
            ERR_INVALID_INTERVAL,
        )

        unchanged = fixtures.read_plan(api, plan["id"])
        assert unchanged["plan_status"] == PlanStatus.ONGOING.value
        assert unchanged["amendment_scope"] is None
        assert unchanged["amendment_adopted_at"] is None
        assert unchanged["amendment_effective_date"] is None

    def test_validation_amendment_without_a_scope_fails_request_shape(self, api):
        """An adoption that omits the required scope is a request-shape failure, not an interval one.

        Adopting the amendment moves the plan `ONGOING → SETTLEMENT_AUTHORIZED` and requires the sponsor to declare an `amendment_action` of `ADOPT`, an `amendment_scope` of `LUMP_SUM_ONLY`, `BUYOUT_ONLY`, or `BOTH`, and an `amendment_effective_date`.
        6. **Request shape** — every required field present, every value of the correct JSON type, every enum value drawn from its declared set, else `ERR_INVALID_REQUEST` (HTTP 422). Unknown fields are ignored, and fields whose value the server computes or assigns are ignored when a client supplies them. Applies to every POST endpoint.

        Design: Corner/validations/amendment_effective_date_before_the_clock_is_an_invalid_interval
        """
        fixtures.reset_clock(api)
        plan, _strategy = self._plan_ready_for_both_scopes(api)

        payload = factories.amendment_adopt_payload(
            AmendmentScope.BOTH.value, "2026-08-10T00:00:00Z"
        )
        payload.pop("amendment_scope", None)
        assert "amendment_scope" not in payload

        validate_error(
            api.post_settlement_amendment(plan["id"], payload, sponsor_headers()),
            ERR_INVALID_REQUEST,
        )

        unchanged = fixtures.read_plan(api, plan["id"])
        assert unchanged["plan_status"] == PlanStatus.ONGOING.value

    def test_validation_amendment_effective_exactly_at_the_clock_is_accepted(self, api):
        """An effective date equal to the clock adopts the amendment and stamps the adoption instant.

        The `amendment_effective_date` must be at or after the logical clock, and an earlier date is rejected with `ERR_INVALID_INTERVAL`.
        On success the plan stores `amendment_scope` and `amendment_effective_date` from the payload, stamps `amendment_adopted_at` with the logical clock, and bumps the plan's `version`.

        Design: Corner/validations/amendment_effective_date_before_the_clock_is_an_invalid_interval
        """
        fixtures.reset_clock(api)
        plan, strategy = self._plan_ready_for_both_scopes(api)
        before = fixtures.read_plan(api, plan["id"])

        adopted = validate_success(
            api.post_settlement_amendment(
                plan["id"],
                factories.amendment_adopt_payload(
                    AmendmentScope.BOTH.value, "2026-08-10T00:00:00Z"
                ),
                sponsor_headers(),
            )
        )

        assert adopted["plan_status"] == PlanStatus.SETTLEMENT_AUTHORIZED.value
        assert adopted["amendment_scope"] == AmendmentScope.BOTH.value
        assert adopted["amendment_adopted_at"].startswith("2026-08-10T00:00:00")
        assert adopted["version"] == before["version"] + 1

        backing = fixtures.read_strategy(api, plan["id"], strategy["id"])
        assert backing["strategy_status"] == StrategyStatus.APPROVED.value


class TestWindowIntervalAndNoticePeriod:
    """Interval well-formedness bites at creation; the notice period bites at opening."""

    def test_validation_inverted_window_interval_is_rejected_at_creation(self, api):
        """A window that closes before it opens never comes into existence.

        Both amounts must be at least 1, and `closes_at` must be strictly after `opens_at`.
        8. **Interval well-formedness** — a lump-sum window requires `opens_at` strictly before `closes_at`, a quote submission requires `lock_days` of at least 1, and an amendment's `amendment_effective_date` must not precede the logical clock; else `ERR_INVALID_INTERVAL` (HTTP 422).

        Design: Corner/validations/window_interval_and_notice_period_are_checked_at_different_priorities
        """
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(api)

        validate_error(
            api.create_window(
                plan["id"],
                factories.window_payload(
                    opens_at="2026-09-30T00:00:00Z",
                    closes_at="2026-08-15T00:00:00Z",
                    window_name="Inverted Election Window",
                    lump_sum_cap_cents=5000000,
                    eligibility_max_lump_sum_cents=3000000,
                ),
                administrator_headers(),
            ),
            ERR_INVALID_INTERVAL,
        )

        _rows, meta = validate_paginated(api.list_windows(plan["id"], sponsor_headers()))
        assert meta["total_count"] == 0

    def test_validation_short_notice_runway_is_only_rejected_at_opening(self, api):
        """A well-formed nineteen-day window is created but cannot be opened.

        Finally, the gap between the logical clock and `closes_at` must be at least 30 days, so that participants have a full statutory month to consider the offer; a shorter runway is rejected with `ERR_NOTICE_PERIOD_TOO_SHORT`.
        9. **Notice period** — opening a window must leave participants at least 30 days between the logical clock and `closes_at`, else `ERR_NOTICE_PERIOD_TOO_SHORT` (HTTP 422). Applies to `POST /prt/lump-sum-windows/{id}/opening`.
        A window starts in `PLANNED` with `notice_count` at 0, `approved_lump_sum_total_cents` and `paid_lump_sum_total_cents` at 0, and `opened_at`, `closed_at`, and `settled_at` all null.

        Design: Corner/validations/window_interval_and_notice_period_are_checked_at_different_priorities
        """
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(api)
        fixtures.create_approved_strategy(
            api, plan["id"], StrategyType.LUMP_SUM_WINDOW.value
        )
        fixtures.adopt_amendment(
            api, plan["id"], AmendmentScope.LUMP_SUM_ONLY.value, "2026-08-01T00:00:00Z"
        )

        window = fixtures.create_window(
            api,
            plan["id"],
            opens_at="2026-08-01T00:00:00Z",
            closes_at="2026-08-20T00:00:00Z",
            window_name="Short Runway Window",
            lump_sum_cap_cents=5000000,
            eligibility_max_lump_sum_cents=3000000,
        )
        assert window["window_status"] == WindowStatus.PLANNED.value
        assert window["notice_count"] == 0
        assert window["opened_at"] is None

        validate_error(
            api.post_window_opening(window["id"], {}, administrator_headers()),
            ERR_NOTICE_PERIOD_TOO_SHORT,
        )

        rows, meta = validate_paginated(
            api.list_windows(plan["id"], sponsor_headers(), {"window_status": "PLANNED"})
        )
        assert meta["total_count"] == 1
        still_planned = require_by_id(rows, window["id"])
        assert still_planned["window_status"] == WindowStatus.PLANNED.value
        assert still_planned["notice_count"] == 0
        assert still_planned["opened_at"] is None


class TestStrategyDecisionSegregation:
    """The deciding identity must differ from the submitting identity."""

    @staticmethod
    def _submitted_strategy(api):
        plan = fixtures.create_plan(api)
        strategy = fixtures.create_strategy(
            api, plan["id"], StrategyType.ANNUITY_BUYOUT.value
        )
        submitted = fixtures.submit_strategy(api, strategy["id"])
        assert submitted["submitted_by_user_id"] == ACTUARY_USER_ID
        return plan, submitted

    def test_validation_submitter_cannot_decide_their_own_strategy(self, api):
        """The submitting user id, acting as fiduciary, cannot approve its own submission.

        Submission records `submitted_by_user_id` from the acting `X-User-ID` and bumps the strategy's `version`.
        The strategy must be `UNDER_EVALUATION`, and the deciding `X-User-ID` must differ from the recorded `submitted_by_user_id`; an actuary who tries to approve their own submission is rejected with `ERR_SEGREGATION_OF_DUTIES`.

        Design: Corner/validations/strategy_submitter_cannot_also_decide_the_strategy
        """
        fixtures.reset_clock(api)
        plan, submitted = self._submitted_strategy(api)

        validate_error(
            api.post_strategy_decision(
                submitted["id"],
                factories.strategy_decision_payload("APPROVE"),
                opaque_headers(UserRole.PLAN_FIDUCIARY.value, ACTUARY_USER_ID),
            ),
            ERR_SEGREGATION_OF_DUTIES,
        )

        unchanged = fixtures.read_strategy(api, plan["id"], submitted["id"])
        assert unchanged["strategy_status"] == StrategyStatus.UNDER_EVALUATION.value
        assert unchanged["decided_by_user_id"] is None
        assert unchanged["decision_rationale"] is None

    def test_validation_a_different_fiduciary_may_decide_the_strategy(self, api):
        """A fiduciary whose user id differs from the submitter's approves the same strategy.

        The strategy must be `UNDER_EVALUATION`, and the deciding `X-User-ID` must differ from the recorded `submitted_by_user_id`; an actuary who tries to approve their own submission is rejected with `ERR_SEGREGATION_OF_DUTIES`.
        Approval moves the strategy `UNDER_EVALUATION → APPROVED` and rejection moves it `UNDER_EVALUATION → REJECTED`; both record `decided_by_user_id` and `decision_rationale` and bump the `version`.

        Design: Corner/validations/strategy_submitter_cannot_also_decide_the_strategy
        """
        fixtures.reset_clock(api)
        _plan, submitted = self._submitted_strategy(api)

        decided = validate_success(
            api.post_strategy_decision(
                submitted["id"],
                factories.strategy_decision_payload("APPROVE"),
                fiduciary_headers(),
            )
        )

        assert decided["strategy_status"] == StrategyStatus.APPROVED.value
        assert decided["decided_by_user_id"] != submitted["submitted_by_user_id"]
        assert decided["version"] == submitted["version"] + 1


class TestPaginationBounds:
    """The limit accepts 1 through 100 and nothing outside it."""

    @staticmethod
    def _plan_with_one_participant(api):
        plan = fixtures.create_plan(api)
        participant = fixtures.create_participant(
            api, plan["id"], participant_reference="AC-PAGE-1"
        )
        return plan, participant

    def test_validation_pagination_limit_above_the_maximum_is_rejected(self, api):
        """A limit of 101, a limit of 0 and a negative offset are each refused.

        Every list endpoint accepts two query parameters. `limit` caps the number of records returned; it defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100. `offset` skips a number of leading records; it defaults to 0 and may not be negative. A `limit` outside 1 through 100, or an `offset` that is negative or not an integer, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422).

        Design: Corner/validations/pagination_limit_above_the_maximum_returns_422
        """
        fixtures.reset_clock(api)
        plan, _participant = self._plan_with_one_participant(api)

        for params in (
            {"plan_id": plan["id"], "limit": 101},
            {"plan_id": plan["id"], "limit": 0},
            {"plan_id": plan["id"], "offset": -1},
        ):
            validate_error(
                api.list_participants(administrator_headers(), params),
                ERR_INVALID_PAGINATION,
            )

    def test_validation_pagination_limit_at_the_maximum_is_accepted(self, api):
        """A limit of exactly 100 lists the single participant with a complete meta block.

        Every list endpoint accepts two query parameters. `limit` caps the number of records returned; it defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100. `offset` skips a number of leading records; it defaults to 0 and may not be negative. A `limit` outside 1 through 100, or an `offset` that is negative or not an integer, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422).
        List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object.

        Design: Corner/validations/pagination_limit_above_the_maximum_returns_422
        """
        fixtures.reset_clock(api)
        plan, participant = self._plan_with_one_participant(api)

        rows, meta = validate_paginated(
            api.list_participants(
                administrator_headers(), {"plan_id": plan["id"], "limit": 100}
            )
        )

        assert meta["limit"] == 100
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(rows) == 1
        assert rows[0]["id"] == participant["id"]
