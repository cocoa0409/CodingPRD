# Glass Mirror Shop API — Product Requirements Document

## 1. Introduction

The Architectural Glass & Mirror Shop API is the operational backbone of a fabrication business that measures, prices, tempers, and installs custom architectural glass — shower enclosures, storefronts, custom mirrors, and tabletops — for a roster of B2B contractor accounts. From the moment an estimator measures a pane to the moment an installer confirms it on site, every artifact of the job (the priced quote, the fabrication batch that tempers the glass, the crew appointment that hangs it, and the warranty claim that may follow) is governed by this system.

The business problem the API solves is one of *coordinated commitment under scarce, time-bounded capacity*. A quote must be priced deterministically down to the cent; a job, once accepted, reserves credit against a contractor's limit and reserves furnace and crew capacity in overlapping time windows; and breakage or a warranty defect must be able to reopen a "finished" job and re-thread it through fabrication without corrupting the financial ledger. Two independent progress axes — how far the glass has been fabricated and how far it has been installed — advance in parallel and must be reconciled continuously.

This document specifies the complete contract: the shared response envelope, the roles and their authority, the pricing and lead-time calculations, the validation ordering that guards every mutation, and the state machines that move quotes, jobs, batches, appointments, claims, and remakes through their lifecycles.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If `X-User-Role` is missing or is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the header is present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes five roles, spelled exactly as follows: `ShopAdmin`, `Estimator`, `Contractor`, `Fabricator`, and `Scheduler`.

- A `ShopAdmin` is the shop operator: it creates contractor accounts, changes their status, registers furnaces and crews, cancels jobs, adjudicates claims, and controls the logical clock. When `X-User-Role` is `ShopAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.
- An `Estimator` measures glass, builds quotes, adds line items, and sends and revises quotes. When `X-User-Role` is `Estimator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.
- A `Fabricator` schedules, completes, and cancels tempering batches and completes remake orders. When `X-User-Role` is `Fabricator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- A `Scheduler` schedules and completes install appointments. When `X-User-Role` is `Scheduler`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- A `Contractor` is a B2B customer acting strictly on its own account: it accepts its own quotes and files claims on its own jobs. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting `ContractorAccount`. Any ownership check on a resource that references a contractor account compares that resource's `contractor_account_id` to `X-User-ID`; a mismatch is an `ERR_FORBIDDEN` (HTTP 403).

Read (`GET`) access is shared broadly across roles as enumerated in the endpoint table of §4; write operations are restricted to the owning role.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

Unless a specific endpoint states otherwise, every list is sorted by `created_at` in ascending order. The `meta` object of any list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this system — contractor accounts, quotes, line items, jobs, furnaces, tempering batches, install crews, install appointments, claim reports, and remake orders — carries a common set of system-managed fields:

- `id`: a server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, stamped once at creation.
- `updated_at`: an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version`: an integer that starts at 1 on creation and increments by one on every mutation. This field underpins the optimistic concurrency control described in §2.7.

Whenever a derived field on a resource is recomputed as a side effect of some operation — for example, a furnace's `reserved_sqft` changing when a batch is scheduled, or an account's `credit_used_cents` changing when a job is accepted — that recomputation counts as a mutation of the affected resource and therefore refreshes its `updated_at` and increments its `version`.

### 2.5. Monetary Precision, Area, and Rounding

All monetary amounts in this system are integer cents; the field-name suffix `_cents` marks them. Every monetary computation that is not already an exact integer is rounded using the **round half up** convention to a whole cent. Geometric area, used to derive billable square footage, is rounded half up to exactly two decimal places before any downstream use. Lead times are whole days, computed with a ceiling on the fabrication term as described in §3. Where a calculation pins a specific order of rounding (for example, discounting and rounding each quote line before summing), that order is mandatory and is spelled out in the relevant workflow; a different order can differ from the specified result by up to one cent per line and is therefore non-conforming.

### 2.6. Parallel Progress Axes and State Reconciliation

