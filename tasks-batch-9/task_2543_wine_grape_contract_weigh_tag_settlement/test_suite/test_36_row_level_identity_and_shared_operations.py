"""Three consequences of the fact that one of the six roles is backed by a persisted entity while
the other five are not. A producer's authorisation is decided per row, by comparing the acting
identity with the producer reached from the target — so a second, entirely legitimate producer is
still a stranger to the first one's paperwork. The recorded operator identity is what makes
segregation of duties enforceable at the scale house. And where two roles genuinely share a write,
both paths must be equally functional and land in the same ledger.
"""
from test_helpers import (
    COORDINATOR,
    LAB_TECH,
    MANAGER,
    SCALE_OPERATOR_USER_ID,
    ApiErrorId,
    accept_contract,
    book_appointment,
    cancel_appointment,
    create_allocation,
    create_block,
    create_contract,
    create_delivery_appointment_payload,
    create_grading_payload,
    create_grower,
    create_lane_payload,
    create_sampling_crew_payload,
    deliver_gross_load,
    make_grower_headers,
    make_lab_tech_headers,
    move_clock,
    read_appointment,
    read_block,
    read_contract,
    read_lane,
    read_weigh_tag,
    setup_harvest_ready,
    setup_offered_contract,
    setup_scheduled_appointment,
    setup_single_load_on_pad,
    validate_error,
    validate_paginated,
    validate_success,
    weigh_tag_version,
)

SETUP_AT = "2026-08-01T00:00:00Z"

OFFERED_PRICE_PER_TON_CENTS = 450000
A_PRICE_THE_STRANGER_WOULD_PREFER = 600000


# --- The producer role is authorised row by row -------------------------------------------


def _two_producers_one_offer_between_them() -> dict:
    """Producer A holds an OFFERED contract over its own block. Producer B is a fully registered
    producer with a block, a contract and an allocation of its own, so its role is beyond
    question and only the row it is aiming at is not its own."""
    move_clock(SETUP_AT)
    ctx = setup_offered_contract({"contract_code": "GC-OWNER-A"})

    stranger = create_grower(name="Stonegate Ranch")
    stranger_block = create_block(stranger["id"])
    stranger_contract = create_contract(stranger["id"], ctx["spec"]["id"])
    create_allocation(stranger_contract["id"], stranger_block["id"])

    ctx["stranger"] = stranger
    ctx["stranger_headers"] = make_grower_headers(stranger["id"])
    ctx["stranger_block"] = stranger_block
    ctx["stranger_contract"] = stranger_contract
    return ctx


def test_a_stranger_cannot_accept_another_producers_offer(api):
    """`Grower` is a permitted role on the acceptance endpoint, so the only thing that can refuse
    this call is the comparison between the acting identity and the contract's producer.

    PRD: "Concretely, a contract action is permitted only when the contract's `grower_id` equals
    `X-User-ID`; a block read is permitted only when the block's `grower_id` equals `X-User-ID`"

    Design: Corner/rbac/grower_cannot_act_on_another_producers_rows
    """
    ctx = _two_producers_one_offer_between_them()

    validate_error(
        api.accept_contract(ctx["contract"]["id"], ctx["stranger_headers"]),
        ApiErrorId.ERR_NOT_CONTRACT_GROWER.value,
        403,
    )


def test_a_stranger_cannot_reprice_another_producers_contract(api):
    """The counter path mutates the negotiated price, so it is guarded identically to the accept
    path rather than being left open because it merely proposes something.

    PRD: "Any attempt by a producer to act on another producer's rows is refused with
    `ERR_NOT_CONTRACT_GROWER` and HTTP 403."

    Design: Corner/rbac/grower_cannot_act_on_another_producers_rows
    """
    ctx = _two_producers_one_offer_between_them()

    validate_error(
        api.counter_contract(
            ctx["contract"]["id"],
            {"counter_base_price_per_ton_cents": A_PRICE_THE_STRANGER_WOULD_PREFER},
            ctx["stranger_headers"],
        ),
        ApiErrorId.ERR_NOT_CONTRACT_GROWER.value,
        403,
    )


def test_the_ownership_rule_covers_reads_of_a_block(api):
    """A block read is a read and still refused: the rule is about the producer reference on the
    row, not about whether the request would have changed anything.

    PRD: "ownership checks on any resource that references a `Grower` compare the resource's
    producer reference to `X-User-ID`."

    Design: Corner/rbac/grower_cannot_act_on_another_producers_rows
    """
    ctx = _two_producers_one_offer_between_them()

    validate_error(
        api.get_vineyard_block(ctx["block"]["id"], ctx["stranger_headers"]),
        ApiErrorId.ERR_NOT_CONTRACT_GROWER.value,
        403,
    )
    assert read_block(ctx["stranger_block"]["id"], ctx["stranger_headers"])["id"] == (
        ctx["stranger_block"]["id"]
    )


