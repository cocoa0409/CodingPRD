"""Authorization unit-pool ledger: reservation vs delivered basis, the
EXHAUSTED<->ACTIVE cycle, the exact pool boundary on schedule, pool
conservation, initial state, immediate consistency, and version increment."""
from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_rbt_headers,
    make_bcba_headers,
    setup_active_authorization,
    schedule_session,
    deliver_session,
    get_authorization,
    factories,
)


# ─── Difficulty: reservation basis vs delivered basis ────────────────────────

def test_pool_under_reservation_basis_holds_full_scheduled_units(api):
    """PRD §3.6: "its `scheduled_units` are added to the owning authorization's
    reserved accumulator for that service line, the direct remaining figure is
    recomputed".

    Design: Difficulty/dual_variant_calc/authorization_pool_reservation_vs_delivered_basis_returns_units
    """
    sc = setup_active_authorization(api, authorized_direct_units=320)
    schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"], "RBT",
                     scheduled_units=8)
    auth = get_authorization(api, sc["authorization"]["id"])
    assert auth["reserved_direct_units"] == 8, auth["reserved_direct_units"]
    assert auth["remaining_direct_units"] == 312, auth["remaining_direct_units"]


def test_short_delivery_returns_difference_to_remaining_pool(api):
    """PRD §3.7: "Because reserved drops by the full scheduled amount while
    delivered rises only by the actual amount, the difference between what was
    scheduled and what was delivered returns to the remaining pool whenever fewer
    units were rendered than reserved."

    Design: Difficulty/dual_variant_calc/authorization_pool_reservation_vs_delivered_basis_returns_units
    """
    sc = setup_active_authorization(api, authorized_direct_units=320)
    session = schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"],
                               "RBT", scheduled_units=8)
    deliver_session(api, session["id"], sc["rbt"]["id"], "RBT", 7)
    auth = get_authorization(api, sc["authorization"]["id"])
    assert auth["reserved_direct_units"] == 0, auth["reserved_direct_units"]
    assert auth["delivered_direct_units"] == 7, auth["delivered_direct_units"]
    assert auth["remaining_direct_units"] == 313, auth["remaining_direct_units"]


# ─── Difficulty: EXHAUSTED <-> ACTIVE cycle on freed units ───────────────────

def test_full_reservation_flips_authorization_to_exhausted(api):
    """PRD §3.4: "The moment the pool ledger recomputes and the direct pool is
    fully consumed — that is, reserved direct units plus delivered direct units
    equal the authorized direct pool, leaving `remaining_direct_units` at zero —
    the authorization flips from `ACTIVE` to `EXHAUSTED`".

    Design: Difficulty/non_linear_state_machine/authorization_exhausted_active_cycle_on_free_units
    """
    sc = setup_active_authorization(api, authorized_direct_units=12)
    schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"], "RBT",
                     scheduled_start="2026-05-01T09:00:00Z",
                     scheduled_end="2026-05-01T11:00:00Z", scheduled_units=8)
    schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"], "RBT",
                     scheduled_start="2026-05-02T09:00:00Z",
                     scheduled_end="2026-05-02T10:00:00Z", scheduled_units=4)
    auth = get_authorization(api, sc["authorization"]["id"])
    assert auth["reserved_direct_units"] == 12
    assert auth["remaining_direct_units"] == 0
    assert auth["status"] == "EXHAUSTED", auth["status"]


def test_cancel_frees_units_and_flips_exhausted_back_to_active(api):
    """PRD §3.4: "Conversely, when a recompute frees reserved units so that
    remaining direct units rise above zero again, an `EXHAUSTED` authorization
    flips back to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/authorization_exhausted_active_cycle_on_free_units
    """
    sc = setup_active_authorization(api, authorized_direct_units=12)
    schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"], "RBT",
                     scheduled_start="2026-05-01T09:00:00Z",
                     scheduled_end="2026-05-01T11:00:00Z", scheduled_units=8)
    sess_b = schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"],
                              "RBT", scheduled_start="2026-05-02T09:00:00Z",
                              scheduled_end="2026-05-02T10:00:00Z",
                              scheduled_units=4)
    get_success_data(api.cancel_session(sess_b["id"], make_rbt_headers(sc["rbt"]["id"])))
    auth = get_authorization(api, sc["authorization"]["id"])
    assert auth["reserved_direct_units"] == 8
    assert auth["remaining_direct_units"] == 4
    assert auth["status"] == "ACTIVE", auth["status"]


