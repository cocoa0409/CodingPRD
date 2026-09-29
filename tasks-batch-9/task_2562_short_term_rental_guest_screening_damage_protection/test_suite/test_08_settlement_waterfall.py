"""The insurance stack: publication rules, posture and the settlement waterfall."""

from test_helpers import (
    ApiErrorId,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.test_users import ADJUDICATOR, COMPLIANCE_OFFICER


def _second_listing(api, cast, payload_factory, **overrides):
    """A second ACTIVE listing of the same host, for visibility scoping."""
    listing = validate_success(
        api.create_property(
            cast.host_headers,
            **payload_factory(cast.host_id, cast.jurisdiction_rule_id, **overrides)
        ),
        expected_status=201,
    )
    return validate_success(
        api.activate_property(listing["id"], cast.host_headers)
    )


def test_publishing_one_global_layer_rederives_the_posture_of_a_listing(api):
    """The listing's posture is derived from its layer set, never written by hand.

    The layer is published with no reference to the listing at all, yet the listing
    flips from unprotected to fully covered and its coverage summary starts counting
    the new rung's untouched capacity.

    PRD: "The layers *visible* to a listing are those with `scope` reading `PLATFORM_GLOBAL` plus those whose `property_id` names this listing. Of those, the *available* ones are the layers whose `layer_state` reads `AVAILABLE`. When the available count is zero the posture is `UNPROTECTED`; when the available count is below the visible count the posture is `REDUCED`; otherwise it is `FULL`."
    PRD: "A published layer starts in `layer_state` `AVAILABLE` with `consumed_cents` at 0 and `version` 1, and its publication recomputes `coverage_posture` for every listing it becomes visible to."
    PRD: "A dedicated computed read exposes how that verdict was reached, returning `coverage_posture` alongside `visible_layer_count`, `available_layer_count` and `remaining_capacity_cents`, the last being the total unconsumed capacity across the available layers."

    Design: Corner/state_machines/property_coverage_posture_rederives_when_platform_layer_added
    """
    cast = fixtures.setup_waiver_listing(api)
    assertions.assert_fields(
        cast.property, "property", coverage_posture="UNPROTECTED", listing_state="ACTIVE"
    )

    layer = fixtures.add_coverage_layer(
        api, "PLATFORM_PROTECTION", 20, 250000, 20000, 0.75, "PLATFORM_GLOBAL"
    )
    assertions.assert_fields(
        layer,
        "coverage_layer",
        layer_state="AVAILABLE",
        consumed_cents=0,
        property_id=None,
        version=1,
    )

    assertions.assert_fields(
        fixtures.read_property(api, cast), "property", coverage_posture="FULL"
    )
    assertions.assert_fields(
        validate_success(api.get_coverage_summary(cast.property_id, cast.host_headers)),
        "coverage_summary",
        coverage_posture="FULL",
        visible_layer_count=1,
        available_layer_count=1,
        remaining_capacity_cents=250000,
    )


def test_the_coverage_summary_sums_the_global_stack_plus_the_listings_own(api):
    """A sibling listing's private layer is visible to that listing alone.

    Three layers are published: one global, one attached to the waiver listing and
    one attached to the deposit listing. Each summary must count two layers — the
    global rung plus its own — and sum only those two capacities, with no deductible
    or co-insurance discount applied to capacity.

    PRD: "The layers *visible* to a listing are those with `scope` reading `PLATFORM_GLOBAL` plus those whose `property_id` names this listing. Of those, the *available* ones are the layers whose `layer_state` reads `AVAILABLE`. When the available count is zero the posture is `UNPROTECTED`; when the available count is below the visible count the posture is `REDUCED`; otherwise it is `FULL`."
    PRD: "A dedicated computed read exposes how that verdict was reached, returning `coverage_posture` alongside `visible_layer_count`, `available_layer_count` and `remaining_capacity_cents`, the last being the total unconsumed capacity across the available layers."

    Design: Corner/calculations/coverage_summary_counts_visible_and_available_layers
    """
    cast = fixtures.setup_waiver_listing(api)
    deposit_listing = _second_listing(
        api,
        cast,
        factories.deposit_property_payload,
        address_line="8 Beach Street",
        city="San Francisco",
    )

    fixtures.add_coverage_layer(
        api, "PLATFORM_PROTECTION", 20, 250000, 20000, 0.75, "PLATFORM_GLOBAL"
    )
    fixtures.add_coverage_layer(
        api, "DAMAGE_WAIVER", 10, 100000, 0, 1.0, "PROPERTY",
        property_id=cast.property_id,
    )
    fixtures.add_coverage_layer(
        api, "OWNER_COVERAGE", 10, 400000, 5000, 0.5, "PROPERTY",
        property_id=deposit_listing["id"],
    )

    assertions.assert_fields(
        validate_success(api.get_coverage_summary(cast.property_id, cast.host_headers)),
        "coverage_summary",
        coverage_posture="FULL",
        visible_layer_count=2,
        available_layer_count=2,
        remaining_capacity_cents=350000,
    )
    assertions.assert_fields(
        validate_success(
            api.get_coverage_summary(deposit_listing["id"], cast.host_headers)
        ),
        "coverage_summary",
        coverage_posture="FULL",
        visible_layer_count=2,
        available_layer_count=2,
        remaining_capacity_cents=650000,
    )


def test_layer_order_is_unique_per_visibility_target_and_not_globally(api):
    """Position 20 is taken among the global rungs but free inside a listing.

    The rejected body and the accepted one differ only in their scope, so the
    uniqueness rule cannot be a global one over `layer_order`.

    PRD: "Separately, `layer_order` must be unique among the layers visible to the same target: unique across the `PLATFORM_GLOBAL` layers as a set, and unique within each individual listing's own layers. A duplicate position is refused with `ERR_LAYER_ORDER_CONFLICT`."

    Design: Corner/validations/coverage_layer_order_conflict_within_same_visibility_target
    """
    cast = fixtures.setup_waiver_listing(api)
    fixtures.add_coverage_layer(
        api, "PLATFORM_PROTECTION", 20, 250000, 20000, 0.75, "PLATFORM_GLOBAL"
    )

    validate_error(
        api.create_coverage_layer(
            COMPLIANCE_OFFICER,
            **factories.coverage_layer_payload(
                "HOST_POLICY", 20, 300000, 10000, 0.6, "PLATFORM_GLOBAL"
            )
        ),
        ApiErrorId.ERR_LAYER_ORDER_CONFLICT,
        expected_status=409,
    )
    assertions.assert_page(
        api.list_coverage_layers(COMPLIANCE_OFFICER, scope="PLATFORM_GLOBAL"),
        total_count=1,
    )

    accepted = validate_success(
        api.create_coverage_layer(
            COMPLIANCE_OFFICER,
            **factories.coverage_layer_payload(
                "HOST_POLICY", 20, 300000, 10000, 0.6, "PROPERTY",
                property_id=cast.property_id,
            )
        ),
        expected_status=201,
    )
    assertions.assert_fields(
        accepted,
        "coverage_layer",
        layer_order=20,
        scope="PROPERTY",
        property_id=cast.property_id,
        layer_state="AVAILABLE",
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast), "property", coverage_posture="FULL"
    )
    assertions.assert_fields(
        validate_success(api.get_coverage_summary(cast.property_id, cast.host_headers)),
        "coverage_summary",
        visible_layer_count=2,
        available_layer_count=2,
    )


