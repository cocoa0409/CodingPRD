# Animal-Control Dispatch API — Product Requirements Document

## 1. Introduction

Municipal animal-control agencies operate at the intersection of public-safety response, animal welfare, and public-health law. A single incoming call — a loose dog in a schoolyard, a bite requiring rabies observation, a cruelty complaint — can spawn a chain of obligations that runs from field dispatch through investigation, quarantine, impound, citation, court referral, and a legally time-boxed report to the county health department. This document specifies the Animal-Control Dispatch API, a backend service that models that entire chain of custody as a set of linked resources under the `/dispatch` namespace.

The system is organized around workflow orchestration: complaints are triaged and priority-scored at intake, officers are dispatched against their territory and duty windows, and cases are opened, investigated, and resolved with risk scoring that evolves as evidence accumulates. Downstream of a case, the API governs quarantine holds with statutory observation windows, animal impounds with kennel-occupancy accounting and owner-facing boarding charges, citations with repeat-offender fine escalation, and rabies reports with hard reporting deadlines. Because many of these obligations must be discharged in a specific order — a case cannot close while an animal is still held, a quarantine cannot be lifted before its observation window elapses — the system enforces a precise, layered set of validations and propagates state changes across related records automatically.

All temporal rules — duty windows, quarantine release eligibility, reporting deadlines, boarding-day accrual — are evaluated against a server-controlled logical clock rather than wall-clock time, so that operational timelines can be exercised deterministically. The remainder of this document defines the global contract every endpoint honors (Section 2), the domain workflows and their scattered business rules (Section 3), the endpoint surface (Section 4), and the canonical error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `Dispatcher`, `FieldOfficer`, `Supervisor`, and `HealthDeptLiaison`.

- A `Dispatcher` is the call-taker. They intake complaints, assign officers to complaints, record citation payments, and read the operational dashboard.
- A `FieldOfficer` is the field agent who accepts and clears their own dispatches, opens and works assigned cases, appends investigation notes, places quarantine holds, impounds animals, issues citations, and submits rabies reports.
- A `Supervisor` performs administrative and override operations: registering officers and kennels, reopening and closing cases, escalating quarantine holds, referring citations to court, and setting the logical clock. A `Supervisor` may also perform any operation available to a `FieldOfficer`, and is exempt from the officer-ownership checks described below.
- A `HealthDeptLiaison` is the county-health contact who reads and clears rabies reports.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `FieldOfficer`, `X-User-ID` is the `id` of the acting `Officer`; ownership checks on any resource that references an officer compare that resource's officer foreign key to `X-User-ID`. Concretely, a `FieldOfficer` may accept or clear a dispatch only when `X-User-ID` equals the dispatch's `officer_id`, and may investigate or resolve a case only when `X-User-ID` equals the case's `assigned_officer_id`; a mismatch is rejected with `ERR_NOT_ASSIGNED_OFFICER`. When `X-User-Role` is `Dispatcher`, `Supervisor`, or `HealthDeptLiaison`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit — for example, an investigation note captures the author's `X-User-ID` as `author_id` and their `X-User-Role` as `author_role` — but it does not compare it to any entity's `id`. A `Supervisor` acting on a dispatch or case is never subject to the ownership comparison.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. Each list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the number of matching rows before pagination and `has_more` indicates whether rows remain beyond the current page.

### 2.4. Common Resource Properties

Most resources carry a standard set of system-managed fields:

- `id` — a unique, server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created; like `updated_at` (and the envelope's `api_request_timestamp`), it is stamped from the host's wall clock rather than the logical clock of Section 2.5.
- `updated_at` — an ISO 8601 UTC timestamp recording the last modification; it is refreshed on every mutation.
- `version` — an integer that begins at 1 on creation and increments by one on every mutation of the resource. It underpins the optimistic-concurrency mechanism of Section 2.8.

One resource type is deliberately exempt. An `InvestigationNote` is an append-only, immutable audit record: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because once written it is never modified. Every other resource type — `Complaint`, `Officer`, `Kennel`, `Dispatch`, `Case`, `QuarantineHold`, `Impound`, `Citation`, and `RabiesReport` — carries the full four-field set.

### 2.5. The Logical Clock

The service maintains a single logical clock that stands in for "now" everywhere a temporal rule is evaluated — officer duty windows, quarantine release eligibility, boarding-day accrual, citation due dates, and rabies reporting deadlines all read this clock rather than the host's wall clock. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any client sets it, every temporal evaluation uses that default instant (never the machine's real time). A `Supervisor` may advance or rewind the clock by supplying a target instant as `to_iso8601`; the operation returns the new clock value as `current_utc`. Timestamps such as a case's `substantiated_at`, a citation's `issued_at`, and a rabies report's `submitted_at` are stamped from this logical clock at the moment the corresponding operation executes.

