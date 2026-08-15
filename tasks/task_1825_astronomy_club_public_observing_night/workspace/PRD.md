# Astronomy Club Observing API — Product Requirements Document

## 1. Introduction

Amateur astronomy clubs run on volunteer labor, shared equipment, and a hard dependency on the sky itself. The club behind this API operates an observatory that hosts public nights, members-only observing sessions, and occasional daytime solar programs. It loans telescopes to trained members, books school and scout groups onto public events, tracks sky-quality measurements for dark-sky advocacy, and collects annual dues that gate every privilege the club offers. Until now these concerns have been managed in spreadsheets and email threads, which means missed suspensions, double-booked loaners, public nights confirmed against a full moon, and no reliable record of who is certified to operate which class of instrument.

This document specifies a single REST API, mounted under `/club`, that consolidates those concerns into one system of record. It governs membership tiers and dues billing with automatic standing transitions; a telescope fleet with collimation scheduling and a condition ledger; a loan program with certification gating and late-fee accrual; an event pipeline that moves an observing night from draft through confirmation to completion, with weather and moon-phase gates along the way; a volunteer-operator staffing workflow whose coverage shortfalls cascade back onto the host event; group visits with capacity accounting and a graduated deposit schedule; and a dark-sky measurement program that freezes a median sky brightness and a letter grade for advocacy use. A logical, server-held clock drives every time-based transition so that dues suspension, certification expiry, and loan lateness are deterministic and testable rather than dependent on wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting rules that apply uniformly to every resource and endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which that user acts. The system recognizes exactly four roles: `ClubOfficer`, `Member`, `EventCoordinator`, and `EquipmentChair`. A request that omits either header, or that names a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` differs by role and is contractually fixed. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` entity; any ownership check on a resource that references a `Member` — a loan reservation's `member_id`, an assignment's `member_id`, a booking's `contact_member_id`, a payment's `member_id`, a reading's `taken_by_member_id` — compares that foreign-key field to `X-User-ID`. When `X-User-Role` is `ClubOfficer`, `EventCoordinator`, or `EquipmentChair`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to an entity's `id`.

The `ClubOfficer` role is the administrative superset for membership, dues, tiers, dark-sky reporting, and the logical clock, and additionally shares every read endpoint plus payment posting and member resignation. `Member` acts on its own loans, bookings, operator assignments, sky-quality readings, and dues payments. `EventCoordinator` owns the observing-event lifecycle, operator invitations, and group-booking confirmation. `EquipmentChair` owns the telescope registry, maintenance tickets, training certifications, and the loan checkout/return desk. The exact endpoint-to-role mapping is given in §4; the scattered rules in §3 name the acting role for every workflow.

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

List endpoints are paginated via two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. List responses are always sorted by `created_at` in ascending order unless explicitly stated otherwise.

Every paginated list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, so clients can page deterministically through the collection.

### 2.4. The Logical Clock and Time-Driven Automation

All time-based behavior in the system is governed by a single server-held **logical clock**, not by wall-clock time. At process startup the logical clock reads exactly `2026-08-01T00:00:00Z`; before any explicit set call it remains pinned at that default and never silently falls back to the host's clock. A `ClubOfficer`-restricted administrative capability advances the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`.

Advancing the clock is the single trigger for every automatic transition in the system. When the new clock satisfies a time-based precondition, the server fires the corresponding transition without requiring any client request against the affected resource: members whose dues standing has expired move from `ACTIVE` to `SUSPENDED` and later to `LAPSED`, active certifications whose `expires_at` has been reached move to `EXPIRED`, and checked-out loans whose window has closed move from `CHECKED_OUT` to `OVERDUE`. These automatic firings cascade exactly as their manually-triggered counterparts do — a suspension still cancels that member's `RESERVED` loans and withdraws their pending operator assignments — so the observable state of the system after a clock advance is identical to the state a sequence of manual transitions would have produced.

### 2.5. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields unless noted otherwise:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, stamped at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at 1 and increments by exactly 1 on every mutation, including mutations driven by cascades and recomputes.

Two entity families are exceptions to this pattern. A `DuesPayment` and a `SkyQualityReading` are append-only records: they carry only `id` and `created_at` — neither `updated_at` nor `version` exists on these resources. Any rule that recomputes a derived field (for example `Member.dues_paid_through`, `Telescope.condition_score`, or `ObservingEvent.confirmed_operator_count`) is a mutation of the owning entity and therefore refreshes its `updated_at` and bumps its `version`, even though the recomputed field itself is read-only to clients.

### 2.6. Nested Resource Retrieval and Referential Existence

Requests that address nested resources validate path identifiers strictly left to right. The first path identifier that does not resolve to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404) before any later identifier or business rule is consulted. The same `ERR_NOT_FOUND` applies to identifiers supplied in the request body of create and update operations: a payload naming a `member_id`, `telescope_id`, `event_id`, `tier_id`, `invoice_id`, or `contact_member_id` that does not resolve is rejected before any state or temporal rule runs. Existence checking therefore precedes every domain rule in this document; when several rules could reject a request, the ordering rules of §2.10 and the priority statements in §3 determine which error surfaces.

### 2.7. Monetary Values, Precision, and Rounding

All money in the system is represented as integer cents. Dues, deposits, late fees, and payments never carry fractional cents. Where a calculation produces a non-integer intermediate — the pro-rated dues computation is the only such case — the final result is rounded **once**, at the end of the computation, using the round-half-up rule to the nearest integer cent. Per-period partial rounding followed by summation is a different, forbidden interpretation: the rounding happens after the full unrounded rational value has been computed, not on any intermediate per-month or per-day slice.

