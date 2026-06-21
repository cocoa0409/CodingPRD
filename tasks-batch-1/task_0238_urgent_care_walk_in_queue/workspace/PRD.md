# Urgent Care Walk-In Queue API — Product Requirements Document

## 1. Introduction

Urgent care centers live and die by their waiting room. Patients arrive on foot or reserve a slot online, a triage nurse sizes up how sick each person is, the front desk pins down identity and how the visit will be paid for, and a clinician finally rooms the patient, charts the encounter, and sends them home — or, when something turns out to be beyond what a walk-in clinic can safely handle, escalates them to a hospital emergency department. This API models that whole choreography as a single coordinated system so that no patient is lost, no room is double-booked, and no charge slips through the cracks.

The product manages several intertwined concerns at once. It maintains a live **queue** ordered by clinical acuity rather than arrival time, so the sickest patient is always next. It tracks **clinic posture** — whether the center is operating normally, surging, or on diversion and refusing new arrivals — as a function of how deep the queue runs. It supports an **occupational-health** side business (employer-paid drug screens, physicals, and respirator fit-tests booked into collector and room slots). And it carries each visit through two independent storylines — a clinical one from exam through discharge or transfer, and a billing one from open charges through a settled invoice. The sections that follow specify the shared platform rules first, then the business workflows, and finally the concrete HTTP surface and error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request that touches the business surface must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. A request missing either header on an authentication-required endpoint is rejected with `ERR_UNAUTHENTICATED`. The bootstrap and test-driving endpoints — creating a clinic, and the clock and seed helpers described in §3 — are the only operations that may be called without these headers.

