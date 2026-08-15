# Title I Program Compliance API — Product Requirements Document

## 1. Introduction

Every fall, a district's federal programs office inherits the same high-stakes puzzle: a Title I, Part A allocation from the state education agency (SEA) that must be distributed to schools by poverty ranking, carved into mandatory set-asides, defended against supplanting findings, reconciled against actual spending, and — if more than fifteen percent remains unspent at year's end — either justified to the SEA through a carryover waiver or surrendered to close-out rules. The work is governed by a web of interlocking federal constraints: schoolwide versus targeted-assistance program thresholds, equitable-services obligations to private-school children, supplement-not-supplant (SNS) methodology documentation, allowable-cost review, and SEA monitoring with corrective action plans. A single missed consultation or stale poverty snapshot can invalidate an entire allocation run.

This document specifies the Title I Program Compliance API, the system of record for that lifecycle. It covers poverty measurement and school ranking, program-model determination, the four regulatory set-asides, SNS documentation, private-school consultation, expenditure charging and allowable-cost review, net-zero budget amendments, carryover accounting with its waiver loop, and SEA monitoring from visit scheduling through finding resolution. The API is mounted under `/title-i` and is written for two audiences: district staff who operate the workflows and the engineers who must implement them so that every figure an auditor recomputes matches the system's own arithmetic to the cent.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes four distinct roles: `FederalProgramsDirector`, `ComplianceAnalyst`, `SEAMonitor`, and `PrivateSchoolOmbudsman`. Failure to provide both headers, or supplying a role the system does not recognize, results in an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error (HTTP 400). A request whose role is recognized but not permitted to call the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

For all four roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as the audit anchor on the resources a user touches — for example, as `submitted_by_user_id` on an expenditure, SNS document, or budget amendment; as `cap_submitted_by_user_id` on a monitoring finding; as `affirmation_signer_id` on a consultation; as `lead_monitor_id` on a visit; and as `reviewed_by_user_id` or `decided_by_user_id` on reviewed artifacts — but it never compares `X-User-ID` to any entity's `id`. This applies identically to `FederalProgramsDirector`, `ComplianceAnalyst`, `SEAMonitor`, and `PrivateSchoolOmbudsman`: none of the four roles is entity-backed.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A `limit` below 1 or above 100, a negative `offset`, or a non-integer value for either is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

List-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

In addition to `limit` and `offset`, list endpoints accept domain filters as optional query parameters, each exact-match unless stated otherwise: grants filter by `fiscal_year` and `status`; schools by `is_active`; private schools by `nonprofit_verified`; poverty snapshots by `grant_id` and `status`; school allocations by `grant_id`, `school_id`, `snapshot_id`, `status`, `program_model`, and `eligibility_flag`; set-asides by `grant_id` and `category`; SNS documents by `school_allocation_id` and `status`; consultations by `grant_id`, `private_school_id`, and `status`; expenditures by `grant_id`, `school_allocation_id`, `set_aside_id`, and `status`; budget amendments by `grant_id` and `status`; monitoring visits by `grant_id` and `status`; and monitoring findings by `visit_id`, `status`, and `severity`. Boolean filters (`is_active`, `nonprofit_verified`) accept only the literal values `true` and `false`, and the `fiscal_year` filter must parse as an integer; anything else is rejected with `ERR_INVALID_REQUEST`.

### 2.4. Common Resource Properties

Every primary resource in the system — grants, schools, private schools, poverty snapshots, school allocations, set-asides, SNS documents, consultations, expenditures, budget amendments, monitoring visits, and monitoring findings — carries a standard set of system-managed fields:

