# Midwifery Birth Center API — Product Requirements Document

## 1. Introduction

The Midwifery Birth Center API is the operational backbone of a community birth center that blends doula support, midwifery care, and out-of-hospital delivery. It coordinates the full arc of a pregnant client's journey: intake and care-plan selection, the prenatal-visit schedule and its ongoing risk screening, birth on-call coverage with backup providers, room booking and the occasional hospital transfer, postpartum and lactation follow-up, and the billing tail of global-fee insurance claims and installment payment plans. The clinical and financial sides of a single episode of care evolve on their own timelines, and the API is built around that reality rather than forcing the two into a single linear workflow.

Two pressures shape almost every rule in this system. The first is clinical safety: a client whose screening crosses a transfer threshold must not deliver at the center, and the API enforces that gate at every clinical milestone. The second is fiscal accuracy: a global fee that is bundled, insured, partially adjudicated, or written off must always reconcile to an exact client-responsibility balance measured in whole cents, and a payment plan built on that balance must never lose or invent a single cent. Because care providers, billing staff, and center administrators act on overlapping data, the system also defends against stale reads at the two points where a snapshot is frozen into a downstream record. This document specifies the entities, lifecycles, calculations, and access rules that together make those guarantees hold.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When both headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as `IntakeCoordinator`, `Midwife`, `BillingClerk`, and `CenterAdmin`. An `IntakeCoordinator` owns client intake, episode opening, and visit scheduling. A `Midwife` owns the clinical lifecycle — activation, screening completion, birth recording, hospital transfer, and care completion. A `BillingClerk` owns the financial lifecycle — charges, insurance claims, payment plans, and write-offs. A `CenterAdmin` is the operational superset that manages rooms, providers, supply kits, care packages, the on-call roster, room bookings, and the server's logical clock. Read access through any `GET` endpoint is open to all four roles. The detailed authorization for each endpoint is given in the table of Section 4.

All four roles carry an **opaque** identity. When `X-User-Role` is `IntakeCoordinator`, `Midwife`, `BillingClerk`, or `CenterAdmin`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`, and ownership of a resource is therefore never decided by matching `X-User-ID` against a stored foreign key. Authorization is purely role-based.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. Out-of-range values are clamped rather than rejected: a supplied `limit` below 1 is treated as 1 and a `limit` above 100 is treated as 100, and a negative `offset` is treated as 0. A `limit` or `offset` that is present but not an integer is rejected with `ERR_INVALID_REQUEST` (HTTP 422). The `offset` parameter sets how many items to skip from the start of the result set and defaults to 0.

Unless an endpoint explicitly states otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system share a set of server-managed fields. Every such resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits, an `updated_at` timestamp in the same format that is refreshed on every mutation, and an integer `version` that begins at its initial value and increments by one with each mutation of the resource. The entities that carry this full set are `Client`, `SupplyKit`, `Provider`, `Room`, `Episode`, `PrenatalVisit`, `OnCallAssignment`, `Booking`, `InsuranceClaim`, `Charge`, and `PaymentPlan`.

The one exception is `CarePackage`, which is a configuration entity — a price-list entry that is immutable once created. A `CarePackage` carries only `id` and `created_at`; it has no `updated_at` and no `version`, because it is never modified after creation. Note that for the lookup endpoints the `id` of a `CarePackage` is its `code`, and the `id` of a `SupplyKit` is its `sku`.

Whenever a derived field changes as a side effect of some operation — for example when an `Episode`'s `balance_due_cents` or `risk_tier` is recomputed — that change is a genuine mutation of the affected resource: its `updated_at` is refreshed and its `version` increments by one. Cascades that touch several resources increment the `version` of each resource they actually mutate.

### 2.5. Resource Existence and Left-to-Right Path Validation

Before any business rule runs, the system confirms that every resource referenced by the request exists. This applies both to identifiers embedded in the URL path and to foreign-key references carried in the request body — `client_id`, `package_code`, `room_id`, `provider_id`, `episode_id`, `claim_id`, and `kit_sku` among them. When a path nests identifiers, they are validated left to right, and the first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` (HTTP 404) before any later identifier or body field is examined. A request that references a missing resource never proceeds to state or business checks.

### 2.6. Validation Ordering

When several checks could apply to a single request, they are evaluated in a fixed priority order so that the same failing request always yields the same error. Authentication is checked first: a request lacking the required headers fails with `ERR_UNAUTHENTICATED` before anything else. Role authorization is checked second, yielding `ERR_FORBIDDEN_ROLE`. Resource existence is checked third, yielding `ERR_NOT_FOUND`. Request well-formedness is checked fourth — required fields present, enum values valid, and integer constraints satisfied (a `parity` of at least 0, an `amount_cents` of at least 0, an `installment_count` of at least 1) — with any violation producing `ERR_INVALID_REQUEST` (HTTP 422). On the two creation endpoints that enforce uniqueness, the duplicate check sits fifth, producing `ERR_DUPLICATE_RESOURCE` (HTTP 409): a `CarePackage` whose `code` already exists, or a `SupplyKit` whose `sku` already exists, is rejected here. State-validity for a requested transition is checked sixth, producing `ERR_INVALID_STATE` (HTTP 409). The domain-specific business and safety rules described throughout Section 3 are evaluated after these foundational layers, each with its own dedicated error code. Optimistic-concurrency version checks sit at the tail of this order, after the foundational checks have passed.