The system recognizes six roles, spelled exactly as follows: `ClinicManager`, `FrontDeskClerk`, `TriageNurse`, `Provider`, `Patient`, and `Anonymous`. Even when a caller is authenticated, each operation is gated by role: if the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`. The §4 endpoint table lists the authorized role(s) for every operation, and §3 describes which actor drives each workflow step.

Three of these roles are **opaque operator identities** and three are not, and the distinction matters for how `X-User-ID` is interpreted. When `X-User-Role` is `ClinicManager`, `FrontDeskClerk`, `TriageNurse`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it but never compares it to any entity's `id`. When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider` entity; any ownership check on a resource that references a provider compares that resource's provider foreign key against `X-User-ID`. When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient` entity; ownership checks on a resource that references a patient compare the resource's patient foreign key against `X-User-ID`. `Anonymous` is the unauthenticated bootstrap caller used only for clinic creation and the clock/seed helpers.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, may not be smaller than 1, and may not exceed 100. The `offset` parameter is the number of items to skip and defaults to 0; it may not be negative. A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_VALIDATION_PAGINATION`.

Unless an endpoint states otherwise, all list responses are sorted by the `created_at` timestamp in ascending order. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifiers

Every resource carries a system-generated `id` formatted as a UUID. The `id` is a bare UUID with no type prefix. It also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recorded when the resource is first created.

Most resources additionally carry an `updated_at` timestamp (same ISO 8601 UTC format, refreshed on every mutation) and an integer `version` that begins at its initial value and increments by one on each mutation. In this domain, every entity — `Clinic`, `ExamRoom`, `Provider`, `QueueEntry`, `Patient`, `Coverage`, `Visit`, `Charge`, `OccHealthOrder`, `Referral`, and `DischargeInstruction` — carries the full set of `id`, `created_at`, `updated_at`, and `version`. Whenever the narrative below says a derived or computed field is "recomputed" or "refreshed" on a resource, that counts as a mutation: it refreshes `updated_at` and increments `version` on the mutated resource.

### 2.5. Nested Resource Retrieval and Reference Resolution

Many paths embed more than one identifier — for example, an exam-room action sits under both a clinic and a room. The server validates path identifiers strictly left to right and rejects the first one that does not resolve with `ERR_NOT_FOUND`. A room action under a non-existent clinic therefore fails on the clinic before the room is ever consulted. The same left-to-right discipline governs queue-entry sub-actions (clinic, then queue entry), charge and discharge actions (visit, then the nested resource), and so on.

References that arrive in a request body rather than the path are resolved separately. When a create or action body names a foreign resource — a `clinic_id`, `patient_id`, `visit_id`, `provider_id`, `collector_id`, `queue_entry_id`, `coverage`, `exam_room_id`, or `room_id` — and that reference does not resolve to an existing record, the request is rejected with `ERR_FK_NOT_FOUND`. Both `ERR_NOT_FOUND` and `ERR_FK_NOT_FOUND` carry HTTP 404; the difference is whether the unresolved reference appeared in the path or the body.

### 2.6. Request Validation Ordering

When several checks could fire on the same request, they are evaluated in a fixed priority so that the returned error is deterministic. Authentication comes first: a request missing its headers fails with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else. Role authorization is next, yielding `ERR_FORBIDDEN_ROLE` (HTTP 403) when the role is not permitted. The server then resolves path-referenced resources left to right (`ERR_NOT_FOUND`, HTTP 404), then body foreign keys (`ERR_FK_NOT_FOUND`, HTTP 404). Only then is the request body checked for well-formedness — required fields present, enum values in range, `esi_level` between 1 and 5 inclusive, `amount_cents` greater than 0, `duration_minutes` at least 5 — which on failure returns `ERR_INVALID_REQUEST` (HTTP 400). After the body is known to be well-formed, state-machine legality is checked: if the target resource is not in a state from which the requested transition is defined, the request fails with `ERR_INVALID_STATE` (HTTP 409). Optimistic-concurrency version checks (`ERR_STALE_VERSION`, HTTP 412) are evaluated after state legality. Domain-specific business rules — queue ordering, isolation, capacity, slot conflicts, and the like — are evaluated last, after all of the foregoing have passed.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two. Each requires the client to echo the last `version` it observed of a specific parent entity as a non-optional field in the request body; if that echoed value does not match the parent's current `version`, the write is rejected before any state change, and the client is expected to re-read the parent and retry.

Settling a visit is the first guarded write. A settle request must carry `expected_visit_version` matching the target `Visit`'s current `version`. If a prior settle or a cascaded billing recompute has advanced the visit's `version` since the client last read it, the echoed value is stale and the settle is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a billing state it has not observed.

Rooming a patient is the second guarded write. Creating a visit must carry `expected_clinic_version` matching the target `Clinic`'s current `version`. Because rooming, posture recomputation, and room-state changes all advance the clinic's `version`, a client that read the clinic before one of those events and then tries to room against the room it believed was free is working from a stale view; the create is rejected with `ERR_STALE_VERSION` (HTTP 412) so the client re-reads room availability before retrying. No other endpoint accepts or requires a version field.

### 2.8. Monetary Precision and the Self-Pay Discount

All money in the system is expressed in whole cents as integers — `amount_cents` on a charge, `copay_cents` on a coverage, and the computed `charges_subtotal_cents` and `patient_responsibility_cents` on a visit. There are no fractional cents. Where the self-pay branch of billing produces a fractional result, the discounted amount is rounded to a whole number of cents using the round-half-up convention, and this rounding is applied exactly once, after the discount, never line by line. The self-pay discount itself is a fraction stored on the clinic as `self_pay_discount_pct`, at least 0 and strictly less than 1, defaulting to 0.30 when not supplied at clinic creation. The full billing computation is described in §3.7.

### 2.9. Clinic Posture and Capacity Governance

A clinic continuously reports its operating **posture** — one of `OPEN`, `SURGE`, or `DIVERSION` — in its computed `posture` field, derived from how deep its active queue runs. The `active_queue_depth` is the count of that clinic's queue entries currently in `WAITING`, `TRIAGED`, `IN_REGISTRATION`, or `READY_FOR_PROVIDER`; entries that are merely `RESERVED` (an online hold that has not yet checked in) and entries in any terminal state are not counted. Two integer thresholds on the clinic govern the escalation, both compared inclusively: when the depth is at or above `diversion_threshold` the posture is `DIVERSION`; otherwise, when the depth is at or above `surge_threshold` the posture is `SURGE`; otherwise it is `OPEN`. A depth exactly equal to `surge_threshold` is `SURGE`, and a depth exactly equal to `diversion_threshold` is `DIVERSION`. The `surge_threshold` defaults to 8 and must be at least 1; the `diversion_threshold` defaults to 14 and must be strictly greater than `surge_threshold`. Posture is recomputed on any event that changes the active depth — a queue create, arrival, triage, rooming, leave-without-being-seen, cancellation, or expiry — and on a run-ops sweep.

A clinic also tracks `rooms_occupied`, the count of its exam rooms currently in `OCCUPIED` state, recomputed whenever a room is occupied or released. A clinic is created with a display `name` and an `exam_room_capacity`, an informational ceiling on how many rooms exist physically that must be at least 1; actual `ExamRoom` rows are created explicitly. Finally, the clinic holds a monotone `ops_run_index` epoch counter that begins at 0 and increments on every run-ops sweep.

### 2.10. Cascading Side Effects and Compensation

A single action frequently mutates several resources at once, and every cascade is part of the contract. Rooming a patient does not merely advance one queue entry — it creates a visit, drives the chosen exam room from `AVAILABLE` to `OCCUPIED`, increments the provider's load, decrements the clinic's active queue depth, and recomputes posture and occupancy. Completing charting or transferring a patient releases the room into `CLEANING` and frees a unit of the provider's capacity. Transferring additionally cancels any still-scheduled occupational-health order tied to the same queue entry. These cascades are spelled out where their workflows live in §3; the governing principle here is that the secondary effects are not optional and not best-effort — they are mandatory and immediate.

One workflow is explicitly **compensating**: cancelling a referral undoes the transfer that created it, reverting the source visit from `TRANSFERRED` back to `CHARTING` and clearing its disposition. Compensation is detailed in §3.6.

## 3. Business Logic & Workflows

### 3.1. Arriving at the Clinic: Reservations, Walk-Ins, and the Queue

The journey begins with a **queue entry** under a clinic. There are two ways in, distinguished by `arrival_channel`. A patient using save-my-spot creates an `ONLINE` entry, which is born in `RESERVED` status; a walk-in created at the front desk uses `WALK_IN` and is born directly in `WAITING`. Either way the entry captures a free-text `chief_complaint`. A clinic that is currently on diversion accepts no new arrivals at all: when the clinic's posture is `DIVERSION`, any attempt to create a queue entry of either channel is rejected with `ERR_CLINIC_ON_DIVERSION`.

An `ONLINE` reservation is a time-boxed hold. At creation the server stamps `reserved_at` with the current clock and sets `hold_expires_at` to thirty minutes after `reserved_at`. A `RESERVED` hold does not count toward the clinic's active queue depth and leaves posture untouched until the patient actually arrives. When the patient checks in, the reservation advances `RESERVED → WAITING`: this is allowed only while the entry is still `RESERVED` and the current clock is at or before `hold_expires_at` — at exactly `hold_expires_at` the hold is still valid. Arrival clears `hold_expires_at`, makes the entry count toward `active_queue_depth` for the first time, recomputes posture, and re-ranks the active queue. A walk-in, already `WAITING`, counts toward the depth from the moment it is created and likewise recomputes posture and ranks on creation.

A hold that is never honored expires. On a run-ops sweep, any `RESERVED` entry whose `hold_expires_at` is strictly in the past relative to the current clock is swept `RESERVED → EXPIRED`. Because a `RESERVED` entry was never counted in the active depth, expiry leaves depth and posture unchanged but removes the entry from the active set and re-ranks the remaining active entries. A patient may also voluntarily walk away from the queue at any pre-rooming stage: a leave-without-being-seen action moves an entry in `WAITING`, `TRIAGED`, `IN_REGISTRATION`, or `READY_FOR_PROVIDER` to `LEFT_WITHOUT_SEEN`, decrementing the active depth, recomputing posture, and re-ranking the rest. Cancellation is narrower: it applies only while the entry is `RESERVED` or `WAITING`, moving it to `CANCELLED`; if the prior status was `WAITING` the active depth is decremented and posture recomputed, while a `RESERVED` cancellation leaves depth and posture untouched since the hold was never counted, and in both cases the remaining active entries are re-ranked.

### 3.2. Queue Ordering and Wait Estimates

The queue is not first-come-first-served — it is ordered by clinical urgency. Every active entry (those in `WAITING`, `TRIAGED`, `IN_REGISTRATION`, or `READY_FOR_PROVIDER`; terminal entries are excluded) is assigned a `priority_rank`, a 1-based integer where rank 1 is next to be roomed. The ranking sorts ascending by three keys in order: first by `esi_level` ascending so the most acute patient (ESI 1) sorts ahead — and because an un-triaged `WAITING` entry has no ESI yet, it is treated as if it carried an ESI of 5 for ordering purposes, so it falls behind any triaged entry of better acuity; second, as a tie-break, by the moment of triage, using `triaged_at` ascending for triaged entries and `created_at` ascending for still-un-triaged `WAITING` entries; and third, as the final deterministic tie-break, by `created_at` ascending. The entry's own identifier is never used as a tie-break. The ranking is recomputed on every active-queue mutation — arrival, triage, re-triage, mark-ready, rooming, leave-without-being-seen, cancellation, and expiry.

Alongside the rank, each active entry carries an `estimated_wait_minutes`, the projected minutes until that entry is roomed, recomputed on the same triggers (triage, re-triage, arrive, mark-ready, leave-without-being-seen, cancel, rooming, and run-ops). The estimate is forward-looking. First the server identifies the entries ahead of this one: the active entries with a strictly lower `priority_rank` that are in `TRIAGED`, `IN_REGISTRATION`, or `READY_FOR_PROVIDER`. Un-triaged `WAITING` entries (and `RESERVED` holds) are excluded from this ahead-set because their service time is unknown until an ESI is assigned. The server then determines the number of effective servers — the count of providers under the clinic whose `on_shift` is true; if there are zero effective servers, `estimated_wait_minutes` is null. Otherwise it sums, over the ahead-set, the mean provider minutes for each ahead-entry's ESI level, read from the clinic's `avg_provider_minutes_per_esi` map (which maps ESI 1 through 5 to mean minutes, defaulting to 40, 30, 20, 12, and 8 minutes respectively). That work-ahead total is divided by the number of effective servers and rounded up to the next whole minute. An entry that is itself rank 1, with no one ahead, estimates 0 minutes.

This estimate comes in two variants. The **conservative** variant is the one persisted on an entry once it has been triaged and is the figure shown on the posted board: it divides the work-ahead total by the effective-server count alone, as just described. The **optimistic** variant is surfaced only when fetching a still-`RESERVED` online reservation that has not yet arrived: it assumes one extra fast-track server, dividing the work-ahead total by the effective-server count plus one before rounding up, which yields an estimate at or below the conservative figure for the same queue state whenever there is at least one effective server.

### 3.3. Triage and the Re-Triage Revision Loop

Once a walk-in is `WAITING`, a triage nurse assesses acuity. Triage advances `WAITING → TRIAGED` and is permitted only from `WAITING` with an `esi_level` in the request between 1 and 5 inclusive. Triage records the `esi_level`, sets the `airborne_precaution` flag (used later to force an isolation room at rooming), stamps `triaged_at`, and recomputes both `priority_rank` and `estimated_wait_minutes` across the active queue.

Acuity can change after registration has begun. A re-triage advances `IN_REGISTRATION → TRIAGED`, permitted only from `IN_REGISTRATION` with a new `esi_level` between 1 and 5; it overwrites the existing `esi_level`, re-stamps `triaged_at` to the current clock, and recomputes ranks and wait estimates. This `IN_REGISTRATION → TRIAGED → IN_REGISTRATION` revision cycle is deliberate: a patient whose condition is re-assessed mid-registration loops back through triage and then forward again. Both triage and re-triage accept an optional `airborne_precaution` value alongside the `esi_level`.

### 3.4. Registration, Coverage, and Becoming Ready

After triage, the front desk registers the patient, which links a new `Patient` record to the queue entry and advances `TRIAGED → IN_REGISTRATION`. Registration is permitted only when the queue entry is `TRIAGED`; the body supplies the `queue_entry_id` being registered, the patient's `legal_name`, and `date_of_birth` (an ISO date in YYYY-MM-DD form), and may include `guarantor_name` and a `consent_signed` flag (false by default). Registration sets the queue entry's `patient_id` to the new patient's `id`.

At registration the server computes whether the patient is a minor and records it in `is_minor`. Age in whole years is the floor of the elapsed time between the patient's `date_of_birth` and the current clock date, and the patient is a minor when that age is below the majority age of 18. The boundary is exact: a patient whose eighteenth birthday is precisely the current clock date is **not** a minor (an age of exactly 18 means `is_minor` is false), while one day before that birthday, at age 17, the patient still is a minor. A minor must have a financial guarantor: when `is_minor` is true and no `guarantor_name` is supplied, registration is rejected with `ERR_GUARANTOR_REQUIRED`.

Coverage is attached to the patient as a separate record carrying a `coverage_type` of either `INSURANCE` or `SELF_PAY`. An insurance coverage requires a `payer_name` and a `member_id` and may carry a fixed `copay_cents` (in cents, at least 0, defaulting to 0); a self-pay coverage needs none of these and ignores any copay. Insurance eligibility starts at `UNVERIFIED` and is resolved by a verify action that, for insurance only, moves it `UNVERIFIED → ELIGIBLE` or `UNVERIFIED → INELIGIBLE` according to the supplied `outcome`, stamping `verified_at` in either case. Verification is defined only from `UNVERIFIED` and only for `INSURANCE`; self-pay coverages skip verification entirely and remain `UNVERIFIED`. Attempting to verify a self-pay coverage, or attaching an insurance coverage missing its `payer_name` or `member_id`, is rejected with `ERR_COVERAGE_TYPE_MISMATCH`.

A queue entry becomes roomable when the front desk marks it ready, advancing `IN_REGISTRATION → READY_FOR_PROVIDER` and recomputing ranks and wait estimates. Mark-ready is permitted only from `IN_REGISTRATION`, and only when registration is genuinely complete: there must exist a `Patient` for this queue entry whose `consent_signed` is true, and there must exist a `Coverage` for that patient of any coverage type. If either is missing, mark-ready is rejected with `ERR_REGISTRATION_INCOMPLETE`.

### 3.5. Rooming, Charting, and Discharge — the Clinical Storyline

Rooming is the pivot from waiting to being seen. A provider rooms a `READY_FOR_PROVIDER` entry, which creates a **visit** and advances the queue entry `READY_FOR_PROVIDER → ROOMED`. The rooming request supplies the `queue_entry_id`, the `provider_id` taking the encounter, the `exam_room_id` to occupy, the `expected_clinic_version` for the concurrency check of §2.7, and an optional `override` flag. Several conditions must all hold. The entry must be the one with the lowest `priority_rank` among `READY_FOR_PROVIDER` entries; rooming a non-front entry without `override` set is rejected with `ERR_QUEUE_ORDER_VIOLATION`. The target exam room must be `AVAILABLE`, else `ERR_ROOM_UNAVAILABLE`. If the entry's `airborne_precaution` is true, the target room's `room_type` must be `ISOLATION`, else `ERR_ISOLATION_REQUIRED`. The provider must be on shift with an `active_visit_count` strictly below their `max_concurrent_visits`, else `ERR_PROVIDER_AT_CAPACITY`.

When all checks pass, the new visit is created with `clinical_status` `IN_EXAM` and `billing_status` `OPEN`; the queue entry's `patient_id` is copied onto the visit and its current ESI is snapshotted into the visit's `acuity_at_rooming`. As a cascade, the exam room goes `AVAILABLE → OCCUPIED` and its `current_visit_id` is set to point back at the new visit; the provider's `active_visit_count` is incremented; the clinic's active queue depth is decremented and its posture, `rooms_occupied`, and the ranks and wait estimates of the remaining active entries are all recomputed; and the clinic's `version` is incremented. Because a room carries only a back-pointer to its visit, the room holding a given visit is discovered by listing exam rooms filtered by `current_visit_id`.

A visit's clinical life then proceeds through charting. A provider starts charting, advancing `IN_EXAM → CHARTING` (defined only from `IN_EXAM`), and later completes charting, advancing `CHARTING → PENDING_DISCHARGE`. Completing charting requires a non-empty `chart_note`, supplied with the request, and as a cascade releases the room `OCCUPIED → CLEANING` (clearing the room's `current_visit_id`), decrements the provider's `active_visit_count`, and recomputes the clinic's `rooms_occupied`. From `PENDING_DISCHARGE` the provider discharges the patient home, advancing `PENDING_DISCHARGE → DISCHARGED` and setting `disposition` to `HOME`. A visit's `disposition` is one of `HOME` (discharged home), `ER_TRANSFER` (escalated to an emergency department), or `LWBS` (the patient left without being seen), and is set at the clinical terminal transition. Discharge is gated by two preconditions beyond the state itself: the visit's `billing_status` must already be one of `CHARGES_POSTED`, `INVOICED`, or `SETTLED` — charges must be finalized before discharge, else `ERR_CHARGES_NOT_FINALIZED` — and a `DischargeInstruction` must exist for the visit. The terminal clinical states are `DISCHARGED` and `TRANSFERRED`.

Discharge instructions are authored by the provider on the visit, carrying `instructions_text` and an optional `follow_up_within_days` (a non-negative integer day count, or null for no follow-up). At creation, if `follow_up_within_days` is null the `follow_up_due_at` is null and `follow_up_status` is `NONE`; otherwise `follow_up_due_at` is set to the current clock plus that many days and `follow_up_status` becomes `PENDING`. Follow-up status then advances on run-ops sweeps relative to the clock: a `PENDING` record whose `follow_up_due_at` has been reached (the current clock is at or after it) flips to `DUE`, with the boundary inclusive so that exactly at `follow_up_due_at` the record is `DUE` while one second earlier it is still `PENDING`; and a record left `DUE` until the current clock reaches `follow_up_due_at` plus a grace period of three days flips to `OVERDUE` on a later sweep.

### 3.6. Escalation: Transfer, Referral, and Compensation

Not every walk-in can be finished in the clinic. When a patient needs an emergency department, the provider transfers the visit, which advances `clinical_status` to `TRANSFERRED` and is defined from either `IN_EXAM` or `CHARTING`. The transfer body names the `destination_facility`, a `transfer_reason` of `ACUITY_ESCALATION`, `CAPABILITY_GAP`, or `PATIENT_REQUEST`, and an optional `mode` of `AMBULANCE` or `PRIVATE_VEHICLE` (defaulting to `AMBULANCE`). For an acutely ill patient the transport mode is not negotiable: when the visit's `acuity_at_rooming` is 2 or lower (a more acute ESI), the transfer must use `mode` `AMBULANCE`, and a transfer of such a visit with any other mode is rejected with `ERR_AMBULANCE_REQUIRED`.

A successful transfer creates a **referral** in `INITIATED` status, sets the visit's `disposition` to `ER_TRANSFER`, and cascades the same room-and-provider release as completing charting — the exam room goes `OCCUPIED → CLEANING`, the provider's `active_visit_count` is decremented, and `rooms_occupied` is recomputed. It further cascades to occupational health: any `SCHEDULED` occupational-health order on the same queue entry is cancelled. The referral itself records its `destination_facility`, `transfer_reason`, and `mode`, and a receiving facility may acknowledge it: accepting a referral advances `INITIATED → ACCEPTED` and stamps `accepted_at` with the current clock.

A referral may also be undone, and this is the system's compensating action. Cancelling a referral advances `INITIATED → CANCELLED`, permitted only while the referral is `INITIATED` and only while the source visit's `clinical_status` is still `TRANSFERRED`. The compensation reverts the source visit `TRANSFERRED → CHARTING` and clears its `disposition` back to null; the room is not automatically re-acquired, so a clinic-manager who cancels a transfer leaves the provider to re-room the patient. The referral's terminal states are `ACCEPTED` and `CANCELLED`.

### 3.7. Charges and the Billing Storyline

A visit's billing dimension runs in parallel with its clinical one and evolves independently. Charges are added to a visit as individual lines while billing is `OPEN`, each carrying a `cpt_code` label, a positive `amount_cents`, and a `source_type` of `VISIT` (the default) or `OCC_HEALTH`. A charge may be voided while billing is still open, which sets its `voided` flag to true and excludes it from the subtotal thereafter.

Posting charges advances the billing dimension `OPEN → CHARGES_POSTED`, permitted only from `OPEN` and only when at least one non-voided charge exists on the visit. Posting computes two figures. The `charges_subtotal_cents` is the sum of `amount_cents` over the visit's charges where `voided` is false **and** `source_type` is `VISIT`; occupational-health charges are employer-billed and are excluded from patient responsibility. The order is pinned: the subtotal is computed first, then the coverage rule is applied, and rounding happens once at the very end rather than per line. The `patient_responsibility_cents` then depends on the patient's single coverage, and this is the system's dual-variant calculation. Under verified insurance — the coverage is `INSURANCE` with `eligibility_status` `ELIGIBLE` — the patient owes a flat `copay_cents`, independent of the subtotal, because the payer covers the balance. In every other case — a `SELF_PAY` coverage, or an `INSURANCE` coverage whose `eligibility_status` is still `UNVERIFIED` or is `INELIGIBLE`, both of which fall back to self-pay — the patient owes the subtotal reduced by the clinic's self-pay discount: the subtotal multiplied by one minus `self_pay_discount_pct`, rounded half-up to whole cents. The same set of charge lines thus yields a flat copay under verified insurance but a discount-scaled amount under self-pay.

The billing dimension continues independently of the clinical one. Invoicing advances `CHARGES_POSTED → INVOICED` and freezes the patient responsibility: once invoiced, no further charges may be posted. An attempt to post charges after billing has advanced past `CHARGES_POSTED` — that is, while `INVOICED` or `SETTLED` — is rejected with `ERR_BILLING_FROZEN`. Settling advances `INVOICED → SETTLED`; it is the concurrency-guarded write of §2.7, requiring `expected_visit_version` to match the visit's current `version` (mismatch yields `ERR_STALE_VERSION`), and on success it increments the visit's `version` by one.

### 3.8. Occupational Health: Slots, Buffers, and Results

Alongside its walk-in queue, the clinic runs an employer-billed occupational-health line. An occupational-health order is booked against a queue entry and carries an `order_type` of `DRUG_SCREEN`, `PHYSICAL`, or `RESPIRATOR_FIT`, the sponsoring `employer_name`, a `scheduled_start` (an ISO 8601 UTC instant), a `duration_minutes` slot length (at least 5, defaulting to 30), and a `collector_id` naming the provider running the order. A room is required for some order types and forbidden for others: a `PHYSICAL` or `RESPIRATOR_FIT` order must supply a `room_id`, while a `DRUG_SCREEN` must omit it; violating this rule is rejected with `ERR_OCC_ROOM_REQUIRED`.

Booking respects two distinct slot-conflict rules. On the collector, an order occupies the **half-open** interval from its `scheduled_start` up to but not including `scheduled_start` plus `duration_minutes`. A new order for a collector is rejected with `ERR_SLOT_CONFLICT` if its interval overlaps any existing `SCHEDULED` or `IN_PROGRESS` order on that same collector, where overlap means the new start falls before the existing end and the existing start falls before the new end. Because the interval is half-open, two back-to-back orders where the new order's start equals the existing order's end do **not** overlap and are allowed — a zero gap is permitted on the collector. The room rule is deliberately stricter. A room-bound order occupies its room for a **closed** window padded by a fifteen-minute cleaning buffer on each side: a new room-bound order is rejected with `ERR_ROOM_SLOT_CONFLICT` if the new start falls before the existing end plus fifteen minutes **and** the existing start falls before the new end plus fifteen minutes, checked against existing `SCHEDULED` or `IN_PROGRESS` room-bound orders on the same room. Two room orders are therefore only allowed when separated by at least the fifteen-minute buffer; unlike the collector, back-to-back room bookings are rejected because the buffer is mandatory.

An order moves through its own lifecycle. Starting an order advances `SCHEDULED → IN_PROGRESS`, permitted only from `SCHEDULED` and only when the current clock is at or after the `scheduled_start`. Recording a result advances `IN_PROGRESS → COMPLETED`, permitted only from `IN_PROGRESS` with a `result` of `NEGATIVE`, `POSITIVE`, `PASS`, or `FAIL`; it sets that `result` and, if a visit exists for the same queue entry, cascades by creating an `OCC_HEALTH`-source charge on that visit (employer-billed, and thus excluded from the patient's responsibility). An order may be cancelled from `SCHEDULED` or `IN_PROGRESS`, moving it to `CANCELLED` and freeing the half-open collector slot and, when a `room_id` was set, the room slot; this is also the cascade target when a visit transfer cancels a still-scheduled order on the same queue entry. An order's terminal states are `COMPLETED` and `CANCELLED`, and its `result` and `status` both begin at their defaults (`PENDING` and `SCHEDULED`).

### 3.9. Exam-Room Operations and the Ops Epoch

Exam rooms and providers are provisioned and tended by the clinic manager. A provider is rostered under a clinic with a `full_name`, a `credential` of `MD`, `DO`, `NP`, or `PA`, an `on_shift` flag (true by default, and only on-shift providers count toward throughput), and a `max_concurrent_visits` cap on simultaneous `IN_EXAM` or `CHARTING` visits (at least 1, defaulting to 2). The provider's `active_visit_count`, the count of visits assigned to them in `IN_EXAM` or `CHARTING`, is a computed field. A new room carries a `room_label` and a `room_type` of `STANDARD` (the default), `ISOLATION`, or `PROCEDURE`, with `ISOLATION` rooms reserved for airborne-precaution visits. A room's `status` lifecycle is `AVAILABLE`, `OCCUPIED`, `CLEANING`, and `OUT_OF_SERVICE`. Rooming drives a room `AVAILABLE → OCCUPIED` (setting `current_visit_id`) and releasing a visit drives it `OCCUPIED → CLEANING` (clearing `current_visit_id`), both as cascades described above. The manager closes the loop by marking a `CLEANING` room clean, advancing `CLEANING → AVAILABLE` and recomputing the clinic's `rooms_occupied`. A manager may also take an `AVAILABLE` room offline, advancing `AVAILABLE → OUT_OF_SERVICE`, and later return it, advancing `OUT_OF_SERVICE → AVAILABLE`; each of these is defined only from the stated source state.

Periodically the clinic manager advances the operational epoch with a run-ops sweep. A sweep increments the clinic's `ops_run_index`, expires every `RESERVED` queue entry whose hold has lapsed (those whose `hold_expires_at` is strictly in the past), advances every discharge instruction's `follow_up_status` against the clock as described in §3.5, and recomputes the clinic's `active_queue_depth`, `posture`, and `rooms_occupied`.

The system also exposes test-driving capabilities outside the business surface. A clock capability sets the server's current UTC clock to a supplied `to_iso8601` instant, and all current-clock reads use that value until it is next set. A seed capability bulk-creates a given `count` of `WALK_IN` queue entries in `WAITING` under a named `clinic_id`, recomputing that clinic's `active_queue_depth` and `posture`, so that a target queue depth can be reached without hand-rolling each entry. Both helpers, along with clinic creation, are reachable without authentication.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or perform a state transition on it return `200 OK`. The request and response payloads for each operation are described in the §3 narratives, not in this table; the table lists only the method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clinics` | Create a clinic (bootstrap, no auth) | ClinicManager, Anonymous |
| GET | `/clinics/{id}` | Fetch a clinic with computed posture and depth | ClinicManager, FrontDeskClerk, TriageNurse, Provider, Patient |
| GET | `/clinics` | List clinics | ClinicManager, FrontDeskClerk, TriageNurse, Provider, Patient |
| POST | `/clinics/{id}/run-ops` | Advance the ops epoch: expire holds, advance follow-ups, recompute posture | ClinicManager |
| POST | `/clinics/{id}/exam-rooms` | Provision an exam room | ClinicManager |
| GET | `/clinics/{id}/exam-rooms` | List exam rooms under a clinic | ClinicManager, FrontDeskClerk, TriageNurse, Provider |
| GET | `/exam-rooms/{id}` | Fetch an exam room | ClinicManager, FrontDeskClerk, TriageNurse, Provider |
| GET | `/exam-rooms` | List exam rooms across clinics; filter by current_visit_id or status | ClinicManager, FrontDeskClerk, TriageNurse, Provider |
| POST | `/clinics/{id}/exam-rooms/{rid}/mark-clean` | Mark a cleaning room available | ClinicManager |
| POST | `/clinics/{id}/exam-rooms/{rid}/take-offline` | Take an available room out of service | ClinicManager |
| POST | `/clinics/{id}/exam-rooms/{rid}/return-online` | Return an out-of-service room | ClinicManager |
| POST | `/clinics/{id}/providers` | Roster a provider | ClinicManager |
| GET | `/clinics/{id}/providers` | List providers under a clinic; filter by on_shift | ClinicManager, FrontDeskClerk, TriageNurse, Provider |
| GET | `/providers/{id}` | Fetch a provider | ClinicManager, FrontDeskClerk, TriageNurse, Provider |
| POST | `/clinics/{id}/queue-entries` | Create a walk-in or save-my-spot reservation | FrontDeskClerk, Patient |
| GET | `/clinics/{id}/queue-entries` | List queue entries under a clinic; filter by status | ClinicManager, FrontDeskClerk, TriageNurse, Provider, Patient |
| GET | `/queue-entries/{id}` | Fetch a queue entry with rank and wait estimate | ClinicManager, FrontDeskClerk, TriageNurse, Provider, Patient |
| GET | `/queue-entries` | List queue entries across clinics; filter by patient_id or status | ClinicManager, FrontDeskClerk, TriageNurse, Provider, Patient |
| POST | `/clinics/{id}/queue-entries/{qid}/arrive` | Check in a save-my-spot hold | FrontDeskClerk, Patient |
| POST | `/clinics/{id}/queue-entries/{qid}/triage` | Assign ESI to a waiting entry | TriageNurse |
| POST | `/clinics/{id}/queue-entries/{qid}/re-triage` | Revise ESI during registration | TriageNurse |
| POST | `/clinics/{id}/queue-entries/{qid}/mark-ready` | Mark registration complete | FrontDeskClerk |
| POST | `/clinics/{id}/queue-entries/{qid}/lwbs` | Record a leave-without-being-seen | FrontDeskClerk |
| POST | `/clinics/{id}/queue-entries/{qid}/cancel` | Cancel a reserved or waiting entry | FrontDeskClerk, Patient |
| POST | `/patients` | Register a patient against a triaged entry | FrontDeskClerk |
| GET | `/patients/{id}` | Fetch a patient | ClinicManager, FrontDeskClerk, TriageNurse, Provider |
| GET | `/patients` | List patients; filter by queue_entry_id | ClinicManager, FrontDeskClerk, TriageNurse, Provider |
| POST | `/coverages` | Attach insurance or self-pay coverage | FrontDeskClerk |
| GET | `/coverages` | List coverages; filter by patient_id | ClinicManager, FrontDeskClerk, Provider |
| GET | `/coverages/{id}` | Fetch a coverage | ClinicManager, FrontDeskClerk, Provider |
| POST | `/coverages/{id}/verify` | Verify insurance eligibility | FrontDeskClerk |
| POST | `/visits` | Room a ready entry: create a visit, occupy a room | Provider |
| GET | `/visits/{id}` | Fetch a visit with computed totals | ClinicManager, FrontDeskClerk, Provider |
| GET | `/visits` | List visits; filter by queue_entry_id, provider_id, exam_room_id, patient_id | ClinicManager, FrontDeskClerk, Provider |
| POST | `/visits/{id}/start-charting` | Begin charting | Provider |
| POST | `/visits/{id}/complete-charting` | Finish charting and release the room | Provider |
| POST | `/visits/{id}/discharge` | Discharge the patient home | Provider |
| POST | `/visits/{id}/transfer` | Transfer to an ER; create a referral | Provider |
| POST | `/visits/{id}/post-charges` | Post charges and compute responsibility | Provider |
| POST | `/visits/{id}/invoice` | Invoice and freeze responsibility | FrontDeskClerk |
| POST | `/visits/{id}/settle` | Settle an invoiced visit (OCC-guarded) | FrontDeskClerk |
| POST | `/visits/{id}/charges` | Add a charge line | Provider |
| GET | `/visits/{id}/charges` | List charges on a visit | ClinicManager, FrontDeskClerk, Provider |
| POST | `/charges/{id}/void` | Void a charge | Provider |
| POST | `/occ-health-orders` | Book an occupational-health order | FrontDeskClerk, ClinicManager |
| GET | `/occ-health-orders` | List occ-health orders; filter by queue_entry_id, collector_id, room_id | ClinicManager, FrontDeskClerk, Provider |
| GET | `/occ-health-orders/{id}` | Fetch an occ-health order | ClinicManager, FrontDeskClerk, Provider |
| POST | `/occ-health-orders/{id}/start` | Start an order | Provider |
| POST | `/occ-health-orders/{id}/result` | Record a result and complete | Provider |
| POST | `/occ-health-orders/{id}/cancel` | Cancel an order and free the slot | FrontDeskClerk, ClinicManager, Provider |
| GET | `/visits/{id}/referrals` | List referrals for a visit | ClinicManager, FrontDeskClerk, Provider |
| GET | `/referrals/{id}` | Fetch a referral | ClinicManager, FrontDeskClerk, Provider |
| POST | `/referrals/{id}/accept` | Accept a referral | ClinicManager |
| POST | `/referrals/{id}/cancel` | Cancel a referral and compensate the visit | ClinicManager |
| POST | `/visits/{id}/discharge-instructions` | Attach discharge instructions and follow-up | Provider |
| GET | `/visits/{id}/discharge-instructions` | List discharge instructions for a visit | ClinicManager, FrontDeskClerk, Provider, Patient |
| GET | `/discharge-instructions/{id}` | Fetch a discharge instruction | ClinicManager, FrontDeskClerk, Provider, Patient |
| POST | `/_clock/set` | Set the server clock (test-driving) | ClinicManager, Anonymous |
| POST | `/_seed/queue-depth` | Bulk-seed waiting entries (test-driving) | ClinicManager, Anonymous |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_QUEUE_ORDER_VIOLATION` | 409 |
| `ERR_ISOLATION_REQUIRED` | 409 |
| `ERR_CLINIC_ON_DIVERSION` | 409 |
| `ERR_ROOM_UNAVAILABLE` | 409 |
| `ERR_PROVIDER_AT_CAPACITY` | 409 |
| `ERR_SLOT_CONFLICT` | 409 |
| `ERR_ROOM_SLOT_CONFLICT` | 409 |
| `ERR_OCC_ROOM_REQUIRED` | 422 |
| `ERR_REGISTRATION_INCOMPLETE` | 409 |
| `ERR_GUARANTOR_REQUIRED` | 422 |
| `ERR_AMBULANCE_REQUIRED` | 409 |
| `ERR_CHARGES_NOT_FINALIZED` | 409 |
| `ERR_BILLING_FROZEN` | 409 |
| `ERR_COVERAGE_TYPE_MISMATCH` | 422 |
| `ERR_VALIDATION_PAGINATION` | 400 |
