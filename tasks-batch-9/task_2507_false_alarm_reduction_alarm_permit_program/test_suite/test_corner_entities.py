"""Entity-surface behaviour: creation defaults and system-sourced fields, computed
fields at issuance, single-resource retrieval round-trips, listing windows,
required-field and type-constraint refusals, referential existence of body
foreign keys, allocation-row immutability and cross-reference integrity.
"""
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


def test_fee_schedule_create_returns_draft_status_with_every_program_constant(api):
    """Publishing a schedule with all of its program constants answers 201 with the
    row in DRAFT at version 1, superseded_at null, and every constant echoed back.

    PRD §3.1: "A freshly created schedule lands in `DRAFT` and nothing consults it."
    PRD §2.9: "the supersession stamps `superseded_at` on the outgoing row, which is
    null while a schedule is `DRAFT` or `ACTIVE`."
    PRD §2.4: "Most resources additionally carry `updated_at`, refreshed on every
    mutation, and `version`, an integer that starts at 1 on creation and increments
    by exactly 1 on every mutation of that row."
    PRD §3.1: "Its `free_alarm_allowance` (2 by default) is the number of leading
    chargeable occurrences per window whose tier base is zero; those occurrences
    still count toward every threshold, they simply cost nothing."
    PRD §3.1: "Its `occupancy_multipliers` object maps each premises occupancy class
    to a multiplier, defaulting to 1.00 for `RESIDENTIAL`, 1.50 for `COMMERCIAL`,
    1.25 for `SCHOOL`, 2.00 for `FINANCIAL` and 1.00 for `GOVERNMENT`."
    PRD §3.1: "`suspension_period_aggravation_cents` (50000 by default) is a flat
    amount added after the per-incident cap when the incident happened inside a live
    suspension interval, and `per_incident_fee_cap_cents` (100000 by default) is the
    cap itself."
    PRD §3.1: "the default ladder charges nothing for occurrences 1 and 2, 10000
    cents for occurrence 3, 25000 for occurrence 4, 40000 for occurrence 5, and
    75000 for occurrence 6 and everything above it."

    Design: Corner/entities/fee_schedule_create_returns_draft_status_with_every_program_constant
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)

    response = api.create_fee_schedule(F.fee_schedule_payload(), U.PROGRAM_ADMIN)
    validate_success(response, 201)
    schedule = get_success_data(response)

    A.assert_entity_envelope(schedule)
    A.assert_status(schedule, "DRAFT")
    assert schedule["version"] == 1, f"a created schedule starts at version 1, got {schedule['version']}"
    assert schedule["superseded_at"] is None, (
        f"superseded_at is null while a schedule is DRAFT, got {schedule['superseded_at']!r}"
    )

    assert schedule["free_alarm_allowance"] == 2
    A.assert_money_cents(schedule["per_incident_fee_cap_cents"], 100000, "per_incident_fee_cap_cents")
    A.assert_money_cents(
        schedule["suspension_period_aggravation_cents"], 50000, "suspension_period_aggravation_cents"
    )

    multipliers = schedule["occupancy_multipliers"]
    assert float(multipliers["COMMERCIAL"]) == 1.50, f"COMMERCIAL multiplier: {multipliers['COMMERCIAL']}"
    assert float(multipliers["FINANCIAL"]) == 2.00, f"FINANCIAL multiplier: {multipliers['FINANCIAL']}"

    tiers = schedule["fee_tiers"]
    assert len(tiers) == 5, f"the default ladder declares five tiers, got {len(tiers)}"
    assert tiers[-1]["to_index"] is None, f"the open-ended tier carries to_index null, got {tiers[-1]}"
    A.assert_money_cents(tiers[-1]["base_fee_cents"], 75000, "open-ended tier base_fee_cents")


def test_alarm_site_get_by_id_returns_the_stored_premises_record(api):
    """Reading one premises back echoes the stored address fields, its occupancy
    class and beat, its ACTIVE status and RESPONSE_ACTIVE posture, and the same
    version the creation answered with.

    PRD §3.2: "A premises record is created with its normalized `address_key`, its
    `street_address`, `city`, `zip_code`, its `occupancy_class` — one of
    `RESIDENTIAL`, `COMMERCIAL`, `SCHOOL`, `FINANCIAL` or `GOVERNMENT` — and its
    `police_beat`."
    PRD §3.2: "A newly created premises starts with `response_status` at
    `RESPONSE_ACTIVE`, every counter at zero and `governing_fee_schedule_id` null."
    PRD §3.2: "the resulting key must be unique among premises whose `status` is
    `ACTIVE`; a premises `status` is either `ACTIVE` or `ARCHIVED`."
    PRD §2.4: "`version`, an integer that starts at 1 on creation and increments by
    exactly 1 on every mutation of that row."

    The read is what a client uses to learn the value it must later echo as
    expected_alarm_site_version, so the version the GET reports must be the very
    value the POST returned: 1 on an untouched premises.

    Design: Corner/entities/alarm_site_get_by_id_returns_the_stored_premises_record
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)

    created = api.create_alarm_site(
        F.alarm_site_payload(
            address_key="1200-MAIN-ST-75201",
            street_address="1200 Main St",
            city="Dallas",
            zip_code="75201",
            occupancy_class="COMMERCIAL",
            police_beat="B-114",
        ),
        U.PERMIT_CLERK,
    )
    validate_success(created, 201)
    posted = get_success_data(created)

    response = api.get_alarm_site(posted["id"], U.PERMIT_CLERK)
    validate_success(response, 200)
    site = get_success_data(response)

    assert site["address_key"] == "1200-MAIN-ST-75201", f"address_key: {site['address_key']!r}"
    assert site["city"] == "Dallas", f"city: {site['city']!r}"
    assert site["zip_code"] == "75201", f"zip_code: {site['zip_code']!r}"
    assert site["occupancy_class"] == "COMMERCIAL", f"occupancy_class: {site['occupancy_class']!r}"
    assert site["police_beat"] == "B-114", f"police_beat: {site['police_beat']!r}"
    A.assert_status(site, "ACTIVE")
    A.assert_status(site, "RESPONSE_ACTIVE", field="response_status")
    assert site["version"] == 1, f"an untouched premises reads at version 1, got {site['version']}"
    assert site["version"] == posted["version"], (
        f"the read version {site['version']} must equal the version creation returned {posted['version']}"
    )


