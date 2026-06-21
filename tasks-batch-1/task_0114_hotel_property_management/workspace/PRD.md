# Hotel Property Management API — Product Requirements Document

## 1. Introduction

This document specifies the Hotel Property Management System (PMS), a server-side API that runs the operational core of a lodging property: reservations and group room blocks, rate plans spanning best-available, corporate, and packaged pricing, availability and controlled overbooking, room assignment and upgrades, guest folios and incidental postings, the nightly audit epoch, and the housekeeping cycle that turns rooms over between stays. The system is the single source of truth for what may be sold, to whom, at what price, and how the resulting charges accrue and settle.

The PMS is deliberately built around a small number of hard tensions that a property must reconcile every single day. Inventory must be sellable up to a configured fraction beyond the physical room count, yet never oversold past that ceiling. A reservation's projected cost is pinned at confirmation for credit purposes, but the money that actually lands on the folio accrues night by night and may diverge from that projection when a guest is upgraded mid-stay. A corporate account's credit must be honored without ever exceeding its limit. The night audit must close one business date and open the next atomically, sweeping no-shows, posting room charges, washing expired group blocks, and advancing the clock — all while the rest of the property is held still. The sections that follow define the entities, their state machines, the calculations that move money and inventory, and the precise validation order that keeps every counter honest.

Four operator roles share the property. A `RevenueManager` configures inventory and pricing and runs inventory controls. A `FrontDeskAgent` runs the desk — guests, reservations, assignment, upgrades, check-in and check-out, folios, and incidentals. A `NightAuditor` owns the audit epoch. A `Guest` is a self-service actor who books, cancels, and reads only their own reservations and folios. The benchmark for this API is that two engineers reading only this document arrive at byte-identical request and response contracts.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope conventions, and cross-cutting principles that apply across every endpoint. All resources live under the `/pms` mount.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing or malformed in either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. The system recognizes exactly four roles, spelled precisely as `RevenueManager`, `FrontDeskAgent`, `NightAuditor`, and `Guest`. When an authenticated caller attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The roles map to identity as follows. When `X-User-Role` is `RevenueManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same holds for `FrontDeskAgent` and for `NightAuditor`: in all three cases `X-User-ID` is an opaque operator identifier the server does not match against stored records. When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting `Guest`; ownership checks on any resource that references a `Guest` compare the resource's `guest_id` to `X-User-ID`. A `Guest` may create a reservation only when the supplied `guest_id` equals their `X-User-ID`, may cancel only their own reservation, and may read only their own reservation, folio, availability, and rate-plan data. An attempt by a `Guest` to act on another guest's resource is an `ERR_FORBIDDEN` (HTTP 403).

The role-to-operation map is the authority for permission checks. A `RevenueManager` exclusively creates hotels, room types, rooms, rate plans, and corporate accounts, closes rate plans, suspends and reinstates corporate accounts, and creates and closes group blocks. A `FrontDeskAgent` exclusively confirms reservations, assigns rooms, upgrades, checks in and out, disputes and resolves folios, and posts and voids incidentals. A `NightAuditor` exclusively opens, completes, and aborts night audit runs. Creating a reservation and cancelling a reservation are shared between `FrontDeskAgent` and `Guest`. Registering a guest and performing non-out-of-order housekeeping transitions are shared between `FrontDeskAgent` and `RevenueManager`; the out-of-order toggle is reserved to `RevenueManager`. All read (GET) endpoints are available to the roles named in the endpoint table of §4, with the `Guest` reads scoped to that guest's own data.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. A `limit` below 1, a `limit` above 100, or an `offset` below 0 is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

Unless an endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` reflects the full count of matching resources before pagination and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix — the `id` conveys identity only and is never client-supplied. Lifecycle-bearing resources additionally carry three system-managed fields: `created_at`, an ISO 8601 UTC timestamp with three fractional digits set at creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, including mutations driven by cascades from other resources; and `version`, an integer that starts at 1 and increases by exactly one on every mutation. The `version` field is the basis for optimistic concurrency control described in §2.6.

This full set of system fields applies to `Hotel`, `RoomType`, `Room`, `RatePlan`, `CorporateAccount`, `Guest`, `GroupBlock`, `Reservation`, `Folio`, `Incidental`, and `NightAuditRun`. The lone exception is the availability read-model: an availability cell is a pure computed projection materialized only inside the availability read response. It carries only an `id` and a `created_at`; it has no `updated_at` and no `version`, because it is never independently stored or mutated. Its `hotel_id` and `room_type_id` are grouping keys echoed from the query, not foreign keys to persisted rows.

### 2.5. Property Scope, Foreign-Key Resolution, and List Filtering

Every entity except the `Hotel` itself is owned by a property and carries a `hotel_id` foreign key to its owning `Hotel`. Resources are addressed directly by their own `id` under flat collections; relationships are expressed through foreign-key fields carried in the request body rather than nested URL paths. When a path-referenced resource identified by `{id}` does not exist within the resolved hotel scope, the request is rejected with `ERR_NOT_FOUND` (HTTP 404). When a foreign-key field supplied in a request body — any of `hotel_id`, `guest_id`, `rate_plan_id`, `room_type_id`, `group_block_id`, `room_id`, `folio_id`, or `corporate_account_id` — points at a resource that does not exist, the request is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 422). Path-identifier existence is checked before body foreign-key existence.

