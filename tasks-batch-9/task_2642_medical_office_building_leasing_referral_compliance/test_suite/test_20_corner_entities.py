"""Entity-surface compliance tests: creation, retrieval, listing, defaults,
derived fields, system fields, type constraints, immutability and the
building/suite/tenant/lease reference graph.

Every test builds its own state from scratch through PRD-declared endpoints.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_line_item_has_no_version_fields,
    assert_money_equals,
    assert_parking_counters,
    assert_share_equals,
    assert_total_count,
    ids_of,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    LEASING_AGENT,
    PORTFOLIO_ADMIN,
    PROPERTY_MANAGER,
)


def test_building_registration_returns_inputs_and_empty_derived_figures(api):
    """Registering a building echoes its six inputs and reports every derived
    tenant-mix and parking figure at its empty-building value.

    PRD §3.1: "The registration carries the building's `name`, its `total_rentable_sf` (at least 1 square foot), the published rate card as `market_base_rent_psf_annual` (strictly positive, 2 decimal places), the budgeted common-area recovery as `operating_expense_annual_psf` (zero or more, 2 decimal places), and the size of the parking pool as `total_parking_stalls` (zero or more)."
    PRD §3.1: "A freshly registered building has no lease book and no allocations, so all its derived figures start from the empty set: `anchor_rentable_sf`, `independent_rentable_sf` and `leased_rentable_sf` are 0, `vacant_rentable_sf` equals `total_rentable_sf`, `anchor_share_pct` reads 0.0000, `tenant_mix_posture` reads `BALANCED`, `mix_freeze_override` is false, `staff_allocated_stalls` and `patient_allocated_stalls` are 0, and `unallocated_stalls` equals `total_parking_stalls`."
    PRD §2.4: "`version` is an integer that begins at 1 when the row is created and increases by exactly 1 on every mutation, again including cascaded mutations."

    Design: Corner/entities/building_creation_returns_all_declared_fields
    """
    payload = f.create_building_payload(name="Meridian Medical Plaza")
    created = validate_success(api.create_building(payload, PORTFOLIO_ADMIN), 201)

    assert created["name"] == "Meridian Medical Plaza"
    assert created["total_rentable_sf"] == 100000
    assert_money_equals(created["market_base_rent_psf_annual"], 30.00,
                        "market_base_rent_psf_annual")
    assert_money_equals(created["operating_expense_annual_psf"], 9.60,
                        "operating_expense_annual_psf")
    assert created["total_parking_stalls"] == 400
    assert_share_equals(created["patient_min_reserve_pct"], 0.60, "patient_min_reserve_pct")
    assert created["version"] == 1, "a newly created row carries version 1"

    read = validate_success(api.get_building(created["id"], PORTFOLIO_ADMIN))
    assert read["anchor_rentable_sf"] == 0
    assert read["independent_rentable_sf"] == 0
    assert read["leased_rentable_sf"] == 0
    assert read["vacant_rentable_sf"] == 100000
    assert_share_equals(read["anchor_share_pct"], 0.0000, "anchor_share_pct")
    assert read["tenant_mix_posture"] == "BALANCED"
    assert read["mix_freeze_override"] is False
    assert_parking_counters(read, staff=0, patient=0, unallocated=400)
    assert read["version"] == 1, "a read never advances version"


def test_suite_read_back_matches_registration(api):
    """A suite reads back with the building taken from the path, the declared
    clinical attributes, and the initial vacant occupancy state.

    PRD §3.1: "Suites are added to a building one at a time, and the `building_id` of a new suite is taken from the building addressed in the path rather than from the payload."
    PRD §3.1: "The payload supplies `suite_number`, which must be unique within that building; `floor`, at least 1; `rentable_sf`, at least 1; and `suite_class`, which is one of `STANDARD_EXAM`, `IMAGING`, `PROCEDURE` or `INFUSION`."
    PRD §3.1: "It also declares the unreserved electrical service at the suite panel as `power_amps_available`, and may optionally declare `medical_gas_available` (whether piped medical gas and vacuum are present, defaulting to false), `shielding_certified` (defaulting to false) and `lead_thickness_mm` (the verified lead-equivalent thickness, null until a shielding review certifies one)."
    PRD §3.1: "Every new suite begins `VACANT` with `last_vacated_on` null, and adding a suite advances the owning building's `version` by 1."

    Design: Corner/entities/suite_retrieval_returns_stored_suite
    """
    building = fx.register_building(api)
    suite = fx.register_suite(api, building["id"], suite_number="150", floor=1,
                              rentable_sf=8000, suite_class="IMAGING",
                              power_amps_available=600, medical_gas_available=False,
                              shielding_certified=True)

    read = validate_success(api.get_suite(suite["id"], LEASING_AGENT))
    assert read["building_id"] == building["id"], "building_id comes from the path"
    assert read["suite_number"] == "150"
    assert read["floor"] == 1
    assert read["rentable_sf"] == 8000
    assert read["suite_class"] == "IMAGING"
    assert read["power_amps_available"] == 600
    assert read["medical_gas_available"] is False
    assert read["shielding_certified"] is True
    assert read["occupancy_status"] == "VACANT"
    assert read["last_vacated_on"] is None
    assert read["version"] == 1

    parent = validate_success(api.get_building(building["id"], PORTFOLIO_ADMIN))
    assert parent["version"] == building["version"] + 1, (
        "adding a suite advances the owning building's version by 1")


def test_suite_listing_filters_by_class_and_pages(api):
    """The suite roster narrows by clinical class and pages with the four
    declared meta fields, defaulting to a page size of 10.

    PRD §3.1: "A building's suite roster can be listed and narrowed by `suite_class` and by `occupancy_status`."
    PRD §2.3: "`limit` controls page size: it defaults to 10, may not be smaller than 1, and may not be larger than 100."
    PRD §2.3: "Paged responses populate four fields inside `meta`: the `limit` and `offset` actually applied, `total_count` giving the number of rows matching the filter before paging, and `has_more` indicating whether rows remain beyond the current page."
    PRD §2.3: "Unless a subsection below states otherwise, list results are ordered by `created_at` ascending."

    Design: Corner/entities/suite_listing_filters_by_class_with_pagination
    """
    building = fx.register_building(api)
    imaging_a = fx.register_suite(api, building["id"], suite_number="150", floor=1,
                                  rentable_sf=8000, suite_class="IMAGING",
                                  power_amps_available=600)
    imaging_b = fx.register_suite(api, building["id"], suite_number="151", floor=1,
                                  rentable_sf=6000, suite_class="IMAGING",
                                  power_amps_available=500)
    standard = fx.register_suite(api, building["id"], suite_number="210", floor=2,
                                 rentable_sf=5000, suite_class="STANDARD_EXAM",
                                 power_amps_available=200)

    page_one, meta_one = validate_paginated(api.list_building_suites(
        building["id"], LEASING_AGENT, params={"suite_class": "IMAGING", "limit": 1, "offset": 0}))
    assert ids_of(page_one) == [imaging_a["id"]]
    assert_total_count(meta_one, 2)
    assert meta_one["limit"] == 1
    assert meta_one["offset"] == 0
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(api.list_building_suites(
        building["id"], LEASING_AGENT, params={"suite_class": "IMAGING", "limit": 1, "offset": 1}))
    assert ids_of(page_two) == [imaging_b["id"]]
    assert_total_count(meta_two, 2)
    assert meta_two["offset"] == 1
    assert meta_two["has_more"] is False

    assert standard["id"] not in ids_of(page_one) + ids_of(page_two), (
        "the STANDARD_EXAM suite never appears in an IMAGING-filtered page")

    everything, meta_all = validate_paginated(
        api.list_building_suites(building["id"], LEASING_AGENT))
    assert ids_of(everything) == [imaging_a["id"], imaging_b["id"], standard["id"]]
    assert_total_count(meta_all, 3)
    assert meta_all["limit"] == 10, "limit defaults to 10"
    assert meta_all["offset"] == 0
    assert meta_all["has_more"] is False


def test_lease_read_by_unknown_id_reports_lease_not_found(api):
    """A well-formed identifier that names no lease is a 404 about the lease
    reference, not about an empty store.

    PRD §2.8: "A lease reference in the path or the body — including a `master_lease_id` on a sublease and a `lease_id` on a booking or a parking allocation — identifies an existing lease, otherwise `ERR_LEASE_NOT_FOUND` (404)."

    Design: Corner/entities/lease_get_unknown_id_returns_lease_not_found
    """
    fx.register_building(api)

    validate_error(api.get_lease(NON_EXISTENT_UUID, LEASING_AGENT),
                   ApiErrorId.ERR_LEASE_NOT_FOUND)

    rows, meta = validate_paginated(api.list_leases(LEASING_AGENT))
    assert rows == [], "no lease has ever been created"
    assert_total_count(meta, 0)


def test_tenant_registration_without_npi_is_rejected(api):
    """The National Provider Identifier is a required input: omitting it is a
    malformed request and persists nothing.

    PRD §3.2: "It carries the practice's `legal_name`; an `affiliation` of `HEALTH_SYSTEM_ANCHOR`, `HEALTH_SYSTEM_AFFILIATED` or `INDEPENDENT_PRACTICE`, which is the tenant-mix classification and the input to anchor concentration; a `primary_specialty` drawn from `PRIMARY_CARE`, `CARDIOLOGY`, `ORTHOPEDICS`, `RADIOLOGY`, `ONCOLOGY`, `OPHTHALMOLOGY` and `GASTROENTEROLOGY`, which is what exclusive-use and radius conflict detection compares; a boolean `is_physician_owned`, true when physicians hold an ownership interest, which is the flag that decides whether third-party appraisal support is required at all; and an `npi`, the National Provider Identifier, which must be exactly 10 digits."
    PRD §2.8: "The body and query string parse; every required input field is present and non-null; every enum-typed value is a declared member of its enumeration; every money field is a non-negative decimal with at most 2 decimal places; every date is a valid ISO-8601 value; `period_end` is on or after `period_start`; `term_end` is strictly later than `term_start`; `window_end` is strictly later than `window_start`; `opinion_high_psf` is at least `opinion_low_psf`; `stall_count` is at least 1; `occupant_count` is at least 1; `landlord_share_pct` and `landlord_share_pct_override` both lie between 0.0000 and 1.0000 inclusive; a clock value is not earlier than the current logical clock; and a `payment_amount` is exactly the invoice's outstanding balance."
    PRD §2.8: "Any failure is `ERR_INVALID_REQUEST` (400)."
    PRD §3.2: "A new tenant starts with `delinquency_event_count` at 0, both risk scores at 0 and `compliance_watch_status` reading `CLEAR`."

    Design: Corner/entities/tenant_creation_missing_required_npi_rejected
    """
    fx.register_building(api)

    without_npi = f.create_tenant_payload(legal_name="Northgate Medical Group PC",
                                          affiliation="INDEPENDENT_PRACTICE",
                                          primary_specialty="GASTROENTEROLOGY",
                                          is_physician_owned=False)
    without_npi.pop("npi")
    validate_error(api.create_tenant(without_npi, PORTFOLIO_ADMIN),
                   ApiErrorId.ERR_INVALID_REQUEST)

    complete = f.create_tenant_payload(legal_name="Northgate Medical Group PC",
                                       affiliation="INDEPENDENT_PRACTICE",
                                       primary_specialty="GASTROENTEROLOGY",
                                       is_physician_owned=False,
                                       npi="1234568041")
    tenant = validate_success(api.create_tenant(complete, PORTFOLIO_ADMIN), 201)
    assert tenant["npi"] == "1234568041"
    assert tenant["compliance_watch_status"] == "CLEAR"
    assert tenant["referral_compliance_risk_score"] == 0
    assert tenant["strict_cumulative_risk_score"] == 0
    assert tenant["delinquency_event_count"] == 0


def test_patient_reserve_pct_defaults_to_point_six_and_caps_staff_stalls(api):
    """A building registered without a patient reserve fraction reads 0.60, so
    a 400-stall pool admits 160 staff stalls and refuses 161.

    PRD §3.1: "A sixth input, `patient_min_reserve_pct`, is optional and expresses the fraction of the pool that must remain available to patients; when omitted it defaults to 0.60, and it is a 4-decimal fraction between 0.0000 and 1.0000."
    PRD §3.9: "The patient-reserve test comes second and applies only to `STAFF` requests: the reserve minimum is `total_parking_stalls` multiplied by `patient_min_reserve_pct` and raised to the next whole stall by ceiling — fractional reserves always round up in the patients' favour — and the request is refused with `ERR_PATIENT_PARKING_RESERVE_BREACH` when `total_parking_stalls` less the post-request staff total would fall below that minimum."
    PRD §3.9: "In a 400-stall building reserving 0.60, the minimum is 240 stalls and staff may therefore hold at most 160: a first staff request for 160 leaves exactly 240 non-staff stalls and is accepted, while a request for 161 would leave 239 and is refused."
    PRD §3.9: "The building's three derived counters are then recomputed: `staff_allocated_stalls` is the summed `stall_count` of active staff allocations, `patient_allocated_stalls` the summed `stall_count` of active patient allocations, and `unallocated_stalls` is `total_parking_stalls` less those two sums."

    Design: Corner/entities/building_patient_reserve_pct_defaults_to_sixty_percent
    """
    payload = f.create_building_payload()
    payload.pop("patient_min_reserve_pct")
    building = validate_success(api.create_building(payload, PORTFOLIO_ADMIN), 201)
    assert_share_equals(building["patient_min_reserve_pct"], 0.60, "patient_min_reserve_pct")

    suite = fx.register_suite(api, building["id"])
    tenant = fx.register_tenant(api)
    lease = fx.draft_lease(api, building["id"], suite["id"], tenant["id"])

    current = fx.read_building(api, building["id"], PROPERTY_MANAGER)
    over_reserve = f.create_parking_allocation_payload(current["version"], building["id"],
                                                       lease["id"], "STAFF", 161)
    validate_error(api.create_parking_allocation(over_reserve, PROPERTY_MANAGER),
                   ApiErrorId.ERR_PATIENT_PARKING_RESERVE_BREACH)

    current = fx.read_building(api, building["id"], PROPERTY_MANAGER)
    at_ceiling = f.create_parking_allocation_payload(current["version"], building["id"],
                                                     lease["id"], "STAFF", 160)
    allocation = validate_success(api.create_parking_allocation(at_ceiling, PROPERTY_MANAGER), 201)
    assert allocation["status"] == "ACTIVE"
    assert allocation["stall_count"] == 160

    after = fx.read_building(api, building["id"], PROPERTY_MANAGER)
    assert_parking_counters(after, staff=160, patient=0, unallocated=240)


def test_suite_optional_clinical_flags_default_to_false_and_null(api):
    """Omitting the three optional clinical attributes yields false, false and
    null — the values the downstream imaging checks read.

    PRD §3.1: "It also declares the unreserved electrical service at the suite panel as `power_amps_available`, and may optionally declare `medical_gas_available` (whether piped medical gas and vacuum are present, defaulting to false), `shielding_certified` (defaulting to false) and `lead_thickness_mm` (the verified lead-equivalent thickness, null until a shielding review certifies one)."
    PRD §3.1: "Every new suite begins `VACANT` with `last_vacated_on` null, and adding a suite advances the owning building's `version` by 1."

    Design: Corner/entities/suite_optional_flags_default_false_when_omitted
    """
    building = fx.register_building(api)

    payload = {"suite_number": "150", "floor": 1, "rentable_sf": 8000,
               "suite_class": "IMAGING", "power_amps_available": 600}
    suite = validate_success(api.create_suite(building["id"], payload, PORTFOLIO_ADMIN), 201)

    assert suite["medical_gas_available"] is False
    assert suite["shielding_certified"] is False
    assert suite["lead_thickness_mm"] is None
    assert suite["occupancy_status"] == "VACANT"


def test_lease_term_months_measured_to_the_exclusive_end(api):
    """A term of 2026-09-01 through 2027-08-31 derives twelve months, so the
    twelve-month minimum is met rather than missed by one.

    PRD §3.3: "Take the difference in years between that exclusive end and `term_start` and multiply by 12, add the difference in their month numbers, and then, if the exclusive end's day of the month is earlier than `term_start`'s day of the month, subtract one whole month because the anniversary day has not been reached."
    PRD §3.3: "A term running from 1 September 2026 through 31 August 2027 therefore yields exactly 12 months and is admissible, while the same term ending one day earlier, on 30 August 2027, yields 11 and is refused with `ERR_MIN_TERM_NOT_MET`; a term of 31 January 2026 through 28 February 2026 yields 1."
    PRD §3.3: "A new lease is created in status `DRAFT` with `fmv_certification_status` reading `NOT_STARTED`, `revision_round` at 0 and `version` at 1."

    Design: Corner/entities/lease_term_months_computed_from_closed_term_dates
    """
    building = fx.register_building(api)
    suite = fx.register_suite(api, building["id"])
    tenant = fx.register_tenant(api)

    payload = f.create_lease_payload(building["id"], suite["id"], tenant["id"],
                                     term_start="2026-09-01", term_end="2027-08-31")
    lease = validate_success(api.create_lease(payload, LEASING_AGENT), 201)

    assert lease["term_months"] == 12, (
        "the count runs to the exclusive end 2027-09-01, giving 12 whole months")
    assert lease["status"] == "DRAFT"
    assert lease["fmv_certification_status"] == "NOT_STARTED"


def test_lease_system_fields_are_server_minted_at_version_one(api):
    """The client supplies no identifier and no timestamps: the lease comes back
    with a server-minted UUID, both timestamps, version 1 and every guardrail
    boolean false.

    PRD §2.4: "Every persisted resource carries a server-minted `id`. It is a UUID and it carries no type prefix — a lease identifier and a building identifier are indistinguishable by shape, and clients must not attempt to infer a resource's type from its identifier."
    PRD §2.4: "`created_at` is the ISO 8601 UTC instant at which the row was created, rendered with exactly three fractional-second digits."
    PRD §3.3: "A new lease is created in status `DRAFT` with `fmv_certification_status` reading `NOT_STARTED`, `revision_round` at 0 and `version` at 1."
    PRD §3.3: "The six document-and-guardrail booleans — `signed_lease_on_file`, `master_lease_consent_on_file`, `space_sharing_schedule_on_file`, `after_hours_authorized`, `rent_concession_locked` and `holdover_premium_applied` — all start false."

    Design: Corner/entities/lease_system_fields_generated_with_version_one
    """
    building = fx.register_building(api)
    suite = fx.register_suite(api, building["id"])
    tenant = fx.register_tenant(api)

    payload = f.create_lease_payload(building["id"], suite["id"], tenant["id"])
    assert "id" not in payload and "version" not in payload, (
        "the drafting payload names no identifier and no version")
    created = validate_success(api.create_lease(payload, LEASING_AGENT), 201)

    assert is_valid_uuid(created["id"]), "the lease id is a server-minted UUID"
    assert is_iso8601_timestamp(created["created_at"])
    assert is_iso8601_timestamp(created["updated_at"])
    assert created["version"] == 1
    assert created["revision_round"] == 0

    read = validate_success(api.get_lease(created["id"], LEASING_AGENT))
    assert read["id"] == created["id"]
    assert read["version"] == 1, "a read never advances version"
    for flag in ("signed_lease_on_file", "master_lease_consent_on_file",
                 "space_sharing_schedule_on_file", "after_hours_authorized",
                 "rent_concession_locked", "holdover_premium_applied"):
        assert read[flag] is False, "{} must start false".format(flag)


def test_lease_draft_rejects_undeclared_type_and_reversed_term(api):
    """An undeclared `lease_type` and a term whose end precedes its start are
    both malformed requests, and neither persists a lease.

    PRD §3.3: "The drafting payload names the three parties to the space — the `building_id` of the building, the `suite_id` of the demised suite, which must belong to that building, and the `tenant_id` of the practice taking the space — and declares the deal's shape through `lease_type`, which is `DIRECT` for a landlord-to-practice lease, `MASTER` for a landlord-to-health-system lease that may be sublet, or `SUBLEASE` for a health-system-to-practice lease sitting under a master."
    PRD §2.8: "The body and query string parse; every required input field is present and non-null; every enum-typed value is a declared member of its enumeration; every money field is a non-negative decimal with at most 2 decimal places; every date is a valid ISO-8601 value; `period_end` is on or after `period_start`; `term_end` is strictly later than `term_start`; `window_end` is strictly later than `window_start`; `opinion_high_psf` is at least `opinion_low_psf`; `stall_count` is at least 1; `occupant_count` is at least 1; `landlord_share_pct` and `landlord_share_pct_override` both lie between 0.0000 and 1.0000 inclusive; a clock value is not earlier than the current logical clock; and a `payment_amount` is exactly the invoice's outstanding balance."
    PRD §2.8: "Any failure is `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/lease_invalid_lease_type_enum_rejected
    """
    building = fx.register_building(api)
    suite = fx.register_suite(api, building["id"])
    tenant = fx.register_tenant(api)

    bad_enum = f.create_lease_payload(building["id"], suite["id"], tenant["id"],
                                      lease_type="GROUND")
    validate_error(api.create_lease(bad_enum, LEASING_AGENT), ApiErrorId.ERR_INVALID_REQUEST)

    reversed_term = f.create_lease_payload(building["id"], suite["id"], tenant["id"],
                                           term_start="2029-08-31", term_end="2026-09-01")
    validate_error(api.create_lease(reversed_term, LEASING_AGENT),
                   ApiErrorId.ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(
        api.list_leases(LEASING_AGENT, params={"building_id": building["id"]}))
    assert rows == [], "neither rejected request persisted a lease"
    assert_total_count(meta, 0)


def test_booking_rejects_zero_occupants_and_zero_length_window(api):
    """A booking must carry at least one occupant and a window whose end is
    strictly later than its start.

    PRD §3.9: "A booking is created by a `LeasingAgent` or by the `TenantPortalUser` themselves, naming the `shared_space_id`, the `lease_id` consuming the space, the `window_start` and `window_end` bounding the occupancy — again inclusive start, exclusive end, with the end required to be later than the start — and the `occupant_count` of at least 1 that this booking contributes to the room's load."
    PRD §2.8: "The body and query string parse; every required input field is present and non-null; every enum-typed value is a declared member of its enumeration; every money field is a non-negative decimal with at most 2 decimal places; every date is a valid ISO-8601 value; `period_end` is on or after `period_start`; `term_end` is strictly later than `term_start`; `window_end` is strictly later than `window_start`; `opinion_high_psf` is at least `opinion_low_psf`; `stall_count` is at least 1; `occupant_count` is at least 1; `landlord_share_pct` and `landlord_share_pct_override` both lie between 0.0000 and 1.0000 inclusive; a clock value is not earlier than the current logical clock; and a `payment_amount` is exactly the invoice's outstanding balance."
    PRD §2.8: "Any failure is `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/booking_zero_occupant_count_rejected
    """
    building = fx.register_building(api)
    suite = fx.register_suite(api, building["id"])
    space = fx.register_shared_space(api, building["id"],
                                     name="Second Floor Shared Waiting Room",
                                     space_type="WAITING_ROOM", capacity_seats=24,
                                     opens_at="07:00", closes_at="19:00")
    tenant = fx.register_tenant(api)
    lease = fx.draft_lease(api, building["id"], suite["id"], tenant["id"])
    fx.file_attestation(api, lease["id"], "SPACE_SHARING_SCHEDULE")

    zero_occupants = f.create_booking_payload(space["id"], lease["id"],
                                              "2026-08-05T09:00:00Z",
                                              "2026-08-05T11:00:00Z", 0)
    validate_error(api.create_booking(zero_occupants, LEASING_AGENT),
                   ApiErrorId.ERR_INVALID_REQUEST)

    zero_length = f.create_booking_payload(space["id"], lease["id"],
                                           "2026-08-05T09:00:00Z",
                                           "2026-08-05T09:00:00Z", 4)
    validate_error(api.create_booking(zero_length, LEASING_AGENT),
                   ApiErrorId.ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(
        api.list_bookings(LEASING_AGENT, params={"shared_space_id": space["id"]}))
    assert rows == [], "neither rejected booking was persisted"
    assert_total_count(meta, 0)


def test_ti_line_item_carries_no_version_and_is_only_appended(api):
    """An appended construction line carries id and created_at but neither
    updated_at nor version, and the append rolls the project totals forward.

    PRD §2.4: "`TILineItem` is the single exception. A construction line item is immutable once appended and is never deleted, so it carries only `id` and `created_at`: it has no `updated_at` field and no `version` field at all."
    PRD §3.6: "The server sets the line's `ti_project_id` from the addressed project rather than from the request body, and assigns `sequence_no`, a 1-based index that increases monotonically within the project and is the pinned processing order for every cost figure derived below."
    PRD §3.6: "Line items are immutable and are never deleted, so the input set only ever grows; a project's lines are readable in `sequence_no` order and can be narrowed by `category`."
    PRD §3.6: "First, the category rule: a line whose `category` is `SHIELDING` on a project whose `target_suite_class` is `IMAGING` is borne entirely by the landlord, so its `effective_share_pct` is 1.0000 — the landlord pays 100% of radiation shielding in an imaging build-out regardless of anything else the project or the line says."
    PRD §3.6: "From the resolved share, `landlord_share_amount` is the line's `cost_amount` multiplied by `effective_share_pct`, rounded half up to 2 decimal places, and `tenant_share_amount` is the line's `cost_amount` **less** that rounded landlord amount."
    PRD §3.6: "The project's totals are then sums of the **already-rounded** per-line figures, taken over the lines in `sequence_no` order: `landlord_committed_amount` sums the per-line landlord amounts, `tenant_committed_amount` sums the per-line tenant amounts, and `allowance_remaining` is `authorized_allowance_total` less `landlord_committed_amount`."
    PRD §3.6: "Appending a line also increments `line_item_count` by 1 and advances the project's `version` by 1."

    Design: Corner/entities/ti_line_item_is_immutable_and_versionless
    """
    building = fx.register_building(api)
    suite = fx.register_suite(api, building["id"])
    tenant = fx.register_tenant(api)
    lease = fx.draft_lease(api, building["id"], suite["id"], tenant["id"])
    project = fx.open_ti_project(api, lease["id"], suite["id"],
                                 target_suite_class="IMAGING", lead_thickness_mm=2.5,
                                 power_amps_requested=150, medical_gas_requested=False,
                                 authorized_allowance_total=500000.00,
                                 landlord_share_pct=0.60)

    payload = f.create_ti_line_item_payload(project["version"],
                                            description="Lead shielding, walls and ceiling",
                                            category="SHIELDING", cost_amount=88000.00)
    line = validate_success(api.create_ti_line_item(project["id"], payload, LEASING_AGENT), 201)

    assert line["ti_project_id"] == project["id"], "ti_project_id comes from the addressed project"
    assert line["sequence_no"] == 1, "sequence_no is a 1-based index within the project"
    assert_share_equals(line["effective_share_pct"], 1.0000, "effective_share_pct")
    assert_money_equals(line["landlord_share_amount"], 88000.00, "landlord_share_amount")
    assert_money_equals(line["tenant_share_amount"], 0.00, "tenant_share_amount")
    assert_line_item_has_no_version_fields(line)

    rows, meta = validate_paginated(api.list_ti_line_items(project["id"], LEASING_AGENT))
    assert_total_count(meta, 1)
    assert ids_of(rows) == [line["id"]]
    for row in rows:
        assert_line_item_has_no_version_fields(row)

    after = validate_success(api.get_ti_project(project["id"], LEASING_AGENT))
    assert after["line_item_count"] == 1
    assert_money_equals(after["landlord_committed_amount"], 88000.00,
                        "landlord_committed_amount")
    assert_money_equals(after["tenant_committed_amount"], 0.00, "tenant_committed_amount")
    assert_money_equals(after["allowance_remaining"], 412000.00, "allowance_remaining")
    assert after["version"] == project["version"] + 1, (
        "appending a line advances the project's version by 1")


def test_suite_creation_under_unknown_building_reports_building_not_found(api):
    """A suite only attaches to an existing parent building; the nested create
    against an unknown building reports the missing building and creates nothing.

    PRD §2.8: "A `building_id` appearing in the path or the body identifies an existing building — otherwise `ERR_BUILDING_NOT_FOUND` (404)."
    PRD §2.8: "This guards `GET /buildings/{id}`, `GET /buildings/{id}/suites`, `GET /buildings/{id}/shared-spaces`, `POST /buildings/{id}/suites`, `POST /buildings/{id}/shared-spaces`, `POST /buildings/{id}/mix-freeze`, `POST /leases` and `POST /parking-allocations`."
    PRD §2.8: "For a nested collection such as a building's suites or a lease's appraisals, the parent named in the path is looked up first, so a request against a suite collection under a building that does not exist reports the missing building and never reports anything about the suite payload."

    Design: Corner/entities/suite_creation_under_unknown_building_returns_building_not_found
    """
    building = fx.register_building(api)

    payload = f.create_suite_payload()
    validate_error(api.create_suite(NON_EXISTENT_UUID, payload, PORTFOLIO_ADMIN),
                   ApiErrorId.ERR_BUILDING_NOT_FOUND)

    rows, meta = validate_paginated(api.list_building_suites(building["id"], PORTFOLIO_ADMIN))
    assert rows == [], "the rejected suite was not attached to the real building either"
    assert_total_count(meta, 0)


def test_lease_draft_rejects_suite_belonging_to_another_building(api):
    """A lease naming one building together with a suite from another is refused
    on the suite reference, and an unknown tenant is refused on the tenant.

    PRD §2.8: "A `suite_id` appearing in the path or the body identifies an existing suite, and where a building is named in the same request the suite's `building_id` matches it — otherwise `ERR_SUITE_NOT_FOUND` (404)."
    PRD §2.8: "A `tenant_id` appearing in the path or the body identifies an existing tenant — otherwise `ERR_TENANT_NOT_FOUND` (404)."
    PRD §3.3: "The drafting payload names the three parties to the space — the `building_id` of the building, the `suite_id` of the demised suite, which must belong to that building, and the `tenant_id` of the practice taking the space — and declares the deal's shape through `lease_type`, which is `DIRECT` for a landlord-to-practice lease, `MASTER` for a landlord-to-health-system lease that may be sublet, or `SUBLEASE` for a health-system-to-practice lease sitting under a master."

    Design: Corner/entities/lease_cross_building_suite_reference_rejected
    """
    building_a = fx.register_building(api, name="Meridian Medical Plaza")
    building_b = fx.register_building(api, name="Lakeside Health Pavilion",
                                      total_rentable_sf=60000, total_parking_stalls=200)
    suite_a = fx.register_suite(api, building_a["id"], suite_number="210", floor=2)
    suite_b = fx.register_suite(api, building_b["id"], suite_number="110", floor=1)
    tenant = fx.register_tenant(api)

    cross_building = f.create_lease_payload(building_a["id"], suite_b["id"], tenant["id"])
    validate_error(api.create_lease(cross_building, LEASING_AGENT),
                   ApiErrorId.ERR_SUITE_NOT_FOUND)

    unknown_tenant = f.create_lease_payload(building_a["id"], suite_a["id"], NON_EXISTENT_UUID)
    validate_error(api.create_lease(unknown_tenant, LEASING_AGENT),
                   ApiErrorId.ERR_TENANT_NOT_FOUND)

    well_formed = f.create_lease_payload(building_a["id"], suite_a["id"], tenant["id"])
    lease = validate_success(api.create_lease(well_formed, LEASING_AGENT), 201)
    assert lease["building_id"] == building_a["id"]
    assert lease["suite_id"] == suite_a["id"]


def test_sublease_master_edge_is_reachable_by_filtered_lease_list(api):
    """A sublease records the master it sits under, and the master_lease_id
    filter is the reverse path back to it.

    PRD §3.3: "A sublease must name the master it sits under through `master_lease_id`, and that reference must point at a lease whose own `lease_type` is `MASTER`; for a direct or master lease `master_lease_id` must be null."
    PRD §3.3: "Leases can be listed and narrowed by `building_id`, `suite_id`, `tenant_id`, `master_lease_id`, `status` and `lease_type`; the `master_lease_id` filter is how the subleases hanging under a hospital master lease are discovered."
    PRD §3.3: "Take the difference in years between that exclusive end and `term_start` and multiply by 12, add the difference in their month numbers, and then, if the exclusive end's day of the month is earlier than `term_start`'s day of the month, subtract one whole month because the anniversary day has not been reached."

    Design: Corner/entities/sublease_master_link_is_reachable_by_filtered_list
    """
    building = fx.register_building(api)
    master_suite = fx.register_suite(api, building["id"], suite_number="100", floor=1,
                                     rentable_sf=12000, power_amps_available=400)
    sub_suite = fx.register_suite(api, building["id"], suite_number="210", floor=2,
                                  rentable_sf=5000, power_amps_available=200)
    anchor_tenant = fx.register_tenant(api, legal_name="Meridian Health System Clinics",
                                       affiliation="HEALTH_SYSTEM_ANCHOR",
                                       primary_specialty="PRIMARY_CARE")
    sub_tenant = fx.register_tenant(api, legal_name="Northgate Medical Group PC",
                                    affiliation="INDEPENDENT_PRACTICE",
                                    primary_specialty="GASTROENTEROLOGY")

    master = fx.draft_lease(api, building["id"], master_suite["id"], anchor_tenant["id"],
                            lease_type="MASTER", term_start="2026-09-01",
                            term_end="2031-08-31", base_rent_psf_annual=28.00)

    sub_payload = f.create_lease_payload(building["id"], sub_suite["id"], sub_tenant["id"],
                                         lease_type="SUBLEASE", master_lease_id=master["id"],
                                         term_start="2027-01-01", term_end="2030-12-31")
    sublease = validate_success(api.create_lease(sub_payload, LEASING_AGENT), 201)
    assert sublease["lease_type"] == "SUBLEASE"
    assert sublease["master_lease_id"] == master["id"]
    assert sublease["term_months"] == 48, (
        "2027-01-01 to the exclusive end 2031-01-01 is 48 whole months")

    subs, subs_meta = validate_paginated(
        api.list_leases(LEASING_AGENT, params={"master_lease_id": master["id"]}))
    assert_total_count(subs_meta, 1)
    assert ids_of(subs) == [sublease["id"]]

    masters, masters_meta = validate_paginated(api.list_leases(
        LEASING_AGENT, params={"building_id": building["id"], "lease_type": "MASTER"}))
    assert_total_count(masters_meta, 1)
    assert ids_of(masters) == [master["id"]]

    master_read = validate_success(api.get_lease(master["id"], LEASING_AGENT))
    assert master_read["master_lease_id"] is None, (
        "for a direct or master lease master_lease_id must be null")
