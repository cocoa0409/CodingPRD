# EQIP Cost-Share API — Product Requirements Document

## 1. Introduction

The Environmental Quality Incentives Program and its state-administered cousins share a demanding operational shape: a finite appropriation of conservation dollars, a fixed application window per state, a competitive ranking of producer applications, and a long compliance tail in which certified practices must be maintained for years and misspent funds must be recovered. This document specifies the EQIP Cost-Share API, a system that administers that lifecycle end to end — from the configuration of a funding program with its pools, payment schedule rates, and ranking criteria, through application screening and pool assignment, to contract obligation, practice certification, payment disbursement, and the recoupment of funds when obligations are breached.

The API serves five distinct operator communities — program administrators, conservation planners, payment officers, quality-assurance inspectors, and the producers themselves — under strict segregation-of-duties rules: the planner who certifies a practice may not approve its payment, the inspector who opens a spot check must be the one who records its result, and the officer who confirms a maintenance violation may not be the planner who reported it. Because the program's money is finite and publicly accountable, every dollar is tracked through an explicit funding-pool ledger governed by a conservation invariant, and every deadline — application windows, implementation deadlines, advance-expenditure clocks, maintenance lifespans — is evaluated against a single logical clock that the server itself maintains.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply across the entire API. All business resources are mounted under the `/eqip` URL prefix; the only endpoint outside that prefix is the administrative clock control listed in §4.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or carrying a role value outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly five roles: `ProgramAdmin`, `ConservationPlanner`, `PaymentOfficer`, `QualityAssuranceOfficer`, and `Applicant`. Each write endpoint admits a fixed set of roles (§4); a request whose role is not among them is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

For four of the roles — `ProgramAdmin`, `ConservationPlanner`, `PaymentOfficer`, and `QualityAssuranceOfficer` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow requires an audit stamp (for example, as `certified_by_user_id` on a certified practice item, `reviewed_by_user_id` on an approved payment request, `inspector_user_id` on a spot check, `reported_by_user_id` on a violation report, or `requested_by_user_id` on a modification request), but it never compares the header to any entity's `id` for these roles. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting Applicant record; ownership checks on any resource that references an applicant compare the resource's `applicant_id` foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_APPLICANT_NOT_OWNER` (HTTP 403). Ownership is enforced on writes only: every read endpoint is available to all five roles regardless of ownership.

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

List endpoints paginate via two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

Beyond pagination, list endpoints accept resource-specific equality filters as query parameters. Programs filter by `state_code` and `status`; pools by `pool_type`; rates by `practice_code`; applications by `program_id`, `applicant_id`, `funded_pool_id`, and `status`; contracts by `program_id`, `application_id`, `applicant_id`, `pool_id`, and `status`; practice items by `contract_id`, `payment_schedule_rate_id`, `certification_status`, and `payment_status`; payment requests by `program_id`, `contract_id`, `practice_item_id`, and `status`; advances by `contract_id`, `applicant_id`, `practice_item_id`, and `status`; modifications by `contract_id`, `practice_item_id`, `kind`, and `status`; spot checks by `contract_id`, `practice_item_id`, `payment_request_id`, and `status`; maintenance obligations by `contract_id`, `practice_item_id`, and `status`; and recoupment demands by `contract_id`, `maintenance_obligation_id`, `advance_payment_id`, `payment_request_id`, and `status`.

### 2.4. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` records the creation instant and `updated_at` the most recent mutation instant, both as ISO 8601 UTC timestamps with three fractional digits. `version` is a system-managed integer that increments by one on every mutation of the resource and underpins the optimistic concurrency rules of §2.10. Any mutation described in §3 — including side effects that land on a resource other than the one named in the request — refreshes that resource's `updated_at` and increments its `version`.

Two configuration entities are deliberate exceptions to this pattern: a program's payment schedule rate and its ranking criterion are immutable configuration rows carrying only `id` and `created_at`. Neither `updated_at` nor `version` exists on these two resources.

### 2.5. Nested Resource Retrieval and Existence Checking

Several resources live beneath a parent in the URL hierarchy — pools, rates, and ranking criteria beneath programs; practice items, advance payments, and modifications beneath contracts. Requests that target nested resources are validated strictly left to right: the existence of each path identifier is confirmed in order, and the request is rejected with the not-found error for the first identifier that does not resolve before any later identifier is examined. The not-found family comprises `ERR_PROGRAM_NOT_FOUND`, `ERR_POOL_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_PRACTICE_ITEM_NOT_FOUND`, `ERR_PAYMENT_REQUEST_NOT_FOUND`, `ERR_ADVANCE_PAYMENT_NOT_FOUND`, `ERR_MODIFICATION_NOT_FOUND`, `ERR_SPOT_CHECK_NOT_FOUND`, `ERR_MAINTENANCE_OBLIGATION_NOT_FOUND`, and `ERR_RECOUPMENT_DEMAND_NOT_FOUND`, each carrying HTTP 404.

The same existence discipline applies to foreign keys supplied in request bodies — an application naming a nonexistent `program_id` or `applicant_id`, a payment request naming a nonexistent `contract_id` or `practice_item_id`, and so on. Where a body supplies two linked identifiers, the pair must actually belong together: a payment request's `practice_item_id` must reference an item of the referenced contract, and a spot check's `payment_request_id`, when supplied, must reference a payment request belonging to the referenced item.

### 2.6. Validation Order and Rejection Priority

When several checks would fail on the same request, the server reports the earliest failure in a fixed evaluation order rather than an arbitrary one. The order, from first to last, is:

1. Header presence and role validity — `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. Role authorization for the endpoint — `ERR_UNAUTHORIZED_ROLE`.
3. Existence of every referenced resource, path identifiers validated left to right and body foreign keys thereafter — the not-found family of §2.5.
4. Applicant ownership — `ERR_APPLICANT_NOT_OWNER`.
5. Whether the target resource's current state permits the operation — the state-specific conflict family, including the frozen-posture rules for contracts under modification review (§3.8).
6. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`.
7. The sampled-request spot-check gate at disbursement — `ERR_SPOT_CHECK_REQUIRED`.
8. Shape, uniqueness, and cardinality — required fields present and correctly typed, valid enum values, non-empty documentation, per-program uniqueness of rates and criteria, quantity bounds, one active payment request per item, one advance per item, exact-amount repayments.
9. Clock-dependent rules — the submission window, implementation deadlines, extension windows, and certification freshness, evaluated on the submission, installation-report, certification, modification, and disbursement workflows.
10. Cross-entity link validity — parcel registration, rate coverage, application-to-item practice consistency, maintenance-obligation overlap, and program-window overlap.
11. Fiscal checks — pool sufficiency, the advance cap, and historically-underserved eligibility.

A request that fails both a state check and a fiscal check therefore reports the state error, and so on down the ladder; lower rungs are evaluated only when every higher rung has passed.

### 2.7. The Logical Clock and the Deadline Sweep

