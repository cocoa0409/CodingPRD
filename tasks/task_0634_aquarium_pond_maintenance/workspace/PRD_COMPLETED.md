# Aquarium & Pond Maintenance API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Aquarium & Pond Maintenance platform, a back-office system that lets a maintenance company run recurring aquatic service for residential and commercial accounts. The business revolves around physical water systems — reef tanks, freshwater aquaria, ponds, and paludaria — that hold live animals, depend on filtration and circulation equipment, and need regular hands-on attention. Around each account the platform coordinates a recurring service route, water chemistry testing with dosing recommendations, equipment repair and filter-media replacement schedules, livestock health and quarantine, new-system install projects, after-hours emergency response, and the per-visit billing and contract that ties it all together.

The platform exists to keep three things consistent that would otherwise drift apart in spreadsheets: the operational posture of each water system (is it stocked safely, is it due for media, is it active or suspended), the money owed against the contract, and the calendar of technicians who must never be double-booked. Many of the hardest rules in this domain are cross-cutting — completing a single visit must bill the account, advance equipment schedules, and possibly resolve an emergency all at once; suspending a contract for non-payment must ripple down to its systems. The requirements below describe those workflows in business terms first, then pin down the precise contract — response shapes, identifiers, rounding, concurrency, and error semantics — that every implementation must honor exactly.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint regardless of the business workflow it serves.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`; an `X-User-ID` that is empty or whitespace-only and an `X-User-Role` whose value is not exactly one of the four recognized role strings both count as malformed for this purpose and yield `ERR_UNAUTHENTICATED` (not `ERR_FORBIDDEN_ROLE`). The system recognizes exactly four roles, spelled precisely as follows: `AccountManager`, `FieldTech`, `Dispatcher`, and `CustomerOwner`. When a request carries valid, recognized headers but the acting role is not permitted to invoke the targeted endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Two of the four roles are tied to a persisted entity, and two are opaque operator identities. When `X-User-Role` is `FieldTech`, `X-User-ID` is the `tech_user_id` of the acting `Technician`; ownership and identity checks that compare a technician against a resource (for example, that the tech starting a visit is the one assigned to it) resolve the acting `Technician` by matching `X-User-ID` to `tech_user_id`, and then compare the resolved `Technician.id` to the resource's `technician_id`. When `X-User-Role` is `CustomerOwner`, `X-User-ID` is the `customer_user_id` of the acting `ServiceContract`; ownership checks on any resource that ultimately rolls up to a contract compare the contract's `customer_user_id` field to `X-User-ID`. When `X-User-Role` is `AccountManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and log it but does not compare it to any entity's `id`. When `X-User-Role` is `Dispatcher`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

Ownership is enforced specifically for `CustomerOwner` actions that touch a contract-scoped resource. When a `CustomerOwner` disputes a visit, approves an install, or cancels a feeding plan, the acting `X-User-ID` must equal the `customer_user_id` of the `ServiceContract` that owns the underlying system or project; if it does not, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, all list responses are sorted by the resource's `created_at` timestamp in ascending order, with the resource's `id` as the ascending tie-breaker when two records share a `created_at`. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when `offset` plus the number of items returned on this page is strictly less than `total_count`. List endpoints additionally accept optional equality-filter query parameters drawn from the listed resource's own fields — for example `status` wherever a resource carries one, plus `route_day` on contracts, `device_kind` on equipment, `parameter` on water tests, `source_kind` on contract invoices, and `system_id`, `technician_id`, and `emergency_call_id` on the visits list; each supplied filter restricts the result set to records whose field equals the given value, and an unrecognized filter parameter is ignored.

### 2.4. Common Resource Properties and Versioning

