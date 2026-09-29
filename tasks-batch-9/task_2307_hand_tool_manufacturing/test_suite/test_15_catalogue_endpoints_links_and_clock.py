"""Partial amendment of a catalogue row, the entity-specific code for every
unresolvable link in a request body, the release gate order, and the logical
clock as the system's only time source."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_timestamp_format,
    create_furnace,
    create_lot,
    create_program,
    create_claimant,
    create_sku,
    furnace_campaign_payload,
    production_lot_payload,
    read_lot,
    read_sku,
    release_payload,
    set_clock,
    make_test_run_payload,
    tool_sku_payload,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_claim_payload,
)

CM = TEST_USERS["channel_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]
WA = TEST_USERS["warranty_administrator_headers"]

DEFAULT_CLOCK_READING = "2026-08-01T00:00:00"
MOVED_CLOCK = "2026-09-15T12:30:00Z"
MOVED_CLOCK_READING = "2026-09-15T12:30:00"
CAMPAIGN_WINDOW = ("2026-08-02T06:00:00Z", "2026-08-02T10:00:00Z")
CORROSION_WINDOW = ("2026-08-04T00:00:00Z", "2026-08-08T00:00:00Z")


# ---------------------------------------------------------------------------
# Amendment is a genuine partial update
# ---------------------------------------------------------------------------


def test_a_price_only_amendment_leaves_the_tier_and_the_acceptance_bar_alone():
    """`list_price_cents` is not an input to the proof-torque derivation, so the
    recomputation reproduces the same 115.8 and the untouched tier survives.

    PRD §3.1: "Only the SKU's own `tool_family`, `nominal_size_mm`, `alloy_grade`
    and `channel` participate — no lot and no test data enters this figure."

    Design: Corner/endpoints/standard_crud_and_partial_patch_on_tool_sku
    """
    sku = create_sku()
    assert sku["version"] == 1
    assert sku["proof_torque_required_nm"] == pytest.approx(115.8, abs=0.01)

    amended = validate_success(api_client.patch_tool_sku(sku["id"], {"list_price_cents": 3900}, CM))

    assert amended["list_price_cents"] == 3900
    assert amended["warranty_tier"] == "LIFETIME"
    assert amended["nominal_size_mm"] == 17
    assert amended["proof_torque_required_nm"] == pytest.approx(115.8, abs=0.01)
    assert amended["version"] == 2


def test_each_accepted_amendment_moves_the_version_by_exactly_one():
    """Two single-field amendments in a row leave the SKU at version 3, and each
    keeps the field the other one set.

    PRD §2.4: "a `version` integer that starts at 1 on creation and increments by
    one on every mutation of that row — including mutations that only touch derived
    fields such as a recomputed hardness index, a refreshed reserve balance or a
    re-derived warranty posture."

    Design: Corner/endpoints/standard_crud_and_partial_patch_on_tool_sku
    """
    sku = create_sku()
    validate_success(api_client.patch_tool_sku(sku["id"], {"list_price_cents": 3900}, CM))

    retiered = validate_success(
        api_client.patch_tool_sku(sku["id"], {"warranty_tier": "LIMITED_5Y"}, CM)
    )

    assert retiered["warranty_tier"] == "LIMITED_5Y"
    assert retiered["list_price_cents"] == 3900
    assert retiered["version"] == 3


def test_a_read_never_mutates_the_row_and_the_filtered_list_shows_the_amended_state():
    """Fetching the SKU twice keeps it at version 3, and the catalogue filters answer
    from the amended row rather than from a stale copy.

    PRD §2.3: "The SKU catalogue can be narrowed by `channel`, `tool_family`,
    `warranty_posture` or `supersedes_sku_id` — the last of these returns the
    successors of a given SKU rather than the SKU itself."

    Design: Corner/endpoints/standard_crud_and_partial_patch_on_tool_sku
    """
    sku = create_sku()
    validate_success(api_client.patch_tool_sku(sku["id"], {"list_price_cents": 3900}, CM))
    validate_success(api_client.patch_tool_sku(sku["id"], {"warranty_tier": "LIMITED_5Y"}, CM))

    fetched = validate_success(api_client.get_tool_sku(sku["id"], WA))
    assert fetched["version"] == 3
    assert read_sku(sku["id"])["version"] == 3

    rows, meta = validate_paginated(
        api_client.list_tool_skus(CM, params={"channel": "BRANDED", "tool_family": "WRENCH"})
    )
    assert meta["total_count"] == 1
    assert rows[0]["list_price_cents"] == 3900
    assert rows[0]["warranty_tier"] == "LIMITED_5Y"

    empty, empty_meta = validate_paginated(
        api_client.list_tool_skus(CM, params={"channel": "PROFESSIONAL"})
    )
    assert empty == []
    assert empty_meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Body-borne links carry their own entity's code
# ---------------------------------------------------------------------------


def _one_row_of_every_linkable_kind():
    sku = create_sku()
    furnace = create_furnace()
    lot = create_lot(sku["id"], specimen_pool_total=20)
    program = create_program()
    claimant = create_claimant()
    return sku, furnace, lot, program, claimant


def _unresolvable_link_cases(sku, furnace, lot, program, claimant):
    return {
        "sku_id_on_a_lot": (
            lambda: api_client.create_production_lot(
                production_lot_payload(NON_EXISTENT_UUID, lot_code="LOT-X", specimen_pool_total=4),
                PP,
            ),
            ApiErrorId.ERR_TOOL_SKU_NOT_FOUND,
        ),
        "furnace_id_on_a_campaign": (
            lambda: api_client.create_furnace_campaign(
                furnace_campaign_payload(
                    lot["id"],
                    NON_EXISTENT_UUID,
                    window_start=CAMPAIGN_WINDOW[0],
                    window_end=CAMPAIGN_WINDOW[1],
                ),
                PP,
            ),
            ApiErrorId.ERR_FURNACE_NOT_FOUND,
        ),
        "lot_id_on_a_campaign": (
            lambda: api_client.create_furnace_campaign(
                furnace_campaign_payload(
                    NON_EXISTENT_UUID,
                    furnace["id"],
                    window_start=CAMPAIGN_WINDOW[0],
                    window_end=CAMPAIGN_WINDOW[1],
                ),
                PP,
            ),
            ApiErrorId.ERR_PRODUCTION_LOT_NOT_FOUND,
        ),
        "chamber_id_on_a_test_run": (
            lambda: api_client.create_test_run(
                make_test_run_payload(
                    lot["id"],
                    test_type="SALT_SPRAY",
                    specimen_count=2,
                    chamber_id=NON_EXISTENT_UUID,
                    window_start=CORROSION_WINDOW[0],
                    window_end=CORROSION_WINDOW[1],
                ),
                QE,
            ),
            ApiErrorId.ERR_CHAMBER_NOT_FOUND,
        ),
        "claimant_id_on_a_claim": (
            lambda: api_client.create_warranty_claim(
                warranty_claim_payload(NON_EXISTENT_UUID, sku["id"], program["id"]), WA
            ),
            ApiErrorId.ERR_CLAIMANT_NOT_FOUND,
        ),
        "program_id_on_a_claim": (
            lambda: api_client.create_warranty_claim(
                warranty_claim_payload(claimant["id"], sku["id"], NON_EXISTENT_UUID), WA
            ),
            ApiErrorId.ERR_WARRANTY_PROGRAM_NOT_FOUND,
        ),
        "supersedes_sku_id_on_a_sku": (
            lambda: api_client.create_tool_sku(
                tool_sku_payload(
                    sku_code="WR-19-BR",
                    nominal_size_mm=19,
                    supersedes_sku_id=NON_EXISTENT_UUID,
                ),
                CM,
            ),
            ApiErrorId.ERR_TOOL_SKU_NOT_FOUND,
        ),
    }


@pytest.mark.parametrize(
    "case",
    [
        "sku_id_on_a_lot",
        "furnace_id_on_a_campaign",
        "lot_id_on_a_campaign",
        "chamber_id_on_a_test_run",
        "claimant_id_on_a_claim",
        "program_id_on_a_claim",
        "supersedes_sku_id_on_a_sku",
    ],
)
def test_an_unresolvable_link_is_reported_with_its_own_entity_code(case):
    """Each link field answers for the entity it points at, never with a generic
    not-found, and never with the downstream business fault it would have hit.

    PRD §2.4: "Identifiers supplied in a request body are checked with the same code
    as their entity: an unresolvable `sku_id`, `primary_sku_id` or
    `supersedes_sku_id` gives `ERR_TOOL_SKU_NOT_FOUND`, an unresolvable `lot_id`
    gives `ERR_PRODUCTION_LOT_NOT_FOUND`, `furnace_id` gives
    `ERR_FURNACE_NOT_FOUND`, `chamber_id` gives `ERR_CHAMBER_NOT_FOUND`,
    `claimant_id` gives `ERR_CLAIMANT_NOT_FOUND` and `program_id` gives
    `ERR_WARRANTY_PROGRAM_NOT_FOUND`."

    Design: Corner/endpoints/body_level_foreign_keys_must_resolve_on_every_link_endpoint
    """
    rows = _one_row_of_every_linkable_kind()
    call, expected = _unresolvable_link_cases(*rows)[case]

    validate_error(call(), expected, 404)


def test_not_one_row_is_written_by_any_of_the_unresolvable_links():
    """Seven refused requests across five collections leave the database exactly as
    the setup left it.

    PRD §2.7: "Many requests violate several rules at once, and exactly one error
    must come back."

    Design: Corner/endpoints/body_level_foreign_keys_must_resolve_on_every_link_endpoint
    """
    rows = _one_row_of_every_linkable_kind()
    for call, expected in _unresolvable_link_cases(*rows).values():
        validate_error(call(), expected, 404)

    for lister, expected_total in (
        (lambda: api_client.list_production_lots(PP), 1),
        (lambda: api_client.list_furnace_campaigns(PP), 0),
        (lambda: api_client.list_test_runs(QE), 0),
        (lambda: api_client.list_warranty_claims(WA), 0),
        (lambda: api_client.list_tool_skus(CM), 1),
    ):
        _, meta = validate_paginated(lister())
        assert meta["total_count"] == expected_total


# ---------------------------------------------------------------------------
# Release is gated on the dossier, but only after the version token
# ---------------------------------------------------------------------------


def test_an_uncertified_lot_is_refused_release_and_banks_no_units():
    """The version token is correct and the lot is neither quarantined nor already
    dispositioned, so the missing certificate is the only rung left.

    PRD §3.5: "and only then, the dossier must be `CERTIFIED`
    (`ERR_LOT_NOT_CERTIFIED`)."

    Design: Corner/endpoints/release_is_a_conditional_action_gated_on_certification
    """
    sku = create_sku()
    lot = create_lot(sku["id"], specimen_pool_total=20)

    validate_error(
        api_client.release_production_lot(lot["id"], release_payload(sku["version"]), PP),
        ApiErrorId.ERR_LOT_NOT_CERTIFIED,
        409,
    )

    unreleased = read_lot(lot["id"])
    assert unreleased["disposition"] == "IN_PROCESS"
    assert unreleased["cert_status"] == "DRAFT"

    untouched = read_sku(sku["id"])
    assert untouched["version"] == sku["version"]
    assert untouched["units_received_total"] == 0
    assert untouched["units_on_hand"] == 0
    assert untouched["units_reserved"] == 0
    assert untouched["units_shipped"] == 0


def test_a_stale_version_token_is_reported_ahead_of_the_missing_certificate():
    """Amending the SKU invalidates the token the planner is holding, and the release
    answers on the token rather than on the dossier.

    PRD §3.5: "That ordering is worth internalising: an uncertified lot released with
    a stale version reports the stale version, not the missing certification."

    Design: Corner/endpoints/release_is_a_conditional_action_gated_on_certification
    """
    sku = create_sku()
    lot = create_lot(sku["id"], specimen_pool_total=20)
    stale_token = sku["version"]
    validate_success(api_client.patch_tool_sku(sku["id"], {"list_price_cents": 3900}, CM))

    body = validate_error(
        api_client.release_production_lot(lot["id"], release_payload(stale_token), PP),
        ApiErrorId.ERR_STALE_SKU_VERSION,
        412,
    )
    assert body["error_id"] != ApiErrorId.ERR_LOT_NOT_CERTIFIED

    assert read_lot(lot["id"])["disposition"] == "IN_PROCESS"
    assert read_sku(sku["id"])["units_received_total"] == 0


# ---------------------------------------------------------------------------
# The logical clock is the only time source
# ---------------------------------------------------------------------------


def test_rows_are_stamped_from_the_documented_default_until_the_clock_is_moved():
    """No clock call has been made, so the first row's own timestamps read the
    documented default instant rather than any wall-clock value.

    PRD §2.8: "It maintains a logical UTC clock which reads exactly
    `2026-08-01T00:00:00Z` until it is moved, and which never falls back to real
    time."

    Design: Corner/endpoints/logical_clock_endpoint_governs_every_timestamp
    """
    sku = create_sku()

    assert_timestamp_format(sku["created_at"])
    assert sku["created_at"].startswith(DEFAULT_CLOCK_READING)
    assert sku["updated_at"].startswith(DEFAULT_CLOCK_READING)


def test_moving_the_clock_stamps_the_next_row_and_the_next_amendment():
    """After the clock moves, a new row is created at the new instant and an
    amendment of the older row refreshes only its `updated_at`.

    PRD §2.4: "Most resources additionally carry an `updated_at` timestamp in the
    same format, refreshed on every mutation, and a `version` integer that starts at 1
    on creation and increments by one on every mutation of that row — including
    mutations that only touch derived fields such as a recomputed hardness index, a
    refreshed reserve balance or a re-derived warranty posture."

    Design: Corner/endpoints/logical_clock_endpoint_governs_every_timestamp
    """
    first = create_sku()
    set_clock(MOVED_CLOCK)

    second = create_sku(sku_code="SO-20-BR", tool_family="SOCKET", nominal_size_mm=20)
    assert second["created_at"].startswith(MOVED_CLOCK_READING)

    amended = validate_success(api_client.patch_tool_sku(first["id"], {"list_price_cents": 3900}, CM))
    assert amended["updated_at"].startswith(MOVED_CLOCK_READING)
    assert amended["created_at"].startswith(DEFAULT_CLOCK_READING)
