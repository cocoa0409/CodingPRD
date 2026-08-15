# GA Hangar Leasing API — Product Requirements Document

## 1. Introduction

General aviation airports operate some of the most constrained real estate in transportation: hangar space. Demand at most fields exceeds supply for years at a stretch, and the properties office must manage that scarcity fairly while honoring federal grant assurances that hangars serve aeronautical purposes. Today that work — tracking who is next in line for a T-hangar, whether a tenant's liability insurance has lapsed, when a lease last escalated, what to do with an aircraft abandoned after an eviction — is typically scattered across spreadsheets, filing cabinets, and institutional memory.

This document specifies an API that consolidates the entire hangar-leasing operation of a general aviation airport properties office into one system of record. It covers hangar inventory organized by size class with time-bounded rate schedules; a waitlist with a transparent priority score and a bounded offer-acceptance window; leases carrying an aeronautical-use attestation and explicit subleasing rules; tenant insurance and environmental compliance tracking; condition inspections that drive hangar availability; non-aeronautical-use audits with a cure window; annual rent escalation; monthly billing with late fees; and the full eviction pipeline through to abandoned-aircraft storage accrual.

Four acting roles use the system — the airport's properties manager, a compliance officer, waitlist applicants, and seated tenants — and nearly all time-dependent behavior (offer expiry, escalation, late fees, billing, compliance lapse detection) is driven by a single logical clock so that outcomes stay deterministic and auditable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once the headers are accepted, the named role must be permitted on the target endpoint per the authorization table in §4; otherwise the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Four roles exist, spelled exactly as follows:

- `AirportManager` — the airport properties office manager; administers airports, rate schedules, hangar inventory, offers, evictions, and inspection close-out.
- `ComplianceOfficer` — the airport's compliance and audit officer; files use-audit findings and reviews environmental records.
- `Applicant` — a prospective tenant on the waitlist.
- `Tenant` — an active leaseholder.

Identity semantics differ by role. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting WaitlistApplication; ownership checks on any resource that references a WaitlistApplication compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting Lease, and the same comparison rule applies to any resource that references a Lease. When `X-User-Role` is `AirportManager` or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server may record it, but it never compares it to any entity's `id`.

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

An unexpected server failure surfaces in the same envelope as `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

Every list endpoint accepts the query parameters `limit` and `offset`. The `limit` parameter defaults to 10 and is clamped into the range 1 to 100 — out-of-range values are clamped, not rejected; `offset` defaults to 0 and is clamped to a minimum of 0. A `limit` or `offset` that does not parse as an integer is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses are sorted by `created_at` ascending, with insertion order breaking ties between resources sharing the same logical instant. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in the system carries a common set of system-maintained properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` timestamps are ISO 8601 UTC values with three fractional digits, and `updated_at` refreshes on every mutation. The `version` property is an integer that increments on every mutation of the resource. All thirteen resource types — airports, hangars, rate schedules, waitlist applications, hangar offers, leases, lease aircraft, insurance certificates, environmental compliance records, condition inspections, use-audit findings, eviction cases, and rent charges — carry this full common set.

### 2.5. The Logical Clock and the Airport Sweep

All time-dependent behavior in the system is evaluated against a server-maintained logical clock, never against wall-clock time. Before any clock-setting call, the logical clock reads exactly 2026-08-01T00:00:00Z and must not fall back to wall-clock time. An `AirportManager` may move the clock through an admin-only test-driving capability that accepts a target instant `to_iso8601` and returns the resulting `current_utc`; the capability responds with 200 and accepts any target instant, including one earlier than the current reading.

Setting the clock runs the airport sweep at the new instant. The sweep iterates its duties in the listed order until a fixed point — a full pass producing no further change — so duties sequenced ahead of billing (late-fee accrual, the delinquency flip) also observe charges the billing pass creates within the same clock advance. Each pass expires offers whose acceptance window has closed; applies annual rent escalation to leases crossing an anniversary; accrues late fees on overdue charges; expires insurance certificates and environmental records whose end instant has been reached and auto-files insurance-lapse findings; accrues abandoned-aircraft storage on executed evictions; escalates audit findings whose cure deadline has passed into eviction cases; and issues monthly rent charges for elapsed billing periods. Sections 3.3, 3.5, 3.7, and 3.8 specify each duty. Every comparison against the logical clock is made at millisecond precision.

### 2.6. Monetary Values, Precision, and Rounding

All monetary amounts are integer cents — `monthly_rate_cents`, `quoted_monthly_rate_cents`, `base_monthly_rate_cents`, `current_monthly_rate_cents`, `liability_coverage_cents`, `base_amount_cents`, `late_fee_cents`, `paid_cents`, `balance_cents`, `outstanding_balance_cents`, `abandoned_aircraft_storage_cents_per_day`, and the payment `amount_cents` are all whole cents, and no fractional cent ever appears anywhere. Where a calculation must round, the rule is round half up to a whole cent, applied exactly once per specified step: annual escalation rounds once per anniversary step, and the late-fee daily amount and the late-fee cap each round half up. Two families of derivation use floor semantics instead: the pro-rated first rent charge rounds down at the daily level, and every day-count derivation (days queued, days overdue, days of storage) truncates fractional days. The pro-rated first charge is computed by pro-rating first and adding late fees later as a separate component; summing amounts before rounding is forbidden.

### 2.7. Optimistic Concurrency Control

Two write operations carry an optimistic-concurrency guard, and both reject a stale writer with `ERR_STALE_VERSION` (HTTP 412).

