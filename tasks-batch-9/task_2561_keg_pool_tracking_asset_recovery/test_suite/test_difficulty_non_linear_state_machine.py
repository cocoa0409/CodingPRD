"""Machines that loop, branch and run two dimensions at once.

The keg carries a custody dimension and a certification dimension that advance
independently, and a reconciliation claim alternates between two live states
under a hard round cap before closing.
"""

from test_helpers import (
    api_client,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    SECOND_TECHNICIAN_USER_ID,
    TECHNICIAN_USER_ID,
    TEST_USERS,
    make_brewer_headers,
    make_distributor_headers,
    make_technician_headers,
)

OPERATOR = TEST_USERS["pool_operator_headers"]
FIRST_TECHNICIAN = make_technician_headers(TECHNICIAN_USER_ID)
SECOND_TECHNICIAN = make_technician_headers(SECOND_TECHNICIAN_USER_ID)

CLOCK = "2026-08-01T23:00:00Z"

POOL = {
    "pool_code": "HB-50L",
    "size_liters": 50,
    "stainless_weight_kg": 12.5,
    "replacement_cost_cents": 23500,
    "region_code": "CO",
    "restrict_threshold_pct": 25,
    "freeze_threshold_pct": 10,
    "restricted_max_kegs_per_order": 2,
}

AGREEMENT = {"per_fill_rate_cents": 2200, "replenishment_threshold_pct": 20}


