# EV Charging Operations API — Product Requirements Document

## 1. Introduction

The electric-vehicle charging network operated by our platform spans many physical sites, each populated with charging piles of varying connector types, rated power outputs, and firmware revisions. Drivers arrive both with a pre-booked hold and as walk-up traffic, and the platform must reconcile pricing across time-of-use windows, membership tiers, promotional campaigns, and roaming arrangements with partner operators. The product surface described here is the canonical back-end contract that joins pile-ledger management, reservation and queue mediation, real-time session metering, fault triage, and operator-to-operator settlement into a single API.

Today, three operational concerns drive this specification. First, every charge that the network delivers must be priced deterministically and reproducibly — the same session settled twice must yield the same cents, with the same allocation between station owner, platform, roaming partner, and tax authority. Second, faults are the dominant cause of revenue leakage and customer dissatisfaction, so the system must isolate a problematic pile instantly, cascade that isolation to anyone who would otherwise have arrived expecting service, and resume normal operation only when a repair has been accepted by the station owner. Third, the financial side — payouts to operators, reversals from refunds, and the audit trail tying both back to original sessions — must be append-only and reconstructible from primitive events, because billing disputes routinely surface weeks after the fact.

The remainder of this document specifies the resources, lifecycles, and calculations the API must enforce. Section 2 fixes the cross-cutting contracts (authentication, response envelope, pagination, precision, optimistic concurrency, audit). Section 3 walks the business workflows. Section 4 lists every endpoint, and Section 5 catalogues the error identifiers the API may return.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every non-test-harness request must carry two HTTP headers: `X-User-ID` (the calling identity) and `X-User-Role` (one of the five recognized roles). A request that omits either header on an endpoint that requires authentication is rejected with `ERR_AUTH_MISSING`. A request whose `X-User-Role` value is not one of the recognized role names, or whose `X-User-ID` does not resolve to a valid actor for that role, is rejected with `ERR_AUTH_INVALID`. A request with valid headers whose role is not authorized for the requested endpoint is rejected with `ERR_FORBIDDEN`.

The five recognized roles, spelled exactly:

- `PlatformOperator` — platform staff. The role identity is opaque: when `X-User-Role` is `PlatformOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `actor_id` on `AuditLog` rows produced by the operator's actions) but does not compare it to any entity's `id`. `PlatformOperator` is the only role permitted to create pricing versions and promotional activities, decommission piles, open repair tickets, create and issue payouts, and exercise the test-harness endpoints (clock advance, sweep, external event emission).
- `StationOwner` — owners of one or more physical stations. The role is entity-backed by `Operator`: when `X-User-Role` is `StationOwner`, `X-User-ID` is the `id` of the acting `Operator`. Ownership checks on any resource that references an `Operator` compare the resource's foreign-key field (for example, `Station.station_owner_id`) to `X-User-ID`. A `StationOwner` may add piles, shelve and off-shelve them, edit pile metadata, and accept or reject repair tickets — but only at stations whose `station_owner_id` matches `X-User-ID`.
- `EVDriver` — end users. The role is entity-backed by `Member`: when `X-User-Role` is `EVDriver`, `X-User-ID` is the `id` of the acting `Member`. Ownership checks on any resource that references a `Member` (reservations, queue entries, sessions) compare the resource's foreign-key field to `X-User-ID`. Drivers reserve piles, join walk-up queues, abandon queues, create sessions, start charging, and stop charging.
- `FieldTechnician` — physical-repair staff. Identity is opaque: when `X-User-Role` is `FieldTechnician`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on `RepairTicket.assigned_technician_id` (set by the dispatching `PlatformOperator`) and on `AuditLog.actor_id`, and a technician may only begin or complete a ticket whose `assigned_technician_id` equals their own `X-User-ID`.
- `CustomerService` — support staff. Identity is opaque: when `X-User-Role` is `CustomerService`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it as `actor_id` on `AuditLog` rows for support actions but does not compare it to any entity's `id`. Support staff may abort a charging session, credit member wallets, stop a running session, and read sessions, members, fault reports, audit logs, and ledger entries.

The test-harness endpoints (`/_clock/advance`, `/_sweep/run`, `/_events/emit`) accept calls under the `PlatformOperator` role and are not subject to the priority-1 missing-header check applied to all other endpoints — they bypass it for test orchestration purposes.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100; values outside that range are rejected with `ERR_VALIDATION`. The `offset` defaults to 0 and must be non-negative. Results are returned sorted by the `created_at` timestamp in ascending order (oldest first) — entities whose schema lacks `created_at` are listed in chronological order of insertion, which is equivalent in practice. The response `meta` block includes `limit`, `offset`, `total_count` (the total matching the query before pagination), and `has_more` (true when `offset + limit < total_count`).

### 2.4. Common Resource Properties, Versioning, and Optimistic Concurrency

Most resources carry a common envelope of system-managed fields. The `id` is a server-minted UUID with no type prefix (no `pile_`/`res_`/`sess_` etc.). The `created_at` and `updated_at` timestamps are ISO 8601 UTC with three fractional digits; the `updated_at` is refreshed every time a mutation changes any field of the resource. The `version` is a non-negative integer that starts at 1 on creation and increments by exactly one on every mutation.

Five entities do **not** carry the full common envelope: `PricingVersion`, `PromoActivity`, `ChargingCurvePoint`, `SettlementLedgerEntry`, `AuditLog`, and `ExternalEventInbox` are append-only or immutable, and so carry only `id` and `created_at` — they have neither `updated_at` nor `version`. All other entities (`Operator`, `Station`, `Pile`, `Member`, `Reservation`, `QueueEntry`, `ChargingSession`, `FaultReport`, `RepairTicket`, `Payout`) carry the full envelope.

For optimistic concurrency on mutable resources, mutation endpoints (those whose payload accepts `version`) implement a check against the current persisted `version`: if the request body supplies a `version` value, the server compares it to the stored value and rejects the request with `ERR_VERSION_CONFLICT` on mismatch. If `version` is omitted from the request body, the check is skipped and the mutation proceeds against the latest stored state. On a successful mutation, the persisted `version` increments by one and `updated_at` is refreshed.

### 2.5. Path Hierarchy, Lookups, and Resource Existence

Nested URL paths are validated left-to-right. For an endpoint like `/stations/{id}/queue-entries`, the station identified by the path must exist before the queue-entry collection is consulted; if it does not, the response is `ERR_NOT_FOUND` regardless of any other condition. The same rule extends through pile, session, reservation, fault-report, repair-ticket, and payout segments. Body foreign keys (such as `pile_id`, `member_id`, `reservation_id`, `fault_report_id`, `operator_id`, `station_owner_id`, `home_operator_id`) are also resolved at creation time; a reference to a non-existent target yields `ERR_NOT_FOUND`.

Validations are evaluated in a strict priority order so that the most specific and most user-relevant rejection wins. Authentication (missing headers, then invalid headers, then forbidden role) is checked first. Resource existence (path identifiers, then body foreign keys) is checked next. State-machine preconditions are checked third (`ERR_INVALID_STATE`). Only after these three layers pass are domain-specific business rules — pile availability, reservation matching, reservation expiry, queue position, curve monotonicity, pricing-window overlap, time-of-use window overlap, off-shelve dependents, no-show threshold, wallet sufficiency, settlement over-allocation, payout window correctness, and payout-net positivity — evaluated. Within those business rules, each one applies only to the endpoints listed in its definition (see §3 for endpoint-specific rule prose); the same condition encountered on an endpoint not listed in its scope does not trigger that error.

### 2.6. Monetary, Energy, and Geographic Precision

All monetary values in the API are integer cents. There are no decimal currency fields; conversions from any computed quantity to cents always round half up. The settlement calculation produces `electricity_fee_cents`, `service_fee_cents`, `tax_cents`, and `total_cents` at 2 decimal places of precision (that is, integer cents — there is no sub-cent representation), and intermediate steps round half up at the points specified in the workflow narrative. Operator-settlement ledger amounts and payout amounts are likewise integer cents.

Energy is metered in milli-kWh — that is, one kilowatt-hour equals one thousand units in `cumulative_energy_milli`, `peak_kwh_milli`, `flat_kwh_milli`, and `valley_kwh_milli`. Conversions from milli-kWh to cents are performed in the settlement workflow by multiplying milli-units by a cents-per-kWh rate and dividing by one thousand, rounded half up.

Geographic coordinates use WGS84 decimal degrees. `latitude` is constrained to the closed interval from minus ninety to plus ninety, `longitude` to the closed interval from minus one hundred eighty to plus one hundred eighty, both with at most six fractional digits.

### 2.7. Audit Trail and Immutable Ledgers

Two write-once data structures form the trust spine of the platform. The `AuditLog` is appended to on every billing adjustment and every fault event, with each row recording `actor_role`, `actor_id`, `entity_kind`, `entity_id`, `event_kind` (one of `BILLING_ADJUSTMENT` or `FAULT_EVENT`), a `payload` capturing the before/after snapshot of relevant fields, and `occurred_at` as an ISO 8601 UTC timestamp. The `SettlementLedgerEntry` table is appended to on session settlement, no-show expiry, payout issuance, and refund reversal — each row captures `session_id`, `operator_id`, `counterparty_kind` (one of `STATION_OWNER_SHARE`, `PLATFORM_SERVICE_FEE`, `ROAMING_PARTNER`, `TAX_AUTHORITY`), a signed `amount_cents`, an associated `tax_cents`, and a `reason` (one of `SESSION_SETTLE`, `REFUND_REVERSAL`, `PAYOUT`, `NO_SHOW_PENALTY`). Both structures are append-only and carry no `version` or `updated_at`.

### 2.8. External Event Inbox and Test-Harness Endpoints

External systems — payment processors, mapping providers, and grid operators — communicate with the platform through a synchronous inbox. Each inbound event is captured as an `ExternalEventInbox` row carrying `source_system` (one of `PAYMENT`, `MAPPING`, `GRID`), `event_type` (e.g., `payment.refunded`, `mapping.location.synced`, `grid.pile_offline`, `grid.pile_online`, `grid.tariff.alert`), a `payload` object, a `received_at` timestamp, and `processed` flag (initially false, flipped to true once the dispatcher has applied any side-effects). The dispatcher runs inline with event submission.

For test orchestration, the platform exposes three administrative capabilities. A clock-advance capability steps the virtual clock forward by a supplied number of milliseconds (`advance_ms`) or to a supplied absolute instant (`to_iso`); it is idempotent on absolute time. A sweep capability runs the reservation-expiry pass, emitting no-show penalties and ledger entries for any reservation whose hold has elapsed. An event-emission capability injects an `ExternalEventInbox` row with caller-supplied `source_system`, `event_type`, and `payload`, and runs the dispatcher synchronously before returning. All three are accessible only to `PlatformOperator`.

## 3. Business Logic & Workflows

### 3.1. Operators, Stations, and the Pile Ledger

The system models commercial counterparties as `Operator` rows, each carrying a `name` (one to one hundred twenty characters, globally unique), a `role_kind` (one of `PLATFORM`, `STATION_OWNER`, `ROAMING_PARTNER`), and a `tax_id` (one to forty characters). Operators are created exclusively by `PlatformOperator` staff. The `Operator` entity also serves as the identity backing for the `StationOwner` role — when a station is created with a `station_owner_id`, that id is the `id` of the owning `Operator` row, and any `StationOwner` request whose `X-User-ID` matches a `station_owner_id` is authorized over that station.

A `Station` carries a display `name` (unique within `operator_id`, one to one hundred twenty characters), an `operator_id` (the running operator brand), a `station_owner_id` (the entity that owns the physical site, which may differ from `operator_id` when the station is sublet to another operator's network for roaming purposes), a `latitude` and `longitude`, a `revenue_share_bps` between zero and ten thousand basis points (the station owner's share of the net service fee on each session), and a `status` of either `ACTIVE` or `SUSPENDED` that defaults to `ACTIVE`. Stations are created by `PlatformOperator` or `StationOwner` actors.

Each `Pile` lives under a parent `Station` (referenced by `station_id`) and carries a manufacturer `model_code` (one to sixty-four characters), a `rated_power_kw` strictly greater than zero and at most three hundred sixty with at most one fractional digit, a `connector_type` (one of `GBT_DC`, `GBT_AC`, `CCS2`, `CHADEMO`), a `firmware_version` in MAJOR.MINOR.PATCH form with integer components, a `last_heartbeat_at` timestamp set by the system, and two orthogonal state dimensions: `lifecycle_state` and `operational_state`.

The `lifecycle_state` reflects shelf posture independent of any real-time activity and ranges over `OFF_SHELF`, `ON_SHELF`, and `DECOMMISSIONED`. New piles start `OFF_SHELF`. The shelving action, performed by a `StationOwner`, moves the pile from `OFF_SHELF` to `ON_SHELF` provided that the pile is currently `OFF_SHELF`, its `firmware_version` matches the MAJOR.MINOR.PATCH integer pattern, and the parent station's `status` is `ACTIVE` — the pile's `operational_state` is simultaneously set to `IDLE`. The off-shelving action returns the pile from `ON_SHELF` back to `OFF_SHELF` provided no charging session exists on this pile with status in `PENDING_AUTH`, `CHARGING`, or `SETTLING`, and no reservation on this pile is in status `HELD`; if either dependent exists, the request is rejected with `ERR_PILE_HAS_DEPENDENTS`. On successful off-shelving the `operational_state` is cleared to null. Decommissioning, performed by a `PlatformOperator`, is a one-way transition from `OFF_SHELF` to `DECOMMISSIONED`; the pile may not be in `ON_SHELF` at the moment of decommission, otherwise the request is rejected as an invalid state.

The `operational_state` is meaningful only while `lifecycle_state` is `ON_SHELF` and is otherwise null. It ranges over `IDLE`, `IN_USE`, `FAULT`, and `OFFLINE`. The system advances the pile from `IDLE` to `IN_USE` automatically when a session on the pile enters `CHARGING`, and returns it to `IDLE` whenever the owning session reaches a terminal state (`SETTLED` or `ABORTED`). A grid offline event sets the operational state to `OFFLINE` from any of `IDLE`, `IN_USE`, or `FAULT`; a grid online event returns it to `IDLE` from `OFFLINE`. Pile metadata (`model_code`, `firmware_version`, `rated_power_kw`) is updated by the `StationOwner` through the pile-edit capability and accepts an optional `version` for optimistic concurrency.

When listing piles, an additional ranking mode is available: callers may supply `available_for_member` (a member id) along with optional filters on `station_id`, `connector_type`, and `operational_state`, in which case the response is restricted to piles whose station has `status` `ACTIVE`, whose `lifecycle_state` is `ON_SHELF`, whose `operational_state` is `IDLE`, that have no `HELD` reservation, and whose station has zero `WAITING` queue entries (this last clause is the queue-jumping prevention rule — drivers cannot bypass a queue by querying availability and walking up to a different idle pile at a busy station). The list is ranked by the availability score described in §3.6, with ties broken by pile `id` ascending.

### 3.2. Members, Wallets, and Pricing Versions

A `Member` carries a `display_name` (one to eighty characters), a `home_operator_id` (the operator the member registered with — this is the field consulted to decide whether a session is roaming), a `tier` of `BASIC`, `SILVER`, `GOLD`, or `PLATINUM` defaulting to `BASIC`, a rolling `no_show_strikes` counter that the system maintains, and a `wallet_balance_cents` integer of prepaid funds that the system also maintains. Members are created by `PlatformOperator` or `CustomerService` staff. Wallet credits, applied through the wallet-credit capability by `PlatformOperator` or `CustomerService`, increase `wallet_balance_cents` by a supplied `amount_cents` and accept an optional `version` for concurrency.

Pricing is governed by immutable, append-only `PricingVersion` rows. Each version belongs to an `operator_id`, carries a human-readable `version_label` (unique within `operator_id`, one to forty characters), an inclusive `effective_from` and exclusive `effective_to` (the latter must be strictly greater than the former) defining a half-open time interval `[effective_from, effective_to)`. A version's electricity rates are `peak_rate_per_kwh_cents`, `flat_rate_per_kwh_cents`, and `valley_rate_per_kwh_cents`, all strictly positive integers in cents per kWh; the base service component is `service_fee_per_kwh_cents`, a non-negative integer in cents per kWh; and the applied tax rate is `tax_bps`, an integer in basis points between zero and five thousand inclusive (so up to fifty percent).

Peak and valley hours are expressed in the station's local time as half-open `{start_hhmm, end_hhmm}` intervals within a calendar day: `peak_windows` and `valley_windows` each contain between zero and six entries whose `start_hhmm` is strictly less than `end_hhmm`, with no overlap among the union of peak and valley entries. Any sample timestamp falling outside both window sets is treated as a flat-rate window. Per-tier service-fee discounts are configured in `tier_service_fee_discount_bps`, a map from each member tier to a basis-points discount value between zero and five thousand inclusive (e.g., `{BASIC:0, SILVER:500, GOLD:1000, PLATINUM:1500}`).

When a new pricing version is submitted, two checks govern its acceptance. First, the new interval must not overlap any other pricing version owned by the same operator on a half-open `[effective_from, effective_to)` basis — if any overlap exists the request is rejected with `ERR_PRICING_WINDOW_OVERLAP`; this is also the loser's identifier when two pricing-version inserts race for the same operator window. Second, the supplied peak and valley window arrays must not overlap each other — if they do, the request is rejected with `ERR_TOU_WINDOWS_OVERLAP`. Pricing versions are listed by `operator_id` and an optional `active_at` filter (returning only versions whose half-open interval contains that instant).

Promotional discounts are layered on top of pricing versions through `PromoActivity` rows, also immutable and operator-scoped via `operator_id`. Each promo has a `name` (one to eighty characters), inclusive `starts_at` and exclusive `ends_at` (with `ends_at` strictly greater than `starts_at`), a `service_fee_discount_bps` between zero and five thousand inclusive (applied on top of the member's tier discount), and an `applies_to_tiers` list — a non-empty subset of `{BASIC, SILVER, GOLD, PLATINUM}`. The same `active_at` filter applies on listing.

### 3.3. Reservations, Queues, and the Path to Charging

A driver who wants a guaranteed slot creates a `Reservation` against a `pile_id`. The system computes `hold_expires_at` as the reservation's `created_at` plus fifteen minutes, sets `status` to `HELD`, and primes `no_show_penalty_cents` at zero. A reservation may only be created when the pile is fit to serve — that is, the pile's `lifecycle_state` is `ON_SHELF` and `operational_state` is `IDLE`; if either is otherwise (`FAULT`, `OFFLINE`, or any non-`ON_SHELF` lifecycle), the request is rejected with `ERR_PILE_UNAVAILABLE`. Two drivers racing for the same pile see the second writer rejected with `ERR_PILE_ALREADY_RESERVED`; first-writer-wins serialization on `Reservation` row insertion guarantees that at most one reservation in `HELD` exists per pile at any time. A driver whose `no_show_strikes` has reached three or more is barred from reserving — the request is rejected with `ERR_NO_SHOW_THRESHOLD_EXCEEDED`. Drivers cancel a `HELD` reservation through the cancel action; this is the only path to `CANCELLED` that does not incur a strike. The cascade path to `CANCELLED` (driven by a pile fault, see §3.5) likewise does not increment strikes.

A `HELD` reservation transitions to `EXPIRED` automatically when the sweep capability is invoked at an instant where `now` is at or after `hold_expires_at`. The transition reads the member's `no_show_strikes` once **before** any mutation, applies the no-show penalty calculation described below, then increments `no_show_strikes` by one, sets `no_show_penalty_cents` on the reservation to the computed penalty, subtracts that penalty from `wallet_balance_cents` (clamped at zero — any deficit between the penalty and the wallet balance is recorded but does not drive the wallet negative), and appends a `SettlementLedgerEntry` with `counterparty_kind` `PLATFORM_SERVICE_FEE`, a positive `amount_cents` equal to the computed penalty, and `reason` `NO_SHOW_PENALTY`. The penalty magnitude is computed as follows: read the prior strikes count, multiply five hundred cents by two raised to the power of prior strikes, then cap the result at five thousand cents — the result is the penalty for this expiry. A driver expiring their first reservation (zero prior strikes) is therefore charged five hundred cents; a second expiry (one prior strike) is one thousand cents; a third (two prior strikes) is two thousand cents; a fourth and beyond saturate at the five-thousand-cent ceiling because doubling from two thousand would exceed it.

When a driver and the sweep both try to claim the same `HELD` reservation simultaneously — the driver trying to start the session and the sweep trying to expire it — exactly one wins: the loser sees `ERR_RESERVATION_EXPIRED`. Serialization is first-writer-wins on `Reservation.status`.

Walk-up traffic uses the station's queue. A `QueueEntry` is created against a `station_id` with `member_id` taken from `X-User-ID`; `enqueued_at` is set by the system as the ISO 8601 UTC instant of insertion, and `position` is assigned as one plus the maximum `position` of any `WAITING` entry at the station, or one if the queue is empty. The entry's initial `status` is `WAITING`. A driver who wants out of the queue invokes the abandon action: their entry moves to `ABANDONED` and every `WAITING` entry at the same station whose `position` is greater than the abandoning entry's `position` decrements by one. When a pile at the station becomes `IDLE` (because a session terminated, a fault was resolved, or the pile was just shelved), the system promotes the `WAITING` entry with the lowest `position`, ties broken by `enqueued_at` ascending and then by entry `id` ascending; the chosen entry moves to `PROMOTED` and every subsequent `WAITING` entry decrements by one. If two queue entries race to claim the same idle pile, the entry at position one (ties broken by `enqueued_at` and then `id`) wins; the loser remains `WAITING` and observes `ERR_QUEUE_NOT_AT_FRONT` if it tried to start a session.

### 3.4. Charging Sessions: Authentication, Metering, and Settlement

A `ChargingSession` is created in `PENDING_AUTH` state by an `EVDriver` against a target `pile_id`, with the driver's `member_id`, an `auth_method` (one of `APP`, `RFID`, `PLUG_AND_CHARGE`), and an optional `reservation_id` linking the session to a pre-existing hold. The session is brought to life by the start action, advancing it from `PENDING_AUTH` to `CHARGING`. Several preconditions guard the transition. The pile must be in `lifecycle_state` `ON_SHELF` and `operational_state` `IDLE`; if not, the request is rejected with `ERR_PILE_UNAVAILABLE` — safety takes precedence over any reservation hold, so a reservation that becomes invalid because the pile faulted between booking and arrival does not unlock charging. The driver's `wallet_balance_cents` must be at least one thousand cents (the minimum authentication hold); otherwise the start is rejected with `ERR_INSUFFICIENT_BALANCE`. If a `reservation_id` was supplied, the reservation must be in `HELD` status, `now` must be strictly less than its `hold_expires_at`, the reservation's `member_id` must match the session's `member_id`, and its `pile_id` must match the session's `pile_id` — a mismatch on member or pile yields `ERR_RESERVATION_MISMATCH`, and an expired hold yields `ERR_RESERVATION_EXPIRED`. If no `reservation_id` was supplied, either there must be no `WAITING` queue entry at the pile's station, or the driver must be the holder of the `WAITING` entry at `position` one — otherwise the start is rejected with `ERR_QUEUE_NOT_AT_FRONT`, the queue-jumping prevention guard.

On a successful start the system captures several derived fields. The session's `started_at` is set to `now`. The session's `pricing_version_id` is pinned to the operator's currently-effective `PricingVersion` at the start instant (this is the only point at which pricing is locked — every subsequent fee calculation for this session uses this snapshot). The session's `promo_activity_id` is set to an applicable promo at `now` (matching by `operator_id` and whose `applies_to_tiers` includes the member's `tier`), or remains null if none qualifies. The pile's `operational_state` is set to `IN_USE`. If the session was reservation-backed, the reservation transitions from `HELD` to `ACTIVATED` and is linked to the session. If the session was queue-led, the matching `QueueEntry` advances from `WAITING` to `PROMOTED` and subsequent waiting entries are re-ranked.

While the session is in `CHARGING`, the pile's telemetry stream appends `ChargingCurvePoint` rows tagged with a `window_tag` of `PEAK`, `FLAT`, or `VALLEY` computed against the pinned `pricing_version_id`'s window definitions. Each point carries `session_id`, `sampled_at` (strictly increasing per session), `instant_power_kw` (non-negative, at most two fractional digits), and `cumulative_energy_milli` (non-negative, monotonically non-decreasing per session). Any append violating monotonicity on `cumulative_energy_milli` or strict-increase on `sampled_at` is rejected with `ERR_CURVE_NON_MONOTONIC`. Abnormal events (such as over-temperature warnings or communication-loss markers) are appended to the session's `abnormal_events` array via the mark-abnormal capability, supplying an `event_type` (e.g., `OVER_TEMPERATURE`, `COMMUNICATION_LOSS`); each event is recorded with its timestamp.

A provisional settlement estimate is available while the session is `CHARGING`: it runs the same arithmetic described below against the curve points captured up to `now`, returning a snapshot of `electricity_fee_cents`, `service_fee_cents`, `tax_cents`, and `total_cents` without mutating any field.

The driver (or the platform) stops the session, advancing it from `CHARGING` to `SETTLING`. On the transition, the system captures `ended_at` as `now` and finalizes the per-window energy totals by walking the curve points: starting from zero, the cumulative-energy delta between consecutive samples (or from zero to the first sample) is attributed to the `window_tag` of the destination sample, accumulating into `peak_kwh_milli`, `flat_kwh_milli`, or `valley_kwh_milli`. Once at least one curve point with non-negative `cumulative_energy_milli` exists, the session automatically advances from `SETTLING` to `SETTLED`; the settlement workflow computes the four monetary fields, debits the wallet, and emits ledger rows as described in §3.6 below. Simultaneously, the pile returns from `IN_USE` to `IDLE`, and the queue-promotion check fires at the parent station.

A session in `CHARGING` may also enter the terminal `ABORTED` state in two ways. The first is automatic: when the pile this session is running on transitions to `FAULT` (because a fault report has been isolated against it), every `CHARGING` session on the pile is aborted, `ended_at` is set to `now`, an entry of type `COMMUNICATION_LOSS` is appended to `abnormal_events`, `electricity_fee_cents`, `service_fee_cents`, `tax_cents`, and `total_cents` remain at zero, an `AuditLog` row with `event_kind` `FAULT_EVENT` is appended, and the pile's subsequent `operational_state` is determined by the pile state machine (typically `FAULT`). The second is operator-driven: `CustomerService` may invoke an override abort, which produces the same effects — no fees, total of zero, an audit row — with the pile reverting per the pile machine. When a stop and an abort race on the same session, the loser sees `ERR_INVALID_SESSION_STATE`; serialization is first-writer-wins on `ChargingSession.status`.

### 3.5. Faults, Isolation, and the Repair Loop

A `FaultReport` against a pile is opened by an `EVDriver` (with `reporter_kind` `USER` and `reporter_member_id` populated with the driver's id), by a `FieldTechnician` or auto-detection system (with `reporter_kind` `AUTO_DETECT` and `reporter_member_id` null), or by a `PlatformOperator`. Each report captures the offending `pile_id`, a free-text `symptom_code` (one to forty characters), and a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`. The initial `status` is `OPEN`. Any fault report write — whether on creation or on a later isolation — appends an `AuditLog` row with `event_kind` `FAULT_EVENT`.

