# Touring Theatrical Management API — Product Requirements Document

## 1. Introduction

A Broadway touring production lives or dies on logistics executed hundreds of miles from the home office: routing a company of actors, musicians, and stagehands from city to city, honoring venue contracts that mix guarantees against box-office splits, keeping the union-mandated coverage bench deep enough that a single sprained ankle does not cancel a sold-out Saturday, and closing out each week's box-office settlement with the licensor's royalty computed to the cent. This document specifies the Touring Theatrical Management API, the system of record for a touring production's producer office, tour manager, company manager, and box-office treasurer.

The API governs the full commercial lifecycle of a tour: the creation of the production entity with its operating budget and recoupment target; the booking of individual city stops with routing buffers and contract terms; the certification of each venue against the production's technical rider; the scheduling and recording of performances and their box-office grosses; the posting, settlement, and cancellation of local crew calls; the administration of company per-diem payments under two distinct policy variants; the contracting of cast, the structuring of character tracks with understudy and swing coverage, and the injury-replacement protocol that keeps the show playing; and finally the weekly wrap that converts a closed engagement into booked money and advances the tour's recoupment position.

Two themes pervade the design and reward careful reading. First, money is handled through a pinned-order settlement waterfall — guarantee versus split, taxes before levies, marginal royalty brackets sampled against the tour's recoupment flag at a precise instant — so the order in which figures are recorded, submitted, approved, and paid matters as much as the figures themselves, and segregation of duties is enforced between those steps. Second, several entities carry derived state that the server recomputes automatically — a stop's compliance posture, a track's exposure, a tour's recoupment flag — and these derivations cascade across entity boundaries, so a single recorded measurement or injury report can legitimately change the status of resources the caller never named.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every resource and every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which that user acts. The system recognizes exactly four roles, spelled exactly as follows: `Producer`, `TourManager`, `CompanyManager`, and `Treasurer`. A request whose `X-User-Role` header is absent or whose value is not one of these four role names is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose declared role is not authorized for the target endpoint — or, on shared transition endpoints, for the specific transition requested — is rejected with `ERR_FORBIDDEN` (HTTP 403).

For all four roles — `Producer`, `TourManager`, `CompanyManager`, and `Treasurer` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does record it where a workflow requires an audit trail — most notably as `submitted_by` and `approved_by` on a settlement — but it never compares `X-User-ID` to any entity's `id` for ownership purposes. Authorization decisions rest entirely on `X-User-Role`, and the segregation-of-duties checks rest on the recorded audit fields, not on entity ownership.

Role responsibilities in brief: the `Producer` is the general manager's office — it owns tour configuration, venues, contract terms and amendments, waivers of failed technical checks, settlement dispute and void, and the test-driving logical clock. The `TourManager` runs routing and physical production — stops, technical advance, performance scheduling, and crew calls. The `CompanyManager` runs the company itself — cast contracts, character tracks, coverage assignments, injuries, and per-diem administration. The `Treasurer` is the box-office treasurer — recording grosses and audited settlement figures and submitting settlements. Settlement approval and payment are shared between `Producer` and `Treasurer`, subject to the segregation-of-duties rules in §2.11. All four roles may invoke every read endpoint.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets the number of items skipped before the returned window begins and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in the system carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recorded at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer starting at its initial value on creation and incremented by one on every mutation of the resource — including mutations performed automatically by the server as cascade side effects.

This last point bears emphasis: when a cascade touches a parent or sibling resource — when a crew-call cancellation feeds a tour's budget, when a tech-check failure reverts a stop's certification, when a performance's played marking flips a stop to `PLAYING` — each affected resource is genuinely mutated, with its own `updated_at` refreshed and its own `version` incremented. A client holding a previously observed `version` of such a resource will observe it advance even though the client never wrote to that resource directly.

### 2.5. Monetary Representation and Rounding

All money in the system is represented as integer cents. Fields whose names end in `_cents` — budgets, guarantees, grosses, payments, royalties, salaries, per-diem rates, penalties — are non-negative integers unless a specific rule states otherwise (one settlement field is explicitly permitted to go negative; see §3.7). Every rounding performed anywhere in the system uses the round-half-up method to the nearest whole cent; no other rounding mode appears in any calculation. Where a calculation is defined over several components, the scaffold of each calculation pins exactly which components are rounded and in what order — per-bracket rounding for royalties, per-line rounding for crew pay, a single rounded half-day rate for per-diems — and §3 states each pinned order alongside its workflow.

Percentages enter the system through `split_pct`, a number constrained to lie between 0 and 100 inclusive, and through fixed royalty rates expressed in basis points. Date fields such as `play_week_start`, `play_week_end`, `load_in_date`, and `perf_date` are ISO dates; `scheduled_start` on a crew call is a full ISO datetime; `curtain_time` is an `HH:MM` 24-hour clock string.

### 2.6. Optimistic Concurrency Control

Two write operations require an optimistic-concurrency token, and they are the only two endpoints in the system that accept a version field in their request bodies.

Creating a stop against a tour requires the non-optional field `expected_tour_version`, carrying the client’s last observed `version` of the parent tour. If the tour’s current `version` does not match — because another stop creation has advanced it since the client last read the tour — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412). This protects the caller from booking against a route and budget position it has not observed.

Amending a stop’s contract terms requires the non-optional field `expected_stop_version`, carrying the client’s last observed `version` of the stop. If the stop’s current `version` does not match, the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field; all other mutations proceed without an OCC check.

### 2.7. Nested Resource Resolution

