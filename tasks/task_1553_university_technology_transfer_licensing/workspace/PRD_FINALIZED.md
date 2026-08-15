# University Technology Transfer & Licensing API — Product Requirements Document

## 1. Introduction

A university technology transfer office (TTO) sits at the intersection of federal research compliance, patent prosecution spend, and multi-party commercialization revenue. Invention disclosures arrive from faculty, staff, and student inventors; the office must determine inventorship, decide whether to pursue patent protection, track prosecution costs on the docket, negotiate exclusive and non-exclusive licenses, collect royalties, and distribute the proceeds to inventors and their departments — all while honoring Bayh-Dole-style federal reporting obligations for government-funded inventions and conflict-of-interest rules when a startup spins out. Errors in any of these steps are expensive: a missed election-of-title deadline can cost the university title to the invention, an overlapping exclusive license invites litigation, and a mis-split distribution creates audit exposure.

This document specifies the University Technology Transfer & Licensing API, mounted under the `/tlo` prefix. The API governs the complete commercialization lifecycle — disclosure intake and inventorship determination, patentability and market assessment gating, the patent prosecution docket with per-cost tracking, license negotiation and milestone administration, royalty receipt and the distribution waterfall, startup formation with equity and conflict-of-interest management, and federal compliance reporting through license default and termination. A logical clock, administrable only by the platform, drives time-dependent behavior such as license activation, expiration, milestone overdue detection, and cure windows; the office's day-to-day actors are separated into distinct roles so that no individual can both prepare and certify the same artifact.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The recognized role values, spelled exactly, are `Inventor`, `TechTransferOfficer`, `LicensingManager`, `ComplianceOfficer`, `ComplianceDirector`, `FinanceOfficer`, `FinanceDirector`, and `SystemAdmin`. The pseudo-role `Any` appears in endpoint tables to indicate that any authenticated role may perform the operation (all read endpoints are open to every authenticated caller). When a caller attempts an operation reserved for another role, or fails an entity-backed ownership check, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `Inventor`, `X-User-ID` is the `id` of the acting `Inventor` record; ownership checks on any resource that references an inventor — such as confirming one's own roster entry or raising a dispute — compare the resource's inventor foreign key to `X-User-ID`, and the `submitter_inventor_id` of a newly submitted disclosure is captured from it. When `X-User-Role` is `TechTransferOfficer`, `LicensingManager`, `ComplianceOfficer`, `ComplianceDirector`, `FinanceOfficer`, `FinanceDirector`, or `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `prepared_by_user_id` on a distribution or compliance report, or as `certified_by_user_id` at certification time — but never compares it to any entity's `id` for ownership.

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter caps the number of returned items: it defaults to 10 when omitted, must be at least 1, and may not exceed 100. The `offset` parameter skips a number of items and defaults to 0. Every list response is sorted by `created_at` in ascending order, and the `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Money Conventions

Every resource in this API carries a system-managed `id` (a server-minted UUID rendered in its canonical dashed 8-4-4-4-12 hexadecimal form, such as `550e8400-e29b-41d4-a716-446655440000`, with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits), an `updated_at` timestamp refreshed on every mutation, and an integer `version` that increments by one with every mutation. Stateful resources additionally expose a `status` field whose exact enumeration values are given entity by entity in §3. All monetary amounts are integer cents — fields ending in `_cents` — and all rates, shares, and equity stakes are integer basis points (ten-thousandths of a whole; 10000 basis points equals one hundred percent). Where a calculation produces a fractional cent, the system rounds half up to the nearest integer cent at the steps the business rules specify; integer-cents arithmetic otherwise needs no rounding. Datetime fields are ISO 8601 UTC and, unless stated otherwise, compared at second precision.

### 2.5. The Logical Clock and Time-Driven Sweeps

The system runs on a logical clock rather than wall-clock time. At startup, before any administrative action, the logical clock reads exactly 2026-08-01T00:00:00Z. A `SystemAdmin` advances it by supplying a target instant via `to_iso8601`. Throughout the API, path parameters are named `departmentId`, `inventorId`, `disclosureId`, `entryId`, `disputeId`, `applicationId`, `startupId`, `planId`, `licenseId`, `milestoneId`, `reportId`, and `distributionId`, and each binds to the `id` of the corresponding resource. Advancing the clock triggers a license sweep: every `EXECUTED` license whose `effective_date` has been reached transitions to `ACTIVE`, and every `EXECUTED` or `ACTIVE` license whose `expiration_date` has been reached transitions to `EXPIRED`. The sweep response reports the new clock value together with the lists of activated and expired license identifiers. All time-dependent rules in §3 — overdue milestones, cure windows, reporting due dates, COI coverage windows — evaluate against this logical clock, never against the server's wall clock.

### 2.6. Validation Order and Request Integrity

Inbound requests are validated against an ordered pipeline, and the first failure encountered determines the response. The pipeline runs: first, authentication headers (§2.1, `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, role and ownership authorization (`ERR_FORBIDDEN`); third, left-to-right existence of path identifiers (the appropriate not-found error, §2.7); fourth, request-body schema conformance — required fields present, enum membership valid, integer ranges respected, unknown payload fields rejected — with `ERR_INVALID_REQUEST`; fifth, state-machine legality (the state errors of §5, each HTTP 409); sixth, segregation-of-duties and compliance gates (`ERR_SEGREGATION_OF_DUTIES`, `ERR_TITLE_NOT_ELECTED`, `ERR_COI_COVERAGE_REQUIRED`); seventh, cross-entity referential usability (roster membership, federal-funding eligibility, pursued-patent prerequisites, the write-off review block, duplicate roster inventors — HTTP 422); eighth, intra-aggregate constraints such as share totals and window overlaps; ninth, clock-dependent windows; and last, fiscal floors — notably the exclusive-license upfront floor. Because schema validation precedes state checks, a malformed body is always `ERR_INVALID_REQUEST` even when the target is also in the wrong state; because fiscal floors come last, an exclusive license that fails both the overlap check and the upfront floor surfaces the overlap error.

### 2.7. Nested Resource Retrieval

