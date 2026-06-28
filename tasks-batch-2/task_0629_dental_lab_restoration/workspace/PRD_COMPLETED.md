# Dental Lab Restoration API — Product Requirements Document

## 1. Introduction

Modern dental laboratories sit at the intersection of clinical craftsmanship and industrial scheduling: a single prescribing doctor sends an impression, scan, or paper prescription, and the lab must turn it into a precisely fabricated crown, bridge, denture, or set of aligners — on a promised deadline, at a contractually correct price, and with a warranty behind it. This API governs that whole pipeline. It tracks a case from intake through computer-aided design, milling or printing, shade-matched try-in, shipping, delivery, and any subsequent warranty remake, while keeping per-unit pricing, volume discounts, rush surcharges, and service-level credits exact to the cent.

The system is built for five collaborating operational roles. Doctors own the clinical decisions on their own cases — what to make, whether the try-in is acceptable, and when to invoke the warranty. Lab technicians shepherd a case through design and fabrication; schedulers reserve milling machines and pack courier routes; billing staff settle invoices and reverse credits; and a lab administrator configures the catalog and adjudicates disputes. Because two cases can contend for the same milling machine and because a doctor's verdict can race against a technician's re-milling step, the platform treats concurrency, revision cycles, and ledger conservation as first-class concerns rather than afterthoughts. The sections that follow define the global contract first, then the business workflows, then the concrete endpoint and error surfaces.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must include `X-User-ID` to identify the acting user and `X-User-Role` to declare their operational capacity. The system recognizes exactly five roles, spelled precisely as `Doctor`, `LabTech`, `Scheduler`, `Billing`, and `LabAdmin`. If either header is missing, or if `X-User-Role` is not one of these five known roles, the request is rejected with `ERR_UNAUTHENTICATED`. When a known, authenticated role attempts an operation it is not permitted to invoke, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Roles differ in how `X-User-ID` is interpreted. When `X-User-Role` is `Doctor`, `X-User-ID` is the `id` of the acting `Doctor`; ownership checks on any resource that references a `Doctor` compare the resource's foreign-key field to `X-User-ID`. Concretely, for Doctor-owned operations — cancelling a case, recording a try-in verdict, and opening a warranty remake request — the acting `X-User-ID` must equal the target case's `doctor_id`; if it does not, the request is rejected with `ERR_NOT_CASE_OWNER` even though the `Doctor` role itself is permitted to call the endpoint. (A `LabAdmin` invoking those same endpoints is exempt from the ownership check.)

When `X-User-Role` is `LabTech`, `Scheduler`, `Billing`, or `LabAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such an identifier for audit purposes but never compares it to any entity's `id` for ownership. `LabTech` operators own restoration setup and the design-and-fabrication advancement of a case. `Scheduler` operators own milling and printing scheduling plus courier routing and delivery confirmation. `Billing` operators own invoice settlement and credit-memo reversal. `LabAdmin` is the superset operational and configuration role: it registers doctors and materials, adjudicates warranty remakes, drives the logical clock, and may perform the shared operations of the other roles (other than ownership-gated Doctor actions).

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

For endpoints that return lists of resources, pagination is controlled via two query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside these bounds is rejected with `ERR_PAGINATION_INVALID`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order; resources sharing an identical `created_at` (common because the logical clock is frozen between advances) are broken by ascending order of creation, so the effective order is the order in which the resources were persisted.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every entity in the system carries a server-minted `id`: a UUID with no type prefix, used for identity only and never as an input to a business decision. Beyond `id`, every entity in this system also carries the full set of audit fields: a `created_at` timestamp set when the resource is first persisted, an `updated_at` timestamp refreshed on every mutation, and an integer `version` that begins at its initial value of 1 and increments by one on each mutation. Both `created_at` and `updated_at` are stamped from the server logical clock of §3.10 (not wall-clock time), so two resources created at the same logical instant carry an identical `created_at`. All of `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. The `version` integer is the basis for optimistic concurrency control described in §2.7. There are no immutable, audit-light entities here: each of `Doctor`, `Material`, `MillMachine`, `CourierRoute`, `Case`, `Restoration`, `FabricationUnit`, `ShadeRecord`, `MillJob`, `RouteStop`, `Invoice`, `CreditMemo`, and `RemakeRequest` exposes `id`, `created_at`, `updated_at`, and `version`.

