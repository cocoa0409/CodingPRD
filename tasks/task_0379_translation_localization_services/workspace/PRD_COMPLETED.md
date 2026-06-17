# Translation & Localization Services API — Product Requirements Document

## 1. Introduction

This document specifies the Translation & Localization Services API, a back-office platform that carries a multilingual translation project from a first cost estimate all the way through to a settled invoice. The platform exists to remove the spreadsheet-and-email choreography that traditionally surrounds language work: a project manager analyzes source assets into translation-memory bands, the system produces a defensible word-count quote, a buyer organization approves it, linguists are matched to language pairs and committed to work windows, translated work passes through an independent quality-assurance loop, certified or notarized deliverables are attested, and the billing team issues a final invoice whose numbers are reconciled against what was actually delivered.

Three forces shape almost every rule in this specification. The first is **dual-variant pricing**: nearly every monetary figure exists once as a forward-looking estimate (computed over *quoted* word bands at quote time) and once as a final figure (computed over *actual* delivered word bands at invoice time), and the two variants deliberately diverge in both their inputs and their surcharge composition. The second is **segregation of duties**: the linguist who translates a job may never be the one who reviews it, and the billing team may never run production operations. The third is **financial consistency under compensation**: provisional linguist payouts and client receivable balances are maintained as running ledgers that must revert cleanly when assignments are superseded, jobs are cancelled, or invoices are voided. The reader should treat every state transition as potentially touching more than one entity's balance, and should expect the system itself — not the client — to drive most cross-entity state propagation.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and contract-level boilerplate that apply across the entire API. Every entity is a top-level collection; there is no URL nesting beyond a parent resource identifier (for example, the jobs of a project).

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers. Every request must include `X-User-ID` to identify the acting principal and `X-User-Role` to declare its operational capacity. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly five roles, spelled precisely as follows: `ProjectManager`, `AccountsReceivable`, `Client`, `Translator`, and `Reviewer`. When a syntactically valid request is made by a role that is not permitted to perform the operation — or by an entity-backed principal acting on a resource it does not own — the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The two operations teams use opaque identities. When `X-User-Role` is `ProjectManager`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. The same holds when `X-User-Role` is `AccountsReceivable`: `X-User-ID` is an opaque operator identifier not backed by any entity. These two roles are mutually exclusive in capability — `ProjectManager` owns production operations (creating linguists, rate cards, projects, jobs, and assignments; quoting; delivering; cancelling) while `AccountsReceivable` owns billing operations (suspending clients; creating, issuing, paying, and voiding invoices) — and neither may perform the other's exclusive operations.

The remaining three roles are entity-backed. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's client foreign key to `X-User-ID`. Concretely, a `Client` may approve a quote only on a project whose `client_id` equals `X-User-ID`, and may read only its own projects, jobs, invoices, and client record; a mismatch yields `ERR_FORBIDDEN_FOR_ROLE`. When `X-User-Role` is `Translator`, `X-User-ID` is the `id` of the acting `Linguist`; ownership checks compare the relevant `linguist_id` to `X-User-ID`. When `X-User-Role` is `Reviewer`, `X-User-ID` is likewise the `id` of the acting `Linguist`. The `Translator` and `Reviewer` roles are two operational hats worn by the same `Linguist` entity: the same person registers once as a linguist and then acts as a `Translator` on assignments where their role is translation and as a `Reviewer` where their role is review. Both may accept or decline their own assignments; a `Translator` may additionally submit a translation on a job where it is the active translator, and a `Reviewer` may additionally file a QA report on a job where it is the active reviewer.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100 — a supplied `limit` below 1 is clamped up to 1 and a supplied `limit` above 100 is clamped down to 100 rather than rejected. The `offset` parameter specifies the number of items to skip and defaults to 0; a supplied negative `offset` is clamped up to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties broken by the resource `id` in ascending order. This is the canonical ordering throughout the platform, and it carries particular significance for the linguist payout ledger and for delivery-certificate numbering, both discussed below.

