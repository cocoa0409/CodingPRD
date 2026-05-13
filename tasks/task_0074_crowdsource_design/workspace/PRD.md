# Crowdsource Design API — Product Requirements Document

## 1. Introduction

This document describes the requirements for the Crowdsource Design platform — a competition marketplace where a sponsoring client publishes a paid creative brief, qualified designers submit original work, an anonymized review panel scores entries through multiple rounds, and the winning submissions are awarded prizes whose copyrights are formally transferred to the client. The platform sits between four very different parties — a Client funding the work, a Designer producing it, a Reviewer judging it, and a PlatformOps operator coordinating the process — and the safety, fairness, and fiscal correctness guarantees the system makes only hold if those four parties never accidentally see each other's information, never act out of turn, and never spend money before the matching copyright clears.

The lifecycle is intentionally long. A project begins as a private draft, passes a platform integrity check, opens for submissions, runs through preliminary, semifinal, and final review rounds with anti-plagiarism cross-checking and dispute mediation woven through, and then settles into copyright registration and prize payment. Time, anonymity, and money are all first-class resources: every stage has a hard window, every reviewer sees every designer through an alias until the project is decided, and every cent of withholding tax is recomputed from the winner's residency at the moment the panel chooses them. Most operations are driven by `PlatformOps`, but several pivotal acts — the original-work declaration on a submission, the next-in-order signature on a copyright transfer, the fairness dispute against a reviewer score — must come from precisely one of the other three roles, and the API enforces that mapping rigorously.

The remainder of this document specifies the global response and authorization contract, the business workflows in narrative form, the endpoint catalog, and the error code reference.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The system recognizes four roles: `PlatformOps`, `Client`, `Designer`, and `Reviewer`. A request missing either header is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not permitted to call the targeted endpoint is rejected with `ERR_FORBIDDEN`.

The four roles bind `X-User-ID` to identity in different ways. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's `client_id` to `X-User-ID`. When `X-User-Role` is `Designer`, `X-User-ID` is the `id` of the acting `Designer`; ownership checks on any resource that references a `Designer` compare the resource's `designer_id` to `X-User-ID`. When `X-User-Role` is `Reviewer`, `X-User-ID` is the `reviewer_id` of the acting member of the reviewer pool; assignment-ownership checks compare the `ReviewAssignment.reviewer_id` to `X-User-ID`. When `X-User-Role` is `PlatformOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `actor_id` on `AuditEvent` whose `actor_kind` is `PLATFORM`) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned and defaults to 10; the minimum accepted value is 1 and the maximum is 100. The `offset` parameter is the number of leading items to skip and defaults to 0. Unless an endpoint description states otherwise, list results are sorted by the resource's `created_at` field in ascending order. The `meta` block on a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system — `Client`, `Designer`, `Project`, `ReviewStage`, `Submission`, `ReviewAssignment`, `Dispute`, `CopyrightTransfer`, `PrizeTier`, and `PrizePayment` — share four system-managed fields:

- `id` is a server-minted UUID with no type prefix.
- `created_at` is an ISO 8601 UTC timestamp with three fractional digits, written once at creation time.
- `updated_at` is an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource (including state transitions, ledger updates, and cascades originating from a parent).
- `version` is an integer that starts at 1 on creation and is incremented by exactly one on every mutation of the resource. Cascaded mutations to a resource — such as `Submission.status` flipping to `ELIMINATED` when a parent stage publishes — increment the affected resource's own `version` and refresh its own `updated_at`.

Three reference catalog entities — `DesignCategory`, `ReviewerPool`, and `AuditEvent` — carry only `id` and `created_at`. They have no `updated_at` and no `version` field; in particular, an `AuditEvent` is append-only and is never amended after it is written.

### 2.5. Optimistic Concurrency Control

Any `PATCH` request and any state-transition action endpoint accepts an optional `version` field in its request body. When `version` is supplied, the server compares it against the current value of the targeted entity's `version` and rejects a mismatch with `ERR_VERSION_CONFLICT`. When `version` is omitted, the server applies the change without a concurrency check. The check uses strict equality on the integer.

### 2.6. Numerical Precision and Monetary Representation

All currency-denominated fields — `prize_pool_cents`, `PrizeTier.gross_amount_cents`, `PrizePayment.gross_amount_cents`, `withholding_cents`, and `net_amount_cents` — are stored and exchanged as non-negative integers in the minor currency unit (cents). Currency arithmetic is performed in integer cents end-to-end; the prize-withholding rule rounds half up after each tier multiplication and then sums the rounded tier amounts.

Scoring fields are decimal numbers carried with two decimal places. `originality_score`, every `aggregated_score` on a `ReviewAssignment`, every value inside `Submission.aggregate_score_by_stage`, and `ReviewStage.passing_threshold` are all real numbers on the closed interval from 0 to 100 with two fractional digits. Whenever the system reduces a quantity to two decimal places, the rounding method is round half up.

### 2.7. Nested Resource Retrieval

Many paths embed multiple identifiers — for example, a project's review stages, a project's submissions, or a project's prize tiers. The server validates path identifiers strictly left to right. The first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` immediately, before any downstream identifier or body field is inspected. The same rule applies to foreign-key fields inside request bodies: a body referring to a non-existent `client_id`, `project_id`, `designer_id`, `submission_id`, `prize_tier_id`, `review_stage_id`, or `reviewer_id` is rejected with `ERR_FK_NOT_FOUND` (which carries a 404 status, distinguishing it from path-level miss). The same left-to-right rule governs URL path variables that target a single nested resource — `review_assignment_id` for an assignment, `transfer_id` for a copyright transfer, `prize_payment_id` for a payment, and `dispute_id` for a dispute — each resolved against its owning resource before any other body or query parameter is consulted.

### 2.8. Cascading State Propagation and Audit Trail

Many transitions in this domain mutate more than the targeted entity. Whenever a parent transition triggers a child state change, the system writes the child mutation, refreshes the child's `updated_at`, and increments the child's `version`. A parent's `version` and `updated_at` are likewise refreshed when its own state moves, including the moves driven by automatic time-gated cascades discussed below. Every audited transition emits an `AuditEvent` row whose `occurred_at` is the server clock at the moment of commit, whose `actor_kind` is one of `CLIENT`, `DESIGNER`, `REVIEWER`, `PLATFORM`, or `SYSTEM`, whose `actor_id` records the acting user (or is set by the server for `SYSTEM`-driven cascades), and whose `subject_kind` and `subject_id` identify the entity acted upon. The `payload` field carries action-specific structured context, typically the previous and new `status` values.

