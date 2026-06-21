# Junk Removal & Hauling API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Junk Removal & Hauling API, a back-office platform that takes a residential or commercial junk-removal job from a customer's first photo through to a settled invoice. The business it models is fundamentally a pricing engine wrapped around a field-operations workflow: customers submit photos of the pile they want hauled away, an estimator reads a rough truck-fraction from the photo, and the platform quotes a price; later, an on-site crew weighs and measures the actual load, diverts what it can to donation or recycling, dumps the remainder at a landfill, and the platform reconciles the quoted estimate against the real cost.

Two pricing realities sit at the heart of the system and must never be conflated. The first is the **photo estimate** — a quote produced before anyone touches the junk, derived from the estimator's eyeballed truck-fraction and the items the customer declared. The second is the **final actual** — the bill computed after the load is weighed on site, incorporating measured volume, the items the crew really hauled, landfill dump fees, recycling gate fees, donation and recycling diversion credits, and tax. The estimate is deliberately incomplete (dump, diversion, and tax are unknowable before the load is weighed), and the final figure is authoritative. A parallel duality governs landfill costs: a single physical dump can be billed either by weight (tons times a per-ton tipping rate) or by volume (truck-fraction-to-landfill times a flat full-truck dump cost), and the same load can yield two different fees depending on which basis the ticket records.

Layered on top of pricing is a temporal scheduling problem. Each job is served by a **dispatch** that reserves a specific crew and truck for a pickup window, and those reservations must respect crew shift boundaries, inter-window travel buffers, truck exclusivity, hazmat certification for refrigerant appliances, and the customer's credit limit. Because crews and jobs can be acted on concurrently by different operators, the platform uses optimistic concurrency control on crew and job versions to keep scheduling decisions from racing against stale data.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_AUTH`. When the headers are well-formed but the role is not permitted to perform the requested operation — or an ownership-bound actor is acting on a resource it does not own — the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly five roles: `PlatformAdmin`, `Customer`, `Dispatcher`, `CrewLead`, and `Billing`.

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The platform admin owns all configuration — pricing policies, crews, trucks, and customer registration — and the test clock; the server does not compare its identifier to any entity's `id`.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's customer foreign key (`customer_id`) to `X-User-ID`. A customer may only create, estimate, accept, revise, cancel, or dispute against jobs and invoices it owns.
- When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record or accept it for scheduling actions but does not compare it to any entity's `id`.
- When `X-User-Role` is `CrewLead`, `X-User-ID` is the `id` of the acting `Crew`; ownership checks on any resource that references a `Crew` compare the resource's crew foreign key (`crew_id`, reached through the job's dispatch) to `X-User-ID`. A crew lead executes on-site actions for the crew assigned to the job.
- When `X-User-Role` is `Billing`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system — pricing policies, customers, crews, trucks, haul jobs, job items, photo estimates, dispatches, and invoices — carry a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix, serving as identity only.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` — an ISO 8601 UTC timestamp recording the last modification; refreshed on every mutation of the resource.
- `version` — an integer that starts at its initial value and increments by one on every mutation of the resource. It is the basis for optimistic concurrency control (see §2.10).

Two entities are deliberately leaner. A `DiversionRecord` and a `DumpTicket` are immutable line items appended to a job during the on-site phase; each carries only an `id` and a `created_at`. Neither has an `updated_at` nor a `version` field — they are written once and never mutated.

Whenever a derived field changes as a side effect of some other action — for example, a crew's `reserved_minutes` shifting because a dispatch was created or voided, or a customer's `outstanding_balance_cents` changing because an invoice was issued or settled — that change is a mutation of the owning resource: it refreshes the owner's `updated_at` and increments the owner's `version`.

### 2.5. Cascading Side Effects and Hierarchical Consistency

A `HaulJob` is the central aggregate; it owns a tree of child resources (`JobItem`, `PhotoEstimate`, `DiversionRecord`, `DumpTicket`, `Invoice`) and is served by a cross-aggregate `Dispatch` that also references a `Crew` and a `Truck`. Because a single operation on the job frequently mutates more than one entity, the platform applies all consequent effects atomically and keeps derived fields reconciled immediately rather than lazily.

Two derived fields are always reconciled by recomputation from their source set, never by blind delta arithmetic that could drift. A crew's `reserved_minutes` is recomputed as the total window length of all of that crew's dispatches that are currently holding the crew (see §2.7 and §3.5). A customer's `outstanding_balance_cents` is recomputed as the total of the customer's still-owed invoices (see §2.9 and §3.8). Each recomputation that changes a value is a mutation of the crew or customer respectively and bumps that resource's `version` and `updated_at`.

### 2.6. Nested Resource Retrieval and Existence Ordering

Many endpoints address a child or related resource through a path that names a parent first — for example a photo estimate, dispatch, or invoice reached beneath a specific job. The platform validates the existence of each identifier in the path in strict left-to-right order, and rejects on the first one that does not resolve. A job-scoped estimate path, for instance, validates the job identifier before the estimate identifier: a missing job yields `ERR_JOB_NOT_FOUND` before the estimate is ever looked up, and only once the job is confirmed does a missing estimate yield `ERR_ESTIMATE_NOT_FOUND`. The same precedence applies to body references: a dispatch create resolves its `crew_id`, `truck_id`, and the referenced job, each producing its own not-found error (`ERR_CREW_NOT_FOUND`, `ERR_TRUCK_NOT_FOUND`, `ERR_JOB_NOT_FOUND`). Dispatch, invoice, customer, and policy identifiers each have their own not-found errors as well: `ERR_DISPATCH_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, and `ERR_POLICY_NOT_FOUND`.

