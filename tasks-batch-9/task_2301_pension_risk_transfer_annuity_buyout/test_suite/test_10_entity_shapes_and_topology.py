"""Entity shape, derivation and topology tests for the Pension Risk Transfer API.

Every test builds its own preconditions from an empty database through declared
endpoints, and every assertion is traced back to a verbatim rule in PRD.md.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    SPONSOR_USER_ID,
    api_errors,
    assertions,
    constants,
    factories,
    fixtures,
    make_participant_headers,
)
from test_helpers.test_users import (
    administrator_headers,
    fiduciary_headers,
    regulator_headers,
    sponsor_headers,
)


# ---------------------------------------------------------------------------
# Local helpers
#
# A few endpoints are authorized to a role that no existing builder acts as,
# so those calls are made here with the role §4 names for the endpoint.
# ---------------------------------------------------------------------------


ASHCROFT_PLAN = {
    "sponsor_name": "Ashcroft Machining",
    "plan_name": "Ashcroft Salaried Plan",
    "plan_ein": "231004556",
    "total_liability_cents": 100000000,
    "plan_assets_cents": 92000000,
    "service_cost_cents": 3000000,
    "interest_cost_cents": 9000000,
    "unrecognized_actuarial_loss_cents": 4000000,
    "discount_rate_bps": 500,
}

#: A deferred-vested participant whose recomputed benefit equals the stated one.
DEFERRED_VESTED_PARTICIPANT = {
    "cohort": "DEFERRED_VESTED",
    "stated_monthly_benefit_cents": 100000,
    "final_average_monthly_earnings_cents": 250000,
    "credited_service_months": 320,
    "date_of_birth": "1968-04-04",
}


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant so two spellings of one moment compare equal."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _create_insurer(api: Any, **overrides: Any) -> Dict[str, Any]:
    """Register a carrier; the registry is the `Regulator`'s to keep."""
    payload = factories.insurer_payload(**overrides)
    return get_success_data(api.create_insurer(payload, regulator_headers()))


def _create_tranche(api: Any, plan_id: str, target_cohort: str) -> Dict[str, Any]:
    """Draft a buyout tranche as the `PlanFiduciary`."""
    payload = factories.tranche_payload(target_cohort)
    return get_success_data(api.create_tranche(plan_id, payload, fiduciary_headers()))


def _start_quoting(api: Any, tranche_id: str) -> Dict[str, Any]:
    return get_success_data(api.post_tranche_quoting(tranche_id, {}, fiduciary_headers()))


def _request_quote(api: Any, tranche_id: str, insurer_id: str) -> Dict[str, Any]:
    payload = factories.quote_request_payload(insurer_id)
    return get_success_data(api.create_quote(tranche_id, payload, fiduciary_headers()))


def _lock_pricing(api: Any, tranche_id: str) -> Dict[str, Any]:
    return get_success_data(api.post_pricing_lock(tranche_id, {}, fiduciary_headers()))


def _create_window(api: Any, plan_id: str, **overrides: Any) -> Dict[str, Any]:
    """Schedule an election window as the `PlanAdministrator`."""
    payload = factories.window_payload(**overrides)
    return get_success_data(api.create_window(plan_id, payload, administrator_headers()))


def _settle_window(api: Any, window_id: str) -> Dict[str, Any]:
    """Settlement is the `PlanSponsor`'s act."""
    return get_success_data(api.post_window_settlement(window_id, {}, sponsor_headers()))


def _cleanse_participant(api: Any, participant_id: str) -> Dict[str, Any]:
    """Walk all three cleansing dimensions so the record reaches `CLEAN`."""
    fixtures.confirm_address(api, participant_id)
    fixtures.confirm_alive(api, participant_id)
    audit = fixtures.open_benefit_audit(api, participant_id)
    fixtures.resolve_audit(api, audit["id"], "ACCEPT_AS_IS")
    return fixtures.read_participant(api, participant_id)


def _authorize_plan(
    api: Any,
    plan_id: str,
    strategy_type: str,
    amendment_scope: str,
    effective_date: str = "2026-08-01T00:00:00Z",
) -> Dict[str, Any]:
    """Approve a strategy of the given type and adopt the matching amendment."""
    fixtures.create_approved_strategy(api, plan_id, strategy_type)
    return fixtures.adopt_amendment(api, plan_id, amendment_scope, effective_date)


