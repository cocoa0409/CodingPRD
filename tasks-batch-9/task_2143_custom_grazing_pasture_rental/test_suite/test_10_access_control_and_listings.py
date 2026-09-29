"""Authentication, role authority, ownership, listings and not-found codes."""

from test_helpers import (
    ADMIN_HEADERS,
    ANONYMOUS_HEADERS,
    UNKNOWN_UUID,
    ApiErrorId,
    build_user_headers,
    capacity_assessment_payload,
    create_contract,
    create_lot,
    create_pasture,
    make_cattle_owner_headers,
    make_grazier_headers,
    make_range_consultant_headers,
    open_infrastructure_ticket,
    provision_active_contract,
    provision_available_pasture,
    provision_pending_contract,
    read_lot,
    read_pasture,
    record_treatment,
    report_death_loss,
    review_death_loss_as_consultant,
    review_treatment_as_owner,
    setup_north_bench_available,
    setup_north_bench_lot_on_feed,
    setup_parties,
    SCHOOL_SECTION,
    DM_1600_AT_25,
    SCHOOL_SECTION_TERMS,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Authentication and role authority
# ===========================================================================

def test_a_request_without_a_role_header_is_unauthenticated(api):
    """PRD 2.1: "A request whose `X-User-Role` header is missing, or whose value is not
    one of those four strings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.8: "The `X-User-Role` header is present and is one of `Grazier`,
    `CattleOwner`, `RangeConsultant`, `PlatformAdmin` — otherwise `ERR_UNAUTHENTICATED`.
    Applies to every endpoint."

    Design: Corner/rbac/request_without_an_x_user_role_header_returns_unauthenticated
    """
    world = setup_parties()
    pasture = create_pasture(world.grazier_id)

    resp = api.get_pasture(pasture["id"], ANONYMOUS_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_an_x_user_id_that_resolves_to_no_grazier_is_a_party_not_found(api):
    """PRD 2.1: "For all three of these roles, `X-User-ID` must be present and must
    resolve to an existing row of the matching entity type, or the request fails with
    `ERR_PARTY_NOT_FOUND` (HTTP 404)."
    PRD 2.1: "When `X-User-Role` is `Grazier`, `X-User-ID` is the `id` of the acting
    `Grazier` record; ownership checks on any resource that references a grazier compare
    that resource's grazier reference to `X-User-ID`."

    Design: Corner/errors/unresolvable_x_user_id_header_returns_party_not_found
    """
    world = setup_parties()
    create_pasture(world.grazier_id)

    resp = api.create_pasture(
        {
            "name": "Ghost Unit", "acres": 50, "forage_type": "NATIVE_RANGE",
            "water_source_type": "POND", "fence_class": "CLASS_C",
        },
        build_user_headers(UNKNOWN_UUID, "Grazier"),
    )
    validate_error(resp, ApiErrorId.ERR_PARTY_NOT_FOUND.value, 404)


def test_a_cattle_owner_may_not_create_a_pasture(api):
    """PRD 2.1: "A request whose role is well-formed but is not listed as an authorized
    role for the endpoint being called is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 3.2: "A `Grazier` creates a pasture unit by supplying a `name` for it, its
    grazeable `acres` (which must be greater than zero), the dominant `forage_type` —
    one of `NATIVE_RANGE`, `IMPROVED_PASTURE`, `COOL_SEASON_MIX` or `WARM_SEASON_MIX` —
    the `water_source_type` that supplies stock water, one of `WELL`, `CREEK`,
    `PIPELINE` or `POND`, and the perimeter `fence_class`, one of `CLASS_A`, `CLASS_B`
    or `CLASS_C`."

    Design: Corner/rbac/cattle_owner_cannot_create_a_pasture
    """
    world = setup_parties()

    resp = api.create_pasture(
        {
            "name": "Not Mine", "acres": 100, "forage_type": "NATIVE_RANGE",
            "water_source_type": "POND", "fence_class": "CLASS_C",
        },
        make_cattle_owner_headers(world.owner_id),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_a_grazier_may_not_rate_their_own_pasture(api):
    """PRD 3.2: "Rating the unit is not the grazier's job. Only a `RangeConsultant` may
    file a carrying-capacity assessment, and because each new assessment supersedes the
    prior one, the filing carries `expected_pasture_version` as described in §2.6."
    PRD 2.1: "A request whose role is well-formed but is not listed as an authorized
    role for the endpoint being called is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/grazier_cannot_file_a_capacity_assessment
    """
    world = setup_parties()
    pasture = create_pasture(world.grazier_id)

    resp = api.create_capacity_assessment(
        pasture["id"],
        capacity_assessment_payload(pasture["version"]),
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    assert read_pasture(pasture["id"], world.grazier_id)["rated_head_days"] == 0


def test_a_platform_admin_may_not_sign_a_contract(api):
    """PRD 2.1: "`PlatformAdmin` is different. When `X-User-Role` is `PlatformAdmin`,
    `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the
    server never compares it to any record's `id` and never resolves it."
    PRD 2.1: "The `PlatformAdmin` registers the three party types and drives the logical
    clock, and holds no business authority over pastures, contracts, lots or
    settlements."

    Design: Corner/rbac/platform_admin_cannot_sign_a_contract
    """
    world = setup_north_bench_available()
    contract = provision_pending_contract(world, world.pasture_id)

    resp = api.sign_contract(
        contract["id"], {"signature_ref": "SIG-ADMIN"}, ADMIN_HEADERS
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    from test_helpers import read_contract
    assert read_contract(contract["id"], world.grazier_id)["lifecycle_status"] == (
        "PENDING_SIGNATURE"
    )


def test_a_grazier_may_void_a_treatment_charge_but_not_approve_it(api):
    """PRD 3.5: "Every recorded charge must be reviewed before the lot can be settled,
    and the review is a small state machine with two constituencies. The `CattleOwner`
    on the contract may approve or dispute: approving moves the treatment
    `RECORDED → APPROVED`, disputing moves it `RECORDED → DISPUTED`, and an owner may
    still approve a treatment they previously disputed, moving it
    `DISPUTED → APPROVED`. The `Grazier` on the contract may withdraw the charge
    instead, voiding it from either `RECORDED → VOIDED` or `DISPUTED → VOIDED`."
    PRD 3.5: "A `decision` naming an outcome the treatment's current `status` does not
    permit — voiding an already-approved row, for instance, since `APPROVED` and
    `VOIDED` are both terminal — is rejected with `ERR_TREATMENT_INVALID_STATE`."

    APPROVE is the CattleOwner's decision, so a Grazier sending it must be refused —
    but the PRD does not pin WHICH code. `Grazier` is listed as an authorized role for
    this endpoint in PRD 4, so ERR_FORBIDDEN_ROLE's stated trigger ("not listed as an
    authorized role for the endpoint being called") does not literally fire; a reader
    following the 2.8 ladder instead lands on rule 10 and reports
    ERR_TREATMENT_INVALID_STATE. Both readings are PRD-faithful, so the assertion is
    relaxed to the pair rather than pinning one.

    Design: Corner/rbac/grazier_cannot_approve_a_treatment_charge_only_void_it
    """
    world = setup_north_bench_lot_on_feed()
    treatment = record_treatment(world.lot_id, world.grazier_id)

    resp = api.review_treatment(
        treatment["id"], {"decision": "APPROVE"}, make_grazier_headers(world.grazier_id)
    )
    validate_error_is_one_of(
        resp,
        [
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            ApiErrorId.ERR_TREATMENT_INVALID_STATE.value,
        ],
    )

    voided = validate_success(
        api.review_treatment(
            treatment["id"], {"decision": "VOID", "note": "Charged to the wrong lot"},
            make_grazier_headers(world.grazier_id),
        ),
        200,
    )
    assert voided["status"] == "VOIDED"


def test_a_range_consultant_may_not_void_a_confirmed_death_report(api):
    """PRD 3.6: "The grazier on the contract may afterwards void a confirmed report
    (`CONFIRMED → VOIDED`), but only while the lot's settlement, if one exists at all,
    is in `DRAFT` or `VOID` — a settled lot cannot have its death record rewritten
    underneath the money."
    PRD 3.6: "Verification belongs to a `RangeConsultant`, who confirms the report
    (`REPORTED → CONFIRMED`) or rejects it (`REPORTED → REJECTED`); no ownership tie is
    required of them, because the consultant's whole value here is independence."

    PRD 3.6: "a `decision` the current `status` does not permit is rejected with
    `ERR_DEATH_LOSS_INVALID_STATE`."

    Voiding is the grazier's decision, so the consultant must be refused — but the PRD
    does not pin WHICH code. `RangeConsultant` is listed as an authorized role for this
    endpoint in PRD 4, so ERR_FORBIDDEN_ROLE's stated trigger ("not listed as an
    authorized role for the endpoint being called") does not literally fire; a reader
    following the 2.8 ladder instead lands on rule 10 and reports
    ERR_DEATH_LOSS_INVALID_STATE. Both readings are PRD-faithful, so the assertion is
    relaxed to the pair rather than pinning one. The report staying CONFIRMED and the
    conserved head counts remain exactly asserted.

    Design: Corner/rbac/range_consultant_cannot_void_a_confirmed_death_loss_report
    """
    world = setup_north_bench_lot_on_feed()
    report = report_death_loss(world.lot_id, world.grazier_id)
    review_death_loss_as_consultant(report["id"], world.consultant_id, "CONFIRM")

    resp = api.review_death_loss(
        report["id"], {"decision": "VOID", "note": "Consultant overreach"},
        make_range_consultant_headers(world.consultant_id),
    )
    validate_error_is_one_of(
        resp,
        [
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            ApiErrorId.ERR_DEATH_LOSS_INVALID_STATE.value,
        ],
    )

    listed, _ = validate_paginated(
        api.list_death_losses(world.lot_id, make_grazier_headers(world.grazier_id))
    )
    assert listed[0]["status"] == "CONFIRMED"
    assert read_lot(world.lot_id, world.grazier_id)["confirmed_death_head"] == 2
    assert read_pasture(world.pasture_id, world.grazier_id)["stocked_head_count"] == 148


def test_a_grazier_may_not_close_another_graziers_pasture(api):
    """PRD 2.1: "Being the right role is not the same as being the right party. On every
    resource-scoped write, the acting entity-backed principal must additionally own the
    target: a `Grazier` must match the pasture's owning grazier or the contract's
    grazier, and a `CattleOwner` must match the contract's cattle owner. A
    role-authorized but non-owning principal is rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/grazier_cannot_close_another_graziers_pasture
    """
    world = setup_north_bench_available(second_grazier=True)

    resp = api.set_pasture_status(
        world.pasture_id, {"to_status": "CLOSED"},
        make_grazier_headers(world.grazier2_id),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    assert read_pasture(world.pasture_id, world.grazier_id)["operational_status"] == "AVAILABLE"


# ===========================================================================
# Identifiers that resolve to nothing
# ===========================================================================

def test_reading_an_unknown_settlement_is_a_settlement_not_found(api):
    """PRD 2.8: "Every identifier embedded in the request path resolves, checked left to
    right, so that the leftmost unresolved identifier is the one reported. The code is
    the one belonging to the segment that failed: `ERR_PASTURE_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_TREATMENT_NOT_FOUND`, `ERR_DEATH_LOSS_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
    `ERR_SETTLEMENT_NOT_FOUND`, or `ERR_PARTY_NOT_FOUND`. Applies to every endpoint
    whose path carries an `id`."

    Design: Corner/entities/get_settlement_with_unknown_id_returns_settlement_not_found
    """
    world = setup_parties()

    resp = api.get_settlement(UNKNOWN_UUID, make_grazier_headers(world.grazier_id))
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_assigning_an_unknown_ticket_is_a_ticket_not_found(api):
    """PRD 2.8: "Every identifier embedded in the request path resolves, checked left to
    right, so that the leftmost unresolved identifier is the one reported. The code is
    the one belonging to the segment that failed: `ERR_PASTURE_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_TREATMENT_NOT_FOUND`, `ERR_DEATH_LOSS_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
    `ERR_SETTLEMENT_NOT_FOUND`, or `ERR_PARTY_NOT_FOUND`. Applies to every endpoint
    whose path carries an `id`."

    Design: Corner/errors/assign_on_an_unknown_ticket_returns_ticket_not_found
    """
    world = setup_parties()

    resp = api.assign_infrastructure_ticket(
        UNKNOWN_UUID, {"repair_party": "GRAZIER"}, make_grazier_headers(world.grazier_id)
    )
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_FOUND.value, 404)


def test_reviewing_an_unknown_treatment_is_a_treatment_not_found(api):
    """PRD 2.8: "Every identifier embedded in the request path resolves, checked left to
    right, so that the leftmost unresolved identifier is the one reported. The code is
    the one belonging to the segment that failed: `ERR_PASTURE_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_TREATMENT_NOT_FOUND`, `ERR_DEATH_LOSS_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
    `ERR_SETTLEMENT_NOT_FOUND`, or `ERR_PARTY_NOT_FOUND`. Applies to every endpoint
    whose path carries an `id`."

    Design: Corner/errors/review_on_an_unknown_treatment_returns_treatment_not_found
    """
    world = setup_parties()

    resp = api.review_treatment(
        UNKNOWN_UUID, {"decision": "APPROVE"}, make_cattle_owner_headers(world.owner_id)
    )
    validate_error(resp, ApiErrorId.ERR_TREATMENT_NOT_FOUND.value, 404)


def test_reading_an_unknown_capacity_assessment_is_an_assessment_not_found(api):
    """PRD 2.8: "Every identifier embedded in the request path resolves, checked left to
    right, so that the leftmost unresolved identifier is the one reported. The code is
    the one belonging to the segment that failed: `ERR_PASTURE_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_TREATMENT_NOT_FOUND`, `ERR_DEATH_LOSS_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
    `ERR_SETTLEMENT_NOT_FOUND`, or `ERR_PARTY_NOT_FOUND`. Applies to every endpoint
    whose path carries an `id`."

    Design: Corner/errors/get_capacity_assessment_with_unknown_id_returns_assessment_not_found
    """
    world = setup_parties()

    resp = api.get_capacity_assessment(
        UNKNOWN_UUID, make_range_consultant_headers(world.consultant_id)
    )
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value, 404)


def test_receiving_an_unknown_lot_is_a_lot_not_found(api):
    """PRD 2.8: "Every identifier embedded in the request path resolves, checked left to
    right, so that the leftmost unresolved identifier is the one reported. The code is
    the one belonging to the segment that failed: `ERR_PASTURE_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_TREATMENT_NOT_FOUND`, `ERR_DEATH_LOSS_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
    `ERR_SETTLEMENT_NOT_FOUND`, or `ERR_PARTY_NOT_FOUND`. Applies to every endpoint
    whose path carries an `id`."

    Design: Corner/errors/receive_on_an_unknown_lot_returns_lot_not_found
    """
    world = setup_parties()

    resp = api.receive_lot(
        UNKNOWN_UUID,
        {
            "head_count_received": 10, "gross_weight_lbs": 5000,
            "scale_ticket_ref": "T-X", "received_at": "2026-08-10T09:00:00Z",
        },
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_FOUND.value, 404)


def test_submitting_an_unknown_contract_is_a_contract_not_found(api):
    """PRD 2.8: "Every identifier embedded in the request path resolves, checked left to
    right, so that the leftmost unresolved identifier is the one reported. The code is
    the one belonging to the segment that failed: `ERR_PASTURE_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_TREATMENT_NOT_FOUND`, `ERR_DEATH_LOSS_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
    `ERR_SETTLEMENT_NOT_FOUND`, or `ERR_PARTY_NOT_FOUND`. Applies to every endpoint
    whose path carries an `id`."

    Design: Corner/errors/submit_on_an_unknown_contract_returns_contract_not_found
    """
    world = setup_parties()

    resp = api.submit_contract(UNKNOWN_UUID, make_grazier_headers(world.grazier_id))
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value, 404)


def test_reviewing_an_unknown_death_report_is_a_death_loss_not_found(api):
    """PRD 2.8: "Every identifier embedded in the request path resolves, checked left to
    right, so that the leftmost unresolved identifier is the one reported. The code is
    the one belonging to the segment that failed: `ERR_PASTURE_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_TREATMENT_NOT_FOUND`, `ERR_DEATH_LOSS_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
    `ERR_SETTLEMENT_NOT_FOUND`, or `ERR_PARTY_NOT_FOUND`. Applies to every endpoint
    whose path carries an `id`."

    Design: Corner/errors/review_on_an_unknown_death_loss_returns_death_loss_not_found
    """
    world = setup_parties()

    resp = api.review_death_loss(
        UNKNOWN_UUID, {"decision": "CONFIRM"},
        make_range_consultant_headers(world.consultant_id),
    )
    validate_error(resp, ApiErrorId.ERR_DEATH_LOSS_NOT_FOUND.value, 404)


def test_a_contract_naming_an_unknown_pasture_is_a_pasture_not_found(api):
    """PRD 2.8: "Every identifier carried in the request body resolves —
    `cattle_owner_id`, `pasture_id`, `contract_id`, `lot_id` — reported as
    `ERR_PARTY_NOT_FOUND`, `ERR_PASTURE_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND` or
    `ERR_LOT_NOT_FOUND` as appropriate. Applies to contract creation,
    infrastructure-ticket creation, and settlement creation."

    Design: Corner/entities/create_contract_with_unknown_pasture_id_returns_pasture_not_found
    """
    world = setup_parties()

    resp = api.create_contract(
        {
            "cattle_owner_id": world.owner_id,
            "pasture_id": UNKNOWN_UUID,
            "billing_mode": "PER_HEAD_PER_DAY",
            "rate_cents": 100,
            "head_count_committed": 20,
            "head_value_cents": 120000,
            "start_date": "2026-08-10",
            "end_date": "2026-11-10",
            "water_responsibility": "GRAZIER",
            "fence_responsibility": "GRAZIER",
            "death_loss_terms": "OWNER_BEARS_ALL",
        },
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_PASTURE_NOT_FOUND.value, 404)


# ===========================================================================
# Listings, filters and the pagination envelope
# ===========================================================================

def test_a_limit_above_one_hundred_is_rejected_rather_than_clamped(api):
    """PRD 2.3: "List endpoints are paginated through two query parameters. The `limit`
    parameter caps the number of records returned; it defaults to 10 when omitted, may
    not be smaller than 1, and may not be larger than 100. The `offset` parameter is the
    number of records to skip and defaults to 0; it may not be negative. A `limit`
    outside the inclusive range of 1 to 100, or a negative `offset`, or a non-integer
    value for either, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/entities/list_pastures_with_limit_above_one_hundred_returns_invalid_pagination
    """
    world = setup_parties()
    create_pasture(world.grazier_id)

    resp = api.list_pastures(
        make_grazier_headers(world.grazier_id), params={"limit": 101, "offset": 0}
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)


def test_contract_listing_paginates_and_filters_by_cattle_owner(api):
    """PRD 2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` counts the
    records matching the filters before pagination is applied and `has_more` is true
    when records remain beyond the current page."
    PRD 3.3: "Contracts can be listed and filtered by `grazier_id`, `cattle_owner_id`,
    `pasture_id`, `lifecycle_status` and `billing_status`."

    Design: Corner/entities/list_contracts_returns_pagination_envelope_and_filters_by_owner
    """
    world = setup_north_bench_available(second_owner=True)
    create_contract(world.grazier_id, world.owner_id, world.pasture_id)
    second = create_contract(
        world.grazier_id, world.owner2_id, world.pasture_id,
        billing_mode="PER_HEAD_PER_DAY", rate_cents=100, shrink_pct=0,
        head_count_committed=30, head_value_cents=120000,
        start_date="2027-04-01", end_date="2027-07-01", treatment_cost_split_pct=0,
        water_responsibility="GRAZIER", fence_responsibility="GRAZIER",
        death_loss_terms="OWNER_BEARS_ALL",
    )

    page_response = api.list_contracts(ADMIN_HEADERS, params={"limit": 1, "offset": 0})
    first_page, meta = validate_paginated(page_response)
    assert page_response.json()["response_type"] == "array"
    assert isinstance(page_response.json()["meta"].get("api_request_id"), str)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(first_page) == 1

    filtered, filtered_meta = validate_paginated(
        api.list_contracts(ADMIN_HEADERS, params={"cattle_owner_id": world.owner2_id})
    )
    assert filtered_meta["total_count"] == 1
    assert filtered[0]["id"] == second["id"]


def test_a_contracts_lot_subresource_returns_only_its_own_lots(api):
    """PRD 3.4: "A booked lot lands in `status` `SCHEDULED` and carries a `contract_id`
    taken from the path. Lots can be listed per contract and filtered by `status`."
    PRD 2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` counts the
    records matching the filters before pagination is applied and `has_more` is true
    when records remain beyond the current page."

    Design: Corner/endpoints/contract_lot_subresource_returns_only_that_contracts_lots
    """
    world = setup_north_bench_lot_on_feed()
    other_pasture, _ = provision_available_pasture(
        world, pasture=SCHOOL_SECTION, assessment=DM_1600_AT_25
    )
    other_contract = provision_active_contract(
        world, other_pasture["id"], signature_ref="SIG-K4", **SCHOOL_SECTION_TERMS
    )
    other_lot = create_lot(
        other_contract["id"], world.grazier_id,
        scheduled_head_count=40, scheduled_delivery_date="2026-08-10",
    )

    first, first_meta = validate_paginated(
        api.list_contract_lots(world.contract_id, make_cattle_owner_headers(world.owner_id))
    )
    assert first_meta["total_count"] == 1
    assert first[0]["id"] == world.lot_id

    second, second_meta = validate_paginated(
        api.list_contract_lots(
            other_contract["id"], make_cattle_owner_headers(world.owner_id),
            params={"status": "SCHEDULED"},
        )
    )
    assert second_meta["total_count"] == 1
    assert second[0]["id"] == other_lot["id"]


def test_infrastructure_tickets_filter_by_contract_and_severity(api):
    """PRD 3.7: "Tickets can be listed and filtered by `pasture_id`, `contract_id`,
    `status` and `severity`."
    PRD 3.7: "Severity is not cosmetic: only a `CRITICAL` ticket counts toward the
    pasture's `open_critical_ticket_count`, and its arrival therefore recomputes that
    count and the pasture's `grazing_posture`, which becomes `RESTRICTED` while the
    ticket is live."

    Design: Corner/endpoints/infrastructure_ticket_list_filters_by_contract_id
    """
    world = setup_north_bench_lot_on_feed()
    critical = open_infrastructure_ticket(
        world.pasture_id, world.contract_id, make_grazier_headers(world.grazier_id),
        asset_type="WATER", severity="CRITICAL", description="Pipeline blown",
        reported_at="2026-09-10T08:00:00Z",
    )
    open_infrastructure_ticket(
        world.pasture_id, world.contract_id, make_cattle_owner_headers(world.owner_id),
        asset_type="FENCE", severity="MINOR", description="Two staples popped",
        reported_at="2026-09-11T08:00:00Z",
    )

    _, both_meta = validate_paginated(
        api.list_infrastructure_tickets(
            make_grazier_headers(world.grazier_id), params={"contract_id": world.contract_id}
        )
    )
    assert both_meta["total_count"] == 2

    narrowed, narrowed_meta = validate_paginated(
        api.list_infrastructure_tickets(
            make_grazier_headers(world.grazier_id),
            params={"contract_id": world.contract_id, "severity": "CRITICAL"},
        )
    )
    assert narrowed_meta["total_count"] == 1
    assert narrowed[0]["id"] == critical["id"]

    pasture = read_pasture(world.pasture_id, world.grazier_id)
    assert pasture["open_critical_ticket_count"] == 1
    assert pasture["grazing_posture"] == "RESTRICTED"


def test_a_lot_lists_its_own_treatments_and_death_reports(api):
    """PRD 3.5: "Each treatment belongs to the lot in whose path it was filed, recorded
    as `lot_id`. Treatments can be listed per lot and filtered by `status`."
    PRD 3.6: "A freshly filed report lands in `status` `REPORTED` and carries no money
    at all — its `owner_liable_head`, `grazier_liable_head` and `credit_cents` all sit at
    0 until somebody independent verifies it. Reports can be listed per lot and filtered
    by `status`."

    Design: Corner/endpoints/lot_subresources_list_their_own_treatments_and_death_losses
    """
    world = setup_north_bench_lot_on_feed()
    approved = record_treatment(world.lot_id, world.grazier_id)
    record_treatment(
        world.lot_id, world.grazier_id, protocol_code="PINK-EYE",
        classification="THERAPEUTIC", treatment_date="2026-09-20", withdrawal_days=14,
        head_treated=4, drug_cost_cents=4500, labor_cost_cents=1200,
    )
    review_treatment_as_owner(approved["id"], world.owner_id, "APPROVE")
    death = report_death_loss(world.lot_id, world.grazier_id, cause="PREDATOR")

    _, all_meta = validate_paginated(
        api.list_treatments(world.lot_id, make_cattle_owner_headers(world.owner_id))
    )
    assert all_meta["total_count"] == 2

    only_approved, approved_meta = validate_paginated(
        api.list_treatments(
            world.lot_id, make_cattle_owner_headers(world.owner_id),
            params={"status": "APPROVED"},
        )
    )
    assert approved_meta["total_count"] == 1
    assert only_approved[0]["id"] == approved["id"]

    deaths, death_meta = validate_paginated(
        api.list_death_losses(world.lot_id, make_cattle_owner_headers(world.owner_id))
    )
    assert death_meta["total_count"] == 1
    assert deaths[0]["id"] == death["id"]
    assert deaths[0]["status"] == "REPORTED"
    assert deaths[0]["owner_liable_head"] == 0
    assert deaths[0]["credit_cents"] == 0
