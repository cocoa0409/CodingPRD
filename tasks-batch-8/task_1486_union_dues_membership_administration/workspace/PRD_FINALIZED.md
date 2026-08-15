# Union Dues & Membership Administration API — Product Requirements Document

## 1. Introduction

A local union office lives or dies by the accuracy of its dues ledger. Employers remit checkoff deductions on behalf of their crews, members fall behind and must be noticed, suspended, reinstated, or expelled under fixed procedural windows, a parent body levies per-capita tax on a precisely defined headcount, and dues objectors are entitled to an agency-fee rebate computed down to the cent. Each of these flows has its own arithmetic, its own calendar rules, and its own segregation-of-duties requirements, and each interacts with the others: posting a remittance can cure a delinquency, voiding one can resurrect it, and a mid-cycle transfer shifts per-capita counts between two locals on a strict period boundary.

This document specifies the Union Dues & Membership Administration API, the system of record for that office. It covers membership registration and dues-rate configuration, the monthly assessment cycle, employer checkoff remittance receipt through reconciliation and posting, delinquency enforcement, dues-objector (agency fee) case handling with rebate calculation, member transfers between locals, per-capita tax reporting to the parent body, and election eligibility determination based on good standing. All business endpoints are mounted under `/api`. The intended audience is the engineering team building the service; the document assumes no access to any other specification artifact.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly five roles, spelled exactly as follows: `ParentBodyAdmin`, `LocalAdmin`, `SecretaryTreasurer`, `OfficeClerk`, and `Member`. A request missing either header, or carrying a role value outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is declared but not permitted on the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The roles divide the office's labor. A `ParentBodyAdmin` charters and configures locals, closes locals, and drives the server's logical clock. A `LocalAdmin` defines dues classifications, runs the delinquency sweep, voids posted remittances, sets and closes objector-case rates, approves per-capita reports, and administers elections. A `SecretaryTreasurer` is the financial officer: assessment runs, remittance reconciliation, dispute resolution and posting, direct-payment entry, reinstatement quoting and reinstatement, rebate issuance, per-capita report creation, submission and payment marking, and transfer completion. An `OfficeClerk` handles front-office intake: registering members and employers, receiving remittances and their deduction lines, drafting and sending delinquency notices, and certifying, accepting, or rejecting transfers. All five roles may call every read endpoint. Direct-payment entry is shared between `SecretaryTreasurer` (office entry) and `Member` (self-service); transfer initiation and transfer cancellation are shared between `OfficeClerk` and `Member`.

Identity binding differs by role. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` record; ownership checks on any resource that references a `Member` compare the resource's member foreign key to `X-User-ID`. A `Member` caller may therefore record a payment, withdraw, file an objector case, initiate a transfer, appeal an issued rebate, or cancel a transfer only for the member whose `id` matches their `X-User-ID`; acting on another member's resources is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `ParentBodyAdmin`, `LocalAdmin`, `SecretaryTreasurer`, or `OfficeClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `received_by_user_id` or `posted_by_user_id` on a remittance, or as `created_by_user_id` or `approved_by_user_id` on a per-capita report — but never compares it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order.

### 2.4. The Logical Clock

The server maintains a logical clock, and every time-dependent rule in this document reads it: notice `sent_at` and cure-deadline arithmetic, suspension timestamps, election window checks, assessment-run period eligibility, transfer readiness, and the current-period determination used by ledger posting. The clock's startup default, before it has ever been set, is exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time. A `ParentBodyAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Periods throughout the API are strings in `YYYY-MM` format and are compared with whole-month arithmetic; date-level rules compare calendar dates at day granularity, ignoring time of day, and spans of months mean calendar months.

### 2.5. Common Resource Properties

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix, rendered in the canonical dashed 8-4-4-4-12 hexadecimal form (e.g., `550e8400-e29b-41d4-a716-446655440000`). The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. The `version` field is an integer that starts at 1 at creation and increments by one on every mutation of the resource, including mutations driven by cascades originating on other resources.

Three resources are exceptions by design, because they are immutable records. A `LedgerEntry`, an `ElectionEligibility`, and an `AssessmentRun` each carry only `id` and `created_at`; both `updated_at` and `version` are absent, and these resources are never updated after creation.

### 2.6. Money, Precision, and the Append-Only Ledger

All monetary amounts in the API are integer cents; no fractional cents exist anywhere. Where a calculation must round, it rounds half up, and each calculation states exactly where rounding is applied. Non-monetary rates are expressed as integers — percentages as whole percents, and dues rates as basis points of gross wages, so that two hundred basis points means 2.00 per cent.

Each member's financial position is derived from an append-only ledger of `LedgerEntry` rows. Every entry has an `entry_type` drawn from `ASSESSMENT_CHARGE`, `SUPPLEMENTAL_CHARGE`, `ADJUSTMENT_CREDIT`, `CHECKOFF_CREDIT`, `DIRECT_PAYMENT`, `REINSTATEMENT_FEE`, `REBATE_CREDIT`, or `VOID_REVERSAL`; a signed `amount_cents` in which charges are positive and credits are negative; the dues `period` the entry pertains to; the owning `member_id`; and a `memo` recording provenance such as a remittance id, a notice id, or a rebate quarter. Entries are never edited or deleted; reversal happens only by posting a negating `VOID_REVERSAL` entry. A member's `arrears_cents` is the ledger balance — the sum of all signed entry amounts — when that sum is positive, and zero otherwise; `credit_balance_cents` is the magnitude of the ledger balance when that sum is negative, and zero otherwise. Because both fields are recomputed from the full entry stream on every posting and every read that needs them, they are always mutually consistent, and any credit balance is consumed immediately by later charges before arrears are allowed to grow again.

### 2.7. Optimistic Concurrency Control

Exactly two write operations are protected by optimistic concurrency control, each against the version of a parent entity the client has already observed.

Initiating a transfer for a member requires the request to carry `expected_member_version`, holding the member's `version` as the client last read it. Because initiating a transfer legitimately supersedes any existing non-terminal transfer of the same member, a writer working from a stale member snapshot would silently supersede a transfer it never saw. If `expected_member_version` does not equal the member's current `version`, the initiation is rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412).

Creating a per-capita report for a local requires the request to carry `expected_local_version`, holding the local's `version` as the client last read it. Because creating a report legitimately supersedes the existing draft report for the same local and period, a stale writer would supersede a draft it never saw. If `expected_local_version` does not equal the local's current `version`, the creation is rejected with `ERR_STALE_LOCAL_VERSION` (HTTP 412).

Endpoints not named above do not accept a version field at all; optimistic concurrency is not optional-on-anything-else in this system.

### 2.8. Segregation of Duties

