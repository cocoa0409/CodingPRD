# Insurance Market Conduct Examination API — Product Requirements Document

## 1. Introduction

A state insurance department does not have the staff to examine every carrier it licenses, so it must choose. The choosing is data-driven: consumer complaint volumes are normalised against policies in force, the financial regulation division contributes a stress indicator, and the consumer services division contributes a trend indicator covering rate-increase velocity, social-media escalation and media volume. Those three signals, weighted and scaled by premium volume, produce a ranked market-analysis picture from which a limited number of examination targets are drawn each cycle. Everything downstream — scope definition, data calls, file sampling, workpapers, criticisms, negotiation, penalties, restitution and publication — follows from that selection, and every step must be defensible in an administrative hearing years later.

This document specifies the service that carries that workflow end to end. The service is mounted under `/market-conduct`. It maintains the carrier data set and the scoring cycles that rank it; it opens examinations and holds their statutory scope across underwriting, rating, claims and producer practices; it issues data calls to carriers and measures the completeness and timeliness of their productions; it draws deterministic file samples and accumulates error rates against per-area statutory tolerances; it records interview and system-walkthrough workpapers; it issues criticisms, runs the bounded rebuttal negotiation with the carrier, and freezes each criticism's restitution exposure at issuance; it negotiates corrective action plans, computes penalties under two statutorily available algorithms, drafts and executes consent orders, allocates sustained restitution across participating states in a multistate collaborative action, and finally publishes the report and schedules any follow-up examination.

Two properties dominate the design. The first is **conservation**: examiner slots inside an analysis cycle and restitution cents inside a multistate allocation are finite quantities that must balance exactly, including when an examination is abandoned mid-flight and its consumption has to be given back. The second is **immutability of what has already been decided**: a restitution exposure computed at criticism issuance survives every subsequent rebuttal round unchanged, and a scope locked by a supervising examiner cannot be edited afterwards. Implementations that treat these as best-effort will produce numbers that a carrier's counsel can pull apart.

## 2. Global Specifications & System-Wide Principles

### 2.1. Departmental Roles and Access Control

Every request other than the logical-clock endpoint must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role that user is acting in. If `X-User-ID` is absent, empty, or not a well-formed UUID, the request is rejected with `ERR_UNAUTHENTICATED`. If the value of `X-User-Role` is not one of the roles the called endpoint declares, the request is rejected with `ERR_ROLE_NOT_PERMITTED`. The clock endpoint is the single exception to the `X-User-ID` requirement; all five roles may drive it.

There are exactly five roles, spelled as follows:

- `MarketAnalyst` — market analysis staff of the department. Owns the carrier data set, the scoring cycle and target selection; has no authority over examination fieldwork or enforcement.
- `ExaminerInCharge` — the examiner running fieldwork. Defines scope areas, issues data calls, dispositions productions, reviews sampled files, records workpapers, issues criticisms and rebuts company responses. Never finalizes a criticism, approves a plan, drafts an order or publishes a report.
- `SupervisingExaminer` — supervising examiner and enforcement authority. Opens examinations, locks scope, finalizes criticisms, reviews corrective action plans, drafts consent orders, publishes reports and aborts examinations.
- `MultistateCoordinator` — the NAIC collaborative-action coordinator. Opens the multistate collaboration, elects its lead state and allocates sustained restitution across participating states; otherwise read-only.
- `InsurerRespondent` — the compliance officer acting for the examined carrier. Produces records, answers criticisms, proposes corrective action plans and executes consent orders.

Identity semantics differ between the departmental roles and the carrier role, and the difference is load-bearing. When `X-User-Role` is `MarketAnalyst`, `ExaminerInCharge`, `SupervisingExaminer` or `MultistateCoordinator`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server records it where a workflow demands an audit key — as `issued_by_user_id` and `finalized_by_user_id` on a `Criticism`, as `reviewed_by_user_id` on a `CorrectiveActionPlan`, and as `drafted_by_user_id` on a `ConsentOrder` — but it never compares that value to any entity's `id`. When `X-User-Role` is `InsurerRespondent`, by contrast, `X-User-ID` is the `id` of the acting `Insurer`; ownership checks on any record the respondent touches walk up to the owning `Examination` and compare its `insurer_id` to `X-User-ID`. A mismatch is rejected with `ERR_NOT_EXAM_SUBJECT`. That check guards the respondent's four writes — producing records against a data call, answering a criticism, proposing a corrective action plan, and executing a consent order — and equally every read the respondent makes against a record whose owning examination belongs to another carrier.

Segregation of duties adds a second identity comparison, this time between two departmental users. It is described in §2.9.

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

Every list endpoint accepts two optional query parameters. `limit` defaults to 10, may be no lower than 1 and no higher than 100. `offset` defaults to 0 and may be no lower than 0. A value outside those ranges is a malformed request.

List results are ordered by `created_at` ascending unless the endpoint's own description states otherwise. Two endpoints do state otherwise: the scores of one cycle are returned in rank order, and the file samples of one accepted data call are returned in ascending `population_index` order — which, because samples are materialised in ascending index order, coincides with `created_at` ascending anyway.

For list responses the `meta` object carries `limit`, `offset`, `total_count` (the count of rows matching the filter before the window is applied) and `has_more` (true when rows remain beyond the current window).

### 2.4. Record Identity, Audit Stamps and the Logical Clock

Every record the service persists is addressed by an `id`: a server-minted UUID with no type prefix. Every record also carries a `created_at` timestamp, rendered as an ISO 8601 UTC instant with three fractional digits.

Most record types additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that record — including mutations that touch only derived counters. Records of the following types carry the full set: `Insurer`, `MarketAnalysisCycle`, `AnalysisScore`, `Examination`, `ExamScopeArea`, `DataCall`, `FileSample`, `Criticism`, `CorrectiveActionPlan`, `ConsentOrder` and `MultistateCollaboration`.

Two record types are append-only workpapers and are therefore exempt: a `FieldworkActivity` and a `CompanyResponse` each carry only `id` and `created_at`. Neither has an `updated_at` field and neither has a `version` field — those keys are absent from their payloads entirely, not merely null. A `FieldworkActivity` records its own moment of occurrence in `conducted_at`; a `CompanyResponse` records its own in `submitted_at`.

All server-generated time originates from a **logical clock**, never from wall-clock time. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`. A test-driving capability sets it to an explicit RFC3339 UTC instant supplied as `to_iso8601`, and answers with the object `{ current_utc, data_calls_flagged_overdue }` where `current_utc` echoes the new instant and `data_calls_flagged_overdue` counts the data calls the move swept into `OVERDUE`. Every field the specification describes as "a logical-clock instant" — `scored_at`, `closed_at`, `criticism_phase_opened_at`, `report_published_at`, `tested_at`, `responded_at`, `reviewed_at`, `conducted_at`, `finalized_at`, `submitted_at`, `executed_at`, `allocation_completed_at` — is read from that clock, and every date-only comparison uses the date part of it.

### 2.5. Statutory Precision and Rounding Discipline

Percentages and scores are carried to exactly 2 decimal places and rounded half up. This covers `complaint_ratio_per_1k`, `complaint_component`, `financial_component`, `trend_component`, `volume_multiplier`, `composite_score`, `error_tolerance_pct`, `error_rate_pct`, `material_error_rate_pct`, `completeness_pct`, `effective_completeness_pct` and `cooperation_credit_pct`.

Money is carried in whole cents as integers, never as fractional currency. Fields named with a `_cents` suffix — `annual_premium_written_cents`, `lifetime_restitution_ordered_cents`, `underpaid_amount_cents`, `restitution_exposure_cents`, `pending_restitution_cents`, `aggregate_restitution_cents`, `remediation_offer_cents`, `restitution_cents`, `penalty_gross_cents`, `penalty_net_cents`, `order_total_cents`, `allocated_total_cents` and each participant's `allocated_cents` — are integers. Where a monetary computation produces a fraction of a cent, it is rounded half up to a whole cent at the exact point in the sequence the relevant rule names, and nowhere else; several rules in §3 pin their rounding order explicitly because rounding earlier or later yields a different, wrong number.

Threshold comparisons throughout the service are inclusive on the stated boundary unless a rule says the comparison is strict. An error rate exactly equal to its tolerance breaches that tolerance. A completeness figure exactly equal to the acceptance floor is accepted. Conversely, the rebuttal-round guard is strict, and the data-call spacing rule is strict.

### 2.6. Version Pinning on Enforcement Writes

Two writes in the enforcement phase are guarded by optimistic concurrency against the parent `Examination`, because in both cases the write is legal on state grounds and would silently overwrite history the client has not seen.

`POST /market-conduct/examinations/{id}/corrective-action-plans` requires a non-optional `expected_examination_version` field carrying the `version` of the target examination as the carrier last read it. A new plan legitimately supersedes the examination's prior `PROPOSED` or `REVISION_REQUESTED` plan, so state alone cannot detect that the carrier is proposing against a plan history it has not observed; the pinned version is the only signal. If `expected_examination_version` does not equal the examination's current `version`, the request is rejected with `ERR_STALE_EXAMINATION_VERSION` and HTTP 412.

`POST /market-conduct/examinations/{id}/consent-orders` requires the same non-optional `expected_examination_version` field. A new draft legitimately voids the prior `DRAFT` order and re-freezes `restitution_cents` from the examination's current restitution aggregate, so the write is state-legal; the pinned version is the only signal that the drafter's view of that aggregate is out of date. A mismatch against the examination's current `version` is rejected with `ERR_STALE_EXAMINATION_VERSION` and HTTP 412.

No other endpoint accepts a version field. Requests to endpoints outside those two must not be examined for one, and supplying one there has no effect.

### 2.7. Cascade Propagation Through the Examination Hierarchy

An `Examination` sits at the head of a hierarchy: scope areas hang off it, data calls hang off scope areas, file samples hang off accepted data calls, and criticisms, workpapers, corrective action plans, consent orders and the multistate collaboration all hang off the examination directly. State changes propagate **upward** as derived counters and bubble-up transitions, and **downward** as terminal cascades.

Upward propagation is immediate and synchronous within the request that triggers it. When a child record changes in a way that feeds a parent counter, the parent's counter is recomputed in the same request, the parent's `updated_at` is refreshed and the parent's `version` is incremented by 1. Several of these upward paths chain further: reviewing the last unreviewed sample of an area drives the area to `TESTED`, which may in turn drive the examination out of `FIELDWORK`, which may in turn activate a multistate collaboration. Each such hop is spelled out in §3 at the workflow that triggers it.

Downward propagation happens when an examination becomes terminal. Publication closes the examination's tested areas; abandonment closes every non-closed area, cancels its live data calls, withdraws its open criticisms, rejects its live corrective action plans, voids its draft consent orders and dissolves its collaboration. Each cascaded record's own `version` is incremented by 1 as part of the same request.

### 2.8. Nested Path Resolution

Many reads and writes address a record through the record that owns it. Path segments are resolved strictly left to right, and the first segment that fails to resolve determines the error. A request naming an examination that does not exist fails with `ERR_EXAMINATION_NOT_FOUND` regardless of whether the child identifier further right would have resolved. A request naming an insurer that does not exist fails with `ERR_INSURER_NOT_FOUND`; a cycle that does not exist, with `ERR_CYCLE_NOT_FOUND`. A scope area, data call, file sample, criticism, corrective action plan, consent order or collaboration identifier that matches no row of that type fails with `ERR_EXAM_RECORD_NOT_FOUND`.

The same discipline applies to identifiers supplied in a request body rather than a path. When a criticism is issued, its body carries both an `exam_id` and a `scope_area_id`; an `exam_id` matching no examination is `ERR_EXAMINATION_NOT_FOUND`, and a `scope_area_id` that either matches no scope area **or** matches one whose own `exam_id` differs from the supplied `exam_id` is `ERR_EXAM_RECORD_NOT_FOUND`. The cross-parent case is checked immediately after plain existence, before any request-shape or business rule runs. Likewise, an `insurer_id` in a body that matches no carrier is `ERR_INSURER_NOT_FOUND`, and a `cycle_id` in a body that matches no cycle is `ERR_CYCLE_NOT_FOUND`.

### 2.9. Segregation of Duties

Two enforcement decisions may not be made by the user who set them up, and the service enforces both by comparing `X-User-ID` against an audit key stored earlier.

A criticism may not be sustained or withdrawn by the examiner who issued it: when finalizing a criticism, if `X-User-ID` equals that criticism's `issued_by_user_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. A report resting on an executed consent order may not be published by the supervising examiner who drafted that order: when publishing, if `X-User-ID` equals the executed order's `drafted_by_user_id`, the request is likewise rejected with `ERR_SEGREGATION_OF_DUTIES`. Both checks carry HTTP 403 and both are evaluated in the authorisation band, before any existence or state check on the target record.

