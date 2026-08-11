# Concierge Senior Transport API — Product Requirements Document

## 1. Introduction

Families arranging transportation for an aging parent live in the gap between a taxi and an ambulance: the trips are mundane — a grocery run, a dialysis appointment, a weekly companion outing — but the riders are not. Seniors may travel with a walker or a power wheelchair, may need a driver who escorts them through the door rather than curbside, and their adult children want visibility into every pickup and drop-off without placing the call themselves. This document specifies the Concierge Senior Transport API, a private non-emergency transport platform that manages the full arc of that service: registering senior clients and their family portal members, vetting drivers through background-check, bonding, and insurance documentation, matching rides to qualified drivers under buffered-schedule and daily-cap constraints, executing door-through-door trips with metered wait time, and settling accounts through invoicing, a prepaid client credit pool, payments, refunds, and disputes.

Two design commitments shape everything that follows. First, the platform treats time as a first-class, test-controllable input: all windows, horizons, grace periods, and notice thresholds are evaluated against a server-side logical clock rather than wall-clock time. Second, money is handled with bank-grade determinism — every fare, fee, invoice line, credit application, and refund reversal follows a pinned evaluation order over integer cents, so two readers of this document arrive at the same number to the cent. The API serves platform operators, concierge coordinators, compliance officers, billing administrators, and — under strict ownership rules — the clients, family members, and drivers themselves.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes seven distinct roles: `PlatformAdmin`, `Coordinator`, `ComplianceOfficer`, `BillingAdmin`, `Client`, `FamilyMember`, and `Driver`. Failure to provide valid, recognized headers will result in an `ERR_UNAUTHENTICATED` error. Furthermore, access to specific operations is restricted by role; an attempt to perform an action outside of the caller's designated role will be rejected with an `ERR_UNAUTHORIZED_ROLE` error.

The meaning of `X-User-ID` depends on the role presented in `X-User-Role`. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's `client_id` field to `X-User-ID`. When `X-User-Role` is `FamilyMember`, `X-User-ID` is the `id` of the acting `FamilyMember`; the member's capabilities derive from that row — the attached client, the `access_level` tier, and whether the membership is still `ACTIVE` — and a member whose status has been revoked, or whose tier does not cover the attempted action, is rejected with `ERR_FAMILY_ACCESS_INSUFFICIENT` on the guarded write actions of §2.6; on portal read endpoints the same revocation instead fails the ownership check with `ERR_FORBIDDEN_OWNERSHIP`. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver`; ownership checks on assignments and assigned rides compare against that driver id, and a driver who touches a resource owned by another driver is rejected with `ERR_FORBIDDEN_OWNERSHIP`. For the remaining roles — `PlatformAdmin`, `Coordinator`, `ComplianceOfficer`, and `BillingAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `reviewed_by_user_id` on a reviewed document, `matched_by_user_id` on a dispatched offer, or `resolved_by_user_id` on a resolved dispute) but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Wherever this document pins an ordering on timestamps — list sorts, the payment waterfall's `due_date` ordering, invoice-line emission, the selector's `created_at` tie-break — entries equal on every pinned key are ordered in the sequence the records were created.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary resources — clients, family members, drivers, compliance documents, rate cards, standing ride series, rides, assignments, invoices, invoice lines, and payments — include a standard set of system-managed fields:

- **`id` (string):** A unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-05-24T10:30:00.123Z`) indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified. This field is refreshed upon any change to the resource's properties.
- **`version` (integer):** A system-managed integer that increments with every mutation of the resource. This field anchors the optimistic concurrency control described in §2.7.

The ride event log is the one exception: a `RideEvent` is an immutable ledger entry and carries only `id` and `created_at`. Both `updated_at` and `version` are absent from ride events — an event, once recorded, is never mutated.

Mutations triggered automatically by the server (the no-show auto-suspension, the compliance-expiry driver cascade, invoice status recomputation under payments and refunds) mutate the affected resource exactly as an explicit write would, refreshing `updated_at` and incrementing `version` where the entity carries those fields.

### 2.5. The Logical Clock, Dates, and Half-Open Windows

Every temporal decision in the system — validity windows, billing periods, cancellation notice, offer timeouts, the no-show grace, the generation horizon, past-due marking — reads a single server-side **logical clock**, never wall-clock time. At startup the logical clock reads exactly `2026-05-01T00:00:00Z`; until it is explicitly set, every evaluation uses this default. A platform-administrator-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant, after which all timestamps, windows, horizons, and notice computations read the new value.

Date ranges in this domain are **half-open**: the start date is included and the end date is excluded. A compliance document is valid on every date from `valid_from` up to but not including `valid_until`; a rate card prices pickups from `effective_from` up to but not including `effective_to`; an invoice bills rides whose pickup date falls from `period_start` up to but not including `period_end`. Two half-open windows that merely touch at a boundary — one ending exactly where the next begins — do not intersect. Standing ride series are the deliberate exception: both `starts_on` and `ends_on` are inclusive bounds on the series' calendar range.

### 2.6. Validation Pipeline and Check Ordering

Every request is evaluated against a fixed, ordered validation pipeline. A request fails at the first check it violates, so when several rules could reject the same request, the error the caller observes is determined by this order:

1. **Well-formedness.** The request body must be valid JSON, declare all required fields, and carry well-formed enum and typed values; violations are rejected with `ERR_INVALID_REQUEST`.
2. **Authentication.** The `X-User-Role` and `X-User-ID` headers must be present and recognized; otherwise `ERR_UNAUTHENTICATED`.
3. **Role gate.** The caller's role must appear in the endpoint's allowed role list; otherwise `ERR_UNAUTHORIZED_ROLE`.
4. **Entity-backed ownership.** A `Client` acts only on their own resources, a `Driver` only on their own assignments and rides, and a `FamilyMember` only on their client's resources; violations surface as `ERR_FORBIDDEN_OWNERSHIP`.
5. **Family capability tier.** Booking requires the member's `access_level` to be `BOOK_FOR_CLIENT` or `BILLING_PAYER`; taking a payment requires `BILLING_PAYER`; and the membership must be `ACTIVE` — this tier check guards ride booking, standing-series booking, payment capture, ride cancellation, and dispute raising, and failures are rejected with `ERR_FAMILY_ACCESS_INSUFFICIENT`.
6. **Existence.** Path-referenced and body-referenced ids must exist, validated left to right; the first missing reference yields `ERR_NOT_FOUND`.
7. **State preconditions.** The target entity must be in a state permitting the operation — the per-entity rejections are `ERR_RIDE_NOT_CANCELLABLE`, `ERR_RIDE_NOT_DISPATCHABLE`, `ERR_ASSIGNMENT_NOT_ACTIONABLE`, `ERR_ASSIGNMENT_RELEASE_INVALID`, `ERR_EXECUTION_EVENT_INVALID`, `ERR_INVOICE_NOT_ISSUABLE`, `ERR_INVOICE_NOT_VOIDABLE`, `ERR_DISPUTE_ACTION_INVALID`, `ERR_PAYMENT_NOT_REFUNDABLE`, `ERR_STANDING_STATUS_INVALID`, `ERR_RATE_CARD_STATE_INVALID`, `ERR_DOC_ALREADY_REVIEWED`, and `ERR_DRIVER_STATE_INVALID`. This stage also carries the client-active gate on ride and series booking, which rejects with `ERR_CLIENT_SUSPENDED`.
8. **Optimistic concurrency.** Where an endpoint takes an expected-version field, the value must equal the resource's current `version`; otherwise `ERR_STALE_VERSION` (see §2.7).
9. **Driver compliance and eligibility.** Activation and offer-acceptance recheck the driver's posture and fitness for the specific ride, surfacing `ERR_DRIVER_COMPLIANCE_INCOMPLETE`, `ERR_DRIVER_NOT_ELIGIBLE`, or `ERR_DRIVER_DAILY_CAP_EXCEEDED`.
10. **Temporal windows.** Document, rate-card, series, and invoice windows must be internally valid, and the no-show grace must have elapsed — `ERR_DOC_WINDOW_INVALID`, `ERR_RATE_WINDOW_INVALID`, `ERR_STANDING_WINDOW_INVALID`, and `ERR_INVOICE_PERIOD_INVALID` are 422 rejections, while `ERR_NO_SHOW_TOO_EARLY` is a 409.
11. **Occupancy and uniqueness.** Buffered-window overlaps (`ERR_RIDE_OVERLAP_DRIVER`), rate-card window intersections (`ERR_RATE_WINDOW_OVERLAP`), invoice period intersections (`ERR_INVOICE_PERIOD_OVERLAP`), a duplicate live offer (`ERR_DUPLICATE_OFFER`), an empty billing set (`ERR_INVOICE_EMPTY`), and the open-work deactivation guard (`ERR_CLIENT_HAS_OPEN_WORK`).
12. **Referential integrity.** Return-leg links and family-booker attachments must point at the right client and ride — `ERR_RETURN_LINK_MISMATCH` and `ERR_FAMILY_CLIENT_MISMATCH`.
13. **Fiscal gates.** An active rate card must cover the ride's class at pickup (`ERR_RATE_CARD_NOT_ACTIVE`, 409), the client's overdue receivables must sit below their hold limit (`ERR_BILLING_HOLD`, 402), a payment must tender a positive amount (`ERR_PAYMENT_AMOUNT_INVALID`, 422), and refund caps are enforced (`ERR_REFUND_EXCEEDS_SETTLED`, 422, and `ERR_REFUND_CREDIT_SPENT`, 409).
14. **Segregation of duties.** Dispute resolution is checked last, after the invoice's existence and dispute state are established; a resolver who dispatched a ride billed on that invoice is rejected with `ERR_SOD_CONFLICT`.

### 2.7. Optimistic Concurrency Control

Two write endpoints carry optimistic concurrency control, and both name the expectation field after the entity being written.

- `PUT /standing-rides/{id}` requires `expected_standing_ride_version` as a non-optional input carrying the caller's last observed `version` of the series. Because editing a template regenerates its future occurrences, an expectation that no longer equals the current version means another writer's edit has already advanced the template — and rebuilt the occurrence set — since the caller last read it. The edit is rejected with `ERR_STALE_VERSION` (HTTP 412).
- `PATCH /clients/{id}` requires `expected_client_version` as a non-optional input carrying the caller's last observed `version` of the client. Any intervening write — including system-driven transitions such as the no-show auto-suspension — advances the client, and a stale expectation is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed here do not take a version field. Rejection leaves the target resource unmodified; the client is expected to re-read and retry with the fresh version.

### 2.8. Monetary Precision and Rounding

All monetary values — fares, fees, invoice lines, credits, payments, refunds — are integer cents. Division-bearing steps round **half-up to whole cents** exactly where specified and nowhere else: the hourly proration step and the after-hours multiplier step of the fare formula, the 50% cancellation tier, and each invoice line amount. The platform never computes an invoice total by summing unrounded amounts and rounding once. Configuration values entered by operators (rates, multipliers, thresholds) are stored at input precision as integers, and each must be non-negative — a rate card's tariff fields, a driver's `max_daily_service_minutes`, and a client's `billing_hold_limit_cents` all reject a negative value with `ERR_INVALID_REQUEST`.

### 2.9. Driver Compliance Posture

A driver's **compliance posture** is the cross-cutting gate behind activation, reinstatement, offer acceptance, and the automated expiry sweep. The posture is complete on a given date when the driver holds, for each of the three required document types — `BACKGROUND_CHECK`, `BONDING`, and `INSURANCE` — at least one `APPROVED` document whose half-open validity window covers that date. The fourth document type, `MOTOR_VEHICLE_RECORD`, may be submitted and reviewed but is not part of the required posture. Posture is always evaluated against a date: activation and reinstatement evaluate it at the logical today, while offer acceptance evaluates it at the ride's scheduled pickup date.

### 2.10. Segregation of Duties in Billing

A billing administrator who was involved in dispatching work must not adjudicate the bill for that work. Concretely, the operator resolving a dispute on an invoice must not be the operator whose `X-User-ID` was recorded as `matched_by_user_id` on any assignment whose ride is billed on that invoice. This check is evaluated only after the invoice's existence and dispute state are established (it sits at the end of the validation pipeline in §2.6), and a conflict is rejected with `ERR_SOD_CONFLICT`.

### 2.11. Referenced Resource Validation

Whenever a request references resources by id — in the path or in the body — the server validates existence in a strict left-to-right order and rejects the request at the first unknown id with `ERR_NOT_FOUND`. Body references such as `client_id`, `driver_id`, `booked_by_family_member_id`, or `linked_return_ride_id` are checked in the order they conceptually appear in the payload, after every path identifier has been resolved. Existence checking always precedes state and business checks, so a request naming a nonexistent resource never surfaces a business-rule error.

## 3. Business Logic & Workflows

### 3.1. Client Registry and the Family Portal

A `Coordinator` registers a senior client with their legal `full_name`, their `mobility_aid` (one of `NONE`, `WALKER`, `FOLDING_WHEELCHAIR`, or `POWER_WHEELCHAIR`), their `assist_level_default` escort tier (`DOOR_TO_DOOR` or `DOOR_THROUGH_DOOR`), a `home_zone` label used later in driver ranking, and a free-text `address`. Registration may also set `billing_hold_limit_cents`, the overdue-receivables threshold at or above which new bookings are blocked; when omitted it defaults to 20,000 cents. A new client starts `ACTIVE` with a `credit_balance_cents` of zero and a `no_show_count` of zero. The client roster can be listed with an optional `status` filter and standard pagination, and individual clients can be fetched by any back-office role as well as by the client themselves or their family members.

Profile edits and status changes go through the OCC-guarded client patch described in §2.7: a `Coordinator` may adjust `status`, `home_zone`, `mobility_aid`, `assist_level_default`, or `billing_hold_limit_cents`, always carrying `expected_client_version`. Suspending a client (`ACTIVE` → `SUSPENDED`) fires a cascade: every ride of that client still in `SCHEDULED` or `DISPATCHING` is cancelled fee-free with `cancel_reason` recorded as `CLIENT_SUSPENDED` and `cancelled_by_role` recorded as the system, any live `OFFERED` assignments on a dispatching ride are expired with `release_reason` of `RIDE_CANCELLED`, and the client's `version` increments. Reinstatement moves the client back `SUSPENDED` → `ACTIVE`. Deactivation — permitted from either `ACTIVE` or `SUSPENDED` — is guarded: the client must have no rides in any open state (`SCHEDULED`, `DISPATCHING`, `ASSIGNED`, `EN_ROUTE`, `ARRIVED`, or `IN_SERVICE`) and no invoices in `DRAFT`, `ISSUED`, or `PARTIALLY_PAID`, otherwise the request fails with `ERR_CLIENT_HAS_OPEN_WORK`. `DEACTIVATED` is terminal for status: any attempt to move a `DEACTIVATED` client to a different status is rejected with `ERR_INVALID_REQUEST`, evaluated ahead of the version check, while edits to the other profile fields of a deactivated client remain permitted.

The family portal hangs off the client record. A `Coordinator` attaches a `FamilyMember` with the `client_id` of the senior, the member's `full_name`, a free-text `relation` (daughter, son, nephew), and an `access_level` tier of `VIEW_ONLY`, `BOOK_FOR_CLIENT`, or `BILLING_PAYER`. The optional `notify_on_ride_events` flag, defaulting to true, governs whether ride log events surface in that member's portal feed. Memberships start `ACTIVE`; revocation by a coordinator moves the member to `REVOKED`, after which every portal action fails the ownership and tier checks of §2.6, and revoking an already-`REVOKED` member succeeds as an idempotent no-op. The member list supports a reverse lookup by `client_id` and a `status` filter.

### 3.2. Driver Onboarding and Compliance

Drivers enter the platform as applicants. A `Coordinator` onboards a driver with `full_name`, `vehicle_class` (`SEDAN` or `WAV`, the wheelchair-accessible class), an `assist_certification` of `NONE`, `DOOR_TO_DOOR`, or `DOOR_THROUGH_DOOR`, a `home_zone`, and `max_daily_service_minutes`, the daily cap on forward-looking scheduled work. The record starts in `APPLICANT`. The driver list can be filtered by `status` and `vehicle_class`.

Compliance documentation is submitted per driver — by a coordinator on the driver's behalf, or by the driver personally, in which case `driver_id` must equal the caller's `X-User-ID`. Each submission names a `doc_type` (`BACKGROUND_CHECK`, `BONDING`, `INSURANCE`, or `MOTOR_VEHICLE_RECORD`), a `valid_from` first valid date, a `valid_until` last valid date forming the half-open window of §2.5, and optionally a `renewal_of_doc_id` pointing at the expired or rejected document this submission renews — the reference is validated for existence only (`ERR_NOT_FOUND` when unknown); the renewed document's type, owner, and status are not checked. A submission whose `valid_until` is not strictly after `valid_from` is rejected with `ERR_DOC_WINDOW_INVALID`. New documents start `PENDING_REVIEW`. A `ComplianceOfficer` reviews with a `decision` of `APPROVE` or `REJECT` and an optional `review_note`; the review records `reviewed_by_user_id` alongside the note, and any attempt to review a document no longer in `PENDING_REVIEW` is rejected with `ERR_DOC_ALREADY_REVIEWED`. The document list supports reverse lookups by `driver_id`, `doc_type`, `status`, and `renewal_of_doc_id`, which makes renewal chains traversable.

Lifecycle moves are posted as driver status events with an `event_type` of `ACTIVATE`, `SUSPEND`, `REINSTATE`, or `OFFBOARD` plus an optional `reason`. Activation (`APPLICANT` → `ACTIVE`) and reinstatement (`SUSPENDED` → `ACTIVE`) both require the complete compliance posture of §2.9 evaluated at the logical today; an incomplete posture is rejected with `ERR_DRIVER_COMPLIANCE_INCOMPLETE`. An event that the driver's current status does not permit — activating an `OFFBOARDED` driver, for instance — is rejected with `ERR_DRIVER_STATE_INVALID`.

Suspension is the dangerous transition because of what it does to booked work. When an `ACTIVE` driver is suspended — manually by a coordinator, or automatically when the ops cycle finds the posture newly incomplete — every `ACCEPTED` assignment of that driver whose ride still sits in `ASSIGNED` is released with `release_reason` of `DRIVER_SUSPENDED`, and each such ride returns to `DISPATCHING` with `assigned_driver_id` cleared, `dispatch_round` incremented by one, and the suspended driver appended to the ride's `excluded_driver_ids`. Outstanding `OFFERED` assignments are deliberately not expired by the cascade; they simply fail if the driver attempts to accept, rejected with `ERR_DRIVER_NOT_ELIGIBLE`. Offboarding from `ACTIVE` fires the same release cascade; offboarding an already `SUSPENDED` driver fires nothing. `OFFBOARDED` is terminal.

Two derived load metrics are computed on read against the logical date whenever a driver is fetched. `current_load_minutes` is the forward-looking figure: the sum of `estimated_duration_minutes` over the driver's rides whose pickup date is the logical today and whose status is `ASSIGNED`, `EN_ROUTE`, `ARRIVED`, or `IN_SERVICE`. `day_worked_minutes` is the chronological actuals figure: the sum of `service_minutes` over the driver's rides with pickup date today that have reached `COMPLETED`. The two intentionally diverge — one counts planned-but-unfinished work at estimated duration, the other only finished work at replayed duration.

### 3.3. Rate Cards and Pricing Foundations

A `PlatformAdmin` authors rate cards. Each card prices one `service_class` (`STANDARD` or `WAV`) over a half-open effectiveness window from `effective_from` to `effective_to`, and carries the full tariff: `hourly_rate_cents` (prorated per minute), `per_mile_cents`, `wait_per_minute_cents`, `included_wait_minutes` of per-ride wait grace, a `minimum_charge_cents` floor, the after-hours pair `after_hours_multiplier_bp` (a basis-points multiplier, so 11,000 means 1.1×) and `after_hours_start_minute` (a minute of day from 0 to 1439, so 1,080 means 18:00), and an optional flat `wav_surcharge_cents` that defaults to zero. Cards start `DRAFT`. Activation requires an internally valid window — `effective_from` strictly before `effective_to`, else `ERR_RATE_WINDOW_INVALID` — and requires that no other `ACTIVE` card of the same `service_class` have a window intersecting this one; windows that touch at a boundary do not intersect, and a true intersection is rejected with `ERR_RATE_WINDOW_OVERLAP`. Activating a card that is not `DRAFT`, or retiring a card already `RETIRED`, is rejected with `ERR_RATE_CARD_STATE_INVALID`; retirement is permitted from either `DRAFT` or `ACTIVE`. The card list can be filtered by `service_class` and `status`.

Every ride's fare — quoted or final — evaluates the same pinned formula against the **ride's rate card**: the card the ride recorded at creation. Booking requires the single `ACTIVE` card of the ride's `service_class` whose window contains the pickup date — exactly one such card must exist; its absence rejects booking with `ERR_RATE_CARD_NOT_ACTIVE` — and snapshots that card onto the ride. A series occurrence instead records the `ACTIVE` card covering its pickup date when one exists at generation time, and may carry none. Every post-booking evaluation — the final settlement at completion, the cancellation fee of §3.7, the no-show fee of §3.6, and the invoice-line rates of §3.8 — resolves the ride's recorded card first, even when that card has since been retired; a ride carrying no recorded card falls back to the `ACTIVE` card covering the pickup date, and failing that to the most recently created card of the same `service_class` covering the pickup date regardless of status. A completion that resolves a card for a ride carrying none records it then. When no card can be resolved at all, the cancellation and no-show fees are zero and completion leaves `final_fare_cents` unset. In order: first, the hourly charge is the card's `hourly_rate_cents` multiplied by the applicable minutes and divided by sixty, rounded half-up to whole cents. Second, the mileage charge is `per_mile_cents` multiplied by the applicable miles, with no rounding. Third, the wait charge is the billable wait — total wait minutes minus `included_wait_minutes`, floored at zero — multiplied by `wait_per_minute_cents`. Fourth, the subtotal is the sum of those three components. Fifth, when the pickup time-of-day (minutes after midnight UTC) is at or after `after_hours_start_minute`, the subtotal is multiplied by `after_hours_multiplier_bp` and divided by ten thousand, rounded half-up to whole cents; pickups earlier in the day skip this step. Sixth, the fare is floored at `minimum_charge_cents`; the difference between the floor and the subtotal is the minimum adjustment, zero when the floor does not bind. Seventh and last, when the ride's `service_class` is `WAV`, the card's `wav_surcharge_cents` is added.

The formula runs in two variants over the same steps. The **provisional quote**, computed at booking and stored as `quoted_fare_cents`, feeds the estimated duration and distance with zero wait. The **final settlement**, computed at completion and stored as `final_fare_cents`, feeds the replayed `service_minutes`, the driver-reported `actual_distance_miles`, and the replayed wait total. The two numbers for the same ride may therefore differ even though the formula is identical.

### 3.4. Booking One-Off Rides and Standing Series

A one-off ride is requested with the `client_id`, a `kind` of `GROCERY`, `APPOINTMENT`, or `COMPANION_OUTING`, the requested `scheduled_pickup_at` instant, planned `estimated_duration_minutes` and `estimated_distance_miles`, and the pickup's `origin_zone`. The two estimated fields must be non-negative integers; a negative value is rejected with `ERR_INVALID_REQUEST`. Two optional references shape the booking: `booked_by_family_member_id` records the portal member who booked on the senior's behalf, and `linked_return_ride_id` marks this ride as the return leg of an outbound appointment. Clients book their own rides; family members book under the tier rules of §2.6; coordinators book on anyone's behalf.

Booking walks the pipeline of §2.6, and the checks that matter most here arrive in this order. The client must be `ACTIVE` — booking for a `SUSPENDED` or `DEACTIVATED` client is rejected with `ERR_CLIENT_SUSPENDED`. This client-active gate, and the booker-attachment check below, fire before the linked ride reference is even resolved, so either rejection masks an unknown `linked_return_ride_id`. Referential integrity comes later in the pipeline: a `linked_return_ride_id` must target a ride of the **same client**, of kind `APPOINTMENT`, still `SCHEDULED`, and with no return link of its own — any mismatch is `ERR_RETURN_LINK_MISMATCH` — and a `booked_by_family_member_id` naming a member attached to a different client is `ERR_FAMILY_CLIENT_MISMATCH`. Last come the fiscal gates: an `ACTIVE` rate card must cover the derived service class at the pickup date (`ERR_RATE_CARD_NOT_ACTIVE`), and the client's overdue receivables must be below their hold limit. The **billing hold** sums, over the client's invoices in `ISSUED` or `PARTIALLY_PAID` whose `due_date` is strictly before the logical today — an invoice due today is not yet overdue — the unpaid remainder of each, and when that sum is greater than or equal to `billing_hold_limit_cents` (exactly equal triggers the hold) the booking is rejected with `ERR_BILLING_HOLD`.

A created ride snapshots the client's profile: `requires_wav` is true exactly when the client's `mobility_aid` is `POWER_WHEELCHAIR`, `service_class` is `WAV` exactly when `requires_wav` and `STANDARD` otherwise, and `assist_level` copies `assist_level_default`. The provisional quote of §3.3 lands in `quoted_fare_cents`, the ride starts `SCHEDULED` with `dispatch_round` zero and an empty `excluded_driver_ids`, and the log opens with a `CREATED` event. Ride listings expose reverse lookups by `client_id`, `assigned_driver_id`, `standing_ride_id`, `booked_by_family_member_id`, `linked_return_ride_id`, and `status`.

Recurring needs become a **standing ride series**: the same cadence fields plus a `weekday` (one of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN`), the pickup time as `pickup_time_of_day_minutes` after midnight (540 is 09:00) — an integer from 0 to 1439, out-of-range values rejected with `ERR_INVALID_REQUEST` — and an inclusive `starts_on` / `ends_on` calendar range; an `ends_on` earlier than `starts_on` is rejected with `ERR_STANDING_WINDOW_INVALID`. Series creation walks the same gates as one-off booking: the client must be `ACTIVE` (`ERR_CLIENT_SUSPENDED`), a `booked_by_family_member_id` recording the portal booker must belong to the series' client (`ERR_FAMILY_CLIENT_MISMATCH`), and the fiscal gates apply unchanged — rate-card availability for the derived class (`ERR_RATE_CARD_NOT_ACTIVE`), evaluated at the series' first upcoming cadence date (the earliest series weekday from the logical today within the inclusive range, or `starts_on` itself when no cadence date remains), and the billing-hold check (`ERR_BILLING_HOLD`). Creation immediately generates occurrences: for every calendar date matching the series weekday that falls from the logical today through the earlier of `ends_on` and fourteen days out — today included — a `SCHEDULED` ride is created with `scheduled_pickup_at` at the cadence time, the estimated fields, `kind`, and `booked_by_family_member_id` copied, and `standing_ride_id` set. Each generated occurrence snapshots the client's profile (`requires_wav`, `service_class`, `assist_level`) exactly as a one-off booking does, computes and stores the provisional quote of §3.3 when an `ACTIVE` rate card covers the occurrence date, and opens its log with a `CREATED` event. Occurrence generation is one shared routine — at creation, on resume, on a template edit, and in the ops cycle: it produces nothing while the series is not `ACTIVE` or the client is not `ACTIVE`, and it skips any cadence date already occupied by a non-`CANCELLED` ride of the series, so regeneration never duplicates an occurrence. The series' computed `next_occurrence_date` is the earliest cadence date from today forward within the inclusive range, or null when none remains.