def test_the_ownership_rule_covers_reads_of_a_contract(api):
    """The stranger cannot even see the terms it was trying to sign, while its own contract reads
    back perfectly well through the very same headers.

    PRD: "(3) a `Grower` acts only on its own rows, else `ERR_NOT_CONTRACT_GROWER`, on every
    endpoint a `Grower` is permitted to call"

    Design: Corner/rbac/grower_cannot_act_on_another_producers_rows
    """
    ctx = _two_producers_one_offer_between_them()

    validate_error(
        api.get_grape_contract(ctx["contract"]["id"], ctx["stranger_headers"]),
        ApiErrorId.ERR_NOT_CONTRACT_GROWER.value,
        403,
    )
    assert read_contract(ctx["stranger_contract"]["id"], ctx["stranger_headers"])["id"] == (
        ctx["stranger_contract"]["id"]
    )


def test_none_of_the_strangers_attempts_touched_the_offer(api):
    """Four refusals later the contract is exactly where the winery left it, at the price the
    winery named.

    PRD: "Read one contract with both state dimensions, the derived caps and the settlement money
    fields."

    Design: Corner/rbac/grower_cannot_act_on_another_producers_rows
    """
    ctx = _two_producers_one_offer_between_them()
    api.accept_contract(ctx["contract"]["id"], ctx["stranger_headers"])
    api.counter_contract(
        ctx["contract"]["id"],
        {"counter_base_price_per_ton_cents": A_PRICE_THE_STRANGER_WOULD_PREFER},
        ctx["stranger_headers"],
    )

    contract = validate_success(api.get_grape_contract(ctx["contract"]["id"], MANAGER))
    assert contract["lifecycle_status"] == "OFFERED"
    assert contract["base_price_per_ton_cents"] == OFFERED_PRICE_PER_TON_CENTS


def test_the_owning_producer_sends_the_identical_call_and_is_accepted(api):
    """The acceptance was never the problem: with the acting identity set to the contract's own
    producer the same request goes through, which isolates the identity check from every other
    guard on that endpoint.

    PRD: "When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the acting `Grower` entity"

    Design: Corner/rbac/grower_cannot_act_on_another_producers_rows
    """
    ctx = _two_producers_one_offer_between_them()
    api.accept_contract(ctx["contract"]["id"], ctx["stranger_headers"])

    accepted = accept_contract(ctx["contract"]["id"], ctx["grower"]["id"])
    assert accepted["lifecycle_status"] == "ACTIVE"


# --- The weigher may not grade its own load -----------------------------------------------

DELIVERED_TONS = 20.000
TARE_WEIGHT_LBS = 17000

# The reading the weigher would have liked to file, and the one an independent lab files.
A_GENEROUS_READING = {"brix": 26.0, "ta_gl": 6.5, "ph": 3.40, "rot_pct": 0.5, "mog_pct": 0.2}
AN_INDEPENDENT_READING = {"brix": 23.0, "ta_gl": 6.5, "ph": 3.40, "rot_pct": 1.0, "mog_pct": 0.5}

# Same person, lab hat on: the role is right and only the recorded identity is wrong.
THE_WEIGHER_WEARING_THE_LAB_HAT = make_lab_tech_headers(SCALE_OPERATOR_USER_ID)


def _a_load_tared_and_waiting_for_the_lab() -> dict:
    """One 20.000-net-ton load at `NET_FINAL` and `PENDING`, both weight passes taken by the
    scale-house operator whose identity the tag now carries."""
    return setup_single_load_on_pad(
        contract_overrides={"contract_code": "GC-SOD"},
        net_tons=DELIVERED_TONS,
        tare_weight_lbs=TARE_WEIGHT_LBS,
        estimated_tons=DELIVERED_TONS,
        planned_tons=DELIVERED_TONS,
    )


def _a_load_still_on_the_inbound_scale() -> dict:
    """The same chain stopped one pass earlier: the gross is captured, so the tag is at
    `GROSS_CAPTURED` and grading it would ordinarily be a state error."""
    ctx = setup_harvest_ready(
        contract_overrides={"contract_code": "GC-SOD-GROSS"},
        estimated_tons=DELIVERED_TONS,
    )
    setup_scheduled_appointment(ctx, planned_tons=DELIVERED_TONS)
    deliver_gross_load(ctx, DELIVERED_TONS, tare_weight_lbs=TARE_WEIGHT_LBS)
    return ctx


