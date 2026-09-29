"""State-machine behaviour of the colocation application pipeline and the site
amendment's two status axes: the submit branch of PRD §3.4, the disposition and
terminal-state rules of PRD §3.5, the two-stage execution, voiding and
billing-axis rules of PRD §3.7, and the initial state a scheduled compliance
audit takes under PRD §3.9.
"""

from datetime import datetime, timedelta

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_INVALID_APPLICATION_STATE,
    ERR_INVALID_BILLING_STATE,
    ERR_NO_EQUIPMENT_LINES,
)
from test_helpers.assertions import (
    assert_amendment_axes,
    assert_cents,
    assert_common_resource_fields,
    assert_load_units,
    assert_occupied_band,
    assert_tower_capacity,
)
from test_helpers.constants import CLOCK_COLD_START_UTC, STANDARD_REVIEW_DAYS
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    AUDITOR_USER_ID,
    make_tenant_headers,
)


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant of the kind PRD §2.4 renders."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


COLD_START = _instant(CLOCK_COLD_START_UTC)

# One antenna line of five 100 lb units with no wind area mounted at 80 ft.
# PRD §3.4 puts that below the 100-foot tier boundary, so the multiplier is
# 1.00 and the line carries (100 + 30 * 0) * 5 * 1.00 = 500.000 load units.
SINGLE_LINE_500_UNITS = {
    "equipment_type": "ANTENNA",
    "model_code": "SM-100",
    "quantity": 5,
    "unit_weight_lbs": 100,
    "wind_area_sqft": 0,
    "mount_elevation_ft": 80,
}

APP_BAND_100_140 = {
    "requested_elevation_bottom_ft": 100,
    "requested_elevation_top_ft": 140,
    "requested_ground_space_sqft": 300,
}

MLA_NO_EXPEDITED_COMMITMENT = {
    "base_monthly_rent_cents": 200000,
    "escalator_pct": 3.0,
    "renewal_terms_count": 1,
}


def _draft_application_on_open_tower(api, *, mla_overrides=None, application_overrides=None):
    """A tower with no reservations, an ACTIVE master lease and a DRAFT
    application carrying one 500.000-load-unit equipment line."""
    tower = fixtures.new_tower(
        api, rated_capacity_load_units=9000, ground_space_total_sqft=9000
    )
    carrier = fixtures.carrier_with_active_lease(
        api, mla_overrides=mla_overrides or dict(MLA_NO_EXPEDITED_COMMITMENT)
    )
    tenant, mla = carrier["tenant"], carrier["mla"]
    app_payload = dict(APP_BAND_100_140)
    app_payload.update(application_overrides or {})
    application = fixtures.new_application(
        api, tower["id"], mla["id"], tenant["id"], **app_payload
    )
    line = fixtures.add_equipment_line(
        api, application["id"], tenant["id"], **SINGLE_LINE_500_UNITS
    )
    return {
        "tower": tower,
        "tenant": tenant,
        "tenant_headers": make_tenant_headers(tenant["id"]),
        "mla": mla,
        "application": application,
        "line": line,
    }


def _papered_amendment_chain(api, *, with_ground_lease=True):
    """One carrier's application driven to APPROVED and papered into a DRAFT
    site amendment on a 9000-unit tower with 9000 sqft of compound."""
    return fixtures.build_colocation_chain(
        api,
        stage="PAPERED",
        with_ground_lease=with_ground_lease,
        tower_overrides={
            "rated_capacity_load_units": 9000,
            "ground_space_total_sqft": 9000,
        },
        lease_overrides={
            "base_monthly_rent_cents": 300000,
            "escalator_pct": 2.0,
            "term_end_date": "2031-05-31",
            "renewal_option_count": 1,
            "buyout_price_cents": 9000000,
        },
        mla_overrides=dict(MLA_NO_EXPEDITED_COMMITMENT),
        application_overrides=dict(APP_BAND_100_140),
        lines=[dict(SINGLE_LINE_500_UNITS)],
        amendment_overrides={
            "effective_date": "2026-08-01",
            "term_end_date": "2031-05-31",
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "restoration_deposit_cents": 0,
        },
    )