Two financial checkpoints require two different people. A remittance is received by an `OfficeClerk`, whose `X-User-ID` is recorded as `received_by_user_id`, but it may only be posted by a `SecretaryTreasurer` whose `X-User-ID` differs from the receiver's; an attempt by the same operator to post the remittance they received is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and the posting operator is recorded as `posted_by_user_id`. Likewise, a per-capita report is created by a `SecretaryTreasurer`, recorded as `created_by_user_id`, but may only be approved by a `LocalAdmin` whose `X-User-ID` differs from the creator's; a same-operator approval is rejected with `ERR_SEGREGATION_OF_DUTIES`, and the approver is recorded as `approved_by_user_id`.

### 2.9. Validation Order and Error Precedence

When several validation rules could reject the same request, the server evaluates them in a fixed priority order so that the surfaced error is deterministic. The order is:

1. **User context** — the `X-User-ID` and `X-User-Role` headers are present and the role is declared (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, HTTP 400).
2. **Role permission** — the role is permitted on this endpoint (`ERR_INSUFFICIENT_PERMISSIONS`, HTTP 403).
3. **Member ownership** — a `Member`-role caller owns the resource (`ERR_NOT_RESOURCE_OWNER`, HTTP 403).
4. **Path existence** — path identifiers exist, validated left to right (`ERR_LOCAL_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_EMPLOYER_NOT_FOUND`, `ERR_CLASSIFICATION_NOT_FOUND`, `ERR_REMITTANCE_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_OBJECTOR_CASE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_PER_CAPITA_REPORT_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`, all HTTP 404).
5. **Optimistic concurrency** — the carried expected version matches the parent's current version (`ERR_STALE_MEMBER_VERSION`, `ERR_STALE_LOCAL_VERSION`, HTTP 412).
6. **State guards** — the target entity's current state permits the transition (`ERR_MEMBER_TERMINAL_STATE`, `ERR_MEMBER_NOT_SUSPENDED`, `ERR_NOT_GOOD_STANDING`, `ERR_MEMBER_STATE_FORBIDDEN`, `ERR_LOCAL_NOT_ACTIVE`, `ERR_REMITTANCE_NOT_RECEIVED`, `ERR_REMITTANCE_NOT_RECONCILED`, `ERR_REMITTANCE_NOT_POSTED`, `ERR_NOTICE_STATE_FORBIDDEN`, `ERR_OBJECTOR_CASE_STATE_FORBIDDEN`, `ERR_TRANSFER_STATE_FORBIDDEN`, `ERR_REPORT_STATE_FORBIDDEN`, `ERR_ELECTION_STATE_FORBIDDEN`, all HTTP 409).
7. **Body referential integrity** — entities referenced in the request body resolve and are mutually consistent: a classification belongs to the member's local, an employer exists, a remittance line's member is on the remittance's roster, a transfer's target local exists and is available. Body-referenced existence failures surface as HTTP 422 (`ERR_MEMBER_NOT_FOUND`, `ERR_CLASSIFICATION_NOT_FOUND`, `ERR_EMPLOYER_NOT_FOUND` as body references), roster violations as `ERR_MEMBER_NOT_ON_ROSTER` (HTTP 422), and target-local failures as `ERR_TARGET_LOCAL_UNAVAILABLE` (HTTP 409).
8. **Temporal rules** — periods and windows: `ERR_INVALID_PERIOD` (HTTP 422), `ERR_PRIOR_PERIOD_UNPOSTED`, `ERR_NOTICE_WINDOW_OPEN`, `ERR_ELECTION_WINDOW_OVERLAP`, `ERR_TRANSFER_NOT_READY` (all HTTP 409), and window-time violations reported as `ERR_ELECTION_STATE_FORBIDDEN` (HTTP 409).
9. **Uniqueness and ranges** — duplicate keys and out-of-range values: `ERR_DUPLICATE_CLASSIFICATION`, `ERR_DUPLICATE_MEMBER_NUMBER`, `ERR_REMITTANCE_EXISTS`, `ERR_DUPLICATE_REMITTANCE_LINE`, `ERR_ASSESSMENT_RUN_EXISTS`, `ERR_OBJECTOR_CASE_EXISTS` (all HTTP 409), `ERR_PCT_OUT_OF_RANGE` (HTTP 422), `ERR_PAYMENT_INVALID_AMOUNT` (HTTP 422), and malformed requests as `ERR_INVALID_REQUEST` (HTTP 400).
10. **Fiscal rules** — money-level checks evaluated last: `ERR_REMITTANCE_UNBALANCED`, `ERR_ARREARS_OUTSTANDING`, `ERR_STALE_PER_CAPITA_RATE`, `ERR_PERIOD_LOCKED` (all HTTP 409), and `ERR_REINSTATEMENT_AMOUNT_MISMATCH` (HTTP 422).

The practical consequence is that, for example, a request with a missing header fails before its payload is examined; a stale version surfaces before a state guard; and a remittance whose header does not cover its lines is reported as a fiscal error only after every existence, state, referential, temporal, and uniqueness question has been settled.

### 2.10. Nested Resource Resolution

Endpoints that address a resource through another resource — a notice under a member, a line under a remittance — validate path identifiers sequentially from left to right. The request is rejected with the 404 error corresponding to the first identifier that does not resolve: a request naming a non-existent member and a non-existent notice fails with `ERR_MEMBER_NOT_FOUND`, and a notice id that does not belong to the member named in the path is treated as not found, surfacing `ERR_NOTICE_NOT_FOUND`. Only after the full path has resolved do the state, referential, temporal, and fiscal rules of §2.9 engage.

## 3. Business Logic & Workflows

### 3.1. Chartering Locals and Defining Dues Classifications

A `ParentBodyAdmin` charters a local by supplying its `name` and its full financial configuration. The `dues_method` selects the working-dues formula branch and is either `PERCENTAGE_OF_GROSS` or `FLAT_RATE`. The local's defaults are `default_dues_percent_bp`, the working-dues rate in basis points of gross wages; `default_flat_dues_cents`, the flat monthly dues in cents; and `per_capita_rate_cents`, the per-capita tax owed to the parent body per countable member per period. Delinquency policy is configured with `delinquency_threshold_cents`, the arrears level at or above which a member becomes delinquency-eligible; `grace_periods`, the number of whole months an unpaid final assessment must be aged before it counts toward delinquency; and `notice_cure_days`, the length of the cure window opened when a notice is sent. Reinstatement and expulsion policy is configured with `reinstatement_base_fee_cents`, the base fee that scales with suspension history; `max_suspensions`, the suspension count at which the office expels rather than suspends; and `expel_after_months`, the number of calendar months of continuous suspension after which the sweep expels the member. A new local starts in `ACTIVE` status with `version` 1.

Configuration can be revised later by a `ParentBodyAdmin`, who may update any of `default_dues_percent_bp`, `default_flat_dues_cents`, `per_capita_rate_cents`, `delinquency_threshold_cents`, `grace_periods`, `notice_cure_days`, or `reinstatement_base_fee_cents` in a single modification; every such mutation increments the local's `version` and refreshes `updated_at`. Changing `per_capita_rate_cents` has a deferred consequence described in §3.8: any draft per-capita report already created for the local is rendered stale, because the rate it pinned no longer matches the local's current rate.