Nearly all resources in the system — `ServiceContract`, `SystemProfile`, `Livestock`, `Equipment`, `Technician`, `ServiceVisit`, `Invoice`, `InstallProject`, `EmergencyCall`, `RepairOrder`, `QuarantineRecord`, and `VacationFeedingPlan` — carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix (a standard hyphenated UUID, version 4 in practice). The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits captured at creation, and the `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation; both of these envelope/lifecycle timestamps — like the response `api_request_timestamp` of §2.2 — are taken from the server's real wall-clock time, distinct from and never overridden by the logical clock of §3.11 (the logical clock governs only completion dates, media due dates, overdue evaluation, and feeding-plan transitions). The `version` is an integer that begins at 1 on creation and increments by one on every mutation of the resource; it underpins optimistic concurrency control as described in §2.7.

One entity is deliberately leaner: a `WaterTest` is an immutable reading and carries only `id` and `created_at`. It has no `updated_at` and no `version`, because a logged measurement is never modified after the fact. Whenever a derived field is recomputed on a resource — for instance, a contract's `account_balance_cents` after an invoice changes, or a system's `bioload_index` after livestock change — that recomputation counts as a mutation of the host resource: its `updated_at` is refreshed and its `version` increments.

### 2.5. Hierarchical Consistency and Cascades

The entity graph is hierarchical, and several state changes propagate across it. A `ServiceContract` owns one or more `SystemProfile` records; each system owns its `Livestock` and `Equipment`. When a contract is suspended, every `SystemProfile` under it that is currently `ACTIVE` is cascaded to `SUSPENDED`; when that contract is later reactivated, every system under it that is `SUSPENDED` is cascaded back to `ACTIVE`. When a contract is terminated, every system under it that is not already `DECOMMISSIONED` is cascaded to `DECOMMISSIONED`, and as each system decommissions, every `Livestock` under it whose `status` is `ALIVE` cascades to `DECEASED`. Each entity touched by a cascade is independently mutated — its `updated_at` is refreshed and its `version` increments — and any derived field affected (such as the contract's `alive_livestock_count`) is recomputed as part of the same operation.

### 2.6. Nested Resource Retrieval and Existence Ordering

Many endpoints address a resource through a nested path, such as fetching the livestock under a system or the water tests under a visit. For any request whose path or body references other resources, the system validates existence left-to-right, in path order first and then body order, rejecting on the first identifier that does not resolve to an existing record with `ERR_NOT_FOUND`. A request for the water tests of a visit that does not exist fails on the visit before the system looks at anything downstream. This existence check (priority 4) runs after authentication (priority 1), role authorization (priority 2), and any applicable ownership check (priority 3), but before state, business, and concurrency checks.

### 2.7. Optimistic Concurrency Control

Two create operations guard against acting on a stale view of a `SystemProfile`, because the system's `version` advances whenever a visit is booked against it or a quarantine occupies it.

Booking a service visit is one such guarded write. A request to book a visit must carry `expected_system_version`, the client's last observed `version` of the target `SystemProfile` named by `system_id`. If that value does not equal the system's current `version` — because another writer advanced it since the client last read it (for example, an install start moved the system out of an eligible posture, or another booking changed its state) — the create is rejected with `ERR_STALE_VERSION` and HTTP status 412, so the booking is re-derived from current system state. On a successful booking, the target `SystemProfile.version` increments by one.

Opening a quarantine is the other guarded write. A request to open a quarantine must carry `expected_tank_version`, the client's last observed `version` of the quarantine-tank `SystemProfile` named by `quarantine_tank_id`. If that value does not equal the tank's current `version` — because another writer already opened an occupancy on the same tank since the client last read it — the create is rejected with `ERR_STALE_VERSION` and HTTP status 412. On a successful open, the tank's `SystemProfile.version` increments by one. No other endpoint accepts a version field; endpoints not named here perform no concurrency check.

### 2.8. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Where a calculation multiplies an amount by a rate — a plan discount, an emergency surcharge, or an install deposit — the product is rounded to a whole number of cents using the round-half-up method (a value exactly at the half-cent rounds up) before it is added to or subtracted from the running total. Counts such as `alive_livestock_count` and balances such as `account_balance_cents` are likewise whole integers.

### 2.9. Stocking Density and the Bioload Principle

Each `SystemProfile` continuously reflects how heavily it is stocked through a derived `bioload_index` carried to two decimal places and a derived `stocking_posture`. The effective water volume of a system is its `nominal_volume_l` multiplied by one minus its `substrate_displacement_pct` — the fraction of volume taken up by rock and substrate. The bioload is the sum, over every `Livestock` on the system whose `status` is `ALIVE`, of that animal's `adult_length_cm` multiplied by the waste factor for its `species_class`; animals that are `QUARANTINED` or `DECEASED` are excluded entirely. That sum is divided by the effective volume, multiplied by 100, and rounded half-up to two decimal places to yield `bioload_index`. The waste factor is 1.0 for `COMMUNITY`, 1.5 for `CICHLID`, 2.0 for `GOLDFISH`, 2.5 for `PREDATOR`, and 0.5 for `INVERT`. The `stocking_posture` is `OVERSTOCKED` when `bioload_index` is strictly greater than 100.0 and `NORMAL` otherwise; a value of exactly 100.0 is `NORMAL`. This index and posture are recomputed whenever livestock are added, change status, when a system's volume is updated, or when a quarantine is cleared or aborted.

### 2.10. The Contract Ledger

Each `ServiceContract` carries a derived `account_balance_cents` that is the single source of truth for what the account currently owes. It is the sum, over every `Invoice` whose `contract_id` is this contract and whose `status` is either `ISSUED` or `OVERDUE`, of that invoice's `total_cents` minus its `amount_paid_cents`; invoices in `PAID` or `VOID` status contribute nothing. This balance is recomputed on every invoice mutation — creation, voiding, or payment — so that suspending, reactivating, and terminating decisions always read a current figure. In parallel, each contract carries `alive_livestock_count`, the count of `Livestock` across all of the contract's systems whose `status` is `ALIVE`, recomputed whenever livestock are created, change status, are swept by a system decommission, or are affected by a quarantine clear or abort.

## 3. Business Logic & Workflows

### 3.1. Contracts, Systems, and the Account Hierarchy

Everything begins with a `ServiceContract`, the billing root for an account. An `AccountManager` opens a contract by supplying the account holder's `customer_name`, the `customer_user_id` that anchors which `CustomerOwner` owns it, a `service_tier` of `BASIC`, `PLUS`, or `PREMIUM`, and a `route_day` — the weekday the recurring route visits this account, one of `MON`, `TUE`, `WED`, `THU`, `FRI`, or `SAT`. A new contract starts in `DRAFT` with a `status` lifecycle of `DRAFT`, `ACTIVE`, `SUSPENDED`, and the terminal `TERMINATED`. Its `account_balance_cents` and `alive_livestock_count` both start at zero.

Under a contract sits one or more `SystemProfile` records, the physical tanks and ponds. An `AccountManager` registers a system by supplying its `contract_id`, a human `label`, a `system_kind` of `REEF`, `FRESHWATER`, `POND`, or `PALUDARIUM`, a `nominal_volume_l` greater than zero, and an optional `substrate_displacement_pct` that is at least zero and strictly less than one, defaulting to 0.0. A system enters in `PROVISIONING` and moves through `ACTIVE`, `SUSPENDED`, and the terminal `DECOMMISSIONED`.

A contract is brought live by an `AccountManager` activating it. Activating a `DRAFT` contract requires that it already have at least one `SystemProfile`; an attempt to activate a contract that has no system is rejected with `ERR_NO_SYSTEM_ON_CONTRACT`, and on success the contract moves `DRAFT → ACTIVE`. The same activation action reactivates a `SUSPENDED` contract, but only when the account is paid up: reactivation requires `account_balance_cents` to be exactly zero, and a non-zero balance is rejected with `ERR_BALANCE_OUTSTANDING`. On reactivation the contract moves `SUSPENDED → ACTIVE` and cascades its `SUSPENDED` systems back to `ACTIVE` as described in §2.5.

Suspending a contract is the non-payment lever. An `AccountManager` may move an `ACTIVE` contract `ACTIVE → SUSPENDED` only when `account_balance_cents` is greater than zero; an attempt to suspend a contract whose balance is zero (or otherwise not greater than zero) is rejected with `ERR_INVALID_STATE`. Suspension cascades its `ACTIVE` systems to `SUSPENDED`. Terminating a contract is available from either `ACTIVE` or `SUSPENDED` and is performed by an `AccountManager`; it is blocked when any `ServiceVisit` on this contract's systems is `SCHEDULED` or `IN_PROGRESS`, in which case the request is rejected with `ERR_VISIT_IN_FLIGHT`. On termination the contract moves to `TERMINATED` and cascades its non-decommissioned systems to `DECOMMISSIONED`, which in turn sweeps each system's `ALIVE` livestock to `DECEASED`.

A `PROVISIONING` system is commissioned to `ACTIVE` by an `AccountManager`. Commissioning requires the owning `ServiceContract` to be `ACTIVE`; otherwise the request is rejected with `ERR_CONTRACT_NOT_ACTIVE`. It is additionally blocked if any `InstallProject` for this system is still open — that is, in `QUOTED`, `APPROVED`, or `IN_BUILD` — in which case the request is rejected with `ERR_OPEN_INSTALL_BLOCKS_COMMISSION`; any install for the system must be `HANDED_OFF` or `CANCELLED` first. A system may also be decommissioned directly by an `AccountManager` from `ACTIVE` or `SUSPENDED`; a direct decommission is blocked when any `ServiceVisit` on the system is `SCHEDULED` or `IN_PROGRESS`, rejected with `ERR_VISIT_IN_FLIGHT`. Whenever a system decommissions — by direct request or by the termination cascade — its `ALIVE` livestock cascade to `DECEASED` and the owning contract's `alive_livestock_count` is recomputed.

### 3.2. Livestock and Equipment on a System

A `FieldTech` or an `AccountManager` adds a `Livestock` item to a system by supplying its `system_id`, a `common_name`, a `species_class` of `COMMUNITY`, `CICHLID`, `GOLDFISH`, `PREDATOR`, or `INVERT`, and an `adult_length_cm` greater than zero. New livestock enters with a `status` of `ALIVE`; the lifecycle values are `ALIVE`, `QUARANTINED`, and `DECEASED`. Adding the animal recomputes the home system's `bioload_index` and `stocking_posture` and the contract's `alive_livestock_count`. Adding livestock is gated by the bioload rule: if the resulting `bioload_index` would land strictly above 100.0 — making the system `OVERSTOCKED` — the addition is rejected with `ERR_OVERSTOCKED` and HTTP status 422.

A `FieldTech` or `AccountManager` also registers `Equipment` on a system by supplying its `system_id`, a `device_kind` of `FILTER`, `PUMP`, `HEATER`, `UV_STERILIZER`, or `SKIMMER`, and a `media_interval_days` of at least one. A device's `status` is one of `OPERATIONAL`, `DEGRADED`, or `OUT_OF_SERVICE`, beginning at `OPERATIONAL`. Each device tracks `last_serviced_on`, the date of its most recent media replacement, which is null until the device is first serviced, and a derived `media_due_on`, the next date media is due. The due date is computed by taking the base date — `last_serviced_on` when it is set, otherwise the date component of the owning `SystemProfile`'s creation date — and adding `media_interval_days` whole days to it. At registration, because the device has never been serviced, `media_due_on` is computed from the system's creation date plus the interval.

### 3.3. The Recurring Route: Booking, Servicing, and Disputes

Service work flows through the `ServiceVisit`, the unit of on-site labor. A `Dispatcher` books a routine visit by supplying the target `system_id`, the `technician_id` to assign, a `scheduled_start` and `scheduled_end` that define the booked window, and `expected_system_version`. The window is a half-open interval running from `scheduled_start` inclusive to `scheduled_end` exclusive. A `visit_kind` may be supplied and defaults to `ROUTINE`; the other value, `EMERGENCY`, is conceptually reserved for visits created from an emergency dispatch. This endpoint does not categorically forbid an `EMERGENCY` `visit_kind`; the only guard it enforces on this point is the kind-consistency rule below, so a request that supplies `visit_kind` `EMERGENCY` together with a resolvable `emergency_call_id` is accepted here. An `emergency_call_id` may accompany the request only for an emergency visit. The kind-consistency rule is strict: an `EMERGENCY` visit requires `emergency_call_id` to be present and a `ROUTINE` visit must omit it; a violation is rejected with `ERR_VISIT_KIND_MISMATCH`. A visit's `status` runs `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, `DISPUTED`, and `CANCELLED`, with `COMPLETED` and `CANCELLED` terminal. A booked visit holds `labor_minutes` (an integer at least zero, defaulting to 0, recorded at completion), a computed `total_cents`, and an `invoice_id` back-reference that is null until completion.

