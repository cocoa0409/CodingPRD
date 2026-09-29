"""What a client may not write, and where every machine starts.

Covers computed and system fields supplied in a request body, the five shape
faults that share one error, cross-reference ownership and state integrity, and
the declared initial state of all thirteen machines.
"""
from test_helpers import (
    ApiErrorId,
    OFFICER_USER_ID,
    accept_use_report,
    assert_identity_fields,
    authorize_guide,
    create_guide,
    create_needs_assessment,
    create_operating_plan,
    create_outfitter,
    create_prospectus,
    create_qualified_guide,
    create_use_area,
    file_bond,
    file_insurance_certificate,
    file_use_report,
    guide_payload,
    issue_noncompliance_action,
    list_fee_assessments,
    outfitter_payload,
    permit_application_payload,
    qualify_guide,
    read_allocation_summary,
    set_clock,
    setup_issued_permit,
    sole_fee_assessment,
    use_area_payload,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    TEST_USERS,
    make_outfitter_representative_headers,
)

ADMIN = TEST_USERS["program_administrator_headers"]
SPECIALIST = TEST_USERS["permit_specialist_headers"]
OFFICER = TEST_USERS["authorized_officer_headers"]


def test_computed_fields_supplied_in_a_body_are_ignored_in_favour_of_the_recompute():
    """PRD §2.5: "Unknown fields in a request body are ignored rather than rejected."
    PRD §2.9: "A large part of this specification consists of fields no client ever writes.
    An area's four allocation figures and its posture, an outfitter's `status`,
    `prior_permit_count` and `active_permit_count`, a permit's `compliance_status`,
    `open_noncompliance_points`, `insurance_current`, `bond_current`, `fee_delinquent`,
    `authorized_client_capacity_total`, `service_days_used_ytd` and
    `latest_performance_rating`, an assessment's `allocated_service_days`,
    `unallocated_service_days` and `prospectus_required`, a guide's
    `base_client_capacity`, an application's `routing_decision` and `hold_expires_at`, a
    plan's `completeness_score`, and every money figure on a fee assessment are all
    derived."
    PRD §3.1: "A `LEAD` holding `WFR` with seven completed seasons therefore carries 8 (the
    lesser of 8 and 8) plus 2 (seven divided by three, floored, capped at 2), for 10."

    Design: Corner/entities/client_supplied_values_for_computed_fields_are_input_ignored
    """
    set_clock()
    outfitter = create_outfitter()
    holder = make_outfitter_representative_headers(outfitter["id"])

    area = validate_success(
        api_client.create_use_area(
            use_area_payload(
                committed_service_days=500,
                pending_service_days=400,
                available_service_days=12,
                demand_ratio=0.9,
                allocation_posture="EXHAUSTED",
            ),
            ADMIN,
        ),
        201,
    )
    assert area["committed_service_days"] == 0
    assert area["pending_service_days"] == 0
    assert area["available_service_days"] == 900
    assert area["demand_ratio"] == 0.0
    assert area["allocation_posture"] == "OPEN"

    summary = read_allocation_summary(area["id"])
    assert summary["allocatable_service_days"] == 900
    assert (
        summary["committed_service_days"]
        + summary["pending_service_days"]
        + summary["available_service_days"]
        == summary["allocatable_service_days"]
    )

    guide = validate_success(
        api_client.create_guide(
            outfitter["id"], guide_payload(base_client_capacity=99), holder
        ),
        201,
    )
    assert guide["base_client_capacity"] == 10

    application = validate_success(
        api_client.create_permit_application(
            permit_application_payload(
                outfitter["id"],
                area["id"],
                narrative="Guided day floats.",
                routing_decision="DIRECT",
                hold_expires_at="2027-02-04",
                preliminary_evaluation_score=99.9,
            ),
            SPECIALIST,
        ),
        201,
    )
    assert application["routing_decision"] is None
    assert application["hold_expires_at"] is None
    assert application["preliminary_evaluation_score"] is None