A computed field that the server recalculates — for example a case's `status`, a doctor's `completed_case_count`, or an invoice's `total_cents` — is itself a mutation: when the server updates such a derived value it refreshes the owning resource's `updated_at` and increments its `version` just as a direct edit would.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many endpoints address a resource through a nested path — for instance a route stop is created against a case, and restorations are listed under a case. When a path or request body names more than one resource, the server validates existence left to right: the parent identifier in the path is checked before any child or foreign-key reference, and the first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404). This existence check is evaluated after authentication and authorization but before business-rule checks, so a request that names a non-existent case never reaches state or pricing logic. Reverse-reachability list endpoints (a doctor's cases, a route's stops, a restoration's units, a unit's remakes, and so on) likewise first confirm the parent exists before returning the attached collection.

### 2.6. Monetary Values, Quantities, and Rounding

All money in this system is stored and returned as integer cents — there are no fractional-cent values and no floating-point money. Field names ending in `_cents` (such as `base_unit_price_cents`, `unit_price_cents`, `subtotal_cents`, `rush_surcharge_cents`, `discount_cents`, `tax_cents`, `sla_credit_cents`, `total_cents`, `amount_cents`, and a doctor's `account_credit_cents`) are always whole-cent integers. Wherever a price or percentage multiplication produces a fractional result, the system rounds half up to the nearest whole cent. "Round half up" means a residual of exactly one half cent rounds away from zero to the next whole cent. This rounding is applied at each individually named computation step, in the pinned order described in §3, rather than once at the end — the order in which rounding is applied is part of the contract and changes the result by up to a cent per line item.

### 2.7. Optimistic Concurrency Control

Two write operations in this system require the client to prove it is acting on a current view of a parent resource, and both reject a stale view rather than silently overwriting it.

First, recording a try-in verdict on a case requires the request to carry `expected_case_version`, a non-optional field whose value must equal the target `Case`'s current `version`. A legitimate event — a lab technician re-milling a requeued unit, or a shade update on a sibling restoration — advances `Case.version`. If the doctor's `expected_case_version` no longer matches the case's current `version`, the verdict is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412), so a doctor can never accept or revise a case whose fabrication state has moved on since they last read it.

Second, starting a mill job requires the request to carry `expected_machine_version`, a non-optional field whose value must equal the target `MillMachine`'s current `version`. When another job has already started on (and thereby advanced the `version` of) that machine, a start request carrying the now-outdated `expected_machine_version` is rejected with `ERR_STALE_MACHINE_VERSION` (HTTP 412), because the machine is occupied and the caller's view of it is stale. No other endpoint takes a version field; endpoints that are not the try-in verdict or the mill-job start neither require nor inspect an expected-version input.

### 2.8. Hierarchical Consistency and Cascades

A `Case` owns its `Restoration`s, and each `Restoration` owns its `FabricationUnit`s, forming a strict ownership tree. Many operations on a case ripple outward across this tree and into the satellite entities (invoice, credit memo, mill jobs, doctor ledger). Whenever a state transition lists secondary effects — requeuing units, voiding an invoice, cancelling mill jobs, issuing or voiding a credit memo, or recomputing a doctor counter — every one of those effects is part of the same operation and is applied together with the primary transition. Each entity touched by a cascade has its own `version` incremented and its own `updated_at` refreshed; the §3 narratives spell out exactly which entities each transition mutates.

### 2.9. Validation Order and Precedence

When several checks could fail for one request, they are evaluated in a fixed precedence so that the returned error is deterministic. The order is: authentication of the headers first (`ERR_UNAUTHENTICATED`); then role authorization for the endpoint (`ERR_FORBIDDEN_ROLE`); then, for the Doctor-owned case-cancel, try-in-verdict, and remake-request-open operations, case ownership (`ERR_NOT_CASE_OWNER`), which on the remake-open endpoint is checked after the path case resolves but before the body's `fabrication_unit_id` is resolved; then existence of every path id and body foreign key, resolved left to right (`ERR_NOT_FOUND`); then that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, HTTP 409); then the optimistic-concurrency version checks (`ERR_STALE_CASE_VERSION` or `ERR_STALE_MACHINE_VERSION`, both HTTP 412); then the domain business-safety, temporal, capacity, and referential checks described throughout §3; and finally, as the lowest-priority schema gate, that the request body is well-formed — required fields present, enum values legal, integers in range — failing which the response is `ERR_INVALID_REQUEST` (HTTP 400). `ERR_VALIDATION` (HTTP 422) is a reserved fallback for a business-rule violation that no more specific code covers. Because state precedes concurrency which precedes the domain checks, a transition attempted from the wrong state surfaces as `ERR_INVALID_STATE` before any version or business check runs.

## 3. Business Logic & Workflows

### 3.1. Catalog, Machines, and Routes: the Standing Configuration

Before any case can move, the lab administrator stands up the reference data. A `Doctor` account records a `full_name`, the `practice_name` they bill under, and an `email` that is expected to be unique per doctor, though the server does not itself enforce this — it accepts any well-formed `email` string and never rejects a duplicate. Each doctor also carries two computed counters that start at zero: `completed_case_count`, the number of that doctor's cases that have reached `DELIVERED`, and `account_credit_cents`, the running ledger of un-applied account credit owed to them.

A `Material` is created with a short `code` that is expected to be unique but is not enforced as such by the server (any non-empty `code` string is accepted, duplicates included; for example `ZIRCONIA`, `EMAX`, `PFM`, `ACRYLIC`, or `PMMA`), a human-readable `name`, an integer `base_unit_price_cents` of at least 1, and a `fabrication_process` of either `MILLED` or `PRINTED`, which fixes whether units made from it are milled or printed. A material also carries an `is_active` flag that defaults to true; only active materials may be chosen on a new restoration.

A `MillMachine` is registered with a `name` and a `capability` of either `MILLED` or `PRINTED`; its `status` begins at `AVAILABLE`. A machine performs only jobs whose process matches its capability. A `CourierRoute` is created with a `label`, a `service_date` (the calendar date in ISO 8601 UTC on which it runs), an integer `max_stops` of at least 1, and a `buffer_minutes` gap (defaulting to 30, and never negative) that must separate consecutive stop windows on that route. A route also tracks a computed `stop_count`, beginning at 0, equal to the number of its route stops whose status is not `CANCELLED`.

### 3.2. Case Intake and Restoration Setup

A case enters the world in `INTAKE`. Creating one records the prescribing `doctor_id`, an `intake_method` of `RX_PAPER`, `IMPRESSION`, or `INTRAORAL_SCAN`, and an optional `is_rush` flag (defaulting to false) indicating the doctor asked for rush turnaround — a choice that later shortens the promised deadline and adds a pricing surcharge. A fresh case starts with `billable_unit_count` and `revision_count` both at 0, and its `status` defaults to `INTAKE`. The SLA timestamps `scheduled_start_at`, `promised_ready_at`, and `shipped_at` are all null at this point, the `sla_breached` flag is false, and the case has no restorations yet.

While the case remains in `INTAKE`, a lab technician adds one or more restorations to it. Each `Restoration` records its parent `case_id`, the chosen `material_id`, a `restoration_type` of `CROWN`, `BRIDGE`, `DENTURE`, or `ALIGNER`, an integer `unit_count` of at least 1 (crowns count teeth, bridges count pontics plus abutments, dentures count arches, aligners count steps), and the doctor's `requested_shade` as a VITA shade code such as "A2". The selected material must have `is_active` true at the moment the restoration is created; choosing an inactive material is rejected with `ERR_MATERIAL_INACTIVE` (HTTP 422). A restoration's `unit_price_cents` is left at 0 on creation and is only computed later, when the case is submitted.

### 3.3. Submitting a Case: Pricing, the SLA Promise, and the Provisional Invoice

Submitting a case advances it from `INTAKE` to `DESIGN`, and it is the single richest moment in the pipeline. The submission is rejected before anything else if the case has no restoration carrying at least one unit — a case with zero billable units cannot be submitted, and the attempt returns `ERR_EMPTY_FABRICATION` (HTTP 422). Given at least one restoration, the transition additionally requires that every restoration on the case references a material that is currently active.

When the transition fires, the server does six things together. First, for each restoration it creates `unit_count` fabrication units, each starting in `QUEUED` with `is_billable` true and `remade_from_unit_id` null. Second, it sets the case's `billable_unit_count` to the sum of every restoration's `unit_count`. Third, it stamps `scheduled_start_at` with the current logical clock — the instant the case leaves `INTAKE`. Fourth, it prices each restoration (see below). Fifth, it computes the turnaround promise and writes `promised_ready_at`. Sixth, it creates exactly one `Invoice` for the case with `kind` `PROVISIONAL`, `billing_status` `DRAFT`, and `delivery_status` `PENDING`, and populates that invoice's amounts. The case's `version` increments by one as part of the submission.

**Per-unit pricing.** Each restoration's `unit_price_cents` is the material's `base_unit_price_cents` multiplied by a type complexity factor and then rounded half up to a whole number of cents. The factor depends on `restoration_type`: a crown uses 1.00, a bridge uses 1.25, a denture uses 2.00, and an aligner uses 0.30. The rounding to whole cents happens per unit, before any quantity multiplication or cross-restoration summation — this ordering is mandatory. The alternative of summing unrounded products and rounding once at the end is explicitly not used and can diverge by up to a cent per line; for instance a base of 9999 cents at factor 1.25 across three units yields 37497 cents under the required per-unit-rounded order versus 37496 cents under round-once.

**The turnaround promise.** The promised deadline is anchored at `scheduled_start_at` plus a number of promised hours. The base figure is the largest per-type turnaround among the case's restorations, where a crown promises 120 hours, a bridge 168 hours, a denture 240 hours, and an aligner 336 hours; the case takes the maximum of these across all its restorations. If the case is not a rush, the promised hours equal that base. If the case is a rush, the promised hours equal the base divided by two using integer floor division, but never less than a floor of 24 hours — that is, the larger of the floor-halved base and 24. The resulting `promised_ready_at` is `scheduled_start_at` advanced by the promised hours.

**The provisional invoice total.** The invoice's `subtotal_cents` is the sum, over every billable fabrication unit on the case, of that unit's restoration's `unit_price_cents`. From that subtotal the server derives the remaining amounts in a pinned order. The `rush_surcharge_cents` is the subtotal multiplied by 0.50 and rounded half up when the case is a rush, and 0 otherwise. The pre-discount base is the subtotal plus the rush surcharge. The `discount_cents` is that pre-discount base multiplied by the doctor's volume-tier percentage and rounded half up: a doctor with a `completed_case_count` of 0 through 4 earns 0%, one with 5 through 19 earns 5%, and one with 20 or more earns 10%. Subtracting the discount from the pre-discount base gives the taxable amount, and `tax_cents` is that taxable amount multiplied by 0.0825 and rounded half up. On the provisional invoice `sla_credit_cents` is always 0 (no shipment has happened yet). Finally, `total_cents` is the taxable amount plus tax minus the SLA credit. The provisional computation reads the doctor's `completed_case_count` as it stands at submit time, and the invoice's `kind` is `PROVISIONAL`.

### 3.4. Scheduling the Machines: Mill Jobs and Capability

Once a case is in `DESIGN`, each queued unit must be reserved on a machine before fabrication can begin. Scheduling a `MillJob` records the `fabrication_unit_id` being made, the `mill_machine_id` reserved, a `start_at` instant in ISO 8601 UTC, and a `duration_minutes` of at least 1; the server computes `end_at` as `start_at` advanced by `duration_minutes` and treats the occupation as the half-open interval that includes `start_at` and excludes `end_at`. A job is born in `SCHEDULED`. Although a unit is normally `QUEUED` when it is reserved, scheduling does not itself validate the targeted unit's current status — the only gates at scheduling time are the capability and double-booking checks below — so a job may be scheduled against a unit in any status. The machine's `capability` must equal the unit's material `fabrication_process`; a printer cannot take a milled unit and vice versa, and a mismatch is rejected with `ERR_MACHINE_CAPABILITY_MISMATCH` (HTTP 422). A new job's half-open interval must also not intersect any non-cancelled job already booked on the same machine; an overlap is rejected with `ERR_MACHINE_DOUBLE_BOOKED` (HTTP 409). Two intervals that merely touch end-to-end — one ending exactly as the next begins — do not intersect, because the interval excludes its own `end_at`.

Starting a scheduled job moves the job from `SCHEDULED` to `RUNNING` and, as a paired effect, advances its unit from `QUEUED` to `MILLING`. Starting requires the machine's `status` to be `AVAILABLE` and requires the request's `expected_machine_version` to match the machine's current `version` per §2.7; on a successful start the machine's `version` increments by one. Completing a running job moves it from `RUNNING` to `DONE` and advances its unit from `MILLING` to `MILLED`. A scheduled (not yet running) job may be cancelled to `CANCELLED`, which frees that machine's reserved half-open interval for re-scheduling. Before a case can leave `DESIGN` (or re-enter the loop), every queued unit on the case must already have a mill job that is `SCHEDULED` or `DONE`.

A machine itself can be taken offline: an `AVAILABLE` machine moves to `MAINTENANCE` only when no mill job on it is currently `RUNNING`, and a `MAINTENANCE` machine can be released back to `AVAILABLE`; each of those two transitions increments the machine's `version`. While a machine is in `MAINTENANCE` it fails the start precondition, since starts require an `AVAILABLE` machine.

### 3.5. Advancing Fabrication and the Try-In

With every queued unit scheduled, a lab technician advances the case from `DESIGN` to `FABRICATION`; the same advancement, applied to a case sitting in `REVISION`, lands it back in `DESIGN` so the design-then-fabrication walk repeats. Re-entry from `REVISION` requires every requeued unit to once again hold a fresh `SCHEDULED` or `DONE` mill job. The case from `FABRICATION` reaches `TRY_IN` once every billable fabrication unit on it is in `MILLED`. Each of these advancements increments the case's `version`.

The try-in verdict is the doctor's decision point, and it is guarded by the optimistic-concurrency check of §2.7: the request carries `verdict` and the mandatory `expected_case_version`, plus an optional `revise_restoration_ids` list naming the restorations to redo. Recording a verdict on a case in `TRY_IN` operates directly on the case's `MILLED` units: the `TRIED_IN` stage is collapsed into the verdict's own transition rather than persisted as a resting state, so a unit is never observably left in `TRIED_IN` — a `REVISE` carries each `MILLED` billable unit straight to `QUEUED` and an `ACCEPT` carries each straight to `PASSED`.

A verdict of `REVISE` sends the case from `TRY_IN` to `REVISION`. This is permitted only while `revision_count` is strictly below the maximum of three revisions; a `REVISE` recorded when `revision_count` already equals that maximum is rejected with `ERR_MAX_REVISIONS_EXCEEDED` (HTTP 422). When a revision is accepted, the server increments `revision_count` by one, sends each milled billable unit back to `QUEUED` for re-milling, creates a `ShadeRecord` with `matched` false for each restoration flagged in the verdict, and increments the case's `version`. Each created `ShadeRecord` records its `restoration_id`, the `shade_code` observed — set to that restoration's own `requested_shade` — and the `matched` flag. From `REVISION` the case re-enters `DESIGN` through the same fabrication-advancement action.

A verdict of `ACCEPT` ships the case from `TRY_IN` to `SHIPPED`. Acceptance requires three things: every billable unit on the case is in `PASSED` or `MILLED`, the `expected_case_version` matches per §2.7, and the case already has a route stop in `PLANNED`. On acceptance the server promotes every billable `MILLED` unit to `PASSED`, stamps `shipped_at` with the current logical clock, and evaluates the SLA — covered next — before finalizing the invoice, flipping the invoice to `ISSUED` and `IN_TRANSIT`, and incrementing the case's `version`.

### 3.6. Shipping, the SLA, the Final Invoice, and Credit

The service-level evaluation happens at ship. The case's `sla_breached` flag is set to true exactly when `shipped_at` is strictly later than `promised_ready_at`; shipping at precisely the promised instant is not a breach. The flag is fixed at ship time and thereafter drives credit issuance.

Acceptance also flips the case's invoice from `PROVISIONAL` to `FINAL` and reruns the total computation in its final variant. The final variant re-reads the doctor's `completed_case_count` at ship time, which may have crossed into a higher discount tier between submit and ship, so the discount can differ from the provisional figure even on identical line items. The final variant additionally computes `sla_credit_cents` as the subtotal multiplied by 0.20 and rounded half up when, and only when, the case's `sla_breached` flag is true; otherwise the SLA credit is 0. Every other step of the total — subtotal, rush surcharge at 0.50, discount at the doctor's tier, tax at 0.0825, each rounded half up in that fixed order — is identical to the provisional computation, and `total_cents` is once again the taxable amount plus tax minus the SLA credit, so the SLA credit is subtracted last.

If the case is breached at ship, the server also issues a credit. It creates a `CreditMemo` in `ISSUED` status whose `amount_cents` equals the invoice's `sla_credit_cents`, recording the related `case_id` and the FINAL `invoice_id`, and it adds that amount to the doctor's `account_credit_cents`. The doctor's account credit is a conserved ledger: issuing a memo adds its amount and voiding a memo later subtracts the identical amount, so the doctor's `account_credit_cents` always equals the sum of the `amount_cents` of that doctor's memos currently in `ISSUED`. The ship transition also sets the invoice's `billing_status` to `ISSUED` and its `delivery_status` to `IN_TRANSIT`.

The invoice carries two independent status dimensions that evolve in parallel. On the billing dimension `billing_status` runs `DRAFT` then `ISSUED` then `PAID`, or jumps to the terminal `VOID`. Marking an invoice paid moves it from `ISSUED` to `PAID` and requires the invoice to currently be `ISSUED`; the billing operator performs it and the invoice's `version` increments. On the delivery dimension `delivery_status` runs `PENDING` then `IN_TRANSIT` then `DELIVERED`, untouched by billing transitions. The `DRAFT`-to-`ISSUED` billing move and the `PENDING`-to-`IN_TRANSIT` delivery move both fire together at ship, the billing move conditioned on the invoice's `kind` having already flipped to `FINAL`.

### 3.7. Routing, Delivery, and Confirmation

Delivery is arranged on a courier route. Attaching a `RouteStop` records the `courier_route_id`, the `case_id` being delivered, a `window_start_at` instant in ISO 8601 UTC, and a `window_minutes` length of at least 1; the server computes `window_end_at` as `window_start_at` advanced by `window_minutes` and treats the service window as a closed interval that includes both ends. A new stop is born in `PLANNED`. Two capacity and spacing rules guard the attach. First, a route may not exceed its `max_stops`: attaching a stop when the route's `stop_count` already equals `max_stops` is rejected with `ERR_ROUTE_AT_CAPACITY` (HTTP 422). Second, the new stop's window, expanded on both the leading and trailing sides by the route's `buffer_minutes`, must not overlap the (unexpanded) window of any non-cancelled stop already on the same route; a conflict is rejected with `ERR_ROUTE_WINDOW_CONFLICT` (HTTP 409). These two checks are listed in business order but evaluated window-conflict first: when a stop both conflicts on its window and would put the route at capacity, the window-conflict check fires and `ERR_ROUTE_WINDOW_CONFLICT` is returned ahead of `ERR_ROUTE_AT_CAPACITY` (consistent with the temporal-before-capacity precedence of §2.9). A successful attach increments the route's `stop_count`.

A planned stop is marked `COMPLETED` when the on-site delivery actually happens. Confirming delivery of a case advances it from `SHIPPED` to `DELIVERED`, and it requires the case to have a route stop in `COMPLETED`. The confirmation has three coupled effects: the case's invoice `delivery_status` moves to `DELIVERED` (allowed only while the invoice's `billing_status` is `ISSUED` or `PAID`), the owning doctor's `completed_case_count` is recomputed upward to include this newly delivered case, and the case's `version` increments. The bump to `completed_case_count` is what can move a doctor into a higher discount tier for subsequent cases.

