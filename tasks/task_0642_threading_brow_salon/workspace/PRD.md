# Threading & Brow Salon API — Product Requirements Document

## 1. Introduction

A high-volume threading and brow studio lives or dies by the flow of its walk-in queue. Customers arrive without appointments, expect to be seen in the order they arrived, and want a quick service — eyebrow threading, a brow tint, a wax — performed on whichever chair and technician next come free. This document specifies the back-office API that orchestrates that floor: a finite pool of chairs and technicians that the walk-in queue competes for, the sanitation downtime that a chair must observe between guests, the membership packages and loyalty points that reward regulars, and the retail and add-on revenue that rides alongside each visit.

The system is built around a single salon as the aggregate root, beneath which chairs, technicians, members, the service menu, and the live queue all hang. The hard parts of the domain are the ones that recur in any quota-allocation business: seating decisions made against a possibly stale view of who currently occupies which chair, the cascading clean-up that a cancelled or voided visit must perform across loyalty, retail stock, and package credits, and the difference between the provisional price a guest is quoted when seated and the finalized settlement that is computed when service ends. Throughout, the API distinguishes the running of the service (whether the technician is still working) from the running of the money (whether the guest has paid), and lets those two dimensions advance on their own clocks.

This specification governs the full lifecycle: registering the salon and its resources, opening for business, joining and managing the queue, seating guests, adding lines, completing and settling visits, and the compensating reversals that keep loyalty balances and retail inventory honest when something is undone.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and contracts that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal and `X-User-Role` declares the capacity in which they are acting. If either header is absent, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles: `SalonManager`, `FrontDeskAgent`, `Technician`, and `Member`. These are peer roles, each owning a slice of the floor. A `SalonManager` owns the salon lifecycle, licensing, the catalog of services, add-ons, and retail products, chair and technician administration, visit voids, and loyalty adjustments. A `FrontDeskAgent` runs the walk-in queue, seats members, manages line items, and completes and settles visits. A `Technician` performs the service itself — adding and voiding line items and completing visits. A `Member` is the walk-in customer, acting on their own packages, their own queue tickets, and their own loyalty reads.

Two of these roles are opaque operator identities and two are entity-backed. When `X-User-Role` is `SalonManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept it for audit but does not compare it to any entity's `id`. When `X-User-Role` is `FrontDeskAgent`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on any resource that references a `Technician` compare the resource's technician foreign key to `X-User-ID`. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's member foreign key to `X-User-ID`, so a `Member` acting on another member's package, ticket, or loyalty record is denied with `ERR_FORBIDDEN_ROLE`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless an endpoint states otherwise, every list is sorted by the resource's `created_at` timestamp in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Server-Minted Identity

Every primary resource carries a server-minted `id`, formatted as a UUID with no type prefix. Clients never supply an `id`; the server mints one on creation. Each resource also carries a `created_at` timestamp, an ISO 8601 UTC instant rendered with three fractional digits, recording when the resource was first created.

Most resources additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is refreshed to the current logical clock on every mutation, and `version` starts at 1 and increments by one with each mutation; together they support optimistic concurrency control and an audit trail. The one exception is the `LoyaltyLedgerEntry`, which is an append-only event record: it carries only `id` and `created_at`, and has neither an `updated_at` field nor a `version` field. A ledger entry is never modified after it is written; corrections are made by writing a new, opposing entry.

### 2.5. The Logical Clock

Time in this system is a server-controlled logical clock, never wall-clock time. On startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it holds that default and never falls back to real time. An administrative test-driving capability lets a `SalonManager` set the clock to a supplied absolute instant via the `to_iso8601` field. Every time-sensitive judgement — whether a license has lapsed, whether a technician's sanitation certification is still valid, and whether a chair has finished its sanitation window — reads this logical clock at the moment of the operation.

### 2.6. Nested Resource Retrieval and Existence Ordering

When an endpoint path carries a resource identifier, the server validates existence before applying any business rule. For nested paths the validation proceeds strictly left to right: the `salonId` (where present) is checked first, then the addressed child such as `ticketId`, `visitId`, `chairId`, `technicianId`, `memberId`, `packageId`, `lineId`, `serviceItemId`, `addOnId`, `retailProductId`, or `entryId`. The first identifier in the path that does not resolve produces its corresponding not-found error — `ERR_SALON_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_CHAIR_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, or `ERR_LINE_NOT_FOUND` — before the system looks any deeper. Resources referenced in a request body rather than the path — a `chair_id`, `technician_id`, `membership_package_id`, `item_ref_id`, or `service_menu_item_id` — are validated after the path resources, yielding `ERR_CHAIR_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_ADDON_NOT_FOUND`, `ERR_RETAIL_NOT_FOUND`, or `ERR_SERVICE_ITEM_NOT_FOUND` as appropriate.

