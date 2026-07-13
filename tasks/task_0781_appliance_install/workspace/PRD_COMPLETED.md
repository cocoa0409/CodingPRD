# Appliance Install Marketplace API — Product Requirements Document

## 1. Introduction

Big-box electronics and appliance retailers increasingly close the sale of a television, dishwasher, or smart thermostat with a bundled promise: "we'll install it for you." Fulfilling that promise reliably, at a fixed and transparent price, and with a vetted professional who actually shows up on time, is the problem this platform solves. The **Appliance & Electronics Installation Marketplace** is the operational backbone that sits between a referring retailer, the end customer who bought the product, and the independent installation professionals ("pros") who perform the work. A retailer refers an order linked to a specific product SKU and a fixed catalog task (a standard TV wall-mount, an appliance hook-up, a smart-device setup); the platform schedules it, dispatches the best-fit vetted pro, tracks the job through completion, prices it, pays the pro, and settles the referral economics back with the retailer.

The system is built around a small number of interacting lifecycles. Work orders move from a retailer draft through scheduling, dispatch, on-site work, and completion, with a warranty-backed redo loop for jobs that need to be corrected. Pros are vetted through an application that can be approved, suspended, reinstated, or allowed to expire, and are matched to work through a deterministic dispatch selector that weighs rating, current payout load, and seniority. Money flows in two coupled directions at completion: a payout accrues to the pro, and a settlement charge accrues against the referring retailer, both of which can be compensated cleanly if an order is cancelled after it was completed. This document specifies the entities, the state machines that govern them, the pricing and payout calculations, the validation and authorization rules, and the HTTP surface that ties them together.

All monetary amounts in this system are expressed and stored as **integer cents** — there are no floating-point currency fields anywhere in the contract. Time is governed by a logical clock (see §2.7) so that every deadline, warranty window, and expiry rule is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. If both headers are present but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The same `ERR_UNAUTHORIZED` code is returned when a caller is permitted by role but does not own the specific resource being acted upon.

There are exactly four roles, spelled precisely as follows:

- **`PlatformAdmin`** — the platform operations role: catalog management, pro vetting decisions, dispatch, retailer settlement runs, order closing and cancellation, and control of the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; a `PlatformAdmin` acts platform-wide and is never subject to per-resource ownership checks.
- **`Retailer`** — the referring retailer. When `X-User-Role` is `Retailer`, `X-User-ID` is the `id` of the acting `Retailer`; ownership checks on any resource that references a retailer compare that resource's `retailer_id` to `X-User-ID`. A retailer may only create work orders whose `retailer_id` equals its own `X-User-ID`, and may only schedule or cancel work orders it owns.
- **`Pro`** — the installation professional. When `X-User-Role` is `Pro`, `X-User-ID` is the `id` of the acting `Pro`; ownership checks compare the relevant foreign key to `X-User-ID`. For assignment actions the comparison is against the `pro_id` of the `Assignment`; for work-order actions (start, complete, add parts) the comparison is against the work order's `appointment_pro_id`.
- **`Customer`** — the end customer receiving the install. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks compare a resource's `customer_id` to `X-User-ID`. A customer may only request a warranty redo or submit a rating on a work order whose `customer_id` equals its own `X-User-ID`.

Ownership violations for the three entity-backed roles surface as `ERR_UNAUTHORIZED` (HTTP 403), the same code used for role-level denials.

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

### 2.3. Pagination

All list endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum accepted value of 1 and a maximum of 100. `offset` defaults to 0 and has a minimum of 0. Results are ordered by `created_at` ascending (oldest first) unless a specific endpoint states otherwise; rows sharing an identical `created_at` (common under the logical clock) are further ordered by ascending creation sequence, so the effective order is deterministic insertion order. Every list response includes `limit`, `offset`, `total_count` (the total number of matching rows before the page window is applied), and `has_more` (a boolean that is true when rows remain beyond the current page) inside the `meta` object.

### 2.4. Common Resource Properties and Identifiers

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits at the moment of creation. Most resources additionally carry an `updated_at` timestamp (same format) and an integer `version` that starts at 1 on creation and increments by 1 on every mutation to that resource. The `Rating` resource is the sole exception: a rating is immutable once written, so it carries only `id` and `created_at` — it has neither an `updated_at` field nor a `version` field. Whenever this document refers to "bumping" or "advancing" a resource's version, it means incrementing that integer `version` by 1 and refreshing `updated_at` to the current logical-clock instant.

Clients must never supply `id`, `created_at`, `updated_at`, or `version` on create; these are all system-controlled. Likewise, any field described below as `source: system` or `source: computed` is owned by the server and is ignored if supplied by a client.

### 2.5. Precision and Rounding