Endpoints that address nested resources validate path identifiers strictly left to right, rejecting with the not-found error that corresponds to the first nonexistent identifier. A request naming a disclosure and a milestone beneath it on a nonexistent disclosure yields `ERR_DISCLOSURE_NOT_FOUND` before any milestone lookup occurs; a well-formed disclosure with a missing milestone yields `ERR_MILESTONE_NOT_FOUND`. The same discipline applies to entries, disputes, applications, costs, startups, plans, licenses, reports, distributions, and compliance reports, each of which has its own dedicated not-found identifier listed in §5.

### 2.8. Optimistic Concurrency Control

Three write operations require an explicit optimistic-concurrency token. Finalizing inventorship on a disclosure requires `expected_disclosure_version`, carrying the client's last-observed `version` of that disclosure. Executing a license requires `expected_license_version` against the license's current `version`. Approving a royalty distribution requires `expected_distribution_version` against the distribution's current `version`. In each case a mismatch — meaning the entity's version has advanced since the client last read it, for example because a dispute was raised, a counter round superseded terms, or a recalculation refreshed pool figures — is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the entity before retrying. No other endpoint accepts or requires a version field.

### 2.9. Prosecution Cost Ledger and the Write-Off Review Threshold

Patent prosecution spend is tracked as an auditable ledger of `PatentCost` rows beneath each application. Each row carries an `amount_cents` (strictly positive), a `reimbursed_amount_cents` that starts at 0 and rises only when approved distributions offset costs, and a `reimbursement_status` of `UNREIMBURSED`, `REIMBURSED`, or `WRITTEN_OFF`; a row is `REIMBURSED` exactly when its `reimbursed_amount_cents` equals its `amount_cents`. Two rollups derive from this ledger. On each application, `total_cost_cents` is the sum of `amount_cents` over all of its cost rows regardless of status, and `unreimbursed_cost_cents` sums the outstanding remainder — the difference between `amount_cents` and `reimbursed_amount_cents` — over rows still `UNREIMBURSED`. The same aggregation rolls up to the disclosure across all of its applications, alongside `written_off_cost_cents`, which sums full `amount_cents` over rows that are `WRITTEN_OFF`. Whenever these rollups are recomputed — at cost creation, at distribution approval, at distribution cancellation, and during the abandon and license-termination cascades — the disclosure's `cost_writeoff_review_required` flag is re-evaluated: it is true whenever `written_off_cost_cents` reaches at least 5,000,000 cents (fifty thousand dollars of written-off prosecution spend). While the flag is true, opening a new patent application on that disclosure is refused with `ERR_COST_REVIEW_REQUIRED`; a `TechTransferOfficer` clears the block through the cost-review clear action, and clearing while the flag is false is refused with `ERR_COST_REVIEW_NOT_REQUIRED`. The clear is sticky until the next recompute once again crosses the threshold.

### 2.10. Segregation of Duties

Two financial-compliance artifacts enforce maker-checker separation. A royalty distribution records the `X-User-ID` of the preparing `FinanceOfficer` as `prepared_by_user_id`, and approval by a `FinanceDirector` whose `X-User-ID` equals that value is refused with `ERR_SEGREGATION_OF_DUTIES`. A federal compliance report likewise records its preparer, and certification by a `ComplianceDirector` whose `X-User-ID` equals the report's `prepared_by_user_id` is refused with the same error. These checks are distinct from role authorization: both actors hold the correct roles, and the refusal turns specifically on identity equality.

## 3. Business Logic & Workflows

### 3.1. Disclosure Intake and Inventorship Determination

Platform provisioning precedes any commercialization activity. A `SystemAdmin` creates each department with its `name` and `college_name`; the department's `distribution_pool_cents` ledger begins at 0. A `SystemAdmin` likewise provisions each inventor. An `Inventor` — whose profile carries `full_name`, `email`, a home `department_id`, and an `appointment_type` of `FACULTY`, `STAFF`, or `STUDENT` — opens the commercialization pipeline by submitting an invention disclosure with a `title`, a technical `description`, and a `funding_source` of `FEDERAL`, `NON_FEDERAL`, or `MIXED`. When the funding source is `FEDERAL` or `MIXED`, the `federal_agency` and `grant_number` are both required; when it is `NON_FEDERAL`, they remain null. If the invention has already been publicly disclosed, the submitter records that date in `public_disclosure_date`, which later drives the patent bar date used in election-of-title timing. The server stamps the new disclosure with `submitter_inventor_id` taken from the caller's `X-User-ID`, initializes both cost rollups to zero, and places the disclosure in `INVENTORSHIP_REVIEW`.

A `TechTransferOfficer` then builds the inventorship roster by adding `DisclosureInventor` entries, each naming an `inventor_id` and a `share_bp` between 1 and 10000 basis points. Roster additions are permitted only while the disclosure is in `INVENTORSHIP_REVIEW`; attempting one against a disclosure in any other state is refused with `ERR_DISCLOSURE_INVALID_STATE`. The same inventor may not appear twice on one disclosure's roster — a duplicate attempt is refused with `ERR_DUPLICATE_INVENTOR`. Each roster addition creates an entry in `PENDING` confirmation status and increments the disclosure's `version` by 1.

Each named inventor then confirms their own entry. Confirmation requires the entry to be `PENDING`, the disclosure still in `INVENTORSHIP_REVIEW`, and the caller's `X-User-ID` to equal the entry's `inventor_id` — confirming someone else's entry is `ERR_FORBIDDEN`, a non-`PENDING` entry is `ERR_ENTRY_NOT_CONFIRMABLE`, and a disclosure outside review is `ERR_DISCLOSURE_INVALID_STATE`. A successful confirm stamps `confirmed_at` with the current clock and moves the entry to `CONFIRMED`.

Any rostered inventor may instead dispute an entry's share by supplying a `reason`. The entry being disputed must be in `PENDING` or `CONFIRMED` status — anything else yields `ERR_ENTRY_NOT_DISPUTABLE` — and the disputing caller must be an inventor on that disclosure's roster, else `ERR_FORBIDDEN`. A dispute cascades: the entry moves to `DISPUTED` (and if it had been `CONFIRMED`, its `confirmed_at` is cleared), a new `InventorshipDispute` is created in `OPEN` status recording the `disclosure_id`, the disputed `entry_id`, and `raised_by_inventor_id` taken from the caller, and the disclosure itself moves from `INVENTORSHIP_REVIEW` to `INVENTORSHIP_DISPUTED` with its `version` incremented by 1.