def test_alarm_permit_issuance_computes_term_end_grace_and_new_installation_grace(api):
    """Approving the premises' first registration at 2026-08-01T00:00:00Z issues
    permit AP-000001 in ACTIVE with term_end_at 2027-08-01, grace_through_at
    2027-08-31 and new_installation_grace_through 2026-08-31, stamps the system
    PERMITTED and pins the premises' governing schedule.

    PRD §3.3: "Its `term_start_at` is the logical clock, `term_end_at` is
    `term_start_at` plus `permit_term_days` whole days, and `grace_through_at` is
    `term_end_at` plus `renewal_grace_days` whole days — the last instant at which a
    grace renewal is still accepted."
    PRD §3.3: "On the premises' **first** issuance only, two further things happen:
    `governing_fee_schedule_id` is pinned to the `ACTIVE` schedule, and
    `new_installation_grace_through` is set to `term_start_at` plus
    `new_installation_grace_days`; on every renewed term that field stays null."
    PRD §3.3: "`renewal_count` starts at 0, `last_renewed_at` is null before the
    first renewal, `revocation_reason` is null, and `issued_by_user_id` records the
    acting clerk's `X-User-ID`."
    PRD §3.3: "a `permit_number` assigned as the next zero-padded sequential value
    in issuance order, formatted `AP-000001`."
    PRD §3.3: "The system's `permitted_at` is stamped with the logical clock and its
    `unpermitted_since` is cleared."

    With permit_term_days 365, term_start_at 2026-08-01T00:00:00Z plus 365 whole days
    is 2027-08-01T00:00:00Z; plus renewal_grace_days 30 that is 2027-08-31T00:00:00Z;
    and term_start_at plus new_installation_grace_days 30 is 2026-08-31T00:00:00Z.

    Design: Corner/entities/alarm_permit_issuance_computes_term_end_grace_and_new_installation_grace
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    schedule_id = X.create_active_fee_schedule(api)
    company_id = X.create_company(api)
    site_id = X.create_site(api, occupancy_class="COMMERCIAL", police_beat="B-114")
    X.create_contacts(api, site_id, 2)
    system_id = X.create_submitted_system(
        api, site_id, company_id, installed_at="2026-07-25T14:00:00Z"
    )

    response = api.approve_registration(system_id, U.PERMIT_CLERK)
    validate_success(response, 201)
    permit = get_success_data(response)

    A.assert_status(permit, "ACTIVE")
    assert permit["term_start_at"].startswith("2026-08-01T00:00:00"), permit["term_start_at"]
    assert permit["term_end_at"].startswith("2027-08-01T00:00:00"), permit["term_end_at"]
    assert permit["grace_through_at"].startswith("2027-08-31T00:00:00"), permit["grace_through_at"]
    assert permit["new_installation_grace_through"].startswith("2026-08-31T00:00:00"), (
        permit["new_installation_grace_through"]
    )
    assert permit["permit_number"] == "AP-000001", f"permit_number: {permit['permit_number']!r}"
    assert permit["renewal_count"] == 0, f"renewal_count: {permit['renewal_count']}"
    assert permit["last_renewed_at"] is None, f"last_renewed_at: {permit['last_renewed_at']!r}"
    assert permit["issued_by_user_id"] == U.PERMIT_CLERK_ID, permit["issued_by_user_id"]
    assert permit["alarm_site_id"] == site_id, permit["alarm_site_id"]

    system = X.get_system(api, system_id)
    A.assert_status(system, "PERMITTED")
    assert system["permitted_at"].startswith("2026-08-01T00:00:00"), system["permitted_at"]

    site = X.get_site(api, site_id)
    assert site["governing_fee_schedule_id"] == schedule_id, site["governing_fee_schedule_id"]


def test_alarm_sites_list_page_two_reports_total_count_limit_offset_and_has_more(api):
    """With three premises and per_page 2, page 1 carries limit 2 / offset 0 /
    total_count 3 / has_more true and page 2 carries limit 2 / offset 2 /
    total_count 3 / has_more false, the two windows partitioning the three rows.

    PRD §2.3: "`page` is an integer that must be at or above 1 and defaults to 1.
    `per_page` is an integer that must lie between 1 and 100 inclusive and defaults
    to 10."
    PRD §2.3: "`limit` carries the effective page size (default 10, minimum 1,
    maximum 100), `offset` carries the number of rows skipped (default 0, being the
    page size multiplied by one less than the requested page), `total_count` carries
    the number of rows matching the filter before the window is applied, and
    `has_more` is true when rows remain beyond the current window."

    Offset on page 2 is the page size 2 multiplied by one less than the page, so 2;
    with total_count 3 that window holds the single remaining row and has_more is
    false.

    Design: Corner/entities/alarm_sites_list_page_two_reports_total_count_limit_offset_and_has_more
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    site_one = X.create_site(api, address_key="1200-MAIN-ST-75201", occupancy_class="COMMERCIAL")
    site_two = X.create_site(api, address_key="88-ELM-AVE-75204", occupancy_class="RESIDENTIAL")
    site_three = X.create_site(api, address_key="4-CIVIC-PLZ-75202", occupancy_class="GOVERNMENT")

    first = api.list_alarm_sites(U.PROGRAM_ADMIN, {"page": 1, "per_page": 2})
    validate_success(first, 200)
    first_rows, first_meta = validate_paginated(first)
    assert len(first_rows) == 2, f"page 1 holds two rows, got {len(first_rows)}"
    assert first_meta["limit"] == 2, first_meta
    assert first_meta["offset"] == 0, first_meta
    assert first_meta["total_count"] == 3, first_meta
    assert first_meta["has_more"] is True, first_meta

    second = api.list_alarm_sites(U.PROGRAM_ADMIN, {"page": 2, "per_page": 2})
    validate_success(second, 200)
    second_rows, second_meta = validate_paginated(second)
    assert len(second_rows) == 1, f"page 2 holds the one remaining row, got {len(second_rows)}"
    assert second_meta["limit"] == 2, second_meta
    assert second_meta["offset"] == 2, second_meta
    assert second_meta["total_count"] == 3, second_meta
    assert second_meta["has_more"] is False, second_meta

    windowed = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert len(windowed) == len(set(windowed)), f"no row may repeat across pages, got {windowed}"
    assert set(windowed) == {site_one, site_two, site_three}, windowed