Accepting a hangar offer requires the request to carry `expected_hangar_version`, the `version` of the hangar as the client last observed it. If the hangar's current `version` no longer matches — for example because a prior acceptance already advanced the version and flipped the hangar's posture — the acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412). Executing an eviction case requires the request to carry `expected_lease_version`, matched against the lease's current `version`; if the lease's version has advanced since the client last read it — for example because a payment cascade bumped the version and returned the lease to good standing — the execution is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). No endpoint other than these two accepts a version field.

### 2.8. Hangar Posture: the Compound Availability Derivation

A hangar's `posture` is a derived field, recomputed on every mutation of a related lease or inspection rather than stored as an independent state. It takes four values. `AVAILABLE`: no lease on the hangar is in `ACTIVE`, `DELINQUENT`, `CURE_PERIOD`, or `EVICTION_PENDING`, and the hangar's `condition_rating` is not `OUT_OF_SERVICE`. `MAINTENANCE_HOLD`: no such lease exists and `condition_rating` is `OUT_OF_SERVICE`. `LEASED`: such a lease exists and `condition_rating` is not `OUT_OF_SERVICE`. `OFFLINE`: such a lease exists and `condition_rating` is `OUT_OF_SERVICE`. Only `AVAILABLE` hangars can receive new offers, and an `OPEN` offer reserves its hangar against further offers for its lifetime. That reservation is a behavioral gate on offer creation, not a fifth posture value: it never feeds the derivation above, so a hangar carrying an `OPEN` offer but no occupying lease and a serviceable `condition_rating` still reports `posture` `AVAILABLE`.

### 2.9. Validation Pipeline and Error Precedence

Every request passes through an ordered validation pipeline; when several checks would fail at once, the earliest check in this ordering determines the response. First, header presence and well-formedness (§2.1). Second, role authorization (§2.1). Third, path-resource existence, validated left to right (§2.10). Fourth, the airport-active gate: operations that require an `ACTIVE` airport are rejected with `ERR_AIRPORT_NOT_ACTIVE` (HTTP 409) while the airport is `SUSPENDED`. Fifth, resource state preconditions: each transition endpoint requires its target resource to be in a specific state, reported with the per-resource identifiers named throughout §3 — `ERR_APPLICATION_NOT_QUEUED`, `ERR_APPLICATION_NOT_WITHDRAWABLE`, `ERR_OFFER_NOT_OPEN`, `ERR_FINDING_NOT_OPEN`, `ERR_CASE_NOT_FILED`, `ERR_INSPECTION_NOT_OPEN`, `ERR_LEASE_NOT_AUDITABLE`, `ERR_LEASE_NOT_DELINQUENT`, `ERR_LEASE_NOT_EVICTED`, `ERR_LEASE_NOT_ACTIVE`, and `ERR_AIRPORT_NOT_SUSPENDED` — with an otherwise unclassified state failure surfacing as `ERR_INVALID_STATE` (HTTP 409). Sixth, time-window checks on the offer-acceptance and cure windows. Seventh, the queue-selection rule for new offers. Eighth, hangar availability, size-class matching, and rate-schedule coverage for new offers. Ninth, cross-entity referential rules such as tail-number uniqueness and the single-primary-aircraft invariant (HTTP 422). Tenth, compliance gates on insurance coverage and remediation attestation (HTTP 422). Eleventh, fiscal gates on balances, overpayment, and the delinquency threshold (HTTP 402). On the two optimistic-concurrency endpoints the version guard (§2.7) is evaluated after the time-window checks and before the remaining availability, cross-entity, and compliance checks; a missing or malformed `expected_hangar_version` or `expected_lease_version` field fails payload validation with `ERR_INVALID_REQUEST` (HTTP 400) at the point the field is consumed. Payload well-formedness checks generally run at the point each field is consumed, after the header and role checks.

### 2.10. Nested Resource Resolution

Endpoints that address a resource nested under others validate every path identifier left to right — the airport first, then the hangar, application, lease, or offer, then the child resource — and each `{id}` segment must identify an existing resource. A failure at any segment is rejected with `ERR_NOT_FOUND` (HTTP 404). A request whose path matches no endpoint, or whose method is not supported by a matched path, is likewise rejected with `ERR_NOT_FOUND` (HTTP 404). Identifiers carried in the request body rather than the path — as on offer creation — resolve under the same rule, and a body-referenced hangar or application that is not scoped to the named airport is also rejected with `ERR_NOT_FOUND` (HTTP 404).

## 3. Business Logic & Workflows

### 3.1. Airports, Rate Schedules, and Hangar Inventory

An airport is onboarded with an `airport_code` (an ICAO/FAA identifier such as KPAO) whose uniqueness the server records but does not enforce, a display `name`, the annual `escalation_pct` expressed as a decimal fraction (0.04 meaning four percent), an `escalation_policy` of either `ANNIVERSARY_COMPOUND` or `ANNIVERSARY_SIMPLE`, the `offer_acceptance_window_hours` an offer remains open before auto-expiry, the `cure_window_days` a tenant has to cure an audit finding before eviction may be filed, and the `late_fee_grace_days` after a rent charge's due date before late fees begin accruing. Both window lengths must be greater than zero, while `escalation_pct` and `late_fee_grace_days` may be zero but must not be negative; malformed creation payloads — a missing required field, an invalid enum spelling, or a non-positive value where a positive one is required — are rejected with `ERR_INVALID_REQUEST` (HTTP 400). A new airport starts in `ACTIVE` status.

Suspending an airport requires it to be `ACTIVE` — otherwise the request fails with `ERR_AIRPORT_NOT_ACTIVE` — and moves it to `SUSPENDED`. Suspension cascades: every `OPEN` offer at the airport moves to `CANCELLED`, and while `QUEUED` and `OFFERED` applications remain in place, none of them can receive new offers during the suspension. More broadly, while an airport is `SUSPENDED`, five operations are rejected with `ERR_AIRPORT_NOT_ACTIVE` (HTTP 409): submitting a waitlist application, extending an offer, accepting an offer, recording a lease payment, and filing an audit finding. Resuming requires the airport to be `SUSPENDED` (otherwise `ERR_AIRPORT_NOT_SUSPENDED`, HTTP 409) and returns it to `ACTIVE`.