- **`id` (string):** A unique, server-generated identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** An ISO 8601 UTC timestamp with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`) recording when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp, refreshed on any change to the resource's properties.
- **`version` (integer):** A system-managed integer that starts at 1 on creation and increments with every modification to the resource, enabling optimistic concurrency control.

Mutations of computed fields count as modifications: when an expenditure review recomputes a grant's ledger totals, or when a finding decision recomputes a grant's monitoring clearance, the owning resource's `updated_at` refreshes and its `version` increments even though no client-supplied field changed.

### 2.5. Cents, Basis Points, and Rounding Discipline

All monetary amounts in the system are integers denominated in cents — `total_allocation_cents`, `reserved_cents`, `amount_cents`, and their kin never carry fractional values. All percentages that govern eligibility, set-asides, and carryover are integer **basis points**, where 10,000 basis points equal one hundred percent; the fifteen-percent carryover ceiling is therefore 1500 basis points, and the forty-percent schoolwide threshold is 4000 basis points.

Whenever a division or a rate multiplication produces a fractional result — a poverty percentage, a set-aside minimum, a per-pupil amount, a carryover percentage — the value is rounded **half up** — ties away from zero — to the nearest integer (cents or basis points, per the field). Rounding is applied exactly where each rule in §3 states it: some pipelines round per school before reconciling a remainder, others round once at the final division. No calculation rounds early "for safety," and no field stores a floating-point approximation.

### 2.6. The Grant's Parallel State Dimensions

A district grant carries **two independent state dimensions on the same row**. The first, `status`, walks the fiscal lifecycle `SETUP` → `RANKING_LOCKED` → `ALLOCATED` → `CLOSED_OUT` and never moves backward. The second, `carryover_waiver_status`, tracks the SEA waiver conversation through `NONE`, `REQUESTED`, `GRANTED`, and `DENIED`, including a re-request loop from `DENIED` back to `REQUESTED`. Each dimension enforces only its own preconditions: a waiver may be requested while the grant sits in `ALLOCATED` regardless of how close close-out is, and the grant's lifecycle does not wait on a waiver decision except where §3.10 says otherwise.

Because the grant row is the fiscal baseline for everything beneath it, the system stamps a generation counter, `ranking_version`, that starts at zero and increments on every successful ranking lock and every snapshot certification — two events that re-baseline the school figures. Separately, the grant's `version` advances on every mutation of the grant row, including mutations performed as side effects of other resources (an expenditure creation, an amendment approval, a finding decision), and `updated_at` refreshes at the same time.

### 2.7. Optimistic Concurrency Control on the Grant Baseline

Two write operations re-baseline the grant's allocation figures and therefore require the client to prove it observed the current baseline. Creating a budget amendment and certifying a poverty snapshot both require a non-optional `expected_grant_version` field in the request body, carrying the grant's `version` as the client last read it. If the value does not match the grant's current `version` — because a prior amendment create, approve, or void, a snapshot certification, a ranking lock, a finalization, or any other grant-row mutation has advanced it since the client's read — the request is rejected with `ERR_STALE_GRANT_VERSION` (HTTP 412), and nothing is written. An amendment's lines are absolute post-amendment values, so drafting them against a superseded baseline would silently misstate every target; the stale-version rejection is what prevents that. Endpoints other than these two do not accept a version field.

### 2.8. Validation Order and Request Integrity

Every request passes through a fixed gauntlet of checks, and the order is part of the contract. First, the presence and recognition of the identity headers (§2.1), then role permission for the target endpoint. Third, existence: every resource id appearing in the path and every foreign-key id in the body must resolve, validated left to right — path parameters first, then body fields in their declared order — with the first miss rejected as `ERR_NOT_FOUND` (HTTP 404). Fourth, body schema: required fields present (a required string must be non-empty), types correct, enum membership honored, charged amounts strictly positive, and no unknown or read-only fields supplied, all rejected as `ERR_INVALID_REQUEST` (HTTP 400); date-range inversions surface as `ERR_INVALID_DATE_RANGE` (HTTP 400) and sub-minimum narratives as `ERR_NARRATIVE_TOO_SHORT` (HTTP 400) at this same tier. Immediately after schema validation, structural conflicts are checked: a duplicate `fiscal_year` on grant creation yields `ERR_DUPLICATE_FISCAL_YEAR` (HTTP 409), a duplicate `nces_id` on school registration yields `ERR_INVALID_REQUEST`, the same `school_id` twice inside a snapshot's `entries` yields `ERR_DUPLICATE_SCHOOL_ENTRY` (HTTP 400), and a second consultation for the same grant-and-private-school pair yields `ERR_DUPLICATE_CONSULTATION` (HTTP 409).

Only then do state-machine gates fire (fifth), each carrying its own 409 error from the catalogue, followed by the optimistic-concurrency check of §2.7 (sixth). Seventh come the segregation-of-duties rules of §2.9, and eighth the open-findings close-out block. Ninth, cross-entity referential consistency: snapshot coverage, private-school verification, consultation completeness at finalization, charge-target consistency, and snapshot-locked schools; the supplement-not-supplant gate fires immediately after charge-target consistency, once the charged allocation is known. Tenth, the temporal rules: fiscal-period bounds on incurred costs, clock bounds on sessions and visit starts, visit overlap, SNS window overlap, and corrective-action due dates. Eleventh and last, the fiscal rules: set-aside floors, amendment net-zero and post-amendment floors, charge amounts against remaining balances, and the carryover and waiver conditions. Because the tiers run in this sequence, a request that fails several of them surfaces the earliest failure — a malformed body reports `ERR_INVALID_REQUEST`, never a masked state-machine error from a later tier. A request whose path matches no route, or whose method the route does not support, is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.9. Segregation of Duties

No operator may adjudicate their own submission. The segregation rule binds five decision points, and at each the acting user's `X-User-ID` must differ from the recorded submitter's: a budget amendment's approve, reject, and void decisions are checked against the amendment's `submitted_by_user_id`; an SNS document review is checked against its `submitted_by_user_id`; an expenditure's allowable-cost review is checked against its `submitted_by_user_id`; and a monitoring finding's CAP acceptance or return is checked against its `cap_submitted_by_user_id`. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The rule has no override and no role exception — a `FederalProgramsDirector` who drafted an amendment cannot then approve it.

### 2.10. The Logical Clock

The server maintains a logical clock that governs every date-sensitive rule in the system: consultation session dates, visit start windows, and the finding-escalation sweep. At startup, before any client call, the clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time. A `FederalProgramsDirector` advances it through an admin-only test-driving capability that accepts a `to_iso8601` instant, sets the clock, and returns the resulting `current_utc` together with an `escalated_finding_ids` array naming every finding the sweep escalated (see §3.9). The submitted instant is parsed leniently — a naive value is read as UTC and a bare date as midnight UTC — any instant is accepted (earlier or later), and the sweep runs on every set; the returned `current_utc` echoes the submitted `to_iso8601` string verbatim. Whenever §3 refers to "the current clock date," it means the date portion of this logical clock, not the host machine's calendar.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Fiscal-Year Grant

A `FederalProgramsDirector` opens the fiscal year by creating the **district grant**: the `fiscal_year` (unique across all grants and between 2020 and 2100 inclusive), the `total_allocation_cents` awarded for Title I, Part A (strictly positive), the `poverty_measure` the year's ranking will use — one of `CENSUS_SAIPE`, `FREE_REDUCED_LUNCH`, `MEDICAID_DIRECT_CERT`, or `COMPOSITE` — and optionally `carryover_in_cents` from the prior year (defaulting to zero, never negative), `admin_reserve_cents` taken off the top for district-level administration (defaulting to zero, never negative, and never exceeding the sum of the total allocation and the carryover in), and `equitable_count_method`, which selects the equitable-services share variant and defaults to `CONSULTATION_AGREED` (the alternative is `VERIFIED_COUNT`). Creating a second grant for an already-used `fiscal_year` is rejected with `ERR_DUPLICATE_FISCAL_YEAR`.

The new grant enters `SETUP` with `carryover_waiver_status` at `NONE`, `ranking_version` at 0, `monitoring_clearance` at `NOT_MONITORED`, and both ledger totals at zero. The system immediately derives `net_allocable_cents` as the total allocation plus the carryover in minus the administrative reserve, and it recomputes the provisional carryover fields described in §3.10 on every subsequent fiscal event. The grant's funds period — the window in which costs may be incurred — runs from July 1 of the calendar year preceding `fiscal_year` through June 30 of `fiscal_year`.

From `SETUP` the grant advances to `RANKING_LOCKED` when the director locks the rankings (§3.3), from there to `ALLOCATED` at finalization, and finally to `CLOSED_OUT` at fiscal close-out. Any operation whose grant-state precondition fails is rejected with `ERR_GRANT_INVALID_STATE`.

### 3.2. The District's Schools and the Poverty Data Snapshot

A `ComplianceAnalyst` registers each public school with its `name`, its unique `nces_id`, and its grade span — `grade_span_low` between 0 and 12 (0 denotes pre-K) and `grade_span_high` at least `grade_span_low` and at most 12 — an endpoint outside 0–12 is rejected with `ERR_INVALID_REQUEST` before the inversion check; an inverted span is rejected with `ERR_INVALID_DATE_RANGE`, and a reused `nces_id` with `ERR_INVALID_REQUEST`. The `is_active` flag defaults to true and governs snapshot coverage: every active school must appear in every certified poverty snapshot. The analyst may later flip `is_active` — the only field a PATCH may carry; a request without it, or restating the current value, changes nothing and does not increment `version` — but a school that appears in any `CERTIFIED` snapshot can no longer be deactivated — the attempt is rejected with `ERR_SCHOOL_LOCKED_BY_SNAPSHOT`.

Participating private schools are registered separately with a `name`, the `low_income_resident_count` of district-resident low-income children attending the school (never negative; this is the verified-count source used by the `VERIFIED_COUNT` variant in §3.4), a `contact_email` for the ombudsman, and a `nonprofit_verified` flag that defaults to false. Consultation may not be opened with a school whose nonprofit status is unverified (§3.6).

With the school roster in place, the analyst builds a **poverty data snapshot** for a grant by supplying the `grant_id`, the `measure` — which must equal the grant's `poverty_measure`, or the certification later fails with `ERR_INVALID_REQUEST` — and the `entries`, an array of records each carrying a `school_id`, that school's `low_income_student_count`, and its `total_student_count`. Within an entry the low-income count must be at least zero and at most the total, and the total must be strictly positive; repeating a `school_id` is rejected with `ERR_DUPLICATE_SCHOOL_ENTRY`. Coverage is enforced at creation and again at certification: the entries must cover every school with `is_active` set exactly once, or the request is rejected with `ERR_SNAPSHOT_INCOMPLETE_COVERAGE`. The snapshot is born in `DRAFT` status. Creation carries no grant-state precondition; the grant-state gate applies only at certification.

Certification is the director's act, and it is the heaviest operation in the system. A snapshot may be certified only while it is `DRAFT` (otherwise `ERR_SNAPSHOT_NOT_CERTIFIABLE`), only while its grant is in `SETUP`, `RANKING_LOCKED`, or `ALLOCATED`, and only when the entries cover every active school exactly once — a missing or extra active school is rejected with `ERR_SNAPSHOT_INCOMPLETE_COVERAGE`. Certification also carries the optimistic-concurrency check of §2.7: the request must include `expected_grant_version` matching the grant's current `version`, else it is rejected with `ERR_STALE_GRANT_VERSION` (HTTP 412). Within certification the checks fire in §2.8 order — snapshot state, grant state, the version check, then coverage — and the measure-equality check runs last.

A successful certification stamps `certified_at` and then cascades through three depths, atomically. At depth one, any other snapshot of the same grant currently in `CERTIFIED` flips to `SUPERSEDED` — the certified-cardinality invariant guarantees at most one certified snapshot per grant. At depth two, if the grant is `RANKING_LOCKED` or `ALLOCATED`, every school allocation of the grant is recomputed in place from the new snapshot: the ranking figures of §3.3 are re-derived, and when the grant is `ALLOCATED` the set-aside minimums, the equitable share, and the allocation waterfall of §3.4 are re-run as well (each set-aside's `reserved_cents` is preserved — only `minimum_cents` moves, with the parent-engagement `school_distributed_minimum_cents` recomputed from the preserved reserve — and each existing row's `serve_elected` flag is retained); any allocation that had been `CERTIFIED` flips back to `PENDING`, and newly active schools receive fresh `PENDING` rows (schools absent from the new entries cannot exist among the old rows, because coverage is total over active schools). At depth three, every SNS document in `ACCEPTED` whose allocation just flipped from `CERTIFIED` to `PENDING` flips to `STALE`, and every expenditure still in `PENDING_REVIEW` with `supplant_screen` set on such an allocation flips to `DISALLOWED` with `disallow_reason` stamped `SNS_STALE_CASCADE`. Finally, the grant's `ranking_version` increments by one and its `version` increments by one, which is exactly what makes a concurrently drafted amendment fail its own `expected_grant_version` check. When the grant is still in `SETUP`, no allocations exist and the depth-two and depth-three cascades have nothing to touch.

### 3.3. Locking Rankings and the Allocation Waterfall

Locking the rankings is the director's bridge from `SETUP` to `RANKING_LOCKED`. It requires the grant to be in `SETUP` (else `ERR_GRANT_INVALID_STATE`) and requires at least one snapshot of the grant in `CERTIFIED` status — with none, the lock is rejected with `ERR_NO_CERTIFIED_SNAPSHOT`. On success the system creates one **school allocation** row per snapshot entry, pinning the `grant_id`, the `school_id`, the `snapshot_id` that produced the figures, and the entry's `low_income_student_count` and `total_student_count` as version-pinned copies, and computes each row's ranking figures:

- `poverty_pct_bp` is the school's `low_income_student_count` multiplied by 10,000 and divided by its `total_student_count`, rounded half up to a whole basis point.
- `rank_position` orders every school in the snapshot by `poverty_pct_bp` descending; ties break on `low_income_student_count` descending, and any remaining tie breaks on the school's `created_at` ascending. The UUID `id` is never used as a tie-break. Positions are one-based: rank 1 is the highest-poverty school.
- `eligibility_flag` is evaluated on the rounded basis-point value: at least 7500 basis points (seventy-five percent) marks `MUST_SERVE`; at least 3500 but below 7500 marks `ELIGIBLE`; below 3500 marks `BELOW_THRESHOLD`.
- `program_model` is `SCHOOLWIDE` when the school's poverty percentage reaches at least 4000 basis points (forty percent) and `TARGETED_ASSISTANCE` otherwise.

Each new allocation starts in `PENDING` status with `serve_elected` false, `supplement_ok` false, its ledger totals at zero, and `per_pupil_cents` and `allocation_amount_cents` at zero until finalization. The lock also increments the grant's `ranking_version` and `version` by one each.

Finalization moves the grant from `RANKING_LOCKED` to `ALLOCATED` and is where money actually attaches to schools. Before any arithmetic, a consultation gate fires when the grant's `equitable_count_method` is `CONSULTATION_AGREED`: every private school with `nonprofit_verified` set must have a consultation for this grant in `AFFIRMATION_SIGNED` status, or finalization is rejected with `ERR_CONSULTATION_INCOMPLETE`. The director may optionally pass `serve_below_threshold_school_ids`, a list of school ids (matched to allocation rows by `school_id`) below the eligibility threshold to elect into the served set — an id naming no school, or a school with no allocation row in this grant, is rejected with `ERR_NOT_FOUND`, while electing a school at or above the threshold is accepted but has no effect; each elected row is flagged `serve_elected` and treated as served. An allocation counts as `served` when its `eligibility_flag` is anything other than `BELOW_THRESHOLD` or when it was elected; the allocation's response body carries this derivation as a boolean `served` field.

Finalization then creates the four set-asides and runs the waterfall of §3.4, writing every allocation row of the grant — filling `per_pupil_cents` and `allocation_amount_cents` on every served allocation — and advances the grant's `version` by one.

Once the grant is `ALLOCATED`, the director certifies individual allocations: a `PENDING` allocation transitions to `CERTIFIED` (a row in any other state is rejected with `ERR_ALLOCATION_NOT_PENDING`), and the operation requires the grant to be `ALLOCATED` (else `ERR_GRANT_INVALID_STATE`). Certification bumps the allocation's own `version`. The reverse transition, `CERTIFIED` → `PENDING`, is never client-invoked — it is the system-driven consequence of a snapshot recertification (§3.2), which recomputes the row's figures in place.

### 3.4. Set-Asides, the Equitable Share, and the Waterfall Arithmetic

Finalization creates four `SetAside` rows for the grant, one per `category`: `PARENT_ENGAGEMENT`, `HOMELESS_SERVICES`, `PROFESSIONAL_DEVELOPMENT`, and `EQUITABLE_SERVICES`. Each row's `minimum_cents` is the regulatory floor, and its `reserved_cents` is initialized to that floor (creation and the figure-write are separate modifications, so a set-aside's `version` reads 2 immediately after finalization):

- The `PARENT_ENGAGEMENT` minimum is one percent of the grant's `total_allocation_cents`, rounded half up to a whole cent — but only when `total_allocation_cents` is strictly greater than $500,000.00; a grant at or below that threshold has a parent-engagement minimum of zero.
- The `HOMELESS_SERVICES` minimum is the greater of a $5,000.00 floor and one-half of one percent of `net_allocable_cents`, the rate portion rounded half up to a whole cent.
- The `PROFESSIONAL_DEVELOPMENT` minimum is five percent of `net_allocable_cents`, rounded half up to a whole cent.
- The `EQUITABLE_SERVICES` minimum comes from the equitable-share computation below.

The equitable share is evaluated in a pinned order that breaks the circular dependency between the share and the school pool. First, the three non-equitable minimums are subtracted from `net_allocable_cents`, leaving a residual base. Second, the private-school low-income count is determined by the grant's `equitable_count_method`: under `CONSULTATION_AGREED` it is the sum of `agreed_low_income_count` across this grant's consultations in `AFFIRMATION_SIGNED` status, with unsigned consultations contributing zero; under `VERIFIED_COUNT` it is the sum of `low_income_resident_count` across all private schools with `nonprofit_verified` set, consultation status irrelevant. Third, the public count is the sum of `low_income_student_count` across the served allocations. The `EQUITABLE_SERVICES` minimum is then the residual base multiplied by the private count and divided by the sum of the public and private counts, rounded half up to a whole cent; when the private count is zero, the minimum is zero. The school pool is the residual base minus the equitable-services minimum. The share is deliberately computed on the residual base — net of the three non-equitable set-asides — not on `net_allocable_cents` directly and not on the post-share school pool.

The waterfall then distributes the school pool across the served set defined in §3.3. Each served school carries a weight: 150 for a `MUST_SERVE` school, 125 for a school at or above the schoolwide threshold but below must-serve (4000 to 7499 basis points), 100 for a targeted-assistance school (3500 to 3999 basis points), and 125 for a `serve_elected` school below the threshold — the elected weight deliberately sits above the targeted-assistance weight, overriding the otherwise non-increasing schedule within the elected band only. Multiplying each served school's weight by its `low_income_student_count` yields its raw claim, and the school pool divided by the sum of all raw claims yields an exact rational unit value, held without rounding (should that sum be zero, every `per_pupil_cents` is zero and the whole pool passes to the remainder reconciliation below). Each served school's `per_pupil_cents` is the unit value multiplied by its own weight, rounded half up to a whole cent — this per-school rounding happens before any reconciliation — and its `allocation_amount_cents` is exactly `per_pupil_cents` multiplied by its `low_income_student_count`. Per-school rounding rarely sums to the pool exactly, so a remainder is reconciled one cent at a time: when the allocated total falls short of the pool, cents are added cycling through the served allocations in `rank_position` ascending order; when it overshoots, cents are removed cycling in `rank_position` descending order. Unserved allocations keep `per_pupil_cents` and `allocation_amount_cents` at zero.

The `PARENT_ENGAGEMENT` row carries one further derived field: `school_distributed_minimum_cents`, ninety percent of its `reserved_cents` rounded half up to a whole cent — the share that must flow down to schools rather than stay at the district level. For the other three categories this field is always zero. It is recomputed every time `reserved_cents` changes, whether through a set-aside adjustment or through an amendment approval or void that touches the parent-engagement row.

After finalization, the director may adjust any set-aside by supplying a new `reserved_cents` — a negative value is rejected with `ERR_INVALID_REQUEST`, otherwise upward without bound and downward only to the floor: a value below `minimum_cents` is rejected with `ERR_SET_ASIDE_BELOW_MINIMUM`. Adjustment carries no grant-state precondition. A successful adjustment recomputes the parent-engagement distribution minimum when that category is touched and advances the grant's `version` by one. The same three set-aside minimums, the equitable share, and the waterfall are re-run wholesale when a snapshot recertifies while the grant is `ALLOCATED` (§3.2).

### 3.5. Supplement-Not-Supplant Documentation

Title I funds must supplement, not supplant, state and local funds, and the district proves its methodology through an **SNS document** per school allocation. A `ComplianceAnalyst` or the director files one by naming the `school_allocation_id`, choosing a `methodology` of `PER_SCHOOL_DISTRIBUTION`, `GRADE_SPAN_GROUPING`, or `PER_PUPIL_FORMULA`, giving the half-open coverage window `coverage_start_date` (inclusive) through `coverage_end_date` (exclusive) — an end date on or before the start is rejected with `ERR_INVALID_DATE_RANGE` — and writing a `narrative` of at least 50 characters (shorter is rejected with `ERR_NARRATIVE_TOO_SHORT`). Filing carries no allocation-state precondition; the `CERTIFIED` requirement bites at submission. Coverage windows on the same allocation must not overlap as half-open intervals — the check runs against every existing document on the allocation, whatever its status: two windows that merely touch at an endpoint do not conflict, but any true intersection is rejected with `ERR_SNS_WINDOW_OVERLAP`. A new document starts in `DRAFT` with `attempt_count` at zero.

Submission moves the document to `SUBMITTED` and is open to the analyst or the director. It is permitted from `DRAFT`, from `RETURNED` (the revision loop), and from `STALE` (the re-baseline loop after a recertification cascade); from any other state it is rejected with `ERR_SNS_NOT_SUBMITTABLE`. Submission additionally requires the covered allocation to be `CERTIFIED`, else `ERR_ALLOCATION_NOT_CERTIFIED`. Each submission records the caller as `submitted_by_user_id` and increments `attempt_count` by one.

Review belongs to the director alone, acting on a document in `SUBMITTED` (otherwise `ERR_SNS_NOT_REVIEWABLE`) and never on their own submission (§2.9). A `decision` of `ACCEPT` moves the document to `ACCEPTED`, records `reviewed_by_user_id` (an optional `review_note` may accompany either decision), and recomputes the allocation's `supplement_ok` to true; a `decision` of `RETURN` moves it to `RETURNED` and requires a `review_note` explaining the rework (missing, the review is rejected with `ERR_INVALID_REQUEST`). An `ACCEPTED` document flips to `STALE` only through the system cascade of §3.2, which simultaneously recomputes `supplement_ok` to false — the documentation no longer provably covers the recomputed allocation, which is precisely why screened expenditures cascade to `DISALLOWED` alongside it.

### 3.6. Private-School Consultation and Equitable Services

Equitable services begin with a `ComplianceAnalyst` opening a **consultation** between a grant and a private school, supplying the `grant_id` and `private_school_id`. Opening carries no grant-state precondition. The school must have `nonprofit_verified` set, else `ERR_PRIVATE_SCHOOL_NOT_VERIFIED`, and the pair must be unique — a second consultation for the same grant and school is rejected with `ERR_DUPLICATE_CONSULTATION`. The consultation opens in `INITIATED` status with an empty `sessions` log and `sessions_count` at zero.

Sessions are logged by the analyst, each appending an entry of `session_date`, `topics` (a string or an array), and `attendee_count` (a non-negative integer) to the append-only `sessions` array and incrementing `sessions_count` by one. Logging is permitted from `INITIATED` (the first session moves the consultation to `CONSULTING`), from `CONSULTING` itself (a self-loop), and from `DISPUTED` (resuming after a dispute); from any other status it is rejected with `ERR_CONSULTATION_INVALID_STATE`. A `session_date` after the current clock date is rejected with `ERR_SESSION_DATE_IN_FUTURE`.

When consultation has matured, the `PrivateSchoolOmbudsman` signs the affirmation, supplying the `agreed_low_income_count` (never negative) that the two parties settled on. Signing requires the consultation to be in `CONSULTING`, requires at least two logged sessions — fewer is rejected with `ERR_INSUFFICIENT_CONSULTATION_SESSIONS` — and requires the grant to be in `SETUP` or `RANKING_LOCKED`, because affirmations lock before allocation; a grant already past that point yields `ERR_GRANT_INVALID_STATE`. A successful signature moves the consultation to `AFFIRMATION_SIGNED` and records the `agreed_low_income_count`, the `affirmation_signed_at` timestamp, and the signer's `affirmation_signer_id`.

The ombudsman who disagrees may instead dispute the outcome from `CONSULTING`, recording a `dispute_reason` as the consultation moves to `DISPUTED`; from `DISPUTED` they may escalate to a formal SEA complaint by filing `complaint_text` (validated but not retained on the consultation), moving to `COMPLAINT_FILED`. An `SEAMonitor` resolves the complaint by posting the SEA's `determination_note`, which is recorded as `complaint_determination` while the consultation returns to `CONSULTING` for continued work. Every one of these transitions enforces its source state with `ERR_CONSULTATION_INVALID_STATE`.

### 3.7. Charging Costs: Expenditure Review and Reclassification

Actual spending enters the system as **expenditures** filed by a `ComplianceAnalyst`. Each charge names the `grant_id`, an `amount_cents` strictly greater than zero, a `function_code` of `INSTRUCTION`, `PD`, `PARENT_ENGAGEMENT`, `HOMELESS_SUPPORT`, or `EQUITABLE_SERVICES`, a free-text `description`, and the `incurred_date` the cost was incurred. The charge target is exactly one of `school_allocation_id` or `set_aside_id`: naming both or neither is rejected with `ERR_CHARGE_TARGET_AMBIGUOUS`, and the named target must belong to the same grant as `grant_id` — a target foreign to the grant is treated as unresolvable within the request and rejected with `ERR_NOT_FOUND`. The function code must agree with the target: a charge against a school allocation must use `INSTRUCTION`, and a charge against a set-aside must use the code matching its category — `PD` for `PROFESSIONAL_DEVELOPMENT`, `PARENT_ENGAGEMENT` for `PARENT_ENGAGEMENT`, `HOMELESS_SUPPORT` for `HOMELESS_SERVICES`, and `EQUITABLE_SERVICES` for `EQUITABLE_SERVICES` — with any mismatch rejected as `ERR_FUNCTION_TARGET_MISMATCH`. An `incurred_date` outside the grant's funds period (§3.1) is rejected with `ERR_COST_OUTSIDE_FISCAL_PERIOD`. Creation carries no grant-state precondition; the `ALLOCATED` requirement applies to review.

Two fiscal gates complete creation. First, the amount must fit the target's remaining balance — for an allocation, its `allocation_amount_cents` minus its `liquidated_cents` minus its `pending_cents`; for a set-aside, its `reserved_cents` minus its `liquidated_cents` minus its own pending charges — or the charge is rejected with `ERR_INSUFFICIENT_ALLOCATION_BALANCE` (HTTP 402). Second, when the filer sets `supplant_screen` to true (default false), flagging that the cost could supplant state or local funds, the charged school allocation must have an `ACCEPTED` SNS document (§3.5); without one the charge is rejected with `ERR_SUPPLANT_RISK_UNRESOLVED` (HTTP 403). A screened charge against a set-aside has no allocation to clear it and is always rejected.

A created expenditure lands in `PENDING_REVIEW`, records its filer as `submitted_by_user_id`, and immediately enters the ledger: pending balances on the grant, and on the target allocation or set-aside, are recomputed within the same request, and the grant's `version` advances by one because its computed ledger fields changed. The grant's ledger is always a live aggregation — `liquidated_cents` is the sum of `amount_cents` over the grant's expenditures in `ALLOWED`, `pending_cents` the same sum over `PENDING_REVIEW`, and each allocation and set-aside carries the same two sums restricted to its own charges — recomputed eagerly inside every triggering request, never deferred to a batch.

Allowable-cost review belongs to the director and never to the filer (§2.9). A review requires the expenditure to be in `PENDING_REVIEW` (else `ERR_EXPENDITURE_NOT_REVIEWABLE`) and the grant to be `ALLOCATED` (else `ERR_GRANT_INVALID_STATE`). A `decision` of `ALLOW` moves the charge to `ALLOWED`; a `decision` of `DISALLOW` moves it to `DISALLOWED` and requires a `disallow_reason` of `SUPPLANT_RISK`, `UNALLOWABLE_COST`, or `INSUFFICIENT_DOCUMENTATION` (missing, the review is rejected with `ERR_INVALID_REQUEST`; the fourth value of the enumeration, `SNS_STALE_CASCADE`, is reserved for the system cascade of §3.2). A `disallow_reason` supplied alongside `ALLOW` is accepted but not stored. Either decision may carry a `review_note` and records the reviewer as `reviewed_by_user_id`, and either one recomputes the ledger aggregates and advances the grant's `version` by one.

A disallowed cost is not necessarily lost money. The analyst may reclassify a `DISALLOWED` expenditure — the only state from which reclassification is permitted, else `ERR_EXPENDITURE_NOT_RECLASSIFIABLE` — by naming a `reclassified_to_fund_source` of `NON_TITLE_I_STATE` or `NON_TITLE_I_LOCAL`. The charge moves to the terminal `RECLASSIFIED` status as compensating bookkeeping; the grant's `liquidated_cents` is unchanged, because the charge was already excluded from the allowed totals at disallow time.

### 3.8. Budget Amendments and the Money-Conservation Invariant

Mid-year rebudgeting happens through **budget amendments**, drafted by either a `ComplianceAnalyst` or the director. Creation, submission, and rejection carry no grant-state precondition; approval and voiding require the grant to be `ALLOCATED`. A draft names the `grant_id`, carries the `expected_grant_version` of §2.7 — a stale baseline is rejected with `ERR_STALE_GRANT_VERSION` (HTTP 412) — and lists its `lines`, each an absolute post-amendment target: a `target_type` of `SCHOOL_ALLOCATION` or `SET_ASIDE`, the `target_id`, and the `new_amount_cents` the target should hold after approval. The array may be empty — an empty draft conserves money trivially — and the same target may appear on multiple lines, applied in array order; every target must belong to the draft's grant, else `ERR_NOT_FOUND`. Because lines are absolute, the draft must conserve money: the sum, over all lines, of each `new_amount_cents` minus the target's current value must equal exactly zero, or creation is rejected with `ERR_AMENDMENT_NOT_NET_ZERO`. A created amendment starts in `DRAFT` and advances the grant's `version` by one, which itself invalidates any other draft pinned to the older baseline.

Submission by the analyst or the director moves a `DRAFT` amendment to `SUBMITTED` and records `submitted_by_user_id`; from any other state the attempt is rejected with `ERR_AMENDMENT_INVALID_STATE`. Approval is the director's call, subject to segregation of duties against the submitter, and requires the grant to be `ALLOCATED`. At approval time every line's floor is re-validated against current reality, not against the draft-time baseline: a set-aside line must leave `reserved_cents` at or above the row's `minimum_cents` (else `ERR_SET_ASIDE_BELOW_MINIMUM`), an allocation line must leave `allocation_amount_cents` at or above the sum of that allocation's `liquidated_cents` and `pending_cents` (else `ERR_AMENDMENT_BELOW_LIQUIDATED`), and a set-aside line must likewise leave the reserve at or above the set-aside's own `liquidated_cents` (also `ERR_AMENDMENT_BELOW_LIQUIDATED`). A successful approval captures `prior_amounts` — a snapshot of each line's `target_id` with its `prior_amount_cents` — writes each line's value onto its target (onto `allocation_amount_cents` or `reserved_cents` as the `target_type` dictates), recomputes the parent-engagement distribution minimum if the `PARENT_ENGAGEMENT` set-aside was touched, and advances the grant's `version` by one. Approval accepts an optional `decision_note`.

Rejection is the sibling decision: the director rejects a `SUBMITTED` amendment — again with segregation of duties against the submitter — and must supply a `decision_note` (missing, the rejection is itself rejected with `ERR_INVALID_REQUEST`). The amendment moves to the terminal `REJECTED` state with `decided_by_user_id` recorded.

An approved amendment can still be undone. Voiding moves an `APPROVED` amendment to the terminal `VOIDED` state; it requires the grant to be `ALLOCATED`, enforces segregation of duties against the original submitter, and restores the captured `prior_amounts` verbatim onto their targets — the compensating action that keeps the money-conservation invariant intact across the amendment's whole life. The parent-engagement distribution minimum is recomputed if that category was touched, and the grant's `version` advances by one. Voiding accepts an optional `decision_note` and records the voider as `decided_by_user_id`.

### 3.9. Monitoring Visits, Findings, and Corrective Action

SEA oversight arrives as **monitoring visits**, scheduled by an `SEAMonitor` with the `grant_id`, an inclusive day interval from `visit_start_date` through `visit_end_date` (an end before the start is rejected with `ERR_INVALID_DATE_RANGE`), and a `scope` of `PROGRAMMATIC`, `FISCAL`, or `COMPREHENSIVE`. The new visit is `SCHEDULED` and records its creator as `lead_monitor_id`. Visits of the same grant must not overlap as closed day intervals — two visits sharing even a single boundary day conflict, and the check considers every other visit of the grant regardless of status — and the overlap check runs both when a visit is scheduled and when one begins, rejected with `ERR_MONITORING_VISIT_OVERLAP`. Scheduling carries no grant-state precondition.

The monitor begins the visit, moving it from `SCHEDULED` to `IN_PROGRESS`, only while the current clock date falls inside the visit window inclusive of both endpoints; a missed window is rejected with `ERR_VISIT_WINDOW_MISSED`, and a visit in any other state with `ERR_VISIT_INVALID_STATE`. Findings may be recorded only while the visit is `IN_PROGRESS` — against any other visit status the recording is rejected with `ERR_VISIT_NOT_ACCEPTING_FINDINGS`. Each **finding** names its `visit_id`, a regulatory `citation`, a `severity` of `OBSERVATION`, `FINDING`, or `SYSTEMIC`, a `description`, and a `cap_due_date` that must fall strictly after the visit's `visit_end_date` (else `ERR_INVALID_DATE_RANGE`). A recorded finding starts in `OPEN` with `cap_attempt_count` at zero, and its creation immediately recomputes the grant's `monitoring_clearance` and advances the grant's `version` by one.

Issuing the report moves an `IN_PROGRESS` visit to `REPORT_ISSUED` and stamps `report_issued_at`. When the visit has no findings at all, it does not linger: it immediately auto-transitions to `CLOSED` — two transitions in one request, so the visit's `version` advances twice — and the grant's `monitoring_clearance` is recomputed — the empty-set closure.

The corrective-action cycle runs on the finding. The analyst or the director submits a CAP from `OPEN`, from `ESCALATED`, or from `CAP_RETURNED` (the revision cycle); any other status is rejected with `ERR_FINDING_INVALID_STATE`. The `cap_narrative` must be at least 50 characters (else `ERR_NARRATIVE_TOO_SHORT`), and each submission records `cap_submitted_by_user_id` and increments `cap_attempt_count` by one, moving the finding to `CAP_SUBMITTED`. The monitor then adjudicates under segregation of duties against `cap_submitted_by_user_id`: accepting moves the finding to the terminal `VERIFIED` state, while returning requires a `return_note` (missing, `ERR_INVALID_REQUEST`) and moves it to `CAP_RETURNED`; both record `decided_by_user_id`. One shortcut exists for trivial matters: an `OPEN` finding whose `severity` is `OBSERVATION` may be closed without corrective action, moving to the terminal `CLOSED_NO_ACTION` state; the shortcut is unavailable to any other severity or status, rejected with `ERR_FINDING_INVALID_STATE`.

Resolution bubbles upward through three depths. The moment a finding reaches `VERIFIED` — or an observation is closed with no action — the system checks its visit: when that was the visit's last finding outside the terminal set (`VERIFIED`, `CLOSED_NO_ACTION`), the visit auto-transitions from `REPORT_ISSUED` to `CLOSED`. One level deeper, the grant's `monitoring_clearance` is recomputed and the grant's `version` advances by one. The clearance derivation itself is a three-way aggregation over the grant's visits and findings: `FINDINGS_OPEN` when any finding of any visit of the grant sits in `OPEN`, `ESCALATED`, `CAP_SUBMITTED`, or `CAP_RETURNED`; `CLEARED` when the grant has at least one `CLOSED` visit and no such finding; and `NOT_MONITORED` otherwise.

Time itself is the final enforcement mechanism. Whenever the logical clock (§2.10) is advanced to a new instant, the escalation sweep fires: every finding whose `cap_due_date` falls strictly before the new clock date and whose status is `OPEN` or `CAP_RETURNED` flips to `ESCALATED`, processed in `created_at` ascending order with `updated_at` refreshed. Findings already in `CAP_SUBMITTED`, `VERIFIED`, or `CLOSED_NO_ACTION` are never escalated. The capability returns the ids of every finding it escalated.

### 3.10. Carryover, Waivers, and Fiscal Close-Out

Federal rules cap how much of a Title I award may remain unspent at year's end, and the grant tracks the exposure continuously. Two carryover variants coexist on the grant row. The **provisional** variant is forward-looking: `provisional_carryover_cents` is `net_allocable_cents` minus `liquidated_cents` minus `pending_cents` — pending charges count as encumbered at face value — and it is recomputed on every expenditure creation, review, and reclassification, and on every amendment approval or void. The **final** variant is chronological: `final_carryover_cents` is `net_allocable_cents` minus `liquidated_cents` only, because no `PENDING_REVIEW` expenditure can exist at close-out, and both it and its percentage are stamped onto the grant at close-out rather than maintained live (until then both read null). Each variant's percentage — `provisional_carryover_pct_bp` and `final_carryover_pct_bp` — is its cents figure multiplied by 10,000 and divided by the grant's `total_allocation_cents`, rounded half up to a whole basis point; note the denominator is the total allocation, not the net allocable amount. The statutory ceiling of fifteen percent is evaluated on the rounded basis-point value: a figure strictly greater than 1500 basis points exceeds the limit.

A district projecting excess carryover asks the SEA for relief through the waiver dimension. The director requests a waiver with a `justification`, which is recorded as `carryover_waiver_justification`. The request requires the grant to be `ALLOCATED` (else `ERR_GRANT_INVALID_STATE`); requires `carryover_waiver_status` to be `NONE` or `DENIED` — the latter being the re-request loop after a denial — with any other value rejected as `ERR_WAIVER_INVALID_STATE`; requires the provisional carryover percentage to be strictly greater than 1500 basis points, since a district already within the limit has nothing to waive (else `ERR_CARRYOVER_WITHIN_LIMIT`); and requires the three-year lookback to be clear: no other grant may hold a `GRANTED` waiver in any of the three fiscal years immediately preceding this grant's `fiscal_year`, or the request is rejected with `ERR_CARRYOVER_WAIVER_WITHIN_3_YEARS`. A denied waiver never blocks a future request, and a granted waiver's own year is the anchor from which the three following years are counted. A valid request moves `carryover_waiver_status` to `REQUESTED`, clears `carryover_waiver_decided_at`, and advances the grant's `version` by one.

The `SEAMonitor` decides a `REQUESTED` waiver — any other waiver status is rejected with `ERR_WAIVER_INVALID_STATE` — with a `decision` of `GRANT` or `DENY` and an optional `decision_note` (validated but not stored). Either decision stamps `carryover_waiver_decided_at`, moves the dimension to `GRANTED` or `DENIED`, and advances the grant's `version` by one.

Close-out is the director's final act on the grant, moving it from `ALLOCATED` to the terminal `CLOSED_OUT`, and four gates guard it beyond the state check itself. No finding of any visit of the grant may remain non-terminal — anything in `OPEN`, `ESCALATED`, `CAP_SUBMITTED`, or `CAP_RETURNED` blocks close-out with `ERR_OPEN_FINDINGS_BLOCK_CLOSEOUT`. No expenditure may remain in `PENDING_REVIEW`, else `ERR_UNRESOLVED_EXPENDITURES`. No amendment may remain in `DRAFT` or `SUBMITTED`, else `ERR_UNRESOLVED_AMENDMENTS`. And the final carryover percentage must be at most 1500 basis points unless the grant holds a `GRANTED` waiver, else `ERR_CARRYOVER_LIMIT_EXCEEDED`. A successful close-out stamps `final_carryover_cents` and `final_carryover_pct_bp` onto the grant and advances its `version` by one, closing the fiscal year for good.

## 4. Endpoint Definitions

Operations that create new stand-alone resources return a `201 Created` status code. Operations that modify an existing resource — state transitions, reviews, adjustments, and the clock — return a `200 OK` status code, as do all reads. The complete request and response shapes of each operation are defined by the workflows of §3; this table is the routing summary. Grant lifecycle operations — lock-rankings, finalize-allocations, close-out, request-carryover-waiver, decide-carryover-waiver — modify the grant and return the updated grant object; the clock operation returns the object described in §2.10.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/title-i/grants` | Create a district Title I grant for a fiscal year | FederalProgramsDirector |
| GET | `/title-i/grants` | List grants | All roles |
| GET | `/title-i/grants/{id}` | Get one grant with all computed ledger and carryover fields | All roles |
| POST | `/title-i/grants/{id}/lock-rankings` | Lock rankings from the certified snapshot; creates school allocation rows | FederalProgramsDirector |
| POST | `/title-i/grants/{id}/finalize-allocations` | Compute set-asides, the equitable share, and the school allocation waterfall | FederalProgramsDirector |
| POST | `/title-i/grants/{id}/close-out` | Close the fiscal year; stamps final carryover; enforces the fifteen-percent limit and waiver | FederalProgramsDirector |
| POST | `/title-i/grants/{id}/request-carryover-waiver` | Request an SEA carryover waiver | FederalProgramsDirector |
| POST | `/title-i/grants/{id}/decide-carryover-waiver` | SEA grants or denies a requested carryover waiver | SEAMonitor |
| POST | `/title-i/schools` | Register a public school | ComplianceAnalyst |
| GET | `/title-i/schools` | List schools | All roles |
| PATCH | `/title-i/schools/{id}` | Update school flags; a school covered by a certified snapshot cannot be deactivated | ComplianceAnalyst |
| POST | `/title-i/private-schools` | Register a participating private school | ComplianceAnalyst |
| GET | `/title-i/private-schools` | List private schools | All roles |
| POST | `/title-i/poverty-snapshots` | Create a poverty data snapshot (DRAFT) for a grant | ComplianceAnalyst |
| GET | `/title-i/poverty-snapshots` | List snapshots | All roles |
| GET | `/title-i/poverty-snapshots/{id}` | Get one snapshot | All roles |
| POST | `/title-i/poverty-snapshots/{id}/certify` | Certify a snapshot; supersedes the prior certified snapshot; re-baselines allocations (OCC on grant version) | FederalProgramsDirector |
| GET | `/title-i/school-allocations` | List school allocations | All roles |
| GET | `/title-i/school-allocations/{id}` | Get one school allocation | All roles |
| POST | `/title-i/school-allocations/{id}/certify` | Certify a PENDING allocation (requires grant ALLOCATED) | FederalProgramsDirector |
| GET | `/title-i/set-asides` | List set-asides | All roles |
| GET | `/title-i/set-asides/{id}` | Get one set-aside | All roles |
| POST | `/title-i/set-asides/{id}/adjust` | Raise or lower the reserved amount, never below the regulatory minimum | FederalProgramsDirector |
| POST | `/title-i/supplement-documentation` | File SNS methodology documentation for a school allocation | ComplianceAnalyst, FederalProgramsDirector |
| GET | `/title-i/supplement-documentation` | List SNS documents | All roles |
| GET | `/title-i/supplement-documentation/{id}` | Get one SNS document | All roles |
| POST | `/title-i/supplement-documentation/{id}/submit` | Submit or resubmit an SNS document for review | ComplianceAnalyst, FederalProgramsDirector |
| POST | `/title-i/supplement-documentation/{id}/review` | Director review: accept or return, with segregation of duties against the submitter | FederalProgramsDirector |
| POST | `/title-i/equitable-services-consultations` | Open consultation with a verified private school for a grant | ComplianceAnalyst |
| GET | `/title-i/equitable-services-consultations` | List consultations | All roles |
| GET | `/title-i/equitable-services-consultations/{id}` | Get one consultation | All roles |
| POST | `/title-i/equitable-services-consultations/{id}/record-session` | Log a consultation session | ComplianceAnalyst |
| POST | `/title-i/equitable-services-consultations/{id}/sign-affirmation` | Ombudsman signs the consultation affirmation | PrivateSchoolOmbudsman |
| POST | `/title-i/equitable-services-consultations/{id}/dispute` | Ombudsman disputes the consultation outcome | PrivateSchoolOmbudsman |
| POST | `/title-i/equitable-services-consultations/{id}/file-complaint` | Ombudsman escalates a dispute to a formal SEA complaint | PrivateSchoolOmbudsman |
| POST | `/title-i/equitable-services-consultations/{id}/resolve-complaint` | SEA posts its determination; consultation resumes | SEAMonitor |
| POST | `/title-i/expenditures` | Charge a cost to a school allocation or set-aside | ComplianceAnalyst |
| GET | `/title-i/expenditures` | List expenditures | All roles |
| GET | `/title-i/expenditures/{id}` | Get one expenditure | All roles |
| POST | `/title-i/expenditures/{id}/review` | Director allowable-cost review: allow or disallow, with segregation of duties against the submitter | FederalProgramsDirector |
| POST | `/title-i/expenditures/{id}/reclassify` | Reclassify a disallowed cost to a non-Title-I fund source | ComplianceAnalyst |
| POST | `/title-i/budget-amendments` | Draft a net-zero budget amendment with absolute target lines (OCC on grant version) | ComplianceAnalyst, FederalProgramsDirector |
| GET | `/title-i/budget-amendments` | List budget amendments | All roles |
| GET | `/title-i/budget-amendments/{id}` | Get one budget amendment | All roles |
| POST | `/title-i/budget-amendments/{id}/submit` | Submit a DRAFT amendment for approval | ComplianceAnalyst, FederalProgramsDirector |
| POST | `/title-i/budget-amendments/{id}/approve` | Approve and apply the lines; floors re-validated at approval | FederalProgramsDirector |
| POST | `/title-i/budget-amendments/{id}/reject` | Reject a submitted amendment | FederalProgramsDirector |
| POST | `/title-i/budget-amendments/{id}/void` | Void an approved amendment, restoring prior amounts verbatim | FederalProgramsDirector |
| POST | `/title-i/monitoring-visits` | Schedule an SEA monitoring visit; same-grant overlap rejected | SEAMonitor |
| GET | `/title-i/monitoring-visits` | List monitoring visits | All roles |
| GET | `/title-i/monitoring-visits/{id}` | Get one monitoring visit | All roles |
| POST | `/title-i/monitoring-visits/{id}/start` | Begin the visit; the clock date must be inside the visit window | SEAMonitor |
| POST | `/title-i/monitoring-visits/{id}/issue-report` | Issue the monitoring report; zero-finding visits auto-close | SEAMonitor |
| POST | `/title-i/monitoring-findings` | Record a finding on an in-progress visit | SEAMonitor |
| GET | `/title-i/monitoring-findings` | List findings | All roles |
| GET | `/title-i/monitoring-findings/{id}` | Get one finding | All roles |
| POST | `/title-i/monitoring-findings/{id}/submit-cap` | Submit a corrective action plan (from OPEN, ESCALATED, or CAP_RETURNED) | ComplianceAnalyst, FederalProgramsDirector |
| POST | `/title-i/monitoring-findings/{id}/accept-cap` | SEA accepts the CAP; the last terminal finding auto-closes the visit | SEAMonitor |
| POST | `/title-i/monitoring-findings/{id}/return-cap` | SEA returns the CAP for rework | SEAMonitor |
| POST | `/title-i/monitoring-findings/{id}/close-no-action` | SEA closes an OBSERVATION-severity finding without corrective action | SEAMonitor |
| POST | `/title-i/_clock/set_current_utc` | Set the server's logical clock and run the finding-escalation sweep | FederalProgramsDirector |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the identifier reference.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NARRATIVE_TOO_SHORT` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_DUPLICATE_FISCAL_YEAR` | 409 Conflict |
| `ERR_DUPLICATE_SCHOOL_ENTRY` | 400 Bad Request |
| `ERR_DUPLICATE_CONSULTATION` | 409 Conflict |
| `ERR_GRANT_INVALID_STATE` | 409 Conflict |
| `ERR_SNAPSHOT_NOT_CERTIFIABLE` | 409 Conflict |
| `ERR_NO_CERTIFIED_SNAPSHOT` | 409 Conflict |
| `ERR_ALLOCATION_NOT_PENDING` | 409 Conflict |
| `ERR_ALLOCATION_NOT_CERTIFIED` | 409 Conflict |
| `ERR_SNS_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_SNS_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_CONSULTATION_INVALID_STATE` | 409 Conflict |
| `ERR_INSUFFICIENT_CONSULTATION_SESSIONS` | 409 Conflict |
| `ERR_EXPENDITURE_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_EXPENDITURE_NOT_RECLASSIFIABLE` | 409 Conflict |
| `ERR_AMENDMENT_INVALID_STATE` | 409 Conflict |
| `ERR_VISIT_INVALID_STATE` | 409 Conflict |
| `ERR_VISIT_NOT_ACCEPTING_FINDINGS` | 409 Conflict |
| `ERR_FINDING_INVALID_STATE` | 409 Conflict |
| `ERR_WAIVER_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_GRANT_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_SUPPLANT_RISK_UNRESOLVED` | 403 Forbidden |
| `ERR_OPEN_FINDINGS_BLOCK_CLOSEOUT` | 409 Conflict |
| `ERR_SNAPSHOT_INCOMPLETE_COVERAGE` | 422 Unprocessable Entity |
| `ERR_PRIVATE_SCHOOL_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_CONSULTATION_INCOMPLETE` | 409 Conflict |
| `ERR_CHARGE_TARGET_AMBIGUOUS` | 400 Bad Request |
| `ERR_FUNCTION_TARGET_MISMATCH` | 400 Bad Request |
| `ERR_SCHOOL_LOCKED_BY_SNAPSHOT` | 409 Conflict |
| `ERR_COST_OUTSIDE_FISCAL_PERIOD` | 422 Unprocessable Entity |
| `ERR_SESSION_DATE_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_VISIT_WINDOW_MISSED` | 409 Conflict |
| `ERR_MONITORING_VISIT_OVERLAP` | 409 Conflict |
| `ERR_SNS_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SET_ASIDE_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_AMENDMENT_NOT_NET_ZERO` | 400 Bad Request |
| `ERR_AMENDMENT_BELOW_LIQUIDATED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_ALLOCATION_BALANCE` | 402 Payment Required |
| `ERR_CARRYOVER_WITHIN_LIMIT` | 409 Conflict |
| `ERR_CARRYOVER_WAIVER_WITHIN_3_YEARS` | 409 Conflict |
| `ERR_CARRYOVER_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_UNRESOLVED_EXPENDITURES` | 409 Conflict |
| `ERR_UNRESOLVED_AMENDMENTS` | 409 Conflict |
