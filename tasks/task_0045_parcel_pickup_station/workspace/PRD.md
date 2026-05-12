# Parcel Pickup Station API — Product Requirements Document

## 1. Introduction

Community parcel pickup stations sit between courier networks and end-recipients: couriers drop parcels off in bulk, clerks shelve them into a known slot grid, and recipients later present a code, an authorization, or a face-match flag to retrieve them. The platform described by this document is the system of record for that handover. It manages station configuration (operating hours, total storage capacity, shelf zones, staff roster), parcel lifecycle (inbound registration, shelving, overtime accrual, long-stay return coordination, pickup, disposal), recipient-facing pickup codes and on-behalf-of authorizations, automated reminders across SMS and IM channels, monthly billing to both courier companies and recipients, and a per-period quality assessment that feeds back into how much a station is paid.

Several concerns run as cross-cutting threads through every workflow: an audit trail must be appended for every state-changing action; outbound events must be queued for downstream PAYMENT, IM, and COURIER systems so external integrations stay in sync; storage fees accrue along a tiered hourly schedule that, once a parcel reaches a terminal state, is locked and may not be re-derived. The product goal is a single fair, auditable, and idempotent surface that the station's own staff, recipients, courier-company integrations, an external payment system, and a platform-administrator operator can all share without stepping on each other's writes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header is rejected with `ERR_AUTH_MISSING` and HTTP 401. A request whose role is not authorized for the requested operation is rejected with `ERR_FORBIDDEN` and HTTP 403.

The platform defines exactly five roles, spelled as shown:

- **`PlatformAdmin`** — operator of the platform itself; creates stations, advances the test clock, drives external courier events, and reads the system-event outbox.
- **`Manager`** — station manager; configures shelf zones, manages staff, runs billing-period and quality-assessment closes, resolves disputes, disposes long-stay parcels, and requests returns.
- **`Clerk`** — front-desk staff; registers inbound parcels and handles pickup verification.
- **`Recipient`** — end user; creates pickup authorizations, requests reissued codes, reads their own parcels, and disputes their own bills.
- **`CourierCompany`** — courier-side actor; responds to return-shipment requests, marks return legs shipped, and disputes courier-side bills.
- **`PaymentSystem`** — external payment integration that records bill payments.

When `X-User-Role` is `Manager`, `X-User-ID` is the `id` of the acting `Staff` record; when `X-User-Role` is `Clerk`, `X-User-ID` is likewise the `id` of the acting `Staff` record. For both roles, any ownership or station-scoping check on a resource that references a `Staff` (for example, the staff actor recorded on an `AuditEvent`) compares the resource's foreign key to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `Recipient`, `CourierCompany`, or `PaymentSystem`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `actor_id` on `AuditEvent` rows the relevant transition writes) but does not compare it to any entity's `id`.

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

All list endpoints accept two query parameters: `limit` and `offset`. The default `limit` is 10, the minimum is 1, the maximum is 100; values outside this range yield `ERR_VALIDATION`. The default `offset` is 0. List endpoints default to sorting by `created_at` ascending. The `meta` block of a list response includes `limit`, `offset`, `total_count`, and `has_more` derived from the underlying scan.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id` that is a UUID string with no type prefix. Resources whose specification declares the common-fields set additionally carry `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits), and `version` (a non-negative integer that increments by one on every successful mutation). The common-fields set applies to `Station`, `ShelfZone`, `Staff`, `Parcel`, `PickupCode`, `ReturnShipment`, `BillingPeriod`, `Bill`, and `QualityAssessment`.

`PickupAuthorization`, `ReminderRecord`, `AuditEvent`, and `SystemEventOutbox` are append-or-narrow-lifecycle records that carry only `id` and `created_at`; they expose neither `updated_at` nor `version`. (`PickupAuthorization` may still transition through its own `status` enumeration without exposing `version`; ownership-style revocation is the only mutation, and it is reflected by a `status` change.)

### 2.5. Nested Resource Path Validation

URLs are validated left-to-right. For a path such as `/stations/{station_id}/billing-periods/{period_yyyymm}/close`, the `station_id` must resolve to a `Station` before the `period_yyyymm` is looked up; the `period_yyyymm` must resolve to a `BillingPeriod` under that station before the close action is considered. Any unresolved segment, in order, yields `ERR_RESOURCE_NOT_FOUND` with HTTP 404. Foreign keys that arrive in the request body — for example, `shelf_zone_id` on parcel registration or `billing_period_id` when joining a bill into a period — are likewise resolved against existing rows; an unresolved foreign key returns the same `ERR_RESOURCE_NOT_FOUND`.

### 2.6. Optimistic Concurrency Control

All `PATCH`/`PUT` mutations accept an optional `version` field in the request body. When the client supplies `version`, the server compares it against the current entity's `version`; a mismatch yields `ERR_VERSION_CONFLICT` with HTTP 409, and the request is otherwise refused without side effect. When the client omits `version`, the OCC check is skipped and the mutation proceeds against the latest row.

### 2.7. Money, Time, and Rounding

Monetary amounts are stored and returned as numbers with two decimal places, rounded half-up. Storage-fee accrual, handover-fee aggregation, the quality-adjusted handover step, and the per-period final total all follow the same two-decimal half-up rule; the only departures from this rule are explicitly called out in §3 (notably the pinned order in which the period-final total rounds the adjusted handover before adding storage, and the four-decimal rounding of quality-component rates before they are mixed). Time is always UTC ISO 8601 with three fractional digits.

### 2.8. Hierarchical State Consistency and Side Effects

