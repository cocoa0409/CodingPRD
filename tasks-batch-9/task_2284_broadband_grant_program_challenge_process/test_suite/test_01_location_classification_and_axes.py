"""Location classification bands and the two independent location state axes."""

from test_helpers import (
    add_milestone,
    api_client,
    create_location_payload,
    create_program,
    ingest_location,
    read_award,
    read_location,
    read_program,
    setup_construction_authorized_award,
    submit_milestone_evidence,
    terminate_award,
    validate_paginated,
    validate_success,
    verify_milestone,
)
from test_helpers.fixtures import ADMIN, ANALYST


def _boundary_program():
    """A program whose four speed thresholds and latency ceiling are stated
    explicitly at the documented default values."""
    return create_program(
        name="BEAD Boundary Fixture",
        unserved_down_mbps_threshold=25,
        unserved_up_mbps_threshold=3,
        served_down_mbps_threshold=100,
        served_up_mbps_threshold=20,
        max_latency_ms=100,
    )


def test_classification_speed_bands_are_inclusive_at_both_edges():
    """Classification's third and fourth tests compare strictly, so a reading
    that exactly equals a threshold escapes the branch below it.

    PRD 3.1: "Third, if `reported_down_mbps` is strictly below
    `unserved_down_mbps_threshold`, or `reported_up_mbps` is strictly below
    `unserved_up_mbps_threshold`, the location is `UNSERVED`; a location
    reporting exactly 25 down and 3 megabits per second up under the default
    thresholds therefore escapes this branch."
    PRD 3.1: "Otherwise the location is `SERVED`, and a location reporting
    exactly 100 down and 20 up under the default thresholds is `SERVED` rather
    than `UNDERSERVED`."

    Design: Difficulty/boundary_precision_check/location_classification_speed_and_latency_edges
    """
    program = _boundary_program()

    at_served_edge = validate_success(
        api_client.create_location(
            create_location_payload(
                program["id"],
                "ADDR-B001",
                reported_down_mbps=100,
                reported_up_mbps=20,
                reported_latency_ms=100,
                reported_technology="FIBER",
            ),
            ANALYST,
        ),
        201,
    )
    assert at_served_edge["classification_status"] == "SERVED"

    just_below_served = validate_success(
        api_client.create_location(
            create_location_payload(
                program["id"],
                "ADDR-B002",
                reported_down_mbps=99,
                reported_up_mbps=20,
                reported_latency_ms=100,
                reported_technology="FIBER",
            ),
            ANALYST,
        ),
        201,
    )
    assert just_below_served["classification_status"] == "UNDERSERVED"

    at_unserved_edge = validate_success(
        api_client.create_location(
            create_location_payload(
                program["id"],
                "ADDR-B003",
                reported_down_mbps=25,
                reported_up_mbps=3,
                reported_latency_ms=60,
                reported_technology="DSL",
            ),
            ANALYST,
        ),
        201,
    )
    assert at_unserved_edge["classification_status"] == "UNDERSERVED"

    just_below_unserved_down = validate_success(
        api_client.create_location(
            create_location_payload(
                program["id"],
                "ADDR-B004",
                reported_down_mbps=24,
                reported_up_mbps=3,
                reported_latency_ms=60,
                reported_technology="DSL",
            ),
            ANALYST,
        ),
        201,
    )
    assert just_below_unserved_down["classification_status"] == "UNSERVED"

    just_below_unserved_up = validate_success(
        api_client.create_location(
            create_location_payload(
                program["id"],
                "ADDR-B005",
                reported_down_mbps=25,
                reported_up_mbps=2,
                reported_latency_ms=60,
                reported_technology="DSL",
            ),
            ANALYST,
        ),
        201,
    )
    assert just_below_unserved_up["classification_status"] == "UNSERVED"


def test_classification_latency_branch_outranks_otherwise_served_speeds():
    """Latency is the second test in the fixed order, so a reading fast enough
    to be SERVED is still UNSERVED once latency passes the ceiling, while
    latency exactly at the ceiling leaves the speeds to decide.

    PRD 3.1: "Second, if `reported_latency_ms` is strictly greater than the
    program's `max_latency_ms`, the location is `UNSERVED`; latency exactly
    equal to the threshold does not trigger this branch."

    Design: Difficulty/boundary_precision_check/location_classification_speed_and_latency_edges
    """
    program = _boundary_program()

    at_latency_ceiling = ingest_location(
        program["id"],
        "ADDR-B011",
        reported_down_mbps=100,
        reported_up_mbps=20,
        reported_latency_ms=100,
        reported_technology="FIBER",
    )
    assert at_latency_ceiling["classification_status"] == "SERVED"

    over_latency_ceiling = validate_success(
        api_client.create_location(
            create_location_payload(
                program["id"],
                "ADDR-B012",
                reported_down_mbps=100,
                reported_up_mbps=20,
                reported_latency_ms=101,
                reported_technology="FIBER",
            ),
            ANALYST,
        ),
        201,
    )
    assert over_latency_ceiling["classification_status"] == "UNSERVED", (
        "Latency strictly above the ceiling classifies UNSERVED however fast "
        "the reported speeds are"
    )