def _engage_expert(api: Any, plan_id: str, opinion: Optional[str] = None) -> Dict[str, Any]:
    expert = fixtures.create_expert(api, plan_id)
    expert = fixtures.review_expert(api, expert["id"], "ENGAGE")
    if opinion is not None:
        expert = fixtures.issue_opinion(api, expert["id"], opinion)
    return expert


class TestPlanEntityShape:
    """The plan resource as it is minted and as it reads back."""

    def test_entity_plan_creation_returns_inputs_and_derived_funded_status(
        self, api, sponsor
    ):
        """Creating a plan returns the stored inputs plus the fields derived at creation.

        "A new plan starts with a `plan_status` of `ONGOING`, has its
        `participant_liability_total_cents` set to 0 because it has no participants yet,
        and has its `accounting_funded_status_bp` derived immediately."
        "Its accounting figure, `accounting_funded_status_bp`, is 0 whenever
        `total_liability_cents` is 0; otherwise it is `plan_assets_cents` multiplied by
        10,000 and rounded half up over `total_liability_cents`, so a fully funded plan
        reads 10000 basis points."
        "All resources except one additionally carry `updated_at`, an ISO 8601 UTC
        timestamp refreshed on every mutation of the resource, and `version`, an integer
        that starts at 1 and increments by one on every mutation."

        Design: Corner/entities/plan_creation_returns_every_declared_field_with_computed_funded_status
        """
        response = api.create_plan(factories.plan_payload(**ASHCROFT_PLAN), sponsor)
        plan = validate_success(response, 201)

        assertions.assert_plan_shape(plan)
        assertions.assert_fields(plan, **ASHCROFT_PLAN)
        assertions.assert_fields(
            plan,
            plan_status="ONGOING",
            version=1,
            participant_liability_total_cents=0,
            accounting_funded_status_bp=constants.funded_status_bp(92000000, 100000000),
        )
        assert plan["accounting_funded_status_bp"] == 9200, plan
        assertions.assert_funded_status_consistent(plan)

    def test_entity_plan_retrieval_returns_the_stored_values_unchanged(
        self, api, regulator
    ):
        """Reading a plan back returns the same declared field values with version still 1.

        "All resources except one additionally carry `updated_at`, an ISO 8601 UTC
        timestamp refreshed on every mutation of the resource, and `version`, an integer
        that starts at 1 and increments by one on every mutation."
        "Its accounting figure, `accounting_funded_status_bp`, is 0 whenever
        `total_liability_cents` is 0; otherwise it is `plan_assets_cents` multiplied by
        10,000 and rounded half up over `total_liability_cents`, so a fully funded plan
        reads 10000 basis points."

        Design: Corner/entities/plan_retrieval_returns_the_stored_values_unchanged
        """
        created = fixtures.create_plan(api, **ASHCROFT_PLAN)

        fetched = validate_success(api.get_plan(created["id"], regulator))

        assertions.assert_plan_shape(fetched)
        for field in assertions.PLAN_FIELDS:
            assert fetched[field] == created[field], (
                "{}: read-back {!r} differs from the created {!r}".format(
                    field, fetched[field], created[field]
                )
            )
        assertions.assert_fields(
            fetched,
            version=1,
            plan_status="ONGOING",
            plan_ein="231004556",
            total_liability_cents=100000000,
            accounting_funded_status_bp=9200,
        )


