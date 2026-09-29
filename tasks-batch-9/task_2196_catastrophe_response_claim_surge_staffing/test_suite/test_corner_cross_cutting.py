"""Queue B — section: cross_cutting_complexity_layers.

Optimistic concurrency on the two version-carrying writes, cascading side effects
(including the "a rejected write fires none of its links" case), the two
loss-estimate methods minted at one clock instant, and the event-level derived
roll-ups reconciling against the append-only reserve ledger.

Every precondition is built inside the test: the server restarts per test, so the
database is empty when each test begins.
"""
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_money_equals
from test_helpers.test_users import (
    make_catastrophe_manager_headers,
    make_claims_examiner_headers,
    make_deployment_coordinator_headers,
)

CM = make_catastrophe_manager_headers("mgr-01")
DC = make_deployment_coordinator_headers("coord-01")
CE = make_claims_examiner_headers("examiner-alice")

CLOCK = "2026-09-01T00:00:00.000Z"

# The event shape shared by every instance in this section: 1000 exposures at
# 250000 average insured value, severity index 0.1000, HURRICANE, Florida.
_EVENT_INPUTS = {
    "peril_type": "HURRICANE",
    "jurisdiction_state": "FL",
    "event_start_utc": CLOCK,
    "exposure_count": 1000,
    "avg_insured_value": 250000,
    "expected_severity_index": 0.1000,
}

# The claim shape shared by every instance: one DWELLING line, 8000 first notice.
_CLAIM_LINES = [
    {
        "coverage_code": "DWELLING",
        "limit_amount": 300000,
        "deductible_amount": 5000,
        "estimated_damage_amount": 120000,
    }
]


def _declared_event(api, cat_code):
    """Clock at 2026-09-01T00:00:00.000Z, then a DECLARED FL hurricane event."""
    validate_success(api.set_clock(CLOCK, CM))
    payload = dict(_EVENT_INPUTS, cat_code=cat_code)
    event = validate_success(api.create_event(payload, CM), 201)
    return validate_success(api.declare_event(event["id"], CM))


def _cat_coded_claim(api, event_id, policy_number):
    """One INTAKE claim already carrying the event's cat code."""
    return validate_success(
        api.create_claim(
            {
                "policy_number": policy_number,
                "loss_state": "FL",
                "loss_date_utc": "2026-09-02T00:00:00.000Z",
                "reported_loss_amount": 8000,
                "coverage_lines": _CLAIM_LINES,
                "event_id": event_id,
            },
            CE,
        ),
        201,
    )


def _triaged_claim(api, event_id, policy_number):
    """The shared FAST_TRACK / DESK claim: severity 5.07, case reserve 28750.00."""
    claim = _cat_coded_claim(api, event_id, policy_number)
    return validate_success(api.triage_claim(claim["id"], CE))


def _desk_adjuster(api):
    """An idle FL staff adjuster certified for desk work, licence good to 2027."""
    return validate_success(
        api.create_adjuster(
            {
                "full_name": "Dana Reyes",
                "employment_type": "STAFF",
                "home_state": "FL",
                "licensed_states": ["FL"],
                "license_expiry_utc": "2027-12-31T00:00:00.000Z",
                "max_open_claims": 5,
                "daily_rate": 700,
                "per_diem_rate": 100,
                "desk_certified": True,
                "aerial_certified": False,
            },
            DC,
        ),
        201,
    )


def _two_room_block(api, event_id):
    """A 2-room ACTIVE block at 200.00 a night over seven nights."""
    block = validate_success(
        api.create_housing_block(
            {
                "event_id": event_id,
                "hotel_name": "Gulfview Inn",
                "city": "Tampa",
                "rooms_total": 2,
                "nightly_rate": 200,
                "block_start_date": "2026-09-01T00:00:00.000Z",
                "block_end_date": "2026-09-08T00:00:00.000Z",
            },
            DC,
        ),
        201,
    )
    return block


