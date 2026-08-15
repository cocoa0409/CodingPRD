# Investigational Drug Randomization API — Product Requirements Document

## 1. Introduction

Clinical trial supply is one of the most heavily audited operations in pharmaceutical research. Every milligram of investigational product must be accounted for from the moment a shipment leaves the sponsor to the moment the unused remainder is witnessed into destruction, and the randomization scheme that separates treatment arms must remain sealed against exactly the people who handle the drug every day. This document specifies the Investigational Drug Randomization API, the system of record for a research pharmacy's investigational drug service: it governs study and site onboarding, drug-lot registration and kit logistics, continuous temperature surveillance with excursion adjudication, slot-driven randomization under a blinding model, per-visit dispensing and returns, emergency unblinding under a three-person rule, monitor-visit reconciliation, and sponsor invoicing for pharmacy services.

Two design commitments shape every workflow that follows. First, accountability is a ledger, not a recollection: kit balances are projections of recorded events — receipts, dispensings, returns, destructions, and monitor-counted adjustments — and the system derives its numbers from those events rather than from free-text attestations. Second, time is explicit: every expiry check, visit window, and business timestamp reads from a single server-maintained logical clock that test harnesses can advance deterministically, so trial timelines can be replayed and audited without depending on wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply to every resource and every request. All resources are mounted under the `/api` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` to identify the acting user and `X-User-Role` to declare their operational capacity. The system recognizes exactly five roles: `SponsorAdmin`, `Pharmacist`, `UnblindedPharmacist`, `Monitor`, and `Investigator`. A request that is missing either header, or whose declared role is not one of these five, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among an endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Role identity works in two different ways, and the distinction matters wherever a resource records who performed a step:

- When `X-User-Role` is `Pharmacist`, `X-User-ID` is the `id` of the acting `PharmacyStaff` record, and that staff record's `is_unblinded` flag must be `false`. Ownership and segregation checks on any resource that references a staff member — for example the `recorded_by_staff_id` captured on a drug return — compare the resource's staff field to `X-User-ID`.
- When `X-User-Role` is `UnblindedPharmacist`, `X-User-ID` is likewise the `id` of an acting `PharmacyStaff` record, but that record's `is_unblinded` flag must be `true`. An `X-User-ID` that does not resolve to an existing staff record, or whose `is_unblinded` flag does not match the declared role, is rejected with `ERR_UNAUTHENTICATED`.
- When `X-User-Role` is `SponsorAdmin`, `Monitor`, or `Investigator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, an unblinding request captures the caller as `requested_by_user_id` — but it does not compare the value to any entity's `id`.

In broad strokes, a `SponsorAdmin` administers studies, sites, staff, lots, shipments, randomization lists, fee schedules, excursion assessments, invoices, and the operational clock; a `Pharmacist` runs the site-level drug service — receipt, release, temperature logging, subject enrollment, randomization, dispensing, returns, and destruction; an `UnblindedPharmacist` exists solely to decide and execute emergency unblinding; a `Monitor` conducts reconciliation visits; and an `Investigator` requests emergency unblinding.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the beginning of the result set and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order, with ties broken by `id` ascending. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, unique across all resources.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that begins at 1 on creation and increments by one on every mutation of the resource, including mutations performed by system cascades rather than by direct client writes.

One deliberate exception exists: a temperature log entry is an immutable observation and carries only `id` and `created_at`. Both `updated_at` and `version` are absent from temperature log resources; the moment of observation is instead recorded in the server-stamped `recorded_at` field, which is never client-supplied.

### 2.5. The Logical Clock

