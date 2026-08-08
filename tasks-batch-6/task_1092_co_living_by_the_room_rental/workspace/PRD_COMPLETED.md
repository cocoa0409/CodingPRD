# Co-Living By-The-Room Rental API — Product Requirements Document

## 1. Introduction

Co-living operators rent bedrooms, not apartments. A single house is carved into individually leased rooms, each with its own all-in rate that bundles rent and a share of the household utilities, and each occupied by a resident who signed up on a different day, on a different cadence, under a different deposit. The operational consequence is that almost nothing in a co-living portfolio lines up: one resident pays weekly while the person across the hall pays monthly, the utility bill has to be split across whoever actually lived there during the period, a broken shared bathroom degrades the experience of five tenancies at once, and a single house-rule problem can escalate into an involuntary move-out that must be tracked against the same room the next applicant is already queuing for.

This document specifies the backend service that runs that business. It covers the full arc from property setup through applicant screening, tenancy conversion, all-in rent billing, delinquency handling, house-rule enforcement, shared-space maintenance, and finally the remittance of collected cash to the property owner. The service is deliberately conservative about state: room availability, house-level compliance posture, member standing, and outstanding balances are all derived quantities that must be recomputed — never merely remembered — whenever they gate a decision. A room that a compliance freeze has taken off the market must stop accepting move-ins the instant the freeze condition holds, not the next time somebody remembers to run a batch job.

The service is mounted under the `/co-living` prefix. It is consumed by five distinct operational audiences — property owners, residents, house-level community managers, compliance staff, and finance staff — plus a platform operations role, and much of the specification below exists because those audiences must be kept apart: the officer who reports a house-rule violation may not be the one who upholds it, and the finance operator who projects a payout may not be the one who releases the money.

## 2. Global Specifications & System-Wide Principles

### 2.1. Actors, Identity Headers and Access Control

Every request to the service must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity in which the caller is acting. If either header is absent or empty, or if `X-User-Role` is not one of the six role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs. Once the caller is authenticated, the service checks that the acting role is one of the roles the target endpoint permits; a role that is not on that list receives `ERR_UNAUTHORIZED` (HTTP 403).

The six roles are `PlatformAdmin`, `Host`, `Member`, `CommunityManager`, `ComplianceOfficer`, and `FinanceAdmin`.

- A `PlatformAdmin` runs platform operations: onboarding property owners and residents, and driving the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it on a resource where a transition writes an actor field, but it never compares it to any entity's `id`.
- A `Host` is a property owner who defines houses and rooms and ultimately receives the payout. When `X-User-Role` is `Host`, `X-User-ID` is the `id` of the acting `Host` entity; ownership checks on any resource that references a `Host` compare the resource's owning `host_id` — directly on a house, or on the house behind a room or a payout — to `X-User-ID`.
- A `Member` is a prospective or current by-the-room resident. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` entity; ownership checks compare `Application.member_id`, `Membership.member_id`, or the `member_id` of the tenancy standing behind an invoice or an incident, to `X-User-ID`.
- A `CommunityManager` is the house-level operator who converts applications into tenancies, runs move-in and move-out, files incidents, and manages maintenance work. When `X-User-Role` is `CommunityManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as the reporter of an incident) but does not compare it to any entity's `id`.
- A `ComplianceOfficer` handles applicant screening and house-rule adjudication. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it is recorded as `submitted_by_user_id` on a screening report and as `reported_by_user_id` or `adjudicated_by_user_id` on an incident, and it is compared only against those recorded operator strings, never against an entity `id`.
- A `FinanceAdmin` handles billing and remittance. When `X-User-Role` is `FinanceAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it is recorded as `recorded_by_user_id` on a payment and as `projected_by_user_id` or `released_by_user_id` on a payout, and is compared only against those recorded operator strings.

Ownership enforcement is scoped to writes. Eleven write operations are ownership-checked for the two entity-backed roles: creating a house, creating a room, revising a room, submitting an application, resubmitting an application, filing a move-out notice, cancelling a tenancy, recording a payment against an invoice, filing a house-rule incident, disputing an incident, and opening a maintenance ticket. In each of these, a `Member` whose `X-User-ID` does not match the owning `member_id`, or a `Host` whose `X-User-ID` does not match the owning `host_id`, is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Read endpoints are deliberately platform-wide: every retrieval and listing endpoint is readable by all six roles and is **not** ownership-scoped, so a `Member` may read any house, room, or invoice in the portfolio.

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

Every list endpoint accepts two optional query-string parameters. `limit` controls page size: it defaults to 10 when omitted, its minimum accepted value is 1, and its maximum accepted value is 100. `offset` controls how many rows are skipped before the page begins: it defaults to 0 and its minimum accepted value is 0. A `limit` outside the range 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

List results are ordered by `created_at` ascending unless the endpoint's own description states otherwise. The `meta` object of a list response carries four pagination fields: `limit` (the effective page size applied), `offset` (the effective skip applied), `total_count` (the number of rows matching the filters before pagination), and `has_more` (true when rows remain beyond the current page).

### 2.4. Resource Identity, Timestamps and the Logical Clock

Every stored resource carries a server-minted `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC string with exactly three fractional-second digits. Most resources additionally carry an `updated_at` timestamp in the same format and an integer `version` that starts at 1 on creation and increases by exactly 1 on each mutation of that resource; `updated_at` is refreshed on every such mutation. Two record types are append-only ledger entries and therefore carry **only** `id` and `created_at` — a screening report and a payment have no `updated_at` and no `version` field at all.

Time in this system is not wall-clock time. A logical clock governs every timestamp the server mints and every deadline comparison it performs, and a platform operations capability sets that clock by supplying a `to_iso8601` instant; the response echoes the resulting `current_utc` verbatim — exactly the string supplied as `to_iso8601`, not re-normalized to the three-fractional-digit form. Before the clock is ever set it reads exactly `2026-05-01T00:00:00Z`, and it must never fall back to the host machine's real time. Every `created_at`, `updated_at`, `applied_at`, `resolved_at`, and `released_at` stamp, along with every SLA deadline, grace-window, notice-length, and strike-window comparison described in this document, reads that clock. Where a rule speaks of "the clock date", it means the calendar date of the current logical clock instant in UTC; where it speaks of "the clock instant", it means the full timestamp. Setting the clock mutates no entity.

Dates that describe occupancy and billing — `requested_move_in_date`, `move_in_date`, `scheduled_move_out_date`, `actual_move_out_date`, `effective_end_date`, `available_from_date`, `period_start`, `period_end`, `due_date`, `cycle_start`, and `cycle_end` — are calendar dates in `YYYY-MM-DD` form. Instants that describe events — `occurred_at`, `sla_deadline_at`, `visit_start`, `visit_end`, `applied_at`, `resolved_at`, `released_at` — are full ISO 8601 UTC datetimes. A value that does not parse in the expected shape is rejected with `ERR_INVALID_REQUEST`.

### 2.5. Nested Paths and the Order in Which Rules Fire

