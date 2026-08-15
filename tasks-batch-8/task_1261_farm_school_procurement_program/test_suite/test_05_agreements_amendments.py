"""Planting agreements and amendments: creation gates, lifecycle guards,
amendment cycle, OCC, and conserved quantities."""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_agreement,
    assert_agreement_quantity_conserved,
    assert_amendment,
    create_accepted_delivery,
    create_agreement,
    create_approved_farm,
    create_farm,
    create_forecast_line,
    create_offering,
    create_product,
    create_program_year,
    create_verified_offering,
    make_farm_manager_headers,
    schedule_delivery,
    setup_procurement_chain,
    sign_agreement,
    validate_error,
    validate_success,
    create_receiving_window,
    create_kitchen,
)
from test_helpers.test_users import TEST_USERS, make_admin_headers

ADMIN = TEST_USERS["admin_headers"]


def test_agreement_create_requires_verified_offering(api):
    """PRD section 3.4: "And the offering itself must be `VERIFIED`
    (`ERR_OFFERING_NOT_VERIFIED`)."

    Design: Corner/state_machines/sm_agreement_create_requires_verified_offering
    """
    year = create_program_year()
    product = create_product()
    farm = create_approved_farm()
    offering = validate_success(
        create_offering(farm["id"], year["id"], product["id"]), 201
    )
    resp = api.submit_offering(
        offering["id"], make_farm_manager_headers(farm["id"])
    )
    validate_success(resp, 200)  # offering now SUBMITTED, not yet VERIFIED
    resp = create_agreement(year["id"], offering["id"])
    validate_error(resp, ApiErrorId.ERR_OFFERING_NOT_VERIFIED)


