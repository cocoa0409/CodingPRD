"""
Who may act, and in whose name.

Three separate gates live in this file, and the PRD keeps them apart with three
different error identifiers. The first is the role matrix: each of the five
staff roles drives the writes reserved to it, and every other role is turned
away from those same writes. The second is entity-backed identity: the
Applicant role carries the id of the applicant record it acts for, so a buyer
holding the right role but the wrong id is still refused. The third is the
four-eyes rule: two decisions compare one operator identifier against another
recorded earlier, so the same person cannot make both halves of the decision.
"""

from test_helpers import (
    CLERK_1,
    DISP_1,
    DISP_2,
    DISPOSITION_OFFICER_2,
    INTAKE_1,
    INTAKE_2,
    INTAKE_OFFICER_1,
    INTAKE_OFFICER_2,
    INV_1,
    TREAS_1,
    ApiErrorId,
    assert_applicant,
    assert_contractor,
    assert_funding_source,
    assert_property,
    expected_reserve_floor_cents,
    factories,
    fixtures,
    make_applicant_headers,
    validate_error,
    validate_success,
)


# ── the permitted half of the role matrix ───────────────────────────────────
def test_intake_officer_registers_a_parcel(api):
    """
    The intake officer is the role that puts a parcel into the prospect registry.

    `IntakeOfficer` — acquisition and title staff. Registers parcels, posts code-enforcement snapshots, records owners of record and the parcel adjacency graph, runs acquisition packets and clears title.

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
    """
    payload = factories.property_payload(
        address="3280 Dogwood Row",
        situs_ward=6,
        lot_area_sqft=6000,
        assessed_value_cents=400000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=3,
    )

    parcel = validate_success(api.create_property(payload, INTAKE_1), 201)

    assert_property(parcel)
    assert parcel["custody_status"] == "PROSPECT"
    assert parcel["title_status"] == "CLOUDED"


def test_board_clerk_authorizes_a_funding_source(api):
    """
    The board clerk is the role that authorizes the money the authority spends.

    `BoardClerk` — clerk to the board of directors. Authorizes funding sources, board-approves acquisition packets, records board decisions on disposition applications and executes development agreements.

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
    """
    payload = factories.funding_source_payload(
        name="Role Matrix Line",
        source_type="GRANT",
        authorized_cents=900000,
        restriction="ANY",
        expires_on="2029-12-31T00:00:00Z",
    )

    source = validate_success(api.create_funding_source(payload, CLERK_1), 201)

    assert_funding_source(source)
    assert source["status"] == "ACTIVE"
    assert source["available_cents"] == 900000
    assert source["reserve_floor_cents"] == expected_reserve_floor_cents(900000)


def test_disposition_officer_registers_an_applicant(api):
    """
    The disposition officer is the role that registers a prospective buyer.

    `DispositionOfficer` — disposition program staff. Lists inventory parcels, holds community reuse hearings, registers applicants, screens buyers, requests further information and recommends awards.

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
    """
    payload = factories.applicant_payload(
        legal_name="Ursula Bergman",
        applicant_type="INDIVIDUAL",
        contact_email="ursula@example.com",
    )

    applicant = validate_success(api.create_applicant(payload, DISP_1), 201)

    assert_applicant(applicant)
    assert applicant["eligibility_status"] == "ELIGIBLE"
    assert applicant["conveyed_property_count"] == 0


def test_inventory_manager_registers_a_contractor(api):
    """
    The inventory manager is the role that onboards the crews who do the work.

    `InventoryManager` — inventory operations. Registers contractors, schedules and settles securing, mowing and demolition work, plans and executes demolition prioritization runs, and runs the periodic compliance sweep.

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
    """
    # The debarment flag is left out of the payload, so the registration also
    # exercises its documented default of false.
    payload = factories.without(
        factories.contractor_payload(
            name="Dogwood Row Crews",
            license_expires_on="2027-12-31T00:00:00Z",
            max_concurrent_crews=2,
            specialties=["MOW", "SECURE"],
        ),
        "debarred",
    )

    contractor = validate_success(api.create_contractor(payload, INV_1), 201)

    assert_contractor(contractor)
    assert contractor["debarred"] is False
    assert contractor["specialties"] == ["MOW", "SECURE"]


