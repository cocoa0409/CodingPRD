"""Contract termination: legality gates and the no-cure cascade."""
from test_helpers import (
    ApiErrorId,
    book_charter,
    lodge_security,
    register_asset,
    set_clock,
    setup_active_contract,
    setup_running_phase,
    setup_signed_contract,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def test_no_cure_termination_cascade(api, contracts_officer_headers, salvage_master_headers):
    """PRD 3.3: "A no-cure termination sets `terminate_reason` to `NO_CURE`,
    increments the contract's `version`, and fires the termination cascade:
    every operation phase in `PLANNED`, `ACTIVE`, `WEATHER_HOLD`, or
    `ENV_SUSPENDED` moves to `ABORTED`; every charter of the casualty in
    `ON_HIRE`, `STANDBY_WEATHER`, or `STANDBY_ENV` is taken to `OFF_HIRE` with
    its charter cost computed at the current logical clock, while charters still
    `BOOKED` move to `CANCELLED`"
    PRD 3.3: "and no salvage award can ever be created for the contract, because
    award computation requires `PERFORMANCE_COMPLETE` — no cure, no pay."

    Design: Corner/state_machines/no_cure_termination_cascade
    """
    ctx = setup_running_phase(
        plan_classes=["TUG", "PONTOON"],
        casualty_overrides={
            "vessel_name": "MV Kara", "casualty_type": "SUNK",
            "declared_salved_value_cents": 800_000_000, "position": "32N 64W",
        },
    )
    # A second charter on a different asset, still BOOKED (never mobilized).
    pontoon = register_asset(
        asset_class="PONTOON", day_rate_cents=500_000, max_hs_meters=1.50
    )
    booked = book_charter(
        ctx["casualty"]["id"], pontoon["id"],
        window_start="2026-06-01T00:00:00Z", window_end="2026-06-05T00:00:00Z",
    )
    assert booked["status"] == "BOOKED"
    set_clock("2026-05-14T00:00:00Z")

    terminated = validate_success(
        api.terminate_contract(ctx["contract"]["id"], {"reason": "NO_CURE"},
                               contracts_officer_headers),
        200,
    )
    assert terminated["status"] == "TERMINATED"
    assert terminated["terminate_reason"] == "NO_CURE"

    phase = validate_success(api.get_phase(ctx["phase"]["id"], salvage_master_headers), 200)
    assert phase["status"] == "ABORTED", "active phase aborted by the cascade"

    on_hire_charter = validate_success(
        api.get_charter(ctx["charter"]["id"], salvage_master_headers), 200
    )
    assert on_hire_charter["status"] == "OFF_HIRE", "on-hire charter settled at the clock"
    assert on_hire_charter["total_cost_cents"] == 8_000_000, (
        "4 active days x 2,000,000 at 2026-05-14"
    )

    booked_after = validate_success(
        api.get_charter(booked["id"], salvage_master_headers), 200
    )
    assert booked_after["status"] == "CANCELLED", "never-mobilized charter cancelled"

    # Award computation requires PERFORMANCE_COMPLETE; on a TERMINATED contract
    # the PRD names the state gate (ERR_CONTRACT_NOT_ACTIVE) while its pipeline
    # also permits the terminal-state rejection — no cure, no pay either way.
    res = api.create_award(ctx["contract"]["id"], contracts_officer_headers)
    validate_error_is_one_of(
        res,
        [
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
            ApiErrorId.ERR_ALREADY_TERMINAL,
        ],
    )


def test_mutual_termination_from_active_rejected(api, contracts_officer_headers):
    """PRD 3.3: "Mutual termination, with `reason` set to `MUTUAL`, is allowed
    from `DRAFT`, `OFFERED`, `COUNTERED`, or `SIGNED` ... From `ACTIVE`, mutual
    termination is forbidden (`ERR_TERMINATION_NOT_ALLOWED`)"

    Design: Corner/state_machines/mutual_termination_from_active_rejected
    """
    ctx = setup_active_contract(casualty_overrides={"vessel_name": "MV Pax"})
    assert ctx["contract"]["status"] == "ACTIVE"
    res = api.terminate_contract(
        ctx["contract"]["id"], {"reason": "MUTUAL"}, contracts_officer_headers
    )
    validate_error(res, ApiErrorId.ERR_TERMINATION_NOT_ALLOWED, expected_status=422)
    after = validate_success(api.get_contract(ctx["contract"]["id"], contracts_officer_headers), 200)
    assert after["status"] == "ACTIVE"


def test_no_cure_on_fixed_price_rejected(api, contracts_officer_headers):
    """PRD 3.3: "the only escape is no-cure termination with `reason` set to
    `NO_CURE`, which is itself lawful only on a `NO_CURE_NO_PAY` contract —
    attempting no-cure on a `FIXED_PRICE` contract is rejected with
    `ERR_NO_CURE_REQUIRES_NCNP`."

    Design: Corner/state_machines/no_cure_on_fixed_price_rejected
    """
    ctx = setup_signed_contract(
        form="FIXED_PRICE", fixed_price_cents=50_000_000,
        casualty_overrides={"vessel_name": "MV Pax"},
    )
    assert ctx["contract"]["security_required_cents"] == 15_000_000
    lodge_security(ctx["contract"]["id"], 15_000_000)
    activated = validate_success(
        api.activate_contract(ctx["contract"]["id"], contracts_officer_headers), 200
    )
    assert activated["status"] == "ACTIVE"
    res = api.terminate_contract(
        ctx["contract"]["id"], {"reason": "NO_CURE"}, contracts_officer_headers
    )
    validate_error(res, ApiErrorId.ERR_NO_CURE_REQUIRES_NCNP, expected_status=422)
    after = validate_success(api.get_contract(ctx["contract"]["id"], contracts_officer_headers), 200)
    assert after["status"] == "ACTIVE"