class TestParticipantListing:
    """Filtering and pagination over the participant collection."""

    def test_entity_participants_listing_paginates_and_filters_by_data_status(
        self, api, administrator
    ):
        """A limited page reports the whole matching total, and the data_status filter narrows it.

        "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the
        envelope's `meta` object."
        "`limit` caps the number of records returned; it defaults to 10, its minimum
        accepted value is 1, and its maximum accepted value is 100."
        "A freshly loaded participant therefore scores 25 and is `NEEDS_REVIEW`; a
        participant who is `CONFIRMED`, `ALIVE_CONFIRMED`, and `PASSED_CLOSED` scores
        100; one who is `CONFIRMED`, `ALIVE_CONFIRMED`, and `CORRECTION_REQUIRED` scores
        85 and is still `CLEAN`; and one who is `CONFIRMED` but `UNVERIFIED` with a
        closed audit sits at exactly 80, which is `CLEAN` because the boundary is
        inclusive."

        Design: Corner/entities/participants_listing_paginates_and_filters_by_data_status
        """
        plan = fixtures.create_plan(api, **ASHCROFT_PLAN)
        first = fixtures.create_participant(
            api, plan["id"], participant_reference="AC-0001", **DEFERRED_VESTED_PARTICIPANT
        )
        cleansed = _cleanse_participant(api, first["id"])
        second = fixtures.create_participant(
            api,
            plan["id"],
            participant_reference="AC-0002",
            cohort="DEFERRED_VESTED",
            stated_monthly_benefit_cents=90000,
            final_average_monthly_earnings_cents=240000,
            credited_service_months=300,
            date_of_birth="1969-05-05",
        )
        third = fixtures.create_participant(
            api,
            plan["id"],
            participant_reference="AC-0003",
            cohort="RETIREE_IN_PAY",
            stated_monthly_benefit_cents=250000,
            final_average_monthly_earnings_cents=500000,
            credited_service_months=400,
            date_of_birth="1956-06-06",
        )

        page_rows, page_meta = validate_paginated(
            api.list_participants(administrator, {"plan_id": plan["id"], "limit": 1, "offset": 0})
        )
        assert len(page_rows) == 1, page_rows
        assert page_meta["total_count"] == 3, page_meta
        assert page_meta["has_more"] is True, page_meta
        assert page_meta["limit"] == 1, page_meta
        assert page_meta["offset"] == 0, page_meta

        clean_rows, clean_meta = validate_paginated(
            api.list_participants(administrator, {"plan_id": plan["id"], "data_status": "CLEAN"})
        )
        assert assertions.ids_of(clean_rows) == [first["id"]], clean_rows
        assert clean_meta["total_count"] == 1, clean_meta
        assert clean_meta["has_more"] is False, clean_meta

        assertions.assert_fields(cleansed, data_confidence_score=100, data_status="CLEAN")
        assertions.assert_fields(second, data_confidence_score=25, data_status="NEEDS_REVIEW")
        assertions.assert_fields(third, data_confidence_score=25, data_status="NEEDS_REVIEW")

    def test_entity_participant_get_with_unknown_id_returns_not_found(
        self, api, administrator
    ):
        """An unresolvable participant segment is the entity's own 404, not a 422.

        "Identifiers embedded in a request path are resolved strictly left to right, and
        the first identifier that does not resolve decides the error."
        "A request naming a benefit audit under a participant that does not exist fails
        with `ERR_PARTICIPANT_NOT_FOUND` before the audit is ever looked up."

        Design: Corner/entities/participant_get_with_unknown_id_returns_not_found
        """
        plan = fixtures.create_plan(api, **ASHCROFT_PLAN)
        existing = fixtures.create_participant(
            api, plan["id"], participant_reference="AC-0001", **DEFERRED_VESTED_PARTICIPANT
        )

        validate_error(
            api.get_participant(NON_EXISTENT_UUID, administrator),
            api_errors.ERR_PARTICIPANT_NOT_FOUND,
        )

        untouched = fixtures.read_participant(api, existing["id"])
        assertions.assert_fields(untouched, version=1)


