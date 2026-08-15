# Positive Pay & Check Fraud Prevention API — Product Requirements Document

## 1. Introduction

Community and regional banks that offer treasury management services to commercial depositors carry a standing exposure to check fraud: forged signatures, altered amounts, counterfeit stock, and payee manipulation all surface as paper or image items presented against business accounts days after the checks were written. Positive Pay is the industry's standard countermeasure — the customer tells the bank what it issued, the bank pays only what matches, and everything else is held for a human decision. This document specifies the API for a Positive Pay & Check Fraud Prevention service operated by a bank on behalf of its enrolled business customers.

The API is mounted under `/treasury` and covers the full operating loop of the service: onboarding an enrollment and training its users, registering issued checks through file uploads, ingesting presented items and matching them synchronously, working the resulting exception queue against firm decision deadlines, maintaining ACH debit block and filter rules on the same accounts, allocating fees and liability when items go wrong, and running the daily and monthly checkpoint processes that keep the book clean. Three service tiers are supported — `POSITIVE_PAY` (check number and amount matching), `PAYEE_POSITIVE_PAY` (which adds payee-name verification), and `REVERSE_POSITIVE_PAY` (a low-volume arrangement in which the customer submits no issue files and instead reviews every presented item).

Two design commitments shape everything that follows. First, every decision the system makes automatically — a match verdict, a fee accrual, a default pay or return at a missed deadline, an account review hold — must be reconstructible after the fact from stored data, because disputes over unauthorized items are decided on exactly that record. Second, duties are segregated: the user who uploaded an issue file may not decide exceptions on checks that file registered, and the bank operator who opens a large liability case may not be the one who resolves it. Implementers should read §2 for the system-wide contracts and §3 for the business workflows in which those contracts are exercised.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting rules that apply to every endpoint in the service.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request in which either header is missing or malformed, or whose role name is not recognized, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The recognized roles are exactly `BankTreasuryManager`, `BankOps`, `CustomerAdmin`, `CustomerManager`, `CustomerDecisionMaker`, and `CustomerViewer`.

The two bank-side roles are opaque operator identities. When `X-User-Role` is `BankTreasuryManager` or `BankOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `assigned_bank_user_id` on a liability case when a `BankOps` operator starts review, as `resolved_by_bank_user_id` when a `BankTreasuryManager` resolves one, or as `waived_by` on a waived fee entry — but it never compares the header value to any entity's `id`.

The four customer-side roles are entity-backed. When `X-User-Role` is `CustomerAdmin`, `CustomerManager`, `CustomerDecisionMaker`, or `CustomerViewer`, `X-User-ID` must be the `id` of an existing `EnrollmentUser` record, and that record's `user_role` field (one of `ADMIN`, `MANAGER`, `DECISION_MAKER`, `VIEWER`) must correspond to the claimed role: `ADMIN` for `CustomerAdmin`, `MANAGER` for `CustomerManager`, `DECISION_MAKER` for `CustomerDecisionMaker`, and `VIEWER` for `CustomerViewer`. Ownership checks compare the resource's enrollment chain to the acting user's `enrollment_id`: a customer-role caller may only touch resources whose owning enrollment equals the `enrollment_id` of their own `EnrollmentUser` record, and any attempt to reach across enrollment boundaries is rejected with `ERR_CROSS_ENROLLMENT_ACCESS` (HTTP 403).

Each endpoint authorizes a specific set of roles, enumerated in §4. A caller whose role is not listed for the endpoint, or a customer-role caller whose `EnrollmentUser.user_role` does not match the claimed role, is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). `CustomerViewer` is read-only across the entire API.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the full size of the filtered result set and `has_more` indicates whether further items exist beyond the returned page.

### 2.4. Common Resource Properties and Version Semantics

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on any mutation of the resource.
- `version` (integer): starts at creation and increments by one on every mutation of the resource.

`OpsRun` records are the single exception to this convention: an ops run is an immutable checkpoint receipt and carries only `id` and `created_at`. It has no `updated_at` and no `version`.

Version increments deserve one refinement on `TreasuryEnrollment`. The enrollment's `version` bumps only on direct lifecycle or configuration writes against the enrollment itself — a configuration patch, an activation, a suspension, a termination, a tier change, or the automatic suspension described in §3.8. Recomputation of the enrollment's computed counters (`open_exception_count`, `provisional_credit_outstanding_cents`, `ytd_bank_loss_cents`) does not increment `version`, even though those counters change in response to activity elsewhere. `AchDebitRule.version` increments on each accepted rule edit; the remaining entities increment `version` on any mutation as stated above.

### 2.5. The Logical Clock

All temporal rules in this document — decision deadlines, stale-dating, claim windows, ACH rule expiry, billing-period closure, no-show detection — are evaluated against a single server-side logical clock, never against wall-clock time. Before any operator intervention, the logical clock starts at exactly `2026-08-01T00:00:00Z`. A `BankOps`-only test-driving capability advances the clock to a supplied instant: the caller posts `to_iso8601` and receives `current_utc` echoing the new logical time. Once set, the clock remains where it was set until set again; it never falls back to wall-clock time. Where a timestamp input defaults (for example `presented_at` on a presented item), the default is the current value of this logical clock.

### 2.6. Integer-Cents Monetary Precision

All monetary quantities are represented as integer cents — `amount_cents`, `cumulative_paid_cents`, `claim_amount_cents`, and every fee and liability figure. Comparisons and accumulations on these values are exact integer arithmetic with no rounding. Where a calculation produces a quotient — the payee-match score, the shared-liability split, the adoption-report basis points — the specific rounding rule is stated alongside the calculation in §3; in every such case the result is an integer. Timestamps used in temporal rules are compared at second precision in UTC, and date-only rules (stale-dating, ACH windows) compare calendar dates.

### 2.7. Optimistic Concurrency Control

Three write operations are protected by optimistic concurrency control, and each names its own expected-version field:

- A configuration patch to an enrollment must carry `expected_enrollment_version`, equal to the enrollment's current `version` as the client last observed it.
- A tier change on an enrollment must likewise carry `expected_enrollment_version` matching the enrollment's current `version`.
- An edit to an ACH debit rule must carry `expected_ach_rule_version` matching the rule's current `version`.

If the supplied expected version does not equal the parent entity's current `version` — because another accepted write has advanced the version since the client last read the entity — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The expected-version field is non-optional on these three operations. Endpoints not named here do not accept a version field. The stale-version check is evaluated before any state preconditions on the same request, so a stale version surfaces as `ERR_STALE_VERSION` even when the request would also have failed a later check.

### 2.8. Segregation of Duties

Two segregation-of-duties rules are enforced, both returning HTTP 403:

1. **Uploader may not decision own exceptions.** When deciding an exception whose `issued_check_id` is non-null, the caller's `X-User-ID` must differ from the `uploaded_by_user_id` of the issue file that registered that check. A violation is rejected with `ERR_SOD_UPLOAD_DECISION_CONFLICT`. Note that `CustomerManager` holds both upload and decision authority; this rule, not the role matrix, is what prevents self-approval.
2. **Case assignee may not resolve large cases.** When resolving a liability case whose `claim_amount_cents` is strictly greater than 25000 cents, the resolving `BankTreasuryManager`'s `X-User-ID` must differ from the case's `assigned_bank_user_id`. A violation is rejected with `ERR_SOD_CASE_RESOLUTION_CONFLICT`. Claims of 25000 cents or less may be resolved by the same operator.

### 2.9. Idempotent Submissions

Two intake endpoints are idempotent so that a retried submission never double-posts. An issue-file upload is keyed by `file_reference`, unique per enrollment: if the reference has been seen before for that enrollment and the canonicalized rows hash identically (the server stores this as `payload_hash`, a SHA-256 over the canonicalized rows array), the server replays the original upload response rather than processing the rows again; if the reference has been seen with a different payload hash, the request is rejected with `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409). Presented-item ingestion accepts an optional `idempotency_key`: a replay of the same key with an identical payload returns the original item, while the same key with a different payload is rejected with `ERR_IDEMPOTENCY_CONFLICT`. A business-level re-presentment — the same account and check number presented again without reusing a key — is not an idempotency error at all; it flows through matching and ordinarily lands as `DUPLICATE_PRESENTMENT` (see §3.4).

