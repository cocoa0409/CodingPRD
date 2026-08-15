# ACH ODFI Origination API — Product Requirements Document

## 1. Introduction

Every ACH payment that a corporate originator sends passes through an originating depository financial institution, and the bank — not the originator — carries the regulatory and financial exposure for what flows through it. NACHA rules hold the ODFI accountable for underwriting its originators, policing unauthorized-return rates, honoring re-presentment limits, and proving after the fact that every dollar settling through a batch was recorded in the general ledger. This document specifies the API through which the bank runs that entire book of work: onboarding and approving originators under exposure limits, taking in payment files and warehousing them until their effective date, releasing them against same-day or next-day cutoff windows, registering inbound returns and notifications of change, monitoring return-rate thresholds, forcing risk interventions up to suspension and termination, and reconciling each settlement batch to the cent.

The audience is the engineering team building this service. Five operator populations interact with it — originator-side operations staff and four disjoint bank functions (underwriting, ACH operations, risk, and finance) — and the system must keep their duties strictly separated while still letting a return registered by operations propagate, within the same request, into a rate recompute, a risk case, a suspension cascade, and eventually a reconciliation variance. All endpoints are mounted under the `/ach` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes exactly five roles: `OriginatorOps`, `OdfiUnderwriter`, `OdfiOperations`, `OdfiRiskOfficer`, and `OdfiFinance`. A request whose headers are missing or malformed, or whose `X-User-Role` value is not one of these five declared roles, is rejected with `ERR_UNAUTHENTICATED`. Beyond authentication, every endpoint declares the roles permitted to call it; a caller whose role is not in the endpoint's list is rejected with `ERR_FORBIDDEN_ROLE`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `OriginatorOps`, `X-User-ID` is the `id` of the acting Originator; ownership checks on any resource that references an Originator compare the resource's originator linkage — a file's own originator reference, an entry's through its file, a NOC's or reversal's through its entry and that entry's file — to `X-User-ID`, and a mismatch is rejected with `ERR_RESOURCE_OWNERSHIP`. When `X-User-Role` is `OdfiUnderwriter`, `OdfiOperations`, `OdfiRiskOfficer`, or `OdfiFinance`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `dispatched_by_user_id` on a SettlementBatch, as `resolved_by_user_id` on a RiskCase, or as `reconciled_by_user_id` on a reconciled batch) but does not compare it to any entity's `id`. One segregation-of-duties exception exists: finance may not reconcile a batch whose recorded dispatcher is the same operator — that rule is specified in §3.5.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the server's wall clock at response time rather than from the §2.4 logical clock.
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
- Requests that fail before reaching an operation use the same envelope: an unmatched route is rejected with `ERR_NOT_FOUND` (404), an unsupported method on a known route with `ERR_INVALID_REQUEST` (405), and an unexpected server failure with `ERR_INTERNAL` (500).

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 band, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order — that is, by `created_at` ascending, which is insertion order; `id` is never used for ordering.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned in the current page is less than `total_count`.

### 2.4. The Logical Clock and the Banking-Day Calendar

Every temporal rule in the system — cutoff windows, effective-date eligibility, NOC deadlines, reversal windows, settlement dates, rate-computation windows — is evaluated against a server-side **logical clock**, never against wall-clock time. Before any client call, the clock starts at exactly 2026-08-01T00:00:00Z; there is no wall-clock fallback. All five roles share a test-driving capability, `POST /ach/_clock/set_current_utc`, which accepts a `to_iso8601` instant, sets the server's current UTC time to it, and returns the resulting `current_utc`; a missing or unparsable `to_iso8601` is rejected with `ERR_INVALID_REQUEST`.

Advancing the clock has a system-wide side effect: the NOC overdue sweep. When the clock is set, the server determines the current banking day under the new time, and every notification-of-change record still in `RECEIVED` status whose `due_date` falls strictly before that banking day transitions to `OVERDUE`.

The calendar itself is deliberately simple. A **banking day** is any Monday through Friday; there is no holiday table. Wherever a rule references "today" or the current day under the logical clock — the effective-date window, the release-date equality, the reversal window, the NOC overdue sweep — it means the calendar date of the current clock instant, whether or not that date is itself a banking day. Adding banking days to a date means advancing one calendar day at a time and counting only days that fall Monday through Friday, stopping when the requested number of banking days has been counted. The "next banking day" after a date is the result of adding one banking day. This single calendar function backs four distinct rules described later: the effective-date window at file intake, the six-banking-day NOC application deadline, the five-banking-day reversal eligibility window, and the settlement date of files that roll to the next-day window.

### 2.5. Common Resource Properties

All primary resources — Originator, CutoffWindow, AchFile, AchEntry, ReturnCase, NocRecord, ReversalRequest, RiskCase, and SettlementBatch — include a standard set of system-managed fields:

- **`id` (string):** A unique, system-generated identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`) indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp, likewise with three fractional digits, indicating when the resource was last modified. It refreshes upon any change to the resource.
- **`version` (integer):** A system-managed integer that starts at 1 when the resource is created and increments by one with every modification to the resource, and that anchors the optimistic-concurrency rules of §2.7.

Any mutation of a resource — including mutations driven by cascades or by recomputation of derived fields such as an originator's exposure totals — refreshes that resource's `updated_at` and increments its `version`. A recomputation that leaves a derived field at its existing value is not a mutation and by itself refreshes neither `updated_at` nor `version`.

Two resources are exceptions by design. A ReturnRateSnapshot is an immutable audit record, and a GlPosting is an append-only ledger event; each carries only `id` and `created_at`, and both `updated_at` and `version` are absent from them.

### 2.6. Request Validation Pipeline

Requests are validated in a fixed, ordered pipeline, and the order is observable: when several checks would fail, the earliest category's error is the one returned. The pipeline runs as follows.

1. **Authentication.** Both headers must be present and well-formed, and the role must be declared; failures yield `ERR_UNAUTHENTICATED`.
2. **Role authorization.** The caller's role must appear in the endpoint's authorized list; otherwise `ERR_FORBIDDEN_ROLE`.
3. **Originator ownership.** For the operations an `OriginatorOps` caller may perform — file creation, appending entries to a file, cancelling a file, requesting a reversal, closing an entry, applying a NOC, and cancelling a requested reversal — the caller's `X-User-ID` must equal the originator identity at the root of the target resource's chain, otherwise `ERR_RESOURCE_OWNERSHIP`.
4. **Path existence.** Path identifiers are resolved left to right. Every resource is addressed by an `id` path segment, and where a path nests one resource beneath another (an entry beneath its file, a NOC beneath its entry), each identifier is validated in turn against its parent chain. The request is rejected with `ERR_NOT_FOUND` at the first identifier that does not resolve.
5. **Request-body schema.** The body must be a JSON object, required fields must be present, enum values must be in range (an unknown return code or NOC code fails here), `amount_cents` must be greater than zero, and date and time fields must be well-formed `YYYY-MM-DD` or `HH:MM` values; violations yield `ERR_INVALID_REQUEST`.
6. **State preconditions.** The target resource must be in the state the operation requires. Each operation maps to its own conflict error — `ERR_ORIGINATOR_NOT_ACTIVE`, `ERR_FILE_NOT_WAREHOUSED`, `ERR_ENTRY_NOT_SETTLED`, `ERR_ENTRY_NOT_RETURNED`, `ERR_REVERSAL_NOT_ACTIONABLE`, `ERR_BATCH_NOT_OPEN`, `ERR_RISK_CASE_ALREADY_RESOLVED`, `ERR_NOC_NOT_ACTIONABLE`, or `ERR_RESOLUTION_NOT_APPLICABLE` — all HTTP 409.
7. **Optimistic concurrency.** For the two endpoints that carry a version field, a stale version is rejected only after ownership, existence, schema, and state checks have passed — see §2.7.
8. **NACHA compliance.** Same-day eligibility, reversal-reason admissibility, the segregation-of-duties rule at reconcile, and the R01-only re-presentment rule are evaluated next.
9. **Temporal windows.** Effective-date, release-date, and reversal-window rules follow.
10. **Structural constraints.** Duplicate active reversals, cutoff-window overlap, empty-file release, missing window definitions, and re-presentment exhaustion.
11. **Fiscal limits.** Last, the debit-exposure admission check and the zero-variance reconciliation requirement.

### 2.7. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control, and each names its guard field explicitly.

A `PATCH /ach/originators/{id}` request must carry `expected_originator_version` holding the value of the originator's `version` the client last observed. If the originator's current `version` has advanced since then — because another underwriting update or a risk-case resolution mutated the originator in between — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting an originator record it has not observed.

A `POST /ach/ach-files/{id}/entries` request must likewise carry `expected_file_version` holding the file's last observed `version`. Because every successful entries-append legitimately mutates the file (totals and the quoted fee are recomputed, and `version` increments), a client appending against a version it has not observed is stale and is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field.

### 2.8. Integer-Cents Money Discipline and Rounding

All monetary values are represented as integer cents — entry amounts, fees, exposure totals, batch nets, and ledger legs alike — and integer arithmetic applies throughout; exposure and batch-net figures are never rounded. Two computations do round, and both use the round-half-up method:

- **Per-entry fee discounts** are rounded half-up to a whole cent per entry before summing (§3.2). The rounding order is pinned: discount each entry first, then sum. Summing the raw discounted values and rounding once at the end is a plausible alternative reading, and it is not the rule.
- **Unauthorized return rates** are rounded half-up to integer basis points, with the rounding applied once to the final ratio (§3.8).

### 2.9. State Cascades and Aggregate Consistency

Several single operations mutate more than one entity, and every cascade is atomic within the request. Suspending or terminating an originator rejects its warehoused files and cancels the warehoused entries inside them, then recomputes the originator's exposure. Cancelling a warehoused file cancels its warehoused entries. Dispatching a batch advances its released files and transmits their entries; settling a batch settles its entries, posts ledger rows, sweeps pending returns and reversals, and recomputes exposure for every affected originator. Closing an entry finalizes its open return case; re-presenting an entry marks that case represented. Parent and child states must therefore never drift apart: the rule that a file in `REJECTED` or `CANCELLED` has no `WAREHOUSED` entries left behind is maintained by the cascades themselves, not by later repair jobs. Each entity mutated along the way observes the `updated_at` and `version` semantics of §2.5.

## 3. Business Logic & Workflows

### 3.1. Originator Onboarding and Underwriting Decisions

An `OdfiUnderwriter` registers a new originator by supplying its `legal_name` and the `sec_codes_allowed` list — a subset of the four supported SEC codes `PPD`, `CCD`, `WEB`, and `TEL` that the originator will be permitted to originate. The record is born in `PENDING_UNDERWRITING` status with `exposure_limit_cents` at its default of 0 and `fee_discount_bps` at its default of 0. Its computed fields also start at zero: `unauth_rate_bps_trailing`, `unauth_rate_bps_mtd`, `outstanding_exposure_gross_cents`, and `outstanding_exposure_debit_cents` all begin at 0 until business activity refreshes them.

Underwriting decisions arrive through the originator update operation, which always requires `expected_originator_version` per §2.7 and increments the originator's `version` by one on success. A `decision` of `APPROVE` is valid only from `PENDING_UNDERWRITING` and moves the originator to `ACTIVE`; approval additionally requires `exposure_limit_cents` to be provided and greater than zero — the approved maximum outstanding debit exposure — and the decision persists the supplied `exposure_limit_cents` plus a `fee_discount_bps` only when one is supplied, an omitted discount leaving the current value in place. A `decision` of `DECLINE`, likewise only from `PENDING_UNDERWRITING`, moves the originator straight to `TERMINATED`, which is terminal; any `exposure_limit_cents` or `fee_discount_bps` accompanying a `DECLINE` is ignored. Presenting a `decision` for an originator no longer in `PENDING_UNDERWRITING`, or submitting any update of any kind for a `TERMINATED` originator, is rejected with `ERR_ORIGINATOR_STATUS_TERMINAL`.

The same update operation doubles as limit maintenance: a request carrying no `decision` persists whichever of `exposure_limit_cents` and `fee_discount_bps` is provided and changes no status, and it is accepted from any status other than `TERMINATED` — `PENDING_UNDERWRITING`, `ACTIVE`, `WATCH`, and `SUSPENDED` alike. On maintenance, `exposure_limit_cents` may be any value of zero or greater; the greater-than-zero requirement binds only `APPROVE`. The `fee_discount_bps` value is a per-entry fee discount in basis points between 0 and 10000 inclusive, applied per entry and then summed as §3.2 describes. Requests failing schema rules — a missing required field, an enum outside its range, a discount outside its band — are rejected with `ERR_INVALID_REQUEST`.

### 3.2. Cutoff Windows and the Fee Rate Card

The bank's processing day is defined by **CutoffWindow** records, which an `OdfiOperations` operator creates. Each window carries a `window_kind` of `SAME_DAY_1`, `SAME_DAY_2`, `SAME_DAY_3`, or `NEXT_DAY` — unique across all window rows — plus `opens_at_utc` and `closes_at_utc` as `HH:MM` UTC times of day, and its rate card: `per_entry_fee_cents`, `file_fee_cents`, and `large_entry_surcharge_cents`, each of which must be zero or greater. The close must be strictly later than the open. Among the three same-day kinds, the half-open time intervals — open inclusive, close exclusive — must not overlap, though adjacency is allowed: one window closing at exactly the instant another opens is legal. The `NEXT_DAY` window is not part of the overlap rule. A duplicate kind, a close not strictly later than its open, or an overlapping same-day interval is rejected with `ERR_WINDOW_OVERLAP`.

The rate card drives the file fee. Each entry's base per-entry fee is the window's `per_entry_fee_cents`, plus the window's `large_entry_surcharge_cents` when the entry's `amount_cents` is strictly greater than $100,000.00 — an entry of exactly $100,000.00 carries no surcharge. The originator's discount then applies per entry: the discounted per-entry fee is the per-entry fee multiplied by the difference between ten thousand and the originator's `fee_discount_bps`, divided by ten thousand, and rounded half-up to a whole cent. The total file fee is the window's `file_fee_cents` — which is never discounted — plus the sum of the discounted per-entry fees over the file's entries. Because the discount is rounded per entry before summing, the fee total is sensitive to the window kind, the entry count, each entry's amount tier, and the originator's discount, and the same entries can price differently under two windows.

### 3.3. File Intake, Warehousing, and Entry Assembly

An originator begins a payment run by creating an **AchFile**. Only `OriginatorOps` may do this, and the caller identity binds the file: `X-User-ID` must be the `id` of an originator in `ACTIVE` status, and the new file's `originator_id` is set from that identity rather than supplied in the payload. An intake attempt whose originator is not `ACTIVE` — still pending, on watch, suspended, terminated, or an `X-User-ID` matching no originator record at all — is rejected with `ERR_ORIGINATOR_NOT_ACTIVE`. The caller supplies the `sec_code` (one of `PPD`, `CCD`, `WEB`, `TEL`), the `requested_window_kind` (`SAME_DAY_1`, `SAME_DAY_2`, `SAME_DAY_3`, or `NEXT_DAY`), and the `effective_date` in `YYYY-MM-DD` form. The SEC code must be among the originator's `sec_codes_allowed`; a code outside the permitted subset is rejected with `ERR_INVALID_REQUEST`. The effective date must be a banking day no earlier than today and no later than the date two banking days ahead — otherwise `ERR_EFFECTIVE_DATE_WINDOW`. A CutoffWindow row must exist for the requested kind; if none does, intake fails with `ERR_NO_ELIGIBLE_WINDOW`.

A new file is an empty shell in `WAREHOUSED` status: `entry_count` and `total_amount_cents` are 0, and `assigned_window_kind`, `settlement_date`, `settlement_batch_id`, and `assessed_fee_cents` remain unset until release. `quoted_fee_cents` is set at intake to the §3.2 fee over the empty file — the requested window's `file_fee_cents` with no per-entry fees — and recomputed on every entries append.

Entries are then appended in bulk. The append payload carries `expected_file_version` (§2.7) alongside the `entries` list, where each entry supplies a `direction` of `DEBIT` or `CREDIT`, an `amount_cents` greater than zero, a `receiver_account` accepted as any non-empty string, and a nine-digit `receiver_routing` number. The append is atomic: if any entry is rejected, no entry from the batch is persisted. An `entries` list may be empty: no entries are persisted, but the file's totals and quoted fee are still recomputed and its `version` still increments. Three gates stand in front of it. The file must still be `WAREHOUSED`, otherwise `ERR_FILE_NOT_WAREHOUSED`; the originator must still be `ACTIVE`, otherwise `ERR_ORIGINATOR_NOT_ACTIVE`; and the caller must own the file, otherwise `ERR_RESOURCE_OWNERSHIP`. Two business limits then apply. If the file's `requested_window_kind` is one of the same-day kinds and any incoming entry's `amount_cents` exceeds $1,000,000.00, the append is rejected with `ERR_SAME_DAY_INELIGIBLE` — an entry of exactly $1,000,000.00 is eligible. And the exposure admission check rejects the append with `ERR_EXPOSURE_LIMIT_EXCEEDED` whenever the originator's `outstanding_exposure_debit_cents` plus the incoming entries' debit total would come out strictly greater than `exposure_limit_cents`; landing exactly on the limit is admitted, and a batch of pure `CREDIT` entries never trips the check.

Outstanding exposure itself is defined over the originator's entries in `WAREHOUSED` or `TRANSMITTED` status only — entries that have settled, returned, closed, or cancelled are excluded. The gross figure, `outstanding_exposure_gross_cents`, sums `amount_cents` across both directions and serves the reporting view on originator reads; the debit figure, `outstanding_exposure_debit_cents`, sums `DEBIT` entries only and is the figure the admission check enforces. Exposure is recomputed whenever entries are created, whenever an entry changes status, and whenever a cancel or suspension cascade removes entries from the outstanding set.

On a successful append, each new **AchEntry** is persisted in `WAREHOUSED` status with its `file_id` recording the owning file and its `representment_count` starting at 0, while `last_return_code`, `first_transmitted_at`, and `settled_at` stay unset. The file's `version` increments by one; `entry_count` and `total_amount_cents` are recomputed as the count and the `amount_cents` sum over all of the file's entries in every status — figures that only ever grow, since cancelled or returned entries still count; and `quoted_fee_cents` is recomputed under the `requested_window_kind` rate card, failing with `ERR_NO_ELIGIBLE_WINDOW` if that window row is missing.

An originator that changes its mind before release can cancel its own file. Cancellation by the owning `OriginatorOps` caller moves the file from `WAREHOUSED` to the terminal `CANCELLED` status, moves every entry of the file still in `WAREHOUSED` to `CANCELLED`, and recomputes the originator's exposure. A file no longer `WAREHOUSED` rejects cancellation with `ERR_FILE_NOT_WAREHOUSED`, and a caller that does not own it is rejected with `ERR_RESOURCE_OWNERSHIP`.

Files may be listed with optional `originator_id`, `status`, and `settlement_batch_id` filters plus the standard `limit` and `offset` pagination parameters.

### 3.4. Release and Cutoff Window Assignment

Release is the bank's act: an `OdfiOperations` operator releases a file, moving it from `WAREHOUSED` to `RELEASED`. Five preconditions guard it. The file must be `WAREHOUSED` (`ERR_FILE_NOT_WAREHOUSED`), its originator must be `ACTIVE` (`ERR_ORIGINATOR_NOT_ACTIVE`), the file must contain at least one entry (`ERR_FILE_EMPTY`), the current banking day under the logical clock must equal the file's `effective_date` (`ERR_RELEASE_DATE_MISMATCH`), and window rows must exist to support the assignment rule (`ERR_NO_ELIGIBLE_WINDOW`).

Window assignment follows a fixed fallback. If the requested window's `closes_at_utc` is still later than the current time, the file gets its requested window. Otherwise, if any same-day window is still open, the file is assigned the open same-day window with the earliest `closes_at_utc`. Otherwise the file falls to `NEXT_DAY`. The assigned kind is recorded in `assigned_window_kind`, and the `settlement_date` follows from it: today when a same-day window was assigned, or the next banking day when the file rolled to `NEXT_DAY`. Release then locates or creates the `OPEN` SettlementBatch keyed on the pair of `assigned_window_kind` and `settlement_date`, records it on the file's `settlement_batch_id`, and computes `assessed_fee_cents` under the assigned window's rate card using the §3.2 fee rule. The assessed fee diverges from the quoted fee exactly when the requested window's cutoff was missed and the file rolled to another window.

### 3.5. Batch Dispatch, Settlement, and Ledger Reconciliation

A **SettlementBatch** aggregates the files assigned to one window-and-date pair and walks a four-state lifecycle: `OPEN`, then `DISPATCHED`, then `SETTLED`, and finally the terminal `RECONCILED`. Batch advancement is an `OdfiOperations` capability driven by an `action` input, and reconciliation belongs to `OdfiFinance`.

Dispatching a batch (`action` of `DISPATCH`) requires the batch to be `OPEN`, otherwise `ERR_BATCH_NOT_OPEN`. Dispatching an empty batch is permitted and simply computes an expected net of zero. At dispatch, every `RELEASED` file assigned to the batch advances to `DISPATCHED`, and every entry of those files — all of which are still `WAREHOUSED` at this point — advances to `TRANSMITTED` with its `first_transmitted_at` stamped to now; that timestamp is the denominator anchor for the rate computations of §3.8 and is written only on an entry's first transmission. The operator's `X-User-ID` is recorded as `dispatched_by_user_id`, and `expected_net_cents` is computed in a pinned evaluation order. First, the principal net is the sum over the batch's dispatched entries where each `DEBIT` entry contributes its `amount_cents` positively and each `CREDIT` entry contributes it negatively. Second, the fee total is the sum of `assessed_fee_cents` over the batch's dispatched files — each file's fee having been computed at release from that file's own entries, never from batch membership. Third, the re-flow adjustment is evaluated over the sweep set as it exists at dispatch: for every originator with at least one entry in this dispatch set, take its unposted return cases (`gl_posted` still false), its re-presented entries (in `TRANSMITTED` with `representment_count` of at least 1 and not part of this dispatch set), and its `TRANSMITTED` reversal requests. An unposted return on a `DEBIT` entry contributes the amount negatively, and on a `CREDIT` entry positively; a re-presented `DEBIT` entry contributes positively and a re-presented `CREDIT` entry negatively; a reversal of a `DEBIT` entry contributes negatively and of a `CREDIT` entry positively. The expected net is the principal net minus the fee total plus this re-flow adjustment.

Settling a batch (`action` of `SETTLE`) requires the batch to be `DISPATCHED`, otherwise `ERR_BATCH_NOT_OPEN`. The batch's `TRANSMITTED` entries advance to `SETTLED` with `settled_at` stamped to now — the anchor for the reversal window of §3.7 — and each settling entry posts a balanced settlement pair of **GlPosting** rows into the batch across the `SETTLEMENT_CLEARING` and `ORIGINATOR_RECEIVABLE` accounts: a `DEBIT` entry credits `ORIGINATOR_RECEIVABLE` for its `amount_cents`, while a `CREDIT` entry debits it, the clearing account taking the opposite leg. Each settled file then posts its fee pair: a debit to `ORIGINATOR_RECEIVABLE` and a credit to `FEE_INCOME` for the file's `assessed_fee_cents` — a file whose assessed fee is zero posts no fee pair, since every ledger row must carry one nonzero leg. Finally, the originator-scoped re-flow sweep runs as it exists at settle time: for every originator with at least one entry settling in this batch, its re-presented entries (in `TRANSMITTED` with `representment_count` of at least 1, outside this batch's dispatch set) advance to `SETTLED` with settlement pairs posted here; its unposted return cases receive reversing ledger pairs here — debiting `ORIGINATOR_RECEIVABLE` when the returned entry was a `DEBIT`, crediting it when the entry was a `CREDIT` — and are marked `gl_posted` true; and its `TRANSMITTED` reversal requests advance to `SETTLED` with ledger pairs that are the exact inverse of the original entry's settlement pair. The batch's `posted_net_cents` is then computed as the signed sum of its own GlPosting rows — credits minus debits — on the `ORIGINATOR_RECEIVABLE` account code, and exposure is recomputed for every affected originator as settled entries leave the outstanding set.

Ledger rows obey three rules everywhere. Every GlPosting row carries an `account_code` of `SETTLEMENT_CLEARING`, `ORIGINATOR_RECEIVABLE`, or `FEE_INCOME`; exactly one of `debit_cents` or `credit_cents` is greater than zero on any row; and `memo` is free text — it may reference an entry, a return case, a reversal, or a fee note, but it is never an input to any decision. Each row's `posted_at` is the logical-clock timestamp of posting.

Because the expected net snapshots the sweep set at dispatch while settlement posts the set as it exists at settle, drift is possible by design: a return, re-presentment, or reversal that enters an affected originator's sweep set between dispatch and settle posts into the batch without ever having been in `expected_net_cents`, and the resulting variance will block reconciliation.

Reconciliation closes the loop. An `OdfiFinance` operator reconciles a batch that must be in `SETTLED`, otherwise `ERR_BATCH_NOT_OPEN`. Segregation of duties is enforced: the reconciler's `X-User-ID` must differ from the recorded `dispatched_by_user_id`, otherwise `ERR_SOD_VIOLATION`. The attempt computes `recon_variance_cents` as `posted_net_cents` minus `expected_net_cents` and persists it on the batch, requiring the variance to be exactly zero; any nonzero variance is rejected with `ERR_RECONCILIATION_MISMATCH`, and because the variance is persisted even on a rejected attempt, a failed reconcile still refreshes the batch's `updated_at` and increments its `version`. A successful reconcile moves the batch to `RECONCILED` and records the caller as `reconciled_by_user_id`, which stays unset until that moment.

### 3.6. Returns, Re-presentment, and Notifications of Change

When the RDFI sends a payment back, an `OdfiOperations` operator registers the return against the entry by supplying a `return_code`. Only entries in `SETTLED` accept a return registration — from `WAREHOUSED`, `TRANSMITTED`, `CLOSED`, or `CANCELLED` the attempt is rejected with `ERR_ENTRY_NOT_SETTLED` — and the code must be one of `R01`, `R02`, `R05`, `R07`, or `R10`, with anything else rejected as `ERR_INVALID_REQUEST`. Registration creates a **ReturnCase** whose `entry_id` records the returned entry, whose `return_code` records the supplied code, and whose `disposition` opens at `OPEN`: `received_at` is the logical-clock timestamp, `is_unauthorized` is true exactly when the code is `R05`, `R07`, or `R10`, `representment_number` copies the entry's current `representment_count` (0 for the entry's first return, 1 after one re-presentment, 2 after two), and `gl_posted` starts false. The entry itself moves to `RETURNED` for every return code — there is no code-specific bypass — its `last_return_code` records the code, and the only exits from `RETURNED` are re-presentment and closure. When the return is unauthorized, registration additionally recomputes both unauthorized return rates at the current clock and writes them to the originator's `unauth_rate_bps_trailing` and `unauth_rate_bps_mtd`; if the recomputed figures breach the §3.8 threshold and no open rate-breach risk case exists for the originator, one is auto-opened on the spot.

Re-presentment sends a returned entry back into the network. An `OdfiOperations` operator may re-present only an entry in `RETURNED` status (otherwise `ERR_ENTRY_NOT_RETURNED`), only when the entry's `last_return_code` is `R01` — insufficient-funds returns are the sole re-presentable kind, and any other code is rejected with `ERR_REPRESENTMENT_CODE_PROHIBITED` — and only while the entry's `representment_count` is still below the hard cap of two, with the attempt at a count of exactly two rejected as `ERR_REPRESENTMENT_EXHAUSTED`. A successful re-presentment increments `representment_count` by one, marks the entry's `OPEN` ReturnCase as `REPRESENTED` (a terminal disposition), and moves the entry itself back to `TRANSMITTED`, where it joins the re-flow sweep: the next batch settle that touches the entry's originator settles it, stamps `settled_at`, posts its settlement pair, and leaves `first_transmitted_at` untouched.

Closure is the write-off path. The owning `OriginatorOps` caller — or an `OdfiOperations` operator — may close an entry in `SETTLED` or `RETURNED`; from any other status the close is rejected with `ERR_ENTRY_NOT_RETURNED`, and an `OriginatorOps` caller that does not own the entry's file is rejected with `ERR_RESOURCE_OWNERSHIP`. Closing moves the entry to the terminal `CLOSED` status and moves any `OPEN` ReturnCase on the entry to its terminal `FINAL` disposition.

Notifications of change arrive through a sibling channel. An `OdfiOperations` operator registers a NOC against an entry — accepted only while the entry is `SETTLED` or `RETURNED`, with any other entry status rejected as `ERR_ENTRY_NOT_SETTLED` — by supplying a `noc_code` of `C01`, `C02`, or `C03` and the `corrected_data` string supplied by the RDFI. The resulting **NocRecord** is born in `RECEIVED` status with `received_at` stamped, `late_applied` false, and `due_date` computed as six banking days after the received date; the originator must apply the correction by the end of that banking day. Should the logical clock advance past the deadline, the sweep of §2.4 flips the record from `RECEIVED` to `OVERDUE`. The owning `OriginatorOps` caller applies the correction through the apply capability: from `RECEIVED` the record becomes `APPLIED` outright, while from `OVERDUE` it likewise becomes `APPLIED` but with `late_applied` set true to record the tardy application; applying an already-`APPLIED` record is rejected with `ERR_NOC_NOT_ACTIONABLE`, and a non-owner with `ERR_RESOURCE_OWNERSHIP`.

### 3.7. Reversal Requests

An originator that discovers a bad entry after settlement may ask the bank to reverse it. The owning `OriginatorOps` caller requests a reversal of its own entry by supplying a `reason` of `DUPLICATE_ENTRY`, `WRONG_AMOUNT`, or `WRONG_ACCOUNT`; any other reason is rejected with `ERR_INVALID_REVERSAL_REASON`. The entry must be in `SETTLED`, otherwise `ERR_ENTRY_NOT_SETTLED`, and the ownership chain is enforced as `ERR_RESOURCE_OWNERSHIP`. Timing is strict: the request's `window_expires_at` is computed as five banking days after the date of the entry's `settled_at`, and the request must be created on or before that date — a later attempt is rejected with `ERR_REVERSAL_WINDOW_EXPIRED`. One active reversal per entry is the structural ceiling: if the entry already has a reversal request in `REQUESTED` or `TRANSMITTED`, the new request is rejected with `ERR_DUPLICATE_ACTIVE_REVERSAL`. A compliant request is created in `REQUESTED` status with `requested_at` stamped at the logical clock.

A requested reversal then advances along one of two branches, selected by the `action` input to the advance capability. Under `TRANSMIT`, performed by an `OdfiOperations` operator, the reversal moves from `REQUESTED` to `TRANSMITTED` and joins the re-flow sweep: the next batch settle touching the entry's originator settles it to `SETTLED` and posts the ledger pair that is the exact inverse of the original entry's settlement pair. Under `CANCEL`, performed by the owning `OriginatorOps` caller, the reversal moves from `REQUESTED` to `CANCELLED`. An action attempted by the wrong side — an `OriginatorOps` `TRANSMIT` or an `OdfiOperations` `CANCEL` — is rejected with `ERR_FORBIDDEN_ROLE`. Either action against a reversal no longer in `REQUESTED` — already transmitted, settled, or cancelled — is rejected with `ERR_REVERSAL_NOT_ACTIONABLE`.

### 3.8. Return-Rate Surveillance and Risk Enforcement

NACHA holds the ODFI responsible for keeping each originator's unauthorized return rate under control, and the system tracks that rate in two variants. An `OdfiRiskOfficer` computes a fresh **ReturnRateSnapshot** for an originator at the current logical clock. The trailing variant counts, over the originator's `DEBIT` entries, the unauthorized return cases — those whose `is_unauthorized` holds, meaning codes `R05`, `R07`, and `R10` — whose `received_at` falls in the half-open window from sixty days before the computation instant up through that instant; an item exactly sixty days old is excluded. The denominator counts the originator's `DEBIT` entries whose `first_transmitted_at` falls in that same half-open window. The trailing rate, `rate_bps_trailing_60d`, is zero when the denominator is zero and is otherwise ten thousand times the numerator divided by the denominator, rounded half-up to an integer basis-point value; the underlying counts are persisted as `unauth_returns_60d` and `debits_60d`. The month-to-date variant repeats the same measurement over the closed window from the first day of the computation instant's UTC calendar month at 00:00:00.000Z through the computation instant — both ends inclusive — persisting `unauth_returns_mtd`, `debits_mtd`, and `rate_bps_mtd`. The snapshot records `originator_id` and the `computed_at` instant, and its `breach` flag is true when either rate is strictly greater than fifty basis points — half a percent; a rate of exactly fifty basis points does not breach. Because one window is half-open and the other closed, the same population of returns and debits can legitimately produce two different rates and even two different breach outcomes.

Computing a snapshot also refreshes the originator's own `unauth_rate_bps_trailing` and `unauth_rate_bps_mtd` fields — the same two fields that unauthorized return registration refreshes per §3.6. Whenever a snapshot's `breach` is true and no `OPEN` RiskCase with `source` of `RATE_BREACH` exists for the originator, the system auto-opens one; the originator rate-field mutation at return-registration time triggers the same conditional creation, so surveillance fires from both the officer's explicit measurement and the inbound return stream.

Risk cases may also be opened manually: an `OdfiRiskOfficer` creates one with `source` of `MANUAL`. Either way, a **RiskCase** is born `OPEN` with `resolution_action` and `resolved_by_user_id` unset, and resolution is the risk officer's call via an `action` input. The case must still be `OPEN` — resolving an already-resolved case is rejected with `ERR_RISK_CASE_ALREADY_RESOLVED` — and the action must be applicable to the originator's current status, otherwise `ERR_RESOLUTION_NOT_APPLICABLE`. The five branches behave as follows. `SUSPEND` applies to an originator in `ACTIVE` or `WATCH` and moves it to `SUSPENDED`. `WATCH` applies only to an `ACTIVE` originator and moves it to `WATCH`. `REINSTATE` applies to an originator in `SUSPENDED` or `WATCH` and moves it one step back toward good standing — `SUSPENDED` to `WATCH`, `WATCH` to `ACTIVE`. `TERMINATE` applies from `ACTIVE`, `WATCH`, or `SUSPENDED` and moves the originator to the terminal `TERMINATED` status. `DISMISS` is always allowed and leaves the originator's status untouched. Resolution moves the case to the terminal `RESOLVED` status and persists the `resolution_action` and the resolving officer's `X-User-ID` as `resolved_by_user_id`.

Suspension and termination carry the §2.9 cascade: every file of the originator still in `WAREHOUSED` moves to the terminal `REJECTED` status, every entry of those files still in `WAREHOUSED` moves to `CANCELLED`, and the originator's exposure figures are recomputed as the cancelled entries drop out of the outstanding set.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code — originator registration, rate snapshots, risk-case creation, file intake, return registration, NOC registration, reversal requests, and cutoff-window creation. Operations that modify an existing resource return `200 OK` — the clock set, underwriting updates, entries-append, release, cancel, re-presentment, NOC apply, entry close, reversal advance, batch advance, and reconcile. Reads likewise return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ach/_clock/set_current_utc` | Advance the logical clock; triggers the NOC overdue sweep | All roles |
| POST | `/ach/originators` | Register an originator pending underwriting | OdfiUnderwriter |
| GET | `/ach/originators/{id}` | Read an originator including computed exposure and rate fields | All roles |
| PATCH | `/ach/originators/{id}` | Underwriting decision or limit/discount maintenance (OCC-guarded) | OdfiUnderwriter |
| POST | `/ach/originators/{id}/return-rate-snapshots` | Compute a return-rate snapshot; auto-opens a risk case on breach | OdfiRiskOfficer |
| GET | `/ach/originators/{id}/return-rate-snapshots` | List an originator's rate snapshots | All roles |
| POST | `/ach/originators/{id}/risk-cases` | Manually open a risk case for an originator | OdfiRiskOfficer |
| GET | `/ach/originators/{id}/risk-cases` | List an originator's risk cases | All roles |
| POST | `/ach/risk-cases/{id}/resolve` | Resolve an open risk case; drives the originator transition | OdfiRiskOfficer |
| POST | `/ach/ach-files` | File intake; creates the empty warehoused file shell | OriginatorOps |
| GET | `/ach/ach-files` | List files; filterable by originator, status, and settlement batch | All roles |
| GET | `/ach/ach-files/{id}` | Read a file | All roles |
| POST | `/ach/ach-files/{id}/entries` | Append entries to a warehoused file (bulk, atomic; OCC-guarded) | OriginatorOps |
| GET | `/ach/ach-files/{id}/entries` | List a file's entries | All roles |
| POST | `/ach/ach-files/{id}/release` | Release a warehoused file on its effective date; assigns window, assessed fee, and batch | OdfiOperations |
| POST | `/ach/ach-files/{id}/cancel` | Originator cancels its own warehoused file | OriginatorOps |
| GET | `/ach/ach-entries/{id}` | Read an entry | All roles |
| POST | `/ach/ach-entries/{id}/returns` | Register an inbound RDFI return against a settled entry | OdfiOperations |
| POST | `/ach/ach-entries/{id}/representments` | Re-present a returned entry (R01 only, under the count cap) | OdfiOperations |
| POST | `/ach/ach-entries/{id}/nocs` | Register an inbound notification of change against an entry | OdfiOperations |
| GET | `/ach/ach-entries/{id}/noc-records` | List an entry's NOC records | All roles |
| POST | `/ach/noc-records/{id}/apply` | Originator marks a NOC as applied to its customer records | OriginatorOps |
| POST | `/ach/ach-entries/{id}/reversals` | Originator requests reversal of its own settled entry | OriginatorOps |
| GET | `/ach/ach-entries/{id}/reversal-requests` | List an entry's reversal requests | All roles |
| GET | `/ach/ach-entries/{id}/return-cases` | List an entry's return cases | All roles |
| POST | `/ach/ach-entries/{id}/close` | Close a settled or returned entry; finalizes any open return case | OriginatorOps, OdfiOperations |
| POST | `/ach/reversal-requests/{id}/advance` | Transmit or cancel a requested reversal | OdfiOperations, OriginatorOps |
| POST | `/ach/settlement-batches/{id}/advance` | Dispatch or settle a settlement batch | OdfiOperations |
| POST | `/ach/settlement-batches/{id}/reconcile` | Reconcile a settled batch (zero variance, SoD-enforced) | OdfiFinance |
| GET | `/ach/settlement-batches/{id}` | Read a settlement batch | All roles |
| GET | `/ach/settlement-batches/{id}/gl-postings` | List a batch's GL postings | OdfiOperations, OdfiFinance, OdfiRiskOfficer, OdfiUnderwriter |
| POST | `/ach/cutoff-windows` | Define a cutoff window and its rate card | OdfiOperations |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_RESOURCE_OWNERSHIP` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ORIGINATOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_ORIGINATOR_STATUS_TERMINAL` | 409 Conflict |
| `ERR_FILE_NOT_WAREHOUSED` | 409 Conflict |
| `ERR_FILE_EMPTY` | 422 Unprocessable Entity |
| `ERR_RELEASE_DATE_MISMATCH` | 409 Conflict |
| `ERR_NO_ELIGIBLE_WINDOW` | 422 Unprocessable Entity |
| `ERR_ENTRY_NOT_SETTLED` | 409 Conflict |
| `ERR_ENTRY_NOT_RETURNED` | 409 Conflict |
| `ERR_REPRESENTMENT_CODE_PROHIBITED` | 422 Unprocessable Entity |
| `ERR_REPRESENTMENT_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_SAME_DAY_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_EFFECTIVE_DATE_WINDOW` | 422 Unprocessable Entity |
| `ERR_EXPOSURE_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_REVERSAL_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_INVALID_REVERSAL_REASON` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACTIVE_REVERSAL` | 409 Conflict |
| `ERR_REVERSAL_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_BATCH_NOT_OPEN` | 409 Conflict |
| `ERR_RECONCILIATION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_NOC_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_RISK_CASE_ALREADY_RESOLVED` | 409 Conflict |
| `ERR_RESOLUTION_NOT_APPLICABLE` | 409 Conflict |
