"""Intake-derived fields, catalog administration, and payer intake gating."""
from test_helpers import (
    ApiErrorId,
    assert_denial_case,
    assert_payer,
    build_user_headers,
    create_denial_payload,
    create_payer_payload,
    get_success_data,
    is_valid_uuid,
    make_denial,
    make_payer,
    make_policy,
    make_remittance_code,
    setup_catalog,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_payer_creation_applies_defaults(api, director_headers):
    """PRD §3.1: "A new payer starts `ACTIVE` with `appeal_policy_review_required` set to false."
    PRD §2.5: "`id` (string): a unique, server-minted UUID with no type prefix."

    Design: Corner/entities/payer_creation_applies_defaults
    """
    resp = api.create_payer(
        create_payer_payload(name="Payer A", plan_type="MEDICARE",
                             default_timely_filing_days=90),
        director_headers,
    )
    payer = validate_success(resp, expected_status=201)
    assert_payer(payer)
    assert payer["status"] == "ACTIVE"
    assert payer["appeal_policy_review_required"] is False
    assert is_valid_uuid(payer["id"])
    assert isinstance(payer["version"], int)


def test_denial_intake_derives_computed_fields(api, specialist_headers):
    """PRD §3.2: "Intake derives the first filing deadline: `next_appeal_deadline` is the
    `remittance_received_date` plus the `timely_filing_days` of the payer's effective level-1
    policy — the level-1 policy whose half-open window contains the remittance date — falling
    back to the payer's `default_timely_filing_days` when no level-1 policy covers that date."
    PRD §3.2: "At intake the denial's `category` is copied from the remittance code and frozen
    — later catalog edits never retroactively change a denial's category — its `status` begins
    at `RECEIVED`, and its `preventable_flag` reads false until triage sets it."
    PRD §3.2: "because a fresh denial is not yet workable, its `priority_score` computes to
    0.00 with a `queue_bucket` of `LOW`."

    Design: Corner/entities/denial_intake_derives_computed_fields
    """
    catalog = setup_catalog(levels=(1,))
    resp = api.create_denial_case(
        create_denial_payload(
            catalog["payer"]["id"], catalog["code"]["id"],
            claim_number="CLM-2001", patient_account_number="PA-2001",
            billed_amount_cents=300000, denied_amount_cents=250000,
        ),
        specialist_headers,
    )
    denial = validate_success(resp, expected_status=201)
    assert_denial_case(denial)
    assert denial["status"] == "RECEIVED"
    assert denial["category"] == "CODING"
    assert denial["next_appeal_deadline"] == "2026-09-30"  # 2026-08-01 + 60 days
    assert denial["open_balance_cents"] == 250000
    assert denial["recovered_amount_cents"] == 0
    assert denial["written_off_cents"] == 0
    assert denial["current_appeal_level"] == 0
    assert denial["priority_score"] == 0.00
    assert denial["queue_bucket"] == "LOW"


def test_denial_intake_missing_payer_id_returns_invalid_request(api, specialist_headers):
    """PRD §2.8: "Required fields must be present, types and enum memberships must be valid,
    and dates must be ISO-formatted; ... Violations are `ERR_VALIDATION` (400) on every
    mutating endpoint."

    Design: Corner/entities/denial_intake_missing_payer_id_returns_invalid_request
    """
    code = make_remittance_code()
    payload = create_denial_payload("payer-omitted", code["id"], claim_number="CLM-2002")
    del payload["payer_id"]
    resp = api.create_denial_case(payload, specialist_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)
    data, meta = validate_paginated(api.list_denial_cases(specialist_headers))
    assert data == [] and meta["total_count"] == 0, "rejected intake must not persist a denial"


def test_denial_list_pagination_envelope(api, specialist_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return. If
    not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter specifies the number of items to skip and defaults to 0."
    PRD §2.3: "Paginated and non-paginated list-based responses include the following fields
    in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/denial_list_pagination_envelope
    """
    catalog = setup_catalog(levels=())
    for n in ("CLM-2003", "CLM-2004", "CLM-2005"):
        make_denial(catalog["payer"]["id"], catalog["code"]["id"], claim_number=n)
    page1, meta1 = validate_paginated(
        api.list_denial_cases(specialist_headers, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0
    page2, meta2 = validate_paginated(
        api.list_denial_cases(specialist_headers, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_denial_create_system_fields_input_ignored(api, specialist_headers):
    """PRD §2.5: "`id` (string): a unique, server-minted UUID with no type prefix."
    PRD §2.5: "`version` (integer): a system-managed integer that increments by one with
    every modification to the resource, including mutations that only recompute derived
    fields; it underpins optimistic concurrency control."
    PRD §2.4: "At startup, before any clock-control call has been made, the logical clock
    reads exactly 2026-08-01T00:00:00Z; it never defaults to real time."

    Design: Corner/entities/denial_create_system_fields_input_ignored
    """
    catalog = setup_catalog(levels=())
    payload = create_denial_payload(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-2006",
    )
    payload.update({
        "id": "11111111-2222-3333-4444-555555555555",
        "created_at": "1999-01-01T00:00:00.000Z",
        "updated_at": "1999-01-01T00:00:00.000Z",
        "version": 99,
    })
    denial = validate_success(api.create_denial_case(payload, specialist_headers), 201)
    assert denial["id"] != "11111111-2222-3333-4444-555555555555"
    assert is_valid_uuid(denial["id"])
    assert denial["version"] != 99, "version is system-managed; the supplied value must not stick"
    assert denial["created_at"] != "1999-01-01T00:00:00.000Z"
    assert denial["created_at"].startswith("2026-08-01"), (
        "created_at is recorded from the logical clock, which starts at 2026-08-01T00:00:00Z"
    )


def test_duplicate_claim_number_rejected(api, specialist_headers):
    """PRD §3.2: "A `DenialsSpecialist` records a new **denial case** with the payer's
    `claim_number` (unique across all denials — a duplicate is rejected with
    `ERR_DUPLICATE_CLAIM_NUMBER`) ..."

    Design: Corner/validations/duplicate_claim_number_rejected
    """
    catalog = setup_catalog(levels=())
    make_denial(catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-2304")
    resp = api.create_denial_case(
        create_denial_payload(
            catalog["payer"]["id"], catalog["code"]["id"],
            claim_number="CLM-2304", patient_account_number="PA-9999",
            billed_amount_cents=50000, denied_amount_cents=50000,
            service_date="2026-07-11", remittance_received_date="2026-08-02",
        ),
        specialist_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM_NUMBER, expected_status=409)
    data, meta = validate_paginated(api.list_denial_cases(specialist_headers))
    assert meta["total_count"] == 1, "exactly one denial exists after the duplicate is rejected"


def test_deadline_fallback_to_payer_default(api, specialist_headers):
    """PRD §3.2: "Intake derives the first filing deadline: `next_appeal_deadline` is the
    `remittance_received_date` plus the `timely_filing_days` of the payer's effective level-1
    policy — the level-1 policy whose half-open window contains the remittance date — falling
    back to the payer's `default_timely_filing_days` when no level-1 policy covers that date."

    Design: Corner/calculations/deadline_fallback_to_payer_default
    """
    catalog = setup_catalog(
        levels=(),
        payer_overrides={"plan_type": "MEDICAID", "default_timely_filing_days": 90},
    )
    denial = make_denial(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-2201",
    )
    assert denial["next_appeal_deadline"] == "2026-10-30", (
        "no level-1 policy exists, so the payer's 90-day default anchors the deadline"
    )


def test_intake_against_inactive_payer_rejected(api, director_headers, specialist_headers):
    """PRD §3.1: "Setting a payer `INACTIVE` blocks new denial intake for that payer with
    `ERR_PAYER_INACTIVE`; denials already in flight are unaffected, and reactivation
    re-enables intake."

    Design: Difficulty/cross_entity_state_dependency/intake_requires_active_payer
    """
    payer = make_payer()
    code = make_remittance_code()
    patched = validate_success(
        api.update_payer(payer["id"], {"status": "INACTIVE"}, director_headers)
    )
    assert patched["status"] == "INACTIVE"
    resp = api.create_denial_case(
        create_denial_payload(payer["id"], code["id"], claim_number="CLM-1401"),
        specialist_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PAYER_INACTIVE, expected_status=409)


def test_inactive_payer_intake_writes_nothing_and_reactivation_reenables(
    api, director_headers, specialist_headers
):
    """PRD §3.1: "Setting a payer `INACTIVE` blocks new denial intake for that payer with
    `ERR_PAYER_INACTIVE`; denials already in flight are unaffected, and reactivation
    re-enables intake."

    Design: Difficulty/cross_entity_state_dependency/intake_requires_active_payer
    """
    payer = make_payer()
    code = make_remittance_code()
    get_success_data(api.update_payer(payer["id"], {"status": "INACTIVE"}, director_headers))
    resp = api.create_denial_case(
        create_denial_payload(payer["id"], code["id"], claim_number="CLM-1402"),
        specialist_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PAYER_INACTIVE)
    data, meta = validate_paginated(api.list_denial_cases(specialist_headers))
    assert data == [] and meta["total_count"] == 0, "rejected intake must leave no partial write"
    get_success_data(api.update_payer(payer["id"], {"status": "ACTIVE"}, director_headers))
    denial = validate_success(
        api.create_denial_case(
            create_denial_payload(payer["id"], code["id"], claim_number="CLM-1403"),
            specialist_headers,
        ),
        expected_status=201,
    )
    assert denial["status"] == "RECEIVED"


def test_manager_cannot_administer_payer(api, manager_headers, specialist_headers):
    """PRD §2.8: "**Authorization.** The authenticated role must appear in the endpoint's
    authorized role list, else `ERR_FORBIDDEN` (403). Applies to every endpoint."
    PRD §4: "| POST | `/rcm/payers` | Create a payer | RevenueCycleDirector |"

    Design: Corner/rbac/manager_cannot_administer_payer
    """
    resp = api.create_payer(
        create_payer_payload(name="Payer X", plan_type="MEDICAID",
                             default_timely_filing_days=45),
        manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    data, meta = validate_paginated(api.list_payers(specialist_headers))
    assert data == [] and meta["total_count"] == 0, "no payer row may be created"
