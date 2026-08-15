# Aircraft Completion API — Product Requirements Document

## 1. Introduction

An aircraft completion center lives and dies by two promises: the airplane leaves on the contractually guaranteed date, and it leaves in a condition that survives regulatory scrutiny. Between those two promises sits a web of interdependent work — livery design approval, strip-versus-scuff decisions on the existing paint, corrosion findings that turn into chargeable discovery work, hangar bays and paint booths that must be scheduled without overlap, interior soft goods that cannot fly without burn certification, a weight-and-balance envelope that the customer must formally acknowledge when exceeded, and a delivery-date guarantee backed by a penalty the finance team must be able to project and settle precisely.

This document specifies the Aircraft Completion API, the system of record for that workflow. It governs a refurbishment engagement — the **Refurb Program** — from initial quote through booking, induction, surface review, production work, inspection, and delivery. Along the way it orchestrates customer-facing approvals (paint schemes, discovery estimates, change orders, invoices) under a strict segregation-of-duties model in which the shop floor drafts and the customer approves, and in which the person who prepares a weight-and-balance record may never be the person who signs it off. Because the commercial basis of every approval is a running set of program totals and dates, all customer-side approvals are protected by optimistic concurrency control so that no one ever approves against figures they have not actually seen.

Scheduling, billing, and penalty math are deliberately dual-variant throughout: material and weight estimates exist in provisional and final form, booth time is billed on a scheduled-versus-actual basis, and the delivery penalty exists both as a forward-looking projection and as a fixed settlement figure captured at final invoicing. The result is a system where every dollar and every day on the contract can be traced back to the event that created it.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. Requests missing either header, or presenting a role the system does not recognize, are rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Access to specific operations is further restricted by role; an attempt to perform an action outside of the caller's designated role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes seven distinct roles:

- **`CenterAdmin`** — the completion-center administrator: master data (customers, aircraft, hangar bays, paint booths), credit-status management, delay confirmation, and the logical clock. When `X-User-Role` is `CenterAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **`ProgramManager`** — the center-side program manager: programs, scheduling (hangar slots and booth bookings), change-order drafting, discovery estimates, and delay reporting. When `X-User-Role` is `ProgramManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **`DesignLead`** — the livery designer responsible for paint scheme drafting and submission. When `X-User-Role` is `DesignLead`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **`ShopTechnician`** — the shop floor technician: surface assessment, discovery logging and completion, soft-goods lots and burn tests, weight record preparation, and booth completion. When `X-User-Role` is `ShopTechnician`, `X-User-ID` is an opaque operator identifier; the server records it (as `prepared_by_user_id` on each Weight Balance Record the technician creates) but does not otherwise compare it to any entity's `id`.
- **`QualityInspector`** — the quality inspector: inspections and weight-record sign-off. When `X-User-Role` is `QualityInspector`, `X-User-ID` is an opaque operator identifier, used only to enforce the segregation-of-duties rule that the signer of a Weight Balance Record must differ from its `prepared_by_user_id`.
- **`FinanceClerk`** — the billing clerk: invoice drafting, issuance, and voiding. When `X-User-Role` is `FinanceClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **`CustomerRep`** — the customer representative, acting on behalf of the Customer entity: all approval decisions and invoice payment. When `X-User-Role` is `CustomerRep`, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a Customer compare the program's `customer_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Burn tests of a soft-goods lot are the one deliberate exception: they are ordered by their per-lot `test_sequence`, which is itself monotone and creation-ordered.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All temporal rules in the system — slot windows, deferral cutoffs, penalty accrual, invoice issuance timestamps — are evaluated against a single server-side **logical clock**, never against the wall clock. Before any call is made, the logical clock reads exactly `2026-08-01T00:00:00Z` (the startup default). A `CenterAdmin` may advance it by setting the clock to a supplied `to_iso8601` instant; the capability exists so that long-running refurbishment timelines can be exercised deterministically. Fields described as dates (for example `contractual_delivery_date`, `committed_delivery_date`, `actual_delivery_date`) are interpreted as UTC calendar days under this clock.

### 2.5. Common Resource Properties and the Program Version Counter

All primary resources carry a standard set of system-managed fields, alongside each entity's own attributes and its lifecycle `status`:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`), set when the resource is first created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp refreshed on any change to the resource's properties.
- **`version` (integer):** a system-managed integer that increments with every modification to the resource.

One entity is deliberately exempt: a **Burn Test** is an append-only record and carries only `id` and `created_at` — both `updated_at` and `version` are absent, because a recorded test result is never modified after the fact.

The Refurb Program's `version` plays a special role. It is the single serialization point for the entire engagement: every mutation of the program itself, and every mutation of one of its children that propagates into a program-level total or date, increments it by exactly one. A customer-side approval against a program is therefore always made against a specific observed version, and the optimistic concurrency rules of §2.6 hang off this counter.

### 2.6. Optimistic Concurrency Control on Customer Approvals

Three write operations — and only these three — are guarded by optimistic concurrency control against the Refurb Program's `version`:

1. Customer approval of a Paint Scheme.
2. Customer approval of a Change Order.
3. Customer approval of a Discovery Item.

Each of these requests must carry `expected_program_version` as a non-optional input field, set to the program `version` the client last observed. If the program's current `version` no longer matches — because another writer has advanced it since the client last read the program — the request is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412). The rule exists because each of these approvals re-baselines commercial or technical ground truth: scheme approval supersedes the previously approved scheme and re-pins `approved_scheme_id`; change-order approval mutates `total_contract_value_cents` and may shift `committed_delivery_date`; discovery approval debits `discovery_cost_total_cents`. Approving any of these from a stale program view would silently overwrite work or figures the customer never saw. Endpoints not listed above do not take a version field.

### 2.7. Hierarchical Consistency and Cascading Side Effects

The Refurb Program is the aggregate root of the engagement, and consistency flows in both directions. Downward: when a program is cancelled, its dependent hangar slots are cancelled with it; when a program is delivered, its active hangar slots are released and the aircraft is returned to service. Upward: when a child record mutates a program-level figure — a change-order approval moving `total_contract_value_cents`, a delay confirmation moving `committed_delivery_date`, a discovery approval moving `discovery_cost_total_cents`, an invoice payment moving `billed_total_cents` — the program's derived fields are recomputed immediately, its `version` increments, and every DRAFT invoice of the program regenerates its computed line items (bumping each such invoice's own `version` and `updated_at`). All mutations and their cascades are atomic within the request: the system never persists a partial application.

