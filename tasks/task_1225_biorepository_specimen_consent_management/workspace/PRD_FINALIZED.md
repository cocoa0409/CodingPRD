# Biorepository Consent API — Product Requirements Document

## 1. Introduction

An academic biobank lives or dies by two assets that are easy to damage and impossible to replace: donor trust and specimen integrity. Every milliliter of blood, saliva, tissue, or plasma in the freezers is bound to a consent record that spells out what research it may serve, and every custody handoff, temperature excursion, and re-identification event must be reconstructible after the fact. This document specifies the Biorepository Consent API, the system of record for an academic biorepository that manages that entire chain — from donor enrollment and consent filing, through collection kit distribution and specimen accession, to committee-reviewed sample distribution and, when a donor withdraws, the controlled destruction of everything their consent no longer covers.

The API coordinates six operator roles with deliberately segregated duties: the staff who register consent never confirm destructions, the reviewers who approve requests never review their own, and the officers who reveal a donor's identity never do so under a grant issued to themselves. Specimen inventory is tracked down to individual aliquots with dual volume ledgers, freezers are monitored by degree-minute excursion accounting with a hard viability ceiling, and every outbound sample is charged against a sharing agreement's contracted quota with surcharge pricing near exhaustion. All deadline-driven behavior — consent withdrawal grace periods, kit expiry, agreement expiry, access-grant expiry, and reservation completion — is evaluated against a controllable logical clock and executed by an explicit sweep, so that compliance timelines are deterministic and auditable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly six roles, spelled as follows: `BiobankAdmin`, `ConsentCoordinator`, `LabTechnician`, `CommitteeReviewer`, `Researcher`, and `QualityOfficer`.

- A `BiobankAdmin` is the biobank operations administrator: the freezer registry, sharing agreements, fulfillment runs, the due-date sweep, and the logical clock belong to this role.
- A `ConsentCoordinator` is the donor and consent registrar and the kit custodian, and also controls de-identification keys and their access grants.
- A `LabTechnician` is the wet-lab operator: accession, aliquoting, voiding, checkout, slot reservations, and temperature readings.
- A `CommitteeReviewer` sits on the request review committee, casting votes and requesting revisions.
- A `Researcher` is the external investigator who creates, submits, and cancels their own sample requests.
- A `QualityOfficer` owns quality and compliance contingencies: freezer failure declaration and return-to-service, destruction orders and their confirmation, and re-identification reveals.

For each of the six roles — `BiobankAdmin`, `ConsentCoordinator`, `LabTechnician`, `CommitteeReviewer`, `Researcher`, and `QualityOfficer` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `requester_user_id` on a sample request, `actor_user_id` on a custody event, `reviewer_user_id` on a vote, `holder_user_id` on a de-identification key, `grantee_user_id` on an access grant, or `created_by_user_id` and `confirmed_by_user_id` on a destruction order) but it never compares `X-User-ID` to any entity's `id`. Attempting an operation outside one's role — or, for the requester-owned mutations described in §3.6, acting on a request whose `requester_user_id` differs from `X-User-ID` — is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. The `meta` object of list responses carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Audit Trail

Donors, consent records, collection kits, specimens, aliquots, storage units, storage slots, slot reservations, sample requests, sharing agreements, de-identification keys, key access grants, and destruction orders all share a standard set of system-managed properties:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer starting at 1 that increments by one on every mutation, including mutations caused by cascades rather than direct client action.

Three resource types are immutable audit records and deviate from this pattern: custody events, temperature readings, and review votes carry only `id` and `created_at`. Both `updated_at` and `version` are absent from them — an event, a reading, or a cast vote is never modified after the fact. When a cascade or reconciliation mutates a parent resource (for example, when an aliquot operation changes a specimen's volumes), that mutation refreshes the parent's `updated_at` and increments its `version` exactly as a direct edit would.

### 2.5. The Logical Clock and the Due-Date Sweep

All deadline semantics in the system — consent grace periods, kit expiry, agreement windows, grant windows, reservation windows — are evaluated against a logical clock, never against wall-clock time. Before any operator intervention the clock starts at exactly 2026-05-01T00:00:00Z. A `BiobankAdmin` may advance the logical clock through a test-driving capability that accepts a target instant in the `to_iso8601` field; the response echoes the new time as `current_utc`. Setting the clock is inert by itself: no deadline processing runs implicitly, and the server never falls back to wall-clock time.

Deadline processing happens only when a `BiobankAdmin` explicitly runs the due-date sweep. One sweep pass performs five jobs: it finalizes consent withdrawals whose grace period has elapsed (firing the full withdrawal cascade of §3.9), expires collection kits whose `expires_at` has been reached, expires sharing agreements whose window has closed, expires key access grants whose window has passed, and completes slot reservations whose window has ended. The sweep response reports how many items each job processed, via the counters `withdrawals_finalized`, `kits_expired`, `agreements_expired`, `grants_expired`, and `reservations_completed`.

Boundary inclusivity is pinned per job. A withdrawal finalizes when the current time is at or after the consent's `grace_deadline`. A kit expires when the current time is at or after its `expires_at`, but only while the kit is `IN_STOCK` or `DISTRIBUTED`. An agreement expires when the current time is at or after its `effective_to`. A grant expires only once the current time is strictly later than its `ends_at`. A reservation completes when its `ends_at` is at or before the current time.

### 2.6. Request Validation Order

Every request passes through a fixed validation cascade, and the ordering is part of the contract — when several checks could fail, the one earliest in this order determines the error returned:

1. **Authentication headers** — presence and non-emptiness of `X-User-ID` and `X-User-Role`, failing as `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Authorization** — role permission for the endpoint and, where applicable, requester ownership, failing as `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Path existence** — resource identifiers in the URL are validated strictly left-to-right; the first identifier that does not resolve to an existing resource fails the request with `ERR_NOT_FOUND` (HTTP 404). A request addressed to a slot nested under a non-existent storage unit, for example, fails on the unit before the slot is ever examined.
4. **Optimistic concurrency** — on the two version-guarded endpoints of §2.7, the expected-version check runs here, before any state or business rule, failing as `ERR_STALE_VERSION`.
5. **Request shape** — required fields present, types valid, enum values within their declared sets, and `starts_at` strictly before `ends_at` wherever a window is supplied; any unknown request field is rejected. All shape failures return `ERR_INVALID_REQUEST` (HTTP 400).
6. **State preconditions** — the target resource must be in the state the transition requires. Domain-specific state errors (`ERR_KIT_NOT_DISTRIBUTABLE`, `ERR_KIT_NOT_RETURNED`, `ERR_CONSENT_NOT_ACTIVE`, `ERR_REQUEST_NOT_UNDER_REVIEW`, `ERR_REQUEST_NOT_APPROVED`, `ERR_ALIQUOT_NOT_RESERVED_FOR_REQUEST`, `ERR_DESTRUCTION_ORDER_NOT_CONFIRMABLE`, `ERR_KEY_NOT_ACTIVE`) and the generic `ERR_INVALID_STATE` (HTTP 409) all live at this tier. Attempting an action on a resource that has already reached a terminal state is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409).
7. **Business rules** — consent status, scope coverage, segregation of duties, referential coherence, temporal windows, quotas, and the remaining domain checks of §3, evaluated in the priority order given with each workflow. Fiscal checks always come last among business rules, so a fulfillment that would fail both an inventory check and the quota check reports the inventory failure first.