### 2.7. Validation Ordering

Across every endpoint the system evaluates checks in a fixed priority order so that the same request always fails on the same reason. Authentication of the user context comes first; a missing or unrecognized `X-User-Role` yields `ERR_MISSING_OR_INVALID_USER_CONTEXT` ahead of everything else. Role authorization comes second, yielding `ERR_FORBIDDEN_ROLE` — including the case of a `Member` reaching for another member's resource. Third, path resources are checked for existence (the left-to-right rule of §2.6). Fourth, body-referenced resources are checked for existence. Fifth, the salon's open status is enforced where it applies. Sixth, the target resource's own state is checked against the transition being requested. Only after those structural gates does the system reach the business-safety, capacity, fiscal, temporal, referential, concurrency, and uniqueness checks described throughout §3. Where a request schema is itself malformed — a required field missing, a wrong type, or a value that is negative or zero where a positive number is required — the request is rejected with `ERR_VALIDATION` (HTTP 422).

### 2.8. Monetary Values, Points, and Precision

All prices and totals are carried as integer cents, so cash arithmetic never introduces fractional-cent drift. The provisional `estimate_total_cents` is a plain sum of integer-cent inputs and requires no rounding. The finalized `final_total_cents` is computed in a pinned sequence of steps, and where a step divides — applying a basis-point discount or computing loyalty — the result is floored to a whole cent or whole point at that step, before the next step runs. Rounding is therefore per-step, never sum-then-round. Basis points throughout the system express a rate out of ten thousand: a discount of 1000 basis points is ten percent of the discountable base. Loyalty is counted in whole integer points and a member's balance is never permitted below zero.

### 2.9. Optimistic Concurrency on Seating

Seating a member into a chair is the one operation that competes for a shared, finite resource — the salon's pool of open chairs — and is therefore guarded by optimistic concurrency control against the `Salon` aggregate. The salon's `version` advances whenever its occupancy view changes: every successful seating, every freeing of a chair on completion or void, and every open or close increments `Salon.version` by one. The seating request must carry an `expected_salon_version` field holding the `version` the client last observed on the salon. If that value does not equal the salon's current `version` — because another writer has seated or freed a chair, or opened or closed the salon, since the client last read it — the seating is rejected with `ERR_STALE_SALON_VERSION` (HTTP 412). This forces a client working from a stale occupancy picture to re-read the salon before it can claim a chair, so it never seats onto a chair it has not actually observed as open. No other endpoint takes a version field; seating is the sole optimistic-concurrency-controlled write.

### 2.10. Hierarchical Consistency and Compensating Cascades

Many operations touch more than one entity, and the system keeps the whole graph consistent in a single immediate step. When a guest is seated, the chosen chair flips to occupied, the chosen technician flips to busy, and the salon's live occupancy count rises — all at once. When service completes or a visit is voided, those same resources are released together and the occupancy count falls. The most demanding case is the void, which is a compensating action: it must leave the member's loyalty balance, the retail stock, and any drawn package credit exactly as they stood before the visit existed. Every such cascade refreshes `updated_at` and increments `version` on each entity it mutates, and the derived figures — a salon's `active_occupancy_count`, a member's `loyalty_balance` and `no_show_strikes`, a queue ticket's `position` — are recomputed from their underlying records rather than stored as independent truth. The specific cascades are described where each workflow lives in §3.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Salon and Its Resources

The `Salon` is the root of everything. A `SalonManager` creates one by supplying a `name`, a `license_number`, and a `license_expiry` instant, and may optionally set the `loyalty_earn_rate_bps`; when omitted that rate defaults to 500, meaning five loyalty points are earned per finalized dollar (the rate must be at least zero). A freshly created salon starts in the `CLOSED` state with an `active_occupancy_count` of 0 and a `version` of 1. The salon also carries a computed `license_status` of either `ACTIVE` or `LAPSED`: it reads `ACTIVE` while the logical clock is strictly before `license_expiry` and `LAPSED` once the clock has reached or passed it. This status is recomputed on every read and again at each seating attempt. The salon's `status` is either `OPEN` or `CLOSED` and gates all queue and seating activity.

Against a salon a `SalonManager` registers the floor's resources. A `Technician` is registered with a `salon_id`, a `display_name`, a `sanitation_cert_expiry` instant, and optionally a list of `certified_addon_codes` (defaulting to an empty list, which means the technician may perform threading only). A technician begins `AVAILABLE` and moves among `AVAILABLE`, `BUSY`, and `OFF_SHIFT`; only an `AVAILABLE` technician may be assigned. A `Chair` is added with a `salon_id`, a `label`, and an optional `sanitation_minutes` value (defaulting to 5), which is the number of minutes the chair must dwell in `SANITIZING` after a visit before it may be seated again; this must be at least zero. A chair begins `OPEN` with its `sanitation_ready_at` null, and cycles among `OPEN`, `OCCUPIED`, `SANITIZING`, and `OUT_OF_SERVICE`. The `sanitation_ready_at` field is the instant the chair leaves `SANITIZING` and stays null until the chair has been used.

