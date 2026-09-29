"""Threshold instants in the sweep, and the pins that later adoptions must not touch."""

from test_helpers import (
    ADMIN,
    BILLER,
    OFFICER,
    TWO_BAND_LADDER,
    advance_clock,
    adopt_schedule,
    api_client,
    create_encounter_payload,
    refresh_encounter,
    refresh_finding,
    refresh_health_center,
    refresh_patient,
    same_instant,
    setup_boot_core,
    setup_boot_pt,
    setup_draft_fee_schedule,
    setup_encounter,
    setup_open_finding,
    validate_success,
)


def _second_period_schedule(ctx):
    """A second two-band ladder for the abutting period [2027-01-01, 2028-01-01)."""
    draft = setup_draft_fee_schedule(
        ctx["health_center_id"],
        fpg_year=2026,
        effective_start="2027-01-01T00:00:00Z",
        effective_end="2028-01-01T00:00:00Z",
        nominal_fee_cents=2500,
        ladder=TWO_BAND_LADDER,
    )
    adoption = adopt_schedule(
        ctx["health_center_id"], draft["fee_schedule"]["id"], ctx["chair_id"]
    )
    return {
        "fee_schedule": adoption["fee_schedule"],
        "fee_schedule_id": adoption["fee_schedule"]["id"],
        "tiers_by_label": {t["tier_label"]: t for t in draft["tiers"]},
        "observed_version": adoption["observed_version"],
    }


def test_the_escalation_boundary_is_inclusive_at_the_due_instant():
    """The day before escalates nothing; the due instant itself escalates.

    PRD 3.8: "A finding escalates — `OPEN → ESCALATED` or `CAP_SUBMITTED → ESCALATED` —
    when its `severity` is `CONDITION`, its `cap_due_at` is at or before the logical
    clock, and no corrective action plan of that finding has `status` equal to
    `ACCEPTED`."

    PRD 3.8: "The third hop follows: because conditions are now imposed, the grantee's
    `scope_posture` moves `OPEN → CHANGE_FROZEN` and the grantee's `version` increments by
    one."

    Design: Corner/cross_cutting_complexity_layers/finding_escalates_exactly_when_the_clock_reaches_cap_due_at
    """
    ctx = setup_boot_core()
    finding = setup_open_finding(
        ctx,
        requirement_code="REQ_BOARD_AUTHORITY_19",
        severity="CONDITION",
        cap_due_days=30,
        service_site_id=ctx["site_id"],
        finding_summary="Governing board lacks patient-majority composition",
    )
    assert same_instant(finding["cap_due_at"]) == "2026-08-31T00:00:00Z"

    advance_clock("2026-08-30T00:00:00Z")
    before = validate_success(api_client.run_compliance_sweep(ADMIN))
    assert before["escalated_finding_count"] == 0, (
        "one day short of the deadline nothing is due, got "
        f"{before['escalated_finding_count']}"
    )
    assert refresh_finding(finding["id"])["status"] == "OPEN"
    assert refresh_health_center(ctx["health_center_id"])["scope_posture"] == "OPEN"

    advance_clock("2026-08-31T00:00:00Z")
    at_due = validate_success(api_client.run_compliance_sweep(ADMIN))
    assert at_due["escalated_finding_count"] == 1, (
        "the boundary instant is included, got "
        f"{at_due['escalated_finding_count']}"
    )

    escalated = refresh_finding(finding["id"])
    assert escalated["status"] == "ESCALATED"
    assert same_instant(escalated["escalated_at"]) == "2026-08-31T00:00:00Z"
    frozen = refresh_health_center(ctx["health_center_id"])
    assert frozen["scope_posture"] == "CHANGE_FROZEN"
    assert frozen["open_condition_count"] == 1


def test_a_later_sweep_escalates_only_the_row_that_has_newly_come_due():
    """The checkpoint is per row: an escalated finding is out of the candidate set.

    PRD 3.9: "Step two escalates findings: every site visit finding whose `severity` is
    `CONDITION`, whose `status` is `OPEN` or `CAP_SUBMITTED`, whose `cap_due_at` is at or
    before the logical clock, and which has no accepted corrective action plan, escalates
    and fires the five-hop escalation cascade of section 3.8."

    PRD 3.8: "The first hop stamps `escalated_at` with the logical clock and recomputes
    the grantee's `open_condition_count`."

    Design: Corner/cross_cutting_complexity_layers/sweep_checkpoint_never_re_escalates_an_already_escalated_finding
    """
    ctx = setup_boot_core()
    one_day = setup_open_finding(
        ctx,
        requirement_code="REQ_SLIDING_FEE_16",
        severity="CONDITION",
        cap_due_days=1,
        service_site_id=ctx["site_id"],
        finding_summary="Sliding fee schedule not posted at the point of service",
    )
    thirty_day = setup_open_finding(
        ctx,
        requirement_code="REQ_BOARD_AUTHORITY_19",
        severity="CONDITION",
        cap_due_days=30,
        service_site_id=ctx["site_id"],
        finding_summary="Governing board lacks patient-majority composition",
    )

    advance_clock("2026-08-02T00:00:00Z")
    first_run = validate_success(api_client.run_compliance_sweep(ADMIN))
    assert first_run["escalated_finding_count"] == 1

    advance_clock("2026-08-31T00:00:00Z")
    second_run = validate_success(api_client.run_compliance_sweep(ADMIN))
    assert second_run["escalated_finding_count"] == 1, (
        "only the thirty-day finding is newly due; the escalated one is not counted "
        f"again, got {second_run['escalated_finding_count']}"
    )

    first_finding = refresh_finding(one_day["id"])
    assert first_finding["status"] == "ESCALATED"
    assert same_instant(first_finding["escalated_at"]) == "2026-08-02T00:00:00Z", (
        "the earlier stamp was not overwritten by the later sweep"
    )
    second_finding = refresh_finding(thirty_day["id"])
    assert second_finding["status"] == "ESCALATED"
    assert same_instant(second_finding["escalated_at"]) == "2026-08-31T00:00:00Z"

    grantee = refresh_health_center(ctx["health_center_id"])
    assert grantee["open_condition_count"] == 2
    assert grantee["scope_posture"] == "CHANGE_FROZEN"


