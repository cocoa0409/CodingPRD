"""Savings periods: provisional vs finalized variants, the bucket identity,
calendar-month scoping, key uniqueness, and state gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_savings_period,
    drive_hit_resolution,
    finalize_period,
    get_success_data,
    setup_provider_with_active_edit,
    setup_savings_scenario,
    validate_error,
)

ADMIN = TEST_USERS["plan_admin_headers"]


def test_savings_provisional_vs_finalized(api):
    """PRD §3.9: "The `provisional_savings_cents` is the optimistic pipeline
    view: the sum of `attributed_savings_cents` over every hit created in the
    period month, regardless of status, counting still-unresolved `FIRED` hits
    at full attributed value and ignoring releases."
    PRD §3.9: "The `finalized_savings_cents` is the audited view: over the
    hits resolved within the period month in `CONFIRMED`, `OVERRIDDEN`,
    `RELEASED_FALSE_POSITIVE`, or `SUPERSEDED`, the sum of each hit's
    attributed savings net of its `released_cents` — `FIRED` hits are excluded
    entirely, so the identical hit population yields a smaller finalized
    number whenever anything is still pending or has been released."

    Design: Difficulty/dual_variant_calc/savings_provisional_vs_finalized
    """
    sc = setup_savings_scenario(npi="NPI-S1", edit_code="SAV-DENY")
    finalized = finalize_period(sc["period"]["id"])
    # Population: A CONFIRMED 50000; B FIRED 70000; C OVERRIDDEN (60000-20000).
    assert finalized["provisional_savings_cents"] == 180000
    assert finalized["finalized_savings_cents"] == 90000
    assert finalized["provisional_savings_cents"] != \
        finalized["finalized_savings_cents"], (
            "the identical hit population yields two different views"
        )


def test_savings_pending_and_reversed(api):
    """PRD §3.9: "The `pending_pipeline_cents` captures the in-flight
    remainder: the attributed sum over hits created in the period that are
    still `FIRED` at finalization time."
    PRD §3.9: "The `reversed_cents` captures give-backs: the sum of
    `released_cents` over hits resolved within the period month in
    `OVERRIDDEN`, `RELEASED_FALSE_POSITIVE`, or `SUPERSEDED`."

    Design: Difficulty/dual_variant_calc/savings_provisional_vs_finalized
    """
    sc = setup_savings_scenario(npi="NPI-S1B", edit_code="SAV-DENY-2")
    finalized = finalize_period(sc["period"]["id"])
    assert finalized["pending_pipeline_cents"] == 70000
    assert finalized["reversed_cents"] == 20000


def test_savings_bucket_identity_values(api):
    """PRD §3.9: "The `provisional_savings_cents` is the optimistic pipeline
    view: the sum of `attributed_savings_cents` over every hit created in the
    period month, regardless of status"
    PRD §3.9: "The `finalized_savings_cents` is the audited view: over the
    hits resolved within the period month in `CONFIRMED`, `OVERRIDDEN`,
    `RELEASED_FALSE_POSITIVE`, or `SUPERSEDED`, the sum of each hit's
    attributed savings net of its `released_cents`"
    PRD §3.9: "The `pending_pipeline_cents` captures the in-flight remainder:
    the attributed sum over hits created in the period that are still `FIRED`
    at finalization time. The `reversed_cents` captures give-backs: the sum of
    `released_cents` over hits resolved within the period month in
    `OVERRIDDEN`, `RELEASED_FALSE_POSITIVE`, or `SUPERSEDED`."

    Design: Difficulty/compensating_invariant/savings_period_bucket_identity
    """
    sc = setup_savings_scenario(npi="NPI-S9", edit_code="BUCKET-DENY")
    finalized = finalize_period(sc["period"]["id"])
    assert finalized["provisional_savings_cents"] == 180000
    assert finalized["finalized_savings_cents"] == 90000
    assert finalized["pending_pipeline_cents"] == 70000
    assert finalized["reversed_cents"] == 20000


def test_savings_bucket_identity_holds(api):
    """PRD §3.9: "Because every hit's attributed amount is, by construction,
    its net amount plus its released amount, the provisional figure equals
    finalized plus pending plus reversed whenever all of the period's hits
    resolved inside the period — the reconciliation identity auditors check
    first."

    Design: Difficulty/compensating_invariant/savings_period_bucket_identity
    """
    sc = setup_savings_scenario(npi="NPI-S9B", edit_code="BUCKET-DENY-2")
    finalized = finalize_period(sc["period"]["id"])
    assert finalized["finalized_savings_cents"] + \
        finalized["pending_pipeline_cents"] + finalized["reversed_cents"] == \
        finalized["provisional_savings_cents"], (
            "confirm/pend/partial-release bucket moves conserve the total"
        )


def test_savings_period_scopes_to_calendar_month(api):
    """PRD §3.9: "Finalization computes four figures from the month's hits and
    stamps `finalized_at`"
    PRD §3.9: "The `provisional_savings_cents` is the optimistic pipeline
    view: the sum of `attributed_savings_cents` over every hit created in the
    period month, regardless of status"
    PRD §3.9: "The `finalized_savings_cents` is the audited view: over the
    hits resolved within the period month in `CONFIRMED`, `OVERRIDDEN`,
    `RELEASED_FALSE_POSITIVE`, or `SUPERSEDED`"

    Design: Corner/calculations/savings_period_scopes_to_calendar_month
    """
    provider, _rule, _version = setup_provider_with_active_edit(
        npi="NPI-M1", edit_code="MONTH-DENY")
    # Every hit is created and resolved under the default 2026-08 clock.
    drive_hit_resolution(provider["id"], 40000, "MM1", "M-MM1", "uphold")

    period = create_savings_period("2026-09")
    finalized = finalize_period(period["id"])
    assert finalized["provisional_savings_cents"] == 0
    assert finalized["finalized_savings_cents"] == 0
    assert finalized["pending_pipeline_cents"] == 0
    assert finalized["reversed_cents"] == 0, (
        "August hits are excluded from the September period"
    )


def test_duplicate_period_key_rejected(api):
    """PRD §3.9: "A `PlanAdmin` opens a savings period by supplying its
    `period_key`, a calendar-month string in YYYY-MM format that must be
    unique across periods — a duplicate is rejected with
    `ERR_DUPLICATE_PERIOD_KEY` (HTTP 409)."

    Design: Corner/validations/duplicate_period_key_rejected
    """
    period = create_savings_period("2026-08")
    resp = api.create_savings_period({"period_key": "2026-08"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERIOD_KEY,
                   expected_status=409)
    still = get_success_data(api.get_savings_period(period["id"], ADMIN))
    assert still["status"] == "OPEN"


def test_period_finalize_from_open_rejected(api):
    """PRD §3.9: "beginning reconciliation requires `OPEN` and finalizing
    requires `RECONCILING`, with out-of-state attempts rejected as
    `ERR_PERIOD_NOT_FINALIZABLE` (HTTP 409)."

    Design: Corner/validations/period_finalize_from_open_rejected
    """
    period = create_savings_period("2026-08")
    resp = api.finalize_savings_period(period["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_FINALIZABLE,
                   expected_status=409)
    still = get_success_data(api.get_savings_period(period["id"], ADMIN))
    assert still["status"] == "OPEN"