All time-dependent behavior in the system — lot and kit expiry, dispensing visit windows, monitor-visit windows, invoice periods, and the business timestamps stamped onto records — reads from a single server-maintained logical clock. The clock never falls back to wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`.

A `SponsorAdmin`-only test-driving capability advances the clock: the caller supplies a `to_iso8601` instant and the response reports the resulting `current_utc`; the clock accepts any supplied instant, forward or backward, with no monotonicity check. Advancing the clock is what makes expiry sweeps, visit-window eligibility, and invoice periods observable in tests. The timestamps `recorded_at`, `dispensed_at`, `activated_at`, `randomized_at`, `started_at`, and `closed_at` are all stamped from this clock at the moment the corresponding event occurs, and the bookkeeping fields `created_at` and `updated_at` (§2.4) are likewise stamped from this clock. A lot is considered expired when the current logical clock has reached or passed the lot's `expiry_date`.

### 2.6. Validation Order and Nested Resource Retrieval

When several checks could reject the same request, the server evaluates them in a fixed priority order, and the earliest failing check is the one whose error is returned — later checks are masked by it:

1. Authentication of `X-User-ID` and `X-User-Role` (`ERR_UNAUTHENTICATED`).
2. Role authorization for the endpoint (`ERR_UNAUTHORIZED_ROLE`).
3. Request-schema conformance: required fields present, types correct, enum values within their declared sets, datetime strings parseable, and window fields satisfying a start strictly before their end (`ERR_INVALID_REQUEST`).
4. Existence of referenced resources. Path identifiers and body foreign-key references are validated left to right; the first unresolvable reference fails the request. Study, site, kit, and subject references yield `ERR_STUDY_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_KIT_NOT_FOUND`, and `ERR_SUBJECT_NOT_FOUND` respectively; any other referenced entity — a lot, staff member, dispensing record, return, excursion, monitor visit, fee schedule, or randomization slot — yields `ERR_NOT_FOUND`.
5. State admissibility: the target entity must be in a state that permits the requested transition or action. Domain-specific state errors — `ERR_STUDY_NOT_ACTIVE`, `ERR_SITE_NOT_ACTIVE`, `ERR_KIT_NOT_RELEASABLE`, `ERR_KIT_NOT_DISPENSABLE`, `ERR_SUBJECT_NOT_RANDOMIZABLE`, `ERR_SUBJECT_NOT_RANDOMIZED`, `ERR_ALREADY_TERMINAL`, and `ERR_EXCURSION_ALREADY_RESOLVED` — are used where they apply, and the generic `ERR_INVALID_STATE` covers every other state-precondition failure. Acting on an entity that has already reached a terminal state — a `DESTROYED` kit, a `CLOSED` study or site, a `COMPLETED` or `WITHDRAWN` subject, a `FINALIZED` or `VOIDED` destruction record, a closed monitor visit, an `EXECUTED` or `REJECTED` unblinding request, or a `VERIFIED` return — is rejected with `ERR_ALREADY_TERMINAL`.
6. Optimistic-concurrency version checks (`ERR_STALE_VERSION`; see §2.7).
7. Pharmaceutical safety gates — dose cap, lot expiry, excursion quarantine, stability budget, and open-label unblinding — detailed in §3.
8. Temporal gates — the dispensing visit-sequence rule (evaluated immediately before the visit-window check), dispensing visit windows, monitor-visit windows and overlaps, and destruction-facility window conflicts — detailed in §3.
9. Uniqueness and capacity constraints — duplicate identifiers, rescreen caps, and slot availability — detailed in §3.
10. Referential integrity and segregation-of-duties rules (`ERR_SEGREGATION_OF_DUTIES`, `ERR_QUANTITY_MISMATCH`, and related codes), detailed in §3.
11. Fiscal gates — the presence of an approved fee schedule where one is required (`ERR_NO_APPROVED_FEE_SCHEDULE`).

### 2.7. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, and both guard the version of the owning study:

- `POST /api/fee-schedules/{id}/approve` requires the request to carry `expected_study_version` holding the client's last-observed `version` of the study. Approving a fee schedule supersedes the study's currently approved schedule — a legitimate create-with-supersede — so if the study's version has advanced since the client last read it (for example because another schedule was approved or the study transitioned), the approval is rejected with `ERR_STALE_VERSION` (HTTP 412).
- `POST /api/studies/{id}/randomization-slots/replace` likewise requires `expected_study_version`. Replacing a study's randomization list retires every unassigned slot and installs a new list — a legitimate supersede of the prior list — and the same rule applies: a value that no longer matches the study's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field; all other writes proceed without an optimistic-concurrency check.

### 2.8. Blinding, Arm-Code Masking, and Segregation of Duties

Blinding is enforced at the response layer. A randomization slot's `arm_code` — the masked treatment-arm code, for example TRT-A — is visible only in responses to `SponsorAdmin` and `UnblindedPharmacist` callers; for `Pharmacist`, `Monitor`, and `Investigator` callers the field is serialized as `null`. The same masking applies to an unblinding request's `revealed_arm_code` once it has been populated.

Segregation of duties is enforced at the action layer. Four workflows require that two segregated steps be performed by different actors: the pharmacist who records a drug return may not verify it; the pharmacist who creates a destruction record may not attest it; the investigator who requests an unblinding may not decide it; and the pharmacist who decides an unblinding may not execute it. Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). Separately, attesting a destruction when the caller is not the designated witness, or voiding a destruction draft when the caller is not its creator, is a role-level failure rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

### 2.9. Units, Monetary Values, and Rounding

Monetary amounts are integers denominated in cents; fee-schedule pricing fields and every invoice figure follow this convention. Wherever a calculation must round a monetary value, it rounds half-up to a whole cent. Two rounding points are pinned: per-visit monitoring fees are rounded half-up individually before they are summed into the monitoring line, and overhead is computed once on the already-rounded line subtotal and rounded half-up a single time. Physical unit counts — kits received, dispensed, returned, destroyed, or lost — are integers, and the accountability arithmetic over them is exact with no rounding. Temperature readings and storage bounds are numeric degrees Celsius and may carry fractional values.

### 2.10. The Kit Accountability Ledger

Every kit maintains a set of counters from which its book on-hand balance is always derived. `units_received` is fixed when the kit is shipped; `units_dispensed`, `units_returned`, `units_destroyed`, and `units_lost` each begin at zero and accumulate over the kit's life. The book balance is:

`on_hand_units` equals `units_received`, minus `units_dispensed`, plus `units_returned`, minus `units_destroyed`, minus `units_lost`.

These counters mutate only through four events: recording a dispensing, recording a return, finalizing a destruction, and closing a monitor visit. The ledger has a conservation invariant worth relying on: dispensing some quantity and later returning the same quantity leaves the book balance unchanged, because the increment to `units_dispensed` and the equal increment to `units_returned` cancel exactly.

The balance has two reading variants. Outside any monitor visit, `on_hand_units` is a pure projection of the kit's counters — a replay of its dispensing, return, destruction, and loss events. At a monitor-visit close, the monitor's physical count replaces the projection: the signed delta between the book balance and the physical count is booked into `units_lost`, so that after the close the two variants agree. Whenever a genuine discrepancy exists, the two variants report different on-hand numbers for identical counter data — that difference is precisely what the monitor visit exists to capture.

### 2.11. Temperature Integrity and the Stability Budget

Every drug lot declares an inclusive storage-temperature range bounded by `storage_temp_min_celsius` and `storage_temp_max_celsius`; a reading exactly equal to either bound is in range. Each lot also carries a `stability_budget_minutes` allowance: a cumulative severity budget that temperature excursions consume. The lot's `stability_minutes_consumed` starts at zero, increases when an excursion assessment charges severity minutes to the lot, and decreases only if an acceptable assessment is later voided. A lot is stability-exhausted once its `stability_minutes_consumed` reaches or exceeds its `stability_budget_minutes`, and exhaustion permanently bars release of its receipt-quarantined kits and restoration of its excursion-quarantined kits. When an excursion is assessed, the server snapshots a reference range onto the excursion itself: `reference_temp_min_celsius` holds the smallest lower storage bound among the affected kits' lots, and `reference_temp_max_celsius` holds the largest upper bound. If no kit is linked to the excursion at assessment time, the snapshot instead falls back to the excursion's own observed extremes — `reference_temp_min_celsius` takes `min_observed_celsius` and `reference_temp_max_celsius` takes `max_observed_celsius` — which yields a severity of zero. All severity mathematics (§3.4) runs against that snapshot.

## 3. Business Logic & Workflows

### 3.1. Study Onboarding and Protocol Activation

A `SponsorAdmin` onboards a trial by creating a study with its sponsor `protocol_number`, a human-readable `title`, the trial `phase` (one of `PHASE_I`, `PHASE_II`, `PHASE_III`, `PHASE_IV`), and the `blinding_model` (`DOUBLE_BLIND`, `SINGLE_BLIND`, or `OPEN_LABEL`). The protocol number is unique across all studies; creating a study with an already-registered `protocol_number` is rejected with `ERR_DUPLICATE_PROTOCOL_NUMBER` (HTTP 409). Two safety parameters complete the record: `max_dose_per_visit_mg`, the protocol's maximum total dose for a single dispensing visit, and `unblinding_suspension_threshold_pct`, the blinding-integrity threshold that defaults to 10 when omitted. A new study begins in `DRAFT` status with `version` 1, and its two integrity counters — `randomized_subject_count` and `unblinded_subject_count` — start at zero. Studies may be listed with an optional `status` filter.

Before a study can enroll anyone, it needs money. A `SponsorAdmin` creates a fee schedule for the study carrying eight pricing fields: `setup_fee_cents`, `dispensing_fee_cents`, `dispensing_tier_threshold`, `dispensing_tier_fee_cents`, `monitoring_fee_cents_per_hour`, `storage_fee_cents_per_kit_month`, `unblinding_fee_cents`, and `overhead_pct`, alongside the `study_id` it prices. A fee schedule starts in `DRAFT`. Approving one is an OCC-guarded operation: the caller presents `expected_study_version`, and if that value no longer matches the study's current `version` the approval is rejected with `ERR_STALE_VERSION` rather than silently superseding a schedule the caller never saw. A successful approval moves the schedule from `DRAFT` to `APPROVED`, pushes any other `APPROVED` schedule of the same study into `SUPERSEDED`, and increments both the fee schedule's `version` and the study's `version`. Only a `DRAFT` schedule can be approved; `SUPERSEDED` is terminal. Fee schedules may be listed with `study_id` and `status` filters.

A study's lifecycle begins in `DRAFT`, moves to `ACTIVE` once the trial is provisioned, may fall back from `ACTIVE` to `SUSPENDED` and be resumed from `SUSPENDED` to `ACTIVE`, and ends in `CLOSED`, reachable from either `ACTIVE` or `SUSPENDED`. Transitioning a study from `DRAFT` to `ACTIVE` — and likewise resuming it from `SUSPENDED` to `ACTIVE` — requires at least one fee schedule of the study to be in `APPROVED` status; without one the transition is rejected with `ERR_NO_APPROVED_FEE_SCHEDULE`. An `ACTIVE` study may be suspended manually by a `SponsorAdmin`, and it may also suspend itself automatically under the blinding-integrity rule of §3.8; either path moves it `ACTIVE` → `SUSPENDED` and cascades every `ACTIVE` site of the study to `ON_HOLD`. Resumption is deliberately asymmetric: when a study returns from `SUSPENDED` to `ACTIVE`, its sites are not reactivated automatically — each `ON_HOLD` site is resumed individually. Both `ACTIVE` → `CLOSED` and `SUSPENDED` → `CLOSED` are available to close out a trial, and `CLOSED` is terminal. Transition requests for a study or a site carry the target state in a `to` field. Every study transition increments the study's `version`.

### 3.2. Sites, Staff, and Investigational Product Supply

Within a study, a `SponsorAdmin` registers each participating site with its `study_id`, a `site_number` unique within that study, a display `name`, and the `principal_investigator`'s full name. A second site created with a `site_number` already used inside the same study is rejected with `ERR_INVALID_REQUEST`. A site begins `INITIATED`. Its first activation — `INITIATED` → `ACTIVE` — requires the owning study to be `ACTIVE` (otherwise `ERR_STUDY_NOT_ACTIVE`) and stamps `activated_at` from the logical clock; that stamp is written on the first activation only, and later `ON_HOLD` → `ACTIVE` resumes never overwrite it. Resuming a held site likewise requires the study to be `ACTIVE`. A site may move between `ACTIVE` and `ON_HOLD` — including the automatic hold that a study suspension cascades down — and may be closed from either `ACTIVE` or `ON_HOLD` to the terminal `CLOSED`. Sites may be listed with optional `study_id` and `status` filters.

The pharmacy workforce is registered by a `SponsorAdmin` as staff records carrying `site_id`, `full_name`, a `license_number` unique across all staff, and an optional `is_unblinded` flag that defaults to `false` — blinded — unless explicitly set. A duplicate `license_number` is rejected with `ERR_INVALID_REQUEST`. The staff list supports `site_id` and `is_unblinded` filters; the `is_unblinded` filter accepts the strings `true` and `false` (case-insensitive), and any other value is rejected with `ERR_INVALID_REQUEST`. These records are the identity anchor for the two pharmacist roles (§2.1) and for the segregation-of-duties checks (§2.8).

Drug supply begins with lot registration. A `SponsorAdmin` registers each lot against its `study_id` with the manufacturer `lot_number` (unique within the study — a duplicate `lot_number` inside the same study is rejected with `ERR_INVALID_REQUEST`), the investigational `product_name`, the per-unit `strength_mg`, the `dosage_form` (for example VIAL or TABLET), the `expiry_date`, the inclusive storage bounds `storage_temp_min_celsius` and `storage_temp_max_celsius`, and the `stability_budget_minutes` allowance. A lot starts `ACTIVE` with `stability_minutes_consumed` at zero; lots may be listed by `study_id` and `status`.

Stock reaches sites through shipments. A `SponsorAdmin` submits a shipment naming a `lot_id`, a destination `site_id`, a non-empty list of `kit_numbers`, and the `units_per_kit` packed into each kit. The server creates one kit per entry of `kit_numbers`, each beginning in `IN_TRANSIT` at the destination site with `units_received` set to `units_per_kit`, and the response array preserves the order in which the kit numbers appeared in the request payload. Kit numbers are unique within a study: if any entry of `kit_numbers` duplicates an existing kit number in that study — or duplicates another entry within the same payload — the entire shipment is rejected with `ERR_DUPLICATE_KIT_NUMBER` and no kits are created. Kits may be listed with `lot_id`, `site_id`, `status`, `allocated_subject_id`, and `excursion_id` filters.

Two system-driven lot transitions keep supply healthy. First, the server recomputes the lot's usable count — the number of its kits still in the usable states `QUARANTINED_RECEIPT`, `AVAILABLE`, `QUARANTINED_EXCURSION`, or `ALLOCATED` — when an excursion is assessed `ACCEPTABLE` or `UNACCEPTABLE` (§3.4) and when a destruction record is finalized (§3.7). When such a recompute finds a lot with zero usable kits, the lot flips from `ACTIVE` to `DEPLETED`. A depletion found by an `UNACCEPTABLE` excursion assessment additionally triggers the automatic resupply — if the lot's study is `ACTIVE` and the affected site is `ACTIVE`, the server automatically creates replacement kits in `IN_TRANSIT` for that lot at that site, each beginning with `units_received` of zero (so its book balance starts at zero), equal in count to the number of kits that just left usable states in the triggering mutation, numbered `RS-` followed by the `lot_number`, a dash, and a 1-based running sequence number counting every resupply kit ever created for the lot — while a depletion found at destruction finalization creates no resupply kits. Second, an ops checkpoint — the sponsor-invoked expiry sweep — advances expiry in three phases: every kit in `QUARANTINED_RECEIPT`, `AVAILABLE`, `QUARANTINED_EXCURSION`, or `ALLOCATED` whose lot's `expiry_date` has been reached by the logical clock moves to `EXPIRED`; then each lot whose `expiry_date` has been reached transitions from `ACTIVE` to `EXPIRED`, while a `DEPLETED` lot past expiry transitions to `CLOSED`; and finally any lot left with zero usable kits receives the same automatic resupply, this time sized to the number of that lot's kits at the site expired by the sweep and continuing the lot's `RS-` sequence. The sweep's response reports `kits_expired`, `lots_expired` (counting only lots that moved `ACTIVE` → `EXPIRED`; a `DEPLETED` lot closing does not count), and `resupply_kits_created`.

### 3.3. Kit Receipt, Quarantine, and Release

When a shipment arrives, a `Pharmacist` receives each `IN_TRANSIT` kit, declaring the shipment's `storage_temp_celsius` at receipt. The receiving site must not be closed — receipt is accepted while the site is `INITIATED`, `ACTIVE`, or `ON_HOLD`, and rejected at a `CLOSED` site with `ERR_SITE_NOT_ACTIVE`. Every receipt, whatever its outcome, creates a temperature log for the kit's site whose `celsius` equals the declared `storage_temp_celsius` and whose `source` is `MANUAL`. If that temperature sits within the lot's inclusive storage range, the kit moves to `QUARANTINED_RECEIPT`, pending review. If it falls outside the range, the kit instead moves to `QUARANTINED_EXCURSION`: the receipt reading opens or extends an open excursion for the site exactly as §3.4 describes, the kit's `pre_quarantine_status` is recorded as `QUARANTINED_RECEIPT` — a receipt-excursion kit was never released, so a later acceptable assessment returns it to receipt quarantine rather than to available stock — and the kit's `excursion_id` links it to that excursion. Receiving a kit that is no longer `IN_TRANSIT` is rejected under the generic state gate with `ERR_INVALID_STATE`.

Release is the pharmacist's disposition of a receipt-quarantined kit into dispenseable stock, moving it `QUARANTINED_RECEIPT` → `AVAILABLE`. Attempting to release a kit in any other state is rejected with `ERR_KIT_NOT_RELEASABLE`. Four gates then guard the release: the kit's lot must be `ACTIVE` — an `EXPIRED` lot yields `ERR_LOT_EXPIRED` and a lot in any other non-active state yields `ERR_INVALID_STATE`; the logical clock must not yet have reached the lot's `expiry_date`, else `ERR_LOT_EXPIRED`; the lot's `stability_minutes_consumed` must still be strictly below its `stability_budget_minutes`, else `ERR_LOT_STABILITY_EXHAUSTED`; and the lot's study must be `ACTIVE`, else `ERR_STUDY_NOT_ACTIVE`.

### 3.4. Temperature Surveillance and Excursion Assessment

Between receipts, a `Pharmacist` records storage-temperature readings by supplying the `site_id`, the observed `celsius`, and the reading `source` — `MANUAL` or `DATALOGGER`; the server stamps `recorded_at` from the logical clock. A reading inside every stored lot's range at that site is a quiet event: the log's `excursion_id` remains null. A reading that falls outside the inclusive storage range of any lot with kits stored at the site is an excursion event — a lot counts as stored at a site while any of its kits carries that `site_id` in any status other than `DESTROYED`. It opens a new `OPEN` temperature excursion for the site — or extends the site's existing `OPEN` excursion — and cascades: every kit at that site in `AVAILABLE` or `ALLOCATED` whose lot's range is violated by the reading moves to `QUARANTINED_EXCURSION`, recording its `pre_quarantine_status` (`AVAILABLE` or `ALLOCATED`; an allocated kit's subject allocation is preserved through the excursion) and linking `excursion_id` to the excursion.

An excursion remembers its own weather. Its `window_start` is the timestamp of the first out-of-range reading linked to it, and its `window_end` tracks the most recent out-of-range reading while it remains `OPEN`. Across all linked out-of-range readings it maintains `min_observed_celsius` and `max_observed_celsius`, and each linked reading's `excursion_id` points back to the excursion.

Adjudication belongs to the sponsor. Assessing an excursion takes an `outcome` and a `resolution_rationale`; the rationale is mandatory for `ACCEPTABLE` and `UNACCEPTABLE`, and optional for `VOID`, where a supplied rationale replaces the stored one. Three outcomes exist, with sharply different consequences:

- `ACCEPTABLE` moves the excursion `OPEN` → `RESOLVED_ACCEPTABLE`. The server computes the excursion's severity (below), records it as `severity_minutes_charged`, and charges it to the stability budget of every distinct lot owning a kit linked to the excursion or quarantined by it — each such lot's `stability_minutes_consumed` increases by `severity_minutes_charged`. Linked kits then restore according to their `pre_quarantine_status`: `AVAILABLE` kits return to `AVAILABLE`, `ALLOCATED` kits return to `ALLOCATED` with their `allocated_subject_id` retained, and receipt-excursion kits return to `QUARANTINED_RECEIPT`; restored kits clear `excursion_id` and `pre_quarantine_status`. One exception overrides the restore: any kit whose lot is stability-exhausted after the charge — consumed has reached or exceeded the budget — remains in `QUARANTINED_EXCURSION`.
- `UNACCEPTABLE` moves the excursion `OPEN` → `RESOLVED_UNACCEPTABLE`. Severity is computed and charged to the same distinct lots exactly as for an acceptable assessment, but every linked kit moves from `QUARANTINED_EXCURSION` to `DESTRUCTION_PENDING`, clearing `pre_quarantine_status` while `excursion_id` is retained for audit. Each affected lot then recomputes its usable count; a lot falling to zero flips from `ACTIVE` to `DEPLETED` and triggers the automatic resupply described in §3.2.
- `VOID` — permitted only from `RESOLVED_ACCEPTABLE`, as a sponsor reversal of an acceptable assessment; a `VOID` attempted from any other status, including `OPEN`, is rejected with `ERR_EXCURSION_ALREADY_RESOLVED` — moves the excursion to `VOIDED`. The budget charge is reversed: every charged lot's `stability_minutes_consumed` is decreased by `severity_minutes_charged`, restoring the compensating invariant on stability minutes. Kits already restored stay restored; the void performs no retroactive kit mutation.

Assessing an excursion that is no longer `OPEN` — other than the void-from-acceptable path — is rejected with `ERR_EXCURSION_ALREADY_RESOLVED`. Excursions may be listed with `site_id` and `status` filters, and temperature logs with `site_id` and `excursion_id` filters.

The severity calculation runs against the snapshot reference range (§2.11) and proceeds in six steps. First, the excursion's duration is the whole number of minutes between `window_start` and `window_end`. Second, that duration is capped at 1,440 minutes — a full twenty-four hours; a longer excursion is credited with exactly 1,440. Third, the server classifies the breach side: the excursion breached below range if `min_observed_celsius` is less than `reference_temp_min_celsius`, and above range if `max_observed_celsius` is greater than `reference_temp_max_celsius`. Fourth, a side multiplier is chosen: 4 when the excursion breached on both sides, 3 when it breached below only, 2 when it breached above only, and 0 when neither side was breached. Fifth, the peak deviation is the larger of two candidates — the reference minimum minus the observed minimum when the excursion breached below, otherwise zero, and the observed maximum minus the reference maximum when it breached above, otherwise zero — and the degree band is that peak deviation divided by two and rounded up to the next whole number, with the band floored at 1. Sixth, `severity_minutes_charged` is the capped duration multiplied by the side multiplier, multiplied again by the degree band. All severity arithmetic is exact integer arithmetic, with the division's ceiling computed exactly.

### 3.5. Subject Enrollment, Screening, and Randomization

A `Pharmacist` registers each candidate subject at their site with a `subject_number` unique within that site — duplicates are rejected with `ERR_INVALID_REQUEST` — and a randomization `stratum` of `STANDARD` or `HIGH_RISK`. Every subject carries two parallel and independent status axes: the enrollment axis `enrollment_status`, beginning at `SCREENING`, and the blinding axis `blinded_status`, beginning at `BLINDED`. The rescreen counter `rescreen_count` starts at zero. Subjects may be listed with `site_id`, `enrollment_status`, and `blinded_status` filters.

Screening outcomes are recorded as enrollment transitions carrying a `to` target and an optional `reason`. A subject who fails screening moves `SCREENING` → `SCREEN_FAILED`. Rescreening moves them back `SCREEN_FAILED` → `SCREENING`, but only once: the transition requires `rescreen_count` to still be zero, increments it by one, and a second rescreen attempt is rejected with `ERR_RESCREEN_LIMIT_EXCEEDED`.

Randomization is driven by the sponsor's uploaded allocation list. Each randomization slot belongs to a study and carries a `sequence_number` fixing its allocation order within its `stratum`, the `kit_number` it assigns, and the masked `arm_code` (§2.8); slots begin `UNASSIGNED` and may be listed with `study_id`, `status`, `stratum`, `assigned_subject_id`, and `kit_number` filters. A `SponsorAdmin` replaces a study's list by uploading a payload `slots` together with `expected_study_version`; if that version no longer matches the study's current `version`, the replacement is rejected with `ERR_STALE_VERSION` rather than discarding a list built on a newer read. A successful replacement retires every `UNASSIGNED` slot to `RELEASED`, installs the payload slots as fresh `UNASSIGNED` entries, leaves `ASSIGNED` slots untouched, and increments the study's `version` by one. The replacement responds `200 OK` with the array of newly installed slots.

Randomizing a subject is the pivotal enrollment act, moving them `SCREENING` → `RANDOMIZED`; attempting it on a subject not in `SCREENING` is rejected with `ERR_SUBJECT_NOT_RANDOMIZABLE`. The gates run in the global order of §2.6: the subject's site must be `ACTIVE` (`ERR_SITE_NOT_ACTIVE`), the site's study must be `ACTIVE` (`ERR_STUDY_NOT_ACTIVE`), and an `UNASSIGNED` slot must exist for this study in the subject's `stratum` (`ERR_NO_RANDOMIZATION_SLOT`). The selected slot is the one with the lowest `sequence_number`, ties broken by the earlier `created_at`. That slot's `kit_number` must then resolve to a kit at the subject's own site in `AVAILABLE` status — with an important priority nuance: if the kit resolves but sits in `QUARANTINED_EXCURSION`, the rejection is the safety error `ERR_KIT_QUARANTINED_EXCURSION`, evaluated at the safety gate (priority 7), whereas any other non-`AVAILABLE` resolution is the later constraint error `ERR_SLOT_KIT_UNAVAILABLE` (priority 9). Finally the resolved kit's lot must not have reached its `expiry_date` at the current logical clock (`ERR_LOT_EXPIRED`). On success the subject's `randomized_at` is stamped from the logical clock, the slot moves `UNASSIGNED` → `ASSIGNED` with `assigned_subject_id` set to the subject, the kit moves `AVAILABLE` → `ALLOCATED` with `allocated_subject_id` set to the subject, and the study's `randomized_subject_count` increases by one — a counter that is never decremented, even if the subject later withdraws.

Subsequent visits draw further kits the same way. Allocating the next kit for an already `RANDOMIZED` subject selects the lowest-sequence `UNASSIGNED` slot of the subject's `stratum` — same tie-break — assigns it, and moves its `AVAILABLE` kit at the subject's site to `ALLOCATED` with `allocated_subject_id` recorded; the subject's enrollment does not change, and the response carries the subject resource.

Closing a subject out requires a clean accountability slate. Moving a `RANDOMIZED` subject to `COMPLETED` or to `WITHDRAWN` is blocked while any of the subject's dispensing records remains `ACTIVE`, surfacing `ERR_ACTIVE_DISPENSING_EXISTS`; both destination states are terminal.

### 3.6. Dispensing, Returns, and Drug Accountability

Dispensing is the moment product leaves the shelf for a subject. A `Pharmacist` records a dispensing by supplying the `subject_id`, the `kit_id`, the protocol `visit_number`, and the `quantity_dispensed` (at least one unit). The subject must be `RANDOMIZED` — otherwise `ERR_SUBJECT_NOT_RANDOMIZED` — and the study must be `ACTIVE` (`ERR_STUDY_NOT_ACTIVE`). The kit must be `ALLOCATED` to this very subject; a kit sitting in `QUARANTINED_EXCURSION` is rejected with the safety error `ERR_KIT_QUARANTINED_EXCURSION`, evaluated before the dispensability check, and a kit in any other wrong state, or allocated to a different subject, is rejected with `ERR_KIT_NOT_DISPENSABLE`. The kit's lot must not have reached expiry at the logical clock (`ERR_LOT_EXPIRED`). Three protocol gates complete the check. The dose cap: `quantity_dispensed` multiplied by the lot's `strength_mg` must not exceed the study's `max_dose_per_visit_mg`, else `ERR_DOSE_EXCEEDS_PROTOCOL_MAX`. The sequence rule: `visit_number` must equal the count of the subject's existing dispensing records plus one, else `ERR_VISIT_OUT_OF_SEQUENCE`. And the visit window: the nominal date of a subject's first visit is their `randomized_at`, and each later visit's nominal date falls exactly twenty-eight days after the previous one; dispensing for a visit is permitted only within the closed interval from three days before its nominal date through three days after it, and a dispensing outside that window is rejected with `ERR_VISIT_WINDOW_VIOLATION`.

A recorded dispensing stores the computed `dose_mg` — the product of `quantity_dispensed` and the kit's lot strength — is stamped `dispensed_at` from the logical clock, and begins in `ACTIVE` status. The dispensed kit moves `ALLOCATED` → `DISPENSED`, its `units_dispensed` increases by `quantity_dispensed`, and its `on_hand_units` is recomputed per the accountability ledger (§2.10). Dispensing records may be listed by `subject_id`, `kit_id`, and `status`.

When a subject brings product back, a `Pharmacist` records a return against an `ACTIVE` dispensing record, naming the `dispensing_record_id` and the `quantity_returned`. The quantity must lie between one and the dispensing record's `quantity_dispensed`, inclusive, and each dispensing record supports at most one return — an out-of-range quantity or a second return against the same record is rejected with `ERR_QUANTITY_MISMATCH`. The server captures the recorder's `X-User-ID` as `recorded_by_staff_id`, the kit moves `DISPENSED` → `RETURNED` with `units_returned` increased by `quantity_returned` and `on_hand_units` recomputed, and the dispensing record itself moves `ACTIVE` → `RETURNED`. The return begins `RECORDED`.

Verification is a second pair of eyes. A `Pharmacist` verifies a `RECORDED` return, and segregation of duties applies: if the verifier's `X-User-ID` equals the return's `recorded_by_staff_id`, the verification is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful verification stamps `verified_by_staff_id` and moves the return `RECORDED` → `VERIFIED`, its terminal state. Returns may be listed by `dispensing_record_id` and `status`.

### 3.7. Destruction Booking, Witnessing, and Finalization

Product that has come back — or has expired on the shelf — is destroyed under witness. A `Pharmacist` books a destruction for a kit in `RETURNED` or `EXPIRED` status by supplying the `kit_id`, the `site_id`, the destruction `method` (`INCINERATION`, `CHEMICAL_NEUTRALIZATION`, or `RETURN_TO_SPONSOR`), a booked facility window `facility_window_start` and `facility_window_end`, the `quantity_destroyed`, and the `witness_staff_id` of the designated witness. The window's end must be strictly after its start, the declared site must equal the kit's own site, and the witness must be a staff member of that same site; violations of these three are rejected with `ERR_INVALID_REQUEST`. The `quantity_destroyed` must equal the kit's current book on-hand balance — units received minus units dispensed plus units returned — otherwise the booking is rejected with `ERR_QUANTITY_MISMATCH`. Facility windows at a site are treated as closed intervals with a turnaround buffer: a booking whose window intersects another non-`VOIDED` destruction window at the same site, or that begins within thirty minutes after such a window ends, is rejected with `ERR_DESTRUCTION_WINDOW_CONFLICT`. On acceptance the server captures the creator's `X-User-ID` as `created_by_staff_id`, records the kit's current status in `kit_prior_status` (`RETURNED` or `EXPIRED`), opens the record in `DRAFT`, and moves the kit to `DESTRUCTION_PENDING`.

Attestation is where the segregation rules of §2.8 bite, and the attestation call carries an optional `void` flag distinguishing its two modes. In witness mode (`void` absent or false), the caller must be the designated witness — an `X-User-ID` other than the record's `witness_staff_id` is rejected with `ERR_UNAUTHORIZED_ROLE` — and must not be the creator, since an `X-User-ID` equal to `created_by_staff_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`; success moves the record `DRAFT` → `WITNESSED`. In void mode (`void` true), only the creator may abandon a draft — any other caller is rejected with `ERR_UNAUTHORIZED_ROLE` — and voiding moves the record `DRAFT` → `VOIDED` and restores the kit from `DESTRUCTION_PENDING` back to its `kit_prior_status`.

Finalization closes the loop. A `WITNESSED` record finalized by a `Pharmacist` moves the kit from `DESTRUCTION_PENDING` to the terminal `DESTROYED`, sets the kit's `units_destroyed` to the record's `quantity_destroyed`, and recomputes `on_hand_units`, which reaches zero. The lot then recomputes its usable count, and if none of its kits remain in usable states it flips from `ACTIVE` to `DEPLETED`; destruction finalization creates no resupply kits. `FINALIZED` and `VOIDED` are the destruction record's terminal states. Destruction records may be listed with `kit_id`, `site_id`, `witness_staff_id`, and `status` filters.

### 3.8. Emergency Unblinding and Blinding-Integrity Safeguards

Medical emergencies sometimes force the blind open. An `Investigator` requests an emergency unblinding by supplying the `subject_id` and a clinical `reason`; the server captures the caller's `X-User-ID` as `requested_by_user_id` and opens the request in `REQUESTED`. The subject must be `RANDOMIZED` — otherwise `ERR_SUBJECT_NOT_RANDOMIZED` — and still `BLINDED`, and the study must actually have a blind to break: requesting an unblinding on an `OPEN_LABEL` study is rejected with `ERR_STUDY_OPEN_LABEL`. Requests may be listed with `subject_id` and `status` filters.

Decision belongs to an `UnblindedPharmacist`, who submits a `decision` of `APPROVED` or `REJECTED`. The requester may never decide their own request: an `X-User-ID` equal to the request's `requested_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. Either decision stamps `decided_by_staff_id` and moves the request from `REQUESTED` to `APPROVED` or to the terminal `REJECTED`.