### 2.9. Validation Priority

Endpoints apply validation rules in a fixed precedence so that the error a client sees first reflects the most fundamental failure. Authentication is checked first: a missing `X-User-ID` or `X-User-Role` short-circuits with `ERR_UNAUTHENTICATED`. Authorization is checked next, surfacing `ERR_FORBIDDEN` when the role is not permitted. Path existence is checked third, yielding `ERR_NOT_FOUND`. Foreign-key existence inside the request body is checked fourth, yielding `ERR_FK_NOT_FOUND`. State-machine source-state validity is checked fifth, yielding `ERR_INVALID_STATE`. Business-safety, temporal, constraint, referential, and fiscal rules are evaluated after all of the above, in the order their identifiers appear in §5 — for example, on the project submit-for-review action, the prize-pool sum check (`ERR_PRIZE_POOL_MISMATCH`) is evaluated after timeline checks (`ERR_TIMELINE_TOO_TIGHT`) and stage-overlap checks (`ERR_STAGE_OVERLAP`). The optimistic concurrency check (`ERR_VERSION_CONFLICT`) is evaluated only after auth, role, existence, and source-state pass, and is the last gate before mutation.

### 2.10. Anonymity Regime

Until the moment a project transitions to `AWARDED`, every reviewer's view of a submission is anonymized. Server-side reads of a `ReviewAssignment` by a `Reviewer` or by a `Client` return the `anonymized_alias` minted at assignment time, and the underlying `designer_id` on the `Submission` is redacted (returned as null) for those roles. When the project transitions to `AWARDED`, `Project.anonymity_unmasked_at` is set to the server clock and subsequent reads return the true `designer_id`. The `PlatformOps` role sees identities at all times because it is operationally accountable for assignment and dispute handling.

### 2.11. Virtual Clock and External Event Driver

The platform operates against a virtual server clock that is moved exclusively by an administrative test-driving capability. Advancing the clock to a future instant may cross time-gated thresholds and trigger cascades — most notably the `Project` lifecycle's automatic move out of the open submission window. External integrations (payment gateway, electronic-signature provider, copyright authority) are also driven through a single inbound-event endpoint: callers supply an `event_type`, the `subject_id` of the target resource, and an optional `payload`, and the server applies the corresponding state transition.

### 2.12. Enumerated Vocabularies

For unambiguous matching across requests, the following enumerations are fixed:

- `Client.status`: `ACTIVE`, `SUSPENDED`.
- `Client.tax_jurisdiction`: `RESIDENT`, `NON_RESIDENT`.
- `Designer.qualification_level`: `NOVICE`, `JUNIOR`, `SENIOR`, `EXPERT`.
- `Designer.tax_residency`: `RESIDENT`, `NON_RESIDENT`.
- `Designer.status`: `ACTIVE`, `SUSPENDED`, `BANNED`.
- `Project.status`: `DRAFT`, `UNDER_PLATFORM_REVIEW`, `ON_SHELF`, `IN_PRELIMINARY`, `IN_SEMIFINAL`, `IN_FINAL`, `AWARDED`, `CLOSED`, `REJECTED`, `CANCELLED`.
- `ReviewStage.stage_kind`: `PRELIMINARY`, `SEMIFINAL`, `FINAL`.
- `ReviewStage.status`: `PENDING`, `OPEN`, `AGGREGATING`, `PUBLISHED`, `EXPIRED`.
- `Submission.status`: `DRAFT`, `SCREENING`, `SCREEN_REJECTED`, `ACCEPTED`, `ADVANCING_SEMIFINAL`, `ADVANCING_FINAL`, `WINNER`, `RUNNER_UP`, `ELIMINATED`, `WITHDRAWN`.
- `Submission.originality_variant`: `PRELIMINARY_SCAN`, `FINAL_CROSSCHECK`.
- `ReviewAssignment.status`: `PENDING`, `SUBMITTED`, `DISPUTED`, `VOIDED`.
- `Dispute.dispute_type`: `PLAGIARISM`, `SCORING_FAIRNESS`, `COPYRIGHT`, `PAYMENT`.
- `Dispute.subject_ref_kind`: `SUBMISSION`, `REVIEW_ASSIGNMENT`, `COPYRIGHT_TRANSFER`, `PRIZE_PAYMENT`.
- `Dispute.filer_kind`: `CLIENT`, `DESIGNER`, `REVIEWER`, `PLATFORM`.
- `Dispute.status`: `FILED`, `MEDIATING_STAGE1`, `MEDIATING_STAGE2`, `ARBITRATION`, `RESOLVED_UPHELD`, `RESOLVED_REJECTED`, `WITHDRAWN`.
- `CopyrightTransfer.scope`: `FULL`, `LIMITED`.
- `CopyrightTransfer.status`: `DRAFTED`, `PENDING_SIGNATURES`, `ALL_SIGNED`, `REGISTERING`, `REGISTERED`, `VOIDED`.
- `PrizeTier.tier_kind`: `MAIN`, `CONSOLATION`.
- `PrizePayment.status`: `SCHEDULED`, `PAYING`, `PAID`, `FAILED`, `REVERSED`.
- `AuditEvent.action_kind`: `REVIEW_SUBMITTED`, `REVIEW_VOIDED`, `REVIEW_DISPUTED`, `STAGE_PUBLISHED`, `COPYRIGHT_DRAFTED`, `COPYRIGHT_SIGNED`, `COPYRIGHT_REGISTERED`, `COPYRIGHT_VOIDED`, `DISPUTE_FILED`, `DISPUTE_RESOLVED`, `PRIZE_PAID`.
- `AuditEvent.actor_kind`: `CLIENT`, `DESIGNER`, `REVIEWER`, `PLATFORM`, `SYSTEM`.
- `AuditEvent.subject_kind`: `SUBMISSION`, `REVIEW_ASSIGNMENT`, `REVIEW_STAGE`, `COPYRIGHT_TRANSFER`, `DISPUTE`, `PRIZE_PAYMENT`.

