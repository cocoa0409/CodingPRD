# Smart Parking Lot API — Product Requirements Document

## 1. Introduction

This document specifies the Smart Parking Lot API, a backend platform that unifies real-time space inventory, gate-driven session lifecycle, prepaid and monthly card management, reservations, enforcement of illegal parking, and revenue settlement under a single coherent contract. Modern parking operators run multi-zone facilities where sensor-driven occupancy, license-plate recognition, and reservation overlays must agree second-by-second; where billing must respect free grace periods, daily caps, monthly coverage, and statutory exemptions for emergency and disabled vehicles; and where every fee, fine, refund, and adjustment must reach a partner-share-aware revenue ledger without drift.

The system serves five distinct human and machine actors — lot operators, drivers, gate systems, enforcement officers, revenue-share partners, and auditors — each with restricted views into the same underlying state. Its central design tension is to keep instantaneous space availability and chargeable session cost truthful at all times, even while drivers, gates, and enforcement events may collide concurrently on the same Space, Session, or Card. The API surface is mounted under `/lots` and related sibling roots (`/vehicles`, `/cards`, `/sessions`, `/reservations`, `/violations`, `/payments`, `/audit-logs`, plus operational test-driving endpoints).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and contracts that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every API call (except `/healthz`) must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring its operational capacity. Missing or empty values yield `ERR_MISSING_AUTH`. Once authenticated, the role is matched against a role-based access matrix; a mismatch yields `ERR_FORBIDDEN`.

Six roles are recognized, spelled exactly as follows: `Operator`, `Driver`, `GateSystem`, `EnforcementOfficer`, `ParkingPartner`, and `Auditor`. The `Operator` is a lot operator who manages lots, zones, spaces, cards, settlements, and waivers. The `Driver` is a vehicle owner or customer initiating reservations and payments. The `GateSystem` is the automated gate or LPR camera that opens and closes sessions. The `EnforcementOfficer` patrols the lot and issues violations. The `ParkingPartner` has read-only access to revenue and settlements as a revenue-share counterparty. The `Auditor` has read-only access across all entities and may run sweeps and clock-advances for audit purposes.

