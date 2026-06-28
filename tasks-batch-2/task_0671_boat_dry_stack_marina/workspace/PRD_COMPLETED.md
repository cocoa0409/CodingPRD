# Boat Dry-Stack Marina API — Product Requirements Document

## 1. Introduction

A dry-stack storage marina warehouses recreational vessels in tiered racks rather than wet slips, lifting each boat in and out of the water on demand with a forklift. This API is the operational backbone for such a facility. It tracks the physical dimensions of every rack bay and every vessel so that a boat is only ever placed where it actually fits; it schedules the forklift launches that splash a boat and haul it back; it prices monthly storage by rack size, oversize surcharge, and peak-versus-off-season demand; and it administers the waitlist that rations scarce rack capacity when the yard is full.

The system serves three operational constituencies whose duties rarely overlap. Dock-side staff move steel and water — they stand up the marina's racks and forklifts, bind vessels to racks, and run the launch and haul-back cycle. Boat owners hold accounts, register their vessels, submit insurance certificates, accept waitlist offers, and pay their bills. Billing staff verify insurance, sweep expiring offers, and issue and settle invoices. Because a vessel cannot be racked without verified insurance, cannot be launched without an available and capacity-rated forklift, and cannot be billed without a settled chronological accounting of its occupancy, the workflows below are heavily cross-referential. This document specifies every rule the implementation must honor; readers should expect a single business fact (a threshold, a cascade, a precondition) to surface in the subsection where it makes operational sense rather than in one consolidated schema block.

All timestamps the system persists are in UTC. The server runs on a **logical clock** that is explicitly set by an operator and never falls back to wall-clock time; every "now" referenced below — offer deadlines, slot openings, seasonal month, days-waiting — is read from that logical clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This includes the clock-setting capability, which still requires valid headers. The system recognizes exactly three roles: `DockMaster`, `BoatOwner`, and `BillingClerk`. When a request carries valid headers but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

`DockMaster` operates the physical plant: creating marinas, forklifts, and racks, driving the full storage-agreement lifecycle, scheduling and running launches, and sweeping the waitlist for promotions. When `X-User-Role` is `DockMaster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`. `BillingClerk` owns insurance verification, the offer-lapse and expiry sweeps, and invoice issuance and voiding. When `X-User-Role` is `BillingClerk`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is never compared to any entity's `id`.

`BoatOwner` is different. When `X-User-Role` is `BoatOwner`, `X-User-ID` is the `id` of the acting `BoatOwnerAccount`; ownership checks on any resource that traces back to a `BoatOwnerAccount` compare the resource's owning account against `X-User-ID`. A vessel references its owner through `owner_id`; launch requests, service orders, and invoices reach an owner through their vessel or directly. When a `BoatOwner` attempts to mutate a vessel, launch request, service order, or invoice that does not belong to them, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the inclusive range of 1 through 100, an `offset` below 0, or a non-integer value supplied for either parameter, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400).

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp in ascending order. The waitlist listing is the documented exception, ordering by descending priority score and then by ascending join time, as detailed in the waitlist narrative.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Mutation Semantics

Every persisted resource exposes a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits marking when it was first created. All entities in this system additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits), refreshed on every mutation, and a `version` integer that begins at the resource's creation and increments by one on every mutation. The `version` field is the basis for optimistic concurrency control described in §2.6.

Whenever the system mutates a resource — whether by direct client action or by a cascade triggered elsewhere — that resource's `updated_at` is refreshed and its `version` is incremented by one. Several operations in this domain mutate more than one resource in a single call; in those cases each affected resource independently has its `updated_at` and `version` advanced. The specific cascades are spelled out in §3.

### 2.5. Nested Reference Resolution and Validation Ordering

Resources in this system are flat: relationships are expressed as foreign-key identifiers carried in request bodies rather than as nested URL paths. When a request references resource identifiers — a `marina_id` on a rack, a `vessel_id` on an agreement, a `source_id` on an invoice — the system resolves each referenced identifier and rejects the request with `ERR_NOT_FOUND` (HTTP 404) if any referenced row does not exist, validating references left to right (the marina first, then the vessel or rack, and so on). The polymorphic invoice source is a special case: when an invoice names a `source_id`, that identifier must resolve to an existing row of the exact type named by `source_kind`, failing which the request is rejected with `ERR_SOURCE_NOT_FOUND` (HTTP 404).

The validations across the system are applied in a fixed priority order, and this order is observable when more than one would fail. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role permission (`ERR_FORBIDDEN_ROLE`), then resource-ownership for `BoatOwner` actions (`ERR_NOT_RESOURCE_OWNER`), then existence of every referenced row (`ERR_NOT_FOUND`), then the polymorphic-source existence check (`ERR_SOURCE_NOT_FOUND`), then whether the requested state transition is legal from the resource's current state (`ERR_INVALID_STATE`), then the optimistic-concurrency rack-version check (`ERR_STALE_RACK_VERSION`). Only after all of those pass does the system evaluate the domain-specific business rules — insurance, forklift capacity, dimension fit, rack availability, scheduling conflicts, occupancy conflicts, slot timing, offer expiry, bay-label uniqueness, single-storage exclusivity, and invoice period validity — and finally the generic request-shape and pagination checks. Where a specific transition's business rules have a meaningful internal order, it is stated in the relevant §3 workflow.

### 2.6. Optimistic Concurrency Control on Rack-Occupying Writes