Many resources exist only under a parent: a stop belongs to a tour; performances, tech-rider checks, crew calls, per-diem statements, and a settlement belong to a stop; cast members and character tracks belong to a tour; coverage assignments belong to a track; injury events belong to a cast member. For any request whose path carries multiple identifiers, the server resolves those identifiers left to right — tour, then stop, then the child — and each identifier must resolve to an existing resource that belongs to the declared parent chain. The path identifiers used across the API are `tour_id`, `venue_id`, `stop_id`, `track_id`, `cast_id`, `check_id`, `perf_id`, `settlement_id`, `coverage_id`, `injury_id`, `pd_id`, and `cc_id`. The first identifier that fails to resolve, or whose resource does not belong to the established parent, rejects the request with `ERR_NOT_FOUND` (HTTP 404). Foreign keys supplied in request bodies — a `venue_id` on stop creation, a `cast_member_id` on a coverage or per-diem, a `principal_member_id` on a track — must likewise resolve to existing resources or the request fails with `ERR_NOT_FOUND`. Every child resource also exposes its parent linkage as a system-maintained field on its representation: a stop carries its `tour_id`, a performance, check, settlement, per-diem statement, and crew call each carry their `stop_id`, a cast member and a character track each carry their `tour_id`, a coverage assignment carries its `track_id`, and an injury event carries the `cast_member_id` of the injured performer.

### 2.8. The Validation Pipeline and Its Ordering

Every mutating request passes through a fixed validation pipeline, and the order of evaluation is itself part of the contract, because a request that violates several rules must surface the earliest one.

First come authentication and authorization (priority 1 and 2): the presence and validity of the role header (`ERR_UNAUTHENTICATED`), the role’s permission for the endpoint and requested transition (`ERR_FORBIDDEN`), and on settlement approval and payment the segregation-of-duties checks (`ERR_SOD_SUBMIT_APPROVE`, `ERR_SOD_APPROVE_PAY`), which are authorization-class rejections evaluated before any existence or state question.

Second comes existence (priority 3): path and body identifiers resolve per §2.7, yielding `ERR_NOT_FOUND`.

Third comes request shape (priority 4): required fields present, unknown fields rejected, enums valid, and numeric ranges respected — cents non-negative, `split_pct` between 0 and 100 inclusive, `play_week_end` on or after `play_week_start`, `load_in_date` on or before `play_week_start`, crew-call `lines` non-empty with unique positions, `actual_lines` positions matching planned positions, and per-diem ranges as detailed in §3.6. Generic shape failures yield `ERR_INVALID_REQUEST` (HTTP 400). Two shape-adjacent checks carry their own codes and are evaluated immediately after the generic shape pass and before any state check: a per-diem statement whose `days_present` falls outside 1 to 7 or whose `travel_days` exceeds the smaller of 2 and `days_present` is rejected with `ERR_PER_DIEM_INVALID` (HTTP 400), and waiving a check without a `waiver_note` is rejected with `ERR_WAIVER_NOTE_REQUIRED` (HTTP 400).

Fourth come state guards (priority 5, all HTTP 409): tour transition legality (`ERR_TOUR_INVALID_STATE`), stop transition and sub-resource creation legality (`ERR_STOP_INVALID_STATE`), compliance certification (`ERR_STOP_NOT_COMPLIANT`), performance scheduling and marking legality (`ERR_STOP_NOT_SCHEDULABLE`, `ERR_PERFORMANCE_INVALID_STATE`), tech-check legality (`ERR_CHECK_INVALID_STATE`), settlement transition legality (`ERR_SETTLEMENT_INVALID_STATE`), cast and injury legality (`ERR_CAST_INVALID_STATE`), coverage-release legality (`ERR_COVERAGE_ACTIVATED`), per-diem payment legality (`ERR_PER_DIEM_INVALID_STATE`), crew-call legality (`ERR_CREW_INVALID_STATE`), and wrap readiness (`ERR_WRAP_NOT_READY`).

Fifth come business safety caps (priority 6, HTTP 422): the weekly and daily performance caps (`ERR_WEEKLY_SHOW_CAP`, `ERR_DAILY_SHOW_CAP`) and the crew-complement rule (`ERR_CREW_COMPLEMENT_SHORT`).

Sixth come uniqueness rules (priority 7, HTTP 422): duplicate coverage rank, duplicate per-diem, or a second open injury on one member — all surfaced as `ERR_DUPLICATE_RECORD`.

Seventh come temporal rules (priority 8, HTTP 422): routing-window conflicts between stops (`ERR_STOP_WINDOW_CONFLICT`), performance dates inside the play week (`ERR_PERFORMANCE_OUTSIDE_WEEK`), and the same-day curtain gap (`ERR_CURTAIN_GAP_CONFLICT`).

Eighth come referential rules about the state of referenced members (priority 9, HTTP 422): `ERR_PRINCIPAL_NOT_CONTRACTED` and `ERR_PRINCIPAL_DOUBLE_BOOKED`.

Last come fiscal rules (priority 10, HTTP 422): the tour budget check (`ERR_TOUR_BUDGET_EXCEEDED`) and the settlement completeness check (`ERR_SETTLEMENT_INCOMPLETE`).

### 2.9. The Logical Clock

Time-dependent rules — cancellation penalties measured against the clock, crew-call cancellation windows — never consult wall-clock time. The system maintains a logical clock whose value before any explicit set is exactly `2026-08-01T00:00:00Z`. A `Producer` may advance the logical clock by supplying a `to_iso8601` instant through the clock-setting capability; the endpoint returns the resulting `current_utc`. Once set, the clock holds the supplied value until the next explicit set — it never falls back to wall-clock time.

### 2.10. Derived State and Automatic Transitions

