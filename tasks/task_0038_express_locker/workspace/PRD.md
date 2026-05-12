# Express Locker API — Product Requirements Document

## 1. Introduction

The Express Locker API governs a network of unattended parcel-locker installations that bridge couriers and recipients in last-mile delivery. Each physical installation is a multi-compartment cabinet that must be remotely supervised — its online state must be tracked, its firmware kept above a minimum baseline, its compartments allocated by size, and its occupancy gauged in real time so that arriving couriers are not directed to a cabinet that cannot accept their parcel.

Three operational tensions shape the system. First, deposits and pickups are physical events: a compartment must actually open, sometimes after multiple retries, and the digital state must mirror what happened in the cabinet. Second, parcels left unattended accrue overtime fees on a tiered schedule, and the timing of fee freezing relative to recipient action is itself a business rule rather than an implementation accident. Third, the network depends on courier behaviour — wrong deposits, unresolved complaints, and capacity-warned cabinets together drive a rating mechanism that can restrict or blacklist a courier without operator intervention. The API therefore combines transactional locker operations, a tiered pricing engine, a reputational gate, and a periodic revenue-settlement workflow.

The remainder of this document specifies the contracts, cross-cutting principles, and business workflows that any conforming implementation must honour.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The API surface is mounted under `/locker-machines` and adjacent top-level resources (`/couriers`, `/parcels`, `/disputes`, `/settlements`, plus a small set of test-driving and event-ingress endpoints).

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, declaring the operational capacity in which the call is being made. The system recognises four role names, spelled exactly: `OperationsAdmin`, `Courier`, `Recipient`, and `Any`. The role `Any` is a read-only convenience role granting access to public-info GETs and is not a separate identity domain.

The `Courier` role is **entity-backed**: when `X-User-Role` is `Courier`, the value of `X-User-ID` is the `id` of the acting `Courier` record, and ownership checks on any resource that references a courier (notably `Parcel.courier_id`) compare the resource's foreign key to `X-User-ID` directly.

The `OperationsAdmin`, `Recipient`, and `Any` roles use **opaque** identities. When `X-User-Role` is `OperationsAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it as `actor_id` on `AuditLog` and `CompartmentEvent` rows but does not compare it to any entity's `id`. When `X-User-Role` is `Recipient`, `X-User-ID` is likewise opaque (it conceptually represents the phone-number-bearing recipient bound to a specific parcel and is recorded into events; it is not joined against any persisted recipient entity). When `X-User-Role` is `Any`, `X-User-ID` is opaque and not compared anywhere.

Requests missing or carrying invalid values for these two headers are rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A header pair that authenticates but whose role is not permitted for the requested endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

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

For endpoints that return lists of resources, pagination is controlled by two query parameters. The `limit` parameter caps the number of items returned: when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. List endpoints return resources sorted by `created_at` in ascending order unless an endpoint description states otherwise. The `meta` object on list responses always carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most top-level resources (`LockerMachine`, `Compartment`, `Courier`, `Parcel`, `OvertimeFeeRecord`, `Dispute`, `SettlementBatch`) carry a standard set of system-managed fields: `id` is a server-minted UUID with no type prefix; `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `version` is a non-negative integer that increments by exactly one on every mutation of that record.

Two entities are append-only event records and deliberately depart from this convention. `PickupCodeAttempt` and `CompartmentEvent` carry only `id` and `created_at` — they have no `updated_at` and no `version` field, because they are never mutated after being written. The same holds for `AuditLog`, which is also append-only with only `id` and `created_at`. Any reference to "the resource's `version`" in subsequent sections excludes these three event-log entities.

### 2.5. Hierarchical Consistency and Cascading Effects

The system maintains coherence between physical-locker objects and the parcels that flow through them. A single business operation may mutate more than one entity in one step, and every such cascade must complete atomically: every entity touched has its `updated_at` refreshed to the operation's timestamp and its `version` incremented by one. For example, completing a recipient pickup advances the parcel's `status`, sets its `picked_up_at`, materialises a final-variant `OvertimeFeeRecord`, releases the compartment back to `AVAILABLE`, clears the compartment's `current_parcel_id`, and appends both a `CompartmentEvent` and an `AuditLog` row — the parcel's and compartment's `version` and `updated_at` both advance, while the freshly written event rows carry only their `created_at`.

The system also recomputes derived occupancy and rating fields on read, so that `LockerMachine.capacity_warning_level`, `LockerMachine.occupied_count_small`, `LockerMachine.occupied_count_medium`, `LockerMachine.occupied_count_large`, `LockerMachine.total_compartments`, `LockerMachine.degraded_mode`, `Courier.lifetime_deposit_count`, `Courier.lifetime_wrong_deposit_count`, `Courier.lifetime_deposit_success_rate`, `Courier.window_wrong_deposit_rate`, and `Courier.complaint_count` always reflect the current ledger of compartments and parcels.

### 2.6. Nested Resource Retrieval

Many endpoints address resources through hierarchical URL paths — for example, a compartment is reached by a path that names both its parent machine and the compartment itself. For any such request, the server validates the path identifiers strictly left-to-right: the machine is resolved before the compartment, and the parcel is resolved before any sub-resource of that parcel. A request whose first unresolvable identifier is the machine fails with `ERR_RESOURCE_NOT_FOUND` keyed to the machine, even if the inner identifiers would also have been invalid; the inner identifiers are not consulted.

### 2.7. Optimistic Concurrency Control

Mutating endpoints accept an optional `version` field in the request body. When the caller supplies a `version`, the server compares it to the entity's current `version`; a mismatch is rejected with `ERR_VERSION_CONFLICT`. Omitting `version` from the body skips the check and forces the operation through. The check applies whenever `version` is present, including on convenience endpoints that drive a state machine — implementations must surface the same error identifier in both situations.

