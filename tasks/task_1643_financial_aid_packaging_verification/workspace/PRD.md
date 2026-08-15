# Financial Aid Packaging & Verification API — Product Requirements Document

## 1. Introduction

A university financial aid office operates under unforgiving constraints: federal Title IV rules determine who may receive which dollars, every award decision must be reconstructible in an audit, and a single mistimed disbursement can trigger an over-award liability that follows the institution for years. This document specifies the Financial Aid Packaging & Verification API, a deterministic service that carries an aid year from initial setup through FAFSA/ISIR import, need analysis, verification casework, professional judgment, award packaging, student acceptance, disbursement, over-award cure, and year-end reconciliation against federal systems.

Two design commitments shape everything that follows. First, every figure the office relies on — the expected family contribution, the Pell schedule lookup, the Stafford caps, the satisfactory-academic-progress pace, the packaging waterfall — is computed by a fixed, reproducible rule with pinned rounding order, so that two independent evaluations of the same data always agree to the cent. Second, the office's segregation-of-duties obligations are enforced structurally: the officer who opens a conflicting-information case may not be the one who resolves it, and the officer who reviews a professional judgment case may not decide it. The API mounts all resources under `/api` and speaks JSON exclusively.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's operational capacity. A request missing either header, or presenting an `X-User-Role` value that is not one of the declared role names, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

The system recognizes exactly three roles, spelled exactly as follows:

- `AidDirector` — the senior financial aid director. Owns the aid-year lifecycle, fund setup and activation, professional judgment decisions, SAP appeals, verification waivers, revision decisions, over-award verification, reconciliation, and the logical clock.
- `AidOfficer` — the financial aid counselor who runs day-to-day operations: student registration, ISIR import, verification processing, conflict substantiation, packaging, and disbursement operations.
- `Student` — the aid applicant, who may view their own records and act on their own award package (accept, decline, request revision) and acknowledge their own notifications.