A `Job` does not have a single linear status. It carries three independent status attributes that advance on their own axes: an overall lifecycle `status` (`ACTIVE`, `CLOSED`, or `CANCELLED`), a `fabrication_status` (`PENDING`, `IN_FABRICATION`, `COMPLETE`, or `REOPENED`), and an `install_status` (`NOT_READY`, `READY`, `SCHEDULED`, `INSTALLED`, or `ON_HOLD`). The fabrication axis and the install axis move independently, and the system reconciles them automatically as underlying work advances.

Reconciliation is a *bubble-up* discipline: when a child event satisfies a parent's completion criteria, the server transitions the parent without a separate client request. When fabrication of every line completes, the fabrication axis reaches `COMPLETE` and, in the same operation, the install axis bubbles from `NOT_READY` to `READY`. When an install appointment completes and fabrication is already `COMPLETE`, the job's lifecycle `status` bubbles from `ACTIVE` to `CLOSED`. Conversely, approving a claim on an installed line reopens the job: the fabrication axis drops from `COMPLETE` to `REOPENED`, and a closed job's lifecycle `status` returns from `CLOSED` to `ACTIVE`. Cancellation and compensation cascades (release of credit holds, cancellation of scheduled batches and appointments, release of furnace reservations) are described in the workflows of §3; each such automatic mutation independently refreshes the affected resource's `updated_at` and increments its `version`.

### 2.7. Optimistic Concurrency Control on Contractor Credit

Accepting a quote draws down credit headroom on a `ContractorAccount` that is shared across all of that account's quotes and jobs. To prevent a client from committing against a stale view of that shared account, the accept operation employs optimistic concurrency control. The accept request must carry `expected_account_version`, which is the `version` of the target `ContractorAccount` that the client last observed. If that value does not match the account's current `version` — because the account was mutated after the client read it, for instance by an earlier accepted quote recording its credit hold — the accept is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). A subsequent accept of a *different*, still-`SENT` quote whose own fields are unchanged must still be rejected on this basis if the `expected_account_version` it carries has fallen behind the account's advanced `version`. Only the accept operation takes a version field; no other endpoint requires `expected_account_version`.

### 2.8. Referential Resolution and Validation Ordering

Every mutation is guarded by an ordered chain of checks, and the *first* check to fail determines the error returned. The chain is evaluated in this fixed priority order:

1. **Authentication** — `X-User-Role` present and a known role, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role is permitted for the operation, and a `Contractor` acts only on its own account, else `ERR_FORBIDDEN` (403).
3. **Existence** — every path and body foreign-key id resolves to an existing resource. Ids are validated left-to-right in the order they appear in the path, then the body; the first unresolved id yields `ERR_NOT_FOUND` (404).
4. **Field validation** — on any creation, required fields are present, enum values are legal, `thickness_mm` is one of 6, 10, or 12, `width_in` and `height_in` are greater than 0, `quantity` is at least 1, and any window's end is strictly after its start; otherwise `ERR_VALIDATION` (400).
5. **State legality** — the target resource is in a legal state for the requested transition (for example, accept requires a `SENT` quote, complete requires a `SCHEDULED` batch or appointment, review requires a `FILED` claim), else `ERR_INVALID_STATE` (409).

Beyond this shared prefix, individual operations layer on business checks whose relative order also matters: safety-glazing enforcement precedes cross-entity referential checks, which precede temporal/scheduling checks, which precede capacity checks, which precede the fiscal credit check, which precedes the concurrency (stale-version) check, which precedes warranty-window checks. The exact ordering for each operation is described alongside its workflow in §3; the governing principle is that a cheaper, more fundamental failure surfaces before a more specialized one, so that (for instance) an expired quote surfaces as `ERR_QUOTE_EXPIRED` before the credit ceiling is ever tested.

### 2.9. Credit Standing and Fiscal Governance

A contractor account tracks three monetary quantities in cents. `credit_limit_cents` is the account's ceiling, supplied at creation. `credit_used_cents` is the sum of the `credit_hold_cents` held by that account's `ACTIVE` jobs, and it begins at 0. `available_credit_cents` is `credit_limit_cents` minus `credit_used_cents`. When a quote is accepted, the resulting job's credit hold is added to `credit_used_cents`; when a job is cancelled, its hold is subtracted back; when a billable remake is approved, the remake surcharge is added. No accept may proceed if it would push the account's exposure past its limit, as detailed in §3.4.