All time-dependent behavior in the system — application windows, implementation deadlines, advance-expenditure clocks, escalation timers, maintenance lifespans — is evaluated against a single server-maintained logical clock, never against wall-clock time. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and the server never falls back to the host's wall clock. A `ProgramAdmin` advances it through an administrative test-driving capability that accepts a target instant `to_iso8601` and returns the resulting `current_utc`. The clock may only move forward; an attempt to set it earlier than its current value is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Setting the clock runs the deadline sweep, a fixed battery of transitions applied wherever the new instant qualifies: programs whose application window has closed (the clock has passed `window_end`) move from `OPEN` to `CLOSED`; practice items whose `implementation_deadline` has passed move from `PLANNED`, `INSTALLED`, or `CERTIFICATION_FAILED` to `EXPIRED` — except while their contract is under modification review, which freezes the expiry sweep; issued advances whose `expenditure_due_date` has passed with money still outstanding move from `ISSUED` to `RETURN_DUE`, and those still unpaid thirty days past the due date escalate, spawning a recoupment demand; maintenance obligations whose `end_date` has been reached move from `ACTIVE` to `SATISFIED`; and recoupment demands whose `due_date` has passed move from `DEMANDED` to `ESCALATED`. The sweep is the only driver of these transitions; each is described in its workflow context in §3.

### 2.8. Funding Pool Conservation

Every program's money lives in one or more funding pools, each a small ledger of three moving balances against an appropriation. `allocated_cents` is the appropriated amount and never changes after creation. `obligated_cents` is the sum reserved by obligated contracts and not yet disbursed or released. `paid_cents` is the net cash disbursed — advances and disbursements paid out, minus applicant repayments received. The derived `available_cents` equals `allocated_cents` minus `obligated_cents` minus `paid_cents`, and the conservation invariant holds at all times: the allocated amount always equals the sum of the available, obligated, and paid balances.

Every money movement in the system is one half of a forward-and-compensating pair that preserves the invariant. Obligation of a contract moves funds from available to obligated; release — through item cancellation, item expiry, contract termination, an approved drop-practice modification, or contract completion — moves them back. Disbursement moves funds from obligated to paid; recoupment payment moves them back. Advance issuance moves funds from obligated to paid; advance return moves them back. A pool's funds are never created or destroyed, only reclassified.

### 2.9. Monetary Precision, Rounding, and Score Precision

All monetary values are integer cents. Every multiplication that produces a monetary amount — a scheduled item amount, an estimated obligation line, an advance cap, a certified payment amount — rounds half-up to whole cents at the point the amount is computed (a fraction of one-half cent or greater rounds up), and rounded line amounts are summed without any re-rounding of the total.

Ranking scores are the one non-integer quantity in the system. The base score may be fractional — criterion weights such as 0.5 are legitimate — no rounding occurs during accumulation, and only the final capped score is rounded half-up to two decimal places. Rate and percentage inputs such as `standard_rate_cents`, `hu_rate_cents`, and `advance_cap_pct` preserve their input precision exactly as supplied.

### 2.10. Optimistic Concurrency Control

Three write operations guard against stale views of a parent aggregate through optimistic concurrency control; no other endpoint accepts or requires a version field.

- Approving a requested contract modification requires the request body field `expected_contract_version`, carrying the contract `version` the approver last observed. If the contract's current `version` has advanced since that observation — for example because a payment disbursement landed between the modification request and its adjudication — the approval is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). A second approval attempt carrying the pre-disbursement version fails even though the modification is still `REQUESTED` and the contract still `MODIFICATION_PENDING`.
- Rejecting a requested contract modification carries the same rule: `expected_contract_version` must equal the contract's current `version`, or the rejection itself is refused with `ERR_STALE_CONTRACT_VERSION` (HTTP 412) and the reviewer must re-read the contract before re-issuing.
- Editing a practice item's `planned_quantity` or `implementation_deadline` while its contract is still in drafting requires `expected_item_version` equal to the item's current `version`. An edit carrying an older version — meaning another edit has already landed, silently changing `scheduled_amount_cents` — is rejected with `ERR_STALE_ITEM_VERSION` (HTTP 412).

### 2.11. Segregation of Duties

Three custody boundaries run through the payment and compliance workflows, and the server enforces each by comparing the acting `X-User-ID` against a recorded counterpart. The payment officer who approves a payment request must not be the planner who certified the underlying practice item: the approver's `X-User-ID` is compared to the item's `certified_by_user_id`, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The quality-assurance officer recording a spot-check result must likewise differ from the certifying planner — a match again yields `ERR_SEGREGATION_OF_DUTIES` — and must additionally be the same officer who opened the check: the actor's `X-User-ID` must equal the spot check's `inspector_user_id`, or the recording is rejected with `ERR_INSPECTOR_MISMATCH` (HTTP 403). Finally, the officer who confirms a maintenance violation must not be the planner who reported it: confirmation compares the actor to the obligation's `reported_by_user_id`, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES`.

## 3. Business Logic & Workflows

### 3.1. Configuring a Program: Pools, Rates, and Ranking Criteria

A `ProgramAdmin` begins by creating a **Conservation Program**, supplying its `program_name`, the federal `fiscal_year`, the two-letter `state_code` it operates under, and the application window bounded by `window_start` and `window_end`. The window is closed at both ends: submissions are accepted at exactly `window_start` and at exactly `window_end`, and the deadline sweep closes the program only once the clock has passed `window_end`. Two optional knobs tune program behavior: `spot_check_modulus`, which defaults to 5 and controls how payment requests are sampled for mandatory spot checks (§3.7), and `advance_cap_pct`, which defaults to 0.5 — one-half — and caps the historically-underserved advance described in §3.6; the cap fraction must be greater than zero and no more than one. One program-creation rule protects applicants from ambiguous deadlines: for the same `state_code`, a new program's window must not intersect any existing program's window, and because the intervals are closed at both ends, windows that merely touch at a single instant still conflict — the new program is rejected with `ERR_WINDOW_OVERLAP` (HTTP 409). A new program starts in `SETUP` with its `ranking_run_count` at zero.

While the program remains in `SETUP`, the administrator builds its configuration tree. A **Funding Pool** is created with a `pool_type` — one of `GENERAL`, `HU_BEGINNING_FARMER`, `HU_SOCIALLY_DISADVANTAGED`, `HU_LIMITED_RESOURCE`, or `HU_VETERAN` — and an `allocated_cents` appropriation of at least 1 cent; a fresh pool starts with `obligated_cents` and `paid_cents` at zero and `available_cents` equal to the allocation. A **Payment Schedule Rate** prices one conservation practice: `practice_code` (one of `COVER_CROP`, `PRESCRIBED_GRAZING`, `WATERING_FACILITY`, `FENCE`, or `NUTRIENT_MANAGEMENT`, unique within the program — a second rate for the same code is rejected with `ERR_DUPLICATE_RATE`), a `unit` of `ACRE`, `FOOT`, or `EACH`, a `standard_rate_cents` of at least 1 cent per unit, an `hu_rate_cents` no lower than the standard rate, and a `lifespan_years` of at least 1 that drives the maintenance obligation of §3.5. A **Ranking Criterion** contributes a `criterion_code` unique within the program (duplicates are rejected with `ERR_DUPLICATE_CRITERION`), a strictly positive `weight` multiplier, and a `max_points` cap of at least 1. Creating any of these rows once the program has left `SETUP` is rejected with `ERR_PROGRAM_NOT_IN_SETUP` (HTTP 409).