Disputes are adjudicated by a `TechTransferOfficer`, who resolves an `OPEN` dispute — resolving a dispute not in `OPEN` status yields `ERR_DISPUTE_NOT_OPEN` — by supplying `resolution_notes` and a complete `adjusted_shares` vector. The vector must name every roster entry exactly once, and its `share_bp` values must sum to exactly 10000 basis points; otherwise the resolve is refused with `ERR_SHARE_SUM_INVALID`. Resolution overwrites each entry's `share_bp` from the vector, resets every entry's `confirmation_status` to `PENDING`, clears every `confirmed_at`, marks the dispute `RESOLVED` with its `resolution_notes` stored, returns the disclosure to `INVENTORSHIP_REVIEW`, and increments the disclosure's `version` by 1. The roster then re-confirms under the adjusted shares.

Once every entry is `CONFIRMED`, the officer finalizes inventorship. Finalization is defined only while the disclosure is in `INVENTORSHIP_REVIEW` and requires at least one roster entry with all entries `CONFIRMED`; a disclosure in the wrong state, an empty roster, or any unconfirmed entry yields `ERR_INVENTORSHIP_NOT_FINALIZABLE`. The `share_bp` values must sum to exactly 10000 basis points, with a violation refused as `ERR_SHARE_SUM_INVALID`. The request must also carry `expected_disclosure_version` matching the disclosure's current `version`; this version check is evaluated before the finalizability conditions above, so if a dispute cycle has advanced the version since the officer last read the disclosure, the finalize is rejected with `ERR_STALE_VERSION` (HTTP 412) even though the dispute has also moved the disclosure out of `INVENTORSHIP_REVIEW`. A successful finalize moves the disclosure to `INVENTORSHIP_CONFIRMED` and increments its `version` by 1.

### 3.2. Assessment Gating and the Patent Decision

With inventorship confirmed, a `TechTransferOfficer` records the office's assessment, supplying a `patentability_rating` and a `market_rating`, each of `HIGH`, `MEDIUM`, or `LOW`, optionally accompanied by `assessment_notes`. Recording the assessment requires the disclosure to be in `INVENTORSHIP_CONFIRMED` — any other state yields `ERR_DISCLOSURE_INVALID_STATE` — and moves it to `UNDER_ASSESSMENT` with the ratings stored.

From `UNDER_ASSESSMENT` the officer records a `decision`, optionally with a `rationale`. Three outcomes exist. A `PURSUE_PATENT` decision is gated: both the `patentability_rating` and the `market_rating` must be `HIGH` or `MEDIUM`, and if either is `LOW` the decision is refused with `ERR_ASSESSMENT_GATE_FAILED`; success moves the disclosure to `PATENT_PURSUED`. A `WAIVE_TO_INVENTORS` decision moves the disclosure to the terminal `WAIVED_TO_INVENTORS` state, releasing the invention to the inventors. A `SHELF` decision moves it to the terminal `SHELVED` state. Any decision attempted from a state other than `UNDER_ASSESSMENT` is refused with `ERR_DISCLOSURE_INVALID_STATE`. Only a `PATENT_PURSUED` disclosure supports downstream commercialization: creating a patent application, forming a startup, or opening a license on a disclosure not in `PATENT_PURSUED` is refused with `ERR_DISCLOSURE_INVALID_STATE`.

### 3.3. The Patent Prosecution Docket

On a `PATENT_PURSUED` disclosure, a `TechTransferOfficer` opens a patent application by supplying the attorney `docket_number`, an `application_type` of `PROVISIONAL`, `NON_PROVISIONAL`, or `PCT`, and a `filed_date`; the application begins in `FILED`. Two additional gates apply at creation. First, the federal gate: when the disclosure's funding is `FEDERAL` or `MIXED` and the application type is `NON_PROVISIONAL` or `PCT`, the disclosure must already have an election-of-title compliance report whose status is `SUBMITTED` or `AGENCY_ACCEPTED` — otherwise creation is refused with `ERR_TITLE_NOT_ELECTED`. Second, the write-off gate: if the disclosure's `cost_writeoff_review_required` flag is true, creation is refused with `ERR_COST_REVIEW_REQUIRED` until the block is cleared.

Prosecution then proceeds as a cyclic docket. An office action moves an application from `FILED` to `OFFICE_ACTION_RECEIVED`, and — because office actions recur — also from `RESPONSE_FILED` back to `OFFICE_ACTION_RECEIVED`. Recording a response via its `response_date` moves an application from `OFFICE_ACTION_RECEIVED` to `RESPONSE_FILED`. A grant, recorded with its `grant_date`, is reachable from `FILED` or `RESPONSE_FILED` and lands in the terminal `GRANTED` state. Every prosecution event validates the application's current status and refuses out-of-order events with `ERR_PATENT_INVALID_STATE`; each event payload is a single date — `received_date` for an office action, `response_date` for a response, `grant_date` for a grant.

Costs accrue against the application as individual `PatentCost` rows, each stamped with the owning `patent_application_id` and carrying a `cost_type` of `FILING_FEE`, `ATTORNEY_FEE`, `MAINTENANCE_FEE`, or `TRANSLATION_FEE`, a strictly positive `amount_cents`, and an `incurred_date`. Recording a cost immediately recomputes the application's and the disclosure's cost rollups per §2.9.

Abandonment is reachable from `FILED`, `OFFICE_ACTION_RECEIVED`, or `RESPONSE_FILED` — any other state yields `ERR_PATENT_INVALID_STATE` — and lands in the terminal `ABANDONED` state. Abandoning an application triggers a three-hop write-off cascade. In the first hop, every cost row of that application whose `reimbursement_status` is `UNREIMBURSED` and whose `reimbursed_amount_cents` is still 0 flips to `WRITTEN_OFF`; partially reimbursed rows are deliberately not written off. In the second hop, each write-off recomputes the disclosure's cost rollups, so `unreimbursed_cost_cents` drops and `written_off_cost_cents` rises by each row's full `amount_cents`. In the third hop, if the recomputed `written_off_cost_cents` has reached at least 5,000,000 cents, the disclosure's `cost_writeoff_review_required` flips to true, blocking new patent applications on the disclosure until the office clears the review.

### 3.4. Startup Formation, Equity, and Conflict-of-Interest Management

