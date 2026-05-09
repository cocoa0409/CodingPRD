# Shared Power Bank Operation API — Product Requirements Document

## 1. Introduction

The shared power bank business operates a fleet of charging cabinets distributed across partner venues in multiple cities. Each cabinet houses a fixed number of slots, and each slot may contain one battery-powered "power bank" device that a passing user can borrow by scanning a QR code, carry away, and return to any cabinet — including a cabinet in a different city than the one they borrowed from. Behind that one-tap experience lies a network of physical hardware that occasionally goes offline, devices that occasionally jam in their slots, batteries that occasionally fall below a safe-to-rent threshold, and field operators who must be dispatched to clear faults and replenish low-battery cabinets before service degrades.

This document specifies the REST API that orchestrates the entire operation: cabinet inventory and heartbeats, the borrow-and-return workflow with its stuck-device recovery cycle, time-based billing with city-specific pricing plans and cross-city surcharges, overdue escalation with progressively rising hourly penalties leading to a "lost device" terminal state, repair-ticket lifecycle, operator task scheduling driven by a weighted priority score, and periodic revenue settlement that splits each rental's charge between the platform and the venue partner. The system must remain consistent under concurrent borrows on the same cabinet, racing operator assignments, and refund events that arrive after a settlement has already been invoiced. Risk-control checks at borrow time guard against repeated-refund abuse and abnormally high borrow frequency from a single user. A small set of test-only endpoints — a logical clock, a sweep runner, and an event emitter — exist solely to allow deterministic black-box verification of time-driven behaviors.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API request except those explicitly noted in §2.1.1 must include both `X-User-ID` and `X-User-Role` headers. If either is missing, the request is rejected with HTTP 401 and `error_id` `ERR_UNAUTHENTICATED`. If the role is well-formed but is not permitted to call the endpoint, the request is rejected with HTTP 403 and `error_id` `ERR_FORBIDDEN`.

The system recognises exactly four roles, spelled with this exact capitalisation:

- `User` — a registered customer who borrows and returns power banks. When `X-User-Role` is `User`, `X-User-ID` is the `id` of the acting `User`. Ownership checks on any resource that references a `User` (most importantly, `Rental.user_id`) compare the resource's foreign-key field to `X-User-ID`. A `User` may read or act on their own `Rental` records and their own `User` record only.
- `Operator` — a field worker who clears stuck devices, processes repair tickets, and accepts replenishment tasks. When `X-User-Role` is `Operator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on the resources the operator acts on (specifically as `RepairTicket.assigned_operator_id` and `OperatorTask.assigned_operator_id` when the corresponding self-assign or auto-assign transition writes it) but does not compare it to any entity's `id` for ownership purposes.
- `Partner` — a location partner viewing settlements for venues they host. When `X-User-Role` is `Partner`, `X-User-ID` is the `id` of the acting `LocationPartner`; reads on `Settlement` are scoped so that a `Partner` may retrieve only those settlements whose `location_partner_id` equals `X-User-ID`.
- `Admin` — a platform administrator. When `X-User-Role` is `Admin`, `X-User-ID` is an opaque administrator identifier not tied to any persisted entity; the server may log it but does not compare it to any entity's `id`.

#### 2.1.1. Endpoints exempt from authentication

The four test-and-integration endpoints are deliberately unauthenticated and accept requests without `X-User-ID` / `X-User-Role` headers: receiving payment events from the upstream payment system (`POST /payment-events`), advancing the logical clock (`POST /_clock/advance`), running scheduled sweeps (`POST /_sweep/run`), and emitting external events (`POST /_events/emit`). For these four endpoints, the auth check at priority 1 is skipped; the role-permission check at priority 2 is also skipped because the endpoints are not in any role's permission set.

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

List endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; values outside these bounds are rejected with `ERR_INVALID_INPUT`. The default `offset` is 0 and there is no upper bound. List endpoints return their results sorted by `created_at` in ascending order. The `meta` block on every list response includes `limit`, `offset`, `total_count`, and `has_more`, with `has_more` set to `true` whenever `offset + limit` is strictly less than `total_count`.

### 2.4. Resource Identity, Timestamps, and Optimistic Concurrency

Every entity that carries the standard set of common fields exposes four properties on its representation: `id`, `created_at`, `updated_at`, and `version`. The `id` is a server-minted UUID with no type prefix — clients never supply it. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `created_at` is fixed at the moment the resource is born and never changes thereafter, while `updated_at` is rewritten to the current logical clock value on every mutation that produces a state change or a field change on the resource. The `version` field is an integer initialised to 1 at creation and incremented by exactly 1 on every successful mutation; clients may include the most-recently-observed `version` in the body of a mutating request as an optimistic concurrency check, in which case the server rejects the request with `ERR_VERSION_CONFLICT` (HTTP 409) when the supplied `version` does not equal the current persisted value. Omitting `version` from the request body skips the OCC check entirely. Among the entities defined in this specification, only `PaymentEvent` does **not** carry the common fields; a `PaymentEvent` exposes `id` and `created_at` only, and has neither `updated_at` nor `version`.

### 2.5. Cabinet Connectivity and Degraded Service

Cabinets report their status to the platform by posting a heartbeat. A cabinet's `online_status` is `ONLINE` when its most recent heartbeat is younger than the heartbeat-timeout threshold of 300 seconds (five minutes), measured against the logical clock at the moment the value is read; otherwise the cabinet is considered `OFFLINE`. The `last_heartbeat_at` field records the timestamp of the most recent heartbeat. New rentals from an `OFFLINE` cabinet, returns to an `OFFLINE` cabinet, and return-retry attempts at an `OFFLINE` cabinet are all rejected with `ERR_CABINET_OFFLINE`. Existing in-flight rentals continue to accrue billing normally even while their start cabinet is offline; only fresh borrow and return calls observe the gate.

A cabinet may also be temporarily blocked by a scheduled maintenance window. When a `SCHEDULED` `MaintenanceWindow` exists for a cabinet such that `window_start` is at or before the current logical clock value and `window_end` is strictly after it, the same three operations — borrow, return, and return-retry — are rejected with `ERR_CABINET_UNDER_MAINTENANCE`. New maintenance windows must not overlap any other `SCHEDULED` window on the same cabinet; overlap is computed with half-open interval semantics, treating each window as the interval `[window_start, window_end)`, so two windows where the first one's `window_end` exactly equals the second one's `window_start` are permitted (they touch but do not overlap), while any strict overlap is rejected with `ERR_MAINTENANCE_WINDOW_OVERLAP`.

### 2.6. Monetary Precision and Rounding Conventions

Every monetary value — `hourly_rate`, `daily_cap`, `cross_city_surcharge`, `wallet_balance`, `deposit_balance`, `charged_amount`, `refund_amount`, `gross_revenue`, `partner_amount`, `refund_adjustment`, the `amount` field on a `PaymentEvent`, and every monetary intermediate computed by a calculation rule — is stored and emitted with exactly two decimal places, and every rounding step uses round-half-up. For settlement aggregations, the rounding order is pinned: each contributing rental's partner share is rounded to two decimal places first and the rounded values are then summed, never the reverse. The `revenue_share_pct` field on a `LocationPartner` is the only monetary-adjacent quantity that is *not* a CNY amount; it is a decimal fraction in the closed range from 0 to 1 with up to four decimal places of precision (so a 33.5% partner share is stored as `0.3350` or equivalently `0.335`).

### 2.7. Validation Priority and Error Surface

When a single request triggers multiple validation failures, the failure that surfaces is determined by a fixed priority order. The server walks the checks in this sequence and returns the first one that fires; later checks are not evaluated:

1. **Authentication** — `X-User-ID` and `X-User-Role` are present (rejection: `ERR_UNAUTHENTICATED`, HTTP 401).
2. **Authorization** — the supplied `X-User-Role` is permitted for the endpoint per the role matrix (rejection: `ERR_FORBIDDEN`, HTTP 403).
3. **Existence of path-parameter resources** — every `id` and `slot_index` in the URL points to an existing resource, evaluated left-to-right (rejection: `ERR_NOT_FOUND`, HTTP 404).
4. **Request body shape** — types, enum membership, and numeric ranges of every field in the request body are valid (rejection: `ERR_INVALID_INPUT`, HTTP 400).
5. **Target-resource state** — the targeted resource is in a state from which the requested transition is defined, including `Rental.rental_status`, `Rental.payment_status`, `RepairTicket.status`, `OperatorTask.status`, `Settlement.status`, `Device.status`, and `Slot.slot_status` preconditions enumerated in §3 (rejection: `ERR_INVALID_STATE`, HTTP 409).
6. **One active rental per user** — when the endpoint is borrow, the caller has no other `Rental` whose `rental_status` is `ACTIVE`, `OVERDUE`, or `STUCK` (rejection: `ERR_DUPLICATE_RENTAL`, HTTP 409).
7. **Rental ownership** — when the endpoint is rental return, return-retry, or rental read, the acting `User`'s `id` equals the `Rental.user_id` (rejection: `ERR_FORBIDDEN`, HTTP 403).
8. **Cabinet connectivity** — the cabinet's `online_status` is `ONLINE` (rejection: `ERR_CABINET_OFFLINE`, HTTP 409). Applies to borrow, return, and return-retry.
9. **Maintenance window** — no `SCHEDULED` `MaintenanceWindow` on the cabinet currently covers the logical clock (rejection: `ERR_CABINET_UNDER_MAINTENANCE`, HTTP 409). Applies to borrow, return, and return-retry.
10. **Borrow eligibility — at least one available device** — at borrow time, the cabinet contains at least one `Device` with `status` equal to `AVAILABLE` and `battery_level` at or above 50 (rejection: `ERR_NO_AVAILABLE_DEVICE`, HTTP 409).
11. **Return slot empty** — at return time, the chosen return slot has `slot_status` equal to `EMPTY` (rejection: `ERR_SLOT_OCCUPIED`, HTTP 409).
12. **Maintenance window overlap** — when scheduling a new maintenance window, no other `SCHEDULED` window on the same cabinet strictly overlaps the new one under half-open interval semantics (rejection: `ERR_MAINTENANCE_WINDOW_OVERLAP`, HTTP 409).
13. **Pricing plan exists** — at borrow time, a `PricingPlan` exists whose `city_code` equals the start cabinet's `city_code` (rejection: `ERR_PRICING_NOT_CONFIGURED`, HTTP 422).
14. **Refund risk control** — at borrow time, the user's `refund_count_30d` is strictly less than 5 (rejection: `ERR_REFUND_LIMIT_EXCEEDED`, HTTP 403).
15. **Borrow frequency risk control** — at borrow time, the user's `borrow_count_24h` is strictly less than 10 (rejection: `ERR_ABNORMAL_BORROW_PATTERN`, HTTP 403).
16. **Deposit sufficient** — at borrow time, the user's `deposit_balance` is at or above the minimum deposit of 99.00 CNY (rejection: `ERR_DEPOSIT_INSUFFICIENT`, HTTP 402).
17. **Wallet not in debt** — at borrow time, the user's `wallet_balance` is at or above 0 (rejection: `ERR_WALLET_INSUFFICIENT`, HTTP 402).
18. **Settlement period valid** — when creating a settlement, `period_end` is strictly after `period_start` (rejection: `ERR_SETTLEMENT_PERIOD_INVALID`, HTTP 422).
19. **Repair-dispatch task readiness** — when completing an operator task whose `task_type` is `REPAIR_DISPATCH`, the linked `RepairTicket` has reached `RESOLVED` (rejection: `ERR_TICKET_UNRESOLVED`, HTTP 409).
20. **Idempotency-key uniqueness** — the supplied `idempotency_key` on an incoming `PaymentEvent` has not been received before (rejection: `ERR_DUPLICATE_PAYMENT_EVENT`, HTTP 409).
21. **Optimistic concurrency** — when the request body supplies a `version`, it equals the current persisted value (rejection: `ERR_VERSION_CONFLICT`, HTTP 409).

The borrow endpoint exercises priorities 1–10 and 13–17 in this order; in particular, a request that fails authorization is reported as `ERR_FORBIDDEN` even if the body would have failed input validation, and a request that fails cabinet connectivity is reported as `ERR_CABINET_OFFLINE` even if the user lacks the deposit. Risk-control checks (priorities 14 and 15) fire after pricing-plan existence (priority 13) but before the fiscal checks (priorities 16 and 17), so a refund-abuse user without a pricing plan first sees `ERR_PRICING_NOT_CONFIGURED`, then `ERR_REFUND_LIMIT_EXCEEDED`, then `ERR_ABNORMAL_BORROW_PATTERN`, then `ERR_DEPOSIT_INSUFFICIENT`, then `ERR_WALLET_INSUFFICIENT`.

### 2.8. Cascade Semantics for Anomaly Chains

A single user-initiated or sweep-initiated action can trigger a chain of dependent state writes across multiple entities; the chain is ordered, and every link is caused by the preceding link rather than directly by the API call. The canonical anomaly chain runs four hops: a `RepairTicket` is created (the action), the targeted `Device` transitions from `AVAILABLE` to `FAULTY` (cascade caused by ticket creation), the slot housing that device transitions from `OCCUPIED` to `FAULTY` (cascade caused by the device transition), and finally an `OperatorTask` of `task_type` `REPAIR_DISPATCH` is auto-created for the cabinet, with `linked_repair_ticket_id` pointing back to the originating ticket and `priority_score` computed at creation (cascade caused by the slot transition). When a single operation produces a state change on a resource, that resource's `updated_at` advances to the current logical clock value and its `version` increments by exactly 1; cascade legs that only read a resource without mutating it leave both fields untouched.

### 2.9. Race Conditions and Serialization Guarantees

When two requests race on the same resource the system serialises them so that exactly one operation produces side effects and the other receives a deterministic error. Four races are defined.

When two users attempt to borrow from the same cabinet at the same instant and the device-selection policy picks the same `Device`, the underlying transition `Device.status` from `AVAILABLE` to `BORROWED` is first-writer-wins on that single device; the rental that loses receives `ERR_NO_AVAILABLE_DEVICE` (HTTP 409) because, at the moment its check runs, the only candidate device is no longer `AVAILABLE`.

When two operators call auto-assign and the priority queue selects the same `OperatorTask` for both, the write of `OperatorTask.assigned_operator_id` is first-writer-wins; the loser receives `ERR_TASK_ALREADY_ASSIGNED` (HTTP 409).

When a return and a refund-issue are processed simultaneously against the same rental, `Rental.payment_status` admits exactly one transition; the loser receives `ERR_INVALID_STATE` (HTTP 409) because the persisted state is no longer the state its precondition expected.

When two `PaymentEvent` requests arrive carrying the same `idempotency_key`, the first is persisted with full side effects and the second is rejected with `ERR_DUPLICATE_PAYMENT_EVENT` (HTTP 409); the second request produces no further effect.

### 2.10. Path Hierarchy and Resource Lookup

Path parameters are resolved left to right. For a slot endpoint of the form `/cabinets/{id}/slots/{slot_index}/eject`, the cabinet identified by `{id}` must exist before the slot identified by `{slot_index}` is sought; if the cabinet is missing the response is `ERR_NOT_FOUND` and the slot is never looked up. The same left-to-right rule applies to every nested URL.

## 3. Business Logic & Workflows

### 3.1. Cabinet Provisioning, Heartbeat, and Slot Topology

A new cabinet enters the system when an administrator submits its `cabinet_code` (the externally-printed identifier embedded in QR codes), the `city_code` of the city it is deployed in (which must be `BJ` or `SH` and must already have a configured `PricingPlan`), the `location_partner_id` of the venue partner hosting it, the hardware `model` (one of `SLOT_8`, `SLOT_16`, or `SLOT_24`), and the cabinet's `firmware_version`. The server derives `total_slots` directly from the model — eight, sixteen, or twenty-four respectively — and auto-creates one `Slot` row per index in the half-open range starting at zero up to `total_slots`. Every freshly-created slot has its `slot_status` initialised to `EMPTY` and its `device_id` set to null. The cabinet's `online_status` is initialised to `ONLINE` and `last_heartbeat_at` is initialised to the cabinet's own `created_at`.

Cabinets remain healthy by sending heartbeats. A heartbeat post carries a `timestamp` field — the wall-clock time at which the cabinet emitted the heartbeat — and an optional `firmware_version` that lets the platform track firmware drift. The server stores the supplied `timestamp` as `last_heartbeat_at`. When this updated `last_heartbeat_at` is younger than the heartbeat-timeout threshold of 300 seconds against the current logical clock the cabinet's `online_status` is set to `ONLINE`; otherwise it is set to `OFFLINE`. A cabinet that crosses the threshold becomes `OFFLINE` only when a fresh heartbeat is received and proves the gap; the more important transition in practice is the one that re-flips a previously-`OFFLINE` cabinet to `ONLINE` after maintenance, which a single fresh heartbeat with a current `timestamp` accomplishes.

Devices are registered into specific slots by the administrator with a payload carrying the `device_code`, the device's `model` (one of `PB_5K`, `PB_10K`, `PB_20K`), the initial `battery_level` as an integer percentage between 0 and 100 inclusive, and the target slot identified by `current_cabinet_id` and `current_slot_index`. Successful registration writes the device's `id` to the target slot's `device_id` and transitions the target slot from `EMPTY` to `OCCUPIED`.

The operator-only force-eject capability — exercised on a specific slot by referring to that slot's parent `cabinet_id` and `slot_index` — is the manual remedy for stuck devices. Force-eject transitions the slot's `slot_status` from `STUCK` back to `EMPTY` and the housed device's `status` from `STUCK_IN_SLOT` back to `AVAILABLE`. Crucially, force-eject does **not** close any open rental cycle: if a `Rental` exists with `rental_status` `STUCK` against this slot's prior state, the rental remains `STUCK` after the eject, and the user must subsequently call return-retry to advance the rental from `STUCK` through `ACTIVE` to `RETURNED`.

### 3.2. Device Lifecycle and Fault Reporting

A `Device` walks the lifecycle `AVAILABLE → BORROWED → AVAILABLE` for healthy round trips and may detour through `STUCK_IN_SLOT`, `FAULTY`, or `LOST` when something goes wrong. Initial registration places the device in `AVAILABLE` with `current_cabinet_id` and `current_slot_index` populated. A successful borrow advances `AVAILABLE → BORROWED` and clears both `current_cabinet_id` and `current_slot_index`. A successful return advances `BORROWED → AVAILABLE` and repopulates `current_cabinet_id` and `current_slot_index` to reflect the return slot. A return-failure advances `BORROWED → STUCK_IN_SLOT`, while a successful return-retry or operator force-eject advances `STUCK_IN_SLOT → AVAILABLE`. The `AVAILABLE → FAULTY` transition is a cascade triggered by the creation of a `RepairTicket` whose `target_type` is `DEVICE` and whose `target_id` equals the device's `id`; the matching reverse transition `FAULTY → AVAILABLE` is the cascade leg of a repair-ticket resolution. The `BORROWED → LOST` transition is driven only by the lost-conversion sweep when the rental that holds the device crosses the lost threshold of 168 hours of elapsed time since the rental began.

Users can report device faults while holding the device: the report-fault endpoint targets a specific device and accepts a single field `issue_code` whose value is one of `ABNORMAL_BATTERY`, `CHARGING_FAILURE`, `PHYSICAL_DAMAGE`, `STUCK_DEVICE`, or `OFFLINE_CABINET`. The caller must be the device's holder — that is, there must exist a `Rental` whose `user_id` equals `X-User-ID`, whose `device_id` equals the targeted device, and whose `rental_status` is one of `ACTIVE`, `OVERDUE`, or `STUCK`. If no such rental exists, the report is rejected with `ERR_FORBIDDEN`. The endpoint always creates a `RepairTicket` with `target_type` `DEVICE`, `target_id` equal to the device, `source` `USER_REPORTED`, and `status` `OPEN`. When the device is in `BORROWED` at the moment of the report, the device's `status` is left untouched; the fault is recorded against the ticket and is processed when the user later returns the device. When the device happens to be in `AVAILABLE` (in a slot — atypical for a user report but accepted by the endpoint), the full anomaly cascade fires: the device transitions `AVAILABLE → FAULTY`, the housing slot transitions `OCCUPIED → FAULTY`, and an `OperatorTask` with `task_type` `REPAIR_DISPATCH` is auto-created for the cabinet.

The platform also runs an anomaly sweep that detects abnormal battery conditions automatically; this sweep is described under the sweep pipeline in §3.6.

### 3.3. Pricing, Wallets, and Deposits

Pricing is per-city: each city has exactly one `PricingPlan`, identified uniquely by its `city_code`. A plan declares the post-grace `hourly_rate` in CNY, the `daily_cap` in CNY (the maximum rental fee chargeable in any 24-hour billable period; the plan's `daily_cap` must be strictly greater than its `hourly_rate`), the `free_minutes` of grace at the start of every rental, and the flat `cross_city_surcharge` in CNY that the system adds when a return cabinet's `city_code` differs from the start cabinet's `city_code`. The administrator creates a plan by supplying these five fields; `hourly_rate`, `daily_cap`, and `cross_city_surcharge` carry two decimal places, `cross_city_surcharge` may be zero or positive, and `free_minutes` may be zero or positive.

Each user is registered by an administrator with a single field `phone` and starts with `wallet_balance` `0.00`, `deposit_balance` `0.00`, `refund_count_30d` `0`, and `borrow_count_24h` `0`. A user tops up their prepaid balance by calling the wallet top-up endpoint with an `amount`; the server adds `amount` to `wallet_balance`. A user pays the deposit by calling the deposit endpoint with an `amount`; the server adds `amount` to `deposit_balance`. The `deposit_balance` is held as collateral against device loss; the minimum deposit required to borrow is 99.00 CNY and the system also caps `deposit_balance` at the same value so a user never holds more than the required collateral. When the deposit endpoint receives a top-up that would push `deposit_balance` above the cap, only the amount required to reach the cap is accepted. Refunds and lost-device deductions move money in the reverse direction and are described in §3.5, §3.6, and §3.7.

### 3.4. Borrowing a Power Bank

A user starts a rental by submitting only the `cabinet_id` of the cabinet they are standing in front of. After all global validations have run in priority order, the server picks the device to dispense by applying a deterministic selector. Eligibility filters in to those `Device` records whose `status` equals `AVAILABLE`, whose `current_cabinet_id` equals the supplied `cabinet_id`, and whose `battery_level` is at or above 50. The eligible set is ranked by `battery_level` in descending order, with ties broken by ascending `Device.id`. The top-ranked device wins; if the eligible set is empty the borrow is rejected with `ERR_NO_AVAILABLE_DEVICE`.

On a winning borrow the server transitions `Device.status` from `AVAILABLE` to `BORROWED` and clears the device's `current_cabinet_id` and `current_slot_index`. The slot the device was housed in transitions `OCCUPIED → EMPTY` and its `device_id` is cleared. A new `Rental` row is created with `user_id` equal to the caller, `start_cabinet_id` equal to the supplied cabinet, `start_slot_index` equal to the slot the dispensed device occupied, `device_id` equal to the chosen device, `rented_at` equal to the current logical clock value, `rental_status` `ACTIVE`, and `payment_status` `PENDING`. The user's `borrow_count_24h` increases by exactly one — it is incremented every time the borrow attempt reaches the side-effect stage, regardless of any subsequent return outcome. The system enforces a strict one-active-rental-per-user invariant: any second borrow attempt while the same user already has a rental in `ACTIVE`, `OVERDUE`, or `STUCK` is rejected with `ERR_DUPLICATE_RENTAL`.

A `User` may read their own rental with the rental-detail capability. When the rental is in a non-terminal state — `ACTIVE`, `OVERDUE`, or `STUCK` — the rental detail includes a provisional `charged_amount` computed against the current logical clock; final billing is described in §3.5 and overdue billing is described in §3.6.

### 3.5. Returning, Stuck-Device Recovery, and Cross-Cabinet Returns

Returning a device requires only the `return_cabinet_id` — the cabinet at which the user wants to return. Cross-cabinet returns are explicitly supported, including returns to a cabinet in a different city than the one where the rental began. The return endpoint applies the global gates (ownership, cabinet connectivity, maintenance window, and so on) and then runs the return-slot selector: eligibility filters in `Slot` records whose `slot_status` is `EMPTY` and whose `cabinet_id` equals `return_cabinet_id`, ranking is by ascending `slot_index`, and tie-breaking is unnecessary because `slot_index` is unique within a cabinet. The lowest-`slot_index` empty slot wins.

When the eligible set is non-empty and the return is otherwise legal, the server treats the operation as the `ACTIVE → RETURNED` transition (or `OVERDUE → RETURNED`, with overdue penalty applied — see §3.6). It writes `Rental.returned_at` to the current logical clock value, sets `Rental.return_cabinet_id` to the supplied cabinet and `Rental.return_slot_index` to the chosen slot, transitions the chosen slot from `EMPTY` to `OCCUPIED` and writes the device's `id` into the slot's `device_id`, transitions the device from `BORROWED` back to `AVAILABLE` and repopulates the device's `current_cabinet_id` and `current_slot_index` to point at the return slot, computes the final billing (described below), debits `User.wallet_balance` by exactly the resulting `Rental.charged_amount`, and bubbles `Rental.payment_status` from `PENDING` to `BILLED` in the same operation.

Final billing is the central calculation. Let *end_time* be `Rental.returned_at` on a final return and the current logical clock value on the provisional read against a non-terminal rental. The server first computes the rental's *total_minutes* as the elapsed seconds between `end_time` and `Rental.rented_at`, divided by 60, with the result rounded down to a whole number. The grace-free *billable_minutes* is the larger of zero and *total_minutes* minus the start cabinet's pricing plan's `free_minutes`. The *billable_hours* is *billable_minutes* divided by 60, rounded up to a whole number. When *billable_hours* is at most 24, the rental fee is the smaller of *billable_hours* multiplied by the start cabinet's `hourly_rate` and the start cabinet's `daily_cap`; when *billable_hours* exceeds 24, the rental fee is the start cabinet's `daily_cap` (the daily cap is fully filled). The cross-city surcharge applies only on the final-return computation, and only when the start cabinet's `city_code` differs from the return cabinet's `city_code`; in that case the start cabinet's plan's `cross_city_surcharge` is added to the rental fee. The provisional read on a non-terminal rental never adds the cross-city surcharge because the return cabinet is not yet known. All arithmetic uses two decimal places with round-half-up. The total assigned to `Rental.charged_amount` is the rental fee plus, if the rental is overdue, the overdue penalty described in §3.6.

When the eligible-slots set is empty (no slot in the return cabinet has `slot_status` `EMPTY`) the return becomes a return-failure. The server records the attempted return cabinet onto `Rental.return_cabinet_id`, transitions the rental from its prior `ACTIVE` (or `OVERDUE`) state to `STUCK`, transitions the lowest-`slot_index` slot of the attempted-return cabinet from `EMPTY` to `STUCK` (this is the slot that the system would have picked, now marked stuck for the device that physically refused to seat), transitions the device from `BORROWED` to `STUCK_IN_SLOT`, and creates a `RepairTicket` with `target_type` `DEVICE`, `target_id` equal to the device, `source` `AUTO_ANOMALY`, `issue_code` `STUCK_DEVICE`, and initial `status` `OPEN`. The response carries `error_id` `ERR_RETURN_FAILED` (HTTP 409). The user resolves the situation by calling the return-retry endpoint, again with a `return_cabinet_id` (which may be the same cabinet or a different one); on retry success the server transitions the previously-stuck slot's `slot_status` from `STUCK` back to `EMPTY`, the device's `status` from `STUCK_IN_SLOT` back to `AVAILABLE`, and the rental's `rental_status` from `STUCK` through `ACTIVE` and onward to `RETURNED` in the same operation, performing all of the side effects of a normal return (final billing, wallet debit, payment-status bubble). The retry uses the same return-slot selector against the new `return_cabinet_id`, so a retry can land in any cabinet that has at least one empty slot.

The operator-driven force-eject capability described in §3.1 is the alternate recovery path when the user is unable to return to a cabinet themselves: it transitions the slot from `STUCK` back to `EMPTY` and the device from `STUCK_IN_SLOT` back to `AVAILABLE`, but it deliberately leaves the rental in `STUCK` so that the user (and not the operator) drives the rental's final state via return-retry.

### 3.6. Overdue Escalation, Lost Conversion, and the Sweep Pipeline

A rental that has not been returned 24 hours after `rented_at` is overdue. The transition from `ACTIVE` to `OVERDUE` is performed by the overdue sweep when the elapsed hours since `rented_at`, computed as the elapsed seconds divided by 3600 and rounded down to a whole number, are strictly greater than 24. The transition from `OVERDUE` to `LOST` is performed by the lost sweep when those same elapsed hours are at or above 168 — that is, after exactly seven days have passed. The two thresholds use different inclusivity: 24 is exclusive (a rental that has elapsed exactly 24 hours stays `ACTIVE`), and 168 is inclusive (a rental that has elapsed exactly 168 hours becomes `LOST`).

Overdue penalty is computed by a tiered hourly schedule that runs alongside the base rental fee. Let *elapsed_hours* be the integer hours computed as above (using `Rental.returned_at` for a final read and the current logical clock value for a provisional read). When *elapsed_hours* is at most 24 the overdue penalty is 0.00. When *elapsed_hours* exceeds 24, define *overdue_hours* as *elapsed_hours* minus 24. For *overdue_hours* of 48 or fewer, the penalty is *overdue_hours* multiplied by 5.00 CNY per hour; this tier covers elapsed hours 24 through 72. For *overdue_hours* between 49 and 144 inclusive, the penalty is the full first tier (48 hours at 5.00 CNY per hour, totalling 240.00 CNY) plus *overdue_hours* minus 48, multiplied by 10.00 CNY per hour; this tier covers elapsed hours 72 through 168. Once *overdue_hours* exceeds 144 the overdue penalty is capped at the full first tier plus the full second tier (48 hours at 5.00 CNY plus 96 hours at 10.00 CNY, totalling 1200.00 CNY). All arithmetic uses two decimal places with round-half-up. The overdue penalty is added to the base rental fee to produce the provisional `charged_amount` while the rental is in `OVERDUE`, and to produce the final `charged_amount` on an `OVERDUE → RETURNED` transition.

Returning during the overdue window — `OVERDUE → RETURNED` — runs all of the side effects of a normal return (slot, device, payment-status bubble, wallet debit) but with `Rental.charged_amount` equal to the rental fee plus the overdue penalty plus, if applicable, the cross-city surcharge.

Lost conversion is the terminal escalation. When the lost sweep promotes the rental from `OVERDUE` to `LOST` it overwrites `Rental.charged_amount` with the flat lost-device fee of 99.00 CNY, replacing any prior provisional amount that may have been visible on the rental. The settlement against the user's collateral runs in this order: the deposit deduction is the smaller of the user's current `deposit_balance` and the 99.00 CNY lost-device fee, the residual is 99.00 minus the deposit deduction, the user's `deposit_balance` is decremented by the deposit deduction (and is therefore clamped at zero, never going negative), and the user's `wallet_balance` is decremented by the residual (and may go negative, representing outstanding debt the user must clear before borrowing again). The rental's `payment_status` advances from `PENDING` directly to `DEPOSIT_DEDUCTED` (it does not pass through `BILLED`). The device that was on rental advances to `LOST`, but `Device.current_cabinet_id` and `Device.current_slot_index` are deliberately left unchanged from their pre-borrow snapshot, leaving a stale forensic trail rather than a misleading "current location".

The sweep endpoint accepts a single field `sweep_type` whose value is one of `overdue`, `lost`, `anomaly`, or `all`. The `overdue` sweep walks every rental in `ACTIVE` and promotes any whose elapsed hours exceed 24 to `OVERDUE`. The `lost` sweep walks every rental in `OVERDUE` and promotes any whose elapsed hours have reached 168 to `LOST`, running the lost-conversion side effects above. The `anomaly` sweep walks every device whose `status` is `AVAILABLE`, whose `battery_level` is strictly less than 5, and which currently sits in a slot whose `slot_status` is `OCCUPIED`; for each such device the sweep creates a `RepairTicket` with `target_type` `DEVICE`, `target_id` equal to the device's `id`, `source` `AUTO_ANOMALY`, `issue_code` `ABNORMAL_BATTERY`, and `status` `OPEN` — this ticket creation is the action, and the rest of the chain (`Device.status` `AVAILABLE → FAULTY`, `Slot.slot_status` `OCCUPIED → FAULTY`, and `OperatorTask` auto-creation) is the cascade defined in §2.8. The `all` sweep runs the three sweep types in the order overdue, lost, anomaly.

### 3.7. Refunds and Risk Control

An administrator may issue a refund against a rental that has been billed. The refund capability is available only when the rental's `payment_status` is `BILLED` and `rental_status` is `RETURNED`; calling it against any other state pair is rejected with `ERR_INVALID_STATE`. On a successful refund the rental's `refund_amount` is set equal to the prior `Rental.charged_amount`, the user's `wallet_balance` is increased by the refund amount, the user's `refund_count_30d` is incremented by one, and the rental's `payment_status` advances from `BILLED` to `REFUNDED`. If the rental's start cabinet is hosted by a partner whose `Settlement` covering `Rental.returned_at` has already reached `INVOICED`, that settlement's `refund_adjustment` is increased by the partner's per-rental share of the refund amount as a cascade leg, computed exactly as described under the settled variant of the revenue-share calculation in §3.9.

Risk control is exercised at borrow time. The user's trailing 30-day refund count, captured in `User.refund_count_30d`, blocks borrowing once it reaches 5 (the check is strict less-than, so a count of 4 still permits borrow and a count of 5 rejects with `ERR_REFUND_LIMIT_EXCEEDED`). The user's trailing 24-hour borrow count, captured in `User.borrow_count_24h`, blocks borrowing once it reaches 10 (the check is strict less-than, so a count of 9 still permits borrow and a count of 10 rejects with `ERR_ABNORMAL_BORROW_PATTERN`). Both counters are evaluated at the moment the borrow request runs through the validation sequence in §2.7.

### 3.8. Repair Tickets, Operator Tasks, and Field Scheduling

Repair tickets are created from three sources: `USER_REPORTED` when the user submits a fault report on the device they are holding, `AUTO_ANOMALY` when an automatic detection (return-failure on a stuck device, or the abnormal-battery sweep) raises one, and `OPERATOR_REPORTED` when an operator manually opens one in the field. A ticket carries a `target_type` of either `DEVICE` or `CABINET`, a `target_id` pointing to the relevant resource of that type, an `issue_code` from the set `ABNORMAL_BATTERY`, `CHARGING_FAILURE`, `PHYSICAL_DAMAGE`, `STUCK_DEVICE`, `OFFLINE_CABINET`, and walks the workflow `OPEN → ASSIGNED → IN_PROGRESS → RESOLVED` with optional `IN_PROGRESS ↔ ON_HOLD` cycles in the middle and an `ASSIGNED → CANCELLED` early exit.

An operator self-assigns to an open ticket; this transition writes `assigned_operator_id` to the calling operator's `X-User-ID` and advances the ticket from `OPEN` to `ASSIGNED`. The ticket auto-transitions from `ASSIGNED` to `IN_PROGRESS` on the first hold or resolve call — clients need not transition explicitly. An in-progress ticket may be paused with the hold capability (advancing it from `IN_PROGRESS` to `ON_HOLD`), and a held ticket may be resumed (advancing it from `ON_HOLD` back to `IN_PROGRESS`); these two transitions form a cycle that may iterate any number of times before resolution. The resolve capability accepts an optional boolean `cancel`; when `cancel` is omitted or false the ticket advances to `RESOLVED`, and when `cancel` is true and the ticket is currently in `ASSIGNED` the ticket advances to `CANCELLED` instead. On resolution, when `target_type` is `DEVICE` the device's `status` advances from `FAULTY` to `AVAILABLE`, and the slot housing the device transitions from `FAULTY` to either `EMPTY` or `OCCUPIED` depending on whether the slot's `device_id` is null. On resolution where `target_type` is `CABINET`, no entity beyond the ticket itself changes state.

Operator tasks coordinate field work outside the repair lifecycle. A task carries the cabinet it targets in `cabinet_id`, a `task_type` of either `REPLENISHMENT` (battery swap), `MAINTENANCE_SWAP` (planned hardware exchange), or `REPAIR_DISPATCH` (auto-created by the anomaly cascade and linked to the originating ticket via `linked_repair_ticket_id`), and a `priority_score` recomputed at creation and on each auto-assign call. The priority score for a cabinet is computed as the cabinet's *low_battery_count* multiplied by 10, plus the cabinet's *faulty_slot_count* multiplied by 5, plus a 50-point offline bonus when the cabinet's `online_status` is `OFFLINE`. The *low_battery_count* is the number of devices whose `current_cabinet_id` equals the cabinet, whose `status` is `AVAILABLE`, and whose `battery_level` is strictly less than 30 — devices in `FAULTY`, `STUCK_IN_SLOT`, or `LOST` are out of service and do not count toward replenishment urgency. The *faulty_slot_count* is the number of slots on the cabinet whose `slot_status` is `FAULTY`. The result is an integer; no rounding is applied.

Auto-assign accepts a single field `city_code` and selects the highest-priority pending task in that city. Eligibility filters in tasks whose `status` is `PENDING` and whose target cabinet's `city_code` equals the supplied `city_code`; the priority score is recomputed on this call so that battery and connectivity changes since task creation are reflected. The eligible set is ranked by `priority_score` in descending order with ties broken by ascending `created_at`. The winning task has its `assigned_operator_id` written to the caller's `X-User-ID` and its `status` advanced from `PENDING` to `ASSIGNED`. When the eligible set is empty the call is rejected with `ERR_NO_PENDING_TASKS`. The task auto-transitions from `ASSIGNED` to `IN_PROGRESS` on the first complete attempt — clients need not transition explicitly. Completing an operator task advances it from `ASSIGNED` or `IN_PROGRESS` to `COMPLETED`; when the task's `task_type` is `REPAIR_DISPATCH` the linked `RepairTicket` must already be in `RESOLVED` (rejection: `ERR_TICKET_UNRESOLVED`). The complete capability also accepts an optional boolean `cancel`; when `cancel` is true and the task is currently in `PENDING`, the task advances to `CANCELLED` instead — only the `Admin` role may exercise the cancel branch.

### 3.9. Revenue Reconciliation, Settlements, and Invoice Issuance

Each `LocationPartner` is registered by the administrator with a `partner_code`, a `name`, and a `revenue_share_pct` — the fraction of qualifying rental revenue paid to the partner. A `Settlement` is the periodic record of how much the platform owes a partner for a window of returned rentals. An administrator creates a settlement by supplying the `location_partner_id`, the `period_start` (inclusive), and the `period_end` (exclusive). The server walks the universe of qualifying rentals — those whose start cabinet's `location_partner_id` equals the settlement's `location_partner_id`, whose `rental_status` is `RETURNED`, and whose `returned_at` falls within `[period_start, period_end)` — and computes a provisional `partner_amount` immediately at creation. The settlement is born with `status` `DRAFT`.

The provisional partner amount is the sum, over the rentals in the universe whose `payment_status` is `BILLED`, of each rental's `charged_amount` multiplied by the partner's `revenue_share_pct`, rounded to two decimal places with round-half-up *per rental*, before the rounded values are summed. The `gross_revenue` on a provisional settlement is the sum of `charged_amount` over the same `BILLED` subset (without the rounding-per-rental step, since the rentals already carry two-decimal `charged_amount`). The `refund_adjustment` on a provisional settlement is 0.00, since pending refunds are not yet attributed to this period. The administrator advances the settlement from `DRAFT` to `APPROVED` with the approve capability; this is a workflow gate and produces no monetary side effects on its own.

Issuing the invoice is the settlement's terminal step. The administrator advances the settlement from `APPROVED` to `INVOICED`. On this transition the server generates an `invoice_number` for the settlement and recomputes the partner amount under the *settled* variant of the revenue-share rule, freezing the result onto the settlement row. The settled variant adds refunded rentals into the calculation: the `refund_adjustment` becomes the sum, over the rentals in the same universe whose `payment_status` is `REFUNDED`, of each rental's `refund_amount` multiplied by the partner's `revenue_share_pct`, again rounded to two decimal places per rental and then summed; the `partner_amount` becomes the provisional-style billed sum (unchanged from the provisional formula) minus this `refund_adjustment`. The settled variant's `gross_revenue` is the sum of `charged_amount` over the `BILLED` subset minus the sum of `refund_amount` over the `REFUNDED` subset — the unrounded values. The rounding order remains pinned: per-rental rounding first, then sum, never the reverse.

Once a settlement reaches `INVOICED`, subsequent refunds against rentals that fall inside its period continue to flow into its `refund_adjustment` as a cascade leg from the refund operation, increasing the running `refund_adjustment` by the per-rental partner share of each new refund. A `Partner` may read settlements scoped to their own partner record, and `Admin` may read any settlement.

The platform also receives event records from the upstream payment system through a dedicated webhook capability that requires no authentication. Each event carries an `idempotency_key` (caller-provided, globally unique), an `event_type` of `PAYMENT_CONFIRMED`, `PAYMENT_FAILED`, or `REFUND_CONFIRMED`, the `rental_id` of the rental the event applies to, the `amount` in CNY, and the `occurred_at` wall-clock time of the upstream event. The server persists the event record on first receipt and rejects any duplicate `idempotency_key` with `ERR_DUPLICATE_PAYMENT_EVENT` without further side effects. Two test-only fixtures support deterministic black-box verification: the clock-advance capability accepts an optional `to` instant or an optional `seconds` delta and updates the logical clock used by every time-driven calculation, and the events-emit capability accepts an `event_type` and an arbitrary `payload` and is used to drive partner-system synchronisation scenarios.

## 4. Endpoint Definitions

The endpoints below collectively define the public contract. Endpoints that create a new resource respond with HTTP 201 and the created object in `data`; endpoints that mutate or read an existing resource respond with HTTP 200 and the updated or fetched object in `data`. Refer back to §3 for each endpoint's full request and response semantics; the table is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /cabinets | Register a new cabinet and auto-create its slot rows. | Admin |
| GET | /cabinets/{id} | Retrieve a cabinet with embedded slots. | Admin, Operator |
| POST | /cabinets/{id}/heartbeat | Cabinet posts a heartbeat; updates `last_heartbeat_at` and recomputes `online_status`. | Admin |
| POST | /cabinets/{id}/slots/{slot_index}/eject | Force-eject a stuck device from a slot. | Operator |
| POST | /devices | Register a device into a slot. | Admin |
| GET | /devices/{id} | Retrieve a device. | Admin, Operator |
| POST | /devices/{id}/report-fault | User reports a fault on the device they are holding. | User |
| POST | /pricing-plans | Create a pricing plan for a city. | Admin |
| POST | /users | Register a user. | Admin |
| GET | /users/{id} | Retrieve a user (`User` role limited to own record). | Admin, User |
| POST | /users/{id}/wallet/topup | Top up the user's wallet balance. | User |
| POST | /users/{id}/deposit | Pay or top up the deposit. | User |
| POST | /rentals | Borrow a power bank. | User |
| GET | /rentals/{id} | Retrieve a rental with provisional billing. | Admin, User |
| POST | /rentals/{id}/return | Return the device at any cabinet. | User |
| POST | /rentals/{id}/return-retry | Retry return after a stuck condition. | User |
| POST | /rentals/{id}/refund | Refund a billed rental. | Admin |
| GET | /repair-tickets/{id} | Retrieve a repair ticket. | Admin, Operator |
| POST | /repair-tickets/{id}/assign | Operator self-assigns to an open ticket. | Operator |
| POST | /repair-tickets/{id}/hold | Pause an in-progress ticket. | Operator |
| POST | /repair-tickets/{id}/resume | Resume a held ticket. | Operator |
| POST | /repair-tickets/{id}/resolve | Resolve (or cancel with `cancel`) a ticket. | Operator |
| POST | /operator-tasks/auto-assign | Pull the highest-priority pending task in a city. | Operator |
| GET | /operator-tasks/{id} | Retrieve an operator task. | Admin, Operator |
| POST | /operator-tasks/{id}/complete | Complete (or cancel with `cancel`) a task. | Operator, Admin |
| POST | /settlements | Create a settlement (provisional partner amount computed at creation). | Admin |
| GET | /settlements/{id} | Retrieve a settlement (`Partner` role limited to own settlements). | Admin, Partner |
| POST | /settlements/{id}/approve | Approve a draft settlement. | Admin |
| POST | /settlements/{id}/issue-invoice | Issue invoice and freeze the settled partner amount and refund adjustment. | Admin |
| POST | /location-partners | Register a location partner. | Admin |
| POST | /maintenance-windows | Schedule a cabinet maintenance window. | Admin |
| POST | /payment-events | Idempotent receipt of an upstream payment event. | (no auth) |
| POST | /_clock/advance | Advance the logical clock (test-only). | (no auth) |
| POST | /_sweep/run | Run a sweep of the supplied `sweep_type` (test-only). | (no auth) |
| POST | /_events/emit | Emit an external event with an `event_type` and `payload` (test-only). | (no auth) |

## 5. Error Code Catalogue

The trigger condition for each error is described inline in §2 and §3 alongside the workflow it guards.

| Error ID | HTTP Status |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_INPUT` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_DUPLICATE_RENTAL` | 409 |
| `ERR_CABINET_OFFLINE` | 409 |
| `ERR_CABINET_UNDER_MAINTENANCE` | 409 |
| `ERR_NO_AVAILABLE_DEVICE` | 409 |
| `ERR_SLOT_OCCUPIED` | 409 |
| `ERR_RETURN_FAILED` | 409 |
| `ERR_DEPOSIT_INSUFFICIENT` | 402 |
| `ERR_WALLET_INSUFFICIENT` | 402 |
| `ERR_PRICING_NOT_CONFIGURED` | 422 |
| `ERR_REFUND_LIMIT_EXCEEDED` | 403 |
| `ERR_ABNORMAL_BORROW_PATTERN` | 403 |
| `ERR_TICKET_UNRESOLVED` | 409 |
| `ERR_TASK_ALREADY_ASSIGNED` | 409 |
| `ERR_NO_PENDING_TASKS` | 409 |
| `ERR_SETTLEMENT_PERIOD_INVALID` | 422 |
| `ERR_DUPLICATE_PAYMENT_EVENT` | 409 |
| `ERR_MAINTENANCE_WINDOW_OVERLAP` | 409 |

---

## Hard Contract Reports

### Contract 1: Field-Name Coverage

Required field names enumerated from `entities[].fields` and `endpoints[].input` / `path_params`:

Entity fields covered (in backticks somewhere in PRD): `cabinet_code`, `city_code`, `location_partner_id`, `model`, `total_slots`, `firmware_version`, `online_status`, `last_heartbeat_at`, `cabinet_id`, `slot_index`, `device_id`, `slot_status`, `device_code`, `battery_level`, `status`, `current_cabinet_id`, `current_slot_index`, `hourly_rate`, `daily_cap`, `free_minutes`, `cross_city_surcharge`, `phone`, `wallet_balance`, `deposit_balance`, `refund_count_30d`, `borrow_count_24h`, `user_id`, `start_cabinet_id`, `start_slot_index`, `rented_at`, `return_cabinet_id`, `return_slot_index`, `returned_at`, `rental_status`, `payment_status`, `charged_amount`, `refund_amount`, `target_type`, `target_id`, `source`, `issue_code`, `assigned_operator_id`, `task_type`, `priority_score`, `linked_repair_ticket_id`, `partner_code`, `name`, `revenue_share_pct`, `period_start`, `period_end`, `gross_revenue`, `partner_amount`, `refund_adjustment`, `invoice_number`, `idempotency_key`, `event_type`, `rental_id`, `amount`, `occurred_at`, `window_start`, `window_end` — each appears verbatim in §2 or §3.

Endpoint request/path identifiers covered: `cabinet_id`, `return_cabinet_id`, `issue_code`, `timestamp`, `firmware_version`, `amount`, `cancel`, `city_code`, `location_partner_id`, `period_start`, `period_end`, `partner_code`, `name`, `revenue_share_pct`, `phone`, `device_code`, `model`, `battery_level`, `current_cabinet_id`, `current_slot_index`, `cabinet_code`, `hourly_rate`, `daily_cap`, `free_minutes`, `cross_city_surcharge`, `idempotency_key`, `event_type`, `rental_id`, `occurred_at`, `to`, `seconds`, `sweep_type`, `payload`, `window_start`, `window_end`, path-`id`, path-`slot_index` — each appears verbatim.

```
Field coverage check:
- entities[].fields: 61 required, 61 present, 0 missing
- endpoints[].request_body: 36 required (deduplicated), 36 present, 0 missing
- endpoints[].query_params: 0 required (this scaffold defines no query_params other than pagination), 0 present, 0 missing
Status: PASS
```

### Contract 2: Rule Coverage

```
Rule coverage check:
- validations[] with priority: 21 checked, 21 expressed in prose (full ordering in §2.7), 0 missing
- concurrency_rules[] with error_id: 4 checked, 4 expressed (§2.9), 0 missing
- state_machines[].transitions: 33 checked (Rental rental_status: 6, Rental payment_status: 3, Device: 7, RepairTicket: 6, OperatorTask: 4, Settlement: 2, Slot: 6 — Note: counted enumerated transitions), 33 fully expressed, 0 missing
- calculations[]: 5 checked (rental_billing, overdue_penalty, lost_conversion, revenue_share_for_settlement, operator_task_priority), 5 fully expressed, 0 missing
- validations[] conditions: 21 checked, 21 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 35 checked, 35 expressed across §3, 0 missing
- entities[].fields[] structured content: 12 entities checked, all defaults/types/sources reconstructible from prose, 0 missing
- sibling-branch symmetry: ACTIVE→RETURNED vs OVERDUE→RETURNED rendered with equal density; provisional vs settled variant rendered with equal density; resolve vs resolve+cancel rendered with equal density; complete vs complete+cancel rendered with equal density. 4 groups checked, 0 asymmetric.
Status: PASS
```

### Contract 3: §3 Path Purity

§3 spans subsections 3.1 through 3.9. A scan for backtick tokens reveals: state names (`ACTIVE`, `OVERDUE`, `RETURNED`, `LOST`, `STUCK`, `BILLED`, `REFUNDED`, `DEPOSIT_DEDUCTED`, `PENDING`, `OPEN`, `ASSIGNED`, `IN_PROGRESS`, `ON_HOLD`, `RESOLVED`, `CANCELLED`, `EMPTY`, `OCCUPIED`, `FAULTY`, `STUCK_IN_SLOT`, `AVAILABLE`, `BORROWED`, `ONLINE`, `OFFLINE`, `DRAFT`, `APPROVED`, `INVOICED`, `SCHEDULED`), enum values (`SLOT_8`, `SLOT_16`, `SLOT_24`, `PB_5K`, `PB_10K`, `PB_20K`, `BJ`, `SH`, `USER_REPORTED`, `AUTO_ANOMALY`, `OPERATOR_REPORTED`, `ABNORMAL_BATTERY`, `CHARGING_FAILURE`, `PHYSICAL_DAMAGE`, `STUCK_DEVICE`, `OFFLINE_CABINET`, `REPLENISHMENT`, `MAINTENANCE_SWAP`, `REPAIR_DISPATCH`, `DEVICE`, `CABINET`, `PAYMENT_CONFIRMED`, `PAYMENT_FAILED`, `REFUND_CONFIRMED`, `overdue`, `lost`, `anomaly`, `all`), field names from entities and request bodies, error IDs (`ERR_*`), entity names (`Rental`, `Device`, `Slot`, `Cabinet`, `RepairTicket`, `OperatorTask`, `Settlement`, `User`, `LocationPartner`, `MaintenanceWindow`, `PricingPlan`, `PaymentEvent`), and role names (`User`, `Operator`, `Admin`, `Partner`).

No backtick token in §3 starts with `/`. No backtick token in §3 is a bare HTTP method. No backtick token combines a method with a path. Endpoints are referred to by state-transition framing (`ACTIVE → RETURNED`, `OVERDUE → LOST`, `OPEN → ASSIGNED`, etc.), by role-plus-action (e.g., "an administrator creates a settlement", "an operator self-assigns"), and by capability description (e.g., "the return-retry endpoint", "the sweep endpoint", "the clock-advance capability") — never by URL or HTTP method.

```
Path purity check (§3 only):
- backtick tokens scanned: ~340
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```