### 2.7. Validation Ordering Across an Endpoint

When a single request could fail several different checks, the platform evaluates them in a fixed priority order so that the same request always produces the same error. The order is: first, authentication — the `X-User-ID` and `X-User-Role` headers must be present and the role must be known (`ERR_MISSING_OR_INVALID_AUTH`); second, authorization — the role must be permitted for the operation, and an ownership-bound actor must own the resource (`ERR_FORBIDDEN_ROLE`); third, existence — every path and body identifier must resolve, left to right (the not-found errors of §2.6); fourth, request well-formedness — required fields present, enums and types valid, with the structural rules described below (`ERR_INVALID_REQUEST`), and, on job creation specifically, the presence of an active pricing policy (`ERR_NO_ACTIVE_POLICY`); fifth, target-state correctness for the requested transition (the various "not in expected state" conflicts); sixth, cross-entity state guards (crew on duty, truck in service, job billable); seventh, the hazmat safety guard (`ERR_CREW_NOT_HAZMAT`); eighth, the temporal scheduling guards (shift containment and window conflicts); ninth, the fiscal credit-limit guard (`ERR_CREDIT_LIMIT_EXCEEDED`); and tenth, the optimistic-concurrency version guards (`ERR_STALE_CREW_VERSION`, `ERR_STALE_JOB_VERSION`).

Request well-formedness, evaluated at the fourth tier, covers: required fields are present; enum values are drawn from their allowed set; a `quantity` is at least 1; a dispatch's `window_end_utc` is strictly later than its `window_start_utc`; and a photo estimate's `raw_fraction` is greater than 0 and at most 1.0. Any violation of these structural rules is `ERR_INVALID_REQUEST`. The one structural rule that carries its own distinct code is the on-site load fraction: a `measured_truck_fraction` that is not greater than 0 and at most 1.0 is rejected with `ERR_INVALID_FRACTION`.

### 2.8. Money, Fractions, Weights, and Rounding

All monetary amounts in the system are integer cents. Every rounding step in every calculation uses the round-half-up convention, applied at each individual rounding point named in the calculation rather than only once at the end — surcharges, for example, round per item before being summed, and the base haul cost, the same-day uplift, each recycling fee, each diversion credit, and the tax each round independently. Percentage fields such as the same-day surcharge, tax rate, and cancellation percentages preserve their input precision and are used as multipliers in those rounding steps.

Truck fractions are floats billed in eighths. The billing granularity is governed by a pricing policy's `fraction_step`, which defaults to 0.125; a measured or estimated raw fraction is always rounded **up** to the next whole multiple of `fraction_step`. After that round-up, a floor is applied: the billed fraction may not fall below the policy's `min_billable_fraction`, which also defaults to 0.125. Billed fractions therefore always land exactly on multiples of the step. Weights are expressed in tons as floats.

### 2.9. The Customer Ledger Principle

A customer's `outstanding_balance_cents` is a computed field that the platform keeps as the authoritative running total of what the customer currently owes. It is defined as the sum of `total_cents` over every invoice belonging to that customer whose `billing_status` is `ISSUED` — that is, invoices that have been billed but not yet settled. A newly registered customer starts with an outstanding balance of 0. Issuing an invoice (on job completion, or on a cancellation that carries a fee) raises the balance; settling an invoice lowers it. The balance is never tracked by incrementing and decrementing a stored counter in isolation — it is recomputed from the customer's `ISSUED` invoice set on every issue and every settle, so it cannot drift.

Each customer also carries a `credit_limit_cents` (default 50000), the maximum outstanding exposure permitted before new commitments are blocked. When a dispatch is created or a job is completed, the platform checks that the customer's current outstanding balance plus the new exposure would not exceed the credit limit; if it would, the operation is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`.