The catalog is likewise the manager's domain. A `ServiceMenuItem` is created with a `salon_id`, a `code` unique within the salon, a `name`, a `base_price_cents` (which must be greater than zero), an `est_minutes` estimate of chair time (greater than zero), and an optional `package_eligible` flag (defaulting to false) marking whether the item may be drawn from a package credit; it begins `LISTED` and may later be `RETIRED`, after which it cannot start new visits. An `AddOn` is created with a `salon_id`, a `code` unique within the salon, a `name`, a `price_cents` (greater than zero), and an optional `requires_certification` flag defaulting to true, indicating whether the assigned technician must list this add-on's `code` among their `certified_addon_codes`; it too is `LISTED` or `RETIRED`. A `RetailProduct` is created with a `salon_id`, a `sku` unique within the salon, a `name`, a `unit_price_cents` (greater than zero), and an optional `initial_stock_qty` (defaulting to 0, at least zero); its live `stock_qty` is seeded from `initial_stock_qty` at creation, decrements when a retail line is added, and is restored when such a line is voided, and is never allowed below zero. Any attempt to create a `Member` with a `phone`, a `ServiceMenuItem` with a `code`, an `AddOn` with a `code`, or a `RetailProduct` with a `sku` that already exists within the same salon is rejected with `ERR_DUPLICATE_RESOURCE`.

Members themselves are registered by a `FrontDeskAgent` or a `SalonManager` with a `salon_id`, a `full_name`, and a `phone` that must be unique within the salon. A new member starts `ACTIVE` with a `loyalty_balance` of 0 and `no_show_strikes` of 0. A member's `status` is one of `ACTIVE`, `SUSPENDED`, or `BANNED`: a `SUSPENDED` member is blocked from joining the queue until cleared, and `BANNED` is terminal. The `loyalty_balance` is a derived figure equal to the sum of the signed `points` across every `LoyaltyLedgerEntry` for that member, floored at zero, and `no_show_strikes` is the running count of the member's un-expired no-show events; both are recomputed whenever the member is read.

### 3.2. Opening, Closing, and the Salon's Daily Cycle

Before any guest can be queued or seated, a `SalonManager` opens the salon, moving its `status` from `CLOSED` to `OPEN`. Opening is permitted only when the license is current — the logical clock must be strictly earlier than `license_expiry`, equivalently `license_status` must be `ACTIVE` — otherwise the open is refused with `ERR_LICENSE_LAPSED`. A successful open increments `Salon.version` by one and unlocks queue and seating operations.

Closing reverses this, moving `status` from `OPEN` back to `CLOSED`. A salon may only close when no chair is currently occupied, that is when `active_occupancy_count` equals zero; a close attempted while a guest is still in a chair is rejected with `ERR_SALON_HAS_ACTIVE_VISITS`. When the salon does close, every queue ticket still `WAITING` or `CALLED` is cascaded to `CANCELLED`, clearing the floor, and `Salon.version` is incremented by one. Both open and close are optimistic-concurrency aware in the sense that they bump the salon's version, which downstream seating clients must observe.

### 3.3. The Walk-In Queue

A walk-in begins when a `FrontDeskAgent` enters a member into the queue by posting a `salon_id`, a `member_id`, and the `service_menu_item_id` the guest wants. This creates a `QueueTicket` in the `WAITING` state, stamps its `joined_at` with the current logical clock, sets its `called_count` to 0, and computes its `position`. Joining the queue requires the salon to be `OPEN` (otherwise `ERR_SALON_NOT_OPEN`) and the member to be `ACTIVE`; a `SUSPENDED` or `BANNED` member attempting to join is refused with `ERR_MEMBER_BLOCKED`.

A ticket's `position` is a one-based FIFO rank computed over only the `WAITING` tickets in the same salon, ordered by `joined_at` ascending and, for any tie, by `created_at` ascending; the ticket identifier is never used in the ordering. A ticket that is not `WAITING` has a `position` of 0. This position is recomputed on every queue event — join, call, requeue, cancel, no-show — and on the salon-close cascade, and again whenever a ticket is read.