# ---------------------------------------------------------------------------
# Optimistic concurrency on the two version-carrying writes
# ---------------------------------------------------------------------------
def test_loss_estimate_with_current_event_version_is_stored_and_bumps_the_event(api):
    """PRD §2.8: "A request that creates a loss-estimate snapshot must carry
    `expected_event_version` holding the client's last observed `version` of the target
    `CatastropheEvent`."
    PRD §3.8: "Multiply the event's `exposure_count` by its `avg_insured_value`, by its
    `expected_severity_index`, and by the peril development factor — 1.40 for `HURRICANE`,
    1.55 for `WILDFIRE`, 1.65 for `FLOOD`, 1.20 for `HAIL`, 1.10 for `WINTER_STORM`, 1.80
    for `EARTHQUAKE` — to obtain the modelled ultimate."
    PRD §3.8: "Each snapshot records `input_reserve_sequence_high_water`, the greatest
    ledger `sequence_no` on the event at snapshot time, or 0 when the event had no entries,
    and `computed_at_utc` at the current logical-clock instant, and is born non-stale."
    PRD §3.8: "Minting a snapshot refreshes the event's `gross_loss_estimate` and
    recomputes posture."

    Design: Corner/cross_cutting_complexity_layers/corner_ccl_occ_loss_estimate_current_event_version_accepted
    """
    event = _declared_event(api, "CAT-2026-125")
    assert event["version"] == 2, "declare is the event's second mutation"

    snapshot = validate_success(
        api.create_loss_estimate(
            {
                "event_id": event["id"],
                "method": "EXPOSURE_BASED",
                "expected_event_version": event["version"],
            },
            CM,
        ),
        201,
    )
    # 1000 * 250000 * 0.1000 * 1.40 = 35000000.00 modelled ultimate, with an
    # incurred_total of 0.00 to subtract.
    assert_money_equals(snapshot["gross_estimate"], 35000000.00, "gross_estimate")
    assert_money_equals(snapshot["ibnr_component"], 35000000.00, "ibnr_component")
    assert_money_equals(snapshot["reported_component"], 0.00, "reported_component")
    assert snapshot["input_reserve_sequence_high_water"] == 0, (
        "no ledger entry exists, so the high-water mark is 0"
    )
    assert snapshot["stale"] is False, "a freshly minted snapshot is born non-stale"

    after = validate_success(api.get_event(event["id"], CM))
    assert after["version"] == 3, (
        f"minting refreshes gross_loss_estimate so version must reach 3, got {after['version']}"
    )
    assert_money_equals(after["gross_loss_estimate"], 35000000.00, "gross_loss_estimate")


def test_loss_estimate_with_predeclaration_event_version_is_rejected_412(api):
    """PRD §2.8: "If that value does not equal the event's current `version`, the request
    is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412) and nothing is created."
    PRD §3.8: "**Loss-estimate snapshots** are the event-level view of ultimate loss,
    minted by a `CatastropheManager`. The payload names the `event_id`, the `method`, and
    `expected_event_version` carrying the client's last observed event `version`; a
    mismatch is `ERR_STALE_EVENT_VERSION` (HTTP 412) and nothing is created."

    Design: Corner/cross_cutting_complexity_layers/corner_ccl_occ_loss_estimate_stale_event_version_rejected
    """
    event = _declared_event(api, "CAT-2026-126")
    stale_version = event["version"] - 1  # the pre-declaration view: 1, not 2.

    rejected = api.create_loss_estimate(
        {
            "event_id": event["id"],
            "method": "EXPOSURE_BASED",
            "expected_event_version": stale_version,
        },
        CM,
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_EVENT_VERSION, 412)

    rows, meta = validate_paginated(
        api.list_loss_estimates(CM, params={"event_id": event["id"]})
    )
    assert meta["total_count"] == 0, "a rejected mint stores no snapshot"
    assert rows == [], "a rejected mint stores no snapshot"

    after = validate_success(api.get_event(event["id"], CM))
    assert after["version"] == 2, (
        f"a rejected mint is not a mutation, so version stays 2, got {after['version']}"
    )
    assert_money_equals(after["gross_loss_estimate"], 0.00, "gross_loss_estimate")