Execution completes the three-person rule. An `UnblindedPharmacist` executes an `APPROVED` request, but the approver may not also execute: an `X-User-ID` equal to `decided_by_staff_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`, so requester, decider, and executor are three distinct actors. Execution copies the treatment arm from the subject's earliest-created `ASSIGNED` randomization slot into the request's `revealed_arm_code` — masked to `null` for blinded roles per §2.8 — moves the request to the terminal `EXECUTED`, and flips the subject's blinding axis from `BLINDED` to `UNBLINDED`.

That flip is felt study-wide. The study's `unblinded_subject_count` is recomputed as the number of its subjects whose `blinded_status` is `UNBLINDED`, and the integrity threshold is evaluated: when one hundred times `unblinded_subject_count` is greater than or equal to `unblinding_suspension_threshold_pct` multiplied by `randomized_subject_count` — and at least one subject has been randomized, so the rule never fires on an empty denominator — the study suspends itself from `ACTIVE` to `SUSPENDED`, cascading every `ACTIVE` site to `ON_HOLD` (§3.1). Under the default threshold of 10, a study suspends once its unblinded subjects reach ten percent of its randomized population.

### 3.9. Monitor Visits, Reconciliation, and Site Invoicing

Sponsors verify accountability on site through monitor visits. A `Monitor` schedules a visit with the `site_id`, their own `monitor_name` recorded as free text — the Monitor role is opaque (§2.1) — and a scheduled window `scheduled_start` to `scheduled_end`, the end strictly after the start. Visit windows at a site behave as half-open intervals: a new visit whose interval intersects an existing `SCHEDULED` or `IN_PROGRESS` visit at the same site is rejected with `ERR_MONITOR_VISIT_OVERLAP`, while adjacency is permitted — a visit beginning exactly when another ends does not conflict. The visit begins `SCHEDULED`, and visits may be listed by `site_id` and `status`.

