# Shoe, Leather & Watch Repair API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Shoe, Leather & Watch Repair API, the system of record for a multi-trade repair shop that takes in customer items, quotes and revises repair work, orders the parts that work depends on, completes the repair against a promised turnaround, and returns the finished item to its owner. The shop services three families of goods — footwear, leather goods, and timepieces — and each family is handled by technicians qualified for it, against a catalog of priced service types that carry their own turnaround and warranty terms.

The operational heart of the system is a single repair ticket that travels a long, sometimes looping path: intake, estimate, customer approval (or a rejection that sends the estimate back for revision), parts procurement, hands-on repair, a ready-for-pickup promise measured against a service-level deadline, and finally pickup — or, if the customer never returns, an unclaimed-item warning and eventual disposal. Two financial disciplines run underneath the whole lifecycle: a provisional-versus-final pricing engine that re-prices the job at the moment of completion using only the work actually done, and a warranty program that lets a customer report a failed repair and obtain a no-charge redo. Because several staff members may touch the same ticket in close succession, the system applies optimistic concurrency control at the two points where a stale read would corrupt money or the estimate chain, and it enforces a segregation-of-duties rule so that the technician who priced a job cannot also sit in judgment of a warranty complaint about it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint. Where a rule below references a specific business event, the full workflow detail lives in §3.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH_CONTEXT`. The system recognizes exactly four roles, spelled precisely as follows: `FrontDeskClerk`, `RepairTechnician`, `ShopManager`, and `Customer`. When a syntactically valid request is made by a role that is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The four roles differ in how `X-User-ID` relates to persisted data:

- When `X-User-Role` is `RepairTechnician`, `X-User-ID` is the `id` of the acting `Technician`; any ownership or authorship check on a resource that references a `Technician` (for example a ticket's `assigned_technician_id`, an estimate's `authored_by_technician_id`, or a claim's `ruled_by_technician_id`) compares that foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's customer foreign-key field to `X-User-ID`. In particular, approving or rejecting an estimate requires that the acting customer's `id` equal the owning ticket's `customer_id`, and a mismatch is rejected with `ERR_NOT_TICKET_OWNER`.
- When `X-User-Role` is `FrontDeskClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.
- When `X-User-Role` is `ShopManager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

Role authority over individual operations is summarized in §4. As a narrative orientation: a `FrontDeskClerk` owns intake, item logging, ready notifications, payment capture, pickup, and the unclaimed flag; a `RepairTechnician` builds and presents estimates, manages parts, adjusts and completes service lines, and drives the repair forward; a `ShopManager` owns the service catalog and technician roster, cancellations, disposal of unclaimed items, warranty rulings, and the test clock; and a `Customer` approves or rejects their own estimates and files warranty claims on their own tickets.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list response carries the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Server Clock

Most resources in the system carry a standard set of server-managed fields. The `id` is a server-minted UUID with no type prefix; it is identity only and is never supplied by the client. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last modification, and the `version` field is an integer that begins at its initial value and increments by one on every mutation of the resource. These four fields apply to `Customer`, `ServiceType`, `Technician`, `RepairTicket`, `TicketItem`, `ServiceLine`, `Estimate`, `PartsOrder`, and `WarrantyClaim`.

Two entities are append-only audit records and therefore carry only `id` and `created_at`: a `Payment` and a `Notification` have neither an `updated_at` nor a `version` field. A `Payment` does change `state` (from `CAPTURED` to `REFUNDED`) but is not versioned; a `Notification` is immutable once written.

Because turnaround promises, unclaimed windows, and warranty expiry all depend on the passage of time, the system reads "now" from a server-controlled logical clock rather than wall-clock time. A `ShopManager` may advance or set this clock for test-driving by supplying a target instant as `to_iso8601`; the response reports the resulting `now`. Every server-stamped timestamp produced afterward — `drop_off_at`, `ready_at`, `picked_up_at`, and every eligibility comparison — uses this clock.

### 2.5. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against the parent `RepairTicket`, because in both cases acting on a stale view of the ticket would corrupt the estimate chain or the billed amount. On these two operations the client must supply `expected_ticket_version` carrying the `version` of the `RepairTicket` it last observed. If that value does not equal the ticket's current `version`, the request is rejected with `ERR_STALE_TICKET_VERSION` (HTTP 412).

The first guarded operation is presenting an estimate. Presenting an estimate requires `expected_ticket_version` to match the target ticket's current `version`; if another writer has already advanced the ticket's version since the technician last read it — for instance because a competing revision was already presented and moved the ticket out of `INTAKE` or `REVISION_REQUESTED` into `AWAITING_APPROVAL` — the present is rejected with `ERR_STALE_TICKET_VERSION`, so a second technician cannot land a competing estimate over a view that is no longer current.

The second guarded operation is capturing a payment. Capturing a payment requires `expected_ticket_version` to match the target ticket's current `version`; if a mark-ready has refreshed `final_charge_cents` since the clerk last read the ticket, the ticket's version will have advanced, and a payment sized against the pre-recompute charge is rejected with `ERR_STALE_TICKET_VERSION` rather than being taken against a stale balance.

No other endpoint takes a version field; operations not named here proceed without an OCC check.

### 2.6. Money, Cents, and Rounding

All monetary amounts in the system are integer counts of cents — `base_price_cents`, `quoted_price_cents`, `adjusted_price_cents`, `supplier_cost_cents`, `marked_up_cost_cents`, `labor_subtotal_cents`, `parts_subtotal_cents`, `rush_surcharge_cents`, `estimate_total_cents`, `final_charge_cents`, `amount_paid_cents`, and a payment's `amount_cents`. There are no fractional cents stored anywhere. Where a calculation multiplies by a non-integer factor — the parts markup and the rush surcharge — the full product is computed first and then rounded once to the nearest whole cent using the round-half-up convention (a value exactly halfway between two cents rounds up). The specific rounding point for each such calculation is stated with its formula in §3.

### 2.7. Item Families, Catalog Eligibility, and Technician Skills

Three item families organize the whole domain, and every relevant enumeration draws from the same set: an item belongs to one of `SHOE`, `LEATHER`, or `WATCH`. A `ServiceType` declares the `item_category` it applies to from this set; a `TicketItem` declares the `item_category` it belongs to; and a `Technician` carries a `skills` array that is a subset of these three families. When a service line is added, the chosen service type's `item_category` must match the `item_category` of the item the service is performed on, and the service type must still be active; a mismatch or a retired type is rejected with `ERR_INVALID_REQUEST` (see §3 for the exact create rule). A retired service type — one whose `active` flag has been turned off — may not be added to any new service line, though lines created before retirement are unaffected.

### 2.8. State Propagation, Cascades, and Versioning on Mutation

Many operations mutate more than one resource at once. Whenever an operation changes the `RepairTicket` — its `repair_status`, its `notify_status`, a derived total, or any cascade originating from it — the ticket's `version` increments by one and its `updated_at` refreshes. Several operations also drive secondary state changes on child resources (parts, service lines, estimates) or spawn entirely new resources; those secondary effects are detailed in the workflow narratives of §3 and must occur as part of the same operation that triggers them. The two most consequential chains — the cancellation cascade that runs from the ticket down through parts, lines, and the open estimate, and the warranty-approval cascade that spawns a redo ticket — are described in full in §3.4 and §3.6 respectively.

### 2.9. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. The order is: first, authentication — the presence and well-formedness of `X-User-ID` and `X-User-Role` (`ERR_MISSING_AUTH_CONTEXT`); second, role authorization for the operation (`ERR_FORBIDDEN_ROLE`); third, existence of every resource named by a path identifier (the not-found family, e.g. `ERR_TICKET_NOT_FOUND`, `ERR_ESTIMATE_NOT_FOUND`, `ERR_PARTS_ORDER_NOT_FOUND`, `ERR_SERVICE_LINE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_SERVICE_TYPE_NOT_FOUND`, `ERR_TICKET_ITEM_NOT_FOUND`); fourth, resolution of body foreign keys and their cross-entity consistency (`ERR_FK_NOT_FOUND`); fifth, uniqueness constraints on create (`ERR_DUPLICATE_KEY`); sixth, request shape, enum/type/range validity, and catalog eligibility (`ERR_INVALID_REQUEST`); seventh, the optimistic-concurrency version check on the two guarded operations (`ERR_STALE_TICKET_VERSION`); and eighth, the target resource being in the correct state for the requested transition (the invalid-state family). Beyond the eighth rank sit the domain-specific guards — segregation of duties, warranty timing, unclaimed timing, and the balance-due check — which are described where their workflows live in §3. The governing principle is that a cheaper, more general failure is reported before a more specific business failure: a request missing its auth headers never reaches a state check, and a path to a non-existent ticket is reported as not-found before any body validation runs.

### 2.10. Nested Reference Validation

The system uses a flat resource topology: every collection sits at the top level, and parent-child relationships are expressed as foreign-key fields filtered through query parameters rather than through deep URL nesting. When a request carries a path identifier, that resource's existence is checked before any body or state rule (per §2.9). When a create request carries foreign-key references in its body — for example a service line's `ticket_id`, `ticket_item_id`, and `service_type_id`, or a parts order's `ticket_id` and `service_line_id` — each reference must resolve to an existing resource, and where two references must belong to the same ticket they are checked for that consistency; an unresolved or cross-ticket reference is rejected with `ERR_FK_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Catalog, Roster, and Customer Setup