# ─── Scheduling a compliance audit ───────────────────────────────────────────


def test_scheduled_audit_starts_in_scheduled_with_zeroed_totals(api):
    """PRD §3.9: "A scheduled audit starts in `SCHEDULED` with `auditor_user_id`
    set to the acting operator identifier, `finding_count` at 0 and
    `retroactive_billing_total_cents` at 0."

    Design: Corner/state_machines/equipment_audit_initial_state_is_scheduled
    """
    tower = fixtures.new_tower(
        api,
        rated_capacity_load_units=5000,
        max_elevation_ft=200,
        ground_space_total_sqft=5000,
    )

    resp = api.create_equipment_audit(
        factories.equipment_audit_payload(
            tower["id"], audit_date="2026-07-31", basis="INSTALL_DATE_BASIS"
        ),
        AUDITOR_HEADERS,
    )

    audit = validate_success(resp, 201)
    assert_common_resource_fields(audit)
    assert audit["status"] == "SCHEDULED", f"expected SCHEDULED, got {audit['status']}"
    assert audit["finding_count"] == 0, "a fresh audit has recorded no findings"
    assert_cents(
        audit["retroactive_billing_total_cents"], 0, "retroactive_billing_total_cents"
    )
    assert audit["auditor_user_id"] == AUDITOR_USER_ID
    assert audit["basis"] == "INSTALL_DATE_BASIS"


# ─── Submitting an application ───────────────────────────────────────────────


def test_submit_on_open_tower_lands_application_in_structural_review(api):
    """PRD §3.4: "If the posture is `OPEN`, the application moves `SUBMITTED →
    UNDER_STRUCTURAL_REVIEW` and the tower's `open_review_count` is incremented
    by one."

    PRD §3.4 also pins the stamping: "A successful submission moves the
    application `DRAFT → SUBMITTED`, stamps `submitted_at` with the current
    logical clock instant, recomputes `total_load_units` over the application's
    lines, and computes `review_deadline_at`."

    Design: Corner/state_machines/submit_moves_draft_application_into_structural_review
    """
    world = _draft_application_on_open_tower(api)

    resp = api.submit_colocation_application(
        world["application"]["id"], {}, world["tenant_headers"]
    )

    application = validate_success(resp, 200)
    assert application["status"] == "UNDER_STRUCTURAL_REVIEW", (
        f"an OPEN tower admits the submission straight into review, got "
        f"{application['status']}"
    )
    assert _instant(application["submitted_at"]) == COLD_START
    assert _instant(application["review_deadline_at"]) == COLD_START + timedelta(
        days=STANDARD_REVIEW_DAYS
    )
    assert_load_units(application["total_load_units"], 500.0, "total_load_units")
    assert application["sla_breached"] is False

    tower = fixtures.read_tower(api, world["tower"]["id"])
    assert_tower_capacity(
        tower,
        open_review_count=1,
        reserved_load_units=0.0,
        capacity_posture="OPEN",
    )


def test_expedited_submission_uses_the_master_lease_review_commitment(api):
    """PRD §3.4: "The review clock runs a number of days determined by the
    contract: if `expedited_requested` is `true` **and** the master lease's
    `expedited_review_days` is not null, the commitment is that many days; in
    every other case — including an expedited request against a master lease
    that bought no commitment — the standard 45-day review period applies."

    Design: Corner/state_machines/expedited_application_uses_master_lease_review_commitment
    """
    mla_overrides = dict(MLA_NO_EXPEDITED_COMMITMENT)
    mla_overrides.update(
        {"base_monthly_rent_cents": 250000, "escalator_pct": 3.5, "renewal_terms_count": 2}
    )
    mla_overrides["expedited_review_days"] = 15
    world = _draft_application_on_open_tower(
        api,
        mla_overrides=mla_overrides,
        application_overrides={"expedited_requested": True},
    )

    resp = api.submit_colocation_application(
        world["application"]["id"], {}, world["tenant_headers"]
    )

    application = validate_success(resp, 200)
    assert application["status"] == "UNDER_STRUCTURAL_REVIEW"
    assert application["expedited_requested"] is True
    assert _instant(application["review_deadline_at"]) == COLD_START + timedelta(days=15)
    assert _instant(application["review_deadline_at"]) != COLD_START + timedelta(
        days=STANDARD_REVIEW_DAYS
    ), "the bought commitment displaces the standard 45-day period"
    assert application["sla_breached"] is False