Two temporal guards apply at booking. First, the proposed window must be well-ordered: `scheduled_start` must be strictly before `scheduled_end`, and a window that is not is rejected with `ERR_BAD_WINDOW`. Second, the technician must be free: the half-open window must not overlap any other non-terminal visit — one that is `SCHEDULED` or `IN_PROGRESS` — already held by the same technician. Because the intervals are half-open, two visits that merely touch at an endpoint (one ending exactly when the next begins) do not conflict; a genuine overlap is rejected with `ERR_TECH_DOUBLE_BOOKED`. The same double-booking guard applies when an emergency dispatch creates a visit for a technician. On a successful booking the target system's `version` increments by one, as covered in §2.7.

A `FieldTech` starts a `SCHEDULED` visit, moving it `SCHEDULED → IN_PROGRESS`. After the visit's own `SCHEDULED` state is confirmed, the acting tech must be the assigned tech — the acting `FieldTech`'s resolved `Technician.id` must equal the visit's `technician_id`, otherwise the start is rejected with `ERR_TECH_MISMATCH` — and only then is the target `SystemProfile` required to be `ACTIVE`, with a system in any other state rejected with `ERR_INVALID_STATE`. (This tech-identity check thus precedes the system-active check on this endpoint.) When the target system's `system_kind` is `REEF`, the assigned `Technician` must have `certified_for_reef` set to true; an uncertified tech is rejected with `ERR_TECH_NOT_CERTIFIED`.