The ticket lifecycle is cyclic. A `FrontDeskAgent` calls a member up by moving the ticket from `WAITING` to `CALLED`, which requires the salon to be `OPEN` (otherwise `ERR_SALON_NOT_OPEN`). Calling must respect FIFO order: the ticket called must be the lowest-position `WAITING` ticket, unless the agent explicitly passes `allow_skip` set to true. Calling a ticket that is not the lowest-position waiting ticket without setting `allow_skip` is rejected with `ERR_QUEUE_ORDER_VIOLATION`. When a ticket is called, the positions of the remaining `WAITING` tickets are recomputed and the queue compacts.

If a called guest steps away, the agent can put the ticket back with a requeue, moving it from `CALLED` to `WAITING`. Because `joined_at` is left unchanged, the guest keeps their original FIFO place; the requeue increments `called_count` by one and recomputes positions across the salon's waiting set. This cyclic edge is bounded: a ticket may be requeued at most twice — the recall limit is two — and a requeue attempted when `called_count` has already reached two is rejected with `ERR_RECALL_LIMIT_REACHED`.

A called guest who does not appear is recorded as a no-show by the agent, moving the ticket from `CALLED` to `NO_SHOW` (which requires the ticket to currently be `CALLED`, else `ERR_TICKET_NOT_CALLED`). A no-show adds one un-expired strike to the member and may escalate the member's standing, as described in §3.7. Finally, a `WAITING` or `CALLED` ticket may be cancelled outright — by a `FrontDeskAgent`, or by the owning `Member` on their own ticket — moving it to `CANCELLED` and recomputing positions for the remaining waiting tickets. The states `SEATED`, `NO_SHOW`, and `CANCELLED` are all terminal for a ticket.

### 3.4. Seating: Claiming a Chair and Technician

Seating is the pivotal operation and the busiest junction in the system. A `FrontDeskAgent` seats a called guest by creating a `ServiceVisit`, supplying the `salon_id`, the `queue_ticket_id` of the called ticket, the `chair_id`, the `technician_id`, the `expected_salon_version`, and optionally a `membership_package_id` to draw a credit and discount from. The visit is created in service status `IN_SERVICE` and payment status `UNPAID`, records its `seated_at`, links its `member_id` and `service_menu_item_id` through the ticket, and computes a provisional `estimate_total_cents`.

A long chain of preconditions guards seating, evaluated after the structural gates of §2.7. The salon must be `OPEN`, else `ERR_SALON_NOT_OPEN`. The ticket must currently be `CALLED`, else `ERR_TICKET_NOT_CALLED`. The license must still be `ACTIVE` at the moment of seating, else `ERR_LICENSE_LAPSED`. The chosen chair must be `OPEN`, else `ERR_CHAIR_NOT_OPEN`; and if the chair carries a `sanitation_ready_at`, the logical clock must have reached or passed it (the clock is at or after `sanitation_ready_at`), else the chair is still cooling down and the seating is refused with `ERR_CHAIR_NOT_SANITIZED`. The chosen technician must be `AVAILABLE`, else `ERR_TECHNICIAN_NOT_AVAILABLE`, and the technician's `sanitation_cert_expiry` must lie in the future (the logical clock is strictly before it), else `ERR_TECH_CERT_EXPIRED`. Finally the `expected_salon_version` must match the salon's current `version`, else `ERR_STALE_SALON_VERSION` as described in §2.9.

A successful seating fires a cross-entity cascade in one immediate step: the ticket moves from `CALLED` to `SEATED`; the new `ServiceVisit` comes into being as `IN_SERVICE`/`UNPAID`; the chair flips `OPEN` to `OCCUPIED`; the technician flips `AVAILABLE` to `BUSY`; the salon's `active_occupancy_count` rises by one; and `Salon.version` is incremented by one.

### 3.5. Building the Bill: Line Items, Estimate, and the Polymorphic Reference

While a visit is `IN_SERVICE`, a `FrontDeskAgent` or `Technician` may attach line items to it. A `VisitLineItem` is created against the visit with a `line_type` of either `ADDON` or `RETAIL`, an `item_ref_id`, and an optional `quantity` (defaulting to 1). The `item_ref_id` is polymorphic: it points to an `AddOn` when `line_type` is `ADDON` and to a `RetailProduct` when `line_type` is `RETAIL`. If the `line_type` does not match the kind of entity the `item_ref_id` actually resolves to, the line is rejected with `ERR_LINE_TYPE_MISMATCH`. A line may only be added to a visit that is `IN_SERVICE`, else `ERR_VISIT_NOT_IN_SERVICE`. Each line records an immutable `unit_price_cents` snapshot of the referenced item's price at the moment it was added, and a derived `line_total_cents` equal to that snapshot multiplied by `quantity`. A line begins `ACTIVE` and may later become `VOIDED`; voided lines are excluded from all settlement and estimate math.