Two compensating invariants are worth naming explicitly. First, book-then-cancel on a hangar slot leaves the bay's occupancy set exactly as it was — cancel restores availability rather than degrading it. Second, issue-then-void on an invoice nets to zero: voiding an ISSUED invoice drops it out of `billed_total_cents` precisely, leaving the total unchanged from before issuance.

### 2.8. Path Validation and Referential Integrity

When an endpoint path contains resource identifiers, the system validates the existence of each identifier in sequential, left-to-right order, rejecting with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource.

Request bodies carry foreign keys, and these are checked for existence and cross-consistency with `ERR_REFERENTIAL_INTEGRITY` (HTTP 422) on failure. A program's `customer_id` must equal the owning aircraft's `customer_id`. A discovery item's `assessment_id`, when present, must reference an assessment of the same program. A weight record's `scheme_id` must equal the program's currently approved scheme. A change order of kind `WEIGHT_ACK` must name an `acknowledges_weight_record_id` belonging to the same program. Dangling or cross-wired references are never accepted.

### 2.9. Monetary Values, Rounding, and Precision

All monetary values in the system are integer cents. Where a computed value can be fractional — the penalty cap, per-line invoice amounts, the booth overrun term, the discovery handling surcharge — the value is rounded half-up to integer cents, and the rounding point is pinned by the relevant calculation rather than left to convention. Weight deltas are carried to exactly 1 decimal place, rounded half-up, and any gate that compares a delta against a limit compares the rounded stored value. Material quantities are integer gallons, each component rounded up to a whole gallon before summation.

### 2.10. Validation Priority Ordering

Incoming requests are validated in a fixed priority order, so that the error a caller receives is always the highest-priority failure present rather than an arbitrary one. The order is:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is a declared role (`ERR_UNAUTHENTICATED`, 401).
2. **Authorization** — the role is permitted on the endpoint (`ERR_FORBIDDEN_ROLE`, 403).
3. **Body well-formedness** — the request body parses and every required input field is present and type/enum-valid (`ERR_INVALID_REQUEST`, 400).
4. **Path existence** — path resources exist, checked left-to-right (`ERR_NOT_FOUND`, 404).
5. **Ownership** — on customer-side actions, the entity-backed `CustomerRep` identity matches the program's `customer_id` (`ERR_FORBIDDEN_OWNERSHIP`, 403).
6. **Optimistic concurrency** — on the three OCC-guarded approvals, `expected_program_version` matches the program's current `version` (`ERR_STALE_PROGRAM_VERSION`, 412).
7. **State validity** — the entity is in a valid from-state for the requested transition, including terminal lockdown (`ERR_INVALID_STATE`, 409), and entity-specific state gates such as aircraft availability (`ERR_AIRCRAFT_BUSY`, 409), bay availability (`ERR_BAY_INACTIVE`, 409), and scheme phase (`ERR_SCHEME_PHASE_TOO_ADVANCED`, 409).
8. **Safety gates** — corrosion discovery, deferral safety, and the three-step delivery gate (`ERR_CORROSION_DISCOVERY_REQUIRED`, `ERR_SAFETY_DEFERRAL_FORBIDDEN`, `ERR_INSPECTION_OUTSTANDING`, `ERR_CERT_REQUIRED`, `ERR_WEIGHT_NOT_SIGNED_OFF`, all 409).
9. **Temporal rules** — slot windows and overlaps, booth buffer gaps, deferral cutoff (`ERR_SLOT_IN_PAST`, `ERR_SLOT_OVERLAP`, `ERR_BOOTH_BUFFER_VIOLATION`, `ERR_DELIVERY_WINDOW_PASSED`, all 409).
10. **Referential integrity** — body foreign keys exist and are cross-consistent (`ERR_REFERENTIAL_INTEGRITY`, 422).
11. **Business constraints** — defer reason, weight delta, segregation of duties, final-inspection prerequisite, advance and invoice gates (`ERR_DEFER_REASON_REQUIRED` 422, `ERR_WEIGHT_DELTA_EXCEEDED` 409, `ERR_SEGREGATION_OF_DUTIES` 403, `ERR_FINAL_INSPECTION_PREREQUISITE` 409, and the gate errors `ERR_ASSESSMENT_REQUIRED`, `ERR_SCHEME_NOT_APPROVED`, `ERR_BOOTH_BOOKING_REQUIRED`, `ERR_DISCOVERY_ITEMS_OPEN`, `ERR_INVOICE_KIND_PHASE`, `ERR_INVOICE_ALREADY_ISSUED`, `ERR_ASSESSMENT_LOCKED`, all 409).
12. **Fiscal rules** — credit standing (`ERR_CREDIT_HOLD`, 402) and settlement status (`ERR_INVOICE_NOT_SETTLED`, 409).

## 3. Business Logic & Workflows

### 3.1. Customers, Aircraft, and the Shape of an Engagement

A `CenterAdmin` registers each operator as a **Customer** with a `name` and `contact_email`; every customer begins life with `credit_status` of `GOOD_STANDING`. Credit is not decorative: an administrator may move a customer to `CREDIT_HOLD` at any time, and while a customer is on hold, three things are refused — booking a new hangar slot for one of their programs, advancing a program from `QUOTED` to `BOOKED`, and advancing a program from `SURFACE_REVIEW` to `IN_WORK` — each rejected with `ERR_CREDIT_HOLD` (HTTP 402).

Aircraft are registered against a customer with a `tail_number`, a `model`, and a `max_delta_lbs` value expressing the largest absolute weight delta, in pounds, that sign-off may accept without a formal customer acknowledgment; the gate is strict — a delta whose absolute value exceeds `max_delta_lbs` requires the acknowledgment, while one exactly equal to it does not. An aircraft begins `IN_SERVICE`, moves to `IN_REFURB` automatically when one of its programs is inducted, returns to `RETURNED` when that program is delivered (or cancelled after induction), and may be inducted again later — the cycle is deliberate, since airframes come back for refurbishment more than once. An aircraft already `IN_REFURB` cannot start another program; the attempt is rejected with `ERR_AIRCRAFT_BUSY`.