## 3. Business Logic & Workflows

### 3.1. Catalog Setup and Party Registration

Before any project can be configured, `PlatformOps` populates the `DesignCategory` catalog. Each category carries a stable uppercase `code` (with only A–Z letters and underscores, unique across the catalog), a human-readable `name`, and a `similarity_corpus_id` that identifies the public-image corpus the platform's preliminary plagiarism scan compares submissions against.

Clients are registered by `PlatformOps` with `company_name` (1 to 200 characters), `contact_email` validated as an RFC 5322 address, and `tax_jurisdiction` set to either `RESIDENT` or `NON_RESIDENT`. A new client's `status` is `ACTIVE` by default. Designers are likewise registered by `PlatformOps`, with `display_name` (1 to 80 characters, unique across all designers), `qualification_level` (defaulting to `NOVICE`), a `categories` array drawn as a non-empty subset of the `DesignCategory.code` set, and `tax_residency` (`RESIDENT` or `NON_RESIDENT`). A new designer's `status` is `ACTIVE` and their `trust_score` starts at 100. Reviewers are added to the platform's reviewer pool with a unique opaque `reviewer_id`, a display `name`, the `categories` they are qualified to score, an integer `max_concurrent_assignments` (1 to 100, default 20), and an optional `conflict_designer_ids` list — the designers whose work this reviewer must never see — defaulting to an empty list.

### 3.2. Project Authoring and Platform Vetting

A `Client` authors a project as a draft. The request carries the owning `client_id`, the `category_code` from the catalog, a `title` (1 to 200 characters), a `brief` (1 to 5000 characters), `reference_material_urls` (0 to 20 entries, each a valid HTTPS URL), the `prize_pool_cents` budget, the timeline triple — `opens_at`, `submission_deadline`, `final_decision_deadline` — and two optional governance knobs: `max_submissions_per_designer` (1 to 10, default 3) and `client_participates_final` (default false). The project is created in `DRAFT` and its `published_winner_list` is initially the empty array. Two timeline checks fire immediately on the create call and again on any later modification: `submission_deadline` must be no earlier than 72 hours after `opens_at`, and `final_decision_deadline` must be no earlier than 168 hours (seven full days) after `submission_deadline`. A request that fails either bound is rejected with `ERR_TIMELINE_TOO_TIGHT`.

While the project is in `DRAFT`, the client configures one or more prize tiers and exactly three review stages. Each `PrizeTier` carries an integer `rank` of at least 1 (unique within the project), a `gross_amount_cents` of at least 0, and a `tier_kind` of either `MAIN` or `CONSOLATION`. A request that creates a project with `prize_pool_cents` below 100,000 cents (i.e., below 1,000.00 in major units), or a `gross_amount_cents` below 0 on any tier, is rejected with `ERR_PRIZE_AMOUNT_INVALID`. Each `ReviewStage` is created for one of the three values of `stage_kind` (`PRELIMINARY`, `SEMIFINAL`, `FINAL`) and carries a `passing_threshold` in the range 0.00 to 100.00, a `reviewer_quorum` of at least 3, a `rubric` mapping each criterion code to a non-negative weight, and the stage window pair `starts_at` and `ends_at`. The `rubric` must contain between 1 and 8 criteria whose weights sum to exactly 100; any departure is rejected with `ERR_RUBRIC_WEIGHTS_INVALID`. The three stages on a project must form a strictly ordered, non-overlapping sequence: the preliminary stage's `ends_at` must be no later than the semifinal stage's `starts_at`, and the semifinal stage's `ends_at` must be no later than the final stage's `starts_at`. A violation surfaces `ERR_STAGE_OVERLAP`.

When the client is ready, they submit the project for platform review, advancing `Project.status` from `DRAFT` to `UNDER_PLATFORM_REVIEW`. Five preconditions are enforced together: the sum of `PrizeTier.gross_amount_cents` across the project's tiers must equal `prize_pool_cents` exactly (otherwise `ERR_PRIZE_POOL_MISMATCH`); the project must include at least one `MAIN` `PrizeTier` whose `rank` is 1; the timeline must satisfy the 72-hour and 168-hour gaps; and exactly the three review stages (`PRELIMINARY`, `SEMIFINAL`, `FINAL`) must exist with `starts_at < ends_at` on each.

A `PlatformOps` operator either approves the project, moving it from `UNDER_PLATFORM_REVIEW` to `ON_SHELF`, or rejects it, sending it to the terminal `REJECTED` state. Approval is permitted only while the virtual clock is still before `opens_at`; the approval transition also sets the `PRELIMINARY` `ReviewStage.status` to `PENDING` (the stage is not yet `PUBLISHED`, so no `AuditEvent` with `action_kind` of `STAGE_PUBLISHED` is emitted at this point). A rejection takes a `reason` string and has no further side effects. Both endpoints respect optimistic concurrency via the optional `version` body field.

### 3.3. Submission Window and Plagiarism Screening

While a project is `ON_SHELF`, designers create submissions. Each submission carries `designer_id` (which must match `X-User-ID` for the `Designer` role), `title` (1 to 120 characters), `asset_urls` (1 to 10 HTTPS URLs), and `original_work_declared`, which must be true on creation; a missing or false declaration is rejected with `ERR_ORIGINAL_DECLARATION_REQUIRED`. The submission is created in `DRAFT`. Before saving, the platform also checks that the count of the designer's existing non-`WITHDRAWN` submissions on this project is strictly less than `Project.max_submissions_per_designer`; an over-cap attempt is rejected with `ERR_SUBMISSION_LIMIT_REACHED`. If two designers race two creates that would together exceed the cap, exactly one wins on a first-writer-wins serialization of the per-`(project_id, designer_id)` count, and the loser receives `ERR_SUBMISSION_LIMIT_REACHED`.

A designer may modify or withdraw their own submission while the modify window is still open. The modify window closes at `modify_window_closes_at`, which the server fixes to the minimum of `Project.submission_deadline` and the `PRELIMINARY` `ReviewStage.starts_at`. A modification or deletion attempted at or after that instant is rejected with `ERR_MODIFY_WINDOW_CLOSED`. Withdrawal moves the submission from `DRAFT` to the terminal `WITHDRAWN` state. Both modify and withdraw accept an optional `version` body field.