class TestRequestShapePrecedence:
    """Required fields, declared enum sets and declared numeric bounds."""

    def test_entity_plan_creation_missing_plan_ein_returns_invalid_request(
        self, api, sponsor
    ):
        """Omitting plan_ein is a request-shape failure even alongside a negative amount.

        "The families below are evaluated in the order listed; the first family that
        finds a violation decides the response, and later families are not consulted."
        "**Request shape** — every required field present, every value of the correct
        JSON type, every enum value drawn from its declared set, else
        `ERR_INVALID_REQUEST` (HTTP 422)."
        "A `PlanSponsor` registers a defined benefit plan by supplying the sponsor's
        `sponsor_name`, the plan's `plan_name`, and its `plan_ein` — the sponsor's
        employer identification number, which must be exactly nine digits and must be
        unique across all registered plans."

        Design: Corner/entities/plan_creation_missing_plan_ein_returns_invalid_request
        """
        payload = factories.plan_payload(**ASHCROFT_PLAN)
        payload.pop("plan_ein")
        payload["plan_assets_cents"] = -5

        validate_error(api.create_plan(payload, sponsor), api_errors.ERR_INVALID_REQUEST)

    def test_entity_participant_cohort_enum_rejects_a_value_outside_the_declared_set(
        self, api, administrator
    ):
        """A cohort outside RETIREE_IN_PAY and DEFERRED_VESTED is a request-shape failure.

        "**Request shape** — every required field present, every value of the correct
        JSON type, every enum value drawn from its declared set, else
        `ERR_INVALID_REQUEST` (HTTP 422)."
        "A `PlanAdministrator` loads participants into the plan one at a time, supplying
        a `participant_reference` between 1 and 40 characters that must be unique within
        the plan, a `cohort` of either `RETIREE_IN_PAY` or `DEFERRED_VESTED`, the
        `stated_monthly_benefit_cents` from the sponsor's records (at least 1), the
        `final_average_monthly_earnings_cents` (at least 1), the
        `credited_service_months` (an integer from 0 through 600), and the participant's
        `date_of_birth`."

        Design: Corner/entities/participant_cohort_enum_rejects_a_value_outside_the_declared_set
        """
        plan = fixtures.create_plan(api, **ASHCROFT_PLAN)
        payload = factories.participant_payload(
            participant_reference="AC-0011",
            cohort="SURVIVING_SPOUSE",
            stated_monthly_benefit_cents=100000,
            final_average_monthly_earnings_cents=250000,
            credited_service_months=320,
            date_of_birth="1968-04-04",
        )

        validate_error(
            api.create_participant(plan["id"], payload, administrator),
            api_errors.ERR_INVALID_REQUEST,
        )

        _rows, meta = validate_paginated(
            api.list_participants(administrator, {"plan_id": plan["id"]})
        )
        assert meta["total_count"] == 0, meta

    def test_entity_participant_service_months_above_the_declared_bound_is_invalid_amount(
        self, api, administrator
    ):
        """Credited service of 601 months breaches the declared 0..600 bound.

        "**Numeric ranges** — money fields at least 0, `discount_rate_bps` within 1
        through 2000, `credited_service_months` within 0 through 600, `capital_ratio_bp`
        within 0 through 20000, `lock_days` within 1 through 180, `quote_valid_days`
        within 1 through 90, `plan_ein` exactly nine digits, and
        `remediation_amount_cents` consistent with the responsibility determination; else
        `ERR_INVALID_AMOUNT` (HTTP 422)."

        Design: Corner/entities/participant_cohort_enum_rejects_a_value_outside_the_declared_set
        """
        plan = fixtures.create_plan(api, **ASHCROFT_PLAN)
        payload = factories.participant_payload(
            participant_reference="AC-0012",
            cohort="DEFERRED_VESTED",
            stated_monthly_benefit_cents=100000,
            final_average_monthly_earnings_cents=250000,
            credited_service_months=601,
            date_of_birth="1968-04-04",
        )

        validate_error(
            api.create_participant(plan["id"], payload, administrator),
            api_errors.ERR_INVALID_AMOUNT,
        )

        _rows, meta = validate_paginated(
            api.list_participants(administrator, {"plan_id": plan["id"]})
        )
        assert meta["total_count"] == 0, meta


class TestExpertDefaults:
    """The declared default on a proposed expert engagement."""

    def test_entity_expert_conflict_disclosed_defaults_to_false_when_omitted(
        self, api, sponsor
    ):
        """An omitted conflict_disclosed lands false, in a fresh INDEPENDENCE_REVIEW engagement.

        "A `PlanSponsor` proposes an expert by supplying an `expert_firm_name` between 1
        and 200 characters, an `engagement_scope` describing what the firm is retained to
        opine on, and an optional `conflict_disclosed` boolean that defaults to false and
        states whether the firm disclosed a relationship with any candidate carrier."
        "The proposal starts in `INDEPENDENCE_REVIEW`, records `proposed_by_user_id` from
        the acting `X-User-ID`, and leaves `reviewed_by_user_id`,
        `safest_available_opinion`, and `opinion_issued_at` null."

        Design: Corner/entities/expert_conflict_disclosed_defaults_to_false_when_omitted
        """
        plan = fixtures.create_plan(api, **ASHCROFT_PLAN)
        payload = factories.expert_payload(
            "Wrenfield Fiduciary Counsel",
            engagement_scope="SAFEST_AVAILABLE_ANNUITY_REVIEW",
        )
        assert "conflict_disclosed" not in payload, payload

        expert = validate_success(api.create_expert(plan["id"], payload, sponsor), 201)

        assertions.assert_expert_shape(expert)
        assertions.assert_fields(
            expert,
            conflict_disclosed=False,
            expert_status="INDEPENDENCE_REVIEW",
            proposed_by_user_id=SPONSOR_USER_ID,
            plan_id=plan["id"],
            version=1,
        )
        assertions.assert_null_fields(
            expert, "reviewed_by_user_id", "safest_available_opinion", "opinion_issued_at"
        )


