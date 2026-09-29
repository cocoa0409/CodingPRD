"""Cross-cutting layers: the two optimistic-concurrency rules, the card selector and immediate visibility."""
from test_helpers import (
    ADMIN_HEADERS,
    add_case,
    api_client,
    assert_case_dimensions,
    assert_cents,
    assert_contract_ledger,
    assert_error_envelope,
    assert_pack_line,
    assert_pagination_meta,
    assert_readiness_score,
    assert_version_advanced_by,
    assert_version_unchanged,
    assign_perfusionist,
    base_setup,
    build_assignment,
    build_contract_update,
    build_pack_line_item,
    configure_pack,
    create_preference_card,
    read_case,
    read_contract,
    read_pack,
    read_perfusionist,
    staffed_setup,
    validate_error,
    validate_paginated,
    validate_success,
)


def _read_card(card_id):
    """Read one preference card as the back office."""
    return validate_success(api_client.get_preference_card(card_id, ADMIN_HEADERS), 200)


def test_both_occ_rules_reject_a_stale_parent_version_and_accept_the_current_one():
    """A stale case version and a stale contract version are both refused, and re-quoting succeeds.

    PRD 2.7: If `expected_case_version` does not equal the case's current `version`, the request is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412).
    PRD 2.7: A mismatch with the contract's current `version` is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412).
    PRD 2.7: A contract's version is advanced by every case accrual, every close, every cancellation, every coverage-posture recomputation and every settlement run, so a stale-version writer would otherwise silently re-price against a ledger state it never observed.
    PRD 2.8: Rungs 24 and 25 are the two stale-version checks of §2.7: (24) `ERR_STALE_CASE_VERSION` on perfusionist assignment; (25) `ERR_STALE_CONTRACT_VERSION` on a contract-terms update.

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_a_stale_parent_version_and_accept_the_current_one
    """
    env = base_setup()
    case_id = env["case"]["id"]
    creation_version = env["case"]["version"]

    staffed = assign_perfusionist(
        case_id, env["p1"]["id"], creation_version, env["chief"]["id"]
    )
    assert staffed["assigned_perfusionist_id"] == env["p1"]["id"]

    # The supersede quotes the version the client last saw at creation time.
    stale_case = api_client.assign_perfusionist(
        case_id,
        build_assignment(env["chief"]["id"], creation_version),
        env["chief_headers"],
    )
    validate_error(stale_case, "ERR_STALE_CASE_VERSION", 412)
    assert_error_envelope(stale_case, "ERR_STALE_CASE_VERSION")

    after_refusal = read_case(case_id)
    assert after_refusal["assigned_perfusionist_id"] == env["p1"]["id"]
    assert_version_unchanged(after_refusal, staffed["version"])

    contract = read_contract(env["contract"]["id"])
    assert_contract_ledger(contract, 400000, 1)
    contract_version = contract["version"]
    # The accrual cascade of the assignment advanced the contract too, so its
    # version is already past the value it was registered with.
    assert contract_version > 1

    stale_contract = api_client.update_hospital_contract(
        env["contract"]["id"],
        build_contract_update(contract_version - 1, per_case_fee_cents=450000),
        ADMIN_HEADERS,
    )
    validate_error(stale_contract, "ERR_STALE_CONTRACT_VERSION", 412)
    refused_terms = read_contract(env["contract"]["id"])
    assert_cents(refused_terms["per_case_fee_cents"], 400000, "per_case_fee_cents")
    assert_version_unchanged(refused_terms, contract_version)

    repriced = validate_success(
        api_client.update_hospital_contract(
            env["contract"]["id"],
            build_contract_update(contract_version, per_case_fee_cents=450000),
            ADMIN_HEADERS,
        ),
        200,
    )
    assert_cents(repriced["per_case_fee_cents"], 450000, "per_case_fee_cents")
    assert_version_advanced_by(repriced, contract_version, 1)


