# Shared Storage Locker API — Product Requirements Document

## 1. Introduction

Unattended shared storage lockers are the operational backbone of last-mile parcel handoff, traveller bag-drop, and short-term personal storage in dense urban locations. A single physical **cabinet** hosts multiple compartments across small, medium, and large size classes; each compartment can be rented by hour, day, or month; and the whole estate is operated by a thin platform team that must reconcile revenue with location partners, dispatch repair technicians the moment hardware misbehaves, and coordinate with an external insurance company when a renter reports damage, loss, or theft.

This document specifies the Shared Storage Locker API — a back-end that owns the source-of-truth state for every cabinet, every compartment, every rental, and every downstream record the operations team uses to settle the books. The API must be precise about three classes of correctness that have historically been the cause of disputes in this domain: monetary settlement (rental fees, overdue accrual, deposit forfeiture, refund reversal, and partner revenue split), state cascades between a rental and its housing compartment (so that a force-clearance leaves the locker in a recoverable state rather than orphaning the renter's belongings), and offline-degraded operation (so that a cabinet whose network has just dropped does not refuse a paying customer outright, but does refuse channels it cannot authenticate).

A secondary goal of the system is auditability. Every compartment opening and every force-clearance must produce an immutable trail that operations, the insurance company, and — when challenged — the renter can inspect after the fact.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API MUST carry two headers: `X-User-ID` (the caller's identity) and `X-User-Role` (the caller's role). A request that omits either header, or supplies a malformed value, is rejected with `ERR_UNAUTHORIZED`. A request whose `X-User-Role` is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN`.

The system defines four roles, spelled exactly as follows: `Renter`, `Operator`, `RepairTechnician`, and `InsuranceAgent`.

- When `X-User-Role` is `Renter`, `X-User-ID` is an opaque renter identifier; it is not the `id` of any persisted entity. The server stores it on `Rental.renter_id` (and, by snapshot, on `InsuranceClaim.renter_id`). Ownership checks on rentals, renewals, returns, holding-claims, claim filings, and evidence submissions compare `X-User-ID` against `Rental.renter_id` (or the snapshotted `InsuranceClaim.renter_id`) directly.
- When `X-User-Role` is `Operator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it on `AuditEvent.actor_id` but does not compare it to any entity's `id`.
- When `X-User-Role` is `RepairTechnician`, `X-User-ID` is an opaque technician identifier; the server compares it to `RepairTicket.assigned_technician_id` when authorising the repair completion step.
- When `X-User-Role` is `InsuranceAgent`, `X-User-ID` is an opaque insurer identifier not tied to any persisted entity; the server may record it on `AuditEvent.actor_id` but does not compare it to any entity's `id`.

A `Renter` whose `X-User-ID` does not match the resource's owning renter on an ownership-checked endpoint is rejected with `ERR_FORBIDDEN`.

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

All list endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; `offset` defaults to 0 and has no upper bound beyond the available `total_count`. List results are sorted by `created_at` ascending unless an endpoint's description states otherwise. The `meta` block of every list response includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

The system mints every resource `id` as a server-generated UUID with no domain-specific prefix; clients MUST NOT supply ids on creation. `Cabinet`, `Compartment`, `Rental`, `InsuranceClaim`, and `RepairTicket` resources additionally carry `created_at` (set on creation), `updated_at` (refreshed on every mutation), and `version` (a non-negative integer that starts at zero on creation and increments by one on every mutation). All three timestamps are ISO 8601 UTC strings with three fractional digits.

`PricingProfile`, `RevenueRecord`, and `AuditEvent` are immutable once written and carry only `id` and `created_at`; they have no `updated_at` and no `version` field.

### 2.5. Optimistic Concurrency Control

Mutation endpoints that target an existing resource (every PATCH and every state-transition POST against `Rental`, `InsuranceClaim`, `RepairTicket`, and `Cabinet`) accept an optional `version` field in the request body. When `version` is present, the server compares it to the persisted resource's `version`: if they differ the write is rejected with `ERR_VERSION_CONFLICT`. When `version` is omitted, the OCC check is skipped and the write proceeds against whatever version is current.

### 2.6. Hierarchical State and Cascade Semantics

A `Cabinet` is the parent of its `Compartment` rows; a `Compartment` houses at most one active `Rental` at a time. State changes propagate through these relationships:

- When a `Compartment.occupancy_status` transitions among `IDLE`, `RENTED`, `OVERDUE`, and `HOLDING`, the parent cabinet's per-size-class occupancy percentages (`small_occupancy_pct`, `medium_occupancy_pct`, `large_occupancy_pct`) and its `capacity_alert_level` are recomputed in the same request.
- When a sweep transitions a `Rental` from `ACTIVE` or `EXPIRING_SOON` to `OVERDUE`, the housing compartment's `occupancy_status` cascades to `OVERDUE` in the same operation.
- When a sweep transitions a `Rental` from `OVERDUE` to `FORCE_CLEARED`, the housing compartment cascades to `HOLDING`, the compartment's `active_rental_id` is cleared, and the compartment's `holding_item_description` and `holding_claim_deadline` are populated.
- When a renter returns a rental, the compartment cascades to `IDLE` and `active_rental_id` is cleared.
- When an operator accepts a repair, the compartment's `operational_status` cascades from `FAULT` to `OK` and `fault_category` is cleared.

Every cascade refreshes `updated_at` and increments `version` on each mutated resource. The cascade executes atomically within the triggering request: a reader who observes the parent change is guaranteed to observe every child change in the same response.

### 2.7. Nested-Resource Path Validation

Paths that nest resources (for example `/cabinets/{cabinet_id}/compartments/{compartment_id}/rentals`) are validated left-to-right. The cabinet must exist before the compartment is looked up; the compartment must exist and belong to that cabinet before the rental endpoint runs. Each failure surfaces as `ERR_NOT_FOUND` with no leakage of which segment failed.

### 2.8. Monetary Precision

All monetary amounts in this system are integer cents (`unit_price_cents`, `deposit_cents`, `overdue_rate_cents_per_hour`, `unit_price_cents_snapshot`, `deposit_cents_snapshot`, `overdue_rate_snapshot`, `insurance_premium_cents`, `rental_fee_cents`, `total_charged_cents`, `overdue_fee_cents`, `deposit_forfeited_cents`, `deposit_refunded_cents`, `claimed_amount_cents`, `payout_cents`, `gross_cents`, `partner_share_cents`, `platform_share_cents`). Inputs and outputs never carry fractional cents. Where rounding is required during a calculation, the system uses round-half-up; where a calculation truncates upward (`ceil`) the rule is stated alongside the formula that uses it. Percentage fields exposed on `Cabinet` (`small_occupancy_pct`, `medium_occupancy_pct`, `large_occupancy_pct`) are stored to two decimal places using round-half-up; thresholds against them use `>=` comparisons against the two-decimal value.

### 2.9. Validation Priority

When multiple validations apply to the same request, the system evaluates them in a fixed order and returns the first failure. The order is: header presence (`ERR_UNAUTHORIZED`), role permission (`ERR_FORBIDDEN`), existence of every URL-path resource left-to-right (`ERR_NOT_FOUND`), `Renter` ownership equality with the owning `Rental.renter_id` or `InsuranceClaim.renter_id` (`ERR_FORBIDDEN`), `version` equality when supplied (`ERR_VERSION_CONFLICT`), source-state legality for the requested transition (`ERR_INVALID_STATE`), then domain-specific safety rules in the order: compartment fault gating (`ERR_COMPARTMENT_FAULT`), cabinet offline gating (`ERR_CABINET_OFFLINE`), compartment occupancy gating (`ERR_COMPARTMENT_UNAVAILABLE`), pricing-profile existence (`ERR_PRICING_PROFILE_NOT_FOUND`), insurance coherence (`ERR_INVALID_INSURANCE`), general bad-request rules (`ERR_BAD_REQUEST`), holding-window expiry (`ERR_CLAIM_WINDOW_EXPIRED`), uniqueness of open insurance claims per rental (`ERR_CLAIM_ALREADY_OPEN`), renewal-state legality (`ERR_RENEWAL_NOT_PERMITTED`), refund-blocked-by-claim (`ERR_REFUND_BLOCKED_BY_CLAIM`), and payout-cap (`ERR_PAYOUT_EXCEEDS_CAP`). This ordering is observable: when a request fails multiple checks the earliest failure wins, so for example a `Renter` who is missing the role header receives `ERR_UNAUTHORIZED` rather than `ERR_FORBIDDEN`, and a renter who supplies a stale `version` against an already-`OVERDUE` rental receives `ERR_VERSION_CONFLICT` before `ERR_RENEWAL_NOT_PERMITTED`.

### 2.10. Concurrency Serialization

The system serialises five known races so that exactly one writer wins and the loser receives a deterministic `error_id`:

- Two `Renter` requests starting a rental on the same `IDLE` compartment serialise on the compartment's `occupancy_status` transition from `IDLE` to `RENTED`; the loser receives `ERR_COMPARTMENT_UNAVAILABLE`.
- A `Renter` returning a rental while a sweep concurrently force-clears it serialise on the rental's `status` transition out of `OVERDUE`; the loser receives `ERR_INVALID_STATE`.
- A `Renter` renewing while a sweep crosses the grace boundary into `OVERDUE` race on the same `Rental.status`; if the sweep wins the renewal sees an already-`OVERDUE` rental and is rejected with `ERR_RENEWAL_NOT_PERMITTED`, and if the renewal wins the sweep observes `ACTIVE` and takes no action.
- Two concurrent writers with stale `version` against the same `Rental`, `Cabinet`, `InsuranceClaim`, or `RepairTicket` are serialised by the OCC check; the loser receives `ERR_VERSION_CONFLICT`.
- Two simultaneous `InsuranceClaim` creations against the same rental serialise on uniqueness of an open claim per rental; the loser receives `ERR_CLAIM_ALREADY_OPEN`.

### 2.11. Time, Sweeps, and Deferred Transitions

Several state transitions are gated on the passage of time rather than on a renter action: a rental moves to `EXPIRING_SOON` thirty minutes before its `current_expires_at`, crosses into `OVERDUE` after a per-profile grace window, and becomes `FORCE_CLEARED` after a per-profile forced-clearance horizon; a cabinet whose `last_heartbeat_at` is older than five minutes degrades, and one whose heartbeat is older than fifteen minutes goes offline. So that the test driver can reach these branches deterministically, the system exposes an admin-only logical clock that the driver advances to a supplied `to_timestamp`, and an admin-only sweep capability that, when invoked, fires every time-gated transition that the current logical clock now satisfies. Advancing the clock alone fires no transitions; only invoking the sweep does.

### 2.12. Revenue, Partner Share, and Auditability

Every cabinet has a location partner identified by `partner_id` who receives a `partner_share_pct` of the gross revenue produced by that cabinet. Each `RevenueRecord` row stores `gross_cents`, `partner_share_cents`, and `platform_share_cents`; the row-level split rounds the partner share half-up and assigns the residual to the platform so that the two always sum to `gross_cents`, including for negative-`gross_cents` refund reversal rows. Aggregations served by the revenue-summary endpoint follow a different rounding order, described in §3.6. Every compartment opening (whether by rental creation, return, or holding-claim) and every force-clearance produces an `AuditEvent` whose `event_kind` is `COMPARTMENT_OPENED` or `FORCE_CLEARANCE`, whose `subject_type` and `subject_id` identify either the involved `Compartment` or the involved `Rental`, whose `actor_role` and `actor_id` identify the originator, whose `unlock_channel` captures the channel for openings (and is null for force-clearance rows), and whose `detail` carries a free-form JSON payload (for example, the destination locker for items moved into holding, or the forfeited deposit amount). Every audit row stores `occurred_at` and `created_at`.

## 3. Business Logic & Workflows

### 3.1. Cabinet Onboarding, Heartbeats, and Degraded Operation

An `Operator` registers a new cabinet by supplying `location_code`, `latitude`, `longitude`, `partner_id`, `partner_share_pct`, and `firmware_version`. `partner_share_pct` is an integer from 0 to 100 inclusive; a value outside this range is rejected with `ERR_BAD_REQUEST`. On creation the cabinet's `online_status` is `ONLINE`, its `last_heartbeat_at` is null, its `capacity_alert_level` is `NONE`, and every counter (`total_compartments`, `small_capacity_total`, `medium_capacity_total`, `large_capacity_total`, `small_occupancy_pct`, `medium_occupancy_pct`, `large_occupancy_pct`) is zero. An `Operator` may later adjust `firmware_version`, `partner_id`, or `partner_share_pct` through the cabinet update operation, which increments `version` and refreshes `updated_at`.

A cabinet announces itself periodically by sending a heartbeat. Each heartbeat refreshes `last_heartbeat_at` to the server's current time and, if the cabinet was previously `DEGRADED` or `OFFLINE`, transitions `online_status` back to `ONLINE` and refreshes `updated_at`; the heartbeat additionally emits an outbound mapping-system sync event carrying the cabinet's status. When the sweep runs against a cabinet whose `last_heartbeat_at` is at least five minutes old and less than fifteen minutes old, `online_status` transitions from `ONLINE` to `DEGRADED`, the cabinet's `capacity_alert_level` is recomputed (degraded cabinets count toward redistribution suggestions), `updated_at` is refreshed, and the outbound mapping-system sync event is emitted. When the sweep observes that `last_heartbeat_at` is at least fifteen minutes old, the cabinet transitions to `OFFLINE` from either `ONLINE` or `DEGRADED`; while `OFFLINE`, any `IDLE` compartment in the cabinet remains rentable only via the `PASSWORD` unlock channel, and rental attempts that supply `QR` or `BLUETOOTH` are rejected with `ERR_CABINET_OFFLINE`.

### 3.2. Compartments, Pricing Profiles, and the Start of a Rental

An `Operator` adds compartments to a cabinet by supplying `slot_number` and `size_class`; `slot_number` must be unique within the parent cabinet, and a duplicate is rejected with `ERR_DUPLICATE_SLOT`. The `size_class` is one of `SMALL`, `MEDIUM`, or `LARGE`. Each new compartment starts with `operational_status` = `OK` and `occupancy_status` = `IDLE`; `fault_category`, `active_rental_id`, `holding_item_description`, and `holding_claim_deadline` are null, and the cabinet's capacity counters are recomputed in the same request.

Before any rental can be priced, an `Operator` must create a pricing profile for the (`size_class`, `rental_mode`) pair. A profile carries `unit_price_cents`, `deposit_cents`, `grace_minutes`, `overdue_rate_cents_per_hour`, and `forced_clearance_hours`; the unit price must be strictly positive, the deposit must be non-negative, the grace minutes must be non-negative, the overdue rate must be non-negative, and the forced-clearance horizon (in hours) must be strictly greater than `grace_minutes` divided by sixty. A second profile with the same (`size_class`, `rental_mode`) pair is rejected with `ERR_DUPLICATE_PROFILE`.

A `Renter` starts a rental by sending the rental-creation request to the chosen compartment, supplying `rental_mode` (one of `HOURLY`, `DAILY`, `MONTHLY`), `billing_units` (the number of hours, days, or months purchased upfront, which must be at least one), `unlock_channel` (one of `QR`, `BLUETOOTH`, or `PASSWORD`), and the insurance fields described in §3.4. The body also echoes the pricing-profile fields `unit_price_cents`, `deposit_cents`, `grace_minutes`, `overdue_rate_cents_per_hour`, and `forced_clearance_hours` for the convenience of clients that prefer to surface them at confirmation time, but the server resolves the active `PricingProfile` for (`compartment.size_class`, request `rental_mode`) and snapshots the canonical values onto the rental as `unit_price_cents_snapshot`, `deposit_cents_snapshot`, `grace_minutes_snapshot`, `overdue_rate_snapshot`, and `forced_clearance_hours_snapshot`. If no profile exists for the pair the request is rejected with `ERR_PRICING_PROFILE_NOT_FOUND`.

At the moment of rental creation the system enforces, in this order after generic checks: the compartment's `operational_status` must be `OK` (otherwise `ERR_COMPARTMENT_FAULT`), the cabinet's `online_status` must be `ONLINE` or `DEGRADED` unless `unlock_channel` is `PASSWORD` (otherwise `ERR_CABINET_OFFLINE`), the compartment's `occupancy_status` must be `IDLE` (otherwise `ERR_COMPARTMENT_UNAVAILABLE`), and the pricing profile must resolve. On success the rental record is minted with `status` = `ACTIVE`, `started_at` set to the request time, `original_expires_at` set to `started_at` plus `billing_units` multiplied by the unit-duration for the rental mode (one hour for `HOURLY`, one day for `DAILY`, a fixed thirty-day month for `MONTHLY`), and `current_expires_at` initially equal to `original_expires_at`; `original_expires_at` is never mutated thereafter while `current_expires_at` extends on every renewal. The rental's `renter_id` is taken from `X-User-ID`, `compartment_id` and `cabinet_id` are set from the URL path, `size_class` is copied from the compartment, `renewal_count` is zero, `ended_at` and `reminder_sent_at` are null, and `overdue_fee_cents`, `deposit_forfeited_cents`, and `deposit_refunded_cents` are zero. The compartment's `occupancy_status` transitions to `RENTED`, `active_rental_id` is set, the cabinet's capacity statistics and `capacity_alert_level` are recomputed, an `AuditEvent` of `event_kind` `COMPARTMENT_OPENED` is emitted carrying the `unlock_channel`, and a `RevenueRecord` with `revenue_kind` = `RENTAL_FEE` is written with the row-level partner split described in §2.12.

The rental fee at creation is computed as `billing_units` multiplied by `unit_price_cents_snapshot`, expressed in integer cents. Because both operands are integer cents no rounding is required, and the same product is added back into `rental_fee_cents` on every renewal.

### 3.3. Renewal and the Path Through Expiry

A `Renter` who owns a rental may renew it while its `status` is `ACTIVE` or `EXPIRING_SOON`. Renewal supplies `renewal_billing_units` (an integer at least one) and an optional `version`; the housing compartment's `operational_status` must remain `OK`, and the renter's `X-User-ID` must equal the rental's `renter_id`. A renewal extends `current_expires_at` by `renewal_billing_units` multiplied by the unit-duration for the rental's mode, adds `renewal_billing_units` multiplied by `unit_price_cents_snapshot` to `rental_fee_cents`, increments `renewal_count` by one, clears `reminder_sent_at`, and emits a `RevenueRecord` row of `revenue_kind` = `RENTAL_FEE` for the renewal increment. If the rental is `EXPIRING_SOON` at the time of renewal, its `status` returns to `ACTIVE`; if the rental is already `OVERDUE` or terminal, the renewal is rejected with `ERR_RENEWAL_NOT_PERMITTED`.

When the sweep observes that the logical clock has reached at least thirty minutes before a rental's `current_expires_at` while still less than that timestamp, the rental transitions from `ACTIVE` to `EXPIRING_SOON`, `reminder_sent_at` is set to the sweep's run-time (idempotently — the field is only written when it is currently null), and an outbound IM-system reminder event is emitted. When the sweep observes that the clock has reached or passed `current_expires_at` plus `grace_minutes_snapshot` minutes, an `ACTIVE` or `EXPIRING_SOON` rental transitions to `OVERDUE` and the housing compartment's `occupancy_status` cascades to `OVERDUE` in the same operation; overdue-fee accrual begins from the grace-end instant.

The overdue fee at any inspection time is computed as follows. Define the grace-end instant as `current_expires_at` plus `grace_minutes_snapshot` minutes. If the inspection time is at or before the grace-end instant the overdue fee is zero. Otherwise the overdue elapsed time is the number of seconds from the grace-end instant to the inspection time; that elapsed time, divided by 3600, is rounded **up** to the next whole hour (any started hour counts as a full hour), and the resulting number of hours is multiplied by `overdue_rate_snapshot` to yield `overdue_fee_cents`. The rounding-up happens before the multiplication, never after. The system distinguishes two variants of this computation: a live-estimate variant used when a reader fetches a rental whose status is `OVERDUE`, which uses the current logical clock as the inspection time and is not persisted; and a final-settled variant used at the moment of return or force-clearance, which uses the transition's `ended_at` as the inspection time, persists the value into `overdue_fee_cents`, and is what later reads of the rental return — subsequent fetches do not recompute against a moving clock.

### 3.4. Insurance at Rental Time

Each rental opt-in to insurance via the `insurance_tier` field, which is one of `NONE`, `BASIC`, or `PREMIUM`. When `insurance_tier` is `NONE`, the renter must supply `declared_value_cents` = 0; when `insurance_tier` is `BASIC` or `PREMIUM`, the renter must supply `declared_value_cents` strictly greater than zero and no greater than the declared-value cap of 10,000,000 cents. Any of: a `NONE` rental with non-zero declared value, a `BASIC` or `PREMIUM` rental with zero declared value, or a declared value above the cap, are rejected with `ERR_INVALID_INSURANCE`.

The insurance premium is computed in a pinned order. First, the per-day base rate by tier is fixed: `BASIC` carries a base rate of 50 cents per day and `PREMIUM` carries 150 cents per day. Second, the rental's total duration in days is `billing_units` multiplied by the unit-duration in seconds for the rental's mode, divided by 86,400, rounded **up** to the next whole day. Third, the tier base amount is the per-day rate multiplied by that day count. Fourth, a value-loading amount is computed as `declared_value_cents` multiplied by the tier loading rate (0.002 for `BASIC`, 0.005 for `PREMIUM`) and then rounded up to the next whole cent; the rounding-up is applied **after** the multiplication, not before. Fifth, the value-loading amount is then capped by the tier's loading cap (2,000 cents for `BASIC`, 10,000 cents for `PREMIUM`) by taking the smaller of the two. Sixth, the insurance premium is the sum of the tier base amount and the (rounded, capped) value-loading amount; because both addends are integer cents no further rounding occurs. For `NONE` the entire premium is zero.

`insurance_premium_cents` is stored on the rental at creation time. The total charged at creation is the rental fee plus the insurance premium plus the deposit snapshot, stored as `total_charged_cents`.

### 3.5. Force-Clearance, Holding, and Claim Window

When the sweep observes that the logical clock has reached or passed `current_expires_at` plus `forced_clearance_hours_snapshot` hours on a rental whose `status` is `OVERDUE`, force-clearance fires. The rental's `status` advances to `FORCE_CLEARED`, `ended_at` is set to the transition time, and `deposit_forfeited_cents` is set to the full `deposit_cents_snapshot` regardless of how the overdue fee compares to the deposit; this is the force-clearance variant of deposit settlement and differs from the return variant described in §3.7. The housing compartment cascades to `occupancy_status` = `HOLDING`, its `active_rental_id` is cleared, `holding_item_description` is populated with a free-text description of where the item has been moved, and `holding_claim_deadline` is set to the transition time plus the system-wide holding claim window. Three `RevenueRecord` rows are written in this transition: a `RENTAL_FEE` row (if one has not already been written for the final period), an `OVERDUE_FEE` row whose `gross_cents` is the rental's `overdue_fee_cents` at the transition instant, and a `DEPOSIT_FORFEIT` row whose `gross_cents` is `deposit_cents_snapshot`. An `AuditEvent` of `event_kind` `FORCE_CLEARANCE` is emitted whose `detail` includes the destination locker and the forfeited deposit amount.

After force-clearance, the renter retains the right to retrieve the held item for the duration of the claim window. The holding-claim request is authenticated against the most-recent force-cleared rental that landed on that compartment — the requesting `Renter`'s `X-User-ID` must equal that rental's `renter_id`. If the current time is past the compartment's `holding_claim_deadline`, the request is rejected with `ERR_CLAIM_WINDOW_EXPIRED`. On success the compartment's `occupancy_status` returns to `IDLE`, `holding_item_description` and `holding_claim_deadline` are cleared, and an `AuditEvent` of `event_kind` `COMPARTMENT_OPENED` is emitted with `unlock_channel` = `OPERATOR_OVERRIDE`.

### 3.6. Return, Deposit Settlement, Refund, and Revenue Reconciliation

A `Renter` returns a rental by submitting the return request with `unlock_channel` and optional `version`. The owning renter check applies, and the rental's `status` must be one of `ACTIVE`, `EXPIRING_SOON`, or `OVERDUE`; a return against `RETURNED`, `FORCE_CLEARED`, or `REFUNDED` is rejected with `ERR_INVALID_STATE`. The compartment's `operational_status` must be `OK` so the renter can physically retrieve the item. On success the rental's `status` becomes `RETURNED`, `ended_at` is set to the transition time, the compartment's `occupancy_status` cascades to `IDLE`, the compartment's `active_rental_id` is cleared, and the cabinet capacity statistics are recomputed.

Deposit settlement on return runs the return-path variant of the deposit waterfall: if `overdue_fee_cents` (final-settled at `ended_at`) is at most `deposit_cents_snapshot`, then `deposit_refunded_cents` is `deposit_cents_snapshot` minus `overdue_fee_cents` and `deposit_forfeited_cents` is zero; if `overdue_fee_cents` exceeds the deposit, then `deposit_refunded_cents` is zero, `deposit_forfeited_cents` is zero (the deposit is fully consumed by the overdue charge with no additional penalty levied in this benchmark), and any outstanding balance is tracked through the `OVERDUE_FEE` revenue record rather than collected here. The return transition then emits a `RENTAL_FEE` revenue record for the final rental fee and, if `overdue_fee_cents` is greater than zero, an `OVERDUE_FEE` revenue record at the same amount. An `AuditEvent` of `event_kind` `COMPARTMENT_OPENED` is emitted carrying the `unlock_channel` from the return request.

A returned rental may be refunded by an `Operator`. The refund request supplies optional `version`. The rental must be in `RETURNED`, and the system must observe no `InsuranceClaim` against this rental in status `REPORTED`, `EVIDENCE_PENDING`, `UNDER_REVIEW`, `EVIDENCE_REJECTED`, `APPROVED`, or `PAID` — the only acceptable state of an existing claim is `DENIED`, and the absence of any claim is also acceptable. A refund against a rental with an active or paid claim is rejected with `ERR_REFUND_BLOCKED_BY_CLAIM`. On success the rental's `status` advances to `REFUNDED`, a `REFUND_REVERSAL` `RevenueRecord` row is emitted whose `gross_cents` is the negative of the sum of all prior `RENTAL_FEE` and `OVERDUE_FEE` `gross_cents` for this rental, the partner share for that row is recomputed against the cabinet's current `partner_share_pct` using the row-level rule (so the residual still balances), and any deposit still held is moved into `deposit_refunded_cents`.

Two views over `RevenueRecord` rows are offered for reconciliation. A flat list is available for filtering across cabinets, revenue kinds, and time windows; the time window on the flat list is supplied as `occurred_at_from` and `occurred_at_to` query parameters, and the same two parameters are accepted by the per-cabinet periodic summary endpoint and by the audit-events listing. A per-cabinet periodic summary aggregates the rows whose `occurred_at` falls in `[occurred_at_from, occurred_at_to]`: the summary first sums `gross_cents` across the period, then computes the aggregate partner share as that sum multiplied by `partner_share_pct` divided by 100 and rounded half-up, then derives the aggregate platform share as the period total minus the aggregate partner share. This per-period aggregate variant of the partner split differs from the per-row variant — the per-row variant rounds each row's partner share at row-creation time, and summing the rounded per-row shares can differ from rounding once after summation by up to one cent per row. The summary endpoint MUST report the per-period aggregate.

### 3.7. Capacity Alerts and Redistribution

Whenever a compartment's `occupancy_status` changes between `IDLE`, `RENTED`, `OVERDUE`, and `HOLDING`, or whenever a compartment is created or removed, the parent cabinet's capacity statistics are recomputed in the same request. For each size class, the count of compartments in that class becomes `small_capacity_total`, `medium_capacity_total`, or `large_capacity_total`; the count of compartments in `RENTED` or `OVERDUE` becomes the numerator of the corresponding occupancy percentage, divided by the size-class total and rendered as a percentage rounded half-up to two decimal places. When a size class has zero compartments, its occupancy percentage is zero. `total_compartments` is the sum across size classes.

The cabinet's `capacity_alert_level` is then derived by tiering each size class' occupancy percentage. A percentage at or above 95.00 is `CRITICAL`, a percentage at or above 80.00 (but below 95.00) is `WARNING`, and anything below 80.00 is `NONE`; the overall `capacity_alert_level` is the most severe of the three size-class verdicts (with `CRITICAL` outranking `WARNING` outranking `NONE`). The threshold comparisons are `>=`, not `>`, so a percentage of exactly 80.00 trips `WARNING` and exactly 95.00 trips `CRITICAL`.

When a cabinet is in `WARNING` or `CRITICAL`, an `Operator` may ask the system to recommend a nearby target for redistribution. The redistribution suggestion endpoint runs the following procedure. The candidate set is every other cabinet whose haversine distance from the source is at most 5.0 kilometres (haversine computed against an earth radius of 6371.0 kilometres and rounded to four decimal places), whose `online_status` is `ONLINE`, whose `capacity_alert_level` is `NONE`, and which has at least one compartment in the offending size class with both `operational_status` = `OK` and `occupancy_status` = `IDLE`. If the candidate set is empty the endpoint returns `{ "suggestion": null, "reason": "NO_TARGET_AVAILABLE" }`. Otherwise the candidates are ranked by a score where lower wins: the candidate's distance in kilometres multiplied by ten, added to the sum of the candidate's three size-class occupancy percentages multiplied by one. If two candidates tie on score, the candidate whose `id` is lexicographically smaller wins. The endpoint returns the winning cabinet as `{ "suggestion": cabinet, "reason": null }`.

### 3.8. Faults, Repair Tickets, and Acceptance

When a fault is observed — by the renter, by an `Operator` walking the site, or by an automated detector — a `RepairTicket` is opened against a specific `compartment_id` with a `fault_category` drawn from `DOOR_NOT_CLOSED`, `SENSOR_FAULT`, `COMMUNICATION_LOSS`, and `USER_REPORTED`. The compartment's `operational_status` cascades from `OK` to `FAULT` and its `fault_category` is set; the compartment is now locked out from new rentals (rental-creation requests against it are rejected with `ERR_COMPARTMENT_FAULT`), but any rental already active on the compartment is **not** auto-terminated — the renter retains the right to retrieve the item. The new ticket's `status` is `OPEN` and `reporter_role` is set from the originating role (`RENTER`, `OPERATOR`, or `SYSTEM`).

An `Operator` dispatches the ticket by supplying `assigned_technician_id` and optional `version`; the ticket's `status` advances to `DISPATCHED`. The assigned `RepairTechnician` — and only that technician, identified by `X-User-ID` equality with `assigned_technician_id` — then marks the work as repaired by supplying `repair_notes` and optional `version`; the ticket's `status` advances to `REPAIRED`. Acceptance is the branching step. An `Operator` accepts the repair, advancing `status` to `ACCEPTED`, stamping `accepted_at`, cascading the compartment's `operational_status` back to `OK`, and clearing `fault_category`; this makes the compartment rentable again once `occupancy_status` is `IDLE`. Alternatively the operator rejects the repair by supplying `rejection_reason`, advancing `status` to `REJECTED`; the compartment remains in `FAULT` and a new `RepairTicket` may be opened to continue the work. Both terminal transitions enforce that the source state is `REPAIRED` — attempts from other states return `ERR_INVALID_STATE`.

### 3.9. Insurance Claim Lifecycle

A `Renter` who owns an active or completed rental may file a single insurance claim against it by supplying `rental_id`, `claim_type` (one of `DAMAGE`, `LOSS`, or `THEFT`), and `claimed_amount_cents` (strictly positive). The rental's `insurance_tier` must be `BASIC` or `PREMIUM`; a claim against a `NONE`-tier rental is rejected at the next stage (request-evidence). At most one claim per rental may exist in any state other than `DENIED` or `PAID`; an attempt to file a second open claim is rejected with `ERR_CLAIM_ALREADY_OPEN`. The new claim's `status` is `REPORTED`, `renter_id` is snapshotted from the rental, `evidence_count` is zero, and `payout_cents`, `insurer_reference`, and `rejection_reason` are null.

The lifecycle is driven by the `InsuranceAgent`. The agent requests evidence (`REPORTED` → `EVIDENCE_PENDING`), and the renter then submits evidence by supplying `evidence_description` and optional `version`; submission increments `evidence_count` and, once `evidence_count` is at least one, advances `status` to `UNDER_REVIEW` and emits an outbound insurance-company sync event that sets `insurer_reference`. While `UNDER_REVIEW`, the agent has three exits: reject the current evidence batch by supplying `rejection_reason`, advancing to `EVIDENCE_REJECTED`; approve by supplying `payout_cents`, advancing to `APPROVED`; or deny by supplying `rejection_reason`, advancing to `DENIED`. After `EVIDENCE_REJECTED`, the agent may re-request evidence, returning the claim to `EVIDENCE_PENDING`; this is the cycle that makes the claim state machine non-linear, and it may repeat any number of times. Approval pins `payout_cents` to a value no greater than the smallest of: `claimed_amount_cents`, the rental's `declared_value_cents`, and the tier-payout cap that the system has configured for the rental's `insurance_tier`; an approval that violates this cap is rejected with `ERR_PAYOUT_EXCEEDS_CAP`. After approval the agent records the payout (`APPROVED` → `PAID`), which emits an outbound payment-system sync event indicating that the insurer has paid the renter; `DENIED` and `PAID` are the two terminal states. Throughout the lifecycle, the renter's ownership is checked against the claim's snapshotted `renter_id`, and the agent's writes are gated by role rather than by ownership.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201 Created; endpoints that modify, retrieve, or list existing resources return HTTP 200 OK. Request and response bodies, side effects, and validation rules are described in §2 and §3 — this table is a navigation index rather than a full specification.

| Method | Path                                                                                  | Description                                                                                  | Authorized Role(s)                       |
| ------ | ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ---------------------------------------- |
| POST   | `/pricing-profiles`                                                                   | Create a pricing profile for a (size class, rental mode) pair                                | `Operator`                               |
| GET    | `/pricing-profiles`                                                                   | List pricing profiles, optionally filtered                                                   | `Operator`, `Renter`                     |
| POST   | `/cabinets`                                                                           | Register a new cabinet                                                                       | `Operator`                               |
| GET    | `/cabinets/{cabinet_id}`                                                              | Get cabinet detail with derived capacity statistics                                          | `Operator`, `Renter`                     |
| GET    | `/cabinets`                                                                           | List cabinets, optionally filtered by online status or capacity alert level                  | `Operator`, `Renter`                     |
| PATCH  | `/cabinets/{cabinet_id}`                                                              | Update cabinet firmware version or partner configuration                                     | `Operator`                               |
| POST   | `/cabinets/{cabinet_id}/heartbeat`                                                    | Cabinet heartbeat; recovers from `DEGRADED` or `OFFLINE` to `ONLINE`                         | `Operator`                               |
| GET    | `/cabinets/{cabinet_id}/redistribution-suggestion`                                    | Suggest a nearby relief cabinet when the source is in `WARNING` or `CRITICAL`                | `Operator`                               |
| POST   | `/cabinets/{cabinet_id}/compartments`                                                 | Add a compartment to a cabinet                                                               | `Operator`                               |
| GET    | `/cabinets/{cabinet_id}/compartments/{compartment_id}`                                | Get a single compartment                                                                     | `Operator`, `Renter`                     |
| GET    | `/cabinets/{cabinet_id}/compartments`                                                 | List compartments under a cabinet                                                            | `Operator`, `Renter`                     |
| POST   | `/cabinets/{cabinet_id}/compartments/{compartment_id}/rentals`                        | Create a rental on the specified compartment                                                 | `Renter`                                 |
| POST   | `/compartments/{compartment_id}/claim-holding`                                        | Renter retrieves an item from a `HOLDING` compartment within the claim window                | `Renter`                                 |
| GET    | `/rentals/{rental_id}`                                                                | Get rental detail (overdue fee is live-estimated for `OVERDUE` rentals)                      | `Renter`, `Operator`                     |
| GET    | `/rentals`                                                                            | List rentals, filterable by renter, cabinet, status                                          | `Renter`, `Operator`                     |
| POST   | `/rentals/{rental_id}/renew`                                                          | Renew an `ACTIVE` or `EXPIRING_SOON` rental                                                  | `Renter`                                 |
| POST   | `/rentals/{rental_id}/return`                                                         | Renter returns the item and terminates the rental                                            | `Renter`                                 |
| POST   | `/rentals/{rental_id}/refund`                                                         | Operator refunds a returned rental                                                           | `Operator`                               |
| POST   | `/insurance-claims`                                                                   | Renter files a new insurance claim against a rental                                          | `Renter`                                 |
| GET    | `/insurance-claims/{claim_id}`                                                        | Get a single insurance claim                                                                 | `Renter`, `InsuranceAgent`, `Operator`   |
| POST   | `/insurance-claims/{claim_id}/request-evidence`                                       | Insurance agent requests (or re-requests) evidence                                           | `InsuranceAgent`                         |
| POST   | `/insurance-claims/{claim_id}/evidence`                                               | Renter submits an evidence batch                                                             | `Renter`                                 |
| POST   | `/insurance-claims/{claim_id}/reject-evidence`                                        | Insurance agent rejects the current evidence batch                                           | `InsuranceAgent`                         |
| POST   | `/insurance-claims/{claim_id}/approve`                                                | Insurance agent approves the claim and pins the payout                                       | `InsuranceAgent`                         |
| POST   | `/insurance-claims/{claim_id}/deny`                                                   | Insurance agent denies the claim                                                             | `InsuranceAgent`                         |
| POST   | `/insurance-claims/{claim_id}/pay`                                                    | Insurance agent records payout disbursement                                                  | `InsuranceAgent`                         |
| POST   | `/repair-tickets`                                                                     | Open a repair ticket against a compartment                                                   | `Renter`, `Operator`                     |
| GET    | `/repair-tickets/{ticket_id}`                                                         | Get a repair ticket                                                                          | `Operator`, `RepairTechnician`           |
| POST   | `/repair-tickets/{ticket_id}/dispatch`                                                | Operator dispatches the ticket to a technician                                               | `Operator`                               |
| POST   | `/repair-tickets/{ticket_id}/repair`                                                  | Assigned technician marks the work as repaired                                               | `RepairTechnician`                       |
| POST   | `/repair-tickets/{ticket_id}/accept`                                                  | Operator accepts the repair; compartment returns to `OK`                                     | `Operator`                               |
| POST   | `/repair-tickets/{ticket_id}/reject`                                                  | Operator rejects the repair; compartment stays in `FAULT`                                    | `Operator`                               |
| GET    | `/revenue-records`                                                                    | List individual revenue records for reconciliation                                           | `Operator`                               |
| GET    | `/cabinets/{cabinet_id}/revenue-summary`                                              | Periodic revenue summary per cabinet (per-period aggregate split)                            | `Operator`                               |
| GET    | `/audit-events`                                                                       | List audit events filtered by event kind, subject, actor, or time window                     | `Operator`                               |
| POST   | `/_clock/advance`                                                                     | Test-driver capability: advance the logical clock to `to_timestamp`                          | `Operator`                               |
| POST   | `/_sweep/run`                                                                         | Run the periodic sweep that fires time-gated transitions                                     | `Operator`                               |

## 5. Error Code Catalogue

| Error ID                       | HTTP Status |
| ------------------------------ | ----------- |
| `ERR_UNAUTHORIZED`             | 401         |
| `ERR_FORBIDDEN`                | 403         |
| `ERR_NOT_FOUND`                | 404         |
| `ERR_PRICING_PROFILE_NOT_FOUND`| 404         |
| `ERR_BAD_REQUEST`              | 422         |
| `ERR_VERSION_CONFLICT`         | 409         |
| `ERR_INVALID_STATE`            | 409         |
| `ERR_COMPARTMENT_FAULT`        | 409         |
| `ERR_COMPARTMENT_UNAVAILABLE`  | 409         |
| `ERR_CABINET_OFFLINE`          | 409         |
| `ERR_INVALID_INSURANCE`        | 422         |
| `ERR_RENEWAL_NOT_PERMITTED`    | 409         |
| `ERR_CLAIM_ALREADY_OPEN`       | 409         |
| `ERR_CLAIM_WINDOW_EXPIRED`     | 409         |
| `ERR_REFUND_BLOCKED_BY_CLAIM`  | 409         |
| `ERR_PAYOUT_EXCEEDS_CAP`       | 422         |
| `ERR_DUPLICATE_PROFILE`        | 409         |
| `ERR_DUPLICATE_SLOT`           | 409         |
