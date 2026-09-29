"""Placements: the home-state waterfall, the diligent-search revision loop and
the strict arithmetic of what counts as a valid declination.
"""

from test_helpers import (
    ERR_BROKER_SUSPENDED,
    ERR_DILIGENT_SEARCH_INSUFFICIENT,
    ERR_HOME_STATE_INDETERMINATE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PLACEMENT_ALREADY_BOUND,
    COMPLIANCE_OFFICER_ANDERS,
    PLATFORM_ADMIN,
    assert_pagination_meta,
    exposure,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_placements_list_paginates_and_reports_total_count_and_has_more(configured_world):
    """A window of two out of three placements reports the full total.

    PRD 2.3: "List responses populate `limit`, `offset`, `total_count` and
    `has_more` in the `meta` object of the envelope. `total_count` reflects the
    number of items matching the filters before pagination is applied, and
    `has_more` is true when items remain beyond the current window."

    Design: Corner/entities/placements_list_paginates_and_reports_total_count_and_has_more
    """
    world = configured_world
    world.create_placement(
        insured_name="Alpha Risk LLC",
        principal_place_of_business_state="TX",
        coverage_class="EXCESS_CASUALTY",
        state_exposures=[exposure("TX", 100_000_000)],
    )
    world.create_placement(
        insured_name="Beta Risk LLC",
        principal_place_of_business_state="NV",
        coverage_class="EXCESS_CASUALTY",
        state_exposures=[exposure("NV", 200_000_000)],
    )
    world.create_placement(
        insured_name="Gamma Risk LLC",
        principal_place_of_business_state="TX",
        coverage_class="EXCESS_CASUALTY",
        state_exposures=[exposure("TX", 300_000_000)],
    )

    first_page, meta = validate_paginated(
        world.api.list_placements(PLATFORM_ADMIN, {"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert_pagination_meta(meta, limit=2, offset=0, total_count=3, has_more=True)
    assert [row["insured_name"] for row in first_page] == ["Alpha Risk LLC", "Beta Risk LLC"]

    second_page, meta = validate_paginated(
        world.api.list_placements(PLATFORM_ADMIN, {"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert_pagination_meta(meta, limit=2, offset=2, total_count=3, has_more=False)
    assert second_page[0]["insured_name"] == "Gamma Risk LLC"

    nevada, meta = validate_paginated(
        world.api.list_placements(PLATFORM_ADMIN, {"home_state": "NV"})
    )
    assert len(nevada) == 1
    assert meta["total_count"] == 1
    assert nevada[0]["insured_name"] == "Beta Risk LLC"

    drafts, meta = validate_paginated(
        world.api.list_placements(PLATFORM_ADMIN, {"status": "DRAFT"})
    )
    assert meta["total_count"] == 3
    assert len(drafts) == 3


def test_placement_create_missing_state_exposures_returns_invalid_request(
    configured_world,
):
    """An absent exposure array is a shape failure, not a home-state failure.

    PRD 2.11: "**Field shape.** Every required field is present, of the declared
    type, within the declared range, and a member of the declared enumeration.
    Applies to every endpoint. Violation: `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/placement_create_missing_state_exposures_returns_invalid_request
    """
    world = configured_world
    validate_error(
        world.api.create_placement(
            {
                "insured_name": "Omission Risk LLC",
                "principal_place_of_business_state": "TX",
                "coverage_class": "PROPERTY",
            },
            world.broker_headers,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    rows, meta = validate_paginated(world.api.list_placements(PLATFORM_ADMIN))
    assert meta["total_count"] == 0
    assert rows == []


def test_declination_create_extra_field_status_is_ignored_input(configured_world):
    """Server-managed fields supplied by a client are not honoured.

    PRD 3.4: "A new declination's `status` is `RECORDED`."

    Design: Corner/entities/declination_create_extra_field_status_is_ignored_input
    """
    world = configured_world
    placement = world.create_placement()
    world.begin_search(placement)

    declination = validate_success(
        world.api.create_declination(
            placement["id"],
            {
                "admitted_carrier_name": "Republic Admitted Mutual",
                "state_code": "TX",
                "reason_code": "NO_APPETITE",
                "declined_on": "2026-07-10T00:00:00Z",
                "status": "INVALIDATED",
                "version": 99,
            },
            world.broker_headers,
        ),
        201,
    )
    assert declination["status"] == "RECORDED"
    assert declination["version"] == 1
    assert declination["admitted_insurer_name"] == "Republic Admitted Mutual"


def test_begin_search_on_a_placement_past_the_search_stage_returns_invalid_state(
    searched_world,
):
    """`begin-search` is declared only out of `DRAFT` and `CHANGES_REQUESTED`.

    PRD 2.11: "**State legality.** The subject record is in a state from which
    the requested transition is declared. Applies to every state-transition
    endpoint."

    Design: Corner/state_machines/begin_search_on_a_placement_past_the_search_stage_returns_invalid_state
    """
    world = searched_world
    before = world.get_placement()
    assert before["status"] == "SEARCH_COMPLETE"
    assert before["declination_count"] == 3

    validate_error(
        world.api.begin_search(before["id"], world.broker_headers),
        ERR_INVALID_STATE,
        409,
    )

    after = world.get_placement()
    assert after["status"] == "SEARCH_COMPLETE"
    assert after["declination_count"] == 3
    assert after["version"] == before["version"]


def test_replaying_complete_search_on_a_completed_placement_is_not_idempotent(
    searched_world,
):
    """A second completion is a repeat of a once-only transition, not a no-op.

    PRD 2.11: "Re-triggering a transition on a terminal state falls here as
    `ERR_INVALID_STATE`, as does any repeat of a once-only action such as
    calculating a policy's tax twice."

    Design: Corner/state_machines/replaying_complete_search_on_a_completed_placement_is_not_idempotent
    """
    world = searched_world
    before = world.get_placement()

    validate_error(
        world.api.complete_search(before["id"], world.broker_headers),
        ERR_INVALID_STATE,
        409,
    )

    after = world.get_placement()
    assert after["status"] == "SEARCH_COMPLETE"
    assert after["declination_count"] == 3
    assert after["version"] == before["version"]
    assert after["updated_at"] == before["updated_at"]


def test_diligent_search_count_excludes_wrong_state_wrong_reason_and_invalidated_rows(
    configured_world,
):
    """Three separate exclusions each cost the search a declination.

    PRD 3.4: "A declination is *valid* only if all four of the following hold:
    its `status` is `RECORDED`; its `reason_code` is anything other than
    `NOT_LICENSED_FOR_CLASS`, because an admitted carrier that is not licensed
    for the class is evidence of nothing about the market's willingness to write
    the risk; its `state_code` equals the placement's `home_state`, so
    declinations obtained elsewhere do not travel; and its `declined_on` is
    **at or after** a cutoff computed as the current logical clock minus a
    lookback of exactly 90 calendar days — a declination landing exactly on the
    cutoff instant still counts."

    Design: Corner/calculations/diligent_search_count_excludes_wrong_state_wrong_reason_and_invalidated_rows
    """
    world = configured_world
    placement = world.create_placement()
    assert placement["home_state"] == "TX"
    world.begin_search(placement)

    # Two rows that count.
    world.record_declination(
        placement,
        admitted_carrier_name="Republic Admitted Mutual",
        state_code="TX",
        reason_code="NO_APPETITE",
        declined_on="2026-07-10T00:00:00Z",
    )
    world.record_declination(
        placement,
        admitted_carrier_name="Pecos Standard Insurance",
        state_code="TX",
        reason_code="CAPACITY",
        declined_on="2026-07-12T00:00:00Z",
    )
    # Excluded by reason code.
    world.record_declination(
        placement,
        admitted_carrier_name="Brazos Admitted Fire",
        state_code="TX",
        reason_code="NOT_LICENSED_FOR_CLASS",
        declined_on="2026-07-16T00:00:00Z",
    )
    # Excluded because it was obtained outside the home state.
    world.record_declination(
        placement,
        admitted_carrier_name="Silver State Admitted Mutual",
        state_code="NV",
        reason_code="NO_APPETITE",
        declined_on="2026-07-18T00:00:00Z",
    )
    # Excluded because it was struck from the record.
    struck = world.record_declination(
        placement,
        admitted_carrier_name="Colorado River Casualty",
        state_code="TX",
        reason_code="CAPACITY",
        declined_on="2026-07-20T00:00:00Z",
    )
    invalidated = world.invalidate_declination(struck)
    assert invalidated["status"] == "INVALIDATED"

    # Five rows on file, only two of them valid, against a minimum of three.
    validate_error(
        world.api.complete_search(placement["id"], world.broker_headers),
        ERR_DILIGENT_SEARCH_INSUFFICIENT,
        422,
    )
    assert world.get_placement(placement["id"])["status"] == "SEARCH_IN_PROGRESS"

    world.record_declination(
        placement,
        admitted_carrier_name="Trinity Mutual Casualty",
        state_code="TX",
        reason_code="UNDERWRITING",
        declined_on="2026-07-22T00:00:00Z",
    )
    completed = world.complete_search(placement)
    assert completed["status"] == "SEARCH_COMPLETE"
    assert completed["declination_count"] == 3


def test_a_suspended_brokerage_cannot_begin_a_diligent_search(configured_world):
    """Suspension blocks the transition without touching the placement.

    PRD 3.1: "A suspended brokerage cannot begin a diligent search: the attempt
    is rejected with `ERR_BROKER_SUSPENDED`."

    Design: Corner/validations/a_suspended_brokerage_cannot_begin_a_diligent_search
    """
    world = configured_world
    placement = world.create_placement()
    suspended = world.suspend_broker()
    assert suspended["status"] == "SUSPENDED"

    validate_error(
        world.api.begin_search(placement["id"], world.broker_headers),
        ERR_BROKER_SUSPENDED,
        409,
    )

    after = world.get_placement(placement["id"])
    assert after["status"] == "DRAFT"
    assert after["version"] == placement["version"]


def test_an_export_list_risk_completes_the_search_with_zero_declinations(
    configured_world,
):
    """The export-list bypass ignores the minimum entirely.

    PRD 3.4: "The one bypass is the export list: when the placement's
    `is_export_list_risk` is true *and* the home state's
    `export_list_exempts_search` is also true, the search is sufficient
    regardless of the count."

    Design: Corner/validations/an_export_list_risk_completes_the_search_with_zero_declinations
    """
    world = configured_world
    assert world.program("TX")["export_list_exempts_search"] is True
    assert world.program("TX")["diligent_search_min_declinations"] == 3

    placement = world.create_placement(
        insured_name="Permian Export Risk LLC",
        is_export_list_risk=True,
        state_exposures=[exposure("TX", 300_000_000)],
    )
    assert placement["home_state"] == "TX"
    world.begin_search(placement)

    declinations = validate_success(
        world.api.list_declinations(placement["id"], PLATFORM_ADMIN), 200
    )
    assert declinations == []

    completed = world.complete_search(placement)
    assert completed["status"] == "SEARCH_COMPLETE"
    assert completed["declination_count"] == 0


def test_request_changes_after_the_placement_is_bound_returns_already_bound(
    policy_world,
):
    """Once a policy references the placement the search cannot be reopened.

    PRD 3.4: "`SEARCH_COMPLETE → CHANGES_REQUESTED`, available only to a
    `ComplianceOfficer`, sends a completed search back for revision; it requires
    that no policy yet references this placement, else
    `ERR_PLACEMENT_ALREADY_BOUND`, and it resets the placement's
    `declination_count` to 0 before setting the status and incrementing the
    `version`."

    Design: Corner/endpoints/request_changes_after_the_placement_is_bound_returns_already_bound
    """
    world = policy_world
    before = world.get_placement()
    assert before["status"] == "BOUND"
    assert before["declination_count"] == 3

    validate_error(
        world.api.request_changes(before["id"], COMPLIANCE_OFFICER_ANDERS),
        ERR_PLACEMENT_ALREADY_BOUND,
        409,
    )

    after = world.get_placement()
    assert after["status"] == "BOUND"
    assert after["declination_count"] == 3
    assert after["version"] == before["version"]


def test_invalidating_a_declination_is_an_action_endpoint_with_a_narrow_effect(
    searched_world,
):
    """Striking a declination moves that row and nothing else.

    PRD 3.4: "A `ComplianceOfficer` may strike one from the record, advancing
    `RECORDED → INVALIDATED` and incrementing the declination's `version`; the
    strike is refused with `ERR_PLACEMENT_ALREADY_BOUND` when the parent
    placement's `status` is already `BOUND`."

    Design: Corner/endpoints/invalidating_a_declination_is_an_action_endpoint_with_a_narrow_effect
    """
    world = searched_world
    placement_before = world.get_placement()
    target = world.declinations[0]

    invalidated = world.invalidate_declination(target)
    assert invalidated["status"] == "INVALIDATED"
    assert invalidated["version"] == target["version"] + 1

    # The pinned count on the placement is untouched by a later strike.
    placement_after = world.get_placement()
    assert placement_after["declination_count"] == 3
    assert placement_after["version"] == placement_before["version"]

    recorded = validate_success(
        world.api.list_declinations(
            placement_after["id"], PLATFORM_ADMIN, {"status": "RECORDED"}
        ),
        200,
    )
    assert len(recorded) == 2
    all_rows = validate_success(
        world.api.list_declinations(placement_after["id"], PLATFORM_ADMIN), 200
    )
    assert len(all_rows) == 3

    # `INVALIDATED` is terminal.
    validate_error(
        world.api.invalidate_declination(target["id"], COMPLIANCE_OFFICER_ANDERS),
        ERR_INVALID_STATE,
        409,
    )


def test_a_zero_value_principal_place_of_business_loses_the_home_state(world):
    """The principal place of business only wins on strictly positive exposure.

    PRD 3.3: "Second, the insured's principal place of business wins if — and
    only if — it carries real exposure: the system looks for an exposure entry
    whose `state_code` equals `principal_place_of_business_state` and whose
    `insured_value_cents` is **strictly greater than zero**, and if at least one
    such entry exists, the `home_state` is the principal place of business."

    Design: Difficulty/boundary_precision_check/home_state_ignores_a_zero_value_principal_place_of_business_row
    """
    world.create_broker()

    zero = world.create_placement(
        insured_name="Basin Logistics Zero LLC",
        principal_place_of_business_state="NV",
        coverage_class="EXCESS_CASUALTY",
        state_exposures=[
            exposure("NV", 0),
            exposure("TX", 500_000_000),
            exposure("CA", 500_000_000),
        ],
    )
    # Nevada is skipped, and the tie between Texas and California is broken
    # alphabetically.
    assert zero["home_state"] == "CA"
    assert zero["total_insured_value_cents"] == 1_000_000_000
    assert zero["status"] == "DRAFT"
    assert zero["declination_count"] == 0

    one_cent = world.create_placement(
        insured_name="Basin Logistics One Cent LLC",
        principal_place_of_business_state="NV",
        coverage_class="EXCESS_CASUALTY",
        state_exposures=[
            exposure("NV", 1),
            exposure("TX", 500_000_000),
            exposure("CA", 500_000_000),
        ],
    )
    # A single cent of real exposure is enough to win outright.
    assert one_cent["home_state"] == "NV"
    assert one_cent["total_insured_value_cents"] == 1_000_000_001


def test_a_placement_with_no_positive_exposure_at_all_is_indeterminate(world):
    """Zero-valued rows count toward the total but never toward the home state.

    PRD 3.3: "Third, failing that, the greatest insured value wins: among only
    those entries whose `insured_value_cents` is strictly greater than zero, the
    system finds the largest `insured_value_cents` and takes the alphabetically
    smallest `state_code` among the entries holding that largest value; if no
    entry has a positive insured value at all, the placement is refused with
    `ERR_HOME_STATE_INDETERMINATE`."

    Design: Difficulty/boundary_precision_check/home_state_ignores_a_zero_value_principal_place_of_business_row
    """
    world.create_broker()

    validate_error(
        world.api.create_placement(
            {
                "insured_name": "Basin Logistics All Zero LLC",
                "principal_place_of_business_state": "NV",
                "coverage_class": "EXCESS_CASUALTY",
                "is_export_list_risk": False,
                "state_exposures": [exposure("NV", 0), exposure("TX", 0)],
            },
            world.broker_headers,
        ),
        ERR_HOME_STATE_INDETERMINATE,
        422,
    )

    validate_error(
        world.api.create_placement(
            {
                "insured_name": "Basin Logistics Empty LLC",
                "principal_place_of_business_state": "NV",
                "coverage_class": "EXCESS_CASUALTY",
                "is_export_list_risk": False,
                "state_exposures": [],
            },
            world.broker_headers,
        ),
        ERR_HOME_STATE_INDETERMINATE,
        422,
    )

    rows, meta = validate_paginated(world.api.list_placements(PLATFORM_ADMIN))
    assert meta["total_count"] == 0
    assert rows == []


def test_a_declination_on_the_ninety_day_cutoff_instant_still_counts(configured_world):
    """The lookback boundary is inclusive to the instant.

    PRD 3.4: "A declination is *valid* only if all four of the following hold:
    its `status` is `RECORDED`; its `reason_code` is anything other than
    `NOT_LICENSED_FOR_CLASS`, because an admitted carrier that is not licensed
    for the class is evidence of nothing about the market's willingness to write
    the risk; its `state_code` equals the placement's `home_state`, so
    declinations obtained elsewhere do not travel; and its `declined_on` is
    **at or after** a cutoff computed as the current logical clock minus a
    lookback of exactly 90 calendar days — a declination landing exactly on the
    cutoff instant still counts."

    Design: Difficulty/boundary_precision_check/diligent_search_lookback_cutoff_is_inclusive_at_ninety_days
    """
    world = configured_world
    placement = world.create_placement(
        insured_name="Cutoff On LLC", state_exposures=[exposure("TX", 300_000_000)]
    )
    assert placement["home_state"] == "TX"
    world.begin_search(placement)

    # 2026-08-01 less ninety calendar days is 2026-05-03.
    for name in (
        "Republic Admitted Mutual",
        "Pecos Standard Insurance",
        "Trinity Mutual Casualty",
    ):
        world.record_declination(
            placement,
            admitted_carrier_name=name,
            state_code="TX",
            reason_code="NO_APPETITE",
            declined_on="2026-05-03T00:00:00Z",
        )

    completed = world.complete_search(placement)
    assert completed["status"] == "SEARCH_COMPLETE"
    assert completed["declination_count"] == 3


def test_a_declination_one_day_before_the_cutoff_is_stale(configured_world):
    """A single day beyond the lookback empties the whole search.

    PRD 3.4: "The count of valid declinations is compared against the home
    state's `diligent_search_min_declinations`, and the search is sufficient when
    the count is greater than or equal to that minimum."

    Design: Difficulty/boundary_precision_check/diligent_search_lookback_cutoff_is_inclusive_at_ninety_days
    """
    world = configured_world

    stale = world.create_placement(
        insured_name="Cutoff Off LLC", state_exposures=[exposure("TX", 300_000_000)]
    )
    world.begin_search(stale)
    for name in (
        "Republic Admitted Mutual",
        "Pecos Standard Insurance",
        "Trinity Mutual Casualty",
    ):
        world.record_declination(
            stale,
            admitted_carrier_name=name,
            state_code="TX",
            reason_code="NO_APPETITE",
            declined_on="2026-05-02T00:00:00Z",
        )
    validate_error(
        world.api.complete_search(stale["id"], world.broker_headers),
        ERR_DILIGENT_SEARCH_INSUFFICIENT,
        422,
    )
    unchanged = world.get_placement(stale["id"])
    assert unchanged["status"] == "SEARCH_IN_PROGRESS"
    assert unchanged["declination_count"] == 0

    mixed = world.create_placement(
        insured_name="Cutoff Mix LLC", state_exposures=[exposure("TX", 300_000_000)]
    )
    world.begin_search(mixed)
    for name, when in (
        ("Republic Admitted Mutual", "2026-05-03T00:00:00Z"),
        ("Pecos Standard Insurance", "2026-05-03T00:00:00Z"),
        ("Trinity Mutual Casualty", "2026-05-02T00:00:00Z"),
    ):
        world.record_declination(
            mixed,
            admitted_carrier_name=name,
            state_code="TX",
            reason_code="NO_APPETITE",
            declined_on=when,
        )
    validate_error(
        world.api.complete_search(mixed["id"], world.broker_headers),
        ERR_DILIGENT_SEARCH_INSUFFICIENT,
        422,
    )
    assert world.get_placement(mixed["id"])["status"] == "SEARCH_IN_PROGRESS"


def test_a_change_request_resets_the_declination_count_and_re_pins_it(searched_world):
    """The count is zeroed on revision and re-pinned at the next completion.

    PRD 2.7: "A placement's `declination_count` is pinned at the instant the
    diligent search is completed."

    Design: Difficulty/non_linear_state_machine/placement_revision_cycle_is_re_enterable_and_resets_the_declination_count
    """
    world = searched_world
    completed = world.get_placement()
    assert completed["status"] == "SEARCH_COMPLETE"
    assert completed["declination_count"] == 3

    revised = world.request_changes()
    assert revised["status"] == "CHANGES_REQUESTED"
    assert revised["declination_count"] == 0

    reopened = world.begin_search()
    assert reopened["status"] == "SEARCH_IN_PROGRESS"
    assert reopened["declination_count"] == 0

    world.record_declination(
        admitted_carrier_name="Brazos Admitted Indemnity",
        state_code="TX",
        reason_code="NO_APPETITE",
        declined_on="2026-07-20T00:00:00Z",
    )
    recompleted = world.complete_search()
    assert recompleted["status"] == "SEARCH_COMPLETE"
    assert recompleted["declination_count"] == 4


def test_the_revision_cycle_may_be_traversed_any_number_of_times(searched_world):
    """Two full loops around the cycle, each transition a mutation of its own.

    PRD 3.4: "`CHANGES_REQUESTED → SEARCH_IN_PROGRESS` re-opens the search under
    the same two ownership-and-active-brokerage preconditions as the first
    opening, closing a cycle — `SEARCH_COMPLETE → CHANGES_REQUESTED →
    SEARCH_IN_PROGRESS → SEARCH_COMPLETE` — that may be traversed any number of
    times."

    Design: Difficulty/non_linear_state_machine/placement_revision_cycle_is_re_enterable_and_resets_the_declination_count
    """
    world = searched_world
    version = world.get_placement()["version"]

    def step(transition, expected_status, expected_count):
        nonlocal version
        placement = transition()
        assert placement["status"] == expected_status
        assert placement["declination_count"] == expected_count
        assert placement["version"] == version + 1
        version = placement["version"]

    step(world.request_changes, "CHANGES_REQUESTED", 0)
    step(world.begin_search, "SEARCH_IN_PROGRESS", 0)

    world.record_declination(
        admitted_carrier_name="Brazos Admitted Indemnity",
        state_code="TX",
        reason_code="NO_APPETITE",
        declined_on="2026-07-20T00:00:00Z",
    )
    step(world.complete_search, "SEARCH_COMPLETE", 4)

    # Second lap around the same cycle.
    step(world.request_changes, "CHANGES_REQUESTED", 0)
    step(world.begin_search, "SEARCH_IN_PROGRESS", 0)
    step(world.complete_search, "SEARCH_COMPLETE", 4)

    rows = validate_success(
        world.api.list_declinations(world.placement["id"], PLATFORM_ADMIN), 200
    )
    assert len(rows) == 4
    assert all(row["status"] == "RECORDED" for row in rows)
