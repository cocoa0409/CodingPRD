# E-Waste & Electronics Recycling (ITAD) API — Product Requirements Document

## 1. Introduction

Corporate IT departments retire laptops, servers, phones, and batteries in bulk, and every one of those assets carries two kinds of residual value: the recoverable resale or refurbishment value of the hardware, and the liability value of the data still on its storage. An IT Asset Disposition (ITAD) operation exists to convert the first into revenue while provably eliminating the second, under the gaze of downstream certification schemes such as R2 and e-Stewards. This document specifies the API of a platform that runs such an operation end to end: business customers open accounts, declare pickup or drop-off manifests, and watch each scanned asset travel a documented chain of custody from facility intake, through data sanitization and triage, to resale, downstream certified recycling, and final settlement.

The platform's obligations are deliberately asymmetrical. On the compliance side it must enforce segregation of duties between the technician who wipes a device and the officer who verifies the wipe, refuse export shipments when the active policy forbids them, never route an asset to a recycler whose certification has lapsed or whose daily intake capacity would be exceeded, and issue tamper-evident certificates of data destruction and recycling. On the commercial side it must value assets twice — once as a provisional quote and once as a realized final settlement — charge tiered recycling and sanitization fees, apply volume rebates, post every monetary movement to a per-account ledger, and reward high-volume customers with automatic tier upgrades that lower the commission charged on resale proceeds. Because sustainability reporting is increasingly a contractual deliverable, the API also computes per-account diversion metrics directly from operational data.

Everything in the system is anchored to a logical clock rather than the host's wall clock, so that certification-expiry checks, scheduling windows, and score computations are deterministic and testable. All API traffic is mounted under the `/itad` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The platform recognizes six roles, spelled exactly as follows: `PlatformAdmin`, `ComplianceOfficer`, `AccountManager`, `IntakeOperator`, `DestructionTechnician`, and `LogisticsCoordinator`. A request arriving without these headers, or carrying a role string that is not one of the six declared roles, is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the named role is not permitted on the targeted endpoint, the request is rejected with `ERR_UNAUTHORIZED`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `AccountManager`, `X-User-ID` is the `id` of the acting **BusinessAccount**; ownership checks on any resource that references a BusinessAccount compare the resource's foreign-key field to `X-User-ID`, so an account manager may create and amend manifests only for its own account (`account_id` equal to `X-User-ID`) and may touch resources beneath it only when the owning manifest's `account_id` equals `X-User-ID`. A violation of this ownership rule is rejected with `ERR_UNAUTHORIZED`. When `X-User-Role` is `PlatformAdmin`, `ComplianceOfficer`, `IntakeOperator`, `DestructionTechnician`, or `LogisticsCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `logged_by_id` on a sanitization record, `verified_by_id` on a verification, `actor_id` on a custody event, or `issued_by_id` on a certificate — but does not compare it to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it is read from the host wall clock, whereas the persisted resource timestamps of §2.4 read the logical clock of §2.9.
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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside that range, or a negative `offset` is rejected with `ERR_VALIDATION`.

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order; resources sharing the same `created_at` instant are ordered by creation sequence.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope; `has_more` is true exactly when `offset` plus the number of returned items is less than `total_count`.

### 2.4. Resource Identity and Common Properties

Every primary resource — BusinessAccount, Recycler, CompliancePolicy, Manifest, Item, DataSanitization, ResaleListing, RecycleBatch, Certificate, and Settlement — carries a standard set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a bare UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it refreshes on every change to the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by one on every mutation of the resource.

Recomputing a derived field on a resource — for example refreshing a manifest's scanned-item count when a new item is scanned in, or recomputing a batch's totals when an item is added — is itself a mutation of that resource and therefore refreshes its `updated_at` and increments its `version`. Two entity kinds are deliberately leaner: **CustodyEvent** and **LedgerEntry** are append-only records that carry only `id` and `created_at`; both `updated_at` and `version` are absent on them, because they are never modified after being written.

### 2.5. Nested Resource Retrieval and Existence Ordering

