# Community Fridge API — Product Requirements Document

## 1. Introduction

Community fridges turn neighborhood surplus into meals, but they operate at the intersection of two unforgiving pressures: food safety and volunteer coordination. A donated tray of prepared food that sits above its safe temperature, a recalled batch that lingers on the shelf, or a cleaning shift that quietly lapses can each turn a well-meaning fridge into a public-health liability. At the same time, the people who keep these fridges running — volunteer stewards, restaurant and grocer donors, community members, and the sponsors who fund reimbursements — need a shared, real-time picture of what is stocked, what is needed, and who is on duty.

This document specifies the Community Fridge & Food-Sharing Network API, the backend that coordinates this ecosystem. The system manages a flat network of fridge locations, each tracking its own live temperature, storage capacity, cleanliness, safety posture, and sponsor-funded budget. It governs the full lifecycle of donated food — from a surplus-rescue pickup offer, through intake with food-safety gating, to community claims, recalls, quarantine, and eventual impact reporting. It schedules and reimburses volunteer stewards, enforces the food-safety protocols that determine whether a fridge may accept new food at all, and produces the usage and impact figures that sponsors and operators rely on.

The requirements below define the API contract precisely where implementations must not diverge — response envelopes, pagination, identifiers, precision, and concurrency — and describe the domain workflows and business rules that the implementation must realize. Every field, calculation, state transition, and validation described here is normative.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they are acting. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_UNAUTHENTICATED`. When the headers are present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly five roles, spelled precisely as follows: `NetworkAdmin`, `Steward`, `DonorAgent`, `SponsorAgent`, and `Member`.

Two of these roles are **entity-backed**, meaning their `X-User-ID` is the identifier of a persisted record and is used for ownership checks:

- When `X-User-Role` is `Steward`, `X-User-ID` is the `id` of the acting `Steward`. Ownership checks on any resource that references a steward compare that resource's steward foreign key to `X-User-ID`; for example, a steward completing a shift must be the shift's assigned `steward_id`.
- When `X-User-Role` is `DonorAgent`, `X-User-ID` is the `id` of the acting `Donor`. When a donor agent posts a surplus offer, the donor identified in the request path must equal `X-User-ID`; a mismatch is rejected with `ERR_DONOR_MISMATCH`. Ownership checks on donor-referencing resources compare the resource's `donor_id` to `X-User-ID`.

The remaining three roles are **opaque**: `NetworkAdmin`, `SponsorAgent`, and `Member` each carry an `X-User-ID` that is an operator identifier not tied to any persisted entity. The server may record such an identifier where a workflow calls for it, but it does not compare it to any entity's `id` for ownership purposes.

`NetworkAdmin` is the network operator: it provisions fridges, stewards, and donors, runs operations checkpoints, sets the logical clock, fails cleaning inspections, and suspends stewards. `Steward` volunteers cover and clean fridges, accept surplus pickups, log intake, and recall or discard unsafe food. `DonorAgent` represents restaurants, grocers, and individuals posting surplus-rescue offers. `SponsorAgent` funds fridges through grants. `Member` is a community member who claims stock and posts needs. The specific operations each role may invoke are enumerated in the endpoint table of §4; read (GET) operations are broadly available to authenticated roles as noted there.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it reflects the server's real wall-clock time at the moment the response is built and is independent of the logical operations clock of §2.6.
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Values outside the permitted range are clamped to the nearest bound rather than rejected — a `limit` below 1 becomes 1, a `limit` above 100 becomes 100, and a negative `offset` becomes 0 — while a non-integer `limit` or `offset` is rejected with `ERR_VALIDATION`. `has_more` is true exactly when `offset + limit` (using the clamped values) is less than `total_count`.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order; resources sharing an identical `created_at` (as happens when the logical clock has not advanced between creations) are ordered by their server-side creation sequence, i.e. the order in which they were persisted.

Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every persisted resource in this system — `Fridge`, `Steward`, `Donor`, `SponsorGrant`, `StewardShift`, `SurplusOffer`, `DonationBatch`, `Claim`, and `NeedPosting` — carries a common set of system-managed fields:

- `id`: a unique, server-minted identifier formatted as a UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version`: an integer that begins at its initial value and increments by one on every mutation of the resource.