class TestParticipantDerivedFields:
    """Fields the server computes rather than accepts, and their recomputation."""

    def test_entity_participant_computed_fields_derive_and_recompute_on_cleansing(
        self, api, administrator
    ):
        """Liability follows the cohort factor while the confidence score is re-derived each step.

        "Otherwise the effective monthly amount is multiplied by twelve, the annual
        amount is multiplied by the factor for the participant's `cohort`, and the
        product is rounded half up over 10,000."
        "For `accounting_liability_cents` the factor is 118,000 basis points for
        `RETIREE_IN_PAY` and 95,500 for `DEFERRED_VESTED`; for
        `settlement_liability_cents` it is 126,250 for `RETIREE_IN_PAY` and 104,500 for
        `DEFERRED_VESTED`."
        "A freshly loaded participant therefore scores 25 and is `NEEDS_REVIEW`; a
        participant who is `CONFIRMED`, `ALIVE_CONFIRMED`, and `PASSED_CLOSED` scores
        100; one who is `CONFIRMED`, `ALIVE_CONFIRMED`, and `CORRECTION_REQUIRED` scores
        85 and is still `CLEAN`; and one who is `CONFIRMED` but `UNVERIFIED` with a
        closed audit sits at exactly 80, which is `CLEAN` because the boundary is
        inclusive."
        "The score is recomputed on every mutation of `address_status`,
        `mortality_status`, `benefit_audit_status`, `date_of_birth`, or `ssn_last4`."

        Design: Corner/entities/participant_computed_fields_derive_from_inputs_and_recompute_on_cleansing
        """
        plan = fixtures.create_plan(api, **ASHCROFT_PLAN)
        payload = factories.participant_payload(
            participant_reference="AC-0009", **DEFERRED_VESTED_PARTICIPANT
        )

        created = validate_success(api.create_participant(plan["id"], payload, administrator), 201)

        expected_accounting = constants.accounting_liability(100000, "DEFERRED_VESTED")
        assert expected_accounting == 11460000, expected_accounting
        assertions.assert_participant_shape(created)
        assertions.assert_fields(
            created,
            data_confidence_score=25,
            data_status="NEEDS_REVIEW",
            address_status="UNCONFIRMED",
            mortality_status="UNVERIFIED",
            benefit_audit_status="NOT_AUDITED",
            address_search_attempts=0,
            address_search_tier="NONE",
            audited_monthly_benefit_cents=100000,
            accounting_liability_cents=expected_accounting,
            settlement_liability_cents=constants.settlement_liability(100000, "DEFERRED_VESTED"),
        )
        assertions.assert_null_fields(created, "tranche_id")

        after_address = fixtures.confirm_address(api, created["id"])
        assertions.assert_fields(
            after_address,
            address_status="CONFIRMED",
            data_confidence_score=65,
            data_status="NEEDS_REVIEW",
            accounting_liability_cents=expected_accounting,
        )

        after_mortality = fixtures.confirm_alive(api, created["id"])
        assertions.assert_fields(
            after_mortality,
            mortality_status="ALIVE_CONFIRMED",
            data_confidence_score=85,
            data_status="CLEAN",
            accounting_liability_cents=expected_accounting,
            settlement_liability_cents=constants.settlement_liability(100000, "DEFERRED_VESTED"),
        )

    def test_entity_participant_system_fields_track_the_logical_clock_not_wall_time(
        self, api, administrator
    ):
        """created_at is stamped from the logical clock and only the mutated row's version moves.

        "Time in this system is not wall-clock time."
        "The server maintains a logical clock whose value at startup is exactly
        `2026-08-01T00:00:00Z`, and which may only be moved by an administrative
        test-driving capability that accepts a `current_utc` instant and sets the clock
        to it."
        "Every resource the API mints carries an `id` that is a server-generated UUID
        with no type prefix, and a `created_at` timestamp that is an ISO 8601 UTC instant
        with three fractional digits taken from the logical clock at creation."
        "All resources except one additionally carry `updated_at`, an ISO 8601 UTC
        timestamp refreshed on every mutation of the resource, and `version`, an integer
        that starts at 1 and increments by one on every mutation."

        Design: Corner/entities/participant_system_fields_track_the_logical_clock_not_wall_time
        """
        plan = fixtures.create_plan(api, **ASHCROFT_PLAN)
        first = fixtures.create_participant(
            api, plan["id"], participant_reference="AC-0010", **DEFERRED_VESTED_PARTICIPANT
        )
        assertions.assert_common_fields(first)
        assert _instant(first["created_at"]) == _instant(constants.CLOCK_EPOCH), first["created_at"]
        assertions.assert_fields(first, version=1)

        fixtures.set_clock(api, "2026-08-05T00:00:00Z")
        second = fixtures.create_participant(
            api,
            plan["id"],
            participant_reference="AC-0011",
            cohort="DEFERRED_VESTED",
            stated_monthly_benefit_cents=90000,
            final_average_monthly_earnings_cents=240000,
            credited_service_months=300,
            date_of_birth="1969-05-05",
        )
        assert _instant(second["created_at"]) == _instant("2026-08-05T00:00:00Z"), second
        assert second["id"] != first["id"], "ids must be distinct server-generated UUIDs"

        mutated = fixtures.confirm_address(api, first["id"])
        assertions.assert_fields(mutated, version=2)
        assert _instant(mutated["created_at"]) == _instant(constants.CLOCK_EPOCH), mutated
        assert _instant(mutated["updated_at"]) == _instant("2026-08-05T00:00:00Z"), mutated

        sibling = fixtures.read_participant(api, second["id"])
        assertions.assert_fields(sibling, version=1)