### 2.7. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control, and the guard is mandatory on both — the expected-version field is never optional on these endpoints, and no other endpoint accepts a version field at all.

- **Aliquot creation.** Creating an aliquot against a specimen requires the request to carry `expected_specimen_version` equal to the specimen's current `version`. If the specimen's version has advanced since the client last observed it — for example because another aliquot creation debited its `residual_volume_ml` or a void restored it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412); the client must re-read the specimen and retry with the fresh version.
- **Consent amendment.** Filing a consent amendment requires the request to carry `expected_consent_record_version` equal to the consent record's current `version`. Because an amendment supersedes the prior record and bumps its version, a second amendment attempted against the same observed version must fail on the stale version alone — it is rejected with `ERR_STALE_VERSION` (HTTP 412) even though the record it targets has already been superseded.

On both endpoints the version check is evaluated before any state or business rule, per the validation order of §2.6.

### 2.8. Units, Precision, and Rounding

Volumes are measured in milliliters. All computed volumes — specimen residuals, committed-volume ledgers, fulfillment charges — are carried to exactly 3 decimal places using round-half-up. Temperature excursion metrics (`peak_excursion_c` and `cumulative_degree_minutes`) are carried to exactly 2 decimal places, also round-half-up. Money is handled in integer cents: the handling fee rounds each per-aliquot line to whole cents with round-half-up before any summation, so the request-level fee is always an exact integer. Committee vote counts are plain integers with no rounding. Timestamps are ISO 8601 in UTC; deadline arithmetic such as grace periods and destruction SLAs operates at second precision.

### 2.9. Segregation of Duties and Dual Control

Three controls in the system are segregated, meaning the same user may never perform both sides of the pair, and every violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403):

- The operator who creates a destruction order may not confirm its execution — `confirmed_by_user_id` must differ from `created_by_user_id`.
- A committee reviewer may not vote on a sample request they themselves submitted — the reviewer's `X-User-ID` must differ from the request's `requester_user_id`.
- A re-identification reveal may not be performed by the user named as the grant's grantee — the revealing officer's `X-User-ID` must differ from the grant's `grantee_user_id`.

## 3. Business Logic & Workflows

### 3.1. Donor Enrollment and the Consent Record Lifecycle

A `ConsentCoordinator` onboards a donor by registering a `donor_reference_code`, an external reference that must be unique across donors. A donor's `status` is `ENROLLED` — the sole donor status in this version of the system.

Against an enrolled donor, the coordinator files consent records. Filing requires `permitted_uses`, a non-empty subset of the consent use enum — `GENERAL_RESEARCH`, `DISEASE_SPECIFIC`, `GENETIC_ANALYSIS`, `COMMERCIAL_USE` — together with an `effective_from` instant. Two optional fields refine the grant: `excluded_uses`, a subset of the same enum carved back out of the permitted set, which defaults to an empty list, and `allow_reidentification`, which defaults to false and governs whether the re-identification key of §3.8 may ever be revealed. A freshly filed consent record is `ACTIVE`. A consent record is usable only once the current time has reached its `effective_from`; an `ACTIVE` record whose `effective_from` is still in the future is treated as not yet effective, and operations that require an active consent reject it with `ERR_CONSENT_NOT_ACTIVE` (HTTP 409). The consent record list accepts optional `donor_id`, `supersedes_consent_id`, and `status` filters, and a donor-scoped variant lists one donor's records.

Consent statuses are `ACTIVE`, `WITHDRAWAL_PENDING`, `WITHDRAWN`, and `SUPERSEDED`, the last two being terminal. A donor-initiated withdrawal begins when the coordinator records it: the consent must be `ACTIVE` and already effective, failing otherwise with `ERR_CONSENT_NOT_ACTIVE`. Recording a withdrawal moves the consent from `ACTIVE` to `WITHDRAWAL_PENDING`, stamps `withdrawal_requested_at` with the current time, computes `grace_deadline` as exactly 72 hours after `withdrawal_requested_at`, and increments the record's `version` by one. The grace period gives the donor a reconsideration window: while the consent is `WITHDRAWAL_PENDING` and the current time is still strictly before `grace_deadline`, the coordinator may rescind the withdrawal, returning the consent to `ACTIVE`, clearing `withdrawal_requested_at` and `grace_deadline` back to null, and again incrementing `version`. A rescind attempted at or after the grace deadline is rejected with `ERR_WITHDRAWAL_GRACE_EXPIRED` (HTTP 409); a rescind attempted on a consent that is not `WITHDRAWAL_PENDING` is rejected with `ERR_CONSENT_NOT_ACTIVE`. What the sweep does once the grace deadline passes is covered in §3.9.

Amendment is the third consent transition. Filing an amendment against a consent creates a brand-new consent record for the same donor — `ACTIVE`, at `version` 1, with its `supersedes_consent_id` pointing at the record it replaces — and flips the prior record from `ACTIVE` to `SUPERSEDED`, incrementing the prior record's `version` by one. The amendment payload takes the same fields as a fresh filing (`permitted_uses`, `effective_from`, optional `excluded_uses` and `allow_reidentification`) plus the mandatory `expected_consent_record_version` guard of §2.7: the stale-version check runs first and fails as `ERR_STALE_VERSION`, after which the record must still be `ACTIVE`, failing as `ERR_CONSENT_NOT_ACTIVE`.

### 3.2. Collection Kit Distribution and Chain of Custody

