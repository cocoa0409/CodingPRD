# Carpet & Upholstery Cleaning API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Carpet & Upholstery Cleaning API, a back-office platform that takes a residential or commercial cleaning request from first measurement all the way through to a settled bill. The business problem it solves is a deceptively hard one: the price a customer is *quoted* when their job is first measured is not always the price the business can *settle* on when the work is finally done. A living room that looked moderately soiled on the phone may turn out to be one of several heavily soiled areas requiring extra passes and solution, and the platform must reconcile that gap honestly without surprising either party.

The system coordinates four kinds of operator around a single job. Customers describe the rooms and surfaces they want cleaned, choose add-ons such as stain treatment or fabric protectant, and may enroll in a recurring plan for a standing discount. Dispatchers own the fleet of truck-mount crews and the calendar, booking each job into a crew's slot map while respecting the turnaround a rig needs between jobs. A Billing team issues the per-job invoice, applies any account credit the customer has accrued, and records payments. A Service Manager presides over the service catalog and adjudicates the re-clean guarantee that backs every completed job. Because crews and invoices are shared, contended resources, the platform layers optimistic concurrency control over the two operations most prone to lost updates — booking a crew slot and paying an invoice — so that a stale client view can never silently overwrite a fresher one.

Throughout, money is handled in integer cents and time is handled in integer minutes measured from a logical epoch-zero, keeping every calculation exact and every scheduling decision reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, conventions, and cross-cutting principles that govern every endpoint. Where a rule is universal, it is stated here once; the detailed business workflows in Section 3 assume it.

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, the acting principal's identifier, and `X-User-Role`, the operational capacity under which the request is made. If either header is absent, or `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_MISSING_AUTH` (HTTP 401). When the headers are valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `Customer`, `Dispatcher`, `ServiceManager`, and `Billing`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; every ownership check on a resource that belongs to a customer compares that resource's owning customer to `X-User-ID`. Concretely, a `CleaningJob` is owned by the customer named in its `customer_id`, and a `RecurringPlan` is owned by the customer named in its `customer_id`; rooms and add-ons are owned transitively through their parent job. When a `Customer` attempts to mutate a job, room, add-on, or plan that they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The other three roles are operator roles whose identity is opaque. When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same holds when `X-User-Role` is `ServiceManager` and when `X-User-Role` is `Billing`: in each case `X-User-ID` is an opaque operator identifier the server may log but never matches against a stored entity. A `ServiceManager` is a superset operator and may perform any mutation that a `Customer`, `Dispatcher`, or `Billing` operator could perform, on any resource, without being subject to the customer ownership check.

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

List endpoints accept two query parameters to page through results. `limit` caps the number of items returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. `offset` is the number of items to skip from the start of the result set; it defaults to 0. Unless a specific endpoint says otherwise, list endpoints return their items sorted by the resource's `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `has_more` is true exactly when `offset` plus the number of items actually returned on this page is still less than `total_count`.

### 2.4. Common Resource Properties

Every primary resource — `Customer`, `ServiceCatalog`, `Crew`, `RecurringPlan`, `CleaningJob`, `RoomAssessment`, `AddOn`, `ScheduledSlot`, `Invoice`, `Payment`, and `GuaranteeClaim` — carries a system-managed `id` that is a server-minted UUID with no type prefix. This `id` exists for identity and addressing only and is never used as an input to a business decision. Each of these resources also carries a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Timestamps are ISO 8601 UTC strings with three fractional digits. The `version` starts at 1 when the resource is created and increments by one on every mutation of that resource; `updated_at` is refreshed to the time of every such mutation.

One entity is deliberately leaner. A `WalletLedgerEntry` is an append-only ledger record: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because once written it is never modified. The ledger is the immutable audit trail behind a customer's account credit.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many paths address a resource nested beneath a parent — a room or add-on beneath a job, a payment beneath an invoice. For any such request the system validates the path identifiers from left to right, and the first identifier that names no existing resource determines the rejection. Thus when a request targets a room under a job, a non-existent job surfaces `ERR_JOB_NOT_FOUND` before the room is ever consulted, and only once the job is confirmed does a missing room surface `ERR_ROOM_NOT_FOUND`. The same left-to-right discipline governs every other resource referenced by a path or body identifier: a missing customer yields `ERR_CUSTOMER_NOT_FOUND`, a missing service catalog yields `ERR_CATALOG_NOT_FOUND`, a missing crew yields `ERR_CREW_NOT_FOUND`, a missing recurring plan yields `ERR_PLAN_NOT_FOUND`, a missing add-on yields `ERR_ADDON_NOT_FOUND`, a missing invoice yields `ERR_INVOICE_NOT_FOUND`, and a missing guarantee claim yields `ERR_CLAIM_NOT_FOUND`. All existence failures carry HTTP 404.

### 2.6. Validation Precedence