Several fields are never written by clients directly. A stop’s `compliance_status` is a derived dimension recomputed on every tech-check creation, measurement, or waiver. A track’s `available_covers` and `exposed` recompute on every coverage change and every cast-member status change. A tour’s `budget_committed_cents`, `budget_spent_cents`, `budget_available_cents`, `cumulative_producer_net_cents`, `recouped`, and `royalty_accrued_cents` are computed fields maintained by the server. A cast member’s `bump_shows_accrued` and `bump_pay_cents` accrue automatically as covered performances are played. The server may also transition resources without an explicit client request on that resource — flipping a stop to `PLAYING` when its first performance is marked played, closing a stop and auto-creating its settlement when its final performance resolves, reverting a certified stop when a check fails, moving cast and coverages through the injury cascade. Every such automatic transition and recomputation is a real mutation for the purposes of §2.4.

### 2.11. Segregation of Duties in Settlement

Settlement follows a three-step custody chain — submit, approve, pay — and the system enforces that no two consecutive steps are performed by the same user. The user who submits a settlement is recorded as `submitted_by`; approval of that settlement by the same `X-User-ID` is rejected with `ERR_SOD_SUBMIT_APPROVE` (HTTP 403). The user who approves is recorded as `approved_by`; payment by the same `X-User-ID` is rejected with `ERR_SOD_APPROVE_PAY` (HTTP 403). Resubmission of a disputed settlement records a fresh `submitted_by`, re-arming the submit-approve segregation check against the new submitter. Approval and payment may be performed by either a `Producer` or a `Treasurer` — the segregation check, not the role, is what separates the two steps.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Production: Tours and Venues

A production begins when a `Producer` creates a tour, supplying its `name`, the total operating budget `budget_total_cents`, the `capitalization_cents` the production must earn back before post-recoupment royalty rates apply, the per-diem policy `per_diem_policy` (either `FULL_WEEK` or `ACTUAL_DAYS`), the daily per-diem rate `per_diem_daily_cents` (which must be greater than zero), and the royalty bracket boundary `royalty_tier_threshold_cents` (also greater than zero). Both budget and capitalization must be non-negative. A new tour starts in `PLANNING` status with `recouped` false and all computed counters — `budget_committed_cents`, `budget_spent_cents`, `cumulative_producer_net_cents`, `royalty_accrued_cents` — at zero. The `budget_available_cents` of a tour is always its `budget_total_cents` minus `budget_committed_cents` minus `budget_spent_cents`; this identity holds after every mutation, and every mutation that moves money between the committed and spent buckets preserves it.

The tour’s own lifecycle is short and one-directional: `PLANNING` to `ON_TOUR` to `COMPLETED` to `CLOSED`, each step taken by a `Producer` patching the tour’s `status`. Moving from `ON_TOUR` to `COMPLETED` requires that every stop of the tour be terminal — each in `WRAPPED` or `CANCELLED`. Moving from `COMPLETED` to `CLOSED` requires that every settlement of the tour be in `PAID` or `VOID`. An out-of-order or premature transition is rejected with `ERR_TOUR_INVALID_STATE`.

Venues are the other foundational record. A `Producer` registers each venue with its `name`, `city`, and the four technical specifications the rider will later be checked against: `stage_width_ft` and `power_amps` (each greater than zero), `fly_capacity_lines`, and `crew_available` — the number of local stagehands the venue can supply per call (each non-negative).

### 3.2. Routing the Tour: Stops, Budget Commitment, and Amendments

With the production and its venues on file, a `TourManager` builds the route by adding stops to the tour. Creating a stop requires the booking `venue_id`, the play window `play_week_start` through `play_week_end` (the end on or after the start, both inclusive), the `load_in_date` (on or before `play_week_start`), the `travel_in_days` needed from the previous city (non-negative — this drives the routing buffer), and the commercial terms `guarantee_cents` (non-negative) and `split_pct` (between 0 and 100 inclusive). Advance box-office knowledge may be supplied as `advance_sales_cents`, defaulting to 0. Creation requires the OCC token `expected_tour_version` as described in §2.6, and the tour must be bookable — in `PLANNING` or `ON_TOUR`; booking against a `COMPLETED` or `CLOSED` tour is rejected with `ERR_TOUR_NOT_BOOKABLE`. A new stop is created with `booking_status` `TENTATIVE` and `compliance_status` `PENDING`, and its creation increments the tour’s `version`.

Routing is where the temporal windowing rules bite. The new stop’s play window, treated as a closed interval, must clear every other non-`CANCELLED` stop of the tour with a mandatory travel buffer: either the new stop’s `play_week_start` falls strictly after the sibling’s `play_week_end` plus the new stop’s own `travel_in_days`, or the sibling’s `play_week_start` falls strictly after the new stop’s `play_week_end` plus the sibling’s `travel_in_days`. Equality on the passing side — a start exactly one day after the sibling’s end plus the travel days — passes; anything tighter is rejected with `ERR_STOP_WINDOW_CONFLICT`.

A `TENTATIVE` stop becomes real when a `Producer` contracts it. Contracting requires the tour to be in `PLANNING` or `ON_TOUR` and subjects the deal to the budget gate: the tour’s `budget_available_cents` must be at least the stop’s `guarantee_cents`, or the request fails with `ERR_TOUR_BUDGET_EXCEEDED`. On success the guarantee moves into the committed bucket — the tour’s `budget_committed_cents` rises by `guarantee_cents` and `budget_available_cents` recomputes. While a stop is `CONTRACTED`, a `Producer` may amend its contract terms; the amendment must carry `expected_stop_version` per §2.6 and at least one term field among `guarantee_cents`, `split_pct`, `load_in_date`, and `travel_in_days` — an empty amendment is `ERR_INVALID_REQUEST`. Amending outside `CONTRACTED` is rejected with `ERR_STOP_INVALID_STATE`. When the guarantee changes, the tour’s `budget_committed_cents` shifts by the difference between the new and old guarantee, and a guarantee increase is again subject to the budget gate: the tour’s available funds must cover the positive delta, else `ERR_TOUR_BUDGET_EXCEEDED`. A successful amendment increments the stop’s `version`.