### 2.7. Monetary Precision and Rounding

All monetary quantities in the system are stored and computed as integer cents — `global_fee_cents`, `amount_cents`, `client_responsibility_cents`, `balance_due_cents`, `total_cents`, `paid_cents`, `remaining_cents`, `billed_amount_cents`, `allowed_amount_cents`, and `paid_amount_cents` are all whole-cent integers. The only calculation that introduces a fraction is the self-pay estimate of the global fee, and that single multiplication is rounded half up to the nearest whole cent. All counts — visit counts, assignment counts, kit counters, installment counts — are likewise exact integers. No value in the system is ever stored as a floating-point dollar amount.

### 2.8. Optimistic Concurrency Control

Two creation endpoints freeze a snapshot of a parent resource into a new child record, and both are guarded against stale reads by an optimistic-concurrency version field. The general rule: the named create request must carry a version field naming the client's last observed `version` of the relevant parent, and if that value does not equal the parent's current `version` the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints that are not named below take no version field at all.

The first guard protects payment-plan creation. A request to create a payment plan must carry `expected_episode_version` holding the client's last observed `version` of the target `Episode`. A payment plan snapshots the episode's `balance_due_cents` into its own `total_cents` at the moment of creation; if another writer has adjudicated, denied, or voided a claim — each of which re-derives `balance_due_cents` and advances `Episode.version` — since the client last read the episode, the client's view of the balance is stale and the plan would lock in a wrong total. When `expected_episode_version` does not match the episode's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the episode before retrying.

The second guard protects booking creation. A request to create a booking must carry `expected_room_version` holding the client's last observed `version` of the target `Room`. A room's occupancy footprint changes whenever another writer creates or cancels a booking on it, and each such write advances `Room.version`. A booking request carrying a stale `expected_room_version` computed its non-overlap against an out-of-date picture of the room's bookings, so when `expected_room_version` does not match the room's current `version` the create is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the room's current bookings before retrying.

### 2.9. The Logical Clock

The server keeps a single logical clock that governs every time-of-day comparison in the system — whether a visit is past due, whether a booking may be checked in, and any other "current time" decision. On startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it stays at that default; it never falls back to wall-clock time. A `CenterAdmin` may advance the clock by supplying a target instant in the `to_iso8601` field, and the response (HTTP 200) reports the new value of `now` as a single `now` field in the response `data` object holding the supplied instant verbatim. All temporal preconditions described in Section 3 are evaluated against this logical clock, not against real-world time.

### 2.10. Supply-Kit Availability

Each `SupplyKit` tracks three figures: `on_hand_count`, the units physically in stock; `reserved_count`, the units currently held by episodes that have reserved but not yet consumed them; and `consumed_count`, the units used up by episodes whose care has reached the kit-consuming milestones. Equivalently, grouping the episodes that reserved a given kit by their `clinical_status`: `reserved_count` is the number of those episodes whose `clinical_status` is `PLANNING` or `ACTIVE`, while `consumed_count` is the number whose `clinical_status` is `BORN`, `COMPLETED`, or `TRANSFERRED`. A kit's available quantity is its `on_hand_count` minus its `reserved_count`, and that available quantity must never drop below zero — any reservation that would drive it negative is refused. The reconciliation that keeps these counters honest is described alongside the episode lifecycle in Section 3, where the reserve and consume moments live.

## 3. Business Logic & Workflows

### 3.1. Intake: Clients, Packages, Kits, and Episode Opening

A client's relationship with the center begins when an `IntakeCoordinator` registers them, supplying the `full_name`, the `date_of_birth`, and the `parity` (the number of prior births, which must be at least 0). Insurance details are optional at intake: `insurance_payer` and `policy_number` may be provided, and when they are omitted they default to the empty string, which the system reads as self-pay. A newly registered client opens in `ACTIVE` `status`. An `IntakeCoordinator` may later archive a client, moving `status` to `ARCHIVED`; archival is a soft action that preserves the record.

Before episodes can be opened, a `CenterAdmin` configures the supporting catalog. A care package is a price-list entry identified by a unique `code` (for example `BIRTH_FULL`); duplicate codes are refused with `ERR_DUPLICATE_RESOURCE`. Each package declares a `package_type` of `BIRTH`, `POSTPARTUM`, or `COMBINED`; a bundled `global_fee_cents` (at least 0); the counts `prenatal_visits_included` and `postpartum_visits_included` that are folded into the global fee (each at least 0); and a `kit_sku` naming the birth kit bundled with the package. Care packages are immutable once created. A supply kit is created with a unique `sku` (duplicates refused with `ERR_DUPLICATE_RESOURCE`), a display `name`, and an initial `on_hand_count`; its `reserved_count` and `consumed_count` both begin at 0.