def test_a_waiver_pool_may_not_be_attached_to_a_deposit_listing(api):
    """The layer-to-listing link is checked against the target's product.

    The deposit listing exists and is perfectly readable, so the refusal is not a
    missing reference; the identical body pointed at the waiver listing is accepted,
    which isolates `protection_product` as the only reason for the rejection.

    PRD: "A `PROPERTY`-scoped layer must name a `property_id` and a `PLATFORM_GLOBAL`-scoped one must leave `property_id` null; furthermore a `DAMAGE_WAIVER` layer must be `PROPERTY`-scoped and attached to a listing whose `protection_product` is `WAIVER`, since there is no waiver pool on a deposit listing. Any violation is refused with `ERR_LAYER_SCOPE_MISMATCH`."
    PRD: "The zero clause is evaluated first on purpose, so a listing with no visible layer at all reads `UNPROTECTED` rather than falling through to `FULL`."

    Design: Corner/endpoints/damage_waiver_layer_on_deposit_listing_rejected
    """
    cast = fixtures.setup_waiver_listing(api)
    deposit_listing = _second_listing(
        api,
        cast,
        factories.deposit_property_payload,
        address_line="8 Beach Street",
        city="San Francisco",
    )
    assertions.assert_fields(
        deposit_listing,
        "property",
        protection_product="DEPOSIT",
        coverage_posture="UNPROTECTED",
    )

    validate_error(
        api.create_coverage_layer(
            COMPLIANCE_OFFICER,
            **factories.coverage_layer_payload(
                "DAMAGE_WAIVER", 10, 100000, 0, 1.0, "PROPERTY",
                property_id=deposit_listing["id"],
            )
        ),
        ApiErrorId.ERR_LAYER_SCOPE_MISMATCH,
        expected_status=422,
    )
    assertions.assert_page(
        api.list_coverage_layers(
            COMPLIANCE_OFFICER, property_id=deposit_listing["id"]
        ),
        total_count=0,
    )
    assertions.assert_fields(
        validate_success(
            api.get_property(deposit_listing["id"], cast.host_headers)
        ),
        "property",
        coverage_posture="UNPROTECTED",
    )

    validate_success(
        api.create_coverage_layer(
            COMPLIANCE_OFFICER,
            **factories.coverage_layer_payload(
                "DAMAGE_WAIVER", 10, 100000, 0, 1.0, "PROPERTY",
                property_id=cast.property_id,
            )
        ),
        expected_status=201,
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast), "property", coverage_posture="FULL"
    )


