# Contents Pack-Out & Restoration Storage API — Product Requirements Document

## 1. Introduction

After a fire, flood, or other covered loss, a contents restoration company takes custody of a homeowner's entire household: every sofa, document, garment, and heirloom is inventoried room by room, triaged as salvageable or not, cleaned, stored in climate-controlled vaults, and eventually packed back once the structure is rebuilt. That physical operation generates a dense web of operational and financial obligations — barcoded inventory trails, disposal documentation with segregation of duties, chain-of-custody records for subcontracted specialty work, monthly storage accruals that must reconcile to the day, and carrier-facing invoices whose balances must settle exactly to zero. This document specifies the REST API that backs that operation, the Contents Pack-Out & Restoration Storage platform.

The platform serves six distinct operator populations, from field technicians scanning barcodes at the loss site to carrier representatives disputing invoice line items after submission. Its core is a hierarchical tree — a pack-out job contains rooms, rooms contain items — surrounded by satellite aggregates: vaults that house items, subcontractors that take specialty referrals, and a billing pipeline (statements, billing runs, carrier invoices) that converts occupancy into carrier-payable amounts. Two calculation variants pervade the financial side: storage accrual runs forward-looking whole-month while a statement is provisional and switches to chronological daily proration at finalization, and claim settlement pays actual cash value or replacement cost depending on the policy coverage type recorded on the job.

Everything in this document is normative. State names, error identifiers, field names, thresholds, and rounding rules are contractual; the workflows that connect them are described in business language and scattered deliberately across the sections that follow, because that is how the operation actually hangs together.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming that operator's role. A request missing either header, or presenting either header empty, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE`.

The platform recognizes exactly six roles, spelled precisely as follows: `ProjectManager`, `InventoryTechnician`, `BillingClerk`, `ClaimsAdjuster`, `SubcontractorContact`, and `CarrierRepresentative`.

A `ProjectManager` owns the structural side of the business: creating jobs, rooms, vaults, and subcontractors; driving job lifecycle transitions including structure sign-off and closure; dispatching, accepting, and rejecting specialty referrals; managing pack-back schedules; and verifying disposal records. An `InventoryTechnician` performs the field and warehouse work: registering items, making triage decisions under optimistic concurrency, running cleaning tasks, activating and releasing vault placements, and documenting disposals. A `BillingClerk` runs the money pipeline: creating storage statements, executing billing runs, and creating, submitting, and recording payments on carrier invoices. A `ClaimsAdjuster` reviews and settles handling claims but is barred by segregation of duties from approving, denying, or settling a claim filed under the same operator identity. A `SubcontractorContact` is a specialty vendor's representative and may act only on referrals belonging to that vendor. A `CarrierRepresentative` disputes or reconciles submitted invoices on behalf of the insurance carrier.

For five of the six roles — `ProjectManager`, `InventoryTechnician`, `BillingClerk`, `ClaimsAdjuster`, and `CarrierRepresentative` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `filed_by_user_id` on a handling claim, `documented_by_user_id` on a disposal record, or `verified_by_user_id` on a verified disposal) and does compare it against such recorded values when enforcing segregation of duties, but it never compares it to any entity's `id`. When `X-User-Role` is `SubcontractorContact`, by contrast, `X-User-ID` is the `id` of the acting `Subcontractor`; any action on a specialty referral compares the referral's `subcontractor_id` to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_REFERRAL_SUBCONTRACTOR`.

Segregation of duties is enforced at three points beyond the referral-ownership rule. The operator verifying a disposal record must differ from the operator who documented it, so `verified_by_user_id` may never equal `documented_by_user_id`. The operator approving, denying, or settling a handling claim must differ from the operator recorded as `filed_by_user_id`. Any violation of these rules is rejected with `ERR_SEGREGATION_OF_DUTIES`.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and may not exceed 100. The `offset` defaults to 0. Results are always sorted by `created_at` ascending unless a more specific ordering is stated for the endpoint (custody events, for example, return in `sequence` order). The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` indicates whether additional results exist beyond the returned window.

### 2.4. Resource Identity, Timestamps, and the Logical Clock

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix. Nearly every resource also carries `created_at` and `updated_at` timestamps in ISO 8601 UTC format with three fractional digits, plus an integer `version` that starts at 1 on creation and increments by exactly 1 on every mutation of that resource. The single exception is the custody event: a `CustodyEvent` carries `id` and `created_at` only — both `updated_at` and `version` are absent from it, because custody events are append-only and never mutated after creation.

All date and datetime stamping in the platform reads a single server-side logical clock, never wall-clock time. Before any operator sets it, the logical clock starts at exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock thereafter. The logical clock governs the `placed_on` and `released_on` dates of storage placements, the `documented_at` timestamp of disposal documentation, and the eligibility of statements for billing-run finalization. An authorized operator (`ProjectManager`, `InventoryTechnician`, or `BillingClerk`) may set the clock to a supplied `to_iso8601` instant through the test-driving clock capability; the response reports the resulting `current_utc`.

Dates that represent service days or accrual periods — `service_date`, `period_start`, `period_end`, `placed_on`, `released_on` — use the `YYYY-MM-DD` calendar date format.

### 2.5. Monetary Precision and Rounding Discipline

All monetary values are integer cents. Whenever a computation produces a fractional cent, the result is rounded half-up to the nearest whole cent, and each computation rounds exactly where its rule says it rounds — rounding is never deferred silently to a later stage. The claim settlement calculation divides using exact rational arithmetic and rounds once, half-up, at the very end. The specialty billed-cost calculation likewise rounds exactly once at the end. The storage daily-proration calculation pins a different and deliberate order: the daily rate for a placement is rounded half-up to whole cents first, once per placement, and only then multiplied by that placement's occupied-day count; unrounded per-placement values are never summed and rounded at the end. As a concrete illustration of why the order matters: a placement whose monthly snapshot rate is 6001 cents yields a daily rate of 197 cents after rounding (6001 times 12 divided by 365, rounded half-up), so three occupied days accrue 591 cents — not the 592 cents that rounding the unrounded product at the end would produce. Volumes are exact integer cubic feet, and the pack-back eligibility figure is an exact integer count.

### 2.6. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control, and only those two take a version field.

