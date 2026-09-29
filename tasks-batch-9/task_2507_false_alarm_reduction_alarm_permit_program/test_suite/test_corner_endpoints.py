"""Endpoint-level reads, filtered listings and conditional actions of the program."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID, get_success_data, validate_error,
    validate_error_is_one_of, validate_paginated, validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U


def test_fee_schedule_read_returns_every_governing_constant(api):
    """Reading an activated fee schedule returns the whole set of governing constants it pins.

    PRD §3.1: "Its `fee_tiers` array holds the marginal ladder as ordered entries
    of `from_index`, `to_index` (null meaning open-ended) and `base_fee_cents`;
    the default ladder charges nothing for occurrences 1 and 2, 10000 cents for
    occurrence 3, 25000 for occurrence 4, 40000 for occurrence 5, and 75000 for
    occurrence 6 and everything above it."

    PRD §3.1: "Its `occupancy_multipliers` object maps each premises occupancy
    class to a multiplier, defaulting to 1.00 for `RESIDENTIAL`, 1.50 for
    `COMMERCIAL`, 1.25 for `SCHOOL`, 2.00 for `FINANCIAL` and 1.00 for
    `GOVERNMENT`."

    PRD §2.9: "A schedule is created in `DRAFT`, may be activated to `ACTIVE`,
    and is pushed to `SUPERSEDED` when a newer schedule is activated in its
    place; the supersession stamps `superseded_at` on the outgoing row, which is
    null while a schedule is `DRAFT` or `ACTIVE`."

    The only schedule in the program has just been activated, so it is `ACTIVE`
    and nothing has superseded it: `superseded_at` is null.

    Design: Corner/endpoints/fee_schedule_read_returns_every_governing_constant
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    schedule_id = X.create_active_fee_schedule(api, schedule_code="FS-2026-A")

    schedule = A.data_of(api.get_fee_schedule(schedule_id, U.BILLING_CLERK))
    A.assert_entity_envelope(schedule)
    assert schedule["schedule_code"] == "FS-2026-A"
    A.assert_status(schedule, "ACTIVE")
    assert schedule["superseded_at"] is None, "an active schedule carries a null superseded_at"

    tiers = schedule["fee_tiers"]
    assert len(tiers) == 5, f"the default ladder has five tiers, got {len(tiers)}"
    assert [t["from_index"] for t in tiers] == [1, 3, 4, 5, 6]
    assert [t["to_index"] for t in tiers] == [2, 3, 4, 5, None]
    assert [t["base_fee_cents"] for t in tiers] == [0, 10000, 25000, 40000, 75000]

    multipliers = schedule["occupancy_multipliers"]
    assert float(multipliers["RESIDENTIAL"]) == 1.00
    assert float(multipliers["COMMERCIAL"]) == 1.50
    assert float(multipliers["SCHOOL"]) == 1.25
    assert float(multipliers["FINANCIAL"]) == 2.00
    assert float(multipliers["GOVERNMENT"]) == 1.00

    late_tiers = schedule["late_renewal_tiers"]
    assert [t["max_days_late"] for t in late_tiers] == [15, 30, None]
    assert [t["fee_cents"] for t in late_tiers] == [1500, 3000, 6000]

    assert sorted(schedule["exempt_cause_codes"]) == sorted(C.EXEMPT_CAUSE_CODES)
    assert "NEW_INSTALLATION_GRACE" in schedule["exempt_cause_codes"]

    assert float(schedule["admin_fee_pct"]) == 0.05
    A.assert_money_cents(schedule["admin_fee_min_cents"], 500, "admin_fee_min_cents")
    A.assert_money_cents(schedule["admin_fee_max_cents"], 5000, "admin_fee_max_cents")
    A.assert_money_cents(schedule["per_incident_fee_cap_cents"], 100000, "per_incident_fee_cap_cents")
    assert schedule["counting_window_mode"] == "ROLLING_365"
    assert schedule["free_alarm_allowance"] == 2
    assert schedule["probation_threshold_count"] == 4
    assert schedule["suspension_threshold_count"] == 6


def test_alarm_company_read_returns_the_scoring_mode_and_status_stamps(api):
    """Reading a freshly registered monitoring company shows its scoring mode, its opening score and its null status stamps.

    PRD §3.10: "A monitoring company is registered with its `legal_name`, its
    state `license_number`, a `contact_email`, a `contact_phone` in E.164 form,
    and a `score_mode` of `VOLUME_WEIGHTED` or `PERIOD_EQUAL` that decides which
    scoring variant governs it thereafter."

    PRD §3.10: "The company is created in `ACTIVE` with
    `reporting_compliance_score` at 1.00, `probation_started_at`,
    `status_reason` and `last_status_action_at` all null, and its derived
    counters recomputed: `monitored_system_count` as the number of systems it
    monitors in `SUBMITTED`, `PERMITTED` or `UNPERMITTED`,
    `dispatch_request_count_lifetime` as the number of dispatch requests it has
    lodged across every status, and `consecutive_flagged_report_count` as the
    length of the most-recent unbroken run of its reports ending in
    `VARIANCE_FLAGGED`, taken in order of `period_start` ascending."

    Nothing has been registered against the company yet, so all three derived
    counters recompute to 0 and the opening score stands at 1.00.

    Design: Corner/endpoints/alarm_company_read_returns_the_scoring_mode_and_status_stamps
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    company_id = X.create_company(
        api,
        legal_name="Guardian Signal Monitoring LLC",
        license_number="TXALM-44120",
        contact_email="ops@guardiansignal.example",
        contact_phone="+12145550101",
        score_mode="VOLUME_WEIGHTED",
    )

    company = A.data_of(api.get_alarm_company(company_id, U.PERMIT_CLERK))
    A.assert_entity_envelope(company)
    assert company["legal_name"] == "Guardian Signal Monitoring LLC"
    assert company["license_number"] == "TXALM-44120"
    assert company["contact_email"] == "ops@guardiansignal.example"
    assert company["contact_phone"] == "+12145550101"
    assert company["score_mode"] == "VOLUME_WEIGHTED"

    A.assert_status(company, "ACTIVE")
    assert company["version"] == 1, f"a newly created row opens at version 1, got {company['version']}"
    A.assert_score_2dp(company["reporting_compliance_score"], 1.00, "reporting_compliance_score")
    assert company["probation_started_at"] is None
    assert company["status_reason"] is None
    assert company["last_status_action_at"] is None

    assert company["monitored_system_count"] == 0
    assert company["dispatch_request_count_lifetime"] == 0
    assert company["consecutive_flagged_report_count"] == 0


def test_alarm_companies_list_filtered_by_status_separates_the_suspended_monitor(api):
    """Filtering the company listing on status separates a suspended monitor from the still-active one, and the licence filter isolates one row.

    PRD §3.10: "A company may be read individually, showing its recomputed score
    and counters, or listed with filters on `status` and `license_number`, paged
    by `page` and `per_page`."

    PRD §3.10: "`SUSPEND` is available from `ACTIVE` or `PROBATION` and carries
    the same dispatch consequences as the automatic suspension, stamping
    `probation_started_at` when the company was still `ACTIVE`."

    PRD §2.3: "`has_more` is true when rows remain beyond the current window."

    Two companies exist and exactly one of them was suspended, so each status
    filter returns exactly one row while the unfiltered page reports a total of 2
    with no further pages.

    Design: Corner/endpoints/alarm_companies_list_filtered_by_status_separates_the_suspended_monitor
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    suspended_id = X.create_company(
        api, legal_name="Guardian Signal Monitoring LLC", license_number="TXALM-44120"
    )
    active_id = X.create_company(
        api, legal_name="Rival Central Station Co", license_number="TXALM-77002"
    )
    validate_success(
        api.company_status_action(
            suspended_id,
            {"action": "SUSPEND", "status_reason": "Repeated unreconciled dispatch reporting."},
            U.PROGRAM_ADMIN,
        )
    )

    still_active = A.single(
        api.list_alarm_companies(U.DISPATCH_SUPERVISOR, {"status": "ACTIVE", "page": 1, "per_page": 25})
    )
    assert still_active["id"] == active_id
    assert still_active["legal_name"] == "Rival Central Station Co"

    suspended = A.single(
        api.list_alarm_companies(U.DISPATCH_SUPERVISOR, {"status": "SUSPENDED", "page": 1, "per_page": 25})
    )
    assert suspended["id"] == suspended_id
    A.assert_status(suspended, "SUSPENDED")

    by_licence = A.single(
        api.list_alarm_companies(U.DISPATCH_SUPERVISOR, {"license_number": "TXALM-44120"})
    )
    assert by_licence["id"] == suspended_id

    _rows, meta = validate_paginated(
        api.list_alarm_companies(U.DISPATCH_SUPERVISOR, {"page": 1, "per_page": 25})
    )
    assert meta["total_count"] == 2, f"both companies must be listed, got {meta['total_count']}"
    assert meta["has_more"] is False, "a 25-row page over two companies has no further rows"