Sky-brightness readings are decimal numbers (magnitudes per square arcsecond) with exactly two decimal places of precision; the only arithmetic ever performed on them is a two-element average inside the median computation, which is itself rounded half-up to two decimal places. Counts — operator coverage, no-show strikes, reading counts, condition scores — are integers throughout.

### 2.8. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control; all other writes take no version field at all.

Confirming an observing event requires the request to carry `expected_event_version`, the value of the event's `version` the client last observed. Because operator acceptances and withdrawals recompute `confirmed_operator_count` and thereby bump the event's `version` whenever coverage changes, a client that read the event before those changes holds a stale snapshot. If `expected_event_version` does not match the event's current `version`, the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412).

Updating a telescope's descriptive fields requires the request to carry `expected_telescope_version`, the value of the telescope's `version` the client last observed. Reservation, checkout, and return cascades all bump the telescope's `version` on every status change, so a descriptive edit made from a superseded snapshot is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently overwriting a fresher state.

### 2.9. Temporal Windows: Half-Open and Closed-Touch Semantics

Two different interval conventions appear in the system, and the distinction is contractual.

Loan windows, event windows, invoice coverage periods, and dark-sky report periods are all **half-open** intervals: the start is inclusive and the end is exclusive. For loan scheduling this means a new reservation whose `window_start` equals an existing reservation's `window_end` does **not** intersect it — touching windows are legal for the same borrower. For dark-sky reports it means a reading whose `taken_at` falls exactly on `period_end` belongs to the next report, not this one. Window sanity itself requires the start to be strictly before the end: a request whose `window_start` is not strictly earlier than `window_end`, or whose `period_start` is not strictly earlier than `period_end`, is rejected with `ERR_INVALID_WINDOW` (HTTP 422). This check applies to loan reservation creation, observing event creation, dark-sky report creation, and dues invoice issuance.

Operator-overlap checking for staffing uses the opposite convention. When a member accepts an operator assignment, the host event's window is compared against the windows of that member's other confirmed assignments using **closed-interval** semantics: a touch at exactly `window_end == window_start` counts as an overlap, because operators need teardown time between events. A conflicting acceptance is rejected with `ERR_OPERATOR_OVERLAP` (HTTP 409).

### 2.10. Validation Ordering

Every endpoint applies the same ordered cascade of checks, and the order is part of the contract because later checks are masked by earlier failures. The order is: (1) authentication headers — `ERR_UNAUTHENTICATED`; (2) role authorization — `ERR_FORBIDDEN`; (3) path-identifier existence, left to right — `ERR_NOT_FOUND`; (4) body-referenced identifier existence — `ERR_NOT_FOUND`; (5) request shape — required fields present, types correct, enums within their declared sets, and numeric ranges honored, any failure producing `ERR_INVALID_REQUEST`; (6) state-machine legality — the target resource is in a state from which the requested transition exists, otherwise `ERR_INVALID_STATE`; and only then (7+) the business rules in their domain-specific order, which §3 states explicitly wherever several business rules guard the same endpoint.

### 2.11. Domain Enumerations

The following enumerations are contractually fixed and appear verbatim throughout this document. Membership tiers are coded `STUDENT`, `INDIVIDUAL`, `FAMILY`, or `PATRON`. A member's lifecycle status is one of `ACTIVE`, `SUSPENDED`, `LAPSED`, `RESIGNED`. An invoice is `OPEN`, `PAID`, or `VOID`. Telescopes and certifications share an equipment-class enumeration: `REFRACTOR`, `REFLECTOR`, `SCT`, `DOBSONIAN`, `SOLAR_SCOPE`. A telescope's status is `AVAILABLE`, `RESERVED`, `ON_LOAN`, `MAINTENANCE`, or `RETIRED`. A certification's status is `ACTIVE`, `EXPIRED`, or `REVOKED`. A loan reservation moves among `RESERVED`, `CHECKED_OUT`, `RETURNED`, `OVERDUE`, `CANCELLED`. A maintenance ticket is `OPEN`, `IN_PROGRESS`, `VERIFICATION`, or `CLOSED`, with a `kind` of `COLLIMATION`, `REPAIR`, or `CLEANING` and a `severity` of `LOW`, `MEDIUM`, or `HIGH`. An observing event's `event_kind` is `PUBLIC_NIGHT`, `MEMBER_NIGHT`, or `SOLAR_SESSION`, and its lifecycle status is `DRAFT`, `SCHEDULED`, `CONFIRMED`, `CANCELLED`, or `COMPLETED`; a cancelled event records a `cancellation_reason` of `WEATHER`, `LOW_COVERAGE`, `MOON`, or `OTHER`. An operator assignment is `INVITED`, `CONFIRMED`, `DECLINED`, `NO_SHOW`, or `WITHDRAWN`. A group visit booking is `PENDING`, `CONFIRMED`, `CANCELLED`, `COMPLETED`, or `NO_SHOW`. A dark-sky report is `OPEN` or `FINALIZED`, and its `advocacy_grade` is one of the letters `A`, `B`, `C`, `D`, or `F`.

## 3. Business Logic & Workflows

### 3.1. Membership Tiers, Registration, and Dues Standing

A `ClubOfficer` defines the club's membership tiers. Each tier is created with a `code` drawn from `STUDENT`, `INDIVIDUAL`, `FAMILY`, or `PATRON`; an `annual_dues_cents` price in integer cents; an `observatory_access_level` from 1 to 3 — where 1 admits the member to public nights only, 2 additionally admits member nights, and 3 confers unaccompanied keyholder status; a boolean `loan_privilege` indicating whether the tier confers telescope-loan eligibility; and a `max_concurrent_loans` cap on how many non-terminal loan reservations a member of the tier may hold at once.