Opening the program moves it from `SETUP` to `OPEN` and is allowed only once the configuration is minimally complete: at least one pool, at least one rate, and at least one ranking criterion must exist, or the attempt fails with `ERR_PROGRAM_INCOMPLETE_CONFIG` (HTTP 409). From `OPEN`, an administrator may close the window manually, moving the program to its terminal `CLOSED` state; the deadline sweep of §2.7 reaches the same state automatically once the clock passes `window_end`.

### 3.2. Producer Registration and the Application Window

Producers enter the system through staff-side registration: a `ProgramAdmin` or `ConservationPlanner` registers an **Applicant** with a `legal_name`, an `hu_category`, and the `parcel_ids` identifying the land parcels the producer controls. The category is one of `NONE`, `BEGINNING_FARMER`, `SOCIALLY_DISADVANTAGED`, `LIMITED_RESOURCE`, or `VETERAN`, defaulting to `NONE`; the derived flag `historically_underserved` is true whenever the category is anything other than `NONE`, and it drives both the higher payment rate of §3.4 and the advance-payment eligibility of §3.6.

With registration complete, the producer drafts an **Application**. The drafting payload names the target `program_id`, the `applicant_id` — which, because the drafter acts in the `Applicant` role, must equal the actor's `X-User-ID` or the request fails with `ERR_APPLICANT_NOT_OWNER` — the `parcel_id` the practices will apply to, a non-empty `planned_practices` list of practice-code-and-quantity pairs (an empty list is rejected with `ERR_INVALID_REQUEST`), and a `self_reported_answers` map of criterion codes to claimed points. Claimed points are clamped to the range from zero up to the criterion's `max_points`, and any answer key that names no criterion of the program is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A new application rests in `DRAFT`.

Submission moves the application from `DRAFT` to `SUBMITTED` and is the moment the program's gates bite. The program must be `OPEN` — a submission against a program in any other state, including one auto-closed by the sweep, fails with `ERR_PROGRAM_NOT_OPEN` (HTTP 409) — and the clock must not have passed `window_end`. Every practice code in `planned_practices` must have a payment schedule rate in the program, or submission fails with `ERR_RATE_NOT_FOUND` (HTTP 422). The `parcel_id` must be an element of the applicant's registered `parcel_ids`, or submission fails with `ERR_PARCEL_NOT_REGISTERED` (HTTP 422). A successful submission computes the application's `provisional_score` by running the ranking formula of §3.3 over the self-reported answers.

Until a contract exists, the producer retains an exit: withdrawal moves an application from `DRAFT`, `SUBMITTED`, or `SCREENED_IN` to `WITHDRAWN`, is available only to the owning applicant, and from any other state is rejected with `ERR_APPLICATION_NOT_WITHDRAWABLE` (HTTP 409).

### 3.3. Screening, Scoring, and the Selection Waterfall

Screening is the `ConservationPlanner`'s adjudication of a `SUBMITTED` application — any other state is rejected with `ERR_APPLICATION_NOT_SUBMITTED` (HTTP 409). The screening payload carries a `decision`. A decision of `SCREENED_OUT` moves the application to that terminal state with no further ceremony. A decision of `SCREENED_IN` requires a `verified_answers` payload — the planner's verified map of criterion codes to points — and triggers two computations. First, the verified answers are recorded and the ranking formula runs over them, storing the result as `ranking_score`; because planner-adjusted points usually differ from producer claims, the verified score generally differs from the `provisional_score` computed at submission. Second, the system prices the application: `estimated_obligation_cents` sums the planned practices, each priced as its quantity multiplied by the applicable rate — the schedule's `hu_rate_cents` when the applicant is historically underserved, `standard_rate_cents` otherwise — with each practice line rounded half-up to whole cents before the lines are summed, never the reverse.

The ranking formula itself is identical for both the provisional and verified variants; only the answer set differs. The base score sums, over every ranking criterion of the program, the criterion's `weight` multiplied by the smaller of the awarded points and the criterion's `max_points`; answers absent from the answer set contribute zero. A tier bonus is then keyed on the base alone: a base of at least 60 earns 10 bonus points, a base of at least 40 but below 60 earns 5, and a base below 40 earns nothing. Evaluation order is pinned — base first, tier lookup second, addition third, cap fourth — so the bonus is never re-derived from an already-bonused total. The final score is the lesser of 100 and the sum of base and bonus; per §2.9, no rounding occurs during accumulation and the final score is rounded half-up to two decimal places.

Once the window has closed, a `ProgramAdmin` runs the selection waterfall, which is permitted only while the program is `CLOSED` (otherwise `ERR_PROGRAM_NOT_CLOSED`, HTTP 409) and only once per program: `ranking_run_count` must still be zero, and a second invocation is rejected with `ERR_RANKING_ALREADY_RUN` (HTTP 409). The candidate set is every application in `SCREENED_IN`. Candidates are considered in descending `ranking_score` order, with ties broken by ascending `estimated_obligation_cents` and then by ascending `created_at`; the application `id` is never consulted as a tiebreaker. For each candidate, pool assignment proceeds as follows: a historically underserved applicant is first tried against the HU pool matching the applicant's category — a beginning farmer maps to `HU_BEGINNING_FARMER`, a socially disadvantaged producer to `HU_SOCIALLY_DISADVANTAGED`, a limited-resource producer to `HU_LIMITED_RESOURCE`, and a veteran to `HU_VETERAN` — and then against the `GENERAL` pool, while a non-HU applicant considers only the `GENERAL` pool. A pool fits when the application's `estimated_obligation_cents` is no greater than the pool's remaining availability; an exact fit succeeds.

Selection writes no pool balances. The waterfall instead carries a running shadow availability per pool, starting from each pool's `available_cents` at the beginning of the run and decremented by each selection, so that earlier selections within the same run constrain later ones; real reservation of funds happens later, at contract obligation. A candidate that fits moves to `SELECTED` with its `funded_pool_id` set to the assigned pool — a field that remains unset until this moment. A candidate that fits no pool becomes `NOT_SELECTED`, and is skipped rather than fatal: a later, smaller application may still find room. When the run completes, `ranking_run_count` advances to 1, and the run reports how many applications it considered (`ranked_count`), how many it funded (`selected_count`), and how many it turned away (`not_selected_count`).

### 3.4. Contract Drafting and Fund Obligation

A `ConservationPlanner` converts a funded application into a contract. The application must be `SELECTED` — any other state fails with `ERR_APPLICATION_NOT_SELECTED` (HTTP 409) — and exactly one contract may ever be created per application. Creation copies the application's `program_id` and `applicant_id` onto the contract and sets the contract's `pool_id` from the application's `funded_pool_id`; the application itself advances from `SELECTED` to `CONTRACTED`. The new contract rests in `DRAFT`, and its `paid_amount_cents` starts at zero.