def _rounding_stack(api, publish_global_first=False):
    """The two-layer stack of the worked example, plus a finished waiver stay."""
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Nadia Reyes", guest_email="nadia@guest.test"
    )
    if publish_global_first:
        platform = fixtures.add_coverage_layer(
            api, "PLATFORM_PROTECTION", 20, 400000, 14990, 0.65, "PLATFORM_GLOBAL"
        )
        waiver = fixtures.add_coverage_layer(
            api, "DAMAGE_WAIVER", 10, 130000, 24990, 0.85, "PROPERTY",
            property_id=cast.property_id,
        )
    else:
        waiver = fixtures.add_coverage_layer(
            api, "DAMAGE_WAIVER", 10, 130000, 24990, 0.85, "PROPERTY",
            property_id=cast.property_id,
        )
        platform = fixtures.add_coverage_layer(
            api, "PLATFORM_PROTECTION", 20, 400000, 14990, 0.65, "PLATFORM_GLOBAL"
        )
    reservation = fixtures.complete_three_night_stay(api, cast)
    claim = fixtures.claim_under_review(api, cast, reservation["id"], 300000)
    return cast, waiver, platform, claim


def test_each_allocation_line_is_rounded_on_its_own_terms(api):
    """Two half-cent lines round up separately and land one cent above the aggregate.

    The waiver rung pays 89259 on 105010 post-deductible at 0.85 and the platform
    rung pays 100757 on 155010 at 0.65. Both products end in exactly half a cent, so
    an implementation that sums the net first and rounds once produces 190015 — one
    cent short of the authoritative figure.

    PRD: "Rounding half up is applied **once per allocation line**, to that line's post-deductible gross multiplied by that line's `coverage_pct` — never to a net figure summed across layers."
    PRD: "The first line charges 130000 gross and pays 89259; the second charges the remaining 170000 and pays 100757; `recovered_cents` is 190016."
    PRD: "Rounding the aggregate of 190015.5 in a single step would have produced 190015."
    PRD: "`host_absorbed_cents` is the gross loss the run started from, minus `recovered_cents`."

    Design: Difficulty/combinatorial_formula/waterfall_rounds_each_allocation_line_not_the_aggregate
    """
    cast, waiver, platform, claim = _rounding_stack(api)
    assertions.assert_fields(
        claim, "damage_claim", projected_recovery_cents=190016
    )

    settled = fixtures.approve_claim(api, claim["id"], 300000)
    assertions.assert_money_split(
        settled,
        approved_amount_cents=300000,
        deposit_applied_cents=0,
        recovered_cents=190016,
        uncovered_cents=0,
        host_absorbed_cents=109984,
    )
    assert settled["recovered_cents"] != 190015, (
        "190015 is what rounding the summed 190015.5 in one step would have produced"
    )

    lines, _meta = assertions.assert_page(
        api.list_settlement_allocations(ADJUDICATOR, claim_id=claim["id"]),
        total_count=2,
    )
    by_index = {row["sequence_index"]: row for row in lines}
    assertions.assert_allocation_line(
        by_index[0],
        coverage_layer_id=waiver["id"],
        sequence_index=0,
        gross_cents=130000,
        deductible_cents=24990,
        allocated_cents=89259,
        voided=False,
    )
    assertions.assert_allocation_line(
        by_index[1],
        coverage_layer_id=platform["id"],
        sequence_index=1,
        gross_cents=170000,
        deductible_cents=14990,
        allocated_cents=100757,
        voided=False,
    )

    assertions.assert_layer_capacity(
        validate_success(api.get_coverage_layer(waiver["id"], COMPLIANCE_OFFICER)),
        consumed_cents=130000,
        layer_state="EXHAUSTED",
    )
    assertions.assert_layer_capacity(
        validate_success(api.get_coverage_layer(platform["id"], COMPLIANCE_OFFICER)),
        consumed_cents=170000,
        layer_state="AVAILABLE",
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast),
        "property",
        coverage_posture="REDUCED",
        listing_state="ACTIVE",
        suspension_reason=None,
    )


