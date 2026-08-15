# Bad Debt & Presumptive Charity Screening API — Product Requirements Document

## 1. Introduction

Hospital self-pay units operate under a dual mandate: maximize legitimate recovery on patient-responsible balances while satisfying charity-care obligations, Medicare bad-debt claiming rules, and consumer credit-reporting protections. This document specifies the Bad Debt & Presumptive Charity Screening API, the system of record for the self-pay unit's entire downstream revenue cycle — from the moment a balance becomes the guarantor's responsibility through statement cycles, presumptive charity screening, early-out vendor placement, collection agency placement, dispute handling, payment plans, write-off, and post-write-off recovery.

The API is deliberately compliance-first. Write-offs follow a two-person approval model with enforced segregation of duties; charity-care write-offs must trace back to a current, evaluated presumptive screening; Medicare bad-debt claims are captured in an append-only log that is voided rather than deleted; and credit reporting can be frozen by dispute or suppressed by charity eligibility at well-defined points in the lifecycle. Time itself is a governed input: all aging, deadline, and sweep behavior is driven by a logical clock rather than wall-clock time, so that statement cycles, recall windows, dispute expiry, and payment-plan default detection are fully deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API. All resources are mounted under the `/self-pay` prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting operator and `X-User-Role` to specify their operational capacity. The system recognizes four distinct roles: `Collector`, `FinancialCounselor`, `RevenueIntegrityOfficer`, and `CollectionAgencyUser`. A request missing either header, or carrying a malformed header, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not in the endpoint's authorized role list is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

For every role, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server never compares it against any resource's `id`. The server does, however, record it where a workflow requires attribution: when a `RevenueIntegrityOfficer` approves a write-off, the acting `X-User-ID` is stamped into the write-off's `approved_by_user_id`, and the segregation-of-duties rules described later compare the approving, creating, and reversing operator identifiers against one another. This opaque-identity model applies identically to `Collector`, `FinancialCounselor`, `RevenueIntegrityOfficer`, and `CollectionAgencyUser`.

Role capabilities in brief: a `Collector` registers accounts, issues and maintains statements, places and recalls early-out and agency placements, posts payments, files disputes, and cures defaulted plans. A `FinancialCounselor` creates and evaluates presumptive charity screenings, and shares dispute-filing and payment-plan setup with the `Collector`. A `RevenueIntegrityOfficer` approves and reverses write-offs, resolves disputes, terminates defaulted plans, and generates vendor performance snapshots; the officer is also the only role that may read the Medicare bad-debt log. A `CollectionAgencyUser` is an external agency operator who posts remittances, marks placements as credit-reported, and reads accounts and placements.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The server maintains a logical clock that governs every date- and time-dependent behavior in the system: aging bucket derivation, statement due dates, recall deadlines, dispute expiry, payment-plan default detection, and all `posted_at`-style timestamps. The logical clock starts at 2026-08-01T00:00:00Z when the server boots and never falls back to wall-clock time.

An administrative clock-advance capability moves the logical clock forward to a caller-supplied `to_iso8601` instant. The supplied instant must be at or after the clock's current value; the clock never moves backward. Advancing the clock is itself a mutation with consequences: immediately after the new time is installed, the server runs the payment-plan default sweep and the dispute-expiry sweep described in §3.7 and §3.6, and the response reports the new time as `now_iso8601` together with how many plans were flagged into default (`plans_flagged_in_default`) and how many disputes expired (`disputes_expired`). Aging buckets are then recomputed against the new date the next time an account is read. `Collector`, `FinancialCounselor`, and `RevenueIntegrityOfficer` may advance the clock.

### 2.5. Common Resource Properties

All primary resources — self-pay accounts, statements, screenings, early-out placements, collection agency placements, disputes, payment plans, write-offs, and recovery transactions — carry a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- **`version` (integer):** a system-managed integer that increments by one on every mutation of the resource, including mutations caused indirectly by cascading side effects on a related resource.

Two resource families are deliberately append-only and carry only `id` and `created_at` from the standard set: Medicare bad-debt log entries and vendor performance snapshots have no `updated_at` and no `version`. Once created they are never modified in place; the only later change a log entry can show is a `voided_at` stamp, which is written as part of write-off reversal and does not constitute a general-purpose update.

### 2.6. Monetary Representation, Precision, and Rounding

All monetary amounts in the system are integer cents; there are no fractional-cent values anywhere in the API. Rounding behavior is defined per calculation rather than globally: vendor and agency contingency fees are rounded half up to the nearest cent; the agency recall fee is rounded down to the nearest cent; the vendor recovery rate and the charity screening's income percentage are rounded down to a whole basis point or whole percent respectively. Aging, collection-effort, and installment arithmetic operate at whole-day granularity with no rounding.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against the parent self-pay account: creating a presumptive charity screening for an account, and approving a pending write-off. Both requests must carry `expected_account_version`, a non-optional field holding the account `version` the client last observed. If the account's current `version` does not equal `expected_account_version` at request-handling time — because another writer has advanced the account since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated.

The rationale differs per endpoint but the mechanism is identical. Creating a screening supersedes any still-current screening on the same account, so a client holding a stale account view would silently supersede state it never saw. Approving a write-off posts the write-off, zeroes the balance, drives the account's status, and may create a Medicare log entry, so the approver must have observed the latest account state before signing off. Endpoints other than these two do not accept a version field.

### 2.8. Balance Integrity and Derived Account Totals

Every self-pay account tracks `original_balance_cents` — the balance at the moment the guarantor became liable — and `current_balance_cents`, which is the original balance less all applied payments and less all charity, write-off, and recovery adjustments. The current balance may never go negative; any mutation that would drive it below zero is rejected.