While the contract is in `DRAFT`, the planner builds out its **Contract Practice Items**. Each item names a `practice_code`, a `planned_quantity` greater than zero, and an `implementation_deadline` by which certification must occur. Two consistency rules tie the item back to its source application: the practice code must appear among the application's `planned_practices` — otherwise `ERR_PRACTICE_NOT_IN_APPLICATION` (HTTP 422) — and the planned quantity must not exceed the quantity planned for that code in the application — otherwise `ERR_QUANTITY_EXCEEDS_APPLICATION` (HTTP 422). Creation resolves the program's rate row for the code into the item's `payment_schedule_rate_id`, copies the rate's `unit` onto the item, and snapshots the item's `applicable_rate_cents`: the schedule's `hu_rate_cents` if and only if the contract's applicant is historically underserved at the moment of item creation, otherwise `standard_rate_cents`. The snapshot is frozen forever afterward; later edits to the rate row never retrofit existing items. The item's `scheduled_amount_cents` is then its `planned_quantity` multiplied by the snapshotted rate, rounded half-up to whole cents. New items begin `PLANNED` on the certification dimension and `UNPAID` on the payment dimension — two parallel status dimensions carried on the same row — and the contract's `obligated_amount_cents` is recomputed as the sum of `scheduled_amount_cents` over its non-terminal items, those whose `certification_status` is not `CANCELLED`, `EXPIRED`, or `CERTIFICATION_REVOKED`. The per-item rounding happens inside each scheduled amount and the contract total is never re-rounded: the contract figure is a sum of rounded line values rather than the rounding of an unrounded sum, and the two can differ when a quantity-rate product lands on a fraction of a cent. Each such mutation — adding an item, editing one, obligating, and so on — increments the contract's `version`.

A planner may also revise a draft item's `planned_quantity` or `implementation_deadline`; the edit requires the item-version guard of §2.10 (`expected_item_version`, with `ERR_STALE_ITEM_VERSION` on a stale view), recomputes `scheduled_amount_cents` from the new quantity against the frozen rate snapshot, recomputes the contract's obligated total, and increments the item's `version`. Both item creation and item editing require the contract to be in `DRAFT`; once it has left drafting, either attempt fails with `ERR_CONTRACT_NOT_DRAFT` (HTTP 409).

Obligation is the `ProgramAdmin`'s act of reserving funds, moving the contract from `DRAFT` to `OBLIGATED` — and a second obligation attempt likewise meets `ERR_CONTRACT_NOT_DRAFT`. Two fiscal gates apply, evaluated under the ladder of §2.6: the contract must contain at least one practice item (`ERR_CONTRACT_EMPTY`, HTTP 409), and its `obligated_amount_cents` must be no greater than the contract pool's `available_cents` (`ERR_POOL_INSUFFICIENT_FUNDS`, HTTP 402) — an obligation that exactly consumes the available balance succeeds. On success, the pool's `obligated_cents` grows and its `available_cents` shrinks by the obligated amount, the application advances from `CONTRACTED` to its terminal `OBLIGATED` state, and the contract's `version` increments.

### 3.5. Installation, Certification, and the Practice Lifespan

Once funds are obligated, the producer implements the practices. Reporting an installation moves an item from `PLANNED` — or from `CERTIFICATION_FAILED`, the retry path — to `INSTALLED`, and is the owning applicant's action. Two guards apply: the contract must be `OBLIGATED` (a contract still drafting, under modification review, completed, or terminated yields `ERR_CONTRACT_NOT_PAYABLE`, HTTP 409), and the clock must not have passed the item's `implementation_deadline` (otherwise `ERR_DEADLINE_PASSED`, HTTP 409). From any certification state other than `PLANNED` or `CERTIFICATION_FAILED`, the report is rejected with `ERR_ITEM_NOT_INSTALLABLE` (HTTP 409). The report increments the item's `version`.

Certification belongs to the `ConservationPlanner` and moves an `INSTALLED` item to `CERTIFIED` — certifying or failing an item in any other state is rejected with `ERR_ITEM_NOT_INSTALLED` (HTTP 409). The certification payload carries `certified_quantity`, which must be at least 1 and no greater than the item's `planned_quantity`, or the certification fails with `ERR_CERTIFIED_QUANTITY_INVALID` (HTTP 422); until this moment the field remains unset. The same deadline guard as installation applies (`ERR_DEADLINE_PASSED` once the clock has passed `implementation_deadline`). A third guard enforces the practice-lifespan regime: because each certification opens a multi-year maintenance obligation on the parcel, certification is blocked when another obligation on the same parcel and practice code is `ACTIVE` or `VIOLATION_REVIEW` and its `end_date` falls strictly after the new certification instant. Obligation intervals are half-open — an existing obligation whose `end_date` is exactly the new certification instant does not block — and a genuine overlap is rejected with `ERR_OBLIGATION_OVERLAP` (HTTP 409).

Successful certification records `certified_quantity`, the certifying planner's `X-User-ID` as `certified_by_user_id`, and the logical-clock instant as `certified_at`, increments the item's `version`, and opens a **Maintenance Obligation** — exactly one per certification. The obligation copies the item's `contract_id`, `practice_item_id`, `parcel_id`, and `practice_code`, takes `start_date` equal to `certified_at`, computes `end_date` as `certified_at` plus `lifespan_years` times 365 days, and begins in `ACTIVE`. The interval is half-open: it covers `start_date` and runs up to but not including `end_date`, and the sweep of §2.7 marks the obligation `SATISFIED` once the clock reaches or passes `end_date` — at exactly `end_date` the obligation is already satisfied.

When an installation does not meet standards, the planner fails the certification, moving the item from `INSTALLED` to `CERTIFICATION_FAILED` and incrementing its `version`; the producer may then correct and report installation again, cycling back to `INSTALLED`.

Two system-driven endings close out items that stall. The expiry sweep of §2.7 moves an item from `PLANNED`, `INSTALLED`, or `CERTIFICATION_FAILED` to `EXPIRED` once the clock passes `implementation_deadline` — but never while the item's contract is under modification review, a freeze that keeps the extension-window rule of §3.8 meaningful at approval time, since an item whose deadline passes during review is still presented for adjudication and rejected with `ERR_EXTENSION_WINDOW_CLOSED` rather than silently expiring. Expiry releases the item's remaining pool obligation — its `scheduled_amount_cents` less the advance net outstanding on the item — returning those funds from obligated to available, and forces any advance on the item with money still outstanding into `RETURN_DUE` with its `expenditure_due_date` reset to the current clock. Cancellation is the other ending: an approved drop-practice modification cancels a `PLANNED` item, and contract termination cancels items in `PLANNED`, `INSTALLED`, or `CERTIFICATION_FAILED`, each cancellation releasing the remaining pool obligation in the same way. Cancellation and expiry never mutate the payment dimension: an item that reaches `CANCELLED` or `EXPIRED` stays `UNPAID` unless it already holds an advance (`ADVANCE_HELD`). Finally, a `CERTIFIED` item can be un-certified only through the spot-check failure cascade of §3.7, which moves it to `CERTIFICATION_REVOKED` and voids its maintenance obligation.