Rate schedules price one size class at one airport. A schedule is created with its `airport_id`, the `size_class` it prices (one of `T_HANGAR`, `BOX`, `EXECUTIVE`, `CORPORATE`), a `monthly_rate_cents` that must be greater than zero, and a half-open coverage window running from `effective_from` (inclusive) to `effective_to` (exclusive); an open-ended schedule supplies the explicit string `'OPEN'` as `effective_to`, the only sanctioned null-equivalent. A missing or unparsable `effective_to` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and no check is made that `effective_to` falls after `effective_from`. Two schedules whose windows merely abut — one's `effective_to` equal to the other's `effective_from` — do not overlap: the boundary instant belongs to the later schedule. When a newer schedule is created for the same airport and size class with exactly the same `effective_from` as an existing one, the older schedule is marked `SUPERSEDED`; overlapping schedules with different start instants instead both remain `ACTIVE` and are resolved at selection time. Selection happens when an offer pins its quoted rate and at lease renewal: among the airport's `ACTIVE` schedules for the hangar's size class whose window contains the offer instant, the winner is the one with the latest `effective_from`, with `created_at` ascending as the final tie-break. If no schedule covers the instant, the operation is rejected with `ERR_NO_ACTIVE_RATE_SCHEDULE` (HTTP 409).

Hangars join an airport's inventory with an `airport_id`, a tenant-facing `hangar_code` (for example T-12) treated as a descriptive label whose uniqueness within the airport the server does not enforce, a `size_class` drawn from the same four-value enumeration, and a descriptive `door_type` of `SLIDING`, `BIFOLD`, or `HYDRAULIC` that never gates any operation. A new hangar starts with `condition_rating` `GOOD`, `posture` `AVAILABLE`, and `status` `OPERATIONAL`. Decommissioning is terminal: it requires that no lease in `ACTIVE`, `DELINQUENT`, `CURE_PERIOD`, or `EVICTION_PENDING` occupies the hangar (`ERR_HANGAR_OCCUPIED`, HTTP 409) and that no `OPEN` offer exists on it (`ERR_OPEN_OFFER_EXISTS`, HTTP 409). A decommissioned hangar leaves the inventory — `status` becomes `DECOMMISSIONED` and the hangar exits the `AVAILABLE` pool — but the decommission does not cascade: applications still `QUEUED` for that size class remain queued.

### 3.2. The Waitlist: Applications and Priority Scoring

A prospective tenant joins the waitlist by submitting an application carrying the target `airport_id`, the `applicant_name` and `applicant_contact`, the `size_class_requested` — the application competes only in that size class's queue — the `aircraft_n_number` of the aircraft to be based, required at application time as evidence of aeronautical intent, and `is_based_tenant_transfer`, which is true when the applicant already holds any `ACTIVE` lease at the same airport and is requesting an in-airport transfer; the flag is recorded as declared, without verifying any existing lease, and no limit is placed on how many applications an applicant files. The application enters `QUEUED` status with `decline_count` zero and a computed `priority_score`.

The priority score starts at one hundred base points, adds one point for every whole day the application has spent in the queue, and adds a thirty-point transfer bonus when `is_based_tenant_transfer` is true. Whole days queued are measured from the application's `created_at` to the ranking instant, truncating any fractional day. The score is computed at creation and recomputed lazily whenever the queue is ranked for an offer. Ranking sorts by score descending and breaks ties by `created_at` ascending — the older application ranks first; because timestamps carry millisecond precision and applications are created sequentially, no further tie-break exists and a random identifier is never consulted. Only applications in `QUEUED` status at the same airport whose `size_class_requested` matches the target hangar's `size_class` enter a ranking. Over its lifetime an application moves among `QUEUED`, `OFFERED`, `ACCEPTED`, `LEASED`, `WITHDRAWN`, `EXPIRED_OFFER`, and `REJECTED`, the last four of which are terminal.

### 3.3. The Offer Cycle: Extension, Expiry, Decline, and Withdrawal

An `AirportManager` extends an offer by naming an `airport_id`, a `hangar_id`, and an `application_id`, optionally setting `override_next_in_queue` to true. Creation enforces, in pipeline order: the airport must be `ACTIVE`; the application must be `QUEUED` (`ERR_APPLICATION_NOT_QUEUED`, HTTP 409); the application must be the highest-ranked eligible `QUEUED` application for the hangar's size class per the priority score, unless `override_next_in_queue` is true (`ERR_NOT_NEXT_IN_QUEUE`, HTTP 409); the hangar's `posture` must be `AVAILABLE`, the hangar must still be `OPERATIONAL` rather than `DECOMMISSIONED`, and no other `OPEN` offer may exist on the hangar (`ERR_HANGAR_NOT_AVAILABLE`, HTTP 409); the hangar's `size_class` must equal the application's `size_class_requested` (`ERR_SIZE_CLASS_MISMATCH`, HTTP 409); and an `ACTIVE` rate schedule must cover the offer instant (`ERR_NO_ACTIVE_RATE_SCHEDULE`).

A created offer lands in `OPEN` status with `offer_sent_at` set to the server timestamp and its `acceptance_deadline` exactly `offer_acceptance_window_hours` hours later. The offer pins `rate_schedule_id` to the selected schedule and copies that schedule's rate into `quoted_monthly_rate_cents`, which is immutable thereafter. The application moves from `QUEUED` to `OFFERED`, and the open offer now holds the §2.8 reservation against other offers — a gate on future offer creation that leaves the hangar's derived `posture` value unchanged — and offer creation itself does not increment the hangar's `version`.

