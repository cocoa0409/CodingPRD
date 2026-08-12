# Mobile Corporate Chair Massage API — Product Requirements Document

## 1. Introduction

Corporate wellness buyers increasingly purchase on-site chair massage: a provider dispatches licensed massage therapists to a customer's office with portable chairs, employees sign up for short sessions on a shared sheet, and the employer is billed afterward. Coordinating this work is operationally demanding — therapists must hold a valid license in the jurisdiction where the event takes place, travel must be quoted up front and settled after the fact, every recipient must sign a waiver before sitting down, and corporate customers expect consolidated invoicing with credit limits, disputes, and satisfaction-driven adjustments.

This document specifies the Mobile Corporate Chair Massage API, which manages that lifecycle end to end: region and corporate account onboarding, therapist and license administration, one-off event bookings, recurring wellness programs that materialize event bookings on a cadence, day-of-event execution, payout accounting, and final billing. All resources are served under the `/chair-massage` URL prefix. The sections below define the system-wide contracts first, then the business workflows in which the rules live, then the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying their operational capacity. The platform recognizes exactly three roles, spelled as follows: `PlatformAdmin`, `Organizer`, and `Therapist`.

- A `PlatformAdmin` is the platform operator with full override power: managing regions, corporate accounts, therapists, licenses, invoices, payouts, waivers, and the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it against any entity's `id`.
- An `Organizer` is a corporate HR representative or event planner who owns the bookings and wellness programs of their company. When `X-User-Role` is `Organizer`, `X-User-ID` is the `id` of the acting `CorporateAccount`; ownership checks on any resource that references a `CorporateAccount` compare the resource's foreign-key field (for example, a booking's `corporate_account_id`) to `X-User-ID`.
- A `Therapist` delivers sessions and manages their own chair-slot lifecycle. When `X-User-Role` is `Therapist`, `X-User-ID` is the `id` of the acting `Therapist`; ownership checks compare resource fields such as a chair slot's `therapist_id` to `X-User-ID`.

A request missing either header, or carrying an empty value for one, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted to perform the operation is rejected with `ERR_FORBIDDEN` (HTTP 403). Three bootstrap operations are exempt from the header-presence requirement: onboarding a therapist, onboarding a corporate account, and the administrative clock-setting capability described in §2.4. Every other endpoint requires both headers.

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

### 2.3. Pagination and List Filtering

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

List endpoints additionally accept optional equality filters appropriate to the resource being listed. Across the API these filter parameters are `status`, `billing_status`, `is_active`, `region_id`, `home_region_id`, `corporate_account_id`, `booking_id`, `therapist_id`, `chair_slot_id`, `event_date`, `entry_kind`, and `recipient_email`.

### 2.4. The Logical Clock and Date/Time Conventions

All date- and time-dependent decisions in the platform — event-day checks, license expiry, cancellation-fee tiers, wellness-occurrence scheduling — read a server-side logical clock, never the real wall clock. The server boots with its logical clock fixed at 2026-05-01T00:00:00Z, and until an administrator moves it, every rule that says "the current logical date" reads that default. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Advancing the clock also triggers the license expiry sweep: every license whose `expires_on` has fallen behind the new current date transitions to `EXPIRED` (§3.2).

Date and time representations are fixed across the API. Calendar dates such as `event_date`, `issued_on`, and `expires_on` use the YYYY-MM-DD format. A wellness program's `window_start_time` is a local wall-clock time of day in HH:MM, 24-hour form, while a booking's `window_start_minutes` expresses the same idea as integer minutes after local midnight, from 0 up to and including 1439. All timestamps are ISO 8601 UTC with three fractional digits.

### 2.5. Common Resource Properties

Primary resources share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource, including modifications caused by derived-field recomputation, and which underpins the optimistic concurrency rules of §2.7.

Two resources are deliberate exceptions: a satisfaction survey and a payout ledger entry are immutable, ledger-style records and carry only `id` and `created_at` — both `updated_at` and `version` are absent from them.

### 2.6. Monetary Precision and Rounding

All monetary values in the platform are integer cents; no fractional-cent arithmetic ever leaks into a stored or returned amount. Percentage-derived amounts — the recurrence discount on a recurring-occurrence invoice, the high-volume travel discount, the tiered cancellation fee, and the satisfaction credit — are each computed by multiplying the relevant base by the percentage and then rounding down (floor) to whole cents. Therapist payout lines are the one place half-up rounding applies: each line is rounded half-up to whole cents before the lines are summed. An invoice's grand total is floored at zero so a customer is never owed a negative balance.

### 2.7. Optimistic Concurrency Control

Two write operations require the client to prove it has observed the current state of the resource its request will mutate. Confirming a booking (`POST /chair-massage/bookings/{id}/confirm`) takes a non-optional `expected_booking_version` field carrying the booking's `version` as the client last read it. If the booking's current `version` has advanced since that read — for example because a chair was assigned or released in the meantime — the confirmation is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412), since the client's picture of which chairs are staffed is stale. Creating a sign-up-sheet claim (`POST /chair-massage/chair-slots/{id}/claims`) likewise takes a non-optional `expected_chair_slot_version` matching the chair slot's current `version`; a mismatch is rejected with `ERR_STALE_CHAIR_SLOT_VERSION` (HTTP 412), because another claim, cancellation, or no-show marking on the same chair has advanced the chair's version and rendered the writer's view of the next free slot stale. Endpoints not named here do not accept an expected-version field.

### 2.8. Validation Pipeline and Error Precedence