A triage request on an item must carry `expected_item_version`, the client's last observed `version` of that item. If another triage decision has advanced the item's `version` since the client last read it, the request is rejected with `ERR_STALE_ITEM_VERSION` (HTTP 412). This guard exists because re-triage is a legitimate revision loop — a salvageable item may be re-determined non-salvageable and vice versa while the item remains re-triageable — so a second triage request observes a valid triage state and would succeed on state grounds alone; the version check is what prevents a client from overwriting a decision it has not observed.

A storage statement creation request must carry `expected_job_version`, the client's last observed `version` of the parent pack-out job. If another writer has advanced the job's `version` since the client last read it, the creation is rejected with `ERR_STALE_JOB_VERSION` (HTTP 412). The guard exists because creating a statement with `supersedes_statement_id` legitimately voids the job's current provisional statement, so a second creation observes a still-valid job state and would succeed on state grounds alone; the version check prevents a client from superseding a statement lineage it has not observed.

Endpoints not listed above do not accept a version field.

### 2.7. Nested Resource Validation and Error Precedence

Endpoints that address nested resources validate path parameters left to right. For example, an endpoint reached through a job, then a room, then an item validates the job's existence first, then the room's, then the item's; the first missing resource on the path determines the `ERR_NOT_FOUND` response. Body-referenced resources — a `vault_id` on placement activation, a `subcontractor_id` on referral creation — are checked for existence in the same pass.

When a single request would fail more than one rule, the failure reported is the one with the highest priority in the following fixed order. First, authentication: missing or empty `X-User-ID` or `X-User-Role` headers yield `ERR_UNAUTHENTICATED`. Second, role authorization: a role outside the endpoint's authorized list yields `ERR_FORBIDDEN_ROLE`. Third, segregation-of-duties and referral-ownership checks — a disposal verifier equal to the documenter, a claim approver, denier, or settler equal to the filer, or a `SubcontractorContact` acting on another vendor's referral — yield `ERR_SEGREGATION_OF_DUTIES` or `ERR_NOT_REFERRAL_SUBCONTRACTOR` respectively. Fourth, request-body schema validation — missing required fields, invalid enum members, integer range violations — yields `ERR_VALIDATION`. Fifth, resource existence along path and body references yields `ERR_NOT_FOUND`. Sixth, the optimistic-concurrency version checks yield `ERR_STALE_ITEM_VERSION` or `ERR_STALE_JOB_VERSION`. Seventh, state-legality checks — invalid-from transitions, terminal lockdown, duplicate actions, item terminal lockdown, the salvageability gate on cleaning and placement, and the job-close terminal-items gate — yield `ERR_INVALID_TRANSITION`, `ERR_ITEM_TERMINAL`, `ERR_ITEM_NOT_SALVAGEABLE`, or `ERR_JOB_ITEMS_NOT_TERMINAL` as applicable. Eighth, business safety rules — hazmat storage, climate compatibility, hazmat manifest requirements — yield `ERR_HAZMAT_STORAGE_FORBIDDEN`, `ERR_CLIMATE_CLASS_INCOMPATIBLE`, or `ERR_HAZMAT_MANIFEST_REQUIRED`. Ninth, business constraints — duplicate barcodes, vault capacity, subcontractor capacity, crew window overlap, and statement period validity — yield `ERR_DUPLICATE_BARCODE`, `ERR_VAULT_CAPACITY_EXCEEDED`, `ERR_SUBCONTRACTOR_AT_CAPACITY`, `ERR_CREW_WINDOW_OVERLAP`, or `ERR_VALIDATION`. Tenth, temporal rules yield `ERR_WINDOW_INVALID` or `ERR_CUSTODY_EVENT_OUT_OF_ORDER`. Eleventh, referential business gates yield `ERR_JOB_NOT_READY_FOR_PACKBACK`, `ERR_NO_ELIGIBLE_ITEMS_FOR_PACKBACK`, `ERR_OPEN_CLAIM_BLOCKS_PACKBACK`, `ERR_SPECIALTY_REQUIRED`, or `ERR_STATEMENT_PERIOD_OPEN`. Twelfth and last, fiscal gates yield `ERR_PAYMENT_EXCEEDS_BALANCE` or `ERR_INVOICE_BALANCE_OUTSTANDING`.

Because lower-priority failures are masked by higher-priority ones, a request that is both unauthenticated and malformed always reports the authentication failure, and a placement request that violates both vault capacity and climate compatibility is evaluated state-legality first if the item is also in the wrong processing status.

### 2.8. Derived Rollups, Cascades, and Compensating Invariants

Several fields on the platform are never written directly; they are recomputed from children whenever a relevant mutation occurs. A room's `item_count` counts the items registered under it. A room's `status` is a compound of its children's two parallel item dimensions, as detailed in §3.1. A vault's `occupied_cu_ft` sums the `volume_cu_ft` of every item with an active placement in that vault, and its `posture` reads `FULL` exactly when `occupied_cu_ft` equals `capacity_cu_ft`, otherwise `OPEN`. A job's `accrued_storage_total_cents` sums, across that job's statements, the `provisional_total_cents` of each provisional statement and the `final_total_cents` of each finalized or invoiced statement, excluding voided statements entirely; it is recomputed on every statement mutation and every placement activation or release touching the job. A job's `billing_status` derives from its invoices' statuses, as detailed in §3.8.

Two compensating invariants hold across the platform. Vault occupancy is conserved: activating a placement adds exactly the item's `volume_cu_ft` to `occupied_cu_ft`, and the paired release — whatever its reason — subtracts exactly the same amount, so an activate-release pair leaves occupancy unchanged. Claim credit is conserved across approval and void: voiding an approved claim that has not yet been swept into an invoice returns the pending settlement liability and any not-yet-submitted invoice credit basis to their pre-approval values; an invoice's `balance_cents` may go negative only through a post-submission claim void, never otherwise.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Job: Intake, Rooms, and Item Registration

A pack-out operation begins when a `ProjectManager` creates a job with the carrier's `claim_number` — unique across all jobs — the `property_address` of the loss site, the `carrier_name`, and the `policy_coverage_type`, which is either `ACV` or `RCV` and later selects which settlement variant applies to handling claims on this job's items. A new job starts in `INTAKE` status with `structure_status` `PENDING` and `billing_status` `ACCUMULATING`.