def _keg_through_the_quarantine_retest_loop():
    """One keg filled, traded, returned, booked onto a wash line, failed on the
    gauge, retested and finally released — with every intermediate read of the
    keg kept for inspection."""
    ctx = fixtures.setup_active_float(
        float_size_kegs=10,
        keg_count=4,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides=dict(AGREEMENT),
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    distributor = fixtures.create_distributor(return_incentive_rate_cents_per_keg=250)
    distributor = fixtures.sign_cooperation_agreement(
        distributor["id"], "BRONZE", "2026-08-01"
    )
    ctx["distributor"] = distributor
    ctx["center"] = fixtures.create_service_center(
        2, name="Denver Wash Line", region_code="CO", intake_buffer_hours=4
    )

    order = fixtures.order_allocated_and_dispatched(
        ctx["agreement"]["id"], 1, "2026-08-01T01:00:00Z"
    )
    keg_id = order["allocated_keg_ids"][0]
    ctx["keg_id"] = keg_id

    fixtures.fill_scan(keg_id, ctx["brewer"]["id"], "2026-08-01T02:00:00Z", "RDG")
    ctx["keg_after_fill"] = fixtures.read_keg(keg_id)
    fixtures.distribution_scan(
        keg_id, distributor["id"], "2026-08-01T03:00:00Z", "RDG"
    )
    fixtures.return_scan(keg_id, distributor["id"], "2026-08-01T04:00:00Z", "RDG")
    ctx["keg_after_return"] = fixtures.read_keg(keg_id)

    cycle = fixtures.create_service_cycle(
        keg_id, ctx["center"]["id"], "2026-08-01T05:00:00Z", headers=FIRST_TECHNICIAN
    )
    ctx["cycle_id"] = cycle["id"]
    fixtures.record_clean(
        cycle["id"],
        "2026-08-01T06:00:00Z",
        caustic_cycle_minutes=15,
        technician_id=TECHNICIAN_USER_ID,
    )
    fixtures.record_inspect(
        cycle["id"], "2026-08-01T07:00:00Z", "PASS", technician_id=TECHNICIAN_USER_ID
    )
    ctx["cycle_after_failed_test"] = fixtures.record_pressure_test(
        cycle["id"],
        "2026-08-01T08:00:00Z",
        pressure_test_psi=34,
        pressure_test_result="FAIL",
        technician_id=TECHNICIAN_USER_ID,
    )
    ctx["keg_after_failed_test"] = fixtures.read_keg(keg_id)
    ctx["cycle_after_retest"] = fixtures.record_pressure_test(
        cycle["id"],
        "2026-08-01T09:00:00Z",
        pressure_test_psi=34,
        pressure_test_result="PASS",
        technician_id=TECHNICIAN_USER_ID,
    )
    ctx["keg_after_retest"] = fixtures.read_keg(keg_id)
    ctx["cycle_after_release"] = fixtures.release_cycle(
        cycle["id"], "2026-08-01T10:00:00Z", headers=SECOND_TECHNICIAN
    )
    ctx["keg_after_release"] = fixtures.read_keg(keg_id)
    return ctx


def test_the_return_scan_closes_the_trade_leg_and_clears_the_accountability_clock():
    """The fill leaves the keg certified while it moves along the custody chain,
    and the return puts it into servicing with the distributor clock cleared.

    PRD: "The keg moves `IN_TRADE → IN_SERVICE` or `AT_RETAIL → IN_SERVICE`, the
    custody spell closes, `dwell_started_at` resets to `scanned_at`, and
    `distributor_custody_started_at` is cleared."

    Design: Difficulty/non_linear_state_machine/keg_parallel_custody_and_service_dimensions_with_quarantine_retest_loop
    """
    ctx = _keg_through_the_quarantine_retest_loop()

    assert ctx["keg_after_fill"]["custody_state"] == "FILLED"
    assert ctx["keg_after_fill"]["service_state"] == "SERVICE_OK"

    assert ctx["keg_after_return"]["custody_state"] == "IN_SERVICE"
    assert ctx["keg_after_return"]["distributor_custody_started_at"] is None


def test_a_failed_gauge_quarantines_the_keg_and_a_passing_retest_moves_custody_only():
    """The failing test drives both dimensions down together; the retest returns
    custody to servicing but leaves the certification dimension failed, because
    only a release restores it.

    PRD: "A cycle quarantined for `PRESSURE_TEST_FAIL` may be retested, and a
    passing retest overwrites the failed pressure fields and moves the keg from
    custody `QUARANTINED` back to `IN_SERVICE`."

    Design: Difficulty/non_linear_state_machine/keg_parallel_custody_and_service_dimensions_with_quarantine_retest_loop
    """
    ctx = _keg_through_the_quarantine_retest_loop()

    assert ctx["cycle_after_failed_test"]["stage"] == "QUARANTINED"
    assert ctx["cycle_after_failed_test"]["quarantine_reason"] == "PRESSURE_TEST_FAIL"
    assert ctx["keg_after_failed_test"]["custody_state"] == "QUARANTINED"
    assert ctx["keg_after_failed_test"]["service_state"] == "SERVICE_FAILED"

    assert ctx["cycle_after_retest"]["stage"] == "PRESSURE_TESTED"
    assert ctx["cycle_after_retest"]["pressure_test_result"] == "PASS"
    assert ctx["keg_after_retest"]["custody_state"] == "IN_SERVICE"
    assert ctx["keg_after_retest"]["service_state"] == "SERVICE_FAILED"


def test_release_resets_the_keg_and_dates_certification_from_the_gauge_reading():
    """Releasing the cycle returns the keg to float and recertifies it, pinning
    the certification instant to the passing retest rather than to the release,
    and giving the wash line its slot back.

    PRD: "On the keg it is a full reset: custody returns to `IN_FLOAT`,
    `service_state` becomes `SERVICE_OK`, `fills_at_last_pressure_test` is set to
    the current `fill_count`, `last_pressure_test_at` is set to the cycle's
    `pressure_tested_at` rather than to `released_at`, `current_brewer_id`,
    `current_distributor_id`, `issuance_order_id` and
    `distributor_custody_started_at` are all cleared, `dwell_started_at` is set
    to `released_at`, `dwell_flag` returns to `WITHIN_LIMIT`, and the keg's
    `version` advances."

    Design: Difficulty/non_linear_state_machine/keg_parallel_custody_and_service_dimensions_with_quarantine_retest_loop
    """
    ctx = _keg_through_the_quarantine_retest_loop()
    cycle = ctx["cycle_after_release"]
    keg = ctx["keg_after_release"]

    assert cycle["stage"] == "RELEASED"
    assert cycle["pressure_test_performed_by_user_id"] == TECHNICIAN_USER_ID
    assert cycle["released_by_user_id"] == SECOND_TECHNICIAN_USER_ID

    assert keg["custody_state"] == "IN_FLOAT"
    assert keg["service_state"] == "SERVICE_OK"
    assert keg["fills_at_last_pressure_test"] == 1
    assert keg["last_pressure_test_at"] == "2026-08-01T09:00:00Z"

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert pool["kegs_available"] == 4
    assert pool["kegs_servicing"] == 0
    assert pool["available_pct"] == 100.00
    assert pool["posture"] == "OPEN"

    center = get_success_data(
        api_client.get_service_center(ctx["center"]["id"], OPERATOR)
    )
    assert center["open_cycle_count"] == 0


def _claim_countered_to_the_round_limit():
    """A misdelivered keg, a filed claim and three alternating counters, then a
    fourth counter and an agreement both posted against the same observed
    version."""
    ctx = fixtures.setup_active_float(
        float_size_kegs=10,
        keg_count=4,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides=dict(AGREEMENT),
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    ctx["other_brewer"] = fixtures.create_brewer(
        name="Other Creek Brewing", brand_code="OTH", credit_limit_cents=400000
    )
    distributor = fixtures.create_distributor(return_incentive_rate_cents_per_keg=250)
    distributor = fixtures.sign_cooperation_agreement(
        distributor["id"], "BRONZE", "2026-08-01"
    )
    ctx["distributor"] = distributor

    order = fixtures.order_allocated_and_dispatched(
        ctx["agreement"]["id"], 1, "2026-08-01T01:00:00Z"
    )
    keg_id = order["allocated_keg_ids"][0]
    ctx["keg_id"] = keg_id
    fixtures.fill_scan(keg_id, ctx["brewer"]["id"], "2026-08-01T02:00:00Z", "RDG")
    ctx["evidence_scan"] = fixtures.distribution_scan(
        keg_id, distributor["id"], "2026-08-01T03:00:00Z", "OTH"
    )
    ctx["keg_after_evidence"] = fixtures.read_keg(keg_id)

    brewer_headers = make_brewer_headers(ctx["other_brewer"]["id"])
    distributor_headers = make_distributor_headers(distributor["id"])
    ctx["brewer_headers"] = brewer_headers
    ctx["distributor_headers"] = distributor_headers

    claim = fixtures.file_claim(
        keg_id,
        distributor["id"],
        ctx["other_brewer"]["id"],
        1500,
        "2026-08-01T03:00:00Z",
    )
    ctx["claim_at_open"] = claim
    ctx["claim_id"] = claim["id"]

    ctx["rounds"] = [
        fixtures.respond_to_claim(
            claim["id"], "COUNTER", brewer_headers, counter_offset_cents=900
        ),
        fixtures.respond_to_claim(
            claim["id"], "COUNTER", distributor_headers, counter_offset_cents=1300
        ),
        fixtures.respond_to_claim(
            claim["id"], "COUNTER", brewer_headers, counter_offset_cents=1000
        ),
    ]
    observed_version = ctx["rounds"][2]["version"]
    ctx["observed_version"] = observed_version

    ctx["fourth_counter_response"] = api_client.respond_reconciliation_claim(
        claim["id"],
        factories.claim_response_payload(
            "COUNTER", observed_version, counter_offset_cents=1250
        ),
        distributor_headers,
    )
    ctx["claim_after_refusal"] = fixtures.read_claim(claim["id"])
    ctx["agree_response"] = api_client.respond_reconciliation_claim(
        claim["id"],
        factories.claim_response_payload("AGREE", observed_version),
        distributor_headers,
    )
    return ctx


def test_counters_flip_the_claim_between_its_two_live_states():
    """Filing is the distributor's move, so the brewer counters first; each
    counter swaps the live state, raises the round count and overwrites the
    outstanding figure.

    PRD: "A `COUNTER` flips the claim between the two live states and increments
    `round_count`: from `SUBMITTED` the brewer counters into `COUNTERED`, and
    from `COUNTERED` the distributor counters back into `SUBMITTED`, each time
    overwriting `counter_offset_cents` with the new figure and stamping
    `last_responder_role` with the side that just moved."

    Design: Difficulty/non_linear_state_machine/claim_counter_negotiation_cycle_hits_round_limit_then_agrees
    """
    ctx = _claim_countered_to_the_round_limit()

    assert ctx["evidence_scan"]["misdelivery_detected"] is True
    assert ctx["keg_after_evidence"]["misdelivery_open"] is True

    opened = ctx["claim_at_open"]
    assert opened["status"] == "SUBMITTED"
    assert opened["round_count"] == 0
    assert opened["owning_brewer_id"] == ctx["brewer"]["id"]
    assert opened["misdelivered_to_brewer_id"] == ctx["other_brewer"]["id"]
    assert opened["claimant_distributor_id"] == ctx["distributor"]["id"]

    rounds = ctx["rounds"]
    assert [row["round_count"] for row in rounds] == [1, 2, 3]
    assert [row["status"] for row in rounds] == ["COUNTERED", "SUBMITTED", "COUNTERED"]
    assert [row["counter_offset_cents"] for row in rounds] == [900, 1300, 1000]
    assert [row["last_responder_role"] for row in rounds] == [
        "Brewer",
        "Distributor",
        "Brewer",
    ]


def test_the_fourth_counter_is_refused_while_agreeing_stays_available():
    """Three counters exhaust the cap, so the fourth is turned away and leaves
    the claim exactly as it stood, yet the very next response on the same
    observed version closes the claim at the outstanding figure.

    PRD: "At most 3 counters may be recorded on one claim; the fourth is refused
    with `ERR_CLAIM_ROUND_LIMIT`, while `AGREE`, `REJECT` and `WITHDRAW` remain
    available at any round count."

    Design: Difficulty/non_linear_state_machine/claim_counter_negotiation_cycle_hits_round_limit_then_agrees
    """
    ctx = _claim_countered_to_the_round_limit()

    validate_error(
        ctx["fourth_counter_response"], ApiErrorId.ERR_CLAIM_ROUND_LIMIT.value, 409
    )

    unchanged = ctx["claim_after_refusal"]
    assert unchanged["round_count"] == 3
    assert unchanged["status"] == "COUNTERED"
    assert unchanged["counter_offset_cents"] == 1000

    agreed = validate_success(ctx["agree_response"], 200)
    assert agreed["status"] == "AGREED"
    assert agreed["agreed_offset_cents"] == 1000
    assert agreed["closed_at"] is not None


def test_the_agreed_offset_pays_the_distributor_without_touching_its_returns():
    """One `RECONCILIATION_OFFSET` accrual is minted for the agreed figure and
    the ledger grows by it, while every return statistic stays at zero.

    PRD: "Crucially, a reconciliation offset is **not** a return:
    `total_returns_count`, `on_time_returns_count`, `on_time_return_pct`,
    `avg_dwell_days` and `cooperation_tier` are all left exactly as they were,
    and no tier promotion is evaluated."

    Design: Difficulty/non_linear_state_machine/claim_counter_negotiation_cycle_hits_round_limit_then_agrees
    """
    ctx = _claim_countered_to_the_round_limit()
    validate_success(ctx["agree_response"], 200)

    rows, _meta = validate_paginated(
        api_client.list_return_incentives(
            OPERATOR, params={"distributor_id": ctx["distributor"]["id"]}
        )
    )
    offsets = [row for row in rows if row["accrual_type"] == "RECONCILIATION_OFFSET"]
    assert len(offsets) == 1
    offset = offsets[0]
    assert offset["claim_id"] == ctx["claim_id"]
    assert offset["incentive_cents"] == 1000
    assert offset["dwell_days"] == 0
    # PRD fixes only `claim_id`, `incentive_cents` and `status` on an offset
    # accrual; it never says what the two dwell-band factors hold on this
    # branch, so their value is not asserted here.

    distributor = fixtures.read_distributor(ctx["distributor"]["id"])
    assert distributor["incentive_accrual_cents"] == 1000
    assert distributor["total_returns_count"] == 0
    assert distributor["on_time_return_pct"] == 0.00
    assert distributor["avg_dwell_days"] == 0.0
    assert distributor["cooperation_tier"] == "BRONZE"

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["misdelivery_open"] is False
    assert keg["custody_state"] == "IN_TRADE"