In addition to user-visible OCC, the system enforces several first-writer-wins serialisations against simultaneous physical actions. Two couriers attempting to deposit into the same compartment in parallel will see the compartment bind to exactly one parcel; the loser receives `ERR_COMPARTMENT_ALREADY_RESERVED`. A simultaneous recipient pickup-confirm and operations recall on the same parcel will resolve to exactly one of `PICKED_UP` or `RECALLED`; the loser receives `ERR_PARCEL_STATE_CHANGED`. A wrong-deposit correction that races against a successful pickup is similarly rejected with `ERR_PARCEL_STATE_CHANGED` whenever the parcel has already advanced past `DEPOSITED`. Two `payment_succeeded` events for the same `OvertimeFeeRecord` are idempotent on `payment_external_id` — a replay of the same external identifier returns 200 with the same record (no double credit), while a second event arriving with a *different* external identifier for the same record is rejected with `ERR_DUPLICATE_PAYMENT_EVENT`. A settlement-lock attempt that races a refund of an in-window fee resolves first-writer-wins on `SettlementBatch.status`: if the lock wins, the refund still applies but is pushed into the next batch's `refund_reversal_cents`; if the refund wins, the lock proceeds normally; an attempt to mutate amounts on an already-locked batch is rejected with `ERR_SETTLEMENT_LOCKED`.

### 2.8. Monetary Precision and Tier Boundaries

All overtime amounts are tracked as **integer cents** in `amount_cents` on `OvertimeFeeRecord`. Hour buckets used in fee calculation are floored to whole hours — partial hours never produce a fractional contribution and there is no per-hour rounding. The cents totals across tiers are summed exactly. Settlement amounts are likewise tracked in integer cents, and the partner's share is taken first by floor before the platform's residual is computed; this ordering is fixed and is described precisely in §3.

### 2.9. Validation Priority

When several validations could fire on a single request, they are evaluated in a fixed priority order so that error responses are deterministic. Header validity comes first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role-based authorisation (`ERR_INSUFFICIENT_PERMISSIONS`), then path-resource existence checked left-to-right (`ERR_RESOURCE_NOT_FOUND`). For deposit creation specifically, machine-degraded-mode comes next (`ERR_MACHINE_OFFLINE_DEGRADED`), then state checks (`ERR_PARCEL_STATE_CHANGED` on already-advanced parcels), then courier reputational gating (`ERR_COURIER_BLACKLISTED` and `ERR_COURIER_RESTRICTED`), then ownership for courier-only operations (`ERR_NOT_COURIER_OWNER`), then the wrong-deposit grace window (`ERR_WRONG_DEPOSIT_GRACE_EXPIRED`), then fit-by-size (`ERR_NO_COMPARTMENT_FITS`), then capacity gating (`ERR_CAPACITY_BLOCKED`), then the pickup-code authentication checks (`ERR_INVALID_PICKUP_CODE`), then the fee-payment gate (`ERR_FEE_PAYMENT_REQUIRED`), then settlement-window readiness (`ERR_PENDING_FEES_IN_WINDOW`), then idempotency (`ERR_DUPLICATE_PAYMENT_EVENT`), and finally OCC (`ERR_VERSION_CONFLICT`). Earlier checks pre-empt later ones — a deposit submitted with a missing header surfaces the header error rather than a downstream business error, and a wrong-deposit correction by a non-owner courier surfaces `ERR_NOT_COURIER_OWNER` even when the grace window has also expired.

### 2.10. Audit and Event Logs

Every compartment-opening event (deposit, pickup, recall, disposal, and operator-driven out-of-service toggles) appends a `CompartmentEvent` whose `event_type` is one of `DEPOSIT_OPEN_OK`, `DEPOSIT_OPEN_FAILED`, `PICKUP_OPEN_OK`, `PICKUP_OPEN_FAILED`, `RECALL_OPEN_OK`, `DISPOSAL_OPEN_OK`, or `OUT_OF_SERVICE_TOGGLE`. The `actor_role` of each event is one of `Courier`, `Recipient`, `OperationsAdmin`, or the literal string `system` for automatic transitions; the `actor_id` is the `X-User-ID` of the acting role, or `system` for automatic events; the `parcel_id` is the associated parcel's id, or null on `OUT_OF_SERVICE_TOGGLE` events that do not involve a parcel.

Operator-driven changes that are not compartment openings — fee adjustments, blacklist transitions, settlement locks — are recorded as `AuditLog` entries with `action` drawn from `COMPARTMENT_OPEN`, `FEE_ADJUSTMENT`, `BLACKLIST_CHANGE`, and `SETTLEMENT_LOCK`, plus a `subject_entity` naming the entity type, a `subject_id` pointing at the affected record, and an immutable `payload` of action-specific structured details. Both kinds of log are append-only — they have no `updated_at` and no `version`.

## 3. Business Logic & Workflows

### 3.1. Provisioning Machines and Compartments

A locker site begins life when an `OperationsAdmin` registers a new `LockerMachine` by supplying its `site_code`, `partner_id`, and initial `firmware_version`. Newly created machines start `online_status` = `ONLINE` with `degraded_mode` = false and have no compartments yet. Compartments are added one at a time, each carrying a `slot_label` (which must be unique within the machine, e.g. "A-12") and a `size` of `SMALL`, `MEDIUM`, or `LARGE`. A fresh compartment enters with `status` = `AVAILABLE` and no `current_parcel_id`.