Two deliberately asymmetric boundary rules govern the acceptance window. On the acceptance path, the applicant must act strictly before the `acceptance_deadline`; an acceptance attempted at exactly the deadline, or at any later instant, is rejected with `ERR_OFFER_WINDOW_EXPIRED` (HTTP 409). The sweep, in contrast, flips an `OPEN` offer to `EXPIRED` only when the logical clock is strictly later than the deadline — a lazy expiry. Consequently, at the exact deadline instant the offer row is still `OPEN` in storage, and an acceptance at that instant fails on the window rule rather than on a state check. When the sweep does expire an offer, the application moves to `EXPIRED_OFFER`, the expired offer's reservation on the hangar is released, and the hangar's posture is recomputed under the §2.8 formula — `AVAILABLE` whenever no occupying lease holds it and its `condition_rating` is not `OUT_OF_SERVICE`.

Declining requires the offer to be `OPEN` (`ERR_OFFER_NOT_OPEN`, HTTP 409) and increments the application's `decline_count`. Each application has exactly one free decline in its lifetime: a first decline returns the application to `QUEUED`, with the free-decline gate expressed in the error catalogue as `ERR_REPEAT_DECLINE_NOT_ALLOWED` (HTTP 409). A decline made when the application has already declined once — a `decline_count` of at least one at decline time — does not error; it moves the application to `REJECTED` and out of the queue. Either way the offer becomes `DECLINED` and the hangar's posture is recomputed toward `AVAILABLE`.

An applicant may withdraw while `QUEUED` or `OFFERED` — any other state fails with `ERR_APPLICATION_NOT_WITHDRAWABLE` (HTTP 409) — moving the application to `WITHDRAWN`; withdrawing while `OFFERED` also moves the linked `OPEN` offer to `CANCELLED` and recomputes the hangar's posture toward `AVAILABLE`. A manager may instead reject a `QUEUED` application (`ERR_APPLICATION_NOT_QUEUED`), moving it to `REJECTED`. Offers terminate in `ACCEPTED`, `DECLINED`, `EXPIRED`, or `CANCELLED`.

### 3.4. Lease Activation and Based Aircraft

Acceptance is the pivotal act of the system: the applicant accepts an `OPEN` offer, and in one atomic operation the lease is born. The acceptance payload carries `expected_hangar_version` (the optimistic-concurrency guard of §2.7), the tenant's `aeronautical_use_attested` attestation — which must be true at lease signing, primary aeronautical use being a condition of tenancy, an attestation of false being rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and `sublease_allowed`, recording whether subleasing is permitted under the lease and later gating unauthorized-sublease findings. It also carries the tenant's initial insurance evidence (`insurance_policy_number`, `insurance_insurer_name`, `insurance_liability_coverage_cents`, `insurance_effective_from`, `insurance_effective_to`) and the first aircraft to be based (`aircraft_n_number`, `aircraft_make_model`).

Beyond the concurrency guard, acceptance requires the offer to be `OPEN` (`ERR_OFFER_NOT_OPEN`), the logical clock to be strictly before the `acceptance_deadline` (`ERR_OFFER_WINDOW_EXPIRED`), the hangar to still be `OPERATIONAL` with its derived posture still `AVAILABLE` — nothing having displaced this offer's reservation (`ERR_HANGAR_NOT_AVAILABLE`), the insurance evidence to satisfy the full §3.7 compliance check at the acceptance instant — coverage meeting the minimum and a window containing that instant — (`ERR_INSUFFICIENT_COVERAGE`, HTTP 422), and the first aircraft's tail number to satisfy the same uniqueness rule as later additions (`ERR_DUPLICATE_N_NUMBER`, HTTP 422). On success — responded with 201 with the new lease in the data field — the offer becomes `ACCEPTED`; the new lease is created in `ACTIVE` status with `tenant_name` copied from the application's `applicant_name`, `base_monthly_rate_cents` copied from the offer's `quoted_monthly_rate_cents`, `lease_start_date` set to the server timestamp, and `last_escalation_anniversary` zero; the first rent charge is created pro-rated per §3.5; the insurance certificate is created in `VALID` status; the aircraft is created `BASED` and marked primary; and the hangar's `posture` becomes `LEASED` with its `version` incremented by one. Once the lease row commits, the application completes its journey from `ACCEPTED` to `LEASED` within the same request. The lease keeps immutable references to its originating application and offer (`application_id`, `offer_id`) alongside its `airport_id` and `hangar_id`.

Two derived figures track the lease's financial health thereafter: `current_monthly_rate_cents`, the escalated rate in force per §3.5, and the pair `days_delinquent` and `outstanding_balance_cents`. The outstanding balance is the sum of `balance_cents` across the lease's `OPEN` and `PARTIALLY_PAID` charges, kept in step on every charge creation, late-fee accrual, and payment. The delinquency figure is the largest overdue-day count among those same charges, or zero when none is past its grace window; it drives both the `DELINQUENT` status and the eviction threshold of §3.8.

A tenant adds further aircraft to the lease with `n_number` and `make_model` required and `is_primary` optional, defaulting to false, each record carrying its owning `lease_id`; the addition carries no lease-state precondition. The tail number must be unique among aircraft currently `BASED` on active-phase leases at the same airport (`ERR_DUPLICATE_N_NUMBER`, HTTP 422), and each lease has exactly one primary aircraft — the aeronautical-use anchor — so declaring a new primary while one already exists is rejected with `ERR_PRIMARY_AIRCRAFT_CONFLICT` (HTTP 422); the old primary must be removed first. Removing an aircraft, available to both the tenant and the manager, requires the aircraft to be `BASED` (otherwise `ERR_INVALID_STATE`, HTTP 409), sets its status to `REMOVED` with `removed_at` stamped, and stops abandoned-aircraft storage accrual for that airframe (§3.8).