def test_agreement_state_family_errors(api):
    """PRD section 3.4: "The grower's `FarmManager` signs the proposal
    (`PROPOSED` → `SIGNED`), which requires the agreement to be `PROPOSED`
    (`ERR_AGREEMENT_NOT_PROPOSED`)"
    PRD section 3.4: "either a `DistrictProgramAdmin` or the grower's
    `FarmManager` may cancel an agreement standing in `PROPOSED`, `SIGNED`, or
    `AMENDMENT_PROPOSED` (any other state draws `ERR_AGREEMENT_NOT_CANCELLABLE`)"

    Design: Corner/state_machines/sm_agreement_state_family_errors
    """
    chain = setup_procurement_chain()
    farm_headers = make_farm_manager_headers(chain.farm["id"])

    # Sign is single-shot.
    resp = api.sign_agreement(chain.agreement["id"], farm_headers)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_PROPOSED)

    # The first delivery flips the agreement to FULFILLING, which is not
    # cancellable.
    delivery = validate_success(
        schedule_delivery(
            chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
            chain.farm["id"], "2026-08-10", 10,
        ),
        201,
    )
    assert delivery["status"] == "SCHEDULED"
    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert agreement["status"] == "FULFILLING"
    resp = api.cancel_agreement(chain.agreement["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_CANCELLABLE)


def test_completed_agreement_terminal_lockdown(api):
    """PRD section 3.4: "When a delivery acceptance brings the
    `delivered_quantity` exactly to the `committed_quantity`, the agreement
    becomes `COMPLETED` — a terminal state"
    PRD section 3.4: "either a `DistrictProgramAdmin` or the grower's
    `FarmManager` may cancel an agreement standing in `PROPOSED`, `SIGNED`, or
    `AMENDMENT_PROPOSED` (any other state draws `ERR_AGREEMENT_NOT_CANCELLABLE`)"

    Design: Corner/state_machines/sm_completed_agreement_terminal_lockdown
    """
    chain = setup_procurement_chain(committed_quantity=40)
    create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 40,
    )
    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert agreement["status"] == "COMPLETED", (
        f"delivered == committed must auto-complete, got {agreement['status']}"
    )
    resp = api.cancel_agreement(chain.agreement["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_CANCELLABLE)


def test_amendment_counterparty_flow(api):
    """PRD section 3.4: "the proposing role answering its own proposal is
    rejected with `ERR_NOT_COUNTERPARTY`."
    PRD section 3.4: "Acceptance requires the amendment to be `PROPOSED`
    (`ERR_AMENDMENT_NOT_OPEN`) and the agreement to stand in
    `AMENDMENT_PROPOSED` (`ERR_AGREEMENT_NOT_AMENDABLE`); it applies the new
    terms — replacing the `committed_quantity`, the `unit_price_cents`, or
    both — increments the agreement's `version`, and returns the agreement to
    `FULFILLING` when at least one delivery exists for it, otherwise to
    `SIGNED`."

    Design: Corner/state_machines/sm_amendment_family_flow
    """
    chain = setup_procurement_chain()  # committed 200, price 250
    farm_headers = make_farm_manager_headers(chain.farm["id"])
    version = chain.agreement["version"]

    amendment = validate_success(
        api.propose_amendment(
            chain.agreement["id"],
            {"new_committed_quantity": 180, "expected_agreement_version": version},
            farm_headers,
        ),
        201,
    )
    assert_amendment(amendment)
    assert amendment["proposed_by_role"] == "FarmManager"

    # The proposing role cannot accept its own proposal.
    resp = api.accept_amendment(amendment["id"], farm_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_COUNTERPARTY)

    # The counterparty (district admin) accepts; terms apply.
    accepted = validate_success(
        api.accept_amendment(amendment["id"], make_admin_headers("admin-1")), 200
    )
    assert accepted["status"] == "ACCEPTED"

    # A decided amendment is no longer open.
    resp = api.accept_amendment(amendment["id"], make_admin_headers("admin-1"))
    validate_error(resp, ApiErrorId.ERR_AMENDMENT_NOT_OPEN)

    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert agreement["committed_quantity"] == 180
    assert agreement["status"] == "SIGNED", (
        "no deliveries exist, so the agreement returns to SIGNED"
    )


def test_amendment_below_delivered_rejected(api):
    """PRD section 3.4: "a new committed quantity may not fall below the
    agreement's `delivered_quantity` (`ERR_AMENDMENT_BELOW_DELIVERED`)"
    PRD section 3.4: "While an agreement stands in `SIGNED`,
    `AMENDMENT_PROPOSED`, or `FULFILLING`, either party — the district admin or
    the owning farm's `FarmManager` — may propose an **amendment**; from any
    other agreement state the attempt fails with `ERR_AGREEMENT_NOT_AMENDABLE`."

    Design: Corner/state_machines/sm_amendment_below_delivered_rejected
    """
    chain = setup_procurement_chain(committed_quantity=200)
    create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 40,
    )
    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert agreement["status"] == "FULFILLING"
    version = agreement["version"]
    farm_headers = make_farm_manager_headers(chain.farm["id"])

    resp = api.propose_amendment(
        chain.agreement["id"],
        {"new_committed_quantity": 30, "expected_agreement_version": version},
        farm_headers,
    )
    validate_error(resp, ApiErrorId.ERR_AMENDMENT_BELOW_DELIVERED)

    # A proposal at or above delivered_quantity is admitted from FULFILLING.
    amendment = validate_success(
        api.propose_amendment(
            chain.agreement["id"],
            {"new_committed_quantity": 180, "expected_agreement_version": version},
            farm_headers,
        ),
        201,
    )
    assert amendment["status"] == "PROPOSED"
    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert agreement["status"] == "AMENDMENT_PROPOSED"


def test_amendment_empty_rejected(api):
    """PRD section 3.4: "The proposal carries at least one of
    `new_committed_quantity` or `new_unit_price_cents` — a proposal with
    neither is `ERR_AMENDMENT_EMPTY`"

    Design: Corner/errors/err_amendment_empty_rejected
    """
    chain = setup_procurement_chain()
    resp = api.propose_amendment(
        chain.agreement["id"],
        {"expected_agreement_version": chain.agreement["version"]},
        make_farm_manager_headers(chain.farm["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AMENDMENT_EMPTY)


def test_farm_and_agreement_guard_family(api):
    """PRD section 3.2: "requires the farm to be `APPLIED` (otherwise
    `ERR_FARM_NOT_APPLIED`)"
    PRD section 3.2: "It demands that the farm actually be `SUSPENDED`
    (`ERR_FARM_NOT_SUSPENDED`)"
    PRD section 3.4: "The agreement's year must equal the offering's year
    (`ERR_OFFERING_YEAR_MISMATCH`). The agreement's window must lie inside the
    offering's harvest window (`ERR_AGREEMENT_WINDOW_OUTSIDE_OFFERING`)."
    PRD section 3.4: "from any other agreement state the attempt fails with
    `ERR_AGREEMENT_NOT_AMENDABLE`."

    Design: Corner/errors/err_farm_and_agreement_guard_family
    """
    year = create_program_year()
    year2 = create_program_year(
        school_year_label="Y2", start_date="2027-07-01", end_date="2028-06-23"
    )
    product = create_product()
    farm = create_approved_farm()
    offering = create_verified_offering(farm["id"], year["id"], product["id"])
    create_forecast_line(year["id"], product["id"], week_number=6, planned_quantity=400)

    # Double approve and reinstate-of-approved both fail their state gates.
    validate_error(api.approve_farm(farm["id"], ADMIN), ApiErrorId.ERR_FARM_NOT_APPLIED)
    validate_error(
        api.reinstate_farm(farm["id"], ADMIN), ApiErrorId.ERR_FARM_NOT_SUSPENDED
    )

    # The agreement's year must equal the offering's year.
    resp = create_agreement(year2["id"], offering["id"], committed_quantity=10)
    validate_error(resp, ApiErrorId.ERR_OFFERING_YEAR_MISMATCH)

    # The agreement's window must lie inside the offering's 4..12 window.
    resp = create_agreement(
        year["id"], offering["id"], committed_quantity=10,
        harvest_start_week=8, harvest_end_week=13,
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_WINDOW_OUTSIDE_OFFERING)

    # A PROPOSED agreement is not amendable.
    agreement = validate_success(
        create_agreement(year["id"], offering["id"], committed_quantity=200), 201
    )
    resp = api.propose_amendment(
        agreement["id"],
        {"new_unit_price_cents": 260,
         "expected_agreement_version": agreement["version"]},
        make_farm_manager_headers(farm["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_AMENDABLE)


def test_reserved_excludes_proposed_agreements(api):
    """PRD section 3.4: "the agreement stands in `SIGNED`,
    `AMENDMENT_PROPOSED`, or `FULFILLING` — `PROPOSED`, `COMPLETED`,
    `BREACHED`, and `CANCELLED` never count"
    PRD section 3.4: "The `reserved_quantity` is the sum of
    `committed_quantity` over all covering agreements, and the
    `uncovered_quantity` is the planned quantity minus the reserved quantity,
    floored at zero"

    Design: Corner/calculations/calc_reserved_excludes_proposed_agreements
    """
    chain = setup_procurement_chain(with_agreement=False)
    agreement = validate_success(
        create_agreement(chain.year["id"], chain.offering["id"], committed_quantity=200),
        201,
    )
    line_id = chain.forecast_line["id"]

    line = validate_success(api.get_forecast_line(line_id, ADMIN), 200)
    assert line["reserved_quantity"] == 0, "a PROPOSED agreement never counts"
    assert line["uncovered_quantity"] == 400

    sign_agreement(agreement["id"], chain.farm["id"])
    line = validate_success(api.get_forecast_line(line_id, ADMIN), 200)
    assert line["reserved_quantity"] == 200
    assert line["uncovered_quantity"] == 200


def test_commitment_within_min_uncovered(api):
    """PRD section 3.4: "the `committed_quantity` may not exceed the smallest
    `uncovered_quantity` among the forecast lines for the same product in the
    same year whose week falls inside the agreement's window — weeks in the
    window with no forecast line at all impose no constraint — and an
    over-committed proposal is rejected with `ERR_COMMITMENT_EXCEEDS_UNCOVERED`
    (HTTP 402)."

    Design: Corner/calculations/calc_commitment_within_min_uncovered
    """
    chain = setup_procurement_chain(with_agreement=False)
    agr_a = validate_success(
        create_agreement(chain.year["id"], chain.offering["id"], committed_quantity=300),
        201,
    )
    sign_agreement(agr_a["id"], chain.farm["id"])

    # 300 reserved of 400 planned leaves an uncovered 100 for week 6.
    resp = create_agreement(
        chain.year["id"], chain.offering["id"], committed_quantity=150
    )
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_EXCEEDS_UNCOVERED)

    agr_b = validate_success(
        create_agreement(
            chain.year["id"], chain.offering["id"], committed_quantity=100
        ),
        201,
    )
    assert_agreement(agr_b)
    assert agr_b["status"] == "PROPOSED"


def test_amendment_reject_cycle_returns_signed_terms_unchanged(api):
    """PRD section 3.4: "Rejection requires the amendment to be `PROPOSED` and
    leaves the agreement's terms unchanged, returning it by the same rule:
    `FULFILLING` if it has deliveries, `SIGNED` otherwise."

    Design: Difficulty/non_linear_state_machine/agreement_amendment_cycle_returns_signed
    """
    chain = setup_procurement_chain()  # committed 200, price 250
    farm_headers = make_farm_manager_headers(chain.farm["id"])

    amendment = validate_success(
        api.propose_amendment(
            chain.agreement["id"],
            {"new_committed_quantity": 180,
             "expected_agreement_version": chain.agreement["version"]},
            farm_headers,
        ),
        201,
    )
    rejected = validate_success(
        api.reject_amendment(amendment["id"], make_admin_headers("admin-1")), 200
    )
    assert rejected["status"] == "REJECTED"

    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert agreement["status"] == "SIGNED", "the agreement cycles back to SIGNED"
    assert agreement["committed_quantity"] == 200, "rejection leaves terms unchanged"
    assert agreement["unit_price_cents"] == 250


def test_amendment_reject_cycle_from_admin_proposal(api):
    """PRD section 3.4: "the owning farm's `FarmManager` answers one proposed
    by the district"
    PRD section 3.4: "Rejection requires the amendment to be `PROPOSED` and
    leaves the agreement's terms unchanged, returning it by the same rule:
    `FULFILLING` if it has deliveries, `SIGNED` otherwise."

    Design: Difficulty/non_linear_state_machine/agreement_amendment_cycle_returns_signed
    """
    chain = setup_procurement_chain()
    amendment = validate_success(
        api.propose_amendment(
            chain.agreement["id"],
            {"new_unit_price_cents": 260,
             "expected_agreement_version": chain.agreement["version"]},
            make_admin_headers("admin-1"),
        ),
        201,
    )
    assert amendment["proposed_by_role"] == "DistrictProgramAdmin"

    rejected = validate_success(
        api.reject_amendment(
            amendment["id"], make_farm_manager_headers(chain.farm["id"])
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"
    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert agreement["status"] == "SIGNED"
    assert agreement["unit_price_cents"] == 250
    assert agreement["committed_quantity"] == 200


def test_agreement_quantity_conservation_mid_flight(api):
    """PRD section 3.4: "its `remaining_quantity` is the committed quantity
    minus the delivered quantity while the agreement is active and zero in
    terminal states, and its `released_quantity` stays zero until the agreement
    ends short"

    Design: Difficulty/compensating_invariant/agreement_quantity_conservation
    """
    chain = setup_procurement_chain(committed_quantity=100)
    create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 40,
    )
    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert agreement["status"] == "FULFILLING"
    assert agreement["delivered_quantity"] == 40
    assert agreement["remaining_quantity"] == 60
    assert agreement["released_quantity"] == 0
    assert_agreement_quantity_conserved(agreement)


def test_agreement_quantity_conservation_after_breach_sweep(api):
    """PRD section 2.8: "agreements in `SIGNED`, `AMENDMENT_PROPOSED`, or
    `FULFILLING` whose harvest window has closed — the current week lying
    beyond the agreement's `harvest_end_week` — are settled: an agreement that
    has delivered its full commitment becomes `COMPLETED`, while one that has
    delivered less becomes `BREACHED`"
    PRD section 3.4: "such an agreement becomes `BREACHED`, its
    `released_quantity` is set to the committed quantity minus the delivered
    quantity, its `remaining_quantity` becomes zero"

    Design: Difficulty/compensating_invariant/agreement_quantity_conservation
    """
    chain = setup_procurement_chain(committed_quantity=100)
    create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 40,
    )
    # 2026-09-21 falls in week 12 of the year, beyond harvest_end_week 10.
    advance_clock("2026-09-21T00:00:00Z")
    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert agreement["status"] == "BREACHED"
    assert agreement["delivered_quantity"] == 40
    assert agreement["remaining_quantity"] == 0
    assert agreement["released_quantity"] == 60
    assert_agreement_quantity_conserved(agreement)


def test_delivery_blocked_while_amendment_pending(api):
    """PRD section 3.5: "The agreement must stand in `SIGNED` or `FULFILLING`
    (`ERR_AGREEMENT_NOT_ACTIVE`)"
    PRD section 3.4: "moves an agreement in `SIGNED` or `FULFILLING` to
    `AMENDMENT_PROPOSED`"

    Design: Difficulty/cross_entity_state_dependency/delivery_blocked_during_amendment_pending
    """
    chain = setup_procurement_chain()
    validate_success(
        api.propose_amendment(
            chain.agreement["id"],
            {"new_unit_price_cents": 275,
             "expected_agreement_version": chain.agreement["version"]},
            make_farm_manager_headers(chain.farm["id"]),
        ),
        201,
    )
    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert agreement["status"] == "AMENDMENT_PROPOSED"

    resp = schedule_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 10,
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


def test_delivery_unblocked_after_amendment_rejected(api):
    """PRD section 3.4: "Rejection requires the amendment to be `PROPOSED` and
    leaves the agreement's terms unchanged, returning it by the same rule:
    `FULFILLING` if it has deliveries, `SIGNED` otherwise."
    PRD section 3.5: "The agreement must stand in `SIGNED` or `FULFILLING`
    (`ERR_AGREEMENT_NOT_ACTIVE`)"

    Design: Difficulty/cross_entity_state_dependency/delivery_blocked_during_amendment_pending
    """
    chain = setup_procurement_chain()
    amendment = validate_success(
        api.propose_amendment(
            chain.agreement["id"],
            {"new_unit_price_cents": 275,
             "expected_agreement_version": chain.agreement["version"]},
            make_farm_manager_headers(chain.farm["id"]),
        ),
        201,
    )
    resp = schedule_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 10,
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    # Resolving the amendment returns the agreement to SIGNED and scheduling
    # works again.
    validate_success(api.reject_amendment(amendment["id"], make_admin_headers("admin-1")), 200)
    delivery = validate_success(
        schedule_delivery(
            chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
            chain.farm["id"], "2026-08-10", 10,
        ),
        201,
    )
    assert delivery["status"] == "SCHEDULED"


def test_delivery_state_error_beats_quantity_constraint(api):
    """PRD section 2.5: "Inbound requests are validated as an ordered pipeline;
    a request that fails an earlier stage is rejected with that stage's error
    and never reaches later stages."
    PRD section 3.5: "The agreement must stand in `SIGNED` or `FULFILLING`
    (`ERR_AGREEMENT_NOT_ACTIVE`)"

    Design: Difficulty/priority_pair_validation_conflict/delivery_state_beats_constraint_conflict
    """
    chain = setup_procurement_chain()
    validate_success(api.cancel_agreement(chain.agreement["id"], ADMIN), 200)

    # Quantity 999 would also exceed the uncommitted remainder, but the state
    # check (stage 6) runs before quantity limits (stage 10).
    resp = schedule_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 999,
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


def test_delivery_state_error_beats_quantity_constraint_completed(api):
    """PRD section 2.5: "Inbound requests are validated as an ordered pipeline;
    a request that fails an earlier stage is rejected with that stage's error
    and never reaches later stages."
    PRD section 3.5: "The agreement must stand in `SIGNED` or `FULFILLING`
    (`ERR_AGREEMENT_NOT_ACTIVE`)"

    Design: Difficulty/priority_pair_validation_conflict/delivery_state_beats_constraint_conflict
    """
    chain = setup_procurement_chain(committed_quantity=40)
    create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 40,
    )
    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert agreement["status"] == "COMPLETED"

    resp = schedule_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-17", 999,
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


def test_occ_amendment_stale_then_supersede(api):
    """PRD section 2.9: "In both cases, if the supplied value does not match
    the parent resource's current `version` — because another write has
    advanced the parent since the client read it — the request is rejected
    with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the parent
    before retrying."
    PRD section 3.4: "marks any earlier still-`PROPOSED` amendment on the same
    agreement `SUPERSEDED`"

    Design: Corner/complexity_layers/layer_occ_amendment_stale_then_supersede
    """
    chain = setup_procurement_chain()
    farm_headers = make_farm_manager_headers(chain.farm["id"])
    version = chain.agreement["version"]

    amd1 = validate_success(
        api.propose_amendment(
            chain.agreement["id"],
            {"new_unit_price_cents": 275, "expected_agreement_version": version},
            farm_headers,
        ),
        201,
    )
    # The first proposal advanced the agreement version: replaying the stale
    # version is rejected.
    resp = api.propose_amendment(
        chain.agreement["id"],
        {"new_unit_price_cents": 260, "expected_agreement_version": version},
        make_admin_headers("admin-1"),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    # Re-read, then retry with the fresh version.
    fresh = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    amd2 = validate_success(
        api.propose_amendment(
            chain.agreement["id"],
            {"new_unit_price_cents": 260,
             "expected_agreement_version": fresh["version"]},
            make_admin_headers("admin-1"),
        ),
        201,
    )
    assert amd2["status"] == "PROPOSED"

    amd1_after = validate_success(api.get_amendment(amd1["id"], ADMIN), 200)
    assert amd1_after["status"] == "SUPERSEDED"
    agreement = validate_success(
        api.get_planting_agreement(chain.agreement["id"], ADMIN), 200
    )
    assert agreement["status"] == "AMENDMENT_PROPOSED"