Two operations in this system claim a rack and therefore guard against acting on a stale view of that rack: accepting a waitlist offer and activating a storage agreement. Both require the caller to supply `expected_rack_version` in the request body, carrying the client's last observed `version` of the target `Rack`. If `expected_rack_version` does not equal the rack's current `version`, the write is rejected with `ERR_STALE_RACK_VERSION` (HTTP 412).

When a `BoatOwner` accepts an offered rack, the rack's `version` may have advanced since the client last read it — for example because a separate promotion sweep re-held it, or a lapse released and re-offered it. Because an offered rack is a legitimately reusable slot, an accept working from an outdated rack view would otherwise bind a second agreement to a rack that has moved on; the `expected_rack_version` mismatch blocks that, returning `ERR_STALE_RACK_VERSION` (HTTP 412). Likewise, when a `DockMaster` activates a `PENDING_COI` agreement onto a rack, the rack's `version` may have advanced since the client last read it — for example because a promotion sweep just held that rack for a different vessel — and the activation working from an outdated rack view is rejected with `ERR_STALE_RACK_VERSION` (HTTP 412). No other endpoint takes a version field; only these two rack-occupying writes carry `expected_rack_version`.

### 2.7. Monetary Precision and Rounding

All monetary amounts in this system are stored as integer cents — there are no fractional cents in any persisted amount. Wherever a calculation produces a non-integer intermediate, the result is rounded to a whole number of cents using the round-half-up method (a value exactly halfway between two integers rounds up). This applies to the monthly storage base rate, the seasonal multiplier, prorated final invoices, and per-line service totals. The launch fee is composed entirely of whole-cent constants and a per-foot charge multiplied by a whole number of feet, so it never requires rounding. Where a calculation sums several amounts, the rounding rule for that specific calculation — round-each-line-then-sum versus round-the-final-product — is stated alongside the calculation in §3, because the two approaches can differ by up to a cent.

### 2.8. Rack Occupancy, Forklift Capacity, and Vessel Fit

Three physical-plant invariants run through the whole system. First, a rack holds at most one vessel: a rack is `AVAILABLE` until an active agreement (or a held waitlist offer) occupies it, at which point it becomes `OCCUPIED`. Activation onto a rack that is not `AVAILABLE` is rejected with `ERR_RACK_NOT_AVAILABLE` (HTTP 409), and the same code guards a promotion sweep that finds no available rack. Second, a forklift is a shared, schedulable machine: its busy interval for a launch may not overlap another live slot on the same forklift, and it must be physically able to lift the vessel. Third, a vessel must dimensionally fit the rack it is placed in. These invariants are enforced at the workflow points described in §3; their thresholds and conflict windows are specified there.

The marina configures its forklift scheduling granularity at creation. The `forklift_service_minutes` value (default 30) is the length of a single launch or haul slot — the service window — and `forklift_buffer_minutes` (default 15) is the turnaround buffer appended to every slot's busy interval for overlap detection on the same forklift. Both are part of the marina record alongside its `name`, its informational `timezone` (default `UTC`, used for display only — all persisted timestamps remain UTC), and the computed `total_rack_count`, which counts the racks belonging to that marina. `forklift_service_minutes` must be an integer of at least 1, and `forklift_buffer_minutes` must be an integer of at least 0.

### 2.9. The Insurance (COI) Gate

No vessel may occupy a rack without verified, in-window insurance. A vessel's `active_policy_id` points to its `InsurancePolicy` whose status is `VERIFIED` and whose effective window covers the logical clock; when no such policy exists it is null. Any operation that requires insurance — activating an agreement, reactivating a winterized agreement, or accepting a waitlist offer — checks that the vessel's `active_policy_id` is not null, and rejects the request with `ERR_COI_NOT_VERIFIED` (HTTP 422) when it is null. The policy lifecycle that populates and clears `active_policy_id` is described in §3.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Marina: Racks, Forklifts, and Owners

A `DockMaster` establishes the physical facility. Creating a marina records its `name` and optional `timezone`, `forklift_service_minutes`, and `forklift_buffer_minutes`. Forklifts are then added to a marina, each carrying its parent `marina_id`, an operator-facing `label` (for example "Wiggins-01"), and a `max_lift_weight_lbs` indicating the heaviest vessel dry weight it can lift, which must be a positive integer. A forklift's `status` is set to `AVAILABLE` at creation and only `AVAILABLE` forklifts are candidates when a launch is being scheduled.

Racks are likewise created under a `marina_id`, each with a `bay_label` (its physical position, e.g. "A-12"), a `size_class` of `SMALL`, `MEDIUM`, or `LARGE` that drives the monthly storage base rate, and three fit limits: `max_loa_ft` (maximum vessel length-overall in feet), `max_beam_ft` (maximum beam in feet), and `max_weight_lbs` (maximum dry weight in pounds). The two foot dimensions are positive numbers carried to two decimals; the weight limit is a positive integer. A rack's `bay_label` must be unique among the racks of the same `marina_id`; a duplicate label is rejected with `ERR_DUPLICATE_BAY_LABEL` (HTTP 409). A rack begins life with `status` `AVAILABLE` and a null `current_agreement_id`; once an active or winterized agreement holds it, `status` becomes `OCCUPIED` and `current_agreement_id` records the holding agreement's id.

