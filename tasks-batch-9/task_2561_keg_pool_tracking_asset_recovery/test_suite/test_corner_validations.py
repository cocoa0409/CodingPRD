"""Admission-ladder corners: which of several simultaneously true failures speaks.

Every scenario here is built so that two or more rules of §2.8 are violated by the
same request, or so that a conditional rule is presented with an input it must not
judge.  The interesting assertion is never merely "it failed" but *which* rule
answered, and that the losing rule becomes visible once the winner is satisfied.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    factories,
    fixtures,
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
    make_technician_headers,
)

OPERATOR = TEST_USERS["pool_operator_headers"]
TECHNICIAN = make_technician_headers(TECHNICIAN_USER_ID)
SECOND_TECHNICIAN = make_technician_headers(SECOND_TECHNICIAN_USER_ID)
CLOCK = "2026-08-01T23:00:00Z"
POOL = {
    "pool_code": "HB-50L",
    "size_liters": 50,
    "stainless_weight_kg": 12.5,
    "replacement_cost_cents": 23500,
    "region_code": "CO",
}
RATE = 2200


def test_a_brewer_posting_a_pool_is_refused_for_its_role_not_its_payload():
    """The body is missing the required `pool_code`, so the request is doubly bad —
    but the authorised-role list is consulted at step 2, long before the shape checks
    at step 4, so the caller sees the role failure and no pool is created.

    PRD: "2. The acting role appears in the target operation's authorised-role list
    — `ERR_FORBIDDEN_ROLE` (403)."

    PRD: "4. Request shape: required fields present, JSON types correct, enum values
    inside their declared domain, integers inside their declared range, ISO 8601
    instants parseable, dates in `YYYY-MM-DD` form, and no conditionally forbidden
    field supplied — for example a `brewer_id` on a scan whose `party_type` is
    `DISTRIBUTOR`. Failure is `ERR_INVALID_REQUEST` (400)."

    PRD: "Checks are evaluated in a fixed precedence order, and the first check that
    fails determines the response; no later check may mask an earlier one."

    Design: Corner/validations/forbidden_role_outranks_the_invalid_pool_payload
    """
    fixtures.pin_clock(CLOCK)
    brewer = fixtures.create_brewer()

    headless_pool = {
        "size_liters": 50,
        "stainless_weight_kg": 12.5,
        "replacement_cost_cents": 23500,
        "region_code": "CO",
    }
    response = api_client.create_pool(headless_pool, make_brewer_headers(brewer["id"]))
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    as_the_operator = api_client.create_pool(headless_pool, OPERATOR)
    validate_error(as_the_operator, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_an_unresolvable_brewer_actor_outranks_the_missing_scan_field():
    """The header names a brewer id that no row carries, and the scan body is also
    missing its required `brand_code_scanned`, and a `FILL` is illegal from
    `IN_FLOAT` besides.  Actor resolution sits at step 3, so it answers, and the
    scan stream stays empty.

    PRD: "3. For the entity-backed roles `Brewer` and `Distributor`, `X-User-ID`
    names an existing row of that entity — `ERR_UNKNOWN_ACTOR` (403). This applies to
    every operation whose authorised roles include `Brewer` or `Distributor`."

    PRD: "18. The requested `scan_point` is legal for the keg's current
    `custody_state` — `ERR_SCAN_SEQUENCE_INVALID` (409), on any scan."

    PRD: "Every accepted scan raises the keg's `scan_count` by one, adds the newly
    closed `dwell_days_closed` into the keg's `cumulative_dwell_days`, and advances
    the keg's `version`."

    Design: Corner/validations/unknown_actor_outranks_the_missing_scan_field_returns_403
    """
    fixtures.pin_clock(CLOCK)
    pool = fixtures.create_pool(**POOL)
    keg = fixtures.import_keg(pool["id"], "K-0001")

    response = api_client.scan_keg(
        keg["id"],
        {
            "scan_point": "FILL",
            "party_type": "BREWER",
            "scanned_at": "2026-08-01T02:00:00Z",
        },
        make_brewer_headers(NON_EXISTENT_UUID),
    )
    validate_error(response, ApiErrorId.ERR_UNKNOWN_ACTOR, 403)

    _, meta = validate_paginated(
        api_client.list_scan_events(OPERATOR, {"keg_id": keg["id"]})
    )
    assert meta["total_count"] == 0

    unchanged = fixtures.read_keg(keg["id"])
    assert unchanged["scan_count"] == 0
    assert unchanged["version"] == keg["version"]


def _one_real_pool_holding_one_keg():
    fixtures.pin_clock(CLOCK)
    pool = fixtures.create_pool(**POOL)
    keg = fixtures.import_keg(pool["id"], "K-0001")
    return {"pool": pool, "keg": keg}


def test_a_zero_limit_is_judged_before_the_pool_id_is_resolved():
    """`limit` 0 is outside the 1-to-100 window, and the pool id in the path belongs
    to nothing at all.  The pagination window is checked at step 5 and path
    identifiers only at step 6, so both calls — the one on a phantom pool and the one
    on the real pool — answer identically.

    PRD: "5. On every list operation, `limit` is an integer between 1 and 100
    inclusive and `offset` is an integer of at least 0 — `ERR_INVALID_PAGINATION`
    (400)."

    PRD: "6. Every path identifier resolves, left to right — the 404 catalogue
    above."

    Design: Corner/validations/invalid_pagination_outranks_the_unknown_pool_lookup
    """
    ctx = _one_real_pool_holding_one_keg()

    on_a_phantom_pool = api_client.list_pool_kegs(
        NON_EXISTENT_UUID, OPERATOR, {"limit": 0}
    )
    validate_error(on_a_phantom_pool, ApiErrorId.ERR_INVALID_PAGINATION, 400)

    on_the_real_pool = api_client.list_pool_kegs(
        ctx["pool"]["id"], OPERATOR, {"limit": 0}
    )
    validate_error(on_the_real_pool, ApiErrorId.ERR_INVALID_PAGINATION, 400)


def test_the_not_found_path_is_reachable_once_the_window_is_legal():
    """With a legal window the same phantom pool id now produces its own 404, which
    proves the earlier verdict was about the window and not about the id; the control
    call on the real pool returns the keg.

    PRD: "A path identifier that does not resolve produces the 404 belonging to that
    resource type: `ERR_BREWER_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`,
    `ERR_POOL_NOT_FOUND`, `ERR_KEG_NOT_FOUND`, `ERR_SCAN_EVENT_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_SERVICE_CENTER_NOT_FOUND`, `ERR_SERVICE_CYCLE_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_ACCRUAL_NOT_FOUND` or
    `ERR_INVESTIGATION_NOT_FOUND`."

    PRD: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`,
    `has_more`) are included for list endpoints."

    Design: Corner/validations/invalid_pagination_outranks_the_unknown_pool_lookup
    """
    ctx = _one_real_pool_holding_one_keg()

    missing = api_client.list_pool_kegs(
        NON_EXISTENT_UUID, OPERATOR, {"limit": 20, "offset": 0}
    )
    validate_error(missing, ApiErrorId.ERR_POOL_NOT_FOUND, 404)

    rows, meta = validate_paginated(
        api_client.list_pool_kegs(ctx["pool"]["id"], OPERATOR, {"limit": 20})
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [ctx["keg"]["id"]]


def test_a_foreign_brewer_is_refused_the_agreement_it_does_not_hold():
    """`Brewer` is an authorised role on the agreement read, so nothing but the
    ownership test at step 8 stands between the second brewer and the first brewer's
    contract: it answers 403 rather than 404, because the row is found before
    ownership is judged, while the lessee itself and the operator both read it.

    PRD: "8. Entity-backed ownership of the now-known target resource —
    `ERR_NOT_RESOURCE_OWNER` (403), on every operation whose authorised roles include
    `Brewer` or `Distributor` and that names an existing resource."

    PRD: "For both entity-backed roles, if `X-User-ID` does not match any existing row
    of the corresponding entity the request is rejected with `ERR_UNKNOWN_ACTOR` (HTTP
    403); if it matches an existing row but not the row the target resource points at,
    the rejection is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    PRD: "A drafted agreement opens in `status` `DRAFT` with `float_posture`
    `HEALTHY`, every counter at zero — `kegs_issued_count`, `kegs_at_brewer_count`,
    `pending_replenishment_kegs`, `billed_fills_count` and `billed_amount_cents` — and
    `effective_date` and `terminated_reason` unset."

    Design: Corner/validations/brewer_cannot_read_another_brewers_float_agreement
    """
    fixtures.pin_clock(CLOCK)
    lessee = fixtures.create_brewer()
    stranger = fixtures.create_brewer(name="Oak Street Ales", brand_code="OAK")
    pool = fixtures.create_pool(**POOL)
    agreement = fixtures.create_agreement(
        lessee["id"], pool["id"], 2, per_fill_rate_cents=RATE
    )

    refused = api_client.get_float_agreement(
        agreement["id"], make_brewer_headers(stranger["id"])
    )
    validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

    as_the_lessee = validate_success(
        api_client.get_float_agreement(
            agreement["id"], make_brewer_headers(lessee["id"])
        )
    )
    assert as_the_lessee["brewer_id"] == lessee["id"]
    assert as_the_lessee["status"] == "DRAFT"
    assert as_the_lessee["float_posture"] == "HEALTHY"

    as_the_operator = validate_success(
        api_client.get_float_agreement(agreement["id"], OPERATOR)
    )
    assert as_the_operator["id"] == agreement["id"]


def _a_second_order_allocated_on_a_version_captured_too_early():
    """A one-keg pool with two single-keg orders raised while it still reads 100.00.
    The first allocation empties it, which freezes the pool, suspends the float and
    bumps the agreement — so the version captured at activation is now stale, and the
    second allocation violates four rules at once.
    """
    fixtures.pin_clock(CLOCK)
    fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer()
    pool = fixtures.create_pool(**POOL)
    fixtures.import_keg(pool["id"], "K-0001")
    agreement = fixtures.create_agreement(
        brewer["id"], pool["id"], 2, per_fill_rate_cents=RATE
    )
    activated = fixtures.activate_agreement(agreement["id"], "2026-08-01")
    stale_version = activated["version"]
    first_order = fixtures.create_order(agreement["id"], 1)
    second_order = fixtures.create_order(agreement["id"], 1)
    fixtures.allocate_order(first_order["id"], agreement["id"])
    return {
        "brewer": brewer,
        "pool": pool,
        "agreement": agreement,
        "stale_version": stale_version,
        "first_order": first_order,
        "second_order": second_order,
        "refusal": api_client.allocate_issuance_order(
            second_order["id"],
            {"expected_agreement_version": stale_version},
            OPERATOR,
        ),
    }


def test_a_stale_agreement_version_answers_before_the_frozen_pool_does():
    """Stale version, frozen pool, suspended float and an empty candidate set are all
    true of the same request, and the concurrency guard at step 9 outranks every one
    of them — the agreement's version really has moved, because the first allocation
    recomputed its posture.

    PRD: "9. The supplied `expected_agreement_version`, `expected_keg_version` or
    `expected_claim_version` matches its parent's current `version` —
    `ERR_STALE_AGREEMENT_VERSION`, `ERR_STALE_KEG_VERSION` or
    `ERR_STALE_CLAIM_VERSION` (412). This guards order allocation, loss-assessment
    creation and claim response respectively."

    PRD: "13. The pool's `posture` is not `FROZEN` — `ERR_POOL_FROZEN` (409), on order
    creation and order allocation."

    PRD: "Every posture change advances the agreement's `version`, and moving into
    `SUSPENDED` is what causes later fill scans and allocations under that agreement
    to be refused with `ERR_FLOAT_SUSPENDED`."

    Design: Corner/validations/stale_agreement_version_is_rejected_before_the_frozen_pool_gate
    """
    ctx = _a_second_order_allocated_on_a_version_captured_too_early()
    validate_error(ctx["refusal"], ApiErrorId.ERR_STALE_AGREEMENT_VERSION, 412)

    assert fixtures.agreement_version(ctx["agreement"]["id"]) > ctx["stale_version"]


def test_the_version_correct_retry_exposes_the_next_rule_in_line():
    """Retrying with the current version satisfies step 9 and the ladder moves on:
    the pool is `FROZEN`, so the caller now sees `ERR_POOL_FROZEN` rather than the
    suspended float or the empty candidate set further down, and neither refusal left
    a mark on the order.

    PRD: "45. The allocation candidate set is non-empty — `ERR_NO_ELIGIBLE_KEGS`
    (409), on allocation."

    PRD: "15. The governing agreement's `float_posture` is not `SUSPENDED` —
    `ERR_FLOAT_SUSPENDED` (409), on order allocation and a fill scan."

    PRD: "Otherwise — including whenever `kegs_total` is zero — the posture is
    `FROZEN`."

    Design: Corner/validations/stale_agreement_version_is_rejected_before_the_frozen_pool_gate
    """
    ctx = _a_second_order_allocated_on_a_version_captured_too_early()
    retry = api_client.allocate_issuance_order(
        ctx["second_order"]["id"],
        {
            "expected_agreement_version": fixtures.agreement_version(
                ctx["agreement"]["id"]
            )
        },
        OPERATOR,
    )
    validate_error(retry, ApiErrorId.ERR_POOL_FROZEN, 409)

    untouched = fixtures.read_order(ctx["second_order"]["id"])
    assert untouched["status"] == "REQUESTED"
    assert untouched["allocated_keg_count"] == 0

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert pool["available_pct"] == 0.00
    assert pool["posture"] == "FROZEN"

    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["float_posture"] == "SUSPENDED"
    assert agreement["kegs_at_brewer_count"] == 1


def _a_float_suspended_by_the_brewers_own_suspension():
    """An active float over a two-keg pool with one order already raised, and then the
    brewer suspended by operator override — which cascades the agreement's posture to
    `SUSPENDED`, so both step 15 and step 16 are now violated by the same allocate.
    """
    fixtures.pin_clock(CLOCK)
    fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer()
    pool = fixtures.create_pool(**POOL)
    first_keg, _ = fixtures.import_kegs(pool["id"], ["K-0001", "K-0002"])
    agreement = fixtures.create_and_activate_agreement(
        brewer["id"], pool["id"], 2, effective_date="2026-08-01", per_fill_rate_cents=RATE
    )
    order = fixtures.create_order(agreement["id"], 1)
    validate_success(
        api_client.set_brewer_status(
            brewer["id"],
            {"status": "SUSPENDED", "status_reason": "Unpaid chargebacks under review"},
            OPERATOR,
        )
    )
    return {
        "brewer": brewer,
        "pool": pool,
        "first_keg": first_keg,
        "agreement": agreement,
        "order": order,
        "refusal": api_client.allocate_issuance_order(
            order["id"],
            {
                "expected_agreement_version": fixtures.agreement_version(
                    agreement["id"]
                )
            },
            OPERATOR,
        ),
    }


def test_a_suspended_brewer_is_reported_as_a_suspended_float_not_a_suspended_brewer():
    """Suspending the brewer makes both rules true at once, because the status change
    cascades into `float_posture` — and the float check sits one step above the brewer
    check, so `ERR_FLOAT_SUSPENDED` is the only admissible answer.  The pool is full
    and `OPEN`, so nothing further up the ladder is in play.

    PRD: "15. The governing agreement's `float_posture` is not `SUSPENDED` —
    `ERR_FLOAT_SUSPENDED` (409), on order allocation and a fill scan."

    PRD: "16. The brewer's `status` is not `SUSPENDED`; `PROBATION` is permitted here
    and is instead expressed through `float_posture`. Failure is
    `ERR_BREWER_SUSPENDED` (409), on agreement activation, order creation, a fill scan
    and loss-assessment resolution."

    PRD: "`float_posture` is recomputed on activation, on every allocation, dispatch or
    return that affects the agreement, on any change to the brewer's `status`, and on
    any change to the pool's `posture`."

    Design: Corner/validations/float_suspended_outranks_brewer_suspended_on_allocate
    """
    ctx = _a_float_suspended_by_the_brewers_own_suspension()

    assert fixtures.read_agreement(ctx["agreement"]["id"])["float_posture"] == "SUSPENDED"
    assert fixtures.read_brewer(ctx["brewer"]["id"])["status"] == "SUSPENDED"
    assert fixtures.read_pool(ctx["pool"]["id"])["posture"] == "OPEN"

    validate_error(ctx["refusal"], ApiErrorId.ERR_FLOAT_SUSPENDED, 409)


def test_restoring_the_brewer_releases_the_posture_and_the_same_allocate_succeeds():
    """The suspension lifts by recompute the moment the brewer returns to `ACTIVE`,
    landing the agreement on `TIGHT` because nothing is at the brewer yet; the
    identical allocate then goes through and pushes the posture up to `HEALTHY`.

    PRD: "The suspension lifts by recompute as soon as the suspending condition clears
    — the pool leaves `FROZEN` or the brewer returns to `ACTIVE` — at which point the
    agreement lands on `TIGHT` or `HEALTHY` according to the same ceiling comparison."

    PRD: "Otherwise, letting the thin-float ceiling be `float_size_kegs` multiplied by
    `replenishment_threshold_pct`, divided by 100 and floored to a whole number of
    kegs, the agreement is `TIGHT` when `kegs_at_brewer_count` is less than or equal to
    that ceiling, and `HEALTHY` otherwise."

    Design: Corner/validations/float_suspended_outranks_brewer_suspended_on_allocate
    """
    ctx = _a_float_suspended_by_the_brewers_own_suspension()
    restored = validate_success(
        api_client.set_brewer_status(
            ctx["brewer"]["id"],
            {"status": "ACTIVE", "status_reason": "Balance cleared"},
            OPERATOR,
        )
    )
    assert restored["status"] == "ACTIVE"
    assert restored["status_reason"] == "Balance cleared"
    assert fixtures.read_agreement(ctx["agreement"]["id"])["float_posture"] == "TIGHT"

    allocated = validate_success(
        api_client.allocate_issuance_order(
            ctx["order"]["id"],
            {
                "expected_agreement_version": fixtures.agreement_version(
                    ctx["agreement"]["id"]
                )
            },
            OPERATOR,
        )
    )
    assert allocated["status"] == "ALLOCATED"
    assert allocated["allocated_keg_ids"] == [ctx["first_keg"]["id"]]

    assert fixtures.read_agreement(ctx["agreement"]["id"])["float_posture"] == "HEALTHY"
    assert fixtures.read_pool(ctx["pool"]["id"])["available_pct"] == 50.00


def test_a_third_single_keg_order_trips_the_aggregate_float_ceiling():
    """Each order asks for a single keg and each is individually far below the float
    size of two, but the third is judged against the live `kegs_at_brewer_count`, which
    already stands at two — and the pool still holds a spare keg at an `OPEN` posture,
    so nothing else could have refused it.

    PRD: "43. `requested_keg_count` plus the agreement's `kegs_at_brewer_count` does
    not exceed its `float_size_kegs` — `ERR_FLOAT_SIZE_EXCEEDED` (422), on order
    creation."

    PRD: "`kegs_at_brewer_count` counts the kegs whose `current_brewer_id` is this
    agreement's brewer, whose `pool_id` is this agreement's pool, and whose
    `custody_state` is `ISSUED_TO_BREWER` or `FILLED`."

    PRD: "14. While the pool's `posture` is `RESTRICTED`, `requested_keg_count` does
    not exceed the pool's `restricted_max_kegs_per_order` — `ERR_POOL_RESTRICTED`
    (409), on order creation and order allocation."

    Design: Corner/validations/third_single_keg_order_exceeds_the_aggregate_float_size
    """
    fixtures.pin_clock(CLOCK)
    fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer()
    pool = fixtures.create_pool(**POOL)
    fixtures.import_kegs(pool["id"], ["K-0001", "K-0002", "K-0003"])
    agreement = fixtures.create_and_activate_agreement(
        brewer["id"], pool["id"], 2, effective_date="2026-08-01", per_fill_rate_cents=RATE
    )
    for _ in range(2):
        order = fixtures.create_order(agreement["id"], 1)
        fixtures.allocate_order(order["id"], agreement["id"])

    refusal = api_client.create_issuance_order(
        factories.create_issuance_order_payload(agreement["id"], 1), OPERATOR
    )
    validate_error(refusal, ApiErrorId.ERR_FLOAT_SIZE_EXCEEDED, 422)

    pool_now = fixtures.read_pool(pool["id"])
    assert pool_now["kegs_available"] == 1
    assert pool_now["available_pct"] == 33.33
    assert pool_now["posture"] == "OPEN"

    _, meta = validate_paginated(api_client.list_issuance_orders(OPERATOR))
    assert meta["total_count"] == 2

    agreement_now = fixtures.read_agreement(agreement["id"])
    assert agreement_now["kegs_at_brewer_count"] == 2
    assert agreement_now["pending_replenishment_kegs"] == 0
    assert agreement_now["float_posture"] == "HEALTHY"


def _a_cycle_open_on_a_keg_that_never_left_the_yard():
    """A keg seeded straight into `IN_SERVICE` — no brewer, no agreement, no order
    needed — booked onto a two-slot wash line, so the step rules can be exercised in
    isolation.
    """
    fixtures.pin_clock(CLOCK)
    fixtures.post_index("2026-07-01", 480)
    pool = fixtures.create_pool(**POOL)
    keg = fixtures.import_keg(pool["id"], "K-0001", initial_custody_state="IN_SERVICE")
    center = fixtures.create_service_center(2, name="Denver Wash Bay", region_code="CO")
    cycle = fixtures.create_service_cycle(
        keg["id"], center["id"], "2026-08-01T01:00:00Z", TECHNICIAN
    )
    return {"pool": pool, "keg": keg, "center": center, "cycle": cycle}


def test_the_caustic_minimum_binds_at_twelve_and_only_on_the_clean_step():
    """Eleven minutes is refused and the cycle does not move; twelve is accepted,
    because the minimum is inclusive; and the `INSPECT` step that follows carries no
    caustic field at all without tripping the rule, since step 22 is conditional on the
    step being a clean.

    PRD: "- **`CLEAN`** requires `stage` `RECEIVED` and an `occurred_at` at or after the
    cycle's `received_at` and not after the logical clock. It records
    `caustic_cycle_minutes`, which must be at least 12 — a shorter caustic wash is
    refused with `ERR_CAUSTIC_CYCLE_TOO_SHORT` — sets `cleaned_at` and advances the
    stage to `CLEANED`."

    PRD: "22. A cleaning step records a long enough caustic wash —
    `ERR_CAUSTIC_CYCLE_TOO_SHORT` (422)."

    PRD: "A result of `PASS` or `MINOR_DEFECT` advances the stage to `INSPECTED`: a
    minor defect is cosmetic and does not stop the keg."

    Design: Corner/validations/caustic_and_psi_minimums_apply_only_to_their_own_service_step
    """
    ctx = _a_cycle_open_on_a_keg_that_never_left_the_yard()

    too_short = api_client.record_service_step(
        ctx["cycle"]["id"],
        factories.clean_step_payload("2026-08-01T02:00:00Z", 11),
        TECHNICIAN,
    )
    validate_error(too_short, ApiErrorId.ERR_CAUSTIC_CYCLE_TOO_SHORT, 422)

    untouched = fixtures.read_cycle(ctx["cycle"]["id"])
    assert untouched["stage"] == "RECEIVED"
    assert untouched["cleaned_at"] is None
    assert untouched["version"] == ctx["cycle"]["version"]

    cleaned = validate_success(
        api_client.record_service_step(
            ctx["cycle"]["id"],
            factories.clean_step_payload("2026-08-01T03:00:00Z", 12),
            TECHNICIAN,
        )
    )
    assert cleaned["stage"] == "CLEANED"
    assert cleaned["caustic_cycle_minutes"] == 12

    inspected = validate_success(
        api_client.record_service_step(
            ctx["cycle"]["id"],
            factories.inspect_step_payload("2026-08-01T04:00:00Z", "PASS"),
            TECHNICIAN,
        )
    )
    assert inspected["stage"] == "INSPECTED"


def test_twenty_nine_psi_is_an_invalid_test_and_quarantines_nothing():
    """A reading below 30 is an invalid test rather than a failed one, so it is refused
    outright: the stage holds at `INSPECTED`, no technician is stamped as the
    certifier, and — unlike a genuine `FAIL` — the keg is neither quarantined nor
    marked `SERVICE_FAILED`.  Thirty passes, because the floor is inclusive.

    PRD: "The recorded `pressure_test_psi` must be at least 30; a lower reading is an
    *invalid* test rather than a failed one and is refused with
    `ERR_PRESSURE_TEST_PSI_TOO_LOW` regardless of the `pressure_test_result` supplied."

    PRD: "With an adequate pressure, a `pressure_test_result` of `PASS` advances the
    stage to `PRESSURE_TESTED`, records `pressure_tested_at` and stamps
    `pressure_test_performed_by_user_id` with the acting `X-User-ID`, while a `FAIL`
    diverts to `QUARANTINED` with `quarantine_reason` `PRESSURE_TEST_FAIL` and sets the
    keg's `service_state` to `SERVICE_FAILED`."

    PRD: "23. A pressure-test step records a high enough test pressure —
    `ERR_PRESSURE_TEST_PSI_TOO_LOW` (422)."

    Design: Corner/validations/caustic_and_psi_minimums_apply_only_to_their_own_service_step
    """
    ctx = _a_cycle_open_on_a_keg_that_never_left_the_yard()
    fixtures.record_clean(ctx["cycle"]["id"], "2026-08-01T03:00:00Z", 12)
    fixtures.record_inspect(ctx["cycle"]["id"], "2026-08-01T04:00:00Z", "PASS")

    too_low = api_client.record_service_step(
        ctx["cycle"]["id"],
        factories.pressure_test_step_payload("2026-08-01T05:00:00Z", 29, "PASS"),
        TECHNICIAN,
    )
    validate_error(too_low, ApiErrorId.ERR_PRESSURE_TEST_PSI_TOO_LOW, 422)

    stalled = fixtures.read_cycle(ctx["cycle"]["id"])
    assert stalled["stage"] == "INSPECTED"
    assert stalled["pressure_test_performed_by_user_id"] is None
    assert fixtures.read_keg(ctx["keg"]["id"])["service_state"] == ctx["keg"]["service_state"]

    passed = validate_success(
        api_client.record_service_step(
            ctx["cycle"]["id"],
            factories.pressure_test_step_payload("2026-08-01T06:00:00Z", 30, "PASS"),
            TECHNICIAN,
        )
    )
    assert passed["stage"] == "PRESSURE_TESTED"
    assert passed["pressure_test_result"] == "PASS"
    assert passed["pressure_test_performed_by_user_id"] == TECHNICIAN_USER_ID

    assert fixtures.read_keg(ctx["keg"]["id"])["custody_state"] == "IN_SERVICE"


def _two_kegs_certified_exactly_two_years_before_the_clock():
    """Both kegs were last pressure tested on 2024-08-02 and the clock stands at
    2026-08-02: exactly 730 days, which is not *more* than 730, so both import as
    `SERVICE_OK` and both are dispatched to the brewer.
    """
    fixtures.pin_clock("2026-08-02T00:00:00Z")
    fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer()
    pool = fixtures.create_pool(**POOL)
    first = fixtures.import_keg(
        pool["id"], "K-0001", last_pressure_test_at="2024-08-02T00:00:00Z"
    )
    second = fixtures.import_keg(
        pool["id"], "K-0002", last_pressure_test_at="2024-08-02T00:00:00Z"
    )
    # Ten more freshly certified shells keep the pool clear of the 10 percent
    # freeze threshold once the two aged kegs leave, so the pool stays `OPEN`
    # and the agreement's `float_posture` never suspends the fill.  Their
    # certification is younger, so the ranking still sends K-0001 and K-0002
    # out first.
    for n in range(3, 13):
        fixtures.import_keg(pool["id"], "K-%04d" % n)
    agreement = fixtures.create_and_activate_agreement(
        brewer["id"], pool["id"], 2, effective_date="2026-08-01", per_fill_rate_cents=RATE
    )
    fixtures.order_allocated_and_dispatched(agreement["id"], 2, "2026-08-01T00:00:00Z")
    return {
        "brewer": brewer,
        "pool": pool,
        "first": first,
        "second": second,
        "agreement": agreement,
    }


def test_a_keg_certified_exactly_seven_hundred_thirty_days_ago_still_fills():
    """Exactly 730 days is inside the window at both ends of the rule: the derivation
    at import reads `SERVICE_OK` because the certification is not *older* than two
    years, and the fill-time certification check admits the scan on the same reasoning.

    PRD: "If instead its certification is older than two years — that is, more than 730
    days have elapsed between `last_pressure_test_at` and the logical clock — it opens
    `SERVICE_OVERDUE`."

    PRD: "the keg's pressure certification must not have lapsed, meaning no more than
    730 days may have elapsed between `last_pressure_test_at` and the logical clock,
    otherwise `ERR_PRESSURE_TEST_OVERDUE`"

    PRD: "A scan's `dwell_days_closed` is the brewer clock read at that scan's
    `scanned_at`, and the keg's `cumulative_dwell_days` is the sum of
    `dwell_days_closed` across all its scans."

    Design: Corner/validations/pressure_certification_at_exactly_730_days_still_fills
    """
    ctx = _two_kegs_certified_exactly_two_years_before_the_clock()
    assert ctx["first"]["service_state"] == "SERVICE_OK"
    assert ctx["second"]["service_state"] == "SERVICE_OK"

    scan = fixtures.fill_scan(
        ctx["first"]["id"], ctx["brewer"]["id"], "2026-08-02T00:00:00Z", "RDG"
    )
    assert scan["dwell_days_closed"] == 1
    assert scan["fill_charge_net_cents"] == 2200
    assert fixtures.read_keg(ctx["first"]["id"])["custody_state"] == "FILLED"


def test_the_seven_hundred_thirty_first_day_refuses_the_fill_as_overdue():
    """One day later the same certification is 731 days old and the second keg is
    refused — with the temporal error, not the fitness error, because the stored
    `service_state` is still the `SERVICE_OK` written at import: neither a clock move
    nor a sweep has rewritten that field, so the fitness check at step 20 cannot mask
    the lapse at step 21.  The refusal bills nothing.

    PRD: "21. The keg's pressure certification has not lapsed —
    `ERR_PRESSURE_TEST_OVERDUE` (422), on a fill scan."

    PRD: "20. A keg may only be filled while certified: `service_state` must be
    `SERVICE_OK` — `ERR_KEG_NOT_FIT_FOR_FILL` (422), on a fill scan."

    PRD: "Rejected scans leave the ledger untouched."

    Design: Corner/validations/pressure_certification_at_exactly_730_days_still_fills
    """
    ctx = _two_kegs_certified_exactly_two_years_before_the_clock()
    fixtures.fill_scan(
        ctx["first"]["id"], ctx["brewer"]["id"], "2026-08-02T00:00:00Z", "RDG"
    )
    fixtures.pin_clock("2026-08-03T00:00:00Z")

    refusal = api_client.scan_keg(
        ctx["second"]["id"],
        factories.fill_scan_payload(
            ctx["brewer"]["id"], "2026-08-03T00:00:00Z", "RDG"
        ),
        make_brewer_headers(ctx["brewer"]["id"]),
    )
    validate_error(refusal, ApiErrorId.ERR_PRESSURE_TEST_OVERDUE, 422)

    stalled = fixtures.read_keg(ctx["second"]["id"])
    assert stalled["service_state"] == "SERVICE_OK"
    assert stalled["custody_state"] == "ISSUED_TO_BREWER"
    assert stalled["fill_count"] == 0

    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["billed_amount_cents"] == 2200
    assert agreement["billed_fills_count"] == 1


def _a_keg_dispatched_a_second_time_behind_its_own_history():
    """One full cycle — fill, distribution, return, then a complete service cycle that
    recertifies the keg and puts it back on the float — followed by a second dispatch
    backdated to 2026-08-04, which reopens a custody interval that swallows cycle one's
    fill instant.
    """
    fixtures.pin_clock("2026-08-20T23:00:00Z")
    fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer()
    distributor = fixtures.create_distributor()
    pool = fixtures.create_pool(**POOL)
    keg = fixtures.import_keg(pool["id"], "K-0001")
    fixtures.import_keg(pool["id"], "K-0002", fill_count=5, fills_at_last_pressure_test=5)
    center = fixtures.create_service_center(2, name="Denver Wash Bay", region_code="CO")
    agreement = fixtures.create_and_activate_agreement(
        brewer["id"], pool["id"], 2, effective_date="2026-08-01", per_fill_rate_cents=RATE
    )
    fixtures.order_allocated_and_dispatched(agreement["id"], 1, "2026-08-02T00:00:00Z")
    fixtures.fill_scan(keg["id"], brewer["id"], "2026-08-05T00:00:00Z", "RDG")
    fixtures.distribution_scan(
        keg["id"], distributor["id"], "2026-08-08T00:00:00Z", "RDG"
    )
    fixtures.return_scan(keg["id"], distributor["id"], "2026-08-10T00:00:00Z", "RDG")

    cycle = fixtures.create_service_cycle(
        keg["id"], center["id"], "2026-08-10T01:00:00Z", TECHNICIAN
    )
    fixtures.record_clean(cycle["id"], "2026-08-10T02:00:00Z", 15)
    fixtures.record_inspect(cycle["id"], "2026-08-10T03:00:00Z", "PASS")
    fixtures.record_pressure_test(cycle["id"], "2026-08-10T04:00:00Z", 45, "PASS")
    fixtures.release_cycle(cycle["id"], "2026-08-10T05:00:00Z", SECOND_TECHNICIAN)

    second_order = fixtures.create_order(agreement["id"], 1)
    fixtures.allocate_order(second_order["id"], agreement["id"])
    fixtures.dispatch_order(second_order["id"], "2026-08-04T00:00:00Z")
    return {
        "brewer": brewer,
        "distributor": distributor,
        "pool": pool,
        "keg": keg,
        "center": center,
        "agreement": agreement,
        "cycle": cycle,
        "second_order": second_order,
    }


def test_a_repeated_fill_pair_across_two_cycles_is_a_duplicate_scan():
    """The duplicate rule is only reachable across two custody cycles, because within
    one cycle a second fill is caught far earlier by the sequence rule.  Here the keg
    is legitimately back in `ISSUED_TO_BREWER`, and the backdated dispatch instant
    makes 2026-08-05 land inside the open interval — so nothing but step 34 can speak,
    and the refusal charges nothing.

    PRD: "34. No existing scan on this keg shares the same pair of `scan_point` and
    `scanned_at` — `ERR_DUPLICATE_SCAN` (409)."

    PRD: "A new scan whose `scanned_at` is at or after `dwell_started_at` lands in the
    open interval and is accepted — including the case where `scanned_at` is exactly
    equal to `dwell_started_at`, because two adjacent intervals touching at a single
    point do not overlap."

    PRD: "Rejected scans leave the ledger untouched."

    Design: Corner/validations/duplicate_fill_scan_pair_in_a_second_cycle_is_rejected
    """
    ctx = _a_keg_dispatched_a_second_time_behind_its_own_history()
    assert fixtures.read_keg(ctx["keg"]["id"])["custody_state"] == "ISSUED_TO_BREWER"

    replay = api_client.scan_keg(
        ctx["keg"]["id"],
        factories.fill_scan_payload(
            ctx["brewer"]["id"], "2026-08-05T00:00:00Z", "RDG"
        ),
        make_brewer_headers(ctx["brewer"]["id"]),
    )
    validate_error(replay, ApiErrorId.ERR_DUPLICATE_SCAN, 409)

    keg = fixtures.read_keg(ctx["keg"]["id"])
    assert keg["fill_count"] == 1
    assert keg["scan_count"] == 3
    assert fixtures.read_agreement(ctx["agreement"]["id"])["billed_amount_cents"] == 2200


def test_a_fresh_instant_in_the_reopened_interval_bills_as_a_late_arrival():
    """A fill one day later is a new pair, so it is accepted — and it is flagged late,
    because the keg's high-water mark still stands at the return scan of 2026-08-10.
    The spell it closes is measured from the backdated dispatch, the mark does not
    rewind, and the second fill bills at the base rate because the tier basis of 4400
    is still short of the first volume band.

    PRD: "A scan is flagged `is_late_arrival` when the keg's `last_scanned_at` is
    already set and this scan's `scanned_at` is strictly earlier than it."

    PRD: "The high-water mark never rewinds — `last_scanned_at` becomes whichever is
    later of its existing value and the new `scanned_at` — so a late arrival cannot
    make a subsequent genuine scan look late."

    PRD: "On the agreement's side, `billed_fills_count` rises by one,
    `billed_amount_cents` grows by the fill's net charge, and the agreement's `version`
    advances."

    Design: Corner/validations/duplicate_fill_scan_pair_in_a_second_cycle_is_rejected
    """
    ctx = _a_keg_dispatched_a_second_time_behind_its_own_history()

    scan = fixtures.fill_scan(
        ctx["keg"]["id"], ctx["brewer"]["id"], "2026-08-06T00:00:00Z", "RDG"
    )
    assert scan["is_late_arrival"] is True
    assert scan["dwell_days_closed"] == 2
    assert scan["fill_charge_net_cents"] == 2200

    keg = fixtures.read_keg(ctx["keg"]["id"])
    assert keg["fill_count"] == 2
    assert keg["scan_count"] == 4
    assert keg["last_scanned_at"] == "2026-08-10T00:00:00Z"

    assert fixtures.read_agreement(ctx["agreement"]["id"])["billed_amount_cents"] == 4400
