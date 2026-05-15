# School Choice Lottery API — Product Requirements Document

## 1. Introduction

Public school districts increasingly run choice and magnet enrollment programs that allow families to apply for seats outside the neighborhood school they would otherwise be assigned. These systems must balance several often-competing goals: predictable registration windows so families can plan, sibling continuity so that brothers and sisters can attend the same school, equity weighting so that economically disadvantaged students are not crowded out by better-resourced families, and the structured ability to admit students from neighboring districts when their home district has explicitly authorized such transfers.

This API exposes a single backend mounted under `/enrollment` that manages the full lifecycle of school choice enrollment: registering districts and schools, opening grade-level seat pools, accepting applications during a fixed window, running a deterministic weighted lottery once the window closes, issuing offers, propagating sibling-anchor priority across siblings within a family, processing accept/decline/withdraw responses, and backfilling vacated seats from the waitlist. A separate inter-district transfer authorization flow gates applications that cross district boundaries. Every state-changing operation is auditable, every numeric outcome is reproducible from a deterministic seed, and every action is gated by role-based access rules that reflect the operational reality of school districts: a district administrator governs the schools, programs, and transfer approvals inside their own district; a family-side user acts on behalf of their own household; a platform operator manages districts and the test clock.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, conventions, and contracts that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifies the acting principal, and `X-User-Role` declares their operational capacity. If either header is absent the request is rejected with `ERR_AUTH_MISSING`. The system recognizes exactly three roles, and any value of `X-User-Role` outside this set is rejected with `ERR_AUTH_INVALID_ROLE`:

- `SystemOperator` — a test-time platform operator who manages districts, advances the simulated clock, and audits lottery runs. When `X-User-Role` is `SystemOperator`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `DistrictAdmin` — administrator of a specific district. When `X-User-Role` is `DistrictAdmin`, `X-User-ID` is the `id` of the acting `District`; ownership checks on any resource that references a `District` (a school, a program, a transfer-request target) compare the resource's district foreign-key to `X-User-ID`.
- `FamilyUser` — an acting member of a household. When `X-User-Role` is `FamilyUser`, `X-User-ID` is the `id` of the acting `Family`; ownership checks on any resource that references a `Family` (a student, an application via its student, a transfer-request via its application) compare the resource's family foreign-key to `X-User-ID`.