When `X-User-Role` is `AidDirector` or `AidOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `opened_by_user_id` on a ConflictingInfoCase, as `reviewed_by_user_id` or `decided_by_user_id` on a ProfessionalJudgmentCase, or as `resolved_by_user_id` on a ConflictingInfoCase — but it never compares that value to any entity's `id`. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting Student; ownership checks on any resource that references a Student compare the resource's foreign-key field — concretely, the package's `student_id` — to `X-User-ID`.

An authenticated caller whose role is not listed among an endpoint's authorized roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

All seventeen resource types — AidYear, FundType, Student, ISIRRecord, VerificationCase, VerificationDocument, ConflictingInfoCase, ProfessionalJudgmentCase, AwardPackage, AwardLine, AwardNotification, RevisionRequest, Disbursement, OverawardCase, ExternalAid, ReconciliationRun, and ReconciliationAdjustment — share one set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a bare UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on any modification of the resource's properties.
- `version` (integer): a system-managed counter that increments with every modification, including recomputation of a derived aggregate such as a pool total.

No entity in this system omits `updated_at` or `version`; the audit trail is uniform.

### 2.5. Monetary Precision and Rounding

Every monetary quantity in the system — costs of attendance, incomes, award amounts, pool budgets, disbursements, reconciliation figures — is represented as an integer number of cents, in both storage and API payloads. Three rounding disciplines are used, each pinned to a specific calculation and never interchangeable: rounding half-up to whole cents (each EFC income tier product, and the EFC per-college-member division); floor rounding to whole cents (the EFC asset contribution and the Pell enrollment proration); and integer floor division in basis points (the SAP pace). Any rule below that names one of these disciplines must be implemented with exactly that discipline at exactly that step.

### 2.6. The Logical Clock

All notions of "now" in the system — the receipt-window check on ISIR import, the `sent_at` stamp on a notification, the `completed_at` stamp on a verification case — read from a server-held logical clock, never from wall-clock time. Before any clock-setting call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z, and the server must not fall back to wall-clock time under any circumstances. An `AidDirector` may advance or set the clock through a test-driving capability that accepts a `to_iso8601` instant and reports the resulting `current_utc` in its response.

### 2.7. Validation Order and Error Precedence

Every request is validated against an ordered ladder of eighteen checks. The checks are evaluated in the priority order given below, so an earlier failure masks later ones — for example, an unauthenticated caller always sees `ERR_UNAUTHENTICATED` even if the request would also have failed a downstream business rule. The ladder is:

1. **Authentication** (all endpoints): `X-User-Role` and `X-User-ID` are present and `X-User-Role` is a declared role name — otherwise `ERR_UNAUTHENTICATED` (401).
2. **Role authorization** (all endpoints): the caller's role is listed in the endpoint's authorized roles — otherwise `ERR_FORBIDDEN_ROLE` (403).
3. **Path existence** (all endpoints): every identifier in the path references an existing entity, validated left-to-right (aid year, then student, then package, then line, then child resource) — otherwise `ERR_NOT_FOUND` (404).
4. **Body references** (creation endpoints whose bodies carry foreign keys): every foreign key in the request body, such as `fund_type_id` on award-line creation or `student_id` on ISIR import, references an existing entity — otherwise `ERR_REFERENCE_NOT_FOUND` (404).
5. **State-machine legality** (all action endpoints): the target entity's state machine permits the requested transition from its current state — otherwise `ERR_INVALID_STATE` (409).
6. **Parent-aggregate state gate** (`POST /api/award-packages/{id}/build`, `POST /api/award-lines/{id}/begin-disbursement`, `POST /api/disbursements`, `POST /api/isir-records`): the AidYear must be `OPEN` for a packaging build, the AwardPackage must be `LOCKED` for begin-disbursement, and the AidYear must not be `CLOSED` for any student-level write — otherwise `ERR_PARENT_STATE_BLOCKS` (409).
7. **Segregation of duties** (`POST /api/conflicting-info-cases/{id}/resolve`, `POST /api/conflicting-info-cases/{id}/resolve-requires-correction`, `POST /api/pj-cases/{id}/approve`, `POST /api/pj-cases/{id}/deny`): the resolving caller on a conflicting-information case must differ from `opened_by_user_id`, and the deciding caller on a professional judgment case must differ from `reviewed_by_user_id` — otherwise `ERR_SEGREGATION_OF_DUTIES` (403).
8. **Student ownership** (`POST /api/award-packages/{id}/accept`, `POST /api/award-packages/{id}/decline`, `POST /api/award-packages/{id}/revision-requests`, `POST /api/award-notifications/{id}/acknowledge`): a Student-role caller may act only on their own package or notification, meaning `X-User-ID` equals the package's `student_id` — otherwise `ERR_NOT_RESOURCE_OWNER` (403).
9. **Request shape** (all endpoints): required fields are present and well-typed, strings required to be non-empty are non-empty, enum values are members of their declared sets, and integers are in range — otherwise `ERR_INVALID_REQUEST` (400).
10. **Field-level domain constraints** (`POST /api/isir-records`, `POST /api/aid-years`, `POST /api/students`, `POST /api/pj-cases`): household-size floors by dependency status, `number_in_college` not exceeding `household_size`, out-of-state cost of attendance strictly above in-state, the sign of `requested_delta_cents` matching its `adjustment_type`, and `cumulative_completed_credits` not exceeding `cumulative_attempted_credits` — otherwise `ERR_FIELD_CONSTRAINT` (422).
11. **Uniqueness** (`POST /api/students`, `POST /api/fund-types`, `POST /api/isir-records`, `POST /api/award-packages`): `ssn` unique across students, `email` unique across students, `fund_code` unique within an aid year, the (`student_id`, `aid_year_id`, `transaction_number`) triple unique across ISIR records, and at most one AwardPackage per (`student_id`, `aid_year_id`) — otherwise `ERR_DUPLICATE` (409).
12. **Receipt window** (`POST /api/isir-records`): `received_at` must be at or before the current logical-clock reading and no earlier than one year before the aid year's own `created_at` — otherwise `ERR_RECEIVED_AT_OUT_OF_WINDOW` (422).
13. **Cross-entity prerequisites** (`POST /api/award-packages/{id}/build`, `POST /api/isir-records`, `POST /api/fund-types/{id}/activate`): a packaging build requires a current ISIR record for the student and aid year, an ISIR import requires the aid year to be `OPEN`, and fund activation requires the aid year to be `DRAFT` or `OPEN` — otherwise `ERR_PREREQUISITE_MISSING` (422).
14. **Optimistic concurrency** (`POST /api/award-packages/{id}/lock`, `POST /api/pj-cases/{id}/approve`): the request's expected-version field must equal the entity's current `version` — otherwise the stale-version error of §2.9 (412).
15. **Pool sufficiency on repack** (`POST /api/revision-requests/{id}/approve`): a repack may not push any non-PELL fund's `pool_reserved_cents` above its `pool_budget_cents` — otherwise `ERR_FUND_POOL_EXHAUSTED` (422).
16. **Over-award gate at acceptance** (`POST /api/award-packages/{id}/accept`): when an OverawardCase for the student and aid year is `OPEN` or `RESOLVING` and the offered-total-based detection still exceeds the cost of attendance, acceptance is refused — `ERR_OVERAWARD_UNRESOLVED` (422); the student must wait for resolution.
17. **Disbursement schedule amount** (`POST /api/disbursements`): `scheduled_cents` must be positive and no greater than the line's remaining headroom, the line must be `DISBURSING`, and the package must be `LOCKED` — otherwise `ERR_DISBURSEMENT_AMOUNT` (422).
18. **Reconciliation arithmetic** (`POST /api/reconciliation-runs/{id}/adjustments`): the sum of `adjust_cents` over all of a run's adjustment rows plus `internal_posted_cents` must equal `federal_reported_cents` — otherwise `ERR_VARIANCE_NOT_ZEROED` (422).

### 2.8. Nested Resource Retrieval

Requests that target nested resources are validated left-to-right along the path: the aid year first, then the student, then the package, then the line, then the child resource. The request is rejected with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing entity, before any later identifier is examined and before any business rule runs — per precedence rung 3 of §2.7, existence always precedes state and business validation.

### 2.9. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, and they are the only operations that take a version field:

- **Package lock.** A request to lock an award package must carry `expected_package_version`, holding the package `version` the client last observed. If the package's current `version` has advanced since that observation — for example because a per-line acceptance released pool reservations and bumped the version — the lock is rejected with `ERR_STALE_PACKAGE_VERSION` (HTTP 412), preventing the client from locking a package it has not observed.
- **Professional judgment approval.** A request to approve a professional judgment case must carry `expected_pj_version`, holding the case `version` the client last observed. If the case's current `version` has advanced since that observation — for example because another writer denied the case — the approval is rejected with `ERR_STALE_PJ_VERSION` (HTTP 412).

Endpoints not named here do not take a version field.

### 2.10. Fund Pool Accounting and Aid-Year Aggregates

The office's fiscal controls rest on four derived aggregates, each recomputed immediately when its inputs change. A FundType's `pool_reserved_cents` is the sum of `offered_cents` over its award lines whose status is `OFFERED`, `ACCEPTED`, `PARTIALLY_ACCEPTED`, `DISBURSING`, or `DISBURSED`, recomputed on every line transition into or out of that set and on any change to `offered_cents`; lines that are `DECLINED`, `CANCELLED`, or `RETURNED` no longer reserve pool. A FundType's `pool_disbursed_cents` is the sum of `disbursed_cents` over `POSTED` disbursements against its lines. An AidYear's `total_packaged_cents` is the same reserved-style sum taken across every award line of every package belonging to the aid year, recomputed on every AwardLine mutation; its `total_disbursed_cents` is the sum of `disbursed_cents` over `POSTED` disbursements of the aid year, recomputed on every disbursement transition into `POSTED` or `RETURNED`.

A non-PELL fund whose `pool_reserved_cents` reaches or exceeds its `pool_budget_cents` is automatically transitioned from `ACTIVE` to `EXHAUSTED` after the AwardLine mutation that caused it, with its `version` incremented; should a later mutation reduce `pool_reserved_cents` below `pool_budget_cents`, the fund automatically returns from `EXHAUSTED` to `ACTIVE`. The fund whose `fund_code` is `PELL` is exempt from this machinery entirely: Pell is treated as an entitlement, its pool check is skipped during packaging, and it never becomes `EXHAUSTED`.

## 3. Business Logic & Workflows

### 3.1. Aid Year Setup and Fund Configuration

An aid cycle begins when an `AidDirector` creates an AidYear, supplying a `year_code` such as `2026-2027`, the in-state cost of attendance `coa_in_state_cents` and the out-of-state figure `coa_out_of_state_cents` (both strictly positive, and the out-of-state figure strictly greater than the in-state figure, or the creation fails with `ERR_FIELD_CONSTRAINT`), a `priority_deadline` timestamp, a `pell_schedule`, and a `verification_tracking_flag_rate`. The deadline fixes the priority cohort boundary described in §3.3. The `verification_tracking_flag_rate` is a fraction greater than 0 and at most 1 governing what share of imported ISIRs the institution flags for verification on its own initiative.

The `pell_schedule` is an array of rows, each carrying `efc_min`, `efc_max`, and `award_cents`. The rows must be sorted by `efc_min` ascending, must be contiguous with no gaps or overlaps, and must collectively cover the inclusive range from 0 to 999,999 — the schedule is validated for this shape when the aid year is opened. An EFC is looked up as the single row whose inclusive `[efc_min, efc_max]` range contains it. The new AidYear starts in `DRAFT`, and its `status` will walk `DRAFT` → `OPEN` → `PACKAGING_LOCKED` → `RECONCILING` → `CLOSED`, with `CLOSED` terminal. Aid years may be listed with pagination and an optional `status` filter, and fetched individually with their computed totals.

Within the aid year, the director defines FundTypes. Each fund carries its `aid_year_id`, a short `fund_code` — conventional codes include `PELL`, `SEOG`, `SUB`, `UNSUB`, `PLUS`, `INST_GRANT`, and `WORK_STUDY` — unique within its aid year (a repeat yields `ERR_DUPLICATE`), a `category` of `FEDERAL_TITLE_IV`, `INSTITUTIONAL`, `STATE`, or `EXTERNAL`, a `need_based` flag, an `annual_cap_cents` per-student maximum that must be strictly positive, and a `pool_budget_cents` pool total that must be zero or positive. When `need_based` is true the fund's offer is constrained by the student's remaining need; when false it is constrained only by the remaining cost-of-attendance gap. Three further switches shape packaging: `priority_cohort_only` (default false) restricts the fund to students whose ISIR is in the `PRIORITY` cohort; `packaging_rank` fixes the fund's position in the packaging waterfall and must be unique within the aid year, with ties in evaluation order broken by `fund_code` ascending; and `requires_verification_complete` (default true) bars the fund from being offered while the student's verification case is unresolved.

A fund is created in `DRAFT` and moves to `ACTIVE` when the director activates it, which is permitted only while the parent aid year is `DRAFT` or `OPEN` — attempting activation under any other aid-year state is rejected with `ERR_PREREQUISITE_MISSING` — and which increments both the fund's `version` and the aid year's `version`. From `ACTIVE` a fund may auto-transition to `EXHAUSTED` and back per §2.10, and both `ACTIVE` and `EXHAUSTED` funds are cascaded to `CLOSED` when the aid year closes. Funds can be listed with `aid_year_id` and `status` filters or browsed as a sub-resource of their aid year, and a single fund fetch exposes the live pool aggregates.

Opening the aid year is itself a guarded transition: the director may move the AidYear from `DRAFT` to `OPEN` only when the `pell_schedule` is non-empty, contiguous, and covers the full range from 0 to 999,999, and when at least one fund under the aid year is already `ACTIVE`; the transition increments the aid year's `version`. Later, the director may move `OPEN` to `PACKAGING_LOCKED` only when every award package under the aid year has reached `NOTIFIED`, `PARTIALLY_ACCEPTED`, `ACCEPTED`, `DECLINED`, or `LOCKED` — no `DRAFT`, `PACKAGED`, or `REVISION_REQUESTED` package may remain — and this transition likewise increments `version`.

### 3.2. Student Registration and Satisfactory Academic Progress

An `AidOfficer` registers each applicant as a Student with a nine-digit `ssn` stored as nine digits with no separators, a `full_name`, a unique notification `email`, a `residency` of `IN_STATE` or `OUT_OF_STATE` (which selects the cost-of-attendance figure used in need analysis), a `dependency_status` of `DEPENDENT` or `INDEPENDENT` as reported on the FAFSA, an `enrollment_status` of `FULL_TIME`, `THREE_QUARTER`, `HALF_TIME`, or `LESS_THAN_HALF`, and an integer `grade_level` from 1 to 5 that drives the Stafford caps of §3.6. Registering a duplicate `ssn` or `email` fails with `ERR_DUPLICATE`. Four academic inputs carry defaults: `cumulative_attempted_credits` and `cumulative_completed_credits` default to 0, `max_timeframe_credits` defaults to 180 (one hundred fifty percent of a typical program length), and `gpa_hundredths` — the cumulative GPA multiplied by one hundred, so 250 means 2.50 — defaults to 0; the completed figure may never exceed the attempted figure (`ERR_FIELD_CONSTRAINT`). A student's `sap_status` begins at `NOT_EVALUATED`. An officer may later update the mutable attributes — `enrollment_status`, `grade_level`, `residency`, `cumulative_attempted_credits`, `cumulative_completed_credits`, `gpa_hundredths`, and `max_timeframe_credits` — through a modification that increments the student's `version`. Students may be listed with `sap_status` and `enrollment_status` filters.

Satisfactory Academic Progress is evaluated on demand by an `AidOfficer`, and the evaluation has two variants selected by a single optional request field. When `transfer_credits` is omitted or zero, the STANDARD variant runs and only the student's as-reported cumulative credits are used. When `transfer_credits` is greater than zero, the TRANSFER variant runs: the transfer credits are added to both the attempted and the completed figures before the pace division, which can flip a failing pace to passing — thirty completed of forty-five attempted yields 6,666 basis points and fails, while adding twelve transfer credits to both figures yields forty-two of fifty-seven, or 7,368 basis points, which passes.

Three gates are then applied. The qualitative gate passes when `gpa_hundredths` is at least 200. The quantitative pace is computed in basis points: effective completed credits multiplied by ten thousand, divided by effective attempted credits using integer division (so the quotient is floored); if effective attempted credits are zero, the pace is treated as the full ten thousand basis points. The pace passes when it is at least 6,667 basis points, that is, 66.67 percent. The maximum-timeframe gate fails when `cumulative_attempted_credits` exceeds `max_timeframe_credits`.

The new `sap_status` is mapped from the outcome and the prior value. If all three gates pass and the prior status is `NOT_EVALUATED`, `GOOD_STANDING`, or `WARNING`, the student becomes `GOOD_STANDING`. If all gates pass but the prior status is `SUSPENDED`, the student remains `SUSPENDED` — only a director's appeal lifts a suspension. If any gate fails and the prior status is `NOT_EVALUATED` or `GOOD_STANDING`, the student drops to `WARNING`. If any gate fails and the prior status is `WARNING` or `APPEAL_APPROVED`, the student drops to `SUSPENDED`. The evaluation sets `sap_status` and increments the student's `version`. Separately, an `AidDirector` may grant a SAP appeal by supplying an `appeal_reason`, moving a `SUSPENDED` student to `APPEAL_APPROVED` — the only path into that state — and incrementing `version`.

### 3.3. ISIR Import, Cohort Assignment, and Need Analysis

When a FAFSA transaction arrives, an `AidOfficer` imports an ISIR record carrying the `student_id`, the `aid_year_id`, a `transaction_number` that starts at 1 and increments with each correction (unique within the student-and-aid-year pair, so a repeated triple fails with `ERR_DUPLICATE`), a `received_at` receipt stamp, `household_size`, `number_in_college`, `agi_cents`, `untaxed_income_cents`, `asset_net_worth_cents`, and an optional `cps_selection_flag` that defaults to false. Import is only possible while the aid year is `OPEN`; otherwise it fails with `ERR_PREREQUISITE_MISSING` — and, per the parent-state gate, never once the aid year is `CLOSED` (`ERR_PARENT_STATE_BLOCKS`). The receipt stamp must satisfy the window of precedence rung 12: at or before the logical clock and no earlier than one year before the aid year's `created_at`, else `ERR_RECEIVED_AT_OUT_OF_WINDOW`. Household fields are checked against dependency: `household_size` must be at least 2 for a `DEPENDENT` student and at least 1 for an `INDEPENDENT` student, `number_in_college` must be at least 1 and no more than `household_size`, and the three money fields must be non-negative — violations fail with `ERR_FIELD_CONSTRAINT`.

An imported record is born in the `IMPORTED` stage of its lifecycle and immediately becomes `CURRENT` when no other record for the same student and aid year carries a higher `transaction_number`; exactly one record per student-and-year is current at any time, surfaced through the boolean `is_current`. When a newer transaction is later imported, the older record is superseded — it moves to the terminal `SUPERSEDED` stage and its `is_current` flips to false — while the newcomer becomes current. Becoming current fixes two things permanently. The `cohort` is set to `PRIORITY` when `received_at` is on or before the aid year's `priority_deadline` and to `STANDARD` otherwise; it is fixed at import and never recomputed even if the deadline later changes. And `verification_selection` is set to `SELECTED` when `cps_selection_flag` is true or when the institution's deterministic selection fires, and to `NOT_SELECTED` otherwise. The deterministic selection computes the SHA-256 digest of the concatenation of the student's `ssn`, a hyphen, and the aid-year code, reduces the digest modulo ten thousand, and flags the record when that residue is strictly less than the `verification_tracking_flag_rate` multiplied by ten thousand. Whenever selection is `SELECTED`, a VerificationCase is opened in `DOCUMENTS_REQUESTED` (§3.4); if the student's earlier case sits in `COMPLETED_CORRECTION_SENT`, the newly selected import loops that case back to `DOCUMENTS_REQUESTED`, and if the earlier case was `COMPLETED_SATISFIED`, the newly selected import likewise returns it to `DOCUMENTS_REQUESTED` for re-verification. The register of ISIR records can be listed with `student_id`, `aid_year_id`, and `is_current` filters.

Import also computes the Expected Family Contribution. The EFC exists in three fields on the record: `efc_provisional_cents`, computed at import from as-reported data; `efc_verified_cents`, which stays null (serializing as null) until verification completes satisfied; and `efc_official_cents`, the figure packaging actually uses — the verified figure once the linked verification case is `COMPLETED_SATISFIED`, and the provisional figure otherwise. Both EFC variants run the same seven-step simplified federal methodology; the PROVISIONAL variant reads the as-reported import values, while the VERIFIED variant reads the verified values from accepted documents and therefore diverges whenever an accepted document changed `agi_cents`, `untaxed_income_cents`, `asset_net_worth_cents`, `household_size`, or `number_in_college`.

The seven steps are pinned. Step one sums `agi_cents` and `untaxed_income_cents` into a total income. Step two looks up the income protection allowance from two fixed tables, indexed by `dependency_status` and by household size capped at five (a household of five or more uses the fifth entry): for a `DEPENDENT` student the allowance is 1,000,000 cents for a household of one, 1,500,000 for two, 2,000,000 for three, 2,400,000 for four, and 2,800,000 for five or more; for an `INDEPENDENT` student the five entries are 1,700,000, 2,200,000, 2,600,000, 3,000,000, and 3,300,000 cents. Step three subtracts the allowance from total income, floored at zero, yielding available income. Step four applies tiered marginal rates to available income: the first 500,000 cents at 22 percent, the portion above 500,000 up to 1,500,000 cents at 35 percent, and any remainder above 1,500,000 cents at 47 percent — with each tier's product rounded half-up to whole cents before the tiers are summed, that rounding order being pinned. Step five derives the asset contribution: when `asset_net_worth_cents` exceeds the asset allowance of 1,000,000 cents, the contribution is the floor of the excess over that allowance multiplied by 5.64 and divided by 100; otherwise the contribution is zero. Step six adds the income and asset contributions and divides by `number_in_college` using integer division that rounds half-up. Step seven clamps the result to never fall below 0 and never exceed 99,999,900 cents.

### 3.4. Verification and Conflicting-Information Casework

A VerificationCase is opened automatically for a selected ISIR, linked to that record through `isir_id`, stamped with the `tracking_group` `V1`, and created in `DOCUMENTS_REQUESTED` with three required VerificationDocument rows — `TAX_RETURN_TRANSCRIPT`, `W2`, and `HOUSEHOLD_FORM` — each bound to its case through `verification_case_id` and starting in `REQUESTED`. A document's `doc_type` may also be `IDENTITY_STATEMENT` or `OTHER` for supplementary requests. The case's `status` then walks a cyclic machine: `DOCUMENTS_REQUESTED` → `DOCUMENTS_RECEIVED` → `UNDER_REVIEW`, then either `COMPLETED_SATISFIED` or `COMPLETED_CORRECTION_SENT`; a correction-sent case loops back to `DOCUMENTS_REQUESTED` when the corrected ISIR arrives selected; a case under review can be returned to `DOCUMENTS_REQUESTED` for more documents; and any of the three non-terminal states can be overridden to `WAIVED` by a director. `COMPLETED_SATISFIED` and `WAIVED` are terminal. Cases may be listed with `student_id`, `aid_year_id`, and `isir_id` filters.

Document handling is officer work. Marking a `REQUESTED` document received moves it to `RECEIVED` and stamps `received_at` from the logical clock; from `RECEIVED` the officer either accepts it, moving it to the terminal `ACCEPTED`, or rejects it, moving it to `REJECTED` with a mandatory non-empty `rejection_reason`. A rejected document can be sent back for resubmission, returning from `REJECTED` to `REQUESTED`: its `received_at` is cleared while the prior `rejection_reason` is retained as history. Each time a document lands in `RECEIVED` or `ACCEPTED`, the parent case re-evaluates its auto-advance: when the count of required document types whose status is `RECEIVED` or `ACCEPTED` reaches 3 — all of `TAX_RETURN_TRANSCRIPT`, `W2`, and `HOUSEHOLD_FORM` for `V1` — the case moves itself from `DOCUMENTS_REQUESTED` to `DOCUMENTS_RECEIVED`, incrementing its `version`.

Once the case is `DOCUMENTS_RECEIVED`, an `AidOfficer` begins review, moving it to `UNDER_REVIEW` (incrementing `version`). From there the officer has three exits. Requesting additional documents returns the case to `DOCUMENTS_REQUESTED`: the `doc_types` named in the request are created or reset to `REQUESTED`, with the `rejection_reason` preserved on any previously rejected rows. Completing with a correction moves the case to `COMPLETED_CORRECTION_SENT` — permitted when at least one required document type has been `ACCEPTED` and a non-empty `resolution_notes` is supplied — recording that the corrected values will arrive later as a new ISIR transaction. Completing satisfied moves the case to `COMPLETED_SATISFIED` and carries the heaviest preconditions: the case must be `UNDER_REVIEW`, every required document type must be `ACCEPTED` (otherwise `ERR_VERIFICATION_DOCS_INCOMPLETE`), a non-empty `resolution_notes` must be supplied, and no ConflictingInfoCase for the same student and aid year may sit in `OPEN`, `SUBSTANTIATED`, or `RESOLVED_REQUIRES_CORRECTION` (otherwise `ERR_CONFLICTING_INFO_OPEN`).

Completing satisfied is where the VERIFIED EFC variant fires. The request may carry `verified_agi_cents`, `verified_untaxed_income_cents`, `verified_asset_net_worth_cents`, `verified_household_size`, and `verified_number_in_college`; any of these omitted defaults to the as-reported import value. The verified figures recompute the seven-step EFC of §3.3, the result is stored as `efc_verified_cents` on the linked ISIR record, and `efc_official_cents` is set to that verified figure. The case's `completed_at` is stamped and its `version` increments. If the new official EFC diverges from the snapshot frozen on an award package sitting in `NOTIFIED`, `PARTIALLY_ACCEPTED`, or `ACCEPTED`, that package's `needs_repack` flag is set true — observed on the next packaging action — while its existing lines are deliberately left untouched.

A director may instead waive verification from `DOCUMENTS_REQUESTED`, `DOCUMENTS_RECEIVED`, or `UNDER_REVIEW`, supplying a non-empty `waived_reason`. Waiving stamps `completed_at`, increments `version`, and lets the provisional figure stand: the linked record's `efc_official_cents` is set to its `efc_provisional_cents`.

Conflicting information runs on a parallel track, because federal rules forbid completing verification while a conflict is unresolved. An `AidOfficer` opens a ConflictingInfoCase with the `student_id`, the `aid_year_id`, the `subject_field` under dispute (for example `agi_cents`, `household_size`, or `dependency_status`), and, for numeric subjects, the `claimed_value_cents` asserted by the conflicting document or third-party statement (null for non-numeric subjects). The opener's `X-User-ID` is captured into `opened_by_user_id` at creation. From `OPEN` the case forks: substantiating moves it to `SUBSTANTIATED`, unsubstantiating to `UNSUBSTANTIATED`, both officer actions that increment `version`. A substantiated case moves to `RESOLVED_REQUIRES_CORRECTION` with a non-empty `resolution`; an unsubstantiated case moves straight to `RESOLVED` with a non-empty `resolution`. Both resolving transitions stamp `resolved_by_user_id` and enforce segregation of duties — the resolving caller must not be the user recorded in `opened_by_user_id`, or the request fails with `ERR_SEGREGATION_OF_DUTIES`. A case in `RESOLVED_REQUIRES_CORRECTION` closes itself to the terminal `RESOLVED` only when a new current ISIR is imported whose value for the `subject_field` equals the claimed value (the `claimed_value_cents` for numeric subjects).

### 3.5. Professional Judgment Adjustments

Special circumstances are handled through a ProfessionalJudgmentCase, submitted by an `AidOfficer` with the `student_id`, the `aid_year_id`, an `adjustment_type`, a signed `requested_delta_cents`, a narrative `justification` of at least twenty characters, and a `documentation_complete` attestation that defaults to false. The `adjustment_type` is one of `EFC_ADJUSTMENT` (recompute the EFC with adjusted inputs), `COA_ADJUSTMENT` (raise the cost of attendance), or `DEPENDENCY_OVERRIDE` (flip the dependency status), and the delta's sign must match: an EFC adjustment may only lower the EFC, so its delta must be zero or negative; a COA adjustment's delta must be strictly positive; a dependency override's delta must be exactly zero — sign violations fail with `ERR_FIELD_CONSTRAINT`.

The case is born `SUBMITTED`. An `AidOfficer` begins review, moving it to `UNDER_REVIEW` and capturing the caller's `X-User-ID` into `reviewed_by_user_id`. The decision belongs to an `AidDirector` and is segregated: the deciding caller must differ from `reviewed_by_user_id` on both approval and denial, or the request fails with `ERR_SEGREGATION_OF_DUTIES`. Denial simply records `decided_by_user_id` and lands the case in the terminal `DENIED`. Approval is guarded more heavily. The case must be `UNDER_REVIEW`; `documentation_complete` must be true; for an `EFC_ADJUSTMENT` the non-positive delta must also leave the current ISIR's `efc_official_cents` at zero or above once applied; for a `COA_ADJUSTMENT` the delta must be positive; and for a `DEPENDENCY_OVERRIDE` the student must currently be `DEPENDENT`. Approval is also one of the two optimistic-concurrency operations of §2.9: the request must carry `expected_pj_version` equal to the case's current `version`, else it is rejected with `ERR_STALE_PJ_VERSION` (412).

An approved case takes effect immediately and durably. The `decided_by_user_id` is recorded; for an EFC adjustment `applied_efc_delta_cents` is set to the requested delta (it is zero for the other types), and for a COA adjustment `applied_coa_delta_cents` is set to the requested delta (likewise zero otherwise); a dependency override flips the student's `dependency_status` to `INDEPENDENT`. Both the case's `version` and the student's `version` increment. If the approval shifts the official EFC or the COA deltas relative to the frozen snapshots of a package in `NOTIFIED`, `PARTIALLY_ACCEPTED`, or `ACCEPTED`, that package's `needs_repack` flag is set true. The approved deltas are then consumed at the next packaging run, as §3.6 describes. Cases are listed with `student_id`, `aid_year_id`, and `status` filters.

### 3.6. Packaging, Notification, Acceptance, and Revision

Packaging begins with a shell: an `AidOfficer` creates an AwardPackage for a `student_id` and `aid_year_id`, at most one per student per aid year (a second attempt fails with `ERR_DUPLICATE`), born in `DRAFT`. Building the package — `DRAFT` → `PACKAGED` — is permitted only while the aid year is `OPEN` (otherwise `ERR_PARENT_STATE_BLOCKS`) and only when a current ISIR record exists for the student and year (otherwise `ERR_PREREQUISITE_MISSING`). The build runs the packaging waterfall, whose evaluation order is pinned end to end:

1. **Snapshots.** `coa_used_cents` is the residency-selected cost of attendance — `coa_in_state_cents` for `IN_STATE`, `coa_out_of_state_cents` for `OUT_OF_STATE` — plus the sum of `applied_coa_delta_cents` over the student's `APPROVED` professional judgment cases for the aid year. `efc_used_cents` is the current ISIR's `efc_official_cents` minus the sum of `applied_efc_delta_cents` over those approved cases, floored at zero. `need_cents` is the cost snapshot minus the EFC snapshot, floored at zero, and is recomputed whenever the package is rebuilt.
2. **Candidate order.** The funds considered are the aid year's `ACTIVE` FundTypes, taken in ascending `packaging_rank` with ties broken by `fund_code` ascending.
3. **Per-fund eligibility and offer, in order.** First, a fund with `priority_cohort_only` true is skipped unless the current ISIR's `cohort` is `PRIORITY`. Second, a fund with `requires_verification_complete` true is skipped unless the student has no verification case at all (a `NOT_SELECTED` outcome) or the case is `COMPLETED_SATISFIED` or `WAIVED`. Third, the base offer is computed: for `PELL`, the schedule lookup described below; for `SUB` and `UNSUB`, the Stafford caps described below; for any other fund, the smaller of `annual_cap_cents` and the running remaining need for a `need_based` fund or the running remaining cost-of-attendance gap otherwise. Fourth, the pool check for every fund except `PELL`: the offer is capped at `pool_budget_cents` minus `pool_reserved_cents`, and the fund is skipped entirely when that leaves zero or less; `PELL` skips the pool check as an entitlement.
4. **Accumulators, updated after each fund's offer is fixed.** The remaining need starts at `need_cents` and is reduced, floored at zero, by each `need_based` fund's offer. The remaining cost-of-attendance gap starts at `coa_used_cents` and is reduced, floored at zero, by every fund's offer, gift or loan. The package's `gift_aid_cents` accumulates offers of funds that are `need_based` and not loan funds — that is, whose `fund_code` is none of `SUB`, `UNSUB`, or `PLUS`.
5. **Line creation.** One AwardLine is created per fund whose final offer is greater than zero, with `offered_cents` set to that offer, `accepted_cents` and `disbursed_cents` starting at zero, status `OFFERED`, and a `sequence_number` assigned in evaluation order starting at 1. A fund whose offer is zero produces no line at all.

The Pell lookup inside step three reads the aid year's `pell_schedule` and finds the single row whose inclusive boundaries satisfy `efc_min` at or below the package's `efc_used_cents` and `efc_max` at or above it; that row's `award_cents` is the pre-proration offer. Enrollment proration then applies: `FULL_TIME` pays one hundred percent, `THREE_QUARTER` pays seventy-five percent, `HALF_TIME` pays fifty percent, and `LESS_THAN_HALF` pays zero — the Pell offer is the floor of the row's `award_cents` multiplied by the proration percentage and divided by one hundred.

The Stafford caps inside step three are fixed by `grade_level` and `dependency_status`. The annual `SUB` cap is 350,000 cents at grade level one, 450,000 at level two, and 550,000 at levels three, four, and five — and the `SUB` caps for `INDEPENDENT` students are identical to those for `DEPENDENT` students at every level. The `UNSUB` cap for a `DEPENDENT` student is a flat 200,000 cents at every level from one through five, while an `INDEPENDENT` student may receive 600,000 cents at levels one and two and 700,000 at levels three, four, and five. `SUB` is need-based: its offer is the smaller of its cap and the running remaining need. `UNSUB` is not: its offer is the smaller of its cap and the running remaining cost-of-attendance gap.

A build leaves heavy footprints: the child lines are created with their `sequence_number` values, the snapshots are frozen onto the package, `pool_reserved_cents` is recomputed for every fund touched (firing the `ACTIVE` → `EXHAUSTED` auto-transition where §2.10 demands), and the aid year's `total_packaged_cents` is recomputed. The package also exposes `total_offered_cents` — the sum of `offered_cents` over lines in `OFFERED`, `ACCEPTED`, `PARTIALLY_ACCEPTED`, `DISBURSING`, or `DISBURSED` — and `total_accepted_cents`, the sum of `accepted_cents` over lines in `ACCEPTED`, `PARTIALLY_ACCEPTED`, `DISBURSING`, or `DISBURSED`. Packages may be listed with `student_id`, `aid_year_id`, and `status` filters, and lines with `package_id`, `fund_type_id`, and `status` filters; a package's lines, notifications, and revision requests are also retrievable as sub-resource listings.

Notification moves the package `PACKAGED` → `NOTIFIED` and is permitted only when at least one child line is still `OFFERED`. Notifying creates an AwardNotification in `DRAFT` and immediately fires it to `SENT`, stamping `sent_at` from the logical clock, assigning `notification_seq` (1 for the package's first notification, incrementing on each re-notification after a revision), and freezing `snapshot_total_offered_cents` to the package's `total_offered_cents` at send time so later drift is detectable. The student acknowledges a `SENT` notification, moving it to the terminal `ACKNOWLEDGED`; acknowledgment is an ownership-checked action (rung 8), so a student acknowledging someone else's notification is refused with `ERR_NOT_RESOURCE_OWNER`.

Acceptance is the student's decision and always ownership-checked: a `Student`-role caller whose `X-User-ID` is not the package's `student_id` is refused with `ERR_NOT_RESOURCE_OWNER`. The acceptance request carries `line_acceptances`, a per-line set of amounts, each of which must lie between zero and that line's `offered_cents` inclusive. The rules per line are exact: an amount equal to `offered_cents` moves the line `OFFERED` → `ACCEPTED` with `accepted_cents` set to `offered_cents`; an amount strictly between zero and the offer moves it to `PARTIALLY_ACCEPTED` with `accepted_cents` set to that amount, releasing the difference from the fund's `pool_reserved_cents`; an amount of zero declines the line, moving it to `DECLINED` and releasing the full `offered_cents` from the pool, which may fire the fund's `EXHAUSTED` → `ACTIVE` return. When every non-declined line is accepted at its full offer, the package lands in `ACCEPTED`; when at least one line is partial or declined, it lands in `PARTIALLY_ACCEPTED`. Either way the package totals are recomputed and over-award detection (§3.8) runs on the new totals. Acceptance is also gated by rung 16: if an over-award case for the student and year is `OPEN` or `RESOLVING` and the offered-total-based detection still exceeds the cost snapshot, the acceptance is rejected with `ERR_OVERAWARD_UNRESOLVED`. A student may instead decline the entire package, moving it `NOTIFIED` → `DECLINED`: every `OFFERED` line becomes `DECLINED`, each fund's reserved pool is released (again possibly reviving `EXHAUSTED` funds), and the aid year's packaged total is recomputed.

A student who wants changes files a revision request with a `reason` of `CHANGE_ENROLLMENT`, `CHANGE_CIRCUMSTANCE`, `APPEAL_AMOUNT`, or `DECLINE_LOAN_ONLY`. Filing moves the package `NOTIFIED` → `REVISION_REQUESTED` and creates the RevisionRequest in `SUBMITTED` with `requested_by_role` captured from the caller (`Student` when the student filed it; the value may also be `AidOfficer`). Only one revision may be in flight: if a request for the package already sits in `SUBMITTED` or `UNDER_REVIEW`, a new filing fails with `ERR_REVISION_ALREADY_PENDING` (409). An `AidOfficer` moves the request `SUBMITTED` → `UNDER_REVIEW`; an `AidDirector` then decides with a mandatory non-empty `decision_notes`. Denial returns the package to `NOTIFIED` unchanged. Approval re-runs the packaging waterfall against current inputs — enrollment, official EFC, professional judgment deltas — adjusting existing lines, creating new ones, or moving ineligible lines `OFFERED` → `CANCELLED` (releasing their reserved pool and recomputing package totals); recomputes every fund's reserved pool with the exhaustion auto-transitions firing in both directions; refuses the whole decision with `ERR_FUND_POOL_EXHAUSTED` if the repack would push any non-PELL fund's reserved pool above its budget; and finally returns the package to `NOTIFIED` through the system transition, creating a fresh AwardNotification with the next `notification_seq`. Either terminal decision — `APPROVED` after its repack or `DENIED` — returns the package from `REVISION_REQUESTED` to `NOTIFIED`. The request lands in `APPROVED` or `DENIED`, both terminal.

One flag governs staleness between verification and packaging: `needs_repack`. It is set true when a satisfied verification or an approved professional judgment changes the official EFC or the COA deltas relative to the package's frozen `efc_used_cents` and `coa_used_cents` snapshots while the package is `NOTIFIED`, `PARTIALLY_ACCEPTED`, or `ACCEPTED`; a package flagged while `NOTIFIED` keeps its old snapshots until a repack actually runs; and the flag clears when an approved revision's repack executes.

When the student has accepted, an `AidOfficer` locks the package, moving it from `ACCEPTED` or `PARTIALLY_ACCEPTED` to the terminal `LOCKED`, stamping `version_locked_at` and incrementing `version`. Locking is the second optimistic-concurrency operation of §2.9: the request must carry `expected_package_version` equal to the package's current `version`, else it fails with `ERR_STALE_PACKAGE_VERSION` (412). `LOCKED` is the gate for all money movement: disbursement scheduling and line disbursement are impossible until the package is locked.

### 3.7. Disbursement Scheduling, Eligibility, Posting, and Returns

Once a package is `LOCKED`, an `AidOfficer` moves individual lines from `ACCEPTED` or `PARTIALLY_ACCEPTED` into `DISBURSING`; attempting this while the package is anything but `LOCKED` fails with `ERR_PARENT_STATE_BLOCKS`. Against a `DISBURSING` line the officer schedules a Disbursement with the `award_line_id`, a `scheduled_cents` amount, and a `term_code` such as `2026-FALL`. Scheduling validates rung 17: `scheduled_cents` must be strictly positive and no greater than the line's `accepted_cents` minus its `disbursed_cents`, the line must be `DISBURSING`, and the package must be `LOCKED` — otherwise `ERR_DISBURSEMENT_AMOUNT` (422). The new Disbursement is born `SCHEDULED` with `disbursed_cents` zero and `failure_reasons` empty; disbursements can be listed filtered by `award_line_id` and `status`.

Eligibility is evaluated on demand, from either `SCHEDULED` or `ELIGIBILITY_FAILED`, and runs five checks in a pinned order, collecting every failing code into `failure_reasons` rather than stopping at the first failure:

1. `ENROLLMENT_BELOW_REQUIRED` — a `FEDERAL_TITLE_IV` fund requires `enrollment_status` of `FULL_TIME`, `THREE_QUARTER`, or `HALF_TIME`; an `INSTITUTIONAL` fund requires `FULL_TIME` or `THREE_QUARTER`; `STATE` and `EXTERNAL` funds carry no enrollment floor.
2. `SAP_NOT_SATISFACTORY` — the student's `sap_status` must be `GOOD_STANDING`, `WARNING`, or `APPEAL_APPROVED`.
3. `VERIFICATION_INCOMPLETE` — for `FEDERAL_TITLE_IV` funds only, the student must have no verification case, or a case in `COMPLETED_SATISFIED` or `WAIVED`.
4. `COA_HEADROOM_EXCEEDED` — the line's `disbursed_cents` plus `scheduled_cents` must not exceed the line's `accepted_cents`, and the package's posted disbursement total plus `scheduled_cents` must not exceed the package's `coa_used_cents`.
5. `AID_YEAR_LOCKED` — the parent aid year's `status` must be `OPEN` or `PACKAGING_LOCKED`; evaluation during `RECONCILING` or `CLOSED` fails.

When no check fails, the disbursement moves to `ELIGIBILITY_PASSED` with `failure_reasons` set to an empty array; when any fail, it moves to `ELIGIBILITY_FAILED` carrying the ordered list of failed codes — for example a student below the enrollment floor with a suspended SAP record would carry two entries. From `ELIGIBILITY_FAILED` the officer may reset the disbursement back to `SCHEDULED` after the underlying enrollment or SAP problem is fixed, clearing `failure_reasons` to empty; evaluation may then be run again.

Posting moves `ELIGIBILITY_PASSED` → `POSTED` and re-checks the money at that instant: the parent line must be `DISBURSING`, and the line's `disbursed_cents` plus `scheduled_cents` must not exceed its `accepted_cents`. Posting stamps the disbursement's `disbursed_cents` equal to `scheduled_cents`, adds `scheduled_cents` to the line's `disbursed_cents`, to the fund's `pool_disbursed_cents`, and to the aid year's `total_disbursed_cents`, and then evaluates the line's completion: when the line's posted total equals its `accepted_cents` (necessarily above zero, since at least one disbursement has posted), the line auto-transitions `DISBURSING` → `DISBURSED`.

Returns unwind money at either granularity. A posted disbursement can be moved `POSTED` → `RETURN_REQUESTED` and then, on confirmation, to the terminal `RETURNED`, subtracting its `disbursed_cents` from the line, the fund pool, and the aid-year total. A whole disbursed line can likewise be moved `DISBURSED` → `RETURN_REQUESTED` — permitted when an over-award case in `OPEN` or `RESOLVING` references the line or when a manual `reason` is supplied — and then confirmed to `RETURNED` with a `return_cents` amount that must be strictly positive and no greater than the line's `disbursed_cents`; confirmation subtracts `return_cents` from the line's `disbursed_cents`, the fund's `pool_disbursed_cents`, and the aid year's `total_disbursed_cents`, and the release may fire the fund's `EXHAUSTED` → `ACTIVE` auto-transition.

### 3.8. Over-Award Detection and Resolution

Over-award detection runs at three moments: on every packaging build, on every package acceptance transition, and whenever external aid is reported. The counted total is pinned by package status so no ambiguity is possible: while the package is `DRAFT`, `PACKAGED`, `NOTIFIED`, or `REVISION_REQUESTED`, the counted figure is `total_offered_cents`; once it is `PARTIALLY_ACCEPTED`, `ACCEPTED`, or `LOCKED`, the counted figure is `total_accepted_cents`. The total aid is the counted figure plus the sum of `amount_cents` over the student's ExternalAid rows for the aid year whose `counts_against_coa` is true. The overage is the total aid minus the package's `coa_used_cents`. When the overage is strictly positive and no case for the student and year is already `OPEN` or `RESOLVING`, an OverawardCase is created in `OPEN` recording `detected_total_aid_cents` and `overage_cents`; when the overage is zero or negative, an existing `OPEN` case is left alone — there is no automatic close, only the manual rollback path.

External aid itself is reported by an `AidOfficer` with the `student_id`, `aid_year_id`, a `source_name` label for the donor, an `amount_cents` that must be strictly positive, and a `counts_against_coa` flag that defaults to true; the report immediately triggers the detection above. External aid rows can be listed with `student_id` and `aid_year_id` filters, and over-award cases with `student_id`, `aid_year_id`, and `status` filters.

Curing an over-award is a planned reduction. An `AidOfficer` begins resolution, moving the case `OPEN` → `RESOLVING` with a `resolution_plan`: an ordered list of steps, each naming an `award_line_id` and a `reduce_by_cents`. The plan is validated as a whole — it must be non-empty, every referenced line must belong to a package of the same student and aid year, each `reduce_by_cents` must be strictly positive and no more than its target line's `accepted_cents`, and the steps must sum to at least the `overage_cents`; any violation fails with `ERR_OVERAWARD_PLAN_INVALID` (422). A valid plan is applied in array order: each step reduces the target line's `accepted_cents`, dropping the line from `ACCEPTED` to `PARTIALLY_ACCEPTED` when a positive remainder survives, and to `DECLINED` only when the reduction exactly equals the accepted amount and no disbursement has posted against the line; package totals and each affected fund's reserved pool are recomputed as the plan proceeds, firing `EXHAUSTED` → `ACTIVE` transitions where warranted. After the plan is applied, the case auto-transitions `RESOLVING` → `RESOLVED` once the recomputed total aid — the package's `total_accepted_cents` plus counted external aid — is at or below `coa_used_cents`.

Resolution is reversible until the director signs off. A rollback from `RESOLVING` — or from `RESOLVED`, reopening a resolved case any time before verification — returns the case to `OPEN`, but only while no `POSTED` disbursement exists on any line the plan modified. The rollback reverts every plan step, restoring each line's `accepted_cents`, and recomputes package and fund aggregates such that the package's `total_accepted_cents` returns to exactly its pre-plan value. Finally, an `AidDirector` verifies a `RESOLVED` case, moving it to the terminal `VERIFIED`.

### 3.9. Year-End Reconciliation and Aid-Year Close

When packaging is finished and the aid year stands `PACKAGING_LOCKED`, the director begins reconciliation, moving the aid year to `RECONCILING` and creating a ReconciliationRun in `DRAFT` whose `run_seq` is one more than the highest existing run sequence for the aid year — 1 for the first run. The run's lifecycle is `DRAFT` → `IMPORTED` → `COMPARED`, then an automatic fork to `BALANCED` or `VARIANCE_FOUND`, and on the variance path `VARIANCE_FOUND` → `ADJUSTED` → `BALANCED`, which is terminal. Runs are listed as a sub-resource of the aid year and can be fetched individually.

The director first imports the federal figure, moving the run to `IMPORTED` with a `federal_reported_cents` total that must be present and non-negative. Comparing then snapshots `internal_posted_cents` — the sum of `disbursed_cents` over every disbursement in `POSTED` status whose award line's package belongs to this aid year, taken at compare time — and computes `variance_cents` as `federal_reported_cents` minus `internal_posted_cents`. A variance of exactly zero auto-transitions the run to `BALANCED`; any non-zero variance routes it to `VARIANCE_FOUND`.

On the variance path the director books ReconciliationAdjustment rows against the run, each naming the `reconciliation_run_id` context, an `award_line_id` whose posted disbursement is being adjusted, a signed non-zero `adjust_cents` (positive books an additional amount, negative reverses), and a `reason_code` of `FEDERAL_UNDERREPORT`, `FEDERAL_OVERREPORT`, `TIMING_DIFFERENCE`, or `DATA_ENTRY_ERROR`. Creating adjustments moves the run to `ADJUSTED` only when the run's arithmetic nets out — the sum of `adjust_cents` across all of the run's adjustment rows plus `internal_posted_cents` must equal `federal_reported_cents`, per rung 18 — otherwise the request fails with `ERR_VARIANCE_NOT_ZEROED`. Finalizing moves `ADJUSTED` → `BALANCED`, recomputing `variance_cents` to zero by applying the adjustments, honoring the invariant that the adjusted internal books match the federal report exactly. Adjustments are browsable per run and per award line as sub-resource listings.

Closing the year is the last act: the director may move the aid year from `RECONCILING` to `CLOSED` only when its latest reconciliation run — the one with the highest `run_seq` — is `BALANCED`. The close cascades every FundType under the aid year, whether `ACTIVE` or `EXHAUSTED`, to `CLOSED`, and increments the aid year's `version`.

## 4. Endpoint Definitions

Operations that create a new resource — an aid year, fund, student, ISIR record, conflicting-information case, professional judgment case, award package, revision request, disbursement, external aid report, or reconciliation adjustment — return `201 Created`. Operations that modify an existing resource or trigger a state transition return `200 OK`. In both cases the created or updated resource is returned in the envelope's `data` field.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the logical clock | AidDirector |
| POST | `/api/aid-years` | Create an AidYear in DRAFT with Pell schedule and COA figures | AidDirector |
| GET | `/api/aid-years` | List aid years with pagination | AidDirector, AidOfficer, Student |
| GET | `/api/aid-years/{id}` | Fetch one aid year including computed totals | AidDirector, AidOfficer |
| POST | `/api/aid-years/{id}/open` | DRAFT to OPEN; requires at least one ACTIVE fund | AidDirector |
| POST | `/api/aid-years/{id}/lock-packaging` | OPEN to PACKAGING_LOCKED; requires no in-flight packages | AidDirector |
| POST | `/api/aid-years/{id}/begin-reconciliation` | PACKAGING_LOCKED to RECONCILING; creates a ReconciliationRun | AidDirector |
| POST | `/api/aid-years/{id}/close` | RECONCILING to CLOSED when the latest run is BALANCED; cascades funds to CLOSED | AidDirector |
| GET | `/api/aid-years/{id}/fund-types` | List funds of an aid year | AidDirector, AidOfficer |
| GET | `/api/aid-years/{id}/reconciliation-runs` | List reconciliation runs of an aid year | AidDirector |
| POST | `/api/fund-types` | Create a fund under an aid year (DRAFT) | AidDirector |
| GET | `/api/fund-types` | List funds; filterable by aid year and status | AidDirector, AidOfficer |
| GET | `/api/fund-types/{id}` | Fetch one fund including pool aggregates | AidDirector, AidOfficer |
| POST | `/api/fund-types/{id}/activate` | DRAFT to ACTIVE | AidDirector |
| POST | `/api/students` | Register a student record | AidOfficer |
| GET | `/api/students` | List students with pagination and filtering | AidDirector, AidOfficer |
| GET | `/api/students/{id}` | Fetch one student | AidDirector, AidOfficer, Student |
| PATCH | `/api/students/{id}` | Update mutable student attributes | AidOfficer |
| POST | `/api/students/{id}/evaluate-sap` | Run SAP evaluation; optional transfer credits select the TRANSFER variant | AidOfficer |
| POST | `/api/students/{id}/sap-appeal` | Director grants a SAP appeal: SUSPENDED to APPEAL_APPROVED | AidDirector |
| GET | `/api/students/{id}/isir-records` | List ISIR transactions for a student | AidDirector, AidOfficer |
| GET | `/api/students/{id}/verification-cases` | List verification cases for a student | AidDirector, AidOfficer |
| GET | `/api/students/{id}/award-packages` | List packages for a student | AidDirector, AidOfficer, Student |
| GET | `/api/students/{id}/external-aid` | List external aid rows for a student | AidDirector, AidOfficer |
| GET | `/api/students/{id}/overaward-cases` | List over-award cases for a student | AidDirector, AidOfficer |
| GET | `/api/students/{id}/pj-cases` | List professional judgment cases for a student | AidDirector, AidOfficer |
| GET | `/api/students/{id}/conflicting-info-cases` | List conflicting-information cases for a student | AidDirector, AidOfficer |
| POST | `/api/isir-records` | Import an ISIR transaction; assigns cohort, provisional EFC, and verification selection | AidOfficer |
| GET | `/api/isir-records` | List ISIR records; filterable | AidDirector, AidOfficer |
| GET | `/api/isir-records/{id}` | Fetch one ISIR record including computed EFC fields | AidDirector, AidOfficer |
| GET | `/api/verification-cases` | List verification cases; filterable by student, aid year, ISIR | AidDirector, AidOfficer |
| GET | `/api/verification-cases/{id}` | Fetch a verification case | AidDirector, AidOfficer |
| POST | `/api/verification-cases/{id}/begin-review` | DOCUMENTS_RECEIVED to UNDER_REVIEW | AidOfficer |
| POST | `/api/verification-cases/{id}/request-documents` | UNDER_REVIEW to DOCUMENTS_REQUESTED with document reset | AidOfficer |
| POST | `/api/verification-cases/{id}/complete-satisfied` | UNDER_REVIEW to COMPLETED_SATISFIED; computes the verified EFC | AidOfficer |
| POST | `/api/verification-cases/{id}/complete-correction` | UNDER_REVIEW to COMPLETED_CORRECTION_SENT | AidOfficer |
| POST | `/api/verification-cases/{id}/waive` | Any non-terminal state to WAIVED (Director override) | AidDirector |
| GET | `/api/verification-cases/{id}/documents` | List documents of a case | AidDirector, AidOfficer |
| POST | `/api/verification-documents/{id}/mark-received` | REQUESTED to RECEIVED; may auto-advance the case | AidOfficer |
| POST | `/api/verification-documents/{id}/accept` | RECEIVED to ACCEPTED | AidOfficer |
| POST | `/api/verification-documents/{id}/reject` | RECEIVED to REJECTED | AidOfficer |
| POST | `/api/verification-documents/{id}/request-resubmission` | REJECTED to REQUESTED | AidOfficer |
| POST | `/api/conflicting-info-cases` | Open a conflicting-information case | AidOfficer |
| GET | `/api/conflicting-info-cases` | List conflicting-information cases; filterable by student and aid year | AidDirector, AidOfficer |
| GET | `/api/conflicting-info-cases/{id}` | Fetch a conflicting-information case | AidDirector, AidOfficer |
| POST | `/api/conflicting-info-cases/{id}/substantiate` | OPEN to SUBSTANTIATED | AidOfficer |
| POST | `/api/conflicting-info-cases/{id}/unsubstantiate` | OPEN to UNSUBSTANTIATED | AidOfficer |
| POST | `/api/conflicting-info-cases/{id}/resolve-requires-correction` | SUBSTANTIATED to RESOLVED_REQUIRES_CORRECTION (segregation enforced) | AidOfficer |
| POST | `/api/conflicting-info-cases/{id}/resolve` | UNSUBSTANTIATED to RESOLVED (segregation enforced) | AidOfficer |
| POST | `/api/pj-cases` | Submit a professional judgment case | AidOfficer |
| GET | `/api/pj-cases` | List professional judgment cases; filterable by student, aid year, status | AidDirector, AidOfficer |
| GET | `/api/pj-cases/{id}` | Fetch a professional judgment case | AidDirector, AidOfficer |
| POST | `/api/pj-cases/{id}/begin-review` | SUBMITTED to UNDER_REVIEW; captures the reviewer | AidOfficer |
| POST | `/api/pj-cases/{id}/approve` | UNDER_REVIEW to APPROVED; applies the delta or override; OCC via expected case version | AidDirector |
| POST | `/api/pj-cases/{id}/deny` | UNDER_REVIEW to DENIED | AidDirector |
| POST | `/api/award-packages` | Create a DRAFT package shell for a student and aid year | AidOfficer |
| GET | `/api/award-packages` | List packages; filterable by student, aid year, status | AidDirector, AidOfficer |
| GET | `/api/award-packages/{id}` | Fetch a package with computed totals | AidDirector, AidOfficer, Student |
| POST | `/api/award-packages/{id}/build` | DRAFT to PACKAGED; runs the packaging waterfall | AidOfficer |
| POST | `/api/award-packages/{id}/notify` | PACKAGED to NOTIFIED; creates and sends the notification | AidOfficer |
| POST | `/api/award-packages/{id}/accept` | Student accepts full or per-line amounts | Student |
| POST | `/api/award-packages/{id}/decline` | Student declines the entire package | Student |
| POST | `/api/award-packages/{id}/lock` | ACCEPTED or PARTIALLY_ACCEPTED to LOCKED; OCC via expected package version | AidOfficer |
| POST | `/api/award-packages/{id}/revision-requests` | Student requests a revision; package to REVISION_REQUESTED | Student |
| GET | `/api/award-packages/{id}/award-lines` | List lines of a package | AidDirector, AidOfficer, Student |
| GET | `/api/award-packages/{id}/notifications` | List notifications of a package | AidDirector, AidOfficer, Student |
| GET | `/api/award-packages/{id}/revision-requests` | List revision requests of a package | AidDirector, AidOfficer, Student |
| GET | `/api/award-lines` | List award lines; filterable by package, fund, status | AidDirector, AidOfficer |
| GET | `/api/award-lines/{id}` | Fetch an award line | AidDirector, AidOfficer, Student |
| POST | `/api/award-lines/{id}/begin-disbursement` | ACCEPTED or PARTIALLY_ACCEPTED to DISBURSING; requires package LOCKED | AidOfficer |
| POST | `/api/award-lines/{id}/request-return` | DISBURSED to RETURN_REQUESTED | AidOfficer |
| POST | `/api/award-lines/{id}/confirm-return` | RETURN_REQUESTED to RETURNED; reduces disbursed aggregates | AidOfficer |
| POST | `/api/award-notifications/{id}/acknowledge` | SENT to ACKNOWLEDGED by the owning student | Student |
| GET | `/api/revision-requests/{id}` | Fetch a revision request | AidDirector, AidOfficer, Student |
| POST | `/api/revision-requests/{id}/begin-review` | SUBMITTED to UNDER_REVIEW | AidOfficer |
| POST | `/api/revision-requests/{id}/approve` | UNDER_REVIEW to APPROVED; repacks the package and re-notifies | AidDirector |
| POST | `/api/revision-requests/{id}/deny` | UNDER_REVIEW to DENIED; package returns to NOTIFIED unchanged | AidDirector |
| POST | `/api/disbursements` | Schedule a disbursement against a DISBURSING line | AidOfficer |
| GET | `/api/disbursements` | List disbursements; filterable by award line and status | AidDirector, AidOfficer |
| GET | `/api/disbursements/{id}` | Fetch a disbursement | AidDirector, AidOfficer |
| POST | `/api/disbursements/{id}/evaluate-eligibility` | Run eligibility; moves to ELIGIBILITY_PASSED or ELIGIBILITY_FAILED | AidOfficer |
| POST | `/api/disbursements/{id}/reset` | ELIGIBILITY_FAILED to SCHEDULED | AidOfficer |
| POST | `/api/disbursements/{id}/post` | ELIGIBILITY_PASSED to POSTED; updates all disbursed aggregates | AidOfficer |
| POST | `/api/disbursements/{id}/request-return` | POSTED to RETURN_REQUESTED | AidOfficer |
| POST | `/api/disbursements/{id}/confirm-return` | RETURN_REQUESTED to RETURNED; reverses aggregates | AidOfficer |
| POST | `/api/external-aid` | Report external aid; runs over-award detection | AidOfficer |
| GET | `/api/external-aid` | List external aid; filterable by student and aid year | AidDirector, AidOfficer |
| GET | `/api/external-aid/{id}` | Fetch an external aid row | AidDirector, AidOfficer |
| GET | `/api/overaward-cases` | List over-award cases; filterable by student, aid year, status | AidDirector, AidOfficer |
| GET | `/api/overaward-cases/{id}` | Fetch an over-award case | AidDirector, AidOfficer |
| POST | `/api/overaward-cases/{id}/begin-resolution` | OPEN to RESOLVING; applies the ordered resolution plan | AidOfficer |
| POST | `/api/overaward-cases/{id}/rollback` | RESOLVING or RESOLVED to OPEN; reverts plan steps exactly | AidOfficer |
| POST | `/api/overaward-cases/{id}/verify` | RESOLVED to VERIFIED (Director sign-off) | AidDirector |
| GET | `/api/reconciliation-runs/{id}` | Fetch a reconciliation run | AidDirector |
| POST | `/api/reconciliation-runs/{id}/import-federal` | DRAFT to IMPORTED with the federal reported total | AidDirector |
| POST | `/api/reconciliation-runs/{id}/compare` | IMPORTED to COMPARED, then auto BALANCED or VARIANCE_FOUND | AidDirector |
| POST | `/api/reconciliation-runs/{id}/adjustments` | VARIANCE_FOUND to ADJUSTED; net adjustment must zero the variance | AidDirector |
| POST | `/api/reconciliation-runs/{id}/finalize` | ADJUSTED to BALANCED | AidDirector |
| GET | `/api/award-lines/{id}/reconciliation-adjustments` | List reconciliation adjustments touching an award line | AidDirector |
| GET | `/api/reconciliation-runs/{id}/adjustments` | List adjustments of a run | AidDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PARENT_STATE_BLOCKS` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FIELD_CONSTRAINT` | 422 Unprocessable Entity |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_RECEIVED_AT_OUT_OF_WINDOW` | 422 Unprocessable Entity |
| `ERR_PREREQUISITE_MISSING` | 422 Unprocessable Entity |
| `ERR_STALE_PACKAGE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PJ_VERSION` | 412 Precondition Failed |
| `ERR_FUND_POOL_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_OVERAWARD_UNRESOLVED` | 422 Unprocessable Entity |
| `ERR_DISBURSEMENT_AMOUNT` | 422 Unprocessable Entity |
| `ERR_VARIANCE_NOT_ZEROED` | 422 Unprocessable Entity |
| `ERR_VERIFICATION_DOCS_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_CONFLICTING_INFO_OPEN` | 422 Unprocessable Entity |
| `ERR_REVISION_ALREADY_PENDING` | 409 Conflict |
| `ERR_OVERAWARD_PLAN_INVALID` | 422 Unprocessable Entity |
