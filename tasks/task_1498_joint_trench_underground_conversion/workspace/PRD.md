# Joint Trench Undergrounding API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Joint Trench Undergrounding API, the coordination backbone for Rule 20 underground conversion projects in which several utilities — electric, telecom, and cable television — share a single open trench to relocate overhead facilities below grade. The program's economics rest on a defensible split of shared costs: each participating utility commits to a basis-point share of the estimated project cost, actual costs are appended to an immutable ledger as work proceeds, and a closing true-up reconciles provisional shares against audited actuals, drawing down the program's Rule 20 credit pool and billing or refunding each participant for the difference. Getting that waterfall right — including its rounding order, its credit consumption sequence, and its segregation of duties between the analyst who drafts a settlement and the manager who publishes it — is the central purpose of the system.

The operational surface is equally constrained. Trench depth is a scarce, regulated resource governed by minimum cover, pairwise vertical separation (with a reduced-separation waiver for qualifying utility pairs), and an electric-deepest placement rule. Excavation may begin only after every parcel along a segment has a recorded trench easement and an issued encroachment permit whose validity window covers the dig. Customer conversions involve panel capacity rules, temporary service, and outage windows bounded by crew capacity and a strict notification lead time. Change orders freeze the segments they touch, reprice the project, and feed a tiered liquidated-damages computation; restoration work carries a warranty clock. Wherever one writer's stale view could silently overwrite another's committed schedule or settlement, the API applies explicit optimistic concurrency control. All resources are mounted under the `/api` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, response contracts, and cross-cutting principles that apply uniformly to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request whose role header is missing or does not name a declared role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes five roles, spelled exactly as follows:

- `ProgramManager` — the utility program manager: owns the project lifecycle, trench segments, change orders, true-up publication, invoice dispute resolution, and restoration acceptance.
- `RightOfWayAgent` — the land and right-of-way specialist: owns easements and permits, and may register parcels.
- `UtilityCoordinator` — a participating utility's trench coordinator: commits and withdraws its own participation, reserves and works its own occupancy slots, requests and runs outage windows, and pays or disputes its own invoices.
- `ConversionContractor` — the service conversion and restoration contractor: owns service conversions and performs restoration work.
- `FinanceAnalyst` — the cost accountant: submits actual cost entries and drafts true-up runs, but may never publish one.