Three running totals are maintained alongside the balance and are recomputed as events post: `charity_writeoff_total_cents` accumulates the amounts of posted charity-care write-offs, `bad_debt_writeoff_total_cents` accumulates the amounts of posted bad-debt write-offs, and `recovery_total_cents` accumulates the gross amount of every recovery transaction posted to the account. Post-write-off recovery accounting can reduce `bad_debt_writeoff_total_cents` under one of the two reserve methodologies described in §3.8, and write-off reversal reduces the corresponding total; no other operation touches these totals. The account's `aging_bucket` is a derived value (see §3.1) recomputed on every read and after every clock advance, with `aging_bucket_entered_at` recording when the account entered its current bucket.

### 2.9. Reference Resolution, Nested Paths, and Validation Order

Requests are validated in a fixed priority order, and the first failing check produces the response — later checks are not evaluated for that request. The order is:

1. **Authentication context.** `X-User-ID` and `X-User-Role` must be present and well-formed, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Applies to every endpoint.
2. **Authorization.** The role must appear in the endpoint's authorized role list, else `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). Applies to every endpoint.
3. **Existence.** Path identifiers are resolved left to right — a request naming an account and then a child resource under it fails on the account first if the account does not exist — and body foreign-key references must resolve. Any unresolved reference yields `ERR_NOT_FOUND` (HTTP 404); the specific missing resource is identified in the human-readable `message`.
4. **Payload shape.** Required fields must be present, types correct, enum values within their declared sets, and numeric ranges honored (for example `amount_cents` greater than zero, or `installment_count` within its allowed range), else `ERR_INVALID_REQUEST` (HTTP 400).
5. **Optimistic concurrency.** On the two OCC-guarded endpoints, `expected_account_version` must equal the account's current `version`, else `ERR_STALE_VERSION` (HTTP 412).
6. **State preconditions.** The target resource must be in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409).
7. **Segregation of duties.** Write-off approval and reversal must be performed by a different principal than the prior step, else `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403).
8. **Screening currency.** A charity-care write-off approval requires the referenced screening to still be `EVALUATED` with an eligible outcome, else `ERR_SCREENING_NOT_CURRENT` (HTTP 409).
9. **Open-dispute guard.** An `OPEN` dispute on the account blocks collection-agency placement with `ERR_OPEN_DISPUTE_BLOCKS_PLACEMENT` (HTTP 409); the same underlying guard on write-off approval surfaces as `ERR_OPEN_DISPUTE_BLOCKS_WRITE_OFF`, the two identifiers distinguishing which guard fired.
10. **Charity-eligibility guard.** An evaluated screening with a charity-eligible outcome blocks both early-out and agency placement with `ERR_CHARITY_ELIGIBLE_BLOCKS_PLACEMENT` (HTTP 409).
11. **Aging and statement-cycle prerequisites.** Early-out placement requires the early-out aging band (`ERR_ACCOUNT_NOT_IN_EARLY_OUT_BUCKET`); direct agency placement requires the deepest band (`ERR_ACCOUNT_NOT_IN_AGENCY_BUCKET`) plus a statement-count minimum; write-off approval enforces its own aging (`ERR_WRITE_OFF_BEFORE_120_DAYS`) and statement-count (`ERR_INSUFFICIENT_STATEMENT_CYCLE`) prerequisites. All are HTTP 409.
12. **Recall deadlines.** Early-out recall after the recall deadline fails with `ERR_RECALL_DEADLINE_PASSED` (HTTP 409).
13. **Recovery reference consistency.** The polymorphic references on a recovery posting must match the entity family required by its payment kind, else `ERR_RECOVERY_FK_MISMATCH` (HTTP 400).
14. **Recovery amount caps.** The posted amount must not exceed the recoverable balance for its target, else `ERR_RECOVERY_EXCEEDS_BALANCE` (HTTP 422).
15. **Full-balance write-offs only.** A write-off request carrying an explicit partial amount is rejected with `ERR_PARTIAL_WRITE_OFF_NOT_SUPPORTED` (HTTP 422).
16. **Cost report year.** A bad-debt write-off's Medicare cost report year must fall within its allowed window, else `ERR_INVALID_COST_REPORT_YEAR` (HTTP 422).

### 2.10. Credit Reporting Status as a Cross-Cutting Ledger

Every account carries a `credit_reporting_status` that moves through a small set of values — `NOT_REPORTED`, `REPORTABLE`, `REPORTED`, `FROZEN_BY_DISPUTE`, and `SUPPRESSED_BY_CHARITY` — as placements, disputes, screenings, and write-offs unfold. This status is never set directly by a client; it changes only as a side effect of the workflows in §3, and several of those workflows consult it before acting. Because charity outcomes and dispute outcomes can both revise it, the exact transition each workflow applies is specified alongside that workflow rather than here.

## 3. Business Logic & Workflows

### 3.1. Registering Self-Pay Accounts and the Aging Clock

A `Collector` or `RevenueIntegrityOfficer` registers a self-pay account by supplying the `patient_mrn`, the `patient_name`, the `original_balance_cents`, and the `guarantor_liability_date` — the ISO 8601 date on which the balance became the patient's responsibility and day zero of the aging clock. The `patient_mrn` is unique per unit. On creation the account's `current_balance_cents` is initialized to the full `original_balance_cents`, its `status` begins at `OPEN`, its `credit_reporting_status` begins at `NOT_REPORTED`, and all running totals start at zero.

Aging is derived, never stored as truth. The number of days outstanding is the whole-day difference between the logical clock's current date and the `guarantor_liability_date`. Fewer than 30 days outstanding places the account in `CURRENT`; at least 30 but fewer than 60 in `BUCKET_30`; at least 60 but fewer than 90 in `BUCKET_60`; at least 90 but fewer than 120 in `BUCKET_90`; and 120 days or more in `BUCKET_120_PLUS`. Boundaries include their lower edge: day 30 is already `BUCKET_30`, day 60 is `BUCKET_60`, day 90 is `BUCKET_90`, and day 120 is `BUCKET_120_PLUS`. The `aging_bucket` is recomputed every time an account is read and after every clock advance, and `aging_bucket_entered_at` is reset to the current logical time only when the bucket value actually changes.

The account list endpoint can be filtered by `status`, `aging_bucket`, and `credit_reporting_status`, in addition to the standard `limit` and `offset` pagination parameters. When an account reaches a terminal state — `CLOSED_PAID` or `CLOSED_CHARITY` — the system records a free-text `status_reason` describing the terminal transition.

### 3.2. The Statement Cycle

Statements document the unit's collection effort and gate later escalation steps. A `Collector` issues a statement against an account whose `status` is `OPEN`, `IN_EARLY_OUT`, or `IN_COLLECTIONS`; accounts in any other status are not statement-eligible and the issuance is rejected with `ERR_ACCOUNT_NOT_STATEMENT_ELIGIBLE`.

Each issued statement receives a `statement_index` equal to one more than the highest index previously used for that account — the first statement is index 1. Its `due_date` is the `guarantor_liability_date` plus thirty days multiplied by the `statement_index`, so statement one is due thirty days after liability began, statement two after sixty, and so on. The statement captures `balance_at_issue_cents` as a snapshot of the account's `current_balance_cents` at issuance, and its `issued_at` is stamped from the logical clock. Although the statement lifecycle formally begins in `DRAFT`, creation issues the statement immediately: the persisted and observable status is always `SENT`, and `DRAFT` is never returned by the API. Issuing a statement increments the account's `statements_sent_count` and bumps the account's `version`.

A `Collector` may subsequently mark a `SENT` statement as delivered, moving it to `DELIVERED`, or as returned, moving it to `RETURNED_UNDELIVERABLE`; either marking against a statement not currently `SENT` is rejected with `ERR_INVALID_STATE`. Delivery is purely evidentiary, but return has an accounting consequence: the account's `statements_sent_count` is decremented by one, because the count is defined as the number of the account's statements currently in `SENT` or `DELIVERED` status — a returned statement no longer counts toward the statement-cycle prerequisites that gate agency placement and write-off — and the account's `version` is incremented.

### 3.3. Presumptive Charity Screening

Before an account is pushed toward collections, a `FinancialCounselor` can screen it for presumptive charity eligibility. Creating a screening requires the target `account_id`, the chosen `screening_model`, and — because creation is OCC-guarded per §2.7 — an `expected_account_version` matching the account's current `version`; a mismatch is rejected with `ERR_STALE_VERSION`. Two screening models exist, and they are genuinely different algorithms applied to the same account. Under `FPL_TIERED` the caller supplies `household_size` and `household_income_cents` (annual income in cents). Under `SCORE_BASED` the caller instead supplies `third_party_score`, a vendor presumptive score from 0 to 1000. Supplying a model without its required inputs, or out-of-range values, fails payload validation with `ERR_INVALID_REQUEST`.

Creation has an immediate consequence for prior screenings: any earlier screening for the same account that is still `PENDING` or `EVALUATED` is automatically transitioned to `SUPERSEDED`. When the superseded screening was `EVALUATED` with an outcome of `FULL_CHARITY` or `PARTIAL_CHARITY` and the account's `credit_reporting_status` had been set to `SUPPRESSED_BY_CHARITY` on its strength, the credit status reverts to `REPORTABLE`, since the new screening may disagree. The account's `version` is incremented by this creation cascade. A freshly created screening is `PENDING` with `eligibility_outcome` also `PENDING`, and carries no `fpl_percent` or `screened_at` yet.

Evaluation is a separate, explicit step by a `FinancialCounselor`. It requires the screening to still be `PENDING` — re-evaluating an already-evaluated screening is rejected with `ERR_INVALID_STATE` — and the account's `status` must be `OPEN`, `IN_EARLY_OUT`, or `IN_COLLECTIONS`, otherwise the evaluation is rejected with `ERR_ACCOUNT_NOT_SCREENABLE`. For an `FPL_TIERED` screening, the system looks up the federal poverty level base for the declared household size — 1,506,000 cents for a household of one, 2,044,000 for two, 2,582,000 for three, 3,120,000 for four, 3,658,000 for five, 4,196,000 for six, 4,734,000 for seven, and 5,272,000 for eight — then computes `fpl_percent` as one hundred times `household_income_cents` divided by that base, rounded down to a whole percent. An `fpl_percent` of at most 200 yields `FULL_CHARITY` with a `charity_writeoff_percent` of 100; above 200 but at most 300 yields `PARTIAL_CHARITY` with a `charity_writeoff_percent` of 50; anything higher yields `NOT_ELIGIBLE` with a `charity_writeoff_percent` of 0. The boundary is inclusive, so exactly 200 percent is full charity while 201 percent drops to partial. For a `SCORE_BASED` screening, `fpl_percent` remains null: a `third_party_score` of at least 700 yields `FULL_CHARITY`, at least 550 but below 700 yields `PARTIAL_CHARITY`, and below 550 yields `NOT_ELIGIBLE`, with the same 100, 50, and 0 write-off percentages. Two screenings on the same account under different models may therefore legitimately reach different outcomes; that is intentional.

Upon evaluation the screening moves from `PENDING` to `EVALUATED`, `screened_at` is stamped from the logical clock, and the credit-reporting consequence fires: if the outcome is `FULL_CHARITY` or `PARTIAL_CHARITY` and the account's `credit_reporting_status` is `REPORTABLE` or `REPORTED`, it becomes `SUPPRESSED_BY_CHARITY` and the account's `version` is incremented. Screenings for an account can be listed through the account, and the write-off list can be filtered by `screening_id` when tracing which write-offs a screening supported.

### 3.4. Early-Out Placement, Recall, and Vendor Performance

Once an account ages into the early collection band, a `Collector` may place it with an early-out vendor by supplying the `account_id`, the `vendor_name`, and the vendor's `contingency_fee_bps` (basis points, where one basis point is one-hundredth of a percent). Placement requires the account to be `OPEN` and in `BUCKET_30` or `BUCKET_60` — an account in any other band is rejected with `ERR_ACCOUNT_NOT_IN_EARLY_OUT_BUCKET`. Two further guards apply, in the validation order of §2.9: no other early-out placement for the account may be `ACTIVE` (else `ERR_ACTIVE_PLACEMENT_EXISTS`), and no evaluated screening with an outcome of `FULL_CHARITY` or `PARTIAL_CHARITY` may exist for the account (else `ERR_CHARITY_ELIGIBLE_BLOCKS_PLACEMENT`).

Placement snapshots `placement_balance_cents` from the account's `current_balance_cents`, stamps `placed_at` from the logical clock, and computes the `recall_deadline` as the `guarantor_liability_date` plus the configured early-out recall-day count — the date by which the account must be recalled or escalated. The account's `status` moves from `OPEN` to `IN_EARLY_OUT` and its `version` increments. The placement's `recovered_cents` starts at zero and accumulates the gross amount of every early-out remittance later attributed to it.

Recalling an early-out placement is permitted only while the logical clock's date is on or before the `recall_deadline`; a recall attempted after that date is rejected with `ERR_RECALL_DEADLINE_PASSED`. A successful recall moves the placement from `ACTIVE` to `RECALLED` and returns the account from `IN_EARLY_OUT` to `OPEN`, incrementing the account's `version`. If the deadline passes with the placement still active, the account becomes eligible for escalation to a collection agency as described in §3.5 — the escalation moves the early-out placement to `ESCALATED_TO_AGENCY`. Finally, if payments drive the account's balance to zero while a placement is active, the placement closes as `COMPLETED_PAID` alongside the account.

Vendor oversight is measured through performance snapshots, generated by a `RevenueIntegrityOfficer` for a named `vendor_name` over a window from `snapshot_period_start` (inclusive) to `snapshot_period_end` (exclusive). The snapshot counts `placements_in_window` — that vendor's early-out placements whose `placed_at` falls inside the window — and sums `recovered_in_window_cents`, the gross amounts of early-out remittances attributed to those placements and posted inside the window. The `recovery_rate_bps` is ten thousand times the recovered sum divided by the summed `placement_balance_cents` of the in-window placements, rounded down to a whole basis point; when no placement balance exists in the window the rate is zero. The snapshot's `meets_minimum_threshold` is true when the rate is at least 1,200 basis points — a twelve percent recovery floor. Snapshots are immutable once generated, carry a `snapshot_generated_at` stamp from the logical clock, and can be listed with a `vendor_name` filter.

### 3.5. Collection Agency Placement, Recall, and Credit Reporting

Agency placement happens by one of two paths, both performed by a `Collector` supplying an `account_id`, an `agency_name`, and the agency's `contingency_fee_bps`. The escalation path applies when the account is `IN_EARLY_OUT` with an `ACTIVE` early-out placement: escalation is permitted only once the logical clock's date has passed that placement's `recall_deadline` — attempting it earlier is rejected with `ERR_RECALL_WINDOW_STILL_OPEN` — and it moves the early-out placement to `ESCALATED_TO_AGENCY` as it places the account with the agency. The direct path applies when the account is `OPEN`: it requires the account to be in `BUCKET_120_PLUS` (else `ERR_ACCOUNT_NOT_IN_AGENCY_BUCKET`) and to have met the configured statement-cycle minimum, meaning `statements_sent_count` must reach the required number of sent-or-delivered statements before agency referral (else `ERR_INSUFFICIENT_STATEMENT_CYCLE`).

Whichever path is taken, the shared guards fire per the §2.9 order: no other agency placement may be `ACTIVE` for the account (`ERR_ACTIVE_PLACEMENT_EXISTS`), no `OPEN` dispute may exist for the account (`ERR_OPEN_DISPUTE_BLOCKS_PLACEMENT`), and no evaluated charity-eligible screening may exist (`ERR_CHARITY_ELIGIBLE_BLOCKS_PLACEMENT`). A successful placement moves the account to `IN_COLLECTIONS`, increments its `version`, snapshots `placement_balance_cents`, stamps `placed_at`, computes `recall_window_closes_at` as the placement date plus the configured agency recall-window day count, and — significantly for the patient's credit — moves `credit_reporting_status` to `REPORTABLE`.

While a placement is active, a `CollectionAgencyUser` may mark it as reported to a consumer bureau. This stamps `credit_reported_at` from the logical clock and moves the account's `credit_reporting_status` to `REPORTED`, unless it is already `FROZEN_BY_DISPUTE` or `SUPPRESSED_BY_CHARITY`, in which case the mark is recorded on the placement but the account status is left alone; the account's `version` increments when its status changes.

Recalling an agency placement always succeeds for an `ACTIVE` placement, but the fee treatment depends on timing. If the logical clock's date is on or before `recall_window_closes_at`, the placement closes as `RECALLED_NO_FEE`. After that date it closes as `RECALLED_WITH_FEE`, and a recall fee is computed: the placement's `placement_balance_cents` multiplied by 1,500 basis points — fifteen percent — capped at 50,000 cents, rounded down to the nearest cent. The fee is recorded for audit only: it does not alter the account's `current_balance_cents`, is not credited to the placement's `recovered_cents`, does not touch any write-off totals, and is never posted as a post-write-off recovery; its only observable footprint is the placement's terminal status. Either way, the account returns from `IN_COLLECTIONS` to `OPEN` with its `version` incremented. If the account had already been reported to a bureau, its `credit_reporting_status` stays `REPORTED` after recall — bureau deletion is a manual step outside this API. As with early-out, a balance reaching zero closes an active agency placement as `CLOSED_PAID`.

### 3.6. Patient Disputes and the Credit-Reporting Freeze

A patient dispute may be filed by a `Collector` or `FinancialCounselor` with an `account_id`, a free-text `dispute_reason`, and a `dispute_amount_cents` naming the portion of the balance under dispute. The disputed amount must be greater than zero and no more than the account's `current_balance_cents` at filing; violations are rejected with `ERR_DISPUTE_AMOUNT_INVALID`. Filing stamps `filed_at` from the logical clock and sets `investigation_due_at` to the filing date plus the configured dispute-investigation day count — the deadline by which the unit must resolve the dispute.

Filing has an immediate credit-reporting consequence, but only when the debt has actually been furnished to a bureau: if an `ACTIVE` agency placement exists for the account with a non-null `credit_reported_at`, the placement closes as `CLOSED_DISPUTE` and the account's `credit_reporting_status` becomes `FROZEN_BY_DISPUTE`, with the account's `version` incremented. If the placement has not yet credit-reported — or no placement exists — the placement simply remains active and the account's credit status is unchanged; recall that an `OPEN` dispute blocks new agency placement entirely via `ERR_OPEN_DISPUTE_BLOCKS_PLACEMENT`, and blocks write-off approval via `ERR_OPEN_DISPUTE_BLOCKS_WRITE_OFF`.

Resolution is the exclusive province of a `RevenueIntegrityOfficer`, who supplies a `resolution_outcome` of `UPHELD_PATIENT` or `UPHELD_PROVIDER`; anything else fails payload validation, and resolving a dispute that is no longer `OPEN` is rejected with `ERR_INVALID_STATE`. Resolution stamps `resolved_at` and moves the dispute to `RESOLVED`. When the patient is upheld, the account's `current_balance_cents` is reduced by the `dispute_amount_cents`, clamped at zero, and if the credit status was `FROZEN_BY_DISPUTE` it becomes `REPORTED`; the account's `version` increments. When the provider is upheld, the balance stands and the `credit_reporting_status` reverts from `FROZEN_BY_DISPUTE` to its pre-dispute value — `REPORTABLE` if the debt had not yet been reported, `REPORTED` otherwise — again incrementing the account's `version`.

A dispute that outlives its investigation window expires automatically: when a clock advance installs a logical date later than `investigation_due_at`, any still-`OPEN` dispute past its deadline moves to `EXPIRED` with `resolution_outcome` set to `UNRESOLVED_EXPIRED`. Expiry treats the bureau reporting as standing: if the account's credit status was `FROZEN_BY_DISPUTE` it reverts to `REPORTED`, and the patient must re-dispute to challenge the debt again. The account's `version` is incremented, and each expired dispute counts toward the `disputes_expired` tally returned by the clock-advance call.

### 3.7. Payment Plans, Default, Cure, and Termination

A `Collector` or `FinancialCounselor` may set up a payment plan on an account by supplying the `account_id`, a positive `installment_amount_cents`, an `installment_count` of at least two and at most the configured maximum installment count, and a `first_installment_due` date. Installments follow a thirty-day cadence: installment number one is due on `first_installment_due`, and each subsequent installment falls due thirty days after its predecessor. The plan begins `ACTIVE` with `installments_paid_count` and `missed_installment_count` both zero.

Default detection runs inside the clock-advance sweep, not at read time. After a new logical time is installed, the sweep walks every `ACTIVE` plan — ordered by `first_installment_due` and then by creation time — and recomputes how many installments have come due: the count of installment due dates falling on or between `first_installment_due` and the new logical date, with an installment due exactly on the logical date counting as due. The missed count is the number due minus `installments_paid_count`, floored at zero, and is written back to `missed_installment_count` whenever it differs. When the missed count reaches two or more missed installments while the plan is still `ACTIVE`, the plan transitions to `IN_DEFAULT` and `default_flagged_at` is stamped from the logical clock; each such plan is counted in the `plans_flagged_in_default` tally.

A defaulted plan can be cured by a `Collector`, but only after a qualifying catch-up payment has posted: an installment recovery attributed to this plan, posted after `default_flagged_at`, whose amount is at least the missed installment count multiplied by the `installment_amount_cents`. Curing without such a payment is rejected with `ERR_CATCH_UP_PAYMENT_REQUIRED`, and attempting to cure a plan that is not `IN_DEFAULT` is rejected with `ERR_PLAN_NOT_IN_DEFAULT` (a 409 conflict in the same family as `ERR_INVALID_STATE`). A successful cure resets `missed_installment_count` to zero, clears `default_flagged_at`, and returns the plan to `ACTIVE`; although the transition is labelled `CURED` in audit prose, the persisted post-cure state is `ACTIVE`. Alternatively, a `RevenueIntegrityOfficer` may terminate a defaulted plan, moving it from `IN_DEFAULT` to `TERMINATED_DEFAULT` — the same not-in-default guard applies — which re-opens the account's eligibility for the bad-debt write-off path. A plan also completes automatically: when `installments_paid_count` reaches the `installment_count`, the plan moves to `COMPLETED`.

### 3.8. Recovery Posting, Vendor Fees, and Post-Write-Off Accounting

Payments enter the system as recovery transactions posted by a `Collector` or a `CollectionAgencyUser`. Each posting names the `account_id`, a positive `amount_cents`, and a `payment_kind` of `INSTALLMENT`, `LUMP_SUM`, `AGENCY_REMITTANCE`, `EARLY_OUT_REMITTANCE`, or `POST_WRITEOFF_RECOVERY`. The kind determines which companion reference is required, and the reference must resolve to an entity of the matching family: an `EARLY_OUT_REMITTANCE` must carry an `attributed_placement_id` resolving to an early-out placement, an `AGENCY_REMITTANCE` must carry an `attributed_placement_id` resolving to a collection agency placement, an `INSTALLMENT` must carry a `payment_plan_id`, and a `POST_WRITEOFF_RECOVERY` must carry a `write_off_id`. A reference that is missing or resolves to the wrong family is rejected with `ERR_RECOVERY_FK_MISMATCH`.

The amount is then checked against the recoverable ceiling for its target and rejected with `ERR_RECOVERY_EXCEEDS_BALANCE` when it exceeds it: for direct payments the ceiling is the account's `current_balance_cents`; for an installment it is the plan's remaining balance; for a post-write-off recovery it is the original write-off amount less all post-write-off recoveries already posted against that write-off.

A posted transaction reduces the account's `current_balance_cents` by the gross `amount_cents` — the patient paid gross, so the balance falls by gross even when a fee is skimmed — and adds the gross amount to the account's `recovery_total_cents`. When the payment is attributed to a placement, the vendor's contingency fee is computed as the `amount_cents` multiplied by the placement's `contingency_fee_bps` and divided by ten thousand, rounded half up to the nearest cent, and the transaction's `net_to_hospital_cents` is the gross amount minus that fee; for unattributed payments the net equals the gross. The attributed placement's `recovered_cents` grows by the gross amount. An installment payment additionally increments the plan's `installments_paid_count`, completing the plan when the count reaches `installment_count` as described in §3.7. Whenever a posting drives the account's balance to zero, the account closes as `CLOSED_PAID` and any active placement closes with it — `COMPLETED_PAID` for early-out, `CLOSED_PAID` for agency — with the account's `version` incremented. Recovery lists can be filtered by `account_id`, `payment_kind`, `attributed_placement_id`, `payment_plan_id`, or `write_off_id`.

Recoveries against an already-written-off account follow one of two accounting treatments, selected by the reserve methodology in force for the account — `DIRECT` by default, or `ALLOWANCE` where the unit has designated the allowance method. Under the direct method (`NET_AGAINST_RECOVERY`), the recovery simply increases `recovery_total_cents` by the gross amount and the historical `bad_debt_writeoff_total_cents` is left untouched — the write-off stands as fact and the recovery flows into the allowance. Under the allowance method (`RESTORE_THEN_REDUCE`), the same gross increase to `recovery_total_cents` is accompanied by a reduction of `bad_debt_writeoff_total_cents` by the recovery amount, clamped at zero; identical inputs therefore produce observably different write-off totals under the two methods. Both treatments then run the same closure check: when the cumulative post-write-off recoveries against a write-off reach or exceed that write-off's `amount_cents` and the account is still `WRITTEN_OFF`, the account transitions to `CLOSED_PAID` with its `version` incremented and its `credit_reporting_status` unchanged.

### 3.9. Write-Off Approval, Reversal, and the Medicare Bad-Debt Log

Write-offs are created in a pending state and take effect only on approval, with segregation of duties enforced at both ends. A `Collector` or `RevenueIntegrityOfficer` creates a write-off by supplying the `account_id` and the `write_off_kind` — `BAD_DEBT` or `CHARITY_CARE` — plus the kind-specific reference: a `CHARITY_CARE` write-off must carry a `screening_id` referencing the supporting screening, while a `BAD_DEBT` write-off must carry the `medicare_cost_report_year` it will be claimed against. Only full-balance write-offs exist: the written-off `amount_cents` is always a snapshot of the account's entire `current_balance_cents` at the moment of approval, and a request carrying an explicit partial amount is rejected with `ERR_PARTIAL_WRITE_OFF_NOT_SUPPORTED`. For a `BAD_DEBT` write-off, the cost report year must be no earlier than the calendar year of the `guarantor_liability_date` and no later than the calendar year of the logical clock at approval time, else `ERR_INVALID_COST_REPORT_YEAR`. A newly created write-off sits in `PENDING_APPROVAL`.

Approval is performed by a `RevenueIntegrityOfficer` and is the second OCC-guarded endpoint: the request must carry `expected_account_version` matching the account's current `version`, with mismatches rejected as `ERR_STALE_VERSION` per §2.7. Approval then enforces its preconditions in the §2.9 order. The write-off must still be `PENDING_APPROVAL`, else `ERR_INVALID_STATE`. The approving officer's `X-User-ID` must differ from the creator's — the same principal may not both request and approve a write-off, and a violation is `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. For `CHARITY_CARE`, the referenced screening must still be `EVALUATED` with an outcome of `FULL_CHARITY` or `PARTIAL_CHARITY` at approval time; a screening that has been superseded, already applied, or evaluated ineligible fails with `ERR_SCREENING_NOT_CURRENT`. For `BAD_DEBT`, the account must be in `BUCKET_120_PLUS` at approval time (else `ERR_WRITE_OFF_BEFORE_120_DAYS`) and must satisfy the write-off statement-cycle minimum (else `ERR_INSUFFICIENT_STATEMENT_CYCLE`); a bad-debt write-off taken directly from `OPEN` additionally requires that no `ACTIVE` payment plan exist for the account (else `ERR_ACTIVE_PAYMENT_PLAN_BLOCKS_WRITE_OFF`). No `OPEN` dispute may exist for the account at approval time, regardless of kind (else `ERR_OPEN_DISPUTE_BLOCKS_WRITE_OFF`). A `BAD_DEBT` write-off may be approved against an account that is `OPEN` or `IN_COLLECTIONS`; a `CHARITY_CARE` write-off requires the account to be `OPEN`.

