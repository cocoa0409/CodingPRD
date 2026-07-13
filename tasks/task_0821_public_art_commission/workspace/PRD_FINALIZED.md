# Public Art Commission API — Product Requirements Document

## 1. Introduction

Municipal capital projects frequently carry a "percent-for-art" obligation: a fixed fraction of the construction budget must be set aside to commission, fabricate, install, and steward public artwork. This document specifies the backend service that administers that obligation end to end — from the moment a capital project reserves its art budget, through the competitive artist call, panel scoring, award, fabrication contracting and milestone payment, to the physical registry that installs artwork on civic sites, tracks its condition over time, lends it to other institutions, and eventually deaccessions it.

The service coordinates several distinct parties who each own part of the workflow. A program office controls the fiscal and commissioning surface — the money, the calls for artists, the selection panel, the awards, and the contracts. A collection registrar controls the physical surface — sites, installation, conservation, and loans. Artists and selection-panel members are external actors who submit proposals and score them respectively, and their actions are always checked against their own identity. Because budgets are a conserved quantity and physical sites are single-occupancy, the system must maintain strict ledgers and interval invariants: an over-commitment of the art budget, a double-booked site, or a payment that exceeds a contract are all defects the API is designed to make impossible.

The requirements below define the global request/response contract first, then the domain-specific cross-cutting principles (budget ledgers, concurrency control, rounding, temporal rules), and finally the business workflows that tie the entities together. Endpoint and error tables at the end summarize the HTTP surface; the behavioral detail lives in the narrative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which the request is made. If either header is missing, or if `X-User-Role` is not one of the four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The four roles are spelled exactly `ProgramAdmin`, `Registrar`, `Artist`, and `Panelist`.

- A `ProgramAdmin` is the public-art program administrator. This role owns capital projects, budget certification, commissions, artist calls, tabulation, awards, fabrication contracts, and milestone approvals. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- A `Registrar` is the collection registrar. This role owns sites, artwork intake and registry, installation, conservation records, loans, and (jointly with `ProgramAdmin`) deaccession. When `X-User-Role` is `Registrar`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- An `Artist` submits and resubmits proposals and submits fabrication milestone deliverables. When `X-User-Role` is `Artist`, `X-User-ID` is the `id` of the acting `Artist`; ownership checks on any resource that references an `Artist` compare the resource's artist foreign key to `X-User-ID`.
- A `Panelist` is a selection-panel member who scores submissions. When `X-User-Role` is `Panelist`, `X-User-ID` is the `id` of the acting `Panelist`; ownership checks on any resource that references a `Panelist` compare the resource's panelist foreign key to `X-User-ID`.

For the entity-backed roles, ownership is enforced beyond mere role permission. When an `Artist` resubmits a proposal, the `artist_id` on the target submission must equal `X-User-ID`; when a `Panelist` scores a submission, the `panelist_id` on the new score must equal `X-User-ID`; and when an `Artist` submits a fabrication milestone deliverable, `X-User-ID` must equal the artist of the awarded submission behind that milestone's contract. Any of these ownership mismatches is rejected with `ERR_NOT_OWNER` (HTTP 403). All four roles may call every read (GET) endpoint.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; a requested `limit` above 100 is capped at 100. The `offset` parameter defaults to 0 and represents the number of leading records to skip. Every list is returned in ascending order of `created_at` (oldest first). The pagination fields `limit`, `offset`, `total_count`, and `has_more` are reported in the `meta` object of list responses, where `total_count` is the count of all records matching the query before pagination and `has_more` is true whenever more records exist beyond the current page.

### 2.4. Common Resource Properties and Versioning

Almost every resource carries a common set of server-managed properties. The `id` is a server-minted UUID (a plain UUID string with no type prefix). The `created_at` timestamp records when the resource was created, and `updated_at` records the most recent mutation; both are ISO 8601 UTC timestamps with three fractional digits. The `version` is an integer that starts at 1 on creation and increments by one on every mutation of the resource. These four properties — `id`, `created_at`, `updated_at`, and `version` — are present on capital projects, commissions, artist calls, artists, submissions, panelists, scores, contracts, milestones, sites, artworks, and loans.

`ConservationRecord` is the single exception. A conservation record is an immutable event log entry: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because it is never mutated after it is appended.