Role identity is anchored as follows. When `X-User-Role` is `UtilityCoordinator`, `X-User-ID` is the `id` of the acting `UtilityParticipation`; ownership checks on any resource that references a `UtilityParticipation` compare the resource's foreign-key field to `X-User-ID`. This ownership rule applies to participation transitions, occupancy-slot creation and transitions (the slot's owning participation must match), and invoice payment and dispute (the invoice's owning participation must match); a mismatch is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403). When `X-User-Role` is `ProgramManager`, `RightOfWayAgent`, `ConversionContractor`, or `FinanceAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `submitted_by_user_id` on an actual cost entry, `created_by_user_id` on a true-up run, or `published_by_user_id` on a published run — but it is never compared to any entity's `id`.

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

---

### 2.3. Pagination

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

Paginated list responses carry four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — projects, participations, trench segments, occupancy slots, parcels, easements, permits, service conversions, outage windows, change orders, true-up runs, invoices, and restoration tasks — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource.
- `version` (integer): a system-managed integer that increments by one with every modification of the resource, and anchors the optimistic concurrency control described in §2.8.

One entity breaks this pattern. An `ActualCostEntry` is append-only: it carries `id` and `created_at` only, has no `updated_at` and no `version`, and exposes no update or transition endpoints. Once appended, a cost entry is immutable; corrections take the form of new entries.

A further convention runs through every entity: late-bound fields read null until the event that supplies them occurs. These are `withdrawn_on` (set at withdrawal), `excavation_start_on` and `excavation_end_on` (set at scheduling), `requested_on`, `signed_on`, and `recorded_on` (set at their easement steps), `panel_capacity_amps` (set when the panel is set), `last_inspection_outcome` (set at the first inspection), `energized_on` (set at energization), `notified_at` (set at notification), `delta_cost_cents`, `delta_delay_days`, and `delay_cause` (set when a change order is priced), `published_by_user_id` (set at publication), `paid_on` (set at payment), `completed_on` and `warranty_expires_on` (set at restoration completion), and `accepted_on` (set at acceptance). In the same way, a project's `latest_true_up_run_id` is null until its first true-up run exists, and a participation's `final_share_cents` is null until the first draft true-up run computes it.

### 2.5. The Logical Clock

All time-dependent evaluation in the system runs against a server-side logical clock, never against wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`. An administrative, `ProgramManager`-only test-driving capability advances the clock to a supplied `to_iso8601` instant; the server never silently falls back to real time.

Three families of rules read this clock. First, permit expiry is lazy: an `ISSUED` permit flips to `EXPIRED` whenever it is read or referenced while the clock has passed its `valid_to`, and advancing the clock triggers a sweep that applies this transition to every overdue permit. Second, invoice late fees are computed at read time against the clock, so the amount due on an unpaid invoice grows as the clock advances. Third, every lead-time and window check — the seventy-two-hour notification lead, outage execution bounds, the warranty claim deadline, and all timestamp fields described as "the clock timestamp" — evaluates against the logical clock.

### 2.6. Money, Precision, and the Pinned Rounding Order

All monetary values in the system are integer cents. Fields such as `estimated_total_cost_cents`, `rule20_credit_cents`, `provisional_share_cents`, `final_share_cents`, `delta_cost_cents`, `amount_cents`, `principal_cents`, `late_fee_cents`, `amount_due_cents`, and `liquidated_damages_cents` are whole numbers of cents; every division or percentage applied to a monetary value rounds half up to the nearest cent.

Every allocation that splits a pool across participants follows one pinned ordering: participants are processed in ascending `sequence_order`, with ties broken by ascending `created_at`. Per-participant rounding happens first, at the individual share, and only then is any remainder reconciled — this order is fixed and may not be reinterprected. The same pinned order governs the provisional share computation, the gross-share step of the final true-up, and the Rule 20 credit waterfall, so that all three consume participants in an identical sequence.

### 2.7. Project Posture and Segment Freezes

Beyond its lifecycle `status`, every project carries a derived `posture` of `CLEAR`, `CONDITIONAL`, or `FROZEN`, recomputed whenever change orders, easements, permits, or participation shares change. The derivation is ordered: the posture is `FROZEN` whenever any change order of the project is `APPROVED`; otherwise it is `CONDITIONAL` whenever any `TRENCH` easement on any parcel of the project is `REFUSED`, or whenever any participation's `variance_flag` is true; otherwise it is `CLEAR`. A permit that lazily expires or is revoked also triggers a posture recomputation.

Posture gates work in two places. At the project level, advancing from `MOBILIZED` to `TRENCHING` is rejected with `ERR_POSTURE_FROZEN` (HTTP 409) while the posture is `FROZEN`. At the segment level, each trench segment carries a computed boolean `frozen`, true while an `APPROVED` change order references that segment — or references no segments at all, which marks the change order project-wide and freezes every segment. A frozen segment refuses scheduling and rescheduling, new occupancy-slot reservations, and state-transition requests with `ERR_CHANGE_ORDER_FREEZE` (HTTP 409); the freeze lifts when the change order is incorporated (or otherwise leaves `APPROVED`).

### 2.8. Optimistic Concurrency Control

Three write operations require the caller to present the version of a parent resource it last observed, and reject the write when that version no longer matches:

- Creating a true-up run requires the request body to carry `expected_project_version`, equal to the target project's current `version`. If another writer has advanced the project's version since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The protection exists because creating a run legitimately supersedes the project's previously published run; a writer holding a stale project version would silently supersede a run it never saw.
- Scheduling or rescheduling a trench segment requires `expected_trench_segment_version`, equal to the segment's current `version`. A mismatch with the segment's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because a reschedule legitimately replaces the current excavation window and a stale writer would silently discard a window it never saw.
- Replanning a project's cutover date likewise requires `expected_project_version`, and a mismatch with the project's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed here do not take a version field. All three protected operations increment the parent resource's `version` by one on success, so every successful write invalidates the version the next writer may be holding.

### 2.9. Segregation of Duties in Settlement

Cost capture and settlement authority are deliberately split across two roles. A `FinanceAnalyst` appends actual cost entries — each entry records the submitter's `X-User-ID` as `submitted_by_user_id` — and drafts true-up runs, each recording its creator as `created_by_user_id`. Only a `ProgramManager` may publish a run, and publication is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) in two cases: when the publisher's `X-User-ID` equals the run's `created_by_user_id`, and when the publisher's `X-User-ID` equals the `submitted_by_user_id` of any actual cost entry included in the run. The analyst who knows the costs may never be the manager who turns them into invoices.

### 2.10. Validation Order and Reference Resolution

When several checks could reject the same request, the server applies them in a fixed precedence so that the surfaced error is deterministic. Authentication comes first: a missing or unrecognized role yields `ERR_UNAUTHENTICATED`, and a recognized role without endpoint authorization yields `ERR_FORBIDDEN`. For the endpoints a `UtilityCoordinator` must own, the ownership check follows next and mismatches yield `ERR_OWNERSHIP_VIOLATION`. Existence is then resolved left to right: path parameters and body references are checked in order, and the first reference that does not correspond to an existing resource is rejected with `ERR_NOT_FOUND` (HTTP 404) before any deeper validation runs. Structural validation follows — required fields present, types valid, enum members recognized, and start-before-end ordering on windows — with failures returning `ERR_VALIDATION` (HTTP 400). Only then does the server evaluate, in order: optimistic concurrency mismatches (`ERR_STALE_VERSION`); state-machine legality, including terminal-state lockdown (`ERR_INVALID_STATE`, HTTP 409); posture and freeze gates (`ERR_POSTURE_FROZEN`, `ERR_CHANGE_ORDER_FREEZE`); business safety rules such as trench geometry and outage coverage; referential gates such as easements and permits; temporal gates such as permit windows, slot windows, notification lead time, and warranty deadlines; capacity and constraint checks such as slot conflicts, crew capacity, and panel sizing; and finally the fiscal rules — share sums, exact payment amounts, and segregation of duties.

Every state machine in the system also observes terminal lockdown: once an entity reaches a terminal state, every further transition request on it is rejected with `ERR_INVALID_STATE`.

## 3. Business Logic & Workflows

### 3.1. Project Formation and Utility Participation

A `ProgramManager` opens a project by supplying a `name`, the `estimated_total_cost_cents` (strictly greater than zero), the `rule20_credit_cents` pool (zero or greater — the program credit consumed later during settlement), and the `target_cutover_on` date. An optional `contingency_days` allowance (zero or greater, defaulting to zero) sets the excusable-delay buffer before liquidated damages accrue. A new project starts in `PLANNING` status with posture `CLEAR`, zero `cumulative_delay_days`, zero `liquidated_damages_cents`, and no `latest_true_up_run_id` — that field stays null until the first true-up run exists.

While the project is in `PLANNING` (or later, per the invitation rules below), the `ProgramManager` invites utilities by creating participation records carrying `project_id`, `utility_name`, a `utility_type` of `ELECTRIC`, `TELECOM`, or `CATV`, a `cost_share_bp` expressed in basis points (each between 1 and 10000, where ten thousand basis points make the whole), a `sequence_order` of at least 1 that fixes both trench order and billing order and must be unique among the project's non-withdrawn participants, and an optional `has_separation_waiver` flag (defaulting to false) attesting that this utility has signed the joint-trench reduced-separation waiver. Invitations are accepted only while the project is in `PLANNING` or `MOBILIZED`; any later attempt is rejected with `ERR_INVALID_STATE`. A fresh participation starts `INVITED`.

Commitment is the utility's own act. A `UtilityCoordinator` acting on its own participation moves it `INVITED → COMMITTED` while the project is in `PLANNING`, and later `COMMITTED → MOBILIZED` once the project itself is `MOBILIZED`, `TRENCHING`, or `CONVERTING`. The participation listing may be filtered by `project_id` and `status`.

All project lifecycle moves are driven through a single mechanism whose `action` field names the desired move — `MOBILIZE`, `START_TRENCHING`, `START_CONVERSION`, `START_RECONCILIATION`, `CLOSE`, or `CANCEL`. Likewise, every entity-level transition in the system is requested with a `to` field naming the target state.

Mobilizing the project (`PLANNING → MOBILIZED`) is the first hard fiscal checkpoint, and it evaluates three gates in the global validation order: at least two participations must be in `COMMITTED` status (`ERR_MIN_PARTICIPANTS`), no two non-withdrawn participations may share a `sequence_order` (`ERR_DUPLICATE_SEQUENCE`), and the `cost_share_bp` values of the participations in `COMMITTED` or `MOBILIZED` must sum to exactly ten thousand (`ERR_SHARE_SUM_INVALID`). On success, the system computes each committed participant's `provisional_share_cents` by waterfall allocation: taking the project's estimated total cost, each participant's raw share is the total multiplied by its basis points and divided by ten thousand, rounded half up to a whole cent, computed per participant in the pinned order (ascending `sequence_order`, ties by ascending `created_at`); the remainder — the estimated total minus the sum of those raw shares — is then distributed one cent at a time, added when the remainder is positive and removed when negative, walking participants in that same pinned order, which never wraps because the absolute remainder is always smaller than the participant count. The invariant after every run of this computation is that the provisional shares of the active participants sum exactly to the estimated total. The computation also maintains `variance_flag` on each participation: the flag becomes true when a previous provisional value existed and the absolute difference between the new and old values is at least ten percent of the old value. Withdrawn participants are excluded from the input set entirely and carry a share of zero; the input set is otherwise every participation in `COMMITTED`, `MOBILIZED`, `INSTALLED`, `BILLED`, or `SETTLED`.

A utility may withdraw while its participation is `INVITED`, `COMMITTED`, or `MOBILIZED`; the same transition is unavailable once installed. Withdrawal fires a six-hop cascade. The participation moves to `WITHDRAWN`, records `withdrawn_on` as the clock timestamp, and its `provisional_share_cents` drops to zero. Every occupancy slot it holds in `RESERVED`, `INSTALLING`, or `INSTALL_FAILED` is released. Each affected segment then recomputes its occupied and available depth. The remaining non-withdrawn participations rescale their `cost_share_bp` so the total returns to ten thousand: each surviving share becomes its current basis points multiplied by ten thousand and divided by the sum of the surviving shares, rounded half up, and any residual rounding drift is corrected by adjusting the participant with the lowest `sequence_order` — ties broken by earliest `created_at` — one basis point up or down. The provisional share waterfall then reruns for all non-withdrawn participants, each participant's `variance_flag` is refreshed, and the project posture is recomputed.

From `MOBILIZED`, the project advances to `TRENCHING` only while its posture is not `FROZEN` and at least one of its trench segments is `SCHEDULED`. A project may instead be cancelled — `PLANNING → CANCELLED` or `MOBILIZED → CANCELLED` — which is a purely administrative act: participations in `INVITED` or `COMMITTED` are left unchanged by it.

### 3.2. Right-of-Way: Parcels, Easements, and Permits

Every property the route touches is registered as a parcel. A `RightOfWayAgent` (or the `ProgramManager`) creates it with `project_id`, `address`, `owner_name`, the `existing_panel_amps` rating of the property's current service panel (greater than zero), and the `load_calc_amps` calculated load (greater than zero). The electrical consequences of those two numbers are computed at creation and detailed in §3.5. Parcels may be listed with a `project_id` filter.

Easements attach to parcels. A `RightOfWayAgent` creates one from a `parcel_id` and an `easement_type` of `TRENCH`, `ACCESS`, or `ANCHOR`; only `TRENCH` easements gate excavation. The easement lifecycle runs `DRAFT → REQUESTED → SIGNED → RECORDED`, with each step stamping the clock onto `requested_on`, `signed_on`, and `recorded_on` respectively, and `RECORDED` terminal. A landowner can refuse: `REQUESTED → REFUSED` recomputes the project posture, which turns `CONDITIONAL` while any `TRENCH` easement stands refused. Refusal is not the end of negotiation — `REFUSED → REQUESTED` reopens the easement, refreshes `requested_on` to the clock, and recomputes posture again. Recording an easement also recomputes posture. The easement listing filters by `parcel_id` and `status`.

Permits attach to the project. Creation takes `project_id`, a `permit_type` of `ENCROACHMENT`, `TRAFFIC_CONTROL`, or `GRADING`, and a validity window `valid_from` to `valid_to`, the end strictly after the start. Permits move `APPLICATION → SUBMITTED → ISSUED` under the `RightOfWayAgent`. From `ISSUED` there are three exits: the authority may revoke the permit (`ISSUED → REVOKED`), which recomputes the project posture; the permit may lapse — the moment the logical clock passes `valid_to`, any read or reference lazily flips it `ISSUED → EXPIRED` and recomputes posture; and once the project itself is `CLOSED`, the permit may be closed (`ISSUED → CLOSED`), which is rejected with `ERR_INVALID_STATE` at any earlier project stage. Permit listings filter by `project_id`, `permit_type`, and `status`.

### 3.3. Trench Segments: Scheduling, Excavation, and Backfill

The `ProgramManager` decomposes the route into trench segments, each created in `PLANNED` status with `project_id`, a human-readable `segment_code`, a `length_ft` in feet (greater than zero), a `max_depth_inches` usable depth (greater than zero), and an optional `parcel_ids` array naming every parcel the segment passes through. The segment listing filters by `project_id`, `status`, and `parcel_ids` — the last matching any segment whose route contains the given parcel.

Scheduling pins the dig window. Setting `excavation_start_on` and `excavation_end_on` (start strictly before end, else `ERR_VALIDATION`) moves a segment `PLANNED → SCHEDULED`; repeating the operation while `SCHEDULED` reschedules it, superseding the prior window entirely. Both forms require the project to be `MOBILIZED` or `TRENCHING` (`ERR_INVALID_STATE` otherwise), require the segment to be unfrozen (`ERR_CHANGE_ORDER_FREEZE`), and require `expected_trench_segment_version` per §2.8; each success increments the segment's `version` by one.

With the project advanced to `TRENCHING`, excavation begins per segment. Moving `SCHEDULED → EXCAVATING` enforces five gates: the project must be `TRENCHING`; the segment must not be frozen (`ERR_CHANGE_ORDER_FREEZE`); no parcel in `parcel_ids` may hold a `TRENCH` easement in `REFUSED` (`ERR_EASEMENT_REFUSED_BLOCKING`); every parcel in `parcel_ids` must hold a `TRENCH` easement in `RECORDED` (`ERR_EASEMENT_NOT_RECORDED`); an `ENCROACHMENT` permit in `ISSUED` status must exist for the project (`ERR_PERMIT_NOT_ISSUED`); and that permit's validity window must cover the whole excavation window, both endpoints inclusive (`ERR_PERMIT_WINDOW_VIOLATION`). When the dig is done, `EXCAVATING → BACKFILLING` requires that every occupancy slot of the segment has reached `INSTALLED`, `VERIFIED`, or `RELEASED` (`ERR_INVALID_STATE` otherwise). `BACKFILLING → BACKFILLED` carries no further gates. A segment that discovers a defect may be reopened — `BACKFILLED → EXCAVATING` — under exactly the same freeze, easement, and permit gates as the original excavation entry. Finally, `BACKFILLED → CLOSED` requires every restoration task on the segment to be `ACCEPTED` (`ERR_RESTORATION_OPEN_BLOCKING`), which ties the surface-restoration workflow of §3.8 into segment closure. Once every segment of the project is `BACKFILLED` or `CLOSED`, the `ProgramManager` may advance the project `TRENCHING → CONVERTING`.

Two derived numbers track depth consumption on each segment. `occupied_depth_inches` is the greatest `depth_bottom_inches` among the segment's slots in `RESERVED`, `INSTALLING`, `INSTALLED`, or `VERIFIED` — zero when no such slot exists — and `available_depth_inches` is `max_depth_inches` minus the occupied depth. Both recompute whenever slots are reserved, installed, verified, released, or swept by a withdrawal cascade.

### 3.4. Occupancy Slots: Depth Bands, Separation, and Install Order

Within a scheduled segment, a `UtilityCoordinator` reserves its own participation's facility band by creating an occupancy slot with `trench_segment_id`, `participation_id` (which must be the coordinator's own participation, else `ERR_OWNERSHIP_VIOLATION`), `depth_top_inches`, `depth_bottom_inches`, `install_start_at`, and `install_end_at`. Reservation is possible only while the segment is `SCHEDULED` or `EXCAVATING` (`ERR_INVALID_STATE` otherwise) and never while the segment is frozen (`ERR_CHANGE_ORDER_FREEZE`). A new slot starts in `RESERVED`, and creating one recomputes the segment's depth figures. The slot listing filters by `trench_segment_id`, `participation_id`, and `status`.

Geometry is enforced at reservation time, after structure, state, and freeze checks and before window-conflict checks, per the global order of §2.10. The top of any band must sit at least twelve inches below grade (`depth_top_inches` of 12 or more; less is `ERR_MIN_COVER_VIOLATION`), and the bottom must lie within the segment's usable depth (`depth_bottom_inches` no greater than `max_depth_inches`, else `ERR_DEPTH_CAPACITY_EXCEEDED`); the bottom must also exceed the top, with malformed bands caught as `ERR_VALIDATION`. Bands on the same segment may never overlap vertically: for a candidate band and each existing band in `RESERVED`, `INSTALLING`, `INSTALL_FAILED`, `INSTALLED`, or `VERIFIED` (released slots no longer participate), the vertical gap is the absolute difference between the candidate's top and the existing band's bottom when the candidate sits above it, otherwise the absolute difference between the existing band's top and the candidate's bottom, and overlapping bands count as a gap of zero. The required gap is six inches only when both participants are non-`ELECTRIC` and both hold a signed separation waiver (`has_separation_waiver` true); in every other pairing it is twelve inches. Any pair below its requirement is rejected with `ERR_MIN_SEPARATION_VIOLATION` — which is also why overlapping bands can never pass. On top of pairwise separation, the electric-deepest rule applies whenever any slot on the segment belongs to an `ELECTRIC` participation: every non-electric band's `depth_bottom_inches` must be at most the smallest electric band's `depth_top_inches` minus twelve inches, and no electric band may be placed above a non-electric band; violations are rejected with `ERR_ELECTRIC_NOT_DEEPEST`.

Time is enforced next. Each install window is a half-open interval — a band's crews own the segment from `install_start_at` up to but not including `install_end_at`, and the end must be strictly after the start. Every window must lie entirely within the segment's excavation window, both endpoints inclusive (`ERR_SLOT_WINDOW_OUT_OF_RANGE`). Two slots on the same segment whose vertical gap is less than twenty-four inches must hold disjoint windows; touching windows, where one ends exactly when the other begins, are allowed, and the shallower slot's window may not begin before the deeper slot's window ends — crews always work deeper-first. Bands separated by twenty-four inches or more may overlap in time freely. Breaches are rejected with `ERR_SLOT_WINDOW_CONFLICT`.

Installation then proceeds slot by slot. Moving `RESERVED → INSTALLING` requires the segment to be `EXCAVATING` and every deeper slot on the same segment — any slot whose `depth_top_inches` is greater — to be `INSTALLED` or `VERIFIED` (`ERR_SLOT_ORDER_VIOLATION`). From `INSTALLING` the coordinator reports success (`→ INSTALLED`) or failure (`→ INSTALL_FAILED`); a failed install may be retried (`INSTALL_FAILED → INSTALLING`) under the same deeper-first gate. The `ProgramManager` alone confirms quality with `INSTALLED → VERIFIED`. A slot in `RESERVED` or `INSTALL_FAILED` may instead be released (`→ RELEASED`) by its owning coordinator — or by the system during a withdrawal cascade — and each release recomputes the segment's occupied and available depth. Once every slot a participation holds has reached `VERIFIED` or `RELEASED`, that participation may advance `MOBILIZED → INSTALLED`.

### 3.5. Customer Service Conversion and Panel Work

The customer-facing half of the program runs on parcels. At parcel creation the system derives `panel_upgrade_required`: true exactly when the calculated load reaches at least eighty percent of the existing panel rating — an exact eighty-percent match requires the upgrade. This flag is a read-only consequence of `load_calc_amps` and `existing_panel_amps`, not an input.

A `ConversionContractor` opens a service conversion with `parcel_id` and `project_id`; the project reference is a denormalized filter key and must equal the parcel's own project, with a mismatch rejected as `ERR_VALIDATION`. The new conversion carries two independent state dimensions that evolve in parallel: `work_status`, starting at `PLANNED`, and `temp_service_status`, starting at `NONE`. Listings filter by `project_id`, `parcel_id`, and `work_status`.

The work axis runs `PLANNED → ROUGH_IN → PANEL_SET → READY_TO_ENERGIZE → ENERGIZED → INSPECTED → COMPLETE`, with one rework loop. Rough-in may begin while the project is `TRENCHING` or `CONVERTING` (`ERR_INVALID_STATE` otherwise). Setting the panel takes a `panel_capacity_amps` value in the request: the new panel's rating must be at least the parcel's calculated load multiplied by 1.25 and rounded up to a whole amp — equality passes, one amp less is rejected with `ERR_PANEL_CAPACITY_INADEQUATE` — and the accepted rating is recorded on the conversion. Energization (`READY_TO_ENERGIZE → ENERGIZED`) is gated on civil completion: the trench segment whose `parcel_ids` contains this parcel must be `BACKFILLED` or `CLOSED` (`ERR_SEGMENT_NOT_BACKFILLED`), and success stamps `energized_on` with the clock. Inspection then decides between two sibling branches off `ENERGIZED`, driven by the submitted `outcome`: a `PASS` moves the conversion to `INSPECTED` and records `last_inspection_outcome` as `PASS`, while a `FAIL` sends the conversion back to `ROUGH_IN` for rework, records `last_inspection_outcome` as `FAIL`, and resets `panel_capacity_amps` to null so the panel must be sized and set again; any `outcome` value other than the one the chosen transition expects is `ERR_VALIDATION`. Completion (`INSPECTED → COMPLETE`) additionally requires that temporary service is fully out of the picture — `temp_service_status` of `NONE` or `TEMP_REMOVED` (`ERR_INVALID_STATE` otherwise).

The temporary-service axis runs `NONE → TEMP_INSTALLED → TEMP_ACTIVE → TEMP_REMOVED`. Removal is the only gated step: `TEMP_ACTIVE → TEMP_REMOVED` requires the work axis to be `ENERGIZED` or `INSPECTED`, so temporary power cannot come down before permanent power is live. Before the project can leave the conversion phase at all, every service conversion of the project must have reached `COMPLETE` — one of the reconciliation gates described in §3.9.

### 3.6. Outage Windows and Crew Coordination

Planned outages are proposed per feeder. A `UtilityCoordinator` or the `ProgramManager` creates a window in `PROPOSED` status with `project_id`, `feeder_id` (crew capacity is tracked per feeder), `start_at`, `end_at`, and an optional `conversion_ids` array naming the affected conversions. Outage listings filter by `project_id`, `feeder_id`, `status`, and `conversion_ids`, the last matching any window that affects the given conversion.

Approval (`PROPOSED → APPROVED`) is the `ProgramManager`'s and enforces three checks. The duration must not exceed eight hours — exactly eight hours passes, anything longer is `ERR_OUTAGE_DURATION_EXCEEDED`. Crew capacity is evaluated with half-open semantics, so back-to-back windows where one ends exactly when the next begins do not overlap: at every instant inside the candidate window, the number of windows on the same feeder in `APPROVED`, `NOTIFIED`, or `EXECUTED` status — counting the candidate — must stay at or below two, else `ERR_CREW_CAPACITY_EXCEEDED`. Every id in `conversion_ids` must exist and belong to this project (`ERR_VALIDATION`).

Customer notification (`APPROVED → NOTIFIED`) is performed by a `UtilityCoordinator` and is bound by a hard lead time: the gap between `start_at` and the logical clock must be at least seventy-two hours; exactly seventy-two hours to the second passes, one second less is rejected with `ERR_NOTIFICATION_LEAD_TIME`. Success stamps `notified_at` with the clock. Execution (`NOTIFIED → EXECUTED`, again the `UtilityCoordinator`) must fall inside the window — starting before `start_at` is `ERR_INVALID_STATE`, and attempting after `end_at` is `ERR_OUTAGE_WINDOW_MISSED` — and every conversion named in `conversion_ids` must either have `work_status` of `ENERGIZED`, `INSPECTED`, or `COMPLETE`, or be riding active temporary service with `temp_service_status` of `TEMP_ACTIVE` (`ERR_TEMP_SERVICE_REQUIRED`). A successful execution later closes (`EXECUTED → CLOSED`).

Plans change. A notified window may be rescheduled — `NOTIFIED → PROPOSED` by the `ProgramManager`, supplying `new_start_at` and `new_end_at` (the new start strictly before the new end, else `ERR_VALIDATION`) — which replaces `start_at` and `end_at` and resets `notified_at` to null, forcing the notification lead time to be earned again. Cancellation (`→ CANCELLED`) is available to the `ProgramManager` from any of `PROPOSED`, `APPROVED`, or `NOTIFIED`, with equal effect from each.

### 3.7. Change Orders, Replanning, and Liquidated Damages

Scope changes enter as change orders created by the `ProgramManager` in `PROPOSED` status with `project_id`, a free-text `description`, and an optional `segment_ids` array; an empty or omitted array means the change is project-wide. The listing filters by `project_id`, `status`, and `segment_ids`, the last matching change orders that reference the given segment.

Pricing (`PROPOSED → PRICED`) supplies the commercial terms: a signed `delta_cost_cents`, a `delta_delay_days` that must not be negative (`ERR_VALIDATION`), and a `delay_cause` of `EXCUSABLE`, `NEGLIGENT`, or `MIXED`. All three are required to price; all three are cleared back to null if the order is revised (`PRICED → PROPOSED`), which also increments the order's `revision_count` — a counter that starts at zero on creation — by one. Approval (`PRICED → APPROVED`) is what bites: every referenced segment — or every segment of the project when `segment_ids` is empty — becomes `frozen`, and the project posture recomputes to `FROZEN` while any change order stands approved. Incorporation (`APPROVED → INCORPORATED`) folds the change into the baseline through one cascade: the project's `estimated_total_cost_cents` increases by `delta_cost_cents` (which may lower it when the delta is negative) and `cumulative_delay_days` increases by `delta_delay_days`; the provisional share waterfall of §3.1 reruns for all non-withdrawn participants against the new estimate; each participant's `variance_flag` refreshes and the project posture recomputes; the frozen segments unfreeze; and the project's `liquidated_damages_cents` is recomputed. Change orders may equally be rejected or withdrawn — `PROPOSED → REJECTED`, `PRICED → REJECTED`, `PROPOSED → WITHDRAWN`, and `PRICED → WITHDRAWN` are all available, each simply terminal with no cascade.

Liquidated damages are computed over incorporated orders only. Each incorporated order contributes its `delta_delay_days` weighted by cause: full weight for `NEGLIGENT`, half weight for `MIXED`, and zero for `EXCUSABLE`. The weighted days are summed, the project's `contingency_days` allowance is subtracted, and the result is floored at zero — the excusable-delay buffer absorbs overrun before damages accrue. The raw damages are those billable days multiplied by five hundred dollars per day (50000 cents). The cap is ten percent of the project's `estimated_total_cost_cents`, rounded half up to a whole cent. The project's `liquidated_damages_cents` is the smaller of the raw figure and the cap.

Separately from change control, the `ProgramManager` may rebaseline the schedule: replanning takes `new_target_cutover_on` together with `expected_project_version` per §2.8, replaces the project's `target_cutover_on`, and increments the project `version` by one. Successive replans supersede earlier ones, and a stale version is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 3.8. Restoration and Warranty

Giving the street back is tracked as restoration tasks. A `ConversionContractor` or the `ProgramManager` creates one in `OPEN` status with `trench_segment_id`, `parcel_id`, and a `task_type` of `HARDSCAPE`, `LANDSCAPE`, or `IRRIGATION`; listings filter by those same three identifiers. The contractor works the task (`OPEN → IN_WORK`) and reports completion (`IN_WORK → COMPLETE`), which stamps `completed_on` with the clock and sets `warranty_expires_on` exactly one hundred eighty days later. Acceptance (`COMPLETE → ACCEPTED`) is the `ProgramManager`'s sign-off and stamps `accepted_on`; `ACCEPTED` is the terminal state, and it is also the gatekeeper for segment closure — a segment cannot close while any of its restoration tasks is short of `ACCEPTED` (§3.3).

Accepted work remains under warranty. While the logical clock has not passed `warranty_expires_on` — the expiry instant itself is still claimable — the `ProgramManager` may open a warranty claim (`ACCEPTED → WARRANTY_CLAIM`); one second past expiry the attempt fails with `ERR_WARRANTY_EXPIRED`. A claim returns the task to the contractor's queue (`WARRANTY_CLAIM → IN_WORK`), from which the normal completion and acceptance cycle runs again.

### 3.9. Actual Costs, True-Up Reconciliation, and Settlement

Reconciliation begins when the physical work is verifiably done. Advancing the project `CONVERTING → RECONCILIATION` requires that every service conversion has `work_status` of `COMPLETE`, every trench segment is `CLOSED`, and every outage window is `CLOSED` or `CANCELLED`; any shortfall is `ERR_INVALID_STATE`. In this phase the finance workflow takes over.

Actual costs accumulate on an append-only ledger. A `FinanceAnalyst` appends each entry with `project_id`, a `cost_code` of `JOINT_TRENCH`, `EXCLUSIVE`, `RESTORATION`, or `PROGRAM_OVERHEAD`, an `amount_cents` greater than zero, and the `incurred_on` date; `participation_id` is required exactly when the cost code is `EXCLUSIVE` and is omitted otherwise. The server records the submitter's `X-User-ID` as `submitted_by_user_id`, anchoring the segregation-of-duties check at publication. Entries are immutable once written — no update or delete exists — and listings, restricted to `ProgramManager` and `FinanceAnalyst`, filter by `project_id`, `cost_code`, and `participation_id`.

Drafting a settlement is the second OCC-protected write of §2.8. A `FinanceAnalyst` creates a true-up run with `project_id` and `expected_project_version`; a stale project version is rejected with `ERR_STALE_VERSION` (HTTP 412). Three prerequisites gate creation — the project must be in `RECONCILIATION`, every trench segment must be `CLOSED`, and every non-withdrawn participation must be `INSTALLED`, `BILLED`, or `SETTLED` — with any failure rejected as `ERR_TRUEUP_PREREQUISITES`. Creating a run supersedes: any previously `PUBLISHED` run of the same project flips to `SUPERSEDED`, and its invoices still in `ISSUED` or `DISPUTED` flip to `VOID`. The new run starts in `DRAFT`, records `created_by_user_id` from the header, bumps the project `version` by one, and becomes the project's `latest_true_up_run_id`. Run listings filter by `project_id` and `status`.

Creation computes the full allocation waterfall. The joint pool is the sum of `amount_cents` over all entries coded `JOINT_TRENCH`, `RESTORATION`, or `PROGRAM_OVERHEAD`; each participant's exclusive total is the sum of entries coded `EXCLUSIVE` against it; the run's `total_actual_cost_cents` is the joint pool plus every exclusive total. Gross shares divide the joint pool using exactly the pinned rounding order and remainder reconciliation of the provisional waterfall in §3.1. The Rule 20 credit then consumes in participation order: starting from the project's `rule20_credit_cents`, each participant in turn absorbs the smaller of the remaining credit and its own gross share, the remainder shrinking as the walk proceeds; the run's `rule20_credit_applied_cents` is the pool minus whatever remains, and never exceeds the pool. Each participant's `final_share_cents` is its gross share minus its absorbed credit plus its exclusive total, and this value is also written back onto the participation itself — before the first draft run exists, the participation's `final_share_cents` is null. The delta is the final share minus the provisional share, and the refund is the absolute value of a negative delta — zero when the delta is positive. All of this lands on the run's `lines` array: one object per participation carrying `participation_id`, `gross_share_cents`, `credit_cents`, `exclusive_cents`, `final_share_cents`, `delta_cents`, and `refund_cents`. Withdrawn participations are excluded from shares, lines, and invoices alike. Where the provisional waterfall priced the estimate and ignored actuals, credits, and exclusives, this final variant prices audited actuals — identical participation data can and does produce different numbers.

Publication (`DRAFT → PUBLISHED`) belongs to the `ProgramManager` and is the moment segregation of duties bites per §2.9: the publisher's `X-User-ID` must differ from the run's `created_by_user_id` and from the `submitted_by_user_id` of every included cost entry, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A successful publish stamps `published_by_user_id`, refreshes the project's `latest_true_up_run_id`, and issues an invoice to every non-withdrawn participation whose `delta_cents` is greater than zero — nothing is billed for a zero or negative delta. Invoices are created in participation order (ascending `sequence_order`, ties by ascending `created_at`), each with `principal_cents` equal to the delta, `issued_on` stamped from the clock, `due_on` exactly thirty days after issuance, and status `ISSUED`; every participation that receives one moves `INSTALLED → BILLED` at that moment.

Invoices accrue late fees against the logical clock, evaluated fresh at every read. No fee accrues until the invoice is at least thirty days past `due_on`; from there, lateness is counted in complete thirty-day periods — thirty to fifty-nine days overdue is one period, sixty days is two — where the days overdue are the whole days between `due_on` and the clock. The rate is keyed on `principal_cents` alone: two percent when the principal is at least one hundred thousand dollars (10000000 cents), one and a half percent below that, and the fee never feeds back into the tier. The `late_fee_cents` is the principal multiplied by the rate and by the number of periods, rounded half up to a whole cent, and `amount_due_cents` is `principal_cents` plus `late_fee_cents`. Payment is exact-change only: the owning `UtilityCoordinator` pays by submitting `paid_amount_cents`, which must equal `amount_due_cents` as of the clock — principal plus whatever late fee has accrued — with any mismatch rejected as `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). Success moves the invoice `ISSUED → PAID`, stamps `paid_on`, and when every invoice of that participation has reached `PAID` or `VOID`, the participation cascades `BILLED → SETTLED`.