A local's lifecycle ends when a `ParentBodyAdmin` closes it, moving `status` from `ACTIVE` to `CLOSED`. Closure is a gate on new work, not a deletion: no new classifications, elections, per-capita reports, or assessment runs may be created for a `CLOSED` local — such attempts fail with `ERR_LOCAL_NOT_ACTIVE` — and no transfer may target it, which surfaces as `ERR_TARGET_LOCAL_UNAVAILABLE`.

Within an active local, a `LocalAdmin` defines dues classifications. Each classification has a `code` — one of `JOURNEYMAN`, `APPRENTICE`, `PROBATIONARY`, or `RETIREE` — unique within the local, so that reusing a code is rejected with `ERR_DUPLICATE_CLASSIFICATION`. Every classification carries a mandatory `min_monthly_dues_cents`, the floor applied after any percentage multiplication, which is also exactly the dues charged when a member's gross wages are zero. The remaining fields are optional overrides: `dues_percent_bp` overrides the local's `default_dues_percent_bp` for this classification and inherits the local default when null; `flat_dues_cents` overrides `default_flat_dues_cents` on the same inherit-when-null rule; `max_monthly_dues_cents` caps the dues after the floor is applied, with null meaning uncapped; and `per_capita_exempt` is a boolean, defaulting to false, that excludes members of this classification from the per-capita headcount. The classification's `local_id` ties it to its owning local. Classifications of a local can be listed with the standard `limit` and `offset` pagination.

### 3.2. Enrolling Members and the Member Ledger

An `OfficeClerk` registers a member by providing the `local_id` of the home local, a `classification_id` that must belong to that same local (a classification from another local is rejected with `ERR_CLASSIFICATION_NOT_FOUND` as a body-reference error), the member's `full_name`, their union card `member_number` — unique within the local, with duplicates rejected as `ERR_DUPLICATE_MEMBER_NUMBER` — and the `joined_at` date. The optional `employer_id` places the member on an employer's checkoff roster; it must reference an existing employer (`ERR_EMPLOYER_NOT_FOUND` as a body-reference error), and when it is null the member is a self-pay member who never appears on any checkoff roster. A new member starts `ACTIVE` with zero arrears, a `suspension_count` of zero, and null `suspended_since` and `last_suspension_ended_at`.

The member resource exposes several computed fields on every read. `arrears_cents` and `credit_balance_cents` derive from the member's ledger exactly as §2.6 describes. `good_standing` is true precisely when the member's `status` is `ACTIVE` and `arrears_cents` is zero; this single predicate gates withdrawal, transfer certification, and transfer completion. `chargeable_share_pct` reflects the member's dues-objector position: while the member has a non-terminal objector case in `RATE_SET`, `REBATE_ISSUED`, or `APPEALED`, it carries that case's chargeable-share percent, and it is null whenever there is no such active case.

Money enters the ledger through a small set of posting events, all sharing one allocation discipline, the **payment waterfall**. The waterfall maintains conceptual buckets in a strict allocation order: first every `REINSTATEMENT_FEE` entry, oldest first by `created_at`; then the member's non-terminal dues assessments, ordered by `period` ascending with ties broken by `created_at` ascending. To determine who owes what, the member's entire `LedgerEntry` stream is replayed in `created_at` ascending order — ties are always broken by `created_at`, never by id: each credit entry fills the earliest open bucket until the credit is exhausted, and each charge entry opens or increases its own bucket. The `paid_cents` of an assessment is the amount of credit the replay allocates to that assessment's bucket, capped at its `assessed_cents`. Replays never filter entries by type or status, so `VOID_REVERSAL` entries negate their originals naturally. The waterfall runs on every credit posting — direct payments, reinstatements, remittance posts, and objector rebates — and on every read of `paid_cents`.

A direct dues payment is recorded either by a `SecretaryTreasurer` at the office window or by the member in self-service, with a payload containing `amount_cents`. The amount must be positive; a zero or negative amount is rejected with `ERR_PAYMENT_INVALID_AMOUNT`. A successful payment posts a `DIRECT_PAYMENT` credit of `amount_cents` against the current clock period, returns the created ledger entry, re-runs the waterfall, recomputes `arrears_cents` and `credit_balance_cents`, and increments the member's `version`. If the member was `DELINQUENT` and the credit drops arrears below the local's `delinquency_threshold_cents`, the auto-cure cascade of §3.5 fires as part of the same request.

Members can be browsed with filters on `local_id`, `classification_id`, `employer_id`, and `status`; a single member read returns the full record including the computed fields above. A member's assessments can be listed with `period` and `status` filters, the ledger with `period` and `entry_type` filters, and the remittance lines referencing the member — their checkoff payment history — with a `period` filter.

### 3.3. Monthly Assessment Runs and the Dues Calculation

Dues are assessed in monthly batches. A `SecretaryTreasurer` triggers an assessment run for a local by supplying `local_id` and `period`; the period must be a well-formed `YYYY-MM` string no later than the current clock period, otherwise the run is rejected with `ERR_INVALID_PERIOD`, and only one run may exist per local and period, with repeats rejected as `ERR_ASSESSMENT_RUN_EXISTS`. The run's local must be `ACTIVE`. A run creates one `PROVISIONAL` `DuesAssessment` for every member of the local in `ACTIVE`, `DELINQUENT`, or `SUSPENDED` status — each member holds at most one assessment per period, the pair of `member_id` and `period` being unique — and posts the corresponding `ASSESSMENT_CHARGE` ledger entries. The same run also sweeps up stale provisionals: any `PROVISIONAL` assessment from a period earlier than the run period for which no wages were ever reported is finalized with a wage base of zero. The immutable run record reports `assessments_created_count` and `assessments_finalized_count`, and the `version` of every assessed or finalized member increments. Runs of a local can be listed with a `period` filter.

The **assessed dues** calculation has two variants sharing one formula skeleton. First, rates resolve down a fallback chain: the percentage rate is the classification's `dues_percent_bp` when set, otherwise the local's `default_dues_percent_bp`; the flat amount is the classification's `flat_dues_cents` when set, otherwise `default_flat_dues_cents`; the floor is the classification's `min_monthly_dues_cents`; and the cap is `max_monthly_dues_cents`, where null means uncapped. Then the local's `dues_method` selects the base: under `FLAT_RATE` the base is the resolved flat amount; under `PERCENTAGE_OF_GROSS` the base is the gross wages in cents multiplied by the resolved basis-point rate divided by ten thousand, rounded half up to whole cents — the only rounding in the entire calculation. The result is then clamped: raised to the floor when it falls below `min_monthly_dues_cents`, and, when a cap exists, lowered to the cap when it exceeds `max_monthly_dues_cents`.