Rooms are then added to the job with a `name` such as "Master Bedroom", a `room_type` drawn from `LIVING`, `BEDROOM`, `KITCHEN`, `BATH`, `GARAGE`, `BASEMENT`, or `OTHER`, and an optional `floor_level` that defaults to 1. Each room starts `OPEN` with an `item_count` of zero.

An `InventoryTechnician` registers items into a room with a scannable `barcode`, a free-text `description`, an `item_category` of `TEXTILE`, `ELECTRONICS`, `FURNITURE`, `DOCUMENT`, `ARTWORK`, `APPLIANCE`, or `GENERAL`, a `declared_value_cents` that is at least zero, and a `volume_cu_ft` of at least one cubic foot. Optional registration inputs are a `photo_ref` captured at inventory, a `hazmat_flag` for sewage- or chemical-contaminated items, and a `smoke_damage_flag` for smoke- or soot-damaged items; both flags default to false. The `barcode` must be unique within the parent job — across all rooms of that job — and a duplicate is rejected with `ERR_DUPLICATE_BARCODE`. Every item is born with `condition_triage` `PENDING`, `processing_status` `REGISTERED`, and a `triage_count` of zero. The platform derives `is_high_value` for each item: an item is high-value exactly when its `declared_value_cents` is at least 1000000 cents — ten thousand dollars — with the boundary itself included.

The moment a job's first item is registered, the job auto-advances from `INTAKE` to `ACTIVE` and its `version` increments by 1, as it does on every job mutation. Items can be listed globally with an optional `room_id` filter, or read individually to see both parallel state dimensions together with `is_high_value`.

A room's `status` is a standing rollup of its children, recomputed automatically on any child item mutation. With at least one item and no item still holding `condition_triage` `PENDING`, the room reads `INVENTORIED`. When, additionally, no item holds a `processing_status` of `REGISTERED`, `AWAITING_CLEANING`, `IN_CLEANING`, `CLEANED`, or `AWAITING_DISPOSAL` — meaning every item is stored, out for specialty, packed back, delivered, disposed, or claim-settled — the room reads `CLEARED`. The rollup is bidirectional: if a child returns to an on-site status, as happens when a stored item's placement is manually released back to `CLEANED`, a `CLEARED` room falls back to `INVENTORIED` or `OPEN` as the predicate dictates.

### 3.2. Triage, the Re-Triage Loop, and the Disposal Pipeline

Every registered item waits for a salvageability determination. An `InventoryTechnician` records that determination — `SALVAGEABLE` or `NON_SALVAGEABLE`, supplied as `determination` — through the item's triage action, which always carries `expected_item_version` per the OCC rule in §2.6 and may carry an optional `triage_note`. Triage is a cyclic dimension: from `PENDING`, `SALVAGEABLE`, or `NON_SALVAGEABLE` an item may be re-determined to either outcome, provided the item's `processing_status` has not reached one of the terminal states `DISPOSED`, `DELIVERED`, or `CLAIM_SETTLED` — any mutation of a terminal item is rejected with `ERR_ITEM_TERMINAL` — and provided the item currently sits in `REGISTERED`, `AWAITING_CLEANING`, `IN_STORAGE`, or `AWAITING_DISPOSAL`; triage from any other processing state is rejected with `ERR_INVALID_TRANSITION`. Every successful triage decision, including a re-triage, increments the item's `triage_count` by one and bumps the item's `version` by one.

A `SALVAGEABLE` determination moves the item's `processing_status` to `AWAITING_CLEANING`. If the item was sitting in `AWAITING_DISPOSAL`, the re-triage pulls it back from the brink: its disposal record, if still `DRAFT` or `DOCUMENTED` (that is, not yet verified), is automatically voided.

A `NON_SALVAGEABLE` determination moves the item to `AWAITING_DISPOSAL` and sets off a four-link cascade. First, the processing status itself flips. Second, entering `AWAITING_DISPOSAL` auto-creates a `DRAFT` disposal record for the item if no non-voided one exists — the record is one-to-one with the item. Third, if the item was in `IN_STORAGE`, its active storage placement is automatically released with `release_reason` `DISPOSAL`. Fourth, that release decrements the vault's `occupied_cu_ft` by the item's `volume_cu_ft` and recomputes `provisional_total_cents` on every `PROVISIONAL` statement of the job plus the job's `accrued_storage_total_cents`. This cascade is the intended serialization point between disposal triage and storage billing.

The disposal record itself then walks a two-signature pipeline. An `InventoryTechnician` documents it by supplying the `disposal_method` — one of `LANDFILL`, `RECYCLE`, `HAZARDOUS_WASTE`, or `DONATION` — and the `facility_name`, optionally with a `photo_ref` of the disposal; documentation without method and facility is rejected with `ERR_VALIDATION`. When the item's `hazmat_flag` is true, documentation additionally requires a `manifest_number` and the `disposal_method` must be `HAZARDOUS_WASTE`; a hazmat documentation missing the manifest or naming any other method is rejected with `ERR_HAZMAT_MANIFEST_REQUIRED`. Successful documentation stamps `documented_by_user_id` with the acting operator and `documented_at` with the logical clock, and moves the record from `DRAFT` to `DOCUMENTED`. Verification is then performed by a `ProjectManager` whose identity differs from `documented_by_user_id` — the segregation-of-duties rule of §2.1, violated requests rejected with `ERR_SEGREGATION_OF_DUTIES` — which stamps `verified_by_user_id`, moves the record to `VERIFIED`, flips the item's `processing_status` to `DISPOSED`, and triggers the room and job compound recompute that bubbles up the tree. An item's disposal record can be fetched as an array of zero or one entries.

### 3.3. Cleaning, Rework, and Specialty Referral