The machine's online state is tracked through periodic heartbeat pings carrying the current firmware. A heartbeat refreshes `last_heartbeat_at` and recomputes `degraded_mode`; when a previously offline machine pings with a firmware that meets the minimum supported baseline (`MIN_FIRMWARE_VERSION`, compared lexicographically by semver parts), the machine transitions back to `ONLINE`. If the firmware is still below the baseline, the machine may be `ONLINE` but `degraded_mode` remains true — degraded mode is the gating signal, not online status alone. Operations may also force `OFFLINE` directly; alternatively, the system itself flips the machine to `OFFLINE` when the heartbeat is silent for longer than the configured `HEARTBEAT_TIMEOUT_SECONDS`. Any transition to `OFFLINE` sets `degraded_mode` to true, advances `version`, refreshes `updated_at`, and immediately blocks new deposits at this machine with `ERR_MACHINE_OFFLINE_DEGRADED`. Parcels already in `PICKUP_PENDING` do not freeze: their overtime clock keeps running through the offline window, so a recipient who returns after restoration may pay more than they would have before the outage.

A compartment may also be removed from service explicitly. Toggling a compartment to `OUT_OF_SERVICE` from `AVAILABLE`, `RESERVED`, or `OCCUPIED` is permitted with one safety rule: if the compartment is currently `OCCUPIED`, the operator must first arrange a recall or disposal of the inhabiting parcel; attempting to take an occupied compartment out of service without that step is rejected with `ERR_OCCUPIED_COMPARTMENT_NEEDS_CLEAR`. Either toggle (out-of-service or back-to-service) appends a `CompartmentEvent` with `event_type` = `OUT_OF_SERVICE_TOGGLE`. Returning a compartment from `OUT_OF_SERVICE` to `AVAILABLE` carries no preconditions. The terminal `DECOMMISSIONED` state exists for permanent retirement and removes the compartment from occupancy denominators.

### 3.2. Capacity Awareness

`LockerMachine.capacity_warning_level` is a derived field — it is recomputed whenever a compartment changes status, whenever a parcel transitions, and whenever a machine is read. The computation works per size, then aggregates. For each size in `SMALL`, `MEDIUM`, `LARGE`: count `size_total` as the number of compartments at this machine with that size whose `status` is anything other than `DECOMMISSIONED`, and `size_occupied` as the number of compartments at this machine with that size whose `status` is exactly `OCCUPIED`. The per-size ratio is `size_occupied` divided by `size_total`, with the convention that a missing denominator (no compartments of that size) is treated as one. The per-size level is determined by exact rational comparison without rounding: when the ratio is at least 0.95, the level is `FULL_BLOCK_DEPOSITS`; otherwise, when the ratio is at least the near-full threshold described below, the level is `NEAR_FULL`; otherwise, the level is `NORMAL`. The boundary semantics are strict: a ratio of exactly 0.95 is `FULL_BLOCK_DEPOSITS`, and a ratio of 0.94999 is still only `NEAR_FULL`.

The near-full threshold itself depends on the wall-clock hour. During the configured peak hours — the half-open windows from 10:00 (inclusive) to 12:00 (exclusive) UTC, and from 18:00 (inclusive) to 21:00 (exclusive) UTC — the near-full ratio drops to 0.70. Outside those windows, it sits at 0.80. The same ratio at 11:30 UTC may therefore be `NEAR_FULL` while at 13:00 it is `NORMAL`.

The machine-wide `capacity_warning_level` is the most severe per-size level across the three sizes (with `FULL_BLOCK_DEPOSITS` strictly more severe than `NEAR_FULL`, which is strictly more severe than `NORMAL`). The exact running tallies of each size's occupancy are exposed on the machine record as `occupied_count_small`, `occupied_count_medium`, and `occupied_count_large`, alongside the aggregate `total_compartments` and `last_open_at` (the most recent successful compartment-opening timestamp on any compartment under this machine).

### 3.3. Deposit Workflow

A deposit begins when a `Courier` initiates the workflow with a payload containing `tracking_no`, `locker_machine_id`, `recipient_phone`, and `required_size`. Several gates fire in priority order before the parcel is even created. The target machine must not be in degraded mode (`ERR_MACHINE_OFFLINE_DEGRADED`). The acting courier's reputational standing must clear: a courier whose `blacklist_status` is `BLACKLISTED` is rejected outright with `ERR_COURIER_BLACKLISTED`, and a courier whose `blacklist_status` is `RESTRICTED` is also rejected with `ERR_COURIER_BLACKLISTED` whenever the requested deposit is at a non-`NORMAL` machine **or** the `required_size` is `SMALL`. A `RESTRICTED` courier may therefore deposit only at machines whose `capacity_warning_level` equals `NORMAL` and only for `required_size` of `MEDIUM` or `LARGE`; the dedicated identifier `ERR_COURIER_RESTRICTED` is reserved for the case where the courier is `RESTRICTED` and the machine is non-`NORMAL`. The machine must offer at least one compartment whose `size` is at least the requested `required_size`, otherwise the request is rejected with `ERR_NO_COMPARTMENT_FITS`. Finally, the per-size `capacity_warning_level` for the requested `required_size` must not be `FULL_BLOCK_DEPOSITS`; if it is, the request is rejected with `ERR_CAPACITY_BLOCKED`.

If all gates pass, the server selects a compartment using a deterministic selection rule: among compartments whose `status` is `AVAILABLE` and whose `size` is greater than or equal to `required_size`, take the one with the lowest current occupancy ratio for its size class, breaking ties on `slot_label` ascending. The selected compartment transitions from `AVAILABLE` to `RESERVED` and its `current_parcel_id` is set to the new parcel's `id`. A new `Parcel` record is created with `status` = `DRAFT`, `compartment_id` set, `failed_open_attempts` = 0, `correction_origin` = `NONE`, `replaces_parcel_id` = null, `fee_waived` = false, `fee_waiver_reason` = `NONE`, and the supplied input fields stored verbatim. The `tracking_no` is unique among parcels whose `status` is not `WRONG_DEPOSIT_VOID` — a duplicate live `tracking_no` is treated as an idempotency violation under `ERR_DUPLICATE_PAYMENT_EVENT`. Two couriers reaching the same compartment in parallel resolve first-writer-wins; the loser sees the compartment as no longer `AVAILABLE` and receives `ERR_COMPARTMENT_ALREADY_RESERVED`.