The variants differ only in the wage base. The **provisional** variant, used when an assessment run creates an assessment, is a forward-looking estimate: the wage base is the gross wages of the member's most recent `FINAL` assessment from an earlier period, or zero when the member has none — which typically lands the provisional at the floor. The **final** variant, used at finalization, takes the actual reported gross wages from the remittance line, or zero when the assessment is finalized without any line. At computation time the assessment pins its resolved inputs: `rate_bp_applied` records the resolved percentage rate and is null when the `FLAT_RATE` branch was used; `flat_applied_cents` records the resolved flat dues and is null when the `PERCENTAGE_OF_GROSS` branch was used; and `min_applied_cents` and `max_applied_cents` record the floor and cap in force, the latter null when uncapped. `gross_wages_cents` records the wage base actually used, `assessed_cents` the resulting charge, and `finalized_at` the logical-clock timestamp of finalization, null while the assessment remains `PROVISIONAL`.

Finalization — the transition from `PROVISIONAL` to the terminal `FINAL` state — happens in two ways: remittance reconciliation reporting the member's wages (§3.4), or a later assessment run finalizing stale provisionals at zero wages as described above. When the final amount differs from the provisional, the system posts a compensating ledger entry for the difference: a `SUPPLEMENTAL_CHARGE` when the final amount is higher, an `ADJUSTMENT_CREDIT` when it is lower, and nothing when they are equal. The member's `arrears_cents` and `credit_balance_cents` recompute through the waterfall, and the member's `version` increments.

### 3.4. Employer Checkoff Remittances: Receipt Through Posting

Employers under a checkoff agreement remit deducted dues in bulk. An `OfficeClerk` first registers each employer with its `name`. When a check arrives, an `OfficeClerk` receives the remittance by supplying `employer_id`, `local_id`, the `period` in `YYYY-MM` form, and `remitted_cents`, the header amount the employer's check covers. One remittance may exist per employer and period; a duplicate is rejected with `ERR_REMITTANCE_EXISTS`. The receiving clerk's identity is recorded in `received_by_user_id`, the remittance starts in `RECEIVED` status with `dispute_status` `NONE`, and the member roster for a remittance is defined as the members whose `employer_id` equals the remittance's employer and whose `local_id` equals its local.

The clerk then adds one `RemittanceLine` per deducted member while the remittance remains `RECEIVED` — line entry into a remittance that has moved on is rejected with `ERR_REMITTANCE_NOT_RECEIVED`. Each line carries the `member_id`, the `deducted_cents` the employer withheld, and the reported `gross_wages_cents` that will drive final percentage-dues computation; the line's `remittance_id` is fixed by the path it was created under. The member must be on this employer's roster for this local and non-terminal, otherwise the line is rejected with `ERR_MEMBER_NOT_ON_ROSTER`, and a second line for the same member in the same remittance is rejected with `ERR_DUPLICATE_REMITTANCE_LINE`. A remittance's lines can be listed at any point, and remittances themselves can be browsed with `employer_id`, `local_id`, `period`, and `status` filters.

Reconciliation, performed by a `SecretaryTreasurer`, is where employer-reported amounts meet union-assessed amounts. It requires the remittance to still be `RECEIVED` (`ERR_REMITTANCE_NOT_RECEIVED` otherwise) and proceeds in a pinned order. Roster re-validation runs first, before any variance is computed: if any line's member no longer qualifies for the roster — for instance because the member withdrew after the line was entered — the entire reconcile is rejected with `ERR_MEMBER_NOT_ON_ROSTER`; this is a validation failure, not a reconciliation outcome. Next the header must balance: `remitted_cents` must equal the sum of the lines' `deducted_cents`, otherwise the reconcile is rejected with `ERR_REMITTANCE_UNBALANCED`, and the difference is reported on the remittance as `header_variance_cents`. Only then are amounts computed. For each line, the member's `PROVISIONAL` assessment for the period is finalized with the line's reported gross wages under the final variant — posting supplemental-charge or adjustment-credit deltas as §3.3 describes — and when the member has no assessment for the period at all, a `FINAL` assessment is synthesized at the line's reported gross. Each line then records `variance_cents`, the line's deducted amount minus the final assessed amount, and `line_status`: `MATCHED` when the variance is zero, `UNDER_DEDUCTED` when negative, and `OVER_DEDUCTED` when positive; both fields are null until reconcile runs. The remittance also computes `expected_total_cents`, the sum of the final assessed dues over all roster members holding a non-terminal assessment for the period, and `missing_member_ids`, the roster members in `ACTIVE` or `DELINQUENT` status who hold a non-terminal assessment for the period but appear on no line, sorted by creation time ascending.

The reconcile has two outcomes. When every line variance is zero and no roster member is missing, the remittance advances from `RECEIVED` to `RECONCILED` and the dispute dimension stays `NONE`. When any variance is non-zero or the missing-member list is non-empty, the remittance instead remains `RECEIVED` and its `dispute_status` moves from `NONE` to `DISPUTED` — the assessments still finalize and deltas still post exactly as in the clean case. A disputed remittance is unblocked by a `SecretaryTreasurer` resolving the dispute, which requires `dispute_status` `DISPUTED` (`ERR_DISPUTE_NOT_ACTIVE` when the dispute is `NONE` or already `RESOLVED`) on a still-`RECEIVED` remittance, and carries a free-text `resolution_note`. Resolution accepts the union-assessed final amounts: under-deduction remainders stay in the affected members' arrears as self-pay obligations, over-deduction excesses will flow to the members' credit balances when the remittance posts, and any missing members' assessments finalize at the floor with a wage base of zero. The remittance's `dispute_status` becomes `RESOLVED` and its `status` becomes `RECONCILED`.

Posting, again by a `SecretaryTreasurer`, turns reconciled paper into ledger entries. Three guards apply, in addition to the role check. The remittance must be `RECONCILED` — otherwise `ERR_REMITTANCE_NOT_RECONCILED`; since a disputed remittance is still `RECEIVED`, this single status guard also subsumes dispute blocking. Every other remittance of the same employer with a strictly earlier period must already be `POSTED` or `VOID`, enforcing strictly chronological posting per employer (`ERR_PRIOR_PERIOD_UNPOSTED`). And segregation of duties per §2.8 requires the posting operator to differ from the receiving clerk (`ERR_SEGREGATION_OF_DUTIES`). Posting writes a `CHECKOFF_CREDIT` of each line's `deducted_cents` to that member's ledger, runs the payment waterfall per affected member, recomputes arrears and credit balances, stamps `posted_at` with the logical clock and `posted_by_user_id` with the caller, and increments the remittance's `version` and every affected member's `version`. Any member whose arrears thereby drop below the delinquency threshold auto-cures per §3.5, and the remittance records those members in `auto_cured_member_ids` for later compensation.

