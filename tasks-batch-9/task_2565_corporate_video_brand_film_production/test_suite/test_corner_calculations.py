"""Derived money, derived counters and derived verdicts, one formula at a time.

Each test drives a single derivation to a value that could not have come from a
simpler rule: a rental day that is ceiled rather than truncated, a day total that
filters its inputs by status, a retention window that decays a second after its
edge, an allowance tested for strict excess, a compensation basis that switches
its own inputs, and a QC verdict whose two caption findings point in opposite
directions.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ARCHIVE_HANDED_OVER,
    ARCHIVE_RETENTION_EXPIRED,
    BASIS_FINAL,
    BASIS_PROVISIONAL,
    BOOKING_HELD,
    BUDGET_LINE_PLANNED,
    CATEGORY_EQUIPMENT,
    CATEGORY_LOCATION,
    CATEGORY_POST,
    CATEGORY_TALENT,
    COORDINATOR,
    DECISION_APPROVE,
    DEFAULT_CLOCK,
    DELIVERABLE_PENDING,
    DEPT_CAMERA,
    DEPT_GRIP_ELECTRIC,
    ENGAGEMENT_CONFIRMED,
    LINE_PRODUCER,
    NON_UNION,
    PROJECT_ARCHIVED,
    QC_CAPTION_REQUIREMENT_UNMET,
    QC_UNREQUESTED_CAPTION_ASSET,
    RESERVATION_RESERVED,
    TECHNICAL_QC_FAILED,
    USAGE_BUYOUT,
    ApiErrorId,
    add_budget_line,
    add_crew_member,
    add_deliverable,
    approve_budget,
    assert_at_default_clock,
    assert_booking_components,
    assert_budget_line,
    assert_deliverable_state,
    assert_instant_equals,
    assert_ledgers,
    assert_project_state,
    assert_reservation,
    assert_shoot_day_state,
    assert_talent_comp,
    assert_total_count,
    assert_version_axes,
    book_crew,
    budget_line_payload,
    cancel_shoot_day,
    cast_talent,
    confirm_booking,
    confirm_talent,
    expected_retention_expiry,
    handover,
    lock_scope,
    open_project,
    passed_cut,
    read_booking,
    read_deliverable,
    read_project,
    read_shoot_day,
    record_qc,
    register_location,
    release_booking,
    reserve_equipment,
    review_cut,
    schedule_shoot_day,
    set_clock,
    submit_cut,
    upload_next_cut,
)


def _scoped_project(
    api,
    client_name,
    campaign_title,
    creative_brief_summary,
    category,
    description,
    unit_rate_cents,
    **project_over,
):
    """A `SCOPED` project carrying one OLV deliverable and one budget line."""
    project = open_project(
        api,
        client_name=client_name,
        campaign_title=campaign_title,
        creative_brief_summary=creative_brief_summary,
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
        **project_over,
    )
    deliverable = add_deliverable(
        api,
        project["id"],
        title=f"{campaign_title} 60",
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=60,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    add_budget_line(
        api,
        project["id"],
        category=category,
        description=description,
        quantity=1,
        unit_rate_cents=unit_rate_cents,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    return project, deliverable


def _planned_day(api, project_id, location_name, address, permit_authority):
    """A one-stage venue at 90,000 cents a day and one `PLANNED` day on it."""
    location = register_location(
        api,
        name=location_name,
        address=address,
        stage_count=1,
        daily_fee_cents=90000,
        insurance_minimum_cents=50000000,
        permit_authority=permit_authority,
    )
    day = schedule_shoot_day(
        api,
        project_id,
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    return location, day


def _wide_rights_project_with_a_draft_memo(api, campaign_title):
    """A three-channel 36-month project delivering one 12-month OLV cut only."""
    project = open_project(
        api,
        client_name="Grantham Mutual",
        campaign_title=campaign_title,
        creative_brief_summary=(
            "Brand film licensed broadly on paper but delivered as a single OLV cut."
        ),
        channel_scope=["OLV", "SOCIAL", "BROADCAST"],
        usage_term_months=36,
        budget_ceiling_cents=50000000,
    )
    add_deliverable(
        api,
        project["id"],
        title="Wide Rights 60",
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=60,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_TALENT,
        description="Principal talent pool",
        quantity=1,
        unit_rate_cents=700000,
        markup_pct=0,
    )
    engagement = cast_talent(
        api,
        project["id"],
        talent_name="Rea Sandoval",
        union_affiliation=NON_UNION,
        compensation_model=USAGE_BUYOUT,
        session_fee_cents=100000,
        session_days=2,
    )
    lock_scope(api, project["id"])
    return project, engagement


def test_a_rental_spanning_106_hours_bills_five_whole_days(api):
    """The partial fifth day bills in full, and the kit lands on both ledgers.

    PRD §3.6: "`rental_days` is the span from pickup to return in hours divided by 24
    and rounded up to a whole day, with a floor of one day, so any partial day bills
    as a full day and a same-morning pickup and return still bills one."

    PRD §3.6: "`total_cost_cents` is the `unit_count` multiplied by the
    `daily_rate_cents` and by `rental_days`."

    PRD §3.6: "A reservation is written at `status` `RESERVED`, and because `RESERVED`
    sits inside *both* inclusion sets, the reservation lands on the provisional **and**
    the committed figure in the same request; the day's `day_cost_cents` is refreshed,
    and the fiscal allowance is evaluated last."

    Design: Corner/calculations/equipment_reservation_cost_ceils_the_partial_rental_day
    """
    project, _deliverable = _scoped_project(
        api,
        client_name="Latham Optics",
        campaign_title="Long Lens",
        creative_brief_summary="One-day OLV brand film with a long rental window.",
        category=CATEGORY_EQUIPMENT,
        description="Camera rental pool",
        unit_rate_cents=200000,
    )
    _location, day = _planned_day(
        api, project["id"], "Latham Rooftop", "80 Summit Street, Denver", "Denver Film Office"
    )

    reservation = reserve_equipment(
        api,
        day["id"],
        vendor_name="Front Range Grip",
        kit_label="Long lens set",
        unit_count=1,
        daily_rate_cents=30000,
        pickup_at="2026-09-08T06:00:00Z",
        return_at="2026-09-12T16:00:00Z",
    )

    assert_reservation(
        reservation, rental_days=5, total_cost_cents=150000, status=RESERVATION_RESERVED
    )
    assert_ledgers(
        read_project(api, project["id"]), provisional_cents=350000, committed_cents=150000
    )
    assert_total_count(
        api.list_shoot_day_equipment_reservations(day["id"], headers=COORDINATOR), 1
    )


def test_the_day_total_counts_the_confirmed_booking_and_never_the_held_one(api):
    """Releasing the confirmed booking drops the day total the held one never joined.

    PRD §3.6: "A day's `day_cost_cents` is a display-only total, recomputed on every
    shoot-day read and after any booking or reservation status change on that day: it
    is the venue's `daily_fee_cents` plus the `cost_cents` of every crew booking on the
    day whose `status` is `CONFIRMED` or `COMPLETED` plus the `total_cost_cents` of
    every reservation on the day whose `status` is `RESERVED` or `RETURNED`."

    PRD §3.5: "The third test counts `confirmed_crew_count`, the crew bookings on the
    day whose `status` is `CONFIRMED` or `COMPLETED`."

    Design: Corner/calculations/shoot_day_cost_excludes_held_and_released_children
    """
    project, _deliverable = _scoped_project(
        api,
        client_name="Warren Paper",
        campaign_title="Fold Line",
        creative_brief_summary="One-day OLV brand film with a partly confirmed unit.",
        category=CATEGORY_LOCATION,
        description="Mill floor fee",
        unit_rate_cents=90000,
    )
    _location, day = _planned_day(
        api, project["id"], "Warren Mill Floor", "12 Paper Row, Appleton", "Appleton Film Office"
    )
    crew_a = add_crew_member(
        api, full_name="Ivo Marek", department=DEPT_CAMERA, hourly_rate_cents=5000
    )
    crew_b = add_crew_member(
        api, full_name="Sasha Bell", department=DEPT_GRIP_ELECTRIC, hourly_rate_cents=5000
    )
    confirmed_booking = book_crew(
        api,
        day["id"],
        crew_a["id"],
        department_role="Operator",
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )
    confirm_booking(api, confirmed_booking["id"])
    held_booking = book_crew(
        api,
        day["id"],
        crew_b["id"],
        department_role="Key Grip",
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )

    assert_shoot_day_state(
        read_shoot_day(api, day["id"]), day_cost_cents=140000, confirmed_crew_count=1
    )

    release_booking(
        api, confirmed_booking["id"], release_reason="Operator reassigned to another unit."
    )

    assert_shoot_day_state(
        read_shoot_day(api, day["id"]), day_cost_cents=90000, confirmed_crew_count=0
    )
    assert_booking_components(read_booking(api, held_booking["id"]), status=BOOKING_HELD)
    assert_total_count(api.list_crew_bookings(shoot_day_id=day["id"], headers=COORDINATOR), 2)


def test_the_archive_flips_to_retention_expired_one_second_after_the_window(api):
    """At the expiry instant the package is still held; a second later it is not.

    PRD §3.10: "`retention_expires_at` is `handover_at` plus the project's
    `raw_footage_retention_months` multiplied by 30 days, using whole days added to the
    handover instant; calendar month lengths are deliberately not used, so a 12-month
    retention term is exactly 360 days."

    PRD §3.10: "`archive_status` is derived from those two columns: it reads
    `NOT_PACKAGED` while `handover_at` is null, `RETENTION_EXPIRED` once the logical
    clock has passed `retention_expires_at`, and `HANDED_OVER` in every other case."

    Design: Corner/calculations/archive_status_flips_to_retention_expired_past_the_360_day_window
    """
    project, deliverable = _scoped_project(
        api,
        client_name="Ossian Rail",
        campaign_title="Sidings",
        creative_brief_summary=(
            "OLV brand film whose raw footage retention is being tracked."
        ),
        category=CATEGORY_POST,
        description="Edit and finish",
        unit_rate_cents=2000000,
        raw_footage_retention_months=12,
        raw_footage_terabytes=30.5,
    )
    approve_budget(api, project["id"], 2000000)
    _location, day = _planned_day(
        api, project["id"], "Ossian Yard", "4 Siding Road, Fort Wayne", "Fort Wayne Film Office"
    )
    cancel_shoot_day(api, day["id"], cancellation_reason="Library footage used instead.")
    cut = passed_cut(
        api,
        deliverable["id"],
        cut_label="Sidings v1",
        aspect_ratio="16:9",
        duration_seconds=60,
        has_captions=False,
        caption_format="NONE",
        file_size_gb=9.0,
    )
    submit_cut(api, cut["id"])
    review_cut(api, cut["id"], DECISION_APPROVE, review_note="Approved as delivered.")
    archived = handover(
        api, project["id"], handover_recipient="Dana Whitlock, client archive custodian"
    )
    assert_at_default_clock(archived["handover_at"])
    expiry = expected_retention_expiry(DEFAULT_CLOCK, 12)
    assert_instant_equals(archived["retention_expires_at"], expiry)

    set_clock(api, expiry)
    at_the_edge = read_project(api, project["id"])

    assert_project_state(
        at_the_edge, status=PROJECT_ARCHIVED, archive_status=ARCHIVE_HANDED_OVER
    )

    set_clock(api, "2027-07-27T00:00:01Z")
    one_second_later = read_project(api, project["id"])

    assert_project_state(
        one_second_later, status=PROJECT_ARCHIVED, archive_status=ARCHIVE_RETENTION_EXPIRED
    )
    assert_instant_equals(one_second_later["retention_expires_at"], expiry)


def test_a_line_landing_exactly_on_the_ceiling_is_accepted_and_one_cent_more_is_not(api):
    """The allowance test is strict excess, so equality passes and 1 cent fails.

    PRD §2.8: "The allowance depends on where the project stands: while the project's
    `status` is `DRAFT` or `SCOPED` the allowance equals `budget_ceiling_cents` exactly,
    with no tolerance; once the budget has been approved — that is, for `IN_PRODUCTION`,
    `IN_POST` and any later status — the allowance is `budget_ceiling_cents` multiplied
    by 1.05, rounded half up to whole cents, so the production may run five percent hot
    against its contracted ceiling."

    PRD §2.8: "If the projected figure is strictly greater than the allowance the write
    is refused with `ERR_BUDGET_CEILING_EXCEEDED` (HTTP 422); a projected figure exactly
    equal to the allowance is accepted."

    Design: Corner/calculations/commitment_allowance_accepts_equality_and_rejects_one_cent_over
    """
    project = open_project(
        api,
        client_name="Nine Cents Media",
        campaign_title="To The Penny",
        creative_brief_summary="OLV brand film budgeted to the exact ceiling.",
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=100000,
    )
    add_deliverable(
        api,
        project["id"],
        title="To The Penny 30",
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=30,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )

    at_the_ceiling = add_budget_line(
        api,
        project["id"],
        category=CATEGORY_POST,
        description="Edit at the ceiling",
        quantity=1,
        unit_rate_cents=100000,
        markup_pct=0,
    )

    assert_budget_line(at_the_ceiling, extended_cents=100000, status=BUDGET_LINE_PLANNED)
    assert_ledgers(read_project(api, project["id"]), provisional_cents=100000)

    one_cent_over = api.create_budget_line(
        budget_line_payload(
            project["id"],
            category=CATEGORY_POST,
            description="One cent of colour",
            quantity=1,
            unit_rate_cents=1,
            markup_pct=0,
        ),
        headers=LINE_PRODUCER,
    )

    validate_error(one_cent_over, ApiErrorId.ERR_BUDGET_CEILING_EXCEEDED)
    assert_total_count(
        api.list_project_budget_lines(project["id"], headers=LINE_PRODUCER), 1
    )
    assert_ledgers(read_project(api, project["id"]), provisional_cents=100000)


def test_the_final_basis_prices_the_cuts_actually_registered_not_the_paper_rights(api):
    """The same memo prices at 655,600 on paper and 330,000 against what exists.

    PRD §3.3: "Under the `PROVISIONAL` basis, `channel_basis_count` is the number of
    distinct channels in the project's `channel_scope` and `term_basis_months` is the
    project's `usage_term_months` — the widest rights the master agreement allows."

    PRD §3.3: "Under the `FINAL` basis, evaluated at confirmation,
    `channel_basis_count` is the count of distinct `channel` values across the
    deliverables actually registered on the project and `term_basis_months` is the
    largest `usage_rights_months` among those deliverables, regardless of what state
    each deliverable is in."

    PRD §3.3: "A term multiplier is selected by the term in months: 1.00 when the term
    is 12 months or fewer, 1.35 when it is more than 12 and at most 24, 1.65 when it is
    more than 24 and at most 36, and 2.00 for any longer term."

    Design: Corner/calculations/talent_final_basis_reads_deliverables_not_project_channel_scope
    """
    _project, engagement = _wide_rights_project_with_a_draft_memo(api, "Wide Rights")

    assert_talent_comp(
        engagement,
        comp_basis=BASIS_PROVISIONAL,
        base_fee_cents=200000,
        usage_load_cents=396000,
        agent_fee_cents=59600,
        total_comp_cents=655600,
        reuse_fee_cents=0,
        pension_health_cents=0,
    )
    assert engagement["channel_basis_count"] == 3, engagement["channel_basis_count"]
    assert engagement["term_basis_months"] == 36, engagement["term_basis_months"]
    assert engagement["reuse_cycles"] == 0, engagement["reuse_cycles"]

    confirmed = confirm_talent(api, engagement["id"])

    assert_talent_comp(
        confirmed,
        comp_basis=BASIS_FINAL,
        base_fee_cents=200000,
        usage_load_cents=100000,
        agent_fee_cents=30000,
        total_comp_cents=330000,
        reuse_fee_cents=0,
        pension_health_cents=0,
    )
    assert confirmed["channel_basis_count"] == 1, confirmed["channel_basis_count"]
    assert confirmed["term_basis_months"] == 12, confirmed["term_basis_months"]
    assert confirmed["reuse_cycles"] == 0, confirmed["reuse_cycles"]


def test_the_basis_switch_replaces_the_provisional_total_row_for_row(api):
    """The provisional figure swaps one total for the other instead of adding to it.

    PRD §3.3: "The engagement then enters the committed set: the project's
    `committed_cost_cents` increases by the `FINAL` `total_comp_cents`, and
    `provisional_cost_cents` is recomputed with the `FINAL` total replacing the
    `PROVISIONAL` total for this engagement — which may move the provisional figure in
    either direction — after which `budget_variance_cents` is recomputed."

    PRD §2.7: "`budget_variance_cents` is `provisional_cost_cents` minus
    `approved_budget_cents`, and is reported as 0 for as long as `approved_budget_cents`
    is null."

    Design: Corner/calculations/talent_basis_switch_reconciles_the_provisional_ledger_downward
    """
    project, engagement = _wide_rights_project_with_a_draft_memo(api, "Wide Rights Ledger")

    assert_ledgers(
        read_project(api, project["id"]), provisional_cents=1355600, committed_cents=0
    )

    confirm_talent(api, engagement["id"])

    after = read_project(api, project["id"])
    assert_ledgers(
        after,
        provisional_cents=1030000,
        committed_cents=330000,
        approved_cents=None,
        variance_cents=0,
    )
    engagements = assert_total_count(
        api.list_project_talent_engagements(project["id"], headers=LINE_PRODUCER), 1
    )
    assert_talent_comp(engagements[0], status=ENGAGEMENT_CONFIRMED)


def test_captions_missing_and_captions_unasked_for_fail_on_their_own_reasons(api):
    """Each caption branch fires alone, and neither borrows the other's finding.

    PRD §3.8: "`CAPTION_REQUIREMENT_UNMET` is recorded when the deliverable's
    `caption_requirement` is anything other than `NONE` and either the cut's
    `has_captions` is false or its `caption_format` differs from that requirement."

    PRD §3.8: "`UNREQUESTED_CAPTION_ASSET` is recorded when the deliverable's
    `caption_requirement` is `NONE` and yet the cut's `has_captions` is true."

    PRD §3.8: "If the findings list is empty the cut advances `PENDING_QC → QC_PASSED`
    and `qc_failure_reasons` is written as an empty array; otherwise the cut advances
    `PENDING_QC → QC_FAILED` and `qc_failure_reasons` holds the findings in the order
    above."

    Design: Corner/calculations/qc_flags_caption_requirement_unmet_and_unrequested_caption_asset
    """
    project = open_project(
        api,
        client_name="Ellery Health",
        campaign_title="Caption Test",
        creative_brief_summary=(
            "Brand film with one captioned social cut and one clean OLV cut."
        ),
        channel_scope=["OLV", "SOCIAL"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
    )
    social = add_deliverable(
        api,
        project["id"],
        title="Caption Test social 15",
        channel="SOCIAL",
        aspect_ratio="9:16",
        target_duration_seconds=15,
        caption_requirement="BURNED_IN_SUBTITLES",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    olv = add_deliverable(
        api,
        project["id"],
        title="Caption Test OLV 60",
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=60,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    social_cut = upload_next_cut(
        api,
        social["id"],
        cut_label="social v1 no captions",
        aspect_ratio="9:16",
        duration_seconds=15,
        has_captions=False,
        caption_format="NONE",
        file_size_gb=2.1,
    )
    olv_cut = upload_next_cut(
        api,
        olv["id"],
        cut_label="OLV v1 with sidecar captions",
        aspect_ratio="16:9",
        duration_seconds=60,
        has_captions=True,
        caption_format="CLOSED_SRT",
        file_size_gb=8.8,
    )

    social_verdict = record_qc(api, social_cut["id"])
    olv_verdict = record_qc(api, olv_cut["id"])

    assert_version_axes(
        social_verdict,
        technical_status=TECHNICAL_QC_FAILED,
        qc_failure_reasons=[QC_CAPTION_REQUIREMENT_UNMET],
    )
    assert_version_axes(
        olv_verdict,
        technical_status=TECHNICAL_QC_FAILED,
        qc_failure_reasons=[QC_UNREQUESTED_CAPTION_ASSET],
    )
    assert_deliverable_state(
        read_deliverable(api, social["id"]),
        status=DELIVERABLE_PENDING,
        consumed_review_rounds=0,
    )
    assert_deliverable_state(
        read_deliverable(api, olv["id"]),
        status=DELIVERABLE_PENDING,
        consumed_review_rounds=0,
    )