List endpoints accept optional filter parameters so that any child can be retrieved from its parent's identifier. Room types may be filtered by `hotel_id` and `code`. Rooms may be filtered by `hotel_id`, `room_type_id`, `assigned_reservation_id`, and `housekeeping_status`. Rate plans may be filtered by `hotel_id`, `corporate_account_id`, `kind`, and `status`. Corporate accounts may be filtered by `hotel_id` and `status`. Guests may be filtered by `hotel_id` and `email`. Group blocks may be filtered by `hotel_id`, `room_type_id`, `rate_plan_id`, and `status`. Reservations may be filtered by `hotel_id`, `guest_id`, `room_type_id`, `rate_plan_id`, `group_block_id`, `corporate_account_id`, `assigned_room_id`, `effective_room_type_id`, and `status`. Folios may be filtered by `hotel_id`, `reservation_id`, and `status`. Incidentals may be filtered by `hotel_id`, `folio_id`, `kind`, and `status`. Night audit runs may be filtered by `hotel_id` and `status`.

### 2.6. Optimistic Concurrency Control

Certain writes guard against acting on a stale view of a parent resource. Two such guards target a parent's `version` specifically. When a room is assigned to a reservation, the request must carry `expected_room_version` matching the target `Room`'s current `version`; if another agent has advanced that room's `version` since the caller last read it — for example, by binding the same physical room to a different reservation under the assignment rules — the request is rejected with `ERR_STALE_ROOM_VERSION` (HTTP 412). When a reservation is created as a pickup from a group block, the request must carry `expected_group_block_version` matching the target `GroupBlock`'s current `version`; if the block's allotment was advanced since the caller last read it — by another pickup or by a cutoff wash that legitimately changed the block — the create is rejected with `ERR_STALE_BLOCK_VERSION` (HTTP 412).

A second family of guarded writes carries an `expected_*_version` for the resource they mutate and reject a mismatch with the generic `ERR_STALE_VERSION` (HTTP 412): closing a rate plan requires `expected_rate_plan_version`; suspending or reinstating a corporate account requires `expected_corporate_account_version`; voiding an incidental requires `expected_folio_version` matching the owning folio; and opening, completing, or aborting a night audit requires `expected_hotel_version` matching the `Hotel`. In each case, when the supplied expected version does not equal the current `version` of the named resource, the write is rejected with the stated stale-version error before any state change is applied. Endpoints not named here do not take a version field.

### 2.7. The Night-Audit Posture Lock

A property is either in `OPEN` posture or `AUDIT_LOCK` posture, recorded on the `Hotel` as `posture`. While a night audit run is `IN_PROGRESS`, the property's `posture` is `AUDIT_LOCK`, and operational mutations are frozen: reservation create, confirm, check-in, check-out, cancel, assign-room, and upgrade; folio dispute and resolve; incidental post and void; and room housekeeping transitions are all rejected with `ERR_HOTEL_AUDIT_LOCKED` (HTTP 409) while the lock is held. Completing or aborting the audit returns the `posture` to `OPEN`. Configuration reads and the audit-run endpoints themselves are not subject to the lock. The property also carries a monotonic `audit_epoch` counter that begins at 0 and increases by one each time an audit completes, and a `current_business_date` that anchors the business-date boundary; the `timezone` field (an IANA zone, defaulting to `UTC`) defines that boundary.

### 2.8. Monetary, Counting, and Rounding Precision

All money in this system is carried in integer cents — there are no fractional-cent values anywhere in stored fields or response bodies. The single place rounding occurs is the per-night rate computation for a percentage-adjusted rate plan, described in §3.4: that per-night figure is rounded half up to a whole number of cents before it is multiplied by the number of nights. Every other monetary aggregate — projected charges, room charges, incidentals, payments, balances, and corporate outstanding balances — is an exact integer sum of already-integer cent values and involves no further rounding. Inventory and block figures (`sold_count`, `sellable_count`, `blocked_rooms`, `picked_up_rooms`, `washed_rooms`) are integer counts.

### 2.9. Cross-Entity Cascades and Consistency

Many operations in this system mutate more than one entity in a single request. Whenever a cascade touches a secondary entity — flipping a room's housekeeping status, recomputing a group block's pickup count, recomputing availability, or adding to a corporate account's outstanding balance — that secondary entity is itself mutated: its `updated_at` is refreshed and its `version` is incremented by one, exactly as for a direct write. The specific cascades are defined in the workflow narratives of §3; the universal rule here is that no counter or status is left silently inconsistent, and every cascade is a real, version-bumping mutation on the affected resource. Computed fields such as a folio's `balance_cents` or a corporate account's `outstanding_balance_cents` are recomputed synchronously inside the mutating request, never deferred.

### 2.10. Uniqueness Constraints

Several identifiers are unique within a property. A `RoomType`'s `code`, a `Room`'s `room_number`, a `RatePlan`'s `code`, and a `Guest`'s `email` must each be unique per hotel. An attempt to create a resource that would collide with an existing value on one of these is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Configuring the Property: Inventory and Pricing