Collection kits are the physical bridge between donor and freezer. A `ConsentCoordinator` registers a kit into stock by declaring its `kit_type` — `BLOOD`, `SALIVA`, or `TISSUE` — and its `expires_at` instant. A new kit is `IN_STOCK` and its `donor_id` is null. The kit list supports optional `donor_id` and `status` filters.

Distribution assigns the kit to a donor. The coordinator supplies the recipient's `donor_id` and may attach a free-text `location` and `note`, which are recorded on the custody event the distribution appends. The kit must be `IN_STOCK` — any other status fails with `ERR_KIT_NOT_DISTRIBUTABLE` (HTTP 409) — and the current time must be strictly earlier than the kit's `expires_at`, failing otherwise with `ERR_KIT_EXPIRED` (HTTP 409); the state check precedes the expiry check. Distribution moves the kit from `IN_STOCK` to `DISTRIBUTED`, stamps `distributed_at`, records the payload's `donor_id` on the kit, and appends a custody event of type `DISTRIBUTED`.

Receiving a returned kit mirrors the flow. The kit must be `DISTRIBUTED`, failing otherwise with `ERR_KIT_NOT_RETURNED` (HTTP 409), and the same unexpired check applies with `ERR_KIT_EXPIRED`. Receive-return moves the kit from `DISTRIBUTED` to `RETURNED`, stamps `returned_at`, and appends a custody event of type `RETURNED`, again carrying the optional `location` and `note`.

Two further kit transitions are system-driven. Accession, described in §3.3, consumes a `RETURNED` kit: the kit moves to `CONSUMED` and a custody event of type `CONSUMED` is appended. The sweep of §2.5 expires any kit still `IN_STOCK` or `DISTRIBUTED` once the current time reaches its `expires_at`, moving it to `EXPIRED` and appending a custody event of type `EXPIRED`. `CONSUMED` and `EXPIRED` are the kit's terminal states.

The chain of custody for a kit is therefore an ordered list of custody events, retrievable per kit in `created_at` ascending order. Each event carries the `kit_id` it belongs to, an `event_type` of `DISTRIBUTED`, `RETURNED`, `CONSUMED`, or `EXPIRED`, the `actor_user_id` of whoever caused it (the literal value "system" for sweep-driven expirations), and the free-text `location` and `note`, either of which may be null. Custody events are immutable audit records in the sense of §2.4 — no `updated_at`, no `version`.

### 3.3. Specimen Accession, Aliquoting, and Volume Accounting

When a kit comes back, a `LabTechnician` accessions its contents as a specimen. The accession payload names the `donor_id`, the `kit_id` of the returned kit, the `consent_record_id` under which the material was collected, the `specimen_type` (`BLOOD`, `SALIVA`, `TISSUE`, or `PLASMA`), the `collected_at` timestamp, and an `initial_volume_ml` that must be greater than zero; an optional `storage_slot_id` places the specimen directly into cold storage. Accession checks, in order: the kit must be `RETURNED`, failing as `ERR_KIT_NOT_RETURNED`; the referenced consent must be `ACTIVE` and effective, failing as `ERR_CONSENT_NOT_ACTIVE`; the donor references must cohere — the kit's `donor_id` and the consent's `donor_id` must both equal the payload's `donor_id`, failing as `ERR_DONOR_MISMATCH` (HTTP 400); and the kit must still be unexpired at accession, failing as `ERR_KIT_EXPIRED`. If a `storage_slot_id` is supplied, that slot must be `AVAILABLE`, failing as `ERR_SLOT_NOT_AVAILABLE` (HTTP 409).

A successful accession consumes the kit (§3.2), sets the specimen's `residual_volume_ml` equal to its `initial_volume_ml`, and starts the specimen's `viability_status` at `USABLE`. Its `lifecycle_status` starts at `IN_STORAGE` when a storage slot was provided and `ACCESSIONED` otherwise; a specimen accessioned without a slot later advances from `ACCESSIONED` to `IN_STORAGE` when the first of its aliquots is placed into a slot. Specimen lifecycle states are `ACCESSIONED`, `IN_STORAGE`, `DESTRUCTION_PENDING`, and the terminal `DESTROYED`. The `viability_status` is a parallel dimension — `USABLE` or `QUARANTINED` — that evolves independently of the lifecycle: a freezer event can quarantine a specimen's viability without touching its lifecycle state. The `collected_at` value matters beyond record-keeping: the fulfillment selector of §3.7 ranks candidate specimens oldest-first by it. The specimen list is paginated and accepts optional `donor_id`, `kit_id`, `consent_record_id`, `storage_slot_id`, `lifecycle_status`, and `viability_status` filters alongside `limit` and `offset`.

Volume accounting keeps three computed figures on every specimen, all at 3 decimal places with round-half-up. The `residual_volume_ml` is the specimen's accessioned volume minus the sum of the `initial_volume_ml` of every child aliquot whose status is not `VOID`; it is recomputed immediately when an aliquot is created (a debit) and when one is voided (a compensating credit). Two committed-volume variants serve different planning questions. The forward-looking `committed_volume_book_ml` sums the `initial_volume_ml` of aliquots in `RESERVED`, `DESTRUCTION_PENDING`, `DISTRIBUTED`, or `DESTROYED` status — it counts material that is merely reserved or queued for destruction, so it exceeds the physical figure whenever reservations exist. The chronological `committed_volume_physical_ml` sums only aliquots in `DISTRIBUTED` or `DESTROYED` — material that is physically gone — so it lags the book figure until checkouts and destructions complete. `VOID` aliquots are excluded from all three aggregates.

Aliquot creation is the act of splitting a specimen. The payload carries the aliquot's `initial_volume_ml`, the mandatory `expected_specimen_version` guard, and an optional `storage_slot_id` whose slot must be `AVAILABLE` or the request fails with `ERR_SLOT_NOT_AVAILABLE`. Per §2.6 the stale-version guard runs first, failing as `ERR_STALE_VERSION`; then the specimen must be aliquotable — `lifecycle_status` in `ACCESSIONED` or `IN_STORAGE` and viability not `QUARANTINED` — failing as `ERR_SPECIMEN_NOT_ALIQUOTABLE` (HTTP 409); then the volume check: the requested `initial_volume_ml` must be greater than zero and no larger than the specimen's current `residual_volume_ml`, with equality allowed, failing as `ERR_INSUFFICIENT_SPECIMEN_VOLUME` (HTTP 422). A created aliquot starts `IN_STORAGE` with its `remaining_volume_ml` equal to its `initial_volume_ml`, and the creation debits the specimen's `residual_volume_ml` by the aliquot volume and increments the specimen's `version` by one. Aliquot statuses are `IN_STORAGE`, `RESERVED`, `QUARANTINED`, `DESTRUCTION_PENDING`, `DISTRIBUTED`, `DESTROYED`, and `VOID`; the last three are terminal. The `reserved_for_request_id` field links a `RESERVED` aliquot to the sample request holding it — set by fulfillment, cleared by release or checkout, and null at all other times. The aliquot list accepts optional `specimen_id`, `storage_slot_id`, `reserved_for_request_id`, and `status` filters, and a specimen-scoped variant lists one specimen's aliquots.