def test_county_treasurer_posts_the_tax_roll(api):
    """
    The county treasurer is the role that posts a parcel's delinquent tax balance.

    `CountyTreasurer` — posts tax roll delinquency balances, books tax-increment recapture receipts and audits the funding ledger.

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
    """
    parcel = fixtures.create_property(
        api,
        address="3280 Dogwood Row",
        situs_ward=6,
        lot_area_sqft=6000,
        assessed_value_cents=400000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=3,
    )

    posted = validate_success(
        api.post_tax_roll_posting(
            parcel["id"],
            {"delinquent_tax_balance_cents": 48000, "tax_year": 2025},
            TREAS_1,
        ),
        200,
    )

    assert_property(posted)
    assert posted["delinquent_tax_balance_cents"] == 48000


# ── the denial half of the role matrix ──────────────────────────────────────
def _one_parcel_and_one_source(api):
    """
    A PROSPECT parcel and an unrestricted funding source, so that every refused
    attempt below is otherwise well formed and would have succeeded under the
    role the endpoint reserves it to.
    """
    parcel = fixtures.create_property(
        api,
        address="3290 Elderberry Row",
        situs_ward=6,
        lot_area_sqft=6000,
        assessed_value_cents=400000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=3,
    )
    source = fixtures.create_funding_source(
        api,
        name="Denial Matrix Line",
        source_type="GRANT",
        authorized_cents=900000,
        restriction="ANY",
        expires_on="2029-12-31T00:00:00Z",
    )
    return parcel, source


def test_disposition_officer_cannot_register_a_parcel(api):
    """
    Registry intake is refused to the disposition officer with a role-permission error.

    If the headers are well formed but the declared role is not among the roles authorized for the requested operation (see the table in §4), the rejection is `ERR_ROLE_NOT_PERMITTED` (403).

    Design: Corner/rbac/other_roles_exclusive_operations_are_rejected
    """
    _one_parcel_and_one_source(api)

    response = api.create_property(
        factories.property_payload(
            address="3291 Elderberry Row",
            situs_ward=6,
            lot_area_sqft=6000,
            assessed_value_cents=400000,
            structure_present=True,
            structure_condition_grade="C",
            vacancy_months=3,
        ),
        DISP_1,
    )

    validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED.value, 403)
    parcels = validate_success(api.list_properties(INTAKE_1), 200)
    assert len(parcels) == 1


def test_intake_officer_cannot_authorize_a_funding_source(api):
    """
    Authorizing money is refused to the intake officer with a role-permission error.

    If the headers are well formed but the declared role is not among the roles authorized for the requested operation (see the table in §4), the rejection is `ERR_ROLE_NOT_PERMITTED` (403).

    Design: Corner/rbac/other_roles_exclusive_operations_are_rejected
    """
    _parcel, source = _one_parcel_and_one_source(api)

    response = api.create_funding_source(
        factories.funding_source_payload(
            name="Unauthorized Line",
            source_type="GRANT",
            authorized_cents=100000,
            restriction="ANY",
            expires_on="2029-12-31T00:00:00Z",
        ),
        INTAKE_1,
    )

    validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED.value, 403)
    unchanged = fixtures.read_funding_source(api, source["id"])
    assert unchanged["version"] == source["version"]
    assert unchanged["authorized_cents"] == 900000


def test_inventory_manager_cannot_list_a_parcel_for_disposition(api):
    """
    Listing a parcel for disposition is refused to the inventory manager with a role-permission error.

    If the headers are well formed but the declared role is not among the roles authorized for the requested operation (see the table in §4), the rejection is `ERR_ROLE_NOT_PERMITTED` (403).

    Design: Corner/rbac/other_roles_exclusive_operations_are_rejected
    """
    parcel, _source = _one_parcel_and_one_source(api)

    response = api.list_property_for_disposition(parcel["id"], INV_1)

    # The role gate answers first, so the parcel's own custody and title, which
    # would have blocked the call later, never get a say.
    validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED.value, 403)
    untouched = fixtures.read_property(api, parcel["id"])
    assert untouched["custody_status"] == "PROSPECT"
    assert untouched["listed_at"] is None
    assert untouched["version"] == parcel["version"]