A property is brought into being by a `RevenueManager`, who supplies the property `name`, the opening `current_business_date` (a `YYYY-MM-DD` calendar date), and optionally a `timezone` and an `overbooking_allowance_pct`. The allowance is a fraction between 0.0 and 0.25 inclusive that governs how far inventory may be sold beyond physical capacity — an allowance of 0.10 means a room type's sellable count is computed against 1.10 times its physical inventory. A new property opens with `posture` set to `OPEN`, `audit_epoch` at 0, and `version` at 1.

Room types are the unit of saleable inventory. Each `RoomType` is created against a `hotel_id` with a `code` (a short label such as KING or SUITE, unique per hotel), a `tier_rank` between 1 and 99 that orders the upgrade ladder so that a higher rank is more premium, a `physical_inventory` count of at least 1 saleable rooms, and a `base_rate_cents` of at least 0 that is the default nightly rate before any rate-plan adjustment. Physical rooms are then created against a `hotel_id` and `room_type_id` with a `room_number` unique per hotel; a freshly created `Room` begins life with `housekeeping_status` set to `CLEAN` and an empty `assigned_reservation_id`.

Rate plans encode how the base rate is modified and how a no-show is charged. A `RatePlan` is created against a `hotel_id` with a `code` unique per hotel, a `kind` of `BAR`, `CORPORATE`, or `PACKAGE`, an `adjustment_mode` of `PCT` or `FLAT`, an `adjustment_value`, a `no_show_policy` of `FIRST_NIGHT`, `FULL_STAY`, or `NONE`, and optionally a `corporate_account_id` and a `package_fee_cents`. The `corporate_account_id` is required when `kind` is `CORPORATE` and is null otherwise. The `package_fee_cents` is a per-stay add-on of at least 0 cents that is 0 unless `kind` is `PACKAGE`. A rate plan is created with `status` set to `ACTIVE`. A `RevenueManager` may later close a plan, moving its `status` to `CLOSED`; a `CLOSED` plan can no longer back a new reservation or a confirmation. Closing a plan requires `expected_rate_plan_version` (see §2.6) and increments the plan's `version` by one.

Corporate accounts carry direct-bill credit. A `CorporateAccount` is created against a `hotel_id` with a `name` and a `credit_limit_cents` of at least 0, the maximum outstanding direct-bill balance the account may carry. It opens with `status` set to `ACTIVE`, an `outstanding_balance_cents` of 0, and `version` 1. The `outstanding_balance_cents` is a computed field — the sum of the `balance_cents` of every corporate-billed folio whose reservation has reached `CHECKED_OUT` and whose `corporate_account_id` is this account — and is described further in §3.7. A `RevenueManager` may suspend an account, moving its `status` from `ACTIVE` to `SUSPENDED`, and may reinstate a suspended account, moving its `status` back to `ACTIVE`; both transitions require `expected_corporate_account_version` and each increments the account's `version`. While an account is `SUSPENDED`, confirming a new corporate reservation drawn on it is blocked.

Guests are registered against a `hotel_id` with a `full_name`, an `email` unique per hotel, and an optional `loyalty_tier` of `NONE`, `SILVER`, `GOLD`, or `PLATINUM` (defaulting to `NONE`). The loyalty tier drives complimentary-upgrade eligibility discussed in §3.5.

### 3.2. Group Blocks and Their Cutoff

A `RevenueManager` reserves rooms for an event by creating a `GroupBlock` against a `hotel_id`, naming the `room_type_id` the block draws from and the `rate_plan_id` that pickups off the block must use. The block carries a `block_name`, an `arrival_date` (the first night covered, inclusive), a `departure_date` (the checkout day, exclusive of the last night), a `cutoff_date`, and a `blocked_rooms` count of at least 1. A new block opens with `status` `OPEN`, a `picked_up_rooms` of 0, a `washed_rooms` of 0, and `version` 1.

The `picked_up_rooms` count is computed: it is the number of reservations attached to the block whose `status` is neither `CANCELLED` nor `NO_SHOW`. It is recomputed every time such a reservation is created, confirmed, cancelled, or no-showed against the block. While the block is `OPEN`, a reservation may pick up against it; pickup is allowed only while the block's `status` is `OPEN` and the property's `current_business_date` is on or before the block's `cutoff_date`. A pickup attempted after the cutoff has passed — meaning the block is already `WASHED` or `CLOSED`, or `current_business_date` is strictly later than `cutoff_date` — is rejected with `ERR_BLOCK_CUTOFF_PASSED` (HTTP 409). A group pickup's `rate_plan_id` must equal the block's `rate_plan_id`; a mismatch is rejected with `ERR_RATE_PLAN_MISMATCH` (HTTP 409).

When the night audit advances `current_business_date` to a value strictly greater than a block's `cutoff_date` while the block is still `OPEN`, the block washes: its `status` moves `OPEN → WASHED`, and its `washed_rooms` is set to the `blocked_rooms` minus the `picked_up_rooms`, or 0 if that difference would be negative. The washed rooms return to general sale, so availability for the block's `room_type_id` is recomputed across the covered dates. A `RevenueManager` may also close a block explicitly, moving its `status` from either `OPEN` or `WASHED` to `CLOSED`, after which the block accepts no further pickups; closing requires `expected_group_block_version` and is rejected with `ERR_BLOCK_HAS_PENDING_PICKUPS` (HTTP 409) if any reservation still attached to the block is in `HELD` status. Re-triggering a transition the block is not eligible for — closing a block already `CLOSED`, for instance — is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.3. Booking, Availability, and Overbooking