State-changing actions in this domain are rarely isolated. Inbound acceptance simultaneously updates the parent station's `current_occupancy` and the targeted zone's `occupied_slots`, mints the initial pickup code, queues the first reminder, and emits the outbound IM event for code delivery. Pickup, return, and disposal each decrement those denormalized counters and lock the parcel's storage fee. Closing a billing period snapshots its quality-adjustment factor, recomputes its rolled-up amounts, issues every child `DRAFT` bill, and queues a payment-system event per bill. Every such mutation also refreshes `updated_at` on the affected entity and bumps `version` by one. A parcel reaching `RETURNED` or `DISPOSED` also voids any still-`ACTIVE` or still-`REISSUED` pickup codes for that parcel.

### 2.9. Idempotency and Sweep Safety

Two operations are designed to be re-runnable without corruption. The first is bill payment: a payment request must carry an `idempotency_key`, and a replay of the same `(bill_id, idempotency_key)` pair returns the original payment's result with the synthetic identifier `ERR_IDEMPOTENCY_REPLAY` and HTTP 200, rather than producing a second `PAID` transition. The second is the sweep capability: the overtime-plus-long-stay sweep walks every non-terminal parcel and emits a reminder only if the matching tier has not yet been emitted for that parcel; if no parcel qualifies, the sweep is a no-op and returns an empty list at HTTP 200.

### 2.10. Outbound Event Outbox and Audit Trail

State-changing actions append an `AuditEvent` row whose `subject_kind` names the affected entity type (one of `Parcel`, `Bill`, `PickupCode`, or `ReturnShipment`), whose `subject_id` is that entity's id, whose `action` is a stable verb-tense label (e.g., `INBOUND_ACCEPTED`, `BILL_DISPUTED`, `SHELF_REASSIGNED`), whose `actor_role` and `actor_id` mirror the request's `X-User-Role` and `X-User-ID`, whose `from_state` and `to_state` carry the state names where applicable (and `from_state` is null on initial creation, `to_state` null on non-state-changes), and whose `payload` is a JSON object that captures the action diff (for example, `{"from_zone": "A", "to_zone": "B"}` on a shelf reassignment). External integrations are reached through a `SystemEventOutbox` whose `target_system` is one of `PAYMENT`, `IM`, or `COURIER`, whose `event_name` is a stable label (e.g., `BILL_ISSUED`, `RETURN_REQUESTED`, `PICKUP_CODE_SENT`, `PICKUP_CODE_REISSUED`, `INBOUND_HANDSHAKE`, `RETURN_SHIPPED`), whose `subject_kind` and `subject_id` name the entity, whose `payload` carries the event body, whose `sequence` is a monotonic counter per `(subject_kind, subject_id)`, and whose `emitted_at` is the timestamp the event was queued.

### 2.11. Validation Priority Order

When a single request fails more than one rule, the response carries the highest-priority error from the following ordering (lower number wins). Authentication checks fire first: missing headers (`ERR_AUTH_MISSING`) precede insufficient role (`ERR_FORBIDDEN`). Existence checks come next, in two stages — path-segment resolution then body foreign-key resolution, both returning `ERR_RESOURCE_NOT_FOUND`. State checks follow: station-not-active (`ERR_STATION_NOT_ACTIVE`) precedes parcel-state incompatibility (`ERR_INVALID_PARCEL_STATE`) which precedes bill-state incompatibility (`ERR_INVALID_BILL_STATE`). Business-safety checks (exception-parcel cannot also shelve — `ERR_EXCEPTION_PARCEL_CANNOT_SHELVE`) come before referential checks (zone-station mismatch — `ERR_SHELF_ZONE_STATION_MISMATCH`), which come before business-constraint checks evaluated in this order: shelf-position occupied (`ERR_SHELF_POSITION_OCCUPIED`), zone full (`ERR_SHELF_ZONE_FULL`), station capacity exceeded (`ERR_STATION_CAPACITY_EXCEEDED`), and duplicate tracking number (`ERR_DUPLICATE_TRACKING_NUMBER`). Pickup verification (`ERR_PICKUP_VERIFICATION_FAILED`), authorization expiry validity (`ERR_AUTHORIZATION_EXPIRY_INVALID`), disposal earliness (`ERR_DISPOSAL_TOO_EARLY`), period-not-ended (`ERR_PERIOD_NOT_ENDED`), quality-assessment-not-closed (`ERR_QUALITY_ASSESSMENT_NOT_CLOSED`), dispute-reason-required (`ERR_DISPUTE_REASON_REQUIRED`), and payment idempotency-key-required (`ERR_IDEMPOTENCY_KEY_REQUIRED`) each apply to their respective endpoints; finally, OCC `ERR_VERSION_CONFLICT` is evaluated last on any `PATCH`/`PUT`. Schema-level range/format violations that do not match a more specific code surface as `ERR_VALIDATION` at HTTP 422.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Station

A `PlatformAdmin` creates a station with a `name` between 1 and 100 characters, a free-form `address`, business hours given as `business_hours_open` and `business_hours_close` in the `HH:MM` 24-hour pattern (where the close time must be strictly later than the open time on the same day), a `storage_capacity` of at least one parcel, and an optional `free_storage_hours` that defaults to 72 hours when not supplied and must itself be at least one. Newly created stations start in `ACTIVE` `status`, with `current_occupancy` initialized to zero and `quality_score` initialized to null until the first quality assessment closes for the station.