## 3. Business Logic & Workflows

### 3.1. Contractor Accounts and Their Credit Standing

A `ShopAdmin` onboards a B2B customer by creating a `ContractorAccount` with a `company_name`, a `tier`, and a `credit_limit_cents` (which must be at least 0). The `tier` is one of `WALK_IN`, `BRONZE`, `SILVER`, or `GOLD`, and it drives the discount applied when the account's quotes are priced. A new account is born with `status` `ACTIVE`, `credit_used_cents` of 0, and `version` 1; its `available_credit_cents` therefore equals its `credit_limit_cents`. The computed `credit_used_cents` reflects the sum of `credit_hold_cents` over that account's `ACTIVE` jobs, and `available_credit_cents` is always `credit_limit_cents` minus `credit_used_cents`.

A `ShopAdmin` may move an account's `status` among `ACTIVE`, `ON_HOLD`, and `SUSPENDED`. The permitted transitions are `ACTIVE` to `ON_HOLD` and back, and `ACTIVE` to `SUSPENDED` and back; each status change increments the account's `version`. An account that is not `ACTIVE` cannot have its quotes accepted (see §3.4). Reading an account returns its `credit_used_cents`, `available_credit_cents`, `version`, and `status`.

### 3.2. Building a Quote: Measurement, Specification, and Line Pricing

An `Estimator` opens a `Quote` for a customer by supplying the `contractor_account_id`. A fresh quote enters in `DRAFT` `status` with `revision_number` 1. While the quote is in `DRAFT`, the estimator adds one `LineItem` at a time, each representing a run of identical panes. A line item's `quote_id` links it to its parent quote.

Each line captures a measurement and a specification: a `product_type` (`SHOWER_ENCLOSURE`, `STOREFRONT`, `CUSTOM_MIRROR`, or `TABLETOP`), a `glass_type` (`ANNEALED`, `TEMPERED`, `LAMINATED`, or `INSULATED`), a `thickness_mm` of 6, 10, or 12, a `width_in` and `height_in` in inches (each strictly positive), and a `quantity` of at least one identical pane. Two optional properties round out the spec: `edge_work`, which is `NONE`, `POLISHED`, or `BEVELED` and defaults to `NONE`; and `requires_safety_glazing`, a boolean defaulting to false that marks panes where building code mandates safety glazing. A new line item enters in `SPEC` `status`.

The moment a line is added, three computed money-and-area fields are derived and stored. First, the pane's geometric area in square feet is the `width_in` multiplied by the `height_in`, divided by 144, rounded half up to two decimal places. The `billable_sqft` is then the greater of that area and a per-pane floor of 4.0 square feet. Second, a per-square-foot rate term is assembled: a base rate by glass type — 800 cents for `ANNEALED`, 1400 for `TEMPERED`, 2000 for `LAMINATED`, and 2600 for `INSULATED` — is multiplied by a thickness multiplier of 1.0 for 6 mm, 1.25 for 10 mm, or 1.5 for 12 mm, and then an edge rate is added: 0 cents for `NONE`, 150 for `POLISHED`, or 300 for `BEVELED`. The `unit_price_cents` is the `billable_sqft` multiplied by that assembled rate term, rounded half up to a whole cent, plus a flat product fee added *after* that rounding: 5000 cents for `SHOWER_ENCLOSURE`, 8000 for `STOREFRONT`, 2000 for `CUSTOM_MIRROR`, and 1500 for `TABLETOP`. Finally, the `line_total_cents` is the `unit_price_cents` multiplied by the `quantity`. These same figures are recomputed on read. A line item also carries a `status` that later advances through fabrication and installation.

### 3.3. Sending and Revising a Quote

When the estimator sends a `DRAFT` quote, it must contain at least one line item; sending an empty quote is rejected with `ERR_QUOTE_EMPTY` (HTTP 422). Sending advances the quote's `status` from `DRAFT` to `SENT` and freezes three groups of computed values on the quote.