From `CONTRACTED`, a `TourManager` advances the stop to `ADVANCED` — the technical advance has begun. Stop transitions are strict about their sources: contracting only from `TENTATIVE`, advancing only from `CONTRACTED`, certifying only from `ADVANCED`, wrapping only from `CLOSED`, and cancellation only from `TENTATIVE`, `CONTRACTED`, `ADVANCED`, or `READY`; any other source state draws `ERR_STOP_INVALID_STATE`.

### 3.3. Certifying the Venue: Tech Rider Compliance

During the advance — that is, while a stop is `CONTRACTED` or `ADVANCED` (creation at any other time is `ERR_STOP_INVALID_STATE`) — a `TourManager` registers the production’s technical rider checks against the venue. Each check names an `item` from the four rider categories `STAGE_WIDTH_FT`, `FLY_LINES`, `POWER_AMPS`, and `CREW_MINIMUM`, and a `required_value` (greater than zero) stating the rider minimum. A new check is `PENDING`, and the very first check created on a stop moves its derived `compliance_status` from `PENDING` to `IN_PROGRESS`.

The `TourManager` then records the venue’s measured reality as `actual_value` (non-negative) on each check. The system computes the outcome: if the recorded value is at least the required value the check becomes `PASS`; below the requirement it becomes `FAIL`. Measurements may be re-recorded — a `FAIL` check can be remediated to `PASS` by a later qualifying measurement, a `PASS` check can regress to `FAIL` on re-measurement, and a passing re-measurement on a `PASS` check simply reconfirms it. Recording a measurement on a `WAIVED` check is rejected with `ERR_CHECK_INVALID_STATE`, because `WAIVED` is terminal. A `Producer` may waive a check that currently stands at `FAIL` by supplying a `waiver_note`; the note is mandatory, its absence draws `ERR_WAIVER_NOTE_REQUIRED`, and waiving a check not in `FAIL` draws `ERR_CHECK_INVALID_STATE`.

Every create, measurement, and waiver recomputes the stop’s `compliance_status`: it is `COMPLIANT` when at least one check exists and every check is `PASS` or `WAIVED`; `NON_COMPLIANT` whenever any check stands at `FAIL`; `IN_PROGRESS` when checks exist, none has failed, and at least one remains `PENDING`. Certification — the `TourManager`’s transition of the stop from `ADVANCED` to `READY` — requires `compliance_status` to be `COMPLIANT`; certifying against anything less is rejected with `ERR_STOP_NOT_COMPLIANT`. Certification also freezes the stop’s forward-looking money: at the moment of certification the server sets `estimated_venue_payment_cents` to the larger of the stop’s `guarantee_cents` and `split_pct` percent of `advance_sales_cents` rounded half-up to whole cents. This provisional estimate deliberately treats advance sales as the adjusted-gross proxy — no taxes or levies are deducted — and it is frozen at certification; the final settlement in §3.7 will recompute the same terms against audited actuals.

Certification is fragile. If any check on a `READY` stop flips to `FAIL` — through a fresh measurement or a re-measurement — the stop’s certification is revoked automatically: `compliance_status` becomes `NON_COMPLIANT` and `booking_status` reverts from `READY` to `ADVANCED`, blocking performance scheduling until the stop is re-certified.

### 3.4. Playing the Week: Performances and Box Office

Once a stop stands at `READY` (or is already `PLAYING`), a `TourManager` schedules performances, each carrying a `perf_date`, a `curtain_time` in `HH:MM` 24-hour form, and a `duration_minutes` running time greater than zero. Scheduling against a stop in any other booking state is rejected with `ERR_STOP_NOT_SCHEDULABLE`. Three protective rules govern the shape of the week, evaluated in the pipeline order of §2.8. The date must fall within the play week — on or after `play_week_start` and on or before `play_week_end`, both ends inclusive — else `ERR_PERFORMANCE_OUTSIDE_WEEK`. The week is capped at eight shows: the count of performances in `SCHEDULED` or `PLAYED` whose `perf_date` lies within the play week must be below eight before a new one is added — the eighth is allowed, the ninth is rejected with `ERR_WEEKLY_SHOW_CAP`. A single day hosts at most two performances: a third performance on the same `perf_date` is rejected with `ERR_DAILY_SHOW_CAP`. And when two performances share a date, the later `curtain_time` must be at least the earlier curtain time plus the earlier show’s `duration_minutes` plus 120 minutes of turnaround; equality passes, anything shorter is rejected with `ERR_CURTAIN_GAP_CONFLICT`.

A scheduled performance is `SCHEDULED` until it resolves. The `Treasurer` marks it `PLAYED`, recording the performance’s `gross_cents` — which must be present and non-negative, with 0 a perfectly valid played gross for a papered house. The `TourManager` may instead mark it `CANCELLED`. Both markings are only legal from `SCHEDULED`; acting on a terminal performance draws `ERR_PERFORMANCE_INVALID_STATE`. Marking is itself gated on the stop still being `READY` or `PLAYING` — otherwise `ERR_STOP_NOT_SCHEDULABLE`.

Played markings bubble upward. The first `PLAYED` performance of a stop flips the stop from `READY` to `PLAYING`. Every performance marked `PLAYED` pays the coverage bench: for each coverage assignment standing at `ACTIVATED` on tracks of this tour, the covering cast member’s `bump_shows_accrued` rises by one and `bump_pay_cents` recomputes per §3.9. And when every performance of the stop has resolved — each `PLAYED` or `CANCELLED` — with at least one performance existing, the stop closes: `booking_status` becomes `CLOSED` and the server auto-creates the stop’s settlement in `DRAFT` with `system_gross_cents` frozen as the sum of `gross_cents` over the stop’s `PLAYED` performances. A dark week — every performance cancelled, with at least one existing — closes directly from `READY` and produces its `DRAFT` settlement with `system_gross_cents` of 0.