### 2.6. Validation Order and Request Integrity

When more than one rule could reject a request, the checks are applied in a fixed priority order, and the first failing check determines the error returned. This ordering is a contract: a lower-priority violation must never mask a higher-priority one.

1. **Authentication.** Headers present and `X-User-Role` known — otherwise `ERR_UNAUTHENTICATED` (401).
2. **Authorization.** The acting role is permitted for the operation per the role model of Section 2.1 — otherwise `ERR_UNAUTHORIZED` (403).
3. **Existence.** Every id in the URL path and every foreign-key id in the request body must resolve to an existing resource, validated left-to-right; the first unresolved id yields the matching not-found error (`ERR_COMPLAINT_NOT_FOUND`, `ERR_OFFICER_NOT_FOUND`, `ERR_KENNEL_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_QUARANTINE_HOLD_NOT_FOUND`, `ERR_IMPOUND_NOT_FOUND`, `ERR_CITATION_NOT_FOUND`, or `ERR_RABIES_REPORT_NOT_FOUND`), all 404.
4. **Ownership.** For the dispatch accept, dispatch clear, case investigate, and case resolve operations, a `FieldOfficer` whose `X-User-ID` does not match the target's owning officer is rejected with `ERR_NOT_ASSIGNED_OFFICER` (403); a `Supervisor` is exempt.
5. **State.** The target must be in a state from which the requested transition is legal — otherwise `ERR_INVALID_STATE`, or the more specific `ERR_COMPLAINT_NOT_DISPATCHABLE` or `ERR_CITATION_ALREADY_RESOLVED`, all 409.
6. **Cross-entity eligibility.** The linked case must satisfy the operation's eligibility predicate — `ERR_CASE_TYPE_NOT_ELIGIBLE`, `ERR_CASE_NOT_ACTIONABLE`, or `ERR_COMPLAINT_NOT_DISPATCHABLE`, all 409 (detailed in Section 3).
7. **Safety.** Case closure blocked by an active hold or a held impound, and premature quarantine release, are rejected here — `ERR_ACTIVE_QUARANTINE_HOLD`, `ERR_ACTIVE_IMPOUND`, or `ERR_QUARANTINE_NOT_ELAPSED`, all 409.
8. **Temporal windows.** Officer schedule conflicts and kennel occupancy conflicts — `ERR_OFFICER_SCHEDULE_CONFLICT` or `ERR_KENNEL_OCCUPIED`, both 409.
9. **Capacity and duty.** Officer off-duty or at dispatch capacity — `ERR_OFFICER_OFF_DUTY` or `ERR_OFFICER_CAPACITY_EXCEEDED`, both 409.
10. **Fiscal.** Case closure blocked by an unresolved citation — `ERR_OUTSTANDING_CITATIONS` (409).
11. **Optimistic concurrency.** A stale `expected_case_version` on impound creation — `ERR_STALE_CASE_VERSION` (412).
12. **Request integrity.** Required body fields present, enum values valid, datetimes parseable, numeric fields well-formed, and window ordering satisfied (`scheduled_end_at` strictly after `scheduled_start_at`; `hold_until` strictly after `impounded_at`) — otherwise `ERR_INVALID_REQUEST` (422).

Note that request-integrity (well-formedness) sits at the lowest priority: a request that also violates authentication, authorization, existence, or a business rule surfaces that higher-priority error first.

### 2.7. Cascading State Propagation and Conserved Counters

A single operation frequently mutates more than one resource, and the system performs every such propagation automatically, without a separate client call on the affected record. Each resource the server touches independently has its `updated_at` refreshed and its `version` incremented as part of the same operation.

Several fields are **conserved counters** — running totals the system maintains as linked records come and go, rather than values a client supplies:

- An `Officer` carries `active_dispatch_count`, the number of that officer's dispatches currently in `PENDING` or `EN_ROUTE`. It starts at 0 when the officer is registered, rises by one when a dispatch is assigned to the officer, and falls by one when one of the officer's dispatches is cleared.
- A `Kennel` carries `occupied_slots`, the number of impounds in that kennel currently in `HELD`. It starts at 0, rises by one when an impound is recorded there, and falls by one when that impound is released (under any disposition, including a euthanasia driven by cascade).
- A `Case` carries `outstanding_fines_total`, the sum of `fine_amount` across the case's citations still in `ISSUED`. It rises by the fine when a citation is issued and falls by the fine when that citation is paid or referred to court.

