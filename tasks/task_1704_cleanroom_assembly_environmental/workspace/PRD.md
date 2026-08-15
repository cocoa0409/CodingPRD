# Cleanroom Assembly & Environmental Monitoring API — Product Requirements Document

## 1. Introduction

Contract assembly inside ISO-classified cleanrooms lives or dies on evidence: who entered the room and whether their gowning qualification was current, what the particle and viable counts showed at each sampling point, how excursions beyond the alert and action limits were investigated and dispositioned, whether the room's certification was in force while product was being built, and whether cleaning had been validated before a batch was ever released. When any one of those controls fails, the quality unit must be able to reconstruct exactly what happened, stop work in flight, and hold suspect product — without relying on hallway conversations or paper logbooks.

This document specifies the Cleanroom Assembly & Environmental Monitoring API, a REST service mounted under `/cleanroom` that manages that control fabric end to end. Its scope covers personnel registration, per-room gowning qualification and entry logging; environmental sampling against two-tier alert and action limits with automatic excursion creation; excursion investigation with product-impact disposition; room certification, recertification, suspension, and voiding; material transfer through pass-through airlocks with dwell and wipe-down protocol; assembly batch records with step-wise travelers; cleaning validation programs built on consecutive verified passes; and customer audit hosting with CAPA-tracked findings.

Four operator roles interact with the system under strict segregation-of-duties rules, and every room carries a derived environmental posture — computed from its open excursions and certification standing — that gates whether personnel may enter, material may be introduced, traveler steps may start, and batches may be released. All time-dependent behavior is evaluated against a controllable logical clock, so that expiry, dwell, and audit-window rules are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring that user's operational capacity. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose declared role is not permitted to invoke the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles:

- `QualityAssurance` — the QA unit: registers rooms and sampling points, records and voids certifications, opens and dispositions excursion investigations, verifies and rejects cleaning cycles, releases, rejects, and resumes batches, voids traveler steps, hosts customer audits, grants and revokes gowning qualifications, suspends and reinstates personnel, decommissions rooms, and drives the logical clock.
- `EnvironmentTech` — the environmental monitoring technician: records environmental samples and records cleaning cycles.
- `ProductionOperator` — the assembly operator: logs room entry and exit, opens batches, adds traveler steps, and starts and completes those steps.
- `MaterialHandler` — the warehouse/material handler: stages material transfers into the airlock and introduces or rejects them.

For each of these four roles — `QualityAssurance`, `EnvironmentTech`, `ProductionOperator`, and `MaterialHandler` alike — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it where a workflow anchors authorship (for example, as `recorded_by_user_id` on an excursion, as `investigated_by_user_id` on an investigation, as `performed_by_user_id` on a traveler step or a cleaning cycle, or as `verified_by_user_id` on a verified cycle), but it never compares `X-User-ID` against any entity's `id`. Every segregation-of-duties comparison in this system is a plain string-equality check between two `X-User-ID` values.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0.

Unless stated otherwise, every list endpoint returns resources sorted by their `created_at` timestamp in ascending order.

Paginated list responses carry the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this API — cleanrooms, personnel, gowning qualifications, sampling points, environmental samples, excursions, investigations, certifications, material transfers, batches, travelers, entry logs, cleaning programs, cleaning cycles, audits, and findings — carries a standard set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation, including mutations caused by automatic cascades and derived-field recomputation. A newly registered cleanroom begins at `version` 1.

These properties are the backbone of the audit trail: every state transition described in §3 is a mutation that refreshes `updated_at` and advances `version` on the affected resource.

### 2.5. The Logical Clock and Lazy Expiry Evaluation

All time-dependent evaluation in the system — certification expiry, gowning qualification expiry, airlock dwell gates, audit windows, and recurrence windows — is driven by a server-side logical clock, never by wall-clock time. Before any call has set it, the logical clock reads exactly 2026-08-01T00:00:00Z, and it must never fall back to wall-clock time. A `QualityAssurance`-only test-driving capability advances the clock: the caller supplies a `to_iso8601` instant, and the response reports the new `current_utc`. Setting the clock does not by itself rewrite any record; the consequences of the new time are realized lazily, on subsequent access.

Two expiry rules are evaluated lazily. First, a room whose `certification_status` is `CERTIFIED` transitions to `CERTIFICATION_EXPIRED` the first time any read or write touches the room after the logical clock has reached or passed the instant that is `certified_at` plus `recert_interval_days` (the day count applied as whole days of twenty-four hours). The boundary is inclusive: at the exact instant the interval elapses, the certification is already expired. Second, a gowning qualification in `QUALIFIED` status flips to `EXPIRED` on read once the logical clock reaches or passes its `qualification_expires_at`, again with the boundary instant itself already treated as expired. Advancing the clock therefore takes effect on the next room or qualification access, at which point the room's environmental posture (§2.7) is also recomputed, since a non-`CERTIFIED` certification status forces a posture floor of `ALERT`.

### 2.6. Two-Tier Environmental Limits: Per-Sample Judgment vs. Mean-Based Certification

Every cleanroom is configured with two tiers of limits for each of two metrics. For the particle metric — airborne particle counts per cubic meter at 0.5 micrometers and larger — the room carries `particle_alert_limit` and `particle_action_limit`. For the viable metric — colony-forming units per cubic meter — it carries `viable_alert_limit` and `viable_action_limit`. For each metric the action limit must be strictly greater than the corresponding alert limit; a room registration whose limits violate that ordering is rejected with `ERR_INVALID_REQUEST`.

Two different judgments use these limits, and the distinction is deliberate. **Per-sample excursion detection** judges every individual environmental sample against the limits of the room its sampling point belongs to: a single result at or above the alert limit is enough to raise an excursion, regardless of what any other sample showed. The comparison boundary includes equality on both tiers — a result exactly equal to the alert limit exceeds the alert tier, and a result exactly equal to the action limit exceeds the action tier. Sample results are integer counts and carry no rounding.