A `ProgramManager` opens an engagement by creating a **Refurb Program** — the quote — naming the `aircraft_id` and `customer_id`, and establishing the commercial terms: `base_price_cents`, the `daily_penalty_rate_cents` at which late delivery accrues, the `penalty_cap_pct` expressing the penalty ceiling as a fraction of the total contract value, and the `contractual_delivery_date`. A new program starts in `QUOTED` with `committed_delivery_date` equal to the contractual date, all totals at zero, `rework_cycles` at zero, and no approved scheme. From `QUOTED`, `BOOKED`, or `INDUCTED` a program may be cancelled outright; cancellation cascades downward, cancelling every `BOOKED` or `ACTIVE` hangar slot of the program (from `QUOTED`, only `BOOKED` slots exist to cancel), and cancelling from `INDUCTED` additionally returns the aircraft to `RETURNED`.

### 3.2. Booking the Hangar and the Paint Booth

Scheduling happens on two kinds of resources. A **Hangar Bay** is registered by a `CenterAdmin` with a `name` and a `daily_rate_cents` stall fee, and begins `ACTIVE`. A bay may be deactivated — moved from `ACTIVE` to `INACTIVE` — but only when it holds no `BOOKED` or `ACTIVE` slots; an `INACTIVE` bay rejects new slot bookings, and both directions of this rule surface as `ERR_BAY_INACTIVE`.

A `ProgramManager` books a **Hangar Slot** by naming the `bay_id`, the `program_id`, and a `start_at`/`end_at` window, while the program is still `QUOTED` or `BOOKED`. Slot windows are half-open intervals: the start is inclusive, the end exclusive, so two slots on the same bay where one ends exactly when the other begins are legal adjacency. A true overlap — any existing `BOOKED` or `ACTIVE` slot on the same bay whose interval intersects the new one under half-open semantics — is rejected with `ERR_SLOT_OVERLAP`. A slot whose `start_at` lies before the logical clock, or whose `start_at` is not strictly before its `end_at`, is rejected with `ERR_SLOT_IN_PAST`. A booked slot is activated once the logical clock falls inside its window and the program is `BOOKED` or `INDUCTED` — attempting activation when the clock has already passed `end_at` yields `ERR_SLOT_IN_PAST`, and too-early activation yields `ERR_INVALID_STATE`. An active slot is released when the aircraft physically vacates, and a still-booked slot may simply be cancelled.

The **Paint Booth** follows a different rhythm. A booth is registered with a `name`, an `hourly_rate_cents`, and a `cure_buffer_hours` value — the mandatory empty gap for cure and cleanup that must follow every booking before the next one may begin. A `ProgramManager` books a **Booth Booking** with `booth_id`, `program_id`, and a spray window from `start_at` to `end_at`, while the program is in any phase from `QUOTED` through `IN_WORK`. The buffer rule is symmetric: a new booking is rejected with `ERR_BOOTH_BUFFER_VIOLATION` unless, for every existing `BOOKED` or `COMPLETED` booking on that booth, the new booking starts at or after the existing booking's end plus the buffer, or the new booking's end plus the buffer falls at or before the existing booking's start. A gap exactly equal to the buffer is acceptable; anything less is not.

Every booking carries two fee figures. At booking time, `scheduled_fee_cents` is computed as the scheduled hours — the whole-hour difference between `end_at` and `start_at` — multiplied by the booth's hourly rate. When a `ShopTechnician` later marks the spray work complete by supplying `actual_hours` (permitted only while the program is `IN_WORK`), the booking moves to `COMPLETED` and `actual_fee_cents` is computed: if actual occupancy did not exceed the scheduled hours, the fee is simply the actual hours times the rate; otherwise the fee is the scheduled hours times the rate plus the overrun hours times the rate times a 1.25 premium multiplier, with the overrun term rounded half-up to integer cents. Completion of a booth booking increments the program's `version` by one. A booking may instead be cancelled, which frees both the window and its buffer.

### 3.3. Livery Design: The Paint Scheme Cycle

The visual identity of the finished aircraft is the **Paint Scheme**, drafted by a `DesignLead` against a program with a `drawing_ref`, the total `painted_area_sqft`, the number of color coats in `coat_count`, and optionally `stripe_pct` — the fraction of the area receiving accent stripe paint, defaulting to zero. A scheme begins in `DRAFT`; the design lead submits it, moving it to `SUBMITTED`, and the customer's representative then decides.

Approval is the consequential act. With the scheme approved, the program's computed `material_estimate_gallons` and `material_estimate_cost_cents` come to life from the pinned scheme and the current assessment decision — both read zero until a scheme reaches `APPROVED` (the tiered math itself lives with the surface decision in §3.4). The `CustomerRep` approves a `SUBMITTED` scheme by presenting `expected_program_version`; the approval is rejected with `ERR_STALE_PROGRAM_VERSION` if that expectation no longer matches the program's current `version` (per §2.6), with `ERR_FORBIDDEN_OWNERSHIP` if the caller is not the program's customer, and with `ERR_SCHEME_PHASE_TOO_ADVANCED` if the program has already moved past `SURFACE_REVIEW` — approval is only possible while the program is `QUOTED`, `BOOKED`, `INDUCTED`, or `SURFACE_REVIEW`. On approval, any previously `APPROVED` scheme of the same program is moved to `SUPERSEDED` with its `superseded_by_id` pointing at the newly approved scheme — a compensating pair that keeps the count of approved schemes per program at exactly one — and the program's `approved_scheme_id` is pinned to the new scheme. The pin is a version pin: everything downstream (material estimates, film weight) reads the scheme that was approved, and a later superseding approval re-baselines that ground truth. The approval increments the program's `version` by one.

Rejection is the lighter path: the customer moves the scheme to `REJECTED`, and the design lead may return it to `DRAFT` for revision, closing the cycle.

### 3.4. Surface Assessment: Strip or Scuff, and What the Metal Tells Us

