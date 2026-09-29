# Broadband Grant Challenge API — Product Requirements Document

## 1. Introduction

A state broadband office does not simply hand out money. Before a single strand of fiber is pulled it must decide, address by address, which locations the federal maps say are unserved, underserved or already served; it must let incumbent providers and aggrieved communities contest those classifications on the record; it must vet applicants for technical, financial and managerial capability; it must score competing proposals on cost per location, speed commitments, affordability and workforce plans; and it must obligate, disburse and — where deployment obligations are broken — claw back public funds. Every one of those decisions is auditable, and every one of them can be invalidated by a later decision made upstream. The Broadband Grant Challenge API is the system of record for that entire chain of custody.

Three properties dominate the design. First, **evidence is weighed, not counted**: a challenge succeeds or fails on a weighted, recency-discounted evidence score measured against a standard that depends on who is challenging. Second, **decisions cascade backwards**: a challenge sustained late in the cycle reclassifies a location, which flips a claim on somebody's application, which invalidates that application's score sheet, which freezes allocation for the whole program until the application is rescored. Third, **no single official may both prepare and approve the same decision** — the office enforces three explicit separations of duty on the acting user identity.

This document specifies the complete external contract: the response envelope, the role model, the classification and scoring arithmetic, the state machines of eleven resource families, the ordered validation ladder, and the fiscal ledger whose invariant must hold after every mutation. The entire surface is mounted under `/broadband`, with a single test-driving clock endpoint mounted outside it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the capacity in which that user is acting. A request with a missing or empty `X-User-ID` is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); the sole exception is the logical-clock endpoint, which is a test-driving facility and requires no acting user. A request whose `X-User-Role` is missing, is not one of the nine declared role names, or is not listed among the roles authorised for the endpoint being called is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The nine roles are `ProgramAdmin`, `EligibilityAnalyst`, `CapabilityReviewer`, `ScoringOfficer`, `EnvironmentalReviewer`, `AuditOfficer`, `Subgrantee`, `Challenger` and `Provider`. A `ProgramAdmin` is the broadband office's program manager: it creates programs and locations, advances program phases, selects applications, obligates awards, authorises construction, adds and disburses milestones, and resolves clawbacks. An `EligibilityAnalyst` ingests national-map locations and runs challenge adjudication. A `CapabilityReviewer` opens and determines capability reviews. A `ScoringOfficer` produces score sheets and returns deficient applications for cure. An `EnvironmentalReviewer` screens, determines a pathway for, and clears environmental and historic preservation review. An `AuditOfficer` verifies milestone build evidence, schedules deployment audits, records their results and issues clawback notices. A `Subgrantee` is the applicant provider or cooperative. A `Challenger` is a community, local-government or nonprofit party filing a challenge, and a `Provider` is an incumbent internet service provider that may file provider-standard challenges and rebut challenges against locations it reported.

Identity semantics differ by role, and they matter because every ownership check compares `X-User-ID` to a stored identifier. When `X-User-Role` is `Subgrantee`, `X-User-ID` is the `id` of the acting `Subgrantee`; ownership checks on any resource that references a `Subgrantee` compare the resource's foreign-key field to `X-User-ID` — an application is owned by the subgrantee whose id equals its `subgrantee_id`, and an award, its milestones and its audits are owned by the subgrantee behind the award's application. When `X-User-Role` is `ProgramAdmin`, `EligibilityAnalyst`, `CapabilityReviewer`, `ScoringOfficer`, `EnvironmentalReviewer`, `AuditOfficer`, `Challenger` or `Provider`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records those opaque identifiers where a transition writes them — as `triaged_by_user_id` and `determined_by_user_id` on a challenge, `submitter_user_id` on a challenge and on an evidence item, `capability_reviewer_user_id` on a subgrantee, `scored_by_user_id` on a score sheet, `cleared_by_user_id` on an environmental review, `verified_by_user_id` on a milestone, `last_verifier_user_id` on an award, and `auditor_user_id` and `notice_issued_by_user_id` on a compliance audit — and compares them to later callers' `X-User-ID` values, but it never compares them to any entity's `id`. The `reporting_provider_user_id` recorded on a location is likewise an opaque `Provider` identifier.

An ownership failure by a caller who does hold an allowed role is `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This covers three situations: a `Subgrantee` acting on an application, location claim or milestone whose owning application's `subgrantee_id` is not its own `X-User-ID`; an evidence append by a caller who is neither the challenge's `submitter_user_id` nor the challenged location's `reporting_provider_user_id`; and a challenge resubmission by a caller other than the challenge's `submitter_user_id`.

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

List endpoints are paginated through two query parameters. `limit` is the maximum number of rows returned; it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` is the number of rows skipped before the page begins; it defaults to 0 and its minimum accepted value is 0. A `limit` outside 1 through 100, a non-integer `limit`, a negative `offset` or a non-integer `offset` is rejected with `ERR_INVALID_PAGINATION`.

Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending.

Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the envelope's `meta` object, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` states whether rows remain beyond the current page.

### 2.4. Common Resource Properties and the Logical Clock

Grant programs, eligible locations, challenges, subgrantees, applications, location claims, score sheets, awards, environmental reviews, milestones and compliance audits all carry the same four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the row was first written.
- `updated_at` (string): an ISO 8601 UTC timestamp recording the last mutation of the row.
- `version` (integer): an integer that starts at 1 and increments by one on every mutation of the row.

Two resource families are append-only records of something that already happened and therefore carry only `id` and `created_at`: a `ChallengeEvidence` item and a `LedgerEntry`. Neither exposes `updated_at` and neither exposes `version` — they are never mutated after creation, so there is nothing for those fields to describe.

Recomputing a derived field counts as a mutation. When a sustained challenge refreshes an application's confirmed location count, when a disbursement refreshes an award's disbursed total, or when a ledger append refreshes a program's balances, the affected row's `updated_at` is refreshed and its `version` increments, even though no client sent a payload naming that row.

All time comparisons — window membership, rebuttal deadlines, evidence recency, certification instants — are made against a **logical clock** rather than wall-clock time. Before any call to the clock-setting endpoint, the logical clock reads exactly `2026-08-01T00:00:00Z`; the server must never fall back to real time. A `ProgramAdmin` moves the clock by supplying `current_utc`, and every subsequent comparison uses the new instant.

### 2.5. Program Phases and the Scoring Posture Gate

A `GrantProgram` moves through `program_state` values `DRAFT`, `CHALLENGE_OPEN`, `CHALLENGE_CLOSED`, `SCORING` and the terminal `ALLOCATION_CLOSED`, always in that order and only forwards. Layered on top of `program_state` is a derived gate, `scoring_posture`, whose values are `OPEN`, `RESTRICTED` and `FROZEN`. The posture is recomputed after every mutation that changes `program_state` and after every mutation that changes the `score_state` of any score sheet belonging to the program — that is, on score-sheet creation, on the fourth hop of the sustained-challenge cascade, and on award termination.

The recomputation first counts `stale_score_sheet_count`: the number of score sheets whose application belongs to this program and whose `score_state` is `STALE`, with no time window applied. Then the posture is `FROZEN` when `program_state` is `DRAFT`, `CHALLENGE_OPEN` or `ALLOCATION_CLOSED`; it is `RESTRICTED` when `program_state` is `CHALLENGE_CLOSED` or `SCORING` **and** `stale_score_sheet_count` is at least 1; and it is `OPEN` in every other case. Both `FROZEN` and `RESTRICTED` block application selection and award obligation with `ERR_SCORING_POSTURE_RESTRICTED`; only `OPEN` permits them. This is the mechanism by which one unresolved reclassification anywhere in the program halts allocation program-wide.

The program row also publishes `location_count_total`, the number of eligible locations recorded against it across every `eligibility_state` value.

### 2.6. Segregation of Duties

Three separations are enforced on `X-User-ID`, and all three surface as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). First, the analyst recorded in a challenge's `triaged_by_user_id` may not record that challenge's determination. Second, the reviewer recorded in a subgrantee's `capability_reviewer_user_id` may not create a score sheet for any application of that subgrantee. Third, the operator recorded in an award's `last_verifier_user_id` — the caller who most recently verified a milestone on that award — may neither record an audit result nor verify remediation on the same award.

### 2.7. Cascade Discipline and Cross-Aggregate Consistency

Several operations in this domain mutate more than one aggregate, and the secondary effects are not optional. A single request may reclassify a location, flip claims on a foreign application, invalidate that application's score sheet and freeze the program's allocation posture; another may deobligate money, release locations and void milestones. Where a cascade is specified, every hop is part of the same request: the request either applies all hops or fails and applies none. Hops are numbered in the workflow narratives of §3 so that the causal chain is unambiguous, and each hop refreshes `updated_at` and increments `version` on every row it touches.

Cascades are also compensating where the domain requires reversibility. Terminating an award returns each of its locations from `AWARD_BOUND` back to `AFFIRMED` and clears `awarded_award_id`, returning the location to the eligible pool; verifying remediation returns failed locations from `AUDIT_FAILED` back to `SERVICE_AVAILABLE`; settling a clawback clears `certified_at` on the failed locations so that the award's certified count returns to what it was before those certifications.

### 2.8. Path Resolution and Reverse-Reachability Reads

Collections are flat: `programs`, `locations`, `challenges`, `subgrantees`, `applications`, `location-claims`, `score-sheets` and `awards` are all top-level segments under `/broadband`, and a resource's parents are expressed as foreign-key fields in its payload rather than as path ancestry. Milestones, compliance audits, environmental reviews, ledger entries and challenge evidence are addressed beneath their parent because they have no independent existence.

