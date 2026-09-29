"""Endpoint semantics: the loss monitor read, the logical-clock sweep, the
escalation booking's three associations, and the builder-funded repair arm.

Every test builds its own world from scratch through PRD-declared endpoints,
because the server is restarted with an empty database before each test.
"""

import pytest

from test_helpers import (
    ADJUSTER_USER_ID,
    INSURER_PERIOD_INSTANT,
    ApiErrorId,
    assert_claim,
    assert_escalation_case,
    assert_loss_monitor,
    assert_neutral,
    assert_policy,
    assert_same_instant,
    builder_response_payload,
    create_escalation_payload,
    create_neutral,
    enroll_policy,
    invoice_policy,
    make_builder_principal_headers,
    make_homeowner_headers,
    pay_policy_premium,
    read_builder,
    read_loss_monitor,
    read_policy,
    record_session_outcome,
    repair_completion_payload,
    set_clock,
    set_clock_payload,
    setup_active_policy,
    setup_builder_arm_claim,
    setup_denied_claim,
    setup_routed_claim,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_loss_monitor_reports_the_denominator_population_beside_the_ratio(
    api, underwriting_officer_headers
):
    """The monitor read returns the two populations behind the ratio, and the
    denominator population excludes a paid-but-not-yet-activated home.

    PRD Section 3.2: "Carrier staff read the monitor directly through a computed
    view that returns the four stored figures - `earned_premium_cents`,
    `incurred_loss_cents`, `loss_ratio` and `monitoring_posture` - alongside the
    two populations behind them."

    PRD Section 3.2: "`policy_count` is the size of the denominator population:
    the number of this builder's policies that are in `ACTIVE` or `EXPIRED`
    coverage state and `PAID` premium state."

    PRD Section 3.2: "`open_claim_count` is the number of claims on any policy of
    this builder whose `status` is not one of the six terminal claim states,
    namely `CLOSED_REPAIRED`, `CLOSED_PAID`, `CLOSED_SETTLED`, `CLOSED_AWARDED`,
    `CLOSED_DENIED_FINAL` and `SUSPENDED_NO_LIMIT`."

    PRD Section 3.2: "The denominator, `earned_premium_cents`, is the sum of
    `premium_cents` over the builder's policies that are both in a coverage state
    of `ACTIVE` or `EXPIRED` and in a premium state of `PAID`; a policy still in
    `PENDING_ENROLLMENT`, or one whose premium is not `PAID`, contributes
    nothing."

    PRD Section 3.2: "`monitoring_posture` is a band on the rounded ratio with
    lower bounds inclusive: `OPEN` below 0.6500, `WATCH` from 0.6500 up to but
    not including 0.9000, `RESTRICTED` from 0.9000 up to but not including
    1.2000, and `FROZEN` at 1.2000 or above."

    Design: Corner/Table 5 Endpoints/the_loss_monitor_read_reports_the_denominator_population_beside_the_ratio
    """
    scenario = setup_routed_claim(
        claimed_amount_cents=500_000,
        substantiation_ratio=1.00,
        coverage_type="STRUCTURAL",
        defect_category="WATER_INTRUSION",
        claim_instant=INSURER_PERIOD_INSTANT,
    )
    builder = scenario["builder"]
    claim = scenario["claim"]
    assert_claim(claim)
    assert claim["obligor"] == "INSURER"
    assert claim["status"] == "INSURER_ADJUDICATION"
    # 500,000 substantiated in full, less the 100,000 structural-term deductible,
    # with the provisional net below 500,000 so no betterment applies.
    assert claim["reserve_cents"] == 400_000
    assert claim["incurred_authorized_cents"] == 400_000

    # A second home for the same builder, paid but never activated: it must sit
    # outside both the numerator and the denominator population.
    second = enroll_policy(
        builder["id"],
        scenario["homeowner"]["id"],
        street_address="9 Restricted Row",
        purchase_price_cents=5_000_000,
        closing_date="2028-09-01",
        posture_override_acknowledged=True,
    )
    assert second["premium_cents"] == 44_881
    invoice_policy(second["id"])
    paid_second = pay_policy_premium(second["id"], builder["id"])
    assert_policy(paid_second)
    assert paid_second["premium_status"] == "PAID"
    assert paid_second["coverage_status"] == "PENDING_ENROLLMENT"

    monitor = validate_success(
        api.get_loss_monitor(builder["id"], underwriting_officer_headers)
    )
    assert_loss_monitor(monitor)
    assert monitor["earned_premium_cents"] == 363_894
    assert monitor["policy_count"] == 1
    assert monitor["incurred_loss_cents"] == 400_000
    assert float(monitor["loss_ratio"]) == pytest.approx(1.0992, abs=1e-9)
    assert monitor["monitoring_posture"] == "RESTRICTED"
    assert monitor["open_claim_count"] == 1

    builder_row = read_builder(builder["id"])
    assert builder_row["earned_premium_cents"] == monitor["earned_premium_cents"]
    assert builder_row["incurred_loss_cents"] == monitor["incurred_loss_cents"]
    assert float(builder_row["loss_ratio"]) == pytest.approx(
        float(monitor["loss_ratio"]), abs=1e-9
    )
    assert builder_row["monitoring_posture"] == monitor["monitoring_posture"]


def test_clock_sweep_reports_its_own_elapsed_counts_and_refuses_to_run_backwards(
    api, compliance_officer_headers, underwriting_officer_headers
):
    """Each advance of the logical clock reports only the rows that this advance
    moved, a repeat of the same instant moves nothing, and an earlier instant is
    refused outright.

    PRD Section 3.4: "Advancing the clock runs an expiry sweep. The sweep does two
    things in order. Every coverage term whose `status` is `OPEN` and whose
    `end_date` falls before the new clock date transitions to the terminal
    `ELAPSED`."

    PRD Section 3.4: "Then every policy whose `coverage_status` is `ACTIVE` and
    whose `BASE` term of type `STRUCTURAL` has an `end_date` before the new clock
    date transitions from `ACTIVE` to `EXPIRED` - the structural term is the
    longest of the three, so its lapse is the lapse of the whole warranty."

    PRD Section 3.4: "The response reports the clock's new value as `current_utc`
    together with `expired_policy_count`, the number of policies moved to
    `EXPIRED`, and `elapsed_term_count`, the number of terms moved to `ELAPSED`."

    PRD Section 3.4: "The clock never regresses: an instant earlier than the
    current one is refused with `ERR_CLOCK_REGRESSION`."

    PRD Section 3.4: "No loss-ratio recompute is needed after a sweep, because an
    `EXPIRED` policy remains in the denominator population exactly as an `ACTIVE`
    one does."

    Design: Corner/Table 5 Endpoints/the_clock_sweep_reports_its_own_elapsed_counts_and_refuses_to_run_backwards
    """
    scenario = setup_active_policy()
    policy = scenario["policy"]
    assert policy["coverage_status"] == "ACTIVE"

    # 2028-09-01 is past the WORKMANSHIP end (2027-08-14) and the SYSTEMS end
    # (2028-08-14) but not the STRUCTURAL end (2036-08-14).
    first = validate_success(
        api.set_clock(set_clock_payload("2028-09-01T00:00:00Z"),
                      compliance_officer_headers)
    )
    assert_same_instant(first["current_utc"], "2028-09-01T00:00:00Z")
    assert first["elapsed_term_count"] == 2
    assert first["expired_policy_count"] == 0

    # 2036-08-15 is past the STRUCTURAL end, so the last term elapses and the
    # whole warranty expires with it.
    second = validate_success(
        api.set_clock(set_clock_payload("2036-08-15T00:00:00Z"),
                      compliance_officer_headers)
    )
    assert_same_instant(second["current_utc"], "2036-08-15T00:00:00Z")
    assert second["elapsed_term_count"] == 1
    assert second["expired_policy_count"] == 1

    # The very same instant is not "earlier than the current one", so it is
    # accepted - and finds nothing left to move.
    third = validate_success(
        api.set_clock(set_clock_payload("2036-08-15T00:00:00Z"),
                      compliance_officer_headers)
    )
    assert_same_instant(third["current_utc"], "2036-08-15T00:00:00Z")
    assert third["elapsed_term_count"] == 0
    assert third["expired_policy_count"] == 0

    validate_error(
        api.set_clock(set_clock_payload("2030-01-01T00:00:00Z"),
                      compliance_officer_headers),
        ApiErrorId.ERR_CLOCK_REGRESSION.value,
    )
    # The refused call left the clock at 2036-08-15: an instant that would be a
    # legal advance from 2030-01-01 is still a regression from where we are.
    validate_error(
        api.set_clock(set_clock_payload("2033-01-01T00:00:00Z"),
                      compliance_officer_headers),
        ApiErrorId.ERR_CLOCK_REGRESSION.value,
    )

    expired_policy = read_policy(policy["id"])
    assert_policy(expired_policy)
    assert expired_policy["coverage_status"] == "EXPIRED"
    assert expired_policy["premium_status"] == "PAID"

    elapsed_terms, terms_meta = validate_paginated(
        api.list_policy_coverage_terms(
            policy["id"], underwriting_officer_headers,
            {"status": "ELAPSED", "limit": 100, "offset": 0},
        )
    )
    assert terms_meta["total_count"] == 3
    assert len(elapsed_terms) == 3
    assert all(term["status"] == "ELAPSED" for term in elapsed_terms)

    monitor = validate_success(
        api.get_loss_monitor(scenario["builder"]["id"], underwriting_officer_headers)
    )
    assert_loss_monitor(monitor)
    assert monitor["earned_premium_cents"] == 363_894
    assert monitor["policy_count"] == 1


def test_booking_an_escalation_links_the_claim_the_neutral_and_the_prior_case(
    api, compliance_officer_headers
):
    """A booking writes three associations - the claim it contests, the neutral it
    books and, on the arbitration rung only, the mediation that authorised it -
    and all three are visible as list filters.

    PRD Section 3.9: "The request names the `stage` being opened - `MEDIATION` or
    `ARBITRATION` - the `neutral_id` to book, a `window_start` and a `window_end`
    bounding the session as ISO 8601 UTC instants where `window_end` must be
    strictly later than `window_start`, and, for arbitration, the `prior_case_id`
    of the mediation case that authorises it."

    PRD Section 3.9: "A successful booking creates an escalation case against the
    claim named in its `claim_id`, in `status` `SCHEDULED`, with `binding` false
    for a `MEDIATION` case and true for an `ARBITRATION` case - `binding` is
    derived from the stage and is never supplied by the client."

    PRD Section 3.9: "The booked neutral's `booked_session_count` is incremented by
    1 and its `version` advances by 1; that counter is the number of escalation
    cases naming this neutral whose `status` is `SCHEDULED`, `SETTLED`, `IMPASSE`
    or `AWARD_ISSUED`."

    PRD Section 2.6: "Escalation cases are filterable by `claim_id`, `neutral_id`,
    `prior_case_id`, `stage` and `status`, and filtering by `neutral_id` is also
    how a client inspects a booking conflict on the panel."

    Design: Corner/Table 5 Endpoints/booking_an_escalation_links_the_claim_the_neutral_and_the_prior_case
    """
    scenario = setup_denied_claim(
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        coverage_type="STRUCTURAL",
        defect_category="WATER_INTRUSION",
    )
    claim = scenario["claim"]
    assert claim["status"] == "DENIED"
    neutral = create_neutral(full_name="Dana Okafor", credential="BOTH")
    assert_neutral(neutral)
    assert neutral["booked_session_count"] == 0
    owner_headers = make_homeowner_headers(scenario["homeowner"]["id"])

    mediation = validate_success(
        api.create_escalation(
            claim["id"],
            create_escalation_payload(
                neutral["id"], "MEDIATION",
                "2028-09-10T14:00:00Z", "2028-09-10T18:00:00Z",
            ),
            owner_headers,
        ),
        201,
    )
    assert_escalation_case(mediation)
    assert mediation["claim_id"] == claim["id"]
    assert mediation["neutral_id"] == neutral["id"]
    assert mediation["stage"] == "MEDIATION"
    assert mediation["status"] == "SCHEDULED"
    assert mediation["binding"] is False
    # No mediation authorises a mediation, so the predecessor link is unset.
    assert mediation.get("prior_case_id") is None

    set_clock("2028-09-10T15:00:00Z")
    record_session_outcome(mediation["id"], "IMPASSE",
                           adjuster_user_id=ADJUSTER_USER_ID)

    arbitration = validate_success(
        api.create_escalation(
            claim["id"],
            create_escalation_payload(
                neutral["id"], "ARBITRATION",
                "2028-09-25T14:00:00Z", "2028-09-25T18:00:00Z",
                prior_case_id=mediation["id"],
            ),
            owner_headers,
        ),
        201,
    )
    assert_escalation_case(arbitration)
    assert arbitration["claim_id"] == claim["id"]
    assert arbitration["neutral_id"] == neutral["id"]
    assert arbitration["stage"] == "ARBITRATION"
    assert arbitration["status"] == "SCHEDULED"
    assert arbitration["binding"] is True
    assert arbitration["prior_case_id"] == mediation["id"]

    by_claim, by_claim_meta = validate_paginated(
        api.list_escalation_cases(compliance_officer_headers,
                                  {"claim_id": claim["id"]})
    )
    assert by_claim_meta["total_count"] == 2
    assert {row["id"] for row in by_claim} == {mediation["id"], arbitration["id"]}

    _, by_neutral_meta = validate_paginated(
        api.list_escalation_cases(compliance_officer_headers,
                                  {"neutral_id": neutral["id"]})
    )
    assert by_neutral_meta["total_count"] == 2

    by_prior, by_prior_meta = validate_paginated(
        api.list_escalation_cases(compliance_officer_headers,
                                  {"prior_case_id": mediation["id"]})
    )
    assert by_prior_meta["total_count"] == 1
    assert by_prior[0]["id"] == arbitration["id"]

    booked_neutral = validate_success(
        api.get_neutral(neutral["id"], compliance_officer_headers)
    )
    assert_neutral(booked_neutral)
    assert booked_neutral["booked_session_count"] == 2


def test_repair_completion_is_available_only_after_the_builder_accepts(api):
    """The completion report is reachable only from `BUILDER_REPAIR_ACCEPTED` and
    only by the builder, and closing the claim that way moves no insurer money at
    all.

    PRD Section 3.7: "When the `obligor` is `BUILDER`, routing advances the claim
    `UNDER_INVESTIGATION -> BUILDER_OBLIGATION_NOTICE`. The settlement waterfall
    runs under the builder-obligation variant, writing `betterment_cents` and
    `net_payable_cents` and forcing `deductible_applied_cents` to 0 - the builder
    repairs in kind, so no policy deductible is charged to the homeowner. Both
    `reserve_cents` and `incurred_authorized_cents` remain 0, because the builder
    and not the carrier funds this arm, and no builder loss-ratio recompute
    occurs."

    PRD Section 3.7: "Because the builder variant zeroes the deductible at step 3,
    its provisional net is larger, which means step 5 can select a higher
    betterment tier for the builder arm than the insurer arm would select on the
    identical claim inputs."

    PRD Section 3.7: "`ACCEPT_OBLIGATION` advances the claim
    `BUILDER_OBLIGATION_NOTICE -> BUILDER_REPAIR_ACCEPTED` and advances its
    `version` by 1; nothing financial moves. When the repair is finished the same
    builder reports a `completion_date`, and the claim advances
    `BUILDER_REPAIR_ACCEPTED -> CLOSED_REPAIRED`, a terminal state reached with
    zero insurer money: `reserve_cents`, `paid_cents`, `released_cents` and
    `incurred_authorized_cents` are all still 0."

    PRD Section 2.8, rung 12: "From-state admission (409). The addressed row is in
    a declared origin state for the requested transition, or the matching state
    error: ... `ERR_INVALID_CLAIM_STATE` ... Applies to every state-transition
    endpoint."

    PRD Section 2.1: "If both headers are present but the value of `X-User-Role` is
    not one of the five role names declared below, or is a declared role that does
    not appear in the authorized-roles list of the endpoint being called, the
    request is refused with `ERR_ROLE_NOT_PERMITTED` and HTTP 403." The authorized
    role for `POST /warranty/claims/{id}/repair-completion` is `BuilderPrincipal`
    alone.

    Design: Corner/Table 5 Endpoints/repair_completion_is_available_only_after_the_builder_accepts_the_obligation
    """
    scenario = setup_builder_arm_claim(
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        coverage_type="STRUCTURAL",
        defect_category="WATER_INTRUSION",
    )
    claim = scenario["claim"]
    builder_headers = make_builder_principal_headers(scenario["builder"]["id"])
    owner_headers = make_homeowner_headers(scenario["homeowner"]["id"])
    assert_claim(claim)
    assert claim["obligor"] == "BUILDER"
    assert claim["status"] == "BUILDER_OBLIGATION_NOTICE"
    assert claim["gross_adjusted_cents"] == 1_750_000
    assert claim["deductible_applied_cents"] == 0
    # Provisional net 1,750,000 is at or above 1,500,000, so the builder arm takes
    # the 8 percent tier: 1,750,000 - 140,000.
    assert claim["betterment_cents"] == 140_000
    assert claim["net_payable_cents"] == 1_610_000
    assert claim["reserve_cents"] == 0
    assert claim["incurred_authorized_cents"] == 0

    # Completion is declared only out of BUILDER_REPAIR_ACCEPTED; the notice state
    # is not an origin state for it.
    validate_error(
        api.create_repair_completion(
            claim["id"], repair_completion_payload("2026-10-01"), builder_headers
        ),
        ApiErrorId.ERR_INVALID_CLAIM_STATE.value,
    )

    accepted = validate_success(
        api.create_builder_response(
            claim["id"],
            builder_response_payload("ACCEPT_OBLIGATION",
                                     response_note="Crew scheduled for October"),
            builder_headers,
        )
    )
    assert_claim(accepted)
    assert accepted["status"] == "BUILDER_REPAIR_ACCEPTED"
    assert accepted["obligor"] == "BUILDER"
    assert accepted["version"] == claim["version"] + 1
    assert accepted["net_payable_cents"] == 1_610_000
    assert accepted["reserve_cents"] == 0

    # The homeowner is not on the authorized-roles list for this endpoint.
    validate_error(
        api.create_repair_completion(
            claim["id"], repair_completion_payload("2026-10-01"), owner_headers
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )

    closed = validate_success(
        api.create_repair_completion(
            claim["id"], repair_completion_payload("2026-10-01"), builder_headers
        )
    )
    assert_claim(closed)
    assert closed["status"] == "CLOSED_REPAIRED"
    assert closed["version"] == accepted["version"] + 1
    assert closed["reserve_cents"] == 0
    assert closed["paid_cents"] == 0
    assert closed["released_cents"] == 0
    assert closed["incurred_authorized_cents"] == 0

    monitor = read_loss_monitor(scenario["builder"]["id"])
    assert_loss_monitor(monitor)
    assert monitor["incurred_loss_cents"] == 0
    assert float(monitor["loss_ratio"]) == pytest.approx(0.0, abs=1e-9)
    assert monitor["monitoring_posture"] == "OPEN"
    # CLOSED_REPAIRED is one of the six terminal claim states.
    assert monitor["open_claim_count"] == 0