def test_an_encounter_keeps_its_pins_when_a_later_schedule_is_adopted():
    """Adopting for a future period rewrites no history at all.

    PRD 1: "The second is **pinning**: an encounter permanently records which fee
    schedule, which income verification and which discount tier produced its charge, so
    that later supersessions and adoptions never silently rewrite history — history is
    rewritten only by the explicitly specified retroactive cascades described in section
    3."

    PRD 3.3: "Any adopted schedule of the same grantee sharing this schedule's
    `effective_start` moves `ADOPTED → SUPERSEDED` and has its
    `superseded_by_fee_schedule_id` pointed at the newly adopted schedule. The new
    schedule's `review_status` is then recomputed, and the grantee's `version` increments
    by one."

    Design: Corner/cross_cutting_complexity_layers/pinned_fee_schedule_and_tier_survive_a_later_adoption
    """
    ctx = setup_boot_pt()
    encounter = setup_encounter(
        ctx,
        ctx["patient_id"],
        encounter_date="2026-03-15T00:00:00Z",
        payer_type="SELF_PAY",
        gross_charge_cents=8000,
    )
    assert encounter["patient_charge_cents"] == 2500
    version_before = refresh_health_center(ctx["health_center_id"])["version"]

    second = _second_period_schedule(ctx)
    assert second["fee_schedule"]["status"] == "ADOPTED"

    pinned = refresh_encounter(encounter["id"])
    assert pinned["fee_schedule_id"] == ctx["fee_schedule_id"], (
        "the encounter still points at the schedule that priced it"
    )
    assert (
        pinned["pinned_discount_tier_id"]
        == ctx["tiers_by_label"]["NOMINAL_FULL"]["id"]
    ), "the pinned band is the original ladder's nominal band"
    assert pinned["patient_charge_cents"] == 2500
    assert pinned["charge_adjustment_cents"] == 0, (
        "no retroactive adjustment was written, got "
        f"{pinned['charge_adjustment_cents']}"
    )
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 2500

    original = validate_success(
        api_client.get_fee_schedule(ctx["fee_schedule_id"], OFFICER)
    )
    assert original["status"] == "ADOPTED", (
        "the periods abut rather than share a start, so nothing was superseded"
    )
    assert original["superseded_by_fee_schedule_id"] is None
    assert (
        refresh_health_center(ctx["health_center_id"])["version"] == version_before + 1
    ), "the adoption is exactly one grantee mutation"


def test_the_selector_prices_against_the_period_containing_the_date_of_service():
    """Two adopted periods abut, and only the containing one is consulted.

    PRD 3.5: "Its candidate set is every fee schedule whose `health_center_id` equals the
    site's grantee, whose `status` is `ADOPTED`, and whose half-open period contains the
    `encounter_date` — that is, whose `effective_start` is at or before the
    `encounter_date` and whose `effective_end` is strictly after it."

    PRD 3.5: "The winner's identifier is pinned onto the encounter as `fee_schedule_id`,
    permanently."

    Design: Corner/cross_cutting_complexity_layers/fee_schedule_selector_picks_the_period_containing_the_encounter_date
    """
    ctx = setup_boot_pt()
    second = _second_period_schedule(ctx)
    advance_clock("2027-02-01T00:00:00Z")

    encounter = validate_success(
        api_client.create_encounter(
            create_encounter_payload(
                ctx["patient_id"],
                ctx["site_id"],
                ctx["service_id"],
                encounter_date="2027-01-15T00:00:00Z",
                payer_type="SELF_PAY",
                gross_charge_cents=8000,
            ),
            BILLER,
        ),
        201,
    )

    assert encounter["fee_schedule_id"] == second["fee_schedule_id"], (
        "2027-01-15 falls inside the second period, not the first"
    )
    assert (
        encounter["pinned_discount_tier_id"]
        == second["tiers_by_label"]["NOMINAL_FULL"]["id"]
    ), "the winning schedule's own ladder supplied the band"
    assert encounter["charge_basis"] == "SLIDING_FEE_TIER"
    assert encounter["patient_charge_cents"] == 2500
    assert encounter["income_verification_id"] == ctx["income_verification_id"], (
        "the closed window from 2026-03-01 still covers the new date of service"
    )

    first = validate_success(
        api_client.get_fee_schedule(ctx["fee_schedule_id"], OFFICER)
    )
    assert first["status"] == "ADOPTED", (
        "the earlier schedule is still adopted, it was simply not a candidate"
    )
    assert first["superseded_by_fee_schedule_id"] is None
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 2500