def test_alarm_permit_get_with_unknown_uuid_returns_permit_not_found(api):
    """A syntactically valid but unused permit identifier in the path answers 404
    ERR_ALARM_PERMIT_NOT_FOUND with a human-readable message, and no permit row
    comes into being.

    PRD §2.5: "The service exposes single-resource reads keyed on `scheduleId`,
    `companyId`, `siteId`, `contactId`, `systemId`, `permitId`, `requestId`,
    `incidentId`, `docketId`, `appealId`, `orderId`, `invoiceId`, `paymentId`,
    `allocationId` and `reportId`, and each unresolvable identifier produces its own
    code: `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_ALARM_COMPANY_NOT_FOUND`,
    `ERR_ALARM_SITE_NOT_FOUND`, `ERR_SITE_CONTACT_NOT_FOUND`,
    `ERR_ALARM_SYSTEM_NOT_FOUND`, `ERR_ALARM_PERMIT_NOT_FOUND`,
    `ERR_DISPATCH_REQUEST_NOT_FOUND`, `ERR_FALSE_ALARM_INCIDENT_NOT_FOUND`,
    `ERR_HEARING_DOCKET_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`,
    `ERR_SUSPENSION_ORDER_NOT_FOUND`, `ERR_PENALTY_INVOICE_NOT_FOUND`,
    `ERR_PAYMENT_RECORD_NOT_FOUND`, `ERR_PAYMENT_ALLOCATION_NOT_FOUND` and
    `ERR_COMPLIANCE_REPORT_NOT_FOUND`."
    PRD §2.5: "Where an identifier cannot be attributed to a specific entity type,
    the umbrella code `ERR_RESOURCE_NOT_FOUND` is returned instead. All fifteen
    entity-specific codes and the umbrella code carry HTTP 404."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/entities/alarm_permit_get_with_unknown_uuid_returns_permit_not_found
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)

    response = api.get_alarm_permit(NON_EXISTENT_UUID, U.PERMIT_CLERK)
    validate_error(response, E.ERR_ALARM_PERMIT_NOT_FOUND, expected_status=404)

    body = response.json()
    assert body["response_type"] == "error", body["response_type"]
    message = body["data"]["message"]
    assert isinstance(message, str) and message.strip(), f"message must be non-empty, got {message!r}"

    listing = api.list_alarm_permits(U.PERMIT_CLERK)
    validate_success(listing, 200)
    A.assert_total_count(listing, 0)


def test_alarm_system_create_without_zone_count_returns_missing_required_field(api):
    """Omitting zone_count from a registration is refused with 422
    ERR_MISSING_REQUIRED_FIELD before any foreign key is resolved, and no
    registration row lands against the premises.

    PRD §2.10: "On every write operation, each required input field must be present
    and non-null; the first missing field in the operation's declared input order is
    reported with `ERR_MISSING_REQUIRED_FIELD`."
    PRD §3.3: "A registration is lodged against a premises naming `alarm_site_id`,
    the `monitoring_company_id` of the company that will monitor the panel and may
    request dispatch for it, the `system_type` (`BURGLARY`, `HOLDUP_PANIC` or
    `COMBINATION`), the `zone_count` of protected zones, which must be at least 1,
    whether `ecv_enabled` is configured on the panel, the `verified_response_mode`
    demanded of it (`NONE` by default, or `AUDIO_VIDEO_REQUIRED` or
    `GUARD_REQUIRED`), and the `installed_at` instant reported on the paperwork."
    PRD §2.10: "Every identifier embedded in the request path must resolve, checked
    strictly left to right so the leftmost unknown segment wins, and then every
    foreign reference supplied in the body must resolve, checked in declared input
    order."

    zone_count is declared with no default, so its absence is the payload-shape
    failure at positions 4 and 5, which precede the body-reference existence checks
    at positions 6 and 7.

    Design: Corner/entities/alarm_system_create_without_zone_count_returns_missing_required_field
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    company_id = X.create_company(api)
    site_id = X.create_site(api)

    payload = F.alarm_system_payload(
        site_id, company_id, system_type="BURGLARY", installed_at="2026-07-25T14:00:00Z"
    )
    del payload["zone_count"]

    response = api.create_alarm_system(payload, U.PERMIT_CLERK)
    validate_error(response, E.ERR_MISSING_REQUIRED_FIELD, expected_status=422)

    listing = api.list_alarm_systems(U.PERMIT_CLERK, {"alarm_site_id": site_id})
    validate_success(listing, 200)
    A.assert_total_count(listing, 0)