Quantities differ by kind. A `RETAIL` line may have a quantity greater than one, but it must not exceed the product's on-hand `stock_qty`; a request for more units than are in stock is rejected with `ERR_INSUFFICIENT_STOCK`. Adding a `RETAIL` line decrements the referenced `RetailProduct.stock_qty` by the line `quantity`. An `ADDON` line must have a quantity of exactly one; any other add-on quantity, or any quantity below one, is rejected with `ERR_INVALID_LINE_QUANTITY`. Add-ons also carry the certification gate: when the referenced add-on's `requires_certification` is true, the visit's assigned technician must list that add-on's `code` among their `certified_addon_codes`, otherwise the line is refused with `ERR_TECH_NOT_CERTIFIED`. This same certification rule applies both when an add-on is attached as a line and at seating time when an add-on is part of the visit.

The provisional `estimate_total_cents` is a list-price view computed at seating and recomputed whenever an `ACTIVE` line is added or voided while the visit is `IN_SERVICE`. It is the plain sum, in integer cents with no rounding, of three parts: the service part, which is the `base_price_cents` of the visit's `ServiceMenuItem`; the add-on part, which is the total of `line_total_cents` across all `ACTIVE` lines whose `line_type` is `ADDON`; and the retail part, the total of `line_total_cents` across all `ACTIVE` lines whose `line_type` is `RETAIL`. The estimate deliberately ignores every membership discount and package credit, counting retail at full unit price; it is the figure a guest is quoted, not what they ultimately settle.

A single line may be voided manually by a `FrontDeskAgent` or `Technician` while the owning visit is still `IN_SERVICE`; voiding a line on a visit that is not `IN_SERVICE` is refused with `ERR_VISIT_NOT_IN_SERVICE`. A line must be `ACTIVE` to be voided — voiding an already-`VOIDED` line is rejected — and the void moves the line from `ACTIVE` to `VOIDED`, excludes it from the recomputed estimate, and, if the line was `RETAIL`, restores its `quantity` back to the product's `stock_qty`.

### 3.6. Memberships, Credits, and the Final Settlement

A `MembershipPackage` belongs to a member and is created by a `FrontDeskAgent` or `SalonManager` with a `member_id` and a `tier` of `BRONZE`, `SILVER`, or `GOLD`. The package begins `PENDING`. Its `discount_bps`, `total_credits`, and `credits_remaining` are derived from the tier: `BRONZE` carries a 500-basis-point discount and four credits, `SILVER` a 1000-basis-point discount and eight credits, and `GOLD` a 1500-basis-point discount and twelve credits. The package moves `PENDING` to `ACTIVE` when the owning `Member` (or a `FrontDeskAgent` on their behalf) activates it on first payment; activation requires the member to be `ACTIVE`, else `ERR_MEMBER_NOT_ACTIVE`, and stamps `discount_bps`, `total_credits`, and `credits_remaining` from the tier. A package is `ACTIVE` while `credits_remaining` is above zero, transitions to `DEPLETED` the moment its last credit is consumed at a visit finalization, and can swing back from `DEPLETED` to `ACTIVE` if a void restores a credit. The owning member or a `SalonManager` may cancel a `PENDING` or `ACTIVE` package, moving it to the terminal `CANCELLED` state, after which `credits_remaining` is frozen and no further credit draws are permitted.

Completion is performed by the `Technician` (or a `FrontDeskAgent`), moving the visit's `service_status` from `IN_SERVICE` to `COMPLETED`; the visit must be `IN_SERVICE` to complete, else `ERR_VISIT_NOT_IN_SERVICE`. Completion stamps `ended_at` with the current clock and computes the finalized `final_total_cents` over the `ACTIVE` lines plus the service, applying the package credit and discount. It also performs the resource release: the chair moves from `OCCUPIED` to `SANITIZING` with its `sanitation_ready_at` set to `ended_at` plus the chair's `sanitation_minutes`; the technician moves from `BUSY` back to `AVAILABLE`; and the salon's `active_occupancy_count` drops by one.

The settlement calculation is evaluated in a pinned order. First, the discountable base is the service part plus the add-on part; retail is never discounted. Second comes the credit decision, evaluated before the discount: if the visit carries a `membership_package_id`, the package is `ACTIVE`, the visit's service is `package_eligible`, and the package's `credits_remaining` is greater than zero, then `used_package_credit` is set true, the service line is charged at zero because the credit covers it in full, and the package's `credits_remaining` is decremented by one (which may carry the package from `ACTIVE` to `DEPLETED`); otherwise `used_package_credit` is false and the service line is charged at its full `base_price_cents`. Third, the membership discount is applied to whatever service-plus-add-on remains chargeable after the credit decision: if a package is set and `ACTIVE`, the discount in cents is the chargeable service part plus the add-on part, multiplied by the package's `discount_bps`, divided by ten thousand, with the quotient floored to a whole cent; if no active package applies, the discount is zero. Fourth, `final_total_cents` is the chargeable service part plus the add-on part, minus the floored discount, plus the retail part. This finalized total generally differs from the provisional `estimate_total_cents` for the same set of lines.