### 2.10. Conserved Ledgers

Two quantities in the system are conserved, meaning that the sum of their parts must equal their whole exactly and at all times, including after a compensating abandonment.

The first is the **examiner slot ledger** on a `MarketAnalysisCycle`. A cycle declares `target_slot_capacity` when it opens. `slots_committed` is defined as the number of examinations attributed to that cycle whose `status` is neither `PUBLISHED` nor `ABORTED`, and `slots_available` is `target_slot_capacity` less `slots_committed`. Every event that adds a non-terminal examination to a cycle raises `slots_committed` by 1 and therefore lowers `slots_available` by 1; every event that drives such an examination terminal lowers `slots_committed` by 1 and restores `slots_available` by 1. An abandoned examination gives its slot back exactly, leaving the ledger where it stood before the examination was opened.

The second is the **multistate restitution ledger** on a `MultistateCollaboration`. Once allocation runs, the sum of every participant's `allocated_cents` — surfaced as `allocated_total_cents` — must equal the examination's sustained restitution aggregate to the cent, with no rounding drift in either direction. If the collaboration is dissolved because its examination was abandoned, every participant's `allocated_cents` and the collaboration's `allocated_total_cents` are reset to 0, leaving nothing stranded.

### 2.11. Order of Rejection

Many endpoints carry several independent checks, and which error a caller sees is part of the contract rather than an implementation detail. Checks are evaluated in the following bands, in this order, and the first band that produces a rejection determines the response:

