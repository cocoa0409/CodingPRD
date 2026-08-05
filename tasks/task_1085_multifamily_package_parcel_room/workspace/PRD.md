# Multifamily Package & Parcel Room API — Product Requirements Document

## 1. Introduction

Modern multifamily communities receive a relentless stream of carrier deliveries — ambient parcels, cold groceries, perishable meal kits, oversized furniture boxes — and the front desk is expected to log every one, notify the right resident, store it safely, and hand it back against a one-time code, all while a finite wall of smart lockers and staff-managed shelves fills and empties throughout the day. This API is the system of record for that parcel room. It coordinates carrier scan-in, storage assignment across smart lockers and shelves, resident notification and code-based pickup, cold-chain and aging deadlines, overflow governance, holding-fee accounting, retail-return drop-off staging, and property-management-system (PMS) roster synchronization.

The design goal is a single, immediately-consistent source of truth for occupancy and money. Every locker occupancy change reprices the property's overflow posture; every settled or evicted package writes to a holding-fee ledger; every roster event streamed from the PMS can cascade holds, releases, and fee waivers across a resident's in-flight packages. Because the physical room has hard capacity limits and cold goods spoil, the system enforces temporal windows, quota thresholds, and segregation-of-duties controls rather than treating them as advisory. This document specifies the complete contract: the response envelope, the role model, the calculation rules, the state machines, and the endpoint and error catalogs an implementer must reproduce exactly.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. Business-process detail lives in Section 3; the two sections are complementary and must be read together.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. If either header is absent, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_MISSING_AUTH_HEADER` (HTTP 401). This is the highest-priority check and is evaluated before any other validation.

The system recognizes exactly five roles: `PropertyManager`, `ConciergeStaff`, `Resident`, `Carrier`, and `PmsIntegration`. When a caller presents a recognized role but that role is not authorized for the requested operation — or is authorized only as an owner and fails the ownership test described below — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Role authorization is the second-priority check, evaluated immediately after header presence and before resource existence.

Two of these roles are **entity-backed**, meaning their `X-User-ID` is not an opaque token but the identifier of a persisted record:

- When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting `Resident`. Ownership checks compare the target resource's resident foreign key to `X-User-ID`: a resident may pick up a package only when the package's `resident_id` equals `X-User-ID`, and may drop off a retail return only when the created return's `resident_id` equals `X-User-ID`. A mismatch is an `ERR_FORBIDDEN_ROLE`.
- When `X-User-Role` is `Carrier`, `X-User-ID` is the `id` of the acting `Carrier`. Ownership checks compare the target resource's carrier foreign key to `X-User-ID`: a carrier may collect a staged retail return only when that return's `carrier_id` equals `X-User-ID`, and when logging an inbound package as a carrier the package's `carrier_id` must equal `X-User-ID`. A mismatch is an `ERR_FORBIDDEN_ROLE`.

The remaining three roles are **opaque**: when `X-User-Role` is `PropertyManager`, `ConciergeStaff`, or `PmsIntegration`, `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it — for example, it writes the acting `X-User-ID` into `return_initiated_by_user_id` on a package moved to `RETURN_INITIATED` — but it does not compare it to any entity's `id` for ownership. `PropertyManager` is the property superuser (configures properties, policy, banks, lockers, shelves, carriers, residents; runs reports and aging sweeps). `ConciergeStaff` is front-desk staff (logs packages, notifies residents, assigns storage, hands out packages, evicts overflow/aged packages, verifies and rejects retail returns). `PmsIntegration` is the property-management-system connector (imports residents, applies roster lifecycle events, and operates the logical clock in test).

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, all list responses are sorted by `created_at` in ascending order. The `meta` object of every list response includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources — `Property`, `LockerBank`, `Locker`, `Shelf`, `Resident`, `Carrier`, `Package`, `RetailReturn`, and `StorageCharge` — carry a standard system-managed field set: an `id` (a server-minted UUID with no type prefix), a `created_at` (ISO 8601 UTC timestamp with three fractional digits), an `updated_at` (same format, refreshed on every mutation), and a `version` (an integer that starts at 1 and increments by 1 on each mutation of that resource). The one exception is the `Notification` resource, which is immutable after creation: it carries only `id` and `created_at`, and has neither an `updated_at` nor a `version` field.

All time-bearing values in this system — `intake_at`, `notified_at`, `sent_at`, `dropped_off_at`, `settled_at`, and every computed deadline — are read from a **logical clock**, never from wall-clock time. The server starts with its logical clock set to `2026-05-01T00:00:00Z` and the clock never falls back to real time; it advances only when an operator sets it explicitly. This makes all temporal windows (cold-chain, aging, holding-fee accrual) deterministic and test-drivable.