State changes also ripple across resource boundaries. Clearing a dispatch drives its linked complaint from `DISPATCHED` to `RESOLVED`; closing a case drives its linked complaint to `CLOSED`; resolving a case as unfounded voids the case's active quarantine holds; escalating a quarantine hold euthanizes the case's held impounds, and each such euthanasia in turn escalates the case's outstanding rabies reports and flags the case for public health. The full chains, their triggering states, and their precise side-effects are specified in Section 3.

### 2.8. Optimistic Concurrency Control on Impound Creation

Recording an impound against a case bumps that case's `version` (because the case now owns another held animal and its child bookkeeping has changed). A single case may legitimately hold several impounds over its life, so the system guards impound creation with an optimistic-concurrency check to prevent a client from acting on a stale view of the case.

Every impound-creation request must carry `expected_case_version`, the `version` of the target `Case` as the client last observed it. If `expected_case_version` does not equal the case's current `version`, the creation is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). This is the only endpoint that takes a version field; no other create or action endpoint accepts or requires one. The mechanism ensures that when one writer has advanced the case since the client's last read — for instance by recording an earlier impound — a second create still carrying the pre-advance version is refused rather than silently layered on top of a case the client has not re-read.

### 2.9. Monetary Values and Precision

All monetary amounts — severity contributions, fines, and boarding fees — are computed with decimal arithmetic and rounded half up. Unless a calculation specifies otherwise, the final stored and returned value is rounded to exactly two decimal places using the round-half-up convention, and monetary values are returned as JSON numbers. One calculation, the impound boarding fee, rounds at a finer grain than the whole: it rounds each taxed line item to two decimal places and then sums the already-rounded lines, which can differ in the cents place from rounding a single grand total. That per-line rule is stated precisely in Section 3.6 and must be followed exactly.

### 2.10. Nested Resource Resolution

Some paths address a child resource beneath a parent — for example, the investigation notes of a case. For any such request, the system validates the path identifiers left-to-right and rejects at the first identifier that does not resolve, returning that identifier's not-found error before considering anything to its right. A request for the notes of a non-existent case therefore fails with `ERR_CASE_NOT_FOUND` rather than returning an empty list. The same left-to-right resolution governs foreign-key ids carried in request bodies, as described in the validation ordering of Section 2.6.

## 3. Business Logic & Workflows

### 3.1. Complaint Intake and Priority Scoring

Every operational thread begins when a `Dispatcher` (or a `Supervisor`) intakes a call. Intake captures the caller's `reporter_name` and `reporter_phone`, the incident's `zone` (one of `NORTH`, `SOUTH`, `EAST`, `WEST`, or `CENTRAL`), the `animal_type` (`DOG`, `CAT`, `WILDLIFE`, `LIVESTOCK`, or `OTHER`), and the `complaint_type` (`STRAY`, `BITE`, `CRUELTY`, `DANGEROUS_DOG`, `NOISE`, or `OTHER`). An optional free-text `description` may accompany the call, and the optional `involves_vulnerable_victim` flag records whether a minor or elderly person is involved; when omitted it is treated as false. A newly intaken complaint enters `status` `NEW`.

At the instant of intake the system computes a `severity_score` and a derived `priority`. The score starts from a base determined by `complaint_type`: a bite scores 50, a dangerous-dog report 40, a cruelty complaint 35, a stray 15, a noise complaint 5, and any other type 10. That base is multiplied by an animal factor keyed on `animal_type`: wildlife multiplies by 1.5, dogs by 1.2, livestock by 1.1, and both cats and the catch-all "other" by 1.0. To this product two additive bonuses are applied. The first is a repeat-incident bonus: the system counts the complaints already persisted in the same `zone` whose `status` is either `NEW` or `DISPATCHED` (excluding the complaint being created, with no time window — the count is taken over currently-open same-zone rows at the moment of insertion), multiplies that count by 5, and caps the result at 20. The second is a vulnerable-victim bonus of 15 points, added when `involves_vulnerable_victim` is true and 0 otherwise. The `severity_score` is the animal-weighted base plus the repeat bonus plus the vulnerable bonus, rounded half up to two decimal places.