Voiding is the corrective action for a mis-created aliquot. A `LabTechnician` may void an aliquot only while it is `IN_STORAGE`, failing otherwise with `ERR_INVALID_STATE` (HTTP 409). Voiding sets the aliquot's status to `VOID`, zeroes its `remaining_volume_ml`, restores the specimen's `residual_volume_ml` by adding the aliquot's `initial_volume_ml` back, and increments the specimen's `version` by one.

### 3.4. Freezer Registry, Temperature Surveillance, and Failure Contingency

A `BiobankAdmin` registers each freezer as a storage unit with a unique `unit_code` and a target `setpoint_c` in Celsius. Two thresholds govern its posture: `warn_threshold_c`, defaulting to -70.0, and `fail_threshold_c`, defaulting to -60.0. A new unit's `posture` is `OPERATIONAL`, and both excursion metrics — `peak_excursion_c` and `cumulative_degree_minutes` — start at zero.

Within a unit, the administrator defines storage slots, each with a `slot_code` unique within the unit and a `capacity_ml` that must be greater than zero. A slot's `status` is `AVAILABLE` or `OFFLINE`; only unit failure takes a slot offline (§2.4's hierarchy principle made concrete), and only return-to-service restores it. Each slot record carries the `storage_unit_id` of its owning unit.

Slots can be booked for planned work. A `LabTechnician` books a reservation with `starts_at`, `ends_at`, and a `purpose` of `MAINTENANCE`, `TRANSFER_HOLD`, or `AUDIT`; the reservation carries the slot's `storage_slot_id` reference and starts in `BOOKED` status. Reservation windows are half-open: the start instant is included, the end instant is excluded, and `ends_at` must be strictly after `starts_at` or the request fails shape validation as `ERR_INVALID_REQUEST`. Booking is rejected with `ERR_SLOT_RESERVATION_OVERLAP` (HTTP 409) when the new window overlaps any existing `BOOKED` reservation on the same slot; back-to-back adjacency — the new `starts_at` landing exactly on an existing reservation's `ends_at` — is allowed, because half-open windows that merely touch do not overlap. The slot itself must be `AVAILABLE` (`ERR_SLOT_NOT_AVAILABLE`), and the unit's `posture` must be `OPERATIONAL` (`ERR_UNIT_NOT_OPERATIONAL`, HTTP 409). The sweep completes a `BOOKED` reservation — moving it to `COMPLETED` — once its `ends_at` is at or before the current time; `CANCELLED` is the fate of bookings caught by a unit failure, as described below.

Temperature surveillance runs through readings. A `LabTechnician` ingests a reading with its `recorded_at` timestamp and a `temp_c` value; readings are immutable audit records carrying the `storage_unit_id` they belong to. The plausible range for `temp_c` is from -100.0 to +25.0 inclusive — anything outside is rejected with `ERR_INVALID_TEMPERATURE_READING` (HTTP 400). A unit's readings are always listed ordered by `recorded_at` ascending with ties broken by `created_at` ascending, and that same ordering drives the excursion math.

Posture is re-evaluated on every reading. A reading strictly above the unit's `warn_threshold_c` but at or below its `fail_threshold_c` moves an `OPERATIONAL` unit to `WARNING`. A reading strictly above `fail_threshold_c` moves the unit — whether `OPERATIONAL` or `WARNING` — to `FAILURE`, firing the same cascade as a declared failure. A reading at or below `warn_threshold_c` returns a `WARNING` unit to `OPERATIONAL`; a unit in `FAILURE` never recovers through readings alone and stays failed until the return-to-service action below.

Two excursion metrics are recomputed on each ingested reading, both at 2 decimal places with round-half-up, over the unit's readings processed in listing order. The **peak** variant, `peak_excursion_c`, is the largest excess any single reading has registered over the `warn_threshold_c`, floored at zero — it reports the single worst deviation regardless of duration, so a unit that touched -65 °C once and a unit that sat at -66 °C for hours can share the same peak. The **cumulative** variant, `cumulative_degree_minutes`, time-weights the deviations: for every reading strictly above `warn_threshold_c`, the excess of its `temp_c` over the threshold is multiplied by the whole minutes elapsed since the previous reading, and the product is added to the running total. Readings at or below the warn threshold accrue zero and end any excursion posture; a unit's very first reading has no predecessor and likewise accrues zero. Long mild excursions can therefore exceed short sharp ones, which is exactly what the viability review at return-to-service relies on.

When a freezer genuinely fails, a `QualityOfficer` declares the failure, optionally attaching a `note`. Declaration moves the unit's `posture` from `OPERATIONAL` or `WARNING` to `FAILURE` and fires the contingency cascade: every slot of the unit flips from `AVAILABLE` to `OFFLINE`; every `BOOKED` reservation on those slots whose `ends_at` is still in the future is `CANCELLED`; every aliquot housed in the unit's slots and currently `IN_STORAGE` flips to `QUARANTINED`; and every specimen housed in those slots takes `viability_status` `QUARANTINED`.

Return-to-service is the officer-driven recovery. The unit must be in `FAILURE` posture, failing otherwise with `ERR_INVALID_STATE`. Returning a unit flips every `OFFLINE` slot back to `AVAILABLE` and then reviews each `QUARANTINED` aliquot against a hard viability ceiling: if the degree-minute delta the unit accumulated over that aliquot's quarantine window is at most 120 degree-minutes, the aliquot returns to `IN_STORAGE`, and its specimen's `viability_status` returns to `USABLE` once no child aliquot remains quarantined. An aliquot whose quarantine window accumulated more than 120 degree-minutes instead moves to `DESTRUCTION_PENDING`, and the system automatically creates a destruction order for its parent specimen — reason `QUALITY_FAILURE`, creator recorded as "system" — whenever no `PENDING` order already covers that specimen.

