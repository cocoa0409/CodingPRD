# Music Publishing Administration & Split Management API — Product Requirements Document

## 1. Introduction

A music publisher earns its administration fee by doing unglamorous work with absolute precision: registering songs with performing rights organizations and mechanical societies, documenting exactly who owns what percentage of each composition, collecting royalty income as it flows in from societies, licensees, and sub-publishers around the world, and turning that income into accurate, auditable payments to writers. Errors compound quickly in this business — a split documented incorrectly in January becomes a misallocated statement in June and a breach-of-contract dispute in December. This document specifies an API that runs that entire back office: catalog onboarding, copyright and society registration, split negotiation between writers and the publisher, royalty statement intake with deterministic work matching, provisional and final allocation of income against confirmed splits, advance recoupment, periodic distribution runs to writers, sub-publishing retention, licensee audits, and the long-horizon tracking of statutory termination rights under U.S. copyright law.

Two design commitments shape everything that follows. First, the system is a ledger: every monetary figure is an integer number of cents, every derived balance can be recomputed from source records, and every amendment reverses prior financial effects rather than editing history. Second, authority is segregated: the operator who processes a royalty statement is never the one who approves the payout it feeds, and the analyst who calculates a distribution run is never the one who approves it. Time itself is a managed input — a logical clock governs all lifecycle timestamps and the lazily derived statuses that depend on dates, so that long-dated rights windows can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API: authentication, response shape, pagination, identity and versioning of resources, the logical clock, monetary precision, concurrency control, and the order in which validations are evaluated.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if the value of `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).

The system recognizes exactly six roles, spelled as follows: `PublisherAdmin`, `CopyrightSpecialist`, `RoyaltyAnalyst`, `FinanceManager`, `Auditor`, and `Writer`. The `PublisherAdmin` is the publishing-house administrator who owns the catalog, the split sets, the sub-publishing network, licensees, societies, advances origination, and the logical clock. The `CopyrightSpecialist` handles copyright filings, society registrations, and termination claims. The `RoyaltyAnalyst` ingests and processes royalty statements and calculates distribution runs. The `FinanceManager` approves and pays advances, approves and pays distribution runs, and settles audits — deliberately segregated from statement processing and run calculation. The `Auditor` conducts examinations of licensee reporting. The `Writer` is the songwriter, who confirms or rejects their own split lines and reads their own earnings.

When `X-User-Role` is `PublisherAdmin`, `CopyrightSpecialist`, `RoyaltyAnalyst`, `FinanceManager`, or `Auditor`, the `X-User-ID` value is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `calculated_by_user_id` or `approved_by_user_id` on a distribution run — but it never compares that value to any entity's `id`. When `X-User-Role` is `Writer`, `X-User-ID` is the `id` of the acting Writer; ownership checks on any resource that references a Writer compare the resource's foreign-key field to `X-User-ID`. This governs two places: a Writer may confirm or reject only their own WRITER split lines (where the line's `writer_id` equals `X-User-ID`), and a Writer may read only their own earnings summary (where the addressed writer's `id` equals `X-User-ID`).

Access to every operation is restricted by role, as enumerated in §4. An attempt to perform an action outside the caller's role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403); a Writer touching a split line that is not their own WRITER line is instead rejected with `ERR_SPLIT_LINE_OWNERSHIP_MISMATCH` (HTTP 403).

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order.

List responses carry the following fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identity

Every resource in the system — Writer, Work, Society, SocietyRegistration, SplitSet, SplitLine, SubPublisher, SubPublishingAgreement, Licensee, RoyaltyStatement, StatementLine, AllocationLine, Advance, DistributionRun, LicenseeAudit, and TerminationClaim — carries a standard set of system-managed properties:

- `id` (string): a server-minted UUID, with no type prefix of any kind.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at 1 at creation and increments on every mutation, including mutations driven by system cascades rather than direct client calls.

Two cross-entity version effects deserve emphasis because they are easy to miss: creating a SplitSet increments the parent Work's `version` by 1, and creating an Advance increments the parent Writer's `version` by 1. Lifecycle timestamps recorded by workflow actions — such as `submitted_at`, `registered_at`, `confirmed_at`, `paid_at`, and `notice_filed_at` — are read from the logical clock described in §2.5.

### 2.5. The Logical Clock and Lazily Derived Statuses

The system runs on a logical clock, never on wall-clock time. Before any operator sets it, the logical clock reads exactly 2026-08-01T00:00:00Z. A `PublisherAdmin`-only capability sets the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; once set, the clock stays where it was put until set again. Every time-dependent read in the system — disbursement timestamps, submission timestamps, expiry evaluation, termination-window derivation — reads this clock.

Two entities have statuses that are derived lazily from the logical clock rather than stored by an explicit transition. A SubPublishingAgreement in `ACTIVE` behaves as `EXPIRED`, and reports `EXPIRED` on any read, once the logical clock reaches or passes its `effective_to`. A TerminationClaim in `TRACKING` behaves as `NOTICE_WINDOW_OPEN` once the logical clock reaches or passes its `window_open_date`; and a claim that has never reached `NOTICE_FILED` behaves as `LAPSED` once the logical clock passes its `window_close_date`. These derived statuses are re-evaluated on every read and before every action on the affected resource; whenever the clock is set to a new value, subsequent reads and actions reflect the new derivation.

### 2.6. Monetary Representation: Integer Cents and Basis Points

All monetary amounts in the system are integers denominated in cents — every field whose name ends in `_cents`, whether input, computed, or snapshot. Division in monetary calculations always rounds down (floor) to a whole cent; there is no fractional-cent arithmetic anywhere, and no rounding mode other than floor is ever applied. Where a calculation cannot divide a pool evenly, the leftover cents are distributed one cent at a time in a pinned order defined by the relevant workflow, so results are deterministic and reproducible.

Percentage shares are expressed in basis points, where 10000 basis points equal 100%. Split documentation, sub-publisher retention, and advance recoupment rates all use basis points.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and they are the only two endpoints in the system that accept a version field.

Creating a SplitSet requires the request to carry `expected_work_version`, holding the `version` of the target Work as the client last observed it. If that value does not equal the Work's current `version` at the moment of creation — for example because another revision was created in the meantime, or a confirmation cascade advanced the Work — the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

Creating an Advance requires the request to carry `expected_writer_version`, holding the `version` of the target Writer as the client last observed it. If the Writer's `version` has advanced since that observation, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Both fields are non-optional on their respective creates; no other endpoint accepts or requires a version field.

### 2.8. Reference Resolution and the Order of Validation

Before any business rule runs, the server resolves every reference the request names. Path identifiers are validated left to right, and the first identifier that does not correspond to an existing resource ends the request with `ERR_NOT_FOUND` (HTTP 404). The same error covers references inside request bodies: the polymorphic `source_id` of a royalty statement is resolved through its `source_type` (a Society when `SOCIETY`, a Licensee when `LICENSEE`, a SubPublisher when `SUB_PUBLISHER`), and `parent_work_id`, `amends_statement_id`, and the `work_id` supplied on a manual line match must each name an existing resource.

When a request violates several rules at once, validation tiers are evaluated in a fixed order so the returned error is deterministic:

1. **Authentication context** — both headers present and the role declared, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Authorization and ownership** — the role is permitted on the endpoint, else `ERR_FORBIDDEN_FOR_ROLE`; the Writer-ownership clauses on split lines and the earnings summary, else `ERR_SPLIT_LINE_OWNERSHIP_MISMATCH` or `ERR_FORBIDDEN_FOR_ROLE` respectively.
3. **Existence** — every path and body reference resolves, left to right, else `ERR_NOT_FOUND`.
4. **Request shape** — required fields present, enum membership, integer ranges, date-range shape (`effective_from` strictly before `effective_to`, `period_end` on or after `period_start`), `line_number` unique within a statement, and participant fields consistent with `participant_type`, else `ERR_VALIDATION` or `ERR_INVALID_DATE_RANGE`.
5. **State preconditions** — the target entity's state machine permits the trigger, and cross-entity state gates hold (a confirmed split set exists where required; an amended statement is in the right state), else `ERR_INVALID_STATE_TRANSITION`, `ERR_NO_CONFIRMED_SPLIT_SET`, `ERR_AMENDED_STATEMENT_NOT_FINAL`, or `ERR_STATEMENT_ALREADY_SUPERSEDED`. Where an amendment target is concerned, `ERR_STATEMENT_ALREADY_SUPERSEDED` is checked before the generic not-final check.
6. **Rights and compliance gates** — no split-set creation or submission and no registration submission against a `TERMINATED` work; termination effective dates inside their statutory window; notice filed inside its filing window; distribution approval segregated from calculation, else `ERR_WORK_RIGHTS_TERMINATED`, `ERR_EFFECTIVE_DATE_OUTSIDE_WINDOW`, `ERR_TERMINATION_WINDOW_NOT_OPEN`, `ERR_NOTICE_DEADLINE_PASSED` (all HTTP 409), or `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
7. **Referential good standing** — referenced entities are in a status that permits the operation: the sub-publisher is `ACTIVE` at agreement activation, the writer is `ACTIVE` at advance approval, the work is `REGISTERED` at manual line match, else `ERR_SUB_PUBLISHER_NOT_ACTIVE`, `ERR_WRITER_NOT_ACTIVE`, or `ERR_WORK_NOT_REGISTERED`.
8. **Interval conflicts** — agreement coverage overlap at activation, audit period overlap at audit creation, statement period overlap at statement creation, else `ERR_COVERAGE_OVERLAP`, `ERR_AUDIT_PERIOD_OVERLAP`, or `ERR_STATEMENT_PERIOD_OVERLAP`.
9. **Aggregate and duplicate constraints** — split pool sums, minimum shares, duplicate split participants, duplicate society registrations, and audit sample-base validity, else `ERR_SPLIT_SUM_INVALID`, `ERR_ZERO_SHARE_LINE`, `ERR_DUPLICATE_SPLIT_PARTICIPANT`, `ERR_DUPLICATE_SOCIETY_REGISTRATION`, or `ERR_AUDIT_SAMPLE_BASE_INVALID`.
10. **Money tie-outs and checkpoint staleness** — the statement gross tie-out, non-empty statement, presence of matched lines, and distribution-run staleness, else `ERR_GROSS_MISMATCH`, `ERR_EMPTY_STATEMENT`, `ERR_NO_MATCHED_LINES`, or `ERR_STALE_DISTRIBUTION_RUN`.
11. **Optimistic concurrency** — the `expected_work_version` and `expected_writer_version` checks of §2.7, else `ERR_STALE_VERSION`.