**Mean-based certification grading** answers a different question — whether the room as a whole meets its classification — and so it judges the mean of a certification run's per-location particle means against the room's `particle_alert_limit`, requiring the mean to fall strictly below the limit. The same set of numbers can therefore trip a per-sample alert excursion while the mean-based certification grade still passes; conversely, a mean exactly equal to the alert limit fails certification even though a single sample exactly at the alert limit produces only an alert excursion.

### 2.7. Environmental Posture: A Derived Room Aggregate

Each cleanroom carries a computed `environment_posture`, one of `IN_CONTROL`, `ALERT`, `ACTION`, or `SHUTDOWN`. Clients never set the posture directly; the server recomputes it after every excursion status change, after every certification result, and after every investigation approval, using a fixed top-to-bottom evaluation order in which the first matching rule wins:

1. If the room carries an approved excursion investigation whose `product_impact` is `CONFIRMED` and whose closure has not yet been superseded by a fresh passing certification recorded after that approval, the posture is `SHUTDOWN`.
2. Otherwise, if any excursion of the room stands in `OPEN` or `UNDER_INVESTIGATION` with severity `ACTION`, the posture is `ACTION`.
3. Otherwise, if any excursion of the room stands in `OPEN` or `UNDER_INVESTIGATION` with severity `ALERT`, the posture is `ALERT`.
4. Otherwise, if the room's `certification_status` is anything other than `CERTIFIED`, the posture rests at a floor of `ALERT`.
5. Otherwise, the posture is `IN_CONTROL`.

Recovery from `SHUTDOWN` requires both halves together: zero excursions of the room in `OPEN` or `UNDER_INVESTIGATION`, and a fresh passing certification recorded after the confirmed-impact approval. Closing the last open alert excursion while certification stands `CERTIFIED` returns the room from `ALERT` to `IN_CONTROL`; an alert-severity excursion entering the open set raises `IN_CONTROL` to `ALERT`, and an action-severity excursion entering the open set raises the room to `ACTION`.

The posture is the room's gatekeeper. Personnel entry, material introduction, traveler step start, and batch release each require the room to be `IN_CONTROL`; against a room in any raised posture those operations are rejected with `ERR_ROOM_NOT_IN_CONTROL`.

### 2.8. Segregation of Duties

Four author-versus-verifier pairs are segregated across the system. In every case the check is string equality between two `X-User-ID` values, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403):

