# Tree Service & Arborist API — Product Requirements Document

## 1. Introduction

The Tree Service & Arborist API coordinates the full operational arc of a professional tree-care business, from the first site visit through final billing. A storm-damaged oak, a heritage elm slated for protected-species review, a row of limbs leaning into a power line — each becomes a **work order** that must be assessed for hazard, priced, permitted where the municipality demands it, scheduled against a finite pool of crews and heavy equipment, and finally either completed and invoiced or cancelled and unwound. The system exists to keep these four concerns — safety, permitting, scheduling, and money — from drifting out of agreement with one another as a job moves through its stages.

Two pricing philosophies coexist. Some jobs are sold as a fixed lump-sum bid (a **per-job** engagement) where the accepted quote becomes the contract price the client owes regardless of what the work actually costs to perform. Others are billed on **hourly** actuals, where the real invoice is metered crew-hours, equipment-hours, and disposal tonnage accrued during the job. Layered over both are surcharges for hazard severity, for working inside a utility-line clearance buffer, for removing designated heritage specimens, and for storm-emergency dispatch. Because crews and cranes are shared and scarce, the API also enforces overlap and mobilization-buffer rules so that a single resource is never double-committed, and it uses optimistic concurrency so that a dispatcher acting on a stale view of a work order cannot silently overwrite another writer's scheduling decision.

This document specifies the API's resources, their lifecycles, the calculations that produce every monetary figure, the validations that protect each operation, and the role-based permissions that govern who may do what. It is written for the engineer who will build the service; domain intent is given first, with the precise contract that follows from it stated alongside.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and the `X-User-Role` header declares the operational capacity under which they act. If either header is absent, or if `X-User-Role` is not one of the four recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_AUTH` (HTTP 401). When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `Dispatcher`, `Arborist`, `FinanceClerk`, and `Client`. A `Dispatcher` is the operations role — it provisions service areas, crews, and equipment, owns all scheduling through bookings, drives the work-order completion and cancellation transitions, and renders permit-review decisions. An `Arborist` is the field expert — it adds trees, runs hazard assessment, drafts and issues estimates and their line items, and files and resubmits permit applications. A `FinanceClerk` is the billing role — it records, finalizes, and voids debris-disposal tickets that feed the disposal ledger. A `Client` is the customer who owns a work order and accepts or declines the estimates issued against it.

The four roles are all **opaque** identities: `X-User-ID` is an operator or customer identifier that is not the primary key of any persisted role entity. For `Dispatcher`, `Arborist`, and `FinanceClerk`, the server does not compare `X-User-ID` to any stored entity `id`; the header simply authorizes the action. For `Client`, the value carries ownership meaning even though it is still opaque: when a work order is created, the `client_user_id` recorded on it is the owning customer's identifier, and ownership checks on estimate acceptance and decline compare the acting `Client`'s `X-User-ID` against that stored `client_user_id`. A `Client` acting on a work order it does not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The server records `client_user_id` from the request body at creation time but never treats it as a foreign key into a user table.

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

For endpoints that return lists of resources, pagination is controlled through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and a supplied value is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip before collecting the page and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses carry the pagination bookkeeping in the `meta` object of the envelope, specifically the fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every resource in the system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. All of the entities in this system — `ServiceArea`, `Crew`, `Equipment`, `WorkOrder`, `TreeAsset`, `Estimate`, `LineItem`, `Permit`, `Booking`, and `DisposalTicket` — additionally carry an `updated_at` timestamp (also ISO 8601 UTC with three fractional digits) and an integer `version`. The `updated_at` field is refreshed on any mutation to the resource, and `version` is an integer that begins at 1 on creation and increments by one on every subsequent mutation of that resource. There are no version-less entities in this domain; each of the ten entity types exposes all four common fields.

Because the `WorkOrder` is the hub of nearly every workflow, its `version` is the one that matters most for concurrency. Several distinct operations legitimately advance a work order's `version`: completing the work order, cancelling it, assessing it, accepting an estimate against it, finalizing a booking on it, and finalizing a disposal ticket on it. Each of these mutations both bumps `version` and refreshes `updated_at`. Computed fields on a resource — for example the running ledgers on a `WorkOrder` — are themselves mutations: when the server recomputes and stores them, that counts as a modification and the resource's `updated_at` and `version` move accordingly.

### 2.5. Hierarchical Consistency and Cascades

The system keeps parent and child resources in agreement automatically, without requiring the client to issue a separate request against each affected child. When a hazard assessment runs, the server recomputes the `hazard_score` and `hazard_tier` of every `TreeAsset` on the work order and then sets the work order's own `hazard_level` to the highest tier observed across its trees; it also recomputes whether the work order `requires_permit`. When a work order is cancelled, the server reaches across every dependent resource to unwind it — reserved bookings are released, recorded disposal tickets are voided, and any estimate still in `DRAFT` or `ISSUED` is superseded — all as side effects of the single cancel action. When an estimate is accepted, every other estimate on that work order that is still `ISSUED` is superseded as a side effect.