### 3.5. Billing, Escalation, Late Fees, and Payments

Rent is billed through charges — each tied to its lease by `lease_id` — with a monthly service period running from `period_start` (inclusive) to `period_end` (exclusive) and a `due_date` equal to `period_start`. The first charge is created at lease activation for the partial period from `lease_start_date` to the first instant of the following calendar month; its `base_amount_cents` is the lease's `current_monthly_rate_cents` multiplied by the number of days remaining in the start month — counting the start day itself — divided by the number of days in that calendar month, with the result rounded down to a whole cent. Pro-rating happens first, with late fees added later as a separate component; amounts are never summed before rounding. On each sweep, for every lease in `ACTIVE`, `DELINQUENT`, `CURE_PERIOD`, or `EVICTION_PENDING` whose latest monthly rent charge's `period_end` is at or before the sweep instant — storage-accrual charges (§3.8) are ignored when locating that boundary — one new charge is created per fully elapsed calendar-month boundary, oldest period first, and never for a period beginning after the sweep instant. A full month's `base_amount_cents` is the `current_monthly_rate_cents` in force at that period's start — and because escalation runs before billing within the same sweep, an anniversary crossed by that sweep is already reflected in the charge.

Annual escalation follows the airport's `escalation_policy`. The sweep counts elapsed anniversaries, one per 365 days after `lease_start_date`, where an anniversary landing exactly on the sweep instant counts as elapsed while an instant one millisecond before it does not. Each anniversary not yet applied per `last_escalation_anniversary` is then applied in ascending order, rounding half up to a whole cent once per step: under `ANNIVERSARY_COMPOUND`, the running `current_monthly_rate_cents` is multiplied by one plus the airport's `escalation_pct`, so growth compounds on the already-escalated rate; under `ANNIVERSARY_SIMPLE`, the original `base_monthly_rate_cents` is multiplied by one plus `escalation_pct` times the index of the anniversary being applied, so growth is linear in the number of anniversaries. The two policies agree through the first anniversary and diverge from the second onward. After the pass, `last_escalation_anniversary` records how many anniversaries have been applied.

Late fees accrue per charge. A charge's overdue-day count is the number of whole days from the end of its grace window — `due_date` plus the airport's `late_fee_grace_days` — to the sweep instant, truncated, and never below zero; at exactly the end of the grace window the count is zero and no fee accrues, so the first fee day is the day after grace ends. When the count is positive, the daily fee is the greater of 500 cents and half a percent (0.005) of the charge's `base_amount_cents` rounded half up to a whole cent. The accrued fee is the daily fee times the overdue-day count, and `late_fee_cents` becomes the lesser of that accrual and a cap of 25 percent (0.25) of the same charge's `base_amount_cents`, rounded half up — the cap is per charge, never against the lease-wide balance. A charge's `balance_cents` is always its `base_amount_cents` plus `late_fee_cents` minus `paid_cents`, recomputed on every payment or fee event, and the charge's status moves among `OPEN`, `PARTIALLY_PAID`, and `PAID`.

Payments arrive from the tenant as `amount_cents`, which must be a positive integer (`ERR_INVALID_REQUEST`, HTTP 400), and are allocated by waterfall: charges in chronological order by `period_start` ascending with `created_at` ascending as the tie-break, and within each charge the late fees are paid first, then the base amount — fees before principal, in integer cents with no fractional allocation. Partial application to the final charge is allowed and leaves it `PARTIALLY_PAID`; an amount exceeding the total outstanding balance across the lease's `OPEN` and `PARTIALLY_PAID` charges is rejected atomically with `ERR_OVERPAYMENT` (HTTP 402) before any allocation, because the system holds no credit balances. A payment may be recorded against a lease in any status — including `EVICTED` or `TERMINATED` — subject only to the airport-active gate and the overpayment rule. A successful payment updates charge statuses and `paid_cents` totals, recomputes the lease's `outstanding_balance_cents`, increments the lease's `version`, and responds 200 with the updated lease in the data field.

The sweep moves an `ACTIVE` lease to `DELINQUENT` when any charge's `balance_cents` is positive and the logical clock has passed that charge's `due_date` plus the grace days, recomputing `days_delinquent`; the hangar's posture stays `LEASED` throughout, since a delinquent tenant still occupies. Paying down from `DELINQUENT` flips the lease back to `ACTIVE` only when the waterfall zeroes `outstanding_balance_cents`, resetting `days_delinquent` to zero. A payment that reduces but does not zero the balance is still applied to charges yet leaves the lease `DELINQUENT` — the no-flip behavior documented in the catalogue as `ERR_PARTIAL_CURE_NOT_ALLOWED` (HTTP 402).

### 3.6. Hangar Condition and Maintenance Responsibility

Condition inspections are opened on a hangar — the record carries its `hangar_id` — by a manager or a compliance officer, capturing the inspector's `condition_rating` (`GOOD`, `FAIR`, `POOR`, or `OUT_OF_SERVICE`), the `maintenance_responsibility` for remediating deficiencies (`TENANT`, `AIRPORT`, or `SHARED`), and a free-text `deficiency_note`. The inspection opens in `OPEN` status with `inspected_at` stamped by the server and `lease_id` bound to the lease occupying the hangar at inspection time — the empty string when the hangar is vacant. Inspections are retrievable both per hangar and per lease.

