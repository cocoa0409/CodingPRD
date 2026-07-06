# House-Sitting & Home-Watch Service API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a professional house-sitting and home-watch platform. When a homeowner travels — for a weekend or for a month — the platform dispatches vetted, insured sitters to their property to perform a recurring service checklist: collecting the mail, watering the plants, and confirming that the home is secure. Every visit is evidenced with photographs and GPS pings, every sitter is background-checked and bonded, every physical key copy is tracked in and out of the office, and every completed visit is priced and rolled up into a single per-booking invoice.

The platform serves three kinds of actors whose concerns rarely overlap. Homeowners (the **Client** role) register their properties, book coverage, and settle invoices. Field staff (the **Sitter** role) travel to properties, perform and evidence visits, report incidents, and carry keys. Operations staff (the **Coordinator** role) run the back office: they onboard clients and sitters, order and adjudicate background checks, issue insurance and bond policies, assign sitters to bookings, manage key custody, and handle incidents and billing. The rules that bind these actors together are unforgiving by design — a sitter may not be assigned without a current clearance and an active bond, a visit may not be closed without evidence and a completed checklist, and a booking may not be billed until every one of its visits has reached a terminal outcome.

Because the domain is money- and liability-sensitive, the service is built around an explicit, test-driven logical clock and around deterministic financial arithmetic. Charges are provisional at the moment a visit closes and are recomputed to a final figure when the booking completes; insurance exposure is reserved when an incident escalates and settled when it resolves. The sections that follow describe the global contract every endpoint honours (Section 2), the business workflows and their scattered rules (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognises exactly three roles, spelled precisely as `Coordinator`, `Client`, and `Sitter`.

The `Coordinator` role is an opaque operator identity: `X-User-ID` for a coordinator is an operator identifier not tied to any persisted entity. The server may record it where a workflow captures the acting operator, but it never compares a coordinator's `X-User-ID` to any entity's `id`.

The `Client` role is entity-backed. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's owning-client foreign key to `X-User-ID`. A client may register a property only under its own identity (the property's `client_id` must equal `X-User-ID`), may book, submit, and cancel only its own bookings, and may pay only its own invoices.

The `Sitter` role is likewise entity-backed. When `X-User-Role` is `Sitter`, `X-User-ID` is the `id` of the acting `Sitter`; ownership checks on any resource that references a `Sitter` compare the resource's sitter foreign key to `X-User-ID`. A sitter may check in, check out, and log evidence only on visits whose `sitter_id` is its own, and files an incident only against such a visit. When a caller acts on a resource it does not own under this rule, the request is rejected with `ERR_FORBIDDEN_NOT_OWNER` (HTTP 403).

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

