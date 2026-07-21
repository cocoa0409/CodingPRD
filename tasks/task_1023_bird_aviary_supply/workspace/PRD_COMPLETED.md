# Bird & Aviary Supply API — Product Requirements Document

## 1. Introduction

The Bird & Aviary Supply platform is the operational backbone for a specialty retailer that trades in live birds, feed, grooming and boarding services, cage construction, and the regulatory paperwork that surrounds all of it. The business sits at the intersection of two hard problems: **regulatory compliance** — every bird of a protected species may only be listed or sold when a valid CITES permit authorizes trade for that species — and **health quarantine** — no bird reaches the sales floor until it has served a mandatory holding window and passed a diagnostic risk assessment. On top of this livestock spine, the same store runs time-boxed services (cage boarding and wing/nail grooming), recurring feed subscriptions with perishable fresh-feed options, and made-to-order cage builds, all settled against a per-customer store-credit wallet.

This document specifies the REST API that governs these workflows. It defines the entities and their lifecycles, the calculations that price services and score health risk, the compliance cascades that ripple through the catalog when a permit is revoked or expires, and the concurrency and inventory-conservation invariants that keep the system consistent. The API is consumed by four distinct operator populations — customers, aviary floor staff, compliance officers, and store management — each of whom owns a different surface of the system. Because the platform is evaluated deterministically against a fixed logical clock, temporal behavior (permit expiry, quarantine hold windows, boarding nights, grooming no-shows) is driven by a server-controlled clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting invariants that apply across every endpoint. Domain workflows that build on these rules are described in Section 3.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 400). This check precedes all others.

The system recognizes exactly four roles, spelled precisely as follows: `Customer`, `AviaryStaff`, `ComplianceOfficer`, and `StoreManager`. Each role owns a distinct surface of operations. When a role attempts an operation it is not authorized to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). In broad strokes: a `Customer` owns and manages their own feed subscriptions, boarding reservations, grooming appointments, and special orders; `AviaryStaff` handle livestock registration, the quarantine and testing lifecycle, listing and sale of birds, boarding check-in and check-out, and grooming service completion; a `ComplianceOfficer` owns species records and the entire CITES permit lifecycle; and a `StoreManager` administers customers, cages, grooming stations, inventory, pricing configuration, the order build lifecycle, refunds, and the test-driving clock. All four roles may perform read (GET) operations across the catalog.

The `Customer` role is **entity-backed**: when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`, and ownership checks on any resource that references a customer compare that resource's `customer_id` foreign key to `X-User-ID`. A customer acting on a subscription, boarding reservation, grooming appointment, or special order whose `customer_id` does not equal their `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The other three roles — `AviaryStaff`, `ComplianceOfficer`, and `StoreManager` — are **opaque**: their `X-User-ID` is an operator identifier not tied to any persisted entity. The server may accept and record it but never compares it to any entity's `id` for ownership purposes.

**Global validation order.** When several checks could reject the same request, they are evaluated in a fixed priority sequence, and the first failing check determines the error returned. The order is: (1) presence and well-formedness of the user-context headers (`ERR_MISSING_USER_CONTEXT`); (2) role authorization for the operation (`ERR_FORBIDDEN_ROLE`); (3) for customer-owned mutations, resource ownership (`ERR_NOT_RESOURCE_OWNER`); (4) existence of every path and body resource id, validated left-to-right (the `ERR_*_NOT_FOUND` family, HTTP 404); (5) request-body well-formedness — required fields present, correct types, valid enum members, and interval/quantity sanity such as `planned_check_out` strictly after `planned_check_in`, `slot_end` strictly after `slot_start`, `capacity` at least 1, `bird_count` at least 1, and `build_qty` at least 1 (`ERR_INVALID_REQUEST`, HTTP 400); (6) state-machine legality of the requested transition (`ERR_INVALID_STATE` and its domain-specific variants, HTTP 409); (7) optimistic-concurrency version match on cage configuration updates (`ERR_STALE_CAGE_VERSION`, HTTP 412); (8) business-referential compliance checks on bird listing and sale; (9) quarantine safety checks; (10)–(11) temporal overlap checks for boarding and grooming; (12) capacity and service-availability checks; (13) inventory sufficiency; (14) wallet sufficiency; and (15) customer-suspension checks. Deeper business rules within a single endpoint are evaluated in this same relative order unless a workflow narrative in Section 3 states otherwise.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the server's real wall-clock time (not the logical clock of Section 2.7).
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. A `limit` outside its bounds is clamped into the `[1, 100]` range and a negative `offset` is clamped to 0 rather than rejected, and a non-integer `limit` or `offset` falls back to its default. Unless a specific endpoint states otherwise, list results are ordered by their `created_at` timestamp in ascending order. Every list response carries the pagination bookkeeping — `limit`, `offset`, `total_count`, and `has_more` — inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every persisted resource in this system carries a system-managed identity and audit set. The `id` is a server-minted UUID with no type prefix; clients never supply it. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. Both `created_at` and `updated_at` are stamped from the server's real wall-clock time, independent of the logical clock of Section 2.7, so their monotonic ordering follows creation/mutation order. Because every entity in this domain is mutable, each also carries an `updated_at` field (ISO 8601 UTC, three fractional digits) refreshed on every mutation, and an integer `version` that begins at 1 on creation and increments by one on every mutation that changes the resource. The `version` field is the basis for the optimistic-concurrency mechanism described in Section 2.5.