def test_preference_card_selector_prefers_revision_over_recency_and_pins_the_choice():
    """The highest revision wins over the most recent card, and a built pack keeps what it pinned.

    PRD 3.5: Publishing a new card retires the ones it replaces: every other card with the same owning surgeon and the same procedure type whose `status` is `ACTIVE` and whose `revision` is lower than **or equal to** the new card's `revision` moves `ACTIVE → SUPERSEDED`.
    PRD 3.5: Crucially, retirement is not retroactive: disposable packs already built keep the card they pinned and the cost they were priced at, so a card revision published mid-week does not silently re-price Monday's cases.
    PRD 3.5: The candidate set is every preference card whose `surgeon_id` is the case's surgeon, whose `procedure_type` is the case's procedure, and whose `status` is `ACTIVE`.
    PRD 3.5: Otherwise the candidates are ordered by `revision` descending, ties broken by `created_at` descending, and the first is selected — so the highest revision wins outright, and only among equal revisions does recency decide.
    PRD 3.5: It records `case_id`, pins the selected card as `applied_preference_card_id`, and copies the card's `prime_volume_ml` verbatim onto itself.
    PRD 3.5: For each materialised line, the gross value is its `quantity` multiplied by its `unit_cost_cents`; the discounted value is that gross multiplied by one minus the contract's `disposable_discount_pct`; the marked-up value is the discounted value multiplied by one plus the contract's `disposable_markup_pct`; and the line's `line_total_cents` is that marked-up value rounded half up to a whole number of cents.

    Design: Corner/cross_cutting_complexity_layers/preference_card_selector_prefers_revision_over_recency_and_pins_the_choice
    """
    env = staffed_setup()
    s1_id = env["surgeon"]["id"]
    pc1_id = env["card"]["id"]

    card_hi = create_preference_card(
        s1_id,
        prime_volume_ml=1600,
        pack_line_items=[build_pack_line_item("A_OXYGENATOR", 1, 1055)],
        required_safety_check_codes=["ACT_BASELINE"],
        revision=3,
    )
    card_mid = create_preference_card(
        s1_id,
        prime_volume_ml=1200,
        pack_line_items=[build_pack_line_item("Z_BUDGET_PACK", 1, 500)],
        required_safety_check_codes=["ACT_BASELINE"],
        blood_management_protocol="ANTIFIBRINOLYTIC",
        min_hematocrit_pct=30,
        revision=2,
    )
    # A new card retires only the cards at or below its own revision.
    assert _read_card(pc1_id)["status"] == "SUPERSEDED"
    assert _read_card(card_hi["id"])["status"] == "ACTIVE"
    assert _read_card(card_mid["id"])["status"] == "ACTIVE"

    pack = configure_pack(env["case"]["id"], env["d1"]["id"], env["p1"]["id"])
    assert pack["applied_preference_card_id"] == card_hi["id"]
    assert pack["prime_volume_ml"] == 1600
    # 1055 discounted by a tenth is 949.5, marked up by a fifth is 1139.4, which
    # rounds half up to 1139.
    assert_cents(pack["pack_cost_cents"], 1139, "pack_cost_cents")
    assert len(pack["line_items"]) == 1
    assert_pack_line(pack["line_items"][0], "A_OXYGENATOR", 1, 1055, 1139, False)

    card_top = create_preference_card(
        s1_id,
        prime_volume_ml=1700,
        pack_line_items=[build_pack_line_item("B_TUBING_PACK", 1, 1155)],
        required_safety_check_codes=["ACT_BASELINE"],
        revision=3,
    )
    assert _read_card(card_hi["id"])["status"] == "SUPERSEDED"
    assert _read_card(card_mid["id"])["status"] == "SUPERSEDED"
    assert _read_card(card_top["id"])["status"] == "ACTIVE"

    # Retirement is not retroactive: the built pack keeps its pinned card and price.
    pinned = read_pack(pack["id"])
    assert pinned["applied_preference_card_id"] == card_hi["id"]
    assert_cents(pinned["pack_cost_cents"], 1139, "pack_cost_cents")
    assert pinned["prime_volume_ml"] == 1600

    case2 = add_case(
        env,
        "case2",
        scheduled_start="2026-08-02T13:31:00Z",
        scheduled_end="2026-08-02T19:31:00Z",
    )
    assign_perfusionist(case2["id"], env["p1"]["id"], case2["version"], env["chief"]["id"])
    pack2 = configure_pack(case2["id"], env["d1"]["id"], env["p1"]["id"])
    assert pack2["applied_preference_card_id"] == card_top["id"]
    assert_cents(pack2["pack_cost_cents"], 1247, "pack_cost_cents")
    assert pack2["prime_volume_ml"] == 1700
    assert_pack_line(pack2["line_items"][0], "B_TUBING_PACK", 1, 1155, 1247, False)

    _cards, meta = validate_paginated(
        api_client.list_preference_cards(
            ADMIN_HEADERS,
            params={"surgeon_id": s1_id, "procedure_type": "CABG", "status": "ACTIVE"},
        )
    )
    assert_pagination_meta(meta, total_count=1, has_more=False)


