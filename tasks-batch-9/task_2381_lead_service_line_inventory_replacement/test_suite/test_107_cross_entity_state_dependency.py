"""Queue A - rule ``cross_entity_state_dependency``.

Three operations whose own target row is in a perfectly legal state and whose
caller is perfectly entitled, refused purely because of the state of a second
entity: a crew, a sampling batch and a parent water system. Each instance is
probed twice - once with the second entity blocking, and once after that second
entity alone has moved, which makes the identical request succeed.
"""

from test_helpers import ApiClient, factories, fixtures, validate_error
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ANALYST_USER_ID,
    OFFICER_HEADERS,
    OFFICER_USER_ID,
    make_field_technician_headers,
)
from test_helpers.types import (
    AppointmentState,
    BatchState,
    Classification,
    ConsentState,
    CrewStatus,
    FulfillmentState,
    FundingMode,
    InventoryStatus,
    ProgramPosture,
    PublicationState,
    ReplacementState,
    VerificationMethod,
)


# ---------------------------------------------------------------------------
# appointment_arrive_depends_on_verification_crew_status
# ---------------------------------------------------------------------------


def _scheduled_appointment_and_its_crew(api: ApiClient):
    """A SCHEDULED POTHOLE appointment whose crew can be flipped either way."""
    system = fixtures.create_water_system(
        api,
        "IL2031015",
        system_name="Windrow Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=[],
        funding_mode=FundingMode.WATERFALL,
    )
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")
    crew = fixtures.create_crew(
        api,
        system["id"],
        crew_name="Crew Bravo",
        shift_start_utc_time="08:00",
        shift_end_utc_time="18:00",
        daily_appointment_capacity=5,
        certified_methods=[VerificationMethod.POTHOLE],
    )
    appointment = fixtures.book_appointment(
        api,
        line["id"],
        crew["id"],
        method=VerificationMethod.POTHOLE,
        window_start_utc="2026-08-05T09:00:00Z",
        window_end_utc="2026-08-05T10:00:00Z",
    )
    assert appointment["state"] == AppointmentState.SCHEDULED
    deactivated = fixtures.set_crew_status(api, crew["id"], CrewStatus.INACTIVE)
    assert deactivated["status"] == CrewStatus.INACTIVE
    return {"system": system, "line": line, "crew": crew, "appointment": appointment}


def test_arrival_is_refused_for_the_crew_status_not_the_appointment_state(
    api: ApiClient,
) -> None:
    """A SCHEDULED appointment cannot be started once its crew is deactivated.

    PRD 3.3: "A `FieldTechnician` whose `X-User-ID` matches the appointment's
    `crew_id` moves it from `SCHEDULED` to `ON_SITE` on arrival, which additionally
    requires the assigned crew's `status` to be `ACTIVE`; arriving with an inactive
    crew is refused with `ERR_CREW_INACTIVE`."
    PRD 2.10: "**Referential business gates.** `ERR_INVENTORY_NOT_PUBLISHED` (409)
    when a replacement order is opened before the inventory is published;
    `ERR_UNVALIDATED_SAMPLING_STRATUM` (409) when a publication is certified while
    the water system has no sampling batch at all or has any batch not yet
    validated; `ERR_CREW_INACTIVE` (409) when arrival is attempted with an inactive
    crew; `ERR_PINNED_SNAPSHOT_STALE` (409) when a certified publication's pinned
    notifiable count no longer matches reality."

    Design: Difficulty/cross_entity_state_dependency/appointment_arrive_depends_on_verification_crew_status
    """
    scenario = _scheduled_appointment_and_its_crew(api)

    response = api.arrive_appointment(
        scenario["appointment"]["id"], make_field_technician_headers(scenario["crew"]["id"])
    )

    error = validate_error(response, "ERR_CREW_INACTIVE", 409)
    assert error["error_id"] != "ERR_APPOINTMENT_STATE_INVALID"
    assert error["error_id"] != "ERR_CREW_IDENTITY_MISMATCH"

    assert (
        fixtures.read_appointment(api, scenario["appointment"]["id"])["state"]
        == AppointmentState.SCHEDULED
    )


def test_reactivating_the_crew_makes_the_identical_arrival_succeed(api: ApiClient) -> None:
    """Nothing about the appointment changed, so flipping the crew back unblocks arrival.

    PRD 3.3: "A new crew's `status` is `ACTIVE`; the administrator may later flip it
    between `ACTIVE` and `INACTIVE`, which advances the crew's `version` by one."
    PRD 3.3: "The crew also carries a derived `scheduled_appointment_count`,
    starting at 0, counting the appointments booked to it whose `state` is
    `SCHEDULED` or `ON_SITE`."
    PRD 3.3: "A `FieldTechnician` whose `X-User-ID` matches the appointment's
    `crew_id` moves it from `SCHEDULED` to `ON_SITE` on arrival, which additionally
    requires the assigned crew's `status` to be `ACTIVE`; arriving with an inactive
    crew is refused with `ERR_CREW_INACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/appointment_arrive_depends_on_verification_crew_status
    """
    scenario = _scheduled_appointment_and_its_crew(api)
    reactivated = fixtures.set_crew_status(api, scenario["crew"]["id"], CrewStatus.ACTIVE)
    assert reactivated["status"] == CrewStatus.ACTIVE

    on_site = fixtures.arrive(
        api, scenario["appointment"]["id"], scenario["crew"]["id"]
    )

    assert on_site["state"] == AppointmentState.ON_SITE
    assert fixtures.read_crew(api, scenario["crew"]["id"])["scheduled_appointment_count"] == 1