A `BoatOwnerAccount` is created (by a `DockMaster` or a `BillingClerk`) under a `marina_id` with a `full_name` and an `email`. Each account exposes a computed `account_balance_cents`, the outstanding amount the owner owes — never below zero — recomputed whenever the account is read and whenever an invoice for that owner is issued, paid, or voided. As detailed in §3.7, the balance is the sum of the `amount_cents` of that owner's invoices that are still in `ISSUED` status; invoices that are `PAID` or `VOIDED` do not contribute.

A vessel is registered under a `marina_id` and an `owner_id`, with a `name` and its physical particulars: `loa_ft` and `beam_ft` (positive numbers, two decimals) and `dry_weight_lbs` (positive integer). A `BoatOwner` may register a vessel only under their own account; when a `BoatOwner` supplies an `owner_id` other than their own `X-User-ID` the registration is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403), evaluated after the referenced `marina_id` and `owner_id` are confirmed to exist. A newly registered vessel starts with `location_status` `OFF_SITE` and `billing_status` `UNBILLED`, and a null `active_policy_id`. These two status dimensions are independent: `location_status` (one of `OFF_SITE`, `RACKED`, `IN_WATER`) tracks where the boat physically is, while `billing_status` (one of `UNBILLED`, `ACTIVE_STORAGE`, `WINTER_HOLD`, `DELINQUENT`, `CLOSED`) tracks its billing posture, and each evolves on its own as the workflows below fire.

### 3.2. Insurance Certificates and the Verification Lifecycle

Insurance is submitted as an `InsurancePolicy` against a `vessel_id`, recording the `carrier_name`, the `liability_limit_cents` (a positive integer), and the coverage window `effective_from` (inclusive start) and `effective_to` (exclusive end), both ISO 8601 UTC. A submitted policy begins in `SUBMITTED` status. From there it follows a verification lifecycle with two terminal outcomes, `REJECTED` and `EXPIRED`.

A `BillingClerk` reviews a `SUBMITTED` policy. Verifying it (`SUBMITTED → VERIFIED`) is permitted only while the policy is in `SUBMITTED` status, only when `effective_to` is strictly later than `effective_from`, and only when `liability_limit_cents` meets or exceeds the system's minimum liability floor — a floor of zero cents, so that any policy (whose `liability_limit_cents` is already constrained to a positive integer at submission) clears it. A verify attempt that fails the status, window-ordering, or floor precondition is rejected with `ERR_INVALID_STATE` (HTTP 409). On verification the policy moves to `VERIFIED`; if the vessel's `active_policy_id` is currently null and this newly verified policy's effective window itself covers the logical clock (`effective_from ≤ clock < effective_to`), the vessel's `active_policy_id` is set to this policy's id — a verified policy whose window does not cover the clock leaves `active_policy_id` null. Alternatively a `SUBMITTED` policy may be rejected (`SUBMITTED → REJECTED`), permitted only from `SUBMITTED`, which simply moves it to `REJECTED`. A `VERIFIED` policy expires (`VERIFIED → EXPIRED`) only when it is still `VERIFIED` and the logical clock has reached or passed its `effective_to` (an expire attempt while the policy is not `VERIFIED`, or before the clock reaches `effective_to`, is rejected with `ERR_INVALID_STATE`, HTTP 409); on expiry the policy moves to `EXPIRED`, and if it was the vessel's `active_policy_id`, that pointer is cleared back to null. Each of these three transitions increments the policy's `version`. A vessel's `active_policy_id` thus reflects, at any moment, the existence of a `VERIFIED` policy whose window covers the clock — the gate every rack-occupying operation consults per §2.9.

### 3.3. Binding a Vessel to a Rack: The Storage Agreement Lifecycle

A `StorageAgreement` binds a `vessel_id` to a `rack_id`. A `DockMaster` creates the agreement in `PENDING_COI` status; at creation the system checks that the vessel physically fits the named rack — `loa_ft` no greater than the rack's `max_loa_ft`, `beam_ft` no greater than `max_beam_ft`, and `dry_weight_lbs` no greater than `max_weight_lbs` — rejecting a misfit with `ERR_VESSEL_DIMENSIONS_EXCEED_RACK` (HTTP 422). The agreement carries computed fields populated later: `tier_size_class`, `monthly_base_cents`, `oversize_surcharge_applied`, `activated_at`, and `terminated_at`. Its `status` is one of `PENDING_COI`, `ACTIVE`, `WINTERIZED`, or `TERMINATED`, with `TERMINATED` terminal.

**Activation** (`PENDING_COI → ACTIVE`) is the central operation and the most heavily guarded. It is permitted only while the agreement is in `PENDING_COI` status. It carries `expected_rack_version` for the optimistic-concurrency check of §2.6 (mismatch → `ERR_STALE_RACK_VERSION`, HTTP 412). It requires the vessel's `active_policy_id` to be non-null (else `ERR_COI_NOT_VERIFIED`, HTTP 422); it requires the target rack to be `AVAILABLE` (else `ERR_RACK_NOT_AVAILABLE`, HTTP 409); and it re-checks dimensional fit (`loa_ft ≤ max_loa_ft`, `beam_ft ≤ max_beam_ft`, `dry_weight_lbs ≤ max_weight_lbs`, else `ERR_VESSEL_DIMENSIONS_EXCEED_RACK`, HTTP 422). The vessel may not already hold another agreement in `ACTIVE` or `WINTERIZED` status; if it does, activation is rejected with `ERR_VESSEL_ALREADY_STORED` (HTTP 409). Finally, the rack's occupancy intervals must not overlap: the half-open interval from this agreement's `activated_at` up to but not including its `terminated_at` must not overlap any existing occupancy interval on the same rack — adjacency, where one occupancy begins exactly when another ended, is allowed — and an overlap is rejected with `ERR_RACK_OCCUPANCY_CONFLICT` (HTTP 409).