The compensation rules are exact, not approximate. Releasing a reserved booking restores that resource's total reserved time to precisely the value it held before the booking existed, and because a reserved booking was never billed, no ledger figure changes. Voiding a disposal ticket that was only ever recorded (never finalized) leaves the work order's accrued disposal cost exactly as it was. The cancel-then-release-then-free-calendar chain must leave each crew's and each equipment unit's reserved-minutes total unchanged relative to the state before the work order existed.

### 2.6. Nested Resource Retrieval and Path Validation

Many resources are addressed beneath their parent work order — trees, estimates, permits, and disposal tickets all live under a work-order path, and line items reference their estimate. Whenever a request path contains more than one resource identifier, the server validates them strictly left-to-right and rejects on the first that does not resolve. The parent work order is checked first; only if it exists does the server attempt to resolve the nested estimate, permit, tree, or disposal ticket beneath it. A request for an estimate under a non-existent work order therefore fails with `ERR_WORK_ORDER_NOT_FOUND` before the estimate is ever looked up. The corresponding not-found codes are `ERR_WORK_ORDER_NOT_FOUND`, `ERR_ESTIMATE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_TREE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_DISPOSAL_TICKET_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, and `ERR_SERVICE_AREA_NOT_FOUND`, each returned with HTTP 404. The same discipline applies to foreign keys supplied in a request body: when a create payload names a `service_area_id`, `work_order_id`, `crew_id`, `equipment_id`, `estimate_id`, or `tree_asset_id` that does not resolve, the request fails with the matching not-found code.

### 2.7. Precision, Rounding, and the Cents Convention

Every monetary figure in the system is an integer count of cents. There are no fractional-cent values stored or returned. Wherever a calculation multiplies a rate by a possibly-fractional quantity or applies a percentage surcharge, the result is rounded to a whole number of cents using the **round-half-up** convention (a value exactly at the half-cent rounds upward). The order in which rounding is applied is itself part of the contract and is pinned in the relevant calculation rules below — in particular, line costs are rounded individually before they are summed, and surcharges are rounded as they are computed rather than after aggregation. The `heritage_surcharge_pct` configured on a service area is a fractional rate (for instance 0.15 meaning fifteen percent) and is stored at its input precision; it is one of the few values that is not in cents.

### 2.8. Optimistic Concurrency on Booking Creation

Reserving a crew or equipment window is the one write in this system guarded by optimistic concurrency, because a booking decision depends on a current view of the work order's schedule and budget context. A request to reserve a resource must carry `expected_work_order_version`, the `version` of the target `WorkOrder` that the client last observed; this field is required and is not optional. The server compares it against the work order's current `version`. If another writer has advanced that version since the client read it — a sibling booking create, a booking finalize, a disposal-ticket finalize, or an estimate acceptance each does so — then the carried value is stale, the client is acting on an out-of-date view of the schedule and budget, and the reservation is rejected with `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412). Only when the supplied version matches the live version does the reservation proceed. No other endpoint in the system takes a version field; reservation creation is the sole optimistic-concurrency-guarded write.

### 2.9. Validation Ordering

When several checks apply to one operation, they are evaluated in a fixed priority order so that the failure a client sees is deterministic. Authentication comes first: the presence and validity of the auth headers (`ERR_MISSING_OR_INVALID_AUTH`) is checked before role authorization (`ERR_FORBIDDEN_ROLE`). Existence checks follow — first that every resource named in the path resolves left-to-right, then that every foreign key in the body resolves — both yielding the relevant 404 code. Next comes request-shape validation: required fields present, enum values legal, the booking window's `end_at` strictly after its `start_at`, numeric quantities and hours and diameters positive, and the `resource_kind` consistent with which of `crew_id`/`equipment_id` was supplied. After shape validation, the optimistic-concurrency version check runs on booking creation. Then state-transition legality is checked (the target must be in the right state for the requested transition). After the generic transition check come the assess-and-issue content guards (a work order must have at least one tree before assessment; an estimate must hold at least one line item before issuance).

The domain-specific business checks then run in the priority order **safety before scheduling before fiscal**. Utility-line clearance is verified first, then the permit gate at estimate acceptance, then ownership, then crew-overlap and equipment-buffer scheduling conflicts, then resource-region matching, and finally the retire guard. Two of these orderings matter especially and are restated where they apply: at estimate acceptance the permit-required gate (`ERR_PERMIT_REQUIRED`) is evaluated at priority 10, strictly **before** the ownership check (`ERR_NOT_RESOURCE_OWNER`) at priority 11, so a missing permit surfaces ahead of an ownership failure.

## 3. Business Logic & Workflows

### 3.1. Configuring Regions, Crews, and Equipment