### 3.5. Sharing Agreements and the Quota Ledger

Outbound sample distribution is governed by sharing agreements — the material-transfer contracts against which fulfillment charges quota. A `BiobankAdmin` creates an agreement with the `recipient_institution` name, a non-empty `scope_uses` subset of the consent use enum describing what the agreement authorizes, a `total_committed_volume_ml` that must be greater than zero, and the effective window `effective_from` to `effective_to`. New agreements are `DRAFT` with `reserved_volume_ml` and `fulfilled_volume_ml` at zero.

Activation moves an agreement from `DRAFT` to `ACTIVE`. The agreement must be `DRAFT`, failing otherwise with `ERR_INVALID_STATE`, and the current time must be strictly before its `effective_to`, failing otherwise with `ERR_AGREEMENT_NOT_EFFECTIVE` (HTTP 409). Activation initializes the quota ledger by setting `remaining_volume_ml` equal to `total_committed_volume_ml`. From then on the ledger invariant holds at all times: `remaining_volume_ml` is always `total_committed_volume_ml` minus `reserved_volume_ml` minus `fulfilled_volume_ml`, where the reserved figure is quota debited at fulfillment but not yet checked out and the fulfilled figure is quota consumed by completed checkouts. Fulfillment (§3.7) may only draw on an agreement that is `ACTIVE` and whose window currently contains the clock — at or after `effective_from` and strictly before `effective_to` — failing otherwise with `ERR_AGREEMENT_NOT_EFFECTIVE`.

Termination is blocked while quota is still encumbered: terminating requires the agreement to be `ACTIVE` (`ERR_INVALID_STATE` otherwise) and its `reserved_volume_ml` to be exactly zero, failing otherwise with `ERR_AGREEMENT_HAS_ACTIVE_RESERVATIONS` (HTTP 409). A terminated agreement is `TERMINATED`. Independently, the sweep expires an `ACTIVE` agreement once the current time reaches its `effective_to`, moving it to `EXPIRED`. `EXPIRED` and `TERMINATED` are terminal.

### 3.6. Sample Requests and Committee Review

A `Researcher` opens a sample request with a `title`, a non-empty `required_uses` subset of the consent use enum describing what the research will exercise, the desired `specimen_type`, a `volume_needed_ml` greater than zero, and the `sharing_agreement_id` whose quota fulfillment will charge against. At creation the referenced agreement's `scope_uses` must cover every element of `required_uses`, failing otherwise with `ERR_AGREEMENT_SCOPE_INSUFFICIENT` (HTTP 409). The creating user's `X-User-ID` is recorded as `requester_user_id`. A new request is `DRAFT` with `revision_round` at zero and the computed tallies — `votes_for`, `votes_against`, `charged_volume_ml`, `fulfilled_volume_ml`, `handling_fee_cents` — at zero, with `recall_required` false. The request list supports optional `sharing_agreement_id` and `status` filters. Request statuses are `DRAFT`, `UNDER_REVIEW`, `REVISION_REQUESTED`, `APPROVED`, `FULFILLED`, `COMPROMISED`, `REJECTED`, and `CANCELLED`, with the last four terminal.

Submission is the requester's own action, so `X-User-ID` must equal the request's `requester_user_id` or the request fails with `ERR_INSUFFICIENT_PERMISSIONS`. From `DRAFT`, submission moves the request to `UNDER_REVIEW`; any other source state except `REVISION_REQUESTED` fails with `ERR_INVALID_STATE`. From `REVISION_REQUESTED`, resubmission additionally requires `revision_round` to still be below the hard cap of 2 rounds, failing at the cap with `ERR_MAX_REVISION_ROUNDS` (HTTP 409), and increments `revision_round` by one on success.

Once `UNDER_REVIEW`, the committee votes. A `CommitteeReviewer` casts a vote with a `decision` of `APPROVE` or `REJECT` and a free-text `rationale` of at least 20 characters, failing shorter input with `ERR_JUSTIFICATION_TOO_SHORT` (HTTP 400). Four checks guard the ballot, in this order: the request must be `UNDER_REVIEW`, failing as `ERR_REQUEST_NOT_UNDER_REVIEW` (HTTP 409); the reviewer must not be the request's own requester, failing as `ERR_SEGREGATION_OF_DUTIES`; the reviewer must not already have voted on this request in the current review round, failing as `ERR_DUPLICATE_VOTE` (HTTP 409); and the rationale-length rule above. Each vote is an immutable `ReviewVote` record carrying the `sample_request_id` it was cast on and the reviewer's `reviewer_user_id`.

The committee numbers five members and decides by a quorum ratio of 0.6, making the quorum count three — five times 0.6 rounded up. `votes_for` counts `APPROVE` votes and `votes_against` counts `REJECT` votes in the current round. The moment `votes_for` reaches at least 3 the request auto-flips from `UNDER_REVIEW` to `APPROVED`; the moment `votes_against` reaches at least 3 — the committee size minus the quorum count plus one — it auto-flips to `REJECTED`. Both boundaries are inclusive: exactly three approvals approve, exactly three rejections reject.

Alternatively, a reviewer may send the request back for revision. Requesting a revision requires the request to be `UNDER_REVIEW` (`ERR_REQUEST_NOT_UNDER_REVIEW`) and `revision_round` still below 2 (`ERR_MAX_REVISION_ROUNDS`), and takes a `rationale` subject to the same 20-character minimum (`ERR_JUSTIFICATION_TOO_SHORT`). The request moves to `REVISION_REQUESTED`, and the ballot resets — `votes_for` and `votes_against` return to zero — while the prior round's vote records remain stored as immutable history. The per-request vote listing always reflects the current round.

Cancellation belongs to the requester alone (`ERR_INSUFFICIENT_PERMISSIONS` for anyone else). From `DRAFT`, `UNDER_REVIEW`, or `REVISION_REQUESTED` cancellation is a clean move to `CANCELLED`. From `APPROVED`, cancellation additionally performs the release compensation of §3.7: every aliquot `RESERVED` for the request returns to `IN_STORAGE` with its `reserved_for_request_id` cleared, and the agreement's ledger is rebalanced — its `reserved_volume_ml` decreases by the request's `charged_volume_ml` while its `remaining_volume_ml` increases by the same amount.

### 3.7. Fulfillment, Quota Charging, and Checkout