class TestSettlementLedgerImmutability:
    """The one resource that carries no version and is never mutated."""

    def test_entity_settlement_entry_is_immutable_with_no_version(self, api, regulator):
        """A lump-sum recognition entry exposes created_at and posted_at but no version.

        "Settlement entries are append-only and are never mutated after they are written,
        so a `SettlementEntry` carries only `id` and `created_at`: it has neither
        `updated_at` nor `version`."
        "It records its own write instant separately in `posted_at`, taken from the
        logical clock when the entry was appended."
        "Its `pbo_settled_cents` is the sum of the paid participants'
        `accounting_liability_cents`, its `amount_cents` is `paid_lump_sum_total_cents`
        minus that `pbo_settled_cents`, and its `deferred_amount_cents` is 0 — a lump-sum
        disbursement is recognised immediately and nothing is held back in accumulated
        other comprehensive income."

        Design: Corner/entities/settlement_entry_is_immutable_with_no_version_and_no_write_endpoint
        """
        plan = fixtures.create_plan(api, **ASHCROFT_PLAN)
        participant = fixtures.create_participant(
            api,
            plan["id"],
            participant_reference="AC-0020",
            cohort="DEFERRED_VESTED",
            stated_monthly_benefit_cents=20000,
            final_average_monthly_earnings_cents=50000,
            credited_service_months=320,
            date_of_birth="1967-07-07",
        )
        _cleanse_participant(api, participant["id"])
        _authorize_plan(api, plan["id"], "LUMP_SUM_WINDOW", "LUMP_SUM_ONLY")

        window = _create_window(
            api,
            plan["id"],
            opens_at="2026-08-01T00:00:00Z",
            closes_at="2026-09-30T00:00:00Z",
            window_name="Ashcroft Window One",
            lump_sum_cap_cents=5000000,
            eligibility_max_lump_sum_cents=15000000,
        )
        fixtures.open_window(api, window["id"])

        election = fixtures.election_for(api, window["id"], participant["id"])
        fixtures.elect(api, election["id"], participant["id"], "LUMP_SUM")

        fixtures.set_clock(api, "2026-09-30T00:00:00Z")
        fixtures.close_window(api, window["id"])
        settled = _settle_window(api, window["id"])

        raw_pv = constants.raw_lump_sum_pv(20000, "DEFERRED_VESTED")
        net = constants.net_lump_sum_cents_for(raw_pv)
        pbo_settled = constants.accounting_liability(20000, "DEFERRED_VESTED")
        assert raw_pv == 2400000 and net == 2400000, (raw_pv, net)
        assert pbo_settled == 2292000, pbo_settled
        assertions.assert_fields(settled, paid_lump_sum_total_cents=net)

        rows, meta = validate_paginated(
            api.list_settlement_entries(
                regulator, {"plan_id": plan["id"], "entry_type": "LUMP_SUM_RECOGNITION"}
            )
        )
        assert meta["total_count"] == 1, meta
        entry = validate_success(api.get_settlement_entry(rows[0]["id"], regulator))

        assertions.assert_settlement_entry_shape(entry)
        assert "version" not in entry, "a settlement entry must not carry a version"
        assert "updated_at" not in entry, "a settlement entry must not carry updated_at"
        assertions.assert_fields(
            entry,
            entry_type="LUMP_SUM_RECOGNITION",
            plan_id=plan["id"],
            window_id=window["id"],
            pbo_settled_cents=pbo_settled,
            amount_cents=net - pbo_settled,
            deferred_amount_cents=0,
        )
        assertions.assert_null_fields(entry, "tranche_id")