When the virtual server clock crosses the project's `submission_deadline`, the project automatically advances from `ON_SHELF` to `IN_PRELIMINARY`. The advance is also reachable through an explicit `PlatformOps` action against the project. Both forms require the clock to have reached the `submission_deadline` and the `PRELIMINARY` stage's `starts_at` to have arrived. The transition cascades three side effects: every `Submission` of this project still in `DRAFT` transitions to `SCREENING`; each affected `Submission` has its `modify_window_closes_at` fixed to the current instant; and the `PRELIMINARY` `ReviewStage.status` becomes `OPEN`.

Entering `SCREENING` invokes the preliminary anti-plagiarism scan. The submission's `originality_score` is computed as one minus the maximum similarity between the submission's `asset_urls` and the public-image corpus identified by the project category's `similarity_corpus_id`, multiplied by 100 and rounded half up to two decimal places; `originality_variant` is set to `PRELIMINARY_SCAN`. The submission's recomputed score is then folded into the owning `Designer.trust_score` (which is itself maintained on the 0 to 100 scale to two decimal places). On scan completion, a `SCREENING` submission whose `originality_score` is at least the preliminary-originality floor advances to `ACCEPTED`; a submission whose `originality_score` is strictly below the floor moves to the terminal `SCREEN_REJECTED` state. The preliminary-originality floor is 60.00. A `SCREEN_REJECTED` outcome also decrements the designer's `trust_score` by the trust-penalty-on-reject, and a `REVIEW_VOIDED` `AuditEvent` is emitted for any prior reviewer assignments on the submission.

### 3.4. Reviewer Assignment, Scoring, and Anonymity

Once the `PRELIMINARY` stage is `OPEN`, `PlatformOps` assigns reviewers from the reviewer pool to the screened submissions of this project. An assignment carries the `review_stage_id`, the `submission_id`, and the `reviewer_id`. Before the assignment is created, two business-safety rules fire: the reviewer must be qualified for the project — that is, the reviewer's `categories` must include the project's `category_code`, otherwise `ERR_REVIEWER_NOT_QUALIFIED` — and the reviewer must not be in conflict of interest with the designer behind the submission. Conflict means the designer's `Designer.id` appears in that reviewer's `conflict_designer_ids`; a violation surfaces `ERR_REVIEWER_CONFLICT_OF_INTEREST`. The reviewer also cannot be overcommitted: the reviewer's current count of `PENDING` assignments across all stages must not exceed their `max_concurrent_assignments` cap, otherwise `ERR_REVIEWER_CAPACITY_EXCEEDED`. When two assignments race that would place the same reviewer on the same submission within the same stage, exactly one wins on the uniqueness constraint over `(review_stage_id, submission_id, reviewer_id)`, and the loser receives `ERR_REVIEWER_ALREADY_ASSIGNED`.

Every `ReviewAssignment` is created in `PENDING` and is minted with an `anonymized_alias` — a server-generated short string that the reviewer sees in place of the designer's identity until the project is awarded. The reviewer scores the submission by supplying `criterion_scores`, a map from criterion code to a numeric score on the 0 to 100 scale, and the assignment moves from `PENDING` to `SUBMITTED`. Four preconditions guard the transition: the virtual clock must still be strictly before the stage's `ends_at` (otherwise `ERR_REVIEW_WINDOW_CLOSED`); the submitted keys of `criterion_scores` must equal the keys of the stage's `rubric` exactly and every score must fall within 0 to 100 (otherwise `ERR_CRITERION_SCORES_INVALID`); the conflict-of-interest check is re-evaluated at submission time as well; and the assignment must currently be `PENDING`. The assignment's `aggregated_score` is computed by the scoring formula described in §3.5, the assignment's `submitted_at` is stamped, and an `AuditEvent` with `action_kind` of `REVIEW_SUBMITTED` is appended.

`PlatformOps` can void a `PENDING` assignment — for example, when a conflict surfaces only after assignment — by transitioning it to the terminal `VOIDED` state. Voiding is allowed only while the stage is `OPEN` or `AGGREGATING`. The void records an optional `reason` and emits a `REVIEW_VOIDED` `AuditEvent`. The endpoint accepts an optional `version` for concurrency control.

### 3.5. Scoring Aggregation and Stage Publication

The score aggregation runs in two phases. The first phase is per-assignment, fired the moment an assignment transitions from `PENDING` to `SUBMITTED`. The rounding order is strictly pinned: each incoming criterion score in `criterion_scores` is first rounded half up to two decimal places (input pre-rounding); each pre-rounded score is then multiplied by the corresponding weight from the stage's `rubric` divided by 100; the resulting products are summed at full precision (no per-criterion product rounding); and the final sum is rounded half up to two decimal places to produce `aggregated_score`. Because rubric weights are constrained to sum to exactly 100, the result lies on the 0 to 100 scale.

The second phase is per-submission, fired when `PlatformOps` moves the stage from `OPEN` to `AGGREGATING`. The stage move is permitted only once the virtual clock has reached the stage's `ends_at`. For each submission in this stage the server collects the list of `aggregated_score` values from all `ReviewAssignment` rows whose `review_stage_id` is this stage, whose `submission_id` is the submission, and whose `status` is exactly `SUBMITTED` (assignments that are `PENDING`, `DISPUTED`, or `VOIDED` are excluded). If the collected count is less than the stage's `reviewer_quorum`, the per-submission aggregate is undefined and the stage cannot publish.

When the count of `SUBMITTED` scores is at least 5, the platform drops the single highest and single lowest scores before computing the mean of the remaining values; when the count is below 5, no trimming occurs and the mean is computed over all `SUBMITTED` scores. When ties exist at the boundary, the sort is broken by ascending `ReviewAssignment.id` so the trimmed selection is deterministic. For stages other than `FINAL`, and for the `FINAL` stage when `Project.client_participates_final` is false, the stage's aggregate per submission is the trimmed (or simple) mean rounded half up to two decimal places, stored under the stage's `stage_kind` in `Submission.aggregate_score_by_stage`. For the `FINAL` stage when `Project.client_participates_final` is true, the client's own scoring assignment is treated specially: after the trimming step, the client's score is removed from the trimmed-reviewer list, the mean of the remaining reviewer scores is computed, and the final aggregate is 30 percent of the client's `aggregated_score` plus 70 percent of the reviewers' mean, rounded half up to two decimal places. The result is stored in the same `Submission.aggregate_score_by_stage` field.