def test_the_walk_follows_layer_order_not_the_order_of_publication(api):
    """Publishing the global rung first changes nothing about the executed walk.

    The stack is published in reverse — position 20 before position 10 — so if the
    walk followed creation order the platform rung would take the first slice and the
    two lines would swap their deductibles and their payments. The per-line figures
    must be identical to the forward-published case, and the computed settlement read
    must reconcile them from the outside.

    PRD: "The eligible layers are ordered by `layer_order` ascending and, where two layers share a position across different visibility targets, by `created_at` ascending. They are never ordered by `id`."
    PRD: "`recovered_cents` is the deposit slice plus the sum of `allocated_cents` across the lines written."
    PRD: "The per-line figure is authoritative."
    PRD: "A computed read reconciles the money on a claim from the outside, returning `approved_amount_cents`, `deposit_applied_cents`, `allocation_count`, `allocated_total_cents`, `recovered_cents`, `uncovered_cents` and `host_absorbed_cents` — enough for a reader to verify the conservation rule of §2.6 without inspecting the individual allocation lines."

    Design: Difficulty/combinatorial_formula/waterfall_rounds_each_allocation_line_not_the_aggregate
    """
    cast, waiver, platform, claim = _rounding_stack(api, publish_global_first=True)

    settled = fixtures.approve_claim(api, claim["id"], 300000)
    assertions.assert_money_split(
        settled,
        approved_amount_cents=300000,
        recovered_cents=190016,
        uncovered_cents=0,
        host_absorbed_cents=109984,
    )

    lines, _meta = assertions.assert_page(
        api.list_settlement_allocations(ADJUDICATOR, claim_id=claim["id"]),
        total_count=2,
    )
    first = [row for row in lines if row["sequence_index"] == 0][0]
    second = [row for row in lines if row["sequence_index"] == 1][0]
    assertions.assert_allocation_line(
        first,
        coverage_layer_id=waiver["id"],
        gross_cents=130000,
        deductible_cents=24990,
        allocated_cents=89259,
        voided=False,
    )
    assertions.assert_allocation_line(
        second,
        coverage_layer_id=platform["id"],
        gross_cents=170000,
        deductible_cents=14990,
        allocated_cents=100757,
        voided=False,
    )
    assert first["allocated_cents"] + second["allocated_cents"] == settled["recovered_cents"], (
        "with no deposit standing, recovered_cents is exactly the sum of the lines"
    )

    assertions.assert_fields(
        validate_success(api.get_settlement_summary(claim["id"], cast.host_headers)),
        "settlement_summary",
        approved_amount_cents=300000,
        deposit_applied_cents=0,
        allocation_count=2,
        allocated_total_cents=190016,
        recovered_cents=190016,
        uncovered_cents=0,
        host_absorbed_cents=109984,
    )


def test_with_no_layer_at_all_the_deposit_is_the_whole_recovery(api):
    """The empty eligible set leaves the post-deposit remainder uncovered.

    Nothing is insured anywhere in the system, so the walk's body never runs: the
    50000 hold absorbs what it can and the remaining 70000 falls entirely on the
    host. No allocation row may be written, and the unprotected posture must not take
    the listing down, because no layer transitioned.

    PRD: "When the reservation's `deposit_state` reads `HELD`, the deposit slice is the smaller of the gross loss still unabsorbed and the reservation's `deposit_hold_cents` reduced by its `deposit_applied_cents`."
    PRD: "When no layer is eligible at all, the walk's body never executes: no allocation line is written, `recovered_cents` equals the deposit slice alone, and `uncovered_cents` equals the entire post-deposit remainder."
    PRD: "In parallel, when the deposit slice is non-zero the reservation's `deposit_state` moves from `HELD` to `APPLIED`, the guest's `deposit_held_cents` falls by the reservation's `deposit_hold_cents`, and both the reservation's `version` and the guest's `version` increase by 1."
    PRD: "A listing that never had an eligible layer in the first place is **not** suspended by this rule even though its `coverage_posture` also reads `UNPROTECTED` — the cascade needs an actual layer transition in the current request to fire."

    Design: Difficulty/boundary_precision_check/deposit_only_settlement_when_no_coverage_layer_is_visible
    """
    cast = fixtures.setup_deposit_listing(
        api, guest_name="Elena Vargas", guest_email="elena@guest.test"
    )
    reservation = fixtures.complete_two_night_stay(api, cast)
    assertions.assert_fields(
        reservation, "reservation", deposit_state="HELD", deposit_hold_cents=50000
    )

    claim = fixtures.claim_under_review(api, cast, reservation["id"], 120000)
    assertions.assert_fields(claim, "damage_claim", projected_recovery_cents=50000)

    settled = fixtures.approve_claim(api, claim["id"], 120000)
    assertions.assert_fields(settled, "damage_claim", claim_state="APPROVED")
    assertions.assert_money_split(
        settled,
        approved_amount_cents=120000,
        deposit_applied_cents=50000,
        recovered_cents=50000,
        uncovered_cents=70000,
        host_absorbed_cents=70000,
    )
    assertions.assert_fields(
        validate_success(api.get_settlement_summary(claim["id"], cast.host_headers)),
        "settlement_summary",
        allocation_count=0,
        allocated_total_cents=0,
        recovered_cents=50000,
        uncovered_cents=70000,
        host_absorbed_cents=70000,
    )
    assertions.assert_page(
        api.list_settlement_allocations(ADJUDICATOR, claim_id=claim["id"]),
        total_count=0,
    )

    assertions.assert_fields(
        validate_success(api.get_reservation(reservation["id"], cast.host_headers)),
        "reservation",
        deposit_state="APPLIED",
        deposit_applied_cents=50000,
    )
    assertions.assert_fields(
        fixtures.read_guest(api, cast), "guest", deposit_held_cents=0
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast),
        "property",
        coverage_posture="UNPROTECTED",
        listing_state="ACTIVE",
        suspension_reason=None,
    )
    assertions.assert_fields(
        validate_success(api.get_coverage_summary(cast.property_id, cast.host_headers)),
        "coverage_summary",
        visible_layer_count=0,
        available_layer_count=0,
        remaining_capacity_cents=0,
    )