A salvageable item enters the cleaning pipeline when an `InventoryTechnician` schedules a cleaning task for it. Scheduling requires the item's `condition_triage` to be `SALVAGEABLE`; an attempt on an untriaged or non-salvageable item is rejected with `ERR_ITEM_NOT_SALVAGEABLE`. One category is exceptional: `ARTWORK` items never receive a cleaning task — they are specialty-only — and scheduling cleaning on artwork is rejected with `ERR_SPECIALTY_REQUIRED`. The task's `process_code` is derived from the item's `item_category` at creation: `TEXTILE` maps to `LAUNDER_DEODORIZE`, `ELECTRONICS` to `DRY_CORROSION_INHIBIT`, `FURNITURE` to `SURFACE_CLEAN`, `DOCUMENT` to `FREEZE_DRY`, `APPLIANCE` to `DEEP_CLEAN`, and `GENERAL` to `STANDARD_CLEAN`. At the same moment the task snapshots `deodorization_required` from the item's `smoke_damage_flag`; later flag changes on the item do not alter the task.

A task starts `SCHEDULED`. Starting it — permitted only while the item's `processing_status` is `AWAITING_CLEANING`, otherwise `ERR_INVALID_TRANSITION` — moves the task to `IN_PROGRESS` and the item to `IN_CLEANING`, bumping the item's `version`. Quality assurance then closes the task in one of two directions, each recording an optional `qa_note`. A passing QA moves the task to its terminal `PASSED` state, moves the item to `CLEANED`, bumps the item's `version`, and computes the task's `fee_cents`: a base of 12000 cents plus a deodorization adder of 4000 cents when `deodorization_required` was snapshotted true, exact integer cents with no rounding. Until a task passes, its `fee_cents` remains null. A failing QA moves the task to `FAILED` while the item stays `IN_CLEANING` awaiting rework; a subsequent rework returns the task to `IN_PROGRESS` and increments its `rework_count` by one. The rework cycle may repeat as often as needed.

High-value and specialty items take a different route. A `ProjectManager` first registers each vendor with a `name`, the `specialty_types` it offers, its `max_concurrent_referrals` capacity, and an optional `contact_email`. The `ProjectManager` then creates a specialty referral on an item, naming a `subcontractor_id`, a `specialty_type` from `ART_CONSERVATION`, `ELECTRONICS_DATA_RECOVERY`, `DOCUMENT_FREEZE_DRYING`, `FUR_CLEANING`, or `JEWELRY_APPRAISAL`, and a `quoted_cost_cents` of at least zero, with an optional `markup_pct` that defaults to 15. The chosen specialty type must appear in the subcontractor's `specialty_types` list, and the referral starts `DRAFT` with `billed_cost_cents` null. Referrals can be listed globally, filterable by `item_id` and/or `subcontractor_id`, or read individually.

Dispatching a referral is gated twice: the item's `processing_status` must be `AWAITING_CLEANING`, `CLEANED`, or `IN_STORAGE` — anything else yields `ERR_INVALID_TRANSITION` — and the subcontractor's `active_referral_count` must be below its `max_concurrent_referrals` capacity, otherwise `ERR_SUBCONTRACTOR_AT_CAPACITY`. Dispatch moves the referral to `DISPATCHED`, moves the item to `OUT_FOR_SPECIALTY` — releasing the item's active placement with `release_reason` `SPECIALTY` first if it was stored, with the usual vault-occupancy and accrual cascade — and increments the subcontractor's `active_referral_count` by one. The capacity counter counts a vendor's referrals in `DISPATCHED`, `IN_CUSTODY`, or `QA_REJECTED` status, and the vendor's `max_concurrent_referrals` is at least one.

Receipt and return of the physical item are performed by a `SubcontractorContact` whose identity is the vendor itself: receipt moves the referral from `DISPATCHED` to `IN_CUSTODY`, and return moves it from `IN_CUSTODY` to `RETURNED`, freeing the vendor's slot by decrementing `active_referral_count` by one. Either action attempted under another vendor's identity is rejected with `ERR_NOT_REFERRAL_SUBCONTRACTOR`. A returned referral faces the `ProjectManager`'s quality decision. Acceptance moves it to the terminal `QA_ACCEPTED` state, computes `billed_cost_cents` as the `quoted_cost_cents` scaled by `markup_pct` percent — that is, the quote multiplied by one hundred plus the markup percentage, divided by one hundred, rounded half-up once at the end — and returns the item to `CLEANED`. Rejection moves it to `QA_REJECTED` and re-holds the vendor's slot by incrementing `active_referral_count` by one. A rejected referral may be re-dispatched; the resend cycle from `QA_REJECTED` back to `DISPATCHED` consumes no new capacity because the slot was never released, and the item stays `OUT_FOR_SPECIALTY` throughout.

Throughout the referral's life, a chain-of-custody log accumulates. Each custody event — recorded by an `InventoryTechnician` or the vendor's `SubcontractorContact` — is bound to its referral through a server-set `referral_id` taken from the creation path, and carries an `event_type` of `PICKED_UP`, `IN_TRANSIT`, `RECEIVED_BY_SUB`, `RETURNED_BY_SUB`, or `RECEIVED_BACK`, an `event_at` timestamp, an `actor_name`, and an optional `note`. The `event_at` of each new event must be strictly greater than every prior `event_at` on the same referral; an out-of-order append is rejected with `ERR_CUSTODY_EVENT_OUT_OF_ORDER`. Each event receives a per-referral `sequence` starting at 1 and increasing monotonically in append order — a `created_at` tie-break is never needed because `event_at` is strictly increasing — and the events of a referral are listed in `sequence` order.

### 3.4. Vaults, Placement, and the Storage Gates

A `ProjectManager` registers storage vaults with a globally unique `code`, a `climate_class` of `CLIMATE_CONTROLLED`, `STANDARD`, or `COLD_STORAGE`, a `capacity_cu_ft` greater than zero, and a `monthly_rate_cents_per_cu_ft` greater than zero. A vault reads back with its computed `occupied_cu_ft` and `posture`.