Posting is atomic and fans out widely. The write-off moves to `POSTED`, `posted_at` is stamped from the logical clock, `approved_by_user_id` records the approver's `X-User-ID`, the account's `current_balance_cents` goes to zero, and the account's `version` increments. For `CHARITY_CARE`, the account moves from `OPEN` to `CLOSED_CHARITY`, the referenced screening moves from `EVALUATED` to `APPLIED`, `charity_writeoff_total_cents` grows by the written-off amount, `credit_reporting_status` becomes `SUPPRESSED_BY_CHARITY`, and — because charity care is never claimable as Medicare bad debt — no log entry is created. For `BAD_DEBT`, the account moves from `OPEN` or `IN_COLLECTIONS` to `WRITTEN_OFF`, `bad_debt_writeoff_total_cents` grows by the amount, and a Medicare bad-debt log entry is appended. Notably, an active agency placement is not closed by the write-off: it remains `ACTIVE` until recalled, since the balance reaching zero by write-off is not a recovery.

The Medicare log entry captures the claim's evidentiary record at the posting instant: the `write_off_id` and denormalized `account_id`, the `cost_report_year` copied from the write-off, `claimed_amount_cents` equal to the write-off amount, `collection_effort_days` measured as the whole days between the `guarantor_liability_date` and the posting date, and an `indigence_documented` flag that is true exactly when a screening exists for the account with status `EVALUATED` or `APPLIED`, an outcome of `FULL_CHARITY` or `PARTIAL_CHARITY`, and a `screened_at` on or before the write-off's posting time — superseded screenings never count. The entry's `logged_at` is stamped at creation and is immutable. Log entries are readable only by a `RevenueIntegrityOfficer`, and can be listed globally or per account or per write-off, filtered by `cost_report_year`, `write_off_id`, or `account_id`.