def test_a_loss_inside_the_hold_is_absorbed_entirely_by_the_deposit(api):
    """The slice is the smaller of the loss and the hold, so nothing is left over.

    An approval of 30000 against a 50000 hold leaves no unabsorbed gross at all: the
    host absorbs nothing, the uncovered tail is zero, and the hold still moves wholly
    off the guest's ledger because the release of the unspent remainder is the sweep's
    business, not the approval's.

    PRD: "When the reservation's `deposit_state` reads `HELD`, the deposit slice is the smaller of the gross loss still unabsorbed and the reservation's `deposit_hold_cents` reduced by its `deposit_applied_cents`."
    PRD: "In parallel, when the deposit slice is non-zero the reservation's `deposit_state` moves from `HELD` to `APPLIED`, the guest's `deposit_held_cents` falls by the reservation's `deposit_hold_cents`, and both the reservation's `version` and the guest's `version` increase by 1."
    PRD: "Approval also raises the guest's `approved_claim_count` by 1, which re-runs the risk score adding 7 points for the approved claim and may re-band `risk_tier`."
    PRD: "Subtract 4 points for each completed stay in `completed_stay_count`, but never more than 20 points in total — the stay credit is floored at 20 points *before* it enters the sum, so a guest with eight completed stays earns the same 20-point credit as a guest with five."

    Design: Difficulty/boundary_precision_check/deposit_only_settlement_when_no_coverage_layer_is_visible
    """
    cast = fixtures.setup_deposit_listing(
        api, guest_name="Elena Vargas", guest_email="elena@guest.test"
    )
    reservation = fixtures.complete_two_night_stay(api, cast)
    stayed = fixtures.read_guest(api, cast)
    assertions.assert_fields(
        stayed, "guest", completed_stay_count=1, deposit_held_cents=50000
    )
    assertions.assert_guest_risk(stayed, 31, "ELEVATED")

    claim = fixtures.claim_under_review(api, cast, reservation["id"], 30000)
    assertions.assert_fields(claim, "damage_claim", projected_recovery_cents=30000)

    settled = fixtures.approve_claim(api, claim["id"], 30000)
    assertions.assert_money_split(
        settled,
        approved_amount_cents=30000,
        deposit_applied_cents=30000,
        recovered_cents=30000,
        uncovered_cents=0,
        host_absorbed_cents=0,
    )
    assertions.assert_page(
        api.list_settlement_allocations(ADJUDICATOR, claim_id=claim["id"]),
        total_count=0,
    )
    assertions.assert_fields(
        validate_success(api.get_reservation(reservation["id"], cast.host_headers)),
        "reservation",
        deposit_state="APPLIED",
        deposit_applied_cents=30000,
        deposit_hold_cents=50000,
    )

    charged = fixtures.read_guest(api, cast)
    assertions.assert_fields(
        charged, "guest", approved_claim_count=1, deposit_held_cents=0
    )
    assertions.assert_guest_risk(charged, 38, "ELEVATED")


def _single_rung_stack(api):
    """A waiver listing whose entire insurance stack is one 100000-cent rung."""
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Marcus Adeyemi", guest_email="marcus@guest.test"
    )
    layer = fixtures.add_coverage_layer(
        api, "DAMAGE_WAIVER", 10, 100000, 0, 1.0, "PROPERTY",
        property_id=cast.property_id,
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast), "property", coverage_posture="FULL"
    )
    reservation = fixtures.complete_three_night_stay(api, cast)
    return cast, layer, reservation