Before any repair can be taken in, the shop's reference data must exist. A `ShopManager` builds the **service catalog** by creating service types, each carrying a `code` that is unique across all service types, a human-readable `name`, the `item_category` it applies to, a `base_price_cents` labor price that must be zero or greater, a `standard_turnaround_days` count of business days to complete at standard priority that must be at least 1, a `warranty_days` coverage window from pickup that must be zero or greater, and a `rush_eligible` flag (defaulting to true) stating whether rush priority may be applied to a ticket containing this service. A new service type is born with its `active` flag true. A manager may later retire a service type, which flips `active` to false; a retired type stays in the catalog and on existing lines but may no longer be added to new service lines. Attempting to create a service type whose `code` already exists is rejected with `ERR_DUPLICATE_KEY`.

The `ShopManager` also maintains the **technician roster**, creating technicians with a `display_name` and a `skills` array drawn from the three item families. A technician is created with `active` true and may be deactivated later, after which `active` is false.

A `FrontDeskClerk` (or a `ShopManager`) registers **customers**, each with a `full_name`, an `email` that is unique across all customers, a `phone` used for SMS notifications, and a `notify_channel` preference that defaults to `EMAIL` and may instead be `SMS`. A customer is created with `status` of `ACTIVE`; an archive action may later set `status` to `ARCHIVED`. A duplicate `email` on creation is rejected with `ERR_DUPLICATE_KEY`.

