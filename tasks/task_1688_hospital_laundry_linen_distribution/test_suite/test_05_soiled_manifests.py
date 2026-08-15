"""Soiled manifests: creation linkage rules, isolation protocol, dock-scale
expected pieces, and vendor returns (PRD 3.4, 3.5)."""
from test_helpers import (
    ApiErrorId,
    base_scenario,
    collect_soiled,
    create_gown_stock,
    create_manifest,
    create_par,
    create_soiled_manifest_payload,
    create_towel_stock,
    fill_unit_to_par,
    get_success_data,
    make_manifest,
    read_stock,
    return_manifest_payload,
    setup_unit_with_collection,
    validate_error,
    validate_success,
)


def test_manifest_return_applies_counts_and_status(api, laundry_vendor_headers):
    """PRD 3.5: "A successful return moves the manifest from `DISPATCHED` to
    `RETURNED` and mutates the stock per line."
    PRD 3.5: "`wash_cycles_completed` increases by the returned `pieces`."
    PRD 3.5: "`in_circulation` increases by the returned pieces minus the
    newly retired ones, since retired pieces leave circulation."
    PRD 3.5: "`in_wash` decreases by the returned pieces, the condemned
    pieces, and the lost amount."

    Design: Corner/state_machines/manifest_return_applies_counts_and_status
    """
    ctx = setup_unit_with_collection(soiled_pieces=8)
    manifest = make_manifest(ctx, [ctx["collect_run"]["id"]], 16.00)

    returned = validate_success(
        api.return_soiled_manifest(
            manifest["id"],
            return_manifest_payload(
                [{"stock_id": ctx["stock"]["id"], "pieces": 7,
                  "condemned_pieces": 0}]
            ),
            laundry_vendor_headers,
        ),
        200,
    )
    assert returned["status"] == "RETURNED"

    stock = read_stock(ctx["stock"]["id"])
    assert stock["in_circulation"] == 79, (
        f"72 after collection + 7 returned = 79, got {stock['in_circulation']}"
    )
    assert stock["in_wash"] == 0, (
        f"8 in wash - (7 returned + 0 condemned + 1 lost) = 0, got {stock['in_wash']}"
    )
    assert stock["wash_cycles_completed"] == 7


def test_return_exceeding_in_wash_returns_negative_inventory(
    api, laundry_vendor_headers
):
    """PRD 3.5: "A return may not drive inventory negative: per line, the
    stock's `in_wash` minus the sum of the line's `pieces`, its
    `condemned_pieces`, and the line's lost amount — the positive difference
    between the line's expected pieces and the sum of returned and condemned
    pieces, or zero when that difference is not positive — must remain at
    least zero, or the return is rejected with `ERR_NEGATIVE_INVENTORY`."

    Design: Corner/validations/return_exceeding_in_wash_returns_negative_inventory
    """
    ctx = setup_unit_with_collection(soiled_pieces=8)
    manifest = make_manifest(ctx, [ctx["collect_run"]["id"]], 16.00)

    res = api.return_soiled_manifest(
        manifest["id"],
        return_manifest_payload(
            [{"stock_id": ctx["stock"]["id"], "pieces": 20,
              "condemned_pieces": 0}]
        ),
        laundry_vendor_headers,
    )
    validate_error(res, ApiErrorId.ERR_NEGATIVE_INVENTORY)

    manifest_after = get_success_data(
        api.get_soiled_manifest(manifest["id"], laundry_vendor_headers)
    )
    assert manifest_after["status"] == "DISPATCHED"


def test_cart_run_already_linked_rejected(api, evs_operator_headers):
    """PRD 3.4: "Every element of `cart_run_ids` must exist and belong to the
    given facility (`ERR_NOT_FOUND`), and every referenced run must be in
    `RECONCILED` status and not already linked to another manifest; a run that
    fails either condition rejects the creation with
    `ERR_CART_RUN_ALREADY_LINKED`."

    Design: Corner/validations/cart_run_already_linked_alone
    """
    ctx = setup_unit_with_collection(soiled_pieces=8)
    make_manifest(ctx, [ctx["collect_run"]["id"]], 16.00)

    res = api.create_soiled_manifest(
        create_soiled_manifest_payload(
            ctx["facility"]["id"],
            [ctx["collect_run"]["id"]],
            [{"stock_id": ctx["stock"]["id"], "weight_lbs": 4.00,
              "isolation_flag": False}],
        ),
        evs_operator_headers,
    )
    validate_error(res, ApiErrorId.ERR_CART_RUN_ALREADY_LINKED)