def test_system_fields_supplied_in_a_body_cannot_pre_declare_an_outcome():
    """PRD §2.4: "Every persisted record carries a server-minted `id`: a UUID string with no
    type prefix of any kind. Clients never supply an `id`; supplying one has no effect."
    PRD §2.4: "Most records additionally carry `updated_at`, in the same timestamp format,
    and `version`, an integer that begins at 1 when the record is created and increases by
    exactly 1 on every mutation of that record."
    PRD §3.2: "A drafted application lands in `status` `DRAFT` and holds no service days
    whatsoever."

    Design: Corner/entities/client_supplied_values_for_system_fields_are_input_ignored
    """
    set_clock()
    area = create_use_area()

    outfitter = validate_success(
        api_client.create_outfitter(
            outfitter_payload(
                id="11111111-1111-1111-1111-111111111111",
                created_at="2001-01-01T00:00:00Z",
                updated_at="2001-01-01T00:00:00Z",
                version=47,
                status="PERMITTED",
                prior_permit_count=9,
            ),
            SPECIALIST,
        ),
        201,
    )
    assert outfitter["id"] != "11111111-1111-1111-1111-111111111111"
    assert_identity_fields(outfitter)
    assert outfitter["created_at"].startswith("2027-01-05"), (
        "creation stamps read the logical clock, not the supplied 2001 value"
    )
    assert outfitter["version"] == 1
    assert outfitter["status"] == "APPLICANT"
    assert outfitter["prior_permit_count"] == 0

    application = validate_success(
        api_client.create_permit_application(
            permit_application_payload(
                outfitter["id"],
                area["id"],
                narrative="Guided day floats.",
                status="AWARDED",
                screened_at="2027-01-04T00:00:00Z",
                version=12,
            ),
            SPECIALIST,
        ),
        201,
    )
    assert application["status"] == "DRAFT"
    assert application["screened_at"] is None
    assert application["version"] == 1

    validate_error(
        api_client.screen_permit_application(application["id"], SPECIALIST),
        ApiErrorId.ERR_INVALID_APPLICATION_STATE,
    )
    assert read_allocation_summary(area["id"])["pending_service_days"] == 0