Every request is validated in a fixed pipeline order, and a failure at any stage short-circuits the rest. First, the presence of the two identity headers is checked (`ERR_UNAUTHENTICATED`, HTTP 401, with the three bootstrap exemptions of §2.1). Second, the role's permission to call the endpoint is checked (`ERR_FORBIDDEN`, HTTP 403). Third, every identifier in the path is resolved left-to-right (`ERR_NOT_FOUND`, HTTP 404 — see §2.10). Fourth, for action endpoints, the target resource must be in a state from which the requested transition is permitted (`ERR_INVALID_STATE`, HTTP 409). Fifth, where an endpoint requires an expected-version field, the version must match (`ERR_STALE_BOOKING_VERSION` or `ERR_STALE_CHAIR_SLOT_VERSION`, HTTP 412). Sixth, the business rules fire in their own fixed relative order: on chair assignment and on booking confirmation the therapist daily-load cap is evaluated first (`ERR_THERAPIST_DAILY_CAP`), then license validity (`ERR_LICENSE_INVALID`), then the double-booking scan (`ERR_THERAPIST_DOUBLE_BOOKED`); on sign-up-sheet claim creation the capacity check (`ERR_SIGNUP_SHEET_FULL`) precedes the duplicate-sign-up check (`ERR_DUPLICATE_SIGNUP`); on check-in the waiver check (`ERR_WAIVER_MISSING`) applies; on invoice issuance the credit-limit check (`ERR_CREDIT_LIMIT_EXCEEDED`) precedes the live-invoice uniqueness check (`ERR_LIVE_INVOICE_EXISTS`); survey uniqueness is guarded by `ERR_DUPLICATE_SURVEY`; and window divisibility by `ERR_WINDOW_NOT_DIVISIBLE`. Finally, field-shape validation — an enum outside its allowed set, a malformed date, an integer outside its permitted range — is reported as `ERR_INVALID_REQUEST` (HTTP 400), except that a window duration that does not divide evenly by the session length is reported under `ERR_WINDOW_NOT_DIVISIBLE` instead.

### 2.9. Hierarchical Consistency and Derived Aggregates

Derived aggregates are maintained eagerly, never lazily: every mutation that changes an input to a derived field recomputes that field immediately within the same request, and each such recomputation is itself a mutation of the owning resource that refreshes its `updated_at` and increments its `version` — even when the client's request targeted a different resource. Adding, cancelling, or no-showing a sign-up claim recomputes the booking's `booked_chair_minutes`; completing a claim recomputes `delivered_chair_minutes`; issuing, paying, or voiding an invoice recomputes the account's `outstanding_balance_cents`; a newly submitted survey recomputes the therapist's `rating_avg_x100`. The same consistency principle drives system-initiated transitions without an explicit client request: chairs complete automatically once their booking completes and all of their claims are terminal, claims cascade to `NO_SHOW` when their chair is marked as such, and licenses expire as the logical clock passes their expiry date.

### 2.10. Nested Resource Retrieval

Requests that target nested paths — an account's bookings, a booking's chair slots, a chair's claims, a claim's waivers — validate path identifiers strictly left-to-right. Each identifier must resolve to an existing resource before the next is examined, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that fails to resolve. Existence checking therefore always precedes any business-rule evaluation for the nested target.

## 3. Business Logic & Workflows

### 3.1. Service Regions and Corporate Accounts

Before any event can be booked, a `PlatformAdmin` defines the service geography. Each region is registered with a unique `code` (such as 'SF-BAY' or 'NYC-MAN'), a human-readable `name`, and the economic parameters that govern travel and scheduling there: `base_mileage_rate_cents` is the per-mile reimbursement in cents for travel within the region, `travel_included_miles` is the mileage included at no charge before per-mile billing applies, `setup_buffer_minutes` is the mandatory gap between a therapist's arrival and the first session start, and `teardown_buffer_minutes` is the mandatory gap between the last session's end and departure. All four numeric parameters must be zero or greater. A region's `is_active` flag defaults to true; an inactive region refuses to let new bookings open scheduling, surfacing `ERR_REGION_INACTIVE` (§3.3).

Corporate customers are onboarded as accounts carrying the legal `company_name`, the `billing_email` that receives invoices, the `region_id` of the account's home region, and a `credit_limit_cents` ceiling — zero or greater — on outstanding invoiced balance. An account begins in `ACTIVE` status. Two computed counters track fiscal exposure: `outstanding_balance_cents`, the sum of `total_cents` across the account's invoices that have been issued and remain unsettled — that is, invoices in `ISSUED` or `DISPUTED` status, with paid and voided invoices excluded — and `lifetime_billed_cents`, the cumulative `total_cents` of every invoice ever issued to the account, paid ones included. Both start at zero.

Account health is managed by a `PlatformAdmin`. Suspension moves an account from `ACTIVE` to `SUSPENDED` and, as a cascade, pauses every one of its wellness programs currently `ACTIVE` (§3.5). Reactivation returns a `SUSPENDED` account to `ACTIVE`. Closure is permitted only from `SUSPENDED` and only while `outstanding_balance_cents` is exactly zero; closing moves the account to its terminal `CLOSED` status and terminates every one of its wellness programs still in `PAUSED`. While an account is not `ACTIVE`, attempts to move its bookings into scheduling are rejected with `ERR_ACCOUNT_SUSPENDED`.

### 3.2. Therapist Onboarding, Licensing, and Compliance Review

