"""Scout packages and the cyclic owner-agreement negotiation."""
from test_helpers import (
    FO,
    LM,
    ApiErrorId,
    assert_location,
    assert_owner_agreement,
    assert_scout_package,
    create_scout_package_payload,
    get_success_data,
    make_owner_rep_headers,
    setup_accepted_scout_package,
    setup_basic_scenario,
    setup_draft_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Scout package photo floor and review lifecycle
# ---------------------------------------------------------------------------

def test_scout_package_submit_with_five_photos_rejected(api):
    """PRD §3.2: "Submission is allowed only while the production is in `PREP`,
    and a package with a `photo_count` below 6 is rejected at submission with
    `ERR_PACKAGE_INCOMPLETE`; a successful submission moves the package from
    `DRAFT` to `SUBMITTED`."

    Design: Corner/state_machines/scout_package_submit_with_five_photos_rejected
    """
    scenario = setup_basic_scenario()
    production_id = scenario["production"]["id"]
    package = get_success_data(api.create_scout_package(
        production_id,
        create_scout_package_payload(scenario["location"]["id"], photo_count=5),
        LM,
    ))

    resp = api.submit_scout_package(production_id, package["id"], LM)
    validate_error(resp, ApiErrorId.ERR_PACKAGE_INCOMPLETE)

    current = get_success_data(api.get_scout_package(production_id, package["id"], LM))
    assert current["status"] == "DRAFT"


def test_scout_package_review_twice_returns_invalid_state(api):
    """PRD §3.2: "The film office then reviews the submitted package with a
    `decision` of `ACCEPT` or `REJECT`, moving it to `ACCEPTED` or `REJECTED`
    respectively."
    PRD §2.7: "then whether the target resource's current state permits the
    requested transition at all (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/scout_package_review_twice_returns_invalid_state
    """
    scenario = setup_basic_scenario()
    package = setup_accepted_scout_package(scenario["production"], scenario["location"])
    assert package["status"] == "ACCEPTED"

    resp = api.review_scout_package(scenario["production"]["id"], package["id"], "REJECT", FO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    current = get_success_data(
        api.get_scout_package(scenario["production"]["id"], package["id"], LM)
    )
    assert current["status"] == "ACCEPTED"


def test_scout_package_coverage_score_out_of_range_rejected(api):
    """PRD §3.2: "The package records the `location_id`, a `photo_count`, a
    surveyor-rated `coverage_score_pct` between 0 and 100 inclusive, and the
    `scout_date` of the physical scout."
    PRD §2.7: "finally payload well-formedness — required fields present and
    well-typed, enum values valid, dates parseable — as `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/scout_package_coverage_score_out_of_range_rejected
    """
    scenario = setup_basic_scenario()
    production_id = scenario["production"]["id"]

    resp = api.create_scout_package(
        production_id,
        create_scout_package_payload(scenario["location"]["id"], coverage_score_pct=101),
        LM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(api.list_scout_packages(production_id, LM))
    assert meta["total_count"] == 0, "No scout package may be persisted after a 400"


# ---------------------------------------------------------------------------
# Difficulty: cross-entity gate — propose requires an ACCEPTED scout package
# ---------------------------------------------------------------------------

def test_propose_rejected_until_scout_package_accepted(api):
    """PRD §3.2: "the first proposal is rejected with `ERR_SCOUT_NOT_ACCEPTED`
    unless an `ACCEPTED` scout package exists for the same production and
    location."

    Design: Difficulty/cross_entity_state_dependency/agreement_propose_gated_by_scout_package_acceptance
    """
    scenario = setup_basic_scenario()
    production = scenario["production"]
    location = scenario["location"]

    # Scout package SUBMITTED but not yet reviewed.
    package = get_success_data(api.create_scout_package(
        production["id"], create_scout_package_payload(location["id"]), LM,
    ))
    get_success_data(api.submit_scout_package(production["id"], package["id"], LM))
    agreement = setup_draft_agreement(production, location)

    blocked = api.propose_owner_agreement(production["id"], agreement["id"], 150_000, LM)
    validate_error(blocked, ApiErrorId.ERR_SCOUT_NOT_ACCEPTED)
    current = get_success_data(api.get_owner_agreement(production["id"], agreement["id"], LM))
    assert current["status"] == "DRAFT" and current["round_count"] == 0

    get_success_data(api.review_scout_package(production["id"], package["id"], "ACCEPT", FO))
    accepted = api.propose_owner_agreement(production["id"], agreement["id"], 150_000, LM)
    data = validate_success(accepted)
    assert data["status"] == "PROPOSED"
    assert data["round_count"] == 1


def test_propose_rejected_with_no_scout_package_at_all(api):
    """PRD §3.2: "the first proposal is rejected with `ERR_SCOUT_NOT_ACCEPTED`
    unless an `ACCEPTED` scout package exists for the same production and
    location."

    Design: Difficulty/cross_entity_state_dependency/agreement_propose_gated_by_scout_package_acceptance
    """
    scenario = setup_basic_scenario()
    production = scenario["production"]
    agreement = setup_draft_agreement(production, scenario["location"])

    resp = api.propose_owner_agreement(production["id"], agreement["id"], 150_000, LM)
    validate_error(resp, ApiErrorId.ERR_SCOUT_NOT_ACCEPTED)
    current = get_success_data(api.get_owner_agreement(production["id"], agreement["id"], LM))
    assert current["status"] == "DRAFT"
    assert current["round_count"] == 0


# ---------------------------------------------------------------------------
# Difficulty: cyclic negotiation state machine and round accounting
# ---------------------------------------------------------------------------

def test_cyclic_counter_loop_locks_owner_counter_rate(api):
    """PRD §3.2: "Each proposal increments `round_count` by one, replaces the
    standing `proposed_day_rate_cents` with the payload rate, and moves the
    agreement to `PROPOSED`."
    PRD §3.2: "The owner representative counters from `PROPOSED`, supplying their
    own `proposed_day_rate_cents`, which replaces the standing rate and moves the
    agreement to `COUNTERED` without incrementing the round count"
    PRD §3.2: "it locks `agreed_day_rate_cents` to the standing
    `proposed_day_rate_cents`, moves the agreement to `EXECUTED`, cascades the
    location to `AGREEMENT_EXECUTED`"

    Design: Difficulty/non_linear_state_machine/owner_agreement_cyclic_counter_loop_round_accounting
    """
    scenario = setup_basic_scenario()
    production, location, owner = scenario["production"], scenario["location"], scenario["owner"]
    setup_accepted_scout_package(production, location)
    agreement = setup_draft_agreement(production, location, {"max_rounds": 5})
    owner_headers = make_owner_rep_headers(owner["id"])
    pid = production["id"]

    get_success_data(api.propose_owner_agreement(pid, agreement["id"], 100_000, LM))
    get_success_data(api.counter_owner_agreement(pid, agreement["id"], 180_000, owner_headers))
    get_success_data(api.propose_owner_agreement(pid, agreement["id"], 140_000, LM))
    get_success_data(api.counter_owner_agreement(pid, agreement["id"], 160_000, owner_headers))

    executed = validate_success(api.accept_owner_agreement(pid, agreement["id"], LM))
    assert_owner_agreement(executed)
    assert executed["status"] == "EXECUTED"
    assert executed["round_count"] == 2, (
        "Only propose hops increment round_count; two proposes must yield 2"
    )
    assert executed["agreed_day_rate_cents"] == 160_000, (
        "The standing COUNTERED rate (160000), not the manager's last proposal (140000), locks"
    )

    location_now = get_success_data(api.get_location(location["id"], LM))
    assert_location(location_now)
    assert location_now["status"] == "AGREEMENT_EXECUTED"


def test_counter_replaces_standing_rate_and_manager_accepts_from_countered(api):
    """PRD §3.2: "The owner representative counters from `PROPOSED`, supplying
    their own `proposed_day_rate_cents`, which replaces the standing rate and
    moves the agreement to `COUNTERED` without incrementing the round count"
    PRD §3.2: "Either side may close the deal, but only the side facing the offer:
    the `OwnerRep` accepts a `PROPOSED` agreement, and the `LocationManager`
    accepts a `COUNTERED` one."

    Design: Difficulty/non_linear_state_machine/owner_agreement_cyclic_counter_loop_round_accounting
    """
    scenario = setup_basic_scenario()
    production, location, owner = scenario["production"], scenario["location"], scenario["owner"]
    setup_accepted_scout_package(production, location)
    agreement = setup_draft_agreement(production, location)
    pid = production["id"]

    get_success_data(api.propose_owner_agreement(pid, agreement["id"], 100_000, LM))
    countered = get_success_data(
        api.counter_owner_agreement(pid, agreement["id"], 175_000, make_owner_rep_headers(owner["id"]))
    )
    assert countered["status"] == "COUNTERED"
    assert countered["proposed_day_rate_cents"] == 175_000
    assert countered["round_count"] == 1

    executed = validate_success(api.accept_owner_agreement(pid, agreement["id"], LM))
    assert executed["status"] == "EXECUTED"
    assert executed["round_count"] == 1
    assert executed["agreed_day_rate_cents"] == 175_000


def test_agreement_counter_at_round_cap_returns_negotiation_exhausted(api):
    """PRD §3.2: "Both proposing and countering are rejected with
    `ERR_NEGOTIATION_EXHAUSTED` when the action would push `round_count` beyond
    `max_rounds`."

    Design: Corner/state_machines/agreement_counter_at_round_cap_returns_negotiation_exhausted
    """
    scenario = setup_basic_scenario()
    production, location, owner = scenario["production"], scenario["location"], scenario["owner"]
    setup_accepted_scout_package(production, location)
    agreement = setup_draft_agreement(production, location, {"max_rounds": 2})
    owner_headers = make_owner_rep_headers(owner["id"])
    pid = production["id"]

    get_success_data(api.propose_owner_agreement(pid, agreement["id"], 100_000, LM))
    get_success_data(api.counter_owner_agreement(pid, agreement["id"], 180_000, owner_headers))
    get_success_data(api.propose_owner_agreement(pid, agreement["id"], 140_000, LM))
    # round_count is now 2 == max_rounds; the counter is the next action.
    resp = api.counter_owner_agreement(pid, agreement["id"], 160_000, owner_headers)
    validate_error(resp, ApiErrorId.ERR_NEGOTIATION_EXHAUSTED)

    current = get_success_data(api.get_owner_agreement(pid, agreement["id"], LM))
    assert current["status"] == "PROPOSED"
    assert current["round_count"] == 2


def test_location_manager_cannot_accept_own_proposal_segregation(api):
    """PRD §3.2: "Either side may close the deal, but only the side facing the
    offer: the `OwnerRep` accepts a `PROPOSED` agreement, and the
    `LocationManager` accepts a `COUNTERED` one."
    PRD §2.7: "then whether the target resource's current state permits the
    requested transition at all (`ERR_INVALID_STATE`)"

    Design: Corner/rbac/location_manager_cannot_accept_own_proposal_segregation
    """
    scenario = setup_basic_scenario()
    production, location = scenario["production"], scenario["location"]
    setup_accepted_scout_package(production, location)
    agreement = setup_draft_agreement(production, location)
    pid = production["id"]
    get_success_data(api.propose_owner_agreement(pid, agreement["id"], 150_000, LM))

    resp = api.accept_owner_agreement(pid, agreement["id"], LM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    current = get_success_data(api.get_owner_agreement(pid, agreement["id"], LM))
    assert current["status"] == "PROPOSED"


# ---------------------------------------------------------------------------
# Consistency: accept cascades to the location immediately
# ---------------------------------------------------------------------------

def test_immediate_visibility_of_cascade_results(api):
    """PRD §2.10: "When an `OwnerAgreement` reaches `EXECUTED`, the Location it
    covers transitions from `SCOUTING` to `AGREEMENT_EXECUTED` without a separate
    client call"
    PRD §3.2: "it locks `agreed_day_rate_cents` to the standing
    `proposed_day_rate_cents`, moves the agreement to `EXECUTED`, cascades the
    location to `AGREEMENT_EXECUTED`"

    Design: Corner/consistency_model/immediate_visibility_of_cascade_results
    """
    scenario = setup_basic_scenario()
    production, location, owner = scenario["production"], scenario["location"], scenario["owner"]
    setup_accepted_scout_package(production, location)
    agreement = setup_draft_agreement(production, location)
    pid = production["id"]
    get_success_data(api.propose_owner_agreement(pid, agreement["id"], 150_000, LM))

    resp = api.accept_owner_agreement(pid, agreement["id"], make_owner_rep_headers(owner["id"]))
    data = validate_success(resp)
    assert data["status"] == "EXECUTED"
    assert data["agreed_day_rate_cents"] == 150_000

    location_now = get_success_data(api.get_location(location["id"], LM))
    assert location_now["status"] == "AGREEMENT_EXECUTED"