When several checks could reject a single request, the system evaluates them in a fixed order so that the same bad request always fails the same way. Authentication comes first: the presence and validity of the `X-User-ID` and `X-User-Role` headers (`ERR_MISSING_AUTH`) is checked before anything else. Authorization comes second: whether the role may perform the operation at all (`ERR_FORBIDDEN_ROLE`). Third, the existence of every resource named by a path or body identifier is confirmed left-to-right, as described in §2.5, yielding the appropriate 404. Fourth, the request body itself is checked for well-formedness — required fields present, enumerated fields within their allowed sets, and integers within their stated bounds — with any failure rejected as `ERR_INVALID_REQUEST` (HTTP 422); this body check applies to every state-changing request. Fifth, for a `Customer`-role mutation, the ownership check of §2.1 runs, yielding `ERR_NOT_RESOURCE_OWNER` if the acting customer does not own the target. Sixth, the target resource's state is checked: if the requested transition is not defined from the resource's current state, the request is rejected with the corresponding state error (the catalogue of these — `ERR_JOB_NOT_DRAFT`, `ERR_JOB_NOT_QUOTED`, `ERR_JOB_NOT_BOOKED`, `ERR_JOB_NOT_IN_PROGRESS`, `ERR_JOB_NOT_COMPLETED`, `ERR_CLAIM_NOT_FILED`, `ERR_INVOICE_NOT_OPEN`, and `ERR_SLOT_NOT_RESERVED` — is HTTP 409). Only after all of these pass does the system evaluate the operation-specific business rules described in Section 3, such as room-count, crew compatibility, slot overlap, the guarantee window, duplicate add-ons, overpayment, and the optimistic-concurrency checks. The relative order among those business rules is described alongside each workflow where it matters.

The well-formedness check at the fourth step enforces the documented numeric floors: a room's `area_sqft` must be at least 1, a payment's `amount_cents` must be at least 1, a slot's `end_minute` must be strictly greater than its `start_minute`, and catalog rates may not be negative. Any violation is an `ERR_INVALID_REQUEST`.

### 2.7. Monetary and Temporal Precision

All money in this system is stored and computed in integer cents; there are no fractional cents. Wherever a price calculation multiplies by a soiling multiplier or a discount percentage and the intermediate result is not a whole number of cents, the system rounds half up to the nearest cent. Rounding happens at each pinned step of a price calculation rather than once at the end — Section 3 specifies exactly where those rounding points fall for the quote and the settlement. All time is expressed as integer minutes counted from a logical epoch-zero: slot boundaries, the completion clock, and the moment a guarantee claim is filed are all such minute values, and the guarantee-window comparison is an exact integer-minute comparison with no rounding.

### 2.8. Hierarchical Consistency and Cascading Side Effects

A single operation frequently mutates more than one resource, and the platform treats every such cascade as part of the operation's contract rather than an afterthought. Booking a job mints a slot and advances the booked crew's `version`. Completing a job releases its slot and, when the job belongs to an active plan, advances that plan's `completed_visit_count`. Issuing an invoice debits the customer's wallet through a ledger entry. Voiding an invoice refunds that wallet and reopens the job for billing. Granting a guarantee mints an entire re-clean job, copies its rooms, and credits the wallet. Each of these secondary effects is enumerated in the workflow that triggers it. Whenever an operation mutates a resource, that resource's `updated_at` is refreshed and its `version` is incremented, including the derived, computed fields such as `total_sqft`, `wallet_credit_cents`, `completed_visit_count`, and `amount_paid_cents` — a change to a computed field is still a mutation of its owning resource.

### 2.9. Optimistic Concurrency Control

Two operations in this system act on resources that other writers contend for, and both require the client to prove it is acting on a current view by submitting the resource's last-observed `version`.

The first is booking a job onto a crew. A booking request must carry `expected_crew_version`, and the server compares it to the target `Crew`'s current `version`. If another write has advanced that crew's `version` since the client last read it — for example, a prior booking that legitimately reserved an overlapping window and bumped the crew — the booking is operating on a stale view of the crew's slot map and is rejected with `ERR_STALE_CREW_VERSION` (HTTP 412). The rescheduling operation books onto a crew in the same way and carries `expected_crew_version` for the crew it is booking onto, subject to the same stale-version rejection. `expected_crew_version` is a required field of these requests, not an optional one.

The second is paying an invoice. A payment request must carry `expected_invoice_version`, and the server compares it to the target `Invoice`'s current `version`. If the invoice has been advanced since the client last read it — because an earlier payment, a void, or a settlement bumped its `version` — the payment reflects a stale view of the invoice and is rejected with `ERR_STALE_INVOICE_VERSION` (HTTP 412). `expected_invoice_version` is a required field of a payment request.

No other endpoint takes a version field, and no other endpoint performs a concurrency check.

### 2.10. The Wallet Ledger Principle

