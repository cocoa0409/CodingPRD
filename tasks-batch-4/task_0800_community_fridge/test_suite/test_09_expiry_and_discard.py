"""Operations-checkpoint expiry at the inclusive use_by boundary, and discard state."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_stocked_batch, set_clock, discard_batch,
    make_admin_headers, make_steward_headers,
)


def test_batch_expires_when_clock_reaches_use_by_exactly(api):
    """PRD §3.7: "The expiry boundary is inclusive: a `STOCKED` or `HELD` batch whose
    `use_by` the logical clock has reached — that is, current time at or after
    `use_by` — is moved to the terminal `EXPIRED` status."

    Design: Difficulty/boundary_precision_check/use_by_expiry_inclusive_lower_bound
    """
    fridge, steward, batch = setup_stocked_batch(
        api, capacity_slots=10, declared_quantity_kg=3.0, use_by="2026-03-10T00:00:00Z"
    )
    set_clock(api, "2026-03-10T00:00:00Z")  # exactly at use_by
    validate_success(api.run_ops(fridge["id"], make_admin_headers()), 200)
    got = validate_success(api.get_batch(batch["id"], make_admin_headers()), 200)
    assert got["status"] == "EXPIRED"


def test_batch_not_expired_before_use_by(api):
    """PRD §3.7: "The expiry boundary is inclusive: a `STOCKED` or `HELD` batch whose
    `use_by` the logical clock has reached — that is, current time at or after
    `use_by` — is moved to the terminal `EXPIRED` status."

    Design: Difficulty/boundary_precision_check/use_by_expiry_inclusive_lower_bound
    """
    fridge, steward, batch = setup_stocked_batch(
        api, capacity_slots=10, declared_quantity_kg=3.0, use_by="2026-03-10T00:00:00Z"
    )
    set_clock(api, "2026-03-09T23:59:59Z")  # one second before use_by
    validate_success(api.run_ops(fridge["id"], make_admin_headers()), 200)
    got = validate_success(api.get_batch(batch["id"], make_admin_headers()), 200)
    assert got["status"] == "STOCKED"


def test_discarding_already_discarded_batch_rejected_invalid_state(api):
    """PRD §3.7: "A `Steward` or `NetworkAdmin` discards a batch, moving it from
    `RECALLED` to the terminal `DISCARDED` status ... A `STOCKED` batch may also be
    discarded directly ... moving it from `STOCKED` to `DISCARDED`."
    PRD §2.5: validation "rejects the request" once a resource is not in a valid state
    for the requested transition, reported as `ERR_INVALID_STATE`.

    Design: Corner/state_machines/discard_already_discarded_returns_invalid_state
    """
    fridge, steward, batch = setup_stocked_batch(
        api, capacity_slots=5, declared_quantity_kg=3.0
    )
    discard_batch(api, batch["id"], steward["id"])
    resp = api.discard_batch(batch["id"], make_steward_headers(steward["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