### 3.5. Local Labor: Crew Calls, Settlement, and Cancellation

While a stop is `ADVANCED`, `READY`, or `PLAYING`, a `TourManager` posts local crew calls (posting at any other time is `ERR_STOP_INVALID_STATE`). Each call has a `call_type` of `LOAD_IN`, `LOAD_OUT`, or `SHOW_RUN`, a `scheduled_start` datetime, and a non-empty `lines` array of planned positions, each entry a `position` with its `rate_cents_per_hour`; positions must be unique within the call. The crew-complement rule guards the post: when the stop carries a `CREW_MINIMUM` tech check standing at `PASS` or `WAIVED`, the number of lines on the call must be at least that check’s `required_value`; and regardless of rider checks, the line count must not exceed the venue’s `crew_available`. Violations are rejected with `ERR_CREW_COMPLEMENT_SHORT`. A posted call is `POSTED`.

After the work, the `TourManager` settles the call by supplying `actual_lines` — entries of `position` and `hours_worked` that must match the planned `lines` position-for-position exactly, or the settle is rejected with `ERR_INVALID_REQUEST`. Settlement computes `total_pay_cents` line by line, in a pinned rounding order: for each line, take `hours_worked`; the first eight hours are paid straight at the line’s rate; the next four hours — the portion of hours beyond eight, up to a cap of four — are paid at one and a half times the rate; any hours beyond twelve are paid at double the rate. The line total is the sum of those three components rounded half-up to whole cents, and the call’s `total_pay_cents` is the sum of the per-line totals — rounding happens once per line, never on the grand sum. Exactly eight hours pays no overtime, and at exactly twelve hours the double-time component is zero. Settling is legal only from `POSTED`, else `ERR_CREW_INVALID_STATE`.

A call may instead be cancelled, by the `TourManager` or automatically when its stop is cancelled — again only from `POSTED`. Cancellation measures the call’s `scheduled_start` against the logical clock: if fewer than 24 hours remain, every planned line accrues a show-up penalty of four hours at its rate, each line’s penalty rounded half-up individually and then summed into the call’s `cancellation_penalty_cents`; with 24 hours or more remaining — exactly 24 hours included — the penalty is zero.

### 3.6. Company Per-Diem Administration

While a stop is `READY`, `PLAYING`, or `CLOSED`, a `CompanyManager` issues per-diem statements to the company members working that city (issuing at any other stop state is `ERR_STOP_INVALID_STATE`). Each statement names its `cast_member_id`, the `days_present` the member spent in the stop city that week (between 1 and 7 inclusive), and of those days the `travel_days` spent traveling — at most the smaller of 2 and `days_present`. Range violations are rejected with `ERR_PER_DIEM_INVALID`. At most one statement may exist per stop and cast member; a second issue for the same pair is `ERR_DUPLICATE_RECORD`.

At creation the statement snapshots the tour’s policy into `policy_snapshot` and the tour’s daily rate into `daily_rate_cents`, so later changes to tour configuration never rewrite issued statements. The `total_cents` then depends on the snapshotted policy. Under `FULL_WEEK`, the statement pays seven times the daily rate regardless of `days_present` or `travel_days`. Under `ACTUAL_DAYS`, the half-day rate is computed first — the daily rate divided by two, rounded half-up to whole cents — and the statement pays the non-travel days (`days_present` minus `travel_days`) at the full daily rate plus the `travel_days` at that rounded half rate. The two variants agree only when the member was present all seven days with no travel days. A statement is `ISSUED` on creation; the `CompanyManager` later marks it `PAID`, a transition legal only from `ISSUED` — paying a statement not in `ISSUED` is `ERR_PER_DIEM_INVALID_STATE`.

### 3.7. Box-Office Settlement: The Waterfall and the Licensor’s Royalty

The settlement of a closed stop is where the week’s money is finally divided. The settlement arrives as a system-created `DRAFT` carrying `system_gross_cents` frozen at creation. The `Treasurer` records the venue’s audited figures onto the settlement — `audited_gross_cents`, `taxes_cents`, and `levies_cents`, each non-negative — which may be written while the settlement is `DRAFT` or `DISPUTED`; writing figures alone preserves the status and changes nothing else.

Submission by the `Treasurer` requires all three audited figures to be present; submitting without any of them is rejected with `ERR_SETTLEMENT_INCOMPLETE`. On submit, the server records the caller as `submitted_by` and recomputes the waterfall in its pinned evaluation order. First, `adjusted_gross_cents` is the audited gross minus taxes minus levies — taxes deducted first, levies second, always in that order. Second, `venue_payment_cents` is the larger of the stop’s `guarantee_cents` and `split_pct` percent of the adjusted gross rounded half-up to whole cents — the guarantee-versus-split election resolved in the venue’s favor, and the only step of the waterfall that rounds. Third, `producer_share_cents` is the adjusted gross minus the venue payment — a figure that may legitimately go negative when the guarantee exceeds the adjusted gross, the producer covering the shortfall. Royalty never feeds back into the venue payment or the producer share.

The settlement’s status machine permits the following moves, any other transition drawing `ERR_SETTLEMENT_INVALID_STATE`: from `DRAFT` to `SUBMITTED`; from `SUBMITTED` either to `APPROVED` or — by a `Producer` supplying a `dispute_reason`, whose absence draws `ERR_INVALID_REQUEST` — to `DISPUTED`; from `DISPUTED` back to `SUBMITTED` (the `Treasurer` may re-set figures in the same submission, the waterfall recomputes from the current figures, and the new caller is recorded as `submitted_by`, re-arming the segregation check); from `DISPUTED` to `VOID` by a `Producer`; and from `APPROVED` to `PAID`.