1. **Authentication** — `ERR_UNAUTHENTICATED`.
2. **Role permission** — `ERR_ROLE_NOT_PERMITTED`.
3. **Carrier ownership** — `ERR_NOT_EXAM_SUBJECT` for an `InsurerRespondent` acting on another carrier's record.
4. **Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES`, criticism finalization first and report publication second.
5. **Existence** — `ERR_INSURER_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_EXAMINATION_NOT_FOUND` and `ERR_EXAM_RECORD_NOT_FOUND` for a missing row; then, one step later, `ERR_EXAM_RECORD_NOT_FOUND` again for a scope area that exists but belongs to a different examination than the body's `exam_id`.
6. **Request shape** — `ERR_INVALID_REQUEST`.
7. **Uniqueness** — `ERR_DUPLICATE_IDENTIFIER`.
8. **Lifecycle state** — `ERR_CYCLE_STATE_INVALID`, `ERR_EXAM_NOT_IN_SCOPING`, `ERR_SCOPE_NOT_LOCKED`, `ERR_DATA_CALL_NOT_AWAITING_RESPONSE`, `ERR_DATA_CALL_NOT_RESPONDED`, `ERR_SAMPLE_ALREADY_REVIEWED`, `ERR_EXAM_NOT_IN_CRITICISM_PHASE`, `ERR_CRITICISM_STATE_INVALID`, `ERR_EXAM_NOT_IN_NEGOTIATION`, `ERR_ENFORCEMENT_RECORD_STATE_INVALID`, `ERR_EXAM_NOT_READY_FOR_PUBLICATION` and `ERR_EXAM_ALREADY_TERMINAL`.
9. **Version pinning** — `ERR_STALE_EXAMINATION_VERSION`.
10. **Business safety**, in this internal order — `ERR_INSURER_NOT_EXAMINABLE`, then `ERR_SCOPE_AREA_NOT_TESTED`, then `ERR_FIELDWORK_NOT_DOCUMENTED`, then `ERR_SAMPLE_SIZE_BELOW_MINIMUM`, then `ERR_REBUTTAL_ROUNDS_EXHAUSTED`.
11. **Temporal occupancy**, in this internal order — `ERR_EXAM_WINDOW_CONFLICT`, then `ERR_DUE_DATE_OUT_OF_WINDOW`, then `ERR_DATA_CALL_WINDOW_CONFLICT`.
12. **Referential prerequisites**, in this internal order — `ERR_CAP_NOT_APPROVED`, then `ERR_ORDER_NOT_EXECUTED`, then `ERR_NO_TOLERANCE_BREACH`, then `ERR_NO_ELIGIBLE_LEAD_STATE`.
13. **Numeric constraints**, in this internal order — `ERR_RECORDS_EXCEED_REQUEST` and `ERR_SAMPLE_EXCEEDS_POPULATION` together, then `ERR_AFFECTED_FILES_EXCEED_ERRORS`, then `ERR_RESPONSE_INCOMPLETE`, then `ERR_CYCLE_SLOTS_EXHAUSTED`.
14. **Fiscal ceilings**, in this internal order — `ERR_PENALTY_CAP_EXCEEDED`, then `ERR_RESTITUTION_NOT_CONSERVED`.

Malformed-request rejection in band 6 covers, across all write endpoints: a required field missing; a field carrying the wrong JSON type; an enum field carrying a value outside its declared set; a monetary or count field that is negative; `sample_size`, `population_size`, `records_requested`, `milestone_count` or `target_slot_capacity` that is not at least 1; a date field that is not formatted `YYYY-MM-DD`; `fieldwork_end_date` that is not strictly after `fieldwork_start_date`; `reference_period_end` that is not strictly after `reference_period_start`; `default_fieldwork_end` that is not strictly after `default_fieldwork_start`; a percentage field outside the inclusive range 0.00 to 100.00; a `narrative`, `summary`, `public_summary` or `rebuttal_note` shorter than 20 characters; a `participating_states` array that is empty, contains a duplicate `state_code`, contains a `state_code` that is not exactly two uppercase letters, or whose `policy_count_in_state` values total zero; a `reviews` array that is empty or contains a duplicate `file_reference`; a `min_composite_score` outside the inclusive range 0.00 to 100.00; a `to_iso8601` that is not an RFC3339 UTC instant; and a scope-lock attempt on an examination that has no scope areas at all.

Duplicate-identifier rejection in band 7 covers five uniqueness rules: a `naic_code` that already exists on another carrier, a `cycle_label` that already exists on another cycle, an `order_number` that already exists on another consent order, a second scope area with the same `area` value on one examination, and a second collaboration on one examination.

Finally, `ERR_EXAM_ALREADY_TERMINAL` guards every write nested under an examination and every write on any of its descendants — scope areas, data calls, file samples, criticisms, company responses, corrective action plans, consent orders and the collaboration alike — once that examination's `status` is `PUBLISHED` or `ABORTED`. A second abandonment attempt and a second publication attempt both land there.

## 3. Business Logic & Workflows

### 3.1. The Carrier Data Set and Complaint-Ratio Surveillance

Market analysis begins with the carrier data set. A `MarketAnalyst` registers a regulated carrier by supplying its `name` (between 1 and 120 characters), its `naic_code` (exactly five digits, unique across all carriers — a collision is `ERR_DUPLICATE_IDENTIFIER`), its `annual_premium_written_cents` for the reference period, its `policy_count_in_force` at period end, its `confirmed_complaints_12mo`, and the two supplied indicators: `financial_stress_score` and `consumer_trend_score`, each an integer between 0 and 100 inclusive. An optional `license_status` records the certificate-of-authority position in the examining state and defaults to `LICENSED`; the other permitted values are `SUSPENDED` and `WITHDRAWN`. All four numeric inputs from premium through complaints must be zero or greater.

Registration immediately derives the surveillance figures. The complaint ratio is the trailing-twelve-month confirmed complaint count multiplied by one thousand and divided by policies in force, rounded half up to two decimal places, and stored as `complaint_ratio_per_1k`. A carrier with no policies in force is not a division error: when `policy_count_in_force` is zero, `complaint_ratio_per_1k` is set to 0.00 and `risk_tier` is set to `UNRATED`, and nothing further is computed. Otherwise `risk_tier` is read off the rounded ratio: `HIGH` when the ratio is 5.00 or more, otherwise `ELEVATED` when it is 2.50 or more, otherwise `MODERATE` when it is 1.00 or more, otherwise `LOW`. Each of those three comparisons is inclusive and each is made against the already-rounded ratio, not the unrounded quotient. Registration also initialises the three enforcement counters — `open_exam_count`, `pending_enforcement_exam_count` and `lifetime_restitution_ordered_cents` — to 0.

Fresh data arrives continuously, so a `MarketAnalyst` may refresh a carrier's market data at any time, supplying any subset of `policy_count_in_force`, `confirmed_complaints_12mo`, `financial_stress_score`, `consumer_trend_score`, `annual_premium_written_cents` and `license_status`. Every refresh re-derives `complaint_ratio_per_1k` and `risk_tier` by exactly the rule above and increments the carrier's `version` by 1. The three enforcement counters are never client-writable: `open_exam_count` tracks the carrier's examinations whose `status` is neither `PUBLISHED` nor `ABORTED`; `pending_enforcement_exam_count` tracks those whose `status` is `NEGOTIATION` or `ORDER_PENDING`; and `lifetime_restitution_ordered_cents` accumulates the `restitution_cents` of every consent order on the carrier's examinations that has reached `EXECUTED`. Carriers may be listed with an optional `license_status` filter and an optional `risk_tier` filter.

### 3.2. Analysis Cycles: Composite Scoring and Target Selection

A `MarketAnalyst` opens a **market-analysis cycle** by supplying a `cycle_label` of 1 to 40 characters, unique across cycles (a collision is `ERR_DUPLICATE_IDENTIFIER`); the data reference period as `reference_period_start` and `reference_period_end`, the latter strictly after the former; a `target_slot_capacity` of at least 1, being the number of examiner slots the division can staff from this cycle; and the fieldwork window every examination the cycle spawns will inherit, as `default_fieldwork_start` and `default_fieldwork_end`, the latter again strictly after the former. An optional `default_exam_mode` is stamped onto every examination the cycle creates and defaults to `ON_SITE`; the only alternative is `DESK`. A new cycle opens in `DRAFT` with `slots_committed` at 0, `slots_available` equal to `target_slot_capacity`, and `scored_insurer_count` and `selected_target_count` both 0. The cycle's `status` progresses `DRAFT → SCORED → TARGETS_SELECTED → CLOSED`.

**Scoring the market.** The analyst runs the scoring pass on a `DRAFT` cycle, which advances it `DRAFT → SCORED`. Running the pass on a cycle in any other state is `ERR_CYCLE_STATE_INVALID`, and that includes re-running it on a cycle that has already been scored. The pass requires at least one carrier whose `license_status` is `LICENSED` or `SUSPENDED`; carriers whose status is `WITHDRAWN` are not scored at all and receive no score row. The pass writes one `AnalysisScore` per scored carrier, each recording its `cycle_id` and `insurer_id` and snapshotting the carrier's current `complaint_ratio_per_1k` into `complaint_ratio_at_scoring`, so that later data refreshes cannot retroactively alter a completed scoring run.

Four sub-scores make up the composite, and the order in which they are combined is pinned. The **complaint component** is a tier lookup on the snapshotted ratio: 40 points when the ratio is 5.00 or more, otherwise 28 points when it is 2.50 or more, otherwise 16 points when it is 1.00 or more, otherwise 6 points; the result is stored as `complaint_component`. The **financial component** is the carrier's `financial_stress_score` multiplied by three tenths, rounded half up to two decimals, then held to a ceiling of 30.00, and stored as `financial_component`. The **trend component** is the carrier's `consumer_trend_score` multiplied by two tenths, rounded half up to two decimals, then held to a ceiling of 30.00, and stored as `trend_component`. The **volume multiplier** is 1.10 for a carrier whose `annual_premium_written_cents` is 5,000,000,000 cents (fifty million dollars) or more, and 1.00 otherwise; it is stored as `volume_multiplier`.

The evaluation order for `composite_score` is: round each of the three components to two decimals **first**, then add the three rounded components together, then multiply that sum by the volume multiplier, then round the product half up to two decimals, and only then hold the result to a ceiling of 100.00. Rounding the product before multiplying, or applying the cap before rounding, produces a different number and is not the rule.

Every score row also receives a 1-based `rank_position`, assigned by the cycle's ranking expression: `composite_score` descending, then `complaint_ratio_at_scoring` descending, then the score row's own `created_at` ascending. The `created_at` tie-break is final; a record's `id` must never be consulted as a tie-break anywhere in this service. On completion the cycle records `scored_insurer_count`, stamps `scored_at` from the logical clock, moves to `SCORED` and increments its own `version` by 1. Score rows are readable per cycle in rank order, filtered optionally by `selected` or `selection_reason`, and per carrier across all cycles, filtered optionally by `cycle_id` or `selected`.

**Selecting targets.** With the cycle in `SCORED`, the analyst runs target selection, which advances it `SCORED → TARGETS_SELECTED`. Selection on a cycle that is not `SCORED` is `ERR_CYCLE_STATE_INVALID`, and a cycle with no remaining examiner slot — `slots_available` of 0 — cannot select at all and is rejected with `ERR_CYCLE_SLOTS_EXHAUSTED`. The request may carry an optional `min_composite_score`; when it is absent the threshold is 40.00.

Selection assigns a `selection_reason` to **every** score row of the cycle, never only to the winners, and the eligibility filter is evaluated in a fixed order so that reason is single-valued. First, a carrier whose `license_status` is anything other than `LICENSED` — that is, a `SUSPENDED` carrier that was scored but cannot be examined — is marked `LICENSE_INELIGIBLE`. Second, a row whose `composite_score` is below the threshold is marked `BELOW_THRESHOLD`; a score exactly equal to the threshold survives. Third, a carrier that already has an examination whose `status` is neither `PUBLISHED` nor `ABORTED`, and whose half-open fieldwork occupancy window from `fieldwork_start_date` inclusive to `fieldwork_end_date` exclusive overlaps the cycle's own half-open window from `default_fieldwork_start` inclusive to `default_fieldwork_end` exclusive, is marked `WINDOW_CONFLICT_DEFERRED`. That third test looks at every live examination of the carrier, including examinations opened by other cycles and for-cause examinations opened directly. Rows surviving all three tests form the candidate pool.

The candidate pool is then ranked by the same expression used for `rank_position` — `composite_score` descending, then `complaint_ratio_at_scoring` descending, then `created_at` ascending — and the department takes as many of the top-ranked rows as it has slots for: the smaller of `slots_available` and the size of the candidate pool. Each taken row has `selected` set to true and `selection_reason` set to `SELECTED`, and produces one examination. Candidates the department ran out of slots for keep `selected` false and are marked `CAPACITY_EXHAUSTED`. An empty candidate pool is explicitly not an error: the cycle still advances to `TARGETS_SELECTED`, with `selected_target_count` of 0 and no examination created.

Each examination created by selection is stamped with the carrier's `insurer_id`, the originating `cycle_id`, an `exam_type` of `MARKET_CONDUCT_EXAM`, a `mode` copied from the cycle's `default_exam_mode`, a `lead_state_code` of `NV` (the examining department's own state), a `fieldwork_start_date` and `fieldwork_end_date` copied from the cycle's defaults, and a `status` of `SCOPING`. Each creation raises the carrier's `open_exam_count` by 1 and the cycle's `slots_committed` by 1, thereby lowering `slots_available` by 1. Selection finishes by writing `selected_target_count` and incrementing the cycle's `version` by 1.

**Closing the cycle.** A cycle that selected at least one target closes itself. When the last examination attributed to the cycle reaches `PUBLISHED` or `ABORTED` — that is, when `slots_committed` falls to 0 while `selected_target_count` is 1 or more — the cycle advances `TARGETS_SELECTED → CLOSED`, stamps `closed_at` from the logical clock and increments its `version` by 1. A cycle that selected nothing has no examinations to wait for and simply remains in `TARGETS_SELECTED`. `CLOSED` is terminal.

### 3.3. Opening an Examination and Defining Statutory Scope

Not every examination comes out of a cycle. A `SupervisingExaminer` may open a for-cause or targeted examination directly by supplying the subject `insurer_id`, an `exam_type` of either `MARKET_CONDUCT_EXAM` or `TARGETED_EXAM`, a `mode` of `ON_SITE` or `DESK`, a `lead_state_code` of exactly two uppercase letters, and the fieldwork occupancy window as `fieldwork_start_date` and `fieldwork_end_date`, the latter strictly after the former. An optional `cycle_id` attributes the examination to an existing cycle and consumes one of its slots; a `cycle_id` naming a cycle whose `slots_available` is 0 is rejected with `ERR_CYCLE_SLOTS_EXHAUSTED`. A carrier whose `license_status` is `WITHDRAWN` cannot be examined at all and the attempt is rejected with `ERR_INSURER_NOT_EXAMINABLE`.

Fieldwork occupancy on a carrier is exclusive. The requested window, read as half-open from `fieldwork_start_date` inclusive to `fieldwork_end_date` exclusive, must not overlap the window of any existing examination of the same carrier whose `status` is neither `PUBLISHED` nor `ABORTED`; an overlap is `ERR_EXAM_WINDOW_CONFLICT`. Because the geometry is half-open, exact adjacency is permitted: one examination ending on the very day another begins does not overlap and is accepted.

A newly opened examination sits in `SCOPING` with `scope_locked` false, `predecessor_exam_id` unset, and every derived counter at zero — `scope_area_count`, `rejected_data_call_count`, `open_criticism_count`, `sustained_criticism_count`, `pending_restitution_cents`, `aggregate_restitution_cents` and `penalty_units_total`. Opening raises the carrier's `open_exam_count` by 1 and, when a `cycle_id` was supplied, raises that cycle's `slots_committed` by 1. The examination's own `status` lifecycle is `SCOPING → DATA_CALL → FIELDWORK → CRITICISM`, from where it either publishes directly or routes `CRITICISM → NEGOTIATION → ORDER_PENDING → PUBLISHED`; `ABORTED` is reachable from any of those six non-terminal states, and `PUBLISHED` and `ABORTED` are both terminal. Examinations can be listed filtered by `insurer_id`, `cycle_id`, `predecessor_exam_id` or `status`.

**Scope areas.** While the examination is in `SCOPING`, the `ExaminerInCharge` adds one **scope area** per statutory examination area. The `area` value is one of `UNDERWRITING`, `RATING`, `CLAIMS` or `PRODUCER`, and at most one area of each value may exist on one examination — a repeat is `ERR_DUPLICATE_IDENTIFIER`. The examiner supplies the `population_size`, being the number of files in that area's population for the reference period, and the `sample_size` to be pulled by the sampling plan; both must be at least 1. Statutory minimum sample sizes depend on the examination's `mode`: an `ON_SITE` examination requires a `sample_size` of at least 10, a `DESK` examination at least 5, and a smaller figure is rejected with `ERR_SAMPLE_SIZE_BELOW_MINIMUM` at HTTP 422. A `sample_size` exceeding the `population_size` is rejected with `ERR_SAMPLE_EXCEEDS_POPULATION`. An optional `error_tolerance_pct` between 0.00 and 100.00 inclusive overrides the statutory default; when it is omitted the default is read from the per-area statutory table — 7.00 percent for `UNDERWRITING`, 5.00 percent for `RATING`, 3.00 percent for `CLAIMS` and 10.00 percent for `PRODUCER`. Each new area starts in `PLANNED`, raises the examination's `scope_area_count` by 1 and increments the examination's `version` by 1. Adding an area to an examination that is no longer in `SCOPING` is rejected with `ERR_EXAM_NOT_IN_SCOPING`.

**Locking scope.** The `SupervisingExaminer` locks the scope, which advances the examination `SCOPING → DATA_CALL`. Locking is possible only from `SCOPING` (otherwise `ERR_EXAM_NOT_IN_SCOPING`), requires at least one scope area to exist (an examination with `scope_area_count` of 0 is a malformed request, `ERR_INVALID_REQUEST`), and requires the subject carrier's `license_status` still to be `LICENSED` or `SUSPENDED` — a carrier that has become `WITHDRAWN` since the examination opened blocks the lock with `ERR_INSURER_NOT_EXAMINABLE`. Locking sets `scope_locked` to true and increments the examination's `version` by 1. From that moment the areas are immutable: any further attempt to add a scope area is rejected with `ERR_EXAM_NOT_IN_SCOPING`.

### 3.4. Data Calls: Issuance, Production and Disposition

With scope locked, the `ExaminerInCharge` issues a **data call** against one scope area, directing the carrier to produce records. The examiner supplies `records_requested` (at least 1, and never more than the area's `population_size` — an excess is `ERR_SAMPLE_EXCEEDS_POPULATION`) and a `response_due_date`. An optional `sampling_method` defaults to `SYSTEMATIC_INTERVAL`, which is currently the only methodology the statute recognises. The server stamps `issued_date` from the date part of the logical clock and opens the call in `ISSUED` with `records_received` 0, `is_late` false, `days_late` 0, `completeness_pct` 0.00, `effective_completeness_pct` 0.00, `sample_draw_interval` 0 and `samples_drawn_count` 0. Issuing a data call while the owning examination is still in `SCOPING` — before scope was locked — is rejected with `ERR_SCOPE_NOT_LOCKED`.

A data call occupies a closed interval on its scope area, running from `issued_date` to `response_due_date` inclusive, and two temporal rules police it. First, the due date must lie inside the examination's fieldwork window in the practical sense: a `response_due_date` earlier than the current logical-clock date, or later than the owning examination's `fieldwork_end_date`, is rejected with `ERR_DUE_DATE_OUT_OF_WINDOW` at HTTP 422. Second, live data calls on one area must be spaced apart. If the area already holds a data call whose `status` is neither `REJECTED` nor `CANCELLED`, and the whole-day distance between that call's `response_due_date` and the requested one is fewer than three days in either direction, the new call is rejected with `ERR_DATA_CALL_WINDOW_CONFLICT`. The comparison is strict: a gap of exactly three days is accepted, a gap of two is not.

A data call's own lifecycle runs `ISSUED → RESPONDED → ACCEPTED` or `ISSUED → RESPONDED → REJECTED`, with `OVERDUE` interposed when time runs out and `CANCELLED` reachable when the examination is abandoned; `ACCEPTED`, `REJECTED` and `CANCELLED` are all terminal. When the logical clock is moved forward, every data call still in `ISSUED` whose `response_due_date` now lies before the new clock date is swept `ISSUED → OVERDUE`, each such call's `version` being incremented by 1, and the count of swept calls is returned as `data_calls_flagged_overdue`.

**The carrier's production.** An `InsurerRespondent` produces records against a call in `ISSUED` or `OVERDUE`, which advances it to `RESPONDED`. A call in any other state is rejected with `ERR_DATA_CALL_NOT_AWAITING_RESPONSE`; the owning examination must be in `DATA_CALL` or `FIELDWORK`; and the acting `X-User-ID` must equal the examination's `insurer_id` or the request is rejected with `ERR_NOT_EXAM_SUBJECT`. The carrier supplies `records_received` and the `submitted_by_contact` naming the compliance contact on the response. `records_received` may not exceed the call's `records_requested`; an excess is rejected with `ERR_RECORDS_EXCEED_REQUEST`.

Production is then measured for lateness and completeness. `responded_at` is stamped from the logical clock. `days_late` is the whole-day difference from `response_due_date` to the response date, floored at zero — a response on or before the due date yields 0 — and `is_late` is true exactly when `days_late` is 1 or more. `completeness_pct` is `records_received` multiplied by one hundred and divided by `records_requested`, rounded half up to two decimals. The lateness penalty is then applied to that **already-rounded** figure: half a percentage point is deducted for each day late, the result is rounded half up to two decimals again, and the outcome is floored at 0.00 before being stored as `effective_completeness_pct`. Applying the penalty to the unrounded quotient, or skipping the second rounding, produces a different figure and is not the rule. The response also increments the call's `version` by 1.

**Disposition.** The `ExaminerInCharge` dispositions a `RESPONDED` call by supplying a `disposition` of either `ACCEPTED` or `REJECTED`, plus an optional `disposition_reason` note. A call that is not in `RESPONDED` is rejected with `ERR_DATA_CALL_NOT_RESPONDED`. The two branches have entirely disjoint consequences.

Accepting requires that `effective_completeness_pct` be at least 95.00; below that figure the acceptance is rejected with `ERR_RESPONSE_INCOMPLETE`, and a value of exactly 95.00 is accepted. A successful acceptance cascades in three hops. First, the call records its sampling plan — `sample_draw_interval` and `samples_drawn_count` — and moves to `ACCEPTED`, its `version` incremented by 1. Second, the owning scope area advances `PLANNED → FIELDWORK` and its file samples are materialised, its own `version` incremented by 1. Third, if this is the first data call of the examination to reach `ACCEPTED`, the examination itself advances `DATA_CALL → FIELDWORK` and its `version` is incremented by 1.

Rejecting draws no samples at all and never advances the examination into `FIELDWORK`. It raises the examination's `rejected_data_call_count` by 1 in every case, and increments the call's `version` by 1. Its effect on the scope area depends on how far testing has already progressed, and all three outcomes are part of the contract. If the area is in `FIELDWORK` and its `reviewed_sample_count` is 0, the area reverts `FIELDWORK → PLANNED`: every one of its file samples is deleted (all of them are necessarily `UNREVIEWED`), `reviewed_sample_count`, `error_count`, `material_error_count`, `error_rate_pct` and `material_error_rate_pct` are reset to 0 or 0.00, `tolerance_breached` and `escalation_required` are reset to false, `samples_drawn_count` is reset to 0 on every already-`ACCEPTED` data call of the area whose samples were just deleted, and the area's `version` is incremented by 1. That reversion exists so a replacement data call can re-draw the whole sample, subject to the three-day spacing rule. If the area is still in `PLANNED`, nothing further happens to it. And if at least one sample of the area has already been reviewed, the area stays in `FIELDWORK` and keeps its samples — only the rejection counter moves. In none of these cases does the examination roll back out of `FIELDWORK`.

### 3.5. Sampling, File Review and Tolerance Testing

Sampling is deterministic; there is no randomness anywhere in this service. When a data call is accepted, the sampling plan is a pure function of the scope area's `population_size`, its `sample_size` and its `area` value. The draw interval is the population size divided by the sample size, discarding any fractional part, and is stored on the call as `sample_draw_interval`; because `sample_size` never exceeds `population_size`, the interval is always 1 or more. The plan then walks the sample positions in order: the first sampled file sits at `population_index` 1, and each subsequent file sits one draw interval further along, so the k-th file after the first sits at 1 plus k times the interval. Exactly `sample_size` files are drawn, and `samples_drawn_count` on the data call is set to that same figure.

Each drawn file becomes a `FileSample` carrying its `data_call_id`, its `population_index`, and a deterministic `file_reference` built from the area's statutory prefix, a hyphen, and the `population_index` zero-padded to six digits. The prefixes are `UW` for `UNDERWRITING`, `RT` for `RATING`, `CLM` for `CLAIMS` and `PRD` for `PRODUCER`, so the four-hundred-and-first file of a claims population is labelled `CLM-000401`. Samples are created in ascending `population_index` order, so their `created_at` ordering matches their index ordering. Each starts with `review_status` of `UNREVIEWED`, `error_severity` of `NONE`, `underpaid_amount_cents` of 0 and `days_to_pay` of 0.

**Reviewing a file.** The `ExaminerInCharge` reviews one sampled file at a time by supplying an `error_severity` of `NONE`, `MINOR` or `MATERIAL`, plus optionally the `underpaid_amount_cents` quantifying consumer harm on that file and the `days_to_pay` the carrier took to settle it. Quantified harm must be zero or greater and must be 0 when the severity is `NONE`; `days_to_pay` is documentation only and feeds no calculation. The review derives `review_status` from severity: `COMPLIANT` when `error_severity` is `NONE`, and `ERROR` for both `MINOR` and `MATERIAL`. It stamps `reviewed_at` from the logical clock and increments the sample's `version` by 1. Reviewing a file whose `review_status` is already `COMPLIANT` or `ERROR` is rejected with `ERR_SAMPLE_ALREADY_REVIEWED`.

**Reviewing in bulk.** Because an area may hold hundreds of files, the examiner may also submit a `reviews` array in one call against an `ACCEPTED` data call, each entry addressing a file by its deterministic `file_reference` and carrying the same `error_severity`, `underpaid_amount_cents` and `days_to_pay` payload as a single review. The array may not be empty and may not name the same `file_reference` twice. Unlike the single-file review, the bulk action is forgiving about files already reviewed: it **skips** them rather than failing. It answers with `{ applied_count, skipped_count, skipped_file_references, scope_area_status, reviewed_sample_count, error_count, error_rate_pct, material_error_rate_pct, tolerance_breached, escalation_required }`, where `applied_count` counts the files actually reviewed, `skipped_count` and `skipped_file_references` report the already-reviewed references that were passed over, and the remaining members mirror the owning area's state after the batch. Bulk review against a data call whose `status` is not `ACCEPTED` is rejected with `ERR_DATA_CALL_NOT_RESPONDED`.

**Error rates and tolerance.** An area's counters are recomputed from its own file samples — those reachable through the data calls of that one area, and only that area. `reviewed_sample_count` counts samples whose `review_status` is anything other than `UNREVIEWED`. `error_count` counts samples whose `review_status` is `ERROR`, which means `MINOR` and `MATERIAL` files alike. `material_error_count` counts only samples whose `error_severity` is `MATERIAL`. `error_rate_pct` is `error_count` multiplied by one hundred and divided by `reviewed_sample_count`, rounded half up to two decimals, or 0.00 when nothing has been reviewed; `material_error_rate_pct` is the same computation over `material_error_count`. On an area whose errors are all `MINOR`, the two rates therefore diverge sharply, and that divergence is intentional. Samples belonging to a rejected data call were deleted and never enter any of these counts.

Two independent flags are read off those rates. `tolerance_breached` is true when `error_rate_pct` is greater than or equal to the area's own `error_tolerance_pct`; an error rate exactly equal to the tolerance breaches it. `escalation_required` is true when `material_error_rate_pct` is greater than or equal to 10.00 percent; again exact equality escalates. `escalation_required` is an escalation signal reported to the supervising examiner and is evaluated entirely independently of `tolerance_breached` — either may be true without the other.

**Closing out testing.** When the last `UNREVIEWED` file of an area is reviewed, whether by a single review or as part of a bulk batch, the area advances `FIELDWORK → TESTED` and cascades in two further hops. First, every counter and both flags above are recomputed, `tested_at` is stamped from the logical clock, and the area's `version` is incremented by 1. Second, when **every** scope area of the examination has reached `TESTED`, the examination bubbles up `FIELDWORK → CRITICISM`, stamps `criticism_phase_opened_at` from the logical clock and increments its `version` by 1 — and that examination transition in turn advances any multistate collaboration on the examination that is still in `LEAD_ASSIGNED` to `ACTIVE`, incrementing the collaboration's `version` by 1. A scope area's `status` therefore runs `PLANNED → FIELDWORK → TESTED`, with the `FIELDWORK → PLANNED` reversion described in §3.4 and `CLOSED` as its single terminal state.

### 3.6. Fieldwork Workpapers and Criticism Issuance

Findings must rest on documented fieldwork. The `ExaminerInCharge` records a **fieldwork activity** on the examination for each piece of evidence, supplying an `activity_type` of `INTERVIEW` or `SYSTEM_WALKTHROUGH`, the `area` the activity covers (one of `UNDERWRITING`, `RATING`, `CLAIMS` or `PRODUCER`, matched to a scope area by value rather than by reference), the `participant_name` and `participant_title` of the carrier staff member involved, a narrative workpaper `summary`, and optionally an `evidence_ref` naming the workpaper exhibit. The server stamps `conducted_at` from the logical clock and computes `documented`, which is true only when the `summary` runs to at least 20 characters **and** an `evidence_ref` is present and non-empty; an activity lacking an exhibit reference is left undocumented. Recording an activity while the examination is still in `SCOPING` is rejected with `ERR_SCOPE_NOT_LOCKED`. Workpapers may be listed per examination, filtered optionally by `activity_type` or `area`.

**Issuing a criticism.** With an area tested, the `ExaminerInCharge` issues a **criticism** by supplying the `exam_id`, the `scope_area_id` the finding rests on, the `statute_citation` naming the statute or regulation cited, a `severity` of `MINOR`, `MATERIAL` or `EGREGIOUS`, and the `affected_file_count` of sampled files the criticism covers. Five business gates guard the issuance and, per §2.11, they are evaluated in this order. The examination's `status` must be `FIELDWORK` or `CRITICISM`, otherwise `ERR_EXAM_NOT_IN_CRITICISM_PHASE`. The referenced scope area's `status` must be `TESTED` — still `PLANNED`, still in `FIELDWORK`, or already `CLOSED` all fail with `ERR_SCOPE_AREA_NOT_TESTED`. The examination's fieldwork must be documented: it must hold at least one fieldwork activity whose `activity_type` is `SYSTEM_WALKTHROUGH`, and — only when the examination's `mode` is `ON_SITE` — at least one whose `activity_type` is `INTERVIEW`; a `DESK` examination requires the walkthrough alone. A missing requirement is `ERR_FIELDWORK_NOT_DOCUMENTED`. An `EGREGIOUS` criticism must rest on an area whose `tolerance_breached` is true; issuing one against a within-tolerance area is rejected with `ERR_NO_TOLERANCE_BREACH` at HTTP 422. And `affected_file_count` must be at least 1 and no greater than the referenced area's `error_count`; an excess is `ERR_AFFECTED_FILES_EXCEED_ERRORS`.

**Freezing the restitution exposure.** Issuance computes the criticism's monetary exposure once and freezes it. The base figure is the sum of `underpaid_amount_cents` across the file samples of the criticism's own scope area whose `review_status` is `ERROR`; samples belonging to other areas of the same examination are excluded entirely. The reviewed-sample denominator is that area's `reviewed_sample_count`, which is guaranteed to be at least 1 because the area must be `TESTED`.

Which of two methods applies is decided deterministically at issuance and stored in `restitution_method`. The method is `POPULATION_EXTRAPOLATED` when the `severity` is `EGREGIOUS`, or when the `severity` is `MATERIAL` **and** the area's `tolerance_breached` is true. In every other case the method is `SAMPLE_ACTUAL`. Both operands carry weight: a `MATERIAL` criticism on a within-tolerance area remains `SAMPLE_ACTUAL`, and a `MINOR` criticism on a breached area also remains `SAMPLE_ACTUAL`.

Under `SAMPLE_ACTUAL`, `restitution_exposure_cents` equals the observed sample harm exactly — the summed underpayment across the area's error files — and the unexamined remainder of the population is not charged. Under `POPULATION_EXTRAPOLATED`, the summed underpayment is first divided by the reviewed-sample count and **that per-file average is rounded half up to a whole cent**, and only then is the rounded average multiplied by the area's `population_size` to give `restitution_exposure_cents`. The rounding order is pinned: dividing, multiplying, and rounding only at the end is a different number and is explicitly not the rule. For identical sample data, extrapolation yields an exposure orders of magnitude larger than the sample-actual figure.

A new criticism opens in `ISSUED` with `response_round` 0 and `rebuttal_count` 0, records the acting `X-User-ID` as `issued_by_user_id` for the later segregation-of-duties comparison, raises the examination's `open_criticism_count` by 1 and its `pending_restitution_cents` by the frozen `restitution_exposure_cents`, and increments the examination's `version` by 1. Criticisms may be listed filtered by `exam_id`, `scope_area_id` or `status`.

### 3.7. Rebuttal Rounds and Criticism Finalization

A criticism is a negotiation, not a verdict. Its `status` cycles `ISSUED → RESPONDED → ISSUED` for as long as the parties disagree, and the cycle is bounded at three response rounds so the negotiation terminates.

The carrier answers a criticism that is in `ISSUED`, moving it to `RESPONDED`. The acting `X-User-ID` must equal the examination's `insurer_id`, otherwise `ERR_NOT_EXAM_SUBJECT`; a criticism in any state other than `ISSUED` yields `ERR_CRITICISM_STATE_INVALID`. The answer supplies a `position` of `CONCUR`, `PARTIAL_CONCUR` or `DISPUTE`, a `narrative` of at least 20 characters, and optionally a `remediation_offer_cents` figure naming restitution the carrier offers to pay voluntarily, which defaults to 0 and must be zero or greater. Each answer materialises a `CompanyResponse` carrying its `criticism_id`, its `round_number` — one greater than the criticism's `response_round` before the answer, and therefore equal to the criticism's `response_round` immediately afterwards — and a `submitted_at` stamp from the logical clock. The criticism's `response_round` is raised by 1 and its `version` incremented by 1. Response rounds may be listed per criticism, filtered optionally by `position`.

The `ExaminerInCharge` may rebut a `RESPONDED` criticism, supplying a `rebuttal_note` of at least 20 characters, which returns the criticism to `ISSUED` for another round, raises `rebuttal_count` by 1 and increments the criticism's `version` by 1. Rebuttal explicitly does **not** recompute the exposure: `restitution_method` and `restitution_exposure_cents` keep the values frozen at issuance, however many rounds the cycle runs. Rebutting a criticism that is not `RESPONDED` is `ERR_CRITICISM_STATE_INVALID`.

Both sides of the cycle share one guard, and the comparison is strict: an answer or a rebuttal is permitted only while the criticism's `response_round` is strictly below three. Once `response_round` has reached three, both are rejected with `ERR_REBUTTAL_ROUNDS_EXHAUSTED`. The practical consequence is that after the third answer the criticism sits in `RESPONDED` with `response_round` at 3 and can only be finalized; `rebuttal_count` therefore never exceeds two on a criticism that reaches finalization.

**Finalization.** The `SupervisingExaminer` finalizes a `RESPONDED` criticism by supplying a `disposition` of `SUSTAINED` or `WITHDRAWN`, plus an optional `penalty_units` figure (zero or greater, defaulting to 0) recording the statutory violation units assessed, and an optional `disposition_note`. Finalizing a criticism that is not `RESPONDED` is `ERR_CRITICISM_STATE_INVALID`, and the acting `X-User-ID` must differ from the criticism's `issued_by_user_id` or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Either disposition records `finalized_by_user_id` from `X-User-ID`, stamps `finalized_at` from the logical clock, and increments the criticism's `version` by 1; both `SUSTAINED` and `WITHDRAWN` are terminal for the criticism. The fiscal consequences of the two dispositions diverge completely, and both must be implemented.

Sustaining cascades in three hops. First, `penalty_units` and `disposition_note` are written alongside the audit stamps. Second, the frozen exposure moves from provisional to accrued on the examination: `open_criticism_count` is lowered by 1 and `pending_restitution_cents` is lowered by the criticism's `restitution_exposure_cents`, while `sustained_criticism_count` is raised by 1, `aggregate_restitution_cents` is raised by that same `restitution_exposure_cents`, and `penalty_units_total` is raised by the criticism's `penalty_units`; the examination's `version` is incremented by 1. Third, if that leaves the examination with `open_criticism_count` of 0 and `sustained_criticism_count` of 1 or more, the examination advances `CRITICISM → NEGOTIATION`, incrementing its `version` again and raising the subject carrier's `pending_enforcement_exam_count` by 1.

Withdrawal is the compensating branch. It lowers `open_criticism_count` by 1 and lowers `pending_restitution_cents` by the criticism's `restitution_exposure_cents`, and it leaves `sustained_criticism_count`, `aggregate_restitution_cents` and `penalty_units_total` completely untouched — no fiscal accrual of any kind. Both the criticism's `version` and the examination's `version` are incremented by 1. An examination all of whose criticisms were withdrawn has no enforcement to negotiate and can therefore leave `CRITICISM` only through publication.

### 3.8. Corrective Action, Consent Orders and Penalty Determination

Once an examination is in `NEGOTIATION`, remediation and settlement proceed in a fixed sequence: the carrier proposes a plan, the supervisor dispositions it, an approved plan opens the consent-order phase, the supervisor drafts an order electing a penalty algorithm, and the carrier executes it.

**Corrective action plans.** The `InsurerRespondent` proposes a plan against the examination, supplying the `expected_examination_version` pin described in §2.6, a `milestone_count` of at least 1 naming the number of remediation milestones committed to, a `completion_due_date` by which the carrier commits to completing them all, and a `narrative` of at least 20 characters. The acting `X-User-ID` must equal the examination's `insurer_id`, otherwise `ERR_NOT_EXAM_SUBJECT`; the examination's `status` must be `NEGOTIATION`, otherwise `ERR_EXAM_NOT_IN_NEGOTIATION`. A new plan opens in `PROPOSED` and supersedes any earlier plan on the examination whose `status` is `PROPOSED` or `REVISION_REQUESTED`: that earlier plan moves to `SUPERSEDED` and has its `version` incremented by 1, and the new plan takes a `revision_round` one greater than the superseded plan's. The very first plan on an examination takes `revision_round` 1. Proposal increments the examination's `version` by 1.

The `SupervisingExaminer` dispositions a `PROPOSED` plan by supplying a `decision` of `APPROVE`, `REJECT` or `REQUEST_REVISION`, plus an optional `review_note`. Any of the three records `reviewed_by_user_id` from `X-User-ID` and the `review_note`, and increments the plan's `version` by 1. Reviewing a plan whose `status` is not `PROPOSED` is rejected with `ERR_ENFORCEMENT_RECORD_STATE_INVALID`. The three branches must be treated with equal care. `REQUEST_REVISION` moves the plan to `REVISION_REQUESTED` and leaves the examination in `NEGOTIATION`. `REJECT` moves the plan to `REJECTED` and likewise leaves the examination in `NEGOTIATION`, obliging the carrier to propose a superseding plan. `APPROVE` moves the plan to `APPROVED` and cascades: the examination advances `NEGOTIATION → ORDER_PENDING` and its `version` is incremented by 1. `APPROVED`, `REJECTED` and `SUPERSEDED` are all terminal for a plan.

**Drafting the consent order.** The `SupervisingExaminer` drafts a consent order on the examination, supplying the `expected_examination_version` pin, an `order_number` unique across all consent orders (a collision is `ERR_DUPLICATE_IDENTIFIER`), and a `penalty_variant` of either `PER_VIOLATION` or `TIERED_AGGREGATE`. The examination's `status` must be `NEGOTIATION` or `ORDER_PENDING`, otherwise `ERR_EXAM_NOT_IN_NEGOTIATION`, and the examination must already hold a corrective action plan in `APPROVED`, otherwise `ERR_CAP_NOT_APPROVED`. Drafting voids any existing `DRAFT` order on the examination — that order moves to `VOIDED` and has its `version` incremented by 1 — records `drafted_by_user_id` from `X-User-ID` as the segregation-of-duties key, opens the new order in `DRAFT`, and increments the examination's `version` by 1.

The order's figures are computed at drafting and frozen there. `restitution_cents` is a snapshot of the examination's `aggregate_restitution_cents`, which by construction reflects `SUSTAINED` criticisms only — criticisms still in `ISSUED` or `RESPONDED`, and criticisms that were `WITHDRAWN`, contribute nothing to it, nor to `penalty_units_total`, nor to `sustained_criticism_count`.

The **per-violation** algorithm ignores restitution size entirely: the gross penalty is the examination's `penalty_units_total` multiplied by 25,000 cents (250 dollars per statutory violation unit).

The **tiered-aggregate** algorithm ignores violation units entirely and instead runs a waterfall over the restitution aggregate. The first 5,000,000 cents of restitution form the first tier; the next 20,000,000 cents form the second tier; everything beyond the first 25,000,000 cents forms the third tier. Each tier's amount is multiplied by its own rate — one tenth for the first tier, six hundredths for the second, three hundredths for the third — and **each of those three products is rounded half up to a whole cent individually before the three are added together**. To that sum is added a flat base of 100,000 cents for each `SUSTAINED` criticism on the examination, that is, 100,000 cents multiplied by `sustained_criticism_count`. Rounding once at the end of the waterfall rather than per tier is a different number and is not the rule.

Whichever variant the department elects, the gross figure is stored as `penalty_gross_cents`, and if it exceeds 50,000,000 cents the draft is rejected outright with `ERR_PENALTY_CAP_EXCEEDED` at HTTP 422 — the statutory ceiling is never silently applied as a clamp, and the department must elect the other variant instead.

The cooperation credit is keyed on a subtotal that already contains the penalty, so the chain looks circular. It is resolved in exactly these five steps, in this order and no other. Step one: `penalty_gross_cents` is the gross figure of the elected variant. Step two: an order subtotal is formed as the restitution aggregate plus that gross penalty; this subtotal is an intermediate that is never persisted on the order. Step three: `cooperation_credit_pct` is fifteen hundredths when the subtotal is 25,000,000 cents or more, and five hundredths otherwise. Step four: `penalty_net_cents` is the gross penalty multiplied by one minus the credit rate, rounded half up to a whole cent. Step five: `order_total_cents` is the restitution aggregate plus the net penalty. The credit tier must be derived from the **gross** subtotal and never from a net figure; for orders whose subtotal straddles 25,000,000 cents, deriving it from net selects the wrong tier.

Because the two variants can differ enormously for the same examination, a supervising examiner or multistate coordinator may ask for both side by side without persisting either. That computed read reports `{ examination_id, sustained_criticism_count, aggregate_restitution_cents, penalty_units_total, per_violation_penalty_gross_cents, per_violation_cooperation_credit_pct, per_violation_penalty_net_cents, per_violation_order_total_cents, tiered_penalty_gross_cents, tiered_cooperation_credit_pct, tiered_penalty_net_cents, tiered_order_total_cents }`, applying the same five-step chain independently to each variant. Nothing is written and no cap rejection occurs on this read.

**Executing the order.** The `InsurerRespondent` executes a `DRAFT` order, supplying the `signed_by` name of the carrier officer who signed it. The acting `X-User-ID` must equal the examination's `insurer_id`, otherwise `ERR_NOT_EXAM_SUBJECT`; an order whose `status` is not `DRAFT` is rejected with `ERR_ENFORCEMENT_RECORD_STATE_INVALID`. Execution stamps `executed_at` from the logical clock, moves the order to `EXECUTED`, increments the order's `version` by 1, and raises the subject carrier's `lifetime_restitution_ordered_cents` by the order's frozen `restitution_cents`. The examination remains in `ORDER_PENDING`; execution alone does not publish anything. `EXECUTED` and `VOIDED` are both terminal for an order.

### 3.9. Multistate Collaboration and Restitution Allocation

Where several states have an interest in the same carrier's conduct, the examination is run as an NAIC collaborative action. A `MultistateCoordinator` opens the collaboration on an examination, supplying the `participating_states` roster and optionally the `call_reference` naming the NAIC collaborative-action call. At most one collaboration may exist per examination; a second attempt is `ERR_DUPLICATE_IDENTIFIER`.

The roster holds between 1 and 12 participant objects. Each carries a `state_code` of exactly two uppercase letters, unique within the array; a `policy_count_in_state` of at least 1; a `has_examiner_resources` boolean declaring whether that state can contribute examiners; and an `allocated_cents` figure which is server-maintained, starts at 0 and is never accepted from the client. The collaboration records `participant_count` as the roster's length, opens in `LEAD_ASSIGNED` with `allocated_total_cents` of 0, and elects its own `lead_state_code`.

Lead-state election is a three-step selector over the roster as supplied. Only participants whose `has_examiner_resources` is true are eligible. Eligible participants are ranked by `policy_count_in_state` descending, and ties are broken by `state_code` ascending in plain lexicographic order on the two-letter code. The first participant after that ordering becomes the collaboration's `lead_state_code`. If no participant has examiner resources, the request is rejected with `ERR_NO_ELIGIBLE_LEAD_STATE` at HTTP 422 and **no** collaboration row is created. This selector writes only the collaboration's own `lead_state_code`; the examination's separate `lead_state_code` is left untouched.

A collaboration's `status` runs `LEAD_ASSIGNED → ACTIVE → SETTLED`, with `DISSOLVED` reachable when the examination is abandoned; `SETTLED` and `DISSOLVED` are both terminal. Activation is not a client action: as described in §3.5, a collaboration in `LEAD_ASSIGNED` advances to `ACTIVE` when its examination bubbles up from `FIELDWORK` to `CRITICISM`, and its `version` is incremented by 1.

**Allocating restitution.** The `MultistateCoordinator` allocates the examination's sustained restitution across the roster, which advances the collaboration `ACTIVE → SETTLED`. A collaboration whose `status` is not `ACTIVE` is rejected with `ERR_ENFORCEMENT_RECORD_STATE_INVALID`; the examination must already hold a consent order in `EXECUTED`, otherwise `ERR_ORDER_NOT_EXECUTED`; and an examination whose `aggregate_restitution_cents` is 0 has nothing to allocate, so the attempt is rejected with `ERR_RESTITUTION_NOT_CONSERVED`.

The allocation itself divides the examination's `aggregate_restitution_cents` by policy count. The denominator is the sum of `policy_count_in_state` across the whole roster, which is at least 1 by the input constraint. Each participant's provisional share is the total multiplied by that participant's `policy_count_in_state`, divided by the denominator, with any fractional cent discarded. Because every share is rounded down, a remainder of whole cents is left over: the total less the sum of the provisional shares. That remainder is distributed one cent at a time, walking the roster ordered by `policy_count_in_state` descending and then `state_code` ascending; since the remainder is always strictly smaller than `participant_count`, exactly the first several participants in that order — as many as there are remainder cents — receive one extra cent each, and no participant receives two. Each participant's final figure is written to its `allocated_cents`, their sum is written to `allocated_total_cents`, `allocation_completed_at` is stamped from the logical clock and the collaboration's `version` is incremented by 1. The conservation invariant of §2.10 must hold exactly: `allocated_total_cents` equals the examination's `aggregate_restitution_cents` to the cent, with no drift.

### 3.10. Publication, Follow-Up Scheduling and Abandonment

**Publishing the report.** The `SupervisingExaminer` publishes the examination report, supplying a `public_summary` of at least 20 characters. Publication is legal from exactly two states, and the two branches have deliberately divergent consequences. Publication from any state other than `CRITICISM` or `ORDER_PENDING` is rejected with `ERR_EXAM_NOT_READY_FOR_PUBLICATION`, and so is publication from `CRITICISM` when the examination already has one or more `SUSTAINED` criticisms — such an examination must route through `NEGOTIATION` and an executed order rather than publishing directly.

The **clean branch** applies when the examination is in `CRITICISM` with `open_criticism_count` of 0 and `sustained_criticism_count` of 0: every criticism was either never issued or was withdrawn. The examination advances `CRITICISM → PUBLISHED`, stamps `report_published_at` from the logical clock, records the supplied `public_summary`, sets `followup_required` to false and leaves `followup_due_date` null. Every scope area still in `TESTED` moves to `CLOSED`, each with its `version` incremented by 1. If the examination carries a `cycle_id`, that cycle's `slots_committed` is lowered by 1, restoring `slots_available`, and the cycle closes if that was its last live examination. The examination's `version` is incremented by 1. No follow-up examination is created on this branch and no consent order was required.

The **enforcement branch** applies when the examination is in `ORDER_PENDING`. It requires a consent order on the examination whose `status` is `EXECUTED`, otherwise `ERR_ORDER_NOT_EXECUTED`, and the acting `X-User-ID` must differ from that order's `drafted_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. The examination advances `ORDER_PENDING → PUBLISHED`, stamping `report_published_at` and recording `public_summary` as before, but here `followup_required` is set to true and `followup_due_date` is computed. Every `TESTED` scope area moves to `CLOSED`. The carrier's `pending_enforcement_exam_count` is lowered by 1. If the examination carries a `cycle_id`, the cycle's `slots_committed` is lowered by 1 and the cycle may close. The examination's `version` is incremented by 1.