def _grade_as(api, tag_id: str, headers: dict, reading: dict):
    return api.create_grading(
        tag_id, create_grading_payload(weigh_tag_version(tag_id), **reading), headers
    )


def test_the_tag_carries_the_identity_of_whoever_weighed_it(api):
    """The comparison the grading endpoint makes is against a value stamped at gross capture, so
    the tag has to be carrying it before any grading is attempted.

    PRD: "the server records it where a transition demands it — as `captured_by_user_id` on a
    weigh tag when a `ScaleOperator` opens the tag, and as `graded_by_user_id` on a grading row
    when a grader records one — but it is never compared to any entity's `id`."

    Design: Corner/rbac/same_user_cannot_weigh_and_grade_the_same_load
    """
    ctx = _a_load_tared_and_waiting_for_the_lab()

    tag = read_weigh_tag(ctx["tag"]["id"], MANAGER)
    assert tag["captured_by_user_id"] == SCALE_OPERATOR_USER_ID
    assert tag["weigh_status"] == "NET_FINAL"
    assert tag["disposition"] == "PENDING"
    assert tag["grade_count"] == 0


def test_the_operator_who_weighed_the_load_may_not_grade_it(api):
    """The role on the request is exactly the one the endpoint wants and the expected version is
    current; the request still fails, because the acting identity is the one on the tag.

    PRD: "When a grading is recorded, the acting `X-User-ID` must differ from the
    `captured_by_user_id` stored on the weigh tag being graded; if the same person weighed and now
    attempts to grade the load, the request is refused with `ERR_SOD_SAME_USER_GRADING` and HTTP
    403."

    Design: Corner/rbac/same_user_cannot_weigh_and_grade_the_same_load
    """
    ctx = _a_load_tared_and_waiting_for_the_lab()

    validate_error(
        _grade_as(api, ctx["tag"]["id"], THE_WEIGHER_WEARING_THE_LAB_HAT, A_GENEROUS_READING),
        ApiErrorId.ERR_SOD_SAME_USER_GRADING.value,
        403,
    )


def test_the_refused_grading_left_the_load_completely_untouched(api):
    """Nothing was written and no counter moved, so the next attempt cannot be blamed on a stale
    version — the tag's own version is exactly what it was.

    PRD: "A tag also carries `grade_count`, starting at 0, `active_adjustment_pct`, null until a
    grading exists"

    Design: Corner/rbac/same_user_cannot_weigh_and_grade_the_same_load
    """
    ctx = _a_load_tared_and_waiting_for_the_lab()
    version_before = read_weigh_tag(ctx["tag"]["id"], MANAGER)["version"]

    _grade_as(api, ctx["tag"]["id"], THE_WEIGHER_WEARING_THE_LAB_HAT, A_GENEROUS_READING)

    tag = read_weigh_tag(ctx["tag"]["id"], MANAGER)
    assert tag["grade_count"] == 0
    assert tag["disposition"] == "PENDING"
    assert tag["version"] == version_before
    assert tag["active_adjustment_pct"] is None


def test_a_different_lab_user_grades_the_very_same_load(api):
    """The load is not poisoned by the refusal: an independent grader takes it through the whole
    pipeline, so the guard is about who acts and not about the tag.

    PRD: "The acting `X-User-ID` is stored on the new grading row as `graded_by_user_id`, and it
    must differ from the tag's `captured_by_user_id` — the segregation-of-duties rule that
    outranks every state question on this endpoint."

    Design: Corner/rbac/same_user_cannot_weigh_and_grade_the_same_load
    """
    ctx = _a_load_tared_and_waiting_for_the_lab()
    _grade_as(api, ctx["tag"]["id"], THE_WEIGHER_WEARING_THE_LAB_HAT, A_GENEROUS_READING)

    grading = validate_success(
        _grade_as(api, ctx["tag"]["id"], LAB_TECH, AN_INDEPENDENT_READING), 201
    )
    assert grading["graded_by_user_id"] != SCALE_OPERATOR_USER_ID

    tag = read_weigh_tag(ctx["tag"]["id"], MANAGER)
    assert tag["disposition"] == "ACCEPTED"
    assert tag["grade_count"] == 1