Before any job can be scheduled, a `Dispatcher` establishes the operating environment. A **service area** is a region configuration carrying a display `name`, a short `region_code` such as "NW-01", and the money-and-policy settings that govern jobs in that region. The `disposal_fee_cents_per_ton` is the tipping fee charged per ton of debris hauled to the landfill or recycler, given in integer cents and never negative. The `requires_permit_authority` flag, which defaults to true, declares whether protected or heritage trees in this region must clear a municipal permit before removal. The `heritage_surcharge_pct` is the fractional premium applied to per-job estimates that include heritage-tree removal; it defaults to 0.15 and is never negative.

A **crew** belongs to a home region through its `service_area_id` and carries a `name`, an `hourly_rate_cents` labor rate per crew-hour that must be greater than zero, and a `certified_utility_clearance` flag (default false) marking whether the crew may work inside the utility buffer. A crew's `status` begins `AVAILABLE` when registered. An **equipment** unit likewise has a `service_area_id`, a `name` or asset tag, and an `hourly_rate_cents` per-hour rate greater than zero; its `kind` is one of `CRANE`, `CHIPPER`, or `STUMP_GRINDER`. Each unit also carries a `mobilization_buffer_minutes` setup-and-teardown buffer (default 30, never negative) that must separate two bookings of that unit — crane units in practice carry a non-zero buffer while others may be zero. Equipment `status` also begins `AVAILABLE`.

Both crews and equipment follow a simple retirement lifecycle. A `Dispatcher` may retire a resource, moving its `status` from `AVAILABLE` to `RETIRED`, but only when that resource has no booking still in `RESERVED`; an attempt to retire a resource that still holds a reserved booking is refused with `ERR_RESOURCE_HAS_RESERVATIONS`. Crews and equipment may be listed and filtered by their home region using the `service_area_id` query filter.

### 3.2. Opening a Work Order and Recording Its Trees

A job begins when a `Dispatcher` or the `Client` opens a **work order** in the `DRAFT` state. The creation payload names the governing region by `service_area_id`, the owning customer by `client_user_id`, a free-text `site_address`, and the `pricing_mode`, which is either `PER_JOB` for an accepted lump-sum bid or `HOURLY` for metered crew-and-equipment actuals. The optional `is_emergency` flag (default false) marks storm-emergency dispatch, which raises priority and later applies an emergency multiplier to the estimate. At creation the work order starts with `hazard_level` of `LOW`, `requires_permit` false, an `accepted_estimate_id` of null, the running ledgers `labor_cost_accrued_cents` and `disposal_cost_accrued_cents` at 0, `final_invoice_cents` at 0, and `version` 1. Work orders can be listed and filtered by `service_area_id`, by `client_user_id`, and by `accepted_estimate_id`.

While the work order is still in `DRAFT`, an `Arborist` or a `Dispatcher` adds the trees to be worked on. Each **tree asset** is implicitly attached to its parent through `work_order_id` and describes one tree: its `species` common name, its `dbh_inches` (diameter at breast height, which must be greater than zero and drives both removal pricing and hazard tier), and a set of condition flags. The `is_protected` flag (default false) marks a municipally protected specimen needing a permit before removal; `is_heritage` (default false) marks a designated heritage tree, which implies protection and triggers the heritage surcharge on per-job pricing; `near_utility_line` (default false) means the crown or trunk sits within the utility-clearance buffer, which later forces any crew booking on this work order to use a line-clearance-certified crew. The `lean_degrees` value (default 0, never negative) records the lean from vertical, and `has_visible_decay` (default false) flags visible structural decay. Two computed fields ride along on each tree: its `hazard_score` and its `hazard_tier`, both of which are filled in by the assessment described next. Trees on a work order can be listed and individually retrieved beneath that work order.

### 3.3. Hazard Assessment and Its Scoring

When the trees have been recorded, an `Arborist` runs the hazard assessment, advancing the work order from `DRAFT` to `ASSESSED`. The assessment refuses to run if the work order has no tree assets at all, returning `ERR_NO_TREES_ASSESSED`. When it does run, it recomputes a per-tree `hazard_score` for every child tree, derives each tree's `hazard_tier`, sets the work order's `hazard_level` to the maximum tier across all its trees, recomputes `requires_permit`, and increments the work order's `version` by one. (The per-tree score is also computed when a tree is first added while the work order is still `DRAFT`.)

A single tree's hazard score is the sum of three contributions. The **diameter contribution** is tiered on `dbh_inches`: a tree at least 36 inches in diameter contributes 50 points; a tree that is at least 18 inches but under 36 contributes 30 points; anything thinner contributes 10 points. The boundary is inclusive at the lower edge — a tree of exactly 18.0 inches lands in the 30-point band, while 17.999 inches falls to the 10-point band. The **lean contribution** takes the lean in degrees, divides it by 5 and rounds that quotient down to a whole number, multiplies the result by 10, and then caps the total at 30 — so the lean contribution can only be 0, 10, 20, or 30. The **decay contribution** is 20 points when `has_visible_decay` is true and 0 otherwise. The three contributions are added to give the integer `hazard_score`.