Within a single operation, where the workflow defines its own ordering, that ordering is stated in §3 alongside the workflow (for example, agreement activation checks the sub-publisher's status before checking coverage overlap).

### 2.9. Derived Balances, Rollups, and Cross-Entity Consistency

Several entities carry derived state that the server maintains automatically. A SplitSet's lifecycle is compound: its status bubbles up from the confirmation states of its child split lines. A Work's `registration_status` bubbles up from the society registrations filed against it. Writer balances (`payable_balance_cents`, `advance_outstanding_cents`, `lifetime_earned_cents`) and Work collection totals (`total_collected_cents`, `total_distributed_cents`) are rollups over statements, allocations, and advances.

Rollups are always recomputed in full from source records when a trigger fires — never patched incrementally in a way that could drift. Any mutation caused by such a cascade still counts as a mutation: the affected resource's `updated_at` is refreshed and its `version` incremented, exactly as if a client had written it directly. This holds for system-driven transitions as well, such as a SplitSet flipping to `CONFIRMED` when its last line confirms, or a statement flipping to `DISTRIBUTED` when its distribution run is paid.

## 3. Business Logic & Workflows

### 3.1. Catalog Onboarding: Writers, Works, and Counterparties

Everything begins with the catalog. A `PublisherAdmin` registers a **Writer** by supplying the writer's `legal_name`, their `ipi_number` (the IPI/CAE interested-party identifier, 9 to 13 characters and unique across all writers — attempts to register a duplicate are rejected), and their `pro_affiliation`, one of `ASCAP`, `BMI`, `SESAC`, `PRS`, `GEMA`, `SACEM`, or `NONE`. A new writer starts with `status` set to `ACTIVE`, `version` at 1, and all three computed balances — `payable_balance_cents`, `advance_outstanding_cents`, and `lifetime_earned_cents` — at zero; any client-supplied values for these computed fields are ignored. A writer can later be suspended by a `PublisherAdmin`, moving `status` from `ACTIVE` to `SUSPENDED` and incrementing `version`, and reactivated back from `SUSPENDED` to `ACTIVE`. Suspension matters downstream: approval of an advance is refused for a writer who is not `ACTIVE`. The writers list accepts optional `status` and `pro_affiliation` filters.

Each writer's financial position is available as a computed read, the earnings summary, returning `writer_id`, `status`, `payable_balance_cents`, `advance_outstanding_cents`, and `lifetime_earned_cents`. A `PublisherAdmin`, `RoyaltyAnalyst`, or `FinanceManager` may read any writer's summary; a `Writer` caller may read only their own — when the addressed writer's `id` does not equal `X-User-ID`, the read is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

A **Work** is created by a `PublisherAdmin` with a primary `title` and the `grant_date` of the original publishing grant — the date from which termination windows are projected decades later. Alternate spellings may be captured in `alternate_titles`, which defaults to an empty list. Derivative works (samples, arrangements) are registered by supplying `parent_work_id`, which must reference an existing Work and is absent for originals; because no endpoint ever updates this field, derivative chains are acyclic by construction. At creation the server mints the `work_code`, a sequential publisher work number in the format `W-000001`, `W-000002`, and so on, unique across works. The work starts with `registration_status` set to `UNREGISTERED` and `copyright_status` set to `UNFILED` — two parallel status dimensions that evolve independently — and with `total_collected_cents` and `total_distributed_cents` at zero. The works list accepts optional `parent_work_id`, `registration_status`, and `copyright_status` filters.

Three kinds of counterparty round out the catalog. A **Society** is created by a `PublisherAdmin` with a display `name`, a short `code` that must be unique, a `society_type` of `PRO`, `MECHANICAL`, or `COLLECTION`, and a home `territory_code` (an ISO-style code, or `WORLD`). A **SubPublisher** is created with a `name` and `home_territory_code`, starts `ACTIVE`, and — exactly like a writer — can be suspended from `ACTIVE` to `SUSPENDED` and reactivated back, each change incrementing its `version`. A **Licensee** is created with a `name` and a `licensee_type` of `STREAMING`, `LABEL`, `SYNC_HOUSE`, or `OTHER`.

### 3.2. Copyright Filings and Society Registration

On the copyright dimension, a `CopyrightSpecialist` moves a work through two recordals. Filing the copyright application — a call carrying a `filing_ref` — moves `copyright_status` from `UNFILED` to `FILED`; attempting it from any other state is rejected with `ERR_INVALID_STATE_TRANSITION`. Recording the copyright-office registration — a call carrying a `registration_number` — then moves the work from `FILED` to `COPCO_REGISTERED`, again with `ERR_INVALID_STATE_TRANSITION` from any other state. Each recordal increments the Work's `version`. A fourth state, `TERMINATED`, is reachable from `UNFILED`, `FILED`, or `COPCO_REGISTERED`, but only as a system cascade when a termination claim takes effect (see §3.10); there is no direct filing action into it.

Society registration is a separate, cyclic lifecycle owned by the `CopyrightSpecialist`. A **SocietyRegistration** is created against a `work_id` and a `society_id` in `DRAFT` status. At most one registration per work-and-society pair may exist in any of `DRAFT`, `SUBMITTED`, `ACKNOWLEDGED`, or `REGISTERED`; a conflicting create is rejected with `ERR_DUPLICATE_SOCIETY_REGISTRATION`. The registrations list accepts optional `work_id`, `society_id`, and `status` filters.

Submitting a registration moves it from `DRAFT` to `SUBMITTED` and stamps `submitted_at` from the logical clock. Two cross-entity gates guard submission: the work's `copyright_status` must not be `TERMINATED` (else `ERR_WORK_RIGHTS_TERMINATED`), and the work must have a SplitSet in `CONFIRMED` status (else `ERR_NO_CONFIRMED_SPLIT_SET`) — a publisher does not register a work with a society before the ownership splits are settled. Submitting from any state other than `DRAFT` or `REJECTED` is rejected with `ERR_INVALID_STATE_TRANSITION`. Once any registration for a work enters `SUBMITTED`, the work's `registration_status` bubbles up from `UNREGISTERED` to `PENDING_SOCIETY`.

From `SUBMITTED`, the society's response is recorded in one of two directions. Acknowledgement moves the registration to `ACKNOWLEDGED` and captures the society-assigned `society_work_number` from the call. Rejection moves it to `REJECTED` and captures the supplied `reason` into `rejection_reason`; if that rejection leaves no other registration of the same work in `DRAFT`, `SUBMITTED`, `ACKNOWLEDGED`, or `REGISTERED`, the work's `registration_status` falls back from `PENDING_SOCIETY` to `UNREGISTERED`. A rejected registration is not terminal: resubmitting moves it from `REJECTED` back to `SUBMITTED`, clears `rejection_reason` to null, refreshes `submitted_at`, and re-applies both cross-entity gates (non-terminated work, confirmed split set) exactly as on a first submission.

Finally, recording registration moves an `ACKNOWLEDGED` registration to `REGISTERED`, stamps `registered_at` from the logical clock, and lifts the work's `registration_status` to `REGISTERED`. The register call may optionally carry an `iswc`: when the registration's society has `society_type` `PRO`, and the work does not yet have one, the provided `iswc` is assigned to the work — this is the only path by which a work acquires its International Standard Work Code, and a work that already has an `iswc` keeps it. Every bubble-up on the registration dimension increments the Work's `version`.

### 3.3. Negotiating the Split: Sets, Lines, and Confirmations

Splits for a work are documented as a **SplitSet**: a versioned container of per-party **SplitLine** rows. A `PublisherAdmin` creates a set by naming the `work_id`, passing the optimistic-concurrency field described in §2.7, and supplying `lines` — an array in which each line declares a `participant_type` of `WRITER` or `PUBLISHER`, a `share_bp` (the line's share of its pool in basis points, where 10000 is the whole pool), and the participant identity: `writer_id` referencing an existing Writer when the participant type is `WRITER`, or `publisher_name` as a display name when it is `PUBLISHER`. Each participant field must be present exactly when its participant type calls for it and null otherwise; inconsistency is rejected with `ERR_VALIDATION`.

Three aggregate constraints are enforced when the set is created. The writer pool — the sum of `share_bp` over all `WRITER` lines — must total exactly 10000 basis points, and independently the publisher pool must total exactly 10000 basis points; any other sum is rejected with `ERR_SPLIT_SUM_INVALID`. Every line's `share_bp` must be at least 1; a zero-share line is rejected with `ERR_ZERO_SHARE_LINE`. And no `writer_id` may appear twice, nor any `publisher_name` twice, within one set; duplicates are rejected with `ERR_DUPLICATE_SPLIT_PARTICIPANT`. A create that passes validation stamps each line's `split_set_id`, leaves every line's `confirmation_status` at `PENDING`, assigns the set its `revision_index` — a per-work creation sequence starting at 1 — computes `writer_pool_total_bp` and `publisher_pool_total_bp` as the respective pool sums, sets the set to `DRAFT`, and increments the Work's `version` by 1. Creating a set against a work whose copyright is `TERMINATED` is refused with `ERR_WORK_RIGHTS_TERMINATED`. The split-sets list accepts optional `work_id` and `status` filters; the split-lines list accepts optional `split_set_id`, `writer_id`, and `confirmation_status` filters, and lines created together in one create or revise request receive strictly increasing `created_at` values in array order, so the original array order is recoverable from the list.

Submitting the set — a `PublisherAdmin` action — moves it from `DRAFT` to `PENDING_CONFIRMATIONS`, provided the work is not `TERMINATED` (else `ERR_WORK_RIGHTS_TERMINATED`) and the set is in `DRAFT` (else `ERR_INVALID_STATE_TRANSITION`). From there the parties weigh in. Confirming a line moves it from `PENDING` to `CONFIRMED` and stamps `confirmed_at` from the logical clock; rejecting one moves it to `REJECTED` and stores the supplied `reason` in the line's `rejection_reason`. Both actions are permitted only while the parent set is `PENDING_CONFIRMATIONS` (else `ERR_INVALID_STATE_TRANSITION`), and both enforce the same ownership rule: a `WRITER` line may be confirmed or rejected only by a `Writer` caller whose `X-User-ID` equals the line's `writer_id` — a `PublisherAdmin` may not touch a `WRITER` line at all — while a `PUBLISHER` line may be confirmed or rejected only by a `PublisherAdmin`. Any breach is rejected with `ERR_SPLIT_LINE_OWNERSHIP_MISMATCH`.

The set's status is a compound of its lines. When the last `PENDING` line of a set becomes `CONFIRMED` — that is, when every line has confirmed — the set moves from `PENDING_CONFIRMATIONS` to `CONFIRMED`, and any other SplitSet of the same work that was `CONFIRMED` is moved to `SUPERSEDED`; the Work's `version` increments. When any line of a set is rejected, the set immediately moves from `PENDING_CONFIRMATIONS` to `DISPUTED`, and the set's `dispute_reason` is copied from the rejecting line's reason. A dispute is not the end: revising a `DISPUTED` set — again a `PublisherAdmin` action, from no other state — deletes all of the set's existing lines, replaces them with the `lines` supplied in the revise call (each fresh line starting `PENDING`), clears `dispute_reason` to null, and returns the set to `DRAFT`, ready to be submitted again. The same pool-sum, zero-share, and duplicate-participant constraints apply to the revised lines exactly as at creation. Note that only a `DRAFT` set can be submitted, so a revised set must go back through submission before lines can confirm.

Termination of the work's rights (§3.10) cancels any set of that work still in `DRAFT`, `PENDING_CONFIRMATIONS`, or `DISPUTED`, moving it to `CANCELLED`; each of its still-`PENDING` lines is moved to `REJECTED` by the system with `rejection_reason` set to `WORK_RIGHTS_TERMINATED`. `SUPERSEDED` and `CANCELLED` are terminal for a set.

### 3.4. Sub-Publishing Agreements and Territorial Coverage

Publishers exploit foreign territories through sub-publishers who collect locally and remit the balance net of their retention. A `PublisherAdmin` drafts a **SubPublishingAgreement** by naming the `sub_publisher_id` and supplying `territory_codes` (a non-empty list of territory codes), `income_types` (a non-empty subset of `PERFORMANCE`, `MECHANICAL`, `SYNC`, `PRINT`, `OTHER`), a `retention_bp` between 1 and 5000 basis points — the share of gross the sub-publisher keeps, never more than half — and a coverage window from `effective_from` (inclusive) to `effective_to` (exclusive), forming a half-open interval. `effective_from` must be strictly before `effective_to`, else `ERR_INVALID_DATE_RANGE`. The agreement starts in `DRAFT`; overlap with other agreements is deliberately not checked at creation. The agreements list accepts optional `sub_publisher_id` and `status` filters.

Activating an agreement — a `PublisherAdmin` action from `DRAFT` only — runs two checks in a fixed order. First, the referenced sub-publisher must be `ACTIVE`; activating against a `SUSPENDED` sub-publisher is rejected with `ERR_SUB_PUBLISHER_NOT_ACTIVE`. Second, a coverage-overlap check runs against every other `ACTIVE` agreement: activation is rejected with `ERR_COVERAGE_OVERLAP` if any other active agreement's `territory_codes` intersect this one's, and its `income_types` intersect this one's, and the two half-open windows genuinely overlap — the other's `effective_from` falls before this one's `effective_to`, and this one's `effective_from` falls before the other's `effective_to`. Touching intervals are not overlap: a neighbor whose `effective_to` equals this agreement's `effective_from` coexists cleanly. Because the overlap rule permits at most one active agreement per territory-and-income-type-and-date combination, the retention selector used during allocation (§3.5) is deterministic.

An `ACTIVE` agreement can be terminated — moving to `TERMINATED` — by a `PublisherAdmin`. Expiry needs no action at all: per §2.5, once the logical clock reaches or passes `effective_to`, the agreement reports and behaves as `EXPIRED`. `TERMINATED` and `EXPIRED` are both terminal.

### 3.5. Royalty Statement Intake, Matching, and Allocation

Royalty income arrives as a **RoyaltyStatement** created by a `RoyaltyAnalyst`. The header names its reporting source polymorphically: `source_type` is one of `SOCIETY`, `LICENSEE`, or `SUB_PUBLISHER`, and `source_id` must identify an existing entity of the corresponding kind — a Society, a Licensee, or a SubPublisher respectively — else `ERR_NOT_FOUND`. The header also carries the `income_type` (one of `PERFORMANCE`, `MECHANICAL`, `SYNC`, `PRINT`, `OTHER`), the `territory_code` the statement covers, the earning period from `period_start` through `period_end` (a closed interval — `period_end` on or after `period_start`, else `ERR_INVALID_DATE_RANGE`), the header-declared `gross_amount_cents`, optionally the `amends_statement_id` of a prior statement this one supersedes (§3.6), and optionally an inline `lines` array. Each line declares a `line_number` (unique within the statement and at least 1, else `ERR_VALIDATION`), the `reported_title` as the source reported it, optional matching hints `reported_iswc` and `reported_work_code`, and the line's `gross_cents` (at least 1). Lines start with `work_id` null and `match_status` `UNMATCHED`; the statement itself starts in `RECEIVED`. Two statements with the same source, income type, and territory may not cover overlapping periods: the check is closed-inclusive — a shared boundary date conflicts — and it considers every statement of that source, income type, and territory whose status is not `REJECTED` or `SUPERSEDED`, excluding the statement being amended, if any. A conflict is rejected with `ERR_STATEMENT_PERIOD_OVERLAP`. The statements list accepts optional `source_id`, `income_type`, `status`, and `amends_statement_id` filters; the statement-lines list accepts optional `statement_id`, `work_id`, and `match_status` filters.

Matching begins when a `RoyaltyAnalyst` runs the auto-match pass, moving the statement from `RECEIVED` to `MATCHING_REVIEW` — refused with `ERR_INVALID_STATE_TRANSITION` from any other state, and with `ERR_EMPTY_STATEMENT` if the statement has no lines. The pass examines every `UNMATCHED` line and builds a candidate set of works: any work whose `iswc` equals the line's `reported_iswc` (when that hint is present), plus any work whose `work_code` equals the line's `reported_work_code` (when that hint is present). Only works whose `registration_status` is `REGISTERED` are eligible — a work the societies do not yet know cannot receive royalties. Candidates are ranked with ISWC-matched works above work-code-matched works, ties broken by ascending work `created_at`; the best candidate wins, the line's `work_id` is set, and its `match_status` becomes `AUTO_MATCHED`. A line with no candidates remains `UNMATCHED`.

A `RoyaltyAnalyst` may also match a line manually, supplying the target `work_id`. This is permitted only while the line is `UNMATCHED` and the statement is in `RECEIVED` or `MATCHING_REVIEW` (else `ERR_INVALID_STATE_TRANSITION`), and only onto a work that exists (else `ERR_NOT_FOUND`) and is `REGISTERED` (else `ERR_WORK_NOT_REGISTERED`); success sets the line's `work_id` and marks it `MANUAL_MATCHED`.

Allocation moves the statement from `MATCHING_REVIEW` to `ALLOCATED` and is where money is first computed. Four preconditions gate it, in the statement-processing order: the statement must contain at least one line (`ERR_EMPTY_STATEMENT`); the sum of every line's `gross_cents` must equal the header's `gross_amount_cents` exactly — the tie-out, else `ERR_GROSS_MISMATCH`; at least one line must be matched, else `ERR_NO_MATCHED_LINES`; and every matched line's work must have a SplitSet in `CONFIRMED` status, else `ERR_NO_CONFIRMED_SPLIT_SET`.

The computation itself runs per matched line and proceeds in three stages. **Stage one, retention.** Throughout this computation, a line's effective gross means its own `gross_cents` plus the share of provisional spread it receives in stage two — or, at the final stage where no spread exists, exactly its `gross_cents`. The server selects the sub-publishing agreement that applies to this line: an agreement that is `ACTIVE` (lazily excluding expired ones per §2.5), whose `territory_codes` contain the statement's `territory_code`, whose `income_types` contain the statement's `income_type`, and whose half-open coverage window contains the statement's `period_end` — `effective_from` on or before `period_end`, and `period_end` strictly before `effective_to`. At most one such agreement can exist; if none applies, retention for the line is zero. Otherwise the retention is the line's effective gross multiplied by the agreement's `retention_bp` and divided by 10000, rounded down to a whole cent. Retention is computed per line and summed into the statement's `retained_cents`.

**Stage two, the provisional spread.** Because the provisional stage assumes unmatched income will eventually find a home, unmatched gross is spread across matched lines. The unmatched total is the sum of `gross_cents` over all lines still `UNMATCHED`; the matched total is the same sum over matched lines. If the unmatched total is zero, no line receives any spread. Otherwise each matched line is credited with the unmatched total multiplied by that line's `gross_cents` and divided by the matched total, rounded down; the cents left over are distributed one at a time to matched lines in descending `gross_cents` order, ties broken by ascending line `created_at`. A line's effective gross for this stage is its own `gross_cents` plus its spread.

**Stage three, pool allocation.** From each matched line's effective gross, the line's retention is subtracted to yield the net. The net divides into two pools: the writer pool is one half of the net — 5000 of the 10000 basis points — rounded down to a whole cent, and the publisher pool is the remainder of the net, so an odd cent lands in the publisher pool. Within each pool, every split line first receives the pool multiplied by its `share_bp` and divided by 10000, rounded down; the pool's leftover cents are then dealt one at a time to that pool's lines in descending `share_bp` order, ties broken by ascending split-line `created_at`, at most one cent per line per pass, repeating passes until nothing remains. One **AllocationLine** is created per split line, in `PROVISIONAL` status, recording the `statement_line_id` and the `split_line_id` it pays — pinned to the SplitSet that was `CONFIRMED` at allocation time, so a later supersession of the work's splits never rewrites history — plus a denormalized `statement_id`, the `participant_type` copied from the split line, and for `WRITER` rows the `writer_id` (null for `PUBLISHER` rows). The computed amount lands in `provisional_amount_cents`; `final_amount_cents` stays null until finalization, and `advance_applied_cents` and `net_payable_cents` start at zero. Allocation rows are created in a pinned order so their `created_at` values are strictly increasing: matched statement lines are processed in ascending line `created_at` order, and within each line the `WRITER`-pool rows are created first in ascending split-line `created_at` order, then the `PUBLISHER`-pool rows. The allocation-lines list accepts optional `statement_line_id`, `split_line_id`, `statement_id`, and `writer_id` filters.

Once allocation completes, the statement's computed totals are refreshed: `retained_cents` carries the summed sub-publisher retention, `suspense_cents` is zero at this stage because every unmatched cent was provisionally spread, and `allocated_total_cents` is the sum of the provisional allocation amounts.

Finalization — a `RoyaltyAnalyst` action from `ALLOCATED` only — locks the money. Allocations are recomputed under the final variant: each matched line's effective gross is exactly its `gross_cents` with no spread, and the unmatched gross is no longer distributed — it accumulates instead into the statement's `suspense_cents`, held back until the unmatched lines are resolved by later amendment. The same retention and pool-split machinery as above then produces each allocation row's `final_amount_cents`, and every row moves from `PROVISIONAL` to `FINAL`. Because the two variants treat unmatched income differently, identical statement data yields different per-writer amounts at the two stages; `allocated_total_cents` is recomputed as the sum of the final amounts, and `retained_cents` is recomputed as well. For each `WRITER` allocation row, the recoupment waterfall of §3.7 then runs against the writer's outstanding advances, determining `advance_applied_cents` and `net_payable_cents`, and the writer's `payable_balance_cents` is credited with the net. Each affected writer's `advance_outstanding_cents` and `lifetime_earned_cents` are recomputed and their `version` incremented; each matched work's `total_collected_cents` is recomputed.

Work rollups obey one rule everywhere they are maintained: a work's `total_collected_cents` is the sum of `gross_cents` over statement lines matched to that work whose statement is `FINALIZED` or `DISTRIBUTED`, and `total_distributed_cents` is the same sum restricted to statements that are `DISTRIBUTED`; both are recomputed in full at every trigger, and statements that are `SUPERSEDED` or `REJECTED` contribute nothing.

Two exits remain. A `RoyaltyAnalyst` may reject a statement in `RECEIVED` — a call carrying a `reason` — moving it to terminal `REJECTED`. And a `FINALIZED` statement becomes `DISTRIBUTED` only as a system effect when a distribution run that included it is paid (§3.8), at which point each matched work's `total_distributed_cents` is recomputed. A statement's full lifecycle is therefore `RECEIVED` → `MATCHING_REVIEW` → `ALLOCATED` → `FINALIZED` → `DISTRIBUTED`, with the `REJECTED` and `SUPERSEDED` branches off `RECEIVED` and `FINALIZED` respectively.

### 3.6. Statement Amendments and Financial Reversal

Sources restate. When a replacement statement is created with `amends_statement_id` naming a prior statement, the system treats it as an amendment: the new statement is created in `RECEIVED` with its own lines and proceeds through the normal pipeline, while the referenced statement is superseded in the same operation. The amendment reference must resolve (else `ERR_NOT_FOUND`), and two state checks then apply in a fixed order — first, if the referenced statement is already `SUPERSEDED`, the create is rejected with `ERR_STATEMENT_ALREADY_SUPERSEDED`; second, if it is anything other than `FINALIZED`, the create is rejected with `ERR_AMENDED_STATEMENT_NOT_FINAL`. Only a `FINALIZED` statement may be amended, because only finalized money needs reversing.

Superseding moves the referenced statement from `FINALIZED` to `SUPERSEDED` and unwinds every financial effect it produced. Each of its allocation rows in `FINAL` status moves to `REVERSED`. The recoupment waterfall is replayed in reverse — applications are undone in reverse chronological order of how they were applied: for each reversed row, its `advance_applied_cents` is credited back to the originating advance, decreasing that advance's `recouped_cents` and increasing its `outstanding_cents` by the same amount. The advance's lifecycle regresses accordingly: an advance in `RECOUPED` whose `recouped_cents` is restored above zero (while remaining below its principal) returns to `RECOUPING`, and an advance in `RECOUPING` whose `recouped_cents` falls all the way to zero returns to `PAID`. On every affected writer, `payable_balance_cents` is debited by the reversed rows' `net_payable_cents`, and `advance_outstanding_cents` and `lifetime_earned_cents` are recomputed from source records. Each matched work's `total_collected_cents` is recomputed under the rollup rule of §3.5, so the superseded statement stops contributing. After every reversal, the per-advance invariant of §3.7 must still hold exactly.

### 3.7. Advances and the Recoupment Waterfall

A publisher may front a writer money against future royalties. A `PublisherAdmin` originates an **Advance** by naming the `writer_id`, passing the optimistic-concurrency field of §2.7, and supplying the external `agreement_ref`, the principal `amount_cents` (at least 1), and optionally a `recoup_rate_bp` between 1 and 10000 basis points that defaults to 10000 — full diversion of the writer's allocations until the advance is recovered. The advance starts in `DRAFT`, and its creation increments the Writer's `version` by 1. The advances list accepts optional `writer_id` and `status` filters.

From there a `FinanceManager` drives the money. Approval moves the advance from `DRAFT` to `APPROVED`, but only while the writer is `ACTIVE` — approving for a `SUSPENDED` writer is rejected with `ERR_WRITER_NOT_ACTIVE`, and approval from any state other than `DRAFT` is `ERR_INVALID_STATE_TRANSITION`. Disbursement moves an `APPROVED` advance to `PAID`, stamps `paid_at` from the logical clock, and sets `outstanding_cents` equal to the full `amount_cents` while `recouped_cents` remains zero; the writer's `advance_outstanding_cents` is recomputed and the writer's `version` increments. A `FinanceManager` may also cancel an advance while it is still `DRAFT` or `APPROVED`, moving it to terminal `CANCELLED`; once paid, an advance can no longer be cancelled.

Recoupment happens inside statement finalization (§3.5), as a waterfall over each `WRITER` allocation row. Starting from the row's `final_amount_cents` as the remaining balance, the server walks the writer's advances that are `PAID` or `RECOUPING`, in ascending `paid_at` order with ties broken by ascending advance `created_at`. At each advance, the recoupment budget is the remaining balance multiplied by the advance's `recoup_rate_bp` and divided by 10000, rounded down; the amount actually applied is the smaller of that budget and the advance's `outstanding_cents`. The application increases the advance's `recouped_cents` and decreases its `outstanding_cents` by the applied amount and reduces the remaining balance accordingly, stopping early if the remaining balance reaches zero. Status follows the money: a `PAID` advance receiving its first application while anything remains outstanding moves to `RECOUPING`, and a `RECOUPING` advance whose `outstanding_cents` reaches exactly zero moves to terminal `RECOUPED`, with the writer's `advance_outstanding_cents` recomputed on each such transition. When the walk ends, the row's `advance_applied_cents` is the portion consumed by recoupment — the final amount minus the remaining balance — and its `net_payable_cents` is the remaining balance, which is credited to the writer's `payable_balance_cents`.

Two invariants close the loop. For every advance in `PAID`, `RECOUPING`, or `RECOUPED`, its `amount_cents` always equals `recouped_cents` plus `outstanding_cents` — and this must hold after every reversal replayed under §3.6 as well. And the writer's rollup fields are always derivable: `advance_outstanding_cents` is the sum of `outstanding_cents` over the writer's advances in `PAID` or `RECOUPING`; `lifetime_earned_cents` is the sum of `final_amount_cents` over the writer's allocation rows in `FINAL` status; and `payable_balance_cents` is a running balance credited with each finalize's net, debited with each reversal's net, and debited again with each distribution payout — recomputed from those sources whenever a rollup trigger fires (advance disbursement, statement finalization, statement supersede, distribution payment), the recomputed value must equal the running balance exactly.

### 3.8. Distribution Runs and Payout Discipline

Writers are paid in periodic batches. A `RoyaltyAnalyst` opens a **DistributionRun** by supplying a `period_label`, which must be unique across runs; the run starts `OPEN`. The runs list accepts an optional `status` filter.

Calculating the run — a `RoyaltyAnalyst` action from `OPEN` only — captures an immutable snapshot. Every writer whose `payable_balance_cents` is at least $25.00 (2500 cents) earns a payout entry, the boundary included: a writer at exactly 2500 cents is paid. The snapshot's `writer_payouts` lists each eligible `writer_id` with an `amount_cents` equal to their full payable balance, ordered by ascending writer `created_at`; `included_statement_ids` lists the ids of every statement in `FINALIZED` status at that moment, ordered by ascending statement `created_at`; and `total_payable_cents` is the sum of the payout amounts. The caller's `X-User-ID` is recorded as `calculated_by_user_id`, and the run moves to `CALCULATED`.

Approval is where segregation of duties bites. A `FinanceManager` approves a `CALCULATED` run, but the approver's `X-User-ID` must differ from `calculated_by_user_id` — the operator who calculated a run may never approve it, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Approval also enforces freshness: if any statement in `FINALIZED` status exists whose id is not in the snapshot's `included_statement_ids`, the run has gone stale and approval is rejected with `ERR_STALE_DISTRIBUTION_RUN`. A clean approval records `approved_by_user_id` and moves the run to `APPROVED`.

Payment executes the snapshot. A `FinanceManager` pays an `APPROVED` run; for each payout entry the writer's `payable_balance_cents` is debited by the entry's `amount_cents` and the writer's `version` incremented; every statement in `included_statement_ids` moves from `FINALIZED` to `DISTRIBUTED`; and each matched work of those statements has its `total_distributed_cents` recomputed. The run ends in terminal `PAID`. If the numbers look wrong before approval, a `RoyaltyAnalyst` may reopen a `CALCULATED` run, returning it to `OPEN` and clearing the snapshot entirely — `writer_payouts` and `included_statement_ids` emptied, `total_payable_cents` reset to zero, `calculated_by_user_id` cleared to null — ready to be calculated afresh.

### 3.9. Licensee Audits and Claim Valuation

When a licensee's reporting looks light, an `Auditor` opens a **LicenseeAudit** naming the `licensee_id`, the audited period from `period_start` through `period_end` (a closed interval — `period_end` on or after `period_start`, else `ERR_INVALID_DATE_RANGE`), and the `valuation_method`, either `ACTUAL_SHORTFALL` or `EXTRAPOLATED`. One licensee may not have two overlapping audits: the period check is closed-inclusive — a shared boundary date counts as overlap — and runs against that licensee's audits in any status; a conflict is rejected with `ERR_AUDIT_PERIOD_OVERLAP`. The audit starts `OPEN`; the audits list accepts optional `licensee_id` and `status` filters.

Fieldwork begins when the `Auditor` moves the audit from `OPEN` to `FIELDWORK`. Issuing findings — supplying the proven `actual_shortfall_cents` (zero or more) and, for the extrapolated variant, `sampled_base_cents` and `reported_base_cents` — moves the audit to `FINDINGS_ISSUED` and computes the claim. Under `ACTUAL_SHORTFALL`, the `claim_amount_cents` is exactly the `actual_shortfall_cents`. Under `EXTRAPOLATED`, the claim scales the proven shortfall up to the full period: the `actual_shortfall_cents` multiplied by the `reported_base_cents` and divided by the `sampled_base_cents`, rounded down to a whole cent. The extrapolated variant is only well-formed when `sampled_base_cents` is present and at least 1 and `reported_base_cents` is present and at least `sampled_base_cents`; otherwise issuing findings is rejected with `ERR_AUDIT_SAMPLE_BASE_INVALID`. Findings may be issued from `FIELDWORK` or from `UNDER_APPEAL` — in the latter case they represent amended findings, and `claim_amount_cents` is recomputed from the new inputs by the same rule.

An appeal, recorded by the `Auditor` with a `reason`, moves the audit from `FINDINGS_ISSUED` to `UNDER_APPEAL`, opening the loop back to amended findings. Resolution comes from a `FinanceManager`, who settles a `FINDINGS_ISSUED` audit by supplying the agreed `settlement_cents` (zero or more), moving it to terminal `SETTLED`. Alternatively, an `Auditor` may close an audit without findings while it is still `OPEN` or in `FIELDWORK`, moving it to terminal `CLOSED`. Every other trigger-state combination is rejected with `ERR_INVALID_STATE_TRANSITION`.

### 3.10. Termination Claims and the Reversion of Rights

U.S. copyright law gives authors a statutory right to reclaim their grants decades later, and tracking those windows is a core duty of this system. A `CopyrightSpecialist` opens a **TerminationClaim** by naming the `work_id`, the `statute_basis` — `SEC_203` or `SEC_304` — and the `intended_effective_date`. At creation the server projects the statutory calendar from the work's `grant_date` using whole-calendar-year arithmetic that preserves month and day (a February 29 date clamps to February 28 when the target year is not a leap year): `window_open_date` is the grant date plus 35 calendar years, `window_close_date` is the grant date plus 40 calendar years, `notice_earliest_date` is the intended effective date minus 10 calendar years, and `notice_latest_date` is the intended effective date minus 2 calendar years. The intended effective date must fall strictly after `window_open_date` and on or before `window_close_date`; otherwise creation is rejected with `ERR_EFFECTIVE_DATE_OUTSIDE_WINDOW`. The claim starts in `TRACKING`; the claims list accepts optional `work_id` and `status` filters, and because claim status is lazily derived (§2.5), list and read responses always reflect the current logical clock.

The claim's lifecycle is driven first by time and then by the specialist. Once the logical clock reaches `window_open_date`, a `TRACKING` claim behaves as `NOTICE_WINDOW_OPEN`. Filing the notice — a `CopyrightSpecialist` action carrying the `notice_ref` — is permitted only in that derived window: attempting it while the derived status is still `TRACKING` because the window has not opened is rejected with `ERR_TERMINATION_WINDOW_NOT_OPEN`, while attempting it after the logical clock has passed `notice_latest_date` is rejected with `ERR_NOTICE_DEADLINE_PASSED`; the filing moment must lie within the inclusive notice window from `notice_earliest_date` through `notice_latest_date`. Filing is also refused with `ERR_WORK_RIGHTS_TERMINATED` if the work's copyright is already `TERMINATED`. A successful filing stamps `notice_filed_at` from the logical clock, records `notice_ref`, and moves the claim to `NOTICE_FILED`. A claim that never reaches `NOTICE_FILED` before the logical clock passes `window_close_date` behaves as `LAPSED`.

Once filed, two endings are possible. The specialist may reject a `NOTICE_FILED` claim — a call carrying a `reason` — moving it to terminal `REJECTED`. Or, once the logical clock has reached the `intended_effective_date`, making the claim effective moves it from `NOTICE_FILED` to terminal `EFFECTIVE` — attempting it earlier is rejected with `ERR_INVALID_STATE_TRANSITION`. Effectuation is the point where rights actually revert: the work's `copyright_status` moves to `TERMINATED`, and the cascade of §3.3 fires — every SplitSet of the work still in `DRAFT`, `PENDING_CONFIRMATIONS`, or `DISPUTED` is moved to `CANCELLED`, and each of their still-`PENDING` split lines is moved to `REJECTED` with `rejection_reason` set to `WORK_RIGHTS_TERMINATED` — while the Work's `version` increments. From that point on, the terminated-work gates scattered through this document close the catalog to new split sets, split submissions, and society submissions for that work.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — lifecycle actions, state transitions, and snapshot operations — return `200 OK`, as do all reads. The table below is a summary only; request payloads, response content, and side effects are defined by the narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PublisherAdmin |
| POST | `/writers` | Create a Writer | PublisherAdmin |
| GET | `/writers` | List writers | All roles |
| GET | `/writers/{id}` | Get a Writer | All roles |
| GET | `/writers/{id}/earnings-summary` | Read a writer's computed balances | PublisherAdmin, RoyaltyAnalyst, FinanceManager, Writer |
| POST | `/writers/{id}/suspend` | Suspend a Writer (ACTIVE → SUSPENDED) | PublisherAdmin |
| POST | `/writers/{id}/reactivate` | Reactivate a Writer (SUSPENDED → ACTIVE) | PublisherAdmin |
| POST | `/works` | Create a Work (original or derivative) | PublisherAdmin |
| GET | `/works` | List works | All roles |
| GET | `/works/{id}` | Get a Work | All roles |
| POST | `/works/{id}/file-copyright` | File a copyright application (UNFILED → FILED) | CopyrightSpecialist |
| POST | `/works/{id}/register-copyright` | Record copyright-office registration (FILED → COPCO_REGISTERED) | CopyrightSpecialist |
| POST | `/societies` | Create a Society | PublisherAdmin |
| GET | `/societies/{id}` | Get a Society | All roles |
| POST | `/society-registrations` | Create a SocietyRegistration (DRAFT) | CopyrightSpecialist |
| GET | `/society-registrations` | List society registrations | All roles |
| GET | `/society-registrations/{id}` | Get a SocietyRegistration | All roles |
| POST | `/society-registrations/{id}/submit` | Submit a registration (DRAFT or REJECTED → SUBMITTED) | CopyrightSpecialist |
| POST | `/society-registrations/{id}/acknowledge` | Record society acknowledgement (SUBMITTED → ACKNOWLEDGED) | CopyrightSpecialist |
| POST | `/society-registrations/{id}/register` | Record registration (ACKNOWLEDGED → REGISTERED); may assign the work's ISWC | CopyrightSpecialist |
| POST | `/society-registrations/{id}/reject` | Record society rejection (SUBMITTED → REJECTED) | CopyrightSpecialist |
| POST | `/split-sets` | Create a SplitSet (DRAFT) with its lines | PublisherAdmin |
| GET | `/split-sets` | List split sets | All roles |
| GET | `/split-sets/{id}` | Get a SplitSet | All roles |
| POST | `/split-sets/{id}/submit` | Submit a set for confirmations (DRAFT → PENDING_CONFIRMATIONS) | PublisherAdmin |
| POST | `/split-sets/{id}/revise` | Revise a disputed set (DISPUTED → DRAFT) with fresh lines | PublisherAdmin |
| GET | `/split-lines` | List split lines | All roles |
| GET | `/split-lines/{id}` | Get a SplitLine | All roles |
| POST | `/split-lines/{id}/confirm` | Confirm a line (PENDING → CONFIRMED) | Writer, PublisherAdmin |
| POST | `/split-lines/{id}/reject` | Reject a line (PENDING → REJECTED) | Writer, PublisherAdmin |
| POST | `/sub-publishers` | Create a SubPublisher | PublisherAdmin |
| GET | `/sub-publishers/{id}` | Get a SubPublisher | All roles |
| POST | `/sub-publishers/{id}/suspend` | Suspend a SubPublisher (ACTIVE → SUSPENDED) | PublisherAdmin |
| POST | `/sub-publishers/{id}/reactivate` | Reactivate a SubPublisher (SUSPENDED → ACTIVE) | PublisherAdmin |
| POST | `/sub-publishing-agreements` | Create a SubPublishingAgreement (DRAFT) | PublisherAdmin |
| GET | `/sub-publishing-agreements` | List sub-publishing agreements | All roles |
| GET | `/sub-publishing-agreements/{id}` | Get a SubPublishingAgreement (status lazily reflects EXPIRED) | All roles |
| POST | `/sub-publishing-agreements/{id}/activate` | Activate an agreement (DRAFT → ACTIVE) | PublisherAdmin |
| POST | `/sub-publishing-agreements/{id}/terminate` | Terminate an agreement (ACTIVE → TERMINATED) | PublisherAdmin |
| POST | `/licensees` | Create a Licensee | PublisherAdmin |
| GET | `/licensees/{id}` | Get a Licensee | All roles |
| POST | `/royalty-statements` | Create a RoyaltyStatement (RECEIVED) with inline lines; optionally amends a prior statement | RoyaltyAnalyst |
| GET | `/royalty-statements` | List royalty statements | All roles |
| GET | `/royalty-statements/{id}` | Get a RoyaltyStatement | All roles |
| POST | `/royalty-statements/{id}/match` | Run the auto-match pass (RECEIVED → MATCHING_REVIEW) | RoyaltyAnalyst |
| POST | `/royalty-statements/{id}/allocate` | Compute provisional allocations (MATCHING_REVIEW → ALLOCATED) | RoyaltyAnalyst |
| POST | `/royalty-statements/{id}/finalize` | Lock allocations and apply recoupment (ALLOCATED → FINALIZED) | RoyaltyAnalyst |
| POST | `/royalty-statements/{id}/reject` | Reject a statement (RECEIVED → REJECTED) | RoyaltyAnalyst |
| GET | `/statement-lines` | List statement lines | All roles |
| GET | `/statement-lines/{id}` | Get a StatementLine | All roles |
| POST | `/statement-lines/{id}/match` | Manually match an UNMATCHED line to a REGISTERED work | RoyaltyAnalyst |
| GET | `/allocation-lines` | List allocation lines | All roles |
| GET | `/allocation-lines/{id}` | Get an AllocationLine | All roles |
| POST | `/advances` | Create an Advance (DRAFT) | PublisherAdmin |
| GET | `/advances` | List advances | All roles |
| GET | `/advances/{id}` | Get an Advance | All roles |
| POST | `/advances/{id}/approve` | Approve an advance (DRAFT → APPROVED) | FinanceManager |
| POST | `/advances/{id}/pay` | Disburse an advance (APPROVED → PAID) | FinanceManager |
| POST | `/advances/{id}/cancel` | Cancel an advance (DRAFT or APPROVED → CANCELLED) | FinanceManager |
| POST | `/distribution-runs` | Create a DistributionRun (OPEN) | RoyaltyAnalyst |
| GET | `/distribution-runs` | List distribution runs | All roles |
| GET | `/distribution-runs/{id}` | Get a DistributionRun | All roles |
| POST | `/distribution-runs/{id}/calculate` | Snapshot payouts (OPEN → CALCULATED) | RoyaltyAnalyst |
| POST | `/distribution-runs/{id}/approve` | Approve a calculated run (CALCULATED → APPROVED) | FinanceManager |
| POST | `/distribution-runs/{id}/pay` | Execute payouts (APPROVED → PAID) | FinanceManager |
| POST | `/distribution-runs/{id}/reopen` | Revert a calculated run (CALCULATED → OPEN) | RoyaltyAnalyst |
| POST | `/licensee-audits` | Create a LicenseeAudit (OPEN) | Auditor |
| GET | `/licensee-audits` | List licensee audits | All roles |
| GET | `/licensee-audits/{id}` | Get a LicenseeAudit | All roles |
| POST | `/licensee-audits/{id}/begin-fieldwork` | Begin fieldwork (OPEN → FIELDWORK) | Auditor |
| POST | `/licensee-audits/{id}/issue-findings` | Issue findings and compute the claim (FIELDWORK or UNDER_APPEAL → FINDINGS_ISSUED) | Auditor |
| POST | `/licensee-audits/{id}/appeal` | Record a licensee appeal (FINDINGS_ISSUED → UNDER_APPEAL) | Auditor |
| POST | `/licensee-audits/{id}/settle` | Settle an audit (FINDINGS_ISSUED → SETTLED) | FinanceManager |
| POST | `/licensee-audits/{id}/close` | Close an audit without findings (OPEN or FIELDWORK → CLOSED) | Auditor |
| POST | `/termination-claims` | Create a TerminationClaim (TRACKING) with projected window dates | CopyrightSpecialist |
| GET | `/termination-claims` | List termination claims (status reflects lazy clock derivation) | All roles |
| GET | `/termination-claims/{id}` | Get a TerminationClaim (status reflects lazy clock derivation) | All roles |
| POST | `/termination-claims/{id}/file-notice` | File the termination notice (NOTICE_WINDOW_OPEN → NOTICE_FILED) | CopyrightSpecialist |
| POST | `/termination-claims/{id}/make-effective` | Effectuate the termination (NOTICE_FILED → EFFECTIVE) | CopyrightSpecialist |
| POST | `/termination-claims/{id}/reject` | Reject a filed claim (NOTICE_FILED → REJECTED) | CopyrightSpecialist |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue enumerates only the identifiers and their HTTP statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_SPLIT_LINE_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_SPLIT_SUM_INVALID` | 422 Unprocessable Entity |
| `ERR_ZERO_SHARE_LINE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SPLIT_PARTICIPANT` | 422 Unprocessable Entity |
| `ERR_AUDIT_SAMPLE_BASE_INVALID` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_NO_CONFIRMED_SPLIT_SET` | 409 Conflict |
| `ERR_AMENDED_STATEMENT_NOT_FINAL` | 409 Conflict |
| `ERR_STATEMENT_ALREADY_SUPERSEDED` | 409 Conflict |
| `ERR_WORK_RIGHTS_TERMINATED` | 409 Conflict |
| `ERR_TERMINATION_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_NOTICE_DEADLINE_PASSED` | 409 Conflict |
| `ERR_EFFECTIVE_DATE_OUTSIDE_WINDOW` | 409 Conflict |
| `ERR_SUB_PUBLISHER_NOT_ACTIVE` | 409 Conflict |
| `ERR_WRITER_NOT_ACTIVE` | 409 Conflict |
| `ERR_WORK_NOT_REGISTERED` | 409 Conflict |
| `ERR_COVERAGE_OVERLAP` | 409 Conflict |
| `ERR_AUDIT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_STATEMENT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_SOCIETY_REGISTRATION` | 409 Conflict |
| `ERR_GROSS_MISMATCH` | 409 Conflict |
| `ERR_EMPTY_STATEMENT` | 409 Conflict |
| `ERR_NO_MATCHED_LINES` | 409 Conflict |
| `ERR_STALE_DISTRIBUTION_RUN` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