An `IntakeCoordinator` opens an **episode of care** by naming the `client_id`, the `package_code`, and the estimated due date `edd`. Opening an episode does a great deal of work at once. The episode starts with `clinical_status` of `PLANNING`, `financial_status` of `UNBILLED`, and `risk_tier` of `LOW`. It snapshots the chosen package's `global_fee_cents` into its own `global_fee_cents` field. It reserves one unit of the package's birth kit: the kit's `reserved_count` increases by one and the episode's `kit_issued` flag becomes true. If no unit is available — that is, if reserving would drive the kit's `on_hand_count` minus `reserved_count` below zero — the open is refused with `ERR_KIT_OUT_OF_STOCK` (HTTP 409). Finally, opening creates the bundled global-fee charge: a `Charge` of `charge_kind` `GLOBAL_FEE` in `DRAFT`, with `amount_cents` equal to the snapshotted `global_fee_cents`, and its `client_responsibility_cents` computed by the estimate variant described in Section 3.6. The episode also exposes the computed counters `prenatal_visits_completed` (starting at 0) and `balance_due_cents`.

### 3.2. The Clinical Axis of an Episode

Every episode carries two independent status axes on the same record, and `clinical_status` is the first of them. It moves through `PLANNING`, `ACTIVE`, `TRANSFERRED`, `BORN`, and `COMPLETED`, with `COMPLETED` the only terminal clinical state. The `Midwife` drives this axis.

A `Midwife` begins active care, transitioning `clinical_status` from `PLANNING` to `ACTIVE`. This is permitted only when the episode is currently in `PLANNING`, when a kit unit has already been reserved (`kit_issued` is true), and when the episode's `risk_tier` is not `TRANSFER_REQUIRED`. The risk gate is a clinical-safety check: an episode whose latest screening demands a hospital transfer cannot be activated, and the attempt is refused with `ERR_RISK_TRANSFER_REQUIRED` (HTTP 409). An activation attempt from any state other than `PLANNING` is refused with `ERR_INVALID_STATE`.

Recording a birth at the center advances `clinical_status` from `ACTIVE` to `BORN`. Two conditions gate it, and they are evaluated in this fixed order after the state check. First, the episode's `risk_tier` must not be `TRANSFER_REQUIRED` — a client who has crossed the transfer threshold must be moved to a hospital rather than delivered at the center, and the attempt is otherwise refused with `ERR_RISK_TRANSFER_REQUIRED`. Second, the episode must have a booking that is currently `IN_USE`; without one the request is refused with `ERR_NO_ACTIVE_BOOKING` (HTTP 409). When both conditions fail together, the `ERR_RISK_TRANSFER_REQUIRED` from the first-evaluated risk gate is the error returned. When the birth is recorded, the `IN_USE` booking cascades to `COMPLETED` (releasing its room and freeing the room interval at the booking's `ends_at`), the episode's reserved kit unit is treated as consumed so the kit's `reserved_count` decreases by one and its `consumed_count` increases by one, and the bundled global-fee charge — held in `DRAFT` — becomes billable, meaning it remains in `DRAFT` status (its status is not changed automatically; marking it `BILLED` is a separate explicit `BillingClerk` action). The episode's `version` increments.

Completing care advances `clinical_status` from `BORN` to `COMPLETED`. This is allowed only when the postpartum follow-up has been fulfilled: the episode's `prenatal_visits_completed` must be at least the package's `postpartum_visits_included`. If too few qualifying visits have been completed the request is refused with `ERR_POSTPARTUM_INCOMPLETE` (HTTP 409); from any state other than `BORN` it is refused with `ERR_INVALID_STATE`.

A hospital transfer is the branch off the normal path, available while the episode is in either `PLANNING` or `ACTIVE` and driving `clinical_status` to `TRANSFERRED`; from any other clinical state it is refused with `ERR_INVALID_STATE`. A transfer fans out a coordinated set of cascades, all detailed in Section 3.8.

### 3.3. Prenatal Visits and the Risk Screening Loop

Visits are scheduled by either an `IntakeCoordinator` or a `Midwife`, who name the `episode_id`, the `visit_kind` (one of `PRENATAL`, `POSTPARTUM`, or `LACTATION`), and the appointment time `scheduled_at`. A visit opens in `SCHEDULED` `status` and may end up `COMPLETED`, `NO_SHOW`, or `CANCELLED`, with `CANCELLED` as the terminal state. The `blood_pressure_systolic` reading and the screening outcome `risk_flag` are both null until the visit is completed.

A `Midwife` completes a scheduled visit, supplying the screening outcome `risk_flag` (one of `NONE`, `WATCH`, or `TRANSFER`) and optionally the `blood_pressure_systolic` reading; these are persisted as the visit moves from `SCHEDULED` to `COMPLETED`. Completion is barred when the owning episode's `clinical_status` is already `TRANSFERRED` or `COMPLETED`; in that case the request is refused with `ERR_INVALID_STATE`, as it is for any visit not currently `SCHEDULED`. Completing a visit increments the visit's `version` and increments the episode's `version`, and it re-derives the episode's `risk_tier` from the episode's completed visits (the calculation appears in Section 3.7). This re-derivation is cyclic: a later visit may push the tier up or pull it back down. Should the re-derived `risk_tier` reach `TRANSFER_REQUIRED` while the episode is `ACTIVE`, the system performs no automatic transfer, but the episode is thereby barred from having a birth recorded until a transfer is carried out.

A scheduled visit that the client misses can be marked a no-show by a `Midwife`, moving `status` from `SCHEDULED` to `NO_SHOW`; this is allowed only once the logical clock has reached or passed the visit's `scheduled_at`, and only on a visit still in `SCHEDULED`. Separately, a scheduled visit may be cancelled by either a `Midwife` or an `IntakeCoordinator`, moving `status` from `SCHEDULED` to `CANCELLED`. Each of these transitions increments the visit's `version`. Only visits in `COMPLETED` status count toward the episode's `prenatal_visits_completed` and toward the risk derivation; visits in `SCHEDULED`, `NO_SHOW`, or `CANCELLED` are excluded from both.