Each customer carries an account-credit balance, `wallet_credit_cents`, which is never an independently stored number but always the exact sum of the signed `delta_cents` of every `WalletLedgerEntry` belonging to that customer, across all entries with no status filter, since the ledger is append-only. The balance starts at 0 for a new customer and, by construction, is never driven below 0. Every movement of credit writes one ledger entry whose `reason` records what produced it — `GUARANTEE_CREDIT` when a re-clean guarantee is granted, `INVOICE_APPLIED` when credit is consumed against an invoice, and `INVOICE_REFUND` when a voided invoice returns previously applied credit — and whose `cleaning_job_id` records the job that produced the movement. Because the consumption at invoice time is capped at the available balance, the running sum can never go negative.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Customers, Catalogs, Crews, and Plans

A `Customer` is created by supplying a `full_name` and an `email`; a `ServiceManager` may also create customers on a caller's behalf. The `email` must be unique across all customers — a second customer attempting to register an address already on file is rejected with `ERR_EMAIL_TAKEN`. A freshly created customer begins life with `status` of `ACTIVE` and an account credit of zero cents. A `ServiceManager` may later move a customer's `status` to `SUSPENDED`; the only two values `status` ever takes are `ACTIVE` and `SUSPENDED`, and a suspended customer cannot advance their jobs (see §3.3).

The **service catalog** pins all the rates a job will use. A `ServiceManager` creates a catalog entry by declaring its `service_type` — either `STEAM` or `DRY` — together with seven pricing and policy fields: `base_rate_cents_per_sqft`, the per-square-foot base price, which must be at least 1; `stain_addon_cents`, the flat charge for a stain treatment; `pet_addon_cents`, the flat charge for pet treatment; `protectant_cents_per_sqft`, the per-square-foot charge for fabric protectant; `move_furniture_flat_cents`, a one-time surcharge applied to a job when furniture moving is requested; and `dry_time_minutes`, the guaranteed dry-time ceiling for this service type, which must be at least 1 and anchors the re-clean guarantee window. The four add-on and surcharge rates must each be zero or greater. Only one catalog may exist per service type; an attempt to create a second `STEAM` or a second `DRY` catalog is rejected with `ERR_SERVICE_TYPE_TAKEN`.

A **crew** represents one truck-mount rig. A `Dispatcher` creates a crew with a `crew_name`, the single `supported_service_type` it can perform (`STEAM` or `DRY`), and a `turnaround_buffer_minutes` value — the minimum idle gap, of zero or more minutes, that the rig needs after one slot ends before the next slot on the same crew may begin. A new crew starts with `status` of `AVAILABLE` and `version` 1. A `Dispatcher` may retire a crew by moving its `status` to `OUT_OF_SERVICE`, which advances the crew's `version`; the two crew states are `AVAILABLE` and `OUT_OF_SERVICE`.

A **recurring plan** captures a customer's standing commitment and the discount it earns. A `Customer` (or a `ServiceManager`) creates a plan by naming the owning `customer_id` and a `cadence` of `MONTHLY`, `QUARTERLY`, or `SEMIANNUAL`. A new plan starts `ACTIVE` with a `completed_visit_count` of 0; that count is maintained by the system as the number of this plan's jobs that have reached completion. A plan may be paused, moving its `status` to `PAUSED`; the two plan states are `ACTIVE` and `PAUSED`. A plan's `cadence` selects the recurring discount applied to every job tied to it: a `MONTHLY` cadence earns the deepest discount of fifteen percent, a `QUARTERLY` cadence earns ten percent, and a `SEMIANNUAL` cadence earns five percent. A one-off job with no plan earns no discount.

The system exposes read access to a customer's ledger movements and to a customer's plans, so that a caller can reach a `WalletLedgerEntry` by its owning `customer_id` and a `RecurringPlan` by its owning `customer_id`, as well as list the slots on a crew by the crew's `crew_id`.

### 3.2. Building a Job: Rooms, Add-Ons, and the Quote

A **cleaning job** is the heart of the system, and it carries two independent status axes at once. Its `lifecycle_status` tracks the booking-and-execution workflow through `DRAFT`, `QUOTED`, `BOOKED`, `IN_PROGRESS`, `COMPLETED`, and `CANCELLED`. Its `billing_status` tracks settlement independently through `UNBILLED`, `INVOICED`, and `PAID`. The two never collapse into one: a job can be `COMPLETED` on the lifecycle axis while still `UNBILLED` on the billing axis.