The `priority` field is then derived from the score: a score of at least 60 is `P1`, a score of at least 30 but below 60 is `P2`, and anything below 30 is `P3`. Both `severity_score` and `priority` are server-computed and are never supplied by the client.

### 3.2. Officers, Duty Windows, and Dispatch Assignment

A `Supervisor` registers each field officer, recording the officer's `name`, `badge_number`, primary `territory_zone` (one of the five zones), and an on-duty window bounded by `shift_start_at` and `shift_end_at` (both ISO 8601 UTC). The optional `max_daily_dispatches` caps how many active dispatches the officer may hold at once; when omitted it defaults to 8. A freshly registered officer has `active_dispatch_count` of 0. Separately, a `Supervisor` creates each `Kennel` with a `code` and a `facility_zone`; a new kennel has `occupied_slots` of 0.

Assigning an officer to a complaint is the work of a `Dispatcher` or `Supervisor`. The assignment payload names the `complaint_id` and the `officer_id`, and defines a planned service window with `scheduled_start_at` and `scheduled_end_at`; an optional `eta_minutes` records the estimated minutes to scene. Several guards apply before the dispatch is created. The complaint must be in `status` `NEW`; a dispatch against a complaint in any other status is rejected with `ERR_COMPLAINT_NOT_DISPATCHABLE`. The new service window must not conflict with the officer's existing active dispatches: two of an officer's active dispatch windows (those in `PENDING` or `EN_ROUTE`) may not overlap, and moreover a new window that falls within a buffer of `BUFFER_MINUTES` (30) minutes of an existing active window is treated as a conflict (buffered adjacency); either situation yields `ERR_OFFICER_SCHEDULE_CONFLICT`. The officer must be on duty — the logical clock must fall within the inclusive interval from `shift_start_at` to `shift_end_at`, otherwise `ERR_OFFICER_OFF_DUTY`. Finally, the officer's `active_dispatch_count` must be strictly below `max_daily_dispatches`, otherwise `ERR_OFFICER_CAPACITY_EXCEEDED`. The window-ordering requirement that `scheduled_end_at` be strictly later than `scheduled_start_at` is enforced as request integrity (`ERR_INVALID_REQUEST`).

When all guards pass, the dispatch is created in `status` `PENDING`. Creating it advances the linked complaint from `NEW` to `DISPATCHED`, incrementing that complaint's `version` by one, and raises the assigned officer's `active_dispatch_count` by one. Dispatches may be listed and filtered by `complaint_id`, by `officer_id`, and by `status`.

### 3.3. The Dispatch Lifecycle in the Field

Once assigned, a dispatch is worked by the officer to whom it belongs. The assigned `FieldOfficer` accepts it, moving it from `PENDING` to `EN_ROUTE`; only the officer whose id matches the dispatch's `officer_id` may do so, and an attempt by anyone else is `ERR_NOT_ASSIGNED_OFFICER`. Accepting requires the dispatch to be in `PENDING`; from any other state the transition is an invalid-state error.

On arriving and finishing the call, the assigned officer clears the dispatch, which advances it from `EN_ROUTE` to `CLEARED` and requires the dispatch to be in `EN_ROUTE`. The clear payload records a `field_outcome`, one of `RESOLVED_ON_SCENE`, `ANIMAL_IMPOUNDED`, `CASE_OPENED`, `GONE_ON_ARRIVAL`, or `REFERRED`; this value is stored only at clear time. Clearing has two further effects beyond the dispatch's own state: it decrements the officer's `active_dispatch_count` by one (the dispatch has left the active set), and it advances the linked complaint from `DISPATCHED` to `RESOLVED`, incrementing the complaint's `version`. As with acceptance, only the assigned officer may clear, and a `Supervisor` is exempt from that ownership comparison.

### 3.4. Opening, Investigating, and Resolving Cases

When a call warrants formal follow-up, a `FieldOfficer` or `Supervisor` opens a `Case` from a complaint. The case records the originating `complaint_id`, the `assigned_officer_id` who will investigate, the `case_type` (`STRAY`, `BITE`, `CRUELTY`, or `DANGEROUS_DOG`), and an optional `animal_identifier` (tag, microchip, or description). A new case enters `status` `OPEN` with `risk_score` 0, `outstanding_fines_total` 0, and `public_health_flag` false. Cases may be listed and filtered by `complaint_id`, `assigned_officer_id`, `case_type`, and `status`.