### 3.2. Intake, Items, and Service Lines

Intake is performed by a `FrontDeskClerk`, who opens a **repair ticket** for a customer by supplying the owning `customer_id` and, optionally, an initial `priority` and an `assigned_technician_id`. A freshly created ticket has its `repair_status` set to `INTAKE`, its `notify_status` set to `NONE`, its `drop_off_at` stamped from the server clock, and its `amount_paid_cents` initialized to 0. The `priority` defaults to `STANDARD` and may be `RUSH`; rush priority applies a surcharge and shortens the promised ready date as described in §3.3 and §3.5. Several ticket fields stay empty at intake and are filled only as the lifecycle advances: `ready_by`, `ready_at`, `sla_breached`, `approved_estimate_id`, `final_charge_cents`, `warranty_expires_at`, and `picked_up_at` are all null or unset until the events that populate them occur. Before approval, a clerk or manager may revise the ticket to set or change its `assigned_technician_id` or its `priority`.

For each physical object dropped off, the clerk logs a **ticket item** referencing the owning `ticket_id`, with its own `item_category`, a free-text `description`, an intake `condition_grade` of `EXCELLENT`, `GOOD`, `FAIR`, or `POOR`, and optional `condition_notes` documenting pre-existing damage (defaulting to an empty string). Documenting condition at intake protects the shop against later disputes.

Each repair task on an item is recorded as a **service line**, which a `FrontDeskClerk` or `RepairTechnician` creates by referencing the owning `ticket_id`, the `ticket_item_id` the work is performed on, and the catalog `service_type_id`. The chosen service type must be active and its `item_category` must match the referenced item's `item_category`; otherwise the create is rejected with `ERR_INVALID_REQUEST`. On creation the line takes status `QUOTED` and snapshots its `quoted_price_cents` from the service type's `base_price_cents` at that moment, freezing the price against later catalog changes. A line also carries an `adjusted_price_cents` that is null until a technician overrides it during repair; when present it must be zero or greater. A line's `status` is one of `QUOTED`, `COMPLETED`, or `VOIDED`.

### 3.3. Estimating and the Revision Loop

A `RepairTechnician` prices the job by drafting an **estimate** against a `ticket_id`, recording the `authored_by_technician_id` who built it and, when the estimate is a revision, the `supersedes_estimate_id` of the prior estimate it replaces. A first estimate leaves `supersedes_estimate_id` null and is assigned `revision_number` 1; a revision takes the prior estimate's `revision_number` plus one. A new estimate is created in status `DRAFT`, and its totals — `labor_subtotal_cents`, `parts_subtotal_cents`, `rush_surcharge_cents`, and `estimate_total_cents` — are computed at draft time using the provisional variant of the totals engine described in §3.5.