def test_alarm_company_create_starts_active_with_default_compliance_score(api):
    """A monitoring company registered with only its five declared inputs lands in
    ACTIVE at version 1 with a 1.00 compliance score, all three derived counters at
    0, its status and probation stamps null, and the supplied score_mode honoured.

    PRD §3.10: "A monitoring company is registered with its `legal_name`, its state
    `license_number`, a `contact_email`, a `contact_phone` in E.164 form, and a
    `score_mode` of `VOLUME_WEIGHTED` or `PERIOD_EQUAL` that decides which scoring
    variant governs it thereafter."
    PRD §3.10: "The company is created in `ACTIVE` with `reporting_compliance_score`
    at 1.00, `probation_started_at`, `status_reason` and `last_status_action_at` all
    null, and its derived counters recomputed: `monitored_system_count` as the number
    of systems it monitors in `SUBMITTED`, `PERMITTED` or `UNPERMITTED`,
    `dispatch_request_count_lifetime` as the number of dispatch requests it has
    lodged across every status, and `consecutive_flagged_report_count` as the length
    of the most-recent unbroken run of its reports ending in `VARIANCE_FLAGGED`,
    taken in order of `period_start` ascending."
    PRD §2.4: "`version`, an integer that starts at 1 on creation and increments by
    exactly 1 on every mutation of that row."

    A company registered into an otherwise empty program monitors no systems, has
    lodged no dispatch requests and has filed no reports, so each recomputed counter
    is 0.

    Design: Corner/entities/alarm_company_create_starts_active_with_default_compliance_score
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)

    response = api.create_alarm_company(
        F.alarm_company_payload(
            legal_name="Northside Alarm Response Inc",
            license_number="TXALM-90311",
            contact_email="ops@northside.example",
            contact_phone="+12145550190",
            score_mode="PERIOD_EQUAL",
        ),
        U.PROGRAM_ADMIN,
    )
    validate_success(response, 201)
    company = get_success_data(response)

    A.assert_entity_envelope(company)
    A.assert_status(company, "ACTIVE")
    assert company["version"] == 1, f"version: {company['version']}"
    A.assert_score_2dp(company["reporting_compliance_score"], 1.00, "reporting_compliance_score")
    assert company["monitored_system_count"] == 0, company["monitored_system_count"]
    assert company["dispatch_request_count_lifetime"] == 0, company["dispatch_request_count_lifetime"]
    assert company["consecutive_flagged_report_count"] == 0, company["consecutive_flagged_report_count"]
    assert company["probation_started_at"] is None, company["probation_started_at"]
    assert company["last_status_action_at"] is None, company["last_status_action_at"]
    assert company["status_reason"] is None, company["status_reason"]
    assert company["score_mode"] == "PERIOD_EQUAL", company["score_mode"]


def test_hearing_docket_create_omitting_capacity_defaults_to_four_seats(api):
    """Opening a docket without a capacity applies the declared default of 4 seats,
    and the session opens in OPEN at version 1 with no appeals seated and held_at
    null.

    PRD §3.6: "It is opened with a `hearing_officer_user_id` naming the officer the
    session belongs to, a `session_start` and `session_end` describing a half-open
    interval whose end must be strictly after its start, a `location` identifying the
    hearing room, and an optional `capacity` between 1 and 8 that defaults to 4 and
    caps how many appeals the session will seat."
    PRD §3.6: "The docket is created in `OPEN` with `scheduled_appeal_count` at 0 and
    `held_at` null."
    PRD §2.4: "`version`, an integer that starts at 1 on creation and increments by
    exactly 1 on every mutation of that row."

    Design: Corner/entities/hearing_docket_create_omitting_capacity_defaults_to_four_seats
    """
    X.set_clock(api, C.CLOCK_PRESENT_UTC)

    payload = F.hearing_docket_payload(
        U.HEARING_OFFICER_ID,
        "2026-10-05T14:00:00Z",
        "2026-10-05T16:00:00Z",
        location="City Hall Room 210",
    )
    del payload["capacity"]

    response = api.create_hearing_docket(payload, U.HEARING_OFFICER)
    validate_success(response, 201)
    docket = get_success_data(response)

    assert docket["capacity"] == 4, f"an omitted capacity defaults to 4, got {docket['capacity']}"
    A.assert_status(docket, "OPEN")
    assert docket["scheduled_appeal_count"] == 0, docket["scheduled_appeal_count"]
    assert docket["held_at"] is None, docket["held_at"]
    assert docket["version"] == 1, docket["version"]


def test_alarm_site_create_initializes_every_derived_counter_to_zero(api):
    """A brand-new premises reports both counting variants, the authoritative window
    count and every money and roster counter at 0 with renewal_block_active false and
    RESPONSE_ACTIVE posture, and its governing schedule stays null even though a
    schedule is already ACTIVE.

    PRD §3.2: "A newly created premises starts with `response_status` at
    `RESPONSE_ACTIVE`, every counter at zero and `governing_fee_schedule_id` null."
    PRD §2.9: "A premises is **pinned** to a schedule the first time any of its
    systems is permitted: at that moment `governing_fee_schedule_id` on the
    `AlarmSite` is set to the currently `ACTIVE` schedule and becomes immutable, and
    it stays null until then."
    PRD §3.2: "`unpermitted_system_count` counts the address's systems that have
    fallen out of permit, `lifted_suspension_count` counts its suspensions that were
    properly lifted, `ecv_callable_contact_count` counts its live callable contacts,
    and `renewal_block_active` is true exactly when `outstanding_balance_cents` is at
    or above the schedule's `delinquent_balance_block_cents`."
    PRD §3.2: "`chargeable_count_window` is the authoritative window count under the
    governing counting variant, while `chargeable_count_rolling_365` and
    `chargeable_count_permit_year` are both maintained at all times so the two
    variants can be compared side by side."

    With no invoices the outstanding balance is 0, which is not at or above
    delinquent_balance_block_cents, so renewal_block_active is false.

    Design: Corner/entities/alarm_site_create_initializes_every_derived_counter_to_zero
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    schedule_id = X.create_active_fee_schedule(api)

    response = api.create_alarm_site(
        F.alarm_site_payload(
            address_key="77-OAK-LN-75210",
            street_address="77 Oak Ln",
            city="Dallas",
            zip_code="75210",
            occupancy_class="SCHOOL",
            police_beat="B-330",
        ),
        U.PROGRAM_ADMIN,
    )
    validate_success(response, 201)
    site = get_success_data(response)

    assert site["chargeable_count_rolling_365"] == 0, site["chargeable_count_rolling_365"]
    assert site["chargeable_count_permit_year"] == 0, site["chargeable_count_permit_year"]
    assert site["chargeable_count_window"] == 0, site["chargeable_count_window"]
    A.assert_money_cents(site["lifetime_assessed_cents"], 0, "lifetime_assessed_cents")
    A.assert_money_cents(site["outstanding_balance_cents"], 0, "outstanding_balance_cents")
    A.assert_money_cents(site["credit_balance_cents"], 0, "credit_balance_cents")
    assert site["unpermitted_system_count"] == 0, site["unpermitted_system_count"]
    assert site["lifted_suspension_count"] == 0, site["lifted_suspension_count"]
    assert site["ecv_callable_contact_count"] == 0, site["ecv_callable_contact_count"]
    assert site["renewal_block_active"] is False, site["renewal_block_active"]
    A.assert_status(site, "RESPONSE_ACTIVE", field="response_status")
    assert site["governing_fee_schedule_id"] is None, (
        "the premises pins its schedule at first issuance, not at creation; "
        f"got {site['governing_fee_schedule_id']!r} while {schedule_id} is ACTIVE"
    )