Completing a visit is where billing happens. A `FieldTech` completes an `IN_PROGRESS` visit by supplying the final `labor_minutes` (which must be present and at least zero), an optional set of `consumable_lines` used to price parts and chemicals, and an optional list of `serviced_equipment_ids` naming the devices whose media was replaced during the visit. Completion moves the visit `IN_PROGRESS → COMPLETED` and triggers several effects together. The visit's `total_cents` is computed (see §3.4). An `Invoice` is created for the billed amount with `status` `ISSUED`, its `source_kind` being `VISIT` for a routine visit and `EMERGENCY_TRIP` for an emergency visit, and the visit's `invoice_id` is set to point at it; creating that invoice recomputes the contract's `account_balance_cents`. For each device named in `serviced_equipment_ids`, that `Equipment`'s `last_serviced_on` is set to the visit's completion date — taken as the current logical-clock instant of §3.11 at the moment of completion, stored as a full ISO 8601 UTC timestamp — and its `media_due_on` is recomputed from the new base date (the date component of that completion timestamp plus the interval). Any identifier in `serviced_equipment_ids` that does not resolve to an existing `Equipment` record fails the request with `ERR_NOT_FOUND`, and `serviced_equipment_ids` may be omitted entirely (treated as an empty list). Finally, if the visit's `visit_kind` is `EMERGENCY`, the linked `EmergencyCall` is moved to `RESOLVED`.

After a visit completes, the `CustomerOwner` who owns the account may dispute it, provided the dispute is filed before payment lands: a visit moves `COMPLETED → DISPUTED` only when its `Invoice.status` is not `PAID`; a dispute against a visit whose invoice is already `PAID` is rejected with `ERR_INVALID_STATE`. The disputing owner must own the contract of the visit's system, enforced as in §2.1, and that ownership check is applied after the visit is found to exist but before the visit's `COMPLETED` state and the invoice-paid gate are evaluated. Disputing voids the visit's invoice — the `Invoice.status` becomes `VOID` and the contract's `account_balance_cents` is recomputed to drop that invoice's contribution. A disputed visit is reworked by a `FieldTech`, who must again be the assigned tech (the same `ERR_TECH_MISMATCH` guard applies), moving it `DISPUTED → IN_PROGRESS`; rework clears the visit's `invoice_id` and resets `total_cents` to zero, so that the next completion issues a fresh invoice. This rework loop may repeat. A `Dispatcher` may cancel a `SCHEDULED` visit, moving it `SCHEDULED → CANCELLED`; if the cancelled visit was an `EMERGENCY` visit whose linked `EmergencyCall` is in `DISPATCHED`, the call is compensated back to `OPEN` and its `dispatched_visit_id` is cleared.

### 3.4. Pricing a Visit

The amount billed at visit completion depends on the owning contract's tier and the labor recorded. Resolve the `service_tier` from the contract that owns the visit's system. The base charge is the tier's base: 6000 cents for `BASIC`, 9000 cents for `PLUS`, and 13000 cents for `PREMIUM`. Each tier includes a block of labor at no extra charge: 30 minutes for `BASIC`, 45 minutes for `PLUS`, and 60 minutes for `PREMIUM`. The overage is the recorded `labor_minutes` minus the tier's included minutes, floored at zero so a visit under the allowance has no overage. That overage is then divided into 15-minute blocks, rounding up so that any partial block bills as a whole block, and each block costs 2000 cents — this is the labor overage charge.

The consumable line total is the sum, over each entry in `consumable_lines`, of that line's `qty` multiplied by its `unit_price_cents`. Add the base, the labor overage, and the consumable total to get the subtotal. The plan discount is the subtotal multiplied by the tier's discount rate — 0% for `BASIC`, 10% for `PLUS`, and 15% for `PREMIUM` — rounded half-up to whole cents, and is subtracted from the subtotal to give the after-discount amount. For a `ROUTINE` visit there is no further charge and `total_cents` equals the after-discount amount. For an `EMERGENCY` visit an emergency surcharge of 25% of the after-discount amount, rounded half-up to whole cents, is added on top; for identical labor and lines this makes an emergency visit's total strictly higher than the routine equivalent. The resulting `total_cents` is stored on the visit and copied to the invoice.

### 3.5. Water Tests and Dosing

During an `IN_PROGRESS` visit, a `FieldTech` logs a `WaterTest` for the system. Each test names the measured `parameter` — one of `ALKALINITY`, `NITRATE`, `PHOSPHATE`, `PH`, or `AMMONIA` — together with the `measured_value` and the `target_value` for that parameter on this system (both at least zero), and the dosing product's `product_strength_ppm_per_ml`, the parts-per-million a single millilitre raises in one litre, which must be greater than zero. The test belongs to the visit through its `visit_id`, which must reference a visit that is currently `IN_PROGRESS`; logging a water test against a visit in any other state is rejected with `ERR_INVALID_STATE`. From these the system derives a `recommended_dose_ml`. When the `measured_value` is at or above the `target_value`, the recommended dose is exactly 0.0 — a reading exactly at target doses nothing, not a sliver. Otherwise the raw dose is the difference between target and measured, multiplied by the system's effective volume (its `nominal_volume_l` times one minus its `substrate_displacement_pct`), divided by `product_strength_ppm_per_ml`; this raw millilitre figure is then rounded up to the next 0.1 mL so the system never under-doses. A `WaterTest`, as noted in §2.4, is immutable; among the standard system-managed fields it carries only `id` and `created_at` (it has no `updated_at` and no `version`), while its serialized representation still returns its own data fields — `visit_id`, `parameter`, `measured_value`, `target_value`, `product_strength_ppm_per_ml`, and the derived `recommended_dose_ml`.

### 3.6. Livestock Health: Quarantine

When an animal needs isolation, a `FieldTech` opens a `QuarantineRecord` by supplying the `livestock_id` of the animal, the `quarantine_tank_id` of the tank that will hold it, a `window_start` and `window_end` defining the occupancy, and `expected_tank_version`. The quarantine tank must be a `SystemProfile` whose `system_kind` is `FRESHWATER`; a tank of any other kind is rejected with `ERR_INVALID_QT_TANK`. The occupancy window is a closed interval inclusive of both `window_start` and `window_end`. The window must be well-ordered with `window_start` at or before `window_end`, and a window that is not is rejected with `ERR_BAD_WINDOW`. Because the tank is a physical resource, two `ACTIVE` quarantines on the same `quarantine_tank_id` may not overlap, and since the intervals are closed, sharing a single endpoint — one window ending exactly when another begins — counts as a conflict; a collision is rejected with `ERR_QT_TANK_OCCUPIED`. The stale-tank concurrency check of §2.7 also applies, and on a successful open the tank's `version` increments. A record's `status` runs `ACTIVE`, `CLEARED`, and `ABORTED`. Opening a quarantine moves the linked `Livestock` to `QUARANTINED`, which recomputes the home system's bioload and the contract's `alive_livestock_count`.

