"""Rejections the program owes a named error, and endpoint effects it owes in prose.

The first half drives one request into each of five refusals: an outsider filing
against someone else's parcel, an approving reviewer trying to certify their own
decision, a duplicated assessor parcel number, a designation code reused across
the two area namespaces, and a request that breaks two rules at once so the
evaluation order decides which error the caller sees.

The second half exercises four endpoints for their effects rather than their
shape: the manual close of a sending area and its partial suspension cascade,
the chain-of-title read model after an issuance and a settled sale, the
compliance sweep run over a program with nothing due, and the release of the
only redemption backing a receiving-site application.

Every test builds its whole registry state from scratch through the API.
"""
import pytest

from test_helpers import (
    ADMIN_USER_ID,
    ApiErrorId,
    MONITOR_USER_ID,
    REVIEWER_USER_ID,
    TEST_USERS,
    api_client,
    assert_certificate,
    assert_certificate_redemption,
    assert_certificate_transfer,
    assert_conservation_easement,
    assert_monitoring_inspection,
    assert_receiving_area,
    assert_receiving_site_application,
    assert_same_date,
    assert_same_instant,
    assert_sending_area,
    assert_sending_parcel,
    assert_severance_application,
    create_active_sending_area,
    create_receiving_area_payload,
    create_sending_area_payload,
    create_severance_application_payload,
    create_sending_parcel_payload,
    credit_party,
    decide_application,
    designate_sending_area,
    enroll_parcel,
    fetch_application,
    fetch_certificate,
    fetch_easement,
    fetch_inspection,
    fetch_parcel,
    fetch_party,
    fetch_receiving_area,
    fetch_receiving_site_application,
    fetch_sending_area,
    fetch_transaction,
    file_severance,
    make_admin_headers,
    make_developer_headers,
    make_landowner_headers,
    propose_transaction,
    publish_appraisal_schedule,
    record_inspection,
    register_bank,
    register_developer,
    register_landowner,
    screen_application,
    set_clock,
    setup_backed_receiving_application,
    setup_certified_severance,
    setup_developer_holding_certificate,
    split_certificate_payload,
    suspend_party,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["admin_headers"]

CLOCK = "2026-08-10T00:00:00Z"

CANONICAL_GEOMETRY = {
    "gross_acres": 100.00,
    "constrained_acres": 22.00,
    "soil_class": "PRIME",
    "existing_dwelling_units": 2,
}

EAST_AREA = {
    "name": "East Ridge",
    "neighborhood_code": "NB-EAST",
    "allocation_formula_version": "V1_NET_ACRE",
    "base_rate_units_per_acre": 0.25,
    "gross_discount_factor": 0.80,
    "equity_tier": "UNDERSERVED",
    "sending_cap_units": 200,
}


def test_a_landowner_cannot_file_a_severance_for_someone_elses_parcel():
    """An outsider landowner files against a parcel owned by another landowner.

    The parcel and the applicant both exist and both are `LANDOWNER` parties, so
    nothing but the ownership comparison can refuse the request; the acting
    identity does not match the parcel's owner and the filing is a 403.  The same
    payload filed by the owner is accepted, which isolates the refusal to the
    acting identity.

    PRD 2.1: "When `X-User-Role` is `Landowner`, `X-User-ID` is the `id` of the
    acting `Party`, and ownership checks on any resource that references a `Party`
    compare the resource's party foreign key to `X-User-ID`."

    PRD 2.1: "A failed ownership comparison is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    PRD 2.10: "**Ownership** — for an entity-backed role, `X-User-ID` matches the
    resource's owning party as §2.1 describes; otherwise `ERR_NOT_RESOURCE_OWNER`
    (403). Applies to severance filing, severance resubmission, receiving-site
    filing, design resubmission, finalization, redemption allocation, redemption
    release, certificate split, certificate retirement, and transaction
    cancellation."

    PRD 3.4: "The `applicant_party_id` must be the same party as the parcel's
    `owner_party_id` and must be of kind `LANDOWNER`; the acting `X-User-ID` must
    equal that party, or the filing is rejected with `ERR_NOT_RESOURCE_OWNER`."

    PRD 3.4: "An accepted filing opens in `status` `SUBMITTED` with
    `revision_round` at 0 and both `allocated_units` and `residual_units_retained`
    at 0."

    PRD 3.4: "Applications can be listed with `sending_parcel_id`,
    `applicant_party_id`, and `status` filters plus `limit` and `offset`."

    Design: Corner/validations/a_landowner_cannot_file_a_severance_for_someone_elses_parcel
    """
    owner = register_landowner(legal_name="Ridge Farm LLC", neighborhood_code="NB-EAST")
    outsider = register_landowner(legal_name="Hollow Creek LLC", neighborhood_code="NB-EAST")
    area = create_active_sending_area(code="SA-EAST", **EAST_AREA)
    parcel = enroll_parcel(owner["id"], area["id"], apn="APN-001", **CANONICAL_GEOMETRY)

    payload = create_severance_application_payload(parcel["id"], owner["id"], 22)
    refused = api_client.create_severance_application(
        payload, make_landowner_headers(outsider["id"])
    )
    validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    rows, meta = validate_paginated(
        api_client.list_severance_applications(
            ADMIN_HEADERS, params={"sending_parcel_id": parcel["id"], "limit": 50, "offset": 0}
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused filing must not have been recorded, got {meta['total_count']} application(s)"
    )
    assert rows == [], f"expected no application rows, got {rows}"

    accepted = validate_success(
        api_client.create_severance_application(payload, make_landowner_headers(owner["id"])),
        201,
    )
    assert_severance_application(accepted)
    assert accepted["status"] == "SUBMITTED", (
        f"the owner's own filing must open in SUBMITTED, got {accepted['status']}"
    )
    assert accepted["applicant_party_id"] == owner["id"], accepted["applicant_party_id"]
    assert accepted["revision_round"] == 0, accepted["revision_round"]
    assert accepted["allocated_units"] == 0, accepted["allocated_units"]
    assert accepted["residual_units_retained"] == 0, accepted["residual_units_retained"]


def test_the_operator_who_approved_a_severance_cannot_also_certify_it():
    """The reviewer who recorded the approval presents an administrator role to certify.

    Segregation of duties compares the acting `X-User-ID` against the stored
    `decided_by_user_id`, so a change of role does not launder the identity: the
    certification is refused, no easement is recorded and no certificate is minted.
    A different operator then certifies the very same application successfully.

    PRD 2.1: "Segregation of duties, rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403), requires that the `X-User-ID` certifying a severance application
    differ from the `decided_by_user_id` that recorded its approval, and that the
    `X-User-ID` verifying a cure differ from the `inspector_user_id` that recorded
    the inspection."

    PRD 2.10: "**Segregation of duties** — as described in §2.1; otherwise
    `ERR_SEGREGATION_OF_DUTIES` (403). Applies to severance certification and cure
    verification."

    PRD 3.5: "The application must be in `APPROVED`, otherwise
    `ERR_APPLICATION_NOT_APPROVED`. The acting `X-User-ID` must differ from the
    application's `decided_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` — the
    operator who certifies may never be the reviewer who approved."

    PRD 3.5: "Only a `ProgramAdministrator` may certify, they may attach an optional
    `recording_note`, and the response is the newly issued certificate rather than
    the application."

    PRD 3.4: "All three branches require the application to be `UNDER_REVIEW`,
    otherwise `ERR_APPLICATION_NOT_IN_REVIEW`, and all three write the acting
    `X-User-ID` into `decided_by_user_id` and increment the application's
    `version`."

    PRD 3.5: "The sending area's `severed_units_total` is recomputed as the sum of
    `allocated_units` over every `CERTIFIED` application on parcels in the area,
    and its `issued_certificate_count` is incremented by one."

    Design: Corner/validations/the_operator_who_approved_a_severance_cannot_also_certify_it
    """
    set_clock(CLOCK)
    owner = register_landowner(legal_name="Ridge Farm LLC", neighborhood_code="NB-EAST")
    area = create_active_sending_area(code="SA-EAST", **EAST_AREA)
    parcel = enroll_parcel(owner["id"], area["id"], apn="APN-001", **CANONICAL_GEOMETRY)
    application = file_severance(parcel["id"], owner["id"], 22)
    screen_application(application["id"], REVIEWER_USER_ID)
    approved = decide_application(application["id"], "APPROVE", REVIEWER_USER_ID)
    assert approved["decided_by_user_id"] == REVIEWER_USER_ID, (
        f"the approving user must be recorded, got {approved['decided_by_user_id']}"
    )

    refused = api_client.certify_severance_application(
        application["id"], make_admin_headers(REVIEWER_USER_ID), {}
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    unchanged = fetch_application(application["id"])
    assert_severance_application(unchanged)
    assert unchanged["status"] == "APPROVED", (
        f"the refused certification must leave the application APPROVED, got {unchanged['status']}"
    )
    assert unchanged["allocated_units"] == 22, unchanged["allocated_units"]
    assert unchanged["certified_by_user_id"] is None, (
        f"no certifying user may be recorded, got {unchanged['certified_by_user_id']}"
    )

    _, easement_meta = validate_paginated(
        api_client.list_conservation_easements(
            ADMIN_HEADERS, params={"sending_parcel_id": parcel["id"], "limit": 50, "offset": 0}
        )
    )
    assert easement_meta["total_count"] == 0, (
        "no conservation easement may be recorded by a refused certification, got "
        f"{easement_meta['total_count']}"
    )
    _, certificate_meta = validate_paginated(
        api_client.list_certificates(
            ADMIN_HEADERS, params={"origin_sending_area_id": area["id"], "limit": 50, "offset": 0}
        )
    )
    assert certificate_meta["total_count"] == 0, (
        f"no certificate may be minted, got {certificate_meta['total_count']}"
    )
    area_between = fetch_sending_area(area["id"])
    assert_sending_area(area_between)
    assert area_between["issued_certificate_count"] == 0, (
        f"got {area_between['issued_certificate_count']}"
    )
    assert area_between["severed_units_total"] == 0, area_between["severed_units_total"]

    certificate = validate_success(
        api_client.certify_severance_application(
            application["id"], make_admin_headers(ADMIN_USER_ID), {}
        ),
        201,
    )
    assert_certificate(certificate)
    assert certificate["units_face"] == 22, (
        f"a different operator certifies the same grant of 22 units, got {certificate['units_face']}"
    )
    certified = fetch_application(application["id"])
    assert certified["status"] == "CERTIFIED", certified["status"]
    assert certified["certified_by_user_id"] == ADMIN_USER_ID, (
        f"got {certified['certified_by_user_id']}"
    )
    assert fetch_sending_area(area["id"])["issued_certificate_count"] == 1, (
        "the successful certification increments the area's issued_certificate_count"
    )


def test_duplicate_parcel_apn_is_rejected_across_sending_areas():
    """The same assessor parcel number re-enrolled under a second active area.

    Uniqueness is program-wide rather than per area, so moving the second
    enrollment to a different active area does not rescue it.  A different APN
    under that same second area is accepted, which proves the refusal was about
    the number and not about the area.

    PRD 3.3: "An administrator enrolls one by supplying `owner_party_id`,
    `sending_area_id`, the `apn` assessor parcel number (4 to 24 characters, unique
    across all parcels, with a collision rejected as `ERR_DUPLICATE_PARCEL_APN`)"

    PRD 2.10: "`apn` is unique across all sending parcels; otherwise
    `ERR_DUPLICATE_PARCEL_APN` (409)."

    PRD 3.3: "Under `V1_NET_ACRE`, eligible acreage is `gross_acres` minus
    `constrained_acres`, and `gross_discount_factor` is ignored entirely. Under
    `V2_GROSS_DISCOUNTED`, eligible acreage is `gross_acres` multiplied by the
    area's `gross_discount_factor`, and `constrained_acres` is ignored entirely."

    PRD 3.3: "Third, a raw figure is formed as the eligible acreage multiplied by
    the area's `base_rate_units_per_acre` multiplied by the soil multiplier.
    Fourth, that raw figure is floored to a whole number — truncated downward,
    never rounded — the parcel's `existing_dwelling_units` are subtracted from the
    floored value because each already-built dwelling consumes one allocated right,
    and the result is taken as zero if the subtraction would go negative."

    PRD 3.3: "Parcels can be listed with `owner_party_id`, `sending_area_id`,
    `parcel_status`, and `easement_status` filters plus `limit` and `offset`, and
    read individually to see the baseline, severed and remaining counts together."

    Design: Corner/validations/duplicate_parcel_apn_is_rejected_across_sending_areas
    """
    owner = register_landowner(legal_name="Ridge Farm LLC", neighborhood_code="NB-EAST")
    east = create_active_sending_area(code="SA-EAST", **EAST_AREA)
    west = create_active_sending_area(
        code="SA-WEST",
        name="West Bench",
        neighborhood_code="NB-WEST",
        allocation_formula_version="V2_GROSS_DISCOUNTED",
        base_rate_units_per_acre=0.25,
        gross_discount_factor=0.80,
        equity_tier="HIGH_VALUE",
        sending_cap_units=200,
    )
    parcel = enroll_parcel(owner["id"], east["id"], apn="APN-001", **CANONICAL_GEOMETRY)
    assert parcel["baseline_allocation_units"] == 22, (
        "the V1 area nets 100.00 less 22.00 acres, so 78.00 x 0.25 x 1.25 floors to 24 less 2 "
        f"dwellings = 22; got {parcel['baseline_allocation_units']}"
    )

    collision = api_client.create_sending_parcel(
        create_sending_parcel_payload(
            owner["id"], west["id"], apn="APN-001", **CANONICAL_GEOMETRY
        ),
        ADMIN_HEADERS,
    )
    validate_error(collision, ApiErrorId.ERR_DUPLICATE_PARCEL_APN.value, 409)

    _, west_meta = validate_paginated(
        api_client.list_sending_parcels(
            ADMIN_HEADERS, params={"sending_area_id": west["id"], "limit": 50, "offset": 0}
        )
    )
    assert west_meta["total_count"] == 0, (
        f"the refused enrollment must leave the second area empty, got {west_meta['total_count']}"
    )
    original = fetch_parcel(parcel["id"])
    assert_sending_parcel(original)
    assert original["sending_area_id"] == east["id"], (
        "the existing parcel must stay in its original area, got "
        f"{original['sending_area_id']}"
    )
    assert original["baseline_allocation_units"] == 22, (
        f"the existing baseline must be untouched, got {original['baseline_allocation_units']}"
    )

    accepted = validate_success(
        api_client.create_sending_parcel(
            create_sending_parcel_payload(
                owner["id"], west["id"], apn="APN-002", **CANONICAL_GEOMETRY
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert_sending_parcel(accepted)
    assert accepted["sending_area_id"] == west["id"], accepted["sending_area_id"]
    assert accepted["baseline_allocation_units"] == 23, (
        "the V2 area discounts gross acreage instead: 100.00 x 0.80 = 80.00 eligible acres, "
        "x 0.25 x 1.25 = 25.0 floored to 25, less 2 dwellings = 23; got "
        f"{accepted['baseline_allocation_units']}"
    )


def test_area_codes_are_unique_across_sending_and_receiving_designations():
    """A receiving area claims a code already taken by a draft sending area.

    The uniqueness domain spans both designation namespaces, so the collision is
    refused from either side while the sending area is still `DRAFT` — activation
    has nothing to do with it.  A free code is then accepted and opens with its
    empty eligibility whitelist.

    PRD 3.2: "The `code` is 3 to 16 characters and must be unique across sending
    areas and receiving areas *together* — the two designation namespaces are
    shared, and a collision on either side is rejected with
    `ERR_DUPLICATE_AREA_CODE`."

    PRD 2.10: "The area `code` is unique across sending and receiving areas
    combined; otherwise `ERR_DUPLICATE_AREA_CODE` (409). Applies to both
    designation endpoints."

    PRD 3.2: "An administrator designates one by supplying its `code`, `name`, and
    `neighborhood_code` under the same length and uniqueness rules as a sending
    area, plus the `base_density_units_per_acre` that expresses the as-of-right
    yield (greater than zero, no more than 40, two decimal places), the
    `max_bonus_pct` ceiling on bonus as a fraction of that as-of-right yield
    (greater than zero, no more than 1, two decimal places), the
    `absorption_cap_units` total the area may absorb across all its sites (greater
    than zero), the `design_review_required` flag (defaulting to true), and an
    optional `eligible_sending_area_codes` whitelist."

    PRD 3.2: "That whitelist defaults to the empty list, and an empty list means
    every sending area is eligible; a non-empty list means only certificates whose
    origin sending area `code` appears in it may be redeemed here, with anything
    else rejected as `ERR_SENDING_RECEIVING_PAIR_NOT_ELIGIBLE`. A new receiving
    area opens in `status` `DRAFT` with `absorbed_units` and `reserved_units` at 0"

    Design: Corner/validations/area_codes_are_unique_across_sending_and_receiving_designations
    """
    sending = designate_sending_area(code="ZONE-1", **EAST_AREA)
    assert_sending_area(sending)
    assert sending["status"] == "DRAFT", (
        f"the sending area is left unactivated on purpose, got {sending['status']}"
    )

    receiving_payload = create_receiving_area_payload(
        code="ZONE-1",
        name="Core District",
        neighborhood_code="NB-CORE",
        base_density_units_per_acre=4.00,
        max_bonus_pct=0.35,
        absorption_cap_units=500,
        design_review_required=True,
    )
    receiving_payload.pop("eligible_sending_area_codes")
    receiving_collision = api_client.create_receiving_area(receiving_payload, ADMIN_HEADERS)
    validate_error(receiving_collision, ApiErrorId.ERR_DUPLICATE_AREA_CODE.value, 409)

    sending_collision = api_client.create_sending_area(
        create_sending_area_payload(code="ZONE-1", **dict(EAST_AREA, name="East Ridge Duplicate")),
        ADMIN_HEADERS,
    )
    validate_error(sending_collision, ApiErrorId.ERR_DUPLICATE_AREA_CODE.value, 409)

    free_payload = dict(receiving_payload, code="ZONE-2")
    accepted = validate_success(
        api_client.create_receiving_area(free_payload, ADMIN_HEADERS), 201
    )
    assert_receiving_area(accepted)
    assert accepted["code"] == "ZONE-2", accepted["code"]
    assert accepted["status"] == "DRAFT", (
        f"a new receiving area opens in DRAFT, got {accepted['status']}"
    )
    assert accepted["absorbed_units"] == 0, accepted["absorbed_units"]
    assert accepted["reserved_units"] == 0, accepted["reserved_units"]
    assert accepted["eligible_sending_area_codes"] == [], (
        "an omitted whitelist defaults to the empty list, got "
        f"{accepted['eligible_sending_area_codes']}"
    )

    _, sending_meta = validate_paginated(
        api_client.list_sending_areas(ADMIN_HEADERS, params={"limit": 50, "offset": 0})
    )
    assert sending_meta["total_count"] == 1, (
        f"only the first ZONE-1 sending area may exist, got {sending_meta['total_count']}"
    )
    _, receiving_meta = validate_paginated(
        api_client.list_receiving_areas(ADMIN_HEADERS, params={"limit": 50, "offset": 0})
    )
    assert receiving_meta["total_count"] == 1, (
        f"only the ZONE-2 receiving area may exist, got {receiving_meta['total_count']}"
    )


def test_suspended_party_safety_check_outranks_the_certificate_state_check():
    """A split that breaks the suspension rule and the tradability rule at once.

    The holder has been suspended and the certificate is already `UNDER_CONTRACT`
    with all 22 units encumbered, so the same request violates the party-safety
    rung and the certificate-state rung together.  The ladder is evaluated from the
    top, so the suspension error is the one the caller sees and nothing about the
    certificate or the open deal moves.

    PRD 2.10: "When several rules could reject the same request, the outcome is not
    left to implementation order. The checks below form one global ladder, evaluated
    strictly from the top; the first check that fails decides the response, and no
    later check is consulted. Authentication precedes authorization, existence
    precedes ownership, safety precedes constraint, and fiscal checks always come
    last."

    PRD 2.10: "**Party suspension** — no party involved in the request, whether the
    actor's own party, the seller, the buyer, the parcel owner or the developer, is
    `SUSPENDED`; otherwise `ERR_PARTY_SUSPENDED` (409). Applies to severance
    filing, transaction proposal, settlement, receiving-site filing, redemption
    allocation, and certificate split."

    PRD 2.10: "The certificate's `lifecycle_status` is `ISSUED` or
    `PARTIALLY_REDEEMED` and its `market_status` is not `UNDER_CONTRACT`; otherwise
    `ERR_CERTIFICATE_NOT_TRANSFERABLE` (409). Applies to transaction proposal,
    certificate split, certificate retirement, and redemption allocation."

    PRD 3.6: "Splitting requires the parent's `lifecycle_status` to be `ISSUED` or
    `PARTIALLY_REDEEMED` and its `market_status` to be `HELD`; a certificate that is
    `UNDER_CONTRACT`, `REDEEMED` or `RETIRED` is rejected with
    `ERR_CERTIFICATE_NOT_TRANSFERABLE`, while one that is `FROZEN` is rejected with
    `ERR_CERTIFICATE_FROZEN` because its source easement is out of compliance. No
    party involved may be `SUSPENDED`."

    PRD 3.7: "An accepted proposal opens in `status` `PROPOSED`, moves the
    certificate `HELD → UNDER_CONTRACT`, grows the certificate's `units_encumbered`
    by the traded `units`, and increments the certificate's `version`."

    PRD 3.6: "The registry can be listed with `holder_party_id`,
    `conservation_easement_id`, `parent_certificate_id`, `origin_sending_area_id`,
    `lifecycle_status`, and `market_status` filters plus `limit` and `offset`, which
    is how a lineage is walked: filtering on `parent_certificate_id` yields one
    generation of children, and filtering on `conservation_easement_id` yields the
    whole family descended from one severance."

    Design: Corner/validations/suspended_party_safety_check_outranks_the_certificate_state_check
    """
    scenario = setup_certified_severance(
        units=22, clock=CLOCK, equity_tier="UNDERSERVED", neighborhood_code="NB-EAST",
    )
    landowner = scenario["landowner"]
    certificate = scenario["certificate"]
    developer = register_developer(legal_name="Core Block Partners", neighborhood_code="NB-CORE")
    register_bank(neighborhood_code="NB-CORE")
    publish_appraisal_schedule(
        neighborhood_code="NB-EAST",
        per_unit_value_cents=1_234_567,
        equity_adjustment_bps=250,
        effective_from="2026-01-01",
        effective_to="2027-01-01",
    )
    credit_party(developer["id"], 30_000_000)
    transaction = propose_transaction(
        certificate["id"], landowner["id"], developer["id"], units=22,
        channel="PRIVATE", agreed_price_cents=30_000_000,
    )
    under_contract = fetch_certificate(certificate["id"])
    assert under_contract["market_status"] == "UNDER_CONTRACT", (
        f"the open proposal must encumber the certificate, got {under_contract['market_status']}"
    )
    assert under_contract["units_encumbered"] == 22, under_contract["units_encumbered"]

    suspend_party(landowner["id"])
    assert fetch_party(landowner["id"])["status"] == "SUSPENDED", (
        "the holder must be SUSPENDED before the split is attempted"
    )

    refused = api_client.split_certificate(
        certificate["id"],
        split_certificate_payload(5, under_contract["version"]),
        make_landowner_headers(landowner["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_PARTY_SUSPENDED.value, 409)

    after = fetch_certificate(certificate["id"])
    assert_certificate(after)
    assert after["market_status"] == "UNDER_CONTRACT", (
        f"the refused split must leave the market dimension alone, got {after['market_status']}"
    )
    assert after["units_encumbered"] == 22, after["units_encumbered"]
    assert after["split_count"] == 0, (
        f"no child may be minted, so split_count stays 0, got {after['split_count']}"
    )
    assert after["units_split_out"] == 0, after["units_split_out"]

    _, children_meta = validate_paginated(
        api_client.list_certificates(
            ADMIN_HEADERS,
            params={"parent_certificate_id": certificate["id"], "limit": 50, "offset": 0},
        )
    )
    assert children_meta["total_count"] == 0, (
        f"the lineage must have no children, got {children_meta['total_count']}"
    )
    assert fetch_transaction(transaction["id"])["status"] == "PROPOSED", (
        "the open deal is untouched by the refused split"
    )


def test_closing_a_sending_area_suspends_open_applications_and_freezes_approved_ones():
    """A manual close over one open application and one already-approved application.

    The cascade is deliberately partial: the `SUBMITTED` filing is suspended with a
    stamped reason, while the `APPROVED` filing keeps its grant and simply becomes
    uncertifiable through the area-status gate.  Nothing new may be filed against
    the area afterwards, and the close itself severs no rights.

    PRD 3.2: "Closing a sending area moves it `ACTIVE → CLOSED`, accepts an
    optional `reason`, increments the area's `version`, and runs a suspension
    cascade over the applications filed against its parcels: every
    `SeveranceApplication` whose `status` is `SUBMITTED`, `UNDER_REVIEW`, or
    `REVISION_REQUESTED` moves to `SUSPENDED` with `denial_reason` set to
    `SENDING_AREA_CLOSED`, and each suspended application's `version` is
    incremented by one as well. An application already in `APPROVED` is
    deliberately left in `APPROVED`: it is not suspended, it simply becomes
    uncertifiable, because certification requires the area to be `ACTIVE`. `CLOSED`
    is terminal — a closed sending area is never reopened."

    PRD 2.10: "The `SendingArea` named by the parcel or application has `status` of
    `ACTIVE`; a `DRAFT` or `CLOSED` area accepts nothing, and the request is
    rejected with `ERR_SENDING_AREA_NOT_ACTIVE` (409). Applies to parcel
    enrollment, severance filing, and severance certification."

    PRD 3.5: "The parcel's sending area must still be `ACTIVE`, otherwise
    `ERR_SENDING_AREA_NOT_ACTIVE`, which is what makes an `APPROVED` application in
    a closed area permanently uncertifiable."

    PRD 3.2: "A newly designated sending area opens in `status` `DRAFT` with
    `severed_units_total` and `issued_certificate_count` both at 0. Activation moves
    it `DRAFT → ACTIVE` and increments its `version`; an area that is not in `DRAFT`
    cannot be activated and yields `ERR_AREA_NOT_DRAFT`."

    PRD 4: "Endpoints that advance, amend, or read an existing record respond with
    HTTP 200."

    Design: Corner/endpoints/closing_a_sending_area_suspends_open_applications_and_freezes_approved_ones
    """
    set_clock(CLOCK)
    owner = register_landowner(legal_name="Ridge Farm LLC", neighborhood_code="NB-EAST")
    area = create_active_sending_area(code="SA-EAST", **EAST_AREA)
    parcel_a = enroll_parcel(
        owner["id"], area["id"], apn="APN-A01",
        gross_acres=40.00, constrained_acres=0.00, soil_class="LOCAL",
        existing_dwelling_units=0,
    )
    parcel_b = enroll_parcel(owner["id"], area["id"], apn="APN-B01", **CANONICAL_GEOMETRY)

    open_application = file_severance(parcel_a["id"], owner["id"], 10)
    assert open_application["status"] == "SUBMITTED", open_application["status"]
    approved_application = file_severance(parcel_b["id"], owner["id"], 22)
    screen_application(approved_application["id"], REVIEWER_USER_ID)
    approved_application = decide_application(
        approved_application["id"], "APPROVE", REVIEWER_USER_ID
    )
    assert approved_application["status"] == "APPROVED", approved_application["status"]

    closed = validate_success(
        api_client.close_sending_area(
            area["id"], ADMIN_HEADERS, {"reason": "designation retired by ordinance"}
        )
    )
    assert_sending_area(closed)
    assert closed["status"] == "CLOSED", closed["status"]
    assert closed["version"] == 3, (
        "designation, activation and close are three writes, so the version reads 3; got "
        f"{closed['version']}"
    )

    suspended = fetch_application(open_application["id"])
    assert_severance_application(suspended)
    assert suspended["status"] == "SUSPENDED", (
        f"the SUBMITTED filing must be suspended by the cascade, got {suspended['status']}"
    )
    assert suspended["denial_reason"] == "SENDING_AREA_CLOSED", (
        f"got {suspended['denial_reason']}"
    )
    assert suspended["version"] == 2, (
        "the filing plus its one cascade write make version 2; got "
        f"{suspended['version']}"
    )

    untouched = fetch_application(approved_application["id"])
    assert untouched["status"] == "APPROVED", (
        f"an APPROVED application is deliberately left APPROVED, got {untouched['status']}"
    )
    assert untouched["allocated_units"] == 22, untouched["allocated_units"]
    assert untouched["denial_reason"] is None, (
        f"no denial reason is stamped on the approved application, got {untouched['denial_reason']}"
    )

    refused_certify = api_client.certify_severance_application(
        approved_application["id"], make_admin_headers(ADMIN_USER_ID), {}
    )
    validate_error(refused_certify, ApiErrorId.ERR_SENDING_AREA_NOT_ACTIVE.value, 409)

    _, certificate_meta = validate_paginated(
        api_client.list_certificates(
            ADMIN_HEADERS, params={"origin_sending_area_id": area["id"], "limit": 50, "offset": 0}
        )
    )
    assert certificate_meta["total_count"] == 0, (
        f"a closed area can mint nothing, got {certificate_meta['total_count']}"
    )

    refused_filing = api_client.create_severance_application(
        create_severance_application_payload(parcel_a["id"], owner["id"], 5),
        make_landowner_headers(owner["id"]),
    )
    validate_error(refused_filing, ApiErrorId.ERR_SENDING_AREA_NOT_ACTIVE.value, 409)

    area_after = fetch_sending_area(area["id"])
    assert area_after["issued_certificate_count"] == 0, area_after["issued_certificate_count"]
    assert area_after["severed_units_total"] == 0, (
        f"a close severs nothing, got {area_after['severed_units_total']}"
    )


def test_chain_of_title_reads_back_issuance_then_sale_in_sequence():
    """Two chain-of-title rows after one issuance and one settled whole-certificate sale.

    The log is append-only, so the certificate carries exactly `seq_no` 1 and 2, and
    each declared filter selects a different slice of it: the transferor filter finds
    only the sale because an issuance has no transferor, the settling transaction
    filter finds the sale row alone, and the type filter finds the issuance alone.
    The single-row read returns the same values as the list row.

    PRD 3.5: "The registry's chain of title opens at the same moment: a
    **CertificateTransfer** row is appended for the new certificate with
    `transfer_type` of `ISSUANCE`, `seq_no` of 1, `from_party_id` unset,
    `to_party_id` set to the applicant, `units` equal to `allocated_units`,
    `price_cents` unset, `market_transaction_id` unset, and `recorded_at` at the
    current logical clock."

    PRD 3.6: "Rows carry `seq_no`, a sequence number scoped to a single certificate
    that starts at 1 and increases by exactly one for each row appended to that
    certificate, so the pair of `certificate_id` and `seq_no` is unique."

    PRD 3.6: "`from_party_id` names the transferor and is unset on `ISSUANCE` and
    `SPLIT_OUT` rows; `to_party_id` names the transferee and is unset on
    `REDEMPTION` and `RETIREMENT` rows. `market_transaction_id` is set on
    `PRIVATE_SALE`, `BANK_PURCHASE`, `BANK_RESALE`, and `REVERSAL` rows and unset on
    the rest. `price_cents` carries the transaction's gross price on market events
    and is unset on `ISSUANCE`, `SPLIT_OUT`, `REDEMPTION`, and `RETIREMENT` rows.
    `recorded_at` is the logical-clock instant the row was appended."

    PRD 3.6: "The chain-of-title log can be listed with `certificate_id`,
    `from_party_id`, `to_party_id`, `market_transaction_id`, and `transfer_type`
    filters plus `limit` and `offset`, and any single row can be read on its own."

    PRD 2.4: "A chain-of-title row is append-only: once written it is never
    modified, so it carries only `id` and `created_at`. Both `updated_at` and
    `version` are absent from a `CertificateTransfer` altogether."

    PRD 3.7: "When the traded `units` equal the certificate's `units_remaining`,
    `conveyance_mode` is pinned to `WHOLE`: the certificate itself changes hands,
    its `holder_party_id` becomes `buyer_party_id`, and `conveyed_certificate_id` is
    set to the traded `certificate_id`."

    PRD 3.7: "Either way the traded certificate's `units_encumbered` is reduced by
    `units` and its `market_status` returns `UNDER_CONTRACT → HELD`, and a
    chain-of-title row is appended to whichever certificate the buyer ends up
    holding — `transfer_type` of `PRIVATE_SALE`, `BANK_PURCHASE`, or `BANK_RESALE`
    according to `channel`, with the seller as `from_party_id`, the buyer as
    `to_party_id`, `units` units, and `price_cents` equal to `gross_price_cents`."

    Design: Corner/endpoints/chain_of_title_reads_back_issuance_then_sale_in_sequence
    """
    scenario = setup_developer_holding_certificate(
        units=22,
        clock=CLOCK,
        equity_tier="UNDERSERVED",
        per_unit_value_cents=1_234_567,
        equity_adjustment_bps=250,
        agreed_price_cents=30_000_000,
        buyer_credit_cents=30_000_000,
    )
    landowner = scenario["landowner"]
    developer = scenario["developer"]
    certificate = scenario["certificate"]
    transaction = scenario["transaction"]

    rows, meta = validate_paginated(
        api_client.list_certificate_transfers(
            make_developer_headers(developer["id"]),
            params={"certificate_id": certificate["id"], "limit": 50, "offset": 0},
        )
    )
    assert meta["total_count"] == 2, (
        "one issuance plus one settled sale make exactly two chain-of-title rows, got "
        f"{meta['total_count']}"
    )
    by_seq = {row["seq_no"]: row for row in rows}
    assert set(by_seq) == {1, 2}, (
        f"the sequence numbers must be 1 and 2, got {sorted(by_seq)}"
    )
    for row in rows:
        assert_certificate_transfer(row)
        assert row["certificate_id"] == certificate["id"], row["certificate_id"]
        assert_same_instant(row["recorded_at"], CLOCK, "CertificateTransfer.recorded_at")

    issuance = by_seq[1]
    assert issuance["transfer_type"] == "ISSUANCE", issuance["transfer_type"]
    assert issuance["from_party_id"] is None, (
        f"an issuance has no transferor, got {issuance['from_party_id']}"
    )
    assert issuance["to_party_id"] == landowner["id"], (
        f"the applicant is the first transferee, got {issuance['to_party_id']}"
    )
    assert issuance["units"] == 22, issuance["units"]
    assert issuance["price_cents"] is None, (
        f"an issuance carries no price, got {issuance['price_cents']}"
    )
    assert issuance["market_transaction_id"] is None, (
        f"an issuance has no settling transaction, got {issuance['market_transaction_id']}"
    )

    sale = by_seq[2]
    assert sale["transfer_type"] == "PRIVATE_SALE", sale["transfer_type"]
    assert sale["from_party_id"] == landowner["id"], sale["from_party_id"]
    assert sale["to_party_id"] == developer["id"], sale["to_party_id"]
    assert sale["units"] == 22, sale["units"]
    assert sale["price_cents"] == 30_000_000, (
        f"the sale row carries the gross price, got {sale['price_cents']}"
    )
    assert sale["market_transaction_id"] == transaction["id"], (
        f"the sale row names its settlement, got {sale['market_transaction_id']}"
    )

    seller_rows, seller_meta = validate_paginated(
        api_client.list_certificate_transfers(
            ADMIN_HEADERS, params={"from_party_id": landowner["id"], "limit": 50, "offset": 0}
        )
    )
    assert seller_meta["total_count"] == 1, (
        "only the sale row has the landowner as transferor, because the issuance has none; got "
        f"{seller_meta['total_count']}"
    )
    assert seller_rows[0]["id"] == sale["id"], seller_rows[0]["id"]

    tx_rows, tx_meta = validate_paginated(
        api_client.list_certificate_transfers(
            ADMIN_HEADERS,
            params={"market_transaction_id": transaction["id"], "limit": 50, "offset": 0},
        )
    )
    assert tx_meta["total_count"] == 1, (
        f"one settlement appended one row, got {tx_meta['total_count']}"
    )
    assert tx_rows[0]["id"] == sale["id"], tx_rows[0]["id"]

    type_rows, type_meta = validate_paginated(
        api_client.list_certificate_transfers(
            ADMIN_HEADERS, params={"transfer_type": "ISSUANCE", "limit": 50, "offset": 0}
        )
    )
    assert type_meta["total_count"] == 1, (
        f"exactly one issuance exists in the whole log, got {type_meta['total_count']}"
    )
    assert type_rows[0]["id"] == issuance["id"], type_rows[0]["id"]

    detail = validate_success(api_client.get_certificate_transfer(sale["id"], ADMIN_HEADERS))
    assert_certificate_transfer(detail)
    for field in (
        "id", "certificate_id", "seq_no", "transfer_type", "from_party_id",
        "to_party_id", "units", "price_cents", "market_transaction_id",
    ):
        assert detail[field] == sale[field], (
            f"the single-row read must agree with the list row on {field}: "
            f"{detail[field]} != {sale[field]}"
        )
    assert_same_instant(detail["recorded_at"], CLOCK, "CertificateTransfer.recorded_at")

    settled = fetch_transaction(transaction["id"])
    assert settled["conveyance_mode"] == "WHOLE", (
        "all 22 remaining units traded, so the conveyance is WHOLE; got "
        f"{settled['conveyance_mode']}"
    )
    assert settled["conveyed_certificate_id"] == certificate["id"], (
        f"a whole conveyance moves the traded certificate itself, got "
        f"{settled['conveyed_certificate_id']}"
    )
    held = fetch_certificate(certificate["id"])
    assert_certificate(held)
    assert held["holder_party_id"] == developer["id"], held["holder_party_id"]
    assert held["market_status"] == "HELD", (
        f"settlement returns the certificate to HELD, got {held['market_status']}"
    )


def test_compliance_sweep_is_a_no_op_bulk_action_when_nothing_is_due():
    """The sweep run five months late over a program whose one inspection is compliant.

    A `COMPLIANT` finding opens `CLOSED` with no cure deadline at all, so there is
    nothing for the sweep to compare against the clock.  It must succeed and change
    nothing: no escalation, no re-versioned row, no freeze — and a second identical
    run must be equally inert.

    PRD 3.9: "Cure deadlines are enforced by an administrator-triggered compliance
    sweep that evaluates every open violation against the current logical clock.
    Every inspection in `CURE_PENDING` whose `cure_deadline` is strictly earlier
    than the clock moves `CURE_PENDING → ESCALATED` with `escalated_at` set from the
    clock, and drives its easement to `ESCALATED` from `VIOLATION_NOTICED` or
    `UNDER_CURE`, incrementing `prior_violation_count` again."

    PRD 3.9: "A finding of `COMPLIANT` records `severity_score` as 0.00, leaves
    `cure_deadline` unset, and opens the inspection directly in `CLOSED`."

    PRD 3.9: "Every accepted inspection updates `last_inspection_at` to its
    `inspection_date`."

    PRD 3.5: "A freshly recorded easement opens with `units_redeemed_confirmed` at
    0, `units_retired` at 0, `amendment_count` at 0, `compliance_status` of
    `COMPLIANT`, `last_inspection_at` unset, `prior_violation_count` at 0, and
    `cure_deadline` unset."

    PRD 3.5: "`lifecycle_status` is `ISSUED`; `market_status` is `HELD`; and
    `issued_at` is the current logical clock."

    PRD 2.4: "`version` is an integer that starts at 1 when the row is created and
    increases by exactly one on every mutation of that row, including mutations
    reached through a cascade rather than through a direct request."

    PRD 4: "Endpoints that advance, amend, or read an existing record respond with
    HTTP 200."

    Design: Corner/endpoints/compliance_sweep_is_a_no_op_bulk_action_when_nothing_is_due
    """
    scenario = setup_certified_severance(
        units=22, clock=CLOCK, equity_tier="UNDERSERVED", neighborhood_code="NB-EAST",
    )
    easement = scenario["easement"]
    certificate = scenario["certificate"]

    inspection = record_inspection(
        easement["id"], "2026-08-10", finding="COMPLIANT", affected_acres=0.00,
        monitor_user_id=MONITOR_USER_ID,
    )
    assert_monitoring_inspection(inspection)
    assert inspection["status"] == "CLOSED", (
        f"a COMPLIANT finding opens directly in CLOSED, got {inspection['status']}"
    )
    assert inspection["severity_score"] == pytest.approx(0.00, abs=0.01), (
        f"a COMPLIANT finding scores 0.00, got {inspection['severity_score']}"
    )
    assert inspection["cure_deadline"] is None, (
        f"a COMPLIANT finding leaves no cure deadline, got {inspection['cure_deadline']}"
    )
    assert inspection["version"] == 1, inspection["version"]

    set_clock("2027-01-01T00:00:00Z")
    validate_success(api_client.run_compliance_sweep(ADMIN_HEADERS, {}))

    after = fetch_inspection(inspection["id"])
    assert_monitoring_inspection(after)
    assert after["status"] == "CLOSED", (
        f"the sweep must not touch a closed inspection, got {after['status']}"
    )
    assert after["severity_score"] == pytest.approx(0.00, abs=0.01), after["severity_score"]
    assert after["cure_deadline"] is None, after["cure_deadline"]
    assert after["escalated_at"] is None, (
        f"nothing escalated, got escalated_at {after['escalated_at']}"
    )
    assert after["version"] == 1, (
        f"an untouched row is not re-versioned, got version {after['version']}"
    )

    easement_after = fetch_easement(easement["id"])
    assert_conservation_easement(easement_after)
    assert easement_after["compliance_status"] == "COMPLIANT", (
        f"got {easement_after['compliance_status']}"
    )
    assert easement_after["prior_violation_count"] == 0, (
        f"got {easement_after['prior_violation_count']}"
    )
    assert_same_date(
        easement_after["last_inspection_at"], "2026-08-10",
        "ConservationEasement.last_inspection_at",
    )
    certificate_after = fetch_certificate(certificate["id"])
    assert certificate_after["market_status"] == "HELD", (
        f"no freeze was ever applied, got {certificate_after['market_status']}"
    )

    validate_success(api_client.run_compliance_sweep(ADMIN_HEADERS, {}))
    twice = fetch_inspection(inspection["id"])
    assert twice["status"] == "CLOSED", twice["status"]
    assert twice["version"] == 1, (
        f"a second sweep is equally inert, got version {twice['version']}"
    )
    assert twice["escalated_at"] is None, twice["escalated_at"]
    assert fetch_easement(easement["id"])["compliance_status"] == "COMPLIANT", (
        "the easement's compliance posture must survive two sweeps unchanged"
    )
    assert fetch_certificate(certificate["id"])["market_status"] == "HELD", (
        "the certificate must survive two sweeps unfrozen"
    )


def test_releasing_the_only_redemption_drops_the_application_to_backing_deficient():
    """The single 16-unit redemption behind a 20-unit bonus request is released.

    Release moves rights out of commitment without consuming them: the certificate
    and the receiving area both get their counters back, while the source easement's
    outstanding total never moved because nothing was ever confirmed.  The
    application loses its sufficiency and drops out of `DESIGN_APPROVED`, after
    which finalization is refused.

    PRD 3.8: "Release sets `released_at`, reduces the certificate's
    `units_encumbered` by `units` and the area's `reserved_units` by `units`,
    recomputes `pending_backed_units`, and increments the redemption's `version`.
    The source easement's `units_outstanding` is deliberately unchanged: allocation
    and release move rights between commitment states without ever creating or
    destroying them, so an allocate-then-release pair returns every counter to its
    starting value. A `DESIGN_APPROVED` application whose backing has fallen below
    `required_backing_units` moves `DESIGN_APPROVED → BACKING_DEFICIENT`."

    PRD 3.8: "A redemption in `ALLOCATED` or `HELD_PENDING_COMPLIANCE` may be
    released, with an optional `reason`, by the application's own developer or by a
    `ProgramAdministrator`."

    PRD 3.8: "Only the application's own developer finalizes, and only from
    `DESIGN_APPROVED` — a `DESIGN_REVIEW`, `REVISIONS_REQUIRED`, or
    `BACKING_DEFICIENT` application is rejected with
    `ERR_APPLICATION_NOT_DESIGN_APPROVED`."

    PRD 3.8: "`required_backing_units` is then the lesser of `requested_bonus_units`
    and `max_bonus_units` — a developer who asks for more density than the area can
    grant is not rejected at intake, but is only ever required to back, and can only
    ever receive, the area's maximum."

    PRD 2.5: "Timestamp fields written from the clock therefore inherit its exact
    value."

    PRD 4: "Endpoints that advance, amend, or read an existing record respond with
    HTTP 200."

    Design: Corner/endpoints/releasing_the_only_redemption_drops_the_application_to_backing_deficient
    """
    scenario = setup_backed_receiving_application(
        backing_units=16,
        site_acres=12.00,
        requested_bonus_units=20,
        absorption_cap_units=500,
        design_review_required=False,
        clock=CLOCK,
    )
    developer = scenario["developer"]
    redemption = scenario["redemption"]
    rsa = scenario["rsa"]
    assert rsa["status"] == "DESIGN_APPROVED", rsa["status"]
    assert rsa["required_backing_units"] == 16, rsa["required_backing_units"]
    assert rsa["pending_backed_units"] == 16, rsa["pending_backed_units"]

    released = validate_success(
        api_client.release_redemption(
            redemption["id"],
            make_developer_headers(developer["id"]),
            {"reason": "developer re-scoped the site plan"},
        )
    )
    assert_certificate_redemption(released)
    assert released["status"] == "RELEASED", (
        f"the released redemption must read RELEASED, got {released['status']}"
    )
    assert_same_instant(released["released_at"], CLOCK, "CertificateRedemption.released_at")
    assert released["version"] > redemption["version"], (
        "release increments the redemption's version"
    )

    certificate = fetch_certificate(scenario["certificate"]["id"])
    assert_certificate(certificate)
    assert certificate["units_encumbered"] == 0, (
        f"the released units return to the certificate, got {certificate['units_encumbered']}"
    )
    assert certificate["units_remaining"] == 22, certificate["units_remaining"]
    assert certificate["units_redeemed"] == 0, (
        f"a released allocation consumed nothing, got {certificate['units_redeemed']}"
    )
    assert certificate["lifecycle_status"] == "ISSUED", (
        f"the rights dimension never advanced, got {certificate['lifecycle_status']}"
    )

    area = fetch_receiving_area(scenario["receiving_area"]["id"])
    assert_receiving_area(area)
    assert area["reserved_units"] == 0, (
        f"the reservation is given back, got {area['reserved_units']}"
    )
    assert area["absorbed_units"] == 0, (
        f"nothing was ever absorbed, got {area['absorbed_units']}"
    )

    easement = fetch_easement(scenario["easement"]["id"])
    assert_conservation_easement(easement)
    assert easement["units_outstanding"] == 22, (
        "the easement's outstanding total is deliberately untouched by allocate-then-release, "
        f"got {easement['units_outstanding']}"
    )
    assert easement["units_redeemed_confirmed"] == 0, easement["units_redeemed_confirmed"]

    deficient = fetch_receiving_site_application(rsa["id"])
    assert_receiving_site_application(deficient)
    assert deficient["status"] == "BACKING_DEFICIENT", (
        "backing has fallen below required_backing_units, so the application leaves "
        f"DESIGN_APPROVED; got {deficient['status']}"
    )
    assert deficient["pending_backed_units"] == 0, deficient["pending_backed_units"]
    assert deficient["backed_units"] == 0, deficient["backed_units"]

    refused = api_client.finalize_receiving_site_application(
        rsa["id"], make_developer_headers(developer["id"]), {}
    )
    validate_error(refused, ApiErrorId.ERR_APPLICATION_NOT_DESIGN_APPROVED.value, 409)

    still_deficient = fetch_receiving_site_application(rsa["id"])
    assert still_deficient["status"] == "BACKING_DEFICIENT", still_deficient["status"]
    assert still_deficient["allocated_bonus_units"] == 0, (
        f"no bonus may be granted, got {still_deficient['allocated_bonus_units']}"
    )
    assert still_deficient["finalized_at"] is None, (
        f"the application was never finalized, got {still_deficient['finalized_at']}"
    )

    holder = fetch_party(developer["id"])
    assert holder["units_held"] == 22, (
        f"the developer holds all 22 units again, got {holder['units_held']}"
    )
    assert holder["certificates_held_count"] == 1, holder["certificates_held_count"]