A `Customer` creates a job by naming the owning `customer_id` and the `service_catalog_id` whose rates the job will use; that catalog pins the job's service type and every rate for the life of the job. The creation request may optionally name a `recurring_plan_id`, which is left null for a one-off job and, when present, applies that plan's discount; it may also optionally set `move_furniture`, which defaults to false. A new job begins in `DRAFT` lifecycle status, `UNBILLED` billing status, and with `total_sqft` of 0. Two further job fields are system-managed and remain null until the relevant event: `origin_job_id`, which is set only on a re-clean job minted from a granted guarantee and otherwise stays null; `scheduled_slot_id`, set when the job is booked onto a crew slot; and `invoice_id`, set when the job is invoiced. The forward-looking `quoted_price_cents` and the chronological `settled_price_cents` are likewise computed by the system, the latter remaining null until the invoice is issued. The completion clock `completed_at_minute` stays null until the job is completed.

While a job remains in `DRAFT`, the customer attaches the rooms to be cleaned. Each **room assessment** is added by giving an `area_label` such as a room or surface name, an `area_sqft` measured in whole square feet of at least 1, and a `soiling_level` of `LIGHT`, `MODERATE`, or `HEAVY`. Rooms may only be added while the job is in `DRAFT`; adding a room to a job in any other lifecycle state is rejected with `ERR_JOB_NOT_DRAFT`. Each time a room is added to a draft job, the job's `total_sqft` is recomputed as the sum of the `area_sqft` of all its rooms. The soiling level chosen here drives a per-room price multiplier later: a `LIGHT` room is priced at its plain base, a `MODERATE` room at one and one-quarter times base, and a `HEAVY` room at one and six-tenths times base.

Add-ons are also attached only while the job is in `DRAFT`, and attaching one to a non-draft job is likewise rejected with `ERR_JOB_NOT_DRAFT`. An **add-on** is requested by its `addon_type` — `STAIN`, `PET`, or `PROTECTANT` — and at most one add-on of each type may exist on a job; a second add-on of a type already present is rejected with `ERR_DUPLICATE_ADDON`. At the moment an add-on is created its `line_price_cents` is computed and frozen from the job's catalog according to type: a `STAIN` add-on takes the catalog's `stain_addon_cents`; a `PET` add-on takes the catalog's `pet_addon_cents`; and a `PROTECTANT` add-on takes the catalog's `protectant_cents_per_sqft` multiplied by the job's current `total_sqft`, rounded half up to whole cents. Because a protectant price reads the job's `total_sqft` at the instant of creation, a `PROTECTANT` add-on created before any room exists — when `total_sqft` is still 0 — freezes a `line_price_cents` of 0, and that frozen value is not retroactively corrected when rooms are added afterward. Attaching an add-on is itself treated as a mutation of the parent job, so the job's `version` is incremented and its `updated_at` refreshed when the add-on is created, even though no stored or computed job field other than its add-on set changes.

A customer **quotes** a draft job to lock in a price, which transitions the job `DRAFT → QUOTED`. Quoting requires the job to have at least one room; quoting a roomless job is rejected with `ERR_NO_ROOMS`. Quoting also requires the owning customer to be `ACTIVE`; a suspended customer's quote attempt is rejected with `ERR_CUSTOMER_SUSPENDED`. On a successful quote, the job's `total_sqft` is frozen as the sum of its rooms' `area_sqft`, and the forward-looking `quoted_price_cents` is computed and frozen.

The quote prices everything currently attached, in a pinned order. First, each room's base line is computed as the catalog's `base_rate_cents_per_sqft` multiplied by that room's `area_sqft` multiplied by the room's soiling multiplier (1.0 for `LIGHT`, 1.25 for `MODERATE`, 1.6 for `HEAVY`), and that per-room line is rounded half up to whole cents *before* being added in; the rooms subtotal is the sum of those individually rounded room lines. Second, the add-ons subtotal is the sum of every attached add-on's already-frozen `line_price_cents`. Third, a move-furniture surcharge is added: if `move_furniture` is set on the job, the catalog's `move_furniture_flat_cents` is added once for the whole job — never once per room — and otherwise nothing is added. Fourth, the pre-discount total is the rooms subtotal plus the add-ons subtotal plus that furniture surcharge. Fifth, the recurring discount is applied to the pre-discount total: the discount percentage is selected from the plan's cadence when the job names a `recurring_plan_id` (fifteen percent for `MONTHLY`, ten percent for `QUARTERLY`, five percent for `SEMIANNUAL`) and is zero when the job has no plan; the discount amount is the pre-discount total multiplied by that percentage, rounded half up to whole cents exactly once. The frozen `quoted_price_cents` is the pre-discount total minus that single rounded discount amount. This quote is a forward projection of the current room and add-on set; once frozen it is never recomputed, even if the room or add-on set later changes.

### 3.3. Scheduling: Booking, Rescheduling, Starting, and Completing