Once headers are present and the role string is valid, the request is checked against the per-endpoint authorization table summarized in §4. If the role is recognized but not authorized for that endpoint, the request is rejected with `ERR_FORBIDDEN`. Any body schema, range, or format violation not covered by one of the more specific errors listed in §5 is rejected with the generic `ERR_VALIDATION`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` query parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their `created_at` timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Primary persisted entities — `District`, `School`, `Program`, `Family`, `Student`, `Application`, and `TransferRequest` — carry a uniform set of system-managed fields:

- `id` (string): a unique, server-minted UUID without any type prefix.
- `created_at` (string): ISO 8601 UTC timestamp with three fractional digits, fixed at the moment the resource is first stored.
- `updated_at` (string): ISO 8601 UTC timestamp updated whenever any property of the resource changes, including derived properties such as `Program.seats_offered`, `Program.seats_accepted`, `Program.window_status`, `Application.status`, `Application.waitlist_position`, `Application.offer_expires_at`, `Application.priority_category`, `Application.lottery_weight`, `Application.lottery_score`, `Family.head_household_application_id`, `TransferRequest.status`, and `TransferRequest.capacity_units_held`.
- `version` (integer): a system-managed integer that increments on every mutation of the resource and is used for optimistic concurrency control.

A small set of audit-and-singleton entities — `LotteryRun`, `WaitlistEvent`, and the singleton `Clock` (whose `id` is the literal string `clock`) — are immutable once written or are server-controlled state, and therefore carry only `id` and (where applicable) `created_at`. Neither `updated_at` nor `version` is present on those entities.

### 2.5. Nested Resource Retrieval and Existence Checks

Every endpoint that takes a path-parameter identifier validates those identifiers in strict left-to-right order. The first identifier that does not resolve to an existing row causes the request to be rejected with `ERR_NOT_FOUND` and a 404 status; later identifiers in the same path are not consulted. Foreign-key identifiers passed inside a request body — for example the `district_id` on a school payload, the `school_id` on a program payload, the `student_id` and `program_id` on an application payload, or the `application_id` and `target_district_id` on a transfer-request payload — are validated after path parameters; an unresolvable body foreign key is rejected with `ERR_FK_NOT_FOUND` and a 422 status.

### 2.6. Optimistic Concurrency Control

Endpoints that modify an existing resource accept an optional `version` field in the request body. If the client supplies `version` and the value does not match the server's current version of the target resource, the request is rejected with `ERR_VERSION_MISMATCH` and a 409 status. If `version` is omitted, the server applies the mutation without an OCC check. This convention applies uniformly to every PATCH endpoint and to every state-transition endpoint (submit, accept, decline, withdraw, approve, deny, revoke).

### 2.7. Numeric Precision and Rounding

The system uses two distinct precision regimes for derived numeric fields, applied with the "round half up" rule in every case:

- `Application.lottery_weight` is rounded to four decimal places. The intermediate poverty-multiplier computation explicitly scales `Family.poverty_index_score` and `District.poverty_index_threshold` to integers by multiplying by 100 and rounding to the nearest integer before any comparison, so that decile boundaries are not perturbed by floating-point drift. Once both values are integers in the range 0 to 100, the comparison and the floor-division both run on integers.
- `Application.lottery_score` is rounded to six decimal places. The underlying uniform draw must be in the half-open interval greater than 0 and less than or equal to 1; if the seeded draw yields exactly 0, it is redrawn.

District-level inter-district capacity arithmetic and all seat counters are exact integer aggregates with no rounding.

### 2.8. Validation Priority Ordering

When multiple validation rules could fire on the same request, they are evaluated in a fixed priority order so that the first failing rule determines the response. The order, from highest priority to lowest, is: authentication header presence (`ERR_AUTH_MISSING`), recognized role (`ERR_AUTH_INVALID_ROLE`), RBAC authorization (`ERR_FORBIDDEN`), path-parameter existence (`ERR_NOT_FOUND`), body foreign-key existence (`ERR_FK_NOT_FOUND`), then domain-state and business rules.

Two non-obvious orderings deserve explicit mention. First, on the lottery draw operation, the rule that requires the program to be in `CLOSED` is evaluated strictly before the rule that distinguishes the already-drawn case: any non-`CLOSED` status that is not yet `LOTTERY_DRAWN` or `BACKFILL` (i.e., `SCHEDULED` or `OPEN`) yields `ERR_LOTTERY_NOT_READY`, while `LOTTERY_DRAWN` or `BACKFILL` yields `ERR_LOTTERY_ALREADY_DRAWN`. Second, on accept and decline, the state check (the application must be `OFFERED`) is evaluated before the offer-expiry temporal check: if the offer's `offer_expires_at` has passed but the clock-advance sweep has not yet promoted the row to `EXPIRED`, the request fails with `ERR_OFFER_EXPIRED`; once the sweep has run, the same request fails earlier with `ERR_INVALID_STATE_FOR_TRANSITION` because the row is no longer `OFFERED`. Third, on transfer-request approval, the district-permission check (the district must permit inter-district transfers) is evaluated before the capacity check, so a district that has both refused transfers and exhausted capacity yields `ERR_DISTRICT_NO_TRANSFERS`, not `ERR_DISTRICT_CAPACITY_EXCEEDED`.

### 2.9. Hierarchical Consistency and Cascades

Several operations mutate more than one entity. When an application accepts an offer, the program's `seats_accepted` increases by one, the family's `head_household_application_id` is established if it was previously null, and every other `OFFERED` application by the same student in any program transitions to `WITHDRAWN` — each such sibling-program withdrawal in turn frees a seat in that program and runs the waitlist-backfill rule there. When an application declines, expires, or is withdrawn from `ACCEPTED`, the program's `seats_offered` decreases by one and the same waitlist-backfill rule runs on that program. When a transfer request is revoked while its linked application is in `SUBMITTED` or `WAITLISTED`, that application transitions to `WITHDRAWN` and the affected program's waitlist positions are recomputed. Every such cascade mutates each affected resource independently, updating its `updated_at` and incrementing its `version`.

### 2.10. Determinism and the Test Clock

The system is fully deterministic by construction. The simulated wall clock is a singleton resource: the `Clock` row has `id` equal to `clock` and a `now` field representing the current logical time. Production-style time advancement is replaced by an operator-driven clock-advance capability that accepts a target instant in the body field `target_now`; when invoked, the system sweeps the database for time-driven transitions whose trigger instants are at or earlier than the new clock value. Programs whose `registration_open_at` has been reached transition from `SCHEDULED` to `OPEN`; programs whose `registration_close_at` has been reached transition from `OPEN` to `CLOSED` and, as a side effect of that close, any `Application` still in `DRAFT` under such a program is auto-transitioned to `WITHDRAWN`. Applications whose `offer_expires_at` has passed are auto-transitioned from `OFFERED` to `EXPIRED`, and each such expiry runs the waitlist-backfill rule on its program. The lottery itself uses a per-program seed supplied as `lottery_seed`; the random draw for each application is derived by concatenating the program's `lottery_seed`, a colon, and the application's `id`, hashing the result with SHA-256, taking the first 8 bytes as a big-endian unsigned integer, and dividing by 2 to the power of 64.

### 2.11. Concurrency Guarantees

Four distinct race conditions are explicitly serialized. When two accept calls arrive on two different `OFFERED` applications by the same student simultaneously, exactly one application reaches `ACCEPTED`; serialization is first-writer-wins on `Application.status` keyed by `student_id`, and the loser sees `ERR_STUDENT_ALREADY_ACCEPTED` (the cascade from the winner has already withdrawn the loser's other offers by the time the loser's precondition is rechecked). When two accept calls race for the last open seat in a program — one on an originally-offered application, the other on a waitlisted application that has just been promoted by a backfill — at most `Program.seats_total` applications may simultaneously hold status `OFFERED` or `ACCEPTED`, and the loser sees `ERR_SEAT_NOT_AVAILABLE`; serialization is first-writer-wins on `Program.seats_offered`, with the seat-availability check re-evaluated inside the transaction. When two lottery draws are invoked on the same program at the same time, the lottery runs exactly once per program lifecycle; the loser observes the program already in `LOTTERY_DRAWN` or `BACKFILL` and is rejected with `ERR_LOTTERY_ALREADY_DRAWN`; serialization is first-writer-wins on the `Program.window_status` transition out of `CLOSED`. When two transfer-request approvals race against the same target district's last available inter-district capacity unit, the total number of `APPROVED` `TransferRequest` rows for that district must not exceed the district's inter-district capacity floor; the loser sees `ERR_DISTRICT_CAPACITY_EXCEEDED`; serialization is first-writer-wins on the count of `APPROVED` transfer requests for that target district.

## 3. Business Logic & Workflows

### 3.1. Foundational Setup: Districts, Schools, and Programs

A `SystemOperator` brings the catalog into existence by creating one or more districts. Each district carries a human-readable `name` (unique, 1 to 120 characters) and a two-letter US `state_code` matching the regular expression of two uppercase letters. Two policy fields on the district drive the rest of the workflow: `accepts_inter_district_transfers`, a boolean that defaults to false, and `poverty_index_threshold`, a decimal in the closed interval from 0.00 to 1.00 with at most two decimal places of precision, defaulting to 0.50. The threshold is the decile cut-off above which a family is treated as disadvantaged for the lottery weighting purposes described in §3.4. Districts may have these two policy fields adjusted later by a `SystemOperator`.

A `DistrictAdmin` whose `X-User-ID` matches a district's `id` populates that district with schools. A school is created with a `district_id` (which must equal the admin's `X-User-ID`), a `name` (unique within the district), a `school_type` enum with values `NEIGHBORHOOD`, `MAGNET`, or `CHARTER`, and a `grade_levels_offered` array — a non-empty subset of the integers from 0 (kindergarten) through 12, sorted in ascending order.

Inside each school the same administrator defines one or more grade-level programs — the actual seat pools that families apply to. A program is bound to its parent via `school_id` and is created with a single `grade_level` (an integer from 0 through 12), an `academic_year` (a four-digit year whose value must be at least 2025), a positive integer `seats_total`, a registration window defined by `registration_open_at` and `registration_close_at` (both ISO 8601 UTC instants, with the close instant required to be strictly later than the open instant), and an optional `lottery_seed`. The seed is a string of 1 to 64 characters that must be set before the lottery is drawn; it may be left unset at creation and assigned later. The program's `seats_offered` and `seats_accepted` derived counters both start at 0, and its `window_status` begins at `SCHEDULED`. A program creation is rejected with `ERR_GRADE_NOT_OFFERED` if `grade_level` does not appear in the parent school's `grade_levels_offered`. Existing programs may be updated by a `DistrictAdmin` whose district owns the school: `seats_total`, `lottery_seed`, and `registration_close_at` are all editable while `window_status` is one of `SCHEDULED`, `OPEN`, or `CLOSED`. A reduction of `seats_total` to a value below the program's current `seats_accepted` is rejected with `ERR_SEATS_BELOW_COMMITTED`; this same rule also fires at creation time if a non-positive integer is supplied.

### 3.2. Family Registration and the Sibling Anchor

A family registers itself (or is registered by a `SystemOperator`) by supplying a `residency_district_id` (a foreign key to a `District`) and a `poverty_index_score` — a decimal in the closed interval from 0.00 to 1.00 representing the family's disadvantage rating, where a higher value means more disadvantaged. The family's `head_household_application_id` derived field starts null. It is set to the `id` of the first application by any student in the household that reaches `ACCEPTED`, and from that point forward, subsequent applications submitted by sibling students are eligible for the sibling-anchor priority described in §3.4 — but only when the anchor's program is in the same district as the new application's program (the anchor's school's `district_id` must equal the new application's program's school's `district_id`). When the anchor application later leaves `ACCEPTED` (either by withdrawal or, more rarely, by a downstream cascade), the anchor is recomputed: it becomes the next-by-`created_at`-ascending `ACCEPTED` application of any student in the family, or null if none remains.

A `FamilyUser` whose `X-User-ID` equals a family's `id` adds one or more students to that family by providing the parent `family_id` and the student's `grade_level_next_year` (an integer in the closed range 0 through 12). An optional `has_iep` boolean flag — indicating an Individualized Education Plan, defaulting to false — is reserved for downstream tie-breaks and is recorded on the student but does not otherwise alter the lottery ordering described in §3.4.

### 3.3. Inter-District Transfer Authorization

When a family wishes to apply for a program whose school sits in a district other than the family's `residency_district_id`, the application must be backed by an approved transfer authorization before it can be submitted. A `FamilyUser` creates a transfer request by supplying the `application_id` it relates to and the `target_district_id` — which must equal the program's school's `district_id`. The transfer request starts in `PENDING` and carries a derived `capacity_units_held` counter that is 0 in every status other than `APPROVED`.

A `DistrictAdmin` of the target district (i.e., whose `X-User-ID` equals the request's `target_district_id`) acts on the request. Approval is rejected with `ERR_DISTRICT_NO_TRANSFERS` if the target district has `accepts_inter_district_transfers` set to false. If transfers are permitted, the system computes the district's inter-district capacity: it sums, across all programs whose school sits in the target district and whose `school_type` is either `MAGNET` or `CHARTER` and whose `window_status` is one of `SCHEDULED`, `OPEN`, `CLOSED`, `LOTTERY_DRAWN`, or `BACKFILL`, the value of `seats_total` minus `seats_accepted` for each such program (`NEIGHBORHOOD` schools do not contribute to inter-district capacity). It then counts the number of transfer requests that currently target this district and are in `APPROVED`. If granting this approval would push that count strictly above the computed capacity — that is, if the current `APPROVED` count plus one would exceed the capacity — the approval is rejected with `ERR_DISTRICT_CAPACITY_EXCEEDED`. Otherwise the transfer request transitions from `PENDING` to `APPROVED` and its `capacity_units_held` is set to 1.

The same administrator may deny a pending request, transitioning `PENDING` to `DENIED`; if the linked application is still in `DRAFT` and crosses district lines, a later attempt to submit it will fail with `ERR_TRANSFER_NOT_APPROVED`. The administrator may also revoke an already-approved request, but only while the linked application is in `DRAFT`, `SUBMITTED`, or `WAITLISTED`. Revocation transitions `APPROVED` to `REVOKED`, sets `capacity_units_held` back to 0, and — when the linked application was in `SUBMITTED` or `WAITLISTED` — cascades that application to `WITHDRAWN` and recomputes the waitlist positions on the affected program.

### 3.4. Application Drafting, Priority Classification, and Lottery Weight

A `FamilyUser` drafts an application on behalf of one of their students by supplying the `student_id`, the target `program_id`, and a `choice_rank` integer in the closed interval from 1 to 5, where 1 represents the family's top choice. The application starts in `DRAFT`. Within the set of applications by a single student that are still in `DRAFT` or `SUBMITTED`, `choice_rank` values must be unique — a second application by the same student at the same rank is rejected with `ERR_DUPLICATE_CHOICE_RANK`. The total number of `DRAFT` or `SUBMITTED` applications a single student may hold simultaneously must not exceed 5; a sixth such application is rejected with `ERR_TOO_MANY_CHOICES`. The student's `grade_level_next_year` must equal the program's `grade_level`, otherwise the request is rejected with `ERR_GRADE_MISMATCH`; this rule fires both at creation and at submit.

Submission transitions the application from `DRAFT` to `SUBMITTED` and is the operation that locks in the lottery inputs. Submission requires the program's `window_status` to be `OPEN`; outside of that window the request is rejected with `ERR_REGISTRATION_WINDOW_CLOSED`. If the application crosses district lines — the program's school's `district_id` is different from the family's `residency_district_id` — a transfer request linking this application must currently be in `APPROVED`; if not, the submission is rejected with `ERR_TRANSFER_NOT_APPROVED`.

At the moment `SUBMITTED` is set, two derived fields are computed on the application: `priority_category` and `lottery_weight`. Both are snapshot calculations; subsequent edits to the family's `poverty_index_score` or the district's `poverty_index_threshold` do not retroactively change either value.

The `priority_category` enum classifies the application into one of five buckets in the following decision order. First, if the family currently has a non-null `head_household_application_id` whose program's school sits in the same district as this program's school, and the new application does not cross district lines (the program's school's `district_id` equals the family's `residency_district_id`), the category is `SIBLING_IN_DISTRICT`. Otherwise, if the application does not cross district lines and the family's `poverty_index_score` is at least the district's `poverty_index_threshold`, the category is `IN_DISTRICT_DISADVANTAGED`. Otherwise, if the application does not cross district lines, the category is `IN_DISTRICT_STANDARD`. Otherwise, if the application crosses district lines and the family's `poverty_index_score` is at least the district's `poverty_index_threshold`, the category is `INTER_DISTRICT_DISADVANTAGED`. In every other case the category is `INTER_DISTRICT_STANDARD`. Sibling priority strictly dominates the poverty multiplier in this classifier: a `SIBLING_IN_DISTRICT` application is so categorized even when the family is non-disadvantaged.

The `lottery_weight` calculation begins from a tiered base weight indexed by `priority_category`. `SIBLING_IN_DISTRICT` receives a base weight of 4.0; `IN_DISTRICT_DISADVANTAGED` receives 3.0; `IN_DISTRICT_STANDARD` receives 2.0; `INTER_DISTRICT_DISADVANTAGED` receives 1.5; `INTER_DISTRICT_STANDARD` receives 1.0. The order of those values is itself part of the policy: inter-district disadvantaged ranks below in-district standard. A poverty multiplier is then applied. Both `Family.poverty_index_score` and `District.poverty_index_threshold` are scaled to integers by multiplying by 100 and rounding to the nearest integer; call those integers the family's scaled score and the district's scaled threshold. If and only if the family's scaled score is strictly greater than the district's scaled threshold, the number of completed deciles by which the family exceeds the threshold is computed by integer floor-division of their difference by 10; the multiplier is then 1.0 plus 0.10 times that decile count. If the family's scaled score does not strictly exceed the threshold, the multiplier is 1.0. A choice-rank decay factor is then applied: the application's `choice_rank` minus 1 is the exponent applied to the constant 0.85, so a first-choice application receives a decay factor of 1.0, a second choice receives 0.85, a third 0.7225, and so on. The raw weight is the base weight multiplied by the poverty multiplier multiplied by the decay factor, and the persisted `lottery_weight` is that raw value rounded half-up to four decimal places.

### 3.5. The Lottery Draw

Once a program's registration window has closed — that is, the operator-driven clock-advance sweep has transitioned the program from `OPEN` to `CLOSED` after `Clock.now` reached the program's `registration_close_at` — a `DistrictAdmin` whose district owns the school may run the lottery for that program. The draw requires the program's `window_status` to be exactly `CLOSED`; a `SCHEDULED` or `OPEN` program is rejected with `ERR_LOTTERY_NOT_READY`, and a `LOTTERY_DRAWN` or `BACKFILL` program is rejected with `ERR_LOTTERY_ALREADY_DRAWN`. The program's `lottery_seed` must be set and non-empty, or the draw is rejected with `ERR_LOTTERY_SEED_MISSING`. At least one application in this program must currently be in `SUBMITTED` for the draw to proceed.

For every `SUBMITTED` application in the program, the system computes a uniform random draw in the interval greater than 0 and less than or equal to 1, deterministically seeded from the program's `lottery_seed` and the application's `id` as described in §2.10. The application's `lottery_score` is then set to its `lottery_weight` multiplied by the negative natural logarithm of that uniform draw, with the result rounded half-up to six decimal places. Higher scores win. This is the inverse-CDF exponential sampling weighted by `lottery_weight`, equivalent to weighted reservoir sampling.

Applications are then sorted by four keys, in order: first by `priority_category` rank ascending, where `SIBLING_IN_DISTRICT` is rank 1, `IN_DISTRICT_DISADVANTAGED` is rank 2, `IN_DISTRICT_STANDARD` is rank 3, `INTER_DISTRICT_DISADVANTAGED` is rank 4, and `INTER_DISTRICT_STANDARD` is rank 5; then by `lottery_score` descending; then by the application's `created_at` ascending; and finally by the application's `id` ascending as the deterministic final tie-break. Priority dominates: a `SIBLING_IN_DISTRICT` application with a low `lottery_score` still beats an `IN_DISTRICT_STANDARD` application with a high `lottery_score`. Within a single `priority_category` bucket, ordering is by `lottery_score` descending alone.

The top `seats_total` applications in this ordering transition from `SUBMITTED` to `OFFERED`. Each such offer sets `offer_expires_at` to `Clock.now` plus 168 hours (the offer-response window of 7 days) and increments the program's `seats_offered` by one. The remaining applications transition from `SUBMITTED` to `WAITLISTED` with their `waitlist_position` assigned 1, 2, 3, and so on in the same ordering — that is, `waitlist_position` 1 goes to the highest-ranked non-offered application. The program transitions from `CLOSED` to `LOTTERY_DRAWN`. The system writes a `LotteryRun` audit record containing this program's `program_id`, a snapshot of the seed in `seed_used`, the `drawn_at` instant equal to `Clock.now`, the `applications_ranked` array (an ordered list of `{application_id, lottery_score, rank}` entries with rank 1 corresponding to the highest score), and `offers_issued_count` set to the number of offers issued (which excludes the waitlisted entries).

### 3.6. Responding to an Offer

A family that has received an offer responds by accepting, declining, or letting the offer expire. Acceptance transitions the application from `OFFERED` to `ACCEPTED` and requires both that the application's current status be `OFFERED` and that `Clock.now` be strictly earlier than the application's `offer_expires_at`. A request issued after expiry but before the clock-advance sweep has had a chance to run is rejected with `ERR_OFFER_EXPIRED`; once the sweep has promoted the row to `EXPIRED`, the same request is rejected with `ERR_INVALID_STATE_FOR_TRANSITION`. On acceptance the program's `seats_accepted` increases by one. If the family's `head_household_application_id` is currently null, this application's `id` is recorded as the new anchor — establishing the sibling priority that subsequent same-district applications by siblings can rely upon. The cascade then runs: every other application by the same student that is currently in `OFFERED` (in any other program) transitions to `WITHDRAWN`, and each such withdrawal in turn decrements that program's `seats_offered` and triggers the waitlist-backfill rule on that program. The cascade depth is therefore three: accept at depth one, sibling-program withdrawal at depth two, and the sibling-program's backfill promotion at depth three.

Decline transitions the application from `OFFERED` to `DECLINED`, decrements the program's `seats_offered` by one, and runs the waitlist-backfill rule on the same program. Backfill cascade depth is two: a decline at depth one promotes the next student's application to `OFFERED` at depth two; if that next student already has an `OFFERED` application in a different program, no further auto-action takes place at depth three (each student may hold multiple offers until they accept one).

Expiry is the system-driven counterpart of decline. When the operator-driven clock advance sweep observes that an application's `offer_expires_at` has been reached, the application transitions from `OFFERED` to `EXPIRED`; `seats_offered` decreases by one and the same waitlist-backfill rule runs.

A family may also withdraw an application that has already reached `ACCEPTED`, but only while `Clock.now` is strictly earlier than the lottery's `drawn_at` plus the withdraw-grace window of 14 days; an attempt past that grace deadline is rejected with `ERR_WITHDRAW_GRACE_PASSED`. Successful withdrawal transitions the application from `ACCEPTED` to `WITHDRAWN`, decrements both `seats_accepted` and `seats_offered` by one, and runs the waitlist-backfill rule on this program. If the withdrawn application was the family's `head_household_application_id`, the anchor is recomputed by selecting the next `ACCEPTED` application of any student in this family ordered by `created_at` ascending, or null if none remains.

### 3.7. The Waitlist and Backfill

Once a program has entered `LOTTERY_DRAWN`, the first transition of any application out of `OFFERED` by decline, expiry, or by the cascade from an accept in another program — or any withdrawal from `ACCEPTED` — moves the program into `BACKFILL`. From that moment, the program is in the backfill regime: every subsequent freed offer triggers the waitlist-backfill rule.

The rule itself is deliberately not a re-running of the lottery. It strictly preserves the original ranking captured at draw time. On a freed seat in the program, the system filters the candidate set down to applications in this program that are currently in `WAITLISTED` and, when an application crosses district lines, that have a currently `APPROVED` linked transfer request. If the candidate set is empty, the freed-seat decrement to `seats_offered` stands and nothing further happens. Otherwise the system consults the `applications_ranked` snapshot in the program's `LotteryRun`, filters that snapshot to the candidate set while preserving its order, and promotes the first survivor: it transitions from `WAITLISTED` to `OFFERED`, its `offer_expires_at` is set to `Clock.now` plus 168 hours, its `waitlist_position` is cleared to null, and the program's `seats_offered` is incremented by one. The remaining surviving waitlisted applications have their `waitlist_position` recomputed: the second-ranked survivor receives position 1, the third receives position 2, and so on. A `WaitlistEvent` audit row is written, recording the program's `program_id`, the `triggered_by_application_id` whose departure freed the seat, the `promoted_application_id` (which may be null when the waitlist was empty), and the `occurred_at` instant.

A subtlety: when a cross-district waitlisted candidate's transfer request was revoked, the side-effect of revocation has already pushed that application to `WITHDRAWN`; the backfill therefore naturally skips it via the status filter, and the freed offer cascades to the next candidate in the snapshot.

### 3.8. Auditing the Run

The system exposes a read-only audit trail for the lottery: a `LotteryRun` row for each program's draw and a `WaitlistEvent` row for each backfill event. These records carry — for runs — the `seed_used` snapshot, the `applications_ranked` ordering, and the `offers_issued_count`, and — for waitlist events — the `triggered_by_application_id`, `promoted_application_id`, and `occurred_at` fields, and they are never mutated after creation. They give a `DistrictAdmin` or `SystemOperator` a reproducible record of how each seat was allocated and how each subsequent vacancy was filled.

List endpoints support filtering. A caller listing applications may narrow by `student_id`, `program_id`, `status` (where `status` denotes the application lifecycle state), or `family_id`. A caller listing transfer requests may narrow by `target_district_id`, `status`, or `application_id`. A caller listing programs may narrow by `school_id`, `district_id`, `window_status`, or `grade_level`. A caller listing schools may narrow by `district_id` or `school_type`. In every case the filters are optional and the result respects the standard `limit` and `offset` pagination of §2.3.

## 4. Endpoint Definitions

Operations that create a new top-level resource return a `201 Created` status; operations that mutate, transition, or read an existing resource return a `200 OK`. All endpoints are mounted under `/enrollment`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/enrollment/districts` | Create a school district | SystemOperator |
| GET    | `/enrollment/districts` | List districts | SystemOperator, DistrictAdmin, FamilyUser |
| GET    | `/enrollment/districts/{id}` | Read a district | SystemOperator, DistrictAdmin, FamilyUser |
| PATCH  | `/enrollment/districts/{id}` | Update district transfer policy and poverty threshold | SystemOperator |
| POST   | `/enrollment/schools` | Create a school under a district | DistrictAdmin |
| GET    | `/enrollment/schools` | List schools, filterable by district and type | SystemOperator, DistrictAdmin, FamilyUser |
| POST   | `/enrollment/programs` | Create a grade-level seat pool within a school | DistrictAdmin |
| GET    | `/enrollment/programs` | List programs, with filters | SystemOperator, DistrictAdmin, FamilyUser |
| GET    | `/enrollment/programs/{id}` | Read a program (includes derived seat counters and window status) | SystemOperator, DistrictAdmin, FamilyUser |
| PATCH  | `/enrollment/programs/{id}` | Update editable program fields while window status permits | DistrictAdmin |
| POST   | `/enrollment/programs/{id}/lottery/draw` | Run the weighted lottery and issue offers | DistrictAdmin |
| GET    | `/enrollment/programs/{id}/waitlist-events` | List waitlist events for a program in chronological order | DistrictAdmin, SystemOperator |
| POST   | `/enrollment/families` | Register a family | FamilyUser, SystemOperator |
| GET    | `/enrollment/families/{id}` | Read a family (includes the sibling-anchor application id) | FamilyUser, DistrictAdmin, SystemOperator |
| POST   | `/enrollment/students` | Add a student to a family | FamilyUser |
| GET    | `/enrollment/students/{id}` | Read a student | FamilyUser, DistrictAdmin |
| POST   | `/enrollment/applications` | Create a DRAFT application | FamilyUser |
| GET    | `/enrollment/applications` | List applications, filterable by student, program, status, family | FamilyUser, DistrictAdmin, SystemOperator |
| GET    | `/enrollment/applications/{id}` | Read an application | FamilyUser, DistrictAdmin, SystemOperator |
| POST   | `/enrollment/applications/{id}/submit` | Transition DRAFT to SUBMITTED | FamilyUser |
| POST   | `/enrollment/applications/{id}/accept` | Transition OFFERED to ACCEPTED (cascades to sibling offers) | FamilyUser |
| POST   | `/enrollment/applications/{id}/decline` | Transition OFFERED to DECLINED (runs waitlist backfill) | FamilyUser |
| POST   | `/enrollment/applications/{id}/withdraw` | Transition ACCEPTED to WITHDRAWN under the grace window | FamilyUser |
| POST   | `/enrollment/transfer-requests` | Create a PENDING inter-district transfer request | FamilyUser |
| GET    | `/enrollment/transfer-requests` | List transfer requests | FamilyUser, DistrictAdmin, SystemOperator |
| POST   | `/enrollment/transfer-requests/{id}/approve` | Transition PENDING to APPROVED | DistrictAdmin |
| POST   | `/enrollment/transfer-requests/{id}/deny` | Transition PENDING to DENIED | DistrictAdmin |
| POST   | `/enrollment/transfer-requests/{id}/revoke` | Transition APPROVED to REVOKED (cascades to linked application) | DistrictAdmin |
| GET    | `/enrollment/lottery-runs/{id}` | Read a lottery run audit record | DistrictAdmin, SystemOperator |
| POST   | `/enrollment/_clock/advance` | Advance the simulated clock and trigger time-driven sweeps | SystemOperator |
| GET    | `/enrollment/_clock` | Read the current simulated clock | SystemOperator, DistrictAdmin, FamilyUser |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_AUTH_MISSING` | 401 |
| `ERR_AUTH_INVALID_ROLE` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 422 |
| `ERR_VERSION_MISMATCH` | 409 |
| `ERR_REGISTRATION_WINDOW_CLOSED` | 409 |
| `ERR_INVALID_STATE_FOR_TRANSITION` | 409 |
| `ERR_LOTTERY_NOT_READY` | 409 |
| `ERR_LOTTERY_ALREADY_DRAWN` | 409 |
| `ERR_LOTTERY_SEED_MISSING` | 422 |
| `ERR_TRANSFER_NOT_APPROVED` | 422 |
| `ERR_DISTRICT_NO_TRANSFERS` | 422 |
| `ERR_DISTRICT_CAPACITY_EXCEEDED` | 409 |
| `ERR_GRADE_MISMATCH` | 422 |
| `ERR_GRADE_NOT_OFFERED` | 422 |
| `ERR_DUPLICATE_CHOICE_RANK` | 422 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_TOO_MANY_CHOICES` | 422 |
| `ERR_STUDENT_ALREADY_ACCEPTED` | 409 |
| `ERR_SEAT_NOT_AVAILABLE` | 409 |
| `ERR_SEATS_BELOW_COMMITTED` | 422 |
| `ERR_WITHDRAW_GRACE_PASSED` | 409 |
| `ERR_VALIDATION` | 422 |
