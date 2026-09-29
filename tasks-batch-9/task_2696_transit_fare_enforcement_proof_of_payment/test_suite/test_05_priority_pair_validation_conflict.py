"""
Requests that break two rules at once, where the ordered validation walk fixes
which of the two errors is reported.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_DOWN_PAYMENT_BELOW_MINIMUM,
    ERR_ENCOUNTER_NOT_PENDING,
    ERR_IDENTITY_NOT_ESTABLISHED,
    ERR_INSTALLMENT_COUNT_OUT_OF_RANGE,
    ERR_PAYMENT_AMOUNT_INVALID,
    ERR_PLAN_NOT_ACTIVE,
)
from test_helpers.assertions import (
    assert_installment_schedule,
    ids_of,
    sole_row_with_source,
)
from test_helpers.constants import (
    IDENTITY_REFUSED,
    OUTCOME_PENDING,
    OUTCOME_UNRESOLVED_IDENTITY,
    PAYMENT_SOURCE_DOWN_PAYMENT,
    PLAN_STATUS_ACTIVE,
    PLAN_STATUS_COMPLETED,
    SETTLEMENT_OUTSTANDING,
    SETTLEMENT_PLAN_ACTIVE,
    SETTLEMENT_SATISFIED,
)
from test_helpers.test_users import make_fare_inspector_headers, make_rider_headers


# ── Encounter state before identity safety on issuance ───────────────

def _terminal_and_pending_identity_refused_encounters(api):
    """
    Two identity-refused encounters on one deployment: the first already resolved
    to a terminal outcome, the second still pending.
    """
    env = fixtures.build_environment(api)
    deployment = fixtures.build_active_deployment(api, env)
    inspector_id = env["inspector"]["id"]

    terminal = fixtures.build_pending_encounter(
        api,
        env,
        deployment,
        occurred_at="2026-08-05T07:00:00Z",
        identity_capture_method=IDENTITY_REFUSED,
    )
    fixtures.resolve(api, terminal["id"], inspector_id, "UNRESOLVED_IDENTITY")
    pending = fixtures.build_pending_encounter(
        api,
        env,
        deployment,
        occurred_at="2026-08-05T08:00:00Z",
        identity_capture_method=IDENTITY_REFUSED,
    )
    return env, terminal, pending


def test_the_terminal_encounter_reports_its_state_not_its_missing_identity(api):
    """
    The encounter must be `PENDING`; any other outcome is refused with
    `ERR_ENCOUNTER_NOT_PENDING`, and that refusal is reached before the rule
    that an `identity_capture_method` of `REFUSED` is refused with
    `ERR_IDENTITY_NOT_ESTABLISHED`, even though this request breaks both.

    Design: Difficulty/priority_pair_validation_conflict/encounter_state_rule_precedes_identity_safety_rule_on_citation_issuance
    """
    env, terminal, _pending = _terminal_and_pending_identity_refused_encounters(api)

    response = api.create_citation(
        factories.citation_payload(terminal["id"]),
        make_fare_inspector_headers(env["inspector"]["id"]),
    )
    validate_error(response, ERR_ENCOUNTER_NOT_PENDING, 409)
    assert response.json()["data"]["error_id"] != ERR_IDENTITY_NOT_ESTABLISHED

    assert (
        fixtures.read_encounter(api, terminal["id"])["outcome"]
        == OUTCOME_UNRESOLVED_IDENTITY
    )


def test_removing_the_state_violation_exposes_the_identity_violation(api):
    """
    Where the encounter is `PENDING` the lower-priority rule is still live: an
    `identity_capture_method` of `REFUSED` is refused with
    `ERR_IDENTITY_NOT_ESTABLISHED`, so neither request leaves a citation behind.

    Design: Difficulty/priority_pair_validation_conflict/encounter_state_rule_precedes_identity_safety_rule_on_citation_issuance
    """
    env, terminal, pending = _terminal_and_pending_identity_refused_encounters(api)
    inspector_headers = make_fare_inspector_headers(env["inspector"]["id"])
    api.create_citation(factories.citation_payload(terminal["id"]), inspector_headers)

    validate_error(
        api.create_citation(factories.citation_payload(pending["id"]), inspector_headers),
        ERR_IDENTITY_NOT_ESTABLISHED,
        422,
    )

    assert fixtures.read_encounter(api, pending["id"])["outcome"] == OUTCOME_PENDING
    for encounter_id in (terminal["id"], pending["id"]):
        rows, meta = validate_paginated(
            api.list_citations(inspector_headers, {"encounter_id": encounter_id})
        )
        assert meta["total_count"] == 0, f"a citation exists against {encounter_id}"
        assert rows == []
    assert fixtures.read_rider(api, env["rider"]["id"])["prior_citation_count"] == 0


# ── Installment count before the down-payment floor ──────────────────

def _first_offence_citation_owing_9720(api):
    """A first-offence no-proof citation: assessed 9000, fee 720, total 9720."""
    chain = fixtures.build_citation_chain(api)
    assert chain["citation"]["total_due_cents"] == 9720
    return chain


def test_an_out_of_range_installment_count_is_reported_before_the_thin_down_payment(api):
    """
    `installment_count` must be between 2 and 6 inclusive, otherwise
    `ERR_INSTALLMENT_COUNT_OUT_OF_RANGE`; that refusal is reached before the rule
    that a down payment below one tenth of the outstanding balance is refused
    with `ERR_DOWN_PAYMENT_BELOW_MINIMUM`.

    Design: Difficulty/priority_pair_validation_conflict/installment_count_constraint_precedes_down_payment_fiscal_floor
    """
    chain = _first_offence_citation_owing_9720(api)
    citation = chain["citation"]

    response = api.create_payment_plan(
        factories.payment_plan_payload(
            citation_id=citation["id"],
            installment_count=9,
            down_payment_cents=100,
            expected_citation_version=citation["version"],
        ),
        make_rider_headers(chain["rider"]["id"]),
    )
    validate_error(response, ERR_INSTALLMENT_COUNT_OUT_OF_RANGE, 422)
    assert response.json()["data"]["error_id"] != ERR_DOWN_PAYMENT_BELOW_MINIMUM


def test_a_legal_installment_count_then_exposes_the_down_payment_floor(api):
    """
    With the count inside 2 to 6 the fiscal rule is still live: 100 cents against
    an outstanding balance of 9720 is below the statutory tenth and is refused
    with `ERR_DOWN_PAYMENT_BELOW_MINIMUM`, leaving the citation untouched.

    Design: Difficulty/priority_pair_validation_conflict/installment_count_constraint_precedes_down_payment_fiscal_floor
    """
    chain = _first_offence_citation_owing_9720(api)
    citation = chain["citation"]
    rider_headers = make_rider_headers(chain["rider"]["id"])

    api.create_payment_plan(
        factories.payment_plan_payload(
            citation_id=citation["id"],
            installment_count=9,
            down_payment_cents=100,
            expected_citation_version=citation["version"],
        ),
        rider_headers,
    )
    validate_error(
        api.create_payment_plan(
            factories.payment_plan_payload(
                citation_id=citation["id"],
                installment_count=3,
                down_payment_cents=100,
                expected_citation_version=citation["version"],
            ),
            rider_headers,
        ),
        ERR_DOWN_PAYMENT_BELOW_MINIMUM,
        422,
    )

    unchanged = fixtures.read_citation(api, citation["id"])
    assert unchanged["settlement_status"] == SETTLEMENT_OUTSTANDING
    assert unchanged["version"] == citation["version"]


def test_correcting_both_violations_opens_the_plan_on_the_pinned_schedule(api):
    """
    A request that satisfies both rules succeeds: the down payment leaves
    `financed_cents` at 8720, the base amount is that figure divided by the count
    rounded down and the remainder sits in the final installment.

    Design: Difficulty/priority_pair_validation_conflict/installment_count_constraint_precedes_down_payment_fiscal_floor
    """
    chain = _first_offence_citation_owing_9720(api)
    citation = chain["citation"]
    rider_headers = make_rider_headers(chain["rider"]["id"])

    plan = validate_success(
        api.create_payment_plan(
            factories.payment_plan_payload(
                citation_id=citation["id"],
                installment_count=3,
                down_payment_cents=1000,
                expected_citation_version=citation["version"],
            ),
            rider_headers,
        ),
        201,
    )
    assert plan["financed_cents"] == 8720
    assert plan["base_installment_cents"] == 2906
    assert plan["final_installment_cents"] == 2908
    assert plan["status"] == PLAN_STATUS_ACTIVE
    assert_installment_schedule(plan)

    financed = fixtures.read_citation(api, citation["id"])
    assert financed["settlement_status"] == SETTLEMENT_PLAN_ACTIVE
    assert financed["amount_paid_cents"] == 1000
    assert financed["outstanding_balance_cents"] == 8720


# ── Plan state before the installment amount ─────────────────────────

def _one_completed_plan_and_one_active_plan(api):
    """
    One rider with two citations: the first paid off through a completed plan,
    the second carrying a live 3-installment plan.
    """
    env = fixtures.build_environment(api)
    deployment = fixtures.build_active_deployment(api, env)
    inspector_id = env["inspector"]["id"]
    rider_id = env["rider"]["id"]
    rider_headers = make_rider_headers(rider_id)

    first_encounter = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at="2026-08-05T07:00:00Z"
    )
    first_citation = fixtures.issue_citation(api, first_encounter["id"], inspector_id)
    completed = fixtures.get_success_data(
        api.create_payment_plan(
            factories.payment_plan_payload(
                citation_id=first_citation["id"],
                installment_count=2,
                down_payment_cents=1000,
                expected_citation_version=first_citation["version"],
            ),
            rider_headers,
        )
    )
    for _ in range(2):
        fixtures.get_success_data(
            api.pay_installment(
                completed["id"], factories.installment_payload(4360), rider_headers
            )
        )

    second_encounter = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at="2026-08-05T08:00:00Z"
    )
    second_citation = fixtures.issue_citation(api, second_encounter["id"], inspector_id)
    active = fixtures.get_success_data(
        api.create_payment_plan(
            factories.payment_plan_payload(
                citation_id=second_citation["id"],
                installment_count=3,
                down_payment_cents=2500,
                expected_citation_version=second_citation["version"],
            ),
            rider_headers,
        )
    )
    return {
        "env": env,
        "rider_headers": rider_headers,
        "first_citation": first_citation,
        "second_citation": second_citation,
        "completed_plan": completed,
        "active_plan": active,
    }


def test_a_completed_plan_reports_its_status_not_the_unscheduled_amount(api):
    """
    The plan must be `ACTIVE` — a `COMPLETED`, `DEFAULTED` or `CANCELLED` plan is
    refused with `ERR_PLAN_NOT_ACTIVE` — and that refusal is reached before the
    rule that an amount other than the next scheduled one is refused with
    `ERR_PAYMENT_AMOUNT_INVALID`.

    Design: Difficulty/priority_pair_validation_conflict/plan_state_rule_precedes_installment_amount_fiscal_rule
    """
    world = _one_completed_plan_and_one_active_plan(api)
    completed = fixtures.read_plan(api, world["completed_plan"]["id"])
    assert completed["status"] == PLAN_STATUS_COMPLETED
    assert completed["installments_paid_count"] == 2
    assert completed["remaining_balance_cents"] == 0

    response = api.pay_installment(
        completed["id"], factories.installment_payload(999), world["rider_headers"]
    )
    validate_error(response, ERR_PLAN_NOT_ACTIVE, 409)
    assert response.json()["data"]["error_id"] != ERR_PAYMENT_AMOUNT_INVALID

    settled = fixtures.read_citation(api, world["first_citation"]["id"])
    assert settled["settlement_status"] == SETTLEMENT_SATISFIED
    assert settled["outstanding_balance_cents"] == 0


def test_the_active_plan_reports_the_amount_rule_and_records_nothing(api):
    """
    Against an `ACTIVE` plan the same amount reaches the fiscal rule instead: the
    submitted amount must equal the scheduled amount of the next unpaid
    installment exactly, so 999 is refused with `ERR_PAYMENT_AMOUNT_INVALID` and
    the append-only ledger still shows only the down payment.

    Design: Difficulty/priority_pair_validation_conflict/plan_state_rule_precedes_installment_amount_fiscal_rule
    """
    world = _one_completed_plan_and_one_active_plan(api)
    active_id = world["active_plan"]["id"]

    validate_error(
        api.pay_installment(
            active_id, factories.installment_payload(999), world["rider_headers"]
        ),
        ERR_PAYMENT_AMOUNT_INVALID,
        422,
    )

    plan = fixtures.read_plan(api, active_id)
    assert plan["status"] == PLAN_STATUS_ACTIVE
    assert plan["installments_paid_count"] == 0
    assert plan["base_installment_cents"] == 5886

    second = fixtures.read_citation(api, world["second_citation"]["id"])
    assert second["offense_sequence"] == 2
    assert second["total_due_cents"] == 20160

    rows, meta = validate_paginated(
        api.list_plan_payments(active_id, world["rider_headers"])
    )
    assert meta["total_count"] == 1
    assert ids_of(rows)
    down = sole_row_with_source(rows, PAYMENT_SOURCE_DOWN_PAYMENT)
    assert down["amount_cents"] == 2500