After physically placing the parcel, the courier confirms the deposit. Confirming requires the parcel still in `DRAFT` with `compartment_id` set (the compartment is still `RESERVED`) and the acting courier not `BLACKLISTED`. Confirming advances the parcel from `DRAFT` to `DEPOSITED`, advances the compartment from `RESERVED` to `OCCUPIED`, generates a six-digit numeric `pickup_code`, sets `deposited_at` to the current server time, appends a `CompartmentEvent` with `event_type` = `DEPOSIT_OPEN_OK`, appends an `AuditLog` with `action` = `COMPARTMENT_OPEN`, and emits an event to the IM system carrying the `recipient_phone` and `pickup_code` so that the recipient receives a notification. Both the parcel's and compartment's `version` increment by one and their `updated_at` refresh to the same instant.

Real cabinets do not always open on the first command. A retry endpoint increments `failed_open_attempts` to record an unsuccessful physical open. When `failed_open_attempts` reaches the cap of three (`MAX_RETRY` = 3), any further confirm-deposit attempt is rejected with `ERR_RETRY_EXHAUSTED`; the courier must instead cancel the deposit. Cancelling after retry exhaustion releases the compartment back to `AVAILABLE` (with `current_parcel_id` cleared), appends a `CompartmentEvent` with `event_type` = `DEPOSIT_OPEN_FAILED`, and frees the courier to begin a successor deposit whose `correction_origin` is `RETRY_REASSIGN`.

### 3.4. Pickup Workflow

The `Recipient` initiates pickup by submitting an authentication `method` of `CODE`, `SMS_LINK`, or `FACE`. When the method is `CODE`, the recipient also submits the supplied `code`; when it is `SMS_LINK`, the system verifies that the deep-link sent at deposit time has not expired; when it is `FACE`, a face-match service decides. Each attempt — successful or not — appends a `PickupCodeAttempt` record carrying the `method`, a `success` flag, and a `failure_reason` drawn from `NONE`, `WRONG_CODE`, `EXPIRED_LINK`, `FACE_MISMATCH`, `FEE_UNPAID`, or `OFFLINE_MACHINE`. A failed attempt leaves the parcel in `DEPOSITED`. The first successful attempt advances the parcel from `DEPOSITED` to `PICKUP_PENDING`, freezes the provisional overtime fee onto the parcel as `provisional_overtime_fee`, and materialises an `OvertimeFeeRecord` with `variant` = `PROVISIONAL`, `cutoff_at` set to the moment of `PICKUP_PENDING` entry, and `payment_status` = `UNPAID`. The compartment must be `OCCUPIED` for the transition to occur; a code entered against a parcel whose code is wrong is rejected with `ERR_INVALID_PICKUP_CODE`.

`PICKUP_PENDING` is a hold state: if the recipient does not advance to compartment-open within 600 seconds, the system reverts the parcel back to `DEPOSITED`; the same revert occurs on an explicit cancel. The provisional fee record remains for audit but its `payment_status` stays `UNPAID`. A future re-initiation begins the cycle again, with a new `cutoff_at` reflecting the new `PICKUP_PENDING` entry.

When the recipient is ready to actually open the compartment, the pickup-confirm step finalises the transaction. If the parcel's `provisional_overtime_fee` is greater than zero and `fee_waived` is false, the latest `OvertimeFeeRecord` of `variant` = `PROVISIONAL` must already be in `payment_status` = `PAID`; otherwise the confirm is rejected with `ERR_FEE_PAYMENT_REQUIRED` (HTTP 402). When the parcel was waived (for example because the deposit was a wrong-deposit by the courier or the machine had been in `SYSTEM_FAULT`), the fee gate is bypassed. If the gate passes, the parcel advances from `PICKUP_PENDING` to `PICKED_UP`, `picked_up_at` is set to the current instant, the compartment is released from `OCCUPIED` to `AVAILABLE` and its `current_parcel_id` cleared, a `CompartmentEvent` with `event_type` = `PICKUP_OPEN_OK` and an `AuditLog` with `action` = `COMPARTMENT_OPEN` are appended, and the IM system receives a `parcel_picked_up` notification. At this same step the system computes the **final** overtime amount with `cutoff_at` set to `picked_up_at` and writes a fresh `OvertimeFeeRecord` with `variant` = `FINAL`. If a tier boundary was crossed between the provisional freeze and the actual pickup, the final amount is strictly greater than the provisional amount; the delta is its own `UNPAID` record that flows through the same payment cascade. The final-variant record's `final_overtime_fee` value is exposed on the parcel.

A recipient who began a pickup but does not wish to continue may cancel the in-flight `PICKUP_PENDING`, which reverts the parcel to `DEPOSITED` and leaves the provisional fee record `UNPAID` for audit.

### 3.5. The Overtime Fee

Overtime is tracked in integer cents on the `OvertimeFeeRecord` rows attached to a parcel — one with `variant` = `PROVISIONAL` (frozen when the recipient first authenticates) and, after pickup, one with `variant` = `FINAL`. Both share the same calculation; only the `cutoff_at` differs. Each record carries a `payment_status` of `UNPAID`, `PAID`, `REFUNDED`, or `WAIVED` and, once paid, a `payment_external_id` returned by the external payment system.