def test_the_duties_rule_answers_before_the_weight_state_does(api):
    """A tag that has only been grossed could not be graded by anybody; asked by the weigher, the
    refusal still names the duties rule rather than the weight state.

    PRD: "(4) the grader is not the operator who weighed the load, else
    `ERR_SOD_SAME_USER_GRADING`, on the grading create only."

    Design: Corner/rbac/same_user_cannot_weigh_and_grade_the_same_load
    """
    ctx = _a_load_still_on_the_inbound_scale()
    assert read_weigh_tag(ctx["tag"]["id"], MANAGER)["weigh_status"] == "GROSS_CAPTURED"

    validate_error(
        _grade_as(api, ctx["tag"]["id"], THE_WEIGHER_WEARING_THE_LAB_HAT, AN_INDEPENDENT_READING),
        ApiErrorId.ERR_SOD_SAME_USER_GRADING.value,
        403,
    )
    validate_error(
        _grade_as(api, ctx["tag"]["id"], LAB_TECH, AN_INDEPENDENT_READING),
        ApiErrorId.ERR_TAG_WEIGH_STATE_INVALID.value,
        409,
    )


# --- One write, two peers ------------------------------------------------------------------

# Two 20.000-ton slots on the same lane and the same date: 40.000 tons against a daily budget of
# 80.000, the second opening exactly one 30-minute cleanout buffer after the first closes.
CALLED_TONS = 40.000
SLOT_TONS = 20.000
BOTH_SLOTS_TONS = 40.000
FIRST_SLOT = ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z")
SECOND_SLOT = ("2026-08-25T16:30:00Z", "2026-08-25T18:30:00Z")


def _an_acknowledged_call_on_an_open_lane() -> dict:
    """An ACTIVE 80.000-ton contract, a pick-ready allocated block, one open lane and one
    ACKNOWLEDGED pick call — the point at which either party may reserve a slot."""
    move_clock(SETUP_AT)
    return setup_harvest_ready(
        contract_overrides={"contract_code": "GC-PEER", "committed_tons": 80.000},
        estimated_tons=CALLED_TONS,
    )


def _book_as(api, ctx: dict, headers: dict, slot):
    return api.create_delivery_appointment(
        create_delivery_appointment_payload(
            ctx["pick_call"]["id"], ctx["lane"]["id"], slot[0], slot[1], SLOT_TONS
        ),
        headers,
    )


def _both_parties_book_a_slot(ctx: dict) -> dict:
    """The producer takes the first slot and the harvest desk takes the second, on the same lane
    and against the same call."""
    ctx["producers_slot"] = book_appointment(
        ctx["pick_call"]["id"],
        ctx["lane"]["id"],
        FIRST_SLOT[0],
        FIRST_SLOT[1],
        SLOT_TONS,
        ctx["grower_headers"],
    )
    ctx["desks_slot"] = book_appointment(
        ctx["pick_call"]["id"],
        ctx["lane"]["id"],
        SECOND_SLOT[0],
        SECOND_SLOT[1],
        SLOT_TONS,
        COORDINATOR,
    )
    return ctx


def test_the_producer_may_reserve_its_own_crush_pad_slot(api):
    """The producer is a first-class author of a booking, not merely a party the winery books on
    behalf of, and its row is created like any other.

    PRD: "Reserve a crush-pad slot against an acknowledged pick call, with `pick_call_id`,
    `lane_id`, `window_start`, `window_end` and `planned_tons`. | HarvestCoordinator, Grower"

    Design: Corner/rbac/peer_roles_share_the_delivery_appointment_booking_operation
    """
    ctx = _an_acknowledged_call_on_an_open_lane()

    booked = validate_success(_book_as(api, ctx, ctx["grower_headers"], FIRST_SLOT), 201)
    assert booked["status"] == "SCHEDULED"
    assert booked["window_start"] == FIRST_SLOT[0]


def test_the_harvest_desk_may_reserve_a_slot_on_the_same_call(api):
    """The other half of the shared write, exercised against the same call and the same lane so
    the two paths are genuinely interchangeable.

    PRD: "Endpoints that bring a brand-new resource row into existence respond with HTTP 201
    Created"

    Design: Corner/rbac/peer_roles_share_the_delivery_appointment_booking_operation
    """
    ctx = _an_acknowledged_call_on_an_open_lane()
    validate_success(_book_as(api, ctx, ctx["grower_headers"], FIRST_SLOT), 201)

    booked = validate_success(_book_as(api, ctx, COORDINATOR, SECOND_SLOT), 201)
    assert booked["status"] == "SCHEDULED"
    assert booked["window_start"] == SECOND_SLOT[0]


