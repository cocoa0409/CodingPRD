"""Endpoint shapes: a partial update, a read-only projection, an operations counter, a toggle."""

from test_helpers import *  # noqa: F401,F403


def test_patching_a_draft_agreement_touches_only_the_supplied_fields(api, ops_headers):
    """PRD §3.3: "While an agreement is still `DRAFT`, the manager may amend its
    `exclusivity_mode`, `minimum_guarantee_cents`, `required_advance_cents`, `term_end_date` and
    `central_licensing_flag`." And: "Amendment is permitted only in `DRAFT` — attempting it in
    any other contract status yields `ERR_INVALID_STATE` — it re-runs the exclusivity,
    guarantee-floor and advance-floor rules, and it increments the agreement's `version` by 1."

    Design: Corner/endpoints/patch_draft_agreement_updates_only_the_editable_fields
    """
    category = create_jersey_category()
    licensee = create_active_licensee(legal_name="Inglewood Textiles")
    agreement = create_draft_agreement(
        licensee["id"],
        category["id"],
        minimum_guarantee_cents=1000000,
        required_advance_cents=250000,
        central_licensing_flag=False,
    )
    assert agreement["version"] == 1

    amended = validate_success(
        api.patch_agreement(
            agreement["id"],
            {
                "minimum_guarantee_cents": 1200000,
                "required_advance_cents": 300000,
                "term_end_date": "2027-06-30",
            },
            ops_headers,
        ),
        200,
    )

    assert amended["minimum_guarantee_cents"] == 1200000
    # 300 000 is exactly the advance floor of the new guarantee, which passes.
    assert amended["required_advance_cents"] == 300000
    assert amended["term_end_date"] == "2027-06-30"
    # Fields the request left out keep their stored values.
    assert amended["exclusivity_mode"] == "NON_EXCLUSIVE"
    assert amended["central_licensing_flag"] is False
    assert amended["term_start_date"] == "2026-01-01"
    assert amended["contract_status"] == "DRAFT"
    assert amended["version"] == 2


def test_the_risk_index_read_defaults_its_parameters_and_stores_nothing(api, ops_headers):
    """PRD §3.2: "A read-only endpoint computes either variant on demand without storing
    anything: `variant` is optional and defaults to `ROLLING_MONITOR`, `as_of_quarter` is
    optional and defaults to the quarter of the logical clock, and the response reports
    `licensee_id`, `as_of_quarter`, `variant`, the resulting `index`, the `posture_band` that
    index falls into, the `factor_count` of contributing rows, and `raw_weighted_total_milli`,
    which is the unrounded weighted sum multiplied by 1000 and truncated so that the single
    rounding step is externally observable."

    Design: Corner/endpoints/risk_index_read_computes_without_storing
    """
    licensee = create_active_licensee(legal_name="Juniper Team Sports")
    assert licensee["version"] == 2

    projection = validate_success(
        api.get_licensee_risk_index(licensee["id"], ops_headers), 200
    )
    assert_risk_index_projection(projection)

    assert projection["licensee_id"] == licensee["id"]
    assert projection["variant"] == "ROLLING_MONITOR"
    assert projection["as_of_quarter"] == "2026Q3"
    assert projection["index"] == 0
    assert projection["factor_count"] == 0
    assert projection["raw_weighted_total_milli"] == 0
    assert projection["posture_band"] == "CLEAR"

    stored = get_licensee(licensee["id"])
    assert stored["compliance_risk_index"] == 0
    # The read left the row exactly as activation had left it.
    assert stored["version"] == 2


def test_closing_a_quarter_reports_counters_and_refuses_a_repeat(api, finance_headers):
    """PRD §3.9: "The response reports the `as_of_quarter` it processed together with five
    counters: `agreements_expired`, `shortfalls_assessed`, `risk_indexes_recomputed`,
    `postures_changed`, `submissions_held` and `submissions_released`."

    Design: Corner/endpoints/quarter_close_reports_counters_and_refuses_a_second_close
    """
    context = setup_active_agreement(
        term_start_date="2026-01-01", term_end_date="2027-12-31", central_licensing_flag=False
    )

    counters = validate_success(
        api.quarter_close(quarter_close_payload("2026Q3"), finance_headers), 200
    )
    assert counters["as_of_quarter"] == "2026Q3"
    # The term runs past the closing quarter, so nothing expires.
    assert counters["agreements_expired"] == 0
    assert counters["shortfalls_assessed"] == 1
    assert counters["risk_indexes_recomputed"] == 1
    assert counters["postures_changed"] == 0
    assert counters["submissions_held"] == 0
    assert counters["submissions_released"] == 0

    agreement = get_agreement(context["agreement"]["id"])
    assert agreement["contract_status"] == "ACTIVE"
    assert agreement["compliance_posture"] == "CLEAR"

    repeat = api.quarter_close(quarter_close_payload("2026Q3"), finance_headers)
    validate_error(repeat, ApiErrorId.QUARTER_ALREADY_CLOSED.value, 409)


def test_unlocking_a_run_returns_it_to_open_and_clears_the_lock_stamp(api, finance_headers):
    """PRD §3.9: "Unlocking moves `LOCKED` back to `OPEN` and clears `locked_at` to null, so a
    late acceptance can still be pooled before the money is committed; the cycle between `OPEN`
    and `LOCKED` is unbounded."

    Design: Corner/endpoints/unlock_returns_a_locked_run_to_open_and_clears_locked_at
    """
    run = create_distribution_run("2026Q2")
    assert run["version"] == 1
    locked = lock_run(run["id"])
    assert locked["status"] == "LOCKED"
    assert locked["locked_at"] is not None
    assert locked["version"] == 2

    # Unlocking carries no body at all, and in particular no expected version.
    reopened = validate_success(
        api.unlock_distribution_run(run["id"], None, finance_headers), 200
    )
    assert reopened["status"] == "OPEN"
    assert reopened["locked_at"] is None
    assert reopened["version"] == 3
    assert reopened["distributed_at"] is None
    assert reopened["pool_gross_cents"] == 0

    repeat = api.unlock_distribution_run(run["id"], None, finance_headers)
    validate_error(repeat, ApiErrorId.INVALID_STATE.value, 409)
    assert get_run(run["id"])["version"] == 3