Approval is where the licensor is paid, and it is the moment the royalty rate card is sampled. Approving — by a `Producer` or `Treasurer` other than the recorded `submitted_by`, per the segregation rule of §2.11 — records the caller as `approved_by` and computes `royalty_cents` as a marginal two-bracket royalty over `producer_share_cents`, using the tour’s `royalty_tier_threshold_cents` as the bracket boundary and the tour’s `recouped` flag at the instant of approval as the rate selector. When the producer share is zero or negative, the royalty is zero. Before recoupment, the portion of the share up to the threshold is charged at 6 percent and any portion above the threshold at 9 percent; after recoupment, the portions are charged at 8 percent and 11 percent respectively. Each bracket’s amount is rounded half-up to whole cents individually, and the royalty is the sum of the two rounded brackets. The reading is strictly marginal — only the share above the threshold pays the higher rate; a flat reading that charged the higher rate on the entire share would overstate the royalty whenever the share exceeds the threshold and is not how this system computes it. The computed `royalty_cents` is added into the tour’s `royalty_accrued_cents`, which at all times equals the sum of royalties over settlements in `APPROVED` or `PAID`. Payment — by a `Producer` or `Treasurer` other than the recorded `approved_by` — completes the chain; `PAID` and `VOID` are terminal.

### 3.8. The Weekly Wrap and the Recoupment Flip

A `CLOSED` stop is wrapped by a `Producer`, and only once its settlement stands at `PAID` — wrapping earlier is rejected with `ERR_WRAP_NOT_READY`. The wrap books the week’s money in one atomic accounting. Stop costs are the sum of `total_pay_cents` over the stop’s crew calls in `SETTLED`, plus the sum of `cancellation_penalty_cents` over its crew calls in `CANCELLED`, plus the sum of `total_cents` over its per-diem statements in `ISSUED` or `PAID` — anything outside those named states is excluded. The stop’s producer net is its settlement’s `producer_share_cents` minus its `royalty_cents` minus those stop costs. The stop’s `wrapped_total_cents` — the total money out booked at wrap — is the settlement’s `venue_payment_cents` plus `royalty_cents` plus stop costs.

The wrap then settles accounts with the tour: `budget_committed_cents` falls by the stop’s `guarantee_cents`, `budget_spent_cents` rises by `wrapped_total_cents`, and `cumulative_producer_net_cents` rises by the stop’s producer net. Only after those totals post does the tour re-evaluate its recoupment: `recouped` becomes true once `cumulative_producer_net_cents` is at least `capitalization_cents` — the boundary itself counts — and the flag flips only here, at wrap. The ordering is deliberate and load-bearing: this stop’s royalty was fixed at approve time against the recoupment flag of that instant, so a wrap that crosses the capitalization line affects only settlements approved afterwards.

Cancellation is the other way a stop leaves the board. A `Producer` may cancel a stop standing at `TENTATIVE`, `CONTRACTED`, `ADVANCED`, or `READY`. The stop’s `cancellation_penalty_cents` is computed from the logical clock: `days_out` is the whole number of days between the clock’s current date and `play_week_start`, taken as the floor of the difference. Cancelling from `TENTATIVE` never penalizes. From `CONTRACTED`, `ADVANCED`, or `READY`: more than 60 days out, the penalty is zero; 31 to 60 days out inclusive, it is a quarter of `guarantee_cents` rounded half-up; 30 days out or fewer, it is half of `guarantee_cents` rounded half-up. The 60-day boundary pays the quarter rate; day 61 pays nothing. If the cancelled stop had been committed, its guarantee leaves `budget_committed_cents` and the penalty lands in `budget_spent_cents`. Cancellation cascades: every `SCHEDULED` performance of the stop becomes `CANCELLED`, and every `POSTED` crew call becomes `CANCELLED`, each accruing its own cancellation penalty per §3.5 — and those crew penalties add into the tour’s `budget_spent_cents` as well.

### 3.9. The Company: Contracts, Tracks, and the Coverage Bench

The `CompanyManager` engages the company by creating cast members with a `name`, a `contract_type` of `PRINCIPAL`, `UNDERSTUDY`, `SWING`, or `ENSEMBLE`, and a `weekly_salary_cents` greater than zero. A new member is `OFFERED`; signing moves them to `CONTRACTED` — a transition legal only from `OFFERED`, else `ERR_CAST_INVALID_STATE`.

The artistic structure of the production is expressed in character tracks, each created with a `track_name`, a `required_covers` count (non-negative) stating how many covers the track must have available, and optionally a `principal_member_id`. A track may also be assigned or re-assigned its principal later; in either case the referenced member must be `CONTRACTED` and belong to the same tour — otherwise `ERR_PRINCIPAL_NOT_CONTRACTED` — and no member may be principal of more than one track of the tour, else `ERR_PRINCIPAL_DOUBLE_BOOKED`. Coverage assignments join a track to a covering cast member with a `kind` of `UNDERSTUDY` or `SWING` — understudies rank before swings in selection — and a `priority_rank` of at least 1 fixing the selection order within the kind; the rank must be unique among the non-`RELEASED` coverages of the same track and kind, a collision drawing `ERR_DUPLICATE_RECORD`. The covering member must likewise be `CONTRACTED` on the same tour. A new coverage stands at `STANDBY`.

Two derived numbers keep the bench honest. A track’s `available_covers` counts its coverages standing at `STANDBY` whose cast member is `CONTRACTED`. A track is `exposed` when its available covers fall below `required_covers` — with the caveat that a track requiring zero covers is never exposed. Every coverage change and every cast-member status change recomputes both figures on every affected track.