Once a program reaches `INDUCTED`, a `ShopTechnician` performs the **Surface Assessment**. Creating a new assessment for a program automatically supersedes whatever previous assessment existed — whether it was still `PENDING` or already `DECIDED` — so at most one assessment is ever current. The technician then records the decision: `decision` is either `STRIP` (take the airframe to bare metal) or `SCUFF` (sand and overcoat), and `corrosion_severity` is one of `NONE`, `LIGHT`, or `HEAVY`, with an optional `findings_note` for the corrosion narrative. Recording the decision moves the assessment from `PENDING` to `DECIDED` and is permitted while the program is `INDUCTED` or `SURFACE_REVIEW`.

While the program is in `SURFACE_REVIEW`, a `DECIDED` assessment may be amended — the same decision and severity fields are overwritten and the assessment's `revision` counter is bumped by one. Amending is a self-loop that keeps the assessment in `DECIDED`; it is refused with `ERR_ASSESSMENT_LOCKED` once the program has left `SURFACE_REVIEW`. The decision matters far beyond the assessment itself: a `SCUFF` decision scales both the paint material estimate and the film weight by a factor of 0.85, so flipping `STRIP` to `SCUFF` re-baselines downstream math.

The strip-versus-scuff choice directly sizes the paint order. The material estimate works from the program's pinned approved scheme and the latest decided assessment — if no assessment is `DECIDED` yet, the prep mode defaults to `STRIP`. The main-color gallons are the scheme's `painted_area_sqft` multiplied by its `coat_count` and divided by a coverage of 350 square feet per gallon; under a `SCUFF` decision this raw figure is scaled by 0.85 before rounding, reflecting that a scuff-and-spray lays less film than a full strip — and the result is rounded up to a whole gallon. Accent gallons are the painted area multiplied by the scheme's `stripe_pct` and divided by an accent coverage of 500 square feet per gallon, again rounded up. The total gallonage is the sum of the two components, and that total is billed at a single average tier rate — not marginally: a total of at most 20 gallons bills every gallon at 18,500 cents; 21 through 60 gallons bills every gallon at 17,250 cents; beyond 60 gallons every gallon bills at 16,000 cents. The resulting cost is an exact integer number of cents. Because both the pinned scheme and the assessment decision feed it, the estimate is re-evaluated whenever either changes.

Corrosion findings carry a safety obligation. If the current assessment records `corrosion_severity` of `HEAVY`, the program may not advance from `SURFACE_REVIEW` to `IN_WORK` until at least one Discovery Item linked to that assessment exists; attempting the advance without one is rejected with `ERR_CORROSION_DISCOVERY_REQUIRED`.

### 3.5. Induction, the Advance Chain, and the Program Phase Machine

The program's phase machine is the spine of the engagement, walked by the `ProgramManager` through explicit advances, each naming a `to_phase`. Each successful advance increments the program's `version` by one, and several advances carry cascades or gates worth stating in one place.

From `QUOTED` to `BOOKED`: at least one hangar slot for the program must exist in `BOOKED` status (`ERR_INVALID_STATE` otherwise), and the customer must be in `GOOD_STANDING` (`ERR_CREDIT_HOLD`).

From `BOOKED` to `INDUCTED`: at least one hangar slot must be `ACTIVE` with a window covering the logical clock (`ERR_INVALID_STATE`). Induction is the moment the aircraft physically enters the center's custody, so the aircraft cascades from `IN_SERVICE` or `RETURNED` to `IN_REFURB`.

From `INDUCTED` to `SURFACE_REVIEW`: a surface assessment for the program must exist in `PENDING` or `DECIDED` status (`ERR_ASSESSMENT_REQUIRED`).

From `SURFACE_REVIEW` to `IN_WORK`: four gates. The current assessment must be `DECIDED` (`ERR_ASSESSMENT_REQUIRED`); the heavy-corrosion rule of §3.4 must be satisfied (`ERR_CORROSION_DISCOVERY_REQUIRED`); a paint scheme must be `APPROVED` (`ERR_SCHEME_NOT_APPROVED`); at least one booth booking must be `BOOKED` (`ERR_BOOTH_BOOKING_REQUIRED`); and the customer must again be in `GOOD_STANDING` (`ERR_CREDIT_HOLD`).

From `IN_WORK` to `IN_INSPECTION`: every discovery item of the program must be in a terminal state — `COMPLETED`, `REJECTED`, or `DEFERRED` (`ERR_DISCOVERY_ITEMS_OPEN`), and at least one booth booking must be `COMPLETED` (`ERR_BOOTH_BOOKING_REQUIRED`).

From `IN_INSPECTION` to `READY_FOR_DELIVERY`: a pinned three-step safety gate, evaluated in order — inspection first, then certification, then weight. Step one: no `FAILED` quality inspection may lack a later `PASSED` inspection of the same `inspection_type`, and a `FINAL` inspection must have passed (`ERR_INSPECTION_OUTSTANDING`). Step two: every soft-goods lot of the program must be `CERTIFIED` — a lot in any other state, including `CERT_QUARANTINED`, blocks the gate (`ERR_CERT_REQUIRED`). Step three: a weight-and-balance record with `variant` of `FINAL` and status `SIGNED_OFF` must exist whose absolute rounded `delta_lbs` is at most the aircraft's `max_delta_lbs`, or else an `APPROVED` change order of kind `WEIGHT_ACK` acknowledging that record must exist (`ERR_WEIGHT_NOT_SIGNED_OFF`).

From `READY_FOR_DELIVERY` to `DELIVERED`: the fiscal gate — the program's `FINAL` invoice must exist in `PAID` status (`ERR_INVOICE_NOT_SETTLED`). Delivery stamps `actual_delivery_date` from the logical clock, recomputes and persists `penalty_final_cents` via the settlement variant of the delivery penalty (§3.10), releases every `ACTIVE` hangar slot of the program, and returns the aircraft to `RETURNED`.

One transition walks backwards. When a quality inspection records a `FAIL` result while the program is `IN_INSPECTION`, the program automatically reverts from `IN_INSPECTION` to `IN_WORK`, its `rework_cycles` increments by one, and the program must earn its way back through the inspection gate after rework.

### 3.6. Discovery Work and the Customer's Approval Chain