Series are edited through the OCC-guarded template update of §2.7 carrying `expected_standing_ride_version`: any of `weekday`, `pickup_time_of_day_minutes`, `kind`, the estimated fields, `origin_zone`, `starts_on`, or `ends_on` may change; an edit attempted on an `ENDED` series is rejected with `ERR_STANDING_STATUS_INVALID`; otherwise the edit increments the series' `version`, deletes its generated rides still `SCHEDULED` with pickup dates after the logical today — removed together with their ride-event log entries — and regenerates the window from the new parameters, except that an edited `PAUSED` series regenerates nothing until resume since generation fires only while the series is `ACTIVE`; rides already `DISPATCHING` or further along are untouched. Lifecycle events posted with an `event_type` of `PAUSE`, `RESUME`, or `END` move the series `ACTIVE` → `PAUSED`, `PAUSED` → `ACTIVE`, or into terminal `ENDED` from either state; an event the current status does not permit is `ERR_STANDING_STATUS_INVALID`. Pausing cancels the series' generated rides that are `SCHEDULED` with pickup dates after the logical today, fee-free, with `cancel_reason` of `SERIES_PAUSED`. Ending cancels **all** generated rides still `SCHEDULED` regardless of date, fee-free, with `cancel_reason` of `SERIES_ENDED`. Resuming re-runs occurrence generation for the current horizon. A coordinator may run these on any series; a client may run them on their own. Series listings filter by `client_id`, `booked_by_family_member_id`, and `status`.

