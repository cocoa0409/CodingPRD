# Community Garden Volunteer API — Product Requirements Document

## 1. Introduction

A community garden association runs its season on the labor of volunteers: individuals who register, sign liability waivers, complete orientation, claim shift slots, log harvests, borrow tools, and irrigate beds — alongside visiting school and club groups whose minors must be supervised at a fixed ratio. Today that coordination lives in spreadsheets and group chats, which makes it impossible to answer basic operational questions with confidence: Who is actually allowed to handle produce for donation? How much of the season's irrigation water is already spoken for? Which beds are free for a new crop plan, and what grew there last? Who holds the shed key?

This document specifies the Community Garden Volunteer API, the system of record for that entire operation. The API governs volunteer onboarding and standing, training certifications, the season lifecycle, garden beds and crop planning, shift slots with waitlist promotion, group bookings with youth-supervision enforcement, tool and shed-key stewardship, harvest logging with a fixed volunteer/donation split, donation recipients with weekly capacity, and irrigation scheduling against a season water budget. Because many of these resources are finite and contended — bed square footage, slot capacity, a four-key shed registry, a season's water budget — the design leans on explicit state machines, derived counters that the server recomputes on every mutation, optimistic concurrency on the few writes that debit shared budgets, and automatic transitions driven by a logical clock that the association's administrators control during testing and operations.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` header, identifying the acting user, and the `X-User-Role` header, declaring the operational capacity in which they act. The system recognizes exactly five roles: `GardenAdmin`, `Coordinator`, `Volunteer`, `GroupLeader`, and `FoodSafetyOfficer`. A request that is missing either header, or whose role value is not one of these five names, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400). A request whose role is well-formed but not authorized for the target operation — including the per-transition actor restrictions on shared transition endpoints — is rejected with `ERR_FORBIDDEN_ROLE` (403).

Identity is bound differently per role. When `X-User-Role` is `Coordinator`, `Volunteer`, `GroupLeader`, or `FoodSafetyOfficer`, `X-User-ID` is the `id` of the acting Volunteer; ownership checks on any resource that references a Volunteer compare the resource's foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_VIOLATION` (403). When `X-User-Role` is `GardenAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it, but it never compares it to any entity's `id`. Because an opaque identifier can never equal a Volunteer's `id`, segregation-of-duties identity comparisons always pass for a `GardenAdmin` caller.

The roles divide labor as follows. A `GardenAdmin` is the association's administrator and holds exclusive control over the logical clock, the scheduler epoch run, season creation, configuration edits, and lifecycle transitions, manual standing transitions, shed-key registration, tool-pool retirement, and donation-recipient administration. A `Coordinator` is a volunteer coordinator — itself a registered Volunteer — and is the only role besides `GardenAdmin` permitted to confirm shift signups, restore tools from maintenance, log irrigation meter readings, and create donation split proposals. A `Volunteer` acts only on its own records: its own signups, tool checkouts, harvest logs, crop-plan proposals, and its own waiver. A `GroupLeader` is a Volunteer who leads an external organization and adds the ability to create and manage its own group bookings; otherwise it shares the Volunteer self-service surface. A `FoodSafetyOfficer` is a produce-safety authority — again a registered Volunteer — that issues and revokes training certifications, verifies or rejects harvest logs, and approves or rejects donation allocations; segregation-of-duties rules bar it from verifying or approving harvests it logged itself and from issuing a certification to itself.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope. List endpoints also accept optional field-matching filters: volunteers filter by `standing`, `waiver_status`, and `orientation_status`; certifications by `volunteer_id`, `cert_type`, and `status`; seasons by `status`; beds by `status` and `irrigation_zone`; crop plans by `season_id`, `bed_id`, `proposer_volunteer_id`, and `status`; shift slots by `season_id`, `task_type`, and `status`; signups by `slot_id`, `volunteer_id`, `status`, and `supervision_adult_signup_id`; group bookings by `slot_id`, `leader_volunteer_id`, and `status`; shed keys by `status` and `current_holder_volunteer_id`; tools by `category` and `status`; tool checkouts by `tool_id`, `volunteer_id`, `signup_id`, and `status`; harvest logs by `season_id`, `bed_id`, `logged_by_volunteer_id`, `status`, and `crop_plan_id`; donation recipients by `active`; donation allocations by `harvest_log_id`, `recipient_id`, and `status`; and irrigation schedules by `season_id`, `zone`, and `status`.

### 2.4. Common Resource Properties

Every resource in the system — volunteers, certifications, seasons, beds, crop plans, shift slots, signups, group bookings, shed keys, tool items, tool checkouts, harvest logs, donation recipients, donation allocations, and irrigation schedules — carries the same four system-managed properties:

- `id` (string): a unique, server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits (for example, `2026-08-01T09:15:00.123Z`), set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at its initial value on creation and increments by exactly one on every mutation of the resource, including state transitions and server-side recomputation of derived fields.

Every transition described in §3 increments the acting entity's `version` by one and refreshes its `updated_at`. Where a transition's side effects also mutate a second entity — for example, a crop-plan approval that changes the bed's allocated area, or a meter reading that changes the season's water counters — that second entity's `version` increments by one and its `updated_at` refreshes as well; each such cross-entity increment is called out in the workflow narrative where it occurs.

### 2.5. The Logical Clock and Scheduled Transitions

All time-dependent behavior in the system is evaluated against a **logical clock**, never against the host's wall clock. Before any administrator call, the clock's startup value is exactly `2026-08-01T00:00:00Z`; the server never falls back to wall-clock time under any circumstance. A `GardenAdmin` may set the logical clock through a test-driving capability that accepts a `to_iso8601` instant and responds with the resulting `current_utc`. Age derivation, waiver expiry, certification expiry, key overdue detection, slot locking, and irrigation window progression all read this clock.

A second administrator-only capability, the **scheduler epoch run**, applies every time-based automatic transition as of the current logical clock and responds with a `transitioned_counts` object summarizing what moved. One epoch run evaluates all of the following:

- A training certification in `ACTIVE` whose `expires_at` has been reached (the clock is at or past `expires_at`) moves to `EXPIRED`, and the subject volunteer's derived credential flags are recomputed.
- A volunteer waiver in `SIGNED` moves to `EXPIRED` once the clock is strictly more than 365 days past its `waiver_signed_at`.
- A shed key in `CHECKED_OUT` moves to `OVERDUE` once the clock is strictly past its `due_back_at`.
- A shift slot in `OPEN` or `FULL` moves to `LOCKED` once the clock reaches 24 hours before its `starts_at`.
- An irrigation schedule in `SCHEDULED` moves to `DUE` once the clock is at or after its `planned_start_at` and not after its `planned_end_at`.
- An irrigation schedule in `SCHEDULED` or `DUE` moves to `MISSED` once the clock is strictly past its `planned_end_at` and no meter reading has been logged.

Each automatic transition is a real mutation: the affected entity's `version` increments and its `updated_at` refreshes.

### 2.6. Validation Order and Error Precedence

When several checks could reject the same request, the server evaluates them in a fixed global order and reports the first failure encountered — first match wins. The tiers, from earliest to latest, are:

1. **Authentication context.** Both headers are present and the role is one of the five declared names, otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Role authorization.** The caller's role is listed for the endpoint and for the specific transition requested, otherwise `ERR_FORBIDDEN_ROLE` (403).
3. **Existence.** Path identifiers are validated left to right, and then every foreign-key reference in the request body — `volunteer_id`, `slot_id`, `bed_id`, `season_id`, `tool_id`, the recipient ids inside `lines`, `supervision_adult_signup_id`, `signup_id`, `harvest_log_id`, `crop_plan_id`, `holder_volunteer_id`, `proposer_volunteer_id`, `logged_by_volunteer_id`, `leader_volunteer_id` — otherwise the referenced entity's not-found error (404), such as `ERR_VOLUNTEER_NOT_FOUND`, `ERR_SHIFT_SLOT_NOT_FOUND`, or `ERR_RECIPIENT_NOT_FOUND`.
4. **Ownership and segregation of duties.** Self-service callers (`Volunteer`, `GroupLeader`, and `FoodSafetyOfficer` acting on their own behalf) may only act on their own records, otherwise `ERR_OWNERSHIP_VIOLATION` (403); the harvest verifier and the allocation approver must not be the harvest's logger, and a certification's issuer must not be its subject, otherwise `ERR_SEGREGATION_OF_DUTIES` (403).
5. **Request shape.** Required fields are present, types are correct, enum values are valid members, and ranges hold — an end strictly after its start for dates and times, `minor_count` not exceeding `member_count`, `capacity_youth` not exceeding `capacity_total`, quantities strictly positive where required, and non-empty `rejection_reason`, `remediation_note`, and `revoked_reason` where those are required — otherwise `ERR_INVALID_REQUEST` (400).
6. **From-state.** The target entity is in the from-state its transition requires, otherwise the entity-specific state error (409) — `ERR_INVALID_VOLUNTEER_STATE`, `ERR_INVALID_CERTIFICATION_STATE`, `ERR_INVALID_SEASON_STATE`, `ERR_INVALID_BED_STATE`, `ERR_INVALID_CROP_PLAN_STATE`, `ERR_INVALID_SLOT_STATE`, `ERR_INVALID_SIGNUP_STATE`, `ERR_INVALID_GROUP_STATE`, `ERR_INVALID_KEY_STATE`, `ERR_INVALID_TOOL_STATE`, `ERR_INVALID_CHECKOUT_STATE`, `ERR_INVALID_HARVEST_STATE`, `ERR_INVALID_ALLOCATION_STATE`, or `ERR_INVALID_IRRIGATION_STATE`.
7. **Cross-entity state guards.** The referenced season, bed, slot, or harvest log is in a status that accepts the operation, otherwise the guard-specific 409 error (`ERR_SEASON_NOT_ACCEPTING`, `ERR_BED_NOT_AVAILABLE`, `ERR_BED_NOT_HARVEST_OPEN`, `ERR_HARVEST_LOG_NOT_VERIFIED`, or a season-level guard such as `ERR_CROP_PLANS_UNRESOLVED`).
8. **Participation gates**, evaluated in a fixed sub-order: orientation first (`ERR_ORIENTATION_REQUIRED`), then waiver (`ERR_WAIVER_REQUIRED`), then standing not `SUSPENDED` (`ERR_VOLUNTEER_SUSPENDED`); shed-key checkout additionally requires standing exactly `GOOD` (`ERR_VOLUNTEER_NOT_IN_GOOD_STANDING`).
9. **Certification gates.** `ERR_PRODUCE_SAFETY_CERT_REQUIRED`, `ERR_TOOL_CERT_REQUIRED`, and `ERR_SAFETY_ATTESTATION_REQUIRED` (409).
10. **Youth supervision.** `ERR_YOUTH_SUPERVISION_REQUIRED` and `ERR_SUPERVISION_RATIO_VIOLATION` (409).
11. **Uniqueness.** `ERR_EMAIL_TAKEN`, `ERR_BED_CODE_TAKEN`, `ERR_KEY_CODE_TAKEN`, `ERR_DUPLICATE_SIGNUP`, `ERR_DUPLICATE_ACTIVE_CERT`, and `ERR_DUPLICATE_ACTIVE_ALLOCATION` (409).
12. **Referential state.** `ERR_CROP_ROTATION_VIOLATION`, `ERR_RECIPIENT_INACTIVE`, `ERR_RECIPIENT_GRADE_RESTRICTED`, `ERR_INVALID_TOOL_STATE`, and `ERR_SIGNUP_NOT_ELIGIBLE` (409).
13. **Temporal windows.** `ERR_OUTSIDE_SEASON_WINDOW`, `ERR_SLOT_LOCKED`, `ERR_OUTSIDE_CHECKIN_WINDOW`, `ERR_HARVEST_IN_FUTURE`, `ERR_IRRIGATION_OVERLAP`, `ERR_BED_OCCUPANCY_OVERLAP`, and `ERR_BED_REST_PERIOD_ACTIVE` (409).
14. **Capacity and quota.** `ERR_SLOT_CAPACITY_EXCEEDED`, `ERR_YOUTH_CAPACITY_EXCEEDED`, `ERR_BED_CAPACITY_EXCEEDED`, `ERR_KEY_LIMIT_EXCEEDED`, `ERR_KEY_REGISTRY_FULL`, `ERR_TOOL_INSUFFICIENT_STOCK`, and `ERR_RECIPIENT_CAPACITY_EXCEEDED` (409).
15. **Water budget.** `ERR_WATER_BUDGET_EXCEEDED` (409).
16. **Split integrity.** `ERR_SPLIT_MISMATCH` (409).
17. **Optimistic concurrency.** A stale `expected_season_version` or `expected_slot_version` is rejected with `ERR_STALE_VERSION` (412).

Sections 3.5, 3.6, 3.8, and 3.9 restate the gates of the major creation workflows in the sequence those workflows apply them; for those operations, the per-workflow sequence refines this catalogue, and every gate listed there maps to one of the tiers above.

### 2.7. Optimistic Concurrency Control

Three write operations carry an optimistic-concurrency obligation, and each names its expectation field explicitly:

- Creating an irrigation schedule (`POST /api/irrigation-schedules`) requires the request to carry `expected_season_version`, the client last-observed `version` of the target Season. If the season's current `version` has advanced past that value — because another write, such as an earlier schedule creation, a meter logging, a cancellation, or a configuration edit, already debited or rebalanced the season's water ledger — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the season before retrying. A writer holding a stale season view would otherwise budget-check against `water_committed_gallons` and `water_actual_gallons` values that no longer hold.
- Patching a season's configuration (`PATCH /api/seasons/{seasonId}`) requires `expected_season_version` matching the season's current `version`. Because two successive configuration edits are each individually legitimate, the second edit's view is stale once the first has advanced the season's `version`; it fails with `ERR_STALE_VERSION` (HTTP 412) and must re-read before retrying.
- Patching a shift slot (`PATCH /api/shift-slots/{slotId}`) requires `expected_slot_version` matching the slot's current `version`. Automatic `OPEN`/`FULL` flips and signup cascades advance a slot's `version` between a client's read and its patch; a stale patch is refused with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version-expectation field; endpoints not listed here process mutations without an OCC check.

### 2.8. Participation Gates, Ownership, and Segregation of Duties

Five operations — creating a shift signup, creating a group booking, creating a harvest log, creating a tool checkout, and checking out a shed key — are gated on the participating volunteer's standing in the program. The gates are evaluated in a fixed sub-order: the volunteer's `orientation_status` must be `ORIENTED` (otherwise `ERR_ORIENTATION_REQUIRED`), then `waiver_status` must be `SIGNED` (otherwise `ERR_WAIVER_REQUIRED`, which covers both `UNSIGNED` and `EXPIRED`), then `standing` must not be `SUSPENDED` (otherwise `ERR_VOLUNTEER_SUSPENDED`). Shed-key checkout is stricter: the prospective holder's `standing` must be exactly `GOOD`, so a volunteer on `PROBATION` is refused with `ERR_VOLUNTEER_NOT_IN_GOOD_STANDING`. The volunteer evaluated is always the participating volunteer named by the request — the signup's `volunteer_id`, the booking's `leader_volunteer_id`, the harvest log's `logged_by_volunteer_id`, the checkout's `volunteer_id`, or the key's `holder_volunteer_id` — which need not be the caller when staff act on a volunteer's behalf.

Ownership binds self-service callers to their own records wherever §3 says "ownership applies": a `Volunteer` or `GroupLeader` caller must be the signup's `volunteer_id`, the booking's `leader_volunteer_id`, the checkout's `volunteer_id`, the harvest log's `logged_by_volunteer_id`, or the crop plan's `proposer_volunteer_id`, and may sign only their own waiver. Violations are rejected with `ERR_OWNERSHIP_VIOLATION` (403).

Segregation of duties separates the person who performs work from the person who certifies it. The caller verifying a harvest log must not be the log's `logged_by_volunteer_id`; the caller approving a donation allocation must not be the harvest log's logger; and a certification's issuer must not be its subject. Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). Because a `GardenAdmin` identity is opaque, it can never coincide with a volunteer `id`, so these comparisons always pass for administrators.

### 2.9. Units, Precision, and Rounding

The system keeps every quantity in integer units, with domain-specific rounding where a division or fraction is involved:

- **Water** is measured in whole gallons with no rounding anywhere: budgets, planned and actual gallons, and the committed, actual, and remaining counters are all integers.
- **Service credit** is measured in whole minutes. Actual elapsed time between check-in and check-out is truncated to whole minutes (partial minutes are dropped), and all credited-minute values are integers.
- **People** — slot capacities, occupancy pools, booking sizes, chaperone counts — are integer persons. The supervision ratio divides minors by 8 and rounds up to a whole chaperone.
- **Harvest weight and donation grams** are integer grams. The volunteer share of a harvest is rounded down to a whole gram, and allocation line amounts are absolute integers that are never rounded.
- **Bed area** is measured in integer square feet.
- **Bed occupancy** is compared in whole days, including the 14-day cover-crop buffer. **Irrigation windows** are compared at second precision on their instants.

### 2.10. Cross-Entity Consistency and Cascading Transitions

Resource identifiers in this API are flat — every resource is addressed by a single id — but existence checks are still ordered: path identifiers are resolved first, then the foreign keys in the request body, and the request is rejected with the not-found error of the first reference that does not exist. A reference to a missing season yields `ERR_SEASON_NOT_FOUND`, a missing bed `ERR_BED_NOT_FOUND`, a missing crop plan `ERR_CROP_PLAN_NOT_FOUND`, a missing slot `ERR_SHIFT_SLOT_NOT_FOUND`, a missing signup `ERR_SIGNUP_NOT_FOUND`, a missing booking `ERR_GROUP_BOOKING_NOT_FOUND`, a missing key `ERR_SHED_KEY_NOT_FOUND`, a missing tool `ERR_TOOL_NOT_FOUND`, a missing checkout `ERR_TOOL_CHECKOUT_NOT_FOUND`, a missing harvest log `ERR_HARVEST_LOG_NOT_FOUND`, a missing recipient `ERR_RECIPIENT_NOT_FOUND`, a missing allocation `ERR_ALLOCATION_NOT_FOUND`, a missing irrigation schedule `ERR_IRRIGATION_SCHEDULE_NOT_FOUND`, a missing certification `ERR_CERTIFICATION_NOT_FOUND`, and a missing volunteer `ERR_VOLUNTEER_NOT_FOUND`.

Derived counters — bed `allocated_sq_ft`, slot `confirmed_count` and `confirmed_youth_count`, tool stock counts, season water counters, recipient weekly commitments, volunteer service and no-show totals — are maintained by the server on every mutation that affects them; clients never write them directly. When a parent or sibling resource undergoes a transition that invalidates dependent work, the server cascades the dependent entities to their own resolution states in the same operation rather than leaving them stranded: cancelling a season cancels its slots, plans, and schedules; completing a slot converts no-shows; suspending a volunteer cancels their upcoming signups. Each cascade, including which states it touches and which it spares, is specified in §3 alongside the transition that triggers it.

## 3. Business Logic & Workflows

### 3.1. Volunteer Registration, Orientation, Waiver, and Standing

A `GardenAdmin` or `Coordinator` registers a new volunteer by supplying the volunteer's `full_name`, `email`, and `date_of_birth`, with an optional `phone` that is stored as null when omitted. The `email` must be unique across all volunteers; a duplicate registration is rejected with `ERR_EMAIL_TAKEN`. At registration the server derives `is_minor` from `date_of_birth` against the current logical clock: the flag is true while the volunteer's age is under eighteen and flips to false on the eighteenth birthday. Every new volunteer begins with `orientation_status` `PENDING`, `waiver_status` `UNSIGNED`, `waiver_signed_at` null, and `standing` `GOOD`.

Orientation is a one-way door. A `GardenAdmin` or `Coordinator` marks orientation completed, moving `orientation_status` from `PENDING` to `ORIENTED`; invoking the completion on a volunteer who is already `ORIENTED` is rejected with `ERR_INVALID_VOLUNTEER_STATE`.

The liability waiver cycles between `SIGNED` and expired states. Signing — which all five roles may invoke, though a `Volunteer`, `GroupLeader`, or `FoodSafetyOfficer` caller may sign only their own record (otherwise `ERR_OWNERSHIP_VIOLATION`) — moves `waiver_status` from `UNSIGNED` to `SIGNED` and stamps `waiver_signed_at` with the current logical clock. The same signing action also serves as renewal: a volunteer whose waiver is `EXPIRED` signs again and returns to `SIGNED`, with `waiver_signed_at` refreshed. Attempting to sign while already `SIGNED` is rejected with `ERR_INVALID_VOLUNTEER_STATE`. A waiver does not last forever: once the logical clock passes `waiver_signed_at` by more than 365 days, the next scheduler epoch run moves `waiver_status` from `SIGNED` to `EXPIRED`, and the volunteer must renew before participating again.

Standing governs whether a volunteer may participate at all and is managed by a `GardenAdmin` through a standing-update action carrying a `to_state`. A volunteer in `GOOD` standing may be moved to `PROBATION` or directly to `SUSPENDED`; a volunteer in `PROBATION` may be moved to `SUSPENDED` or reinstated to `GOOD`; a volunteer in `SUSPENDED` may be reinstated to `GOOD`. Each manual move requires the named from-state, and a mismatch is rejected with `ERR_INVALID_VOLUNTEER_STATE`. Standing also moves on its own: the moment a volunteer's `no_show_count` — the count of their signups in `NO_SHOW` — becomes at least 3 while their standing is `GOOD`, the standing drops to `PROBATION` automatically. The boundary is exact: the third no-show triggers the drop, the second does not. `PROBATION` never auto-reverts; reinstatement is always a manual act.

Suspension is the heavy hammer because of what it cascades. Moving a volunteer to `SUSPENDED` cancels every one of their shift signups currently in `REQUESTED` or `CONFIRMED`. For each cancelled signup that had been `CONFIRMED`, the freed spot triggers the waitlist promotion selection on that slot (§3.5): the earliest-positioned `WAITLISTED` signup that fits both occupancy pools is promoted to `CONFIRMED`, and a `FULL` slot that yields no eligible candidate reopens to `OPEN` — flipping back to `FULL` if a promotion fills the freed spot. Signups cancelled by this cascade carry no no-show penalty.

Three counters summarize a volunteer's history and are recomputed by the server as events occur: `total_service_minutes` accumulates credited minutes across their signups (§3.5), `no_show_count` tallies their `NO_SHOW` signups, and `held_key_count` counts the shed keys currently in their keeping (§3.7).

### 3.2. Training Certifications and Credential Flags

Certifications record that a volunteer has completed a training track. A `GardenAdmin` or `FoodSafetyOfficer` issues one by naming the subject `volunteer_id`, a `cert_type` of `PRODUCE_SAFETY`, `SUPERVISION`, or `TOOL_SAFETY`, and an `expires_at` instant. The expiry must be strictly after the issuance clock time, otherwise the request fails shape validation with `ERR_INVALID_REQUEST`. Segregation of duties forbids self-issuance: the issuer's identity must differ from the subject's, otherwise `ERR_SEGREGATION_OF_DUTIES`. A volunteer may hold at most one `ACTIVE` certification of each `cert_type`; issuing a second live certification of a type the volunteer already holds is rejected with `ERR_DUPLICATE_ACTIVE_CERT`. On issuance the server stamps `issued_at` with the current logical clock, sets the certification `status` to `ACTIVE`, and leaves `revoked_reason` null.

Three derived flags on the Volunteer record summarize its live credentials. `can_supervise` is true exactly when the volunteer holds a certification with `cert_type` `SUPERVISION` in `ACTIVE` status; `produce_safety_certified` and `tool_safety_certified` follow the same pattern for `PRODUCE_SAFETY` and `TOOL_SAFETY` respectively. The server recomputes these flags whenever a certification of the subject is issued, expires, or is revoked.

Certifications end in one of two terminal states, `EXPIRED` or `REVOKED`. Expiry is automatic: when the logical clock reaches a certification's `expires_at`, the next epoch run moves it from `ACTIVE` to `EXPIRED` and recomputes the subject's flags. Revocation is a deliberate act by a `GardenAdmin` or `FoodSafetyOfficer` carrying a non-empty `revoked_reason` (an empty or missing reason fails with `ERR_INVALID_REQUEST`); only an `ACTIVE` certification may be revoked, otherwise `ERR_INVALID_CERTIFICATION_STATE`. Revocation recomputes the subject's flags and carries one further cascade: when the revoked certification's `cert_type` is `PRODUCE_SAFETY`, every harvest log the subject still has in `SUBMITTED` falls back to `DRAFT`, because those logs now require re-verification against a valid credential (§3.8).

### 3.3. Season Lifecycle and the Water Ledger

A `GardenAdmin` opens planning by creating a season with a `name`, the enrollment window `signup_opens_at` and `signup_closes_at`, the operating window `season_starts_at` and `season_ends_at`, and the irrigation budget `water_budget_gallons`. The closing instant must be strictly after the opening instant, the season end strictly after the season start, and the budget strictly greater than zero gallons; violations are rejected with `ERR_INVALID_REQUEST`. The enrollment window is informational — no hard gate reads it — while the operating window bounds shifts, harvests, and irrigation. A new season starts in `DRAFT` with its water counters zeroed.

The season tracks water through three derived counters. `water_committed_gallons` is the sum of `planned_gallons` over the season's irrigation schedules in `SCHEDULED`, `DUE`, or `MISSED` — water promised but not yet metered. `water_actual_gallons` is the sum of `gallons_actual` over schedules in `LOGGED` or `RECONCILED` — water the meter has confirmed. `water_remaining_gallons` is the budget minus committed minus actual. Schedules in `CANCELLED` contribute to neither bucket. The projection gate that guards new schedules is defined in §3.9; note the deliberate divergence between the forward-looking view and the settled one: while the season runs, committed water counts unlogged plans, but once the season enters `RECONCILIATION` every still-open schedule is cascade-cancelled, committed collapses to zero, and final usage is read from `water_actual_gallons` alone — a number that diverges from the earlier projection whenever actual meter readings differ from plans.

While a season remains in `DRAFT` or `OPEN_ENROLLMENT`, a `GardenAdmin` may edit its configuration — `name`, the signup window, the season window, or `water_budget_gallons` — subject to the optimistic-concurrency rule of §2.7 (`expected_season_version` required, stale values rejected with `ERR_STALE_VERSION`). Editing a season that has advanced beyond `OPEN_ENROLLMENT` is rejected with `ERR_INVALID_SEASON_STATE`. Every successful edit increments the season's `version`.

The season lifecycle is driven entirely by a `GardenAdmin` through a transition action carrying a `to_state`, and every move is guarded:

- `DRAFT → OPEN_ENROLLMENT` requires that at least one garden bed exists whose status is not `OUT_OF_SERVICE`, otherwise `ERR_SEASON_GUARD_ACTIVE_BED_REQUIRED`.
- `OPEN_ENROLLMENT → DRAFT` (a revert) is permitted only while zero shift slots, zero crop plans, and zero irrigation schedules reference the season, otherwise `ERR_SEASON_REVERT_BLOCKED`.
- `OPEN_ENROLLMENT → PLANTING` requires at least one crop plan for the season in `APPROVED` or `PLANTED`, otherwise `ERR_CROP_PLANS_UNRESOLVED`.
- `PLANTING → GROWING` requires zero crop plans for the season in `PROPOSED` or `APPROVED` — every plan must be resolved, otherwise `ERR_CROP_PLANS_UNRESOLVED` — and cascades: every bed in `PLANTED` moves to `GROWING`.
- `GROWING → HARVESTING` requires zero irrigation schedules for the season in `DUE` or `MISSED`, otherwise `ERR_IRRIGATION_UNRESOLVED`. Two cascades follow: every bed in `GROWING` moves to `HARVEST_OPEN`, and for each bed that flips, every crop plan on that bed in `PLANTED` moves to `HARVESTING`.
- `HARVESTING → RECONCILIATION` requires zero harvest logs for the season in `SUBMITTED`, otherwise `ERR_HARVEST_LOGS_UNVERIFIED`, and zero donation allocations for the season's logs in `PENDING`, otherwise `ERR_ALLOCATIONS_PENDING`. On entry, every irrigation schedule in `SCHEDULED` or `DUE` is cascade-cancelled, freeing its committed water back into the ledger.
- `RECONCILIATION → CLOSED` requires zero irrigation schedules for the season in `SCHEDULED`, `DUE`, `MISSED`, or `LOGGED`, otherwise `ERR_IRRIGATION_UNRESOLVED`, and zero harvest logs for the season in `DRAFT`, `SUBMITTED`, or `VERIFIED`, otherwise `ERR_HARVEST_LOGS_UNVERIFIED`.
- `DRAFT`, `OPEN_ENROLLMENT`, or `PLANTING → CANCELLED` abandons the season and cascades broadly: crop plans for the season in `PROPOSED` or `APPROVED` move to `WITHDRAWN` (freeing their bed allocations), shift slots for the season in `DRAFT`, `OPEN`, or `FULL` move to `CANCELLED` (which in turn cascades to their signups, group bookings, and linked tool checkouts per §3.5), and irrigation schedules in `SCHEDULED` or `DUE` move to `CANCELLED`.

Any transition attempted from a from-state it does not allow is rejected with `ERR_INVALID_SEASON_STATE`. `CLOSED` and `CANCELLED` are terminal.

### 3.4. Garden Beds and Crop Plan Coordination

A `GardenAdmin` or `Coordinator` registers a garden bed with a `bed_code` unique across all beds (duplicates fail with `ERR_BED_CODE_TAKEN`), a `size_sq_ft` plantable area strictly greater than zero, a `sun_exposure` of `FULL`, `PARTIAL`, or `SHADE`, an `irrigation_zone` label used for irrigation overlap checks, and an optional `soil_ph` that is null when omitted. New beds start `FALLOW`, with `allocated_sq_ft` at zero, `last_plant_family` null, and `last_harvest_closed_at` null.

Beds move through their lifecycle on a transition action carrying a `to_state`, available to `GardenAdmin` and `Coordinator` except where noted:

- `FALLOW → RESERVED` requires that at least one season currently sits in `OPEN_ENROLLMENT` or `PLANTING`, otherwise `ERR_SEASON_NOT_ACCEPTING`.
- `RESERVED → PLANTED` requires at least one crop plan on this bed in `APPROVED` or `PLANTED`, otherwise `ERR_CROP_PLANS_UNRESOLVED`.
- `PLANTED → GROWING` happens either through the season cascade when the season moves `PLANTING → GROWING` or manually.
- `GROWING → HARVEST_OPEN` happens either through the season cascade when the season moves `GROWING → HARVESTING` or manually, and cascades in turn: every crop plan on the bed in `PLANTED` moves to `HARVESTING`.
- `HARVEST_OPEN → POST_HARVEST` requires zero crop plans on the bed in `APPROVED`, `PLANTED`, or `HARVESTING`, otherwise `ERR_CROP_PLANS_UNRESOLVED`; the transition stamps `last_harvest_closed_at` with the current logical clock.
- `POST_HARVEST → FALLOW` enforces the cover-crop rest: the clock must have reached `last_harvest_closed_at` plus 14 days, otherwise `ERR_BED_REST_PERIOD_ACTIVE`.
- From any state other than `OUT_OF_SERVICE`, a `GardenAdmin` may take the bed to `OUT_OF_SERVICE` (from `FALLOW`, `RESERVED`, `PLANTED`, `GROWING`, `HARVEST_OPEN`, or `POST_HARVEST`); the cascade moves crop plans on the bed in `PROPOSED` or `APPROVED` to `WITHDRAWN`, freeing their allocated area.
- `OUT_OF_SERVICE → FALLOW` is a `GardenAdmin`-only remediation that requires a non-empty `remediation_note`, otherwise `ERR_INVALID_REQUEST`.

A transition attempted from a disallowed from-state is rejected with `ERR_INVALID_BED_STATE`.

Against this bed lifecycle, volunteers plan crops. A `GardenAdmin`, `Coordinator`, `Volunteer`, or `GroupLeader` proposes a crop plan with `season_id`, `bed_id`, `proposer_volunteer_id`, `crop_type`, `plant_family`, `requested_sq_ft` (strictly greater than zero), `planned_start_date`, `planned_end_date` (strictly after the start date), and an optional `expected_yield_grams` estimate that defaults to 0 and may not be negative. Creation is gated: the season must be in `OPEN_ENROLLMENT` or `PLANTING` (otherwise `ERR_SEASON_NOT_ACCEPTING`), the bed must not be `OUT_OF_SERVICE` (otherwise `ERR_BED_NOT_AVAILABLE`), and a `Volunteer` or `GroupLeader` caller may propose only as themselves — the `proposer_volunteer_id` must equal their identity, otherwise `ERR_OWNERSHIP_VIOLATION`. A new plan starts `PROPOSED` with `rejection_reason` null.

Approval is the allocation moment, performed by a `GardenAdmin` or `Coordinator`, and it runs six checks: the plan is `PROPOSED` (otherwise `ERR_INVALID_CROP_PLAN_STATE`); the season is in `OPEN_ENROLLMENT` or `PLANTING` (otherwise `ERR_SEASON_NOT_ACCEPTING`); the bed is in `FALLOW` or `RESERVED` (otherwise `ERR_BED_NOT_AVAILABLE`); the area fits — the bed's `allocated_sq_ft`, being the sum of `requested_sq_ft` over the bed's plans in `APPROVED`, `PLANTED`, or `HARVESTING`, plus the candidate's `requested_sq_ft`, must not exceed the bed's `size_sq_ft`, with an exact fit allowed and one square foot over failing with `ERR_BED_CAPACITY_EXCEEDED`; the occupancy windows clear — two plans on the same bed, both in `APPROVED`, `PLANTED`, or `HARVESTING`, conflict unless one plan's `planned_end_date` plus a mandatory 14-day cover-crop buffer falls strictly before the other's `planned_start_date`, in either order, and adjacency is forbidden so a plan starting exactly fourteen days after another's end still conflicts, failing with `ERR_BED_OCCUPANCY_OVERLAP`; and the rotation check passes — the candidate's `plant_family` must differ from the bed's `last_plant_family`, otherwise `ERR_CROP_ROTATION_VIOLATION`. Approving writes the allocation: the bed's `allocated_sq_ft` rises by the plan's `requested_sq_ft`, and both the plan's and the bed's `version` increment.

The rotation anchor, `last_plant_family`, is the `plant_family` of the most recent crop plan on the bed to reach `COMPLETE`, and it is null until the first plan completes — a bed that has never completed a plan imposes no rotation constraint.

Rejection and resubmission form a loop. A `GardenAdmin` or `Coordinator` rejects a `PROPOSED` plan with a non-empty `rejection_reason` (an empty reason fails with `ERR_INVALID_REQUEST`), which is recorded on the plan. A `REJECTED` plan may be resubmitted to `PROPOSED` by staff or by the proposing volunteer (ownership applies, otherwise `ERR_OWNERSHIP_VIOLATION`); resubmission clears `rejection_reason` to null and may apply updated `requested_sq_ft`, `planned_start_date`, `planned_end_date`, `crop_type`, or `plant_family` supplied with the request.

Once approved, planting is a physical-world confirmation. Moving a plan from `APPROVED` to `PLANTED` is open to staff and to the proposer (ownership applies), requires the season to be in `PLANTING` (otherwise `ERR_SEASON_NOT_ACCEPTING`), and requires the bed to be in `RESERVED` or `PLANTED` (otherwise `ERR_BED_NOT_AVAILABLE`). From `PLANTED`, the only way forward is the system cascade: when the bed moves `GROWING → HARVEST_OPEN`, its `PLANTED` plans move to `HARVESTING`.

Completion closes the loop. A `GardenAdmin` or `Coordinator` moves a `HARVESTING` plan to `COMPLETE`; the plan's `plant_family` is written to the bed's `last_plant_family`, the bed's `allocated_sq_ft` falls by the plan's `requested_sq_ft`, and both entities' `version` increment.

Withdrawal releases a plan before completion, manually by staff or the proposer (ownership applies), or automatically when the season is cancelled or the bed goes `OUT_OF_SERVICE`. The two branches differ in their bookkeeping: withdrawing from `APPROVED` releases the allocation — the bed's `allocated_sq_ft` falls by `requested_sq_ft` and the bed's `version` increments — while withdrawing from `PROPOSED` frees nothing because no area was ever allocated. The manual move requires the plan to be in `PROPOSED` or `APPROVED`, otherwise `ERR_INVALID_CROP_PLAN_STATE`. `COMPLETE` and `WITHDRAWN` are terminal; `REJECTED` is not, since resubmission reopens it.

### 3.5. Shift Slots, Signups, and Waitlist Promotion

Work happens against shift slots. A `GardenAdmin` or `Coordinator` creates a slot with a `season_id`, a `task_type` of `PLANTING`, `WEEDING`, `HARVEST`, `IRRIGATION`, `COMPOST`, `REPAIR`, or `OUTREACH`, a `starts_at` and `ends_at` (the end strictly after the start), a `capacity_total` strictly greater than zero, a `capacity_youth` that is non-negative and no larger than `capacity_total` (range violations fail with `ERR_INVALID_REQUEST`), and three optional declarations: `requires_produce_safety` (default false), and `required_tool_id` with `required_tool_qty` (defaults null and 0), which declare the tool and per-signup quantity each confirmed participant is expected to have. Both `starts_at` and `ends_at` must lie within the season's operating window from `season_starts_at` to `season_ends_at`, otherwise `ERR_OUTSIDE_SEASON_WINDOW`. A new slot starts in `DRAFT` with all occupancy counters at zero and `next_waitlist_position` at 1.

While a slot is in `DRAFT` or `OPEN`, a `GardenAdmin` or `Coordinator` may edit its `capacity_total`, `capacity_youth`, `starts_at`, or `ends_at`, subject to the optimistic-concurrency rule of §2.7 (`expected_slot_version` required, stale values rejected with `ERR_STALE_VERSION`); editing a slot in any later status is rejected with `ERR_INVALID_SLOT_STATE`. After a capacity change the server re-evaluates the `OPEN`/`FULL` determination against the updated capacity, and the edit increments the slot's `version`.

The slot lifecycle mixes manual and automatic moves:

- `DRAFT → OPEN`, by a `GardenAdmin` or `Coordinator`, requires the season to be in `OPEN_ENROLLMENT`, `PLANTING`, `GROWING`, or `HARVESTING`, otherwise `ERR_SEASON_NOT_ACCEPTING`.
- `OPEN → FULL` is automatic: the moment `confirmed_count` reaches `capacity_total`, the slot fills.
- `FULL → OPEN` is automatic in the other direction: when a cancellation frees a spot and the waitlist promotion selection finds no eligible candidate, the slot reopens.
- `OPEN` or `FULL → LOCKED` happens automatically at the epoch run once the clock reaches 24 hours before `starts_at`, and a `GardenAdmin` or `Coordinator` may also lock a slot manually from `OPEN` or `FULL`.
- `LOCKED → COMPLETED`, by a `GardenAdmin` or `Coordinator`, is blocked while any signup on the slot remains `CHECKED_IN` — everyone must be checked out first, otherwise `ERR_SIGNUPS_STILL_CHECKED_IN`. Completion cascades: every signup still `CONFIRMED` becomes `NO_SHOW`, incrementing its volunteer's `no_show_count` by one, and each volunteer whose count thereby reaches 3 while in `GOOD` standing drops to `PROBATION`; group bookings on the slot in `CHECKED_IN` become `COMPLETED`, while bookings still `CONFIRMED` become `CANCELLED`.
- `DRAFT`, `OPEN`, or `FULL → CANCELLED`, manually by a `GardenAdmin` or `Coordinator` or through the season-cancellation cascade. Cancellation cascades: signups in `REQUESTED`, `CONFIRMED`, or `WAITLISTED` become `CANCELLED` with no no-show penalty, and group bookings in `REQUESTED` or `CONFIRMED` become `CANCELLED`; then, for each cancelled signup, any of its tool checkouts in `OPEN` that were linked through `signup_id` become `AUTO_CLOSED`, and for each auto-closed checkout the tool's counts are recomputed — `checked_out_count` falls by the outstanding units and `available_count` rises by the same amount.

Any transition from a disallowed from-state is rejected with `ERR_INVALID_SLOT_STATE`, and `COMPLETED` and `CANCELLED` are terminal.

Occupancy is a two-pool system the server derives continuously. A slot's `confirmed_count` is the number of its signups in `CONFIRMED` or `CHECKED_IN` — each counting one — plus the sum of `member_count` over its group bookings in `CONFIRMED` or `CHECKED_IN`. Its `confirmed_youth_count` is the number of those signups whose `is_youth` is true plus the sum of `minor_count` over those bookings. The `waitlist_count` is the number of signups in `WAITLISTED`. Signups in `REQUESTED` or `WAITLISTED` occupy nothing in either pool. A slot is `FULL` exactly when `confirmed_count` equals `capacity_total`.

A volunteer joins a slot through a signup created by a `GardenAdmin`, `Coordinator`, or the volunteer themselves (`Volunteer` and `GroupLeader` callers must sign up themselves — `volunteer_id` must equal their identity, otherwise `ERR_OWNERSHIP_VIOLATION`) with a `slot_id`, a `volunteer_id`, and, for minors, a `supervision_adult_signup_id`. Creation applies its gates in sequence: the slot must be in `OPEN` or `FULL` (otherwise `ERR_INVALID_SLOT_STATE`); the clock must still be earlier than 24 hours before `starts_at` (otherwise `ERR_SLOT_LOCKED`); the volunteer must pass the participation gates of §2.8 — `ORIENTED` (otherwise `ERR_ORIENTATION_REQUIRED`), waiver `SIGNED` (otherwise `ERR_WAIVER_REQUIRED`), not `SUSPENDED` (otherwise `ERR_VOLUNTEER_SUSPENDED`); when the slot's `requires_produce_safety` is true the volunteer must hold an `ACTIVE` `PRODUCE_SAFETY` certification (otherwise `ERR_PRODUCE_SAFETY_CERT_REQUIRED`); a minor — the signup snapshots `is_youth` from the volunteer's `is_minor` at creation — must name a `supervision_adult_signup_id` that references a signup on the same slot in `CONFIRMED` or `CHECKED_IN` whose volunteer `can_supervise` (otherwise `ERR_YOUTH_SUPERVISION_REQUIRED`); and the volunteer may hold only one non-terminal signup per slot (otherwise `ERR_DUPLICATE_SIGNUP`). A new signup starts `REQUESTED`, with `waitlist_position`, `checked_in_at`, and `checked_out_at` all null.

Confirmation is the staff decision, by a `GardenAdmin` or `Coordinator`, and it re-runs the structural gates: the signup is `REQUESTED` (otherwise `ERR_INVALID_SIGNUP_STATE`), the slot is `OPEN` or `FULL` (otherwise `ERR_INVALID_SLOT_STATE`), the clock is earlier than 24 hours before `starts_at` (otherwise `ERR_SLOT_LOCKED`), and a youth signup's supervising adult is still valid (otherwise `ERR_YOUTH_SUPERVISION_REQUIRED`). Then one of two branches fires. When both pools fit — `confirmed_count` plus one does not exceed `capacity_total`, and for a youth signup `confirmed_youth_count` plus one does not exceed `capacity_youth` — the signup becomes `CONFIRMED`, both pools increment accordingly, and the slot flips from `OPEN` to `FULL` when the total reaches capacity. When there is no room, the signup does not fail; it becomes `WAITLISTED` instead, receiving `waitlist_position` from the slot's `next_waitlist_position` — a per-slot monotonic counter that starts at 1 and increments with each assignment — while the slot stays `FULL` and its `waitlist_count` grows by one.

Promotion fills freed spots without staff involvement. Whenever a `CONFIRMED` spot is freed — by any cancellation, including the slot-independent suspension cascade of §3.1 — the server scans the slot's `WAITLISTED` signups in ascending `waitlist_position` (positions are unique per slot, so no tie-break is ever needed) and promotes the first candidate that satisfies both pool constraints: `confirmed_count` plus one within `capacity_total`, and, for a youth candidate, `confirmed_youth_count` plus one within `capacity_youth`. The promoted signup becomes `CONFIRMED`, its `waitlist_position` returns to null, and the slot flips `OPEN → FULL` if the promotion fills it. When no waitlisted candidate is eligible — or none exists — no promotion occurs and a `FULL` slot falls back to `OPEN`.

Cancellation releases a signup, manually by staff or by the signup's own volunteer (ownership applies, otherwise `ERR_OWNERSHIP_VIOLATION`), or automatically when the slot is cancelled or the volunteer is suspended. From `REQUESTED` or `WAITLISTED` the manual move simply cancels, clearing `waitlist_position` if one was set. From `CONFIRMED` the manual move additionally requires the clock to be earlier than 24 hours before `starts_at` (otherwise `ERR_SLOT_LOCKED`), and it frees the spot: `confirmed_count` falls by one — and `confirmed_youth_count` too when the cancelled signup was a youth — the promotion selection runs on the freed spot, and the slot moves `FULL → OPEN` when promotion finds no eligible candidate. Cancellation carries one supervision-loss cascade: if the cancelled signup is named as the `supervision_adult_signup_id` of youth signups on the same slot in `REQUESTED` or `CONFIRMED`, those youth signups are themselves cancelled, since their supervision guarantee has evaporated. A manual cancel from a state outside `REQUESTED`, `WAITLISTED`, or `CONFIRMED` is rejected with `ERR_INVALID_SIGNUP_STATE`.

Check-in and check-out turn attendance into service credit. Checking in — by staff or the volunteer themselves (ownership applies) — requires the signup to be `CONFIRMED` and the clock to fall within the window from 30 minutes before `starts_at` through `ends_at`; outside that window the attempt is rejected with `ERR_OUTSIDE_CHECKIN_WINDOW`. Check-in stamps `checked_in_at` and assigns a provisional `credited_minutes` equal to the slot's scheduled length — the whole-minute difference between `ends_at` and `starts_at` — and the volunteer's `total_service_minutes` is recomputed. Checking out requires the signup to be `CHECKED_IN`, stamps `checked_out_at`, and finalizes the credit: the actual elapsed time between `checked_in_at` and `checked_out_at`, truncated to whole minutes, is compared against the scheduled length plus a 30-minute grace, and the final `credited_minutes` is the lesser of the two, never below zero. The volunteer's `total_service_minutes` is recomputed again — it is always the sum of `credited_minutes` over their signups in `CHECKED_IN` (provisional values) or `COMPLETED` (final values), while `NO_SHOW` and `CANCELLED` signups contribute zero. A signup that never checks in is swept to `NO_SHOW` by the slot-completion cascade, its `credited_minutes` set to zero and its volunteer's `no_show_count` incremented. `COMPLETED`, `NO_SHOW`, and `CANCELLED` are terminal for a signup.

### 3.6. Group Bookings and Youth Supervision

Visiting groups — school classes, clubs, corporate teams — are booked as a unit. A `GardenAdmin`, `Coordinator`, or `GroupLeader` creates a booking with a `slot_id`, a `leader_volunteer_id`, an `organization_name`, a `member_count` strictly greater than zero that counts every attendee including chaperones, a `minor_count` that is non-negative and no larger than `member_count`, a `chaperone_count` of declared adult chaperones that is non-negative, and `chaperone_volunteer_ids`, the volunteer ids of those chaperones. A `GroupLeader` caller may book only for itself — `leader_volunteer_id` must equal its identity, otherwise `ERR_OWNERSHIP_VIOLATION`. On creation the server derives `required_chaperones` as the `minor_count` divided by 8 and rounded up to a whole chaperone — so 16 minors require exactly 2 — and the booking starts `REQUESTED` with `rejection_reason` null.

Creation applies its gates in sequence: the slot must be in `OPEN` or `FULL` (otherwise `ERR_INVALID_SLOT_STATE`); the clock must be earlier than 24 hours before the slot's `starts_at` (otherwise `ERR_SLOT_LOCKED`); the leader must pass the participation gates of §2.8 — oriented, waiver signed, not suspended (`ERR_ORIENTATION_REQUIRED`, `ERR_WAIVER_REQUIRED`, `ERR_VOLUNTEER_SUSPENDED`); the supervision ratio must hold (otherwise `ERR_SUPERVISION_RATIO_VIOLATION`); and both capacity pools must pre-check — `confirmed_count` plus `member_count` within `capacity_total` (otherwise `ERR_SLOT_CAPACITY_EXCEEDED`) and `confirmed_youth_count` plus `minor_count` within `capacity_youth` (otherwise `ERR_YOUTH_CAPACITY_EXCEEDED`).

The supervision ratio rule is precise and is evaluated both at creation and again at confirmation. It passes exactly when all three clauses hold: `chaperone_count` is at least `required_chaperones`; the count of distinct ids in `chaperone_volunteer_ids` — duplicates are counted once — that each reference an existing volunteer holding an `ACTIVE` `SUPERVISION` certification is at least `required_chaperones`; and `minor_count` does not exceed `member_count`. Every listed chaperone must hold the `ACTIVE` supervision credential at creation and still hold it when the booking is confirmed.

Confirmation, by a `GardenAdmin` or `Coordinator`, re-runs the structural and safety gates: the booking is `REQUESTED` (otherwise `ERR_INVALID_GROUP_STATE`), the slot is `OPEN` or `FULL` (otherwise `ERR_INVALID_SLOT_STATE`), the clock precedes the 24-hour lock (otherwise `ERR_SLOT_LOCKED`), the ratio check passes again (otherwise `ERR_SUPERVISION_RATIO_VIOLATION`), and both capacity pools still fit (otherwise `ERR_SLOT_CAPACITY_EXCEEDED` or `ERR_YOUTH_CAPACITY_EXCEEDED`). On success the slot's `confirmed_count` rises by `member_count` and its `confirmed_youth_count` by `minor_count`, and the slot flips `OPEN → FULL` when total capacity is reached. Unlike individual signups, a group booking has no waitlist: when the pools cannot hold the group, the confirm simply fails.

Rejection, also by a `GardenAdmin` or `Coordinator`, moves a `REQUESTED` booking to `REJECTED` with a non-empty `rejection_reason` (otherwise `ERR_INVALID_REQUEST`). Group check-in — by staff or by the booking's own leader (ownership applies, otherwise `ERR_OWNERSHIP_VIOLATION`) — requires the booking to be `CONFIRMED` and the clock to fall within the window from 30 minutes before `starts_at` through `ends_at`, otherwise `ERR_OUTSIDE_CHECKIN_WINDOW`. Completion is never manual: when the slot moves `LOCKED → COMPLETED`, its `CHECKED_IN` bookings cascade to `COMPLETED`, while its still-`CONFIRMED` bookings cascade to `CANCELLED`.

Cancellation releases a booking from `REQUESTED` or `CONFIRMED`, manually by staff or the leader (ownership applies), or automatically when the slot is cancelled or completed. A manual cancellation from `CONFIRMED` requires the clock to precede the 24-hour lock (otherwise `ERR_SLOT_LOCKED`), and it returns the group's footprint to the pools: `confirmed_count` falls by `member_count`, `confirmed_youth_count` by `minor_count`, and a `FULL` slot reopens to `OPEN`. Cancelling a `REQUESTED` booking frees nothing, since `REQUESTED` bookings occupy no pool space. A cancel from any other state is rejected with `ERR_INVALID_GROUP_STATE`; `COMPLETED`, `CANCELLED`, and `REJECTED` are terminal.

### 3.7. Tool Pools, Tool Checkouts, and Shed Keys

The tool shed is modeled as pools of identical units. A `GardenAdmin` or `Coordinator` registers a tool pool with a `tool_name`, a `category` of `HAND`, `POWER`, `IRRIGATION`, `SAFETY`, or `OTHER`, and a `total_count` strictly greater than zero. The pool starts `IN_SERVICE` with `available_count` equal to `total_count` and `checked_out_count`, `in_maintenance_count`, and `written_off_count` at zero. One conservation invariant holds at all times: `total_count` always equals the sum of available, checked-out, in-maintenance, and written-off units. The server derives `available_count` as `total_count` minus the other three counters, and derives `checked_out_count` as the sum of outstanding units — `qty` minus `qty_returned` — over the pool's checkouts in `OPEN` or `PARTIAL_RETURN`.

Borrowing is a checkout created by a `GardenAdmin`, `Coordinator`, or the borrower themselves (a `Volunteer` or `GroupLeader` caller's `volunteer_id` must equal their identity, otherwise `ERR_OWNERSHIP_VIOLATION`) with a `tool_id`, a `volunteer_id`, a `qty` strictly greater than zero, and an optional `signup_id` linking the loan to one of the same volunteer's shift signups — a link is accepted only when that signup belongs to the same volunteer and is in `CONFIRMED` or `CHECKED_IN`, otherwise `ERR_SIGNUP_NOT_ELIGIBLE`. Creation is gated: the tool must be `IN_SERVICE` (otherwise `ERR_INVALID_TOOL_STATE`); the borrower must pass the participation gates of §2.8 (`ERR_ORIENTATION_REQUIRED`, then `ERR_WAIVER_REQUIRED`, then `ERR_VOLUNTEER_SUSPENDED`); a `POWER`-category tool additionally requires the borrower to hold an `ACTIVE` `TOOL_SAFETY` certification (otherwise `ERR_TOOL_CERT_REQUIRED`); and `qty` must not exceed the pool's `available_count` (otherwise `ERR_TOOL_INSUFFICIENT_STOCK`). A successful checkout starts `OPEN` with `qty_returned` at zero and `condition_on_return` null, and the pool's `checked_out_count` rises by `qty` while `available_count` falls by `qty`; the pool's `version` increments alongside the checkout's.

Returns flow through a single transition action carrying a `to_state`, and they come in two sizes, both open to staff and to the borrower (ownership applies) from `OPEN` or `PARTIAL_RETURN` (otherwise `ERR_INVALID_CHECKOUT_STATE`). A full return supplies a `qty_returned` exactly equal to the outstanding remainder — `qty` minus the prior `qty_returned` — and a `condition_on_return` of `GOOD` or `DAMAGED`, which is required on every return; the checkout moves to `RETURNED`. A partial return supplies a `qty_returned` strictly greater than zero and strictly less than the remainder, with its condition, and the checkout moves to `PARTIAL_RETURN`. A `qty_returned` that is zero, negative, or larger than the remainder is rejected with `ERR_QUANTITY_INVALID`. Either way, the bookkeeping runs per returned unit: the pool's `checked_out_count` falls by the units returned this call, and the condition routes them — `GOOD` units flow back into `available_count`, while `DAMAGED` units accumulate in `in_maintenance_count` until repaired. Both the checkout's and the pool's `version` increment.

Damaged tools are restored to service by a `GardenAdmin` or `Coordinator` through a restore action carrying a `qty`: that many units move from `in_maintenance_count` back to `available_count`, and the pool's `version` increments. Asking to restore more units than are currently in maintenance is rejected with `ERR_QUANTITY_INVALID`.

When units will not come back, a `GardenAdmin` or `Coordinator` writes the checkout off, moving it from `OPEN` or `PARTIAL_RETURN` to `CLOSED_LOSS`. The outstanding units — `qty` minus `qty_returned` — leave `checked_out_count` and accumulate in `written_off_count`, and the loss cascades to the borrower's record: a borrower in `GOOD` standing drops to `PROBATION`. Both entities' `version` increment. A gentler ending exists for casualties of scheduling: when a slot cancellation cancels a signup (§3.5), any of its `OPEN` checkouts linked through `signup_id` move to `AUTO_CLOSED`, and the outstanding units return to `available_count` exactly as if they had come back in `GOOD` condition, with no standing penalty. `RETURNED`, `CLOSED_LOSS`, and `AUTO_CLOSED` are terminal.

Retirement takes a whole pool out of service. A `GardenAdmin` retires a pool that is `IN_SERVICE` (otherwise `ERR_INVALID_TOOL_STATE`) only when its `checked_out_count` is zero — every unit must be home or written off first, otherwise `ERR_TOOL_UNITS_OUTSTANDING`. `RETIRED` is terminal, and attempting a new checkout against a retired pool fails with `ERR_INVALID_TOOL_STATE`.

The shed itself is guarded more tightly than any tool. A `GardenAdmin` registers each physical key with a unique `key_code` (duplicates fail with `ERR_KEY_CODE_TAKEN`), and the registry is capped: at most 4 keys may exist in any status other than `RETIRED`, so registering a fifth live key is rejected with `ERR_KEY_REGISTRY_FULL`. A new key starts `AVAILABLE` with `current_holder_volunteer_id` and `due_back_at` null.

Checking a key out — a `GardenAdmin` or `Coordinator` invoking the key transition with `to_state` `CHECKED_OUT`, a `holder_volunteer_id`, and a `due_back_at` — is permitted only from `AVAILABLE` (otherwise `ERR_INVALID_KEY_STATE`) and applies the strictest participation screen in the system: the holder must be `ORIENTED` (otherwise `ERR_ORIENTATION_REQUIRED`), must hold a `SIGNED` waiver (otherwise `ERR_WAIVER_REQUIRED`), and must be in `GOOD` standing — `PROBATION` is disqualifying here (otherwise `ERR_VOLUNTEER_NOT_IN_GOOD_STANDING`). One key per person: the holder's `held_key_count` — the number of keys whose `current_holder_volunteer_id` names this volunteer with status `CHECKED_OUT` or `OVERDUE` — must be zero, otherwise `ERR_KEY_LIMIT_EXCEEDED`. Finally, `due_back_at` must be strictly after the current logical clock, otherwise the request fails shape validation with `ERR_INVALID_REQUEST`. A successful checkout records the holder, stamps the deadline, and raises the holder's `held_key_count` to one.

Time catches up with forgotten keys: when the clock passes `due_back_at`, the next epoch run moves the key from `CHECKED_OUT` to `OVERDUE`. Return is a staff action — requested with `to_state` `RETURNED` — from `CHECKED_OUT` or `OVERDUE` (otherwise `ERR_INVALID_KEY_STATE`); it restores the key to `AVAILABLE`, clears `current_holder_volunteer_id` and `due_back_at` to null, and decrements the holder's `held_key_count`. Declaring a key lost, from `CHECKED_OUT` or `OVERDUE`, moves it to the terminal `LOST` state, clears the holder, decrements `held_key_count`, and cascades a standing penalty: a holder in `GOOD` standing drops to `PROBATION`. A `GardenAdmin` may also retire an `AVAILABLE` key, moving it to the terminal `RETIRED` state and out of the registry cap.

### 3.8. Harvest Logs and Donation Distribution

When beds open for harvest, produce flows to two destinations: the volunteers who grew it and the donation network. Everything starts with a harvest log, created by a `GardenAdmin`, `Coordinator`, or the logger themselves (a `Volunteer` or `GroupLeader` caller's `logged_by_volunteer_id` must equal their identity, otherwise `ERR_OWNERSHIP_VIOLATION`) with `season_id`, `bed_id`, an optional `crop_plan_id` linking the log to the plan it fulfills (null when omitted), `logged_by_volunteer_id`, `crop_type`, `weight_grams` strictly greater than zero, a `quality_grade` of `A`, `B`, or `C`, a `harvested_at` instant, and a `safety_attestation` flag. Creation applies its gates in sequence: the season must be in `HARVESTING` (otherwise `ERR_SEASON_NOT_ACCEPTING`); the bed must be in `HARVEST_OPEN` (otherwise `ERR_BED_NOT_HARVEST_OPEN`); the logger must pass the participation gates of §2.8 (`ERR_ORIENTATION_REQUIRED`, `ERR_WAIVER_REQUIRED`, `ERR_VOLUNTEER_SUSPENDED`); the logger must hold an `ACTIVE` `PRODUCE_SAFETY` certification (otherwise `ERR_PRODUCE_SAFETY_CERT_REQUIRED`); `safety_attestation` must be true (otherwise `ERR_SAFETY_ATTESTATION_REQUIRED`); and `harvested_at` must lie within the season's operating window (otherwise `ERR_OUTSIDE_SEASON_WINDOW`) and must not be after the current logical clock (otherwise `ERR_HARVEST_IN_FUTURE`). A new log starts `DRAFT` with `rejection_reason` null.

While a log is `DRAFT`, staff or the logger may edit its `crop_type`, `weight_grams`, `quality_grade`, `harvested_at`, `safety_attestation`, or `crop_plan_id`; editing a log in any other status is rejected with `ERR_INVALID_HARVEST_STATE`, and a self-service caller who is not the logger is rejected with `ERR_OWNERSHIP_VIOLATION`. Each edit increments the log's `version`.

Submission moves a log from `DRAFT` to `SUBMITTED` — by staff or the logger (ownership applies) — and re-checks the safety basis: `safety_attestation` must still be true (otherwise `ERR_SAFETY_ATTESTATION_REQUIRED`), and the logger must hold an `ACTIVE` `PRODUCE_SAFETY` certification at submit time (otherwise `ERR_PRODUCE_SAFETY_CERT_REQUIRED`); a log not in `DRAFT` cannot be submitted (`ERR_INVALID_HARVEST_STATE`).

Verification is the food-safety checkpoint, performed by a `GardenAdmin` or `FoodSafetyOfficer` moving a `SUBMITTED` log to `VERIFIED`. Segregation of duties applies: the verifier's identity must differ from the log's `logged_by_volunteer_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`), and the logger must still hold an `ACTIVE` `PRODUCE_SAFETY` certification at verify time (otherwise `ERR_PRODUCE_SAFETY_CERT_REQUIRED`). The same actors may instead reject the log with a non-empty `rejection_reason` (otherwise `ERR_INVALID_REQUEST`), moving it to `REJECTED`. A rejected log is not dead: staff or the logger may return it from `REJECTED` to `DRAFT`, which clears `rejection_reason` to null and reopens editing. A `DRAFT` log may instead be abandoned to `DISCARDED` by staff or the logger. Two cascades complete the picture: if the logger's `PRODUCE_SAFETY` certification is revoked (§3.2), their logs sitting in `SUBMITTED` fall back to `DRAFT` for re-verification; and when a donation allocation for a `VERIFIED` log reaches `DISTRIBUTED`, the log cascades to `SPLIT_FINALIZED`. `SPLIT_FINALIZED` and `DISCARDED` are terminal.

The donation network is a registry of recipients administered by a `GardenAdmin`: each carries an `org_name`, a `contact_email`, a `weekly_capacity_grams` strictly greater than zero, a `priority_tier` from 1 (highest) to 5 (lowest) that serves as informational ordering for split proposals, an optional `accepts_grade_c` flag (default true), and an optional `active` flag (default true). The administrator may later patch `weekly_capacity_grams`, `priority_tier`, `accepts_grade_c`, `active`, or `contact_email`, each edit incrementing the recipient's `version`. Each recipient also carries a live counter, `committed_this_week_grams`: the sum of line grams naming that recipient over donation allocations in `PENDING`, `APPROVED`, or `DISTRIBUTED` whose `created_at` falls inside the ISO week of the current logical clock — the half-open week running from Monday 00:00:00.000 inclusive to the next Monday 00:00:00.000 exclusive.

A split is proposed by a `GardenAdmin` or `Coordinator` creating a donation allocation with a `harvest_log_id` and a set of `lines`, each line naming a `recipient_id` and an integer `grams` strictly greater than zero. The referenced log must be `VERIFIED` (otherwise `ERR_HARVEST_LOG_NOT_VERIFIED`), and a log carries at most one non-terminal allocation — one in `PENDING`, `APPROVED`, or `DISTRIBUTED` — so a second proposal against a log that already has one is rejected with `ERR_DUPLICATE_ACTIVE_ALLOCATION`.

The split arithmetic is pinned to a fixed rounding order. First, `volunteer_share_grams` is computed as the log's `weight_grams` multiplied by 0.20 and rounded down to a whole gram — the rounding happens first, before anything else. Second, `donatable_grams` is the remainder, `weight_grams` minus `volunteer_share_grams`, so the donatable pool absorbs the rounding rather than the volunteer share. Third, the request's line amounts are absolute integer grams, and they must sum exactly to `donatable_grams` — neither rounding the share to nearest nor summing-then-rounding is acceptable, and any mismatch is rejected with `ERR_SPLIT_MISMATCH`. Each line is then screened: the recipient must be active (otherwise `ERR_RECIPIENT_INACTIVE`); if the log's `quality_grade` is `C`, every named recipient must have `accepts_grade_c` true (otherwise `ERR_RECIPIENT_GRADE_RESTRICTED`); and the recipient's weekly capacity must pre-check — `committed_this_week_grams` plus the line's grams must not exceed `weekly_capacity_grams`, with an exact fit allowed (otherwise `ERR_RECIPIENT_CAPACITY_EXCEEDED`). A valid proposal starts `PENDING` with `rejection_reason` null.

Approval, by a `GardenAdmin` or `FoodSafetyOfficer`, moves a `PENDING` allocation to `APPROVED` and re-runs the safeguards: the allocation is `PENDING` (otherwise `ERR_INVALID_ALLOCATION_STATE`), the harvest log is still `VERIFIED` (otherwise `ERR_HARVEST_LOG_NOT_VERIFIED`), segregation of duties bars the harvest's logger from approving (otherwise `ERR_SEGREGATION_OF_DUTIES`), every line's recipient is still active (otherwise `ERR_RECIPIENT_INACTIVE`), and each recipient's weekly commitment is re-checked against the line grams with exact fit allowed (otherwise `ERR_RECIPIENT_CAPACITY_EXCEEDED`). On approval each recipient's `committed_this_week_grams` rises by its line grams. The same actors may instead reject a `PENDING` allocation with a non-empty `rejection_reason` (otherwise `ERR_INVALID_REQUEST`).

Distribution is the closing act, by a `GardenAdmin` or `Coordinator` moving an `APPROVED` allocation to `DISTRIBUTED` (from any other state, `ERR_INVALID_ALLOCATION_STATE`). Distribution cascades: the harvest log moves from `VERIFIED` to `SPLIT_FINALIZED`, and both the allocation's and the log's `version` increment. `DISTRIBUTED` and `REJECTED` are terminal for an allocation.

### 3.9. Irrigation Scheduling and Meter Reconciliation

Water is the season's scarcest budgeted resource, and scheduling it debits the season's ledger. A `GardenAdmin` or `Coordinator` creates an irrigation schedule with a `season_id`, a `zone` label, a `planned_start_at`, a `planned_end_at` strictly after the start, a `planned_gallons` strictly greater than zero, and — because the create debits the season — an `expected_season_version` per the optimistic-concurrency rule of §2.7, with stale values rejected as `ERR_STALE_VERSION`. Creation then applies its gates: the season must be in `PLANTING`, `GROWING`, or `HARVESTING` (otherwise `ERR_SEASON_NOT_ACCEPTING`); the planned window must lie within the season's operating window (otherwise `ERR_OUTSIDE_SEASON_WINDOW`); the window must not collide with another schedule in the same season and the same `zone` (otherwise `ERR_IRRIGATION_OVERLAP`); and the water budget gate must pass (otherwise `ERR_WATER_BUDGET_EXCEEDED`).

The overlap rule treats windows as half-open intervals: a window ending at an instant T and another beginning at T do not conflict. Two schedules in the same season and same zone conflict exactly when both are in an occupied status — `SCHEDULED`, `DUE`, `MISSED`, `LOGGED`, or `RECONCILED` — and each window's start is before the other's end. `CANCELLED` windows never block anything.

The budget gate projects the season's ledger forward in a pinned evaluation order. First, committed water is the sum of `planned_gallons` over the season's schedules in `SCHEDULED`, `DUE`, or `MISSED`, excluding the candidate itself, which is not yet persisted. Second, actual water is the sum of `gallons_actual` over the season's schedules in `LOGGED` or `RECONCILED`. Third, the projection is committed plus actual plus the candidate's `planned_gallons`. The gate passes exactly when the projection does not exceed the season's `water_budget_gallons` — exact equality is allowed. Once the candidate persists as `SCHEDULED`, the season's `water_committed_gallons` includes it, `water_remaining_gallons` is recomputed as budget minus committed minus actual, and both the schedule's and the season's `version` increment.

Time moves schedules without human involvement: at an epoch run, a schedule in `SCHEDULED` whose window has begun — the clock at or after `planned_start_at` and not after `planned_end_at` — becomes `DUE`, and a schedule in `SCHEDULED` or `DUE` whose window has closed — the clock strictly past `planned_end_at` — with no meter reading logged becomes `MISSED`.

Until a reading exists, `gallons_actual` is null. Meter reconciliation is the staff act of recording what actually flowed: a `GardenAdmin` or `Coordinator` logs the meter for a schedule in `SCHEDULED`, `DUE`, or `MISSED` (otherwise `ERR_INVALID_IRRIGATION_STATE`) by supplying `gallons_actual`, which must be zero or greater (otherwise `ERR_QUANTITY_INVALID`). Logging records the reading, recomputes the schedule's `variance_flag` — true exactly when `gallons_actual` exceeds `planned_gallons` multiplied by 1.10 and rounded down to a whole gallon, and false until any reading exists — and rebalances the season's ledger: `water_committed_gallons` falls by the schedule's `planned_gallons`, `water_actual_gallons` rises by `gallons_actual`, and `water_remaining_gallons` is recomputed. The schedule moves to `LOGGED`, and both entities' `version` increment. A `GardenAdmin` alone may then move a `LOGGED` schedule to `RECONCILED`, marking the reading as audited.

Cancellation releases planned water. A `GardenAdmin` or `Coordinator` may cancel a schedule in `SCHEDULED` or `DUE` (otherwise `ERR_INVALID_IRRIGATION_STATE`), and the same move happens automatically when the season enters `RECONCILIATION` or is `CANCELLED`. Cancellation subtracts the schedule's `planned_gallons` from the season's `water_committed_gallons`, recomputes `water_remaining_gallons`, and increments both entities' `version`. `RECONCILED` and `CANCELLED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — transitions, signings, check-ins, meter loggings, partial updates — return a `200 OK` status code. All endpoints are mounted under `/api`. Readers reconstruct each operation's request payload and side effects from the narratives in §2 and §3; this table fixes only the HTTP contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the logical clock (startup default `2026-08-01T00:00:00Z`; never falls back to wall-clock) | GardenAdmin |
| POST | `/api/_scheduler/run_epoch` | Apply all time-based automatic transitions as of the logical clock | GardenAdmin |
| POST | `/api/volunteers` | Register a volunteer | GardenAdmin, Coordinator |
| GET | `/api/volunteers` | List volunteers | All five roles |
| GET | `/api/volunteers/{volunteerId}` | Get one volunteer | All five roles |
| POST | `/api/volunteers/{volunteerId}/orientation/complete` | Mark orientation completed | GardenAdmin, Coordinator |
| POST | `/api/volunteers/{volunteerId}/waiver/sign` | Sign or renew the liability waiver | All five roles |
| POST | `/api/volunteers/{volunteerId}/standing` | Manual standing transition (`PROBATION` / `SUSPENDED` / `GOOD`) | GardenAdmin |
| POST | `/api/certifications` | Issue a training certification (issuer may not be the subject) | GardenAdmin, FoodSafetyOfficer |
| GET | `/api/certifications` | List certifications | All five roles |
| GET | `/api/certifications/{certificationId}` | Get one certification | All five roles |
| POST | `/api/certifications/{certificationId}/revoke` | Revoke an `ACTIVE` certification | GardenAdmin, FoodSafetyOfficer |
| POST | `/api/seasons` | Create a season (`DRAFT`, water counters zeroed) | GardenAdmin |
| GET | `/api/seasons` | List seasons | All five roles |
| GET | `/api/seasons/{seasonId}` | Get one season | All five roles |
| PATCH | `/api/seasons/{seasonId}` | Edit season configuration (OCC on the season version; only while `DRAFT` or `OPEN_ENROLLMENT`) | GardenAdmin |
| POST | `/api/seasons/{seasonId}/transition` | Season lifecycle transition with guards and cascades | GardenAdmin |
| POST | `/api/beds` | Register a garden bed (`FALLOW`) | GardenAdmin, Coordinator |
| GET | `/api/beds` | List beds | All five roles |
| GET | `/api/beds/{bedId}` | Get one bed | All five roles |
| POST | `/api/beds/{bedId}/transition` | Bed lifecycle transition (`RESERVED`/`PLANTED`/`GROWING`/`HARVEST_OPEN`/`POST_HARVEST`/`FALLOW`/`OUT_OF_SERVICE`) | GardenAdmin, Coordinator |
| POST | `/api/crop-plans` | Propose a crop plan for a bed in a season | GardenAdmin, Coordinator, Volunteer, GroupLeader |
| GET | `/api/crop-plans` | List crop plans | All five roles |
| GET | `/api/crop-plans/{cropPlanId}` | Get one crop plan | All five roles |
| POST | `/api/crop-plans/{cropPlanId}/transition` | Crop-plan transition (`APPROVED`/`REJECTED`/`PROPOSED` resubmit/`PLANTED`/`COMPLETE`/`WITHDRAWN`) | GardenAdmin, Coordinator, Volunteer, GroupLeader |
| POST | `/api/shift-slots` | Create a shift slot (`DRAFT`) | GardenAdmin, Coordinator |
| GET | `/api/shift-slots` | List shift slots | All five roles |
| GET | `/api/shift-slots/{slotId}` | Get one shift slot | All five roles |
| PATCH | `/api/shift-slots/{slotId}` | Edit slot capacity/times (OCC on the slot version; only while `DRAFT` or `OPEN`) | GardenAdmin, Coordinator |
| POST | `/api/shift-slots/{slotId}/transition` | Slot lifecycle transition (`OPEN`/`LOCKED`/`COMPLETED`/`CANCELLED`) | GardenAdmin, Coordinator |
| POST | `/api/shift-signups` | Create a signup (`REQUESTED`) | GardenAdmin, Coordinator, Volunteer, GroupLeader |
| GET | `/api/shift-signups` | List signups | All five roles |
| GET | `/api/shift-signups/{signupId}` | Get one signup | All five roles |
| POST | `/api/shift-signups/{signupId}/confirm` | Confirm a `REQUESTED` signup; waitlists instead when pools are full | GardenAdmin, Coordinator |
| POST | `/api/shift-signups/{signupId}/cancel` | Cancel a non-terminal signup; freeing a `CONFIRMED` spot triggers promotion | GardenAdmin, Coordinator, Volunteer, GroupLeader |
| POST | `/api/shift-signups/{signupId}/check-in` | Check in to a shift (window: 30 minutes before `starts_at` through `ends_at`) | GardenAdmin, Coordinator, Volunteer, GroupLeader |
| POST | `/api/shift-signups/{signupId}/check-out` | Check out; final credit is the lesser of actual elapsed and scheduled plus 30 minutes | GardenAdmin, Coordinator, Volunteer, GroupLeader |
| POST | `/api/group-bookings` | Request a group booking (`REQUESTED`) | GardenAdmin, Coordinator, GroupLeader |
| GET | `/api/group-bookings` | List group bookings | All five roles |
| GET | `/api/group-bookings/{bookingId}` | Get one group booking | All five roles |
| POST | `/api/group-bookings/{bookingId}/transition` | Booking transition (`CONFIRMED`/`REJECTED`/`CHECKED_IN`/`CANCELLED`) | GardenAdmin, Coordinator, GroupLeader |
| POST | `/api/shed-keys` | Register a shed key (at most 4 non-`RETIRED` keys) | GardenAdmin |
| GET | `/api/shed-keys` | List shed keys | All five roles |
| GET | `/api/shed-keys/{keyId}` | Get one shed key | All five roles |
| POST | `/api/shed-keys/{keyId}/transition` | Key transition (`CHECKED_OUT` with holder and due-back / `RETURNED` / `LOST` / `RETIRED`) | GardenAdmin, Coordinator |
| POST | `/api/tools` | Register a tool pool | GardenAdmin, Coordinator |
| GET | `/api/tools` | List tools | All five roles |
| GET | `/api/tools/{toolId}` | Get one tool | All five roles |
| POST | `/api/tools/{toolId}/restore` | Move units from maintenance back to available | GardenAdmin, Coordinator |
| POST | `/api/tools/{toolId}/retire` | Retire a tool pool (requires zero checked-out units) | GardenAdmin |
| POST | `/api/tool-checkouts` | Check out tool units | GardenAdmin, Coordinator, Volunteer, GroupLeader |
| GET | `/api/tool-checkouts` | List tool checkouts | All five roles |
| GET | `/api/tool-checkouts/{checkoutId}` | Get one tool checkout | All five roles |
| POST | `/api/tool-checkouts/{checkoutId}/transition` | Return (full or partial, with condition) or write off a checkout | GardenAdmin, Coordinator, Volunteer, GroupLeader |
| POST | `/api/harvest-logs` | Create a harvest log (`DRAFT`) | GardenAdmin, Coordinator, Volunteer, GroupLeader |
| GET | `/api/harvest-logs` | List harvest logs | All five roles |
| GET | `/api/harvest-logs/{harvestLogId}` | Get one harvest log | All five roles |
| PATCH | `/api/harvest-logs/{harvestLogId}` | Edit a `DRAFT` harvest log (owner or staff) | GardenAdmin, Coordinator, Volunteer, GroupLeader |
| POST | `/api/harvest-logs/{harvestLogId}/transition` | Harvest transition (`SUBMITTED`/`VERIFIED`/`REJECTED`/`DRAFT` resubmit/`DISCARDED`) | GardenAdmin, Coordinator, Volunteer, GroupLeader, FoodSafetyOfficer |
| POST | `/api/donation-recipients` | Register a donation recipient | GardenAdmin |
| GET | `/api/donation-recipients` | List recipients | All five roles |
| GET | `/api/donation-recipients/{recipientId}` | Get one recipient | All five roles |
| PATCH | `/api/donation-recipients/{recipientId}` | Update recipient capacity, tier, acceptance, and active flags | GardenAdmin |
| POST | `/api/donation-allocations` | Propose a donation split for a `VERIFIED` harvest log | GardenAdmin, Coordinator |
| GET | `/api/donation-allocations` | List donation allocations | All five roles |
| GET | `/api/donation-allocations/{allocationId}` | Get one allocation | All five roles |
| POST | `/api/donation-allocations/{allocationId}/transition` | Allocation transition (`APPROVED`/`REJECTED` by officers; `DISTRIBUTED` by coordinators) | GardenAdmin, Coordinator, FoodSafetyOfficer |
| POST | `/api/irrigation-schedules` | Create an irrigation window (OCC on the season version; budget gate) | GardenAdmin, Coordinator |
| GET | `/api/irrigation-schedules` | List irrigation schedules | All five roles |
| GET | `/api/irrigation-schedules/{scheduleId}` | Get one irrigation schedule | All five roles |
| POST | `/api/irrigation-schedules/{scheduleId}/log-meter` | Record actual meter gallons (from `SCHEDULED`/`DUE`/`MISSED`) | GardenAdmin, Coordinator |
| POST | `/api/irrigation-schedules/{scheduleId}/transition` | Irrigation transition (`CANCELLED` / `RECONCILED`) | GardenAdmin, Coordinator |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier and the HTTP status code.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_VOLUNTEER_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_SEASON_NOT_FOUND` | 404 Not Found |
| `ERR_BED_NOT_FOUND` | 404 Not Found |
| `ERR_CROP_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_SHIFT_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_SIGNUP_NOT_FOUND` | 404 Not Found |
| `ERR_GROUP_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_SHED_KEY_NOT_FOUND` | 404 Not Found |
| `ERR_TOOL_NOT_FOUND` | 404 Not Found |
| `ERR_TOOL_CHECKOUT_NOT_FOUND` | 404 Not Found |
| `ERR_HARVEST_LOG_NOT_FOUND` | 404 Not Found |
| `ERR_RECIPIENT_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_IRRIGATION_SCHEDULE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_VOLUNTEER_STATE` | 409 Conflict |
| `ERR_INVALID_CERTIFICATION_STATE` | 409 Conflict |
| `ERR_INVALID_SEASON_STATE` | 409 Conflict |
| `ERR_INVALID_BED_STATE` | 409 Conflict |
| `ERR_INVALID_CROP_PLAN_STATE` | 409 Conflict |
| `ERR_INVALID_SLOT_STATE` | 409 Conflict |
| `ERR_INVALID_SIGNUP_STATE` | 409 Conflict |
| `ERR_INVALID_GROUP_STATE` | 409 Conflict |
| `ERR_INVALID_KEY_STATE` | 409 Conflict |
| `ERR_INVALID_TOOL_STATE` | 409 Conflict |
| `ERR_INVALID_CHECKOUT_STATE` | 409 Conflict |
| `ERR_INVALID_HARVEST_STATE` | 409 Conflict |
| `ERR_INVALID_ALLOCATION_STATE` | 409 Conflict |
| `ERR_INVALID_IRRIGATION_STATE` | 409 Conflict |
| `ERR_SEASON_GUARD_ACTIVE_BED_REQUIRED` | 409 Conflict |
| `ERR_SEASON_REVERT_BLOCKED` | 409 Conflict |
| `ERR_SEASON_NOT_ACCEPTING` | 409 Conflict |
| `ERR_CROP_PLANS_UNRESOLVED` | 409 Conflict |
| `ERR_IRRIGATION_UNRESOLVED` | 409 Conflict |
| `ERR_HARVEST_LOGS_UNVERIFIED` | 409 Conflict |
| `ERR_ALLOCATIONS_PENDING` | 409 Conflict |
| `ERR_SIGNUPS_STILL_CHECKED_IN` | 409 Conflict |
| `ERR_TOOL_UNITS_OUTSTANDING` | 409 Conflict |
| `ERR_BED_NOT_AVAILABLE` | 409 Conflict |
| `ERR_BED_NOT_HARVEST_OPEN` | 409 Conflict |
| `ERR_HARVEST_LOG_NOT_VERIFIED` | 409 Conflict |
| `ERR_ORIENTATION_REQUIRED` | 409 Conflict |
| `ERR_WAIVER_REQUIRED` | 409 Conflict |
| `ERR_VOLUNTEER_SUSPENDED` | 409 Conflict |
| `ERR_VOLUNTEER_NOT_IN_GOOD_STANDING` | 409 Conflict |
| `ERR_PRODUCE_SAFETY_CERT_REQUIRED` | 409 Conflict |
| `ERR_TOOL_CERT_REQUIRED` | 409 Conflict |
| `ERR_SAFETY_ATTESTATION_REQUIRED` | 409 Conflict |
| `ERR_YOUTH_SUPERVISION_REQUIRED` | 409 Conflict |
| `ERR_SUPERVISION_RATIO_VIOLATION` | 409 Conflict |
| `ERR_EMAIL_TAKEN` | 409 Conflict |
| `ERR_BED_CODE_TAKEN` | 409 Conflict |
| `ERR_KEY_CODE_TAKEN` | 409 Conflict |
| `ERR_DUPLICATE_SIGNUP` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_CERT` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_ALLOCATION` | 409 Conflict |
| `ERR_CROP_ROTATION_VIOLATION` | 409 Conflict |
| `ERR_RECIPIENT_INACTIVE` | 409 Conflict |
| `ERR_RECIPIENT_GRADE_RESTRICTED` | 409 Conflict |
| `ERR_SIGNUP_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_OUTSIDE_SEASON_WINDOW` | 409 Conflict |
| `ERR_SLOT_LOCKED` | 409 Conflict |
| `ERR_OUTSIDE_CHECKIN_WINDOW` | 409 Conflict |
| `ERR_HARVEST_IN_FUTURE` | 409 Conflict |
| `ERR_IRRIGATION_OVERLAP` | 409 Conflict |
| `ERR_BED_OCCUPANCY_OVERLAP` | 409 Conflict |
| `ERR_BED_REST_PERIOD_ACTIVE` | 409 Conflict |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_YOUTH_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_BED_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_KEY_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_KEY_REGISTRY_FULL` | 409 Conflict |
| `ERR_TOOL_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_RECIPIENT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_WATER_BUDGET_EXCEEDED` | 409 Conflict |
| `ERR_SPLIT_MISMATCH` | 409 Conflict |
| `ERR_QUANTITY_INVALID` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
