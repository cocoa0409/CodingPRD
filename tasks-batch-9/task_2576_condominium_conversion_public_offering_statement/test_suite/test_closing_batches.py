"""Closing batches: assignment, unassignment, the inclusive threshold pair, the
half-open window and the release gate on closing.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_cents,
    assert_decimal_equals,
    assert_instant,
    assert_no_write,
    assert_page,
)
from test_helpers.factories import (
    assignment_payload,
    batch_payload,
    component_payload,
)
from test_helpers.fixtures import (
    assign_agreement,
    batch_version,
    build_registered_project,
    deliver_pos,
    evaluate_threshold,
    fund_escrow,
    harden,
    make_agreement,
    make_batch,
    make_project,
    release_batch,
    set_clock,
)
from test_helpers.test_users import escrow_headers, sponsor_headers

FOUNDATION = component_payload(
    "FOUNDATION", 40, 20, 10000000, 5000, "EXCELLENT", 0, False, True
)


def test_threshold_evaluation_on_a_draft_batch_reports_invalid_state_transition(api):
    """PRD: An evaluation from `OPEN_FOR_ASSIGNMENT` requires the project's
    `included_unit_count` to be at least 1 and takes the batch `OPEN_FOR_ASSIGNMENT →
    THRESHOLD_MET` when met and `OPEN_FOR_ASSIGNMENT → THRESHOLD_SHORT` when not.

    Design: Corner/validations/threshold_evaluation_on_a_draft_batch_reports_invalid_state_transition
    """
    project = make_project(api, "44 Cove Lane, Bangor ME", 1968, 2)
    batch = make_batch(
        api,
        project["id"],
        1,
        "2026-09-01T00:00:00Z",
        "2026-10-01T00:00:00Z",
        50,
        1,
    )
    assert batch["status"] == "DRAFT"

    validate_error(
        api.evaluate_threshold(batch["id"], sponsor_headers()),
        "ERR_INVALID_STATE_TRANSITION",
        expected_status=409,
    )

    after = validate_success(api.get_batch(batch["id"], sponsor_headers()))
    assert after["status"] == "DRAFT"
    assert_decimal_equals(after["presale_pct"], "0.00", "presale_pct")
    assert after["qualifying_agreement_count"] == 0
    assert after["assigned_agreement_count"] == 0
    assert after["version"] == batch["version"]
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "included_unit_count"
    ] == 0


def _effective_two_units(api, address="44 Cove Lane, Bangor ME"):
    """An EFFECTIVE statement over two INCLUDED units at 5000 bp each."""
    return build_registered_project(
        api,
        address,
        1968,
        unit_specs=(("101", 5000), ("102", 5000)),
        components=[FOUNDATION],
        annual_operating_expense_cents=1000000,
        boundary_convention="PAINT_TO_PAINT",
        opening_reserve_balance_cents=0,
        section_word_count=200,
        body_ref_prefix="s1",
    )


def test_delete_agreement_assignment_unlinks_without_deleting_the_agreement(api):
    """PRD: The sponsor may also unassign an agreement from a batch that has not been
    released, clearing `closing_batch_id`, re-deriving both counters, and moving the
    batch from `THRESHOLD_MET` to `THRESHOLD_SHORT` when it no longer qualifies.

    Design: Corner/endpoints/delete_agreement_assignment_unlinks_without_deleting_the_agreement
    """
    built = _effective_two_units(api)
    u1, u2 = built["units"]
    owner = make_agreement(
        api, u1["id"], "Ada Ling", "TX-1001", "OWNER_OCCUPANT", 30000000, 3000000
    )
    investor = make_agreement(
        api, u2["id"], "Kestrel Holdings LLC", "TX-2002", "INVESTOR", 30000000, 3000000
    )
    batch = make_batch(
        api,
        built["project"]["id"],
        1,
        "2026-09-01T00:00:00Z",
        "2026-10-01T00:00:00Z",
        50,
        1,
    )
    created_version = batch["version"]
    assign_agreement(api, batch["id"], owner["id"], created_version)

    before = validate_success(api.get_batch(batch["id"], sponsor_headers()))
    assert before["assigned_agreement_count"] == 1
    assert before["qualifying_agreement_count"] == 0
    assert before["status"] == "OPEN_FOR_ASSIGNMENT"
    assert before["version"] == created_version + 1
    assert validate_success(api.get_agreement(owner["id"], sponsor_headers()))[
        "closing_batch_id"
    ] == batch["id"]

    validate_success(
        api.unassign_agreement(batch["id"], owner["id"], sponsor_headers())
    )

    unlinked = validate_success(api.get_agreement(owner["id"], sponsor_headers()))
    assert unlinked["closing_batch_id"] is None
    assert unlinked["contract_status"] == "SIGNED"
    assert unlinked["escrow_status"] == "PENDING"
    assert validate_success(api.get_agreement(investor["id"], sponsor_headers()))[
        "closing_batch_id"
    ] is None
    _, meta = validate_paginated(api.list_agreements(sponsor_headers()))
    assert_page(meta, total_count=2)

    after = validate_success(api.get_batch(batch["id"], sponsor_headers()))
    assert after["assigned_agreement_count"] == 0
    assert after["qualifying_agreement_count"] == 0
    assert_decimal_equals(after["presale_pct"], "0.00", "presale_pct")
    assert after["status"] == "OPEN_FOR_ASSIGNMENT"
    assert after["version"] == created_version + 2
    _, meta = validate_paginated(
        api.list_batch_agreements(batch["id"], sponsor_headers())
    )
    assert_page(meta, total_count=0)


def test_assigning_an_already_assigned_agreement_to_a_second_batch_is_refused(api):
    """PRD: The agreement's `conversion_project_id` must match the batch's, and its
    `closing_batch_id` must be null — an agreement already assigned anywhere is refused
    with `ERR_AGREEMENT_ALREADY_ASSIGNED` (409).

    Design: Corner/errors/assigning_an_already_assigned_agreement_to_a_second_batch_is_refused
    """
    built = _effective_two_units(api)
    project_id = built["project"]["id"]
    u1, u2 = built["units"]
    owner = make_agreement(
        api, u1["id"], "Ada Ling", "TX-1001", "OWNER_OCCUPANT", 30000000, 3000000
    )
    investor = make_agreement(
        api, u2["id"], "Kestrel Holdings LLC", "TX-2002", "INVESTOR", 30000000, 3000000
    )
    first = make_batch(
        api, project_id, 1, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", 50, 1
    )
    assign_agreement(api, first["id"], owner["id"], first["version"])
    second = make_batch(
        api, project_id, 2, "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z", 50, 1
    )
    second_version = second["version"]

    assert validate_success(api.get_agreement(owner["id"], sponsor_headers()))[
        "closing_batch_id"
    ] == first["id"]
    assert second["status"] == "DRAFT"

    validate_error(
        api.assign_agreement(
            second["id"],
            assignment_payload(owner["id"], second_version),
            sponsor_headers(),
        ),
        "ERR_AGREEMENT_ALREADY_ASSIGNED",
        expected_status=409,
    )
    assert validate_success(api.get_agreement(owner["id"], sponsor_headers()))[
        "closing_batch_id"
    ] == first["id"]
    refused = validate_success(api.get_batch(second["id"], sponsor_headers()))
    assert refused["status"] == "DRAFT"
    assert refused["assigned_agreement_count"] == 0
    assert refused["version"] == second_version

    validate_success(
        api.assign_agreement(
            second["id"],
            assignment_payload(investor["id"], second_version),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert validate_success(api.get_agreement(investor["id"], sponsor_headers()))[
        "closing_batch_id"
    ] == second["id"]
    assert validate_success(api.get_batch(second["id"], sponsor_headers()))[
        "status"
    ] == "OPEN_FOR_ASSIGNMENT"


def test_first_assignment_bumps_the_batch_and_strands_the_captured_batch_version(api):
    """PRD: The assignment is guarded against stale reads of the batch: a mismatch
    between `expected_closing_batch_version` and the batch's current `version` is
    rejected with `ERR_STALE_BATCH_VERSION` and HTTP status 412, leaving the batch and
    the agreement untouched.

    Design: Corner/cross_cutting_complexity_layers/first_assignment_bumps_the_batch_and_strands_the_captured_batch_version
    """
    built = _effective_two_units(api)
    u1, u2 = built["units"]
    owner = make_agreement(
        api, u1["id"], "Ada Ling", "TX-1001", "OWNER_OCCUPANT", 30000000, 3000000
    )
    investor = make_agreement(
        api, u2["id"], "Kestrel Holdings LLC", "TX-2002", "INVESTOR", 30000000, 3000000
    )
    batch = make_batch(
        api,
        built["project"]["id"],
        1,
        "2026-09-01T00:00:00Z",
        "2026-10-01T00:00:00Z",
        50,
        1,
    )
    captured = batch["version"]
    assert captured == 1
    assert batch["status"] == "DRAFT"
    assert batch["assigned_agreement_count"] == 0

    first = validate_success(
        api.assign_agreement(
            batch["id"], assignment_payload(owner["id"], captured), sponsor_headers()
        ),
        expected_status=201,
    )
    bumped = validate_success(api.get_batch(batch["id"], sponsor_headers()))
    assert bumped["version"] == 2
    assert bumped["status"] == "OPEN_FOR_ASSIGNMENT"
    assert bumped["assigned_agreement_count"] == 1
    assert validate_success(api.get_agreement(owner["id"], sponsor_headers()))[
        "closing_batch_id"
    ] == batch["id"]

    validate_error(
        api.assign_agreement(
            batch["id"], assignment_payload(investor["id"], captured), sponsor_headers()
        ),
        "ERR_STALE_BATCH_VERSION",
        expected_status=412,
    )
    stranded = validate_success(api.get_batch(batch["id"], sponsor_headers()))
    assert stranded["version"] == 2
    assert stranded["assigned_agreement_count"] == 1
    assert validate_success(api.get_agreement(investor["id"], sponsor_headers()))[
        "closing_batch_id"
    ] is None

    validate_success(
        api.assign_agreement(
            batch["id"],
            assignment_payload(investor["id"], first["version"]),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    final = validate_success(api.get_batch(batch["id"], sponsor_headers()))
    assert final["version"] == 3
    assert final["assigned_agreement_count"] == 2
    assert final["qualifying_agreement_count"] == 0
    assert_decimal_equals(final["presale_pct"], "0.00", "presale_pct")
    assert validate_success(api.get_agreement(investor["id"], sponsor_headers()))[
        "closing_batch_id"
    ] == batch["id"]


def test_presale_pct_inclusive_at_exact_threshold_equality(api):
    """PRD: The batch is met when `presale_pct` is **at or above**
    `min_presale_threshold_pct` and `qualifying_agreement_count` is **at or above**
    `min_absolute_unit_count`; the percentage comparison is made on the rounded value,
    not on the exact ratio.

    Design: Difficulty/boundary_precision_check/presale_pct_inclusive_at_exact_threshold_equality
    """
    built = build_registered_project(
        api,
        "31 Egress Way, Revere MA",
        1974,
        unit_specs=(("E-1", 5000), ("E-2", 5000)),
        components=[FOUNDATION],
        annual_operating_expense_cents=875000,
        boundary_convention="PAINT_TO_PAINT",
        opening_reserve_balance_cents=0,
    )
    project_id = built["project"]["id"]
    agreement = make_agreement(
        api,
        built["units"][0]["id"],
        "Hal Egress",
        "TAX-OO-14",
        "OWNER_OCCUPANT",
        24000000,
        2400000,
    )
    deliver_pos(api, agreement["id"])
    fund_escrow(api, agreement["id"], 2400000)
    set_clock(api, "2026-08-16T00:00:00Z")
    harden(api, agreement["id"])
    batch = make_batch(
        api,
        project_id,
        1,
        "2026-08-16T00:00:00Z",
        "2026-09-16T00:00:00Z",
        50.00,
        1,
    )
    assign_agreement(api, batch["id"], agreement["id"], batch_version(api, batch["id"]))

    def evaluate():
        row = validate_success(api.evaluate_threshold(batch["id"], sponsor_headers()))
        assert row["assigned_agreement_count"] == 1
        assert row["qualifying_agreement_count"] == 1
        assert_decimal_equals(row["presale_pct"], "50.00", "presale_pct")
        return row

    met = evaluate()
    assert met["status"] == "THRESHOLD_MET"
    assert_instant(met["last_evaluated_at"], "2026-08-16T00:00:00Z")

    validate_success(
        api.patch_batch(batch["id"], {"min_presale_threshold_pct": 50.01}, sponsor_headers())
    )
    short = evaluate()
    assert short["status"] == "THRESHOLD_SHORT"
    # A batch at `THRESHOLD_SHORT` is itself one of the eight RESTRICTED clauses, and
    # on rung 7 "The project's derived posture is consulted first: ... a batch release
    # attempted on a project whose posture is `RESTRICTED` rather than `OPEN` is
    # rejected with `ERR_PROJECT_RESTRICTED`" — strictly ahead of the threshold rule.
    assert validate_success(api.get_project(project_id, sponsor_headers()))[
        "posture"
    ] == "RESTRICTED"
    validate_error(
        api.release_batch(batch["id"], escrow_headers()),
        "ERR_PROJECT_RESTRICTED",
        expected_status=409,
    )
    assert validate_success(api.get_batch(batch["id"], sponsor_headers()))[
        "released_at"
    ] is None

    validate_success(
        api.patch_batch(batch["id"], {"min_presale_threshold_pct": 49.99}, sponsor_headers())
    )
    met_again = evaluate()
    assert met_again["status"] == "THRESHOLD_MET"

    validate_success(
        api.patch_batch(batch["id"], {"min_absolute_unit_count": 2}, sponsor_headers())
    )
    absolute_short = evaluate()
    assert absolute_short["status"] == "THRESHOLD_SHORT"

    final = validate_success(api.get_batch(batch["id"], sponsor_headers()))
    assert_decimal_equals(
        final["min_presale_threshold_pct"], "49.99", "min_presale_threshold_pct"
    )
    assert final["min_absolute_unit_count"] == 2
    assert final["released_at"] is None

    row = validate_success(api.get_agreement(agreement["id"], sponsor_headers()))
    assert row["contract_status"] == "HARD"
    assert row["escrow_status"] == "FUNDED"
    project = validate_success(api.get_project(project_id, sponsor_headers()))
    assert_cents(project["escrow_balance_cents"], 2400000, "escrow_balance_cents")
    assert_cents(project["escrow_reconciliation_delta_cents"], 0, "delta")


def test_closing_blocked_until_assigned_batch_is_released(api):
    """PRD: its `closing_batch_id` is non-null; the assigned batch is at `RELEASED`,
    refused otherwise with `ERR_BATCH_NOT_RELEASED` (409).

    Design: Difficulty/cross_entity_state_dependency/closing_blocked_until_assigned_batch_is_released
    """
    built = build_registered_project(
        api,
        "5 Gable Street, Chelsea MA",
        1963,
        unit_specs=(("G-1", 5000), ("G-2", 5000)),
        components=[FOUNDATION],
        annual_operating_expense_cents=875000,
        boundary_convention="PAINT_TO_PAINT",
        opening_reserve_balance_cents=0,
        section_word_count=180,
        body_ref_prefix="s3://pos/g",
    )
    project_id = built["project"]["id"]
    u1, u2 = built["units"]

    agreement = make_agreement(
        api, u1["id"], "Kira Gable", "TAX-OO-19", "OWNER_OCCUPANT", 24000000, 2400000
    )
    deliver_pos(api, agreement["id"])
    fund_escrow(api, agreement["id"], 2400000)
    set_clock(api, "2026-08-16T00:00:00Z")
    hardened = harden(api, agreement["id"])
    assert hardened["contract_status"] == "HARD"
    assert hardened["escrow_status"] == "FUNDED"

    batch = make_batch(
        api,
        project_id,
        1,
        "2026-08-16T00:00:00Z",
        "2026-09-16T00:00:00Z",
        50.00,
        1,
    )
    assign_agreement(api, batch["id"], agreement["id"])
    evaluated = evaluate_threshold(api, batch["id"])
    assert evaluated["status"] == "THRESHOLD_MET"
    assert_decimal_equals(evaluated["presale_pct"], "50.00", "presale_pct")
    assert evaluated["released_at"] is None

    # step 1: the agreement side of the dependency is fully satisfied, so the only
    # possible ground for refusal is the batch's own state.
    #
    # The assignment above "sets the agreement's `closing_batch_id` to the batch", and
    # "Each entity touched by such a cascade has its own `updated_at` refreshed ... and
    # its own `version` incremented by one" — so `hardened`'s version is deliberately
    # stale by then.  The no-write check is made against the state immediately before
    # the refused request.
    before_close = validate_success(
        api.get_agreement(agreement["id"], sponsor_headers())
    )
    validate_error(
        api.close_agreement(agreement["id"], escrow_headers()),
        "ERR_BATCH_NOT_RELEASED",
        expected_status=409,
    )
    refused = validate_success(api.get_agreement(agreement["id"], sponsor_headers()))
    assert refused["contract_status"] == "HARD"
    assert refused["escrow_status"] == "FUNDED"
    assert refused["closed_at"] is None
    assert_no_write(before_close, refused, "agreement")
    assert validate_success(api.get_unit(u1["id"], sponsor_headers()))[
        "sale_status"
    ] == "HARD_CONTRACT"
    mid_project = validate_success(api.get_project(project_id, sponsor_headers()))
    assert_cents(mid_project["escrow_balance_cents"], 2400000, "escrow_balance_cents")
    assert_cents(mid_project["escrow_disbursed_cents"], 0, "escrow_disbursed_cents")
    assert mid_project["status"] == "PRESALE"

    # step 2: nothing changes but the state of the other entity
    released = release_batch(api, batch["id"])
    assert released["status"] == "RELEASED"
    assert_instant(released["released_at"], "2026-08-16T00:00:00Z")
    assert validate_success(api.get_project(project_id, sponsor_headers()))[
        "status"
    ] == "CLOSINGS"

    # step 3: byte-identical request, different batch state
    closed = validate_success(api.close_agreement(agreement["id"], escrow_headers()))
    assert closed["contract_status"] == "CLOSED"
    assert closed["escrow_status"] == "DISBURSED"
    assert_instant(closed["closed_at"], "2026-08-16T00:00:00Z")

    assert validate_success(api.get_unit(u1["id"], sponsor_headers()))[
        "sale_status"
    ] == "SOLD"
    second = validate_success(api.get_unit(u2["id"], sponsor_headers()))
    assert second["declaration_status"] == "INCLUDED"
    assert second["sale_status"] == "UNSOLD"

    end_batch = validate_success(api.get_batch(batch["id"], sponsor_headers()))
    assert end_batch["status"] == "RELEASED"
    assert_instant(end_batch["released_at"], "2026-08-16T00:00:00Z")

    end_project = validate_success(api.get_project(project_id, sponsor_headers()))
    assert_cents(end_project["escrow_balance_cents"], 0, "escrow_balance_cents")
    assert_cents(
        end_project["escrow_disbursed_cents"], 2400000, "escrow_disbursed_cents"
    )
    assert_cents(end_project["escrow_refunded_cents"], 0, "escrow_refunded_cents")
    assert_cents(
        end_project["escrow_reconciliation_delta_cents"], 0, "escrow delta"
    )
    assert end_project["status"] == "CLOSINGS"


def test_closing_batch_half_open_window_adjacency_allowed(api):
    """PRD: Because both comparisons are strict, a new window starting at precisely the
    instant a sibling window ends is **accepted**: there is no buffer, no gap
    requirement, and no aggregate capacity beyond the rule that at most one batch may
    occupy any single instant.

    Design: Difficulty/resource_temporal_overlap/closing_batch_half_open_window_adjacency_allowed
    """
    project = make_project(api, "60 Ionic Place, Lynn MA", 1961, 4)
    project_id = project["id"]
    first = make_batch(
        api,
        project_id,
        1,
        "2026-08-16T00:00:00Z",
        "2026-09-16T00:00:00Z",
        50.00,
        1,
    )
    assert first["status"] == "DRAFT"

    # probe 1: adjacent after — new_start == other_end, so the overlap test is false
    adjacent_after = validate_success(
        api.create_batch(
            project_id,
            batch_payload(2, "2026-09-16T00:00:00Z", "2026-10-16T00:00:00Z", 50.00, 1),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert adjacent_after["status"] == "DRAFT"
    assert adjacent_after["batch_sequence_no"] == 2
    assert_instant(adjacent_after["window_start_at"], "2026-09-16T00:00:00Z")
    assert_decimal_equals(adjacent_after["presale_pct"], "0.00", "presale_pct")
    assert adjacent_after["assigned_agreement_count"] == 0
    assert adjacent_after["version"] == 1

    # probe 2: one shared second is enough, and there is no tolerance
    validate_error(
        api.create_batch(
            project_id,
            batch_payload(3, "2026-09-15T23:59:59Z", "2026-09-16T00:00:00Z", 50.00, 1),
            sponsor_headers(),
        ),
        "ERR_BATCH_WINDOW_OVERLAP",
        expected_status=409,
    )

    # probe 3: adjacent before — new_end == other_start, symmetric to probe 1
    adjacent_before = validate_success(
        api.create_batch(
            project_id,
            batch_payload(4, "2026-07-16T00:00:00Z", "2026-08-16T00:00:00Z", 50.00, 1),
            sponsor_headers(),
        ),
        expected_status=201,
    )
    assert adjacent_before["batch_sequence_no"] == 4
    assert adjacent_before["status"] == "DRAFT"

    # probe 4: containment is overlap
    validate_error(
        api.create_batch(
            project_id,
            batch_payload(5, "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z", 50.00, 1),
            sponsor_headers(),
        ),
        "ERR_BATCH_WINDOW_OVERLAP",
        expected_status=409,
    )

    # probe 5: an empty half-open interval is rejected on geometry alone
    validate_error(
        api.create_batch(
            project_id,
            batch_payload(6, "2026-11-16T00:00:00Z", "2026-11-16T00:00:00Z", 50.00, 1),
            sponsor_headers(),
        ),
        "ERR_BATCH_WINDOW_OVERLAP",
        expected_status=409,
    )

    rows, meta = validate_paginated(api.list_batches(project_id, sponsor_headers()))
    assert_page(meta, total_count=3)
    by_sequence = {row["batch_sequence_no"]: row for row in rows}
    assert sorted(by_sequence) == [1, 2, 4]
    assert_instant(by_sequence[4]["window_start_at"], "2026-07-16T00:00:00Z")
    assert_instant(by_sequence[4]["window_end_at"], "2026-08-16T00:00:00Z")
    assert_instant(by_sequence[1]["window_start_at"], "2026-08-16T00:00:00Z")
    assert_instant(by_sequence[1]["window_end_at"], "2026-09-16T00:00:00Z")
    assert_instant(by_sequence[2]["window_start_at"], "2026-09-16T00:00:00Z")
    assert_instant(by_sequence[2]["window_end_at"], "2026-10-16T00:00:00Z")
    assert all(row["status"] == "DRAFT" for row in rows)