The totals are computed with a *pinned rounding order*. The tier discount percentage is taken from the account's `tier`: `WALK_IN` gets 0.0, `BRONZE` 0.05, `SILVER` 0.10, and `GOLD` 0.15. The `subtotal_cents` is the plain sum of every line's `line_total_cents`. The `total_cents` is computed by taking each line's `line_total_cents`, multiplying it by one minus the tier percentage, rounding that discounted line half up to a whole cent, and only then summing across the lines — the discount is applied and rounded per line *before* the sum, not after. The `discount_cents` is the `subtotal_cents` minus the `total_cents`.

Sending also stamps a provisional lead time and an expiry. The `quoted_lead_days` is a provisional estimate that ignores the furnace queue: it is a base fabrication allowance of 3 days, plus the number of days needed to fabricate this quote's glass, plus a fixed install allowance of 2 days. The fabrication days are the quote's total billable area — the sum over lines of `billable_sqft` multiplied by `quantity` — divided by a standard throughput of 50 square feet per day, rounded up to the next whole day. The `valid_until` timestamp is stamped as the quote's `created_at` plus 30 days.

A `SENT` quote can be pulled back for edits. Revising returns the quote's `status` from `SENT` to `DRAFT`, increments its `revision_number` by one, and clears `quoted_lead_days` and `valid_until` back to null; they are re-stamped the next time the quote is sent. This send-and-revise loop may repeat any number of times until the quote is accepted. A quote's terminal outcome is `ORDERED`; once ordered it cannot be revised or re-sent.

### 3.4. Accepting a Quote: Job Creation, Credit Hold, and Committed Lead Time

Acceptance is the pivot from sales to production, and only the owning `Contractor` may accept — the acting `X-User-ID` must equal the quote's `contractor_account_id`, else `ERR_FORBIDDEN`. The accept request carries a single body field, `expected_account_version`. Acceptance runs an ordered gauntlet of checks after authentication, authorization, and existence: the quote must be in `SENT` `status` (else `ERR_INVALID_STATE`); the owning `ContractorAccount` must be `ACTIVE` (else `ERR_ACCOUNT_NOT_ACTIVE`, HTTP 409); the quote must not be expired, meaning the current clock is at or before `valid_until` (else `ERR_QUOTE_EXPIRED`, HTTP 409); the account's `available_credit_cents` must be at least the quote's `total_cents` (else `ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 409); and finally `expected_account_version` must match the account's current `version` (else `ERR_STALE_ACCOUNT_VERSION`, HTTP 412). The account-active, expiry, credit, and stale-version checks are evaluated in exactly that order.

On success, the quote transitions from `SENT` to the terminal `ORDERED` state and a new `Job` is created. The job records the originating `quote_id` and `contractor_account_id`, and starts with lifecycle `status` `ACTIVE`, `fabrication_status` `PENDING`, and `install_status` `NOT_READY`; the quote's `ordered_job_id` is set to the new job's `id`. The job's `job_fab_sqft` is the total billable area of the quote — the sum over lines of `billable_sqft` multiplied by `quantity`.

Acceptance stamps a *committed* lead time on the job that, unlike the quoted estimate, accounts for the furnace backlog observed at accept time. The `committed_lead_days` is the base fabrication allowance of 3 days, plus the number of days to fabricate the combined workload divided by the standard throughput of 50 square feet per day and rounded up to the next whole day, plus the fixed install allowance of 2 days. The combined workload is the current scheduled backlog — the sum of `total_sqft` over *all* tempering batches in `SCHEDULED` status across the shop — added to this job's `job_fab_sqft`. Because the backlog term is included, identical glass yields a longer committed lead time than its quoted lead time whenever the furnace queue is non-empty.

Acceptance also reserves credit. The job's `credit_hold_cents` is set to the quote's `total_cents`, that amount is added to the account's `credit_used_cents`, and the account's `version` is incremented by one. As a final cascade caused by the job's creation, every one of the quote's line items advances from `SPEC` to `FABRICATING`.

### 3.5. Fabrication: Tempering Batches on Furnaces

Fabrication capacity lives in `TemperingFurnace` resources, which a `ShopAdmin` registers with a `name`, a `max_batch_sqft` (strictly positive) that caps how much glass one batch may load, and an optional `cooldown_minutes` that defaults to 60 and defines the mandatory gap required after a batch window before the next batch may begin on that furnace. A furnace's `reserved_sqft` starts at 0 and tracks the sum of `total_sqft` over its `SCHEDULED` batches.