A reservation is opened by a `FrontDeskAgent` or by a `Guest` booking for themselves. The create payload supplies a `hotel_id`, a `guest_id`, a `room_type_id`, a `rate_plan_id`, an `arrival_date`, a `departure_date`, and — for a group pickup — a `group_block_id` together with the `expected_group_block_version` described in §2.6. The `departure_date` must be strictly later than the `arrival_date`; a request where it is not, or where a required field is missing, an enum value is invalid, or a date is not a well-formed `YYYY-MM-DD`, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A new reservation is created in `HELD` status. The server computes `nights` as the number of days from `arrival_date` to `departure_date` (which must be at least 1), sets `effective_room_type_id` equal to the booked `room_type_id`, copies `corporate_account_id` from the rate plan when that plan's `kind` is `CORPORATE` and leaves it null otherwise, and leaves `assigned_room_id`, `is_upgraded`, and `upgrade_is_comp` at their initial values (`assigned_room_id` null, `is_upgraded` false, `upgrade_is_comp` false). Creating a reservation also creates its `Folio` in `OPEN` status with `bill_to` derived (see §3.6), and recomputes availability for the covered dates. When a `group_block_id` is supplied, the block's `picked_up_rooms` is recomputed and the block's `version` is incremented.

Availability is the gate on every booking. For each room type and each single night, the sellable count is the floor of the room type's `physical_inventory` multiplied by one plus the property's `overbooking_allowance_pct`, minus the number of `OUT_OF_ORDER` rooms of that type. The sold count for a night is the number of reservations of that type whose stay interval covers the night — that is, whose `arrival_date` is on or before the night and whose `departure_date` is strictly after it — and whose `status` is neither `CANCELLED` nor `NO_SHOW`; a reservation's `effective_room_type_id` is used as its type when set, otherwise its `room_type_id`. A new reservation is admissible for a given night only when the current sold count plus one is at most the sellable count; selling the room that brings the sold count up to the sellable count is permitted, but the next one is not. If for any night in the half-open interval from `arrival_date` to `departure_date` the sold count plus one would exceed the sellable count, the booking is rejected with `ERR_NO_AVAILABILITY` (HTTP 409).

The availability read endpoint exposes this computation directly. A caller supplies a `room_type_id`, a `start_date`, and an `end_date`, optionally narrowed by `hotel_id`, and receives one cell per night across the requested range. Each cell echoes its `hotel_id` and `room_type_id`, names the single `stay_date` it tracks, and carries the computed `sold_count` and `sellable_count` for that night.

When a reservation is cancelled (permitted from `HELD` or `CONFIRMED`, by a `FrontDeskAgent` or by the owning `Guest`, while posture is `OPEN`), its `status` moves to `CANCELLED`. If a room was assigned, that room's `assigned_reservation_id` is cleared to null and the room's `version` is incremented, while its housekeeping status is left unchanged. Availability is recomputed for every covered night so the released inventory returns to sale, the reservation's `Folio` moves from `OPEN` to `CLOSED`, and if the reservation was attached to a group block, that block's `picked_up_rooms` is recomputed. Re-triggering cancel on a reservation already in a terminal state is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.4. Nightly Rate Computation

The nightly rate is the foundation of every room charge and no-show charge, and its rounding order is fixed. Start from the booked or effective room type's `base_rate_cents`. When the backing rate plan's `adjustment_mode` is `PCT`, the nightly figure is the base rate multiplied by one plus the `adjustment_value` divided by 100 — where `adjustment_value` is signed percentage points, so a value of -15 yields 15 percent off — and that product is rounded half up to a whole number of cents. This per-night rounding happens before any multiplication by the number of nights: the rate is rounded per night first and then multiplied, never summed and then rounded. When the `adjustment_mode` is `FLAT`, the nightly figure is the `base_rate_cents` plus the `adjustment_value` (signed cents), with no rounding step. In either mode the nightly figure is then floored at 0 cents, so it never goes negative. The per-stay `package_fee_cents` is never folded into the nightly rate; it is added exactly once where the forward projection is built, as described in §3.6.

### 3.5. Room Assignment, Inspection Cycle, and Upgrades

Physical rooms move through a housekeeping cycle. A room created `CLEAN` is inspected by a `FrontDeskAgent` (or `RevenueManager`) — transitioning `CLEAN → INSPECTED` — before it can receive a guest. After a stay, the room returns `DIRTY` and is cleaned `DIRTY → CLEAN` and then inspected again, forming the cycle `DIRTY → CLEAN → INSPECTED → OCCUPIED → DIRTY`. Each housekeeping transition is requested with a `target` status and the `expected_room_version`, and each increments the room's `version`. The system transitions `INSPECTED → OCCUPIED` automatically at check-in and `OCCUPIED → DIRTY` automatically at check-out; the desk drives only `DIRTY → CLEAN` and `CLEAN → INSPECTED`. A transition requested against a room not in the matching source status is rejected with `ERR_INVALID_STATE` (HTTP 409).