A `PlatformAdmin` onboards each therapist with a `full_name`, a contact `email` that is unique per therapist, the `home_region_id` whose mileage and setup rules apply to that therapist by default, a `per_hour_rate_cents` used for payout computation — notably not what the customer pays — and a `max_minutes_per_day` safety cap, at least 30, on the therapist's total booked chair-minutes across all bookings on a single calendar date. Therapists begin `ACTIVE` and accumulate a computed `rating_avg_x100`: the rolling average of the therapist's last ten submitted satisfaction-survey ratings, multiplied by 100 and rounded half-up, or 0 while no surveys exist.

Therapist status is admin-managed. Suspension moves a therapist `ACTIVE` → `SUSPENDED`; reactivation moves `SUSPENDED` → `ACTIVE` and is offered from `SUSPENDED` only; deactivation is terminal, moving `SUSPENDED` → `DEACTIVATED`, and is permitted only when the therapist holds no chair slot in `ASSIGNED`, `EN_ROUTE`, or `ON_SITE` status.

Licensing is jurisdictional. A `PlatformAdmin` registers each license with the `therapist_id` of the licensee, the `region_id` of the jurisdiction in which it is valid, the government-issued `license_number` — unique within the therapist-and-region pair — the `issued_on` date, and an `expires_on` date that must fall strictly after `issued_on`. Licenses begin `ACTIVE`. Compliance review can suspend a license: the suspension request carries a free-text `reason`, which the server records in the license's `suspension_reason`. Suspension never unassigns chairs retroactively, but it blocks any later booking confirmation that depends on the license (§3.4). Reinstatement (`SUSPENDED` → `ACTIVE`) requires the expiry date to be on or after the current logical date, and clears `suspension_reason`. Revocation (`ACTIVE` → `REVOKED`) is terminal and cascades: every `ASSIGNED` chair slot staffed by that therapist whose booking is delivered in the license's region and whose `event_date` falls on or after the current logical date transitions to `RELEASED`, and each such release decrements the therapist's booked-minutes tally for that date. Licenses also expire automatically — when the current logical date passes `expires_on`, a license in `ACTIVE` or `SUSPENDED` transitions to `EXPIRED`, and the same sweep runs whenever the administrative clock is advanced.

### 3.3. Composing an Event Booking

An `Organizer` composes a one-off event by supplying the `corporate_account_id` being billed, the delivery `region_id`, the `site_address` of the chair-massage site, the `event_date`, the `window_start_minutes` at which the first session may start, the `window_duration_minutes` of the total on-site window (at least 30), the `chair_count` requested (at least 1), the per-recipient `slot_minutes` (at least 5), and the customer-facing `per_minute_rate_cents` charged per chair-minute before discounts (at least 1). The on-site window must divide evenly into whole sessions — `window_duration_minutes` must be an exact multiple of `slot_minutes` — or creation fails with `ERR_WINDOW_NOT_DIVISIBLE`; other malformed values, such as an out-of-range integer or a badly formatted date, fail with `ERR_INVALID_REQUEST`. A new booking is stamped with `booking_kind` `EVENT`, an operational `status` of `DRAFT`, and a parallel `billing_status` of `UNBILLED`. The billing dimension takes values `UNBILLED`, `INVOICED`, `PAID`, `DISPUTED`, and `VOID` and evolves independently of the operational posture, driven by invoice events rather than booking actions (§3.8). Its `wellness_program_id` is null, and `booked_chair_minutes`, `delivered_chair_minutes`, and `cancellation_fee_cents` all start at zero.

Opening scheduling moves the booking `DRAFT` → `SCHEDULING`. This is permitted only while the owning corporate account is `ACTIVE` (otherwise `ERR_ACCOUNT_SUSPENDED`) and the delivery region is active (otherwise `ERR_REGION_INACTIVE`). The transition materializes the chair plan: `chair_count` chair-slot rows are created, numbered by `chair_index` from 0 up to `chair_count` minus one, each in `UNASSIGNED` status with a null `therapist_id`, and the booking's `version` increments.

### 3.4. Staffing Chairs and Confirming the Booking

Staffing happens chair by chair. An `Organizer` assigns a therapist by naming a `therapist_id` for a chair that is `UNASSIGNED`, while the booking is `SCHEDULING`, and the candidate therapist is `ACTIVE`. Three business checks then run in a fixed order — daily cap first, license second, double-booking third.

The daily-load safety cap comes first: the therapist's booked-minutes tally for the booking's `event_date` is the sum of the per-session length over every one of the therapist's chairs in `ASSIGNED`, `EN_ROUTE`, or `ON_SITE` status on bookings occurring that date; adding the candidate booking's chair commitment — computed as the whole number of sessions that fit inside the booking's on-site window, multiplied by the per-session length — must not push that tally above the therapist's `max_minutes_per_day`, or the assignment is rejected with `ERR_THERAPIST_DAILY_CAP`. Second, license validity: the candidate must hold a license in the booking's delivery region that is `ACTIVE` and whose `expires_on` falls on or after the `event_date`, otherwise `ERR_LICENSE_INVALID`. Third, the double-booking scan: the candidate must have no other chair in `ASSIGNED`, `EN_ROUTE`, or `ON_SITE` status on any booking sharing the same `event_date` whose time window overlaps this booking's window, where each window is extended by the `setup_buffer_minutes` before it and the `teardown_buffer_minutes` after it of the region in which that booking is delivered. Windows are treated as half-open intervals, so back-to-back engagements where one extended window ends exactly when the other begins are permitted; a genuine overlap is rejected with `ERR_THERAPIST_DOUBLE_BOOKED`. On success the chair transitions `UNASSIGNED` → `ASSIGNED`, its `assigned_at` timestamp is set, and its `version` increments.