Several endpoints address a sub-resource beneath a parent — the screening rounds of an application, the payments of an invoice. Path identifiers are resolved strictly left to right, and the first identifier that resolves to nothing terminates the request. The not-found code is specific to the entity that failed to resolve: `ERR_HOUSE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, or `ERR_PAYOUT_NOT_FOUND`, all at HTTP 404.

Because many operations are guarded by several rules at once, the order in which those rules are evaluated is fixed and must be honoured exactly — a request that violates two rules always reports the earlier one. The full precedence chain, from first-evaluated to last, is:

1. Header authentication (`ERR_UNAUTHENTICATED`).
2. Role permission for the endpoint (`ERR_UNAUTHORIZED`).
3. Resolution of every identifier embedded in the request path, left to right (the entity-specific 404 codes above).
4. Ownership for the entity-backed roles on the eleven write operations listed in §2.1 (`ERR_NOT_RESOURCE_OWNER`). On room creation specifically, a `Host`'s ownership is judged against the house named by the body's `house_id`, and this check fires only when that `house_id` resolves to an existing house owned by a different host; when the `house_id` does not resolve to any house at all, the ownership check is skipped and the request falls through to foreign-key resolution at step 6, which reports `ERR_HOUSE_NOT_FOUND`.
5. Shape of the request body and query string — required fields present, enum members recognised, integers non-negative where declared, dates in `YYYY-MM-DD`, datetimes in ISO 8601 UTC, `limit` within 1 to 100 and `offset` at least 0 (`ERR_INVALID_REQUEST`).
6. Resolution of every foreign key supplied in the request body, on house creation, room creation, application submission, membership creation, invoice generation, incident filing, ticket opening, and payout opening (`ERR_HOST_NOT_FOUND`, `ERR_HOUSE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`).
7. Cross-entity linkage coherence on ticket opening (`ERR_ENTITY_MISMATCH`).
8. Uniqueness on member onboarding and room creation (`ERR_DUPLICATE_EMAIL`, `ERR_DUPLICATE_ROOM_NUMBER`).
9. The one-tenancy-per-member rule on membership creation (`ERR_MEMBER_ALREADY_HOUSED`).
10. The target resource's own state admitting the requested transition (`ERR_APPLICATION_NOT_PENDING`, `ERR_INVALID_MEMBERSHIP_STATE`, `ERR_INVALID_INCIDENT_STATE`, `ERR_INVALID_TICKET_STATE`, `ERR_INVALID_PAYOUT_STATE`, `ERR_INVOICE_NOT_PAYABLE`).
11. The cross-entity room-availability gate on rendering an application decision and on creating a membership (`ERR_ROOM_NOT_AVAILABLE`).
12. The cross-entity tenancy gate on invoice generation (`ERR_INVALID_MEMBERSHIP_STATE`).
13. Optimistic concurrency on room revision and visit scheduling (`ERR_STALE_ROOM_VERSION`, `ERR_STALE_HOUSE_VERSION`).
14. The background-check safety gate on approval (`ERR_BACKGROUND_FAILED`).
15. The house posture gate on move-in (`ERR_HOUSE_POSTURE_BLOCKED`).
16. The house freeze gate on payout release (`ERR_HOUSE_FROZEN`).
17. Segregation of duties on incident adjudication and payout release (`ERR_SEGREGATION_OF_DUTIES`).
18. Date-range ordering on invoice generation, payout opening, visit scheduling, and move-out (`ERR_INVALID_DATE_RANGE`).
19. The move-in date not being in the past, on membership creation (`ERR_MOVE_IN_DATE_IN_PAST`).
20. Minimum notice length on a member-initiated notice (`ERR_NOTICE_TOO_SHORT`).
21. The past-due precondition on a non-payment notice (`ERR_NOT_PAST_DUE`).
22. Billing-period length on invoice generation (`ERR_INVALID_PERIOD_LENGTH`).
23. Billing-period non-overlap on invoice generation (`ERR_INVOICE_PERIOD_OVERLAP`).
24. Payout-cycle non-overlap on payout opening (`ERR_PAYOUT_CYCLE_OVERLAP`).
25. The grace window having expired before a late fee is assessed (`ERR_LATE_FEE_NOT_DUE`).
26. Room turnover spacing on membership creation (`ERR_ROOM_TURNOVER_CONFLICT`).
27. House visit-calendar capacity on visit scheduling (`ERR_VISIT_CAPACITY_CONFLICT`).
28. The dispute-round ceiling on disputing an incident (`ERR_DISPUTE_LIMIT_REACHED`).
29. The screening-round ceiling on resubmission and on filing a further screening round (`ERR_APPLICATION_ROUND_LIMIT`).
30. Fee-adjustment coherence with the invoice's current fee (`ERR_LATE_FEE_ALREADY_ASSESSED`, `ERR_NO_LATE_FEE_TO_WAIVE`).
31. The income sufficiency rule on approval once the cosigner round has been consumed (`ERR_INCOME_INSUFFICIENT`).
32. The overpayment ceiling on recording a payment (`ERR_OVERPAYMENT`).

Note the consequence of positions 15 through 17: a house posture problem surfaces before a segregation-of-duties problem, and both surface before the temporal and fiscal checks that follow. Note likewise that stale-version rejection at position 13 sits *after* the resource's own state check at position 10, so a request that is both stale and aimed at a wrong-state resource reports the state error.

### 2.6. Cent Arithmetic, Rounding and Rounding Order

All money in this system is stored and transported as whole integer cents; there are no decimal currency fields anywhere in the API. Wherever a monetary computation produces a fractional cent, the result is rounded half up — a value exactly at the halfway point rounds away from zero — unless the rule explicitly calls for rounding up to the next whole cent, which two of the utility divisions do.

Rounding order is part of the specification, not an implementation detail. Where a formula rounds twice, the two roundings happen independently at the points the formula names, and must never be fused into a single rounding of the composite expression. Where a formula rounds per line item and then sums, the sum of rounded lines is the answer; summing first and rounding once produces a different cents value and is incorrect. The formulas in §3 state their rounding points explicitly, and those statements are binding.

Counts of rooms, strike points, screening rounds, dispute rounds, and breach hours are plain integers with no rounding at all.

### 2.7. Optimistic Concurrency on the Rate Card and the House Calendar

Two write operations carry optimistic-concurrency protection, each keyed on the `version` of a parent resource rather than on the resource being written.

Revising a room — the `PUT /co-living/rooms/{id}` operation — requires a non-optional `expected_room_version` field in the request body, carrying the `version` value the client last observed on that room. If it does not equal the room's current `version`, the revision is rejected with `ERR_STALE_ROOM_VERSION` (HTTP 412). This matters because a rate revision legitimately supersedes the previous rate card: without the check, a client working from a stale read would silently overwrite an edit it never saw, and no state precondition would catch it. A successful revision increments the room's `version` by 1.

Booking a technician visit — the `POST /co-living/tickets/{id}/schedule` operation — requires a non-optional `expected_house_version` field carrying the `version` the client last observed on the house that owns the ticket. If it does not equal that house's current `version`, the booking is rejected with `ERR_STALE_HOUSE_VERSION` (HTTP 412). Booking a second, different ticket into the same house is a perfectly legal operation under the house's concurrent-visit allowance, so no state precondition can distinguish a fresh booking from one made against an outdated view of the calendar; the version check does. A successful booking increments the house's `version` by 1, which is precisely what makes any other client's cached house version stale.

No other endpoint accepts a version field. In particular, move-in, notice, move-out, cancellation, payment, fee adjustment, adjudication, dispute, projection, and release take no expected-version input at all.

### 2.8. Derived House Bookkeeping and the Posture Gate

A house maintains six computed integers describing its room inventory: `total_room_count` is the number of rooms whose `house_id` names it, and `vacant_room_count`, `reserved_room_count`, `occupied_room_count`, `notice_pending_room_count`, and `out_of_service_room_count` are the counts of those rooms whose `occupancy_state` is `VACANT`, `RESERVED`, `OCCUPIED`, `NOTICE_PENDING`, and `OUT_OF_SERVICE` respectively. All six start at 0 when a house is created. They are recomputed on every room creation and on every change to any room's `occupancy_state`, including changes reached indirectly through a cascade. Because rooms are never soft-deleted, the five state buckets always partition the total: after every request — cascades included — `total_room_count` must equal the sum of the other five counts.

Layered on top of those counts is `compliance_posture`, a derived gate over the house whose value is one of `OPEN`, `RESTRICTED`, or `FROZEN`, defaulting to `OPEN`. It is never stored-and-forgotten: it is re-evaluated freshly at the start of every request that reads a house and at the start of every request whose validation gates on it, which is to say move-in and payout release. Its evaluation proceeds in a fixed dominance order — the frozen condition is tested first, then the restricted condition, and only if neither holds is the posture `OPEN`:

- The **frozen condition** holds when the house has at least one maintenance ticket whose `severity` is `CRITICAL`, whose `status` is either `OPEN` or `SCHEDULED`, and whose `sla_deadline_at` is strictly earlier than the current clock instant.
- The **restricted condition** holds when either of two things is true. First, the house's turnover ratio — `notice_pending_room_count` divided by `total_room_count`, treated as zero when `total_room_count` is zero — is strictly greater than one half. This comparison is performed exactly, by testing whether twice `notice_pending_room_count` is strictly greater than `total_room_count`, with no floating-point rounding; a house with exactly half its rooms in `NOTICE_PENDING` therefore stays out of the restricted band. Second, the house has at least three upheld house-rule incidents — incidents whose `house_id` names it, whose `status` is `UPHELD`, and whose `occurred_at` is at or after the instant thirty days before the current clock instant.

`OPEN` allows move-ins. `RESTRICTED` blocks move-ins but permits payout release. `FROZEN` blocks both. The transitions between postures are entirely system-driven: `OPEN → RESTRICTED` and `RESTRICTED → FROZEN` and `OPEN → FROZEN` happen the moment the corresponding condition begins to hold, and `RESTRICTED → OPEN` and `FROZEN → OPEN` happen the moment neither condition holds any more — typically when the overdue critical ticket is resolved, which both clears the frozen condition and, provided the restricted condition is also absent, re-enables move-ins and payout releases in the same evaluation.

### 2.9. Segregation of Duties

Two decisions in this system are deliberately split across two human operators, and the split is enforced by comparing `X-User-ID` against an operator string recorded earlier on the resource.

House-rule adjudication is segregated from house-rule reporting: the `X-User-ID` adjudicating an incident must differ from the `reported_by_user_id` captured when the incident was filed. Payout release is segregated from payout projection: the `X-User-ID` releasing a payout must differ from the `projected_by_user_id` captured when the projection ran. Either violation yields `ERR_SEGREGATION_OF_DUTIES` at HTTP 403. Because the recorded strings are opaque operator identifiers rather than entity references, the comparison is a plain string inequality; the roles themselves (`ComplianceOfficer` for adjudication, `FinanceAdmin` for release) are checked separately and earlier.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Portfolio: Hosts, Houses and Rooms

The portfolio begins with a property owner. Platform operations onboards a `Host` by supplying its `legal_name` (a non-empty string of at most 200 characters), a `payout_account_ref` (a non-empty opaque bank or payment-account reference to which that host's money is eventually remitted), and a `contact_email` that must contain an `@` character. A host is the ultimate payout recipient for every house it owns.

A house is created under a host by naming its `host_id` together with a human-readable `label` (non-empty, e.g. "Peachtree A"), an `address_line1`, a `city`, a two-letter uppercase US `state_code` (exactly two uppercase letters), and a `monthly_utility_budget_cents` — the house-level all-in utility budget for a month, which must be zero or greater and which is later split across the rooms that are occupied during a billing period. At creation the six room-state counts are all zero and `compliance_posture` is `OPEN`. Creating a house is permitted to the owning `Host` and to `PlatformAdmin`; when a `Host` creates it, the body's `host_id` must equal the caller's `X-User-ID`.

Rooms are the rentable units. Adding a room names the `house_id` it belongs to, a `room_number` that is non-empty and unique within that house, a `weekly_rate_cents` and a `monthly_rate_cents` (both strictly greater than zero — these are the all-in weekly and monthly base rents, exclusive of the shared utility share), and an optional `private_bath` boolean that defaults to false. A room is born `VACANT`; its creation recomputes the owning house's `total_room_count` and `vacant_room_count`. A second room reusing an existing `room_number` in the same house is rejected with `ERR_DUPLICATE_ROOM_NUMBER`. Rooms also carry a system-managed `occupancy_state` and a computed `available_from_date` that stays null until the room enters `NOTICE_PENDING`.

The room's rate card can be revised after the fact — its `weekly_rate_cents`, `monthly_rate_cents`, or `private_bath`, each of which is optional on the revision body so that any field omitted (or sent as null) is left unchanged, while a supplied `weekly_rate_cents` or `monthly_rate_cents` must still be strictly greater than zero — but only under the optimistic-concurrency discipline of §2.7: the revision must carry `expected_room_version`, and a mismatch is rejected with `ERR_STALE_ROOM_VERSION`. Crucially, a rate revision is forward-looking only. It bumps the room's `version` but does **not** retroactively change the `base_period_rate_cents` of any tenancy already created against that room; existing residents keep the rate that was pinned when their tenancy was created. Both room writes are available to the owning `Host` and to `PlatformAdmin`; a `Host` must own the room's house.

### 3.2. Applicants, Screening and the Income Bar

A `Member` is onboarded by platform operations with a `full_name`, a globally unique `email` containing an `@`, and a self-declared `declared_monthly_income_cents` (zero or greater). That declared figure is captured for the record but is **never** used to qualify anyone — only a vendor-verified figure ever qualifies an applicant. A second member reusing an existing email is rejected with `ERR_DUPLICATE_EMAIL`. Each member also carries a computed `strike_points` total and a `standing_band`, both described in §3.7; a freshly onboarded member has zero strike points and stands in band `GOOD`.

An `Application` ties a prospective resident to a specific room at a chosen cadence. It names the `member_id`, the `room_id` applied for, a `requested_move_in_date` in `YYYY-MM-DD` form, and a `billing_cycle` of either `WEEKLY` or `MONTHLY`. Submitting an application is open to a `Member` acting for themselves (the body's `member_id` must equal `X-User-ID`) and to a `CommunityManager` submitting on behalf of a walk-in. A new application starts in status `SUBMITTED`, with `screening_round` at 0 and `required_deposit_cents` at 0; its `monthly_equivalent_cents` and `required_income_cents` are likewise 0 until the first screening round computes them. Its `status` moves through the values `SUBMITTED`, `SCREENED`, `APPROVED`, `CONDITIONAL`, `DENIED`, and `CONVERTED`; `DENIED` and `CONVERTED` are terminal.

Screening is the only way out of `SUBMITTED`. A `ComplianceOfficer` files a screening round by supplying the vendor's `background_result` (one of `CLEAR`, `FLAGGED`, or `FAILED`), a `verified_monthly_income_cents` for the applicant alone (zero or greater, excluding any cosigner), and a non-empty `report_reference`. Filing is only accepted while the application is in `SUBMITTED` and while its `screening_round` is below the two-round ceiling; a further round beyond that ceiling is rejected with `ERR_APPLICATION_ROUND_LIMIT`, and filing against any status other than `SUBMITTED` is `ERR_APPLICATION_NOT_PENDING`. Each filing creates a `ScreeningReport` whose `sequence_number` is a 1-based round index equal to the application's prior `screening_round` plus 1 (and which serves as the deterministic tie-break when two reports of one application share a `created_at`), records the filing officer's `X-User-ID` as `submitted_by_user_id`, advances the application to `SCREENED`, and recomputes the application's `screening_round`. A screening report is an append-only ledger row: it carries only `id` and `created_at`, no `updated_at` and no `version`.

Filing a screening round also recomputes two figures used to qualify the applicant. The first is `monthly_equivalent_cents`, the applicant's rent normalized to a monthly number: when the application's `billing_cycle` is `MONTHLY`, it is simply the room's current `monthly_rate_cents`; when the cycle is `WEEKLY`, it is the room's current `weekly_rate_cents` multiplied by fifty-two weeks per year, divided by twelve months per year, and rounded half up to whole cents. The second is `required_income_cents`, the bar the applicant's income must reach: the `monthly_equivalent_cents` multiplied by an income multiple of three, rounded half up to whole cents. These two roundings are independent — the weekly normalization is rounded to whole cents first, and the multiple-of-three bar is computed from that rounded figure and rounded again — and they must never be collapsed into one fused multiplication. Both figures read the room at its current rate card at the moment screening runs.

The listing of an application's screening rounds returns them oldest first, ordered by `created_at` and then by `sequence_number`.

### 3.3. The Decision, the Fork, and the Cosigner Revision Cycle

Once an application is `SCREENED`, a `ComplianceOfficer` renders a decision by supplying a `decision` of either `APPROVE` or `DENY`, plus an optional `decision_note` free-text remark that is recorded on the application. A decision may only be rendered while the application is `SCREENED`; any other status yields `ERR_APPLICATION_NOT_PENDING`. The room named by the application must also be `VACANT` at decision time — a cross-entity gate that yields `ERR_ROOM_NOT_AVAILABLE` when the room is anything else.

A `DENY` decision always lands the application in `DENIED`, sets `required_deposit_cents` to 0, and records the note. An `APPROVE` decision does not always mean the same thing: the fork between `APPROVED` and `CONDITIONAL` is decided by the screening result and the income bar, not by any operator input. The applicant's qualifying income is the latest screening report's `verified_monthly_income_cents` plus, if one has been supplied, the `cosigner_monthly_income_cents` — where "the latest screening report" means the one for this application with the greatest `created_at`, ties broken by the greatest `sequence_number`. On an `APPROVE`:

- If the latest report's `background_result` is `FAILED`, approval is refused outright with `ERR_BACKGROUND_FAILED`; a failed background can never be approved.
- The application lands in `APPROVED` when the latest `background_result` is `CLEAR` **and** the qualifying income is at least the `required_income_cents` bar (equality qualifies — the comparison is inclusive).
- The application lands in `CONDITIONAL` when the latest `background_result` is `FLAGGED`, **or** when the qualifying income falls below the `required_income_cents` bar while no cosigner income has yet been recorded.

There is one important interaction with the income check. If the qualifying income is below the bar and a cosigner figure has *already* been supplied on a prior round — that is, `cosigner_monthly_income_cents` is no longer null — the applicant has exhausted the cosigner remedy, and an `APPROVE` is rejected with `ERR_INCOME_INSUFFICIENT` (HTTP 422) rather than being routed to `CONDITIONAL` again. In other words, insufficient income with no cosigner yet on file produces a conditional offer inviting a cosigner; insufficient income after the cosigner round has been consumed is a hard failure.

The deposit is pinned at decision time from the room's **current** `weekly_rate_cents`, regardless of the application's billing cycle. An `APPROVED` decision sets `required_deposit_cents` to the weekly rate multiplied by a deposit multiple of one, rounded half up. A `CONDITIONAL` decision sets it to the weekly rate multiplied by a conditional deposit multiple of two — a doubled deposit — rounded half up. A `DENIED` decision sets it to zero.

A `CONDITIONAL` application is not a dead end; it opens a bounded revision cycle. The applicant — a `Member` acting for themselves — may resubmit, which sends the application from `CONDITIONAL` back to `SUBMITTED` for another screening round and optionally attaches `cosigner_monthly_income_cents` (which must be zero or greater when present, and which stays null until this resubmit supplies it). Resubmitting resets `required_deposit_cents` back to 0. Resubmission is only legal from `CONDITIONAL` (otherwise `ERR_APPLICATION_NOT_PENDING`) and only while `screening_round` remains below the two-round ceiling (otherwise `ERR_APPLICATION_ROUND_LIMIT`). The full legal loop is therefore `CONDITIONAL → SUBMITTED → SCREENED → CONDITIONAL`, bounded so that no application is ever screened more than twice.

### 3.4. Converting to a Tenancy and Moving In

A `CommunityManager` converts an approved or conditional application into a `Membership` by naming the `application_id` and the scheduled `move_in_date` (the first billable day, `YYYY-MM-DD`). Conversion is legal only from `APPROVED` or `CONDITIONAL` — any other status is `ERR_APPLICATION_NOT_PENDING` — and only while the application's room is still `VACANT`, which is again `ERR_ROOM_NOT_AVAILABLE`. A `CONDITIONAL` application converts perfectly well; it simply carries its doubled deposit into the tenancy.

Two further gates guard conversion. First, the member behind the application must not already hold a live tenancy: if any other `Membership` of that member is in `PENDING_MOVE_IN`, `ACTIVE`, or `NOTICE_GIVEN`, conversion is rejected with `ERR_MEMBER_ALREADY_HOUSED`. Second, the requested `move_in_date` may not be strictly earlier than the current logical clock date (`ERR_MOVE_IN_DATE_IN_PAST`), and it must clear the room's turnover spacing: it must be strictly later than the `effective_end_date` plus the two-day turnover buffer of every prior tenancy on that same room whose `tenancy_status` is `MOVED_OUT` or `NOTICE_GIVEN` (`ERR_ROOM_TURNOVER_CONFLICT`). The occupancy interval on a room is closed on both ends, and the buffer is strict — a new move-in exactly on the buffered edge is a conflict.

Conversion has several effects at once. It advances the application to `CONVERTED` (terminal); it creates the membership in `tenancy_status` `PENDING_MOVE_IN` and `billing_status` `CURRENT`; it copies `member_id` from the application, copies `room_id` from the application and `house_id` from the room, and copies the `billing_cycle`; it drives the room from `VACANT` to `RESERVED`; and it recomputes the house's room-state counts and then its `compliance_posture`. At creation the tenancy pins three values that never move afterward: `period_days` is fixed at 7 when the billing cycle is `WEEKLY` and 30 when `MONTHLY` (calendar month length is never used); `base_period_rate_cents` is pinned to the room's `weekly_rate_cents` when `WEEKLY` and `monthly_rate_cents` when `MONTHLY`, immune to any later rate-card edit; and `deposit_cents` is copied from the application's `required_deposit_cents`. The membership also exposes computed and system fields that fill in over its life: `notice_reason`, `scheduled_move_out_date`, `actual_move_out_date`, `effective_end_date`, `provisional_final_charge_cents`, `final_charge_cents`, and `balance_due_cents`.

Moving the resident in is a `CommunityManager` action, legal only from `PENDING_MOVE_IN` (`ERR_INVALID_MEMBERSHIP_STATE`). It requires that the clock date has reached the `move_in_date` — the move-in may not run early, and an attempt before that date is rejected with `ERR_INVALID_MEMBERSHIP_STATE` (checked at the position-10 state gate, before the posture gate) — and that the house `compliance_posture` is `OPEN` when freshly re-evaluated; a `RESTRICTED` or `FROZEN` house blocks the move-in with `ERR_HOUSE_POSTURE_BLOCKED`. On success the tenancy advances `PENDING_MOVE_IN → ACTIVE`, the room advances `RESERVED → OCCUPIED`, and the house's `reserved_room_count`, `occupied_room_count`, and `compliance_posture` are recomputed.

A tenancy that has not yet moved in can instead be cancelled, by either a `CommunityManager` or the owning `Member`. Cancellation is legal only from `PENDING_MOVE_IN` (`ERR_INVALID_MEMBERSHIP_STATE`) and takes an optional `cancel_reason`. It advances the tenancy `PENDING_MOVE_IN → CANCELLED` (terminal), returns the room `RESERVED → VACANT`, clears the room's `available_from_date` to null, and recomputes the house's room-state counts so that `occupied_room_count` and the partition invariant return to exactly their pre-creation values.

### 3.5. All-In Billing: Invoices, the Utility Split, and the Late-Fee Tier

A `FinanceAdmin` generates one all-in rent invoice per billing period by naming the `membership_id`, the `period_start`, and the `period_end` (both `YYYY-MM-DD`, both inclusive). An invoice may only be generated while the tenancy is `ACTIVE` or `NOTICE_GIVEN`; a `PENDING_MOVE_IN`, `CANCELLED`, or `MOVED_OUT` tenancy cannot be billed, and the attempt is rejected with `ERR_INVALID_MEMBERSHIP_STATE`. The period must be well-formed: `period_end` may not precede `period_start` (`ERR_INVALID_DATE_RANGE`), and the inclusive length — `period_end` minus `period_start` plus one day — must equal the tenancy's `period_days`, seven for weekly and thirty for monthly (`ERR_INVALID_PERIOD_LENGTH`). The new closed interval `[period_start, period_end]` may not intersect any existing invoice of the same tenancy; adjacency is fine, so a new period starting exactly one day after a prior `period_end` is allowed, but any overlap is `ERR_INVOICE_PERIOD_OVERLAP`. The `due_date` is set equal to `period_start` — the all-in rent is due on the first day of the period — and the invoice opens in status `OPEN`.

The charge is assembled in a pinned order. The **base rent** — stored on the invoice as `base_rent_cents` — is the tenancy's pinned `base_period_rate_cents`. The **utility share** is this tenancy's slice of the house's `monthly_utility_budget_cents` for the period, computed from a denominator sampled at `period_start`: `occupied_rooms_at_period_start` is the count of distinct memberships of the same house whose `tenancy_status` is `ACTIVE` or `NOTICE_GIVEN` and whose closed occupancy interval covers `period_start` — that is, whose `move_in_date` is on or before `period_start` and whose `actual_move_out_date` is either null or on or after `period_start`. Memberships in `PENDING_MOVE_IN`, `CANCELLED`, or `MOVED_OUT` are excluded; the tenancy being invoiced counts itself. This audit count is stored on the invoice as `occupied_rooms_at_period_start`. The monthly utility slice is the house budget divided by the greater of that count and one, rounded **up** to the next whole cent. For a monthly tenancy the `utility_share_cents` is that monthly slice directly; for a weekly tenancy it is the monthly slice multiplied by seven and divided by thirty, again rounded **up** to the next whole cent. Both divisions use ceiling, never half-up rounding, and they are applied in that order — monthly slice first, then the weekly conversion.

The **subtotal** — `subtotal_cents` — is base rent plus utility share, and nothing else. It deliberately excludes proration and any fee, because it is the *only* figure the late-fee tier is keyed on. The **total** — `total_amount_cents` — is the subtotal plus `proration_adjustment_cents` (a signed move-out adjustment, zero on a fresh invoice) plus `late_fee_cents` (zero until a late fee is assessed). An invoice also tracks `amount_paid_cents`, the sum of payments applied to it, starting at zero. Generating the invoice recomputes the tenancy's `balance_due_cents`.

The late fee itself is tiered on the subtotal and is only ever set when a fee is assessed (see §3.6): if `subtotal_cents` is below 20000 cents the fee is 1500 cents; if it is at least 20000 but below 40000 cents the fee is 2500 cents; and at 40000 cents or above the fee is 4000 cents. The tier keys strictly on the subtotal, so proration and prior fees never move an invoice into a different late-fee band.

### 3.6. Payments, Delinquency and the Compensating Waive

Cash is applied to an invoice by the owning `Member` or by a `FinanceAdmin`, supplying an `amount_cents` (strictly greater than zero) and a `method` of `CARD`, `ACH`, or `CASH`. A payment is an append-only ledger row carrying only `id` and `created_at` alongside the `invoice_id` it lands on, its `amount_cents` and `method`; it also stamps `applied_at` from the logical clock and records the acting `X-User-ID` as `recorded_by_user_id`. A payment against an already-`PAID` invoice is refused with `ERR_INVOICE_NOT_PAYABLE`, and a payment whose `amount_cents` exceeds the invoice's outstanding remainder — its `total_amount_cents` minus its `amount_paid_cents` — is refused with `ERR_OVERPAYMENT`.

Each accepted payment raises `amount_paid_cents` and advances the invoice's `status`. From `OPEN`, a payment strictly between zero and the outstanding remainder moves the invoice to `PARTIAL`; a payment exactly equal to the remainder moves it straight to `PAID`. From `PARTIAL`, a payment equal to the remainder moves it to `PAID`. From `PAST_DUE`, a payment equal to the remainder moves it to `PAID`. Every accepted payment recomputes the tenancy's `balance_due_cents`, which is the sum, over the tenancy's invoices in status `OPEN`, `PARTIAL`, or `PAST_DUE`, of each invoice's `total_amount_cents` minus its `amount_paid_cents`; fully `PAID` invoices drop out of the sum entirely, and invoices of other tenancies never enter it.

Delinquency is handled through the invoice's fee-adjustment operation, a `FinanceAdmin` action taking an `action` of `ASSESS` or `WAIVE`. Assessing a late fee is legal only once the grace window has expired — the clock date must be strictly later than the invoice's `due_date` plus a three-day grace, otherwise `ERR_LATE_FEE_NOT_DUE` — and only while the invoice is `OPEN` or `PARTIAL` and carries no fee yet; assessing a second time when `late_fee_cents` is already above zero is `ERR_LATE_FEE_ALREADY_ASSESSED`, and assessing against an invoice that is not `OPEN` or `PARTIAL` (for example one left `PAST_DUE` by an earlier fee, even after that fee was waived back to zero) is likewise `ERR_LATE_FEE_ALREADY_ASSESSED`. An assessment sets `late_fee_cents` from the subtotal tier of §3.5, raises `total_amount_cents` by that fee, drives the invoice to `PAST_DUE`, drives the tenancy's `billing_status` from `CURRENT` to `PAST_DUE`, and recomputes `balance_due_cents`.

Waiving reverses an assessed fee exactly. It is legal only while `late_fee_cents` is greater than zero (otherwise `ERR_NO_LATE_FEE_TO_WAIVE`), it lowers `total_amount_cents` by exactly the current `late_fee_cents`, and it resets `late_fee_cents` to zero. The invoice's `status` deliberately stays `PAST_DUE` — only a full payment clears that — and the tenancy's `balance_due_cents` returns to exactly its pre-assessment value. Assessing a fee and then waiving it must be perfectly balance-neutral.

The `billing_status` axis moves independently of the tenancy axis: a tenancy can be `PAST_DUE` while `ACTIVE`, `NOTICE_GIVEN`, or `MOVED_OUT`. A `PAST_DUE` tenancy returns to `CURRENT` when a payment brings its `balance_due_cents` to zero while the tenancy is still live; the same zeroing payment on a tenancy that has already `MOVED_OUT` instead moves `billing_status` to `SETTLED` (terminal), freezing the billing axis. Either payment-driven billing transition also recomputes the member's `strike_points` and `standing_band`. And critically, when a payment returns a tenancy to `CURRENT`, if that tenancy was under a `NONPAYMENT` notice, the notice auto-rescinds — the mechanics of that back-edge are described in §3.7.

### 3.7. House Rules, Strikes, and the Compliance Cascade

Any `CommunityManager`, `ComplianceOfficer`, or `Member` may file a `HouseRuleIncident` against a tenancy. Filing names the `membership_id`, a `rule_code` (one of `QUIET_HOURS`, `GUEST_POLICY`, `CLEANLINESS`, `SMOKING`, `UNAUTHORIZED_OCCUPANT`), a `severity` (`MINOR`, `MAJOR`, or `SEVERE`), a non-empty `description`, and an `occurred_at` instant marking when the violation happened. A `Member` may only file against a tenancy they own. Filing copies `house_id` from the membership, records the filer's `X-User-ID` as `reported_by_user_id`, and starts the incident in `REPORTED` with `dispute_round` at 0. An incident's `severity_points` are fixed by its severity — 1 for `MINOR`, 3 for `MAJOR`, 6 for `SEVERE` — but those points count toward a member only while the incident is `UPHELD`. The incident's `status` moves among `REPORTED`, `UPHELD`, `DISMISSED`, and `DISPUTED`, with `DISMISSED` terminal.

A `ComplianceOfficer` adjudicates by supplying an `outcome` of `UPHOLD` or `DISMISS` plus an optional `adjudication_note`. Adjudication is legal only while the incident is `REPORTED` or `DISPUTED` (otherwise `ERR_INVALID_INCIDENT_STATE`), and the adjudicating `X-User-ID` must differ from the incident's `reported_by_user_id` — the segregation-of-duties rule of §2.9, whose breach is `ERR_SEGREGATION_OF_DUTIES`. Adjudication records `adjudicated_by_user_id`. A `DISMISS` moves the incident to `DISMISSED` and recomputes the member's `strike_points` (a dismissed incident contributes nothing). An `UPHOLD` moves it to `UPHELD` and recomputes `strike_points` and `standing_band`.

The strike total, `strike_points`, is the sum of `severity_points` over every incident that belongs to one of this member's tenancies, whose `status` is exactly `UPHELD`, and whose `occurred_at` is at or after the instant ninety days before the current clock instant. The window is half-open on the left: an incident exactly at the ninety-day boundary counts, one strictly older does not. Only `UPHELD` incidents count — `REPORTED`, `DISPUTED`, and `DISMISSED` contribute zero. The `standing_band` follows the total: `GOOD` at zero points, `WATCH` at one through five points, and `PROBATION` at six points or more.

Upholding an incident can trigger a four-hop cascade. Hop one is the strike recomputation just described. If that recomputation carries the member to six or more strike points — the suspension threshold — hop two fires: any of that member's tenancies currently `ACTIVE` is driven to `NOTICE_GIVEN` with `notice_reason` set to `COMPLIANCE` and `scheduled_move_out_date` set to the clock date plus a fourteen-day compliance-notice window, and its `provisional_final_charge_cents` is written per the provisional notice-block accounting of §3.8. Hop three drives that tenancy's room `OCCUPIED → NOTICE_PENDING`, setting the room's `available_from_date` to the `scheduled_move_out_date` plus the two-day turnover buffer. Hop four recomputes the house's room-state counts and then its `compliance_posture`. This cascade is triggered by the strike-point bump on the member, not directly by the adjudicate call — an uphold that leaves the member below the threshold stops after hop one.

The charged resident may dispute an `UPHELD` incident. Disputing is a `Member` action on a tenancy they own, supplying a `dispute_reason`; it is legal only while the incident is `UPHELD` (otherwise `ERR_INVALID_INCIDENT_STATE`) and only while `dispute_round` is below the two-round ceiling (otherwise `ERR_DISPUTE_LIMIT_REACHED`). A dispute moves the incident `UPHELD → DISPUTED`, increments `dispute_round` by one, records the `dispute_reason`, and recomputes `strike_points` — while under re-review a `DISPUTED` incident contributes zero, so a dispute can relax the member's `standing_band`. Even when a dispute drops the member back below the suspension threshold, an existing `COMPLIANCE` notice is left in place: `COMPLIANCE` notices never auto-rescind. From `DISPUTED`, a `ComplianceOfficer` may adjudicate again — `UPHOLD` back to `UPHELD` or `DISMISS` to `DISMISSED`, each recomputing `strike_points` and `standing_band`, each still segregated from the reporter — so the legal cycle is `UPHELD → DISPUTED → UPHELD`, bounded by the two-round ceiling. A member's standing is re-derived every time their record is read.

### 3.8. Giving Notice, Moving Out, and the Two Proration Variants

An `ACTIVE` tenancy enters its wind-down when notice is filed, a `Member` or `CommunityManager` action supplying a `reason` of `MEMBER_INITIATED` or `NONPAYMENT` and, for a member-initiated notice, a `scheduled_move_out_date`. Notice is legal only from `ACTIVE` (`ERR_INVALID_MEMBERSHIP_STATE`). A `MEMBER_INITIATED` notice must schedule the move-out at least fourteen days out — its `scheduled_move_out_date` must be on or after the clock date plus fourteen days, otherwise `ERR_NOTICE_TOO_SHORT`. A `NONPAYMENT` notice ignores the supplied date entirely and instead pins `scheduled_move_out_date` to the clock date plus a seven-day non-payment window; it is only permitted while the tenancy's `billing_status` is `PAST_DUE`, otherwise `ERR_NOT_PAST_DUE`. (The third notice reason, `COMPLIANCE`, is never filed through this operation — it arises only from the strike cascade of §3.7.)

Filing notice advances the tenancy `ACTIVE → NOTICE_GIVEN`, sets `notice_reason` and `scheduled_move_out_date`, writes `provisional_final_charge_cents` under the provisional variant below, drives the room `OCCUPIED → NOTICE_PENDING` while setting the room's `available_from_date` to the `scheduled_move_out_date` plus the two-day turnover buffer, and recomputes the house's `notice_pending_room_count`, `occupied_room_count`, and then `compliance_posture`.

The proration math shares one setup. The **target period** is the billing period of length `period_days` that contains the move-out date under evaluation, anchored on `move_in_date`: period *k* runs from `move_in_date` plus *k* times `period_days` through one day before the next period begins. The **period subtotal** for that period is its base rent plus its utility share, computed exactly as an invoice's subtotal is in §3.5.

- **Provisional notice-block (Variant A)** runs at notice time — both on a filed notice and on the compliance cascade — and writes `provisional_final_charge_cents`. It charges the entire period containing the move-out date with no daily refund whatsoever: the provisional final charge equals the full period subtotal. The resident is quoted a whole period. Variant A samples its `occupied_rooms_at_period_start` denominator as of the notice instant.
- **Final settlement daily (Variant B)** runs at move-out and writes `final_charge_cents`. It prorates by the day: the daily rate is the period subtotal divided by `period_days`, rounded half up once; the occupied-day count is the number of days from the target period's start through the `actual_move_out_date` inclusive of the move-out day; and the final charge is the daily rate multiplied by that occupied-day count as an exact integer product — the daily rate is rounded once, then multiplied, and the product is never rounded again. The proration adjustment written onto the invoice is the final charge minus the period subtotal, which is negative (a credit) whenever the resident occupied fewer than a full period's days. For an identical move-out date, Variant B is strictly smaller than Variant A whenever the occupied days fall short of a full period.

Move-out is a `CommunityManager` action from `NOTICE_GIVEN` (`ERR_INVALID_MEMBERSHIP_STATE`), supplying the real last billable day as `actual_move_out_date`. That date must be on or after the tenancy's `move_in_date` and on or before the current clock date, otherwise `ERR_INVALID_DATE_RANGE`. Move-out advances the tenancy `NOTICE_GIVEN → MOVED_OUT`, sets `actual_move_out_date` and `effective_end_date` (the latter being the actual move-out date when present, else the scheduled one — the right edge of the tenancy's closed occupancy interval on the room), writes `final_charge_cents` under Variant B, and applies the signed proration delta to the matching open invoice — writing the invoice's `proration_adjustment_cents` and then recomputing its `total_amount_cents`. The matching invoice is the tenancy's invoice in status `OPEN`, `PARTIAL`, or `PAST_DUE` whose period covers the actual move-out date (`period_start` on or before it and `period_end` on or after it); when several qualify, the one with the greatest `period_start`; when none exists, only `final_charge_cents` is written and no invoice is touched. Variant B reuses that matching invoice's stored `subtotal_cents` when an invoice exists. Move-out then recomputes `balance_due_cents`; if the balance is zero after the delta lands, the billing axis settles to `SETTLED`. Finally the room goes `NOTICE_PENDING → VACANT`, its `available_from_date` clears to null, and the house's room-state counts and `compliance_posture` are recomputed.

There is one back-edge on the tenancy axis. Only a `NONPAYMENT` notice auto-rescinds: when a payment brings a `NOTICE_GIVEN`, `NONPAYMENT` tenancy's `billing_status` back to `CURRENT`, the notice is undone — `notice_reason` and `scheduled_move_out_date` clear to null, `provisional_final_charge_cents` clears to null, the tenancy returns `NOTICE_GIVEN → ACTIVE`, the room returns `NOTICE_PENDING → OCCUPIED` with its `available_from_date` cleared, and the house counts and posture recompute. `MEMBER_INITIATED` and `COMPLIANCE` notices never auto-rescind.

### 3.9. Maintenance, Shared-Space SLAs, and the Rent Credit

A maintenance work order is opened against a house by a `Member` or a `CommunityManager`. It names the `house_id`, an `area` (`ROOM`, `SHARED_KITCHEN`, `SHARED_BATH`, `LAUNDRY`, or `COMMON_AREA`), a `severity` (`CRITICAL`, `HIGH`, or `NORMAL`), and a non-empty `description`. Two optional links widen the ticket's scope: `room_id`, set only for in-room work and null for shared-space work, and `affected_membership_id`, the tenancy entitled to a rent credit if the SLA is breached. When `room_id` is set, that room must belong to `house_id`, and when `affected_membership_id` is set, that tenancy must belong to the same house; either mismatch is `ERR_ENTITY_MISMATCH`. A `Member` opening a ticket must own the referenced tenancy. A ticket with a null `affected_membership_id` never yields a credit at all.

On creation the ticket opens in `OPEN` and its `sla_deadline_at` is computed as `created_at` plus the severity's SLA window — twenty-four hours for `CRITICAL`, seventy-two hours for `HIGH`, and one hundred sixty-eight hours for `NORMAL`. One creation-time cascade exists: a `CRITICAL` ticket whose `area` is `ROOM` and whose `room_id` names a room currently `VACANT` drives that room `VACANT → OUT_OF_SERVICE` and recomputes the house's `vacant_room_count` and `out_of_service_room_count`. A `CRITICAL` room ticket on a room that is `OCCUPIED` or `NOTICE_PENDING` does **not** take it out of service — the room keeps its tenancy state.

Scheduling a technician visit is a `CommunityManager` action from `OPEN` (`ERR_INVALID_TICKET_STATE`). It supplies `visit_start` and `visit_end` and the `expected_house_version` of §2.7. The window must be well-formed — `visit_end` strictly after `visit_start`, otherwise `ERR_INVALID_DATE_RANGE` — and it must respect house calendar capacity: over the half-open interval from `visit_start` up to but excluding `visit_end`, no instant may be covered by more than two `SCHEDULED` visits of the same house, counting the new one. Touching windows do not overlap — a visit ending exactly when another begins is fine — but exceeding the ceiling anywhere is `ERR_VISIT_CAPACITY_CONFLICT`. Scheduling stores `visit_start` and `visit_end`, advances the ticket `OPEN → SCHEDULED`, and increments the house's `version` by one.

Resolving a work order is a `CommunityManager` action legal from `OPEN` or `SCHEDULED` (resolving an already-`RESOLVED` ticket is `ERR_INVALID_TICKET_STATE`), taking an optional `resolution_note`. Resolution stamps `resolved_at` from the logical clock, computes `breach_hours`, writes `rent_credit_cents`, and — when the ticket had taken a room `OUT_OF_SERVICE` — returns that room `OUT_OF_SERVICE → VACANT` and recomputes the house's counts and posture. Resolving a `SCHEDULED` ticket also frees its `[visit_start, visit_end)` slot on the house calendar.

The SLA breach and credit are computed as follows. The elapsed time is the whole hours between `created_at` and `resolved_at`, taken by flooring to a whole number of hours; `breach_hours` is that elapsed figure minus the severity's SLA window, floored at zero (never negative). If the ticket has no `affected_membership_id`, or if `breach_hours` is zero, the `rent_credit_cents` is zero. Otherwise the credit builds from three independent roundings, in order: the daily rate is the affected tenancy's pinned `base_period_rate_cents` divided by its `period_days`, rounded half up; the breach is converted to whole days by dividing `breach_hours` by twenty-four and rounding **up** to the next whole day; the raw credit is the daily rate multiplied by that breach-day count and by the area weight, rounded half up; and a cap equal to the tenancy's `base_period_rate_cents` times one quarter, rounded half up, bounds the result. The final `rent_credit_cents` is the smaller of the raw credit and the cap. The area weight is 1.00 for `ROOM`, 0.50 for `SHARED_KITCHEN` and `SHARED_BATH`, and 0.25 for `LAUNDRY` and `COMMON_AREA`. The affected tenancy's pinned rate and period days are used, never the room's current rate card.

### 3.10. Payouts: Projection, Release, and the Dual-Basis Settlement

Remittance to the property owner runs through a `Payout`, opened by a `FinanceAdmin` naming the `house_id`, a `cycle_start`, and a `cycle_end` (both `YYYY-MM-DD`, both inclusive). The cycle must be ordered — `cycle_end` on or after `cycle_start`, otherwise `ERR_INVALID_DATE_RANGE` — and its closed `[cycle_start, cycle_end]` interval may not intersect any existing payout of the same house in status `DRAFT`, `PROJECTED`, or `RELEASED` (`ERR_PAYOUT_CYCLE_OVERLAP`). A new payout opens in `DRAFT` with every money field at zero and `variant_applied` set to `NONE`. Its `status` advances `DRAFT → PROJECTED → RELEASED`.

Both settlement passes read the same invoice set and the same ticket set. The **cycle invoices** are every invoice whose tenancy's `house_id` names this house and whose `period_start` falls within the closed cycle window (both ends inclusive), in any status — `OPEN`, `PARTIAL`, `PAST_DUE`, or `PAID`. The **cycle tickets** are every `RESOLVED` maintenance ticket of this house whose `resolved_at` date falls within the same closed window. The `maintenance_credit_cents` is the sum of `rent_credit_cents` over those tickets. An empty invoice set is legal and yields a gross of zero and a net of zero.

Projection — a `FinanceAdmin` action from `DRAFT` (`ERR_INVALID_PAYOUT_STATE`) — runs the **accrual** variant. The `gross_cents` is the sum of `total_amount_cents` over the cycle invoices (billed, not collected). The `platform_fee_cents` is the sum, over those same invoices, of each invoice's `total_amount_cents` times a platform fee rate of 0.125, rounded half up per invoice and then summed — the rounding is per-invoice and the sum of rounded lines is the answer; summing first and rounding once is wrong. The `reserve_cents` is the gross times a reserve rate of 0.05, rounded half up. The `net_payout_cents` is the gross minus the platform fee minus the maintenance credit minus the reserve, floored at zero. Projection sets `variant_applied` to `ACCRUAL_PROJECTION`, records the acting `X-User-ID` as `projected_by_user_id`, and advances the payout to `PROJECTED`.

Release — a `FinanceAdmin` action from `PROJECTED` (`ERR_INVALID_PAYOUT_STATE`) — re-runs the settlement on a **cash** basis and remits. It is blocked while the house `compliance_posture` is `FROZEN` (`ERR_HOUSE_FROZEN`, freshly re-evaluated), and the releasing `X-User-ID` must differ from `projected_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`). Under the cash variant the `gross_cents` is the sum of `amount_paid_cents` over the cycle invoices (collected only); the `platform_fee_cents` is the sum of each invoice's `amount_paid_cents` times 0.125, again rounded half up per invoice then summed; the `reserve_cents` drops to zero; and the `net_payout_cents` is gross minus platform fee minus maintenance credit, floored at zero — the same invoice set therefore produces a different net than the projection did, because it reads collected cash rather than billed amounts and releases the reserve. Release rewrites all the money fields, sets `variant_applied` to `CASH_FINAL`, records `released_by_user_id` and `released_at`, and advances the payout to `RELEASED`. The net is always remitted to the host's `payout_account_ref`.

## 4. Endpoint Definitions

Newly created resources are returned with HTTP 201; retrievals, listings, and state-changing operations that modify an existing resource return HTTP 200. The clock-setting capability also returns 200. The table below lists every endpoint with its authorized roles; the request and response shapes, side effects, and validation rules for each are given in the §3 narratives above.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/co-living/_clock/set_current_utc` | Sets the logical clock to a supplied instant | PlatformAdmin |
| POST | `/co-living/hosts` | Registers a property owner that receives payouts | PlatformAdmin |
| POST | `/co-living/houses` | Creates a co-living house under a host | Host, PlatformAdmin |
| GET | `/co-living/houses/{id}` | Reads one house with freshly re-evaluated posture and counts | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| GET | `/co-living/houses` | Lists houses, filterable by host and posture | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| POST | `/co-living/rooms` | Adds a rentable by-the-room unit to a house | Host, PlatformAdmin |
| PUT | `/co-living/rooms/{id}` | Revises a room's rate card or amenity flags (OCC on room version) | Host, PlatformAdmin |
| GET | `/co-living/rooms/{id}` | Reads one room | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| GET | `/co-living/rooms` | Lists rooms, filterable by house and occupancy state | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| POST | `/co-living/members` | Onboards a prospective resident | PlatformAdmin |
| GET | `/co-living/members/{id}` | Reads one member with recomputed strike points and standing | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| POST | `/co-living/applications` | Submits an application for a room at a chosen billing cycle | Member, CommunityManager |
| GET | `/co-living/applications/{id}` | Reads one application | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| GET | `/co-living/applications` | Lists applications, filterable by member, room and status | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| POST | `/co-living/applications/{id}/screening-reports` | Files a screening round, moving the application to SCREENED | ComplianceOfficer |
| GET | `/co-living/applications/{id}/screening-reports` | Lists screening rounds, oldest first | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| POST | `/co-living/applications/{id}/decision` | Renders the compliance decision (approve/deny with fork) | ComplianceOfficer |
| POST | `/co-living/applications/{id}/resubmit` | Sends a conditional application back for another round | Member |
| POST | `/co-living/memberships` | Converts an approved/conditional application into a tenancy | CommunityManager |
| GET | `/co-living/memberships/{id}` | Reads one tenancy with both state axes and the live balance | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| GET | `/co-living/memberships` | Lists tenancies, filterable by member, room, house, application and either axis | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| POST | `/co-living/memberships/{id}/move-in` | Moves the resident in; gated on OPEN posture | CommunityManager |
| POST | `/co-living/memberships/{id}/notice` | Files a move-out notice (member-initiated or nonpayment) | Member, CommunityManager |
| POST | `/co-living/memberships/{id}/move-out` | Finalizes move-out and settles proration | CommunityManager |
| POST | `/co-living/memberships/{id}/cancel` | Cancels a not-yet-moved-in tenancy and releases the room | CommunityManager, Member |
| POST | `/co-living/invoices` | Generates one all-in rent invoice for a period | FinanceAdmin |
| GET | `/co-living/invoices/{id}` | Reads one invoice with its full charge breakdown | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| GET | `/co-living/invoices` | Lists invoices, filterable by tenancy and status | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| POST | `/co-living/invoices/{id}/payments` | Applies cash to an invoice | Member, FinanceAdmin |
| GET | `/co-living/invoices/{id}/payments` | Lists cash applications, oldest first | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| POST | `/co-living/invoices/{id}/fee-adjustment` | Assesses or waives the tiered late fee | FinanceAdmin |
| POST | `/co-living/incidents` | Files a house-rule violation report against a tenancy | CommunityManager, ComplianceOfficer, Member |
| GET | `/co-living/incidents/{id}` | Reads one incident | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| GET | `/co-living/incidents` | Lists incidents, filterable by house, tenancy and status | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| POST | `/co-living/incidents/{id}/adjudicate` | Upholds or dismisses an incident (segregated from reporter) | ComplianceOfficer |
| POST | `/co-living/incidents/{id}/dispute` | Lets the charged resident dispute an upheld incident | Member |
| POST | `/co-living/tickets` | Opens a maintenance work order against a house | Member, CommunityManager |
| GET | `/co-living/tickets/{id}` | Reads one maintenance ticket | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| GET | `/co-living/tickets` | Lists maintenance tickets, filterable by house, room, tenancy and status | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| POST | `/co-living/tickets/{id}/schedule` | Books a technician visit window (OCC on house version) | CommunityManager |
| POST | `/co-living/tickets/{id}/resolve` | Closes the work order and issues any SLA-breach credit | CommunityManager |
| POST | `/co-living/payouts` | Opens a payout cycle for a house | FinanceAdmin |
| POST | `/co-living/payouts/{id}/project` | Runs the accrual projection and withholds the reserve | FinanceAdmin |
| POST | `/co-living/payouts/{id}/release` | Re-runs settlement on a cash basis and remits | FinanceAdmin |
| GET | `/co-living/payouts/{id}` | Reads one payout with its applied variant | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |
| GET | `/co-living/payouts` | Lists payouts, filterable by house and status | Host, Member, CommunityManager, ComplianceOfficer, FinanceAdmin, PlatformAdmin |