A `TechTransferOfficer` may form a startup around a `PATENT_PURSUED` disclosure by supplying the company `name`, a `founded_date`, and an `equity_model` of `FIXED` or `ANTI_DILUTION`; the startup begins in `INCORPORATION` with `equity_issued` false and `university_equity_bp` unset. The chosen `equity_model` selects which calculation variant will later price the university's stake.

Because inventors founding companies pose conflicts of interest, a `ComplianceOfficer` files a management plan for each conflicted inventor, naming the `inventor_id`, a coverage window from `coverage_start` (inclusive) to `coverage_end` (exclusive, and strictly after the start), and the `management_plan_text`. The named inventor must be on the roster of the startup's disclosure, else the filing is refused with `ERR_INVENTOR_NOT_ON_DISCLOSURE`. New plans enter `SUBMITTED` status.

A `ComplianceDirector` adjudicates. Approval requires the plan to be `SUBMITTED` — anything else yields `ERR_COI_NOT_REVIEWABLE` — and the startup must not be `DISSOLVED`, else `ERR_STARTUP_INVALID_STATE`. Approval also re-checks the coverage window against every other `APPROVED` plan for the same startup and inventor: because windows are half-open, two plans overlap exactly when each starts before the other ends, and an overlap refuses the approval with `ERR_COI_WINDOW_OVERLAP`. Rejection stores a `rejection_reason` and moves the plan to `REJECTED`. A rejected plan is not dead: a `ComplianceOfficer` may revise it with new `coverage_start`, `coverage_end`, or `management_plan_text` values, which returns it to `SUBMITTED` and clears the `rejection_reason`; revision is defined only from `REJECTED` — otherwise `ERR_COI_NOT_REVISABLE` — and the revised window must not half-open overlap any `SUBMITTED` or `APPROVED` plan for the same startup and inventor, on pain of `ERR_COI_WINDOW_OVERLAP`.

Issuing the university's equity moves a startup from `INCORPORATION` to `EQUITY_ISSUED`, sets `equity_issued` true, and computes `university_equity_bp`. Issue-equity is gated on live conflict coverage: at least one `APPROVED` plan for this startup must have a window covering the current clock — `coverage_start` at or before the clock and `coverage_end` strictly after it — or the issuance is refused with `ERR_COI_COVERAGE_REQUIRED`; issuing from any status other than `INCORPORATION` yields `ERR_STARTUP_INVALID_STATE`. The equity computation follows the startup's chosen variant. Under `FIXED`, the university receives a flat 500 basis points regardless of valuation; the payload's `post_money_valuation_cents` is ignored. Under `ANTI_DILUTION`, the request must supply `post_money_valuation_cents` greater than 0 (its absence is `ERR_INVALID_REQUEST`); the raw stake is 800 basis points scaled by the ratio of a 1,000,000,000-cent base valuation to the supplied post-money valuation, the raw value is floored to an integer number of basis points, and the result is clamped to a floor of 200 basis points and a cap of 1500 basis points. Both clamps are genuinely reachable: a post-money valuation above roughly 2.67 billion dollars drives the raw figure below the floor, and one below roughly 533 million dollars drives it above the cap. The two variants answer the same question with different numbers whenever the anti-dilution formula yields anything other than 500.

Dissolution moves a startup from `INCORPORATION` or `EQUITY_ISSUED` to the terminal `DISSOLVED` state — any other state yields `ERR_STARTUP_INVALID_STATE` — and cascades to the conflict plans: every plan of that startup in `SUBMITTED` or `APPROVED` status moves to `TERMINATED`.

### 3.5. License Negotiation, Execution, and the Exclusivity Window

A `LicensingManager` opens a license negotiation on a `PATENT_PURSUED` disclosure by supplying the `licensee_name`, an `exclusivity` of `EXCLUSIVE` or `NON_EXCLUSIVE`, the `effective_date` and `expiration_date` (which must be strictly later), a `royalty_rate_bp` between 100 and 2000 basis points, a `minimum_annual_royalty_cents` of at least 0, and an `upfront_fee_cents` of at least 0. Optionally the license links to a startup on the same disclosure via `startup_id`, which triggers the conflict-of-interest coverage gate at execution and the startup-linked inventor-share reduction at distribution time. A new license begins in `IN_NEGOTIATION`.

Negotiation proceeds in counter rounds. A counter by the `LicensingManager` toggles the license between `IN_NEGOTIATION` and `COUNTERED` — countering from either state is legal, from any other state it is `ERR_LICENSE_NOT_NEGOTIABLE` — overwriting whichever of `royalty_rate_bp`, `minimum_annual_royalty_cents`, `upfront_fee_cents`, or `expiration_date` appear in the payload and incrementing the license's `version` by 1 each round.

Execution moves the license from `IN_NEGOTIATION` or `COUNTERED` to `EXECUTED`; from any other state it is `ERR_LICENSE_NOT_EXECUTABLE`. Execution carries five checks. First, optimistic concurrency: the request must carry `expected_license_version` matching the license's current `version`; if counter rounds have advanced the version since the client last read the terms, execution is rejected with `ERR_STALE_VERSION` (HTTP 412) so a client never signs terms it has not seen. Second, when a `startup_id` is linked, an `APPROVED` conflict-of-interest plan for that startup must cover the current clock, else `ERR_COI_COVERAGE_REQUIRED`. Third, for an `EXCLUSIVE` license, the closed interval from `effective_date` through `expiration_date` — both ends inclusive — must not intersect the corresponding closed interval of any other `EXECUTED`, `ACTIVE`, or `DEFAULT_NOTICE` exclusive license on the same disclosure; an intersection is `ERR_EXCLUSIVE_OVERLAP`. Fourth — checked last, after every other execution gate — an `EXCLUSIVE` license must carry an `upfront_fee_cents` of at least 500,000 cents, else `ERR_UPFRONT_BELOW_FLOOR` (HTTP 402). Successful execution increments the license's `version` by 1.

Thereafter the logical clock governs activation and expiry per §2.5: an `EXECUTED` license becomes `ACTIVE` once the clock reaches its `effective_date`, and an `EXECUTED` or `ACTIVE` license becomes `EXPIRED` once the clock reaches its `expiration_date`. Both `TERMINATED` and `EXPIRED` are terminal.

### 3.6. Milestones, Default, and Termination