### 2.10. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of a parent resource, and both reject stale writes rather than silently overwriting.

When a dispatch is created, the request must carry `expected_crew_version` holding the client's last observed `version` of the target `Crew`. If that value does not match the crew's current `version` — because another writer has, for instance, reserved an overlapping window on the same crew and thereby advanced the crew's version since the client last read it — the create is rejected with `ERR_STALE_CREW_VERSION` (HTTP 412). This prevents the new dispatch from running its overlap check against an outdated picture of the crew's schedule.

When a scheduled job is revised, the request must carry `expected_job_version` holding the client's last observed `version` of the target `HaulJob`. If that value does not match the job's current `version` — because a prior re-estimate or dispatch has already moved the job since the client last read it — the revise is rejected with `ERR_STALE_JOB_VERSION` (HTTP 412).

No other endpoint takes a version field, and the version guard is never optional on these two operations: the field must be present and must match.

### 2.11. Pricing Policy Activation

Pricing is configured through `PricingPolicy` resources, each labeled by a `name` and carrying all of the rates the engine needs. A policy's `status` is either `ACTIVE` or `RETIRED`, and at most one policy is `ACTIVE` at any time. The first policy created becomes `ACTIVE`; whenever a new policy is created and activated, any policy that was previously `ACTIVE` transitions to `RETIRED`. A `HaulJob` pins the `id` of whatever policy is `ACTIVE` at the moment of job creation into its `pricing_policy_id`, and that policy is frozen for the life of the job — later activations of other policies do not change how an existing job prices.

A pricing policy's rate fields are: `full_truck_cents`, the price of a full (1.0) truckload at the base tier; `tier_breaks`, an ordered array of bands described in §3.3; `min_billable_fraction` and `fraction_step` for fraction billing (both defaulting to 0.125); the three item surcharges `mattress_surcharge_cents`, `appliance_surcharge_cents`, and `freon_surcharge_cents`; the two landfill rates `dump_fee_per_ton_cents` (weight basis) and `full_truck_dump_cents` (volume basis); the recycling gate rate `recycle_fee_per_ton_cents`; the diversion credit rate `diversion_credit_per_ton_cents`; the `same_day_surcharge_pct` (default 0.20); the `tax_pct` (default 0.08); and the two cancellation rates `cancel_pct_scheduled` (default 0.25) and `cancel_pct_dispatched` (default 0.50). All cents-denominated rate fields must be at least 0, and the percentage fields must be at least 0.

## 3. Business Logic & Workflows

### 3.1. Configuration: Policies, Customers, Crews, and Trucks

Before any job can be priced, a platform operator stands up the configuration entities. Creating a pricing policy supplies its `name`, `full_truck_cents`, `tier_breaks`, the surcharge and landfill rates, and optionally the fraction and percentage knobs; the new policy becomes `ACTIVE` and retires the prior active policy as described in §2.11. Registering a customer supplies an `email` and a `full_name`, optionally a `credit_limit_cents`; the email must be unique among customers, the customer is created with `status` `ACTIVE`, and its `outstanding_balance_cents` starts at 0.

A crew is created with a `name` and a daily shift window defined by `shift_start_utc` (inclusive) and `shift_end_utc` (exclusive), optionally a `buffer_minutes` (default 30) and a `hazmat_certified` flag (default false). A new crew starts `ON_DUTY` with `reserved_minutes` of 0. A crew's duty `status` may later be set to `ON_DUTY` or `OFF_DUTY`; each such change is a mutation that increments the crew's `version` by one. A truck is created with a `name` and starts `IN_SERVICE`; its `status` may later be set to `IN_SERVICE` or `OUT_OF_SERVICE`. The `buffer_minutes` value is the minimum travel gap required between any two pickup windows assigned to the same crew, and `hazmat_certified` records whether the crew is permitted to handle refrigerant appliances.

### 3.2. Job Intake and the Photo Estimate

A customer (or a dispatcher acting on their behalf) opens a job by supplying the `customer_id`, the `service_type`, and the pickup `address`. The job is created in `DRAFT`, and its `pricing_policy_id` is set to the currently active policy; if no policy is `ACTIVE` at that moment, the creation is rejected with `ERR_NO_ACTIVE_POLICY`. The `service_type` is either `SAME_DAY` or `SCHEDULED`; a `SAME_DAY` job attracts a rush uplift at pricing time, while a `SCHEDULED` job does not. The job's `estimated_truck_fraction`, `measured_truck_fraction`, `estimated_total_cents`, `final_total_cents`, and `cancellation_fee_cents` are all empty at intake and are populated only as the workflow reaches the relevant milestones.

