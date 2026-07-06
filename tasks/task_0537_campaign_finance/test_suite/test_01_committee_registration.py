"""Committee registration, common fields, listing, and immediate consistency."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, ApiErrorId, NO_AUTH_HEADERS,
    create_committee_payload, create_contribution_payload,
    TEST_USERS, make_treasurer_headers,
    set_clock, create_active_committee, add_contribution, add_expenditure,
)

REGULATOR = TEST_USERS["regulator_headers"]
TREASURER = TEST_USERS["treasurer_headers"]
PUBLIC = TEST_USERS["public_headers"]


def test_register_committee_starts_pending_with_zeroed_totals(api):
    """PRD §3.1: "A newly registered committee begins in PENDING with all four derived
    totals zeroed and solvency_status at SOLVENT."
    PRD §2.4: "The id is a server-minted UUID with no type prefix."

    Design: Corner/entities/committee_create_persists_all_fields
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    resp = api.create_committee(create_committee_payload(name="Nu", committee_type="PAC"), TREASURER)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PENDING", f"expected PENDING, got {data['status']}"
    assert data["total_receipts_cents"] == 0
    assert data["total_disbursements_cents"] == 0
    assert data["total_penalties_cents"] == 0
    assert data["cash_on_hand_cents"] == 0
    assert data["solvency_status"] == "SOLVENT"
    assert is_valid_uuid(data["id"]), "id must be a bare UUID with no prefix"


def test_committee_status_and_totals_are_server_set(api):
    """PRD §3.1: "A newly registered committee begins in PENDING with all four derived
    totals zeroed and solvency_status at SOLVENT."
    PRD §2.9: "Each Committee maintains four derived totals that are never supplied by
    clients and are recomputed immediately whenever their inputs change."

    Design: Corner/entities/committee_system_fields_generated
    """
    payload = create_committee_payload(name="Xi", committee_type="PAC")
    payload["status"] = "ACTIVE"          # client-supplied — must be ignored
    payload["total_receipts_cents"] = 999999  # client-supplied — must be ignored
    data = validate_success(api.create_committee(payload, TREASURER), expected_status=201)
    assert data["status"] == "PENDING", "server must ignore client-supplied status"
    assert data["total_receipts_cents"] == 0, "server must ignore client-supplied totals"