Presenting a draft estimate to the customer is the event that moves the ticket from intake into the approval cycle. A technician presents an estimate only when the estimate is in `DRAFT` and its owning ticket is in `INTAKE` or `REVISION_REQUESTED`; this operation is guarded by the optimistic-concurrency check on the ticket (§2.5), so the request must carry `expected_ticket_version` matching the ticket's current `version`, failing with `ERR_STALE_TICKET_VERSION` if it does not. Presenting additionally requires that at least one non-`VOIDED` service line exist on the ticket, failing with `ERR_NO_SERVICE_LINES` otherwise. A successful present moves the estimate from `DRAFT` to `PRESENTED`, advances the ticket's `repair_status` to `AWAITING_APPROVAL`, recomputes the estimate totals under the provisional variant, and appends an `ESTIMATE_PRESENTED` notification. When the estimate being presented is a revision, the present is valid only if its `supersedes_estimate_id` points at the ticket's most recent `REJECTED` estimate; a revision that cites the wrong predecessor is rejected with `ERR_BAD_REVISION_CHAIN`. A valid revision present also transitions that most recent rejected estimate from `REJECTED` to `SUPERSEDED`, and the new estimate's `revision_number` is the prior estimate's plus one.

The customer, and only the ticket's owning customer, then acts on a presented estimate. Approval is permitted only while the ticket is in `AWAITING_APPROVAL` and the estimate is `PRESENTED`; if the acting customer is not the ticket owner the request is rejected with `ERR_NOT_TICKET_OWNER`. Approval moves the estimate from `PRESENTED` to `APPROVED`, records that estimate's `id` as the ticket's `approved_estimate_id`, and computes the ticket's promised `ready_by` once, here, from the SLA rule in §3.5. The effective destination of the approve depends on outstanding parts: if any parts order on the ticket is still in `REQUESTED` or `ORDERED`, the same approve call lands the ticket in `AWAITING_PARTS` rather than `APPROVED`; otherwise the ticket moves to `APPROVED`.

Rejection is the loop's hinge. A customer rejects a presented estimate while the ticket is in `AWAITING_APPROVAL` and the estimate is `PRESENTED`, again subject to the owner check (`ERR_NOT_TICKET_OWNER`). Rejection moves the estimate from `PRESENTED` to `REJECTED` and sends the ticket from `AWAITING_APPROVAL` back to `REVISION_REQUESTED`. From `REVISION_REQUESTED` the technician drafts and presents a fresh estimate that supersedes the rejected one, closing the cycle `REVISION_REQUESTED → AWAITING_APPROVAL → REVISION_REQUESTED` until the customer finally approves. Each of present, approve, and reject increments the ticket's `version` by one.

### 3.4. Parts Procurement and Ticket Cancellation

When a repair needs a component, a `RepairTechnician` raises a **parts order** referencing the owning `ticket_id` and the `service_line_id` that needs the part, with a `part_name`, a wholesale `supplier_cost_cents` that must be zero or greater, an optional `quantity` (defaulting to 1, at least 1), and a `lead_time_days` supplier lead time that must be zero or greater and that extends the ticket's promised turnaround. A parts order is created in status `REQUESTED`, and its customer-facing `marked_up_cost_cents` is computed at creation by the parts-markup rule in §3.5. A parts order's `status` moves along the pipeline `REQUESTED → ORDERED → RECEIVED`, with a `CANCELLED` branch reachable from either `REQUESTED` or `ORDERED`.

A technician places an order, advancing it from `REQUESTED` to `ORDERED`, only while the owning ticket is in `AWAITING_APPROVAL`, `REVISION_REQUESTED`, `APPROVED`, or `AWAITING_PARTS`. A technician then receives the part, advancing it from `ORDERED` to `RECEIVED`. Receiving does not auto-advance the ticket: when the ticket is in `AWAITING_PARTS` and every parts order has reached `RECEIVED` or `CANCELLED`, the ticket merely becomes eligible for the technician to start repair, which the technician triggers explicitly. A technician may cancel a parts order from `REQUESTED` or `ORDERED`; a cancelled order's `marked_up_cost_cents` is excluded from any subsequently presented estimate. When a technician cancels a single part directly, the owning service line is **not** automatically voided — the line-void only fires as a continuation of the ticket-cancellation cascade described next. Each of order, receive, and cancel increments the ticket's `version` by one.