def test_site_contact_create_client_supplied_status_extra_field_ignored(api):
    """A roster entry posted with status REMOVED and a removed_at stamp still lands
    ACTIVE with removed_at null and version 1, and the write bumps the premises to
    version 2 with one callable contact counted.

    PRD §3.2: "Adding one supplies the premises reference `alarm_site_id`, the party's
    `full_name`, a `phone_number` in E.164 form, their `relationship` to the premises
    (owner, manager, keyholder and the like), a `contact_priority` between 1 and 5
    that fixes call order, and `is_ecv_callable`, which defaults to true and decides
    whether the contact counts toward enhanced call verification."
    PRD §3.2: "A contact's `status` is `ACTIVE` or `REMOVED`; removal is soft, setting
    `status` to `REMOVED` and stamping `removed_at` (null while active) rather than
    deleting the row."
    PRD §3.2: "Both adding and removing a contact recompute
    `ecv_callable_contact_count` on the premises and bump that premises' `version` by
    1 — which is why a client holding an `expected_alarm_site_version` from before a
    roster edit will be turned away on its next guarded write."
    PRD §2.6: "Nothing in this program consults wall-clock time."
    PRD §2.4: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp
    with three fractional digits recorded at insertion."

    status and removed_at are not among the declared creation inputs and move only
    through soft removal, so the posted values cannot take effect: the row is ACTIVE
    with removed_at null. The premises was at version 1 after creation, so the roster
    write leaves it at version 2.

    Design: Corner/entities/site_contact_create_client_supplied_status_extra_field_ignored
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    site_id = X.create_site(api, address_key="1200-MAIN-ST-75201", occupancy_class="COMMERCIAL")

    response = api.create_site_contact(
        F.site_contact_payload(
            site_id,
            full_name="Ingrid Sato",
            phone_number="+12145550133",
            relationship="KEYHOLDER",
            contact_priority=3,
            is_ecv_callable=True,
            status="REMOVED",
            removed_at="2026-07-01T00:00:00Z",
        ),
        U.alarm_user(site_id),
    )
    validate_success(response, 201)
    contact = get_success_data(response)

    A.assert_status(contact, "ACTIVE")
    assert contact["removed_at"] is None, (
        f"removed_at is null while a contact is active, got {contact['removed_at']!r}"
    )
    assert contact["created_at"].startswith("2026-08-01T00:00:00"), contact["created_at"]
    assert contact["version"] == 1, contact["version"]

    site = X.get_site(api, site_id)
    assert site["ecv_callable_contact_count"] == 1, site["ecv_callable_contact_count"]
    assert site["version"] == 2, (
        f"the roster write bumps the premises from version 1 to 2, got {site['version']}"
    )


def test_alarm_system_create_rejects_zone_count_below_one(api):
    """A registration declaring zone_count 0 is refused with 422
    ERR_INVALID_FIELD_VALUE even though every other field is well formed and every
    foreign key resolves.

    PRD §3.3: "the `zone_count` of protected zones, which must be at least 1"
    PRD §2.10: "Then each supplied field must be well formed: enum fields must hold a
    declared member, cents and count fields must be non-negative integers with no
    floats accepted anywhere, timestamps must parse as RFC 3339 UTC with a trailing
    `Z`, percentage fields must lie between 0 and 1 inclusive, identifiers must be
    UUID strings, and tier arrays must be non-empty. The first offending field in
    declared input order is reported with `ERR_INVALID_FIELD_VALUE`."

    Design: Corner/entities/alarm_system_create_rejects_zone_count_below_one
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    company_id = X.create_company(api)
    site_id = X.create_site(api)

    response = api.create_alarm_system(
        F.alarm_system_payload(
            site_id,
            company_id,
            system_type="COMBINATION",
            zone_count=0,
            installed_at="2026-07-25T14:00:00Z",
        ),
        U.PERMIT_CLERK,
    )
    validate_error(response, E.ERR_INVALID_FIELD_VALUE, expected_status=422)

    listing = api.list_alarm_systems(U.PERMIT_CLERK, {"alarm_site_id": site_id})
    validate_success(listing, 200)
    A.assert_total_count(listing, 0)