A `FieldTech` clears an `ACTIVE` quarantine, moving it `ACTIVE → CLEARED`, only when the linked `Livestock.status` is `QUARANTINED`; if the quarantine is `ACTIVE` but the linked livestock is not `QUARANTINED`, the clear is rejected with `ERR_INVALID_STATE`. Clearing returns the animal to `ALIVE` and bubbles the change up: the home `SystemProfile`'s `bioload_index` and `stocking_posture` are recomputed and the contract's `alive_livestock_count` is recomputed. Because returning the animal raises bioload, the clear is gated by the overstock rule exactly as a livestock addition is: if returning the animal would push the home system's `bioload_index` strictly above 100.0, the clear is rejected with `ERR_OVERSTOCKED`. A `FieldTech` may instead abort a quarantine, moving it `ACTIVE → ABORTED`, which sets the linked `Livestock` to `DECEASED`; the contract's `alive_livestock_count` is unchanged here, because a `QUARANTINED` animal was already excluded from the count.

### 3.7. Equipment Repair

When a device faults, a `FieldTech` or `AccountManager` opens a `RepairOrder` against it by supplying the `equipment_id`, a non-empty `reported_symptom`, and an optional `parts_needed` flag that defaults to false. A repair's `status` runs `REPORTED`, `DIAGNOSED`, `AWAITING_PARTS`, and the terminal `CLOSED` and `SCRAPPED`. A `FieldTech` diagnoses a `REPORTED` order, moving it `REPORTED → DIAGNOSED` and setting the target `Equipment.status` to `DEGRADED`. From `DIAGNOSED`, if `parts_needed` is true on the repair, the tech may order parts, moving it `DIAGNOSED → AWAITING_PARTS`; attempting to order parts when `parts_needed` is false is not a defined transition and is rejected with `ERR_INVALID_STATE`. When parts arrive, the tech moves it `AWAITING_PARTS → DIAGNOSED`, which forms the parts-backorder cycle and may loop if re-diagnosis turns up further parts. A `FieldTech` closes a `DIAGNOSED` order, moving it `DIAGNOSED → CLOSED` and setting the `Equipment.status` back to `OPERATIONAL`, but only when the `Equipment.status` is not `OUT_OF_SERVICE`; a close attempt while the target `Equipment.status` is `OUT_OF_SERVICE` is rejected with `ERR_INVALID_STATE`. Alternatively the tech scraps a `DIAGNOSED` order, moving it `DIAGNOSED → SCRAPPED` and setting the `Equipment.status` to `OUT_OF_SERVICE`.

### 3.8. Install Projects: Quote to Handoff

New builds run as an `InstallProject`. An `AccountManager` creates a quote by supplying the `contract_id`, the `system_id` of the system being built (which must be `PROVISIONING`; a quote against a system in any other state is rejected with `ERR_SYSTEM_NOT_PROVISIONING`), a `labor_estimate_cents`, and an `equipment_estimate_cents` (each an integer at least zero). The project's `status` runs `QUOTED`, `APPROVED`, `IN_BUILD`, and the terminal `HANDED_OFF` and `CANCELLED`. It also carries `actual_labor_minutes`, `actual_equipment_cents`, and `change_order_cents` (each an integer at least zero, defaulting to 0) used at handoff, plus the computed `quote_total_cents`, `deposit_cents`, and `final_total_cents`.

The owning `CustomerOwner` approves a `QUOTED` project, moving it `QUOTED → APPROVED`. Approval requires the acting owner to own `contract_id` and requires the owning `ServiceContract` to be `ACTIVE`, otherwise `ERR_CONTRACT_NOT_ACTIVE`. At approval the provisional figures are computed: `quote_total_cents` is `labor_estimate_cents` plus `equipment_estimate_cents`, and `deposit_cents` is that quote total multiplied by the deposit rate of 30%, rounded half-up to whole cents. A deposit `Invoice` is then created with `source_kind` `INSTALL` and `total_cents` equal to `deposit_cents`, in `status` `ISSUED`, which recomputes the contract's `account_balance_cents`.

A `FieldTech` begins the build on an `APPROVED` project, moving it `APPROVED → IN_BUILD`, but only when the target `SystemProfile.status` is `PROVISIONING`; otherwise the request is rejected with `ERR_SYSTEM_NOT_PROVISIONING`. An `AccountManager` hands off an `IN_BUILD` project, moving it `IN_BUILD → HANDED_OFF`, after supplying the `actual_labor_minutes` and `actual_equipment_cents` (both required at handoff) and an optional `change_order_cents`. At handoff the final figure is computed from actuals: the actual labor minutes are divided into 15-minute blocks rounded up, each block costing 2000 cents, and `final_total_cents` is that actual labor charge plus `actual_equipment_cents` plus `change_order_cents`. A balance `Invoice` is created with `source_kind` `INSTALL` and `total_cents` equal to `final_total_cents` minus the previously collected `deposit_cents`, in `status` `ISSUED`, recomputing the contract's balance. The same project thus bills twice under two different algorithms — a provisional deposit from estimates, then a final balance from actuals plus change orders.

An `AccountManager` may cancel a project that is `QUOTED` or `APPROVED`, moving it to `CANCELLED`. When the cancelled project was `APPROVED` and therefore had a deposit invoice, that deposit `Invoice` is voided — its `status` becomes `VOID` — and the contract's `account_balance_cents` is recomputed to remove the deposit's contribution.

### 3.9. Emergency Calls