Derived and cascade-driven changes count as mutations: when the server recomputes a field such as `listed_bird_count`, `current_occupancy`, `quantity_allocated`, or a status transition driven by a compliance cascade, the affected resource's `updated_at` is refreshed and its `version` is incremented, exactly as a direct client edit would do.

### 2.5. Optimistic Concurrency Control on Cage Configuration

Cage configuration is the one place where a plain field update carries no state precondition that would otherwise stop a second writer from clobbering the first, so it is protected by optimistic concurrency control keyed on the cage's `version`. A request to update a cage unit's mutable configuration must carry `expected_cage_version`, and this field is **required**, not optional, on that operation. The server compares `expected_cage_version` against the target `CageUnit`'s current `version` as soon as that field is confirmed present and integer-valued, ahead of validating the specific mutable fields (`nightly_rate_cents`, `capacity`, `status`) carried in the request body; a stale version is therefore reported even when one of those accompanying field values is itself malformed. If they do not match — for example, because a boarding check-in already advanced the cage's `version` and occupancy since the client last read it — the update is rejected with `ERR_STALE_CAGE_VERSION` (HTTP 412), preventing the client from overwriting a configuration it never observed. A successful update applies the changes and increments the cage's `version` by one. No other endpoint in the system takes a version field; the concurrency guard exists solely for cage configuration updates.

### 2.6. Monetary Amounts, the Store-Credit Wallet, and Rounding

All monetary amounts in the system are integer counts of cents, stored in fields suffixed `_cents`. No amount is ever represented as a fractional-cent or floating value in a stored field. Where a calculation multiplies by a rate or percentage and could produce a fractional-cent intermediate — the subscription club discount and the per-line special-order tax — the result is rounded to a whole number of cents using the **round half up** convention (a value exactly at the half-cent rounds away from zero, upward).

Each `Customer` holds a store-credit balance in `wallet_credit_cents`. Charges debit this balance and refunds credit it back. The wallet is a floor-zero resource: no debit — a feed-subscription charge, a special-order payment, a boarding settlement, or a grooming fee — may ever drive `wallet_credit_cents` below zero. Any debit that would do so is rejected with `ERR_INSUFFICIENT_WALLET` (HTTP 402), and the balance is left untouched. Store managers may top up a wallet directly by crediting an `amount_cents` adjustment.

### 2.7. The Logical Clock and Temporal Evaluation

All time-dependent behavior is governed by a server-controlled **logical clock**, never real wall-clock time. On startup the clock reads exactly `2026-07-01T00:00:00Z`, and it holds that value until an operator sets it. A test-driving capability, available to any role, advances the clock to a supplied `to_iso8601` instant. Quarantine hold windows, boarding nights, grooming no-show eligibility, and CITES permit expiry are all measured against this clock.

Permit expiry is evaluated **lazily**. A permit does not need an explicit call to expire; whenever a permit or its owning species is read or acted upon after the clock has advanced to or past the permit's `valid_until` instant, the permit is treated as `EXPIRED` and the associated compliance cascade (Section 2.10) is applied at that moment.

### 2.8. Nested Resource Retrieval and Left-to-Right Validation

Several read endpoints expose a child collection reachable from a parent — the CITES permits of a species, and the quarantine records of a bird. For any request whose path contains more than one resource identifier, the server validates the identifiers strictly left to right and rejects with the 404 error for the **first** identifier that does not resolve. A request for the quarantine records of a non-existent bird therefore fails with `ERR_BIRD_NOT_FOUND` before the child collection is ever consulted. The same left-to-right existence discipline applies to every mutating endpoint that references ids in its path or body: each referenced entity must resolve, in path-then-body order, before any state or business rule is evaluated.

Each entity type has its own not-found error, all returning HTTP 404: an unresolved customer yields `ERR_CUSTOMER_NOT_FOUND`, a species `ERR_SPECIES_NOT_FOUND`, a CITES permit `ERR_PERMIT_NOT_FOUND`, a bird `ERR_BIRD_NOT_FOUND`, a quarantine record `ERR_QUARANTINE_NOT_FOUND`, a cage unit `ERR_CAGE_NOT_FOUND`, a boarding reservation `ERR_RESERVATION_NOT_FOUND`, a grooming station `ERR_STATION_NOT_FOUND`, a grooming appointment `ERR_APPOINTMENT_NOT_FOUND`, a feed subscription `ERR_SUBSCRIPTION_NOT_FOUND`, an inventory item `ERR_INVENTORY_NOT_FOUND`, and a special order `ERR_ORDER_NOT_FOUND`.

### 2.9. Inventory Conservation