def test_manual_reserve_entry_with_pretriage_claim_version_is_rejected_412(api):
    """PRD §2.8: "A request that appends a manual reserve entry to a claim must carry
    `expected_claim_version` holding the client's last observed `version` of that `Claim`.
    If that value does not equal the claim's current `version`, the request is rejected
    with `ERR_STALE_CLAIM_VERSION` (HTTP 412) and no ledger row is written."
    PRD §3.6: "Triage stamps `severity_score` and `triage_tier`, stamps `inspection_mode`,
    stamps `deadline_utc`, and appends an `INITIAL_CASE` entry to the reserve ledger whose
    case-reserve movement comes from the initial-reserve rule and whose paid movement is
    exactly 0.00, taking the next per-event sequence number."

    Design: Corner/cross_cutting_complexity_layers/corner_ccl_occ_reserve_entry_stale_claim_version_rejected
    """
    event = _declared_event(api, "CAT-2026-127")
    claim = _triaged_claim(api, event["id"], "POL-1011")
    assert claim["version"] == 2, "triage is the claim's second mutation"

    rejected = api.create_reserve_entry(
        claim["id"],
        {
            "expected_claim_version": claim["version"] - 1,
            "entry_type": "REVISION",
            "delta_case_reserve": 1000,
            "delta_paid": 0,
            "memo": "manual uplift on stale view",
        },
        CE,
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_CLAIM_VERSION, 412)

    rows, meta = validate_paginated(
        api.list_reserve_entries(CE, params={"claim_id": claim["id"]})
    )
    assert meta["total_count"] == 1, "the append was rejected, so the ledger keeps one row"
    assert rows[0]["entry_type"] == "INITIAL_CASE"
    assert_money_equals(rows[0]["delta_case_reserve"], 28750.00, "delta_case_reserve")
    assert rows[0]["sequence_no"] == 1

    after_claim = validate_success(api.get_claim(claim["id"], CE))
    assert_money_equals(after_claim["case_reserve"], 28750.00, "case_reserve")
    assert after_claim["version"] == 2, (
        f"a rejected append is not a mutation, got version {after_claim['version']}"
    )
    after_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(after_event["incurred_total"], 28750.00, "incurred_total")