### 3.4. Birth On-Call Coverage and Backups

On-call coverage is arranged by a `CenterAdmin`. Providers — midwives and doulas eligible for on-call — are created with a `full_name`, a `role_type` of `MIDWIFE` or `DOULA`, a `license_number`, and a `max_active_episodes` ceiling (at least 1) that caps how many episodes the provider may primarily cover at once. A provider opens in `AVAILABLE` `status` with an `active_assignment_count` of 0; the `status` field ranges over `AVAILABLE` and `UNAVAILABLE`, the latter marking a provider who is not eligible to take new coverage.

A primary on-call assignment is created by naming the `episode_id`, the `provider_id`, and the coverage window's `coverage_start` and `coverage_end`. The new assignment takes `coverage_role` `PRIMARY` and `status` `ASSIGNED`, its `backup_assignment_id` null until a backup is named, and the provider's `active_assignment_count` increments by one. Two gates guard the create. The provider's **primary load** must be below `max_active_episodes` before the assignment is admitted; a provider already at the ceiling is refused with `ERR_PROVIDER_AT_CAPACITY` (HTTP 409). And the new coverage window must not overlap any of that provider's existing primary windows — the overlap rule, with its closed-interval semantics, is given in Section 3.9 — with a conflict refused as `ERR_PROVIDER_WINDOW_OVERLAP` (HTTP 409).

A provider's **primary load** — the figure persisted in `active_assignment_count` and used to gate new primary assignments — is the number of that provider's assignments that currently carry active primary coverage. It counts every assignment for the provider that is either a `PRIMARY` row in `ASSIGNED` or `ON_DUTY`, or a `BACKUP` row that has been promoted to `PROMOTED`, because a promoted backup is now itself carrying primary coverage. A `BACKUP` row still sitting in `ASSIGNED` does not count toward primary load. Separately, a provider's **coverage load** is a wider roster-reporting figure that counts every assignment for the provider in `ASSIGNED`, `ON_DUTY`, or `PROMOTED` regardless of `coverage_role`; it differs from primary load precisely by including a backup row still in `ASSIGNED`. Only the primary load is persisted in `active_assignment_count` and only the primary load gates the capacity check.

A primary assignment can be given a backup. Naming a backup creates a second `OnCallAssignment` for the same episode with `coverage_role` `BACKUP` and `status` `ASSIGNED`, over a coverage window supplied as `coverage_start` and `coverage_end`, on the named `provider_id`; the primary's `backup_assignment_id` is then set to the new backup's `id`. The backup provider must differ from the primary's provider: a backup that names the primary's own provider is refused with `ERR_BACKUP_SAME_PROVIDER` (HTTP 409). The only validation gate on naming a backup, beyond the existence of the named assignment and provider, is this distinct-provider check; naming a backup is otherwise permitted regardless of the primary assignment's current `status` or `coverage_role` and never re-checks the named provider's capacity. Backup rows do not consume primary capacity and are not subject to the primary-window overlap check.

A primary assignment moves on duty when the `CenterAdmin` advances it from `ASSIGNED` to `ON_DUTY`; this requires that the assignment be `PRIMARY` and `ASSIGNED` and that the covered episode's `clinical_status` be `ACTIVE`. A primary assignment is released when coverage is no longer needed, moving from either `ASSIGNED` or `ON_DUTY` to `RELEASED`; release requires that the assignment be `PRIMARY` and that the episode's `clinical_status` be one of `BORN`, `COMPLETED`, or `TRANSFERRED`, and it decrements the provider's `active_assignment_count` by one. The states `RELEASED` and `STOOD_DOWN` are terminal. The `PROMOTED` state is reached only by a backup whose primary was stood down, and `STOOD_DOWN` is reached only by the transfer cascade; both are system transitions described in Section 3.8. Any of these on-call transitions attempted from a disallowed state is refused with `ERR_INVALID_STATE`, and each increments the assignment's `version`.

### 3.5. Room Booking and the Birth-Center Stay

Rooms are created by a `CenterAdmin` with a `name` and an optional `turnover_minutes` cleaning buffer (defaulting to 0) that the center enforces after each booking before the next may begin. A room opens in `OPEN` `status`; a `CenterAdmin` may close it, moving `status` to `CLOSED`, after which it rejects new bookings.

A booking ties an episode to a room over a time interval. It is created by naming the `episode_id`, the `room_id`, the interval's `starts_at` and `ends_at`, and the optimistic-concurrency field `expected_room_version` discussed in Section 2.8. A new booking opens in `HELD` `status` and advances the room's `version` by one. Three checks guard the create. The interval must be well-formed: `starts_at` must fall strictly before `ends_at`, and a zero-length or inverted interval is refused with `ERR_INVALID_INTERVAL` (HTTP 422). The interval must not collide with an existing non-terminal booking on the same room once the room's turnover buffer is taken into account; a collision is refused with `ERR_ROOM_DOUBLE_BOOKED` (HTTP 409), and the exact overlap semantics are given in Section 3.9. And the room version supplied must be current, else `ERR_STALE_VERSION`.