All list endpoints are paginated through two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100; a supplied value outside this range is clamped to the nearest bound rather than rejected. The `offset` parameter defaults to 0 and represents the number of records to skip; a negative offset is clamped to 0. A `limit` or `offset` that cannot be parsed as an integer falls back to its default (10 and 0 respectively). Collections are returned sorted by `created_at` in ascending order (oldest first), with ties broken by ascending creation sequence (insertion order). The `meta` block of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the size of the full filtered collection and `has_more` is true when records remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` that is a UUID carrying no type prefix. Every resource also records a `created_at` timestamp, an ISO 8601 UTC instant with three fractional digits captured from the logical clock at creation.

Most resources additionally carry an `updated_at` timestamp and an integer `version`. On creation, `version` is 1 and `updated_at` equals `created_at`; on every mutation that changes the resource, `updated_at` is refreshed to the current clock instant and `version` is incremented by one. The single exception is the visit log entry, which is an append-only piece of evidence: it carries only `id` and `created_at`, and has neither an `updated_at` nor a `version` field, because once written it is never modified.

### 2.5. Path Resolution, Referential Existence, and the Logical Clock

Resource identifiers named in a request path or body are resolved left to right, and the first one that does not correspond to a stored resource fails the request with the corresponding not-found error (for example `ERR_CLIENT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_SITTER_NOT_FOUND`, `ERR_BGCHECK_NOT_FOUND`, `ERR_COVERAGE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_VISITLOG_NOT_FOUND`, `ERR_KEY_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND`), each returned with HTTP 404.

The service keeps a single logical clock that governs every timestamp and every time-dependent rule (clearance expiry, coverage windows, visit windows, and incident timing). On startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly set it never falls back to wall-clock time. An administrative test-driving capability sets the clock to a supplied instant carried in the `to_iso8601` field; all subsequent time comparisons use the value most recently set.

### 2.6. Optimistic Concurrency Control on Coverage Policies

Issuing a coverage policy is guarded by optimistic concurrency on the sitter it covers. A create-coverage-policy request must carry `expected_sitter_version` as a required input field, holding the client's last observed `version` of the target `Sitter`. If `expected_sitter_version` does not match the sitter's current `version`, the request is rejected with `ERR_STALE_SITTER_VERSION` (HTTP 412). This protects the supersede decision: because issuing a new policy supersedes the sitter's prior active policy of the same type, a stale view of the sitter would supersede a policy the caller never saw. When a policy is issued successfully, the sitter's `version` is incremented by one, so any concurrently held stale version is thereby invalidated. No other endpoint accepts a version field.

### 2.7. Monetary Precision and Rounding

All monetary values are integer cents. Wherever a computation produces a fractional cent — a percentage discount, a service fee, a tax, a weekend multiplier, or a duration factor — the result is rounded half up to a whole number of cents. Rounding is applied once, at the final step of each named quantity, never on intermediate sub-expressions, except where a multi-step financial computation explicitly pins a rounding at each of its named steps (see the invoice roll-up in Section 3.9). Day arithmetic used to generate visit schedules is performed on whole UTC calendar days.

### 2.8. Validation Precedence

When several conditions could reject the same request, they are evaluated in a fixed order so that the returned error is deterministic. The order is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); then role authorization (`ERR_UNAUTHORIZED`); then existence of every referenced resource, left to right (the not-found family); then ownership for entity-backed actors (`ERR_FORBIDDEN_NOT_OWNER`); then well-formedness of the request body — required fields present, enumerations valid, and the recurring/vacation frequency rule satisfied (`ERR_INVALID_REQUEST`); then the state guard for the requested transition (the not-in-state family, HTTP 409); then optimistic-concurrency on coverage-policy creation (`ERR_STALE_SITTER_VERSION`); and finally the endpoint's specific business rules. Endpoint-specific orderings that matter — sitter assignment and visit check-out in particular — are stated with their workflows in Section 3.

### 2.9. Key Custody and Conservation

Each property holds a fixed number of physical key copies, `key_copies_total`, established at registration and never less than 1. The service tracks, as a derived quantity, `available_key_copies` — the number of copies currently sitting at the office, equal to `key_copies_total` minus the number of copies currently checked out and minus the number reported lost. A copy leaving the office for a sitter decrements the available count; a copy returned increments it; a copy reported lost moves from the checked-out bucket to a lost bucket, leaving the available count unchanged. Under every one of these operations the total number of copies is conserved: available plus checked-out plus lost always equals `key_copies_total`.

### 2.10. Sitter Reliability and Suspension

Every sitter carries a `reliability_score` derived from two cumulative counters: `missed_visit_count` (the number of that sitter's visits marked missed) and `escalated_incident_count` (the number of that sitter's incidents that were escalated). The score is one hundred, reduced by twenty for each missed visit and by ten for each escalated incident, and floored at zero — that is, the greater of zero and the value obtained by subtracting twenty times the missed-visit count and ten times the escalated-incident count from one hundred. The score is recomputed every time either counter changes. A sitter whose reliability score falls below the minimum reliability threshold of 60 is suspended, moving the sitter's `status` to `SUSPENDED`. The minimum reliability threshold of 60 also gates assignment (Section 3.4).

## 3. Business Logic & Workflows

### 3.1. Onboarding Clients and Registering Properties

A `Coordinator` onboards a client by supplying the client's `full_name`, `email`, and optionally a `billing_tier` of either `STANDARD` or `PREMIUM`; when omitted, the billing tier defaults to `STANDARD`. A newly created client is initialised with `status` equal to `ACTIVE`.

A property is registered under an existing client either by a `Coordinator` or by the owning `Client`. Registration supplies the owning `client_id`, a human `label` such as "Lakeside Cabin", a street `address`, a `size_tier` of `SMALL`, `MEDIUM`, or `LARGE`, an optional `has_pets` flag that defaults to false, and a non-empty `checklist_config`. The `checklist_config` is a non-empty subset drawn from the service tasks `MAIL`, `PLANTS`, and `SECURITY` that every visit to this property must complete. Registration also supplies the geofence: the property centre coordinates `center_lat` and `center_lng`, and an optional `geofence_radius_m` — the permitted check-in distance from the centre in metres — that defaults to 150. Finally it supplies `key_copies_total`, the number of physical key copies held for the property (at least one). At registration the derived `available_key_copies` equals `key_copies_total`, since no copies are yet out or lost. The `size_tier` and `has_pets` values feed the per-visit surcharges described in Section 3.6.

### 3.2. Onboarding Sitters, Clearing Background Checks, and Issuing Coverage

A `Coordinator` onboards a sitter with a `full_name` and `email`. A new sitter begins with `status` equal to `ONBOARDING`, a `background_check_status` of `NONE`, a `missed_visit_count` and `escalated_incident_count` of zero, and a `reliability_score` of 100.

Vetting begins when a coordinator submits a background check for a sitter, supplying the subject `sitter_id`, an external `provider_ref`, and an `expires_at` instant after which a cleared check is considered stale. A submitted check starts in `SUBMITTED`, and the sitter's mirrored `background_check_status` is set to `SUBMITTED`. A coordinator later adjudicates the check by supplying a `decision`. Adjudicating a check that is not in `SUBMITTED` is rejected with `ERR_BGCHECK_NOT_PENDING`. Clearing it advances the check from `SUBMITTED` to `CLEARED`, stamps `cleared_at` with the current clock, mirrors `CLEARED` onto the sitter's `background_check_status`, and — if the sitter was still `ONBOARDING` — promotes the sitter's `status` to `ACTIVE`. Rejecting it instead advances the check from `SUBMITTED` to `REJECTED` and mirrors `REJECTED` onto the sitter's `background_check_status`, with no promotion and no `cleared_at`.

Insurance and bonding are recorded as coverage policies issued by a coordinator against a sitter. A policy supplies the `sitter_id`, a `policy_type` of either `BOND` (fidelity and theft) or `LIABILITY` (property damage), a `coverage_amount_cents` of at least one, an `effective_from` instant, an `expires_at` instant, and the `expected_sitter_version` described in Section 2.6. A policy is active while the clock is at or after `effective_from` and strictly before `expires_at`. A newly issued policy is `ACTIVE`; any prior `ACTIVE` policy of the same `policy_type` for that sitter is superseded, moving to `SUPERSEDED`, and the sitter's `version` is incremented by one. A liability policy also tracks `reserved_exposure_cents` (exposure reserved by escalated, not-yet-resolved incidents) and `paid_out_cents` (cumulative settled indemnity), both starting at zero; once cumulative pay-outs reach or exceed the coverage amount the policy becomes `EXHAUSTED`, as described in Section 3.7.

### 3.3. Creating and Submitting Bookings

A booking expresses a homeowner's request for coverage over a date range. Either a `Coordinator` or the owning `Client` creates a booking against a `property_id`, choosing a `booking_type` of `RECURRING` (a repeating schedule) or `VACATION` (a single continuous coverage window), and supplying an inclusive `start_date` and inclusive `end_date` and a `base_visit_rate_cents` (the base per-visit rate before surcharges, at least zero). A recurring booking must additionally supply a `frequency` of `DAILY`, `WEEKLY`, or `BIWEEKLY`; a vacation booking must omit `frequency` entirely. A body that violates this pairing — a recurring booking with no frequency, or a vacation booking that carries one — is malformed and is rejected with `ERR_INVALID_REQUEST`. A new booking starts in `DRAFT`, and its `client_id` is copied from the property's owning client at creation; its `sitter_id` remains null until a sitter is assigned.

Submitting a booking moves it from `DRAFT` to `PENDING_ASSIGNMENT`, placing it in the assignment pool. Submission may be performed by the owning `Client` or a `Coordinator`. Submitting a booking that is not in `DRAFT` is rejected with `ERR_BOOKING_NOT_DRAFT`. The property's `checklist_config` must be non-empty at submission; an empty checklist is rejected with `ERR_CHECKLIST_CONFIG_EMPTY`. For vacation bookings only, the property must be free of conflicting vacation coverage: if any other `VACATION` booking on the same property that is currently in `PENDING_ASSIGNMENT`, `SCHEDULED`, or `ACTIVE` has an inclusive date range that overlaps the submitted booking's `[start_date, end_date]`, submission is rejected with `ERR_PROPERTY_BOOKING_OVERLAP`.

### 3.4. Assigning a Sitter and Generating the Visit Schedule

Assignment is a coordinator-only step that takes a booking from `PENDING_ASSIGNMENT` to `SCHEDULED`, binding a specific sitter to the work. The request supplies the chosen `sitter_id`. Assigning a booking that is not in `PENDING_ASSIGNMENT` is rejected with `ERR_BOOKING_NOT_PENDING_ASSIGNMENT`. Beyond that state guard, four business qualifications are evaluated in this fixed order:

1. **Clearance.** The sitter's latest background check must be `CLEARED` and still valid — the current clock must be strictly before that check's `expires_at`. A sitter who is not cleared, or whose clearance has expired, fails first with `ERR_SITTER_NOT_CLEARED`.
2. **Bond.** The sitter must hold an `ACTIVE` `BOND` coverage policy that is in its window — the clock at or after its `effective_from` and strictly before its `expires_at`. Otherwise assignment fails with `ERR_SITTER_COVERAGE_INACTIVE`.
3. **Reliability.** The sitter's `reliability_score` must be at least 60; a lower score fails with `ERR_SITTER_RELIABILITY_TOO_LOW`.
4. **Schedule.** None of the visits this booking would generate may collide with the sitter's existing `SCHEDULED` or `IN_PROGRESS` visits under the buffered-overlap rule: two visit windows conflict when the prospective visit's start is earlier than the existing visit's end extended by the buffer, and simultaneously the existing visit's start is earlier than the prospective visit's end extended by the buffer. The buffer is zero, so this reduces to a strict overlap of the two half-hour windows. Any such collision fails with `ERR_SITTER_SCHEDULE_CONFLICT`.

When all four qualifications pass, assignment records `sitter_id` on the booking, generates the visit rows, and creates the booking's invoice in `DRAFT` with a subtotal of zero.

Visit generation lays out one visit per scheduled date. For a `VACATION` booking there is one visit for each calendar day from `start_date` to `end_date` inclusive, so the number of visits equals the whole-day difference between the two dates plus one. For a `RECURRING` booking the step between visits is one day for `DAILY`, seven days for `WEEKLY`, and fourteen days for `BIWEEKLY`; visits fall on the start date and every step-day multiple thereafter for as long as the date remains at or before `end_date`, so the number of visits equals the floor of the whole-day difference divided by the step, plus one. Each generated visit inherits `booking_id`, and copies `sitter_id` and `property_id` from the booking. Its `scheduled_start` is 09:00:00Z on the scheduled date and its `scheduled_end` is thirty minutes later, at 09:30:00Z (the standard visit length is thirty minutes). Its `is_weekend` flag is true when `scheduled_start` falls on a Saturday or Sunday in UTC. Visits are generated in ascending `scheduled_start` order. Every generated visit begins in `SCHEDULED`.

If a coordinator concludes the wrong sitter was chosen, the booking can be returned to the pool. Unassigning moves the booking from `SCHEDULED` back to `PENDING_ASSIGNMENT`; a booking not in `SCHEDULED` is rejected with `ERR_BOOKING_NOT_SCHEDULED`. Unassignment cancels every `SCHEDULED` visit of the booking (moving each to `CANCELLED`), voids the booking's invoice (to `VOID`), and clears `sitter_id` back to null, so the booking can be assigned afresh.

### 3.5. Key Custody

Before a sitter can enter a property, a coordinator issues a key assignment naming the `property_id`, the entrusted `sitter_id`, and the `booking_id` the copy is issued for. A new assignment starts `AT_OFFICE`. Checking a copy out — an action available to a `Coordinator` or the `Sitter` — moves the assignment from `AT_OFFICE` to `CHECKED_OUT`, stamps `checked_out_at` with the current clock, and decrements the property's `available_key_copies` by one. A checkout attempt on an assignment not in `AT_OFFICE` is rejected with `ERR_KEY_NOT_AT_OFFICE`, and a checkout is refused with `ERR_NO_KEY_COPIES_AVAILABLE` when the property has zero copies available (`available_key_copies` less than one).

Returning a copy moves the assignment from `CHECKED_OUT` to `RETURNED`, stamps `returned_at`, and increments `available_key_copies` by one. Reporting a copy lost — a coordinator-only action — moves the assignment from `CHECKED_OUT` to `LOST`; the copy shifts from the checked-out bucket into the lost bucket and `available_key_copies` is left unchanged, so the property's total remains conserved. Both returning and reporting-lost require the assignment to be `CHECKED_OUT`; otherwise the request is rejected with `ERR_KEY_NOT_CHECKED_OUT`.

### 3.6. Activating the Booking and Running Visits

Once keys are in hand, a coordinator activates the booking, moving it from `SCHEDULED` to `ACTIVE`. Activation requires that a key assignment for this booking and its sitter is already `CHECKED_OUT`; if none is, activation is rejected with `ERR_KEY_NOT_READY`. Activating a booking not in `SCHEDULED` is rejected with `ERR_BOOKING_NOT_SCHEDULED`. Activation issues the invoice, moving it from `DRAFT` to `ISSUED`.

A sitter performs a visit by checking in and later checking out, and only the visit's own sitter may do so. Checking in moves the visit from `SCHEDULED` to `IN_PROGRESS` and stamps `check_in_at` with the current clock. Check-in requires the visit to be in `SCHEDULED` (otherwise `ERR_VISIT_NOT_SCHEDULED`) and the owning booking to be `ACTIVE` (otherwise `ERR_BOOKING_NOT_ACTIVE`). Two field conditions then apply, in order: the check-in location, supplied as `gps_lat` and `gps_lng`, must lie within the geofence — the distance from the check-in point to the property centre must be at most `geofence_radius_m` metres, and a check-in outside that radius is rejected with `ERR_OUTSIDE_GEOFENCE`; and a key assignment for this booking and this sitter must currently be `CHECKED_OUT`, failing otherwise with `ERR_KEY_NOT_CHECKED_OUT`.

During an in-progress visit the sitter appends evidence — photos, GPS pings, and notes — as visit log entries. Each entry names its `visit_id` and an `entry_type` of `PHOTO`, `GPS_PING`, or `NOTE`, carries a `photo_url` (present when the type is `PHOTO`, otherwise null), the coordinates `gps_lat` and `gps_lng` captured at the moment, and a client-supplied `captured_at` timestamp. Evidence may be appended only while the visit is in progress or flagged; appending to a visit that is neither `IN_PROGRESS` nor `FLAGGED` is rejected with `ERR_VISIT_NOT_IN_PROGRESS`. These entries are immutable once written.

Checking out closes the visit. It stamps `check_out_at` with the current clock, computes the provisional charge, and updates the invoice. Two conditions are checked in this fixed order: first, at least one visit log entry must exist for the visit, and a checkout with no evidence is rejected with `ERR_VISIT_EVIDENCE_MISSING`; second, the `completed_tasks` set supplied at checkout must exactly equal the property's `checklist_config` set, and any mismatch is rejected with `ERR_CHECKLIST_INCOMPLETE`. A checkout attempted on a visit that is neither `IN_PROGRESS` nor `FLAGGED` is rejected with `ERR_VISIT_NOT_IN_PROGRESS`.

Every closed visit carries a charge. The **provisional charge**, computed at checkout and stored in `provisional_charge_cents`, is built as follows. The size surcharge is 0 cents for a `SMALL` property, 1500 cents for a `MEDIUM` property, and 3500 cents for a `LARGE` property. The pet surcharge is 1000 cents when the property has pets and 0 otherwise. These two surcharges are added to the booking's `base_visit_rate_cents` to form the base sum. The base sum is then multiplied by the weekend multiplier — 1.25 when the visit's `is_weekend` is true, and 1.0 otherwise. That product is then multiplied by a duration factor, which for the provisional charge is fixed at 1.0 (a standard-length visit is assumed and the actual elapsed time is ignored). The resulting amount is rounded half up to whole cents in a single final rounding. On a successful checkout the provisional charge is added to the invoice's `subtotal_cents`, the invoice's `billed_visit_count` is incremented by one, and the invoice financials are recomputed as described in Section 3.9.

### 3.7. Incidents and Liability Exposure

While a visit is in progress, its sitter may file an incident against it. Filing supplies the `visit_id`, a `category` of `BREAK_IN`, `WATER_LEAK`, `FIRE`, `MEDICAL`, or `OTHER`, and a `severity` of `MINOR`, `MAJOR`, or `EMERGENCY`. Filing requires the visit to be `IN_PROGRESS`; filing against a visit in any other state — including one already `FLAGGED` — is rejected with `ERR_VISIT_NOT_IN_PROGRESS`, so a visit carries at most one incident at a time. Filing sets the incident's `booking_id` from the visit, records `reported_by_sitter_id` from the acting sitter's `X-User-ID`, opens the incident in `OPEN`, and flags the visit, moving it from `IN_PROGRESS` to `FLAGGED`. A flagged visit cannot be closed while any of its incidents remains open: closing a flagged visit requires that every incident on the visit is `RESOLVED`, and an unresolved incident is rejected with `ERR_UNRESOLVED_INCIDENT` (this check joins the evidence and checklist conditions of Section 3.6 when the flagged visit checks out, and is evaluated first — ahead of the evidence and checklist checks). A flagged visit that satisfies all three checks closes to `DONE` exactly like an in-progress one — stamping `check_out_at`, computing the same provisional charge, and updating the invoice identically.

A coordinator may escalate an open incident, moving it from `OPEN` to `ESCALATED`. Escalation is permitted only when the sitter holds an `ACTIVE` `LIABILITY` coverage policy; without one it is rejected with `ERR_NO_LIABILITY_COVERAGE`, and escalating an incident not in `OPEN` is rejected with `ERR_INCIDENT_NOT_OPEN`. Escalation computes the estimated exposure and reserves it: the reserve, stored in the incident's `estimated_exposure_cents`, is the lesser of the liability policy's `coverage_amount_cents` and the severity reserve — 50000 cents for `MINOR`, 200000 cents for `MAJOR`, and 500000 cents for `EMERGENCY`. That amount is added to the liability policy's `reserved_exposure_cents`. Escalation also increments the sitter's `escalated_incident_count` by one and recomputes the sitter's `reliability_score`, which may in turn drop the sitter below the minimum reliability threshold and suspend them (Section 2.10).

Resolving an incident supplies the `assessed_damage_cents` — the assessed property damage, which must be at least zero, else `ERR_INVALID_REQUEST` — and moves the incident to `RESOLVED`. An incident may be resolved from either `OPEN` or `ESCALATED`; resolving from any other state is rejected with `ERR_INCIDENT_NOT_RESOLVABLE`. In both cases the settled payout, stored in `settled_payout_cents`, is the lesser of the assessed damage and the policy's `coverage_amount_cents`; when no liability policy applies (the incident was never escalated and the sitter holds no `ACTIVE` liability policy at resolution time), the settled payout is the assessed damage uncapped. The two resolution paths differ in their ledger effects:

- Resolving directly from `OPEN` (an incident that was never escalated) computes `settled_payout_cents` but makes no change to the policy's reserved or paid-out ledgers, because no reserve was ever placed.
- Resolving from `ESCALATED` computes `settled_payout_cents`, releases the previously placed reserve by subtracting the incident's `estimated_exposure_cents` from the policy's `reserved_exposure_cents`, and adds the settled payout to the policy's `paid_out_cents`. If, after this, the policy's `paid_out_cents` is at or above its `coverage_amount_cents`, the policy becomes `EXHAUSTED`, and — caused by that exhaustion — the sitter's `status` moves to `SUSPENDED`.

### 3.8. Missed Visits and Reliability Consequences

When a sitter fails to attend a visit, a coordinator marks it missed after its window has closed. Marking a visit missed moves it from `SCHEDULED` to `MISSED`. It requires the visit to still be in `SCHEDULED` (otherwise `ERR_VISIT_NOT_SCHEDULED`) and the current clock to be at or after the visit's `scheduled_end`; marking a visit missed while its window is still open (clock before `scheduled_end`) is rejected with `ERR_VISIT_WINDOW_OPEN`. Marking a visit missed increments the sitter's `missed_visit_count` by one and recomputes the `reliability_score`; if the recomputed score is below the minimum reliability threshold of 60, the sitter's `status` cascades to `SUSPENDED`.

### 3.9. Completing the Booking, Billing, and Cancellation

A booking may be completed only once all of its work has settled. A coordinator completes an active booking, moving it from `ACTIVE` to `COMPLETED`; a booking not in `ACTIVE` is rejected with `ERR_BOOKING_NOT_ACTIVE`, and completion requires that every visit of the booking is terminal — `DONE`, `MISSED`, or `CANCELLED` — with any non-terminal visit rejecting the request with `ERR_VISITS_NOT_RESOLVED`. On completion, each `DONE` visit's charge is recomputed into `final_charge_cents` using the **final** variant of the per-visit charge: identical to the provisional computation except that the duration factor is no longer fixed at 1.0. Instead the duration factor is the actual elapsed minutes between `check_in_at` and `check_out_at` divided by the standard thirty minutes, clamped to a minimum of 0.5 and a maximum of 2.0. Because it reflects real GPS-logged elapsed time, the final charge can diverge from the provisional one in either direction. The invoice is then recomputed from the final charges.

The invoice roll-up proceeds in a pinned order to resolve the interdependence between discount, fee, and tax. The `subtotal_cents` is the sum of the contributing visit charges — provisional charges while the booking is `ACTIVE`, final charges at completion — where only `DONE` visits contribute and `CANCELLED` or `MISSED` visits contribute nothing; the `billed_visit_count` is the number of such contributing visits. A loyalty discount rate is then keyed on the subtotal: the rate is 0.10 when the subtotal is at least 50000 cents, otherwise 0.05 when the subtotal is at least 20000 cents, and otherwise 0.00. The `discount_cents` is the subtotal multiplied by that rate, rounded half up. The discounted base is the subtotal minus the discount. The `service_fee_cents` is the discounted base multiplied by the service fee rate of 0.08, rounded half up. The `tax_cents` is the sum of the discounted base and the service fee, multiplied by the tax rate of 0.07, rounded half up. The `total_cents` is the discounted base plus the service fee plus the tax. Each of these steps is rounded half up in the order shown.

Payment closes the financial lifecycle. The owning `Client` or a `Coordinator` pays an issued invoice, moving it from `ISSUED` to `PAID`. Payment requires the invoice to be in `ISSUED` (otherwise `ERR_INVOICE_NOT_ISSUED`) and the owning booking to be `COMPLETED` (otherwise `ERR_BOOKING_NOT_COMPLETED`).

Cancellation can intervene at any non-terminal point. Either the owning `Client` or a `Coordinator` cancels a booking that is in `DRAFT`, `PENDING_ASSIGNMENT`, `SCHEDULED`, or `ACTIVE`, moving it to `CANCELLED`; cancelling an already-terminal booking is rejected with `ERR_BOOKING_NOT_CANCELLABLE`. Cancelling a booking that had progressed to `SCHEDULED` or `ACTIVE` triggers a cascade in three hops: first, every visit not already `CANCELLED` or `MISSED` — that is, any visit in `SCHEDULED`, `IN_PROGRESS`, `FLAGGED`, or `DONE` — moves to `CANCELLED`; second, each such visit that had already billed a charge (one that was `DONE`) has that charge reversed, so the invoice's `subtotal_cents` is decremented and the invoice financials are recomputed; third, the invoice moves to `VOID`. In addition, any `CHECKED_OUT` key assignment for this booking is returned, moving to `RETURNED` and releasing its key copy back to the office. Cancelling a booking still in `DRAFT` or `PENDING_ASSIGNMENT` — before any visits or invoice exist — simply moves it to `CANCELLED` with no cascade.

## 4. Endpoint Definitions

Creation endpoints that mint a new resource return HTTP 201; all other successful reads and state transitions return HTTP 200. Request and response bodies are not restated here — reconstruct them from the workflow narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Coordinator |
| POST | `/home-watch/clients` | Onboard a client | Coordinator |
| GET | `/home-watch/clients` | List clients | Coordinator, Client, Sitter |
| GET | `/home-watch/clients/{id}` | Get a client | Coordinator, Client, Sitter |
| POST | `/home-watch/properties` | Register a property under a client | Coordinator, Client |
| GET | `/home-watch/properties` | List properties (filter by `client_id`) | Coordinator, Client, Sitter |
| GET | `/home-watch/properties/{id}` | Get a property | Coordinator, Client, Sitter |
| POST | `/home-watch/sitters` | Onboard a sitter | Coordinator |
| GET | `/home-watch/sitters` | List sitters | Coordinator, Client, Sitter |
| GET | `/home-watch/sitters/{id}` | Get a sitter | Coordinator, Client, Sitter |
| POST | `/home-watch/background-checks` | Submit a background check for a sitter | Coordinator |
| POST | `/home-watch/background-checks/{id}/decide` | Clear or reject a submitted background check | Coordinator |
| GET | `/home-watch/background-checks` | List background checks (filter by `sitter_id`) | Coordinator, Sitter |
| GET | `/home-watch/background-checks/{id}` | Get a background check | Coordinator, Sitter |
| POST | `/home-watch/coverage-policies` | Issue an insurance/bond policy (OCC-guarded on sitter version) | Coordinator |
| GET | `/home-watch/coverage-policies` | List coverage policies (filter by `sitter_id`) | Coordinator, Sitter |
| GET | `/home-watch/coverage-policies/{id}` | Get a coverage policy | Coordinator, Sitter |
| POST | `/home-watch/bookings` | Create a booking (recurring or vacation) in DRAFT | Coordinator, Client |
| GET | `/home-watch/bookings` | List bookings (filter by `property_id`, `client_id`, `sitter_id`, `status`) | Coordinator, Client, Sitter |
| GET | `/home-watch/bookings/{id}` | Get a booking | Coordinator, Client, Sitter |
| POST | `/home-watch/bookings/{id}/submit` | Submit a DRAFT booking to the assignment pool | Coordinator, Client |
| POST | `/home-watch/bookings/{id}/assign` | Assign a sitter and generate visits + invoice | Coordinator |
| POST | `/home-watch/bookings/{id}/unassign` | Return a SCHEDULED booking to the assignment pool | Coordinator |
| POST | `/home-watch/bookings/{id}/activate` | Activate a scheduled booking | Coordinator |
| POST | `/home-watch/bookings/{id}/complete` | Complete an active booking and finalize charges | Coordinator |
| POST | `/home-watch/bookings/{id}/cancel` | Cancel a booking with cascade | Coordinator, Client |
| GET | `/home-watch/visits` | List visits (filter by `booking_id`, `property_id`, `sitter_id`, `status`) | Coordinator, Client, Sitter |
| GET | `/home-watch/visits/{id}` | Get a visit | Coordinator, Client, Sitter |
| POST | `/home-watch/visits/{id}/check-in` | Sitter checks in (geofence + key verified) | Sitter |
| POST | `/home-watch/visits/{id}/check-out` | Sitter checks out; provisional charge billed | Sitter |
| POST | `/home-watch/visits/{id}/mark-missed` | Mark an unattended visit missed after its window closes | Coordinator |
| POST | `/home-watch/visit-logs` | Append a photo/GPS/note evidence entry | Sitter |
| GET | `/home-watch/visit-logs` | List visit log entries (filter by `visit_id`) | Coordinator, Client, Sitter |
| GET | `/home-watch/visit-logs/{id}` | Get a visit log entry | Coordinator, Client, Sitter |
| POST | `/home-watch/key-assignments` | Issue a key copy assignment for a booking's sitter | Coordinator |
| POST | `/home-watch/key-assignments/{id}/check-out` | Check out a key copy to the sitter | Coordinator, Sitter |
| POST | `/home-watch/key-assignments/{id}/return` | Return a key copy to the office | Coordinator, Sitter |
| POST | `/home-watch/key-assignments/{id}/report-lost` | Report a checked-out key copy lost | Coordinator |
| GET | `/home-watch/key-assignments` | List key assignments (filter by `property_id`, `sitter_id`, `booking_id`) | Coordinator, Sitter |
| GET | `/home-watch/key-assignments/{id}` | Get a key assignment | Coordinator, Sitter |
| POST | `/home-watch/incidents` | File an incident during an in-progress visit | Sitter |
| POST | `/home-watch/incidents/{id}/escalate` | Escalate an incident (reserve liability exposure) | Coordinator |
| POST | `/home-watch/incidents/{id}/resolve` | Resolve an incident with assessed damage | Coordinator |
| GET | `/home-watch/incidents` | List incidents (filter by `visit_id`, `booking_id`, `reported_by_sitter_id`) | Coordinator, Client, Sitter |
| GET | `/home-watch/incidents/{id}` | Get an incident | Coordinator, Client, Sitter |
| GET | `/home-watch/invoices` | List invoices (filter by `booking_id`, `client_id`) | Coordinator, Client |
| GET | `/home-watch/invoices/{id}` | Get an invoice | Coordinator, Client |
| POST | `/home-watch/invoices/{id}/pay` | Pay an issued invoice for a completed booking | Coordinator, Client |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_FORBIDDEN_NOT_OWNER | 403 |
| ERR_CLIENT_NOT_FOUND | 404 |
| ERR_PROPERTY_NOT_FOUND | 404 |
| ERR_SITTER_NOT_FOUND | 404 |
| ERR_BGCHECK_NOT_FOUND | 404 |
| ERR_COVERAGE_NOT_FOUND | 404 |
| ERR_BOOKING_NOT_FOUND | 404 |
| ERR_VISIT_NOT_FOUND | 404 |
| ERR_VISITLOG_NOT_FOUND | 404 |
| ERR_KEY_NOT_FOUND | 404 |
| ERR_INCIDENT_NOT_FOUND | 404 |
| ERR_INVOICE_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 422 |
| ERR_CHECKLIST_CONFIG_EMPTY | 422 |
| ERR_STALE_SITTER_VERSION | 412 |
| ERR_BGCHECK_NOT_PENDING | 409 |
| ERR_BOOKING_NOT_DRAFT | 409 |
| ERR_BOOKING_NOT_PENDING_ASSIGNMENT | 409 |
| ERR_BOOKING_NOT_SCHEDULED | 409 |
| ERR_BOOKING_NOT_ACTIVE | 409 |
| ERR_BOOKING_NOT_CANCELLABLE | 409 |
| ERR_BOOKING_NOT_COMPLETED | 409 |
| ERR_VISITS_NOT_RESOLVED | 409 |
| ERR_SITTER_NOT_CLEARED | 409 |
| ERR_SITTER_COVERAGE_INACTIVE | 403 |
| ERR_SITTER_RELIABILITY_TOO_LOW | 403 |
| ERR_SITTER_SCHEDULE_CONFLICT | 409 |
| ERR_PROPERTY_BOOKING_OVERLAP | 409 |
| ERR_VISIT_NOT_SCHEDULED | 409 |
| ERR_VISIT_NOT_IN_PROGRESS | 409 |
| ERR_VISIT_WINDOW_OPEN | 409 |
| ERR_OUTSIDE_GEOFENCE | 422 |
| ERR_VISIT_EVIDENCE_MISSING | 422 |
| ERR_CHECKLIST_INCOMPLETE | 422 |
| ERR_UNRESOLVED_INCIDENT | 409 |
| ERR_KEY_NOT_AT_OFFICE | 409 |
| ERR_KEY_NOT_CHECKED_OUT | 409 |
| ERR_NO_KEY_COPIES_AVAILABLE | 409 |
| ERR_KEY_NOT_READY | 409 |
| ERR_INCIDENT_NOT_OPEN | 409 |
| ERR_INCIDENT_NOT_RESOLVABLE | 409 |
| ERR_NO_LIABILITY_COVERAGE | 409 |
| ERR_INVOICE_NOT_ISSUED | 409 |