def test_committee_list_is_paginated_array_envelope(api):
    """PRD §2.3: "The meta object of a list response carries limit, offset, total_count,
    and has_more."

    Design: Corner/entities/committee_list_pagination
    """
    validate_success(api.create_committee(create_committee_payload(name="C1"), TREASURER), expected_status=201)
    validate_success(api.create_committee(create_committee_payload(name="C2"), TREASURER), expected_status=201)
    data, meta = validate_paginated(api.list_committees(PUBLIC, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] >= 2, f"expected total_count >= 2, got {meta['total_count']}"
    assert len(data) == 1, "limit=1 must return a single item"
    assert meta["has_more"] is True, "with 2+ committees and limit=1, has_more must be true"


def test_individual_contribution_matchable_capped(api):
    """PRD §3.2: "For an INDIVIDUAL source this is the smaller of the contribution's
    amount_cents and a matchable cap of 20000 cents; for every other contributor type it is 0."

    Design: Corner/entities/contribution_computed_matchable
    """
    committee = create_active_committee(api, name="Om", committee_type="PAC")
    con = validate_success(
        api.create_contribution(
            committee["id"],
            create_contribution_payload(contributor_type="INDIVIDUAL", amount_cents=50000),
            make_treasurer_headers(committee["id"]),
        ),
        expected_status=201,
    )
    assert con["matchable_amount_cents"] == 20000, "matchable = min(50000, 20000 cap)"


def test_expenditure_has_no_version_field(api):
    """PRD §2.4: "An Expenditure is immutable after creation and therefore carries only id
    and created_at; it has no updated_at and no version."

    Design: Corner/entities/expenditure_created_has_no_version_field
    """
    committee = create_active_committee(api, name="Pi", committee_type="PAC")
    data = validate_success(
        api.create_expenditure(
            committee["id"],
            {"payee_name": "Vendor", "amount_cents": 10000, "expenditure_date": "2026-02-20T00:00:00Z", "purpose": "print"},
            make_treasurer_headers(committee["id"]),
        ),
        expected_status=201,
    )
    assert is_valid_uuid(data["id"])
    assert "created_at" in data
    assert "version" not in data, "immutable expenditure must not carry a version field"
    assert "updated_at" not in data, "immutable expenditure must not carry updated_at"


def test_get_missing_committee_returns_not_found(api):
    """PRD §2.10: Each resource type has its own not-found error ... "ERR_COMMITTEE_NOT_FOUND".

    Design: Corner/entities/committee_get_not_found_returns_404
    """
    resp = api.get_committee("00000000-0000-0000-0000-000000000000", PUBLIC)
    validate_error(resp, ApiErrorId.ERR_COMMITTEE_NOT_FOUND.value)


def test_register_committee_missing_committee_type_rejected(api):
    """PRD §2.7: "Body validation — required body fields are present, correctly typed, and
    any enum value is a valid member; otherwise ERR_VALIDATION (422)."

    Design: Corner/entities/committee_create_missing_required_field
    """
    payload = {"name": "NoType", "election_cycle": "2026", "jurisdiction": "CA", "treasurer_name": "T"}
    validate_error(api.create_committee(payload, TREASURER), ApiErrorId.ERR_VALIDATION.value)


def test_register_committee_invalid_committee_type_enum_rejected(api):
    """PRD §2.7: "Body validation — required body fields are present, correctly typed, and
    any enum value is a valid member; otherwise ERR_VALIDATION (422)."
    PRD §3.1: committee_type is "one of CANDIDATE, PAC, or PARTY".

    Design: Corner/entities/committee_create_invalid_enum_committee_type
    """
    payload = create_committee_payload(name="Bad", committee_type="SUPERPAC")
    validate_error(api.create_committee(payload, TREASURER), ApiErrorId.ERR_VALIDATION.value)


def test_contribution_under_missing_committee_returns_not_found(api):
    """PRD §2.10: "A request for activities under a non-existent registrant fails with
    ERR_REGISTRANT_NOT_FOUND before any activity lookup is attempted." (per-resource
    not-found; ERR_COMMITTEE_NOT_FOUND for a missing committee id).

    Design: Corner/entities/contribution_fk_committee_not_found
    """
    missing = "00000000-0000-0000-0000-000000000000"
    resp = api.create_contribution(missing, create_contribution_payload(), make_treasurer_headers(missing))
    validate_error(resp, ApiErrorId.ERR_COMMITTEE_NOT_FOUND.value)


def test_report_create_with_missing_period_returns_not_found(api):
    """PRD §2.10: "a create that names a period_id or client_id that does not exist is
    rejected with the corresponding not-found error (ERR_PERIOD_NOT_FOUND,
    ERR_LOBBYING_PERIOD_NOT_FOUND, or ERR_CLIENT_NOT_FOUND)."

    Design: Corner/entities/report_create_period_not_found
    """
    committee = create_active_committee(api, name="Rho")
    resp = api.create_report(
        committee["id"],
        {"period_id": "00000000-0000-0000-0000-000000000000", "expected_committee_version": committee["version"]},
        make_treasurer_headers(committee["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_FOUND.value)


def test_committee_receipts_immediately_reflect_new_contribution(api):
    """PRD §2.9: "Each Committee maintains four derived totals that are never supplied by
    clients and are recomputed immediately whenever their inputs change."

    Design: Corner/consistency_model/contribution_receipts_immediately_visible
    """
    committee = create_active_committee(api, name="ImmCo", committee_type="PAC")
    add_contribution(api, committee["id"], amount_cents=7000)
    fetched = validate_success(api.get_committee(committee["id"], make_treasurer_headers(committee["id"])))
    assert fetched["total_receipts_cents"] == 7000, "receipts must reflect the contribution immediately"


def test_committee_version_increments_by_one_per_mutation(api):
    """PRD §2.4: "version is an integer that starts at its initial value and increments by
    one on every mutation of the resource."
    PRD §3.1: "Every one of these transitions increments the committee's version."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_mutation
    """
    created = validate_success(api.create_committee(create_committee_payload(name="VerCo", committee_type="PAC"), TREASURER), expected_status=201)
    v1 = created["version"]
    approved = validate_success(api.approve_committee(created["id"], REGULATOR))
    v2 = approved["version"]
    assert v2 == v1 + 1, f"approve is a mutation; version must increment by 1 ({v1} -> {v2})"