### 2.5. Occupancy Posture and Overflow Governance

Each `Property` continuously derives an `occupancy_posture` — one of `OPEN`, `RESTRICTED`, or `FROZEN` — from live locker utilization, and this posture is persisted and refreshed on any locker occupancy change. To compute it, the system counts `in_service_locker_count` as the number of that property's lockers whose `status` is not `OUT_OF_SERVICE`, and `occupied_locker_count` as the number whose `status` is `OCCUPIED`. Utilization is defined as 1.0 when the in-service count is zero; otherwise it is the occupied count divided by the in-service count. The posture is `FROZEN` when utilization is greater than or equal to 1.0; it is `RESTRICTED` when utilization is greater than or equal to the property's `overflow_threshold_pct` and strictly less than 1.0; otherwise it is `OPEN`. The threshold comparison is inclusive at its boundary — a utilization exactly equal to the configured threshold (default 0.85, i.e. 85 percent) already yields `RESTRICTED`.

Posture is recomputed on every event that changes locker occupancy or in-service status: assigning a locker at notify, releasing one at pickup, return-initiate, or disposal, creating a new locker, and taking a locker out of service. As utilization crosses these boundaries the posture moves accordingly — `OPEN → RESTRICTED` when it reaches the threshold, `RESTRICTED → FROZEN` when it reaches full, `FROZEN → RESTRICTED` when it falls back below full, and `RESTRICTED → OPEN` when it drops below the threshold. Every such recomputation persists the new `occupancy_posture` and increments the property's `version`. Because these occupancy cascades silently bump `Property.version`, a configuration writer that read the property earlier may find its expected version stale (see Section 2.9).

### 2.6. Storage Topology, Fit, and Capacity

Storage is organized as a flat hierarchy under a `Property`: `LockerBank` records group smart-locker compartments, `Locker` records are individual compartments, and `Shelf` records are staff-managed aggregate-capacity zones. A locker bank has a `storage_class` of either `AMBIENT` or `REFRIGERATED`, which is the physical class of every locker created under it; a locker inherits that `storage_class` when its own is omitted at creation. Each locker also has a `size_class` of `SMALL`, `MEDIUM`, `LARGE`, or `OVERSIZE`, ranked in that ascending order.

A locker **fits** a package when the locker's `size_class` rank is greater than or equal to the package's `size_class` rank and the `storage_class` matches the package's storage requirement. For any bank, the **nominal** compartment count for a requested size and class counts every matching locker regardless of `status`, while the **effective** count includes only those matching lockers whose `status` is `AVAILABLE`. Live auto-assignment at notify uses the effective count (only `AVAILABLE` compartments qualify); capacity reporting exposes both, and the two diverge whenever any matching compartment is `OCCUPIED` or `OUT_OF_SERVICE`. At the bank level these roll up as `nominal_locker_count` (all lockers under the bank regardless of status) and `available_locker_count` (lockers under the bank whose `status` is `AVAILABLE`).

Shelves use aggregate capacity rather than single-occupancy. A shelf's `occupied_count` is the number of packages whose `shelf_id` equals that shelf and whose `status` is `AWAITING_PICKUP`. Available shelf capacity is the shelf's `capacity` minus its occupied count; a shelf can accept a new package only when that available capacity is at least 1 — equivalently, only while the occupied count is strictly less than the capacity. A shelf whose occupied count already equals its capacity is full.

### 2.7. Holding-Fee Ledger, Precision, and Loyalty Discounts

The parcel room charges residents for extended storage. Holding fees are always expressed in whole cents (integer). Any fractional cent produced during calculation is rounded using the round-half-up method, and — importantly — rounding is applied at the per-day and per-charge granularities specified in Section 3, never once at the end. All monetary amounts returned in responses are integers in cents.

Each `Property` maintains a fee ledger surfaced as `uncollected_fee_cents`: the sum of `amount_cents` across all `StorageCharge` records of type `HOLDING_FEE` whose `status` is `OUTSTANDING`, aggregated over that property's packages. Charges are created only at pickup or return-initiate (including system-driven eviction during an aging sweep); the only value of `charge_type` currently minted is `HOLDING_FEE`. A charge's `amount_cents` is the **net** amount owed after the resident's per-charge loyalty discount, and each charge records a human-readable `basis` (for example, "5 chargeable days x 150 + 0 oversize"), a `status` of `OUTSTANDING`, `COLLECTED`, or `WAIVED`, and a `settled_at` instant that is set at the moment the charge leaves `OUTSTANDING`. A charge created at pickup is born `COLLECTED`; a charge created at return-initiate or aging eviction is born `OUTSTANDING` and increases the property's uncollected total.

