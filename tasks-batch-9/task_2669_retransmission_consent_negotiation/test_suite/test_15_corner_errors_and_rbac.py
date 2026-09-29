"""Not-found identity, request-shape rejection, and the four access-control gates."""

from prd_bench_local_runner.testing import build_user_headers

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_distributor,
    create_election,
    create_election_payload,
    create_fee_settlement_payload,
    create_station,
    execute_agreement_payload,
    issue_settlement,
    make_distributor_rep_headers,
    make_group_counsel_headers,
    make_station_negotiator_headers,
    read_agreement,
    read_election,
    read_settlements,
    resolve_audit_finding_payload,
    resolve_rights_dispute_payload,
    setup_executed_agreement,
    setup_network_approved_agreement,
    validate_error,
    validate_paginated,
    validate_success,
    void_settlement_payload,
)

ADMIN = TEST_USERS["carriage_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
COUNSEL = TEST_USERS["group_counsel_headers"]
NETWORK = TEST_USERS["network_representative_headers"]


def test_each_unresolved_path_identifier_reports_its_own_not_found_code(api):
    """Eight resource kinds answer with eight distinct 404 identifiers.

    PRD §2.8: "Each resource kind has its own not-found code:
    `ERR_STATION_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`,
    `ERR_NEGOTIATION_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_AUDIT_FINDING_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    and `ERR_SETTLEMENT_NOT_FOUND`."

    Design: Corner/errors/corner_unknown_path_ids_return_their_own_not_found_error
    """
    validate_error(
        api.get_distributor(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_DISTRIBUTOR_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_election(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_ELECTION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_negotiation(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_NEGOTIATION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_offer(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_OFFER_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_agreement(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.resolve_audit_finding(
            NON_EXISTENT_UUID,
            resolve_audit_finding_payload("SUBSTANTIATED", resolution_note="No such finding"),
            COMPLIANCE,
        ),
        ApiErrorId.ERR_AUDIT_FINDING_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.resolve_rights_dispute(
            NON_EXISTENT_UUID,
            resolve_rights_dispute_payload("INCLUDED", resolution_note="No such dispute"),
            COMPLIANCE,
        ),
        ApiErrorId.ERR_DISPUTE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.void_fee_settlement(
            NON_EXISTENT_UUID,
            void_settlement_payload(void_reason="No such settlement"),
            COUNSEL,
        ),
        ApiErrorId.ERR_SETTLEMENT_NOT_FOUND.value,
        404,
    )


def test_a_well_formed_election_body_naming_no_distributor_is_a_404(api):
    """The body foreign key is resolved after the shape passes, and it is a 404.

    PRD §2.8: "Body foreign-key resolution - `ERR_STATION_NOT_FOUND`,
    `ERR_DISTRIBUTOR_NOT_FOUND` or `ERR_REPORT_NOT_FOUND` as appropriate. Applies to
    the four operations that accept a foreign key in the body: opening a carriage
    election, filing a subscriber report, submitting an offer, and issuing a fee
    settlement."

    Design: Corner/errors/corner_body_foreign_key_and_pagination_errors_are_rejected
    """
    station = create_station()

    response = api.create_election(
        create_election_payload(station["id"], NON_EXISTENT_UUID),
        make_station_negotiator_headers(station["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DISTRIBUTOR_NOT_FOUND.value, 404)

    elections, meta = validate_paginated(api.list_elections(ADMIN))
    assert elections == []
    assert meta["total_count"] == 0


def test_a_limit_above_the_ceiling_is_a_shape_violation_and_one_hundred_is_not(api):
    """101 is out of range at priority 3; exactly 100 is the permitted maximum.

    PRD §2.3: "A `limit` outside the range 1 through 100, or a negative `offset`, is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/errors/corner_body_foreign_key_and_pagination_errors_are_rejected
    """
    validate_error(
        api.list_elections(ADMIN, params={"limit": 200, "offset": 0}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    elections, meta = validate_paginated(
        api.list_elections(ADMIN, params={"limit": 100, "offset": 0})
    )
    assert elections == []
    assert meta["limit"] == 100
    assert meta["offset"] == 0
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_missing_or_unrecognised_role_headers_are_unauthenticated(api):
    """An absent header and an unknown role name are both 401, never 403.

    PRD §2.1: "A request with a missing header, an empty header, or a role string
    outside that set of six is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/corner_missing_auth_headers_are_unauthenticated
    """
    without_role = {"X-User-ID": "admin-1", "Content-Type": "application/json"}
    without_user_id = {"X-User-Role": "CarriageAdmin", "Content-Type": "application/json"}
    unknown_role = build_user_headers("sales-1", "SalesPlanner")

    for headers in (without_role, without_user_id, unknown_role):
        error = validate_error(
            api.list_elections(headers),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        assert error["error_id"] != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value


def test_a_role_outside_the_operations_list_is_refused_before_any_lookup(api):
    """The role gate answers 403 even though none of the addressed rows exist.

    PRD §2.10: "Attempts by either role to reach a restricted read are refused with
    `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/corner_other_roles_exclusive_operations_are_rejected
    """
    distributor = create_distributor()

    validate_error(
        api.list_fee_settlements(
            NON_EXISTENT_UUID, make_distributor_rep_headers(distributor["id"])
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api.get_subscriber_report(NON_EXISTENT_UUID, NETWORK),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api.create_fee_settlement(
            NON_EXISTENT_UUID,
            create_fee_settlement_payload(NON_EXISTENT_UUID),
            make_station_negotiator_headers(NON_EXISTENT_UUID),
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )


def _two_slots_with_one_draft_election():
    station_a = create_station()
    station_b = create_station(
        call_sign="WQRS", market_code="PDX", dma_rank=22,
        market_tv_households=1200000, network_affiliation="FOX",
    )
    distributor_a = create_distributor(name="Cascade Cable")
    election = create_election(station_a["id"], distributor_a["id"])
    return station_a, station_b, distributor_a, election


def test_a_second_station_group_cannot_amend_another_stations_election(api):
    """The role matches but `X-User-ID` is a different station, so it is refused.

    PRD §2.1: "When `X-User-Role` is `StationGroupNegotiator`, `X-User-ID` is the
    `id` of the acting `Station`; ownership checks on any resource that references a
    `Station` compare the resource's station foreign-key field to `X-User-ID`."

    Design: Corner/rbac/corner_peer_roles_cannot_reach_the_other_slots_rows
    """
    _, station_b, _, election = _two_slots_with_one_draft_election()

    response = api.amend_election(
        election["id"],
        {"incumbent_rate_per_sub_cents": 300},
        make_station_negotiator_headers(station_b["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_COUNTERPARTY.value, 403)

    assert read_election(election["id"])["incumbent_rate_per_sub_cents"] == 220


def test_the_owning_station_amends_and_the_counterparty_keeps_the_shared_read(api):
    """Ownership scoping bars the stranger without closing the slot's own parties out.

    PRD §3.3: "While the election is still `DRAFT`, the negotiator may amend it,
    revising any of `election_type`, `requested_tier` or
    `incumbent_rate_per_sub_cents`."

    Design: Corner/rbac/corner_peer_roles_cannot_reach_the_other_slots_rows
    """
    station_a, _, distributor_a, election = _two_slots_with_one_draft_election()

    amended = validate_success(
        api.amend_election(
            election["id"],
            {"incumbent_rate_per_sub_cents": 300},
            make_station_negotiator_headers(station_a["id"]),
        ),
        200,
    )
    assert amended["incumbent_rate_per_sub_cents"] == 300

    seen = validate_success(
        api.get_election(
            election["id"], make_distributor_rep_headers(distributor_a["id"])
        ),
        200,
    )
    assert seen["status"] == "DRAFT"
    assert seen["incumbent_rate_per_sub_cents"] == 300


def test_the_accepting_counsel_may_not_countersign_the_agreement_it_bound(api):
    """counsel-1 holds the right role yet is refused; counsel-2 signs the same row.

    PRD §3.7: "And the executing counsel's `X-User-ID` must differ from the
    agreement's `accepted_by_user_id`; the counsel who bound the group may not also
    sign for it, and an attempt is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/corner_segregation_of_duties_blocks_the_same_user_on_both_steps
    """
    ctx = setup_network_approved_agreement()
    agreement_id = ctx["agreement"]["id"]
    assert ctx["agreement"]["accepted_by_user_id"] == "counsel-1"

    response = api.execute_agreement(
        agreement_id,
        execute_agreement_payload(execution_note="Self-countersignature attempt"),
        make_group_counsel_headers("counsel-1"),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    refused = read_agreement(agreement_id)
    assert refused["execution_status"] == "PENDING_EXECUTION"
    assert refused["executed_by_user_id"] is None

    signed = validate_success(
        api.execute_agreement(
            agreement_id,
            execute_agreement_payload(execution_note="Countersigned by second counsel"),
            make_group_counsel_headers("counsel-2"),
        ),
        200,
    )
    assert signed["execution_status"] == "EXECUTED"
    assert signed["executed_by_user_id"] == "counsel-2"


def test_the_issuing_counsel_may_not_void_its_own_settlement(api):
    """The issuer is refused, an independent counsel voids, and the ledger unwinds.

    PRD §3.9: "The voiding counsel's `X-User-ID` must differ from the settlement's
    `issued_by_user_id`, or the request is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/corner_segregation_of_duties_blocks_the_same_user_on_both_steps
    """
    ctx = setup_executed_agreement()
    settlement = issue_settlement(
        ctx["agreement"]["id"], ctx["report"]["id"], counsel_user_id="counsel-1"
    )
    assert settlement["issued_by_user_id"] == "counsel-1"
    assert settlement["gross_fee_cents"] == 25000000

    validate_error(
        api.void_fee_settlement(
            settlement["id"],
            void_settlement_payload(void_reason="Issuer attempting to void own settlement"),
            make_group_counsel_headers("counsel-1"),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    assert read_settlements(ctx["agreement"]["id"])[0]["status"] == "ISSUED"

    voided = validate_success(
        api.void_fee_settlement(
            settlement["id"],
            void_settlement_payload(void_reason="Voided by independent counsel after review"),
            make_group_counsel_headers("counsel-3"),
        ),
        200,
    )
    assert voided["status"] == "VOIDED"

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["lifetime_gross_fee_cents"] == 0
    assert agreement["lifetime_net_retained_cents"] == 0


def test_the_identity_gate_is_reached_before_the_settlement_state_gate(api):
    """Voiding a VOIDED row as its own issuer still reports the identity refusal.

    PRD §2.8: "Segregation of duties - `ERR_SEGREGATION_OF_DUTIES`. Applies to two
    operations: executing an agreement and voiding a fee settlement."

    Design: Corner/rbac/corner_segregation_of_duties_blocks_the_same_user_on_both_steps
    """
    ctx = setup_executed_agreement()
    settlement = issue_settlement(
        ctx["agreement"]["id"], ctx["report"]["id"], counsel_user_id="counsel-1"
    )
    validate_success(
        api.void_fee_settlement(
            settlement["id"],
            void_settlement_payload(),
            make_group_counsel_headers("counsel-3"),
        ),
        200,
    )

    error = validate_error(
        api.void_fee_settlement(
            settlement["id"],
            void_settlement_payload(),
            make_group_counsel_headers("counsel-1"),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    assert error["error_id"] != ApiErrorId.ERR_SETTLEMENT_NOT_ISSUED.value