Whenever a mutation changes a resource, its `updated_at` is refreshed and its `version` is incremented. This applies equally to mutations driven directly by a request and to mutations driven indirectly through a cascade — for example, when approving a milestone drives a contract to completion, the contract's `updated_at` and `version` advance, and so do those of any artwork and commission the cascade touches.

### 2.5. Monetary Precision and Rounding

All monetary amounts are stored and exchanged as integer cents. Wherever a rate or fraction is multiplied into a cents amount, the result is converted back to an integer number of cents using round-half-up (a value exactly at the half-cent boundary rounds away from zero, upward). This rounding rule governs the provisional and final art-budget computations and the per-line milestone amounts. Panel composite scores, by contrast, are not monetary; they are rounded half-up to two decimal places. Ledger aggregations (committed, uncommitted, paid, and remaining totals) are exact integer arithmetic with no rounding.

### 2.6. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of a parent resource by supplying that parent's expected version. These are the only two endpoints that take a version field; no other endpoint accepts one.

The first is commission creation under a capital project: the request must include `expected_project_version` carrying the client's last observed `version` of the funding `CapitalProject`. If the project's current `version` has advanced beyond that value — because another writer already created a commission that consumed part of the art budget and bumped the project's `version` and `committed_cents` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The rejection prevents a writer whose view of the remaining budget is stale from over-committing the budget.

The second is scheduling a contract's milestone set: the request must include `expected_contract_version` carrying the client's last observed `version` of the parent `Contract`. If the contract's current `version` has advanced beyond that value — because another writer already scheduled a milestone set and bumped the contract's `version` — the schedule is rejected with `ERR_STALE_VERSION` (HTTP 412).

In both cases the check compares the supplied expected version against the parent's current `version`; equality is required, any inequality is a stale-version rejection.

### 2.7. Budget and Payment Ledgers as Conserved Quantities

The system maintains two ledger invariants, each anchored on a conserved total.

At the project level, the art budget is conserved: `art_budget_cents` always equals `uncommitted_cents` plus `committed_cents`. The `committed_cents` figure is the sum of `allocation_cents` across every child commission of the project whose `status` is not `CANCELLED`, and `uncommitted_cents` is `art_budget_cents` minus `committed_cents`. Creating a commission raises committed and lowers uncommitted by the allocation; cancelling a commission removes it from the committed sum, so committed falls and uncommitted rises by the same allocation.

At the contract level, the fabrication amount is conserved: `contract_amount_cents` always equals `paid_cents` plus `remaining_cents`. The `paid_cents` figure is the sum of `amount_cents` across the contract's milestones whose `status` is `PAID`, and `remaining_cents` is `contract_amount_cents` minus `paid_cents`. A contract begins with `paid_cents` at 0 and `remaining_cents` equal to `contract_amount_cents`; approving (paying) a milestone raises paid and lowers remaining by that milestone's `amount_cents`.

### 2.8. The Logical Clock and Temporal Rules

Time in this system is a logical clock, never the wall clock. On server startup the clock reads exactly `2026-03-01T00:00:00Z`; until it is explicitly set, every read of "now" returns that default. A `ProgramAdmin` may advance the clock to a supplied instant, `to_iso8601`, through the administrative test-driving capability. All temporal comparisons — submission deadlines, loan interval buffers, install-date occupancy — evaluate against this logical clock and against the stored instants on the relevant resources.

### 2.9. Nested Resource Resolution and Validation Ordering