### 2.10. Validation Order and Error Precedence

When several checks could fail on the same request, they are evaluated in a fixed priority order, and the first failure wins:

1. **Header presence and role recognition** — a missing or malformed `X-User-ID` or `X-User-Role`, or an unrecognized role name, yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization** — the claimed role must be listed for the endpoint and, for customer roles, must match the `EnrollmentUser.user_role`; otherwise `ERR_FORBIDDEN_FOR_ROLE`.
3. **Ownership scope** — for customer-role callers, the target resource's enrollment chain must equal the caller's `enrollment_id`; otherwise `ERR_CROSS_ENROLLMENT_ACCESS`.
4. **Request shape** — required fields present, types correct, enum membership valid, amounts positive integers, row schema valid, a `FILTER` rule carrying `max_amount_cents` and a `BLOCK` rule omitting it, an extend-deadline target within its allowed window; shape failures yield `ERR_INVALID_REQUEST` and surface before any resource lookup, so a malformed body on a nonexistent id returns `ERR_INVALID_REQUEST`. One exception runs the other way: a malformed path identifier resolves as `ERR_NOT_FOUND`.
5. **Existence** — path and body-referenced identifiers are validated left to right; the first missing one yields `ERR_NOT_FOUND`.
6. **Optimistic concurrency** — the expected-version checks of §2.7, yielding `ERR_STALE_VERSION`. This is evaluated before all state preconditions.
7. **State preconditions**, outermost scope first: a mutation against a `TERMINATED` enrollment yields `ERR_ENROLLMENT_TERMINATED`; a customer write or child mutation while the enrollment is not `ACTIVE` yields `ERR_ENROLLMENT_NOT_ACTIVE`; only then do resource-state rules fire — `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_ACCOUNT_HAS_OPEN_EXCEPTIONS`, `ERR_ENROLLMENT_NOT_SETTLED`, `ERR_ENROLLMENT_NOT_ACTIVATABLE`, `ERR_CHECK_NOT_VOIDABLE`, `ERR_EXCEPTION_NOT_OPEN`, `ERR_ITEM_NOT_REVERSIBLE`, `ERR_ITEM_NOT_CLAIMABLE`, `ERR_CASE_NOT_OPEN`, `ERR_FEE_ENTRY_NOT_WAIVABLE`, `ERR_SESSION_NOT_COMPLETABLE`, `ERR_PERIOD_ALREADY_BILLED`.
8. **Temporal business rules** — `ERR_DECISION_DEADLINE_PASSED`, `ERR_CLAIM_WINDOW_CLOSED`, `ERR_PERIOD_NOT_CLOSED`.
9. **Uniqueness and policy constraints** — `ERR_TIER_FORBIDS_ISSUE_FILES`, `ERR_TIER_CHANGE_NOT_ALLOWED`, `ERR_IDEMPOTENCY_CONFLICT`, `ERR_ACH_RULE_WINDOW_OVERLAP`, `ERR_TRAINING_SCHEDULE_CONFLICT`, the two segregation-of-duties rejections, and `ERR_ACH_RULE_NOT_ACTIVE`.
10. **Waiver authority caps** — `ERR_WAIVER_EXCEEDS_AUTHORITY`, evaluated last, after the entry's waivability has been established.

### 2.11. Resource Existence and Referenced Identifiers

Identifiers appearing in the URL path or referenced in the request body (such as an `enrollment_id`, `account_id`, or `presented_item_id`) are validated for existence in left-to-right order, and the first identifier that does not resolve to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404). Body-referenced links — the account an upload targets, the item a liability claim is filed against, the users recorded as training attendees — are checked the same way after the path identifiers. Existence checks run after authentication, authorization, and request-shape validation, and before any state or business rule evaluation, per the ordering in §2.10.

## 3. Business Logic & Workflows

### 3.1. Enrollment Onboarding, Training, and Lifecycle

A bank treasury manager opens the relationship by creating a `TreasuryEnrollment` with the customer's legal `business_name`, the service `tier` (`POSITIVE_PAY`, `PAYEE_POSITIVE_PAY`, or `REVERSE_POSITIVE_PAY`), and the `default_decision` (`PAY` or `RETURN`) that governs exceptions the customer leaves undecisioned. Four behavioral knobs may be supplied at creation or left to their defaults: `deadline_mode` selects the deadline variant and defaults to `SAME_DAY_CUTOFF` (the alternative is `ROLLING_HOURS`); `decision_window_hours` defaults to 24 and must lie between 1 and 72 inclusive; `amount_tolerance_cents` defaults to 0 and must be non-negative; `payee_score_threshold` defaults to 85 and must lie between 0 and 100 inclusive. Two further knobs govern automated risk responses: `stale_days`, defaulting to 180, sets the age at which an unpaid registered check becomes `STALE_DATED`; and `loss_suspension_threshold_cents`, which defaults to null, arms an automatic enrollment suspension described in §3.8 — a null value disables that trigger. A new enrollment starts in `PENDING_ACTIVATION` with its counters zeroed: `open_exception_count` at zero, `provisional_credit_outstanding_cents` at zero, and `ytd_bank_loss_cents` at zero.

Enrollment users are provisioned through `EnrollmentUser` records carrying `enrollment_id`, a `display_name`, and a `user_role`. A `BankTreasuryManager` may create users for any enrollment; a `CustomerAdmin` may create users only inside their own enrollment. The user list can be filtered by `enrollment_id` and `user_role`.