After aggregation, `PlatformOps` publishes the stage. Two preconditions must hold: every submission in this stage must have at least `reviewer_quorum` `SUBMITTED` assignments, and no in-stage submission may have any assignment currently in `DISPUTED`. A failure on either condition rejects the publish with `ERR_QUORUM_NOT_MET`. On a successful publish, `ReviewStage.status` flips to `PUBLISHED`, `advancing_submission_ids` is pinned in the same instant and becomes immutable, an `AuditEvent` with `action_kind` of `STAGE_PUBLISHED` is emitted, and the parent project advances: `IN_PRELIMINARY` to `IN_SEMIFINAL` when the preliminary stage publishes, and `IN_SEMIFINAL` to `IN_FINAL` when the semifinal stage publishes. Each cascade also propagates to submissions. On preliminary publish, every `ACCEPTED` submission whose stored aggregate equals or exceeds `passing_threshold` advances to `ADVANCING_SEMIFINAL`, and every `ACCEPTED` submission whose stored aggregate is strictly below `passing_threshold` transitions to the terminal `ELIMINATED` state. On semifinal publish, every `ADVANCING_SEMIFINAL` submission whose semifinal aggregate equals or exceeds `passing_threshold` advances to `ADVANCING_FINAL`, and every `ADVANCING_SEMIFINAL` submission whose semifinal aggregate is below `passing_threshold` transitions to `ELIMINATED`. After preliminary publish the `SEMIFINAL` `ReviewStage.status` flips to `OPEN`; after semifinal publish the `FINAL` `ReviewStage.status` flips to `OPEN`. When two `PlatformOps` operators race the publish of the same stage, the second is rejected with `ERR_STAGE_ALREADY_PUBLISHED` because exactly one publish is allowed per stage and the transition is serialized first-writer-wins on the `AGGREGATING` to `PUBLISHED` move.

### 3.6. Dispute Filing, Mediation, and the Aggregation Loop

Disputes are filed by `Client`, `Designer`, `Reviewer`, or `PlatformOps`. Each filing carries a scoping `project_id`, a `dispute_type` from `PLAGIARISM`, `SCORING_FAIRNESS`, `COPYRIGHT`, or `PAYMENT`, a `subject_ref_kind` describing what the dispute is about (`SUBMISSION`, `REVIEW_ASSIGNMENT`, `COPYRIGHT_TRANSFER`, or `PRIZE_PAYMENT`), a `subject_ref_id` matching that kind, a `filer_kind` declaring which class of party is filing, and a `filer_id` that resolves to the corresponding entity (the `Client.id`, `Designer.id`, or `ReviewerPool.reviewer_id`, or an opaque platform-operator identifier). Optional `evidence_urls` (0 to 20 HTTPS URLs) may be provided. The new dispute starts in `FILED`. Filing windows are strict: a `SCORING_FAIRNESS` dispute must be filed before the stage in question transitions to `PUBLISHED`; a `COPYRIGHT` or `PAYMENT` dispute must be filed within 14 days of the relevant `CopyrightTransfer` becoming `REGISTERED` or the relevant `PrizePayment` becoming `PAID` respectively. A filing outside its window is rejected with `ERR_DISPUTE_WINDOW_CLOSED`; the system also stamps `filed_within_window` on the new record. When a `SCORING_FAIRNESS` dispute targets a `REVIEW_ASSIGNMENT`, the targeted assignment cascades from `SUBMITTED` to `DISPUTED`, an `AuditEvent` with `action_kind` of `REVIEW_DISPUTED` is emitted, and that score is excluded from aggregation until the dispute resolves.

`PlatformOps` walks the dispute through stage-1 mediation (advancing `FILED` to `MEDIATING_STAGE1`) and, if needed, stage-2 mediation (`MEDIATING_STAGE1` to `MEDIATING_STAGE2`). If neither stage produces a resolution, `PlatformOps`, the `Client`, or the `Designer` may escalate to `ARBITRATION`. From any of `MEDIATING_STAGE1`, `MEDIATING_STAGE2`, or `ARBITRATION`, `PlatformOps` resolves the dispute by supplying an `outcome` of either `UPHELD` or `REJECTED` and a `resolution_note`. The state transitions correspondingly to `RESOLVED_UPHELD` or `RESOLVED_REJECTED`, and the resolution emits an `AuditEvent` with `action_kind` of `DISPUTE_RESOLVED`. A filer (`Client` or `Designer`) may instead withdraw their own dispute from `FILED` directly to `WITHDRAWN`, provided the withdrawer is the original filer.

Resolution cascades depend on `dispute_type`. An `UPHELD` `SCORING_FAIRNESS` dispute targeting a `REVIEW_ASSIGNMENT` moves the assignment from `DISPUTED` to the terminal `VOIDED`, emits a `REVIEW_VOIDED` `AuditEvent`, and recomputes `Submission.aggregate_score_by_stage` without that score; if after voiding any in-stage submission falls below `reviewer_quorum` `SUBMITTED` assignments, the stage's status reverts from `AGGREGATING` to `OPEN` so that a fresh `ReviewAssignment` can be created to restore quorum. A `REJECTED` `SCORING_FAIRNESS` dispute reverts the assignment from `DISPUTED` back to `SUBMITTED`, re-includes its score, and recomputes the affected submission's aggregate. An `UPHELD` `COPYRIGHT` or `PLAGIARISM` dispute cascades into the copyright-transfer void path described in §3.8. An `UPHELD` `PAYMENT` dispute cascades into the payment-reversal path described in §3.9.

A separate cancellation path exists for projects already past `ON_SHELF`: an `UPHELD` `PLAGIARISM` dispute against the project's own reference material legitimacy permits `PlatformOps` to cancel the project from `IN_PRELIMINARY` to `CANCELLED`, which cascades all `ReviewStage` rows of this project to the terminal `EXPIRED` state and voids all still-active `ReviewAssignment` rows. The earlier-path cancellation, available to the project's `Client` while the project is still `ON_SHELF` and no submissions have advanced past `DRAFT` or `WITHDRAWN`, also cascades every `ReviewStage` row to `EXPIRED`.

### 3.7. Award Selection and Originality Cross-Check