Paginated and non-paginated list responses include the following fields in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every primary resource carries a system-managed `id`, formatted as a UUID with no type prefix and minted by the server. The full-lifecycle resources — `Client`, `Linguist`, `Project`, `ProjectJob`, `Assignment`, `QAReport`, `Invoice`, and `DeliveryCertificate` — additionally carry three system-managed fields: `created_at`, an ISO 8601 UTC timestamp with three fractional digits set when the resource is first created; `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation; and `version`, an integer that begins at the resource's initial value and increments by one on every mutation. The `version` field is the basis for optimistic concurrency control described in §2.8.

Two entities are deliberately leaner. A `RateCard` is immutable configuration and a `PayoutLedgerEntry` is an append-only event record; both carry only `id` and `created_at`. Neither carries `updated_at` and neither carries `version`, because neither is ever mutated after creation. The `PayoutLedgerEntry` log is replayed in `created_at` ascending order, which is its canonical and authoritative replay order.

### 2.5. Nested Resource Retrieval and Existence Ordering

When an endpoint path or request body references several resources, the server validates them left to right and front to back. Path identifiers are checked before foreign keys carried in the body, and the first identifier that does not resolve to an existing resource causes immediate rejection with `ERR_NOT_FOUND` (HTTP 404). For example, a request to list the jobs of a project rejects on the project identifier before it ever considers job-level filters, and creating an assignment that names a non-existent job rejects on the job before the linguist is examined. This existence sweep runs after authentication and authorization but before any business rule.

### 2.6. Validation Ordering

Because a single write may trip several checks at once, the platform evaluates validations in a fixed priority order, and the **first** failing check determines the rejection. The order, highest priority first, is: (1) the user-context header check, which fails with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) the role-and-ownership check, which fails with `ERR_FORBIDDEN_FOR_ROLE`; (3) the existence sweep over path and foreign-key resources, which fails with `ERR_NOT_FOUND`; (4) request-body well-formedness — required fields present, enum values legal, the work window's end strictly later than its start, and all integer counts at least zero — which fails with `ERR_INVALID_REQUEST`; (5) the state check that the target resource is in a state from which the requested transition is allowed, which fails with `ERR_INVALID_STATE`; and then the business rules in this relative order: (6) reviewer segregation of duties, failing with `ERR_SEGREGATION_VIOLATION`; (7) linguist qualification and activeness for the project's locale pair, failing with `ERR_LINGUIST_NOT_QUALIFIED`; (8) the QA-report reviewer precondition, failing with `ERR_NO_REVIEWER_ASSIGNED`; (9) the linguist daily-throughput capacity check, failing with `ERR_THROUGHPUT_EXCEEDED`; (10) the optimistic-concurrency version check, failing with `ERR_STALE_VERSION`; and (11) the invoice fiscal precondition that the project be delivered, failing with `ERR_PROJECT_NOT_DELIVERED`. The reviewer work-window collision check shares the business tier with the others and fails with `ERR_WINDOW_OVERLAP`. Where a specific workflow names other state-specific errors (such as `ERR_CLIENT_SUSPENDED`, `ERR_NO_JOBS`, `ERR_EMPTY_ANALYSIS`, `ERR_PROJECT_NOT_APPROVED`, `ERR_PROJECT_HAS_INVOICE`, `ERR_LINGUIST_INACTIVE`, or `ERR_NOT_ASSIGNED_TRANSLATOR`), those checks belong to the state-and-business tier and are described alongside the workflow they guard in §3.

### 2.7. Monetary Precision, Rounding, and the Per-Band Rounding Rule

Every monetary amount in the system is stored and returned as a whole number of cents (an integer). There are no sub-cent values anywhere in the API. Whenever a calculation produces a fractional cent it is resolved by **rounding half up** to the nearest whole cent.

One rounding convention governs every pricing computation and must be applied exactly: the platform **rounds each translation-memory band separately and then sums the rounded per-band amounts** — it never sums the raw per-band products first and rounds once at the end. This per-band-then-sum order is pinned because the two orders can disagree by a cent, and the test suite checks the pinned order. The same half-up convention with a single decimal place governs the quality-assurance score, which is the only non-cent figure in the system; it is carried to one decimal place.

### 2.8. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of a parent resource by carrying that parent's last-observed `version`. These are not optional fields.

Creating an assignment requires `expected_job_version` in the request body, carrying the `ProjectJob` version the client last read. The server compares it against the target job's current `version`; if another writer has advanced that version since the client read it — most commonly because a replacement assignment of the same role was already created on the job, which legitimately supersedes the prior one and increments the job's `version` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents the client from creating an assignment against a job whose assignment lineup it has not actually observed.

Issuing an invoice requires `expected_project_version` in the request body, carrying the `Project` version the client last read. The server compares it against the target project's current `version`; if another writer has advanced the project version since the client read it — for example because the project already cycled through an issue, or another invoice action moved its version — the issue is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints other than assignment creation and invoice issue do not take a version field and perform no concurrency check. The supplied concurrency token is retained on the written resource and echoed back: an `Assignment` carries the `expected_job_version` it was created with, and an `Invoice` carries an `expected_project_version` field that is null on a draft invoice and is set to the supplied token when the invoice is issued.

### 2.9. Ledger Consistency for Linguist Payouts

Each linguist carries a derived `committed_payout_cents` figure that must always equal the running sum of that linguist's `PayoutLedgerEntry` records, which in turn equals the sum of `payout_cents` over that linguist's assignments currently in `ACCEPTED`, `IN_PROGRESS`, or `DELIVERED`. The ledger is append-only: each entry records the `linguist_id`, the `assignment_id` whose payout it commits or reverts, an `entry_type`, a signed `amount_cents`, and a human-readable `reason`. The `entry_type` is `COMMIT` when an assignment is accepted, `REVERSAL` when an accepted or in-progress assignment is superseded or cancelled, and `FINAL_ADJUST` when a job is delivered and the translator's payout moves from its provisional to its final value. The `amount_cents` is positive for a `COMMIT` and for a positive `FINAL_ADJUST`, and negative for a `REVERSAL` and for a negative `FINAL_ADJUST`. Whenever an entry is appended, the owning linguist's `committed_payout_cents` is reconciled by the same signed amount, so the running sum and the derived field never drift apart. These reconciliations are mutations on the linguist record and therefore refresh its `updated_at` and increment its `version`.

### 2.10. Ledger Consistency for Client Receivables

Each client carries a derived `ar_balance_cents` figure equal to the sum of `total_cents` over that client's issued, non-voided invoices. When an invoice is issued, the client's `ar_balance_cents` increases by the invoice `total_cents`; when an issued invoice is paid, it decreases by `total_cents`; and when an issued invoice is voided, it likewise decreases by `total_cents`, returning the balance to its pre-issue value. A draft invoice that is voided without ever having been issued does not touch the balance. Each of these reconciliations is a mutation on the client record and refreshes its `updated_at` and increments its `version`.

### 2.11. Hierarchical State Propagation

Many state transitions in this platform are driven by the server rather than requested directly by a client, and several mutate more than one entity at once. The reader should not treat any single operation as touching only its own resource. When the first translator assignment on any of a project's jobs is accepted, the system advances both that job and its parent project. When every non-cancelled job of a project reaches its delivered state, the project is advanced to delivered without any explicit request. When a project's invoice is issued, the project is advanced to its invoiced state; when that issued invoice is later voided, the project reverts to delivered so a corrected invoice can be issued. Cancelling a project cascades into its non-terminal jobs and, through them, into the active assignments and the linguist payout ledger. Every such automatic transition is a real mutation: it refreshes the affected resource's `updated_at` and increments its `version`. The detailed preconditions and side effects of each transition live in §3 alongside the workflow they belong to.

## 3. Business Logic & Workflows

### 3.1. Foundational Records: Clients, Linguists, and Rate Cards

Before any project can exist, three kinds of reference records must be in place. A **client** is the buyer organization. Either a `ProjectManager` or an `AccountsReceivable` operator may create one by supplying its `name` and `billing_email`; on creation its `status` is `ACTIVE` and its derived `ar_balance_cents` starts at zero. Only an `AccountsReceivable` operator may suspend a client, which moves its `status` to `SUSPENDED`. A `SUSPENDED` client blocks two things: a new project cannot be created against it, and an invoice cannot be issued for it. Both rejections use `ERR_CLIENT_SUSPENDED`. A client's two enumerated statuses are `ACTIVE` and `SUSPENDED`.

A **linguist** is a person who translates and possibly reviews. Only a `ProjectManager` may register one, supplying the `full_name`, the `native_locale` (the BCP-47 locale the linguist translates into, such as de-DE), and `qualified_pairs` — an array of source-locale and target-locale pairs the linguist is allowed to work. Two further inputs are optional. The `can_review` flag declares whether the linguist may act in the reviewer capacity and defaults to false. The `daily_throughput_words` figure caps how many weighted source words the linguist may be committed to on any single UTC calendar day and defaults to 2500. On registration the linguist's `status` is `ACTIVE` and its derived `committed_payout_cents` starts at zero. Only a `ProjectManager` may deactivate a linguist, moving its `status` to `INACTIVE`; an `INACTIVE` linguist cannot accept new assignments. A linguist's two enumerated statuses are `ACTIVE` and `INACTIVE`.

A **rate card** is immutable pricing configuration for one language direction. Only a `ProjectManager` may create one, naming the `source_locale`, the `target_locale`, the `base_rate_cents_per_word` charged to the client per source word before translation-memory weighting, and the `linguist_rate_cents_per_word` paid to the translating linguist per weighted word. An `active` flag, defaulting to true, declares whether new projects may reference the card; there is one active card per source-and-target pair. Because a rate card never changes after creation, it carries only `id` and `created_at`.

### 3.2. Opening a Project and Building Its Job List

A `ProjectManager` opens a **project** against an existing client and an existing rate card, supplying the `client_id`, the `rate_card_id`, and a `name`. Two pricing levers are chosen here. The `rush_tier` selects a delivery-speed surcharge multiplier and is one of `STANDARD`, `EXPRESS`, or `SAME_DAY`, defaulting to `STANDARD`. The `certification_mode` selects the attestation add-on and is one of `NONE`, `CERTIFIED`, or `NOTARIZED`, defaulting to `NONE`. At creation the project pins the rate card's two rates into `pinned_base_rate_cents_per_word` and `pinned_linguist_rate_cents_per_word`, so later edits to the rate card never disturb a project already in flight; the project's source and target locales are likewise inherited from the rate card. If the named client is not `ACTIVE`, creation is rejected with `ERR_CLIENT_SUSPENDED`. A new project's `status` is `DRAFT` and its `quoted_total_cents` is null until it is quoted. A project moves through these enumerated states over its life: `DRAFT`, `QUOTED`, `APPROVED`, `IN_PRODUCTION`, `DELIVERED`, `INVOICED`, and `CANCELLED`.

Inside a project, a `ProjectManager` adds one or more **project jobs**, each representing a single source asset. Creating a job requires the `filename` and accepts four optional analyzed word-band counts, each defaulting to zero: `quoted_no_match_words` for fully new text, `quoted_fuzzy_words` for partial translation-memory matches in the seventy-five to ninety-nine percent range, `quoted_reps_words` for exact repetitions, and `quoted_context_words` for in-context exact matches. A new job's `status` is `PENDING`, its `revision_rounds` is zero, its `latest_qa_score` is null, its four `actual_*_words` band counts are null, and its `weighted_source_words` is null (it is first populated when the project is quoted and later recomputed from the actual bands at delivery, and is carried as a floating-point number of weighted words). Adding a job to a project that is already in `QUOTED` re-opens the estimate: the project's `quoted_total_cents` is reset to null and the project moves from `QUOTED` back to `DRAFT`, because the previously computed quote no longer reflects the work. A job moves through these enumerated states: `PENDING`, `TRANSLATING`, `IN_QA`, `REVISION`, `QA_PASSED`, `DELIVERED`, and `CANCELLED`.

### 3.3. Quoting: The Forward-Looking Estimate

When the job list is settled, a `ProjectManager` requests a quote, which drives the project from `DRAFT` to `QUOTED`. Two preconditions guard this: the project must have at least one job, otherwise the request is rejected with `ERR_NO_JOBS`; and across all jobs the quoted band-word counts must sum to more than zero, otherwise it is rejected with `ERR_EMPTY_ANALYSIS`. The quote is a forward-looking provisional estimate computed over the *quoted* band words, and it is written to `quoted_total_cents`; as a side effect each job's `weighted_source_words` is computed from its quoted bands.

The estimate is built in a pinned evaluation order, each step feeding the next. The platform first assigns every translation-memory band a pay factor: a no-match word counts as one full word; a fuzzy seventy-five-to-ninety-nine word counts as sixty-five hundredths of a word; an exact repetition counts as thirty-five hundredths of a word; and an in-context exact match counts as fifteen hundredths of a word. **Step one** computes, for each job and each of the four bands, a per-band amount equal to that band's word count multiplied by the project's pinned base rate per word and by that band's pay factor, with each per-band amount rounded half up to whole cents individually. **Step two** sets the translation subtotal to the sum, over every job and every band, of those rounded per-band amounts — recall from §2.7 that the rounding happens per band, before summing. **Step three** computes the weighted word total as the sum over all jobs of each band's word count multiplied by its pay factor, left unrounded. **Step four** selects the volume-discount fraction from that weighted word total: the discount is ten hundredths when the weighted word total is at least twenty thousand, five hundredths when it is at least five thousand but below twenty thousand, and zero otherwise; the after-discount amount is the translation subtotal multiplied by one minus the discount fraction, rounded half up to whole cents. **Step five** multiplies the after-discount amount by the rush multiplier for the project's rush tier — one for `STANDARD`, one and thirty hundredths for `EXPRESS`, and one and seventy-five hundredths for `SAME_DAY` — and rounds the result half up to whole cents. **Step six** computes the certification add-on: the total source words is the sum over all jobs of the four raw band-word counts; the page count is that total divided by two hundred fifty words per page and rounded up to the next whole page; the add-on is zero for `NONE`, the page count multiplied by five hundred cents per page for `CERTIFIED`, and the page count multiplied by five hundred cents per page plus a three-thousand-five-hundred-cent notary flat for `NOTARIZED`. **Step seven** sets `quoted_total_cents` to the after-rush amount plus the certification add-on. The estimate uses quoted bands only and includes no revision surcharge.

### 3.4. Client Approval

Once a project is `QUOTED`, the buyer reviews and approves it, advancing it from `QUOTED` to `APPROVED`. Only the owning `Client` may do this: the acting principal's `X-User-ID` must equal the project's `client_id`, and a mismatch is rejected with `ERR_FORBIDDEN_FOR_ROLE`. Approval additionally requires that the project's `quoted_total_cents` not be null — that is, that a current quote exists — otherwise the request is rejected with `ERR_INVALID_STATE`. Approval itself carries no balance or ledger side effects; it simply unlocks production.

### 3.5. Assigning Linguists: Matching, Segregation, Windows, and Throughput

A `ProjectManager` staffs a job by creating **assignments**. An assignment names the `job_id`, the `linguist_id`, the `role` (either `TRANSLATOR` or `REVIEWER`), a `window_start` and a `window_end` bounding the linguist's committed work window as ISO 8601 UTC instants, and the `expected_job_version` optimistic-concurrency token described in §2.8. The work window is half-open: `window_end` must be strictly later than `window_start`, and a body that violates this is rejected with `ERR_INVALID_REQUEST`. A newly created assignment's `status` is `OFFERED`, its `payout_finalized` flag is false, and an assignment moves through these enumerated states: `OFFERED`, `ACCEPTED`, `IN_PROGRESS`, `DELIVERED`, `DECLINED`, `SUPERSEDED`, and `CANCELLED`.

Creating an assignment performs several checks and side effects. The assigned linguist must be qualified for the project's source-and-target locale pair and must be `ACTIVE`; a linguist who does not list the pair in `qualified_pairs`, or who is inactive, is rejected with `ERR_LINGUIST_NOT_QUALIFIED`. When the new assignment's role is `REVIEWER`, the named linguist must differ from the job's active translator linguist — the reviewer's `linguist_id` may not equal the `linguist_id` of the job's non-terminal `TRANSLATOR` assignment — and a same-person reviewer assignment is rejected with `ERR_SEGREGATION_VIOLATION`. Also for a `REVIEWER` role, the new half-open window must not overlap the job's active (non-terminal) translator window: because the intervals are half-open, a reviewer window whose `window_start` exactly equals the translator window's `window_end` does **not** overlap and is allowed, while any interior intersection of the two intervals does overlap and is rejected with `ERR_WINDOW_OVERLAP`. This per-job interval-collision rule is distinct from the per-day capacity rule discussed below. As a matter of structure, creating an assignment supersedes any prior non-terminal assignment of the same role on the same job — the prior one is moved to `SUPERSEDED` — and creating the assignment increments the job's `version` by one (which is exactly what makes a stale `expected_job_version` from another writer fail with `ERR_STALE_VERSION` as described in §2.8).

A linguist accepts an offered assignment, moving it from `OFFERED` to `ACCEPTED`; the same offer may instead be declined, moving it from `OFFERED` to `DECLINED`. Both actions may be taken only by the linguist who owns the assignment — the acting `X-User-ID` must equal the assignment's `linguist_id` — and an attempt by anyone else is rejected with `ERR_FORBIDDEN_FOR_ROLE`. Acceptance carries three further preconditions: the accepting linguist's `status` must be `ACTIVE`, otherwise `ERR_LINGUIST_INACTIVE`; the parent project must be `APPROVED` or `IN_PRODUCTION`, otherwise `ERR_PROJECT_NOT_APPROVED`; and accepting must not push any shared UTC calendar day's committed weighted words over the linguist's `daily_throughput_words` cap. The throughput check sums the weighted source words the linguist is already committed to across all overlapping `ACCEPTED` and `IN_PROGRESS` windows that share a UTC day with the new window, and if adding this assignment's weighted words would exceed the daily cap on any shared day, acceptance is rejected with `ERR_THROUGHPUT_EXCEEDED`. The weighted-word contribution of any assignment — whether `TRANSLATOR` or `REVIEWER` — is the job's quoted weighted source words, so reviewer assignments count toward the daily throughput total exactly as translator assignments do even though a reviewer's `payout_cents` is zero. The set of UTC calendar days a half-open window touches spans the start date through the end date inclusive, except that a window ending exactly at 00:00:00 of a later date does not occupy that final date. When acceptance succeeds, the assignment's `payout_cents` is set to the provisional linguist payout computed over the job's quoted bands (see §3.9), a `COMMIT` ledger entry of that amount is appended, and the linguist's `committed_payout_cents` is increased by that amount. If the accepted assignment's role is `TRANSLATOR`, acceptance additionally drives the job from `PENDING` to `TRANSLATING` and — when it is the first accepted translator assignment in the project — drives the project from `APPROVED` to `IN_PRODUCTION`. The translator-into-translating transition requires the parent project to be `APPROVED` or `IN_PRODUCTION`, otherwise `ERR_PROJECT_NOT_APPROVED`, and increments the job's `version` by one. Once accepted, an assignment becomes `IN_PROGRESS` automatically as the job moves into active work.

Whenever a replacement assignment of the same role is created on a job, the prior assignment is superseded automatically. A superseded assignment that was merely `OFFERED` simply moves to `SUPERSEDED` with no ledger effect. A superseded assignment that had already been `ACCEPTED` or was `IN_PROGRESS` triggers compensation: a `REVERSAL` ledger entry equal to the negative of its `payout_cents` is appended, and the linguist's `committed_payout_cents` is decreased by that same `payout_cents`, cleanly backing out the provisional commitment.

### 3.6. Translation Submission and the QA Revision Loop

A job that has reached `TRANSLATING` is worked by its active translator, who then submits the translation, advancing the job from `TRANSLATING` to `IN_QA`. Submission may be performed only by the linguist who is the job's `ACCEPTED` or `IN_PROGRESS` translator, otherwise `ERR_NOT_ASSIGNED_TRANSLATOR`; and on this first submission out of `TRANSLATING` a reviewer must already be lined up — an `IN_PROGRESS` reviewer assignment must exist on the job — otherwise `ERR_NO_REVIEWER_ASSIGNED`. The reviewer-lined-up precondition is checked only for the first submission out of `TRANSLATING`; a revision resubmission out of `REVISION` (described below) does not re-check it. Submission increments the job's `version` by one.

Within `IN_QA`, the job's reviewer files a **QA report**, supplying the `reviewer_assignment_id` (which must name a reviewer assignment that is `IN_PROGRESS` on this job), the optional severity counts `critical_count`, `major_count`, and `minor_count` (each defaulting to zero and never negative), and a `scored_word_count`, the word base over which error density is normalized, which must be strictly greater than zero. Filing a report computes a `score` and an `outcome` (one of `PASS` or `FAIL`), as detailed in §3.10. The reviewer precondition is enforced as a single combined check failing with `ERR_NO_REVIEWER_ASSIGNED`: the named `reviewer_assignment_id` must belong to this job, carry the `REVIEWER` role, be `IN_PROGRESS`, and be owned by the acting reviewer (its `linguist_id` equals the actor's `X-User-ID`), and the acting reviewer must not also be the job's translator. A report on a job that is not `IN_QA` is instead rejected on state with `ERR_INVALID_STATE`, and a `reviewer_assignment_id` that resolves to no assignment at all is rejected during the existence sweep with `ERR_NOT_FOUND`. Filing a report sets the job's `latest_qa_score` to the report's `score` and increments the job's `version` by one. A `PASS` outcome drives the job from `IN_QA` to `QA_PASSED`; a `FAIL` outcome drives it from `IN_QA` to `REVISION`.

A job in `REVISION` is reworked by the same active translator, who submits again, advancing the job from `REVISION` back to `IN_QA`. As with the first submission, the actor must be the job's active translator (`ERR_NOT_ASSIGNED_TRANSLATOR` otherwise). A revision resubmission increments the job's `revision_rounds` by one and increments the job's `version` by one. This forms a cyclic loop — `REVISION` to `IN_QA` to `REVISION` — that repeats until a QA report finally passes and the job lands in `QA_PASSED`. The cumulative count of completed revision rounds recorded in `revision_rounds` later drives a billing surcharge described in §3.8.

### 3.7. Delivery and Certification

A `ProjectManager` delivers a passed job, advancing it from `QA_PASSED` to `DELIVERED`. The job must be in `QA_PASSED`, otherwise `ERR_INVALID_STATE`. Delivery requires the four re-analyzed actual band-word counts in the body — `actual_no_match_words`, `actual_fuzzy_words`, `actual_reps_words`, and `actual_context_words` — which capture what was truly delivered and which must sum to more than zero, otherwise `ERR_EMPTY_ANALYSIS`. Delivery records these actuals on the job and recomputes the job's `weighted_source_words` from the actual bands rather than the quoted ones.

Delivery is the moment a translator's pay is finalized. The job's translator assignment is finalized: its `payout_cents` is recomputed via the final payout variant (actual bands plus a quality adjustment, see §3.9), its `payout_finalized` flag is set to true, and its `status` is moved to `DELIVERED`. A `FINAL_ADJUST` ledger entry is appended whose `amount_cents` is the final payout minus the provisional payout — which may be negative if the final figure is lower — and the linguist's `committed_payout_cents` is reconciled by that same provisional-to-final delta. If the project's `certification_mode` is not `NONE`, delivery mints a **delivery certificate** for the job. The certificate copies the project's `certification_mode` into its own `certification_mode` (which is therefore always `CERTIFIED` or `NOTARIZED`, never `NONE`, since no certificate is minted for a `NONE` project), records the `job_id` it attests, computes a `page_count` equal to the job's actual total source words divided by two hundred fifty words per page rounded up to the next whole page, and assigns a `certificate_number`. The certificate number is sequential per project, assigned in job `created_at` ascending order among that project's certified deliveries. Delivery increments the job's `version` by one. Finally, delivery bubbles up: when every non-cancelled job in the project is `DELIVERED`, the project advances from `IN_PRODUCTION` to `DELIVERED` automatically.

### 3.8. Invoicing: The Final Reconciled Figure

Billing belongs entirely to `AccountsReceivable`. An operator first creates a draft **invoice** for a project; the new invoice's `status` is `DRAFT`, its `client_id` is copied from the project, and its `project_id` records the project it bills. Creating the draft performs no project-state precondition and runs no calculation: the six computed amount fields (`translation_subtotal_cents`, `volume_discount_cents`, `rush_surcharge_cents`, `revision_surcharge_cents`, `certification_cents`) together with `total_cents` and the `expected_project_version` field all start null and are populated only when the invoice is issued. An invoice moves through these enumerated states: `DRAFT`, `ISSUED`, `PAID`, and `VOIDED`.

Issuing an invoice advances it from `DRAFT` to `ISSUED` and is the most consequential billing action. It requires `expected_project_version` in the body, the optimistic-concurrency token described in §2.8; a mismatch with the project's current `version` is rejected with `ERR_STALE_VERSION`. Three further preconditions apply: the parent project must be `DELIVERED`, otherwise `ERR_PROJECT_NOT_DELIVERED`; and the owning client's `status` must be `ACTIVE`, otherwise `ERR_CLIENT_SUSPENDED`. Issuing runs the final-invoice calculation over all delivered jobs, populates the six computed amount fields and the `total_cents`, increases the client's `ar_balance_cents` by `total_cents`, increments the project's `version` by one, and bubbles the project up from `DELIVERED` to `INVOICED`.

The final-invoice figure is the dual variant of the quote estimate, computed on the actual delivered bands rather than the quoted ones, and it composes six stored amounts. The per-band rounding rule and the half-up convention of §2.7 apply throughout, and the band pay factors are the same as in §3.3. **First**, the `translation_subtotal_cents` is the sum over every delivered job and every band of the per-band amount (actual band word count times the pinned base rate times the band pay factor), each rounded half up to whole cents before summing. **Second**, the weighted word total is computed over the actual bands exactly as in the estimate, the volume-discount fraction is selected from it with the same boundaries (ten hundredths at a weighted total of at least twenty thousand, five hundredths at a weighted total of at least five thousand but below twenty thousand, otherwise zero), and the `volume_discount_cents` is the `translation_subtotal_cents` minus the half-up-rounded product of `translation_subtotal_cents` and one minus the discount fraction. **Third**, the after-discount amount is `translation_subtotal_cents` minus `volume_discount_cents`, and the `rush_surcharge_cents` is the half-up-rounded product of that after-discount amount and the rush multiplier (one for `STANDARD`, one and thirty hundredths for `EXPRESS`, one and seventy-five hundredths for `SAME_DAY`), minus the after-discount amount. **Fourth**, the `revision_surcharge_cents` is the sum over jobs of a per-job revision surcharge; for one job, the chargeable rounds is the job's `revision_rounds` minus the one free revision round allowed, floored at zero (so a job with zero or one revision rounds owes nothing), and the per-job surcharge is the half-up-rounded product of that job's translation subtotal, the revision surcharge rate of eight hundredths, and the chargeable round count. **Fifth**, the `certification_cents` is computed from the project's actual total source words and its `certification_mode` exactly as the certification add-on was computed in the estimate: zero for `NONE`, page count times five hundred cents for `CERTIFIED`, and page count times five hundred cents plus the three-thousand-five-hundred-cent notary flat for `NOTARIZED`, where the page count is the actual total source words divided by two hundred fifty words per page rounded up. **Sixth**, the `total_cents` is the after-discount amount plus `rush_surcharge_cents` plus `revision_surcharge_cents` plus `certification_cents`. The decisive difference from the quote estimate is twofold: the final figure reads actual bands instead of quoted bands, and it inserts the revision surcharge between the rush surcharge and the certification add-on — a charge the quote estimate omits entirely.

An issued invoice is later marked paid, advancing it from `ISSUED` to `PAID`; the invoice must be `ISSUED`, otherwise `ERR_INVALID_STATE`, and payment decreases the client's `ar_balance_cents` by `total_cents`. An issued invoice may instead be voided, advancing it from `ISSUED` to `VOIDED`; the invoice must be `ISSUED` and not yet `PAID`, otherwise `ERR_INVALID_STATE`. Voiding an issued invoice is a compensation: it decreases the client's `ar_balance_cents` by `total_cents`, restoring the pre-issue balance, and reverts the project from `INVOICED` back to `DELIVERED` so that a corrected invoice can be issued. A draft invoice may also be voided directly, advancing it from `DRAFT` to `VOIDED` with no balance or project effect.

### 3.9. Linguist Payout: Provisional at Accept, Final at Delivery

A translating linguist's pay is computed once provisionally and once finally, both from the same skeleton. The weighted words for a job is the sum over its bands of each band's word count multiplied by its pay factor (one for no-match, sixty-five hundredths for fuzzy, thirty-five hundredths for repetitions, fifteen hundredths for in-context). The base payout is the weighted words multiplied by the project's `pinned_linguist_rate_cents_per_word`, rounded half up to whole cents. The **provisional** variant, applied when an assignment is accepted, uses the job's quoted bands and applies no quality adjustment; the resulting `payout_cents` is committed to the linguist's `committed_payout_cents` via the `COMMIT` ledger entry described in §3.5. The **final** variant, applied at job delivery, recomputes the base over the actual bands and then applies a quality adjustment keyed on the job's `latest_qa_score`: if the latest QA score is at least ninety-five, a bonus of the base multiplied by five hundredths (rounded half up) is added; if the latest QA score is below eighty, a penalty of the base multiplied by ten hundredths (rounded half up) is subtracted; and if the score falls at eighty or above but below ninety-five, no adjustment is made. The final `payout_cents` is the base plus that adjustment. Reviewer assignments are never metered through this calculation; a reviewer assignment carries a `payout_cents` of zero.

### 3.10. QA Scoring

When a QA report is filed, its `score` is computed as follows. The weighted error count is the `critical_count` multiplied by ten, plus the `major_count` multiplied by five, plus the `minor_count` multiplied by one. The penalty is the weighted error count divided by the `scored_word_count`, then multiplied by one thousand, expressing errors per thousand words. The `score` is one hundred minus that penalty, rounded half up to one decimal place; if the result is negative it is floored at zero point zero. The `outcome` is `PASS` when the score is at least ninety, and `FAIL` otherwise. This pass threshold of ninety is what separates the `QA_PASSED` branch from the `REVISION` branch of the job state machine in §3.6, and the resulting `score` is what is stored as the job's `latest_qa_score` and later consulted by the final payout's quality adjustment in §3.9.

### 3.11. Cancellation and Cascade

A `ProjectManager` may cancel a project, moving it to `CANCELLED`, the project's only terminal state. Cancellation is permitted only while the project is in `DRAFT`, `QUOTED`, `APPROVED`, or `IN_PRODUCTION`; a cancel request against a project already in `DELIVERED`, `INVOICED`, or `CANCELLED` is rejected on state with `ERR_INVALID_STATE`. Cancellation is unconditional while the project is `DRAFT` or `QUOTED`. Once the project is `APPROVED` or `IN_PRODUCTION`, cancellation is blocked if an invoice in `ISSUED` or `PAID` exists for the project, in which case it is rejected with `ERR_PROJECT_HAS_INVOICE`. In every permitted case, cancelling a project cascade-cancels all of its jobs that are not already terminal — that is, every job not already in `DELIVERED` or `CANCELLED`. Each cascade-cancelled job moves to `CANCELLED`: a job in `PENDING` simply terminates with no further effect, while a job in any of the active working states `TRANSLATING`, `REVISION`, `IN_QA`, or `QA_PASSED` additionally cancels its active (non-terminal) assignments and reverts the affected linguists' `committed_payout_cents`. Cancelling an active `ACCEPTED` or `IN_PROGRESS` assignment in this cascade appends a `REVERSAL` ledger entry equal to the negative of its `payout_cents` and decreases the owning linguist's `committed_payout_cents` by that amount, so no linguist remains committed to work that will never happen.

### 3.12. Reading Back the Record

Every entity is independently readable, and several reverse-lookup lists let operators trace the graph. A project's jobs, a project's invoices, a job's assignments, a job's QA reports, and a job's certificate are all listable from their parent; a linguist's assignments and a linguist's payout-ledger entries are listable from the linguist; and an assignment's payout-ledger entries and an assignment's QA reports are listable from the assignment. Several of these accept narrowing filters: assignment lists accept a `status` filter, and a job's assignment list also accepts a `role` filter; job lists, invoice lists, and project lists accept a `status` filter; the project list also accepts `client_id` and `rate_card_id` filters; the global invoice list accepts `client_id`, `project_id`, and `status` filters; a job's QA-report list accepts an `outcome` filter; a linguist's payout-ledger list accepts an `entry_type` filter. A linguist's assignment list accepts a `status` filter as well. Reads respect ownership: an entity-backed `Client` sees only its own projects, jobs, invoices, and client record, and a `Translator` or `Reviewer` sees only its own linguist record, assignments, jobs, and QA reports. The delivery certificate's `certificate_number` and the payout ledger's `created_at` ascending replay order, described earlier, are the two orderings that carry business meaning beyond mere convenience.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including all state-transition actions and all reads — return `200 OK`. All endpoints require the `X-User-ID` and `X-User-Role` headers described in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clients` | Create a Client | ProjectManager, AccountsReceivable |
| GET | `/clients/{id}` | Get a Client | ProjectManager, AccountsReceivable, Client |
| POST | `/clients/{id}/suspend` | Suspend a Client | AccountsReceivable |
| POST | `/linguists` | Register a Linguist | ProjectManager |
| GET | `/linguists/{id}` | Get a Linguist | ProjectManager, AccountsReceivable, Translator, Reviewer |
| POST | `/linguists/{id}/deactivate` | Deactivate a Linguist | ProjectManager |
| GET | `/linguists/{id}/assignments` | List a Linguist's Assignments | ProjectManager, Translator, Reviewer |
| GET | `/linguists/{id}/payout-ledger` | List a Linguist's PayoutLedgerEntries | ProjectManager, Translator, Reviewer |
| POST | `/rate-cards` | Create a RateCard | ProjectManager |
| GET | `/rate-cards/{id}` | Get a RateCard | ProjectManager, AccountsReceivable |
| POST | `/projects` | Create a Project | ProjectManager |
| GET | `/projects/{id}` | Get a Project | ProjectManager, AccountsReceivable, Client |
| GET | `/projects` | List Projects | ProjectManager, AccountsReceivable |
| POST | `/projects/{id}/quote` | Compute the provisional quote | ProjectManager |
| POST | `/projects/{id}/approve` | Client approves the quote | Client |
| POST | `/projects/{id}/cancel` | Cancel a Project | ProjectManager |
| POST | `/projects/{id}/jobs` | Add a ProjectJob to a project | ProjectManager |
| GET | `/projects/{id}/jobs` | List jobs of a project | ProjectManager, AccountsReceivable, Client |
| GET | `/jobs/{id}` | Get a ProjectJob | ProjectManager, AccountsReceivable, Translator, Reviewer, Client |
| POST | `/jobs/{id}/submit-translation` | Translator submits translation | Translator |
| POST | `/jobs/{id}/deliver` | Deliver a passed job | ProjectManager |
| GET | `/jobs/{id}/certificate` | List the DeliveryCertificate(s) for a job | ProjectManager, AccountsReceivable, Client |
| POST | `/assignments` | Create an Assignment | ProjectManager |
| GET | `/assignments/{id}` | Get an Assignment | ProjectManager, Translator, Reviewer |
| GET | `/jobs/{id}/assignments` | List Assignments for a job | ProjectManager, Translator, Reviewer |
| GET | `/assignments/{id}/payout-ledger` | List PayoutLedgerEntries for an Assignment | ProjectManager, Translator, Reviewer |
| POST | `/assignments/{id}/accept` | Linguist accepts an assignment | Translator, Reviewer |
| POST | `/assignments/{id}/decline` | Linguist declines an assignment | Translator, Reviewer |
| POST | `/jobs/{id}/qa-reports` | Reviewer files a QA report | Reviewer |
| GET | `/qa-reports/{id}` | Get a QAReport | ProjectManager, Reviewer, Translator |
| GET | `/jobs/{id}/qa-reports` | List QA reports for a job | ProjectManager, Reviewer, Translator |
| GET | `/assignments/{id}/qa-reports` | List QA reports under a reviewer Assignment | ProjectManager, Reviewer |
| POST | `/projects/{id}/invoices` | Create a draft Invoice for a project | AccountsReceivable |
| GET | `/invoices/{id}` | Get an Invoice | ProjectManager, AccountsReceivable, Client |
| GET | `/projects/{id}/invoices` | List Invoices for a project | ProjectManager, AccountsReceivable, Client |
| GET | `/invoices` | List Invoices | ProjectManager, AccountsReceivable |
| POST | `/invoices/{id}/issue` | Issue an Invoice | AccountsReceivable |
| POST | `/invoices/{id}/pay` | Mark an Invoice paid | AccountsReceivable |
| POST | `/invoices/{id}/void` | Void an Invoice | AccountsReceivable |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CLIENT_SUSPENDED` | 409 |
| `ERR_NO_JOBS` | 409 |
| `ERR_EMPTY_ANALYSIS` | 409 |
| `ERR_PROJECT_NOT_APPROVED` | 409 |
| `ERR_PROJECT_NOT_DELIVERED` | 409 |
| `ERR_PROJECT_HAS_INVOICE` | 409 |
| `ERR_LINGUIST_INACTIVE` | 409 |
| `ERR_LINGUIST_NOT_QUALIFIED` | 409 |
| `ERR_SEGREGATION_VIOLATION` | 409 |
| `ERR_NO_REVIEWER_ASSIGNED` | 409 |
| `ERR_NOT_ASSIGNED_TRANSLATOR` | 409 |
| `ERR_THROUGHPUT_EXCEEDED` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_STALE_VERSION` | 412 |