Once a station exists, a `Manager` populates its shelf grid. Each shelf zone carries a `zone_code` that is unique within its parent station and is between 1 and 16 characters in length, a `row_count` and a `column_count` (each at least one), and a `zone_type` drawn from `STANDARD`, `OVERSIZED`, `FRAGILE`, or `COLD` with `STANDARD` as the default. The server derives the zone's `capacity` as the row count multiplied by the column count and maintains `occupied_slots` as the live count of parcels assigned to the zone whose `status` is one of `SHELVED`, `OVERTIME`, or `AWAITING_RETURN`. The same `Manager` adds staff to the station: each staff record is addressed by its `staff_id` and carries the station's `station_id`, the staff member's `full_name`, a contact `phone` consisting of 6 to 15 digit characters, and a `role_kind` of either `CLERK` or `MANAGER`. New staff land in `ACTIVE` `status`; managers may move staff to `OFF_DUTY` or `TERMINATED`. Updates to the station itself — including its `name`, `address`, hours, `storage_capacity`, `free_storage_hours`, and operational `status` (`ACTIVE`, `SUSPENDED`, or `CLOSED`) — flow through the station-update capability and may carry an optional `version` for OCC.

The station-update path is also where suspension surfaces. When a station's `status` is not `ACTIVE`, every inbound and pickup action is rejected with `ERR_STATION_NOT_ACTIVE` (HTTP 409); list and read operations remain available while a station is `SUSPENDED`.

### 3.2. Inbound Registration: From Handover to Shelf

A courier-company-side handshake — driven through the test-driving capability that simulates the courier system — pre-announces a parcel by `courier_company_id`, `tracking_number`, `station_id`, `recipient_phone`, `weight_grams`, and `size_class`. No database row is written by this handshake; instead it queues a `COURIER`-targeted `INBOUND_HANDSHAKE` event into the outbox so external systems stay in sync, and clears the way for the clerk's subsequent registration.

A `Clerk` then registers the parcel against the station; the resulting record is addressed by its `parcel_id`. The registration payload carries the courier identifiers `courier_company_id` and `tracking_number`, the recipient's `recipient_phone` (a 6-to-15-digit string), an optional `recipient_name` (which may be null and defaults to null), the declared `weight_grams` (at least one), and the `size_class` from the set `S`, `M`, `L`, or `XL`. If the parcel is being accepted normally, the clerk also supplies a target `shelf_zone_id` together with a `shelf_position` label of the form `Rxx-Cyy`. If, on the other hand, the parcel arrived damaged or to the wrong station, the clerk records this by setting `exception_type` to either `DAMAGED` or `WRONG_DELIVERY` (the default value when not supplied is `NONE`). The boolean parameter `accept_and_shelve` distinguishes the normal acceptance path from the exception path: the value `true` (or the absence of a non-`NONE` `exception_type`) advances the state machine from `UNREGISTERED` to `SHELVED`, while a non-`NONE` `exception_type` advances it from `UNREGISTERED` to `REJECTED`.

The normal acceptance path is conditional on five things, all of which must hold: the station's `status` must be `ACTIVE`; the station's `current_occupancy` must be strictly less than its `storage_capacity` (otherwise the request is rejected with `ERR_STATION_CAPACITY_EXCEEDED`); the targeted shelf zone's `occupied_slots` must be strictly less than its `capacity` (otherwise `ERR_SHELF_ZONE_FULL`); the request's `exception_type` must be `NONE`; and no other `ACTIVE`-lifecycle parcel may share this courier company's `tracking_number`. Two further structural checks fire before capacity is consulted: a referential check that the targeted shelf zone's `station_id` matches the path station — a mismatch raises `ERR_SHELF_ZONE_STATION_MISMATCH` — and an occupancy check that no other parcel currently in `SHELVED`, `OVERTIME`, or `AWAITING_RETURN` already holds the target `shelf_position` in that zone (otherwise `ERR_SHELF_POSITION_OCCUPIED`). Acceptance pins the parcel to its `shelf_zone_id` and `shelf_position`, sets `shelved_at` to the current server time, computes `free_storage_deadline` as `shelved_at` plus the parent station's `free_storage_hours` worth of hours (immutable once set), increments the station's `current_occupancy` and the zone's `occupied_slots` by one each, mints an initial pickup code (see §3.3), emits the first reminder record (tier `T1_INITIAL`, channel `SMS`, `triggered_by` `INBOUND`), appends an `AuditEvent` whose `action` is `INBOUND_ACCEPTED`, and queues an `IM`-targeted `PICKUP_CODE_SENT` event into the outbox.

The exception path is gentler. It only requires that the station's `status` is `ACTIVE` or `SUSPENDED` and that `exception_type` is not `NONE`. It does not consume capacity, does not occupy a shelf slot, leaves `shelf_zone_id` and `shelf_position` null, sets the parcel's `status` to `REJECTED` with `exception_type` preserved, and appends an audit event of `action` `INBOUND_REJECTED` whose `payload` records the exception type. If a request both names a non-`NONE` `exception_type` and asks for a shelf assignment, the safety rule fires before any capacity or referential check and the request is refused with `ERR_EXCEPTION_PARCEL_CANNOT_SHELVE`.

A parcel that was rejected can be re-presented; a fresh registration after a `REJECTED` row simply produces a new parcel row from `UNREGISTERED`. Because the duplicate-tracking rule applies only to active-lifecycle rows (those whose `status` is not in the `REJECTED` set), the re-presentation is not blocked by the first attempt.

### 3.3. Pickup Codes: Minting, Reissuance, and Voiding