Training is a hard gate on first activation. A `BankOps` operator schedules a `TrainingSession` by supplying `enrollment_id`, a `trainer_id` (an opaque bank trainer identifier used as the scheduling resource), and a `scheduled_start` and `scheduled_end` in UTC; the end must be strictly after the start or the request fails shape validation with `ERR_INVALID_REQUEST`. Scheduling enforces a per-trainer conflict rule: each scheduled session occupies a buffered window that begins 30 minutes before its start and ends 30 minutes after its end, and a new session for the same trainer whose buffered window intersects the buffered window of any existing `SCHEDULED` session is rejected with `ERR_TRAINING_SCHEDULE_CONFLICT`. Because of the buffer, even exact adjacency of the raw windows — one session ending exactly when another begins — counts as a conflict. Sessions can be listed by `enrollment_id`, `trainer_id`, or `status`. A `BankOps` operator completes a session by recording `attendee_user_ids`; completion requires the session still be `SCHEDULED` (otherwise `ERR_SESSION_NOT_COMPLETABLE`), a non-empty attendee list, and every listed id belonging to an `EnrollmentUser` of this enrollment (an empty list fails shape validation with `ERR_INVALID_REQUEST`; an unknown user id yields `ERR_NOT_FOUND`). A scheduled session may instead be cancelled, moving it from `SCHEDULED` to `CANCELLED` (again, `ERR_SESSION_NOT_COMPLETABLE` guards the state). A session still `SCHEDULED` when its `scheduled_end` falls behind the logical clock is marked `NO_SHOW` by the daily sweep.

Activation from `PENDING_ACTIVATION` to `ACTIVE` is performed by a `BankTreasuryManager` and requires at least one `COMPLETED` training session for the enrollment; without one the request is rejected with `ERR_ENROLLMENT_NOT_ACTIVATABLE`. A manager may also suspend an `ACTIVE` enrollment, moving it to `SUSPENDED`, and later reactivate it. Re-activation from `SUSPENDED` does not re-check the training gate — that gate applies only to the initial activation. While an enrollment is `SUSPENDED`, all customer-side writes are rejected with `ERR_ENROLLMENT_NOT_ACTIVE`: issue-file uploads, check voids, exception decisions, ACH rule writes, and liability filings all fail, while item matching, sweeps, and default processing continue to run. Any mutation against the resources of a `TERMINATED` enrollment is rejected with `ERR_ENROLLMENT_TERMINATED`, and this check fires before the not-active check when both could apply.

Termination moves an enrollment from `ACTIVE` or `SUSPENDED` to the terminal `TERMINATED` state, but only once the book is settled: every account of the enrollment must be `CLOSED` and the enrollment's `open_exception_count` must be zero, otherwise the request is rejected with `ERR_ENROLLMENT_NOT_SETTLED`.

Configuration edits are shared between the bank and the customer: a `BankTreasuryManager` or the enrollment's own `CustomerAdmin` may patch `default_decision`, `decision_window_hours`, `amount_tolerance_cents`, `payee_score_threshold`, `stale_days`, or `loss_suspension_threshold_cents`. The patch must carry `expected_enrollment_version` per §2.7. Editing `default_decision` changes only future exceptions — the `default_decision_snapshot` pinned on each existing `OPEN` exception is not retro-changed.

Tier migration is a manager-only operation taking `new_tier` and `expected_enrollment_version`. Two gates apply, both rejecting with `ERR_TIER_CHANGE_NOT_ALLOWED`: the enrollment's `open_exception_count` must be zero, and a migration to `REVERSE_POSITIVE_PAY` is permitted only when the enrollment's issued-check volume over the trailing ninety days — counted across all of its accounts, inclusive of both window endpoints, and counting rows in every status including `REGISTERED`, `CONSUMED`, `VOIDED`, and `STALE_DATED` — is at most 75 rows; a 76th row in the window makes the enrollment ineligible. An accepted tier change sets `tier` to `new_tier` and increments the enrollment's `version`. The enrollment resource can be read by all roles; its report and statement endpoints are described in §3.7 and §3.9.

### 3.2. Accounts and the Settlement Ledger

Each enrolled checking relationship is an `Account`, created by a `BankTreasuryManager` with an `enrollment_id`, an `account_number` of 6 to 17 digits that is unique within the enrollment, and an optional `payment_review_threshold_cents`. Accounts may not be created under a `TERMINATED` enrollment (`ERR_ENROLLMENT_TERMINATED`). A new account starts `ACTIVE` with `cumulative_paid_cents`, `cumulative_reversed_cents`, and `net_settled_cents` all zero. The account list can be filtered by `enrollment_id` and `status`.

The account maintains a chronological settlement ledger. On every item pay event — a clean auto-match, an exception decided to pay, or an exception defaulted to pay — the item's `amount_cents` is added to `cumulative_paid_cents`. On every reversal, the amount is added to `cumulative_reversed_cents`. Both gross counters only ever increase; `net_settled_cents` is recomputed on every mutation as the paid total minus the reversed total. The invariant is that a pay event followed by its own reversal leaves `net_settled_cents` exactly where it was before the payment, while both gross counters have moved.

Immediately after every pay-side ledger update, the review threshold is evaluated: if `payment_review_threshold_cents` is non-null, the account is still `ACTIVE`, and `cumulative_paid_cents` has reached or exceeded the threshold — equality triggers — the account automatically transitions to `REVIEW_HOLD`. While an account is in `REVIEW_HOLD`, auto-matching is suspended: every item ingested against it becomes an exception with reason `ACCOUNT_HOLD_REVIEW` (see §3.4). A `BankOps` operator clears the hold, returning the account from `REVIEW_HOLD` to `ACTIVE`; clearing the hold does not retro-process items already held — it only restores clean auto-matching for future items — and attempting it on an account that is not in `REVIEW_HOLD` fails with `ERR_ACCOUNT_NOT_ACTIVE`.

Closing an account is a manager action that moves it from `ACTIVE` or `REVIEW_HOLD` to the terminal `CLOSED` state. The close is blocked while any exception with this `account_id` is `OPEN` (`ERR_ACCOUNT_HAS_OPEN_EXCEPTIONS`). A close from `ACTIVE` additionally requires that the owning enrollment not be `TERMINATED` (`ERR_ENROLLMENT_TERMINATED`).

### 3.3. Issued-Check File Intake