When activation succeeds, several things happen at once. The agreement snapshots `tier_size_class` from the rack's current `size_class` (pinning the storage rate even if the rack is later reclassified), and `monthly_base_cents` together with `oversize_surcharge_applied` are computed as described below. The agreement's `activated_at` is stamped with the logical clock and its `status` becomes `ACTIVE`. As the first cascade hop, the rack's `status` becomes `OCCUPIED`, its `current_agreement_id` is set to this agreement's id, and the rack's `version` is incremented. As the second cascade hop — caused by the rack becoming occupied — the vessel's `location_status` becomes `RACKED` and its `billing_status` becomes `ACTIVE_STORAGE`. Both the agreement and the rack and the vessel have their `updated_at` refreshed and `version` incremented.

The monthly storage base rate is pinned at activation. The base for the snapshotted `tier_size_class` is 20000 cents for `SMALL`, 35000 cents for `MEDIUM`, and 52500 cents for `LARGE`. An oversize surcharge applies when the vessel is nearly as long as the rack permits: specifically, when the rack's `max_loa_ft` minus the vessel's `loa_ft` is at most half a foot (0.5 ft), the vessel is within the oversize band. When within the band, `monthly_base_cents` is the base multiplied by 1.15 (a fifteen-percent surcharge), rounded half up to whole cents, and `oversize_surcharge_applied` is set true; otherwise `monthly_base_cents` is exactly the base and `oversize_surcharge_applied` is false. The seasonal multiplier is never folded into `monthly_base_cents` — it is applied later, at invoice time, as described in §3.7.

**Winterization** (`ACTIVE → WINTERIZED`) is permitted only while the agreement is `ACTIVE` and only while the bound vessel's `location_status` is `RACKED` (the boat is in its rack, not in the water); a winterize attempt where the agreement is not `ACTIVE`, or where the vessel is not `RACKED`, is rejected with `ERR_INVALID_STATE` (HTTP 409). It moves the agreement to `WINTERIZED` and flips the vessel's `billing_status` to `WINTER_HOLD`, incrementing the agreement's `version`. **Reactivation** (`WINTERIZED → ACTIVE`) is permitted only while the agreement is `WINTERIZED` and only while the vessel's `active_policy_id` is non-null (else `ERR_COI_NOT_VERIFIED`, HTTP 422); it returns the agreement to `ACTIVE` and the vessel's `billing_status` to `ACTIVE_STORAGE`, incrementing the agreement's `version`. The seasonal cycle of `ACTIVE → WINTERIZED → ACTIVE` may repeat across seasons.

**Termination** ends an agreement and frees its rack as a compensation for the original activation. From `ACTIVE`, termination is permitted only while the agreement is `ACTIVE` and only while the vessel's `location_status` is not `IN_WATER` (no boat may be terminated while it is splashed and out on the water); a termination attempt while the agreement is `ACTIVE` but the vessel is `IN_WATER` is rejected with `ERR_INVALID_STATE` (HTTP 409). From `WINTERIZED`, termination is permitted whenever the agreement is `WINTERIZED`. In both cases the agreement's `status` becomes `TERMINATED`, its `terminated_at` is stamped with the logical clock; as compensation the rack's `status` returns to `AVAILABLE`, its `current_agreement_id` is cleared to null, and the rack's `version` is incremented; and the vessel's `location_status` becomes `OFF_SITE` while its `billing_status` becomes `CLOSED`. The agreement's `version` is incremented. Freeing the rack makes it eligible for a subsequent waitlist promotion sweep; any waitlist entry already in `OFFERED` status that holds a different rack is unaffected. A requested transition that is not legal from the agreement's current status is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.4. The Waitlist: Priority, Offers, and Placement

When the yard is full, owners queue on the waitlist. A `WaitlistEntry` is created against a `vessel_id` with a `requested_size_class` (the `SMALL`, `MEDIUM`, or `LARGE` rack the owner wants) and an optional `deposit_paid` flag (default false) indicating a priority deposit was paid. The entry's `joined_at` is stamped with the logical clock at creation and is the basis for waiting time. The entry exposes a computed `priority_score` and an `offered_rack_id` and `offer_expires_at` that are null until an offer is made. Its `status` runs through `WAITING`, `OFFERED`, `PLACED`, `EXPIRED`, and `WITHDRAWN`, with `PLACED`, `EXPIRED`, and `WITHDRAWN` terminal.

Priority ranks WAITING entries. The entry's days-waiting is the whole number of days between its `joined_at` and the logical clock — computed as the elapsed seconds divided by 86400 and then floored to a whole number of days, and clamped to zero should the logical clock precede `joined_at`. The `priority_score` is that days-waiting count plus a deposit bonus of 100000 when `deposit_paid` is true (and zero when it is false). Reading a single waitlist entry or listing the waitlist recomputes `priority_score` against the logical clock at read time, so a later read of the same entry yields a higher score as more whole days accrue. The waitlist list endpoint is ordered by `priority_score` descending, then by `joined_at` ascending.