Refurbishment always finds things. A `ShopTechnician` logs a **Discovery Item** against a program — with a `description`, optionally an `assessment_id` tying it to the assessment that surfaced it, and optionally `safety_linked` (defaulting to `false`) — while the program is `INDUCTED`, `SURFACE_REVIEW`, `IN_WORK`, or `IN_INSPECTION`. Items also arise automatically: a failed inspection with two or more major defects causes the system to create an item with `source` of `INSPECTION_AUTO`, `safety_linked` forced to `true`, and status `OPEN`. Manually logged items carry `source` of `MANUAL`.

An `OPEN` item is priced by the `ProgramManager`, who attaches `est_cost_cents` and `est_hours`, moving it to `ESTIMATED`. The customer then chooses among three outcomes. Approval — presenting `expected_program_version` under the OCC rule of §2.6, with `ERR_FORBIDDEN_OWNERSHIP` guarding identity — moves the item to `APPROVED` and debits the program: `discovery_cost_total_cents` increases by the item's `est_cost_cents`, the program's `version` increments, and because that program total changed, every DRAFT invoice of the program regenerates its computed lines and bumps its own `version` and `updated_at`. Rejection moves the item to `REJECTED`, terminal and contribution-free. Deferral moves the item to `DEFERRED` but is fenced by three rules: a `safety_linked` item may never be deferred (`ERR_SAFETY_DEFERRAL_FORBIDDEN`); deferral is only possible while the logical clock date is on or before the program's `committed_delivery_date` (`ERR_DELIVERY_WINDOW_PASSED`); and the request must carry a non-empty `defer_reason` (`ERR_DEFER_REASON_REQUIRED`, HTTP 422).

An approved item is eventually worked. The technician completes it by recording `actual_cost_cents`, moving it to `COMPLETED`; the program's `discovery_cost_total_cents` then adjusts by the difference between actual and estimate — up or down — the program version increments, and DRAFT invoices regenerate their lines again. In the program's running `discovery_cost_total_cents`, `APPROVED` items contribute their `est_cost_cents`, `COMPLETED` items contribute their `actual_cost_cents`, and items in `OPEN`, `ESTIMATED`, `REJECTED`, or `DEFERRED` contribute nothing.

### 3.7. Change Orders and the Negotiation Cycle

Scope changes travel through the **Change Order**. A `ProgramManager` drafts one against a program with a `delta_price_cents` (a signed price delta), a `description`, and optionally a `kind` (defaulting to `SCOPE`), a `delta_days` delivery shift (defaulting to zero), and an `acknowledges_weight_record_id`. The `kind` of `WEIGHT_ACK` exists for exactly one purpose — customer acknowledgment of an over-limit weight delta — and requires `acknowledges_weight_record_id` referencing a weight record of the same program (`ERR_REFERENTIAL_INTEGRITY` otherwise). A new order begins `DRAFT` with `negotiation_round` at one.

The manager submits the order — permitted unless the program is `DELIVERED` or `CANCELLED` — moving it to `SUBMITTED`. The customer then has three answers. Rejection ends the matter at `REJECTED`. A counter, carrying a `counter_note`, moves the order to `COUNTERED`, from which the manager revises it back to `DRAFT`; each revise bumps `negotiation_round` by one and overwrites `delta_price_cents`, `delta_days`, and `description` from the revision payload. Approval is the heavy path: the `CustomerRep` presents `expected_program_version` (OCC per §2.6, `ERR_STALE_PROGRAM_VERSION` on mismatch) under the usual ownership check. On approval the order moves to `APPROVED`, and a three-link cascade fires in order. Link one: the program's `total_contract_value_cents` — defined as `base_price_cents` plus the signed `delta_price_cents` of every `APPROVED` change order — absorbs this order's delta, and if `delta_days` is positive the `committed_delivery_date` shifts out by that many days; the program version increments. Link two: that same positive `delta_days` causes the system to create a Delay Event with `source` of `CHANGE_ORDER`, category `CUSTOMER_CAUSED`, `impact_days` equal to the `delta_days`, and status `CONFIRMED` — such events are born confirmed and never pass through `REPORTED`. Link three: the confirmation of that event triggers recomputation of the program's `projected_penalty_cents` and regeneration of every DRAFT invoice's lines, including the penalty credit line on the `FINAL` kind.

### 3.8. Interior Soft Goods and Burn Certification

Every interior soft-goods lot — seat covers, carpets, sidewalls — must hold burn certification before the aircraft may be delivered. A `ShopTechnician` registers a **Soft Good Lot** against a program (in any phase other than `DELIVERED` or `CANCELLED`) with a `description`, a `material` designation, a `quantity`, and an `estimated_weight_lbs` catalog weight that feeds the provisional weight calculation. A lot begins `UNCERTIFIED` with `fail_count` zero.

Certification is driven entirely by recorded **Burn Tests**. The technician records a test against a lot by its `lot_id`, with a `test_method` — one of `VERTICAL_12S`, `VERTICAL_60S`, or `HORIZONTAL_25` — a `result` of `PASS` or `FAIL`, and the `lab_name` of the accredited laboratory. Each test receives the next per-lot `test_sequence`, a monotone sequence starting at one that fixes the ordering of a lot's test history. The first test recorded moves the lot from `UNCERTIFIED` to `IN_TEST`. From there, each new test is judged as the latest: a `PASS` moves the lot to `CERTIFIED`; a `FAIL` increments `fail_count` and moves the lot to `CERT_FAILED` when the resulting count is below three, or to `CERT_QUARANTINED` — terminal — when the count reaches three. A `CERT_FAILED` lot returns to `IN_TEST` when a further test is recorded, so the retest cycle is bounded but forgiving: a lot carrying two recorded failures that then passes becomes `CERTIFIED` with those two fails permanently on record — fails never reset. Tests may not be recorded against lots already `CERTIFIED` or `CERT_QUARANTINED`.

### 3.9. Weight & Balance: Provisional, Final, and the Sign-Off Gate