Inbound acceptance mints the first pickup code automatically. Codes are six-digit numeric strings — the format is exactly six digits — and the code minting routine picks a random 6-digit candidate, rejects it if any other `PickupCode` row currently in `ACTIVE` status holds the same `code`, and retries up to 20 times; if 20 candidates all collide, the registration fails with `ERR_PICKUP_CODE_GENERATION_EXHAUSTED`. The newly minted row records `code`, sets `status` to `ACTIVE`, stamps `issued_at` to the current time, sets `issue_reason` to `INITIAL`, and leaves both `consumed_at` and `superseded_by` null. The `code` uniqueness rule is platform-wide and applies only across rows in `ACTIVE` status — codes that have transitioned to `REISSUED`, `CONSUMED`, or `VOIDED` are not eligible to collide.

A `Recipient` (or a `Clerk` acting on the recipient's behalf) may request a reissued code when the original is lost. The reissue request carries a `reason`. To be eligible, the parent parcel must currently be in one of `SHELVED`, `OVERTIME`, or `AWAITING_RETURN`, and an `ACTIVE` code must currently exist for the parcel. On success, the old code transitions from `ACTIVE` to `REISSUED`, its `superseded_by` is set to the new code's id, and a fresh code is minted under the same six-digit collision rules with `issue_reason` `REISSUED_LOST`; an `IM`-targeted `PICKUP_CODE_REISSUED` event is queued. If two reissue requests for the same parcel arrive simultaneously, exactly one succeeds — the second is refused with `ERR_PICKUP_CODE_REISSUE_RACE` (HTTP 409) — so that at most one `ACTIVE` code exists per parcel at any moment.

Codes terminate in one of two ways. When a parcel is successfully picked up using the code, that code transitions from `ACTIVE` to `CONSUMED` and its `consumed_at` is stamped. When the parent parcel reaches the terminal states `RETURNED` or `DISPOSED`, any still-`ACTIVE` code transitions to `VOIDED` (with `consumed_at` explicitly set to null) and any still-`REISSUED` (older) code also transitions to `VOIDED`. A code in `CONSUMED` is already terminal and is not further altered by parcel disposal.

### 3.4. On-Behalf-of Pickup Authorizations

When the recipient cannot collect in person, a `Recipient` may authorize a delegate. The authorization payload supplies the delegate's `delegate_name`, the delegate's `delegate_id_number` (a government ID number), the delegate's `delegate_phone`, and an `expires_at` instant. The server stamps `granted_at` itself, sets the authorization's `status` to `ACTIVE`, and validates the expiry window: the `expires_at` must be strictly later than the just-stamped `granted_at` and no later than the parcel's `free_storage_deadline` plus seven days. A violation surfaces as `ERR_AUTHORIZATION_EXPIRY_INVALID` (HTTP 422). Because `PickupAuthorization` carries no common version field, OCC does not apply to it; revocation flows through the authorization-update capability and simply sets its `status` to `REVOKED`. When an authorization is presented at pickup time, it must still be in `ACTIVE` status and the current server time must be strictly less than its `expires_at`; otherwise the pickup fails with `ERR_PICKUP_VERIFICATION_FAILED` (or, where the framing emphasizes the authorization's own state, `ERR_AUTHORIZATION_EXPIRED`).

### 3.5. Reminder Cadence and the Sweep

A reminder is a row that records `tier`, `channel`, `sent_at`, and `triggered_by`. The four tiers, in order of escalation severity, are `T1_INITIAL`, `T2_FOLLOWUP`, `T3_ESCALATION`, and `T4_RETURN_CONFIRM`. The channels are `SMS` and `IM`. The sweep capability — which a `PlatformAdmin` or `Manager` runs against the platform, optionally narrowed to a single `station_id` — walks every non-terminal parcel and applies three rules in sequence. First, for each parcel still in `SHELVED` where the current server time is at or after its `free_storage_deadline` and no `T2_FOLLOWUP` reminder has yet been recorded for that parcel, a reminder is emitted at tier `T2_FOLLOWUP` over `SMS` with `triggered_by` `OVERTIME_SWEEP`; the parcel is advanced from `SHELVED` to `OVERTIME` and its `storage_fee_total` is recomputed (provisional). Second, for each parcel currently in `OVERTIME` where the current server time is at or after `free_storage_deadline` plus 24 hours and no `T3_ESCALATION` reminder has yet been recorded for that parcel, a reminder is emitted at tier `T3_ESCALATION` over `IM` with `triggered_by` `OVERTIME_SWEEP`. Third, for each parcel currently in `OVERTIME` where the current server time is at or after `shelved_at` plus 168 hours, the parcel is advanced from `OVERTIME` to `AWAITING_RETURN`, `long_stay_flagged_at` is stamped to the current time, and a reminder is emitted at tier `T4_RETURN_CONFIRM` over `IM` with `triggered_by` `LONG_STAY_SWEEP`. The sweep is idempotent: it never emits a duplicate `ReminderRecord` for the same tier on the same parcel, so multiple back-to-back sweep calls are safe and a sweep where no parcel qualifies returns at HTTP 200 with an empty emission list. Each `SHELVED → OVERTIME` transition appends an `AuditEvent` of `action` `OVERTIME_FLAGGED`; each `OVERTIME → AWAITING_RETURN` transition appends `LONG_STAY_FLAGGED`.

Test scenarios may need to fast-forward time without waiting on wall-clock duration. The clock-advance capability — `PlatformAdmin`-only — accepts a `seconds` argument and shifts the server's logical `now()` forward by that many seconds; the response is an object reporting the new now-value. Combined with the sweep, this lets the test suite drive the entire long-stay → return → disposal arc deterministically.

### 3.6. Pickup Verification

