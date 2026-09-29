"""Path resolution failures, authentication, role authorization, resource
ownership and segregation of duties."""
from test_helpers import (
    ApiErrorId,
    create_barge,
    create_commodity,
    create_contract,
    create_lock,
    create_shipper,
    create_tow,
    draft_tariff,
    file_tariff,
    make_claims_adjuster_headers,
    make_contract_manager_headers,
    make_harbor_agent_headers,
    make_lock_master_headers,
    make_rate_authority_headers,
    make_towboat_dispatcher_headers,
    make_waterway_admin_headers,
    read_barge,
    read_contract,
    read_lock,
    read_reservation,
    read_shipper,
    read_tariff,
    read_tow,
    request_lock_slot,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_waterway_admin_headers()
DISPATCH = make_towboat_dispatcher_headers()
HARBOR = make_harbor_agent_headers()
BILLER = make_contract_manager_headers()
ADJUSTER = make_claims_adjuster_headers()

UNKNOWN_IDS = {
    "shipper": "00000000-0000-4000-8000-000000000001",
    "commodity": "00000000-0000-4000-8000-000000000002",
    "tariff_filing": "00000000-0000-4000-8000-000000000003",
    "barge": "00000000-0000-4000-8000-000000000004",
    "cleaning_order": "00000000-0000-4000-8000-000000000005",
    "fleeting_assignment": "00000000-0000-4000-8000-000000000006",
    "lock": "00000000-0000-4000-8000-000000000007",
    "lock_reservation": "00000000-0000-4000-8000-000000000008",
    "tow": "00000000-0000-4000-8000-000000000009",
    "barge_assignment": "00000000-0000-4000-8000-00000000000a",
    "freight_contract": "00000000-0000-4000-8000-00000000000b",
    "cargo_claim": "00000000-0000-4000-8000-00000000000c",
    "fleeting_berth": "00000000-0000-4000-8000-00000000000d",
}


# ---------------------------------------------------------------------------
# Queue B — path existence
# ---------------------------------------------------------------------------
def test_get_shipper_with_unknown_id_returns_not_found(api):
    """PRD §2.6: "The path variables used across the API are `shipper_id`,
    `commodity_id`, `tariff_filing_id`, `barge_id`, `cleaning_order_id`,
    `fleeting_berth_id`, `fleeting_assignment_id`, `lock_id`,
    `lock_reservation_id`, `tow_id`, `barge_assignment_id`,
    `freight_contract_id` and `cargo_claim_id`, and each resolves to the
    not-found code of its own entity: `ERR_SHIPPER_NOT_FOUND`,
    `ERR_COMMODITY_NOT_FOUND`, `ERR_TARIFF_FILING_NOT_FOUND`,
    `ERR_BARGE_NOT_FOUND`, `ERR_CLEANING_ORDER_NOT_FOUND`,
    `ERR_FLEETING_BERTH_NOT_FOUND`, `ERR_FLEETING_ASSIGNMENT_NOT_FOUND`,
    `ERR_LOCK_NOT_FOUND`, `ERR_LOCK_RESERVATION_NOT_FOUND`, `ERR_TOW_NOT_FOUND`,
    `ERR_BARGE_ASSIGNMENT_NOT_FOUND`, `ERR_FREIGHT_CONTRACT_NOT_FOUND` and
    `ERR_CARGO_CLAIM_NOT_FOUND` respectively, each with HTTP 404."

    Design: Corner/errors/get_shipper_with_unknown_id_returns_not_found
    """
    response = api.get_shipper(UNKNOWN_IDS["shipper"], BILLER)
    validate_error(response, ApiErrorId.ERR_SHIPPER_NOT_FOUND.value)
    assert response.json()["response_type"] == "error"


def test_get_commodity_with_unknown_id_returns_not_found(api):
    """PRD §2.6: "The path variables used across the API are `shipper_id`,
    `commodity_id`, `tariff_filing_id`, `barge_id`, `cleaning_order_id`,
    `fleeting_berth_id`, `fleeting_assignment_id`, `lock_id`,
    `lock_reservation_id`, `tow_id`, `barge_assignment_id`,
    `freight_contract_id` and `cargo_claim_id`, and each resolves to the
    not-found code of its own entity: `ERR_SHIPPER_NOT_FOUND`,
    `ERR_COMMODITY_NOT_FOUND`, `ERR_TARIFF_FILING_NOT_FOUND`,
    `ERR_BARGE_NOT_FOUND`, `ERR_CLEANING_ORDER_NOT_FOUND`,
    `ERR_FLEETING_BERTH_NOT_FOUND`, `ERR_FLEETING_ASSIGNMENT_NOT_FOUND`,
    `ERR_LOCK_NOT_FOUND`, `ERR_LOCK_RESERVATION_NOT_FOUND`, `ERR_TOW_NOT_FOUND`,
    `ERR_BARGE_ASSIGNMENT_NOT_FOUND`, `ERR_FREIGHT_CONTRACT_NOT_FOUND` and
    `ERR_CARGO_CLAIM_NOT_FOUND` respectively, each with HTTP 404."

    Design: Corner/errors/get_commodity_with_unknown_id_returns_not_found
    """
    validate_error(api.get_commodity(UNKNOWN_IDS["commodity"], ADMIN),
                   ApiErrorId.ERR_COMMODITY_NOT_FOUND.value)


def test_get_tariff_filing_with_unknown_id_returns_not_found(api):
    """PRD §2.6: "The path variables used across the API are `shipper_id`,
    `commodity_id`, `tariff_filing_id`, `barge_id`, `cleaning_order_id`,
    `fleeting_berth_id`, `fleeting_assignment_id`, `lock_id`,
    `lock_reservation_id`, `tow_id`, `barge_assignment_id`,
    `freight_contract_id` and `cargo_claim_id`, and each resolves to the
    not-found code of its own entity: `ERR_SHIPPER_NOT_FOUND`,
    `ERR_COMMODITY_NOT_FOUND`, `ERR_TARIFF_FILING_NOT_FOUND`,
    `ERR_BARGE_NOT_FOUND`, `ERR_CLEANING_ORDER_NOT_FOUND`,
    `ERR_FLEETING_BERTH_NOT_FOUND`, `ERR_FLEETING_ASSIGNMENT_NOT_FOUND`,
    `ERR_LOCK_NOT_FOUND`, `ERR_LOCK_RESERVATION_NOT_FOUND`, `ERR_TOW_NOT_FOUND`,
    `ERR_BARGE_ASSIGNMENT_NOT_FOUND`, `ERR_FREIGHT_CONTRACT_NOT_FOUND` and
    `ERR_CARGO_CLAIM_NOT_FOUND` respectively, each with HTTP 404."

    Design: Corner/errors/get_tariff_filing_with_unknown_id_returns_not_found
    """
    validate_error(
        api.get_tariff_filing(UNKNOWN_IDS["tariff_filing"], ADMIN),
        ApiErrorId.ERR_TARIFF_FILING_NOT_FOUND.value)


def test_get_barge_with_unknown_id_returns_not_found(api):
    """PRD §2.6: "The path variables used across the API are `shipper_id`,
    `commodity_id`, `tariff_filing_id`, `barge_id`, `cleaning_order_id`,
    `fleeting_berth_id`, `fleeting_assignment_id`, `lock_id`,
    `lock_reservation_id`, `tow_id`, `barge_assignment_id`,
    `freight_contract_id` and `cargo_claim_id`, and each resolves to the
    not-found code of its own entity: `ERR_SHIPPER_NOT_FOUND`,
    `ERR_COMMODITY_NOT_FOUND`, `ERR_TARIFF_FILING_NOT_FOUND`,
    `ERR_BARGE_NOT_FOUND`, `ERR_CLEANING_ORDER_NOT_FOUND`,
    `ERR_FLEETING_BERTH_NOT_FOUND`, `ERR_FLEETING_ASSIGNMENT_NOT_FOUND`,
    `ERR_LOCK_NOT_FOUND`, `ERR_LOCK_RESERVATION_NOT_FOUND`, `ERR_TOW_NOT_FOUND`,
    `ERR_BARGE_ASSIGNMENT_NOT_FOUND`, `ERR_FREIGHT_CONTRACT_NOT_FOUND` and
    `ERR_CARGO_CLAIM_NOT_FOUND` respectively, each with HTTP 404."

    Design: Corner/errors/get_barge_with_unknown_id_returns_not_found
    """
    validate_error(api.get_barge(UNKNOWN_IDS["barge"], ADMIN),
                   ApiErrorId.ERR_BARGE_NOT_FOUND.value)


def test_get_cleaning_order_with_unknown_id_returns_not_found(api):
    """PRD §2.6: "The path variables used across the API are `shipper_id`,
    `commodity_id`, `tariff_filing_id`, `barge_id`, `cleaning_order_id`,
    `fleeting_berth_id`, `fleeting_assignment_id`, `lock_id`,
    `lock_reservation_id`, `tow_id`, `barge_assignment_id`,
    `freight_contract_id` and `cargo_claim_id`, and each resolves to the
    not-found code of its own entity: `ERR_SHIPPER_NOT_FOUND`,
    `ERR_COMMODITY_NOT_FOUND`, `ERR_TARIFF_FILING_NOT_FOUND`,
    `ERR_BARGE_NOT_FOUND`, `ERR_CLEANING_ORDER_NOT_FOUND`,
    `ERR_FLEETING_BERTH_NOT_FOUND`, `ERR_FLEETING_ASSIGNMENT_NOT_FOUND`,
    `ERR_LOCK_NOT_FOUND`, `ERR_LOCK_RESERVATION_NOT_FOUND`, `ERR_TOW_NOT_FOUND`,
    `ERR_BARGE_ASSIGNMENT_NOT_FOUND`, `ERR_FREIGHT_CONTRACT_NOT_FOUND` and
    `ERR_CARGO_CLAIM_NOT_FOUND` respectively, each with HTTP 404."

    Design: Corner/errors/get_cleaning_order_with_unknown_id_returns_not_found
    """
    validate_error(api.get_cleaning_order(UNKNOWN_IDS["cleaning_order"], HARBOR),
                   ApiErrorId.ERR_CLEANING_ORDER_NOT_FOUND.value)


def test_get_fleeting_assignment_with_unknown_id_returns_not_found(api):
    """PRD §2.6: "The path variables used across the API are `shipper_id`,
    `commodity_id`, `tariff_filing_id`, `barge_id`, `cleaning_order_id`,
    `fleeting_berth_id`, `fleeting_assignment_id`, `lock_id`,
    `lock_reservation_id`, `tow_id`, `barge_assignment_id`,
    `freight_contract_id` and `cargo_claim_id`, and each resolves to the
    not-found code of its own entity: `ERR_SHIPPER_NOT_FOUND`,
    `ERR_COMMODITY_NOT_FOUND`, `ERR_TARIFF_FILING_NOT_FOUND`,
    `ERR_BARGE_NOT_FOUND`, `ERR_CLEANING_ORDER_NOT_FOUND`,
    `ERR_FLEETING_BERTH_NOT_FOUND`, `ERR_FLEETING_ASSIGNMENT_NOT_FOUND`,
    `ERR_LOCK_NOT_FOUND`, `ERR_LOCK_RESERVATION_NOT_FOUND`, `ERR_TOW_NOT_FOUND`,
    `ERR_BARGE_ASSIGNMENT_NOT_FOUND`, `ERR_FREIGHT_CONTRACT_NOT_FOUND` and
    `ERR_CARGO_CLAIM_NOT_FOUND` respectively, each with HTTP 404."

    Design: Corner/errors/get_fleeting_assignment_with_unknown_id_returns_not_found
    """
    validate_error(
        api.get_fleeting_assignment(UNKNOWN_IDS["fleeting_assignment"], HARBOR),
        ApiErrorId.ERR_FLEETING_ASSIGNMENT_NOT_FOUND.value)


def test_get_lock_with_unknown_id_returns_not_found(api):
    """PRD §2.6: "The path variables used across the API are `shipper_id`,
    `commodity_id`, `tariff_filing_id`, `barge_id`, `cleaning_order_id`,
    `fleeting_berth_id`, `fleeting_assignment_id`, `lock_id`,
    `lock_reservation_id`, `tow_id`, `barge_assignment_id`,
    `freight_contract_id` and `cargo_claim_id`, and each resolves to the
    not-found code of its own entity: `ERR_SHIPPER_NOT_FOUND`,
    `ERR_COMMODITY_NOT_FOUND`, `ERR_TARIFF_FILING_NOT_FOUND`,
    `ERR_BARGE_NOT_FOUND`, `ERR_CLEANING_ORDER_NOT_FOUND`,
    `ERR_FLEETING_BERTH_NOT_FOUND`, `ERR_FLEETING_ASSIGNMENT_NOT_FOUND`,
    `ERR_LOCK_NOT_FOUND`, `ERR_LOCK_RESERVATION_NOT_FOUND`, `ERR_TOW_NOT_FOUND`,
    `ERR_BARGE_ASSIGNMENT_NOT_FOUND`, `ERR_FREIGHT_CONTRACT_NOT_FOUND` and
    `ERR_CARGO_CLAIM_NOT_FOUND` respectively, each with HTTP 404."

    Design: Corner/errors/get_lock_with_unknown_id_returns_not_found
    """
    validate_error(api.get_lock(UNKNOWN_IDS["lock"], DISPATCH),
                   ApiErrorId.ERR_LOCK_NOT_FOUND.value)


def test_get_lock_reservation_with_unknown_id_returns_not_found(api):
    """PRD §2.6: "The path variables used across the API are `shipper_id`,
    `commodity_id`, `tariff_filing_id`, `barge_id`, `cleaning_order_id`,
    `fleeting_berth_id`, `fleeting_assignment_id`, `lock_id`,
    `lock_reservation_id`, `tow_id`, `barge_assignment_id`,
    `freight_contract_id` and `cargo_claim_id`, and each resolves to the
    not-found code of its own entity: `ERR_SHIPPER_NOT_FOUND`,
    `ERR_COMMODITY_NOT_FOUND`, `ERR_TARIFF_FILING_NOT_FOUND`,
    `ERR_BARGE_NOT_FOUND`, `ERR_CLEANING_ORDER_NOT_FOUND`,
    `ERR_FLEETING_BERTH_NOT_FOUND`, `ERR_FLEETING_ASSIGNMENT_NOT_FOUND`,
    `ERR_LOCK_NOT_FOUND`, `ERR_LOCK_RESERVATION_NOT_FOUND`, `ERR_TOW_NOT_FOUND`,
    `ERR_BARGE_ASSIGNMENT_NOT_FOUND`, `ERR_FREIGHT_CONTRACT_NOT_FOUND` and
    `ERR_CARGO_CLAIM_NOT_FOUND` respectively, each with HTTP 404."

    Design: Corner/errors/get_lock_reservation_with_unknown_id_returns_not_found
    """
    validate_error(
        api.get_lock_reservation(UNKNOWN_IDS["lock_reservation"], DISPATCH),
        ApiErrorId.ERR_LOCK_RESERVATION_NOT_FOUND.value)


def test_get_tow_with_unknown_id_returns_not_found(api):
    """PRD §2.6: "The path variables used across the API are `shipper_id`,
    `commodity_id`, `tariff_filing_id`, `barge_id`, `cleaning_order_id`,
    `fleeting_berth_id`, `fleeting_assignment_id`, `lock_id`,
    `lock_reservation_id`, `tow_id`, `barge_assignment_id`,
    `freight_contract_id` and `cargo_claim_id`, and each resolves to the
    not-found code of its own entity: `ERR_SHIPPER_NOT_FOUND`,
    `ERR_COMMODITY_NOT_FOUND`, `ERR_TARIFF_FILING_NOT_FOUND`,
    `ERR_BARGE_NOT_FOUND`, `ERR_CLEANING_ORDER_NOT_FOUND`,
    `ERR_FLEETING_BERTH_NOT_FOUND`, `ERR_FLEETING_ASSIGNMENT_NOT_FOUND`,
    `ERR_LOCK_NOT_FOUND`, `ERR_LOCK_RESERVATION_NOT_FOUND`, `ERR_TOW_NOT_FOUND`,
    `ERR_BARGE_ASSIGNMENT_NOT_FOUND`, `ERR_FREIGHT_CONTRACT_NOT_FOUND` and
    `ERR_CARGO_CLAIM_NOT_FOUND` respectively, each with HTTP 404."

    Design: Corner/errors/get_tow_with_unknown_id_returns_not_found
    """
    validate_error(api.get_tow(UNKNOWN_IDS["tow"], DISPATCH),
                   ApiErrorId.ERR_TOW_NOT_FOUND.value)


def test_get_barge_assignment_with_unknown_id_returns_not_found(api):
    """PRD §2.6: "The path variables used across the API are `shipper_id`,
    `commodity_id`, `tariff_filing_id`, `barge_id`, `cleaning_order_id`,
    `fleeting_berth_id`, `fleeting_assignment_id`, `lock_id`,
    `lock_reservation_id`, `tow_id`, `barge_assignment_id`,
    `freight_contract_id` and `cargo_claim_id`, and each resolves to the
    not-found code of its own entity: `ERR_SHIPPER_NOT_FOUND`,
    `ERR_COMMODITY_NOT_FOUND`, `ERR_TARIFF_FILING_NOT_FOUND`,
    `ERR_BARGE_NOT_FOUND`, `ERR_CLEANING_ORDER_NOT_FOUND`,
    `ERR_FLEETING_BERTH_NOT_FOUND`, `ERR_FLEETING_ASSIGNMENT_NOT_FOUND`,
    `ERR_LOCK_NOT_FOUND`, `ERR_LOCK_RESERVATION_NOT_FOUND`, `ERR_TOW_NOT_FOUND`,
    `ERR_BARGE_ASSIGNMENT_NOT_FOUND`, `ERR_FREIGHT_CONTRACT_NOT_FOUND` and
    `ERR_CARGO_CLAIM_NOT_FOUND` respectively, each with HTTP 404."

    Design: Corner/errors/get_barge_assignment_with_unknown_id_returns_not_found
    """
    validate_error(
        api.get_barge_assignment(UNKNOWN_IDS["barge_assignment"], DISPATCH),
        ApiErrorId.ERR_BARGE_ASSIGNMENT_NOT_FOUND.value)


def test_get_freight_contract_with_unknown_id_returns_not_found(api):
    """PRD §2.6: "The path variables used across the API are `shipper_id`,
    `commodity_id`, `tariff_filing_id`, `barge_id`, `cleaning_order_id`,
    `fleeting_berth_id`, `fleeting_assignment_id`, `lock_id`,
    `lock_reservation_id`, `tow_id`, `barge_assignment_id`,
    `freight_contract_id` and `cargo_claim_id`, and each resolves to the
    not-found code of its own entity: `ERR_SHIPPER_NOT_FOUND`,
    `ERR_COMMODITY_NOT_FOUND`, `ERR_TARIFF_FILING_NOT_FOUND`,
    `ERR_BARGE_NOT_FOUND`, `ERR_CLEANING_ORDER_NOT_FOUND`,
    `ERR_FLEETING_BERTH_NOT_FOUND`, `ERR_FLEETING_ASSIGNMENT_NOT_FOUND`,
    `ERR_LOCK_NOT_FOUND`, `ERR_LOCK_RESERVATION_NOT_FOUND`, `ERR_TOW_NOT_FOUND`,
    `ERR_BARGE_ASSIGNMENT_NOT_FOUND`, `ERR_FREIGHT_CONTRACT_NOT_FOUND` and
    `ERR_CARGO_CLAIM_NOT_FOUND` respectively, each with HTTP 404."

    Design: Corner/errors/get_freight_contract_with_unknown_id_returns_not_found
    """
    validate_error(
        api.get_freight_contract(UNKNOWN_IDS["freight_contract"], BILLER),
        ApiErrorId.ERR_FREIGHT_CONTRACT_NOT_FOUND.value)


def test_get_cargo_claim_with_unknown_id_returns_not_found(api):
    """PRD §2.6: "The path variables used across the API are `shipper_id`,
    `commodity_id`, `tariff_filing_id`, `barge_id`, `cleaning_order_id`,
    `fleeting_berth_id`, `fleeting_assignment_id`, `lock_id`,
    `lock_reservation_id`, `tow_id`, `barge_assignment_id`,
    `freight_contract_id` and `cargo_claim_id`, and each resolves to the
    not-found code of its own entity: `ERR_SHIPPER_NOT_FOUND`,
    `ERR_COMMODITY_NOT_FOUND`, `ERR_TARIFF_FILING_NOT_FOUND`,
    `ERR_BARGE_NOT_FOUND`, `ERR_CLEANING_ORDER_NOT_FOUND`,
    `ERR_FLEETING_BERTH_NOT_FOUND`, `ERR_FLEETING_ASSIGNMENT_NOT_FOUND`,
    `ERR_LOCK_NOT_FOUND`, `ERR_LOCK_RESERVATION_NOT_FOUND`, `ERR_TOW_NOT_FOUND`,
    `ERR_BARGE_ASSIGNMENT_NOT_FOUND`, `ERR_FREIGHT_CONTRACT_NOT_FOUND` and
    `ERR_CARGO_CLAIM_NOT_FOUND` respectively, each with HTTP 404."

    Design: Corner/errors/get_cargo_claim_with_unknown_id_returns_not_found
    """
    validate_error(api.get_cargo_claim(UNKNOWN_IDS["cargo_claim"], ADJUSTER),
                   ApiErrorId.ERR_CARGO_CLAIM_NOT_FOUND.value)


def test_reserving_a_berth_that_does_not_exist_returns_not_found(api):
    """PRD §2.7: "**Foreign-key existence.** Every foreign key supplied in the
    body resolves to an existing row, validated in the order the fields are
    declared in the endpoint's input list — otherwise the matching not-found
    code (404). Applies to every write endpoint carrying foreign keys."

    Design: Corner/errors/create_fleeting_assignment_with_unknown_berth_returns_not_found
    """
    barge = create_barge(hull_number="BL-E001")
    validate_error(api.create_fleeting_assignment({
        "barge_id": barge["id"],
        "fleeting_berth_id": UNKNOWN_IDS["fleeting_berth"],
        "start_at": "2026-08-18T00:00:00Z",
        "end_at": "2026-08-19T00:00:00Z",
    }, HARBOR), ApiErrorId.ERR_FLEETING_BERTH_NOT_FOUND.value)
    assert read_barge(barge["id"])["operational_status"] == "IDLE"


# ---------------------------------------------------------------------------
# Queue B — authentication, authorization, ownership, segregation of duties
# ---------------------------------------------------------------------------
def test_request_without_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to every endpoint must carry two headers:
    `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's
    role. If either header is absent, or if `X-User-Role` does not name one of
    the roles declared below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD §2.1: "Authentication is always evaluated before authorization, and both
    are evaluated before anything else about the request is examined."

    Design: Corner/rbac/request_without_identity_headers_returns_unauthenticated
    """
    validate_error(api.create_barge({
        "hull_number": "BL-F001",
        "capacity_tons": 1750,
        "light_draft_feet": 1.5,
        "tons_per_inch_immersion": 17.0,
    }, {"Content-Type": "application/json"}),
        ApiErrorId.ERR_UNAUTHENTICATED.value)

    _rows, meta = validate_paginated(api.list_barges(ADMIN))
    assert meta["total_count"] == 0, "the refused registration stored nothing"


def test_harbor_agent_cannot_seal_a_tow(api):
    """PRD §2.7: "**Role authorization.** The caller's role appears in the
    endpoint's authorized list — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies
    to every endpoint."
    PRD §4: "The "Authorized Role(s)" column lists exactly which roles may call
    the endpoint; a caller holding any other role is refused with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/harbor_agent_cannot_seal_a_tow
    """
    tow = create_tow(towboat_name="M/V Quebec", horsepower=4000)
    validate_error(api.seal_tow(tow["id"], HARBOR),
                   ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    stored = read_tow(tow["id"])
    assert stored["status"] == "BUILDING", (
        "the role check fires before the empty-tow state check")
    assert stored["version"] == 1


def test_claims_adjuster_cannot_issue_a_freight_invoice(api):
    """PRD §2.7: "**Role authorization.** The caller's role appears in the
    endpoint's authorized list — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies
    to every endpoint."
    PRD §2.7: "A caller who sends a malformed body to an endpoint their role may
    not use sees the authorization failure, not the body failure; a caller who
    sends a stale version alongside a cargo incompatibility sees the stale
    version failure, because concurrency sits above safety on this ladder."

    Design: Corner/rbac/claims_adjuster_cannot_issue_a_freight_invoice
    """
    commodity = create_commodity(code="CORN", commodity_group="GRAIN")
    shipper = create_shipper()
    contract = create_contract(shipper["id"], commodity["id"], contracted_tons=1700)

    validate_error(api.issue_invoice(
        contract["id"],
        {"expected_shipper_version": read_shipper(shipper["id"])["version"]},
        ADJUSTER),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    stored = read_contract(contract["id"])
    assert stored["billing_status"] == "NOT_BILLED"
    assert stored["movement_status"] == "DRAFT"
    assert read_shipper(shipper["id"])["outstanding_balance_cents"] == 0


def test_lock_master_cannot_grant_a_slot_at_another_chamber(api):
    """PRD §2.1: "When `X-User-Role` is `LockMaster`, `X-User-ID` is the `id` of
    the `Lock` the caller masters. Ownership checks compare the target
    resource's chamber reference to `X-User-ID`: granting, denying or
    rescheduling a lock reservation compares the reservation's `lock_id` to
    `X-User-ID`, and changing a chamber's posture compares the chamber's own
    `id` to `X-User-ID`. A `LockMaster` acting on another chamber's reservation,
    or on another chamber, is refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/lock_master_cannot_grant_a_slot_at_another_chamber
    """
    first_lock = create_lock(lock_name="Chain of Rocks")
    second_lock = create_lock(lock_name="Mel Price", river_mile=200.8,
                              cycle_minutes=60, turnback_buffer_minutes=20)
    tow = create_tow(towboat_name="M/V Romeo", horsepower=4000)
    reservation = request_lock_slot(first_lock["id"], tow["id"],
                                    "2026-08-15T08:00:00Z")

    validate_error(api.grant_lock_reservation(
        reservation["id"], make_lock_master_headers(second_lock["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert read_reservation(reservation["id"])["status"] == "REQUESTED"
    assert read_lock(first_lock["id"])["granted_reservation_count"] == 0

    granted = validate_success(api.grant_lock_reservation(
        reservation["id"], make_lock_master_headers(first_lock["id"])))
    assert granted["status"] == "GRANTED"
    assert read_lock(first_lock["id"])["granted_reservation_count"] == 1


def test_tariff_filer_cannot_effectuate_the_filing_it_filed(api):
    """PRD §3.2: "The acting `X-User-ID` must differ from `filed_by_user_id`, or
    the call is refused with `ERR_SEGREGATION_OF_DUTIES` — the analyst who wrote
    the rate may not be the authority who publishes it."
    PRD §3.2: "Filing the draft with the rate bureau moves it `DRAFT → FILED`
    and is the moment the filer's identity is captured: the acting `X-User-ID`
    is written to `filed_by_user_id`, and the filing's `version` increments."

    Design: Corner/rbac/tariff_filer_cannot_effectuate_the_filing_it_filed
    """
    filing = draft_tariff(analyst_user_id="u-1", tariff_code="T-GRAIN-SOD")
    file_tariff(filing["id"], analyst_user_id="u-1")

    validate_error(api.effectuate_tariff_filing(
        filing["id"], make_rate_authority_headers("u-1")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    stored = read_tariff(filing["id"])
    assert stored["status"] == "FILED"
    assert stored.get("effectuated_by_user_id") is None

    effectuated = validate_success(api.effectuate_tariff_filing(
        filing["id"], make_rate_authority_headers("u-2")))
    assert effectuated["status"] == "EFFECTIVE"
    assert effectuated["effectuated_by_user_id"] == "u-2"
    assert effectuated["filed_by_user_id"] == "u-1"