Paint and interior work change what the aircraft weighs, and the change must be documented twice. A **Weight Balance Record** is prepared by a `ShopTechnician` against a program, naming the `scheme_id` — which must equal the program's currently pinned `approved_scheme_id` at creation time (`ERR_REFERENTIAL_INTEGRITY` otherwise) — a `variant` of `PROVISIONAL` or `FINAL`, and the `removal_weight_lbs` and `installed_weight_lbs` figures (estimates for a provisional record, scale weights for a final one). The server stamps the preparer into `prepared_by_user_id` from the acting `X-User-ID`.

Two values are computed at creation and stored. The paint film weight `film_lbs` is the pinned scheme's `painted_area_sqft` multiplied by its `coat_count`, multiplied by a film factor, multiplied by one plus the scheme's `stripe_pct`; the film factor is 0.006 pounds per square foot per coat for a `PROVISIONAL` record and 0.0058 for a `FINAL` record, and when the program's current decided assessment is `SCUFF` the whole film figure is scaled by 0.85. The `delta_lbs` is then the installed weight minus the removal weight plus the film weight, rounded half-up to one decimal place — and it is this rounded, stored value that every downstream gate compares.

A new record begins in `PREPARED` status. Sign-off is performed by a `QualityInspector` and is fenced by two rules. First, segregation of duties: the signing `X-User-ID` must differ from the record's `prepared_by_user_id` — a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Second, the weight gate: the absolute value of the rounded `delta_lbs` must be at most the aircraft's `max_delta_lbs`, unless an `APPROVED` change order of kind `WEIGHT_ACK` exists whose `acknowledges_weight_record_id` is this record — otherwise the sign-off is rejected with `ERR_WEIGHT_DELTA_EXCEEDED`. When a record is signed off, any previously `SIGNED_OFF` record of the same program and the same `variant` is automatically superseded, keeping the count of signed-off records per program and variant at most one. Only `FINAL` records participate in the delivery gate of §3.5; the provisional variant exists for planning.

### 3.10. Delays, the Committed Date, and the Delivery Penalty

Schedule truth is maintained through **Delay Events**. A `ProgramManager` reports an event against a program (in any non-terminal phase) with a `category` — `CUSTOMER_CAUSED`, `CENTER_CAUSED`, or `FORCE_MAJEURE` — an `impact_days` count of calendar days, and a free-text `reason`. A reported event starts in `REPORTED` with `source` of `MANUAL` and receives the next per-program `event_seq`, a monotone sequence that fixes chronological replay order. A `CenterAdmin` confirms an event, or the customer disputes it; both `CONFIRMED` and `DISPUTED` are terminal.

Confirmation is where the date moves. The program's `committed_delivery_date` is defined as the `contractual_delivery_date` plus the sum of `impact_days` over all confirmed events whose category is excusable — `CUSTOMER_CAUSED` or `FORCE_MAJEURE` — applied cumulatively in ascending `event_seq` order. `CENTER_CAUSED` events never shift the date, in either direction; `REPORTED` and `DISPUTED` events contribute nothing. Confirming an excusable event therefore moves the committed date out by its `impact_days`, increments the program's version, recomputes the projected penalty, and regenerates DRAFT invoice lines. (Recall from §3.7 that change-order approvals manufacture their own already-confirmed `CUSTOMER_CAUSED` events, so a customer-caused schedule slip is indistinguishable in the date math whether it arrived by negotiation or by report.)

The delivery penalty exists in two variants sharing one pinned evaluation order. First, the contract value is fixed as `base_price_cents` plus the signed `delta_price_cents` of all `APPROVED` change orders — the cap depends on this value, so it is computed before anything else. Second, the cap is that contract value multiplied by the program's `penalty_cap_pct`, rounded half-up to integer cents. Third, the adjusted committed date is the contractual date plus the included excusable events' days in `event_seq` order. Fourth, the non-excusable late days are the calendar days from that adjusted date to the reference date, floored at zero. Fifth, the raw penalty is those days multiplied by `daily_penalty_rate_cents`. Sixth and finally, the penalty is the smaller of the raw figure and the cap.

The two variants differ only in what they include and when they look. The **projection** variant — surfaced on every program read as `projected_penalty_cents` and recomputed on any delay or change-order mutation — includes confirmed excusable events *and* still-`REPORTED` excusable events, and takes its reference date as the later of the logical clock date and the adjusted committed date, i.e. it assumes delivery at the later of today and the current commitment. The **settlement** variant — computed when the `FINAL` invoice is issued and again at delivery, persisted as `penalty_final_cents` — excludes `REPORTED` and `DISPUTED` events entirely and takes its reference date as the actual delivery date (or the logical clock date at issuance if the aircraft has not yet been delivered). Identical underlying data can therefore yield a settlement penalty different from — usually larger than — the projection the customer last saw; the figure is fixed at issuance and later slippage is not re-billed.

### 3.11. Quality Inspection and the Rework Loop

A `QualityInspector` schedules a **Quality Inspection** against a program while it is `IN_WORK` or `IN_INSPECTION`, naming an `inspection_type` of `PREP`, `PAINT`, `INTERIOR`, or `FINAL`; the inspection begins `SCHEDULED`. Recording a result supplies the `result` (`PASS` or `FAIL`) together with the `major_defects` and `minor_defects` counts, and requires the program to be `IN_INSPECTION` (`ERR_INVALID_STATE` otherwise). The `FINAL` type carries a prerequisite on both outcomes: at least one `PASSED` `PAINT` inspection and at least one `PASSED` `INTERIOR` inspection must already exist for the program, else the result recording is rejected with `ERR_FINAL_INSPECTION_PREREQUISITE`.

A `PASS` simply closes the inspection. A `FAIL` is louder: the inspection becomes `FAILED` (terminal for that record), the program automatically reverts from `IN_INSPECTION` to `IN_WORK` with `rework_cycles` incremented as described in §3.5, and when the recorded `major_defects` reaches two or more the system creates a safety-linked discovery item as described in §3.6 — at exactly one major defect no item is created; at two, one is. Rework means scheduling a *new* inspection of the same type; the system links it to the failed one via `rework_of_id`, and the delivery gate's first step (§3.5) is precisely the rule that every `FAILED` inspection must be answered by a later `PASSED` inspection of the same type.

### 3.12. Invoicing: Milestones, Stall Fees, and Settlement

