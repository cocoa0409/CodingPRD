"""Booths, assignments, permits, and utility hookups: system-field handling,
activation preconditions, terminal lockdown, commitment invariant, permit
revocation cascade, and propane energize permit gating."""
import pytest

from test_helpers import (
    TEST_USERS, validate_error, validate_success, is_valid_uuid,
    assert_assignment_fee_invariants,
    create_market, create_vendor_entity, create_booth_entity,
    create_draft_application, create_submitted_application,
    create_accepted_application, create_under_jury_application,
    create_assignment_for, activate_assignment,
    setup_accepted_application, setup_active_assignment,
    create_permit_for, create_installed_hookup,
    get_market, get_booth, get_assignment, get_permit, get_hookup, get_vendor,
)

OPERATOR = TEST_USERS["market_operator_headers"]
UTILITY = TEST_USERS["utility_crew_headers"]


def test_booth_create_ignores_client_supplied_system_fields(api, market_operator_headers):
    """PRD §2.4: "Every persisted resource carries an `id` field: a
    server-minted UUID with no type prefix. Every resource also carries
    `created_at`, an ISO 8601 UTC timestamp with three fractional digits, set at
    creation and never modified."

    Design: Corner/entities/booth_system_fields_id_created_at_ignored
    """
    market = create_market({"name": "SM", "season_code": "SM-1"})
    payload = {
        "booth_code": "SYS-1", "booth_type": "STANDARD", "zone": "NORTH",
        "square_feet": 80,
        "id": "11111111-1111-1111-1111-111111111111",
        "created_at": "2000-01-01T00:00:00Z",
        "updated_at": "2000-01-01T00:00:00Z",
    }
    booth = validate_success(api.create_booth(market["id"], payload,
                                              market_operator_headers), 201)
    assert booth["id"] != "11111111-1111-1111-1111-111111111111", \
        "client-supplied id must be ignored (server mints the id)"
    assert is_valid_uuid(booth["id"])
    assert booth["created_at"] != "2000-01-01T00:00:00Z", \
        "client-supplied created_at must be ignored (set at creation)"
    assert booth["status"] == "AVAILABLE"


def test_assignment_activate_rejected_when_application_not_accepted(api, market_operator_headers):
    """PRD §3.4: "Activation requires that the linked application is
    `ACCEPTED`, that no other `ACTIVE` assignment exists on the same booth, and
    that the market's `posture` is `SETUP` or `OPEN`. If the application is not
    `ACCEPTED`, the attempt is rejected with `ERR_PAYMENT_NOT_SATISFIED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/assignment_activate_requires_application_accepted
    """
    market = create_market({"name": "M13", "season_code": "W26M"})
    vendor = create_vendor_entity(legal_name="V13", category="EXPERIENCE")
    booth = create_booth_entity(market["id"], booth_code="STD-X1", zone="EAST")
    # Application is UNDER_JURY (one score), not ACCEPTED.
    app = create_under_jury_application(market["id"], vendor["id"], scores=[70],
                                        juror_prefix="juror-m13")
    assert app["status"] == "UNDER_JURY"
    asg = create_assignment_for(market["id"], booth["id"], app["id"])
    res = api.activate_assignment(market["id"], asg["id"], market_operator_headers)
    validate_error(res, "ERR_PAYMENT_NOT_SATISFIED", expected_status=409)


def test_assignment_activate_succeeds_when_application_accepted(api, market_operator_headers):
    """PRD §3.4: "Activation transitions the assignment from `PENDING_PAYMENT`
    to `ACTIVE`."
    PRD §3.4: "On activation, the booth's `status` transitions to `RESERVED` and
    the market's `total_booths_committed` increments by 1."

    Design: Difficulty/cross_entity_state_dependency/assignment_activate_requires_application_accepted
    """
    ctx = setup_accepted_application(booth_overrides={"booth_code": "STD-OK"})
    market_id = ctx["market"]["id"]
    asg = create_assignment_for(market_id, ctx["booth"]["id"], ctx["application"]["id"])
    activated = validate_success(
        api.activate_assignment(market_id, asg["id"], market_operator_headers), 200)
    assert activated["status"] == "ACTIVE"
    booth = get_booth(market_id, ctx["booth"]["id"])
    assert booth["status"] == "RESERVED"
    market = get_market(market_id)
    assert market["total_booths_committed"] == 1