# ---------------------------------------------------------------------------
# Cascading side effects, including the rejected-write case
# ---------------------------------------------------------------------------
def test_cancelling_the_only_assignment_regresses_the_claim_and_leaves_the_ledger_alone(api):
    """PRD §3.7: "Either source state behaves identically: the adjuster's
    `open_assignment_count` and `surge_capacity_score` are recomputed, and when the claim
    has no assignment left in `SCHEDULED` or `IN_PROGRESS`, the claim regresses
    `INSPECTION_PENDING → TRIAGED` and the event's posture is recomputed — which is how a
    mass demobilization can tighten an event's posture without anyone touching the event."
    PRD §3.3: "The **availability term** starts from the adjuster's `open_assignment_count`
    — the number of their inspection assignments currently in `SCHEDULED` or `IN_PROGRESS`
    — divided by their `max_open_claims`; that load ratio is capped at 1, subtracted from
    1, and multiplied by 100, so an idle adjuster contributes 100 points and a fully loaded
    one contributes zero."
    PRD §3.3: "The result is clamped so that it is not below 0 and not above 100, and only
    then rounded half up to 2 decimal places into `surge_capacity_score`."
    PRD §2.10: "The ledger has no status filter and no time window: it is append-only,
    entries are never retracted, and a reversal is itself an entry that participates in the
    sum rather than deleting its target."

    Design: Corner/cross_cutting_complexity_layers/corner_ccl_cascade_assignment_cancel_regresses_claim_but_not_reserves
    """
    event = _declared_event(api, "CAT-2026-128")
    claim = _triaged_claim(api, event["id"], "POL-1012")
    assert claim["inspection_mode"] == "DESK", "8000 first notice on a FAST_TRACK claim is desk work"
    adjuster = _desk_adjuster(api)

    assignment = validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim["id"],
                "mode": "DESK",
                "window_start_utc": "2026-09-01T00:00:00.000Z",
                "window_end_utc": "2026-09-02T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        201,
    )
    assert validate_success(api.get_claim(claim["id"], CE))["handling_status"] == (
        "INSPECTION_PENDING"
    ), "scheduling pulls the claim onto the inspection track"

    cancelled = validate_success(api.cancel_inspection_assignment(assignment["id"], DC))
    assert cancelled["status"] == "CANCELLED"

    after_claim = validate_success(api.get_claim(claim["id"], CE))
    assert after_claim["handling_status"] == "TRIAGED", (
        "no live assignment remains, so the claim regresses to TRIAGED"
    )
    assert_money_equals(after_claim["case_reserve"], 28750.00, "case_reserve")

    after_adjuster = validate_success(api.get_adjuster(adjuster["id"], DC))
    assert after_adjuster["open_assignment_count"] == 0
    # (1 - 0/5) * 100 - 0 credential - 0 fatigue + 5 desk bonus = 105, clamped to 100.
    assert_money_equals(after_adjuster["surge_capacity_score"], 100.00, "surge_capacity_score")

    _, meta = validate_paginated(api.list_reserve_entries(CE, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 1, "cancelling an assignment appends no ledger row"


def test_confirm_rejected_for_room_shortage_fires_none_of_its_side_effect_links(api):
    """PRD §3.5: "Finally, unless `role_type` is `DESK`, the deployment must name a housing
    block, that block must be `ACTIVE`, and its `rooms_available` must be at least the
    deployment's `rooms_reserved`, failing which the answer is
    `ERR_HOUSING_CAPACITY_EXCEEDED`."
    PRD §3.5: "Confirmation then does five things at once. It stamps `provisional_cost` and
    `surge_premium_tier` from the provisional variant of the cost rule. It adds the
    deployment's `rooms_reserved` to the block's `rooms_occupied` and recomputes
    `rooms_available`, taking the block `ACTIVE → EXHAUSTED` if availability lands on zero.
    It moves the adjuster `AVAILABLE → DEPLOYED` and recomputes their surge-capacity score.
    And it recomputes the parent event's `surge_adjuster_count` and posture."
    PRD §3.5: "The created deployment is `REQUESTED`, its `selection_reason` records
    `EXPLICIT_ADJUSTER` when the caller pinned an adjuster and `SELECTOR_RANKED` when the
    server chose, and both `provisional_cost` and `final_settled_cost` read 0.00 because a
    requested deployment has not been priced and has drawn no rooms."
    PRD §3.1: "`surge_adjuster_count` is the number of deployments on the event whose
    status is `CONFIRMED` or `ON_SITE`."

    Design: Corner/cross_cutting_complexity_layers/corner_ccl_cascade_rejected_confirm_fires_no_partial_links
    """
    event = _declared_event(api, "CAT-2026-129")
    block = _two_room_block(api, event["id"])
    validate_success(api.open_housing_block(block["id"], DC))
    adjuster = _desk_adjuster(api)

    deployment = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "FIELD",
                "window_start_utc": "2026-09-01T00:00:00.000Z",
                "window_end_utc": "2026-09-06T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
                "housing_block_id": block["id"],
                "rooms_reserved": 4,
            },
            DC,
        ),
        201,
    )

    rejected = api.confirm_deployment(deployment["id"], DC)
    validate_error(rejected, ApiErrorId.ERR_HOUSING_CAPACITY_EXCEEDED, 409)

    after_block = validate_success(api.get_housing_block(block["id"], DC))
    assert after_block["status"] == "ACTIVE", "the room draw link never fired"
    assert after_block["rooms_occupied"] == 0
    assert after_block["rooms_available"] == 2

    after_adjuster = validate_success(api.get_adjuster(adjuster["id"], DC))
    assert after_adjuster["deployment_status"] == "AVAILABLE", "the adjuster-lock link never fired"

    after_deployment = validate_success(api.get_deployment(deployment["id"], DC))
    assert after_deployment["status"] == "REQUESTED"
    assert_money_equals(after_deployment["provisional_cost"], 0.00, "provisional_cost")

    after_event = validate_success(api.get_event(event["id"], CM))
    assert after_event["surge_adjuster_count"] == 0, "no deployment reached CONFIRMED"


