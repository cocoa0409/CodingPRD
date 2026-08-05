# Vacation Rental Management API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a full-service vacation-rental management platform in the style of a professional property-management operator. The platform carries a short-term rental property through its complete operational arc: an owner is onboarded and their property is permitted, listed, and syndicated to booking channels; nightly rates are set dynamically from seasonal, occupancy, and last-minute signals; guests are screened and booked against a calendar that must never double-sell a night; cleaning turnovers and independent inspections gate each new stay; maintenance work orders are dispatched, approved, and billed; and, at period close, each owner receives a reconciled statement that splits rental income, deducts the management fee and owner-billable maintenance charges, and remits occupancy tax to the jurisdiction.

The system is fundamentally a reconciliation engine wrapped around a temporal calendar. Two forces dominate its design. First, **temporal windowing**: bookings occupy half-open date intervals, turnover crews carry buffered availability windows, permits expire, and pricing rules cover date ranges — every one of these must be evaluated against a single authoritative logical clock rather than wall-clock time. Second, **ledger reconciliation**: money flows from guest payment through management-fee splits, maintenance charges, and tax remittance into an owner payout, and every derived total must reconcile to the penny at both a provisional (draft) and a final (finalized) stage. Layered on top are optimistic concurrency on pricing supersession, cascading cancellations that ripple from a property offboard down through bookings, turnovers, and inspections, and a strict segregation of duties that forbids a single vendor from both cleaning and inspecting the same turnover.

This specification is the sole contract for implementers. Section 2 fixes the system-wide envelope, access-control, precision, concurrency, and consistency rules. Section 3 narrates the business workflows and the calculations that drive them. Sections 4 and 5 enumerate the endpoint surface and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request is authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. When these headers are missing, or when `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to perform the requested operation — or an ownership-scoped role acts on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes six roles, spelled exactly as follows: `PlatformAdmin`, `PropertyManager`, `Owner`, `Guest`, `Vendor`, and `Anonymous`.

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. `PlatformAdmin` is the operational superuser responsible for the logical clock, owner creation, statement generation, and offboarding.
- When `X-User-Role` is `PropertyManager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`. The property manager drives listing, pricing, permits, channels, screening, turnovers, work-order administration, statements, and reviews.
- When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner`. Ownership checks on any resource that references an `Owner` compare the resource's owning-owner foreign key to `X-User-ID` — an `Owner` may read only their own properties, statements, and work orders, and may approve or reject work orders and offboard only against properties whose `owner_id` equals their `X-User-ID`.
- When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting `Guest`. Ownership checks on any resource that references a `Guest` compare the resource's `guest_id` to `X-User-ID` — a `Guest` may read and act on only bookings whose `guest_id` equals their `X-User-ID`, and may read only their own guest record.
- When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting `Vendor`. Ownership checks on any resource that references a `Vendor` compare the resource's assigned-vendor foreign key to `X-User-ID` — a `Vendor` may start or complete only turnovers whose `assigned_vendor_id` equals their `X-User-ID`, and may start or complete only work orders whose `vendor_id` equals their `X-User-ID`.
- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque public identifier not tied to any persisted entity. Two endpoints — guest self-registration and property price-quoting — are fully public and may be called with no authentication headers at all; the remaining Anonymous-authorized surface (inquiry booking creation) accepts requests bearing the `Anonymous` role.

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