def test_second_submit_on_reviewing_application_rejected(api):
    """PRD §2.6: "The target resource is in a state from which the requested
    transition is declared → `ERR_INVALID_APPLICATION_STATE`,
    `ERR_INVALID_AMENDMENT_STATE`, `ERR_INVALID_BILLING_STATE`,
    `ERR_INVALID_PROJECT_STATE`, `ERR_INVALID_LEASE_STATE`,
    `ERR_INVALID_AUDIT_STATE`, `ERR_INVALID_COST_SHARE_STATE` or
    `ERR_INVALID_ANALYSIS_STATE` (409)."

    Submission is declared only as `DRAFT → SUBMITTED`, so a second submit from
    `UNDER_STRUCTURAL_REVIEW` is refused and re-stamps nothing.

    Design: Corner/state_machines/second_submit_on_reviewing_application_rejected
    """
    world = _draft_application_on_open_tower(api)
    app_id = world["application"]["id"]
    fixtures.submit_application(api, app_id, world["tenant"]["id"])

    resp = api.submit_colocation_application(app_id, {}, world["tenant_headers"])

    validate_error(resp, ERR_INVALID_APPLICATION_STATE, 409)

    application = fixtures.read_application(api, app_id)
    assert application["status"] == "UNDER_STRUCTURAL_REVIEW"
    assert application["revision_count"] == 0, "a refused submit is not a revision"
    assert _instant(application["review_deadline_at"]) == COLD_START + timedelta(
        days=STANDARD_REVIEW_DAYS
    ), "no second review deadline is issued"
    assert_tower_capacity(
        fixtures.read_tower(api, world["tower"]["id"]), open_review_count=1
    )


def test_submit_without_equipment_lines_rejected(api):
    """PRD §2.6: "The application has at least one equipment line →
    `ERR_NO_EQUIPMENT_LINES` (422), on application submit and application
    revise."

    Design: Corner/state_machines/submit_without_equipment_lines_rejected
    """
    world = _draft_application_on_open_tower(api)
    app_id = world["application"]["id"]

    deleted = api.delete_equipment_line(world["line"]["id"], world["tenant_headers"])
    assert deleted.status_code == 204, (
        f"removing a line from a DRAFT application returns 204, got "
        f"{deleted.status_code}: {deleted.text}"
    )

    resp = api.submit_colocation_application(app_id, {}, world["tenant_headers"])

    validate_error(resp, ERR_NO_EQUIPMENT_LINES, 422)

    application = fixtures.read_application(api, app_id)
    assert application["status"] == "DRAFT"
    assert_load_units(application["total_load_units"], 0.0, "total_load_units")
    assert application["review_deadline_at"] is None, (
        "a refused submission issues no review deadline"
    )
    assert application["submitted_at"] is None
    assert_tower_capacity(
        fixtures.read_tower(api, world["tower"]["id"]), open_review_count=0
    )


# ─── Disposition and terminal states ─────────────────────────────────────────


def test_approve_from_draft_application_rejected(api):
    """PRD §3.5: "A `PortfolioAdmin` can approve from either of two states —
    `UNDER_STRUCTURAL_REVIEW → APPROVED` or `MODIFICATION_REQUIRED → APPROVED`
    — and the evidence required differs."

    Design: Corner/state_machines/approve_from_draft_application_rejected
    """
    world = _draft_application_on_open_tower(api)
    app_id = world["application"]["id"]

    resp = api.approve_colocation_application(app_id, {}, ADMIN_HEADERS)

    validate_error(resp, ERR_INVALID_APPLICATION_STATE, 409)

    application = fixtures.read_application(api, app_id)
    assert application["status"] == "DRAFT", "an unsubmitted application stays DRAFT"
    assert application["submitted_at"] is None
    assert_tower_capacity(
        fixtures.read_tower(api, world["tower"]["id"]), open_review_count=0
    )