def test_expected_pieces_round_half_up_visible_via_in_wash(api):
    """PRD 3.4: "Each manifest line's expected piece count is derived from the
    dock scale: `weight_lbs` divided by the stock's `piece_weight_lbs`,
    rounded half up to a whole piece."
    PRD 3.4: "Because the dock scale is more authoritative than unit-floor
    counts, creation applies a dock-scale recount adjustment per line: the
    stock's `in_wash` increases by the expected piece count minus the soiled
    pieces recorded for that stock across the linked cart runs."

    Design: Corner/calculations/expected_pieces_rounds_half_up
    """
    ctx = base_scenario()
    towel = create_towel_stock(ctx["facility"]["id"])
    # 10.125 lbs / 0.75 lbs = 13.5 -> round half up -> 14 expected pieces.
    create_manifest(
        ctx["facility"]["id"],
        [],
        [{"stock_id": towel["id"], "weight_lbs": 10.125,
          "isolation_flag": False}],
    )

    stock = read_stock(towel["id"])
    assert stock["in_wash"] == 14, (
        "dock-scale adjustment must add round_half_up(13.5) = 14 pieces to "
        f"in_wash, got {stock['in_wash']}"
    )


class TestIsolationSafetyBeatsLinkConflict:
    """A manifest violating both the isolation protocol and the cart-run
    linkage rule must surface the safety error (PRD 2.9 ordering)."""

    def _setup(self):
        ctx = base_scenario()
        gown = create_gown_stock(ctx["facility"]["id"])
        create_par(ctx["unit"]["id"], gown["id"], 30, "DAILY")
        ctx["gown"] = gown
        ctx["fill_run"] = fill_unit_to_par(ctx)
        ctx["collect_run"] = collect_soiled(
            ctx, [{"stock_id": ctx["stock"]["id"], "pieces": 8}]
        )
        # First manifest links the collection run.
        make_manifest(ctx, [ctx["collect_run"]["id"]], 16.00)
        return ctx

    def test_isolation_violation_reported_over_link_conflict(
        self, api, evs_operator_headers
    ):
        """PRD 2.9: "Eighth, safety attestations — isolation protocol
        acknowledgement (`ERR_ISOLATION_PROTOCOL_REQUIRED`) and clean-storage
        attestation (`ERR_STORAGE_NOT_ATTESTED`)."
        PRD 2.9: "Tenth, referential integrity — linkage, uniqueness, and
        configuration prerequisites (`ERR_CART_RUN_ALREADY_LINKED`,
        `ERR_MANIFEST_ALREADY_INVOICED`, `ERR_PAR_LEVEL_CONFLICT`,
        `ERR_NO_ISOLATION_LINE`, `ERR_NO_PAR_LEVEL`)."
        PRD 3.4: "When any line of a manifest has `isolation_flag` set to
        true, the creation payload must carry `isolation_protocol_ack` as
        true; a manifest that omits the acknowledgement is rejected with
        `ERR_ISOLATION_PROTOCOL_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/manifest_conflict_safety_isolation_beats_referential_link
        """
        ctx = self._setup()
        res = api.create_soiled_manifest(
            create_soiled_manifest_payload(
                ctx["facility"]["id"],
                [ctx["collect_run"]["id"]],
                [{"stock_id": ctx["gown"]["id"], "weight_lbs": 5.00,
                  "isolation_flag": True}],
                isolation_protocol_ack=False,
            ),
            evs_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_ISOLATION_PROTOCOL_REQUIRED)

    def test_link_conflict_surfaces_once_safety_passes(
        self, api, evs_operator_headers
    ):
        """PRD 3.4: "Every element of `cart_run_ids` must exist and belong to
        the given facility (`ERR_NOT_FOUND`), and every referenced run must be
        in `RECONCILED` status and not already linked to another manifest; a
        run that fails either condition rejects the creation with
        `ERR_CART_RUN_ALREADY_LINKED`."

        Design: Difficulty/priority_pair_validation_conflict/manifest_conflict_safety_isolation_beats_referential_link
        """
        ctx = self._setup()
        res = api.create_soiled_manifest(
            create_soiled_manifest_payload(
                ctx["facility"]["id"],
                [ctx["collect_run"]["id"]],
                [{"stock_id": ctx["gown"]["id"], "weight_lbs": 5.00,
                  "isolation_flag": True}],
                isolation_protocol_ack=True,
            ),
            evs_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_CART_RUN_ALREADY_LINKED)