A room can also be taken out of service. A `RevenueManager` moves a room to `OUT_OF_ORDER` from any of `DIRTY`, `CLEAN`, or `INSPECTED`, provided the room's `assigned_reservation_id` is null; a room currently bound to a reservation cannot be taken out of order and the attempt is rejected with `ERR_ROOM_NOT_ASSIGNABLE` (HTTP 409). Taking a room out of order recomputes the sellable count for its room type, removing one sellable room, and increments the room's `version`. A `RevenueManager` restores an out-of-order room by transitioning `OUT_OF_ORDER → CLEAN`, which recomputes the sellable count to restore the room and increments `version`.

Assigning a specific physical room to a reservation is a `FrontDeskAgent` action carrying a `room_id` and the `expected_room_version` (the OCC guard of §2.6). The target room must not be `OUT_OF_ORDER`, must not already be bound to another reservation, and must belong to a room type whose `tier_rank` is at least the reservation's effective tier; a target that violates any of these is rejected with `ERR_ROOM_NOT_ASSIGNABLE` (HTTP 409). On success the reservation's `assigned_room_id` is set to the room, the room's `assigned_reservation_id` is set to the reservation, and the room's `version` is incremented.

An upgrade moves a reservation to a higher-tier room type and is a `FrontDeskAgent` action carrying a `target_room_type_id` and a `comp` boolean. The upgrade sets the reservation's `effective_room_type_id` to the target type, sets `is_upgraded` to true, and records `upgrade_is_comp` from the `comp` flag. Loyalty tier governs whether a complimentary upgrade is warranted: an upgrade marked complimentary carries no rate change. When the upgrade is not complimentary, the folio's forward projection is recomputed at the higher rate using the forward room-charge calculation of §3.6. Either way, availability is recomputed for both the source type and the target type across the covered dates, since the upgrade shifts the reservation's sold-count contribution from one type to the other. As with assignment, an upgrade target that is below the reservation's effective tier, out of order, or otherwise unassignable is rejected with `ERR_ROOM_NOT_ASSIGNABLE` (HTTP 409).

### 3.6. The Reservation Lifecycle, the Folio, and Forward Projection

Confirming a reservation is a `FrontDeskAgent` action moving its `status` from `HELD` to `CONFIRMED`, and it is the moment the stay's cost is pinned for credit purposes. Confirmation is permitted only while the property's posture is `OPEN`, the backing rate plan's `status` is `ACTIVE` (otherwise `ERR_RATE_PLAN_MISMATCH`, HTTP 409), and — for a corporate reservation — the backing `CorporateAccount`'s `status` is `ACTIVE` (otherwise `ERR_CORPORATE_SUSPENDED`, HTTP 409) and the corporate credit check passes. On confirmation the folio's `projected_charges_cents` is pinned by the forward room-charge calculation, and if the reservation is attached to a group block, the block's `picked_up_rooms` is recomputed. Confirming a reservation not in `HELD` is rejected with `ERR_INVALID_STATE` (HTTP 409).

The forward room-charge calculation projects the entire stay from a single rate snapshot taken at confirmation (or at a paid upgrade). It computes the nightly rate of §3.4 for the rate plan against the room type effective at that moment, multiplies it by the reservation's `nights`, and, when the rate plan's `kind` is `PACKAGE`, adds the `package_fee_cents` once for the whole stay. The result is stored as `projected_charges_cents`. This forward figure deliberately ignores any later per-night divergence — it is the number used for the corporate credit gate and for the guest's pre-stay estimate.

Every reservation has exactly one `Folio`, created with the reservation, carrying its `reservation_id` and the same `hotel_id`. The folio's `bill_to` is `CORPORATE` when the reservation carries a `corporate_account_id` and `GUEST` otherwise. The folio aggregates money through several computed fields. Its `room_charges_cents` is the sum of the `amount_cents` of all `POSTED` night-audit room-charge incidentals on it. Its `incidentals_cents` is the sum of the `amount_cents` of all `POSTED` agent-posted incidentals, where payment lines are stored as negative amounts. Its `payments_cents` is the sum of the `amount_cents` of `POSTED` payment incidentals (which are negative). Its `balance_cents` is the `room_charges_cents` plus the `incidentals_cents` — and because payment lines are stored negative, payments reduce the balance through that sum. Lines in `VOIDED` status are excluded from every one of these sums. While the folio is `OPEN` before check-out, the balance is provisional, reflecting only the nights and lines posted so far and still mutable; at and after the close that fires on check-out, no-show, or cancel, the balance is frozen at that instant as the total of all posted room charges and incidentals, and no later posting alters it.

Incidentals are posted to an `OPEN` folio by a `FrontDeskAgent` with a `hotel_id`, the `folio_id`, a `kind` of `CHARGE`, `PAYMENT`, or `ADJUSTMENT`, a `description`, and an `amount_cents` magnitude that the caller supplies as a non-negative value. The server stores `CHARGE` and `ADJUSTMENT` lines as positive and signs `PAYMENT` lines negative on store, sets the line's `status` to `POSTED`, and records `posted_by_kind` as `AGENT` for desk postings (the night audit posts its room-charge and no-show lines with `posted_by_kind` of `NIGHT_AUDIT`). Posting recomputes the folio totals. A `FrontDeskAgent` may void a posted line, moving its `status` to `VOIDED` so it drops out of every folio sum; voiding carries `expected_folio_version`, recomputes the folio totals, and increments the folio's `version`. A folio that is not in the status required for the requested operation — for instance, an attempt to post or void against a folio that is not `OPEN` — is rejected with `ERR_FOLIO_NOT_OPEN` (HTTP 409).

