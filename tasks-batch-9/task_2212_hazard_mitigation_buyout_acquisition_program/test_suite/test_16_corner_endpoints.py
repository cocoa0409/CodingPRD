"""Endpoints: the logical clock, the two participation gates and the offer cross-checks."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


ADMIN = TEST_USERS["program_administrator_headers"]
MONITOR = TEST_USERS["compliance_monitor_headers"]
STAFF = TEST_USERS["staff_appraiser_headers"]


# ─── The test-driving clock endpoint ──────────────────────────────────────────

def test_the_pinned_instant_stamps_later_rows_and_a_rejected_set_moves_nothing(api):
    """Both writes carry the one pinned instant, so the malformed set never took effect.

    "On a cold service the logical clock stands at `2026-08-01T00:00:00Z`. A single
    administrative capability moves it: a caller supplies a `current_utc` instant and
    the clock is set to that value."

    "This capability is outside the business surface - any of the six roles may invoke
    it, it requires no `X-User-ID`, it creates and mutates nothing, it advances no
    `version`, and the only error it can return is `ERR_INVALID_REQUEST`. Its response
    body is the newly set `current_utc`."

    "Dates are written `YYYY-MM-DD`; a date field that is not in that shape, or a
    datetime field that is not a valid ISO 8601 UTC instant, is `ERR_INVALID_REQUEST`."

    Design: Corner/endpoints/the_clock_endpoint_pins_the_logical_now_used_by_every_later_write
    """
    pinned = validate_success(api.set_clock("2027-03-15T12:00:00Z", MONITOR))
    assert pinned["current_utc"] == "2027-03-15T12:00:00Z"

    project = validate_success(
        api.create_mitigation_project(
            factories.create_mitigation_project_payload(
                project_code="EP-CLOCK-1", grant_program="FMA",
                period_of_performance_end_date="2030-12-31",
            ),
            ADMIN,
        ),
        201,
    )
    assert project["created_at"].startswith("2027-03-15T12:00:00")
    assert project["updated_at"] == project["created_at"]

    validate_error(
        api.set_clock("not-an-instant", MONITOR),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    parcel = validate_success(
        api.create_parcel(
            project["id"],
            factories.create_parcel_payload(
                project["id"], apn="APN-EP-CLOCK-1", site_address="3801 River Rd",
                acreage=0.34, occupancy_type="OWNER_OCCUPIED",
                structure_type="SINGLE_FAMILY",
            ),
            make_subrecipient_coordinator_headers(project["id"]),
        ),
        201,
    )
    assert parcel["created_at"].startswith("2027-03-15T12:00:00")
    assert parcel["created_at"] == project["created_at"]


# ─── Two endpoints reading the participation dimension differently ────────────

def test_interest_is_enough_to_build_an_offer_but_not_to_present_it(api):
    """The signature is only demanded by the second endpoint, which then books the share.

    "It requires the parcel's `pre_event_fmv_cents` to be non-null - an owner cannot
    sign a voluntary acknowledgement before knowing what the pre-event basis is - and a
    null `pre_event_fmv_cents` is refused with `ERR_PRE_EVENT_VALUE_NOT_DETERMINED`."

    "the parcel's `participation_status` must be `INTERESTED` or `VOLUNTARY_CONFIRMED`,
    otherwise `ERR_PARTICIPATION_NOT_VOLUNTARY` - note this is a cross-dimension check,
    and a parcel may perfectly well have reached `VALUE_ESTABLISHED` on the acquisition
    dimension while still only `INTERESTED` on the participation dimension"

    "The parcel's `participation_status` must now be fully `VOLUNTARY_CONFIRMED` -
    merely `INTERESTED` was enough to build the offer but is not enough to put it in
    front of the owner - otherwise `ERR_PARTICIPATION_NOT_VOLUNTARY`."

    Design: Corner/endpoints/offer_creation_and_offer_presentation_read_two_different_participation_gates
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.create_approved_project(
        api,
        project_overrides={"project_code": "EP-PART-1", "grant_program": "FMA"},
        parcel_overrides={
            "apn": "APN-EP-PART-1", "site_address": "3901 River Rd", "acreage": 0.34,
            "occupancy_type": "OWNER_OCCUPIED", "structure_type": "SINGLE_FAMILY",
        },
    )
    project = state["project"]
    parcel = state["parcel"]
    coordinator = make_subrecipient_coordinator_headers(project["id"])

    validate_error(
        api.record_participation(
            parcel["id"],
            factories.participation_payload(
                parcel["id"], "CONFIRM_VOLUNTARY",
                voluntary_acknowledgement_signed_on="2026-07-20",
            ),
            coordinator,
        ),
        ApiErrorId.ERR_PRE_EVENT_VALUE_NOT_DETERMINED.value,
        422,
    )
    untouched = validate_success(api.get_parcel(parcel["id"], ADMIN))
    assert untouched["participation_status"] == "NOT_CONTACTED"
    assert untouched["pre_event_fmv_cents"] is None

    valued = validate_success(
        api.record_pre_event_value(
            parcel["id"],
            factories.pre_event_value_payload(
                parcel["id"], pre_event_fmv_cents=20_000_000,
                pre_event_value_basis="MARKET_STUDY",
            ),
            STAFF,
        )
    )
    assert valued["pre_event_fmv_cents"] == 20_000_000

    interested = validate_success(
        api.record_participation(
            parcel["id"],
            factories.participation_payload(parcel["id"], "INTERESTED"),
            coordinator,
        )
    )
    assert interested["participation_status"] == "INTERESTED"

    initial = fixtures.accepted_initial_appraisal(
        api, parcel["id"], effective_date="2026-07-01",
        indicated_value_cents=20_000_000,
    )
    review = fixtures.accepted_review_appraisal(
        api, parcel["id"], initial, effective_date="2026-07-05",
        indicated_value_cents=20_000_000,
    )
    established = validate_success(api.get_parcel(parcel["id"], ADMIN))
    assert established["acquisition_status"] == "VALUE_ESTABLISHED"
    assert established["participation_status"] == "INTERESTED"

    offer = fixtures.build_offer(api, project, parcel["id"], review)
    assert offer["status"] == "DRAFT"
    assert offer["base_value_cents"] == 20_000_000

    validate_error(
        api.present_purchase_offer(offer["id"], coordinator),
        ApiErrorId.ERR_PARTICIPATION_NOT_VOLUNTARY.value,
        409,
    )
    unobligated = validate_success(api.get_mitigation_project(project["id"], ADMIN))
    assert unobligated["federal_obligated_cents"] == 0

    confirmed = validate_success(
        api.record_participation(
            parcel["id"],
            factories.participation_payload(
                parcel["id"], "CONFIRM_VOLUNTARY",
                voluntary_acknowledgement_signed_on="2026-07-20",
            ),
            coordinator,
        )
    )
    assert confirmed["participation_status"] == "VOLUNTARY_CONFIRMED"
    assert confirmed["voluntary_acknowledgement_signed_on"] == "2026-07-20"

    presented = validate_success(api.present_purchase_offer(offer["id"], coordinator))
    assert presented["status"] == "PRESENTED"

    obligated = validate_success(api.get_mitigation_project(project["id"], ADMIN))
    assert obligated["federal_obligated_cents"] == 16_050_000