### 2.8. Cold-Chain and Aging Windows

Perishable and cold goods are governed by two independent temporal windows, both measured on the logical clock from the package's `intake_at`. The **cold-chain window** applies only to packages whose `storage_type` is `PERISHABLE`: their `cold_chain_deadline_at` is `intake_at` plus the property's `perishable_hold_hours` (default 48 hours, i.e. two days). This window is half-open — a pickup or observation at exactly `cold_chain_deadline_at` is still safe, and only an observation strictly after the deadline forfeits the package. For all other storage types `cold_chain_deadline_at` is null.

The **aging window** applies to every package: its `aging_deadline_at` is `intake_at` plus a number of days that depends on storage type — `aging_days_perishable` (default 2) when the `storage_type` is `COLD` or `PERISHABLE`, and `aging_days_standard` (default 10) otherwise. The aging boundary is inclusive: a package qualifies for aging return once the current clock is greater than or equal to its `aging_deadline_at`.

### 2.9. Optimistic Concurrency Control on Property Policy

A property's fee/aging/overflow policy may be updated only under optimistic concurrency control. A policy-update request must carry `expected_property_version` as a required field whose value is the client's last-observed `Property.version`. If that value does not equal the property's current `version`, the update is rejected with `ERR_STALE_PROPERTY_VERSION` (HTTP 412). Because locker occupancy cascades (notify, pickup, return-initiate, disposal, out-of-service, locker creation) silently advance the property's version, a policy write carrying a version captured before any such cascade is refused, preventing a lost update over the previously-read configuration. No other endpoint accepts or requires a version field; the OCC guard exists solely on the property policy update.

### 2.10. Nested Resource Retrieval and Validation Ordering