Many endpoints address a resource nested under one or more parents in the URL path. Path parameters are resolved left to right, and every referenced resource — whether named in the path or the body — must exist. A missing resource yields the corresponding not-found error (`ERR_PROJECT_NOT_FOUND`, `ERR_COMMISSION_NOT_FOUND`, `ERR_CALL_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`, `ERR_ARTIST_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND`, `ERR_SCORE_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_ARTWORK_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, or `ERR_LOAN_NOT_FOUND`), each returned with HTTP 404.

Validation is evaluated in a fixed priority order so that the reported error is deterministic when several checks would fail. Authentication (presence and validity of the `X-User-ID` and `X-User-Role` headers) is checked first, yielding `ERR_UNAUTHENTICATED`. Role permission is checked next, yielding `ERR_UNAUTHORIZED`. For the three ownership-guarded operations — an artist's resubmission, a panelist's score, and an artist's milestone submission — ownership is checked immediately after role permission, yielding `ERR_NOT_OWNER`. Resource existence is checked next, yielding the appropriate not-found error. State legality (whether the target resource is in a state that permits the requested transition) is checked next, yielding `ERR_INVALID_STATE` (HTTP 409). Only after these gates pass are the domain-specific business rules — conflict-of-interest, interval conflicts, quorum, fiscal ceilings, structural validation, and optimistic-concurrency — evaluated; their specific orderings are noted with each workflow. The generic body-validation failure (a missing or malformed required field, an out-of-range enum, or a missing required `expected_project_version` or `expected_contract_version`) surfaces as `ERR_VALIDATION` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Capital Projects and the Percent-for-Art Budget

A capital project is where the money originates. A `ProgramAdmin` opens one by supplying a human-readable `name` and the estimated `construction_budget_cents`, which must be greater than zero. The percent-for-art rate, `percent_rate`, is optional; when omitted it defaults to 0.01 (one percent), and any supplied rate must lie between the minimum of 0.005 (half a percent) and the maximum of 0.05 (five percent), inclusive of both bounds. A new project starts life in status `DRAFT`.

At creation the spendable art budget, `art_budget_cents`, is computed in its **provisional** variant: multiply `construction_budget_cents` by `percent_rate` and round the resulting cents product half-up to a whole number of cents. Because no commissions exist yet, `committed_cents` is set to 0 and `uncommitted_cents` equals the full `art_budget_cents`.

The provisional budget is only an estimate. When the true construction cost is known, a `ProgramAdmin` certifies the project by supplying the `certified_construction_budget_cents`, which must be present and greater than zero. Certification is permitted only while the project is in `DRAFT`; it advances the project `DRAFT → BUDGET_CERTIFIED` and recomputes `art_budget_cents` in its **final** variant — `certified_construction_budget_cents` multiplied by `percent_rate`, again rounded half-up to whole cents. The final figure typically diverges from the provisional one. After the recomputation, `uncommitted_cents` is recomputed as `art_budget_cents` minus `committed_cents`, so previously committed allocations are preserved against the new budget. `BUDGET_CERTIFIED` is terminal for the project lifecycle. Fetching a project returns its current ledger figures, recomputed from its live commissions.

### 3.2. Commissions: Committing, Awarding, and Contracting the Budget

A commission reserves a slice of a project's art budget for one artwork procurement. A `ProgramAdmin` creates a commission against a project by supplying a `title`, an `allocation_cents` (greater than zero), and `expected_project_version`. Beyond the optimistic-concurrency check described earlier, the allocation is subject to the budget ceiling: the project's `committed_cents` plus the requested `allocation_cents` must not exceed `art_budget_cents`. If it would, the request is rejected with `ERR_ALLOCATION_EXCEEDS_BUDGET` (HTTP 422); the boundary is inclusive, so an allocation that brings committed exactly up to the budget is allowed. On success the commission is stored with its `project_id` and an initial status of `OPEN`, its `awarded_submission_id` is null, the project's `committed_cents` rises and `uncommitted_cents` falls by the allocation, and the project's `version` increments by one. Commissions can be listed and filtered by `project_id` and `status`.

Awarding closes the selection. A `ProgramAdmin` awards a commission by naming the winning `submission_id`. Award is permitted only when the commission is `OPEN`; additionally the artist call linked to this commission (the call whose `commission_id` equals the commission's `id`) must already be in status `TABULATED`, the named submission's `call_id` must belong to a call under this very commission — otherwise `ERR_SUBMISSION_CALL_MISMATCH` (HTTP 422) — and that submission must be in status `SCORED` with a `composite_score` greater than zero. On award, the winning submission transitions `SCORED → AWARDED`; every sibling submission on the same call still in `SCORED` is transitioned `SCORED → REJECTED` in a fan-out; the commission's `awarded_submission_id` is set to the winning submission's id; and the commission itself advances `OPEN → AWARDED`.

Cancellation unwinds a commission. A `ProgramAdmin` may cancel a commission while it is in either `OPEN` or `AWARDED` status, moving it to `CANCELLED`. Cancellation releases the budget: the commission is dropped from the committed sum, so the project's `committed_cents` decreases by `allocation_cents` and `uncommitted_cents` increases by the same amount, restoring the budget invariant. Cancellation also cascades to the solicitation: the linked artist call, if it is in `OPEN` or `CLOSED`, transitions to `CANCELLED`, and in turn every non-terminal submission on that call — those in `SUBMITTED`, `REVISION_REQUESTED`, or `SCORED` — transitions to `WITHDRAWN`. Both `FULFILLED` and `CANCELLED` are terminal for a commission.

Contracting turns an award into a fabrication agreement. A `ProgramAdmin` creates the fabrication contract for an awarded commission by supplying the `submission_id` and the `contract_amount_cents`. The commission must be in `AWARDED`, the supplied `submission_id` must equal the commission's `awarded_submission_id`, and the `contract_amount_cents` (greater than zero) must not exceed the commission's `allocation_cents` — a larger amount is rejected with `ERR_CONTRACT_EXCEEDS_ALLOCATION` (HTTP 422). On success a `Contract` is created in status `DRAFT` with its `commission_id`, its `paid_cents` at 0 and `remaining_cents` equal to `contract_amount_cents`, and the commission advances `AWARDED → CONTRACTED`. The final leg of the commission lifecycle, `CONTRACTED → FULFILLED`, is never requested directly; it occurs by cascade when the commission's artwork reaches fabrication (see §3.5).

### 3.3. Soliciting Artists: Calls, Panels, and Submissions

An artist call is the competitive solicitation under a commission. A `ProgramAdmin` opens a call by supplying its `call_type` — either `RFQ` or `RFP` — the `submission_deadline` (an ISO 8601 UTC instant), and the `quorum_min`, which must be at least 1 and sets how many non-recused panelists must have scored before the panel can tabulate. A call is created with its `commission_id` and status `OPEN`; calls can be listed and filtered by `commission_id` and `status`.

The selection panel is assembled per call. A `ProgramAdmin` adds a panelist by supplying an `evaluator_name` and an optional `has_conflict` flag, which defaults to false. The panelist's `recused` property is set from that flag at creation: a panelist declared with a conflict is recused, and a recused panelist may neither score submissions nor be counted toward quorum. Each panelist stores the `call_id` of the call it evaluates; a call's panelists can be listed.

Artists are onboarded independently. A `ProgramAdmin` registers an artist with a `display_name`, an `email`, and an optional home `region` (which defaults to null).

Submitting a proposal is an artist action. Acting as `Artist`, the submitter posts to an open call with the `artist_id` identifying the submitting artist and a `proposed_budget_cents` (greater than zero). The call must be `OPEN`, and the moment of submission — the logical clock — must fall strictly before the call's `submission_deadline`; a submission at or after the deadline is rejected with `ERR_DEADLINE_PASSED` (HTTP 422). An artist may hold at most one non-withdrawn submission per call: a second live submission to the same call by the same artist (uniqueness on the `call_id`/`artist_id` pair) is rejected with `ERR_DUPLICATE_SUBMISSION` (HTTP 409). A new submission stores its `call_id` and starts in status `SUBMITTED` with a null `composite_score`.

Revision is a two-step loop. A `ProgramAdmin` may request a revision on a submission that is `SUBMITTED` while its call is still `OPEN`, moving it `SUBMITTED → REVISION_REQUESTED`; as a side effect, any existing `Score` rows for that submission are discarded, because a revised proposal must be re-scored from scratch. The artist then resubmits: acting as `Artist`, and only when `X-User-ID` equals the submission's `artist_id` (otherwise `ERR_NOT_OWNER`), the owner moves a `REVISION_REQUESTED` submission back to `SUBMITTED`, re-entering the scoring pool. Resubmission requires the submission to be in `REVISION_REQUESTED`, the linked call to be `OPEN`, and the logical clock to be strictly before the `submission_deadline` — a late resubmission is likewise rejected with `ERR_DEADLINE_PASSED`. This forms the cycle `SUBMITTED → REVISION_REQUESTED → SUBMITTED`.

### 3.4. Panel Scoring, Tabulation, and the Composite Score

Scoring is a panelist action. Acting as `Panelist`, a panel member scores a submission across four criteria — `artistic_merit`, `feasibility`, `community_impact`, and `durability` — each an integer from 0 to 100 inclusive, alongside the `panelist_id` and the implied `submission_id`. The `panelist_id` must equal `X-User-ID`, or the score is rejected with `ERR_NOT_OWNER`. Two business guards apply, in this order: a recused panelist (one whose declared conflict left `has_conflict` true) may not score at all, and an attempt to do so is rejected first with `ERR_PANELIST_CONFLICT` (HTTP 422); and a panelist may hold at most one score per submission, so a second score for the same submission is then rejected with `ERR_DUPLICATE_SCORE` (HTTP 409). Each accepted score carries a computed `weighted_value`: the sum of 0.40 times `artistic_merit`, 0.25 times `feasibility`, 0.20 times `community_impact`, and 0.15 times `durability`. Scores can be fetched individually and listed by `submission_id` and `panelist_id`.

Closing a call stops intake. A `ProgramAdmin` closes an `OPEN` call, moving it `OPEN → CLOSED`; once closed, new submissions to it are refused on state grounds.

Tabulation is where the panel's verdict is computed. A `ProgramAdmin` tabulates a `CLOSED` call, advancing it `CLOSED → TABULATED`. Before any score is computed, quorum is checked: the number of non-recused panelists on the call who have scored **every** non-withdrawn submission on that call must be at least the call's `quorum_min` (the boundary is inclusive — exactly `quorum_min` such panelists suffices). If fewer qualify, tabulation is rejected with `ERR_QUORUM_NOT_MET` (HTTP 409).

When quorum holds, the system computes each non-withdrawn submission's `composite_score` and sets its state. For a given submission, the **counted** scores are those authored by non-recused panelists; scores from recused panelists are excluded entirely. Ordering, where it matters, is by score `created_at` ascending. First the durability gate: take the mean of the `durability` criterion across the counted scores; if that mean is below the durability floor of 40, the submission is disqualified — its `composite_score` is set to 0 and it transitions `SUBMITTED → DISQUALIFIED`. Otherwise the submission passes the gate, transitions `SUBMITTED → SCORED`, and its `composite_score` is computed from the counted scores' `weighted_value` figures in one of two variants:

- **Trimmed variant** — when there are at least three counted scores: drop exactly one score with the highest `weighted_value` and exactly one score with the lowest `weighted_value` (if two scores tie for an extreme, drop the one with the earlier `created_at`), then take the mean of the remaining `weighted_value` figures and round it half-up to two decimal places.
- **Mean variant** — when there are fewer than three counted scores: take the mean of all counted `weighted_value` figures and round it half-up to two decimal places.

The trimmed and mean variants diverge whenever the dropped extremes are asymmetric. A submission that is disqualified or scored zero cannot subsequently be awarded, since award requires a `composite_score` strictly greater than zero.

### 3.5. Fabrication: Milestone Scheduling, Payment, and the Completion Cascade

Once a contract exists, its payment schedule is laid out in a single call. A `ProgramAdmin` schedules the full milestone set for a contract by supplying `expected_contract_version` and a list of `milestones`; each entry names its 1-based `sequence` (unique within the contract), a `title`, and its `pct`, the fraction of the contract that milestone represents (greater than zero and at most 1). The supplied `pct` values across the contract must sum to exactly 1.0, or the schedule is rejected with `ERR_MILESTONE_PCT_SUM` (HTTP 422). Beyond the optimistic-concurrency guard on `expected_contract_version`, scheduling computes each milestone's `amount_cents` with a pinned rounding order: process the milestones in ascending `sequence`; for every milestone except the one with the highest sequence, set its `amount_cents` to `contract_amount_cents` multiplied by that milestone's `pct`, rounded half-up to whole cents, and accumulate a running total; the highest-sequence milestone then takes exactly `contract_amount_cents` minus that running total, so the milestone amounts sum precisely to the contract amount and the final line absorbs the rounding remainder. Each milestone starts in status `PENDING`. Scheduling increments the contract's `version` by one. A contract's milestones can be listed.

Activation brings a contract to life and mints the artwork. A `ProgramAdmin` activates a contract that is in `DRAFT`; activation additionally requires that the funding capital project be in `BUDGET_CERTIFIED` and that the contract's already-scheduled milestone `pct` values sum to 1.0. On success the contract moves `DRAFT → ACTIVE` and a new `Artwork` is synthesized with `acquisition_type` of `COMMISSION`, its `contract_id` pointing back at this contract, `location_status` of `FABRICATION`, and `condition_status` of `GOOD`.

Milestone delivery and payment drive fabrication forward. The awarded artist submits a deliverable: acting as `Artist`, and only when `X-User-ID` equals the awarded artist behind the contract (the `artist_id` of the submission the contract was awarded from, otherwise `ERR_NOT_OWNER`), the owner moves a milestone `PENDING → SUBMITTED`, provided the milestone is `PENDING` and its parent contract is `ACTIVE`. A `ProgramAdmin` then approves and pays it: a `SUBMITTED` milestone whose contract is `ACTIVE` transitions `SUBMITTED → PAID`, and the contract's `paid_cents` increases by that milestone's `amount_cents` while `remaining_cents` decreases by the same amount.

Approval carries a conditional cascade. If, after a milestone is paid, the contract's `paid_cents` equals its `contract_amount_cents`, the contract transitions `ACTIVE → COMPLETED`; that completion transitions the linked artwork (the one whose `contract_id` is this contract) `FABRICATION → FABRICATED`; and the artwork reaching `FABRICATED` transitions the parent commission (reached via the contract's `commission_id`) `CONTRACTED → FULFILLED`. This is the single serialization chain from a final milestone payment all the way to a fulfilled commission. Every entity the cascade touches has its `updated_at` refreshed and its `version` incremented.

### 3.6. The Physical Registry: Sites, Intake, Installation, and Conservation

Sites are civic locations that host artwork. A `Registrar` registers a site with a `name`, an `address`, and an optional `capacity` that defaults to 1; sites in this system are single-occupancy, so capacity is always 1. A new site is `AVAILABLE` with a null `current_artwork_id`.

Artwork enters the collection two ways. Commission artworks are minted automatically by contract activation, as described above. Everything else is taken in directly: a `Registrar` intakes an artwork with a `title`, an `acquisition_type`, an optional `appraised_value_cents`, and an optional `site_id`. Direct intake accepts only an `acquisition_type` of `DONATION` or `LOAN`; a `COMMISSION` acquisition supplied here is rejected with `ERR_DONATION_TYPE_REQUIRED` (HTTP 422), because commission artworks may only arise from contract activation. A directly intaken artwork is created with `location_status` of `FABRICATED` and `condition_status` of `GOOD`, and its `contract_id` is null. Artworks can be fetched and listed, filtered by `contract_id`, `site_id`, `acquisition_type`, and `location_status`.

An artwork carries two independent state dimensions. Its `location_status` moves through `FABRICATION`, `FABRICATED`, `INSTALLED`, and the terminal `DEACCESSIONED`, while its `condition_status` moves independently across `GOOD`, `FAIR`, `POOR`, and `NEEDS_TREATMENT`, driven only by conservation events. The two evolve in parallel and do not gate each other except where explicitly stated.

Installation places a fabricated artwork on a site. A `Registrar` installs an artwork by supplying the target `site_id` and the `install_date` (an ISO 8601 UTC instant). The artwork must be `FABRICATED`, the target site must be `AVAILABLE`, and no already-installed artwork may occupy that site over an interval that contains the `install_date`. Site occupancy is treated as a half-open interval beginning at the install instant and extending forward indefinitely, with adjacency permitted; a colliding install is rejected with `ERR_SITE_INTERVAL_CONFLICT` (HTTP 409). On success the artwork moves `FABRICATED → INSTALLED` with its `site_id` and `install_date` recorded, and the target site moves `AVAILABLE → OCCUPIED` with its `current_artwork_id` set to the installed artwork.

Conservation records track condition over time. A `Registrar` appends a conservation record to an artwork with a `record_type` — one of `INSPECTION`, `TREATMENT`, or `DAMAGE` — a `condition_after` — one of `GOOD`, `FAIR`, `POOR`, or `NEEDS_TREATMENT` — optional free-text `notes`, and an optional `performed_at` instant that defaults to the logical clock when omitted. The record is stored against its `artwork_id`, and as a side effect the artwork's `condition_status` is set to the supplied `condition_after`. Records may be appended only while the artwork's `location_status` is not `DEACCESSIONED`. Conservation records are immutable event entries and are never updated; an artwork's conservation records can be listed.

### 3.7. Loans and Deaccession

Loans lend an artwork to another institution for a date interval. A `Registrar` requests a loan against an artwork with a `borrower_name`, a `loan_start`, and a `loan_end`, where `loan_end` must be after `loan_start`. The requested interval, treated as closed on both ends, must not overlap — and must not sit within 30 calendar days (the loan buffer) — of any non-returned loan on the same artwork, meaning any loan currently in `REQUESTED` or `APPROVED`; a violation is rejected with `ERR_LOAN_INTERVAL_CONFLICT` (HTTP 409). A new loan is stored against its `artwork_id` in status `REQUESTED`; loans on an artwork can be listed. A `Registrar` approves a `REQUESTED` loan, moving it `REQUESTED → APPROVED`, provided the artwork's `location_status` is not `DEACCESSIONED`; and a `Registrar` returns an `APPROVED` loan, moving it `APPROVED → RETURNED`, which frees the artwork to be loaned again. `RETURNED` is terminal.

Deaccession retires an artwork from the collection. Either a `ProgramAdmin` or a `Registrar` may deaccession an artwork whose `location_status` is `FABRICATED` or `INSTALLED`, supplying the `deaccession_method` — one of `SALE`, `DONATION`, `DESTRUCTION`, or `TRANSFER` — and an optional `deaccession_proceeds_cents`. Deaccession is blocked while any loan on the artwork is in `APPROVED`; such an attempt is rejected with `ERR_DEACCESSION_BLOCKED_BY_LOAN` (HTTP 409). On success the artwork moves to `DEACCESSIONED` with its `deaccession_method` and `deaccession_proceeds_cents` recorded. If the artwork was installed, its site is freed as a compensating action: the site moves `OCCUPIED → AVAILABLE` and its `current_artwork_id` is cleared to null. A deaccession of a merely fabricated (never installed) artwork has no site to free.

Finally, an administrative test-driving capability lets a `ProgramAdmin` advance the logical clock to a supplied `to_iso8601` instant, which all temporal comparisons in the system read against.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. Endpoints that create a new resource respond with HTTP 201; endpoints that modify or transition an existing resource, and all reads, respond with HTTP 200. Request bodies, response bodies, and side effects are described in the workflow narratives of §3, not in this table.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /projects | Create a capital project (art budget computed provisionally) | ProgramAdmin |
| GET | /projects/{id} | Fetch a capital project | ProgramAdmin, Registrar, Artist, Panelist |
| POST | /projects/{id}/certify | Certify the construction budget; recompute the final art budget | ProgramAdmin |
| POST | /projects/{id}/commissions | Create a commission funded by the project art budget | ProgramAdmin |
| GET | /commissions/{id} | Fetch a commission | ProgramAdmin, Registrar, Artist, Panelist |
| GET | /commissions | List commissions (filter by project_id, status) | ProgramAdmin, Registrar, Artist, Panelist |
| POST | /commissions/{id}/award | Award a scored submission; reject siblings | ProgramAdmin |
| POST | /commissions/{id}/cancel | Cancel a commission; release budget and cascade | ProgramAdmin |
| POST | /commissions/{id}/contracts | Create the fabrication contract for the awarded submission | ProgramAdmin |
| GET | /contracts/{id} | Fetch a contract | ProgramAdmin, Registrar, Artist, Panelist |
| GET | /contracts | List contracts (filter by commission_id, submission_id, status) | ProgramAdmin, Registrar, Artist, Panelist |
| POST | /contracts/{id}/activate | Activate a contract; synthesize the commission artwork | ProgramAdmin |
| POST | /contracts/{id}/milestone-schedule | Schedule the milestone set in one call; amounts computed with pinned rounding | ProgramAdmin |
| GET | /contracts/{id}/milestones | List a contract's milestones | ProgramAdmin, Registrar, Artist, Panelist |
| POST | /milestones/{id}/submit | Awarded artist submits a milestone deliverable | Artist |
| POST | /milestones/{id}/approve | Approve and pay a milestone; drives the fabrication cascade | ProgramAdmin |
| POST | /commissions/{id}/calls | Open an artist call (RFQ/RFP) for a commission | ProgramAdmin |
| GET | /calls/{id} | Fetch an artist call | ProgramAdmin, Registrar, Artist, Panelist |
| GET | /calls | List calls (filter by commission_id, status) | ProgramAdmin, Registrar, Artist, Panelist |
| POST | /calls/{id}/close | Close a call to new submissions | ProgramAdmin |
| POST | /calls/{id}/tabulate | Tabulate panel scores; set composite scores and SCORED/DISQUALIFIED | ProgramAdmin |
| POST | /calls/{id}/panelists | Add a selection-panel member to a call | ProgramAdmin |
| GET | /calls/{id}/panelists | List a call's panelists | ProgramAdmin, Registrar, Artist, Panelist |
| POST | /artists | Onboard an artist | ProgramAdmin |
| POST | /calls/{id}/submissions | Artist submits to an open call before the deadline | Artist |
| GET | /submissions/{id} | Fetch a submission | ProgramAdmin, Registrar, Artist, Panelist |
| GET | /submissions | List submissions (filter by call_id, artist_id, status) | ProgramAdmin, Registrar, Artist, Panelist |
| POST | /submissions/{id}/request-revision | Panel requests a revision (invalidates prior scores) | ProgramAdmin |
| POST | /submissions/{id}/resubmit | Artist resubmits a revised proposal before the deadline | Artist |
| POST | /submissions/{id}/scores | Panelist scores a submission across four criteria | Panelist |
| GET | /scores/{id} | Fetch a score | ProgramAdmin, Registrar, Artist, Panelist |
| GET | /scores | List scores (filter by submission_id, panelist_id) | ProgramAdmin, Registrar, Artist, Panelist |
| POST | /sites | Register an installation site | Registrar |
| GET | /sites/{id} | Fetch an installation site | ProgramAdmin, Registrar, Artist, Panelist |
| POST | /artworks | Intake a DONATION or LOAN artwork | Registrar |
| GET | /artworks/{id} | Fetch an artwork | ProgramAdmin, Registrar, Artist, Panelist |
| GET | /artworks | List artworks (filter by contract_id, site_id, acquisition_type, location_status) | ProgramAdmin, Registrar, Artist, Panelist |
| POST | /artworks/{id}/install | Install a fabricated artwork on an available site | Registrar |
| POST | /artworks/{id}/deaccession | Deaccession an artwork; free its site | ProgramAdmin, Registrar |
| POST | /artworks/{id}/conservation-records | Append a conservation/maintenance record; update condition | Registrar |
| GET | /artworks/{id}/conservation-records | List an artwork's conservation records | ProgramAdmin, Registrar, Artist, Panelist |
| POST | /artworks/{id}/loans | Request a loan of an artwork for a date interval | Registrar |
| GET | /artworks/{id}/loans | List an artwork's loans | ProgramAdmin, Registrar, Artist, Panelist |
| POST | /loans/{id}/approve | Approve a requested loan | Registrar |
| POST | /loans/{id}/return | Return a loaned artwork; close the loan interval | Registrar |
| POST | /_clock/set_current_utc | Set the logical clock (test-driving) | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_OWNER | 403 |
| ERR_PROJECT_NOT_FOUND | 404 |
| ERR_COMMISSION_NOT_FOUND | 404 |
| ERR_CALL_NOT_FOUND | 404 |
| ERR_SUBMISSION_NOT_FOUND | 404 |
| ERR_ARTIST_NOT_FOUND | 404 |
| ERR_PANELIST_NOT_FOUND | 404 |
| ERR_SCORE_NOT_FOUND | 404 |
| ERR_CONTRACT_NOT_FOUND | 404 |
| ERR_MILESTONE_NOT_FOUND | 404 |
| ERR_ARTWORK_NOT_FOUND | 404 |
| ERR_SITE_NOT_FOUND | 404 |
| ERR_LOAN_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_PANELIST_CONFLICT | 422 |
| ERR_QUORUM_NOT_MET | 409 |
| ERR_DUPLICATE_SCORE | 409 |
| ERR_DUPLICATE_SUBMISSION | 409 |
| ERR_SUBMISSION_CALL_MISMATCH | 422 |
| ERR_DEADLINE_PASSED | 422 |
| ERR_SITE_INTERVAL_CONFLICT | 409 |
| ERR_LOAN_INTERVAL_CONFLICT | 409 |
| ERR_MILESTONE_PCT_SUM | 422 |
| ERR_DONATION_TYPE_REQUIRED | 422 |
| ERR_ALLOCATION_EXCEEDS_BUDGET | 422 |
| ERR_CONTRACT_EXCEEDS_ALLOCATION | 422 |
| ERR_DEACCESSION_BLOCKED_BY_LOAN | 409 |
| ERR_VALIDATION | 422 |