Confirmation moves the booking `SCHEDULING` → `CONFIRMED`. Every chair must be `ASSIGNED`; the license check is re-evaluated for every therapist assigned on the booking (`ERR_LICENSE_INVALID` on failure); and the buffer-extended double-booking scan is re-run across all of the booking's assigned therapists (`ERR_THERAPIST_DOUBLE_BOOKED` on failure). Confirmation is also guarded by optimistic concurrency: the request must carry `expected_booking_version` equal to the booking's current `version`, and because each assignment or release on the booking advances that version, a client confirming against a version the server has since advanced is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412) rather than allowed to confirm a staffing plan it has not observed. A successful confirmation creates the travel plan: for each assigned therapist, a travel leg is created in `PLANNED` status with `travel_fee_variant` `QUOTED`, provided none already exists for that booking-and-therapist pair. Each leg records the departure `origin_address`, the one-way `distance_miles` (zero or greater), and a computed `travel_fee_cents`. Under the `QUOTED` variant — the organizer-facing cost preview used at confirmation time — the billable distance is the leg's `distance_miles` reduced by the region's `travel_included_miles`, floored at zero, and the fee is that billable distance multiplied by the region's `base_mileage_rate_cents`.

An `Organizer` may also release an `ASSIGNED` chair while the booking is `SCHEDULING` or `CONFIRMED`, moving it to `RELEASED`. The chair retains its `therapist_id` for audit and may be assigned anew; the therapist's booked-minutes tally for the `event_date` is decremented; and if the released therapist has no other `ASSIGNED` chair remaining on the booking, that therapist's `PLANNED` travel leg for the booking transitions to `WAIVED`.

### 3.5. Recurring Wellness Programs

Recurring engagements are modeled as wellness programs owned by a corporate account. An `Organizer` creates one with the owning `corporate_account_id`, a program `name` such as 'Q3 Engineering Wellness', a `cadence` of `WEEKLY`, `BIWEEKLY`, or `MONTHLY`, the `chair_count` requested per occurrence, the per-recipient `slot_minutes` (at least 5), the `window_start_time` of day at which each occurrence begins, the `window_duration_minutes` of the per-occurrence on-site window — at least the session length and, as with one-off bookings, an exact multiple of it or creation fails with `ERR_WINDOW_NOT_DIVISIBLE` — and a `recurrence_discount_pct` between 0.00 and 0.50 that is applied to the chair-minute subtotal on each recurring occurrence's invoice. A new program is `ACTIVE`, with `occurrences_materialized` at 0 and a computed `next_occurrence_date`.

The next occurrence date is always strictly after the current logical date; when the current date itself matches the schedule, the program advances to the following cycle. For `WEEKLY` programs it is the next date matching the program's anchor weekday on a seven-day cycle. `BIWEEKLY` programs follow the same weekday logic on a fourteen-day cycle anchored at the program's creation date. `MONTHLY` programs land on the same calendar day-of-month in the following month, clamped to the last day of the month for short months — a January 31 anchor yields February 28. The value is recomputed at creation, on resume, and after each materialization, and it is null while the program is `PAUSED` or `TERMINATED`.

An `Organizer` of the account that owns the program may pause an `ACTIVE` program, which sets `next_occurrence_date` to null; resume a `PAUSED` program, which recomputes it; or terminate the program from either `ACTIVE` or `PAUSED`. Termination is terminal but deliberately does not cancel bookings already materialized from the program — those live out their own lifecycle.

Each occurrence is produced by materializing the next booking: an `Organizer` or `PlatformAdmin` supplies the `event_date`, and the platform creates a booking whose `booking_kind` is `RECURRING_OCCURRENCE`, whose `wellness_program_id` points back to the program, and whose `slot_minutes`, `chair_count`, and on-site window are copied from the program. The operation is idempotent per `next_occurrence_date`, advances the program's schedule per its cadence, and increments `occurrences_materialized` by one. The materialized booking then flows through the ordinary booking lifecycle — scheduling opens, chairs are staffed, and so on.

### 3.6. Event Day: Travel, Arrival, and the Sign-Up Sheet

On the `event_date` itself, each assigned therapist drives their own chair through its travel posture. Departing transitions a chair `ASSIGNED` → `EN_ROUTE`; it is accepted only from the therapist named on the chair — the caller's `X-User-ID` must equal the chair's `therapist_id` — and only when the current logical date equals the booking's `event_date`. Arriving transitions the chair `EN_ROUTE` → `ON_SITE` under the same identity check and stamps `arrived_at`. Once at least one chair is `ON_SITE` and the current logical date is the `event_date`, the `Organizer` starts service, moving the booking `CONFIRMED` → `IN_PROGRESS`.

Meanwhile the sign-up sheet fills. An `Organizer` claims a slot on a specific chair by supplying the `recipient_name`, the `recipient_email`, and `expected_chair_slot_version`. The sign-up sheet is a shared surface: every claim, cancellation, or no-show marking on a chair advances that chair's `version`, so a claim submitted against a version the server has since advanced is rejected with `ERR_STALE_CHAIR_SLOT_VERSION` (HTTP 412). Each new claim takes the next free `slot_ordinal`, defined as the current count of non-`CANCELLED` claims on that chair, and its `start_offset_minutes` — the point within the on-site window at which the session begins — is that ordinal multiplied by the booking's `slot_minutes`. Two checks guard the sheet, evaluated capacity first: the new claim must fit the window, meaning one more than the new claim's `slot_ordinal`, multiplied by `slot_minutes`, must not exceed `window_duration_minutes` (otherwise `ERR_SIGNUP_SHEET_FULL`); and the `recipient_email` must not already hold a non-`CANCELLED` claim on the same booking (otherwise `ERR_DUPLICATE_SIGNUP`). A created claim begins `CLAIMED`, carries its `chair_slot_id` plus a denormalized `booking_id` for direct filtered-list reads, has a null `waiver_id`, and its arrival adds the booking's `slot_minutes` to `booked_chair_minutes`, incrementing both the chair's and the booking's `version` — the latter being a derived-field mutation.