A **promotion sweep**, run by a `DockMaster`, takes a `marina_id` and a `requested_size_class` and offers an available rack to the best waiting entry. It requires an `AVAILABLE` rack in that marina whose `size_class` equals the requested class to exist (else `ERR_RACK_NOT_AVAILABLE`, HTTP 409); when several such racks are available the sweep holds the earliest-created one. Among all `WAITING` entries with that same `requested_size_class`, the sweep selects the maximum `priority_score`, breaking ties first by earliest `joined_at` and then by earliest `created_at`; the entry id is never used in the decision. If an available rack exists but no `WAITING` entry of that `requested_size_class` is present, the sweep is rejected with `ERR_INVALID_STATE` (HTTP 409). Crucially, the sweep measures days-waiting against the logical clock at the sweep instant and freezes that score into the selection, so two sweeps run at different clock positions can rank the same two entries differently if one entry has crossed a whole-day boundary that the other has not. The selected winner transitions `WAITING → OFFERED` (permitted only from `WAITING`): its `offered_rack_id` is set to the selected rack, that rack's `status` becomes `OCCUPIED` as a held reservation while its `current_agreement_id` stays null, the rack's `version` is incremented, and the entry's `offer_expires_at` is set to the logical clock plus the offer time-to-live (described below). The entry's `version` is incremented.

**Accepting** an offer (`OFFERED → PLACED`) is a `BoatOwner` action and is the second rack-occupying write that carries `expected_rack_version` for the optimistic-concurrency check of §2.6. Acceptance is permitted only while the entry is `OFFERED`, only while the logical clock is strictly before `offer_expires_at` (at or after the deadline the accept is rejected with `ERR_OFFER_EXPIRED`, HTTP 409), and only while the vessel's `active_policy_id` is non-null (else `ERR_COI_NOT_VERIFIED`, HTTP 422). The vessel must not already hold an `ACTIVE` or `WINTERIZED` agreement (else `ERR_VESSEL_ALREADY_STORED`, HTTP 409). On success the system creates a new `StorageAgreement` in `PENDING_COI` status binding the entry's `vessel_id` to its `offered_rack_id` as a cascade, moves the entry to `PLACED`, and increments the entry's `version`; this cascade-created agreement does not itself hold the rack (it stays `PENDING_COI` until separately activated) nor advance the rack's `version`. The offer time-to-live is a fixed 48 hours after which an unaccepted offer may be lapsed.

A `BillingClerk` lapses an expired offer (`OFFERED → EXPIRED`), permitted only while the entry is `OFFERED` and the logical clock has reached or passed `offer_expires_at` (a lapse attempted before the clock reaches `offer_expires_at` is rejected with `ERR_INVALID_STATE`, HTTP 409); as compensation for the held reservation, the offered rack's `status` returns to `AVAILABLE`, its rack `version` is incremented, the entry's `offered_rack_id` is cleared to null, and the entry moves to `EXPIRED` with its `version` incremented. A `BoatOwner` may withdraw a still-waiting entry (`WAITING → EXPIRED`-style withdrawal, specifically `WAITING → WITHDRAWN`), permitted only while the entry is `WAITING`, moving it to `WITHDRAWN` and incrementing its `version`. Any of these transitions attempted from a status from which it is not defined is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.5. Launches: Forklift Scheduling, Splash, and Haul-Back

A launch takes a racked boat out of its bay, onto a forklift, and into the water; later it comes back. A `LaunchRequest` is created against a `vessel_id` with a `requested_window_start` (the desired launch start instant, ISO 8601 UTC) and an optional `with_valet_splash` flag (default false) bundling a valet splash service. It begins in `REQUESTED` status, with a computed `forklift_slot_id` (null until scheduled) and a computed `launch_fee_cents` (zero until scheduled). The `status` is cyclic across `REQUESTED`, `SCHEDULED`, `SPLASHED`, `RACKED`, and `CANCELLED`, with `CANCELLED` terminal.

**Scheduling** a launch (`REQUESTED → SCHEDULED`), a `DockMaster` action, is permitted only while the request is `REQUESTED` and only while the vessel's `location_status` is `RACKED` (the boat must be in its rack to launch); a schedule attempt where the request is not `REQUESTED`, or where the vessel is not `RACKED`, is rejected with `ERR_INVALID_STATE` (HTTP 409). The system must be able to book a `ForkliftSlot` at the `requested_window_start` on some `AVAILABLE` forklift belonging to the vessel's own marina whose `max_lift_weight_lbs` is at least the vessel's `dry_weight_lbs`. If no such capacity-eligible forklift exists in that marina, the request is rejected with `ERR_FORKLIFT_CAPACITY_EXCEEDED` (HTTP 422). A `ForkliftSlot` records its parent `forklift_id`, the `launch_request_id` it serves (null when released), its `window_start` (the supplied service-start instant), its computed `window_end` (`window_start` plus the marina's `forklift_service_minutes`), and its computed `busy_until` (`window_start` plus `forklift_service_minutes` plus `forklift_buffer_minutes` — the exclusive end of the forklift's busy interval). A slot's `status` is one of `BOOKED`, `COMPLETED`, or `RELEASED`. The new slot's busy interval — the half-open span from `window_start` up to but not including `busy_until` — must not overlap any non-`RELEASED` slot on the same forklift; adjacency at `busy_until` (one slot's busy interval ending exactly when the next begins) is allowed. When every capacity-eligible forklift has an overlapping live slot, scheduling is rejected with `ERR_FORKLIFT_SLOT_CONFLICT` (HTTP 409); otherwise the earliest-created capacity-eligible forklift with a free window is selected. On success the system creates the slot in `BOOKED` status on the selected forklift, links it both ways (the slot's `launch_request_id` and the request's `forklift_slot_id`), computes `launch_fee_cents`, moves the request to `SCHEDULED`, and increments the request's `version`.