Every `InventoryItem` tracks two counts: `quantity_on_hand` (unallocated units available) and `quantity_allocated` (units reserved to active subscriptions and orders). These two counts obey a conservation invariant across every allocate/release pair: the sum of `quantity_on_hand` and `quantity_allocated` is constant. To **allocate** n units, the system subtracts n from `quantity_on_hand` and adds n to `quantity_allocated`. To **release** n units, it subtracts n from `quantity_allocated` and adds n back to `quantity_on_hand`. Neither count may ever go negative. A distinct third movement, **consume**, occurs only when a built order is delivered: n units are subtracted from `quantity_allocated` without being returned to `quantity_on_hand`, because the finished goods physically leave the store. Before any allocation, the system verifies that `quantity_on_hand` is at least the number of units requested; if it is not, the allocation is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 409).

### 2.10. Compliance Cascades and Hierarchical Consistency

The catalog is a graph of cross-referencing entities, and certain compliance events ripple through it. When a CITES permit is revoked, or lazily expires, the owning species and all of its currently-listed birds are brought into a consistent restricted state in one cascade: the `Species` moves to `RESTRICTED`, every `Bird` of that species whose `status` is `LISTED` is moved to `SUSPENDED`, and the species' derived `listed_bird_count` is recomputed to reflect the birds that just left the listed population. Each entity touched by the cascade is an independent mutation that refreshes `updated_at` and increments `version`. Conversely, when a fresh permit restores a species to `ACTIVE`, suspended birds of that species become eligible to be re-listed, which again recomputes `listed_bird_count`. The `listed_bird_count` on a species is always the count of that species' birds in `LISTED` status and is recomputed whenever a bird of the species changes listed membership.

## 3. Business Logic & Workflows

### 3.1. Customers, Club Membership, and the Wallet

A `StoreManager` registers a customer by supplying a `full_name` and an `email`. A new customer begins in `ACTIVE` `status`, with `club_tier` of `NONE` and `wallet_credit_cents` of 0. The store manager may later credit the wallet by posting an `amount_cents` adjustment, which is added to `wallet_credit_cents`.

A customer's `club_tier` is not set at creation and is never a free-form field on other operations; it is changed only through the dedicated club-membership operation, which accepts a `club_tier` of `NONE`, `SILVER`, or `GOLD`. The tier matters because it discounts feed subscriptions (Section 3.7). A store manager may also suspend a customer, moving `status` from `ACTIVE` to `SUSPENDED`. A `SUSPENDED` customer may not open new feed subscriptions or special orders, nor be the buyer of a bird; such attempts are rejected with `ERR_CUSTOMER_SUSPENDED`.

### 3.2. Species Registration and the CITES Permit Lifecycle

A `ComplianceOfficer` creates a species record by supplying its `common_name`, `scientific_name`, and `cites_appendix`. The appendix is one of `I`, `II`, `III`, or `NONE`, and it drives two derived facts: the species' `permit_required` flag is computed as true when `cites_appendix` is `I`, `II`, or `III`, and false when it is `NONE`; and the appendix sets the base health-risk weight used in quarantine scoring (Section 3.3). A new species begins with `status` `ACTIVE` and `listed_bird_count` of 0.

CITES permits move through a branching lifecycle with a revision loop. A compliance officer creates a permit against a species by supplying the `species_id`, an external `permit_number`, and a `valid_until` expiry instant; the permit is born in `DRAFT`. Submitting a permit advances it from `DRAFT` to `SUBMITTED`. A submitted permit can be sent back for rework, returning it from `SUBMITTED` to `DRAFT` — the cyclic revision edge — or it can be approved. Approval requires the permit to be `SUBMITTED` and requires its `valid_until` to be strictly after the current logical clock; approving an already-lapsed permit is rejected with `ERR_PERMIT_EXPIRED_INPUT` (HTTP 400). A successful approval moves the permit from `SUBMITTED` to `APPROVED` and, as a side effect, sets the owning `Species.status` to `ACTIVE`, authorizing trade.

An `APPROVED` permit can be revoked, moving it to the terminal `REVOKED` state and triggering the compliance cascade of Section 2.10: the owning `Species` becomes `RESTRICTED`, every `LISTED` bird of that species is moved to `SUSPENDED`, and `listed_bird_count` is recomputed downward. The same cascade fires when an approved permit lazily reaches the terminal `EXPIRED` state because the logical clock has advanced to or past its `valid_until`; expiry is evaluated the next time the permit or its species is read or acted upon. The permit states are `DRAFT`, `SUBMITTED`, `APPROVED`, `REVOKED`, and `EXPIRED`, with `REVOKED` and `EXPIRED` terminal. Any of these transitions attempted from an illegal source state is rejected as an invalid state transition (`ERR_INVALID_STATE`, HTTP 409).

### 3.3. Livestock Intake, Quarantine, and Health Testing