- The technician who recorded the sample that triggered an excursion (anchored as the excursion's `recorded_by_user_id`) may not open that excursion's investigation.
- The QA who opened an investigation (anchored as its `investigated_by_user_id`) may not approve that same investigation.
- The technician who performed a cleaning cycle (anchored as its `performed_by_user_id`) may not verify that same cycle.
- The QA who releases a batch must differ from the `performed_by_user_id` of every traveler step belonging to that batch.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and no other endpoint accepts a version field.

Recording a room certification requires the request to carry `expected_room_version`, holding the `version` of the target cleanroom as the client last observed it. If the room's current `version` has advanced since that observation — for instance because another writer recorded a certification that supersedes the prior one, or because an excursion cascade recomputed the room's posture — the request is rejected with `ERR_STALE_ROOM_VERSION` (HTTP 412), preventing the client from certifying a room state it never observed.

Releasing an assembly batch likewise requires the request to carry `expected_batch_version` matching the batch's current `version`. A mismatch — possible, for example, after a room shutdown cascade parked the batch on hold and back, or after a traveler completion advanced the batch — is rejected with `ERR_STALE_BATCH_VERSION` (HTTP 412).

### 2.10. Validation Order and Error Precedence

When several checks could reject the same request, the server evaluates them in a fixed priority order so that the surfaced error is deterministic:

1. Presence and well-formedness of the `X-User-ID` and `X-User-Role` headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization for the endpoint (`ERR_FORBIDDEN`).
3. Existence of every identifier in the path and every foreign-key identifier in the body, validated left to right (`ERR_NOT_FOUND`).
4. Where §2.9 applies, the expected-version match (`ERR_STALE_ROOM_VERSION` or `ERR_STALE_BATCH_VERSION`).
5. Whether the target entity stands in a state from which the requested transition exists (`ERR_INVALID_STATE`).
6. The room-posture gate, applied to personnel entry, material introduction, traveler start, and batch release (`ERR_ROOM_NOT_IN_CONTROL`).
7. The room-certification gate, applied to material introduction and batch release (`ERR_ROOM_NOT_CERTIFIED`).
8. Segregation of duties on the four pairs of §2.8 (`ERR_SEGREGATION_OF_DUTIES`).
9. Structural request validity — required fields present, enum values valid, each action limit strictly greater than its alert limit, an audit's `window_end` strictly after its `window_start`, `dwell_minutes` not negative, `result_value` not negative, and `root_cause` at least 20 characters long (`ERR_INVALID_REQUEST`).
10. Cross-reference coherence — a sampling point belonging to the room addressed, a gowning qualification matching the presented personnel and room, a traveler belonging to the batch addressed, and a declared recurrence pointing to a `CLOSED` excursion at the same sampling point (`ERR_REFERENTIAL_INTEGRITY`, HTTP 422).
11. Temporal gates — the gowning qualification not expired, the transfer's dwell elapsed, the audit window started (`ERR_GOWNING_NOT_QUALIFIED`, `ERR_DWELL_TIME_NOT_MET`, `ERR_AUDIT_WINDOW_NOT_STARTED`).
12. Personnel active at entry — a suspended person may not enter any room (`ERR_PERSONNEL_SUSPENDED`).
13. Aggregate guards — no second draft investigation per excursion (`ERR_INVESTIGATION_ALREADY_OPEN`), no second active or validated cleaning program per room (`ERR_PROGRAM_ALREADY_ACTIVE`), no second open entry log for the same personnel-and-room pair (`ERR_ENTRY_ALREADY_OPEN`), traveler step order (`ERR_TRAVELER_STEP_ORDER`), batch release with unsettled travelers (`ERR_BATCH_TRAVELERS_UNSETTLED`), audit close with unverified findings (`ERR_AUDIT_FINDINGS_OPEN`), and certification with open excursions (`ERR_OPEN_EXCURSIONS_BLOCK_CERTIFICATION`) or without a validated cleaning program (`ERR_CLEANING_NOT_VALIDATED`).

### 2.11. Numeric Precision and Rounding

Excursion severity scores are rounded to exactly two decimal places using the round-half-up method and are represented in responses as numbers. Sample results and consecutive-pass counters are integers with no rounding applied. Certification grade means are computed at full precision — the sum of the location means divided by their count — and the pass comparison is performed on the unrounded mean. Timestamp comparisons (expiry, dwell, audit windows, recurrence windows) are evaluated at second precision on ISO 8601 values.

## 3. Business Logic & Workflows

### 3.1. Rooms, Sampling Plans, and the Certification Cycle

A `QualityAssurance` operator registers a cleanroom by supplying a unique `room_code` (such as CR-101), the target `iso_class` — one of `ISO_5`, `ISO_6`, `ISO_7`, or `ISO_8` — the four monitoring limits `particle_alert_limit`, `particle_action_limit`, `viable_alert_limit`, and `viable_action_limit`, and the `recert_interval_days` that governs how long a passed certification remains in force. A new room is born with `certification_status` `UNCERTIFIED`, `environment_posture` `IN_CONTROL`, lifecycle `status` `ACTIVE`, a null `certified_at`, and `version` 1. The room listing can be filtered by `iso_class` or `certification_status`, and every read or write of a room first applies the lazy expiry evaluation described in §2.5.

Within a room, QA defines the sampling plan as a set of sampling points. Each point is identified by a `point_code` unique within the room (such as SP-01), a `metric` of `PARTICLE` or `VIABLE`, and a `zone_iso_class` that feeds severity scoring and must equal the room's own `iso_class` at the time the point is defined. A point spends its life `ACTIVE`; QA may retire it, moving it from `ACTIVE` to `RETIRED` — permitted only while the point is `ACTIVE`, otherwise `ERR_INVALID_STATE` — and a retired point rejects any new sample, also with `ERR_INVALID_STATE`.

Certification is recorded by QA against a room and carries the `executed_at` instant at which the certification test was physically executed, the array `location_mean_values` of per-location mean particle concentrations used for the grade check, the optimistic-concurrency guard `expected_room_version` (§2.9), and optionally `supersedes_certification_id` naming the certification this new one replaces. The `location_mean_values` array must be non-empty. The computed `grade_passed` flag is true exactly when the mean of `location_mean_values` — the sum divided by the count, computed at full precision — falls strictly below the room's `particle_alert_limit`; a mean equal to the limit fails. The recorded certification `result` is `PASS` only when three conditions hold together: the grade check passed (otherwise `ERR_CERTIFICATION_GRADE_FAILED`), the room has zero excursions in `OPEN` or `UNDER_INVESTIGATION` (otherwise `ERR_OPEN_EXCURSIONS_BLOCK_CERTIFICATION`), and at least one cleaning validation program for the room stands at `VALIDATED` (otherwise `ERR_CLEANING_NOT_VALIDATED`); any shortfall records the certification as `FAIL`. Recording against a room that is not `ACTIVE` is refused with `ERR_ROOM_NOT_ACTIVE`, and a stale `expected_room_version` is refused with `ERR_STALE_ROOM_VERSION`. On a `PASS`, the room's `certification_status` becomes `CERTIFIED`, `certified_at` is set to the certification's `executed_at`, the referenced superseded certification (if any) is marked superseded, the room's `version` increments by one, and the environmental posture is recomputed. This single recording flow serves initial certification from `UNCERTIFIED`, recertification from `CERTIFICATION_EXPIRED`, and reinstatement from `CERTIFICATION_SUSPENDED`.

A certification remains in force until the logical clock reaches or passes `certified_at` plus `recert_interval_days`; lazy evaluation then moves the room from `CERTIFIED` to `CERTIFICATION_EXPIRED`, and the posture floor of §2.7 raises the room to `ALERT` until it is recertified. QA may instead void a certification outright — but only the room's latest passing certification, pinned precisely as the first row when the room's `PASS` certifications are ordered by `executed_at` descending with ties broken by `created_at` descending; targeting any other certification is rejected with `ERR_NOT_LATEST_CERTIFICATION`. Voiding moves the room from `CERTIFIED` to `CERTIFICATION_SUSPENDED`, recomputes the posture, and thereby fails every room-dependent gate until a fresh pass is recorded. Certifications can be listed per room or across rooms, the cross-room listing filterable by `cleanroom_id` or `supersedes_certification_id`.

### 3.2. Personnel, Gowning Qualification, and Room Entry

QA registers personnel with a unique `employee_code` (the badge code), the `full_name`, and a `role_title`; each record is born `ACTIVE`. Gowning qualification is per room: granting one pairs a `personnel_id` with a `cleanroom_id`, stamps `qualified_at` at grant time, and computes `qualification_expires_at` as exactly 365 days after `qualified_at`. The qualification stands `QUALIFIED` until the logical clock reaches the expiry instant — at the exact expiry instant, entry is already denied — at which point lazy evaluation marks it `EXPIRED`. QA may revoke a qualification from either `QUALIFIED` or `EXPIRED` status, moving it to terminal `REVOKED`; revocation from any other source state is rejected with `ERR_INVALID_STATE`. Qualifications are listable filtered by `personnel_id`, `cleanroom_id`, or `status`, and both directions of sub-resource listing exist — the qualifications held for a room, and the qualifications held by one personnel record.

Entry to a room is logged by a `ProductionOperator` presenting a `personnel_id` and a `cleanroom_id`. Entry is refused with `ERR_PERSONNEL_SUSPENDED` when the person is `SUSPENDED`; with `ERR_GOWNING_NOT_QUALIFIED` when no `QUALIFIED`, unexpired qualification exists for that person-and-room pair; with `ERR_ROOM_NOT_IN_CONTROL` when the room's posture is raised; and with `ERR_ENTRY_ALREADY_OPEN` when an entry log whose `exited_at` is still null already exists for the same pair — one person cannot be inside the same room twice. A successful entry stamps `entered_at` at log time and leaves `exited_at` null while the person is inside; the matching exit, also performed by a `ProductionOperator`, stamps `exited_at`. Entry log listings filter by `personnel_id` and `cleanroom_id`.

Suspension is the disciplinary lever: QA may suspend a personnel record only from `ACTIVE` and reinstate it only from `SUSPENDED`, with `ERR_INVALID_STATE` guarding both directions. Suspending a person has an immediate side effect beyond blocking future entries — every open entry log for that person is force-closed, its `exited_at` set to the suspension instant. While `SUSPENDED`, the person may not enter any room.

### 3.3. Environmental Sampling and Excursion Detection

An `EnvironmentTech` records an environmental sample by supplying the `sampling_point_id`, the measured `result_value` — a non-negative integer count, particles per cubic meter or CFU per cubic meter depending on the point's `metric` — and the `sampled_at` instant at which the sample was physically taken. Optionally the technician declares `recurrence_of_excursion_id`, a self-link asserting that this result recurs an earlier excursion at the same location; the link must point to a `CLOSED` excursion at the same sampling point, otherwise the record is rejected with `ERR_REFERENTIAL_INTEGRITY`. The sample listing filters by `sampling_point_id` and `classification`.

On creation, every sample is classified per the two-tier rule of §2.6 against its room's limits: a `result_value` at or above the room's action limit for the point's metric yields `ACTION_EXCEEDED`; otherwise a value at or above the alert limit yields `ALERT_EXCEEDED`; otherwise the sample stands `IN_CONTROL`. Any classification other than `IN_CONTROL` automatically creates an excursion within the same request. The excursion inherits the room — its `cleanroom_id` denormalized from the sampling point — carries the `sampling_point_id`, and links back to the triggering sample via `sample_id`, while the sample's `triggered_excursion_id` points forward at the excursion it created. The excursion is born `OPEN`, its `severity` mirroring the sample's classification (`ALERT_EXCEEDED` becomes `ALERT`; `ACTION_EXCEEDED` becomes `ACTION`), its `recorded_by_user_id` anchored to the recording technician's `X-User-ID` as the segregation anchor, and its `severity_score` computed as described below. The room posture is recomputed in the same breath — a first alert-severity excursion moves `IN_CONTROL` to `ALERT`, and an action-severity excursion raises the room to `ACTION`.

The severity score combines three factors. The base weight is 10 when the sampling point's `metric` is `VIABLE` and 4 when it is `PARTICLE`. The zone multiplier is read from the point's `zone_iso_class`: 3 for `ISO_5`, 2.5 for `ISO_6`, 2 for `ISO_7`, and 1 for `ISO_8`. The recurrence factor counts how many excursions at the same sampling point already stand `CLOSED` with their triggering sample's `sampled_at` falling inside the trailing 30-day window before this sample's `sampled_at`; the window includes its lower bound exactly thirty days back and excludes this sample's own instant, the count is taken only from excursions closed before this excursion's creation, and the new excursion never counts itself. The score is the base weight multiplied by the zone multiplier, multiplied by one plus one quarter of the recurrence count, rounded half-up to two decimal places.

Excursions are listed with filters on `cleanroom_id`, `status`, `severity`, `sampling_point_id`, `sample_id`, or `recurrence_of_excursion_id`. The samples behind a single excursion are retrievable as a list containing zero or one element, since exactly one sample triggers an excursion.

### 3.4. Excursion Investigation and Product-Impact Disposition

An excursion in `OPEN` is taken up by QA through an investigation. Opening one requires the excursion to stand `OPEN` (`ERR_EXCURSION_NOT_OPEN`) and requires that no other investigation for the same excursion already sits in `DRAFT` — exactly one open investigation per excursion (`ERR_INVESTIGATION_ALREADY_OPEN`). The investigator supplies a `root_cause` narrative of at least 20 characters, a `product_impact` assessment of `NONE`, `POTENTIAL`, or `CONFIRMED`, and a product `disposition` of `RELEASE`, `REJECT`, or `REWORK`; the investigation is bound to its excursion by `excursion_id`. The system anchors `investigated_by_user_id` to the acting QA's `X-User-ID`, which must differ from the excursion's `recorded_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`), and the excursion moves from `OPEN` to `UNDER_INVESTIGATION` while the investigation itself stands `DRAFT`.