A posted remittance can be unwound only by a `LocalAdmin` voiding it, and only within strict limits: the remittance must be `POSTED` (`ERR_REMITTANCE_NOT_POSTED`); no remittance of the same employer with a strictly later period may be `POSTED`, so unwinds proceed in strictly reverse-chronological order (also reported as `ERR_PRIOR_PERIOD_UNPOSTED`); and the period must not be locked — once the local's per-capita report for that period has been submitted or paid, voiding is rejected with `ERR_PERIOD_LOCKED`. Voiding posts `VOID_REVERSAL` entries negating every checkoff credit and every finalization delta the remittance produced, recomputes member balances, increments the affected versions, and restores the pre-post delinquency state: every member listed in `auto_cured_member_ids` transitions back from `ACTIVE` to `DELINQUENT`.

### 3.5. Delinquency, Notices, Suspension, and Reinstatement

Delinquency enforcement is a deterministic sweep over one local, run by a `LocalAdmin` with a payload containing the `local_id`. The sweep processes the local's members in `created_at` ascending order, each member's outcome independent of the others, and considers members in `ACTIVE`, `DELINQUENT`, or `SUSPENDED` status. Two predicates drive it. A member is **aged** when they hold a `FINAL` assessment with a remaining unpaid balance whose period is at least `grace_periods` whole months before the current clock period. A member is **over** when their `arrears_cents` is at or above `delinquency_threshold_cents` — the boundary is inclusive.

An `ACTIVE` member who is both aged and over transitions to `DELINQUENT`, and the sweep creates a `DRAFT` `DelinquencyNotice` capturing an `arrears_at_notice_cents` snapshot — unless a `DRAFT` notice already exists for the member; an existing `SENT` notice does not block a new draft. A `DELINQUENT` member who is no longer both aged and over returns to `ACTIVE`; this defensive path normally never fires, because credits cure delinquency at posting time. A member with a `SENT` notice whose `cure_deadline` has been reached — the deadline is at or before the current clock time — and who is still over has the notice move to `EXPIRED` and is suspended; if instead their arrears have fallen below the threshold, the notice moves to `CURED` and the member returns to `ACTIVE`. Finally, a `SUSPENDED` member whose suspension began at least `expel_after_months` calendar months before the current clock date is expelled. The sweep reports `newly_delinquent_member_ids`, `notices_created`, `notices_expired`, `notices_cured`, `newly_suspended_member_ids`, and `expelled_member_ids`.

The suspension-versus-expulsion decision is a cap check: when the suspension would raise the member's `suspension_count` to reach `max_suspensions`, the sweep expels instead of suspending. Suspension increments `suspension_count` by one and stamps `suspended_since` with the logical clock. Both suspension and expulsion from the `DELINQUENT` state cancel the member's transfers: suspension cancels any transfer in `INITIATED` or `PENDING_TARGET`, because suspension breaks the good-standing precondition those transfers rest on, while expulsion cancels every non-terminal transfer including an `ACCEPTED_BY_TARGET` one. Expulsion of a long-`SUSPENDED` member likewise cancels every non-terminal transfer; any `FILED` or `RATE_SET` objector case survives, but rebates may no longer be issued to the expelled member (`ERR_MEMBER_STATE_FORBIDDEN`).

Notices have their own small lifecycle. An `OfficeClerk` may also draft a notice manually, but only for a `DELINQUENT` member (`ERR_MEMBER_STATE_FORBIDDEN` otherwise), and only while no other `DRAFT` notice exists for the member (`ERR_NOTICE_WINDOW_OPEN`); again, a `SENT` notice does not block drafting. Sending a draft — which requires it to still be `DRAFT` (`ERR_NOTICE_STATE_FORBIDDEN`) — stamps `sent_at` with the logical clock and computes `cure_deadline` as `notice_cure_days` days after `sent_at`. The cure window is the half-open interval from `sent_at` up to but not including `cure_deadline`, and sending is refused with `ERR_NOTICE_WINDOW_OPEN` while another `SENT` notice's window still contains the current clock time. A member's notices can be listed with a `status` filter.

Cure happens where money moves. Whenever any credit posting — a direct payment, a reinstatement, a remittance post, an objector rebate — drops a `DELINQUENT` member's arrears below the threshold, the member auto-cures to `ACTIVE` in the same request: every `SENT` notice for the member moves to `CURED`, every `DRAFT` notice is deleted, and when the cause was a remittance post the member is recorded in that remittance's `auto_cured_member_ids`.

A `SUSPENDED` member returns through reinstatement, a `SecretaryTreasurer` operation with an exact-amount contract. A reinstatement quote — also available to a `SecretaryTreasurer` as a computed read returning `arrears_cents`, `reinstatement_fee_cents`, and `total_due_cents` — is evaluated in a pinned order: first the member's arrears before any fee posting, straight from the waterfall; then the fee, which is the local's `reinstatement_base_fee_cents` multiplied by the member's current `suspension_count` (the count was already incremented at suspension time and is modified by neither the quote nor the fee posting); then `total_due_cents`, the sum of the two. Reinstatement requires the member to be `SUSPENDED` (`ERR_MEMBER_NOT_SUSPENDED` otherwise) and recomputes the quote at call time; the request's `amount_cents` must equal the recomputed `total_due_cents` exactly, and any mismatch is rejected with `ERR_REINSTATEMENT_AMOUNT_MISMATCH`. Because the fee enters the ledger only through its own posting, a quote taken after a failed attempt is unchanged. A successful reinstatement posts a `REINSTATEMENT_FEE` charge for the fee first and a `DIRECT_PAYMENT` credit for the full amount second, both against the current clock period; the member returns to `ACTIVE` with arrears recomputed to zero, `suspended_since` cleared to null, `last_suspension_ended_at` set to the logical clock time, and `version` incremented.

Voluntary exit is the member's own action and is gated on a clean ledger: `arrears_cents` must be zero, otherwise the withdrawal is rejected with `ERR_ARREARS_OUTSTANDING`. An `ACTIVE` member who withdraws moves to `WITHDRAWN`; every non-terminal transfer is cancelled and every `DRAFT` notice is deleted unsent. A `DELINQUENT` member faces the same zero-arrears precondition — a delinquent member must clear arrears before withdrawing — and on success additionally has any `SENT` notice move to `CURED`. Withdrawal increments the member's `version`.

### 3.6. Dues Objector Cases and Rebates

A member who objects to the use of their dues files a dues-objector (agency fee) case. Filing is the member's own action on their own record; it is refused when the member already has a non-terminal case (`ERR_OBJECTOR_CASE_EXISTS`), when the member is `SUSPENDED` (`ERR_MEMBER_STATE_FORBIDDEN`), and when the member is `WITHDRAWN` or `EXPELLED` (`ERR_MEMBER_TERMINAL_STATE`). A new case starts in `FILED` status with `filed_at` stamped from the logical clock, `cumulative_rebate_cents` at zero, and `chargeable_share_pct`, `rate_set_at`, and `last_rebated_period` all null. Cases can be browsed with `member_id` and `status` filters.