**Follow-up scheduling.** The follow-up interval is keyed on the most severe severity among the examination's `SUSTAINED` criticisms, ranked `EGREGIOUS` above `MATERIAL` above `MINOR`; criticisms that were `WITHDRAWN` never influence the interval. When the examination has no sustained criticisms at all, `followup_required` is false and `followup_due_date` is null. Otherwise the interval is twelve calendar months when the most severe sustained criticism is `EGREGIOUS`, eighteen calendar months when it is `MATERIAL`, and twenty-four calendar months when it is `MINOR`. `followup_due_date` is the date part of the logical clock at publication advanced by that many calendar months, clamped to the last day of the target month when the day of the month does not exist there — a publication on the 31st advancing into a 30-day month lands on the 30th.

The enforcement branch also creates the **follow-up examination** itself, in `SCOPING`. It carries the same `insurer_id`, a `predecessor_exam_id` pointing at the examination just published, no `cycle_id`, an `exam_type` of `TARGETED_EXAM`, a `mode` of `DESK` regardless of the predecessor's mode, the predecessor's `lead_state_code` copied across, a `fieldwork_start_date` equal to `followup_due_date`, and a `fieldwork_end_date` sixty days after `followup_due_date`. Its creation raises the carrier's `open_exam_count` by 1. Because the follow-up carries no `cycle_id`, it consumes no examiner slot from the predecessor's cycle.