Placing a `CLEANED` item into a vault is the most heavily gated operation in the platform. An `InventoryTechnician` activates a placement by naming the target `vault_id`; the checks fire in the §2.7 precedence order, and their business content is as follows. The item's `condition_triage` must be `SALVAGEABLE`, else `ERR_ITEM_NOT_SALVAGEABLE`, and its `processing_status` must be `CLEANED`, else `ERR_INVALID_TRANSITION`; a terminal item rejects with `ERR_ITEM_TERMINAL`. A hazmat-flagged item may never enter any vault: rejection `ERR_HAZMAT_STORAGE_FORBIDDEN`. Items in the climate-required categories `TEXTILE`, `DOCUMENT`, `ARTWORK`, and `ELECTRONICS` may be placed only into `CLIMATE_CONTROLLED` vaults; placement of such an item into a `STANDARD` or `COLD_STORAGE` vault is rejected with `ERR_CLIMATE_CLASS_INCOMPATIBLE`. Capacity is checked exactly: the vault's current `occupied_cu_ft` plus the item's `volume_cu_ft` must not exceed `capacity_cu_ft`, with an exact fit — the sum landing precisely on capacity — allowed; overflow is rejected with `ERR_VAULT_CAPACITY_EXCEEDED`. Finally, a high-value item — one whose `is_high_value` derives true — may be placed only if the item already has a `QA_ACCEPTED` specialty referral; placement without one is rejected with `ERR_SPECIALTY_REQUIRED`.

Activation writes the placement with `status` `ACTIVE`, a `placed_on` date read from the logical clock, `released_on` and `release_reason` null, and a `monthly_rate_cents` snapshot computed as the item's `volume_cu_ft` multiplied by the vault's `monthly_rate_cents_per_cu_ft` — a snapshot, so later vault rate changes do not alter it. The item moves to `IN_STORAGE`, the vault's `occupied_cu_ft` increases by the item's `volume_cu_ft`, and every `PROVISIONAL` statement of the job recomputes its `provisional_total_cents` together with the job's `accrued_storage_total_cents`. Placements are listed per item or per vault.

A manual release by an `InventoryTechnician` — permitted only while the placement is `ACTIVE`, otherwise `ERR_INVALID_TRANSITION` — stamps `released_on` from the logical clock, sets `release_reason` to `MANUAL`, moves the item from `IN_STORAGE` back to `CLEANED`, decrements the vault's occupancy by exactly the added volume, and recomputes provisional accrual and the job total. The other four release reasons — `DISPOSAL`, `CLAIM`, `SPECIALTY`, and `PACK_BACK` — are written only by the system cascades described in their own sections; in every case the released placement's status becomes `RELEASED`, which is terminal.

### 3.5. Structure Sign-Off and the Pack-Back Pipeline

Parallel to item processing, the job's `structure_status` tracks the building itself. A `ProjectManager` starts structure work, moving `PENDING` to `IN_PROGRESS`; completes it, moving `IN_PROGRESS` to `COMPLETE`; and may rescind completion if structure work reopens, moving `COMPLETE` back to `IN_PROGRESS` — the cycle may repeat. All three structure actions require the job's main status not to be `CLOSED`, and rescinding is blocked while any pack-back schedule of the job sits in `CONFIRMED`, `IN_TRANSIT`, or `DELIVERED` — rejection `ERR_INVALID_TRANSITION` — because a live pack-back depends on the completion it gates. Completion opens the pack-back gate; rescission re-closes it.

Once the structure is complete, a `ProjectManager` requests pack-back schedules for the job, each naming a `crew_id`, a `service_date`, and a daily window from `window_start_hour` to `window_end_hour`. Window hours are integers: start runs 0 through 23, end runs 1 through 24, the end must be strictly greater than the start — otherwise `ERR_WINDOW_INVALID` — and occupation is half-open: a crew occupies from the start hour up to but not including the end hour. A new schedule starts `REQUESTED` with `eligible_item_count` null and `reschedule_count` zero.

Confirming a schedule runs a four-gate check sequence. First, the job's `structure_status` must be `COMPLETE`, else `ERR_JOB_NOT_READY_FOR_PACKBACK`. Second, no other schedule with the same `crew_id` and `service_date` in `CONFIRMED` or `IN_TRANSIT` status may have a half-open window overlapping this one; pure adjacency — one window's end equal to the other's start — is allowed, and a genuine collision yields `ERR_CREW_WINDOW_OVERLAP`. Third, the eligibility count must be at least one: the eligible set is exactly those items of the job whose `processing_status` is `IN_STORAGE` and whose every specialty referral has reached `QA_ACCEPTED` — no fuzzy "ready" notion, the enum set is the filter — and an empty set yields `ERR_NO_ELIGIBLE_ITEMS_FOR_PACKBACK`. Fourth, no eligible item may carry an open handling claim — one in `FILED`, `UNDER_REVIEW`, or `APPROVED` status — else `ERR_OPEN_CLAIM_BLOCKS_PACKBACK`. On success the schedule moves to `CONFIRMED` and the `eligible_item_count` snapshot is stored.

Starting transit moves the schedule from `CONFIRMED` to `IN_TRANSIT` and sweeps every eligible item: each moves from `IN_STORAGE` to `PACKED_BACK`, its active placement is released with `release_reason` `PACK_BACK`, vault occupancy is decremented, and accrual is recomputed. The job's first schedule to enter `IN_TRANSIT` also moves the job's main status from `ACTIVE` to `PACKBACK_IN_PROGRESS`. Delivery moves the schedule from `IN_TRANSIT` to `DELIVERED` and marks all of the job's `PACKED_BACK` items `DELIVERED` — a terminal item state. Completion closes the schedule at `COMPLETED`, which is terminal. A confirmed schedule can instead be rescheduled: supplying a new `service_date`, `window_start_hour`, and `window_end_hour` — all three present and valid, with the end strictly after the start else `ERR_WINDOW_INVALID` — returns the schedule to `REQUESTED`, increments `reschedule_count` by one, and frees the crew window, since a `REQUESTED` schedule occupies no window. From `REQUESTED` or `CONFIRMED` a schedule may be cancelled outright, ending at the terminal `CANCELLED`.

### 3.6. Handling Claims: Filing, Adjudication, Settlement Variants

When an item is lost or damaged during handling, a `ProjectManager` or `InventoryTechnician` files a handling claim on it with a `claim_type` of `LOSS` or `DAMAGE`, a free-text `description` of what happened, a `replacement_cost_cents` of at least zero, and an `item_age_years` in whole years of at least zero. At most one open claim — one in `FILED`, `UNDER_REVIEW`, or `APPROVED` status — may exist per item. Filing stamps `filed_by_user_id` with the acting operator's identity, which anchors segregation of duties for the rest of the claim's life. The claim starts `FILED` with `settlement_variant` and `settlement_amount_cents` null and `credited_invoice_id` null. Claims are listed per item; separately, the claims credited to a given invoice can be listed via that invoice.

