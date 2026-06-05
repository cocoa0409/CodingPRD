"""Corner Coverage — cross_cutting_complexity_layers + consistency_model.

OCC stale-version on recertify and finalize; grant.units_finalized reconciliation
after a finalize; visit list pagination with status filter; immediate consistency.

Two corner stubs (cascading_side_effects_already_covered_by_difficulty and
dual_variant_calc_already_covered_by_difficulty) are excluded_because: in the
corner index — their assertions are owned by the §1.8 difficulty instances
(test_04_difficulty_transitive_cascade and test_01_difficulty_dual_variant_calc
respectively).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    set_clock,
    setup_poc_with_grant,
    setup_recert_due_poc,
    schedule_visit,
    complete_visit,
    finalize_visit,
    recertify_plan_payload,
    finalize_visit_payload,
    make_therapist_headers,
    TEST_USERS,
)


def test_occ_stale_plan_version_on_recertify(api):
    """PRD §2.6: "A recertification request must include `expected_plan_of_care_version`
    in its body. The value must match the current `version` of the target `PlanOfCare`
    exactly. If another writer (typically a visit-finalize on the same plan, which
    silently advances `version` through the cumulative-billed cascade) has bumped the
    plan's `version` since the client last read it, the recertification is rejected
    with `ERR_STALE_PLAN_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_version_on_recertify
    """
    ctx = setup_recert_due_poc(
        certified_start_date="2026-06-01",
        certified_end_date="2026-06-08",
    )
    th = ctx["therapist"]["id"]
    stale_v = ctx["poc"]["version"] - 1  # explicitly stale (one less than current)
    res = api.recertify_plan_of_care(
        ctx["poc"]["id"],
        recertify_plan_payload(
            expected_plan_of_care_version=stale_v,
            certified_start_date="2026-06-01",
            certified_end_date="2026-07-31",
        ),
        make_therapist_headers(th),
    )
    validate_error(res, "ERR_STALE_PLAN_VERSION", expected_status=412)


def test_occ_stale_plan_version_on_visit_finalize(api):
    """PRD §2.6: "A visit-finalize request must include `expected_plan_of_care_version`
    in its body, where the value is the client's last-observed `version` of the parent
    `PlanOfCare` (reached through the visit's `authorization_grant_id` → grant's
    `plan_of_care_id`). When another finalize, or a recertification, has already
    advanced `PlanOfCare.version` since the client read it, this finalize is rejected
    with `ERR_STALE_PLAN_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_version_on_visit_finalize
    """
    ctx = setup_poc_with_grant(
        insurance_type="MEDICARE", medicare_enrolled=True,
        total_units_granted=20,
    )
    th = ctx["therapist"]["id"]
    gid = ctx["grant"]["id"]
    poc_id = ctx["poc"]["id"]
    # Two completed visits ready to finalize.
    vA = schedule_visit(gid, th, "2026-06-02T09:00:00Z", "2026-06-02T09:30:00Z",
                        planned_minutes=30, cpt_code="CPT_97110_THER_EX")
    complete_visit(vA["id"], th, actual_minutes=30)
    vB = schedule_visit(gid, th, "2026-06-03T09:00:00Z", "2026-06-03T09:30:00Z",
                        planned_minutes=30, cpt_code="CPT_97110_THER_EX")
    complete_visit(vB["id"], th, actual_minutes=30)
    # Capture stale version, then finalize vB (which bumps POC.version).
    stale_v = get_success_data(
        api.get_plan_of_care(poc_id, TEST_USERS["billing_clerk_headers"])
    )["version"]
    finalize_visit(vB["id"], poc_id)
    # Now finalize vA with the stale version — should be ERR_STALE_PLAN_VERSION.
    res = api.finalize_visit(
        vA["id"],
        finalize_visit_payload(expected_plan_of_care_version=stale_v),
        TEST_USERS["billing_clerk_headers"],
    )
    validate_error(res, "ERR_STALE_PLAN_VERSION", expected_status=412)


def test_derived_field_reconciliation_grant_units_finalized(api):
    """PRD §3.5: "The grant's `units_finalized` is recomputed by re-summing
    `billable_units` over visits in `FINALIZED` status, ordered by `created_at` then
    `id`."
    PRD §3.4: "`units_finalized` is the simpler companion: a running sum, ordered the
    same way, of `billable_units` over visits whose `status` is `FINALIZED`."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_grant_units_finalized
    """
    ctx = setup_poc_with_grant(
        insurance_type="MEDICARE", medicare_enrolled=True,
        total_units_granted=10,
    )
    th = ctx["therapist"]["id"]
    v = schedule_visit(
        ctx["grant"]["id"], th,
        "2026-06-02T09:00:00Z", "2026-06-02T09:30:00Z",
        planned_minutes=30, cpt_code="CPT_97110_THER_EX",
    )
    complete_visit(v["id"], th, actual_minutes=30)
    finalize_visit(v["id"], ctx["poc"]["id"])
    g = validate_success(
        api.get_authorization_grant(ctx["grant"]["id"], TEST_USERS["billing_clerk_headers"]),
        200,
    )
    # 30min → billable_units=2 → units_finalized=2.
    assert g["units_finalized"] == 2
    assert g["units_consumed"] == 2


def test_pagination_with_filtering_visits_status_filter(api):
    """PRD §2.3: "The `limit` parameter sets the maximum page size; when omitted it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter
    sets the number of items to skip and defaults to 0."
    PRD §2.3: "Each list response includes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/cross_cutting_complexity_layers/pagination_with_filtering_visits_status_filter
    """
    ctx = setup_poc_with_grant(insurance_type="COMMERCIAL", total_units_granted=20)
    th = ctx["therapist"]["id"]
    gid = ctx["grant"]["id"]
    for date in ("2026-06-02", "2026-06-03", "2026-06-04"):
        schedule_visit(gid, th, f"{date}T09:00:00Z", f"{date}T09:30:00Z",
                       planned_minutes=30, cpt_code="CPT_97110_THER_EX")
    data, meta = validate_paginated(
        api.list_visits(
            TEST_USERS["billing_clerk_headers"],
            params={"authorization_grant_id": gid, "status": "SCHEDULED", "limit": 2},
        )
    )
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2


# ─── Section: consistency_model ─────────────────────────────────


def test_immediate_consistency_visit_finalize_updates_visible_in_same_response(api):
    """PRD §3.5: "Finalization then cascades up the aggregate. The grant's
    `units_finalized` is recomputed by re-summing `billable_units` over visits in
    `FINALIZED` status, ordered by `created_at` then `id`. The plan's
    `cumulative_billed_cents` is refreshed by summing `billed_cents` over every
    `FINALIZED` visit reachable through any of the plan's grants, again ordered by
    `created_at` then `id` for determinism. Finally, the plan's `capped_status` is
    re-evaluated against the refreshed `cumulative_billed_cents` per the three-bucket
    rule in §2.7."

    Design: Corner/consistency_model/immediate_consistency_visit_finalize_updates_visible_in_same_response
    """
    ctx = setup_poc_with_grant(
        insurance_type="MEDICARE", medicare_enrolled=True,
        total_units_granted=10,
    )
    th = ctx["therapist"]["id"]
    v = schedule_visit(
        ctx["grant"]["id"], th,
        "2026-06-02T09:00:00Z", "2026-06-02T09:30:00Z",
        planned_minutes=30, cpt_code="CPT_97110_THER_EX",
    )
    complete_visit(v["id"], th, actual_minutes=30)
    finalized = finalize_visit(v["id"], ctx["poc"]["id"])
    # Visit.billed_cents = 30 min → 2 billable units → 3200 + 1600 = 4800¢.
    assert finalized["status"] == "FINALIZED"
    assert finalized["billed_cents"] == 4800
    # POC's cumulative_billed_cents and capped_status must be visible immediately
    # after the finalize response — read via GET.
    poc = validate_success(
        api.get_plan_of_care(ctx["poc"]["id"], TEST_USERS["billing_clerk_headers"]),
        200,
    )
    assert poc["cumulative_billed_cents"] == 4800
    assert poc["capped_status"] == "UNDER_CAP"