A folio may be frozen for review independent of the reservation. A `FrontDeskAgent` disputes an `OPEN` folio, moving its `status` `OPEN → DISPUTED`, after which no new incidental postings are accepted and check-out is blocked. The agent later resolves the dispute, moving `DISPUTED → OPEN` and re-opening the folio for postings and check-out. Both transitions require posture `OPEN`. A dispute or resolve requested against a folio not in the required source status is rejected with `ERR_INVALID_STATE` (HTTP 409).

Check-in is a `FrontDeskAgent` action moving the reservation `CONFIRMED → CHECKED_IN`. It requires posture `OPEN`, a non-null `assigned_room_id` (otherwise `ERR_NO_ROOM_ASSIGNED`, HTTP 409), the assigned room's `housekeeping_status` equal to `INSPECTED` (otherwise `ERR_ROOM_NOT_INSPECTED`, HTTP 409), and the property's `current_business_date` on or after the reservation's `arrival_date` (otherwise `ERR_ARRIVAL_NOT_REACHED`, HTTP 409). On check-in the assigned room cascades `INSPECTED → OCCUPIED` and its `version` is incremented.

Check-out is a `FrontDeskAgent` action moving the reservation `CHECKED_IN → CHECKED_OUT`. It requires posture `OPEN` and a folio that is not `DISPUTED` (otherwise `ERR_FOLIO_DISPUTED_CHECKOUT`, HTTP 409). On check-out the folio moves `OPEN → CLOSED` with its final balance frozen; the assigned room cascades `OCCUPIED → DIRTY`, its `assigned_reservation_id` is cleared to null, and its `version` is incremented; and when the folio's `bill_to` is `CORPORATE`, the folio's `balance_cents` is added to the corporate account's `outstanding_balance_cents` and that account's `version` is incremented. Confirming, checking in, or checking out a reservation that is not in the corresponding source status is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.7. Corporate Credit and the Direct-Bill Ledger

Corporate reservations are gated by credit at confirmation. When a corporate reservation is confirmed, the system computes a forward projection — the corporate account's current `outstanding_balance_cents` plus the folio's `projected_charges_cents` for the reservation being confirmed — and rejects the confirmation when that projected total is strictly greater than the account's `credit_limit_cents`, returning `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). A projected total exactly equal to the limit is allowed; only a strict overage is rejected.

The account's `outstanding_balance_cents` itself is the sum of the `balance_cents` of every folio that is billed to the account — that is, every folio whose `bill_to` is `CORPORATE` and whose reservation's `corporate_account_id` is this account and whose reservation has reached `CHECKED_OUT`. The ledger is advanced at check-out: when a corporate-billed reservation checks out, its frozen folio balance is added to the account's outstanding balance, as described in §3.6. The confirm-time credit gate thus weighs already-settled corporate stays against the forward projection of the stay being confirmed, never exceeding the configured limit.

### 3.8. The Night Audit Epoch

The night audit is the property's daily close, owned by a `NightAuditor`, and it runs as a locked epoch. Opening an audit creates a `NightAuditRun` against a `hotel_id` carrying `expected_hotel_version`; the run begins `IN_PROGRESS`, the property's `posture` moves to `AUDIT_LOCK`, and the `Hotel`'s `version` is incremented. Opening a second audit while one is already `IN_PROGRESS` for the property is rejected with `ERR_AUDIT_ALREADY_RUNNING` (HTTP 409). The run records the `business_date` being closed (the property's `current_business_date` at the start) and, at completion, an `epoch` equal to the property's `audit_epoch` plus one.

Completing the audit is a `NightAuditor` action carrying `expected_hotel_version` and is the atomic close of the business date. It is blocked when any `CHECKED_IN` reservation departing today — whose `departure_date` equals the `business_date` — still has a folio that is `OPEN` or `DISPUTED`, in which case the completion is rejected with `ERR_AUDIT_BLOCKED_OPEN_BALANCE` (HTTP 409). When the completion proceeds, it performs four cascades in turn. First, the no-show sweep: every reservation that is `CONFIRMED`, arriving today (its `arrival_date` equals the `business_date`), and not `CHECKED_IN` is flipped `CONFIRMED → NO_SHOW`, a no-show charge is posted to its folio per the rate plan's policy, its covered availability is recomputed to release inventory, its group block's `picked_up_rooms` is recomputed if it is a pickup, and its folio moves `OPEN → CLOSED`; the run's `no_show_count` records how many were swept. Second, the room-charge posting: each `CHECKED_IN` reservation receives one nightly room-charge incidental posted with `posted_by_kind` of `NIGHT_AUDIT` for the night being closed, computed by the chronological room-charge calculation below; the run's `room_postings_count` records how many were posted. Third, the clock advance: the property's `current_business_date` advances by one calendar day, its `audit_epoch` increases by one, and its `version` is incremented. Fourth, the block wash: every `GroupBlock` whose `cutoff_date` is strictly less than the new `current_business_date` and is still `OPEN` washes to `WASHED` with its `washed_rooms` set as in §3.2; the run's `washed_block_count` records how many washed. Finally the property's `posture` returns `AUDIT_LOCK → OPEN`, and the run's `status` becomes `COMPLETED`.