A coverage may be released from `STANDBY` by the `CompanyManager`; releasing an `ACTIVATED` coverage — one currently covering an open injury — is rejected with `ERR_COVERAGE_ACTIVATED`. Releasing an entire cast member, also a `CompanyManager` action, is legal from `OFFERED`, `CONTRACTED`, or `ON_LEAVE`, but is blocked while any of the member’s coverages stands at `ACTIVATED` (again `ERR_COVERAGE_ACTIVATED`); on release, the member’s `STANDBY` and `SUSPENDED` coverages are released with them, and every affected track recomputes. `REPLACED` and `RELEASED` are terminal for a cast member.

### 3.10. Injury, Coverage Activation, and Return

When a performer goes down, the `CompanyManager` reports an injury on the cast member, optionally with free-text `notes`. The member must be `CONTRACTED` — reporting on anyone else is `ERR_CAST_INVALID_STATE` — and no member may carry two open injuries: one injury in `COVERED` per member at a time, a second report drawing `ERR_DUPLICATE_RECORD`. The injury event is created in an atomic fork decided by the coverage selector.

The selector considers the coverages on the injured member’s principal track, filtering to those standing at `STANDBY` whose cast member is `CONTRACTED`. It ranks candidates with understudies before swings, then by ascending `priority_rank`, then — the final tie-break — by ascending creation time; the coverage’s `id` is never used in ranking. When the pool yields a candidate, the event takes the `COVERED` branch: the injured member moves from `CONTRACTED` to `ON_LEAVE`; that leave suspends the member’s own `STANDBY` and `ACTIVATED` coverages on other tracks, each suspension recomputing its track’s bench; the selected coverage flips from `STANDBY` to `ACTIVATED` and is recorded on the event as `covered_by_coverage_id`; and the activated coverage’s track recomputes — an activated cover is not an available cover, so the track may become `exposed`.

When the pool is empty, the event takes the `REPLACED` branch instead — but only if the injured member actually is the principal of some track of the tour; an injury on a non-principal member with no coverage path is rejected with `ERR_PRINCIPAL_NOT_CONTRACTED`. In this branch the member moves directly from `CONTRACTED` to `REPLACED`, skipping `ON_LEAVE` entirely; no coverage is activated; `covered_by_coverage_id` stays null; and the principal’s track keeps its `principal_member_id` pointing at the replaced member until the `CompanyManager` assigns a successor, its exposure recomputing against the vacant bench.

A `COVERED` injury may resolve. Resolution — by the `CompanyManager`, and only from `COVERED`, anything else drawing `ERR_INJURY_INVALID_STATE` — returns the member from `ON_LEAVE` to `CONTRACTED`, flips the activated coverage recorded in `covered_by_coverage_id` back to `STANDBY` (safely doing nothing if none was recorded), restores the member’s `SUSPENDED` coverages to `STANDBY`, and recomputes every affected track. `RESOLVED` and `REPLACED` are terminal states for an injury event.

Finally, the understudy bump pays the covering bench for its work. Each performance marked `PLAYED` while a coverage stands at `ACTIVATED` accrues one show to the covering member’s `bump_shows_accrued`, and `bump_pay_cents` is the accrued show count multiplied by a per-show unit: the weekly salary of the track’s principal — the member recorded as `principal_member_id` — divided by eight, rounded half-up to whole cents. A member with no covered shows has a bump pay of zero.

## 4. Endpoint Definitions