Every recipient must sign a waiver before sitting down. The `Organizer` records a waiver for a claim by supplying the `booking_id`, a `signer_email` that must equal the claim's `recipient_email`, and a non-empty, opaque `signature_payload`; the server stamps `signed_at`, binds the waiver to the claim through the waiver's `slot_claim_id`, and points the claim's `waiver_id` at the new waiver. A `PlatformAdmin` may later revoke a waiver, which stamps its `revoked_at`. Check-in transitions a claim `CLAIMED` → `CHECKED_IN` and is permitted only while the booking is `IN_PROGRESS` and the claim references a waiver that has not been revoked; attempting check-in without one is rejected with `ERR_WAIVER_MISSING`. A successful check-in stamps `checked_in_at` and leaves the booked-minutes tally untouched, since the claim was already counted.

### 3.7. Delivering Sessions and Closing Out the Booking

The therapist working a chair marks each checked-in session done. Completing a claim moves it `CHECKED_IN` → `COMPLETED`, requires the caller to be the therapist assigned to the claim's parent chair, stamps `completed_at`, and recomputes the booking's `delivered_chair_minutes` — the sum of `slot_minutes` over the booking's `COMPLETED` claims — incrementing both the claim's and the booking's `version`. The `booked_chair_minutes` tally, by contrast, sums `slot_minutes` over claims in `CLAIMED`, `CHECKED_IN`, or `COMPLETED` status and does not change at completion. An `Organizer` may cancel a `CLAIMED` claim while the booking is `SCHEDULING`, `CONFIRMED`, or `IN_PROGRESS`, moving it to `CANCELLED`, or mark it `NO_SHOW`; either way the claim leaves the booked-minutes tally, which is recomputed, and both versions increment again.

Chairs and claims also fail together. Once the current logical date has passed the `event_date`, an `Organizer` may mark an `ASSIGNED` chair `NO_SHOW`, which cascades every `CLAIMED` claim on that chair to `NO_SHOW`. And when the booking completes, any `ON_SITE` chair whose claims have all reached a terminal state transitions automatically to `COMPLETED`.

Closing out the service, the `Organizer` completes the booking (`IN_PROGRESS` → `COMPLETED`); the transition is refused with `ERR_CLAIMS_OUTSTANDING` while any claim remains in `CLAIMED` or `CHECKED_IN`, since every claim must first reach `COMPLETED`, `NO_SHOW`, or `CANCELLED`. Completion settles the money. Each travel leg still `PLANNED` is recomputed under the `SETTLED` variant: the billable distance is again the `distance_miles` reduced by the region's `travel_included_miles`, floored at zero, multiplied by the `base_mileage_rate_cents` — but when the therapist completed twenty or more sessions on this booking, a high-volume discount of twenty percent of that base amount, floored to whole cents, is subtracted. The leg's `travel_fee_variant` flips to `SETTLED` and its status to `REIMBURSED`.

Completion also posts the payout ledger: one `EARNING` entry per therapist with at least one `COMPLETED` claim on the booking, and one `TRAVEL_REIMBURSEMENT` entry per leg moving to `REIMBURSED`. Every ledger entry records the payee `therapist_id`, the source `booking_id`, an `entry_kind` of `EARNING`, `TRAVEL_REIMBURSEMENT`, or `ADJUSTMENT` — the last reserved for administrative corrections, for which a `memo` is required — a signed `amount_cents` that is positive when owed to the therapist and negative for clawbacks, and a server-stamped `posted_at`. The earning amount pins per-line rounding: for each of the therapist's completed claims on the booking, the line is the booking's `slot_minutes` multiplied by the therapist's `per_hour_rate_cents` divided by sixty minutes per hour, rounded half-up to whole cents; the entry's amount is the integer sum of those per-line amounts. Rounding each line before summing is mandatory — summing first and rounding once can drift the total by cents.

Cancellation follows a tiered policy. Cancelling from `DRAFT` is free and records a `cancellation_fee_cents` of 0. Cancelling from `SCHEDULING` is likewise free, and every `ASSIGNED` chair is set to `RELEASED`. Cancelling from `CONFIRMED` releases the same chairs — each release decrementing the therapist's booked-minutes tally for the `event_date` — waives every `PLANNED` travel leg on the booking, zeroing its `travel_fee_cents`, which in turn reduces the `travel_fees_cents` of any draft invoice already created for the booking, and assesses a fee on the booking's committed value, defined as `booked_chair_minutes` multiplied by `per_minute_rate_cents`. The fee tier depends on the whole hours, rounded down, from the current moment until the event start — the `event_date` at `window_start_minutes`: fewer than 24 hours out, the fee is fifty percent of the committed value, floored to whole cents; at least 24 hours but fewer than 72 hours, twenty-five percent; at least 72 hours but fewer than 168 hours — one week — ten percent; and at 168 hours or more, no fee at all.

### 3.8. Invoicing, Payment, Disputes, and Satisfaction Credits