Once a job is `QUOTED`, a `Dispatcher` **books** it onto a crew, which transitions the job `QUOTED → BOOKED`. The booking request supplies the chosen `crew_id`, the `start_minute` and `end_minute` of the desired slot, and the `expected_crew_version` for optimistic concurrency. Several conditions must hold, and they are evaluated after the generic state and ownership gates of §2.6. The named crew must be `AVAILABLE`; booking onto an out-of-service crew is rejected with `ERR_CREW_UNAVAILABLE`. The crew's `supported_service_type` must equal the service type pinned by the job's catalog; a steam crew cannot take a dry job and vice versa, and a mismatch is rejected with `ERR_SERVICE_TYPE_MISMATCH`. The requested interval must not collide with any `RESERVED` slot already on that crew once each existing slot is extended at its tail by the crew's `turnaround_buffer_minutes`: a new slot whose start falls within an existing slot's reserved-plus-buffer span overlaps and is rejected with `ERR_SLOT_OVERLAP`, while a new slot beginning exactly at the buffer boundary — immediately after the buffer elapses — is adjacent rather than overlapping and is allowed. Finally the supplied `expected_crew_version` must match the crew's live `version`, failing which the booking is rejected with `ERR_STALE_CREW_VERSION` as described in §2.9.

A successful booking has three effects: a new `ScheduledSlot` is created on the crew, carrying the booking's `crew_id`, the job's `cleaning_job_id`, the supplied `start_minute` and `end_minute`, and `status` of `RESERVED`; the job's `scheduled_slot_id` is pointed at that new slot; and the crew's `version` is incremented by one. A slot's `status` is one of `RESERVED` or `RELEASED`.

A booked job may be **rescheduled** any number of times before it starts. A `Dispatcher` reschedules by supplying a new `crew_id`, `start_minute`, `end_minute`, and `expected_crew_version` for the crew being booked onto — possibly a different crew. Rescheduling repeats the same crew-availability, service-type-match, slot-overlap, and crew-version checks as booking, drawing on the same `ERR_CREW_UNAVAILABLE`, `ERR_SERVICE_TYPE_MISMATCH`, `ERR_SLOT_OVERLAP`, and `ERR_STALE_CREW_VERSION` rejections. A successful reschedule is a two-hop slot cascade: the job's current slot is released, transitioning that slot `RESERVED → RELEASED`, and a fresh `RESERVED` slot is created on the new crew, with the job's `scheduled_slot_id` repointed to the new slot and the new crew's `version` incremented.

A `Dispatcher` **starts** a booked job, transitioning it `BOOKED → IN_PROGRESS`. Starting requires that the job's `scheduled_slot_id` still references a `RESERVED` slot; if that slot is not reserved, the start is rejected with `ERR_SLOT_NOT_RESERVED`. A `Dispatcher` then **completes** an in-progress job, transitioning it `IN_PROGRESS → COMPLETED`. The completion request supplies a `completed_at_minute`, the logical completion clock in minutes from epoch-zero, which must be zero or greater; this value is recorded on the job and anchors the guarantee window. Completing a job releases its slot, transitioning it `RESERVED → RELEASED`. If the job belongs to a recurring plan and that plan is `ACTIVE`, completion also increments the plan's `completed_visit_count` by one, a bubble-up recompute on the parent plan.

A `Customer` may **cancel** a job, transitioning it to `CANCELLED` — a terminal lifecycle state. Cancellation is permitted from `DRAFT`, `QUOTED`, or `BOOKED`; a cancel attempt against a job whose `lifecycle_status` is anything other than these three (such as `IN_PROGRESS`, `COMPLETED`, or already `CANCELLED`) is rejected with `ERR_JOB_ALREADY_BILLED` (HTTP 409) — not with one of the `ERR_JOB_NOT_*` state errors — regardless of the job's `billing_status`. Because cancellation undoes billing eligibility, it requires the job's `billing_status` to still be `UNBILLED`; cancelling a job whose billing has already started is rejected with `ERR_JOB_ALREADY_BILLED`. When a cancelled job from `QUOTED` or `BOOKED` has a `RESERVED` slot attached, that slot is released, transitioning it `RESERVED → RELEASED`, and the job's `scheduled_slot_id` is cleared — this release is itself the first hop of the cancel cascade. A `DRAFT` job has no slot and so simply moves to `CANCELLED` with no slot effect.

### 3.4. Per-Job Billing: Settlement, Wallet, and Payment

Settlement runs on the independent billing axis and may begin only once the lifecycle axis has reached `COMPLETED`. The Billing team **issues** the per-job invoice, transitioning the job's `billing_status` `UNBILLED → INVOICED`. Issuing requires that the job's `lifecycle_status` be `COMPLETED`; an attempt to invoice a job that has not completed is rejected with `ERR_JOB_NOT_COMPLETED`. It also requires that no open or settled invoice already exist for the job — there is one invoice per job — and a second attempt is rejected with `ERR_JOB_ALREADY_BILLED`.