Loyalty earned at completion follows from the finalized total. The `loyalty_earned` figure is computed by taking `final_total_cents` divided by 100 to express it in whole dollars, multiplying by the salon's `loyalty_earn_rate_bps`, dividing by 100, and flooring the result to a whole number of points. This earn is computed before any settle-time redemption: a redemption reduces the cash a guest owes at settle, never the points they earn from the visit.

### 3.7. Settling Payment, Redeeming Points, and No-Show Risk

Payment runs on its own dimension. The payment status of a visit begins `UNPAID` and may advance to `SETTLED` and, on a refund, to `REFUNDED`, and it advances independently of the service dimension except for one cross-dimension guard: a visit may only be settled once its `service_status` is `COMPLETED`. A `FrontDeskAgent` or `SalonManager` settles a completed visit, moving `payment_status` from `UNPAID` to `SETTLED`. Settling a visit whose service is not yet `COMPLETED` is rejected with `ERR_VISIT_NOT_COMPLETED`, and settling a visit that is not `UNPAID` is rejected with `ERR_VISIT_NOT_UNPAID`.

At settle the guest may optionally redeem loyalty points by supplying `redeem_points`. The points redeemed must not exceed the member's current `loyalty_balance`; a request to redeem more than the balance is refused with `ERR_INSUFFICIENT_LOYALTY`. When `redeem_points` is greater than zero, a `REDEEM` ledger entry of negative `redeem_points` is written, and the settlement cash is reduced by `redeem_points` multiplied by the point value of five cents per point, with the reduced amount floored at zero so a redemption can never push the bill below nothing. Regardless of redemption, settling writes an `EARN` ledger entry of the positive `loyalty_earned` computed at completion, and the member's `loyalty_balance` is recomputed from the full ledger.

No-shows feed a separate risk track on the member. Each un-expired no-show contributes one strike to `no_show_strikes`, and at the moment a no-show is recorded the member's standing is re-evaluated against two thresholds: a member whose un-expired strike count is at least four is moved to the terminal `BANNED` state; otherwise a member whose strike count is at least two is moved to `SUSPENDED`; below two strikes the member remains `ACTIVE`. The ban threshold is therefore the fourth strike and the suspend threshold the second strike, both evaluated as "at least." A `SUSPENDED` member cannot rejoin the queue until cleared, and a `BANNED` member is permanently barred.

A `SalonManager` may also adjust a member's loyalty manually, granting or deducting points; this writes an `ADJUSTMENT` ledger entry carrying the signed `points` and the member's `loyalty_balance` is recomputed. Each `LoyaltyLedgerEntry` records its `member_id`, the `service_visit_id` that produced it (null for a manual adjustment), an `entry_type` of `EARN`, `REDEEM`, `REVERSAL`, or `ADJUSTMENT`, and a signed `points` delta — positive for `EARN` and `ADJUSTMENT`, negative for `REDEEM`, and the opposite of the entry it reverses for a `REVERSAL`.

### 3.8. Undoing a Visit: The Compensating Void

A `SalonManager` may void a visit at any point while its `service_status` is not already `VOIDED`; voiding an already-voided visit is refused with `ERR_VISIT_ALREADY_VOIDED`. The void sets `service_status` to `VOIDED` and is the system's deepest compensating cascade, designed to leave the member's loyalty balance and the retail stock exactly where they stood before the visit existed.

The void unwinds in several coordinated effects. If the chair is still `OCCUPIED` by this visit, it is moved from `OCCUPIED` to `SANITIZING` with `sanitation_ready_at` set to the current clock plus the chair's `sanitation_minutes`, the assigned technician moves from `BUSY` back to `AVAILABLE`, and the salon's `active_occupancy_count` drops by one. If the visit had drawn a package credit — that is, `used_package_credit` is true — the package's `credits_remaining` is incremented by one, which may compensate a `DEPLETED` package back to `ACTIVE`. If the visit had already been settled — `payment_status` is `SETTLED` — then the payment moves to `REFUNDED`, a `REVERSAL` ledger entry of negative `loyalty_earned` is written to claw back the points the visit granted, and the `stock_qty` of each `RetailProduct` referenced by a `RETAIL` line is restored. Finally, every `ACTIVE` `VisitLineItem` on the visit is moved to `VOIDED`. Taken together, these effects guarantee that a voided visit leaves no residue in loyalty, inventory, or package credits.

### 3.9. Chair Sanitation and Out-of-Service Handling