When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Vehicle`; ownership checks on any resource that references a `Vehicle` (sessions, reservations, violations, cards bound to that vehicle) compare the resource's `vehicle_id` to `X-User-ID`. When `X-User-Role` is `Operator`, `GateSystem`, `EnforcementOfficer`, `ParkingPartner`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it on `AuditLog.actor_id` (and `AuditLog.actor_role`) when an audit-bearing action runs, but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter caps the page size and defaults to 10 when omitted; permitted values are integers from 1 to 100 inclusive. The `offset` parameter defaults to 0 and must be a non-negative integer. Any value outside these bounds is rejected with `ERR_BAD_REQUEST`.

Unless an endpoint explicitly states otherwise, list responses are sorted by `created_at` in ascending order. The `meta` object on list responses always carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every resource is uniquely identified by an `id` field, which is a server-minted UUID. The `id` does not embed any type prefix and is opaque to clients.

Most entities — `ParkingLot`, `Zone`, `Space`, `Vehicle`, `Card`, `Session`, `Reservation`, `Violation` — additionally carry `created_at` (ISO 8601 UTC with three fractional digits, set at creation), `updated_at` (same format, refreshed on every mutation), and a monotonically increasing integer `version` (starting at 1, incremented by exactly one on every mutation that persists a change to the resource).

Append-only journal-style records — `Fine`, `Payment`, `RevenueEntry`, and `AuditLog` — are immutable once written. They carry only `id` and `created_at`; both `updated_at` and `version` are absent on these resources, and any client attempt to mutate them is rejected with `ERR_INVALID_STATE`.

### 2.5. Optimistic Concurrency Control

Mutations on versioned resources may include the resource's current `version` either in the request body or via an `If-Match` header. When supplied, the server compares the supplied value against the live `version` of the target resource: a match permits the operation to proceed and increments `version` by one as part of the mutation; a mismatch rejects the request with `ERR_VERSION_CONFLICT` (HTTP 409). When the client omits the version from both body and header, the optimistic-concurrency check is skipped — the operation runs against whatever version is current — and any other applicable validations still apply.

Race scenarios serialize on the underlying entity. When a recharge and an auto-pay debit on the same `Card` collide, the second writer to arrive with a stale `version` is rejected with `ERR_VERSION_CONFLICT`. When two operators attempt to bind the same `Vehicle` to two different `MONTHLY` cards simultaneously, exactly one binding edge is admitted and the loser is rejected with `ERR_VEHICLE_ALREADY_BOUND`. When a `Driver` initiates a session payment while an `Operator` waives the same session at the same instant, exactly one payment-status transition wins and the loser is rejected with `ERR_INVALID_STATE`. When two reservations target the same `Space` over overlapping windows, exactly one is admitted as `HELD` and the loser is rejected with `ERR_RESERVATION_OVERLAP`. When two drivers simultaneously gate-in to the same `FREE` space, the first writer to assign `Space.current_session_id` wins and the loser is rejected with `ERR_SPACE_OCCUPIED`. Idempotency keys carried via `external_ref` on `Payment` writes are unique once present; a duplicate yields `ERR_DUPLICATE_EXTERNAL_REF`.

### 2.6. Nested Resource Retrieval and Path Validation

Many resources sit in a `/lots/{lot_id}/zones/{zone_id}/spaces/{space_id}` hierarchy. When a request path contains multiple identifiers, the server validates them strictly left-to-right: it confirms the lot exists, then the zone exists and belongs to that lot, then the space exists and belongs to that zone. The first identifier that fails to resolve causes the request to fail with `ERR_NOT_FOUND` before any downstream validation runs. Foreign-key identifiers carried inside the request body (such as `card_id`, `vehicle_id`, `reservation_id`, `space_id`, `lot_id`, `zone_id`, `target_card_id`, `subject_id`, `session_id`, or the `subject_id`/`subject_kind` filter on audit queries) are likewise resolved after path validation; an unresolvable body reference yields `ERR_NOT_FOUND` as well.

### 2.7. Validation Priority Ordering

When multiple checks apply to a single request, the server evaluates them in a fixed priority order so that the most fundamental failures surface first and are not masked by downstream checks. Authentication (presence of `X-User-Role` and `X-User-ID`, yielding `ERR_MISSING_AUTH` on failure) holds the highest priority, followed by role authorization (yielding `ERR_FORBIDDEN`), then path-parameter existence resolved left-to-right (yielding `ERR_NOT_FOUND`), then existence of body foreign keys (yielding `ERR_NOT_FOUND`), then optimistic-concurrency on `PATCH` and `PUT` requests (yielding `ERR_VERSION_CONFLICT`), then state-machine eligibility for the requested transition (yielding `ERR_INVALID_STATE`).

After these structural checks, business rules apply in this order: vehicle exemption (`ERR_EXEMPT_VEHICLE`) before binding eligibility (`ERR_VEHICLE_HAS_OPEN_VIOLATIONS`); reservation interval-overlap (`ERR_RESERVATION_OVERLAP`) before space-bookability inside the tow-grace window (`ERR_SPACE_NOT_BOOKABLE`); then card binding cardinality (`ERR_CARD_BINDING_LIMIT`), card validity (`ERR_CARD_EXPIRED`), and card-transfer compatibility (`ERR_INVALID_CARD_TRANSFER`). Photo-evidence enforcement on violations (`ERR_PHOTO_REQUIRED`) precedes reservation-window validity (`ERR_INVALID_RESERVATION_WINDOW`), which precedes funds checks on stored-value debits (`ERR_INSUFFICIENT_BALANCE`), which precedes refund-window expiry (`ERR_REFUND_WINDOW_EXPIRED`), which precedes mandatory-reason enforcement on audit-bearing actions (`ERR_REASON_REQUIRED`). Pagination-bounds rejections and license-plate-format rejections share `ERR_BAD_REQUEST` and apply at the structural-input layer.

### 2.8. Hierarchical Consistency and Cascading Updates

A successful gate-in atomically transitions `Space.occupancy_status` from `FREE` to `OCCUPIED`, sets `Space.current_session_id` to the new session, decrements `Zone.free_spaces` by one, and — if the entry matches a `HELD` reservation for the same vehicle within the matching window — transitions `Reservation.status` from `HELD` to `MATCHED`, sets `Reservation.matched_session_id`, and clears `Space.reservation_lock` to `UNRESERVED`. Each affected resource has its `updated_at` refreshed and its `version` incremented; the cached `Zone.free_spaces` and `Zone.total_spaces` are themselves stored fields that the system keeps consistent across child mutations.

A successful gate-out atomically transitions `Session.occupancy_status` from `ACTIVE` to `EXITED`, pins `Session.exit_at` to the current instant, pins `Session.final_fee_cents` (and `Session.billing_kind`) using the final-settlement variant of session billing, transitions the holding `Space.occupancy_status` from `OCCUPIED` to `FREE`, sets `Space.last_exited_at` to the same exit instant, and clears `Space.current_session_id`. The cached `Zone.free_spaces` is incremented by one only when `Space.reservation_lock` is `UNRESERVED` at exit time. If the session was pinned to a card with `auto_pay_enabled` set to true, the system cascades a settlement that creates a `SESSION_FEE` `Payment`, debits a `STORED_VALUE` card by `Session.final_fee_cents`, transitions `Session.payment_status` from `UNPAID` to `PAID`, and emits a corresponding revenue entry.

Creating a `HIGH`-severity event such as a tow advances violations and may cascade onto sessions: when a violation is towed and a linked session is still `ACTIVE`, the tow forces `Session.occupancy_status` from `ACTIVE` to `EXITED`, pins `Session.final_fee_cents`, transitions the holding `Space.occupancy_status` from `OCCUPIED` to `FREE`, and writes an `AuditLog` row with `action` `BILLING_ADJUSTMENT`. When a violation is paid and a linked session is in `DISPUTED` payment status, the session payment cascades from `DISPUTED` back to `UNPAID`. Every cascade refreshes the affected resources' `updated_at` and increments their `version`.

### 2.9. Precision, Currency, and Time

All monetary fields are integer cents; the API never returns or accepts fractional cents. Where multiplication by a decimal multiplier is required (notably the violation-type multiplier in fine computation and the partner-share basis-points multiplier in revenue allocation), the multiplication is performed in arbitrary-precision decimal and rounded half-up to the nearest integer cent at the step indicated; integer surcharges are then added without further rounding. Where division by an integer is required (for example halving the no-show penalty), the result is rounded half-up to the nearest integer cent.

Hourly billing counts started hours: any partial hour is rounded up to the next whole hour. The daily-cap floor is enforced per calendar day in `ParkingLot.timezone`, taking the minimum of the raw hourly product and `ParkingLot.daily_cap_cents` for each day before summing across days. All timestamps in request bodies and response payloads are ISO 8601 UTC with three fractional digits.

### 2.10. Vehicle Exemption and Special Vehicles

A `Vehicle` whose `kind` is `EMERGENCY` or `DISABLED` is exempt from billing on every session it parks (its `Session.billing_kind` is pinned as `EXEMPT_VEHICLE` and `Session.final_fee_cents` is zero) and is exempt from `OVERSTAY` and `NON_PAYING` violation issuance. An attempt to charge such a vehicle for a session fee, or to issue an `OVERSTAY` or `NON_PAYING` violation against it, is rejected with `ERR_EXEMPT_VEHICLE`. `BLOCKING` and `WRONG_ZONE` violations remain enforceable against exempt vehicles on the same terms as any other vehicle.

### 2.11. Audit Logging and Mandatory Reasons

Audit-bearing actions — billing adjustments (waivers, refunds, tows, dispute moves), reservation changes (window or vehicle edits), fine waivers, and card transfers — must include a non-empty `reason` field in the request body. A missing or empty `reason` on any such action is rejected with `ERR_REASON_REQUIRED`. When the action proceeds, the server appends an `AuditLog` row whose `action` is one of `BILLING_ADJUSTMENT`, `RESERVATION_CHANGE`, `FINE_WAIVE`, or `CARD_TRANSFER`, capturing `actor_role`, `actor_id`, `subject_kind`, `subject_id`, the `before` snapshot of mutated fields, the `after` snapshot, and the supplied `reason`.

## 3. Business Logic & Workflows

### 3.1. Lot, Zone, and Space Inventory

A lot is materialized when an `Operator` creates it, supplying its display `name`, the IANA `timezone` whose calendar days bracket the daily-cap window, the base `hourly_rate_cents` charged per started hour after the free period, the per-calendar-day ceiling `daily_cap_cents`, and four optional pricing knobs that default if omitted: `free_minutes` (the grace period in minutes from entry, default 15), `tow_grace_minutes` (the buffer in minutes after a session exit before the same space becomes re-bookable, default 5), `reservation_hold_minutes` (the hold expiry duration in minutes after the requested start time before a no-show is realized, default 15), `no_show_penalty_cents` (the penalty applied to the payer of an unmatched reservation, default 500 cents), and `partner_share_bps` (the partner's revenue share in basis points, default 0 — for example, 2000 means 20.00%).

Within a lot, an `Operator` defines zones each carrying a short `code` unique within its parent lot (e.g. `A`, `B-VIP`) and a `zone_type` drawn from `STANDARD`, `VIP`, `DISABLED`, or `EMERGENCY`. The `zone_type` drives downstream eligibility: emergency and disabled vehicles can park in any zone but the type signals exemption-zone reservations.

Within a zone, an `Operator` provisions individual spaces by supplying a `label` unique within the zone (e.g. `A-12`). Each `Space` carries two parallel state dimensions. The `occupancy_status` dimension tracks physical occupancy and toggles between `FREE` and `OCCUPIED` driven by gate events. The `reservation_lock` dimension tracks reservation overlay and toggles between `UNRESERVED` and `RESERVED` driven by reservation lifecycle. Both states default to `FREE` and `UNRESERVED` at creation. The space additionally carries `current_session_id` (the `id` of the active session occupying it, or null when free), `last_exited_at` (the timestamp of the most recent session exit, used to enforce `tow_grace_minutes`), and a denormalized `lot_id` for fast filtering.

Every zone caches `total_spaces` and `free_spaces`. The `total_spaces` count tracks child spaces and is updated on space create or delete. The `free_spaces` count tracks how many child spaces simultaneously have `occupancy_status` equal to `FREE` and `reservation_lock` equal to `UNRESERVED`. A real-time availability lookup over a lot returns these counts per zone, with an optional `zone_type` query filter to narrow the result.

Adding a new space increments the parent zone's `total_spaces` and `free_spaces` each by one; the zone's `updated_at` and `version` are bumped. Reading an individual space exposes its current `occupancy_status`, `reservation_lock`, and `current_session_id` so that gate operators and drivers can resolve a parking decision in real time.

### 3.2. Vehicles and Plate Registration

A vehicle is registered when a `GateSystem` or `Operator` posts a `plate` along with an optional `kind` defaulting to `REGULAR`. The system normalizes the supplied plate to uppercase with all whitespace stripped, then validates the result against the regular expression for license plates: a non-empty string of length 1 to 12 inclusive, drawn only from uppercase ASCII letters, digits, and the hyphen character. A plate that fails the regex is rejected with `ERR_BAD_REQUEST`; a normalized plate already present on another `Vehicle` is also rejected with `ERR_BAD_REQUEST` (the global uniqueness invariant on plates).

The `kind` is one of `REGULAR`, `EMERGENCY`, or `DISABLED`. New vehicles start with `binding_eligible` set to true and `open_violation_count` set to zero. Both fields are computed server-side: `open_violation_count` is the count of related violations whose `status` is `PENDING` or `DISPUTED`, and `binding_eligible` is false whenever the vehicle has any violation in either of those statuses (so it equals true exactly when `open_violation_count` is zero).

### 3.3. Cards: Issuance, Validity, Binding, and Transfer

An `Operator` issues a card by supplying `card_type` (`MONTHLY` or `STORED_VALUE`), an external `holder_ref` (the issuer's customer reference), `valid_from` and `valid_until` (both ISO 8601 UTC; `valid_from` is the inclusive start of validity and `valid_until` is the inclusive end — interpret as the last second of that day), an optional `monthly_fee_cents` (the flat monthly fee charged on a `MONTHLY` card that exempts its bound vehicles' sessions from per-session billing; zero on `STORED_VALUE`), and an optional `auto_pay_enabled` flag (default false; when true, completed sessions and fines bound to this card auto-debit balance or charge). New cards are issued in `ACTIVE` status with `balance_cents` zero and `bound_vehicle_ids` empty.

Reads return the card with two balance views: `balance_cents` is the provisional balance, computed by walking every `Payment` row whose `card_id` equals this card in chronological `processed_at` order (ties broken by `Payment.id` ascending) and applying each payment as follows — a `CARD_RECHARGE` adds `amount_cents`, a `SESSION_FEE` subtracts `amount_cents`, a `FINE_PAYMENT` subtracts `amount_cents`, a `NO_SHOW_PENALTY` subtracts `amount_cents`, and a `REFUND` adds `amount_cents` (a refund increases the balance because it returns funds). The accumulator runs in integer cents with no rounding. The companion `finalized_balance_cents` runs the identical chronological accumulator over the same card but excludes payments whose subject lifecycle is non-terminal — that is, it excludes payments whose subject is a session with `occupancy_status` `ACTIVE`, a violation whose `status` is neither `PAID` nor `TOWED_AWAY`, or a reservation whose `status` is none of `MATCHED`, `EXPIRED_NO_SHOW`, or `CANCELLED`. Because the finalized variant only excludes mid-lifecycle rows that the provisional already includes, the finalized balance can lag the provisional but never exceed it.

A recharge is initiated by `Operator` or `Driver` and supplies `amount_cents` and an optional idempotency `external_ref`. If `external_ref` is supplied and already present on another `Payment`, the request is rejected with `ERR_DUPLICATE_EXTERNAL_REF`. On success, a `CARD_RECHARGE` `Payment` is appended (`amount_cents` positive), the provisional balance grows, and — when `auto_pay_enabled` is true on this card — the system cascades a settlement sweep that pays any unpaid completed sessions for vehicles bound to this card.

Binding a vehicle to a card requires the vehicle's `binding_eligible` to be true (otherwise `ERR_VEHICLE_HAS_OPEN_VIOLATIONS`), the card's status to be neither `EXPIRED` nor outside its `[valid_from, valid_until]` window (otherwise `ERR_CARD_EXPIRED`), and the card's binding cardinality to admit one more vehicle. Binding cardinality enforces three rules in concert: a `STORED_VALUE` card may have at most one bound vehicle; a `MONTHLY` card may have at most four bound vehicles; and any single vehicle may be bound to at most one `MONTHLY` card across the entire system. A breach of the per-card cap (a stored-value card already has one binding, or a monthly card already has four) yields `ERR_CARD_BINDING_LIMIT`. A breach of the cross-card monthly invariant (the vehicle is already bound to a different `MONTHLY` card) yields `ERR_VEHICLE_ALREADY_BOUND`. On success, the vehicle's `id` is appended to `bound_vehicle_ids`. Unbinding by `vehicle_id` removes that vehicle from `bound_vehicle_ids`; an attempt to unbind a vehicle not currently bound to the card is rejected with `ERR_VEHICLE_NOT_BOUND`.

Transferring a card moves balance and bindings from a source card to another card belonging to the same `holder_ref`, identified by `target_card_id`, with a mandatory `reason`. The transfer is admitted only when both source and target are in `ACTIVE` status and they share the same `holder_ref`; furthermore, the transfer is permitted only between like types — `STORED_VALUE` to `STORED_VALUE` or `MONTHLY` to `MONTHLY`. Any of these mismatches yields `ERR_INVALID_CARD_TRANSFER`. On success, the target's `balance_cents` increases by the source's `balance_cents`, the source's `balance_cents` is set to zero, vehicle bindings are moved (subject to the target's cardinality, with breaches surfacing as `ERR_CARD_BINDING_LIMIT`), and an `AuditLog` row with `action` `CARD_TRANSFER` is written.

A card moves between `ACTIVE` and `SUSPENDED` cyclically and reaches `EXPIRED` terminally. An `Operator` may suspend an `ACTIVE` card (existing bindings are retained but pending auto-pays pause); the operator may then reactivate a `SUSPENDED` card back to `ACTIVE`, allowed only while the current instant remains before `valid_until` (auto-pays then resume). When the current instant moves beyond `valid_until` (recognized either by an admin clock-advance or by a sweep run), an `ACTIVE` or `SUSPENDED` card transitions to `EXPIRED`; on this terminal transition every binding is cleared (`bound_vehicle_ids` becomes empty) and `auto_pay_enabled` is forced to false.

### 3.4. Reservations: Hold, Match, Expire, and Cancel

A `Driver` (or an `Operator` acting on a driver's behalf) creates a reservation by posting `zone_id`, `vehicle_id`, `scheduled_start_at`, `scheduled_end_at`, and an optional `card_id`. The reservation window must satisfy `scheduled_end_at` strictly greater than `scheduled_start_at`, and `scheduled_start_at` must be at least five minutes earlier than the current instant (i.e. `scheduled_start_at` must be at or after the current instant minus five minutes); a violation yields `ERR_INVALID_RESERVATION_WINDOW`. The vehicle must have `binding_eligible` equal to true; otherwise `ERR_VEHICLE_HAS_OPEN_VIOLATIONS`. When the chosen zone is `STANDARD` and the lot's `no_show_penalty_cents` is greater than zero, `card_id` is required as the payer of any future no-show charge.

The system runs a space selector across the chosen zone. A candidate space is one whose `zone_id` matches the requested zone, whose `occupancy_status` is `FREE` or whose `scheduled_start_at` is at or after the space's `last_exited_at` plus the lot's `tow_grace_minutes` (the closed buffer interval), and which has no other reservation in `HELD` or `MATCHED` status whose interval overlaps the requested `[scheduled_start_at, scheduled_end_at)` half-open interval. Touching boundaries do not overlap — back-to-back reservations on the same space are allowed. Overlap yields `ERR_RESERVATION_OVERLAP`; a space caught inside another session's tow-grace window yields `ERR_SPACE_NOT_BOOKABLE`. Among candidates, the selector picks the space with the lexicographically smallest `label`; ties (which only arise across distinct zones, but the selector also tie-breaks within a zone for safety) are broken by the space's `id` ascending. If the candidate set is empty, the request is rejected with `ERR_NO_SPACE_AVAILABLE`. On success, the reservation is created in `HELD` status with `space_id` set to the selected space, and the holding space's `reservation_lock` toggles to `RESERVED`.

A reservation in `HELD` may transition along three terminal branches. A gate-in by the reservation's vehicle whose entry instant lies within the matching window — at or after `scheduled_start_at` minus five minutes and at or before `scheduled_start_at` plus the lot's `reservation_hold_minutes` — and whose space matches the reservation's `space_id` (or a fallback selector if that space is taken) transitions the reservation from `HELD` to `MATCHED`, sets `matched_session_id` to the session's `id` (immutable thereafter), and clears the holding `Space.reservation_lock` to `UNRESERVED`. The match writes a `RESERVATION` revenue entry whose gross amount is the negative of the match-credit discount computed by the reservation-charge calculation.

A clock advance that crosses `scheduled_start_at` plus the lot's `reservation_hold_minutes` while `matched_session_id` is still null transitions the reservation from `HELD` to `EXPIRED_NO_SHOW`, sets `penalty_charged_cents` to the lot's `no_show_penalty_cents`, clears `Space.reservation_lock` to `UNRESERVED`, creates a `NO_SHOW_PENALTY` `Payment` debited from `Reservation.card_id` when present, and writes a `NO_SHOW_PENALTY` revenue entry. Insufficient stored-value funds on the payer card surface as `ERR_INSUFFICIENT_BALANCE` during the cascade.

A `Driver` or `Operator` may cancel a `HELD` reservation. If the cancellation arrives at or after `scheduled_start_at` minus thirty minutes — the no-cancel window — `penalty_charged_cents` is set to half of the lot's `no_show_penalty_cents`, divided in integer cents and rounded half-up to the nearest cent, a `NO_SHOW_PENALTY` `Payment` is created, and a `NO_SHOW_PENALTY` revenue entry is written. If the cancellation arrives earlier than that, `penalty_charged_cents` stays zero and no penalty payment is created. In both cases, `Reservation.status` moves from `HELD` to `CANCELLED`, the holding `Space.reservation_lock` is cleared to `UNRESERVED`, and an `AuditLog` row with `action` `RESERVATION_CHANGE` is written. The cancel transition itself is unconditional on time so long as the reservation is still `HELD`.

A reservation while still `HELD` may have its window or vehicle edited via a partial update accepting `scheduled_start_at`, `scheduled_end_at`, `vehicle_id`, and a mandatory `reason`; the request requires an `If-Match` header for optimistic concurrency, must pass the same window and vehicle-eligibility checks as creation, and writes an `AuditLog` row with `action` `RESERVATION_CHANGE`.

The reservation-charge calculation pins billing semantics in two strictly ordered steps. The first step determines the `billing_type` from the reservation's terminal `status`: a status of `MATCHED` pins `billing_type` to `RESERVATION`, while `EXPIRED_NO_SHOW` and `CANCELLED` both pin `billing_type` to `NO_SHOW_PENALTY`. The second step computes the effective charge using the pinned `billing_type`. When `billing_type` is `RESERVATION`, the system first computes `scheduled_window_hours` as the duration from `scheduled_start_at` to `scheduled_end_at` in seconds divided by 3600 and rounded up to the next whole number; it then computes a reference amount equal to the smaller of `scheduled_window_hours` multiplied by the lot's `hourly_rate_cents` and the lot's `daily_cap_cents`; it then computes the discount as the reference amount multiplied by the match-discount basis points (the constant `MATCH_DISCOUNT_BPS` fixed at 1000, equivalent to 10.00%) divided by 10000 and rounded half-up to the nearest cent; the effective charge is the negative of this discount, recorded as a negative-gross adjustment so that house and partner shares net out correctly. When `billing_type` is `NO_SHOW_PENALTY` and `status` is `EXPIRED_NO_SHOW`, the effective charge is the lot's `no_show_penalty_cents`. When `billing_type` is `NO_SHOW_PENALTY` and `status` is `CANCELLED`, the effective charge is half the lot's `no_show_penalty_cents` rounded half-up to the nearest cent if the cancellation occurred at or after `scheduled_start_at` minus thirty minutes, and zero otherwise. Pinning step one before step two prevents a dangling reference: the discount formula references `MATCHED` only after the status branch has already selected `RESERVATION`.

### 3.5. Sessions: Entry, Estimation, Exit, Payment, and Waiver

A session opens when a `GateSystem` (or an `Operator` working a gate) posts to the lot's session endpoint, supplying either a `vehicle_id` or a `plate` (which is normalized identically to vehicle registration), an optional `space_id` (if absent, the system runs the same selector logic as reservations to pick the lex-smallest-label `FREE` candidate that respects `tow_grace_minutes`), and an optional `card_id` to pin a payment instrument to this session at entry time.

Entry is admitted only when the chosen space's `occupancy_status` equals `FREE`, and either `Space.reservation_lock` equals `UNRESERVED` or there is a `HELD` reservation for this exact space whose vehicle matches the entering vehicle and whose matching window includes the current instant; otherwise the request is rejected with `ERR_SPACE_OCCUPIED` (the space is currently occupied by a different session) or `ERR_SPACE_NOT_BOOKABLE` (the space is inside its post-exit tow-grace buffer and is not held by a matching reservation). Specifically, entry into a space whose `reservation_lock` is `UNRESERVED` requires the current instant to be at or after `Space.last_exited_at` plus the lot's `tow_grace_minutes` whenever `last_exited_at` is set. On admission, the new session is created with `entry_at` set to the current instant, `occupancy_status` `ACTIVE`, and `payment_status` `UNPAID`; the holding space transitions to `OCCUPIED` with `current_session_id` set to the new session, the parent zone's `free_spaces` decrements by one, and any `HELD` reservation that matched flips to `MATCHED` with its space's `reservation_lock` cleared to `UNRESERVED`.

Reading a session re-runs the session-billing calculation in its provisional-estimate variant on every request and returns the result as `estimated_fee_cents` (recomputed live and never persisted). The same session in `EXITED` state returns `final_fee_cents` and `billing_kind` pinned at exit time and never recomputed. Because the started-hour count uses ceiling rounding and is therefore discontinuous at hour boundaries, a provisional estimate taken one millisecond before exit can differ from the eventual final settlement.

The session-billing calculation runs in two pre-classification checks followed by a tiered hourly tally with a daily cap. Pre-classification: if the session's vehicle has `kind` `EMERGENCY` or `DISABLED`, `billing_kind` is pinned to `EXEMPT_VEHICLE` and the fee is zero. Otherwise, if the session has a non-null `card_id` and that card has `card_type` `MONTHLY` and `status` `ACTIVE` and the session's vehicle is in the card's `bound_vehicle_ids` and the session's `entry_at` lies inside the card's `[valid_from, valid_until]` window, then `billing_kind` is pinned to `MONTHLY_COVERED` and the fee is zero. Otherwise, `billing_kind` is `HOURLY`.

For the `HOURLY` path, the system measures the session duration as the difference in seconds between the exit clock and `entry_at`. The exit clock is the current instant when the session is `ACTIVE` (provisional variant) or the pinned `exit_at` when the session is `EXITED` (final variant). If the duration is at most the lot's `free_minutes` multiplied by 60 seconds, the fee is zero. Otherwise, the duration is split into per-calendar-day segments using the lot's `timezone`: for each calendar day that the session spans, the segment in seconds is the smaller of the day's end and the exit clock, minus the larger of the day's start and `entry_at`. The free period applies only on the first day (the day containing `entry_at`); subsequent days do not get a fresh free period. For each day, the billable seconds equal the segment seconds minus, on the first day only, `free_minutes` multiplied by 60; that value is then floored at zero. The day's started-hour count is the billable seconds divided by 3600 rounded up to the next whole number — any partial hour rounds up. The day's raw cost is started hours multiplied by `hourly_rate_cents`. The day's capped cost is the smaller of the raw cost and the lot's `daily_cap_cents`. The session fee is the sum of capped costs across all spanned days. All arithmetic runs in integer cents.

Exiting the session pins `exit_at` to the current instant, runs the final-settlement variant of session billing to pin `final_fee_cents` and `billing_kind`, transitions `occupancy_status` from `ACTIVE` to `EXITED`, transitions the holding space's `occupancy_status` from `OCCUPIED` to `FREE`, sets `Space.last_exited_at` equal to `exit_at`, clears `Space.current_session_id`, and increments `Zone.free_spaces` by one when `Space.reservation_lock` is `UNRESERVED`. If the session is pinned to a card whose `auto_pay_enabled` is true, the system cascades a session-fee payment immediately.

Paying a session is initiated by a `Driver` or `Operator` and accepts an optional `card_id` (overriding the session's pinned card if absent at session creation) and an optional `external_ref` for idempotency. Payment is admitted only on a session whose `occupancy_status` is `EXITED` and whose `final_fee_cents` is pinned. When a `STORED_VALUE` card is used, the card's `balance_cents` must be at least `final_fee_cents`; otherwise `ERR_INSUFFICIENT_BALANCE`. When the session's vehicle is `EMERGENCY` or `DISABLED`, the request is rejected with `ERR_EXEMPT_VEHICLE` (an exempt vehicle's session has zero fee and needs no explicit pay). On success, a `SESSION_FEE` `Payment` is created, `payment_status` transitions from `UNPAID` to `PAID`, the stored-value card's `balance_cents` is debited by `final_fee_cents`, and a `RevenueEntry` is created with `billing_type` `HOURLY` (or `MONTHLY` when `billing_kind` is `MONTHLY_COVERED` and the entry-time fee was zero).

An `Operator` may waive an unpaid session by supplying a non-empty `reason`. Waivers are admitted only on `EXITED` sessions; they transition `payment_status` from `UNPAID` to `WAIVED`, write an `AuditLog` row with `action` `BILLING_ADJUSTMENT`, and produce a `RevenueEntry` with `billing_type` `ADJUSTMENT` and `gross_amount_cents` equal to the negative of `final_fee_cents`.

A session in `UNPAID` payment status moves to `DISPUTED` automatically when an `EnforcementOfficer` issues an `OVERSTAY` violation against an `EXITED` session linked to it; the cascade also triggers a recomputation of `Vehicle.binding_eligible` because `open_violation_count` increased. From `DISPUTED`, the session moves back to `UNPAID` only via the violation lifecycle: when an `Operator` flips a `DISPUTED` violation back to `PENDING`, the linked session's `payment_status` cascades from `DISPUTED` to `UNPAID`. A session in `PAID` may also revert to `UNPAID` when its `SESSION_FEE` `Payment` is refunded inside the seven-day refund window.

### 3.6. Violations, Fines, and Tow Coordination

An `EnforcementOfficer` issues a violation by posting `lot_id`, `vehicle_id`, `violation_type` (one of `OVERSTAY`, `NON_PAYING`, `BLOCKING`, `WRONG_ZONE`), an optional `session_id` (null for non-session violations such as a wrong-zone walk-up), `space_id` (the space where evidence was captured), an optional `photo_uri`, the `detected_at` timestamp, and the officer's `officer_id` (an opaque enforcement-officer identifier). When `violation_type` is `BLOCKING` or `WRONG_ZONE`, the `photo_uri` must be non-empty; an empty or missing `photo_uri` for these types is rejected with `ERR_PHOTO_REQUIRED`. When the targeted vehicle is `EMERGENCY` or `DISABLED` and the violation type is `OVERSTAY` or `NON_PAYING`, the request is rejected with `ERR_EXEMPT_VEHICLE`; the same exempt vehicle remains subject to `BLOCKING` and `WRONG_ZONE` enforcement.

On admission, the violation enters `PENDING` status. A `Fine` is appended in the same transaction whose `violation_id` points back to the violation, whose `amount_cents` is computed by the fine-amount calculation and immutable thereafter, whose `components` is an immutable breakdown carrying `base_cents`, `type_multiplier`, `repeat_offender_surcharge_cents`, and `photo_required_surcharge_cents`, and whose `paid_at` is null. The vehicle's `open_violation_count` increments by one and `binding_eligible` is recomputed (it becomes false if it was previously true). When the violation's `violation_type` is `OVERSTAY` and the linked session is `EXITED` and currently `UNPAID`, the session's `payment_status` cascades from `UNPAID` to `DISPUTED`.

The fine-amount calculation is pinned at violation creation in the following ordered steps. The base amount is taken from a fixed table keyed on `violation_type`: `OVERSTAY` is 2000 cents ($20.00), `NON_PAYING` is 3000 cents ($30.00), `BLOCKING` is 5000 cents ($50.00), and `WRONG_ZONE` is 4000 cents ($40.00). The type multiplier is taken from a fixed table keyed on `violation_type`: `OVERSTAY` is 1.0, `NON_PAYING` is 1.5, `BLOCKING` is 2.0, and `WRONG_ZONE` is 1.25. The photo-required surcharge is 1500 cents when `violation_type` is `BLOCKING` or `WRONG_ZONE`, and zero otherwise. The repeat-offender surcharge is determined by counting prior violations attributed to this vehicle (excluding the violation under construction) whose `status` is `PAID` or `TOWED_AWAY`, or whose `status` is `PENDING` and whose `detected_at` is at or after the current instant minus 90 days: a count of zero implies a zero surcharge, a count of exactly one implies 1000 cents (`REPEAT_TIER1_CENTS`), a count of exactly two implies 2500 cents (`REPEAT_TIER2_CENTS`), and a count of three or more implies 5000 cents (`REPEAT_TIER3_CENTS`). The final amount is computed by first multiplying `base_cents` by `type_multiplier` in arbitrary-precision decimal, rounding the product half-up to the nearest integer cent, and then adding the photo-required surcharge and the repeat-offender surcharge as integer cents without further rounding. Fixing this order — multiply-and-round before adding integer surcharges — eliminates round-each-component versus round-final divergence.

A violation moves between `PENDING` and `DISPUTED` cyclically and reaches `PAID` or `TOWED_AWAY` terminally. A `Driver` may dispute a `PENDING` violation by patching its status to `DISPUTED`; the dispute is admitted only when the current instant is at or before `detected_at` plus 14 days, requires a non-empty `reason`, and writes an `AuditLog` row with `action` `BILLING_ADJUSTMENT`. An `Operator` may flip a `DISPUTED` violation back to `PENDING` by patching its status to `PENDING`; the flip requires a non-empty `reason` and writes an `AuditLog` row with `action` `BILLING_ADJUSTMENT`. A linked session whose `payment_status` was `DISPUTED` at the moment of the operator's flip cascades back to `UNPAID`.

A `Driver` or `Operator` may pay a `PENDING` violation by supplying `amount_cents` exactly equal to the fine's `amount_cents`, an optional `card_id`, and an optional idempotency `external_ref`. On success, `Violation.status` transitions from `PENDING` to `PAID`, `Fine.paid_at` is set to the current instant, the vehicle's `open_violation_count` decrements by one and `binding_eligible` is recomputed (true exactly when `open_violation_count` is now zero), and a `RevenueEntry` is created with `billing_type` `FINE`. If a session is linked and its `payment_status` is `DISPUTED`, the session cascades from `DISPUTED` to `UNPAID`.

An `Operator` may coordinate a tow on a `PENDING` violation older than 24 hours by supplying a non-empty `reason`. The tow is admitted only when `Violation.status` is `PENDING`, `violation_type` is one of `BLOCKING`, `WRONG_ZONE`, or `OVERSTAY`, and `Fine.amount_cents` has gone unpaid for at least 24 hours since `detected_at`. On success, `Violation.status` transitions to `TOWED_AWAY`, the vehicle's `open_violation_count` decrements by one, an `AuditLog` row with `action` `BILLING_ADJUSTMENT` is written, and — if the linked session is still `ACTIVE` — the session is force-exited (its `occupancy_status` flips from `ACTIVE` to `EXITED`, `final_fee_cents` is pinned, and the holding `Space.occupancy_status` flips from `OCCUPIED` to `FREE`).

### 3.7. Payments, Refunds, and the Revenue Ledger

`Payment` rows are append-only and capture every monetary movement: a `kind` of `SESSION_FEE`, `FINE_PAYMENT`, `CARD_RECHARGE`, `NO_SHOW_PENALTY`, or `REFUND`, a polymorphic `subject_id` (the session, violation, card, reservation, or original payment that the row references), a positive `amount_cents` (interpreted as outflow when `kind` is `REFUND`), an optional `card_id` for the payment instrument (null for external-rail payments), the `processed_at` timestamp at which the payment was applied, and an optional `external_ref` providing idempotency (when present, it must be globally unique; a duplicate is rejected with `ERR_DUPLICATE_EXTERNAL_REF`).

An `Operator` may refund an existing payment by posting a non-empty `reason` against the original payment's id. The refund is admitted only when the current instant is at or before the original payment's `processed_at` plus seven days; otherwise the request is rejected with `ERR_REFUND_WINDOW_EXPIRED`. On success, a new `REFUND` `Payment` is appended (separate row), the subject lifecycle is reverted (a session payment moves from `PAID` back to `UNPAID`), a `RevenueEntry` is created with `billing_type` `REFUND` and `gross_amount_cents` equal to the negative of the original amount, the stored-value card is credited by the refunded amount when the original payment debited a stored-value card, and an `AuditLog` row with `action` `BILLING_ADJUSTMENT` is written.

`RevenueEntry` rows are likewise append-only. Each entry carries the `lot_id` it originated under, an optional `zone_id` when the entry can be attributed to a zone (null otherwise), a `billing_type` drawn from `HOURLY`, `MONTHLY`, `RESERVATION`, `NO_SHOW_PENALTY`, `FINE`, `REFUND`, and `ADJUSTMENT`, a `source_kind` drawn from `SESSION`, `RESERVATION`, `VIOLATION`, `CARD`, and `MANUAL`, a polymorphic `source_id` pointing to the source entity, the signed `gross_amount_cents` (positive for revenue and negative for refund or adjustment) before partner share, the per-entry `partner_share_cents` and `house_share_cents`, the `settlement_period` day-key in lot timezone (formatted `YYYY-MM-DD`) at which the entry was generated, and an optional `notes` narrative populated only when `billing_type` is `ADJUSTMENT`.

The revenue-split calculation runs per-entry in a fixed order. For each new entry, the system first computes the partner cut as the entry's `gross_amount_cents` multiplied by the lot's `partner_share_bps` divided by 10000 and rounded half-up to the nearest integer cent; the result is sign-preserving for negative gross amounts (so a refund's partner share is negative in raw form) but is then clamped to a floor of zero, ensuring `partner_share_cents` is always non-negative. The house cut is then computed as `gross_amount_cents` minus `partner_share_cents`, preserving the sign of gross. Both values are stored on the entry and never re-rounded. Aggregating partner totals across a settlement period sums each entry's already-rounded `partner_share_cents`; it does not multiply the period's gross sum by the basis-point ratio and then round once. With mixed-sign entries and more than two rows, those two methods can diverge by up to one cent per entry; per-entry-then-sum is authoritative.

The revenue endpoint accepts optional `from`, `to`, `group_by`, `billing_type`, `limit`, and `offset` query parameters; `group_by` may be any combination of `period`, `zone_id`, and `billing_type` and the response groups its `RevenueEntry[]` payload accordingly using the per-entry-then-sum invariant. Settlement is invoked separately: an `Operator` posts to the settlement-run endpoint with an optional `period`, and the system emits an immutable invoice record carrying `invoice_id`, the `period`, and the period's `gross_total_cents`, `partner_total_cents`, and `house_total_cents`. After a settlement run, the `settlement_period` of subsequent revenue rows uses the next day-key.

### 3.8. Audit Trail and Operational Test-Driving Endpoints

Every audit-bearing action appends an `AuditLog` row. The system surfaces the log via a list endpoint accepting optional `subject_kind`, `subject_id`, and `action` filters along with the standard `limit` and `offset` controls; only `Operator` and `Auditor` roles read this surface.

Three operational endpoints exist for testability and for processing time-driven transitions. An admin-only clock-advance capability advances the logical clock to the supplied `to` instant; the advance triggers eligible card transitions to `EXPIRED` (any `ACTIVE` or `SUSPENDED` card whose `valid_until` is now in the past) and eligible reservation transitions from `HELD` to `EXPIRED_NO_SHOW` (any `HELD` reservation whose `scheduled_start_at` plus the lot's `reservation_hold_minutes` is now in the past with `matched_session_id` still null). A sweep-run capability is the idempotent companion: it recomputes card expirations, reservation no-shows, and denormalized `Zone.total_spaces` and `Zone.free_spaces` counts, returning a summary object with `cards_expired`, `reservations_expired`, and `zones_recomputed`. An external-event injection capability accepts an `event_kind` (`LPR_DETECT`, `PAYMENT_CALLBACK`, or `IM_ACK`) and a `payload`, applies the corresponding side effect (opening a session for the detected plate, marking a `Payment.external_ref` as confirmed, or stamping notification delivery for an instant-message acknowledgement without state mutation), and returns `applied` and `side_effects`.

## 4. Endpoint Definitions

This section enumerates the API surface. New resources are returned with HTTP status 201; modifications and reads are returned with HTTP status 200. Refer to the §3 narratives above for full request and response semantics, including request bodies, side effects, and cascade rules — the table below is intentionally compact.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/lots` | Create a parking lot | `Operator` |
| GET | `/lots/{lot_id}` | Read parking lot configuration | `Operator`, `Driver`, `EnforcementOfficer`, `ParkingPartner`, `Auditor` |
| POST | `/lots/{lot_id}/zones` | Create a zone within a lot | `Operator` |
| GET | `/lots/{lot_id}/availability` | Real-time availability summary by zone, with optional `zone_type` filter | `Operator`, `Driver`, `EnforcementOfficer`, `ParkingPartner`, `Auditor` |
| POST | `/lots/{lot_id}/zones/{zone_id}/spaces` | Create a space | `Operator` |
| GET | `/lots/{lot_id}/zones/{zone_id}/spaces/{space_id}` | Read a space's real-time status | `Operator`, `Driver`, `EnforcementOfficer`, `ParkingPartner`, `Auditor` |
| POST | `/vehicles` | Register a vehicle (LPR registration) | `Operator`, `GateSystem` |
| GET | `/vehicles/{vehicle_id}` | Read a vehicle | `Operator`, `Driver`, `EnforcementOfficer`, `GateSystem`, `Auditor` |
| POST | `/cards` | Issue a card | `Operator` |
| GET | `/cards/{card_id}` | Read a card; returns provisional `balance_cents` and `finalized_balance_cents` | `Operator`, `Driver`, `ParkingPartner`, `Auditor` |
| POST | `/cards/{card_id}/recharge` | Recharge stored-value card; idempotent on `external_ref` | `Operator`, `Driver` |
| POST | `/cards/{card_id}/bind` | Bind a vehicle to this card | `Operator` |
| POST | `/cards/{card_id}/unbind` | Unbind a vehicle from this card | `Operator` |
| POST | `/cards/{card_id}/suspend` | Suspend an `ACTIVE` card | `Operator` |
| POST | `/cards/{card_id}/reactivate` | Reactivate a `SUSPENDED` card | `Operator` |
| POST | `/cards/{card_id}/transfer` | Transfer balance and bindings to another card under same `holder_ref` | `Operator` |
| POST | `/lots/{lot_id}/reservations` | Create a reservation; selector picks a Space | `Driver`, `Operator` |
| GET | `/reservations/{reservation_id}` | Read a reservation | `Driver`, `Operator`, `ParkingPartner`, `Auditor` |
| PATCH | `/reservations/{reservation_id}` | Update reservation window or vehicle (`HELD` only); requires `If-Match` and `reason` | `Driver`, `Operator` |
| POST | `/reservations/{reservation_id}/cancel` | Cancel a `HELD` reservation | `Driver`, `Operator` |
| POST | `/lots/{lot_id}/sessions` | Open a session at a gate (entry) | `GateSystem`, `Operator` |
| GET | `/sessions/{session_id}` | Read a session; `estimated_fee_cents` recomputed live | `Driver`, `Operator`, `ParkingPartner`, `GateSystem`, `Auditor` |
| POST | `/sessions/{session_id}/exit` | Close a session at gate-out; pins `final_fee_cents` | `GateSystem`, `Operator` |
| POST | `/sessions/{session_id}/pay` | Pay a session fee | `Driver`, `Operator` |
| POST | `/sessions/{session_id}/waive` | Operator waives an unpaid session | `Operator` |
| POST | `/violations` | Issue a violation; `Fine` auto-created with computed amount | `EnforcementOfficer` |
| GET | `/violations/{violation_id}` | Read a violation | `EnforcementOfficer`, `Driver`, `Operator`, `Auditor` |
| PATCH | `/violations/{violation_id}` | Move violation between `PENDING` and `DISPUTED` per RBAC; `reason` required | `Driver`, `Operator` |
| POST | `/violations/{violation_id}/pay` | Pay the fine; idempotent on `external_ref` | `Driver`, `Operator` |
| POST | `/violations/{violation_id}/tow` | Coordinate tow-away for an unpaid violation older than 24h | `Operator` |
| POST | `/payments/{payment_id}/refund` | Refund an existing payment within 7-day window | `Operator` |
| GET | `/lots/{lot_id}/revenue` | Multi-dimensional revenue aggregation | `Operator`, `ParkingPartner`, `Auditor` |
| POST | `/lots/{lot_id}/settlement/run` | Settle current period: emit invoice and partner-share snapshot | `Operator` |
| GET | `/audit-logs` | List audit log entries; filter by `subject_kind`, `subject_id`, `action` | `Auditor`, `Operator` |
| POST | `/_clock/advance` | Advance virtual clock (test driver) | `Operator`, `Auditor` |
| POST | `/_sweep/run` | Run idempotent sweep | `Operator`, `Auditor` |
| POST | `/_events/emit` | Inject an external event for synchronization tests | `Operator`, `Auditor` |