# ─── One create endpoint reading three sibling rows ───────────────────────────

def test_the_offer_create_rejects_the_wrong_appraisal_the_wrong_basis_and_a_swollen_deduction(api):
    """Three distinct cross-references fail in turn, and clearing the last one lets it through.

    "that appraisal must have `appraisal_type` of `REVIEW` and `status` of `ACCEPTED`,
    otherwise `ERR_REVIEW_APPRAISAL_REQUIRED`; the `offer_basis` must correspond to the
    source appraisal's `valuation_basis`, meaning `PRE_EVENT_FMV` pairs with
    `PRE_EVENT` and `POST_EVENT_FMV` pairs with `POST_EVENT`, and any other pairing is
    `ERR_VALUATION_BASIS_MISMATCH`; and the parcel's `dob_deduction_total_cents` must
    not exceed the source appraisal's `indicated_value_cents`, otherwise
    `ERR_DOB_EXCEEDS_BASE_VALUE`, because prior benefits that swallow the entire value
    mean there is nothing left to buy."

    "The record's `version` advances by 1, the parcel's `dob_deduction_total_cents` is
    recomputed without it, and the parcel's `version` advances by 1."

    "`incentive_cents` is `pre_incentive_net_cents` multiplied by that rate, **rounded
    half up to whole cents first and only then capped** at 2,250,000 cents."

    Design: Corner/endpoints/offer_creation_cross_checks_the_source_appraisal_type_basis_and_the_deduction_total
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.parcel_value_established(
        api,
        indicated_value_cents=20_000_000,
        project_overrides={"project_code": "EP-XREF-1", "grant_program": "FMA"},
        parcel_overrides={
            "apn": "APN-EP-XREF-1", "site_address": "4001 River Rd", "acreage": 0.34,
            "occupancy_type": "OWNER_OCCUPIED", "structure_type": "SINGLE_FAMILY",
        },
    )
    project = state["project"]
    parcel_id = state["parcel"]["id"]
    coordinator = make_subrecipient_coordinator_headers(project["id"])

    def _offer_attempt(source_appraisal_id, **overrides):
        parcel = validate_success(api.get_parcel(parcel_id, ADMIN))
        return api.create_purchase_offer(
            parcel_id,
            factories.create_purchase_offer_payload(
                parcel_id, source_appraisal_id, parcel["version"], **overrides
            ),
            coordinator,
        )

    validate_error(
        _offer_attempt(state["initial_appraisal"]["id"]),
        ApiErrorId.ERR_REVIEW_APPRAISAL_REQUIRED.value,
        422,
    )

    validate_error(
        _offer_attempt(
            state["review_appraisal"]["id"], offer_basis="POST_EVENT_FMV"
        ),
        ApiErrorId.ERR_VALUATION_BASIS_MISMATCH.value,
        422,
    )

    dob = fixtures.record_dob(
        api, project, parcel_id, benefit_source="NFIP_CLAIM",
        amount_cents=25_000_000, received_on="2026-05-10",
    )
    assert dob["deductible_cents"] == 25_000_000
    swollen = validate_success(api.get_parcel(parcel_id, ADMIN))
    assert swollen["dob_deduction_total_cents"] == 25_000_000

    validate_error(
        _offer_attempt(state["review_appraisal"]["id"]),
        ApiErrorId.ERR_DOB_EXCEEDS_BASE_VALUE.value,
        422,
    )

    reversed_record = validate_success(
        api.reverse_dob_record(
            dob["id"],
            factories.reverse_dob_record_payload(
                dob["id"], reversal_reason="claim rescinded by carrier"
            ),
            ADMIN,
        )
    )
    assert reversed_record["status"] == "REVERSED"
    assert reversed_record["deductible_cents"] == 25_000_000

    cleared = validate_success(api.get_parcel(parcel_id, ADMIN))
    assert cleared["dob_deduction_total_cents"] == 0

    offer = validate_success(
        _offer_attempt(state["review_appraisal"]["id"]), 201
    )
    assert offer["status"] == "DRAFT"
    assert offer["base_value_cents"] == 20_000_000
    assert offer["dob_deduction_cents"] == 0
    assert offer["pre_incentive_net_cents"] == 20_000_000
    assert offer["incentive_cents"] == 1_400_000
    assert offer["net_offer_cents"] == 21_400_000

    offers, meta = validate_paginated(
        api.list_purchase_offers(ADMIN, params={"parcel_id": parcel_id})
    )
    assert meta["total_count"] == 1
    assert len(offers) == 1


# ─── One global uniqueness scope beside one project-scoped one ────────────────

def test_the_project_code_collides_globally_while_the_apn_collides_per_project(api):
    """The identical APN is fatal on the first project and legal on the second.

    "A `ProgramAdministrator` registers one by supplying a `project_code` that must be
    unique across every project in the system and between 4 and 32 characters long - a
    collision is `ERR_DUPLICATE_PROJECT_CODE`."

    "A parcel declares an `apn` - the assessor's parcel number, which must be unique
    within its project, with a collision reported as `ERR_DUPLICATE_APN`, and which may
    legitimately repeat across two different projects."

    Design: Corner/endpoints/duplicate_project_codes_are_global_while_duplicate_apns_are_scoped_to_the_project
    """
    api.set_clock("2026-08-01T00:00:00Z")
    first = fixtures.create_draft_project(
        api, project_code="EP-DUP-A", grant_program="FMA"
    )
    second = fixtures.create_draft_project(
        api, project_code="EP-DUP-B", grant_program="FMA"
    )

    shared = fixtures.create_parcel(
        api, first, apn="APN-SHARED", site_address="4101 River Rd", acreage=0.34,
        occupancy_type="OWNER_OCCUPIED", structure_type="SINGLE_FAMILY",
    )
    assert shared["apn"] == "APN-SHARED"

    validate_error(
        api.create_mitigation_project(
            factories.create_mitigation_project_payload(
                project_code="EP-DUP-A", grant_program="FMA"
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_PROJECT_CODE.value,
        409,
    )

    validate_error(
        api.create_parcel(
            first["id"],
            factories.create_parcel_payload(
                first["id"], apn="APN-SHARED", site_address="4102 River Rd",
                acreage=0.41, occupancy_type="VACANT", structure_type="NONE",
            ),
            make_subrecipient_coordinator_headers(first["id"]),
        ),
        ApiErrorId.ERR_DUPLICATE_APN.value,
        409,
    )

    twin = fixtures.create_parcel(
        api, second, apn="APN-SHARED", site_address="4201 Oak St", acreage=0.52,
        occupancy_type="OWNER_OCCUPIED", structure_type="SINGLE_FAMILY",
    )
    assert twin["apn"] == "APN-SHARED"
    assert twin["project_id"] == second["id"]

    projects, project_meta = validate_paginated(api.list_mitigation_projects(ADMIN))
    assert project_meta["total_count"] == 2
    assert len(projects) == 2

    parcels, parcel_meta = validate_paginated(
        api.list_parcels(ADMIN, params={"project_id": first["id"]})
    )
    assert parcel_meta["total_count"] == 1
    assert len(parcels) == 1