**Abandoning an examination.** A `SupervisingExaminer` may abort any examination whose `status` is not already terminal, supplying an `abort_reason` recording the justification. An examination already in `PUBLISHED` or `ABORTED` is rejected with `ERR_EXAM_ALREADY_TERMINAL`, which also covers a second abort attempt. Abandonment is the system's compensating transaction and it unwinds in four hops, all within the same request.

The first hop records `abort_reason` and moves the examination to `ABORTED`. The second hop sweeps the descendants: every data call whose `status` is `ISSUED`, `OVERDUE` or `RESPONDED` moves to `CANCELLED`; every scope area whose `status` is `PLANNED`, `FIELDWORK` or `TESTED` moves to `CLOSED`; every criticism whose `status` is `ISSUED` or `RESPONDED` moves to `WITHDRAWN`; every corrective action plan whose `status` is `PROPOSED` or `REVISION_REQUESTED` moves to `REJECTED`; every consent order whose `status` is `DRAFT` moves to `VOIDED`; and a collaboration whose `status` is `LEAD_ASSIGNED` or `ACTIVE` moves to `DISSOLVED`, resetting every participant's `allocated_cents` and the collaboration's `allocated_total_cents` to 0. Each swept record has its own `version` incremented by 1.

The third hop reverses the accounting. Each criticism withdrawn in the second hop lowers the examination's `open_criticism_count` by 1 and lowers its `pending_restitution_cents` by that criticism's `restitution_exposure_cents`, driving both to 0; already-`SUSTAINED` criticisms are untouched, so `sustained_criticism_count`, `aggregate_restitution_cents` and `penalty_units_total` retain whatever was accrued before the abort. Because the examination has become terminal, the carrier's `open_exam_count` is lowered by 1; the carrier's `pending_enforcement_exam_count` is lowered by 1 as well, but only when the examination's status immediately before the abort was `NEGOTIATION` or `ORDER_PENDING`; and when the examination carries a `cycle_id`, that cycle's `slots_committed` is lowered by 1, restoring `slots_available` exactly.

