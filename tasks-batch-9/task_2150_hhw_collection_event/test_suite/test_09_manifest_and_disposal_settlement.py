"""Preparing, signing, shipping and receiving the uniform hazardous waste
manifest, the two rounding disciplines, and the discrepancy revision cycle."""

from test_helpers import (
    ADMIN,
    CONTRACTOR,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_kg,
    assert_manifest,
    assert_rate,
    container_action,
    create_manifest_payload,
    inspect_event,
    manifest_action,
    open_container,
    pack_line,
    prepare_manifest,
    read_container,
    read_event,
    read_manifest,
    read_program,
    setup_canon,
    setup_two_class_manifest,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_get_manifest_with_unknown_id_returns_manifest_not_found(api):
    """PRD §2.5: "Path identifier resolution, evaluated left to right along the
    URL: each identifier in the path must resolve to a stored row before the next is
    considered. The failure code names the missing entity — `ERR_PROGRAM_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_MATERIAL_CATEGORY_NOT_FOUND`,
    `ERR_STAFFER_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`,
    `ERR_CONTAINER_NOT_FOUND` or `ERR_MANIFEST_NOT_FOUND` — each at HTTP 404."

    Design: Corner/entities/get_manifest_with_unknown_id_returns_manifest_not_found
    """
    response = api.get_manifest(NON_EXISTENT_UUID, CONTRACTOR)
    validate_error(response, ApiErrorId.ERR_MANIFEST_NOT_FOUND, 404)


def test_manifest_over_an_unsealed_drum_is_refused(api):
    """PRD §3.8: "Every container named must currently be `SEALED` with a null
    `manifest_id`, or the request is refused with `ERR_CONTAINER_NOT_SEALED`, and every
    container's event must match the manifest's event, or it is refused with
    `ERR_CONTAINER_EVENT_MISMATCH`."

    Design: Corner/validations/manifest_create_with_open_container_returns_container_not_sealed
    """
    ctx = setup_canon(5)
    container = open_container(ctx["event_id"])
    assert container["status"] == "OPEN"
    event_version = read_event(ctx["event_id"])["version"]

    response = api.create_manifest(
        create_manifest_payload(
            ctx["event_id"],
            [container["id"]],
            event_version,
            manifest_tracking_number="MAN-OPEN",
        ),
        CONTRACTOR,
    )
    validate_error(response, ApiErrorId.ERR_CONTAINER_NOT_SEALED, 409)

    after = read_container(container["id"])
    assert after["status"] == "OPEN"
    assert after["manifest_id"] is None
    _, meta = validate_paginated(
        api.list_manifests(CONTRACTOR, params={"event_id": ctx["event_id"]})
    )
    assert meta["total_count"] == 0


def test_contractor_may_not_sign_the_manifest_the_county_signs(api):
    """PRD §2.1: "Manifest actions are split between two roles that must remain
    distinct: signing, receiving and rejecting a manifest require `ProgramAdmin`, while
    shipping and reopening a manifest require `PackingContractor`. A request that
    carries a permitted role for the manifest-action endpoint but names an action
    reserved for the other role is likewise rejected with `ERR_UNAUTHORIZED_ROLE`."
    PRD §3.8: "Signing moves `DRAFT → SIGNED` and belongs to the `ProgramAdmin` — the
    county, not the contractor, signs as generator."

    Design: Corner/roles/manifest_sign_by_packing_contractor_returns_unauthorized_role
    """
    ctx = setup_canon(29, line_weights=(1.5,), manifest={"manifest_tracking_number": "MAN-SIGN"})
    assert ctx["manifest"]["status"] == "DRAFT"

    response = api.manifest_transition(ctx["manifest_id"], {"action": "SIGN"}, CONTRACTOR)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    manifest = read_manifest(ctx["manifest_id"])
    assert manifest["status"] == "DRAFT"
    assert manifest["signed_by_user_id"] is None
    assert manifest["signed_at_utc"] is None


def test_manifest_preparation_on_a_stale_event_version_is_rejected(api):
    """PRD §2.7: "The same exposure applies, and the same remedy: a
    manifest-creation request must carry `expected_event_version` as a required,
    non-optional field whose value is the `version` of the target `CollectionEvent` row
    as the client last observed it. A value that does not equal the event's current
    `version` is rejected with `ERR_STALE_VERSION` at HTTP 412, and no manifest is
    created, no draft is voided, and no container changes state."

    Design: Corner/cross_cutting_complexity_layers/manifest_create_with_stale_event_version_returns_stale_version
    """
    ctx = setup_canon(28, line_weights=(1.5,), appointment={"declared_total_kg": 6.0})
    stale_version = ctx["event_version"]

    failed = inspect_event(ctx["event_id"], "FAIL", finding_code="SUMP-OVERFLOW")
    assert failed["containment_status"] == "DEFICIENT"

    response = api.create_manifest(
        create_manifest_payload(
            ctx["event_id"],
            [ctx["container_id"]],
            stale_version,
            manifest_tracking_number="MAN-STALE",
        ),
        CONTRACTOR,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION, 412)

    container = read_container(ctx["container_id"])
    assert container["status"] == "SEALED"
    assert container["manifest_id"] is None
    _, meta = validate_paginated(
        api.list_manifests(CONTRACTOR, params={"event_id": ctx["event_id"]})
    )
    assert meta["total_count"] == 0


def test_a_second_draft_supersedes_the_first_and_hands_its_drum_back(api):
    """PRD §3.8: "It also supersedes: any other manifest of the same event still
    sitting in `DRAFT` transitions to `VOIDED`, with `superseded_by_manifest_id` set to
    the new manifest's `id`, and every container that voided manifest was carrying
    returns `MANIFESTED → SEALED` with its `manifest_id` cleared."
    PRD §2.3: "Manifests may be filtered by `event_id`, by `status` and by
    `superseded_by_manifest_id`."

    Design: Corner/state_machines/superseding_manifest_voids_prior_draft_and_returns_containers
    """
    ctx = setup_canon(
        22, line_weights=(1.5, 2.5), appointment={"declared_total_kg": 12.0}
    )
    drum_a = open_container(ctx["event_id"], container_code="DRUM-A1")
    pack_line(drum_a["id"], ctx["line_ids"][0])
    container_action(drum_a["id"], "SEAL")
    drum_b = open_container(ctx["event_id"], container_code="DRUM-A2")
    pack_line(drum_b["id"], ctx["line_ids"][1])
    container_action(drum_b["id"], "SEAL")

    first = prepare_manifest(
        ctx["event_id"], [drum_a["id"]], manifest_tracking_number="MAN-S1"
    )
    assert first["status"] == "DRAFT"

    second = prepare_manifest(
        ctx["event_id"], [drum_b["id"]], manifest_tracking_number="MAN-S2"
    )
    assert second["status"] == "DRAFT"

    voided = read_manifest(first["id"])
    assert voided["status"] == "VOIDED"
    assert voided["superseded_by_manifest_id"] == second["id"]

    returned = read_container(drum_a["id"])
    assert returned["status"] == "SEALED"
    assert returned["manifest_id"] is None
    carried = read_container(drum_b["id"])
    assert carried["status"] == "MANIFESTED"
    assert carried["manifest_id"] == second["id"]

    assert read_program(ctx["program_id"])["budget_encumbered_cents"] == 621
    _, meta = validate_paginated(
        api.list_manifests(CONTRACTOR, params={"superseded_by_manifest_id": second["id"]})
    )
    assert meta["total_count"] == 1


def test_container_estimate_and_manifest_invoice_land_one_cent_apart(api):
    """PRD §3.8: "Take one drum holding three accepted latex-paint lines at 155 cents
    per kilogram weighing 1.5, 2.5 and 0.5 kilograms. The container estimate rounds
    each line first — 232.5 becomes 233, 387.5 becomes 388, 77.5 becomes 78 — and sums
    to 699 cents. The manifest invoice sums the exact products to 697.5 against 4.5
    kilograms, derives a blended rate of 155.0000, multiplies back to 697.5, and rounds
    once to 698 cents."

    Design: Difficulty/dual_variant_calc/container_estimate_versus_manifest_invoice_divergence
    """
    ctx = setup_canon(32)

    container = read_container(ctx["container_id"])
    assert container["estimated_disposal_cost_cents"] == 699
    assert_kg(container["net_weight_kg"], 4.5, "container net_weight_kg")

    manifest = read_manifest(ctx["manifest_id"])
    assert_manifest(manifest)
    assert_kg(manifest["net_weight_kg"], 4.5, "manifest net_weight_kg")
    assert_rate(manifest["blended_rate_cents_per_kg"], 155.0)
    assert manifest["invoiced_disposal_cost_cents"] == 698
    assert container["estimated_disposal_cost_cents"] - manifest["invoiced_disposal_cost_cents"] == 1


def test_receiving_moves_the_money_from_encumbered_to_spent(api):
    """PRD §3.8: "The rest of receiving is bookkeeping. Every container of the
    manifest moves `SHIPPED → DISPOSED`, draining its `estimated_disposal_cost_cents`
    out of `budget_in_transit_cents`; the manifest's `invoiced_disposal_cost_cents` is
    added to the program's `budget_spent_cents`; the event's `tonnage_reported_kg` —
    the sum of `net_weight_kg` across that event's received manifests, rounded half up
    to three decimal places — and the program's `tonnage_ytd_kg` are recomputed; and
    the posture is recomputed."
    PRD §3.8: "That one-cent delta is the program's rounding variance, and it is
    **never** written back to the container."

    Design: Difficulty/dual_variant_calc/container_estimate_versus_manifest_invoice_divergence
    """
    ctx = setup_canon(32)

    program = read_program(ctx["program_id"])
    assert program["budget_spent_cents"] == 698
    assert program["budget_encumbered_cents"] == 0
    assert program["budget_in_transit_cents"] == 0

    container = read_container(ctx["container_id"])
    assert container["status"] == "DISPOSED"
    assert container["estimated_disposal_cost_cents"] == 699, (
        "The rounding variance is never written back to the drum"
    )
    assert_kg(read_event(ctx["event_id"])["tonnage_reported_kg"], 4.5, "tonnage_reported_kg")


def test_rejected_load_returns_its_drum_and_reopening_re_attaches_it(api):
    """PRD §3.8: "Second, because the manifest has entered discrepancy, every
    container carrying that `manifest_id` moves `SHIPPED → SEALED`, clears its
    `manifest_id` and sets its `discrepancy_flag` to true, processed in container
    `created_at` ascending order; each such move returns that container's
    `estimated_disposal_cost_cents` from `budget_in_transit_cents` back into
    `budget_encumbered_cents`, undoing the shipping transfer exactly."
    PRD §3.8: "Every container of that manifest's event carrying a raised
    `discrepancy_flag` with a status of `SEALED` and a null `manifest_id` is
    re-attached: `SEALED → MANIFESTED`, `manifest_id` set to this manifest,
    `discrepancy_flag` cleared, processed in `created_at` ascending order."

    Design: Difficulty/non_linear_state_machine/manifest_discrepancy_reopen_revision_cycle
    """
    ctx = setup_canon(31, manifest={"manifest_tracking_number": "MAN-0004"})
    assert ctx["manifest"]["status"] == "SHIPPED"

    rejected = validate_success(
        api.manifest_transition(
            ctx["manifest_id"],
            {"action": "REJECT", "discrepancy_code": "WEIGHT_VARIANCE"},
            ADMIN,
        ),
        200,
    )
    assert rejected["status"] == "DISCREPANCY"

    returned = read_container(ctx["container_id"])
    assert returned["status"] == "SEALED"
    assert returned["discrepancy_flag"] is True

    reopened = manifest_action(ctx["manifest_id"], "REOPEN")
    assert reopened["status"] == "DRAFT", "The cycle returns to the machine's start"

    reattached = read_container(ctx["container_id"])
    assert reattached["status"] == "MANIFESTED"
    assert reattached["discrepancy_flag"] is False
    assert read_event(ctx["event_id"])["discrepancy_container_count"] == 0


def test_revised_manifest_can_be_signed_shipped_and_received_again(api):
    """PRD §3.8: "On success the manifest returns to `DRAFT`, its `discrepancy_code`
    is cleared, and both `signed_by_user_id` and `signed_at_utc` are cleared so the
    county must sign afresh."
    PRD §3.8: "Throughout the whole revision cycle the re-attached containers stay
    encumbered in `budget_encumbered_cents` — the money never leaves the program's
    commitments while the load is being re-papered — and the manifest can then be
    signed, shipped and received again."

    Design: Difficulty/non_linear_state_machine/manifest_discrepancy_reopen_revision_cycle
    """
    ctx = setup_canon(31, manifest={"manifest_tracking_number": "MAN-0004"})
    manifest_action(ctx["manifest_id"], "REJECT", discrepancy_code="WEIGHT_VARIANCE")
    manifest_action(ctx["manifest_id"], "REOPEN")

    assert manifest_action(ctx["manifest_id"], "SIGN")["status"] == "SIGNED"
    manifest_action(ctx["manifest_id"], "SHIP")
    received = manifest_action(ctx["manifest_id"], "RECEIVE", invoice_reference="INV-104")

    assert received["status"] == "RECEIVED"
    assert received["invoiced_disposal_cost_cents"] == 698
    assert read_container(ctx["container_id"])["status"] == "DISPOSED"

    program = read_program(ctx["program_id"])
    assert program["budget_spent_cents"] == 698
    assert program["budget_in_transit_cents"] == 0
    assert program["budget_encumbered_cents"] == 0


def test_two_rate_classes_are_estimated_by_rounding_every_line_first(api):
    """PRD §3.8: "For every dropoff line packed into the container whose
    `disposition` is `ACCEPTED`, the line's cost is its `net_weight_kg` multiplied by
    its material category's `disposal_rate_cents_per_kg`, rounded half up to a whole
    number of cents; the container's estimate is the sum of those already-rounded line
    costs."
    PRD §3.8: "A manifest's `container_ids` is at all times the identifiers of the
    containers whose `manifest_id` points at it, ordered by container `created_at`
    ascending; its `net_weight_kg` is the sum of those containers' `net_weight_kg`
    rounded half up to three decimal places; and its `estimated_disposal_cost_cents` is
    the sum of those containers' `estimated_disposal_cost_cents`, carrying the
    round-per-line-then-sum lineage forward unchanged."

    Design: Difficulty/combinatorial_formula/disposal_blended_rate_rounding_order_mode_b
    """
    ctx = setup_two_class_manifest()

    assert ctx["estimate_a"] == 699, "233 + 388 + 78 over the three latex lines"
    assert ctx["estimate_b"] == 120, "0.25 kg of pool acid at 480 cents/kg"

    manifest = read_manifest(ctx["manifest_id"])
    assert manifest["estimated_disposal_cost_cents"] == 819
    assert_kg(manifest["net_weight_kg"], 4.75, "manifest net_weight_kg")


def test_the_blended_rate_settles_the_invoice_one_cent_below_the_estimate(api):
    """PRD §3.8: "A weighted total is then formed by taking every accepted line in
    every container of the manifest, multiplying each line's `net_weight_kg` by its
    material category's `disposal_rate_cents_per_kg`, and summing those products
    **exactly, with no intermediate rounding at all**. The `blended_rate_cents_per_kg`
    is that exact weighted total divided by the manifest's `net_weight_kg`, rounded
    half up to four decimal places — or zero when the manifest's `net_weight_kg` is
    zero. Finally, `invoiced_disposal_cost_cents` is the manifest's `net_weight_kg`
    multiplied by its `blended_rate_cents_per_kg`, rounded half up to a whole number of
    cents, exactly once."

    Design: Difficulty/combinatorial_formula/disposal_blended_rate_rounding_order_mode_b
    """
    ctx = setup_two_class_manifest()
    estimate = read_manifest(ctx["manifest_id"])["estimated_disposal_cost_cents"]

    received = validate_success(
        api.manifest_transition(
            ctx["manifest_id"], {"action": "RECEIVE", "invoice_reference": "INV-88"}, ADMIN
        ),
        200,
    )

    assert_rate(received["blended_rate_cents_per_kg"], 172.1053)
    assert_kg(received["net_weight_kg"], 4.75, "manifest net_weight_kg")
    assert received["invoiced_disposal_cost_cents"] == 818
    assert estimate - received["invoiced_disposal_cost_cents"] == 1
    assert read_program(ctx["program_id"])["budget_spent_cents"] == 818