A `Fabricator` schedules a `TemperingBatch` by supplying the `job_id`, the `furnace_id`, and a `scheduled_start` and `scheduled_end` window (the end must be strictly after the start). At creation the batch's `total_sqft` is computed as the sum, over the job's line items currently in `FABRICATING` status, of `billable_sqft` multiplied by `quantity`. If no line remains in `FABRICATING`, the batch would be empty and the request is rejected with `ERR_EMPTY_BATCH` (HTTP 422). Two capacity-and-timing guards apply, in this order: first, the batch window must not collide with another `SCHEDULED` batch on the same furnace once the furnace's `cooldown_minutes` buffer is added after each batch window, else `ERR_FURNACE_WINDOW_CONFLICT` (HTTP 409); then the batch's `total_sqft` must not exceed the furnace's `max_batch_sqft`, else `ERR_BATCH_CAPACITY_EXCEEDED` (HTTP 422). On success the batch enters `SCHEDULED` status, the furnace's `reserved_sqft` increases by the batch's `total_sqft`, and if this is the job's first batch its `fabrication_status` advances from `PENDING` to `IN_FABRICATION`.

Completing a `SCHEDULED` batch (permitted only from `SCHEDULED`, else `ERR_INVALID_STATE`) moves it to `DONE`, advances each of the job's `FABRICATING` line items to `FABRICATED`, and releases the batch's `total_sqft` back from the furnace's `reserved_sqft`. If, after this, every line item of the job is `FABRICATED`, the job's `fabrication_status` bubbles from `IN_FABRICATION` to `COMPLETE`, which in turn bubbles the `install_status` from `NOT_READY` to `READY`. Cancelling a `SCHEDULED` batch (again only from `SCHEDULED`) moves it to `CANCELLED` and, as compensation, releases its `total_sqft` from the furnace's `reserved_sqft`.

### 3.6. Installation: Crews, Safety Glazing, and Completion

Install capacity lives in `InstallCrew` resources, which a `ShopAdmin` registers with a `name` and a `certified_products` array listing the product types the crew is qualified to install. A `Scheduler` books an `InstallAppointment` by supplying the `job_id`, the `crew_id`, and a `window_start` and `window_end` (the end strictly after the start).

Booking runs several business checks in order. Safety glazing is enforced first: any line item with `requires_safety_glazing` set to true must have a `glass_type` of `TEMPERED` or `LAMINATED` before install can be scheduled, else `ERR_SAFETY_GLAZING_REQUIRED` (HTTP 422). Next, the job's `fabrication_status` must be `COMPLETE`, else `ERR_FABRICATION_INCOMPLETE` (HTTP 409). Then the crew must be certified for every product type present in the job — every distinct `product_type` among the job's lines must appear in the crew's `certified_products` — else `ERR_CREW_NOT_CERTIFIED` (HTTP 409). Finally, the appointment window must not overlap another `SCHEDULED` appointment on the same crew, evaluated as half-open intervals, else `ERR_CREW_DOUBLE_BOOKED` (HTTP 409). On success the appointment enters `SCHEDULED` status and the job's `install_status` advances from `READY` to `SCHEDULED`.

Completing a `SCHEDULED` appointment (permitted only from `SCHEDULED`, else `ERR_INVALID_STATE`) moves it to `COMPLETED`, advances each of the job's `FABRICATED` line items to `INSTALLED`, and moves the job's `install_status` from `SCHEDULED` to `INSTALLED`. If the job's `fabrication_status` is already `COMPLETE` at that moment, the job's lifecycle `status` bubbles from `ACTIVE` to `CLOSED`.

### 3.7. Breakage, Warranty Claims, and Remakes

Breakage and post-install defects are handled through claims. A `Scheduler`, `Fabricator`, or `Contractor` files a `ClaimReport` against a specific line by supplying the `job_id`, the `line_item_id`, a `claim_type` of `BREAKAGE` (physical breakage) or `WARRANTY_DEFECT` (post-install defect), and a free-text `cause`. An optional `billable_to_contractor` boolean, defaulting to false, records whether the remake cost is charged to the contractor (site-fault breakage) or absorbed by the shop (shop-fault or warranty). A new claim enters in `FILED` status.