Adjudication belongs to the `ClaimsAdjuster`, and every transition carries an optional `review_note`. Submitting for review moves the claim from `FILED` to `UNDER_REVIEW`. Approval and denial both require the acting adjuster's identity to differ from `filed_by_user_id` — a self-decided claim is rejected with `ERR_SEGREGATION_OF_DUTIES`. Denial moves the claim to `DENIED`, and an appeal returns it from `DENIED` to `UNDER_REVIEW`; the appeal cycle may repeat. Approval moves the claim to `APPROVED` and triggers settlement computation. The `settlement_variant` is copied at that moment from the job's `policy_coverage_type`, resolved from the item through its room to the job, and `settlement_amount_cents` is computed per the variant.

Under the `ACV` variant, the settlement depreciates the replacement cost by age with a cap and a floor. The depreciation percentage is the item's `item_age_years` multiplied by 10 percent per year, capped at a maximum of 70 percent. The depreciated value is the `replacement_cost_cents` scaled down by that percentage — but never below a floor of 30 percent of the replacement cost. In other words, the settlement takes the larger of the age-depreciated value and the 30-percent floor, and the result is rounded half-up once at the end to integer cents. Under the `RCV` variant, the settlement is the full replacement cost capped at 250000 cents — unless the item has any specialty referral in `QA_ACCEPTED` status, in which case the settlement is the full replacement cost uncapped. Both variants produce integer cents; division uses exact rational arithmetic with a single half-up rounding at the end, and identical claim data yields different cents under the two variants.

An approved claim settles in one of two ways. A `ClaimsAdjuster` may settle it directly — again, the settler must differ from the filer, else `ERR_SEGREGATION_OF_DUTIES` — or the claim is swept automatically when a carrier invoice is submitted, as §3.8 describes. Either path moves the claim to the terminal `SETTLED` and cascades into the item: the item's `processing_status` becomes `CLAIM_SETTLED` from any non-terminal state, and if the item was `IN_STORAGE` its active placement is released with `release_reason` `CLAIM`, decrementing vault occupancy and recomputing provisional accrual and the job's `accrued_storage_total_cents`. On the invoice-sweep path the claim's `credited_invoice_id` is set to the submitting invoice; a directly settled claim keeps `credited_invoice_id` null. Alternatively, an approved claim that has not been swept may be voided — voiding requires `credited_invoice_id` still null, else `ERR_INVALID_TRANSITION` — moving it to the terminal `VOIDED` and undoing the approval under the claim-credit conservation invariant of §2.8.

### 3.7. Storage Statements, the Billing Run, and the Two Accrual Variants

The financial heart of the platform is the storage statement. A `BillingClerk` creates a statement for a job with a `period_start` and a `period_end`, the request carrying `expected_job_version` per §2.6 and optionally a `supersedes_statement_id`. The period is half-open: it covers from `period_start` up to but not including `period_end`, and the end must be strictly after the start, else `ERR_VALIDATION`. The non-voided statements of one job must have disjoint periods, and a job holds at most one `PROVISIONAL` statement at a time — unless the creation names that provisional statement in `supersedes_statement_id`, in which case the named statement is voided as the new one succeeds. This create-with-supersede is how a provisional period is corrected; any period overlap or duplicate-provisional violation is rejected with `ERR_VALIDATION`.

A statement is born `PROVISIONAL`, and while provisional its `provisional_total_cents` is computed — and recomputed on every placement activation or release touching the job — under the provisional variant of the storage accrual: a forward-looking, whole-month convention. Only placements currently `ACTIVE` whose `placed_on` falls before the statement's `period_end` participate. For each such placement, the charged span runs from the later of the placement's `placed_on` and the statement's `period_start` through `period_end`, and the charge is the placement's `monthly_rate_cents` snapshot multiplied by the number of distinct calendar months that span touches — any partial month counting as a full month, because the convention assumes continued occupancy. The `final_total_cents` stays null while the statement is provisional.

The billing run is the ops checkpoint that converts provisionals to finals. Executed by a `BillingClerk`, it finalizes every `PROVISIONAL` statement across all jobs whose `period_end` is on or before the logical clock's current date, computing each statement's `final_total_cents` under the final variant and moving it to `FINALIZED`. The run reports the `finalized_count` and the `finalized_statement_ids`. The final variant is a chronological daily proration over every placement — active or released — that occupied at least one day of the period. A placement occupies a given UTC date when its `placed_on` is on or before that date and the date falls before the earlier of its `released_on` and the statement's `period_end`, with the whole span intersected against the period. Each placement's daily rate is its `monthly_rate_cents` multiplied by 12 and divided by 365, rounded half-up once per placement per the pinned rounding order of §2.5; that rounded daily rate is then multiplied by the placement's occupied-day count, and the statement total is the sum of the per-placement charges. Because released placements participate and days rather than whole months are counted, the final figure generally differs from the provisional figure computed over identical placement data. Each finalization also recomputes the job's `accrued_storage_total_cents`. Statements are listed globally, filterable by `job_id` and/or `supersedes_statement_id`, and read individually.

A statement leaves `PROVISIONAL` in exactly three ways: supersession voids it (`VOIDED` being terminal), the billing run finalizes it, or — from `FINALIZED` — it is swept into a carrier invoice at invoice creation, becoming `INVOICED` (also terminal) as its `final_total_cents` contributes to that invoice's `storage_cents`.

### 3.8. Carrier Invoices: Sweep, Tiered Fee, Credit Pinning, and Reconciliation

With at least one finalized statement on a job, a `BillingClerk` creates a carrier invoice, optionally carrying an `adjustment_cents` — a carrier-agreed manual adjustment in cents that may be negative and defaults to zero. Creation is blocked while any statement of the job remains `PROVISIONAL`, and it requires at least one `FINALIZED` statement to sweep; violation is rejected with `ERR_STATEMENT_PERIOD_OPEN`. At creation, every `FINALIZED` statement of the job is swept: each becomes `INVOICED`, and the invoice's `storage_cents` is set to the sum of their `final_total_cents` values.