def test_alarm_system_create_rejects_invalid_enum_verified_response_mode(api):
    """A registration naming GUARD_RESPONSE as its verified_response_mode is refused
    with 422 ERR_INVALID_FIELD_VALUE rather than coerced to the NONE default, and the
    premises is left untouched at version 1.

    PRD §3.3: "the `verified_response_mode` demanded of it (`NONE` by default, or
    `AUDIO_VIDEO_REQUIRED` or `GUARD_REQUIRED`)"
    PRD §2.7: "a value outside that range is rejected with `ERR_INVALID_FIELD_VALUE`,
    as is a non-integer cents amount, a negative count, an unrecognized enum member,
    a malformed UUID, an empty tier array, or a timestamp that does not parse as an
    RFC 3339 UTC instant with a trailing `Z`."
    PRD §2.4: "`version`, an integer that starts at 1 on creation and increments by
    exactly 1 on every mutation of that row."

    GUARD_RESPONSE is a declared verification_method on a dispatch request, not a
    member of the system's verified-response enumeration, so it is an unrecognized
    enum member for this field.

    Design: Corner/entities/alarm_system_create_rejects_invalid_enum_verified_response_mode
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    company_id = X.create_company(api)
    site_id = X.create_site(api)

    response = api.create_alarm_system(
        F.alarm_system_payload(
            site_id,
            company_id,
            system_type="BURGLARY",
            zone_count=4,
            verified_response_mode="GUARD_RESPONSE",
            installed_at="2026-07-25T14:00:00Z",
        ),
        U.PERMIT_CLERK,
    )
    validate_error(response, E.ERR_INVALID_FIELD_VALUE, expected_status=422)

    listing = api.list_alarm_systems(U.PERMIT_CLERK, {"alarm_site_id": site_id})
    validate_success(listing, 200)
    A.assert_total_count(listing, 0)

    site = X.get_site(api, site_id)
    assert site["version"] == 1, f"a refused registration mutates nothing, got {site['version']}"


def test_site_contact_create_rejects_contact_priority_above_five(api):
    """A roster entry at contact_priority 6 is a range violation refused with 422
    ERR_INVALID_FIELD_VALUE, not a duplicate-priority conflict, and no contact is
    stored.

    PRD §3.2: "a `contact_priority` between 1 and 5 that fixes call order"
    PRD §2.10: "Then each supplied field must be well formed: enum fields must hold a
    declared member, cents and count fields must be non-negative integers with no
    floats accepted anywhere, timestamps must parse as RFC 3339 UTC with a trailing
    `Z`, percentage fields must lie between 0 and 1 inclusive, identifiers must be
    UUID strings, and tier arrays must be non-empty. The first offending field in
    declared input order is reported with `ERR_INVALID_FIELD_VALUE`."
    PRD §2.10: "A contact's `contact_priority` must be unique among the `ACTIVE`
    contacts of the same premises, failing with `ERR_DUPLICATE_CONTACT_PRIORITY`."

    The roster is empty, so nothing collides and the uniqueness rule cannot fire; the
    only fault is the out-of-range value, caught at the payload-shape position.

    Design: Corner/entities/site_contact_create_rejects_contact_priority_above_five
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    site_id = X.create_site(api, address_key="1200-MAIN-ST-75201", occupancy_class="COMMERCIAL")

    response = api.create_site_contact(
        F.site_contact_payload(
            site_id,
            full_name="Out Of Range",
            phone_number="+12145550166",
            relationship="KEYHOLDER",
            contact_priority=6,
            is_ecv_callable=True,
        ),
        U.PERMIT_CLERK,
    )
    validate_error(response, E.ERR_INVALID_FIELD_VALUE, expected_status=422)
    assert response.json()["data"]["error_id"] != E.ERR_DUPLICATE_CONTACT_PRIORITY, (
        "an empty roster cannot collide, so this must not be reported as a duplicate priority"
    )

    listing = api.list_site_contacts(U.PERMIT_CLERK, {"alarm_site_id": site_id})
    validate_success(listing, 200)
    A.assert_total_count(listing, 0)