The calculation works as follows. If the parcel's `fee_waived` is true, the amount is zero — no further computation. Otherwise, take the elapsed time between `deposited_at` and `cutoff_at`, convert to seconds, divide by 3600, and floor to a whole number — call this `elapsed_hours`. The first 24 elapsed hours are free; that is the `FREE_HOURS` constant. Hours from the 25th up to the 72nd accrue at the tier-one rate of 100 cents per hour; specifically, the tier-one count is the number of hours that fall in the half-open range above `FREE_HOURS` and at or below `TIER1_END_HOURS` (which is 72), with the count clamped to be non-negative and not exceeding the tier's width. Hours from the 73rd up to the 168th accrue at the tier-two rate of 200 cents per hour; the tier-two count is the number of hours that fall in the half-open range above `TIER1_END_HOURS` and at or below `TIER2_END_HOURS` (which is 168), again clamped non-negative. Hours beyond the 168th accrue at the tier-three rate of 400 cents per hour; the tier-three count is whatever remains above `TIER2_END_HOURS`, clamped non-negative. The raw amount in cents is the sum of the three tiers, each as the integer product of its hour-count and its per-hour rate — there is no per-hour rounding. The final `amount_cents` is the smaller of this raw sum and the hard cap `FEE_CAP_CENTS` of 10000 cents (one hundred dollars).

Provisional and final amounts may differ when a tier boundary is crossed in the interval between `PICKUP_PENDING` entry and actual pickup; in that case the final amount is strictly larger and its difference is collected as a top-up record with its own payment lifecycle. Both records remain on the parcel for traceability.

### 3.6. Wrong-Deposit Correction

If a courier realises a parcel was placed in error — wrong tracking number, wrong recipient, wrong size match — they may flag the deposit as a wrong deposit within a short grace window of 900 seconds (`WRONG_DEPOSIT_GRACE_SECONDS`) measured from `deposited_at`. The correction request supplies replacement input as `new_tracking_no`, `new_recipient_phone`, and `new_required_size`. Two preconditions are checked: the elapsed time since deposit must be strictly less than the grace window, otherwise the request is rejected with `ERR_WRONG_DEPOSIT_GRACE_EXPIRED`; and the acting `X-User-ID` must equal the `Parcel.courier_id` of the original parcel, otherwise the request is rejected with `ERR_NOT_COURIER_OWNER`. Additionally, if the parcel has already advanced beyond `DEPOSITED` (for example, a recipient has begun pickup while the courier was preparing the correction), the request is rejected with `ERR_PARCEL_STATE_CHANGED`.

A successful correction sets the original parcel's `status` to `WRONG_DEPOSIT_VOID`, sets its `fee_waived` to true with `fee_waiver_reason` = `COURIER_WRONG_DEPOSIT`, and marks any provisional fee record on it as `WAIVED`. A successor `Parcel` is created on the same compartment with `correction_origin` = `WRONG_DEPOSIT` and `replaces_parcel_id` pointing back at the old parcel; the compartment stays `OCCUPIED` but its `current_parcel_id` is rebound to the successor. The successor inherits the new tracking number, recipient phone, and size requirement supplied in the request; a fresh `pickup_code` is minted on its own confirm-deposit. The first parcel's `tracking_no` is now exempt from the live-uniqueness rule (because `WRONG_DEPOSIT_VOID` is excluded from that check), so the old number may legitimately be reused elsewhere if needed.

The wrong-deposit also touches the courier's reputation. `Courier.lifetime_wrong_deposit_count` increments and `Courier.window_wrong_deposit_rate` is recomputed over the rolling 30-day window ending at the current instant. If, after the recompute, the rolling rate is at least the blacklist threshold (`BLACKLIST_THRESHOLD_RATE` = 0.10, i.e. ten percent), the courier's `blacklist_status` auto-flips from `ACTIVE` to `RESTRICTED`, with `blacklist_reason` set to a system-supplied note and a `BLACKLIST_CHANGE` `AuditLog` appended. The flip from `ACTIVE` to `RESTRICTED` is the third hop in a four-hop cascade: the correction (hop 1) flips the original parcel's status (hop 2), bumps the rolling rate (hop 2 also computes the courier reputation), flips `blacklist_status` (hop 3), and changes the gating outcome of the next deposit by this courier (hop 4) — the next attempted deposit is now subject to the `RESTRICTED` rules and may be rejected with `ERR_COURIER_RESTRICTED` at non-`NORMAL` machines or with `ERR_COURIER_BLACKLISTED` for `SMALL` packages.

### 3.7. Long-Stay Sweep, Recall, Return, and Disposal

Parcels left for an extended period transition through a long-stay path designed to free compartments. The sweep is invoked through an admin-only test-driving capability that processes all `Parcel` rows whose `status` is `DEPOSITED`, ordered by `deposited_at` ascending and then by `id` ascending as a stable tie-break. For each such parcel, the sweep checks whether the elapsed time since `deposited_at` is at least the long-stay threshold (`LONG_STAY_THRESHOLD_HOURS` of 168 hours); equality at the threshold triggers the transition. When the threshold is met, the parcel advances from `DEPOSITED` to `LONG_STAY`, the moment of transition is recorded for downstream window arithmetic, an IM notification is dispatched to the recipient, and a courier-company event is emitted. As soon as the sweep encounters a parcel whose elapsed time is below the threshold, it stops processing — chronological order guarantees that all subsequent rows are even younger. The `_sweep/run` capability does not auto-fire on a clock advance; the operator must trigger it explicitly.

Operations and couriers each have a path forward from `LONG_STAY`. The original courier may recall the parcel within the recall window (`RECALL_WINDOW_HOURS` = 72) measured from the moment of transition into `LONG_STAY`. Recalling is restricted to the parcel's owning courier (`ERR_NOT_COURIER_OWNER` otherwise) and requires the parcel still in `LONG_STAY`. A successful recall advances the parcel to `RECALLED`, releases the compartment to `AVAILABLE`, and appends `CompartmentEvent` with `event_type` = `RECALL_OPEN_OK` plus an `AuditLog` row.