The `LicensingManager` attaches milestone terms to a license — each stamped with the owning `license_id` — supplying a `description`, a `due_date`, and an `amount_cents` of at least 0; milestones begin `PENDING`, and a `PENDING` milestone whose `due_date` has passed relative to the current clock is considered overdue.

Marking a milestone achieved requires the milestone to be `PENDING` — else `ERR_MILESTONE_NOT_PENDING` — the license to be `EXECUTED` or `ACTIVE` — else `ERR_LICENSE_NOT_ACTIVE` — and the current clock to be at or before the milestone's `due_date`; achieving after the due date is refused with `ERR_MILESTONE_OVERDUE`. Success moves the milestone to `ACHIEVED`. Waiving a milestone stores a `waiver_reason` and moves it to `WAIVED`; waiver likewise requires a `PENDING` milestone, but is permitted while the license is `ACTIVE` or in `DEFAULT_NOTICE`.

When a licensee falls behind, the `LicensingManager` declares default, supplying a `reason`. Declaration requires the license to be `ACTIVE` — else `ERR_LICENSE_NOT_ACTIVE` — and at least one `PENDING` milestone whose `due_date` precedes the current clock; without such grounds the declaration is refused with `ERR_NO_DEFAULT_GROUNDS`. A declared default moves the license to `DEFAULT_NOTICE`, stamps `default_notice_date` with the current clock, and computes a `cure_deadline` sixty days later.

From `DEFAULT_NOTICE` two exits exist. Curing returns the license to `ACTIVE` and clears both `default_notice_date` and `cure_deadline`; it requires the license to be in `DEFAULT_NOTICE` — else `ERR_LICENSE_NOT_IN_DEFAULT` — and the current clock to be at or before the `cure_deadline`, else `ERR_CURE_PERIOD_EXPIRED`. Termination moves the license to the terminal `TERMINATED` state and requires the clock to be strictly past the `cure_deadline`; terminating at or before it is refused with `ERR_CURE_PERIOD_ACTIVE`, and terminating from any state other than `DEFAULT_NOTICE` is `ERR_LICENSE_NOT_TERMINABLE`. An optional `termination_reason` may accompany the request.

Termination fires a three-hop cascade. In the first hop, every `PENDING` milestone of the license moves to `CANCELLED`, and every royalty report in `SUBMITTED` or `ACCEPTED` status moves to `VOIDED`. In the second hop, each report voided in the first hop that has a distribution in `CALCULATED` or `APPROVED` status has that distribution moved to `CANCELLED`, and voiding an `ACCEPTED` report recomputes the license's cumulative rollups. In the third hop, each distribution that had been `APPROVED` when cancelled reverses its recorded cost applications exactly — every affected cost row's `reimbursed_amount_cents` is reduced by the cents originally applied to it, and a row returning to 0 flips from `REIMBURSED` back to `UNREIMBURSED` — after which the disclosure's cost rollups are recomputed.

### 3.7. Royalty Reporting and Acceptance Pricing

Once a license is in force, the `LicensingManager` submits periodic royalty reports, each with a `period_start` (inclusive), a `period_end` (exclusive, strictly after the start), and `reported_sales_cents` of at least 0. Report periods on one license may not half-open overlap any existing non-`VOIDED` report period on that license; an overlapping submission is refused with `ERR_REPORT_PERIOD_OVERLAP`. New reports begin `SUBMITTED`.

Acceptance by a `FinanceOfficer` prices the report and moves it from `SUBMITTED` to `ACCEPTED` — accepting a report in any other state is `ERR_REPORT_NOT_ACCEPTABLE`. Acceptance computes three figures. First, the earned royalty is tiered against cumulative sales. Let the cumulative base be the sum of `reported_sales_cents` over all of this license's other reports in `ACCEPTED` or `PAID` status, excluding the report being priced (acceptance processes reports in chronological order, and a late-accepted report still prices against the full current accepted-and-paid set). The tier-one rate is the license's `royalty_rate_bp`; the tier-two rate is half of that, floored to an integer number of basis points. The tier-one capacity is 100,000,000 cents of cumulative sales: the portion of this report's sales priced at tier one is the smaller of the report's `reported_sales_cents` and the remaining headroom between the cumulative base and that capacity — zero once the base has reached the capacity, and sales landing exactly at the cap still price at tier one, since the cap is an inclusive ceiling. The remainder of the report prices at tier two. Each tier's amount is the portion multiplied by its rate in basis points, divided by 10000, rounded half up to integer cents, and `earned_royalty_cents` is the sum of the two already-rounded tier amounts — rounding each portion first and then summing, never summing raw values and rounding once.

Second, acceptance computes the annual minimum true-up. License years are 365-day half-open intervals counted from the `effective_date`: year one runs from the effective date up to 365 days later, year two from there up to day 730, and so on. A report is year-closing when its `period_end` falls in a later license year than its `period_start` — that is, when the number of whole 365-day periods elapsed between the effective date and the period end exceeds the number elapsed between the effective date and the period start. A report that is not year-closing owes no true-up: `true_up_cents` is 0. A year-closing report owes the shortfall of its year's earnings against the annual minimum: sum `earned_royalty_cents` over this license's `ACCEPTED` and `PAID` reports whose periods lie entirely within the closing year — including this report's just-computed earned figure — and `true_up_cents` is the amount by which the license's `minimum_annual_royalty_cents` exceeds that sum, or 0 if there is no shortfall. The minimum applies in full to any crossed year, even a partial one; there is no proration. Third, `accepted_royalty_cents` is the sum of `earned_royalty_cents` and `true_up_cents`, and the license's cumulative rollups are recomputed: `cumulative_sales_cents` sums `reported_sales_cents` over the license's `ACCEPTED` and `PAID` reports, and `cumulative_royalty_cents` sums their `accepted_royalty_cents`.

### 3.8. The Distribution Waterfall and Share Splits