When a system is in distress, a `Dispatcher` or `AccountManager` opens an `EmergencyCall` by supplying the `system_id`, a `severity` of `LOW`, `HIGH`, or `CRITICAL`, the `reported_at` time, and a flat `trip_fee_cents` (an integer at least zero). The `trip_fee_cents` is recorded on the call and returned in its representation, but it is a stored attribute only: it is never added to any invoice. The amount billed when the dispatched emergency visit completes is governed entirely by the visit-pricing rule of §3.4 (the tier base, labor overage, and consumables, discounted, plus the 25% emergency surcharge) and does not include `trip_fee_cents`. A call's `status` runs `OPEN`, `DISPATCHED`, and the terminal `RESOLVED` and `CANCELLED`; it also carries a `dispatched_visit_id` back-reference that is null until dispatch. A `Dispatcher` dispatches an `OPEN` call by supplying the `technician_id` to send and the `scheduled_start` and `scheduled_end` of the emergency window. Dispatch requires the target `SystemProfile` to be `ACTIVE` and requires the assigned `Technician.active` to be true; a target system that is not `ACTIVE` and an assigned technician whose `active` is false are each rejected with `ERR_INVALID_STATE`. When the system's `system_kind` is `REEF` it additionally requires the assigned `Technician.certified_for_reef` to be true, with an uncertified tech rejected by `ERR_TECH_NOT_CERTIFIED`. These checks are evaluated in order after the call's own state is confirmed `OPEN`: technician existence, then call state, then system-active and technician-active, then reef certification, then the double-booking window guard below. The dispatched technician is also subject to the same double-booking window guard as a routine booking, rejected with `ERR_TECH_DOUBLE_BOOKED` on overlap. Dispatch creates an `EMERGENCY` `ServiceVisit` (its `visit_kind` `EMERGENCY` and `emergency_call_id` set to this call) in `SCHEDULED`, sets the call's `dispatched_visit_id`, and moves the call `OPEN → DISPATCHED`. When the dispatched emergency visit later completes, the call moves `DISPATCHED → RESOLVED`. A `Dispatcher` may cancel an `OPEN` call, moving it `OPEN → CANCELLED`.

### 3.10. Invoices and Payments

An `Invoice` is always raised by a workflow event rather than created directly: a completed visit, an approved or handed-off install, each produces one. Every invoice records the `contract_id` of the billed account, a `source_kind` of `VISIT`, `INSTALL`, or `EMERGENCY_TRIP`, the `source_id` of the originating record resolved by that kind, the `total_cents` face amount copied from the source's computed total at issuance, a `due_on` date that is set to `null` at issuance (no due date is assigned by any workflow event that raises an invoice), an `amount_paid_cents` that starts at zero and never exceeds `total_cents`, and a `status` of `ISSUED`, `OVERDUE`, `PAID`, or `VOID`. An `AccountManager` applies a payment by supplying an `amount_cents`. A payment is only accepted on an invoice that is `ISSUED` or `OVERDUE`; a payment on a `PAID` or `VOID` invoice is rejected with `ERR_INVOICE_NOT_PAYABLE`. The payment `amount_cents` must be strictly greater than zero and must not drive `amount_paid_cents` above `total_cents`; a non-positive payment or one that would overpay is rejected with `ERR_OVERPAYMENT`. A valid payment advances `amount_paid_cents`, and when the invoice becomes fully paid its `status` moves to `PAID`; each payment recomputes the contract's `account_balance_cents`.

An `AccountManager` may flag an `ISSUED` invoice as `OVERDUE` once it is past its `due_on` relative to the logical clock — "past" meaning the logical clock of §3.11 is strictly greater than the invoice's `due_on`; this moves the invoice to `OVERDUE` but does not change the balance, since both `ISSUED` and `OVERDUE` invoices count toward `account_balance_cents`. An attempt to flag an invoice that is not past its due date — including the case where `due_on` is `null`, which is the state of every invoice at issuance — is rejected with `ERR_INVALID_STATE`, as is an attempt to flag an invoice that is not in `ISSUED` status.

### 3.11. Vacation Feeding and the Logical Clock

While an owner is away, a `CustomerOwner` or `AccountManager` schedules a `VacationFeedingPlan` on a system by supplying the `system_id`, a `window_start` and `window_end`, and `feedings_per_day` (an integer at least 1 and at most 6). The window here is half-open — `window_start` inclusive to `window_end` exclusive — and must be well-ordered with `window_start` strictly before `window_end`, otherwise `ERR_BAD_WINDOW`. A plan's `status` runs `SCHEDULED`, `ACTIVE`, `COMPLETED`, and `CANCELLED`. Plan activation and completion are driven by the server's logical clock rather than by a direct request. When the clock reaches a plan's `window_start` and the plan's home `SystemProfile` is `ACTIVE`, the plan moves `SCHEDULED → ACTIVE`; when the clock reaches the plan's `window_end`, an `ACTIVE` plan moves `ACTIVE → COMPLETED`. A `CustomerOwner` who owns the plan's contract may cancel a `SCHEDULED` plan, moving it `SCHEDULED → CANCELLED`.

The logical clock itself is an internal test-driving capability available to an `AccountManager` or `Dispatcher`, which advances the server's logical time to a supplied `to_iso8601` instant. The clock starts at 2026-01-01T00:00:00Z at server startup and reads exactly that default until first set, never falling back to wall-clock time. It governs overdue flagging, emergency `reported_at` semantics, and feeding-plan transitions; an emergency's `reported_at` is stored verbatim as the supplied instant and is not validated against or rewritten by the clock. Advancing the clock auto-evaluates every feeding plan: a `SCHEDULED` plan whose home `SystemProfile` is `ACTIVE` activates as soon as the logical clock is at or after its `window_start` (the boundary is inclusive), and an `ACTIVE` plan completes as soon as the logical clock is at or after its `window_end` (also inclusive), so that a single clock advance that reaches both boundaries moves a plan straight through `SCHEDULED → ACTIVE → COMPLETED` within the same evaluation pass.

### 3.12. Technicians and Validation Ordering