def test_assignment_activate_from_released_rejected(api, market_operator_headers):
    """PRD §3.4: "Activation transitions the assignment from `PENDING_PAYMENT`
    to `ACTIVE`." (RELEASED is terminal; no outbound transitions are defined.)
    PRD §2.9: "Then entity state validity (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/assignment_terminal_lockdown_released
    """
    ctx = setup_active_assignment()
    market_id = ctx["market"]["id"]
    asg_id = ctx["assignment"]["id"]
    released = validate_success(api.release_assignment(market_id, asg_id,
                                                       market_operator_headers), 200)
    assert released["status"] == "RELEASED"
    res = api.activate_assignment(market_id, asg_id, market_operator_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def _setup_two_active_assignments(api, name_suffix=""):
    """Market with two ACCEPTED applications and two ACTIVE assignments."""
    caps = {"FOOD_BEVERAGE": 5, "CRAFT": 5, "APPAREL": 5, "HOME_GOODS": 5,
            "EXPERIENCE": 5}
    market = create_market({"name": f"M17{name_suffix}",
                            "season_code": f"W26Q{name_suffix}", "category_caps": caps})
    ctxs = []
    for i, code in enumerate(["CH-1", "CH-2"]):
        vendor = create_vendor_entity(legal_name=f"V17{name_suffix}{i}",
                                      category="FOOD_BEVERAGE")
        booth = create_booth_entity(market["id"], booth_code=code, booth_type="CHALET",
                                    zone="NORTH" if i == 0 else "SOUTH", square_feet=100)
        app = create_accepted_application(market["id"], vendor["id"],
                                          scores=[80, 80, 80],
                                          juror_prefix=f"juror-m17{name_suffix}-{i}",
                                          requested_booth_type="CHALET")
        asg = create_assignment_for(market["id"], booth["id"], app["id"])
        asg = activate_assignment(market["id"], asg["id"])
        ctxs.append({"vendor": vendor, "booth": booth, "application": app,
                     "assignment": asg})
    return market, ctxs


def test_booth_commitment_invariant_balances_over_activate_release_pairs(api,
                                                                         market_operator_headers):
    """PRD §3.4: "On activation, the booth's `status` transitions to `RESERVED`
    and the market's `total_booths_committed` increments by 1."
    PRD §3.4: "An `ACTIVE` assignment may be released by an operator, which
    transitions it to `RELEASED`, returns the booth to `AVAILABLE`, and
    decrements `total_booths_committed` by 1."

    Design: Difficulty/compensating_invariant/booth_commitment_invariant
    """
    market, ctxs = _setup_two_active_assignments(api)
    market = get_market(market["id"])
    assert market["total_booths_committed"] == 2, "two activations -> +2"

    for c in ctxs:
        validate_success(api.release_assignment(market["id"], c["assignment"]["id"],
                                                market_operator_headers), 200)
    market = get_market(market["id"])
    assert market["total_booths_committed"] == 0, \
        "2 activations + 2 releases must cancel out to zero"


def test_booth_commitment_invariant_balances_over_mixed_release_and_forfeit(api,
                                                                            market_operator_headers):
    """PRD §3.4: "An `ACTIVE` assignment may also be forfeited by an operator
    providing a `reason` of `NO_SHOW`, `PERMIT_REVOKED`, or `OPERATOR_EJECTION`.
    Forfeiture transitions the assignment to `FORFEITED`, returns the booth to
    `AVAILABLE`, decrements `total_booths_committed` by 1, and — only when
    `reason` is `NO_SHOW` — increments the vendor's `no_show_strikes` by 1."

    Design: Difficulty/compensating_invariant/booth_commitment_invariant
    """
    market, ctxs = _setup_two_active_assignments(api, name_suffix="F")
    market_id = market["id"]
    validate_success(api.release_assignment(market_id, ctxs[0]["assignment"]["id"],
                                            market_operator_headers), 200)
    forfeited = validate_success(
        api.forfeit_assignment(market_id, ctxs[1]["assignment"]["id"],
                               {"reason": "OPERATOR_EJECTION"}, market_operator_headers), 200)
    assert forfeited["status"] == "FORFEITED"

    market = get_market(market_id)
    assert market["total_booths_committed"] == 0
    booth = get_booth(market_id, ctxs[1]["booth"]["id"])
    assert booth["status"] == "AVAILABLE"
    vendor = get_vendor(ctxs[1]["vendor"]["id"])
    assert vendor["no_show_strikes"] == 0, \
        "OPERATOR_EJECTION forfeiture must not add a no-show strike"


def test_derived_total_booths_committed_increment_decrement(api, market_operator_headers):
    """PRD §3.4: "On activation, the booth's `status` transitions to `RESERVED`
    and the market's `total_booths_committed` increments by 1."
    PRD §3.4: "An `ACTIVE` assignment may be released by an operator, which
    transitions it to `RELEASED`, returns the booth to `AVAILABLE`, and
    decrements `total_booths_committed` by 1."

    Design: Corner/cross_cutting_layers/derived_field_reconciliation_total_booths_committed
    """
    ctx = setup_accepted_application()
    market_id = ctx["market"]["id"]
    asg = create_assignment_for(market_id, ctx["booth"]["id"], ctx["application"]["id"])
    assert get_market(market_id)["total_booths_committed"] == 0

    validate_success(api.activate_assignment(market_id, asg["id"],
                                             market_operator_headers), 200)
    assert get_market(market_id)["total_booths_committed"] == 1

    validate_success(api.release_assignment(market_id, asg["id"],
                                            market_operator_headers), 200)
    assert get_market(market_id)["total_booths_committed"] == 0


def test_permit_revoke_cascades_to_assignment_and_booth(api, market_operator_headers):
    """PRD §3.5: "Both transitions carry the same side effect: if the permit is
    a `TEMP_STRUCTURE` permit and a booth assignment is linked, the assignment
    transitions to `FORFEITED` with reason `PERMIT_REVOKED`."
    PRD §3.4: "Forfeiture transitions the assignment to `FORFEITED`, returns the
    booth to `AVAILABLE`, decrements `total_booths_committed` by 1, and — only
    when `reason` is `NO_SHOW` — increments the vendor's `no_show_strikes` by 1."

    Design: Difficulty/transitive_cascade/permit_revoke_cascade_depth3
    """
    ctx = setup_active_assignment(booth_overrides={"booth_code": "CH-P",
                                                   "booth_type": "CHALET", "zone": "SOUTH",
                                                   "square_feet": 100})
    market_id = ctx["market"]["id"]
    permit = create_permit_for(market_id, ctx["assignment"]["id"], "TEMP_STRUCTURE")

    revoked = validate_success(api.revoke_permit(market_id, permit["id"],
                                                 market_operator_headers), 200)
    assert revoked["status"] == "REVOKED"
    asg = get_assignment(market_id, ctx["assignment"]["id"])
    assert asg["status"] == "FORFEITED", "cascade link 1: assignment forfeited"
    booth = get_booth(market_id, ctx["booth"]["id"])
    assert booth["status"] == "AVAILABLE", "cascade link 2: booth returned"


def test_permit_revoke_cascade_restores_commitment_without_no_show_strike(api,
                                                                          market_operator_headers):
    """PRD §3.5: "Both transitions carry the same side effect: if the permit is
    a `TEMP_STRUCTURE` permit and a booth assignment is linked, the assignment
    transitions to `FORFEITED` with reason `PERMIT_REVOKED`."
    PRD §3.4: "Forfeiture transitions the assignment to `FORFEITED`, returns the
    booth to `AVAILABLE`, decrements `total_booths_committed` by 1, and — only
    when `reason` is `NO_SHOW` — increments the vendor's `no_show_strikes` by 1."

    Design: Difficulty/transitive_cascade/permit_revoke_cascade_depth3
    """
    ctx = setup_active_assignment(booth_overrides={"booth_code": "CH-P2",
                                                   "booth_type": "CHALET", "zone": "SOUTH",
                                                   "square_feet": 100})
    market_id = ctx["market"]["id"]
    permit = create_permit_for(market_id, ctx["assignment"]["id"], "TEMP_STRUCTURE")
    assert get_market(market_id)["total_booths_committed"] == 1

    validate_success(api.revoke_permit(market_id, permit["id"], market_operator_headers), 200)
    market = get_market(market_id)
    assert market["total_booths_committed"] == 0, "cascade link 3: counter decremented"
    vendor = get_vendor(ctx["vendor"]["id"])
    assert vendor["no_show_strikes"] == 0, \
        "PERMIT_REVOKED forfeiture must not add a no-show strike"


def _setup_propane_hookup_without_permit(api, name_suffix=""):
    """Market SETUP + powered CHALET booth + INSTALLED PROPANE hookup, with no
    PROPANE_HEAT permit anywhere."""
    market = create_market({"name": f"M10{name_suffix}",
                            "season_code": f"W26J{name_suffix}"})
    booth = create_booth_entity(market["id"], booth_code=f"CH-PROP{name_suffix}",
                                booth_type="CHALET", zone="NORTH", square_feet=100,
                                has_power=True)
    hookup = create_installed_hookup(market["id"], booth["id"], "PROPANE")
    assert hookup["status"] == "INSTALLED"
    return market, booth, hookup


def test_energize_propane_without_permit_rejected(api, utility_crew_headers):
    """PRD §3.5: "Energizing transitions an `INSTALLED` hookup to `ENERGIZED`;
    energizing requires the market to be in `SETUP` or `OPEN` posture, and for
    `PROPANE` hookups it additionally requires an `ACTIVE` `PROPANE_HEAT` permit
    for the same booth's `ACTIVE` assignment — otherwise rejected with
    `ERR_PERMIT_REQUIRED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential
    """
    market, _booth, hookup = _setup_propane_hookup_without_permit(api)
    res = api.energize_hookup(market["id"], hookup["id"], utility_crew_headers)
    validate_error(res, "ERR_PERMIT_REQUIRED", expected_status=409)


def test_energize_propane_with_active_permit_succeeds(api, utility_crew_headers):
    """PRD §3.5: "Energizing transitions an `INSTALLED` hookup to `ENERGIZED`;
    energizing requires the market to be in `SETUP` or `OPEN` posture, and for
    `PROPANE` hookups it additionally requires an `ACTIVE` `PROPANE_HEAT` permit
    for the same booth's `ACTIVE` assignment — otherwise rejected with
    `ERR_PERMIT_REQUIRED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential
    """
    ctx = setup_active_assignment(booth_overrides={"booth_code": "CH-HOK",
                                                   "booth_type": "CHALET", "zone": "NORTH",
                                                   "square_feet": 100, "has_power": True})
    market_id = ctx["market"]["id"]
    create_permit_for(market_id, ctx["assignment"]["id"], "PROPANE_HEAT")
    hookup = create_installed_hookup(market_id, ctx["booth"]["id"], "PROPANE")
    energized = validate_success(api.energize_hookup(market_id, hookup["id"],
                                                     utility_crew_headers), 200)
    assert energized["status"] == "ENERGIZED"


def test_energize_propane_rejected_when_assignment_has_no_permit(api, utility_crew_headers):
    """PRD §3.5: "Energizing transitions an `INSTALLED` hookup to `ENERGIZED`;
    energizing requires the market to be in `SETUP` or `OPEN` posture, and for
    `PROPANE` hookups it additionally requires an `ACTIVE` `PROPANE_HEAT` permit
    for the same booth's `ACTIVE` assignment — otherwise rejected with
    `ERR_PERMIT_REQUIRED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/hookup_energize_requires_permit_active
    """
    ctx = setup_active_assignment(booth_overrides={"booth_code": "CH-H",
                                                   "booth_type": "CHALET", "zone": "NORTH",
                                                   "square_feet": 100, "has_power": True})
    hookup = create_installed_hookup(ctx["market"]["id"], ctx["booth"]["id"], "PROPANE")
    res = api.energize_hookup(ctx["market"]["id"], hookup["id"], utility_crew_headers)
    validate_error(res, "ERR_PERMIT_REQUIRED", expected_status=409)


def test_energize_propane_rejected_when_permit_revoked(api, utility_crew_headers,
                                                       market_operator_headers):
    """PRD §3.5: "Energizing transitions an `INSTALLED` hookup to `ENERGIZED`;
    energizing requires the market to be in `SETUP` or `OPEN` posture, and for
    `PROPANE` hookups it additionally requires an `ACTIVE` `PROPANE_HEAT` permit
    for the same booth's `ACTIVE` assignment — otherwise rejected with
    `ERR_PERMIT_REQUIRED` (HTTP 409)."
    PRD §3.5: "A permit starts in `ACTIVE` status and may transition to
    `EXPIRED` (automatically during `run_ops` when the current UTC instant is at
    or past `expires_at`) or `REVOKED` (by operator action)."

    Design: Difficulty/cross_entity_state_dependency/hookup_energize_requires_permit_active
    """
    ctx = setup_active_assignment(booth_overrides={"booth_code": "CH-HR",
                                                   "booth_type": "CHALET", "zone": "NORTH",
                                                   "square_feet": 100, "has_power": True})
    market_id = ctx["market"]["id"]
    permit = create_permit_for(market_id, ctx["assignment"]["id"], "PROPANE_HEAT")
    validate_success(api.revoke_permit(market_id, permit["id"], market_operator_headers), 200)
    hookup = create_installed_hookup(market_id, ctx["booth"]["id"], "PROPANE")
    res = api.energize_hookup(market_id, hookup["id"], utility_crew_headers)
    validate_error(res, "ERR_PERMIT_REQUIRED", expected_status=409)
    asg = get_assignment(market_id, ctx["assignment"]["id"])
    assert asg["status"] == "ACTIVE", \
        "revoking a PROPANE_HEAT permit must not cascade-forfeit the assignment"