A chair that has just hosted a completed or voided visit sits in `SANITIZING` until its window elapses. The window's end is `sanitation_ready_at`, computed as the visit's end instant plus the chair's `sanitation_minutes`. A `FrontDeskAgent` or `SalonManager` marks the chair back to `OPEN` once the window has elapsed — the logical clock must be at or after `sanitation_ready_at` — and a mark-sanitized attempted before that instant is refused with `ERR_SANITATION_WINDOW_OPEN`.

For maintenance, a `SalonManager` may take a chair out of service, but only when it is not `OCCUPIED`; taking an occupied chair out of service is rejected with `ERR_CHAIR_OCCUPIED`. A chair that is `OPEN` or `SANITIZING` may move to `OUT_OF_SERVICE`, and a `SalonManager` may later return an out-of-service chair to `OPEN`, which also clears its `sanitation_ready_at` back to null.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. The clock-setting capability returns `200 OK`. Each endpoint's request and response details are reconstructed from the workflow narratives in §3; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock to an absolute instant | SalonManager |
| POST | `/salon-svc/salons` | Create a salon (starts CLOSED) | SalonManager |
| GET | `/salon-svc/salons` | List salons | SalonManager, FrontDeskAgent, Technician, Member |
| GET | `/salon-svc/salons/{salonId}` | Get a salon | SalonManager, FrontDeskAgent, Technician, Member |
| POST | `/salon-svc/salons/{salonId}/open` | Open the salon for business | SalonManager |
| POST | `/salon-svc/salons/{salonId}/close` | Close the salon; cancel remaining queue tickets | SalonManager |
| POST | `/salon-svc/technicians` | Register a technician | SalonManager |
| GET | `/salon-svc/technicians` | List technicians | SalonManager, FrontDeskAgent, Technician |
| GET | `/salon-svc/technicians/{technicianId}` | Get a technician | SalonManager, FrontDeskAgent, Technician |
| POST | `/salon-svc/chairs` | Add a chair (starts OPEN) | SalonManager |
| GET | `/salon-svc/chairs` | List chairs | SalonManager, FrontDeskAgent, Technician |
| GET | `/salon-svc/chairs/{chairId}` | Get a chair | SalonManager, FrontDeskAgent, Technician |
| POST | `/salon-svc/chairs/{chairId}/mark-sanitized` | Mark a sanitizing chair open after its window | FrontDeskAgent, SalonManager |
| POST | `/salon-svc/chairs/{chairId}/take-out-of-service` | Take a non-occupied chair out of service | SalonManager |
| POST | `/salon-svc/chairs/{chairId}/return-to-service` | Return an out-of-service chair to open | SalonManager |
| POST | `/salon-svc/members` | Register a member | FrontDeskAgent, SalonManager |
| GET | `/salon-svc/members` | List members | SalonManager, FrontDeskAgent |
| GET | `/salon-svc/members/{memberId}` | Get a member | SalonManager, FrontDeskAgent, Member |
| POST | `/salon-svc/members/{memberId}/loyalty-adjustments` | Grant or deduct loyalty points | SalonManager |
| GET | `/salon-svc/loyalty-entries` | List loyalty ledger entries | SalonManager, FrontDeskAgent, Member |
| GET | `/salon-svc/loyalty-entries/{entryId}` | Get a loyalty ledger entry | SalonManager, FrontDeskAgent, Member |
| POST | `/salon-svc/packages` | Create a membership package | FrontDeskAgent, SalonManager |
| GET | `/salon-svc/packages` | List packages | SalonManager, FrontDeskAgent, Member |
| GET | `/salon-svc/packages/{packageId}` | Get a membership package | SalonManager, FrontDeskAgent, Member |
| POST | `/salon-svc/packages/{packageId}/activate` | Activate a pending package | Member, FrontDeskAgent |
| POST | `/salon-svc/packages/{packageId}/cancel` | Cancel a package | Member, SalonManager |
| POST | `/salon-svc/service-menu-items` | Create a quick-service menu item | SalonManager |
| GET | `/salon-svc/service-menu-items` | List menu items | SalonManager, FrontDeskAgent, Technician, Member |
| GET | `/salon-svc/service-menu-items/{serviceItemId}` | Get a service menu item | SalonManager, FrontDeskAgent, Technician, Member |
| POST | `/salon-svc/add-ons` | Create an add-on service | SalonManager |
| GET | `/salon-svc/add-ons` | List add-ons | SalonManager, FrontDeskAgent, Technician, Member |
| GET | `/salon-svc/add-ons/{addOnId}` | Get an add-on | SalonManager, FrontDeskAgent, Technician, Member |
| POST | `/salon-svc/retail-products` | Create a retail product | SalonManager |
| GET | `/salon-svc/retail-products` | List retail products | SalonManager, FrontDeskAgent, Member |
| GET | `/salon-svc/retail-products/{retailProductId}` | Get a retail product | SalonManager, FrontDeskAgent, Member |
| POST | `/salon-svc/queue-tickets` | Walk-in member joins the queue | FrontDeskAgent |
| GET | `/salon-svc/queue-tickets` | List queue tickets | SalonManager, FrontDeskAgent, Member |
| GET | `/salon-svc/queue-tickets/{ticketId}` | Get a queue ticket | SalonManager, FrontDeskAgent, Member |
| POST | `/salon-svc/queue-tickets/{ticketId}/call` | Call the next member up | FrontDeskAgent |
| POST | `/salon-svc/queue-tickets/{ticketId}/requeue` | Put a called member back in line | FrontDeskAgent |
| POST | `/salon-svc/queue-tickets/{ticketId}/no-show` | Record a no-show for a called member | FrontDeskAgent |
| POST | `/salon-svc/queue-tickets/{ticketId}/cancel` | Cancel a waiting or called ticket | FrontDeskAgent, Member |
| POST | `/salon-svc/service-visits` | Seat a called member onto a chair and technician | FrontDeskAgent |
| GET | `/salon-svc/service-visits` | List service visits | SalonManager, FrontDeskAgent, Technician, Member |
| GET | `/salon-svc/service-visits/{visitId}` | Get a service visit | SalonManager, FrontDeskAgent, Technician, Member |
| POST | `/salon-svc/service-visits/{visitId}/line-items` | Add an add-on or retail line to a visit | FrontDeskAgent, Technician |
| GET | `/salon-svc/service-visits/{visitId}/line-items` | List line items on a visit | SalonManager, FrontDeskAgent, Technician, Member |
| GET | `/salon-svc/visit-line-items` | List visit line items | SalonManager, FrontDeskAgent, Technician, Member |
| GET | `/salon-svc/visit-line-items/{lineId}` | Get a single visit line item | SalonManager, FrontDeskAgent, Technician, Member |
| POST | `/salon-svc/visit-line-items/{lineId}/void` | Void a single line item | FrontDeskAgent, Technician |
| POST | `/salon-svc/service-visits/{visitId}/complete` | Complete the service | Technician, FrontDeskAgent |
| POST | `/salon-svc/service-visits/{visitId}/settle` | Settle payment on a completed visit | FrontDeskAgent, SalonManager |
| POST | `/salon-svc/service-visits/{visitId}/void` | Void a visit and compensate | SalonManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_LINE_QUANTITY` | 409 |
| `ERR_LINE_TYPE_MISMATCH` | 409 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_SALON_NOT_FOUND` | 404 |
| `ERR_TICKET_NOT_FOUND` | 404 |
| `ERR_VISIT_NOT_FOUND` | 404 |
| `ERR_CHAIR_NOT_FOUND` | 404 |
| `ERR_TECHNICIAN_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_PACKAGE_NOT_FOUND` | 404 |
| `ERR_LINE_NOT_FOUND` | 404 |
| `ERR_SERVICE_ITEM_NOT_FOUND` | 404 |
| `ERR_ADDON_NOT_FOUND` | 404 |
| `ERR_RETAIL_NOT_FOUND` | 404 |
| `ERR_SALON_NOT_OPEN` | 409 |
| `ERR_TICKET_NOT_CALLED` | 409 |
| `ERR_VISIT_NOT_IN_SERVICE` | 409 |
| `ERR_VISIT_NOT_COMPLETED` | 409 |
| `ERR_VISIT_NOT_UNPAID` | 409 |
| `ERR_VISIT_ALREADY_VOIDED` | 409 |
| `ERR_CHAIR_NOT_OPEN` | 409 |
| `ERR_CHAIR_OCCUPIED` | 409 |
| `ERR_TECHNICIAN_NOT_AVAILABLE` | 409 |
| `ERR_MEMBER_NOT_ACTIVE` | 409 |
| `ERR_RECALL_LIMIT_REACHED` | 409 |
| `ERR_LICENSE_LAPSED` | 403 |
| `ERR_TECH_CERT_EXPIRED` | 403 |
| `ERR_MEMBER_BLOCKED` | 403 |
| `ERR_TECH_NOT_CERTIFIED` | 409 |
| `ERR_CHAIR_NOT_SANITIZED` | 409 |
| `ERR_SANITATION_WINDOW_OPEN` | 409 |
| `ERR_QUEUE_ORDER_VIOLATION` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_SALON_HAS_ACTIVE_VISITS` | 409 |
| `ERR_INSUFFICIENT_LOYALTY` | 402 |
| `ERR_STALE_SALON_VERSION` | 412 |