Starting a visit is gated on the clock: the `Monitor` may start only while the logical clock lies within the scheduled window, both bounds inclusive, otherwise the start is rejected with `ERR_OUTSIDE_VISIT_WINDOW`; starting stamps `started_at` and moves the visit `SCHEDULED` → `IN_PROGRESS`.

Closing a visit is the reconciliation act. The `Monitor` submits `counts`, a list of entries each pairing a `kit_id` with the `physical_units` counted on the shelf. Two preconditions guard the close: every drug return recorded against dispensing records at this site must already be `VERIFIED` (`ERR_UNVERIFIED_RETURN_PENDING`), and the submitted counts must cover every kit at the site in an on-hand state — `AVAILABLE`, `ALLOCATED`, `QUARANTINED_EXCURSION`, `EXPIRED`, `RETURNED`, or `DESTRUCTION_PENDING` — exactly once (`ERR_COUNT_INCOMPLETE`). At close the server stamps `closed_at`, computes `actual_minutes` as the whole minutes from `started_at` to `closed_at`, and reconciles each counted kit: the adjustment is the kit's book on-hand balance minus the submitted `physical_units`, and whenever the adjustment is nonzero it is added to the kit's `units_lost` — positive when units are missing, negative when an overage is found — with `on_hand_units` recomputed. This is the physical-reconciliation variant of the ledger (§2.10): the physical count replaces the projected balance and the delta is booked so the variants agree afterward. The visit's `discrepancy_count` records how many counted kits carried a nonzero adjustment; when every count matches the book, the visit closes `CLOSED_RECONCILED`, and with one or more discrepancies it closes `CLOSED_DISCREPANCY`. Either way, every dispensing record at the site in `RETURNED` whose drug return is `VERIFIED` advances to the terminal `RECONCILED`, and both closed visit states are terminal.