# ---------------------------------------------------------------------------
# Both loss-estimate methods minted at one clock instant
# ---------------------------------------------------------------------------
def test_two_snapshot_methods_at_one_instant_leave_the_earlier_one_as_the_headline(api):
    """PRD §3.8: "Both methods share a common base: the `reported_component` is the event's
    `incurred_total`, that is its `case_reserve_total` plus its `paid_total`."
    PRD §3.8: "Count the distinct claims among the event's `INITIAL_CASE` ledger entries to
    get the reported claim count."
    PRD §3.8: "The `ibnr_component` is the average incurred per claim multiplied by the
    ultimate claim count less the reported claim count (with that difference floored at
    zero), the whole product floored at 0.00 and rounded to 2 decimal places."
    PRD §3.1: "`gross_loss_estimate` mirrors the `gross_estimate` of the event's latest
    loss-estimate snapshot — the one with the greatest `computed_at_utc`, with ties broken
    in favour of the earliest `created_at` — and reads 0.00 when the event has no snapshot."

    Design: Corner/cross_cutting_complexity_layers/corner_ccl_dual_variant_both_snapshot_methods_at_one_clock_instant
    """
    event = _declared_event(api, "CAT-2026-130")
    _triaged_claim(api, event["id"], "POL-1013")

    version_before_a = validate_success(api.get_event(event["id"], CM))["version"]
    snap_a = validate_success(
        api.create_loss_estimate(
            {
                "event_id": event["id"],
                "method": "EXPOSURE_BASED",
                "expected_event_version": version_before_a,
            },
            CM,
        ),
        201,
    )
    version_before_b = validate_success(api.get_event(event["id"], CM))["version"]

    snap_b = validate_success(
        api.create_loss_estimate(
            {
                "event_id": event["id"],
                "method": "INCURRED_DEVELOPMENT",
                "expected_event_version": version_before_b,
            },
            CM,
        ),
        201,
    )
    # reported 28750.00 over 1 reported claim; ultimate claims ceil(1000 * 0.1000 * 0.35)
    # = 35, so ibnr = 28750.00 * 34 = 977500.00.
    assert snap_b["method"] == "INCURRED_DEVELOPMENT"
    assert_money_equals(snap_b["gross_estimate"], 1006250.00, "gross_estimate")
    assert_money_equals(snap_b["ibnr_component"], 977500.00, "ibnr_component")
    assert_money_equals(snap_b["reported_component"], 28750.00, "reported_component")
    assert snap_b["input_reserve_sequence_high_water"] == 1, (
        "the INITIAL_CASE row from triage is the only ledger entry"
    )
    assert snap_b["stale"] is False

    exposure_rows, exposure_meta = validate_paginated(
        api.list_loss_estimates(
            CM, params={"event_id": event["id"], "method": "EXPOSURE_BASED"}
        )
    )
    assert exposure_meta["total_count"] == 1
    assert exposure_rows[0]["id"] == snap_a["id"]
    assert_money_equals(exposure_rows[0]["gross_estimate"], 35000000.00, "gross_estimate A")
    assert_money_equals(exposure_rows[0]["ibnr_component"], 34971250.00, "ibnr_component A")

    after = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(after["gross_loss_estimate"], 35000000.00, "gross_loss_estimate")

    _, all_meta = validate_paginated(
        api.list_loss_estimates(CM, params={"event_id": event["id"]})
    )
    assert all_meta["total_count"] == 2, "both snapshots are stored"