Customers on the `POSITIVE_PAY` and `PAYEE_POSITIVE_PAY` tiers register their check runs by uploading an issue file. A `CustomerAdmin` or `CustomerManager` submits the target `enrollment_id` and `account_id`, a client-chosen `file_reference`, and a `rows` array in which each row carries `check_number`, `amount_cents`, `payee_name`, and `issue_date`. Whole-file gates run before any row is processed: the enrollment must be `ACTIVE` (a write against a `TERMINATED` enrollment fails first with `ERR_ENROLLMENT_TERMINATED`, and any other non-active status fails with `ERR_ENROLLMENT_NOT_ACTIVE`); the tier must not be `REVERSE_POSITIVE_PAY`, since reverse-tier customers by definition submit no issue files (`ERR_TIER_FORBIDS_ISSUE_FILES`); and the target account must belong to the named enrollment and be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE` — ingesting against a `CLOSED` account fails the same way). Idempotent replay is then resolved on `file_reference` exactly as §2.9 describes.

Rows that survive the gates are validated independently, in row order, and the upload accepts partial success. A row is rejected when its `check_number` is not 1 to 12 digits, when `amount_cents` is not a positive integer, when `payee_name` is not 1 to 80 characters, or when `issue_date` is not a valid ISO calendar date on or before the current logical date. A row is also rejected when the same `check_number` appears twice within the file, and when the account already holds an issued check with that number in `REGISTERED`, `CONSUMED`, or `VOIDED` status — a number whose previous check went `STALE_DATED` may legitimately be re-issued. Per-row rejections are collected on the upload record as `row_errors`, an array of objects giving the `row_index`, the offending `check_number`, and a human-readable `reason`.

The resulting `IssueFileUpload` is immutable and self-describing: `row_count` is the total rows submitted, `accepted_row_count` the rows that produced checks, and `rejected_row_count` the rows that failed. Its `status` is assigned synchronously at upload — `ACCEPTED` when every row produced a check, `PARTIALLY_ACCEPTED` when some did, and `REJECTED` when none did. The server also records `uploaded_by_user_id` from the caller's `X-User-ID`; this field is the segregation-of-duties source used later at exception decision time. Uploads can be listed and filtered by `enrollment_id`, `account_id`, `uploaded_by_user_id`, and `status`.

Every accepted row creates an `IssuedCheck` in `REGISTERED` status, linked to its `account_id` and the `issue_file_id` of the upload that registered it, with the row's `check_number`, `amount_cents`, `payee_name`, and `issue_date`. A check number is unique per account among checks that are not `STALE_DATED`. The issued-check list can be filtered by `account_id`, `issue_file_id`, `consumed_by_item_id`, `status`, and `check_number`.

A `CustomerAdmin` or `CustomerManager` may void a registered check, moving it from `REGISTERED` to the terminal `VOIDED` status. The void requires the enrollment to be `ACTIVE` (with the usual `ERR_ENROLLMENT_TERMINATED` / `ERR_ENROLLMENT_NOT_ACTIVE` precedence) and the check to still be `REGISTERED` — voiding a `CONSUMED`, already-`VOIDED`, or `STALE_DATED` check is rejected with `ERR_CHECK_NOT_VOIDABLE`. Checks leave `REGISTERED` by two other paths described elsewhere: payment consumes them (§3.4 and §3.5), and the daily sweep stale-dates them (§3.9). A returned item does not consume its check: the check remains `REGISTERED`, and a later re-presentment matches against it again.

### 3.4. Presented-Item Ingestion and the Matching Cascade

Presented items enter through `BankOps` ingestion. Each request names the `account_id` and supplies the item as presented: `check_number`, `amount_cents` (a positive integer), the payee text exactly as read off the item in `payee_name_raw`, and the presentment `channel` — `TELLER`, `REMOTE_DEPOSIT`, or `CLEARING`. `presented_at` may be supplied explicitly and defaults to the current logical clock; `idempotency_key` may be supplied for replay protection per §2.9. Ingestion runs the matching cascade synchronously and returns the item with its verdict.

The cascade is an ordered rule chain; the first rule that fires decides `match_result` and stops evaluation:

1. **Tier gate.** If the enrollment's `tier` is `REVERSE_POSITIVE_PAY`, the verdict is `REVERSE_REVIEW` — reverse-tier customers review everything, so no matching is attempted.
2. **Account hold.** If the account is in `REVIEW_HOLD`, the verdict is `ACCOUNT_HOLD_REVIEW`.
3. **Existence.** The system looks for an `IssuedCheck` on the same account with the same `check_number`. If there is none, the verdict is `NO_ISSUE_RECORD`.
4. **Voided.** If the matched check is `VOIDED`, the verdict is `VOIDED_ITEM`.
5. **Stale.** If the matched check is `STALE_DATED`, the verdict is `STALE_DATED_ITEM`.
6. **Duplicate.** If the matched check is `CONSUMED`, the verdict is `DUPLICATE_PRESENTMENT`.
7. **Amount.** If the absolute difference between the item's `amount_cents` and the check's `amount_cents` exceeds the enrollment's `amount_tolerance_cents`, the verdict is `AMOUNT_MISMATCH`. A difference exactly equal to the tolerance still counts as an amount match.
8. **Payee.** If the tier is `PAYEE_POSITIVE_PAY`, the payee-match score is computed (below) and recorded on the item as `match_score`; a score below the enrollment's `payee_score_threshold` yields `PAYEE_MISMATCH`. On tiers that do not verify payees, `match_score` remains null.
9. **Clean.** If nothing above fired, the verdict is `CLEAN`.

The payee-match score compares the issued `payee_name` against the presented `payee_name_raw`. Both names are normalized to uppercase and split into tokens on any non-alphanumeric character, with empty tokens discarded; if either side yields no tokens, the score is zero. Otherwise each issued token earns a similarity: 100 when some presented token equals it exactly; otherwise 50 when some presented token is a prefix of it or it is a prefix of some presented token, provided the shorter of the two tokens has length at least 3; otherwise 0. Each issued token's contribution is its own length multiplied by its similarity and divided by the total character length of all issued tokens, rounded down to a whole number — and this per-token rounding down is applied before summing. The score is the plain sum of those contributions with no further rounding. Scoring the tokens in this pinned order matters: summing the unrounded contributions first and rounding once at the end is a forbidden alternate reading, because the two procedures can differ by enough points to flip a pass into a mismatch at the threshold boundary.

A `CLEAN` verdict pays the item on the spot: it moves from `RECEIVED` to `PAID`, `paid_at` is stamped from the logical clock, the account ledger and review-threshold evaluation of §3.2 run, and the matched check moves from `REGISTERED` to `CONSUMED` with its `consumed_by_item_id` set to the paying item's id.

Any non-`CLEAN` verdict — including `REVERSE_REVIEW` and `ACCOUNT_HOLD_REVIEW` — holds the item: it moves from `RECEIVED` to `EXCEPTION_HELD`, an `OPEN` exception is created as §3.5 describes, and the item's `exception_id` is set to that exception's id. Items can be listed and filtered by `account_id`, `exception_id`, and `status`.

A paid item can later be reversed by a `BankTreasuryManager`, moving it from `PAID` to `REVERSED`; the request carries a free-text `reason`, and any attempt to reverse an item not in `PAID` is rejected with `ERR_ITEM_NOT_REVERSIBLE`. The reversal adds the item's `amount_cents` to the account's `cumulative_reversed_cents` and recomputes `net_settled_cents`, returning the net figure to its pre-payment value. Note that only the direct `PAID` status is reversible — items that reached `DEFAULT_PAID` are not reversed through this operation.

### 3.5. The Exception Queue: Decisions, Deadlines, and Defaults

Every held item is shadowed by an `ExceptionItem`, created `OPEN` at ingestion with its `enrollment_id` denormalized from the item's account, its `account_id`, its `presented_item_id`, and — whenever the cascade matched a check — its `issued_check_id`, which stays null for the `NO_ISSUE_RECORD` and `REVERSE_REVIEW` reasons. The exception's `reason` mirrors the item's `match_result`: one of `NO_ISSUE_RECORD`, `AMOUNT_MISMATCH`, `PAYEE_MISMATCH`, `VOIDED_ITEM`, `STALE_DATED_ITEM`, `DUPLICATE_PRESENTMENT`, `REVERSE_REVIEW`, or `ACCOUNT_HOLD_REVIEW`. Two values are pinned at creation and never re-derived: `default_decision_snapshot` captures the enrollment's `default_decision` as it stood at that moment (later configuration edits do not retro-change it), and `decision_deadline_at` is computed from the item's `presented_at` as described below. The exception starts with `extended_once` false, `decided_by_user_id` and `decided_at` null, and `liability_party` null. Creation also accrues a provisional 200-cent exception fee (§3.7) linked through the exception's `fee_entry_id`, and adds one to the enrollment's `open_exception_count`. The queue can be listed and filtered by `enrollment_id`, `account_id`, `presented_item_id`, `issued_check_id`, `fee_entry_id`, `decided_by_user_id`, `status`, or `reason`.

The deadline computation has two variants. Under `SAME_DAY_CUTOFF`, an item presented before 14:00:00 UTC gets a deadline of 20:00:00 UTC that same day, while an item presented at exactly 14:00:00 UTC or later gets 20:00:00 UTC on the following day. Under `ROLLING_HOURS`, the deadline is exactly `decision_window_hours` hours after `presented_at` — an item presented at 13:00:00 UTC with a 24-hour window is due at 13:00:00 UTC the next day, where the same presentment under `SAME_DAY_CUTOFF` would be due at 20:00:00 UTC that evening. The deadline is inclusive for customer decisions: a decision recorded at exactly `decision_deadline_at` is accepted. The daily sweep, by contrast, defaults only exceptions whose deadline is strictly behind the clock.

A `CustomerManager` or `CustomerDecisionMaker` decisions an `OPEN` exception by submitting `decision` as `PAY` or `RETURN`. The decision enforces four preconditions, evaluated in order — enrollment state first (a `TERMINATED` enrollment rejects with `ERR_ENROLLMENT_TERMINATED`, any other non-`ACTIVE` status with `ERR_ENROLLMENT_NOT_ACTIVE`), then exception state (not `OPEN` rejects with `ERR_EXCEPTION_NOT_OPEN`), then the deadline (a logical clock later than `decision_deadline_at` rejects with `ERR_DECISION_DEADLINE_PASSED`), and finally the uploader segregation-of-duties check of §2.8 (`ERR_SOD_UPLOAD_DECISION_CONFLICT`, applied only when `issued_check_id` is non-null). On either decision the server records `decided_by_user_id` from the caller and stamps `decided_at`, derives `liability_party`, and subtracts one from the enrollment's `open_exception_count`.

A `PAY` decision moves the exception to `DECISIONED_PAY` and the item from `EXCEPTION_HELD` to `PAID`, with the full pay-side cascade: `paid_at` stamped, the account ledger updated, the review threshold evaluated (which may flip the account to `REVIEW_HOLD`), and the linked check — when there is one — moved from `REGISTERED` to `CONSUMED` with `consumed_by_item_id` set. The customer approved the item, so `liability_party` is set to `CUSTOMER`. A `RETURN` decision moves the exception to `DECISIONED_RETURN` and the item from `EXCEPTION_HELD` to `RETURNED`, accrues a 500-cent return fee linked to the exception (§3.7), and sets `liability_party` to `NONE` — the item was never paid, so there is no loss to allocate. The returned item's check is not consumed and remains matchable by a future presentment.

A `BankOps` operator may extend a deadline exactly once per exception by supplying `new_deadline_at`. The extension requires the exception still be `OPEN` (`ERR_EXCEPTION_NOT_OPEN`), requires `extended_once` still be false (a second extension is rejected with `ERR_EXCEPTION_ALREADY_EXTENDED`), requires the logical clock still be at or before the current `decision_deadline_at` (`ERR_DECISION_DEADLINE_PASSED`), and requires the new deadline to fall strictly after the current clock and no more than 24 hours after it — a target outside that window fails shape validation with `ERR_INVALID_REQUEST`. A successful extension moves `decision_deadline_at` to `new_deadline_at` and sets `extended_once` to true.

Exceptions the customer never touches are resolved by the daily sweep. An exception still `OPEN` whose `decision_deadline_at` is strictly earlier than the logical clock is defaulted according to its `default_decision_snapshot`: a snapshot of `PAY` moves the exception to `DEFAULTED_PAY` and the item to `DEFAULT_PAID` with the same ledger effects as a decided pay (`paid_at`, cumulative paid, threshold evaluation, check consumption), while a snapshot of `RETURN` moves the exception to `DEFAULTED_RETURN` and the item to `DEFAULT_RETURNED` with the 500-cent return-fee accrual. Defaults carry no `decided_by_user_id` or `decided_at`, subtract one from `open_exception_count`, and — because the deadline was missed and the default rule governs — set `liability_party` to `CUSTOMER` on both the pay and the return default. The liability matrix at the exception level is therefore complete: `DECISIONED_RETURN` yields `NONE`, and every pay or default path — `DECISIONED_PAY`, `DEFAULTED_PAY`, `DEFAULTED_RETURN` — yields `CUSTOMER`. Bank liability arises only through the liability-case process of §3.8 on items that were actually paid.

### 3.6. ACH Debit Block and Filter Rules

The same accounts can carry ACH debit authorization rules, maintained jointly by `BankOps`, `CustomerAdmin`, and `CustomerManager`. A rule is created with an `account_id`, a `rule_type`, the `originator_company_id` it scopes to (1 to 10 characters), a `sec_code` of `CCD`, `PPD`, `WEB`, or `TEL`, and an effective window from `effective_start_date` (inclusive) to `effective_end_date` (exclusive, and null for an open-ended rule). A `BLOCK` rule auto-returns all matching debits and must not carry `max_amount_cents`; a `FILTER` rule holds debits above a cap and must carry `max_amount_cents` — either shape violation is an `ERR_INVALID_REQUEST`. New rules start `ACTIVE`.

Window overlap is policed within the triple of `account_id`, `originator_company_id`, and `sec_code`: a create is rejected with `ERR_ACH_RULE_WINDOW_OVERLAP` when another rule with the same triple, in `ACTIVE` or `SUSPENDED` status, has a window intersecting the new one. Windows are half-open — the start date is included and the end date excluded — so two windows that merely touch, one's end date equal to the other's start date, do not overlap and are allowed; a null end date makes the window open-ended. Rules can be listed by `account_id` and `status`.

An existing rule's `max_amount_cents`, `effective_start_date`, or `effective_end_date` may be edited while the rule is `ACTIVE` or `SUSPENDED`; the edit must carry `expected_ach_rule_version` per §2.7, rejects a stale version with `ERR_STALE_VERSION`, re-validates window overlap against the rest of the rule set excluding the rule itself (`ERR_ACH_RULE_WINDOW_OVERLAP`), and increments the rule's `version`. Editing an `EXPIRED` or `RETIRED` rule is rejected with `ERR_ACH_RULE_NOT_ACTIVE`.

Suspension and resumption cycle the rule between `ACTIVE` and `SUSPENDED`. Suspending requires the rule be `ACTIVE` and resuming requires it be `SUSPENDED`; either call against the wrong state is `ERR_ACH_RULE_NOT_ACTIVE`. Both require the enrollment be `ACTIVE` (with the standard `ERR_ENROLLMENT_NOT_ACTIVE` / `ERR_ENROLLMENT_TERMINATED` precedence). Resumption additionally re-validates that the window has not elapsed — the `effective_end_date` must be null or on or after the current logical date, otherwise `ERR_ACH_RULE_NOT_ACTIVE` — and re-runs the overlap check against `ACTIVE` and `SUSPENDED` siblings (`ERR_ACH_RULE_WINDOW_OVERLAP`). Either state may be retired to the terminal `RETIRED` status. Separately, the daily sweep moves any `ACTIVE` or `SUSPENDED` rule whose non-null `effective_end_date` has fallen before the current logical date to `EXPIRED`.

### 3.7. Fee Accrual, Waivers, and Monthly Billing

All service charges live in a per-enrollment fee ledger. Each `FeeLedgerEntry` records its `enrollment_id`, an optional `exception_id` (null for `ADJUSTMENT` and `MINIMUM_TOPUP` entries), the billing `period` (the year-month, formatted `YYYY-MM`, of the entry's `created_at`), a `fee_type` of `EXCEPTION_FEE`, `RETURN_FEE`, `ADJUSTMENT`, or `MINIMUM_TOPUP`, an `amount_cents`, and a `status` of `ACCRUED`, `BILLED`, or `WAIVED`. Two fees accrue from the exception workflow: every exception creation — for any reason, including `REVERSE_REVIEW` — accrues one `EXCEPTION_FEE` entry of 200 cents in `ACCRUED` status, linked back from the exception's `fee_entry_id`; and every item that enters `RETURNED` or `DEFAULT_RETURNED` accrues one `RETURN_FEE` entry of 500 cents, `ACCRUED`, linked to the exception. Entries can be listed by `enrollment_id`, `period`, `exception_id`, `status`, and `fee_type`.

Waiver is a bank action shared by `BankOps` and `BankTreasuryManager`, taking a free-text `reason`. Waivability is checked first: the entry's `fee_type` must be `EXCEPTION_FEE`, `RETURN_FEE`, or `MINIMUM_TOPUP` and its status `ACCRUED` or `BILLED` — waiving an `ADJUSTMENT` entry or an already-`WAIVED` entry is rejected with `ERR_FEE_ENTRY_NOT_WAIVABLE`. Authority is then capped: a `BankOps` operator may waive amounts of at most 1000 cents, while anything larger requires a `BankTreasuryManager`, and an over-authority attempt is rejected with `ERR_WAIVER_EXCEEDS_AUTHORITY` (HTTP 422); the manager's waiver authority is uncapped. A successful waiver moves the entry to `WAIVED` and records `waived_from_status` (the `ACCRUED` or `BILLED` status it came from), `waived_by`, and `waiver_reason` from the submitted reason. Reinstatement is manager-only: a `WAIVED` entry returns to whatever status `waived_from_status` recorded — `ACCRUED` or `BILLED` — and the three waiver fields are cleared to null; reinstating a non-`WAIVED` entry is `ERR_FEE_ENTRY_NOT_WAIVABLE`. `ADJUSTMENT` and `MINIMUM_TOPUP` entries are created directly in `BILLED` status by monthly billing; an adjustment is never waivable, while a top-up is waivable (its size usually forces the manager path).

Monthly billing runs per enrollment and period and performs a pinned sequence. First, the exception fees are re-rated by volume: the period's `EXCEPTION_FEE` entries are ordered by their exception's `created_at` ascending, with ties broken by fractional seconds and then by `check_number` ascending — never by id — and waived rows remain in this ordered set, since a waiver does not change tier positions. The re-rated price is 200 cents each for the first ten exceptions, 150 cents each for the eleventh through fortieth, and 100 cents each from the forty-first onward. The re-rated total is compared against the provisional total — the sum of the same entries' `amount_cents`, each accrued at 200 — and when the difference is non-zero a single `ADJUSTMENT` entry is created in `BILLED` status with `amount_cents` equal to the re-rated total minus the provisional total, which is negative whenever volume discounts apply.

The statement derivation then runs in a fixed order. It sums the period's `EXCEPTION_FEE` entries across all statuses into the provisional exception-fee figure; computes the adjustment as above; sums the period's `RETURN_FEE` entries across all statuses; and sums all `WAIVED` entries of the period, split by fee type. The pre-minimum total is the provisional exception fees plus the adjustment, plus the return fees net of waived return fees, minus the waived exception fees. The net due is the greater of the 5000-cent monthly minimum and that pre-minimum figure; if the minimum exceeds the pre-minimum, a `MINIMUM_TOPUP` entry is created in `BILLED` status for the difference. Applying the minimum before subtracting waivers is a forbidden alternate reading: waivers reduce the pre-minimum figure, and only then is the floor applied. Finally, every `ACCRUED` entry of the period flips to `BILLED`, which is the count reported by the run as `fees_billed`.

A computed statement can be read at any time for a supplied `period` and returns `period`, `exception_fees_cents`, `return_fees_cents`, `adjustment_cents`, `waived_cents`, `minimum_topup_cents`, `net_due_cents`, and `entry_count`. On that read, `net_due_cents` is the sum of the period's entries in `BILLED` status — which includes any `ADJUSTMENT` and `MINIMUM_TOPUP` — while waived amounts are excluded from the net and surfaced separately as `waived_cents`.

### 3.8. Unauthorized-Item Liability Claims

When a customer discovers a paid item it never authorized, a `CustomerAdmin`, `CustomerManager`, or `CustomerDecisionMaker` files a `LiabilityCase` against it, naming the `presented_item_id` and a `claim_reason` of `FORGED_SIGNATURE`, `ALTERED_AMOUNT`, `COUNTERFEIT`, or `UNAUTHORIZED_PAYEE`. Filing requires the item be in `PAID` status (otherwise `ERR_ITEM_NOT_CLAIMABLE`) and within the claim window: the logical clock must be no later than thirty days after the item's `paid_at`, with a filing exactly thirty days after still accepted and anything later rejected with `ERR_CLAIM_WINDOW_CLOSED`. The case opens in `FILED` with `claim_amount_cents` pinned to the item's `amount_cents` at filing, `filed_by_user_id` taken from the caller, `enrollment_id` denormalized from the item's account, and `provisional_credit_cents` at zero. Cases can be listed by `enrollment_id`, `presented_item_id`, `filed_by_user_id`, and `status`.

A `BankOps` operator picks up a `FILED` case by starting review, moving it to `UNDER_REVIEW` — any other starting state fails with `ERR_CASE_NOT_OPEN` — and becoming its `assigned_bank_user_id`. Starting review posts a provisional credit when the claim is small: if `claim_amount_cents` is at most 25000 cents, `provisional_credit_cents` is set to the full claim amount and the same amount is added to the enrollment's `provisional_credit_outstanding_cents`; above 25000 cents no provisional credit posts and `provisional_credit_cents` stays zero.

Resolution is manager-only, taking a `resolution` of `BANK_LIABLE`, `CUSTOMER_LIABLE`, or `SHARED`, and requires the case be `UNDER_REVIEW` (`ERR_CASE_NOT_OPEN`). For claims strictly greater than 25000 cents, the resolver's `X-User-ID` must differ from `assigned_bank_user_id` per §2.8, or the resolution is rejected with `ERR_SOD_CASE_RESOLUTION_CONFLICT`. The resolver is recorded as `resolved_by_bank_user_id`. Every resolution first unwinds the provisional credit, subtracting `provisional_credit_cents` from the enrollment's `provisional_credit_outstanding_cents`; on a bank-liable outcome the credit becomes final, and on a customer-liable outcome it is clawed back. The split itself depends on the resolution: `RESOLVED_BANK_LIABLE` sets `bank_liability_cents` to the full `claim_amount_cents` and `customer_liability_cents` to zero; `RESOLVED_CUSTOMER_LIABLE` sets the customer figure to the full claim and the bank figure to zero; `RESOLVED_SHARED` gives the bank the claim amount divided by two rounded down to a whole cent and the customer the remainder, so an odd cent always lands on the customer — a 10001-cent claim splits 5000 to the bank and 5001 to the customer. Whenever the bank bears any share, that share is added to the enrollment's `ytd_bank_loss_cents`, which accumulates the bank-liability amounts of cases resolved within the calendar year of their resolution.

The year-to-date loss figure arms the enrollment's automatic suspension: after a resolution that adds to it, if `loss_suspension_threshold_cents` is non-null and `ytd_bank_loss_cents` has reached or exceeded it, an `ACTIVE` enrollment transitions to `SUSPENDED` without any operator action. This automatic suspension is one of the version-bumping enrollment writes listed in §2.4, and the suspended enrollment behaves exactly as §3.1 describes — customer writes blocked, matching and sweeps continuing.

A filer-side withdrawal moves a case from `FILED` or `UNDER_REVIEW` to `WITHDRAWN`; a terminal case rejects the attempt with `ERR_CASE_NOT_OPEN`. Withdrawing from `UNDER_REVIEW` reverses any outstanding provisional credit by subtracting `provisional_credit_cents` from the enrollment's `provisional_credit_outstanding_cents`; withdrawing from `FILED` has no ledger effect since no credit has posted yet.

### 3.9. Checkpoint Ops Runs and Adoption Reporting

Batch processing is explicit and receipted: a `BankOps` operator triggers a checkpoint run by naming its `kind` — `DAILY_SWEEP` or `MONTHLY_BILLING` — and receives a completed `OpsRun` receipt, since runs execute synchronously and finish in `COMPLETED` status. A daily sweep optionally scopes to a single `enrollment_id` and otherwise covers all enrollments; a `period` must not be supplied for it. A monthly billing run requires both an `enrollment_id` and a `period` in `YYYY-MM` form — omitting the period fails shape validation with `ERR_INVALID_REQUEST`.

The daily sweep performs four chores, each counted on the receipt. Every `OPEN` exception whose `decision_deadline_at` is strictly earlier than the logical clock is defaulted per its snapshot, counted as `exceptions_defaulted`. Every `REGISTERED` check whose age has reached the enrollment's `stale_days` — the current logical date is on or after `issue_date` plus that many days, with an age of exactly `stale_days` days staling the check — moves to `STALE_DATED`, counted as `checks_staled`. Every `ACTIVE` or `SUSPENDED` ACH rule whose non-null `effective_end_date` is before the current logical date moves to `EXPIRED`, counted as `ach_rules_expired`. And every `SCHEDULED` training session whose `scheduled_end` has passed moves to `NO_SHOW`, counted as `sessions_marked_no_show`. The monthly billing run executes the fee reconciliation of §3.7 and reports the adjustment posted as `adjustment_cents` and the top-up posted as `minimum_topup_cents`. A billing run requires the period to be fully elapsed — its last day must be entirely behind the logical clock, otherwise `ERR_PERIOD_NOT_CLOSED` — and refuses to run twice for the same enrollment and period: if any `BILLED` entries already exist for that pair, the run is rejected with `ERR_PERIOD_ALREADY_BILLED`. Ops-run receipts can be listed by `enrollment_id` and `kind`.

Finally, an adoption report gives relationship managers a quantitative view of how well each customer is using the service. For an enrollment it returns `presented_total` (all presented items across the enrollment's accounts), `clean_paid_total` (items whose `match_result` was `CLEAN`), `exceptions_total`, `decisioned_total` (exceptions in `DECISIONED_PAY` or `DECISIONED_RETURN`), `defaulted_total` (exceptions in `DEFAULTED_PAY` or `DEFAULTED_RETURN`), and `training_completed_count` (sessions in `COMPLETED`). Two ratios are reported in basis points as integers, rounded half-up: `on_time_decision_bp` is the decisioned share of all resolved exceptions — decisioned plus defaulted — and is zero when no exception has resolved yet; `issue_file_compliance_bp` is the clean-paid share of all presented items, and is null for `REVERSE_POSITIVE_PAY` enrollments (which submit no issue files) and null when no items have been presented at all.

## 4. Endpoint Definitions

Operations that create a new resource — enrollments, enrollment users, accounts, issue-file uploads, presented items, ACH rules, liability cases, training sessions, and ops runs — return `201 Created`. Operations that modify an existing resource or return data without creating a resource return `200 OK`. Request bodies, side effects, and preconditions for each operation are specified in §3; the table below is the routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/treasury/enrollments` | Create an enrollment in `PENDING_ACTIVATION` | BankTreasuryManager |
| GET    | `/treasury/enrollments/{id}` | Get an enrollment | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| PATCH  | `/treasury/enrollments/{id}` | Patch mutable enrollment configuration (OCC) | BankTreasuryManager, CustomerAdmin |
| POST   | `/treasury/enrollments/{id}/activate` | Activate from `PENDING_ACTIVATION` (training gate) or `SUSPENDED` | BankTreasuryManager |
| POST   | `/treasury/enrollments/{id}/suspend` | Suspend an `ACTIVE` enrollment | BankTreasuryManager |
| POST   | `/treasury/enrollments/{id}/terminate` | Terminate a settled enrollment | BankTreasuryManager |
| POST   | `/treasury/enrollments/{id}/change-tier` | Migrate service tier (gated, OCC) | BankTreasuryManager |
| GET    | `/treasury/enrollments/{id}/adoption-report` | Computed adoption metrics | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerViewer |
| GET    | `/treasury/enrollments/{id}/fee-statement` | Computed fee statement for a period | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerViewer |
| POST   | `/treasury/enrollment-users` | Create an enrollment user | BankTreasuryManager, CustomerAdmin |
| GET    | `/treasury/enrollment-users/{id}` | Get an enrollment user | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| GET    | `/treasury/enrollment-users` | List enrollment users | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| POST   | `/treasury/accounts` | Create an account under an enrollment | BankTreasuryManager |
| GET    | `/treasury/accounts/{id}` | Get an account | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| GET    | `/treasury/accounts` | List accounts | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| POST   | `/treasury/accounts/{id}/close` | Close an account with no open exceptions | BankTreasuryManager |
| POST   | `/treasury/accounts/{id}/clear-review-hold` | Clear a payment review hold | BankOps |
| POST   | `/treasury/issue-files` | Upload an issued-check file (idempotent, per-row validation) | CustomerAdmin, CustomerManager |
| GET    | `/treasury/issue-files/{id}` | Get an upload | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| GET    | `/treasury/issue-files` | List uploads | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| GET    | `/treasury/issued-checks/{id}` | Get an issued check | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| GET    | `/treasury/issued-checks` | List issued checks | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| POST   | `/treasury/issued-checks/{id}/void` | Void a `REGISTERED` check | CustomerAdmin, CustomerManager |
| POST   | `/treasury/presented-items` | Ingest a presented item; synchronous matching | BankOps |
| GET    | `/treasury/presented-items/{id}` | Get a presented item | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| GET    | `/treasury/presented-items` | List presented items | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| POST   | `/treasury/presented-items/{id}/reverse` | Reverse a `PAID` item | BankTreasuryManager |
| GET    | `/treasury/exceptions/{id}` | Get an exception | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| GET    | `/treasury/exceptions` | List the exception queue | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| POST   | `/treasury/exceptions/{id}/decision` | Customer pay/return decision before deadline | CustomerManager, CustomerDecisionMaker |
| POST   | `/treasury/exceptions/{id}/extend-deadline` | Extend the decision deadline once | BankOps |
| POST   | `/treasury/ach-rules` | Create an ACH debit block/filter rule | BankOps, CustomerAdmin, CustomerManager |
| GET    | `/treasury/ach-rules/{id}` | Get an ACH rule | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| GET    | `/treasury/ach-rules` | List ACH rules | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| PATCH  | `/treasury/ach-rules/{id}` | Edit amount cap or window (OCC, overlap re-validation) | BankOps, CustomerAdmin, CustomerManager |
| POST   | `/treasury/ach-rules/{id}/suspend` | Suspend an `ACTIVE` rule | BankOps, CustomerAdmin, CustomerManager |
| POST   | `/treasury/ach-rules/{id}/resume` | Resume a `SUSPENDED` rule | BankOps, CustomerAdmin, CustomerManager |
| POST   | `/treasury/ach-rules/{id}/retire` | Retire a rule (terminal) | BankOps, CustomerAdmin, CustomerManager |
| POST   | `/treasury/liability-cases` | File an unauthorized-item claim on a `PAID` item | CustomerAdmin, CustomerManager, CustomerDecisionMaker |
| GET    | `/treasury/liability-cases/{id}` | Get a liability case | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| GET    | `/treasury/liability-cases` | List liability cases | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| POST   | `/treasury/liability-cases/{id}/start-review` | Open review; posts provisional credit | BankOps |
| POST   | `/treasury/liability-cases/{id}/resolve` | Resolve with liability split (SoD for large claims) | BankTreasuryManager |
| POST   | `/treasury/liability-cases/{id}/withdraw` | Withdraw a non-terminal case | CustomerAdmin, CustomerManager, CustomerDecisionMaker |
| GET    | `/treasury/fee-entries/{id}` | Get a fee ledger entry | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| GET    | `/treasury/fee-entries` | List fee ledger entries | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| POST   | `/treasury/fee-entries/{id}/waive` | Waive a fee entry (authority-capped) | BankOps, BankTreasuryManager |
| POST   | `/treasury/fee-entries/{id}/reinstate` | Reinstate a waived entry to its prior status | BankTreasuryManager |
| POST   | `/treasury/training-sessions` | Schedule a training session (per-trainer conflict rule) | BankOps |
| GET    | `/treasury/training-sessions/{id}` | Get a training session | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| GET    | `/treasury/training-sessions` | List training sessions | BankTreasuryManager, BankOps, CustomerAdmin, CustomerManager, CustomerDecisionMaker, CustomerViewer |
| POST   | `/treasury/training-sessions/{id}/complete` | Complete a session with attendee list | BankOps |
| POST   | `/treasury/training-sessions/{id}/cancel` | Cancel a scheduled session | BankOps |
| POST   | `/treasury/ops-runs` | Run a `DAILY_SWEEP` or `MONTHLY_BILLING` checkpoint | BankOps |
| GET    | `/treasury/ops-runs/{id}` | Get an ops run receipt | BankTreasuryManager, BankOps |
| GET    | `/treasury/ops-runs` | List ops run receipts | BankTreasuryManager, BankOps |
| POST   | `/_clock/set_current_utc` | Advance the logical clock | BankOps |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3; this table is the identifier and status reference.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_CROSS_ENROLLMENT_ACCESS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ENROLLMENT_TERMINATED` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_ACTIVATABLE` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_SETTLED` | 409 Conflict |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACCOUNT_HAS_OPEN_EXCEPTIONS` | 409 Conflict |
| `ERR_TIER_FORBIDS_ISSUE_FILES` | 409 Conflict |
| `ERR_TIER_CHANGE_NOT_ALLOWED` | 409 Conflict |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 Conflict |
| `ERR_CHECK_NOT_VOIDABLE` | 409 Conflict |
| `ERR_ITEM_NOT_REVERSIBLE` | 409 Conflict |
| `ERR_ITEM_NOT_CLAIMABLE` | 409 Conflict |
| `ERR_EXCEPTION_NOT_OPEN` | 409 Conflict |
| `ERR_DECISION_DEADLINE_PASSED` | 409 Conflict |
| `ERR_EXCEPTION_ALREADY_EXTENDED` | 409 Conflict |
| `ERR_ACH_RULE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_ACH_RULE_NOT_ACTIVE` | 409 Conflict |
| `ERR_TRAINING_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_SESSION_NOT_COMPLETABLE` | 409 Conflict |
| `ERR_CLAIM_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CASE_NOT_OPEN` | 409 Conflict |
| `ERR_SOD_UPLOAD_DECISION_CONFLICT` | 403 Forbidden |
| `ERR_SOD_CASE_RESOLUTION_CONFLICT` | 403 Forbidden |
| `ERR_WAIVER_EXCEEDS_AUTHORITY` | 422 Unprocessable Entity |
| `ERR_FEE_ENTRY_NOT_WAIVABLE` | 409 Conflict |
| `ERR_PERIOD_ALREADY_BILLED` | 409 Conflict |
| `ERR_PERIOD_NOT_CLOSED` | 409 Conflict |