The tier follows from the score by strict lower-bound thresholds: a score of 70 or more is `SEVERE`, a score of at least 40 but under 70 is `MODERATE`, and anything below 40 is `LOW`. The boundary at 40 is inclusive — a score of exactly 40 is `MODERATE`, not `LOW`.

### 3.4. Building an Estimate Line by Line

Once a work order is `ASSESSED` (or already `QUOTED`, allowing a fresh estimate after a decline), an `Arborist` drafts an **estimate**. A new estimate starts in `DRAFT` with its `pricing_mode` copied from the work order at draft time and every total at 0. Each estimate is attached to its work order through `work_order_id` and accumulates a set of computed money fields described below: a `line_items_subtotal_cents`, a `hazard_surcharge_cents`, a `heritage_surcharge_cents`, a `utility_surcharge_cents`, an `emergency_multiplier_applied` flag, and the final `total_cents`. Estimates on a work order can be listed and individually retrieved beneath it.

The arborist fills the estimate with **line items**, each supplied with its parent `estimate_id` in the body, a `service_type`, and a `quantity` greater than zero. The optional `tree_asset_id` names the tree a line applies to; it is required for `REMOVAL` and `STUMP_GRINDING` lines and is null for `HAUL_OFF` and `UTILITY_CLEARANCE` lines. The `service_type` is one of `REMOVAL`, `STUMP_GRINDING`, `HAUL_OFF`, or `UTILITY_CLEARANCE`, and the meaning of `quantity` depends on it: for `REMOVAL` and `UTILITY_CLEARANCE` it is a tree count and is always 1; for `STUMP_GRINDING` it is the stump diameter in inches; for `HAUL_OFF` it is debris tons. Line items may only be added while the parent estimate is in `DRAFT`; an attempt against an estimate in any other state is refused with `ERR_ESTIMATE_NOT_DRAFT`. Each line carries two computed fields, a `unit_cost_cents` and an `extended_cost_cents`. Line items can be listed and filtered by `estimate_id` and by `tree_asset_id`.

The per-line `unit_cost_cents` is resolved from the service type. A `REMOVAL` line is priced by the diameter tier of its referenced tree, billing the whole tree at the tier its `dbh_inches` falls in (the tier is not applied marginally): 180000 cents for a tree at least 36 inches, 95000 cents for a tree at least 18 but under 36 inches, and 45000 cents for a tree under 18 inches. A `STUMP_GRINDING` line costs 1200 cents per inch of stump diameter. A `HAUL_OFF` line costs 8500 cents per ton of debris. A `UTILITY_CLEARANCE` line is a flat 60000 cents. The line's `extended_cost_cents` is the unit cost multiplied by the quantity, rounded half-up to a whole number of cents — and crucially this rounding happens once per line, here, before any subtotaling.

### 3.5. Surcharges, the Dual Pricing Variants, and Issuing the Estimate

An `Arborist` issues an estimate to move it from `DRAFT` to `ISSUED`. Issuance is refused if the estimate holds no line items, returning `ERR_ESTIMATE_EMPTY`, and it is refused with `ERR_ESTIMATE_NOT_DRAFT` if the estimate is not in `DRAFT`. When the work order is being quoted for the first time, the very first issue also advances the work order from `ASSESSED` to `QUOTED` and increments the work order's `version` by one. Issuing recomputes every surcharge and the `total_cents` so the figures the client sees are current; the same recomputation also happens whenever a line item is mutated while the estimate is still `DRAFT`.

The total is built up in a pinned order. First, the `line_items_subtotal_cents` is the sum of the already-rounded `extended_cost_cents` of every line — rounding happens per line first, then those integer cents are summed; the subtotal is never produced by summing raw products and rounding once at the end. Next the `hazard_surcharge_cents` is computed from the work order's overall `hazard_level`: the surcharge percentage is twenty percent when the level is `SEVERE`, ten percent when it is `MODERATE`, and zero otherwise, and that percentage is applied to the integer subtotal and rounded half-up on its own. The `utility_surcharge_cents` is a flat 25000 cents for each distinct tree that is `near_utility_line` and is referenced by a `REMOVAL` or `UTILITY_CLEARANCE` line on the estimate. The `heritage_surcharge_cents` applies only under per-job pricing: when `pricing_mode` is `PER_JOB` and at least one `REMOVAL` line references a heritage tree, it is the service area's `heritage_surcharge_pct` applied to the integer subtotal and rounded half-up; in every other case, including all hourly estimates, it is zero.

These four amounts — subtotal plus the three surcharges — are added to form a pre-emergency figure. The emergency multiplier is applied last and only when the work order's `is_emergency` is true: in that case the `total_cents` is the pre-emergency figure multiplied by 1.5 and rounded half-up, and `emergency_multiplier_applied` is recorded as true; otherwise the `total_cents` equals the pre-emergency figure and `emergency_multiplier_applied` is false.

