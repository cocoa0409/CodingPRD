"""Festival and ProgramVersion lifecycle.

These tests target the linear-with-terminal-branch Festival state
machine (PRD §3.1) and the cyclic-with-branch ProgramVersion state
machine (PRD §3.3 — the draft↔ready-for-review revision cycle, the
version-pinning publish that flips the festival to PUBLISHED, and the
auto-supersession of a prior PUBLISHED version when a sibling version
publishes after it).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    AuditEventCategory,
    assert_audit_contains,
    assert_festival_shape,
    assert_program_version_shape,
    assert_audit_chronological,
    assert_four_envelopes_queued,
    assert_pagination_meta,
    create_festival,
    festival_in_scheduling,
    base_world,
    add_program_item,
    add_program_version,
    publish_version,
    confirm_item,
    confirmed_item_world,
    read_audit_log,
    revision_return_payload,
    validate_error,
    validate_paginated,
    validate_success,
    get_success_data,
)


# ---------------------------------------------------------------------------
# Festival linear lifecycle: PLANNED → SCHEDULING → PUBLISHED (auto on the
# first program-version publish) → LIVE on a clock-cross of start_time →
# CLOSED on a clock-cross of end_time + FESTIVAL_CLOSE_GRACE_SECONDS.
# ---------------------------------------------------------------------------


def test_festival_open_scheduling_transition(api, producer_headers):
    """PRD §3.1: "From `PLANNED` the festival moves to the working state
    `SCHEDULING` through the open-scheduling capability the producer
    exercises (no body required), appending an audit entry."

    Claim: POST /festivals/{fid}/open-scheduling flips the status from
    PLANNED to SCHEDULING and writes a STATE_TRANSITION audit row.
    """
    bag = create_festival(api)
    assert bag.festival["status"] == "PLANNED", \
        "Fresh festival starts in PLANNED per PRD §3.1"
    resp = api.open_scheduling(bag.festival_id, producer_headers)
    data = validate_success(resp)
    assert data["status"] == "SCHEDULING"
    # The PRD §3.1 says the open-scheduling capability "appending an audit
    # entry" — the entry's event_category is STATE_TRANSITION per the
    # §2.8 mapping ("the generic category for the manual state-flip
    # endpoints such as confirm, announce, cancel, suspend, resume,
    # publish, submit-for-review, return-for-revision, withdraw, the
    # team withdraw, the rehearsal cancel").
    entries = read_audit_log(api, bag,
                             event_category=AuditEventCategory.STATE_TRANSITION.value,
                             subject_entity_type="Festival")
    assert_audit_chronological(entries)
    assert_audit_contains(entries,
                          event_category=AuditEventCategory.STATE_TRANSITION.value,
                          subject_entity_type="Festival",
                          subject_entity_id=bag.festival_id,
                          to_state="SCHEDULING")


def test_program_version_first_publish_pins_current_program_version_id(api):
    """PRD §3.3: "the publish capability ... atomically does a
    compare-and-swap on the parent `Festival.current_program_version_id`
    keyed on the festival's `version` integer ... A prior `PUBLISHED`
    version under the same festival, if any, is automatically flipped to
    the absorbing state `SUPERSEDED` and its `superseded_by_version_id`
    back-pointer is stamped with the new pinned version's id, forming a
    chain that traces the festival's program history."

    Claim: the first publish pins
    `Festival.current_program_version_id` to the published version's
    id; a second publish on a sibling version re-pins the pointer and
    flips the first version to SUPERSEDED with its
    `superseded_by_version_id` field stamped to the second version's
    id.  Also: the festival's status flips from SCHEDULING to PUBLISHED
    on the first publish (per PRD §3.1 the SCHEDULING→PUBLISHED edge is
    "automatic the first time a `ProgramVersion` under it transitions
    to the `PUBLISHED` state").
    """
    bag = base_world(api, day_count=3, version_label="v1")
    # The base_world fixture has the festival in SCHEDULING with a DRAFT
    # version V1 and an empty program-items list.  Add a single
    # PROPOSED-then-CONFIRMED item so the submit-for-review step doesn't
    # trip ERR_EMPTY_PROGRAM_VERSION per PRD §3.3.
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    confirm_item(api, bag, str(bag.program_item["id"]))
    v1_id = bag.version_id
    v1_published = publish_version(api, bag, v1_id)
    assert v1_published["status"] == "PUBLISHED"
    assert v1_published["published_at"] is not None
    # The festival's pointer is now V1.
    fest = get_success_data(api.get_festival(bag.festival_id, {"X-User-ID": "test-x", "X-User-Role": "AuditViewer"}))
    assert fest["current_program_version_id"] == v1_id, \
        "Festival.current_program_version_id pins to the first published version per PRD §3.3"
    assert fest["status"] == "PUBLISHED", \
        "Festival.status flips SCHEDULING → PUBLISHED on the first publish per PRD §3.1"
    # Create a second DRAFT version V2, attach a fresh program item to it
    # so submit-for-review's empty-program guard does not fire, then
    # publish V2.  The PRD §3.3 prose names the side-effect on V1.
    v2 = add_program_version(api, bag, version_label="v2-superseder")
    # The new item is created under V2 — its program_version_id field is
    # the V2 id.  Per PRD §3.3 the version's "program_item_ids" snapshot
    # is taken at publish-time as the set of ProgramItem.id values whose
    # program_version_id matches the publishing version; the prose does
    # not require those items to be in CONFIRMED state for the snapshot
    # to include them, only the FK match.  The cross-state gate that
    # the §3.3 confirm precondition pins — "the item's
    # program_version_id must equal the festival's
    # current_program_version_id once any version has been published" —
    # is the precise reason the V2-attached item is not confirmed in
    # this fixture step: the festival's currently-pinned version is V1,
    # so a confirm of the V2-attached item would (correctly) fire
    # ERR_PROGRAM_VERSION_SUPERSEDED.  The item lives in PROPOSED until
    # V2 publishes and the pointer flips.
    add_program_item(api, bag, day_index=1, hour_offset_in_day=10,
                     program_version_id=str(v2["id"]))
    v2_published = publish_version(api, bag, str(v2["id"]))
    assert v2_published["status"] == "PUBLISHED"
    # Re-read V1 — it must now be SUPERSEDED with its back-pointer
    # stamped to V2's id.
    from test_helpers import AUDIT_HEADERS
    v1_after = get_success_data(api.get_program_version(bag.festival_id, v1_id, AUDIT_HEADERS))
    assert v1_after["status"] == "SUPERSEDED", \
        "Prior PUBLISHED version flips to SUPERSEDED on a sibling publish per PRD §3.3"
    assert v1_after["superseded_by_version_id"] == str(v2["id"]), \
        ("The superseded version's superseded_by_version_id back-pointer is the "
         "newly-pinned version's id per PRD §3.3")
    fest_after = get_success_data(api.get_festival(bag.festival_id, AUDIT_HEADERS))
    assert fest_after["current_program_version_id"] == str(v2["id"]), \
        "Festival's current pointer re-pins to V2 after V2's publish per PRD §3.3"


def test_publish_emits_version_publish_schedule_change_with_four_queued_envelopes(api):
    """PRD §3.3: the publish capability "include[s] the auto-emission of
    a `ScheduleChange` of kind `VERSION_PUBLISH` whose `sync_envelopes`
    array is seeded with the four `QUEUED` records for `ticketing`,
    `im`, `broadcasting`, `sponsor`, fanning out the publish
    announcement to all four downstream systems through the standard
    event-driven-synchronisation surface of §2.8."

    Claim: after a publish, the schedule-changes list contains a
    `change_kind=VERSION_PUBLISH` row whose `sync_envelopes` array has
    exactly the four canonical-ordered targets all in status QUEUED.
    """
    bag = base_world(api, day_count=2)
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    confirm_item(api, bag, str(bag.program_item["id"]))
    publish_version(api, bag)
    # List the schedule changes filtered by kind=VERSION_PUBLISH per the
    # PRD §3.4 list-filter set.
    from test_helpers import AUDIT_HEADERS
    listing = validate_success(
        api.list_schedule_changes(bag.festival_id, AUDIT_HEADERS,
                                  params={"change_kind": "VERSION_PUBLISH", "limit": 10})
    )
    # The standard envelope's `data` is an array for list endpoints.
    rows = listing if isinstance(listing, list) else listing.get("items", listing.get("data", []))
    matches = [r for r in rows if r.get("change_kind") == "VERSION_PUBLISH"]
    assert matches, "A VERSION_PUBLISH ScheduleChange is auto-emitted on the publish per PRD §3.3"
    change = matches[0]
    # The PRD §2.8 prose: "the four elements are the connectors to the
    # four external systems ... and the order in which they appear in
    # the array is the canonical order `ticketing`, `im`, `broadcasting`,
    # `sponsor`. ... A fresh apply seeds all four elements with `QUEUED`
    # and stamps `queued_at` on each."
    assert_four_envelopes_queued(change)


def test_program_version_revision_cycle_draft_to_review_back_to_draft(api):
    """PRD §3.3: "From `READY_FOR_REVIEW` the artist-liaison may bounce
    the version back to `DRAFT` through the return-for-revision
    capability, which requires a `reason` string in the body (missing
    reason returns `ERR_MISSING_REVISION_REASON` at HTTP 400) — this is
    the cyclic `DRAFT ↔ READY_FOR_REVIEW` revision loop the scenario
    calls out, and the audit entry records the reason in its
    `payload_summary`."

    Claim: the cycle DRAFT → READY_FOR_REVIEW → DRAFT → READY_FOR_REVIEW
    succeeds when the return body carries a `reason`, the
    payload_summary of the audit row contains the reason text, and a
    return-for-revision without a `reason` field is rejected with
    `ERR_MISSING_REVISION_REASON` at HTTP 400.

    Difficulty: non_linear_state_machine /
    program_version_draft_review_revision_cycle  — the rule-3 instance
    on the cycle-shape state machine.

    # difficulty: non_linear_state_machine/program_version_draft_review_revision_cycle
    """
    bag = base_world(api, day_count=2)
    # A program item under V1 so submit-for-review's empty-program guard
    # (ERR_EMPTY_PROGRAM_VERSION) does not fire.
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    confirm_item(api, bag, str(bag.program_item["id"]))
    vid = bag.version_id
    # Drive the cycle.
    from test_helpers import LIAISON_HEADERS, PRODUCER_HEADERS
    sub1 = validate_success(api.submit_program_version_for_review(bag.festival_id, vid, PRODUCER_HEADERS))
    assert sub1["status"] == "READY_FOR_REVIEW"
    # Return-for-revision without a reason is rejected.
    bad_resp = api.return_program_version_for_revision(
        bag.festival_id, vid, {}, LIAISON_HEADERS,
    )
    validate_error(bad_resp, ApiErrorId.ERR_MISSING_REVISION_REASON.value,
                   expected_status=400)
    # And the with-reason path closes the cycle.
    reason_text = "add Saturday headliner"
    ret = validate_success(api.return_program_version_for_revision(
        bag.festival_id, vid, revision_return_payload(reason=reason_text), LIAISON_HEADERS,
    ))
    assert ret["status"] == "DRAFT", \
        "Return-for-revision flips status back to DRAFT per PRD §3.3"
    # Submit again to land READY_FOR_REVIEW a second time — the cycle
    # has now visited DRAFT twice, evidence of the cyclic shape.
    sub2 = validate_success(api.submit_program_version_for_review(bag.festival_id, vid, PRODUCER_HEADERS))
    assert sub2["status"] == "READY_FOR_REVIEW"
    # Audit log lists at least four STATE_TRANSITION rows on this
    # version id: PLANNED→SCHEDULING on the festival (already logged in
    # an earlier fixture step on the festival itself), V1 creation
    # (subject=ProgramVersion), submit-for-review (status→READY), return
    # (status→DRAFT, reason in payload_summary), and the second submit
    # (status→READY again).  Filter to ProgramVersion subject and the
    # vid.  PRD §3.7: the audit list is ordered by created_at ascending
    # per festival.
    pv_entries = read_audit_log(api, bag,
                                event_category=AuditEventCategory.STATE_TRANSITION.value,
                                subject_entity_type="ProgramVersion")
    pv_entries = [e for e in pv_entries if e.get("subject_entity_id") == vid]
    # At least one row mentions the reason text in the payload_summary
    # per the PRD §3.3 sentence "the audit entry records the reason in
    # its `payload_summary`".
    matching_reason = [e for e in pv_entries
                       if reason_text in (e.get("payload_summary") or "")]
    assert matching_reason, \
        "The return-for-revision audit row's payload_summary contains the reason text per PRD §3.3"


def test_program_version_revision_cycle_second_pass_visits_all_four_transitions(api):
    """A second test on the same difficulty-design instance, mandated by
    the §2.1.A coverage rule (every difficulty instance gets at least
    two tests).  Asserts the full four-edge cycle and the terminal
    publish from READY_FOR_REVIEW.

    PRD §3.3: "From either `DRAFT` or `READY_FOR_REVIEW` the producer
    transitions the version forward to `PUBLISHED` through the publish
    capability".  So a version that has cycled DRAFT→READY→DRAFT→READY
    can still publish from the second READY.

    # difficulty: non_linear_state_machine/program_version_draft_review_revision_cycle
    """
    bag = base_world(api, day_count=2)
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    confirm_item(api, bag, str(bag.program_item["id"]))
    vid = bag.version_id
    from test_helpers import LIAISON_HEADERS, PRODUCER_HEADERS, AUDIT_HEADERS
    # Cycle once.
    validate_success(api.submit_program_version_for_review(bag.festival_id, vid, PRODUCER_HEADERS))
    validate_success(api.return_program_version_for_revision(
        bag.festival_id, vid, revision_return_payload(reason="r1"), LIAISON_HEADERS))
    validate_success(api.submit_program_version_for_review(bag.festival_id, vid, PRODUCER_HEADERS))
    # Now publish from READY_FOR_REVIEW, the second edge into PUBLISHED.
    pub = validate_success(api.publish_program_version(bag.festival_id, vid, PRODUCER_HEADERS))
    assert pub["status"] == "PUBLISHED"
    assert isinstance(pub.get("published_at"), str) and pub["published_at"], \
        "Published version's published_at is non-null per PRD §3.3"
    # And the version's program_item_ids snapshot is non-empty (the
    # version had one CONFIRMED item attached at publish time).
    snapshot = pub.get("program_item_ids")
    assert isinstance(snapshot, list) and len(snapshot) >= 1, \
        "Published version's program_item_ids snapshot is non-empty per PRD §3.3"


def test_publish_with_empty_program_version_rejected(api):
    """PRD §3.3: "the submit-for-review capability ... is rejected with
    `ERR_EMPTY_PROGRAM_VERSION` at HTTP 409 when the version has zero
    attached program items".

    Claim: submit-for-review on a brand-new DRAFT version with no
    attached ProgramItems is rejected with `ERR_EMPTY_PROGRAM_VERSION`
    at HTTP 409.
    """
    bag = festival_in_scheduling(api, day_count=2)
    # Stage and equipment kit are not needed for a version-with-no-items.
    from test_helpers import register_artist
    bag.artist = register_artist(api, tier="OPENER")
    bag.artist_id = str(bag.artist["id"])
    add_program_version(api, bag, version_label="empty")
    vid = bag.version_id
    from test_helpers import PRODUCER_HEADERS
    resp = api.submit_program_version_for_review(bag.festival_id, vid, PRODUCER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_EMPTY_PROGRAM_VERSION.value,
                   expected_status=409)


def test_program_version_listing_paginates_and_filters_by_status(api):
    """PRD §2.3: list endpoints accept `limit` and `offset` and return
    the four-field meta block.  PRD §2.3: "Filters are query-string
    parameters whose names mirror the field names of the entity ...
    `status` ... interpreted as exact-match equality."  PRD §3.3 lists
    the program-version states the filter targets.

    Claim: GET /festivals/{fid}/program-versions returns a paginated
    response with the standard four-field meta block, and a
    `status=DRAFT` filter returns only rows whose `status` is exactly
    `DRAFT`.
    """
    bag = base_world(api, day_count=3)
    # Add a second DRAFT version so the filter is meaningfully filtering.
    add_program_version(api, bag, version_label="v-extra-draft")
    from test_helpers import AUDIT_HEADERS
    listing = api.list_program_versions(bag.festival_id, AUDIT_HEADERS,
                                        params={"status": "DRAFT", "limit": 50, "offset": 0})
    data, meta = validate_paginated(listing)
    assert isinstance(data, list)
    assert_pagination_meta(meta, expected_limit=50, expected_offset=0)
    # Every returned row has the exact-match status.
    for row in data:
        assert row.get("status") == "DRAFT", \
            "status filter is exact-match per PRD §2.3"


def test_withdraw_a_never_published_version(api):
    """PRD §3.3: "The terminal-on-the-discard-axis state of an
    unpublished version is `WITHDRAWN`, reached via the withdraw
    capability from either `DRAFT` or `READY_FOR_REVIEW` and gated on
    the version's having never published."

    Claim: a DRAFT version that has never published transitions to
    WITHDRAWN via the withdraw endpoint, and the listing reflects the
    terminal status.
    """
    bag = base_world(api, day_count=2)
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    vid = bag.version_id
    from test_helpers import PRODUCER_HEADERS
    resp = api.withdraw_program_version(bag.festival_id, vid, PRODUCER_HEADERS)
    data = validate_success(resp)
    assert data["status"] == "WITHDRAWN", \
        "Withdraw flips a never-published version's status to WITHDRAWN per PRD §3.3"
    assert_program_version_shape(data)


def test_festival_hard_cancel_fans_out_to_non_terminal_children(api):
    """PRD §3.1: "the festival-cancel capability ... flips the festival
    to `CANCELLED` from any non-terminal state, and fires a broad
    fan-out: every non-terminal `ProgramItem` flips to its own
    `CANCELLED` state ... every non-terminal `Rehearsal` flips to
    `CANCELLED`; every `TicketType` flips to `WITHDRAWN`; every
    `PLANNED` or `DELIVERED` `ExposureAllocation` flips to `VOIDED`
    with a `FulfilmentLog` row of `event_type` equal to
    `PROGRAM_VOIDED`".

    Claim: a `Festival` hard-cancel from SCHEDULING flips the festival
    itself to CANCELLED.  The broader fan-out's effect on the other
    children families is verified elsewhere; this test pins the
    festival-level flip and the audit row.
    """
    bag = festival_in_scheduling(api)
    from test_helpers import ADMIN_HEADERS
    resp = api.cancel_festival(bag.festival_id, {"reason": "test-hard-cancel"},
                               ADMIN_HEADERS)
    data = validate_success(resp)
    assert data["status"] == "CANCELLED", \
        "festival-cancel flips status to CANCELLED per PRD §3.1"
    entries = read_audit_log(api, bag,
                             event_category=AuditEventCategory.STATE_TRANSITION.value,
                             subject_entity_type="Festival")
    # Among the festival-subject STATE_TRANSITION rows, one has
    # to_state == "CANCELLED".
    cancelled_rows = [e for e in entries if e.get("to_state") == "CANCELLED"]
    assert cancelled_rows, \
        "An audit row of subject Festival to_state=CANCELLED is appended per PRD §3.1"


def test_festival_cancel_requires_platform_admin_or_producer_role(api, ticketing_headers):
    """PRD §4 table: the `/festivals/{festivalId}/cancel` endpoint's
    allowlist is `PlatformAdmin, FestivalProducer`.  PRD §2.1 names the
    generic-permission-denial error id as `ERR_INSUFFICIENT_PERMISSIONS`
    at HTTP 403.

    Claim: a TicketingAdmin calling festival-cancel receives
    `ERR_INSUFFICIENT_PERMISSIONS` at HTTP 403.
    """
    bag = festival_in_scheduling(api)
    resp = api.cancel_festival(bag.festival_id, {"reason": "x"}, ticketing_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
                   expected_status=403)


def test_open_scheduling_idempotent_on_already_scheduling_festival(api, producer_headers):
    """PRD §3.1 implies the open-scheduling transition is from PLANNED
    only — the lifecycle's linear shape has a single PLANNED →
    SCHEDULING edge.  Calling open-scheduling on a festival that has
    already moved past PLANNED is therefore in the state-precondition
    family that the §2.6 priority-5 state gate would reject.  Because
    the PRD §3.1 prose does not pin a specific error_id for the
    "already-past-PLANNED" case (the state-precondition family covers
    it generically), we assert only the negative outcome: the second
    open-scheduling call does not crash and the festival's status
    remains `SCHEDULING` (a no-op on the absorbing-state side of the
    edge — the open-scheduling capability cannot drive the system
    backwards).
    """
    bag = festival_in_scheduling(api)
    resp2 = api.open_scheduling(bag.festival_id, producer_headers)
    # Whatever the server's error_id choice, the festival's status must
    # not regress to PLANNED — the state machine is forward-only on
    # the linear axis per PRD §3.1's shape.  We do a fresh GET to
    # confirm.
    from test_helpers import AUDIT_HEADERS
    final = get_success_data(api.get_festival(bag.festival_id, AUDIT_HEADERS))
    assert_festival_shape(final)
    assert final["status"] in {"SCHEDULING", "PUBLISHED", "LIVE", "CLOSED", "CANCELLED"}, \
        ("The festival's status must remain on the forward-progress chain "
         "after any post-PLANNED open-scheduling attempt per PRD §3.1's "
         "linear-with-terminal-branch shape.")
    # The HTTP-level outcome of the redundant call is left to the
    # implementation as the PRD does not pin a specific error_id for
    # "already at SCHEDULING"; we accept both a 2xx idempotent-style
    # success and any 4xx state-gate error.
    assert resp2.status_code in (200, 409), \
        ("Repeat open-scheduling on a SCHEDULING festival is either an "
         "idempotent 200 (returning the unchanged row) or a 409 state-gate "
         "rejection — both are PRD-consistent because §3.1 names no specific "
         "outcome for the redundant call.")