A `Clerk` collects a parcel using one of three verification methods. The pickup payload specifies `verification_method` as the discriminator and, depending on the choice, fills in either `code` (the six-digit code), `authorization_id` and `delegate_id_number` together, or `face_match` (a server-trusted boolean flag). Pickup is permitted from `SHELVED`, `OVERTIME`, or `AWAITING_RETURN` — but the third case is only permitted when no `ReturnShipment` exists for the parcel whose `status` is `COURIER_ACCEPTED`, `SHIPPED`, or `DISPOSED`. Verification succeeds if any one of the following holds: the supplied `code` matches an `ACTIVE` `PickupCode` for this parcel; or the supplied `authorization_id` resolves to a `PickupAuthorization` whose `status` is `ACTIVE`, whose `delegate_id_number` matches the supplied value, and whose `expires_at` is strictly later than the current server time; or `face_match` is true. None of these holding raises `ERR_PICKUP_VERIFICATION_FAILED`.

On success, the parcel's `status` becomes `PICKED_UP`, its `picked_up_at` is stamped, and its `storage_fee_total` is finalized — that is, recomputed one final time from `shelved_at` through `picked_up_at` and then `storage_fee_locked` is set to true. If the finalized `storage_fee_total` is strictly greater than zero, the parcel is rolled into a `RECIPIENT`-`payer_kind` bill for the parcel's current billing period (the bill is created lazily if no `RECIPIENT` bill yet exists for that period, recipient, and station). If the code path was used, the matching code transitions from `ACTIVE` to `CONSUMED` and stamps `consumed_at`. If the authorization path was used, the matching authorization transitions from `ACTIVE` to `CONSUMED`. The station's `current_occupancy` and the zone's `occupied_slots` each decrement by one, and an audit event of `action` `PICKED_UP` is appended. When two clerks try to pick up the same parcel simultaneously, the first writer wins the `PICKED_UP` transition; the loser is refused with `ERR_PARCEL_ALREADY_PICKED_UP` (HTTP 409). A pickup against an `AWAITING_RETURN` parcel that still has a `REQUESTED` `ReturnShipment` succeeds, but the side effects also flip that return's `status` from `REQUESTED` to `COURIER_DECLINED` with a note.

### 3.7. Returns and Disposal of Unclaimed Parcels

Once a parcel is in `AWAITING_RETURN`, a `Manager` may request that the courier reclaim it. The return-shipment request optionally carries `courier_tracking_return` for the courier's return-leg tracking; the request is recorded as a new `ReturnShipment` (addressed by its `return_shipment_id`) whose `status` is `REQUESTED`, whose `courier_company_id` mirrors the parcel's at request time, and whose `requested_at` is stamped server-side. A courier-system event then records the courier's response by setting `decision` to either `accept` or `decline`: acceptance flips the return's `status` from `REQUESTED` to `COURIER_ACCEPTED` and stamps `courier_response_at`; declination flips it to `COURIER_DECLINED` and likewise stamps `courier_response_at`. Both responses require the parent parcel to still be in `AWAITING_RETURN`. A subsequent ship action — accepting `courier_tracking_return` if not yet recorded — flips the return from `COURIER_ACCEPTED` to `SHIPPED`, stamps `shipped_at`, and cascades the parent parcel from `AWAITING_RETURN` to `RETURNED`; on the cascade the parcel's `returned_at` is stamped, its `storage_fee_total` is finalized and `storage_fee_locked` is set to true, both occupancy counters decrement, an `AuditEvent` of `action` `RETURNED` is appended, and a `COURIER`-targeted `RETURN_SHIPPED` event is queued.

When a parcel languishes past every escalation, the `Manager` may finally dispose of it. Disposal is permitted only when `long_stay_flagged_at` is non-null and the current server time is at or after `long_stay_flagged_at` plus 240 hours, and only when no `ReturnShipment` for the parcel is currently in `COURIER_ACCEPTED` or `SHIPPED`. A premature disposal attempt is refused with `ERR_DISPOSAL_TOO_EARLY` (HTTP 422). On success, the parcel transitions from `AWAITING_RETURN` to `DISPOSED`, `storage_fee_locked` becomes true, both occupancy counters decrement, and an audit event of `action` `DISPOSED` is appended. The optional `reason` text on the disposal call is recorded inside the audit `payload`. A race between pickup and disposal on the same `AWAITING_RETURN` parcel serializes to one winner; the loser receives `ERR_INVALID_PARCEL_STATE` (HTTP 409).

### 3.8. Storage-Fee Accrual: Tiered Hourly Pricing

A parcel's storage fee begins to accrue only after its `free_storage_deadline`. Until that moment, `storage_fee_total` is zero. At any evaluation time `t` — either the current server time (provisional) or the terminal-state timestamp (final) — the formula is the same. If `t` is at or before `free_storage_deadline`, the fee is zero. Otherwise, the overdue duration is the difference `(t - free_storage_deadline)` expressed in hours and rounded up to the next whole hour. That whole-hour overdue value is then split into three tiers: the first tier covers the first 24 of those overdue hours and is priced at 0.50 CNY per hour; the second tier covers the next 72 overdue hours (overdue hours 25 through 96) and is priced at 1.00 CNY per hour; the third tier covers all overdue hours beyond 96 and is priced at 2.00 CNY per hour. The first-tier count is the minimum of the overdue hours and 24. The second-tier count is the maximum of zero and the minimum of (overdue hours minus 24) and 72. The third-tier count is the maximum of zero and (overdue hours minus 24 minus 72). The raw subtotal is the sum of each tier count multiplied by its tier rate. That raw subtotal is then multiplied by the size multiplier — 1.0 for `S`, 1.0 for `M`, 1.5 for `L`, and 2.0 for `XL` — and the final number is rounded to two decimal places, half-up. Rounding happens exactly once, after the size multiplier has been applied.