The two pricing modes diverge in what `total_cents` means downstream. Under `PER_JOB`, the heritage surcharge may be non-zero, and the `total_cents` is the binding contract price: when the client accepts it, it pins the price the work order will be invoiced at on completion, and the actual booking and disposal costs never change that invoice. Under `HOURLY`, the heritage surcharge is forced to zero — the heritage premium is folded into metered hours rather than the quote — and the `total_cents` is only a non-binding planning figure; the real invoice for an hourly job is built from metered actuals at completion, not from this total.

### 3.6. The Permit Revision Cycle

Some jobs cannot proceed to acceptance without a municipal permit. A work order `requires_permit` exactly when at least one of its trees is protected or heritage **and** the governing service area's `requires_permit_authority` is true; this flag is recomputed during assessment. An `Arborist` files a **permit** application beneath the work order with a municipal `authority_ref` and an optional `covers_heritage` flag (default false) declaring whether the application covers at least one heritage tree. A new permit starts in `DRAFT` with `revision_count` at 0.

The permit moves through a review cycle. Submitting a permit advances it to `UNDER_REVIEW`, whether from the initial `DRAFT` or from a later `CHANGES_REQUESTED` state; submission is only allowed when the work order actually `requires_permit`, and a submit against a work order that does not require one is refused with `ERR_PERMIT_NOT_REQUIRED`. While a permit sits `UNDER_REVIEW`, a `Dispatcher` may either request changes or decide it. Requesting changes sends the permit from `UNDER_REVIEW` back to `CHANGES_REQUESTED` and increments its `revision_count` by one; the permit may then be resubmitted, looping `UNDER_REVIEW` → `CHANGES_REQUESTED` → `UNDER_REVIEW` any number of times, each round-trip bumping `revision_count`. When the dispatcher instead decides the permit, the body carries a `decision`: a value of APPROVE drives `UNDER_REVIEW` → `APPROVED`, and a value of DENY drives `UNDER_REVIEW` → `DENIED`. Both `APPROVED` and `DENIED` are terminal. Permits on a work order can be listed and individually retrieved beneath it.

### 3.7. Client Acceptance, Decline, and the Redraft Loop

Once an estimate is `ISSUED`, the owning `Client` decides on it. Accepting an issued estimate is the pivotal commitment that moves the work order from `QUOTED` to `SCHEDULED`. Before that happens, two guards run in order. First, if the work order `requires_permit`, an `APPROVED` permit must already exist on it; absent one, acceptance is refused with `ERR_PERMIT_REQUIRED`, and this gate is checked at priority 10 — ahead of ownership. Second, the acting client must own the work order, that is, their `X-User-ID` must equal the work order's `client_user_id`; a mismatch is refused with `ERR_NOT_RESOURCE_OWNER` at priority 11. Acceptance is also refused with `ERR_ESTIMATE_NOT_ISSUED` if the target estimate is not in `ISSUED`. When acceptance succeeds, the estimate moves `ISSUED` → `ACCEPTED`, the work order's `accepted_estimate_id` is set to that estimate, every other estimate on the work order still in `ISSUED` is superseded to `SUPERSEDED`, the work order advances `QUOTED` → `SCHEDULED`, and the work order's `version` increments by one.

The owning client may instead decline an issued estimate. Declining requires that the acting client own the work order (otherwise `ERR_NOT_RESOURCE_OWNER`) and moves the estimate `ISSUED` → `DECLINED`. A decline does not drag the work order backward: it stays in `QUOTED`, so the arborist may draft a fresh estimate and issue it again, redrafting as many times as needed until the client accepts one. Beyond explicit decline and acceptance, the system itself supersedes estimates: an estimate in `DRAFT` or `ISSUED` is driven to `SUPERSEDED` whenever a sibling estimate is accepted or when the work order is cancelled. `ACCEPTED`, `DECLINED`, and `SUPERSEDED` are the terminal estimate states.

### 3.8. Scheduling Resources Against the Job

With the work order `SCHEDULED`, a `Dispatcher` reserves the crews and equipment that will do the work by creating **bookings**. A booking is a flat top-level resource that names the `work_order_id` it serves, a `resource_kind` of either `CREW` or `EQUIPMENT`, the chosen `crew_id` (required when the kind is `CREW`, otherwise null) or `equipment_id` (required when the kind is `EQUIPMENT`, otherwise null), a `start_at` and an `end_at` window in ISO 8601 UTC where `end_at` must be strictly after `start_at`, and the `expected_work_order_version` for the optimistic-concurrency check described in §2.8. A booking also carries an `actual_hours` field that is null until finalization and a computed `billed_cost_cents`. The window-shape check rejects a non-positive window with `ERR_INVALID_TIME_WINDOW`, and a `resource_kind` that disagrees with which of `crew_id`/`equipment_id` was supplied is rejected with `ERR_RESOURCE_KIND_MISMATCH`. A new booking begins in `RESERVED`, occupies the chosen resource's window, and increments the work order's `version` by one (so a later create still carrying the prior version becomes stale). Bookings can be listed and filtered by `work_order_id`, by `crew_id`, and by `equipment_id`.