def test_site_contact_read_returns_one_roster_row_with_its_callable_flag(api):
    """Reading one roster entry returns its call order, its relationship and the callable flag that governs verification.

    PRD §3.2: "Adding one supplies the premises reference `alarm_site_id`, the
    party's `full_name`, a `phone_number` in E.164 form, their `relationship` to
    the premises (owner, manager, keyholder and the like), a `contact_priority`
    between 1 and 5 that fixes call order, and `is_ecv_callable`, which defaults
    to true and decides whether the contact counts toward enhanced call
    verification."

    PRD §3.2: "A contact's `status` is `ACTIVE` or `REMOVED`; removal is soft,
    setting `status` to `REMOVED` and stamping `removed_at` (null while active)
    rather than deleting the row."

    The contact has not been removed, so it reads back `ACTIVE` with a null
    `removed_at`.

    Design: Corner/endpoints/site_contact_read_returns_one_roster_row_with_its_callable_flag
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    site_id = X.create_site(
        api,
        address_key="1200-MAIN-ST-75201",
        street_address="1200 Main St",
        city="Dallas",
        zip_code="75201",
        occupancy_class="COMMERCIAL",
        police_beat="B-114",
    )
    first_id = X.create_contact(
        api,
        site_id,
        full_name="Rosa Villarreal",
        phone_number="+12145550111",
        relationship="OWNER",
        contact_priority=1,
        is_ecv_callable=True,
    )
    X.create_contact(
        api,
        site_id,
        full_name="Dev Anand",
        phone_number="+12145550112",
        relationship="MANAGER",
        contact_priority=2,
        is_ecv_callable=True,
    )

    contact = A.data_of(api.get_site_contact(first_id, U.DISPATCH_SUPERVISOR))
    A.assert_entity_envelope(contact)
    assert contact["alarm_site_id"] == site_id
    assert contact["full_name"] == "Rosa Villarreal"
    assert contact["phone_number"] == "+12145550111"
    assert contact["relationship"] == "OWNER"
    assert contact["contact_priority"] == 1
    assert contact["is_ecv_callable"] is True
    A.assert_status(contact, "ACTIVE")
    assert contact["removed_at"] is None


def test_alarm_systems_list_filtered_by_site_and_status_separates_pending_registrations(api):
    """Filtering the system listing by premises and status separates a still-pending registration from the permitted one.

    PRD §4: "List alarm systems, filterable by premises, monitoring company or
    status."

    PRD §3.3: "The row is created in `SUBMITTED`, and the new-installation grace
    anchor is taken from `installed_at`."

    PRD §3.3: "The system's `permitted_at` is stamped with the logical clock and
    its `unpermitted_since` is cleared."

    One system was approved while the clock read 2026-08-01T00:00:00Z and the
    second was left in `SUBMITTED`, so each status filter returns exactly one of
    the two rows of that premises.

    Design: Corner/endpoints/alarm_systems_list_filtered_by_site_and_status_separates_pending_registrations
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC, system_count=1)
    pending_id = X.create_submitted_system(api, bundle.site_id, bundle.company_id)

    submitted = A.single(
        api.list_alarm_systems(
            U.PERMIT_CLERK,
            {"alarm_site_id": bundle.site_id, "status": "SUBMITTED", "page": 1, "per_page": 25},
        )
    )
    assert submitted["id"] == pending_id
    A.assert_status(submitted, "SUBMITTED")
    assert submitted["permitted_at"] is None

    permitted = A.single(
        api.list_alarm_systems(
            U.PERMIT_CLERK,
            {"alarm_site_id": bundle.site_id, "status": "PERMITTED", "page": 1, "per_page": 25},
        )
    )
    assert permitted["id"] == bundle.system_id
    A.assert_status(permitted, "PERMITTED")
    assert X.parse(permitted["permitted_at"]) == X.parse("2026-08-01T00:00:00Z")

    rows, meta = validate_paginated(
        api.list_alarm_systems(U.PERMIT_CLERK, {"alarm_site_id": bundle.site_id, "per_page": 25})
    )
    assert meta["total_count"] == 2, f"the premises has two systems, got {meta['total_count']}"
    assert {row["id"] for row in rows} == {bundle.system_id, pending_id}

    by_company = A.assert_total_count(
        api.list_alarm_systems(
            U.PERMIT_CLERK, {"monitoring_company_id": bundle.company_id, "per_page": 25}
        ),
        2,
    )
    assert all(row["monitoring_company_id"] == bundle.company_id for row in by_company)


def test_alarm_permits_list_filtered_by_site_returns_both_active_permits(api):
    """Filtering the permit listing by premises returns both issued permits with their sequential numbers, and the system filter narrows to one.

    PRD §3.3: "A permit is created — `PENDING_ISSUANCE` is only the pre-persist
    state, so the row lands directly in `ACTIVE` — carrying `alarm_system_id`, the
    denormalized `alarm_site_id` copied from the system, and a `permit_number`
    assigned as the next zero-padded sequential value in issuance order, formatted
    `AP-000001`."

    PRD §3.3: "Its `term_start_at` is the logical clock, `term_end_at` is
    `term_start_at` plus `permit_term_days` whole days, and `grace_through_at` is
    `term_end_at` plus `renewal_grace_days` whole days — the last instant at
    which a grace renewal is still accepted."

    PRD §4: "List permits, filterable by system, premises or status."

    Both permits were issued while the clock read 2026-08-01T00:00:00Z, so each
    term ends 365 whole days later on 2027-08-01T00:00:00Z and neither has been
    renewed.

    Design: Corner/endpoints/alarm_permits_list_filtered_by_site_returns_both_active_permits
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC, system_count=2)

    rows = A.assert_total_count(
        api.list_alarm_permits(
            U.PERMIT_CLERK,
            {"alarm_site_id": bundle.site_id, "status": "ACTIVE", "page": 1, "per_page": 25},
        ),
        2,
    )
    assert {row["id"] for row in rows} == set(bundle.permit_ids)
    assert {row["permit_number"] for row in rows} == {"AP-000001", "AP-000002"}
    for row in rows:
        assert row["alarm_site_id"] == bundle.site_id
        A.assert_status(row, "ACTIVE")
        assert row["renewal_count"] == 0
        assert X.parse(row["term_start_at"]) == X.parse("2026-08-01T00:00:00Z")
        assert X.parse(row["term_end_at"]) == X.parse("2027-08-01T00:00:00Z")
        assert X.parse(row["grace_through_at"]) == X.parse("2027-08-31T00:00:00Z")

    first = A.single(
        api.list_alarm_permits(
            U.PERMIT_CLERK, {"alarm_system_id": bundle.system_ids[0], "page": 1, "per_page": 25}
        )
    )
    assert first["id"] == bundle.permit_ids[0]
    assert first["alarm_system_id"] == bundle.system_ids[0]


def test_dispatch_request_read_returns_the_frozen_ecv_verdict_and_call_attempts(api):
    """Reading a submitted dispatch request returns the verification verdict frozen at submission together with the call log behind it.

    PRD §3.4: "`distinct_ecv_contact_count` is then the number of distinct
    contact identifiers surviving that filter, defaulting to 0 for an empty log."

    PRD §3.4: "Two consequences follow directly and are both intended: a log of
    two calls placed to the *same* contact yields a distinct count of 1 and is
    therefore insufficient for a two-call request even though two calls really
    were made, while a log of exactly two calls to *different* contacts yields 2,
    meets the inclusive threshold and is sufficient."

    PRD §3.4: "On acceptance the row denormalizes `alarm_site_id` and
    `monitoring_company_id` from the system and is created in `SUBMITTED`."

    The log names two distinct active callable contacts of the same premises, so
    the frozen distinct count is 2 and, for a `TWO_CALL_ECV` submission, the
    frozen verdict is sufficient.

    Design: Corner/endpoints/dispatch_request_read_returns_the_frozen_ecv_verdict_and_call_attempts
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_PRESENT_UTC, contact_count=2)
    occurred_at = "2026-09-15T03:09:00Z"
    attempts = [
        F.call_attempt(bundle.contact_ids[0], "2026-09-15T03:10:00Z", "NO_ANSWER"),
        F.call_attempt(bundle.contact_ids[1], "2026-09-15T03:11:00Z", "NO_ANSWER"),
    ]
    request_id = X.submit_dispatch_request(
        api,
        bundle,
        bundle.system_id,
        occurred_at,
        call_attempts=attempts,
        idempotency_key="gsm-0915-a",
    )

    request = A.data_of(api.get_dispatch_request(request_id, U.DISPATCH_SUPERVISOR))
    A.assert_entity_envelope(request)
    A.assert_status(request, "SUBMITTED")
    assert request["version"] == 1
    assert request["alarm_system_id"] == bundle.system_id
    assert request["alarm_site_id"] == bundle.site_id
    assert request["monitoring_company_id"] == bundle.company_id
    assert request["alarm_type"] == "BURGLARY"
    assert request["verification_method"] == "TWO_CALL_ECV"
    assert X.parse(request["occurred_at"]) == X.parse(occurred_at)
    assert request["idempotency_key"] == "gsm-0915-a"

    assert request["ecv_sufficient"] is True
    assert request["distinct_ecv_contact_count"] == 2
    assert request["system_permitted_at_occurrence"] is True
    assert request["refusal_reason"] is None
    assert request["validated_at"] is None
    assert request["validated_by_user_id"] is None

    log = request["call_attempts"]
    assert len(log) == 2, f"the frozen log holds both attempts, got {len(log)}"
    assert [entry["site_contact_id"] for entry in log] == [
        bundle.contact_ids[0],
        bundle.contact_ids[1],
    ]
    assert [entry["outcome"] for entry in log] == ["NO_ANSWER", "NO_ANSWER"]