The accrual has two variants. The provisional variant is invoked during the overtime sweep and as a snapshot when a billing period is being closed: it uses `t = now()`, writes the resulting figure to `storage_fee_total`, and leaves `storage_fee_locked` false. The final variant is invoked when the parcel transitions into `PICKED_UP`, `RETURNED`, or `DISPOSED`: it uses `t` equal to that terminal-state timestamp (`picked_up_at`, `returned_at`, or the disposal time, respectively), writes the resulting figure to `storage_fee_total`, and sets `storage_fee_locked` to true. Once locked, subsequent recomputes must not alter the recorded `storage_fee_total`.

### 3.9. Monthly Billing: Period, Bills, and Quality Adjustment

Bills are grouped into per-station monthly billing periods. A `Manager` or `PlatformAdmin` creates (or fetches the existing) `BillingPeriod` for a given `period_yyyymm` — a six-digit `YYYYMM` string that is unique per station. The server derives `period_start` as the first day of that month at 00:00:00.000 UTC and `period_end` as the first day of the following month at 00:00:00.000 UTC; the start is inclusive and the end exclusive. A new period begins life in `OPEN` `status`, with `handover_fee_total`, `storage_fee_total`, `final_total` all initialized to zero and `quality_adjustment_factor` initialized to 1.0.

Children of the period are `Bill` rows; each is addressed by its `bill_id`. Each bill names its parent `billing_period_id`, declares its `payer_kind` (`COURIER_COMPANY` for handover-fee bills, `RECIPIENT` for storage-fee bills), and records a `payer_ref` — the `courier_company_id` for a courier-company bill and the `recipient_phone` for a recipient bill. The bill rolls up `handover_fee_amount`, `storage_fee_amount`, and a `parcel_count`. A new bill begins in `DRAFT` and is held there until its parent period closes.

Period close is gated on two preconditions. The current server time must be at or after `period_end` — otherwise the close is refused with `ERR_PERIOD_NOT_ENDED` (HTTP 422). And the `QualityAssessment` for the same `(station_id, period_yyyymm)` must be in `status` `CLOSED` — otherwise the close is refused with `ERR_QUALITY_ASSESSMENT_NOT_CLOSED` (HTTP 422). On a successful close, the period snapshots its `quality_adjustment_factor` from the assessment's `composite_score` (see §3.10), recomputes `handover_fee_total` and `storage_fee_total` from its child bills' rollups, recomputes its `final_total` per the pinned rounding order, transitions to `CLOSED`, and every child bill in `DRAFT` flips to `ISSUED` with `issued_at` stamped and a `PAYMENT`-targeted `BILL_ISSUED` event queued per bill.

Handover-fee rollup. For each pair of (`BillingPeriod`, `courier_company_id`) the system counts the parcels at the period's station whose `shelved_at` lies in the half-open interval `[period_start, period_end)` and whose terminal `status` is not `REJECTED`. (Rejected parcels were never shelved and so contribute nothing; a re-presentation after rejection is a fresh parcel row and counts in its own right.) That count is multiplied by the per-parcel handover fee of 0.80 CNY and rounded to two decimal places half-up; the result becomes `handover_fee_amount` on the courier-company bill. Storage-fee rollup. For each recipient bill, the bill's `storage_fee_amount` is the sum of `Parcel.storage_fee_total` finalized within the period for that recipient, again rounded to two decimal places half-up. The handover-fee amount on recipient bills is zero, and the storage-fee amount on courier-company bills is zero.

Period final total. The order of operations is pinned and must not be re-associated. First, the period multiplies `handover_fee_total` by `quality_adjustment_factor` and rounds that intermediate product to two decimal places half-up. Then it adds `storage_fee_total` to that rounded intermediate. Then it rounds the sum again to two decimal places half-up. The result becomes `final_total`. This is deliberately distinct from rounding `(handover_total * factor + storage_total)` in one step, and that one-step variant is not permitted.

After close, payments may arrive. A `PaymentSystem` posts a payment to a bill with an `idempotency_key` and an `amount`; a missing `idempotency_key` is refused with `ERR_IDEMPOTENCY_KEY_REQUIRED`. A successful payment requires the bill's `status` to be `ISSUED`, requires the parent period to be in `CLOSED` or `DISPUTED`, and flips the bill from `ISSUED` to `PAID` with `paid_at` stamped. Two payments with the same idempotency key on the same bill collapse: the second returns the original outcome with `ERR_IDEMPOTENCY_REPLAY` at HTTP 200. Two payments with different idempotency keys racing on the same already-`PAID` bill instead surface `ERR_BILL_ALREADY_PAID` (HTTP 409) on the loser. Once every sibling bill under a period is in a terminal state (`PAID`, `WRITTEN_OFF`, or `RESOLVED`), the period auto-transitions from `CLOSED` to `SETTLED` and an `AuditEvent` of `action` `PERIOD_SETTLED` is appended.