A booking proceeds through its lifecycle as the stay unfolds. A `CenterAdmin` confirms a held booking, moving `status` from `HELD` to `CONFIRMED`, which requires the room's `status` to be `OPEN`. The `CenterAdmin` then checks in, moving `status` from `CONFIRMED` to `IN_USE`; check-in requires that the episode's `clinical_status` be `ACTIVE` and that the logical clock have reached or passed the booking's `starts_at`. A booking in `HELD` or `CONFIRMED` may be cancelled by a `CenterAdmin`, moving `status` to `CANCELLED`, which releases the room interval and advances the room's `version` by one. A booking has six possible `status` values — `HELD`, `CONFIRMED`, `IN_USE`, `COMPLETED`, `TRANSFERRED`, and `CANCELLED` — of which `COMPLETED`, `TRANSFERRED`, and `CANCELLED` are terminal, representing the two success endings (birth at the center versus hospital transfer) and the abandoned hold respectively. The move to `COMPLETED` is driven by the record-birth cascade (Section 3.2), which releases the room interval at the booking's `ends_at`; the move to `TRANSFERRED` is driven by the transfer cascade (Section 3.8), which releases the room interval immediately and creates the transfer-fee charge. Each booking transition increments the booking's `version`, and any transition attempted from a disallowed state is refused with `ERR_INVALID_STATE`.

### 3.6. The Financial Axis: Charges, Claims, and Client Responsibility

An episode's `financial_status` is its second, independent axis, moving through `UNBILLED`, `PLAN_ACTIVE`, `SETTLED`, and `WRITTEN_OFF`, with `SETTLED` and `WRITTEN_OFF` terminal. It evolves entirely separately from `clinical_status`, and the `BillingClerk` drives most of it.

A `BillingClerk` may add out-of-bundle charges to an episode by naming the `episode_id`, the `charge_kind`, and the `amount_cents`. Such charges are of kind `EXTRA_VISIT` or `SUPPLY`, open in `DRAFT` `status`, and — like all non-global charges — carry full client responsibility, so their `client_responsibility_cents` equals their `amount_cents`. Adding a charge re-derives the episode's `balance_due_cents` and increments the episode's `version`. A `DRAFT` charge may be marked `BILLED` by a `BillingClerk`. A charge has four `status` values — `DRAFT`, `BILLED`, `PAID`, and `VOID`. The `charge_kind` enumeration is `GLOBAL_FEE`, `EXTRA_VISIT`, `SUPPLY`, and `TRANSFER_FEE`; the transfer-fee variety is created only by the transfer cascade, never directly. A charge created against a claim records that claim in its `claim_id`, which is otherwise the empty string for self-pay or extra charges.

The single global-fee charge per episode is where insurance enters. The `client_responsibility_cents` on that charge is computed in one of three variants depending on the state of the linked insurance claim. In the **estimate** variant — used when no claim has yet adjudicated, meaning either there is no claim or the claim is still `SUBMITTED` — the client responsibility is the gross global fee multiplied by the self-pay estimate fraction of 0.20 (that is, twenty percent), with the product rounded half up to a whole cent. In the **adjudicated** variant — used once the claim is `ADJUDICATED` — the client responsibility is the claim's `allowed_amount_cents` minus its `paid_amount_cents`. In the **denied** variant — used when the claim is `DENIED` — the client owes the entire gross global fee, so the client responsibility equals the charge's `amount_cents`. For every charge that is not a global fee (`EXTRA_VISIT`, `SUPPLY`, or `TRANSFER_FEE`), client responsibility is always the full `amount_cents`, never insured.

A `BillingClerk` submits a global-fee insurance claim for an episode by naming the `episode_id`. The new claim opens in `SUBMITTED` `status`, snapshots the episode's `global_fee_cents` into its own `billed_amount_cents`, and links the episode's global-fee charge by setting that charge's `claim_id` to the new claim. A claim's `status` ranges over `SUBMITTED`, `ADJUDICATED`, `DENIED`, and `VOID`, with `VOID` terminal. The claim also carries `allowed_amount_cents` and `paid_amount_cents`, which are entered at adjudication.

Adjudicating a claim moves it from `SUBMITTED` to `ADJUDICATED`, with the `BillingClerk` supplying the `allowed_amount_cents` and `paid_amount_cents`. These amounts must respect the ordering that the paid amount is at most the allowed amount and the allowed amount is at most the claim's `billed_amount_cents`; a request that breaks `paid_amount_cents` ≤ `allowed_amount_cents` ≤ `billed_amount_cents` is refused with `ERR_CLAIM_AMOUNTS_INVALID` (HTTP 422). Adjudication cascades into billing: the episode's global-fee charge's `client_responsibility_cents` is recomputed by the adjudicated variant (the allowed amount minus the paid amount), which re-derives the episode's `balance_due_cents` and increments the episode's `version`; the claim's own `version` also increments. Denying a claim moves it from `SUBMITTED` to `DENIED` and cascades the denied variant: the global-fee charge's `client_responsibility_cents` becomes the full `amount_cents`, the episode's `balance_due_cents` is re-derived, and the episode's `version` increments alongside the claim's. Voiding a claim moves it from `SUBMITTED` or `DENIED` to `VOID`; it is permitted only when no payment plan exists on the episode, since a plan built on the balance must not be undermined — a void attempted while a plan exists is refused with `ERR_CLAIM_HAS_PLAN` (HTTP 409). Voiding reverts the global-fee charge's `client_responsibility_cents` to the estimate variant (the gross global fee times 0.20, rounded half up), re-derives the episode's `balance_due_cents`, and increments both the episode's `version` and the claim's `version`. In each of these three claim cascades (adjudicate, deny, void), the only versions advanced are the episode's and the claim's; the global-fee charge whose `client_responsibility_cents` is recomputed does not have its own `version` incremented (nor its `updated_at` refreshed) by the cascade. Any claim transition attempted from a disallowed state is refused with `ERR_INVALID_STATE`.