def test_payment_allocation_row_is_immutable_and_carries_no_version_field(api):
    """The allocation produced by settling the permit issue invoice exposes only id
    and created_at beyond its own fields — no updated_at and no version — and is
    readable both through the filtered list and by identifier.

    PRD §2.4: "`PaymentAllocation` rows are immutable ledger lines produced as a
    by-product of posting a payment; they carry only `id` and `created_at`. An
    allocation has no `updated_at` and no `version` field at all — when an allocation
    is reversed, its `status` moves from `APPLIED` to `REVERSED` and the reversal is
    recorded through the parent payment's own mutation, not through a revision counter
    on the line."
    PRD §3.9: "Every non-zero application creates a `PaymentAllocation` — which
    carries only an `id` and a `created_at` beyond its own fields, having no revision
    counter of its own — recording the `payment_record_id`, the `penalty_invoice_id`,
    the `amount_cents` applied, a 1-based `sequence_index` giving its position in the
    order that produced it, and `status` of `APPLIED`."
    PRD §3.8: "A `PERMIT_ISSUE_FEE` invoice carries one PERMIT_ISSUE line at
    `permit_issue_fee_cents`."
    PRD §3.8: "`admin_fee_cents` is then the subtotal times `admin_fee_pct`, rounded
    half up once on the already-rounded subtotal, and clamped upward to
    `admin_fee_min_cents` and downward to `admin_fee_max_cents`."

    The issue fee is 5000 cents; 0.05 of that is 250, clamped up to the 500-cent
    floor, so the invoice is assessed at 5500 and outstanding at 5500. A 5500-cent
    tender against the only candidate invoice therefore produces exactly one
    allocation of 5500 cents at the first position of the waterfall, index 1.

    Design: Corner/entities/payment_allocation_row_is_immutable_and_carries_no_version_field
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_STARTUP_UTC,
        installed_at=C.CLOCK_STARTUP_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    invoices = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")
    assert len(invoices) == 1, f"one permit issue invoice is expected, got {len(invoices)}"
    invoice_id = invoices[0]["id"]
    A.assert_money_cents(invoices[0]["outstanding_cents"], 5500, "outstanding_cents")

    payment_id = X.post_payment(api, bundle, 5500, C.CLOCK_STARTUP_UTC, method="CARD")

    listing = api.list_payment_allocations(U.BILLING_CLERK, {"payment_record_id": payment_id})
    validate_success(listing, 200)
    rows = A.assert_total_count(listing, 1)
    assert rows[0]["sequence_index"] == 1, (
        f"sequence_index is 1-based, so the only line sits at 1, got {rows[0]['sequence_index']}"
    )
    assert rows[0]["penalty_invoice_id"] == invoice_id, rows[0]["penalty_invoice_id"]

    response = api.get_payment_allocation(rows[0]["id"], U.BILLING_CLERK)
    validate_success(response, 200)
    allocation = get_success_data(response)

    A.assert_money_cents(allocation["amount_cents"], 5500, "allocation amount_cents")
    A.assert_status(allocation, "APPLIED")
    A.assert_allocation_row(allocation)
    assert "version" not in allocation, "an allocation line carries no revision counter"
    assert "updated_at" not in allocation, "an allocation line carries no updated_at"


def test_alarm_system_create_with_unknown_alarm_site_id_returns_site_not_found(api):
    """A registration naming an unused premises identifier is refused with 404
    ERR_ALARM_SITE_NOT_FOUND, and the real company it named keeps a monitored system
    count of 0.

    PRD §2.5: "The same codes serve references supplied inside a request body, which
    are resolved only after every path segment has resolved, and among themselves in
    the order the fields are declared for that operation. A `monitoring_company_id`
    that names nothing yields `ERR_ALARM_COMPANY_NOT_FOUND`; an `alarm_site_id` yields
    `ERR_ALARM_SITE_NOT_FOUND`"
    PRD §3.3: "A registration is lodged against a premises naming `alarm_site_id`, the
    `monitoring_company_id` of the company that will monitor the panel and may request
    dispatch for it"
    PRD §3.10: "`monitored_system_count` as the number of systems it monitors in
    `SUBMITTED`, `PERMITTED` or `UNPERMITTED`"

    alarm_site_id is the leftmost declared reference of the operation, so it is the
    one reported; the company reference resolves and is never reached.

    Design: Corner/entities/alarm_system_create_with_unknown_alarm_site_id_returns_site_not_found
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    company_id = X.create_company(api)

    response = api.create_alarm_system(
        F.alarm_system_payload(
            NON_EXISTENT_UUID,
            company_id,
            system_type="BURGLARY",
            zone_count=6,
            installed_at="2026-07-25T14:00:00Z",
        ),
        U.PERMIT_CLERK,
    )
    validate_error(response, E.ERR_ALARM_SITE_NOT_FOUND, expected_status=404)

    company = X.get_company(api, company_id)
    assert company["monitored_system_count"] == 0, (
        f"a refused registration monitors nothing, got {company['monitored_system_count']}"
    )