Either a `Recipient` (for their own recipient-bill) or a `CourierCompany` (for its own courier-bill) may dispute an issued bill. The dispute payload requires a non-empty `reason` — an empty reason returns `ERR_DISPUTE_REASON_REQUIRED` (HTTP 422). On dispute, the bill flips from `ISSUED` to `DISPUTED`, its `dispute_reason` is recorded, and the parent period auto-bubbles from `CLOSED` to `DISPUTED`. Disputing a bill that is not in `ISSUED` is refused with `ERR_BILL_NOT_ISSUED` (HTTP 409); this is also how a close-versus-dispute race resolves — if close wins, the still-`DRAFT` bill is not yet eligible for dispute and the dispute attempt fails fairly. A `Manager` later resolves a disputed bill — optionally supplying an `adjustment_amount` (which may recompute the bill's rolled-up amounts) and an explanatory `note` — flipping it from `DISPUTED` to `RESOLVED`. Alternatively, the same `Manager` may write off a disputed bill with an optional `note`, flipping it from `DISPUTED` to `WRITTEN_OFF`. When no child bill under the period is still in `DISPUTED`, the period auto-bubbles from `DISPUTED` back to `CLOSED` (and may then settle once all bills terminate).

### 3.10. Quality Assessment: From Operations to Revenue Adjustment

In parallel with billing, a per-station, per-month `QualityAssessment` measures four operational signals for the same `(station_id, period_yyyymm)` window. The `mis_shelving_rate` is the count of parcels in the period that have at least one shelf-reassignment audit event recorded against a non-staff-initiated correction, divided by the count of parcels that reached `SHELVED` in the period. The `lost_parcel_rate` is the count of parcels in the period that ended in `REJECTED` status with `exception_type` `WRONG_DELIVERY`, divided by the count of parcels inbound in the period. The `complaint_rate` is the count of bills in the period that entered `DISPUTED`, divided by the count of bills in the period that entered `ISSUED`. The `response_timeliness_score` is the average, over every `ReminderRecord` in the period, of one minus the value `clamp((reminder_delay_minutes - 15) / 15, 0, 1)` — where the SLA is 15 minutes, a delay of 15 minutes or less yields a per-reminder score of 1.0, a delay of 30 minutes or more yields 0.0, and intermediate delays scale linearly; an assessment with no reminders defaults to 1.0. Each of these four component rates is rounded to four decimal places half-up before mixing.

The `composite_score` is the weighted sum: 0.30 multiplied by `(1 - mis_shelving_rate)`, plus 0.30 multiplied by `(1 - lost_parcel_rate)`, plus 0.20 multiplied by `(1 - complaint_rate)`, plus 0.20 multiplied by `response_timeliness_score`. The composite is rounded to two decimal places half-up. The assessment is created in `DRAFT`, and a `Manager` closes it by invoking the assessment-close capability, which computes the four rates, computes the composite, sets `closed_at`, and transitions the assessment from `DRAFT` to `CLOSED`.

The composite then drives the `quality_adjustment_factor` snapshotted at billing-period close. The mapping uses inclusive lower bounds: a composite of 0.95 or greater yields a factor of 1.05; otherwise a composite of 0.85 or greater yields a factor of 1.00; otherwise a composite of 0.70 or greater yields a factor of 0.95; otherwise the factor is 0.85. The factor is read once at period close and pinned onto the period; it does not float thereafter. Until the very first assessment for a station has been closed, the station's `quality_score` remains null; once at least one assessment has closed, the station's `quality_score` carries the latest closed assessment's `composite_score`.

### 3.11. Mis-Shelving Correction and Audit Visibility

A `Clerk` or `Manager` may correct a mis-shelved parcel by moving it to a different `shelf_zone_id` and `shelf_position`, optionally supplying `version` for OCC. The reassignment appends an `AuditEvent` whose `action` is `SHELF_REASSIGNED` and whose `payload` records the `from` and `to` zone/position pair. Non-staff-initiated corrections — i.e., those that the assessment flags as quality-impacting under the mis-shelving-rate definition — are counted toward `mis_shelving_rate` for the encompassing assessment period. A `PlatformAdmin` or `Manager` may list the audit-event ledger to verify activity, filtering by `subject_kind` and `subject_id`. A `PlatformAdmin` may also list the outbox of system events, filtering by `target_system`, `event_name`, or `subject_id`, to confirm that every state change that should have produced an outbound integration call did so.

## 4. Endpoint Definitions

All endpoints obey a consistent status-code convention. A `POST` that creates a new top-level resource returns HTTP 201. Mutations of existing resources — including state-machine transitions invoked via `POST` (pickup, dispute, close, ship, etc.) and `PATCH` updates — return HTTP 200. Read operations return HTTP 200. Authentication and validation failures return the HTTP status indicated by the matching error code in §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/advance` | Advance the server's logical clock by N seconds (test harness). | `PlatformAdmin` |
| POST | `/_sweep/run` | Run overtime + long-stay sweep across all parcels; idempotent (no duplicate reminders). | `PlatformAdmin`, `Manager` |
| POST | `/_events/courier/inbound` | Simulate a courier-company-side handover handshake (test-driving external event). | `PlatformAdmin` |
| POST | `/stations` | Create a station. | `PlatformAdmin` |
| GET | `/stations` | List stations (paginated). | `PlatformAdmin`, `Manager`, `Clerk` |
| GET | `/stations/{station_id}` | Read a station. | `PlatformAdmin`, `Manager`, `Clerk` |
| PATCH | `/stations/{station_id}` | Update station profile (name, hours, capacity, free_storage_hours, status). | `PlatformAdmin`, `Manager` |
| POST | `/stations/{station_id}/shelf-zones` | Create a shelf zone. | `Manager` |
| GET | `/stations/{station_id}/shelf-zones` | List shelf zones for a station. | `Manager`, `Clerk` |
| POST | `/stations/{station_id}/staff` | Create staff. | `Manager` |
| PATCH | `/staff/{staff_id}` | Update staff status. | `Manager` |
| POST | `/stations/{station_id}/parcels` | Register an inbound parcel; assigns shelf position or rejects as exception. | `Clerk` |
| GET | `/stations/{station_id}/parcels` | List parcels at a station. | `Manager`, `Clerk` |
| GET | `/parcels/{parcel_id}` | Read a parcel. | `Manager`, `Clerk`, `Recipient`, `CourierCompany` |
| PATCH | `/parcels/{parcel_id}/shelf` | Reassign a shelf slot (mis-shelving correction). Counted toward `mis_shelving_rate`. | `Clerk`, `Manager` |
| POST | `/parcels/{parcel_id}/pickup` | Pick up a parcel using code, authorization, or face match. | `Clerk` |
| POST | `/parcels/{parcel_id}/dispose` | Manager disposes an unclaimed parcel. | `Manager` |
| POST | `/parcels/{parcel_id}/pickup-codes` | Mint or re-issue a pickup code (reason=LOST). | `Clerk`, `Recipient` |
| GET | `/parcels/{parcel_id}/pickup-codes` | List pickup codes for a parcel (history). | `Clerk`, `Manager`, `Recipient` |
| POST | `/parcels/{parcel_id}/authorizations` | Create an on-behalf-pickup authorization. | `Recipient` |
| PATCH | `/authorizations/{authorization_id}` | Revoke an authorization. | `Recipient` |
| GET | `/parcels/{parcel_id}/reminders` | List reminder records for a parcel. | `Manager`, `Clerk`, `Recipient` |
| POST | `/parcels/{parcel_id}/return-shipments` | Request a return shipment (long-stay parcel). | `Manager` |
| POST | `/return-shipments/{return_shipment_id}/courier-response` | Record courier accept/decline (driven by courier-system event). | `PlatformAdmin`, `CourierCompany` |
| POST | `/return-shipments/{return_shipment_id}/ship` | Mark return shipment shipped; transitions parent parcel to `RETURNED`. | `PlatformAdmin`, `CourierCompany` |
| POST | `/stations/{station_id}/billing-periods` | Create (or fetch) a billing period for a YYYYMM. | `Manager`, `PlatformAdmin` |
| POST | `/stations/{station_id}/billing-periods/{period_yyyymm}/close` | Close a billing period: snapshot fees, factor, issue bills. | `Manager` |
| GET | `/stations/{station_id}/billing-periods/{period_yyyymm}` | Read a billing period with rollups. | `Manager`, `PlatformAdmin` |
| GET | `/billing-periods/{billing_period_id}/bills` | List bills under a period. | `Manager`, `PlatformAdmin`, `CourierCompany`, `Recipient` |
| GET | `/bills/{bill_id}` | Read a bill. | `Manager`, `PlatformAdmin`, `CourierCompany`, `Recipient` |
| POST | `/bills/{bill_id}/payments` | Record a payment (idempotent by `idempotency_key`). | `PaymentSystem` |
| POST | `/bills/{bill_id}/dispute` | Open a dispute on an issued bill. | `Recipient`, `CourierCompany` |
| POST | `/bills/{bill_id}/resolve-dispute` | Resolve dispute (manager). | `Manager` |
| POST | `/bills/{bill_id}/write-off` | Write off a disputed bill. | `Manager` |
| POST | `/stations/{station_id}/quality-assessments` | Create (or fetch) a quality assessment for a YYYYMM. | `Manager`, `PlatformAdmin` |
| POST | `/stations/{station_id}/quality-assessments/{period_yyyymm}/close` | Close the quality assessment: compute `composite_score`. | `Manager` |
| GET | `/stations/{station_id}/quality-assessments/{period_yyyymm}` | Read a quality assessment. | `Manager`, `PlatformAdmin` |
| GET | `/audit-events` | List audit events (filterable). | `PlatformAdmin`, `Manager` |
| GET | `/system-events` | List system events emitted to PAYMENT/IM/COURIER (test introspection). | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_MISSING` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_STATION_NOT_ACTIVE` | 409 |
| `ERR_INVALID_PARCEL_STATE` | 409 |
| `ERR_INVALID_BILL_STATE` | 409 |
| `ERR_INVALID_RETURN_STATE` | 409 |
| `ERR_EXCEPTION_PARCEL_CANNOT_SHELVE` | 422 |
| `ERR_SHELF_ZONE_STATION_MISMATCH` | 422 |
| `ERR_SHELF_POSITION_OCCUPIED` | 409 |
| `ERR_SHELF_ZONE_FULL` | 409 |
| `ERR_STATION_CAPACITY_EXCEEDED` | 409 |
| `ERR_DUPLICATE_TRACKING_NUMBER` | 409 |
| `ERR_PICKUP_VERIFICATION_FAILED` | 422 |
| `ERR_PARCEL_ALREADY_PICKED_UP` | 409 |
| `ERR_PICKUP_CODE_GENERATION_EXHAUSTED` | 409 |
| `ERR_PICKUP_CODE_REISSUE_RACE` | 409 |
| `ERR_AUTHORIZATION_EXPIRY_INVALID` | 422 |
| `ERR_AUTHORIZATION_EXPIRED` | 422 |
| `ERR_DISPOSAL_TOO_EARLY` | 422 |
| `ERR_PERIOD_NOT_ENDED` | 422 |
| `ERR_QUALITY_ASSESSMENT_NOT_CLOSED` | 422 |
| `ERR_BILL_NOT_ISSUED` | 409 |
| `ERR_BILL_ALREADY_PAID` | 409 |
| `ERR_DISPUTE_REASON_REQUIRED` | 422 |
| `ERR_IDEMPOTENCY_KEY_REQUIRED` | 422 |
| `ERR_IDEMPOTENCY_REPLAY` | 200 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_VALIDATION` | 422 |