### 3.7. Deriving the Episode Risk Tier

The episode's `risk_tier` — one of `LOW`, `ELEVATED`, or `TRANSFER_REQUIRED` — is a computed reflection of the screening recorded across the episode's visits. It is re-derived every time a visit is completed, and it considers only the episode's visits in `COMPLETED` status; `SCHEDULED`, `NO_SHOW`, and `CANCELLED` visits are ignored. With no completed visits, the tier is `LOW`.

The derivation draws three figures from the completed visits. The first is the worst screening flag among them, where the flags are ordered with `NONE` lowest, `WATCH` in the middle, and `TRANSFER` highest. The second is the highest `blood_pressure_systolic` recorded among them, treated as 0 if none was recorded. The third is the count of completed visits whose `risk_flag` is `WATCH`. The tier is then chosen by the first matching rule, evaluated top to bottom: if the worst flag is `TRANSFER`, the tier is `TRANSFER_REQUIRED`; otherwise if the highest systolic reading is at least 160, the tier is `TRANSFER_REQUIRED`; otherwise if the worst flag is `WATCH` and the number of watch-flagged visits is at least 2, the tier is `TRANSFER_REQUIRED`; otherwise if the worst flag is `WATCH`, the tier is `ELEVATED`; otherwise if the highest systolic reading is at least 140, the tier is `ELEVATED`; otherwise the tier is `LOW`. All of these comparisons are exact integer comparisons with inclusive boundaries — a systolic reading of exactly 160 already requires transfer, and a reading of exactly 140 already raises the tier to elevated.

### 3.8. The Hospital-Transfer Cascade

A hospital transfer is the most consequential single action in the system, because it simultaneously resolves the episode's room, its on-call coverage, its kit, and its billing. When a `Midwife` transfers an episode (permitted from `PLANNING` or `ACTIVE`), the episode's `clinical_status` moves to `TRANSFERRED`, its `version` increments, and the following cascades fire together.

The episode's active room booking, if it is in `HELD`, `CONFIRMED`, or `IN_USE`, moves to `TRANSFERRED`. That booking transition fires its own side effects: it releases the room interval immediately, and it creates a new `Charge` of `charge_kind` `TRANSFER_FEE` in `DRAFT` on the episode, with `amount_cents` equal to the fixed transfer fee of 75,000 cents (that is, seven hundred fifty dollars), and the booking's own `version` increments.

The episode's primary on-call assignment, if it is in `ASSIGNED` or `ON_DUTY`, is stood down to `STOOD_DOWN`. Standing a primary down decrements that primary provider's `active_assignment_count` by one. If that primary names a backup through its `backup_assignment_id`, the referenced backup assignment — a `BACKUP` row in `ASSIGNED` — is promoted to `PROMOTED`, and the promotion increments the backup provider's `active_assignment_count` by one. In effect the coverage hands off from the departing primary to its named backup as part of the same transfer.

The kit reserved for this episode is treated as consumed and is non-recoverable once transfer occurs: the kit's `reserved_count` decreases by one and its `consumed_count` increases by one. (This mirrors record-birth, where the reserved unit is likewise consumed; the contrast is with a write-off, where no kit movement occurs.) Taken together, the transfer cascade closes the clinical episode at the center, releases the room, reshuffles on-call coverage, books the transfer fee, and finalizes the kit — each affected resource having its own `version` advanced.

### 3.9. Temporal Overlap Rules: Coverage Windows and Room Intervals

Two distinct overlap rules govern time in this system, and they use deliberately different interval semantics.

On-call coverage windows use **closed-interval** semantics across the span `[coverage_start, coverage_end]`. A new primary coverage window must not overlap any existing primary window of the same provider drawn from that provider's assignments in `ASSIGNED`, `ON_DUTY`, or `PROMOTED`. Because the interval is closed, touching endpoints count as a collision: if one window's `coverage_end` exactly equals another window's `coverage_start`, that is a conflict. There is no buffer between coverage windows. A violation is refused with `ERR_PROVIDER_WINDOW_OVERLAP`.

Room bookings use **half-open** semantics across the span `[starts_at, ends_at)`, where the start is included and the end is excluded. A new booking must not overlap any existing non-terminal booking on the same room, with the room's turnover buffer applied after each booking. When `turnover_minutes` is 0, two bookings that exactly abut — the next booking's `starts_at` equal to the previous booking's `ends_at` — do not collide. When `turnover_minutes` is greater than 0, the next booking must start at or after the previous booking's `ends_at` plus that many minutes of turnover; starting any earlier is a collision. A violation is refused with `ERR_ROOM_DOUBLE_BOOKED`.

### 3.10. Settling the Balance: Payment Plans and the Waterfall