An `AviaryStaff` member registers a livestock bird by supplying its `species_id`, a leg-band `band_code` (nominally unique, though uniqueness is not enforced), a `list_price_cents` sale price, and an optional `imported` flag that defaults to false. A new bird begins in `INTAKE` with a null `housing_cage_id`. The bird's `status` proceeds through `INTAKE`, `IN_QUARANTINE`, `CLEARED`, `LISTED`, `SOLD`, `REJECTED`, and `SUSPENDED`, with `SOLD` and `REJECTED` terminal.

**Starting quarantine.** Moving a bird from `INTAKE` to `IN_QUARANTINE` requires the bird to be in `INTAKE` and requires a supplied `cage_id` naming a `HOUSING`-class cage whose `current_occupancy` is strictly below its `capacity`; if no such capacity exists on the named cage, the request is rejected with `ERR_NO_HOUSING_CAPACITY`. On success the server opens a new `QuarantineRecord` in `OPEN` for the bird, sets the bird's `housing_cage_id` to the chosen cage, increments that cage's `current_occupancy` by one (moving the cage's `status` to `OCCUPIED` if occupancy now equals capacity), and computes the bird's **provisional** risk score. The provisional score, stored in `provisional_risk_score`, is the species base weight — 40 for appendix `I`, 25 for `II`, 15 for `III`, and 5 for `NONE` — plus an import penalty of 20 points when the bird is imported, and nothing extra otherwise.

**The quarantine record.** A quarantine record captures the `bird_id` it covers, the `opened_at` instant it was opened, a computed `min_clear_at`, a running `failed_test_count` and `retest_count` (both starting at 0), and a `status` of `OPEN`, `UNDER_TEST`, `CLEARED`, or `FAILED`, with `CLEARED` and `FAILED` terminal. The `min_clear_at` is the `opened_at` instant plus a mandatory minimum hold of 14 days (that is, 14 times 86,400 seconds); a record may not be cleared while the current clock is before `min_clear_at`. The boundary is inclusive: clearing at an instant exactly equal to `min_clear_at` is permitted.

**Testing loop.** Diagnostic testing is a cycle. Starting a test moves an `OPEN` record to `UNDER_TEST`; starting a test on a record that is not `OPEN` is rejected with `ERR_QUARANTINE_NOT_OPEN`. From `UNDER_TEST`, recording a test result carries a `result` value. A `result` of `FAIL` increments `failed_test_count` by one and leaves the record in `UNDER_TEST` (a self-loop). A `result` of `RETEST` increments `retest_count` by one and returns the record to `OPEN` for another round. Recording a result on a record that is not `UNDER_TEST` is rejected with `ERR_QUARANTINE_NOT_OPEN`.

**Clearing.** Clearing a record is permitted from `OPEN` or `UNDER_TEST` (as is failing, below; a clear or fail attempted from a terminal `CLEARED` or `FAILED` record is rejected with `ERR_INVALID_STATE`) and is guarded by two conditions evaluated in this order: first, the current clock must be at or after `min_clear_at`, else `ERR_QUARANTINE_TOO_EARLY`; second, the bird's **final** risk score must be strictly below the failure threshold of 60, else `ERR_RISK_TOO_HIGH_TO_CLEAR`. The final risk score, stored in `final_risk_score`, is the species base weight (40/25/15/5 for `I`/`II`/`III`/`NONE`) plus 15 points for each failed test counted in `failed_test_count` plus 5 points for each retest counted in `retest_count`; unlike the provisional score, the final score ignores the import flag. A score of 60 or higher cannot be cleared and must instead be failed. On a successful clear, the record moves to `CLEARED` and the owning bird bubbles up from `IN_QUARANTINE` to `CLEARED`, with its `final_risk_score` set at that moment.

**Failing.** Failing a record is permitted from `OPEN` or `UNDER_TEST` and moves it to `FAILED`. This bubbles the owning bird to the terminal `REJECTED` state and triggers a cage-release cascade: the bird's `final_risk_score` is computed and recorded, the housing cage's `current_occupancy` is decremented by one, the bird's `housing_cage_id` is cleared, and the cage's `status` is recomputed to `AVAILABLE` once occupancy drops below capacity.

### 3.4. Listing, Suspension, and Sale of Birds

Once a bird is `CLEARED`, an `AviaryStaff` member can list it for sale, moving it from `CLEARED` to `LISTED`. Listing is a compliance-gated action: the owning `Species.status` must be `ACTIVE`, else the request is rejected with `ERR_SPECIES_RESTRICTED`; and if the species has `permit_required` true, an `APPROVED`, non-expired CITES permit must exist for that species, else `ERR_PERMIT_NOT_APPROVED`. On success the species' `listed_bird_count` is incremented by one.

When a permit is revoked or expires, the cascade of Section 2.10 moves every `LISTED` bird of the now-`RESTRICTED` species to `SUSPENDED` and decrements `listed_bird_count` accordingly. A suspended bird can be re-listed once a fresh approved permit has restored the species: re-listing moves the bird from `SUSPENDED` back to `LISTED`, requires the bird to be `SUSPENDED` and the owning `Species.status` to be `ACTIVE` again, and increments `listed_bird_count` by one. As with initial listing, re-listing a bird of a restricted species is rejected with `ERR_SPECIES_RESTRICTED`.

Selling a `LISTED` bird requires a `buyer_customer_id` and three conditions: the bird must be `LISTED`; the owning `Species.status` must be `ACTIVE`, else `ERR_SPECIES_RESTRICTED`; and the buyer customer's `status` must be `ACTIVE`, else `ERR_CUSTOMER_SUSPENDED`. On a successful sale the bird moves to the terminal `SOLD` state, the species' `listed_bird_count` is decremented by one, the housing cage's `current_occupancy` is decremented by one with the cage `status` recomputed, and the bird's `housing_cage_id` is cleared. Birds can be listed and filtered by their `species_id` and `housing_cage_id`.

### 3.5. Cage Boarding

Cages come in two usage classes. A `StoreManager` creates a cage unit with a `label`, a `cage_class` of either `HOUSING` (for livestock quarantine) or `BOARDING` (for customer boarding), a `capacity` of at least one occupant, and, for boarding cages, a `nightly_rate_cents` rate that defaults to 0. A cage begins `AVAILABLE` with `current_occupancy` of 0, and its `status` cycles among `AVAILABLE`, `OCCUPIED` (when occupancy equals capacity), and `OUT_OF_SERVICE`. Store managers update mutable cage configuration — `nightly_rate_cents`, `capacity`, and `status` — under the optimistic-concurrency rule of Section 2.5, supplying `expected_cage_version`.

A `Customer` reserves boarding by supplying the `customer_id`, a `cage_id` (expected to name a `BOARDING`-class cage, though the cage's class is not re-validated at reservation time), a `planned_check_in`, and a `planned_check_out` that must be strictly after the check-in. A reservation records an `actual_check_out` (null until checkout), a `provisional_cost_cents`, and a `final_cost_cents`, and moves through `RESERVED`, `CHECKED_IN`, `CHECKED_OUT`, and `CANCELLED`, with the last two terminal. At reservation, the system rejects any window that overlaps another non-cancelled reservation on the same cage, where overlap includes a 12-hour cleaning buffer applied after a prior reservation's `planned_check_out`; a conflict is rejected with `ERR_CAGE_TIME_CONFLICT`. The **provisional** boarding cost is computed at reservation as the cage's `nightly_rate_cents` multiplied by the number of nights in the planned window, where the number of nights is the difference between `planned_check_out` and `planned_check_in` divided by one day (86,400 seconds) and rounded up to the next whole night, with any partial day counting as a full night and a minimum of one night. The provisional figure charges nothing to the wallet.

Checking in a reservation moves it from `RESERVED` to `CHECKED_IN`. It requires the current clock to be at or after `planned_check_in`, and requires the target cage to not be `OUT_OF_SERVICE` and to have `current_occupancy` strictly below `capacity`; failing any of these three preconditions — including an attempt to check in before `planned_check_in` — is rejected with `ERR_NO_BOARDING_CAPACITY`. On check-in the cage's `current_occupancy` is incremented by one, moving the cage to `OCCUPIED` if occupancy now equals capacity. Checking out moves a `CHECKED_IN` reservation to `CHECKED_OUT`: the `actual_check_out` is set to the current clock and the **final** cost is computed as the cage's `nightly_rate_cents` multiplied by the actual number of nights (the same night-counting rule applied between `planned_check_in` and `actual_check_out`) plus a late fee of 2,000 cents when the `actual_check_out` is later than the `planned_check_out`, and no late fee otherwise. That `final_cost_cents` is debited from the customer's `wallet_credit_cents`, subject to the floor-zero wallet rule (`ERR_INSUFFICIENT_WALLET`). Check-out also decrements the cage's `current_occupancy` by one and recomputes its `status` to `AVAILABLE` once occupancy falls below capacity. A reservation that has never been checked in may be cancelled by the owning customer, moving it from `RESERVED` to `CANCELLED`; because no cage occupancy was ever taken, cancellation releases nothing. Reservations can be filtered by `customer_id` and `cage_id`.

### 3.6. Grooming Appointments

A `StoreManager` sets up a grooming station with a `label` and a `service_types` array, a subset of `WING_TRIM` and `NAIL_TRIM`. A station is `OPEN` on creation and can be closed, moving its `status` to `CLOSED`; a closed station rejects new appointments.

A `Customer` books an appointment by supplying the `customer_id`, the `grooming_station_id`, a `service_type` of `WING_TRIM` or `NAIL_TRIM`, a `slot_start`, a `slot_end` strictly after the start, and a flat `fee_cents`. The requested `service_type` must be listed in the station's `service_types` and the station must be open; a service the station does not offer, or a closed station, is rejected with `ERR_SERVICE_NOT_OFFERED`. The half-open slot from `slot_start` up to `slot_end` must not overlap another non-cancelled appointment on the same station; unlike boarding there is no buffer, so back-to-back adjacency (one appointment's end equal to the next's start) is allowed, and a true overlap is rejected with `ERR_STATION_TIME_CONFLICT`. A new appointment begins `BOOKED`, and its `status` resolves to `COMPLETED`, `CANCELLED`, or `NO_SHOW`.

Completing an appointment moves it from `BOOKED` to `COMPLETED` and debits the `fee_cents` from the owning customer's `wallet_credit_cents`, subject to the floor-zero rule (`ERR_INSUFFICIENT_WALLET`). The owning customer may cancel a `BOOKED` appointment, moving it to `CANCELLED` with no charge. An `AviaryStaff` member may mark a `BOOKED` appointment as `NO_SHOW`, but only once the current clock is at or after the appointment's `slot_end`; a no-show attempted before `slot_end`, or on an appointment that is not `BOOKED`, is rejected with `ERR_INVALID_STATE`. Appointments can be filtered by `customer_id` and `grooming_station_id`.

### 3.7. Feed Subscriptions and Fresh Inventory

A `Customer` opens a feed subscription by supplying the `customer_id`, a `tier` of `STANDARD` or `PREMIUM`, a `bird_count` of at least one, an optional `fresh_feed` flag defaulting to false, and, when `fresh_feed` is true, a `fresh_item_id` naming the inventory item to draw from (expected to be a `FRESH` item, though the item's `feed_kind` is not re-validated). A subscription's `status` is `ACTIVE`, `PAUSED`, or `CANCELLED`, with `CANCELLED` terminal.

The **monthly charge** is computed at creation and stored in `monthly_charge_cents`, and it is recomputed whenever the field is read. It is built up as follows: start from the tier base, which is 4,000 cents for `STANDARD` and 7,000 cents for `PREMIUM`; add a per-bird component of 1,500 cents multiplied by `bird_count`; if `fresh_feed` is true, add a fresh surcharge of 2,500 cents; then apply the owning customer's club discount, read from their `club_tier` at creation time — a discount of 0 percent for `NONE`, 10 percent for `SILVER`, and 20 percent for `GOLD` — by multiplying the accumulated subtotal by one minus that discount fraction and rounding the product half up to a whole number of cents. At creation the resulting `monthly_charge_cents` is snapshotted into `created_charge_cents` and that amount is debited from the customer's wallet, subject to the floor-zero wallet rule (`ERR_INSUFFICIENT_WALLET`) and the suspension rule (`ERR_CUSTOMER_SUSPENDED`). When `fresh_feed` is true, the system also allocates fresh inventory at creation, reserving `bird_count` units of the named fresh item under the conservation rule of Section 2.9 (with `ERR_INSUFFICIENT_INVENTORY` if stock is short).

Pausing an active subscription moves it from `ACTIVE` to `PAUSED`; if the subscription carries fresh feed, its fresh allocation is released back to inventory (its `bird_count` units returned from `quantity_allocated` to `quantity_on_hand`). Resuming moves it from `PAUSED` back to `ACTIVE`; if it carries fresh feed, the system re-allocates `bird_count` units, which requires the fresh item's `quantity_on_hand` to be at least `bird_count`, else `ERR_INSUFFICIENT_INVENTORY`. Cancelling is permitted from either `ACTIVE` or `PAUSED` and moves the subscription to `CANCELLED`. Cancellation accepts an optional `refund_wallet` flag: when `refund_wallet` is true and the subscription is still `ACTIVE` (within its first cycle), the exact `created_charge_cents` originally debited is credited back to the customer's wallet as a compensation reversal. Additionally, if the subscription was `ACTIVE` and carried fresh feed, its held fresh allocation is released back to inventory on cancellation.

### 3.8. Special Cage-Build Orders

Special orders track two independent axes at once: a payment axis and a build axis. A `Customer` opens a special order by supplying the `customer_id`, a `cage_item_id` naming the inventory item to be consumed as the cage-kit build component (expected to be a `DRY` item, though the item's `feed_kind` is not re-validated), a `build_qty` of at least one, and a `line_items` array. Each entry in `line_items` is an object with a `unit_price_cents`, a `quantity`, and a `tax_rate`. On creation the order allocates `build_qty` units of the `cage_item_id` inventory item under the conservation rule (reserving from `quantity_on_hand` into `quantity_allocated`, with `ERR_INSUFFICIENT_INVENTORY` if stock is short), and a `SUSPENDED` customer is blocked with `ERR_CUSTOMER_SUSPENDED`.

The `invoice_total_cents` is computed at creation with a **pinned rounding order**: the tax for each line is rounded to whole cents individually, and only then are the lines summed — rounding per line before summation, not summing before rounding, because the two orders can yield different cent totals. For each line, the line subtotal is `unit_price_cents` multiplied by `quantity`; the line tax is that subtotal multiplied by the line's `tax_rate`, rounded half up to a whole number of cents; and the line's contribution is the subtotal plus the rounded tax. The `invoice_total_cents` is the sum of those per-line contributions across all lines.

A new order begins with `payment_status` `UNPAID` and `build_status` `QUEUED`. The payment axis runs `UNPAID` → `PAID` → `REFUNDED`, with `REFUNDED` terminal; the build axis runs `QUEUED` → `IN_BUILD` → `BUILT` → `DELIVERED`, with a `CANCELLED` branch and `DELIVERED`/`CANCELLED` terminal. The two axes are independent except where a rule explicitly crosses them.

**Payment axis.** The owning customer pays an order, moving `payment_status` from `UNPAID` to `PAID`. Payment requires `payment_status` to be `UNPAID`, else `ERR_ORDER_ALREADY_PAID`; requires the `build_status` to not be `CANCELLED`, else `ERR_ORDER_CANCELLED`; and requires the customer's `wallet_credit_cents` to be at least `invoice_total_cents`, else `ERR_INSUFFICIENT_WALLET`. Payment debits `invoice_total_cents` from the wallet. A `StoreManager` refunds a paid order, moving `payment_status` from `PAID` to `REFUNDED`; a refund is permitted only when the `payment_status` is `PAID` and the `build_status` is `CANCELLED` (only cancelled builds are refundable) — a refund attempted from any other combination of statuses is rejected with `ERR_INVALID_STATE` — and it credits `invoice_total_cents` back to the wallet as an exact compensation reversal of the payment debit.

**Build axis.** A `StoreManager` drives the build. Starting a build moves `build_status` from `QUEUED` to `IN_BUILD`; marking built moves it from `IN_BUILD` to `BUILT`. Delivering moves `build_status` from `BUILT` to `DELIVERED`, but carries a cross-axis guard: the order's `payment_status` must be `PAID`, else `ERR_ORDER_NOT_PAID` — an unpaid order cannot be delivered. Delivery consumes the build allocation, subtracting `build_qty` from the inventory item's `quantity_allocated` as finished goods leaving the system (with no return to `quantity_on_hand`). Cancelling a build is permitted while `build_status` is `QUEUED` or `IN_BUILD`, moving it to the terminal `CANCELLED` and releasing the build allocation as an exact reversal of the create-time allocation: `build_qty` units move from `quantity_allocated` back to `quantity_on_hand`. Any of these transitions attempted from an illegal source state is rejected as an invalid state transition (`ERR_INVALID_STATE`). Special orders can be filtered by `customer_id` and `cage_item_id`.

Inventory itself is administered by a `StoreManager`, who creates an item with a `sku`, a `feed_kind` of `DRY` or `FRESH`, and an initial `quantity_on_hand` (its `quantity_allocated` starting at 0), and who can restock by adding a supplied number of `units` to `quantity_on_hand`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions, wallet adjustments, and configuration updates — return `200 OK`. The logical-clock control endpoint returns `200 OK`. All list endpoints accept the `limit` and `offset` query parameters described in Section 2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| POST | `/customers` | Create a customer | StoreManager |
| GET | `/customers` | List customers | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| GET | `/customers/{id}` | Get a customer | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| POST | `/customers/{id}/club-membership` | Set a customer's club tier | StoreManager |
| POST | `/customers/{id}/wallet/adjustments` | Credit store credit to a customer's wallet | StoreManager |
| POST | `/customers/{id}/suspend` | Suspend a customer | StoreManager |
| POST | `/species` | Create a species record | ComplianceOfficer |
| GET | `/species` | List species | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| GET | `/species/{id}` | Get a species | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| GET | `/species/{id}/permits` | List CITES permits for a species | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| POST | `/cites-permits` | Create a CITES permit in DRAFT | ComplianceOfficer |
| GET | `/cites-permits/{id}` | Get a permit | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| POST | `/cites-permits/{id}/submit` | Submit a DRAFT permit | ComplianceOfficer |
| POST | `/cites-permits/{id}/return-for-revision` | Return a SUBMITTED permit to DRAFT | ComplianceOfficer |
| POST | `/cites-permits/{id}/approve` | Approve a SUBMITTED permit | ComplianceOfficer |
| POST | `/cites-permits/{id}/revoke` | Revoke an APPROVED permit | ComplianceOfficer |
| POST | `/birds` | Register a livestock bird | AviaryStaff |
| GET | `/birds` | List/filter birds | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| GET | `/birds/{id}` | Get a bird | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| GET | `/birds/{id}/quarantine-records` | List quarantine records for a bird | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| POST | `/birds/{id}/start-quarantine` | Start quarantine; occupy a HOUSING cage | AviaryStaff |
| POST | `/birds/{id}/list-for-sale` | List a CLEARED bird for sale | AviaryStaff |
| POST | `/birds/{id}/relist` | Re-list a SUSPENDED bird | AviaryStaff |
| POST | `/birds/{id}/sell` | Sell a LISTED bird to a customer | AviaryStaff |
| GET | `/quarantine-records/{id}` | Get a quarantine record | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| POST | `/quarantine-records/{id}/start-test` | Start a diagnostic test | AviaryStaff |
| POST | `/quarantine-records/{id}/record-test-result` | Record a FAIL or RETEST result | AviaryStaff |
| POST | `/quarantine-records/{id}/clear` | Clear quarantine (guarded) | AviaryStaff |
| POST | `/quarantine-records/{id}/fail` | Fail quarantine | AviaryStaff |
| POST | `/cage-units` | Create a cage unit | StoreManager |
| GET | `/cage-units` | List cage units | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| GET | `/cage-units/{id}` | Get a cage unit | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| PATCH | `/cage-units/{id}` | Update mutable cage config with OCC | StoreManager |
| POST | `/boarding-reservations` | Create a boarding reservation | Customer |
| GET | `/boarding-reservations` | List/filter reservations | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| GET | `/boarding-reservations/{id}` | Get a reservation | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| POST | `/boarding-reservations/{id}/check-in` | Check in a reservation | AviaryStaff |
| POST | `/boarding-reservations/{id}/check-out` | Check out; settle final cost | AviaryStaff |
| POST | `/boarding-reservations/{id}/cancel` | Cancel a RESERVED reservation | Customer |
| POST | `/grooming-stations` | Create a grooming station | StoreManager |
| GET | `/grooming-stations` | List grooming stations | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| GET | `/grooming-stations/{id}` | Get a grooming station | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| POST | `/grooming-stations/{id}/close` | Close a station | StoreManager |
| POST | `/grooming-appointments` | Book a grooming appointment | Customer |
| GET | `/grooming-appointments` | List/filter appointments | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| GET | `/grooming-appointments/{id}` | Get an appointment | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| POST | `/grooming-appointments/{id}/complete` | Complete an appointment; settle fee | AviaryStaff |
| POST | `/grooming-appointments/{id}/cancel` | Cancel a BOOKED appointment | Customer |
| POST | `/grooming-appointments/{id}/no-show` | Mark a past-slot appointment NO_SHOW | AviaryStaff |
| POST | `/feed-subscriptions` | Create a feed subscription | Customer |
| GET | `/feed-subscriptions` | List/filter subscriptions | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| GET | `/feed-subscriptions/{id}` | Get a subscription | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| POST | `/feed-subscriptions/{id}/pause` | Pause a subscription | Customer |
| POST | `/feed-subscriptions/{id}/resume` | Resume a subscription | Customer |
| POST | `/feed-subscriptions/{id}/cancel` | Cancel a subscription | Customer |
| POST | `/inventory-items` | Create an inventory item | StoreManager |
| GET | `/inventory-items` | List inventory items | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| GET | `/inventory-items/{id}` | Get an inventory item | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| POST | `/inventory-items/{id}/restock` | Add units to on-hand stock | StoreManager |
| POST | `/special-orders` | Create a special/cage-build order | Customer |
| GET | `/special-orders` | List/filter special orders | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| GET | `/special-orders/{id}` | Get a special order | StoreManager, AviaryStaff, ComplianceOfficer, Customer |
| POST | `/special-orders/{id}/pay` | Pay an UNPAID order from wallet | Customer |
| POST | `/special-orders/{id}/refund` | Refund a PAID+CANCELLED order | StoreManager |
| POST | `/special-orders/{id}/start-build` | Start the build | StoreManager |
| POST | `/special-orders/{id}/mark-built` | Mark the build complete | StoreManager |
| POST | `/special-orders/{id}/deliver` | Deliver a built, paid order | StoreManager |
| POST | `/special-orders/{id}/cancel-build` | Cancel a queued/in-build order | StoreManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_SPECIES_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_BIRD_NOT_FOUND` | 404 Not Found |
| `ERR_QUARANTINE_NOT_FOUND` | 404 Not Found |
| `ERR_CAGE_NOT_FOUND` | 404 Not Found |
| `ERR_RESERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_STATION_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_INVENTORY_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PERMIT_EXPIRED_INPUT` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_QUARANTINE_NOT_OPEN` | 409 Conflict |
| `ERR_ORDER_ALREADY_PAID` | 409 Conflict |
| `ERR_ORDER_NOT_PAID` | 409 Conflict |
| `ERR_ORDER_CANCELLED` | 409 Conflict |
| `ERR_STALE_CAGE_VERSION` | 412 Precondition Failed |
| `ERR_SPECIES_RESTRICTED` | 409 Conflict |
| `ERR_PERMIT_NOT_APPROVED` | 409 Conflict |
| `ERR_QUARANTINE_TOO_EARLY` | 409 Conflict |
| `ERR_RISK_TOO_HIGH_TO_CLEAR` | 409 Conflict |
| `ERR_CAGE_TIME_CONFLICT` | 409 Conflict |
| `ERR_STATION_TIME_CONFLICT` | 409 Conflict |
| `ERR_NO_HOUSING_CAPACITY` | 409 Conflict |
| `ERR_NO_BOARDING_CAPACITY` | 409 Conflict |
| `ERR_SERVICE_NOT_OFFERED` | 409 Conflict |
| `ERR_INSUFFICIENT_INVENTORY` | 409 Conflict |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_INSUFFICIENT_WALLET` | 402 Payment Required |