## 5. Error Code Catalogue

Trigger conditions for every error are described inline in §2 and §3; the table below lists only the canonical identifier and HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_AUTH` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_BAD_REQUEST` | 400 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SPACE_OCCUPIED` | 409 |
| `ERR_SPACE_NOT_BOOKABLE` | 409 |
| `ERR_RESERVATION_OVERLAP` | 409 |
| `ERR_NO_SPACE_AVAILABLE` | 409 |
| `ERR_INVALID_RESERVATION_WINDOW` | 422 |
| `ERR_VEHICLE_HAS_OPEN_VIOLATIONS` | 409 |
| `ERR_VEHICLE_ALREADY_BOUND` | 409 |
| `ERR_CARD_BINDING_LIMIT` | 409 |
| `ERR_CARD_EXPIRED` | 409 |
| `ERR_INVALID_CARD_TRANSFER` | 422 |
| `ERR_INSUFFICIENT_BALANCE` | 402 |
| `ERR_REFUND_WINDOW_EXPIRED` | 422 |
| `ERR_PHOTO_REQUIRED` | 422 |
| `ERR_EXEMPT_VEHICLE` | 422 |
| `ERR_REASON_REQUIRED` | 422 |
| `ERR_DUPLICATE_EXTERNAL_REF` | 409 |
| `ERR_VEHICLE_NOT_BOUND` | 409 |