def test_one_approval_walks_the_stack_empty_and_takes_the_listing_down(api):
    """A single decision fires all five links of the exhaustion cascade.

    The rung has no deductible and pays in full, so the approval consumes it to the
    cent. That flip empties the listing's stack, which drives the posture to
    unprotected, which suspends the listing — a chain no request other than this
    decision touched.

    PRD: "Approving a claim therefore fires a five-link cascade: the allocation lines are written, each charged layer's `consumed_cents` rises, a layer reaching its `limit_cents` flips to `EXHAUSTED`, that flip can drive the listing's `coverage_posture` to `UNPROTECTED`, and that posture suspends an `ACTIVE` listing with `suspension_reason` `COVERAGE_EXHAUSTED`."
    PRD: "The layer sits in `AVAILABLE` while `consumed_cents` is below `limit_cents` and flips to `EXHAUSTED` the moment `consumed_cents` equals `limit_cents`; the flip re-derives `coverage_posture` for every listing the layer is visible to and increases the layer's `version` by 1."
    PRD: "Approval sets `decided_at` to the current logical clock, `decided_by_user_id` to the adjudicator's `X-User-ID`, plus `decision_reason_code` and `approved_amount_cents`, and recomputes `appeal_due_at` as 168 hours — seven days — after `decided_at`."
    PRD: "Approval also raises the guest's `approved_claim_count` by 1, which re-runs the risk score adding 7 points for the approved claim and may re-band `risk_tier`."

    Design: Difficulty/transitive_cascade/claim_approval_cascade_exhausts_last_layer_and_suspends_listing
    """
    cast, layer, reservation = _single_rung_stack(api)
    claim = fixtures.claim_under_review(api, cast, reservation["id"], 100000)

    settled = fixtures.approve_claim(api, claim["id"], 100000)
    assertions.assert_fields(
        settled, "damage_claim", claim_state="APPROVED", decided_by_user_id="adj-1",
        decision_reason_code="DAMAGE_CONFIRMED",
    )
    assertions.assert_money_split(
        settled,
        approved_amount_cents=100000,
        deposit_applied_cents=0,
        recovered_cents=100000,
        uncovered_cents=0,
        host_absorbed_cents=0,
    )
    assert settled["appeal_due_at"].startswith("2026-08-20T12:00:00"), (
        "seven days after the 2026-08-13T12:00:00Z decision, got {0!r}".format(
            settled["appeal_due_at"]
        )
    )

    lines, _meta = assertions.assert_page(
        api.list_settlement_allocations(ADJUDICATOR, claim_id=claim["id"]),
        total_count=1,
    )
    assertions.assert_allocation_line(
        lines[0],
        coverage_layer_id=layer["id"],
        sequence_index=0,
        gross_cents=100000,
        deductible_cents=0,
        allocated_cents=100000,
        voided=False,
    )

    spent = validate_success(api.get_coverage_layer(layer["id"], COMPLIANCE_OFFICER))
    assertions.assert_layer_capacity(
        spent, consumed_cents=100000, layer_state="EXHAUSTED"
    )
    assertions.assert_version_advanced_by(layer, spent, 1, "coverage_layer")

    assertions.assert_fields(
        fixtures.read_property(api, cast),
        "property",
        coverage_posture="UNPROTECTED",
        listing_state="SUSPENDED",
        suspension_reason="COVERAGE_EXHAUSTED",
    )
    assertions.assert_fields(
        validate_success(api.get_coverage_summary(cast.property_id, cast.host_headers)),
        "coverage_summary",
        coverage_posture="UNPROTECTED",
        visible_layer_count=1,
        available_layer_count=0,
        remaining_capacity_cents=0,
    )

    charged = fixtures.read_guest(api, cast)
    assertions.assert_fields(charged, "guest", approved_claim_count=1)
    assertions.assert_guest_risk(charged, 38, "ELEVATED")


def test_the_suspension_freezes_new_confirmations_and_refuses_reinstatement(api):
    """The tail of the cascade is commercial: nothing new may be confirmed.

    A booking requested before the decision survives the suspension untouched, but it
    can no longer be confirmed, and the host cannot simply reactivate the listing
    while the stack it emptied is still exhausted.

    PRD: "Suspension leaves reservations already sitting in `REQUESTED` or `CONFIRMED` untouched; it simply means no further confirmation on that listing can succeed."
    PRD: "The listing's `listing_state` must be `ACTIVE`. A `DRAFT` or `SUSPENDED` listing is refused with `ERR_PROPERTY_NOT_LISTED`."
    PRD: "Reinstatement moves `listing_state` from `SUSPENDED` back to `ACTIVE` and demands all of the same things **plus** one more: `coverage_posture` must not read `UNPROTECTED`, and a reinstatement attempted with an empty insurance stack is refused with `ERR_COVERAGE_UNPROTECTED`."

    Design: Difficulty/transitive_cascade/claim_approval_cascade_exhausts_last_layer_and_suspends_listing
    """
    cast, layer, reservation = _single_rung_stack(api)
    next_guest = fixtures.add_guest(api, cast, "Priya Raman", "priya.raman@guest.test")
    upcoming = fixtures.book_stay(
        api,
        cast,
        guest_id=next_guest["id"],
        check_in="2026-08-20",
        check_out="2026-08-22",
    )
    assertions.assert_fields(upcoming, "reservation", stay_state="REQUESTED")

    claim = fixtures.claim_under_review(api, cast, reservation["id"], 100000)
    fixtures.approve_claim(api, claim["id"], 100000)
    suspended = fixtures.read_property(api, cast)
    assertions.assert_fields(
        suspended,
        "property",
        listing_state="SUSPENDED",
        suspension_reason="COVERAGE_EXHAUSTED",
        coverage_posture="UNPROTECTED",
    )

    untouched = validate_success(api.get_reservation(upcoming["id"], cast.host_headers))
    assertions.assert_fields(untouched, "reservation", stay_state="REQUESTED")
    assertions.assert_version_unchanged(upcoming, untouched, "reservation")

    validate_error(
        api.confirm_reservation(upcoming["id"], cast.host_headers),
        ApiErrorId.ERR_PROPERTY_NOT_LISTED,
        expected_status=409,
    )
    validate_error(
        api.activate_property(cast.property_id, cast.host_headers),
        ApiErrorId.ERR_COVERAGE_UNPROTECTED,
        expected_status=409,
    )

    after = fixtures.read_property(api, cast)
    assertions.assert_fields(
        after,
        "property",
        listing_state="SUSPENDED",
        suspension_reason="COVERAGE_EXHAUSTED",
    )
    assertions.assert_version_unchanged(suspended, after, "property")
    assertions.assert_layer_capacity(
        validate_success(api.get_coverage_layer(layer["id"], COMPLIANCE_OFFICER)),
        consumed_cents=100000,
        layer_state="EXHAUSTED",
    )