The invoice's administrative fee is tiered, and the evaluation order is pinned to break what would otherwise be a circular dependency. First the subtotal is formed as `storage_cents` plus `adjustment_cents`. Then the fee percentage is selected by that pre-fee subtotal — never by the post-fee total: 5 percent when the subtotal is below 100000 cents, 7 percent when it is at least 100000 and below 500000 cents, and 9 percent when it is at least 500000 cents. The `admin_fee_cents` is that percentage of the subtotal, rounded half-up to whole cents. The `total_cents` is the subtotal plus the fee — equivalently, `storage_cents` plus `adjustment_cents` plus `admin_fee_cents`. A new invoice starts `DRAFT` with `claim_credit_cents` zero and `amount_paid_cents` zero, and its `balance_cents` is always the total minus the claim credit minus the amount paid. Invoice creation recomputes the job's `billing_status`.

Submitting an invoice — a `BillingClerk` action — does the claim sweep. Every `APPROVED` handling claim of the job becomes `SETTLED` with its `credited_invoice_id` set to this invoice, the item-level claim-settlement cascade of §3.6 fires for each, and the invoice's `claim_credit_cents` is pinned to the sum of those claims' `settlement_amount_cents` values. The pin is a version-pinned snapshot: later claim changes never alter it. A disputed invoice may be resubmitted through the same action; resubmission re-sweeps any newly approved claims into the credit, accumulating onto the pinned figure, and moves the invoice back to `SUBMITTED`. Either submission recomputes the job's `billing_status`.

While `SUBMITTED`, the invoice faces the carrier. A `CarrierRepresentative` may dispute it — a `dispute_reason` is required, its absence rejected with `ERR_VALIDATION` — moving it to `DISPUTED` and setting the job's `billing_status` to `DISPUTED`. A `BillingClerk` records payments against a `SUBMITTED` or `DISPUTED` invoice: each `amount_cents` must be at least 1 — a smaller amount is rejected with `ERR_VALIDATION` — and no more than the current `balance_cents`, an excess rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`; the payment adds to `amount_paid_cents`, recomputes `balance_cents`, and leaves the invoice's status unchanged. When the balance reaches exactly zero cents, a `CarrierRepresentative` reconciles the invoice to its terminal `RECONCILED` state; reconciliation with any nonzero balance is rejected with `ERR_INVOICE_BALANCE_OUTSTANDING`. Dispute and reconciliation both recompute the job's `billing_status`.

That job-level `billing_status` is derived standing state: it reads `DISPUTED` if any of the job's invoices is `DISPUTED`; otherwise `RECONCILED` if the job has at least one invoice and every invoice is `RECONCILED`; otherwise `INVOICED` if any invoice is `SUBMITTED` or `RECONCILED`; otherwise `ACCUMULATING` — a `DRAFT` invoice alone never moves it off `ACCUMULATING`. Invoices are listed per job and read individually.

### 3.9. Job Closure

Closing a job is a `ProjectManager` action available from `INTAKE`, `ACTIVE`, or `PACKBACK_IN_PROGRESS`, and it is gated three ways. Every item of the job — reached through its rooms — must sit in a terminal processing state, `DELIVERED`, `DISPOSED`, or `CLAIM_SETTLED`; any non-terminal item yields `ERR_JOB_ITEMS_NOT_TERMINAL`. No statement of the job may remain `PROVISIONAL`, and no invoice may sit in `DRAFT`, `SUBMITTED`, or `DISPUTED`; either violation yields `ERR_INVALID_TRANSITION`. A closed job is terminal: all further mutations against it are rejected.

## 4. Endpoint Definitions