Issuing the invoice first computes the job's **settled price** by replaying the job's rooms and add-ons in `created_at` ascending order, and it differs from the quote in exactly one respect: a heavy-soiling escalation surcharge that the forward quote optimistically omits. The settlement proceeds in pinned steps. First, it recomputes the rooms subtotal exactly as the quote does — the same per-room base of `base_rate_cents_per_sqft` times `area_sqft` times the soiling multiplier (1.0, 1.25, or 1.6), each room line rounded half up before being summed — but it iterates the rooms in `created_at` ascending order while keeping a running count of how many `HEAVY` rooms it has seen. Second, the add-ons subtotal is the sum of every add-on's `line_price_cents`, taken in `created_at` ascending order. Third, the move-furniture surcharge of `move_furniture_flat_cents` is added once if `move_furniture` is set, and otherwise nothing. Fourth, if the running count of `HEAVY` rooms reaches three or more, a one-time escalation surcharge of 4000 cents is added; if there are fewer than three heavy rooms, no escalation is added. Fifth, the pre-discount total is the rooms subtotal plus the add-ons subtotal plus the furniture surcharge plus the escalation surcharge. Sixth, the recurring discount is applied exactly as in the quote — the cadence-keyed percentage of fifteen, ten, or five percent for a plan-bound job, or zero for a one-off, multiplied against the pre-discount total and rounded half up once. The resulting `settled_price_cents` is the pre-discount total minus that rounded discount. Because the escalation surcharge appears only here, a job with three or more heavy rooms settles strictly higher than it quoted, while a lightly soiled job settles at the same figure it quoted.

Issuing the invoice then creates the **invoice** itself, carrying the job's `cleaning_job_id` and an `amount_due_cents` equal to the freshly computed `settled_price_cents`. Against that face amount the system applies the customer's account credit: `wallet_applied_cents` is the smaller of the customer's current `wallet_credit_cents` and the invoice's `amount_due_cents`, so that neither the wallet nor the remaining balance can go negative. Applying the wallet writes a `WalletLedgerEntry` whose `delta_cents` is the negative of `wallet_applied_cents` and whose `reason` is `INVOICE_APPLIED`, which is the cascade hop from invoice issuance to wallet debit. The invoice's `net_payable_cents` is then set to `amount_due_cents` minus `wallet_applied_cents`. Its `amount_paid_cents` starts at 0. The invoice begins with `status` of `OPEN` and `version` 1; an invoice's `status` is one of `OPEN`, `SETTLED`, or `VOID`. Finally the job's `invoice_id` is set and its `billing_status` becomes `INVOICED`.

The Billing team records a **payment** against an open invoice. A payment request supplies an `amount_cents` of at least 1, a `method` of `CARD`, `CASH`, or `CHECK`, and the `expected_invoice_version` for optimistic concurrency. The invoice must be `OPEN`; a payment against a settled or voided invoice is rejected with `ERR_INVOICE_NOT_OPEN`. A payment may not exceed the invoice's remaining net balance — that is, `amount_cents` may be no larger than `net_payable_cents` minus the already-paid `amount_paid_cents`; an overpayment is rejected with `ERR_OVERPAYMENT` (HTTP 402). The supplied `expected_invoice_version` must match the invoice's live `version`, failing which the payment is rejected with `ERR_STALE_INVOICE_VERSION`. A recorded payment is created with `status` of `APPLIED` and is immutable thereafter — this version offers no reversal of a payment, and `APPLIED` is the only payment status. Recording the payment recomputes the invoice's `amount_paid_cents` as the sum of the `amount_cents` of all its `APPLIED` payments and increments the invoice's `version`. When the cumulative `APPLIED` total reaches or exceeds the invoice's `net_payable_cents`, the invoice transitions `OPEN → SETTLED`, and that settlement cascades across the billing axis to set the job's `billing_status` to `PAID` — the job's billing-axis transition `INVOICED → PAID` is driven by the invoice reaching `SETTLED`, not by a separate client call. `PAID` is the terminal billing state.

The Billing team may **void** an open invoice that has taken no money. Voiding requires the invoice's `amount_paid_cents` to be exactly 0; an invoice that already carries at least one `APPLIED` payment cannot be voided and the attempt is rejected with `ERR_INVOICE_HAS_PAYMENTS`. Voiding transitions the invoice `OPEN → VOID` and increments its `version`. If any wallet credit was applied at issuance — that is, if `wallet_applied_cents` was greater than 0 — voiding refunds it by writing a `WalletLedgerEntry` whose `delta_cents` is the positive `wallet_applied_cents` and whose `reason` is `INVOICE_REFUND`. Voiding is a compensation that undoes issuance: the job's `billing_status` is reset to `UNBILLED` and its `invoice_id` is cleared, returning the job to an unbilled state from which it could be invoiced afresh.

### 3.5. The Re-Clean Guarantee