If the recall window has elapsed (the time since `LONG_STAY` entry is at least `RECALL_WINDOW_HOURS`), Operations may instead arrange a return to sender; this advances the parcel to `RETURNED`, releases the compartment, and emits a `parcel_return_requested` event to the courier-company system. After a longer threshold of 336 hours (`DISPOSE_THRESHOLD_HOURS`) measured from the `LONG_STAY` entry, Operations may also record an on-site disposal, which moves the parcel to `DISPOSED`, releases the compartment, and appends an `AuditLog` row whose `payload` records the supplied `reason`. Disposal carries a precondition that the elapsed time since `LONG_STAY` entry is at least `DISPOSE_THRESHOLD_HOURS`.

### 3.8. Fee Payment, Refund, and Manual Waivers

The payment cascade runs through the events ingress. A `payment_succeeded` event referencing an `OvertimeFeeRecord.id` advances that record from `UNPAID` to `PAID` provided the record still exists, is `UNPAID`, and has `amount_cents` > 0 (a zero-amount fee record cannot be marked paid; the attempt is rejected with `ERR_FEE_ZERO_NOT_PAYABLE`). The captured `payment_external_id` is the idempotency key: a replay of the same event (same external id) returns 200 with no double credit; a *different* external id targeting the same record is rejected with `ERR_DUPLICATE_PAYMENT_EVENT`. Reaching `PAID` is the cascade hop that unblocks the `PICKUP_PENDING → PICKED_UP` transition for non-waived parcels.

Refunds reverse the path. A `payment_refunded` event matching an existing `payment_external_id`, or a dispute resolution that calls for refund (see below), advances the record from `PAID` to `REFUNDED`. If the parcel itself is in `PICKED_UP`, the refund will be picked up by the next settlement run as part of `refund_reversal_cents`; either way the refund appends an `AuditLog` row whose `action` is `FEE_ADJUSTMENT`.

Operations may manually waive a fee in a few business situations. The waiver is permitted from `UNPAID` to `WAIVED` and requires a `reason` drawn from `SYSTEM_FAULT` (deposit happened while the machine was in degraded mode), `COURIER_WRONG_DEPOSIT` (set automatically on wrong-deposit corrections), or `MANUAL_DISPUTE` (operator-driven exception). The waiver sets `Parcel.fee_waived` to true and records the chosen reason in `Parcel.fee_waiver_reason`. A `FEE_ADJUSTMENT` `AuditLog` is appended.

### 3.9. Disputes

A dispute may be opened by either the `Recipient` or the original `Courier`. The opener supplies a `claim_type` of `WRONG_DEPOSIT`, `OVERTIME_DISPUTE`, or `DAMAGED`; the system records the opener under `opened_by_role` (one of `Recipient` or `Courier`) and starts the dispute in `status` = `OPEN`. Operations alone resolves the dispute by submitting a `resolution`. Three resolutions exist: `WAIVE` advances the dispute to `RESOLVED_WAIVED`, refunds the latest `OvertimeFeeRecord` if it was `PAID` (or marks it `WAIVED` if it was still `UNPAID`), sets `Parcel.fee_waived` to true with `fee_waiver_reason` = `MANUAL_DISPUTE`, and records the refunded or waived amount on `outcome_amount_cents`. The waiver path is only available when the parcel is not in `DISPOSED` or `RETURNED`. `REJECT` advances the dispute to `RESOLVED_REJECTED` and produces no fee or courier side effects (`outcome_amount_cents` is 0). `COURIER_AT_FAULT` advances the dispute to `RESOLVED_COURIER_AT_FAULT`, increments the original courier's `complaint_count`, waives the fee in the same fashion as `WAIVE`, and may further cascade the courier's `blacklist_status` (see below). A dispute that has already left `OPEN` cannot be resolved again — a second resolve call is rejected with `ERR_DISPUTE_ALREADY_RESOLVED`.

### 3.10. Courier Reputation, Blacklisting, and Reinstatement

A `Courier` record is brought into the system by an `OperationsAdmin` registration call carrying the courier's contact `phone` (E.164 format) and the courier-company external identifier `company_id` used for cross-system synchronisation; new couriers start in `blacklist_status` = `ACTIVE` with `blacklist_reason` of null.

A courier's standing is summarised in `blacklist_status`, with three legal values: `ACTIVE`, `RESTRICTED`, `BLACKLISTED`. The auto-flip from `ACTIVE` to `RESTRICTED` is driven by the wrong-deposit cascade described above (window wrong-deposit rate at or above 0.10). Operations may also manually move a courier into `RESTRICTED` with a supplied `reason` (recorded in `blacklist_reason`).

Escalation from `RESTRICTED` to `BLACKLISTED` happens automatically when `complaint_count` reaches at least the blacklist complaint threshold (`BLACKLIST_COMPLAINT_THRESHOLD` = 5) within the rolling 30-day window, and Operations may also force the transition with a manual blacklist call carrying a `reason`. Once `BLACKLISTED`, the courier's deposit attempts are rejected outright with `ERR_COURIER_BLACKLISTED`, regardless of machine or size; this is the reputational sledgehammer.

Reinstatement returns a `RESTRICTED` or `BLACKLISTED` courier to `ACTIVE`, but only if both reputational signals have already cooled: the rolling `window_wrong_deposit_rate` must be strictly below 0.10 and the rolling `complaint_count` must be strictly below 5. A successful reinstatement clears `blacklist_reason` to null and appends a `BLACKLIST_CHANGE` `AuditLog`. Any blacklist or reinstatement also appends a `BLACKLIST_CHANGE` `AuditLog` row — these transitions are always auditable.