A `ClubOfficer` registers a new member by supplying `full_name`, `email`, and the `tier_id` of the chosen tier. The `email` must be unique across members. The server stamps `joined_at` at registration, initializes `status` to `ACTIVE`, and initializes `dues_paid_through` to exactly `joined_at` — that is, joined plus zero days — so a brand-new member's first invoice is due immediately even though the account is technically in good standing. Two read-only derivatives follow the member everywhere: `effective_access_level` equals the tier's `observatory_access_level` while the member is `ACTIVE` and is 0 in every other status, and `no_show_strikes` counts the member's no-show marks within a rolling 365-day window (see §3.7).

Dues are billed through invoices and settled through payments. Issuing an invoice names the `member_id` and a half-open coverage period from `period_start` (inclusive) to `period_end` (exclusive); the window-sanity rule requires `period_start` strictly before `period_end`. The invoice's `amount_cents` is computed at issuance and is read-only thereafter. When the invoice covers a full membership year — that is, the day count from `period_start` to `period_end` equals exactly 365 — the charged `amount_cents` is the tier's `annual_dues_cents` exactly, with no proration arithmetic performed. For any other day count — the mid-year-join case — the charged amount is the tier's `annual_dues_cents` multiplied by the day count of the invoice period and divided by 365, with the resulting rational rounded half-up to integer cents in a single final rounding. The two variants can differ from a naive per-month-rounding interpretation by whole cents; the per-month interpretation is wrong.

Settling an invoice is done by posting a payment that names the `invoice_id`, the paying `member_id`, and the tendered `amount_cents`. The payment's `member_id` must match the invoice's member. A payment suffices only if the tendered amount plus any previously accrued member credit covers the invoice's `amount_cents` in full; otherwise the posting is rejected with `ERR_PAYMENT_INSUFFICIENT` (HTTP 422). When coverage is complete, the invoice moves `OPEN → PAID`, and the member's `dues_paid_through` recomputes to the later of its current value and the invoice's `period_end`. Overpayment is not lost: the excess becomes member credit, and each later settlement records in its own `credit_applied_cents` how much of a prior overpayment it consumed. The server stamps each payment's `posted_at` at posting time. A `ClubOfficer` may also void an `OPEN` invoice, moving it `OPEN → VOID`; voiding carries no financial side effects.