### 3.6. Historically Underserved Advance Payments

Producers in a historically underserved category may receive part of a practice's scheduled funding up front. Advance issuance is the `PaymentOfficer`'s action against a specific practice item of a specific contract, and five gates guard it, in the order of §2.6. The contract must be `OBLIGATED` (`ERR_CONTRACT_NOT_OBLIGATED`, HTTP 409). The item's `certification_status` must be `PLANNED` (`ERR_ITEM_NOT_PLANNED`, HTTP 409). The applicant must be historically underserved (`ERR_NOT_HISTORICALLY_UNDERSERVED`, HTTP 422). The item must never have had an advance before, in any status (`ERR_ADVANCE_ALREADY_ISSUED`, HTTP 409), and no advance anywhere on the contract may still have money outstanding (`ERR_ADVANCE_OUTSTANDING`, HTTP 409). Finally the requested `issued_cents` must be at least 1 cent and no greater than the advance cap: the program's `advance_cap_pct` multiplied by the item's `scheduled_amount_cents`, rounded half-up to whole cents — half the scheduled amount under the default cap. An advance of exactly the cap succeeds; one cent more is rejected with `ERR_ADVANCE_CAP_EXCEEDED` (HTTP 422).

Issuance moves the issued amount within the pool from obligated to paid — `obligated_cents` falls by `issued_cents` and `paid_cents` rises by the same amount — and moves the item's payment dimension from `UNPAID` to `ADVANCE_HELD`. The advance records `issued_at` as the current clock instant, computes its `expenditure_due_date` as exactly 90 days later, and opens with `applied_cents` and `returned_cents` at zero and `outstanding_cents` equal to `issued_cents`. Three accounting fields are bound by a standing invariant: the issued amount always equals the sum of the applied, returned, and outstanding portions.

The producer who will not spend the advance returns it, paying back exactly the outstanding amount in a single `amount_cents` payment — any other figure is rejected with `ERR_RETURN_AMOUNT_MISMATCH` (HTTP 422) — from either `ISSUED` or `RETURN_DUE` (any other state yields `ERR_ADVANCE_NOT_RETURNABLE`, HTTP 409). A full return increments `returned_cents` by the amount, drives the outstanding balance to zero, closes the advance (`CLOSED`, its terminal state), and moves the returned amount within the pool from paid back to obligated — reducing `paid_cents` and raising `obligated_cents` by the returned amount — with the returned amount held once more as pool obligation for the item, released later on the same terms as any other remaining obligation (§3.5, §3.7, §3.8); across an issue-and-full-return pair the pool's paid balance is unchanged net-net.

Advances left outstanding against the clock escalate on their own. The sweep of §2.7 moves an advance from `ISSUED` to `RETURN_DUE` once the clock passes `expenditure_due_date` with money still outstanding; the same transition is forced immediately when the item expires, when the contract is terminated, when a drop-practice modification removes the item, or when a disbursement leaves a residual outstanding balance. From `RETURN_DUE`, a second sweep fires once the clock passes thirty days beyond the due date with funds still outstanding: the advance moves to `ESCALATED` and the system spawns a **Recoupment Demand** for the outstanding amount, linking it through `advance_payment_id` and setting its `due_date` thirty days out. An escalated advance reaches `CLOSED` only when the linked demand is paid in full — the payment increments the advance's `returned_cents`, zeroes its outstanding balance, and reduces the pool's `paid_cents` by the amount recovered.

### 3.7. Payment Requests, Spot Checks, and the Revocation Cascade

Payment begins with the producer. The owning applicant requests payment against a certified practice item, supplying the `contract_id`, the `practice_item_id` — which must belong to that contract — a `documented_cost_cents` of at least 1 cent representing the producer's documented actual cost, and `documentation_refs`, the receipt and photo references that must number at least one (an empty list is rejected with `ERR_DOCUMENTATION_INCOMPLETE`, HTTP 422). The item must be `CERTIFIED` (`ERR_ITEM_NOT_CERTIFIED`, HTTP 409), the contract must be `OBLIGATED` (`ERR_CONTRACT_NOT_PAYABLE`), and the item must have no other payment request in flight — any existing request in `SUBMITTED`, `UNDER_REVIEW`, `APPROVED`, or `DISBURSED` blocks creation with `ERR_PAYMENT_REQUEST_ACTIVE` (HTTP 409).

Creation stamps three computed fields. The request inherits the contract's `program_id` and receives a `sequence_number`: one plus the count of all payment requests already existing for that program, regardless of status, assigned in creation order starting from 1. The `sampled` flag is set when the sequence number is an exact multiple of the program's `spot_check_modulus` — under the default modulus of five, requests numbered 5, 10, 15, and so on are sampled, while requests 4 and 6 are not — and a sampled request may not be disbursed until a spot check gates it through. The `computed_amount_cents` is the smaller of two figures: the item's `certified_quantity` multiplied by its snapshotted `applicable_rate_cents`, rounded half-up to whole cents; and the producer's `documented_cost_cents`.

Review then proceeds through the `PaymentOfficer`'s pipeline. Review moves a request from `SUBMITTED` to `UNDER_REVIEW` (any other state yields `ERR_REQUEST_NOT_SUBMITTED`, HTTP 409). From `UNDER_REVIEW` the officer either approves or rejects — both require that state, or `ERR_REQUEST_NOT_UNDER_REVIEW` (HTTP 409) results. Approval enforces the segregation boundary of §2.11: the approver must not be the planner who certified the item (`ERR_SEGREGATION_OF_DUTIES`), and a successful approval records the approver's `X-User-ID` as `reviewed_by_user_id`. Rejection moves the request to its terminal `REJECTED` state.

Disbursement converts an `APPROVED` request into cash — any other state meets `ERR_REQUEST_NOT_APPROVED` (HTTP 409) — behind two further gates. If the request was `sampled`, a spot check linked to this very request and standing in `PASSED` must exist; a pending or failed check satisfies nothing, and the disbursement is rejected with `ERR_SPOT_CHECK_REQUIRED` (HTTP 409). Independently, the disbursement must occur at or before the instant exactly 365 days after the item's `certified_at`; a later attempt fails with `ERR_CERTIFICATION_STALE` (HTTP 409).

A successful disbursement settles several accounts in a pinned order — computed amount first, advance offset second, cash movement third. The `advance_offset_cents` is the smaller of the computed amount and the outstanding balance of the item's advance, or zero when no advance exists; the `disbursed_amount_cents` is the computed amount minus that offset. Within the pool, `obligated_cents` falls by the item's `scheduled_amount_cents` less the advance net outstanding on the item, while `paid_cents` grows by the newly disbursed cash; because the full scheduled obligation is released while only the computed amount is paid, any gap between the scheduled estimate and the certified final amount returns to the pool's available balance here. The advance, when one exists, absorbs the offset into `applied_cents`; if that zeroes its outstanding balance the advance moves to `CLOSED`, otherwise it moves to `RETURN_DUE` with its `expenditure_due_date` reset to the current clock. The item's payment dimension moves to `PAID` — from `UNPAID` when no advance was outstanding, from `ADVANCE_HELD` when one was — its `paid_amount_cents` is set to the request's computed amount, and its `version` increments; the contract's `paid_amount_cents` grows by the same computed amount and the contract's `version` increments as well.