Several safety and scheduling checks run on a reservation, in the safety-before-scheduling-before-fiscal order. If any tree on the work order is `near_utility_line`, then a `CREW` booking must use a crew whose `certified_utility_clearance` is true; a crew lacking the certification is rejected with `ERR_UTILITY_CLEARANCE_REQUIRED`. For a `CREW` booking, the new window is checked for overlap against every other `RESERVED` or `FINALIZED` booking of the same crew, treating each window as half-open over its `start_at` and `end_at`: any intersection is rejected with `ERR_CREW_DOUBLE_BOOKED`, but adjacency where one window's end exactly equals another's start does not count as an overlap and is allowed. For an `EQUIPMENT` booking, the unit's `mobilization_buffer_minutes` is added to both sides of each existing `RESERVED` or `FINALIZED` window of that same unit, and the new booking is rejected with `ERR_EQUIPMENT_DOUBLE_BOOKED` if it falls within that buffered span — so adjacency that would be legal for a crew is rejected for a buffered unit. Finally, the booked crew's or equipment's `service_area_id` must equal the work order's `service_area_id`; a region mismatch is rejected with `ERR_RESOURCE_REGION_MISMATCH`.

### 3.9. Metering Hours, Disposal, and the Cancellation Unwind

A reserved booking is closed out one of two ways. Finalizing a booking records the metered hours and moves it `RESERVED` → `FINALIZED`. Finalization is permitted only while the work order is `SCHEDULED` (otherwise `ERR_WORK_ORDER_NOT_SCHEDULED`) and only on a booking still `RESERVED` (otherwise `ERR_BOOKING_NOT_RESERVED`); the work-order-state guard is evaluated before the booking-state guard, so when both fail at once — for instance after the work order has been cancelled, which leaves the work order non-`SCHEDULED` and the booking `RELEASED` — `ERR_WORK_ORDER_NOT_SCHEDULED` surfaces ahead of `ERR_BOOKING_NOT_RESERVED`. Once both guards pass, the supplied `actual_hours` must be greater than zero, and a missing or non-positive value is rejected with `ERR_INVALID_ACTUAL_HOURS`. On finalization the server computes the booking's `billed_cost_cents`, adds it to the work order's `labor_cost_accrued_cents`, and increments the work order's `version` by one.

The billed cost first resolves the applicable per-hour rate: when `resource_kind` is `CREW` the rate is the crew's `hourly_rate_cents`, and when it is `EQUIPMENT` the rate is the equipment's `hourly_rate_cents`. Hours are then split at an overtime threshold of 8 hours: the regular portion is the lesser of the actual hours and 8, and the overtime portion is whatever exceeds 8 (zero if none). The regular hours are billed at the resolved rate and the overtime hours are billed at 1.5 times that rate, and the combined amount is rounded half-up exactly once to a whole number of cents — the two portions are summed before that single rounding so no double-rounding drift creeps in. The boundary is exact: 8.0 hours produces no overtime, while 8.001 hours puts a sliver into the overtime band.

Alternatively, a reserved booking may be released, moving `RESERVED` → `RELEASED`; release is permitted only on a booking still `RESERVED` (otherwise `ERR_BOOKING_NOT_RESERVED`) and simply frees the resource's occupied window so it no longer participates in overlap checks, touching no ledger because a reserved booking was never billed. The same release happens automatically to every reserved booking when the work order is cancelled.

Debris is tracked separately. A `Dispatcher` or a `FinanceClerk` records a **disposal ticket** beneath the work order, supplying the `debris_tons` hauled off (greater than zero); the ticket starts `RECORDED` with `fee_cents` of 0. A `FinanceClerk` finalizes the ticket, moving `RECORDED` → `FINALIZED` only while the work order is `SCHEDULED` (otherwise `ERR_WORK_ORDER_NOT_SCHEDULED`); finalization computes `fee_cents` as the `debris_tons` multiplied by the service area's `disposal_fee_cents_per_ton`, rounded half-up to whole cents, adds it to the work order's `disposal_cost_accrued_cents`, and increments the work order's `version` by one. A `FinanceClerk` may instead void a ticket, moving `RECORDED` → `VOIDED`, permitted only on a ticket still `RECORDED` (otherwise `ERR_TICKET_NOT_RECORDED`); voiding a never-finalized ticket leaves the accrued disposal cost unchanged. Disposal tickets can be listed and individually retrieved beneath their work order, and a recorded ticket is also voided automatically when the work order is cancelled. `FINALIZED` and `VOIDED` are the terminal ticket states.

### 3.10. Completion, Invoicing, and the Two Terminal Branches

