"""Policy lifecycle: binding, the waiting period and its boundary, activation,
expiring an unbound quote, the participating-community gate, and the lapse
precondition.

Covers difficulty queue A (boundary_precision_check waiting-period instance) and
corner queue B (state_machines, validations sections for the policy lifecycle).
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_community,
    create_property,
    create_elevation_certificate,
    quote_policy_as_underwriter,
    setup_quoted_policy,
    setup_bound_policy,
    setup_active_policy,
    assert_property,
    ApiErrorId,
    TEST_USERS,
)


def test_activate_at_effective_date_boundary_succeeds(api):
    """PRD §3.5: "Activation additionally requires that the waiting period has
    elapsed — the current logical-clock instant must be at or after the policy's
    `effective_date`; an earlier attempt is rejected with
    `ERR_WAITING_PERIOD_NOT_ELAPSED` (HTTP 409)."
    PRD §3.5: "`effective_date` is the bind date plus the waiting period"

    Design: Difficulty/boundary_precision_check/activate_at_effective_date_boundary_waiting_period
    """
    community, prop, bound = setup_bound_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="holder-14",
        flood_zone="X", base_flood_elevation_ft=10.0, lowest_floor_elevation_ft=11.0,
        crs_class=10, is_lender_required=False,
        building_coverage=100000, contents_coverage=40000, quote_as_underwriter=True,
    )
    assert bound["effective_date"] == "2026-03-31T00:00:00.000Z", bound["effective_date"]

    set_clock("2026-03-31T00:00:00Z")  # exactly at effective_date
    resp = api.activate_policy(bound["id"], TEST_USERS["underwriter_headers"])
    active = validate_success(resp)
    assert active["status"] == "ACTIVE", active["status"]


def test_activate_one_day_before_effective_date_rejected(api):
    """PRD §3.5: "Activation additionally requires that the waiting period has
    elapsed — the current logical-clock instant must be at or after the policy's
    `effective_date`; an earlier attempt is rejected with
    `ERR_WAITING_PERIOD_NOT_ELAPSED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/activate_at_effective_date_boundary_waiting_period
    """
    community, prop, bound = setup_bound_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="holder-14b",
        flood_zone="X", base_flood_elevation_ft=10.0, lowest_floor_elevation_ft=11.0,
        crs_class=10, is_lender_required=False,
        building_coverage=100000, contents_coverage=40000, quote_as_underwriter=True,
    )
    assert bound["effective_date"] == "2026-03-31T00:00:00.000Z", bound["effective_date"]

    set_clock("2026-03-30T00:00:00Z")  # one day before effective_date
    resp = api.activate_policy(bound["id"], TEST_USERS["underwriter_headers"])
    validate_error(resp, ApiErrorId.ERR_WAITING_PERIOD_NOT_ELAPSED, expected_status=409)


def test_bind_already_bound_policy_rejected(api):
    """PRD §3.5: "Binding is permitted only while the policy is `QUOTED`; an
    attempt against any other status is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/bind_from_already_bound_returns_invalid_state
    """
    community, prop, bound = setup_bound_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="h-b2",
        flood_zone="X", base_flood_elevation_ft=10.0, lowest_floor_elevation_ft=11.0,
        crs_class=10, is_lender_required=True,
        building_coverage=100000, contents_coverage=40000, quote_as_underwriter=True,
    )
    resp = api.bind_policy(bound["id"], TEST_USERS["underwriter_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_expire_quote_retires_unbound_quote(api):
    """PRD §3.5: "a policy in `QUOTED` status can be expired directly, moving it
    to the terminal `EXPIRED` status; this is permitted only from `QUOTED`"

    Design: Corner/state_machines/expire_quote_retires_unbound_quote
    """
    community, prop, policy = setup_quoted_policy(
        owner_id="h-qe", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
    )
    resp = api.expire_quote(policy["id"], TEST_USERS["underwriter_headers"])
    expired = validate_success(resp)
    assert expired["status"] == "EXPIRED", expired["status"]


def test_bind_in_non_participating_community_rejected(api):
    """PRD §3.5: "Binding requires that the property's community is participating:
    if the resolved community's `participating` flag is false, the bind is
    rejected with `ERR_COMMUNITY_NOT_PARTICIPATING` (HTTP 409)."

    Design: Corner/validations/bind_in_non_participating_community_rejected
    """
    community = create_community(crs_class=10, participating=False)
    set_clock("2026-03-01T00:00:00Z")
    prop = create_property(
        community["id"], "h-np", flood_zone="X",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=10.0,
    )
    create_elevation_certificate(prop["id"], "h-np", lowest_floor_elevation_ft=11.0)
    policy = quote_policy_as_underwriter(
        prop["id"], "RISK_RATING_2_0",
        building_coverage=100000, contents_coverage=40000, is_lender_required=True,
    )
    resp = api.bind_policy(policy["id"], TEST_USERS["underwriter_headers"])
    validate_error(resp, ApiErrorId.ERR_COMMUNITY_NOT_PARTICIPATING, expected_status=409)


def test_lapse_before_expiration_rejected(api):
    """PRD §3.6: "but only once the term has run: the current logical-clock
    instant must be at or after the policy's `expiration_date`, and an earlier
    attempt is rejected with `ERR_POLICY_NOT_EXPIRED` (HTTP 409)."

    Design: Corner/state_machines/lapse_before_expiration_returns_policy_not_expired
    """
    community, prop, active = setup_active_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="h-lp",
        flood_zone="X", base_flood_elevation_ft=10.0, lowest_floor_elevation_ft=11.0,
        crs_class=10, is_lender_required=True,
        building_coverage=100000, contents_coverage=40000, quote_as_underwriter=True,
    )
    set_clock("2026-06-01T00:00:00Z")  # well before expiration 2027-03-01
    resp = api.lapse_policy(active["id"], TEST_USERS["underwriter_headers"])
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_EXPIRED, expected_status=409)


def test_activate_sets_compliant_on_sfha_mortgaged_property(api):
    """PRD §3.5: "When a policy activates, the property's `active_policy_id` is
    set to point at it, and where the structure is both in an SFHA and mortgaged
    the property's `compliance_status` becomes `COMPLIANT`."

    Design: Corner/state_machines/activate_after_compliance_becomes_compliant
    """
    community, prop, active = setup_active_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="h-cm",
        flood_zone="AE", base_flood_elevation_ft=8.0, lowest_floor_elevation_ft=10.0,
        has_active_mortgage=True, crs_class=10, is_lender_required=True,
        building_coverage=250000, contents_coverage=100000, quote_as_underwriter=True,
    )
    assert active["status"] == "ACTIVE", active["status"]
    fetched = validate_success(
        api.get_property(prop["id"], TEST_USERS["underwriter_headers"])
    )
    assert_property(fetched)
    assert fetched["compliance_status"] == "COMPLIANT", fetched["compliance_status"]
    assert fetched["active_policy_id"] == active["id"], fetched["active_policy_id"]


def test_active_policy_pointer_visible_immediately(api):
    """PRD §3.2: "`active_policy_id` is a denormalized pointer to the property's
    currently in-force policy, or null when none is active; it is set when a
    policy activates and cleared when that policy leaves the active state."

    Design: Corner/consistency_model/immediate_consistency_active_policy_pointer_in_same_response_chain
    """
    community, prop, active = setup_active_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="h-im",
        flood_zone="X", base_flood_elevation_ft=10.0, lowest_floor_elevation_ft=11.0,
        crs_class=10, is_lender_required=True,
        building_coverage=100000, contents_coverage=40000, quote_as_underwriter=True,
    )
    fetched = validate_success(
        api.get_property(prop["id"], TEST_USERS["underwriter_headers"])
    )
    assert fetched["active_policy_id"] == active["id"], fetched["active_policy_id"]