### 3.8. Cancellation and its Cascades

A doctor may cancel a case that has never shipped or been delivered. Cancelling a case that is still in `INTAKE` requires only that the case has no shipped or delivered history; it voids any `DRAFT` invoice on the case by setting that invoice's `billing_status` to `VOID` and increments the case's `version`. Cancelling a case that has reached `DESIGN` carries a heavier cascade: every `SCHEDULED` mill job belonging to the case's units is cancelled to `CANCELLED`, which frees each reserved machine interval for re-scheduling, the case's invoice `billing_status` is set to `VOID`, and the case's `version` increments. In both cancel paths the case lands in the terminal `CANCELLED` state, and the draft-to-void billing move requires the invoice to currently be `DRAFT`.

### 3.9. Warranty Remakes after Delivery

After a case is `DELIVERED`, the doctor may invoke the warranty against a unit that failed in the mouth. Opening a `RemakeRequest` records the `case_id`, the `fabrication_unit_id` reported as failed, and a `reason` of `SHADE_MISMATCH`, `POOR_FIT`, `FRACTURE`, or `CONTACT_OPEN`; the request is born in `OPEN`. The targeted unit must be one that is in `PASSED` on a `DELIVERED` case — a remake aimed at any unit that is not `PASSED`, or whose case is not `DELIVERED`, is rejected with `ERR_UNIT_NOT_WARRANTABLE` (HTTP 422).

