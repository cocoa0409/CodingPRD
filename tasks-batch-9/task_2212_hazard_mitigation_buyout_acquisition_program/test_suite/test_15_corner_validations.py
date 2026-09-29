"""Validations: inclusive ceilings, conditional requirements and interval collisions."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


ADMIN = TEST_USERS["program_administrator_headers"]
SPECIALIST = TEST_USERS["relocation_specialist_headers"]


# ─── The federal share cap, whose ceiling is inclusive ────────────────────────

CAP_CENTS = 16_050_000


def _draft_offer_under_an_exact_cap(api):
    """A DRAFT offer of 21,400,000 whose federal item is exactly the project's cap."""
    state = fixtures.parcel_with_draft_offer(
        api, project_overrides={"total_federal_share_cap_cents": CAP_CENTS}
    )
    assert state["project"]["total_federal_share_cap_cents"] == CAP_CENTS
    assert state["offer"]["net_offer_cents"] == 21_400_000
    return state


def test_presentation_is_permitted_when_the_item_lands_exactly_on_the_cap(api):
    """Landing on the ceiling is not breaching it, so the whole cap is obligated at once.

    "The cap check `ERR_FEDERAL_SHARE_CAP_EXCEEDED` reads this total at three
    moments - presenting an offer, funding a closing and paying a relocation claim -
    and in each case tests the current `federal_obligated_cents` plus the prospective
    per-item federal share against `total_federal_share_cap_cents`, with the ceiling
    inclusive: landing exactly on the cap is permitted."

    "And the obligation cap must hold: the project's current
    `federal_obligated_cents` plus this offer's prospective federal item must be at
    most `total_federal_share_cap_cents`, otherwise
    `ERR_FEDERAL_SHARE_CAP_EXCEEDED`."

    Design: Corner/validations/presenting_an_offer_at_exactly_the_federal_cap_is_permitted_and_the_next_item_is_not
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _draft_offer_under_an_exact_cap(api)

    presented = validate_success(
        api.present_purchase_offer(
            state["offer"]["id"],
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        )
    )
    assert presented["status"] == "PRESENTED"
    assert presented["net_offer_cents"] == 21_400_000

    project = validate_success(
        api.get_mitigation_project(state["project"]["id"], ADMIN)
    )
    assert project["federal_obligated_cents"] == CAP_CENTS
    assert project["federal_obligated_cents"] == project["total_federal_share_cap_cents"]


def test_the_next_obligating_item_is_refused_and_the_total_stays_on_the_cap(api):
    """A 400,000-cent settlement cannot be part-applied: the ledger is left untouched.

    "Funding moves the closing to `FUNDED`, stamps `funded_at` from the logical
    clock and `funded_by_user_id` with the acting `X-User-ID`, moves the parcel's
    `acquisition_status` from `OFFER_ACCEPTED` to `CLOSED`, recomputes the project's
    `federal_obligated_cents` to include the settlement-cost item."

    "The cap check `ERR_FEDERAL_SHARE_CAP_EXCEEDED` reads this total at three
    moments - presenting an offer, funding a closing and paying a relocation claim -
    and in each case tests the current `federal_obligated_cents` plus the prospective
    per-item federal share against `total_federal_share_cap_cents`, with the ceiling
    inclusive: landing exactly on the cap is permitted."

    Design: Corner/validations/presenting_an_offer_at_exactly_the_federal_cap_is_permitted_and_the_next_item_is_not
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _draft_offer_under_an_exact_cap(api)
    coordinator = make_subrecipient_coordinator_headers(state["project"]["id"])

    validate_success(api.present_purchase_offer(state["offer"]["id"], coordinator))
    accepted = validate_success(
        api.respond_to_purchase_offer(
            state["offer"]["id"],
            factories.owner_response_payload(state["offer"]["id"], "ACCEPT"),
            coordinator,
        )
    )
    assert accepted["status"] == "ACCEPTED"

    closing = validate_success(
        api.create_closing_record(
            state["parcel"]["id"],
            factories.create_closing_record_payload(
                state["parcel"]["id"], accepted["id"],
                scheduled_closing_date="2026-08-15", settlement_cost_cents=400_000,
            ),
            coordinator,
        ),
        201,
    )

    validate_error(
        api.fund_closing_record(closing["id"], ADMIN),
        ApiErrorId.ERR_FEDERAL_SHARE_CAP_EXCEEDED.value,
        422,
    )

    unfunded = validate_success(api.get_closing_record(closing["id"], ADMIN))
    assert unfunded["status"] == "SCHEDULED"
    assert unfunded["funded_at"] is None

    project = validate_success(
        api.get_mitigation_project(state["project"]["id"], ADMIN)
    )
    assert project["federal_obligated_cents"] == CAP_CENTS