List endpoints accept two pagination query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100; a request that asks for more than 100 is capped at 100. The `offset` parameter defaults to 0 and has a minimum of 0. Every collection is returned in ascending order of `created_at` (oldest first) unless an endpoint narrative states otherwise. The `meta` block of a list response carries `limit`, `offset`, `total_count` (the total number of records matching the filter before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at 1 on creation and increments by 1 on each mutation. The one exception is the `StatementLine` resource: statement lines are immutable ledger entries and carry only `id` and `created_at` — they have neither `updated_at` nor `version`.

All date, window, expiry, and elapsed-day computations are evaluated against a single server **logical clock**, never against wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any clock-setting call it continues to read exactly that default. An administrative test-driving capability advances the clock to a supplied `to_iso8601` instant, after which all temporal comparisons — permit expiry, check-in eligibility, days-to-check-in for refunds, last-minute pricing, and turnover-window buffering — use the new value.

### 2.5. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Wherever a calculation produces a fractional cent, the result is rounded half-up (round-half-away-from-zero at the .5 boundary) to a whole cent. The pinned points at which rounding occurs are specified with each calculation in Section 3 — most importantly, the dynamic nightly rate is rounded **once per night** after the full multiplicative product and only then multiplied by the number of nights, and the management fee is rounded **per booking** before the per-booking amounts are summed. Percentages such as the management fee percent and the occupancy tax percent are expressed in whole-number percent units (for example, a value of 20 means twenty percent), and rate multipliers on pricing rules are expressed in basis points where 10000 basis points equal a factor of 1.0.

### 2.6. Validation Ordering and Error Precedence

When a request could fail more than one check, the checks are evaluated in a fixed priority order and the first failure determines the returned error. The order is:

1. **Authentication** — headers present and `X-User-Role` a recognized role, else `ERR_UNAUTHENTICATED` (401). This applies to every endpoint except guest self-registration and property price-quoting, which are public.
2. **Authorization** — the role is permitted for the endpoint, and an ownership-scoped role owns the target resource, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every path id and every referenced foreign key resolves to an existing resource, validated left-to-right in the order they appear in the path and then the body, else `ERR_NOT_FOUND` (404).
4. **Body well-formedness** — required fields present, enum values legal, and numeric ranges satisfied (a `rating` between 1 and 5 inclusive, a `cost_cents` that is zero or greater, and a `check_out` strictly after `check_in`), else `ERR_VALIDATION` (422).
5. **State** — the target resource is in a legal state for the requested transition, else the specific state error for that operation (see below), falling back to the generic `ERR_INVALID_STATE` (409) for any transition attempted from a state that does not permit it.
6. **Business-safety** — guest-ban, segregation-of-duties, and permit-expiry checks.
7. **Business-referential** — open-work-order and owner-approval checks.
8. **Business-constraint (domain)** — vendor-type and minimum-stay checks.
9. **Business-temporal** — date-overlap and vendor-window checks.
10. **Business-fiscal** — the non-negative-payout check.
11. **Optimistic concurrency** — the pricing-rule stale-version check.

The state-tier (priority 5) errors, each raised only after authentication, authorization, existence, and body checks have passed, are: `ERR_PROPERTY_NOT_BOOKABLE` (409) when a booking is created against a property that is not `LISTED`; `ERR_SCREENING_NOT_APPROVED` (409) when a booking is confirmed while its `screening_status` is not `APPROVED`; `ERR_TURNOVER_NOT_READY` (409) when a check-in is attempted while the property's most recent turnover is not `INSPECTED`; `ERR_TURNOVER_NOT_CLEANED` (409) when an inspection is recorded against a turnover not in `CLEANED`; `ERR_STATEMENT_NOT_FINALIZED` (409) when payment is attempted on a statement not in `FINALIZED`; `ERR_PERMIT_NOT_ACTIVE` (409) when a property is listed without an `ACTIVE` permit; and `ERR_BOOKING_NOT_CHECKED_OUT` (409) when a review is created for a booking not in `CHECKED_OUT`. The business-safety tier (priority 6) carries `ERR_GUEST_BANNED` (403), `ERR_SOD_INSPECTOR_IS_CLEANER` (409), and `ERR_PERMIT_EXPIRED` (409). The referential tier (priority 7) carries `ERR_OPEN_WORK_ORDERS` (409) and `ERR_OWNER_APPROVAL_REQUIRED` (403). The domain-constraint tier (priority 8) carries `ERR_VENDOR_NOT_CLEANER` (422) and `ERR_MIN_STAY_NOT_MET` (422). The temporal tier (priority 9) carries `ERR_DATES_UNAVAILABLE` (409) and `ERR_VENDOR_UNAVAILABLE` (409). The fiscal tier (priority 10) carries `ERR_NEGATIVE_PAYOUT` (409). The concurrency tier (priority 11) carries `ERR_STALE_VERSION` (412).

### 2.7. Optimistic Concurrency on Pricing Supersession

Creating a pricing rule against a property is the one operation guarded by optimistic concurrency control. The create request must carry an `expected_property_version` field, which is not optional and must equal the target property's current `version` at the moment the server processes the request. If another writer has advanced the property's version since the client last read it — for example by creating an intervening pricing rule — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The rationale is that a newly created same-type overlapping rule legitimately supersedes (deactivates) the prior one; a create issued from a stale property view, one that has not observed the intervening pricing change, must not silently supersede based on outdated pricing, so it is rejected as a stale-version write. A successful pricing-rule create increments the property's `version` by 1. No other endpoint accepts or requires a version field.

### 2.8. Cascading State Propagation and Money Conservation

Several operations mutate more than one entity, and every cascade is mandatory and immediate. Offboarding a property is the deepest: it drives the property to `OFFBOARDED`, transitions every one of its channel listings to `DELISTED`, and cancels every non-terminal booking (any booking whose `stay_status` is `HOLD` or `CONFIRMED`). Each such booking cancellation itself cascades — it releases the held calendar nights and cancels that booking's turnover task if the task is still non-terminal, and that turnover cancellation in turn cancels any `COMPLETED` inspection attached to it. Revoking a property's `ACTIVE` permit is a lighter cascade: if the property is `LISTED`, it is automatically driven to `UNLISTED`.

Whenever a mutation changes an entity, that entity's `updated_at` is refreshed and its `version` is incremented (except `StatementLine`, which is immutable). Owner statements observe a **money-conservation invariant** that must hold at every draft and finalized moment: the management fee, the owner payout, and the owner-billable work-order charges together equal the gross rental — that is, gross rental minus management fee minus work-order owner charges equals the owner payout. Reopening a finalized statement is a compensating action that removes the derived tax-remittance line and reverts to the provisional split while preserving this invariant, and it increments the statement's `version`.

### 2.9. Calendar Availability and Overlap Semantics

A property's calendar treats each booking as occupying the half-open interval from its `check_in` up to but not including its `check_out`; two stays that merely touch at a shared date (one checking out the morning another checks in) do not overlap and are both allowed. Availability over any date window is computed as the window's total night count minus the nights covered by bookings whose `stay_status` is `HOLD`, `CONFIRMED`, `CHECKED_IN`, or `CHECKED_OUT`, minus blocked nights (of which there are none in this system, since there is no separate calendar-block entity). The invariant that available nights plus booked nights plus blocked nights equals the total window nights must always hold; creating a booking occupies nights and cancelling one releases them, restoring the balance.

## 3. Business Logic & Workflows

### 3.1. Onboarding Owners, Guests, and Vendors

An `Owner` is registered by a platform administrator with a `legal_name`, an `email`, an optional `payout_method` (one of `ACH`, `CHECK`, or `WIRE`, defaulting to `ACH`), and a `default_management_fee_pct` that expresses the percentage of rental income the operator retains on that owner's statements. A new owner begins in `status` `ACTIVE`; over its life an owner may also be `SUSPENDED` or `OFFBOARDED`.

A `Guest` may register themselves through the public surface, or an operator may register them; either way the payload carries a `full_name`, an `email`, and an optional `government_id_verified` flag that defaults to false when omitted. A guest starts `UNSCREENED` and may become `APPROVED` or `BANNED`. Banning a guest drives their `status` to `BANNED`; a banned guest may neither create a booking nor be approved during screening, and either attempt is rejected with `ERR_GUEST_BANNED`.

A `Vendor` represents a crew and is created with a `name`, a `vendor_type` (one of `CLEANER`, `INSPECTOR`, `MAINTENANCE`, or `GENERAL`), and an `email`. Vendors begin `ACTIVE` and may be set `INACTIVE`. The vendor type matters downstream: only a `CLEANER` may be assigned to a turnover, and a work order may only be assigned to a vendor whose `status` is `ACTIVE`.

### 3.2. Property Onboarding, Permits, Channels, and Listing

A `Property` is created against an existing owner by referencing that owner's identifier as `owner_id`, together with an `address`, `city`, `state_code`, `jurisdiction_code` (the tax jurisdiction that drives permitting and remittance), a `base_nightly_rate_cents` before dynamic factors, a per-stay `cleaning_fee_cents`, a `max_occupancy`, and an optional `default_cancellation_policy` (one of `FLEXIBLE`, `MODERATE`, or `STRICT`, defaulting to `MODERATE`) that new bookings inherit unless overridden. A freshly created property begins in `status` `ONBOARDING` with its `version` at 1.

Before a property can be published, it needs a permit. A `Permit` is created against a property via its `property_id` and carries a `permit_number`, its own `jurisdiction_code`, an `occupancy_tax_pct` applied to the taxable base of bookings, an `issued_on` date, and an `expires_on` date. A permit starts `PENDING`. Activating a permit moves it from `PENDING` to `ACTIVE`, but only when the logical clock is at or before its `expires_on`; an activation attempted after expiry is rejected with `ERR_PERMIT_EXPIRED`. Revoking an `ACTIVE` permit moves it to `REVOKED`, and if its property was `LISTED`, that property is automatically driven back to `UNLISTED`.

Publishing a property advances it from `ONBOARDING` (or from `UNLISTED`) to `LISTED`. This requires the property to have a permit in `ACTIVE` status — absent one, the request fails with `ERR_PERMIT_NOT_ACTIVE` — and additionally requires the logical clock to be at or before that permit's `expires_on`, else `ERR_PERMIT_EXPIRED`. Unlisting moves a `LISTED` property to `UNLISTED`. Offboarding may be invoked from `ONBOARDING`, `LISTED`, or `UNLISTED` and drives the property to the terminal `OFFBOARDED` state, triggering the full cancellation and delisting cascade described in Section 2.8.

Each `ChannelListing` ties a property (by `property_id`) to a distribution `channel` (one of `AIRBNB`, `VRBO`, `DIRECT`, or `BOOKING_COM`) with an optional `external_listing_ref`. A listing is created in `DRAFT`. Syncing a listing advances it from `DRAFT` or `PAUSED` to `SYNCED`, but only while its property is `LISTED`. Pausing a `SYNCED` listing returns it to `PAUSED`. When a property is offboarded, all of its channel listings — whether `DRAFT`, `SYNCED`, or `PAUSED` — are driven to the terminal `DELISTED` state.

### 3.3. Dynamic Pricing Rules and Quoting

A `PricingRule` shapes a property's nightly rate and is created against the property (referenced by `property_id`) by a property manager. Each rule declares a `rule_type` (one of `SEASONAL`, `OCCUPANCY`, `LAST_MINUTE`, or `MIN_STAY`), a tie-break `priority` where a higher value wins among same-type matches, and — depending on type — an optional `multiplier_bps` rate multiplier in basis points (used by `SEASONAL`, `OCCUPANCY`, and `LAST_MINUTE` rules), an optional `min_nights` (used by `MIN_STAY` rules), and an optional inclusive `start_date` and exclusive `end_date` bounding the range the rule covers. A rule carries an `active` flag that begins true and is set false once the rule is superseded. Creating a rule deactivates every same-type rule that is currently active and whose date window overlaps the new rule's window, then leaves the new rule active. Because this supersession changes pricing state, the create is guarded by optimistic concurrency: the caller must supply `expected_property_version` matching the property's current `version`, as detailed in Section 2.7, and a successful create increments that version.

The **occupancy percentage** for a prospective stay measures how full the property is around the requested check-in. The system defines a thirty-day window centered on `check_in`: it begins fifteen days before check-in and ends fifteen days after (a half-open window that includes its start and excludes its end). It counts the booked night-days within that window — those nights falling inside the half-open interval from `check_in` to `check_out` of any other booking on the same property whose `stay_status` is `HOLD`, `CONFIRMED`, `CHECKED_IN`, or `CHECKED_OUT`, explicitly excluding the booking being priced — and divides that count by thirty, multiplies by one hundred, and takes the floor to a whole integer percent. Cancelled and declined bookings never contribute.

The **dynamic nightly quote** starts from the property's `base_nightly_rate_cents` and applies three independent factors in turn. The seasonal factor is drawn from active `SEASONAL` rules whose half-open date window (from `start_date` up to `end_date`) covers the check-in date; among matches, the highest-priority rule wins, breaking any tie in favor of the earliest-created rule, and its factor is its `multiplier_bps` divided by 10000 — if no seasonal rule matches, the factor is 1.0. The occupancy factor is tiered on the occupancy percentage: at eighty percent or above the factor is 1.25, at fifty percent or above (but below eighty) the factor is 1.10, and below fifty percent the factor is 1.0. The last-minute factor applies when the whole-day gap between the logical clock and check-in is seven days or fewer, in which case the factor is 0.85, otherwise 1.0. The per-night rate is the base multiplied by all three factors, rounded half-up to whole cents exactly once after the full product; the nightly subtotal is then that per-night rate multiplied by the number of nights. A property manager, guest, administrator, or anonymous caller may request a standalone quote for a candidate `check_in`/`check_out` window without creating a booking; the quote response reports `per_night_rate_cents`, `nights`, `nightly_subtotal_cents`, `cleaning_fee_cents`, `occupancy_tax_cents`, `total_cents`, and the computed `occupancy_pct`.

### 3.4. Booking Creation, Screening, and the Parallel Status Model

Creating a `Booking` references the property (`property_id`) and the guest (`guest_id`) and supplies a `check_in`, a `check_out`, and an optional `cancellation_policy` that defaults from the property's `default_cancellation_policy`. Bookings use two independent status dimensions that evolve in parallel: `stay_status`, which begins at `HOLD`, and `screening_status`, which begins at `PENDING`. At creation the property must be `LISTED` (else `ERR_PROPERTY_NOT_BOOKABLE`), the guest must not be `BANNED` (else `ERR_GUEST_BANNED`), the number of `nights` must meet any active `MIN_STAY` rule's `min_nights` (else `ERR_MIN_STAY_NOT_MET`), and the requested interval must not overlap any existing booking on the property whose `stay_status` is `HOLD`, `CONFIRMED`, or `CHECKED_IN`. Overlap uses half-open interval semantics so back-to-back stays are permitted; a genuine overlap is rejected with `ERR_DATES_UNAVAILABLE`.

On successful creation the server computes and snapshots the full price. It derives `nights` as the whole-day difference between `check_out` and `check_in`, locks the dynamic per-night rate into `quoted_per_night_cents` and the `nightly_subtotal_cents`, snapshots the property's cleaning fee into `quoted_cleaning_fee_cents`, computes `occupancy_tax_cents` as the taxable base (nightly subtotal plus cleaning fee) multiplied by the active permit's `occupancy_tax_pct` divided by one hundred and rounded half-up (using zero when the property has no `ACTIVE` permit), and sets `total_cents` to the sum of nightly subtotal, cleaning fee, and occupancy tax. The `refund_cents` field starts at 0. The booking holds the calendar nights it occupies, and an empty `messages` list is initialized.

Screening a booking records a `decision` and advances the `screening_status` dimension; screening acts only on a booking whose `screening_status` is still `PENDING`, and a booking already `APPROVED` or `DECLINED` is rejected with `ERR_INVALID_STATE`. A decision of `APPROVED` moves `screening_status` from `PENDING` to `APPROVED`, provided the guest is not `BANNED` (else `ERR_GUEST_BANNED`). A decision of `DECLINED` moves `screening_status` to `DECLINED` and, as a side effect, cancels the stay: `stay_status` becomes `CANCELLED` and the held calendar nights are released. Booking participants exchange messages on the thread by appending a `body` with an optional `sender_role`; the server records each entry as an object bearing `sender_role`, `body`, and an `at` timestamp onto the append-only `messages` array, and the append returns HTTP 201 with the updated booking.

### 3.5. The Stay Lifecycle: Confirm, Check-In, Check-Out, and Cancellation

The `stay_status` dimension progresses only after screening clears. Confirming a booking advances `stay_status` from `HOLD` to `CONFIRMED`, but only when `screening_status` is `APPROVED`; a confirm attempted otherwise is rejected with `ERR_SCREENING_NOT_APPROVED`. Checking in advances `CONFIRMED → CHECKED_IN` and requires two conditions: the logical clock must be at or after the booking's `check_in` — a check-in attempted before that instant fails with `ERR_INVALID_STATE` — and the property's most recent turnover task, if any exists, must be in `INSPECTED` status — a check-in against an un-inspected turnover fails with `ERR_TURNOVER_NOT_READY`. Checking out advances `CHECKED_IN → CHECKED_OUT`; upon check-out the booking becomes eligible for inclusion in the owner statement covering its check-out period and becomes eligible to receive a review.

Cancellation may be invoked from either `HOLD` or `CONFIRMED` and drives `stay_status` to `CANCELLED`. Cancellation computes the refund, releases the held calendar nights (restoring the availability invariant), and cascades to the booking's turnover task: a non-terminal turnover is cancelled, which in turn cancels any `COMPLETED` inspection attached to it.

The **cancellation refund** depends on the booking's `cancellation_policy` and on how far ahead of check-in the cancellation occurs. The system computes days-to-check-in as the floored whole-day difference between `check_in` and the current logical clock, then selects a refund percentage with inclusive (at-or-greater-than) boundaries. Under `FLEXIBLE`, a cancellation at least one day before check-in refunds the full one hundred percent, otherwise nothing. Under `MODERATE`, a cancellation at least thirty days out refunds fully, one at least seven days out (but fewer than thirty) refunds fifty percent, and anything under seven days refunds nothing — so for identical timing `MODERATE` can pay out far less than `FLEXIBLE`. Under `STRICT`, only a cancellation at least sixty days out refunds fully, otherwise nothing. The refundable nightly portion is the `nightly_subtotal_cents` times the refund percentage, rounded half-up; the cleaning fee is refunded in full only when the stay had not yet checked in (`stay_status` is not `CHECKED_IN`) and the refund percentage is greater than zero, otherwise it is not refunded; the tax portion is the `occupancy_tax_cents` times the refund percentage, rounded half-up. The final `refund_cents` is the sum of the refundable nightly amount, the cleaning refund, and the tax refund.

### 3.6. Turnover Cleaning and Independent Inspection

After a stay, a `TurnoverTask` schedules the cleaning. It is created by a property manager referencing the checked-out `booking_id`, the `property_id`, the `assigned_vendor_id`, and a `scheduled_window_start` and `scheduled_window_end` that bound the crew's window as a closed interval with travel buffer. The assigned vendor must be of `vendor_type` `CLEANER`, else `ERR_VENDOR_NOT_CLEANER`. The system also enforces crew availability: for the same assigned vendor, it examines every other turnover in a non-terminal-ish status (`SCHEDULED`, `IN_PROGRESS`, `CLEANED`, or `FAILED`), expands each such task's window by two hours (120 minutes) on both sides, and treats the requested window as conflicting if it intersects any buffered window under closed-interval comparison — that is, the requested start is at or before the buffered end and the buffered start is at or before the requested end. Any conflict is rejected with `ERR_VENDOR_UNAVAILABLE`. This buffered, closed-interval overlap for crews deliberately contrasts with the unbuffered half-open overlap used for guest bookings, where adjacent intervals are allowed.

A turnover begins `SCHEDULED`. The assigned cleaner starts it (`SCHEDULED → IN_PROGRESS`) and later marks it done (`IN_PROGRESS → CLEANED`); both actions require the acting vendor to be the task's `assigned_vendor_id`. An `Inspection` is then recorded against the task, referencing the `turnover_task_id`, the `inspector_vendor_id`, a `result` of `PASS` or `FAIL`, and optional `notes`. The inspection requires the turnover to be in `CLEANED` (else `ERR_TURNOVER_NOT_CLEANED`) and enforces segregation of duties: the `inspector_vendor_id` must differ from the turnover's `assigned_vendor_id`, since a crew may not inspect its own cleaning — a self-inspection is rejected with `ERR_SOD_INSPECTOR_IS_CLEANER`. A `PASS` result drives the turnover `CLEANED → INSPECTED` (unblocking the next check-in); a `FAIL` result drives it `CLEANED → FAILED`. A failed turnover can be re-started by the assigned cleaner (`FAILED → IN_PROGRESS`) for a re-clean. An inspection is created in `COMPLETED` and only ever moves to `CANCELLED` as part of a turnover-cancellation cascade. A turnover may be cancelled from `SCHEDULED`, `IN_PROGRESS`, or `CLEANED` — by a property manager directly, or by the system during a booking-cancel or property-offboard cascade — and any `COMPLETED` inspection on that task is cancelled with it.

### 3.7. Maintenance Work Orders

A `WorkOrder` captures a maintenance job on a property. It is created referencing the `property_id`, with a `description`, an estimated `cost_cents`, a `billable_to` party (one of `OWNER`, `GUEST`, or `COMPANY`), and an optional `vendor_id` (which remains null until assignment). At creation the server computes `requires_owner_approval`: it is true only when `billable_to` is `OWNER` **and** the `cost_cents` strictly exceeds the owner-approval threshold of five hundred dollars (50,000 cents). The boundary is strict — a cost exactly equal to the threshold does not require owner approval. A work order also carries an `owner_statement_id`, which is null until the charge is posted to a statement on approval.

A work order begins `OPEN`. Assigning it references a `vendor_id` and moves it `OPEN → ASSIGNED`, setting that vendor; the referenced vendor must exist and be `ACTIVE` (a non-`ACTIVE` vendor is rejected with `ERR_INVALID_STATE`). The assigned vendor starts it (`ASSIGNED → IN_PROGRESS`) and completes it (`IN_PROGRESS → COMPLETED`), both requiring the acting vendor to be the work order's `vendor_id`. From `IN_PROGRESS` the job may be sent to `NEEDS_INFO`, and a property manager may resume it from `NEEDS_INFO` back to `ASSIGNED`, forming a revision loop. A completed work order is resolved by either approval or rejection. Rejection moves it `COMPLETED → REJECTED`. Approval moves it `COMPLETED → APPROVED`; when the work order's `requires_owner_approval` is true, the approving actor must be the `Owner` of the property, else `ERR_OWNER_APPROVAL_REQUIRED`.

Approval of a `billable_to` `OWNER` work order carries a two-step cascade: the system posts a `WORK_ORDER_CHARGE` statement line with an `amount_cents` equal to the negative of the work order's `cost_cents` and a `source_ref` naming the work order, appends it to the owner's `DRAFT` statement whose `period_year` and `period_month` equal the logical clock's current year and month (choosing the earliest-created such statement when several exist; when no matching `DRAFT` statement exists the approval still succeeds and no charge line is posted), sets the work order's `owner_statement_id` to that statement, and recomputes the statement's `work_order_owner_charges_cents` and `owner_payout_cents` to reflect the new charge.

### 3.8. Owner Statements, Splits, and Tax Remittance

An `OwnerStatement` reconciles a period's activity for one owner. It is generated for an `owner_id`, a `period_year`, and a `period_month` (1 through 12) and is created in `DRAFT`. Generation aggregates the **qualifying bookings**: those on the owner's properties whose `stay_status` is `CHECKED_OUT` and whose `check_out` falls in the statement's month and year. From these it computes `gross_rental_cents` as the sum of the qualifying bookings' `nightly_subtotal_cents`; `mgmt_fee_cents` as the sum of a per-booking management fee, where each booking's fee is its `nightly_subtotal_cents` times the owner's `default_management_fee_pct` divided by one hundred, rounded half-up per booking before summing; `cleaning_pass_through_cents` as the sum of the qualifying bookings' `quoted_cleaning_fee_cents` (an informational pass-through); and `work_order_owner_charges_cents` as the sum of `cost_cents` over `APPROVED`, `billable_to`-`OWNER` work orders on the owner's properties whose `owner_statement_id` points at this statement. The `owner_payout_cents` is the gross rental minus the management fee minus the work-order owner charges. Generation also lays down the ledger's `RENTAL`, `MGMT_FEE`, and `CLEANING_PASS_THROUGH` statement lines. Each `StatementLine` records its owning `statement_id`, a `line_type` (one of `RENTAL`, `MGMT_FEE`, `WORK_ORDER_CHARGE`, `TAX_REMITTANCE`, or `CLEANING_PASS_THROUGH`), a signed `amount_cents` (positive credits the owner, negative debits), and a `source_ref` naming the originating booking or work order (null for aggregate lines).

The split is computed twice, in two variants. While the statement is `DRAFT`, the split is **provisional**: `work_order_owner_charges_cents` counts only the work orders already approved and linked at generation time, so the payout is provisional. Finalizing recomputes the **final** split, re-aggregating to include any owner-billable work orders approved between generation and finalize — the final payout differs from the provisional one whenever those charges changed. Finalizing advances the statement `DRAFT → FINALIZED`, sets `tax_remitted_cents` to the sum of `occupancy_tax_cents` over the qualifying bookings (this value is set only at finalize), and lays down the `TAX_REMITTANCE` statement line. Finalizing is blocked while any work order on the owner's properties for the period is still in a non-terminal status (`OPEN`, `ASSIGNED`, `IN_PROGRESS`, `NEEDS_INFO`, or `COMPLETED`); such an attempt is rejected with `ERR_OPEN_WORK_ORDERS`.

Reopening moves a statement `FINALIZED → DRAFT` as a compensating action: it removes the derived `TAX_REMITTANCE` line and reverts to the provisional split, preserving the money-conservation invariant, and increments the statement's `version`. Paying moves a statement `FINALIZED → PAID`; it requires the statement to be `FINALIZED` (else `ERR_STATEMENT_NOT_FINALIZED`) and requires `owner_payout_cents` to be zero or greater (a negative payout is rejected with `ERR_NEGATIVE_PAYOUT`). A statement's individual ledger lines may be listed and optionally filtered by `line_type`.

### 3.9. Reviews

A `Review` is written against a checked-out booking. It references the `booking_id` and the `property_id`, carries a `rating` from 1 to 5 inclusive, an optional free-text `comment`, and an `author_role` of `GUEST` or `MANAGER`. The booking must be in `CHECKED_OUT`, else `ERR_BOOKING_NOT_CHECKED_OUT`. A review is created `SUBMITTED`. A property manager may publish it (`SUBMITTED → PUBLISHED`) or suppress it (`SUBMITTED → SUPPRESSED`, or `PUBLISHED → SUPPRESSED`); `SUPPRESSED` is terminal.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201; state transitions, other mutations, and reads return HTTP 200. All endpoints emit the standard response envelope of Section 2.2. The request and response bodies and side effects for each endpoint are described in the Section 3 narratives; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/owners` | Create an owner | PlatformAdmin |
| GET | `/owners/{id}` | Get an owner | PlatformAdmin, PropertyManager, Owner |
| POST | `/guests` | Register a guest | Anonymous, PlatformAdmin, PropertyManager |
| GET | `/guests/{id}` | Get a guest | PlatformAdmin, PropertyManager, Guest |
| POST | `/guests/{id}/ban` | Ban a guest | PlatformAdmin, PropertyManager |
| POST | `/vendors` | Create a vendor | PlatformAdmin, PropertyManager |
| GET | `/vendors/{id}` | Get a vendor | PlatformAdmin, PropertyManager, Vendor |
| POST | `/properties` | Create a property | PlatformAdmin, PropertyManager |
| GET | `/properties/{id}` | Get a property | PlatformAdmin, PropertyManager, Owner |
| GET | `/properties` | List properties | PlatformAdmin, PropertyManager, Owner |
| POST | `/properties/{id}/list` | List (publish) a property | PropertyManager |
| POST | `/properties/{id}/unlist` | Unlist a property | PropertyManager |
| POST | `/properties/{id}/offboard` | Offboard a property (cascades) | PropertyManager, PlatformAdmin, Owner |
| POST | `/properties/{id}/pricing-rules` | Create a pricing rule (OCC on property version) | PropertyManager |
| GET | `/properties/{id}/pricing-rules` | List a property's pricing rules | PlatformAdmin, PropertyManager |
| POST | `/properties/{id}/quote` | Compute a dynamic price quote | PlatformAdmin, PropertyManager, Guest, Anonymous |
| POST | `/permits` | Create a permit | PlatformAdmin, PropertyManager |
| GET | `/permits/{id}` | Get a permit | PlatformAdmin, PropertyManager |
| GET | `/permits` | List permits | PlatformAdmin, PropertyManager |
| POST | `/permits/{id}/activate` | Activate a permit | PlatformAdmin, PropertyManager |
| POST | `/permits/{id}/revoke` | Revoke a permit | PlatformAdmin, PropertyManager |
| POST | `/channel-listings` | Create a channel listing | PropertyManager |
| GET | `/channel-listings/{id}` | Get a channel listing | PlatformAdmin, PropertyManager |
| GET | `/channel-listings` | List channel listings | PlatformAdmin, PropertyManager |
| POST | `/channel-listings/{id}/sync` | Sync a channel listing | PropertyManager |
| POST | `/channel-listings/{id}/pause` | Pause a channel listing | PropertyManager |
| GET | `/pricing-rules/{id}` | Get a pricing rule | PlatformAdmin, PropertyManager |
| POST | `/bookings` | Create a booking | Guest, PropertyManager, Anonymous |
| GET | `/bookings/{id}` | Get a booking | PlatformAdmin, PropertyManager, Guest |
| GET | `/bookings` | List bookings | PlatformAdmin, PropertyManager, Guest |
| POST | `/bookings/{id}/screen` | Screen a booking's guest | PropertyManager |
| POST | `/bookings/{id}/confirm` | Confirm a booking | PropertyManager, Guest |
| POST | `/bookings/{id}/check-in` | Check in a booking | PropertyManager |
| POST | `/bookings/{id}/check-out` | Check out a booking | PropertyManager |
| POST | `/bookings/{id}/cancel` | Cancel a booking | Guest, PropertyManager |
| POST | `/bookings/{id}/messages` | Append a message to a booking thread | Guest, PropertyManager |
| POST | `/turnover-tasks` | Schedule a cleaning turnover | PropertyManager |
| GET | `/turnover-tasks/{id}` | Get a turnover task | PlatformAdmin, PropertyManager, Vendor |
| GET | `/turnover-tasks` | List turnover tasks | PlatformAdmin, PropertyManager, Vendor |
| POST | `/turnover-tasks/{id}/start` | Start a turnover | Vendor |
| POST | `/turnover-tasks/{id}/complete` | Mark a turnover cleaned | Vendor |
| POST | `/turnover-tasks/{id}/cancel` | Cancel a turnover | PropertyManager |
| POST | `/inspections` | Record a turnover inspection | Vendor, PropertyManager |
| GET | `/inspections/{id}` | Get an inspection | PlatformAdmin, PropertyManager, Vendor |
| GET | `/inspections` | List inspections | PlatformAdmin, PropertyManager, Vendor |
| POST | `/work-orders` | Create a work order | PropertyManager, Owner, Vendor |
| GET | `/work-orders/{id}` | Get a work order | PlatformAdmin, PropertyManager, Owner, Vendor |
| GET | `/work-orders` | List work orders | PlatformAdmin, PropertyManager, Owner, Vendor |
| POST | `/work-orders/{id}/assign` | Assign a vendor to a work order | PropertyManager |
| POST | `/work-orders/{id}/start` | Start a work order | Vendor |
| POST | `/work-orders/{id}/request-info` | Mark a work order NEEDS_INFO | Vendor, PropertyManager |
| POST | `/work-orders/{id}/resume` | Resume a work order to ASSIGNED | PropertyManager |
| POST | `/work-orders/{id}/complete` | Complete a work order | Vendor |
| POST | `/work-orders/{id}/approve` | Approve a completed work order | PropertyManager, Owner |
| POST | `/work-orders/{id}/reject` | Reject a completed work order | PropertyManager, Owner |
| POST | `/owner-statements` | Generate an owner statement | PropertyManager, PlatformAdmin |
| GET | `/owner-statements/{id}` | Get an owner statement | PlatformAdmin, PropertyManager, Owner |
| GET | `/owner-statements` | List owner statements | PlatformAdmin, PropertyManager, Owner |
| GET | `/owner-statements/{id}/lines` | List a statement's lines | PlatformAdmin, PropertyManager, Owner |
| POST | `/owner-statements/{id}/finalize` | Finalize a statement | PropertyManager |
| POST | `/owner-statements/{id}/reopen` | Reopen a finalized statement | PropertyManager |
| POST | `/owner-statements/{id}/pay` | Pay a finalized statement | PropertyManager |
| POST | `/reviews` | Create a review | Guest, PropertyManager |
| GET | `/reviews/{id}` | Get a review | PlatformAdmin, PropertyManager, Guest |
| GET | `/reviews` | List reviews | PlatformAdmin, PropertyManager, Guest |
| POST | `/reviews/{id}/publish` | Publish a review | PropertyManager |
| POST | `/reviews/{id}/suppress` | Suppress a review | PropertyManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PROPERTY_NOT_BOOKABLE` | 409 |
| `ERR_SCREENING_NOT_APPROVED` | 409 |
| `ERR_TURNOVER_NOT_READY` | 409 |
| `ERR_TURNOVER_NOT_CLEANED` | 409 |
| `ERR_STATEMENT_NOT_FINALIZED` | 409 |
| `ERR_PERMIT_NOT_ACTIVE` | 409 |
| `ERR_BOOKING_NOT_CHECKED_OUT` | 409 |
| `ERR_GUEST_BANNED` | 403 |
| `ERR_SOD_INSPECTOR_IS_CLEANER` | 409 |
| `ERR_PERMIT_EXPIRED` | 409 |
| `ERR_OPEN_WORK_ORDERS` | 409 |
| `ERR_OWNER_APPROVAL_REQUIRED` | 403 |
| `ERR_VENDOR_NOT_CLEANER` | 422 |
| `ERR_MIN_STAY_NOT_MET` | 422 |
| `ERR_DATES_UNAVAILABLE` | 409 |
| `ERR_VENDOR_UNAVAILABLE` | 409 |
| `ERR_NEGATIVE_PAYOUT` | 409 |
| `ERR_STALE_VERSION` | 412 |