def test_assignment_effects_are_visible_in_the_same_response_and_on_immediate_reads():
    """The staffing response already carries every derived value, and immediate reads agree with it.

    PRD 2.2: Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
    PRD 2.9: Every operation that changes what a case carries must post the matching delta to the contract in the same request and advance the contract's `updated_at` and `version`.
    PRD 3.4: On success from `SCHEDULED`, the case moves `SCHEDULED → STAFFED`: `assigned_perfusionist_id` is set to the named perfusionist, the provisional fee is computed and written to `provisional_fee_cents`, the fiscal dimension moves `UNBILLED → PROVISIONAL_ACCRUED`, `accrued_fee_cents` is set to the provisional amount, and the contract absorbs it — `accrued_case_fee_cents` rises by that amount, `accrued_case_count` rises by one, and the contract's `updated_at` and `version` advance.
    PRD 3.4: The admission score just computed is stored on the perfusionist.
    PRD 3.3: Failing that, the contract is `THIN` when primary-call coverage reaches at least half the horizon, again 2160 minutes or more.
    PRD 3.3: This posture is recomputed on three occasions: whenever a call rotation slot is created, whenever the logical clock advances and the horizon therefore slides forward, and whenever the systemic-finding cascade releases a primary call slot.

    Design: Corner/consistency_model/assignment_effects_are_visible_in_the_same_response_and_on_immediate_reads
    """
    env = base_setup()
    case_id = env["case"]["id"]
    p1_id = env["p1"]["id"]
    assert env["case"]["bypass_status"] == "SCHEDULED"
    assert env["p1"]["readiness_score"] == 0.0

    written = validate_success(
        api_client.assign_perfusionist(
            case_id,
            build_assignment(p1_id, env["case"]["version"]),
            env["chief_headers"],
        ),
        200,
    )
    assert_case_dimensions(written, "STAFFED", "PROVISIONAL_ACCRUED")
    assert written["assigned_perfusionist_id"] == p1_id
    assert_cents(written["provisional_fee_cents"], 400000, "provisional_fee_cents")
    assert_cents(written["accrued_fee_cents"], 400000, "accrued_fee_cents")
    assert isinstance(written["version"], int)

    contract = read_contract(env["contract"]["id"])
    assert_contract_ledger(contract, 400000, 1)
    # The single three-day primary window was posted at slot creation and fills
    # the horizon, but no backup call exists, so the posture rests at THIN.
    assert contract["coverage_posture"] == "THIN"

    holder = read_perfusionist(p1_id)
    assert_readiness_score(holder["readiness_score"], 0.694)
    assert holder["readiness_variant_last"] == "ADMISSION"

    echoed = read_case(case_id)
    for field in (
        "bypass_status",
        "assigned_perfusionist_id",
        "provisional_fee_cents",
        "accrued_fee_cents",
        "billing_status",
        "version",
    ):
        assert echoed[field] == written[field], (
            "the read of " + field + " disagrees with the write response"
        )

    # Reading again settles nothing further.
    assert_contract_ledger(read_contract(env["contract"]["id"]), 400000, 1)