Moving a case into investigation advances it from `OPEN` to `UNDER_INVESTIGATION` and requires the acting officer to be the case's assigned officer (a `Supervisor` is exempt). This transition sets the **provisional** `risk_score`. The provisional score sums a type weight — 40 for a bite case, 35 for dangerous-dog, 30 for cruelty, and 10 for stray — with a severity component equal to the linked complaint's `severity_score` multiplied by 0.5 and rounded half up to two decimal places, and then clamps the result to the range 0 through 100.

Resolution is the officer's decision, taken while the case is `UNDER_INVESTIGATION`, and carried in the `resolution` field as either `SUBSTANTIATED` or `UNFOUNDED`. Resolving as substantiated advances the case from `UNDER_INVESTIGATION` to `SUBSTANTIATED`, stamps `substantiated_at` from the logical clock, and sets the **final** `risk_score`: the same type weight plus the same half-severity component, plus a substantiation bonus of 20 points, the whole clamped to 0 through 100. Resolving as unfounded advances the case from `UNDER_INVESTIGATION` to `UNFOUNDED` and sets `risk_score` to 0; it additionally cascades to every quarantine hold on that case still in `ACTIVE`, driving each from `ACTIVE` to `VOIDED` (with the further downstream effects described in Section 3.5). Both resolutions require the acting officer to match the case's assigned officer, with the `Supervisor` exempt.

A substantiated case is not necessarily final: a `Supervisor` may reopen it, driving it from `SUBSTANTIATED` back to `UNDER_INVESTIGATION`. Reopening clears `substantiated_at` (setting it back to null) and recomputes the provisional `risk_score` exactly as the initial investigate transition does. Throughout a case's life, a `FieldOfficer` or `Supervisor` may append `InvestigationNote` records — each carrying a `note_type` (`OBSERVATION`, `EVIDENCE`, `WITNESS`, or `FOLLOWUP`) and a free-text `body` — and the system stamps each note's `case_id` from the path and captures the author's `author_role` and `author_id` from the request headers. Notes are append-only and immutable; they may be listed for a case.

### 3.5. Quarantine Holds and the Rabies-Reporting Chain

Quarantine is reserved for cases that pose a rabies exposure risk. Placing an animal under observation is permitted only when the linked case's `case_type` is `BITE` or `DANGEROUS_DOG` — any other type is `ERR_CASE_TYPE_NOT_ELIGIBLE` — and only when the case is in `UNDER_INVESTIGATION` or `SUBSTANTIATED`, otherwise `ERR_CASE_NOT_ACTIONABLE`. The hold payload names the `case_id`, the `hold_type` (`HOME_QUARANTINE` or `FACILITY_QUARANTINE`), the observation `start_at`, and an optional `animal_identifier`. On creation the hold enters `status` `ACTIVE` and the system computes its observation length: `required_days` is 10 for a bite case and 14 for a dangerous-dog case (and 10 for any other eligible input). The `release_due_at` is `start_at` advanced by exactly that many days.

A hold may be released by a `FieldOfficer` or `Supervisor`, moving it from `ACTIVE` to `RELEASED`, but only once the observation window has elapsed: the logical clock must be at or after `release_due_at`. The boundary is inclusive — a clock reading exactly `release_due_at` is releasable — and any earlier attempt is rejected with `ERR_QUARANTINE_NOT_ELAPSED`.

Two other exits from `ACTIVE` exist. A `Supervisor` may escalate a hold when the animal turns symptomatic, moving it from `ACTIVE` to `ESCALATED`. Escalation triggers a cascade: every impound on the same case still in `HELD` is euthanized (driven from `HELD` to `EUTHANIZED`), which in turn frees the kennel and escalates the case's outstanding rabies reports and flags the case for public health, as detailed in Section 3.6. Separately, the system itself voids a hold as part of unfounded-case resolution: each `ACTIVE` hold on a case resolved unfounded is driven from `ACTIVE` to `VOIDED`, and voiding cascades to every rabies report tied to that hold by `quarantine_hold_id` still in `SUBMITTED`, driving each from `SUBMITTED` to `CLEARED`.