The sponsor's bill for a period is computed, never edited. A `SponsorAdmin` requests a site's invoice with `period_start`, `period_end`, and a `variant` of `PROVISIONAL` or `FINAL`, all supplied as query parameters; the period is the half-open interval that includes `period_start` and excludes `period_end`. The site's study must have an `APPROVED` fee schedule, or the computation is rejected with `ERR_NO_APPROVED_FEE_SCHEDULE`. Five lines build the invoice:

1. **Setup** — the schedule's `setup_fee_cents` is charged if the site's `activated_at` falls within the period; otherwise this line is zero.
2. **Dispensing** — every dispensing record whose kit belongs to this site and whose `dispensed_at` falls in the period contributes a per-record fee. Within each subject's own records, ordered by `dispensed_at` with ties broken by `created_at`, the subject's cumulative dispensing index decides the rate: positions up to and including `dispensing_tier_threshold` each bill `dispensing_fee_cents`, and every position beyond the threshold bills `dispensing_tier_fee_cents`.
3. **Monitoring** — under the `FINAL` variant, visits in `CLOSED_RECONCILED` or `CLOSED_DISCREPANCY` whose `closed_at` falls in the period are billed at their `actual_minutes`; under `PROVISIONAL`, any visit in `SCHEDULED`, `IN_PROGRESS`, `CLOSED_RECONCILED`, or `CLOSED_DISCREPANCY` whose scheduled window overlaps the period is billed, using `actual_minutes` for closed visits and the whole minutes between `scheduled_start` and `scheduled_end` for unclosed ones. Each visit's fee is `monitoring_fee_cents_per_hour` multiplied by its minutes and divided by sixty, rounded half-up to a whole cent per visit, and the line is the sum of those per-visit amounts.
4. **Storage** — the count of kits at the site in `AVAILABLE`, `ALLOCATED`, or `QUARANTINED_EXCURSION` whose `created_at` precedes `period_end`, evaluated at read time and identical under both variants, multiplied by `storage_fee_cents_per_kit_month`.
5. **Unblinding** — under `FINAL`, the count of unblinding requests belonging to subjects at this site in `EXECUTED` status whose `updated_at` (the execution time) falls in the period; under `PROVISIONAL`, requests in `APPROVED` or `EXECUTED` with `updated_at` in the period. The count is multiplied by `unblinding_fee_cents`.