Billing runs through the **Invoice**, drafted by a `FinanceClerk` against a program with a `kind` of `DEPOSIT`, `PROGRESS`, or `FINAL`. Drafting is permitted in any non-terminal program phase — the kind-appropriate phase is enforced at issuance, not at drafting — and at most one non-`VOIDED` invoice of each kind may exist per program. An invoice begins `DRAFT`, and while it remains a draft its `lines` are a living computation, regenerated on every program-total, discovery, or penalty mutation; issuance freezes them.

Every line is individually rounded half-up to integer cents first, and only then summed into `total_cents` — sum-then-round is forbidden, and the per-line handling surcharge below is where that ordering bites. The line composition by kind:

- A `DEPOSIT` invoice carries a single milestone line: ten percent of `base_price_cents`, rounded.
- A `PROGRESS` invoice carries a milestone line of forty percent of `base_price_cents`, rounded, plus a hangar stall fee line. The stall fee takes the program's longest-duration non-`CANCELLED` hangar slot (`BOOKED`, `ACTIVE`, or `RELEASED`; ties broken by earliest `created_at`, and the line is zero if none exists), computes the calendar-day ceiling of its occupied window — the window length divided by twenty-four hours, rounded up — and multiplies those days by the bay's `daily_rate_cents`.
- A `FINAL` invoice carries a remainder line equal to `total_contract_value_cents` minus the rounded deposit milestone (ten percent of base) minus the rounded progress milestone (forty percent of base) — those two constants are subtracted whether or not the corresponding invoices were ever created — followed by one line per discovery item in `APPROVED` or `COMPLETED` status (the `actual_cost_cents` for completed items, the `est_cost_cents` for merely approved ones), plus a per-item handling line of ten percent of that item's amount, each handling line individually rounded half-up; then a booth fee line summing the `actual_fee_cents` of all `COMPLETED` bookings (or the `scheduled_fee_cents` of `BOOKED` bookings when none have completed); and finally a penalty credit line equal to the negative of `penalty_final_cents` as fixed at issuance.