All nine resource types carry all four fields; none of them omit `updated_at` or `version`. Crucially, the `version` and `updated_at` fields are also refreshed whenever a *derived* field changes as a side effect of another operation. For instance, when a fridge's `stock_slots_used`, `safety_posture`, or any budget figure is recomputed because of an intake, a recall, or a completed shift, that fridge's `updated_at` is refreshed and its `version` is incremented — even though no client wrote to the fridge directly. This makes `version` a faithful record of every change a resource has undergone, whether client-driven or reconciled by the server.

### 2.5. Nested Resource Retrieval and Validation Precedence

Many endpoints address a resource through a hierarchical path — for example, a batch nested under a fridge, or a claim nested under a batch. The system validates the identifiers in such a path from left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource. A request naming a batch under a fridge that does not exist fails on the fridge before the batch is ever considered. Body foreign keys are likewise checked for existence.

Across all endpoints, validation proceeds in a fixed order of precedence, and the first failing check determines the error returned. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_UNAUTHORIZED`), then donor-ownership on offer creation (`ERR_DONOR_MISMATCH`), then existence of referenced resources (`ERR_NOT_FOUND`). Only after those universal gates pass does an endpoint evaluate its state, concurrency, safety, temporal, capacity, and fiscal rules, in the order described in the relevant workflow below. Malformed bodies, missing required fields, invalid enum values, and a clock that would move backward are all reported as `ERR_VALIDATION`.

### 2.6. The Logical Operations Clock

The system runs on a **logical clock**, not wall-clock time. The server boots with the clock set to `2026-03-01T00:00:00Z`, and the clock never reads real time. All time-based comparisons — batch expiry, offer and need deadlines, shift windows, certification of "now" for reliability — read this logical clock. A `NetworkAdmin` may advance the clock by supplying a new instant as `to_iso8601`; the new value must be greater than or equal to the current value, and an attempt to move it backward is rejected with `ERR_VALIDATION`. Setting the clock returns no resource payload.

### 2.7. Fridge Safety Posture and Cascading Reconciliation

Each `Fridge` continuously derives a `safety_posture`, one of `OPERATIONAL`, `RESTRICTED`, or `QUARANTINED`, and this posture is the master gate that determines whether food may flow into the fridge. The posture is recomputed whenever any of its inputs changes — the fridge's `active_recall_count`, its `current_temp_c`, or its `last_cleaned_at`. The rule is evaluated top-down: if the fridge has at least one active recall (`active_recall_count` is one or more), the posture is `QUARANTINED`. Otherwise, if the interior temperature is above 8.0 degrees Celsius, **or** more than seven days (that is, more than 604800 seconds) have elapsed on the logical clock since the fridge was last cleaned, the posture is `RESTRICTED`. When neither condition holds, the posture is `OPERATIONAL`.

`active_recall_count` is itself a derived count: the number of donation batches at this fridge currently in `RECALLED` status.

A `QUARANTINED` posture is more than a label — it triggers a **cascade** across the fridge's dependent resources, and the cascade reverts when the fridge recovers. When a fridge becomes `QUARANTINED`, every other batch at that fridge that was in `STOCKED` status is moved to `HELD`, and every `NeedPosting` at that fridge that was in `OPEN` status is moved to `SUSPENDED`. When the fridge later leaves `QUARANTINED` (its `active_recall_count` returns to zero and no other blocker remains), each `HELD` batch returns to `STOCKED` and each `SUSPENDED` need returns to `OPEN`. Every resource touched by such a reconciliation independently has its `updated_at` refreshed and its `version` incremented, per §2.4. `RESTRICTED` posture does not trigger the hold cascade; instead it gates intake and offer-acceptance and raises the hazard reimbursement multiplier described in §3.3.

### 2.8. Storage Slot Ledger and Capacity

A fridge has a fixed number of physical storage slots, `capacity_slots`, established at creation and always at least 1. The system maintains a live slot ledger on the fridge. `stock_slots_used` is the sum of the `slot_footprint` values of every batch at the fridge whose status is `STOCKED`, `HELD`, or `RECALLED` — these three statuses all continue to occupy physical space. Any batch in a terminal status (`EXPIRED`, `DISCARDED`, or `CLAIMED_OUT`) has vacated its slots and is excluded from the sum. `free_slots` is `capacity_slots` minus `stock_slots_used`. Slot arithmetic is exact and integer-valued. The ledger is recomputed on every batch stock/free transition: intake, hold, recall, discard, expiry, and claimed-out.

### 2.9. Sponsor Budget Ledger and Fiscal Responsibility

Each fridge also maintains a budget ledger denominated in whole cents, and it is the single source of truth for reimbursement funding. `budget_granted_cents` is the sum of `amount_cents` over every `SponsorGrant` for the fridge currently in `ACTIVE` status. `budget_committed_cents` is the sum of `reimbursement_amount_cents` over every `StewardShift` for the fridge currently in `COMPLETED` status. `budget_available_cents` is `budget_granted_cents` minus `budget_committed_cents`. All three figures are exact integer cents and are recomputed whenever a grant is created or cancelled or a shift is completed or reverted. The invariant `budget_granted_cents == budget_available_cents + budget_committed_cents` holds at all times, and the grant-cancellation rule described in §3.2 is designed to preserve it.

### 2.10. Optimistic Concurrency Control for Intake

Logging a donation intake is the one operation in this system protected by optimistic concurrency control. A request to log a `DonationBatch` intake against a fridge must include `expected_fridge_version`, a non-optional field carrying the `version` of the target `Fridge` that the client last observed. If `expected_fridge_version` does not equal the fridge's current `version`, the intake is rejected with `ERR_FRIDGE_VERSION_CONFLICT` (HTTP 412). Because every intake occupies capacity slots and bumps the fridge's `version`, and because slot-freeing transitions also bump it, a client whose view of free capacity is stale will be turned away rather than silently over-committing slots. No other endpoint takes a version field or performs an OCC check.

### 2.11. Numeric Precision and Impact Accounting

Monetary reimbursement amounts are computed in exact decimal arithmetic and rounded to whole cents using the round-half-up convention. Reliability scores are computed to two decimal places, also round-half-up. Meal-impact figures are whole integers, rounded half-up. Where a calculation both rounds per item and sums across items — notably the fridge impact report — the rounding is applied per item first and the rounded results are then summed; the order is fixed and must not be replaced by rounding a single aggregate. Slot counts are exact integers. All timestamp comparisons use the logical clock of §2.6.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Network: Fridges, Stewards, and Donors

The network is populated by a `NetworkAdmin`. A fridge is created with a human-readable `name`, a `location_label` describing its street or neighborhood, and a `capacity_slots` count of at least one physical slot. On creation the fridge starts fully available: its `safety_posture` is `OPERATIONAL`, its `stock_slots_used` is zero and `free_slots` equals `capacity_slots`, all budget figures are zero, its `active_recall_count` and `ops_run_index` are zero, its `current_temp_c` starts at 4.0 degrees, and its `last_cleaned_at` defaults to the moment of creation. The `total_meals_provided` impact figure begins at zero.

A steward is registered with a `name` and an `email`. A new steward is `ACTIVE` with a `missed_count` of zero; its `completed_count`, `reliability_actual`, and `reliability_projected` are derived on read. A `NetworkAdmin` may later suspend a steward, moving `status` from `ACTIVE` to `SUSPENDED`. A donor is registered with a `name`, a `donor_type` of `RESTAURANT`, `GROCER`, or `INDIVIDUAL`, and a `contact` phone or email.

A fridge's interior temperature is kept current through readings. When a `NetworkAdmin` or `Steward` records a reading, the supplied `reading_c` replaces the fridge's `current_temp_c` and the fridge's `safety_posture` is recomputed against the 8.0-degree warning threshold described in §2.7. A reading that pushes the temperature above the warning line can move an `OPERATIONAL` fridge to `RESTRICTED`; a reading that brings it back down can restore it, provided no recall or stale-cleaning condition remains.

### 3.2. Sponsor Grants and the Budget Ledger

A `SponsorAgent` (or a `NetworkAdmin`) funds a fridge by creating a grant against it, supplying a `sponsor_name` and an `amount_cents` of at least one cent. The grant is recorded with the fridge it funds captured as `fridge_id`, its `status` set to `ACTIVE`, and the fridge's `budget_granted_cents` and `budget_available_cents` each increased by `amount_cents`.

A grant may later be cancelled by a `SponsorAgent` or `NetworkAdmin` to withdraw its uncommitted funds, moving `status` from `ACTIVE` to `CANCELLED`. Cancellation is only permitted while the grant is `ACTIVE`; otherwise it is rejected with `ERR_INVALID_STATE`. Because committed funds cannot be clawed back, cancellation is allowed only when the fridge's `budget_available_cents` is at least the grant's `amount_cents`; if the withdrawal would drive the available balance below zero, it is rejected with `ERR_BUDGET_EXCEEDED`. On a successful cancellation, both `budget_granted_cents` and `budget_available_cents` are reduced by `amount_cents`, which preserves the ledger invariant of §2.9.

### 3.3. Scheduling, Completing, and Reimbursing Steward Shifts

Coverage and cleaning duties are organized as shifts. A `Steward` (scheduling their own duty) or a `NetworkAdmin` schedules a shift at a fridge, supplying the assigned `steward_id`, a `kind` of `COVERAGE` or `CLEANING`, and the window `start_at` (inclusive) and `end_at` (exclusive). When the actor is a `Steward`, the supplied `steward_id` must equal the acting `X-User-ID`; a steward scheduling a shift for a different steward is rejected with `ERR_UNAUTHORIZED` (a `NetworkAdmin` may schedule for any steward). The shift records the covered fridge as `fridge_id`, starts in `SCHEDULED` status, and carries `miles_traveled` and `handled_cold_chain` fields that remain at their defaults of 0 and false until completion. The window itself must be well-formed: `start_at` must be strictly before `end_at`, or the request is rejected with `ERR_PICKUP_WINDOW_INVALID`.

Two scheduling conflicts are then checked. A new `COVERAGE` shift must not overlap an existing `SCHEDULED` or `COMPLETED` `COVERAGE` shift on the **same fridge**; the windows are treated as half-open intervals `[start, end)`, so a shift that begins exactly when another ends is adjacent and permitted, while any true overlap is rejected with `ERR_SHIFT_OVERLAP_FRIDGE`. Independently, a new shift for a given steward must not fall within a 30-minute travel buffer of any other `SCHEDULED` or `COMPLETED` shift (of either `kind`) for that **same steward** on any fridge; shifts in any other status, such as `MISSED`, are ignored for this check. The buffer expands each such existing shift by 30 minutes on both ends into a closed interval, and a collision is rejected with `ERR_STEWARD_DOUBLE_BOOKED`.

A shift is completed by its assigned `Steward` or by a `NetworkAdmin`, who supplies `miles_traveled` and the `handled_cold_chain` flag at that moment. Completion is subject to ordered gating, and the first check is that the shift is still in `SCHEDULED` status — a shift in any other status (already `COMPLETED`, `MISSED`, etc.) is rejected with `ERR_INVALID_STATE` before any of the checks below are evaluated: the steward must be `ACTIVE`, or the request fails with `ERR_STEWARD_SUSPENDED`; the logical clock must have reached the shift's `start_at` (that is, current time at or after `start_at`), or the request fails with `ERR_INVALID_STATE`; and when the actor is a `Steward`, the acting `X-User-ID` must equal the shift's `steward_id`, or the request fails with `ERR_STEWARD_NOT_ASSIGNED` (a `NetworkAdmin` may complete any shift). On success the shift moves from `SCHEDULED` to `COMPLETED`, its `completed_at` is stamped with the current logical time, the steward's `completed_count` is recomputed, and the reimbursement is calculated and committed to the fridge's `budget_committed_cents`.

The reimbursement, stored as `reimbursement_amount_cents`, combines four ingredients. First, a base stipend keyed to the shift's `kind`: 1500 cents for a `COVERAGE` shift and 2000 cents for a `CLEANING` shift. Second, a tiered mileage allowance on `miles_traveled`: the first 5 miles are reimbursed at 50 cents per mile; each mile beyond 5 and up to 20 is reimbursed at 30 cents per mile; each mile beyond 20 is reimbursed at 20 cents per mile. Concretely, for up to 5 miles the allowance is the miles times 50 cents; for more than 5 and up to 20 miles it is 250 cents plus 30 cents for each mile above 5; beyond 20 miles it is 250 cents plus 450 cents plus 20 cents for each mile above 20; the mileage allowance is rounded half-up to whole cents. Third, a cold-chain bonus of 500 cents is added when `handled_cold_chain` is true, and nothing otherwise. The base, mileage allowance, and bonus are summed, and finally the sum is multiplied by a hazard factor: 1.25 when the fridge's `safety_posture` is `RESTRICTED` at the moment of completion, and 1.0 otherwise. The final product is rounded half-up to whole cents to yield `reimbursement_amount_cents`.

When the completed shift is a `CLEANING` shift, completion also sets the fridge's `last_cleaned_at` to the current logical time and recomputes the fridge's `safety_posture`, which can lift a fridge out of `RESTRICTED` if a stale-cleaning condition was the only thing holding it there.

A `NetworkAdmin` may fail the inspection of a completed cleaning shift. This is a deliberate cyclic revert: it is permitted only when the shift's `kind` is `CLEANING` (otherwise `ERR_INVALID_STATE`), and it moves the shift from `COMPLETED` back to `SCHEDULED`. The reversal subtracts the shift's `reimbursement_amount_cents` from the fridge's `budget_committed_cents` and then zeroes `reimbursement_amount_cents`, restores the fridge's `last_cleaned_at` to its prior value, and recomputes `safety_posture`.

A steward's reliability is derived on read from the current state of its shifts. Let the number of `COMPLETED` shifts be the completed tally, the number of `MISSED` shifts be the missed tally, and the number of `SCHEDULED` shifts whose `end_at` is still in the future (beyond the logical clock) be the upcoming tally. The `reliability_actual` score is the completed tally divided by the sum of the completed and missed tallies, rounded half-up to two decimals; if that sum is zero, `reliability_actual` is 1.00. The `reliability_projected` score optimistically counts upcoming shifts as though they will complete: it is the completed tally plus the upcoming tally, divided by the sum of the completed, missed, and upcoming tallies, rounded half-up to two decimals; if that sum is zero, `reliability_projected` is 1.00. The projected score diverges from the actual score exactly when there are upcoming shifts.

### 3.4. Surplus Rescue Offers

A `DonorAgent` posts a surplus-rescue pickup offer, which a steward can later fulfill as an intake. The offer is created under the donor — whose identity must match the acting `X-User-ID`, or the post is rejected with `ERR_DONOR_MISMATCH` — and captures that donor as `donor_id`. The donor supplies the target `fridge_id`, a free-text `description` of the surplus, an `estimated_quantity_kg` greater than zero, and a `pickup_by` deadline. A malformed pickup window is rejected with `ERR_PICKUP_WINDOW_INVALID`. The offer begins in `OFFERED` status.

An `OFFERED` offer forks two ways. A `Steward` (or `NetworkAdmin`) may accept it, moving it from `OFFERED` to `ACCEPTED`. Acceptance is checked in this order: the offer must be in `OFFERED` status, and from any other status it is rejected with `ERR_INVALID_STATE` before the fridge and deadline are examined; then the target fridge's `safety_posture` must be `OPERATIONAL`, failing with `ERR_FRIDGE_NOT_OPERATIONAL` otherwise; and then the current logical time must be strictly before `pickup_by`, failing with `ERR_OFFER_EXPIRED` if the deadline has passed. Alternatively, an offer that is never accepted before its deadline expires: the operations checkpoint of §3.9 moves an `OFFERED` offer to the terminal `EXPIRED` status once the clock reaches `pickup_by`. An accepted offer that is not converted before its deadline is likewise swept to `EXPIRED`.

An `ACCEPTED` offer reaches its intended terminal status, `CONVERTED`, automatically: when a donation intake is logged citing this offer, the system moves the offer from `ACCEPTED` to `CONVERTED` as a side effect of the intake (see §3.5).

### 3.5. Donation Intake and Food-Safety Gating

Logging an intake is the central food-safety chokepoint of the system, performed by a `Steward` or `NetworkAdmin`. The intake creates a `DonationBatch` under a fridge and records the receiving fridge as `fridge_id`, the logging steward's `steward_id`, and an optional `surplus_offer_id` that ties the intake back to a rescue offer (null for walk-in donations). The donor declares a `food_category` — one of `PRODUCE`, `BAKERY`, `DAIRY`, `PREPARED`, or `PACKAGED` — a `storage_type` of `COLD_CHAIN` or `AMBIENT`, a `declared_quantity_kg` greater than zero, a `slot_footprint` of at least one physical slot, the measured `intake_temp_c`, a `use_by` timestamp, and an `allergens` list of labels (empty by default). Every intake must also carry `expected_fridge_version` for the concurrency check of §2.10.

The intake is gated in a fixed order. After existence checks, the concurrency check runs: `expected_fridge_version` must equal the fridge's current `version`, or the intake is rejected with `ERR_FRIDGE_VERSION_CONFLICT`. Next, the fridge's `safety_posture` must be `OPERATIONAL`; a `RESTRICTED` or `QUARANTINED` fridge cannot accept new food and the intake is rejected with `ERR_FRIDGE_NOT_OPERATIONAL`. Then two food-safety label checks apply. For a cold-chain intake, the temperature must be safe: if `storage_type` is `COLD_CHAIN` and `intake_temp_c` is strictly above 5.0 degrees Celsius, the intake is rejected with `ERR_TEMP_UNSAFE`; a reading of exactly 5.0 degrees is accepted. When the `food_category` is `BAKERY`, `DAIRY`, or `PREPARED`, the `allergens` list must be non-empty, or the intake is rejected with `ERR_ALLERGEN_LABEL_REQUIRED`. Finally, capacity is checked: the batch's `slot_footprint` must fit within the fridge's current `free_slots`, or the intake is rejected with `ERR_CAPACITY_EXCEEDED`.

On success the batch is created in `STOCKED` status. The fridge's `stock_slots_used` increases by the batch's `slot_footprint` and `free_slots` is recomputed, and the fridge's `version` increments by one — this is the increment that later invalidates any stale `expected_fridge_version`. The batch's `provisional_meals` is computed immediately from the declared mass: it is `declared_quantity_kg` divided by 1.2 kilograms per meal, rounded half-up to a whole number of meals. If the intake cited a `surplus_offer_id` whose offer is in `ACCEPTED` status, that offer is moved to `CONVERTED` as part of the same operation.

A batch also tracks `available_quantity_kg`, the mass still up for grabs, which equals `declared_quantity_kg` minus the sum of `quantity_kg` over all of its non-`VOIDED` claims. Its `realized_quantity_kg` and `realized_meals` remain at zero until the batch reaches a terminal status, at which point they are frozen (see §3.6 and §3.7).

### 3.6. Community Claims and Stock Depletion

A `Member` (or a `Steward` or `NetworkAdmin`) claims a portion of a stocked batch, supplying the `quantity_kg` wanted and an optional non-identifying `recipient_label`. The claim records the claimed batch as `donation_batch_id` and denormalizes the batch's fridge as `fridge_id`, and it begins in `OPEN` status. A claim is only valid against a batch in `STOCKED` status; a batch that is `RECALLED`, `HELD`, or in any terminal status cannot be claimed, and the attempt is rejected with `ERR_BATCH_RECALLED`. The batch must also not be past its `use_by`: a claim on a batch whose `use_by` the logical clock has reached is rejected with `ERR_USE_BY_PASSED`. The requested `quantity_kg` must be at most the batch's current `available_quantity_kg`, and the batch must have some availability remaining; a claim exceeding what is available, or against a batch with zero available, is rejected with `ERR_NO_PORTIONS`.

A successful claim reduces the batch's `available_quantity_kg` by the claimed `quantity_kg`. If that reduction drives `available_quantity_kg` to zero, the batch has been fully distributed: it transitions from `STOCKED` to the terminal `CLAIMED_OUT` status, which frees its slots (removing its `slot_footprint` from the fridge's `stock_slots_used`) and freezes its realized figures. Freezing means `realized_quantity_kg` is set to the sum of `quantity_kg` over the batch's non-`VOIDED` claims, and `realized_meals` is set to that realized mass divided by 1.2 kilograms per meal, rounded half-up to a whole number of meals.

Claims are also moved by cascades rather than by direct action. When a batch is recalled, each of its `OPEN` claims is moved to `VOIDED`, and each voided claim's `quantity_kg` returns to the batch's `available_quantity_kg`. When a batch transitions to `EXPIRED`, each of its `OPEN` claims is moved to the terminal `EXPIRED` status.

### 3.7. Recalls, Quarantine, Discards, and Expiry

Food safety sometimes requires pulling a batch. A `Steward` or `NetworkAdmin` recalls a batch that is currently `STOCKED` or `HELD`, moving it to `RECALLED`; a recall attempted on a batch in any other status (already `RECALLED` or terminal) is rejected with `ERR_INVALID_STATE`. A recalled batch continues to occupy its slots (it is still counted in `stock_slots_used`). The recall voids all `OPEN` claims on the batch as described in §3.6, and it raises the fridge's `active_recall_count`, which forces the fridge's `safety_posture` to `QUARANTINED`. That quarantine in turn triggers the cascade of §2.7: every other `STOCKED` batch at the fridge is moved to `HELD` and every `OPEN` need is moved to `SUSPENDED`.

A recalled batch is resolved by discarding it. A `Steward` or `NetworkAdmin` discards a batch, moving it from `RECALLED` to the terminal `DISCARDED` status; this frees its slots and freezes its realized `realized_quantity_kg` and `realized_meals` figures using the same rule as in §3.6. Discarding recomputes the fridge's `active_recall_count`; if it reaches zero and no other blocker remains, the fridge leaves `QUARANTINED`, and the reversal cascade returns each `HELD` batch to `STOCKED` and each `SUSPENDED` need to `OPEN`. A `STOCKED` batch may also be discarded directly — for spoilage discovered outside a recall — moving it from `STOCKED` to `DISCARDED`, which frees its slots (a compensation for the slot occupation taken at intake) and freezes its realized figures. Discard is therefore only valid from `RECALLED` or `STOCKED`; a discard attempted on a batch in any other status (`HELD` or already terminal) is rejected with `ERR_INVALID_STATE`.

Batches that quietly age out are handled by the operations checkpoint of §3.9. The expiry boundary is inclusive: a `STOCKED` or `HELD` batch whose `use_by` the logical clock has reached — that is, current time at or after `use_by` — is moved to the terminal `EXPIRED` status, which frees its slots and freezes its realized figures. Expiring a batch also expires its `OPEN` claims as described in §3.6.

### 3.8. Community Needs

A `Member`, `Steward`, or `NetworkAdmin` posts a community need at a fridge, supplying an `item_description`, a `quantity_needed` of at least one unit, and a `needed_by` deadline. The need records its fridge as `fridge_id` and begins in `OPEN` status. A need is suspended, not by direct request but by the quarantine cascade of §2.7: when its fridge becomes `QUARANTINED`, an `OPEN` need moves to `SUSPENDED`, and when the fridge recovers it moves back from `SUSPENDED` to `OPEN`. A need that reaches its deadline expires: the operations checkpoint moves an `OPEN` or `SUSPENDED` need to the terminal `EXPIRED` status once the logical clock reaches `needed_by`.

### 3.9. Operations Checkpoints and Impact Reporting

Because time in this system advances only on the logical clock, the passage of deadlines is realized through an explicit operations checkpoint run by a `NetworkAdmin` against a fridge. Each checkpoint increments the fridge's `ops_run_index` by one and then, at the current logical time, sweeps the fridge's dependent resources: `STOCKED` and `HELD` batches that have reached their `use_by` are expired (freeing slots and freezing realized figures); `OFFERED` and `ACCEPTED` offers that have reached their `pickup_by` are expired; `OPEN` and `SUSPENDED` needs that have reached their `needed_by` are expired; and `SCHEDULED` shifts that have reached their `end_at` while still scheduled are moved to `MISSED`, each incrementing the assigned steward's `missed_count` by one. After the sweep, the fridge's `safety_posture` is recomputed. The `MISSED` status is terminal for a shift, and a missed shift never earns reimbursement.

The fridge's `total_meals_provided` is the impact figure reported on read. It is computed by taking every terminal batch at the fridge — those in `EXPIRED`, `DISCARDED`, or `CLAIMED_OUT` status, and only those — computing for each such batch its `realized_quantity_kg` divided by 1.2 kilograms per meal rounded half-up to a whole number of meals, and then summing those per-batch whole-meal results. The rounding is performed per batch before summing; the total is not obtained by dividing a summed mass. Batches still in `STOCKED`, `HELD`, or `RECALLED` status contribute nothing to the impact figure.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify or read an existing resource return `200 OK`. Reconstruct request payloads, response side effects, and validation ordering from the workflow narratives in §3; the table below lists only the HTTP surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fridges` | Create a fridge location | NetworkAdmin |
| GET | `/fridges/{fridgeId}` | Get a fridge (computed posture, slot ledger, budget ledger, impact) | NetworkAdmin, Steward, DonorAgent, SponsorAgent, Member |
| POST | `/fridges/{fridgeId}/temperature` | Record an interior temperature reading; recompute posture | NetworkAdmin, Steward |
| POST | `/fridges/{fridgeId}/run-ops` | Run an operations checkpoint at the current logical clock | NetworkAdmin |
| POST | `/stewards` | Register a volunteer steward | NetworkAdmin |
| GET | `/stewards/{stewardId}` | Get a steward (computed reliability) | NetworkAdmin, Steward, Member, DonorAgent, SponsorAgent |
| POST | `/stewards/{stewardId}/suspend` | Suspend a steward | NetworkAdmin |
| POST | `/donors` | Register a surplus donor | NetworkAdmin |
| GET | `/donors/{donorId}` | Get a donor | NetworkAdmin, DonorAgent, Steward |
| POST | `/fridges/{fridgeId}/grants` | Create a sponsor grant funding a fridge | SponsorAgent, NetworkAdmin |
| GET | `/grants/{grantId}` | Get a sponsor grant | NetworkAdmin, SponsorAgent, Steward |
| GET | `/grants` | List sponsor grants, filterable by fridge | NetworkAdmin, SponsorAgent, Steward |
| POST | `/grants/{grantId}/cancel` | Cancel a grant, withdrawing uncommitted funds | SponsorAgent, NetworkAdmin |
| POST | `/fridges/{fridgeId}/shifts` | Schedule a coverage or cleaning shift | Steward, NetworkAdmin |
| GET | `/shifts/{shiftId}` | Get a steward shift | NetworkAdmin, Steward, Member |
| GET | `/shifts` | List shifts, filterable by fridge and/or steward | NetworkAdmin, Steward, Member |
| POST | `/shifts/{shiftId}/complete` | Complete a shift; compute reimbursement | Steward, NetworkAdmin |
| POST | `/shifts/{shiftId}/fail-inspection` | Fail a completed cleaning shift; revert and reverse reimbursement | NetworkAdmin |
| POST | `/donors/{donorId}/offers` | Post a surplus-rescue pickup offer | DonorAgent, NetworkAdmin |
| GET | `/offers/{offerId}` | Get a surplus offer | NetworkAdmin, DonorAgent, Steward |
| GET | `/offers` | List surplus offers, filterable by donor and/or fridge | NetworkAdmin, DonorAgent, Steward |
| POST | `/offers/{offerId}/accept` | Accept a surplus offer for pickup | Steward, NetworkAdmin |
| POST | `/fridges/{fridgeId}/donation-batches` | Log a donation intake into a fridge | Steward, NetworkAdmin |
| GET | `/donation-batches/{batchId}` | Get a donation batch | NetworkAdmin, Steward, Member, DonorAgent |
| GET | `/donation-batches` | List batches, filterable by fridge, steward, and/or source offer | NetworkAdmin, Steward, Member, DonorAgent |
| POST | `/donation-batches/{batchId}/recall` | Recall a batch, cascading into fridge quarantine | Steward, NetworkAdmin |
| POST | `/donation-batches/{batchId}/discard` | Discard a batch, freeing its slots | Steward, NetworkAdmin |
| POST | `/donation-batches/{batchId}/claims` | Claim a portion of a stocked batch | Member, Steward, NetworkAdmin |
| GET | `/claims/{claimId}` | Get a claim | NetworkAdmin, Steward, Member |
| GET | `/claims` | List claims, filterable by batch and/or fridge | NetworkAdmin, Steward, Member |
| POST | `/fridges/{fridgeId}/needs` | Post a community need at a fridge | Member, Steward, NetworkAdmin |
| GET | `/needs/{needId}` | Get a need posting | NetworkAdmin, Steward, Member |
| GET | `/needs` | List need postings, filterable by fridge | NetworkAdmin, Steward, Member |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving capability) | NetworkAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_DONOR_MISMATCH` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_BATCH_RECALLED` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_FRIDGE_VERSION_CONFLICT` | 412 Precondition Failed |
| `ERR_FRIDGE_NOT_OPERATIONAL` | 409 Conflict |
| `ERR_TEMP_UNSAFE` | 422 Unprocessable Entity |
| `ERR_ALLERGEN_LABEL_REQUIRED` | 422 Unprocessable Entity |
| `ERR_USE_BY_PASSED` | 422 Unprocessable Entity |
| `ERR_STEWARD_SUSPENDED` | 409 Conflict |
| `ERR_STEWARD_NOT_ASSIGNED` | 409 Conflict |
| `ERR_PICKUP_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_SHIFT_OVERLAP_FRIDGE` | 409 Conflict |
| `ERR_STEWARD_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_NO_PORTIONS` | 409 Conflict |
| `ERR_BUDGET_EXCEEDED` | 402 Payment Required |