Disposing of an investigation is a second, separate QA act, and the two outcomes diverge sharply. Approval requires the investigation to still stand `DRAFT` (`ERR_INVESTIGATION_NOT_DRAFT`) and requires the approver's `X-User-ID` to differ from the investigation's `investigated_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`). Approval moves the investigation to terminal `APPROVED` and the parent excursion from `UNDER_INVESTIGATION` to `CLOSED`, then recomputes the room posture. When the approved `product_impact` is `CONFIRMED`, the room enters `SHUTDOWN` and the cascade fires atomically within the same request: every assembly batch of the room standing `OPEN` or `IN_PROGRESS` moves to `ON_HOLD` with `hold_reason` set to `EXCURSION_PRODUCT_IMPACT`, and every material transfer of the room still `STAGED` moves to `REJECTED`. When the approved impact is `NONE` or `POTENTIAL`, the posture recompute may instead let the room recover — closing the room's last open excursion with certification in force returns the room toward `IN_CONTROL`. Rejection likewise requires a `DRAFT` investigation (`ERR_INVESTIGATION_NOT_DRAFT`); it moves the investigation to terminal `REJECTED` and loops the excursion back from `UNDER_INVESTIGATION` to `OPEN` — a cycle that may repeat without bound until an investigation survives approval — and the recomputed posture stays raised while the excursion stands open again.