# ─── Difficulty: exact pool boundary on schedule ─────────────────────────────

def test_schedule_exactly_remaining_units_succeeds(api):
    """PRD §3.6: "scheduling must not push the reserved-plus-delivered total above
    the authorized pool for the session's service line; an attempt to over-commit
    the pool is rejected with `ERR_UNITS_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/units_exceeded_exact_pool_boundary_on_schedule
    """
    sc = setup_active_authorization(api, authorized_direct_units=5)
    schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"], "RBT",
                     scheduled_start="2026-08-01T09:00:00Z",
                     scheduled_end="2026-08-01T10:15:00Z", scheduled_units=5)
    auth = get_authorization(api, sc["authorization"]["id"])
    assert auth["reserved_direct_units"] == 5
    assert auth["remaining_direct_units"] == 0


def test_schedule_one_unit_over_pool_returns_units_exceeded(api):
    """PRD §3.6: "scheduling must not push the reserved-plus-delivered total above
    the authorized pool for the session's service line; an attempt to over-commit
    the pool is rejected with `ERR_UNITS_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/units_exceeded_exact_pool_boundary_on_schedule
    """
    sc = setup_active_authorization(api, authorized_direct_units=5)
    schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"], "RBT",
                     scheduled_start="2026-08-01T09:00:00Z",
                     scheduled_end="2026-08-01T10:15:00Z", scheduled_units=5)
    resp = api.create_session(
        factories.create_session_payload(
            sc["authorization"]["id"], sc["rbt"]["id"],
            scheduled_start="2026-08-02T09:00:00Z",
            scheduled_end="2026-08-02T10:30:00Z", scheduled_units=6,
        ),
        make_rbt_headers(sc["rbt"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNITS_EXCEEDED.value, 409)


# ─── Difficulty: pool conservation under schedule-then-cancel ────────────────

def test_pool_invariant_holds_after_schedule(api):
    """PRD §2.7: "The invariant the system upholds at all times is that, for the
    direct line, reserved plus delivered plus remaining always equals the
    authorized direct pool."

    Design: Difficulty/compensating_invariant/unit_pool_conserved_under_schedule_then_cancel
    """
    sc = setup_active_authorization(api, authorized_direct_units=320)
    schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"], "RBT",
                     scheduled_start="2026-03-10T09:00:00Z",
                     scheduled_end="2026-03-10T11:00:00Z", scheduled_units=8)
    auth = get_authorization(api, sc["authorization"]["id"])
    assert auth["reserved_direct_units"] == 8
    assert auth["delivered_direct_units"] == 0
    assert auth["remaining_direct_units"] == 312
    assert (auth["reserved_direct_units"] + auth["delivered_direct_units"]
            + auth["remaining_direct_units"]) == 320


def test_pool_returns_to_zero_drift_after_compensating_cancel(api):
    """PRD §2.7: "The invariant the system upholds at all times is that, for the
    direct line, reserved plus delivered plus remaining always equals the
    authorized direct pool."
    PRD §3.7: "the session's reserved units for its service line are released back
    to remaining".

    Design: Difficulty/compensating_invariant/unit_pool_conserved_under_schedule_then_cancel
    """
    sc = setup_active_authorization(api, authorized_direct_units=320)
    session = schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"],
                               "RBT", scheduled_start="2026-03-10T09:00:00Z",
                               scheduled_end="2026-03-10T11:00:00Z",
                               scheduled_units=8)
    get_success_data(api.cancel_session(session["id"], make_rbt_headers(sc["rbt"]["id"])))
    auth = get_authorization(api, sc["authorization"]["id"])
    assert auth["reserved_direct_units"] == 0
    assert auth["delivered_direct_units"] == 0
    assert auth["remaining_direct_units"] == 320
    assert (auth["reserved_direct_units"] + auth["delivered_direct_units"]
            + auth["remaining_direct_units"]) == 320


