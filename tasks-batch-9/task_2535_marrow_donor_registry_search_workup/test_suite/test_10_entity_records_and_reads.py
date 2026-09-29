"""Entity records and reads: creation echoes, system fields, defaults,
listing/pagination, path-id and body-FK resolution, and reverse reachability.

Every test builds its own preconditions from an empty database with the logical
UTC clock reading 2026-08-01T00:00:00Z.
"""
from datetime import datetime

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assertions as A,
    constants as C,
    factories as f,
    fixtures,
    make_center_ops_headers,
    make_liaison_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_EPOCH = "2026-08-01T00:00:00Z"


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a comparable datetime."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# The donor rows the design index calls D3: allele-level at every locus, so it
# declares no ambiguous loci at all.
D3_HLA_REGISTRY = {
    "A": ["01:01", "02:01"],
    "B": ["07:02", "15:01"],
    "C": ["07:02", "03:04"],
    "DRB1": ["15:01", "11:01"],
    "DQB1": ["06:02", "02:01"],
}

D2_HLA_REGISTRY = {
    "A": ["01:01", "02:01"],
    "B": ["07:02", "11:01"],
    "C": ["07:02", "07:04"],
    "DRB1": ["15:01", "03:01"],
    "DQB1": ["06", "02"],
}


def test_registry_creation_echoes_inputs_and_seeds_system_fields(api, operations_headers):
    """PRD §3.1: "A `RegistryOperations` operator registers a registry with a `code` of one to sixteen characters drawn from uppercase letters, digits and the hyphen, which must be unique across all registries — a repeat is refused with `ERR_REGISTRY_CODE_ALREADY_EXISTS` — together with a legal `name` of one to one hundred and twenty characters, a `country_code` of exactly two uppercase letters, a `currency_code` of exactly three uppercase letters naming the currency the registry invoices in, and an `fx_rate_to_usd` giving the United States dollar value of one unit of that currency, expressed as a positive number with exactly four decimal places."
    PRD §3.1: "A registry also carries `cooperation_status`, which is one of `ACTIVE`, `SUSPENDED` or `TERMINATED` and defaults to `ACTIVE`, and `cooperation_tier`, an integer from 1 to 3 recording the partner service tier that feeds the ranking calculation."
    PRD §3.1: "The read view of a registry also exposes `donor_count`, the number of donor profiles filed under it."
    PRD §2.5: "`version` is an integer that starts at 1 on creation and increments by one on every mutation of the row, including mutations the server performs on its own initiative inside a cascade."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/entities/registry_creation_echoes_every_input_and_seeds_its_system_fields
    """
    payload = {
        "code": "DKMS-DE",
        "name": "DKMS Germany",
        "country_code": "DE",
        "currency_code": "EUR",
        "fx_rate_to_usd": 1.0850,
        "is_domestic": False,
        "cooperation_tier": 2,
        "ct_response_deadline_hours": 120,
    }

    response = api.create_registry(payload, operations_headers)
    data = validate_success(response, expected_status=201)
    A.assert_registry(data)

    body = response.json()
    assert body["response_type"] == "object", (
        f"a single resource must be wrapped as response_type \"object\", got {body['response_type']!r}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )
    assert body["meta"].get("api_request_timestamp"), "meta.api_request_timestamp must be present"

    # Every declared input echoed back unchanged.
    assert data["code"] == "DKMS-DE"
    assert data["name"] == "DKMS Germany"
    assert data["country_code"] == "DE"
    assert data["currency_code"] == "EUR"
    assert float(data["fx_rate_to_usd"]) == pytest.approx(1.0850, abs=0.00005)
    assert data["is_domestic"] is False
    assert data["cooperation_tier"] == 2
    assert data["ct_response_deadline_hours"] == 120

    # Server-seeded fields.
    assert data["cooperation_status"] == "ACTIVE", (
        "cooperation_status defaults to ACTIVE when the optional input is omitted"
    )
    assert data["donor_count"] == 0, "a brand-new registry has no donor profiles filed under it"
    assert data["version"] == 1, "version starts at 1 on creation"
    assert _instant(data["created_at"]) == _instant(data["updated_at"]), (
        "an unmutated row carries created_at == updated_at"
    )

    reread = validate_success(api.get_registry(data["id"], operations_headers))
    assert reread == data, "the read view must return the identical row the create returned"


def test_patient_read_returns_stored_typing_and_zeroed_case_ledger(api, coordinator_headers):
    """PRD §3.3: "Recipient typing arrives as `hla_typing`, an object with exactly the five keys `A`, `B`, `C`, `DRB1` and `DQB1`, each an array of exactly two allele-level strings in the colon-separated form; recipient typing is never antigen-level, and anything malformed is refused with `ERR_INVALID_REQUEST`."
    PRD §3.3: "At creation the server stamps `coordinating_user_id` from `X-User-ID`, sets `conditioning_status` to `NOT_SCHEDULED` with `conditioning_start_date` null, `conditioning_aborted_reason` null and `committed_cost_cents` at zero."
    PRD §2.1: "the server records it — as `coordinating_user_id` on the `Patient` at patient creation, and as `opened_by_user_id` on the `WorkupCase` at workup open — but never compares it to any entity's `id`."

    Design: Corner/entities/patient_read_returns_the_stored_typing_and_zeroed_case_ledger
    """
    payload = f.create_patient_payload(
        mrn="MRN-0001",
        transplant_center_code="TC-01",
        country_code="US",
        diagnosis_code="AML",
        urgency_tier="HIGH",
        weight_kg=70.0,
        cmv_status="POSITIVE",
        case_budget_cents=5_000_000,
    )
    created = validate_success(api.create_patient(payload, coordinator_headers), 201)

    data = validate_success(api.get_patient(created["id"], coordinator_headers))
    A.assert_patient(data)

    A.assert_hla_typing_object(data["hla_typing"], "patient.hla_typing")
    for locus, alleles in payload["hla_typing"].items():
        assert sorted(data["hla_typing"][locus]) == sorted(alleles), (
            f"the stored typing must hold the submitted alleles at locus {locus}: "
            f"expected {alleles}, got {data['hla_typing'][locus]}"
        )

    assert data["coordinating_user_id"] == coordinator_headers["X-User-ID"], (
        "coordinating_user_id is stamped from X-User-ID at creation, never accepted as input"
    )
    assert data["conditioning_status"] == "NOT_SCHEDULED"
    assert data["conditioning_start_date"] is None
    assert data["conditioning_aborted_reason"] is None
    assert data["committed_cost_cents"] == 0, "a patient with no claims has committed nothing"
    assert data["case_budget_cents"] == 5_000_000
    assert float(data["weight_kg"]) == pytest.approx(70.0, abs=0.05)
    assert data["urgency_tier"] == "HIGH"
    assert data["version"] == 1


def test_donor_listing_pages_in_created_at_order_with_filtered_total_count(api, operations_headers):
    """PRD §2.3: "Unless a specific list endpoint documents a different ordering, list results are sorted by `created_at` ascending."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filter before paging and `has_more` indicates whether rows remain beyond the returned page."
    PRD §2.3: "The `limit` parameter caps the number of rows returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100."
    PRD §2.3: "The `offset` parameter is the number of rows to skip and defaults to 0; its minimum accepted value is 0."
    PRD §3.2: "Donor profiles can be listed and filtered by home registry through `registry_id` and by availability through `availability_status`, and each donor's calendar windows can be listed with optional filters on `status` and on `reason`."
    PRD §2.10: "`Registry.donor_count` is the count of donor profiles whose `registry_id` is that registry, counted regardless of their `availability_status`."

    Design: Corner/entities/donor_listing_orders_by_created_at_and_reports_total_count_and_has_more
    """
    domestic = fixtures.create_registry(code="NMDP-US")
    international = fixtures.create_international_registry(code="DKMS-DE")

    # The clock moves between registrations so created_at strictly increases and
    # the declared created_at ascending ordering is observable.
    d1 = fixtures.create_donor(domestic["id"], donor_code="D-0001", age_years=27)
    fixtures.set_clock("2026-08-02T00:00:00Z")
    d3 = fixtures.create_donor(
        domestic["id"],
        donor_code="D-0003",
        age_years=55,
        sex="M",
        weight_kg=91.0,
        cmv_status="POSITIVE",
        hla_typing_registry=D3_HLA_REGISTRY,
        consented_methods=["PBSC"],
        ambiguous_loci=[],
    )
    fixtures.set_clock("2026-08-03T00:00:00Z")
    d2 = fixtures.create_donor(
        international["id"],
        donor_code="D-0002",
        age_years=41,
        sex="M",
        weight_kg=84.0,
        cmv_status="NEGATIVE",
        hla_typing_registry=D2_HLA_REGISTRY,
        consented_methods=["PBSC"],
        ambiguous_loci=["DQB1"],
        prior_donation_count=1,
        availability_status="WITHDRAWN",
    )

    page1, meta1 = validate_paginated(api.list_donors(operations_headers, {"limit": 2, "offset": 0}))
    assert [row["id"] for row in page1] == [d1["id"], d3["id"]], (
        "the first page must carry the two earliest-created donors in created_at ascending order"
    )
    assert meta1["limit"] == 2 and meta1["offset"] == 0
    assert meta1["total_count"] == 3, "total_count counts every matching row before paging"
    assert meta1["has_more"] is True, "one row remains beyond the first page of two"

    page2, meta2 = validate_paginated(api.list_donors(operations_headers, {"limit": 2, "offset": 2}))
    assert [row["id"] for row in page2] == [d2["id"]]
    assert meta2["offset"] == 2 and meta2["total_count"] == 3
    assert meta2["has_more"] is False, "no rows remain beyond the second page"

    filtered, meta3 = validate_paginated(
        api.list_donors(
            operations_headers,
            {"registry_id": domestic["id"], "availability_status": "AVAILABLE"},
        )
    )
    assert [row["id"] for row in filtered] == [d1["id"], d3["id"]], (
        "the WITHDRAWN international donor is excluded by both filters"
    )
    assert meta3["total_count"] == 2, "total_count reflects the filter, not the whole table"
    assert meta3["has_more"] is False

    unpaged, meta4 = validate_paginated(api.list_donors(operations_headers))
    assert meta4["limit"] == C.DEFAULT_LIMIT, "an omitted limit defaults to 10"
    assert meta4["offset"] == 0, "an omitted offset defaults to 0"
    assert [row["id"] for row in unpaged] == [d1["id"], d3["id"], d2["id"]]
    assert meta4["total_count"] == 3 and meta4["has_more"] is False

    assert fixtures.read_donor(d1["id"])["registry_id"] == domestic["id"]
    assert validate_success(api.get_registry(domestic["id"], operations_headers))["donor_count"] == 2
    assert validate_success(
        api.get_registry(international["id"], operations_headers)
    )["donor_count"] == 1, "donor_count counts the withdrawn donor too"


ABSENT_PATH_ID_CASES = [
    (
        "registry",
        ApiErrorId.ERR_REGISTRY_NOT_FOUND,
        lambda api: api.get_registry(NON_EXISTENT_UUID, TEST_USERS["operations_headers"]),
    ),
    (
        "collection_center",
        ApiErrorId.ERR_COLLECTION_CENTER_NOT_FOUND,
        lambda api: api.get_collection_center(NON_EXISTENT_UUID, TEST_USERS["operations_headers"]),
    ),
    (
        "patient",
        ApiErrorId.ERR_PATIENT_NOT_FOUND,
        lambda api: api.get_patient(NON_EXISTENT_UUID, TEST_USERS["coordinator_headers"]),
    ),
    (
        "search_request",
        ApiErrorId.ERR_SEARCH_REQUEST_NOT_FOUND,
        lambda api: api.get_search_request(NON_EXISTENT_UUID, TEST_USERS["coordinator_headers"]),
    ),
    (
        "donor",
        ApiErrorId.ERR_DONOR_NOT_FOUND,
        lambda api: api.get_donor(NON_EXISTENT_UUID, TEST_USERS["operations_headers"]),
    ),
    (
        "match_candidate",
        ApiErrorId.ERR_MATCH_CANDIDATE_NOT_FOUND,
        lambda api: api.get_match_candidate(NON_EXISTENT_UUID, TEST_USERS["coordinator_headers"]),
    ),
    (
        "match_candidate_typing_requests",
        ApiErrorId.ERR_MATCH_CANDIDATE_NOT_FOUND,
        lambda api: api.list_typing_requests(NON_EXISTENT_UUID, TEST_USERS["coordinator_headers"]),
    ),
    (
        "typing_request_response",
        ApiErrorId.ERR_TYPING_REQUEST_NOT_FOUND,
        lambda api: api.respond_typing_request(
            NON_EXISTENT_UUID,
            f.typing_response_payload(),
            make_liaison_headers(NON_EXISTENT_UUID),
        ),
    ),
    (
        "workup_case",
        ApiErrorId.ERR_WORKUP_CASE_NOT_FOUND,
        lambda api: api.get_workup_case(NON_EXISTENT_UUID, TEST_USERS["physician_headers"]),
    ),
    (
        "clearance_item",
        ApiErrorId.ERR_CLEARANCE_ITEM_NOT_FOUND,
        lambda api: api.get_clearance_item(NON_EXISTENT_UUID, TEST_USERS["physician_headers"]),
    ),
    (
        "collection_booking",
        ApiErrorId.ERR_BOOKING_NOT_FOUND,
        lambda api: api.get_collection_booking(
            NON_EXISTENT_UUID, make_center_ops_headers(NON_EXISTENT_UUID)
        ),
    ),
    (
        "shipment",
        ApiErrorId.ERR_SHIPMENT_NOT_FOUND,
        lambda api: api.get_shipment(NON_EXISTENT_UUID, TEST_USERS["operations_headers"]),
    ),
    (
        "reimbursement_claim",
        ApiErrorId.ERR_CLAIM_NOT_FOUND,
        lambda api: api.get_reimbursement_claim(NON_EXISTENT_UUID, TEST_USERS["operations_headers"]),
    ),
]


@pytest.mark.parametrize(
    "collection,expected_error,call",
    ABSENT_PATH_ID_CASES,
    ids=[case[0] for case in ABSENT_PATH_ID_CASES],
)
def test_absent_path_identifier_returns_the_entity_specific_not_found_error(
    api, collection, expected_error, call
):
    """PRD §2.8: "Identifiers that appear in a path are resolved strictly left to right, and the first identifier that does not resolve decides the response with HTTP 404. An unknown registry identifier yields `ERR_REGISTRY_NOT_FOUND`; an unknown collection centre identifier yields `ERR_COLLECTION_CENTER_NOT_FOUND`; an unknown patient identifier yields `ERR_PATIENT_NOT_FOUND`; an unknown search request identifier yields `ERR_SEARCH_REQUEST_NOT_FOUND`; an unknown donor identifier yields `ERR_DONOR_NOT_FOUND`; an unknown match candidate identifier yields `ERR_MATCH_CANDIDATE_NOT_FOUND`; an unknown confirmatory typing request identifier yields `ERR_TYPING_REQUEST_NOT_FOUND`; an unknown workup case identifier yields `ERR_WORKUP_CASE_NOT_FOUND`; an unknown clearance item identifier yields `ERR_CLEARANCE_ITEM_NOT_FOUND`; an unknown collection booking identifier yields `ERR_BOOKING_NOT_FOUND`; an unknown product shipment identifier yields `ERR_SHIPMENT_NOT_FOUND`; and an unknown reimbursement claim identifier yields `ERR_CLAIM_NOT_FOUND`."
    PRD §2.9: "The fifth rung resolves path identifiers left to right, and the sixth resolves body foreign keys in declaration order, both as described in §2.8."
    PRD §2.9: "Rungs seven through ten are the scope and duty checks, in this order: patient ownership for a `TransplantCoordinator` (`ERR_PATIENT_NOT_OWNED`), registry scope for a `DonorRegistryLiaison` (`ERR_REGISTRY_SCOPE_VIOLATION`), collection-centre scope for a `CollectionCenterOps` operator (`ERR_CENTER_SCOPE_VIOLATION`), and finally the two-physician rule on the collection-method decision (`ERR_SEGREGATION_OF_DUTIES`)."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/entities/absent_path_ids_return_the_entity_specific_not_found_error
    """
    response = call(api)
    error = validate_error(response, expected_error.value)

    body = response.json()
    assert body["response_type"] == "error", (
        f"an error response must carry response_type \"error\", got {body['response_type']!r}"
    )
    assert error["message"], f"the {collection} 404 must carry a human-readable message"


PATIENT_REQUIRED_FIELDS = [
    "mrn",
    "transplant_center_code",
    "country_code",
    "diagnosis_code",
    "urgency_tier",
    "weight_kg",
    "cmv_status",
    "hla_typing",
    "case_budget_cents",
]


@pytest.mark.parametrize("omitted_field", PATIENT_REQUIRED_FIELDS)
def test_patient_creation_missing_required_field_returns_invalid_request(
    api, coordinator_headers, omitted_field
):
    """PRD §2.9: "The third rung is body schema conformance on every write endpoint (`ERR_INVALID_REQUEST`): required fields present, types correct, enum values in range, numeric bounds respected, HLA typing objects carrying all five loci with exactly two strings each, and a non-empty consented-methods list."
    PRD §3.3: "A `TransplantCoordinator` registers the recipient with an `mrn` of one to thirty-two characters that must be unique across all patients — a repeat is refused with `ERR_MRN_ALREADY_EXISTS` — a `transplant_center_code` of one to sixteen characters naming the owning centre as a free-form label with no entity behind it, a `country_code` of exactly two uppercase letters, and a `diagnosis_code` of one to sixteen characters."

    Design: Corner/entities/patient_creation_missing_required_fields_returns_invalid_request
    """
    payload = f.create_patient_payload(mrn="MRN-0001")
    payload.pop(omitted_field)

    validate_error(
        api.create_patient(payload, coordinator_headers), ApiErrorId.ERR_INVALID_REQUEST.value
    )

    # The rejected call wrote nothing, so it consumed no mrn uniqueness slot.
    recovered = validate_success(
        api.create_patient(f.create_patient_payload(mrn="MRN-0001"), coordinator_headers), 201
    )
    assert recovered["mrn"] == "MRN-0001"


def test_patient_creation_with_a_four_locus_typing_object_returns_invalid_request(
    api, coordinator_headers
):
    """PRD §3.3: "Recipient typing arrives as `hla_typing`, an object with exactly the five keys `A`, `B`, `C`, `DRB1` and `DQB1`, each an array of exactly two allele-level strings in the colon-separated form; recipient typing is never antigen-level, and anything malformed is refused with `ERR_INVALID_REQUEST`."
    PRD §2.9: "The third rung is body schema conformance on every write endpoint (`ERR_INVALID_REQUEST`): required fields present, types correct, enum values in range, numeric bounds respected, HLA typing objects carrying all five loci with exactly two strings each, and a non-empty consented-methods list."

    Design: Corner/entities/patient_creation_missing_required_fields_returns_invalid_request
    """
    four_loci = {
        "A": ["01:01", "02:01"],
        "B": ["07:02", "08:01"],
        "C": ["07:02", "07:04"],
        "DRB1": ["15:01", "03:01"],
    }
    payload = f.create_patient_payload(mrn="MRN-0001", hla_typing=four_loci)

    validate_error(
        api.create_patient(payload, coordinator_headers), ApiErrorId.ERR_INVALID_REQUEST.value
    )

    recovered = validate_success(
        api.create_patient(f.create_patient_payload(mrn="MRN-0001"), coordinator_headers), 201
    )
    assert recovered["mrn"] == "MRN-0001", (
        "the rejected four-locus call created no Patient and consumed no mrn"
    )


def test_omitted_optional_inputs_fall_back_to_declared_defaults(
    api, operations_headers, coordinator_headers
):
    """PRD §3.1: "A registry also carries `cooperation_status`, which is one of `ACTIVE`, `SUSPENDED` or `TERMINATED` and defaults to `ACTIVE`, and `cooperation_tier`, an integer from 1 to 3 recording the partner service tier that feeds the ranking calculation."
    PRD §3.2: "Real registries, however, frequently hold only antigen-level resolution at some loci, and the donor payload declares that honestly through `ambiguous_loci`, an array that must be a duplicate-free subset of `A`, `B`, `C`, `DRB1` and `DQB1` and that defaults to empty."
    PRD §3.2: "`prior_donation_count`, an integer from 0 to 5 defaulting to 0, counts completed prior donations, and each prior donation penalises the volunteer's domestic logistics factor in the ranking calculation, because the programme prefers to spread the donation burden."
    PRD §3.2: "A donor profile also accepts `availability_status` at registration, defaulting to `AVAILABLE`; the four legal values are `AVAILABLE`, `TEMPORARILY_DEFERRED`, `PERMANENTLY_DEFERRED` and `WITHDRAWN`, and after registration this field is mutated only by system transitions — a non-availability answer to a typing request, a screening deferral, an adverse event, or the lapse of a deferral."
    PRD §3.3: "The coordinator supplies `patient_id`, a `search_scope` of either `DOMESTIC_ONLY` or `DOMESTIC_AND_INTERNATIONAL`, and optionally `min_preliminary_score` — a two-decimal number in the closed range 0.00 to 100.00 that defaults to 60.00 and acts as the floor a donor must reach to be worth materialising."
    PRD §3.3: "The donor's preliminary match score must be greater than or equal to the search's `min_preliminary_score` — a donor whose score exactly equals the floor is admitted."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    registry_payload = f.create_registry_payload(code="NMDP-US")
    assert "cooperation_status" not in registry_payload, "the default is only observable if omitted"
    registry = validate_success(api.create_registry(registry_payload, operations_headers), 201)
    assert registry["cooperation_status"] == "ACTIVE"

    donor_payload = f.create_donor_payload(
        registry["id"],
        donor_code="D-0003",
        age_years=55,
        sex="M",
        weight_kg=91.0,
        cmv_status="POSITIVE",
        hla_typing_registry=D3_HLA_REGISTRY,
        consented_methods=["PBSC"],
    )
    donor_payload.pop("ambiguous_loci")
    donor_payload.pop("prior_donation_count")
    assert "availability_status" not in donor_payload
    donor = validate_success(
        api.create_donor(donor_payload, make_liaison_headers(registry["id"])), 201
    )
    assert donor["ambiguous_loci"] == [], "ambiguous_loci defaults to empty"
    assert donor["prior_donation_count"] == 0
    assert donor["availability_status"] == "AVAILABLE"

    patient = validate_success(
        api.create_patient(f.create_patient_payload(mrn="MRN-0001"), coordinator_headers), 201
    )

    search_payload = f.create_search_request_payload(patient["id"], search_scope="DOMESTIC_ONLY")
    assert "min_preliminary_score" not in search_payload
    search = validate_success(api.create_search_request(search_payload, coordinator_headers), 201)
    A.assert_search_request(search)

    assert float(search["min_preliminary_score"]) == pytest.approx(
        C.MIN_PRELIM_SCORE_DEFAULT, abs=0.005
    ), "an omitted min_preliminary_score defaults to 60.00"
    assert search["status"] == "SEARCHING"
    assert search["match_pool_size"] == 1, (
        "the defaulted 60.00 floor is load-bearing: the donor's 69.17 preliminary score clears it"
    )

    candidates = fixtures.list_candidates(search["id"], headers=coordinator_headers)
    assert len(candidates) == 1
    candidate = candidates[0]
    A.assert_match_candidate(candidate)
    assert float(candidate["preliminary_score"]) == pytest.approx(69.17, abs=0.005)
    assert candidate["rank_position"] == 1
    assert candidate["candidate_role"] == "PRIMARY"
    assert candidate["status"] == "IDENTIFIED"


def test_typing_request_computes_attempt_number_and_frozen_deadline(api):
    """PRD §3.4: "The created request records `match_candidate_id`, an `attempt_number` equal to the candidate's `ct_attempt_count` after the increment — so 1 or 2 — a `requested_at` stamped from the logical clock, and a computed `deadline_at`."
    PRD §3.4: "It opens in `status` `REQUESTED` with `responded_at`, `reported_hla_typing`, `reported_match_grade`, `donor_available_flag` and `expired_by_sweep_at` all null, and its four legal states are `REQUESTED`, `RESPONDED`, `EXPIRED` and `CANCELLED`, the last three all terminal."
    PRD §3.4: "The deadline is computed once, at request time, and then frozen. It begins at `requested_at` plus the donor registry's contractual `ct_response_deadline_hours`."
    PRD §3.4: "Raising a confirmatory-typing request is a coordinator action on a specific candidate, and the only body field it accepts is an optional `priority_flag` defaulting to false, which marks the request as clinically urgent."
    PRD §3.4: "A successful request raises the candidate's `ct_attempt_count` by one and moves the candidate `IDENTIFIED → TYPING_REQUESTED`, or `TYPING_EXPIRED → TYPING_REQUESTED` on the second attempt, which is exactly why the candidate's history is cyclic: `TYPING_REQUESTED → TYPING_EXPIRED → TYPING_REQUESTED`, bounded to two attempts in total."
    PRD §3.4: "When the candidate carrying the request is the search's `PRIMARY`, the search itself advances `SEARCHING → PRIMARY_ENGAGED`; when the candidate is a newly promoted primary, the same act moves the search `BACKUP_REQUIRED → PRIMARY_ENGAGED`, and that cycle may repeat once for each available backup."

    Design: Corner/entities/typing_request_fields_are_computed_from_the_registry_deadline_policy
    """
    ctx = fixtures.setup_primary_candidate(
        with_center=False,
        registry_overrides={"code": "NMDP-US", "ct_response_deadline_hours": 168},
    )
    assert ctx["candidate"]["ct_attempt_count"] == 0

    # The body carries nothing at all, so priority_flag must fall back to false.
    data = validate_success(
        api.create_typing_request(ctx["candidate_id"], {}, ctx["coordinator_headers"]), 201
    )
    A.assert_typing_request(data)

    assert data["match_candidate_id"] == ctx["candidate_id"]
    assert data["attempt_number"] == 1
    assert data["status"] == "REQUESTED"
    assert data["priority_flag"] is False, "an omitted priority_flag defaults to false"
    assert _instant(data["requested_at"]) == _instant(CLOCK_EPOCH), (
        "requested_at is stamped from the logical clock, which still reads its initial instant"
    )
    assert _instant(data["deadline_at"]) == _instant("2026-08-08T00:00:00Z"), (
        "the deadline is requested_at plus the domestic registry's 168 contractual hours, "
        "with no international grace and no priority reduction"
    )
    for field in (
        "responded_at",
        "reported_hla_typing",
        "reported_match_grade",
        "donor_available_flag",
        "expired_by_sweep_at",
    ):
        assert data[field] is None, f"{field} must open null on a freshly raised request"

    candidate = fixtures.read_candidate(ctx["candidate_id"], ctx["coordinator_headers"])
    assert candidate["ct_attempt_count"] == 1
    assert candidate["status"] == "TYPING_REQUESTED"

    search = fixtures.read_search(ctx["search_id"], ctx["coordinator_headers"])
    assert search["status"] == "PRIMARY_ENGAGED"


def test_system_fields_are_stamped_from_the_logical_clock(api, operations_headers):
    """PRD §2.4: "Nothing in this system reads wall-clock time. Every deadline, expiry, viability, calendar and date comparison reads a server-held logical UTC clock, which before any call has been made reads exactly `2026-08-01T00:00:00Z` and never falls back to the host's real time."
    PRD §2.4: "A `RegistryOperations` operator may move that clock forward or backward through a test-driving capability at `POST /_clock/set_current_utc`, supplying the target instant as `to_iso8601`; the response reports the newly effective instant as `current_utc` and the instant it replaced as `previous_utc`."
    PRD §2.5: "`id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the row was first written."
    PRD §3.1: "A newly registered centre starts with `committed_slot_minutes` at zero."

    Design: Corner/entities/system_fields_are_stamped_from_the_logical_clock_not_from_input
    """
    payload = f.create_collection_center_payload(
        name="Metro Apheresis Center", country_code="US", concurrent_collection_capacity=1
    )

    first = validate_success(api.create_collection_center(dict(payload), operations_headers), 201)
    A.assert_collection_center(first)
    assert _instant(first["created_at"]) == _instant(CLOCK_EPOCH)
    assert _instant(first["updated_at"]) == _instant(CLOCK_EPOCH)
    assert first["version"] == 1
    assert first["committed_slot_minutes"] == 0

    clock = validate_success(api.set_clock("2026-08-15T12:34:56Z", operations_headers))
    assert _instant(clock["current_utc"]) == _instant("2026-08-15T12:34:56Z")
    assert _instant(clock["previous_utc"]) == _instant(CLOCK_EPOCH)

    second = validate_success(api.create_collection_center(dict(payload), operations_headers), 201)
    A.assert_collection_center(second)
    assert _instant(second["created_at"]) == _instant("2026-08-15T12:34:56Z"), (
        "created_at comes from the logical clock, never from the host's real time"
    )
    assert _instant(second["updated_at"]) == _instant(second["created_at"])
    assert second["version"] == 1
    assert second["committed_slot_minutes"] == 0

    assert first["id"] != second["id"], (
        "two byte-identical payloads mint two distinct ids: the centre's name is not an identity"
    )


INVALID_DONOR_OVERRIDES = [
    ("age_below_17", {"age_years": 16}),
    ("age_above_75", {"age_years": 76}),
    ("prior_donation_count_above_5", {"prior_donation_count": 6}),
    ("sex_not_M_or_F", {"sex": "X"}),
    ("cmv_status_unknown", {"cmv_status": "UNKNOWN_STATUS"}),
    ("consented_methods_unknown_value", {"consented_methods": ["CORD_BLOOD"]}),
    ("consented_methods_empty", {"consented_methods": []}),
    ("consented_methods_duplicated", {"consented_methods": ["PBSC", "PBSC"]}),
    ("ambiguous_loci_duplicated", {"ambiguous_loci": ["A", "A"]}),
    ("ambiguous_loci_unknown_locus", {"ambiguous_loci": ["Z"]}),
]


@pytest.mark.parametrize(
    "label,overrides", INVALID_DONOR_OVERRIDES, ids=[case[0] for case in INVALID_DONOR_OVERRIDES]
)
def test_donor_creation_rejects_out_of_range_numbers_and_unknown_enum_values(
    api, label, overrides
):
    """PRD §2.9: "The third rung is body schema conformance on every write endpoint (`ERR_INVALID_REQUEST`): required fields present, types correct, enum values in range, numeric bounds respected, HLA typing objects carrying all five loci with exactly two strings each, and a non-empty consented-methods list."
    PRD §3.2: "Registration accepts ages from 17 through 75 inclusive — registries do enrol volunteers slightly outside the collection age band, and rejecting them at enrolment would corrupt the registry's own records — but the search eligibility filter of §3.3 admits only volunteers aged 18 through 60 inclusive, so a 17-year-old or a 61-year-old is a perfectly valid profile that will never be materialised into a candidate."
    PRD §3.2: "The clinical payload comprises `age_years` as a whole number, `sex` as either `M` or `F`, `weight_kg` as a positive number with one decimal place, and `cmv_status` as either `NEGATIVE` or `POSITIVE`."
    PRD §3.2: "`consented_methods` is a non-empty, duplicate-free subset of `PBSC` and `MARROW` recording the collection methods the volunteer agreed to at enrolment; a volunteer who consented only to peripheral blood stem cell donation can never be harvested by marrow aspiration, and the collection-method decision of §3.6 enforces that."
    PRD §3.2: "Real registries, however, frequently hold only antigen-level resolution at some loci, and the donor payload declares that honestly through `ambiguous_loci`, an array that must be a duplicate-free subset of `A`, `B`, `C`, `DRB1` and `DQB1` and that defaults to empty."
    PRD §3.2: "`prior_donation_count`, an integer from 0 to 5 defaulting to 0, counts completed prior donations, and each prior donation penalises the volunteer's domestic logistics factor in the ranking calculation, because the programme prefers to spread the donation burden."

    Design: Corner/entities/donor_creation_rejects_out_of_range_numbers_and_unknown_enum_values
    """
    registry = fixtures.create_registry(code="NMDP-US")
    liaison = make_liaison_headers(registry["id"])

    base = {
        "donor_code": "D-BAD",
        "age_years": 30,
        "hla_typing_registry": f.DONOR_HLA_FULL_ALLELE,
        "ambiguous_loci": [],
    }
    base.update(overrides)
    payload = f.create_donor_payload(registry["id"], **base)

    validate_error(api.create_donor(payload, liaison), ApiErrorId.ERR_INVALID_REQUEST.value)

    assert validate_success(
        api.get_registry(registry["id"], TEST_USERS["operations_headers"])
    )["donor_count"] == 0, f"the rejected {label} call must have created no donor profile"


def test_donor_registration_accepts_the_inclusive_age_boundaries(api, operations_headers):
    """PRD §3.2: "Registration accepts ages from 17 through 75 inclusive — registries do enrol volunteers slightly outside the collection age band, and rejecting them at enrolment would corrupt the registry's own records — but the search eligibility filter of §3.3 admits only volunteers aged 18 through 60 inclusive, so a 17-year-old or a 61-year-old is a perfectly valid profile that will never be materialised into a candidate."
    PRD §3.2: "Newly registered donors start with `blocked_day_count` and `adverse_event_count` at zero, with `deferral_until` null and `last_followup_at` null, and each registration raises the owning registry's `donor_count` by one."

    Design: Corner/entities/donor_creation_rejects_out_of_range_numbers_and_unknown_enum_values
    """
    registry = fixtures.create_registry(code="NMDP-US")
    liaison = make_liaison_headers(registry["id"])

    for donor_code, age_years in (("D-AGE-17", 17), ("D-AGE-75", 75)):
        payload = f.create_donor_payload(
            registry["id"],
            donor_code=donor_code,
            age_years=age_years,
            hla_typing_registry=f.DONOR_HLA_FULL_ALLELE,
            ambiguous_loci=[],
        )
        data = validate_success(api.create_donor(payload, liaison), 201)
        A.assert_donor_profile(data)
        assert data["age_years"] == age_years, (
            f"age {age_years} sits exactly on an inclusive registration boundary"
        )
        assert data["blocked_day_count"] == 0
        assert data["adverse_event_count"] == 0
        assert data["deferral_until"] is None
        assert data["last_followup_at"] is None

    assert validate_success(api.get_registry(registry["id"], operations_headers))["donor_count"] == 2


def test_follow_up_rows_are_append_only_and_carry_no_version(api, physician_headers):
    """PRD §2.5: "There is one deliberate exception. `DonorFollowUp` rows are immutable append-only records: they carry only `id` and `created_at`. A follow-up row has no `updated_at` field and no `version` field at all, and neither field should be present in its response payload."
    PRD §3.9: "Each filed row stamps `reported_at` from the logical clock and refreshes the donor's `last_followup_at` to the latest `reported_at` on record. An `ADVERSE_EVENT` row additionally raises the donor's `adverse_event_count` by one."
    PRD §3.9: "When an `ADVERSE_EVENT` row carries a `severity_grade` of 4 or higher, the row's `triggered_permanent_deferral` is recorded as true — it is false on every other row — and the donor's `availability_status` moves to `PERMANENTLY_DEFERRED`, whether the donor was `AVAILABLE` or already `TEMPORARILY_DEFERRED` at the time."
    PRD §2.3: "Unless a specific list endpoint documents a different ordering, list results are sorted by `created_at` ascending."

    Design: Corner/entities/follow_up_rows_are_immutable_and_expose_no_version
    """
    registry = fixtures.create_registry(code="NMDP-US")
    liaison = make_liaison_headers(registry["id"])
    donor = fixtures.create_donor(registry["id"], donor_code="D-0001", age_years=27)

    first = validate_success(
        api.create_follow_up(
            donor["id"],
            f.create_follow_up_payload(
                "DAY_7_CONTACT", 0, description="Routine day-7 call"
            ),
            liaison,
        ),
        201,
    )
    A.assert_donor_follow_up(first)
    assert _instant(first["reported_at"]) == _instant(CLOCK_EPOCH)
    assert first["triggered_permanent_deferral"] is False

    fixtures.set_clock("2026-08-30T09:00:00Z")

    second = validate_success(
        api.create_follow_up(
            donor["id"],
            f.create_follow_up_payload(
                "ADVERSE_EVENT", 2, description="Transient bone pain"
            ),
            physician_headers,
        ),
        201,
    )
    A.assert_donor_follow_up(second)
    assert _instant(second["reported_at"]) == _instant("2026-08-30T09:00:00Z")
    assert second["triggered_permanent_deferral"] is False, (
        "grade 2 is below the grade-4 permanent-deferral threshold"
    )

    rows, meta = validate_paginated(api.list_follow_ups(donor["id"], liaison))
    assert meta["total_count"] == 2, "the second filing appended a row rather than overwriting one"
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert rows[0]["event_type"] == "DAY_7_CONTACT", "the earlier row is untouched"
    assert rows[0]["severity_grade"] == 0
    assert rows[0]["description"] == "Routine day-7 call"
    for row in rows:
        assert "updated_at" not in row, "a listed follow-up row must expose no updated_at"
        assert "version" not in row, "a listed follow-up row must expose no version"

    refreshed = fixtures.read_donor(donor["id"])
    assert refreshed["availability_status"] == "AVAILABLE"
    assert refreshed["adverse_event_count"] == 1
    assert _instant(refreshed["last_followup_at"]) == _instant("2026-08-30T09:00:00Z")


def test_body_foreign_keys_resolve_before_version_and_ownership_rules(
    api, operations_headers, coordinator_headers
):
    """PRD §2.8: "Foreign keys supplied in a request body are resolved after every path identifier, and in the order in which the endpoint declares them. Opening a search resolves `patient_id`, and an unknown value yields `ERR_PATIENT_NOT_FOUND`. Creating a collection booking resolves `workup_case_id` first and `collection_center_id` second, so a request naming a non-existent case and a non-existent centre reports `ERR_WORKUP_CASE_NOT_FOUND` rather than `ERR_COLLECTION_CENTER_NOT_FOUND`."
    PRD §2.9: "The two version guards of §2.7 sit immediately below the state gates and above every safety, temporal and constraint rule: `ERR_STALE_WORKUP_VERSION` on booking creation, then `ERR_STALE_PATIENT_VERSION` on a conditioning action."
    PRD §2.9: "Rungs seven through ten are the scope and duty checks, in this order: patient ownership for a `TransplantCoordinator` (`ERR_PATIENT_NOT_OWNED`), registry scope for a `DonorRegistryLiaison` (`ERR_REGISTRY_SCOPE_VIOLATION`), collection-centre scope for a `CollectionCenterOps` operator (`ERR_CENTER_SCOPE_VIOLATION`), and finally the two-physician rule on the collection-method decision (`ERR_SEGREGATION_OF_DUTIES`)."
    PRD §2.10: "`CollectionCenter.committed_slot_minutes` is the sum of `duration_minutes` over that centre's bookings whose `status` is `HELD`, `CONFIRMED` or `COMPLETED`."

    Design: Corner/entities/body_foreign_keys_are_resolved_before_any_state_rule_runs
    """
    center = fixtures.create_collection_center(name="Metro Apheresis Center")
    center_ops = make_center_ops_headers(center["id"])

    # A version value read from the centre row: real, but belonging to no workup
    # case, so the stale-version guard would fire if it were ever reached.
    absent_case = f.create_booking_payload(
        NON_EXISTENT_UUID,
        center["id"],
        C.TIMELINE["BOOKING_START_AT"],
        center["version"],
    )
    validate_error(
        api.create_collection_booking(absent_case, center_ops),
        ApiErrorId.ERR_WORKUP_CASE_NOT_FOUND.value,
    )

    both_absent = f.create_booking_payload(
        NON_EXISTENT_UUID,
        NON_EXISTENT_UUID,
        C.TIMELINE["BOOKING_START_AT"],
        1,
    )
    validate_error(
        api.create_collection_booking(both_absent, make_center_ops_headers(NON_EXISTENT_UUID)),
        ApiErrorId.ERR_WORKUP_CASE_NOT_FOUND.value,
    )

    validate_error(
        api.create_search_request(
            f.create_search_request_payload(NON_EXISTENT_UUID), coordinator_headers
        ),
        ApiErrorId.ERR_PATIENT_NOT_FOUND.value,
    )

    reread = validate_success(api.get_collection_center(center["id"], operations_headers))
    assert reread["committed_slot_minutes"] == 0, "no booking row was created by any rejected call"

    empty, meta = validate_paginated(api.list_collection_bookings(operations_headers))
    assert empty == [] and meta["total_count"] == 0


def test_every_child_is_reachable_from_its_parent_through_a_declared_read(
    api, coordinator_headers, physician_headers, operations_headers
):
    """PRD §2.8: "Where a nested read path does exist, it exists purely as a reverse-reachability channel — a way to list the children a cascade created — and never as a statement of business identity."
    PRD §3.3: "Candidates can be listed and filtered by `search_request_id`, by `donor_id`, by `candidate_role` and by `status`, and a patient's searches are separately listable, which is how a coordinator reaches a search it did not record the identifier of."
    PRD §3.4: "A candidate's typing requests are listable with an optional `status` filter, which is how an operator inspects both attempts of a twice-requested candidate."
    PRD §3.6: "The case's three clearance items are listable in their creation order, with the physical examination at index zero, the infectious-disease panel at index one and the consent at index two; a candidate's workup cases are listable with an optional `case_status` filter."
    PRD §3.9: "Claims are listable and filterable by `workup_case_id`, by `patient_id`, by `billing_registry_id` and by `status`."

    Design: Corner/entities/every_child_entity_is_reachable_from_its_parent_through_a_declared_read
    """
    ctx = fixtures.setup_pipeline("workup_open")

    # Walk down from the patient using only declared reads, never a recorded id.
    searches, meta = validate_paginated(
        api.list_patient_search_requests(ctx["patient_id"], coordinator_headers)
    )
    assert meta["total_count"] == 1, "the patient has exactly one recorded search"
    assert [row["id"] for row in searches] == [ctx["search_id"]]
    walk_search_id = searches[0]["id"]

    candidates, meta = validate_paginated(
        api.list_match_candidates(
            coordinator_headers,
            params={"search_request_id": walk_search_id, "candidate_role": "PRIMARY"},
        )
    )
    assert meta["total_count"] == 1, "one candidate holds the PRIMARY role"
    assert [row["id"] for row in candidates] == [ctx["candidate_id"]]
    walk_candidate_id = candidates[0]["id"]

    typing_requests, meta = validate_paginated(
        api.list_typing_requests(
            walk_candidate_id, coordinator_headers, params={"status": "RESPONDED"}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in typing_requests] == [ctx["typing_request_id"]]

    cases, meta = validate_paginated(
        api.list_workup_cases(
            walk_candidate_id, coordinator_headers, params={"case_status": "OPEN"}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in cases] == [ctx["workup_case_id"]]
    walk_case_id = cases[0]["id"]

    items, meta = validate_paginated(
        api.list_clearance_items(walk_case_id, physician_headers)
    )
    assert meta["total_count"] == 3, "opening the case wrote exactly three clearance items"
    assert [row["item_type"] for row in items] == ["PHYSICAL_EXAM", "IDM_PANEL", "CONSENT"]
    for row in items:
        A.assert_clearance_item(row)
        assert row["workup_case_id"] == walk_case_id
        assert row["result"] == "PENDING"

    claims, meta = validate_paginated(
        api.list_reimbursement_claims(
            operations_headers, params={"workup_case_id": walk_case_id}
        )
    )
    assert meta["total_count"] == 1, "the cascade wrote exactly one claim for the case"
    claim = claims[0]
    A.assert_reimbursement_claim(claim)
    assert claim["workup_case_id"] == walk_case_id
    assert claim["patient_id"] == ctx["patient_id"]
    assert claim["status"] == "PROVISIONAL"