The invoice then totals in a pinned order: `subtotal_cents` is the sum of the five lines; `overhead_cents` is the subtotal multiplied by `overhead_pct` and divided by one hundred, rounded half-up to a whole cent; and `total_cents` is the subtotal plus the overhead. The response reports `setup_fee_cents`, `dispensing_fees_cents`, `monitoring_fees_cents`, `storage_fees_cents`, `unblinding_fees_cents`, `subtotal_cents`, `overhead_cents`, `total_cents`, and the `variant` used. For identical site data the two variants diverge exactly when pipeline visits or approved-but-not-yet-executed unblinding requests exist.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read, modify, or act on an existing resource return `200 OK`. Request and response payloads for each endpoint are reconstructed from the workflow narratives in §3 together with the global specifications of §2; the table below fixes only the HTTP contract and the authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/studies` | Create a study in `DRAFT` | SponsorAdmin |
| GET | `/api/studies` | List studies | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor, Investigator |
| GET | `/api/studies/{id}` | Get a study | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor, Investigator |
| POST | `/api/studies/{id}/transition` | Transition a study per its lifecycle | SponsorAdmin |
| POST | `/api/sites` | Create a site in `INITIATED` | SponsorAdmin |
| GET | `/api/sites` | List sites | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor, Investigator |
| GET | `/api/sites/{id}` | Get a site | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor, Investigator |
| POST | `/api/sites/{id}/transition` | Transition a site per its lifecycle | SponsorAdmin |
| POST | `/api/staff` | Create a pharmacy staff member | SponsorAdmin |
| GET | `/api/staff` | List staff | SponsorAdmin, Pharmacist, UnblindedPharmacist |
| GET | `/api/staff/{id}` | Get a staff member | SponsorAdmin, Pharmacist, UnblindedPharmacist |
| POST | `/api/lots` | Register a drug lot | SponsorAdmin |
| GET | `/api/lots` | List lots | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor |
| GET | `/api/lots/{id}` | Get a lot | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor |
| POST | `/api/shipments` | Ship kits to a site (bulk creation in `IN_TRANSIT`) | SponsorAdmin |
| GET | `/api/kits` | List kits | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor |
| GET | `/api/kits/{id}` | Get a kit | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor |
| POST | `/api/kits/{id}/receive` | Receive a kit into receipt quarantine (or excursion quarantine) | Pharmacist |
| POST | `/api/kits/{id}/release` | Release a receipt-quarantined kit to available stock | Pharmacist |
| POST | `/api/temperature-logs` | Record a storage temperature reading | Pharmacist |
| GET | `/api/temperature-logs` | List temperature logs | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor |
| GET | `/api/temperature-logs/{id}` | Get a temperature log | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor |
| GET | `/api/temperature-excursions` | List temperature excursions | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor |
| GET | `/api/temperature-excursions/{id}` | Get a temperature excursion | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor |
| POST | `/api/temperature-excursions/{id}/assess` | Assess an excursion (acceptable, unacceptable, or void) | SponsorAdmin |
| POST | `/api/subjects` | Register a subject in `SCREENING` / `BLINDED` | Pharmacist |
| GET | `/api/subjects` | List subjects | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor, Investigator |
| GET | `/api/subjects/{id}` | Get a subject | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor, Investigator |
| POST | `/api/subjects/{id}/transition` | Transition a subject's enrollment axis | Pharmacist |
| POST | `/api/subjects/{id}/randomize` | Randomize a screening subject via slot selection | Pharmacist |
| POST | `/api/subjects/{id}/allocate-kit` | Allocate the next kit to a randomized subject | Pharmacist |
| POST | `/api/studies/{id}/randomization-slots/replace` | Replace a study's randomization slot list (OCC-guarded) | SponsorAdmin |
| GET | `/api/randomization-slots` | List randomization slots (arm codes masked for blinded roles) | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor, Investigator |
| GET | `/api/randomization-slots/{id}` | Get a randomization slot | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor, Investigator |
| POST | `/api/dispensing-records` | Dispense an allocated kit to its subject | Pharmacist |
| GET | `/api/dispensing-records` | List dispensing records | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor |
| GET | `/api/dispensing-records/{id}` | Get a dispensing record | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor |
| POST | `/api/returns` | Record a subject drug return | Pharmacist |
| GET | `/api/returns` | List drug returns | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor |
| GET | `/api/returns/{id}` | Get a drug return | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor |
| POST | `/api/returns/{id}/verify` | Verify a recorded return (segregated from recorder) | Pharmacist |
| POST | `/api/destruction-records` | Book a kit destruction into a facility window | Pharmacist |
| GET | `/api/destruction-records` | List destruction records | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor |
| GET | `/api/destruction-records/{id}` | Get a destruction record | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor |
| POST | `/api/destruction-records/{id}/attest` | Witness-attest a draft, or creator-void it | Pharmacist |
| POST | `/api/destruction-records/{id}/finalize` | Finalize a witnessed destruction | Pharmacist |
| POST | `/api/unblinding-requests` | Request an emergency unblinding | Investigator |
| GET | `/api/unblinding-requests` | List unblinding requests (arm codes masked for blinded roles) | SponsorAdmin, Pharmacist, UnblindedPharmacist, Investigator |
| GET | `/api/unblinding-requests/{id}` | Get an unblinding request | SponsorAdmin, Pharmacist, UnblindedPharmacist, Investigator |
| POST | `/api/unblinding-requests/{id}/decide` | Approve or reject an unblinding request | UnblindedPharmacist |
| POST | `/api/unblinding-requests/{id}/execute` | Execute an approved unblinding | UnblindedPharmacist |
| POST | `/api/monitor-visits` | Schedule a monitor visit | Monitor |
| GET | `/api/monitor-visits` | List monitor visits | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor |
| GET | `/api/monitor-visits/{id}` | Get a monitor visit | SponsorAdmin, Pharmacist, UnblindedPharmacist, Monitor |
| POST | `/api/monitor-visits/{id}/start` | Start a scheduled visit within its window | Monitor |
| POST | `/api/monitor-visits/{id}/close` | Close a visit with physical counts and reconcile | Monitor |
| POST | `/api/fee-schedules` | Create a fee schedule in `DRAFT` | SponsorAdmin |
| GET | `/api/fee-schedules` | List fee schedules | SponsorAdmin |
| GET | `/api/fee-schedules/{id}` | Get a fee schedule | SponsorAdmin |
| POST | `/api/fee-schedules/{id}/approve` | Approve a fee schedule (OCC-guarded; supersedes prior) | SponsorAdmin |
| GET | `/api/sites/{id}/invoice` | Compute a site's invoice for a period and variant | SponsorAdmin |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock (test-driving) | SponsorAdmin |
| POST | `/api/_ops/expiry_sweep` | Run the expiry sweep across kits and lots | SponsorAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue fixes only the identifier and the HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STUDY_NOT_FOUND` | 404 |
| `ERR_SITE_NOT_FOUND` | 404 |
| `ERR_KIT_NOT_FOUND` | 404 |
| `ERR_SUBJECT_NOT_FOUND` | 404 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STUDY_NOT_ACTIVE` | 409 |
| `ERR_SITE_NOT_ACTIVE` | 409 |
| `ERR_KIT_NOT_RELEASABLE` | 409 |
| `ERR_KIT_NOT_DISPENSABLE` | 409 |
| `ERR_SUBJECT_NOT_RANDOMIZABLE` | 409 |
| `ERR_SUBJECT_NOT_RANDOMIZED` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_EXCURSION_ALREADY_RESOLVED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_LOT_EXPIRED` | 422 |
| `ERR_KIT_QUARANTINED_EXCURSION` | 422 |
| `ERR_LOT_STABILITY_EXHAUSTED` | 422 |
| `ERR_DOSE_EXCEEDS_PROTOCOL_MAX` | 422 |
| `ERR_STUDY_OPEN_LABEL` | 422 |
| `ERR_VISIT_WINDOW_VIOLATION` | 422 |
| `ERR_VISIT_OUT_OF_SEQUENCE` | 422 |
| `ERR_OUTSIDE_VISIT_WINDOW` | 422 |
| `ERR_MONITOR_VISIT_OVERLAP` | 409 |
| `ERR_DESTRUCTION_WINDOW_CONFLICT` | 409 |
| `ERR_NO_RANDOMIZATION_SLOT` | 422 |
| `ERR_SLOT_KIT_UNAVAILABLE` | 422 |
| `ERR_DUPLICATE_PROTOCOL_NUMBER` | 409 |
| `ERR_DUPLICATE_KIT_NUMBER` | 409 |
| `ERR_RESCREEN_LIMIT_EXCEEDED` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_QUANTITY_MISMATCH` | 422 |
| `ERR_UNVERIFIED_RETURN_PENDING` | 422 |
| `ERR_COUNT_INCOMPLETE` | 422 |
| `ERR_NO_APPROVED_FEE_SCHEDULE` | 422 |
| `ERR_ACTIVE_DISPENSING_EXISTS` | 422 |