# ---------------------------------------------------------------------------
# publication_certify_depends_on_sampling_batch_state
# ---------------------------------------------------------------------------


def _draft_publication_over_an_open_stratum(api: ApiClient):
    """A valid DRAFT publication whose water system still owns one OPEN, empty batch."""
    system = fixtures.create_water_system(
        api,
        "IL2031016",
        system_name="Pinehollow Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=[],
        funding_mode=FundingMode.WATERFALL,
    )
    line = fixtures.make_lead_line(api, system["id"], address_label="101 Elm St")
    batch = fixtures.open_batch(api, system["id"], stratum_code="STR-A", stratum_line_count=20)
    assert batch["state"] == BatchState.OPEN
    assert batch["valid_sample_count"] == 0
    advanced = fixtures.advance_to_validation_pending(api, system["id"])
    publication = fixtures.draft_publication(api, system["id"], advanced["version"])
    assert publication["state"] == PublicationState.DRAFT
    assert publication["drafted_by_user_id"] == ANALYST_USER_ID
    return {"system": system, "line": line, "batch": batch, "publication": publication}


def test_certification_is_refused_for_the_batch_state_not_the_publication_state(
    api: ApiClient,
) -> None:
    """A valid DRAFT publication cannot be certified while its stratum is still OPEN.

    PRD 3.4: "what it does carry is a blockage downstream, since a batch that is
    not `VALIDATED` keeps inventory certification for that water system failing
    with `ERR_UNVALIDATED_SAMPLING_STRATUM`."
    PRD 2.10: "**Segregation of duties.** The certifying officer's `X-User-ID`
    differs from the publication's `drafted_by_user_id`, else
    `ERR_SEGREGATION_OF_DUTIES` (403)."
    PRD 3.5: "A publication's `state` walks `DRAFT`, `CERTIFIED`, `PUBLISHED` and
    the terminal `SUPERSEDED`; a request against a publication that is not in the
    declared origin state yields `ERR_PUBLICATION_STATE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/publication_certify_depends_on_sampling_batch_state
    """
    scenario = _draft_publication_over_an_open_stratum(api)
    assert (
        fixtures.read_service_line(api, scenario["line"]["id"])["classification"]
        == Classification.LEAD
    )

    response = api.certify_publication(scenario["publication"]["id"], OFFICER_HEADERS)

    error = validate_error(response, "ERR_UNVALIDATED_SAMPLING_STRATUM", 409)
    assert error["error_id"] != "ERR_SEGREGATION_OF_DUTIES"
    assert error["error_id"] != "ERR_PUBLICATION_STATE_INVALID"

    unchanged = fixtures.read_publication(api, scenario["publication"]["id"])
    assert unchanged["state"] == PublicationState.DRAFT
    assert unchanged["notifiable_line_count"] is None


def test_validating_the_stratum_makes_the_identical_certification_succeed(
    api: ApiClient,
) -> None:
    """The publication never moved; moving the sibling batch to VALIDATED unblocks it.

    PRD 3.5: "Beyond the publication being in `DRAFT` and the certifying user id
    differing from `drafted_by_user_id`, the water system must have at least one
    sampling batch and every one of its batches must be `VALIDATED`, else
    `ERR_UNVALIDATED_SAMPLING_STRATUM`; no customer notification belonging to the
    water system's service lines may currently be overdue, else
    `ERR_NOTIFICATION_OVERDUE_BLOCK`; and the logical clock's calendar date must be
    on or before the water system's `compliance_deadline_date`, else
    `ERR_COMPLIANCE_DEADLINE_PASSED`."
    PRD 3.5: "When all of that holds, the publication moves to `CERTIFIED`,
    `certified_by_user_id` is set to the certifying `X-User-ID`, and the live
    water-system counters are frozen onto the publication as `pinned_lead_count`,
    `pinned_grr_count`, `pinned_unknown_count` and `pinned_non_lead_count` — all
    null before certification."
    PRD 3.5: "`notifiable_line_count` is then set to the sum of the pinned lead,
    galvanized and unknown counts; it is the number of customer notifications the
    publish step will have to create."

    Design: Difficulty/cross_entity_state_dependency/publication_certify_depends_on_sampling_batch_state
    """
    scenario = _draft_publication_over_an_open_stratum(api)
    fixtures.append_samples(api, scenario["batch"]["id"], scenario["line"]["id"])
    validated = fixtures.validate_batch(api, scenario["batch"]["id"])
    assert validated["state"] == BatchState.VALIDATED

    certified = fixtures.certify_publication(api, scenario["publication"]["id"])

    assert certified["state"] == PublicationState.CERTIFIED
    assert certified["certified_by_user_id"] == OFFICER_USER_ID
    assert certified["pinned_lead_count"] == 1
    assert certified["pinned_grr_count"] == 0
    assert certified["pinned_unknown_count"] == 0
    assert certified["pinned_non_lead_count"] == 0
    assert certified["notifiable_line_count"] == 1