Two temporal and target constraints guard claim filing. A `WARRANTY_DEFECT` claim is valid only within 365 days of the target line's installation; filed later, it is rejected with `ERR_CLAIM_WINDOW_EXPIRED` (HTTP 409). The claim target must also be in a claimable line state: a `WARRANTY_DEFECT` requires the line to be `INSTALLED`, while a `BREAKAGE` may target a line that is either `FABRICATED` or `INSTALLED`; any other target state is rejected with `ERR_CLAIM_TARGET_INVALID` (HTTP 409).

Only a `ShopAdmin` adjudicates a `FILED` claim by supplying a `decision` of `APPROVE` or `REJECT` (a claim must be `FILED` to be reviewed, else `ERR_INVALID_STATE`). Rejecting moves the claim to `REJECTED` with no further effect. Approving moves the claim to `APPROVED` and unleashes a three-hop cascade. First, the target line item — whether it was `INSTALLED` or `FABRICATED` — transitions to `BROKEN`. Second, caused by that line breaking, a `RemakeOrder` is created in `PENDING` status: it copies the `claim_report_id`, `job_id`, `line_item_id`, and `billable_to_contractor` from the claim, and its `remake_cost_cents` is the line's `unit_price_cents` plus a remake surcharge of 2500 cents; the claim's `remake_order_id` is set to the new order's `id`; the job's `fabrication_status` moves from `COMPLETE` to `REOPENED`; and if the broken line had been `INSTALLED`, the job's `install_status` moves from `INSTALLED` to `ON_HOLD` and, if the job had previously `CLOSED`, its lifecycle `status` returns from `CLOSED` to `ACTIVE`. Third, caused by the remake order's creation, if `billable_to_contractor` is true then the remake surcharge of 2500 cents is added both to the account's `credit_used_cents` and to the job's `credit_hold_cents`.

A `Fabricator` completes a `PENDING` remake (only from `PENDING`, else `ERR_INVALID_STATE`), moving the `RemakeOrder` to `COMPLETE` and returning its target line item from `BROKEN` to `FABRICATED`. If, after that, every line item of the job is `FABRICATED` or `INSTALLED`, the job's `fabrication_status` bubbles from `REOPENED` back to `COMPLETE`.

### 3.8. Job Cancellation and As-Built Exposure

A `ShopAdmin` may cancel a job, but only while its lifecycle `status` is `ACTIVE` (else `ERR_INVALID_STATE`). Cancellation moves the job's `status` from `ACTIVE` to `CANCELLED` and runs a compensation-and-cascade sweep: the job's `credit_hold_cents` is subtracted back from the account's `credit_used_cents`, releasing the reservation; every `SCHEDULED` tempering batch of the job is cancelled, each releasing its `total_sqft` from its furnace's `reserved_sqft`; and every `SCHEDULED` install appointment of the job is cancelled.

Throughout a job's life, its `final_total_cents` reflects the *as-built* exposure rather than the provisional hold. Recomputed on read, it is the sum, over the job's line items currently in `INSTALLED` status, of each such line's `line_total_cents` multiplied by one minus the account's tier percentage and rounded half up per line, plus the remake surcharge of 2500 cents for each `RemakeOrder` of the job whose `billable_to_contractor` is true. This as-built figure diverges from the provisional `credit_hold_cents` whenever a billable remake occurs or a line never installs.