Spot checks are the audit instrument standing behind sampled disbursements. A `QualityAssuranceOfficer` opens one against a practice item, naming the `contract_id`, the `practice_item_id` (which must belong to that contract), and optionally a `payment_request_id` — required when the check gates a sampled disbursement, and required to belong to the referenced item when present. The item must be `CERTIFIED` at creation (`ERR_ITEM_NOT_CERTIFIED`); the opening officer is recorded as `inspector_user_id`, and the check begins in `PENDING`.

Recording the result belongs to the same officer who opened the check: the actor must equal `inspector_user_id` (`ERR_INSPECTOR_MISMATCH`, HTTP 403), must differ from the item's certifier (`ERR_SEGREGATION_OF_DUTIES`), and the check must still be `PENDING` (`ERR_SPOT_CHECK_NOT_PENDING`, HTTP 409). A `result` of `PASS` moves the check to `PASSED`. A `result` of `FAIL` requires a `failure_reason` — recording a failure without one is rejected with `ERR_INVALID_REQUEST` — and moves the check to `FAILED`, with consequences that depend on where the linked payment request stands. When the linked request is still `APPROVED` and pre-disbursement, the request simply stays `APPROVED`, but its disbursement remains blocked until a different `PASSED` spot check exists for it; a `FAILED` check satisfies no gate. When the linked request has already been `DISBURSED`, the failure fires a four-hop revocation cascade: the request itself moves from `DISBURSED` to `REVOKED`; the item's certification collapses from `CERTIFIED` to `CERTIFICATION_REVOKED` while its payment dimension falls from `PAID` to `RECOUPMENT_PENDING`, with the item's `version` incrementing; the item's maintenance obligation is voided, moving to `VOID`; and a recoupment demand is created for the revoked request's full `computed_amount_cents`, due thirty days out and linked through `payment_request_id`. Critically, the pool's funds are not restored at revocation time — they come back only when the producer pays the demand (§3.8).

### 3.8. Modifications, Contract Endings, and Recoupment

Circumstances change after obligation, and the modification workflow is the controlled valve. The owning applicant requests a modification with a `kind` of `EXTEND_DEADLINE`, `ADD_PRACTICE`, or `DROP_PRACTICE`, and the request requires the contract to be `OBLIGATED` (`ERR_CONTRACT_NOT_OBLIGATED`). The kind determines the payload: `practice_item_id` is required for `EXTEND_DEADLINE` and `DROP_PRACTICE`; `new_deadline` is required for `EXTEND_DEADLINE` and `ADD_PRACTICE`; and `new_practice_code` together with a strictly positive `new_quantity` are required for `ADD_PRACTICE` — a missing kind-specific field is rejected with `ERR_INVALID_REQUEST`. The requester's `X-User-ID` is recorded as `requested_by_user_id`, the modification begins in `REQUESTED`, and a successfully lodged request swings the contract from `OBLIGATED` to `MODIFICATION_PENDING`, incrementing the contract's `version`.

Some validation already bites at request time. For `EXTEND_DEADLINE`, the target item's `certification_status` must be `PLANNED`, `INSTALLED`, or `CERTIFICATION_FAILED` (`ERR_ITEM_NOT_EXTENDABLE`, HTTP 409), and the requested `new_deadline` must fall strictly after the item's current `implementation_deadline` and no more than 365 days beyond it (`ERR_EXTENSION_TOO_LONG`, HTTP 422). A request that fails validation leaves the contract in `OBLIGATED` — the swing to `MODIFICATION_PENDING` happens only for a well-formed request. While a contract stands in `MODIFICATION_PENDING` it is frozen: payment requests, advance issuance, certifications, and termination are all rejected against it, and the expiry sweep of §2.7 skips its items.

Adjudication belongs to the `ProgramAdmin`, and both branches require the modification to be `REQUESTED` (`ERR_MODIFICATION_NOT_REQUESTED`, HTTP 409), the contract to stand in `MODIFICATION_PENDING` (`ERR_CONTRACT_NOT_MODIFIABLE`, HTTP 409), and the stale-version guard of §2.10 — `expected_contract_version` matching the contract's current `version`, or `ERR_STALE_CONTRACT_VERSION` (HTTP 412). Approval re-evaluates the kind-specific rules against the world as it now stands. For `ADD_PRACTICE`, the new item's scheduled amount must fit the pool's `available_cents` (`ERR_POOL_INSUFFICIENT_FUNDS`). For `EXTEND_DEADLINE`, the item must still be in an extendable state (`ERR_ITEM_NOT_EXTENDABLE`), the clock must not have passed the item's current deadline (`ERR_EXTENSION_WINDOW_CLOSED`, HTTP 409 — reachable precisely because the sweep froze during review), and the `new_deadline` bounds are checked once more (`ERR_EXTENSION_TOO_LONG`). Approval then applies the kind's effect: an extension rewrites the item's `implementation_deadline` to `new_deadline` and increments the item's `version`; an addition creates a fresh practice item in `PLANNED` and `UNPAID` with the snapshot rate rule of §3.4, grows the contract's `obligated_amount_cents` by the new scheduled amount, and reserves the same amount in the pool (obligated up, available down); a drop cancels the item (`CANCELLED`), releases its remaining obligation — the scheduled amount less the advance net outstanding — back to the pool's available balance, and forces any advance on the item with money still outstanding into `RETURN_DUE` with its `expenditure_due_date` reset to the current clock. Either approval or rejection returns the contract to `OBLIGATED` and increments the contract's `version`; rejection additionally marks the modification `REJECTED`. Both modification terminal states — `APPROVED` and `REJECTED` — are final.

Two orderly endings close a contract. Completion moves an `OBLIGATED` contract to `COMPLETED` and demands a clean ledger, checked under the ladder of §2.6: every practice item must be terminal — either `CERTIFIED` with its payment dimension in `PAID` or `RECOUPED`, or else `CANCELLED` or `EXPIRED` — otherwise `ERR_ITEMS_NOT_FINAL` (HTTP 409); no advance of the contract may stand in `ISSUED`, `RETURN_DUE`, or `ESCALATED` (`ERR_ADVANCE_OUTSTANDING`); no payment request may be active in `SUBMITTED`, `UNDER_REVIEW`, or `APPROVED` (`ERR_PAYMENT_REQUEST_ACTIVE`); and no modification may be `REQUESTED` (`ERR_PENDING_MODIFICATION_EXISTS`, HTTP 409). On completion the contract's `version` increments and any residual obligation still held for the contract is released back to the pool, obligated falling and available rising by the same amount.