Fulfillment is the `BiobankAdmin`-run allocation that turns an approved request into physical reservations. The request must be `APPROVED`, failing otherwise with `ERR_REQUEST_NOT_APPROVED` (HTTP 409). Fulfillment then evaluates its checks in a fixed order: every candidate's specimen consent must be `ACTIVE` and effective (`ERR_CONSENT_NOT_ACTIVE`); consent scope coverage must hold (`ERR_CONSENT_SCOPE_VIOLATION`, HTTP 403); the linked agreement must be `ACTIVE` and inside its effective window (`ERR_AGREEMENT_NOT_EFFECTIVE`); the eligible inventory must suffice (`ERR_INSUFFICIENT_INVENTORY`); and only then — last among the business rules — the fiscal quota check (`ERR_INSUFFICIENT_QUOTA`).

**Consent scope coverage** is exact set algebra, applied at fulfillment selection and again at checkout: coverage holds when every element of the request's `required_uses` appears in the consent's `permitted_uses` and no element of `required_uses` appears in the consent's `excluded_uses`.

**The selector** is deterministic. An aliquot is eligible when all of the following hold: the aliquot is `IN_STORAGE`; its specimen's `lifecycle_status` is `IN_STORAGE`; the specimen's `viability_status` is `USABLE`; the specimen's `specimen_type` equals the request's `specimen_type`; the specimen's consent is `ACTIVE`; and scope coverage holds for that consent. Eligible aliquots are ranked by their specimen's `collected_at` ascending, ties broken by the aliquot's own `created_at` ascending — never by identifier. The selector accumulates aliquots greedily in ranking order until the cumulative selected volume reaches the request's `volume_needed_ml`. If the entire eligible pool cannot cover `volume_needed_ml`, fulfillment is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 409) and nothing is reserved — partial reservations never happen.

**The quota charge** is computed in a pinned evaluation order once selection succeeds. First, the selected volume is the sum of the selected aliquots' `initial_volume_ml`. Second, the agreement's pre-fulfillment utilization is its `fulfilled_volume_ml` divided by its `total_committed_volume_ml`. Third, the multiplier branch: when that utilization is already at least 0.8 — that is, 80 percent of the contracted total has been consumed — the surcharge multiplier 1.25 applies; otherwise the multiplier is 1.0. Fourth, the raw charge is the selected volume times the multiplier, rounded half-up to 3 decimal places. Fifth, the feasibility gate: if the charge exceeds the agreement's `remaining_volume_ml`, fulfillment is rejected with `ERR_INSUFFICIENT_QUOTA` (HTTP 402) and no partial debit occurs. On success the agreement's `reserved_volume_ml` increases by the charge and its `remaining_volume_ml` decreases by the same amount; the request's `charged_volume_ml` records the charge; and each selected aliquot flips from `IN_STORAGE` to `RESERVED` with `reserved_for_request_id` set to the request.

**The handling fee** is computed alongside the charge, with the rounding order pinned per aliquot: each selected aliquot's fee is 500 cents plus 2.5 cents per milliliter of its `initial_volume_ml`, and each per-aliquot fee is rounded half-up to whole cents first; only then are the rounded lines summed into the request's `handling_fee_cents`. The order matters: two 0.5 ml aliquots produce raw fees of 501.25 cents each, which round to 501 each and sum to 1002, whereas summing the raw fees first would round 1002.5 to 1003 — the former rule is the one in force.

**Checkout** is the physical shipment, performed by a `LabTechnician` who names the `request_id` the aliquot ships against. Two gates precede the listed checks, in this order: a checkout attempted on an aliquot that has already reached a terminal state (`DISTRIBUTED`, `DESTROYED`, or `VOID`) is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409), as the terminal-state rule of §2.6 requires; and the payload's `request_id` must resolve to an existing sample request, failing as `ERR_NOT_FOUND` (HTTP 404). Its checks then run in order: the aliquot must be `RESERVED` and its `reserved_for_request_id` must equal the payload's `request_id`, failing as `ERR_ALIQUOT_NOT_RESERVED_FOR_REQUEST` (HTTP 409); the request must be `APPROVED`, failing as `ERR_REQUEST_NOT_APPROVED`; the specimen's consent must be `ACTIVE`, failing as `ERR_CONSENT_NOT_ACTIVE`; scope coverage must hold against the request's `required_uses`, failing as `ERR_CONSENT_SCOPE_VIOLATION`; and the storage unit housing the aliquot's slot must have `posture` `OPERATIONAL`, failing as `ERR_UNIT_NOT_OPERATIONAL`. A successful checkout moves the aliquot from `RESERVED` to `DISTRIBUTED`, zeroes its `remaining_volume_ml`, clears its `reserved_for_request_id`, and settles the ledger: the agreement's `reserved_volume_ml` decreases by the aliquot's share of the request's charge while its `fulfilled_volume_ml` increases by the same share, and the request's `fulfilled_volume_ml` grows by the aliquot's `initial_volume_ml`. When a checkout brings the request's `fulfilled_volume_ml` to at least its `volume_needed_ml`, the request auto-flips from `APPROVED` to `FULFILLED`.

### 3.8. De-identification Keys and Controlled Re-identification

Every specimen may carry at most one live de-identification key — the coded handle that lets authorized processes link back to donor identity under strict control. A `ConsentCoordinator` mints a key by naming its `specimen_id`; if the specimen already has a key that is not `REVOKED`, creation is rejected with `ERR_KEY_ALREADY_EXISTS` (HTTP 409). Minting generates the server-side `key_code` — an identifier used for identity only, never as an input to any decision — records the creator's `X-User-ID` as `holder_user_id`, sets the key `ACTIVE`, and starts its `reveal_count` at zero. Keys carry no other states: `ACTIVE`, and the terminal `REVOKED`, which a key reaches automatically when its specimen is destroyed, whether through a manual destruction order or the consent-withdrawal cascade. The key list accepts optional `specimen_id` and `status` filters.

Re-identification access is time-boxed through grants. A `ConsentCoordinator` creates a key access grant naming the `grantee_user_id` who may request reveals, the window `starts_at` to `ends_at`, and a free-text `purpose`; the grant references its key via `deidentification_key_id` and starts `ACTIVE`. Grant windows are closed — both the start and the end instant belong to the window — and `ends_at` must be strictly after `starts_at` or the request fails as `ERR_INVALID_REQUEST`. Because the windows are closed, touching endpoints already count as overlap, and the rule goes further: a new grant whose window overlaps an existing grant on the same key, or that leaves a gap of less than 24 hours on either side of an existing grant on the same key, is rejected with `ERR_GRANT_WINDOW_CONFLICT` (HTTP 409). The sweep moves a grant from `ACTIVE` to `EXPIRED` once the current time is strictly later than its `ends_at`; `EXPIRED` is terminal.