The shop's logical clock underpins every temporal rule above — quote expiry at accept and the warranty window at claim filing. A `ShopAdmin` holds an admin-only test-driving capability that sets the server's logical clock to a supplied `to_iso8601` instant. The clock starts at `2026-05-01T00:00:00Z` at server startup and never falls back to real wall-clock time.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read or modify an existing resource return `200 OK`. All endpoints are mounted at the service root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/contractor-accounts` | Create a B2B contractor account | ShopAdmin |
| GET | `/contractor-accounts/{id}` | Read a contractor account | ShopAdmin, Estimator, Contractor |
| POST | `/contractor-accounts/{id}/set-status` | Change account status | ShopAdmin |
| POST | `/quotes` | Create a DRAFT quote | Estimator |
| GET | `/quotes/{id}` | Read a quote with computed totals and lead time | Estimator, Contractor, ShopAdmin |
| GET | `/quotes` | List quotes; filter by account or status | Estimator, Contractor, ShopAdmin |
| POST | `/quotes/{id}/line-items` | Add a glass line item to a DRAFT quote | Estimator |
| GET | `/quotes/{id}/line-items` | List a quote's line items | Estimator, Contractor, ShopAdmin |
| POST | `/quotes/{id}/send` | Send a DRAFT quote (freeze totals and lead time) | Estimator |
| POST | `/quotes/{id}/revise` | Return a SENT quote to DRAFT | Estimator |
| POST | `/quotes/{id}/accept` | Accept a SENT quote; create a job and hold credit | Contractor |
| GET | `/jobs/{id}` | Read a job | Estimator, Fabricator, Scheduler, ShopAdmin, Contractor |
| GET | `/jobs` | List jobs; filter by quote or account | Estimator, Fabricator, Scheduler, ShopAdmin, Contractor |
| POST | `/jobs/{id}/cancel` | Cancel an ACTIVE job | ShopAdmin |
| POST | `/tempering-furnaces` | Register a tempering furnace | ShopAdmin |
| GET | `/tempering-furnaces/{id}` | Read a furnace | Fabricator, ShopAdmin |
| POST | `/tempering-batches` | Schedule a tempering batch on a furnace window | Fabricator |
| GET | `/tempering-batches/{id}` | Read a tempering batch | Fabricator, ShopAdmin |
| GET | `/tempering-batches` | List batches; filter by furnace, job, or status | Fabricator, ShopAdmin |
| POST | `/tempering-batches/{id}/complete` | Complete a batch; fabricate its lines | Fabricator |
| POST | `/tempering-batches/{id}/cancel` | Cancel a SCHEDULED batch | Fabricator |
| POST | `/install-crews` | Register an install crew with certifications | ShopAdmin |
| POST | `/install-appointments` | Schedule an install appointment on a crew window | Scheduler |
| GET | `/install-appointments/{id}` | Read an install appointment | Scheduler, ShopAdmin |
| GET | `/install-appointments` | List appointments; filter by crew, job, or status | Scheduler, ShopAdmin |
| POST | `/install-appointments/{id}/complete` | Complete an install; mark lines INSTALLED | Scheduler |
| POST | `/claim-reports` | File a breakage or warranty claim | Scheduler, Fabricator, Contractor |
| GET | `/claim-reports/{id}` | Read a claim report | Scheduler, Fabricator, ShopAdmin, Contractor |
| GET | `/claim-reports` | List claims; filter by line item, job, or status | Scheduler, Fabricator, ShopAdmin, Contractor |
| POST | `/claim-reports/{id}/review` | Adjudicate a FILED claim | ShopAdmin |
| GET | `/remake-orders/{id}` | Read a remake order | Fabricator, Scheduler, ShopAdmin |
| GET | `/remake-orders` | List remake orders; filter by claim, job, line item, or status | Fabricator, Scheduler, ShopAdmin |
| POST | `/remake-orders/{id}/complete` | Complete a remake; re-fabricate the line | Fabricator |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ShopAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_QUOTE_EMPTY` | 422 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 |
| `ERR_STALE_ACCOUNT_VERSION` | 412 |
| `ERR_FABRICATION_INCOMPLETE` | 409 |
| `ERR_SAFETY_GLAZING_REQUIRED` | 422 |
| `ERR_CREW_NOT_CERTIFIED` | 409 |
| `ERR_CREW_DOUBLE_BOOKED` | 409 |
| `ERR_FURNACE_WINDOW_CONFLICT` | 409 |
| `ERR_BATCH_CAPACITY_EXCEEDED` | 422 |
| `ERR_EMPTY_BATCH` | 422 |
| `ERR_CLAIM_WINDOW_EXPIRED` | 409 |
| `ERR_CLAIM_TARGET_INVALID` | 409 |
| `ERR_PAGINATION_INVALID` | 400 |