Cancelling a whole ticket is reserved for a `ShopManager` and is permitted only while the ticket is in `INTAKE`, `AWAITING_APPROVAL`, `REVISION_REQUESTED`, `APPROVED`, or `AWAITING_PARTS`; any other state is rejected with `ERR_NOT_CANCELLABLE`. A cancellation drives a three-hop transitive cascade, where each hop is caused by the mutation the prior hop produced, not by the cancel directly. First, every parts order of the ticket that is not yet `RECEIVED` transitions to `CANCELLED`. Second, each parts order entering `CANCELLED` as part of this cascade transitions its owning service line (named by the order's `service_line_id`) from `QUOTED` or `COMPLETED` to `VOIDED`. Third, each service line entering `VOIDED` causes the ticket's still-open estimate — one whose status is `DRAFT` or `PRESENTED` — to be rejected (moved to `REJECTED`), because the set of lines backing the quote has changed. Beyond the graded chain, the operation also mops up: any remaining non-`VOIDED` service line that has no backing part is voided as well, and any still-open estimate is rejected. The ticket's `repair_status` becomes `CANCELLED` and its `version` increments by one. `CANCELLED` is terminal.

### 3.5. Pricing: Estimate Totals, Parts Markup, Rush Surcharge, and the Ready-By SLA

The shop's money is governed by four interlocking calculations. All amounts are integer cents per §2.6.

**Parts markup.** When a parts order is created, its `marked_up_cost_cents` is computed by multiplying `supplier_cost_cents` by `quantity` and then by a markup multiplier, taking the full product and rounding it once, half-up, to a whole cent. The multiplier is the retail markup of 1.35 for a part on a normal (non-redo) ticket, whose marked-up cost flows into the customer-billed estimate and final charge. For a part on a warranty-redo ticket — a ticket that is referenced by some warranty claim's `redo_ticket_id` — the multiplier is the at-cost factor of 1.0, so the same `supplier_cost_cents` and `quantity` produce a smaller `marked_up_cost_cents`, because a redo is no-charge and parts are passed at wholesale. The single rounding happens after the full product is formed; rounding per unit and then multiplying by quantity is incorrect.

**Estimate totals.** The totals engine runs in two variants, with a pinned evaluation order. Step one, the labor subtotal is the sum, over the service lines in scope, of each line's price. Step two, the parts subtotal is the sum, over the parts orders in scope, of their `marked_up_cost_cents`. Step three, a pre-rush total is the labor subtotal plus the parts subtotal. Step four, the rush surcharge is computed from that pre-rush total and the ticket's priority (detailed below). Step five, the estimate total is the pre-rush total plus the rush surcharge. The two variants differ in which lines and parts are in scope and in how each line is priced:

- The **provisional** variant runs when an estimate is presented (the ticket entering `AWAITING_APPROVAL`). Each line is priced at its `quoted_price_cents`; the lines in scope are those with status `QUOTED`; the parts in scope are those with status `REQUESTED`, `ORDERED`, or `RECEIVED`. The result is written to the estimate's `estimate_total_cents`, with the intermediate sums written to `labor_subtotal_cents`, `parts_subtotal_cents`, and `rush_surcharge_cents`.
- The **final** variant runs when the ticket is marked ready (entering `READY_FOR_PICKUP`). Each line is priced at its `adjusted_price_cents` when that override is present and at its `quoted_price_cents` otherwise; the lines in scope are those with status `COMPLETED`; the parts in scope are those with status `RECEIVED` only. The result is written to the ticket's `final_charge_cents`. Because a line voided or a part cancelled after the estimate was presented drops out of the final scope, the provisional total and the final charge can legitimately diverge.

**Rush surcharge.** Inside the totals engine at step four, the surcharge is zero whenever the ticket's `priority` is not `RUSH`. For a `RUSH` ticket, the surcharge is a marginal tiered charge on the pre-rush total, with half-open tier boundaries. The portion of the pre-rush total from 0 up to but not including 5000 cents is charged at a rate of 0.30; the portion from 5000 up to but not including 20000 cents is charged at 0.20; and the portion at or above 20000 cents is charged at 0.10. Because the boundaries are half-open, a pre-rush total of exactly 5000 cents places the full 5000 in the first tier and nothing in the second. The three tier portions are each multiplied by their rate, the three results are summed, and that sum is rounded once, half-up, to a whole cent (sum first, then round). The surcharge actually applied is the larger of this rounded amount and a floor of 1500 cents — so for any `RUSH` ticket the surcharge is never below 1500 cents. As a worked boundary, a pre-rush of exactly 5000 cents yields a raw surcharge of 1500 cents, which equals the floor and is applied as 1500.

**Ready-by SLA.** When an estimate is approved, the ticket's promised `ready_by` is computed once from the service mix. First, a base number of business days is the maximum, over the ticket's non-`VOIDED` service lines, of each line's service type `standard_turnaround_days`. Second, a parts contribution is the maximum, over the ticket's non-`CANCELLED` parts orders, of their `lead_time_days`, taken as 0 when there are no parts. The SLA day count is the base plus the parts contribution. If the ticket's `priority` is `RUSH`, the SLA day count is replaced by the larger of a rush minimum of 1 day and the SLA day count multiplied by 0.5 and rounded up to the next whole day. The promised `ready_by` is then `drop_off_at` advanced by that many whole calendar days in UTC. As a worked boundary, a 5-business-day job at rush priority becomes the ceiling of 2.5, which is 3 days, floored at the 1-day rush minimum.

### 3.6. Repair Execution, Mark-Ready, and Warranty

Beginning the hands-on work transitions the ticket to `IN_REPAIR`. A `RepairTechnician` starts repair from either `APPROVED` or `AWAITING_PARTS`. Starting requires that the ticket have an `assigned_technician_id` set and that the named technician be active; otherwise the request is rejected with `ERR_NO_TECHNICIAN`. When starting from `AWAITING_PARTS`, every parts order on the ticket must already be in `RECEIVED` or `CANCELLED`, failing with `ERR_PARTS_NOT_READY` otherwise. While the ticket is `IN_REPAIR`, a technician works each service line and may, on a line still in `QUOTED`, supply an `adjusted_price_cents` override and/or mark the line `COMPLETED`; completing a line is permitted only while the ticket is `IN_REPAIR`, and an attempt otherwise is rejected with `ERR_INVALID_TICKET_STATE`. A supplied `adjusted_price_cents` overrides `quoted_price_cents` for that line in the final totals. Completing a line moves it from `QUOTED` to `COMPLETED` and increments the ticket's `version`.

Marking the ticket ready transitions it from `IN_REPAIR` to `READY_FOR_PICKUP` and is permitted only when every non-`VOIDED` service line on the ticket is `COMPLETED`; an incomplete line set is rejected with `ERR_LINES_NOT_COMPLETED`. Mark-ready stamps `ready_at` from the server clock, computes `final_charge_cents` via the final variant of the totals engine, and sets `sla_breached` to true exactly when `ready_at` is later than the promised `ready_by` and false otherwise. The ticket's `version` increments.

The ready notification runs on a parallel track. A `FrontDeskClerk` sends the ready-for-pickup notification, which moves the ticket's `notify_status` from `NONE` to `READY_NOTIFIED` and appends a `READY_FOR_PICKUP` notification, incrementing the ticket's `version`. This `notify_status` dimension — whose values are `NONE`, `READY_NOTIFIED`, and `UNCLAIMED_WARNED` — evolves independently of `repair_status`. A `Notification` records the `ticket_id` it concerns, a `kind` of `READY_FOR_PICKUP`, `UNCLAIMED_WARNING`, or `ESTIMATE_PRESENTED`, a `channel` resolved from the customer's `notify_channel` at send time (`EMAIL` or `SMS`), and a message `body`.

Pickup releases the item. A `FrontDeskClerk` records pickup from either `READY_FOR_PICKUP` or `UNCLAIMED`, but only once the captured payments cover the bill: pickup requires `amount_paid_cents` to be at least `final_charge_cents`, and a shortfall is rejected with `ERR_BALANCE_DUE`. Pickup stamps `picked_up_at` from the clock and computes the ticket's `warranty_expires_at` as `picked_up_at` advanced by a coverage window equal to the maximum, over the ticket's `COMPLETED` service lines, of their service type `warranty_days` (taken as zero whole calendar days, leaving `warranty_expires_at` equal to `picked_up_at`, when there are no completed lines). The ticket's `version` increments. `PICKED_UP` is terminal.

Payments accrue against the ticket independently. A `FrontDeskClerk` captures a **payment** referencing the `ticket_id`, an `amount_cents` greater than zero, and a `method` of `CASH`, `CARD`, or `STORE_CREDIT`; the capture is OCC-guarded and requires `expected_ticket_version` per §2.5. A captured payment takes `state` `CAPTURED`, and the ticket's `amount_paid_cents` is recomputed as the sum of `amount_cents` over the ticket's payments in state `CAPTURED`. A `ShopManager` may refund a captured payment, but only while it is `CAPTURED`; a refund on an already-refunded payment is rejected with `ERR_PAYMENT_NOT_REFUNDABLE`. Refunding moves the payment's `state` from `CAPTURED` to `REFUNDED` and recomputes the ticket's `amount_paid_cents` with refunded payments excluded, restoring the balance to its pre-capture value; the ticket's `version` increments.

**Warranty.** After pickup, the owning customer may file a **warranty claim** against a service alleged to have failed, referencing the original `ticket_id`, the failed `service_line_id`, the `reported_by_customer_id` (which must equal the ticket's `customer_id`), and a `defect_description`. A claim may be filed only while the original ticket is `PICKED_UP` and the current clock is at or before that ticket's `warranty_expires_at`; a claim filed after expiry or against a ticket not picked up is rejected with `ERR_WARRANTY_EXPIRED`. A new claim takes status `FILED`, with `ruled_by_technician_id` and `redo_ticket_id` unset.

A `ShopManager` adjudicates a filed claim, supplying the `ruled_by_technician_id` who rules on it. Both rulings enforce segregation of duties: the `ruled_by_technician_id` must differ from the `authored_by_technician_id` of the original ticket's approved estimate, and a match is rejected with `ERR_SEGREGATION_VIOLATION`. Denying a filed claim moves it from `FILED` to `DENIED` and has no further effect — no redo ticket and no line copy. Approving a filed claim moves it from `FILED` to `APPROVED` and drives a two-hop cascade: first, the system spawns a new no-charge redo `RepairTicket` whose `repair_status` is `APPROVED`, whose `priority` is `RUSH`, whose `final_charge_cents` is 0, and whose `customer_id` is copied from the original ticket, and records that new ticket's `id` as the claim's `redo_ticket_id`; second, caused by that spawn rather than by the claim directly, the failed service line is copied onto the redo ticket as a no-charge `QUOTED` line with `quoted_price_cents` of 0. Because the redo ticket is a redo, any parts ordered against it are marked up at the at-cost factor of 1.0 per §3.5.

### 3.7. Unclaimed Items and Disposal

When a ready item goes uncollected, two time thresholds — both measured in whole calendar days (UTC) from the ticket's `ready_at` and both using an inclusive at-or-after comparison — govern what the shop may do. A `FrontDeskClerk` flags an uncollected ticket as unclaimed, moving its `repair_status` from `READY_FOR_PICKUP` to `UNCLAIMED`, only once the clock has reached or passed `ready_at` plus the 30-day unclaimed grace window; an earlier attempt is rejected with `ERR_UNCLAIMED_TOO_EARLY`. Flagging sets the ticket's `notify_status` to `UNCLAIMED_WARNED`, appends an `UNCLAIMED_WARNING` notification, and increments the ticket's `version`. A ticket in `UNCLAIMED` can still be picked up by the customer under the same balance-due rule as a normal pickup.

Disposal is the last resort and belongs to a `ShopManager`. A ticket may be disposed from `UNCLAIMED` only when its `notify_status` is `UNCLAIMED_WARNED` — a ticket that was never warned is rejected with `ERR_UNCLAIMED_NOT_WARNED` — and only once the clock has reached or passed `ready_at` plus the 90-day disposal window; an earlier attempt is rejected with `ERR_DISPOSAL_TOO_EARLY`. Disposal moves the ticket's `repair_status` to `DISPOSED`, voids all of the ticket's remaining non-`VOIDED` service lines, and increments the ticket's `version`. `DISPOSED` is terminal.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the action endpoints that drive a state transition or recompute a derived value — return a `200 OK` status code. The request body, the resources mutated, and the side effects of each operation are not repeated here; they are reconstructed from the narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set` | Set the server UTC clock (test-driving) | ShopManager |
| POST | `/customers` | Create a Customer | FrontDeskClerk, ShopManager |
| GET | `/customers` | List Customers | FrontDeskClerk, ShopManager, RepairTechnician |
| GET | `/customers/{id}` | Get a Customer | FrontDeskClerk, ShopManager, RepairTechnician, Customer |
| POST | `/service-types` | Create a ServiceType | ShopManager |
| GET | `/service-types` | List ServiceTypes | FrontDeskClerk, ShopManager, RepairTechnician |
| GET | `/service-types/{id}` | Get a ServiceType | FrontDeskClerk, ShopManager, RepairTechnician |
| POST | `/service-types/{id}/retire` | Retire a ServiceType | ShopManager |
| POST | `/technicians` | Create a Technician | ShopManager |
| GET | `/technicians` | List Technicians | FrontDeskClerk, ShopManager, RepairTechnician |
| GET | `/technicians/{id}` | Get a Technician | FrontDeskClerk, ShopManager, RepairTechnician |
| POST | `/repair-tickets` | Create (intake) a RepairTicket | FrontDeskClerk |
| GET | `/repair-tickets` | List RepairTickets | FrontDeskClerk, ShopManager, RepairTechnician |
| GET | `/repair-tickets/{id}` | Get a RepairTicket | FrontDeskClerk, ShopManager, RepairTechnician, Customer |
| PATCH | `/repair-tickets/{id}` | Assign technician / update priority before approval | FrontDeskClerk, ShopManager |
| POST | `/repair-tickets/{id}/start-repair` | Begin repair | RepairTechnician |
| POST | `/repair-tickets/{id}/mark-ready` | Mark repair complete and ready | RepairTechnician |
| POST | `/repair-tickets/{id}/notify-ready` | Send the ready-for-pickup notification | FrontDeskClerk |
| POST | `/repair-tickets/{id}/pickup` | Customer pickup | FrontDeskClerk |
| POST | `/repair-tickets/{id}/flag-unclaimed` | Flag an uncollected ticket as unclaimed and warn | FrontDeskClerk |
| POST | `/repair-tickets/{id}/dispose` | Dispose an unclaimed item after the disposal window | ShopManager |
| POST | `/repair-tickets/{id}/cancel` | Cancel a ticket before repair completion | ShopManager |
| POST | `/ticket-items` | Add a TicketItem with intake condition | FrontDeskClerk |
| GET | `/ticket-items` | List TicketItems | FrontDeskClerk, ShopManager, RepairTechnician, Customer |
| GET | `/ticket-items/{id}` | Get a TicketItem | FrontDeskClerk, ShopManager, RepairTechnician, Customer |
| POST | `/service-lines` | Add a ServiceLine | FrontDeskClerk, RepairTechnician |
| GET | `/service-lines` | List ServiceLines | FrontDeskClerk, ShopManager, RepairTechnician, Customer |
| GET | `/service-lines/{id}` | Get a ServiceLine | FrontDeskClerk, ShopManager, RepairTechnician, Customer |
| PATCH | `/service-lines/{id}` | Adjust a line price and/or complete it during repair | RepairTechnician |
| POST | `/estimates` | Create a DRAFT Estimate | RepairTechnician |
| GET | `/estimates` | List Estimates | FrontDeskClerk, ShopManager, RepairTechnician, Customer |
| GET | `/estimates/{id}` | Get an Estimate | FrontDeskClerk, ShopManager, RepairTechnician, Customer |
| POST | `/estimates/{id}/present` | Present a DRAFT estimate (OCC-guarded on the ticket) | RepairTechnician |
| POST | `/estimates/{id}/approve` | Approve the presented estimate | Customer |
| POST | `/estimates/{id}/reject` | Reject the presented estimate | Customer |
| POST | `/parts-orders` | Request a PartsOrder against a ServiceLine | RepairTechnician |
| GET | `/parts-orders` | List PartsOrders | FrontDeskClerk, ShopManager, RepairTechnician |
| GET | `/parts-orders/{id}` | Get a PartsOrder | FrontDeskClerk, ShopManager, RepairTechnician |
| POST | `/parts-orders/{id}/order` | Place the parts order | RepairTechnician |
| POST | `/parts-orders/{id}/receive` | Receive the part | RepairTechnician |
| POST | `/parts-orders/{id}/cancel` | Cancel the parts order | RepairTechnician |
| POST | `/payments` | Capture a Payment against a ticket (OCC-guarded on the ticket) | FrontDeskClerk |
| GET | `/payments` | List Payments | FrontDeskClerk, ShopManager |
| GET | `/payments/{id}` | Get a Payment | FrontDeskClerk, ShopManager |
| POST | `/payments/{id}/refund` | Refund a captured payment | ShopManager |
| GET | `/notifications` | List Notifications | FrontDeskClerk, ShopManager, RepairTechnician, Customer |
| GET | `/notifications/{id}` | Get a Notification | FrontDeskClerk, ShopManager, RepairTechnician, Customer |
| POST | `/warranty-claims` | File a WarrantyClaim against a picked-up ticket's service line | Customer |
| GET | `/warranty-claims` | List WarrantyClaims | FrontDeskClerk, ShopManager, RepairTechnician, Customer |
| GET | `/warranty-claims/{id}` | Get a WarrantyClaim | FrontDeskClerk, ShopManager, RepairTechnician, Customer |
| POST | `/warranty-claims/{id}/approve` | Approve a claim; spawn a no-charge redo ticket | ShopManager |
| POST | `/warranty-claims/{id}/deny` | Deny a claim | ShopManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_TICKET_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_VIOLATION` | 403 Forbidden |
| `ERR_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_ESTIMATE_NOT_FOUND` | 404 Not Found |
| `ERR_PARTS_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_TICKET_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_TYPE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FK_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_KEY` | 409 Conflict |
| `ERR_INVALID_TICKET_STATE` | 409 Conflict |
| `ERR_INVALID_ESTIMATE_STATE` | 409 Conflict |
| `ERR_INVALID_PARTS_STATE` | 409 Conflict |
| `ERR_INVALID_CLAIM_STATE` | 409 Conflict |
| `ERR_STALE_TICKET_VERSION` | 412 Precondition Failed |
| `ERR_NO_SERVICE_LINES` | 409 Conflict |
| `ERR_BAD_REVISION_CHAIN` | 409 Conflict |
| `ERR_PARTS_NOT_READY` | 409 Conflict |
| `ERR_NO_TECHNICIAN` | 409 Conflict |
| `ERR_LINES_NOT_COMPLETED` | 409 Conflict |
| `ERR_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PAYMENT_NOT_REFUNDABLE` | 409 Conflict |
| `ERR_UNCLAIMED_TOO_EARLY` | 409 Conflict |
| `ERR_DISPOSAL_TOO_EARLY` | 409 Conflict |
| `ERR_UNCLAIMED_NOT_WARNED` | 409 Conflict |
| `ERR_WARRANTY_EXPIRED` | 422 Unprocessable Entity |
| `ERR_BALANCE_DUE` | 402 Payment Required |