A `SCHEDULED` work order forks to one of two terminal outcomes, and the two branches diverge sharply. Completing the work order moves it `SCHEDULED` → `COMPLETED`, but only when no booking on it is still `RESERVED` (every booking must be `FINALIZED` or `RELEASED`, otherwise `ERR_OPEN_BOOKINGS`) and no disposal ticket on it is still `RECORDED` (otherwise `ERR_OPEN_DISPOSAL`). On completion the server computes `final_invoice_cents` and increments the work order's `version` by one.

The invoice is computed by pricing mode. For a `PER_JOB` work order the invoice is forward-looking: it is exactly the accepted estimate's `total_cents`, the frozen contract price, and the actual labor and disposal accruals are ignored entirely. For an `HOURLY` work order the invoice is built from chronological actuals: it is the `labor_cost_accrued_cents` plus the `disposal_cost_accrued_cents` plus a hazard surcharge computed over those accruals. That hazard surcharge takes the sum of the labor and disposal accruals, multiplies it by the hazard percentage drawn from the work order's `hazard_level` — twenty percent for `SEVERE`, ten percent for `MODERATE`, zero otherwise — and rounds half-up to whole cents. The two modes consume opposite inputs through opposite algorithms: per-job freezes the quoted price and ignores actuals, hourly ignores any estimate and sums the metered ledgers plus the accrual-based surcharge.