When the `FINAL` stage is `AGGREGATING`, `PlatformOps` performs the award. The award call accepts `tier_assignments`, an ordered list of pairs of `prize_tier_id` and `submission_id` that names a winning submission for every `PrizeTier` of this project. The transition moves the project from `IN_FINAL` to `AWARDED` and is gated by two preconditions: the `FINAL` `ReviewStage.status` must be `AGGREGATING`, and every `PrizeTier` of the project must have a winning submission selected in the payload. If any `ReviewAssignment` on a final-stage submission is currently `DISPUTED` at the moment the award is attempted, the award is rejected with `ERR_DISPUTE_PENDING`; conversely, if a pending dispute resolution commits first and removes the offending `DISPUTED` assignment, the award can proceed afterwards. The serialization is first-writer-wins on the `IN_FINAL` to `AWARDED` transition.

The award is the system's largest cascade. The `FINAL` `ReviewStage.status` is moved to `PUBLISHED`. `Project.anonymity_unmasked_at` is set to the server clock, lifting the anonymity regime described in §2.10. `Project.published_winner_list` is set to the ordered submission identifiers in tier-rank order and becomes immutable. Each selected submission has its `prize_tier_id` pinned to the chosen tier, and the chosen tier's `winner_submission_id` is pinned to the submission's identifier (the field is null for any tier that did not receive a winner). Each selected submission's status flips to `WINNER` if the tier's `tier_kind` is `MAIN` or to `RUNNER_UP` if `CONSOLATION`. Every other `ADVANCING_FINAL` submission of this project transitions to `ELIMINATED`. For each winning submission a `CopyrightTransfer` is auto-created in `DRAFTED`, and for each `PrizeTier` with a selected winner a `PrizePayment` is auto-created in `SCHEDULED`. At the same instant, the originality cross-check is recomputed for every winning submission: `originality_variant` is set to `FINAL_CROSSCHECK`, and a new `originality_score` is produced by the formula described next.

The cross-check formula reuses the public-corpus similarity from `similarity_corpus_id` and adds a peer-similarity term computed against the other submissions in the same `Project` whose status is `ADVANCING_FINAL`, `WINNER`, or `RUNNER_UP` (excluding the submission itself). Letting public-similarity be the maximum similarity against the public corpus and peer-similarity be the maximum similarity against the eligible peers, the combined similarity is the larger of public-similarity and the weighted blend in which peer-similarity is given a peer weight of 0.70 and public-similarity is given the complementary weight of 0.30. The `originality_score` is one minus that combined similarity, multiplied by 100 and rounded half up to two decimal places. Because the peer term can only raise the combined similarity above the public-only number, the final-cross-check score is never higher than the original preliminary-scan score on the same asset and can be strictly lower.

The award call also pins each `PrizePayment` row's `gross_amount_cents`, `withholding_cents`, and `net_amount_cents` using the prize-withholding calculation. The inputs are the `PrizeTier.gross_amount_cents` of the matched tier (an integer in cents) and the winning `Designer.tax_residency` captured at award time. When the residency is `RESIDENT`, the withholding is the gross multiplied by the resident rate of 0.20 and then rounded half up to integer cents; when the residency is `NON_RESIDENT`, the withholding is split across two tiers measured in cents — the portion at or below the tier-break boundary of 400,000 cents (i.e., 4,000.00 in major units) is multiplied by the non-resident tier-1 rate of 0.20 and rounded half up to integer cents, the portion strictly above the boundary is multiplied by the non-resident tier-2 rate of 0.30 and rounded half up to integer cents, and the two rounded tier amounts are then summed. The `net_amount_cents` is the gross minus the total withholding. Two designers with identical `gross_amount_cents` therefore end up with different `withholding_cents` and `net_amount_cents` depending on residency: the `RESIDENT` variant produces a flat-rate withholding; the `NON_RESIDENT` variant produces the tiered result.

### 3.8. Copyright Transfer Workflow

Each auto-drafted `CopyrightTransfer` carries the `project_id`, the `submission_id` of the winning entry, a `scope` of `FULL` or `LIMITED`, and a `usage_rights` list of permitted usage tags. The transfer-scope rule fires on create and on modification: when `scope` is `LIMITED`, `usage_rights` must be non-empty; when `scope` is `FULL`, `usage_rights` must be empty. A violation surfaces `ERR_TRANSFER_SCOPE_INVALID`. A `PlatformOps` operator may also create a transfer manually for a winning or runner-up submission when the auto-draft is missing, supplying `project_id`, `submission_id`, `scope`, and `usage_rights` when applicable.

The lifecycle then runs: `DRAFTED` to `PENDING_SIGNATURES` (issued for signing) requires the linked submission's `status` to be in `WINNER` or `RUNNER_UP` and the scope/usage-rights pairing to be valid; on issue the server emits a `COPYRIGHT_DRAFTED` `AuditEvent` and pre-populates `signers` in the fixed order `CLIENT`, `DESIGNER`, `PLATFORM_NOTARY`. From `PENDING_SIGNATURES`, the three parties sign one at a time. Each `sign` call supplies a `signer_party_kind` of `CLIENT`, `DESIGNER`, or `PLATFORM_NOTARY` and (optionally) `version`. The next-unsigned slot in `signers` must match the supplied party kind, and the caller's identity must match: the `CLIENT` slot is signed by the `Project.client_id`, the `DESIGNER` slot by the linked `Submission.designer_id`, and the `PLATFORM_NOTARY` slot by `PlatformOps`. An out-of-order signature is rejected with `ERR_SIGNATURE_OUT_OF_ORDER`. Each successful sign emits a `COPYRIGHT_SIGNED` `AuditEvent`; the final signature on the last slot flips the transfer to `ALL_SIGNED`. When two signers race the same transfer while a previous slot is still unsigned, the out-of-order party loses with `ERR_SIGNATURE_OUT_OF_ORDER`; only the next-in-order signer wins.

A signed transfer is then sent for external registration, moving `ALL_SIGNED` to `REGISTERING` and triggering the platform's outbound request to the copyright authority. When the external authority confirms by emitting an inbound event with `event_type` of `COPYRIGHT_REGISTERED` whose `subject_id` matches the transfer's identifier, the transfer flips to `REGISTERED`, `registration_ref` and `registered_at` are pinned from the event, and a `COPYRIGHT_REGISTERED` `AuditEvent` is appended.