Issuance is gated by phase and uniqueness, both rejected with the named errors: a `DEPOSIT` invoice may be issued from `BOOKED` onward through `READY_FOR_DELIVERY`; a `PROGRESS` invoice requires `IN_WORK` or later but not `DELIVERED` or `CANCELLED`; a `FINAL` invoice requires exactly `READY_FOR_DELIVERY` — violations surface as `ERR_INVOICE_KIND_PHASE` — and a second non-`VOIDED` invoice of the same kind surfaces as `ERR_INVOICE_ALREADY_ISSUED`. Issuing stamps `issued_at` from the logical clock, freezes the lines, and for the `FINAL` kind persists the settlement-variant penalty into `penalty_final_cents`. The customer pays an `ISSUED` invoice — ownership-checked — moving it to `PAID` and recomputing the program's `billed_total_cents`, which sums `total_cents` over invoices in `ISSUED` or `PAID` status and nothing else; the payment increments the program's version. A `FinanceClerk` may void a `DRAFT` invoice freely, or an `ISSUED` one provided the program is not yet `DELIVERED` (`ERR_INVALID_STATE`); voiding an issued invoice drops it back out of `billed_total_cents` exactly, per the compensating invariant of §2.7, and increments the program version, while voiding a draft leaves the total untouched since drafts never contributed.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code. Operations that modify an existing resource — state transitions, approvals, and other actions — return a `200 OK` status code. All endpoints are mounted under `/completion`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/completion/_clock/set_current_utc` | Set the logical clock to a supplied instant | CenterAdmin |
| POST | `/completion/customers` | Register a customer/operator | CenterAdmin |
| GET | `/completion/customers` | List customers (paginated) | Any |
| POST | `/completion/customers/{id}/credit-status` | Set customer credit status | CenterAdmin |
| POST | `/completion/aircraft` | Register an aircraft | CenterAdmin |
| GET | `/completion/aircraft/{id}` | Get aircraft | Any |
| GET | `/completion/aircraft` | List aircraft (filterable by customer) | Any |
| POST | `/completion/programs` | Create a refurbishment program (quote) | ProgramManager |
| GET | `/completion/programs/{id}` | Get program including all computed fields | Any |
| GET | `/completion/programs` | List programs | Any |
| POST | `/completion/programs/{id}/advance` | Advance program phase | ProgramManager |
| POST | `/completion/programs/{id}/cancel` | Cancel a program | ProgramManager |
| POST | `/completion/paint-schemes` | Create livery/paint scheme | DesignLead |
| GET | `/completion/paint-schemes/{id}` | Get scheme | Any |
| GET | `/completion/paint-schemes` | List schemes | Any |
| POST | `/completion/paint-schemes/{id}/submit` | Submit scheme for customer approval | DesignLead |
| POST | `/completion/paint-schemes/{id}/approve` | Customer approves scheme; supersedes prior | CustomerRep |
| POST | `/completion/paint-schemes/{id}/reject` | Customer rejects scheme | CustomerRep |
| POST | `/completion/paint-schemes/{id}/revise` | Return rejected scheme to draft | DesignLead |
| POST | `/completion/surface-assessments` | Create surface assessment (supersedes prior) | ShopTechnician |
| GET | `/completion/surface-assessments/{id}` | Get assessment | Any |
| GET | `/completion/surface-assessments` | List assessments | Any |
| POST | `/completion/surface-assessments/{id}/decide` | Record strip-vs-scuff decision and severity | ShopTechnician |
| POST | `/completion/surface-assessments/{id}/amend` | Amend a decided assessment | ShopTechnician |
| POST | `/completion/discovery-items` | Log discovery work item | ShopTechnician |
| GET | `/completion/discovery-items/{id}` | Get discovery item | Any |
| GET | `/completion/discovery-items` | List discovery items | Any |
| POST | `/completion/discovery-items/{id}/estimate` | Attach cost/hour estimate | ProgramManager |
| POST | `/completion/discovery-items/{id}/approve` | Customer approves estimate | CustomerRep |
| POST | `/completion/discovery-items/{id}/reject` | Customer rejects estimate | CustomerRep |
| POST | `/completion/discovery-items/{id}/defer` | Customer defers non-safety item | CustomerRep |
| POST | `/completion/discovery-items/{id}/complete` | Complete approved work with actual cost | ShopTechnician |
| POST | `/completion/change-orders` | Draft a change order | ProgramManager |
| GET | `/completion/change-orders/{id}` | Get change order | Any |
| GET | `/completion/change-orders` | List change orders | Any |
| POST | `/completion/change-orders/{id}/submit` | Submit change order to customer | ProgramManager |
| POST | `/completion/change-orders/{id}/approve` | Customer approves; applies deltas and cascades | CustomerRep |
| POST | `/completion/change-orders/{id}/reject` | Customer rejects change order | CustomerRep |
| POST | `/completion/change-orders/{id}/counter` | Customer counters with note | CustomerRep |
| POST | `/completion/change-orders/{id}/revise` | Revise countered order back to draft | ProgramManager |
| POST | `/completion/hangar-bays` | Register a hangar bay | CenterAdmin |
| GET | `/completion/hangar-bays` | List bays | Any |
| POST | `/completion/hangar-bays/{id}/deactivate` | Deactivate a bay | CenterAdmin |
| POST | `/completion/hangar-slots` | Book a hangar slot | ProgramManager |
| GET | `/completion/hangar-slots/{id}` | Get slot | Any |
| GET | `/completion/hangar-slots` | List slots | Any |
| POST | `/completion/hangar-slots/{id}/activate` | Activate a booked slot | ProgramManager |
| POST | `/completion/hangar-slots/{id}/release` | Release an active slot | ProgramManager |
| POST | `/completion/hangar-slots/{id}/cancel` | Cancel a booked slot | ProgramManager |
| POST | `/completion/paint-booths` | Register a paint booth with cure buffer | CenterAdmin |
| GET | `/completion/paint-booths` | List booths | Any |
| POST | `/completion/booth-bookings` | Book a booth spray window | ProgramManager |
| GET | `/completion/booth-bookings/{id}` | Get booking | Any |
| GET | `/completion/booth-bookings` | List bookings | Any |
| POST | `/completion/booth-bookings/{id}/complete` | Mark spray work done with actual hours | ShopTechnician |
| POST | `/completion/booth-bookings/{id}/cancel` | Cancel a booking | ProgramManager |
| POST | `/completion/soft-good-lots` | Register an interior soft-goods lot | ShopTechnician |
| GET | `/completion/soft-good-lots/{id}` | Get lot | Any |
| GET | `/completion/soft-good-lots` | List lots | Any |
| POST | `/completion/soft-good-lots/{id}/burn-tests` | Record a burn test for a lot | ShopTechnician |
| GET | `/completion/soft-good-lots/{id}/burn-tests` | List burn tests of a lot | Any |
| POST | `/completion/weight-balance-records` | Prepare a weight & balance record | ShopTechnician |
| GET | `/completion/weight-balance-records/{id}` | Get record | Any |
| GET | `/completion/weight-balance-records` | List records | Any |
| POST | `/completion/weight-balance-records/{id}/sign-off` | Quality sign-off on a record | QualityInspector |
| POST | `/completion/quality-inspections` | Schedule an inspection | QualityInspector |
| GET | `/completion/quality-inspections/{id}` | Get inspection | Any |
| GET | `/completion/quality-inspections` | List inspections | Any |
| POST | `/completion/quality-inspections/{id}/record-result` | Record pass/fail with defect counts | QualityInspector |
| POST | `/completion/delay-events` | Report a schedule delay event | ProgramManager |
| GET | `/completion/delay-events/{id}` | Get delay event | Any |
| GET | `/completion/delay-events` | List delay events | Any |
| POST | `/completion/delay-events/{id}/confirm` | Confirm event; shifts committed date if excusable | CenterAdmin |
| POST | `/completion/delay-events/{id}/dispute` | Customer disputes a reported event | CustomerRep |
| POST | `/completion/invoices` | Create a draft invoice | FinanceClerk |
| GET | `/completion/invoices/{id}` | Get invoice | Any |
| GET | `/completion/invoices` | List invoices | Any |
| POST | `/completion/invoices/{id}/issue` | Issue invoice; freezes lines | FinanceClerk |
| POST | `/completion/invoices/{id}/pay` | Customer pays an issued invoice | CustomerRep |
| POST | `/completion/invoices/{id}/void` | Void a draft or issued invoice | FinanceClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_PROGRAM_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_AIRCRAFT_BUSY` | 409 Conflict |
| `ERR_BAY_INACTIVE` | 409 Conflict |
| `ERR_SCHEME_PHASE_TOO_ADVANCED` | 409 Conflict |
| `ERR_SCHEME_NOT_APPROVED` | 409 Conflict |
| `ERR_ASSESSMENT_REQUIRED` | 409 Conflict |
| `ERR_ASSESSMENT_LOCKED` | 409 Conflict |
| `ERR_CORROSION_DISCOVERY_REQUIRED` | 409 Conflict |
| `ERR_SAFETY_DEFERRAL_FORBIDDEN` | 409 Conflict |
| `ERR_DELIVERY_WINDOW_PASSED` | 409 Conflict |
| `ERR_DEFER_REASON_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DISCOVERY_ITEMS_OPEN` | 409 Conflict |
| `ERR_SLOT_IN_PAST` | 409 Conflict |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_BOOTH_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_BOOTH_BOOKING_REQUIRED` | 409 Conflict |
| `ERR_CERT_REQUIRED` | 409 Conflict |
| `ERR_WEIGHT_NOT_SIGNED_OFF` | 409 Conflict |
| `ERR_WEIGHT_DELTA_EXCEEDED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INSPECTION_OUTSTANDING` | 409 Conflict |
| `ERR_FINAL_INSPECTION_PREREQUISITE` | 409 Conflict |
| `ERR_REFERENTIAL_INTEGRITY` | 422 Unprocessable Entity |
| `ERR_CREDIT_HOLD` | 402 Payment Required |
| `ERR_INVOICE_KIND_PHASE` | 409 Conflict |
| `ERR_INVOICE_ALREADY_ISSUED` | 409 Conflict |
| `ERR_INVOICE_NOT_SETTLED` | 409 Conflict |
