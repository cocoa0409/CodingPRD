"""Resource-level behaviour: what a create returns, what a read returns, how a
list filters and pages, and how the server refuses a malformed or dangling
reference."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    DEFAULT_INVOICE_DUE_DAYS,
    DEFAULT_MAX_DAILY_ORDERS,
    DEFAULT_NOTICE_LEAD_DAYS,
    ERR_CYCLE_NOT_FOUND,
    ERR_INSPECTOR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PARCEL_NOT_FOUND,
    ERR_PROGRAM_NOT_FOUND,
    ERR_ZONE_ALREADY_EVALUATED,
    OMIT,
    PROGRAM_TYPE_CHIPPER,
    RESPONSE_TYPE_ARRAY,
    RESPONSE_TYPE_OBJECT,
    add_zone,
    assert_append_only_row,
    assert_common_fields,
    assert_envelope_meta,
    assert_error_response_type,
    assert_instant,
    assert_posture,
    assert_program_capacity,
    assert_risk,
    assert_version,
    assert_zone_grade,
    contractor_payload,
    create_contractor,
    create_cycle,
    create_inspector,
    create_parcel,
    create_program,
    enrollment_payload,
    get_contractor,
    get_inspector,
    get_program,
    ids_of,
    inspection_payload,
    list_enrollments,
    list_inspections,
    list_parcels,
    list_zone_evaluations,
    moderate_parcel_payload,
    next_apn,
    open_cycle,
    parcel_patch,
    parcel_payload,
    schedule_inspection,
    serve_notice,
    set_clock,
    zone_payload,
)
from test_helpers.test_users import (
    FIRE_MARSHAL_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    make_inspector_headers,
)

# A second dangling identifier, needed whenever one request must carry two
# unresolvable foreign keys at once.
SECOND_NON_EXISTENT_UUID = "00000000-0000-0000-0000-0000000000aa"


class TestParcelIntake:
    """Intake both stores what the assessor supplied and derives a first score."""

    def test_parcel_creation_returns_an_intake_scored_row(self, client):
        """A complete parcel POST answers 201 with the row already scored under
        the provisional variant and its inspection-derived posture still neutral.

        PRD: "Each parcel enters the inventory with its assessor parcel number in
        apn - non-empty and unique across the whole inventory, with a collision
        refused as ERR_APN_ALREADY_REGISTERED - together with the owner_name of
        record, the owner_email that will be used whenever a notice is served
        electronically, and the physical situs_address."

        PRD: "The intake-provisional variant runs at parcel creation and on any
        attribute update that changes a scoring field while the parcel has not yet
        been verified in the field; it takes the vegetation subscore from the
        owner's self-reported vegetation_type - 15 points for
        IRRIGATED_LANDSCAPE, 40 for GRASS, 75 for BRUSH and 90 for MIXED_CONIFER -
        and it uses a hardening credit of exactly 0.00, because no
        structure-hardening findings exist yet. It sets risk_score_basis to
        INTAKE_PROVISIONAL."

        PRD: "a score of 55.00 or above but below 75.00 is HIGH"

        PRD: "compliance_status is the parcel's derived defensible-space posture,
        initialised at intake to PENDING_INSPECTION and thereafter moving among
        COMPLIANT, NON_COMPLIANT, ABATEMENT_PENDING and EXEMPT as inspections,
        notices and abatement orders move. Alongside it the parcel keeps
        open_violation_count, initialised to 0, and last_passed_inspection_at_utc,
        which holds the completion instant of the most recent passing inspection on
        the parcel and stays null until one exists. inspection_priority_rank is
        null at intake and remains null until the first cycle advance ranks the
        inventory."

        PRD: "The response_type is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/entities/parcel_creation_returns_intake_scored_row
        """
        response = client.create_parcel(
            parcel_payload(
                apn="APN-1001",
                owner_name="Ann Reyes",
                owner_email="ann@example.com",
                situs_address="12 Ridge Rd",
                structure_present=True,
                lot_area_sqft=43560,
            ),
            headers=PROGRAM_ADMIN_HEADERS,
        )
        assert_envelope_meta(response, RESPONSE_TYPE_OBJECT)
        parcel = validate_success(response, 201)

        assert parcel["apn"] == "APN-1001"
        assert parcel["owner_name"] == "Ann Reyes"
        assert parcel["owner_email"] == "ann@example.com"
        assert parcel["situs_address"] == "12 Ridge Rd"
        assert parcel["roof_class"] == "CLASS_B"
        assert parcel["vegetation_type"] == "BRUSH"
        assert parcel["slope_pct"] == 30
        assert parcel["hazard_zone"] == "HIGH"
        assert parcel["access_constraint"] == "GATED"
        assert parcel["structure_present"] is True

        # 60 * 0.30 + 75 * 0.30 + 45 * 0.25 + 25 * 0.15 = 55.50, times 1.15.
        assert_risk(parcel, 63.83, "HIGH", basis="INTAKE_PROVISIONAL")
        assert_posture(parcel, "PENDING_INSPECTION", open_violation_count=0)
        assert parcel["inspection_priority_rank"] is None
        assert parcel["last_passed_inspection_at_utc"] is None
        assert_common_fields(parcel)


class TestContractorRead:
    """A read returns the stored row and performs no write of its own."""

    def test_contractor_retrieval_returns_the_registered_row(self, client):
        """GET on a contractor echoes every registered attribute and both ledger
        fields still standing at zero.

        PRD: "A contractor is registered with a business_name that must be
        non-empty and unique across the roster, an hourly_rate_cents crew labour
        rate of at least 1 cent per crew-hour, a mobilization_fee_cents flat
        mobilization charge that may be 0, a license_status of ACTIVE, SUSPENDED
        or REVOKED that defaults to ACTIVE, an insurance_expiry_utc
        liability-insurance expiry, and a max_daily_orders ceiling on how many jobs
        the crew can hold on any one calendar day, which must be at least 1 and
        defaults to 2. committed_crew_hours and completed_crew_hours both start at
        0."

        PRD: "A contractor's committed_crew_hours must always equal the sum of
        crew_hours across that contractor's orders whose status is AWARDED or
        WORK_COMPLETE; its completed_crew_hours is a lifetime tally that only ever
        grows."

        PRD: "version, an integer that starts at 1 when the resource is created
        and increments by exactly 1 on every successful mutation of that resource."

        Design: Corner/entities/contractor_retrieval_returns_stored_row
        """
        created = validate_success(
            client.create_contractor(
                contractor_payload(
                    business_name="Ridgeline Fuels LLC",
                    hourly_rate_cents=8600,
                    mobilization_fee_cents=32000,
                    license_status="ACTIVE",
                    insurance_expiry_utc="2027-06-30T00:00:00Z",
                    max_daily_orders=2,
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            201,
        )

        response = client.get_contractor(created["id"], headers=FIRE_MARSHAL_HEADERS)
        assert_envelope_meta(response, RESPONSE_TYPE_OBJECT)
        contractor = validate_success(response)

        assert contractor["id"] == created["id"]
        assert contractor["business_name"] == "Ridgeline Fuels LLC"
        assert contractor["hourly_rate_cents"] == 8600
        assert contractor["mobilization_fee_cents"] == 32000
        assert contractor["max_daily_orders"] == 2
        assert contractor["license_status"] == "ACTIVE"
        assert_instant(contractor["insurance_expiry_utc"], "2027-06-30T00:00:00Z")
        assert contractor["committed_crew_hours"] == 0
        assert contractor["completed_crew_hours"] == 0
        assert_version(contractor, 1)


class TestParcelListing:
    """The risk_class filter is applied to the derived band, then paged."""

    def test_parcel_listing_filters_by_risk_class_and_pages_the_filtered_set(
        self, client
    ):
        """With two HIGH parcels and one MODERATE parcel, limit 1 over
        risk_class HIGH returns one row of a filtered total of two.

        PRD: "Parcel listings can be narrowed by community_id, by
        compliance_status and by risk_class, and paged with limit and offset."

        PRD: "List responses populate four pagination fields inside meta: limit
        and offset echo the effective values used to build the page, total_count
        reports the number of records matching the filter before pagination was
        applied, and has_more is true when records remain beyond the current page."

        PRD: "a score of 35.00 or above but below 55.00 is MODERATE"

        Design: Corner/entities/parcel_listing_filters_by_risk_class_with_pagination
        """
        high_one = create_parcel(client, parcel_payload(apn="APN-1101"))
        high_two = create_parcel(client, parcel_payload(apn="APN-1102"))
        moderate = create_parcel(client, moderate_parcel_payload(apn="APN-1103"))
        assert high_one["risk_class"] == "HIGH"
        assert high_two["risk_class"] == "HIGH"
        assert_risk(moderate, 35.25, "MODERATE")

        response = client.list_parcels(
            headers=PROGRAM_ADMIN_HEADERS,
            params={"risk_class": "HIGH", "limit": 1, "offset": 0},
        )
        assert_envelope_meta(response, RESPONSE_TYPE_ARRAY)
        first_page, meta = validate_paginated(response)

        assert len(first_page) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert first_page[0]["id"] in (high_one["id"], high_two["id"])
        assert moderate["id"] not in ids_of(first_page)

        second_page, meta = list_parcels(client, risk_class="HIGH", limit=1, offset=1)
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert len(second_page) == 1
        assert second_page[0]["id"] != first_page[0]["id"]
        assert sorted(ids_of(first_page) + ids_of(second_page)) == sorted(
            [high_one["id"], high_two["id"]]
        )

        unfiltered, meta = list_parcels(client, limit=10)
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert moderate["id"] in ids_of(unfiltered)


class TestUnknownIdentifier:
    """A dangling path referent is a 404, never an empty success."""

    def test_inspector_get_on_an_unknown_id_answers_not_found(self, client):
        """A syntactically valid identifier that names no inspector answers 404
        ERR_INSPECTOR_NOT_FOUND inside the error envelope.

        PRD: "Path segments are resolved strictly left to right, and the first
        segment that fails to resolve determines the error."

        PRD: "Each missing referent has its own error identifier and all of them
        answer with HTTP 404: ERR_CYCLE_NOT_FOUND, ERR_PARCEL_NOT_FOUND,
        ERR_COMMUNITY_NOT_FOUND, ERR_INSPECTOR_NOT_FOUND, ERR_CONTRACTOR_NOT_FOUND,
        ERR_INSPECTION_NOT_FOUND, ERR_ZONE_EVALUATION_NOT_FOUND,
        ERR_FINDING_NOT_FOUND, ERR_NOTICE_NOT_FOUND,
        ERR_ABATEMENT_ORDER_NOT_FOUND, ERR_PAYMENT_NOT_FOUND,
        ERR_PROGRAM_NOT_FOUND, ERR_ENROLLMENT_NOT_FOUND and
        ERR_CERTIFICATE_NOT_FOUND."

        PRD: "The meta object for error responses contains only api_request_id and
        api_request_timestamp."

        Design: Corner/entities/inspector_get_unknown_id_not_found
        """
        response = client.get_inspector(
            NON_EXISTENT_UUID, headers=PROGRAM_ADMIN_HEADERS
        )
        assert_error_response_type(response)
        body = assert_envelope_meta(response)
        validate_error(response, ERR_INSPECTOR_NOT_FOUND, 404)

        assert sorted(body["meta"].keys()) == [
            "api_request_id",
            "api_request_timestamp",
        ], "an error envelope carries only the two request fields in meta"
        assert body["data"]["message"].strip() != ""

        # The refused read left the roster empty: a genuine inspector registered
        # afterwards is the first row and still opens with an idle workload.
        inspector = create_inspector(client)
        assert inspector["id"] != NON_EXISTENT_UUID
        assert inspector["assigned_open_count"] == 0


class TestRequiredInputs:
    """Every field the parcel endpoint declares without a default is mandatory."""

    def test_parcel_create_without_apn_is_rejected_and_writes_nothing(self, client):
        """Omitting apn answers 400 ERR_INVALID_REQUEST and leaves the inventory
        empty, while the same body carrying an apn is accepted.

        PRD: "Request shape - required body fields present and non-null; enum
        fields carrying declared members only; numeric fields inside their declared
        ranges (slope_pct between 0 and 100 inclusive, crew_hours and
        actual_crew_hours positive multiples of 0.5, amount_cents at least 1);
        datetimes parsing as ISO 8601 UTC. Applies to every endpoint. Failure:
        ERR_INVALID_REQUEST (400)."

        PRD: "Each parcel enters the inventory with its assessor parcel number in
        apn - non-empty and unique across the whole inventory, with a collision
        refused as ERR_APN_ALREADY_REGISTERED - together with the owner_name of
        record, the owner_email that will be used whenever a notice is served
        electronically, and the physical situs_address."

        PRD: "Five intake attributes drive the risk model."

        PRD: "The recorded lot size goes into lot_area_sqft, which must be at
        least 1 square foot."

        Design: Corner/entities/parcel_create_missing_apn_returns_400
        """
        validate_error(
            client.create_parcel(
                parcel_payload(apn=OMIT), headers=PROGRAM_ADMIN_HEADERS
            ),
            ERR_INVALID_REQUEST,
            400,
        )
        _rows, meta = list_parcels(client)
        assert meta["total_count"] == 0, "a refused create writes no row"

        accepted = validate_success(
            client.create_parcel(
                parcel_payload(apn="APN-1201"), headers=PROGRAM_ADMIN_HEADERS
            ),
            201,
        )
        assert_risk(accepted, 63.83, "HIGH")

        # None of the five scoring attributes, and neither the lot size nor the
        # owner block, declares a default either.
        for field in (
            "owner_name",
            "owner_email",
            "situs_address",
            "roof_class",
            "vegetation_type",
            "slope_pct",
            "lot_area_sqft",
            "hazard_zone",
            "access_constraint",
        ):
            validate_error(
                client.create_parcel(
                    parcel_payload(apn=next_apn(), **{field: OMIT}),
                    headers=PROGRAM_ADMIN_HEADERS,
                ),
                ERR_INVALID_REQUEST,
                400,
            )

        _rows, meta = list_parcels(client)
        assert meta["total_count"] == 1, "only the well-formed create survived"


class TestDeclaredDefaults:
    """An omitted optional input is materialised, not left null."""

    def test_optional_inputs_fall_back_to_their_declared_defaults(self, client):
        """A contractor, an inspector, a parcel and a cycle created with every
        optional input omitted come back carrying the PRD's default values.

        PRD: "notice_lead_days is the minimum number of whole days that must
        separate an owner notice from the visit it announces, and it defaults to 10
        when the request omits it."

        PRD: "A newly created cycle opens in PLANNING with its epoch counter at 0
        and its activated_at_utc and closed_at_utc both null."

        PRD: "structure_present records whether a habitable structure exists on
        the land and defaults to true when omitted."

        PRD: "Two further flags matter later rather than now:
        owner_hardship_flag, which records an income or senior hardship
        determination and defaults to false, and exemption_flag, which records a
        district-granted program exemption and also defaults to false."

        PRD: "An inspector enters the roster with a full_name and a
        certification_level of BASIC, ADVANCED or WUI_SPECIALIST, plus a status
        that defaults to ACTIVE and may be set to SUSPENDED."

        PRD: "a license_status of ACTIVE, SUSPENDED or REVOKED that defaults to
        ACTIVE"

        Design: Corner/entities/optional_inputs_fall_back_to_declared_defaults
        """
        contractor = create_contractor(client)
        assert contractor["license_status"] == "ACTIVE"
        assert contractor["max_daily_orders"] == DEFAULT_MAX_DAILY_ORDERS
        assert contractor["max_daily_orders"] == 2

        inspector = create_inspector(client)
        assert inspector["status"] == "ACTIVE"

        parcel = create_parcel(client)
        assert parcel["structure_present"] is True
        assert parcel["owner_hardship_flag"] is False
        assert parcel["exemption_flag"] is False

        cycle = create_cycle(client, season_year=2027)
        assert cycle["notice_lead_days"] == DEFAULT_NOTICE_LEAD_DAYS
        assert cycle["notice_lead_days"] == 10
        assert cycle["invoice_due_days"] == DEFAULT_INVOICE_DUE_DAYS
        assert cycle["invoice_due_days"] == 45
        assert cycle["status"] == "PLANNING"
        assert cycle["epoch"] == 0
        assert cycle["activated_at_utc"] is None
        assert cycle["closed_at_utc"] is None

        assert get_contractor(client, contractor["id"])["committed_crew_hours"] == 0
        assert get_inspector(client, inspector["id"])["assigned_open_count"] == 0


class TestServerStampedFields:
    """Identity and audit columns are written by the server off the logical clock."""

    def test_parcel_system_fields_are_stamped_from_the_logical_clock(self, client):
        """A create stamps version 1 with created_at equal to updated_at, and a
        later update moves version and updated_at while created_at stays pinned.

        PRD: "Every resource is identified by an id that the server mints as a
        UUID."

        PRD: "Most resources also carry the full set of audit columns: created_at,
        recording when the row was first written; updated_at, refreshed on every
        mutation; and version, an integer that starts at 1 when the resource is
        created and increments by exactly 1 on every successful mutation of that
        resource."

        PRD: "The service does not read wall-clock time. Instead it maintains a
        logical clock that begins at 2026-08-01T00:00:00Z on a freshly started
        server, and every deadline comparison, window test, expiry check and
        staleness measurement in this document is evaluated against that clock."

        PRD: "Every successful update increments the parcel's version by 1."

        Design: Corner/entities/parcel_system_fields_stamped_by_server
        """
        set_clock(client, "2026-08-05T00:00:00Z")
        parcel = create_parcel(client)

        assert isinstance(parcel["id"], str) and parcel["id"] != ""
        assert_version(parcel, 1)
        assert_instant(parcel["created_at"], "2026-08-05T00:00:00Z")
        assert_instant(parcel["updated_at"], "2026-08-05T00:00:00Z")

        set_clock(client, "2026-08-06T00:00:00Z")
        updated = validate_success(
            client.update_parcel(
                parcel["id"],
                parcel_patch(parcel["version"], slope_pct=50),
                headers=PROGRAM_ADMIN_HEADERS,
            )
        )
        assert_version(updated, 2)
        assert updated["id"] == parcel["id"]
        assert_instant(updated["updated_at"], "2026-08-06T00:00:00Z")
        assert_instant(updated["created_at"], "2026-08-05T00:00:00Z")


class TestDeclaredDomains:
    """Enum membership and numeric range are screened before any scoring runs."""

    def test_undeclared_enum_member_and_out_of_range_number_are_rejected(self, client):
        """A roof_class outside the four declared ratings, a negative slope and an
        undeclared vegetation model are each a 400, and the corrected body is a 201.

        PRD: "roof_class is the roof assembly's fire rating and is one of CLASS_A,
        CLASS_B, CLASS_C or NONE."

        PRD: "vegetation_type is the dominant fuel model the owner reports and is
        one of IRRIGATED_LANDSCAPE, GRASS, BRUSH or MIXED_CONIFER."

        PRD: "slope_pct is the average parcel slope expressed in percent, between
        0 and 100 inclusive."

        PRD: "Request shape - required body fields present and non-null; enum
        fields carrying declared members only; numeric fields inside their declared
        ranges (slope_pct between 0 and 100 inclusive, crew_hours and
        actual_crew_hours positive multiples of 0.5, amount_cents at least 1);
        datetimes parsing as ISO 8601 UTC."

        Design: Corner/entities/parcel_create_with_undeclared_roof_class_returns_400
        """
        validate_error(
            client.create_parcel(
                parcel_payload(apn="APN-1501", roof_class="CLASS_D"),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_INVALID_REQUEST,
            400,
        )
        _rows, meta = list_parcels(client)
        assert meta["total_count"] == 0

        validate_error(
            client.create_parcel(
                parcel_payload(apn="APN-1502", slope_pct=-5),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_INVALID_REQUEST,
            400,
        )
        validate_error(
            client.create_parcel(
                parcel_payload(apn="APN-1503", vegetation_type="CHAPARRAL"),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_INVALID_REQUEST,
            400,
        )

        accepted = validate_success(
            client.create_parcel(
                parcel_payload(apn="APN-1504", roof_class="CLASS_B", slope_pct=30),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            201,
        )
        assert_risk(accepted, 63.83, "HIGH")


class TestAppendOnlyEvidence:
    """A zone measurement is evidence: written once, never rewritten."""

    def test_zone_evaluation_is_immutable_and_cannot_be_rewritten(self, client):
        """The graded measurement carries no version and no updated_at, and a
        second measurement of the same zone on the same visit is refused with the
        original left untouched.

        PRD: "Two kinds of finding exist, both created by the assigned inspector,
        both immutable once written, and both carrying only id and created_at for
        audit metadata."

        PRD: "A zone evaluation, a structure-hardening finding, and a
        cost-recovery payment each carry only id and created_at: they have no
        updated_at field and no version field at all, because nothing in this
        specification ever edits one after it is written."

        PRD: "At most one evaluation may exist per zone per inspection, and a
        second attempt on a zone already measured is refused with
        ERR_ZONE_ALREADY_EVALUATED."

        PRD: "on moderate ground, where slope_pct is at least 20 but below 40, the
        factor is 1.25"

        Design: Corner/entities/zone_evaluation_is_immutable_and_cannot_be_rewritten
        """
        cycle = open_cycle(client)
        inspector = create_inspector(client)
        parcel = create_parcel(client, slope_pct=30)
        inspection = schedule_inspection(
            client,
            parcel["id"],
            cycle["id"],
            inspector["id"],
            scheduled_start_utc="2026-08-20T15:00:00Z",
            scheduled_end_utc="2026-08-20T17:00:00Z",
        )
        serve_notice(client, inspection["id"])

        measured = add_zone(client, inspection["id"], inspector["id"], "ZONE_1", 15.0)
        assert_zone_grade(
            measured,
            required_ft=37.5,
            deficit_ft=22.5,
            ratio=0.6000,
            severity="MAJOR",
            points=60.00,
        )
        assert_append_only_row(measured)

        validate_error(
            client.create_zone_evaluation(
                inspection["id"],
                zone_payload("ZONE_1", 35.0),
                headers=make_inspector_headers(inspector["id"]),
            ),
            ERR_ZONE_ALREADY_EVALUATED,
            409,
        )

        reread = validate_success(
            client.get_zone_evaluation(measured["id"], headers=PROGRAM_ADMIN_HEADERS)
        )
        assert reread["measured_clearance_ft"] == 15.0
        assert_zone_grade(
            reread,
            required_ft=37.5,
            deficit_ft=22.5,
            ratio=0.6000,
            severity="MAJOR",
            points=60.00,
        )
        assert_append_only_row(reread)

        _rows, meta = list_zone_evaluations(client, inspection_id=inspection["id"])
        assert meta["total_count"] == 1, "the rejected rewrite added no second row"


class TestBodyForeignKeyOrder:
    """Body foreign keys are resolved in the PRD's declaration order."""

    def test_inspection_create_with_unknown_parcel_reports_the_parcel(self, client):
        """A real cycle, a dangling parcel_id and a real inspector answer
        ERR_PARCEL_NOT_FOUND, and a dangling cycle_id outranks the parcel.

        PRD: "Once every path segment resolves, foreign keys supplied in the
        request body are validated in a fixed declaration order: cycle_id, then
        parcel_id, then community_id, then inspector_id, then contractor_id, then
        inspection_id, then violation_notice_id, then support_program_id."

        PRD: "Existence - every path referent resolves left to right, then every
        body foreign key resolves in the declaration order given in section 2.6. Applies
        to every endpoint. Failure: the matching not-found identifier (404)."

        PRD: "An inspector's assigned_open_count must always equal the number of
        inspections carrying that inspector_id whose status is SCHEDULED, NOTICED
        or ACCESS_DENIED."

        Design: Corner/entities/inspection_create_with_unknown_parcel_not_found
        """
        cycle = open_cycle(client)
        inspector = create_inspector(client)
        parcel = create_parcel(client)

        validate_error(
            client.create_inspection(
                inspection_payload(
                    NON_EXISTENT_UUID,
                    cycle["id"],
                    inspector["id"],
                    "2026-08-20T15:00:00Z",
                    "2026-08-20T17:00:00Z",
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_PARCEL_NOT_FOUND,
            404,
        )
        _rows, meta = list_inspections(client, cycle_id=cycle["id"])
        assert meta["total_count"] == 0
        assert get_inspector(client, inspector["id"])["assigned_open_count"] == 0

        # cycle_id sits above parcel_id, so a dangling cycle wins even when the
        # parcel resolves - and still wins when neither resolves.
        validate_error(
            client.create_inspection(
                inspection_payload(
                    parcel["id"],
                    NON_EXISTENT_UUID,
                    inspector["id"],
                    "2026-08-20T15:00:00Z",
                    "2026-08-20T17:00:00Z",
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_CYCLE_NOT_FOUND,
            404,
        )
        validate_error(
            client.create_inspection(
                inspection_payload(
                    SECOND_NON_EXISTENT_UUID,
                    NON_EXISTENT_UUID,
                    inspector["id"],
                    "2026-08-20T15:00:00Z",
                    "2026-08-20T17:00:00Z",
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_CYCLE_NOT_FOUND,
            404,
        )
        _rows, meta = list_inspections(client, cycle_id=cycle["id"])
        assert meta["total_count"] == 0


class TestExistenceOutranksConcurrency:
    """A dangling program is answered before its version token is compared."""

    def test_enrollment_create_with_unknown_program_reports_not_found(self, client):
        """An enrollment naming a bogus support_program_id answers 404
        ERR_PROGRAM_NOT_FOUND even though its version token matches a real program.

        PRD: "Existence - every path referent resolves left to right, then every
        body foreign key resolves in the declaration order given in section 2.6."

        PRD: "Creating a support enrollment requires a non-optional
        expected_program_version field carrying the client's last observed version
        of the target SupportProgram. A mismatch with the program's current version
        is rejected with ERR_STALE_PROGRAM_VERSION (HTTP 412)."

        PRD: "A support program's budget_remaining_cents must always equal
        budget_total_cents minus the sum of reserved_amount_cents over that
        program's enrollments whose status is APPROVED, COMPLETED or REIMBURSED -
        enrollments in WAITLISTED, NO_SHOW or CANCELLED contribute nothing."

        Design: Corner/entities/enrollment_create_with_unknown_program_not_found
        """
        cycle = open_cycle(client)
        parcel = create_parcel(client)
        program = create_program(
            client,
            cycle["id"],
            PROGRAM_TYPE_CHIPPER,
            budget_total_cents=500000,
            capacity_slots=5,
        )
        assert_version(program, 1)

        validate_error(
            client.create_enrollment(
                enrollment_payload(
                    NON_EXISTENT_UUID, parcel["id"], program["version"]
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_PROGRAM_NOT_FOUND,
            404,
        )

        assert_program_capacity(
            get_program(client, program["id"]), 500000, reserved_slots=0
        )
        _rows, meta = list_enrollments(client, support_program_id=program["id"])
        assert meta["total_count"] == 0