def test_termination_rewinds_eligibility_axis_without_disturbing_service_axis():
    """The eligibility and service axes move independently, so termination's
    release of the eligibility axis leaves a location that already reached
    SERVICE_AVAILABLE exactly where it was, while locations still under
    construction are rewound.

    PRD 3.1: "The two evolve independently: a location can sit at
    `AWARD_BOUND` while still `NOT_BUILT`, and it can travel all the way to
    `CERTIFIED` without its eligibility axis ever changing again."
    PRD 3.7: "Each released location moves on the eligibility axis
    `AWARD_BOUND → AFFIRMED` and has its `awarded_award_id` cleared to null,
    returning it to the eligible pool; the application moves
    `AWARDED → NOT_SELECTED`; and the program's `scoring_posture` is recomputed
    on the standard rule."
    PRD 3.7: "Terminating from `CONSTRUCTION_AUTHORIZED` additionally returns
    every location whose `service_state` is `UNDER_CONSTRUCTION` to
    `NOT_BUILT`."

    Design: Difficulty/non_linear_state_machine/location_parallel_eligibility_and_service_axes
    """
    ctx = setup_construction_authorized_award()
    built = ctx["location_ids"]["L2"]

    milestone = add_milestone(ctx["award_id"], 1, [built])
    submit_milestone_evidence(
        ctx["award_id"], milestone["id"], [built], ctx["subgrantee_id"]
    )
    verify_milestone(ctx["award_id"], milestone["id"], "APPROVED")

    advanced = read_location(built)
    assert advanced["eligibility_state"] == "AWARD_BOUND"
    assert advanced["service_state"] == "SERVICE_AVAILABLE"

    terminate_award(ctx["award_id"], "Subgrantee withdrew from the build.")

    released = read_location(built)
    assert released["eligibility_state"] == "AFFIRMED"
    assert released["awarded_award_id"] is None
    assert released["service_state"] == "SERVICE_AVAILABLE", (
        "A location already at SERVICE_AVAILABLE is untouched by the rewind, "
        "which only returns UNDER_CONSTRUCTION locations to NOT_BUILT"
    )

    for key in ("L3", "L5"):
        rewound = read_location(ctx["location_ids"][key])
        assert rewound["eligibility_state"] == "AFFIRMED"
        assert rewound["awarded_award_id"] is None
        assert rewound["service_state"] == "NOT_BUILT"


def test_termination_voids_undisbursed_milestones_and_deobligates_remainder():
    """Termination's cascade voids every milestone that never reached
    DISBURSED and deobligates only the undisbursed remainder, which with
    nothing yet paid returns the whole obligation to the uncommitted balance.

    PRD 3.7: "A `DEOBLIGATION` ledger entry is appended for
    `obligation_amount_cents` minus `disbursed_to_date_cents` — the undisbursed
    remainder only."
    PRD 3.7: "Every `AWARD_BOUND` claim of the award moves to `RELEASED`, and
    every milestone of the award not already `DISBURSED` — that is, every
    milestone in `PLANNED`, `EVIDENCE_SUBMITTED`, `APPROVED`, `REJECTED` or
    `HELD` — moves to `VOIDED`."

    Design: Difficulty/non_linear_state_machine/location_parallel_eligibility_and_service_axes
    """
    ctx = setup_construction_authorized_award()
    built = ctx["location_ids"]["L2"]

    milestone = add_milestone(ctx["award_id"], 1, [built])
    submit_milestone_evidence(
        ctx["award_id"], milestone["id"], [built], ctx["subgrantee_id"]
    )
    verify_milestone(ctx["award_id"], milestone["id"], "APPROVED")

    terminated = terminate_award(ctx["award_id"], "Subgrantee withdrew.")
    assert terminated["award_state"] == "TERMINATED"
    assert terminated["disbursed_to_date_cents"] == 0

    rows, _ = validate_paginated(api_client.list_milestones(ctx["award_id"], ADMIN))
    assert [m["milestone_state"] for m in rows] == ["VOIDED"]

    program = read_program(ctx["program_id"])
    assert program["obligated_balance_cents"] == 0
    assert program["disbursed_balance_cents"] == 0
    assert program["uncommitted_balance_cents"] == 100000000

    entries, _ = validate_paginated(
        api_client.list_ledger_entries(ctx["award_id"], ADMIN)
    )
    deobligations = [e for e in entries if e["entry_type"] == "DEOBLIGATION"]
    assert len(deobligations) == 1
    assert deobligations[0]["amount_cents"] == read_award(ctx["award_id"])[
        "obligation_amount_cents"
    ]