Dues standing drives the membership lifecycle automatically. When the logical clock reaches `dues_paid_through` plus a grace period of 7 days while the member is `ACTIVE`, the member transitions `ACTIVE → SUSPENDED`; the boundary is inclusive, so exactly at `dues_paid_through` plus 7 days the member is suspended, and one second earlier they are still active. Suspension recomputes `effective_access_level` to 0, cancels every loan reservation the member holds in `RESERVED` status (each releasing its telescope per the cascade of §3.3), and withdraws every operator assignment the member holds in `INVITED` or `CONFIRMED` status (each recomputing the host event's coverage per §3.6). When the logical clock reaches `dues_paid_through` plus a lapse period of 37 days while the member is `ACTIVE` or `SUSPENDED`, the member transitions to `LAPSED` with `effective_access_level` recomputed to 0; from `ACTIVE` this fires on the same 37-day threshold, and from `SUSPENDED` the same threshold applies with no additional preconditions.

Recovery paths exist from both degraded states. A `ClubOfficer` may reinstate a member `SUSPENDED → ACTIVE`, but only while the logical clock is still earlier than the member's `dues_paid_through` — which in practice means a payment posted while the member was suspended has already pushed `dues_paid_through` forward past the current instant. Reinstatement recomputes `effective_access_level` back to the tier's `observatory_access_level`. A `LAPSED` member is revived differently: when a posted payment settles an `OPEN` invoice whose `period_end` lies strictly after the logical clock, the member moves `LAPSED → ACTIVE` as a side effect of the payment, recomputing both `dues_paid_through` and `effective_access_level`. A member (or a `ClubOfficer` on their behalf) may resign from either `ACTIVE` or `SUSPENDED`, moving to the terminal `RESIGNED` state. Resignation is blocked while the member holds any loan in `CHECKED_OUT` or `OVERDUE` status — the attempt is rejected with `ERR_LOANS_OUTSTANDING` (HTTP 422). Resigning from `ACTIVE` additionally cancels the member's `RESERVED` loans and withdraws the member's `INVITED` and `CONFIRMED` assignments, mirroring the suspension cascade; resigning from `SUSPENDED` carries no further cascades because suspension already applied them.

### 3.2. The Telescope Fleet: Registry, Condition, and Collimation

The `EquipmentChair` maintains the club's telescope registry. Registering a telescope requires a display `name` and an `equipment_class` drawn from the shared class enumeration. A new telescope starts in `AVAILABLE` status with a read-only `condition_score` of 100 and a read-only `collimation_due_at` initialized to its `created_at` plus 180 days — new inventory is assumed freshly collimated.

Condition is a ledger, not a counter. Every maintenance ticket carries a signed `condition_delta`, and a telescope's `condition_score` is recomputed on every ticket close as 100 plus the sum of `condition_delta` across **all** of that telescope's tickets in `CLOSED` status, floored at 0 — that is, if the sum would push the score below 0, the score is 0. The recompute is a full reconciliation over the closed set on every close, which makes it commutative and idempotent: a ticket's delta applies exactly once no matter how many times the ticket cycled between in-progress and verification before closing. When the closed ticket's `kind` is `COLLIMATION`, the close additionally resets the telescope's `collimation_due_at` to the logical clock plus 180 days.

The descriptive fields of a telescope — currently just `name` — can be updated by the `EquipmentChair`. That update is one of the two OCC-guarded writes in the system: the request must carry `expected_telescope_version` matching the telescope's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) as described in §2.8. A successful update bumps the telescope's `version` by 1.

A telescope leaves service through retirement. From `AVAILABLE`, retirement requires that no loan reservation for this telescope exists in `RESERVED`, `CHECKED_OUT`, or `OVERDUE` status. From `MAINTENANCE`, retirement is the write-off path for equipment damaged beyond repair: it requires only that no reservation is `CHECKED_OUT` or `OVERDUE`, and as a side effect every non-`CLOSED` maintenance ticket for the telescope is forced to `CLOSED` with its `condition_delta` applied through the normal condition recompute. Retirement is terminal in both cases.

### 3.3. Maintenance Tickets and the Repair Cycle

A maintenance ticket is opened by the `EquipmentChair` with a `telescope_id`, a `kind` of `COLLIMATION`, `REPAIR`, or `CLEANING`, a `severity` of `LOW`, `MEDIUM`, or `HIGH`, and the signed `condition_delta` that will be applied to the telescope's condition when the ticket eventually closes. Opening a ticket against an `AVAILABLE` telescope moves the telescope `AVAILABLE → MAINTENANCE`; opening one against a telescope already in `MAINTENANCE` leaves the status unchanged. The server stamps `opened_at` at creation and `closed_at` when the ticket finally closes.

The ticket workflow is a small cycle. Starting work moves `OPEN → IN_PROGRESS`; submitting the work for verification moves `IN_PROGRESS → VERIFICATION`; a failed verification reopens the ticket `VERIFICATION → IN_PROGRESS` so work continues; and a passed verification closes it `VERIFICATION → CLOSED`. Closing recomputes the telescope's `condition_score` across the full closed set as described in §3.2 and, when no other non-`CLOSED` ticket remains for that telescope, returns the telescope `MAINTENANCE → AVAILABLE`. Collimation discipline is enforced not only by this cycle but at the loan desk: a telescope whose `collimation_due_at` is not strictly later than the logical clock cannot be reserved (§3.4), so an overdue-for-collimation instrument effectively self-grounds until a `COLLIMATION` ticket runs to completion.

### 3.4. The Telescope Loan Program

The loan program lets eligible members reserve telescopes for half-open windows. Creating a reservation names the borrowing `member_id`, the `telescope_id`, and the window from `window_start` (inclusive) to `window_end` (exclusive). Creation is guarded by an ordered battery of business checks; they are evaluated in this order so that the listed error surfaces rather than a later one masking it.

First, the certification gate: the member must hold a certification in `ACTIVE` status for the reserved telescope's `equipment_class`; otherwise the creation is rejected with `ERR_CERTIFICATION_REQUIRED` (HTTP 422). Second, the standing gate: the member's `status` must be `ACTIVE` and the member's tier must have `loan_privilege` true; otherwise the rejection is `ERR_MEMBER_NOT_IN_GOOD_STANDING` (HTTP 422). Third, telescope reservability: the telescope must be in `AVAILABLE` status and its `collimation_due_at` must be strictly later than the logical clock; a telescope that is reserved, on loan, under maintenance, or due for collimation is rejected with `ERR_TELESCOPE_NOT_RESERVABLE` (HTTP 409). Fourth, the borrower's own schedule: the new window must not intersect any non-terminal reservation of the **same member**, regardless of which telescope is involved — a borrower cannot be responsible for two kits over one night. Because loan windows are half-open, a new window whose `window_start` equals an existing window's `window_end` does not intersect it; otherwise a conflict is rejected with `ERR_LOAN_WINDOW_CONFLICT` (HTTP 409). Telescope-level double booking needs no separate rule: a telescope with a live reservation is `RESERVED` or `ON_LOAN`, never `AVAILABLE`, so the third check already excludes it. Fifth and last, the tier's concurrency cap: the count of the member's non-terminal reservations — those in `RESERVED`, `CHECKED_OUT`, or `OVERDUE` — must be strictly below the tier's `max_concurrent_loans` before another is created; at or over the cap the creation is rejected with `ERR_LOAN_CAP_REACHED` (HTTP 422).

A successful creation moves the named telescope `AVAILABLE → RESERVED` and the reservation begins in `RESERVED`. Checkout, performed by the `EquipmentChair`, moves the reservation `RESERVED → CHECKED_OUT` and simultaneously moves the telescope `RESERVED → ON_LOAN`, stamping `checkout_at` with the logical clock. Checkout is only legal while the logical clock is at or after `window_start` and strictly before `window_end`, and while the member is still `ACTIVE`.

If the logical clock reaches `window_end` while the reservation is still `CHECKED_OUT`, the reservation automatically becomes `OVERDUE`, and late fees begin accruing. The fee computation distinguishes provisional from final reads. While the loan remains `OVERDUE`, reading it returns a provisional `overdue_fees_cents` computed against the logical clock — the value keeps growing and is never persisted. On return, the fee is finalized against `returned_at` and persisted. In both variants the formula is the same: the number of whole days late is the day count from `window_end` to the reference instant (the logical clock provisionally, `returned_at` at finalization), floored at zero; the first 2 days are free, so the billable day count is the days late minus 2, again floored at zero; the fee is the billable days multiplied by 500 cents. The boundary is inclusive in the natural direction: exactly 2 days late yields zero fee, and 3 days late yields exactly 500 cents. The final variant then applies a cap of 10000 cents; the provisional variant is uncapped so that a member reading the loan sees the true exposure.

Return, performed by the `EquipmentChair`, accepts an optional `damage_reported` flag. From either `CHECKED_OUT` or `OVERDUE`, the reservation moves to the terminal `RETURNED` state and the server stamps `returned_at`. Without damage reported, the telescope returns `ON_LOAN → AVAILABLE`. With `damage_reported` true, the telescope instead moves `ON_LOAN → MAINTENANCE` and a maintenance ticket is opened against it automatically. A `RESERVED` reservation can instead be cancelled — by the borrowing `Member`, by a `ClubOfficer` via the member's lifecycle cascades, or by the `EquipmentChair` directly — moving it `RESERVED → CANCELLED` and releasing the telescope `RESERVED → AVAILABLE`. Certification revocation also cancels: when the `EquipmentChair` revokes a certification, every reservation in `RESERVED` status whose telescope's `equipment_class` matches the revoked class moves to `CANCELLED`, releasing those telescopes in turn.

### 3.5. Training and Certification

The `EquipmentChair` issues training certifications naming the `member_id`, the certified `equipment_class`, and the `expires_at` instant after which the certification is unusable. The server stamps `issued_at` at issuance and the certification begins in `ACTIVE`. Two exits exist: when the logical clock reaches `expires_at`, the certification automatically moves `ACTIVE → EXPIRED`; and the `EquipmentChair` may revoke at any time while the certification is `ACTIVE`, moving it `ACTIVE → REVOKED`. Revocation carries the cascade described in §3.4: any of that member's reservations still in `RESERVED` whose telescope's `equipment_class` matches the revoked certification's class are cancelled and their telescopes released. A certification is usable for gating only while `ACTIVE` and only strictly before `expires_at` — at or after `expires_at` it confers nothing, which is exactly what the expiry transition records.

### 3.6. Observing Events: Scheduling, Coverage, Weather, and Completion

An `EventCoordinator` drafts an observing event with a `title`, an `event_kind` of `PUBLIC_NIGHT`, `MEMBER_NIGHT`, or `SOLAR_SESSION`, a half-open window from `window_start` to `window_end`, an expected `moon_illumination_pct` between 0 and 100 for the event night, and a `min_operators` coverage requirement of at least 1. The event begins in `DRAFT` with `weather_cancellation_pct` initialized to 0; `weather_cancellation_pct` is thereafter maintained only through the weather-check capability, which records the latest forecast cancellation probability (0 to 100) onto the event. The read-only `confirmed_operator_count` tracks how many of the event's operator assignments currently sit in `CONFIRMED`.

Scheduling moves `DRAFT → SCHEDULED` and applies two kind-specific gates. For a `PUBLIC_NIGHT`, the moon must cooperate: `moon_illumination_pct` of at most 40 is required, and anything brighter is rejected with `ERR_MOON_TOO_BRIGHT` (HTTP 422). For a `SOLAR_SESSION`, the window must lie entirely within civil daylight for the observatory site: the server consults a fixed daylight table in which every date's civil daylight runs from 06:00Z inclusive to 20:00Z exclusive of the same UTC date, so the event's `window_start` must be at or after 06:00Z and its `window_end` at or before 20:00Z of that date; a window straying outside is rejected with `ERR_NOT_DAYLIGHT_WINDOW` (HTTP 422). A scheduled event can be sent back for replanning, moving `SCHEDULED → DRAFT` with no side effects.

Confirmation moves `SCHEDULED → CONFIRMED` and is the second OCC-guarded write in the system: the request must carry `expected_event_version` matching the event's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). The business gates behind confirmation are evaluated in a fixed order. First, operator coverage: `confirmed_operator_count` must be at least `min_operators` — exactly meeting the minimum passes, one short fails with `ERR_INSUFFICIENT_OPERATORS` (HTTP 422). Second, weather: the latest `weather_cancellation_pct` must be strictly below 70; at 70 or above the confirm is rejected with `ERR_WEATHER_RISK` (HTTP 422). Third, solar safety: for a `SOLAR_SESSION` only, at least one operator whose assignment is `CONFIRMED` on the event must hold an `ACTIVE` certification in `SOLAR_SCOPE`; without one the confirm is rejected with `ERR_NO_SOLAR_CERTIFIED_OPERATOR` (HTTP 422). A successful confirm bumps the event's `version` by 1.

Weather can also kill a confirmed event directly: when a weather-check records a `weather_cancellation_pct` of 70 or higher on an event that is currently `CONFIRMED`, the event auto-cancels with `cancellation_reason` `WEATHER`, applying the same cascades as a manual cancellation.

Cancellation from `SCHEDULED` or `CONFIRMED` requires the coordinator to supply a `cancellation_reason` of `WEATHER`, `LOW_COVERAGE`, `MOON`, or `OTHER`. Cancelling from `SCHEDULED` withdraws every operator assignment of the event in `INVITED` or `CONFIRMED` (moving each to `WITHDRAWN`) and cancels every group booking of the event in `PENDING` or `CONFIRMED`. Cancelling from `CONFIRMED` withdraws the same assignments and cancels only the `CONFIRMED` group bookings, annotating each with a deposit refund note. In both cases the event's `cancellation_reason` is recorded on the event itself.

Coverage can also lapse underneath a confirmed event. Whenever a `CONFIRMED` operator assignment is withdrawn or marked no-show such that the recomputed `confirmed_operator_count` falls below `min_operators`, the host event automatically falls back `CONFIRMED → SCHEDULED`; this is the intended serialization point between staffing churn and event status, and it is why the confirm path is version-guarded.

After the window closes — that is, once the logical clock is at or after `window_end` — the coordinator completes the event, moving `CONFIRMED → COMPLETED`. Completion cascades to group bookings: every booking in `CONFIRMED` moves to `COMPLETED`. Operator assignments in `CONFIRMED` remain `CONFIRMED` at completion; attendance is recorded separately through the no-show marking described next.

### 3.7. Staffing Public Nights: Operator Assignments and No-Show Strikes

The `EventCoordinator` staffs an event by inviting members, creating an operator assignment that names the `event_id`, the `member_id` of the volunteer, and the `telescope_id` the operator will run. The assignment begins in `INVITED` with the server stamping `invited_at`.

Only the invited `Member` may respond. Accepting moves `INVITED → CONFIRMED` and is guarded by three checks beyond the actor-owns-assignment rule: the member's `status` must be `ACTIVE` (otherwise `ERR_MEMBER_NOT_IN_GOOD_STANDING`, HTTP 422); the member must hold an `ACTIVE` certification for the assigned telescope's `equipment_class` (otherwise `ERR_CERTIFICATION_REQUIRED`, HTTP 422); and the member must not already hold another `CONFIRMED` assignment whose host event window overlaps this one. That overlap check uses closed-interval semantics per §2.9 — a touch at exactly `window_end == window_start` counts as overlap — and a conflict is rejected with `ERR_OPERATOR_OVERLAP` (HTTP 409). A successful accept recomputes the host event's `confirmed_operator_count` over the event's `CONFIRMED` assignments only — `INVITED`, `DECLINED`, `NO_SHOW`, and `WITHDRAWN` never count — and bumps the event's `version`, which is precisely why a stale `expected_event_version` on a later confirm surfaces as `ERR_STALE_VERSION`.

Declining moves `INVITED → DECLINED` with no side effects. Withdrawing moves `CONFIRMED → WITHDRAWN`, recomputes the host's coverage, and — when the host was `CONFIRMED` and coverage drops below `min_operators` — knocks the host back `CONFIRMED → SCHEDULED` per §3.6. After the host event has completed, the `EventCoordinator` may mark a still-`CONFIRMED` assignment as `NO_SHOW`; the marking recomputes both the member's `no_show_strikes` and the host's `confirmed_operator_count`, since a `NO_SHOW` no longer counts as coverage.

No-show strikes are computed over a rolling window: the member's no-show marks — from operator assignments marked `NO_SHOW` and from group bookings marked `NO_SHOW` — are ordered by the server-stamped mark instant ascending, ties broken by the marked entity's `created_at` ascending; the window opens at the logical clock minus 365 days, and a strike counts while its mark instant is at or after that window start. A strike exactly 365 days old today still counts; once the clock passes the mark instant plus 365 days it drops off. The throttle that consumes this count lives in §3.8.

### 3.8. Group Visits: Booking, Capacity, and Deposits

A `Member` books a group visit onto a host event, naming the `event_id`, a `group_name` for the school or organization, a `party_size` of at least 1, and the sponsoring `contact_member_id`. Group visits attach only to `PUBLIC_NIGHT` events. Two creation-time gates run in order. First the standing gate: the contact member must be `ACTIVE`, else `ERR_MEMBER_NOT_IN_GOOD_STANDING` (HTTP 422). Second the no-show throttle: a contact member whose `no_show_strikes` has reached 2 within the rolling 365-day window may not create further bookings — the attempt is rejected with `ERR_NO_SHOW_THROTTLED` (HTTP 422).

The booking's `deposit_cents` is computed at creation and is read-only thereafter. The deposit is tiered by party size with **marginal** allocation across tiers: the first 10 attendees are free (0 cents each); attendees 11 through 30 are charged 1000 cents each; every attendee beyond 30 is charged 2000 cents each. Marginal means a party of 31 pays 0 for the first ten plus 20000 for the next twenty plus 2000 for the thirty-first, totaling 22000 cents — not 62000 cents as a flat-rate misreading would produce.

A new booking starts in `PENDING`. The `EventCoordinator` confirms it, moving `PENDING → CONFIRMED`, only while the host event is `SCHEDULED` or `CONFIRMED`, and only while aggregate capacity holds: the sum of `party_size` across the event's already-`CONFIRMED` bookings plus this booking's `party_size` must not exceed 60 attendees per event; exceeding it is rejected with `ERR_EVENT_GROUP_CAPACITY` (HTTP 422). Cancellation moves either `PENDING` or `CONFIRMED` to `CANCELLED`; from `PENDING` the acting member must be the booking's `contact_member_id` or an `EventCoordinator`, and from `CONFIRMED` the same actors may cancel, with event-level cancellation cascading bookings to `CANCELLED` as described in §3.6. Completion of the host event cascades `CONFIRMED` bookings to `COMPLETED`. After the host has completed, the coordinator may instead mark a `CONFIRMED` booking `NO_SHOW`, which recomputes the contact member's `no_show_strikes` per §3.7.

### 3.9. Sky-Quality Measurement and Dark-Sky Reporting

The club's light-pollution advocacy runs on Sky Quality Meter readings. Any `Member` may record a reading taken during an event, supplying the `taken_by_member_id`, the `event_id` during which it was taken, and the `sqm_value` — a decimal magnitudes-per-square-arcsecond figure that must lie between 10.00 and 22.99 inclusive; the server stamps `taken_at` at recording time. Readings are append-only: they carry no `updated_at` and no `version`.

A `ClubOfficer` opens a dark-sky report over a half-open period from `period_start` to `period_end`; the window-sanity rule requires the start strictly before the end. The report begins `OPEN` and immediately sweeps in every reading whose `taken_at` falls within the half-open window — a reading exactly at `period_end` belongs to the next report. The report's read-only `reading_count` reflects how many readings have been swept in. While `OPEN`, the report's `median_sqm` is provisional: it is recomputed on every newly recorded reading that falls inside the window, and the `advocacy_grade` recomputes alongside it.

The median is computed by sorting the swept readings' `sqm_value`s ascending. If no readings exist in the window, `median_sqm` is null. For an odd count, the median is the middle element of the sorted list. For an even count, the median is the average of the two middle elements, rounded half-up to two decimal places. The `advocacy_grade` bands on the median with higher SQM meaning darker sky: a median of at least 21.50 earns `A`; at least 20.50 earns `B`; at least 19.50 earns `C`; at least 18.50 earns `D`; anything below 18.50 earns `F`. Band edges are inclusive — a median of exactly 21.50 is an `A`.

Finalizing a report requires at least 3 swept readings; attempting to finalize with fewer is rejected with `ERR_INSUFFICIENT_READINGS` (HTTP 422). Finalization moves the report `OPEN → FINALIZED` and freezes both `median_sqm` and `advocacy_grade` at their finalize-time values; readings recorded later inside the window do not change the frozen numbers.

### 3.10. Role-by-Role Operating Summary

The workflows above interleave across four roles. A `ClubOfficer` runs the back office: defines tiers, registers members, issues and voids invoices, posts payments, reinstates suspended members, opens and finalizes dark-sky reports, and drives the logical clock for the entire system. A `Member` lives in the self-service lane: reserves and cancels loans, accepts or declines or withdraws operator invitations, books and cancels group visits, records sky-quality readings, posts dues payments, and may resign. The `EventCoordinator` owns the event pipeline end to end: drafts, schedules, unschedules, weather-checks, confirms, cancels, and completes events; invites operators and marks their no-shows; confirms group bookings and marks theirs. The `EquipmentChair` owns hardware and skills: registers and edits and retires telescopes, opens and works maintenance tickets through the verification cycle, issues and revokes certifications, and staffs the loan desk at checkout and return. Shared lanes are narrow: both `Member` and `EquipmentChair` can create and cancel loan reservations; both `Member` and `ClubOfficer` can post payments and resign; both `Member` and `EventCoordinator` can cancel group bookings; and every role reads broadly across the system per §4.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including every state-transition action and the clock set — return `200 OK`. All endpoints are mounted under the `/club` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/club/_clock/set_current_utc` | Advance the server logical clock; fires automatic time-based transitions | ClubOfficer |
| POST | `/club/membership-tiers` | Create a membership tier | ClubOfficer |
| GET | `/club/membership-tiers/{tierId}` | Fetch one tier | ClubOfficer, Member, EventCoordinator, EquipmentChair |
| GET | `/club/membership-tiers` | List tiers | ClubOfficer, Member, EventCoordinator, EquipmentChair |
| POST | `/club/members` | Register a member (initial status `ACTIVE`) | ClubOfficer |
| GET | `/club/members/{memberId}` | Fetch one member | ClubOfficer, Member, EventCoordinator, EquipmentChair |
| GET | `/club/members` | List members; filter by `status` or `tier_id` | ClubOfficer, EventCoordinator, EquipmentChair |
| POST | `/club/members/{memberId}/reinstate` | Reinstate a suspended member once dues are current | ClubOfficer |
| POST | `/club/members/{memberId}/resign` | Resign a member; cascades cancel loans and withdraw assignments | Member, ClubOfficer |
| POST | `/club/dues-invoices` | Issue a dues invoice with pro-rated amount | ClubOfficer |
| GET | `/club/dues-invoices/{invoiceId}` | Fetch one invoice | ClubOfficer, Member |
| GET | `/club/dues-invoices` | List invoices; filter by `member_id` or `status` | ClubOfficer, Member |
| POST | `/club/dues-invoices/{invoiceId}/void` | Void an open invoice | ClubOfficer |
| POST | `/club/dues-payments` | Post a payment against an open invoice | Member, ClubOfficer |
| GET | `/club/dues-payments` | List payments; filter by `member_id` or `invoice_id` | ClubOfficer, Member |
| GET | `/club/dues-payments/{paymentId}` | Fetch one payment | ClubOfficer, Member |
| POST | `/club/telescopes` | Register a telescope (initial status `AVAILABLE`) | EquipmentChair |
| GET | `/club/telescopes/{telescopeId}` | Fetch one telescope | ClubOfficer, Member, EventCoordinator, EquipmentChair |
| GET | `/club/telescopes` | List telescopes; filter by `status` or `equipment_class` | ClubOfficer, Member, EventCoordinator, EquipmentChair |
| PUT | `/club/telescopes/{telescopeId}` | Update a telescope's descriptive fields (OCC-guarded) | EquipmentChair |
| POST | `/club/telescopes/{telescopeId}/retire` | Retire a telescope from `AVAILABLE` or `MAINTENANCE` | EquipmentChair |
| POST | `/club/maintenance-tickets` | Open a maintenance ticket | EquipmentChair |
| GET | `/club/maintenance-tickets/{ticketId}` | Fetch one ticket | ClubOfficer, EquipmentChair |
| GET | `/club/maintenance-tickets` | List tickets; filter by `telescope_id` or `status` | ClubOfficer, EquipmentChair |
| POST | `/club/maintenance-tickets/{ticketId}/start` | Begin work on a ticket | EquipmentChair |
| POST | `/club/maintenance-tickets/{ticketId}/submit-verification` | Submit ticket work for verification | EquipmentChair |
| POST | `/club/maintenance-tickets/{ticketId}/reopen` | Return a failed verification to in-progress | EquipmentChair |
| POST | `/club/maintenance-tickets/{ticketId}/close` | Close a verified ticket; recompute condition | EquipmentChair |
| POST | `/club/training-certifications` | Issue a certification to a member | EquipmentChair |
| GET | `/club/training-certifications/{certId}` | Fetch one certification | ClubOfficer, Member, EquipmentChair, EventCoordinator |
| GET | `/club/training-certifications` | List certifications; filter by `member_id`, `equipment_class`, `status` | ClubOfficer, Member, EquipmentChair, EventCoordinator |
| POST | `/club/training-certifications/{certId}/revoke` | Revoke a certification; cancels matching reserved loans | EquipmentChair |
| POST | `/club/loan-reservations` | Create a loan reservation | Member, EquipmentChair |
| GET | `/club/loan-reservations/{loanId}` | Fetch one loan (provisional overdue fee when `OVERDUE`) | ClubOfficer, Member, EquipmentChair |
| GET | `/club/loan-reservations` | List loans; filter by `member_id`, `telescope_id`, `status` | ClubOfficer, Member, EquipmentChair |
| POST | `/club/loan-reservations/{loanId}/checkout` | Check out a reserved loan within its window | EquipmentChair |
| POST | `/club/loan-reservations/{loanId}/return` | Return a loan; optional damage report routes telescope to maintenance | EquipmentChair |
| POST | `/club/loan-reservations/{loanId}/cancel` | Cancel a reserved loan | Member, EquipmentChair |
| POST | `/club/observing-events` | Create an observing event (initial status `DRAFT`) | EventCoordinator |
| GET | `/club/observing-events/{eventId}` | Fetch one event | ClubOfficer, Member, EventCoordinator, EquipmentChair |
| GET | `/club/observing-events` | List events; filter by `status` or `event_kind` | ClubOfficer, Member, EventCoordinator, EquipmentChair |
| POST | `/club/observing-events/{eventId}/schedule` | Schedule a draft event (moon / daylight gates) | EventCoordinator |
| POST | `/club/observing-events/{eventId}/unschedule` | Send a scheduled event back to draft | EventCoordinator |
| POST | `/club/observing-events/{eventId}/weather-check` | Record the latest forecast cancellation probability | EventCoordinator |
| POST | `/club/observing-events/{eventId}/confirm` | Confirm a scheduled event (OCC-guarded; coverage, weather, solar gates) | EventCoordinator |
| POST | `/club/observing-events/{eventId}/cancel` | Cancel a scheduled or confirmed event with a reason | EventCoordinator |
| POST | `/club/observing-events/{eventId}/complete` | Complete a confirmed event after its window ends | EventCoordinator |
| POST | `/club/event-operator-assignments` | Invite a member to operate a telescope at an event | EventCoordinator |
| GET | `/club/event-operator-assignments/{assignmentId}` | Fetch one assignment | ClubOfficer, Member, EventCoordinator |
| GET | `/club/event-operator-assignments` | List assignments; filter by `event_id`, `member_id`, `telescope_id`, `status` | ClubOfficer, Member, EventCoordinator |
| POST | `/club/event-operator-assignments/{assignmentId}/accept` | Accept an operator invitation | Member |
| POST | `/club/event-operator-assignments/{assignmentId}/decline` | Decline an operator invitation | Member |
| POST | `/club/event-operator-assignments/{assignmentId}/withdraw` | Withdraw a confirmed operator commitment | Member |
| POST | `/club/event-operator-assignments/{assignmentId}/mark-no-show` | Mark a confirmed operator as no-show after completion | EventCoordinator |
| POST | `/club/group-visit-bookings` | Book a group visit onto a public night | Member |
| GET | `/club/group-visit-bookings/{bookingId}` | Fetch one booking | ClubOfficer, Member, EventCoordinator |
| GET | `/club/group-visit-bookings` | List bookings; filter by `event_id`, `contact_member_id`, `status` | ClubOfficer, Member, EventCoordinator |
| POST | `/club/group-visit-bookings/{bookingId}/confirm` | Confirm a pending booking (aggregate capacity gate) | EventCoordinator |
| POST | `/club/group-visit-bookings/{bookingId}/cancel` | Cancel a pending or confirmed booking | Member, EventCoordinator |
| POST | `/club/group-visit-bookings/{bookingId}/mark-no-show` | Mark a confirmed booking as no-show after completion | EventCoordinator |
| POST | `/club/sky-quality-readings` | Record a sky-quality reading taken during an event | Member |
| GET | `/club/sky-quality-readings/{readingId}` | Fetch one reading | ClubOfficer, Member, EventCoordinator |
| GET | `/club/sky-quality-readings` | List readings; filter by `event_id` or `taken_by_member_id` | ClubOfficer, Member, EventCoordinator |
| POST | `/club/dark-sky-reports` | Open a dark-sky report over a period | ClubOfficer |
| GET | `/club/dark-sky-reports/{reportId}` | Fetch one report | ClubOfficer, Member, EventCoordinator |
| GET | `/club/dark-sky-reports` | List reports; filter by `status` | ClubOfficer, Member, EventCoordinator |
| POST | `/club/dark-sky-reports/{reportId}/finalize` | Finalize a report, freezing median and grade | ClubOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_MOON_TOO_BRIGHT` | 422 |
| `ERR_NOT_DAYLIGHT_WINDOW` | 422 |
| `ERR_WEATHER_RISK` | 422 |
| `ERR_INSUFFICIENT_OPERATORS` | 422 |
| `ERR_NO_SOLAR_CERTIFIED_OPERATOR` | 422 |
| `ERR_CERTIFICATION_REQUIRED` | 422 |
| `ERR_MEMBER_NOT_IN_GOOD_STANDING` | 422 |
| `ERR_TELESCOPE_NOT_RESERVABLE` | 409 |
| `ERR_LOAN_WINDOW_CONFLICT` | 409 |
| `ERR_OPERATOR_OVERLAP` | 409 |
| `ERR_EVENT_GROUP_CAPACITY` | 422 |
| `ERR_NO_SHOW_THROTTLED` | 422 |
| `ERR_PAYMENT_INSUFFICIENT` | 422 |
| `ERR_LOANS_OUTSTANDING` | 422 |
| `ERR_INSUFFICIENT_READINGS` | 422 |
| `ERR_LOAN_CAP_REACHED` | 422 |