def test_false_alarm_incident_read_returns_the_stored_fee_basis_breakdown(api):
    """Reading a counted incident returns its occurrence index, its assessed fee and the stored audit breakdown of every pricing input.

    PRD §3.5: "In either case the incident's `occurrence_index` is the size of
    the set it belongs to — the incident is already counted at that point, so it
    counts itself — and `counted_window_mode` records which variant produced the
    number."

    PRD §3.5: "Every input to that computation is preserved on the incident as
    `fee_basis`, holding `tier_base_cents`, `occupancy_multiplier`,
    `non_ecv_surcharge_applied` and `unpermitted_multiplier_applied` as booleans
    recording whether each factor differed from 1, `cap_applied`, and
    `aggravation_cents`."

    PRD §3.1: "the default ladder charges nothing for occurrences 1 and 2, 10000
    cents for occurrence 3, 25000 for occurrence 4, 40000 for occurrence 5, and
    75000 for occurrence 6 and everything above it."

    Three chargeable incidents were counted at this commercial premises, so the
    third carries index 3: its marginal tier base is 10000 cents, the commercial
    occupancy multiplier is 1.50, the request was a two-call submission on a
    permitted system so neither the surcharge nor the unpermitted factor applies,
    and 10000 times 1.50 is 15000 cents, well under the 100000-cent cap.

    Design: Corner/endpoints/false_alarm_incident_read_returns_the_stored_fee_basis_breakdown
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2026-09-20T01:00:00Z",
        site_overrides={"occupancy_class": "COMMERCIAL"},
        contact_count=3,
        system_count=3,
    )
    occurrences = ["2026-09-15T03:09:00Z", "2026-09-16T04:00:00Z", "2026-09-17T04:00:00Z"]
    incidents = [
        X.create_counted_incident(api, bundle, bundle.system_ids[index], occurred_at)
        for index, occurred_at in enumerate(occurrences)
    ]

    incident = A.data_of(
        api.get_false_alarm_incident(incidents[2].incident_id, U.HEARING_OFFICER)
    )
    A.assert_entity_envelope(incident)
    A.assert_status(incident, "COUNTED")
    assert incident["determination"] == "COUNTED"
    assert incident["occurrence_index"] == 3
    A.assert_money_cents(incident["assessed_fee_cents"], 15000, "assessed_fee_cents")
    assert incident["counted_window_mode"] == "ROLLING_365"
    assert incident["determined_by_user_id"] == U.REVIEW_OFFICER_ID
    assert X.parse(incident["determined_at"]) == X.parse("2026-09-20T01:00:00Z")
    assert incident["exempt_cause_code"] is None
    assert incident["appeal_count"] == 0
    assert incident["alarm_site_id"] == bundle.site_id
    assert incident["alarm_system_id"] == bundle.system_ids[2]
    assert X.parse(incident["occurred_at"]) == X.parse(occurrences[2])

    A.assert_fee_basis(
        incident["fee_basis"],
        tier_base_cents=10000,
        occupancy_multiplier=1.50,
        non_ecv_surcharge_applied=False,
        unpermitted_multiplier_applied=False,
        aggravation_cents=0,
        cap_applied=False,
    )


def test_site_false_alarm_summary_recomputes_posture_without_bumping_the_version(api):
    """The premises summary recomputes both window variants, the balances and the posture without advancing the premises revision.

    PRD §2.4: "The one documented exception is the read-only false alarm summary
    on a premises: it recomputes and returns the posture and balance figures at
    the current logical clock without persisting a version bump."

    PRD §3.2: "A read-only summary capability returns all of this recomputed at
    the current logical clock — both variant counts, the authoritative count, the
    posture, the outstanding and credit balances and the renewal block flag —
    without persisting a version bump."

    PRD §3.5: "Otherwise, if `chargeable_count_window` is at or above
    `probation_threshold_count`, the posture is `RESPONSE_PROBATION`."

    PRD §3.2: "`renewal_block_active` is true exactly when
    `outstanding_balance_cents` is at or above the schedule's
    `delinquent_balance_block_cents`."

    Four chargeable incidents at this commercial premises price at 0, 0,
    10000 times 1.50 = 15000 and 25000 times 1.50 times 1.20 = 45000 cents, whose
    invoices assess 15750 and 47250 with the five-percent administrative fee; the
    four permit issue invoices add 4 times 5500 = 22000, so the outstanding and
    lifetime totals are both 22000 + 15750 + 47250 = 85000 cents. Four is at the
    inclusive probation threshold and 85000 is above the 50000-cent blocking
    threshold.

    Design: Corner/endpoints/site_false_alarm_summary_recomputes_posture_without_bumping_the_version
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2026-09-20T01:00:00Z",
        site_overrides={"occupancy_class": "COMMERCIAL"},
        contact_count=3,
        system_count=4,
    )
    occurrences = [
        "2026-09-15T03:09:00Z",
        "2026-09-16T04:00:00Z",
        "2026-09-17T04:00:00Z",
        "2026-09-18T04:00:00Z",
    ]
    for index, occurred_at in enumerate(occurrences[:3]):
        X.create_counted_incident(api, bundle, bundle.system_ids[index], occurred_at)
    X.create_counted_incident(
        api,
        bundle,
        bundle.system_ids[3],
        occurrences[3],
        alarm_type="DURESS",
        verification_method="NONE",
        call_attempts=[],
    )

    site_before = X.get_site(api, bundle.site_id)

    summary = A.data_of(api.get_false_alarm_summary(bundle.site_id, U.PROGRAM_ADMIN))
    assert summary["chargeable_count_window"] == 4
    assert summary["chargeable_count_rolling_365"] == 4
    assert summary["chargeable_count_permit_year"] == 4
    A.assert_money_cents(summary["outstanding_balance_cents"], 85000, "outstanding_balance_cents")
    A.assert_money_cents(summary["lifetime_assessed_cents"], 85000, "lifetime_assessed_cents")
    A.assert_money_cents(summary["credit_balance_cents"], 0, "credit_balance_cents")
    assert summary["response_status"] == "RESPONSE_PROBATION"
    assert summary["renewal_block_active"] is True
    assert summary["ecv_callable_contact_count"] == 3
    assert summary["unpermitted_system_count"] == 0

    site_after = X.get_site(api, bundle.site_id)
    A.assert_version_unchanged(site_before, site_after)
    assert site_after["updated_at"] == site_before["updated_at"], (
        "the read-only summary must not refresh the premises updated_at"
    )


def test_hearing_docket_read_returns_the_seat_count_against_capacity(api):
    """Reading a docket that has seated one appeal returns the seat count, the capacity it is measured against and the revision a client must echo back.

    PRD §3.6: "The docket is created in `OPEN` with `scheduled_appeal_count` at 0
    and `held_at` null."

    PRD §3.6: "On success the appeal moves to `SCHEDULED` with its
    `hearing_docket_id` set, and the docket's `scheduled_appeal_count` and
    `version` each rise by 1."

    PRD §3.6: "When the count reaches `capacity` the docket closes itself, `OPEN →
    CLOSED_FOR_SCHEDULING`, and further seating attempts meet
    `ERR_DOCKET_NOT_OPEN`."

    PRD §3.6: "A docket may be read individually — the read is how a client
    learns the `version` it must send back as `expected_hearing_docket_version` —
    or listed with filters on `hearing_officer_user_id`, `status`, and a
    `session_from` / `session_to` window, paged by `page` and `per_page`."

    One of the four seats is taken, so the count is 1 against a capacity of 4 and
    the docket stays `OPEN`; the single seating raised the docket from version 1
    to version 2.

    Design: Corner/endpoints/hearing_docket_read_returns_the_seat_count_against_capacity
    """
    bundle = X.setup_program_baseline(api, clock="2026-09-20T01:00:00Z")
    incident = X.create_counted_incident(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    appeal_id = X.file_appeal(api, bundle, incident.incident_id)
    docket_id = X.create_docket(
        api,
        "2026-10-05T14:00:00Z",
        "2026-10-05T16:00:00Z",
        location="City Hall Room 210",
        capacity=4,
    )
    X.schedule_appeal(api, appeal_id, docket_id)

    docket = A.data_of(api.get_hearing_docket(docket_id, U.PERMIT_CLERK))
    A.assert_entity_envelope(docket)
    A.assert_status(docket, "OPEN")
    assert docket["hearing_officer_user_id"] == U.HEARING_OFFICER_ID
    assert docket["capacity"] == 4
    assert docket["scheduled_appeal_count"] == 1
    assert docket["held_at"] is None
    assert docket["location"] == "City Hall Room 210"
    assert X.parse(docket["session_start"]) == X.parse("2026-10-05T14:00:00Z")
    assert X.parse(docket["session_end"]) == X.parse("2026-10-05T16:00:00Z")
    assert docket["version"] == 2, f"one seating bumps the docket to version 2, got {docket['version']}"


def test_hearing_dockets_list_filtered_by_officer_and_session_window(api):
    """The docket listing filters on the sitting officer, the docket status and a session window whose upper bound excludes the later session.

    PRD §3.6: "A docket may be read individually — the read is how a client
    learns the `version` it must send back as `expected_hearing_docket_version` —
    or listed with filters on `hearing_officer_user_id`, `status`, and a
    `session_from` / `session_to` window, paged by `page` and `per_page`."

    PRD §3.6: "the earliest legal back-to-back start is exactly the existing
    `session_end` plus 15 minutes, since strictness makes that value pass."

    PRD §2.3: "Unless a specific endpoint states otherwise, list results are
    sorted by `created_at` ascending."

    The second session starts at 16:15, exactly the first session's 16:00 end plus
    the 15-minute buffer, so both dockets exist for the same officer. A window
    ending at 16:00 admits only the first; widening the window to the end of the
    day admits both, in creation order.

    Design: Corner/endpoints/hearing_dockets_list_filtered_by_officer_and_session_window
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    first_id = X.create_docket(
        api, "2026-10-05T14:00:00Z", "2026-10-05T16:00:00Z", location="City Hall Room 210"
    )
    second_id = X.create_docket(
        api,
        "2026-10-05T16:15:00Z",
        "2026-10-05T18:15:00Z",
        location="Municipal Court Annex Room 2B",
        headers=U.HEARING_OFFICER,
    )

    narrow = A.single(
        api.list_hearing_dockets(
            U.PROGRAM_ADMIN,
            {
                "hearing_officer_user_id": U.HEARING_OFFICER_ID,
                "session_from": "2026-10-05T00:00:00Z",
                "session_to": "2026-10-05T16:00:00Z",
                "page": 1,
                "per_page": 25,
            },
        )
    )
    assert narrow["id"] == first_id

    wide = A.assert_total_count(
        api.list_hearing_dockets(
            U.PROGRAM_ADMIN,
            {
                "hearing_officer_user_id": U.HEARING_OFFICER_ID,
                "session_from": "2026-10-05T00:00:00Z",
                "session_to": "2026-10-05T23:59:00Z",
                "page": 1,
                "per_page": 25,
            },
        ),
        2,
    )
    assert [row["id"] for row in wide] == [first_id, second_id]

    open_rows = A.assert_total_count(
        api.list_hearing_dockets(U.PROGRAM_ADMIN, {"status": "OPEN", "per_page": 25}), 2
    )
    assert {row["id"] for row in open_rows} == {first_id, second_id}

    cancelled, meta = validate_paginated(
        api.list_hearing_dockets(U.PROGRAM_ADMIN, {"status": "CANCELLED", "per_page": 25})
    )
    assert meta["total_count"] == 0, "no docket has been cancelled"
    assert cancelled == []
    assert meta["has_more"] is False

    _rows, other_meta = validate_paginated(
        api.list_hearing_dockets(
            U.PROGRAM_ADMIN, {"hearing_officer_user_id": "ho-99", "per_page": 25}
        )
    )
    assert other_meta["total_count"] == 0, "another officer's calendar is empty"


def test_appeal_read_returns_the_decision_findings_and_rehearing_depth(api):
    """Reading a decided appeal returns the ruling, its written findings, the deciding officer and the rehearing depth of an original filing.

    PRD §3.6: "An accepted appeal is created in `FILED` with `filed_at` at the
    logical clock, `filed_by_user_id` set from the acting `X-User-ID`,
    `hearing_docket_id` null, `decision`, `decided_at`, `decided_by_user_id` and
    `findings` all null, and `alarm_site_id` denormalized from the incident."

    PRD §3.6: "The new row's `rehearing_depth` is the prior appeal's
    `rehearing_depth` plus 1, and an original appeal has depth 0."

    PRD §3.6: "All three branches record `decision`, `decided_at`,
    `decided_by_user_id` and `findings`, and all three are terminal for the appeal
    row."

    PRD §3.6: "Appeals may be read individually, exposing the `decision`,
    `findings` and `rehearing_depth`, or listed with filters on
    `false_alarm_incident_id`, `alarm_site_id`, `hearing_docket_id`,
    `prior_appeal_id` — which is how a rehearing chain is walked — plus `status`
    and `decision`, again paged by `page` and `per_page`."

    The appeal was filed at 2026-09-20T01:00:00Z and granted at the session start
    of 2026-10-05T14:00:00Z by the docket's own officer; because it is an original
    filing rather than a rehearing, its depth is 0 and `prior_appeal_id` is null.

    Design: Corner/endpoints/appeal_read_returns_the_decision_findings_and_rehearing_depth
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2026-09-20T01:00:00Z",
        site_overrides={"occupancy_class": "COMMERCIAL"},
        contact_count=3,
        system_count=4,
    )
    occurrences = [
        "2026-09-15T03:09:00Z",
        "2026-09-16T04:00:00Z",
        "2026-09-17T04:00:00Z",
        "2026-09-18T04:00:00Z",
    ]
    incidents = [
        X.create_counted_incident(api, bundle, bundle.system_ids[index], occurred_at)
        for index, occurred_at in enumerate(occurrences)
    ]

    appeal_id, docket_id = X.create_heard_appeal(
        api,
        bundle,
        incidents[2].incident_id,
        session_start="2026-10-05T14:00:00Z",
        session_end="2026-10-05T16:00:00Z",
        grounds="WRONG_CAUSE_CODE",
    )
    X.decide_appeal(
        api,
        appeal_id,
        "GRANTED",
        findings="The panel log shows a utility power transient, not an operator error.",
        exempt_cause_code="UTILITY_POWER_FAILURE",
    )

    appeal = A.data_of(api.get_appeal(appeal_id, U.BILLING_CLERK))
    A.assert_entity_envelope(appeal)
    A.assert_status(appeal, "GRANTED")
    assert appeal["decision"] == "GRANTED"
    assert appeal["findings"] == (
        "The panel log shows a utility power transient, not an operator error."
    )
    assert appeal["decided_by_user_id"] == U.HEARING_OFFICER_ID
    assert X.parse(appeal["decided_at"]) == X.parse("2026-10-05T14:00:00Z")
    assert appeal["rehearing_depth"] == 0
    assert appeal["prior_appeal_id"] is None
    assert appeal["grounds"] == "WRONG_CAUSE_CODE"
    assert appeal["false_alarm_incident_id"] == incidents[2].incident_id
    assert appeal["hearing_docket_id"] == docket_id
    assert appeal["alarm_site_id"] == bundle.site_id
    assert appeal["filed_by_user_id"] == bundle.site_id
    assert X.parse(appeal["filed_at"]) == X.parse("2026-09-20T01:00:00Z")