The transfer can be voided by `PlatformOps` along three distinct paths, all driven by an upheld dispute. From `PENDING_SIGNATURES`, void is permitted when an `UPHELD` dispute of `dispute_type` `COPYRIGHT` or `PLAGIARISM` targets the linked submission; the void emits a `COPYRIGHT_VOIDED` `AuditEvent` and cascades any linked `PrizePayment` to `REVERSED`, which in turn emits a compensating payment-reversal event. From `ALL_SIGNED`, void is permitted only when an `UPHELD` `COPYRIGHT` dispute targets the submission and `registration_ref` is still null (the transfer has not yet been confirmed by the authority); the cascade is identical to the `PENDING_SIGNATURES` path. From `REGISTERED`, void is permitted when an `UPHELD` `COPYRIGHT` or `PLAGIARISM` dispute targets the submission; this path additionally emits an external deregistration request to the copyright authority, and the linked `PrizePayment` cascades `PAID` to `REVERSED` with a compensating refund event. In all three paths, the void call carries the originating `dispute_id` and supports `version`. The winning submission itself stays in `WINNER` or `RUNNER_UP` — those are terminal — and only the fiscal and registry effects are reversed.

### 3.9. Prize Payment Dispatch and Settlement

A `PrizePayment` row, created in `SCHEDULED` on award, mirrors the matched tier's `gross_amount_cents`, the computed `withholding_cents`, and the derived `net_amount_cents`, plus the winning `designer_id`, the originating `project_id`, and the matched `prize_tier_id`. `PlatformOps` dispatches the payment by transitioning `SCHEDULED` to `PAYING`. The dispatch call supplies an `idempotency_key` that must be unique across the pair `(project_id, prize_tier_id)`; if a payment with the same key is already `PAYING` or `PAID`, the duplicate is rejected with `ERR_DUPLICATE_IDEMPOTENCY_KEY` and the existing payment's identifier is returned in the conflict response. Dispatch is also gated on the linked `CopyrightTransfer.status` being `REGISTERED`; a dispatch attempt against an unregistered transfer is rejected with `ERR_COPYRIGHT_NOT_REGISTERED`. The dispatch emits the platform's outbound payment request carrying the `idempotency_key`.

The external payment system then drives the payment to terminal status through the inbound-event channel. An event with `event_type` of `PAYMENT_COMPLETED` and `subject_id` equal to the payment's identifier moves `PAYING` to `PAID`, pins `external_payment_ref` from the event, and emits a `PRIZE_PAID` `AuditEvent`. An event with `event_type` of `PAYMENT_FAILED` moves `PAYING` to `FAILED`. From `FAILED`, `PlatformOps` may retry, moving `FAILED` back to `SCHEDULED` for a fresh dispatch attempt. A `PAID` payment may still be reversed: when the corresponding `CopyrightTransfer` is voided from `REGISTERED`, the payment cascades `PAID` to `REVERSED` and the `PRIZE_PAID` `AuditEvent` payload is extended with a reversal note.

### 3.10. Project Closure, Audit, and Test-Driving Capabilities

`PlatformOps` closes an `AWARDED` project once all settlements have completed: every `PrizePayment` row of the project must be in `PAID` or `REVERSED`, every `CopyrightTransfer` row must be in `REGISTERED` or `VOIDED`, and every open dispute must be in a resolved terminal state (`RESOLVED_UPHELD`, `RESOLVED_REJECTED`, or `WITHDRAWN`). On close, the project transitions to the terminal `CLOSED` state.

All audited activity is recorded in `AuditEvent` rows that capture `occurred_at`, `action_kind`, `actor_kind`, `actor_id`, `subject_kind`, `subject_id`, and a structured `payload` typically holding the previous and new `status`. The catalog is read-only and supports filtering by `project_id`, `subject_kind`, `subject_id`, and `action_kind`.

For test-driving and time-gated cascades, an administrative capability advances the virtual clock to a supplied ISO 8601 instant: the request body carries a `to` field, and the server applies the advance, crossing any thresholds in between. Crossing a project's `submission_deadline` performs the cascade described in §3.3. A second administrative capability simulates an inbound event from an external system: the request body carries `event_type`, the `subject_id` of the targeted resource, and an optional `payload`. Supported `event_type` values are `PAYMENT_COMPLETED`, `PAYMENT_FAILED`, and `COPYRIGHT_REGISTERED`, applying the transitions described in §3.8 and §3.9. Internal-stage operations — moving a stage from `OPEN` to `AGGREGATING` and from `AGGREGATING` to `PUBLISHED` — remain `PlatformOps` actions, but the timer that gates them is the same virtual clock.

## 4. Endpoint Definitions