### 3.5. Material Transfer Through the Airlock

A `MaterialHandler` stages a material transfer by naming the destination `cleanroom_id`, the supplier's `material_lot`, an `item_description`, the `dwell_minutes` the item must rest in the pass-through airlock before it may be introduced (zero or greater), and `wiped_down`, recording whether the wipe-down protocol step was performed. Staging stamps `staged_at` at creation and leaves the transfer `STAGED`. The transfer listing filters by `cleanroom_id` and `status`.

Introduction from the airlock into the room is gated five ways: the transfer must still stand `STAGED` (`ERR_TRANSFER_NOT_STAGED`); `wiped_down` must be true (`ERR_WIPE_DOWN_MISSING`); the logical clock must have reached or passed `staged_at` plus `dwell_minutes` — the boundary is inclusive, so introduction is allowed at the exact instant the dwell completes, and earlier attempts fail with `ERR_DWELL_TIME_NOT_MET`; the room's posture must be `IN_CONTROL` (`ERR_ROOM_NOT_IN_CONTROL`); and the room's certification must stand `CERTIFIED` (`ERR_ROOM_NOT_CERTIFIED`). A successful introduction moves the transfer from `STAGED` to terminal `INTRODUCED`.

A handler may also reject a staged transfer outright; the manual rejection path checks the same `STAGED` precondition (`ERR_TRANSFER_NOT_STAGED`). Independently of any handler action, the shutdown cascade of §3.4 rejects every still-`STAGED` transfer of the affected room. Either way the transfer lands in terminal `REJECTED`.

### 3.6. Batch Records and Assembly Travelers

A `ProductionOperator` opens an assembly batch by naming the `cleanroom_id` where assembly occurs, a unique `batch_number`, and the `product_code` being assembled; the batch starts `OPEN`. Work is decomposed into assembly traveler steps added to the batch — each bound to it by `batch_id` — with a `step_sequence` giving the step's position and a `step_description` carrying the work instruction text; every step is born `PENDING`. Batch listings filter by `cleanroom_id` and `status`.

Starting a step is the operator's act and is gated four ways: the batch must stand `OPEN` or `IN_PROGRESS` (`ERR_BATCH_NOT_STARTABLE`); the room's posture must be `IN_CONTROL` (`ERR_ROOM_NOT_IN_CONTROL`); every sibling step with a lower `step_sequence` must already be `COMPLETE` or `VOID`, so steps execute in ascending order (`ERR_TRAVELER_STEP_ORDER`); and the starting operator must hold a `QUALIFIED`, unexpired gowning qualification for the room (`ERR_GOWNING_NOT_QUALIFIED`). A successful start anchors `performed_by_user_id` to the operator's `X-User-ID`, and the batch's first step start automatically moves the batch from `OPEN` to `IN_PROGRESS`.

Completing a step belongs to the same operator who started it: the step must stand `IN_PROGRESS` (`ERR_TRAVELER_NOT_IN_PROGRESS`), and the completer's `X-User-ID` must equal the step's `performed_by_user_id` (`ERR_TRAVELER_PERFORMER_MISMATCH`). When the last unsettled step of a batch resolves — every traveler of the batch `COMPLETE` or `VOID`, with at least one `COMPLETE` — the batch automatically becomes `COMPLETE`. QA may void a step while it is `PENDING`; voiding from any other state fails with `ERR_TRAVELER_NOT_VOIDABLE`.

Release is QA's final act on a batch and the most heavily gated operation in the system. The batch must stand `COMPLETE` (`ERR_BATCH_NOT_COMPLETE`), with `ERR_BATCH_TRAVELERS_UNSETTLED` guarding the attempt whenever any traveler still stands `PENDING` or `IN_PROGRESS`; the room's posture must be `IN_CONTROL` (`ERR_ROOM_NOT_IN_CONTROL`); the room's certification must stand `CERTIFIED` (`ERR_ROOM_NOT_CERTIFIED`); the releaser's `X-User-ID` must differ from the `performed_by_user_id` of every traveler step of the batch (`ERR_SEGREGATION_OF_DUTIES`); and the request must carry `expected_batch_version` equal to the batch's current `version`, with a mismatch rejected as `ERR_STALE_BATCH_VERSION` (§2.9). A released batch moves to terminal `RELEASED`, and its `version` increments by one. QA may instead reject a `COMPLETE` batch, moving it to terminal `REJECTED`; the same `ERR_BATCH_NOT_COMPLETE` guard applies.

A batch parked at `ON_HOLD` by the shutdown cascade can be resumed by QA once the room is again `IN_CONTROL`: resume requires the batch to stand `ON_HOLD` (`ERR_BATCH_NOT_ON_HOLD`) and the room posture gate (`ERR_ROOM_NOT_IN_CONTROL`), and it returns the batch to `IN_PROGRESS` with `hold_reason` cleared.

### 3.7. Cleaning Validation Programs and Cycles

QA creates a cleaning validation program for a room by supplying the `cleanroom_id`, a `method_code` identifying the cleaning method, and optionally `required_consecutive_passes`, which defaults to 3 when omitted. The program starts `DRAFT` with `consecutive_pass_count` 0. Activation moves the program from `DRAFT` to `ACTIVE` and is refused with `ERR_PROGRAM_ALREADY_ACTIVE` when another program for the same room already stands `ACTIVE` or `VALIDATED` — one room carries at most one live program. Program listings filter by `cleanroom_id` and `status`.