The launch fee is assembled from a base, a per-foot charge, an optional heavy-vessel surcharge, and an optional splash fee. The base is 4500 cents. The per-foot component is 250 cents multiplied by the vessel's `loa_ft` rounded up to the next whole foot. A heavy surcharge of 3000 cents applies when the vessel's `dry_weight_lbs` is strictly greater than 8000 pounds, and is zero otherwise. A splash fee of 6000 cents applies when `with_valet_splash` is true, and is zero otherwise. The `launch_fee_cents` is the sum of those four parts; because every part is a whole number of cents, no rounding is needed.

**Unscheduling** (`SCHEDULED → REQUESTED`) is the cyclic revert: permitted only while the request is `SCHEDULED`, it releases the booked slot (the `ForkliftSlot` becomes `RELEASED` and its `launch_request_id` is cleared to null, freeing the interval) as a cascade, clears the request's `forklift_slot_id` to null, returns the request to `REQUESTED`, and increments its `version`. **Splashing** (`SCHEDULED → SPLASHED`) puts the boat in the water: permitted only while the request is `SCHEDULED` and only once the logical clock has reached or passed the booked slot's `window_start` — an earlier attempt is rejected with `ERR_SLOT_NOT_YET_OPEN` (HTTP 409). On splash the booked slot's `status` becomes `COMPLETED` as the first cascade hop; caused by that slot completing, the vessel's `location_status` becomes `IN_WATER` as the second hop, while the rack stays `OCCUPIED` because the agreement still holds it — the vessel is merely absent. The request's `version` is incremented. **Haul-back** (`SPLASHED → RACKED`) is the cyclic return loop: permitted only while the request is `SPLASHED`, it returns the vessel's `location_status` to `RACKED`, moves the request to `RACKED`, and increments its `version`.

A `BoatOwner` may **cancel** a launch request. From `REQUESTED`, cancellation (permitted only from `REQUESTED`) simply moves the request to `CANCELLED`. From `SCHEDULED`, cancellation (permitted only from `SCHEDULED`) additionally releases the booked slot as compensation for the schedule's booking — the `ForkliftSlot` becomes `RELEASED` and its `launch_request_id` is cleared to null — clears the request's `forklift_slot_id` to null, and resets `launch_fee_cents` to zero before moving the request to `CANCELLED`. Either cancellation increments the request's `version`. A transition requested from a status where it is not defined is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.6. Valet, Fuel, and Haul Services

Beyond launches, owners order discrete services. A `ServiceOrder` is created against a `vessel_id` with a `service_kind` of `FUEL`, `VALET_SPLASH`, `WINTERIZATION`, or `HAUL_OUT`. For a `FUEL` order, the request also carries `fuel_gallons` (a non-negative number to three decimals, default 0) and `fuel_price_cents_per_gal` (a non-negative integer, default 0); for other kinds these fuel fields are ignored. The order begins in `ORDERED` status, exposes a computed `total_cents`, and runs through `ORDERED`, `FULFILLED`, or `CANCELLED`, the latter two terminal.

The `total_cents` is computed at creation. For a `FUEL` order it is the single fuel line — `fuel_gallons` multiplied by `fuel_price_cents_per_gal` — rounded half up to whole cents (the per-line round); because there is exactly one line, the total equals that rounded line. For `VALET_SPLASH` the total is 6000 cents. For `WINTERIZATION` the total is 25000 cents. For `HAUL_OUT` the total is 18000 cents. The rounding rule is round-each-line-then-sum: each line is rounded to whole cents before any summation, which can differ by up to a cent from summing first.

A `DockMaster` fulfills an order (`ORDERED → FULFILLED`), permitted only from `ORDERED`, moving it to `FULFILLED`. A `BoatOwner` cancels an order (`ORDERED → CANCELLED`), permitted only from `ORDERED`, moving it to `CANCELLED`. Each transition increments the order's `version`; a transition from any other status is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.7. Invoicing, Seasonal Pricing, and Settlement

A `BillingClerk` issues a `StorageInvoice` against an `owner_id` and a polymorphic source identified by `source_kind` (one of `STORAGE_AGREEMENT`, `LAUNCH_REQUEST`, or `SERVICE_ORDER`) and `source_id`. As noted in §2.5, the `source_id` must resolve to an existing row of the declared `source_kind`, else `ERR_SOURCE_NOT_FOUND` (HTTP 404). The invoice carries a `variant` (default `FINAL`), a `period_start` and `period_end` (both ISO 8601 UTC, used only for storage invoices), a computed `amount_cents`, and a `status` of `ISSUED`, `PAID`, or `VOIDED`. It is issued in `ISSUED` status.

The `amount_cents` depends on the source kind. For a `LAUNCH_REQUEST` source, the amount is simply the launch's `launch_fee_cents`. For a `SERVICE_ORDER` source, the amount is the order's `total_cents`. For a `STORAGE_AGREEMENT` source, the amount layers the seasonal multiplier on top of the agreement's pinned `monthly_base_cents`. The seasonal factor is determined by the UTC month of `period_start`: months May through September inclusive (month 5 through month 9) are peak and carry a multiplier of 1.20; all other months are off-season and carry a multiplier of 1.00. The seasonal monthly amount is `monthly_base_cents` multiplied by that factor, rounded half up to whole cents.