Closing an inspection is the manager's act and requires the inspection to be `OPEN` (`ERR_INSPECTION_NOT_OPEN`, HTTP 409). When `maintenance_responsibility` is `TENANT` and the rating is `POOR` or `OUT_OF_SERVICE`, a `remediation_note` attesting the remediation must accompany the close (`ERR_REMEDIATION_NOTE_REQUIRED`, HTTP 422). On close the inspection becomes `CLOSED`, the hangar's `condition_rating` adopts this inspection's rating — the latest `CLOSED` inspection always wins — the hangar's `version` increments, and its `posture` is recomputed under the compound rule of §2.8. That recomputation is how a hangar drops into `MAINTENANCE_HOLD` or `OFFLINE` on a failing rating and returns to service once a later inspection closes with a better one.

### 3.7. Insurance and Environmental Compliance

Tenants evidence liability insurance by submitting certificates — each bound to its `lease_id` — with `insurer_name`, `policy_number`, `liability_coverage_cents`, and a coverage window from `effective_from` (inclusive) to `effective_to` (exclusive). A lease is insurance-compliant at an instant exactly when some certificate for it is in `VALID` status, its window contains the instant, and its `liability_coverage_cents` is at least 100000000 cents — one million dollars of liability coverage. Lease activation enforces the same minimum (`ERR_INSUFFICIENT_COVERAGE`). Certificate submission applies this same check at the submission instant: a submission that fails it — coverage below the minimum or a window not containing the submission instant — is rejected with `ERR_INSUFFICIENT_COVERAGE` (HTTP 422), and one that passes is recorded `VALID`. On each sweep, any `VALID` certificate whose `effective_to` has been reached flips to `EXPIRED`, and a lease left with zero covering certificates is flagged with an `INSURANCE_LAPSE` finding per §3.8 unless one is already `OPEN`.

Environmental compliance runs on records of three `record_type` values — `FUEL_STORAGE_PERMIT`, `STORMWATER_PLAN`, and `HAZMAT_DISCLOSURE` — submitted by the tenant with an `expires_at` end instant and stamped `submitted_at` by the server, with no constraint placed on `expires_at` relative to the submission instant. A submission enters `PENDING_REVIEW`; a `ComplianceOfficer` then approves or rejects it with a required non-empty `review_note`, moving the record to `APPROVED` or `REJECTED`, and reviewing a record no longer `PENDING_REVIEW` fails with `ERR_INVALID_STATE` (HTTP 409). The sweep moves a `PENDING_REVIEW` or `APPROVED` record to `EXPIRED` once its `expires_at` has been reached; a `REJECTED` record never expires.

### 3.8. Use Audits, Cure Windows, Eviction, and Abandoned Aircraft

A `ComplianceOfficer` files a use-audit finding against a lease in `ACTIVE` or `DELINQUENT` status — any other state fails with `ERR_LEASE_NOT_AUDITABLE` (HTTP 409) — naming a `finding_type` of `NON_AERONAUTICAL_USE`, `UNAUTHORIZED_SUBLEASE`, `INSURANCE_LAPSE`, or `ENVIRONMENTAL_LAPSE`; an invalid spelling fails with `ERR_INVALID_REQUEST`. An `UNAUTHORIZED_SUBLEASE` finding applies only when the lease's `sublease_allowed` is false (`ERR_FINDING_NOT_APPLICABLE`, HTTP 422). The sweep also files `INSURANCE_LAPSE` findings automatically when a lease loses coverage, skipping the sublease check and requiring only that the lease is `ACTIVE` or `DELINQUENT`. A filed finding opens in `OPEN` status with `observed_at` stamped and its `cure_deadline` exactly the airport's `cure_window_days` days later. Filing against an `ACTIVE` lease moves it to `CURE_PERIOD`; filing against a `DELINQUENT` lease leaves it `DELINQUENT` with the finding `OPEN` alongside.

A finding is curable strictly before its `cure_deadline`; a cure attempt at exactly the deadline or later is rejected with `ERR_CURE_WINDOW_EXPIRED` (HTTP 409), and curing a finding that is not `OPEN` fails with `ERR_FINDING_NOT_OPEN` (HTTP 409). Two finding types carry evidence gates: curing an `INSURANCE_LAPSE` requires a `VALID` certificate covering the current instant (`ERR_INSURANCE_STILL_LAPSED`, HTTP 422), and curing an `ENVIRONMENTAL_LAPSE` requires an `APPROVED` environmental record covering the current instant (`ERR_ENVIRONMENTAL_STILL_LAPSED`, HTTP 422). A successful cure stamps `cured_at`, moves the finding to `CURED`, and — when the lease is in `CURE_PERIOD` and no other `OPEN` findings remain on it — returns the lease to `ACTIVE`; a lease that was `DELINQUENT` when the finding was filed stays `DELINQUENT` on cure.

When the sweep reaches a `cure_deadline` with the finding still `OPEN`, the finding becomes `ESCALATED_TO_EVICTION`, an eviction case is auto-created in `FILED` status with `reason` `UNCURED_AUDIT` and `use_audit_finding_id` pointing at that finding, and the lease moves to `EVICTION_PENDING` — a three-hop cascade from sweep to finding to case to lease. Delinquency takes a manual path instead: a manager files the case with a `reason` that defaults to `DELINQUENCY` when omitted and may be any of the three enumeration values (`UNCURED_AUDIT`, `DELINQUENCY`, `NON_AERONAUTICAL_USE`), against a lease that is `DELINQUENT` (`ERR_LEASE_NOT_DELINQUENT`, HTTP 409) and whose `days_delinquent` has reached the fixed system threshold of thirty days (`ERR_DELINQUENCY_THRESHOLD_NOT_MET`, HTTP 402); such cases carry an empty `use_audit_finding_id`. Filing stamps `filed_at`, moves the lease to `EVICTION_PENDING`, and increments the lease's `version`.

