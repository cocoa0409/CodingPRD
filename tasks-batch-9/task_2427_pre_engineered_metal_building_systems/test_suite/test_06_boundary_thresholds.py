"""Thresholds tested from both sides of the boundary.

Each of these rules is stated with an inclusive or strict bound, so the only
convincing test is the pair: the last value that passes and the first that does
not.
"""

from test_helpers import (
    ADMIN,
    ENGINEER,
    SALES,
    STANDARD_KITS,
    append_components,
    assert_rate,
    authorize_builder,
    chain_locked_configuration,
    create_builder,
    create_design,
    create_jurisdiction,
    create_quote,
    create_quote_payload,
    get_builder,
    get_design,
    get_jurisdiction,
    member_component_payload,
    review_design,
    revise_design,
    set_clock,
    submit_design,
    validate_error,
    validate_paginated,
)

#: Twenty hundredths of the 9853859-cent parts subtotal, rounded half up.
ADJUSTMENT_FLOOR_CENTS = -1970772


def _design_at_two_consumed_revisions():
    """A REVISION_REQUIRED design that has already used two of its three laps."""
    chain = chain_locked_configuration()
    configuration = chain["configuration"]
    design = create_design(configuration["id"], configuration["version"])
    append_components(design["id"], [member_component_payload()])
    for _ in range(2):
        submit_design(design["id"])
        review_design(design["id"], "REQUEST_REVISION")
        revise_design(design["id"])
    submit_design(design["id"])
    review_design(design["id"], "REQUEST_REVISION")
    return design


def _two_jurisdictions_sharing_a_territory_and_three_builders():
    """One authorized builder against a territory cap of two, plus two candidates."""
    set_clock()
    harris = create_jurisdiction()
    galveston = create_jurisdiction(
        code="TX-GALVESTON",
        name="Galveston County TX",
        exposure_category="D",
        design_wind_speed_mph=150,
        max_authorized_builders=2,
    )
    first = create_builder(harris["id"])
    authorize_builder(first["id"])
    second = create_builder(
        harris["id"],
        name="Bayou Building Systems",
        tier="BRONZE",
        credit_limit_cents=50000000,
    )
    third = create_builder(
        galveston["id"],
        name="Island Erectors",
        tier="BRONZE",
        credit_limit_cents=50000000,
    )
    return {
        "harris": harris,
        "galveston": galveston,
        "first": first,
        "second": second,
        "third": third,
    }


def test_01_an_adjustment_exactly_at_the_floor_is_accepted_and_priced():
    """Twenty percent of the subtotal, negated, is still a legal adjustment.

    PRD §3.4: "The ``adjustment_cents`` value is a commercial lever with a floor:
    a negative adjustment may not be more negative than twenty percent of the
    parts subtotal, where that bound is twenty hundredths of ``subtotal_cents``
    rounded half up to whole cents and then negated."

    PRD §3.4: "``subtotal_cents`` is ``steel_cost_cents`` plus
    ``panel_cost_cents`` plus ``accessory_cost_cents``."

    Design: Difficulty/boundary_precision_check/adjustment_floor_at_exactly_twenty_percent_of_subtotal
    """
    chain = chain_locked_configuration(kits=STANDARD_KITS)

    quote = create_quote(
        chain["builder"]["id"],
        chain["configuration"]["id"],
        freight_distance_miles=240,
        adjustment_cents=ADJUSTMENT_FLOOR_CENTS,
    )

    assert quote["subtotal_cents"] == 9853859
    assert quote["adjustment_cents"] == -1970772
    # 9853859 - 1970772 + 165972.
    assert quote["pre_discount_total_cents"] == 8049059
    assert_rate(quote["total_discount_rate"], 0.03)
    assert quote["quoted_price_cents"] == 7807587


def test_02_one_cent_past_the_floor_is_refused_and_persists_nothing(api):
    """The bound is inclusive at the floor and exclusive one cent below it.

    PRD §3.4: "An ``adjustment_cents`` below that floor is rejected with
    ``ERR_ADJUSTMENT_LIMIT_EXCEEDED``; positive adjustments are unbounded."

    PRD §2.5: "Fifteenth, last, are the fiscal checks: the adjustment floor and
    the builder's credit."

    Design: Difficulty/boundary_precision_check/adjustment_floor_at_exactly_twenty_percent_of_subtotal
    """
    chain = chain_locked_configuration(kits=STANDARD_KITS)
    create_quote(
        chain["builder"]["id"],
        chain["configuration"]["id"],
        freight_distance_miles=240,
        adjustment_cents=ADJUSTMENT_FLOOR_CENTS,
    )

    response = api.create_quote(
        create_quote_payload(
            chain["builder"]["id"],
            chain["configuration"]["id"],
            freight_distance_miles=240,
            adjustment_cents=ADJUSTMENT_FLOOR_CENTS - 1,
        ),
        SALES,
    )

    validate_error(response, "ERR_ADJUSTMENT_LIMIT_EXCEEDED", expected_status=422)
    _, meta = validate_paginated(api.list_quotes(SALES))
    assert meta["total_count"] == 1