def test_appeals_list_filtered_by_docket_and_status_returns_the_hearing_roster(api):
    """Filtering the appeal listing by docket and status returns the seated roster, and the incident and premises filters find the same row.

    PRD §3.6: "Appeals may be read individually, exposing the `decision`,
    `findings` and `rehearing_depth`, or listed with filters on
    `false_alarm_incident_id`, `alarm_site_id`, `hearing_docket_id`,
    `prior_appeal_id` — which is how a rehearing chain is walked — plus `status`
    and `decision`, again paged by `page` and `per_page`."

    PRD §3.6: "On success the appeal moves to `SCHEDULED` with its
    `hearing_docket_id` set, and the docket's `scheduled_appeal_count` and
    `version` each rise by 1."

    The one appeal in the program has been seated, so the roster filtered to
    `SCHEDULED` holds exactly one row — the same number the docket's own
    `scheduled_appeal_count` reports — and no appeal remains in `FILED`.

    Design: Corner/endpoints/appeals_list_filtered_by_docket_and_status_returns_the_hearing_roster
    """
    bundle = X.setup_program_baseline(api, clock="2026-09-20T01:00:00Z")
    incident = X.create_counted_incident(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    appeal_id = X.file_appeal(api, bundle, incident.incident_id)
    docket_id = X.create_docket(
        api, "2026-10-05T14:00:00Z", "2026-10-05T16:00:00Z", location="City Hall Room 210"
    )
    X.schedule_appeal(api, appeal_id, docket_id)

    seated = A.single(
        api.list_appeals(
            U.HEARING_OFFICER,
            {
                "hearing_docket_id": docket_id,
                "status": "SCHEDULED",
                "page": 1,
                "per_page": 25,
            },
        )
    )
    assert seated["id"] == appeal_id
    assert seated["false_alarm_incident_id"] == incident.incident_id
    assert seated["hearing_docket_id"] == docket_id

    docket = A.data_of(api.get_hearing_docket(docket_id, U.HEARING_OFFICER))
    assert docket["scheduled_appeal_count"] == 1, (
        "the roster length must agree with the docket's own seat count"
    )

    by_incident = A.single(
        api.list_appeals(
            U.HEARING_OFFICER,
            {"false_alarm_incident_id": incident.incident_id, "per_page": 25},
        )
    )
    assert by_incident["id"] == appeal_id

    by_site = A.single(
        api.list_appeals(U.HEARING_OFFICER, {"alarm_site_id": bundle.site_id, "per_page": 25})
    )
    assert by_site["id"] == appeal_id

    _rows, meta = validate_paginated(
        api.list_appeals(
            U.HEARING_OFFICER,
            {"hearing_docket_id": docket_id, "status": "FILED", "per_page": 25},
        )
    )
    assert meta["total_count"] == 0, "the seated appeal has left the unscheduled pool"


def test_penalty_invoice_read_returns_every_money_column_and_its_line_items(api):
    """Reading the permit issue invoice returns each money column, both state dimensions and the single line item behind the subtotal.

    PRD §3.8: "A `PERMIT_ISSUE_FEE` invoice carries one PERMIT_ISSUE line at
    `permit_issue_fee_cents`."

    PRD §3.8: "`admin_fee_cents` is then the subtotal times `admin_fee_pct`,
    rounded half up once on the already-rounded subtotal, and clamped upward to
    `admin_fee_min_cents` and downward to `admin_fee_max_cents`; the clamp binds
    before the fee joins the assessment, so a 200-cent subtotal still carries the
    500-cent floor and a 200000-cent subtotal carries the 5000-cent ceiling."

    PRD §3.8: "`assessed_cents` is `subtotal_cents` plus `admin_fee_cents` plus
    `late_penalty_cents`; `paid_cents` and `adjusted_cents` start at 0;
    `outstanding_cents` is `assessed_cents` minus `paid_cents` minus
    `adjusted_cents`, floored at zero and never negative."

    PRD §3.8: "`issued_on` is the logical clock and `due_on` is `issued_on` plus
    `invoice_due_days` whole days."

    PRD §3.8: "The row records `alarm_site_id` plus exactly one source link:
    `false_alarm_incident_id` when `kind` is `FALSE_ALARM_FEE`, `alarm_permit_id`
    when `kind` is `PERMIT_ISSUE_FEE`, `PERMIT_RENEWAL_FEE` or
    `UNPERMITTED_OPERATION_PENALTY`, `suspension_order_id` when `kind` is
    `REINSTATEMENT_FEE`."

    The subtotal is the 5000-cent issue fee; five percent of that is 250, raised by
    the clamp to the 500-cent floor, so the assessment is 5500 cents and, with
    nothing paid or adjusted, all 5500 is outstanding. Issued at
    2026-08-01T00:00:00Z it falls due 30 whole days later on 2026-08-31.

    Design: Corner/endpoints/penalty_invoice_read_returns_every_money_column_and_its_line_items
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    rows = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")
    assert len(rows) == 1, f"the single approval issued one invoice, got {len(rows)}"

    invoice = A.data_of(api.get_penalty_invoice(rows[0]["id"], bundle.holder_headers))
    A.assert_entity_envelope(invoice)
    assert invoice["kind"] == "PERMIT_ISSUE_FEE"
    assert invoice["alarm_site_id"] == bundle.site_id
    assert invoice["alarm_permit_id"] == bundle.permit_id
    assert invoice["false_alarm_incident_id"] is None
    assert invoice["suspension_order_id"] is None
    assert invoice["invoice_number"], "an issued invoice carries a sequential invoice_number"

    A.assert_invoice_totals(
        invoice,
        subtotal_cents=C.PERMIT_ISSUE_INVOICE_SUBTOTAL_CENTS,
        admin_fee_cents=C.PERMIT_ISSUE_INVOICE_ADMIN_CENTS,
        assessed_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
        paid_cents=0,
        adjusted_cents=0,
        outstanding_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
        payment_status="UNPAID",
        collections_stage="CURRENT",
    )
    A.assert_outstanding_identity(invoice)
    A.assert_money_cents(invoice["late_penalty_cents"], 0, "late_penalty_cents")
    assert invoice["days_delinquent"] == 0
    assert X.parse(invoice["issued_on"]) == X.parse("2026-08-01T00:00:00Z")
    assert X.parse(invoice["due_on"]) == X.parse("2026-08-31T00:00:00Z")

    line_items = invoice["line_items"]
    assert len(line_items) == 1, f"a permit issue invoice carries one line, got {len(line_items)}"
    line = line_items[0]
    assert line["code"] == "PERMIT_ISSUE"
    A.assert_money_cents(line["unit_amount_cents"], 5000, "unit_amount_cents")
    assert line["quantity"] == 1
    A.assert_money_cents(line["extended_cents"], 5000, "extended_cents")


def test_suspension_order_read_returns_the_computed_reinstatement_conditions(api):
    """Reading a served order returns the reinstatement ladder frozen at serve time for a first suspension.

    PRD §3.5: "And when `chargeable_count_window` reaches or exceeds
    `suspension_threshold_count`, an enforcement order is auto-proposed for the
    premises: a suspension order in `PROPOSED` with `basis` of
    `EXCESSIVE_FALSE_ALARMS`, its `triggering_incident_id` set to this incident,
    `effective_from` at the logical clock plus 10 days and `effective_through` at
    30 days after that."

    PRD §3.7: "Writing that prior count as the number of previously lifted
    suspensions: `reinstatement_fee_cents` is `reinstatement_base_fee_cents`
    multiplied by the quantity 1 plus `reinstatement_escalation_pct` times the
    prior count, rounded half up to a whole cent; `probation_days` is 90 whole
    days multiplied by the prior count plus 1; `suspension_sequence` is the prior
    count plus 1; and `required_conditions` is fixed as an object with
    `inspection_required` true, `ecv_attestation_required` true,
    `min_ecv_contacts` equal to 2 plus the prior count, and
    `invoices_paid_required` true."

    PRD §3.7: "With the base fee at 60000 cents and the escalation at 0.5, a first
    suspension carries a 60000-cent reinstatement fee with 90 probation days and 2
    callable contacts required, a second carries 90000 cents with 180 days and 3
    contacts, a third 120000 cents with 270 days and 4 contacts."

    The sixth chargeable incident reaches the inclusive suspension threshold, so an
    order is proposed effective 2026-09-30T01:00:00Z through 2026-10-30T01:00:00Z.
    The premises has never had a suspension lifted, so the prior count is 0: the
    fee is 60000 times 1, probation is 90 times 1 days, the sequence is 1 and two
    callable contacts are required.

    Design: Corner/endpoints/suspension_order_read_returns_the_computed_reinstatement_conditions
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2026-09-20T01:00:00Z",
        site_overrides={"occupancy_class": "COMMERCIAL"},
        contact_count=3,
        system_count=6,
    )
    occurrences = [
        "2026-09-15T03:09:00Z",
        "2026-09-16T04:00:00Z",
        "2026-09-17T04:00:00Z",
        "2026-09-18T04:00:00Z",
        "2026-09-19T04:00:00Z",
        "2026-09-19T05:00:00Z",
    ]
    incidents = [
        X.create_counted_incident(api, bundle, bundle.system_ids[index], occurred_at)
        for index, occurred_at in enumerate(occurrences)
    ]

    proposed = [row for row in X.orders_of_site(api, bundle.site_id) if row["status"] == "PROPOSED"]
    assert len(proposed) == 1, f"the threshold auto-proposes one order, got {len(proposed)}"
    order_id = proposed[0]["id"]
    validate_success(api.serve_suspension_order(order_id, U.PERMIT_CLERK))

    order = A.data_of(api.get_suspension_order(order_id, U.DISPATCH_SUPERVISOR))
    A.assert_entity_envelope(order)
    A.assert_status(order, "EFFECTIVE")
    assert order["basis"] == "EXCESSIVE_FALSE_ALARMS"
    assert order["alarm_site_id"] == bundle.site_id
    assert order["triggering_incident_id"] == incidents[5].incident_id
    assert X.parse(order["served_at"]) == X.parse("2026-09-20T01:00:00Z")
    assert X.parse(order["effective_from"]) == X.parse("2026-09-30T01:00:00Z")
    assert X.parse(order["effective_through"]) == X.parse("2026-10-30T01:00:00Z")

    A.assert_money_cents(order["reinstatement_fee_cents"], 60000, "reinstatement_fee_cents")
    assert order["probation_days"] == 90
    assert order["suspension_sequence"] == 1

    conditions = order["required_conditions"]
    assert conditions["inspection_required"] is True
    assert conditions["ecv_attestation_required"] is True
    assert conditions["min_ecv_contacts"] == 2
    assert conditions["invoices_paid_required"] is True

    assert order["reinstatement_requested_at"] is None
    assert order["technician_inspection_date"] is None
    assert order["ecv_attestation"] is None
    assert order["lifted_at"] is None
    assert order["vacated_reason"] is None