The courier's quality score is exposed in two variants on a single rating endpoint. The **lifetime** variant is built for analytic dashboards. It computes `lifetime_success_rate` as the count of successful deposits (the lifetime deposit count minus the count of failed open attempts) divided by the sum of the lifetime deposit count plus the failed-attempt count, with the denominator clamped to a minimum of one to avoid division by zero, then combines it into a weighted score with the formula: weight `W_SUCCESS` of 0.5 multiplied by `lifetime_success_rate`, plus weight `W_LOW_WRONG` of 0.3 multiplied by one minus the rolling 30-day `window_wrong_deposit_rate`, plus weight `W_LOW_COMPLAINT` of 0.2 multiplied by one minus the smaller of the ratio of `complaint_count` to the complaint normaliser `COMPLAINT_NORM` of 5 and the value one. The result is rounded half-up to four decimal places; ties between couriers are broken by `lifetime_success_rate` descending, then by `Courier.created_at` ascending.

The **window_30d** variant is used for blacklist gating and rolls forward with the clock. Its denominator and numerator both come from parcels whose `deposited_at` falls within the last 30 days ending at the current instant, with parcels in `DRAFT` status excluded from the count; the numerator counts the deposits whose successor parcel has `correction_origin` = `WRONG_DEPOSIT`. The result is reported to four decimal places. Because the window slides with wall-clock time, a courier whose lifetime rate is fine may still trip the `RESTRICTED` gate during a single bad week, and conversely a previously-`RESTRICTED` courier's gate clears purely by clock advance once the bad incidents fall out of the window.

### 3.11. Settlement and Revenue Sharing

`SettlementBatch` aggregates partner revenue over a half-open period defined by `period_start` (inclusive, UTC) and `period_end` (exclusive, UTC). Operations creates a batch for a given `partner_id` over an interval; the batch enters `status` = `DRAFT`, and reads of the batch recompute aggregations on the fly. Locking the batch (advancing `status` from `DRAFT` to `LOCKED`) requires two conditions: the period must already be closed, meaning `period_end` is at or before the current instant (`ERR_PERIOD_NOT_CLOSED` otherwise); and there must be no `OvertimeFeeRecord` within the window whose `payment_status` is `UNPAID` and whose parcel is in a state that requires payment (`ERR_PENDING_FEES_IN_WINDOW` otherwise). Locking freezes the totals, appends a `SETTLEMENT_LOCK` `AuditLog`, and from this moment forward refunds within the window are allowed to complete but cannot mutate the locked totals — they roll into the next batch's `refund_reversal_cents` instead.

Settling a `LOCKED` batch advances it to `SETTLED` and emits a payment-system payout event carrying the `partner_id` and the computed `partner_share_cents`.

The revenue calculation itself runs on every read and is finalised at lock time. Begin by summing the `amount_cents` over all `OvertimeFeeRecord` rows with `variant` = `FINAL`, with `payment_status` = `PAID` *as of the compute instant*, whose parcel's `locker_machine_id` belongs to a machine whose `partner_id` matches the batch's `partner_id`, and whose `created_at` is at or after `period_start` and strictly before `period_end`. This sum is the `gross_overtime_revenue_cents`. Separately, sum the `amount_cents` of all such (`variant` = `FINAL`) records that are now `REFUNDED` *and* whose `updated_at` is at or after `period_start` and strictly before `period_end`; this is the `refund_reversal_cents`. The `net_revenue_cents` is the gross minus the refund-reversal. The rounding order is **fixed** and material: the partner's share is computed first as `partner_share_cents` equal to the floor of the net multiplied by the partner share ratio (`PARTNER_SHARE_RATIO` = 0.30); the platform's share is then derived as the residual `platform_share_cents` equal to `net_revenue_cents` minus `partner_share_cents`. This guarantees that the two shares sum exactly to the net with no drift on odd-cents amounts. Reversing the order — rounding the platform's share first and deriving the partner's share by subtraction — would shift the boundary cent in the partner's favour and would not match the contract.

### 3.12. Test-Driving and External Synchronisation

Two admin-only capabilities exist for test-harness use. A logical-clock advance accepts a `seconds` value and moves the server clock forward by that many seconds, returning the new now. Advancing the clock does not auto-trigger the long-stay sweep — operators (or the test harness) must explicitly invoke the sweep run when they want to see eligible parcels transition to `LONG_STAY`.

External-event ingress accepts an `event_type` and a `payload` and dispatches the cascade described above. The currently recognised `event_type` values are `payment_succeeded`, `payment_refunded`, `im_delivered`, and `courier_company_ack`. Payment events flow through the fee-record lifecycle and respect idempotency on `payment_external_id` as already described. IM and courier-company acknowledgements are recorded for traceability but do not by themselves change parcel state.

## 4. Endpoint Definitions

