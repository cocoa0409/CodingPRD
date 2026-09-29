"""Declared authority: header shape, role exclusivity, duty splits and identity."""

from test_helpers import (
    TEST_USERS,
    UNKNOWN_UUID,
    ApiErrorId,
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers import factories as fac
from test_helpers import fixtures as fx

CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_START_PINNED = "2026-08-01T00:00:00.000Z"
CHECK_IN_UTC = "2026-08-14T07:00:00Z"
EXECUTION_UTC = "2026-08-14T09:00:00Z"
INTAKE_UTC = "2026-08-20T12:00:00Z"
POS_DELIVERED_AT = "2026-08-10T10:00:00Z"

GALLERY = TEST_USERS["gallery_manager_headers"]
MARKETING = TEST_USERS["marketing_manager_headers"]
OFFICER_ALPHA = TEST_USERS["compliance_officer_headers"]
OFFICER_BRAVO = TEST_USERS["compliance_officer_bravo_headers"]
INTAKE = TEST_USERS["contract_administrator_headers"]
ADJUDICATOR = TEST_USERS["contract_admin_adjudicator_headers"]
DISBURSER = TEST_USERS["contract_admin_disburser_headers"]
UNDERWRITER = TEST_USERS["contract_admin_underwriter_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]
ANY_REP = TEST_USERS["sales_representative_headers"]

ROLE_HEADER_MISSING = {"X-User-ID": "mm-primary", "Content-Type": "application/json"}
ID_HEADER_MISSING = {
    "X-User-Role": "MarketingManager",
    "Content-Type": "application/json",
}
UNDECLARED_ROLE = build_user_headers("sd-primary", "SalesDirector")


def test_a_missing_or_unrecognised_header_pair_is_unauthenticated():
    """The same well-formed body fails three times on headers and then succeeds.

    The PRD states: "Every request must carry two headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, declaring the capacity they act in."

    The PRD states: "If either header is absent, or if `X-User-Role` is not one of the
    six roles below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    The PRD states: "Header presence and role recognition — `ERR_UNAUTHENTICATED`
    (401), on every endpoint."

    Design: Corner/rbac/request_missing_x_user_id_returns_unauthenticated
    """
    fx.pin_clock(CLOCK_START)
    payload = fac.create_prospect_payload(
        household_name="Alvarez Household",
        primary_age=45,
        household_income_cents=10_000_000,
        marital_status="MARRIED",
    )

    validate_error(
        api.create_prospect(payload, ROLE_HEADER_MISSING),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api.create_prospect(payload, UNDECLARED_ROLE),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api.create_prospect(payload, ID_HEADER_MISSING),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )

    accepted = validate_success(api.create_prospect(payload, MARKETING), 201)
    assert accepted["household_name"] == "Alvarez Household"
    assert fx.read_prospect(accepted["id"])["primary_age"] == 45


def test_no_role_can_reach_another_roles_exclusive_operation():
    """Nine crossings are refused at authorisation, ahead of any existence check.

    The PRD states: "If the headers are well formed but the named role is not
    authorised for the target operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    The PRD states: "Role authorisation for the target operation — `ERR_UNAUTHORIZED`
    (403), on every endpoint."

    The PRD states: "Existence of path-parameter resources, validated strictly left to
    right, yielding HTTP 404 with the code for the *first* identifier in the path that
    does not resolve: `ERR_CHANNEL_NOT_FOUND`, `ERR_GALLERY_NOT_FOUND`,
    `ERR_REPRESENTATIVE_NOT_FOUND`, `ERR_PROSPECT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
    `ERR_PRESENTATION_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
    `ERR_FINANCING_APPLICATION_NOT_FOUND`, `ERR_RESCISSION_REQUEST_NOT_FOUND`,
    `ERR_REFUND_DISBURSEMENT_NOT_FOUND`, `ERR_CLOSING_PACKAGE_NOT_FOUND` or
    `ERR_RETRAINING_ASSIGNMENT_NOT_FOUND`."

    The PRD states: "`PlatformAdmin` — operates the logical clock and the rescission
    sweep epoch, and holds no business write authority at all."

    The PRD states: "That read is available to a `MarketingManager`, a
    `GalleryManager`, a `ComplianceOfficer` and a `PlatformAdmin`."

    The PRD states: "The computed analysis read echoes `representative_id`,
    `window_start_utc`, `window_end_utc`, `executed_count`, `rescinded_count`,
    `cancellation_rate`, the `min_sample` of 2, and the `retraining_required` verdict,
    and it is available only to a `GalleryManager`, a `ComplianceOfficer` and a
    `PlatformAdmin`."

    The PRD states: "A `PlatformAdmin` moves the clock by supplying a `to_iso8601`
    instant."

    Design: Corner/rbac/roles_cannot_reach_other_roles_exclusive_operations
    """
    fx.pin_clock(CLOCK_START)

    crossings = [
        api.check_in_tour_booking(
            UNKNOWN_UUID, fac.check_in_payload(True), MARKETING
        ),
        api.create_tour_channel(fac.create_tour_channel_payload(), GALLERY),
        api.create_prospect(fac.create_prospect_payload(), ANY_REP),
        api.fund_purchase_agreement(
            UNKNOWN_UUID, fac.fund_payload(1, funding_reference="WIRE-1"), OFFICER_ALPHA
        ),
        api.review_sales_presentation(UNKNOWN_UUID, fac.review_payload("CLEAR"), INTAKE),
        api.create_tour_channel(fac.create_tour_channel_payload(), PLATFORM),
        api.get_rescission_analysis(UNKNOWN_UUID, MARKETING),
        api.get_channel_no_show_summary(UNKNOWN_UUID, ANY_REP),
        api.set_clock(fac.set_clock_payload("2026-08-02T00:00:00Z"), INTAKE),
    ]
    for response in crossings:
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    unmoved = fx.create_prospect()
    assert unmoved["created_at"] == CLOCK_START_PINNED


def test_every_declared_role_performs_its_own_exclusive_operations():
    """One chain runs the clock, the gallery, the tour, the sale and the underwriting.

    The PRD states: "The six roles are non-overlapping duty holders:"

    The PRD states: "`GalleryManager` — owns gallery capacity, the representative
    roster and rotation, and performs tour check-in."

    The PRD states: "`MarketingManager` — owns tour generation: channels,
    incentive-gift configuration, prospect intake, and the tour schedule."

    The PRD states: "`SalesRepresentative` — conducts the presentation, records
    disclosure acknowledgments, executes purchase agreements, and submits financing
    applications, but only for their own tours."

    The PRD states: "`ComplianceOfficer` — files prohibited-claim findings, issues
    review decisions, and administers compliance retraining."

    The PRD states: "`ContractAdministrator` — underwrites financing, funds contracts,
    records and delivers closing documents, and administers rescission intake,
    adjudication and refunds."

    The PRD states: "`PlatformAdmin` — operates the logical clock and the rescission
    sweep epoch, and holds no business write authority at all."

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
    """
    fx.pin_clock(CLOCK_START)
    gallery = validate_success(
        api.create_sales_gallery(fac.create_sales_gallery_payload(), GALLERY), 201
    )
    representative = validate_success(
        api.create_sales_representative(
            fac.create_sales_representative_payload(gallery["id"]), GALLERY
        ),
        201,
    )
    channel = validate_success(
        api.create_tour_channel(fac.create_tour_channel_payload(), MARKETING), 201
    )
    prospect = validate_success(
        api.create_prospect(fac.create_prospect_payload(), MARKETING), 201
    )
    booking = validate_success(
        api.create_tour_booking(
            fac.create_tour_booking_payload(
                channel["id"],
                prospect["id"],
                gallery["id"],
                scheduled_start_utc=CHECK_IN_UTC,
            ),
            MARKETING,
        ),
        201,
    )

    fx.pin_clock(CHECK_IN_UTC)
    checked_in = validate_success(
        api.check_in_tour_booking(booking["id"], fac.check_in_payload(True), GALLERY)
    )
    assert checked_in["assigned_rep_id"] == representative["id"]

    rep_headers = fx.make_sales_representative_headers(representative["id"])
    presentation = validate_success(
        api.create_sales_presentation(
            fac.create_sales_presentation_payload(booking["id"]), rep_headers
        ),
        201,
    )
    for code, offset in (
        ("RESCISSION_RIGHTS", 120),
        ("PUBLIC_OFFERING_STATEMENT_DELIVERY", 240),
        ("NOT_AN_INVESTMENT", 360),
    ):
        validate_success(
            api.create_disclosure_acknowledgment(
                fac.create_disclosure_acknowledgment_payload(
                    presentation["id"],
                    code,
                    recording_timestamp_offset_seconds=offset,
                ),
                rep_headers,
            ),
            201,
        )

    reviewed = validate_success(
        api.review_sales_presentation(
            presentation["id"], fac.review_payload("CLEAR"), OFFICER_ALPHA
        )
    )
    assert reviewed["review_status"] == "CLEARED"
    assert reviewed["disclosure_status"] == "COMPLETE"
    assert reviewed["compliance_score"] == 100

    validate_success(
        api.complete_sales_presentation(presentation["id"], rep_headers)
    )
    assert fx.read_booking(booking["id"])["status"] == "TOURED"

    fx.pin_clock(EXECUTION_UTC)
    agreement = validate_success(
        api.create_purchase_agreement(
            fac.create_purchase_agreement_payload(
                presentation["id"],
                state_code="FL",
                purchase_price_cents=3_200_000,
                down_payment_cents=320_000,
                pos_delivered_at=POS_DELIVERED_AT,
            ),
            rep_headers,
        ),
        201,
    )
    assert agreement["financed_amount_cents"] == 3_019_980
    assert agreement["rescission_status"] == "OPEN"

    application = validate_success(
        api.create_financing_application(
            fac.create_financing_application_payload(
                agreement["id"], fx.read_agreement(agreement["id"])["version"]
            ),
            rep_headers,
        ),
        201,
    )
    decided = validate_success(
        api.decide_financing_application(
            application["id"], fac.financing_decision_payload("APPROVE"), UNDERWRITER
        )
    )
    assert decided["status"] == "APPROVED"
    assert decided["approved_amount_cents"] == 3_019_980


def test_the_same_operator_may_not_review_its_own_finding_or_pay_its_own_award():
    """Bravo is refused the review and the adjudicator is refused the disbursement.

    The PRD states: "Two same-person prohibitions are enforced on `X-User-ID`, and
    both return `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    The PRD states: "A `ComplianceOfficer` who filed any prohibited-claim finding
    against a presentation may not then issue a review decision on that presentation —
    the comparison is between the acting `X-User-ID` and the `reported_by_user_id` of
    every finding on that presentation, and the prohibition applies to both a clearing
    and a flagging decision."

    The PRD states: "Separately, the `ContractAdministrator` who adjudicated a
    rescission request may not issue the refund disbursement for it — the comparison is
    between the acting `X-User-ID` and the request's `adjudicated_by_user_id`."

    The PRD states: "The append records `reported_by_user_id` as the acting
    `X-User-ID` and stamps `detected_at`, recomputes the presentation's
    `prohibited_claim_points` and `compliance_score`, and increments the
    presentation's `version` by one."

    The PRD states: "The `prohibited_claim_points` total is itself the sum of
    `penalty_points` over every prohibited-claim finding on the presentation, where
    `penalty_points` is derived from the finding's `severity`: a `MINOR` finding costs
    5 points, a `MAJOR` finding costs 15, and an `EGREGIOUS` finding costs 40."

    The PRD states: "Creation copies `refund_policy_applied` from the agreement's
    `refund_policy`, sets `base_refund_cents` to the agreement's
    `escrow_collected_cents` — immutable since execution, so the snapshot cannot drift
    — opens in `status` `PENDING`, and stamps `issued_by_user_id` with the acting
    `X-User-ID`, leaving `settlement_reference` and `settled_at` null."

    Design: Corner/rbac/segregation_of_duties_bars_self_review_and_self_disbursement
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_open_presentation(
        rep_count=1,
        issue_incentive_gift=False,
        check_in_at=CHECK_IN_UTC,
        booking_overrides={"scheduled_start_utc": CHECK_IN_UTC},
    )
    presentation_id = scene["presentation"]["id"]
    rep_id = scene["assigned_rep_id"]
    fx.acknowledge_required_disclosures(presentation_id, rep_id)

    finding = fx.file_claim_finding(
        presentation_id,
        "MINOR",
        fx.read_presentation(presentation_id)["version"],
        headers=OFFICER_BRAVO,
    )
    assert finding["reported_by_user_id"] == "officer-bravo"
    assert finding["penalty_points"] == 5
    assert fx.read_presentation(presentation_id)["compliance_score"] == 95

    self_review = api.review_sales_presentation(
        presentation_id, fac.review_payload("CLEAR"), OFFICER_BRAVO
    )
    validate_error(self_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert fx.read_presentation(presentation_id)["review_status"] == "UNREVIEWED"

    cleared = fx.review_presentation(presentation_id, "CLEAR", OFFICER_ALPHA)
    assert cleared["review_status"] == "CLEARED"
    assert cleared["reviewed_by_user_id"] == "officer-alpha"

    fx.complete_presentation(presentation_id, rep_id)
    fx.pin_clock(EXECUTION_UTC)
    agreement = fx.execute_agreement(
        presentation_id,
        rep_id,
        state_code="FL",
        purchase_price_cents=3_200_000,
        down_payment_cents=320_000,
        pos_delivered_at=POS_DELIVERED_AT,
    )

    fx.pin_clock(INTAKE_UTC)
    request = fx.intake_rescission(agreement["id"], "HAND_DELIVERED", headers=INTAKE)
    assert request["intake_user_id"] == "admin-intake"
    adjudicated = fx.adjudicate_rescission(request["id"], headers=ADJUDICATOR)
    assert adjudicated["adjudicated_by_user_id"] == "admin-adjudicator"

    self_payment = api.create_refund_disbursement(
        fac.create_refund_disbursement_payload(request["id"], "ACH"), ADJUDICATOR
    )
    validate_error(self_payment, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    empty_rows, empty_meta = validate_paginated(
        api.list_refund_disbursements(
            DISBURSER, params={"rescission_request_id": request["id"]}
        )
    )
    assert empty_meta["total_count"] == 0
    assert empty_rows == []

    disbursement = validate_success(
        api.create_refund_disbursement(
            fac.create_refund_disbursement_payload(request["id"], "ACH"), DISBURSER
        ),
        201,
    )
    assert disbursement["issued_by_user_id"] == "admin-disburser"
    assert disbursement["status"] == "PENDING"


def test_one_representative_cannot_work_another_representatives_tour():
    """The unbound representative is refused the presentation and the acknowledgment.

    The PRD states: "When `X-User-Role` is `SalesRepresentative`, `X-User-ID` is the
    `id` of the acting `SalesRepresentative` record; ownership checks on any resource
    that references a representative compare the resource's representative reference
    to `X-User-ID` — specifically a booking's `assigned_rep_id`, a presentation's
    `rep_id`, and an agreement's `rep_id`."

    The PRD states: "A mismatch is rejected with `ERR_REPRESENTATIVE_MISMATCH` (HTTP
    403)."

    The PRD states: "Representative ownership for the entity-backed role —
    `ERR_REPRESENTATIVE_MISMATCH` (403). This guards exactly five operations: `POST
    /sales-presentations`, `POST /disclosure-acknowledgments`, `POST
    /sales-presentations/{id}/complete`, `POST /purchase-agreements` and `POST
    /financing-applications`."

    The PRD states: "The acting `X-User-ID` must be the booking's `assigned_rep_id`,
    and the booking must be `CHECKED_IN`."

    Design: Corner/rbac/representative_identity_bars_another_representatives_tour
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_checked_in_tour(
        rep_count=2,
        issue_incentive_gift=False,
        check_in_at=CHECK_IN_UTC,
        booking_overrides={"scheduled_start_utc": CHECK_IN_UTC},
    )
    booking_id = scene["booking"]["id"]
    assigned_rep_id = scene["assigned_rep_id"]
    outsider = next(
        rep for rep in scene["reps"] if rep["id"] != assigned_rep_id
    )
    outsider_headers = fx.make_sales_representative_headers(outsider["id"])

    stolen_tour = api.create_sales_presentation(
        fac.create_sales_presentation_payload(
            booking_id, recorded_ack_reference="REC-BOGUS"
        ),
        outsider_headers,
    )
    validate_error(stolen_tour, ApiErrorId.ERR_REPRESENTATIVE_MISMATCH.value, 403)

    presentation = fx.open_presentation(booking_id, assigned_rep_id)
    assert presentation["rep_id"] == assigned_rep_id
    assert presentation["recorded_ack_reference"] == "REC-0001"

    stolen_ack = api.create_disclosure_acknowledgment(
        fac.create_disclosure_acknowledgment_payload(
            presentation["id"], "RESCISSION_RIGHTS"
        ),
        outsider_headers,
    )
    validate_error(stolen_ack, ApiErrorId.ERR_REPRESENTATIVE_MISMATCH.value, 403)
    assert fx.read_presentation(presentation["id"])["disclosure_ack_count"] == 0

    acknowledgment = fx.acknowledge_disclosure(
        presentation["id"], assigned_rep_id, "RESCISSION_RIGHTS"
    )
    assert acknowledgment["presentation_id"] == presentation["id"]

    rows, meta = validate_paginated(
        api.list_sales_presentations(GALLERY, params={"booking_id": booking_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == presentation["id"]

    untouched = fx.read_representative(outsider["id"])
    assert untouched["status"] == "ACTIVE"
    assert untouched["tours_taken_count"] == 0