def test_03_the_third_revise_is_permitted_while_the_count_is_below_three():
    """A design may travel the review loop at most three times.

    PRD §3.6: "A design may travel that loop at most three times: the transition
    is permitted only while ``revision_count`` is strictly below three, and an
    attempt made when ``revision_count`` has already reached three is refused with
    ``ERR_REVISION_LIMIT_REACHED``."

    Design: Difficulty/boundary_precision_check/revision_limit_boundary_at_third_and_fourth_revise
    """
    design = _design_at_two_consumed_revisions()
    before = get_design(design["id"])
    assert before["revision_count"] == 2
    assert before["status"] == "REVISION_REQUIRED"

    third = revise_design(design["id"])

    assert third["revision_count"] == 3
    assert third["status"] == "DRAFT"


def test_04_the_fourth_revise_is_refused_once_the_count_has_reached_three(api):
    """At exactly three consumed revisions the loop is closed.

    PRD §3.6: "A design may travel that loop at most three times: the transition
    is permitted only while ``revision_count`` is strictly below three, and an
    attempt made when ``revision_count`` has already reached three is refused with
    ``ERR_REVISION_LIMIT_REACHED``."

    PRD §3.6: "**Consuming a revision.** An ``Engineer`` returns a
    ``REVISION_REQUIRED`` design to ``DRAFT``."

    Design: Difficulty/boundary_precision_check/revision_limit_boundary_at_third_and_fourth_revise
    """
    design = _design_at_two_consumed_revisions()
    revise_design(design["id"])
    submit_design(design["id"])
    review_design(design["id"], "REQUEST_REVISION")

    response = api.revise_design(design["id"], ENGINEER)

    validate_error(response, "ERR_REVISION_LIMIT_REACHED", expected_status=409)
    after = get_design(design["id"])
    assert after["revision_count"] == 3
    assert after["status"] == "REVISION_REQUIRED"


def test_05_the_second_authorization_fits_under_a_territory_cap_of_two():
    """One authorized builder is strictly below the cap, so one more is admitted.

    PRD §3.2: "Before it proceeds, the system counts the builders whose
    ``territory_code`` matches this builder's and whose ``status`` is
    ``AUTHORIZED``; if that count is already equal to or greater than the home
    jurisdiction's ``max_authorized_builders``, authorization is refused with
    ``ERR_TERRITORY_BUILDER_LIMIT``."

    PRD §3.2: "Put plainly: the count of authorized builders in the territory must
    be strictly below the cap for one more to be admitted, so a territory whose
    cap is 2 and which already holds two authorized builders admits none."

    Design: Difficulty/boundary_precision_check/territory_builder_limit_boundary_at_second_and_third_authorization
    """
    network = _two_jurisdictions_sharing_a_territory_and_three_builders()
    assert get_jurisdiction(network["harris"]["id"])["authorized_builder_count"] == 1

    second = authorize_builder(network["second"]["id"])

    assert second["status"] == "AUTHORIZED"
    assert get_jurisdiction(network["harris"]["id"])["authorized_builder_count"] == 2


def test_06_the_third_authorization_is_refused_on_a_territory_wide_count(api):
    """The cap counts the territory, so a sibling jurisdiction is also full.

    PRD §3.1: "Alongside it the server maintains ``authorized_builder_count``,
    which starts at 0 and always reflects the number of builders whose
    ``territory_code`` equals this jurisdiction's ``territory_code`` and whose
    ``status`` is ``AUTHORIZED``."

    PRD §3.1: "Note the scope carefully: the count is a **territory** count, not a
    per-jurisdiction count, so two jurisdictions sharing a ``territory_code`` see
    the same population and both have their ``authorized_builder_count`` refreshed
    whenever a builder in that territory is authorized or suspended."

    PRD §3.2: "The server copies the jurisdiction's ``territory_code`` onto the
    builder at creation — the builder's territory is a snapshot, not a live lookup
    — sets ``credit_used_cents`` to 0 and therefore ``credit_available_cents``
    equal to ``credit_limit_cents``, and places the builder in
    ``PENDING_AUTHORIZATION`` with ``authorized_at`` left null."

    Design: Difficulty/boundary_precision_check/territory_builder_limit_boundary_at_second_and_third_authorization
    """
    network = _two_jurisdictions_sharing_a_territory_and_three_builders()
    authorize_builder(network["second"]["id"])

    response = api.authorize_builder(network["third"]["id"], ADMIN)

    validate_error(response, "ERR_TERRITORY_BUILDER_LIMIT", expected_status=409)
    third = get_builder(network["third"]["id"])
    assert third["status"] == "PENDING_AUTHORIZATION"
    assert third["authorized_at"] is None
    # The Galveston jurisdiction shares TX-GULF and sees the same population.
    assert get_jurisdiction(network["galveston"]["id"])["authorized_builder_count"] == 2