Disputes run through the same entity. The owning coordinator moves `ISSUED → DISPUTED` with a `reason`; the `ProgramManager` resolves the dispute (`DISPUTED → ISSUED`) optionally carrying `adjusted_principal_cents`, which when provided must be greater than zero (`ERR_VALIDATION`) and replaces `principal_cents`, after which the late fee recomputes from the new principal. An invoice in `ISSUED` or `DISPUTED` may also be voided (`→ VOID`) by the `ProgramManager` — and is voided automatically when its run is superseded. Invoice listings, open to `ProgramManager`, `UtilityCoordinator`, and `FinanceAnalyst`, filter by `true_up_run_id`, `participation_id`, and `status`.

The run itself settles (`PUBLISHED → SETTLED`) once every invoice it issued is `PAID` or `VOID` (`ERR_INVALID_STATE` until then). That settles the project: closing the project (`RECONCILIATION → CLOSED`) requires that the project's latest true-up run exists and stands `SETTLED`. `CLOSED` and `CANCELLED` are the project's terminal states; beyond them, only the permit-closing housekeeping of §3.2 remains.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — lifecycle actions, transitions, scheduling, replanning, and the clock — return `200 OK`, as do all reads. Error responses follow §2.2 and the catalogue in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/projects` | Create a project (PLANNING, posture CLEAR) | ProgramManager |
| GET | `/api/projects` | List projects (filters: `status`, `posture`) | Any authenticated role |
| GET | `/api/projects/{id}` | Get a project (posture, delay days, liquidated damages, version) | Any authenticated role |
| POST | `/api/projects/{id}/lifecycle` | Lifecycle actions: MOBILIZE, START_TRENCHING, START_CONVERSION, START_RECONCILIATION, CLOSE, CANCEL | ProgramManager |
| POST | `/api/projects/{id}/replan` | Rebaseline the cutover date (OCC on project version) | ProgramManager |
| POST | `/api/participations` | Invite a utility (creates participation, INVITED) | ProgramManager |
| GET | `/api/participations` | List participations (filters: `project_id`, `status`) | Any authenticated role |
| GET | `/api/participations/{id}` | Get a participation | Any authenticated role |
| POST | `/api/participations/{id}/transition` | Transition own participation to COMMITTED, MOBILIZED, INSTALLED, or WITHDRAWN | UtilityCoordinator |
| POST | `/api/trench-segments` | Create a trench segment (PLANNED) | ProgramManager |
| GET | `/api/trench-segments` | List segments (filters: `project_id`, `status`, `parcel_ids`) | Any authenticated role |
| GET | `/api/trench-segments/{id}` | Get a segment (depth fields, frozen flag, version) | Any authenticated role |
| POST | `/api/trench-segments/{id}/schedule` | Set or replace the excavation window (OCC on segment version) | ProgramManager |
| POST | `/api/trench-segments/{id}/transition` | Transition segment to EXCAVATING, BACKFILLING, BACKFILLED, or CLOSED (incl. reopen) | ProgramManager |
| POST | `/api/occupancy-slots` | Reserve a depth band and install window (own participation) | UtilityCoordinator |
| GET | `/api/occupancy-slots` | List slots (filters: `trench_segment_id`, `participation_id`, `status`) | Any authenticated role |
| GET | `/api/occupancy-slots/{id}` | Get a slot | Any authenticated role |
| POST | `/api/occupancy-slots/{id}/transition` | Transition slot to INSTALLING, INSTALLED, INSTALL_FAILED, VERIFIED, or RELEASED | UtilityCoordinator, ProgramManager |
| POST | `/api/parcels` | Register a parcel (computes `panel_upgrade_required`) | RightOfWayAgent, ProgramManager |
| GET | `/api/parcels` | List parcels (filter: `project_id`) | Any authenticated role |
| GET | `/api/parcels/{id}` | Get a parcel | Any authenticated role |
| POST | `/api/easements` | Create an easement (DRAFT) | RightOfWayAgent |
| GET | `/api/easements` | List easements (filters: `parcel_id`, `status`) | Any authenticated role |
| GET | `/api/easements/{id}` | Get an easement | Any authenticated role |
| POST | `/api/easements/{id}/transition` | Transition easement to REQUESTED, SIGNED, RECORDED, or REFUSED | RightOfWayAgent |
| POST | `/api/permits` | Create a permit (APPLICATION) | RightOfWayAgent |
| GET | `/api/permits` | List permits (filters: `project_id`, `permit_type`, `status`) | Any authenticated role |
| GET | `/api/permits/{id}` | Get a permit (lazy expiry evaluated at read) | Any authenticated role |
| POST | `/api/permits/{id}/transition` | Transition permit to SUBMITTED, ISSUED, REVOKED, or CLOSED | RightOfWayAgent |
| POST | `/api/service-conversions` | Create a service conversion (work PLANNED, temp NONE) | ConversionContractor |
| GET | `/api/service-conversions` | List conversions (filters: `project_id`, `parcel_id`, `work_status`) | Any authenticated role |
| GET | `/api/service-conversions/{id}` | Get a conversion (both state dimensions) | Any authenticated role |
| POST | `/api/service-conversions/{id}/work-transition` | Work-axis transition; PANEL_SET takes `panel_capacity_amps`, inspection takes `outcome` | ConversionContractor |
| POST | `/api/service-conversions/{id}/temp-service-transition` | Temp-axis transition to TEMP_INSTALLED, TEMP_ACTIVE, or TEMP_REMOVED | ConversionContractor |
| POST | `/api/outage-windows` | Propose an outage window (PROPOSED) | UtilityCoordinator, ProgramManager |
| GET | `/api/outage-windows` | List outages (filters: `project_id`, `feeder_id`, `status`, `conversion_ids`) | Any authenticated role |
| GET | `/api/outage-windows/{id}` | Get an outage window | Any authenticated role |
| POST | `/api/outage-windows/{id}/transition` | Transition outage to APPROVED, NOTIFIED, EXECUTED, CLOSED, CANCELLED, or PROPOSED (reschedule) | ProgramManager, UtilityCoordinator |
| POST | `/api/change-orders` | Create a change order (PROPOSED) | ProgramManager |
| GET | `/api/change-orders` | List change orders (filters: `project_id`, `status`, `segment_ids`) | Any authenticated role |
| GET | `/api/change-orders/{id}` | Get a change order | Any authenticated role |
| POST | `/api/change-orders/{id}/transition` | Transition change order to PRICED, PROPOSED (revise), APPROVED, INCORPORATED, REJECTED, or WITHDRAWN | ProgramManager |
| POST | `/api/actual-cost-entries` | Append an immutable actual cost entry | FinanceAnalyst |
| GET | `/api/actual-cost-entries` | List actual cost entries (filters: `project_id`, `cost_code`, `participation_id`) | ProgramManager, FinanceAnalyst |
| GET | `/api/actual-cost-entries/{id}` | Get an actual cost entry | ProgramManager, FinanceAnalyst |
| POST | `/api/true-up-runs` | Create a true-up run (computes lines; supersedes prior PUBLISHED run; OCC on project version) | FinanceAnalyst |
| GET | `/api/true-up-runs` | List true-up runs (filters: `project_id`, `status`) | ProgramManager, FinanceAnalyst |
| GET | `/api/true-up-runs/{id}` | Get a true-up run including computed lines | ProgramManager, FinanceAnalyst |
| POST | `/api/true-up-runs/{id}/transition` | Publish (segregation of duties; issues invoices) or settle a run | ProgramManager |
| GET | `/api/invoices` | List invoices (filters: `true_up_run_id`, `participation_id`, `status`) | ProgramManager, UtilityCoordinator, FinanceAnalyst |
| GET | `/api/invoices/{id}` | Get an invoice (late fee evaluated at read) | ProgramManager, UtilityCoordinator, FinanceAnalyst |
| POST | `/api/invoices/{id}/transition` | Transition invoice to PAID, DISPUTED, ISSUED (dispute resolution), or VOID | UtilityCoordinator, ProgramManager |
| POST | `/api/restoration-tasks` | Create a restoration task (OPEN) | ConversionContractor, ProgramManager |
| GET | `/api/restoration-tasks` | List restoration tasks (filters: `trench_segment_id`, `parcel_id`, `status`) | Any authenticated role |
| GET | `/api/restoration-tasks/{id}` | Get a restoration task (warranty expiry) | Any authenticated role |
| POST | `/api/restoration-tasks/{id}/transition` | Transition task to IN_WORK, COMPLETE, ACCEPTED, or WARRANTY_CLAIM | ConversionContractor, ProgramManager |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock (lazy permit expiry sweep) | ProgramManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_OWNERSHIP_VIOLATION` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_POSTURE_FROZEN` | 409 |
| `ERR_CHANGE_ORDER_FREEZE` | 409 |
| `ERR_MIN_PARTICIPANTS` | 409 |
| `ERR_SHARE_SUM_INVALID` | 422 |
| `ERR_DUPLICATE_SEQUENCE` | 409 |
| `ERR_MIN_COVER_VIOLATION` | 422 |
| `ERR_DEPTH_CAPACITY_EXCEEDED` | 422 |
| `ERR_MIN_SEPARATION_VIOLATION` | 422 |
| `ERR_ELECTRIC_NOT_DEEPEST` | 422 |
| `ERR_SLOT_WINDOW_OUT_OF_RANGE` | 422 |
| `ERR_SLOT_WINDOW_CONFLICT` | 409 |
| `ERR_SLOT_ORDER_VIOLATION` | 409 |
| `ERR_EASEMENT_NOT_RECORDED` | 409 |
| `ERR_EASEMENT_REFUSED_BLOCKING` | 409 |
| `ERR_PERMIT_NOT_ISSUED` | 409 |
| `ERR_PERMIT_WINDOW_VIOLATION` | 409 |
| `ERR_PANEL_CAPACITY_INADEQUATE` | 422 |
| `ERR_SEGMENT_NOT_BACKFILLED` | 409 |
| `ERR_TEMP_SERVICE_REQUIRED` | 409 |
| `ERR_OUTAGE_DURATION_EXCEEDED` | 422 |
| `ERR_CREW_CAPACITY_EXCEEDED` | 409 |
| `ERR_NOTIFICATION_LEAD_TIME` | 409 |
| `ERR_OUTAGE_WINDOW_MISSED` | 409 |
| `ERR_TRUEUP_PREREQUISITES` | 409 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
| `ERR_WARRANTY_EXPIRED` | 409 |
| `ERR_RESTORATION_OPEN_BLOCKING` | 409 |