An `EnvironmentTech` records each cleaning cycle under its program — the cycle carries the `program_id` — supplying the analytical `result`, `PASS` or `FAIL`, and the record anchors `performed_by_user_id` to the recording technician's `X-User-ID`. A cycle recorded with `result` `FAIL` never waits for review: it is stored directly as `REJECTED`, the program's `consecutive_pass_count` resets to 0, and a program that stood `VALIDATED` drops to `RE_VALIDATION_REQUIRED`.

A passing cycle sits in `RECORDED` until QA renders a verdict. Verification requires the cycle to stand `RECORDED` (`ERR_CYCLE_NOT_RECORDED`), a `result` of `PASS` (`ERR_CYCLE_RESULT_FAIL`), and a verifier whose `X-User-ID` differs from the cycle's `performed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); verification stamps `verified_by_user_id`, moves the cycle to terminal `VERIFIED`, and increments the program's `consecutive_pass_count` by one. When the count reaches `required_consecutive_passes` — the boundary is inclusive, so reaching the required number exactly is sufficient — the program moves automatically to `VALIDATED`, whether it stood `ACTIVE` or `RE_VALIDATION_REQUIRED`. QA may instead reject a recorded cycle (again `ERR_CYCLE_NOT_RECORDED` when the cycle is not `RECORDED`), moving it to terminal `REJECTED`, resetting `consecutive_pass_count` to 0, and forcing a `VALIDATED` program back to `RE_VALIDATION_REQUIRED`, from which it must re-accumulate the full run of consecutive verified passes to reach `VALIDATED` again.

A `VALIDATED` cleaning program is a hard precondition of room certification (§3.1), which ties the cleaning loop directly into the certification cycle: a room cannot certify, recertify, or recover from suspension while its cleaning validation is incomplete or lapsed.

### 3.8. Customer Audits and CAPA Findings

QA schedules a customer audit by supplying the `customer_code` of the hosting customer, the audited `cleanroom_id`, and a scope window from `window_start` to `window_end`; the window must be non-empty, with `window_end` strictly after `window_start`, otherwise `ERR_INVALID_REQUEST`. The audit begins `SCHEDULED`, and audit listings filter by `cleanroom_id` and `status`.

Opening the audit requires it to stand `SCHEDULED` (`ERR_AUDIT_NOT_SCHEDULED`) and requires the logical clock to have reached or passed `window_start` (`ERR_AUDIT_WINDOW_NOT_STARTED`). Opening moves the audit to `IN_PROGRESS` and computes its scope snapshot over the audited room's environmental samples whose `sampled_at` falls inside the window — `window_start` inclusive and `window_end` exclusive, so a sample taken exactly at the window start is in scope while one taken exactly at the window end is out.

While the audit is `IN_PROGRESS`, QA records findings, each bound to its audit by `audit_id`, carrying a `severity` of `OBSERVATION`, `MINOR`, `MAJOR`, or `CRITICAL` and a free-text `description`; every finding starts `OPEN`. A finding's CAPA lifecycle advances from `OPEN` to `CAPA_SUBMITTED` when QA submits the corrective action — only from `OPEN`, otherwise `ERR_FINDING_NOT_OPEN` — and from `CAPA_SUBMITTED` to terminal `CAPA_VERIFIED` when QA verifies the submitted action — only from `CAPA_SUBMITTED`, otherwise `ERR_FINDING_NOT_CAPA_SUBMITTED`. Verifying the audit's last unverified finding does not itself close the audit; the audit remains `IN_PROGRESS` until explicitly closed.

Closing the audit requires it to stand `IN_PROGRESS` (`ERR_AUDIT_NOT_IN_PROGRESS`) and requires every finding of the audit to stand at `CAPA_VERIFIED`; if any finding is still short of verified, the close is rejected with `ERR_AUDIT_FINDINGS_OPEN`. A successful close moves the audit to terminal `CLOSED`.

### 3.9. Decommissioning a Room