Executing a case requires it to be `FILED` (`ERR_CASE_NOT_FILED`, HTTP 409) and carries the `expected_lease_version` concurrency guard of §2.7. Execution stamps `executed_at`, snapshots the abandoned-aircraft daily storage rate of 2500 cents into `abandoned_aircraft_storage_cents_per_day`, zeroes `storage_days_already_billed`, moves the case to `EXECUTED` and the lease to `EVICTED`, increments the lease's `version` by one, and recomputes the hangar's posture to `AVAILABLE` — the hangar is freed even though aircraft may still sit inside it, because storage now accrues against the evicted tenant. The aircraft themselves remain `BASED` until removed.

From execution onward, the sweep accrues storage for each `EXECUTED` case whose lease still has at least one `BASED` aircraft: it takes the whole days elapsed since `executed_at`, subtracts `storage_days_already_billed`, and when that difference is positive records an accrual of the day count multiplied by the snapshotted daily rate multiplied by the number of `BASED` aircraft on the lease, then advances `storage_days_already_billed` by the day count. Storage is charged per based aircraft per day. Each accrual is recorded as an additional rent charge on the lease — its period running from `executed_at` plus the previously billed days to the sweep instant — and enters the same ledger as monthly rent charges: it adds to the lease's `outstanding_balance_cents`, accrues late fees, and is paid down by the payment waterfall, while remaining invisible to the monthly billing pass of §3.5.