Every monetary quantity is an integer number of cents. Wherever a calculation produces a fractional cent — commission on a labor basis, a percentage-based add-on bundle discount, a percentage after-hours surcharge, a marked-up parts line — the result is rounded to a whole cent using **round half up** (a value exactly at the .5 boundary rounds away from zero, upward). The one non-monetary rounded quantity is a pro's `rating_avg`, which is rounded to two decimal places, also round half up. Where a formula composes several rounded sub-results, the rounding is applied at each point noted in §3 and the intermediate whole-cent results are then combined; the order of rounding is significant and is specified explicitly for parts billing (round each line, then sum — never sum then round).

### 2.6. Optimistic Concurrency Control on Dispatch

Dispatching a work order is the one mutation guarded by optimistic concurrency control. A dispatch request must carry `expected_work_order_version`, a required input field whose value is the `version` of the target work order that the caller last observed. The server compares `expected_work_order_version` against the work order's current `version`. If they do not match, the dispatch is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated. This protects against a stale supersede: because a successful dispatch advances the work order's `version` (see §3), a dispatch carrying an older version means the order was already dispatched — or reverted to scheduled and re-dispatched — since the caller last read it, so honoring the offer would wrongly supersede the live one. The rejection is a stale-version comparison, not a timing or first-writer rule. No other endpoint accepts or requires a version field; only dispatch takes `expected_work_order_version`.

### 2.7. The Logical Clock and Deterministic Time

The platform runs on a logical clock rather than wall-clock time so that warranty windows, offer TTLs, vetting expiry, and appointment-window rules are fully deterministic. On server startup the clock reads exactly `2026-03-01T00:00:00Z`; until an operator advances it, every read of "now" returns that default and never the real wall-clock time. A `PlatformAdmin` may move the clock forward (or to any instant) by supplying a target `to_iso8601`; the response echoes the new `current_utc`. All system timestamps — `approved_at`, `expires_at`, `offered_at`, `responded_at`, `completed_at`, `warranty_expires_at`, `settled_at`, and the audit `created_at`/`updated_at` — are taken from this logical clock.

### 2.8. Nested Resource Resolution and Existence Ordering

Several endpoints address a child through its parent path — for example, a part or a rating attached to a specific work order, or an application attached to a specific pro. Path and body-referenced resources are validated left to right: the parent named earliest in the path is resolved first, and if any referenced resource does not exist the request fails with the corresponding `ERR_<RESOURCE>_NOT_FOUND` code (HTTP 404) — `ERR_RETAILER_NOT_FOUND`, `ERR_SERVICE_ZONE_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRO_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_INSTALL_TASK_NOT_FOUND`, `ERR_ADDON_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_PAYOUT_NOT_FOUND`, `ERR_SETTLEMENT_ENTRY_NOT_FOUND`, or `ERR_RATING_NOT_FOUND` — before any state or business validation runs.

### 2.9. Validation Ordering

When more than one rule could reject a request, the checks are evaluated in a fixed priority so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization and then resource ownership (both `ERR_UNAUTHORIZED`), then existence of every referenced resource (the `ERR_*_NOT_FOUND` family), then body well-formedness (`ERR_VALIDATION`: required fields present, enum values valid, `stars` within 1 to 5, monetary fields integral). The appointment-window ordering check (`ERR_INVALID_APPOINTMENT_WINDOW`) is evaluated after body well-formedness. State checks follow, and the terminal check is evaluated first: if the target is already in a terminal state the request yields `ERR_ALREADY_TERMINAL`, and only otherwise, when it is not in a valid from-state for the requested transition, does it yield `ERR_INVALID_STATE`. Domain-specific business rules — retailer suspension, zone coverage, add-on category match, vetting status and expiry, schedule conflict, zone capacity, appointment-not-started, warranty expiry, empty dispatch pool, duplicate rating, rating-state, and the dispatch OCC check — are evaluated after the generic state checks, each described alongside the workflow it guards in §3. This ordering matters: an earlier check masking a later one is intentional, so tests will assert the earliest applicable code.

### 2.10. Cascading Side Effects and Cross-Aggregate Consistency

A single business action frequently mutates several resources at once, and every one of those effects is part of the contract. Completing a work order, for instance, does not merely change the order's `status`; it writes a payout to the pro and a settlement charge to the retailer, and recomputes derived balances on both. Whenever any transition below lists a side effect that touches a second resource — creating a payout, holding it, releasing it, reversing it, or creating or reversing a settlement entry — the server performs all listed effects atomically, bumping the `version` and `updated_at` of every mutated resource that carries those fields, and recomputing every derived aggregate the effect names. The precise cascades are specified per transition in §3; none of them is optional.

## 3. Business Logic & Workflows

### 3.1. Catalog, Zones, and Account Setup

Before any job can flow, a `PlatformAdmin` populates the reference data. A **retailer** is created with a `name` and a `commission_rate_bps` — the referral fee, in basis points of the install task's base labor price, that the retailer retains on each completed job. A retailer begins life with `status` `ACTIVE` and a `settlement_balance_cents` of 0; an admin can later toggle `status` between `ACTIVE` and `SUSPENDED`. A suspended retailer blocks new scheduling (see §3.3). The `commission_rate_bps` must be between 0 and 10000 inclusive.