The episode's net client responsibility lives in its computed `balance_due_cents`, and that figure is derived in a pinned two-step order so that charges and the payment plan never chase each other in a circle. Step one sums client responsibility across the episode's charges: it adds up the `client_responsibility_cents` of every charge whose `status` is `DRAFT` or `BILLED`, excluding charges that are `VOID` or `PAID`. Step two consults the plan only if one exists: if the episode has a payment plan in `OPEN` or `PAID_OFF`, the balance becomes the plan's `total_cents` minus its `paid_cents`, floored at zero so it is never negative; if no such plan exists, the balance is simply the step-one sum. The plan's `total_cents` is frozen at plan creation, so once a plan exists later charge edits do not retroactively change that frozen total — charges feed the plan total at creation, and thereafter the plan governs the balance.

A `BillingClerk` creates an installment plan by naming the `episode_id`, the `installment_count` (at least 1), and the optimistic-concurrency field `expected_episode_version` from Section 2.8. Creation requires the episode's `balance_due_cents` to be strictly greater than zero; a plan create attempted on a zero balance is refused with `ERR_NO_BALANCE` (HTTP 409). On success the plan opens in `OPEN` `status` with its `total_cents` snapshotted from the episode's `balance_due_cents`, its `paid_cents` at 0 and `remaining_cents` equal to `total_cents`, and the episode's `financial_status` advances from `UNBILLED` to `PLAN_ACTIVE` while the episode's `version` increments. The plan create is the financial-axis transition into `PLAN_ACTIVE`, and it is allowed only from `UNBILLED`.

The installment schedule is computed once at creation and pinned. The base installment amount is the `total_cents` divided by the `installment_count`, taking the floor. The remainder is the `total_cents` minus the base times the `installment_count`. Installments are ordered first through last, and the remainder is distributed to the earliest installments first: the first however-many installments equal to the remainder each get the base plus one cent, and every installment after that gets the base. The remainder is never spread evenly and never pushed to the last installment.

A `BillingClerk` applies a payment to a plan by supplying an `amount_cents`. The payment is allocated by walking the installments in order from first to last: for each installment not yet fully paid, the system applies the smaller of the remaining payment and that installment's outstanding due, then moves to the next installment only once the current one is fully covered. A payment may not exceed the plan's `remaining_cents`; any overpayment beyond the final installment is refused with `ERR_OVERPAYMENT` (HTTP 409). After a payment, the plan's `paid_cents` increases by the amount applied and its `remaining_cents` becomes `total_cents` minus `paid_cents`. When a payment drives `remaining_cents` to exactly 0, the plan moves from `OPEN` to `PAID_OFF`, and that completion cascades on the financial axis: the episode's `financial_status` moves from `PLAN_ACTIVE` to `SETTLED`, and that settlement marks every `BILLED` charge on the episode as `PAID`. A plan's `version` increments on each payment.

A plan may instead be defaulted by a `BillingClerk`, moving `status` from `OPEN` to `DEFAULTED`, which is allowed only while `remaining_cents` is greater than zero; a default attempted on a plan not currently `OPEN`, or on an `OPEN` plan whose `remaining_cents` is already zero, is refused with `ERR_INVALID_STATE`. A plan's `status` ranges over `OPEN`, `PAID_OFF`, `DEFAULTED`, and `CANCELLED`, the last three terminal. The `CANCELLED` ending is reached only through a write-off, described next.

### 3.11. Writing Off an Episode