# ---------------------------------------------------------------------------
# replacement_order_creation_depends_on_water_system_inventory_status
# ---------------------------------------------------------------------------


def _system_with_one_eligible_lead_line(api: ApiClient):
    """A DRAFT water system carrying a single ELIGIBLE lead line and nothing else."""
    system = fixtures.create_water_system(
        api,
        "IL2031017",
        system_name="Stonecreek Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=[],
        funding_mode=FundingMode.WATERFALL,
    )
    line = fixtures.make_lead_line(api, system["id"], address_label="101 Elm St")
    return {"system": system, "line": line}


def test_order_creation_is_refused_for_the_parent_inventory_status_not_the_line(
    api: ApiClient,
) -> None:
    """An ELIGIBLE lead line still cannot be ordered before the inventory is published.

    PRD 3.7: "Three gates guard the opening: the line's `replacement_state` must be
    `ELIGIBLE` or `REPLACED_PARTIAL`, else `ERR_LINE_NOT_ELIGIBLE`; the water
    system's `inventory_status` must be `PUBLISHED` or `AMENDMENT_PENDING`, because
    replacement may not precede publication, else `ERR_INVENTORY_NOT_PUBLISHED`;
    and the `program_posture` must not be `FROZEN`."
    PRD 3.2: "At the end of any classification recompute that lands the line's
    `classification` in `LEAD`, `GRR` or `UNKNOWN`, a line still sitting at
    `NOT_REQUIRED` moves to `ELIGIBLE`, its `replacement_priority_score` is
    recomputed, and its `version` advances by one."

    Design: Difficulty/cross_entity_state_dependency/replacement_order_creation_depends_on_water_system_inventory_status
    """
    scenario = _system_with_one_eligible_lead_line(api)
    advanced = fixtures.advance_to_validation_pending(api, scenario["system"]["id"])
    assert advanced["inventory_status"] == InventoryStatus.VALIDATION_PENDING
    assert advanced["program_posture"] == ProgramPosture.OPEN

    before = fixtures.read_service_line(api, scenario["line"]["id"])
    assert before["classification"] == Classification.LEAD
    assert before["replacement_state"] == ReplacementState.ELIGIBLE

    response = api.create_replacement_order(
        factories.replacement_order_payload(
            scenario["line"]["id"],
            estimated_cost_cents=100000,
            excavation_start_date="2026-08-10",
            excavation_end_date="2026-08-11",
        ),
        ADMIN_HEADERS,
    )

    error = validate_error(response, "ERR_INVENTORY_NOT_PUBLISHED", 409)
    assert error["error_id"] != "ERR_LINE_NOT_ELIGIBLE"
    assert error["error_id"] != "ERR_PROGRAM_POSTURE_FROZEN"

    assert (
        fixtures.read_service_line(api, scenario["line"]["id"])["replacement_state"]
        == ReplacementState.ELIGIBLE
    )


def test_publishing_the_parent_inventory_makes_the_identical_order_succeed(
    api: ApiClient,
) -> None:
    """The line was eligible all along; only the parent's inventory status was missing.

    PRD 3.7: "The new order is created with `fulfillment_state` `DRAFT` and
    `consent_state` `NOT_REQUESTED`, and the service line moves from `ELIGIBLE` to
    `IN_PROGRAM` — or, on a follow-up order covering the customer side of an already
    partially replaced line whose `classification` is still `LEAD`, `GRR` or
    `UNKNOWN`, from `REPLACED_PARTIAL` back to `IN_PROGRAM`, closing that axis's
    cycle `IN_PROGRAM → REPLACED_PARTIAL → IN_PROGRAM`."
    PRD 3.5: "Alongside the cascade, the water system's `inventory_status` moves to
    `PUBLISHED` — from `VALIDATION_PENDING` on a first publication, or from
    `AMENDMENT_PENDING` on a later one — its `outstanding_notification_count` and
    `program_posture` are recomputed, and its `version` advances by one."

    Design: Difficulty/cross_entity_state_dependency/replacement_order_creation_depends_on_water_system_inventory_status
    """
    scenario = _system_with_one_eligible_lead_line(api)
    fixtures.publish_inventory(api, scenario["system"]["id"], scenario["line"]["id"])
    published = fixtures.read_water_system(api, scenario["system"]["id"])
    assert published["inventory_status"] == InventoryStatus.PUBLISHED

    order = fixtures.open_order(
        api,
        scenario["line"]["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-10",
        excavation_end_date="2026-08-11",
    )

    assert order["fulfillment_state"] == FulfillmentState.DRAFT
    assert order["consent_state"] == ConsentState.NOT_REQUESTED
    assert (
        fixtures.read_service_line(api, scenario["line"]["id"])["replacement_state"]
        == ReplacementState.IN_PROGRAM
    )