A `CRITICAL` fault auto-isolates on creation; otherwise, a `FieldTechnician` or `PlatformOperator` invokes the isolate capability to advance the report from `OPEN` to `ISOLATED`. The isolation cascade is the system's most consequential side-effect chain: the pile's `operational_state` moves to `FAULT` (the pile machine permits this from `IDLE`, `IN_USE`, and indirectly from `OFFLINE`); every `HELD` reservation on the pile is moved to `CANCELLED` (no strike — this is the compensating semantics distinguishing fault-driven cancellations from normal cancellations and from sweep-driven expiries); every `WAITING` queue entry at the station has its `position` re-ranked but the entries themselves are not removed; any in-flight session in `CHARGING` on this pile transitions to `ABORTED` with the consequences enumerated in §3.4; an `AuditLog` row with `event_kind` `FAULT_EVENT` is appended.

Repair is mediated by `RepairTicket` rows linked to a fault via `fault_report_id`. The repair ticket carries an `assigned_technician_id` (set by the dispatching `PlatformOperator`), a `dispatched_at` timestamp captured by the system at dispatch, free-text `repair_notes` (zero to one thousand characters) recorded on completion, and a `status` whose enumerated values are `OPEN`, `DISPATCHED`, `IN_REPAIR`, `AWAITING_ACCEPTANCE`, `CLOSED`, and `REJECTED`. The normal walk is `OPEN → DISPATCHED → IN_REPAIR → AWAITING_ACCEPTANCE → CLOSED`, with a possible cycle back from `AWAITING_ACCEPTANCE` to `IN_REPAIR` on rejection; `REJECTED` is reserved as a terminal label and is not produced by any transition the API exposes. A ticket is opened in `OPEN` by a `PlatformOperator`. Dispatch by a `PlatformOperator` moves the ticket to `DISPATCHED` and sets `dispatched_at` to `now`; if the parent fault was still `OPEN`, dispatch cascades it to `ISOLATED` (triggering the pile cascade above). Begin, invoked by a `FieldTechnician`, moves the ticket from `DISPATCHED` to `IN_REPAIR` provided `assigned_technician_id` matches `X-User-ID`. Complete, invoked by the same technician, moves it from `IN_REPAIR` to `AWAITING_ACCEPTANCE` and records the supplied `repair_notes`. Acceptance by a `StationOwner` (whose `X-User-ID` matches the parent station's `station_owner_id`) moves the ticket from `AWAITING_ACCEPTANCE` to `CLOSED`, which cascades the parent fault report from `ISOLATED` to `RESOLVED`, which in turn moves the pile's `operational_state` from `FAULT` back to `IDLE` and fires the queue-promotion check at the station. Rejection by the same `StationOwner` moves the ticket back from `AWAITING_ACCEPTANCE` to `IN_REPAIR`, cycling the work item for the technician.

### 3.6. Settlement Calculation, Roaming, and Operator Allocation

When a session enters `SETTLED`, the platform computes four monetary fields and writes the corresponding ledger rows. Throughout, the pinned `pricing_version_id` (here denoted as `pv`) and pinned `promo_activity_id` (here denoted as `promo`) are the sole pricing inputs — no live pricing or promo lookup is performed at settlement time.

**Step A — derive per-window energy.** Walk the session's `ChargingCurvePoint` rows in `sampled_at` order. For each point, the cumulative-energy delta between this sample and the previous one (or between zero and the first sample) is attributed to the `window_tag` of the destination sample, accumulating into three running totals in milli-kWh: `peak_milli`, `flat_milli`, and `valley_milli`. Their sum is `total_milli`. These totals also populate `peak_kwh_milli`, `flat_kwh_milli`, and `valley_kwh_milli` on the session.

**Step B — compute electricity fee, rounding per window before summing.** For each of the three windows independently, multiply the window's milli-kWh by its rate from `pv` (`peak_rate_per_kwh_cents`, `flat_rate_per_kwh_cents`, or `valley_rate_per_kwh_cents`), divide by one thousand, and round half up to an integer cents value. Sum the three per-window cents totals to obtain `electricity_fee_cents`. The rounding order is pinned at the per-window level — rounding once on the summed milli-kWh is not equivalent and is not permitted.

**Step C — compute service fee with stacked discounts.** Take the member's tier discount in basis points from `pv.tier_service_fee_discount_bps[member.tier]` — call this the tier discount. If a `promo_activity_id` is pinned on the session and the member's `tier` is in the promo's `applies_to_tiers`, take the promo's `service_fee_discount_bps` as the promo discount; otherwise the promo discount is zero. Compute a base service amount by multiplying `total_milli` by `pv.service_fee_per_kwh_cents`, dividing by one thousand, and rounding half up — this is the base service cents. The two discounts stack multiplicatively rather than additively: form an effective factor equal to ten thousand minus the tier discount, multiplied by ten thousand minus the promo discount (so the factor is a product of basis-point complements, with units of basis-points squared). Multiply the base service cents by this effective factor, divide by one hundred million (because the factor is in basis-points squared and we need a fractional retention), and round half up to obtain `service_fee_cents`.

**Step D — compute tax and total.** Add `electricity_fee_cents` and `service_fee_cents`, multiply by `pv.tax_bps`, divide by ten thousand, and round half up; the result is `tax_cents`. The session's `total_cents` is the sum of `electricity_fee_cents`, `service_fee_cents`, and `tax_cents`. After the four monetary fields are written, the member's `wallet_balance_cents` is decremented by `total_cents`.

The same monetary inputs drive **operator settlement** — the allocation of the net (excluding tax) across station owner, platform, optional roaming partner, and tax authority — using a fixed waterfall:

1. Compute `net_cents` as `electricity_fee_cents` plus `service_fee_cents` (tax is routed separately).
2. Determine whether the session is roaming: it is roaming when the member's `home_operator_id` is not equal to the station's `operator_id`. If roaming, the roaming partner's allocation is `net_cents` multiplied by fifteen hundred basis points (fifteen percent), divided by ten thousand, rounded half up. Otherwise the roaming allocation is zero.
3. Subtract the roaming allocation from `net_cents` to obtain the post-roaming remainder. The platform's allocation is that remainder multiplied by five hundred basis points (five percent), divided by ten thousand, rounded half up.
4. Subtract the platform allocation from the post-roaming remainder to obtain the post-platform amount. The station owner's allocation is that post-platform amount multiplied by `station.revenue_share_bps`, divided by ten thousand, rounded half up.
5. The operator residual is the post-platform amount minus the station-owner allocation.
6. The full `tax_cents` is routed to the `TAX_AUTHORITY`.

A safety guard fires before this allocation: the sum of `station.revenue_share_bps`, the platform's five-hundred-basis-point base fee, and (when roaming applies) the fifteen-hundred-basis-point roaming share must not exceed ten thousand basis points (one hundred percent). If it would, settlement is rejected with `ERR_SETTLEMENT_OVER_ALLOCATION`.

On a successful settlement, four `SettlementLedgerEntry` rows are appended, each with `reason` `SESSION_SETTLE` and positive `amount_cents`: one with `counterparty_kind` `STATION_OWNER_SHARE` for the station-owner allocation, one with `PLATFORM_SERVICE_FEE` for the platform allocation, one with `ROAMING_PARTNER` for the roaming allocation (only if non-zero), and one with `TAX_AUTHORITY` carrying the tax amount; the `tax_cents` column on the appropriate row mirrors the session tax for traceability.

The same allocation is invoked again whenever a refund event arrives — and this is the **only** point at which reversal rows are produced. The reversal is recomputed from scratch using the current values of `station.revenue_share_bps`, the platform base fee, and the roaming share (not stored deltas from the original settlement); each of the four ledger rows is then written with `amount_cents` of the opposite sign and `reason` `REFUND_REVERSAL`. The invariant that ties original and reversal together is that for each `counterparty_kind`, the sum of original plus reversal `amount_cents` on the session is exactly zero — the compensating-invariant condition. The session's `total_cents` is adjusted accordingly and an `AuditLog` row with `event_kind` `BILLING_ADJUSTMENT` is appended.

The pile-availability ranking used by the pile listing when `available_for_member` is supplied (see §3.1) is computed as follows. After the filtering rules in §3.1 select eligible piles, each candidate is scored as five times the pile's `rated_power_kw` plus twenty-five times the member's tier rank (with `BASIC` = 0, `SILVER` = 1, `GOLD` = 2, `PLATINUM` = 3) minus one hundred times the haversine distance in kilometers between the member's last known location and the station's location (derived from `latitude` and `longitude`). The result is an integer score; the response is sorted by score in descending order, with ties broken by pile `id` ascending.

### 3.7. Payouts, Reversals, and Periodic Settlement

A `Payout` represents a periodic settlement to an operator over a half-open time window. A `PlatformOperator` creates a payout draft against a target `operator_id`, an inclusive `period_start`, and an exclusive `period_end` strictly greater than `period_start` (otherwise the creation is rejected with `ERR_INVALID_PAYOUT_WINDOW`). On creation, the system computes three monetary totals from the operator's `SettlementLedgerEntry` rows whose source session's `ended_at` falls within `[period_start, period_end)`. The `gross_cents` is the sum of positive `amount_cents` for the operator across the window. The `reversal_cents` is the sum of absolute values of negative `amount_cents` whose `reason` is `REFUND_REVERSAL` for the operator across the window. The `net_cents` is `gross_cents` minus `reversal_cents`. The initial `status` is `PENDING`.

The payout is issued by a `PlatformOperator` invoking the issue capability. The transition from `PENDING` to `ISSUED` requires `net_cents` to be at least zero; if refunds have pushed it negative by issue time, the request is rejected with `ERR_PAYOUT_NEGATIVE_NET`. On a successful issue, a single `SettlementLedgerEntry` is appended with `reason` `PAYOUT` and an `amount_cents` of the negated `net_cents` value (the payout debit), with `counterparty_kind` selected by the recipient operator's role.

After issuance, a payout may still be reversed. When an external refund event arrives that references a `SettlementLedgerEntry` whose source session's `ended_at` is inside `[period_start, period_end)` of an already-`ISSUED` payout, the payout transitions to `REVERSED`, the refund flow writes the per-counterparty `REFUND_REVERSAL` rows described in §3.6, and an `AuditLog` row with `event_kind` `BILLING_ADJUSTMENT` is appended. If the same refund arrives while the payout is still `PENDING`, the payout's `net_cents` is recomputed by the dispatcher and the subsequent issue attempt is rejected with `ERR_PAYOUT_PERIOD_DRIFT`; the loser between simultaneous refund-dispatch and issue is the issue attempt, with the same identifier. Serialization across these cases is first-writer-wins on `Payout.status`.

### 3.8. External Event Synchronization

The external event inbox accepts three external `source_system` values, each handled by the dispatcher inline with submission. A `PAYMENT` event with `event_type` `payment.refunded` carrying a `payload` that references a session triggers the refund-reversal pathway described in §3.6 and §3.7. A `GRID` event with `event_type` `grid.pile_offline` or `grid.pile_online` moves the referenced pile's `operational_state` to `OFFLINE` or back to `IDLE`, respectively, provided its `lifecycle_state` is `ON_SHELF`. A `MAPPING` event with `event_type` such as `mapping.location.synced` updates the referenced station's coordinates. Each event row carries `source_system`, `event_type`, `payload`, `received_at`, and `processed`; the dispatcher flips `processed` to true after side-effects are applied.

The clock-advance capability accepts either `advance_ms` (a relative step) or `to_iso` (an absolute target) and returns the new logical `now`. The sweep capability examines every `HELD` reservation and, for any whose `hold_expires_at` is at or before the logical `now`, runs the expiry transition described in §3.3, returning the list of expired reservation ids. The event-emit capability injects an `ExternalEventInbox` row with caller-supplied fields and runs the dispatcher synchronously.

## 4. Endpoint Definitions

A new resource creation (the workflows that produce a fresh row — operators, stations, piles, members, pricing versions, promo activities, reservations, queue entries, sessions, curve points, fault reports, repair tickets, payouts) returns HTTP 201. All other endpoints — state transitions, mutations, list and detail reads, test-harness invocations — return HTTP 200 on success. Error semantics follow §5.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/operators` | Create an operator | `PlatformOperator` |
| GET | `/operators` | List operators | `PlatformOperator`, `StationOwner`, `CustomerService` |
| GET | `/operators/{id}` | Get operator | `PlatformOperator`, `StationOwner`, `CustomerService` |
| POST | `/stations` | Create a station | `PlatformOperator`, `StationOwner` |
| GET | `/stations` | List stations | `PlatformOperator`, `StationOwner`, `EVDriver`, `FieldTechnician`, `CustomerService` |
| GET | `/stations/{id}` | Get station detail | `PlatformOperator`, `StationOwner`, `EVDriver`, `FieldTechnician`, `CustomerService` |
| POST | `/stations/{id}/piles` | Add a pile to a station (initial lifecycle is off-shelf) | `StationOwner` |
| POST | `/piles/{id}/shelve` | Move pile lifecycle from off-shelf to on-shelf | `StationOwner` |
| POST | `/piles/{id}/off-shelve` | Move pile lifecycle from on-shelf back to off-shelf | `StationOwner` |
| POST | `/piles/{id}/decommission` | Permanently retire a pile | `PlatformOperator` |
| PATCH | `/piles/{id}` | Update pile metadata | `StationOwner` |
| GET | `/piles` | List piles; supports availability-scored listing | `PlatformOperator`, `StationOwner`, `EVDriver`, `FieldTechnician`, `CustomerService` |
| GET | `/piles/{id}` | Get pile detail | `PlatformOperator`, `StationOwner`, `EVDriver`, `FieldTechnician`, `CustomerService` |
| POST | `/members` | Create a member | `PlatformOperator`, `CustomerService` |
| GET | `/members/{id}` | Get member detail | `PlatformOperator`, `CustomerService`, `EVDriver` |
| POST | `/members/{id}/wallet-credit` | Credit member wallet | `PlatformOperator`, `CustomerService` |
| POST | `/pricing-versions` | Create a pricing version | `PlatformOperator` |
| GET | `/pricing-versions` | List pricing versions | `PlatformOperator`, `StationOwner`, `CustomerService` |
| POST | `/promo-activities` | Create a promo activity | `PlatformOperator` |
| GET | `/promo-activities` | List promo activities | `PlatformOperator`, `StationOwner`, `EVDriver` |
| POST | `/reservations` | Create a reservation (fifteen-minute hold) | `EVDriver` |
| POST | `/reservations/{id}/cancel` | Cancel a held reservation | `EVDriver` |
| GET | `/reservations/{id}` | Get a reservation | `EVDriver`, `PlatformOperator`, `CustomerService` |
| POST | `/stations/{id}/queue-entries` | Join the walk-up queue at a station | `EVDriver` |
| POST | `/queue-entries/{id}/abandon` | Leave the queue | `EVDriver` |
| GET | `/stations/{id}/queue-entries` | List queue entries at a station | `EVDriver`, `StationOwner`, `PlatformOperator`, `CustomerService` |
| POST | `/sessions` | Create a charging session (pending authentication) | `EVDriver` |
| POST | `/sessions/{id}/start` | Start charging | `EVDriver` |
| POST | `/sessions/{id}/curve-points` | Append a curve sample | `PlatformOperator`, `FieldTechnician` |
| POST | `/sessions/{id}/mark-abnormal` | Mark an abnormal event on the session | `PlatformOperator`, `FieldTechnician` |
| POST | `/sessions/{id}/stop` | Stop a charging session and settle | `EVDriver`, `PlatformOperator` |
| POST | `/sessions/{id}/abort` | Abort a charging session | `CustomerService` |
| GET | `/sessions/{id}` | Get session detail | `EVDriver`, `PlatformOperator`, `CustomerService`, `StationOwner` |
| GET | `/sessions/{id}/estimate` | Provisional settlement estimate while charging | `EVDriver`, `PlatformOperator`, `CustomerService` |
| GET | `/sessions/{id}/curve-points` | List curve points for a session | `EVDriver`, `PlatformOperator`, `FieldTechnician`, `CustomerService` |
| POST | `/fault-reports` | Report a fault on a pile | `EVDriver`, `FieldTechnician`, `PlatformOperator` |
| POST | `/fault-reports/{id}/isolate` | Manually isolate a fault | `FieldTechnician`, `PlatformOperator` |
| GET | `/fault-reports/{id}` | Get a fault report | `FieldTechnician`, `PlatformOperator`, `StationOwner`, `CustomerService` |
| POST | `/fault-reports/{id}/repair-tickets` | Open a repair ticket | `PlatformOperator` |
| POST | `/repair-tickets/{id}/dispatch` | Dispatch a repair ticket | `PlatformOperator` |
| POST | `/repair-tickets/{id}/begin` | Technician begins repair | `FieldTechnician` |
| POST | `/repair-tickets/{id}/complete` | Mark repair complete | `FieldTechnician` |
| POST | `/repair-tickets/{id}/accept` | Station owner accepts repair | `StationOwner` |
| POST | `/repair-tickets/{id}/reject` | Station owner rejects repair | `StationOwner` |
| GET | `/sessions/{id}/ledger-entries` | List ledger entries for a session | `PlatformOperator`, `StationOwner`, `CustomerService` |
| POST | `/payouts` | Create a payout draft | `PlatformOperator` |
| POST | `/payouts/{id}/issue` | Issue a pending payout | `PlatformOperator` |
| GET | `/payouts/{id}` | Get a payout | `PlatformOperator`, `StationOwner` |
| GET | `/payouts` | List payouts | `PlatformOperator`, `StationOwner` |
| GET | `/audit-logs` | List audit log entries | `PlatformOperator`, `CustomerService` |
| POST | `/_clock/advance` | Advance the virtual clock (test only) | `PlatformOperator` |
| POST | `/_sweep/run` | Run the reservation-expiry sweep (test only) | `PlatformOperator` |
| POST | `/_events/emit` | Emit an external event (test only) | `PlatformOperator` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|-------------------|
| `ERR_AUTH_MISSING` | 401 |
| `ERR_AUTH_INVALID` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_SESSION_STATE` | 409 |
| `ERR_PILE_UNAVAILABLE` | 409 |
| `ERR_PILE_HAS_DEPENDENTS` | 409 |
| `ERR_PILE_ALREADY_RESERVED` | 409 |
| `ERR_RESERVATION_EXPIRED` | 409 |
| `ERR_RESERVATION_MISMATCH` | 422 |
| `ERR_QUEUE_NOT_AT_FRONT` | 409 |
| `ERR_CURVE_NON_MONOTONIC` | 422 |
| `ERR_PRICING_WINDOW_OVERLAP` | 409 |
| `ERR_TOU_WINDOWS_OVERLAP` | 422 |
| `ERR_NO_SHOW_THRESHOLD_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_BALANCE` | 402 |
| `ERR_SETTLEMENT_OVER_ALLOCATION` | 422 |
| `ERR_INVALID_PAYOUT_WINDOW` | 422 |
| `ERR_PAYOUT_NEGATIVE_NET` | 409 |
| `ERR_PAYOUT_PERIOD_DRIFT` | 409 |
| `ERR_VALIDATION` | 422 |