For an `ACCEPTED` report with no existing distribution, a `FinanceOfficer` calculates the distribution; a report not in `ACCEPTED` status, or one that already has a distribution, is refused with `ERR_REPORT_NOT_ACCEPTABLE` — at most one distribution ever exists per report, and the distribution's `royalty_report_id` records which report it belongs to. Calculation snapshots the report's `accepted_royalty_cents` as `gross_cents`, stamps `prepared_by_user_id` from the caller's `X-User-ID`, and evaluates a fixed-order waterfall. The `cost_offset_cents` is the smaller of `gross_cents` and the disclosure's `unreimbursed_cost_cents` at calculation time. The `net_cents` is what remains of the gross after the offset. The university's administrative fee, `admin_fee_cents`, is 25 percent of the net, rounded half up to integer cents. The inventor percentage depends on the disclosure's `funding_source`: 40 percent when funding is `FEDERAL` or `MIXED`, 35 percent when `NON_FEDERAL`, and in either case reduced by 5 percentage points when the license is linked to a startup via `startup_id`. The `inventor_pool_cents` is that percentage of the net, rounded half up to integer cents. The `department_pool_cents` is whatever remains of the net after the admin fee and inventor pool — it deliberately absorbs any rounding remainder. The `university_pool_cents` is the cost offset plus the admin fee. Conservation holds by construction: the gross equals the sum of the cost offset, admin fee, inventor pool, and department pool, equivalently the university, inventor, and department pools.

The inventor pool divides among the disclosure's `CONFIRMED` roster entries into `inventor_shares`. Each entry's raw amount is the pool multiplied by its `share_bp` and divided by 10000. Each raw amount is floored to whole cents, and the remainder — the pool minus the sum of the floors — is distributed one cent at a time to entries ordered by `share_bp` descending with ties broken by the entry's `created_at` ascending (never by identifier), wrapping back to the front if the remainder exceeds the roster size, until the remainder is exhausted. Each entry's `amount_cents` is its floor plus any extra cents received; rounding half up per entry is explicitly not the algorithm. The department pool divides analogously into `department_shares`: the distinct home departments of the `CONFIRMED` inventors each carry a weight equal to the summed `share_bp` of that department's confirmed entries; raw amounts, floors, and one-cent remainder distribution follow the same pattern, ordered by weight descending with ties broken by the department's `created_at` ascending, and the department shares sum exactly to the pool. A freshly calculated distribution sits in `CALCULATED` status with an empty `cost_applications` list — offsets are only applied at approval. A `FinanceOfficer` may also recalculate an existing distribution from current cost and roster data, which re-runs the waterfall and both splits and increments the distribution's `version` by 1.

Approval by a `FinanceDirector` moves a `CALCULATED` distribution to `APPROVED` — any other state yields `ERR_DISTRIBUTION_NOT_APPROVABLE`. Two guards bind: the approver's `X-User-ID` must differ from the distribution's `prepared_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; and the request must carry `expected_distribution_version` matching the distribution's current `version` — if a recalculation has advanced the version since the director last read the figures, approval is rejected with `ERR_STALE_VERSION` (HTTP 412). Approval applies the cost offset to the disclosure's `UNREIMBURSED` cost rows in chronological order by `incurred_date`, breaking ties by `created_at` ascending: each row absorbs the smaller of the remaining offset and its own outstanding remainder, and a row whose `reimbursed_amount_cents` reaches its full `amount_cents` flips to `REIMBURSED`. The exact applications are recorded in `cost_applications` as cost-identifier and applied-cents pairs, the disclosure's `unreimbursed_cost_cents` is recomputed, and the distribution's `version` increments by 1.

Payment by a `FinanceDirector` moves an `APPROVED` distribution to `PAID` — any other state yields `ERR_DISTRIBUTION_NOT_PAYABLE` — and cascades: the underlying report moves from `ACCEPTED` to `PAID`, the license's cumulative rollups are recomputed (the report remains within the accepted-and-paid set, so totals are unchanged but `updated_at` refreshes), and each department named in `department_shares` has its `distribution_pool_cents` — the running department-pool ledger a department was created with at 0 — increased by its share amount.

Cancellation by a `FinanceDirector`, optionally with a `cancel_reason`, is defined from `CALCULATED` or `APPROVED` — anything else yields `ERR_DISTRIBUTION_NOT_CANCELLABLE`. Cancelling from `CALCULATED` needs no cost reversal because offsets only apply at approval. Cancelling from `APPROVED` reverses `cost_applications` exactly: each named cost row's `reimbursed_amount_cents` is reduced by its applied cents, rows returning to 0 flip from `REIMBURSED` back to `UNREIMBURSED`, and the disclosure's rollup is recomputed to exactly its pre-approval value. The license-termination cascade of §3.6 cancels distributions through the same mechanism.

### 3.9. Federal Compliance Reporting

Disclosures funded by `FEDERAL` or `MIXED` sources carry Bayh-Dole-style reporting duties; opening a compliance report on a `NON_FEDERAL` disclosure is refused with `ERR_NOT_FEDERALLY_FUNDED`. A `ComplianceOfficer` opens a report by supplying a `report_type` of `INITIAL_DISCLOSURE`, `ELECTION_OF_TITLE`, `UTILIZATION_REPORT`, or `EXTENSION_REQUEST`; the report begins in `DRAFT` with `prepared_by_user_id` stamped from the caller. Due dates derive from the report type. An `INITIAL_DISCLOSURE` report is due 180 days after the disclosure's `created_at`. An `ELECTION_OF_TITLE` report is due at the earlier of two instants: the statutory deadline 730 days after the disclosure's `created_at`, and — only when the disclosure has a `public_disclosure_date` — the patent bar date, which is 365 days after the public disclosure less a 30-day buffer; when no public disclosure date is recorded, the statutory deadline alone governs. `UTILIZATION_REPORT` and `EXTENSION_REQUEST` due dates are client-provided in the payload's `due_date`.

The officer submits a `DRAFT` report, moving it to `PENDING_CERTIFICATION` — submission from any other state is `ERR_COMPLIANCE_REPORT_INVALID_STATE`. Certification is performed by a `ComplianceDirector` whose `X-User-ID` must differ from the report's `prepared_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; certification requires the report to be `PENDING_CERTIFICATION`, stamps `certified_by_user_id` from the caller and `submitted_at` from the current clock, computes `late_flag` as true exactly when `submitted_at` is strictly after the `due_date` — submission exactly on the due date is on time — and moves the report to `SUBMITTED`. The director may instead reject a `PENDING_CERTIFICATION` report with a `rejection_reason`, returning it to `DRAFT` for revision.

