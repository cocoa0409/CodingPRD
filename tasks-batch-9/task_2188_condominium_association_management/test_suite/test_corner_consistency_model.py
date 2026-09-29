"""Consistency probes: the writing response already carries the derived state.

Nothing in this service is eventually consistent. A call that ratifies a budget
or applies a payment must have finished every derived write before it answers, so
a read issued immediately afterwards can add nothing and contradict nothing.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers.assertions import (
    assert_allocation_sums_to,
    assert_fields_equal,
    fetch_ledger_entries,
    find_entry,
    read_budget,
    read_unit,
    snapshot_row,
)
from test_helpers.factories import (
    charge_payload,
    payment_payload,
    resale_certificate_payload,
)
from test_helpers.fixtures import (
    add_owner,
    add_unit,
    adopt_budget,
    create_association,
    set_clock,
)
from test_helpers.test_users import MANAGER_HEADERS, TITLE_AGENT_HEADERS

HARBOR_POINT = "Harbor Point Condominium Association"


def test_the_ratify_response_already_carries_the_whole_allocation(api):
    """No second read is needed to learn what the ratification allocated.

    The 13200000-cent budget divides into a 1100000-cent monthly pool that splits
    evenly over two 5000-basis-point units, so both shares are 550000 and no
    remainder cent is awarded. The ratify response must already show `ADOPTED`,
    the stamped `adopted_at`, the derived totals and the fully populated
    `allocation_snapshot`; a body that returns the status while leaving the
    snapshot empty for a later read to fill in is the failure mode. The immediate
    re-read agrees field for field, and both units already show their share.

    PRD 3.2: "On `NOTICED → ADOPTED`, the server writes `no_weight_bp` and stamps
    `adopted_at` with the logical clock, then runs a five-hop cascade."
    PRD 3.2: "Hop one computes the allocation snapshot and writes every unit's
    `monthly_assessment_cents`, advancing each `Unit.version` by 1."
    PRD 3.2: "Each unit's `monthly_assessment_cents` receives its final share, and
    the budget's `allocation_snapshot` freezes one object per participant carrying
    `unit_id`, `interest_bp`, `monthly_cents` holding the final share, and
    `remainder_cent_awarded`, a boolean that is true exactly when the final share
    differs from the per-line rounded value computed in the third step."
    PRD 3.2: "The cycle is genuinely cyclic: a board may push a budget back to
    `DRAFT` from `PROPOSED`, from `NOTICED`, or from `REJECTED`, and each return
    increments `revision_round`, which starts at 0."

    Design: Corner/consistency_model/ratify_response_already_carries_the_allocation_no_second_read_required
    """
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    add_owner(
        ctx,
        "d1",
        full_name="Dana Reed",
        email="dana@example.test",
        board_role="DIRECTOR",
        is_seated=True,
    )
    add_unit(ctx, "101", "o1", 5_000, heated_sqft=1_000)
    add_unit(ctx, "102", "o1", 5_000, heated_sqft=1_000)

    ratified = adopt_budget(
        ctx,
        meeting_start="2026-09-01T10:00:00Z",
        meeting_end="2026-09-01T12:00:00Z",
        attending=("d1",),
    )
    assert_fields_equal(
        ratified,
        status="ADOPTED",
        adopted_at="2026-09-01T10:00:00Z",
        assessment_total_cents=13_200_000,
        monthly_assessable_cents=1_100_000,
        revision_round=0,
        no_weight_bp=0,
    )

    snapshot = ratified["allocation_snapshot"]
    assert len(snapshot) == 2
    assert_allocation_sums_to(snapshot, "monthly_cents", 1_100_000)
    for label in ("101", "102"):
        row = snapshot_row(snapshot, ctx.units[label])
        assert row["interest_bp"] == 5_000
        assert row["monthly_cents"] == 550_000
        assert row["remainder_cent_awarded"] is False

    reread = read_budget(api, ratified["id"], MANAGER_HEADERS)
    assert_fields_equal(
        reread,
        status="ADOPTED",
        adopted_at="2026-09-01T10:00:00Z",
        assessment_total_cents=13_200_000,
        monthly_assessable_cents=1_100_000,
        revision_round=0,
    )
    assert reread["allocation_snapshot"] == snapshot
    for label in ("101", "102"):
        assert (
            read_unit(api, ctx.units[label], MANAGER_HEADERS)[
                "monthly_assessment_cents"
            ]
            == 550_000
        )


def test_the_payment_re_derives_the_lien_posture_before_it_answers(api):
    """The ladder runs inside the payment, not on some later sweep.

    A 200000-cent collection cost due 2026-04-01 puts the unit in `LIEN_FILED` at
    the epoch clock -- 122 days aged, above the 180000 threshold -- with voting
    barred. The owner's payoff must leave the unit `CURRENT` with a null
    `lien_recorded_at` and voting restored on the very next read; a design that
    keeps the unit reading `LIEN_FILED` until the next billing run fails. The same
    write also advances `Unit.version`, so the token captured before the payment is
    already stale for a certificate request.

    PRD 3.1: "The stored `PAYMENT` row records `amount_cents` as the arithmetic
    negation of the supplied figure, because a payment is a credit against the
    unit."
    PRD 3.1: "On every ledger mutation and on every billing run the server walks
    the following ladder from the top and takes the **first** matching rule, so
    escalation and de-escalation share one evaluation."
    PRD 3.1: "Rule 1: if `balance_due_cents` is less than or equal to 0, the
    posture is `CURRENT`."
    PRD 3.1: "Falling back from `LIEN_FILED → LATE_NOTICE` (which happens when the
    balance is still positive but below `lien_threshold_cents` while
    `oldest_unpaid_age_days` is at least 30) or from `LIEN_FILED → CURRENT` (when
    the balance reaches zero or below) clears `lien_recorded_at` to null, sets
    `voting_eligible` back to true, and triggers the same `BALLOTING`
    eligible-weight recomputation."
    PRD 3.1: "Separately, an owner statement capability returns the unit's
    per-bucket open balances together with its `oldest_unpaid_age_days`; because
    it is owner-scoped, a `UnitOwner` calling it for a unit they do not own is
    refused with `ERR_NOT_UNIT_OWNER`."
    PRD 2.6: "A mismatch against the unit's current `version` is rejected with
    `ERR_STALE_UNIT_VERSION` (HTTP 412)."

    Design: Corner/consistency_model/payment_response_already_shows_the_re_derived_delinquency_posture
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    ctx = create_association(api, legal_name=HARBOR_POINT)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    unit_id = add_unit(ctx, "101", "o1", 10_000, heated_sqft=1_000)
    get_success_data(
        api.create_charge(
            unit_id,
            charge_payload(
                entry_type="COLLECTION_COST",
                amount_cents=200_000,
                due_on="2026-04-01T00:00:00Z",
                effective_period="2026-04",
                memo="collection counsel",
            ),
            MANAGER_HEADERS,
        )
    )
    lienned = read_unit(api, unit_id, MANAGER_HEADERS)
    assert_fields_equal(
        lienned,
        balance_due_cents=200_000,
        oldest_unpaid_age_days=122,
        delinquency_stage="LIEN_FILED",
        voting_eligible=False,
        lien_recorded_at="2026-08-01T00:00:00Z",
    )
    stale_version = lienned["version"]

    validate_success(
        api.create_payment(
            unit_id,
            payment_payload(200_000, effective_period="2026-08", memo="payoff"),
            ctx.owner("o1"),
        ),
        201,
    )

    settled = read_unit(api, unit_id, MANAGER_HEADERS)
    assert_fields_equal(
        settled,
        balance_due_cents=0,
        credit_balance_cents=0,
        oldest_unpaid_age_days=0,
        delinquency_stage="CURRENT",
        voting_eligible=True,
        lien_recorded_at=None,
    )
    assert settled["version"] == stale_version + 1

    statement = validate_success(api.get_unit_statement(unit_id, ctx.owner("o1")))
    assert statement["oldest_unpaid_age_days"] == 0

    rows = fetch_ledger_entries(api, MANAGER_HEADERS, unit_id=unit_id)
    assert len(rows) == 2
    charge = find_entry(rows, entry_type="COLLECTION_COST")
    assert charge["amount_cents"] == 200_000
    assert charge["applied_cents"] == 200_000
    assert charge["status"] == "POSTED"
    payment = find_entry(rows, entry_type="PAYMENT")
    assert payment["amount_cents"] == -200_000
    assert payment["unapplied_cents"] == 0

    validate_error(
        api.request_resale_certificate(
            unit_id,
            resale_certificate_payload(
                "TA-0001", stale_version, closing_date="2026-09-15T00:00:00Z"
            ),
            TITLE_AGENT_HEADERS,
        ),
        "ERR_STALE_UNIT_VERSION",
        412,
    )