## 5. Error Code Catalogue

The trigger condition for each error is described in the §2 and §3 narratives above; this table gives only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_HOST_NOT_FOUND` | 404 |
| `ERR_HOUSE_NOT_FOUND` | 404 |
| `ERR_ROOM_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_MEMBERSHIP_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_INCIDENT_NOT_FOUND` | 404 |
| `ERR_TICKET_NOT_FOUND` | 404 |
| `ERR_PAYOUT_NOT_FOUND` | 404 |
| `ERR_ENTITY_MISMATCH` | 409 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_DUPLICATE_ROOM_NUMBER` | 409 |
| `ERR_MEMBER_ALREADY_HOUSED` | 409 |
| `ERR_APPLICATION_NOT_PENDING` | 409 |
| `ERR_ROOM_NOT_AVAILABLE` | 409 |
| `ERR_INVALID_MEMBERSHIP_STATE` | 409 |
| `ERR_INVALID_INCIDENT_STATE` | 409 |
| `ERR_INVALID_TICKET_STATE` | 409 |
| `ERR_INVALID_PAYOUT_STATE` | 409 |
| `ERR_INVOICE_NOT_PAYABLE` | 409 |
| `ERR_STALE_ROOM_VERSION` | 412 |
| `ERR_STALE_HOUSE_VERSION` | 412 |
| `ERR_BACKGROUND_FAILED` | 409 |
| `ERR_HOUSE_POSTURE_BLOCKED` | 409 |
| `ERR_HOUSE_FROZEN` | 409 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_MOVE_IN_DATE_IN_PAST` | 409 |
| `ERR_NOTICE_TOO_SHORT` | 409 |
| `ERR_NOT_PAST_DUE` | 409 |
| `ERR_INVALID_PERIOD_LENGTH` | 422 |
| `ERR_INVOICE_PERIOD_OVERLAP` | 409 |
| `ERR_PAYOUT_CYCLE_OVERLAP` | 409 |
| `ERR_LATE_FEE_NOT_DUE` | 409 |
| `ERR_LATE_FEE_ALREADY_ASSESSED` | 409 |
| `ERR_NO_LATE_FEE_TO_WAIVE` | 409 |
| `ERR_ROOM_TURNOVER_CONFLICT` | 409 |
| `ERR_VISIT_CAPACITY_CONFLICT` | 409 |
| `ERR_DISPUTE_LIMIT_REACHED` | 409 |
| `ERR_APPLICATION_ROUND_LIMIT` | 409 |
| `ERR_INCOME_INSUFFICIENT` | 422 |
| `ERR_OVERPAYMENT` | 422 |