After transmittal, the director records the agency's disposition via an `outcome`. An `ACCEPTED` outcome moves a `SUBMITTED` report to the terminal `AGENCY_ACCEPTED` state. A `REJECTED` outcome, with `agency_notes` captured into `rejection_reason`, loops the report back to `DRAFT` for the revision cycle, clearing `submitted_at`, `certified_by_user_id`, and `late_flag`. Recording a disposition from any state other than `SUBMITTED` is `ERR_COMPLIANCE_REPORT_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new resource — whether stand-alone or added to a parent collection — return `201 Created`. Operations that modify or transition an existing resource return `200 OK`. Error responses carry the identifiers catalogued in §5 with the HTTP statuses shown there.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/tlo/_clock/set_current_utc` | Advance the logical clock; sweeps license activation/expiry | SystemAdmin |
| POST | `/tlo/departments` | Create a department | SystemAdmin |
| GET | `/tlo/departments` | List departments | Any |
| GET | `/tlo/departments/{departmentId}` | Get a department | Any |
| POST | `/tlo/inventors` | Provision an inventor | SystemAdmin |
| GET | `/tlo/inventors` | List inventors, optionally filtered by department | Any |
| GET | `/tlo/inventors/{inventorId}` | Get an inventor | Any |
| GET | `/tlo/inventors/{id}/disclosure-entries` | List roster entries naming this inventor | Any |
| GET | `/tlo/inventors/{id}/disputes` | List disputes raised by this inventor | Any |
| GET | `/tlo/inventors/{id}/disclosures` | List disclosures submitted by this inventor | Any |
| GET | `/tlo/inventors/{id}/coi-plans` | List COI plans naming this inventor | Any |
| POST | `/tlo/disclosures` | Submit an invention disclosure | Inventor |
| GET | `/tlo/disclosures` | List disclosures with filters | Any |
| GET | `/tlo/disclosures/{disclosureId}` | Get a disclosure | Any |
| POST | `/tlo/disclosures/{id}/inventors` | Add an inventor roster entry | TechTransferOfficer |
| GET | `/tlo/disclosures/{id}/inventors` | List roster entries of a disclosure | Any |
| POST | `/tlo/disclosures/{disclosureId}/inventorship/finalize` | Finalize inventorship (OCC on disclosure version) | TechTransferOfficer |
| POST | `/tlo/disclosures/{disclosureId}/assessment` | Record patentability and market assessment | TechTransferOfficer |
| POST | `/tlo/disclosures/{disclosureId}/decision` | Assessment gate decision: pursue, waive, or shelf | TechTransferOfficer |
| POST | `/tlo/disclosures/{disclosureId}/cost-review/clear` | Clear the write-off review block | TechTransferOfficer |
| GET | `/tlo/disclosure-entries/{entryId}` | Get a roster entry | Any |
| POST | `/tlo/disclosure-entries/{entryId}/confirm` | Inventor confirms own roster entry | Inventor |
| POST | `/tlo/disclosure-entries/{entryId}/dispute` | A rostered inventor disputes this entry's share | Inventor |
| GET | `/tlo/disclosure-entries/{id}/disputes` | List disputes against this entry | Any |
| GET | `/tlo/inventorship-disputes` | List disputes, optionally filtered by disclosure | Any |
| GET | `/tlo/inventorship-disputes/{disputeId}` | Get a dispute | Any |
| POST | `/tlo/inventorship-disputes/{disputeId}/resolve` | Resolve a dispute with an adjusted share vector | TechTransferOfficer |
| POST | `/tlo/disclosures/{id}/patent-applications` | Open a patent application on the docket | TechTransferOfficer |
| GET | `/tlo/disclosures/{id}/patent-applications` | List patent applications of a disclosure | Any |
| GET | `/tlo/patent-applications/{applicationId}` | Get a patent application | Any |
| POST | `/tlo/patent-applications/{applicationId}/office-action` | Record an office action | TechTransferOfficer |
| POST | `/tlo/patent-applications/{applicationId}/file-response` | Record an office-action response | TechTransferOfficer |
| POST | `/tlo/patent-applications/{applicationId}/grant` | Record grant | TechTransferOfficer |
| POST | `/tlo/patent-applications/{applicationId}/abandon` | Abandon the application; write-off cascade | TechTransferOfficer |
| POST | `/tlo/patent-applications/{id}/costs` | Record a prosecution cost | TechTransferOfficer |
| GET | `/tlo/patent-applications/{id}/costs` | List costs of an application | Any |
| POST | `/tlo/disclosures/{id}/startups` | Form a startup around a disclosure | TechTransferOfficer |
| GET | `/tlo/disclosures/{id}/startups` | List startups of a disclosure | Any |
| GET | `/tlo/startups/{startupId}` | Get a startup | Any |
| POST | `/tlo/startups/{startupId}/issue-equity` | Issue university equity (variant per equity model) | TechTransferOfficer |
| POST | `/tlo/startups/{startupId}/dissolve` | Dissolve a startup; terminates open COI plans | TechTransferOfficer |
| GET | `/tlo/startups/{id}/licenses` | List licenses linked to this startup | Any |
| POST | `/tlo/startups/{id}/coi-plans` | File a conflict-of-interest management plan | ComplianceOfficer |
| GET | `/tlo/startups/{id}/coi-plans` | List COI plans of a startup | Any |
| GET | `/tlo/coi-plans/{planId}` | Get a COI plan | Any |
| POST | `/tlo/coi-plans/{planId}/approve` | Approve a COI plan (overlap re-checked) | ComplianceDirector |
| POST | `/tlo/coi-plans/{planId}/reject` | Reject a COI plan | ComplianceDirector |
| PATCH | `/tlo/coi-plans/{planId}` | Revise and resubmit a rejected COI plan | ComplianceOfficer |
| POST | `/tlo/disclosures/{id}/licenses` | Open a license negotiation | LicensingManager |
| GET | `/tlo/disclosures/{id}/licenses` | List licenses of a disclosure | Any |
| GET | `/tlo/licenses/{licenseId}` | Get a license | Any |
| POST | `/tlo/licenses/{licenseId}/counter` | Counter-offer round; toggles negotiation status | LicensingManager |
| POST | `/tlo/licenses/{licenseId}/execute` | Execute the license (OCC on license version) | LicensingManager |
| POST | `/tlo/licenses/{licenseId}/declare-default` | Declare licensee default on overdue-milestone grounds | LicensingManager |
| POST | `/tlo/licenses/{licenseId}/cure` | Cure a default within the cure window | LicensingManager |
| POST | `/tlo/licenses/{licenseId}/terminate` | Terminate after the cure window lapses; full cascade | LicensingManager |
| POST | `/tlo/licenses/{id}/milestones` | Add a milestone term | LicensingManager |
| GET | `/tlo/licenses/{id}/milestones` | List milestones of a license | Any |
| GET | `/tlo/milestones/{milestoneId}` | Get a milestone | Any |
| POST | `/tlo/licenses/{licenseId}/milestones/{milestoneId}/achieve` | Mark a milestone achieved (on/before due date) | LicensingManager |
| POST | `/tlo/licenses/{licenseId}/milestones/{milestoneId}/waive` | Waive a pending milestone | LicensingManager |
| POST | `/tlo/licenses/{id}/royalty-reports` | Submit a periodic royalty report | LicensingManager |
| GET | `/tlo/licenses/{id}/royalty-reports` | List royalty reports of a license | Any |
| GET | `/tlo/royalty-reports/{reportId}` | Get a royalty report | Any |
| POST | `/tlo/royalty-reports/{reportId}/accept` | Accept a report; computes earned royalty and true-up | FinanceOfficer |
| POST | `/tlo/royalty-reports/{id}/distribution` | Calculate the distribution waterfall for an accepted report | FinanceOfficer |
| GET | `/tlo/royalty-reports/{id}/distribution` | Get the distribution for a report (array of 0 or 1) | Any |
| GET | `/tlo/distributions/{distributionId}` | Get a distribution | Any |
| POST | `/tlo/distributions/{distributionId}/recalculate` | Recalculate pools from current costs/roster | FinanceOfficer |
| POST | `/tlo/distributions/{distributionId}/approve` | Approve a distribution (OCC plus segregation of duties) | FinanceDirector |
| POST | `/tlo/distributions/{distributionId}/pay` | Pay an approved distribution; credits department pools | FinanceDirector |
| POST | `/tlo/distributions/{distributionId}/cancel` | Cancel a calculated or approved distribution | FinanceDirector |
| POST | `/tlo/disclosures/{id}/compliance-reports` | Open a federal compliance report | ComplianceOfficer |
| GET | `/tlo/disclosures/{id}/compliance-reports` | List compliance reports of a disclosure | Any |
| GET | `/tlo/compliance-reports/{reportId}` | Get a compliance report | Any |
| POST | `/tlo/compliance-reports/{reportId}/submit` | Submit a draft report for certification | ComplianceOfficer |
| POST | `/tlo/compliance-reports/{reportId}/certify` | Certify and transmit to the agency | ComplianceDirector |
| POST | `/tlo/compliance-reports/{reportId}/reject` | Reject a report pending certification; returns to draft | ComplianceDirector |
| POST | `/tlo/compliance-reports/{reportId}/agency-response` | Record agency disposition | ComplianceDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DEPARTMENT_NOT_FOUND` | 404 |
| `ERR_INVENTOR_NOT_FOUND` | 404 |
| `ERR_DISCLOSURE_NOT_FOUND` | 404 |
| `ERR_DISCLOSURE_ENTRY_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_PATENT_APPLICATION_NOT_FOUND` | 404 |
| `ERR_LICENSE_NOT_FOUND` | 404 |
| `ERR_MILESTONE_NOT_FOUND` | 404 |
| `ERR_ROYALTY_REPORT_NOT_FOUND` | 404 |
| `ERR_DISTRIBUTION_NOT_FOUND` | 404 |
| `ERR_STARTUP_NOT_FOUND` | 404 |
| `ERR_COI_PLAN_NOT_FOUND` | 404 |
| `ERR_COMPLIANCE_REPORT_NOT_FOUND` | 404 |
| `ERR_DISCLOSURE_INVALID_STATE` | 409 |
| `ERR_INVENTORSHIP_NOT_FINALIZABLE` | 409 |
| `ERR_ENTRY_NOT_CONFIRMABLE` | 409 |
| `ERR_ENTRY_NOT_DISPUTABLE` | 409 |
| `ERR_DISPUTE_NOT_OPEN` | 409 |
| `ERR_PATENT_INVALID_STATE` | 409 |
| `ERR_COST_REVIEW_REQUIRED` | 422 |
| `ERR_COST_REVIEW_NOT_REQUIRED` | 409 |
| `ERR_STARTUP_INVALID_STATE` | 409 |
| `ERR_COI_NOT_REVIEWABLE` | 409 |
| `ERR_COI_NOT_REVISABLE` | 409 |
| `ERR_LICENSE_NOT_NEGOTIABLE` | 409 |
| `ERR_LICENSE_NOT_EXECUTABLE` | 409 |
| `ERR_LICENSE_NOT_ACTIVE` | 409 |
| `ERR_LICENSE_NOT_IN_DEFAULT` | 409 |
| `ERR_LICENSE_NOT_TERMINABLE` | 409 |
| `ERR_MILESTONE_NOT_PENDING` | 409 |
| `ERR_MILESTONE_OVERDUE` | 409 |
| `ERR_NO_DEFAULT_GROUNDS` | 409 |
| `ERR_CURE_PERIOD_EXPIRED` | 409 |
| `ERR_CURE_PERIOD_ACTIVE` | 409 |
| `ERR_REPORT_NOT_ACCEPTABLE` | 409 |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 |
| `ERR_DISTRIBUTION_NOT_APPROVABLE` | 409 |
| `ERR_DISTRIBUTION_NOT_PAYABLE` | 409 |
| `ERR_DISTRIBUTION_NOT_CANCELLABLE` | 409 |
| `ERR_COMPLIANCE_REPORT_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_TITLE_NOT_ELECTED` | 409 |
| `ERR_COI_COVERAGE_REQUIRED` | 409 |
| `ERR_INVENTOR_NOT_ON_DISCLOSURE` | 422 |
| `ERR_NOT_FEDERALLY_FUNDED` | 422 |
| `ERR_DUPLICATE_INVENTOR` | 422 |
| `ERR_SHARE_SUM_INVALID` | 409 |
| `ERR_COI_WINDOW_OVERLAP` | 409 |
| `ERR_EXCLUSIVE_OVERLAP` | 409 |
| `ERR_ASSESSMENT_GATE_FAILED` | 409 |
| `ERR_UPFRONT_BELOW_FLOOR` | 402 |
| `ERR_STALE_VERSION` | 412 |