def test_board_clerk_cannot_plan_a_demolition_run(api):
    """
    Planning a demolition prioritization run is refused to the board clerk with a role-permission error.

    If the headers are well formed but the declared role is not among the roles authorized for the requested operation (see the table in §4), the rejection is `ERR_ROLE_NOT_PERMITTED` (403).

    Design: Corner/rbac/other_roles_exclusive_operations_are_rejected
    """
    _parcel, source = _one_parcel_and_one_source(api)

    response = api.create_demolition_run(
        factories.demolition_run_payload(source["id"], 100000, source["version"]),
        CLERK_1,
    )

    validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED.value, 403)
    unchanged = fixtures.read_funding_source(api, source["id"])
    assert unchanged["open_run_count"] == 0
    assert unchanged["version"] == source["version"]
    runs = validate_success(
        api.list_funding_source_demolition_runs(source["id"], INV_1), 200
    )
    assert runs == []


def test_disposition_officer_cannot_post_the_tax_roll(api):
    """
    Posting the county tax roll is refused to the disposition officer with a role-permission error.

    If the headers are well formed but the declared role is not among the roles authorized for the requested operation (see the table in §4), the rejection is `ERR_ROLE_NOT_PERMITTED` (403).

    Design: Corner/rbac/other_roles_exclusive_operations_are_rejected
    """
    parcel, _source = _one_parcel_and_one_source(api)

    response = api.post_tax_roll_posting(
        parcel["id"], {"delinquent_tax_balance_cents": 1000, "tax_year": 2025}, DISP_1
    )

    validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED.value, 403)
    untouched = fixtures.read_property(api, parcel["id"])
    assert untouched["delinquent_tax_balance_cents"] == 0
    assert untouched["version"] == parcel["version"]


# ── entity-backed applicant identity ────────────────────────────────────────
def _draft_application_and_a_stranger(api):
    """
    A listed grade C parcel assessed at 100,000 cents, so the homeowner-sale
    quote settles at its 100,000-cent floor, with a DRAFT application belonging
    to buyer A and an unrelated buyer B registered alongside it.
    """
    bundle = fixtures.listed_parcel(
        api,
        funding_source=fixtures.create_acquisition_funding_source(
            api, name="Owner Check Line"
        ),
        property_overrides={
            "address": "3300 Filbert Row",
            "situs_ward": 6,
            "lot_area_sqft": 6000,
            "assessed_value_cents": 100000,
            "structure_present": True,
            "structure_condition_grade": "C",
            "vacancy_months": 5,
        },
        packet_overrides={"donor_name": "Filbert Trust"},
    )
    buyer_a = fixtures.create_applicant(
        api, legal_name="Vera Lindqvist", contact_email="vera@example.com"
    )
    buyer_b = fixtures.create_applicant(
        api, legal_name="Walter Nkemdirim", contact_email="walter@example.com"
    )
    application = fixtures.draft_application(
        api,
        bundle["property"]["id"],
        buyer_a["id"],
        program="HOMEOWNER_SALE",
        proposed_use="Owner-occupied single family",
        offer_price_cents=100000,
    )
    return {
        "application": application,
        "buyer_a": buyer_a,
        "buyer_b": buyer_b,
    }


def test_a_stranger_cannot_submit_another_buyers_application(api):
    """
    A buyer carrying the applicant role but a different applicant id may not submit someone else's application.

    Ownership is checked against that value: submitting or resubmitting an application requires `X-User-ID` to equal the application's `applicant_id`; reporting milestone completions requires `X-User-ID` to equal the `applicant_id` of the agreement's originating application; and when an `Applicant` drafts a new application, the `applicant_id` in the payload must be its own. Any mismatch is rejected with `ERR_NOT_APPLICATION_OWNER` (403).

    Design: Corner/rbac/applicant_cannot_act_on_another_applicants_application
    """
    scene = _draft_application_and_a_stranger(api)
    application_id = scene["application"]["id"]

    response = api.submit_application(
        application_id, make_applicant_headers(scene["buyer_b"]["id"])
    )

    validate_error(response, ApiErrorId.NOT_APPLICATION_OWNER.value, 403)
    untouched = fixtures.read_application(api, application_id)
    assert untouched["status"] == "DRAFT"
    assert untouched["submitted_at"] is None
    assert untouched["applicant_id"] == scene["buyer_a"]["id"]
    assert untouched["version"] == scene["application"]["version"]