Storage invoices come in two variants, which must be treated with equal care. The **provisional** variant (`variant` `PROVISIONAL`), issued at the start of a period, is forward-looking: it assumes the vessel stays the whole month and bills the full seasonal monthly amount, ignoring `period_end`. The **final** variant (`variant` `FINAL`), issued at period close, is chronological and prorated: it multiplies the seasonal monthly amount by the billable days divided by the number of days in the month of `period_start`, rounded half up to whole cents. The billable-days count is the inclusive day span across the half-open period from `period_start` up to but not including `period_end`. The difference between the provisional amount and the final amount is the proration credit delta. For any storage invoice — both `PROVISIONAL` and `FINAL` — both `period_start` and `period_end` must be present (even though a `PROVISIONAL` invoice ignores `period_end` in its amount), and for a `STORAGE_AGREEMENT` `FINAL` invoice the `period_end` must additionally be strictly after `period_start`; a missing `period_start` or `period_end` on a storage invoice, or a `FINAL` `period_end` not strictly after `period_start`, is rejected with `ERR_INVALID_PERIOD` (HTTP 422), while a present-but-unparseable `period_start`/`period_end` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). For `LAUNCH_REQUEST` and `SERVICE_ORDER` sources the `variant` is treated as `FINAL` regardless of what is supplied.

Issuing an invoice may push the owner over the delinquency line. The owner's outstanding balance is the sum of `amount_cents` across that owner's invoices still in `ISSUED` status (`PAID` and `VOIDED` excluded). When that balance reaches or exceeds the delinquency threshold of 50000 cents, the `billing_status` of the vessel tied to the newly issued invoice's source — the agreement's, launch request's, or service order's `vessel_id` — flips to `DELINQUENT` (and only if it was not already `DELINQUENT`).

A `BoatOwner` pays an issued invoice (`ISSUED → PAID`), permitted only while the invoice is `ISSUED`; the invoice moves to `PAID`, the owner's balance is recomputed, and if the recomputed balance is now zero (no other `ISSUED` invoices remain for that owner) and the `billing_status` of the vessel tied to this paid invoice's source was `DELINQUENT`, that vessel's `billing_status` is restored to `ACTIVE_STORAGE`. A `BillingClerk` voids an issued invoice (`ISSUED → VOIDED`), permitted only while the invoice is `ISSUED`; the invoice moves to `VOIDED` and the owner's balance is recomputed. Each transition increments the invoice's `version`. Attempting to pay or void an invoice that is not `ISSUED` is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.8. Reads, Request Shape, and Cross-Role Visibility