To a `DRAFT` or `ESTIMATED` job, the customer or dispatcher may attach **job items** — the things to be hauled. Each item carries a `category` (one of `STANDARD`, `MATTRESS`, `APPLIANCE`, or `FREON_APPLIANCE`), a `quantity` (default 1, at least 1), and a free-text `description`. These items are the actual manifest used for the final bill.

Quoting begins with a **photo estimate**. The customer or dispatcher submits one with a `photo_url`, a `raw_fraction` (the estimator's eyeballed truck-fraction, which must be greater than 0 and at most 1.0), and an optional `declared_items` array — each entry naming a `category` and a `quantity` — that represents the surcharge-bearing items visible in the photo. A submitted estimate starts in `SUBMITTED` status with `accepted` false. A job may accumulate several submitted estimates over time.

Accepting an estimate is the act that moves a `DRAFT` job to `ESTIMATED`. The customer accepts a specific estimate; to do so the job must have at least one estimate in `SUBMITTED` status (otherwise `ERR_NO_ESTIMATE`) and the targeted estimate itself must be `SUBMITTED` (otherwise `ERR_ESTIMATE_NOT_SUBMITTED`). On acceptance, the targeted estimate transitions `SUBMITTED → ACCEPTED` and its `accepted` flag becomes true; any estimate that was previously `ACCEPTED` on the same job is pushed to `SUPERSEDED` with its `accepted` flag cleared to false, so at most one estimate is accepted per job at any time. Acceptance then computes the job's `estimated_truck_fraction` and `estimated_total_cents` from that accepted estimate, and advances the job `DRAFT → ESTIMATED`.

### 3.3. Pricing the Estimate

The job's `estimated_truck_fraction` is derived from the accepted estimate's `raw_fraction` by the fraction-billing rule: divide the raw fraction by the policy's `fraction_step` and round that quotient up to the next whole number of steps, multiply back by `fraction_step` to get the billed fraction, then take the larger of that billed fraction and the policy's `min_billable_fraction`. The result is always an exact multiple of the step.

The estimated cost, `estimated_total_cents`, is the **base haul cost** computed from `estimated_truck_fraction`, plus a same-day uplift if applicable, plus the declared-item surcharge. The base haul cost is a tiered (marginal-band) function of the billed fraction over the policy's `full_truck_cents`. The policy's `tier_breaks` is an ordered array of bands, each band naming an `upper_fraction` and a `marginal_multiplier`; the bands must start at fraction 0 and end at an `upper_fraction` of 1.0, with strictly increasing upper bounds. To compute the base, walk the bands in order, treating each band as the interval from the previous band's upper bound to its own `upper_fraction`. For each band, the amount of the billed fraction that falls inside that band — the lesser of the billed fraction and the band's upper bound, minus the previous band's upper bound, never less than zero — is multiplied by `full_truck_cents` and by that band's `marginal_multiplier`, and the products are accumulated across all bands. The accumulated base is then rounded.

If the job's `service_type` is `SAME_DAY`, a rush uplift is added: the base is multiplied by the policy's `same_day_surcharge_pct`, that product is rounded, and the result is added to the base. A `SCHEDULED` job skips this step entirely.

The declared-item surcharge sums a per-item surcharge across the accepted estimate's `declared_items`. For each declared entry, the surcharge is the policy's per-category rate multiplied by the entry's quantity, and that product is rounded before being added to the running total. The per-category rates are: `mattress_surcharge_cents` for `MATTRESS`, `appliance_surcharge_cents` for `APPLIANCE` (an appliance without refrigerant), and `freon_surcharge_cents` for `FREON_APPLIANCE` (a refrigerant appliance requiring EPA recovery). A `STANDARD` item carries no surcharge. The estimated total is the base (with any same-day uplift) plus this rounded-per-item surcharge sum. Crucially, the estimate deliberately excludes landfill dump fees, recycling fees, diversion credits, and tax — none of those are knowable until the load is weighed on site, so they appear only in the final bill.

### 3.4. Scheduling: Reserving a Crew and Truck

Once a job is `ESTIMATED`, a dispatcher schedules it by creating a **dispatch** that reserves a crew and a truck for a pickup window. The create supplies the `haul_job_id`, the `crew_id`, the `truck_id`, the `window_start_utc` (inclusive) and `window_end_utc` (exclusive, and strictly after the start), and the `expected_crew_version` carrying the client's last observed crew version. The job must be in `ESTIMATED` status (otherwise `ERR_JOB_NOT_ESTIMATED`).

Several guards apply before a reservation is allowed, and they are evaluated in the priority order of §2.7. The crew version must match (otherwise `ERR_STALE_CREW_VERSION`, HTTP 412, per §2.10). The crew must be `ON_DUTY` (otherwise `ERR_CREW_OFF_DUTY`) and the truck must be `IN_SERVICE` (otherwise `ERR_TRUCK_OUT_OF_SERVICE`). If the job contains any `FREON_APPLIANCE` job item, the assigned crew must have `hazmat_certified` true (otherwise `ERR_CREW_NOT_HAZMAT`, HTTP 422). The pickup window must lie entirely within the crew's shift — its start at or after `shift_start_utc` and its end at or before `shift_end_utc` (otherwise `ERR_WINDOW_OUTSIDE_SHIFT`). The window must keep a gap of at least the crew's `buffer_minutes` from every other window currently held by that crew — that is, from every dispatch on the crew that is `RESERVED` or `ACTIVE` (otherwise `ERR_CREW_WINDOW_CONFLICT`). And the window must not intersect, under half-open interval semantics, any window currently held by that truck — any dispatch on the truck that is `RESERVED` or `ACTIVE` (otherwise `ERR_TRUCK_WINDOW_CONFLICT`). Finally, the customer's outstanding balance plus this job's exposure must not exceed the credit limit (otherwise `ERR_CREDIT_LIMIT_EXCEEDED`, per §2.9).

When all guards pass, the dispatch is created with `dispatch_status` `RESERVED`. Its `window_minutes` is computed as the whole number of minutes between `window_start_utc` and `window_end_utc`. The crew's `reserved_minutes` is recomputed to include this new window, the crew's `version` is incremented by one, and the job advances `ESTIMATED → SCHEDULED`.

### 3.5. The Revision Loop

A scheduled job is not locked in. A customer may revise a `SCHEDULED` job to send it back for re-estimation, and this forms the system's revision cycle (`SCHEDULED → ESTIMATED`, mirroring the `ESTIMATED → SCHEDULED` scheduling edge). The job must be in `SCHEDULED` status (otherwise `ERR_JOB_NOT_REVISABLE`), and the request must carry `expected_job_version` matching the job's current version (otherwise `ERR_STALE_JOB_VERSION`, HTTP 412, per §2.10). On revision, the job's `RESERVED` dispatch transitions to `VOIDED`; the crew's `reserved_minutes` is recomputed to drop that voided window; the job returns to `ESTIMATED` so the customer may submit a fresh estimate, re-accept, and re-dispatch; and the job's `version` is incremented by one. From `ESTIMATED` the customer can accept a new estimate (re-running the estimate pricing) and a dispatcher can re-dispatch, closing the loop.

A crew's `reserved_minutes` is at all times the sum, in whole minutes, of the window lengths of every dispatch on that crew whose `dispatch_status` is `RESERVED` or `ACTIVE`. It is recomputed from that set — never delta-drifted — on every dispatch creation, void, or release, and starts at 0 for a new crew.

### 3.6. On-Site Execution: Activate, Arrive, Divert, Dump, Load

When the crew sets out, the dispatcher activates the reserved dispatch. Activation requires the dispatch to be `RESERVED` (otherwise `ERR_DISPATCH_NOT_RESERVED`) and the crew to be `ON_DUTY` (otherwise `ERR_CREW_OFF_DUTY`); it transitions the dispatch `RESERVED → ACTIVE` and drives the job `SCHEDULED → DISPATCHED`.

The crew lead then marks arrival on a `DISPATCHED` job (otherwise `ERR_JOB_NOT_DISPATCHED`), advancing it `DISPATCHED → ON_SITE`. While the job is `ON_SITE` and before it is loaded, the crew lead records what happens to the junk. A **diversion record** captures material sent to donation or recycling: it names a `destination` (either `DONATION` or `RECYCLING`) and the `tons` diverted (at least 0). Both destinations earn the customer a diversion credit; recycling additionally incurs a recycling gate fee. A **dump ticket** captures material taken to the landfill: it carries `landfill_tons` (at least 0), `landfill_fraction` (the truck-fraction of mixed waste taken to landfill, at least 0 and at most 1.0), and a `fee_basis` of either `WEIGHT_BASED` or `VOLUME_BASED`. Each dump ticket's `dump_fee_cents` is left empty at recording time and is computed later, at load. Recording a diversion or a dump ticket requires the job to be `ON_SITE` (otherwise `ERR_JOB_NOT_ON_SITE`).

Loading closes the on-site phase. The crew lead records the `measured_truck_fraction` — the actual raw fraction measured on site, which must be greater than 0 and at most 1.0 (otherwise `ERR_INVALID_FRACTION`) — on an `ON_SITE` job (otherwise `ERR_JOB_NOT_ON_SITE`). Load stores the measured fraction, computes each dump ticket's `dump_fee_cents`, computes the job's `final_total_cents`, and advances the job `ON_SITE → LOADED`.

### 3.7. Computing the Final Bill

Each dump ticket's pass-through `dump_fee_cents` is computed from its own `fee_basis`. A `WEIGHT_BASED` ticket's fee is its `landfill_tons` multiplied by the policy's `dump_fee_per_ton_cents`, rounded. A `VOLUME_BASED` ticket's fee is its `landfill_fraction` multiplied by the policy's `full_truck_dump_cents`, rounded. The same physical load can therefore produce a different fee under the two bases, and each ticket is computed independently and rounded on its own.

The job's `final_total_cents` is assembled, in cents, as follows. First, the billed fraction is the job's `measured_truck_fraction` put through the same round-up-to-step-then-floor-at-minimum rule used for estimates. The base haul cost is the tiered marginal-band function of that billed fraction over `full_truck_cents`, computed exactly as in §3.3 and then rounded. If the job's `service_type` is `SAME_DAY`, the same-day uplift — the base multiplied by `same_day_surcharge_pct`, rounded — is added to the base. The item surcharge is summed over the job's actual `JobItem` manifest (not the declared estimate items): for each item, its category's surcharge rate multiplied by its `quantity`, rounded per item, then summed. The dump total is the sum of every dump ticket's computed `dump_fee_cents`. The recycling fee is summed over only those diversion records whose `destination` is `RECYCLING`: each such record's `tons` multiplied by `recycle_fee_per_ton_cents`, rounded, then summed. The diversion credit is summed over **all** diversion records regardless of destination — both `DONATION` and `RECYCLING` earn it: each record's `tons` multiplied by `diversion_credit_per_ton_cents`, rounded, then summed. The subtotal is the base (with any uplift) plus the item surcharge plus the dump total plus the recycling fee, minus the diversion credit. Tax is the subtotal multiplied by the policy's `tax_pct`, rounded. The final total is the subtotal plus the tax. Every rounding step here is round-half-up and independent of the others, and the item surcharge rounds per item before summing.

### 3.8. Completion, Invoicing, and Settlement

A dispatcher completes a `LOADED` job (otherwise `ERR_JOB_NOT_LOADED`). Completion issues a **service invoice**: a new `Invoice` is created with `kind` `SERVICE`, `billing_status` `ISSUED`, `dispute_status` `NONE`, `total_cents` equal to the job's `final_total_cents`, and `customer_id` copied from the job. Issuing that invoice raises the customer's `outstanding_balance_cents` (recomputed from the customer's `ISSUED` invoice set, per §2.9). Completion also releases the job's `ACTIVE` dispatch — transitioning it `ACTIVE → RELEASED` — and recomputes the crew's `reserved_minutes` to drop that released window. The job then advances `LOADED → COMPLETED`. Before the invoice is issued, the credit-limit guard applies: if the new exposure would push the customer's outstanding balance over `credit_limit_cents`, completion is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. There is exactly one invoice per completed job.

An invoice carries two independent status dimensions. The `billing_status` runs `ISSUED → SETTLED`, while the `dispute_status` runs across `NONE`, `DISPUTED`, and `RESOLVED`; the two move independently of each other. Billing settles an invoice that is `ISSUED` (otherwise `ERR_INVOICE_NOT_ISSUED`), is not currently `DISPUTED` (otherwise `ERR_INVOICE_DISPUTED`), and whose linked job is in the appropriate terminal state — `COMPLETED` for a `SERVICE` invoice or `CANCELLED` for a `CANCELLATION` invoice (otherwise `ERR_JOB_NOT_BILLABLE`). Settling transitions `billing_status` `ISSUED → SETTLED` and recomputes the customer's `outstanding_balance_cents` downward to drop the now-settled invoice.

A customer may dispute its own invoice while the invoice is `ISSUED` (otherwise `ERR_INVOICE_NOT_ISSUED`) and its `dispute_status` is `NONE` (otherwise `ERR_INVOICE_ALREADY_DISPUTED`); disputing moves `dispute_status` to `DISPUTED` and leaves `billing_status` unchanged at `ISSUED`. Billing resolves a dispute when `dispute_status` is `DISPUTED` (otherwise `ERR_INVOICE_NOT_DISPUTED`); resolving moves `dispute_status` to `RESOLVED`, again leaving `billing_status` unchanged, after which the invoice may be settled.

### 3.9. Cancellation

A customer may cancel its own job while the job is in `ESTIMATED`, `SCHEDULED`, or `DISPATCHED` status (otherwise `ERR_JOB_NOT_CANCELLABLE`). The cancellation fee depends on the job's status at the instant of cancellation: an `ESTIMATED` job cancels with a fee of 0; a `SCHEDULED` job cancels with a fee equal to its `estimated_total_cents` multiplied by the policy's `cancel_pct_scheduled`, rounded; and a `DISPATCHED` job cancels with a fee equal to its `estimated_total_cents` multiplied by the policy's `cancel_pct_dispatched`, rounded. The computed amount is recorded on the job's `cancellation_fee_cents`.

Cancellation also unwinds the schedule. If the job has a `RESERVED` or `ACTIVE` dispatch, that dispatch transitions to `VOIDED` and the crew's `reserved_minutes` is recomputed to drop its window. If the cancellation fee is greater than 0, a **cancellation invoice** is issued: a new `Invoice` with `kind` `CANCELLATION`, `billing_status` `ISSUED`, `dispute_status` `NONE`, and `total_cents` equal to the cancellation fee, and the customer's `outstanding_balance_cents` is recomputed upward accordingly. If the fee is 0, no invoice is created. The job then advances to `CANCELLED`.

### 3.10. Reading the System

Beyond the workflow actions, the platform exposes read access scoped by role. A customer's jobs and invoices can be listed (filterable by status, and by `billing_status` for invoices respectively), as can a crew's dispatches, a truck's dispatches, a job's items, photo estimates, diversion records, dump tickets, and invoices, and the full dispatch list filterable by `haul_job_id`, `crew_id`, `truck_id`, or `dispatch_status`. Job lists may be filtered by `customer_id`, `pricing_policy_id`, and `status`; photo-estimate lists by `status`; diversion lists by `destination`; invoice lists for a job by `kind`. Each of these supports the standard `limit` and `offset` pagination. Single-resource reads return the resource with its computed fields populated — a customer with its current `outstanding_balance_cents`, a crew with its current `reserved_minutes` and `version`, and a job with its estimate and final totals.

Finally, a platform-admin-only test capability sets the server's current UTC clock to a supplied instant via the `to_iso8601` field; this exists so that same-day-versus-scheduled behavior and shift-window containment can be exercised deterministically.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or append a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including state transitions and status changes — return a `200 OK` status code. List and single-resource reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pricing-policies` | Create a pricing policy; it becomes ACTIVE and retires the prior active policy | PlatformAdmin |
| GET | `/pricing-policies/{id}` | Get a pricing policy | PlatformAdmin, Dispatcher, Billing |
| POST | `/customers` | Register a customer | PlatformAdmin |
| GET | `/customers/{id}` | Get a customer with computed outstanding balance | PlatformAdmin, Billing, Dispatcher, Customer |
| GET | `/customers/{id}/haul-jobs` | List a customer's haul jobs | PlatformAdmin, Billing, Dispatcher, Customer |
| GET | `/customers/{id}/invoices` | List a customer's invoices | PlatformAdmin, Billing, Customer |
| POST | `/crews` | Create a crew with a daily shift window | PlatformAdmin |
| GET | `/crews/{id}` | Get a crew with computed reserved minutes and version | PlatformAdmin, Dispatcher, CrewLead |
| GET | `/crews/{id}/dispatches` | List dispatches for a crew | PlatformAdmin, Dispatcher, CrewLead |
| POST | `/crews/{id}/status` | Set crew duty status | PlatformAdmin |
| POST | `/trucks` | Create a truck | PlatformAdmin |
| GET | `/trucks/{id}` | Get a truck | PlatformAdmin, Dispatcher |
| GET | `/trucks/{id}/dispatches` | List dispatches for a truck | PlatformAdmin, Dispatcher |
| POST | `/trucks/{id}/status` | Set truck service status | PlatformAdmin |
| POST | `/haul-jobs` | Create a haul job in DRAFT; pins the active pricing policy | Customer, Dispatcher |
| GET | `/haul-jobs` | List haul jobs | PlatformAdmin, Dispatcher, Billing, Customer |
| GET | `/haul-jobs/{id}` | Get a haul job with computed totals | PlatformAdmin, Dispatcher, Billing, Customer, CrewLead |
| POST | `/haul-jobs/{id}/items` | Add a job item to a DRAFT/ESTIMATED job | Customer, Dispatcher |
| GET | `/haul-jobs/{id}/items` | List job items on a job | PlatformAdmin, Dispatcher, Billing, Customer, CrewLead |
| POST | `/haul-jobs/{id}/photo-estimates` | Submit a photo estimate | Customer, Dispatcher |
| GET | `/haul-jobs/{id}/photo-estimates` | List photo estimates on a job | PlatformAdmin, Dispatcher, Customer |
| POST | `/haul-jobs/{id}/photo-estimates/{estimateId}/accept` | Accept a submitted estimate; move job to ESTIMATED | Customer |
| POST | `/haul-jobs/{id}/revise` | Revise a SCHEDULED job back to ESTIMATED | Customer |
| POST | `/haul-jobs/{id}/arrive` | Mark crew arrival; DISPATCHED to ON_SITE | CrewLead |
| POST | `/haul-jobs/{id}/load` | Record measured load; ON_SITE to LOADED; compute final total | CrewLead |
| POST | `/haul-jobs/{id}/complete` | Complete job; LOADED to COMPLETED; issue service invoice | Dispatcher |
| POST | `/haul-jobs/{id}/cancel` | Cancel a job; assess cancellation fee | Customer |
| GET | `/haul-jobs/{id}/diversions` | List diversion records on a job | PlatformAdmin, Dispatcher, Billing, CrewLead |
| POST | `/haul-jobs/{id}/diversions` | Record a donation/recycling diversion on an ON_SITE job | CrewLead |
| GET | `/haul-jobs/{id}/dump-tickets` | List dump tickets on a job | PlatformAdmin, Dispatcher, Billing, CrewLead |
| POST | `/haul-jobs/{id}/dump-tickets` | Record a landfill dump ticket on an ON_SITE job | CrewLead |
| GET | `/haul-jobs/{id}/invoices` | List invoices for a job | PlatformAdmin, Dispatcher, Billing, Customer |
| POST | `/dispatches` | Create a dispatch reserving crew+truck window; job ESTIMATED to SCHEDULED | Dispatcher |
| GET | `/dispatches` | List dispatches | PlatformAdmin, Dispatcher, CrewLead |
| GET | `/dispatches/{id}` | Get a dispatch | PlatformAdmin, Dispatcher, CrewLead |
| POST | `/dispatches/{id}/activate` | Activate a RESERVED dispatch; job SCHEDULED to DISPATCHED | Dispatcher |
| GET | `/invoices/{id}` | Get an invoice | PlatformAdmin, Billing, Customer |
| POST | `/invoices/{id}/settle` | Settle an ISSUED, non-disputed invoice | Billing |
| POST | `/invoices/{id}/dispute` | Dispute an ISSUED invoice | Customer |
| POST | `/invoices/{id}/resolve-dispute` | Resolve a DISPUTED invoice | Billing |
| POST | `/_clock/set_current_utc` | Test-only: set the server's current UTC clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_AUTH` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_JOB_NOT_FOUND` | 404 Not Found |
| `ERR_ESTIMATE_NOT_FOUND` | 404 Not Found |
| `ERR_DISPATCH_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_NOT_FOUND` | 404 Not Found |
| `ERR_TRUCK_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_FRACTION` | 400 Bad Request |
| `ERR_NO_ACTIVE_POLICY` | 409 Conflict |
| `ERR_NO_ESTIMATE` | 409 Conflict |
| `ERR_ESTIMATE_NOT_SUBMITTED` | 409 Conflict |
| `ERR_JOB_NOT_ESTIMATED` | 409 Conflict |
| `ERR_JOB_NOT_REVISABLE` | 409 Conflict |
| `ERR_JOB_NOT_DISPATCHED` | 409 Conflict |
| `ERR_JOB_NOT_ON_SITE` | 409 Conflict |
| `ERR_JOB_NOT_LOADED` | 409 Conflict |
| `ERR_JOB_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_DISPATCH_NOT_RESERVED` | 409 Conflict |
| `ERR_INVOICE_NOT_ISSUED` | 409 Conflict |
| `ERR_INVOICE_ALREADY_DISPUTED` | 409 Conflict |
| `ERR_INVOICE_NOT_DISPUTED` | 409 Conflict |
| `ERR_INVOICE_DISPUTED` | 409 Conflict |
| `ERR_CREW_OFF_DUTY` | 409 Conflict |
| `ERR_TRUCK_OUT_OF_SERVICE` | 409 Conflict |
| `ERR_JOB_NOT_BILLABLE` | 409 Conflict |
| `ERR_CREW_NOT_HAZMAT` | 422 Unprocessable Entity |
| `ERR_WINDOW_OUTSIDE_SHIFT` | 409 Conflict |
| `ERR_CREW_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_TRUCK_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_CREW_VERSION` | 412 Precondition Failed |
| `ERR_STALE_JOB_VERSION` | 412 Precondition Failed |