def test_the_two_bookings_are_one_collection_of_two_rows(api):
    """The call's appointments are listed from the winery side, and nothing distinguishes the row
    the producer created from the row the desk created.

    PRD: "List delivery appointments; filter by `pick_call_id`, `lane_id` or `status`. |
    GrowerRelationsManager, HarvestCoordinator, ScaleOperator, QualityLabTech"

    Design: Corner/rbac/peer_roles_share_the_delivery_appointment_booking_operation
    """
    ctx = _both_parties_book_a_slot(_an_acknowledged_call_on_an_open_lane())

    rows, meta = validate_paginated(
        api.list_delivery_appointments(
            COORDINATOR, params={"pick_call_id": ctx["pick_call"]["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {
        ctx["producers_slot"]["id"],
        ctx["desks_slot"]["id"],
    }
    assert {row["status"] for row in rows} == {"SCHEDULED"}


def test_the_lane_ledger_does_not_care_who_booked(api):
    """Both reservations count against the same lane exactly alike, so the derived ledger reads
    forty tons across two live slots.

    PRD: "Two derived figures round out the row: `committed_tons`, the sum of `planned_tons` over
    the lane's appointments in status `SCHEDULED` or `ARRIVED` to 3 decimals, and
    `scheduled_appointment_count`, the count of those same appointments."

    Design: Corner/rbac/peer_roles_share_the_delivery_appointment_booking_operation
    """
    ctx = _both_parties_book_a_slot(_an_acknowledged_call_on_an_open_lane())

    lane = read_lane(ctx["lane"]["id"])
    assert float(lane["committed_tons"]) == BOTH_SLOTS_TONS
    assert lane["scheduled_appointment_count"] == 2


def test_releasing_a_slot_is_not_a_shared_operation(api):
    """Sharing the create does not imply sharing the cancel: the producer cannot release even the
    slot it booked itself, and the row stays scheduled.

    PRD: "Release a scheduled slot with an optional `reason` (`SCHEDULED` to `CANCELLED`). |
    HarvestCoordinator"

    Design: Corner/rbac/peer_roles_share_the_delivery_appointment_booking_operation
    """
    ctx = _both_parties_book_a_slot(_an_acknowledged_call_on_an_open_lane())

    validate_error(
        api.cancel_delivery_appointment(
            ctx["producers_slot"]["id"], ctx["grower_headers"], {"reason": "Crew reassigned"}
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert read_appointment(ctx["producers_slot"]["id"])["status"] == "SCHEDULED"


def test_the_desk_releases_the_producers_slot_and_the_ledger_follows(api):
    """The row the producer created is fully within the harvest desk's gift to cancel, and the
    lane's derived figures fall back by exactly that one reservation.

    PRD: "The `HarvestCoordinator` may release a slot, driving `SCHEDULED → CANCELLED` with an
    optional `reason` in the body; cancellation is permitted only from `SCHEDULED`, any other
    status being `ERR_APPOINTMENT_NOT_OPEN`, and it recomputes the lane's `committed_tons` and
    `scheduled_appointment_count` and the pick call's `appointed_tons`."

    Design: Corner/rbac/peer_roles_share_the_delivery_appointment_booking_operation
    """
    ctx = _both_parties_book_a_slot(_an_acknowledged_call_on_an_open_lane())

    cancelled = cancel_appointment(ctx["producers_slot"]["id"], reason="Crew reassigned")
    assert cancelled["status"] == "CANCELLED"

    lane = read_lane(ctx["lane"]["id"])
    assert float(lane["committed_tons"]) == SLOT_TONS
    assert lane["scheduled_appointment_count"] == 1


def test_the_same_peer_pattern_holds_on_the_reference_writes(api):
    """The two receiving-side reference tables are shared between the producer-relations desk and
    the harvest desk in the same way, which is the pattern seen from the winery side.

    PRD: "Open a receiving lane with a mandatory `lane_code` and `daily_capacity_tons` plus
    optional `turnaround_buffer_minutes`, `max_load_tons` and `status`. | GrowerRelationsManager,
    HarvestCoordinator"

    Design: Corner/rbac/peer_roles_share_the_delivery_appointment_booking_operation
    """
    move_clock(SETUP_AT)

    validate_success(api.create_lane(create_lane_payload(), MANAGER), 201)
    validate_success(api.create_lane(create_lane_payload(), COORDINATOR), 201)
    validate_success(api.create_sampling_crew(create_sampling_crew_payload(), MANAGER), 201)
    validate_success(api.create_sampling_crew(create_sampling_crew_payload(), COORDINATOR), 201)