Every completed job is backed by a re-clean guarantee, and a `Customer` exercises it by **filing** a claim against a job. A claim is filed by naming the `cleaning_job_id` of the completed job the customer is unhappy with, a free-text `reason`, and a `filed_at_minute` — the time the claim is filed, in minutes from epoch-zero, of zero or greater. A new claim begins with `status` of `FILED`; a claim's status is one of `FILED`, `GRANTED`, or `DENIED`, the latter two terminal.

A `ServiceManager` adjudicates each filed claim, and the two outcomes diverge sharply. Both **grant** and **deny** require the claim to still be `FILED`; acting on an already-adjudicated claim is rejected with `ERR_CLAIM_NOT_FILED`.

**Granting** a claim, which transitions it `FILED → GRANTED`, carries two preconditions and a rich set of side effects. The referenced job must itself be `COMPLETED`, failing which the grant is rejected with `ERR_JOB_NOT_COMPLETED`. The claim must also fall inside the guarantee window, which is derived from the origin job's service dry-time: the window length in minutes is the origin job's catalog `dry_time_minutes` doubled, and the claim is eligible when the elapsed time since completion — the claim's `filed_at_minute` minus the origin job's `completed_at_minute` — is no greater than that window, with the boundary inclusive, so a claim filed exactly at the window's end is still eligible. A claim filed past the window is rejected with `ERR_GUARANTEE_WINDOW_EXPIRED`. On a successful grant, the system mints a re-clean `CleaningJob` in `DRAFT` lifecycle status, copying the origin job's `customer_id`, its `service_catalog_id`, its `recurring_plan_id`, and its `move_furniture` flag, and setting the new job's `origin_job_id` to the origin job's id; it copies each of the origin job's room assessments onto the re-clean job and sets the re-clean job's `total_sqft` to the sum of the copied rooms' `area_sqft`; it grants a flat goodwill account credit of 2000 cents by writing a `WalletLedgerEntry` with that positive `delta_cents` and a `reason` of `GUARANTEE_CREDIT`; and it sets the claim's `reclean_job_id` to the new job's id. These are the cascade hops from grant to re-clean job, to room copy, and to wallet credit.

**Denying** a claim, which transitions it `FILED → DENIED`, is deliberately the empty mirror of granting: no re-clean job is created, no rooms are copied, and no wallet credit is granted. A denied claim simply reaches its terminal state with no secondary effect whatsoever.

### 3.6. Reading the Record

The platform exposes read access throughout so that any participant can reconstruct the state of a job and its money trail. A single job can be fetched to reveal both of its status axes together with its `quoted_price_cents` and `settled_price_cents`. Jobs can be listed and filtered by their `customer_id`, their `service_catalog_id`, their `recurring_plan_id`, their `origin_job_id`, their `scheduled_slot_id`, their `invoice_id`, or their `lifecycle_status`. A job's rooms, add-ons, scheduled slots, invoices, guarantee claims, and the wallet ledger movements it produced are each individually listable, the last reachable by the `cleaning_job_id` recorded on each `WalletLedgerEntry`. Catalogs can be listed and filtered by `service_type`. A crew's slots can be listed and filtered by their `status`. Guarantee claims can be listed and filtered by `cleaning_job_id`, by `reclean_job_id`, or by `status`. The payments on an invoice are reachable by each payment's `invoice_id`. Where a list endpoint accepts paging, it accepts the standard `limit` and `offset` parameters of §2.3.

## 4. Endpoint Definitions