def test_dispatch_request_rejects_system_monitored_by_a_different_company(api):
    """An operator of a second registered company lodging a dispatch request for a
    system monitored by the first company is refused with 409
    ERR_COMPANY_NOT_SYSTEM_MONITOR, no request row is created for that system and the
    second company's lifetime request count stays 0.

    PRD §3.4: "It is refused with `ERR_OPEN_DISPATCH_REQUEST_EXISTS` when the system
    already has a request in `SUBMITTED`, `VALIDATED` or `DISPATCHED`; with
    `ERR_COMPANY_NOT_SYSTEM_MONITOR` when the acting company is not the system's
    monitoring company; with `ERR_COMPANY_DISPATCH_PRIVILEGE_SUSPENDED` when the
    company is `SUSPENDED` or `REVOKED`; with `ERR_POLICE_RESPONSE_SUSPENDED` when the
    premises posture is `RESPONSE_SUSPENDED`; and with `ERR_INSUFFICIENT_ECV_CONTACTS`
    when the premises' live callable roster is below the distinct-contact minimum its
    posture requires."
    PRD §2.10: "The monitoring company named as reporter must be the monitoring company
    of the referenced alarm system, and the referenced system must belong to the
    referenced premises; this guards dispatch-request submission, incident creation and
    compliance-report filing, and fails with `ERR_COMPANY_NOT_SYSTEM_MONITOR`."
    PRD §3.10: "`dispatch_request_count_lifetime` as the number of dispatch requests it
    has lodged across every status"

    The company-to-system link is a plain body reference rather than a path nesting, so
    it is re-validated on every submission; §2.10 names dispatch-request submission
    among the operations this check guards, and the catalogue carries it at HTTP 409 —
    not the 404 of an unresolvable reference and not a 403.

    Design: Corner/entities/dispatch_request_rejects_system_monitored_by_a_different_company
    """
    bundle = X.setup_program_baseline(api, site_overrides={"occupancy_class": "COMMERCIAL"})
    rival_company_id = X.create_company(
        api,
        legal_name="Rival Central Station Co",
        license_number="TXALM-77002",
        contact_email="ops@rivalcentral.example",
        contact_phone="+12145550222",
        score_mode="VOLUME_WEIGHTED",
    )
    occurred_at = C.FIRST_CHARGEABLE_OCCURRED_AT

    response = api.create_dispatch_request(
        F.dispatch_request_payload(
            bundle.system_id,
            occurred_at,
            X.two_call_attempts(bundle, occurred_at),
            verification_method="TWO_CALL_ECV",
            idempotency_key="rival-001",
        ),
        U.alarm_company_operator(rival_company_id),
    )
    # PRD names two codes for this one scenario: §3.4 pins
    # `ERR_COMPANY_NOT_SYSTEM_MONITOR` for "the acting company is not the
    # system's monitoring company", while §2.1 pins `ERR_NOT_RESOURCE_OWNER`
    # for an `AlarmCompanyOperator` whose `X-User-ID` differs from "the
    # monitoring company of the target system" and §2.10 ranks that identity
    # check at position 8, ahead of the position-22 coherence check.  Either
    # answer is faithful, so accept both and keep every other assertion.
    validate_error_is_one_of(
        response,
        [E.ERR_COMPANY_NOT_SYSTEM_MONITOR, E.ERR_NOT_RESOURCE_OWNER],
    )

    listing = api.list_dispatch_requests(
        U.DISPATCH_SUPERVISOR, {"alarm_system_id": bundle.system_id}
    )
    validate_success(listing, 200)
    A.assert_total_count(listing, 0)

    rival = X.get_company(api, rival_company_id)
    assert rival["dispatch_request_count_lifetime"] == 0, (
        f"a refused submission was never lodged, got {rival['dispatch_request_count_lifetime']}"
    )


def test_penalty_invoices_list_filter_reaches_the_cascade_created_permit_invoice(api):
    """The permit issue invoice raised as a side effect of approval is discoverable
    only through the filtered invoice list, where the permit reference and the kind
    together retrieve exactly one row carrying INV-000001, 5000 + 500 = 5500 cents and
    null incident and suspension references.

    PRD §3.8: "Invoices are never posted by hand; each one is a side effect of exactly
    one triggering event — a system reaching `PERMITTED`, a permit renewal, a system
    falling to `UNPERMITTED`, an incident being ruled chargeable, or a suspension order
    being served — and every rate it uses comes from the schedule pinned in the
    premises' `governing_fee_schedule_id`, never from a newer active schedule."
    PRD §3.8: "The row records `alarm_site_id` plus exactly one source link:
    `false_alarm_incident_id` when `kind` is `FALSE_ALARM_FEE`, `alarm_permit_id` when
    `kind` is `PERMIT_ISSUE_FEE`, `PERMIT_RENEWAL_FEE` or
    `UNPERMITTED_OPERATION_PENALTY`, `suspension_order_id` when `kind` is
    `REINSTATEMENT_FEE`. It receives the next sequential `invoice_number` in issuance
    order, zero-padded in the form INV-000001."
    PRD §3.8: "A `PERMIT_ISSUE_FEE` invoice carries one PERMIT_ISSUE line at
    `permit_issue_fee_cents`."
    PRD §3.8: "`assessed_cents` is `subtotal_cents` plus `admin_fee_cents` plus
    `late_penalty_cents`; `paid_cents` and `adjusted_cents` start at 0;
    `outstanding_cents` is `assessed_cents` minus `paid_cents` minus `adjusted_cents`,
    floored at zero and never negative."
    PRD §3.8: "The money dimension starts at `UNPAID` and terminates at `PAID` or
    `VOIDED`."
    PRD §3.8: "The dunning dimension starts at `CURRENT` and terminates at
    `WRITTEN_OFF`."
    PRD §2.3: "Filters supplied on a list endpoint combine conjunctively — a request
    naming both a premises and a status returns only rows matching both."

    The single PERMIT_ISSUE line is 5000 cents, so the subtotal is 5000; the
    administrative fee of 0.05 times 5000 is 250, clamped up to the 500-cent floor;
    assessed is therefore 5500 and, with nothing paid or adjusted, outstanding is 5500
    as well.

    Design: Corner/entities/penalty_invoices_list_filter_reaches_the_cascade_created_permit_invoice
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_STARTUP_UTC,
        installed_at=C.CLOCK_STARTUP_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )

    listing = api.list_penalty_invoices(
        U.BILLING_CLERK, {"alarm_permit_id": bundle.permit_id, "kind": "PERMIT_ISSUE_FEE"}
    )
    invoice = A.single(listing)

    assert invoice["invoice_number"] == "INV-000001", invoice["invoice_number"]
    assert invoice["alarm_site_id"] == bundle.site_id, invoice["alarm_site_id"]
    A.assert_invoice_totals(
        invoice,
        subtotal_cents=C.PERMIT_ISSUE_INVOICE_SUBTOTAL_CENTS,
        admin_fee_cents=C.PERMIT_ISSUE_INVOICE_ADMIN_CENTS,
        assessed_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
        outstanding_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
        payment_status="UNPAID",
        collections_stage="CURRENT",
    )
    assert invoice["false_alarm_incident_id"] is None, invoice["false_alarm_incident_id"]
    assert invoice["suspension_order_id"] is None, invoice["suspension_order_id"]