A `Dispatcher` maintains the technician roster, adding a `Technician` by supplying a `tech_user_id` (non-empty and unique across technicians; a `tech_user_id` that duplicates an existing technician's is rejected with `ERR_INVALID_REQUEST`), a `full_name`, an optional `certified_for_reef` flag defaulting to false, and an optional `active` flag defaulting to true. The `tech_user_id` is the identity anchor that ties a `FieldTech` login to the technician record, as described in §2.1.

Across every endpoint, validation checks are applied in a fixed priority order so that the most fundamental failure surfaces first. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization against the RBAC matrix (`ERR_FORBIDDEN_ROLE`), then the ownership check for `CustomerOwner` actions (`ERR_NOT_RESOURCE_OWNER`), then existence of all referenced resources validated left-to-right (`ERR_NOT_FOUND`), then whether the target entity is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). After those come the business checks: the tech-identity match on visit start and rework (`ERR_TECH_MISMATCH`), the reef-certification gate on visit start and emergency dispatch (`ERR_TECH_NOT_CERTIFIED`), the overstock gate on adding livestock and clearing a quarantine (`ERR_OVERSTOCKED`), the technician double-booking guard on booking a visit and dispatching an emergency (`ERR_TECH_DOUBLE_BOOKED`), the quarantine-tank occupancy guard on opening a quarantine (`ERR_QT_TANK_OCCUPIED`), the freshwater-tank constraint on opening a quarantine (`ERR_INVALID_QT_TANK`), the visit-kind consistency check on booking a visit (`ERR_VISIT_KIND_MISMATCH`), the window-ordering check on visits, quarantines, and feeding plans (`ERR_BAD_WINDOW`), the payment guard (`ERR_OVERPAYMENT`), the optimistic-concurrency check on booking visits and opening quarantines (`ERR_STALE_VERSION`), and finally generic request validation of required fields, enum domains, and numeric ranges (`ERR_INVALID_REQUEST`). The state check (`ERR_INVALID_STATE`) applies to every transition endpoint; existence, authentication, role, and generic request validation apply across all endpoints. The ordering above places `ERR_INVALID_REQUEST` last only relative to the named business guards (`ERR_TECH_MISMATCH` through `ERR_STALE_VERSION`); in the concrete implementation the structural validation of the request body — presence of required fields, correct JSON types, enum-domain membership, and numeric-range bounds — is performed immediately after authentication and role authorization and therefore before the existence of resources named in that same body is checked. The practical consequence is that on a collection-creating `POST` (for example creating a system, livestock, equipment, visit, install, emergency, repair, quarantine, or feeding plan) a body that is malformed surfaces `ERR_INVALID_REQUEST` even when an identifier carried in the body also fails to resolve, whereas on an action endpoint addressed by a path identifier the path resource's existence (`ERR_NOT_FOUND`) and then its state (`ERR_INVALID_STATE`) are evaluated before that endpoint's own request-body fields are validated.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action and every payment — return a `200 OK` status code. All paths below are mounted under the `/aquatics` prefix except the internal logical-clock endpoint.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/aquatics/contracts` | Create a service contract (DRAFT) | AccountManager |
| GET | `/aquatics/contracts` | List contracts (paginated) | AccountManager, Dispatcher |
| GET | `/aquatics/contracts/{id}` | Fetch a contract incl. derived balance and alive count | AccountManager, Dispatcher, CustomerOwner |
| POST | `/aquatics/contracts/{id}/activate` | Activate a DRAFT or reactivate a SUSPENDED contract | AccountManager |
| POST | `/aquatics/contracts/{id}/suspend` | Suspend an ACTIVE contract for non-payment | AccountManager |
| POST | `/aquatics/contracts/{id}/terminate` | Terminate a contract; decommission its systems | AccountManager |
| POST | `/aquatics/systems` | Create a system profile (PROVISIONING) under a contract | AccountManager |
| GET | `/aquatics/systems/{id}` | Fetch a system incl. derived bioload and posture | AccountManager, Dispatcher, FieldTech, CustomerOwner |
| GET | `/aquatics/contracts/{id}/systems` | List systems under a contract | AccountManager, Dispatcher, CustomerOwner |
| POST | `/aquatics/systems/{id}/commission` | Move a PROVISIONING system to ACTIVE | AccountManager |
| POST | `/aquatics/systems/{id}/decommission` | Decommission a system; cascade live livestock to DECEASED | AccountManager |
| POST | `/aquatics/livestock` | Add a livestock item to a system; recompute bioload | FieldTech, AccountManager |
| GET | `/aquatics/systems/{id}/livestock` | List livestock under a system | AccountManager, Dispatcher, FieldTech, CustomerOwner |
| GET | `/aquatics/livestock/{id}` | Fetch a single livestock item | AccountManager, Dispatcher, FieldTech, CustomerOwner |
| POST | `/aquatics/equipment` | Register a device on a system; compute first media due date | FieldTech, AccountManager |
| GET | `/aquatics/systems/{id}/equipment` | List equipment under a system | AccountManager, Dispatcher, FieldTech, CustomerOwner |
| GET | `/aquatics/equipment/{id}` | Fetch a single device incl. media due date | AccountManager, Dispatcher, FieldTech, CustomerOwner |
| POST | `/aquatics/technicians` | Add a technician to the roster | Dispatcher |
| GET | `/aquatics/technicians/{id}` | Fetch a technician | Dispatcher, AccountManager, FieldTech |
| POST | `/aquatics/visits` | Book a ROUTINE service visit (OCC on the system version) | Dispatcher |
| GET | `/aquatics/visits/{id}` | Fetch a visit incl. total and invoice link | AccountManager, Dispatcher, FieldTech, CustomerOwner |
| GET | `/aquatics/visits` | List visits; filter by system, technician, or emergency call | AccountManager, Dispatcher, FieldTech |
| POST | `/aquatics/visits/{id}/start` | Start a SCHEDULED visit | FieldTech |
| POST | `/aquatics/visits/{id}/complete` | Complete an IN_PROGRESS visit; bill it and issue an invoice | FieldTech |
| POST | `/aquatics/visits/{id}/dispute` | Owner disputes a COMPLETED visit; voids its invoice | CustomerOwner |
| POST | `/aquatics/visits/{id}/rework` | Tech reopens a DISPUTED visit for rework | FieldTech |
| POST | `/aquatics/visits/{id}/cancel` | Cancel a SCHEDULED visit | Dispatcher |
| POST | `/aquatics/visits/{id}/water-tests` | Log a water test on an IN_PROGRESS visit; compute dose | FieldTech |
| GET | `/aquatics/visits/{id}/water-tests` | List water tests for a visit | AccountManager, Dispatcher, FieldTech, CustomerOwner |
| GET | `/aquatics/invoices/{id}` | Fetch an invoice | AccountManager, CustomerOwner |
| GET | `/aquatics/contracts/{id}/invoices` | List invoices for a contract | AccountManager, CustomerOwner |
| POST | `/aquatics/invoices/{id}/payments` | Apply a payment to an ISSUED/OVERDUE invoice | AccountManager |
| POST | `/aquatics/invoices/{id}/flag-overdue` | Flag an ISSUED invoice past its due date as OVERDUE | AccountManager |
| POST | `/aquatics/installs` | Create an install project quote (QUOTED) | AccountManager |
| GET | `/aquatics/installs/{id}` | Fetch an install project incl. quote/deposit/final totals | AccountManager, FieldTech, CustomerOwner |
| GET | `/aquatics/contracts/{id}/installs` | List install projects for a contract | AccountManager, CustomerOwner |
| GET | `/aquatics/systems/{id}/installs` | List install projects for a system | AccountManager, FieldTech, CustomerOwner |
| POST | `/aquatics/installs/{id}/approve` | Owner approves a QUOTED project; issues deposit invoice | CustomerOwner |
| POST | `/aquatics/installs/{id}/start-build` | Begin the build on an APPROVED project | FieldTech |
| POST | `/aquatics/installs/{id}/handoff` | Hand off an IN_BUILD project; bill final; issue balance invoice | AccountManager |
| POST | `/aquatics/installs/{id}/cancel` | Cancel a QUOTED/APPROVED project; void deposit invoice if any | AccountManager |
| POST | `/aquatics/emergencies` | Open an emergency call (OPEN) | Dispatcher, AccountManager |
| GET | `/aquatics/emergencies/{id}` | Fetch an emergency call | Dispatcher, AccountManager, FieldTech |
| GET | `/aquatics/systems/{id}/emergencies` | List emergency calls for a system | Dispatcher, AccountManager, FieldTech |
| POST | `/aquatics/emergencies/{id}/dispatch` | Dispatch a tech; auto-creates an EMERGENCY visit | Dispatcher |
| POST | `/aquatics/emergencies/{id}/cancel` | Cancel an OPEN emergency call | Dispatcher |
| POST | `/aquatics/quarantines` | Open a quarantine in a FRESHWATER QT tank (OCC on tank version) | FieldTech |
| GET | `/aquatics/quarantines/{id}` | Fetch a quarantine record | FieldTech, AccountManager, Dispatcher |
| GET | `/aquatics/livestock/{id}/quarantines` | List quarantine records for a livestock item | FieldTech, AccountManager, Dispatcher |
| GET | `/aquatics/systems/{id}/quarantines` | List quarantine records using a system as the QT tank | FieldTech, AccountManager, Dispatcher |
| POST | `/aquatics/quarantines/{id}/clear` | Clear a quarantine; return the animal to ALIVE (overstock-gated) | FieldTech |
| POST | `/aquatics/quarantines/{id}/abort` | Abort a quarantine; animal becomes DECEASED | FieldTech |
| POST | `/aquatics/repairs` | Open a repair order for a device (REPORTED) | FieldTech, AccountManager |
| GET | `/aquatics/repairs/{id}` | Fetch a repair order | FieldTech, AccountManager |
| GET | `/aquatics/equipment/{id}/repairs` | List repair orders for a device | FieldTech, AccountManager |
| POST | `/aquatics/repairs/{id}/diagnose` | Diagnose a REPORTED repair; device to DEGRADED | FieldTech |
| POST | `/aquatics/repairs/{id}/order-parts` | Order parts for a DIAGNOSED repair | FieldTech |
| POST | `/aquatics/repairs/{id}/parts-arrived` | Parts arrived; return to DIAGNOSED | FieldTech |
| POST | `/aquatics/repairs/{id}/close` | Close a DIAGNOSED repair; device to OPERATIONAL | FieldTech |
| POST | `/aquatics/repairs/{id}/scrap` | Scrap a DIAGNOSED repair; device to OUT_OF_SERVICE | FieldTech |
| POST | `/aquatics/feeding-plans` | Schedule a vacation feeding plan on an ACTIVE system | CustomerOwner, AccountManager |
| GET | `/aquatics/feeding-plans/{id}` | Fetch a feeding plan | CustomerOwner, AccountManager, Dispatcher |
| GET | `/aquatics/systems/{id}/feeding-plans` | List feeding plans for a system | CustomerOwner, AccountManager, Dispatcher |
| POST | `/aquatics/feeding-plans/{id}/cancel` | Owner cancels a SCHEDULED feeding plan | CustomerOwner |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test-driving) | AccountManager, Dispatcher |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TECH_MISMATCH` | 403 |
| `ERR_TECH_NOT_CERTIFIED` | 422 |
| `ERR_OVERSTOCKED` | 422 |
| `ERR_TECH_DOUBLE_BOOKED` | 409 |
| `ERR_QT_TANK_OCCUPIED` | 409 |
| `ERR_INVALID_QT_TANK` | 422 |
| `ERR_VISIT_KIND_MISMATCH` | 422 |
| `ERR_BAD_WINDOW` | 422 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CONTRACT_NOT_ACTIVE` | 422 |
| `ERR_SYSTEM_NOT_PROVISIONING` | 422 |
| `ERR_OPEN_INSTALL_BLOCKS_COMMISSION` | 409 |
| `ERR_BALANCE_OUTSTANDING` | 422 |
| `ERR_VISIT_IN_FLIGHT` | 409 |
| `ERR_INVOICE_NOT_PAYABLE` | 409 |
| `ERR_NO_SYSTEM_ON_CONTRACT` | 422 |
| `ERR_INVALID_REQUEST` | 422 |