Operations that create a brand-new resource — registering a customer, creating a catalog, crew, plan, job, room, add-on, invoice, payment, or guarantee claim — return `201 Created`. Operations that modify or transition an existing resource, and all read operations, return `200 OK`. The request and response payloads for each operation are described in the Section 3 narratives; the table below is only a routing summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a customer | Customer, ServiceManager |
| GET | `/customers/{id}` | Get a customer | Customer, ServiceManager, Billing, Dispatcher |
| POST | `/customers/{id}/suspend` | Suspend a customer account | ServiceManager |
| GET | `/customers/{id}/wallet-ledger` | List a customer's wallet ledger entries | Customer, ServiceManager, Billing |
| GET | `/customers/{id}/recurring-plans` | List a customer's recurring plans | Customer, ServiceManager |
| POST | `/service-catalogs` | Create a service catalog entry | ServiceManager |
| GET | `/service-catalogs/{id}` | Get a service catalog entry | Customer, ServiceManager, Dispatcher, Billing |
| GET | `/service-catalogs` | List service catalogs | Customer, ServiceManager, Dispatcher, Billing |
| POST | `/crews` | Create a truck-mount crew | Dispatcher |
| GET | `/crews/{id}` | Get a crew | Customer, ServiceManager, Dispatcher, Billing |
| POST | `/crews/{id}/out-of-service` | Mark a crew out of service | Dispatcher |
| GET | `/crews/{id}/scheduled-slots` | List slots on a crew | Dispatcher, ServiceManager |
| POST | `/recurring-plans` | Create a recurring plan | Customer, ServiceManager |
| GET | `/recurring-plans/{id}` | Get a recurring plan | Customer, ServiceManager |
| POST | `/recurring-plans/{id}/pause` | Pause a recurring plan | Customer, ServiceManager |
| POST | `/cleaning-jobs` | Create a draft cleaning job | Customer, ServiceManager |
| GET | `/cleaning-jobs/{id}` | Get a cleaning job | Customer, ServiceManager, Dispatcher, Billing |
| GET | `/cleaning-jobs` | List/filter cleaning jobs | Customer, ServiceManager, Dispatcher, Billing |
| POST | `/cleaning-jobs/{id}/rooms` | Add a room assessment to a draft job | Customer, ServiceManager |
| GET | `/cleaning-jobs/{id}/rooms` | List room assessments for a job | Customer, ServiceManager, Dispatcher, Billing |
| POST | `/cleaning-jobs/{id}/add-ons` | Add an add-on to a draft job | Customer, ServiceManager |
| GET | `/cleaning-jobs/{id}/add-ons` | List add-ons for a job | Customer, ServiceManager, Dispatcher, Billing |
| GET | `/cleaning-jobs/{id}/scheduled-slots` | List slots booked for a job | Customer, ServiceManager, Dispatcher, Billing |
| GET | `/cleaning-jobs/{id}/wallet-ledger` | List wallet ledger entries produced by a job | Customer, ServiceManager, Billing |
| POST | `/cleaning-jobs/{id}/quote` | Quote a draft job | Customer, ServiceManager |
| POST | `/cleaning-jobs/{id}/book` | Book a quoted job onto a crew slot | Dispatcher, ServiceManager |
| POST | `/cleaning-jobs/{id}/reschedule` | Release the current slot and reserve a new one | Dispatcher, ServiceManager |
| POST | `/cleaning-jobs/{id}/start` | Start a booked job | Dispatcher, ServiceManager |
| POST | `/cleaning-jobs/{id}/complete` | Complete an in-progress job | Dispatcher, ServiceManager |
| POST | `/cleaning-jobs/{id}/cancel` | Cancel a job | Customer, ServiceManager |
| POST | `/cleaning-jobs/{id}/invoice` | Issue the per-job invoice | Billing, ServiceManager |
| GET | `/invoices/{id}` | Get an invoice | Customer, ServiceManager, Billing |
| GET | `/cleaning-jobs/{id}/invoices` | List invoices for a job | Customer, ServiceManager, Billing |
| POST | `/invoices/{id}/payments` | Record a payment against an invoice | Billing, ServiceManager |
| GET | `/invoices/{id}/payments` | List payments for an invoice | Customer, ServiceManager, Billing |
| POST | `/invoices/{id}/void` | Void an unpaid invoice | Billing, ServiceManager |
| POST | `/guarantee-claims` | File a re-clean guarantee claim | Customer, ServiceManager |
| GET | `/guarantee-claims/{id}` | Get a guarantee claim | Customer, ServiceManager |
| GET | `/cleaning-jobs/{id}/guarantee-claims` | List guarantee claims for a job | Customer, ServiceManager |
| GET | `/guarantee-claims` | List/filter guarantee claims | Customer, ServiceManager |
| POST | `/guarantee-claims/{id}/grant` | Grant a claim and create a re-clean job | ServiceManager |
| POST | `/guarantee-claims/{id}/deny` | Deny a claim | ServiceManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_CATALOG_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_JOB_NOT_FOUND` | 404 Not Found |
| `ERR_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_ADDON_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_EMAIL_TAKEN` | 409 Conflict |
| `ERR_SERVICE_TYPE_TAKEN` | 409 Conflict |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_JOB_NOT_DRAFT` | 409 Conflict |
| `ERR_JOB_NOT_QUOTED` | 409 Conflict |
| `ERR_JOB_NOT_BOOKED` | 409 Conflict |
| `ERR_JOB_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_JOB_NOT_COMPLETED` | 409 Conflict |
| `ERR_JOB_ALREADY_BILLED` | 409 Conflict |
| `ERR_SLOT_NOT_RESERVED` | 409 Conflict |
| `ERR_CLAIM_NOT_FILED` | 409 Conflict |
| `ERR_INVOICE_NOT_OPEN` | 409 Conflict |
| `ERR_NO_ROOMS` | 409 Conflict |
| `ERR_SERVICE_TYPE_MISMATCH` | 409 Conflict |
| `ERR_CREW_UNAVAILABLE` | 409 Conflict |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_GUARANTEE_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_DUPLICATE_ADDON` | 409 Conflict |
| `ERR_OVERPAYMENT` | 402 Payment Required |
| `ERR_INVOICE_HAS_PAYMENTS` | 409 Conflict |
| `ERR_STALE_CREW_VERSION` | 412 Precondition Failed |
| `ERR_STALE_INVOICE_VERSION` | 412 Precondition Failed |