A `NightAuditor` may instead abort an in-progress run, carrying `expected_hotel_version`. An abort advances no date and posts nothing; it moves the property's `posture` back to `OPEN`, increments the `Hotel`'s `version`, and sets the run's `status` to `ABORTED`. Completing or aborting a run that is not `IN_PROGRESS` is rejected with `ERR_INVALID_STATE` (HTTP 409).

The chronological room-charge calculation accrues the stay night by night, in contrast to the forward projection of §3.6. For each audited night a `CHECKED_IN` reservation is open, the system re-reads the reservation's `effective_room_type_id` at post time, computes the nightly rate of §3.4 for the rate plan against that effective type, and posts a single `NIGHT_AUDIT` `CHARGE` incidental for that one night's nightly amount. The folio's `room_charges_cents` is then the sum of the `amount_cents` of all such posted night-audit charge lines. Because each night is posted at the rate in effect that night, a mid-stay upgrade changes only the nights posted after it and leaves already-posted nights untouched — so the chronological accrual diverges from the single-snapshot forward projection whenever an upgrade lands mid-stay.

The no-show charge is computed when the sweep flips a reservation to `NO_SHOW`, and its evaluation order is fixed: the nightly rate of §3.4 is resolved first for the rate plan against the reservation's booked `room_type_id`, and then the policy multiplier keyed off the rate plan's `no_show_policy` is applied. Under `FIRST_NIGHT` the charge is exactly one nightly rate. Under `FULL_STAY` the charge is the nightly rate multiplied by the reservation's `nights`. Under `NONE` the charge is 0. When the resulting charge is greater than 0, it is posted to the folio as a `NIGHT_AUDIT` `CHARGE` incidental described as a no-show charge.