def test_shape_faults_of_five_different_kinds_all_return_one_invalid_request():
    """PRD §2.5: "**Request shape** — every required field present and non-null, every enum
    value a declared member, every integer in range, every date well formed and every date
    pair correctly ordered (`ERR_INVALID_REQUEST`, 400)."
    PRD §3.1: "supplying its short administrative `area_code`, which must be unique across
    all use areas, its human-readable `name`, the `total_allocated_service_days` the land
    management plan grants to commercial outfitting (at least 1), the `season_year` the
    seasonal window belongs to, the `season_open_date` and `season_close_date` bounding that
    window (both inclusive, both ISO 8601 UTC date-times), the `party_size_max` clients
    permitted in one commercial party, and the `max_clients_per_guide` ratio ceiling the
    area imposes."
    PRD §3.2: "the `requested_service_days` (at least 1), and the `proposed_activity_type`,
    one of `HUNTING`, `FISHING`, `PACK_STOCK`, `RIVER_FLOAT` or `MOUNTAINEERING`."

    Design: Corner/entities/enum_range_uniqueness_and_inverted_date_inputs_are_rejected
    """
    set_clock()
    area = create_use_area()
    outfitter = create_outfitter()

    validate_error(
        api_client.create_use_area(
            use_area_payload(
                area_code="BRW-11",
                name="Zero Allocation",
                total_allocated_service_days=0,
                reserved_admin_service_days=0,
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    validate_error(
        api_client.create_use_area(
            use_area_payload(
                area_code="BRW-12",
                name="All Reserved",
                total_allocated_service_days=500,
                reserved_admin_service_days=500,
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    validate_error(
        api_client.create_use_area(
            use_area_payload(
                area_code="BRW-13",
                name="Inverted Season",
                season_open_date="2027-09-30",
                season_close_date="2027-05-15",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    validate_error(
        api_client.create_use_area(
            use_area_payload(
                area_code="BRW-01",
                name="Duplicate Code",
                season_year=2028,
                season_open_date="2028-05-15",
                season_close_date="2028-09-30",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    validate_error(
        api_client.create_outfitter(
            outfitter_payload(
                legal_name="Short EIN LLC", ein="4100001", contact_email="short@x.example"
            ),
            SPECIALIST,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    validate_error(
        api_client.create_outfitter(
            outfitter_payload(
                legal_name="Twin EIN LLC", ein="410000001", contact_email="twin@x.example"
            ),
            SPECIALIST,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    validate_error(
        api_client.create_permit_application(
            permit_application_payload(
                outfitter["id"], area["id"], proposed_activity_type="HELI_SKIING"
            ),
            SPECIALIST,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    validate_error(
        api_client.create_permit_application(
            permit_application_payload(
                outfitter["id"], area["id"], requested_service_days=0
            ),
            SPECIALIST,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    areas, area_meta = validate_paginated(api_client.list_use_areas(ADMIN))
    assert area_meta["total_count"] == 1
    assert [row["area_code"] for row in areas] == ["BRW-01"]
    apps, app_meta = validate_paginated(api_client.list_permit_applications(SPECIALIST))
    assert app_meta["total_count"] == 0 and apps == []


def test_a_resolvable_reference_is_still_checked_for_ownership_and_state():
    """PRD §3.6: "The guide's `outfitter_id` must equal the permit's `outfitter_id`, else
    `ERR_GUIDE_OUTFITTER_MISMATCH` — a holder may not borrow another outfitter's guide."
    PRD §3.2: "Succession is checked strictly at both drafting and screening time: a
    `RENEWAL` must carry a `predecessor_permit_id`, that permit must belong to the same
    outfitter and the same use area as the application, and its `administrative_status` must
    be `ACTIVE`, `SUSPENDED` or `EXPIRED`; a `NEW` application must not carry one at all."
    PRD §3.3: "The cited assessment must be `PUBLISHED`, else
    `ERR_NEEDS_ASSESSMENT_NOT_PUBLISHED`, and must record `public_need_finding`
    `NEED_EXISTS`, else `ERR_NO_PUBLIC_NEED`"

    Design: Corner/entities/flat_topology_cross_reference_integrity_rejects_mismatched_owners
    """
    context = setup_issued_permit()
    area = context["use_area"]
    permit = context["permit"]
    alpine_holder = context["holder_headers"]

    unpublished = create_needs_assessment(
        area["id"],
        assessment_year=2028,
        determined_capacity_service_days=800,
    )
    assert unpublished["status"] == "DRAFT"

    cedar = create_outfitter(
        legal_name="Cedar Creek Guides LLC",
        ein="410000002",
        contact_email="ops@cedar.example",
    )
    cedar_guide = create_qualified_guide(
        cedar["id"], full_name="Tom Reed", seasons_experience=5
    )
    assert cedar_guide["status"] == "QUALIFIED"

    validate_error(
        api_client.create_guide_authorization(
            permit["id"], {"guide_id": cedar_guide["id"]}, alpine_holder
        ),
        ApiErrorId.ERR_GUIDE_OUTFITTER_MISMATCH,
    )

    validate_error(
        api_client.create_permit_application(
            permit_application_payload(
                cedar["id"],
                area["id"],
                application_type="RENEWAL",
                requested_service_days=100,
                predecessor_permit_id=permit["id"],
            ),
            SPECIALIST,
        ),
        ApiErrorId.ERR_SUCCESSION_PREDECESSOR_INVALID,
    )

    validate_error(
        api_client.create_permit_application(
            permit_application_payload(
                context["outfitter"]["id"],
                area["id"],
                requested_service_days=100,
                predecessor_permit_id=permit["id"],
            ),
            SPECIALIST,
        ),
        ApiErrorId.ERR_SUCCESSION_PREDECESSOR_INVALID,
    )

    validate_error(
        api_client.create_prospectus(
            {
                "use_area_id": area["id"],
                "needs_assessment_id": unpublished["id"],
                "offered_service_days": 300,
                "submission_deadline_date": "2027-03-01",
            },
            SPECIALIST,
        ),
        ApiErrorId.ERR_NEEDS_ASSESSMENT_NOT_PUBLISHED,
    )

    after = validate_success(api_client.get_permit(permit["id"], SPECIALIST))
    assert after["authorized_client_capacity_total"] == 0
    _rows, meta = validate_paginated(
        api_client.list_permit_guide_authorizations(permit["id"], SPECIALIST)
    )
    assert meta["total_count"] == 0


def test_every_machine_lands_in_its_declared_initial_state():
    """PRD §3.1: "A newly opened area is evaluated against an empty permit and application
    set, so it reports `committed_service_days` 0, `pending_service_days` 0,
    `available_service_days` equal to its allocatable total, `demand_ratio` 0.0 and
    `allocation_posture` `OPEN`."
    PRD §3.1: "A new solicitation opens in `status` `OPEN` with `responsive_application_count`
    0, `awarded_application_id` null and `cancellation_reason_code` null."
    PRD §3.5: "A new plan enters `DRAFT` with `revision_round` 0, `deficiency_sections` an
    empty array, and `reviewed_by_user_id`, `approved_by_user_id` and `rejection_reason_code`
    all null."
    PRD §3.7: "The report is created `SUBMITTED` with `accepted_at` and `supersedes_report_id`
    null."
    PRD §3.7: "A fee assessment is never created by a request of its own: it exists only as a
    consequence of an acceptance, its `season_year` is unique per permit, and it is
    discoverable only through the permit's assessment listing, ordered by `season_year`
    ascending then `created_at` ascending, with optional `season_year` and `status` filters."

    Design: Corner/state_machines/every_entity_lands_in_its_declared_initial_state
    """
    context = setup_issued_permit()
    area = context["use_area"]
    permit = context["permit"]
    outfitter = context["outfitter"]

    assert context["needs_assessment"]["status"] == "PUBLISHED"
    assert context["application"]["status"] == "PERMIT_ISSUED"
    assert permit["administrative_status"] == "ISSUED"
    assert permit["compliance_status"] == "COMPLIANT"
    assert permit["suspension_count"] == 0
    assert permit["open_noncompliance_points"] == 0
    assert permit["authorized_client_capacity_total"] == 0
    assert permit["service_days_used_ytd"] == 0

    prospectus = create_prospectus(
        area["id"], context["needs_assessment"]["id"], offered_service_days=100
    )
    assert prospectus["status"] == "OPEN"
    assert prospectus["responsive_application_count"] == 0
    assert prospectus["awarded_application_id"] is None
    assert prospectus["cancellation_reason_code"] is None

    guide = create_guide(outfitter["id"])
    assert guide["status"] == "PENDING_QUALIFICATION"
    assert guide["qualified_at"] is None
    assert guide["base_client_capacity"] == 10, (
        "capacity is computed at hire even before the program qualifies the guide"
    )
    qualify_guide(guide["id"])

    authorization = authorize_guide(permit["id"], guide["id"], outfitter["id"])
    assert authorization["status"] == "AUTHORIZED"
    assert authorization["revoked_at"] is None
    assert authorization["authorized_client_capacity"] == 8

    certificate = file_insurance_certificate(permit["id"], outfitter["id"])
    assert certificate["status"] == "ACTIVE"

    bond = file_bond(permit["id"], outfitter["id"])
    assert bond["status"] == "ACTIVE"
    assert bond["required_amount_cents"] == 1_000_000

    plan = create_operating_plan(permit["id"], outfitter["id"])
    assert plan["status"] == "DRAFT"
    assert plan["revision_round"] == 0
    assert plan["deficiency_sections"] == []
    assert plan["completeness_score"] == 100.0

    set_clock("2027-07-01T00:00:00Z")
    report = file_use_report(permit["id"], outfitter["id"])
    assert report["status"] == "SUBMITTED"
    assert report["accepted_at"] is None
    assert report["supersedes_report_id"] is None
    assert report["season_year"] == 2027
    assert report["adjusted_gross_revenue_cents"] == 2_000_000
    assert report["applied_rate_bp"] is None
    assert report["fee_component_cents"] is None

    rows, _meta = list_fee_assessments(permit["id"])
    assert rows == [], "no assessment exists before an acceptance"

    accept_use_report(report["id"])
    assessment = sole_fee_assessment(permit["id"])
    assert assessment["status"] == "PROVISIONAL"
    assert assessment["variant_applied"] == "PROVISIONAL_PER_REPORT"
    assert assessment["reported_agr_cents"] == 2_000_000
    assert assessment["assessed_fee_cents"] == 60_000
    assert assessment["paid_to_date_cents"] == 0
    assert assessment["balance_due_cents"] == 60_000

    action = issue_noncompliance_action(permit["id"])
    assert action["status"] == "ISSUED"
    assert action["points"] == 2
    assert action["issued_by_user_id"] == OFFICER_USER_ID

    final = validate_success(api_client.get_permit(permit["id"], SPECIALIST))
    assert final["fee_delinquent"] is True
    assert final["compliance_status"] == "PROBATION"
    assert final["administrative_status"] == "ISSUED", (
        "the two permit dimensions move on disjoint triggers"
    )