The reveal itself is a `QualityOfficer` action taking the `grant_id` under which the reveal is requested and a free-text `justification`. Its checks run in a fixed order. First, dual control: the revealing officer's `X-User-ID` must differ from the named grant's `grantee_user_id`, failing as `ERR_SEGREGATION_OF_DUTIES`. Second, the `justification` must be at least 20 characters, failing as `ERR_JUSTIFICATION_TOO_SHORT`. Third, the terminal gate: the key must be `ACTIVE` (failing otherwise with `ERR_KEY_NOT_ACTIVE`, HTTP 409), there must exist an `ACTIVE` grant on this key whose closed window contains the current time, and the consent under which the specimen was collected must have `allow_reidentification` set to true — failures of these reveal preconditions surface as `ERR_NO_ACTIVE_GRANT` (HTTP 403). A successful reveal increments the key's `reveal_count` by one.

### 3.9. Consent Withdrawal Cascade and Specimen Destruction

The grace period of §3.1 ends in the sweep. When the due-date sweep finds a `WITHDRAWAL_PENDING` consent whose `grace_deadline` is at or before the current time, it finalizes the withdrawal: the consent moves to `WITHDRAWN`, its `version` increments by one, and a three-depth cascade fires.

- **Depth 1 — specimens.** Every specimen of the consent's donor whose `lifecycle_status` is `ACCESSIONED` or `IN_STORAGE` flips to `DESTRUCTION_PENDING`, and one destruction order is auto-created per such specimen: reason `CONSENT_WITHDRAWAL`, `created_by_user_id` recorded as "system", and `consent_record_id` set to the withdrawn consent.
- **Depth 2 — aliquots and keys.** Every aliquot of those specimens whose status is `IN_STORAGE`, `RESERVED`, or `QUARANTINED` flips to `DESTRUCTION_PENDING`, and every `ACTIVE` de-identification key referencing an affected specimen flips to `REVOKED`.
- **Depth 3 — requests and agreements.** For each flipped aliquot that had been `RESERVED`, the reserving sample request flips from `APPROVED` to `COMPROMISED`, and its sharing agreement's ledger is rebalanced as release compensation — `reserved_volume_ml` decreases by that request's `charged_volume_ml` while `remaining_volume_ml` increases by the same amount. Separately, for each sample request that already has an aliquot of the affected specimens in `DISTRIBUTED` status, the request's `recall_required` flag is set to true; the request itself stays `APPROVED` or `FULFILLED`.

Destruction orders are the auditable instrument that actually destroys material. Beyond the sweep-created orders above, a `QualityOfficer` may create one manually by naming the target `specimen_id` and a `reason` of `CONSENT_WITHDRAWAL`, `QUALITY_FAILURE`, or `OTHER`; manual orders leave `consent_record_id` null and record the creator's `X-User-ID` as `created_by_user_id`. Creating an order — manual or automatic — flips the target specimen to `DESTRUCTION_PENDING` (a specimen may enter this state from `ACCESSIONED` or `IN_STORAGE` alike), flips every child aliquot in `IN_STORAGE`, `RESERVED`, or `QUARANTINED` to `DESTRUCTION_PENDING` as well, and sets the order's `due_at` to exactly 48 hours after its creation. A new order is `PENDING`; `COMPLETED` is its only other state and is terminal. The order list accepts optional `consent_record_id`, `specimen_id`, and `status` filters.

Confirming execution is the second half of the segregated control. A `QualityOfficer` confirms a `PENDING` order — any other status fails with `ERR_DESTRUCTION_ORDER_NOT_CONFIRMABLE` (HTTP 409) — and the confirming officer must not be the order's creator, failing with `ERR_SEGREGATION_OF_DUTIES`; the state check precedes the segregation check. Confirmation records the officer as `confirmed_by_user_id`, computes `completed_late` as true exactly when the confirmation time is strictly later than `due_at` (confirmation precisely at the deadline counts as on time), moves the order to `COMPLETED`, and finishes the destruction: the specimen flips from `DESTRUCTION_PENDING` to `DESTROYED`, every child aliquot in `DESTRUCTION_PENDING` flips to `DESTROYED` with its `remaining_volume_ml` zeroed, and each `ACTIVE` de-identification key of the specimen flips to `REVOKED`.

## 4. Endpoint Definitions