### 3.9. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority order so that the same failing request always yields the same error. The order is: first authentication, rejecting a missing or malformed `X-User-ID` or `X-User-Role` with `ERR_UNAUTHENTICATED`; then authorization, rejecting a role not permitted for the operation (including a `Guest` acting on another guest's resource) with `ERR_FORBIDDEN`; then path-resource existence, rejecting an unknown `{id}` with `ERR_NOT_FOUND`; then body foreign-key existence, rejecting an unknown referenced resource with `ERR_REFERENCE_NOT_FOUND`; then body well-formedness, rejecting malformed bodies, bad enums, a `departure_date` not strictly after `arrival_date`, bad date formats, or out-of-bound pagination with `ERR_INVALID_REQUEST` (or `ERR_PAGINATION_INVALID` for the pagination case); then posture, rejecting an operational mutation while the property is `AUDIT_LOCK` with `ERR_HOTEL_AUDIT_LOCKED`; then transition validity, rejecting a target not in a valid state for the requested transition with `ERR_INVALID_STATE`. Beyond these come the business checks in their own order: rate-plan applicability (`ERR_RATE_PLAN_MISMATCH`), then group-block cutoff (`ERR_BLOCK_CUTOFF_PASSED`), then room assignability (`ERR_ROOM_NOT_ASSIGNABLE`), then availability (`ERR_NO_AVAILABILITY`), then corporate credit (`ERR_CREDIT_LIMIT_EXCEEDED`), and finally the optimistic-concurrency stale-version checks (`ERR_STALE_ROOM_VERSION` on assign-room, `ERR_STALE_BLOCK_VERSION` on a block pickup). Authentication is checked before authorization, existence before well-formedness, posture before transition validity, and the OCC checks last, so that a higher-priority failure always masks a lower-priority one on the same request.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state transition and every cascade-bearing action — return a `200 OK` status code. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pms/hotels` | Create a hotel (property) | RevenueManager |
| GET | `/pms/hotels/{id}` | Get hotel | RevenueManager, FrontDeskAgent, NightAuditor, Guest |
| POST | `/pms/room-types` | Create a room type | RevenueManager |
| GET | `/pms/room-types/{id}` | Get room type | RevenueManager, FrontDeskAgent, NightAuditor, Guest |
| GET | `/pms/room-types` | List room types | RevenueManager, FrontDeskAgent, NightAuditor, Guest |
| POST | `/pms/rooms` | Create a physical room | RevenueManager |
| GET | `/pms/rooms/{id}` | Get room | RevenueManager, FrontDeskAgent, NightAuditor |
| GET | `/pms/rooms` | List rooms | RevenueManager, FrontDeskAgent, NightAuditor |
| POST | `/pms/rooms/{id}/housekeeping` | Transition a room's housekeeping status | FrontDeskAgent, RevenueManager |
| POST | `/pms/rate-plans` | Create a rate plan (BAR/CORPORATE/PACKAGE) | RevenueManager |
| GET | `/pms/rate-plans/{id}` | Get rate plan | RevenueManager, FrontDeskAgent, NightAuditor, Guest |
| GET | `/pms/rate-plans` | List rate plans | RevenueManager, FrontDeskAgent, NightAuditor, Guest |
| POST | `/pms/rate-plans/{id}/close` | Close a rate plan | RevenueManager |
| POST | `/pms/corporate-accounts` | Create a corporate account | RevenueManager |
| GET | `/pms/corporate-accounts/{id}` | Get corporate account | RevenueManager, FrontDeskAgent, NightAuditor |
| GET | `/pms/corporate-accounts` | List corporate accounts | RevenueManager, FrontDeskAgent, NightAuditor |
| POST | `/pms/corporate-accounts/{id}/suspend` | Suspend a corporate account | RevenueManager |
| POST | `/pms/corporate-accounts/{id}/reinstate` | Reinstate a suspended corporate account | RevenueManager |
| POST | `/pms/guests` | Register a guest | FrontDeskAgent, RevenueManager |
| GET | `/pms/guests/{id}` | Get guest | RevenueManager, FrontDeskAgent, NightAuditor, Guest |
| GET | `/pms/guests` | List guests | RevenueManager, FrontDeskAgent, NightAuditor |
| POST | `/pms/group-blocks` | Create a group block | RevenueManager |
| GET | `/pms/group-blocks/{id}` | Get group block | RevenueManager, FrontDeskAgent, NightAuditor |
| GET | `/pms/group-blocks` | List group blocks | RevenueManager, FrontDeskAgent, NightAuditor |
| POST | `/pms/group-blocks/{id}/close` | Close a group block | RevenueManager |
| POST | `/pms/reservations` | Create a reservation (HELD) | FrontDeskAgent, Guest |
| GET | `/pms/reservations/{id}` | Get reservation | RevenueManager, FrontDeskAgent, NightAuditor, Guest |
| GET | `/pms/reservations` | List reservations | RevenueManager, FrontDeskAgent, NightAuditor, Guest |
| POST | `/pms/reservations/{id}/confirm` | Confirm a HELD reservation | FrontDeskAgent |
| POST | `/pms/reservations/{id}/assign-room` | Assign a physical room to a reservation | FrontDeskAgent |
| POST | `/pms/reservations/{id}/upgrade` | Upgrade a reservation to a higher-tier type | FrontDeskAgent |
| POST | `/pms/reservations/{id}/check-in` | Check in a CONFIRMED reservation | FrontDeskAgent |
| POST | `/pms/reservations/{id}/check-out` | Check out a CHECKED_IN reservation | FrontDeskAgent |
| POST | `/pms/reservations/{id}/cancel` | Cancel a HELD/CONFIRMED reservation | FrontDeskAgent, Guest |
| GET | `/pms/folios/{id}` | Get folio by id | RevenueManager, FrontDeskAgent, NightAuditor, Guest |
| GET | `/pms/folios` | List folios | RevenueManager, FrontDeskAgent, NightAuditor, Guest |
| POST | `/pms/folios/{id}/dispute` | Freeze a folio pending review | FrontDeskAgent |
| POST | `/pms/folios/{id}/resolve` | Re-open a disputed folio | FrontDeskAgent |
| POST | `/pms/incidentals` | Post an incidental line to a folio | FrontDeskAgent |
| GET | `/pms/incidentals/{id}` | Get incidental line by id | RevenueManager, FrontDeskAgent, NightAuditor, Guest |
| GET | `/pms/incidentals` | List incidentals | RevenueManager, FrontDeskAgent, NightAuditor, Guest |
| POST | `/pms/incidentals/{id}/void` | Void a posted incidental line | FrontDeskAgent |
| POST | `/pms/night-audit-runs` | Open a night audit run | NightAuditor |
| GET | `/pms/night-audit-runs/{id}` | Get a night audit run | RevenueManager, NightAuditor |
| GET | `/pms/night-audit-runs` | List night audit runs | RevenueManager, NightAuditor |
| POST | `/pms/night-audit-runs/{id}/complete` | Complete the audit | NightAuditor |
| POST | `/pms/night-audit-runs/{id}/abort` | Abort an in-progress audit | NightAuditor |
| GET | `/pms/availability` | Read per-night availability for a room type | RevenueManager, FrontDeskAgent, NightAuditor, Guest |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_HOTEL_AUDIT_LOCKED` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_RATE_PLAN_MISMATCH` | 409 |
| `ERR_ROOM_NOT_ASSIGNABLE` | 409 |
| `ERR_BLOCK_CUTOFF_PASSED` | 409 |
| `ERR_BLOCK_HAS_PENDING_PICKUPS` | 409 |
| `ERR_NO_AVAILABILITY` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_CORPORATE_SUSPENDED` | 409 |
| `ERR_ROOM_NOT_INSPECTED` | 409 |
| `ERR_NO_ROOM_ASSIGNED` | 409 |
| `ERR_FOLIO_NOT_OPEN` | 409 |
| `ERR_FOLIO_DISPUTED_CHECKOUT` | 409 |
| `ERR_AUDIT_BLOCKED_OPEN_BALANCE` | 409 |
| `ERR_AUDIT_ALREADY_RUNNING` | 409 |
| `ERR_ARRIVAL_NOT_REACHED` | 409 |
| `ERR_STALE_ROOM_VERSION` | 412 |
| `ERR_STALE_BLOCK_VERSION` | 412 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_PAGINATION_INVALID` | 400 |