def _two_deposit_stays(api):
    """Two finished deposit stays on sibling listings that share one global rung."""
    cast_a = fixtures.setup_deposit_listing(
        api, guest_name="Ada Sloan", guest_email="ada.sloan@guest.test"
    )
    sibling = _second_listing(
        api,
        cast_a,
        factories.deposit_property_payload,
        address_line="10 Beach Street",
        city="San Francisco",
    )
    guest_b = fixtures.add_guest(api, cast_a, "Ben Oyelaran", "ben@guest.test")
    cast_b = fixtures.Cast(
        cast_a.host, guest_b, cast_a.jurisdiction_rule, sibling
    )

    layer = fixtures.add_coverage_layer(
        api, "PLATFORM_PROTECTION", 20, 250000, 20000, 0.75, "PLATFORM_GLOBAL"
    )

    stay_a = fixtures.book_stay(api, cast_a)
    fixtures.confirm_stay(api, cast_a, stay_a["id"])
    stay_b = fixtures.book_stay(api, cast_b)
    fixtures.confirm_stay(api, cast_b, stay_b["id"])

    fixtures.check_in_stay(api, cast_a, stay_a["id"])
    fixtures.check_in_stay(api, cast_b, stay_b["id"], clock=None)
    fixtures.complete_stay(api, cast_a, stay_a["id"])
    stay_b = fixtures.complete_stay(api, cast_b, stay_b["id"], clock=None)
    stay_a = validate_success(api.get_reservation(stay_a["id"], cast_a.host_headers))
    return cast_a, cast_b, layer, stay_a, stay_b


def test_the_projection_promises_capacity_a_competing_claim_then_consumes(api):
    """Identical claim data, 75000 cents apart between promise and payment.

    Both claims are submitted while the shared rung is untouched, so both projections
    read its full capacity. The smaller claim is then decided first and consumes
    100000 of it, and the larger claim — whose own data never changed — recovers
    147500 instead of the 222500 it was promised, leaving a 100000-cent tail.

    PRD: "Because it reads layer capacity at submission time, it can promise capacity that a competing claim consumes before the decision lands."
    PRD: "The provisional mode, run at each submission for review, takes as its gross the smaller of `claimed_amount_cents` and the listing's `claim_ceiling_cents`, and its only output is `projected_recovery_cents`."
    PRD: "The final mode, run at an approving decision, takes as its gross the `approved_amount_cents` and has real effects: it emits the allocation lines, raises each charged layer's `consumed_cents` — possibly to `EXHAUSTED` — moves the reservation's `deposit_state` from `HELD` to `APPLIED` when the deposit slice is greater than zero, and writes `deposit_applied_cents`, `recovered_cents`, `uncovered_cents` and `host_absorbed_cents` onto the claim."
    PRD: "`uncovered_cents` is whatever gross loss remains unabsorbed after the walk."

    Design: Difficulty/dual_variant_calc/claim_recovery_projection_diverges_from_final_after_layer_partly_consumed
    """
    cast_a, cast_b, layer, stay_a, stay_b = _two_deposit_stays(api)
    claim_a = fixtures.claim_under_review(api, cast_a, stay_a["id"], 150000)
    claim_b = fixtures.claim_under_review(api, cast_b, stay_b["id"], 300000)
    assertions.assert_fields(claim_a, "damage_claim", projected_recovery_cents=110000)
    assertions.assert_fields(claim_b, "damage_claim", projected_recovery_cents=222500)

    settled_a = fixtures.approve_claim(api, claim_a["id"], 150000)
    assertions.assert_money_split(
        settled_a,
        approved_amount_cents=150000,
        deposit_applied_cents=50000,
        recovered_cents=110000,
        uncovered_cents=0,
        host_absorbed_cents=40000,
    )
    assertions.assert_layer_capacity(
        validate_success(api.get_coverage_layer(layer["id"], COMPLIANCE_OFFICER)),
        consumed_cents=100000,
        layer_state="AVAILABLE",
    )

    settled_b = fixtures.approve_claim(api, claim_b["id"], 300000)
    assertions.assert_money_split(
        settled_b,
        approved_amount_cents=300000,
        deposit_applied_cents=50000,
        recovered_cents=147500,
        uncovered_cents=100000,
        host_absorbed_cents=152500,
    )
    assertions.assert_fields(
        settled_b, "damage_claim", projected_recovery_cents=222500
    )
    assert settled_b["projected_recovery_cents"] - settled_b["recovered_cents"] == 75000, (
        "the promise exceeded the payment by exactly 75000 cents"
    )

    lines, _meta = assertions.assert_page(
        api.list_settlement_allocations(ADJUDICATOR, claim_id=claim_b["id"]),
        total_count=1,
    )
    assertions.assert_allocation_line(
        lines[0],
        coverage_layer_id=layer["id"],
        sequence_index=0,
        gross_cents=150000,
        deductible_cents=20000,
        allocated_cents=97500,
        voided=False,
    )
    assertions.assert_layer_capacity(
        validate_success(api.get_coverage_layer(layer["id"], COMPLIANCE_OFFICER)),
        consumed_cents=250000,
        layer_state="EXHAUSTED",
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast_a), "property", coverage_posture="UNPROTECTED"
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast_b), "property", coverage_posture="UNPROTECTED"
    )


