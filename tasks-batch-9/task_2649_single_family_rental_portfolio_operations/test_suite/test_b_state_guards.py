"""Re-entrant cure cycles, the second terminal exit, and the two ordered lock guards.

The obligation dimension is the only true cycle in the system and the only place a counter
records how many times a row has been round the loop; the scope lock is the only place two
guards of different ranks sit on the same call.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import ERR_HOME_NOT_ACQUIRED, ERR_PROJECT_SCOPE_EMPTY
from test_helpers.assertions import (
    assert_absent_or_empty,
    assert_fields,
    assert_home_dimensions,
    assert_money_group,
    created,
    failed,
    ok,
)
from test_helpers.constants import (
    ASSET_ACQUIRED,
    ASSET_RENOVATING,
    ASSET_STABILIZED,
    CLOCK_SEP_06,
    OBLIGATION_PLANNED,
    OBLIGATION_RESOLUTION_REJECTED,
    OBLIGATION_RESOLUTION_SUBMITTED,
    OBLIGATION_WAIVED,
    OCC_VACANT,
    POSTURE_FROZEN,
    POSTURE_RESTRICTED,
    PROJECT_IN_PROGRESS,
    PROJECT_RENT_READY,
    PROJECT_SCOPING,
)


def test_a_rejected_resolution_reopens_the_cure_loop_and_counts_the_round(api):
    """Only the re-entry increments the counter, and the second submit re-stamps co-2.

    PRD SS3.9: "`REJECT` moves the obligation `RESOLUTION_SUBMITTED` -> `RESOLUTION_REJECTED`
    and clears `submitted_by_user_id`, reopening the cure cycle so it can be planned again for
    another round."  PRD SS3.9 on planning: "Planning moves the obligation `OPEN -> PLANNED`, or
    `RESOLUTION_REJECTED -> PLANNED` with `resolution_round` increased by 1 -- that counter
    records how many rejected-and-replanned cure rounds the obligation has been through."  PRD
    SS3.9 on submission: "The obligation moves `PLANNED -> RESOLUTION_SUBMITTED` and its
    `submitted_by_user_id` is stamped from the caller's `X-User-ID`".  Throughout, PRD SS2.8
    clause 4 holds the posture at `RESTRICTED`: "if the home has at least one compliance
    obligation whose `severity` is `MAJOR` and whose `status` is one of `OPEN`, `PLANNED`,
    `RESOLUTION_SUBMITTED` or `RESOLUTION_REJECTED`, the posture is `RESTRICTED`."

    Design: Corner/state_machines/obligation_reject_reopens_the_cure_cycle_with_incremented_round
    """
    ctx = x.acquired_home(api)
    obligation = x.planned_obligation(
        api,
        ctx.home_id,
        severity="MAJOR",
        planned_resolution_on="2026-09-30",
        description="Unapproved fence height",
    )
    ok(
        api.submit_obligation_resolution(
            obligation["id"],
            f.submit_resolution_payload(evidence_ref="photo-001"),
            x.COMPLIANCE,
        )
    )

    rejected = ok(
        api.review_obligation_resolution(
            obligation["id"],
            f.review_resolution_payload(
                "REJECT", review_note="Photo does not show the fence line"
            ),
            x.DIRECTOR,
        )
    )
    assert_fields(rejected, status=OBLIGATION_RESOLUTION_REJECTED, resolution_round=0)
    assert_absent_or_empty(rejected, "submitted_by_user_id")
    assert_fields(ok(api.get_home(ctx.home_id, x.OPS)), leasing_posture=POSTURE_RESTRICTED)

    replanned = ok(
        api.plan_obligation(
            obligation["id"], f.plan_obligation_payload("2026-10-31"), x.COMPLIANCE
        )
    )
    assert_fields(
        replanned,
        status=OBLIGATION_PLANNED,
        resolution_round=1,
        planned_resolution_on="2026-10-31",
    )

    resubmitted = ok(
        api.submit_obligation_resolution(
            obligation["id"],
            f.submit_resolution_payload(evidence_ref="photo-002"),
            x.COMPLIANCE_2,
        )
    )
    assert_fields(
        resubmitted,
        status=OBLIGATION_RESOLUTION_SUBMITTED,
        submitted_by_user_id="co-2",
        evidence_ref="photo-002",
        resolution_round=1,
    )
    assert_fields(ok(api.get_home(ctx.home_id, x.OPS)), leasing_posture=POSTURE_RESTRICTED)


def test_a_waived_minor_hoa_citation_keeps_its_evidence_and_no_tax_money(api):
    """WAIVE is the second terminal exit, and it never writes the appeal money group.

    PRD SS3.9: "`WAIVE` moves it `RESOLUTION_SUBMITTED` -> `WAIVED` and is permitted only for an
    obligation whose `obligation_type` is `HOA_VIOLATION` and whose `severity` is `MINOR` or
    `MAJOR`".  The money group it must leave alone belongs to the accept-only tax cascade: "When
    the accepted obligation's `obligation_type` is `PROPERTY_TAX_APPEAL`, acceptance runs four
    further hops in order", the first computing `annual_tax_savings_cents` and
    `net_tax_benefit_cents` and the second overwriting the home's `assessed_value_cents`.  On
    creation those fields start at zero -- PRD SS3.9: the obligation "is created in `OPEN` with
    `resolution_round` 0 ... and `settled_value_cents`, `annual_tax_savings_cents`,
    `consultant_fee_cents` and `net_tax_benefit_cents` all 0."

    Design: Corner/state_machines/minor_hoa_obligation_reaches_the_waived_terminal_state
    """
    ctx = x.acquired_home(api)
    obligation = x.planned_obligation(
        api,
        ctx.home_id,
        severity="MINOR",
        planned_resolution_on="2026-09-15",
        description="Trash bin left at curb",
    )
    ok(
        api.submit_obligation_resolution(
            obligation["id"],
            f.submit_resolution_payload(evidence_ref="hoa-letter-77"),
            x.COMPLIANCE,
        )
    )

    waived = ok(
        api.review_obligation_resolution(
            obligation["id"],
            f.review_resolution_payload("WAIVE", review_note="HOA withdrew the citation"),
            x.DIRECTOR,
        )
    )
    assert_fields(
        waived,
        status=OBLIGATION_WAIVED,
        evidence_ref="hoa-letter-77",
        resolution_round=0,
    )
    assert_money_group(
        waived,
        settled_value_cents=0,
        annual_tax_savings_cents=0,
        consultant_fee_cents=0,
        net_tax_benefit_cents=0,
    )

    home = ok(api.get_home(ctx.home_id, x.OPS))
    assert_money_group(
        home, assessed_value_cents=28000000, property_tax_annual_cents=350000
    )
    assert_fields(home, leasing_posture=POSTURE_RESTRICTED)


def test_the_scope_lock_reports_the_empty_set_first_and_the_asset_state_later(api):
    """Two guards on one call: 422 on the empty project, 409 once the home has moved on.

    PRD SS3.3: "Locking requires the project to be in `SCOPING`, requires at least one work
    order on the project whose `status` is one of `PENDING_DISPATCH`, `DISPATCHED`, `ACCEPTED`,
    `IN_PROGRESS` or `COMPLETED` -- an empty or fully-voided scope set is refused with
    `ERR_PROJECT_SCOPE_EMPTY` -- and requires the home's `asset_status` to be exactly
    `ACQUIRED`, otherwise `ERR_HOME_NOT_ACQUIRED`. A successful lock moves the project `SCOPING
    -> IN_PROGRESS` and stores `turn_started_on`, then cascades in two further hops: the home
    advances `ACQUIRED -> RENOVATING`, which recomputes its `leasing_posture` to `FROZEN`".  PRD
    SS3.3 also permits the second project: "A home whose earlier project already reached
    `RENT_READY` may, however, open a later `TURN` project -- which will then have to satisfy
    the acquired-state check when its scope is locked."  Which of the two guards speaks is fixed
    by PRD SS2.7, where "**Rank 400 -- home not acquired.** `ERR_HOME_NOT_ACQUIRED` (409) on
    project scope-lock" precedes "**Rank 402 -- empty scope set.** `ERR_PROJECT_SCOPE_EMPTY`
    (422) on project scope-lock", and "Evaluation stops at the first violated rule, and only
    that rule's error is reported."

    Design: Corner/state_machines/lock_scope_enforces_empty_scope_then_acquired_home_preconditions
    """
    ctx = x.acquired_home(api)
    project = created(
        api.create_renovation_project(
            f.renovation_project_payload(ctx.home_id, 400000), x.OPS
        )
    )

    failed(
        api.lock_project_scope(project["id"], f.lock_scope_payload("2026-08-05"), x.OPS),
        ERR_PROJECT_SCOPE_EMPTY,
    )
    assert_fields(
        ok(api.get_renovation_project(project["id"], x.OPS)), status=PROJECT_SCOPING
    )
    assert_home_dimensions(ok(api.get_home(ctx.home_id, x.OPS)), ASSET_ACQUIRED, OCC_VACANT)

    order = created(
        api.create_work_order(
            f.work_order_payload(ctx.home_id, ctx.paint_id, project_id=project["id"]), x.OPS
        )
    )
    locked = ok(
        api.lock_project_scope(project["id"], f.lock_scope_payload("2026-08-05"), x.OPS)
    )
    assert_fields(locked, status=PROJECT_IN_PROGRESS, turn_started_on="2026-08-05")
    assert_home_dimensions(
        ok(api.get_home(ctx.home_id, x.OPS)), ASSET_RENOVATING, OCC_VACANT, POSTURE_FROZEN
    )

    ok(api.dispatch_work_order(order["id"], {}, x.OPS))
    x.set_clock(api, CLOCK_SEP_06)
    ok(
        api.complete_work_order(
            order["id"], f.complete_work_order_payload(300000, "2026-09-06"), x.OPS
        )
    )
    assert_fields(
        ok(api.get_renovation_project(project["id"], x.OPS)), status=PROJECT_RENT_READY
    )
    assert_home_dimensions(ok(api.get_home(ctx.home_id, x.OPS)), ASSET_STABILIZED, OCC_VACANT)

    turn = created(
        api.create_renovation_project(
            f.turn_project_payload(ctx.home_id, 200000), x.OPS
        )
    )
    body = failed(
        api.lock_project_scope(turn["id"], f.lock_scope_payload("2026-09-07"), x.OPS),
        ERR_HOME_NOT_ACQUIRED,
    )
    assert body.get("error_id") != ERR_PROJECT_SCOPE_EMPTY
    assert_fields(ok(api.get_renovation_project(turn["id"], x.OPS)), status=PROJECT_SCOPING)
    assert_home_dimensions(ok(api.get_home(ctx.home_id, x.OPS)), ASSET_STABILIZED, OCC_VACANT)
