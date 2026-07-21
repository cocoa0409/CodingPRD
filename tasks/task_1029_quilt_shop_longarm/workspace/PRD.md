# Quilt Shop & Longarm Service API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Quilt Shop & Longarm Service API, the operational backbone of a full-service quilting retailer. The business spans several intertwined activities: fabric is sold from bolts and cut by the yard; curated kits, bill-of-materials bundles, and block-of-the-month subscriptions are assembled from those bolts; a longarm-quilting studio takes customer quilt tops, schedules them onto machines, and prices the finishing work; classes and multi-day retreats are taught; and a loyalty club rewards members for the money they spend. Special orders let staff source items a customer wants that the shop does not stock.

The API must hold all of these threads together consistently. Fabric inventory has to stay accurate as yardage is cut, voided, restocked, and discontinued, and the availability of a kit depends on whether its component bolts are still carried. Longarm pricing is computed twice — once as an estimate when a job is taken in, and once as a final charge once the finished quilt is measured — and completing a job, fulfilling a special order, or enrolling in a class all move a member's loyalty balance and tier. Because staff frequently re-quote special orders as vendor prices firm up, the system must protect a quote from being overwritten on the basis of a stale reading. The sections below define the global contract every endpoint honors, the business workflows that drive each entity through its lifecycle, the full endpoint list, and the catalogue of error codes.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that every endpoint obeys.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly three roles, spelled precisely: `Member`, `Clerk`, and `Manager`. If either header is missing, or if `X-User-Role` is not one of these three values, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The roles form an escalating capability ladder. A `Member` is a club customer who may create and manage only their own longarm jobs, class enrollments, and special orders, and who may read any resource through the GET endpoints. A `Clerk` is shop staff who run inventory, the cutting counter, the longarm queue, classes, and the special-order desk. A `Manager` can do everything a `Clerk` can do, and is additionally the only role permitted to discontinue a fabric bolt.

The `Member` role is entity-backed: when `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`, and ownership checks compare a resource's `member_id` to `X-User-ID`. Specifically, when a `Member` creates or acts on a longarm job, an enrollment, or a special order, the `member_id` recorded on (or referenced by) that resource must equal the caller's `X-User-ID`; a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. The `Clerk` and `Manager` roles are opaque: when `X-User-Role` is `Clerk` or `Manager`, `X-User-ID` is an operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`. Staff acting in these roles are not subject to the ownership check and may act on any member's resources.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and callers may set it no lower than 1 and no higher than 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless otherwise stated, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. Each list response reports pagination state in the `meta` object through the `limit`, `offset`, `total_count`, and `has_more` fields.

### 2.4. Common Resource Properties and Versioning

Every primary resource carries a system-managed `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp — refreshed on every mutation, in the same format — and an integer `version` that begins at 1 and increments by one on each mutation of the resource.

There is one deliberate exception. A `LoyaltyTransaction` is an append-only ledger row: it carries only `id` and `created_at`, and has neither `updated_at` nor `version`. Ledger rows are never modified once written; corrections are made only by appending further rows. All other entities in this system — `Member`, `FabricBolt`, `FabricCut`, `Kit`, `LongarmMachine`, `LongarmJob`, `ClassEvent`, `Enrollment`, and `SpecialOrder` — carry the full `id`/`created_at`/`updated_at`/`version` set.

### 2.5. Request Validation Order

When a request could fail more than one check, the checks are evaluated in a fixed priority order, and the first failure determines the error returned:

1. **Authentication.** The `X-User-ID` and `X-User-Role` headers must be present and the role must be one of `Member`, `Clerk`, or `Manager`; otherwise `ERR_UNAUTHENTICATED` (401).
2. **Authorization.** The role must be permitted for the operation per §2.1; otherwise `ERR_FORBIDDEN` (403).
3. **Existence.** Every identifier referenced in the path or the request body — whether it is a path id or a foreign key in the body — must resolve to an existing row. References are checked left to right, and the first unresolved reference yields the corresponding not-found error (for example `ERR_MEMBER_NOT_FOUND`, `ERR_BOLT_NOT_FOUND`, `ERR_CUT_NOT_FOUND`, `ERR_KIT_NOT_FOUND`, `ERR_MACHINE_NOT_FOUND`, `ERR_JOB_NOT_FOUND`, `ERR_CLASS_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, or `ERR_SPECIAL_ORDER_NOT_FOUND`), each returned with HTTP 404.
4. **Ownership.** For a `Member`-role write to a longarm job, an enrollment, or a special order, the resource's `member_id` must equal `X-User-ID`; otherwise `ERR_NOT_RESOURCE_OWNER` (403).
5. **State precondition.** The target resource must be in a state that permits the operation (the state machines in §3 spell these out); otherwise a 409 conflict specific to the transition, such as `ERR_BOLT_DISCONTINUED`, `ERR_JOB_NOT_QUEUED`, `ERR_JOB_NOT_IN_PROGRESS`, `ERR_MACHINE_UNAVAILABLE`, `ERR_CLASS_NOT_OPEN`, `ERR_ENROLLMENT_NOT_ACTIVE`, `ERR_SPECIAL_ORDER_NOT_QUOTED`, or `ERR_CUT_NOT_VOIDABLE`.
6. **Field-shape constraints.** Required fields must be present and well-typed, enum fields must carry a recognized member, and quantities that must be positive (a cut's `yards_requested`, an order's `quantity`, measured dimensions, a class `capacity`, and unit costs) must be greater than zero; violations yield `ERR_NON_POSITIVE_AMOUNT` for a non-positive numeric amount or `ERR_VALIDATION` for a missing field, wrong type, or invalid enum member, both with HTTP 422.
7. **Interval validity and resource overlap.** Time windows must be well-formed and non-overlapping where required, yielding `ERR_INVALID_TIME_WINDOW`, `ERR_MACHINE_SCHEDULE_CONFLICT`, or `ERR_MEMBER_SCHEDULE_CONFLICT` (all 409), as described in §3.
8. **Duplicate enrollment.** A member may not hold two active enrollments in the same class; a second attempt yields `ERR_DUPLICATE_ENROLLMENT` (409).
9. **Capacity and quota.** Fabric yardage and class seats must be sufficient, yielding `ERR_INSUFFICIENT_YARDAGE` or `ERR_CLASS_FULL` (both 409).
10. **Optimistic concurrency.** Where an operation carries an expected version, it must match the current version; otherwise `ERR_STALE_VERSION` (412).

This ordering is normative: a state-precondition failure (priority 5) is reported before a field-shape failure (priority 6), and the optimistic-concurrency check (priority 10) is the last check applied.

### 2.6. Monetary Precision, Rounding, and Point Accrual

All prices and monetary totals are decimal dollar amounts. Wherever a formula in §3 specifies rounding, the amount is rounded to exactly two decimal places using the round-half-up convention, and — unless a formula explicitly pins an earlier rounding step — that rounding is applied once, to the final figure. Two calculations pin an intermediate rounding step and are called out where they appear: a kit's per-component line amounts are each rounded before they are summed, and a fabric cut's line price is rounded at the moment of the cut.

Fabric yardage is tracked exactly as a decimal quantity; the running total of remaining yards on a bolt is never rounded. Loyalty points, by contrast, are whole numbers. Whenever points are earned, the raw amount is the dollar figure that drives the award multiplied by ten points per dollar, and that product is floored to the nearest whole number of points before it is recorded. Point reversals carry the negative of the exact whole-number magnitude that was originally granted.

### 2.7. Optimistic Concurrency on Special-Order Revisions

Revising a special order's quote is guarded by optimistic concurrency control. A revise-quote request must carry `expected_special_order_version`, the `version` of the `SpecialOrder` that the client last observed. Because each revision supersedes the prior quote and advances the order's `version`, a request whose `expected_special_order_version` does not equal the order's current `version` means another revision has already moved the order forward since the client read it; such a request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a quote it never saw. This is the only endpoint that takes a version field; no other operation requires or accepts one.

### 2.8. Derived-Field Reconciliation and Cascade Consistency

Several fields are read-only and are recomputed by the server rather than supplied by clients — a bolt's `yards_remaining` and `status`, a member's `points_balance` and `loyalty_tier`, a class's `seats_taken` and `status`, a kit's `materials_cost`, `kit_price`, and `status`, and the priced fields on jobs and orders. Whenever an operation changes an input those fields depend on, the server reconciles the derived fields immediately, in the same request, so a returned resource always reflects the current state.

Some operations cascade across entities. Discontinuing a bolt not only sets that bolt terminal but also marks every kit that lists the bolt among its components as unavailable. Cancelling a class cancels each of its confirmed enrollments, and each enrollment cancellation in turn reverses that member's loyalty and recomputes the member's balance and tier. Completing a longarm job and fulfilling a special order each append a loyalty ledger row and then recompute the owning member's balance and tier. Every entity that is mutated in the course of such a cascade has its own `updated_at` refreshed and its own `version` incremented; a reconciliation that changes a resource is a mutation of that resource.

### 2.9. The Loyalty Ledger

Loyalty is implemented as an append-only ledger. Each `LoyaltyTransaction` records the `member_id` it belongs to, a signed integer `points` delta (positive for an award, negative for a reversal), a `reason` drawn from `ENROLLMENT_CONFIRM`, `ENROLLMENT_CANCEL_REVERSAL`, `SPECIAL_ORDER_FULFILL`, and `LONGARM_COMPLETE`, and a `source_type`/`source_id` pair that labels the originating entity type (`Enrollment`, `SpecialOrder`, or `LongarmJob`) and its id. The `source_type` and `source_id` are descriptive back-references, not canonical foreign keys.

A member's `points_balance` is always the signed sum of every one of that member's ledger rows, with no filtering by reason or sign — reversals net directly against awards. It starts at zero for a new member and is recomputed from the ledger on every loyalty mutation. The `loyalty_tier` is derived from that balance: `BRONZE` while the balance is below 1,000 points, `SILVER` once the balance reaches 1,000 but remains below 5,000, and `GOLD` once the balance reaches 5,000 or more. A new member starts at `BRONZE`.

## 3. Business Logic & Workflows

### 3.1. Membership and the Loyalty Program

A member record is opened by staff — a `Clerk` or a `Manager` — who supply the member's `name`, `email`, and optionally a `phone` number (which may be omitted and defaults to absent). The `email` must be unique across members; a collision is a field-shape validation failure. A newly created member begins with a `points_balance` of zero and therefore a `loyalty_tier` of `BRONZE`; both are read-only and are maintained entirely by the system.

The loyalty balance moves only through ledger activity, never by direct edit. As described in §2.9, the balance is the running signed sum of the member's ledger rows, and the tier follows the balance across its two thresholds. Anyone — the member themselves or staff — may read a member record, and a member's full ledger history is retrievable as a list of that member's loyalty rows, ordered by creation time and paginated with `limit` and `offset`. The three award reasons and the one reversal reason are all exercised by the workflows that follow.

### 3.2. Fabric Bolt Inventory and the Cutting Counter

Fabric arrives on bolts. Staff register a `FabricBolt` with its `sku`, its `color` (the print or color name), a `price_per_yard`, and the `original_yards` loaded onto the bolt, and may set a `reorder_threshold` that defaults to 5 yards. On creation the bolt's `yards_remaining` is initialized to its `original_yards`, and its `status` is derived from the stock levels below — normally `IN_STOCK`.

A bolt's `yards_remaining` is always its `original_yards` minus the total `yards_requested` across all of its cuts that remain in `CUT` status; voided cuts are excluded from that sum, and the remaining total is kept exact without rounding. The bolt's `status` is reconciled from this figure after every cut, void, restock, or discontinuation. While remaining yardage sits above the reorder threshold the bolt is `IN_STOCK`; when it falls to the threshold or below while still greater than zero it becomes `LOW_STOCK`; and when it reaches exactly zero it becomes `DEPLETED`. These transitions are symmetric: adding yardage back can lift a `DEPLETED` bolt to `LOW_STOCK` (when remaining yardage is above zero but still at or below the threshold) or to `IN_STOCK` (when it rises strictly above the threshold), and can lift a `LOW_STOCK` bolt back to `IN_STOCK` once remaining yardage exceeds the threshold.

Restocking a bolt adds an `added_yards` amount: both `original_yards` and `yards_remaining` increase by that amount, and the status is recomputed. A `Manager` — and only a `Manager` — may discontinue a bolt, driving it to the terminal `DISCONTINUED` state. Discontinuation is allowed from any of the stock states; attempting it on a bolt that is already `DISCONTINUED` is rejected with `ERR_BOLT_DISCONTINUED`. Discontinuing a bolt cascades: every kit whose component list references that bolt is marked `UNAVAILABLE`, and each affected kit is itself mutated (its `updated_at` and `version` advance).

Cutting is the core counter operation, performed by staff. A cut names the `bolt_id` to draw from, the `yards_requested` to cut, and optionally a `member_id` for a club customer — a walk-in leaves `member_id` absent. The requested yardage must be greater than zero, the bolt must not be `DISCONTINUED` (otherwise `ERR_BOLT_DISCONTINUED`), and the bolt must have at least the requested yardage remaining, or the cut is refused with `ERR_INSUFFICIENT_YARDAGE`. A successful cut is recorded in `CUT` status, its `line_price` is computed as the requested yards multiplied by the bolt's `price_per_yard`, rounded half-up to two decimal places at the moment of the cut, and the bolt's remaining yardage and status are reconciled. Cuts can be listed and filtered by `bolt_id`, by `member_id`, or by `status`. A cut may be voided by staff only while it is in `CUT` status; a void attempt on a cut that is not currently `CUT` is rejected with `ERR_CUT_NOT_VOIDABLE`. Voiding moves the cut to `VOIDED`, returns its `yards_requested` to the bolt's remaining yardage, and reconciles the bolt's status.

### 3.3. Kits, Bill-of-Materials Bundles, and Blocks of the Month

Staff assemble curated products by combining bolts. A `Kit` carries a `name`, a `kit_type` that is one of `KIT`, `BOM`, or `BLOCK_OF_MONTH`, and a `components` list. Each component names a `bolt_id`, the `yards_per_kit` that product consumes from that bolt, and a `quantity` of that component in the kit; every referenced `bolt_id` must resolve to an existing bolt.

A kit's `materials_cost` and `kit_price` are computed at creation and on any later recompute. The materials cost is built component by component: for each component the system takes its `yards_per_kit` times the referenced bolt's current `price_per_yard`, rounds that line to two decimal places, multiplies the rounded line by the component's `quantity`, and adds the result into the running materials cost. This per-line rounding happens before the components are summed — the rounding order is pinned as round-then-sum, not sum-then-round. The `kit_price` is then the finished `materials_cost` multiplied by a kit markup of 1.4, rounded half-up to two decimal places. A kit is `AVAILABLE` on creation and remains so until one of its component bolts is discontinued, at which point the discontinuation cascade of §3.2 flips the kit to `UNAVAILABLE`.

### 3.4. The Longarm Quilting Queue

The longarm studio finishes customer quilt tops on a set of machines. A `LongarmMachine` is registered with a `name` label and a `model`; its `status` may be supplied at creation and otherwise defaults to `AVAILABLE`, the alternative value being `MAINTENANCE`.

A quilt owner — a member acting for themselves, or staff acting on their behalf — takes in a `LongarmJob` by supplying the `member_id`, the quoted quilt dimensions `quoted_width_in` and `quoted_length_in`, and a `pattern_tier` of `EDGE_TO_EDGE`, `CUSTOM`, or `HEIRLOOM`. Three optional booleans, each defaulting to false, capture add-ons: `batting_addon` for the batting service, `thread_addon` for specialty thread, and `rush` for expedited handling. Intake computes an `estimated_price` and places the job in `QUEUED`. When a member takes in their own job the `member_id` must match their `X-User-ID`, per §2.1.

Longarm pricing runs over a single job's area and is computed in two variants that share one formula. The area is the width multiplied by the length, in square inches. The base charge is the area multiplied by the per-square-inch rate for the job's pattern tier: $0.02 for `EDGE_TO_EDGE`, $0.035 for `CUSTOM`, and $0.05 for `HEIRLOOM`. If the area is strictly greater than 7,500 square inches, the base charge is then multiplied by a large-quilt surcharge factor of 1.1. Starting from that base as the running subtotal, a flat $25 batting fee is added when `batting_addon` is set, and a flat $12 specialty-thread fee is added when `thread_addon` is set. If `rush` is set, the resulting subtotal is then multiplied by 1.25. The price is the greater of that subtotal and a $30 minimum charge, and finally it is rounded half-up to two decimal places — a single rounding applied once at the very end. The **estimate** variant runs this formula over the quoted dimensions to produce `estimated_price` at intake. The **final** variant runs the identical formula over the measured dimensions to produce `final_price` at completion, and it diverges from the estimate whenever the measured dimensions differ from the quoted ones.

Staff start a queued job by assigning it to a machine and a time slot: the request carries the `machine_id`, a `scheduled_start`, and a `scheduled_end`. Starting a job is permitted only while the job is `QUEUED` (otherwise `ERR_JOB_NOT_QUEUED`). The referenced machine must exist (otherwise `ERR_MACHINE_NOT_FOUND`) and must be `AVAILABLE` rather than in `MAINTENANCE` (otherwise `ERR_MACHINE_UNAVAILABLE`). The slot's `scheduled_end` must be strictly later than its `scheduled_start` (otherwise `ERR_INVALID_TIME_WINDOW`). Finally, the requested slot must not collide, within a fixed setup buffer of 30 minutes (`SETUP_BUFFER_MINUTES` = 30), on the same machine, with the slot of any other job on that machine that is in `IN_PROGRESS` or `COMPLETED` status; a collision is rejected with `ERR_MACHINE_SCHEDULE_CONFLICT`. Concretely, two slots on the same machine collide unless they are separated by a gap of at least 30 minutes: if the later slot's `scheduled_start` is fewer than 30 minutes after the earlier slot's `scheduled_end` (or the intervals overlap outright), the request conflicts; a gap of exactly 30 minutes or more is allowed. For example, an existing slot ending at 12:00 and a new slot starting at 12:15 have only a 15-minute gap and therefore conflict, whereas a new slot starting at 12:30 is accepted. A successful start records the `machine_id`, `scheduled_start`, and `scheduled_end` on the job (the `machine_id` is null until this point) and advances it from `QUEUED` to `IN_PROGRESS`.

Completing a job records the finished measurements. Staff supply `measured_width_in` and `measured_length_in`, both of which must be greater than zero (otherwise `ERR_NON_POSITIVE_AMOUNT`); completion is permitted only while the job is `IN_PROGRESS` (otherwise `ERR_JOB_NOT_IN_PROGRESS`). On completion the measured dimensions are stored, the `final_price` is computed via the final pricing variant over those measured dimensions (it remains null until this point), and the job advances from `IN_PROGRESS` to the terminal `COMPLETED`. Completion also awards loyalty: the system appends a `LoyaltyTransaction` for the job's member with `reason` `LONGARM_COMPLETE` and a `points` award equal to the final price times ten points per dollar, floored to a whole number, and then recomputes the member's `points_balance` and `loyalty_tier`. Jobs may be listed and filtered by `member_id`, by `machine_id`, or by `status`.

### 3.5. Classes, Retreats, and Enrollment

Staff schedule teaching events. A `ClassEvent` is created with a `title`, an `event_type` of either `CLASS` or `RETREAT`, an `instructor` name, a `start_time` and `end_time`, a `capacity`, and a `fee`. The `end_time` must be strictly later than the `start_time` (otherwise `ERR_INVALID_TIME_WINDOW`), and `capacity` must be greater than zero. A new event opens immediately in `OPEN` status with `seats_taken` of zero.

A class's `seats_taken` is always the count of its enrollments in `CONFIRMED` status; cancelled enrollments do not count. The event's `status` tracks this count against `capacity`: it flips from `OPEN` to `FULL` the moment confirmed seats equal capacity, and back from `FULL` to `OPEN` when a cancellation drops confirmed seats below capacity — the latter only while the event has not itself been cancelled. Staff may cancel an event while it is `OPEN` or `FULL` (otherwise `ERR_CLASS_NOT_OPEN`), which moves it to the terminal `CANCELLED` state and cascades: every enrollment currently `CONFIRMED` on that event is cancelled, and each of those cancellations runs its own loyalty reversal (below).

Enrolling puts a member into a class, and may be initiated by the member for themselves or by staff. The request names the `class_event_id` and the `member_id`; when a member enrolls themselves the `member_id` must equal their `X-User-ID`. Enrollment is refused if the class is not accepting enrollments — it must be `OPEN` (a class already at capacity is `FULL`, and enrolling into a full class is rejected with `ERR_CLASS_FULL`). A member may not hold two active enrollments in the same class; a duplicate confirmed enrollment is rejected with `ERR_DUPLICATE_ENROLLMENT`. Nor may a member be enrolled into a class whose time window overlaps that of another class in which they already hold a `CONFIRMED` enrollment; such an overlap is rejected with `ERR_MEMBER_SCHEDULE_CONFLICT`. A successful enrollment is recorded as `CONFIRMED`, and it earns loyalty at once: its `points_earned` is the class `fee` times ten points per dollar, floored to a whole number, and a `LoyaltyTransaction` with `reason` `ENROLLMENT_CONFIRM` is appended for that amount before the member's balance and tier are recomputed. The class's `seats_taken` is then incremented, tipping the class to `FULL` if it has reached capacity.

An enrollment can be cancelled — by the member who owns it or by staff — while it is `CONFIRMED`; cancelling one that is already `CANCELLED` is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`. Cancellation moves the enrollment to the terminal `CANCELLED` state and reverses its loyalty: a `LoyaltyTransaction` with `reason` `ENROLLMENT_CANCEL_REVERSAL` is appended for the negative of the enrollment's original `points_earned`, and the member's balance and tier are recomputed. The class's `seats_taken` is then recomputed, and if the class was `FULL` and now sits below capacity it returns to `OPEN` — except when the class itself has been cancelled, in which case it stays terminal. This same reversal-and-recompute sequence runs for each enrollment swept up in a class cancellation. Enrollments may be listed and filtered by `member_id`, by `class_event_id`, or by `status`.

### 3.6. Special Orders and the Re-Quote Loop

When a customer wants something the shop does not stock, staff or the member open a `SpecialOrder`. It names the `member_id` it is for, a free-text `description`, a `quantity` (which must be greater than zero), and an estimated vendor `est_unit_cost` per unit. Creating the order computes a `quoted_price` and places it in `QUOTED` status with `version` 1; when a member opens their own order the `member_id` must equal their `X-User-ID`.

Special-order pricing has two variants. The **estimate** variant, used at creation and on every re-quote, sets `quoted_price` to the estimated unit cost times the `quantity` times a special-order markup of 1.5, rounded half-up to two decimal places; it excludes shipping. The **final** variant, used at fulfillment, sets `final_total` to the actual unit cost times the `quantity` times that same 1.5 markup, plus the shipping cost, rounded half-up to two decimal places; `final_total` is null until the order is fulfilled and diverges from the quoted price whenever the actual unit cost differs from the estimate or any shipping is charged.

Because vendor prices firm up over several rounds of negotiation, staff re-quote an order in place — a self-transition that keeps it in `QUOTED` while replacing the numbers. A re-quote supplies a new `est_unit_cost`, a new `quantity`, and the `expected_special_order_version` that guards the update. Re-quoting is permitted only while the order is `QUOTED` (otherwise `ERR_SPECIAL_ORDER_NOT_QUOTED`); the new `quantity` must be greater than zero (otherwise `ERR_NON_POSITIVE_AMOUNT`); and `expected_special_order_version` must match the order's current `version` or the request is rejected as stale with `ERR_STALE_VERSION`, per §2.7. A successful re-quote replaces the stored `est_unit_cost` and `quantity`, recomputes `quoted_price` under the estimate variant, and increments the order's `version` by one — so each accepted revision advances the version the next re-quote must present.

Fulfilling an order closes it out. Staff record the `actual_unit_cost` (which must be greater than zero, otherwise `ERR_NON_POSITIVE_AMOUNT`) and an optional `shipping_cost` that defaults to zero. Fulfillment is permitted only while the order is `QUOTED` (otherwise `ERR_SPECIAL_ORDER_NOT_QUOTED`). It stores the actual cost and shipping, computes `final_total` under the final variant, and advances the order from `QUOTED` to the terminal `FULFILLED` state. Fulfillment also awards loyalty: a `LoyaltyTransaction` with `reason` `SPECIAL_ORDER_FULFILL` is appended for the member, with a `points` award equal to the final total times ten points per dollar, floored to a whole number, after which the member's `points_balance` and `loyalty_tier` are recomputed. Special orders may be listed and filtered by `member_id` or by `status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read a resource or a list, or that modify or transition an existing resource, return `200 OK`. An "Any" authorization below means all three roles — `Member`, `Clerk`, and `Manager` — are permitted.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/members` | Create a member | Clerk, Manager |
| GET | `/api/members/{id}` | Get a member | Any |
| GET | `/api/members/{id}/loyalty-transactions` | List a member's loyalty ledger rows | Any |
| POST | `/api/fabric-bolts` | Create a fabric bolt | Clerk, Manager |
| GET | `/api/fabric-bolts/{id}` | Get a fabric bolt | Any |
| POST | `/api/fabric-bolts/{id}/restock` | Add yardage to a bolt | Clerk, Manager |
| POST | `/api/fabric-bolts/{id}/discontinue` | Discontinue a bolt | Manager |
| POST | `/api/fabric-cuts` | Cut yardage from a bolt | Clerk, Manager |
| GET | `/api/fabric-cuts` | List cuts, filterable by bolt/member/status | Any |
| GET | `/api/fabric-cuts/{id}` | Get a cut | Any |
| POST | `/api/fabric-cuts/{id}/void` | Void a cut and restore yardage | Clerk, Manager |
| POST | `/api/kits` | Create a kit / BOM / block-of-month | Clerk, Manager |
| GET | `/api/kits/{id}` | Get a kit | Any |
| POST | `/api/longarm-machines` | Create a longarm machine | Clerk, Manager |
| GET | `/api/longarm-machines/{id}` | Get a longarm machine | Any |
| POST | `/api/longarm-jobs` | Intake a longarm job (computes the estimate) | Any |
| GET | `/api/longarm-jobs` | List longarm jobs, filterable by member/machine/status | Any |
| GET | `/api/longarm-jobs/{id}` | Get a longarm job | Any |
| POST | `/api/longarm-jobs/{id}/start` | Assign a machine + time slot and begin the job | Clerk, Manager |
| POST | `/api/longarm-jobs/{id}/complete` | Record measured dims, compute final price, complete | Clerk, Manager |
| POST | `/api/classes` | Create a class or retreat | Clerk, Manager |
| GET | `/api/classes/{id}` | Get a class | Any |
| POST | `/api/classes/{id}/cancel` | Cancel a class and cascade-cancel its enrollments | Clerk, Manager |
| POST | `/api/enrollments` | Enroll a member in a class | Any |
| GET | `/api/enrollments` | List enrollments, filterable by member/class/status | Any |
| GET | `/api/enrollments/{id}` | Get an enrollment | Any |
| POST | `/api/enrollments/{id}/cancel` | Cancel an enrollment and reverse loyalty | Any |
| POST | `/api/special-orders` | Create a special order (computes the quote) | Any |
| GET | `/api/special-orders` | List special orders, filterable by member/status | Any |
| GET | `/api/special-orders/{id}` | Get a special order | Any |
| POST | `/api/special-orders/{id}/revise-quote` | Re-quote a special order (OCC-guarded) | Clerk, Manager |
| POST | `/api/special-orders/{id}/fulfill` | Fulfill a special order (records actuals, final total) | Clerk, Manager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_BOLT_NOT_FOUND` | 404 |
| `ERR_CUT_NOT_FOUND` | 404 |
| `ERR_KIT_NOT_FOUND` | 404 |
| `ERR_MACHINE_NOT_FOUND` | 404 |
| `ERR_JOB_NOT_FOUND` | 404 |
| `ERR_CLASS_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_SPECIAL_ORDER_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_NON_POSITIVE_AMOUNT` | 422 |
| `ERR_INVALID_TIME_WINDOW` | 409 |
| `ERR_BOLT_DISCONTINUED` | 409 |
| `ERR_CUT_NOT_VOIDABLE` | 409 |
| `ERR_JOB_NOT_QUEUED` | 409 |
| `ERR_JOB_NOT_IN_PROGRESS` | 409 |
| `ERR_MACHINE_UNAVAILABLE` | 409 |
| `ERR_CLASS_NOT_OPEN` | 409 |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 |
| `ERR_SPECIAL_ORDER_NOT_QUOTED` | 409 |
| `ERR_MACHINE_SCHEDULE_CONFLICT` | 409 |
| `ERR_MEMBER_SCHEDULE_CONFLICT` | 409 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_INSUFFICIENT_YARDAGE` | 409 |
| `ERR_CLASS_FULL` | 409 |
| `ERR_STALE_VERSION` | 412 |