def test_withdrawn_application_cannot_be_resubmitted(api):
    """PRD §3.5: "`REJECTED`, `WITHDRAWN` and `AMENDMENT_ISSUED` are the three
    terminal states of an application."

    PRD §3.5 also pins the counter effect of the withdrawal itself:
    "Withdrawing from `UNDER_STRUCTURAL_REVIEW` decrements `open_review_count`
    by one **and** sets every `ISSUED` or `QUOTED` analysis of the application
    to `SUPERSEDED`; withdrawing from `MODIFICATION_REQUIRED` supersedes those
    analyses but touches no counter; withdrawing from `DRAFT`, `SUBMITTED` or
    `CAPACITY_HOLD` has no side effects at all."

    Design: Corner/state_machines/withdrawn_application_terminal_lockdown_rejects_resubmit
    """
    world = _draft_application_on_open_tower(api)
    app_id = world["application"]["id"]
    tenant_headers = world["tenant_headers"]
    fixtures.submit_application(api, app_id, world["tenant"]["id"])
    withdrawn = validate_success(
        api.withdraw_colocation_application(app_id, {}, tenant_headers), 200
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert_tower_capacity(
        fixtures.read_tower(api, world["tower"]["id"]), open_review_count=0
    )

    resp = api.submit_colocation_application(app_id, {}, tenant_headers)

    validate_error(resp, ERR_INVALID_APPLICATION_STATE, 409)

    application = fixtures.read_application(api, app_id)
    assert application["status"] == "WITHDRAWN", "WITHDRAWN admits no further transition"
    assert_tower_capacity(
        fixtures.read_tower(api, world["tower"]["id"]), open_review_count=0
    )


# ─── The two-stage execution of a site amendment ─────────────────────────────


def test_execute_without_signature_parks_amendment_and_claims_no_capacity(api):
    """PRD §3.7: "When it is `false`, the amendment moves `DRAFT →
    PENDING_SIGNATURE`: the only precondition is that the amendment's tower has
    a ground lease whose `status` is `ACTIVE`, otherwise
    `ERR_GROUND_LEASE_NOT_ACTIVE`, and the amendment parks awaiting the
    countersignature without claiming any capacity."

    Design: Corner/state_machines/execute_with_signature_pending_holds_amendment_and_capacity
    """
    chain = _papered_amendment_chain(api)
    amendment_id = chain["amendment"]["id"]

    resp = api.execute_site_amendment(
        amendment_id, factories.execute_payload(False), ADMIN_HEADERS
    )

    amendment = validate_success(resp, 200)
    assert_amendment_axes(
        amendment, execution_status="PENDING_SIGNATURE", billing_status="NOT_BILLING"
    )
    assert_load_units(amendment["reserved_load_units"], 500.0, "reserved_load_units")

    tower = fixtures.read_tower(api, chain["tower"]["id"])
    assert_tower_capacity(
        tower,
        reserved_load_units=0.0,
        reserved_ground_space_sqft=0,
        available_ground_space_sqft=9000,
        occupied_band_count=0,
        capacity_posture="OPEN",
    )

    mla = fixtures.read_master_lease(api, chain["tenant"]["id"], chain["mla"]["id"])
    assert mla["executed_amendment_count"] == 0, (
        "no amendment has been executed yet on this master lease"
    )
    application = fixtures.read_application(api, chain["application"]["id"])
    assert application["status"] == "AMENDMENT_ISSUED"


def test_execution_opens_the_billing_axis_and_reconciles_the_tower(api):
    """PRD §3.7: "The system itself drives three further billing moves:
    `NOT_BILLING → BILLING` as a side effect of the execution axis reaching
    `EXECUTED`, which also recomputes `current_monthly_rent_cents`; `BILLING →
    CLOSED` and `SUSPENDED → CLOSED` as side effects of the execution axis
    reaching `TERMINATED`; and `NOT_BILLING → CLOSED` as a side effect of the
    execution axis reaching `VOIDED`."

    PRD §3.7 also pins the reconciliation this fires: "The tower's
    `reserved_load_units`, `reserved_load_pct`, `reserved_ground_space_sqft`,
    `available_ground_space_sqft`, `occupied_elevation_bands` and
    `capacity_posture` are all recomputed, the master lease's
    `executed_amendment_count` is recomputed, and the tower's `version` is
    incremented by one."

    Design: Corner/state_machines/amendment_execution_opens_billing_axis_and_reconciles_counters
    """
    chain = _papered_amendment_chain(api)
    amendment_id = chain["amendment"]["id"]
    fixtures.execute_amendment(api, amendment_id, signature_received=False)

    resp = api.execute_site_amendment(
        amendment_id, factories.execute_payload(True), ADMIN_HEADERS
    )

    amendment = validate_success(resp, 200)
    assert_amendment_axes(
        amendment,
        execution_status="EXECUTED",
        billing_status="BILLING",
        restoration_status="NOT_REQUIRED",
    )
    # PRD §3.7: an effective_date of 2026-08-01 has seen no anniversary at the
    # cold-start clock, so the site rent is still the un-escalated base.
    assert_cents(
        amendment["current_monthly_rent_cents"], 200000, "current_monthly_rent_cents"
    )

    mla = fixtures.read_master_lease(api, chain["tenant"]["id"], chain["mla"]["id"])
    assert mla["executed_amendment_count"] == 1

    tower = fixtures.read_tower(api, chain["tower"]["id"])
    assert_tower_capacity(
        tower,
        reserved_load_units=500.0,
        reserved_load_pct=5.556,
        reserved_ground_space_sqft=300,
        available_ground_space_sqft=8700,
        occupied_band_count=1,
        capacity_posture="OPEN",
    )
    assert_occupied_band(
        tower["occupied_elevation_bands"][0],
        amendment_id=amendment_id,
        bottom_ft=100,
        top_ft=140,
        tenant_id=chain["tenant"]["id"],
    )


def test_void_from_pending_signature_closes_the_billing_axis(api):
    """PRD §3.7: "An amendment that has not yet been executed can be voided
    with no preconditions, as `DRAFT → VOIDED` or `PENDING_SIGNATURE → VOIDED`
    on the execution axis, which also sets `billing_status` to `CLOSED`."

    Design: Corner/state_machines/void_from_pending_signature_closes_billing_axis
    """
    chain = _papered_amendment_chain(api)
    amendment_id = chain["amendment"]["id"]
    parked = fixtures.execute_amendment(api, amendment_id, signature_received=False)
    assert_amendment_axes(
        parked, execution_status="PENDING_SIGNATURE", billing_status="NOT_BILLING"
    )

    resp = api.void_site_amendment(amendment_id, {}, ADMIN_HEADERS)

    amendment = validate_success(resp, 200)
    assert_amendment_axes(
        amendment, execution_status="VOIDED", billing_status="CLOSED"
    )

    tower = fixtures.read_tower(api, chain["tower"]["id"])
    assert_tower_capacity(
        tower,
        reserved_load_units=0.0,
        reserved_ground_space_sqft=0,
        available_ground_space_sqft=9000,
        occupied_band_count=0,
    )
    mla = fixtures.read_master_lease(api, chain["tenant"]["id"], chain["mla"]["id"])
    assert mla["executed_amendment_count"] == 0


def test_billing_move_to_billing_from_not_billing_rejected(api):
    """PRD §3.7: "Any billing move not declared from the amendment's current
    `billing_status` is rejected with `ERR_INVALID_BILLING_STATE`."

    Design: Corner/state_machines/billing_status_to_billing_from_not_billing_rejected
    """
    chain = _papered_amendment_chain(api, with_ground_lease=False)
    amendment_id = chain["amendment"]["id"]

    resp = api.set_site_amendment_billing_status(
        amendment_id, factories.billing_status_payload("BILLING"), ADMIN_HEADERS
    )

    validate_error(resp, ERR_INVALID_BILLING_STATE, 409)

    amendment = fixtures.read_amendment(api, amendment_id)
    assert_amendment_axes(
        amendment, execution_status="DRAFT", billing_status="NOT_BILLING"
    )