class TestQuoteParentReferences:
    """An annuity quote resolves a path parent and a body-supplied carrier."""

    def test_entity_quote_creation_requires_an_existing_tranche_and_insurer(
        self, api, fiduciary
    ):
        """The unknown tranche in the path and the unknown insurer in the body fail differently.

        "The full set of not-found errors is `ERR_PLAN_NOT_FOUND`,
        `ERR_STRATEGY_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`,
        `ERR_WINDOW_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`, `ERR_TRANCHE_NOT_FOUND`,
        `ERR_QUOTE_NOT_FOUND`, `ERR_INSURER_NOT_FOUND`, `ERR_EXPERT_NOT_FOUND`,
        `ERR_TRANSFER_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, and
        `ERR_SETTLEMENT_ENTRY_NOT_FOUND`, each carrying HTTP 404."
        "A quote request naming an `insurer_id` that does not exist fails with
        `ERR_INSURER_NOT_FOUND`; a tranche assignment naming a `participant_id` that does
        not exist fails with `ERR_PARTICIPANT_NOT_FOUND`. Path resolution always precedes
        body-identifier resolution."
        "A created quote starts in `REQUESTED` with `requested_at` stamped from the
        logical clock, records its `tranche_id` and `insurer_id`, leaves `premium_cents`,
        `lock_days`, `quote_valid_days`, `submitted_at`, `expires_at`,
        `rating_at_submission`, `composite_score_bp`, and `decline_reason` null, and
        bumps the tranche's `version`."

        Design: Corner/entities/quote_creation_requires_an_existing_tranche_and_a_registered_insurer
        """
        plan = fixtures.create_plan(api, **ASHCROFT_PLAN)
        participant = fixtures.create_participant(
            api, plan["id"], participant_reference="AC-0030", **DEFERRED_VESTED_PARTICIPANT
        )
        _cleanse_participant(api, participant["id"])
        _authorize_plan(api, plan["id"], "ANNUITY_BUYOUT", "BUYOUT_ONLY")
        _engage_expert(api, plan["id"])
        tranche = _create_tranche(api, plan["id"], "DEFERRED_VESTED")
        fixtures.assign_participant(api, tranche["id"], participant["id"])
        _start_quoting(api, tranche["id"])
        insurer = _create_insurer(
            api,
            insurer_name="Beacon National Life",
            rating_grade="AA_MINUS",
            capital_ratio_bp=3800,
            capacity_cents=200000000,
        )

        validate_error(
            api.create_quote(
                NON_EXISTENT_UUID, factories.quote_request_payload(insurer["id"]), fiduciary
            ),
            api_errors.ERR_TRANCHE_NOT_FOUND,
        )
        validate_error(
            api.create_quote(
                tranche["id"], factories.quote_request_payload(NON_EXISTENT_UUID), fiduciary
            ),
            api_errors.ERR_INSURER_NOT_FOUND,
        )

        quote = validate_success(
            api.create_quote(
                tranche["id"], factories.quote_request_payload(insurer["id"]), fiduciary
            ),
            201,
        )
        assertions.assert_quote_shape(quote)
        assertions.assert_fields(
            quote,
            tranche_id=tranche["id"],
            insurer_id=insurer["id"],
            quote_status="REQUESTED",
            version=1,
        )
        assertions.assert_null_fields(
            quote,
            "premium_cents",
            "lock_days",
            "quote_valid_days",
            "submitted_at",
            "expires_at",
            "rating_at_submission",
            "composite_score_bp",
            "decline_reason",
        )

        _rows, meta = validate_paginated(
            api.list_quotes(fiduciary, {"tranche_id": tranche["id"]})
        )
        assert meta["total_count"] == 1, meta