Rabies reports carry the statutory notification to the county health department. Submitting a report is likewise restricted to cases whose `case_type` is `BITE` or `DANGEROUS_DOG` (`ERR_CASE_TYPE_NOT_ELIGIBLE`). The payload names the `case_id`, the covering `quarantine_hold_id`, the `victim_name`, the `exposure_date`, and an optional `animal_identifier`. On submission the report enters `status` `SUBMITTED`; the system stamps `submitted_at` from the logical clock, computes `deadline_at` as `exposure_date` advanced by 24 hours, and sets `is_late` to true exactly when `submitted_at` is strictly after `deadline_at`, and false otherwise. A `HealthDeptLiaison` clears a report after a negative observation, moving it from `SUBMITTED` to `CLEARED`. Reports may be listed and filtered by `case_id`, `quarantine_hold_id`, and `status`. Beyond the liaison's manual clear, a report may reach `CLEARED` through the quarantine-void cascade above, or reach `ESCALATED` through the euthanasia cascade below.

### 3.6. Impound, Kennel Occupancy, and Boarding Fees

Impounding an animal is permitted only when the linked case is in `UNDER_INVESTIGATION` or `SUBSTANTIATED`; otherwise the request is `ERR_CASE_NOT_ACTIONABLE`. The payload names the `case_id`, the `kennel_id`, the occupancy window bounded by `impounded_at` and `hold_until`, the optional `animal_identifier`, and an optional `licensed` flag (defaulting to false). It must also carry `expected_case_version` for the optimistic-concurrency check of Section 2.8. The kennel must have room in a scheduling sense: within one kennel, the closed occupancy interval from `impounded_at` to `hold_until` of a new impound may not overlap that of any impound already in `HELD` there, though intervals that merely touch at a shared endpoint are permitted; a genuine overlap is `ERR_KENNEL_OCCUPIED`. The requirement that `hold_until` be strictly later than `impounded_at` is enforced as request integrity (`ERR_INVALID_REQUEST`).

A successful impound is created in `status` `HELD` with `boarding_fee` initialized to 0 (the fee is computed only at release). Recording it raises the kennel's `occupied_slots` by one and increments the parent case's `version` by one.

Releasing an impound is performed by a `FieldOfficer` or `Supervisor` and carries a `disposition` naming the terminal state: `REDEEMED`, `ADOPTED`, `RELEASED`, or `EUTHANIZED`. Any of these drives the impound from `HELD` to the corresponding terminal status, lowers the kennel's `occupied_slots` by one, and computes the owner-facing `boarding_fee`. The fee is built from three taxed line items. First, the number of boarding days is the elapsed occupancy — the seconds between `impounded_at` and the release logical-clock time, divided by 86,400 seconds per day — rounded up to the next whole day, with a floor of one day (so any occupancy bills at least one day). The daily line is that day count multiplied by a daily rate of 12.50; the intake line is a flat 15.00; and the surcharge line is 22.75 when the animal is not `licensed` and 0 when it is. Each line is then grossed up by a tax rate of 0.075 — that is, multiplied by 1.075 — and **each grossed-up line is rounded half up to two decimal places individually**; the `boarding_fee` is the sum of those three separately-rounded amounts. The per-line rounding is mandatory and is not equivalent to rounding a single combined total.

Euthanasia deserves special note because it arises two ways with different effects. When an officer releases an impound with disposition `EUTHANIZED`, it follows the ordinary release path above: the kennel is freed and the boarding fee is computed, with no further cascade. When instead an impound is euthanized by the system as part of a quarantine escalation (Section 3.5), it is likewise driven from `HELD` to `EUTHANIZED` and the kennel's `occupied_slots` is lowered by one, but this cascade additionally escalates every rabies report on the same case (matched by `case_id`) still in `SUBMITTED`, driving each from `SUBMITTED` to `ESCALATED`. Each such rabies escalation is itself consequential: it sets the linked case's `public_health_flag` to true and adds 20 points to the case's `risk_score`, clamped to the range 0 through 100. Impounds may be listed and filtered by `case_id`, `kennel_id`, and `status`.

### 3.7. Citations, Fines, and Court Referral

A citation is issued against a case by a `FieldOfficer` or `Supervisor`, and only while the case is in `UNDER_INVESTIGATION` or `SUBSTANTIATED` (otherwise `ERR_CASE_NOT_ACTIONABLE`). The payload names the `case_id`, the `violation_code` (`UNLICENSED`, `LEASH`, `DANGEROUS`, `BITE`, or `CRUELTY`), the `issued_to_name`, and a stable `issued_to_ref` that identifies the cited party across citations so repeat offenders can be detected.