A `LocalAdmin` sets the chargeable share — the percent of dues chargeable to the objector — from either `FILED` or `APPEALED` status (`ERR_OBJECTOR_CASE_STATE_FORBIDDEN` from anywhere else), moving the case to `RATE_SET`. The supplied `chargeable_share_pct` must lie between 0 and 100 inclusive (`ERR_PCT_OUT_OF_RANGE` otherwise); the case stamps `rate_set_at`, increments its `version`, and the member's `chargeable_share_pct` begins reflecting the new percent. Because re-rating after an appeal resets the basis for subsequent rebates, the same fields update identically on the appeal-cycle path.

The rebate calculation has two variants that answer different questions and differ numerically for the same case. The **actual** variant runs when a `SecretaryTreasurer` issues the rebate. It includes the member's `FINAL` assessments whose period is later than `last_rebated_period` — or, when no rebate has ever been issued, whose period is at or after the period of `rate_set_at` — and whose `paid_cents` is positive. For each included assessment, the agency fee is the assessed amount multiplied by the chargeable-share percent and divided by one hundred, rounded half up to whole cents; the line rebate is the smaller of the assessment's `paid_cents` and `assessed_cents`, minus that agency fee, floored at zero. The rebate is the sum of the per-line rebates — rounding is applied per assessment line first and the rounded lines are then summed, never the reverse. Issuing posts a `REBATE_CREDIT` of the rebate against the current clock period, applies the waterfall with any excess flowing to `credit_balance_cents`, advances `cumulative_rebate_cents` by the rebate and `last_rebated_period` to the latest included period, increments the member's `version`, and can trigger the auto-cure cascade of §3.5. Issuance requires the case to be in `RATE_SET` (`ERR_OBJECTOR_CASE_STATE_FORBIDDEN`), the member not to be `WITHDRAWN` or `EXPELLED` (`ERR_MEMBER_TERMINAL_STATE`), and the member not to be `SUSPENDED` (`ERR_MEMBER_STATE_FORBIDDEN`).

The **projected** variant backs a computed read that returns `actual_rebate_to_date_cents` and `projected_year_rebate_cents`. The actual-to-date figure is the lifetime line-rebate sum, computed by the same per-line rounding rule, over the member's `FINAL` paid assessments with periods at or before the current clock period, deliberately ignoring `last_rebated_period`. The projected figure is forward-looking: it is the actual rebate to date plus, for each remaining calendar period of the calendar year containing the current clock that falls after the latest `FINAL` assessment period, the floor dues minus the floor dues multiplied by the chargeable-share percent divided by one hundred and rounded half up. Here the floor dues are what the assessed-dues calculation of §3.3 yields at a zero wage base: the resolved flat dues under `FLAT_RATE`, or the floor `min_monthly_dues_cents` under `PERCENTAGE_OF_GROSS`. The projection is read-only and posts nothing.

The member may appeal an issued rebate — only from `REBATE_ISSUED` (`ERR_OBJECTOR_CASE_STATE_FORBIDDEN`), and only the case's own member may appeal (`ERR_NOT_RESOURCE_OWNER`) — which moves the case to `APPEALED` and increments its `version`; the appeal cycle then continues with a re-rate as above. A `LocalAdmin` may close a case from `FILED` or `REBATE_ISSUED` (`ERR_OBJECTOR_CASE_STATE_FORBIDDEN` otherwise); closing clears the member's `chargeable_share_pct` to null and ends the case in `CLOSED`.

### 3.7. Transfers Between Locals

A transfer moves a member's home local at a period boundary. Either the member or an `OfficeClerk` initiates it with a payload naming the `to_local_id`, the `effective_period`, and — per §2.7 — the `expected_member_version`. The target local must exist, be `ACTIVE`, and differ from the origin local (`ERR_TARGET_LOCAL_UNAVAILABLE`); the `effective_period`, the first period the member counts at the target, must be no earlier than the current clock period; and the member must be in good standing at initiation (`ERR_NOT_GOOD_STANDING`). A new transfer starts `INITIATED` with `from_local_id` pinned to the member's current local, and initiation increments the member's `version`. Creating a transfer while a non-terminal transfer already exists for the member does not fail: the prior transfer, whether `INITIATED`, `PENDING_TARGET`, or `ACCEPTED_BY_TARGET`, moves to `SUPERSEDED`. Transfers can be browsed with `member_id`, `from_local_id`, `to_local_id`, and `status` filters.

From `INITIATED`, an `OfficeClerk` at the origin office certifies the member's standing, which re-checks good standing at that moment (`ERR_NOT_GOOD_STANDING`) and moves the transfer to `PENDING_TARGET` (any other source state is `ERR_TRANSFER_STATE_FORBIDDEN`). The target side, again an `OfficeClerk`, then either accepts — requiring the target local to still be `ACTIVE` (`ERR_TARGET_LOCAL_UNAVAILABLE`) — moving the transfer to `ACCEPTED_BY_TARGET`, or rejects it to `REJECTED_BY_TARGET`, optionally recording a `reason` that is stored on the transfer as `reject_reason`.

Completion is a `SecretaryTreasurer` action with three guards, evaluated per the §2.9 order: the transfer must be `ACCEPTED_BY_TARGET` (`ERR_TRANSFER_STATE_FORBIDDEN`); the current clock period must have reached the `effective_period` (`ERR_TRANSFER_NOT_READY` when completion is attempted earlier); and the member must still be `ACTIVE` with zero arrears (`ERR_NOT_GOOD_STANDING`, `ERR_ARREARS_OUTSTANDING`). Completion moves the transfer to `COMPLETED`, rewrites the member's `local_id` to the target, increments the member's `version`, and shifts per-capita headcounts per §3.8: the origin local counts the member for periods before the effective period, the target for the effective period onward. A transfer in `COMPLETED` is terminal.

Cancellation moves the transfer to `CANCELLED`. It is available from `INITIATED` or `PENDING_TARGET` to the member themselves or an `OfficeClerk` (`ERR_TRANSFER_STATE_FORBIDDEN` from any later state), and also fires as a system cascade when the member is suspended, expelled, or withdraws, per §3.5. `REJECTED_BY_TARGET`, `COMPLETED`, `CANCELLED`, and `SUPERSEDED` are the terminal transfer states.

### 3.8. Per-Capita Tax Reporting

Each period, the local owes the parent body a per-capita tax computed on a precisely defined headcount. A `SecretaryTreasurer` creates a report for a local by supplying the `period` and — per §2.7 — the `expected_local_version`; the local must be `ACTIVE`. Creation pins an immutable snapshot: `member_count`, the countable headcount at that instant; `rate_cents`, copied from the local's `per_capita_rate_cents`; and `tax_due_cents`, the product of the two. Because the snapshot is pinned at creation, later membership changes never mutate an existing report — the office creates a superseding draft instead. Creating a report for a local and period that already has a `DRAFT` report supersedes that draft to `SUPERSEDED`; creating one when an `APPROVED`, `SUBMITTED`, or `PAID` report exists for the period is rejected with `ERR_REPORT_STATE_FORBIDDEN`. Creation increments the local's `version`. A local's reports can be listed with `period` and `status` filters.