def test_each_submission_re_pins_the_projection_to_the_capacity_it_can_see(api):
    """The provisional run writes nothing and is redone from scratch on resubmission.

    While both claims merely sit under review the rung is untouched: no allocation
    row exists and no deposit has moved. Once the competing claim is decided, sending
    the larger claim back for evidence and resubmitting it re-pins the projection to
    the capacity that actually survives — 147500 rather than the 222500 promised
    earlier, on claim data that never changed.

    PRD: "The provisional run writes no allocation rows, does not touch any layer's `consumed_cents`, and does not move `deposit_state`; it sets `projected_recovery_cents` and nothing else."
    PRD: "It also pins `projected_recovery_cents` by running the settlement waterfall of §3.7 in its **provisional** mode, whose gross loss is the smaller of `claimed_amount_cents` and the listing's `claim_ceiling_cents` — the host's full ask rather than any adjudicated figure."
    PRD: "Compute the layer's remaining capacity as its `limit_cents` minus its `consumed_cents`; if that capacity is zero or below, skip the layer without consuming a `sequence_index`."

    Design: Difficulty/dual_variant_calc/claim_recovery_projection_diverges_from_final_after_layer_partly_consumed
    """
    cast_a, cast_b, layer, stay_a, stay_b = _two_deposit_stays(api)
    claim_a = fixtures.claim_under_review(api, cast_a, stay_a["id"], 150000)
    claim_b = fixtures.claim_under_review(api, cast_b, stay_b["id"], 300000)
    assertions.assert_fields(claim_b, "damage_claim", projected_recovery_cents=222500)

    assertions.assert_layer_capacity(
        validate_success(api.get_coverage_layer(layer["id"], COMPLIANCE_OFFICER)),
        consumed_cents=0,
        layer_state="AVAILABLE",
    )
    assertions.assert_page(
        api.list_settlement_allocations(ADJUDICATOR, claim_id=claim_b["id"]),
        total_count=0,
    )
    assertions.assert_fields(
        validate_success(api.get_reservation(stay_b["id"], cast_b.host_headers)),
        "reservation",
        deposit_state="HELD",
        deposit_applied_cents=0,
    )

    fixtures.approve_claim(api, claim_a["id"], 150000)
    assertions.assert_layer_capacity(
        validate_success(api.get_coverage_layer(layer["id"], COMPLIANCE_OFFICER)),
        consumed_cents=100000,
        layer_state="AVAILABLE",
    )

    validate_success(
        api.request_claim_evidence(
            claim_b["id"], ADJUDICATOR, note="One more shot of the damaged wall."
        )
    )
    fixtures.add_photo_evidence(
        api, cast_b, claim_b["id"], count=1, prefix="round2-photo"
    )
    repinned = validate_success(
        api.submit_claim_for_review(claim_b["id"], cast_b.host_headers)
    )
    assertions.assert_fields(
        repinned,
        "damage_claim",
        claim_state="UNDER_REVIEW",
        evidence_round=2,
        claimed_amount_cents=300000,
        projected_recovery_cents=147500,
    )
    assert repinned["projected_recovery_cents"] != 222500, (
        "the first submission's promise must not survive a competing consumption"
    )