On issuance the system computes the fine. The `base_fine` is fixed by `violation_code`: 50 for unlicensed, 75 for leash, 250 for dangerous, 300 for bite, and 500 for cruelty. It then counts this party's prior resolved citations — those sharing the same `issued_to_ref` whose `status` is `PAID` or `COURT_REFERRED`, counted at issue time with no time window. If there are no such priors, the multiplier is 1.0 and the `fine_amount` equals the base fine (the standard, first-offense case). If there is at least one prior, the party is a repeat offender: the multiplier is 1 plus 0.5 times the number of priors, where the prior count is capped at 3 for this purpose — so one prior yields 1.5×, two priors 2.0×, and three or more priors 2.5×. The `fine_amount` is the base fine times that multiplier, rounded half up to two decimal places, and in the repeat case is strictly greater than the base fine. The citation is created in `status` `ISSUED`; the system stamps `issued_at` from the logical clock and sets `due_at` to `issued_at` advanced by 30 days. Issuing raises the case's `outstanding_fines_total` by the `fine_amount`.

A citation leaves `ISSUED` two ways, and both require it to still be in `ISSUED` — a pay or refer attempt on an already-resolved citation is `ERR_CITATION_ALREADY_RESOLVED`. A `Dispatcher` or `Supervisor` records payment, moving the citation from `ISSUED` to `PAID`; a `Supervisor` refers an unpaid citation to court, moving it from `ISSUED` to `COURT_REFERRED`. Either exit lowers the case's `outstanding_fines_total` by that citation's `fine_amount`. Citations may be listed and filtered by `case_id` and `status`.

### 3.8. Case Closure and Operational Reporting

Closing a case is a `Supervisor`-only act and the terminal step in a case's life. A case may be closed only from `SUBSTANTIATED` or `UNFOUNDED`. Three obligations must be discharged first, and each has its own rejection. The case may not close while any quarantine hold on it is still `ACTIVE` (`ERR_ACTIVE_QUARANTINE_HOLD`); it may not close while any impound on it is still `HELD` (`ERR_ACTIVE_IMPOUND`); and it may not close while any citation on it remains in `ISSUED` (`ERR_OUTSTANDING_CITATIONS`). Per the validation ordering of Section 2.6, the active-hold and held-impound safety checks are evaluated ahead of the outstanding-citation fiscal check. When all three are satisfied, the case advances to `CLOSED`, and the closure cascades to the linked complaint: a complaint in `DISPATCHED` or `RESOLVED` is driven to `CLOSED`, incrementing that complaint's `version`.

