"""Lifecycles that are not a straight line: parallel dimensions and a bounded cycle."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures


def test_shut_in_royalties_cycle_the_obligation_dimension_without_moving_tenure(api):
    """Two royalty payments cycle the lease through OBLIGATION_DUE and CURED while tenure stays SHUT_IN_HELD.

    For a shut-in payment that is the only circumstance in which the obligation dimension changes.
    A `CURED` lease returns to `COMPLIANT` once no open obligation date lies within 30 days of the clock date, and a `CURED` lease moves back to `OBLIGATION_DUE` once the next obligation date falls within that 30-day window — which is exactly how a lease held by shut-in royalties cycles from `COMPLIANT` to `OBLIGATION_DUE` to `CURED` and back to `OBLIGATION_DUE` once per anniversary.

    Design: Difficulty/non_linear_state_machine/lease_tenure_and_obligation_dimensions_advance_independently
    """
    context = fixtures.setup_pooled_producing_well(api, clock="2026-08-05T00:00:00Z")
    lease1_id = context["lease1_id"]
    lease2_id = context["lease2_id"]

    fixtures.change_status(api, context["well_id"], "SHUT_IN", "2026-08-01")

    validate_success(
        api.record_obligation_event(
            lease1_id,
            factories.obligation_event_payload(
                "SHUT_IN_PAYMENT", "2026-08-05", shut_in_start_date="2026-08-01"
            ),
            fixtures.LAND_ADMIN,
        ),
        200,
    )
    lease = validate_success(api.get_lease(lease1_id, fixtures.LAND_ADMIN), 200)
    assert lease["tenure_status"] == "SHUT_IN_HELD"
    assert lease["obligation_status"] == "COMPLIANT"
    assert lease["shut_in_payments_made"] == 1
    # 2026-08-01 plus 90 days plus 365 days for the payment already made.
    assert lease["shut_in_next_due_date"] == "2027-10-30"

    fixtures.set_clock(api, "2027-10-05T00:00:00Z")
    first_run = fixtures.run_obligation_pass(api)
    assert first_run["leases_flagged_obligation_due"] == 1

    lease = validate_success(api.get_lease(lease1_id, fixtures.LAND_ADMIN), 200)
    assert lease["obligation_status"] == "OBLIGATION_DUE"
    assert lease["tenure_status"] == "SHUT_IN_HELD"
    other = validate_success(api.get_lease(lease2_id, fixtures.LAND_ADMIN), 200)
    assert other["obligation_status"] == "COMPLIANT"
    assert other["tenure_status"] == "PRIMARY_TERM"

    validate_success(
        api.record_obligation_event(
            lease1_id,
            factories.obligation_event_payload("SHUT_IN_PAYMENT", "2027-10-05"),
            fixtures.LAND_ADMIN,
        ),
        200,
    )
    lease = validate_success(api.get_lease(lease1_id, fixtures.LAND_ADMIN), 200)
    assert lease["obligation_status"] == "CURED"
    assert lease["tenure_status"] == "SHUT_IN_HELD"
    assert lease["shut_in_payments_made"] == 2
    assert lease["shut_in_next_due_date"] == "2028-10-29"

    fixtures.set_clock(api, "2027-11-01T00:00:00Z")
    second_run = fixtures.run_obligation_pass(api)
    assert second_run["leases_expired"] == 0

    lease = validate_success(api.get_lease(lease1_id, fixtures.LAND_ADMIN), 200)
    assert lease["obligation_status"] == "COMPLIANT"
    assert lease["tenure_status"] == "SHUT_IN_HELD"


def test_the_dispute_exchange_runs_two_rounds_and_refuses_a_third_rebuttal(api):
    """Answer and rebuttal alternate twice, then the round cap stops the partner.

    `PARTNER_REBUTTAL`, by a `PartnerRepresentative`, requires `dispute_status` of `OPERATOR_RESPONDED` (else `ERR_DISPUTE_NOT_RESOLVABLE`, 409), the clock's date on or before `rebuttal_due_date` (else `ERR_REBUTTAL_DEADLINE_PASSED`, 422), and `round_count` strictly less than 2 (else `ERR_MAX_DISPUTE_ROUNDS_EXCEEDED`, 422).
    A prompt response therefore shortens the partner's remaining rebuttal time compared with the original schedule; the rebuttal window is measured from the answer, not from the filing.

    Design: Difficulty/non_linear_state_machine/dispute_exchange_cycle_two_rounds_then_round_cap
    """
    context = fixtures.setup_disputed_statement(
        api,
        clock="2026-08-10T00:00:00Z",
        disputed_amount_cents=100_000,
        basis_note="Overhead allocation on the capital pool is contested",
    )
    dispute_id = context["dispute_id"]
    partner_headers = context["partner_b_headers"]

    filed = context["dispute"]
    assert filed["round_count"] == 0
    assert filed["response_due_date"] == "2026-10-09"

    def respond(note):
        return validate_success(
            api.create_dispute_exchange(
                dispute_id,
                factories.dispute_exchange_payload("OPERATOR_RESPONSE", note),
                fixtures.JIB_ACCOUNTANT,
            ),
            200,
        )

    def rebut(note):
        return api.create_dispute_exchange(
            dispute_id,
            factories.dispute_exchange_payload("PARTNER_REBUTTAL", note),
            partner_headers,
        )

    def read():
        return validate_success(
            api.get_dispute(dispute_id, fixtures.JIB_ACCOUNTANT), 200
        )

    respond("Round 1 operator answer with supporting vouchers")
    dispute = read()
    assert dispute["dispute_status"] == "OPERATOR_RESPONDED"
    assert dispute["rebuttal_due_date"] == "2026-09-09"

    validate_success(rebut("Round 1 rebuttal: vouchers do not cover the overhead basis"), 200)
    dispute = read()
    assert dispute["dispute_status"] == "OPEN"
    assert dispute["round_count"] == 1
    assert dispute["response_due_date"] == "2026-10-09"

    respond("Round 2 operator answer")
    validate_success(rebut("Round 2 rebuttal"), 200)
    dispute = read()
    assert dispute["dispute_status"] == "OPEN"
    assert dispute["round_count"] == 2

    respond("Round 3 operator answer")
    assert read()["dispute_status"] == "OPERATOR_RESPONDED"

    validate_error(
        rebut("Round 3 rebuttal, must be refused"),
        "ERR_MAX_DISPUTE_ROUNDS_EXCEEDED",
        422,
    )

    dispute = read()
    assert dispute["dispute_status"] == "OPERATOR_RESPONDED"
    assert dispute["round_count"] == 2

    statement = validate_success(
        api.get_jib_statement(context["statement_id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert statement["statement_status"] == "DISPUTED"