Requests that target nested resources are validated strictly left to right along the path. The server resolves each path identifier in turn — account, then manifest, then item, then batch, then settlement, then listing, then sanitization, then certificate, then recycler, in whatever subset the path contains — and rejects the request at the first identifier that does not resolve, before examining anything to its right. Each unresolved identifier maps to its own dedicated error: `ERR_ACCOUNT_NOT_FOUND`, `ERR_MANIFEST_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_SANITIZATION_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, and `ERR_RECYCLER_NOT_FOUND`, all returned as 404. A request to scan an item under a manifest that does not exist, for instance, fails with `ERR_MANIFEST_NOT_FOUND` regardless of what the item payload contains. Identifiers carried in the request body rather than the path — `item_id` on listing creation and on batch-item addition, and `recycler_id` on batch creation — are resolved immediately after body validation and before any state or policy gate, each unresolved value mapping to its own dedicated error from the family above.

### 2.6. Validation Order of Evaluation

When several checks could reject the same request, the server evaluates them in a fixed priority order so that the surfaced error is deterministic. The ordering, from earliest to latest, is:

1. Authentication context — missing or invalid headers yield `ERR_UNAUTHENTICATED`.
2. Role authorization — a role not listed for the endpoint yields `ERR_UNAUTHORIZED`.
3. Path existence, left to right as described in §2.5 — the `ERR_*_NOT_FOUND` family.
4. Account-manager ownership — an `AccountManager` touching another account's resource yields `ERR_UNAUTHORIZED`.
5. Request body schema — missing required fields, type mismatches, invalid enum members, a `weight_kg` that is not greater than zero, a `declared_item_count` below one, an `asking_price_cents` below `floor_price_cents`, a missing `pickup_route` on a `PICKUP` manifest (or one supplied on `DROPOFF`), or a `scheduled_end` that is not strictly after `scheduled_start` all yield `ERR_VALIDATION`.
6. Optimistic concurrency — a stale `expected_manifest_version` yields `ERR_STALE_VERSION` (see §2.8).
7. Generic transition state preconditions — the target resource is not in the state the transition starts from, or is in a terminal state, yielding `ERR_INVALID_STATE`.
8.–11. Specialized state gates, in this order: `ERR_BATCH_NOT_STAGING`, then `ERR_MANIFEST_NOT_RECEIVED`, then `ERR_LISTING_NOT_ACTIVE`, then `ERR_SETTLEMENT_NOT_FINALIZED`.
12. Segregation of duties on sanitization verification — `ERR_SEGREGATION_OF_DUTIES`.
13. The data-sanitization gate — `ERR_DATA_SANITIZATION_UNVERIFIED`.
14. The export ban — `ERR_EXPORT_NOT_ALLOWED`.
15. The allowed-method check — `ERR_SANITIZATION_METHOD_NOT_ALLOWED`.
16. Account activity — `ERR_ACCOUNT_SUSPENDED`.
17. Recycler category support — `ERR_RECYCLER_CATEGORY_UNSUPPORTED`.
18. Recycle routing — `ERR_ITEM_NOT_RECYCLE_ROUTED`.
19. The settlement-finality guard — `ERR_SETTLEMENT_ALREADY_FINALIZED`.
20. Selector pool emptiness — `ERR_NO_ELIGIBLE_RECYCLER`.
21.–24. Temporal checks, in this order: `ERR_WINDOW_IN_PAST`, then `ERR_ROUTE_WINDOW_CONFLICT`, then `ERR_RECYCLER_CERT_EXPIRED`, then `ERR_RECYCLER_DAILY_CAPACITY_EXCEEDED`.
25.–31. Business constraints, in this order: `ERR_MANIFEST_EMPTY`, `ERR_MANIFEST_ITEM_COUNT_MISMATCH`, `ERR_MANIFEST_HAS_ITEMS`, `ERR_BATCH_EMPTY`, `ERR_FINALIZE_ITEMS_PENDING`, `ERR_CLOSE_SETTLEMENT_UNPAID`, and finally the fiscal check `ERR_FLOOR_PRICE_VIOLATION`.

Endpoint-specific consequences of this ordering — which of these checks actually guard a given workflow — are restated in §3 alongside each workflow.

### 2.7. Monetary, Weight, and Score Precision

All monetary amounts are represented as integer cents; there are no fractional cents anywhere in the API. Whenever a monetary formula produces a fractional intermediate, it is rounded using the round-half-up method. Settlement computations follow a pinned round-then-sum order: every per-line amount is rounded half-up to whole cents first, and only then are the rounded lines summed into totals.

Weights are handled at three decimal places: an item's `weight_kg` accepts up to three decimal places on input, batch gross weights are summed at three decimal places, and lifetime diversion thresholds are compared at three decimal places. Scores and percentage rates — the recycler risk score and the sustainability diversion rate — are rounded half-up to two decimal places.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both are guarded against the manifest's version.

Amending a DRAFT manifest requires the request to carry `expected_manifest_version` holding the manifest `version` the client last observed. If the manifest's current `version` no longer equals the supplied value — because another writer has advanced it since the client's read — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), rather than silently overwriting a change the client never saw. The same rule guards quote creation: creating a QUOTE settlement against a manifest requires `expected_manifest_version` matching the manifest's current `version`, and a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), so the figures in the new quote are always computed against a manifest the client has actually observed. No other endpoint accepts a version field.

### 2.9. The Logical Clock

All temporal validation and all time-dependent computation in the platform read a single logical clock. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any explicit set call it continues to read that default; it never falls back to wall-clock time. An admin-only test-driving capability, `POST /itad/_clock/set_current_utc`, sets the logical clock to a supplied `to_iso8601` instant — including one earlier than the current reading — and returns the resulting `current_utc`. Scheduling windows, certification-expiry checks, and the day arithmetic inside the recycler risk score all evaluate against this clock.

### 2.10. Chain-of-Custody Audit Trail

Every physical movement of material through the platform is recorded on an append-only custody trail. Each entry on the trail is polymorphic: its `subject_type` is one of `MANIFEST`, `ITEM`, or `BATCH`, and its `subject_id` is interpreted according to that type rather than as a foreign key to a single entity kind. The `event_type` is one of `RECEIVED_FACILITY`, `TRANSFERRED`, `SHIPPED_DOWNSTREAM`, `DELIVERED_DOWNSTREAM`, or `PROCESSED`. Entries may carry free-text `from_location` and `to_location` fields, and every entry records the acting operator's `X-User-ID` as `actor_id`. Custody entries are written automatically by the workflows in §3 — facility receipt, batch transfer, downstream shipment, downstream delivery acknowledgment, and processing completion — and the trail is queryable by `subject_type` and `subject_id`, ordered by `created_at` ascending. Both query parameters are required; a missing `subject_id` or a `subject_type` outside the three declared values is rejected with `ERR_VALIDATION`. An `AccountManager` querying a `MANIFEST` or `ITEM` subject that resolves to another account is rejected with `ERR_UNAUTHORIZED`; `BATCH` subjects and unresolvable identifiers are not ownership-checked. Entries are never updated or deleted.

### 2.11. Compliance Policy Activation

The platform's compliance behavior is parametrized by CompliancePolicy records, and exactly one policy is active platform-wide at any moment. A policy declares the certification `standard` it parametrizes (`R2` or `E_STEWARDS`), the `sanitization_methods_allowed` while it is active, whether downstream `export_allowed` shipments are permitted (under an e-Stewards-style policy this is false), whether `resale_requires_verified_sanitization` is enforced, and the three selector weights `weight_cert_freshness`, `weight_volume`, and `weight_violations`, each between zero and one inclusive. Creating a policy with `is_active` set to true atomically deactivates every other policy; a policy created with `is_active` false (the default) leaves the current activation untouched. Where no policy is active, the resale data gate behaves as if verified sanitization were required — the strict reading is the default.

## 3. Business Logic & Workflows

### 3.1. Business Accounts and Tier Progression

Everything begins with a **BusinessAccount**, opened by a `PlatformAdmin` with the customer's legal `company_name` and primary `contact_email`. The account's `tier` may be supplied at creation and otherwise defaults to `STANDARD`; the recognized tiers are `STANDARD`, `VOLUME`, and `ENTERPRISE`. A new account starts with `status` `ACTIVE`, a `credit_balance_cents` of zero, and a `lifetime_diverted_kg` of zero. The credit balance is never written directly: it is the running sum of every ledger `amount_cents` posted to the account, and a positive balance means the platform owes the customer money. Reading an account returns both computed figures.

Tiers are earned, not assigned. Each time one of the account's items reaches its terminal completion — whether by being sold and finalized or by being processed downstream — the item's `weight_kg` is added to `lifetime_diverted_kg`, and the accumulation is compared against two thresholds at three-decimal precision: at least 1000 kg promotes the account to `VOLUME`, and at least 5000 kg promotes it to `ENTERPRISE`, with both boundaries inclusive so that exactly 1000.0 kg is enough for `VOLUME`. The account's tier becomes whichever of its current tier and the threshold-implied tier ranks higher in the order `STANDARD` below `VOLUME` below `ENTERPRISE`; a tier is never demoted by this mechanism. Tier membership has a direct commercial consequence described in §3.6: enterprise accounts pay a lower commission on resale.

A `PlatformAdmin` may also update an account's `tier` directly through the same account-update operation that drives status changes — a request carrying neither `tier` nor `status` is rejected with `ERR_VALIDATION` — and any such amendment refreshes `updated_at` and increments the account's `version`. Separately, a `PlatformAdmin` may suspend an account, moving `status` from `ACTIVE` to `SUSPENDED`. Suspension blocks new manifest creation and the scheduling of drafts against that account with `ERR_ACCOUNT_SUSPENDED`, while manifests already in flight are unaffected. Suspension is reversible — the account returns from `SUSPENDED` to `ACTIVE` — and either change increments the account's `version`. Closing an account is permanent and deliberately hard: the transition from `ACTIVE` to `CLOSED` is refused with `ERR_INVALID_STATE` unless every manifest of the account is already `CLOSED` or `CANCELLED` and the `credit_balance_cents` is exactly zero, so a customer cannot be closed out while money or material is still unresolved.

### 3.2. Compliance Policies and the Certified Recycler Registry

Downstream material may only flow to recyclers the platform has vetted. A `ComplianceOfficer` registers each downstream partner as a **Recycler** with its legal `name`, the `certification_standard` it is audited under (`R2` or `E_STEWARDS`), the `certification_expires_at` instant at which that certification lapses, the non-empty `accepted_categories` subset of the eight device categories it accepts (`LAPTOP`, `DESKTOP`, `SERVER`, `PHONE`, `TABLET`, `MONITOR`, `BATTERY`, `OTHER`), and the `daily_intake_capacity_kg` it can absorb per calendar delivery day, which must be a number greater than zero (`ERR_VALIDATION` otherwise). Registration may also record a `violation_count` of known downstream compliance violations, a non-negative integer defaulting to zero; only the range from zero to ten influences scoring. Two figures are computed for each recycler: `total_processed_kg`, the sum of gross weight over all of its batches that have reached `PROCESSED`, and `risk_score`, the selection score described next.

The risk score blends three components using the weights of the currently active compliance policy. First, certification freshness: the number of whole days from the current logical clock to `certification_expires_at` — computed as the floor of the seconds between them divided by 86400, and allowed to go negative once the certification has lapsed — is divided by 365 and then clamped into the range from zero to one. Second, processed volume: `total_processed_kg` divided by 10000, clamped to a maximum of one. Third, violation-freeness: one minus `violation_count` divided by ten, clamped to a minimum of zero. The weighted sum of the three components — using `weight_cert_freshness`, `weight_volume`, and `weight_violations` from the active policy — is multiplied by 100 and rounded half-up to two decimal places to produce the `risk_score`. When no policy is active, `risk_score` is null. Because the weights come from the active policy, switching the policy re-ranks the fleet: an R2-style weighting such as 0.5, 0.2, and 0.3 lets certification freshness dominate, while an e-Stewards-style weighting such as 0.3, 0.2, and 0.5 lets the violation-free record dominate, and identical recycler statistics can produce a different winner under the two regimes.

When a batch is created without an explicit recycler, the selector policy chooses among the eligible recyclers — those whose `certification_expires_at` is strictly after the requested delivery date, expiry being exclusive — ranks them by `risk_score` descending, breaks ties by `total_processed_kg` descending and then by `created_at` ascending (never by identifier; equal instants fall back to creation sequence), and assigns the winner. If no recycler's certification is strictly valid on the requested date, creation fails with `ERR_NO_ELIGIBLE_RECYCLER`.

### 3.3. Manifest Intake: From Draft to Reconciled

A customer shipment enters the system as a **Manifest**, created by an `AccountManager` against its own account; attempting to open a manifest for a different account is an ownership violation rejected with `ERR_UNAUTHORIZED`. Creation captures the `account_id`, the `mode` — `PICKUP` when the platform collects, `DROPOFF` when the customer delivers — the `pickup_route` identifier, the appointment window `scheduled_start` and `scheduled_end`, and the customer-declared `declared_item_count`, an integer of at least one. A `pickup_route` is required exactly when the mode is `PICKUP` and must be absent of meaning otherwise, `scheduled_end` must be strictly after `scheduled_start` whenever both are supplied, and violations of these body rules surface as `ERR_VALIDATION`. The account must be `ACTIVE`, or creation fails with `ERR_ACCOUNT_SUSPENDED`; on the creation path the ownership check runs first, then body validation, then resolution of the target account (`ERR_ACCOUNT_NOT_FOUND`), then the account-activity check. A new manifest is `DRAFT`, with `received_item_count` zero and `discrepancy_flag` false; the flag simply records whether `received_item_count` differs from `declared_item_count`.

While the manifest remains `DRAFT`, the account manager may amend its `pickup_route`, `scheduled_start`, `scheduled_end`, or `declared_item_count`. The window-pair and route-mode rules of creation are re-validated against the effective merged values before the concurrency check, violations surfacing as `ERR_VALIDATION`. Amendments run under the optimistic-concurrency rule of §2.8: the request must carry `expected_manifest_version`, and a stale value is rejected with `ERR_STALE_VERSION`.

Scheduling is performed by a `LogisticsCoordinator` and moves the manifest `DRAFT` → `SCHEDULED`. The guard chain runs in a fixed order: the manifest must actually be in `DRAFT` (otherwise `ERR_INVALID_STATE`); the owning account must be `ACTIVE` (`ERR_ACCOUNT_SUSPENDED`); both `scheduled_start` and `scheduled_end` must be set (`ERR_VALIDATION`); the window's `scheduled_end` must lie strictly after the current logical clock (`ERR_WINDOW_IN_PAST`); and, for `PICKUP` manifests only, the half-open window from `scheduled_start` up to but not including `scheduled_end` must not overlap the window of any other manifest on the same `pickup_route` that is currently `SCHEDULED` or `RECEIVED` (`ERR_ROUTE_WINDOW_CONFLICT`). Because windows are half-open, pure adjacency — one route window ending exactly when the next begins — is allowed and is not a conflict.

Receipt at the facility is recorded by an `IntakeOperator`, moving the manifest `SCHEDULED` → `RECEIVED` and writing a custody entry whose `subject_type` is `MANIFEST` and whose `event_type` is `RECEIVED_FACILITY`. Items are then scanned in (§3.4), and once scanning and triage are complete the intake operator reconciles the manifest, moving it `RECEIVED` → `RECONCILED`. Reconciliation enforces its checks in order: the manifest must be in `RECEIVED`; no item of the manifest may still sit in `INTAKE` — both violations surface as `ERR_INVALID_STATE`, and both run before the count checks; then at least one item must have been scanned (`ERR_MANIFEST_EMPTY`); and finally the scanned count must equal the declared count (`ERR_MANIFEST_ITEM_COUNT_MISMATCH`). Every one of these transitions — schedule, receive, reconcile, and the terminal ones below — increments the manifest's `version` by one and refreshes `updated_at`.

Two terminal outcomes exist. Cancellation by an `AccountManager` is available from either `DRAFT` or `SCHEDULED`, but only while nothing has been scanned: once `received_item_count` is non-zero, cancellation is rejected with `ERR_MANIFEST_HAS_ITEMS`. Closure by an `AccountManager` is available from `RECONCILED`, and only after the money has settled: at least one settlement must exist for the manifest, and every settlement that has not been superseded must be `PAID` or `VOIDED`, otherwise the close is rejected with `ERR_CLOSE_SETTLEMENT_UNPAID`. `CLOSED` and `CANCELLED` are terminal; a terminal manifest rejects every further transition with `ERR_INVALID_STATE`.

### 3.4. Item Scanning, Triage, and Routing

Each physical asset becomes an **Item** when an `IntakeOperator` scans it into a manifest, which is permitted while the manifest is `DRAFT` and again while it is `RECEIVED`; the scanned record carries the owning manifest's identity as its `manifest_id`. Scanning captures the asset's `serial_number` — unique within its manifest, a duplicate surfacing as `ERR_VALIDATION` — its `category` (one of `LAPTOP`, `DESKTOP`, `SERVER`, `PHONE`, `TABLET`, `MONITOR`, `BATTERY`, `OTHER`), its `weight_kg` (greater than zero, up to three decimal places), two booleans `data_bearing` (the device carries storage requiring sanitization) and `hazmat_flag` (hazardous material such as batteries or CRT glass, which attracts a flat surcharge at settlement), and a `declared_grade` of `A`, `B`, `C`, or `D` used by quote valuation. A freshly scanned item has `disposition` `NONE`, `processing_status` `INTAKE`, and zero `provisional_value_cents` and `final_value_cents`, and its parallel `data_status` dimension initializes to `PENDING` when the device is data-bearing and to `NOT_REQUIRED` otherwise. Each scan recomputes the manifest's `received_item_count` — and with it `discrepancy_flag` — and increments the manifest's `version`.

An item carries two independent state dimensions from this point on. The physical dimension, `processing_status`, walks among `INTAKE`, `FOR_RESALE`, `FOR_REFURB`, `FOR_RECYCLE`, `LISTED`, `SOLD`, `BATCHED`, `DOWNSTREAM`, and the terminal `COMPLETE`. The data dimension, `data_status`, walks `PENDING` → `SANITIZED` → `VERIFIED` under sanitization and verification (§3.5), and slides back to `PENDING` when a verification is rejected. The two dimensions interact at exactly the gates the compliance regime cares about: listing for resale and batching for recycling both require the data dimension to be in `NOT_REQUIRED` or `VERIFIED`, with the finer listing rules spelled out in §3.6.

Triage is the routing decision, taken by an `IntakeOperator` with a target `disposition`. Every triage call requires the owning manifest to be `RECEIVED`, and is rejected with `ERR_MANIFEST_NOT_RECEIVED` otherwise. From `INTAKE`, an item may be routed to `FOR_RESALE`, `FOR_REFURB`, or `FOR_RECYCLE`; rerouting is allowed from `FOR_REFURB` to `FOR_RESALE` (refurbishment passed QA and the asset is worth selling as-is), from `FOR_REFURB` to `FOR_RECYCLE` (refurbishment proved uneconomical), and from `FOR_RESALE` to `FOR_RECYCLE` (resale abandoned). Routing writes the `disposition` — `RESALE`, `REFURB`, or `RECYCLE` — and recomputes `provisional_value_cents`: resale- and refurbishment-routed items are re-estimated under the quote valuation of §3.8, while recycle-routed items carry a provisional value of exactly zero. Each triage transition increments the item's `version`. While triaged for recycling, an item carries a `recycle_batch_id` only once it has been placed into a batch; the field is null outside the `BATCHED` and `DOWNSTREAM` states.

### 3.5. Data Sanitization and Destruction Certification

Data-bearing devices may not leave the facility — for resale or for recycling — until their storage has been provably sanitized. A `DestructionTechnician` logs each sanitization attempt against a triaged data-bearing item — that is, any item that has left `INTAKE`, whatever its later processing state; an item still in `INTAKE` is rejected with `ERR_INVALID_STATE`, and a non-data-bearing item with `ERR_VALIDATION`, in that order — supplying the `method` — one of `CRYPTO_ERASE`, `NIST_CLEAR`, `NIST_PURGE`, or `PHYSICAL_DESTROY` — and the technician-reported `outcome`, `PASS` or `FAIL`. The chosen method must appear in the active compliance policy's `sanitization_methods_allowed`; a method outside the policy is refused with `ERR_SANITIZATION_METHOD_NOT_ALLOWED`. When no policy is active, every method is allowed. A logged attempt starts in `LOGGED` status with `logged_by_id` recorded from the technician's `X-User-ID`; when the outcome is `PASS` the item's `data_status` advances to `SANITIZED`, while a `FAIL` outcome leaves it at `PENDING`.

Verification belongs to a different pair of hands. A `ComplianceOfficer` reviews a `LOGGED` record by submitting a `verdict` of `APPROVE` or `REJECT`; a record in any other state refuses the transition with `ERR_INVALID_STATE`. Segregation of duties is enforced before the verdict itself is considered: the verifier's `X-User-ID` must differ from the record's `logged_by_id`, and a technician attempting to verify their own work — or an officer verifying a record they themselves logged — is rejected with `ERR_SEGREGATION_OF_DUTIES`. On `APPROVE`, the attempt's `outcome` must be `PASS` — a failed attempt can never be verified, and the request fails with `ERR_INVALID_STATE` — after which the record becomes `VERIFIED`, `verified_by_id` is set to the verifier, and the item's `data_status` advances to `VERIFIED`. On `REJECT`, the record becomes `REJECTED`, `verified_by_id` is still recorded, and the item's `data_status` falls back to `PENDING`, opening a retry loop in which a fresh sanitization attempt may be logged and verified.

Once a data-bearing item reaches `VERIFIED`, a `ComplianceOfficer` may issue it a **Certificate of Data Destruction**: the request's `cert_type` must be `DATA_DESTRUCTION` (any other value is rejected with `ERR_VALIDATION`), and the data gate of §2.6 applies in full — issuing the certificate for a data-bearing item whose `data_status` is anything but `VERIFIED` is rejected with `ERR_DATA_SANITIZATION_UNVERIFIED`. The certificate is created `ISSUED`, stamped with a server-minted `certificate_number` consisting of the prefix `CERT-` followed by eight uppercase hexadecimal characters, linked to its `item_id`, and attributed to the issuing officer via `issued_by_id`. Should circumstances invalidate a certificate, the officer may void it, moving `ISSUED` → `VOIDED`; voided certificates are excluded from the certificate count in the sustainability report (§3.9). Certificates of recycling, by contrast, are never issued by hand — they exist only as the automatic output of batch processing described in §3.7, linked to a `batch_id`.

### 3.6. Resale Listings and the Sales Cycle

An item triaged `FOR_RESALE` is offered for sale through a **ResaleListing** created by an `IntakeOperator`. Creation supplies the `item_id`, an `asking_price_cents`, a `floor_price_cents` of at least zero, and a sales `channel` of `B2B_AUCTION` or `RETAIL`; the asking price must not sit below the floor, and a payload violating that rule fails body validation with `ERR_VALIDATION` before any state check runs. After body validation, the item must actually be in `FOR_RESALE` (`ERR_INVALID_STATE`), and then the data gate applies: for a data-bearing item, listing requires `data_status` `VERIFIED` whenever the active policy's `resale_requires_verified_sanitization` flag is true — which is also the strict default applied when no policy is active at all — and requires `SANITIZED` or `VERIFIED` when the flag is false; breaching the gate yields `ERR_DATA_SANITIZATION_UNVERIFIED`. Non-data-bearing items pass the gate trivially. A created listing is `ACTIVE`, and the item moves `FOR_RESALE` → `LISTED` in the same operation.

Selling is the fiscal moment. The sale is recorded by an `IntakeOperator` supplying a `sale_price_cents`, an integer of at least zero (`ERR_VALIDATION` otherwise); the listing must be `ACTIVE` (`ERR_LISTING_NOT_ACTIVE`, checked first), and the offered price must be at least the listing's `floor_price_cents` (`ERR_FLOOR_PRICE_VIOLATION`, checked after the state gate). On success the listing becomes `SOLD`, the item moves `LISTED` → `SOLD`, and the item's `final_value_cents` is computed per line as the sale price minus the platform's commission, where the commission is the sale price multiplied by the account-tier rate and rounded half-up to whole cents: fifteen percent for `STANDARD` accounts, fifteen percent for `VOLUME`, and ten percent for `ENTERPRISE`.

The sales cycle is not one-way. A buyer return moves the listing `SOLD` → `RETURNED` and is only possible while the manifest's money is still fluid: if any settlement of the owning manifest is `FINALIZED` or `PAID`, the return is rejected with `ERR_SETTLEMENT_ALREADY_FINALIZED`. The return cascade then does three things — the item moves `SOLD` → `FOR_RESALE`, its `final_value_cents` is reset to zero, and any `QUOTE_OPEN` settlement of the owning manifest is recomputed under the quote variant of §3.8 with that settlement's `version` incremented. From `RETURNED`, the listing may be reactivated — moving back to `ACTIVE` — which requires the item to be in `FOR_RESALE` (`ERR_INVALID_STATE` otherwise) and moves it back to `LISTED`. Alternatively, an unsold listing may be withdrawn: `ACTIVE` → `WITHDRAWN` is terminal for the listing and returns the item `LISTED` → `FOR_RESALE`, free to be relisted through a fresh listing or retriaged to recycling.

### 3.7. Downstream Recycling: Batches, Shipment, and Processing

Items routed to recycling leave the facility in a **RecycleBatch** assembled by a `LogisticsCoordinator`. Creation captures the planned `scheduled_delivery_date` and an `is_export` flag; the recycler may be nominated explicitly through `recycler_id` or left to the selector policy of §3.2 when omitted. Two policy gates run at creation, after body validation and before the temporal certification check: an export shipment while the active policy's `export_allowed` is false is rejected with `ERR_EXPORT_NOT_ALLOWED` (when no policy is active, export is permitted), and — when no `recycler_id` was supplied — an empty selector pool is rejected with `ERR_NO_ELIGIBLE_RECYCLER`. Whether nominated or selected, the recycler's `certification_expires_at` must be strictly after the scheduled delivery date — the expiry instant itself is already too late — and a lapsed certification is rejected with `ERR_RECYCLER_CERT_EXPIRED`. A new batch is `STAGING` with `gross_weight_kg` and `item_count` both zero; both are computed fields maintained automatically as items come and go.

Filling the batch is governed by a strict chain. The batch must still be `STAGING`, or the add fails with `ERR_BATCH_NOT_STAGING`. Next the data gate: a data-bearing item must be `VERIFIED` — `ERR_DATA_SANITIZATION_UNVERIFIED` otherwise — while non-data-bearing items pass. Then the recycler must actually accept the item's `category` in its `accepted_categories` (`ERR_RECYCLER_CATEGORY_UNSUPPORTED`), and finally the item itself must be recycle-routed, meaning `disposition` `RECYCLE` and `processing_status` `FOR_RECYCLE` (`ERR_ITEM_NOT_RECYCLE_ROUTED`). On success the item moves `FOR_RECYCLE` → `BATCHED`, its `recycle_batch_id` is set to the batch, a custody entry is written with `subject_type` `ITEM`, `event_type` `TRANSFERRED`, and `to_location` set to the literal prefix `batch:` followed by the batch's `id`, the batch totals are recomputed, and the batch's `version` increments. Removal is the compensating mirror — an item identifier that does not resolve to an item currently contained in the batch is rejected with `ERR_ITEM_NOT_FOUND`, and removal is allowed only while `STAGING` under the same `ERR_BATCH_NOT_STAGING` gate — returning the item `BATCHED` → `FOR_RECYCLE`, nulling its `recycle_batch_id`, recomputing totals, and incrementing the batch version; removal returns no content.

Shipping commits the batch downstream and moves it `STAGING` → `IN_TRANSIT`. The guard order at ship time is: the batch must be in `STAGING` (`ERR_INVALID_STATE`); the recycler's certification must still be strictly valid at the scheduled delivery date, re-checked here just as at creation (`ERR_RECYCLER_CERT_EXPIRED`); the recycler's daily intake must absorb the load — the sum of `gross_weight_kg` over this recycler's batches in `IN_TRANSIT`, `DELIVERED`, or `PROCESSED` sharing the same calendar delivery day, plus this batch's own gross weight, must not exceed `daily_intake_capacity_kg`, with an exact fit allowed and only a strictly-greater overflow rejected with `ERR_RECYCLER_DAILY_CAPACITY_EXCEEDED`; and the batch must contain at least one item (`ERR_BATCH_EMPTY`). Shipping moves every contained item `BATCHED` → `DOWNSTREAM` and writes a batch-level custody entry of `event_type` `SHIPPED_DOWNSTREAM`.

Downstream acknowledgment and final processing belong to the `ComplianceOfficer`. Delivery acknowledgment moves `IN_TRANSIT` → `DELIVERED` and writes a `DELIVERED_DOWNSTREAM` custody entry. Processing moves `DELIVERED` → `PROCESSED` and fires the completion cascade: every contained item moves `DOWNSTREAM` → `COMPLETE`; the batch's `gross_weight_kg` is added to the recycler's `total_processed_kg`; a Certificate of Recycling is auto-issued with `cert_type` `RECYCLING`, the `batch_id` populated, status `ISSUED`, and `issued_by_id` set to the literal `system`; each completing item adds its `weight_kg` to its account's `lifetime_diverted_kg` and may trigger the tier upgrade of §3.1; and custody entries of `event_type` `PROCESSED` are written for each item and for the batch itself. `PROCESSED` is terminal for the batch.

### 3.8. Settlements, Ledger Posting, and Payout

Money moves through a **Settlement**. An `IntakeOperator` may request a quote for a manifest while it stands `RECEIVED` or `RECONCILED` — any other state yields `ERR_INVALID_STATE` once the OCC check has passed — and only while no settlement of the manifest stands `FINALIZED` or `PAID`, a configuration rejected with `ERR_SETTLEMENT_ALREADY_FINALIZED` after the state check; the request carries nothing but the OCC guard `expected_manifest_version`, and a value that no longer matches the manifest's current `version` is rejected with `ERR_STALE_VERSION` before any figure is computed. The created settlement records its owning manifest as `manifest_id`, has `kind` `QUOTE` and `status` `QUOTE_OPEN`, and it supersedes its predecessor: if a previous `QUOTE_OPEN` settlement existed for the manifest, that record moves to `SUPERSEDED` and the new settlement's `supersedes_settlement_id` points at it, forming a chain that can be walked through the settlement list's `supersedes_settlement_id` filter. For an `AccountManager`, the platform-wide settlement list is silently restricted to settlements of its own account. Creating the quote also increments the manifest's `version`, which is exactly what the OCC guard on the next re-quote protects against.

The quote's `gross_buyback_cents` estimates what the platform will pay for the manifest's assets. The quote variant counts every item whose `disposition` is `RESALE` or `REFURB`, regardless of where it stands in processing, and values it per line: an item already `SOLD` contributes its realized `final_value_cents`, while an unsold item contributes its catalog estimate — a base value for its `category` multiplied by the multiplier for its `declared_grade`, rounded half-up to whole cents. The base values are 40000 cents for a `LAPTOP`, 25000 for a `DESKTOP`, 120000 for a `SERVER`, 15000 for a `PHONE`, 18000 for a `TABLET`, 8000 for a `MONITOR`, 0 for a `BATTERY`, and 5000 for `OTHER`; grade `A` values at full base, `B` at seventy percent, `C` at forty percent, and `D` at ten percent. Recycle-routed items contribute zero to the buyback in every variant. Per-line amounts are rounded first and then summed — the pinned round-then-sum order of §2.7 — into `gross_buyback_cents`.

Against the buyback stand `total_fees_cents`. Each recycle-routed item incurs a recycling fee of three parts: a category base fee — 800 cents for a `LAPTOP`, 1000 for a `DESKTOP`, 2500 for a `SERVER`, 300 for a `PHONE`, 400 for a `TABLET`, 1200 for a `MONITOR`, 1500 for a `BATTERY`, and 900 for `OTHER` — plus a weight charge and a flat 2000-cent hazmat surcharge when `hazmat_flag` is set. The weight charge multiplies the item's whole `weight_kg` by a single per-kilogram rate chosen by the item's total weight: under 5.0 kg the rate is 120 cents per kilogram, from 5.0 kg up to and including 20.0 kg the rate is 90 cents per kilogram, and above 20.0 kg the rate is 60 cents per kilogram; the product is rounded half-up to whole cents. Every data-bearing item additionally incurs one sanitization fee: the quote variant assumes the default `NIST_CLEAR` method at 700 cents, while the final variant uses the method of the item's latest `VERIFIED` sanitization record, at 500 cents for `CRYPTO_ERASE`, 700 for `NIST_CLEAR`, 1000 for `NIST_PURGE`, and 1500 for `PHYSICAL_DESTROY`; a data-bearing item with no `VERIFIED` record is charged the `NIST_CLEAR` default of 700 cents even in the final variant. Finally, when the manifest's `mode` is `PICKUP`, a flat pickup fee of 15000 cents applies in both variants. The per-line fees, each already in whole cents, are summed and the pickup fee added to form `total_fees_cents`.

The rebate and the net follow a pinned evaluation order that breaks the apparent circularity between them. First gross, then fees, then the pre-rebate net defined as `gross_buyback_cents` minus `total_fees_cents`; the rebate tier is keyed on this pre-rebate figure and never on the post-rebate result. A pre-rebate net of at least 500000 cents earns the `GOLD` tier at five percent; at least 100000 cents earns `SILVER` at two percent — both boundaries inclusive — and anything below earns no rebate tier. The `volume_rebate_cents` is the pre-rebate net multiplied by the tier rate and rounded half-up to whole cents, computed only when the pre-rebate net is positive; a zero or negative pre-rebate net yields a rebate of exactly zero. The settlement's `net_amount_cents` is then the pre-rebate net plus the rebate: a positive net means the platform pays the customer (a buyback), a negative net means the customer owes fees.

Finalization, performed by a `PlatformAdmin`, converts the quote into the realized record. Only a settlement whose `kind` is `QUOTE` may be finalized — a `FINAL` record is never re-finalized — the owning manifest must be `RECONCILED` (`ERR_INVALID_STATE`), and every item of the manifest must stand in `SOLD` or `COMPLETE` (`ERR_FINALIZE_ITEMS_PENDING`); the state checks run before the item-pending check. Finalization flips `kind` to `FINAL` and `status` `QUOTE_OPEN` → `FINALIZED`, moves every `SOLD` item of the manifest to `COMPLETE` — each such completion adding the item's weight to `lifetime_diverted_kg` and possibly upgrading the account tier, since resale counts as diversion — and recomputes all four totals under the final variant: only `COMPLETE` items count, sold items contribute their realized net `final_value_cents`, recycled and unsold items contribute zero, fees are computed on the final basis, and the rebate rule runs unchanged. The ledger then posts in a fixed sequence: a `BUYBACK_CREDIT` entry of the positive gross when gross is non-zero, then a `FEE_DEBIT` of the negated fees when fees are non-zero, then a `BONUS_CREDIT` of the rebate when the rebate is non-zero; every posted `LedgerEntry` records its `account_id`, its `settlement_id`, its `entry_type` (one of the five types above, or `REVERSAL` on a void), its signed `amount_cents` (credits positive, debits negative), and the running `balance_after_cents` immediately after posting. The account's `credit_balance_cents` grows by exactly `net_amount_cents`.

Two exits exist from `FINALIZED`, both restricted to `PlatformAdmin` and both guarded by `ERR_SETTLEMENT_NOT_FINALIZED` when attempted from any other state. Paying the settlement moves it to `PAID` and posts a single `PAYOUT_DEBIT` of the negated `net_amount_cents`, reducing `credit_balance_cents` by the same amount — the platform settles its debt to the customer. Voiding moves it to `VOIDED` and posts one `REVERSAL` entry per entry that finalization posted, each with the negated amount of its original, so the account's balance returns exactly to its pre-finalization value — the compensating invariant. A settlement's ledger trail is readable on its own, and the account-wide trail lists every entry across settlements in chronological `created_at` order. `SUPERSEDED`, `PAID`, and `VOIDED` are all terminal for a settlement.

### 3.9. Sustainability Reporting

Each account can be read as an ESG report computed live from operational data. The report's `total_items` counts every item the account has ever scanned, in any processing state, and `total_weight_kg` sums their `weight_kg` at three decimal places. The `diverted_weight_kg` sums weight over only those items that have reached `COMPLETE`, and the `diversion_rate_pct` expresses the diverted share as a percentage of total weight, rounded half-up to two decimal places; when the account has no weight at all, the rate is exactly 0.0 rather than a division failure. On the financial side, `resale_proceeds_cents` sums `final_value_cents` over completed items whose `disposition` is `RESALE` or `REFURB`, while `recycling_fees_cents` sums, over completed recycle-routed items, each item's per-line recycling fee plus — for data-bearing items — the sanitization fee, both on the final fee basis of §3.8. Finally, `certificates_issued` counts the account's `ISSUED` certificates of type `DATA_DESTRUCTION`; certificates that have been voided are excluded from this count.

## 4. Endpoint Definitions

Operations that create a new resource — an account, recycler, policy, manifest, item, sanitization record, certificate, listing, batch, or settlement — return `201 Created`. Operations that act on an existing resource without creating a new one — state transitions, amendments, sells, returns, verification, shipment, processing, finalization, payout, voiding, and adding an item to a batch — return `200 OK`. Removing an item from a batch returns `204 No Content` with no body. All list endpoints are paginated per §2.3. The 200 OK operations return the resource the path targets: manifest transitions and amendments return the manifest, item triage returns the item, sanitization verification returns the sanitization record, listing sell, return, relist, and withdraw return the listing, batch item-add, ship, deliver, and process return the batch, settlement finalize, pay, and void return the settlement, certificate voiding returns the certificate, and the clock endpoint returns an object carrying the resulting `current_utc`. Three list endpoints additionally accept exact-match filters: the account-manifest and recycler-batch lists filter by `status`, and the manifest-item list filters by `processing_status`; an unrecognized filter value is rejected with `ERR_VALIDATION`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/itad/accounts` | Create a business ITAD account | PlatformAdmin |
| GET | `/itad/accounts/{id}` | Read one account, including computed balance and lifetime diversion | PlatformAdmin, AccountManager, ComplianceOfficer |
| PATCH | `/itad/accounts/{id}` | Update tier and/or drive account status transitions | PlatformAdmin |
| GET | `/itad/accounts/{id}/manifests` | List manifests of an account | PlatformAdmin, AccountManager |
| GET | `/itad/accounts/{id}/ledger-entries` | List ledger entries of an account | PlatformAdmin, AccountManager |
| GET | `/itad/accounts/{id}/sustainability-report` | Computed ESG/compliance report for an account | PlatformAdmin, AccountManager, ComplianceOfficer |
| POST | `/itad/recyclers` | Register a certified downstream recycler | ComplianceOfficer |
| GET | `/itad/recyclers/{id}` | Read one recycler, including computed risk score and processed volume | PlatformAdmin, ComplianceOfficer, LogisticsCoordinator |
| GET | `/itad/recyclers/{id}/recycle-batches` | List batches routed to a recycler | PlatformAdmin, ComplianceOfficer, LogisticsCoordinator |
| POST | `/itad/compliance-policies` | Create a compliance policy; activating one deactivates all others | PlatformAdmin |
| GET | `/itad/compliance-policies` | List compliance policies | PlatformAdmin, ComplianceOfficer |
| POST | `/itad/manifests` | Create a DRAFT manifest for an account | AccountManager |
| GET | `/itad/manifests/{id}` | Read one manifest | PlatformAdmin, AccountManager, IntakeOperator, LogisticsCoordinator |
| PATCH | `/itad/manifests/{id}` | Amend a DRAFT manifest under optimistic concurrency | AccountManager |
| POST | `/itad/manifests/{id}/schedule` | Schedule a manifest (DRAFT to SCHEDULED) with window and route checks | LogisticsCoordinator |
| POST | `/itad/manifests/{id}/receive` | Mark a scheduled manifest received at the facility | IntakeOperator |
| POST | `/itad/manifests/{id}/reconcile` | Reconcile a received manifest after count and triage checks | IntakeOperator |
| POST | `/itad/manifests/{id}/close` | Close a reconciled manifest once settlements are paid or voided | AccountManager |
| POST | `/itad/manifests/{id}/cancel` | Cancel a DRAFT or SCHEDULED manifest with zero scanned items | AccountManager |
| POST | `/itad/manifests/{id}/items` | Scan an item into a manifest | IntakeOperator |
| GET | `/itad/manifests/{id}/items` | List items of a manifest | PlatformAdmin, AccountManager, IntakeOperator, LogisticsCoordinator, ComplianceOfficer |
| GET | `/itad/manifests/{id}/settlements` | List settlements of a manifest | PlatformAdmin, AccountManager, IntakeOperator |
| GET | `/itad/items/{id}` | Read one item | PlatformAdmin, AccountManager, IntakeOperator, LogisticsCoordinator, ComplianceOfficer, DestructionTechnician |
| POST | `/itad/items/{id}/triage` | Route an item to resale, refurbishment, or recycling | IntakeOperator |
| POST | `/itad/items/{id}/sanitizations` | Log a data-sanitization attempt on an item | DestructionTechnician |
| GET | `/itad/items/{id}/sanitizations` | List sanitization records of an item | PlatformAdmin, ComplianceOfficer, DestructionTechnician, IntakeOperator |
| POST | `/itad/sanitizations/{id}/verify` | Verify or reject a logged sanitization | ComplianceOfficer |
| POST | `/itad/items/{id}/certificates` | Issue a Certificate of Data Destruction for an item | ComplianceOfficer |
| GET | `/itad/items/{id}/certificates` | List certificates of an item | PlatformAdmin, ComplianceOfficer, AccountManager, IntakeOperator |
| POST | `/itad/listings` | Create a resale listing for a FOR_RESALE item | IntakeOperator |
| GET | `/itad/items/{id}/listings` | List listings of an item | PlatformAdmin, IntakeOperator, AccountManager |
| POST | `/itad/listings/{id}/sell` | Record a sale at or above the floor price | IntakeOperator |
| POST | `/itad/listings/{id}/return` | Return a sold listing and revert the item to resale stock | IntakeOperator |
| POST | `/itad/listings/{id}/relist` | Re-activate a returned listing | IntakeOperator |
| POST | `/itad/listings/{id}/withdraw` | Withdraw an active listing | IntakeOperator |
| POST | `/itad/recycle-batches` | Create a STAGING batch; selector policy picks the recycler when omitted | LogisticsCoordinator |
| GET | `/itad/recycle-batches/{id}` | Read one batch | PlatformAdmin, LogisticsCoordinator, ComplianceOfficer |
| GET | `/itad/recycle-batches/{id}/items` | List items contained in a batch | PlatformAdmin, LogisticsCoordinator, ComplianceOfficer |
| POST | `/itad/recycle-batches/{id}/items` | Add a recycle-routed item to a STAGING batch | LogisticsCoordinator |
| DELETE | `/itad/recycle-batches/{id}/items/{item_id}` | Remove an item from a STAGING batch | LogisticsCoordinator |
| POST | `/itad/recycle-batches/{id}/ship` | Ship a batch downstream after certification and capacity checks | LogisticsCoordinator |
| POST | `/itad/recycle-batches/{id}/deliver` | Acknowledge downstream delivery | ComplianceOfficer |
| POST | `/itad/recycle-batches/{id}/process` | Mark a delivered batch processed, firing the completion cascade | ComplianceOfficer |
| GET | `/itad/recycle-batches/{id}/certificates` | List certificates of a batch | PlatformAdmin, ComplianceOfficer, LogisticsCoordinator |
| POST | `/itad/manifests/{id}/settlements` | Create or recalculate a QUOTE settlement under optimistic concurrency | IntakeOperator |
| GET | `/itad/settlements/{id}` | Read one settlement | PlatformAdmin, AccountManager, IntakeOperator |
| GET | `/itad/settlements` | List settlements, with supersedes-chain lookup | PlatformAdmin, AccountManager, IntakeOperator |
| POST | `/itad/settlements/{id}/finalize` | Finalize a quote, complete sold items, and post ledger entries | PlatformAdmin |
| POST | `/itad/settlements/{id}/pay` | Pay out a finalized settlement | PlatformAdmin |
| POST | `/itad/settlements/{id}/void` | Void a finalized settlement with reversing ledger entries | PlatformAdmin |
| GET | `/itad/settlements/{id}/ledger-entries` | List ledger entries produced by a settlement | PlatformAdmin, AccountManager |
| POST | `/itad/certificates/{id}/void` | Void an issued certificate | ComplianceOfficer |
| GET | `/itad/custody-events` | Query the append-only custody trail by subject | PlatformAdmin, ComplianceOfficer, IntakeOperator, LogisticsCoordinator, AccountManager |
| POST | `/itad/_clock/set_current_utc` | Advance the logical clock used by temporal validations and scores | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_RECYCLER_NOT_FOUND` | 404 |
| `ERR_MANIFEST_NOT_FOUND` | 404 |
| `ERR_ITEM_NOT_FOUND` | 404 |
| `ERR_BATCH_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_LISTING_NOT_FOUND` | 404 |
| `ERR_SANITIZATION_NOT_FOUND` | 404 |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_BATCH_NOT_STAGING` | 409 |
| `ERR_MANIFEST_NOT_RECEIVED` | 409 |
| `ERR_LISTING_NOT_ACTIVE` | 409 |
| `ERR_SETTLEMENT_NOT_FINALIZED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_DATA_SANITIZATION_UNVERIFIED` | 422 |
| `ERR_EXPORT_NOT_ALLOWED` | 422 |
| `ERR_SANITIZATION_METHOD_NOT_ALLOWED` | 422 |
| `ERR_ACCOUNT_SUSPENDED` | 422 |
| `ERR_RECYCLER_CATEGORY_UNSUPPORTED` | 422 |
| `ERR_ITEM_NOT_RECYCLE_ROUTED` | 422 |
| `ERR_SETTLEMENT_ALREADY_FINALIZED` | 422 |
| `ERR_NO_ELIGIBLE_RECYCLER` | 422 |
| `ERR_WINDOW_IN_PAST` | 422 |
| `ERR_ROUTE_WINDOW_CONFLICT` | 409 |
| `ERR_RECYCLER_CERT_EXPIRED` | 422 |
| `ERR_RECYCLER_DAILY_CAPACITY_EXCEEDED` | 422 |
| `ERR_MANIFEST_EMPTY` | 422 |
| `ERR_MANIFEST_ITEM_COUNT_MISMATCH` | 422 |
| `ERR_MANIFEST_HAS_ITEMS` | 422 |
| `ERR_BATCH_EMPTY` | 422 |
| `ERR_FINALIZE_ITEMS_PENDING` | 422 |
| `ERR_CLOSE_SETTLEMENT_UNPAID` | 422 |
| `ERR_FLOOR_PRICE_VIOLATION` | 422 |

Requests that match no defined path or method are rejected with `ERR_NOT_FOUND` (404), and unexpected server failures with `ERR_INTERNAL` (500); both carry the standard error envelope and belong to no domain flow above.