End of life for a cleanroom is a QA act guarded three ways: the room must stand `ACTIVE`, it must hold no batches in `OPEN`, `IN_PROGRESS`, or `ON_HOLD`, and it must hold no `STAGED` transfers; any of the three failures is rejected with `ERR_INVALID_STATE`. Decommissioning moves the room's lifecycle `status` to terminal `DECOMMISSIONED`. Thereafter the room rejects all further operational writes — entries, samples, transfers, travelers, and certifications alike — with `ERR_ROOM_NOT_ACTIVE`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — state transitions, verifications, introductions, releases, and the like — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cleanroom/_clock/set_current_utc` | Set the server logical clock | QualityAssurance |
| POST | `/cleanroom/rooms` | Register a cleanroom | QualityAssurance |
| GET | `/cleanroom/rooms` | List cleanrooms | QualityAssurance, ProductionOperator, MaterialHandler, EnvironmentTech |
| GET | `/cleanroom/rooms/{roomId}` | Get one cleanroom (with lazy expiry evaluation) | QualityAssurance, ProductionOperator, MaterialHandler, EnvironmentTech |
| POST | `/cleanroom/rooms/{id}/sampling-points` | Define a sampling point in a room | QualityAssurance |
| GET | `/cleanroom/rooms/{id}/sampling-points` | List sampling points of a room | QualityAssurance, ProductionOperator, MaterialHandler, EnvironmentTech |
| GET | `/cleanroom/sampling-points/{pointId}` | Get one sampling point | QualityAssurance, ProductionOperator, MaterialHandler, EnvironmentTech |
| POST | `/cleanroom/sampling-points/{pointId}/retire` | Retire a sampling point (rejects new samples) | QualityAssurance |
| POST | `/cleanroom/rooms/{roomId}/decommission` | Decommission a cleanroom (requires no open batches or staged transfers) | QualityAssurance |
| POST | `/cleanroom/samples` | Record an environmental sample; auto-creates an excursion when the classification is not IN_CONTROL | EnvironmentTech |
| GET | `/cleanroom/samples` | List samples, filterable | QualityAssurance, EnvironmentTech |
| GET | `/cleanroom/samples/{sampleId}` | Get one sample | QualityAssurance, EnvironmentTech |
| GET | `/cleanroom/excursions` | List excursions, filterable | QualityAssurance, EnvironmentTech |
| GET | `/cleanroom/excursions/{id}/samples` | List samples that triggered a given excursion (0 or 1 element) | QualityAssurance, EnvironmentTech |
| GET | `/cleanroom/excursions/{excursionId}` | Get one excursion | QualityAssurance, EnvironmentTech |
| POST | `/cleanroom/excursions/{id}/investigations` | Open an investigation (moves the excursion OPEN → UNDER_INVESTIGATION) | QualityAssurance |
| GET | `/cleanroom/excursions/{id}/investigations` | List investigations of an excursion | QualityAssurance, EnvironmentTech |
| GET | `/cleanroom/investigations/{investigationId}` | Get one investigation | QualityAssurance, EnvironmentTech |
| POST | `/cleanroom/investigations/{investigationId}/approve` | Approve an investigation: closes the excursion; CONFIRMED impact cascades room → SHUTDOWN, batches → ON_HOLD, staged transfers → REJECTED | QualityAssurance |
| POST | `/cleanroom/investigations/{investigationId}/reject` | Reject an investigation: the excursion loops back UNDER_INVESTIGATION → OPEN | QualityAssurance |
| POST | `/cleanroom/rooms/{id}/certifications` | Record a room certification (OCC-guarded; PASS requires grade_passed, zero open excursions, and a VALIDATED cleaning program) | QualityAssurance |
| GET | `/cleanroom/rooms/{id}/certifications` | List certifications of a room | QualityAssurance, EnvironmentTech |
| GET | `/cleanroom/certifications/{certId}` | Get one certification | QualityAssurance, EnvironmentTech |
| GET | `/cleanroom/certifications` | List certifications across rooms (filtered) | QualityAssurance, EnvironmentTech |
| POST | `/cleanroom/rooms/{id}/certifications/{certId}/void` | Void the latest PASS certification (suspends room certification) | QualityAssurance |
| POST | `/cleanroom/personnel` | Register personnel | QualityAssurance |
| GET | `/cleanroom/personnel` | List personnel | QualityAssurance, EnvironmentTech |
| GET | `/cleanroom/personnel/{personnelId}` | Get one personnel record | QualityAssurance, EnvironmentTech |
| POST | `/cleanroom/personnel/{personnelId}/suspend` | Suspend a personnel record (blocks entries; force-closes open entry logs) | QualityAssurance |
| POST | `/cleanroom/personnel/{personnelId}/reinstate` | Reinstate a suspended personnel record | QualityAssurance |
| POST | `/cleanroom/gowning-qualifications` | Grant a per-room gowning qualification (valid 365 days) | QualityAssurance |
| GET | `/cleanroom/gowning-qualifications` | List gowning qualifications (filtered by personnel_id or cleanroom_id) | QualityAssurance, EnvironmentTech |
| GET | `/cleanroom/gowning-qualifications/{qualId}` | Get one gowning qualification | QualityAssurance, EnvironmentTech |
| POST | `/cleanroom/gowning-qualifications/{qualId}/revoke` | Revoke a gowning qualification | QualityAssurance |
| GET | `/cleanroom/rooms/{id}/gowning-qualifications` | List gowning qualifications for a room (sub-resource) | QualityAssurance, EnvironmentTech |
| GET | `/cleanroom/personnel/{id}/gowning-qualifications` | List gowning qualifications for a personnel record (sub-resource) | QualityAssurance, EnvironmentTech |
| POST | `/cleanroom/entry-logs` | Log a personnel entry (requires ACTIVE personnel, QUALIFIED non-expired gowning qualification, and room posture IN_CONTROL) | ProductionOperator |
| GET | `/cleanroom/entry-logs` | List entry logs (filtered) | QualityAssurance, EnvironmentTech |
| GET | `/cleanroom/entry-logs/{entryLogId}` | Get one entry log | QualityAssurance, EnvironmentTech |
| POST | `/cleanroom/entry-logs/{entryLogId}/exit` | Log the matching exit | ProductionOperator |
| POST | `/cleanroom/material-transfers` | Stage a material transfer into the airlock | MaterialHandler |
| GET | `/cleanroom/material-transfers` | List transfers (filtered) | QualityAssurance, MaterialHandler |
| GET | `/cleanroom/material-transfers/{transferId}` | Get one transfer | QualityAssurance, MaterialHandler |
| POST | `/cleanroom/material-transfers/{transferId}/introduce` | Introduce a staged transfer into the room | MaterialHandler |
| POST | `/cleanroom/material-transfers/{transferId}/reject` | Reject a staged transfer | MaterialHandler |
| POST | `/cleanroom/batches` | Open an assembly batch | ProductionOperator |
| GET | `/cleanroom/batches` | List batches (filtered) | QualityAssurance, ProductionOperator |
| GET | `/cleanroom/batches/{batchId}` | Get one batch | QualityAssurance, ProductionOperator |
| POST | `/cleanroom/batches/{id}/travelers` | Add a traveler step to a batch | ProductionOperator |
| GET | `/cleanroom/batches/{id}/travelers` | List travelers of a batch | QualityAssurance, ProductionOperator |
| GET | `/cleanroom/travelers/{travelerId}` | Get one traveler | QualityAssurance, ProductionOperator |
| POST | `/cleanroom/travelers/{travelerId}/start` | Start a traveler step (gated on posture, qualification, step order) | ProductionOperator |
| POST | `/cleanroom/travelers/{travelerId}/complete` | Complete a traveler step (performer only); last settle completes the batch | ProductionOperator |
| POST | `/cleanroom/travelers/{travelerId}/void` | Void a pending traveler step | QualityAssurance |
| POST | `/cleanroom/batches/{batchId}/release` | Release a completed batch (OCC-guarded; posture, certification, and segregation-of-duties gated) | QualityAssurance |
| POST | `/cleanroom/batches/{batchId}/reject` | Reject a completed batch | QualityAssurance |
| POST | `/cleanroom/batches/{batchId}/resume` | Resume an ON_HOLD batch after the room returns IN_CONTROL | QualityAssurance |
| POST | `/cleanroom/cleaning-programs` | Create a cleaning validation program for a room | QualityAssurance |
| GET | `/cleanroom/cleaning-programs` | List cleaning programs (filtered) | QualityAssurance, EnvironmentTech |
| GET | `/cleanroom/cleaning-programs/{programId}` | Get one cleaning program | QualityAssurance, EnvironmentTech |
| POST | `/cleanroom/cleaning-programs/{programId}/activate` | Activate a program (only one ACTIVE/VALIDATED per room) | QualityAssurance |
| POST | `/cleanroom/cleaning-programs/{id}/cycles` | Record a cleaning cycle; result=FAIL records the cycle directly as REJECTED and resets the program counter | EnvironmentTech |
| GET | `/cleanroom/cleaning-programs/{id}/cycles` | List cycles of a program | QualityAssurance, EnvironmentTech |
| GET | `/cleanroom/cleaning-cycles/{cycleId}` | Get one cycle | QualityAssurance, EnvironmentTech |
| POST | `/cleanroom/cleaning-cycles/{cycleId}/verify` | QA-verify a passing cycle (segregation: verifier ≠ performer); increments consecutive_pass_count and may validate the program | QualityAssurance |
| POST | `/cleanroom/cleaning-cycles/{cycleId}/reject` | QA-reject a cycle; resets the program counter and forces re-validation | QualityAssurance |
| POST | `/cleanroom/audits` | Schedule a customer audit over a scope window | QualityAssurance |
| GET | `/cleanroom/audits` | List audits (filtered) | QualityAssurance, EnvironmentTech |
| GET | `/cleanroom/audits/{auditId}` | Get one audit | QualityAssurance, EnvironmentTech |
| POST | `/cleanroom/audits/{auditId}/open` | Open an audit (requires now ≥ window_start) | QualityAssurance |
| POST | `/cleanroom/audits/{id}/findings` | Record an audit finding | QualityAssurance |
| GET | `/cleanroom/audits/{id}/findings` | List findings of an audit | QualityAssurance, EnvironmentTech |
| POST | `/cleanroom/audit-findings/{findingId}/submit-capa` | Submit a CAPA for an open finding | QualityAssurance |
| POST | `/cleanroom/audit-findings/{findingId}/verify-capa` | Verify a submitted CAPA | QualityAssurance |
| POST | `/cleanroom/audits/{auditId}/close` | Close an audit (requires every finding CAPA_VERIFIED) | QualityAssurance |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_ROOM_VERSION` | 412 |
| `ERR_STALE_BATCH_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_REFERENTIAL_INTEGRITY` | 422 |
| `ERR_ROOM_NOT_IN_CONTROL` | 409 |
| `ERR_ROOM_NOT_CERTIFIED` | 409 |
| `ERR_ROOM_NOT_ACTIVE` | 409 |
| `ERR_CERTIFICATION_GRADE_FAILED` | 409 |
| `ERR_OPEN_EXCURSIONS_BLOCK_CERTIFICATION` | 409 |
| `ERR_CLEANING_NOT_VALIDATED` | 409 |
| `ERR_NOT_LATEST_CERTIFICATION` | 409 |
| `ERR_EXCURSION_NOT_OPEN` | 409 |
| `ERR_INVESTIGATION_ALREADY_OPEN` | 409 |
| `ERR_INVESTIGATION_NOT_DRAFT` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_GOWNING_NOT_QUALIFIED` | 409 |
| `ERR_PERSONNEL_SUSPENDED` | 409 |
| `ERR_ENTRY_ALREADY_OPEN` | 409 |
| `ERR_TRANSFER_NOT_STAGED` | 409 |
| `ERR_WIPE_DOWN_MISSING` | 409 |
| `ERR_DWELL_TIME_NOT_MET` | 409 |
| `ERR_BATCH_NOT_COMPLETE` | 409 |
| `ERR_BATCH_NOT_ON_HOLD` | 409 |
| `ERR_BATCH_NOT_STARTABLE` | 409 |
| `ERR_BATCH_TRAVELERS_UNSETTLED` | 409 |
| `ERR_TRAVELER_STEP_ORDER` | 409 |
| `ERR_TRAVELER_NOT_IN_PROGRESS` | 409 |
| `ERR_TRAVELER_PERFORMER_MISMATCH` | 409 |
| `ERR_TRAVELER_NOT_VOIDABLE` | 409 |
| `ERR_PROGRAM_ALREADY_ACTIVE` | 409 |
| `ERR_CYCLE_NOT_RECORDED` | 409 |
| `ERR_CYCLE_RESULT_FAIL` | 409 |
| `ERR_AUDIT_NOT_SCHEDULED` | 409 |
| `ERR_AUDIT_WINDOW_NOT_STARTED` | 409 |
| `ERR_AUDIT_NOT_IN_PROGRESS` | 409 |
| `ERR_AUDIT_FINDINGS_OPEN` | 409 |
| `ERR_FINDING_NOT_OPEN` | 409 |
| `ERR_FINDING_NOT_CAPA_SUBMITTED` | 409 |
