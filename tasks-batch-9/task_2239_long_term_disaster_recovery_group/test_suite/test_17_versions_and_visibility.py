"""Two clients racing the same parent record, and the promise that a 2xx already tells the truth.

The version guards are the only thing separating the refused write from the accepted one here:
each rejected body is resubmitted byte-for-byte against a fresh read and then succeeds.
"""

from test_helpers import (
    ADMIN,
    BUILDER,
    CASE_MANAGER,
    CHAIR,
    OFFICER,
    ApiErrorId,
    assert_disbursement,
    assert_funding_commitment,
    assert_funding_source,
    assert_member_organization,
    assert_recovery_case,
    case_presentation_payload,
    case_version,
    construction_project_payload,
    create_case,
    create_funding_source,
    create_survivor,
    disbursement_payload,
    document_damage,
    funding_commitment_payload,
    make_member_org_delegate_headers,
    open_session,
    permit_project,
    read_case,
    read_presentation,
    run_assessment,
    schedule_session,
    seat_member_org,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    verify_damage,
)


def test_the_second_delegate_must_re_read_before_pledging(api):
    """PRD §2.10: "A `POST /funding-commitments` request must carry
    `expected_presentation_version` holding the client's last observed `version` of the target
    `CasePresentation`. If it does not match the presentation's current `version`, the create
    is rejected with `ERR_STALE_PRESENTATION_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/corner_second_delegate_pledging_on_a_stale_presentation_version_is_refused
    """
    set_clock()
    survivor = create_survivor(
        household_name="Whitfield Household",
        primary_contact_phone="555-0310",
        household_size=5,
        income_band="VLI",
        head_of_household_age=41,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Whole-house framing",
        documented_cost_cents=2_000_000,
        photo_count=9,
    )
    verify_damage(item["id"], verified_cost_cents=2_000_000)
    assessment = run_assessment(case["id"])
    first_org = seat_member_org(
        org_name="Harbor Lutheran Relief",
        org_type="FAITH_BASED",
        contact_email="harbor@relief.example",
        annual_pledge_cap_cents=1_000_000,
    )
    second_org = seat_member_org(
        org_name="Downtown Rotary Trust",
        org_type="CIVIC_CLUB",
        contact_email="rotary@trust.example",
        annual_pledge_cap_cents=1_000_000,
    )
    session = schedule_session(
        session_label="UNT concurrent pledges", quorum_min_member_orgs=2
    )
    open_session(session["id"], [first_org["id"], second_org["id"]])
    presentation = validate_success(
        api.create_case_presentation(
            case_presentation_payload(
                case["id"],
                session["id"],
                assessment["id"],
                narrative="Whole-house framing rebuild.",
            ),
            CASE_MANAGER,
        ),
        201,
    )
    validate_success(api.present_case_presentation(presentation["id"], {}, CHAIR))
    window = validate_success(api.deliberate_case_presentation(presentation["id"], {}, CHAIR))
    # Both delegates read the same version before either of them writes.
    shared_read = window["version"]
    second_body = funding_commitment_payload(
        presentation["id"], second_org["id"], 500_000, shared_read
    )
    delegate_headers = make_member_org_delegate_headers(second_org["id"])

    first_pledge = validate_success(
        api.create_funding_commitment(
            funding_commitment_payload(
                presentation["id"], first_org["id"], 500_000, shared_read
            ),
            make_member_org_delegate_headers(first_org["id"]),
        ),
        201,
    )
    overtaken = api.create_funding_commitment(second_body, delegate_headers)

    assert_funding_commitment(first_pledge)
    assert first_pledge["status"] == "PLEDGED"
    assert first_pledge["pledged_cents"] == 500_000
    validate_error(overtaken, ApiErrorId.ERR_STALE_PRESENTATION_VERSION.value, 412)
    moved_on = read_presentation(presentation["id"])
    assert moved_on["version"] > shared_read
    # The refused pledge left no trace on the running total.
    assert moved_on["pledged_total_cents"] == 500_000
    second_body["expected_presentation_version"] = moved_on["version"]
    resubmitted = validate_success(
        api.create_funding_commitment(second_body, delegate_headers), 201
    )
    assert resubmitted["status"] == "PLEDGED"
    assert resubmitted["pledged_cents"] == 500_000
    pledges, meta = validate_paginated(
        api.list_funding_commitments(CHAIR, params={"presentation_id": presentation["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in pledges} == {first_pledge["id"], resubmitted["id"]}
    assert read_presentation(presentation["id"])["pledged_total_cents"] == 1_000_000
    charged_once = validate_success(api.get_member_organization(second_org["id"], ADMIN))
    assert_member_organization(charged_once)
    assert charged_once["committed_cents"] == 500_000
    assert charged_once["remaining_pledge_capacity_cents"] == 500_000


def test_the_officer_must_re_read_the_case_after_the_table_moves_money(api):
    """PRD §2.10: "A `POST /disbursements` request must carry `expected_case_version` holding
    the client's last observed `version` of the target `RecoveryCase`. If it does not match the
    case's current `version`, the create is rejected with `ERR_STALE_CASE_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_complexity_layers/corner_disbursement_request_on_a_stale_case_version_is_refused
    """
    set_clock()
    survivor = create_survivor(
        household_name="Bergstrom Household",
        primary_contact_phone="555-0311",
        household_size=3,
        income_band="ELI",
        head_of_household_age=58,
        has_member_with_disability=True,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Sill plate and joists",
        documented_cost_cents=1_000_000,
        photo_count=6,
    )
    verify_damage(item["id"], verified_cost_cents=1_000_000)
    assessment = run_assessment(case["id"])
    org = seat_member_org(
        org_name="Northside Community Fund",
        org_type="NONPROFIT",
        contact_email="north@fund.example",
        annual_pledge_cap_cents=2_000_000,
    )
    create_funding_source(
        label="Sill plate repair grant",
        source_type="FOUNDATION_GRANT",
        restriction_code="STRUCTURE_REPAIR_ONLY",
        total_cents=1_000_000,
        admin_retention_allowed=False,
    )
    session = schedule_session(session_label="UNT stale case version")
    open_session(session["id"], [org["id"]])
    presentation = validate_success(
        api.create_case_presentation(
            case_presentation_payload(
                case["id"],
                session["id"],
                assessment["id"],
                narrative="Sill plate and joist replacement.",
            ),
            CASE_MANAGER,
        ),
        201,
    )
    validate_success(api.present_case_presentation(presentation["id"], {}, CHAIR))
    window = validate_success(api.deliberate_case_presentation(presentation["id"], {}, CHAIR))
    # The officer's read predates the table's award.
    officer_read = case_version(case["id"])
    commitment = validate_success(
        api.create_funding_commitment(
            funding_commitment_payload(
                presentation["id"], org["id"], 1_000_000, window["version"]
            ),
            make_member_org_delegate_headers(org["id"]),
        ),
        201,
    )
    validate_success(
        api.decide_case_presentation(
            presentation["id"],
            {"decision": "AWARD", "decision_note": "Fully pledged by Northside."},
            CHAIR,
        )
    )
    project = validate_success(
        api.create_construction_project(
            construction_project_payload(
                case["id"],
                scope_code="STRUCTURE_REBUILD",
                required_trade_hours={"FRAMING": 150},
                estimated_material_cents=650_000,
            ),
            BUILDER,
        ),
        201,
    )
    permit_project(project["id"], permit_number="PB-4072")
    current = case_version(case["id"])
    body = disbursement_payload(
        case["id"],
        1_000_000,
        current - 1,
        purpose_code="STRUCTURE_REPAIR",
        project_id=project["id"],
        commitment_id=commitment["id"],
        payee_name="Sillworks Carpentry LLC",
    )

    stale = api.create_disbursement(body, OFFICER)

    # The award's commitment cascade moved the case on from what the officer had read.
    assert current > officer_read
    validate_error(stale, ApiErrorId.ERR_STALE_CASE_VERSION.value, 412)
    nothing_created, meta = validate_paginated(
        api.list_disbursements(OFFICER, params={"case_id": case["id"]})
    )
    assert meta["total_count"] == 0
    assert nothing_created == []
    body["expected_case_version"] = current
    requested = validate_success(api.create_disbursement(body, OFFICER), 201)
    assert_disbursement(requested)
    assert requested["status"] == "DOB_CLEARED"
    assert requested["dob_exposure_cents"] == 0
    assert requested["requested_cents"] == 1_000_000
    approved = validate_success(
        api.approve_disbursement(
            requested["id"], {"approval_note": "Approved at the current case version."}, ADMIN
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["net_cents"] == 1_000_000
    assert approved["gross_cents"] == 1_000_000
    committed = read_case(case["id"])
    assert_recovery_case(committed)
    assert committed["total_committed_cents"] == 1_000_000
    # Approval reserves the source; only payment moves the case's disbursed ledger.
    assert committed["total_net_disbursed_cents"] == 0
    assert committed["funding_status"] == "FULLY_COMMITTED"


def test_a_successful_write_already_carries_everything_it_derived(api):
    """PRD §2.6: "There is no deferred reconciliation and no eventual consistency: by the time
    a 2xx response is written, every derived roll-up named in §3 already reflects the change."

    Design: Corner/consistency_model/corner_every_derived_figure_is_already_present_in_the_response_that_caused_it
    """
    set_clock()
    survivor = create_survivor(
        household_name="Iravani Household",
        primary_contact_phone="555-0312",
        household_size=4,
        income_band="ELI",
        head_of_household_age=46,
        is_uninsured=True,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Rear wall and header",
        documented_cost_cents=1_000_000,
        photo_count=5,
    )
    verify_damage(item["id"], verified_cost_cents=1_000_000)
    assessment = run_assessment(case["id"])
    org = seat_member_org(
        org_name="Riverbend Benevolence Society",
        org_type="CIVIC_CLUB",
        contact_email="riverbend@bene.example",
        annual_pledge_cap_cents=1_000_000,
    )
    source = create_funding_source(
        label="Rear wall rebuild grant",
        source_type="FOUNDATION_GRANT",
        restriction_code="STRUCTURE_REPAIR_ONLY",
        total_cents=1_000_000,
        admin_retention_allowed=False,
    )
    project = validate_success(
        api.create_construction_project(
            construction_project_payload(
                case["id"],
                scope_code="STRUCTURE_REBUILD",
                required_trade_hours={"FRAMING": 130},
                estimated_material_cents=600_000,
            ),
            BUILDER,
        ),
        201,
    )
    permit_project(project["id"], permit_number="PB-4073")
    session = schedule_session(session_label="UNT immediate consistency")
    open_session(session["id"], [org["id"]])
    presentation = validate_success(
        api.create_case_presentation(
            case_presentation_payload(
                case["id"],
                session["id"],
                assessment["id"],
                narrative="Rear wall and header rebuild.",
            ),
            CASE_MANAGER,
        ),
        201,
    )
    validate_success(api.present_case_presentation(presentation["id"], {}, CHAIR))
    commitment = validate_success(
        api.create_funding_commitment(
            funding_commitment_payload(
                presentation["id"],
                org["id"],
                1_000_000,
                validate_success(
                    api.deliberate_case_presentation(presentation["id"], {}, CHAIR)
                )["version"],
            ),
            make_member_org_delegate_headers(org["id"]),
        ),
        201,
    )

    awarded = validate_success(
        api.decide_case_presentation(
            presentation["id"],
            {"decision": "AWARD", "decision_note": "Fully pledged; no bridge needed."},
            CHAIR,
        )
    )

    # Every award figure is in the award's own body.
    assert awarded["bridge_tier"] == "TIER_B"
    assert awarded["bridge_authorized_cents"] == 0
    assert awarded["awarded_cents"] == 1_000_000
    assert awarded["shortfall_cents"] == 0
    cascaded = read_case(case["id"])
    assert cascaded["total_committed_cents"] == 1_000_000
    assert cascaded["funding_status"] == "FULLY_COMMITTED"
    assert cascaded["case_status"] == "ACTIVE_RECOVERY"
    charged = validate_success(api.get_member_organization(org["id"], ADMIN))
    assert charged["committed_cents"] == 1_000_000
    assert charged["remaining_pledge_capacity_cents"] == 0
    requested = validate_success(
        api.create_disbursement(
            disbursement_payload(
                case["id"],
                1_000_000,
                cascaded["version"],
                purpose_code="STRUCTURE_REPAIR",
                project_id=project["id"],
                commitment_id=commitment["id"],
                payee_name="Headerline Framing LLC",
            ),
            OFFICER,
        ),
        201,
    )
    assert requested["dob_pool_cents"] == 0
    assert requested["dob_exposure_cents"] == 0
    assert requested["status"] == "DOB_CLEARED"
    approved = validate_success(
        api.approve_disbursement(
            requested["id"], {"approval_note": "Approved; single restricted source."}, ADMIN
        )
    )
    assert approved["allocation_lines"] == [
        {
            "funding_source_id": source["id"],
            "net_cents": 1_000_000,
            "retention_cents": 0,
            "gross_cents": 1_000_000,
        }
    ]
    assert approved["net_cents"] == 1_000_000
    assert approved["admin_retained_cents"] == 0
    assert approved["gross_cents"] == 1_000_000
    reserved = validate_success(api.get_funding_source(source["id"], ADMIN))
    assert_funding_source(reserved)
    assert reserved["committed_cents"] == 1_000_000
    assert reserved["available_cents"] == 0
    assert reserved["status"] == "EXHAUSTED"
    paid = validate_success(
        api.pay_disbursement(requested["id"], {"payment_reference": "CHK-7301"}, OFFICER)
    )
    assert paid["status"] == "PAID"
    settled = read_case(case["id"])
    assert settled["total_net_disbursed_cents"] == 1_000_000
    assert settled["funding_status"] == "SATISFIED"