def test_payment_records_list_filtered_by_site_and_method(api):
    """Filtering the payment listing by premises and tender method returns the one posted receipt, while a different method and a later window return nothing.

    PRD §3.9: "The accepted payment is created in `APPLIED` with the next
    sequential `receipt_number` in the form RCT-000001 and `recorded_by_user_id`
    taken from the acting `X-User-ID` — that stamp is what later bars the same
    person from adjusting the invoice they collected on."

    PRD §3.9: "Whatever remains after every candidate is exhausted becomes the
    payment's `credited_cents` and is added to the premises' `credit_balance_cents`;
    `allocated_cents` is the tendered amount minus that credit."

    PRD §3.9: "A payment may be read individually, showing its `allocated_cents`
    and `credited_cents`, or listed with filters on `alarm_site_id`, `status`,
    `method` and a `tendered_from` / `tendered_to` window, paged by `page` and
    `per_page`."

    The premises owes exactly the 5500-cent permit issue invoice and 5500 cents were
    tendered by card, so the waterfall allocates all 5500 and parks no credit. The
    tender is dated 2026-08-01, so a window opening on 2026-08-02 excludes it.

    Design: Corner/endpoints/payment_records_list_filtered_by_site_and_method
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    payment_id = X.post_payment(
        api, bundle, 5500, "2026-08-01T00:00:00Z", method="CARD", allocation_mode="AUTO_WATERFALL"
    )

    row = A.single(
        api.list_payment_records(
            U.BILLING_CLERK,
            {"alarm_site_id": bundle.site_id, "method": "CARD", "page": 1, "per_page": 25},
        )
    )
    assert row["id"] == payment_id
    A.assert_status(row, "APPLIED")
    assert row["method"] == "CARD"
    assert row["allocation_mode"] == "AUTO_WATERFALL"
    assert row["recorded_by_user_id"] == U.BILLING_CLERK_ID
    assert row["receipt_number"], "an applied payment carries a sequential receipt_number"
    A.assert_money_cents(row["amount_cents"], 5500, "amount_cents")
    A.assert_money_cents(row["allocated_cents"], 5500, "allocated_cents")
    A.assert_money_cents(row["credited_cents"], 0, "credited_cents")
    A.assert_cash_conservation(row)

    _ach, ach_meta = validate_paginated(
        api.list_payment_records(
            U.BILLING_CLERK,
            {"alarm_site_id": bundle.site_id, "method": "ACH", "page": 1, "per_page": 25},
        )
    )
    assert ach_meta["total_count"] == 0, "nothing was tendered by ACH"
    assert ach_meta["has_more"] is False

    _later, later_meta = validate_paginated(
        api.list_payment_records(
            U.BILLING_CLERK,
            {
                "alarm_site_id": bundle.site_id,
                "tendered_from": "2026-08-02T00:00:00Z",
                "per_page": 25,
            },
        )
    )
    assert later_meta["total_count"] == 0, "the tender predates the window"

    applied = A.single(
        api.list_payment_records(
            U.BILLING_CLERK,
            {"alarm_site_id": bundle.site_id, "status": "APPLIED", "per_page": 25},
        )
    )
    assert applied["id"] == payment_id


def test_compliance_report_read_returns_all_five_scored_metrics(api):
    """Reading an accepted compliance report returns the city's own count and all five derived metrics at their declared precisions.

    PRD §3.10: "`system_dispatch_count` is the number of dispatch requests
    attributed to that company whose `occurred_at` falls inside the closed period
    interval and whose status is not `CANCELLED` — a `REFUSED` request still
    counts, because the company did ask for dispatch even though the city declined,
    and only a cancellation removes the ask."

    PRD §3.10: "`variance_pct` is that count divided by the greater of 1 and
    `system_dispatch_count`, at four decimal places."

    PRD §3.10: "`period_ecv_rate` is the lesser of 1 and `ecv_attempt_count`
    divided by the greater of 1 and `reported_dispatch_count`, at four decimal
    places, so extra verification attempts earn no credit above a rate of 1."

    PRD §3.10: "`period_score` is 0.6 times `period_accuracy` plus 0.4 times
    `period_ecv_rate`, rounded half up to two decimal places."

    PRD §3.10: "Acceptance moves the report to the terminal `ACCEPTED`, stamping
    `reviewed_at` and `reviewed_by_user_id`, admitting the `period_score` into the
    company's score set, and resetting `consecutive_flagged_report_count`."

    One request was lodged inside the period and one was claimed, so the variance
    count is 0 and `variance_pct` is 0 divided by 1, that is 0.0000; accuracy is 1
    minus 0, that is 1.0000; the ECV rate is the lesser of 1 and 2 divided by 1,
    clipped to 1.0000; and the score is 0.6 plus 0.4, that is 1.00.

    Design: Corner/endpoints/compliance_report_read_returns_all_five_scored_metrics
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_PRESENT_UTC)
    X.submit_dispatch_request(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    X.set_clock(api, "2026-09-30T00:00:00Z")
    report_id = X.submit_compliance_report(
        api,
        bundle,
        "2026-09-01T00:00:00Z",
        "2026-09-30T00:00:00Z",
        reported_dispatch_count=1,
        reported_cancellation_count=0,
        ecv_attempt_count=2,
    )
    X.review_compliance_report(api, report_id, "ACCEPT", variance_notes="Counts reconcile exactly.")

    report = A.data_of(api.get_compliance_report(report_id, bundle.operator_headers))
    A.assert_entity_envelope(report)
    A.assert_status(report, "ACCEPTED")
    assert report["monitoring_company_id"] == bundle.company_id
    assert X.parse(report["period_start"]) == X.parse("2026-09-01T00:00:00Z")
    assert X.parse(report["period_end"]) == X.parse("2026-09-30T00:00:00Z")
    assert report["reported_dispatch_count"] == 1
    assert report["reported_cancellation_count"] == 0
    assert report["ecv_attempt_count"] == 2
    assert report["system_dispatch_count"] == 1
    assert report["variance_count"] == 0
    A.assert_ratio_4dp(report["variance_pct"], 0.0000, "variance_pct")
    A.assert_ratio_4dp(report["period_accuracy"], 1.0000, "period_accuracy")
    A.assert_ratio_4dp(report["period_ecv_rate"], 1.0000, "period_ecv_rate")
    A.assert_score_2dp(report["period_score"], 1.00, "period_score")
    assert report["correction_count"] == 0
    assert report["reviewed_by_user_id"] == U.REVIEW_OFFICER_ID
    assert X.parse(report["reviewed_at"]) == X.parse("2026-09-30T00:00:00Z")


def test_compliance_reports_list_filtered_by_company_and_status(api):
    """Filtering the report listing by company and status separates the flagged period from the accepted one, and the period window selects only the later month.

    PRD §3.10: "A report may be read individually, exposing its computed variance
    and `period_score`, or listed with filters on `monitoring_company_id`,
    `status` and a `period_from` / `period_to` window, paged by `page` and
    `per_page`."

    PRD §3.10: "Flagging requires an actual discrepancy — `variance_pct` must be
    strictly above 0.1000, else `ERR_NO_REPORTABLE_VARIANCE` — and moves the report
    to `VARIANCE_FLAGGED`, storing the `variance_notes` and incrementing
    `consecutive_flagged_report_count`."

    PRD §2.3: "Unless a specific endpoint states otherwise, list results are
    sorted by `created_at` ascending."

    The August period claims three dispatches against a month with none on record,
    so its `variance_pct` is 3 divided by the greater of 1 and 0, that is 3.0000 —
    strictly above the 0.1000 floor — and it can be flagged, while the September
    period reconciles exactly and is accepted.

    Design: Corner/endpoints/compliance_reports_list_filtered_by_company_and_status
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_PRESENT_UTC)
    X.submit_dispatch_request(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    X.set_clock(api, "2026-09-30T00:00:00Z")

    august_id = X.submit_compliance_report(
        api,
        bundle,
        "2026-08-01T00:00:00Z",
        "2026-08-31T00:00:00Z",
        reported_dispatch_count=3,
        reported_cancellation_count=0,
        ecv_attempt_count=0,
    )
    september_id = X.submit_compliance_report(
        api,
        bundle,
        "2026-09-01T00:00:00Z",
        "2026-09-30T00:00:00Z",
        reported_dispatch_count=1,
        reported_cancellation_count=0,
        ecv_attempt_count=2,
    )
    X.review_compliance_report(api, september_id, "ACCEPT", variance_notes="Counts reconcile exactly.")
    X.review_compliance_report(
        api,
        august_id,
        "FLAG_VARIANCE",
        variance_notes="Three dispatches reported for a month with none on record.",
    )

    flagged = A.single(
        api.list_compliance_reports(
            U.REVIEW_OFFICER,
            {
                "monitoring_company_id": bundle.company_id,
                "status": "VARIANCE_FLAGGED",
                "page": 1,
                "per_page": 25,
            },
        )
    )
    assert flagged["id"] == august_id
    assert X.parse(flagged["period_start"]) == X.parse("2026-08-01T00:00:00Z")
    A.assert_ratio_4dp(flagged["variance_pct"], 3.0000, "variance_pct")

    accepted = A.single(
        api.list_compliance_reports(
            U.REVIEW_OFFICER,
            {
                "monitoring_company_id": bundle.company_id,
                "status": "ACCEPTED",
                "page": 1,
                "per_page": 25,
            },
        )
    )
    assert accepted["id"] == september_id

    both = A.assert_total_count(
        api.list_compliance_reports(
            U.REVIEW_OFFICER,
            {"monitoring_company_id": bundle.company_id, "page": 1, "per_page": 25},
        ),
        2,
    )
    assert [row["id"] for row in both] == [august_id, september_id]

    windowed = A.single(
        api.list_compliance_reports(
            U.REVIEW_OFFICER,
            {
                "monitoring_company_id": bundle.company_id,
                "period_from": "2026-09-01T00:00:00Z",
                "per_page": 25,
            },
        )
    )
    assert windowed["id"] == september_id


def test_reject_registration_drives_the_system_into_its_terminal_rejected_state(api):
    """Rejecting a registration lands the system in a terminal state with no permit, no money and no further action possible.

    PRD §3.3: "Rejection is the sibling branch out of `SUBMITTED`. A clerk supplies
    `rejection_reason`, the row moves `SUBMITTED → REJECTED` — a terminal state —
    the reason is stored on `rejection_reason`, and the monitoring company's
    `monitored_system_count` is decremented. The system's `version` is bumped by 1.
    No permit is created, no money is assessed and no premises counter changes."

    PRD §2.10: "This covers every state machine in the program — alarm systems,
    permits, dispatch requests, incidents, hearing dockets, appeals, suspension
    orders, both invoice dimensions, monitoring companies and compliance reports —
    and any attempt to act on a resource already in a terminal state fails here
    with `ERR_INVALID_STATE`."

    Nothing was ever approved at this premises, so both the outstanding balance and
    the lifetime assessment stay at 0 and no permit row exists for the system.

    Design: Corner/endpoints/reject_registration_drives_the_system_into_its_terminal_rejected_state
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    company_id = X.create_company(api)
    site_id = X.create_site(api)
    X.create_contacts(api, site_id, 2)
    system_id = X.create_submitted_system(api, site_id, company_id)

    system = A.data_of(
        api.reject_registration(
            system_id,
            {"rejection_reason": "Panel model is not on the approved equipment list."},
            U.PERMIT_CLERK,
        )
    )
    A.assert_status(system, "REJECTED")
    assert system["rejection_reason"] == (
        "Panel model is not on the approved equipment list."
    )
    assert system["permitted_at"] is None
    assert system["version"] == 2, f"rejection bumps the system to version 2, got {system['version']}"

    _permits, permit_meta = validate_paginated(
        api.list_alarm_permits(U.PERMIT_CLERK, {"alarm_system_id": system_id, "per_page": 25})
    )
    assert permit_meta["total_count"] == 0, "a rejected registration issues no permit"

    site = X.get_site(api, site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 0, "outstanding_balance_cents")
    A.assert_money_cents(site["lifetime_assessed_cents"], 0, "lifetime_assessed_cents")

    company = X.get_company(api, company_id)
    assert company["monitored_system_count"] == 0

    validate_error(
        api.approve_registration(system_id, U.PERMIT_CLERK),
        E.ERR_INVALID_STATE,
        expected_status=409,
    )


def test_dispatch_request_refuse_is_a_conditional_action_out_of_submitted(api):
    """Refusing a submitted request stores the coded reason, closes the row terminally and bars any incident from ever citing it.

    PRD §3.4: "The sibling branch is refusal: the supervisor supplies a coded
    `refusal_reason` of `ECV_DEFICIENT`, `RESPONSE_SUSPENDED`,
    `VERIFIED_RESPONSE_MISSING` or `DUPLICATE_SIGNAL`, the row moves `SUBMITTED →
    REFUSED` (terminal), the reason is stored, and no incident may ever reference
    that request."

    PRD §2.10: "This covers every state machine in the program — alarm systems,
    permits, dispatch requests, incidents, hearing dockets, appeals, suspension
    orders, both invoice dimensions, monitoring companies and compliance reports —
    and any attempt to act on a resource already in a terminal state fails here
    with `ERR_INVALID_STATE`."

    Refusal is the only write the row takes, so its revision rises from 1 to 2 and
    the validation stamps stay null; because no incident can be opened, the
    premises' chargeable window count stays at 0.

    Design: Corner/endpoints/dispatch_request_refuse_is_a_conditional_action_out_of_submitted
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_PRESENT_UTC)
    request_id = X.submit_dispatch_request(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")

    request = A.data_of(
        api.refuse_dispatch_request(
            request_id, {"refusal_reason": "DUPLICATE_SIGNAL"}, U.DISPATCH_SUPERVISOR
        )
    )
    A.assert_status(request, "REFUSED")
    assert request["refusal_reason"] == "DUPLICATE_SIGNAL"
    assert request["validated_at"] is None
    assert request["validated_by_user_id"] is None
    assert request["dispatched_at"] is None
    assert request["version"] == 2, f"refusal bumps the request to version 2, got {request['version']}"

    validate_error(
        api.create_false_alarm_incident(
            F.false_alarm_incident_payload(request_id), U.DISPATCH_SUPERVISOR
        ),
        E.ERR_INVALID_STATE,
        expected_status=409,
    )
    validate_error(
        api.refuse_dispatch_request(
            request_id, {"refusal_reason": "ECV_DEFICIENT"}, U.DISPATCH_SUPERVISOR
        ),
        E.ERR_INVALID_STATE,
        expected_status=409,
    )
    validate_error(
        api.validate_dispatch_request(request_id, U.DISPATCH_SUPERVISOR),
        E.ERR_INVALID_STATE,
        expected_status=409,
    )

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 0, "a refused request never becomes a false alarm"


def test_dispatch_request_close_valid_ends_a_genuine_alarm_with_no_incident(api):
    """Closing a dispatched request as a genuine alarm ends it terminally, charges nothing and counts nothing.

    PRD §3.4: "Closing the request as a genuine alarm, with optional
    `closing_notes`, moves `DISPATCHED → CLOSED_VALID` (terminal) and records a
    verified alarm — no fee, no counting; it is refused with
    `ERR_INCIDENT_ALREADY_REPORTED` if an incident already references the request."

    PRD §3.4: "Dispatch requests are listable and readable by the whole program
    staff, filterable by system, premises, monitoring company and status, and by
    occurrence window through `occurred_from` and `occurred_to`."

    PRD §3.5: "Otherwise it is `RESPONSE_ACTIVE`."

    The dispatch was recorded while the clock read 2026-09-15T04:00:00Z and that
    stamp survives the closure. No incident exists, so the window count stays 0 and
    the premises keeps its active posture; the only money ever assessed is the
    5500-cent permit issue invoice.

    Design: Corner/endpoints/dispatch_request_close_valid_ends_a_genuine_alarm_with_no_incident
    """
    bundle = X.setup_program_baseline(api, clock="2026-09-15T04:00:00Z")
    request_id = X.create_dispatched_request(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")

    request = A.data_of(
        api.close_valid_dispatch_request(
            request_id,
            U.DISPATCH_SUPERVISOR,
            {"closing_notes": "Forced rear door and property missing; genuine burglary."},
        )
    )
    A.assert_status(request, "CLOSED_VALID")
    assert X.parse(request["dispatched_at"]) == X.parse("2026-09-15T04:00:00Z")

    _incidents, incident_meta = validate_paginated(
        api.list_false_alarm_incidents(
            U.REVIEW_OFFICER, {"dispatch_request_id": request_id, "per_page": 25}
        )
    )
    assert incident_meta["total_count"] == 0, "a genuine alarm opens no incident"

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 0
    assert site["response_status"] == "RESPONSE_ACTIVE"
    A.assert_money_cents(
        site["lifetime_assessed_cents"],
        C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
        "lifetime_assessed_cents",
    )

    validate_error(
        api.create_false_alarm_incident(
            F.false_alarm_incident_payload(request_id), U.DISPATCH_SUPERVISOR
        ),
        E.ERR_INVALID_STATE,
        expected_status=409,
    )


def test_hearing_docket_cancel_releases_its_scheduled_appeal_back_to_filed(api):
    """Cancelling a docket returns its seated appeal to the unscheduled pool, zeroes the seat count and releases the session interval.

    PRD §3.6: "Cancelling a docket is likewise available symmetrically from `OPEN`
    or `CLOSED_FOR_SCHEDULING`, takes an optional `cancellation_reason`, and lands
    in the terminal `CANCELLED`."

    PRD §3.6: "Its consequences cascade downward: every appeal seated on it in
    `SCHEDULED` reverts to `FILED` with `hearing_docket_id` cleared, returning to
    the unscheduled pool to await a new session; `scheduled_appeal_count` is reset
    to 0; the session's interval is released for overlap purposes; and `version`
    rises by 1."

    PRD §3.6: "A proposed session is compared against that officer's existing
    dockets in `OPEN`, `CLOSED_FOR_SCHEDULING` or `HELD` — a `CANCELLED` docket
    releases its interval and is ignored — and rejected with
    `ERR_DOCKET_SESSION_OVERLAP` if a conflict is found."

    Because the interval is released, the very same officer may immediately open a
    replacement session over exactly the same two hours; the contested incident
    stays in `APPEALED` because the appeal itself is still live, merely unseated.

    Design: Corner/endpoints/hearing_docket_cancel_releases_its_scheduled_appeal_back_to_filed
    """
    bundle = X.setup_program_baseline(api, clock="2026-09-20T01:00:00Z")
    incident = X.create_counted_incident(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    appeal_id = X.file_appeal(api, bundle, incident.incident_id)
    docket_id = X.create_docket(
        api, "2026-10-05T14:00:00Z", "2026-10-05T16:00:00Z", location="City Hall Room 210"
    )
    X.schedule_appeal(api, appeal_id, docket_id)

    docket = A.data_of(
        api.cancel_docket(
            docket_id,
            {"cancellation_reason": "Hearing officer reassigned to a county matter."},
            U.HEARING_OFFICER,
        )
    )
    A.assert_status(docket, "CANCELLED")
    assert docket["scheduled_appeal_count"] == 0
    assert docket["held_at"] is None

    appeal = X.get_appeal(api, appeal_id)
    A.assert_status(appeal, "FILED")
    assert appeal["hearing_docket_id"] is None
    assert appeal["decision"] is None

    released = X.get_incident(api, incident.incident_id)
    A.assert_status(released, "APPEALED")

    replacement = A.data_of(
        api.create_hearing_docket(
            F.hearing_docket_payload(
                U.HEARING_OFFICER_ID,
                "2026-10-05T14:00:00Z",
                "2026-10-05T16:00:00Z",
                location="City Hall Room 210",
            ),
            U.PROGRAM_ADMIN,
        ),
        201,
    )
    A.assert_status(replacement, "OPEN")
    assert replacement["id"] != docket_id


def test_appeal_withdraw_frees_a_seat_and_reopens_the_closed_docket(api):
    """Withdrawing a seated appeal frees its seat, reopens the docket that capacity had closed and returns the incident to counted.

    PRD §3.6: "When the count reaches `capacity` the docket closes itself, `OPEN →
    CLOSED_FOR_SCHEDULING`, and further seating attempts meet
    `ERR_DOCKET_NOT_OPEN`."

    PRD §3.6: "Withdrawal from either state returns the incident from `APPEALED` to
    `COUNTED` and resumes dunning on its invoice; withdrawal from `SCHEDULED`
    additionally decrements the docket's `scheduled_appeal_count`, and if that
    docket was `CLOSED_FOR_SCHEDULING` the freed seat reopens it,
    `CLOSED_FOR_SCHEDULING → OPEN`."

    PRD §3.6: "A permit holder may also give up a seat voluntarily: withdrawal is
    available from `FILED` or `SCHEDULED`, takes an optional `withdrawal_reason`,
    and may only be exercised by the appellant — the acting `X-User-ID` must equal
    the appeal's `alarm_site_id`, else `ERR_NOT_RESOURCE_OWNER`."

    All four seats of the session were taken, so the docket had closed itself;
    releasing one seat leaves 3 of 4 filled and the docket open again. The withdrawn
    appeal's incident keeps the index 4 and the 45000-cent fee it carried before the
    appeal, because withdrawal is not a ruling.

    Design: Corner/endpoints/appeal_withdraw_frees_a_seat_and_reopens_the_closed_docket
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2026-09-20T01:00:00Z",
        site_overrides={"occupancy_class": "COMMERCIAL"},
        contact_count=3,
        system_count=4,
    )
    occurrences = [
        "2026-09-15T03:09:00Z",
        "2026-09-16T04:00:00Z",
        "2026-09-17T04:00:00Z",
    ]
    incidents = [
        X.create_counted_incident(api, bundle, bundle.system_ids[index], occurred_at)
        for index, occurred_at in enumerate(occurrences)
    ]
    incidents.append(
        X.create_counted_incident(
            api,
            bundle,
            bundle.system_ids[3],
            "2026-09-18T04:00:00Z",
            alarm_type="DURESS",
            verification_method="NONE",
            call_attempts=[],
        )
    )

    docket_id = X.create_docket(
        api,
        "2026-10-05T14:00:00Z",
        "2026-10-05T16:00:00Z",
        location="City Hall Room 210",
        capacity=4,
    )
    appeal_ids = [X.file_appeal(api, bundle, incident.incident_id) for incident in incidents]
    for appeal_id in appeal_ids:
        X.schedule_appeal(api, appeal_id, docket_id)

    closed = A.data_of(api.get_hearing_docket(docket_id, U.HEARING_OFFICER))
    A.assert_status(closed, "CLOSED_FOR_SCHEDULING")
    assert closed["scheduled_appeal_count"] == 4

    withdrawn = A.data_of(
        api.withdraw_appeal(
            appeal_ids[3],
            bundle.holder_headers,
            {"withdrawal_reason": "Owner accepts the duress-panel finding."},
        )
    )
    A.assert_status(withdrawn, "WITHDRAWN")
    # PRD §3.6 clears `hearing_docket_id` only on docket *cancellation*; the
    # withdrawal paragraph names the seat decrement and the reopen but says
    # nothing about the seated docket reference, so it is not asserted here.
    assert withdrawn["decision"] is None

    reopened = A.data_of(api.get_hearing_docket(docket_id, U.HEARING_OFFICER))
    A.assert_status(reopened, "OPEN")
    assert reopened["scheduled_appeal_count"] == 3

    restored = X.get_incident(api, incidents[3].incident_id)
    A.assert_status(restored, "COUNTED")
    assert restored["occurrence_index"] == 4
    A.assert_money_cents(restored["assessed_fee_cents"], 45000, "assessed_fee_cents")

    for appeal_id in appeal_ids[:3]:
        still_seated = X.get_appeal(api, appeal_id)
        A.assert_status(still_seated, "SCHEDULED")
        assert still_seated["hearing_docket_id"] == docket_id


def test_suspension_order_vacate_voids_the_reinstatement_fee_invoice(api):
    """Vacating a served order voids its reinstatement invoice, leaves the escalation ladder untouched and restores the probation posture.

    PRD §3.7: "It is reachable from `PROPOSED`, `EFFECTIVE` or
    `REINSTATEMENT_PENDING` and lands in the terminal `VACATED`."

    PRD §3.7: "From `EFFECTIVE` or `REINSTATEMENT_PENDING` the `REINSTATEMENT_FEE`
    invoice carrying that `suspension_order_id` is voided and its allocations
    reversed into the premises' `credit_balance_cents`."

    PRD §3.7: "In neither case is `lifted_suspension_count` incremented: a vacated
    order never counted as a suspension at all."

    PRD §3.5: "Orders in `VACATED` or `EXPIRED` are ignored entirely, and a premises
    with no pinned schedule is `RESPONSE_ACTIVE`."

    Before the vacatur the premises owes 6 permit issue invoices at 5500 plus the
    false alarm invoices 15750, 47250, 63000 and 105000 plus the 63000-cent
    reinstatement invoice, that is 327000 cents. Voiding the reinstatement invoice
    removes its 63000 from both the invoice and the roll-up, leaving 264000. No
    payment was ever posted, so nothing lands in credit.

    Design: Corner/endpoints/suspension_order_vacate_voids_the_reinstatement_fee_invoice
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2026-09-20T01:00:00Z",
        site_overrides={"occupancy_class": "COMMERCIAL"},
        contact_count=3,
        system_count=6,
    )
    occurrences = [
        "2026-09-15T03:09:00Z",
        "2026-09-16T04:00:00Z",
        "2026-09-17T04:00:00Z",
    ]
    for index, occurred_at in enumerate(occurrences):
        X.create_counted_incident(api, bundle, bundle.system_ids[index], occurred_at)
    X.create_counted_incident(
        api,
        bundle,
        bundle.system_ids[3],
        "2026-09-18T04:00:00Z",
        alarm_type="DURESS",
        verification_method="NONE",
        call_attempts=[],
    )
    X.create_counted_incident(api, bundle, bundle.system_ids[4], "2026-09-19T04:00:00Z")
    X.create_counted_incident(api, bundle, bundle.system_ids[5], "2026-09-19T05:00:00Z")

    proposed = [row for row in X.orders_of_site(api, bundle.site_id) if row["status"] == "PROPOSED"]
    assert len(proposed) == 1, f"the threshold auto-proposes one order, got {len(proposed)}"
    order_id = proposed[0]["id"]
    validate_success(api.serve_suspension_order(order_id, U.PERMIT_CLERK))

    before = X.get_site(api, bundle.site_id)
    A.assert_money_cents(before["outstanding_balance_cents"], 327000, "outstanding_balance_cents")

    order = A.data_of(
        api.vacate_suspension_order(
            order_id,
            {"vacated_reason": "Order issued against the wrong premises record."},
            U.PROGRAM_ADMIN,
        )
    )
    A.assert_status(order, "VACATED")
    assert order["vacated_reason"] == "Order issued against the wrong premises record."
    assert order["lifted_at"] is None

    reinstatement = X.invoices_of_site(api, bundle.site_id, kind="REINSTATEMENT_FEE")
    assert len(reinstatement) == 1, f"serving issued one reinstatement invoice, got {len(reinstatement)}"
    A.assert_invoice_totals(
        reinstatement[0], assessed_cents=63000, outstanding_cents=0, payment_status="VOIDED"
    )

    after = X.get_site(api, bundle.site_id)
    A.assert_money_cents(after["outstanding_balance_cents"], 264000, "outstanding_balance_cents")
    A.assert_money_cents(after["credit_balance_cents"], 0, "credit_balance_cents")
    assert after["lifted_suspension_count"] == 0
    assert after["response_status"] == "RESPONSE_PROBATION"


def test_nightly_run_advances_every_delinquent_invoice_in_one_call(api):
    """One nightly pass adds the late penalty to both overdue invoices and advances both dunning stages, and a second pass at the same instant changes nothing.

    PRD §3.8: "`days_delinquent` is the whole days between `due_on` and the logical
    clock, floored at zero."

    PRD §3.8: "The nightly run advances `CURRENT → NOTICE` once `days_delinquent` is
    at least 1, and `NOTICE → FINAL_NOTICE` once it is at least 30; both steps
    require `outstanding_cents` above zero and require that the linked incident,
    when there is one, is not in `APPEALED`."

    PRD §3.8: "Step two: `late_penalty_cents` is that principal times
    `late_penalty_pct`, rounded half up, and is added into `assessed_cents` — once
    per invoice, never twice."

    PRD §2.6: "Because the run is idempotent with respect to money — the late
    penalty is applied at most once per invoice — running it twice on the same
    logical instant does not double-charge anyone."

    Both permit issue invoices were issued on 2026-08-01 and fell due 30 days later
    on 2026-08-31; at a clock of 2026-09-05 each is 5 whole days delinquent, which
    is at least 1 but under 30, so each takes one stage step to `NOTICE`. The
    penalty is 5500 times 0.10, that is 550, lifting each assessment to 6050 and the
    premises' balance to 2 times 6050, that is 12100 cents.

    Design: Corner/endpoints/nightly_run_advances_every_delinquent_invoice_in_one_call
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC, system_count=2)
    before_rows = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")
    assert len(before_rows) == 2, f"two approvals issued two invoices, got {len(before_rows)}"
    before_by_id = {row["id"]: row for row in before_rows}
    for row in before_rows:
        A.assert_invoice_totals(row, collections_stage="CURRENT", assessed_cents=5500)

    X.set_clock(api, "2026-09-05T00:00:00Z")
    validate_success(api.run_nightly(U.PROGRAM_ADMIN))

    first_pass = {}
    for invoice_id in before_by_id:
        invoice = X.get_invoice(api, invoice_id)
        A.assert_invoice_totals(
            invoice,
            subtotal_cents=5000,
            admin_fee_cents=500,
            assessed_cents=6050,
            paid_cents=0,
            adjusted_cents=0,
            outstanding_cents=6050,
            payment_status="UNPAID",
            collections_stage="NOTICE",
        )
        A.assert_money_cents(invoice["late_penalty_cents"], 550, "late_penalty_cents")
        assert invoice["days_delinquent"] == 5
        assert invoice["version"] == before_by_id[invoice_id]["version"] + 1, (
            "the nightly run bumps each mutated invoice by exactly one revision"
        )
        first_pass[invoice_id] = invoice

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 12100, "outstanding_balance_cents")
    A.assert_money_cents(site["lifetime_assessed_cents"], 12100, "lifetime_assessed_cents")

    for permit_id in bundle.permit_ids:
        A.assert_status(X.get_permit(api, permit_id), "ACTIVE")
    for system_id in bundle.system_ids:
        A.assert_status(X.get_system(api, system_id), "PERMITTED")

    validate_success(api.run_nightly(U.PROGRAM_ADMIN))
    for invoice_id, snapshot in first_pass.items():
        again = X.get_invoice(api, invoice_id)
        for field in (
            "assessed_cents",
            "late_penalty_cents",
            "outstanding_cents",
            "days_delinquent",
            "collections_stage",
            "payment_status",
            "version",
        ):
            assert again[field] == snapshot[field], (
                f"a second run at the same instant must not move {field}: "
                f"{snapshot[field]} became {again[field]}"
            )


def test_clock_set_moves_time_without_recomputing_any_entity(api):
    """Setting the clock a year forward returns an empty body and ages nothing; only the nightly run afterwards moves the permit into grace.

    PRD §2.6: "Moving the clock recomputes nothing on its own: no permit ages, no
    invoice escalates and no suspension expires merely because the clock advanced."

    PRD §2.6: "It moves each permit whose term end is within 30 days into its
    renewable state, moves an unrenewed permit past its term end into grace, and
    expires a permit that has outrun its grace window — which in turn drives the
    unpermitted cascade described in §3.3."

    PRD §2.2: "For 2xx responses with no data, it contains an empty object."

    PRD §2.4: "Any operation that recomputes a derived counter on a parent — a
    premises roll-up, a docket seat count, a company counter — is a mutation of that
    parent and therefore refreshes its `updated_at` and bumps its `version`."

    The permit runs from 2026-08-01 to 2027-08-01 with grace through 2027-08-31, so
    a clock of 2027-08-16 sits past the term end and inside the grace window; even
    so the permit stays `ACTIVE` at version 1 until the batch runs, and the premises
    still shows only the 5500 cents assessed at issuance.

    Design: Corner/endpoints/clock_set_moves_time_without_recomputing_any_entity
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    permit_before = X.get_permit(api, bundle.permit_id)
    site_before = X.get_site(api, bundle.site_id)
    A.assert_status(permit_before, "ACTIVE")

    response = api.set_clock({"current_utc": "2027-08-16T00:00:00Z"}, U.PROGRAM_ADMIN)
    validate_success(response, 200)
    body = get_success_data(response)
    assert body in ({}, None), f"the clock endpoint returns no entity, got {body!r}"

    permit_after = X.get_permit(api, bundle.permit_id)
    A.assert_status(permit_after, "ACTIVE")
    A.assert_version_unchanged(permit_before, permit_after)
    assert permit_after["version"] == 1
    assert permit_after["last_renewed_at"] is None
    assert permit_after["renewal_count"] == 0

    site_after = X.get_site(api, bundle.site_id)
    A.assert_version_unchanged(site_before, site_after)
    A.assert_money_cents(
        site_after["outstanding_balance_cents"],
        C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
        "outstanding_balance_cents",
    )
    assert site_after["response_status"] == "RESPONSE_ACTIVE"

    validate_success(api.run_nightly(U.PROGRAM_ADMIN))
    permit_aged = X.get_permit(api, bundle.permit_id)
    A.assert_status(permit_aged, "GRACE")
    assert permit_aged["version"] > permit_before["version"], (
        "the batch is what ages the permit, and it bumps the revision"
    )

    site_aged = X.get_site(api, bundle.site_id)
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    permit_back = X.get_permit(api, bundle.permit_id)
    A.assert_status(permit_back, "GRACE")
    A.assert_version_unchanged(permit_aged, permit_back)
    site_back = X.get_site(api, bundle.site_id)
    A.assert_version_unchanged(site_aged, site_back)
    A.assert_money_cents(
        site_back["outstanding_balance_cents"],
        site_aged["outstanding_balance_cents"],
        "outstanding_balance_cents",
    )