A **service zone** carries a `zone_code` (unique across all zones), a display `name`, a `max_concurrent_appointments` capacity of at least 1, and a `coverage_active` flag that defaults to true. The zone code uniqueness and the capacity floor are enforced at creation. `coverage_active` gates whether the platform currently services the zone; scheduling into a zone whose coverage is off is refused.

A **customer** record holds `full_name`, `email`, `phone`, and `address_line` (the service address for the install). Customers may be created either by a `PlatformAdmin` or by a `Retailer`.

The **install-task catalog** defines the fixed, priced units of work. Each `InstallTask` has a `task_code` (unique across tasks), a `name`, a `category` (one of `TV_MOUNT`, `APPLIANCE`, or `SMART_DEVICE`), a `required_skill` (also one of `TV_MOUNT`, `APPLIANCE`, `SMART_DEVICE`) that a pro must hold to perform it, a `base_price_cents` (the fixed base labor price, at least 0), an `estimated_minutes` on-site duration of at least 1 (informational only), and a `warranty_days` window of at least 0 days during which a redo may be requested. The **add-on catalog** parallels it: each `AddOn` has an `addon_code` (unique across add-ons), a `name`, a `category` (one of `TV_MOUNT`, `APPLIANCE`, `SMART_DEVICE`) constraining which orders it may attach to, and a `price_cents` list price of at least 0.

A **pro** (installer) is created with a `full_name`, `email`, a single `service_zone_id` naming the one zone the pro serves, and a `skills` array — a non-empty subset of `TV_MOUNT`, `APPLIANCE`, and `SMART_DEVICE`. All of a pro's derived counters start at 0: `pending_payout_cents`, `reserved_slot_count`, `rating_sum`, `rating_count`, and `rating_avg`. These are all server-computed and never client-supplied.

### 3.2. Pro Vetting Lifecycle

A pro cannot be dispatched until vetted. A `PlatformAdmin` submits a **vetting application** for a given pro, supplying the `pro_id` and an external `background_check_ref`; the application is born in `PENDING_REVIEW` with `approved_at` and `expires_at` both null. From `PENDING_REVIEW`, an admin either approves or rejects it. Approving a `PENDING_REVIEW` application moves it to `APPROVED`, stamps `approved_at` with the current logical-clock instant, and sets `expires_at` to that instant plus the platform's vetting validity window (`VETTING_VALID_DAYS`, which is 365 days). Rejecting a `PENDING_REVIEW` application moves it to `REJECTED`, a terminal state. Attempting either transition on an application not in `PENDING_REVIEW` is refused with `ERR_INVALID_STATE`; attempting it on an already-terminal application yields `ERR_ALREADY_TERMINAL`.

An `APPROVED` application can be suspended by an admin, moving it to `SUSPENDED`; a suspended pro is dispatch-ineligible. A `SUSPENDED` application can be reinstated back to `APPROVED`, which restores the pro's dispatch eligibility while leaving `approved_at` and `expires_at` unchanged. This forms an `APPROVED` ↔ `SUSPENDED` cycle. Separately, vetting lapses on its own: once the logical clock passes an approved application's `expires_at`, the application is treated as `EXPIRED` — a terminal state — and this is evaluated at dispatch-eligibility and accept-eligibility time (a pro whose `clock > expires_at` is no longer eligible even if the stored `status` still reads `APPROVED`). `EXPIRED` and `REJECTED` are terminal.

### 3.3. Work Order Creation and Scheduling