A lease closes in one of three ways. A tenant terminates voluntarily from `ACTIVE` or `DELINQUENT` — `ERR_LEASE_NOT_ACTIVE` (HTTP 409) guards the state requirement — with `outstanding_balance_cents` at zero (`ERR_OUTSTANDING_BALANCE`, HTTP 402), and the hangar's posture returns to `AVAILABLE`. A manager closes out an `EVICTED` lease (`ERR_LEASE_NOT_EVICTED`, HTTP 409) once every aircraft is `REMOVED`; if any aircraft remains `BASED`, the terminating request must carry `abandon_remaining_aircraft` set to true, otherwise it is rejected with `ERR_AIRCRAFT_STILL_BASED` (HTTP 409). Either close-out moves the lease to `TERMINATED` and resolves the case: `CLOSED_AIRCRAFT_REMOVED` when all aircraft were removed, or `CLOSED_AIRCRAFT_ABANDONED` when remaining aircraft are abandoned — in which case those aircraft flip to `REMOVED` with `removed_at` stamped and storage accrual stops. `EVICTED` and `TERMINATED` are the lease's terminal states.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with 201; endpoints that modify an existing resource or perform an action respond with 200 — this includes offer acceptance, which responds 201 because it creates the lease. Paths below are relative to the service root. List endpoints accept the pagination parameters of §2.3 plus resource filters: an airport's hangars filter by `size_class` and `posture`; rate schedules by `airport_id` and `size_class`; the hangar list by `airport_id`, `size_class`, and `posture`; applications by `airport_id`, `size_class_requested`, and `status`; offers by `airport_id`, `hangar_id`, `application_id`, `rate_schedule_id`, and `status`; leases by `airport_id`, `hangar_id`, `application_id`, `offer_id`, and `status`; audit findings and rent charges by `status`; and the eviction-case list by `use_audit_finding_id` and `lease_id`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the server logical clock; runs the airport sweep at the new instant | AirportManager |
| POST | /airports | Create an airport | AirportManager |
| GET | /airports | List airports | AirportManager, ComplianceOfficer, Applicant, Tenant |
| GET | /airports/{id} | Get an airport | AirportManager, ComplianceOfficer, Applicant, Tenant |
| POST | /airports/{id}/suspend | Suspend an airport (cancels open offers) | AirportManager |
| POST | /airports/{id}/resume | Resume a suspended airport | AirportManager |
| GET | /airports/{id}/hangars | List hangars of an airport | AirportManager, ComplianceOfficer, Applicant, Tenant |
| POST | /rate-schedules | Create a rate schedule for a size class at an airport | AirportManager |
| GET | /rate-schedules | List rate schedules (filtered) | AirportManager, ComplianceOfficer, Applicant, Tenant |
| GET | /rate-schedules/{id} | Get a rate schedule | AirportManager, ComplianceOfficer, Applicant, Tenant |
| POST | /hangars | Add a hangar to an airport's inventory | AirportManager |
| GET | /hangars | List hangars (filtered) | AirportManager, ComplianceOfficer, Applicant, Tenant |
| GET | /hangars/{id} | Get a hangar | AirportManager, ComplianceOfficer, Applicant, Tenant |
| POST | /hangars/{id}/decommission | Decommission a hangar | AirportManager |
| POST | /applications | Submit a waitlist application | Applicant |
| GET | /applications | List waitlist applications (filtered) | AirportManager, ComplianceOfficer, Applicant, Tenant |
| GET | /applications/{id} | Get an application | AirportManager, ComplianceOfficer, Applicant, Tenant |
| POST | /applications/{id}/withdraw | Withdraw an application | Applicant |
| POST | /applications/{id}/reject | Reject an application (manager) | AirportManager |
| POST | /offers | Extend a hangar offer to the next eligible applicant | AirportManager |
| GET | /offers | List offers (filtered) | AirportManager, ComplianceOfficer, Applicant, Tenant |
| GET | /offers/{id} | Get an offer | AirportManager, ComplianceOfficer, Applicant, Tenant |
| POST | /offers/{id}/accept | Applicant accepts an offer; creates the lease | Applicant |
| POST | /offers/{id}/decline | Applicant declines an offer | Applicant |
| GET | /leases | List leases (filtered) | AirportManager, ComplianceOfficer, Applicant, Tenant |
| GET | /leases/{id} | Get a lease | AirportManager, ComplianceOfficer, Applicant, Tenant |
| POST | /leases/{id}/payments | Tenant makes a payment; waterfall allocation across open charges | Tenant |
| POST | /leases/{id}/terminate | Terminate a lease (voluntary when ACTIVE/DELINQUENT with zero balance; manager close-out when EVICTED) | Tenant, AirportManager |
| POST | /leases/{id}/aircraft | Add an aircraft to a lease | Tenant |
| GET | /leases/{id}/aircraft | List aircraft on a lease | AirportManager, ComplianceOfficer, Applicant, Tenant |
| POST | /aircraft/{id}/remove | Remove an aircraft from its lease (abandoned-aircraft flow after eviction) | Tenant, AirportManager |
| POST | /leases/{id}/insurance-certificates | Submit a new insurance certificate | Tenant |
| GET | /leases/{id}/insurance-certificates | List insurance certificates for a lease | AirportManager, ComplianceOfficer, Applicant, Tenant |
| POST | /leases/{id}/environmental-records | Submit an environmental compliance record | Tenant |
| GET | /leases/{id}/environmental-records | List environmental records for a lease | AirportManager, ComplianceOfficer, Applicant, Tenant |
| POST | /environmental-records/{id}/approve | Approve an environmental record | ComplianceOfficer |
| POST | /environmental-records/{id}/reject | Reject an environmental record | ComplianceOfficer |
| POST | /hangars/{id}/inspections | Open a condition inspection | AirportManager, ComplianceOfficer |
| GET | /hangars/{id}/inspections | List inspections for a hangar | AirportManager, ComplianceOfficer, Applicant, Tenant |
| GET | /leases/{id}/inspections | List inspections bound to a lease | AirportManager, ComplianceOfficer, Applicant, Tenant |
| POST | /inspections/{id}/close | Close an inspection; applies condition rating to hangar | AirportManager |
| POST | /leases/{id}/audit-findings | File a non-aeronautical-use / compliance audit finding | ComplianceOfficer |
| GET | /leases/{id}/audit-findings | List audit findings for a lease | AirportManager, ComplianceOfficer, Applicant, Tenant |
| GET | /audit-findings/{id} | Get an audit finding | AirportManager, ComplianceOfficer, Applicant, Tenant |
| POST | /audit-findings/{id}/cure | Tenant cures a finding before its deadline | Tenant |
| POST | /leases/{id}/eviction-cases | File an eviction case (delinquency) | AirportManager |
| GET | /leases/{id}/eviction-cases | List eviction cases for a lease | AirportManager, ComplianceOfficer, Applicant, Tenant |
| GET | /eviction-cases | List eviction cases (filtered) | AirportManager, ComplianceOfficer, Applicant, Tenant |
| GET | /eviction-cases/{id} | Get an eviction case | AirportManager, ComplianceOfficer, Applicant, Tenant |
| POST | /eviction-cases/{id}/execute | Execute an eviction (OCC on lease version) | AirportManager |
| GET | /leases/{id}/rent-charges | List rent charges for a lease | AirportManager, ComplianceOfficer, Applicant, Tenant |
| GET | /rent-charges/{id} | Get a rent charge | AirportManager, ComplianceOfficer, Applicant, Tenant |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflow that raises it in §2 and §3; this table is the identifier-to-status index only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_AIRPORT_NOT_ACTIVE | 409 |
| ERR_AIRPORT_NOT_SUSPENDED | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_APPLICATION_NOT_QUEUED | 409 |
| ERR_APPLICATION_NOT_WITHDRAWABLE | 409 |
| ERR_OFFER_NOT_OPEN | 409 |
| ERR_OFFER_WINDOW_EXPIRED | 409 |
| ERR_CURE_WINDOW_EXPIRED | 409 |
| ERR_NOT_NEXT_IN_QUEUE | 409 |
| ERR_HANGAR_NOT_AVAILABLE | 409 |
| ERR_SIZE_CLASS_MISMATCH | 409 |
| ERR_NO_ACTIVE_RATE_SCHEDULE | 409 |
| ERR_REPEAT_DECLINE_NOT_ALLOWED | 409 |
| ERR_HANGAR_OCCUPIED | 409 |
| ERR_OPEN_OFFER_EXISTS | 409 |
| ERR_LEASE_NOT_AUDITABLE | 409 |
| ERR_FINDING_NOT_APPLICABLE | 422 |
| ERR_FINDING_NOT_OPEN | 409 |
| ERR_INSURANCE_STILL_LAPSED | 422 |
| ERR_ENVIRONMENTAL_STILL_LAPSED | 422 |
| ERR_LEASE_NOT_DELINQUENT | 409 |
| ERR_DELINQUENCY_THRESHOLD_NOT_MET | 402 |
| ERR_CASE_NOT_FILED | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_LEASE_NOT_ACTIVE | 409 |
| ERR_LEASE_NOT_EVICTED | 409 |
| ERR_AIRCRAFT_STILL_BASED | 409 |
| ERR_OUTSTANDING_BALANCE | 402 |
| ERR_OVERPAYMENT | 402 |
| ERR_PARTIAL_CURE_NOT_ALLOWED | 402 |
| ERR_DUPLICATE_N_NUMBER | 422 |
| ERR_PRIMARY_AIRCRAFT_CONFLICT | 422 |
| ERR_INSUFFICIENT_COVERAGE | 422 |
| ERR_REMEDIATION_NOTE_REQUIRED | 422 |
| ERR_INSPECTION_NOT_OPEN | 409 |