Termination is the disorderly ending, available from `DRAFT` and from `OBLIGATED` — a contract under modification review is frozen against termination — and always final at `TERMINATED`. Terminating an obligated contract is blocked while any of its payment requests stands in `DISBURSED` (`ERR_DISBURSED_PAYMENTS_EXIST`, HTTP 409), because disbursed money must be recovered through recoupment rather than written off. The termination then cascades: every item in `PLANNED`, `INSTALLED`, or `CERTIFICATION_FAILED` moves to `CANCELLED`, and each cancellation releases its remaining pool obligation back to available; every advance with money still outstanding is forced to `RETURN_DUE` with its `expenditure_due_date` reset to the current clock, its later escalation sweep spawning the recoupment demand; every non-terminal payment request — `SUBMITTED`, `UNDER_REVIEW`, or `APPROVED` — moves to `REJECTED`; any `REQUESTED` modification is likewise rejected; the application remains in `OBLIGATED` as the historical record; and the contract's `version` increments. Terminating a draft contract merely cancels its items and increments the version, touching no pool funds because none were ever obligated.

The compliance tail runs through maintenance obligations and recoupment demands. A `ConservationPlanner` who finds a certified practice unmaintained reports a violation against an `ACTIVE` obligation (`ERR_OBLIGATION_NOT_ACTIVE`, HTTP 409), moving it to `VIOLATION_REVIEW` and stamping `reported_by_user_id`. A `QualityAssuranceOfficer` then adjudicates from `VIOLATION_REVIEW` — both branches require that state, or `ERR_OBLIGATION_NOT_IN_REVIEW` (HTTP 409). Dismissal returns the obligation to `ACTIVE`, and the cycle may repeat. Confirmation moves it to its terminal `VIOLATION_CONFIRMED` state, enforces the segregation boundary of §2.11 — the confirmer must differ from the reporter, `ERR_SEGREGATION_OF_DUTIES` — and fires the financial consequence: when the item's `paid_amount_cents` is greater than zero, a recoupment demand is created for exactly that amount, linked through `maintenance_obligation_id` and due thirty days hence, and the item's payment dimension falls from `PAID` to `RECOUPMENT_PENDING`. Obligations also end quietly through the satisfaction sweep (`ACTIVE` to `SATISFIED` once the clock reaches `end_date`) or abruptly through the spot-check cascade (`ACTIVE` to `VOID` when the underlying certification is revoked).

A **Recoupment Demand** is the system's collectible instrument, and its amount is pinned to its source: a demand born of a revoked payment request carries that request's `computed_amount_cents`; one born of a confirmed maintenance violation carries the item's `paid_amount_cents` and is created only when that amount is positive; one born of advance escalation carries the advance's `outstanding_cents`. Whatever the source, `due_date` is set thirty days after creation, and the sweep moves an unpaid demand from `DEMANDED` to `ESCALATED` once the clock passes the due date. Payment is the producer's action and must cover exactly the demand's `amount_cents` in a single `amount_cents` payment — any other figure is rejected with `ERR_REPAYMENT_AMOUNT_MISMATCH` (HTTP 422) — from either `DEMANDED` or `ESCALATED` (any other state yields `ERR_DEMAND_NOT_PAYABLE`, HTTP 409). A paid demand restores the pool, reducing `paid_cents` by the recovered amount; moves the linked item from `RECOUPMENT_PENDING` to `RECOUPED`, the payment dimension's terminal state; and, when the demand was born of an advance, increments that advance's `returned_cents`, zeroes its outstanding balance, and closes the advance. `PAID` is the demand's only terminal state.

## 4. Endpoint Definitions