When a path contains more than one identifier, identifiers are resolved strictly left to right and the first unresolvable one determines the error. A request naming a milestone under a non-existent award fails with `ERR_AWARD_NOT_FOUND` before the milestone is ever looked up. Sub-collection reads (the claims filed against a location, the claims and score sheets and awards of an application, the evidence of a challenge, an award's ledger entries, milestones, compliance audits and environmental review) exist purely as reverse-reachability read channels over a foreign key; they never define the identity of the child resource, and each of them accepts `limit` and `offset`. The environmental-review read returns an array holding zero or one row.

### 2.9. Numeric Precision and Rounding

Money is held in integer cents throughout; there are no fractional cents anywhere in the system. Wherever a monetary computation involves a division, the quotient is rounded half up to a whole cent exactly once, at the step where the division appears, and never re-rounded afterwards. Score components, evidence weights and capability components are decimal numbers carried to exactly 2 decimal places, also rounded half up. The one four-decimal quantity in the system is an audit's `noncompliant_share`, which is rounded half up to 4 decimal places before it is used to select a penalty tier.

Rounding order is part of the contract, not an implementation detail. Where the specification says to round per item and then sum, summing first and rounding afterwards is wrong even when the two agree numerically on a particular input. Where it says a multiplier applies once to an unrounded subtotal, applying it to a rounded subtotal is wrong. The §3 narratives state the order for each calculation explicitly.

Percentage inputs (`min_match_pct`, `holdback_pct`, `match_offer_pct`, `local_hire_pct`) are decimal numbers constrained to the range 0 through 100 inclusive; a value outside that range, a non-integer where an integer is required, a negative cents amount, an out-of-range enum value or a timestamp lacking an explicit UTC offset is rejected with `ERR_INVALID_REQUEST`.

### 2.10. Optimistic Concurrency on Evidence and Scoring

Two write paths take a stale-version guard, and on those two the guard field is a required input, not an optional one.

Appending an evidence item to a challenge requires `expected_challenge_version`, carrying the `version` of the parent `Challenge` as the client last observed it. Every append recomputes the challenge's evidence scores and therefore increments the challenge's `version`, so a client that read the challenge, then lost the race to another appender, is holding a stale number. If `expected_challenge_version` does not equal the challenge's current `version`, the append is rejected with `ERR_STALE_CHALLENGE_VERSION` (HTTP 412).

Creating a score sheet requires `expected_application_version`, carrying the `version` of the parent `Application` as the client last observed it. A new score sheet legitimately supersedes an earlier one — a sustained challenge drives the application to `RESCORE_REQUIRED` and marks the old sheet `STALE` — so the write itself is valid from a reachable state; what is not valid is a client scoring against a view of the application that has since moved. If `expected_application_version` does not equal the application's current `version`, the create is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412).

No other endpoint accepts a version field, and no other endpoint performs a version check.

### 2.11. The Appropriation Ledger and Its Invariant

Every fiscal movement is recorded as an immutable `LedgerEntry` against an award. An entry carries `award_id`, an `entry_type` drawn from `OBLIGATION`, `DISBURSEMENT`, `DEOBLIGATION` and `CLAWBACK_RECOVERY`, a strictly positive `amount_cents` (the sign is implied by `entry_type`, never by the number), a `source_reference` naming the triggering object such as a milestone sequence, an audit window or a termination reason, a `memo` for the audit trail, and `program_uncommitted_after_cents`, a snapshot of the program's uncommitted balance taken immediately after the entry was appended. Entries are never updated or deleted, so replaying them in full is the definition of the program's balances rather than a cache of them.

After every append, the program's three balances are re-derived from the complete set of ledger entries belonging to that program's awards, with no status filter and no time window. Let the obligation total be the sum of `amount_cents` over entries of type `OBLIGATION`, the disbursement total the same sum over `DISBURSEMENT`, the deobligation total over `DEOBLIGATION`, and the recovery total over `CLAWBACK_RECOVERY`. Then `uncommitted_balance_cents` is `total_appropriation_cents` minus the obligation total, plus the deobligation total, plus the recovery total; `obligated_balance_cents` is the obligation total minus the deobligation total minus the disbursement total; and `disbursed_balance_cents` is the disbursement total minus the recovery total. Reconciliation is exact integer arithmetic — nothing is rounded here. The invariant that must hold after every mutation is that `total_appropriation_cents` equals the sum of `uncommitted_balance_cents`, `obligated_balance_cents` and `disbursed_balance_cents`.

### 2.12. Validation Order

When more than one rule could reject a request, the rule with the lowest priority number wins and its error is the one returned; evaluation stops at the first violation. The ladder below is the complete ordering.

1. **Priority 10 — authentication.** `X-User-ID` present and non-empty on every endpoint except the logical-clock setter → `ERR_UNAUTHENTICATED`.
2. **Priority 12 — role authorisation.** `X-User-Role` present, one of the nine declared roles, and listed for the endpoint → `ERR_UNAUTHORIZED`.
3. **Priority 14 — request validity.** Body parses as JSON; every required input field present; enum values in range; integer fields integral; percentage fields within 0 through 100; every `*_cents` field at least 0; ISO 8601 timestamps parse and carry an explicit UTC offset → `ERR_INVALID_REQUEST`.
4. **Priority 16 — pagination validity.** On list endpoints, `limit` an integer from 1 through 100 and `offset` an integer of at least 0 → `ERR_INVALID_PAGINATION`.
5. **Priorities 20 through 28 — existence,** resolved in this order: `program_id` in path or body → `ERR_PROGRAM_NOT_FOUND`; `location_id` in path or body → `ERR_LOCATION_NOT_FOUND`; the challenge id in the path → `ERR_CHALLENGE_NOT_FOUND`; `subgrantee_id` in path or body → `ERR_SUBGRANTEE_NOT_FOUND`; `application_id` in path or body → `ERR_APPLICATION_NOT_FOUND`; `award_id` in path or body → `ERR_AWARD_NOT_FOUND`; the milestone id in the path, which must belong to the award named earlier in the path → `ERR_MILESTONE_NOT_FOUND`; the audit id in the path, which must likewise belong to that award, and the environmental-review sub-path, which must resolve to an existing review of that award → `ERR_AUDIT_NOT_FOUND`; and, for environmental-review sub-actions, the award having a review row at all → `ERR_ENVIRONMENTAL_REVIEW_NOT_FOUND`.
6. **Priority 30 — resource ownership** → `ERR_NOT_RESOURCE_OWNER`, as described in §2.1.
7. **Priority 32 — segregation of duties** → `ERR_SEGREGATION_OF_DUTIES`, as described in §2.6.
8. **Priority 40 — program phase** → `ERR_PROGRAM_STATE_INVALID`. Location ingestion requires `DRAFT` or `CHALLENGE_OPEN`. Filing a challenge and appending challenge evidence require `CHALLENGE_OPEN`. The five adjudication actions — triage, close-rebuttal, request-additional-evidence, determine and resubmit — are permitted in `CHALLENGE_OPEN`, `CHALLENGE_CLOSED` or `SCORING`, which is precisely what lets a late determination cascade into scoring. Opening the challenge window requires `DRAFT`; closing it requires `CHALLENGE_OPEN`; opening scoring requires `CHALLENGE_CLOSED`; closing allocation, creating score sheets and selecting applications require `SCORING`. Subgrantee, application and location-claim operations require `CHALLENGE_OPEN`, `CHALLENGE_CLOSED` or `SCORING`. `ALLOCATION_CLOSED` blocks every program-scoped mutation.
9. **Priority 41 — challenge state** → `ERR_CHALLENGE_STATE_INVALID`. Evidence append requires `SUBMITTED`, `REBUTTAL_OPEN`, `UNDER_REVIEW` or `DEFICIENT`; triage requires `SUBMITTED`; close-rebuttal requires `REBUTTAL_OPEN`; request-additional-evidence and determine require `UNDER_REVIEW`; resubmit requires `DEFICIENT`. `SUSTAINED` and `REJECTED` are terminal and admit no call at all.
10. **Priority 42 — subgrantee state** → `ERR_SUBGRANTEE_STATE_INVALID`. Beginning a capability review requires `REGISTERED` or `REMEDIATION_REQUIRED`; recording a determination requires `UNDER_CAPABILITY_REVIEW`; submitting remediation requires `REMEDIATION_REQUIRED`. `DISQUALIFIED` is terminal.
11. **Priority 43 — application state** → `ERR_APPLICATION_STATE_INVALID`. Creating a location claim requires `DRAFT` or `RETURNED_FOR_CURE`; submitting requires `DRAFT` or `RETURNED_FOR_CURE`; returning for cure requires `SUBMITTED`; score-sheet creation requires `SUBMITTED` or `RESCORE_REQUIRED`; selection requires `SCORED`. `AWARDED` and `NOT_SELECTED` are terminal.
12. **Priority 44 — obligation eligibility.** Award obligation requires the application to be `SELECTED`; a `SCORED` or `NOT_SELECTED` application cannot be obligated → `ERR_APPLICATION_NOT_SELECTED`.
13. **Priority 45 — award state** → `ERR_AWARD_STATE_INVALID`. Environmental-review actions require `OBLIGATED`; authorising construction requires `OBLIGATED` with a cleared review; milestone operations require `CONSTRUCTION_AUTHORIZED` or `IN_CONSTRUCTION`; compliance-audit operations require `IN_CONSTRUCTION` or `CLOSED`. `TERMINATED` is terminal.
14. **Priority 46 — milestone state** → `ERR_MILESTONE_STATE_INVALID`. Submitting evidence requires `PLANNED` or `REJECTED`; verification requires `EVIDENCE_SUBMITTED`; disbursement requires `APPROVED`. `DISBURSED` and `VOIDED` are terminal, and a `HELD` milestone accepts no direct call — it returns to `EVIDENCE_SUBMITTED` only through remediation verification on the audit that held it.
15. **Priority 47 — audit state** → `ERR_AUDIT_STATE_INVALID`. Recording a result requires `SCHEDULED`; issuing a clawback notice requires `FAILED` or `APPEALED`; appealing requires `CLAWBACK_NOTICE_ISSUED`; resolving with settlement requires `CLAWBACK_NOTICE_ISSUED` while resolving with waiver requires `APPEALED`; verifying remediation requires `FAILED`. `PASSED`, `REMEDIATED`, `CLAWBACK_SETTLED` and `CLAWBACK_WAIVED` are terminal.
16. **Priority 48 — environmental review state** → `ERR_EHP_STATE_INVALID`. Recording a determination requires `SCREENING` or `EA_REQUIRED`; clearing requires `CATEGORICAL_EXCLUSION`, `MITIGATION_REQUIRED` or `BLOCKED`. `BLOCKED` is deliberately admitted by this check so that the domain refusal at priority 56 is the error the caller actually sees. `CLEARED` is terminal.
17. **Priority 49 — allocation gate.** Application selection and award obligation require `scoring_posture` to be `OPEN`; `FROZEN` and `RESTRICTED` both block them → `ERR_SCORING_POSTURE_RESTRICTED`.
18. **Priority 50 — challenge version guard** → `ERR_STALE_CHALLENGE_VERSION`.
19. **Priority 51 — application version guard** → `ERR_STALE_APPLICATION_VERSION`.
20. **Priority 55 — clearance precondition.** Authorising construction requires the award's environmental review to be `CLEARED` → `ERR_EHP_NOT_CLEARED`.
21. **Priority 56 — adverse effect.** Clearing is refused when the review is `BLOCKED` on the `ADVERSE_EFFECT` pathway → `ERR_EHP_ADVERSE_EFFECT_BLOCKING`.
22. **Priority 60 — award scope.** Every id in `built_location_ids` on evidence submission, in `planned_location_ids` on milestone creation, and in `failed_location_ids` on result recording must name a location whose `eligibility_state` is `AWARD_BOUND` under this award, meaning its `awarded_award_id` equals the award's `id` → `ERR_LOCATION_NOT_IN_AWARD_SCOPE`.
23. **Priority 61 — program scope.** A challenge's location must belong to the same program as the challenge, and a claim's location must belong to the application's program → `ERR_PROGRAM_SCOPE_MISMATCH`.
24. **Priority 65 — challenge window** → `ERR_CHALLENGE_WINDOW_CLOSED`.
25. **Priority 66 — application window** → `ERR_APPLICATION_WINDOW_CLOSED`.
26. **Priority 67 — rebuttal deadline** → `ERR_REBUTTAL_DEADLINE_NOT_REACHED`.
27. **Priority 68 — audit window buffer** → `ERR_AUDIT_WINDOW_BUFFER_CONFLICT`.
28. **Priority 69 — claim window overlap** → `ERR_LOCATION_CLAIM_WINDOW_CONFLICT`.
29. **Priority 70 — window ordering.** On application creation `proposed_construction_start` must be strictly before `proposed_construction_end`; on audit creation `window_start` strictly before `window_end`; on program creation `challenge_window_start` strictly before `challenge_window_end` and `application_window_start` strictly before `application_window_end` → `ERR_WINDOW_ORDER_INVALID`.
30. **Priority 75 — duplicate challenge** → `ERR_DUPLICATE_CHALLENGE`.
31. **Priority 76 — evidence standard** → `ERR_EVIDENCE_STANDARD_NOT_MET`.
32. **Priority 77 — rebuttal prevails** → `ERR_REBUTTAL_PREVAILS`.
33. **Priority 78 — rebuttal rounds exhausted** → `ERR_REBUTTAL_ROUND_EXHAUSTED`.
34. **Priority 79 — resubmission limits** → `ERR_RESUBMISSION_LIMIT_REACHED`.
35. **Priority 80 — minimum speed commitment** → `ERR_SPEED_COMMITMENT_BELOW_MINIMUM`.
36. **Priority 81 — minimum match** → `ERR_MATCH_BELOW_MINIMUM`.
37. **Priority 82 — applicant qualification.** Score-sheet creation and award obligation both require the application's subgrantee to be `QUALIFIED` → `ERR_SUBGRANTEE_NOT_QUALIFIED`.
38. **Priority 83 — eligible denominator.** Score-sheet creation requires at least one location claim in `CLAIMED_ELIGIBLE`, so the final cost denominator is at least 1 → `ERR_NO_ELIGIBLE_LOCATIONS`.
39. **Priority 84 — uniqueness of addresses and claims** → `ERR_DUPLICATE_LOCATION_ADDRESS`.
40. **Priority 85 — award uniqueness** → `ERR_AWARD_ALREADY_EXISTS`.
41. **Priority 86 — final milestone conflict** → `ERR_FINAL_MILESTONE_CONFLICT`.
42. **Priority 90 — everything deferred** → `ERR_ALL_LOCATIONS_EHCL_DEFERRED`.
43. **Priority 91 — appropriation exhausted** → `ERR_PROGRAM_FUNDS_EXHAUSTED`.
44. **Priority 92 — nothing payable** → `ERR_NO_DISBURSABLE_AMOUNT`.
45. **Priority 93 — clawback amount** → `ERR_CLAWBACK_AMOUNT_INVALID`.

The practical consequence of this ordering is that state checks always precede business checks: an attempt to sustain a challenge whose evidence is insufficient *and* whose state is wrong reports the state error, and an obligation attempt on a program with a stale score sheet reports the posture error at priority 49 rather than reaching the fiscal checks at priorities 90 and 91.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program Round and Its Eligible-Location Inventory

A `ProgramAdmin` opens a round by creating a **Grant Program**, supplying a `name`, the appropriation `fiscal_year`, and `total_appropriation_cents` — the total federal allocation available to obligate, which must be greater than zero. The four window boundaries are also supplied at creation: `challenge_window_start` and `challenge_window_end` bound the period during which classifications may be contested, and `application_window_start` and `application_window_end` bound the period during which subgrantee applications may be submitted. Both windows are half-open: the start instant is inside the window and the end instant is outside it.

Ten policy parameters may be supplied at creation and otherwise take their programme defaults. `min_match_pct` is the minimum non-federal match an application must offer and defaults to 25.0. `holdback_pct` is the share of the obligation withheld until the final milestone and defaults to 10.0 — so by default a subgrantee can draw down at most ninety percent of its obligation before that final draw. Four speed thresholds define the classification bands: `unserved_down_mbps_threshold` (default 25) and `unserved_up_mbps_threshold` (default 3) are the download and upload speeds *strictly below* which a location is unserved, while `served_down_mbps_threshold` (default 100) and `served_up_mbps_threshold` (default 20) are the speeds *at or above* which a location may be considered served. `max_latency_ms` is the round-trip latency strictly above which reported service is treated as unreliable, and defaults to 100. `ehcl_threshold_cents` is the extremely-high-cost-location threshold, strictly above which a single claimed location is an extremely high cost location, and defaults to 2500000 — twenty-five thousand dollars per location. `ehcl_waiver_enabled` defaults to true, and when true those extremely-high-cost claims are deferred out of the award at obligation time rather than funded.

On creation the program starts in `DRAFT`, its `uncommitted_balance_cents` equals `total_appropriation_cents`, `obligated_balance_cents` and `disbursed_balance_cents` are both 0, and `scoring_posture` is `FROZEN`.

Locations arrive one at a time from the national map. An `EligibleLocation` is ingested with its `program_id`, the map's broadband serviceable location identifier `address_id`, the reported performance triple `reported_down_mbps`, `reported_up_mbps` and `reported_latency_ms`, the `reported_technology`, and `reporting_provider_user_id` — the opaque identifier of the provider that reported this service, which later becomes the only provider identity permitted to file rebuttal evidence against challenges on this location. An `address_id` must be unique within a program; a repeat is refused with `ERR_DUPLICATE_LOCATION_ADDRESS`. Reported technology is one of `FIBER`, `CABLE`, `DSL`, `LICENSED_FIXED_WIRELESS`, `UNLICENSED_FIXED_WIRELESS`, `GEOSTATIONARY_SATELLITE` or `LEO_SATELLITE`.

Classification is decided at ingestion and stamped into `classification_status`, with `classification_source` recorded as `NATIONAL_MAP`. The decision walks four tests in a fixed order and the first one that matches wins, so a later test never overrides an earlier one. First, if the reported technology is `UNLICENSED_FIXED_WIRELESS` or `GEOSTATIONARY_SATELLITE`, the location is `UNSERVED` regardless of the speeds reported, because federal rules treat those two technologies as unreliable. Second, if `reported_latency_ms` is strictly greater than the program's `max_latency_ms`, the location is `UNSERVED`; latency exactly equal to the threshold does not trigger this branch. Third, if `reported_down_mbps` is strictly below `unserved_down_mbps_threshold`, or `reported_up_mbps` is strictly below `unserved_up_mbps_threshold`, the location is `UNSERVED`; a location reporting exactly 25 down and 3 megabits per second up under the default thresholds therefore escapes this branch. Fourth, if `reported_down_mbps` is strictly below `served_down_mbps_threshold`, or `reported_up_mbps` is strictly below `served_up_mbps_threshold`, the location is `UNDERSERVED` — which is where that exactly-25-by-3 location lands. Otherwise the location is `SERVED`, and a location reporting exactly 100 down and 20 up under the default thresholds is `SERVED` rather than `UNDERSERVED`. Speeds are compared as the declared numbers with no rounding, and latency is compared as integers.

Each location tracks two independent state axes, and the pair is central to the domain. The **eligibility axis**, `eligibility_state`, follows the map, challenge and allocation lifecycle through `MAPPED`, `CHALLENGED`, `AFFIRMED`, `RECLASSIFIED`, `AWARD_BOUND` and the terminal `DEFERRED_HIGH_COST`, starting at `MAPPED`. The **service axis**, `service_state`, follows physical deployment through `NOT_BUILT`, `UNDER_CONSTRUCTION`, `SERVICE_AVAILABLE`, `CERTIFIED` and `AUDIT_FAILED`, starting at `NOT_BUILT`. The two evolve independently: a location can sit at `AWARD_BOUND` while still `NOT_BUILT`, and it can travel all the way to `CERTIFIED` without its eligibility axis ever changing again. Each location also carries `challenge_count`, the number of challenge rows recorded against it, re-derived when a challenge is filed against the location and again when that challenge is triaged; `awarded_award_id`, which names the award that bound the location and is null while none has; and `certified_at`, the logical instant at which the service axis reached `CERTIFIED`, null while it has not.

Phase advancement is a `ProgramAdmin` responsibility. Opening the challenge window moves the program `DRAFT → CHALLENGE_OPEN` and requires that `location_count_total` be at least 1 and that the logical clock sit inside the half-open challenge window, at or after `challenge_window_start` and strictly before `challenge_window_end`; the posture is recomputed and remains `FROZEN`. Closing the challenge window moves it `CHALLENGE_OPEN → CHALLENGE_CLOSED` and requires that the clock have reached `challenge_window_end` and that no challenge of this program still sit in `SUBMITTED`. That close does three things: every challenge of the program still in `REBUTTAL_OPEN` is advanced to `UNDER_REVIEW` with its `rebuttal_deadline` forced to the current instant; every location of the program still in `MAPPED` moves on the eligibility axis `MAPPED → AFFIRMED` with its `classification_source` left as `NATIONAL_MAP`; and the posture is recomputed to `RESTRICTED` if at least one score sheet of the program is `STALE`, otherwise to `OPEN`. Opening scoring moves the program `CHALLENGE_CLOSED → SCORING`, requires that the clock have reached `application_window_end`, and requires that no challenge of the program sit in `SUBMITTED` or `REBUTTAL_OPEN` — a challenge left in `UNDER_REVIEW` is deliberately allowed through, and that is exactly what makes a late determination cascade into a live scoring phase. The posture is recomputed on the same rule. Closing allocation moves the program `SCORING → ALLOCATION_CLOSED`, requires that no application of the program still sit in `SELECTED`, then moves every application of the program still open to `NOT_SELECTED` — `DRAFT → NOT_SELECTED`, `SUBMITTED → NOT_SELECTED`, `RETURNED_FOR_CURE → NOT_SELECTED`, `SCORED → NOT_SELECTED` and `RESCORE_REQUIRED → NOT_SELECTED`, releases each of those applications' claims from `CLAIMED_ELIGIBLE` or `CLAIMED_INELIGIBLE` to `RELEASED`, and recomputes the posture to `FROZEN`.

### 3.2. Filing a Challenge and Building the Evidentiary Record

While the program is `CHALLENGE_OPEN` and the logical clock sits inside the half-open challenge window, a `Challenger` or a `Provider` files a **Challenge** against a location's classification by supplying `program_id`, `location_id`, its own `challenger_type`, the `asserted_classification` it says is correct, and a `rationale` giving the narrative basis. The `challenger_type` is one of `PROVIDER`, `COMMUNITY`, `LOCAL_GOVERNMENT` or `NONPROFIT`, and `asserted_classification` is one of `SERVED`, `UNDERSERVED` or `UNSERVED`. Filing outside the window is refused with `ERR_CHALLENGE_WINDOW_CLOSED`; a challenged location belonging to a different program than the one named is refused with `ERR_PROGRAM_SCOPE_MISMATCH`. At most one non-terminal challenge may exist for a given pairing of contested location and filing identity, so a second live filing by the same party against the same location is refused with `ERR_DUPLICATE_CHALLENGE`.

A new challenge starts in `challenge_state` `SUBMITTED`, records the filer's `X-User-ID` as `submitter_user_id`, sets `rebuttal_round` and `resubmission_count` to 0, and stamps `required_sufficiency_threshold` from the challenger type: 60.00 when `challenger_type` is `PROVIDER`, and 40.00 for every other challenger type. The full lifecycle runs `SUBMITTED`, `REBUTTAL_OPEN`, `UNDER_REVIEW`, `DEFICIENT` and the two terminal outcomes `SUSTAINED` and `REJECTED`.

Evidence is appended one item at a time, and each **ChallengeEvidence** item is immutable once written. Each item names its parent through `challenge_id`, taken from the path rather than the payload. An append supplies `evidence_type`, the `collected_at` instant at which the artefact was gathered, a free-text `description`, and the concurrency guard `expected_challenge_version` described in §2.10. The permitted evidence types are `SPEED_TEST`, `SUBSCRIBER_BILL`, `SERVICE_DENIAL_LETTER`, `FIELD_SURVEY`, `PROVIDER_ATTESTATION`, `MAP_DATA_EXPORT` and `CONSTRUCTION_PERMIT_RECORD`. Which side an item lands on is decided by identity, never by the caller's role: `submitter_side` is `CHALLENGE` when the caller's `X-User-ID` equals the challenge's `submitter_user_id`, and `REBUTTAL` for any other permitted caller — which in practice means the challenged location's `reporting_provider_user_id`. Any other caller is refused with `ERR_NOT_RESOURCE_OWNER`. The item records the appending caller in its own `submitter_user_id`. Appends are permitted while the challenge is `SUBMITTED`, `REBUTTAL_OPEN`, `UNDER_REVIEW` or `DEFICIENT`, and only while the program is `CHALLENGE_OPEN` and the clock is inside the challenge window.

Each item's contribution is weighted by type and discounted by age. The `base_weight` comes from the type: a `PROVIDER_ATTESTATION` is worth 35, a `SERVICE_DENIAL_LETTER` 30, a `SUBSCRIBER_BILL` 25, a `FIELD_SURVEY` 20, a `CONSTRUCTION_PERMIT_RECORD` 20, a `SPEED_TEST` 15 and a `MAP_DATA_EXPORT` 10. Age is measured in whole days from the artefact's `collected_at` to the challenge's `created_at`: take the elapsed time between those two instants, express it in seconds, divide by the 86400 seconds in a day, and discard any fraction. The resulting `recency_multiplier` is 1.0 when that age is 180 days or fewer, 0.5 when it is between 181 and 365 days inclusive, and 0 when it is more than 365 days — that is, evidence stays at full weight for half a year, is halved for the remainder of the first year, and counts for nothing once it is more than a year old. Each item's `weighted_value` is its `base_weight` multiplied by its `recency_multiplier`, rounded half up to 2 decimal places. An item's `evidence_state` is `ACCEPTED` when its `recency_multiplier` is greater than zero and `STALE_EXCLUDED` when the multiplier is zero.

Two running totals live on the challenge, and both are recomputed on every append. `evidence_sufficiency_score` is the sum of `weighted_value` over `ACCEPTED` items on the `CHALLENGE` side, and `rebuttal_strength_score` is the same sum over `ACCEPTED` items on the `REBUTTAL` side; each per-item value is rounded to 2 decimal places first, the rounded values are then summed, and the sum is rounded to 2 decimal places again. Alongside them the challenge carries `distinct_evidence_type_count`, the number of distinct `evidence_type` values among `ACCEPTED` items on the `CHALLENGE` side. `STALE_EXCLUDED` items contribute nothing to either score and are excluded from the distinct-type count entirely.

Whether the record meets its **evidence standard** turns on two conditions, and both must hold. The first is common to every challenger type: `evidence_sufficiency_score` must be at least `required_sufficiency_threshold`. The second is variant-specific. Under the **provider standard**, which applies when `challenger_type` is `PROVIDER`, the threshold is 60.00 and the record must also contain at least one `ACCEPTED` `CHALLENGE`-side item whose `evidence_type` is `PROVIDER_ATTESTATION` or `MAP_DATA_EXPORT`; the distinct-type rule does not apply to providers at all. Under the **community standard**, which applies when `challenger_type` is `COMMUNITY`, `LOCAL_GOVERNMENT` or `NONPROFIT`, the threshold is 40.00 and `distinct_evidence_type_count` must be at least 2; no privileged evidence type is required. A challenge that fails its standard where the standard is required is refused with `ERR_EVIDENCE_STANDARD_NOT_MET`.

### 3.3. Adjudicating a Challenge

Triage is the `EligibilityAnalyst`'s decision to take a challenge seriously. It moves the challenge `SUBMITTED → REBUTTAL_OPEN` and requires the program to be in `CHALLENGE_OPEN`, `CHALLENGE_CLOSED` or `SCORING` and the evidence standard of §3.2 to be met in full — the score at or above the challenger type's threshold, plus the provider's privileged-item requirement or the community party's two-distinct-type requirement as applicable. Triage sets `rebuttal_round` to 1, stamps `rebuttal_deadline` at thirty days after the current logical instant, records the acting analyst as `triaged_by_user_id`, and on the eligibility axis moves the contested location `MAPPED → CHALLENGED` while re-deriving that location's `challenge_count`.

Once the rebuttal window has done its work the analyst closes it, moving the challenge `REBUTTAL_OPEN → UNDER_REVIEW` and freezing `rebuttal_strength_score` for that round. Closing is permitted either once the logical clock has reached `rebuttal_deadline` or, earlier, as soon as `rebuttal_strength_score` is greater than zero — a rebuttal on the record makes waiting pointless. Closing before the deadline with no rebuttal evidence at all is refused with `ERR_REBUTTAL_DEADLINE_NOT_REACHED`.

From `UNDER_REVIEW` the analyst may reopen the record for another round instead of deciding it, moving the challenge `UNDER_REVIEW → REBUTTAL_OPEN` with a `reason`. Reopening requires `rebuttal_round` to be strictly below the ceiling of two rounds and requires the program to be `CHALLENGE_OPEN` or `CHALLENGE_CLOSED`, so the negotiation cycle cannot be restarted once scoring has opened. It increments `rebuttal_round` and re-stamps `rebuttal_deadline` at thirty days past the current instant. Attempting a third round, once `rebuttal_round` has reached two, is refused with `ERR_REBUTTAL_ROUND_EXHAUSTED`.

Determination is the terminal act, taken by an `EligibilityAnalyst` or a `ProgramAdmin` from `UNDER_REVIEW`, supplying an `outcome` of `SUSTAINED`, `REJECTED` or `DEFICIENT` and optionally a `determination_note`. Whatever the outcome, the acting caller may not be the one recorded in `triaged_by_user_id`, and the recorded outcome is stamped into `outcome` while the caller is stamped into `determined_by_user_id`. The three branches diverge sharply and each carries its own preconditions.

A `REJECTED` determination moves the challenge `UNDER_REVIEW → REJECTED` and, on the eligibility axis, moves the location `CHALLENGED → AFFIRMED` with `classification_status` and `classification_source` left exactly as they were. It has no further preconditions beyond state and the segregation check.

A `DEFICIENT` determination moves the challenge `UNDER_REVIEW → DEFICIENT` and likewise moves the location `CHALLENGED → AFFIRMED`, leaving the classification alone. It requires that `rebuttal_strength_score` be greater than or equal to `evidence_sufficiency_score` — the rebuttal has tied or prevailed, so the challenge record as filed is deficient rather than wrong. `DEFICIENT` is exactly the complement of the refusal that guards a sustain, and it is the only outcome that reopens the resubmission cycle.

A `SUSTAINED` determination moves the challenge `UNDER_REVIEW → SUSTAINED` and requires two things beyond state and segregation: the evidence standard must still be met at determination time (`evidence_sufficiency_score` at or above `required_sufficiency_threshold`, with the applicable variant condition satisfied), and `evidence_sufficiency_score` must be **strictly greater** than `rebuttal_strength_score`. A sustain attempted while the rebuttal ties or exceeds the challenge is refused with `ERR_REBUTTAL_PREVAILS`; a sustain attempted on a record below its standard is refused with `ERR_EVIDENCE_STANDARD_NOT_MET`.

A sustain then runs a four-hop cascade, and all four hops belong to that single request.

- **Hop 1.** The location's `classification_status` is re-stamped from the challenge's `asserted_classification`, its `classification_source` becomes `CHALLENGE_DETERMINATION`, and on the eligibility axis it moves `CHALLENGED → RECLASSIFIED`.
- **Hop 2**, caused by hop 1. Because the location's classification is now `UNSERVED` or `UNDERSERVED`, every location claim on that location sitting in `CLAIMED_INELIGIBLE` flips to `CLAIMED_ELIGIBLE`. For each owning application, `confirmed_location_count` rises by one, `eligible_project_cost_cents` rises by that claim's `claimed_cost_cents`, and `final_cost_per_location_cents` is recomputed.
- **Hop 3**, caused by hop 2. Because that application's confirmed location count changed, each of its score sheets in `score_state` `FINAL` moves to `STALE`, the application moves `SCORED → RESCORE_REQUIRED` with `rescore_required_reason` set to `CHALLENGE_RECLASSIFICATION`, and the application's `version` increments by one.
- **Hop 4**, caused by hop 3. Because the program's `stale_score_sheet_count` has now reached at least one, the program's `scoring_posture` moves `OPEN → RESTRICTED`, which blocks award obligation across the entire program until every stale sheet has been superseded.

A `DEFICIENT` challenge may be resubmitted by the party that filed it. Resubmission moves the challenge `DEFICIENT → SUBMITTED` with an optionally revised `rationale`, requires that the caller's `X-User-ID` equal `submitter_user_id`, requires `resubmission_count` to be strictly below the limit of two, and requires the program to be `CHALLENGE_OPEN` with the logical clock still strictly before `challenge_window_end`. It increments `resubmission_count`, resets `rebuttal_round` to 0, clears `rebuttal_deadline`, `triaged_by_user_id` and `outcome` back to null, and on the eligibility axis moves the location `AFFIRMED → CHALLENGED` — the same challenge re-entering review, so `challenge_count` is unchanged. A resubmission attempted once `resubmission_count` has reached two is refused with `ERR_RESUBMISSION_LIMIT_REACHED`.

### 3.4. Qualifying an Applicant

A `ProgramAdmin` registers a prospective **Subgrantee** under a program with its `legal_name`, its `ein` as reported, its declared unaudited `net_assets_cents`, the `requested_amount_cents` it says it will request (which must be greater than zero and forms the basis of the financial test), its declared `key_personnel_count`, and `has_prior_federal_award` stating whether it has administered a prior federal broadband award, defaulting to false. Registration starts `capability_state` at `REGISTERED` with `remediation_count` and `withdrawn_personnel_count` both at 0. The capability lifecycle runs `REGISTERED`, `UNDER_CAPABILITY_REVIEW`, `QUALIFIED`, `REMEDIATION_REQUIRED`, `SUSPENDED` and the terminal `DISQUALIFIED`.

A `CapabilityReviewer` opens review, moving the applicant `REGISTERED → UNDER_CAPABILITY_REVIEW`, permitted while the program is in any of `DRAFT`, `CHALLENGE_OPEN`, `CHALLENGE_CLOSED` or `SCORING`. Opening records the acting reviewer as `capability_reviewer_user_id` and sets `review_variant` to `INITIAL` on a first review, or to `REMEDIATION` when the review is being reopened after a remediation submission.

The determination is where the arithmetic happens. The same reviewer who opened the review — the check compares `X-User-ID` to `capability_reviewer_user_id` — supplies a `technical_raw_score` and optionally a `determination_note`, and the server derives four numbers. The **technical component**, `technical_component`, is the smaller of 40.00 and the supplied `technical_raw_score`, rounded half up to 2 decimals; it is capped at 40.00. The **financial component**, `financial_component`, tests liquidity: the applicant's liquidity requirement is one quarter of `requested_amount_cents`; the coverage ratio is the applicable net-asset basis divided by that requirement, capped at 1.0 so that over-coverage earns nothing extra; 35.00 multiplied by that capped ratio, itself capped at 35.00, is then multiplied by the variant's haircut, and the product is rounded half up to 2 decimals. The haircut is applied inside that single rounding step, not afterwards. The **managerial component**, `managerial_component`, awards 5 points per person in the applicable personnel basis plus a flat 5 points when `has_prior_federal_award` is true, takes the smaller of that sum and 25.00, and rounds half up to 2 decimals; it is capped at 25.00. Finally `capability_index` is the sum of the three rounded components, rounded half up to 2 decimals.

Two variants select the inputs, and the difference is deliberate: identical submitted figures score strictly lower on the second pass. Under the **initial review** variant, in force when `review_variant` is `INITIAL`, the net-asset basis is the unaudited `net_assets_cents`, the haircut is 1.00 (no reduction at all), and the personnel basis is the full declared `key_personnel_count`. Under the **remediation review** variant, in force when `review_variant` is `REMEDIATION`, the net-asset basis is the audited restatement `audited_net_assets_cents`, the haircut is 0.85, and the personnel basis is `key_personnel_count` minus `withdrawn_personnel_count`.

The determination then routes the applicant to one of three states, and the routing is exhaustive. The applicant becomes `QUALIFIED` — moving `UNDER_CAPABILITY_REVIEW → QUALIFIED` — when `capability_index` is at least 70.00 **and** `technical_component` is at least 24.00 **and** `financial_component` is at least 17.50. It moves `UNDER_CAPABILITY_REVIEW → REMEDIATION_REQUIRED` when `review_variant` is `INITIAL` and either `capability_index` falls in the band from 55.00 up to but not including 70.00, or `capability_index` reaches 70.00 while `technical_component` is below 24.00 or `financial_component` is below 17.50 — a strong overall score with a weak leg still buys only a second chance. It moves `UNDER_CAPABILITY_REVIEW → DISQUALIFIED` when `capability_index` is below 55.00, or when `review_variant` is `REMEDIATION` and `capability_index` is below 70.00. In all three branches the raw score and all four derived numbers are stamped onto the applicant. Disqualification additionally moves every application of that applicant sitting in `DRAFT`, `SUBMITTED` or `RETURNED_FOR_CURE` to `NOT_SELECTED`.

An applicant in `REMEDIATION_REQUIRED` gets exactly one corrective pass. The applicant itself, or a `ProgramAdmin` acting for it, submits a remediation carrying `audited_net_assets_cents` and `withdrawn_personnel_count`; a `Subgrantee` caller's `X-User-ID` must equal the applicant's own `id`. The submission requires `remediation_count` to be 0, sets it to 1, sets `review_variant` to `REMEDIATION`, stamps both payload figures onto the applicant, and moves it `REMEDIATION_REQUIRED → UNDER_CAPABILITY_REVIEW` for the second determination.

The applicant's `open_noncompliance_count` counts its awards whose `compliance_state` is `NONCOMPLIANT`; it is the hook by which a failed deployment audit suspends and later reinstates a qualified applicant, as described in §3.9.

### 3.5. Assembling and Submitting an Application

An **Application** is opened as a draft by the applicant itself or by a `ProgramAdmin` acting for it, naming `program_id` and `subgrantee_id` — and when the caller's role is `Subgrantee`, `subgrantee_id` must equal the caller's `X-User-ID`. The draft carries the applicant's whole offer. `match_offer_pct` is the non-federal match percentage offered. `committed_down_mbps`, `committed_up_mbps` and `committed_latency_ms` are the download speed, upload speed and round-trip latency promised at every awarded location. `low_cost_plan_price_cents` is the monthly price of the proposed low-cost service option, and `participates_in_state_affordability_program` states whether the applicant will honour the state affordability subsidy, defaulting to false. The workforce offer is three fields: `has_dbe_plan` and `has_union_agreement` state whether a disadvantaged-business-enterprise plan and a project labour agreement are attached, both defaulting to false, and `local_hire_pct` is the percentage of construction hours committed to local hires, defaulting to 0. Finally `proposed_construction_start` and `proposed_construction_end` bound the proposed construction window, half-open with the start inside and the end outside, and the start must be strictly before the end. A new draft starts with `application_state` `DRAFT` and with `claim_count` and `returned_for_cure_count` at 0. The `application_state` axis runs `DRAFT`, `SUBMITTED`, `RETURNED_FOR_CURE`, `SCORED`, `RESCORE_REQUIRED`, `SELECTED` and the two terminal states `AWARDED` and `NOT_SELECTED`.

Locations are attached to a draft one at a time as **LocationClaims**. A claim names `application_id`, `location_id` and `claimed_cost_cents` — the deployment cost the applicant attributes to that single location, which must be greater than zero — and may be filed only by the owning applicant while the application is `DRAFT` or `RETURNED_FOR_CURE`. A claim's location must belong to the application's program, or the request is refused with `ERR_PROGRAM_SCOPE_MISMATCH`; the same location may not be claimed twice by one application, or the request is refused with `ERR_DUPLICATE_LOCATION_ADDRESS`. Because two applications cannot build the same location at the same time, a new claim's construction window — taken from its application as `proposed_construction_start` through `proposed_construction_end`, half-open — must not overlap the window of any other non-`RELEASED` claim on the same location; touching endpoints, where one window's end instant equals the other's start instant, are allowed, and a genuine overlap is refused with `ERR_LOCATION_CLAIM_WINDOW_CONFLICT`.

The claim's `claim_state` is decided at creation from the claimed location's classification: `CLAIMED_ELIGIBLE` when the location's `classification_status` is `UNSERVED` or `UNDERSERVED`, and `CLAIMED_INELIGIBLE` when it is `SERVED`. Over its life a claim may also reach `AWARD_BOUND`, `EHCL_DEFERRED` or `RELEASED`. Two further fields are stamped later, at award obligation, and are absent until then: `is_ehcl`, true exactly when `claimed_cost_cents` is strictly greater than the program's `ehcl_threshold_cents`; and `match_share_cents`, the claim's per-location share of the non-federal match.

Four aggregates on the application are re-derived after every claim change. `claim_count` counts claims in `CLAIMED_ELIGIBLE`, `CLAIMED_INELIGIBLE`, `AWARD_BOUND` or `EHCL_DEFERRED`; `confirmed_location_count` counts the narrower set of claims in `CLAIMED_ELIGIBLE` or `AWARD_BOUND`; `total_project_cost_cents` sums `claimed_cost_cents` over the wider set; and `eligible_project_cost_cents` sums it over the narrower set. Claims in `RELEASED` are excluded from all four.

Cost per location is computed in two variants, and both are stamped at submission and recomputed whenever any claim of the application changes `claim_state` — through the reclassification cascade of §3.3, through extremely-high-cost deferral, or through release. The **preliminary** variant divides `total_project_cost_cents` by `claim_count` and lands in `preliminary_cost_per_location_cents`; its denominator counts every claim regardless of the claimed location's classification, and the figure is shown on the application but used for nothing else. The **final** variant divides `eligible_project_cost_cents` by `confirmed_location_count` and lands in `final_cost_per_location_cents`; its denominator counts only claims on locations that are `UNSERVED` or `UNDERSERVED`, so the very same claim set yields a different per-location cost, and this is the figure that drives both the scoring cost tier and the award obligation. Each quotient is rounded half up to a whole cent. The preliminary denominator can never be zero at submission because at least one claim is required to submit; the final figure stays null while the application is unsubmitted, and a final denominator of zero at scoring time is refused with `ERR_NO_ELIGIBLE_LOCATIONS`.

Submission is the applicant's own act and moves the application `DRAFT → SUBMITTED`. It requires the caller's `X-User-ID` to equal `subgrantee_id`, the program to be `CHALLENGE_OPEN` or `CHALLENGE_CLOSED`, the logical clock to sit inside the half-open application window at or after `application_window_start` and strictly before `application_window_end`, `claim_count` to be at least 1, `match_offer_pct` to be at least the program's `min_match_pct`, and `committed_down_mbps` and `committed_up_mbps` to be at least the program's `served_down_mbps_threshold` and `served_up_mbps_threshold` respectively — with the floor stated absolutely as at least 100 megabits per second down and at least 20 up. Submitting outside the window is refused with `ERR_APPLICATION_WINDOW_CLOSED`; a speed commitment under those floors is refused with `ERR_SPEED_COMMITMENT_BELOW_MINIMUM`; a match under the program minimum is refused with `ERR_MATCH_BELOW_MINIMUM`. Submission stamps both cost-per-location variants.

A `ScoringOfficer` or `ProgramAdmin` may hand a submitted application back once, supplying a `cure_reason` and moving it `SUBMITTED → RETURNED_FOR_CURE`. The return requires `returned_for_cure_count` to be 0 and sets it to 1, so the cure cycle `SUBMITTED → RETURNED_FOR_CURE → SUBMITTED` runs at most once. Re-submitting a cured application moves it `RETURNED_FOR_CURE → SUBMITTED`, again requires the caller to be the owning applicant, the clock to be inside the application window and `claim_count` to be at least 1 and `match_offer_pct` to be at least the program's minimum, and recomputes both cost-per-location variants. A submission attempted once `returned_for_cure_count` has reached two is refused with `ERR_RESUBMISSION_LIMIT_REACHED`.

### 3.6. Scoring, Rescoring and Selection

Scoring is a `ScoringOfficer`'s act, performed while the program is `SCORING`, and it produces a **ScoreSheet** for one application. The request names `application_id` and the concurrency guard `expected_application_version`. Beyond the version check it requires the application to be in `SUBMITTED` or `RESCORE_REQUIRED`, the application's applicant to be `QUALIFIED` — otherwise `ERR_SUBGRANTEE_NOT_QUALIFIED` — at least one location claim in `CLAIMED_ELIGIBLE`, so that `confirmed_location_count` — the final cost denominator — is at least 1, otherwise `ERR_NO_ELIGIBLE_LOCATIONS` — and the acting officer not to be the applicant's `capability_reviewer_user_id`. The sheet records the acting officer as `scored_by_user_id` and freezes two snapshots taken at scoring time: `basis_final_cost_per_location_cents`, the application's `final_cost_per_location_cents` as it stood, and `basis_confirmed_location_count`, its `confirmed_location_count` as it stood. Those snapshots are what make a sheet auditable after the underlying application has moved on.

The total is built from four independently capped components, so a component's raw sum may exceed its cap and be clipped before anything else happens to it.

`cost_points` is a tiered selection on the application's final cost per location, worth at most 30.00. It is 30.00 when that cost is at most 100000 cents — a thousand dollars a location — 24.00 when it is at most 250000, 16.00 when it is at most 500000, 8.00 when it is at most 1000000, and 0.00 above that. Each tier boundary is inclusive on its upper edge, so a cost of exactly 250000 cents earns 24.00 rather than 16.00.

`speed_points` is a capped additive branch worth at most 30.00. It starts from a base of 25.00 for any qualifying commitment, adds 5.00 when `committed_down_mbps` is at least 1000 **and** `committed_up_mbps` is at least 1000 — symmetrical gigabit service — adds a further 2.00 when `committed_latency_ms` is at most 50, and then takes the smaller of that sum and 30.00. An applicant offering symmetrical gigabit at 50 milliseconds therefore raises 32.00 raw and is clipped to 30.00.

`affordability_points` is a capped tiered branch worth at most 20.00. The base is 20.00 when `low_cost_plan_price_cents` is at most 3000 — thirty dollars a month — 14.00 when it is at most 5000, 6.00 when it is at most 7500, and 0.00 above that; a further 5.00 is added when `participates_in_state_affordability_program` is true; and the result is the smaller of that sum and 20.00.

`workforce_points` is a capped mixed branch worth at most 20.00. It adds 5.00 when `has_dbe_plan` is true, 5.00 when `has_union_agreement` is true, and a local-hire contribution of 10.00 multiplied by `local_hire_pct` divided by 100, rounded half up to 2 decimals — so a full local-hire commitment earns the whole 10.00 and a half commitment earns 5.00. The sum is then clipped to 20.00.

The applicant's own strength then multiplies the whole. `capability_multiplier` is 1.05 when the applicant's `capability_index` is at least 90.00, and 1.00 otherwise. The subtotal is the sum of the four component figures as stored; `total_score` is that subtotal multiplied by `capability_multiplier`, rounded half up to 2 decimals, and then capped at 100.00. The multiplier is applied once, to the unrounded subtotal, and the cap is applied last.

Creating the sheet sets its `score_state` to `FINAL`, marks any prior sheet of that application `SUPERSEDED`, sets the application's `current_total_score` to the new `total_score`, moves the application `SUBMITTED → SCORED`, increments the application's `version` by one, and triggers a posture recomputation on the program. A sheet's `score_state` is one of `FINAL`, `STALE` or `SUPERSEDED`.

Rescoring closes the cycle opened by a late reclassification. An application driven to `RESCORE_REQUIRED` by the third hop of the sustain cascade — carrying `rescore_required_reason` of `CHALLENGE_RECLASSIFICATION` and a `STALE` sheet — is scored again under exactly the same preconditions as a first scoring: program in `SCORING`, applicant `QUALIFIED`, `confirmed_location_count` at least 1, the segregation check against `capability_reviewer_user_id`, and a matching `expected_application_version`. A rescore moves the prior `STALE` sheet to `SUPERSEDED`, creates a new sheet in `FINAL`, clears `rescore_required_reason` back to null, sets `current_total_score` to the new total, increments the application's `version` by one, and moves the application `RESCORE_REQUIRED → SCORED`. Because a sustained challenge can recur on a different location, the cycle `SCORED → RESCORE_REQUIRED → SCORED` is unbounded. Once no `STALE` sheet remains, the posture recomputation lifts the program from `RESTRICTED` back to `OPEN` and allocation can proceed.

Selection is a `ProgramAdmin` act that moves an application `SCORED → SELECTED` while the program is `SCORING` and its `scoring_posture` is `OPEN`. A selection attempted while the posture is `RESTRICTED` or `FROZEN` is refused with `ERR_SCORING_POSTURE_RESTRICTED`. Selection has no other side effects — it simply marks the application ready to be obligated.

### 3.7. Obligating an Award

Obligation is a `ProgramAdmin` act naming an `application_id`, and it is the single most consequential computation in the system. The application must be `SELECTED`, or the request is refused with `ERR_APPLICATION_NOT_SELECTED`; the program's `scoring_posture` must be `OPEN`; the applicant must be `QUALIFIED`; and the application must not already have a non-`TERMINATED` award, nor may any claimed location already be `AWARD_BOUND` to another award, or the request is refused with `ERR_AWARD_ALREADY_EXISTS`.

The obligation runs as a single pinned pass of nine steps. The extremely-high-cost test looks circular — per-location cost depends on the retained set and the retained set depends on the test — so the order below is fixed and there is no second deferral pass.

1. The base set is every location claim of the application in `CLAIMED_ELIGIBLE`. Record its count and the sum of its `claimed_cost_cents`. Claims in `CLAIMED_INELIGIBLE` never enter the base set.
2. A preliminary per-location cost is recorded for audit only: the base-set cost sum divided by the base-set count, rounded half up to a whole cent.
3. For every claim in the base set, `is_ehcl` is set to true exactly when its `claimed_cost_cents` is strictly greater than the program's `ehcl_threshold_cents`, and false otherwise.
4. If the program's `ehcl_waiver_enabled` is true and at least one claim is flagged, every flagged claim moves to `claim_state` `EHCL_DEFERRED` and its location moves on the eligibility axis `AFFIRMED → DEFERRED_HIGH_COST`; the retained set is the base set minus the deferred claims and `ehcl_deferred_count` records how many were deferred. Otherwise the retained set is the whole base set and `ehcl_deferred_count` is 0 — which is how a program that disables the waiver funds even an extremely expensive location.
5. If the retained set is empty, the obligation is refused with `ERR_ALL_LOCATIONS_EHCL_DEFERRED`.
6. `total_eligible_cost_cents` is the sum of `claimed_cost_cents` over the retained set, and `final_per_location_cost_cents` is that sum divided by the retained count, rounded half up to a whole cent. This figure is frozen at obligation: even if it now exceeds `ehcl_threshold_cents`, no further deferral occurs.
7. `match_requirement_cents` is computed over the retained set with a pinned rounding order. Walking the retained claims in ascending `created_at` order, each claim's `match_share_cents` is its `claimed_cost_cents` multiplied by the program's `min_match_pct` divided by 100, rounded half up to a whole cent; `match_requirement_cents` is then the exact integer sum of those per-claim shares. Rounding the aggregate product instead — taking `total_eligible_cost_cents` times `min_match_pct` divided by 100 and rounding that once — is explicitly wrong: the two disagree by whole cents whenever individual shares round up.
8. `obligation_amount_cents` is `total_eligible_cost_cents` minus `match_requirement_cents` — the federal share. `holdback_cap_cents` is `obligation_amount_cents` multiplied by the quantity 100 minus the program's `holdback_pct`, divided by 100, rounded half up to a whole cent; it is the cumulative ceiling on everything disbursed before the final milestone, so at the default ten percent holdback a subgrantee can draw at most ninety percent of its obligation across all non-final milestones.
9. If `obligation_amount_cents` exceeds the program's `uncommitted_balance_cents`, the obligation is refused with `ERR_PROGRAM_FUNDS_EXHAUSTED`.

When all nine steps pass, an **Award** is created with `award_state` `OBLIGATED` and `compliance_state` `COMPLIANT`, its `confirmed_location_count` counting the claims now bound to it, `disbursed_to_date_cents` at 0, and `certified_location_count` and `failed_location_count` at 0. Every retained claim moves to `AWARD_BOUND` and its location moves on the eligibility axis to `AWARD_BOUND` with `awarded_award_id` stamped to the new award — `AFFIRMED → AWARD_BOUND` for a location the challenge process left alone, and `RECLASSIFIED → AWARD_BOUND` for one a sustained challenge reclassified, and in both cases only when a claim on that location for this application is `CLAIMED_ELIGIBLE` and either its `claimed_cost_cents` is at most the extremely-high-cost threshold or the program has disabled the waiver. The application moves `SELECTED → AWARDED`. An `OBLIGATION` ledger entry for the obligation amount is appended, and the program's balances are re-derived from the ledger as described in §2.11.

The award lifecycle runs `OBLIGATED`, `CONSTRUCTION_AUTHORIZED`, `IN_CONSTRUCTION` and the two terminal states `CLOSED` and `TERMINATED`, with `compliance_state` tracking deployment posture across `COMPLIANT`, `NONCOMPLIANT` and `CURED` independently of the award state.

Termination is the compensating path, taken by a `ProgramAdmin` with a `terminated_reason`, and it runs as `OBLIGATED → TERMINATED`, as `CONSTRUCTION_AUTHORIZED → TERMINATED`, or as `IN_CONSTRUCTION → TERMINATED` — but the last of those only when `compliance_state` is `NONCOMPLIANT`. All three run the same four-hop cascade, and the reason is stamped into `terminated_reason`.

- **Hop 1.** A `DEOBLIGATION` ledger entry is appended for `obligation_amount_cents` minus `disbursed_to_date_cents` — the undisbursed remainder only.
- **Hop 2**, caused by hop 1. The program's balances are re-derived from the ledger as described in §2.11, so `obligated_balance_cents` falls and `uncommitted_balance_cents` rises by the deobligated remainder. Because only the remainder is deobligated, `disbursed_balance_cents` is unchanged by a termination.
- **Hop 3**, caused by hop 1. Every `AWARD_BOUND` claim of the award moves to `RELEASED`, and every milestone of the award not already `DISBURSED` — that is, every milestone in `PLANNED`, `EVIDENCE_SUBMITTED`, `APPROVED`, `REJECTED` or `HELD` — moves to `VOIDED`.
- **Hop 4**, caused by hop 3. Each released location moves on the eligibility axis `AWARD_BOUND → AFFIRMED` and has its `awarded_award_id` cleared to null, returning it to the eligible pool; the application moves `AWARDED → NOT_SELECTED`; and the program's `scoring_posture` is recomputed on the standard rule.

Terminating from `CONSTRUCTION_AUTHORIZED` additionally returns every location whose `service_state` is `UNDER_CONSTRUCTION` to `NOT_BUILT`.

### 3.8. Environmental Clearance and Milestone Disbursement

Before a shovel moves, an `EnvironmentalReviewer` opens an **EnvironmentalReview** on the obligated award, declaring whether `tribal_consultation_required` and `shpo_consultation_required` are in scope for the award footprint — consultation with tribal authorities and with the State Historic Preservation Office respectively, both defaulting to false. The review starts in `ehp_state` `SCREENING`. Its lifecycle covers `SCREENING`, `CATEGORICAL_EXCLUSION`, `EA_REQUIRED`, `MITIGATION_REQUIRED` and the two terminal states `CLEARED` and `BLOCKED`. An attempt to record a determination or to clear a review that was never opened is refused with `ERR_ENVIRONMENTAL_REVIEW_NOT_FOUND`.

The reviewer records determinations by supplying a `pathway`, which is stamped into the review's `pathway` field and may be `CATEGORICAL_EXCLUSION`, `EA_REQUIRED`, `MITIGATION_PLAN_ACCEPTED` or `ADVERSE_EFFECT`. Screening forks on the consultation flags. A `CATEGORICAL_EXCLUSION` determination moves the review `SCREENING → CATEGORICAL_EXCLUSION` and is available only when both `tribal_consultation_required` and `shpo_consultation_required` are false — with no consultation obligations, clearance needs no mitigation record. An `EA_REQUIRED` determination moves the review `SCREENING → EA_REQUIRED` and is available only when at least one of the two flags is true: an environmental assessment must precede any clearance.

From `EA_REQUIRED` the assessment resolves one of two ways, and the two branches have deliberately divergent side-effect sets. A `MITIGATION_PLAN_ACCEPTED` determination moves the review `EA_REQUIRED → MITIGATION_REQUIRED` and stamps the supplied `mitigation_summary` — the mitigation commitments — onto the review. An `ADVERSE_EFFECT` determination moves the review `EA_REQUIRED → BLOCKED` and stamps nothing else at all: no mitigation record, no clearance fields, ever. A blocked award can never reach `CONSTRUCTION_AUTHORIZED`; the only way forward is termination.

Clearance moves the review to `CLEARED`, stamping the acting reviewer as `cleared_by_user_id` and the current logical instant as `cleared_at`. It runs as `CATEGORICAL_EXCLUSION → CLEARED` unconditionally, and as `MITIGATION_REQUIRED → CLEARED` only when `mitigation_summary` is not null. Clearance attempted on a `BLOCKED` review is admitted past the state ladder specifically so that it can be refused with `ERR_EHP_ADVERSE_EFFECT_BLOCKING`; an adverse-effect finding cannot be cleared.

With clearance in hand, a `ProgramAdmin` authorises construction, moving the award `OBLIGATED → CONSTRUCTION_AUTHORIZED` and moving every `AWARD_BOUND` location on the service axis `NOT_BUILT → UNDER_CONSTRUCTION`. Authorisation without a `CLEARED` review is refused with `ERR_EHP_NOT_CLEARED`.

**Milestones** are the build plan, added by a `ProgramAdmin` with a `sequence_no` giving the ordinal position (at least 1, unique within the award), a `description`, an `evidence_basis`, the `planned_location_ids` in scope, and `is_final`, which defaults to false and marks the draw that releases the holdback and closes the award. Every id in `planned_location_ids` must name a location `AWARD_BOUND` under this award, or the request is refused with `ERR_LOCATION_NOT_IN_AWARD_SCOPE`. At most one milestone per award may have `is_final` true; a second is refused with `ERR_FINAL_MILESTONE_CONFLICT`, as is verification of the final milestone while any other milestone of the award is still `PLANNED`, `EVIDENCE_SUBMITTED` or `HELD`. A milestone starts with `milestone_state` `PLANNED` and `resubmission_count` at 0, and its `milestone_state` axis covers `PLANNED`, `EVIDENCE_SUBMITTED`, `APPROVED`, `REJECTED`, `HELD` and the terminal `DISBURSED` and `VOIDED`.

The applicant submits build evidence, moving the milestone `PLANNED → EVIDENCE_SUBMITTED`. It supplies `built_location_ids`, the locations it asserts are built, and `invoiced_cost_cents`, the invoiced construction cost. Submission requires the caller to be the subgrantee behind the award's application, the award to be `CONSTRUCTION_AUTHORIZED` or `IN_CONSTRUCTION`, the award's `compliance_state` to be `COMPLIANT` or `CURED`, every id in `built_location_ids` to appear in `planned_location_ids`, and — when `evidence_basis` is `INVOICED_COST` — `invoiced_cost_cents` to be supplied rather than null. Both payload values are stamped onto the milestone. A rejected milestone may be resubmitted, moving it `REJECTED → EVIDENCE_SUBMITTED` with `resubmission_count` incremented and `built_location_ids` replaced, requiring `resubmission_count` to be strictly below two and the award's compliance posture again to be `COMPLIANT` or `CURED`; a third resubmission is refused with `ERR_RESUBMISSION_LIMIT_REACHED`.

Verification is performed by an `AuditOfficer` or a `ProgramAdmin` supplying an `outcome` of `APPROVED` or `REJECTED` and, on rejection, a `rejection_reason`. An `APPROVED` verification moves the milestone `EVIDENCE_SUBMITTED → APPROVED` and requires every verified location id to appear in `built_location_ids` and every verified location to be `UNDER_CONSTRUCTION` on the service axis. It stamps `verified_location_count` — the count of locations the verifier confirmed built — computes `payable_amount_cents`, moves each verified location on the service axis `UNDER_CONSTRUCTION → SERVICE_AVAILABLE`, records the caller as the milestone's `verified_by_user_id`, and records the caller as the award's `last_verifier_user_id`, which is what later bars that same person from recording an audit result or verifying remediation on this award. A `REJECTED` verification moves the milestone `EVIDENCE_SUBMITTED → REJECTED`, stamps `rejection_reason`, sets `payable_amount_cents` to 0, and likewise records the caller as the award's `last_verifier_user_id`.

The payable amount is computed at approval under one of three rules. Throughout, the cumulative ceiling is the award's `holdback_cap_cents`, and the remaining headroom is that ceiling minus the award's `disbursed_to_date_cents`. When `is_final` is true, the payable amount is the award's `obligation_amount_cents` minus `disbursed_to_date_cents` — the holdback is released in full and the headroom clamp does not apply. When `is_final` is false and `evidence_basis` is `BUILD_PROGRESS`, the **pro-rata build** variant applies: a gross figure is the award's `obligation_amount_cents` multiplied by `verified_location_count` and divided by the award's `confirmed_location_count`, rounded half up to a whole cent, and the payable amount is the smaller of that gross figure and the remaining headroom. When `is_final` is false and `evidence_basis` is `INVOICED_COST`, the **cost-reimbursement** variant applies: an eligible figure is `invoiced_cost_cents` multiplied by the quantity 100 minus the program's `min_match_pct`, divided by 100 — the federal share of what was invoiced — rounded half up to a whole cent, and the payable amount is the smaller of that eligible figure and the remaining headroom. Identical build progress therefore yields a different payable amount under the two bases. In every case the single division is rounded before the clamp is applied.

Disbursement is a `ProgramAdmin` act on an `APPROVED` milestone. It requires the award's `compliance_state` to be `COMPLIANT` or `CURED` and `payable_amount_cents` to be strictly greater than 0; a payable amount at or below zero — typically because the holdback ceiling is already exhausted — is refused with `ERR_NO_DISBURSABLE_AMOUNT`. Disbursement moves the milestone `APPROVED → DISBURSED`, appends a `DISBURSEMENT` ledger entry for the payable amount, re-derives the award's `disbursed_to_date_cents` as the sum of its disbursements less its recoveries, and re-derives the program's balances. It moves each verified location in scope on the service axis `SERVICE_AVAILABLE → CERTIFIED`, stamping `certified_at` with the current logical instant and re-deriving the award's `certified_location_count`. On the award axis the first disbursement moves the award `CONSTRUCTION_AUTHORIZED → IN_CONSTRUCTION`; disbursing the milestone whose `is_final` is true moves the award `IN_CONSTRUCTION → CLOSED`, which additionally requires that milestone to be `APPROVED` and the award's `compliance_state` to be `COMPLIANT` or `CURED`, and which brings `disbursed_to_date_cents` up to the full `obligation_amount_cents`.

### 3.9. Deployment Audits, Clawback and Reinstatement

Once an award is `IN_CONSTRUCTION` or `CLOSED`, an `AuditOfficer` schedules a **ComplianceAudit** over a field observation window, supplying `audit_type` — one of `SPEED_TEST`, `SERVICE_AVAILABILITY` or `COMBINED` — and `window_start` and `window_end`. Unlike the program and construction windows, the observation window is a **closed** interval: both endpoints are inside it. The start must be strictly before the end, and the new window must neither overlap nor sit within twenty-four hours of the window of any existing non-terminal audit on the same award; a violation is refused with `ERR_AUDIT_WINDOW_BUFFER_CONFLICT`. The audit starts with `audit_state` `SCHEDULED`, records the scheduling officer as `auditor_user_id`, and sets `appeal_count` to 0. Its `audit_state` axis covers `SCHEDULED`, `PASSED`, `FAILED`, `REMEDIATED`, `CLAWBACK_NOTICE_ISSUED`, `APPEALED`, `CLAWBACK_SETTLED` and `CLAWBACK_WAIVED`, of which `PASSED`, `REMEDIATED`, `CLAWBACK_SETTLED` and `CLAWBACK_WAIVED` are terminal.

Recording a result is an `AuditOfficer` act on a `SCHEDULED` audit, supplying a `result` of `PASSED` or `FAILED`, the `tested_location_ids` actually measured, and, on failure, the `failed_location_ids`. The caller may not be the award's `last_verifier_user_id`. The logical clock must have reached `window_start`. `tested_location_count` is stamped as the number of per-location results submitted, and `failed_location_count` is the length of `failed_location_ids`.

A `PASSED` result moves the audit `SCHEDULED → PASSED` and requires every measured location to meet the award's application's `committed_down_mbps`, `committed_up_mbps` and `committed_latency_ms`; `failed_location_ids` is stamped as an empty list.

A `FAILED` result moves the audit `SCHEDULED → FAILED` and requires `failed_location_ids` to be non-empty with every listed id naming a location `AWARD_BOUND` under this award. It then runs a three-hop cascade in the same request.

- **Hop 1.** `failed_location_ids` is stamped; each listed location moves on the service axis to `AUDIT_FAILED` — as `SERVICE_AVAILABLE → AUDIT_FAILED` for one not yet certified and as `CERTIFIED → AUDIT_FAILED` for one already certified — and a location that was `CERTIFIED` also has its `certified_at` cleared to null. The award's `compliance_state` moves `COMPLIANT → NONCOMPLIANT`, and the award's `failed_location_count` and `certified_location_count` are re-derived.
- **Hop 2**, caused by hop 1's compliance change. Every milestone of that award moves to `HELD` — as `EVIDENCE_SUBMITTED → HELD` for one awaiting verification and as `APPROVED → HELD` for one already verified — and has its `payable_amount_cents` zeroed — for an already-approved milestone this releases a reserved disbursement.
- **Hop 3**, caused by hop 2's non-empty held set. The award's applicant moves `QUALIFIED → SUSPENDED` and its `open_noncompliance_count` rises by one.

The same request also stamps the audit's `noncompliant_share` and `penalty_multiplier`. The share is `failed_location_count` divided by the award's `confirmed_location_count`, rounded half up to 4 decimal places. The multiplier is then selected by tier, with every tier boundary inclusive on its upper edge: 1.00 when the share is at most 0.10, 1.10 when it is at most 0.25, 1.25 when it is at most 0.50, and 1.50 above that — so a share of exactly 0.5000 selects 1.25, not 1.50.

Where money has already gone out the door, the officer issues a **clawback notice**, moving the audit `FAILED → CLAWBACK_NOTICE_ISSUED`. Issuance requires the award's `disbursed_to_date_cents` to be greater than 0, records the caller as `notice_issued_by_user_id`, and stamps `recovery_amount_cents`. The recovery is computed in two rounded steps: a base recovery is the award's `disbursed_to_date_cents` multiplied by `failed_location_count` and divided by the award's `confirmed_location_count` — using the exact unrounded fraction — rounded half up to a whole cent; that base is then multiplied by `penalty_multiplier`, rounded half up to a whole cent again, and the result is capped at the award's `disbursed_to_date_cents`, because the office can never recover more than it paid.

The applicant may appeal, moving the audit `CLAWBACK_NOTICE_ISSUED → APPEALED` with an `appeal_basis`. The caller must be the subgrantee behind the award's application, and `appeal_count` must be strictly below two; it is incremented by the appeal. From `APPEALED` the officer may re-issue the notice, moving the audit `APPEALED → CLAWBACK_NOTICE_ISSUED` while `appeal_count` is at most two, recomputing `recovery_amount_cents` against the award's current `disbursed_to_date_cents` and re-recording `notice_issued_by_user_id`. The appeal cycle `CLAWBACK_NOTICE_ISSUED → APPEALED → CLAWBACK_NOTICE_ISSUED` therefore runs at most twice.

Resolution is a `ProgramAdmin` act supplying a `resolution` of `SETTLED` or `WAIVED`, and the two branches are mirror images. A `SETTLED` resolution moves the audit `CLAWBACK_NOTICE_ISSUED → CLAWBACK_SETTLED` and requires `recovery_amount_cents` to be non-null and no greater than the award's `disbursed_to_date_cents`. `settled_amount_cents` takes the payload's `settled_amount_cents` when one is supplied — which must fall between 1 and `recovery_amount_cents` inclusive, or the request is refused with `ERR_CLAWBACK_AMOUNT_INVALID` — and otherwise defaults to the full `recovery_amount_cents`. A `CLAWBACK_RECOVERY` ledger entry for that amount is appended, the award's `disbursed_to_date_cents` is reduced, the program's `disbursed_balance_cents` falls and its `uncommitted_balance_cents` rises by the settled amount, the award's `compliance_state` becomes `CURED`, and every location in `failed_location_ids` still sitting at `AUDIT_FAILED` has its `certified_at` cleared to null so that the award's re-derived `certified_location_count` returns to its pre-certification value for those locations. A `WAIVED` resolution moves the audit `APPEALED → CLAWBACK_WAIVED`, requires the caller not to be the `notice_issued_by_user_id` who issued the notice, sets `settled_amount_cents` to 0, appends no ledger entry at all, and leaves the award's `compliance_state` at `NONCOMPLIANT`.

The remediation path is the alternative to clawback and undoes the failure cascade. An `AuditOfficer` or `ProgramAdmin` verifies remediation on a `FAILED` audit, optionally supplying a `remediation_note`, and the caller may not be the award's `last_verifier_user_id`. The audit moves `FAILED → REMEDIATED`; each failed location returns on the service axis `AUDIT_FAILED → SERVICE_AVAILABLE`; the award's `compliance_state` moves `NONCOMPLIANT → CURED` and its `failed_location_count` is re-derived; every held milestone returns `HELD → EVIDENCE_SUBMITTED` with `payable_amount_cents` staying 0 until it is verified again; and the applicant returns `SUSPENDED → QUALIFIED`, which requires its `open_noncompliance_count` to have been exactly 1 before the transition and decrements it to 0.

## 4. Endpoint Definitions

Operations that create a new resource — a program, a location, a challenge, an evidence item, a subgrantee, an application, a location claim, a score sheet, an award, an environmental review, a milestone or a compliance audit — return `201 Created`. Operations that modify an existing resource, including every state-transition action and the logical-clock setter, return `200 OK`. Every read returns `200 OK`. Request bodies, response payloads and side effects are specified in §2 and §3, not in this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical UTC clock | ProgramAdmin |
| POST | `/broadband/programs` | Create a grant program round with its thresholds and windows | ProgramAdmin |
| GET | `/broadband/programs/{id}` | Fetch one grant program with its computed balances and scoring posture | ProgramAdmin, EligibilityAnalyst, CapabilityReviewer, ScoringOfficer, EnvironmentalReviewer, AuditOfficer, Subgrantee, Challenger, Provider |
| GET | `/broadband/programs` | List grant programs, filterable by fiscal year and state | ProgramAdmin, EligibilityAnalyst, ScoringOfficer, Subgrantee |
| POST | `/broadband/programs/{id}/open-challenge-window` | Move a DRAFT program into CHALLENGE_OPEN so challenges may be filed | ProgramAdmin |
| POST | `/broadband/programs/{id}/close-challenge-window` | Close the challenge window; every still-MAPPED location is AFFIRMED | ProgramAdmin |
| POST | `/broadband/programs/{id}/open-scoring` | Open the scoring phase so score sheets may be produced | ProgramAdmin |
| POST | `/broadband/programs/{id}/close-allocation` | Close allocation; every SCORED application never selected becomes NOT_SELECTED | ProgramAdmin |
| POST | `/broadband/locations` | Ingest one national-map location record and classify it | ProgramAdmin, EligibilityAnalyst |
| GET | `/broadband/locations/{id}` | Fetch one eligible location with both of its state axes | ProgramAdmin, EligibilityAnalyst, ScoringOfficer, AuditOfficer, Subgrantee, Challenger, Provider |
| GET | `/broadband/locations` | List locations filtered by program, classification, either state axis, or bound award | ProgramAdmin, EligibilityAnalyst, ScoringOfficer, AuditOfficer, Subgrantee, Challenger, Provider |
| GET | `/broadband/locations/{id}/location-claims` | List every claim filed against this location across applications | ProgramAdmin, EligibilityAnalyst, ScoringOfficer, AuditOfficer |
| POST | `/broadband/challenges` | File a challenge contesting a location's classification | Challenger, Provider |
| GET | `/broadband/challenges/{id}` | Fetch one challenge with its evidence scores and rebuttal counters | ProgramAdmin, EligibilityAnalyst, ScoringOfficer, Challenger, Provider |
| GET | `/broadband/challenges` | List challenges filtered by program, contested location or state | ProgramAdmin, EligibilityAnalyst, ScoringOfficer, Challenger, Provider |
| POST | `/broadband/challenges/{id}/evidence` | Append one immutable evidence item to a challenge | Challenger, Provider |
| GET | `/broadband/challenges/{id}/evidence` | List the evidence items of a challenge | ProgramAdmin, EligibilityAnalyst, Challenger, Provider |
| POST | `/broadband/challenges/{id}/triage` | Accept a challenge for review and open the rebuttal window | EligibilityAnalyst |
| POST | `/broadband/challenges/{id}/close-rebuttal` | Close the rebuttal window and move the challenge to review | EligibilityAnalyst |
| POST | `/broadband/challenges/{id}/request-additional-evidence` | Reopen the rebuttal window for another round | EligibilityAnalyst |
| POST | `/broadband/challenges/{id}/determine` | Determine a challenge SUSTAINED, REJECTED or DEFICIENT | EligibilityAnalyst, ProgramAdmin |
| POST | `/broadband/challenges/{id}/resubmit` | Resubmit a DEFICIENT challenge with a corrected rationale | Challenger, Provider |
| POST | `/broadband/subgrantees` | Register a prospective subgrantee with its declared figures | ProgramAdmin |
| GET | `/broadband/subgrantees/{id}` | Fetch one subgrantee with its capability components and index | ProgramAdmin, CapabilityReviewer, ScoringOfficer, AuditOfficer, Subgrantee |
| GET | `/broadband/subgrantees` | List subgrantees filtered by program or capability state | ProgramAdmin, CapabilityReviewer, ScoringOfficer, AuditOfficer |
| POST | `/broadband/subgrantees/{id}/begin-capability-review` | Open technical, financial and managerial capability review | CapabilityReviewer |
| POST | `/broadband/subgrantees/{id}/record-capability-determination` | Record the technical raw score and derive the capability index | CapabilityReviewer |
| POST | `/broadband/subgrantees/{id}/submit-remediation` | Supply audited financials and withdrawn-personnel corrections | Subgrantee, ProgramAdmin |
| POST | `/broadband/applications` | Open a draft application with its speed, affordability and workforce commitments | Subgrantee, ProgramAdmin |
| GET | `/broadband/applications/{id}` | Fetch one application with both cost-per-location variants and its score | ProgramAdmin, ScoringOfficer, CapabilityReviewer, AuditOfficer, Subgrantee |
| GET | `/broadband/applications` | List applications filtered by program, subgrantee or state | ProgramAdmin, ScoringOfficer, CapabilityReviewer, AuditOfficer, Subgrantee |
| POST | `/broadband/applications/{id}/submit` | Submit a draft or cured application for scoring | Subgrantee |
| POST | `/broadband/applications/{id}/return-for-cure` | Return a submitted application to the subgrantee for correction | ScoringOfficer, ProgramAdmin |
| POST | `/broadband/applications/{id}/select` | Select a scored application for award | ProgramAdmin |
| GET | `/broadband/applications/{id}/location-claims` | List the location claims of an application | ProgramAdmin, ScoringOfficer, AuditOfficer, Subgrantee |
| GET | `/broadband/applications/{id}/score-sheets` | List the score sheets produced for an application, including STALE ones | ProgramAdmin, ScoringOfficer, AuditOfficer |
| GET | `/broadband/applications/{id}/awards` | List the awards obligated from an application | ProgramAdmin, ScoringOfficer, AuditOfficer, Subgrantee |
| POST | `/broadband/location-claims` | Claim one eligible location for a draft application at a declared cost | Subgrantee |
| POST | `/broadband/score-sheets` | Score a submitted or rescore-required application | ScoringOfficer |
| POST | `/broadband/awards` | Obligate an award to a selected application | ProgramAdmin |
| GET | `/broadband/awards/{id}` | Fetch one award with its obligation, holdback cap and disbursement totals | ProgramAdmin, ScoringOfficer, EnvironmentalReviewer, AuditOfficer, Subgrantee |
| GET | `/broadband/awards` | List awards filtered by application, award state or compliance state | ProgramAdmin, EnvironmentalReviewer, AuditOfficer, Subgrantee |
| POST | `/broadband/awards/{id}/authorize-construction` | Authorize construction once environmental review is cleared | ProgramAdmin |
| POST | `/broadband/awards/{id}/terminate` | Terminate an award, deobligating its undisbursed balance | ProgramAdmin |
| GET | `/broadband/awards/{id}/ledger-entries` | List the immutable ledger entries of an award | ProgramAdmin, AuditOfficer, Subgrantee |
| POST | `/broadband/awards/{id}/environmental-review` | Open environmental and historic preservation screening | EnvironmentalReviewer |
| GET | `/broadband/awards/{id}/environmental-review` | List the environmental review of an award (zero or one row) | ProgramAdmin, EnvironmentalReviewer, AuditOfficer, Subgrantee |
| POST | `/broadband/awards/{id}/environmental-review/determination` | Record a screening or assessment determination | EnvironmentalReviewer |
| POST | `/broadband/awards/{id}/environmental-review/clear` | Clear the review so construction may be authorized | EnvironmentalReviewer |
| POST | `/broadband/awards/{id}/milestones` | Add a build milestone with its evidence basis and planned location set | ProgramAdmin |
| GET | `/broadband/awards/{id}/milestones` | List the milestones of an award | ProgramAdmin, AuditOfficer, Subgrantee |
| POST | `/broadband/awards/{id}/milestones/{milestoneId}/submit-evidence` | Submit build-progress or invoiced-cost evidence for a milestone | Subgrantee |
| POST | `/broadband/awards/{id}/milestones/{milestoneId}/verify` | Verify submitted build evidence and compute the payable amount | AuditOfficer, ProgramAdmin |
| POST | `/broadband/awards/{id}/milestones/{milestoneId}/disburse` | Disburse an approved milestone and certify its locations | ProgramAdmin |
| POST | `/broadband/awards/{id}/compliance-audits` | Schedule a speed-test or service-availability audit over a closed window | AuditOfficer |
| GET | `/broadband/awards/{id}/compliance-audits` | List the compliance audits of an award | ProgramAdmin, AuditOfficer, Subgrantee |
| POST | `/broadband/awards/{id}/compliance-audits/{auditId}/record-result` | Record the audit result | AuditOfficer |
| POST | `/broadband/awards/{id}/compliance-audits/{auditId}/issue-clawback-notice` | Issue a clawback notice at the tiered penalty multiplier | AuditOfficer, ProgramAdmin |
| POST | `/broadband/awards/{id}/compliance-audits/{auditId}/appeal` | Appeal an issued clawback notice | Subgrantee |
| POST | `/broadband/awards/{id}/compliance-audits/{auditId}/resolve-clawback` | Settle or waive a clawback | ProgramAdmin |
| POST | `/broadband/awards/{id}/compliance-audits/{auditId}/verify-remediation` | Verify that the failed locations were remediated | AuditOfficer, ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_LOCATION_NOT_FOUND` | 404 |
| `ERR_CHALLENGE_NOT_FOUND` | 404 |
| `ERR_SUBGRANTEE_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_AWARD_NOT_FOUND` | 404 |
| `ERR_MILESTONE_NOT_FOUND` | 404 |
| `ERR_AUDIT_NOT_FOUND` | 404 |
| `ERR_ENVIRONMENTAL_REVIEW_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PROGRAM_STATE_INVALID` | 409 |
| `ERR_CHALLENGE_STATE_INVALID` | 409 |
| `ERR_SUBGRANTEE_STATE_INVALID` | 409 |
| `ERR_APPLICATION_STATE_INVALID` | 409 |
| `ERR_APPLICATION_NOT_SELECTED` | 409 |
| `ERR_AWARD_STATE_INVALID` | 409 |
| `ERR_MILESTONE_STATE_INVALID` | 409 |
| `ERR_AUDIT_STATE_INVALID` | 409 |
| `ERR_EHP_STATE_INVALID` | 409 |
| `ERR_SCORING_POSTURE_RESTRICTED` | 409 |
| `ERR_STALE_CHALLENGE_VERSION` | 412 |
| `ERR_STALE_APPLICATION_VERSION` | 412 |
| `ERR_EHP_NOT_CLEARED` | 409 |
| `ERR_EHP_ADVERSE_EFFECT_BLOCKING` | 422 |
| `ERR_LOCATION_NOT_IN_AWARD_SCOPE` | 422 |
| `ERR_PROGRAM_SCOPE_MISMATCH` | 422 |
| `ERR_CHALLENGE_WINDOW_CLOSED` | 409 |
| `ERR_APPLICATION_WINDOW_CLOSED` | 409 |
| `ERR_REBUTTAL_DEADLINE_NOT_REACHED` | 409 |
| `ERR_AUDIT_WINDOW_BUFFER_CONFLICT` | 409 |
| `ERR_LOCATION_CLAIM_WINDOW_CONFLICT` | 409 |
| `ERR_WINDOW_ORDER_INVALID` | 400 |
| `ERR_DUPLICATE_CHALLENGE` | 409 |
| `ERR_EVIDENCE_STANDARD_NOT_MET` | 422 |
| `ERR_REBUTTAL_PREVAILS` | 422 |
| `ERR_REBUTTAL_ROUND_EXHAUSTED` | 409 |
| `ERR_RESUBMISSION_LIMIT_REACHED` | 409 |
| `ERR_SPEED_COMMITMENT_BELOW_MINIMUM` | 422 |
| `ERR_MATCH_BELOW_MINIMUM` | 422 |
| `ERR_SUBGRANTEE_NOT_QUALIFIED` | 409 |
| `ERR_NO_ELIGIBLE_LOCATIONS` | 422 |
| `ERR_DUPLICATE_LOCATION_ADDRESS` | 409 |
| `ERR_AWARD_ALREADY_EXISTS` | 409 |
| `ERR_FINAL_MILESTONE_CONFLICT` | 409 |
| `ERR_ALL_LOCATIONS_EHCL_DEFERRED` | 422 |
| `ERR_PROGRAM_FUNDS_EXHAUSTED` | 422 |
| `ERR_NO_DISBURSABLE_AMOUNT` | 422 |
| `ERR_CLAWBACK_AMOUNT_INVALID` | 422 |