All endpoints accept JSON request bodies (when applicable) and return responses in the standard envelope of §2.2. As a general rule, endpoints that create a new resource respond with HTTP 201; endpoints that read or modify an existing resource respond with HTTP 200. Errors follow the standard error envelope and use the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/design-categories` | Create a design category. | `PlatformOps` |
| GET | `/design-categories` | List design categories. | `PlatformOps`, `Client`, `Designer`, `Reviewer` |
| POST | `/clients` | Register a client account. | `PlatformOps` |
| POST | `/designers` | Register a designer profile. | `PlatformOps` |
| GET | `/designers/{designer_id}` | Fetch a designer profile. | `PlatformOps`, `Designer` |
| POST | `/reviewer-pool` | Add a reviewer to the reviewer pool. | `PlatformOps` |
| POST | `/projects` | Create a draft project. | `Client` |
| GET | `/projects/{project_id}` | Get a single project. | `PlatformOps`, `Client`, `Designer`, `Reviewer` |
| GET | `/projects` | List projects with optional filters by `status`, `category_code`, and `client_id`. | `PlatformOps`, `Client`, `Designer`, `Reviewer` |
| POST | `/projects/{project_id}/prize-tiers` | Configure a prize tier on a project. | `Client` |
| POST | `/projects/{project_id}/review-stages` | Configure a review stage with rubric and timing. | `Client` |
| POST | `/projects/{project_id}/submit-for-review` | Submit a draft project for platform review. | `Client` |
| POST | `/projects/{project_id}/approve` | Approve a project for on-shelf. | `PlatformOps` |
| POST | `/projects/{project_id}/reject` | Reject a project under platform review. | `PlatformOps` |
| POST | `/projects/{project_id}/cancel` | Cancel a project (client while on-shelf; platform on upheld plagiarism dispute). | `Client`, `PlatformOps` |
| POST | `/projects/{project_id}/award` | Finalize winners and trigger the award cascade. | `PlatformOps` |
| POST | `/projects/{project_id}/close` | Close a fully settled project. | `PlatformOps` |
| POST | `/projects/{project_id}/submissions` | Create a designer submission. | `Designer` |
| GET | `/projects/{project_id}/submissions` | List submissions in a project with optional filters by `status` and `designer_id`. | `PlatformOps`, `Client`, `Designer`, `Reviewer` |
| GET | `/submissions/{submission_id}` | Get a submission. | `PlatformOps`, `Client`, `Designer`, `Reviewer` |
| PATCH | `/submissions/{submission_id}` | Modify a submission within its modify window. | `Designer` |
| DELETE | `/submissions/{submission_id}` | Withdraw a submission within its modify window. | `Designer` |
| POST | `/review-stages/{review_stage_id}/start-aggregation` | Move a review stage from open to aggregating. | `PlatformOps` |
| POST | `/review-stages/{review_stage_id}/publish` | Publish a review stage's results. | `PlatformOps` |
| POST | `/review-assignments` | Assign a reviewer to a submission within a stage. | `PlatformOps` |
| POST | `/review-assignments/{review_assignment_id}/submit-scores` | Submit per-criterion scores for an assignment. | `Reviewer`, `Client` |
| POST | `/review-assignments/{review_assignment_id}/void` | Void a pending assignment. | `PlatformOps` |
| GET | `/review-assignments/{review_assignment_id}` | Fetch an assignment. | `PlatformOps`, `Reviewer`, `Client` |
| POST | `/copyright-transfers` | Manually create a copyright transfer. | `PlatformOps` |
| POST | `/copyright-transfers/{transfer_id}/issue-for-signing` | Move a transfer to pending signatures. | `PlatformOps` |
| POST | `/copyright-transfers/{transfer_id}/sign` | Sign the next slot of a transfer. | `Client`, `Designer`, `PlatformOps` |
| POST | `/copyright-transfers/{transfer_id}/register` | Submit a transfer to the copyright authority. | `PlatformOps` |
| POST | `/copyright-transfers/{transfer_id}/void` | Void a transfer on an upheld dispute. | `PlatformOps` |
| GET | `/copyright-transfers/{transfer_id}` | Get a copyright transfer. | `PlatformOps`, `Client`, `Designer` |
| POST | `/prize-payments/{prize_payment_id}/dispatch` | Dispatch a scheduled payment. | `PlatformOps` |
| POST | `/prize-payments/{prize_payment_id}/retry` | Retry a failed payment. | `PlatformOps` |
| GET | `/prize-payments/{prize_payment_id}` | Get a prize payment. | `PlatformOps`, `Designer` |
| GET | `/prize-payments` | List prize payments with optional filters by `project_id`, `designer_id`, and `status`. | `PlatformOps`, `Designer` |
| POST | `/disputes` | File a dispute. | `Client`, `Designer`, `Reviewer`, `PlatformOps` |
| POST | `/disputes/{dispute_id}/start-mediation` | Begin stage-1 mediation. | `PlatformOps` |
| POST | `/disputes/{dispute_id}/escalate` | Escalate to stage-2 mediation. | `PlatformOps` |
| POST | `/disputes/{dispute_id}/request-arbitration` | Move a dispute to arbitration. | `PlatformOps`, `Client`, `Designer` |
| POST | `/disputes/{dispute_id}/resolve` | Resolve a dispute with `outcome` of `UPHELD` or `REJECTED`. | `PlatformOps` |
| POST | `/disputes/{dispute_id}/withdraw` | Withdraw a previously filed dispute. | `Client`, `Designer` |
| GET | `/disputes/{dispute_id}` | Get a dispute. | `PlatformOps`, `Client`, `Designer`, `Reviewer` |
| GET | `/disputes` | List disputes with optional filters by `project_id`, `dispute_type`, and `status`. | `PlatformOps`, `Client`, `Designer` |
| GET | `/audit-events` | List audit events with optional filters by `project_id`, `subject_kind`, `subject_id`, and `action_kind`. | `PlatformOps` |
| POST | `/_clock/advance` | Advance the virtual server clock to the supplied `to` instant. | `PlatformOps` |
| POST | `/_events/emit` | Emit a simulated inbound event (`event_type`, `subject_id`, optional `payload`). | `PlatformOps` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_ORIGINAL_DECLARATION_REQUIRED` | 422 |
| `ERR_REVIEWER_CONFLICT_OF_INTEREST` | 422 |
| `ERR_REVIEWER_NOT_QUALIFIED` | 422 |
| `ERR_REVIEWER_CAPACITY_EXCEEDED` | 422 |
| `ERR_MODIFY_WINDOW_CLOSED` | 422 |
| `ERR_REVIEW_WINDOW_CLOSED` | 422 |
| `ERR_TIMELINE_TOO_TIGHT` | 422 |
| `ERR_STAGE_OVERLAP` | 422 |
| `ERR_SUBMISSION_LIMIT_REACHED` | 422 |
| `ERR_RUBRIC_WEIGHTS_INVALID` | 422 |
| `ERR_CRITERION_SCORES_INVALID` | 422 |
| `ERR_TRANSFER_SCOPE_INVALID` | 422 |
| `ERR_SIGNATURE_OUT_OF_ORDER` | 409 |
| `ERR_COPYRIGHT_NOT_REGISTERED` | 422 |
| `ERR_PRIZE_POOL_MISMATCH` | 422 |
| `ERR_PRIZE_AMOUNT_INVALID` | 422 |
| `ERR_QUORUM_NOT_MET` | 422 |
| `ERR_DISPUTE_WINDOW_CLOSED` | 422 |
| `ERR_DISPUTE_PENDING` | 409 |
| `ERR_REVIEWER_ALREADY_ASSIGNED` | 409 |
| `ERR_STAGE_ALREADY_PUBLISHED` | 409 |
| `ERR_DUPLICATE_IDEMPOTENCY_KEY` | 409 |
