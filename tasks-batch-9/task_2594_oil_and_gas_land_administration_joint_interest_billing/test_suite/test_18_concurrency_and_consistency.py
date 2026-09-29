"""Version expectations on the two guarded writes, ledger reversal, and read-your-write."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures

CLOCK = "2026-08-10T00:00:00Z"


def _bare_well(api, **overrides):
    return validate_success(
        api.create_well(
            factories.create_well_payload(omit_fields=["spud_date"], **overrides),
            fixtures.LAND_ADMIN,
        ),
        201,
    )


def _owner(api, name, email, bond):
    return validate_success(
        api.create_interest_owner(
            factories.create_interest_owner_payload(
                owner_name=name, contact_email=email, bond_posted_cents=bond
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )


def _book_unpaid_june_costs(api, well_id):
    return [
        fixtures.book_cost(
            api, well_id, "COMPLETION", "CAPITAL", 2_000_000, "2026-06-05"
        ),
        fixtures.book_cost(api, well_id, "COMPLETION", "CAPITAL", 500_000, "2026-06-07"),
        fixtures.book_cost(
            api, well_id, "LEASE_OPERATING", "OPERATING", 300_000, "2026-06-09"
        ),
    ]


def test_a_second_division_order_row_built_on_a_stale_well_reading_is_refused(api):
    """Every recorded position bumps the well, so the second writer must have re-read it.

    Recording a working-interest position on a well requires `expected_well_version` as a mandatory, non-optional input field carrying the client's last observed `version` of that well. If the supplied value does not equal the well's current `version`, the request is rejected with `ERR_STALE_WELL_VERSION` (HTTP 412).

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_well_version_on_interest_create_returns_412
    """
    fixtures.set_clock(api, CLOCK)
    well = _bare_well(api)
    operator = _owner(api, "Operator Energy LLC", "operator@example.com", 50_000_000)
    partner_a = _owner(api, "Delta Partners LP", "delta@example.com", 10_000_000)
    observed_version = fixtures.well_version(api, well["id"])
    validate_success(
        api.create_well_interest(
            well["id"],
            factories.create_well_interest_payload(
                operator["id"],
                0.5,
                0.4125,
                "2026-01-01",
                observed_version,
                is_operator=True,
                preferential_right=True,
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )

    validate_error(
        api.create_well_interest(
            well["id"],
            factories.create_well_interest_payload(
                partner_a["id"], 0.3, 0.24, "2026-01-01", observed_version
            ),
            fixtures.LAND_ADMIN,
        ),
        "ERR_STALE_WELL_VERSION",
        412,
    )

    _, meta = validate_paginated(
        api.list_well_interests(
            fixtures.LAND_ADMIN, params={"well_id": well["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 1

    midway = validate_success(api.get_well(well["id"], fixtures.LAND_ADMIN), 200)
    assert midway["consent_working_interest_pct"] == 0.500000

    validate_success(
        api.create_well_interest(
            well["id"],
            factories.create_well_interest_payload(
                partner_a["id"], 0.3, 0.24, "2026-01-01", midway["version"]
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    _, final_meta = validate_paginated(
        api.list_well_interests(
            fixtures.LAND_ADMIN, params={"well_id": well["id"], "limit": 100}
        )
    )
    assert final_meta["total_count"] == 2


def test_a_revision_built_on_the_draft_reading_of_an_issued_bill_is_refused(api):
    """Two revisions off one reading would reverse the same charge twice.

    Revising a JIB statement requires `expected_jib_statement_version` as a mandatory, non-optional input field carrying the client's last observed `version` of the statement being revised. If the supplied value does not equal that statement's current `version`, the request is rejected with `ERR_STALE_STATEMENT_VERSION` (HTTP 412).
    A revision supersedes the statement it targets and reverses that statement's contribution to the well's billed-to-date ledger; two revisions built from the same observed version would each supersede the same statement and reverse the same amount twice, so the stale-version check makes the second one fail deterministically.

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_statement_version_on_revision_returns_412
    """
    context = fixtures.setup_standard_june_statement(api, clock=CLOCK)
    draft = validate_success(
        api.get_jib_statement(context["statement_id"], fixtures.JIB_ACCOUNTANT), 200
    )
    draft_version = draft["version"]
    fixtures.issue_statement(api, context["statement_id"])

    validate_error(
        api.revise_jib_statement(
            context["statement_id"],
            factories.statement_revision_payload(
                "JIB-2026-06-R1", draft_version, cost_basis="CASH"
            ),
            fixtures.JIB_ACCOUNTANT,
        ),
        "ERR_STALE_STATEMENT_VERSION",
        412,
    )

    statement = validate_success(
        api.get_jib_statement(context["statement_id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert statement["statement_status"] == "ISSUED"

    rows, meta = validate_paginated(
        api.list_jib_statements(
            fixtures.JIB_ACCOUNTANT,
            params={"well_id": context["well_id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 1
    for row in rows:
        assert row["superseded_statement_id"] is None

    well = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert well["billed_to_date_cents"] == 2_934_000


def test_voiding_an_issued_bill_takes_it_off_the_ledger_and_frees_its_period(api):
    """A bill raised over the wrong period has to be withdrawn without leaving a replacement.

    A void, also by a `JointInterestAccountant`, carries `void_reason` and requires `statement_status` of `DRAFT` or `ISSUED`, else `ERR_STATEMENT_NOT_VOIDABLE` with status 409. It sets `statement_status` to `VOID` and applies the same ledger reversal as a revision when the statement was `ISSUED`, and none when it was `DRAFT` — but it creates **no** superseding statement.
    The voided statement's line items are retained for audit and excluded from every balance, and because void statements are excluded from the period-overlap test, the billing period is freed for a fresh draft.

    Design: Corner/cross_cutting_complexity_layers/voiding_an_issued_statement_returns_the_well_ledger_to_zero
    """
    context = fixtures.setup_issued_june_statement(api, clock=CLOCK)

    voided = validate_success(
        api.void_jib_statement(
            context["statement_id"],
            fixtures.JIB_ACCOUNTANT,
            factories.statement_void_payload("Issued against the wrong billing period"),
        ),
        200,
    )

    assert voided["statement_status"] == "VOID"
    assert voided["total_billed_cents"] == 2_934_000

    well = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert well["billed_to_date_cents"] == 0

    replacement = fixtures.open_statement(
        api, context["well_id"], statement_number="JIB-2026-06B"
    )
    reissued = validate_success(
        api.issue_jib_statement(replacement["id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert reissued["statement_status"] == "ISSUED"
    assert reissued["total_billed_cents"] == 2_934_000

    final_well = validate_success(
        api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200
    )
    assert final_well["billed_to_date_cents"] == 2_934_000


def test_the_issuance_reply_already_carries_every_figure_it_just_computed(api):
    """No second call is needed to learn what the joint account was just billed.

    On success `issued_at` is taken from the logical clock and `payment_due_date` is set to 30 days after it; `statement_status` becomes `ISSUED`; the statement's `version` increments by 1. The well's `billed_to_date_cents` increases by the statement's `total_billed_cents` and the well's `version` increments by 1.
    Under the `ACCRUAL` basis, an entry qualifies when its `cost_status` is `ACCRUED` or `PAID` and its `incurred_date` falls on or after `billing_period_start` and on or before `billing_period_end`.

    Design: Corner/consistency_model/the_issuance_response_already_carries_the_recomputed_totals
    """
    context = fixtures.setup_pooled_producing_well(api, clock=CLOCK)
    _book_unpaid_june_costs(api, context["well_id"])
    statement = fixtures.open_statement(api, context["well_id"])

    issued = validate_success(
        api.issue_jib_statement(statement["id"], fixtures.JIB_ACCOUNTANT), 200
    )

    assert issued["statement_status"] == "ISSUED"
    assert issued["direct_cost_cents"] == 2_800_000
    assert issued["overhead_cents"] == 134_000
    assert issued["total_billed_cents"] == 2_934_000
    assert issued["payment_due_date"] == "2026-09-09"
    assert issued["prepared_by_user_id"] == "u-jib-1"

    well = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert well["billed_to_date_cents"] == 2_934_000

    rows, meta = validate_paginated(
        api.list_jib_statement_line_items(
            statement["id"], fixtures.JIB_ACCOUNTANT, params={"limit": 100}
        )
    )
    assert meta["total_count"] == 3
    assert sum(row["total_billed_cents"] for row in rows) == 2_934_000

    _, accrued_meta = validate_paginated(
        api.list_cost_entries(
            fixtures.JIB_ACCOUNTANT,
            params={
                "well_id": context["well_id"],
                "cost_status": "ACCRUED",
                "limit": 100,
            },
        )
    )
    assert accrued_meta["total_count"] == 3