When an endpoint path or body references resources, the system validates existence left-to-right along the path first, then body foreign keys, and rejects at the first identifier that does not resolve — returning the specific not-found error for that resource type: `ERR_PROPERTY_NOT_FOUND`, `ERR_LOCKER_BANK_NOT_FOUND`, `ERR_LOCKER_NOT_FOUND`, `ERR_SHELF_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, or `ERR_RETAIL_RETURN_NOT_FOUND`, each HTTP 404.

Validations are applied in a fixed global priority so that overlapping checks resolve deterministically. The order is: (1) authentication headers present and role known (`ERR_MISSING_AUTH_HEADER`, 401); (2) role permitted and, for entity-backed roles, ownership of the target (`ERR_FORBIDDEN_ROLE`, 403); (3) existence of all referenced resources (the 404 family above); (4) target resource in a state permitting the operation (`ERR_INVALID_STATE`, 409); (5) dual-control on return-complete (`ERR_SOD_VIOLATION`, 403); (6) recipient resident active on notify (`ERR_RESIDENT_NOT_ACTIVE`, 409); (7) cold-chain freshness on perishable pickup (`ERR_COLD_CHAIN_EXPIRED`, 409); (8) posture gating of locker assignment (`ERR_STORAGE_FROZEN` / `ERR_STORAGE_RESTRICTED`, 409); (9) storage compatibility of the chosen locker or shelf (`ERR_LOCKER_UNAVAILABLE` / `ERR_LOCKER_SIZE_MISMATCH` / `ERR_SHELF_FULL` / `ERR_NO_STORAGE_AVAILABLE`, 409); (10) pickup-code match (`ERR_INVALID_PICKUP_CODE`, 403); (11) retail-return staging capacity (`ERR_STAGING_FULL`, 409); (12) tracking-number uniqueness (`ERR_DUPLICATE_TRACKING`, 409); (13) property-policy OCC (`ERR_STALE_PROPERTY_VERSION`, 412); and (14) body well-formedness — required fields present, enums valid, numeric fields non-negative, `capacity` greater than 0, `loyalty_discount_pct` at least 0 and strictly less than 1, and `overflow_threshold_pct` strictly greater than 0 and at most 1 (`ERR_VALIDATION`, 400). Where a lower-numbered check would fire, it takes precedence over any higher-numbered one on the same request.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Property and Its Storage

A `PropertyManager` creates a `Property` by supplying at minimum a `name`; the request may also set the community `timezone` (an informational IANA label defaulting to UTC) and the full policy block: `overflow_threshold_pct` (default 0.85), `aging_days_standard` (default 10), `aging_days_perishable` (default 2), `perishable_hold_hours` (default 48), `holding_fee_grace_days` (default 3), `holding_fee_daily_cents` (default 150), `perishable_fee_multiplier` (default 2), `oversize_surcharge_cents` (default 500), `holding_fee_cap_cents` (default 5000), and `return_staging_capacity` (default 25). A newly created property starts with `occupancy_posture` equal to `OPEN`, all computed counts (`occupied_locker_count`, `in_service_locker_count`, `uncollected_fee_cents`, `return_staging_count`) at zero, and `version` at 1.

The same manager may later revise the policy. A policy update carries the required `expected_property_version` (see Section 2.9) plus any subset of the policy fields — `overflow_threshold_pct`, `aging_days_standard`, `aging_days_perishable`, `perishable_hold_hours`, `holding_fee_grace_days`, `holding_fee_daily_cents`, `perishable_fee_multiplier`, `oversize_surcharge_cents`, `holding_fee_cap_cents`, and `return_staging_capacity`. Applying the update writes the provided fields, increments the property's `version` by 1, and recomputes `occupancy_posture` using the new threshold.

Under a property, the manager builds the physical topology. A `LockerBank` is created with its `property_id`, a `label` (e.g., "A"), and a `storage_class` of `AMBIENT` or `REFRIGERATED`; its `nominal_locker_count` and `available_locker_count` both begin at zero. Individual `Locker` compartments are then created against a `locker_bank_id` with a `size_class` and an optional `storage_class` (defaulting to the owning bank's class when omitted). A freshly created locker's `status` is `AVAILABLE` and its `current_package_id` is null; creating it recomputes the owning bank and property counts and posture and bumps the property's `version`. A locker's `current_package_id` mirrors whatever package occupies it and is null whenever the locker is not `OCCUPIED`. A manager may take an `AVAILABLE` locker `OUT_OF_SERVICE`; this is permitted only while the locker is `AVAILABLE` — attempting it on an `OCCUPIED` locker is rejected with `ERR_LOCKER_UNAVAILABLE` — and it recomputes `in_service_locker_count` and posture and bumps the property's `version`.

Staff-managed `Shelf` zones are created with a `property_id`, a `zone` label, a `storage_class`, and a `capacity` that must be strictly greater than zero; the shelf's `occupied_count` starts at zero. The manager also registers each delivering `Carrier` with a `property_id`, a display `name`, a `scac` alpha code (unique per property), and an optional `allows_smart_locker_delivery` flag (default true) indicating whether that carrier may deliver directly into smart lockers. Residents are registered either by the manager or via PMS import with a `property_id`, `unit_number`, `full_name`, `email`, an optional `phone`, an optional `notify_channel` of `EMAIL`, `SMS`, or `PUSH` (default `EMAIL`), and an optional `loyalty_discount_pct` (a fraction at least 0 and strictly below 1, default 0.0). A registered resident begins with `status` `ACTIVE`.

### 3.2. Logging an Inbound Package

Either a `Carrier` or `ConciergeStaff` scans an inbound parcel into the room, supplying its `property_id`, the recipient `resident_id`, the delivering `carrier_id`, a `tracking_number`, a `size_class` (`SMALL`, `MEDIUM`, `LARGE`, or `OVERSIZE`), and a `storage_type` (`AMBIENT`, `COLD`, or `PERISHABLE`). When a carrier performs the scan, the supplied `carrier_id` must equal the carrier's own `X-User-ID`. The `tracking_number` must be unique within the property across all non-terminal packages; a collision with any package not yet in `PICKED_UP`, `RETURNED`, or `DISPOSED` is rejected with `ERR_DUPLICATE_TRACKING`.

A logged package enters `status` `LOGGED` with `storage_mode` `NONE` and no storage assigned (`locker_id` and `shelf_id` both null). Its `intake_at` is stamped from the logical clock, and the system computes the derived fields: `is_oversize` is true exactly when `size_class` is `OVERSIZE`; `aging_deadline_at` and, for perishables, `cold_chain_deadline_at` are set per Section 2.8. A `Package` also exposes a provisional fee (`provisional_fee_cents`), a settled fee (`final_fee_cents`, null while unsettled), a `pickup_code` (null until first notify), a `notify_count` (starting at 0), a `notified_at` (null until first notify), and a `return_initiated_by_user_id` (null until an eviction records the acting user).

### 3.3. Notification, Storage Assignment, and Pickup Codes

`ConciergeStaff` drives notification. The first notification of a `LOGGED` package advances it from `LOGGED` to `AWAITING_PICKUP`. The staff member may steer storage using an optional `storage_target` together with an optional explicit `locker_id` or `shelf_id`; when no explicit compartment is named the system auto-assigns using the effective (AVAILABLE-only) locker capacity described in Section 2.6, and if auto-assignment finds no eligible locker or shelf the request is rejected with `ERR_NO_STORAGE_AVAILABLE`.

Several preconditions gate the first notify, and their errors follow the priority in Section 2.10. The recipient resident's `status` must be `ACTIVE`; otherwise the notify is rejected with `ERR_RESIDENT_NOT_ACTIVE`. When the target is a locker, the property's posture gates assignment: a `FROZEN` property blocks all locker assignment (`ERR_STORAGE_FROZEN`), and a `RESTRICTED` property blocks `AMBIENT` locker assignment specifically (`ERR_STORAGE_RESTRICTED`) while still permitting refrigerated assignment. The chosen locker must be `AVAILABLE`, must fit the package's size, and must match on storage class — a locker that is not available (because it is `OCCUPIED` or `OUT_OF_SERVICE`) yields `ERR_LOCKER_UNAVAILABLE`, and a locker too small for the package or of the wrong storage class yields `ERR_LOCKER_SIZE_MISMATCH`. When the target is a shelf, the shelf's `occupied_count` must be strictly below its `capacity` and its storage class must match; a full shelf yields `ERR_SHELF_FULL` and a class mismatch yields `ERR_LOCKER_SIZE_MISMATCH`.

On a successful first notify, the system mints a six-character one-time `pickup_code`, sets `notified_at` to the current clock, and increments `notify_count`. If a locker was assigned, its `locker_id` is recorded on the package, that locker transitions `AVAILABLE → OCCUPIED` with its `current_package_id` set to the package, and the package's `storage_mode` becomes `LOCKER`; if a shelf was assigned, its `shelf_id` is recorded and `storage_mode` becomes `SHELF`. The system then recomputes the bank's `available_locker_count`, the property's `occupied_locker_count` and `in_service_locker_count`, recomputes and persists the property's `occupancy_posture` (which may step `OPEN → RESTRICTED → FROZEN`), and bumps the property's `version`. Finally it emits a `Notification` record of `kind` `INITIAL` whose `channel` is a snapshot of the resident's `notify_channel` at send time, carrying the `pickup_code`, with `sent_at` stamped from the clock and a `package_id` linking it to the package.

A package already in `AWAITING_PICKUP` may be re-notified as a reminder — a cyclic self-transition from `AWAITING_PICKUP` back to `AWAITING_PICKUP`. A reminder still requires the resident to be `ACTIVE`, increments `notify_count`, refreshes `notified_at`, and creates a `Notification` of `kind` `REMINDER` that reuses the original `pickup_code`; it does not re-mint the code and does not reassign or change storage. Notifications are always readable per package and expose their `pickup_code` only for pickup-bearing kinds (it is null for kinds that carry no code).

### 3.4. Resident Pickup and Fee Settlement

A `Resident` picking up their own package, or `ConciergeStaff` acting on the resident's behalf, presents the `pickup_code`. When the actor is a resident, the package's `resident_id` must equal the resident's `X-User-ID`. The package must be in `AWAITING_PICKUP`; for a `PERISHABLE` package the current clock must not be strictly after its `cold_chain_deadline_at`, otherwise the pickup is refused with `ERR_COLD_CHAIN_EXPIRED` (a pickup exactly at the deadline remains allowed). The supplied code must equal the package's `pickup_code`; a mismatch is rejected with `ERR_INVALID_PICKUP_CODE`.

On success the package advances `AWAITING_PICKUP → PICKED_UP`. The system pins the final holding fee into `final_fee_cents` using the final variant of the fee calculation (Section 3.5), with the accrual end frozen at the pickup instant (`picked_up_at`). When that final fee is greater than zero, a `StorageCharge` of type `HOLDING_FEE` is created already `COLLECTED`, with `amount_cents` equal to the net amount after the resident's loyalty discount and `settled_at` stamped at pickup. The system then releases storage — an occupied locker transitions `OCCUPIED → AVAILABLE` with `current_package_id` cleared to null, or the assigned shelf's occupied count is decremented — sets `storage_mode` back to `NONE`, recomputes the bank and property locker counts, recomputes and persists `occupancy_posture`, and bumps the property's `version`.

### 3.5. Computing the Holding Fee (Provisional and Final)

The holding fee is a tiered, day-by-day accrual computed from a single package against its property's policy. Let the accrual end instant be the current logical clock for a provisional read, the pickup instant for a final settlement at pickup, or the current clock for a final settlement at return-initiate. The number of elapsed days is the whole number of 24-hour periods between `intake_at` and that end instant, discarding any fractional day (floor). The number of chargeable days is the elapsed days minus the property's `holding_fee_grace_days`, but never less than zero. The per-day rate is the property's `holding_fee_daily_cents`, multiplied by the `perishable_fee_multiplier` when the package's `storage_type` is `COLD` or `PERISHABLE`, and by 1 otherwise.

The gross fee is built by rounding each individual day's rate to whole cents with round-half-up and then summing those rounded per-day amounts across all chargeable days — the rounding happens per day, before summation, never once on the total. If the package `is_oversize`, the property's `oversize_surcharge_cents` is added once to the gross as a flat surcharge. The gross is then capped: the final gross is the smaller of the computed gross and the property's `holding_fee_cap_cents`. The **provisional** variant (surfaced live as `provisional_fee_cents` while the package is still `AWAITING_PICKUP`) uses the current clock as its end and therefore grows as time passes; the **final** variant (pinned into `final_fee_cents`) freezes its end at the pickup instant or at the return-initiate instant and never re-grows thereafter.

When a charge is actually created, the resident's loyalty discount is applied to that gross to produce the net stored in `amount_cents`: the net is the gross fee multiplied by one minus the resident's `loyalty_discount_pct`, rounded half-up to whole cents. When a single operation settles many packages at once — an aging sweep can settle several, though ordinary pickup settles exactly one — the discount is applied and rounded per individual charge first, and only then are the resulting net amounts summed into the property's `uncollected_fee_cents`. The pinned order is always round-per-charge and then sum, never sum-then-discount-then-round.

### 3.6. PMS Roster Events and Their Cascades

The `PmsIntegration` connector streams roster lifecycle events against a resident by supplying an `event_type` of `PLACE_HOLD`, `RELEASE_HOLD`, or `MOVE_OUT`. Each event moves the resident through their own state machine (`ACTIVE`, `HOLD`, `MOVED_OUT`) and cascades to that resident's in-flight packages.

A `PLACE_HOLD` event moves an `ACTIVE` resident to `HOLD` and cascades every one of that resident's `AWAITING_PICKUP` packages to `HELD`; each such package emits a `Notification` of `kind` `MOVE_OUT_HOLD`, and the package's storage assignment is retained (not released) while it is `HELD`. A later `RELEASE_HOLD` event returns a `HOLD` resident to `ACTIVE` and cascades each of that resident's `HELD` packages back to `AWAITING_PICKUP`, with no additional side effects. A `MOVE_OUT` event moves a resident — whether currently `ACTIVE` or `HOLD` — to the terminal `MOVED_OUT` state. When the resident was `ACTIVE`, move-out first cascades each `AWAITING_PICKUP` package to `HELD` (which, as above, creates a `MOVE_OUT_HOLD` notification). In both the active and hold cases, move-out then waives money: every `OUTSTANDING` `HOLDING_FEE` charge belonging to that resident's packages is set to `WAIVED`, and the property's `uncollected_fee_cents` is decreased by the summed waived amount.

### 3.7. Evicting to Return and Dual-Control Completion

When a package must leave the room without a resident pickup — because it has aged out or the room is overflowing — it is evicted to return. `ConciergeStaff` or a `PropertyManager` initiates this on an `AWAITING_PICKUP` package, and the aging sweep performs the same transition with the system as actor. Return-initiate advances the package `AWAITING_PICKUP → RETURN_INITIATED`. It pins `final_fee_cents` using the final variant as of now, and when that fee is greater than zero it creates a `StorageCharge` of type `HOLDING_FEE` in `OUTSTANDING` status carrying the net amount, thereby increasing the property's `uncollected_fee_cents`. It releases the locker or shelf, recomputes the bank and property counts and `occupancy_posture`, and bumps the property's `version`. Critically, it records the acting `X-User-ID` into the package's `return_initiated_by_user_id` (the system writes the literal `SYSTEM` when an aging sweep drives the transition), and it emits a `Notification` of `kind` `RETURN_NOTICE`.

Completing the return is a dual-control step: `ConciergeStaff` or a `Carrier` confirms that the return-initiated package was physically handed to the carrier, advancing it `RETURN_INITIATED → RETURNED`. The confirming actor's `X-User-ID` must differ from the `return_initiated_by_user_id` recorded at eviction; if the same user attempts both halves, the completion is rejected with `ERR_SOD_VIOLATION`, enforcing separation of duties between whoever evicted the package and whoever hands it back to the carrier. A package in any state other than the one each transition expects yields `ERR_INVALID_STATE`.

### 3.8. The Aging Sweep and Cold-Chain Forfeiture

A `PropertyManager` or `ConciergeStaff` runs an aging sweep over a property to clear stale inventory in one batch of system-actor transitions. The sweep's candidate set is every package under the property that is currently `AWAITING_PICKUP` and whose current clock has reached or passed its `aging_deadline_at` (the boundary is inclusive), where the deadline uses `aging_days_perishable` for `COLD` or `PERISHABLE` storage types and `aging_days_standard` otherwise. Candidates are processed in ascending `intake_at` order, breaking ties by ascending `created_at`.

Within that ordered set, any `PERISHABLE` package already strictly past its `cold_chain_deadline_at` is forfeited first: it transitions `AWAITING_PICKUP → DISPOSED`, which releases its storage, recomputes counts and posture, bumps the property's `version`, and emits a `Notification` of `kind` `DISPOSED_NOTICE`. A disposed package accrues no salvage charge. Every remaining candidate is evicted `AWAITING_PICKUP → RETURN_INITIATED` with the system as actor and `return_initiated_by_user_id` set to `SYSTEM`, pinning `final_fee_cents`, creating `OUTSTANDING` `HOLDING_FEE` charges, and increasing `uncollected_fee_cents` exactly as a manual eviction would. Independently of aging, a resident's `PERISHABLE` package observed strictly after `cold_chain_deadline_at` at pickup time is blocked with `ERR_COLD_CHAIN_EXPIRED` (Section 3.4).

### 3.9. Retail-Return Drop-off and Carrier Collection

A `Resident` drops off an outbound retail return by supplying a `property_id`, their own `resident_id` (which must equal the resident's `X-User-ID`), the collecting `carrier_id`, and the outbound `tracking_number`. The drop-off is blocked when the property is already at capacity — that is, when `return_staging_count` equals `return_staging_capacity` — and rejected with `ERR_STAGING_FULL`; the staging count is the number of returns under the property whose `status` is `DROPPED_OFF` or `AWAITING_CARRIER`. A successful drop-off creates a `RetailReturn` in `status` `DROPPED_OFF` with `dropped_off_at` stamped from the clock and increments the property's `return_staging_count`.

`ConciergeStaff` then verifies the return label, advancing it `DROPPED_OFF → AWAITING_CARRIER`, or rejects a bad-label return with an optional `reject_reason`, advancing it to the terminal `REJECTED` status (`DROPPED_OFF → REJECTED`) and recording the reason on `reject_reason` while decrementing the property's `return_staging_count`. Finally, the collecting `Carrier` picks up a staged return, advancing it `AWAITING_CARRIER → PICKED_UP` and decrementing `return_staging_count`; the carrier's `X-User-ID` must equal the return's `carrier_id`, otherwise the collection is rejected with `ERR_FORBIDDEN_ROLE`. Any of these transitions attempted from the wrong starting status yields `ERR_INVALID_STATE`.

The logical clock itself is operated by a `PropertyManager` or `PmsIntegration` through an admin-only test-driving capability that advances the clock to a supplied `to_iso8601` instant; this drives every deadline and accrual deterministically and never rewinds to wall-clock time.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions, policy updates, sweeps, and notifications — return `200 OK`. All reads return `200 OK`. Request and response bodies are not enumerated here; reconstruct them from the Section 3 narratives.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/parcelroom/properties` | Create a Property with fee/aging/overflow policy | PropertyManager |
| GET | `/parcelroom/properties/{id}` | Get a Property (computed occupancy and ledger fields) | PropertyManager, ConciergeStaff, Resident, Carrier, PmsIntegration |
| PATCH | `/parcelroom/properties/{id}/policy` | Update Property policy under optimistic concurrency | PropertyManager |
| GET | `/parcelroom/properties/{id}/report` | Operational report: utilization, aging, uncollected fees, staging | PropertyManager, ConciergeStaff |
| POST | `/parcelroom/properties/{id}/aging-sweep` | Run aging + cold-chain + overflow batch | PropertyManager, ConciergeStaff |
| GET | `/parcelroom/properties/{id}/locker-banks` | List LockerBanks under a Property | PropertyManager, ConciergeStaff, Resident, Carrier, PmsIntegration |
| GET | `/parcelroom/properties/{id}/shelves` | List Shelves under a Property | PropertyManager, ConciergeStaff, Resident, Carrier, PmsIntegration |
| GET | `/parcelroom/properties/{id}/residents` | List Residents under a Property | PropertyManager, ConciergeStaff, Resident, Carrier, PmsIntegration |
| GET | `/parcelroom/properties/{id}/carriers` | List Carriers under a Property | PropertyManager, ConciergeStaff, Resident, Carrier, PmsIntegration |
| POST | `/parcelroom/locker-banks` | Create a LockerBank | PropertyManager |
| GET | `/parcelroom/locker-banks/{id}` | Get a LockerBank | PropertyManager, ConciergeStaff, Resident, Carrier, PmsIntegration |
| GET | `/parcelroom/locker-banks/{id}/lockers` | List Lockers under a LockerBank | PropertyManager, ConciergeStaff, Resident, Carrier, PmsIntegration |
| POST | `/parcelroom/lockers` | Create a Locker compartment | PropertyManager |
| GET | `/parcelroom/lockers/{id}` | Get a Locker | PropertyManager, ConciergeStaff, Resident, Carrier, PmsIntegration |
| POST | `/parcelroom/lockers/{id}/out-of-service` | Take an AVAILABLE Locker out of service | PropertyManager |
| POST | `/parcelroom/shelves` | Create a staff-managed Shelf | PropertyManager |
| GET | `/parcelroom/shelves/{id}` | Get a Shelf | PropertyManager, ConciergeStaff, Resident, Carrier, PmsIntegration |
| POST | `/parcelroom/residents` | Register a Resident (manual or PMS import) | PropertyManager, PmsIntegration |
| GET | `/parcelroom/residents/{id}` | Get a Resident | PropertyManager, ConciergeStaff, Resident, Carrier, PmsIntegration |
| POST | `/parcelroom/residents/{id}/pms-sync` | Apply a PMS roster lifecycle event | PmsIntegration |
| POST | `/parcelroom/carriers` | Register a Carrier at a Property | PropertyManager |
| GET | `/parcelroom/carriers/{id}` | Get a Carrier | PropertyManager, ConciergeStaff, Resident, Carrier, PmsIntegration |
| POST | `/parcelroom/packages` | Scan/log an inbound package at delivery | Carrier, ConciergeStaff |
| GET | `/parcelroom/packages/{id}` | Get a Package (includes provisional_fee_cents) | PropertyManager, ConciergeStaff, Resident, Carrier, PmsIntegration |
| GET | `/parcelroom/packages` | List/filter Packages | PropertyManager, ConciergeStaff, Resident, Carrier, PmsIntegration |
| POST | `/parcelroom/packages/{id}/notify` | Notify resident, assign storage, issue pickup code | ConciergeStaff |
| POST | `/parcelroom/packages/{id}/pickup` | Resident (or staff) picks up with pickup code | Resident, ConciergeStaff |
| POST | `/parcelroom/packages/{id}/return-initiate` | Evict an awaiting package to return | ConciergeStaff, PropertyManager |
| POST | `/parcelroom/packages/{id}/return-complete` | Confirm returned package handed to carrier (dual-control) | ConciergeStaff, Carrier |
| GET | `/parcelroom/packages/{id}/notifications` | List Notifications for a Package | PropertyManager, ConciergeStaff, Resident, Carrier, PmsIntegration |
| GET | `/parcelroom/packages/{id}/charges` | List StorageCharges for a Package | PropertyManager, ConciergeStaff, Resident, Carrier, PmsIntegration |
| POST | `/parcelroom/retail-returns` | Resident drops off an outbound retail return | Resident |
| GET | `/parcelroom/retail-returns/{id}` | Get a RetailReturn | PropertyManager, ConciergeStaff, Resident, Carrier, PmsIntegration |
| GET | `/parcelroom/retail-returns` | List/filter RetailReturns | PropertyManager, ConciergeStaff, Resident, Carrier, PmsIntegration |
| POST | `/parcelroom/retail-returns/{id}/verify-label` | Staff verifies the return label | ConciergeStaff |
| POST | `/parcelroom/retail-returns/{id}/reject` | Staff rejects a bad-label return | ConciergeStaff |
| POST | `/parcelroom/retail-returns/{id}/carrier-pickup` | Carrier collects the staged return | Carrier |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PropertyManager, PmsIntegration |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADER` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_PROPERTY_NOT_FOUND` | 404 |
| `ERR_LOCKER_BANK_NOT_FOUND` | 404 |
| `ERR_LOCKER_NOT_FOUND` | 404 |
| `ERR_SHELF_NOT_FOUND` | 404 |
| `ERR_RESIDENT_NOT_FOUND` | 404 |
| `ERR_CARRIER_NOT_FOUND` | 404 |
| `ERR_PACKAGE_NOT_FOUND` | 404 |
| `ERR_RETAIL_RETURN_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_RESIDENT_NOT_ACTIVE` | 409 |
| `ERR_COLD_CHAIN_EXPIRED` | 409 |
| `ERR_STORAGE_FROZEN` | 409 |
| `ERR_STORAGE_RESTRICTED` | 409 |
| `ERR_LOCKER_UNAVAILABLE` | 409 |
| `ERR_LOCKER_SIZE_MISMATCH` | 409 |
| `ERR_SHELF_FULL` | 409 |
| `ERR_NO_STORAGE_AVAILABLE` | 409 |
| `ERR_INVALID_PICKUP_CODE` | 403 |
| `ERR_STAGING_FULL` | 409 |
| `ERR_DUPLICATE_TRACKING` | 409 |
| `ERR_STALE_PROPERTY_VERSION` | 412 |