The headcount itself deserves care. The base population is every member whose current `local_id` is the reporting local, plus every member with a completed transfer out of the local whose effective period is strictly later than the report period. From that base, the countable set keeps members whose status is `ACTIVE` or `DELINQUENT`, whose classification is not `per_capita_exempt`, and who do not have a completed transfer into the local with an effective period strictly later than the report period. The comparison being strict creates the boundary rule: a transfer whose `effective_period` equals the report period counts the member at the target local for that period, and at the origin local for every earlier period.

Approval is a `LocalAdmin` action from `DRAFT` (`ERR_REPORT_STATE_FORBIDDEN` otherwise) guarded twice: the approver must differ from the report's creator (`ERR_SEGREGATION_OF_DUTIES`, per §2.8), and the local's current `per_capita_rate_cents` must still equal the report's pinned `rate_cents` — a rate change after creation forces re-creation, surfacing `ERR_STALE_PER_CAPITA_RATE` at approval. Approval records `approved_by_user_id` and increments the report's `version`. A `SecretaryTreasurer` then submits the `APPROVED` report, moving it to `SUBMITTED` and locking the period: from that point, remittances of the local for that period can no longer be voided (`ERR_PERIOD_LOCKED`). Marking the `SUBMITTED` report paid moves it to the terminal `PAID` state. Each of these steps increments the report's `version`.

### 3.9. Elections and Eligibility

A `LocalAdmin` schedules an election for an `ACTIVE` local by supplying a `title`, the nomination window as `nomination_open_at` and `nomination_close_at`, the `eligibility_cutoff_at` reference instant, and optionally `required_good_standing_months`, which defaults to 12. The three instants must be strictly ordered — open before close, close before cutoff — or creation fails with `ERR_INVALID_REQUEST`. Nomination windows of one local are closed intervals and never overlap, and touching endpoints count as overlapping: a new election whose window so much as shares a boundary instant with an existing election of the same local is rejected with `ERR_ELECTION_WINDOW_OVERLAP`. A new election starts `SCHEDULED`; elections can be browsed with `local_id` and `status` filters.

Opening nominations requires the election to be `SCHEDULED` and the logical clock to have reached `nomination_open_at`; violations surface as `ERR_ELECTION_STATE_FORBIDDEN`. The election moves to `NOMINATION_OPEN` and its `version` increments. Freezing eligibility requires `NOMINATION_OPEN` and the clock at or past `nomination_close_at` (again `ERR_ELECTION_STATE_FORBIDDEN`), and produces the electorate snapshot: one immutable `ElectionEligibility` record per member of the local whose status is `ACTIVE` or `DELINQUENT` at freeze time. Each snapshot records the `election_id`, the `member_id`, an `eligible` boolean, the `arrears_at_freeze_cents` snapshot, the member's `last_suspension_ended_at` at freeze (null if the member was never suspended), and `ineligibility_reasons`, an ordered list that is empty exactly when the member is eligible.

Eligibility is computed per member at freeze as follows, with reasons collected in this pinned order. If the member's status is not `ACTIVE`, the reason `NOT_ACTIVE` is recorded. If `arrears_cents` is not zero, `ARREARS_OUTSTANDING` is recorded. If the member's `last_suspension_ended_at` is not null and the calendar date that is `required_good_standing_months` calendar months after that suspension-ended date falls after the date of `eligibility_cutoff_at`, `INSUFFICIENT_STANDING_MONTHS` is recorded. The member is eligible exactly when no reasons were recorded. The standing window is inclusive — a suspension that ended exactly `required_good_standing_months` calendar months before the cutoff date satisfies the requirement — and the comparison is at date granularity, ignoring time of day.