A `BillingClerk` may write off an episode's balance, moving the `financial_status` to `WRITTEN_OFF` from either `UNBILLED` or `PLAN_ACTIVE`. A write-off cancels the episode's open payment plan if one exists, moving that plan's `status` from `OPEN` to `CANCELLED`, and it voids every charge on the episode that is in `DRAFT` or `BILLED`, moving each to `VOID`. The episode's `version` increments. Unlike a transfer or a recorded birth, a write-off makes no movement of the supply kit. A write-off attempted from a financial state other than `UNBILLED` or `PLAN_ACTIVE` is refused with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action and the logical-clock adjustment — return a `200 OK` status code. Reconstructing the full request body and side effects of any endpoint below requires reading the corresponding workflow narrative in Section 3; this table lists only the routing contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/birth-center/_clock/set_current_utc` | Set the server logical clock | CenterAdmin |
| POST | `/birth-center/clients` | Register a client (intake) | IntakeCoordinator |
| GET | `/birth-center/clients/{id}` | Get a client | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| GET | `/birth-center/clients` | List clients (paginated) | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| POST | `/birth-center/clients/{id}/archive` | Archive a client | IntakeCoordinator |
| POST | `/birth-center/care-packages` | Create an immutable care package | CenterAdmin |
| GET | `/birth-center/care-packages/{id}` | Get a care package by code | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| GET | `/birth-center/care-packages` | List care packages | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| POST | `/birth-center/supply-kits` | Create a supply kit record | CenterAdmin |
| GET | `/birth-center/supply-kits/{id}` | Get a supply kit by sku | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| GET | `/birth-center/supply-kits` | List supply kits | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| POST | `/birth-center/providers` | Create a provider | CenterAdmin |
| GET | `/birth-center/providers/{id}` | Get a provider | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| GET | `/birth-center/providers` | List providers | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| POST | `/birth-center/rooms` | Create a birth-center room | CenterAdmin |
| GET | `/birth-center/rooms/{id}` | Get a room | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| GET | `/birth-center/rooms` | List rooms | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| POST | `/birth-center/rooms/{id}/close` | Close a room to new bookings | CenterAdmin |
| POST | `/birth-center/episodes` | Open an episode of care | IntakeCoordinator |
| GET | `/birth-center/episodes/{id}` | Get an episode | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| GET | `/birth-center/episodes` | List episodes | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| POST | `/birth-center/episodes/{id}/activate` | Begin active care | Midwife |
| POST | `/birth-center/episodes/{id}/transfer` | Hospital transfer (with cascades) | Midwife |
| POST | `/birth-center/episodes/{id}/record-birth` | Record birth at center | Midwife |
| POST | `/birth-center/episodes/{id}/complete-care` | Complete the episode | Midwife |
| POST | `/birth-center/episodes/{id}/write-off` | Write off the episode's balance | BillingClerk |
| GET | `/birth-center/episodes/{id}/prenatal-visits` | List visits on an episode | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| GET | `/birth-center/episodes/{id}/charges` | List charges on an episode | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| GET | `/birth-center/episodes/{id}/on-call-assignments` | List on-call assignments on an episode | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| GET | `/birth-center/episodes/{id}/bookings` | List bookings on an episode | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| GET | `/birth-center/episodes/{id}/insurance-claims` | List claims on an episode | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| GET | `/birth-center/episodes/{id}/payment-plans` | List payment plans on an episode | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| POST | `/birth-center/prenatal-visits` | Schedule a visit | IntakeCoordinator, Midwife |
| GET | `/birth-center/prenatal-visits/{id}` | Get a prenatal visit | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| POST | `/birth-center/prenatal-visits/{id}/complete` | Complete a visit and record screening | Midwife |
| POST | `/birth-center/prenatal-visits/{id}/mark-no-show` | Mark a past-due visit as no-show | Midwife |
| POST | `/birth-center/prenatal-visits/{id}/cancel` | Cancel a scheduled visit | IntakeCoordinator, Midwife |
| POST | `/birth-center/on-call-assignments` | Assign a primary on-call provider | CenterAdmin |
| GET | `/birth-center/on-call-assignments/{id}` | Get an on-call assignment | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| GET | `/birth-center/on-call-assignments` | List on-call assignments | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| POST | `/birth-center/on-call-assignments/{id}/name-backup` | Create and link a backup assignment | CenterAdmin |
| POST | `/birth-center/on-call-assignments/{id}/go-on-duty` | Primary goes on duty | CenterAdmin |
| POST | `/birth-center/on-call-assignments/{id}/release` | Release primary coverage | CenterAdmin |
| POST | `/birth-center/bookings` | Hold a room booking | CenterAdmin |
| GET | `/birth-center/bookings/{id}` | Get a booking | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| GET | `/birth-center/bookings` | List bookings | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| POST | `/birth-center/bookings/{id}/confirm` | Confirm a held booking | CenterAdmin |
| POST | `/birth-center/bookings/{id}/check-in` | Check in to a room | CenterAdmin |
| POST | `/birth-center/bookings/{id}/cancel` | Cancel a held/confirmed booking | CenterAdmin |
| POST | `/birth-center/charges` | Add an out-of-bundle charge | BillingClerk |
| GET | `/birth-center/charges/{id}` | Get a charge | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| GET | `/birth-center/charges` | List charges | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| POST | `/birth-center/charges/{id}/bill` | Mark a draft charge as billed | BillingClerk |
| POST | `/birth-center/insurance-claims` | Submit a global-fee insurance claim | BillingClerk |
| GET | `/birth-center/insurance-claims/{id}` | Get an insurance claim | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| GET | `/birth-center/insurance-claims` | List claims | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| POST | `/birth-center/insurance-claims/{id}/adjudicate` | Adjudicate a claim | BillingClerk |
| POST | `/birth-center/insurance-claims/{id}/deny` | Deny a claim | BillingClerk |
| POST | `/birth-center/insurance-claims/{id}/void` | Void a claim | BillingClerk |
| POST | `/birth-center/payment-plans` | Create an installment plan | BillingClerk |
| GET | `/birth-center/payment-plans/{id}` | Get a payment plan | IntakeCoordinator, Midwife, BillingClerk, CenterAdmin |
| POST | `/birth-center/payment-plans/{id}/payments` | Apply a payment | BillingClerk |
| POST | `/birth-center/payment-plans/{id}/default` | Mark a plan as defaulted | BillingClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_RISK_TRANSFER_REQUIRED` | 409 Conflict |
| `ERR_BACKUP_SAME_PROVIDER` | 409 Conflict |
| `ERR_PROVIDER_AT_CAPACITY` | 409 Conflict |
| `ERR_PROVIDER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_ROOM_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_INVALID_INTERVAL` | 422 Unprocessable Entity |
| `ERR_CLAIM_AMOUNTS_INVALID` | 422 Unprocessable Entity |
| `ERR_KIT_OUT_OF_STOCK` | 409 Conflict |
| `ERR_OVERPAYMENT` | 409 Conflict |
| `ERR_NO_BALANCE` | 409 Conflict |
| `ERR_POSTPARTUM_INCOMPLETE` | 409 Conflict |
| `ERR_NO_ACTIVE_BOOKING` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CLAIM_HAS_PLAN` | 409 Conflict |
