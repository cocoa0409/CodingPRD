"""Programs, their derived budget position and the append-only budget ledger."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_budget_position_consistent,
    assert_program,
    create_active_program,
    create_dealer_claimant,
    create_offer,
    create_program,
    create_program_payload,
    create_published_offer,
    entries_of_type,
    list_ledger,
    open_claim,
    read_claimant,
    read_program,
    setup_approved_claim,
    substantiate_claimant,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


def test_new_program_is_draft_with_full_budget_available(api):
    """PRD §3.1: "The program is born in `DRAFT` with `available_cents` equal to
    `budget_total_cents` and `utilization_pct` at 0.0."
    PRD §2.4: "`version` is an integer that starts at 1 when the resource is
    created and increases by exactly 1 on every mutation of that resource;
    `updated_at` is refreshed on the same occasions."

    Design: Corner/entities/create_program_returns_201_with_computed_budget_position
    """
    created = validate_success(
        api.create_program(
            create_program_payload(name="Seed Program", budget_total_cents=500000), ADMIN
        ),
        201,
    )
    data = validate_success(api.get_program(created["id"], ADMIN))
    assert_program(data)
    assert data["status"] == "DRAFT"
    assert data["budget_total_cents"] == 500000
    assert data["committed_cents"] == 0
    assert data["reserve_cents"] == 0
    assert data["available_cents"] == 500000
    assert float(data["utilization_pct"]) == 0.0
    assert data["version"] == 1


def test_unknown_program_id_reports_program_not_found(api):
    """PRD §2.8: "Path existence — every resource named in the URL path must exist,
    resolved left to right, else the corresponding not-found error
    (`ERR_PROGRAM_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CLAIMANT_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND`, `ERR_PAYOUT_NOT_FOUND`,
    `ERR_CARD_NOT_FOUND` or `ERR_FRAUD_CASE_NOT_FOUND`, all HTTP 404)."

    Design: Corner/entities/get_program_with_unknown_id_returns_not_found
    """
    create_program(name="Anchor Program", budget_total_cents=500000)
    resp = api.get_program("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value)


def test_program_creation_without_budget_is_a_validation_error(api):
    """PRD §2.8: "Shape validation — required fields present, enum values drawn
    from their declared sets, constrained integers positive, an offer's
    `effective_end_date` strictly later than its `effective_start_date`, and a
    receipt's `lines` a non-empty array each of whose entries carries `sku`, a
    `quantity` greater than zero and a `unit_price_cents` greater than zero.
    Any breach is `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_program_missing_required_field_is_rejected
    """
    resp = api.create_program(
        {"name": "Incomplete Program", "fiscal_year": 2026, "escheat_jurisdiction": "CA"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    _, meta = validate_paginated(api.list_programs(ADMIN))
    assert meta["total_count"] == 0, "A rejected creation must not persist a program row"


def test_program_listing_paginates_with_limit_and_offset(api):
    """PRD §2.3: "The `meta` block of a list response reports `limit` and `offset`
    as applied, `total_count` as the number of records matching the filters before
    pagination, and `has_more` as true when records remain beyond the current page."

    Design: Corner/entities/list_programs_paginates_with_limit_and_offset
    """
    for name in ("Page A", "Page B", "Page C"):
        create_program(name=name, budget_total_cents=100000)

    first, meta_first = validate_paginated(api.list_programs(ADMIN, params={"limit": 2, "offset": 0}))
    assert meta_first["total_count"] == 3
    assert meta_first["limit"] == 2
    assert meta_first["offset"] == 0
    assert meta_first["has_more"] is True
    assert len(first) == 2

    second, meta_second = validate_paginated(
        api.list_programs(ADMIN, params={"limit": 2, "offset": 2})
    )
    assert meta_second["total_count"] == 3
    assert meta_second["offset"] == 2
    assert meta_second["has_more"] is False
    assert len(second) == 1


def test_child_collections_filter_by_their_parent_identifier(api):
    """PRD §3.2: "Offer listings may be narrowed by `program_id`, by `status`, by
    `channel` and by `sku_scope`."
    PRD §3.3: "Claim listings may be narrowed by `claimant_id`, by `offer_id`, by
    `adjudication_status` and by `payment_status`."

    Design: Corner/entities/fk_reverse_lookups_list_children_by_parent_id
    """
    program = create_active_program(name="Reverse Program", budget_total_cents=100000000)
    offer_a = create_published_offer(program["id"], name="Reverse Tools", sku_scope="TOOLS")
    offer_b = create_offer(program["id"], name="Reverse Paint", sku_scope="PAINT")
    claimant = create_dealer_claimant(legal_name="Reverse Dealer", email="rv@rv.example")
    claim = open_claim(offer_a["id"], claimant)

    offers, offers_meta = validate_paginated(
        api.list_offers(ADMIN, params={"program_id": program["id"]})
    )
    assert offers_meta["total_count"] == 2
    assert {o["id"] for o in offers} == {offer_a["id"], offer_b["id"]}

    claims, claims_meta = validate_paginated(
        api.list_claims(ADMIN, params={"claimant_id": claimant["id"]})
    )
    assert claims_meta["total_count"] == 1
    assert claims[0]["id"] == claim["id"]


def test_budget_adjustment_to_zero_is_refused(api):
    """PRD §3.1: "An adjustment that would drive `budget_total_cents` to zero or
    below is refused with `ERR_BUDGET_ADJUSTMENT_INVALID` (HTTP 422)."

    Design: Corner/validations/budget_adjustment_to_zero_is_rejected
    """
    program = create_active_program(name="Zero Budget Program", budget_total_cents=1000000)
    resp = api.create_budget_adjustment(
        program["id"],
        {
            "delta_cents": -1000000,
            "memo": "Cancel program funding",
            "expected_program_version": program["version"],
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_BUDGET_ADJUSTMENT_INVALID.value)

    after = read_program(program["id"])
    assert after["budget_total_cents"] == 1000000
    assert after["status"] == "ACTIVE"
    assert list_ledger(program_id=program["id"], entry_type="BUDGET_ADJUSTMENT") == []


def test_stale_expected_program_version_blocks_a_budget_adjustment(api):
    """PRD §2.7: "Adjusting a program's budget requires the request to carry
    `expected_program_version`, a non-optional field holding the client's last
    observed `version` of the target program. A mismatch with the program's
    current `version` is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412)."
    PRD §3.1: "The delta is added to `budget_total_cents`, a ledger row of type
    `BUDGET_ADJUSTMENT` is appended, and the budget position is recomputed — which
    may fire either the lock or the unlock transition."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_program_version_on_budget_adjustment_returns_412
    """
    created = validate_success(
        api.create_program(
            create_program_payload(name="OCC Program", budget_total_cents=1000000), ADMIN
        ),
        201,
    )
    version_at_create = created["version"]
    activated = validate_success(api.activate_program(created["id"], ADMIN))
    version_after_activate = activated["version"]

    stale = api.create_budget_adjustment(
        created["id"],
        {
            "delta_cents": 50000,
            "memo": "Stale top-up",
            "expected_program_version": version_at_create,
        },
        ADMIN,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_PROGRAM_VERSION.value)

    fresh = validate_success(
        api.create_budget_adjustment(
            created["id"],
            {
                "delta_cents": 50000,
                "memo": "Fresh top-up",
                "expected_program_version": version_after_activate,
            },
            ADMIN,
        )
    )
    assert fresh["budget_total_cents"] == 1050000

    entries = list_ledger(program_id=created["id"], entry_type="BUDGET_ADJUSTMENT")
    assert len(entries) == 1, "Only the accepted adjustment may append a ledger row"

    after = read_program(created["id"])
    assert after["available_cents"] == 1050000
    assert_budget_position_consistent(after)


def test_approval_response_and_program_read_reflect_the_cascade_immediately(api):
    """PRD §2.9: "A caller that reads a program immediately after an approval sees
    the committed budget already moved; a caller that reads a claimant immediately
    after a fraud substantiation sees the claimant blocked and its open claims
    already denied."
    PRD §3.6: "As the first cascade hop, a ledger row of type `COMMIT` with
    `amount_cents` equal to `final_rebate_cents` is appended, raising the program's
    `committed_cents`."

    Design: Corner/consistency_model/approve_response_already_reflects_every_cascade
    """
    ctx = setup_approved_claim(
        program_overrides={"name": "Immediate Program"}, budget_total_cents=1000000
    )
    assert ctx["claim"]["final_rebate_cents"] == 1600
    assert ctx["claim"]["adjudication_status"] == "APPROVED"

    program = read_program(ctx["program"]["id"])
    assert program["committed_cents"] == 1600
    assert program["pending_provisional_cents"] == 0
    assert program["reserve_cents"] == 0
    assert program["available_cents"] == 998400

    entries = list_ledger(claim_id=ctx["claim"]["id"])
    accruals = entries_of_type(entries, "ACCRUAL")
    commits = entries_of_type(entries, "COMMIT")
    assert len(accruals) == 1 and accruals[0]["amount_cents"] == 1600
    assert len(commits) == 1 and commits[0]["amount_cents"] == 1600


# --------------------------------------------------------------------------- #
# Money conservation across approval and revocation
# --------------------------------------------------------------------------- #

def test_approve_then_revoke_restores_available_cents_exactly(api):
    """PRD §3.1: "Fourth, `available_cents` is `budget_total_cents` less
    `committed_cents` less `reserve_cents`."
    PRD §3.7: "As hop three, each revoked claim appends a ledger row of type
    `RELEASE` whose `amount_cents` equals that claim's `final_rebate_cents`,
    lowering the program's `committed_cents`; and any payout of that claim in
    `PENDING` or `REISSUE_PENDING` moves to `VOIDED` with the claim's payment
    state reset to `NONE`."

    Design: Difficulty/compensating_invariant/approve_then_revoke_restores_program_available_cents_exactly
    """
    ctx = setup_approved_claim(
        program_overrides={"name": "Conservation Program"}, budget_total_cents=1000000
    )
    after_approve = read_program(ctx["program"]["id"])
    assert after_approve["committed_cents"] == 1600
    assert after_approve["available_cents"] == 998400

    substantiate_claimant(ctx["claimant"]["id"], opened_reason="LEDGER_AUDIT")

    after_revoke = read_program(ctx["program"]["id"])
    assert after_revoke["committed_cents"] == 0
    assert after_revoke["available_cents"] == 1000000
    assert float(after_revoke["utilization_pct"]) == 0.0
    assert_budget_position_consistent(after_revoke)


def test_commit_and_release_entries_pair_on_the_revoked_claim_ledger(api):
    """PRD §3.9: "The ledger itself is readable: individual entries may be fetched,
    and entry listings may be narrowed by `program_id`, by `claim_id` and by
    `entry_type`, which together make every movement of program money auditable
    after the fact."
    PRD §3.1: "First, `committed_cents` is the sum of the amounts of all `COMMIT`
    entries, less the sum of all `RELEASE` entries, less the sum of all
    `ESCHEAT_REVERSAL` entries."

    Design: Difficulty/compensating_invariant/approve_then_revoke_restores_program_available_cents_exactly
    """
    ctx = setup_approved_claim(
        program_overrides={"name": "Conservation Ledger Program"}, budget_total_cents=1000000
    )
    substantiate_claimant(ctx["claimant"]["id"], opened_reason="LEDGER_AUDIT")

    entries = list_ledger(claim_id=ctx["claim"]["id"])
    commits = entries_of_type(entries, "COMMIT")
    releases = entries_of_type(entries, "RELEASE")
    assert len(commits) == 1 and commits[0]["amount_cents"] == 1600
    assert len(releases) == 1 and releases[0]["amount_cents"] == 1600

    claim = validate_success(api.get_claim(ctx["claim"]["id"], ADMIN))
    assert claim["adjudication_status"] == "REVOKED"
    assert read_claimant(ctx["claimant"]["id"])["status"] == "BLOCKED"