class TestHybridTopology:
    """Cross-cutting associations resolved from both directions."""

    def test_entity_hybrid_topology_quote_links_tranche_and_insurer(
        self, api, fiduciary, administrator
    ):
        """The bound quote is addressable by tranche and carrier at once, and the complaint points sideways.

        "Selection stores the declared `selection_basis`, writes every candidate quote's
        `composite_score_bp`, and records the winner's identifiers and score in the
        tranche's `selected_quote_id`, `selected_insurer_id`, and `selection_score_bp`."
        "Alongside all of that the selected quote transitions `LOCKED → BOUND`, the
        tranche stamps `settled_at`, and every entity touched bumps its `version`."
        "Second, every assigned participant transitions `ASSIGNED →
        TRANSFERRED_TO_INSURER`."
        "When a `tranche_id` is supplied it must be a tranche the participant was
        actually assigned to, and a mismatch is rejected with
        `ERR_QUOTE_TRANCHE_MISMATCH`; when omitted, the complaint snapshots the
        participant's `tranche_id` as it stood at filing, which is null for lump-sum and
        residual participants."

        Design: Corner/entities/hybrid_topology_quote_links_tranche_and_insurer_across_the_hierarchy
        """
        plan = fixtures.create_plan(api, **ASHCROFT_PLAN)
        participant = fixtures.create_participant(
            api, plan["id"], participant_reference="AC-0040", **DEFERRED_VESTED_PARTICIPANT
        )
        _cleanse_participant(api, participant["id"])
        _authorize_plan(api, plan["id"], "ANNUITY_BUYOUT", "BUYOUT_ONLY")
        _engage_expert(api, plan["id"], "AFFIRMATIVE")
        insurer = _create_insurer(
            api,
            insurer_name="Beacon National Life",
            rating_grade="AA_MINUS",
            capital_ratio_bp=3800,
            capacity_cents=200000000,
        )

        tranche = _create_tranche(api, plan["id"], "DEFERRED_VESTED")
        fixtures.assign_participant(api, tranche["id"], participant["id"])
        _start_quoting(api, tranche["id"])
        quote = _request_quote(api, tranche["id"], insurer["id"])
        fixtures.submit_quote(
            api, quote["id"], insurer["id"], premium_cents=11800000, lock_days=90,
            quote_valid_days=60,
        )
        fixtures.select_insurer(api, tranche["id"], "SAFETY_WEIGHTED")
        locked = _lock_pricing(api, tranche["id"])
        transfer = fixtures.initiate_in_kind_transfer(
            api, tranche["id"], 12000000, 2, locked["version"]
        )
        fixtures.review_transfer(api, transfer["id"], insurer["id"], "ACCEPT")
        settled = fixtures.settle_tranche(api, tranche["id"])

        complaint_payload = factories.complaint_payload(
            "ANNUITY_FORM",
            tranche["id"],
            complaint_narrative=(
                "The annuity form the carrier set up is not the joint-and-survivor "
                "form I elected."
            ),
        )
        complaint = validate_success(
            api.create_complaint(
                participant["id"],
                complaint_payload,
                make_participant_headers(participant["id"]),
            ),
            201,
        )

        linked_rows, linked_meta = validate_paginated(
            api.list_quotes(
                fiduciary, {"tranche_id": tranche["id"], "insurer_id": insurer["id"]}
            )
        )
        assert linked_meta["total_count"] == 1, linked_meta
        assert assertions.ids_of(linked_rows) == [quote["id"]], linked_rows
        assertions.assert_fields(linked_rows[0], quote_status="BOUND")

        assertions.assert_complaint_shape(complaint)
        assertions.assert_fields(
            complaint, participant_id=participant["id"], tranche_id=tranche["id"]
        )

        complaint_rows, complaint_meta = validate_paginated(
            api.list_complaints(administrator, {"tranche_id": tranche["id"]})
        )
        assert complaint_meta["total_count"] == 1, complaint_meta
        assert assertions.ids_of(complaint_rows) == [complaint["id"]], complaint_rows

        assertions.assert_fields(
            settled,
            selected_insurer_id=insurer["id"],
            selected_quote_id=quote["id"],
            tranche_status="SETTLED",
        )
        assertions.assert_fields(
            fixtures.read_participant(api, participant["id"]),
            participant_status="TRANSFERRED_TO_INSURER",
        )