Billing is invoice-driven, and exactly one live invoice — one in `DRAFT`, `ISSUED`, or `DISPUTED` status — may exist per booking at any time; attempting to create a second, or to issue while another live invoice exists for the booking, is rejected with `ERR_LIVE_INVOICE_EXISTS`. A `PlatformAdmin` creates the draft invoice for a booking by choosing a `pricing_variant`. Under `PROVISIONAL`, available while the booking is `CONFIRMED` or `IN_PROGRESS` for deposit-style pre-billing as well as for what-if previews, the billable volume `chair_minutes_billed` is the booking's `booked_chair_minutes`. Under `FINAL`, used for `COMPLETED` or `CANCELLED` bookings, it is the booking's `delivered_chair_minutes` — zero for a cancelled booking, where the cancellation fee dominates. The invoice's `corporate_account_id` is denormalized from its booking at issuance.

The invoice's `subtotal_cents` is the billable volume multiplied by the booking's `per_minute_rate_cents` — exact integer arithmetic, with no rounding. The recurrence tier is then read off the undiscounted subtotal: an `EVENT` booking is `STANDARD` and its `recurrence_discount_cents` is 0; a `RECURRING_OCCURRENCE` booking whose wellness program has not been `TERMINATED` is `RECURRING`, and its discount is the subtotal multiplied by the program's `recurrence_discount_pct`, floored to whole cents. The invoice's `travel_fees_cents` sums the `travel_fee_cents` of the booking's legs in `PLANNED` or `REIMBURSED` status — `WAIVED` legs contribute nothing — and its `cancellation_fee_cents` is copied from the booking when the invoice bills a cancelled booking. While the invoice remains `DRAFT`, these totals recompute whenever an underlying source field changes.

Satisfaction surveys feed a credit. An `Organizer` may submit a survey for a claim once the claim is `COMPLETED` and its booking is `IN_PROGRESS` or `COMPLETED` — otherwise `ERR_BOOKING_NOT_COMPLETED` — providing a `rating` from 1 to 5 and an optional `comment` that defaults to empty; the server stamps `submitted_at`. At most one survey exists per claim, and a second submission is rejected with `ERR_DUPLICATE_SURVEY`. Each submission recomputes the therapist's `rating_avg_x100` over the therapist's last ten surveys — incrementing the therapist's `version` — and, while the booking's invoice is still `DRAFT`, recomputes `satisfaction_credit_cents`. The credit tiers on the average rating across the surveys attached to the booking's completed claims: with no surveys the credit is 0; otherwise the average is the sum of the ratings divided by their count, multiplied by 100 and rounded half-up. An average strictly below 2.00 earns a credit of twenty-five percent of the subtotal, floored to whole cents; an average of 2.00 or higher but below 3.00 earns ten percent; an average of 3.00 or higher earns nothing. The boundary is exact — an average of 1.99 earns twenty-five percent while an average of exactly 2.00 earns only ten. Finally, the invoice's `total_cents` is the subtotal minus the recurrence discount, plus the travel fees, plus the cancellation fee, minus the satisfaction credit, floored at zero.

Issuance moves the invoice `DRAFT` → `ISSUED`, stamps `issued_at`, and requires the booking to be `COMPLETED` or `CANCELLED`. Two guards apply, the credit check first: issuance may not push the account's outstanding balance above its `credit_limit_cents` — the post-issue outstanding, meaning the current `outstanding_balance_cents` plus this invoice's `total_cents`, must stay within the limit, otherwise `ERR_CREDIT_LIMIT_EXCEEDED` — and no other live invoice may exist for the booking. On success, `outstanding_balance_cents` and `lifetime_billed_cents` each increase by `total_cents`, and the booking's `billing_status` moves `UNBILLED` → `INVOICED`.

Payment recording moves the invoice `ISSUED` → `PAID`, subtracts `total_cents` from `outstanding_balance_cents`, and moves `billing_status` to `PAID`. An `Organizer` of the account that owns the invoice's booking may instead dispute an `ISSUED` invoice; a non-empty `dispute_reason` is required, and an empty one fails with `ERR_DISPUTE_REASON_REQUIRED`. Dispute moves `billing_status` to `DISPUTED` but deliberately leaves the outstanding balance unchanged — disputed invoices still count toward credit utilization. A `PlatformAdmin` resolves a dispute by returning the invoice `DISPUTED` → `ISSUED`, moving `billing_status` back to `INVOICED`; resolution preserves the disputed numbers, since totals are not recomputed, so any adjustment requires voiding and re-issuing. Voiding is permitted from `DRAFT` or `DISPUTED`. From `DRAFT`, nothing was ever counted, the balance is untouched, and the booking's `billing_status` stays `UNBILLED`. From `DISPUTED`, the invoice's `total_cents` is subtracted back out of `outstanding_balance_cents` and `billing_status` returns to `UNBILLED`, freeing the booking to be invoiced again.

## 4. Endpoint Definitions