# ─── Corner: PARENT_TRAINING pool boundary ───────────────────────────────────

def test_parent_training_pool_boundary_exact_fit_then_overflow(api):
    """PRD §3.6: "scheduling must not push the reserved-plus-delivered total above
    the authorized pool for the session's service line; an attempt to over-commit
    the pool is rejected with `ERR_UNITS_EXCEEDED`."

    Design: Corner/validations/parent_training_pool_boundary_exact_fit
    """
    sc = setup_active_authorization(api, authorized_parent_training_units=16,
                                    with_rbt=False)
    bcba_id = sc["bcba"]["id"]
    bcba_h = make_bcba_headers(bcba_id)
    schedule_session(api, sc["authorization"]["id"], bcba_id, "BCBA",
                     service_line="PARENT_TRAINING",
                     scheduled_start="2026-02-02T09:00:00Z",
                     scheduled_end="2026-02-02T12:00:00Z", scheduled_units=12)
    # 12 + 4 == 16 <= 16 fits.
    ok = api.create_session(
        factories.create_session_payload(
            sc["authorization"]["id"], bcba_id, service_line="PARENT_TRAINING",
            scheduled_start="2026-02-03T09:00:00Z",
            scheduled_end="2026-02-03T10:00:00Z", scheduled_units=4,
        ),
        bcba_h,
    )
    validate_success(ok, 201)
    # 12 + 4 + 5 == 21 > 16 overflows.
    over = api.create_session(
        factories.create_session_payload(
            sc["authorization"]["id"], bcba_id, service_line="PARENT_TRAINING",
            scheduled_start="2026-02-04T09:00:00Z",
            scheduled_end="2026-02-04T10:15:00Z", scheduled_units=5,
        ),
        bcba_h,
    )
    validate_error(over, ApiErrorId.ERR_UNITS_EXCEEDED.value, 409)


# ─── Corner: initial authorization state ─────────────────────────────────────

def test_new_authorization_is_active_with_empty_pools(api):
    """PRD §3.4: "A new authorization is born `ACTIVE`, with all reserved and
    delivered accumulators at zero and `remaining_direct_units` equal to the
    authorized direct pool".

    Design: Corner/state_machines/initial_state_authorization_is_active
    """
    sc = setup_active_authorization(api, authorized_direct_units=100,
                                    with_rbt=False)
    auth = sc["authorization"]
    assert auth["status"] == "ACTIVE"
    assert auth["reserved_direct_units"] == 0
    assert auth["delivered_direct_units"] == 0
    assert auth["remaining_direct_units"] == 100


# ─── Corner: immediate consistency of the pool ledger ────────────────────────

def test_pool_ledger_reflected_in_immediate_read(api):
    """PRD §2.9: "These propagations are computed atomically within the request
    that triggers them, so a reader observing any resource after the request sees
    a fully reconciled picture rather than a half-applied one."

    Design: Corner/consistency_model/pool_ledger_visible_in_same_request_response
    """
    sc = setup_active_authorization(api, authorized_direct_units=100)
    schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"], "RBT",
                     scheduled_start="2026-02-02T09:00:00Z",
                     scheduled_end="2026-02-02T10:30:00Z", scheduled_units=6)
    auth = get_authorization(api, sc["authorization"]["id"])
    assert auth["reserved_direct_units"] == 6
    assert auth["remaining_direct_units"] == 94


# ─── Corner: version increments on each mutation ─────────────────────────────

def test_authorization_version_increments_on_pool_mutation(api):
    """PRD §2.4: "Whenever a computed field on a resource changes — for example,
    the recomputation of an authorization's pool ledger or supervision posture —
    that recomputation is itself a mutation: it refreshes `updated_at` and
    increments `version`."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_authorization_mutation
    """
    sc = setup_active_authorization(api, authorized_direct_units=100)
    assert sc["authorization"]["version"] == 1, sc["authorization"]["version"]
    schedule_session(api, sc["authorization"]["id"], sc["rbt"]["id"], "RBT",
                     scheduled_units=8)
    auth = get_authorization(api, sc["authorization"]["id"])
    assert auth["version"] == 2, (
        f"expected version 2 after pool-ledger mutation, got {auth['version']}"
    )