A `Retailer` opens a **work order** in `DRAFT` by referencing the product being installed and the parties involved: the referring `retailer_id` (which must equal the caller's own `X-User-ID`), the `customer_id` receiving the install, the `install_task_id` naming the fixed task, the `service_zone_id` the appointment falls in, the `product_sku` of the purchased item, its `product_category` (one of `TV_MOUNT`, `APPLIANCE`, `SMART_DEVICE`), and optional free-text `scope_notes`. The `product_category` must equal the referenced install task's `category`. A freshly created order has `status` `DRAFT`, an empty `selected_addon_ids`, a `quoted_price_cents` and `final_price_cents` of 0, and a null `appointment_pro_id`.

Scheduling is the retailer's next move on a `DRAFT` order. The retailer supplies the appointment window — `scheduled_start` and `scheduled_end` (both UTC) — and an optional `selected_addon_ids` list of add-ons to attach. Several conditions are checked before the order advances from `DRAFT` to `SCHEDULED`: the order must currently be in `DRAFT` (otherwise `ERR_INVALID_STATE`, or `ERR_ALREADY_TERMINAL` if it was cancelled or closed); the referring retailer must be `ACTIVE`, else the request is refused with `ERR_RETAILER_SUSPENDED`; the target zone's `coverage_active` must be true, else `ERR_ZONE_COVERAGE_INACTIVE`; the window must be well-ordered with `scheduled_start` strictly before `scheduled_end`, else `ERR_INVALID_APPOINTMENT_WINDOW`; and every id in `selected_addon_ids` must resolve to an add-on whose `category` equals the order's install task `category`, else `ERR_ADDON_CATEGORY_MISMATCH`. A nonexistent add-on id in the list is an existence failure (`ERR_ADDON_NOT_FOUND`) and is caught before the category comparison.

On a successful schedule the server records `scheduled_start`, `scheduled_end`, and the ordered `selected_addon_ids`, and computes the **provisional quote**. The `quoted_price_cents` is the install task's `base_price_cents` plus the sum of the `price_cents` of every add-on named in `selected_addon_ids`, at full list price — with no bundle discount, no parts, and no zone surcharge folded in. This is deliberately the provisional half of a dual-variant price: the authoritative charge is computed only at completion (§3.6) and diverges from the quote whenever a bundle discount, billed parts, or an after-hours surcharge applies. Because all inputs are integer cents, the quote needs no rounding.

A `DRAFT` or `SCHEDULED` order may be cancelled by its retailer (or by a `PlatformAdmin`); cancellation is covered in §3.8 alongside the compensation rules for later stages.

### 3.4. Dispatch and the Pro-Selection Policy

Dispatch is a `PlatformAdmin` action that advances an order from `SCHEDULED` to `DISPATCHED` (and, in the warranty loop, from `REDO_REQUESTED` to `DISPATCHED`). Because a dispatch supersedes any prior offer on the order, it is guarded by optimistic concurrency: the request carries `expected_work_order_version`, which must equal the order's current `version`, failing with `ERR_STALE_VERSION` (HTTP 412) on any mismatch as described in §2.6. The order must be in `SCHEDULED` or `REDO_REQUESTED` (otherwise `ERR_INVALID_STATE` / `ERR_ALREADY_TERMINAL`).

The heart of dispatch is a **deterministic selector** that chooses exactly one pro. A pro is an eligible candidate only if all of the following hold: the install task's `required_skill` is among the pro's `skills`; the pro's `service_zone_id` equals the order's `service_zone_id`; the pro has a vetting application that is `APPROVED` with the logical clock at or before its `expires_at` (a suspended, rejected, pending, or expired vetting disqualifies the pro); and the pro has no `ACCEPTED` assignment whose appointment window, expanded on both sides by the travel buffer of 30 minutes (`TRAVEL_BUFFER_MINUTES`), overlaps the order's `[scheduled_start, scheduled_end)` window. If the candidate pool is empty, dispatch is refused with `ERR_NO_ELIGIBLE_PRO`. Otherwise the candidates are ranked by `rating_avg` descending; ties are broken by `pending_payout_cents` ascending (favoring the pro carrying the lighter payout load); any remaining tie is broken by `created_at` ascending (the earliest-created pro wins), and a still-remaining tie on identical `created_at` is broken by ascending creation sequence (the earlier-created pro wins). The selector uses no random input and no id-based ordering — given the same data it always chooses the same pro. The first-ranked candidate is selected.

On a successful dispatch the server sets the order's `appointment_pro_id` to the selected pro, creates an `Assignment` for that pro in status `OFFERED` (copying the order's `scheduled_start` into the assignment's `appointment_start` and `scheduled_end` into `appointment_end`, and stamping `offered_at` with the clock), increments the selected pro's `reserved_slot_count` by 1, and increments the work order's `version` by 1. The new assignment's `work_order_id` and `pro_id` record the pairing; its `responded_at` is null until the pro answers.

### 3.5. Accepting, Declining, and Expiring Offers

An offered assignment sits in `OFFERED` until the pro responds or it lapses. Each assignment tracks a `reserved_slot_count`-affecting reservation on its pro: the count reflects how many of the pro's assignments are currently in `OFFERED` or `ACCEPTED`. The offer answers are the pro's to make — the acting `Pro`'s `X-User-ID` must equal the assignment's `pro_id`.

**Accepting** an `OFFERED` assignment moves it to `ACCEPTED` and stamps `responded_at` with the clock, but only after a battery of safety checks, each guarding against a specific hazard. The accepting pro's vetting must be `APPROVED` — not `PENDING_REVIEW`, `SUSPENDED`, or `REJECTED` — else `ERR_PRO_NOT_APPROVED`. That approved vetting must not have lapsed: the clock must be at or before the application's `expires_at`, else `ERR_VETTING_EXPIRED`. The pro must have no scheduling conflict: the accepted window `[appointment_start, appointment_end)`, expanded by the 30-minute travel buffer on each side, must not overlap another `ACCEPTED` assignment of the same pro, else `ERR_PRO_SCHEDULE_CONFLICT`. Finally, zone aggregate capacity must hold: the count of `ACCEPTED` assignments in the same zone whose windows overlap this one must be strictly less than the zone's `max_concurrent_appointments`, else `ERR_ZONE_CAPACITY_EXCEEDED`. Only when all four pass does the assignment become `ACCEPTED`.

**Declining** an `OFFERED` assignment moves it to `DECLINED`, stamps `responded_at`, decrements the pro's `reserved_slot_count` by 1, and reverts the parent work order from `DISPATCHED` back to `SCHEDULED` with its `appointment_pro_id` cleared — returning the order to the schedulable/dispatchable pool. **Expiry** is the system-triggered analogue: an admin (acting for the system) expires an `OFFERED` assignment — the server does not itself gate this call on any elapsed offer time-to-live (`OFFER_TTL_HOURS`), so any assignment currently in `OFFERED` may be expired — moving it to `EXPIRED`, decrementing the pro's `reserved_slot_count` by 1, and likewise reverting the order from `DISPATCHED` to `SCHEDULED` with `appointment_pro_id` cleared. Assignments in `DECLINED`, `EXPIRED`, and `CANCELLED` are terminal. Should the parent order be cancelled while dispatched, the system cancels the active assignment (from `OFFERED` or `ACCEPTED` to `CANCELLED`) and decrements the pro's `reserved_slot_count` by 1 — this system cancellation is detailed in §3.8.

### 3.6. On-Site Work, Parts, and Completion Pricing

Once a pro has accepted, the assigned pro **starts** the job, advancing the order from `DISPATCHED` to `IN_PROGRESS`. Starting requires the order to be in `DISPATCHED`, the order's active assignment to be in `ACCEPTED`, and the caller's `X-User-ID` to equal the order's `appointment_pro_id`; a caller who is not the appointment pro is refused with `ERR_UNAUTHORIZED`, and a wrong from-state yields `ERR_INVALID_STATE`.

While the job is underway (before completion) the pro may add **part/hardware lines** to the order. Each part carries the owning `work_order_id`, a `name` describing the hardware, a `unit_cost_cents` (the pro's at-cost acquisition price per unit, at least 0), a `quantity` of at least 1, and a `markup_bps` platform markup in basis points between 0 and 20000 inclusive. When a part is added, the server computes its `line_billed_cents` — the amount the customer is billed for that line — as the unit cost times quantity, marked up by the line's basis points, rounded half up to a whole cent: that is, `unit_cost_cents` multiplied by `quantity`, then multiplied by (10000 plus `markup_bps`) and divided by 10000, with the result rounded half up. Each line is rounded independently at the moment it is computed.

**Completion** is the pivotal transition, advancing the order from `IN_PROGRESS` to `COMPLETED`. It is performed by the appointment pro (`X-User-ID` must equal `appointment_pro_id`), requires the order to be in `IN_PROGRESS`, and is allowed only once the clock has reached the appointment start — that is, the current clock must be at or after `scheduled_start`, else the completion is refused with `ERR_APPOINTMENT_NOT_STARTED`. On completion the server computes the authoritative `final_price_cents`, stamps `completed_at` with the current clock, sets `warranty_expires_at` to `completed_at` plus the install task's `warranty_days`, and fires the money cascade described in §3.7.

The **final price** is built from four additive components, evaluated in this order. First, the add-ons gross is the sum of the `price_cents` of every add-on in `selected_addon_ids`. Second, a bundle discount is applied only when the order carries at least three add-ons (`BUNDLE_MIN_ADDONS` is 3): in that case the discount is 10 percent of the add-ons gross (`BUNDLE_DISCOUNT_BPS` is 1000 basis points), rounded half up to a whole cent, but capped so it never exceeds 5000 cents (`MAX_BUNDLE_DISCOUNT_CENTS`) — the discount is the smaller of the rounded ten-percent figure and 5000 cents; with fewer than three add-ons the discount is 0. The discounted add-ons total is the add-ons gross minus that bundle discount. Third, the billed parts total is the sum of every part line's `line_billed_cents`, computed by rounding each line half up and then summing the rounded lines — the rounding is per line and then summed, never summed and then rounded, and the two can differ by a cent or more at fractional-cent lines. Fourth, an after-hours zone surcharge applies when the appointment falls outside standard business hours: if the UTC hour of `scheduled_start` is earlier than 8 (`STANDARD_START_HOUR_UTC`) or the UTC hour of `scheduled_end` is later than 18 (`STANDARD_END_HOUR_UTC`), the surcharge is the greater of a flat 4000 cents (`AFTER_HOURS_FLAT_CENTS`) and 15 percent of the install task's `base_price_cents` (`AFTER_HOURS_BPS` is 1500 basis points) rounded half up to a whole cent; if the appointment is entirely within standard hours the surcharge is 0. The `final_price_cents` is then the install task's `base_price_cents` plus the discounted add-ons total plus the billed parts total plus the zone surcharge. Because this final figure folds in a possible discount, billed parts, and a surcharge, it diverges from the earlier `quoted_price_cents` whenever any of those three is present.

### 3.7. Payouts, Settlement, and the Money Cascade

Completing an order fires a two-pronged cascade — one arm pays the pro, the other bills the retailer — and both arms are created atomically at the moment of completion.

**The pro payout.** The system creates a `PayoutRecord` in status `PENDING` linked to the completed order's `work_order_id`, the appointment `pro_id`, and the referring `retailer_id` (denormalized onto the payout for settlement). Its money fields are computed as follows. The `gross_task_cents` is the labor basis: the install task's `base_price_cents` plus the discounted add-ons total (the same discounted add-ons figure used in the final price). The `commission_cents` is the platform's cut: 25 percent of `gross_task_cents` (`PLATFORM_COMMISSION_BPS` is 2500 basis points), rounded half up to a whole cent. The `parts_reimbursement_cents` reimburses the pro's hardware outlay at cost with no markup: the sum over the order's parts of `unit_cost_cents` times `quantity`. The provisional `payout_cents` is then `gross_task_cents` minus `commission_cents` plus `parts_reimbursement_cents`. This provisional figure stands while the payout is `PENDING` or `HELD`; the final figure is computed only when the payout is released (§3.8), where a per-redo penalty is subtracted.

**The retailer settlement charge.** Creation of that payout cascades into a `RetailerSettlementEntry` of `entry_type` `CHARGE` in status `PENDING`, linking the `retailer_id`, the `work_order_id`, and the triggering `payout_record_id`. Its `amount_cents` is what the retailer owes the platform: the order's `final_price_cents` minus the retailer's retained referral fee, where the referral fee (`referral_fee_cents`) is the retailer's `commission_rate_bps` applied to the install task's `base_price_cents` — that is, `base_price_cents` times `commission_rate_bps` divided by 10000, rounded half up to a whole cent. The entry's `settled_at` is null while `PENDING`.

**Derived balances.** Two running aggregates are recomputed whenever their inputs change. A retailer's `settlement_balance_cents` is the sum of `amount_cents` over that retailer's settlement entries whose `status` is `PENDING` (REVERSAL entries carry a negative `amount_cents`, so they subtract); SETTLED and REVERSED entries do not contribute. A pro's `pending_payout_cents` is the sum of `payout_cents` over that pro's payout records whose `status` is either `PENDING` or `RELEASED`; `HELD` and `REVERSED` payouts are excluded. At completion, both the referring retailer's `settlement_balance_cents` and the appointment pro's `pending_payout_cents` are recomputed to reflect the new charge and payout.

**The settlement run.** A `PlatformAdmin` periodically settles a retailer by supplying a `period_end` cutoff. The run selects that retailer's settlement entries whose `status` is `PENDING` and whose `created_at` is at or before `period_end` (inclusive), moves each to `SETTLED`, and stamps each `settled_at` with the current clock. It returns an inline summary object containing the `retailer_id`, the `settled_entry_count` (how many entries were settled), the `gross_settled_cents` (the sum of `amount_cents` over the settled entries, where REVERSAL rows contribute negative amounts), and the `remaining_balance_cents` (the retailer's `settlement_balance_cents` after the run, i.e. the sum of any still-`PENDING` entries created after `period_end`). Settling an entry that is not `PENDING`, or one that does not belong to the retailer being settled, is not eligible for the run. After the run the retailer's `settlement_balance_cents` is recomputed with the now-`SETTLED` entries excluded.

### 3.8. Warranty Redo, Closing, and Cancellation Compensation

**Warranty redo.** A completed job carries a warranty. The customer who owns the order (`X-User-ID` equal to the order's `customer_id`) may request a redo while the order is `COMPLETED` and the clock is at or before the order's `warranty_expires_at`; a request after that instant is refused with `ERR_WARRANTY_EXPIRED`, and a request on an order not in `COMPLETED` yields `ERR_INVALID_STATE`. A redo request advances the order from `COMPLETED` to `REDO_REQUESTED`, increments the order's `redo_count` by 1, moves the order's payout from `PENDING` to `HELD`, and recomputes the pro's `pending_payout_cents` (which now excludes the held payout). From `REDO_REQUESTED` the order is dispatched again (§3.4), flows through `DISPATCHED` → `IN_PROGRESS` → `COMPLETED`, and this closes the warranty redo cycle. When the redo reaches `COMPLETED` again, the order's `final_price_cents` is recomputed, `completed_at` and `warranty_expires_at` are refreshed to the new completion instant, and the held payout returns from `HELD` to `PENDING` (rather than a second payout or settlement entry being created), with the pro's `pending_payout_cents` recomputed accordingly.

**Closing.** After the warranty window has fully elapsed, a `PlatformAdmin` closes a `COMPLETED` order, advancing it to `CLOSED`. Closing is permitted only once the clock is strictly past the order's `warranty_expires_at`; the order must be in `COMPLETED`. Closing releases the pro's payout, moving it from `PENDING` to `RELEASED` and recomputing `payout_cents` with the **final variant**: the final payout is the provisional payout minus a per-redo penalty of 3000 cents (`REDO_PENALTY_CENTS`) times the order's `redo_count`, floored at 0 (never negative). Thus a job that was never redone releases at exactly its provisional amount, while each redo shaves 3000 cents off the pro's take. The pro's `pending_payout_cents` is recomputed after release (a `RELEASED` payout continues to count toward the pending total).

**Cancellation and compensation.** Cancelling an order drives it to the terminal `CANCELLED` state, and what must be undone depends on how far the order had progressed. A `Retailer` may cancel its own order while it is still `DRAFT` or `SCHEDULED`, optionally recording a `reason`; nothing downstream exists yet, so only the cancellation is recorded. A `PlatformAdmin` handles cancellations of orders already in flight. Cancelling a `DISPATCHED` order also transitions that order's active assignment — whether `OFFERED` or `ACCEPTED` — to `CANCELLED` and decrements the affected pro's `reserved_slot_count` by 1. Cancelling a `COMPLETED` order triggers full financial compensation so the order's net economic contribution returns to exactly 0: the order's payout, whether `PENDING` or `HELD`, is reversed to `REVERSED`; and the retailer settlement charge is unwound — if the order's `CHARGE` settlement entry is still `PENDING`, it is moved to `REVERSED` so it stops contributing to the balance, whereas if that charge was already `SETTLED`, a compensating `RetailerSettlementEntry` of `entry_type` `REVERSAL` is created in status `PENDING` whose `amount_cents` is the negative of the original charge amount. In either path the retailer's `settlement_balance_cents` and the appointment pro's `pending_payout_cents` are recomputed, leaving this order's net contribution to both at 0. The order's from-state must be one the cancel supports (`DRAFT`, `SCHEDULED`, `DISPATCHED`, or `COMPLETED`); an order already `CANCELLED` or `CLOSED` is terminal and yields `ERR_ALREADY_TERMINAL`.

### 3.9. Rating the Pro

After the work is done, the customer who owns the order may rate the pro. A rating may be submitted only when the order's `status` is `COMPLETED` or `CLOSED`, else the request is refused with `ERR_RATING_NOT_ALLOWED`; and at most one rating may exist per work order, so a second attempt is rejected with `ERR_DUPLICATE_RATING`. The submitting caller must own the order (`X-User-ID` equal to the order's `customer_id`). The rating captures the owning `work_order_id`, `stars` (an integer from 1 to 5 — values outside that range are an `ERR_VALIDATION` failure), and an optional free-text `comment`; the server copies the `pro_id` from the order's `appointment_pro_id` and the `customer_id` from the order's `customer_id`. A rating is immutable, carrying only `id` and `created_at`.

Each new rating updates the rated pro's running aggregates: `rating_sum` accumulates by adding the new `stars`, `rating_count` increases by 1, and `rating_avg` is recomputed as `rating_sum` divided by `rating_count`, rounded half up to two decimal places (and defined as 0 when `rating_count` is 0). This `rating_avg` is the primary key by which dispatch ranks candidate pros (§3.4), so a pro's rating history directly steers future work toward them.

## 4. Endpoint Definitions

The table below is a routing summary only; request payloads, response bodies, and side effects are specified in §2 and §3 and must be reconstructed from those narratives. As a general rule, an endpoint that creates a brand-new resource returns HTTP 201, while an endpoint that reads or modifies an existing resource returns HTTP 200. All endpoints emit the standard envelope of §2.2, and all list endpoints honor the pagination and ordering rules of §2.3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/retailers` | Create a retailer account (starts ACTIVE). | `PlatformAdmin` |
| GET | `/retailers/{id}` | Fetch a retailer. | `PlatformAdmin`, `Retailer` |
| PATCH | `/retailers/{id}/status` | Suspend or reactivate a retailer. | `PlatformAdmin` |
| POST | `/retailers/{id}/settlements` | Run a retailer settlement; returns a run summary. | `PlatformAdmin` |
| POST | `/service-zones` | Create a service zone. | `PlatformAdmin` |
| GET | `/service-zones/{id}` | Fetch a service zone. | `PlatformAdmin`, `Retailer`, `Pro` |
| POST | `/customers` | Create a customer. | `PlatformAdmin`, `Retailer` |
| GET | `/customers/{id}` | Fetch a customer. | `PlatformAdmin`, `Retailer`, `Customer` |
| POST | `/pros` | Create a pro (installer) profile. | `PlatformAdmin` |
| GET | `/pros/{id}` | Fetch a pro. | `PlatformAdmin`, `Pro` |
| GET | `/pros` | List pros, optionally filtered by service zone. | `PlatformAdmin` |
| POST | `/pros/{id}/applications` | Submit a vetting application for a pro. | `PlatformAdmin` |
| GET | `/applications/{id}` | Fetch a vetting application. | `PlatformAdmin`, `Pro` |
| GET | `/applications` | List vetting applications, filtered by pro. | `PlatformAdmin`, `Pro` |
| POST | `/applications/{id}/approve` | Approve a pending application. | `PlatformAdmin` |
| POST | `/applications/{id}/reject` | Reject a pending application. | `PlatformAdmin` |
| POST | `/applications/{id}/suspend` | Suspend an approved application. | `PlatformAdmin` |
| POST | `/applications/{id}/reinstate` | Reinstate a suspended application to APPROVED. | `PlatformAdmin` |
| POST | `/install-tasks` | Create a fixed-task catalog entry. | `PlatformAdmin` |
| GET | `/install-tasks/{id}` | Fetch an install task. | `PlatformAdmin`, `Retailer` |
| POST | `/add-ons` | Create an add-on catalog entry. | `PlatformAdmin` |
| GET | `/add-ons/{id}` | Fetch an add-on. | `PlatformAdmin`, `Retailer` |
| POST | `/work-orders` | Create a retailer-referred work order (DRAFT). | `Retailer` |
| GET | `/work-orders/{id}` | Fetch a work order. | `PlatformAdmin`, `Retailer`, `Pro`, `Customer` |
| GET | `/work-orders` | List work orders with optional foreign-key filters. | `PlatformAdmin`, `Retailer`, `Pro` |
| POST | `/work-orders/{id}/schedule` | Schedule the order, attach add-ons, compute the quote. | `Retailer` |
| POST | `/work-orders/{id}/dispatch` | Select an eligible pro and create an OFFERED assignment. | `PlatformAdmin` |
| POST | `/work-orders/{id}/start` | Pro starts the job. | `Pro` |
| POST | `/work-orders/{id}/parts` | Add a part/hardware line to the order. | `Pro` |
| GET | `/work-orders/{id}/parts` | List the order's part lines. | `PlatformAdmin`, `Pro`, `Retailer` |
| POST | `/work-orders/{id}/complete` | Pro completes the job; prices it; fires the cascade. | `Pro` |
| POST | `/work-orders/{id}/request-redo` | Customer requests a warranty redo. | `Customer` |
| POST | `/work-orders/{id}/cancel` | Cancel a work order (compensates completion effects). | `PlatformAdmin`, `Retailer` |
| POST | `/work-orders/{id}/close` | Close a completed order after warranty; releases payout. | `PlatformAdmin` |
| POST | `/work-orders/{id}/ratings` | Customer rates the pro for a completed order. | `Customer` |
| GET | `/ratings/{id}` | Fetch a rating. | `PlatformAdmin`, `Pro`, `Customer` |
| GET | `/ratings` | List ratings with optional foreign-key filters. | `PlatformAdmin`, `Pro`, `Customer` |
| GET | `/assignments/{id}` | Fetch an assignment. | `PlatformAdmin`, `Pro` |
| GET | `/assignments` | List assignments with optional foreign-key filters. | `PlatformAdmin`, `Pro` |
| POST | `/assignments/{id}/accept` | Pro accepts an offered assignment. | `Pro` |
| POST | `/assignments/{id}/decline` | Pro declines an offered assignment. | `Pro` |
| POST | `/assignments/{id}/expire` | System-triggered expiry of an offer past its TTL. | `PlatformAdmin` |
| GET | `/payout-records/{id}` | Fetch a payout record. | `PlatformAdmin`, `Pro` |
| GET | `/payout-records` | List payout records with optional foreign-key filters. | `PlatformAdmin`, `Pro` |
| GET | `/settlement-entries/{id}` | Fetch a settlement entry. | `PlatformAdmin`, `Retailer` |
| GET | `/settlement-entries` | List settlement entries with optional foreign-key filters. | `PlatformAdmin`, `Retailer` |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving). | `PlatformAdmin` |

## 5. Error Code Catalogue

Trigger conditions for each error are given in the §2 and §3 narratives; this catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_RETAILER_NOT_FOUND` | 404 |
| `ERR_SERVICE_ZONE_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_PRO_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_INSTALL_TASK_NOT_FOUND` | 404 |
| `ERR_ADDON_NOT_FOUND` | 404 |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_PAYOUT_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_ENTRY_NOT_FOUND` | 404 |
| `ERR_RATING_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_INVALID_APPOINTMENT_WINDOW` | 422 |
| `ERR_RETAILER_SUSPENDED` | 409 |
| `ERR_ZONE_COVERAGE_INACTIVE` | 409 |
| `ERR_ADDON_CATEGORY_MISMATCH` | 422 |
| `ERR_NO_ELIGIBLE_PRO` | 409 |
| `ERR_PRO_NOT_APPROVED` | 409 |
| `ERR_VETTING_EXPIRED` | 409 |
| `ERR_PRO_SCHEDULE_CONFLICT` | 409 |
| `ERR_ZONE_CAPACITY_EXCEEDED` | 409 |
| `ERR_APPOINTMENT_NOT_STARTED` | 422 |
| `ERR_WARRANTY_EXPIRED` | 422 |
| `ERR_DUPLICATE_RATING` | 409 |
| `ERR_RATING_NOT_ALLOWED` | 409 |
| `ERR_STALE_VERSION` | 412 |