Operations that create a new resource — a region, corporate account, wellness program, therapist, license, event booking, materialized occurrence, draft invoice, sign-up claim, waiver, or satisfaction survey — return a `201 Created` status code. Operations that modify an existing resource, including all state-transition actions, return `200 OK`. The table below is a summary only; the request payloads, computed fields, and side effects of each operation are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/chair-massage/_clock/set_current_utc` | Advance the server's logical clock | PlatformAdmin |
| POST | `/chair-massage/regions` | Create a service region | PlatformAdmin |
| GET | `/chair-massage/regions` | List regions (paginated) | PlatformAdmin, Organizer, Therapist |
| GET | `/chair-massage/regions/{id}` | Fetch a region | PlatformAdmin, Organizer, Therapist |
| POST | `/chair-massage/corporate-accounts` | Onboard a corporate account | PlatformAdmin |
| GET | `/chair-massage/corporate-accounts` | List corporate accounts (paginated) | PlatformAdmin |
| GET | `/chair-massage/corporate-accounts/{id}` | Fetch one corporate account | PlatformAdmin, Organizer |
| POST | `/chair-massage/corporate-accounts/{id}/suspend` | Suspend account (cascades pause to ACTIVE wellness programs) | PlatformAdmin |
| POST | `/chair-massage/corporate-accounts/{id}/reactivate` | Reactivate a suspended account | PlatformAdmin |
| POST | `/chair-massage/corporate-accounts/{id}/close` | Close account (requires zero outstanding balance; cascades terminate PAUSED wellness programs) | PlatformAdmin |
| GET | `/chair-massage/corporate-accounts/{id}/wellness-programs` | List wellness programs owned by account | PlatformAdmin, Organizer |
| GET | `/chair-massage/corporate-accounts/{id}/bookings` | List bookings of account | PlatformAdmin, Organizer |
| GET | `/chair-massage/corporate-accounts/{id}/invoices` | List invoices billed to account | PlatformAdmin, Organizer |
| POST | `/chair-massage/wellness-programs` | Create a recurring wellness program | Organizer |
| GET | `/chair-massage/wellness-programs` | List wellness programs (paginated) | PlatformAdmin, Organizer |
| GET | `/chair-massage/wellness-programs/{id}` | Fetch one program | PlatformAdmin, Organizer |
| POST | `/chair-massage/wellness-programs/{id}/pause` | Pause recurrence | Organizer |
| POST | `/chair-massage/wellness-programs/{id}/resume` | Resume recurrence | Organizer |
| POST | `/chair-massage/wellness-programs/{id}/terminate` | Terminate recurrence | Organizer |
| GET | `/chair-massage/wellness-programs/{id}/bookings` | List bookings materialized from this program | PlatformAdmin, Organizer |
| POST | `/chair-massage/wellness-programs/{id}/materialize-occurrence` | Materialize the next recurring-occurrence booking for this program | Organizer, PlatformAdmin |
| POST | `/chair-massage/therapists` | Onboard a therapist | PlatformAdmin |
| GET | `/chair-massage/therapists` | List therapists (paginated) | PlatformAdmin, Organizer |
| GET | `/chair-massage/therapists/{id}` | Fetch one therapist | PlatformAdmin, Organizer, Therapist |
| POST | `/chair-massage/therapists/{id}/suspend` | Suspend a therapist | PlatformAdmin |
| POST | `/chair-massage/therapists/{id}/reactivate` | Reactivate a suspended therapist | PlatformAdmin |
| POST | `/chair-massage/therapists/{id}/deactivate` | Deactivate (terminal) a suspended therapist | PlatformAdmin |
| GET | `/chair-massage/therapists/{id}/licenses` | List licenses held by therapist | PlatformAdmin, Organizer, Therapist |
| GET | `/chair-massage/therapists/{id}/chair-slots` | List chair-slots assigned to therapist | PlatformAdmin, Organizer, Therapist |
| GET | `/chair-massage/therapists/{id}/travel-legs` | List travel legs of a therapist | PlatformAdmin, Organizer, Therapist |
| GET | `/chair-massage/therapists/{id}/payout-ledger-entries` | List payout ledger entries for therapist | PlatformAdmin, Therapist |
| POST | `/chair-massage/therapist-licenses` | Register a license for a therapist | PlatformAdmin |
| GET | `/chair-massage/therapist-licenses` | List licenses (paginated) | PlatformAdmin, Organizer |
| GET | `/chair-massage/therapist-licenses/{id}` | Fetch one license | PlatformAdmin, Organizer, Therapist |
| POST | `/chair-massage/therapist-licenses/{id}/suspend` | Suspend license | PlatformAdmin |
| POST | `/chair-massage/therapist-licenses/{id}/reinstate` | Reinstate a suspended license | PlatformAdmin |
| POST | `/chair-massage/therapist-licenses/{id}/revoke` | Revoke license (terminal); cascades chair-slot release | PlatformAdmin |
| POST | `/chair-massage/bookings` | Create a one-off EVENT booking (DRAFT) | Organizer |
| GET | `/chair-massage/bookings` | List bookings (paginated) | PlatformAdmin, Organizer, Therapist |
| GET | `/chair-massage/bookings/{id}` | Fetch one booking | PlatformAdmin, Organizer, Therapist |
| POST | `/chair-massage/bookings/{id}/open-scheduling` | Move DRAFT to SCHEDULING; materializes chair slots | Organizer |
| POST | `/chair-massage/bookings/{id}/confirm` | Move SCHEDULING to CONFIRMED (OCC-guarded) | Organizer |
| POST | `/chair-massage/bookings/{id}/start-service` | Move CONFIRMED to IN_PROGRESS (must be event date, at least one chair ON_SITE) | Organizer |
| POST | `/chair-massage/bookings/{id}/complete` | Move IN_PROGRESS to COMPLETED; posts payout ledger, settles travel fees | Organizer |
| POST | `/chair-massage/bookings/{id}/cancel` | Cancel from DRAFT/SCHEDULING/CONFIRMED; tiered cancellation fee applies from CONFIRMED | Organizer |
| GET | `/chair-massage/bookings/{id}/chair-slots` | List chair-slots of booking | PlatformAdmin, Organizer, Therapist |
| GET | `/chair-massage/bookings/{id}/slot-claims` | List slot-claims (sign-up sheet) of booking | PlatformAdmin, Organizer, Therapist |
| GET | `/chair-massage/bookings/{id}/travel-legs` | List travel legs of booking | PlatformAdmin, Organizer, Therapist |
| GET | `/chair-massage/bookings/{id}/payout-ledger-entries` | List payout ledger entries posted against this booking | PlatformAdmin, Organizer |
| GET | `/chair-massage/bookings/{id}/invoices` | List invoices for booking (at most one non-VOID at any time) | PlatformAdmin, Organizer |
| POST | `/chair-massage/bookings/{id}/invoices` | Create a DRAFT invoice for this booking | PlatformAdmin |
| GET | `/chair-massage/chair-slots` | List chair-slots (paginated, filterable) | PlatformAdmin, Organizer, Therapist |
| GET | `/chair-massage/chair-slots/{id}` | Fetch one chair-slot | PlatformAdmin, Organizer, Therapist |
| POST | `/chair-massage/chair-slots/{id}/assign` | Assign a therapist to this chair | Organizer |
| POST | `/chair-massage/chair-slots/{id}/depart` | Therapist marks ASSIGNED to EN_ROUTE on the event date | Therapist |
| POST | `/chair-massage/chair-slots/{id}/arrive` | Therapist marks EN_ROUTE to ON_SITE | Therapist |
| POST | `/chair-massage/chair-slots/{id}/release` | Organizer releases an ASSIGNED chair | Organizer |
| POST | `/chair-massage/chair-slots/{id}/mark-no-show` | Mark an ASSIGNED chair NO_SHOW after the event date has passed | Organizer |
| POST | `/chair-massage/chair-slots/{id}/claims` | Sign-up sheet: create a claim on this chair (OCC-guarded) | Organizer |
| GET | `/chair-massage/chair-slots/{id}/claims` | List claims on a chair (sign-up sheet view) | PlatformAdmin, Organizer, Therapist |
| GET | `/chair-massage/slot-claims/{id}` | Fetch one slot claim | PlatformAdmin, Organizer, Therapist |
| GET | `/chair-massage/slot-claims/{id}/waivers` | List waivers for this claim | PlatformAdmin, Organizer, Therapist |
| GET | `/chair-massage/slot-claims/{id}/satisfaction-surveys` | List satisfaction surveys for this claim (at most one element) | PlatformAdmin, Organizer, Therapist |
| POST | `/chair-massage/slot-claims/{id}/check-in` | Check in a CLAIMED claim (requires active waiver) | Organizer |
| POST | `/chair-massage/slot-claims/{id}/complete` | Therapist marks CHECKED_IN to COMPLETED | Therapist |
| POST | `/chair-massage/slot-claims/{id}/cancel` | Cancel a CLAIMED claim | Organizer |
| POST | `/chair-massage/slot-claims/{id}/mark-no-show` | Mark a CLAIMED claim NO_SHOW (post-event) | Organizer |
| POST | `/chair-massage/slot-claims/{id}/waiver` | Sign a waiver for this claim | Organizer |
| POST | `/chair-massage/slot-claims/{id}/satisfaction-surveys` | Submit satisfaction survey for a COMPLETED claim (at most one) | Organizer |
| GET | `/chair-massage/travel-legs/{id}` | Fetch one travel leg | PlatformAdmin, Organizer, Therapist |
| GET | `/chair-massage/waivers/{id}` | Fetch one waiver | PlatformAdmin, Organizer, Therapist |
| GET | `/chair-massage/waivers/{id}/slot-claims` | List slot-claims referencing this waiver (at most one element) | PlatformAdmin, Organizer, Therapist |
| POST | `/chair-massage/waivers/{id}/revoke` | Revoke a signed waiver | PlatformAdmin |
| GET | `/chair-massage/bookings/{id}/waivers` | List waivers under a booking | PlatformAdmin, Organizer |
| GET | `/chair-massage/invoices` | List invoices (paginated) | PlatformAdmin, Organizer |
| GET | `/chair-massage/invoices/{id}` | Fetch one invoice | PlatformAdmin, Organizer |
| POST | `/chair-massage/invoices/{id}/issue` | Issue a DRAFT invoice (checks credit limit) | PlatformAdmin |
| POST | `/chair-massage/invoices/{id}/record-payment` | Record payment on an ISSUED invoice | PlatformAdmin |
| POST | `/chair-massage/invoices/{id}/dispute` | Organizer disputes an ISSUED invoice | Organizer |
| POST | `/chair-massage/invoices/{id}/resolve-dispute` | Admin resolves dispute; invoice returns DISPUTED to ISSUED | PlatformAdmin |
| POST | `/chair-massage/invoices/{id}/void` | Void a DRAFT or DISPUTED invoice | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue is a summary of identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_BOOKING_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CHAIR_SLOT_VERSION` | 412 Precondition Failed |
| `ERR_THERAPIST_DAILY_CAP` | 422 Unprocessable Entity |
| `ERR_LICENSE_INVALID` | 422 Unprocessable Entity |
| `ERR_THERAPIST_DOUBLE_BOOKED` | 422 Unprocessable Entity |
| `ERR_SIGNUP_SHEET_FULL` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SIGNUP` | 422 Unprocessable Entity |
| `ERR_WAIVER_MISSING` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_LIVE_INVOICE_EXISTS` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SURVEY` | 422 Unprocessable Entity |
| `ERR_WINDOW_NOT_DIVISIBLE` | 422 Unprocessable Entity |
| `ERR_ACCOUNT_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_REGION_INACTIVE` | 422 Unprocessable Entity |
| `ERR_BOOKING_NOT_COMPLETED` | 422 Unprocessable Entity |
| `ERR_CLAIMS_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_DISPUTE_REASON_REQUIRED` | 400 Bad Request |