The API uses the following conventions for HTTP status codes: endpoints that create a brand-new top-level resource return 201; all other successful responses (including state-transition endpoints, list reads, single-resource reads, and lock/settle operations) return 200. Error responses carry the status indicated by the error catalogue in §5. The summary below names the path, the verb, the high-level intent, and the roles authorised to call it; request-payload fields, response shapes, and side effects must be reconstructed from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/locker-machines` | Create a `LockerMachine` | `OperationsAdmin` |
| GET | `/locker-machines` | List `LockerMachine` records | `Any` |
| GET | `/locker-machines/{machineId}` | Get a `LockerMachine` including `capacity_warning_level` | `Any` |
| POST | `/locker-machines/{machineId}/heartbeat` | Heartbeat ping with current `firmware_version` | `OperationsAdmin`, `system` |
| POST | `/locker-machines/{machineId}/offline` | Force machine to `OFFLINE` | `OperationsAdmin` |
| GET | `/locker-machines/{machineId}/audit-logs` | List `AuditLog` entries scoped to this machine | `OperationsAdmin` |
| POST | `/locker-machines/{machineId}/compartments` | Create a `Compartment` | `OperationsAdmin` |
| GET | `/locker-machines/{machineId}/compartments` | List compartments under a machine | `Any` |
| GET | `/locker-machines/{machineId}/compartments/{compartmentId}` | Get a single compartment | `Any` |
| POST | `/locker-machines/{machineId}/compartments/{compartmentId}/out-of-service` | Mark compartment `OUT_OF_SERVICE` | `OperationsAdmin` |
| POST | `/locker-machines/{machineId}/compartments/{compartmentId}/in-service` | Restore compartment to `AVAILABLE` | `OperationsAdmin` |
| POST | `/couriers` | Register a `Courier` | `OperationsAdmin` |
| GET | `/couriers/{courierId}` | Get a `Courier` including rating fields | `OperationsAdmin`, `Courier` |
| GET | `/couriers/{courierId}/rating` | Get courier quality score with both `lifetime` and `window_30d` variants | `OperationsAdmin`, `Courier` |
| POST | `/couriers/{courierId}/restrict` | Set `blacklist_status` to `RESTRICTED` | `OperationsAdmin` |
| POST | `/couriers/{courierId}/blacklist` | Set `blacklist_status` to `BLACKLISTED` | `OperationsAdmin` |
| POST | `/couriers/{courierId}/reinstate` | Restore courier to `ACTIVE` | `OperationsAdmin` |
| POST | `/parcels` | Begin deposit; server selects compartment by lowest occupancy then `slot_label` ascending | `Courier` |
| POST | `/parcels/{parcelId}/confirm-deposit` | Courier confirms physical placement; mints `pickup_code` | `Courier` |
| POST | `/parcels/{parcelId}/cancel-deposit` | Cancel deposit after retry exhaustion | `Courier` |
| POST | `/parcels/{parcelId}/retry-open` | Increment `failed_open_attempts` (deposit-failure retry) | `Courier` |
| POST | `/parcels/{parcelId}/correct-wrong-deposit` | Flag wrong deposit within grace window; create successor parcel | `Courier` |
| POST | `/parcels/{parcelId}/initiate-pickup` | Recipient initiates pickup with `method` of `CODE`, `SMS_LINK`, or `FACE` | `Recipient` |
| POST | `/parcels/{parcelId}/pickup-confirm` | Recipient opens compartment after fee paid | `Recipient` |
| POST | `/parcels/{parcelId}/cancel-pickup` | Cancel mid-flow pickup; returns parcel to `DEPOSITED` | `Recipient` |
| POST | `/parcels/{parcelId}/recall` | Courier recalls a `LONG_STAY` parcel within `RECALL_WINDOW_HOURS` | `Courier` |
| POST | `/parcels/{parcelId}/return-to-sender` | Operations returns parcel after recall window expiry | `OperationsAdmin` |
| POST | `/parcels/{parcelId}/dispose` | Operations records on-site disposal after dispose threshold | `OperationsAdmin` |
| POST | `/parcels/{parcelId}/waive-fee` | Operations manually waives overtime fee | `OperationsAdmin` |
| GET | `/parcels` | List parcels with filters | `Any` |
| GET | `/parcels/{parcelId}` | Get a parcel including provisional and final fees | `Any` |
| GET | `/parcels/{parcelId}/fees` | List `OvertimeFeeRecord` rows for parcel | `Any` |
| POST | `/parcels/{parcelId}/disputes` | Open a `Dispute` | `Recipient`, `Courier` |
| POST | `/disputes/{disputeId}/resolve` | Resolve a dispute | `OperationsAdmin` |
| POST | `/settlements` | Create a `SettlementBatch` in `DRAFT` | `OperationsAdmin` |
| GET | `/settlements` | List settlement batches | `OperationsAdmin` |
| GET | `/settlements/{batchId}` | Get a settlement batch (recomputes aggregations) | `OperationsAdmin` |
| POST | `/settlements/{batchId}/lock` | Lock the batch (freeze totals) | `OperationsAdmin` |
| POST | `/settlements/{batchId}/settle` | Settle a locked batch | `OperationsAdmin` |
| POST | `/_clock/advance` | Advance the test-harness server clock by a number of `seconds` | `OperationsAdmin` |
| POST | `/_sweep/run` | Run the long-stay sweep | `OperationsAdmin` |
| POST | `/events/emit` | External-event ingress with `event_type` and `payload` | `OperationsAdmin`, `system` |

## 5. Error Code Catalogue

The trigger conditions for each error are stated in the workflow and rule narratives in §2 and §3; the table below summarises only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_MACHINE_OFFLINE_DEGRADED` | 409 |
| `ERR_COMPARTMENT_ALREADY_RESERVED` | 409 |
| `ERR_OCCUPIED_COMPARTMENT_NEEDS_CLEAR` | 409 |
| `ERR_NO_COMPARTMENT_FITS` | 409 |
| `ERR_CAPACITY_BLOCKED` | 409 |
| `ERR_PARCEL_STATE_CHANGED` | 409 |
| `ERR_RETRY_EXHAUSTED` | 409 |
| `ERR_WRONG_DEPOSIT_GRACE_EXPIRED` | 409 |
| `ERR_NOT_COURIER_OWNER` | 403 |
| `ERR_INVALID_PICKUP_CODE` | 409 |
| `ERR_FEE_PAYMENT_REQUIRED` | 402 |
| `ERR_FEE_ZERO_NOT_PAYABLE` | 409 |
| `ERR_COURIER_BLACKLISTED` | 403 |
| `ERR_COURIER_RESTRICTED` | 403 |
| `ERR_DISPUTE_ALREADY_RESOLVED` | 409 |
| `ERR_PERIOD_NOT_CLOSED` | 409 |
| `ERR_PENDING_FEES_IN_WINDOW` | 409 |
| `ERR_SETTLEMENT_LOCKED` | 409 |
| `ERR_DUPLICATE_PAYMENT_EVENT` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