The fourth hop propagates that slot release upward: if the release leaves the cycle with `slots_committed` of 0 while its `selected_target_count` is 1 or more, the cycle advances `TARGETS_SELECTED → CLOSED` and stamps `closed_at`. Finally, the examination's own `version` is incremented by 1.

## 4. Endpoint Definitions

Operations that create a new stand-alone record, or add a new distinct record to a collection — registering a carrier, opening a cycle, opening an examination, adding a scope area, issuing a data call, recording a workpaper, issuing a criticism, filing a company response, proposing a plan, drafting an order, opening a collaboration — return `201 Created`. Every other operation, including all state transitions on an existing record and all reads, returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/market-conduct/insurers` | Register a regulated carrier with the market-analysis data set | MarketAnalyst |
| GET | `/market-conduct/insurers` | List carriers, optionally filtered by licence status or computed risk tier | MarketAnalyst, ExaminerInCharge, SupervisingExaminer, MultistateCoordinator |
| GET | `/market-conduct/insurers/{id}` | Read one carrier including its complaint ratio, risk tier and enforcement counters | MarketAnalyst, ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| PATCH | `/market-conduct/insurers/{id}/market-data` | Refresh the carrier's complaint, financial, trend, premium or licence inputs | MarketAnalyst |
| GET | `/market-conduct/insurers/{id}/analysis-scores` | Every analysis score produced for this carrier across all cycles | MarketAnalyst, SupervisingExaminer |
| POST | `/market-conduct/analysis-cycles` | Open a market-analysis cycle with slot capacity and default fieldwork window | MarketAnalyst |
| GET | `/market-conduct/analysis-cycles` | List market-analysis cycles | MarketAnalyst, SupervisingExaminer |
| GET | `/market-conduct/analysis-cycles/{id}` | Read one cycle including its examiner-slot ledger | MarketAnalyst, SupervisingExaminer |
| POST | `/market-conduct/analysis-cycles/{id}/score` | Run the scoring pass over every LICENSED or SUSPENDED carrier | MarketAnalyst |
| GET | `/market-conduct/analysis-cycles/{id}/scores` | The analysis scores of one cycle, in rank order | MarketAnalyst, SupervisingExaminer |
| POST | `/market-conduct/analysis-cycles/{id}/select-targets` | Apply eligibility, ranking and slot capacity to turn scores into examinations | MarketAnalyst |
| POST | `/market-conduct/examinations` | Open a for-cause or targeted examination directly | SupervisingExaminer |
| GET | `/market-conduct/examinations` | List examinations by subject carrier, cycle, predecessor or status | MarketAnalyst, ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| GET | `/market-conduct/examinations/{id}` | Read one examination including version, scope flags and enforcement aggregates | MarketAnalyst, ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| POST | `/market-conduct/examinations/{id}/scope-areas` | Add a statutory examination area with population, sample size and tolerance | ExaminerInCharge |
| GET | `/market-conduct/examinations/{id}/scope-areas` | The scope areas of one examination with testing state and error rates | MarketAnalyst, ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| POST | `/market-conduct/examinations/{id}/lock-scope` | Lock the examination scope and open the data-call phase | SupervisingExaminer |
| POST | `/market-conduct/examinations/{id}/fieldwork-activities` | Record an interview or system-walkthrough workpaper | ExaminerInCharge |
| GET | `/market-conduct/examinations/{id}/fieldwork-activities` | The fieldwork workpapers of one examination | ExaminerInCharge, SupervisingExaminer, MultistateCoordinator |
| GET | `/market-conduct/examinations/{id}/exposure-summary` | Both penalty variants side by side, without persisting either | SupervisingExaminer, MultistateCoordinator |
| POST | `/market-conduct/examinations/{id}/publish-report` | Publish the examination report and schedule any follow-up | SupervisingExaminer |
| POST | `/market-conduct/examinations/{id}/abort` | Abort a non-terminal examination and unwind its dependents | SupervisingExaminer |
| GET | `/market-conduct/scope-areas/{id}` | Read one scope area including both error rates and the tolerance flags | ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| POST | `/market-conduct/scope-areas/{id}/data-calls` | Issue a data call against one scope area | ExaminerInCharge |
| GET | `/market-conduct/scope-areas/{id}/data-calls` | The data calls issued against one scope area | ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| GET | `/market-conduct/data-calls/{id}` | Read one data call including lateness and both completeness percentages | ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| POST | `/market-conduct/data-calls/{id}/respond` | Carrier produces records against a data call | InsurerRespondent |
| POST | `/market-conduct/data-calls/{id}/disposition` | Accept or reject the carrier's production | ExaminerInCharge |
| GET | `/market-conduct/data-calls/{id}/file-samples` | The file samples drawn from one accepted data call, by population index | ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| POST | `/market-conduct/data-calls/{id}/bulk-review` | Review many drawn files in one call, addressed by file reference | ExaminerInCharge |
| GET | `/market-conduct/file-samples/{id}` | Read one sampled file workpaper | ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| POST | `/market-conduct/file-samples/{id}/review` | Review one sampled file, recording severity and quantified harm | ExaminerInCharge |
| POST | `/market-conduct/criticisms` | Issue a criticism against a TESTED scope area, freezing its exposure | ExaminerInCharge |
| GET | `/market-conduct/criticisms` | List criticisms by examination, scope area or status | ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| GET | `/market-conduct/criticisms/{id}` | Read one criticism including its frozen restitution method and exposure | ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| POST | `/market-conduct/criticisms/{id}/responses` | Carrier answers a criticism, consuming one response round | InsurerRespondent |
| GET | `/market-conduct/criticisms/{id}/responses` | The company response rounds recorded against one criticism | ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| POST | `/market-conduct/criticisms/{id}/rebut` | Examiner rebuts the carrier's answer, reopening the criticism | ExaminerInCharge |
| POST | `/market-conduct/criticisms/{id}/finalize` | Sustain or withdraw a responded criticism | SupervisingExaminer |
| POST | `/market-conduct/examinations/{id}/corrective-action-plans` | Carrier proposes a corrective action plan against the version it last observed | InsurerRespondent |
| GET | `/market-conduct/examinations/{id}/corrective-action-plans` | The plans proposed on one examination, including superseded revisions | ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| GET | `/market-conduct/corrective-action-plans/{id}` | Read one corrective action plan | ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| POST | `/market-conduct/corrective-action-plans/{id}/review` | Approve, reject or request revision of a proposed plan | SupervisingExaminer |
| POST | `/market-conduct/examinations/{id}/consent-orders` | Draft a consent order electing a penalty variant, against the observed version | SupervisingExaminer |
| GET | `/market-conduct/examinations/{id}/consent-orders` | The consent orders drafted on one examination, including voided drafts | ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| GET | `/market-conduct/consent-orders/{id}` | Read one consent order including the full penalty derivation | ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| POST | `/market-conduct/consent-orders/{id}/execute` | Carrier executes the consent order | InsurerRespondent |
| POST | `/market-conduct/examinations/{id}/collaborations` | Open a multistate collaboration and elect its lead state | MultistateCoordinator |
| GET | `/market-conduct/examinations/{id}/collaborations` | The multistate collaboration attached to one examination | ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| GET | `/market-conduct/collaborations/{id}` | Read one collaboration including the per-state allocation array | ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |
| POST | `/market-conduct/collaborations/{id}/allocate-restitution` | Allocate sustained restitution across participating states by policy count | MultistateCoordinator |
| POST | `/market-conduct/_clock/set_current_utc` | Set the logical clock and sweep overdue data calls | MarketAnalyst, ExaminerInCharge, SupervisingExaminer, MultistateCoordinator, InsurerRespondent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_NOT_EXAM_SUBJECT` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INSURER_NOT_FOUND` | 404 |
| `ERR_CYCLE_NOT_FOUND` | 404 |
| `ERR_EXAMINATION_NOT_FOUND` | 404 |
| `ERR_EXAM_RECORD_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_IDENTIFIER` | 409 |
| `ERR_CYCLE_STATE_INVALID` | 409 |
| `ERR_EXAM_NOT_IN_SCOPING` | 409 |
| `ERR_SCOPE_NOT_LOCKED` | 409 |
| `ERR_DATA_CALL_NOT_AWAITING_RESPONSE` | 409 |
| `ERR_DATA_CALL_NOT_RESPONDED` | 409 |
| `ERR_SAMPLE_ALREADY_REVIEWED` | 409 |
| `ERR_EXAM_NOT_IN_CRITICISM_PHASE` | 409 |
| `ERR_CRITICISM_STATE_INVALID` | 409 |
| `ERR_EXAM_NOT_IN_NEGOTIATION` | 409 |
| `ERR_ENFORCEMENT_RECORD_STATE_INVALID` | 409 |
| `ERR_EXAM_NOT_READY_FOR_PUBLICATION` | 409 |
| `ERR_EXAM_ALREADY_TERMINAL` | 409 |
| `ERR_STALE_EXAMINATION_VERSION` | 412 |
| `ERR_INSURER_NOT_EXAMINABLE` | 409 |
| `ERR_SCOPE_AREA_NOT_TESTED` | 409 |
| `ERR_FIELDWORK_NOT_DOCUMENTED` | 409 |
| `ERR_SAMPLE_SIZE_BELOW_MINIMUM` | 422 |
| `ERR_REBUTTAL_ROUNDS_EXHAUSTED` | 409 |
| `ERR_EXAM_WINDOW_CONFLICT` | 409 |
| `ERR_DUE_DATE_OUT_OF_WINDOW` | 422 |
| `ERR_DATA_CALL_WINDOW_CONFLICT` | 409 |
| `ERR_CAP_NOT_APPROVED` | 409 |
| `ERR_ORDER_NOT_EXECUTED` | 409 |
| `ERR_NO_TOLERANCE_BREACH` | 422 |
| `ERR_NO_ELIGIBLE_LEAD_STATE` | 422 |
| `ERR_RECORDS_EXCEED_REQUEST` | 422 |
| `ERR_SAMPLE_EXCEEDS_POPULATION` | 422 |
| `ERR_AFFECTED_FILES_EXCEED_ERRORS` | 422 |
| `ERR_RESPONSE_INCOMPLETE` | 409 |
| `ERR_CYCLE_SLOTS_EXHAUSTED` | 409 |
| `ERR_PENALTY_CAP_EXCEEDED` | 422 |
| `ERR_RESTITUTION_NOT_CONSERVED` | 409 |
