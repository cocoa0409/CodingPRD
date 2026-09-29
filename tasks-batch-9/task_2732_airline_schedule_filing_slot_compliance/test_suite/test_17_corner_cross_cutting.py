"""Cross-cutting breadth: concurrency tokens and read-after-write agreement.

A fork attempted from a token that a sibling write has already invalidated, and
one attach call followed immediately by four reads that must all tell the same
story about the same two rows.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_schedule_version,
    assert_score_matches_counters,
    assert_slot_holding,
    create_flight_leg,
    create_schedule_version,
    create_slot_holding,
    read_leg,
    read_version,
    setup_reference_data,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

OFFICER = TEST_USERS["compliance_officer_headers"]


# ─── Layer 1: the fork token is bumped by the whole subtree ───────────────

def _plan_whose_token_a_leg_create_has_already_moved():
    """A version read before its first leg existed, so the token is stale."""
    ref = setup_reference_data(("MUC", "TXL"))
    version = create_schedule_version(
        ref["carrier"]["id"], ref["season"]["id"], version_label="W26-O1"
    )
    ref["stale_token"] = version["version"]
    ref["leg"] = create_flight_leg(
        ref["carrier"]["id"],
        version["id"],
        ref["stations"]["MUC"]["id"],
        ref["stations"]["TXL"]["id"],
        "2026-11-03T08:00:00.000Z",
        "2026-11-03T09:00:00.000Z",
        flight_number="HX320",
    )
    ref["version"] = read_version(version["id"], ref["planner"])
    return ref


def _supersede(world, token):
    return api_client.supersede_schedule_version(
        world["version"]["id"],
        {
            "version_label": "W26-O2",
            "expected_schedule_version_version": token,
        },
        world["planner"],
    )


class TestSupersedingFromAStaleReadCreatesNoSuccessorAtAll:
    """One fork refused on its token, then the same fork with a fresh one."""

    def test_a_leg_create_invalidates_the_token_and_the_fork_writes_nothing(self):
        """The leg wrote a different row, yet it moved the version's token - and
        the refused fork leaves no successor and no change on the target.

        PRD §2.7: "Every write anywhere in that version's subtree - creating a
        leg, retiming a leg, cancelling a leg, assigning a tail, attaching a
        slot, validating, transmitting, acknowledging, or any compliance
        re-derivation triggered by those - increments the schedule version's
        `version`."

        PRD §2.7: "If the supplied value does not equal the current `version`,
        the request is rejected with `ERR_STALE_SCHEDULE_VERSION` (HTTP 412): the
        target version does not move to `SUPERSEDED`, no successor row is
        created, and no counter changes."

        Design: Corner/cross_cutting_complexity_layers/superseding_a_version_from_a_stale_read_creates_no_successor_at_all
        """
        world = _plan_whose_token_a_leg_create_has_already_moved()
        assert world["version"]["version"] > world["stale_token"]

        validate_error(
            _supersede(world, world["stale_token"]),
            ApiErrorId.ERR_STALE_SCHEDULE_VERSION,
            expected_status=412,
        )

        _, meta = validate_paginated(
            api_client.list_schedule_versions(
                world["planner"], params={"carrier_id": world["carrier"]["id"]}
            )
        )
        assert meta["total_count"] == 1

        target = read_version(world["version"]["id"], OFFICER)
        assert target["filing_status"] == "DRAFT"
        assert target["version"] == world["version"]["version"]
        assert target["leg_count"] == 1

    def test_the_retry_with_the_fresh_token_forks_an_empty_successor(self):
        """The successor is a brand-new plan: it points back at its parent and
        inherits the pair but not a single leg.

        PRD §2.7: "Re-reading the version and re-attempting with the fresh number
        succeeds."

        PRD §3.4: "a brand-new schedule version is created in `filing_status`
        `DRAFT` with `compliance_state` `CLEAN`, the same `carrier_id` and
        `season_id` as its parent, `supersedes_version_id` pointing back at the
        parent, and **zero legs** - a fork never copies the manifest."

        Design: Corner/cross_cutting_complexity_layers/superseding_a_version_from_a_stale_read_creates_no_successor_at_all
        """
        world = _plan_whose_token_a_leg_create_has_already_moved()
        validate_error(
            _supersede(world, world["stale_token"]),
            ApiErrorId.ERR_STALE_SCHEDULE_VERSION,
        )

        successor = validate_success(
            _supersede(world, world["version"]["version"]), expected_status=201
        )
        assert_schedule_version(successor)
        assert successor["supersedes_version_id"] == world["version"]["id"]
        assert successor["filing_status"] == "DRAFT"
        assert successor["compliance_state"] == "CLEAN"
        assert successor["leg_count"] == 0
        assert successor["filing_charge_accrued_cents"] == 0
        assert successor["carrier_id"] == world["carrier"]["id"]
        assert successor["season_id"] == world["season"]["id"]

        parent = read_version(world["version"]["id"], OFFICER)
        assert parent["filing_status"] == "SUPERSEDED"
        assert parent["version"] == world["version"]["version"] + 1
        assert read_leg(world["leg"]["id"], OFFICER)["schedule_version_id"] == (
            world["version"]["id"]
        )


# ─── Layer 2: detail and list projections of one write ────────────────────

def _one_leg_and_the_series_it_is_about_to_use():
    """An `FRA` Monday series and the single unslotted leg that matches it."""
    ref = setup_reference_data(("FRA", "MUC"))
    ref["holding"] = create_slot_holding(
        ref["stations"]["FRA"]["id"],
        ref["season"]["id"],
        ref["carrier"]["id"],
        movement_type="DEPARTURE",
        slot_time_utc="2026-11-02T08:00:00.000Z",
        days_of_week="1",
        series_weeks=5,
        historic_precedence=False,
    )
    ref["version"] = create_schedule_version(
        ref["carrier"]["id"], ref["season"]["id"], version_label="W26-C1"
    )
    ref["leg"] = create_flight_leg(
        ref["carrier"]["id"],
        ref["version"]["id"],
        ref["stations"]["FRA"]["id"],
        ref["stations"]["MUC"]["id"],
        "2026-11-02T08:00:00.000Z",
        "2026-11-02T09:00:00.000Z",
        flight_number="HX101",
    )
    return ref


def _attach(world):
    return api_client.attach_slot(
        world["leg"]["id"],
        {"slot_holding_id": world["holding"]["id"], "movement_type": "DEPARTURE"},
        world["planner"],
    )


class TestDerivedCountersAgreeBetweenTheDetailReadAndTheListRead:
    """One attach, then the same row read by id and through a filtered list."""

    def test_the_series_counters_are_identical_in_both_projections(self):
        """The write response already carries the new figures, and neither the
        detail read nor the filtered list disagrees with it by a single field.

        PRD §2.10: "When a request mutates a source row, every dependent
        quantity is recomputed inside that same request, in a fixed order, and
        the response body already reflects the result."

        PRD §4: "List slot series, filterable by station, season, carrier,
        historic predecessor, encumbering transaction, status, movement type and
        at-risk flag."

        Design: Corner/consistency_model/derived_counters_agree_between_the_detail_read_and_the_list_read
        """
        world = _one_leg_and_the_series_it_is_about_to_use()
        validate_success(_attach(world))

        detail = validate_success(
            api_client.get_slot_holding(world["holding"]["id"], world["planner"])
        )
        assert_slot_holding(detail)
        assert detail["attached_operations"] == 1
        assert detail["utilization_pct_as_filed"] == 20.00
        assert detail["credited_operations"] == 0
        assert detail["utilization_pct"] == 0.00
        assert detail["at_risk_of_loss"] is True

        rows, meta = validate_paginated(
            api_client.list_slot_holdings(
                world["planner"],
                params={
                    "season_id": world["season"]["id"],
                    "at_risk_of_loss": "true",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1
        assert rows[0] == detail

    def test_the_version_counters_are_identical_in_both_projections(self):
        """The at-risk series costs the plan 15.00 points the moment the attach
        lands, and the list projection reports the same five figures as the
        detail read.

        PRD §2.10: "That is a five-link chain fired by a single field change, and
        every link is observable in the same response or in an immediately
        following read."

        PRD §3.7: "A version with one at-risk slot alone has a raw penalty of
        15.00 and scores 85.00."

        Design: Corner/consistency_model/derived_counters_agree_between_the_detail_read_and_the_list_read
        """
        world = _one_leg_and_the_series_it_is_about_to_use()
        validate_success(_attach(world))

        detail = validate_success(
            api_client.get_schedule_version(world["version"]["id"], world["planner"])
        )
        assert detail["leg_count"] == 1
        assert detail["unslotted_leg_count"] == 0
        assert detail["at_risk_slot_count"] == 1
        assert detail["schedule_compliance_score"] == 85.00
        assert detail["compliance_state"] == "BLOCKED"
        assert_score_matches_counters(detail)

        rows, meta = validate_paginated(
            api_client.list_schedule_versions(
                world["planner"],
                params={
                    "carrier_id": world["carrier"]["id"],
                    "season_id": world["season"]["id"],
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1
        listed = rows[0]
        for field in (
            "leg_count",
            "unslotted_leg_count",
            "at_risk_slot_count",
            "schedule_compliance_score",
            "compliance_state",
        ):
            assert listed[field] == detail[field], field