# ---------------------------------------------------------------------------
# Derived event-level fields reconciling with their sources
# ---------------------------------------------------------------------------
def test_event_totals_are_rederived_from_the_two_row_reserve_ledger(api):
    """PRD §2.10: "At any instant, an event's `incurred_total` equals the sum, over every
    reserve entry belonging to that event, of the entry's change to case reserve plus its
    change to paid loss, rounded to 2 decimal places."
    PRD §3.1: "`case_reserve_total` and `paid_total` are the sums of the case-reserve and
    paid movements of every ledger entry belonging to the event, each to 2 decimal places,
    and `incurred_total` is their sum — the conserved quantity of §2.10."
    PRD §3.8: "The append is written with the next per-event `sequence_no`, an
    `effective_utc` of the current instant, and a null `reverses_entry_id`."
    PRD §3.8: "Afterwards the claim's `case_reserve` and `paid_amount`, and the event's
    `case_reserve_total`, `paid_total` and `incurred_total`, are recomputed, snapshots below
    the new high-water mark go stale, and posture is recomputed."

    Design: Corner/cross_cutting_complexity_layers/corner_ccl_derived_event_totals_reconcile_with_reserve_ledger
    """
    event = _declared_event(api, "CAT-2026-131")
    claim = _triaged_claim(api, event["id"], "POL-1014")

    entry = validate_success(
        api.create_reserve_entry(
            claim["id"],
            {
                "expected_claim_version": claim["version"],
                "entry_type": "REVISION",
                "delta_case_reserve": 1000,
                "delta_paid": 0,
                "memo": "adjuster field note uplift",
            },
            CE,
        ),
        201,
    )
    assert entry["sequence_no"] == 2, "the INITIAL_CASE row took sequence_no 1"
    assert_money_equals(entry["delta_case_reserve"], 1000.00, "delta_case_reserve")

    after_claim = validate_success(api.get_claim(claim["id"], CE))
    assert_money_equals(after_claim["case_reserve"], 29750.00, "case_reserve")
    assert_money_equals(after_claim["paid_amount"], 0.00, "paid_amount")

    after_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(after_event["case_reserve_total"], 29750.00, "case_reserve_total")
    assert_money_equals(after_event["paid_total"], 0.00, "paid_total")
    assert_money_equals(after_event["incurred_total"], 29750.00, "incurred_total")

    _, meta = validate_paginated(api.list_reserve_entries(CE, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 2, "28750.00 opening row plus the 1000.00 revision"


def test_housing_committed_cost_counts_a_pending_block_and_drops_a_released_one(api):
    """PRD §3.1: "`housing_committed_cost` sums, over every housing block on the event whose
    `status` is `PENDING`, `ACTIVE` or `EXHAUSTED`, that block's `nightly_rate` multiplied by
    its `rooms_total` multiplied by its `block_night_count`, to 2 decimal places; released
    blocks drop out of the sum entirely."
    PRD §3.4: "From that span the system computes `block_night_count`, the number of whole
    days from `block_start_date` up to but not including `block_end_date`."
    PRD §3.4: "Releasing a block hands the inventory back to the hotel and is available from
    `PENDING`, `ACTIVE` or `EXHAUSTED`; a block already `RELEASED` is refused with
    `ERR_HOUSING_NOT_RELEASABLE`."
    PRD §3.4: "Releasing from `ACTIVE` recomputes the parent event's
    `housing_committed_cost`, since released blocks drop out of that sum."

    Design: Corner/cross_cutting_complexity_layers/corner_ccl_derived_housing_committed_cost_counts_pending_and_drops_released
    """
    event = _declared_event(api, "CAT-2026-132")
    block = _two_room_block(api, event["id"])
    assert block["status"] == "PENDING"

    while_pending = validate_success(api.get_event(event["id"], CM))
    # 200.00 nightly * 2 rooms * 7 nights = 2800.00, committed while still PENDING.
    assert_money_equals(
        while_pending["housing_committed_cost"], 2800.00, "housing_committed_cost while PENDING"
    )

    validate_success(api.open_housing_block(block["id"], DC))
    while_active = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(
        while_active["housing_committed_cost"], 2800.00, "housing_committed_cost while ACTIVE"
    )

    released = validate_success(api.release_housing_block(block["id"], DC))
    assert released["status"] == "RELEASED"
    assert released["block_night_count"] == 7, "2026-09-01 up to but not including 2026-09-08"

    after = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(
        after["housing_committed_cost"], 0.00, "housing_committed_cost after release"
    )

    rows, meta = validate_paginated(
        api.list_housing_blocks(DC, params={"event_id": event["id"], "status": "RELEASED"})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == block["id"]


def test_confirm_draws_both_rooms_prices_the_deployment_and_leaves_settled_cost_at_zero(api):
    """PRD §3.5: "Confirmation then does five things at once. It stamps `provisional_cost`
    and `surge_premium_tier` from the provisional variant of the cost rule. It adds the
    deployment's `rooms_reserved` to the block's `rooms_occupied` and recomputes
    `rooms_available`, taking the block `ACTIVE → EXHAUSTED` if availability lands on zero.
    It moves the adjuster `AVAILABLE → DEPLOYED` and recomputes their surge-capacity score.
    And it recomputes the parent event's `surge_adjuster_count` and posture."
    PRD §3.5: "Step two computes labour: the adjuster's `daily_rate` multiplied by a rate
    factor and by the nights, rounded to 2 decimal places, where the rate factor is exactly
    1 for a `STAFF` adjuster and 1.35 for an `INDEPENDENT` one."
    PRD §3.5: "Step four picks the tier **from that subtotal alone, never from the
    post-premium total**, so no iteration is needed and the answer is well-defined in a
    single pass: a subtotal of 20000.00 or more is `TIER_HIGH` at a premium rate of 11
    percent; a subtotal of 5000.00 or more but below 20000.00 is `TIER_MID` at 6 percent;
    anything below 5000.00 is `TIER_NONE` at zero."
    PRD §3.5: "The **provisional** variant, stamped into `provisional_cost` at confirmation,
    uses the deployment's full requested `window_end_utc` as the settle-end instant and
    treats per-diem eligibility as 1 unconditionally, so an independent adjuster with a
    hotel room is charged per-diem *and* housing."
    PRD §3.1: "`deployment_settled_cost` sums the `final_settled_cost` of every deployment
    on the event that has reached `DEMOBILIZED`, to 2 decimal places."

    Design: Corner/cross_cutting_complexity_layers/corner_ccl_derived_rooms_and_provisional_cost_after_confirm
    """
    event = _declared_event(api, "CAT-2026-133")
    block = _two_room_block(api, event["id"])
    validate_success(api.open_housing_block(block["id"], DC))
    adjuster = _desk_adjuster(api)

    deployment = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "FIELD",
                "window_start_utc": "2026-09-01T00:00:00.000Z",
                "window_end_utc": "2026-09-06T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
                "housing_block_id": block["id"],
                "rooms_reserved": 2,
            },
            DC,
        ),
        201,
    )

    confirmed = validate_success(api.confirm_deployment(deployment["id"], DC))
    # 5 nights: labour 700*1*5 = 3500.00, per diem 100*5 = 500.00, housing 200*2*5
    # = 2000.00 -> subtotal 6000.00 -> TIER_MID at 6% -> 360.00 premium -> 6360.00.
    assert confirmed["status"] == "CONFIRMED"
    assert_money_equals(confirmed["provisional_cost"], 6360.00, "provisional_cost")
    assert confirmed["surge_premium_tier"] == "TIER_MID"
    assert_money_equals(confirmed["final_settled_cost"], 0.00, "final_settled_cost")

    after_block = validate_success(api.get_housing_block(block["id"], DC))
    assert after_block["status"] == "EXHAUSTED", "rooms_available landed on zero"
    assert after_block["rooms_occupied"] == 2
    assert after_block["rooms_available"] == 0

    after_adjuster = validate_success(api.get_adjuster(adjuster["id"], DC))
    assert after_adjuster["deployment_status"] == "DEPLOYED"

    after_event = validate_success(api.get_event(event["id"], CM))
    assert after_event["surge_adjuster_count"] == 1
    assert_money_equals(
        after_event["deployment_settled_cost"], 0.00, "deployment_settled_cost"
    )
    assert_money_equals(after_event["housing_committed_cost"], 2800.00, "housing_committed_cost")