The lab administrator adjudicates. Approving a remake request moves it from `OPEN` to `APPROVED`, transitions the targeted `PASSED` unit to the terminal `REMADE_OUT`, and spawns a brand-new replacement `FabricationUnit` in `QUEUED` with `is_billable` false and its `remade_from_unit_id` pointing at the unit it replaces; the replaced unit's `version` increments. Because the replacement unit is non-billable, the case's `billable_unit_count` and the invoice subtotal are conserved across the remake — warranty work is never re-billed. A unit's `is_billable` flag is fixed at creation and never mutated thereafter, which is what guarantees that conservation. Approving requires that the parent case is `DELIVERED` and that the request targets the `PASSED` unit and is still `OPEN`. Alternatively the administrator may deny a remake request, moving it from `OPEN` to `DENIED`.

Sometimes a within-SLA warranty re-ship makes an earlier SLA credit moot. In that case the billing operator voids the corresponding credit memo: the memo moves from `ISSUED` to `VOID`, and the doctor's `account_credit_cents` is decremented by exactly that memo's `amount_cents`, preserving the conservation invariant described in §3.6.

### 3.10. The Logical Clock

Every deadline, SLA comparison, and scheduling interval in the system reads a server-controlled logical clock rather than wall time. At startup the clock reads exactly `2026-01-01T00:00:00Z` and stays there until moved; it never falls back to real wall-clock time. An administrator-only test-driving capability sets the clock to a supplied `to_iso8601` instant, advancing or rewinding it, and the response reports the resulting `current_utc`. Because `scheduled_start_at`, `promised_ready_at`, and `shipped_at` are all stamped from this clock, driving the clock is how a test arranges a case to ship before or after its promised deadline.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a distinct resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including every state-machine transition and the logical-clock control — return a `200 OK` status code. The table below is a routing summary only; the request payloads, response bodies, and side effects for each operation live in the §3 narratives above.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock to an ISO 8601 UTC instant | LabAdmin |
| POST | `/doctors` | Register a prescribing doctor account | LabAdmin |
| GET | `/doctors/{id}` | Fetch a doctor with computed counters | LabAdmin, Billing, Doctor |
| GET | `/doctors` | List doctors | LabAdmin, Billing |
| GET | `/doctors/{id}/cases` | List a doctor's cases | LabAdmin, Billing, Doctor |
| POST | `/materials` | Create a material in the catalog | LabAdmin |
| GET | `/materials/{id}` | Fetch a material | LabAdmin, LabTech, Billing |
| GET | `/materials` | List materials | LabAdmin, LabTech, Billing |
| GET | `/materials/{id}/restorations` | List restorations using a material | LabAdmin, LabTech, Billing |
| POST | `/mill-machines` | Register a milling/printing machine | LabAdmin, Scheduler |
| GET | `/mill-machines/{id}` | Fetch a machine with version and status | LabAdmin, Scheduler, LabTech |
| GET | `/mill-machines/{id}/mill-jobs` | List mill jobs on a machine | LabAdmin, Scheduler, LabTech |
| POST | `/mill-machines/{id}/maintenance` | Take an AVAILABLE machine into MAINTENANCE | Scheduler, LabAdmin |
| POST | `/mill-machines/{id}/release` | Return a MAINTENANCE machine to AVAILABLE | Scheduler, LabAdmin |
| POST | `/courier-routes` | Create a courier route | LabAdmin, Scheduler |
| GET | `/courier-routes/{id}` | Fetch a courier route with stop_count | LabAdmin, Scheduler |
| GET | `/courier-routes/{id}/route-stops` | List stops on a route | LabAdmin, Scheduler |
| POST | `/cases` | Create a case in INTAKE | LabAdmin, LabTech, Doctor |
| GET | `/cases/{id}` | Fetch a case with status, SLA timestamps, version | LabAdmin, LabTech, Doctor, Billing, Scheduler |
| GET | `/cases` | List cases | LabAdmin, LabTech, Billing, Scheduler |
| POST | `/cases/{id}/restorations` | Add a restoration to an INTAKE case | LabAdmin, LabTech |
| GET | `/cases/{id}/restorations` | List restorations on a case | LabAdmin, LabTech, Doctor, Billing |
| GET | `/restorations/{id}` | Fetch a restoration with computed unit_price_cents | LabAdmin, LabTech, Doctor, Billing |
| GET | `/restorations/{id}/fabrication-units` | List fabrication units of a restoration | LabAdmin, LabTech, Doctor |
| GET | `/restorations/{id}/shade-records` | List shade records of a restoration | LabAdmin, LabTech, Doctor |
| GET | `/fabrication-units/{id}` | Fetch a fabrication unit | LabAdmin, LabTech, Doctor |
| GET | `/fabrication-units/{id}/remakes` | List replacement units spawned from a unit | LabAdmin, LabTech, Doctor |
| GET | `/fabrication-units/{id}/remake-requests` | List remake requests targeting a unit | LabAdmin, LabTech, Doctor |
| GET | `/fabrication-units/{id}/mill-jobs` | List mill jobs for a unit | LabAdmin, Scheduler, LabTech |
| POST | `/cases/{id}/submit` | Submit an INTAKE case to DESIGN | LabTech, LabAdmin |
| POST | `/cases/{id}/start-fabrication` | Advance DESIGN or REVISION toward FABRICATION | LabTech, LabAdmin |
| POST | `/cases/{id}/ready-tryin` | Advance FABRICATION to TRY_IN | LabTech, LabAdmin |
| POST | `/cases/{id}/tryin-verdict` | Record the doctor's try-in verdict (ACCEPT or REVISE) | Doctor |
| POST | `/cases/{id}/confirm-delivery` | Confirm delivery to reach DELIVERED | Scheduler, LabAdmin |
| POST | `/cases/{id}/cancel` | Cancel an INTAKE or DESIGN case | Doctor, LabAdmin |
| GET | `/cases/{id}/invoice` | Fetch the case's invoice — returned as a paginated `array` envelope (the single invoice, if any, as the sole element) rather than a bare object | LabAdmin, Billing, Doctor |
| GET | `/cases/{id}/credit-memos` | List SLA credit memos on a case | LabAdmin, Billing, Doctor |
| GET | `/cases/{id}/remake-requests` | List remake requests on a case | LabAdmin, LabTech, Doctor |
| GET | `/cases/{id}/route-stops` | List a case's route stops | LabAdmin, Scheduler, Doctor |
| POST | `/mill-jobs` | Schedule a mill/print job for a QUEUED unit | Scheduler, LabTech, LabAdmin |
| GET | `/mill-jobs/{id}` | Fetch a mill job | LabAdmin, Scheduler, LabTech |
| POST | `/mill-jobs/{id}/start` | Start a SCHEDULED job (unit to MILLING) | Scheduler, LabAdmin |
| POST | `/mill-jobs/{id}/complete` | Complete a RUNNING job (unit to MILLED) | Scheduler, LabAdmin |
| POST | `/mill-jobs/{id}/cancel` | Cancel a SCHEDULED job, freeing the interval | Scheduler, LabAdmin |
| POST | `/route-stops` | Attach a stop to a courier route | Scheduler, LabAdmin |
| GET | `/route-stops/{id}` | Fetch a route stop | LabAdmin, Scheduler |
| POST | `/route-stops/{id}/complete` | Mark a PLANNED stop COMPLETED | Scheduler, LabAdmin |
| GET | `/invoices/{id}` | Fetch an invoice with all amounts and both status dimensions | LabAdmin, Billing, Doctor |
| GET | `/invoices/{id}/credit-memos` | List credit memos applied against an invoice | LabAdmin, Billing, Doctor |
| POST | `/invoices/{id}/pay` | Mark an ISSUED invoice PAID | Billing, LabAdmin |
| POST | `/cases/{id}/remake-requests` | Open a warranty remake request | Doctor, LabAdmin |
| GET | `/remake-requests/{id}` | Fetch a remake request | LabAdmin, LabTech, Doctor |
| POST | `/remake-requests/{id}/approve` | Approve a remake, spawning a non-billable unit | LabAdmin |
| POST | `/remake-requests/{id}/deny` | Deny a remake request | LabAdmin |
| GET | `/credit-memos/{id}` | Fetch a credit memo | LabAdmin, Billing, Doctor |
| POST | `/credit-memos/{id}/void` | Void an SLA credit memo and decrement account credit | Billing, LabAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_CASE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_CASE_VERSION` | 412 |
| `ERR_STALE_MACHINE_VERSION` | 412 |
| `ERR_MATERIAL_INACTIVE` | 422 |
| `ERR_MACHINE_CAPABILITY_MISMATCH` | 422 |
| `ERR_EMPTY_FABRICATION` | 422 |
| `ERR_MAX_REVISIONS_EXCEEDED` | 422 |
| `ERR_MACHINE_DOUBLE_BOOKED` | 409 |
| `ERR_ROUTE_WINDOW_CONFLICT` | 409 |
| `ERR_ROUTE_AT_CAPACITY` | 422 |
| `ERR_UNIT_NOT_WARRANTABLE` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_VALIDATION` | 422 |
| `ERR_PAGINATION_INVALID` | 400 |