### 3.5. Dispatch and the Driver Selector

Dispatching is a coordinator-driven match attempt against a ride in `SCHEDULED` or `DISPATCHING`; from any other status the attempt is rejected with `ERR_RIDE_NOT_DISPATCHABLE`, and dispatching while an `OFFERED` assignment is still live for the ride is rejected with `ERR_DUPLICATE_OFFER`. An attempt rejected by either gate changes nothing. Each attempt that passes the gates moves the ride to `DISPATCHING`, increments the ride's `dispatch_round`, and then runs the selector policy.

The selector filters the driver pool to those eligible for this specific ride, requiring all of: driver status `ACTIVE`; complete compliance posture (§2.9) evaluated at the ride's scheduled pickup date; `vehicle_class` of `WAV` whenever the ride's `requires_wav` is true (any class otherwise); an `assist_certification` rank at least the ride's `assist_level` rank on the ladder `NONE` < `DOOR_TO_DOOR` < `DOOR_THROUGH_DOOR`; no buffered-window conflict with the driver's live work; headroom under the daily cap such that `current_load_minutes` plus the ride's `estimated_duration_minutes` stays at or below `max_daily_service_minutes`; and absence from the ride's `excluded_driver_ids`. The buffered window a ride occupies on a driver is the half-open interval from thirty minutes before its pickup to thirty minutes after its estimated end; two occupied windows conflict exactly when each starts strictly before the other ends, so windows that merely touch do not conflict. Only live windows count — the driver's `ACCEPTED` assignments whose rides are `ASSIGNED`, `EN_ROUTE`, `ARRIVED`, or `IN_SERVICE`; finished and cancelled work occupies nothing.

