"""Single transitions: the states rows start in, and the ones they refuse.

Each test drives one transition and pins what it wrote — the stamp, the version
bump, the counter it refreshed — or drives a transition that is not available
from the current state and pins that nothing at all moved.
"""

from test_helpers import (
    ADMIN,
    LOGISTICS,
    SALES,
    accept_quote_payload,
    anchored_bom,
    assert_draft_configuration_is_uncomputed,
    assert_order_dimensions,
    assert_weight,
    authorize_builder,
    cancel_load,
    chain_accepted_order,
    chain_authorized_builder,
    chain_locked_configuration,
    chain_released_order,
    chain_sealed_order,
    create_builder,
    create_builder_payload,
    create_configuration,
    create_jurisdiction,
    create_quote,
    get_builder,
    get_configuration,
    get_drawing_package,
    get_jurisdiction,
    get_order,
    get_quote,
    get_shipment_load,
    lock_configuration,
    make_builder_headers,
    make_sealing_engineer_headers,
    minimal_bom,
    plan_load,
    publish_loading_criteria,
    set_clock,
    suspend_builder,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The instant the fixtures move the logical clock to, in the three-fractional-digit
#: form the API writes it back in.
WORKING_DAY_STAMP = "2026-08-05T00:00:00.000Z"


def test_01_a_new_builder_starts_pending_with_its_ledger_open(api):
    """Onboarding lands in PENDING_AUTHORIZATION and counts towards nothing.

    PRD §3.2: "The server copies the jurisdiction's ``territory_code`` onto the
    builder at creation — the builder's territory is a snapshot, not a live lookup
    — sets ``credit_used_cents`` to 0 and therefore ``credit_available_cents``
    equal to ``credit_limit_cents``, and places the builder in
    ``PENDING_AUTHORIZATION`` with ``authorized_at`` left null."

    PRD §3.1: "Alongside it the server maintains ``authorized_builder_count``,
    which starts at 0 and always reflects the number of builders whose
    ``territory_code`` equals this jurisdiction's ``territory_code`` and whose
    ``status`` is ``AUTHORIZED``."

    Design: Corner/state_machines/new_builder_starts_in_pending_authorization
    """
    set_clock()
    jurisdiction = create_jurisdiction()

    builder = validate_success(
        api.create_builder(create_builder_payload(jurisdiction["id"]), ADMIN),
        expected_status=201,
    )

    assert builder["status"] == "PENDING_AUTHORIZATION"
    assert builder["authorized_at"] is None
    assert builder["territory_code"] == "TX-GULF"
    assert builder["credit_used_cents"] == 0
    assert builder["credit_available_cents"] == 200000000
    assert get_jurisdiction(jurisdiction["id"])["authorized_builder_count"] == 0


def test_02_authorization_stamps_the_clock_and_refreshes_the_territory_count():
    """The transition into AUTHORIZED is what makes a builder countable.

    PRD §3.2: "On success the builder's ``status`` becomes ``AUTHORIZED``,
    ``authorized_at`` is stamped with the current logical clock,
    ``authorized_builder_count`` is recomputed for every jurisdiction sharing the
    builder's ``territory_code``, ``commercial_hold`` is cleared on every order
    belonging to this builder with each of those orders' ``production_status``
    recomputed, and the builder's ``version`` increments."

    PRD §3.2: "Authorization is the transition into ``AUTHORIZED``, and it is
    available from both ``PENDING_AUTHORIZATION`` and ``SUSPENDED`` — the same
    operation onboards a new builder and rehabilitates a suspended one."

    Design: Corner/state_machines/authorize_pending_builder_transitions_to_authorized
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    builder = create_builder(jurisdiction["id"])
    assert builder["version"] == 1

    authorized = authorize_builder(builder["id"])

    assert authorized["status"] == "AUTHORIZED"
    assert authorized["authorized_at"] == WORKING_DAY_STAMP
    assert authorized["version"] == 2
    assert get_jurisdiction(jurisdiction["id"])["authorized_builder_count"] == 1


def test_03_locking_for_a_suspended_builder_fails_the_authorization_gate(api):
    """The lock is a legal transition that a suspended builder may not use.

    PRD §3.3: "Locking a configuration in any other state yields
    ``ERR_INVALID_STATE_TRANSITION``, and locking a configuration whose builder is
    not ``AUTHORIZED`` yields ``ERR_BUILDER_NOT_AUTHORIZED``."

    PRD §3.2: "In all five, a builder that is ``PENDING_AUTHORIZATION`` or
    ``SUSPENDED`` produces ``ERR_BUILDER_NOT_AUTHORIZED``."

    Design: Corner/state_machines/lock_on_suspended_builder_fails_the_authorization_precondition
    """
    chain = chain_authorized_builder()
    configuration = create_configuration(
        chain["builder"]["id"], chain["jurisdiction"]["id"]
    )
    suspend_builder(chain["builder"]["id"])

    response = api.lock_configuration(configuration["id"], SALES)

    validate_error(response, "ERR_BUILDER_NOT_AUTHORIZED", expected_status=409)
    after = get_configuration(configuration["id"])
    assert after["version"] == 1
    assert_draft_configuration_is_uncomputed(after)
    assert get_jurisdiction(chain["jurisdiction"]["id"])["authorized_builder_count"] == 0


def test_04_issuing_a_quote_opens_a_thirty_day_window_and_reprices_nothing(api):
    """Issue stamps the two temporal fields and touches no price field.

    PRD §3.5: "On success ``issued_at`` is stamped with the current logical clock,
    ``valid_until`` is set to ``issued_at`` plus a validity window of thirty days,
    ``status`` becomes ``ISSUED``, and the quote's ``version`` increments."

    PRD §3.4: "While the quote is ``DRAFT``, ``issued_at`` and ``valid_until`` are
    null."

    PRD §2.4: "Every timestamp the business writes — ``issued_at``,
    ``valid_until``, ``locked_at``, ``authorized_at``, ``sealed_at``,
    ``released_at``, ``completed_at``, ``dispatched_at`` — is taken from the
    logical clock at the moment of the transition, and every temporal validation
    compares against it."

    Design: Corner/state_machines/issue_quote_stamps_issued_at_and_thirty_day_valid_until
    """
    chain = chain_locked_configuration()
    drafted = create_quote(chain["builder"]["id"], chain["configuration"]["id"])
    assert drafted["issued_at"] is None
    assert drafted["valid_until"] is None
    set_clock("2026-08-10T00:00:00Z")

    issued = validate_success(api.issue_quote(drafted["id"], SALES))

    assert issued["status"] == "ISSUED"
    assert issued["issued_at"] == "2026-08-10T00:00:00.000Z"
    assert issued["valid_until"] == "2026-09-09T00:00:00.000Z"
    assert issued["created_at"] == WORKING_DAY_STAMP
    assert issued["version"] == 2
    assert issued["quoted_price_cents"] == drafted["quoted_price_cents"]
    assert issued["subtotal_cents"] == drafted["subtotal_cents"]
    assert issued["freight_cost_cents"] == drafted["freight_cost_cents"]


def test_05_a_consumed_quote_refuses_both_a_second_accept_and_a_second_issue(api):
    """ACCEPTED is terminal, so neither transition is available from it.

    PRD §3.5: "Acceptance is the only operation a ``Builder`` may perform, and it
    moves the quote from ``ISSUED`` to the terminal state ``ACCEPTED``."

    PRD §3.5: "The quote must be ``ISSUED``, or the request fails with
    ``ERR_INVALID_STATE_TRANSITION``."

    PRD §3.5: "Issuing a quote that is not ``DRAFT`` yields
    ``ERR_INVALID_STATE_TRANSITION``."

    Design: Corner/state_machines/issue_and_accept_on_a_consumed_quote_return_invalid_state_transition
    """
    chain = chain_accepted_order()
    quote_id = chain["quote"]["id"]
    before = get_quote(quote_id)

    second_accept = api.accept_quote(
        quote_id,
        accept_quote_payload(requested_erection_start_date="2026-09-20T00:00:00Z"),
        make_builder_headers(chain["builder"]["id"]),
    )
    second_issue = api.issue_quote(quote_id, SALES)

    validate_error(second_accept, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
    validate_error(second_issue, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
    after = get_quote(quote_id)
    assert after["status"] == "ACCEPTED"
    assert after["version"] == before["version"]
    orders, meta = validate_paginated(api.list_orders(SALES, params={"quote_id": quote_id}))
    assert meta["total_count"] == 1
    assert orders[0]["id"] == chain["order"]["id"]
    builder = get_builder(chain["builder"]["id"])
    assert builder["credit_used_cents"] == after["quoted_price_cents"]
    order = get_order(chain["order"]["id"])
    assert order["requested_erection_start_date"].startswith("2026-09-15T00:00:00")


def test_06_a_cancelled_truck_can_be_neither_dispatched_nor_cancelled_again(api):
    """The from-state check is band nine, ahead of the lot-complete check.

    PRD §2.5: "and a shipment load must be ``PLANNED`` both to be dispatched and
    to be cancelled."

    PRD §2.5: "Ninth is the target resource's own from-state,
    ``ERR_INVALID_STATE_TRANSITION``."

    PRD §2.5: "Tenth are the states of related resources — a configuration that
    must be locked, a design that must be approved, drawings that must be sealed,
    an order that must be released, a fabrication lot that must be complete, an
    order that must be free of active work."

    Design: Corner/state_machines/cancelled_shipment_load_cannot_be_dispatched_or_cancelled_again
    """
    chain = chain_released_order(components=anchored_bom())
    load = plan_load(
        chain["order"]["id"],
        component_marks=["AB-1"],
        erection_stage="ANCHORAGE",
        unload_window_start="2026-09-15T08:00:00Z",
        unload_window_end="2026-09-15T12:00:00Z",
    )
    cancelled = cancel_load(load["id"])

    dispatch_again = api.dispatch_shipment_load(load["id"], LOGISTICS)
    cancel_again = api.cancel_shipment_load(load["id"], LOGISTICS)

    validate_error(dispatch_again, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
    validate_error(cancel_again, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
    after = get_shipment_load(load["id"])
    assert after["status"] == "CANCELLED"
    assert after["dispatched_at"] is None
    assert after["version"] == cancelled["version"]
    order = get_order(chain["order"]["id"])
    assert_weight(order["assigned_weight_lbs"], 0)
    assert_weight(order["unassigned_weight_lbs"], 15308.80)


def test_07_a_second_seal_is_refused_rather_than_replayed(api):
    """The stamps of the first seal survive, and no side effect re-runs.

    PRD §3.7: "The package must be ``PENDING``, or the request fails with
    ``ERR_INVALID_STATE_TRANSITION``."

    PRD §3.7: "A successful seal stamps ``sealed_at`` with the current logical
    clock, records the acting ``X-User-ID`` as ``sealed_by_user_id``, captures the
    jurisdiction's current ``criteria_revision`` as ``criteria_revision_at_seal``,
    and sets ``status`` to ``SEALED``."

    PRD §2.5: "Checks are evaluated in a fixed global precedence, and the first
    failure short-circuits the request: no later check runs and no state
    changes."

    Design: Corner/state_machines/second_seal_on_a_sealed_package_is_refused_not_replayed
    """
    chain = chain_sealed_order(components=minimal_bom())
    sealed = chain["package"]
    order_before = get_order(chain["order"]["id"])
    set_clock("2026-08-20T00:00:00Z")

    response = api.seal_drawing_package(
        sealed["id"], make_sealing_engineer_headers("u_seal_2")
    )

    validate_error(response, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
    package = get_drawing_package(sealed["id"])
    assert package["sealed_at"] == WORKING_DAY_STAMP
    assert package["sealed_by_user_id"] == "u_seal_1"
    assert package["version"] == sealed["version"]
    order_after = get_order(chain["order"]["id"])
    assert order_after["version"] == order_before["version"]
    assert_order_dimensions(order_after, "ENG_SEALED", "PROD_NOT_RELEASED")
    assert order_after["drawing_package_id"] == sealed["id"]


def test_08_a_criteria_revision_spares_drafts_and_other_jurisdictions():
    """Only a LOCKED configuration of the revised jurisdiction goes stale.

    PRD §3.1: "That single increment is the origin of the five-hop invalidation
    chain described in §2.10, and the trigger for the first hop is precise: a
    configuration goes stale only if it is currently ``LOCKED``, belongs to this
    jurisdiction, and has a ``criteria_revision_at_lock`` strictly below the
    jurisdiction's new ``criteria_revision``."

    PRD §3.1: "A configuration still in ``DRAFT`` is unaffected, because it has
    not yet pinned anything."

    PRD §2.10: "Every locked configuration of that jurisdiction whose
    ``criteria_revision_at_lock`` now sits below the new ``criteria_revision``
    becomes ``CRITERIA_STALE``."

    Design: Corner/state_machines/criteria_revision_spares_draft_and_other_jurisdiction_configurations
    """
    chain = chain_authorized_builder()
    builder_id = chain["builder"]["id"]
    harris = chain["jurisdiction"]
    bexar = create_jurisdiction(code="TX-BEXAR", name="Bexar County TX")
    locked = lock_configuration(
        create_configuration(builder_id, harris["id"])["id"]
    )
    draft = create_configuration(
        builder_id, harris["id"],
        clear_span_ft=80, eave_height_ft=20, insulation_r_value=13,
    )
    other = lock_configuration(
        create_configuration(builder_id, bexar["id"])["id"]
    )

    revised = publish_loading_criteria(
        harris["id"],
        exposure_category="D",
        design_wind_speed_mph=160,
        ground_snow_load_psf=5,
        seismic_design_category="B",
    )

    assert revised["criteria_revision"] == 2
    stale = get_configuration(locked["id"])
    assert stale["status"] == "CRITERIA_STALE"
    assert stale["version"] == locked["version"] + 1
    untouched_draft = get_configuration(draft["id"])
    assert untouched_draft["version"] == 1
    assert_draft_configuration_is_uncomputed(untouched_draft)
    untouched_other = get_configuration(other["id"])
    assert untouched_other["status"] == "LOCKED"
    assert untouched_other["version"] == other["version"]
    assert get_jurisdiction(bexar["id"])["criteria_revision"] == 1