Operations that create a new resource — a program, pool, rate, criterion, applicant, application, contract, practice item, payment request, advance, modification, or spot check — return `201 Created`. Operations that modify an existing resource, including every state transition, edit, approval, rejection, disbursement, return, and payment, return `200 OK`, as do all reads. The table below is a summary only: request payloads, computed fields, side effects, and error conditions are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/eqip/programs` | Create a conservation program | ProgramAdmin |
| GET | `/eqip/programs` | List programs | Any |
| GET | `/eqip/programs/{id}` | Get one program | Any |
| POST | `/eqip/programs/{id}/open` | Open the application window | ProgramAdmin |
| POST | `/eqip/programs/{id}/close` | Close the application window | ProgramAdmin |
| POST | `/eqip/programs/{id}/run-ranking` | Run the ranking selection waterfall | ProgramAdmin |
| POST | `/eqip/programs/{id}/pools` | Create a funding pool | ProgramAdmin |
| GET | `/eqip/programs/{id}/pools` | List pools of a program | Any |
| GET | `/eqip/pools/{id}` | Get one pool's balances | Any |
| POST | `/eqip/programs/{id}/rates` | Create a payment schedule rate | ProgramAdmin |
| GET | `/eqip/programs/{id}/rates` | List payment schedule rates | Any |
| POST | `/eqip/programs/{id}/ranking-criteria` | Create a ranking criterion | ProgramAdmin |
| GET | `/eqip/programs/{id}/ranking-criteria` | List ranking criteria | Any |
| POST | `/eqip/applicants` | Register a producer | ProgramAdmin, ConservationPlanner |
| GET | `/eqip/applicants/{id}` | Get one applicant | Any |
| POST | `/eqip/applications` | Create a draft application | Applicant |
| GET | `/eqip/applications/{id}` | Get one application | Any |
| GET | `/eqip/applications` | List and filter applications | Any |
| POST | `/eqip/applications/{id}/submit` | Submit an application | Applicant |
| POST | `/eqip/applications/{id}/withdraw` | Withdraw an application | Applicant |
| POST | `/eqip/applications/{id}/screen` | Screen an application in or out | ConservationPlanner |
| POST | `/eqip/contracts` | Create a draft contract from a selected application | ConservationPlanner |
| GET | `/eqip/contracts/{id}` | Get one contract | Any |
| GET | `/eqip/contracts` | List and filter contracts | Any |
| POST | `/eqip/contracts/{id}/practice-items` | Add a practice item to a draft contract | ConservationPlanner |
| GET | `/eqip/contracts/{id}/practice-items` | List items of a contract | Any |
| POST | `/eqip/contracts/{id}/obligate` | Obligate contract funds | ProgramAdmin |
| POST | `/eqip/contracts/{id}/terminate` | Terminate a contract | ProgramAdmin |
| POST | `/eqip/contracts/{id}/complete` | Complete a contract | ProgramAdmin |
| GET | `/eqip/practice-items/{id}` | Get one practice item | Any |
| GET | `/eqip/practice-items` | List and filter practice items | Any |
| PATCH | `/eqip/practice-items/{id}` | Edit a draft item's quantity or deadline | ConservationPlanner |
| POST | `/eqip/practice-items/{id}/report-installed` | Report a practice installed | Applicant |
| POST | `/eqip/practice-items/{id}/certify` | Certify an installed practice | ConservationPlanner |
| POST | `/eqip/practice-items/{id}/fail-certification` | Fail certification of an installed practice | ConservationPlanner |
| POST | `/eqip/payment-requests` | Request payment for a certified item | Applicant |
| GET | `/eqip/payment-requests/{id}` | Get one payment request | Any |
| GET | `/eqip/payment-requests` | List and filter payment requests | Any |
| POST | `/eqip/payment-requests/{id}/review` | Begin review of a payment request | PaymentOfficer |
| POST | `/eqip/payment-requests/{id}/approve` | Approve a payment request | PaymentOfficer |
| POST | `/eqip/payment-requests/{id}/reject` | Reject a payment request | PaymentOfficer |
| POST | `/eqip/payment-requests/{id}/disburse` | Disburse an approved payment | PaymentOfficer |
| POST | `/eqip/contracts/{id}/advance-payments` | Issue a historically underserved advance | PaymentOfficer |
| GET | `/eqip/contracts/{id}/advance-payments` | List advances of a contract | Any |
| GET | `/eqip/advance-payments/{id}` | Get one advance | Any |
| GET | `/eqip/advance-payments` | List and filter advances | Any |
| POST | `/eqip/advance-payments/{id}/return` | Return an outstanding advance | Applicant |
| POST | `/eqip/contracts/{id}/modifications` | Request a contract modification | Applicant |
| GET | `/eqip/contracts/{id}/modifications` | List modifications of a contract | Any |
| GET | `/eqip/modifications/{id}` | Get one modification | Any |
| GET | `/eqip/modifications` | List and filter modifications | Any |
| POST | `/eqip/modifications/{id}/approve` | Approve a modification | ProgramAdmin |
| POST | `/eqip/modifications/{id}/reject` | Reject a modification | ProgramAdmin |
| POST | `/eqip/spot-checks` | Open a spot check | QualityAssuranceOfficer |
| GET | `/eqip/spot-checks/{id}` | Get one spot check | Any |
| GET | `/eqip/spot-checks` | List and filter spot checks | Any |
| POST | `/eqip/spot-checks/{id}/record-result` | Record a spot check result | QualityAssuranceOfficer |
| GET | `/eqip/maintenance-obligations/{id}` | Get one maintenance obligation | Any |
| GET | `/eqip/maintenance-obligations` | List and filter maintenance obligations | Any |
| POST | `/eqip/maintenance-obligations/{id}/report-violation` | Report a maintenance violation | ConservationPlanner |
| POST | `/eqip/maintenance-obligations/{id}/confirm-violation` | Confirm a maintenance violation | QualityAssuranceOfficer |
| POST | `/eqip/maintenance-obligations/{id}/dismiss-violation` | Dismiss a maintenance violation | QualityAssuranceOfficer |
| GET | `/eqip/recoupment-demands/{id}` | Get one recoupment demand | Any |
| GET | `/eqip/recoupment-demands` | List and filter recoupment demands | Any |
| POST | `/eqip/recoupment-demands/{id}/pay` | Pay a recoupment demand | Applicant |
| POST | `/_clock/set_current_utc` | Advance the logical clock and run the deadline sweep | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_APPLICANT_NOT_OWNER` | 403 Forbidden |
| `ERR_INSPECTOR_MISMATCH` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_POOL_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICANT_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_PRACTICE_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_ADVANCE_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_MODIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_SPOT_CHECK_NOT_FOUND` | 404 Not Found |
| `ERR_MAINTENANCE_OBLIGATION_NOT_FOUND` | 404 Not Found |
| `ERR_RECOUPMENT_DEMAND_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_NOT_IN_SETUP` | 409 Conflict |
| `ERR_PROGRAM_INCOMPLETE_CONFIG` | 409 Conflict |
| `ERR_PROGRAM_NOT_OPEN` | 409 Conflict |
| `ERR_PROGRAM_NOT_CLOSED` | 409 Conflict |
| `ERR_RANKING_ALREADY_RUN` | 409 Conflict |
| `ERR_APPLICATION_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_APPLICATION_NOT_SUBMITTED` | 409 Conflict |
| `ERR_APPLICATION_NOT_SELECTED` | 409 Conflict |
| `ERR_CONTRACT_NOT_DRAFT` | 409 Conflict |
| `ERR_CONTRACT_EMPTY` | 409 Conflict |
| `ERR_CONTRACT_NOT_OBLIGATED` | 409 Conflict |
| `ERR_CONTRACT_NOT_MODIFIABLE` | 409 Conflict |
| `ERR_CONTRACT_NOT_PAYABLE` | 409 Conflict |
| `ERR_ITEMS_NOT_FINAL` | 409 Conflict |
| `ERR_PENDING_MODIFICATION_EXISTS` | 409 Conflict |
| `ERR_ITEM_NOT_INSTALLABLE` | 409 Conflict |
| `ERR_ITEM_NOT_INSTALLED` | 409 Conflict |
| `ERR_ITEM_NOT_CERTIFIED` | 409 Conflict |
| `ERR_ITEM_NOT_EXTENDABLE` | 409 Conflict |
| `ERR_ITEM_NOT_PLANNED` | 409 Conflict |
| `ERR_REQUEST_NOT_SUBMITTED` | 409 Conflict |
| `ERR_REQUEST_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_REQUEST_NOT_APPROVED` | 409 Conflict |
| `ERR_ADVANCE_NOT_RETURNABLE` | 409 Conflict |
| `ERR_MODIFICATION_NOT_REQUESTED` | 409 Conflict |
| `ERR_SPOT_CHECK_NOT_PENDING` | 409 Conflict |
| `ERR_OBLIGATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_OBLIGATION_NOT_IN_REVIEW` | 409 Conflict |
| `ERR_DEMAND_NOT_PAYABLE` | 409 Conflict |
| `ERR_DISBURSED_PAYMENTS_EXIST` | 409 Conflict |
| `ERR_DUPLICATE_RATE` | 409 Conflict |
| `ERR_DUPLICATE_CRITERION` | 409 Conflict |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_OBLIGATION_OVERLAP` | 409 Conflict |
| `ERR_DEADLINE_PASSED` | 409 Conflict |
| `ERR_CERTIFICATION_STALE` | 409 Conflict |
| `ERR_SPOT_CHECK_REQUIRED` | 409 Conflict |
| `ERR_ADVANCE_ALREADY_ISSUED` | 409 Conflict |
| `ERR_ADVANCE_OUTSTANDING` | 409 Conflict |
| `ERR_PAYMENT_REQUEST_ACTIVE` | 409 Conflict |
| `ERR_EXTENSION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_RATE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_PARCEL_NOT_REGISTERED` | 422 Unprocessable Entity |
| `ERR_PRACTICE_NOT_IN_APPLICATION` | 422 Unprocessable Entity |
| `ERR_QUANTITY_EXCEEDS_APPLICATION` | 422 Unprocessable Entity |
| `ERR_CERTIFIED_QUANTITY_INVALID` | 422 Unprocessable Entity |
| `ERR_NOT_HISTORICALLY_UNDERSERVED` | 422 Unprocessable Entity |
| `ERR_ADVANCE_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DOCUMENTATION_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_EXTENSION_TOO_LONG` | 422 Unprocessable Entity |
| `ERR_RETURN_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REPAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_POOL_INSUFFICIENT_FUNDS` | 402 Payment Required |
| `ERR_STALE_CONTRACT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ITEM_VERSION` | 412 Precondition Failed |