Eligible drivers are ranked deterministically: zone match first (driver `home_zone` equal to the ride's `origin_zone` outranks non-match), then `current_load_minutes` ascending, then the driver's `created_at` ascending as the final tie-break — ids are never used to break ties. A non-empty pool yields one `OFFERED` assignment stamped with `offered_at`, an `offer_expires_at` thirty minutes later, the `round` at which it was made, `matched_by` of `COORDINATOR`, and the dispatcher's identifier in `matched_by_user_id`; the ride log gains `DISPATCHED` and `OFFERED` events. An empty pool is not an error: the dispatch call returns success with `data` null, the ride is left `DISPATCHING` with the round increment applied, and neither an assignment nor log events are created.

The offered driver responds with a `decision` of `ACCEPT` or `DECLINE` and an optional `decline_reason`; responding to an assignment no longer `OFFERED` is `ERR_ASSIGNMENT_NOT_ACTIONABLE`, and the caller must be the offered driver or the response fails with `ERR_FORBIDDEN_OWNERSHIP`. Acceptance rechecks the full eligibility rule at that moment — an offer accepted late can still fail: a driver no longer `ACTIVE` or whose documents do not cover the pickup date is rejected with `ERR_DRIVER_NOT_ELIGIBLE`, a newly created buffered-window conflict with `ERR_RIDE_OVERLAP_DRIVER`, and a daily cap that no longer fits with `ERR_DRIVER_DAILY_CAP_EXCEEDED`. A clean acceptance moves the ride to `ASSIGNED`, sets `assigned_driver_id`, stamps `responded_at`, and appends an `ACCEPTED` event. Declining stamps `responded_at`, records the optional `decline_reason`, appends the driver to `excluded_driver_ids`, and logs `DECLINED` with the decline reason as the event's note, so re-offers after a decline or a timeout run the selector with the exclusion set applied.

An accepted driver may hand work back: releasing an `ACCEPTED` assignment (any other status is `ERR_ASSIGNMENT_RELEASE_INVALID`, with an optional `reason` recorded) stamps `release_reason` of `DRIVER_RELEASE` and `responded_at`, and pushes the ride through the rematch cycle — back to `DISPATCHING` with `assigned_driver_id` cleared, `dispatch_round` incremented, the releasing driver added to `excluded_driver_ids`, and a `RELEASED` event logged carrying the reason as its note. Offers also die of old age: when the ops cycle finds `offer_expires_at` at or before the logical now, the assignment moves to `EXPIRED`, the driver joins the exclusion set, and the timeout is logged as an `EXPIRED` event. Across every path — response, driver release, cancellation, suspension cascade, timeout — `responded_at` is stamped exactly when an assignment reaches `ACCEPTED`, `DECLINED`, or `RELEASED`, and is never stamped on an assignment that `EXPIRED`. Assignment listings support reverse lookup by `ride_id` and `driver_id` plus a `status` filter.

### 3.6. Trip Execution, Waiting, and No-Show Handling

Once assigned, the trip belongs to the driver, who appends execution events to their own ride — the caller's `X-User-ID` must equal the ride's `assigned_driver_id` or the append fails with `ERR_FORBIDDEN_OWNERSHIP`. Each append names an `event_type` of `EN_ROUTE`, `ARRIVED`, `WAIT_STARTED`, `WAIT_ENDED`, `SERVICE_STARTED`, `COMPLETE`, or `NO_SHOW`, with an optional free-text `note` and, at completion, the driver-reported `actual_distance_miles`. An event not permitted from the ride's current status — including any attempt to begin service or complete while a wait segment is still open — is rejected with `ERR_EXECUTION_EVENT_INVALID`.

The happy path advances `ASSIGNED` → `EN_ROUTE` → `ARRIVED` → `IN_SERVICE` → `COMPLETED`. Concretely, `EN_ROUTE` is permitted only from `ASSIGNED`, `ARRIVED` only from `EN_ROUTE`, `SERVICE_STARTED` only from `ARRIVED`, `COMPLETE` only from `IN_SERVICE`, and `NO_SHOW` only from `ARRIVED`; `WAIT_STARTED` and `WAIT_ENDED` are permitted from `ARRIVED` or `IN_SERVICE` and never change the ride's status, with opening a second segment while one is still open, or closing without an open segment, both invalid. Going en route stamps `en_route_at`; arriving stamps `arrived_at`, the instant from which the no-show grace is measured. Wait segments bookend the idle middle: the ride's `wait_minutes` starts at zero and is the sum, over closed `WAIT_STARTED`/`WAIT_ENDED` event pairs in occurrence order, of each pair's elapsed whole minutes. Billing applies the rate card's grace exactly — wait equal to `included_wait_minutes` bills zero minutes, and wait one minute above the grace bills exactly one minute. Completion requires the open-wait precondition plus a non-negative integer `actual_distance_miles` in the payload (a negative value is `ERR_INVALID_REQUEST`); it computes `service_minutes` as the whole minutes from service start to completion, finalizes `wait_minutes`, evaluates the final-settlement fare variant of §3.3 into `final_fare_cents`, and logs `COMPLETED`.

When the rider never appears, the assigned driver records `NO_SHOW` — but only once the logical now has reached fifteen minutes past `arrived_at`; an earlier attempt is `ERR_NO_SHOW_TOO_EARLY`. A recorded no-show sets `no_show_fee_cents` (zero until that moment) to the `minimum_charge_cents` of the ride's rate card as resolved in §3.3 — zero when no card resolves — increments the client's `no_show_count`, and logs `NO_SHOW_RECORDED`. The strike limit is automatic and severe: the moment a recorded no-show leaves an `ACTIVE` client's `no_show_count` at three or more, the client is suspended by the system and the full suspension cascade of §3.1 fires — future `SCHEDULED` and `DISPATCHING` rides cancelled fee-free with `cancel_reason` of `CLIENT_SUSPENDED`, their live offers expired — with the count increment and the suspension applied as two successive mutations of the client record, so the striking no-show advances the client's `version` twice. Counts below the limit carry no status effect, and a no-show recorded for a client who is not `ACTIVE` changes only the count.

Every transition above lands in the ride's event log. Each `RideEvent` records the owning `ride_id`, the `event_type` (the full vocabulary runs `CREATED`, `DISPATCHED`, `OFFERED`, `ACCEPTED`, `DECLINED`, `RELEASED`, `EN_ROUTE`, `ARRIVED`, `WAIT_STARTED`, `WAIT_ENDED`, `SERVICE_STARTED`, `COMPLETED`, `CANCELLED`, `NO_SHOW_RECORDED`, `EXPIRED`), the `actor_role`, the `actor_user_id` — the literal string `system` for automatic transitions — the logical `occurred_at` timestamp, and an optional `note`. The portal-facing log reads in `occurred_at` ascending order with `created_at` ascending breaking ties and, when both timestamps are equal, in the order the events were recorded, and whether a given family member's feed surfaces these events is governed by their `notify_on_ride_events` flag.

### 3.7. Cancellations and Tiered Fees

A ride may be cancelled by the client themselves, by a family member of that client holding `BOOK_FOR_CLIENT` or `BILLING_PAYER`, or by a coordinator, from any of `SCHEDULED`, `DISPATCHING`, `ASSIGNED`, `EN_ROUTE`, or `ARRIVED`; attempts from `IN_SERVICE`, `COMPLETED`, `CANCELLED`, or `NO_SHOW` are rejected with `ERR_RIDE_NOT_CANCELLABLE`. The caller may attach a free-text `cancel_note`; the system records `cancelled_by_role` as the caller's role and sets the enum `cancel_reason` to `CUSTOMER` for any caller-initiated cancel, appending a `CANCELLED` event that carries the note.

Caller-initiated cancels bill a tiered fee against the ride's rate card as resolved in §3.3 — zero when no card resolves. The notice is the whole minutes from the logical now to `scheduled_pickup_at`. Notice of at least a full day — 1,440 minutes — is free; exactly 1,440 is free. Notice of at least four hours — 240 minutes — but less than a full day bills half of `minimum_charge_cents`, rounded half-up to whole cents; exactly 240 lands in this half-fee tier. Anything shorter bills the full `minimum_charge_cents`; 239 minutes of notice is already a full-fee cancel. Cancels from `EN_ROUTE` or `ARRIVED` necessarily carry under four hours of notice, so they always bill the full minimum.

The assignment side effects track the state being cancelled from. Cancelling a `DISPATCHING` ride expires its live `OFFERED` assignments with `release_reason` of `RIDE_CANCELLED`. Cancelling from `ASSIGNED`, `EN_ROUTE`, or `ARRIVED` releases the `ACCEPTED` assignment with the same `RIDE_CANCELLED` reason — a driver-initiative release and a cancellation release read differently in the log — and the driver's derived load figures reflect the removal since cancelled rides occupy no window and count toward neither load metric.

System-initiated cancels are always fee-free and carry their own reasons: `CLIENT_SUSPENDED` from the suspension cascades, `SERIES_PAUSED` and `SERIES_ENDED` from series lifecycle events. For those, `cancellation_fee_cents` stays at its default of zero — which, as §3.8 shows, also keeps them off invoices.

### 3.8. Invoicing and the Client Credit Pool

Billing is period-based. A `BillingAdmin` generates an invoice for a `client_id` over the half-open period from `period_start` to `period_end`; a `period_end` not strictly after `period_start` is rejected with `ERR_INVOICE_PERIOD_INVALID`, a period intersecting any existing non-`VOIDED` invoice for that client with `ERR_INVOICE_PERIOD_OVERLAP` (touching boundaries do not intersect), and a period containing no billable work with `ERR_INVOICE_EMPTY`.

Billable work in the period is precisely: `COMPLETED` rides; `CANCELLED` rides whose `cancellation_fee_cents` is positive; and `NO_SHOW` rides — all keyed by the pickup date falling inside the half-open window. Rides still open, and fee-free cancellations, bill nothing. Each completed ride emits lines in a pinned order: a `HOURLY` line whose `quantity` is `service_minutes`; a `MILEAGE` line whose `quantity` is `actual_distance_miles`; a `WAIT` line whose `quantity` is the billable wait minutes, emitted only when the billable wait exceeds zero; a `WAV_SURCHARGE` line of quantity one only for `WAV`-class rides; and a `MINIMUM_ADJUSTMENT` line of quantity one with `unit_rate_cents` zero only when the fare floor bound above the subtotal. Every other line's `unit_rate_cents` snapshots the rate from the ride's card. Fee-bearing cancellations contribute a single `CANCELLATION_FEE` line of quantity one; no-shows a single `NO_SHOW_FEE` line of quantity one. On both fee lines, `unit_rate_cents` is the resolved card's `minimum_charge_cents` — the ride's recorded fee itself when no card resolves — and `amount_cents` is the ride's recorded fee. Each line's `amount_cents` is rounded half-up to whole cents at line level **first**, and the invoice's `charges_cents` is the plain sum of those rounded amounts — never a sum of unrounded amounts rounded once. The ordering matters in practice: two late-cancel fees each computed as half of a 2,501-cent minimum round to 1,251 cents apiece at line level, so the invoice charges 2,502 cents, not 2,501. Lines are laid down ride by ride in `scheduled_pickup_at` ascending order with `created_at` ascending breaking ties, and each `InvoiceLine` carries its `invoice_id` and `ride_id` back-references. Line listings support reverse lookup by `ride_id`, `invoice_id`, and `line_kind`.

The credit pool then applies, in a pinned order that defuses the apparent circularity. `charges_cents` is computed first from the rounded lines. `credit_applied_cents` is then the smaller of the client's current `credit_balance_cents` and half of `charges_cents` — the cap is 5,000 basis points of the pre-credit charges, taken by floor division. `total_due_cents` is the charges minus the applied credit. Generation debits the client's pool by exactly `credit_applied_cents` (skipped when zero, leaving the client row untouched), and the invoice's `due_date` is set fourteen days after `period_end`. New invoices start `DRAFT`; invoice listings filter by `client_id` and `issuance_status`.

Issuing moves the invoice `DRAFT` → `ISSUED` — from any other state the attempt is `ERR_INVOICE_NOT_ISSUABLE` — and makes it payable: it enters the payment waterfall's candidate set and, once its `due_date` passes, the overdue-receivables sum behind the billing hold. Voiding is the compensation path: a `DRAFT` or `ISSUED` invoice with `paid_cents` of zero may be voided (optionally with a `void_reason`), which moves it to `VOIDED`, credits exactly `credit_applied_cents` back into the client's pool (skipped when zero, leaving the client row untouched), and removes it from both the waterfall and the receivables sets. Voiding anything else — a partially paid, paid, or already voided invoice, or one with any money applied — is `ERR_INVOICE_NOT_VOIDABLE`. Finally, the ops cycle marks an invoice's `past_due` flag true once the logical date passes `due_date` while the invoice is `ISSUED` or `PARTIALLY_PAID`; the flag is a latch and never auto-clears.

The invoice carries **two independent state dimensions**. The issuance dimension (`issuance_status`: `DRAFT`, `ISSUED`, `PARTIALLY_PAID`, `PAID`, `VOIDED`) tracks the money; the dispute dimension (`dispute_status`: `NONE`, `DISPUTED`, `RESOLVED_ACCEPTED`, `RESOLVED_REJECTED`) tracks the disagreement, and the two evolve independently — a dispute can be raised and resolved while payments keep arriving against the issuance side.

### 3.9. Payments, Refunds, and Disputes

Money arrives as a `Payment` naming the `client_id`, a tendered `amount_cents`, and a `method` of `CARD`, `ACH`, or `CHECK`; a non-positive amount is rejected with `ERR_PAYMENT_AMOUNT_INVALID`. Billing admins take payments directly, and family members holding `BILLING_PAYER` pay on their client's behalf. The tendered amount waterfall-applies to the client's open invoices — those `ISSUED` or `PARTIALLY_PAID` with `total_due_cents` still above `paid_cents` — in `due_date` ascending order with `created_at` ascending breaking ties. Each candidate absorbs the smaller of the remaining tender and its outstanding balance; the application is recorded in the payment's `applications` array as an `invoice_id` / `applied_cents` pair in allocation order, the invoice's `paid_cents` (initially zero) grows by the applied amount, and its issuance status recomputes — `ISSUED` becomes `PARTIALLY_PAID` under a partial cover and `PAID` under a full one, with `PARTIALLY_PAID` reaching `PAID` when cumulative applications meet the total. Any remainder beyond all open invoices is credited to the client's `credit_balance_cents`. A new payment starts `SETTLED`. Payment listings filter by `client_id` and `status`.

Refunds unwind the waterfall in exactly reverse order. A billing admin refunds with an `amount_cents` and an optional `reason`, and the checks fire in a fixed order: a fully `REFUNDED` payment refuses further refunds with `ERR_PAYMENT_NOT_REFUNDABLE`; a non-positive `amount_cents` is rejected with `ERR_INVALID_REQUEST`; and the amount may not exceed the payment's `amount_cents` minus its already `refunded_cents` (else `ERR_REFUND_EXCEEDS_SETTLED`). The reversal walks the `applications` array newest-first, reversing up to the refund amount in total with a partial reversal permitted at the tail application; each reversal decrements the entry's `applied_cents` in place — an entry whose `applied_cents` reaches zero drops out of the array — decrements the target invoice's `paid_cents`, and recomputes its issuance status — `PAID` drops to `PARTIALLY_PAID` when some but not all of the total remains covered, and to `ISSUED` when coverage falls to zero. Whatever portion of the refund exceeds the reversed applications was originally a credit-pool remainder, and that credit portion may not exceed the client's current `credit_balance_cents` — a client who has already spent the credit cannot refund it, and the entire refund is rejected with `ERR_REFUND_CREDIT_SPENT`. On success the pool is debited by the credit portion, `refunded_cents` (initially zero) grows by the refund amount, and the payment moves to `PARTIALLY_REFUNDED`, or to `REFUNDED` when the cumulative refunds equal the original amount.

Disputes run on the invoice's second dimension. The endpoint gates per action ahead of loading the invoice: a `BillingAdmin` attempting `RAISE`, or a `Client` or `FamilyMember` attempting `RESOLVE_ACCEPT` or `RESOLVE_REJECT`, is rejected with `ERR_UNAUTHORIZED_ROLE`. The client themselves, or a family member holding `BILLING_PAYER` for that client, raises a dispute with an `action` of `RAISE`; raising is only meaningful against an invoice in `ISSUED` or `PARTIALLY_PAID` with dispute dimension `NONE`, and any other combination is `ERR_DISPUTE_ACTION_INVALID`. Resolution belongs to a `BillingAdmin`: `RESOLVE_ACCEPT` takes an optional `credit_cents` goodwill amount — a negative value is `ERR_INVALID_REQUEST`, and the amount defaults to zero when omitted — that may not exceed the invoice's `total_due_cents` (an excess is rejected with `ERR_INVALID_REQUEST`, evaluated before the segregation-of-duties check), posts that amount into the client's `credit_balance_cents` (skipped when zero, leaving the client row untouched), and records `resolution_credit_cents` (zero until then) and the resolver's `resolved_by_user_id`; `RESOLVE_REJECT` simply records `resolved_by_user_id`. Both resolutions require the dispute dimension to be `DISPUTED` — resolving a non-disputed invoice is again `ERR_DISPUTE_ACTION_INVALID` — and both run the segregation-of-duties check of §2.10 last, rejecting a conflicted resolver with `ERR_SOD_CONFLICT`.

### 3.10. The Ops Cycle and Logical-Clock Housekeeping

Automated bookkeeping runs as an explicit, administrator-triggered ops cycle rather than a background daemon, so tests and operators control exactly when the world ages. One cycle performs four sweeps. First, document expiry: every `APPROVED` compliance document whose `valid_until` has arrived — the half-open window has ended at the logical today — moves to `EXPIRED`, and when the owning driver is `ACTIVE` and no other approved document of the same type covers today, the posture has collapsed and the driver is auto-suspended with the full release cascade of §3.2. Second, horizon generation: standing series regenerate their occurrences within the fourteen-day window, keeping the pipeline of future `SCHEDULED` rides topped up. Third, offer timeouts: any `OFFERED` assignment whose `offer_expires_at` has been reached moves to `EXPIRED`, its driver joining the ride's `excluded_driver_ids`. Fourth, receivables aging: invoices past their `due_date` in `ISSUED` or `PARTIALLY_PAID` latch their `past_due` flag.

The cycle's response summarizes the sweep as the new `ops_epoch` together with the affected id sets — `expired_compliance_doc_ids`, `generated_ride_ids`, `expired_assignment_ids`, and `past_due_invoice_ids` — each set listing its ids in the creation order of the affected records. Time itself is operator-controlled through the test-driving capability of §2.5, which sets the logical clock to a supplied `to_iso8601` instant; every sweep above, and every window, grace, horizon, and notice computation elsewhere in this document, reads that clock.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (a client, a family member, a driver, a compliance document, a rate card, a standing series, a ride, an invoice, or a payment) return a `201 Created` status code. Operations that modify an existing resource — status events, dispatch, execution events, responds, releases, cancels, reviews, activation, retirement, issuance, voiding, dispute events, refunds, and the ops/clock capabilities — return a `200 OK` status code. The dispatch endpoint also returns `200 OK` with `data` null when the selector pool is empty, and the clock-setting capability returns `200 OK` with no resource payload.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clients` | Register a senior client | Coordinator |
| GET | `/clients/{id}` | Fetch one client | PlatformAdmin, Coordinator, BillingAdmin, Client, FamilyMember |
| GET | `/clients` | List clients with filters and pagination | PlatformAdmin, Coordinator, BillingAdmin |
| PATCH | `/clients/{id}` | Edit client profile or status; OCC-guarded | Coordinator |
| POST | `/family-members` | Attach a family member to a client | Coordinator |
| GET | `/family-members/{id}` | Fetch one family member | Coordinator, BillingAdmin, Client, FamilyMember |
| GET | `/family-members` | List family members (reverse lookup by client) | Coordinator, BillingAdmin |
| POST | `/family-members/{id}/revoke` | Revoke a family member's portal access | Coordinator |
| POST | `/drivers` | Onboard a driver (starts APPLICANT) | Coordinator |
| GET | `/drivers/{id}` | Fetch one driver including computed load metrics | PlatformAdmin, Coordinator, BillingAdmin, Driver |
| GET | `/drivers` | List drivers with filters | PlatformAdmin, Coordinator |
| POST | `/drivers/{id}/status-events` | Driver lifecycle event: ACTIVATE / SUSPEND / REINSTATE / OFFBOARD | Coordinator |
| POST | `/compliance-docs` | Submit a compliance document | Coordinator, Driver |
| GET | `/compliance-docs/{id}` | Fetch one compliance document | PlatformAdmin, Coordinator, ComplianceOfficer, Driver |
| GET | `/compliance-docs` | List compliance documents with reverse lookups | PlatformAdmin, Coordinator, ComplianceOfficer |
| POST | `/compliance-docs/{id}/review` | Review a PENDING_REVIEW document | ComplianceOfficer |
| POST | `/rate-cards` | Author a rate card (starts DRAFT) | PlatformAdmin |
| GET | `/rate-cards/{id}` | Fetch one rate card | PlatformAdmin, Coordinator, BillingAdmin |
| GET | `/rate-cards` | List rate cards | PlatformAdmin, Coordinator, BillingAdmin |
| POST | `/rate-cards/{id}/activate` | Activate a DRAFT card after window validation | PlatformAdmin |
| POST | `/rate-cards/{id}/retire` | Retire a DRAFT or ACTIVE card | PlatformAdmin |
| POST | `/standing-rides` | Create a recurring weekly ride series | Coordinator, Client, FamilyMember |
| GET | `/standing-rides/{id}` | Fetch one standing ride series | Coordinator, BillingAdmin, Client, FamilyMember |
| GET | `/standing-rides` | List standing ride series | Coordinator, BillingAdmin |
| PUT | `/standing-rides/{id}` | Edit series template; OCC-guarded; regenerates future occurrences | Coordinator |
| POST | `/standing-rides/{id}/status-events` | Series lifecycle: PAUSE / RESUME / END | Coordinator, Client |
| POST | `/rides` | Request a one-off ride | Client, FamilyMember, Coordinator |
| GET | `/rides/{id}` | Fetch one ride | Client, FamilyMember, Coordinator, Driver, BillingAdmin |
| GET | `/rides` | List rides with reverse lookups | Client, FamilyMember, Coordinator, Driver, BillingAdmin |
| POST | `/rides/{id}/cancel` | Cancel a ride; tiered fee by notice | Client, FamilyMember, Coordinator |
| POST | `/rides/{id}/dispatch` | Run the driver selector once | Coordinator |
| POST | `/rides/{id}/execution-events` | Driver appends an execution event | Driver |
| GET | `/rides/{id}/events` | Ride log for the family portal | Client, FamilyMember, Coordinator, BillingAdmin |
| GET | `/assignments/{id}` | Fetch one assignment | Coordinator, BillingAdmin, Driver |
| GET | `/assignments` | List assignments (reverse lookup by ride or driver) | Coordinator, BillingAdmin, Driver |
| POST | `/assignments/{id}/respond` | Driver responds to an offer: ACCEPT / DECLINE | Driver |
| POST | `/assignments/{id}/release` | Accepted driver releases the ride back to matching | Driver |
| POST | `/invoices/generate` | Generate a DRAFT invoice for a billing period | BillingAdmin |
| GET | `/invoices/{id}` | Fetch one invoice | BillingAdmin, Coordinator, Client, FamilyMember |
| GET | `/invoices` | List invoices | BillingAdmin, Coordinator, Client, FamilyMember |
| GET | `/invoices/{id}/lines` | List an invoice's lines in pinned emission order | BillingAdmin, Coordinator, Client, FamilyMember |
| GET | `/invoice-lines/{id}` | Fetch one invoice line | BillingAdmin, Coordinator |
| GET | `/invoice-lines` | List invoice lines with reverse lookups | BillingAdmin, Coordinator |
| POST | `/invoices/{id}/issue` | Issue a DRAFT invoice | BillingAdmin |
| POST | `/invoices/{id}/void` | Void an unpaid DRAFT/ISSUED invoice; restores applied credit | BillingAdmin |
| POST | `/invoices/{id}/dispute-events` | Dispute lifecycle: RAISE / RESOLVE_ACCEPT / RESOLVE_REJECT | BillingAdmin, Client, FamilyMember |
| POST | `/payments` | Take a payment; waterfall-applies to open invoices | FamilyMember, BillingAdmin |
| GET | `/payments/{id}` | Fetch one payment | BillingAdmin, FamilyMember, Client |
| GET | `/payments` | List payments | BillingAdmin, Coordinator |
| POST | `/payments/{id}/refund` | Refund a payment fully or partially | BillingAdmin |
| POST | `/ops/run-cycle` | Advance the ops epoch: doc expiry, occurrence generation, offer expiry, past-due marking | PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (test-driving endpoint) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_FAMILY_ACCESS_INSUFFICIENT` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CLIENT_SUSPENDED` | 409 Conflict |
| `ERR_CLIENT_HAS_OPEN_WORK` | 409 Conflict |
| `ERR_RIDE_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_RIDE_NOT_DISPATCHABLE` | 409 Conflict |
| `ERR_DUPLICATE_OFFER` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_ASSIGNMENT_RELEASE_INVALID` | 409 Conflict |
| `ERR_EXECUTION_EVENT_INVALID` | 409 Conflict |
| `ERR_DRIVER_STATE_INVALID` | 409 Conflict |
| `ERR_DRIVER_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_DRIVER_COMPLIANCE_INCOMPLETE` | 409 Conflict |
| `ERR_DRIVER_DAILY_CAP_EXCEEDED` | 409 Conflict |
| `ERR_RIDE_OVERLAP_DRIVER` | 409 Conflict |
| `ERR_NO_SHOW_TOO_EARLY` | 409 Conflict |
| `ERR_DOC_ALREADY_REVIEWED` | 409 Conflict |
| `ERR_DOC_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_RATE_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_RATE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_RATE_CARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_RATE_CARD_STATE_INVALID` | 409 Conflict |
| `ERR_STANDING_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_STANDING_STATUS_INVALID` | 409 Conflict |
| `ERR_INVOICE_PERIOD_INVALID` | 422 Unprocessable Entity |
| `ERR_INVOICE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_INVOICE_EMPTY` | 422 Unprocessable Entity |
| `ERR_INVOICE_NOT_ISSUABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_VOIDABLE` | 409 Conflict |
| `ERR_DISPUTE_ACTION_INVALID` | 409 Conflict |
| `ERR_PAYMENT_AMOUNT_INVALID` | 422 Unprocessable Entity |
| `ERR_PAYMENT_NOT_REFUNDABLE` | 409 Conflict |
| `ERR_REFUND_EXCEEDS_SETTLED` | 422 Unprocessable Entity |
| `ERR_REFUND_CREDIT_SPENT` | 409 Conflict |
| `ERR_RETURN_LINK_MISMATCH` | 409 Conflict |
| `ERR_FAMILY_CLIENT_MISMATCH` | 409 Conflict |
| `ERR_BILLING_HOLD` | 402 Payment Required |
| `ERR_SOD_CONFLICT` | 403 Forbidden |