Operations that create a new resource — a tour, a venue, a stop, a check, a performance, a cast member, a track, a coverage, an injury, a per-diem statement, or a crew call — return `201 Created`. Operations that modify an existing resource, including all status transitions, amendments, figure recording, and the clock set, return `200 OK`. Readers reconstruct complete request payloads from the narratives of §3; this table is a locator, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/tours` | Create a tour (status `PLANNING`, counters 0, `recouped` false) | Producer |
| GET | `/tours/{tour_id}` | Get a tour with computed budget/recoup fields | Any |
| PATCH | `/tours/{tour_id}` | Advance tour status (`PLANNING`→`ON_TOUR`→`COMPLETED`→`CLOSED` with preconditions) | Producer |
| POST | `/venues` | Create a venue with tech specs and local crew capacity | Producer |
| GET | `/venues/{venue_id}` | Get a venue | Any |
| POST | `/tours/{tour_id}/stops` | Add a stop to the route (OCC on the tour’s `version`); window-conflict and routing-buffer checks apply | TourManager |
| GET | `/stops` | List stops; filterable by `tour_id`, `venue_id`, `status` | Any |
| GET | `/stops/{stop_id}` | Get a stop | Any |
| PUT | `/stops/{stop_id}` | Drive `booking_status`: `CONTRACTED`/`WRAPPED`/`CANCELLED` (Producer), `ADVANCED`/`READY` (TourManager); `WRAPPED` runs the weekly wrap | Producer, TourManager |
| POST | `/stops/{stop_id}/amend` | Amend contract terms while `CONTRACTED` (OCC on the stop’s `version`); at least one term field required | Producer |
| POST | `/stops/{id}/tech-checks` | Create a rider compliance check (stop `CONTRACTED` or `ADVANCED`) | TourManager |
| GET | `/stops/{id}/tech-checks` | List checks of a stop | Any |
| PUT | `/tech-checks/{check_id}` | Record `actual_value` (TourManager; system sets `PASS`/`FAIL`) or waive a `FAIL` via `status` `WAIVED` with `waiver_note` (Producer) | TourManager, Producer |
| POST | `/stops/{id}/performances` | Schedule a performance (stop `READY`/`PLAYING`; weekly cap 8, daily cap 2, curtain gap 120 minutes) | TourManager |
| GET | `/stops/{id}/performances` | List performances of a stop; filterable by `perf_date` | Any |
| PUT | `/performances/{perf_id}` | Mark `PLAYED` with `gross_cents` (Treasurer) or `CANCELLED` (TourManager); bubble-up may flip the stop and auto-create the settlement | Treasurer, TourManager |
| GET | `/stops/{id}/settlement` | Fetch the settlement of a stop (1:1, returns an array of zero or one) | Any |
| PUT | `/settlements/{settlement_id}` | Record audited figures (Treasurer; `DRAFT` or `DISPUTED`, no status change) and drive status: `SUBMITTED` (Treasurer), `DISPUTED`/`VOID` (Producer), `APPROVED`/`PAID` (Producer or Treasurer with segregation of duties) | Treasurer, Producer |
| POST | `/tours/{id}/cast` | Create a cast member (`OFFERED`) | CompanyManager |
| GET | `/tours/{id}/cast` | List cast of a tour; filterable by `status`, `contract_type` | Any |
| GET | `/cast/{cast_id}` | Get a cast member | Any |
| PUT | `/cast/{cast_id}` | Drive cast status: `CONTRACTED` from `OFFERED`, or `RELEASED` (blocked while any coverage is `ACTIVATED`) | CompanyManager |
| POST | `/tours/{id}/tracks` | Create a character track (principal optional at creation) | CompanyManager |
| GET | `/tours/{id}/tracks` | List tracks of a tour | Any |
| GET | `/tracks` | List tracks; filterable by `tour_id`, `principal_member_id` | Any |
| GET | `/tracks/{track_id}` | Get a track with computed `available_covers`/`exposed` | Any |
| PATCH | `/tracks/{track_id}` | Assign or replace the principal (member `CONTRACTED`, not principal of another track) | CompanyManager |
| POST | `/tracks/{id}/coverages` | Assign an understudy/swing cover (member `CONTRACTED`; rank unique per track and kind among non-`RELEASED`) | CompanyManager |
| GET | `/tracks/{id}/coverages` | List coverages of a track; filterable by `status` | Any |
| GET | `/cast/{id}/coverages` | List coverages held by a cast member; filterable by `status` | Any |
| PUT | `/coverages/{coverage_id}` | Release a `STANDBY` coverage | CompanyManager |
| POST | `/cast/{id}/injuries` | Report an injury; atomically takes the `COVERED` branch (selector activates a coverage) or the `REPLACED` branch (empty pool) | CompanyManager |
| GET | `/cast/{id}/injuries` | List injuries of a cast member | Any |
| PUT | `/injuries/{injury_id}` | Resolve a `COVERED` injury (member returns, coverage deactivates, suspensions restore) | CompanyManager |
| POST | `/stops/{id}/per-diems` | Issue a per-diem statement (one per stop and cast member); computes `total_cents` from tour snapshots | CompanyManager |
| GET | `/stops/{id}/per-diems` | List per-diem statements of a stop | Any |
| GET | `/cast/{id}/per-diems` | List per-diem statements of a cast member | Any |
| PUT | `/per-diems/{pd_id}` | Mark a statement `PAID` | CompanyManager |
| POST | `/stops/{id}/crew-calls` | Post a local crew call with planned rate lines (complement checks apply) | TourManager |
| GET | `/stops/{id}/crew-calls` | List crew calls of a stop | Any |
| PUT | `/crew-calls/{cc_id}` | Settle with `actual_lines` (computes crew pay) or cancel (computes the cancellation penalty against the logical clock) | TourManager |
| POST | `/_clock/set_current_utc` | Set the logical clock (default before any call is exactly `2026-08-01T00:00:00Z`; never falls back to wall-clock time) | Producer |

## 5. Error Code Catalogue

Trigger conditions for each error live with their workflows in §2 and §3; this catalogue is a locator only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SOD_SUBMIT_APPROVE` | 403 |
| `ERR_SOD_APPROVE_PAY` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_WAIVER_NOTE_REQUIRED` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_TOUR_NOT_BOOKABLE` | 409 |
| `ERR_TOUR_INVALID_STATE` | 409 |
| `ERR_INJURY_INVALID_STATE` | 409 |
| `ERR_STOP_INVALID_STATE` | 409 |
| `ERR_STOP_NOT_COMPLIANT` | 409 |
| `ERR_STOP_NOT_SCHEDULABLE` | 409 |
| `ERR_CHECK_INVALID_STATE` | 409 |
| `ERR_PERFORMANCE_INVALID_STATE` | 409 |
| `ERR_SETTLEMENT_INVALID_STATE` | 409 |
| `ERR_SETTLEMENT_INCOMPLETE` | 422 |
| `ERR_CAST_INVALID_STATE` | 409 |
| `ERR_COVERAGE_ACTIVATED` | 409 |
| `ERR_PRINCIPAL_NOT_CONTRACTED` | 422 |
| `ERR_PRINCIPAL_DOUBLE_BOOKED` | 422 |
| `ERR_DUPLICATE_RECORD` | 422 |
| `ERR_PER_DIEM_INVALID` | 400 |
| `ERR_PER_DIEM_INVALID_STATE` | 409 |
| `ERR_WEEKLY_SHOW_CAP` | 422 |
| `ERR_DAILY_SHOW_CAP` | 422 |
| `ERR_CURTAIN_GAP_CONFLICT` | 422 |
| `ERR_STOP_WINDOW_CONFLICT` | 422 |
| `ERR_TOUR_BUDGET_EXCEEDED` | 422 |
| `ERR_CREW_INVALID_STATE` | 409 |
| `ERR_CREW_COMPLEMENT_SHORT` | 422 |
| `ERR_PERFORMANCE_OUTSIDE_WEEK` | 422 |
| `ERR_WRAP_NOT_READY` | 409 |