# ─── One field, mandatory or optional according to a sibling ──────────────────

def test_the_declaration_number_is_mandatory_for_hmgp_and_optional_otherwise(api):
    """The same omission is fatal under HMGP and harmless under FMA.

    "A `ProgramAdministrator` registers one by supplying a `project_code` that must
    be unique across every project in the system and between 4 and 32 characters long
    - a collision is `ERR_DUPLICATE_PROJECT_CODE`; a `grant_program` of `HMGP`, `FMA`
    or `BRIC`; a `disaster_declaration_number`, which is mandatory when
    `grant_program` is `HMGP` and optional otherwise."

    "Structural validation of the request body or query string -
    `ERR_INVALID_REQUEST`. This applies to every write endpoint and every list
    endpoint, and covers a missing required field, a wrong JSON type, an enum value
    outside its declared set."

    Design: Corner/validations/hmgp_projects_require_a_disaster_declaration_number_and_fma_projects_do_not
    """
    api.set_clock("2026-08-01T00:00:00Z")

    validate_error(
        api.create_mitigation_project(
            factories.create_mitigation_project_payload(
                project_code="VAL-COND-1", grant_program="HMGP"
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    declared = validate_success(
        api.create_mitigation_project(
            factories.create_mitigation_project_payload(
                project_code="VAL-COND-2", grant_program="HMGP",
                disaster_declaration_number="DR-4700-XX",
            ),
            ADMIN,
        ),
        201,
    )
    assert declared["disaster_declaration_number"] == "DR-4700-XX"

    undeclared = validate_success(
        api.create_mitigation_project(
            factories.create_mitigation_project_payload(
                project_code="VAL-COND-3", grant_program="FMA"
            ),
            ADMIN,
        ),
        201,
    )
    assert undeclared["disaster_declaration_number"] is None

    projects, meta = validate_paginated(api.list_mitigation_projects(ADMIN))
    assert meta["total_count"] == 2
    assert len(projects) == 2


# ─── The expiry instant, read with opposite senses by two endpoints ───────────

def _presented_offer_expiring_on_the_last_day_of_august(api):
    state = fixtures.parcel_with_presented_offer(api)
    assertions.assert_instant_equals(
        state["offer"]["presented_at"], "2026-08-01T00:00:00Z", "presented_at"
    )
    assertions.assert_instant_equals(
        state["offer"]["expires_at"], "2026-08-31T00:00:00Z", "expires_at"
    )
    project = validate_success(
        api.get_mitigation_project(state["project"]["id"], ADMIN)
    )
    assert project["federal_obligated_cents"] == 16_050_000
    return state


def test_at_the_expiry_instant_itself_the_offer_has_not_yet_lapsed(api):
    """Strictly-after means the offer is still live on the boundary the clock has reached.

    "A `ProgramAdministrator` expires an offer that must be `PRESENTED`, otherwise
    `ERR_INVALID_OFFER_STATE`, and whose validity window must have genuinely lapsed:
    the logical clock must be **strictly after** `expires_at`, and an attempt at
    exactly `expires_at` or earlier is `ERR_OFFER_NOT_YET_EXPIRED`."

    "Presentation moves `status` to `PRESENTED`, stamps `presented_at` from the
    logical clock, computes `expires_at` as `presented_at` plus 30 calendar days."

    Design: Corner/validations/offer_expiry_is_refused_at_the_expiry_instant_and_the_response_is_refused_one_second_later
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _presented_offer_expiring_on_the_last_day_of_august(api)

    api.set_clock("2026-08-31T00:00:00Z")
    validate_error(
        api.expire_purchase_offer(state["offer"]["id"], ADMIN),
        ApiErrorId.ERR_OFFER_NOT_YET_EXPIRED.value,
        409,
    )

    offer = validate_success(api.get_purchase_offer(state["offer"]["id"], ADMIN))
    assert offer["status"] == "PRESENTED"


def test_one_second_later_the_response_is_refused_and_the_expiry_succeeds(api):
    """The same instant flips both comparisons, and the lapse releases the obligation.

    "The offer must be `PRESENTED`, otherwise `ERR_INVALID_OFFER_STATE`, and the
    logical clock must be at or before `expires_at` - the boundary is inclusive, so a
    response landing exactly on `expires_at` is timely, and anything strictly later is
    `ERR_OFFER_EXPIRED`."

    "Expiry moves the offer to `EXPIRED` and otherwise has exactly the same effects
    as a decline: parcel back to `VALUE_ESTABLISHED`, `federal_obligated_cents`
    recomputed downward, and the offer's, parcel's and project's `version` each
    advanced by 1."

    Design: Corner/validations/offer_expiry_is_refused_at_the_expiry_instant_and_the_response_is_refused_one_second_later
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _presented_offer_expiring_on_the_last_day_of_august(api)

    api.set_clock("2026-08-31T00:00:01Z")
    validate_error(
        api.respond_to_purchase_offer(
            state["offer"]["id"],
            factories.owner_response_payload(state["offer"]["id"], "ACCEPT"),
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        ),
        ApiErrorId.ERR_OFFER_EXPIRED.value,
        409,
    )
    still_live = validate_success(api.get_purchase_offer(state["offer"]["id"], ADMIN))
    assert still_live["status"] == "PRESENTED"

    expired = validate_success(
        api.expire_purchase_offer(state["offer"]["id"], ADMIN)
    )
    assert expired["status"] == "EXPIRED"

    parcel = validate_success(api.get_parcel(state["parcel"]["id"], ADMIN))
    assert parcel["acquisition_status"] == "VALUE_ESTABLISHED"

    project = validate_success(
        api.get_mitigation_project(state["project"]["id"], ADMIN)
    )
    assert project["federal_obligated_cents"] == 0


# ─── The project-scoped rental assistance interval ───────────────────────────

TENANT_PARCELS = (
    {
        "apn": "APN-VAL-OVLP-1", "site_address": "3601 River Rd", "acreage": 0.34,
        "occupancy_type": "TENANT_OCCUPIED", "structure_type": "MULTI_FAMILY",
    },
    {
        "apn": "APN-VAL-OVLP-2", "site_address": "3602 River Rd", "acreage": 0.41,
        "occupancy_type": "TENANT_OCCUPIED", "structure_type": "MULTI_FAMILY",
    },
)


def _one_household_on_two_parcels(api):
    """The same household_reference on a case per parcel, each parcel with an accepted offer."""
    state = fixtures.create_approved_project_with_parcels(api, list(TENANT_PARCELS))
    project = state["project"]
    coordinator = make_subrecipient_coordinator_headers(project["id"])

    cases = []
    for parcel, start in zip(state["parcels"], ("2026-09-01", "2027-01-01")):
        valued = fixtures.progress_parcel_to_value_established(
            api, project, parcel, pre_event_fmv_cents=20_000_000,
            indicated_value_cents=20_000_000,
        )
        offer = fixtures.build_offer(
            api, project, parcel["id"], valued["review_appraisal"]
        )
        validate_success(api.present_purchase_offer(offer["id"], coordinator))
        validate_success(
            api.respond_to_purchase_offer(
                offer["id"], factories.owner_response_payload(offer["id"], "ACCEPT"),
                coordinator,
            )
        )
        case = validate_success(
            api.create_relocation_case(
                parcel["id"],
                factories.create_relocation_case_payload(
                    parcel["id"], displacee_type="TENANT_90_DAY",
                    household_reference="HH-SHARED", rhp_method="COMPARABLE_DWELLING",
                    rental_assistance_start_date=start,
                ),
                SPECIALIST,
            ),
            201,
        )
        assert case["household_reference"] == "HH-SHARED"
        cases.append(case)

    state["cases"] = cases
    return state


def test_the_first_tenant_case_occupies_a_forty_two_month_half_open_interval(api):
    """Both cases exist despite one shared reference, and the first one draws the full term.

    "`household_reference` is unique **within a parcel only** - a collision on the
    same parcel is `ERR_DUPLICATE_HOUSEHOLD_REFERENCE`, but the same
    `household_reference` may legitimately appear on two different parcels of one
    project, which is exactly the situation the rental-assistance overlap check below
    is designed to catch."

    "First, `rental_assistance_months` is 42 when `displacee_type` is
    `TENANT_90_DAY`, and exactly 0 when `displacee_type` is `OWNER_OCCUPANT`,
    `TENANT_UNDER_90_DAY` or `BUSINESS`."

    "Second, `rental_assistance_end_date` is `rental_assistance_start_date` plus
    `rental_assistance_months` calendar months, clamped to month end where the anchor
    day-of-month does not exist in the target month, and it is the **exclusive** upper
    bound of the occupation interval."

    Design: Corner/validations/one_household_cannot_hold_overlapping_rental_assistance_periods_on_two_parcels
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _one_household_on_two_parcels(api)

    determined = validate_success(
        api.determine_relocation_eligibility(state["cases"][0]["id"], SPECIALIST)
    )
    assert determined["status"] == "ELIGIBILITY_DETERMINED"
    assert determined["rental_assistance_months"] == 42
    assert determined["rental_assistance_end_date"] == "2030-03-01"


def test_the_second_case_starting_inside_that_interval_is_refused(api):
    """The check is project-scoped and fires at determination, not at case creation.

    "And no **other** case in the same project - reached through the case's parcel's
    `project_id` - carrying the same `household_reference` may have a
    rental-assistance occupation interval that intersects this case's. That interval
    is half-open: `[rental_assistance_start_date, rental_assistance_end_date)`."

    "An intersection is `ERR_RELOCATION_PERIOD_OVERLAP`, and a household cannot draw
    rental assistance for two dwellings over the same months."

    "The case opens in `status` `OPENED` at `version` 1 with `appeal_count` 0,
    `denial_reason` and `appeal_basis` null, `rental_assistance_end_date` null, and
    every computed benefit field at 0."

    Design: Corner/validations/one_household_cannot_hold_overlapping_rental_assistance_periods_on_two_parcels
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _one_household_on_two_parcels(api)

    validate_success(
        api.determine_relocation_eligibility(state["cases"][0]["id"], SPECIALIST)
    )

    validate_error(
        api.determine_relocation_eligibility(state["cases"][1]["id"], SPECIALIST),
        ApiErrorId.ERR_RELOCATION_PERIOD_OVERLAP.value,
        409,
    )

    blocked = validate_success(
        api.get_relocation_case(state["cases"][1]["id"], ADMIN)
    )
    assert blocked["status"] == "OPENED"
    assert blocked["rental_assistance_end_date"] is None
    assert blocked["rental_assistance_months"] == 0


# ─── The parcel-scoped household reference ───────────────────────────────────

def test_a_second_case_for_the_same_household_on_one_parcel_is_a_duplicate(api):
    """Uniqueness is checked at creation, long before any occupation interval exists.

    "`household_reference` is unique **within a parcel only** - a collision on the
    same parcel is `ERR_DUPLICATE_HOUSEHOLD_REFERENCE`."

    "A `RelocationSpecialist` opens a `RelocationCase` on the parcel, declaring a
    `displacee_type` of `OWNER_OCCUPANT`, `TENANT_90_DAY`, `TENANT_UNDER_90_DAY` or
    `BUSINESS`; a `household_reference`; an `rhp_method` of `COMPARABLE_DWELLING` or
    `ACTUAL_REPLACEMENT`; a `rental_assistance_start_date`."

    Design: Corner/validations/a_second_case_for_the_same_household_on_one_parcel_is_refused
    """
    api.set_clock("2026-08-01T00:00:00Z")
    project = fixtures.create_draft_project(
        api, project_code="VAL-DUPHH-1", grant_program="FMA"
    )
    parcel = fixtures.create_parcel(
        api, project, apn="APN-VAL-DUPHH-1", site_address="3701 River Rd",
        acreage=0.34, occupancy_type="OWNER_OCCUPIED", structure_type="SINGLE_FAMILY",
    )

    first = fixtures.open_relocation_case(
        api, parcel["id"], household_reference="HH-DUP",
        rental_assistance_start_date="2026-09-01",
    )
    assert first["rental_assistance_start_date"] == "2026-09-01"

    validate_error(
        api.create_relocation_case(
            parcel["id"],
            factories.create_relocation_case_payload(
                parcel["id"], household_reference="HH-DUP",
                rental_assistance_start_date="2027-01-01",
            ),
            SPECIALIST,
        ),
        ApiErrorId.ERR_DUPLICATE_HOUSEHOLD_REFERENCE.value,
        409,
    )

    cases, meta = validate_paginated(
        api.list_relocation_cases(ADMIN, params={"parcel_id": parcel["id"]})
    )
    assert meta["total_count"] == 1
    assert len(cases) == 1