After the freeze, a `LocalAdmin` concludes the `ELIGIBILITY_FROZEN` election, moving it to the terminal `CONCLUDED` state and incrementing its `version`. The snapshots remain queryable in both directions: an election's eligibility list with `member_id` and `eligible` filters, and a member's eligibility history across elections with an `election_id` filter.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or perform an action on it, and all reads, return `200 OK`. Request payloads, computed fields, and side effects are defined in §2 and §3; the table below is the routing summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ParentBodyAdmin |
| POST | `/api/system/sweeps/delinquency` | Run the delinquency sweep for one local | LocalAdmin |
| POST | `/api/locals` | Charter a local with its dues/per-capita/delinquency configuration | ParentBodyAdmin |
| GET | `/api/locals/{id}` | Get a local | All roles |
| PATCH | `/api/locals/{id}` | Update local configuration | ParentBodyAdmin |
| POST | `/api/locals/{id}/close` | Close a local | ParentBodyAdmin |
| POST | `/api/locals/{id}/classifications` | Define a dues classification for the local | LocalAdmin |
| GET | `/api/locals/{id}/classifications` | List classifications of a local | All roles |
| POST | `/api/members` | Register a member | OfficeClerk |
| GET | `/api/members` | List members with filters | All roles |
| GET | `/api/members/{id}` | Get a member with computed financial fields | All roles |
| POST | `/api/members/{id}/payments` | Record a direct dues payment | SecretaryTreasurer, Member |
| POST | `/api/members/{id}/withdraw` | Voluntary withdrawal | Member |
| GET | `/api/members/{id}/reinstatement-quote` | Computed reinstatement quote | SecretaryTreasurer |
| POST | `/api/members/{id}/reinstate` | Reinstate a suspended member | SecretaryTreasurer |
| GET | `/api/members/{id}/assessments` | List a member's dues assessments | All roles |
| GET | `/api/members/{id}/ledger` | List a member's ledger entries chronologically | All roles |
| GET | `/api/members/{id}/remittance-lines` | List remittance lines referencing the member | All roles |
| POST | `/api/assessment-runs` | Run a monthly assessment batch for a local and period | SecretaryTreasurer |
| GET | `/api/locals/{id}/assessment-runs` | List assessment runs of a local | All roles |
| POST | `/api/employers` | Register a checkoff employer | OfficeClerk |
| GET | `/api/employers/{employerId}` | Get an employer | All roles |
| POST | `/api/remittances` | Receive an employer checkoff remittance | OfficeClerk |
| GET | `/api/remittances` | List remittances with filters | All roles |
| GET | `/api/remittances/{id}` | Get a remittance with computed reconciliation fields | All roles |
| POST | `/api/remittances/{id}/lines` | Add a per-member deduction line | OfficeClerk |
| GET | `/api/remittances/{id}/lines` | List a remittance's lines | All roles |
| POST | `/api/remittances/{id}/reconcile` | Reconcile lines against union-assessed dues | SecretaryTreasurer |
| POST | `/api/remittances/{id}/resolve-dispute` | Resolve a disputed remittance accepting union amounts | SecretaryTreasurer |
| POST | `/api/remittances/{id}/post` | Post a reconciled remittance to member ledgers | SecretaryTreasurer |
| POST | `/api/remittances/{id}/void` | Void a posted remittance with compensating entries | LocalAdmin |
| POST | `/api/members/{id}/notices` | Draft a delinquency notice manually | OfficeClerk |
| GET | `/api/members/{id}/notices` | List a member's delinquency notices | All roles |
| POST | `/api/members/{id}/notices/{noticeId}/send` | Send a draft notice, opening its cure window | OfficeClerk |
| POST | `/api/members/{id}/objector-cases` | File a dues-objection case | Member |
| GET | `/api/objector-cases` | List objector cases with filters | All roles |
| GET | `/api/objector-cases/{caseId}` | Get an objector case | All roles |
| GET | `/api/objector-cases/{caseId}/rebate-projection` | Computed actual-to-date and year-end projected rebate | All roles |
| POST | `/api/objector-cases/{caseId}/set-rate` | Set or re-set the chargeable-share percent | LocalAdmin |
| POST | `/api/objector-cases/{caseId}/issue-rebate` | Issue the actual rebate | SecretaryTreasurer |
| POST | `/api/objector-cases/{caseId}/appeal` | Appeal the issued rebate | Member |
| POST | `/api/objector-cases/{caseId}/close` | Close a filed or rebated case | LocalAdmin |
| POST | `/api/members/{id}/transfers` | Initiate a transfer to another local | Member, OfficeClerk |
| GET | `/api/transfers` | List transfers with filters | All roles |
| GET | `/api/transfers/{transferId}` | Get a transfer | All roles |
| POST | `/api/transfers/{transferId}/certify` | Origin office certifies good standing | OfficeClerk |
| POST | `/api/transfers/{transferId}/accept` | Target local accepts the transfer | OfficeClerk |
| POST | `/api/transfers/{transferId}/reject` | Target local rejects the transfer | OfficeClerk |
| POST | `/api/transfers/{transferId}/complete` | Complete an accepted transfer in its effective period | SecretaryTreasurer |
| POST | `/api/transfers/{transferId}/cancel` | Cancel an initiated or pending transfer | Member, OfficeClerk |
| POST | `/api/locals/{id}/per-capita-reports` | Create a draft per-capita report with pinned snapshot | SecretaryTreasurer |
| GET | `/api/locals/{id}/per-capita-reports` | List a local's per-capita reports | All roles |
| POST | `/api/per-capita-reports/{reportId}/approve` | Approve a draft report | LocalAdmin |
| POST | `/api/per-capita-reports/{reportId}/submit` | Submit an approved report, locking the period | SecretaryTreasurer |
| POST | `/api/per-capita-reports/{reportId}/mark-paid` | Mark a submitted report paid | SecretaryTreasurer |
| POST | `/api/locals/{id}/elections` | Schedule an election with its nomination window | LocalAdmin |
| GET | `/api/elections` | List elections with filters | All roles |
| GET | `/api/elections/{id}` | Get an election | All roles |
| POST | `/api/elections/{id}/open-nominations` | Open the nomination window | LocalAdmin |
| POST | `/api/elections/{id}/freeze-eligibility` | Freeze eligibility snapshots for the electorate | LocalAdmin |
| POST | `/api/elections/{id}/conclude` | Conclude a frozen election | LocalAdmin |
| GET | `/api/elections/{id}/eligibilities` | List eligibility snapshots of an election | All roles |
| GET | `/api/members/{id}/eligibilities` | List a member's eligibility snapshots across elections | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 where the guarded workflow lives.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_LOCAL_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_EMPLOYER_NOT_FOUND` | 404 Not Found |
| `ERR_CLASSIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_REMITTANCE_NOT_FOUND` | 404 Not Found |
| `ERR_NOTICE_NOT_FOUND` | 404 Not Found |
| `ERR_OBJECTOR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSFER_NOT_FOUND` | 404 Not Found |
| `ERR_PER_CAPITA_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_ELECTION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_MEMBER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_LOCAL_VERSION` | 412 Precondition Failed |
| `ERR_MEMBER_TERMINAL_STATE` | 409 Conflict |
| `ERR_MEMBER_NOT_SUSPENDED` | 409 Conflict |
| `ERR_NOT_GOOD_STANDING` | 409 Conflict |
| `ERR_MEMBER_STATE_FORBIDDEN` | 409 Conflict |
| `ERR_LOCAL_NOT_ACTIVE` | 409 Conflict |
| `ERR_REMITTANCE_NOT_RECEIVED` | 409 Conflict |
| `ERR_REMITTANCE_NOT_RECONCILED` | 409 Conflict |
| `ERR_REMITTANCE_NOT_POSTED` | 409 Conflict |
| `ERR_DISPUTE_NOT_ACTIVE` | 409 Conflict |
| `ERR_NOTICE_STATE_FORBIDDEN` | 409 Conflict |
| `ERR_OBJECTOR_CASE_STATE_FORBIDDEN` | 409 Conflict |
| `ERR_TRANSFER_STATE_FORBIDDEN` | 409 Conflict |
| `ERR_REPORT_STATE_FORBIDDEN` | 409 Conflict |
| `ERR_ELECTION_STATE_FORBIDDEN` | 409 Conflict |
| `ERR_MEMBER_NOT_ON_ROSTER` | 422 Unprocessable Entity |
| `ERR_TARGET_LOCAL_UNAVAILABLE` | 409 Conflict |
| `ERR_INVALID_PERIOD` | 422 Unprocessable Entity |
| `ERR_PRIOR_PERIOD_UNPOSTED` | 409 Conflict |
| `ERR_NOTICE_WINDOW_OPEN` | 409 Conflict |
| `ERR_ELECTION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_TRANSFER_NOT_READY` | 409 Conflict |
| `ERR_DUPLICATE_CLASSIFICATION` | 409 Conflict |
| `ERR_DUPLICATE_MEMBER_NUMBER` | 409 Conflict |
| `ERR_REMITTANCE_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_REMITTANCE_LINE` | 409 Conflict |
| `ERR_ASSESSMENT_RUN_EXISTS` | 409 Conflict |
| `ERR_OBJECTOR_CASE_EXISTS` | 409 Conflict |
| `ERR_PCT_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_PAYMENT_INVALID_AMOUNT` | 422 Unprocessable Entity |
| `ERR_REMITTANCE_UNBALANCED` | 409 Conflict |
| `ERR_ARREARS_OUTSTANDING` | 409 Conflict |
| `ERR_REINSTATEMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_STALE_PER_CAPITA_RATE` | 409 Conflict |
| `ERR_PERIOD_LOCKED` | 409 Conflict |