Most read endpoints are available to all three roles, while a few — listing forklifts, fetching a forklift, fetching or listing forklift slots, and listing owner accounts — are restricted to operational and billing staff. A forklift slot is read by its `id` and exposes `window_start`, `window_end`, `busy_until`, and `status`; slots are also listable filtered by `forklift_id`, `launch_request_id`, and `status`. Every mutating request must carry its required body fields, well-typed, with any enum value drawn from the declared set; a missing required field, a wrong type, or an out-of-set enum value is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Listing endpoints across the system accept their documented filters alongside `limit` and `offset`: racks filter by `marina_id`, `size_class`, `status`, and `current_agreement_id`; vessels by `marina_id`, `owner_id`, `location_status`, `billing_status`, and `active_policy_id`; agreements by `vessel_id`, `rack_id`, and `status`; launch requests by `vessel_id`, `forklift_slot_id`, and `status`; service orders by `vessel_id`, `service_kind`, and `status`; insurance policies by `vessel_id` and `status`; invoices by `owner_id`, `source_kind`, `source_id`, and `status`; waitlist entries by `vessel_id`, `requested_size_class`, `status`, and `offered_rack_id`; forklifts and owners by `marina_id`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state transitions — return `200 OK`. The clock-setting capability advances the server's logical clock to a supplied `to_iso8601` instant and returns `200 OK`; the request body must carry `to_iso8601` as a parseable ISO-8601 instant (a missing or unparseable value is rejected with `ERR_INVALID_REQUEST`, HTTP 400). Before any such call the clock reads its startup default — `2026-04-01T00:00:00Z` — and never falls back to wall-clock time.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | DockMaster, BillingClerk |
| POST | `/marina/marinas` | Create a marina | DockMaster |
| GET | `/marina/marinas/{id}` | Fetch a marina | DockMaster, BillingClerk, BoatOwner |
| GET | `/marina/marinas` | List marinas | DockMaster, BillingClerk, BoatOwner |
| POST | `/marina/forklifts` | Create a forklift for a marina | DockMaster |
| GET | `/marina/forklifts/{id}` | Fetch a forklift | DockMaster, BillingClerk |
| GET | `/marina/forklifts` | List forklifts; filter by marina | DockMaster, BillingClerk |
| POST | `/marina/racks` | Create a rack bay | DockMaster |
| GET | `/marina/racks/{id}` | Fetch a rack (includes version for OCC) | DockMaster, BillingClerk, BoatOwner |
| GET | `/marina/racks` | List racks | DockMaster, BillingClerk, BoatOwner |
| POST | `/marina/owners` | Create a boat owner account | DockMaster, BillingClerk |
| GET | `/marina/owners/{id}` | Fetch an owner account incl. balance | DockMaster, BillingClerk, BoatOwner |
| GET | `/marina/owners` | List owner accounts | DockMaster, BillingClerk |
| POST | `/marina/vessels` | Register a vessel under an owner | DockMaster, BoatOwner |
| GET | `/marina/vessels/{id}` | Fetch a vessel | DockMaster, BillingClerk, BoatOwner |
| GET | `/marina/vessels` | List vessels | DockMaster, BillingClerk, BoatOwner |
| POST | `/marina/insurance-policies` | Submit a COI for a vessel | BillingClerk, BoatOwner |
| GET | `/marina/insurance-policies/{id}` | Fetch an insurance policy | DockMaster, BillingClerk, BoatOwner |
| GET | `/marina/insurance-policies` | List insurance policies | DockMaster, BillingClerk, BoatOwner |
| POST | `/marina/insurance-policies/{id}/verify` | Verify a submitted COI | BillingClerk |
| POST | `/marina/insurance-policies/{id}/reject` | Reject a submitted COI | BillingClerk |
| POST | `/marina/insurance-policies/{id}/expire` | Expire a verified COI past its window | BillingClerk |
| POST | `/marina/storage-agreements` | Create a PENDING_COI agreement | DockMaster |
| GET | `/marina/storage-agreements/{id}` | Fetch a storage agreement | DockMaster, BillingClerk, BoatOwner |
| GET | `/marina/storage-agreements` | List storage agreements | DockMaster, BillingClerk, BoatOwner |
| POST | `/marina/storage-agreements/{id}/activate` | Activate an agreement; occupies rack (OCC) | DockMaster |
| POST | `/marina/storage-agreements/{id}/winterize` | Winterize an active agreement | DockMaster |
| POST | `/marina/storage-agreements/{id}/reactivate` | Reactivate a winterized agreement | DockMaster |
| POST | `/marina/storage-agreements/{id}/terminate` | Terminate an agreement; frees rack | DockMaster |
| POST | `/marina/waitlist` | Join the waitlist for a size class | DockMaster, BoatOwner |
| GET | `/marina/waitlist/{id}` | Fetch a waitlist entry incl. priority | DockMaster, BillingClerk, BoatOwner |
| GET | `/marina/waitlist` | List waitlist entries (priority order) | DockMaster, BillingClerk, BoatOwner |
| POST | `/marina/waitlist/promote` | Promotion sweep: offer rack to best entry | DockMaster |
| POST | `/marina/waitlist/{id}/accept` | Accept an offered rack (OCC) | BoatOwner |
| POST | `/marina/waitlist/{id}/lapse` | Lapse an expired offer; frees held rack | BillingClerk |
| POST | `/marina/waitlist/{id}/withdraw` | Withdraw a waiting entry | BoatOwner |
| POST | `/marina/launch-requests` | Create a launch request | DockMaster, BoatOwner |
| GET | `/marina/launch-requests/{id}` | Fetch a launch request | DockMaster, BillingClerk, BoatOwner |
| GET | `/marina/launch-requests` | List launch requests | DockMaster, BillingClerk, BoatOwner |
| POST | `/marina/launch-requests/{id}/schedule` | Schedule a launch; books a slot | DockMaster |
| POST | `/marina/launch-requests/{id}/unschedule` | Unschedule; releases the slot | DockMaster |
| POST | `/marina/launch-requests/{id}/splash` | Splash the vessel; slot completes | DockMaster |
| POST | `/marina/launch-requests/{id}/haul-back` | Haul the vessel back to its rack | DockMaster |
| POST | `/marina/launch-requests/{id}/cancel` | Cancel a launch; releases any slot | BoatOwner |
| GET | `/marina/forklift-slots/{id}` | Fetch a forklift slot | DockMaster, BillingClerk |
| GET | `/marina/forklift-slots` | List forklift slots | DockMaster, BillingClerk |
| POST | `/marina/service-orders` | Order a fuel/valet/winterization/haul service | DockMaster, BoatOwner |
| GET | `/marina/service-orders/{id}` | Fetch a service order | DockMaster, BillingClerk, BoatOwner |
| GET | `/marina/service-orders` | List service orders | DockMaster, BillingClerk, BoatOwner |
| POST | `/marina/service-orders/{id}/fulfill` | Mark a service order fulfilled | DockMaster |
| POST | `/marina/service-orders/{id}/cancel` | Cancel a service order | BoatOwner |
| POST | `/marina/invoices` | Issue an invoice against a source | BillingClerk |
| GET | `/marina/invoices/{id}` | Fetch an invoice | DockMaster, BillingClerk, BoatOwner |
| GET | `/marina/invoices` | List invoices | DockMaster, BillingClerk, BoatOwner |
| POST | `/marina/invoices/{id}/pay` | Pay an issued invoice | BoatOwner |
| POST | `/marina/invoices/{id}/void` | Void an issued invoice | BillingClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_SOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_RACK_VERSION` | 412 Precondition Failed |
| `ERR_COI_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_FORKLIFT_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_VESSEL_DIMENSIONS_EXCEED_RACK` | 422 Unprocessable Entity |
| `ERR_RACK_NOT_AVAILABLE` | 409 Conflict |
| `ERR_FORKLIFT_SLOT_CONFLICT` | 409 Conflict |
| `ERR_RACK_OCCUPANCY_CONFLICT` | 409 Conflict |
| `ERR_SLOT_NOT_YET_OPEN` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_DUPLICATE_BAY_LABEL` | 409 Conflict |
| `ERR_VESSEL_ALREADY_STORED` | 409 Conflict |
| `ERR_INVALID_PERIOD` | 422 Unprocessable Entity |
| `ERR_INVALID_PAGINATION` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