Cancellation is the compensating branch and is reachable from `DRAFT`, `ASSESSED`, `QUOTED`, or `SCHEDULED` — any non-terminal state. A cancel against an already-terminal work order is refused with `ERR_WORK_ORDER_TERMINAL`. Cancelling drives a full unwind as side effects: every `RESERVED` booking is released, freeing that resource's calendar window; every `RECORDED` disposal ticket is voided; every `DRAFT` or `ISSUED` estimate is superseded; `final_invoice_cents` is set to 0; the work order moves to `CANCELLED`; and the work order's `version` increments by one. Nothing is billed on cancellation — the release-and-free-calendar chain must leave each resource's reserved-minutes total exactly as it stood before the work order existed. Where a transition is requested that is not legal from the resource's current state and no more specific state error applies, the system responds with `ERR_INVALID_STATE_TRANSITION`. Malformed request bodies more generally are rejected with `ERR_INVALID_REQUEST`, and an illegal enum value — on `pricing_mode`, `kind`, `resource_kind`, `service_type`, or `decision` — with `ERR_INVALID_ENUM`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including every state-transition action — return `200 OK`. All list and single-resource retrievals return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/service-areas` | Create a service area | Dispatcher |
| GET | `/service-areas` | List service areas | Dispatcher, Arborist, FinanceClerk, Client |
| GET | `/service-areas/{id}` | Get a service area | Dispatcher, Arborist, FinanceClerk, Client |
| POST | `/crews` | Register a crew | Dispatcher |
| GET | `/crews` | List crews (filter by service_area_id) | Dispatcher, Arborist, FinanceClerk, Client |
| GET | `/crews/{id}` | Get a crew | Dispatcher, Arborist, FinanceClerk, Client |
| POST | `/crews/{id}/retire` | Retire a crew | Dispatcher |
| POST | `/equipment` | Register an equipment unit | Dispatcher |
| GET | `/equipment` | List equipment (filter by service_area_id) | Dispatcher, Arborist, FinanceClerk, Client |
| GET | `/equipment/{id}` | Get an equipment unit | Dispatcher, Arborist, FinanceClerk, Client |
| POST | `/equipment/{id}/retire` | Retire an equipment unit | Dispatcher |
| POST | `/work-orders` | Create a work order (DRAFT) | Dispatcher, Client |
| GET | `/work-orders` | List work orders (filters available) | Dispatcher, Arborist, FinanceClerk, Client |
| GET | `/work-orders/{id}` | Get a work order | Dispatcher, Arborist, FinanceClerk, Client |
| POST | `/work-orders/{id}/assess` | Run hazard assessment; DRAFT to ASSESSED | Arborist |
| POST | `/work-orders/{id}/complete` | Complete the job; SCHEDULED to COMPLETED | Dispatcher |
| POST | `/work-orders/{id}/cancel` | Cancel the job; cascades release/void/supersede | Dispatcher |
| POST | `/work-orders/{id}/trees` | Add a tree to a DRAFT work order | Arborist, Dispatcher |
| GET | `/work-orders/{id}/trees` | List trees on a work order | Dispatcher, Arborist, FinanceClerk, Client |
| GET | `/work-orders/{id}/trees/{treeId}` | Get a tree | Dispatcher, Arborist, FinanceClerk, Client |
| POST | `/work-orders/{id}/estimates` | Create a DRAFT estimate | Arborist |
| GET | `/work-orders/{id}/estimates` | List estimates on a work order | Dispatcher, Arborist, FinanceClerk, Client |
| GET | `/work-orders/{id}/estimates/{estimateId}` | Get an estimate | Dispatcher, Arborist, FinanceClerk, Client |
| POST | `/work-orders/{id}/estimates/{estimateId}/issue` | Issue estimate; DRAFT to ISSUED (work order to QUOTED) | Arborist |
| POST | `/work-orders/{id}/estimates/{estimateId}/accept` | Client accepts estimate; work order to SCHEDULED | Client |
| POST | `/work-orders/{id}/estimates/{estimateId}/decline` | Client declines estimate; ISSUED to DECLINED | Client |
| POST | `/line-items` | Add a line item to a DRAFT estimate | Arborist |
| GET | `/line-items` | List line items (filter by estimate_id, tree_asset_id) | Dispatcher, Arborist, FinanceClerk, Client |
| GET | `/line-items/{id}` | Get a line item | Dispatcher, Arborist, FinanceClerk, Client |
| POST | `/work-orders/{id}/permits` | Create a DRAFT permit application | Arborist |
| GET | `/work-orders/{id}/permits` | List permits on a work order | Dispatcher, Arborist, FinanceClerk, Client |
| GET | `/work-orders/{id}/permits/{permitId}` | Get a permit | Dispatcher, Arborist, FinanceClerk, Client |
| POST | `/work-orders/{id}/permits/{permitId}/submit` | Submit/resubmit permit; to UNDER_REVIEW | Arborist |
| POST | `/work-orders/{id}/permits/{permitId}/request-changes` | Request changes; to CHANGES_REQUESTED | Dispatcher |
| POST | `/work-orders/{id}/permits/{permitId}/decide` | Decide permit; to APPROVED or DENIED | Dispatcher |
| POST | `/bookings` | Reserve a crew or equipment window (OCC) | Dispatcher |
| GET | `/bookings` | List bookings (filters available) | Dispatcher, Arborist, FinanceClerk, Client |
| GET | `/bookings/{id}` | Get a booking | Dispatcher, Arborist, FinanceClerk, Client |
| POST | `/bookings/{id}/finalize` | Finalize a booking with metered hours; to FINALIZED | Dispatcher |
| POST | `/bookings/{id}/release` | Release a reserved booking; to RELEASED | Dispatcher |
| POST | `/work-orders/{id}/disposal-tickets` | Record a debris disposal ticket | Dispatcher, FinanceClerk |
| GET | `/work-orders/{id}/disposal-tickets` | List disposal tickets on a work order | Dispatcher, Arborist, FinanceClerk, Client |
| GET | `/work-orders/{id}/disposal-tickets/{ticketId}` | Get a disposal ticket | Dispatcher, Arborist, FinanceClerk, Client |
| POST | `/work-orders/{id}/disposal-tickets/{ticketId}/finalize` | Finalize disposal ticket; to FINALIZED | FinanceClerk |
| POST | `/work-orders/{id}/disposal-tickets/{ticketId}/void` | Void a recorded disposal ticket; to VOIDED | FinanceClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_AUTH` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SERVICE_AREA_NOT_FOUND` | 404 |
| `ERR_CREW_NOT_FOUND` | 404 |
| `ERR_EQUIPMENT_NOT_FOUND` | 404 |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 |
| `ERR_TREE_NOT_FOUND` | 404 |
| `ERR_ESTIMATE_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_BOOKING_NOT_FOUND` | 404 |
| `ERR_DISPOSAL_TICKET_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_INVALID_TIME_WINDOW` | 400 |
| `ERR_RESOURCE_KIND_MISMATCH` | 400 |
| `ERR_INVALID_ACTUAL_HOURS` | 400 |
| `ERR_STALE_WORK_ORDER_VERSION` | 412 |
| `ERR_WORK_ORDER_TERMINAL` | 409 |
| `ERR_WORK_ORDER_NOT_SCHEDULED` | 409 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_NO_TREES_ASSESSED` | 409 |
| `ERR_ESTIMATE_NOT_DRAFT` | 409 |
| `ERR_ESTIMATE_NOT_ISSUED` | 409 |
| `ERR_ESTIMATE_EMPTY` | 409 |
| `ERR_PERMIT_NOT_REQUIRED` | 409 |
| `ERR_BOOKING_NOT_RESERVED` | 409 |
| `ERR_TICKET_NOT_RECORDED` | 409 |
| `ERR_OPEN_BOOKINGS` | 409 |
| `ERR_OPEN_DISPOSAL` | 409 |
| `ERR_RESOURCE_HAS_RESERVATIONS` | 409 |
| `ERR_UTILITY_CLEARANCE_REQUIRED` | 422 |
| `ERR_PERMIT_REQUIRED` | 422 |
| `ERR_CREW_DOUBLE_BOOKED` | 409 |
| `ERR_EQUIPMENT_DOUBLE_BOOKED` | 409 |
| `ERR_RESOURCE_REGION_MISMATCH` | 422 |