For situational awareness, a `Dispatcher` or `Supervisor` may read an operational dashboard that aggregates the current state of the system. It reports `total_complaints` as the count of all complaints regardless of status; `open_cases` as the count of cases whose `status` is `OPEN` or `UNDER_INVESTIGATION`; `active_quarantine_holds` as the count of holds whose `status` is `ACTIVE`; and `total_outstanding_fines` as the sum of `fine_amount` across all citations still in `ISSUED`, rounded half up to two decimal places. When nothing matches — including against an empty database — the three counts return as the integer 0 and the fines total returns as 0.00.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that fetch, list, or drive a state transition on an existing resource return `200 OK`. Request and response bodies are not repeated here — reconstruct them from the workflow narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/dispatch/complaints` | Intake a complaint; compute severity and priority | Dispatcher, Supervisor |
| GET | `/dispatch/complaints/{id}` | Fetch a complaint | Dispatcher, FieldOfficer, Supervisor, HealthDeptLiaison |
| POST | `/dispatch/officers` | Register a field officer | Supervisor |
| GET | `/dispatch/officers/{id}` | Fetch an officer | Dispatcher, FieldOfficer, Supervisor |
| POST | `/dispatch/kennels` | Create a kennel/run | Supervisor |
| GET | `/dispatch/kennels/{id}` | Fetch a kennel | FieldOfficer, Supervisor |
| POST | `/dispatch/dispatches` | Assign an officer to a complaint | Dispatcher, Supervisor |
| GET | `/dispatch/dispatches/{id}` | Fetch a dispatch | Dispatcher, FieldOfficer, Supervisor |
| GET | `/dispatch/dispatches` | List/filter dispatches | Dispatcher, FieldOfficer, Supervisor |
| POST | `/dispatch/dispatches/{id}/accept` | Assigned officer goes en route | FieldOfficer |
| POST | `/dispatch/dispatches/{id}/clear` | Officer clears the scene with an outcome | FieldOfficer |
| POST | `/dispatch/cases` | Open an investigation case | FieldOfficer, Supervisor |
| GET | `/dispatch/cases/{id}` | Fetch a case | Dispatcher, FieldOfficer, Supervisor, HealthDeptLiaison |
| GET | `/dispatch/cases` | List/filter cases | Dispatcher, FieldOfficer, Supervisor |
| POST | `/dispatch/cases/{id}/investigate` | Move a case into investigation (or reopen) | FieldOfficer, Supervisor |
| POST | `/dispatch/cases/{id}/resolve` | Resolve a case substantiated or unfounded | FieldOfficer, Supervisor |
| POST | `/dispatch/cases/{id}/close` | Close a resolved case | Supervisor |
| POST | `/dispatch/cases/{id}/notes` | Append an investigation note | FieldOfficer, Supervisor |
| GET | `/dispatch/cases/{id}/notes` | List investigation notes for a case | FieldOfficer, Supervisor, HealthDeptLiaison |
| POST | `/dispatch/quarantine-holds` | Place an animal under quarantine observation | FieldOfficer, Supervisor |
| GET | `/dispatch/quarantine-holds/{id}` | Fetch a quarantine hold | FieldOfficer, Supervisor, HealthDeptLiaison |
| GET | `/dispatch/quarantine-holds` | List/filter quarantine holds | FieldOfficer, Supervisor, HealthDeptLiaison |
| POST | `/dispatch/quarantine-holds/{id}/release` | Release a hold after the window elapses | FieldOfficer, Supervisor |
| POST | `/dispatch/quarantine-holds/{id}/escalate` | Escalate a symptomatic animal | Supervisor |
| POST | `/dispatch/impounds` | Impound an animal into a kennel | FieldOfficer, Supervisor |
| GET | `/dispatch/impounds/{id}` | Fetch an impound | FieldOfficer, Supervisor |
| GET | `/dispatch/impounds` | List/filter impounds | FieldOfficer, Supervisor |
| POST | `/dispatch/impounds/{id}/release` | Release an impound with a disposition | FieldOfficer, Supervisor |
| POST | `/dispatch/citations` | Issue a citation with fine escalation | FieldOfficer, Supervisor |
| GET | `/dispatch/citations/{id}` | Fetch a citation | FieldOfficer, Supervisor |
| GET | `/dispatch/citations` | List/filter citations | FieldOfficer, Supervisor |
| POST | `/dispatch/citations/{id}/pay` | Record payment of a citation | Dispatcher, Supervisor |
| POST | `/dispatch/citations/{id}/refer-court` | Refer an unpaid citation to court | Supervisor |
| POST | `/dispatch/rabies-reports` | Submit a rabies report to the health dept | FieldOfficer, Supervisor |
| GET | `/dispatch/rabies-reports/{id}` | Fetch a rabies report | FieldOfficer, Supervisor, HealthDeptLiaison |
| GET | `/dispatch/rabies-reports` | List/filter rabies reports | FieldOfficer, Supervisor, HealthDeptLiaison |
| POST | `/dispatch/rabies-reports/{id}/clear` | Health dept clears a rabies report | HealthDeptLiaison |
| GET | `/dispatch/reports/summary` | Aggregate operational dashboard | Dispatcher, Supervisor |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Supervisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_ASSIGNED_OFFICER` | 403 |
| `ERR_COMPLAINT_NOT_FOUND` | 404 |
| `ERR_OFFICER_NOT_FOUND` | 404 |
| `ERR_KENNEL_NOT_FOUND` | 404 |
| `ERR_DISPATCH_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_QUARANTINE_HOLD_NOT_FOUND` | 404 |
| `ERR_IMPOUND_NOT_FOUND` | 404 |
| `ERR_CITATION_NOT_FOUND` | 404 |
| `ERR_RABIES_REPORT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_COMPLAINT_NOT_DISPATCHABLE` | 409 |
| `ERR_CITATION_ALREADY_RESOLVED` | 409 |
| `ERR_CASE_TYPE_NOT_ELIGIBLE` | 409 |
| `ERR_CASE_NOT_ACTIONABLE` | 409 |
| `ERR_OFFICER_OFF_DUTY` | 409 |
| `ERR_OFFICER_SCHEDULE_CONFLICT` | 409 |
| `ERR_OFFICER_CAPACITY_EXCEEDED` | 409 |
| `ERR_KENNEL_OCCUPIED` | 409 |
| `ERR_QUARANTINE_NOT_ELAPSED` | 409 |
| `ERR_ACTIVE_QUARANTINE_HOLD` | 409 |
| `ERR_ACTIVE_IMPOUND` | 409 |
| `ERR_OUTSTANDING_CITATIONS` | 409 |
| `ERR_STALE_CASE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 422 |