The API is mounted under `/api`. Resource creation endpoints return HTTP 201 with the created resource; read endpoints, transition endpoints, releases, billing runs, and the clock capability return HTTP 200. Every transition endpoint takes a request-body `action` field naming the verb to perform (for example `CLOSE`, `STRUCTURE_START`, `DOCUMENT`, `VERIFY`, `START`, `QA_PASS`, `QA_FAIL`, `REWORK`, `DISPATCH`, `RECEIVE`, `RETURN`, `QA_ACCEPT`, `QA_REJECT`, `SUBMIT_REVIEW`, `APPROVE`, `DENY`, `APPEAL`, `SETTLE`, `VOID`, `CONFIRM`, `START_TRANSIT`, `DELIVER`, `COMPLETE`, `RESCHEDULE`, `CANCEL`, `SUBMIT`, `RECORD_PAYMENT`, `DISPUTE`, `RECONCILE`), with the action-specific payload fields described in §3. Authorized roles below are exhaustive; any other role receives `ERR_FORBIDDEN_ROLE`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/pack-out-jobs | Create a pack-out job | ProjectManager |
| GET | /api/pack-out-jobs/{id} | Read a job with computed billing/rollup fields | ProjectManager, InventoryTechnician, BillingClerk, ClaimsAdjuster |
| POST | /api/pack-out-jobs/{id}/transition | Job lifecycle + structure actions: STRUCTURE_START, STRUCTURE_COMPLETE, STRUCTURE_RESCIND, CLOSE | ProjectManager |
| POST | /api/pack-out-jobs/{id}/rooms | Add a room to a job | ProjectManager |
| GET | /api/pack-out-jobs/{id}/rooms | List rooms of a job (paginated) | ProjectManager, InventoryTechnician, BillingClerk, ClaimsAdjuster |
| POST | /api/rooms/{id}/items | Register an inventoried item with photo/barcode | InventoryTechnician |
| GET | /api/items | List items, optionally filtered by room (paginated) | ProjectManager, InventoryTechnician, BillingClerk, ClaimsAdjuster |
| GET | /api/items/{id} | Read an item (both parallel state dimensions + high-value flag) | ProjectManager, InventoryTechnician, BillingClerk, ClaimsAdjuster |
| POST | /api/items/{id}/triage | Salvageable determination / OCC-guarded re-triage | InventoryTechnician |
| GET | /api/items/{id}/disposal-record | Fetch the item's disposal record (array of 0–1) | ProjectManager, InventoryTechnician |
| POST | /api/disposal-records/{id}/transition | DOCUMENT (InventoryTechnician) / VERIFY (ProjectManager, SoD-checked) | InventoryTechnician, ProjectManager |
| POST | /api/items/{id}/cleaning-tasks | Schedule cleaning; process derived from category; artwork rejected | InventoryTechnician |
| GET | /api/items/{id}/cleaning-tasks | List cleaning tasks of an item | ProjectManager, InventoryTechnician |
| POST | /api/cleaning-tasks/{id}/transition | START, QA_PASS, QA_FAIL, REWORK (rework cycle) | InventoryTechnician |
| POST | /api/vaults | Register a storage vault | ProjectManager |
| GET | /api/vaults/{id} | Read a vault incl. computed occupancy and posture | ProjectManager, InventoryTechnician, BillingClerk |
| POST | /api/items/{id}/placements | Activate placement of a cleaned item into a vault (all gates) | InventoryTechnician |
| GET | /api/items/{id}/placements | List placements of an item | ProjectManager, InventoryTechnician, BillingClerk |
| GET | /api/vaults/{id}/placements | List placements in a vault | ProjectManager, InventoryTechnician, BillingClerk |
| POST | /api/storage-placements/{id}/release | Manual release of an active placement (reason MANUAL) | InventoryTechnician |
| POST | /api/subcontractors | Register a specialty subcontractor | ProjectManager |
| GET | /api/subcontractors/{id} | Read a subcontractor incl. active referral count | ProjectManager, InventoryTechnician |
| POST | /api/items/{id}/specialty-referrals | Create a specialty referral for an item | ProjectManager |
| GET | /api/specialty-referrals | List referrals, filterable by item and/or subcontractor | ProjectManager, InventoryTechnician, SubcontractorContact |
| GET | /api/specialty-referrals/{id} | Read a referral | ProjectManager, InventoryTechnician, SubcontractorContact |
| POST | /api/specialty-referrals/{id}/transition | DISPATCH / RECEIVE / RETURN / QA_ACCEPT / QA_REJECT | ProjectManager, SubcontractorContact |
| POST | /api/specialty-referrals/{id}/custody-events | Append a chain-of-custody event (strictly increasing timestamp) | InventoryTechnician, SubcontractorContact |
| GET | /api/specialty-referrals/{id}/custody-events | List custody events of a referral in sequence order | ProjectManager, InventoryTechnician, SubcontractorContact |
| POST | /api/items/{id}/handling-claims | File a loss/damage claim on an item (one open claim per item) | ProjectManager, InventoryTechnician |
| GET | /api/items/{id}/handling-claims | List claims on an item | ProjectManager, InventoryTechnician, ClaimsAdjuster |
| GET | /api/carrier-invoices/{id}/handling-claims | List claims credited to an invoice | BillingClerk, ClaimsAdjuster, CarrierRepresentative |
| POST | /api/handling-claims/{id}/transition | SUBMIT_REVIEW, APPROVE, DENY, APPEAL, SETTLE, VOID | ClaimsAdjuster |
| POST | /api/pack-out-jobs/{id}/pack-back-schedules | Request a pack-back schedule (crew window) | ProjectManager |
| GET | /api/pack-out-jobs/{id}/pack-back-schedules | List pack-back schedules of a job | ProjectManager, InventoryTechnician |
| POST | /api/pack-back-schedules/{id}/transition | CONFIRM, START_TRANSIT, DELIVER, COMPLETE, RESCHEDULE, CANCEL | ProjectManager |
| POST | /api/pack-out-jobs/{id}/storage-statements | Create a provisional statement (OCC; create-with-supersede) | BillingClerk |
| GET | /api/storage-statements | List statements, filterable by job and/or supersession | BillingClerk, ProjectManager |
| GET | /api/storage-statements/{id} | Read a statement | BillingClerk, ProjectManager |
| POST | /api/billing-runs | Finalize every provisional statement whose period has elapsed | BillingClerk |
| POST | /api/pack-out-jobs/{id}/carrier-invoices | Create a draft invoice sweeping finalized statements | BillingClerk |
| GET | /api/pack-out-jobs/{id}/carrier-invoices | List invoices of a job | BillingClerk, ProjectManager, CarrierRepresentative |
| GET | /api/carrier-invoices/{id} | Read an invoice | BillingClerk, ProjectManager, CarrierRepresentative |
| POST | /api/carrier-invoices/{id}/transition | SUBMIT, RECORD_PAYMENT, DISPUTE, RECONCILE | BillingClerk, CarrierRepresentative |
| POST | /_clock/set_current_utc | Set the server logical clock | ProjectManager, InventoryTechnician, BillingClerk |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NOT_REFERRAL_SUBCONTRACTOR | 403 |
| ERR_VALIDATION | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_ITEM_VERSION | 412 |
| ERR_STALE_JOB_VERSION | 412 |
| ERR_INVALID_TRANSITION | 409 |
| ERR_ITEM_TERMINAL | 409 |
| ERR_ITEM_NOT_SALVAGEABLE | 409 |
| ERR_JOB_ITEMS_NOT_TERMINAL | 409 |
| ERR_JOB_NOT_READY_FOR_PACKBACK | 409 |
| ERR_NO_ELIGIBLE_ITEMS_FOR_PACKBACK | 422 |
| ERR_OPEN_CLAIM_BLOCKS_PACKBACK | 409 |
| ERR_STATEMENT_PERIOD_OPEN | 409 |
| ERR_HAZMAT_STORAGE_FORBIDDEN | 422 |
| ERR_CLIMATE_CLASS_INCOMPATIBLE | 422 |
| ERR_HAZMAT_MANIFEST_REQUIRED | 422 |
| ERR_VAULT_CAPACITY_EXCEEDED | 422 |
| ERR_DUPLICATE_BARCODE | 409 |
| ERR_SUBCONTRACTOR_AT_CAPACITY | 422 |
| ERR_CREW_WINDOW_OVERLAP | 422 |
| ERR_WINDOW_INVALID | 422 |
| ERR_CUSTODY_EVENT_OUT_OF_ORDER | 422 |
| ERR_SPECIALTY_REQUIRED | 422 |
| ERR_PAYMENT_EXCEEDS_BALANCE | 422 |
| ERR_INVOICE_BALANCE_OUTSTANDING | 422 |