def test_the_rightful_owner_still_submits_after_the_strangers_attempt(api):
    """
    The buyer whose id matches the application's applicant_id submits it successfully, unaffected by the stranger's refused attempt.

    Ownership is checked against that value: submitting or resubmitting an application requires `X-User-ID` to equal the application's `applicant_id`; reporting milestone completions requires `X-User-ID` to equal the `applicant_id` of the agreement's originating application; and when an `Applicant` drafts a new application, the `applicant_id` in the payload must be its own. Any mismatch is rejected with `ERR_NOT_APPLICATION_OWNER` (403).

    Design: Corner/rbac/applicant_cannot_act_on_another_applicants_application
    """
    scene = _draft_application_and_a_stranger(api)
    application_id = scene["application"]["id"]

    validate_error(
        api.submit_application(
            application_id, make_applicant_headers(scene["buyer_b"]["id"])
        ),
        ApiErrorId.NOT_APPLICATION_OWNER.value,
        403,
    )

    submitted = validate_success(
        api.submit_application(
            application_id, make_applicant_headers(scene["buyer_a"]["id"])
        ),
        200,
    )

    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_at"] is not None
    assert submitted["revision_round"] == 0
    assert submitted["applicant_id"] == scene["buyer_a"]["id"]


# ── four eyes on the two decisions that demand them ─────────────────────────
def test_the_officer_who_opened_a_packet_cannot_close_it(api):
    """
    The intake officer who initiated an acquisition packet may not be the one who closes it, but a second holder of the same role may.

    A different `IntakeOfficer` — one whose `X-User-ID` differs from `initiated_by_user_id`, on pain of `ERR_SEGREGATION_OF_DUTIES` — closes a `BOARD_APPROVED` packet by supplying the recorded `deed_reference`.

    Design: Corner/rbac/segregation_of_duties_blocks_packet_initiator_and_governing_screener
    """
    source = fixtures.create_acquisition_funding_source(api, name="Four Eyes Line")
    parcel = fixtures.create_property(
        api,
        address="3310 Ginkgo Row",
        situs_ward=6,
        lot_area_sqft=6000,
        assessed_value_cents=100000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=5,
    )
    packet = fixtures.open_packet(
        api, parcel["id"], source["id"], donor_name="Ginkgo Trust"
    )
    assert packet["initiated_by_user_id"] == INTAKE_OFFICER_1
    fixtures.board_approve_packet(api, packet["id"])

    refused = api.close_packet(
        packet["id"], {"deed_reference": "BK-5010-PG-01"}, INTAKE_1
    )

    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
    parked = fixtures.read_packet(api, packet["id"])
    assert parked["status"] == "BOARD_APPROVED"
    assert parked["closed_by_user_id"] is None
    assert fixtures.read_property(api, parcel["id"])["custody_status"] == "PROSPECT"

    closed = validate_success(
        api.close_packet(packet["id"], {"deed_reference": "BK-5010-PG-01"}, INTAKE_2),
        200,
    )

    assert closed["status"] == "CLOSED"
    assert closed["closed_by_user_id"] == INTAKE_OFFICER_2
    assert fixtures.read_property(api, parcel["id"])["custody_status"] == "ACQUIRED"


def test_the_officer_who_screened_a_buyer_cannot_recommend_it(api):
    """
    The disposition officer whose user id performed the governing screening may not sign the recommendation, but a second holder of the same role may.

    Recommending a disposition application requires the acting `X-User-ID` to differ from the `screened_by_user_id` of the governing eligibility screening — the screening on that application with the greatest `sequence_no` — so the officer who cleared a buyer cannot also carry that buyer to the board. Either violation is reported as `ERR_SEGREGATION_OF_DUTIES` (403).

    Design: Corner/rbac/segregation_of_duties_blocks_packet_initiator_and_governing_screener
    """
    bundle = fixtures.screened_application(api)
    application_id = bundle["application"]["id"]
    assert bundle["screening"]["outcome"] == "PASS"
    screener = bundle["screening"]["screened_by_user_id"]

    refused = api.recommend_application(
        application_id,
        {"recommendation_memo": "Self-signed recommendation"},
        DISP_1,
    )

    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
    parked = fixtures.read_application(api, application_id)
    assert parked["status"] == "SCREENED"
    assert parked["recommended_by_user_id"] is None
    assert parked["recommendation_memo"] is None

    recommended = validate_success(
        api.recommend_application(
            application_id,
            {"recommendation_memo": "Independent review of the screening"},
            DISP_2,
        ),
        200,
    )

    assert recommended["status"] == "RECOMMENDED"
    assert recommended["recommended_by_user_id"] == DISPOSITION_OFFICER_2
    assert recommended["recommended_by_user_id"] != screener
