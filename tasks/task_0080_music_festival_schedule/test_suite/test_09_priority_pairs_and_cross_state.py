"""Priority-pair validation conflicts (rule-5 in the difficulty
design) and the cross-entity-state preconditions (rule-7).

The PRD §2.6 prose pins two specific priority conflicts where two
validation rules would each reject the same request and the
numerically-earlier-category rule's error_id wins:

  Instance A (rule-5-instance-A) — the program-item-confirm pair on
  the (cross-entity-state, business-temporal) categories: the
  cross-state ERR_PROGRAM_VERSION_SUPERSEDED check at priority 6 vs
  the artist-multi-festival temporal-overlap ERR_ARTIST_MULTI_FESTIVAL_CONFLICT
  check at priority 11.  The state-category error wins because its
  category sits earlier in the evaluation order.

  Instance B (rule-5-instance-B) — the exposure-allocation-create
  pair on the (business-referential, business-fiscal) categories: the
  ERR_ARTIST_NOT_ELIGIBLE_FOR_TIER specialisation of the
  ERR_EXPOSURE_KIND_NOT_CONTRACTED referential check at priority 16
  vs the ERR_TIER_CONTRACT_UNITS_EXCEEDED fiscal-cap check at
  priority 19.  The referential-category error wins.

The PRD §3.5 cross-entity-state preconditions are the rule-7 ground
that the §1.6 error catalog names:

  Instance A — the program-item-confirm cross-state gate
  ERR_PROGRAM_VERSION_SUPERSEDED.
  Instance B — the sound-check schedule-PATCH cross-state gate
  ERR_PARENT_ITEM_NOT_READY (the parent ProgramItem is in CONFIRMED or
  ANNOUNCED) and ERR_TEAM_NOT_AVAILABLE (the team is in AVAILABLE).
  Instance C — the exposure-allocation deliver cross-state gate
  ERR_EXPOSURE_ALLOCATION_NOT_DELIVERABLE (the tied program item is
  in PERFORMED).

And the unrelated-but-clean ticketing-allowed-state gates:

  ERR_TICKET_TYPE_NOT_ACTIVE — issuance on a SUSPENDED type.
  ERR_TICKET_TYPE_TIE_INVALID — issuance after the tied item is
    cancelled (the cascade scrubs the tie list).

The full ticket-zone-capacity boundary precision pair is in
test_10_boundary_precision_and_zone.py — that's the rule-6 instance B
(strict-> on the post-increment integer count) and its zero-capacity-
edge ERR_TICKET_ZONE_NO_STAGE companion.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    AUDIT_HEADERS,
    AuditEventCategory,
    CANONICAL_FINAL_REFUND_CENTS,
    CANONICAL_PROVISIONAL_REFUND_CENTS,
    CATALOG_KINDS,
    LIAISON_HEADERS,
    PRODUCER_HEADERS,
    SPONSOR_HEADERS,
    STAGE_HEADERS,
    THRESHOLDS,
    TICKETING_HEADERS,
    add_exposure_allocation,
    add_program_item,
    add_program_version,
    add_sound_check_slot,
    add_sponsor_tier,
    add_stage,
    add_team,
    advance_clock_to,
    base_world,
    confirm_item,
    confirmed_item_with_scheduled_sound_check,
    confirmed_item_world,
    confirmed_published_world_with_ticket,
    create_and_apply_item_cancel,
    delivered_allocation_world,
    external_commitment,
    factories as F,
    fixtures as FIX,
    get_sponsor_tier_snapshot,
    get_success_data,
    issue_tickets,
    publish_version,
    read_audit_log,
    register_artist,
    run_waterfall,
    schedule_sound_check,
    seed_default_catalog,
    sponsor_tier_payload,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Rule 5 instance A — the cross-state-vs-business-temporal pair at the
# program-item confirm endpoint.  PRD §2.6 names the case verbatim.
# ---------------------------------------------------------------------------


def test_priority_pair_a_state_beats_business_temporal_at_program_item_confirm(api):
    """PRD §2.6 first specific priority-conflict sentence: "First,
    when a `POST /festivals/{festivalId}/program-items/{itemId}/confirm`
    request would fail both the cross-entity state check (because the
    item's `program_version_id` is not the festival's current
    published `current_program_version_id` — the program-version-
    superseded gate) and the business-temporal
    artist-multi-festival-overlap check, the cross-entity state check
    wins because its category sits earlier in the evaluation order.
    The state-category error is `ERR_PROGRAM_VERSION_SUPERSEDED` at
    HTTP 409; the business-temporal error is
    `ERR_ARTIST_MULTI_FESTIVAL_CONFLICT` at HTTP 409.  The client sees
    the state error."

    Construction: a festival with two program versions, V1 published
    so it's the current version, V2 left in DRAFT (so V2's items would
    fail the cross-state gate of PRD §3.3 "the item's
    `program_version_id` must equal the parent festival's
    `current_program_version_id`").  The artist on the V2-attached
    item has an external commitment whose half-open window strictly
    overlaps the candidate's half-open window, so the §2.6 priority-11
    ERR_ARTIST_MULTI_FESTIVAL_CONFLICT check would also fail.  Both
    rules are violated simultaneously; the §2.6 priority ordering
    says the state-category (priority 6) error wins over the
    business-temporal (priority 11) error.

    But wait — the cross-state error fires on the confirm endpoint
    when the item's program_version_id is on a version that's been
    SUPERSEDED, the §3.3 sentence "the cross-entity state error
    `ERR_PROGRAM_VERSION_SUPERSEDED` at HTTP 409 fires (this is the
    cross-entity state gate against the festival's pinned version,
    and before any version has yet published the gate is relaxed to
    'the `program_version_id` references a non-`WITHDRAWN`-
    non-`SUPERSEDED` version under the festival')".  So the
    SUPERSEDED version-id is the load-bearing setup: it requires a
    prior PUBLISHED version that has been superseded by a newer
    publish.  We arrange:

      V1 created, the bag's initial DRAFT version.  We add one item
        under V1, confirm it (the cross-state gate is relaxed pre-
        first-publish, so this confirm succeeds), then submit and
        publish V1.  Festival.current_program_version_id is V1.
      V2 created as a fresh DRAFT version with one item attached.
        Confirm V2's item — this succeeds because at this point V1
        is the current pinned version and V2's item references V2,
        which is not the current pinned version but the §3.3 prose
        on the confirm-time cross-state gate names the relaxed
        case "before any version has yet published the gate is
        relaxed to 'the program_version_id references a
        non-WITHDRAWN-non-SUPERSEDED version under the festival'".
        Wait — V1 has published, so the relaxed-gate clause does not
        apply.  The strict gate "the item's `program_version_id`
        must equal Festival.current_program_version_id" applies
        from the moment of the first publish onward.  The confirm
        on a V2-attached item with V1 as the current pinned version
        would therefore fail with ERR_PROGRAM_VERSION_SUPERSEDED.
        That is the exact construction we want.

    The artist on the V2 item has an external commitment that
    overlaps the V2 item's window — so the §2.6 priority-11 rule's
    error_id would also be a candidate.  Per the §2.6 prose the
    earlier-category error wins, so the test asserts the client sees
    ERR_PROGRAM_VERSION_SUPERSEDED, not
    ERR_ARTIST_MULTI_FESTIVAL_CONFLICT.

    Difficulty rule 5 instance A:
    # difficulty: priority_pair_validation_conflict/state_beats_business_temporal_on_programitem_confirm
    """
    bag = base_world(api, day_count=4, artist_tier="OPENER",
                     stage_zone_capacity=100)
    # V1 with one item, confirm it (pre-publish so the cross-state
    # gate of PRD §3.3 is relaxed), then publish V1 so the festival's
    # current_program_version_id points at V1.
    item1 = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=bag.artist_id,
                               stage_id=bag.stage_id,
                               start_time=bag.festival_start + 3600,
                               end_time=bag.festival_start + 3600 + 1800,
                               genre="rock", equipment_kit_codes=[]),
        LIAISON_HEADERS,
    ))
    confirm_item(api, bag, str(item1["id"]))
    publish_version(api, bag)
    # Now create V2, a fresh DRAFT version whose items will fail the
    # strict "program_version_id == current_program_version_id" gate
    # because the current pinned version is V1.
    v2 = get_success_data(api.create_program_version(
        bag.festival_id, F.program_version_payload(version_label="v2-draft"),
        PRODUCER_HEADERS,
    ))
    # An artist with an external commitment that overlaps the V2-item's
    # candidate window — this is the business-temporal failure that
    # would fire at priority 11 per PRD §2.6, against the cross-state
    # failure at priority 6.  The commitment's half-open window must
    # actually intersect the candidate's half-open window per the
    # PRD §3.5 multi-festival-overlap rule.
    cand_start = bag.festival_start + 2 * 86400 + 12 * 3600
    cand_end = cand_start + 3600
    # The commitment's window strictly overlaps the candidate's.
    overlap_commitment = external_commitment(
        festival_external_id="ConflictExt",
        start_time=cand_start - 1800,  # 30 minutes before candidate's start
        end_time=cand_start + 1800,    # 30 minutes after candidate's start
        city="ConflictCity",
    )
    artist_v2 = get_success_data(api.create_artist(
        F.artist_payload(stage_name="ConflictArtist",
                         tier="OPENER",
                         home_city="HC",
                         external_commitments=[overlap_commitment],
                         minimum_travel_buffer_hours=4),
        LIAISON_HEADERS,
    ))
    # Create the V2-attached item.  The create endpoint runs the
    # cross-state gate "the item's program_version_id is a
    # non-WITHDRAWN-non-SUPERSEDED version under the festival" — V2 is
    # in DRAFT, so the create itself is accepted.  The confirm endpoint
    # is where the strict equal-to-current gate is enforced.
    cand_item = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=str(v2["id"]),
                               artist_id=str(artist_v2["id"]),
                               stage_id=bag.stage_id,
                               start_time=cand_start, end_time=cand_end,
                               genre="rock", equipment_kit_codes=[]),
        LIAISON_HEADERS,
    ))
    # Confirm the V2-attached item.  Both gates would fail.  The PRD
    # §2.6 ordering says the state-category gate wins.
    resp = api.confirm_program_item(bag.festival_id, str(cand_item["id"]),
                                    LIAISON_HEADERS)
    # ERR_PROGRAM_VERSION_SUPERSEDED is the expected error, not the
    # business-temporal ERR_ARTIST_MULTI_FESTIVAL_CONFLICT.  PRD §2.6
    # pins the precedence.
    validate_error(resp, ApiErrorId.ERR_PROGRAM_VERSION_SUPERSEDED.value,
                   expected_status=409)


def test_priority_pair_a_temporal_fires_alone_when_state_is_fine(api):
    """Sanity-pair to the priority-A test above: when only the
    business-temporal artist-multi-festival overlap fires (with the
    cross-state version-pin gate satisfied — the item's
    `program_version_id` IS the festival's current pinned version),
    the client sees the temporal error
    `ERR_ARTIST_MULTI_FESTIVAL_CONFLICT` at HTTP 409.

    This pin proves the temporal-error code path exists in the
    implementation — without this evidence the prior test's "state
    beats temporal" assertion would have a vacuous-truth reading
    where the temporal rule simply isn't implemented.

    # difficulty: priority_pair_validation_conflict/state_beats_business_temporal_on_programitem_confirm
    """
    bag = base_world(api, day_count=3, artist_tier="OPENER",
                     stage_zone_capacity=100,
                     # The bag's default artist has no external commitments.
                     )
    # Publish V1 with one item so the festival is PUBLISHED.
    seed_item = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=bag.artist_id,
                               stage_id=bag.stage_id,
                               start_time=bag.festival_start + 3600,
                               end_time=bag.festival_start + 7200,
                               genre="g", equipment_kit_codes=[]),
        LIAISON_HEADERS,
    ))
    confirm_item(api, bag, str(seed_item["id"]))
    publish_version(api, bag)
    # Now register an artist with an external commitment that overlaps
    # the candidate window.
    cand_start = bag.festival_start + 1 * 86400 + 12 * 3600
    cand_end = cand_start + 3600
    overlap = external_commitment(festival_external_id="Other",
                                  start_time=cand_start - 1800,
                                  end_time=cand_end + 1800,
                                  city="X")
    artist = get_success_data(api.create_artist(
        F.artist_payload(stage_name="OverlapArtist", tier="OPENER",
                         home_city="X",
                         external_commitments=[overlap],
                         minimum_travel_buffer_hours=4),
        LIAISON_HEADERS,
    ))
    # The candidate's program_version_id is the festival's pinned V1
    # (the bag.version_id), so the cross-state gate passes.  The
    # candidate's stage_id is the bag's default stage.  The
    # multi-festival-overlap rule fires because the commitment's
    # window intersects the candidate's window.
    cand_resp = api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=str(artist["id"]),
                               stage_id=bag.stage_id,
                               start_time=cand_start, end_time=cand_end,
                               genre="g", equipment_kit_codes=[]),
        LIAISON_HEADERS,
    )
    # The PRD §3.3 narrative on the create endpoint says the
    # overlap-and-travel-buffer-and-multi-festival checks "all run at
    # creation time as advisory rejections — they reject the create
    # when violated".  So the create itself is the rejection point.
    # If the implementation makes the create advisory-accept and the
    # confirm authoritative-reject, the confirm's rejection is the
    # observation point.  We accept either point.
    if cand_resp.status_code in (400, 409, 422):
        validate_error(cand_resp,
                       ApiErrorId.ERR_ARTIST_MULTI_FESTIVAL_CONFLICT.value,
                       expected_status=409)
    else:
        # Advisorily accepted on create; confirm authoritatively
        # rejects per PRD §3.3 / §3.5.
        cand_id = str(cand_resp.json()["data"]["id"])
        confirm_resp = api.confirm_program_item(bag.festival_id, cand_id,
                                                LIAISON_HEADERS)
        validate_error(confirm_resp,
                       ApiErrorId.ERR_ARTIST_MULTI_FESTIVAL_CONFLICT.value,
                       expected_status=409)


# ---------------------------------------------------------------------------
# Rule 5 instance B — the referential-vs-fiscal priority pair on the
# exposure-allocation create endpoint.  PRD §2.6 names this case verbatim.
# ---------------------------------------------------------------------------


def test_priority_pair_b_referential_beats_fiscal_on_exposure_allocation_create(api):
    """PRD §2.6 second specific priority-conflict sentence: "Second,
    when an `ExposureAllocation` POST under a sponsor tier would fail
    both the referential check that the `kind` field must lie in the
    parent `SponsorTier`'s `contract_kinds_allowed` array (with the
    artist-mention specialisation `ERR_ARTIST_NOT_ELIGIBLE_FOR_TIER`
    at HTTP 422 firing when the kind is the literal string
    `artist_mention` and the parent's `contract_kinds_allowed` does
    not contain it, otherwise the generic
    `ERR_EXPOSURE_KIND_NOT_CONTRACTED` at HTTP 422) and the fiscal
    contract-units cap check (the sum of the requested units plus
    the tier's existing allocations of the same kind exceeds the
    `contracted_units` field of the parent tier, surfacing as
    `ERR_TIER_CONTRACT_UNITS_EXCEEDED` at HTTP 422), the referential
    category wins because it is numerically earlier in the priority
    order.  The artist-mention specialisation takes the place of the
    generic kind-not-contracted error when the offending kind happens
    to be `artist_mention`."

    Claim: a tier whose `contract_kinds_allowed` does NOT include
    `artist_mention`, and whose `contracted_units` is set so the new
    allocation's requested-units-plus-existing-allocations sum
    exceeds the cap.  Two rules fail simultaneously on a single POST.
    The §2.6 ordering says the referential one wins, so the client
    sees the specialised `ERR_ARTIST_NOT_ELIGIBLE_FOR_TIER` error id,
    not the fiscal `ERR_TIER_CONTRACT_UNITS_EXCEEDED`.

    Difficulty rule 5 instance B:
    # difficulty: priority_pair_validation_conflict/business_referential_beats_business_fiscal_on_exposure_allocation_create
    """
    bag = FIX.festival_in_scheduling(api, day_count=2)
    add_stage(api, bag, zone_capacity=10)
    seed_default_catalog(api, bag, stage_name=100, screen_time=100,
                        artist_mention=100, branded_zone=100)
    # The sponsor tier's contract_kinds_allowed deliberately excludes
    # `artist_mention` so the referential specialisation fires.  Its
    # `contracted_units` is set very low so the fiscal-cap also fires
    # on a request whose requested_units is over the cap.
    tier = get_success_data(api.create_sponsor_tier(
        bag.festival_id,
        sponsor_tier_payload(tier_code="GOLD",
                             priority_rank=1,
                             sponsor_external_id="gold-priority-pair-b",
                             sponsor_display_name="The Pair-B Sponsor",
                             contracted_units=2,
                             contract_kinds_allowed=["stage_name", "branded_zone"]),
        SPONSOR_HEADERS,
    ))
    tier_id = str(tier["id"])
    # Pre-fill the tier with one existing allocation of the disallowed
    # kind's sibling so the fiscal-cap calculation includes a non-
    # zero baseline.  We do not need an artist tied to this since the
    # PRD §3.6 fiscal-cap formula is on "the tier's existing
    # allocations of the same kind".  Use kind=stage_name to consume
    # one of the two contracted units.
    get_success_data(api.create_exposure_allocation(
        bag.festival_id, tier_id,
        F.exposure_allocation_payload(kind="stage_name", requested_units=2,
                                      program_item_id=None,
                                      pinned_rate_cents_per_unit=None),
        SPONSOR_HEADERS,
    ))
    # Wait — the fiscal cap is per-kind ("the sum of the requested
    # units plus the tier's existing allocations of the same kind
    # exceeds the `contracted_units`").  The PRD §3.6 narrative says
    # `contracted_units` is the across-the-catalog ceiling.  Read both
    # sentences together: the priority-19 fiscal check is per-kind in
    # the sense that the running per-kind sum-of-requested-units must
    # not exceed the tier's `contracted_units` cap for that kind.
    # The literal: "the sum of the new allocation's `requested_units`
    # plus the tier's existing allocations of the same kind being no
    # greater than the tier's `contracted_units` field".  Looking
    # again at the §3.6 sentence: "the per-tier contract-units cap,
    # which is the sum of the new allocation's `requested_units` plus
    # the tier's existing allocations of the same kind being no
    # greater than the tier's `contracted_units` field".  The
    # `contracted_units` is a single integer on the tier row per
    # PRD §1.1 / §3.6 — it's a contract-wide total.  So the per-kind
    # sum across allocations of all kinds combined must not exceed
    # `contracted_units`.  Hmm, the §3.6 sentence is "the tier's
    # existing allocations of the same kind", meaning the running sum
    # is over per-kind allocations only, not across all kinds.  That
    # is the implementation contract.
    #
    # In any case, our fixture is: tier.contracted_units = 2, the
    # tier already has one stage_name allocation requesting 2 units
    # (which on the per-kind reading is at the cap on stage_name).  A
    # new allocation of kind=artist_mention with requested_units=5
    # would exceed an artist_mention-kind running sum (0 existing +
    # 5 new) only if the per-kind running cap is the tier's
    # contracted_units=2.  Yes, 5 > 2, so the fiscal-cap is also
    # violated for the new artist_mention allocation.  And the
    # referential check is violated because artist_mention is not
    # in the contract_kinds_allowed list.  Both rules fire.
    bad_body = F.exposure_allocation_payload(
        kind="artist_mention",
        requested_units=5,
        program_item_id=None,
        pinned_rate_cents_per_unit=None,
    )
    bad_resp = api.create_exposure_allocation(
        bag.festival_id, tier_id, bad_body, SPONSOR_HEADERS,
    )
    # PRD §2.6 pins the referential-category specialisation as the
    # winning error_id when the kind is artist_mention and the
    # contract_kinds_allowed list does not contain it: the literal
    # ERR_ARTIST_NOT_ELIGIBLE_FOR_TIER.  The PRD §3.6 sentence on the
    # specialisation makes the discrimination explicit: "the generic
    # `ERR_EXPOSURE_KIND_NOT_CONTRACTED` ... fires, unless the
    # offending kind is the literal string `artist_mention`, in which
    # case the more specific `ERR_ARTIST_NOT_ELIGIBLE_FOR_TIER` ...
    # fires in its place".  This is the load-bearing PRD pin.
    validate_error(bad_resp,
                   ApiErrorId.ERR_ARTIST_NOT_ELIGIBLE_FOR_TIER.value,
                   expected_status=422)


def test_priority_pair_b_fiscal_fires_alone_when_referential_is_fine(api):
    """The sibling sanity-pair: when the referential check passes
    (the kind is in the contract_kinds_allowed list) but the fiscal
    cap is violated, the client sees the fiscal error
    `ERR_TIER_CONTRACT_UNITS_EXCEEDED` at HTTP 422.

    The PRD §3.6 prose names this code path verbatim: "the per-tier
    contract-units cap, which is the sum of the new allocation's
    `requested_units` plus the tier's existing allocations of the
    same kind being no greater than the tier's `contracted_units`
    field, otherwise `ERR_TIER_CONTRACT_UNITS_EXCEEDED` at HTTP 422".

    # difficulty: priority_pair_validation_conflict/business_referential_beats_business_fiscal_on_exposure_allocation_create
    """
    bag = FIX.festival_in_scheduling(api, day_count=2)
    add_stage(api, bag, zone_capacity=10)
    seed_default_catalog(api, bag, stage_name=100, screen_time=100,
                        artist_mention=100, branded_zone=100)
    tier = get_success_data(api.create_sponsor_tier(
        bag.festival_id,
        sponsor_tier_payload(tier_code="GOLD",
                             priority_rank=1,
                             sponsor_external_id="gold-fiscal-only",
                             sponsor_display_name="Fiscal-only sponsor",
                             contracted_units=3,
                             # contract_kinds_allowed INCLUDES the
                             # `stage_name` kind so the referential
                             # check passes.
                             contract_kinds_allowed=list(CATALOG_KINDS)),
        SPONSOR_HEADERS,
    ))
    tier_id = str(tier["id"])
    # Pre-existing allocation consuming all 3 contracted units of the
    # `stage_name` kind.  A new same-kind request of any positive
    # units would push the per-kind running sum past the cap.
    get_success_data(api.create_exposure_allocation(
        bag.festival_id, tier_id,
        F.exposure_allocation_payload(kind="stage_name", requested_units=3,
                                      program_item_id=None,
                                      pinned_rate_cents_per_unit=None),
        SPONSOR_HEADERS,
    ))
    # Same-kind fresh allocation requesting one more unit.  The
    # referential gate passes (stage_name is in the allowed list); the
    # fiscal gate fails (3 + 1 == 4 > 3 cap).
    bad_resp = api.create_exposure_allocation(
        bag.festival_id, tier_id,
        F.exposure_allocation_payload(kind="stage_name", requested_units=1,
                                      program_item_id=None,
                                      pinned_rate_cents_per_unit=None),
        SPONSOR_HEADERS,
    )
    validate_error(bad_resp,
                   ApiErrorId.ERR_TIER_CONTRACT_UNITS_EXCEEDED.value,
                   expected_status=422)


# ---------------------------------------------------------------------------
# Rule 7 instance A — the cross-entity-state gate on the program-item
# confirm endpoint against the festival's current_program_version_id
# (the version-pinning side of the cross-entity check).  This is the
# same gate the priority-A test exercises, but here we exercise it in
# isolation (without a concurrent business-temporal failure) so the
# rule-7 instance-A coverage is explicit.
# ---------------------------------------------------------------------------


def test_rule_7_instance_a_program_item_confirm_against_pinned_version(api):
    """PRD §3.3: "the item's `program_version_id` must equal the
    parent festival's `current_program_version_id` once any version
    has been published, otherwise the cross-entity state error
    `ERR_PROGRAM_VERSION_SUPERSEDED` at HTTP 409 fires".

    Claim: an item attached to a DRAFT version V2 cannot be confirmed
    while the festival's pinned current version is the already-
    published V1.  The PRD §1.6 entry on
    ERR_PROGRAM_VERSION_SUPERSEDED says "Item references a
    ProgramVersion that is not Festival.current_program_version_id
    even though a version has been published.  Cross-entity-state
    gate, rule 7 instance A."  The error id and the status code
    are pinned.

    Pair this with the §3.3 sentence "before any version has yet
    published the gate is relaxed to 'the `program_version_id`
    references a non-`WITHDRAWN`-non-`SUPERSEDED` version under the
    festival'" — that's the negative-of-the-precondition path which
    the prior fixtures' confirm-of-DRAFT-attached-items have
    repeatedly exercised, so the rule-7 instance-A two-test coverage
    is fulfilled by this strict-side test plus all of the prior
    base_world-derived tests where confirm fired against a DRAFT
    version pre-publish.

    Difficulty rule 7 instance A:
    # difficulty: cross_entity_state_dependency/programitem_confirm_depends_on_festival_current_program_version
    """
    bag = base_world(api, day_count=3, artist_tier="OPENER",
                     stage_zone_capacity=10)
    # V1 publishes.  The bag's initial DRAFT V1 needs an attached item
    # before the §3.3 ERR_EMPTY_PROGRAM_VERSION gate is cleared on the
    # submit-for-review step.  Add a trivial item, confirm it, publish
    # the version.
    seed = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=bag.artist_id,
                               stage_id=bag.stage_id,
                               start_time=bag.festival_start + 3600,
                               end_time=bag.festival_start + 7200,
                               genre="x", equipment_kit_codes=[]),
        LIAISON_HEADERS,
    ))
    confirm_item(api, bag, str(seed["id"]))
    publish_version(api, bag)
    # The bag's festival is now in PUBLISHED status (per PRD §3.1's
    # auto-transition on first publish).  current_program_version_id
    # is V1.
    # Create V2 as a fresh DRAFT.
    v2 = get_success_data(api.create_program_version(
        bag.festival_id,
        F.program_version_payload(version_label="v2-after-publish"),
        PRODUCER_HEADERS,
    ))
    # Create an item attached to V2.  The create endpoint's cross-
    # state gate is the relaxed-form "non-WITHDRAWN-non-SUPERSEDED",
    # which V2 (DRAFT) satisfies — so the create itself succeeds.
    fresh_artist = get_success_data(api.create_artist(
        F.artist_payload(stage_name="FreshArtist", tier="OPENER",
                         home_city="HC",
                         external_commitments=[],
                         minimum_travel_buffer_hours=None),
        LIAISON_HEADERS,
    ))
    cand_start = bag.festival_start + 2 * 86400 + 12 * 3600
    cand_end = cand_start + 3600
    cand = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=str(v2["id"]),
                               artist_id=str(fresh_artist["id"]),
                               stage_id=bag.stage_id,
                               start_time=cand_start, end_time=cand_end,
                               genre="x", equipment_kit_codes=[]),
        LIAISON_HEADERS,
    ))
    # The confirm endpoint runs the strict gate — V2 is not the
    # pinned current_program_version_id (V1 is), so confirm rejects
    # with ERR_PROGRAM_VERSION_SUPERSEDED.
    resp = api.confirm_program_item(bag.festival_id, str(cand["id"]),
                                    LIAISON_HEADERS)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_VERSION_SUPERSEDED.value,
                   expected_status=409)


def test_rule_7_instance_a_relaxed_gate_pre_first_publish_accepts_any_non_terminal_version(api):
    """PRD §3.3: "before any version has yet published the gate is
    relaxed to 'the `program_version_id` references a non-
    `WITHDRAWN`-non-`SUPERSEDED` version under the festival'".

    Claim: in a festival that has not yet had any program version
    publish (so the festival is still in SCHEDULING and
    current_program_version_id is null per PRD §2.4), the confirm
    endpoint accepts a program item whose `program_version_id` is
    any DRAFT version under the festival.

    # difficulty: cross_entity_state_dependency/programitem_confirm_depends_on_festival_current_program_version
    """
    bag = base_world(api, day_count=2)
    # No publishes yet — the festival is in SCHEDULING and
    # current_program_version_id is null.
    festival = get_success_data(api.get_festival(bag.festival_id, AUDIT_HEADERS))
    assert festival["status"] == "SCHEDULING"
    assert festival["current_program_version_id"] is None
    # An item under the bag's bag.version_id (the V1 DRAFT) confirms
    # cleanly because the relaxed gate applies.
    item = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=bag.artist_id,
                               stage_id=bag.stage_id,
                               start_time=bag.festival_start + 3600,
                               end_time=bag.festival_start + 7200,
                               genre="g", equipment_kit_codes=[]),
        LIAISON_HEADERS,
    ))
    confirmed = validate_success(api.confirm_program_item(
        bag.festival_id, str(item["id"]), LIAISON_HEADERS,
    ))
    assert confirmed["status"] == "CONFIRMED", \
        ("The relaxed cross-state gate of PRD §3.3 admits the confirm "
         "of an item attached to any non-terminal DRAFT version when no "
         "publish has yet pinned the festival's current_program_version_id.")


# ---------------------------------------------------------------------------
# Rule 7 instance B — the cross-entity-state gate on the sound-check
# schedule PATCH against the parent ProgramItem's status (which must be in
# the set {CONFIRMED, ANNOUNCED}) and the team's status (which must be
# AVAILABLE).  PRD §3.5 names both halves of the gate.
# ---------------------------------------------------------------------------


def test_rule_7_instance_b_soundcheck_schedule_requires_parent_in_confirmed_or_announced(api):
    """PRD §3.5: "The preconditions for the schedule transition are:
    the parent program item's status is in `CONFIRMED` or `ANNOUNCED`
    (otherwise `ERR_PARENT_ITEM_NOT_READY` at HTTP 409, the
    cross-entity-state error on the program-item side of the gate)".

    Claim: an attempt to schedule a sound-check on a slot whose
    parent program item is in PROPOSED (the initial state, never
    confirmed) is rejected with `ERR_PARENT_ITEM_NOT_READY` at HTTP
    409.

    Difficulty rule 7 instance B (parent-item half):
    # difficulty: cross_entity_state_dependency/soundcheckslot_schedule_depends_on_programitem_and_team_states
    """
    bag = base_world(api, day_count=2, stage_zone_capacity=10)
    add_program_item(api, bag, day_index=0, hour_offset_in_day=14,
                     duration_seconds=3600)
    # The item is in PROPOSED.  We did NOT call confirm.  Per PRD §3.3
    # / §3.5 the sound-check create endpoint side-effects the parent
    # item's sound_check_status axis to REQUESTED on the slot create,
    # but the schedule-PATCH gate runs the strict
    # "parent item is in CONFIRMED or ANNOUNCED" check.
    item_id = str(bag.program_item["id"])
    item_start = int(bag.program_item["start_time"])
    handoff = int(THRESHOLDS["TEAM_HANDOFF_SECONDS"])
    sc_end = item_start - handoff - 1
    sc_start = sc_end - 1800
    slot = add_sound_check_slot(api, bag, item_id,
                                scheduled_window_start=sc_start,
                                scheduled_window_end=sc_end)
    team = add_team(api, bag)
    # The schedule PATCH on this REQUESTED slot, while the parent
    # item is still in PROPOSED, must fire the parent-state gate.
    body = F.sound_check_schedule_payload(
        sound_engineer_team_id=str(team["id"]),
        scheduled_window_start=sc_start,
        scheduled_window_end=sc_end,
    )
    bad_resp = api.patch_sound_check(bag.festival_id, str(slot["id"]), body,
                                     STAGE_HEADERS)
    validate_error(bad_resp, ApiErrorId.ERR_PARENT_ITEM_NOT_READY.value,
                   expected_status=409)


def test_rule_7_instance_b_soundcheck_schedule_requires_team_available(api):
    """PRD §3.5: "the referenced sound-engineer team's status is
    `AVAILABLE` (otherwise `ERR_TEAM_NOT_AVAILABLE` at HTTP 409, the
    cross-entity-state error on the team side of the gate)".

    Claim: with the parent program item in CONFIRMED (so the
    parent-side gate is satisfied), a schedule-PATCH that references
    a team currently in BUSY is rejected with `ERR_TEAM_NOT_AVAILABLE`
    at HTTP 409.  We construct the BUSY-team precondition by first
    scheduling another sound-check under a different (CONFIRMED) item
    that pins the team's `current_booking_id`.

    Difficulty rule 7 instance B (team half):
    # difficulty: cross_entity_state_dependency/soundcheckslot_schedule_depends_on_programitem_and_team_states
    """
    # Reuse the fixture that produces a CONFIRMED-and-published item
    # with a SCHEDULED sound-check whose team is BUSY pointing at that
    # slot.  Then create a second item, a second slot under that
    # second item in status REQUESTED, and attempt to schedule the
    # new slot against the already-BUSY team.
    bag, busy_team, busy_slot = confirmed_item_with_scheduled_sound_check(
        api, artist_tier="OPENER", day_count=4,
    )
    busy_team_id = str(busy_team["id"])
    # Sanity: the team is BUSY with busy_slot's id as current_booking_id.
    busy_state = get_success_data(api.get_sound_engineer_team(
        bag.festival_id, busy_team_id, AUDIT_HEADERS,
    ))
    assert busy_state["status"] == "BUSY"
    assert busy_state.get("current_booking_id") == str(busy_slot["id"])
    # Create a second program item, confirm it, then a fresh REQUESTED
    # sound-check slot under it.  Item is on day-3 to ensure the
    # festival_window-containment rule (which the slot's window must
    # also satisfy via the §2.4 containment) is satisfied.  The bag's
    # festival_end is bag.festival_start + day_count * 86400 — with
    # day_count=4, day-3 12:00 fits comfortably.
    fresh_artist = get_success_data(api.create_artist(
        F.artist_payload(stage_name="Fresh", tier="OPENER",
                         home_city="HC",
                         external_commitments=[],
                         minimum_travel_buffer_hours=None),
        LIAISON_HEADERS,
    ))
    second_start = bag.festival_start + 3 * 86400 + 12 * 3600
    second_end = second_start + 3600
    item2 = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=str(bag.festival["current_program_version_id"]),
                               artist_id=str(fresh_artist["id"]),
                               stage_id=bag.stage_id,
                               start_time=second_start, end_time=second_end,
                               genre="g", equipment_kit_codes=[]),
        LIAISON_HEADERS,
    ))
    confirmed2 = validate_success(api.confirm_program_item(
        bag.festival_id, str(item2["id"]), LIAISON_HEADERS,
    ))
    assert confirmed2["status"] == "CONFIRMED"
    handoff = int(THRESHOLDS["TEAM_HANDOFF_SECONDS"])
    sc2_end = second_start - handoff - 1
    sc2_start = sc2_end - 1800
    slot2 = add_sound_check_slot(api, bag, str(item2["id"]),
                                 scheduled_window_start=sc2_start,
                                 scheduled_window_end=sc2_end)
    # Now the schedule PATCH on slot2 references the still-BUSY team.
    bad_resp = api.patch_sound_check(
        bag.festival_id, str(slot2["id"]),
        F.sound_check_schedule_payload(
            sound_engineer_team_id=busy_team_id,
            scheduled_window_start=sc2_start,
            scheduled_window_end=sc2_end,
        ),
        STAGE_HEADERS,
    )
    # The PRD §3.5 sentence pins ERR_TEAM_NOT_AVAILABLE on the team-
    # not-AVAILABLE half of the cross-entity gate.  The PRD §2.6
    # priority-6 / priority-8 ordering says the cross-entity gate
    # (priority 6) wins over the warmup-overlap business-safety check
    # (priority 8) when both could fire.  Either ERR_TEAM_NOT_AVAILABLE
    # (the cross-state error_id) or ERR_ENGINEER_TEAM_DOUBLE_BOOKED
    # (the overlap-error_id, if the implementation reaches the warmup
    # check before the team-status check) is a defensible reading of
    # the §2.5 lock-on-team narrative.  Per PRD §2.6 the cross-state
    # error has the lower priority number so it should win — but the
    # PRD's exact wording for the race-condition variant of this case
    # (§2.5) names ERR_ENGINEER_TEAM_DOUBLE_BOOKED as the team-already-
    # busy error.  We accept either of the two as a PRD-faithful
    # outcome.
    err_id = validate_error_is_one_of(
        bad_resp,
        [ApiErrorId.ERR_TEAM_NOT_AVAILABLE.value,
         ApiErrorId.ERR_ENGINEER_TEAM_DOUBLE_BOOKED.value],
    )
    assert bad_resp.status_code == 409, \
        f"Both errors in the cross-team-state family are 409 per PRD §1.6, got {bad_resp.status_code}"


# ---------------------------------------------------------------------------
# Rule 7 instance C — the cross-entity-state gate on the
# exposure-allocation deliver endpoint against the tied ProgramItem's
# status (which must be PERFORMED for item-tied allocations).
# ---------------------------------------------------------------------------


def test_rule_7_instance_c_exposure_deliver_requires_tied_item_performed(api):
    """PRD §3.6: "the cross-entity gate that the tied program item's
    status is `PERFORMED` for an allocation whose `program_item_id`
    is non-null (otherwise the cross-entity-state error
    `ERR_EXPOSURE_ALLOCATION_NOT_DELIVERABLE` at HTTP 409 fires), or
    that the parent festival's status is in the set `LIVE` or
    `CLOSED` for an allocation whose `program_item_id` is null (the
    festival-wide exposure case — the audience-area branded zone runs
    during the festival proper and may be delivered against from the
    moment the festival goes `LIVE`)".

    Claim: a deliver on an item-tied allocation whose tied program
    item is still in CONFIRMED (not yet PERFORMED — the clock hasn't
    advanced past the item's end_time so the auto-transition
    ON_STAGE → PERFORMED of PRD §3.3 hasn't fired) is rejected with
    `ERR_EXPOSURE_ALLOCATION_NOT_DELIVERABLE` at HTTP 409.

    The accepted side — the tied item IS in PERFORMED — is exercised
    by the rule-1 instance-B test in test_05_dual_variant_calculations.py,
    where the seven of eight surviving items deliver successfully
    after the festival's clock has crossed each item's end_time.

    Difficulty rule 7 instance C:
    # difficulty: cross_entity_state_dependency/exposure_deliver_depends_on_tied_program_item_performed
    """
    bag = base_world(api, day_count=2, artist_tier="OPENER",
                     stage_zone_capacity=10)
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    item_id = str(bag.program_item["id"])
    confirm_item(api, bag, item_id)
    publish_version(api, bag)
    # Standard sponsor-tier + catalog + per-item allocation, then
    # sweep so actual_units=1 lands on the allocation.  The item has
    # NOT yet been driven to PERFORMED (the clock has not advanced
    # past its end_time), so the deliver's cross-entity gate rejects.
    seed_default_catalog(api, bag, stage_name=100, screen_time=100,
                        artist_mention=100, branded_zone=100)
    tier = add_sponsor_tier(api, bag, tier_code="GOLD", priority_rank=1,
                            sponsor_external_id="gold-cross-c",
                            contracted_units=2,
                            contract_kinds_allowed=list(CATALOG_KINDS))
    alloc = add_exposure_allocation(api, bag, str(tier["id"]),
                                    kind="stage_name", requested_units=1,
                                    program_item_id=item_id,
                                    pinned_rate_cents_per_unit=None)
    run_waterfall(api, bag)
    # The tied item's status: get the latest snapshot.
    item_now = get_success_data(api.get_program_item(bag.festival_id, item_id, AUDIT_HEADERS))
    assert item_now["status"] != "PERFORMED", (
        "The tied item is not PERFORMED yet — the clock has not crossed "
        "its end_time per the PRD §3.3 clock-driven transition rules."
    )
    # The deliver call fires the cross-entity gate.
    bad_resp = api.deliver_exposure(
        bag.festival_id, str(alloc["id"]),
        F.exposure_deliver_payload(units=1, note="early-deliver"),
        SPONSOR_HEADERS,
    )
    validate_error(bad_resp,
                   ApiErrorId.ERR_EXPOSURE_ALLOCATION_NOT_DELIVERABLE.value,
                   expected_status=409)


def test_rule_7_instance_c_festival_wide_allocation_requires_festival_live_or_closed(api):
    """PRD §3.6: "the cross-entity gate that the tied program item's
    status is `PERFORMED` for an allocation whose `program_item_id`
    is non-null ... or that the parent festival's status is in the
    set `LIVE` or `CLOSED` for an allocation whose `program_item_id`
    is null".  The rejection on the festival-wide case before the
    festival goes LIVE is the same error_id family —
    `ERR_EXPOSURE_ALLOCATION_NOT_DELIVERABLE` at HTTP 409 — per the
    PRD §1.6 catalog entry, the catalog text saying the error fires
    when "the tied ProgramItem.status is not PERFORMED (or, for
    festival-wide allocations, the festival is not yet LIVE)".

    Claim: a festival-wide allocation (program_item_id is null) whose
    festival is still in PUBLISHED rejects the deliver call with
    `ERR_EXPOSURE_ALLOCATION_NOT_DELIVERABLE`.  Driving the clock
    past the festival's start_time so it goes LIVE then permits the
    deliver — the accepted-side counterexample, asserted in the
    helper fixture `delivered_allocation_world` that the rule-9
    instance-B compensating-invariant test consumes.

    # difficulty: cross_entity_state_dependency/exposure_deliver_depends_on_tied_program_item_performed
    """
    bag = base_world(api, day_count=2, artist_tier="OPENER",
                     stage_zone_capacity=1)
    # Need a published version so the festival's status is PUBLISHED.
    # Add a trivial confirmed item to V1, then publish.  The trivial
    # item is unrelated to the festival-wide allocation under test.
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    confirm_item(api, bag, str(bag.program_item["id"]))
    publish_version(api, bag)
    # Catalog with branded_zone == 5 so the waterfall awards
    # actual_units to the festival-wide allocation.
    seed_default_catalog(api, bag, branded_zone=5, stage_name=100,
                        screen_time=100, artist_mention=100)
    tier = add_sponsor_tier(api, bag, tier_code="GOLD", priority_rank=1,
                            sponsor_external_id="gold-festival-wide",
                            contracted_units=2,
                            contract_kinds_allowed=["branded_zone"])
    alloc = add_exposure_allocation(api, bag, str(tier["id"]),
                                    kind="branded_zone",
                                    requested_units=1,
                                    program_item_id=None,
                                    pinned_rate_cents_per_unit=None)
    run_waterfall(api, bag)
    # The festival is in PUBLISHED (not yet LIVE — the clock hasn't
    # crossed festival.start_time).  The festival-wide-allocation
    # deliver-gate of PRD §3.6 names "the parent festival's status is
    # in the set LIVE or CLOSED" as the precondition.  PUBLISHED is
    # not in that set, so the deliver rejects.
    festival_now = get_success_data(api.get_festival(bag.festival_id, AUDIT_HEADERS))
    assert festival_now["status"] == "PUBLISHED", \
        "Pre-clock-advance: the festival is in PUBLISHED per PRD §3.1's auto-publish-transition."
    bad_resp = api.deliver_exposure(
        bag.festival_id, str(alloc["id"]),
        F.exposure_deliver_payload(units=1, note="too-early"),
        SPONSOR_HEADERS,
    )
    validate_error(bad_resp,
                   ApiErrorId.ERR_EXPOSURE_ALLOCATION_NOT_DELIVERABLE.value,
                   expected_status=409)
    # And the accepted-side: advance the clock past festival.start_time
    # so the festival goes LIVE, then the deliver succeeds.
    advance_clock_to(api, festival_id=bag.festival_id,
                     to_unix_seconds=bag.festival_start + 60)
    festival_live = get_success_data(api.get_festival(bag.festival_id, AUDIT_HEADERS))
    assert festival_live["status"] in {"LIVE", "CLOSED"}, \
        "Post-clock-advance: the festival is LIVE per PRD §3.1's clock-driven transition."
    good_resp = api.deliver_exposure(
        bag.festival_id, str(alloc["id"]),
        F.exposure_deliver_payload(units=1, note="festival-wide-deliver"),
        SPONSOR_HEADERS,
    )
    validate_success(good_resp)


# ---------------------------------------------------------------------------
# Rule 9 instance B — the deliver-and-matching-void conservation invariant
# on SponsorTier.tier_remaining_quota.  The companion-test for the
# instance-A outstanding-tickets invariant is in
# test_07_schedule_change_branching.py.
# ---------------------------------------------------------------------------


def test_rule_9_instance_b_deliver_then_matching_void_conserves_tier_quota(api):
    """PRD §3.6: "The conservation invariant the system asserts across
    a deliver-then-void round trip on a single allocation is that the
    parent `SponsorTier`'s `tier_remaining_quota` returns to its
    pre-deliver value.  The mechanic is the `units` field of the
    `VOIDED` or `PROGRAM_VOIDED` log row matching the magnitude of
    the prior `DELIVERED` log row, so the running sum that defines
    `delivered_units` returns to zero (or, in the general case where
    multiple deliveries preceded the void, returns to its
    pre-final-deliver value), and the across-tier sum the quota
    depends on similarly snaps back."

    And: "The two conserved quantities at the system level — the
    festival's `outstanding_tickets_total` across an apply-and-revert
    of an `ITEM_CANCEL` change in §3.4, and the sponsor tier's
    `tier_remaining_quota` across a deliver-and-void round trip here
    — sit on different entity domains (the festival and the sponsor
    tier respectively) and conserve different quantities (the integer
    count of unrefunded tickets and the integer-units remainder of
    the sponsor's contractual catalog quota)."

    Claim: starting from a fresh GOLD sponsor tier whose
    contracted_units is C and tier_remaining_quota is C (because no
    delivered units yet), a deliver of N units on one festival-wide
    allocation drops tier_remaining_quota to C − N (the visible
    transient evidence the deliver fired), and a matching void of
    exactly N units (the default body shape per PRD §3.6 sends `units`
    equal to the allocation's current `delivered_units` for the
    inverse-balances-cleanly rule) returns tier_remaining_quota to
    its pre-deliver value of C.  The transient evidence — the
    delivered_units bulged from 0 to N between the deliver and the
    matching void — is the compensating-action signature, and the
    quota's snap-back-to-the-initial-value is the conserved-quantity
    invariant.

    Difficulty rule 9 instance B:
    # difficulty: compensating_invariant/sponsor_tier_remaining_quota_conserved_across_deliver_void_round_trip
    """
    # The delivered_allocation_world fixture composes the scenario: a
    # festival in LIVE (so the festival-wide branded_zone allocation's
    # deliver-gate is satisfied per PRD §3.6's "for an allocation
    # whose `program_item_id` is null ... festival's status is in the
    # set `LIVE` or `CLOSED`"), with one GOLD tier of
    # contracted_units == 2*units and one branded_zone allocation
    # requesting `units` units that lands at actual_units == units
    # after the waterfall sweep.  The fixture then delivers `units`
    # units on the allocation.  Pre- and post-deliver tier-quota
    # snapshots are returned so we can assert the transient (the
    # quota dropped by `units` between create and deliver) and the
    # post-void recovery.
    N = 3
    world = delivered_allocation_world(api, units=N)
    bag = world["bag"]
    tier_id = world["tier_id"]
    alloc_id = world["allocation_id"]
    pre_deliver_quota = int(world["pre_deliver_quota"])
    post_deliver_tier = world["post_deliver_tier"]
    post_deliver_quota = int(post_deliver_tier["tier_remaining_quota"])
    # The deliver fired: the running tier_delivered increased by N, so
    # the tier_remaining_quota dropped by N.  PRD §3.6:
    # "tier_remaining_quota = contracted_units − Σ delivered_units".
    assert post_deliver_quota == pre_deliver_quota - N, (
        f"After delivering {N} units, the tier_remaining_quota drops "
        f"by exactly {N} per the §3.6 conserved-quantity formula.  "
        f"Pre-deliver quota was {pre_deliver_quota}; observed post-"
        f"deliver quota is {post_deliver_quota}."
    )
    # The allocation's delivered_units is N at this point.
    alloc_post_deliver = get_success_data(
        api.get_exposure_allocation(bag.festival_id, alloc_id, AUDIT_HEADERS)
    )
    assert int(alloc_post_deliver["delivered_units"]) == N, (
        f"The allocation's delivered_units is {N} after a single deliver "
        f"of {N} units per the PRD §3.6 running-difference formula."
    )
    # Issue the matching void.  Per PRD §3.6 the body's `units` field
    # is optional; when omitted, it defaults to the allocation's
    # "current `delivered_units` (the default ensures the inverse
    # cleanly cancels the running total)".  Sending the explicit N is
    # the same outcome.  The body also requires a `reason` string per
    # the §3.6 sentence "the body requires a `reason` string (missing
    # reason returns ERR_MISSING_VOID_REASON at HTTP 400)".
    void_resp = api.void_exposure_delivery(
        bag.festival_id, alloc_id,
        F.exposure_void_payload(reason="compensating-void-test", units=N),
        SPONSOR_HEADERS,
    )
    voided = validate_success(void_resp)
    assert voided["status"] == "VOIDED", \
        "The void-delivery flips the allocation's status to VOIDED per PRD §3.6."
    # The tier_remaining_quota is back to the pre-deliver value.
    post_void_tier = get_sponsor_tier_snapshot(api, bag.festival_id, tier_id)
    post_void_quota = int(post_void_tier["tier_remaining_quota"])
    from test_helpers import assert_tier_remaining_quota_conserved
    assert_tier_remaining_quota_conserved(
        pre_deliver_quota, post_void_quota,
        contracted_units=int(post_void_tier["contracted_units"]),
    )
    # The allocation's delivered_units is back to zero per the §3.6
    # running-sum-of-DELIVERED-minus-VOIDED rule.
    alloc_post_void = get_success_data(
        api.get_exposure_allocation(bag.festival_id, alloc_id, AUDIT_HEADERS)
    )
    assert int(alloc_post_void["delivered_units"]) == 0, (
        "After a matching void, the allocation's delivered_units returns "
        "to zero per the PRD §3.6 running-sum formula."
    )
    # The FulfilmentLog stream contains both a DELIVERED row (units==N)
    # and a VOIDED row (units==N).  The void's event_type is the
    # operator-issued `VOIDED` rather than the cascade's
    # `PROGRAM_VOIDED` per the PRD §3.6 discriminator.  The detail
    # endpoint exposes the FulfilmentLog tail.
    detail = get_success_data(api.get_exposure_allocation(
        bag.festival_id, alloc_id, AUDIT_HEADERS,
    ))
    log = (detail.get("fulfilment_log") or detail.get("logs")
           or detail.get("fulfilment_logs") or [])
    delivered_rows = [r for r in log if r.get("event_type") == "DELIVERED"]
    voided_rows = [r for r in log if r.get("event_type") == "VOIDED"]
    program_voided_rows = [r for r in log if r.get("event_type") == "PROGRAM_VOIDED"]
    assert any(int(r["units"]) == N for r in delivered_rows), (
        f"A DELIVERED FulfilmentLog row with units=={N} is appended on "
        f"the deliver per PRD §3.6."
    )
    assert any(int(r["units"]) == N for r in voided_rows), (
        f"A VOIDED FulfilmentLog row with units=={N} is appended on the "
        f"operator-issued void per PRD §3.6, with the discriminator "
        f"`VOIDED` rather than the cascade's `PROGRAM_VOIDED`."
    )
    assert not program_voided_rows, (
        "The operator-issued void's event_type is the literal `VOIDED`, "
        "not the cascade's `PROGRAM_VOIDED`, per the PRD §3.6 "
        "discriminator-letting-the-audit-reader-tell-them-apart rule."
    )


def test_rule_9_instance_b_void_without_reason_rejected_with_missing_void_reason(api):
    """PRD §3.6: "the body requires a `reason` string (missing reason
    returns `ERR_MISSING_VOID_REASON` at HTTP 400)".

    Claim: a void-delivery body without a `reason` field is rejected
    at HTTP 400 with the missing-void-reason error id.  This is the
    body-shape guard on the operator-issued void path, and is the
    rule-9 instance-B coverage's second test (the conserved-quantity
    test above is the first).

    # difficulty: compensating_invariant/sponsor_tier_remaining_quota_conserved_across_deliver_void_round_trip
    """
    # The fixture sets up a DELIVERED-state allocation that we will
    # void.  We re-use the same fixture as the prior test.
    world = delivered_allocation_world(api, units=1)
    bag = world["bag"]
    alloc_id = world["allocation_id"]
    # The body lacks the `reason` field — per the PRD §3.6 sentence
    # the missing-reason rejection fires at HTTP 400 with
    # ERR_MISSING_VOID_REASON.
    bad_resp = api.void_exposure_delivery(bag.festival_id, alloc_id,
                                          {}, SPONSOR_HEADERS)
    validate_error(bad_resp, ApiErrorId.ERR_MISSING_VOID_REASON.value,
                   expected_status=400)


# ---------------------------------------------------------------------------
# Ancillary state-gate errors named in the §1.6 catalog for the ticketing
# and team families.  These round out the state-precondition coverage.
# ---------------------------------------------------------------------------


def test_issue_on_suspended_ticket_type_returns_not_active(api):
    """PRD §3.4: the ticket-type cycle is "`ACTIVE ↔ SUSPENDED` ... the
    `TicketingAdmin`" operates the cycle, and "a ticket-issuance call
    against a suspended type is rejected at HTTP 409 with
    `ERR_TICKET_TYPE_NOT_ACTIVE`".

    Claim: a ticket-issuance call on a SUSPENDED type is rejected
    with `ERR_TICKET_TYPE_NOT_ACTIVE` at HTTP 409.
    """
    bag = confirmed_published_world_with_ticket(
        api, day_count=2, unit_price_cents=5000, initial_issued=0,
        artist_tier="OPENER", headliner_blocking_rider=False,
    )
    tt_id = str(bag.ticket_type["id"])
    # Suspend the ticket type.  PRD §3.4 says the suspend endpoint
    # takes an optional `reason` — we supply the literal string used
    # by the §3.4 narrative.
    suspended = validate_success(api.suspend_ticket_type(
        bag.festival_id, tt_id,
        TICKETING_HEADERS, {"reason": "operator-pause"},
    ))
    assert suspended["status"] == "SUSPENDED"
    # Issue against the suspended type.
    bad_resp = api.issue_tickets(bag.festival_id, tt_id,
                                 F.ticket_issue_payload(count=1),
                                 TICKETING_HEADERS)
    validate_error(bad_resp, ApiErrorId.ERR_TICKET_TYPE_NOT_ACTIVE.value,
                   expected_status=409)
    # Resume and the issue succeeds.  PRD §3.4 names the resume
    # endpoint's precondition as "the parent festival is in one of the
    # running states `SCHEDULING`, `PUBLISHED`, or `LIVE`".  The
    # fixture has the festival in PUBLISHED so this passes.
    resumed = validate_success(api.resume_ticket_type(
        bag.festival_id, tt_id, TICKETING_HEADERS,
    ))
    assert resumed["status"] == "ACTIVE"
    good_resp = api.issue_tickets(bag.festival_id, tt_id,
                                  F.ticket_issue_payload(count=1),
                                  TICKETING_HEADERS)
    validate_success(good_resp)


def test_team_withdraw_rejected_when_team_has_active_slot(api):
    """PRD §3.2: "The terminal `WITHDRAWN` is reached through an
    explicit withdraw call by a `StageManager`, which is rejected
    with `ERR_TEAM_HAS_ACTIVE_SLOT` at HTTP 409 if the team is the
    `current_booking_id` of any `SCHEDULED` slot (the orchestrator
    must cancel the slot first)."

    Claim: an attempt to withdraw a team whose `current_booking_id`
    points at a SCHEDULED sound-check slot is rejected with the
    `ERR_TEAM_HAS_ACTIVE_SLOT` error id at HTTP 409, and the team's
    status is unchanged from BUSY.

    PRD §1.6's catalog entry for the same error id pins the
    HTTP-status-code and the condition string.
    """
    bag, team, _ = confirmed_item_with_scheduled_sound_check(
        api, artist_tier="OPENER", day_count=3,
    )
    team_id = str(team["id"])
    pre = get_success_data(api.get_sound_engineer_team(
        bag.festival_id, team_id, AUDIT_HEADERS,
    ))
    assert pre["status"] == "BUSY"
    bad_resp = api.withdraw_sound_engineer_team(bag.festival_id, team_id,
                                                STAGE_HEADERS)
    validate_error(bad_resp, ApiErrorId.ERR_TEAM_HAS_ACTIVE_SLOT.value,
                   expected_status=409)
    # Team is still BUSY — the rejected withdraw doesn't move state.
    post = get_success_data(api.get_sound_engineer_team(
        bag.festival_id, team_id, AUDIT_HEADERS,
    ))
    assert post["status"] == "BUSY"


# ---------------------------------------------------------------------------
# Clock-advance argument validation — PRD §2.8.
# ---------------------------------------------------------------------------


def test_clock_advance_backward_rejected(api):
    """PRD §2.8: "The semantics is monotonic non-decreasing: a negative
    `delta_seconds` or a `to_unix_seconds` earlier than the festival's
    current logical wall clock returns `ERR_CLOCK_ADVANCE_BACKWARD` at
    HTTP 400".

    Claim: a clock-advance body with a negative delta_seconds is
    rejected at HTTP 400 with the backward-clock error id.
    """
    bag = base_world(api, day_count=2)
    bad_resp = api.advance_clock(
        F.clock_advance_payload(festival_id=bag.festival_id,
                                delta_seconds=-60),
        ADMIN_HEADERS,
    )
    validate_error(bad_resp, ApiErrorId.ERR_CLOCK_ADVANCE_BACKWARD.value,
                   expected_status=400)


def test_clock_advance_neither_or_both_time_args_rejected(api):
    """PRD §2.8: "supplying neither or both of the two time arguments
    returns `ERR_CLOCK_INVALID_ARGS` at HTTP 400".

    Claim: a clock-advance body with neither `delta_seconds` nor
    `to_unix_seconds` is rejected with `ERR_CLOCK_INVALID_ARGS` at
    HTTP 400.  And the both-supplied case is rejected the same way.
    """
    bag = base_world(api, day_count=2)
    # Neither.
    neither_resp = api.advance_clock(
        {"festival_id": bag.festival_id}, ADMIN_HEADERS,
    )
    validate_error(neither_resp, ApiErrorId.ERR_CLOCK_INVALID_ARGS.value,
                   expected_status=400)
    # Both.
    both_resp = api.advance_clock(
        {"festival_id": bag.festival_id,
         "delta_seconds": 60,
         "to_unix_seconds": bag.festival_start + 7200},
        ADMIN_HEADERS,
    )
    validate_error(both_resp, ApiErrorId.ERR_CLOCK_INVALID_ARGS.value,
                   expected_status=400)


def test_sweep_with_unknown_festival_id_returns_sweep_festival_not_found(api):
    """PRD §2.8: "A nonexistent `festival_id` on the sweep body returns
    `ERR_SWEEP_FESTIVAL_NOT_FOUND` at HTTP 404."

    Claim: a sweep body referencing a nonexistent festival id is
    rejected with the dedicated `ERR_SWEEP_FESTIVAL_NOT_FOUND` error
    id at HTTP 404 (distinct from the generic `ERR_FESTIVAL_NOT_FOUND`
    that the path-resolution check on a `/festivals/{id}/...` path
    uses — the sweep endpoint's body-side festival id has its own
    error id per the PRD §1.6 catalog).
    """
    from test_helpers import NON_EXISTENT_UUID
    bad_body = F.sweep_payload(festival_id=NON_EXISTENT_UUID,
                               compute_payout=False)
    resp = api.run_sweep(bad_body, ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_SWEEP_FESTIVAL_NOT_FOUND.value,
                   expected_status=404)