Operations that create a new resource — whether a stand-alone record or a new member of a parented collection — return `201 Created`. Operations that act on an existing resource without creating a new one return `200 OK`. Request payloads, response contents, and side effects are defined by the workflows of §3; the table below is the routing contract only. "Any" in the role column means all six roles of §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | BiobankAdmin |
| POST | `/biobank/sweeps/process-due` | Run the due-date sweep | BiobankAdmin |
| POST | `/biobank/donors` | Register a donor | ConsentCoordinator |
| GET | `/biobank/donors/{donorId}` | Get a donor | Any |
| POST | `/biobank/donors/{donorId}/consent-records` | File a consent record for a donor | ConsentCoordinator |
| GET | `/biobank/consent-records` | List consent records with optional filters | Any |
| GET | `/biobank/donors/{donorId}/consent-records` | List consent records of a donor | Any |
| GET | `/biobank/consent-records/{consentId}` | Get a consent record | Any |
| POST | `/biobank/consent-records/{consentId}/withdraw` | Initiate consent withdrawal | ConsentCoordinator |
| POST | `/biobank/consent-records/{consentId}/rescind-withdrawal` | Rescind a pending withdrawal | ConsentCoordinator |
| POST | `/biobank/consent-records/{consentId}/amendments` | File a superseding amendment (OCC-guarded) | ConsentCoordinator |
| POST | `/biobank/collection-kits` | Register a collection kit into stock | ConsentCoordinator |
| GET | `/biobank/collection-kits` | List collection kits with optional filters | Any |
| GET | `/biobank/collection-kits/{kitId}` | Get a collection kit | Any |
| POST | `/biobank/collection-kits/{kitId}/distribute` | Distribute a kit to a donor | ConsentCoordinator |
| POST | `/biobank/collection-kits/{kitId}/receive-return` | Receive a kit back | ConsentCoordinator |
| GET | `/biobank/collection-kits/{id}/custody-events` | List custody events of a kit | Any |
| POST | `/biobank/specimens` | Accession a specimen from a returned kit | LabTechnician |
| GET | `/biobank/specimens` | List specimens with optional filters | Any |
| GET | `/biobank/specimens/{specimenId}` | Get a specimen | Any |
| POST | `/biobank/specimens/{specimenId}/aliquots` | Create an aliquot (OCC-guarded) | LabTechnician |
| GET | `/biobank/specimens/{specimenId}/aliquots` | List aliquots of a specimen | Any |
| GET | `/biobank/aliquots` | List aliquots with optional filters | Any |
| GET | `/biobank/aliquots/{aliquotId}` | Get an aliquot | Any |
| POST | `/biobank/aliquots/{aliquotId}/void` | Void an in-storage aliquot | LabTechnician |
| POST | `/biobank/aliquots/{aliquotId}/checkout` | Ship a reserved aliquot against its request | LabTechnician |
| POST | `/biobank/storage-units` | Register a freezer | BiobankAdmin |
| GET | `/biobank/storage-units/{unitId}` | Get a storage unit | Any |
| POST | `/biobank/storage-units/{id}/slots` | Define a storage slot in a unit | BiobankAdmin |
| GET | `/biobank/storage-units/{id}/slots` | List slots of a unit | Any |
| GET | `/biobank/storage-slots/{slotId}` | Get a storage slot | Any |
| POST | `/biobank/storage-slots/{id}/reservations` | Book a slot reservation window | LabTechnician |
| GET | `/biobank/storage-slots/{id}/reservations` | List reservations of a slot | Any |
| POST | `/biobank/storage-units/{id}/temperature-readings` | Ingest a temperature reading | LabTechnician |
| GET | `/biobank/storage-units/{id}/temperature-readings` | List readings of a unit | Any |
| POST | `/biobank/storage-units/{unitId}/declare-failure` | Declare freezer failure | QualityOfficer |
| POST | `/biobank/storage-units/{unitId}/return-to-service` | Return a failed freezer to service | QualityOfficer |
| POST | `/biobank/sample-requests` | Create a sample request | Researcher |
| GET | `/biobank/sample-requests` | List sample requests with optional filters | Any |
| GET | `/biobank/sample-requests/{requestId}` | Get a sample request | Any |
| POST | `/biobank/sample-requests/{requestId}/submit` | Submit for committee review | Researcher |
| POST | `/biobank/sample-requests/{id}/votes` | Cast a committee vote | CommitteeReviewer |
| GET | `/biobank/sample-requests/{id}/votes` | List votes of the current review round | Any |
| POST | `/biobank/sample-requests/{requestId}/request-revision` | Send the request back for revision | CommitteeReviewer |
| POST | `/biobank/sample-requests/{requestId}/fulfill` | Allocate aliquots and charge quota | BiobankAdmin |
| POST | `/biobank/sample-requests/{requestId}/cancel` | Cancel own request, releasing reservations | Researcher |
| POST | `/biobank/sharing-agreements` | Create a sharing agreement | BiobankAdmin |
| GET | `/biobank/sharing-agreements/{agreementId}` | Get a sharing agreement | Any |
| POST | `/biobank/sharing-agreements/{agreementId}/activate` | Activate an agreement | BiobankAdmin |
| POST | `/biobank/sharing-agreements/{agreementId}/terminate` | Terminate an agreement | BiobankAdmin |
| POST | `/biobank/deidentification-keys` | Mint a de-identification key | ConsentCoordinator |
| GET | `/biobank/deidentification-keys` | List de-identification keys with optional filters | Any |
| GET | `/biobank/deidentification-keys/{keyId}` | Get a de-identification key | Any |
| POST | `/biobank/deidentification-keys/{id}/grants` | Grant time-boxed re-identification access | ConsentCoordinator |
| GET | `/biobank/deidentification-keys/{id}/grants` | List access grants of a key | Any |
| POST | `/biobank/deidentification-keys/{keyId}/reveal` | Re-identify a specimen under an active grant | QualityOfficer |
| POST | `/biobank/destruction-orders` | Manually create a destruction order | QualityOfficer |
| GET | `/biobank/destruction-orders` | List destruction orders with optional filters | Any |
| GET | `/biobank/destruction-orders/{orderId}` | Get a destruction order | Any |
| POST | `/biobank/destruction-orders/{orderId}/confirm-execution` | Confirm destruction execution | QualityOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_CONSENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_CONSENT_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_WITHDRAWAL_GRACE_EXPIRED` | 409 Conflict |
| `ERR_KIT_NOT_DISTRIBUTABLE` | 409 Conflict |
| `ERR_KIT_NOT_RETURNED` | 409 Conflict |
| `ERR_KIT_EXPIRED` | 409 Conflict |
| `ERR_DONOR_MISMATCH` | 400 Bad Request |
| `ERR_SPECIMEN_NOT_ALIQUOTABLE` | 409 Conflict |
| `ERR_INSUFFICIENT_SPECIMEN_VOLUME` | 422 Unprocessable Entity |
| `ERR_ALIQUOT_NOT_RESERVED_FOR_REQUEST` | 409 Conflict |
| `ERR_UNIT_NOT_OPERATIONAL` | 409 Conflict |
| `ERR_SLOT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_SLOT_RESERVATION_OVERLAP` | 409 Conflict |
| `ERR_GRANT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_NO_ACTIVE_GRANT` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_DUPLICATE_VOTE` | 409 Conflict |
| `ERR_REQUEST_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_REQUEST_NOT_APPROVED` | 409 Conflict |
| `ERR_MAX_REVISION_ROUNDS` | 409 Conflict |
| `ERR_AGREEMENT_NOT_EFFECTIVE` | 409 Conflict |
| `ERR_AGREEMENT_SCOPE_INSUFFICIENT` | 409 Conflict |
| `ERR_INSUFFICIENT_QUOTA` | 402 Payment Required |
| `ERR_INSUFFICIENT_INVENTORY` | 409 Conflict |
| `ERR_AGREEMENT_HAS_ACTIVE_RESERVATIONS` | 409 Conflict |
| `ERR_DESTRUCTION_ORDER_NOT_CONFIRMABLE` | 409 Conflict |
| `ERR_INVALID_TEMPERATURE_READING` | 400 Bad Request |
| `ERR_JUSTIFICATION_TOO_SHORT` | 400 Bad Request |
| `ERR_KEY_NOT_ACTIVE` | 409 Conflict |
| `ERR_KEY_ALREADY_EXISTS` | 409 Conflict |