Reversal unwinds a posted write-off and is likewise officer-only and segregation-checked: the reversing officer's `X-User-ID` must differ from the `approved_by_user_id` recorded at approval (else `ERR_SEGREGATION_OF_DUTIES_VIOLATION`), the write-off must be `POSTED` (else `ERR_INVALID_STATE`), and the logical clock's date must be within the configured reversal window of the posting date — a reversal attempted after the window closes is rejected with `ERR_REVERSAL_WINDOW_PASSED`. Reversal restores the account's `current_balance_cents` by the full written-off amount and increments its `version`. The account's status rewinds along the path it came: from `WRITTEN_OFF` it returns to `IN_COLLECTIONS` if an `ACTIVE` agency placement still exists and to `OPEN` otherwise, and from `CLOSED_CHARITY` it returns to `OPEN`. A reversed `CHARITY_CARE` write-off reduces `charity_writeoff_total_cents` by the amount, rolls the screening from `APPLIED` back to `EVALUATED`, and reverts `credit_reporting_status` to its pre-write-off value (`REPORTABLE` if the placement was reported, `NOT_REPORTED` otherwise). A reversed `BAD_DEBT` write-off reduces `bad_debt_writeoff_total_cents` by the amount and voids the linked log entry by stamping its `voided_at` — the entry is voided in place, never deleted, preserving the append-only audit trail. The write-off itself ends in `REVERSED`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource, transition a state, or read data return `200 OK`. Error responses carry the HTTP status paired with each error identifier in §5. The table below is a summary only — request payloads, preconditions, and side effects are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/self-pay/accounts` | Register a new self-pay account | Collector, RevenueIntegrityOfficer |
| GET | `/self-pay/accounts` | List self-pay accounts with optional filters | Collector, FinancialCounselor, RevenueIntegrityOfficer, CollectionAgencyUser |
| GET | `/self-pay/accounts/{id}` | Get a single self-pay account (recomputes aging on read) | Collector, FinancialCounselor, RevenueIntegrityOfficer, CollectionAgencyUser |
| POST | `/self-pay/accounts/{id}/statements` | Issue a statement for an account | Collector |
| GET | `/self-pay/accounts/{id}/statements` | List statements for an account | Collector, FinancialCounselor, RevenueIntegrityOfficer |
| GET | `/self-pay/statements/{statementId}` | Get a single statement | Collector, FinancialCounselor, RevenueIntegrityOfficer |
| POST | `/self-pay/statements/{statementId}/mark-delivered` | Mark a statement delivered | Collector |
| POST | `/self-pay/statements/{statementId}/mark-returned` | Mark a statement returned undeliverable | Collector |
| POST | `/self-pay/presumptive-charity-screenings` | Create a presumptive charity screening (OCC-guarded) | FinancialCounselor |
| GET | `/self-pay/presumptive-charity-screenings/{screeningId}` | Get a screening | Collector, FinancialCounselor, RevenueIntegrityOfficer |
| GET | `/self-pay/accounts/{id}/presumptive-charity-screenings` | List screenings for an account | Collector, FinancialCounselor, RevenueIntegrityOfficer |
| POST | `/self-pay/presumptive-charity-screenings/{screeningId}/evaluate` | Evaluate a pending screening | FinancialCounselor |
| POST | `/self-pay/early-out-placements` | Place an account with an early-out vendor | Collector |
| GET | `/self-pay/early-out-placements/{placementId}` | Get an early-out placement | Collector, RevenueIntegrityOfficer |
| GET | `/self-pay/accounts/{id}/early-out-placements` | List early-out placements for an account | Collector, RevenueIntegrityOfficer |
| POST | `/self-pay/early-out-placements/{placementId}/recall` | Recall an early-out placement | Collector |
| POST | `/self-pay/collection-agency-placements` | Place an account with a collection agency (direct or escalation) | Collector |
| GET | `/self-pay/collection-agency-placements/{placementId}` | Get a collection agency placement | Collector, RevenueIntegrityOfficer, CollectionAgencyUser |
| GET | `/self-pay/accounts/{id}/collection-agency-placements` | List agency placements for an account | Collector, RevenueIntegrityOfficer, CollectionAgencyUser |
| POST | `/self-pay/collection-agency-placements/{placementId}/recall` | Recall an agency placement (fee logic by recall window) | Collector |
| POST | `/self-pay/collection-agency-placements/{placementId}/mark-credit-reported` | Mark the placement as reported to a consumer bureau | CollectionAgencyUser |
| POST | `/self-pay/patient-disputes` | File a patient dispute against an account | Collector, FinancialCounselor |
| GET | `/self-pay/patient-disputes/{disputeId}` | Get a dispute | Collector, FinancialCounselor, RevenueIntegrityOfficer |
| GET | `/self-pay/accounts/{id}/patient-disputes` | List disputes for an account | Collector, FinancialCounselor, RevenueIntegrityOfficer |
| POST | `/self-pay/patient-disputes/{disputeId}/resolve` | Resolve an open dispute | RevenueIntegrityOfficer |
| POST | `/self-pay/payment-plans` | Set up a payment plan on an account | Collector, FinancialCounselor |
| GET | `/self-pay/payment-plans/{planId}` | Get a payment plan | Collector, FinancialCounselor, RevenueIntegrityOfficer |
| GET | `/self-pay/accounts/{id}/payment-plans` | List payment plans for an account | Collector, FinancialCounselor, RevenueIntegrityOfficer |
| POST | `/self-pay/payment-plans/{planId}/cure` | Cure a defaulted plan after catch-up payment | Collector |
| POST | `/self-pay/payment-plans/{planId}/terminate` | Terminate a defaulted plan | RevenueIntegrityOfficer |
| POST | `/self-pay/bad-debt-write-offs` | Create a write-off pending approval | Collector, RevenueIntegrityOfficer |
| GET | `/self-pay/bad-debt-write-offs/{writeOffId}` | Get a write-off | Collector, RevenueIntegrityOfficer |
| GET | `/self-pay/bad-debt-write-offs` | List write-offs with optional filters | Collector, RevenueIntegrityOfficer |
| GET | `/self-pay/accounts/{id}/bad-debt-write-offs` | List write-offs for an account | Collector, RevenueIntegrityOfficer |
| POST | `/self-pay/bad-debt-write-offs/{writeOffId}/approve` | Approve a pending write-off (OCC-guarded, segregation of duties) | RevenueIntegrityOfficer |
| POST | `/self-pay/bad-debt-write-offs/{writeOffId}/reverse` | Reverse a posted write-off within the reversal window | RevenueIntegrityOfficer |
| GET | `/self-pay/medicare-bad-debt-log-entries/{entryId}` | Get a single Medicare bad-debt log entry | RevenueIntegrityOfficer |
| GET | `/self-pay/medicare-bad-debt-log-entries` | List Medicare bad-debt log entries with optional filters | RevenueIntegrityOfficer |
| GET | `/self-pay/accounts/{id}/medicare-bad-debt-log-entries` | List log entries for an account | RevenueIntegrityOfficer |
| GET | `/self-pay/bad-debt-write-offs/{writeOffId}/medicare-bad-debt-log-entries` | List log entries for a write-off | RevenueIntegrityOfficer |
| POST | `/self-pay/recovery-transactions` | Post a recovery or payment against an account | Collector, CollectionAgencyUser |
| GET | `/self-pay/recovery-transactions/{transactionId}` | Get a recovery transaction | Collector, RevenueIntegrityOfficer, CollectionAgencyUser |
| GET | `/self-pay/recovery-transactions` | List recovery transactions with optional filters | Collector, RevenueIntegrityOfficer, CollectionAgencyUser |
| GET | `/self-pay/accounts/{id}/recovery-transactions` | List recovery transactions for an account | Collector, RevenueIntegrityOfficer, CollectionAgencyUser |
| POST | `/self-pay/vendor-performance-snapshots` | Generate a vendor performance snapshot for a window | RevenueIntegrityOfficer |
| GET | `/self-pay/vendor-performance-snapshots/{snapshotId}` | Get a snapshot | RevenueIntegrityOfficer |
| GET | `/self-pay/vendor-performance-snapshots` | List snapshots with optional vendor filter | RevenueIntegrityOfficer |
| POST | `/self-pay/_clock/set_current_utc` | Advance the logical clock and run the default and expiry sweeps | Collector, FinancialCounselor, RevenueIntegrityOfficer |

## 5. Error Code Catalogue

The catalogue below pairs each error identifier with its HTTP status code. Trigger conditions for each error are defined in the §2 and §3 narratives.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_SCREENING_NOT_CURRENT` | 409 Conflict |
| `ERR_CHARITY_ELIGIBLE_BLOCKS_PLACEMENT` | 409 Conflict |
| `ERR_ACCOUNT_NOT_SCREENABLE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_STATEMENT_ELIGIBLE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_IN_EARLY_OUT_BUCKET` | 409 Conflict |
| `ERR_ACCOUNT_NOT_IN_AGENCY_BUCKET` | 409 Conflict |
| `ERR_INSUFFICIENT_STATEMENT_CYCLE` | 409 Conflict |
| `ERR_WRITE_OFF_BEFORE_120_DAYS` | 409 Conflict |
| `ERR_ACTIVE_PLACEMENT_EXISTS` | 409 Conflict |
| `ERR_RECALL_DEADLINE_PASSED` | 409 Conflict |
| `ERR_RECALL_WINDOW_STILL_OPEN` | 409 Conflict |
| `ERR_OPEN_DISPUTE_BLOCKS_PLACEMENT` | 409 Conflict |
| `ERR_OPEN_DISPUTE_BLOCKS_WRITE_OFF` | 409 Conflict |
| `ERR_DISPUTE_AMOUNT_INVALID` | 422 Unprocessable Entity |
| `ERR_ACTIVE_PAYMENT_PLAN_BLOCKS_WRITE_OFF` | 409 Conflict |
| `ERR_PLAN_NOT_IN_DEFAULT` | 409 Conflict |
| `ERR_CATCH_UP_PAYMENT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_RECOVERY_FK_MISMATCH` | 400 Bad Request |
| `ERR_RECOVERY_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_PARTIAL_WRITE_OFF_NOT_SUPPORTED` | 422 Unprocessable Entity |
| `ERR_INVALID_COST_REPORT_YEAR` | 422 Unprocessable Entity |
| `ERR_REVERSAL_WINDOW_PASSED` | 409 Conflict |
