# Service Dog Placement API — Product Requirements Document

## 1. Introduction

Assistance-dog organizations operate one of the longest pipelines in the nonprofit world: a puppy enters the program at eight weeks, spends over a year with a volunteer raiser, passes through advanced training, matches with a waitlisted client, attends a multi-week team class, and — only after passing a standardized public access test — is placed. The placement is not the end of the story: follow-up visits, annual recertification, and an aftercare support channel continue for the working life of the partnership. Every stage of this pipeline carries compliance obligations, segregation-of-duties requirements, and money (client fundraising requirements tracked to the cent), and until now the organization has run it on spreadsheets.

This document specifies a REST API that runs the full program end to end: applicant intake and disability-related task assessment, a ranked waitlist with a fundraising requirement, puppy-raiser recruitment and foster placement, health screening with origin-dependent clearance gates, training milestone tracking with advancement gates, team training classes with public access testing, and post-placement follow-up, recertification, and owner support. The API is mounted under `/api`.

The design is deliberately conservative about who may do what. Intake staff never touch training records; trainers never approve applicants; evaluators never score a dog they trained; the operator who records a donation pledge is never the one who marks it received. These separations are not bureaucratic decoration — they are the audit spine of an organization that places animals with disabled clients and answers to accreditors.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. When either header is missing, or the role value is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the role is declared but is not listed among the roles authorized for the endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The declared roles, spelled exactly as the header value must appear, are: `ProgramAdmin`, `IntakeCoordinator`, `TrainingDirector`, `Veterinarian`, `Trainer`, `Evaluator`, `Applicant`, `PuppyRaiser`.

`ProgramAdmin` is the organization superuser: an opaque operator identifier not tied to any persisted entity, owning raiser and trainer administration, dog intake, and the logical clock. `IntakeCoordinator` is likewise opaque, owning applicant intake, assessments, the waitlist, the fundraising ledger, and match administration. `TrainingDirector` is opaque as well, owning placements, career-change decisions, classes, enrollments, graduation, and aftercare. `Veterinarian` is an opaque operator identifier for external vet accounts, limited to health-screening work. For these four roles the server may record the supplied `X-User-ID` on resources where a transition writes an operator field (for example `reviewed_by_user_id` on an `Applicant`), but it never compares the value to any entity's `id`.

The remaining four roles are entity-backed. When `X-User-Role` is `Trainer`, `X-User-ID` is the `id` of the acting `Trainer`; ownership checks on any resource that references a `Trainer` compare the resource's trainer field to `X-User-ID`. When `X-User-Role` is `Evaluator`, `X-User-ID` is likewise the `id` of the acting `Trainer` (an evaluator is a trainer identity with evaluation privileges); scoring and result-recording endpoints compare the resource's evaluator field to `X-User-ID`. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`; an applicant acts only on records whose applicant chain terminates at that `id`, and violations are rejected with `ERR_OWNERSHIP_SCOPE` (HTTP 403). When `X-User-Role` is `PuppyRaiser`, `X-User-ID` is the `id` of the acting `PuppyRaiser`; a raiser acts only on their own profile and their own placements, with the same `ERR_OWNERSHIP_SCOPE` on violation.

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

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, must be at least 1, and must not exceed 100; `offset` defaults to 0. Every list response includes the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`. Unless an endpoint's narrative states otherwise, lists are sorted by `created_at` ascending.

### 2.4. Common Resource Properties

Every persisted resource carries an `id`, which is a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. All entities except `TrainingMilestone` additionally carry `updated_at` (same timestamp format, refreshed on every mutation) and `version` (an integer that increments by 1 on every mutation of that entity). `TrainingMilestone` is the single exception: milestone records are append-only assessment evidence and carry only `id` and `created_at` — both `updated_at` and `version` are absent from milestone resources.

### 2.5. The Logical Clock

The server maintains a logical clock. At startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to the wall clock. A `ProgramAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; the response reports the new `current_utc` plus the counts `swept_followups_missed` and `swept_partnerships_recert_due`. Advancing the clock triggers the scheduled sweep described in §2.8 and recomputes every waitlist entry's `rank_score` as wait days accumulate. Anywhere this document says "now", "today", or "the current date", it means the logical clock.

### 2.6. Request Validation Order

Every request passes through a fixed pipeline of checks, evaluated in this order:

1. **Request shape** — the body is well-formed, required fields are present, enum members are valid, and numeric ranges are respected (amounts positive, scores within 0–100, `ends_on` strictly later than `starts_on`, class `capacity` between 2 and 6). Violations are rejected with `ERR_VALIDATION` (HTTP 400).
2. **Authentication** — headers present and role declared (`ERR_UNAUTHENTICATED`).
3. **Role authorization** — the acting role appears in the endpoint's authorized roles (`ERR_FORBIDDEN`).
4. **Ownership scope** — entity-backed actors operate only on their own records (`ERR_OWNERSHIP_SCOPE`).
5. **Path resolution** — nested paths resolve left to right, parent before child; an unresolvable path parameter is rejected with `ERR_NOT_FOUND` (HTTP 404).
6. **Body references** — body-supplied references (`waitlist_entry_id`, `puppy_raiser_id`, `primary_trainer_id`, `match_id`, `evaluator_id`, `sire_id` and `dam_id`, `lead_trainer_id`, `assigned_trainer_id`) must resolve to existing resources; failures return `ERR_REFERENCE_NOT_FOUND` (HTTP 404).
7. **Optimistic concurrency** — on the three OCC-guarded writes described in §2.7, the expected-version field must match (`ERR_STALE_VERSION`, `ERR_STALE_DOG_VERSION`, or `ERR_STALE_PARTNERSHIP_VERSION`, each HTTP 412).
8. **Terminal lockdown** — no transition fires out of a terminal state (`ERR_ALREADY_TERMINAL`, HTTP 409).
9. **From-state membership** — the resource must be in a declared from-state for the requested transition (`ERR_INVALID_STATE`, HTTP 409).
10. **Domain rules** — business state, safety, constraint, temporal, referential, and fiscal rules, evaluated in the priority order given in §2.9 and throughout §3.

### 2.7. Optimistic Concurrency Control

Three write operations are OCC-guarded. No other endpoint takes a version field.

- **Creating an enrollment** against a class requires the non-optional field `expected_class_version`, carrying the client's last observed `version` of that `TeamTrainingClass`. If the class's version has advanced since the client read it — for example another writer has just enrolled a pair, legitimately consuming a seat — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a stale view of remaining capacity.
- **Proposing a match** against a dog requires the non-optional field `expected_dog_version`, carrying the client's last observed `version` of that `Dog`. A mismatch with the dog's current `version` is rejected with `ERR_STALE_DOG_VERSION` (HTTP 412).
- **Scheduling a recertification** against a partnership requires the non-optional field `expected_partnership_version`, carrying the client's last observed `version` of that `Partnership`. A mismatch is rejected with `ERR_STALE_PARTNERSHIP_VERSION` (HTTP 412).

### 2.8. Scheduled Sweep Rules

Advancing the logical clock runs a sweep over scheduled obligations, processing entities in order of their `due_on` or `recert_due_at` ascending, breaking ties by `created_at` ascending. Two transitions fire during the sweep: a `FollowUp` still `SCHEDULED` whose current logical date is more than 7 days past its `due_on` becomes `MISSED`; and a `Partnership` in `ACTIVE` whose current logical date is later than its `recert_due_at` with no `COMPLETED_PASS` recertification recorded since activation becomes `RECERT_DUE`. The same clock advance also recomputes every waitlist entry's `rank_score` because `wait_days` derives from the logical clock.

### 2.9. Money, Precision, and Rounding

All monetary quantities are integer cents. Percentages and scores that carry a fractional component are rounded half-up to 1 decimal place, and any multiplication that produces fractional cents is rounded half-up to a whole cent at the point of multiplication — never carried as a fraction into later steps. Wherever a calculation in §3 pins an evaluation order (per-section-then-average, credit-then-subsidy), the prose order is the required order.

## 3. Business Logic & Workflows

### 3.1. Applicant Intake and Disability Task Assessment

An `IntakeCoordinator` or `ProgramAdmin` opens the pipeline by creating an applicant with `full_name`, `email`, `placement_track`, `household_income_cents`, and `region`. `email` must be unique across applicants; `household_income_cents` is self-reported annual household income in cents and must be non-negative; `region` is a region code such as NW or SW used later for raiser and dog matching; and `placement_track` is one of `MOBILITY`, `PTSD`, `AUTISM`, or `FACILITY`. A new applicant begins in `SUBMITTED`, with `verified_income_cents` null and `denial_reason` null.

Review begins when an `IntakeCoordinator` begins review of a `SUBMITTED` applicant, moving `application_status` to `IN_REVIEW` and recording the acting operator id in `reviewed_by_user_id`. If the file is incomplete, the coordinator requests more information — supplying an `info_request_note` — moving the applicant from `IN_REVIEW` to `NEEDS_INFO`. The applicant themselves then resubmits, which returns the application from `NEEDS_INFO` to `IN_REVIEW`; a resubmission by anyone other than that applicant is rejected with `ERR_OWNERSHIP_SCOPE`. From either `IN_REVIEW` or `NEEDS_INFO`, the coordinator may deny the application, recording the supplied `denial_reason`; the applicant lands in the terminal state `DENIED`.

The disability-related task assessment lives alongside the review. An `IntakeCoordinator` creates an assessment under an applicant, supplying `required_tasks` — an array of task codes drawn from `RETRIEVE_ITEMS`, `OPEN_DOORS`, `BALANCE_SUPPORT`, `INTERRUPT_ANXIETY`, `ALERT_SOUND`, `GUIDE_NAVIGATION`, `DEEP_PRESSURE`, and `MEDICAL_ALERT`, with at least one entry required — plus a `task_urgency_tier` of `STANDARD`, `HIGH`, or `CRITICAL`, a `home_environment_score` from 0 to 10 inclusive, and optional free-text `notes`. The assessment starts in `DRAFT` with `finalized_by_user_id` null. Finalizing takes a payload `outcome` and moves the assessment to `FINALIZED_ACCEPTED` or `FINALIZED_REJECTED`, stamping `finalized_by_user_id` with the acting operator id. Assessment `status`, `applicant_id`, `finalized_by_user_id`, and the creation fields above make up the assessment record.

Approval is the gate to the waitlist. An `IntakeCoordinator` approving an applicant enforces two checks in order: the applicant must currently be `IN_REVIEW` (otherwise `ERR_INVALID_STATE`), and at least one of the applicant's assessments must be `FINALIZED_ACCEPTED` (otherwise `ERR_ASSESSMENT_REQUIRED`). Approval stamps `approved_by_user_id` with the acting operator id, moves the applicant to `WAITLISTED`, and creates the waitlist entry described in §3.2.

Withdrawal is available from every non-terminal state except `PLACED` — that is, from `SUBMITTED`, `IN_REVIEW`, `NEEDS_INFO`, `WAITLISTED`, `MATCH_ELIGIBLE`, `MATCHED`, or `TEAM_TRAINING`; attempting it elsewhere is `ERR_INVALID_STATE`. Either the applicant themselves or an `IntakeCoordinator` may withdraw; when the actor is the applicant, acting on any record other than their own is `ERR_OWNERSHIP_SCOPE`. (A `PLACED` applicant exits the program through partnership dissolution, §3.8.) Withdrawal lands the applicant in the terminal state `WITHDRAWN` and fires the full compensation cascade: the applicant's waitlist entry, if in `PENDING`, `ELIGIBLE`, `MATCHED`, or `SUSPENDED`, becomes `CLOSED`; every `PLEDGED` contribution becomes `VOID` and every `RECEIVED` contribution becomes `REFUNDED` under the refund-clawback rules of §3.3, with `raised_cents` settling to exactly 0; any `ACCEPTED` match record becomes `DISSOLVED`, returning the dog from `MATCHED` to `MATCH_READY`; and any `ENROLLED` enrollment becomes `WITHDRAWN`, which itself reverts the dog from `TEAM_TRAINING` to `MATCH_READY`, dissolves the accepted match, and decrements the class's `enrolled_count`. Every mutation in this cascade refreshes `updated_at`, and the applicant's own `version` increments by 1.

### 3.2. The Waitlist: Requirements, Rank, and Eligibility

Approval creates a `WaitlistEntry` with `status` `PENDING`, `listed_at` set to the logical-clock timestamp, `raised_cents` 0, `dissolved_match_count` 0, `requirement_final_cents` null, and `requirement_provisional_cents` computed by the provisional variant of the fundraising rule below. An applicant carries at most one entry whose `status` is `PENDING`, `ELIGIBLE`, `MATCHED`, or `SUSPENDED`.

**Fundraising requirement.** The requirement has two variants that share an evaluation skeleton and differ in one pinned respect. Both variants begin from the gross base requirement for the applicant's `placement_track`: 1,500,000 cents for `MOBILITY`, 1,800,000 cents for `PTSD`, 1,800,000 cents for `AUTISM`, and 900,000 cents for `FACILITY`. Both then compute an income credit from the applicable income figure — the applicant's self-reported `household_income_cents` in the provisional variant, the payload `verified_income_cents` in the final variant. The credit percentage brackets, with inclusive lower boundaries, are: income below 3,000,000 cents earns a credit of 60 percent of gross; income of at least 3,000,000 but below 6,000,000 earns 40 percent; at least 6,000,000 but below 10,000,000 earns 20 percent; at least 10,000,000 earns no credit. The income credit is gross multiplied by the credit percentage, rounded half-up to a whole cent, and the provisional net is gross minus the income credit.

The variants diverge at the subsidy step. In the **provisional** variant — computed at waitlist-entry creation — the subsidy tier is keyed on the gross requirement: if gross is at least 1,000,000 cents the subsidy is 10 percent, otherwise 15 percent; the subsidy is gross multiplied by that percentage, rounded half-up to a whole cent; and the requirement written to `requirement_provisional_cents` is gross minus income credit minus subsidy. In the **final** variant — computed when an `IntakeCoordinator` recalculates an entry from verified income — the subsidy tier is keyed on the provisional net (the post-credit figure): provisional net of at least 1,000,000 cents yields 10 percent, otherwise 15 percent; the subsidy is provisional net multiplied by that percentage, rounded half-up; and the requirement written to `requirement_final_cents` is provisional net minus subsidy. Because the tier key and subsidy base differ, identical inputs can diverge between variants. Recalculation also copies the payload income onto the applicant as `verified_income_cents` and then re-evaluates eligibility exactly as a contribution receive or refund would.

The entry's `effective_requirement_cents` is `requirement_final_cents` when set, otherwise `requirement_provisional_cents`. The entry's `raised_cents` is at all times the sum of `amount_cents` over the applicant's contributions in `RECEIVED` status — this ledger invariant is maintained on every receive, refund, and withdrawal.

**Eligibility flips.** Whenever a receive or a recalculation leaves `raised_cents` at least equal to `effective_requirement_cents` — the boundary is inclusive — a `PENDING` entry flips to `ELIGIBLE`, and its applicant mirrors from `WAITLISTED` to `MATCH_ELIGIBLE`. Whenever a refund clawback or a recalculation leaves `raised_cents` strictly below `effective_requirement_cents`, an `ELIGIBLE` entry reverts to `PENDING` and the applicant mirrors from `MATCH_ELIGIBLE` back to `WAITLISTED`. Both flips recompute `rank_score` (the 15-point fundraising bonus applies only while `ELIGIBLE`).

**Rank score.** An entry's `rank_score` is recomputed on creation, on every eligibility flip, on every clock sweep, and on every dissolve event. The wait component is the number of whole days between `listed_at` and the current logical time — partial days discarded — multiplied by 0.5 points per day, capped at 40 points. The urgency component is drawn from the `task_urgency_tier` of the applicant's latest `FINALIZED_ACCEPTED` assessment: 10 points for `STANDARD`, 25 for `HIGH`, 40 for `CRITICAL`. The home component is that assessment's `home_environment_score` multiplied by 2 points per point, capped at 20 points. The fundraising bonus is 15 points while the entry is `ELIGIBLE`, zero otherwise. Finally, 10 points are subtracted for each dissolved match — the penalty is `dissolved_match_count` multiplied by 10. The total is rounded half-up to 1 decimal place.

**Suspension and reinstatement.** An `IntakeCoordinator` may suspend an entry in `PENDING` or `ELIGIBLE`, moving it to `SUSPENDED` and excluding it from the match-selector candidate pool. Reinstating a `SUSPENDED` entry re-evaluates eligibility from the ledger: when `raised_cents` is below `effective_requirement_cents` the entry lands in `PENDING`; when `raised_cents` is at least the effective requirement it lands in `ELIGIBLE`, and in that case the applicant mirrors from `WAITLISTED` to `MATCH_ELIGIBLE`; either way `rank_score` is recomputed. Entries close — from `PENDING`, `ELIGIBLE`, `MATCHED`, or `SUSPENDED` — when the applicant withdraws; an entry in `PENDING` or `MATCHED` also closes when its enrollment graduates. `CLOSED` is terminal.

### 3.3. The Fundraising Ledger

An `IntakeCoordinator` records a contribution under an applicant, supplying `donor_name` and `amount_cents`. The amount must be at least 100 cents; anything less is rejected with `ERR_CONTRIBUTION_BELOW_MINIMUM` (HTTP 422). Fundraising creation is only permitted while the applicant is active: creating a contribution for an applicant in `DENIED`, `WITHDRAWN`, or `PLACED` is rejected with `ERR_APPLICANT_NOT_ACTIVE` (HTTP 409). A new contribution is `PLEDGED`, with `created_by_user_id` set to the acting operator id and `received_by_user_id` null.

Marking a contribution received is a second, segregated act: an `IntakeCoordinator` receives a `PLEDGED` contribution, and the receiving operator must differ from `created_by_user_id` — when the same operator attempts both acts, the receive is rejected with `ERR_SOD_CONFLICT` (HTTP 409). Receiving stamps `received_by_user_id`, moves the contribution to `RECEIVED`, adds its `amount_cents` to the entry's `raised_cents`, and fires the eligibility flip of §3.2 when the inclusive threshold is crossed.

Refunding a `RECEIVED` contribution is blocked once the money is locked into a placement pipeline: when the linked entry is `MATCHED` or the applicant is `PLACED`, the refund is rejected with `ERR_REFUND_NOT_ALLOWED`. An allowed refund moves the contribution to `REFUNDED` and runs the clawback: the entry's `raised_cents` is reduced by the refunded `amount_cents`; if the entry was `ELIGIBLE` and the reduced total is now strictly below `effective_requirement_cents`, the entry reverts to `PENDING` and the applicant mirrors from `MATCH_ELIGIBLE` to `WAITLISTED`, with `rank_score` recomputed without the bonus. During a withdrawal cascade, voids precede refunds: every `PLEDGED` contribution is voided first, then every `RECEIVED` contribution is refunded in `created_at` ascending order, so `raised_cents` settles to exactly 0. `PLEDGED` also transitions directly to `VOID` when the applicant withdraws. `REFUNDED` and `VOID` are terminal.

### 3.4. Puppy Raisers, Trainers, and Dog Intake

**Raisers.** A `ProgramAdmin` recruits a puppy raiser with `full_name`, `region`, `foster_capacity` (at least 1), and `experience_score` (0 to 100 inclusive). The raiser starts in `APPLIED`, with `current_dog_count` 0 and `last_placement_ended_at` null. Vetting moves `APPLIED` to `VETTED`; approval moves `VETTED` to `APPROVED`. The first placement created for an `APPROVED` raiser moves them to `ACTIVE`; when their `current_dog_count` later returns to 0 on a completion or early return, they drop back to `APPROVED`. A raiser in `APPROVED` or `ACTIVE` whose `current_dog_count` is 0 may be placed `ON_HIATUS` — by a `ProgramAdmin`, or by the raiser themselves acting on their own profile (otherwise `ERR_OWNERSHIP_SCOPE`) — and resume returns `ON_HIATUS` to `APPROVED` under the same actor rules. Deactivation by a `ProgramAdmin` moves a raiser from `APPLIED`, `VETTED`, `APPROVED`, or `ON_HIATUS` to the terminal state `INACTIVE`, and requires `current_dog_count` of 0 in all cases.

**Trainers.** A `ProgramAdmin` creates a trainer with `full_name` and an optional `pat_certified` flag (defaulting to false) that marks whether the trainer may administer public access tests and recertifications. Trainers begin in `PROBATION`; certification moves `PROBATION` to `CERTIFIED`; suspension moves `CERTIFIED` to `SUSPENDED`; reinstatement moves `SUSPENDED` back to `CERTIFIED`; deactivation moves any of `PROBATION`, `CERTIFIED`, or `SUSPENDED` to the terminal `INACTIVE`. A `SUSPENDED` trainer is excluded from new milestone recording, from class-lead assignment, and from evaluator duty — attempts to use one on those endpoints fail with `ERR_INVALID_STATE`.

**Dog intake.** A `ProgramAdmin` registers a dog with `name`, `origin` (`BRED` or `DONATED`), `breed`, `sex` (`MALE` or `FEMALE`), `born_on` as an ISO date, and `region`. Lineage rules depend on origin and violations are rejected with `ERR_DONOR_LINEAGE_INVALID` (HTTP 422): a `BRED` dog requires `sire_id` referencing an existing `MALE` dog and `dam_id` referencing an existing `FEMALE` dog distinct from the sire, and forbids `donor_name`; a `DONATED` dog requires `donor_name` and forbids both `sire_id` and `dam_id`. New dogs are `REGISTERED`, with `clearance_score` null, `primary_trainer_id` null, `certified_tasks` an empty set, and `career_change_reason` null.

### 3.5. Health Screening and the Two Clearance Tracks

A `Veterinarian` begins screening on a `REGISTERED` dog, moving it to `IN_HEALTH_SCREENING`, then creates a draft screening under that dog — the dog must be `IN_HEALTH_SCREENING` at creation — supplying `hip_grade` (`EXCELLENT`, `GOOD`, `FAIR`, `POOR`), `elbow_grade` (`NORMAL`, `GRADE1`, `GRADE2`), `eye_result` (`CLEAR`, `ABNORMAL`), `cardiac_result` (`NORMAL`, `ABNORMAL`), and `genetic_panel` (`CLEAR`, `CARRIER`, `AFFECTED`). The screening is `DRAFT`, with `veterinarian_user_id` set to the acting operator id.

Submission computes the screening's `clearance_score` as the sum of five component point values: hip contributes 30 for `EXCELLENT`, 24 for `GOOD`, 12 for `FAIR`, and 0 for `POOR`; elbow contributes 20 for `NORMAL`, 8 for `GRADE1`, and 0 for `GRADE2`; eye contributes 15 for `CLEAR` and 0 for `ABNORMAL`; cardiac contributes 15 for `NORMAL` and 0 for `ABNORMAL`; genetic contributes 20 for `CLEAR`, 10 for `CARRIER`, and 0 for `AFFECTED`. The score is an integer number of points with no rounding. A hard fail — any single component scoring 0 — fails the screening regardless of total.

The pass gate then depends on the dog's origin, and the two tracks are genuinely different. A `DONATED` dog passes when its score is at least 84 with no hard fail; a `CARRIER` genetic panel is tolerated on this track at its 10 points. A `BRED` dog passes only when its score is at least 92 **and** the genetic panel is `CLEAR`, with no other hard fail — so an identical component set can pass a donated dog yet fail a bred dog twice over (once on the threshold, once on the genetic requirement). A passing submission moves the screening to `CLEARED` and mirrors the dog from `IN_HEALTH_SCREENING` to `CLEARED`, storing the screening's score as the dog's `clearance_score`. A failing submission — hard fail or below threshold — moves the screening to `FAILED` and mirrors the dog to `CAREER_CHANGED` with `career_change_reason` set to `HEALTH`, again storing the score. Both screening outcomes are terminal; a screening in `DRAFT` is the only submittable state.

### 3.6. Raiser Placement and Advanced Training

**Placing a dog with a raiser.** A `TrainingDirector` creates a raiser placement for a dog in `CLEARED` or `RECALLED` — any other dog status is `ERR_INVALID_STATE`, and both states are reachable only through a submitted `CLEARED` screening. When the request supplies `puppy_raiser_id`, that explicit pick bypasses ranking but not eligibility: the raiser must be `APPROVED` or `ACTIVE` with `current_dog_count` below `foster_capacity` (violations are `ERR_RAISER_CAPACITY`, HTTP 409), and the raiser's `region` must equal the dog's `region` (a mismatch is `ERR_VALIDATION`). When `puppy_raiser_id` is omitted, the raiser selector runs: the candidate pool is every raiser in `APPROVED` or `ACTIVE` whose `current_dog_count` is below `foster_capacity` and whose `region` equals the dog's `region`; the pool is ranked by `experience_score` descending, ties broken by `last_placement_ended_at` ascending with nulls sorted last — a never-placed raiser loses ties to previously active ones — then by `created_at` ascending; an empty pool is rejected with `ERR_NO_AVAILABLE_RAISER`.

A created placement is `ACTIVE`, with `started_on` set from the logical clock, `ended_on` null, the dog moving to `RAISER_PLACED`, the raiser's `current_dog_count` increasing by 1, and an `APPROVED` raiser moving to `ACTIVE` on their first placement.

**Completing or ending a placement.** A `TrainingDirector` completes an `ACTIVE` placement by supplying `primary_trainer_id`, which must reference a `CERTIFIED` trainer (otherwise `ERR_INVALID_STATE`). Completion moves the placement to `COMPLETED`, sets `ended_on`, advances the dog from `RAISER_PLACED` to `IN_ADVANCED_TRAINING` with `primary_trainer_id` recorded on the dog, decrements the raiser's `current_dog_count`, stamps the raiser's `last_placement_ended_at` with the current time, and drops an `ACTIVE` raiser to `APPROVED` when the count reaches 0. Early return — available to a `TrainingDirector`, or to the raiser acting on their own placement (`acting raiser id` must equal the placement's `puppy_raiser_id`, else `ERR_OWNERSHIP_SCOPE`), with an optional `reason` — moves the placement to `EARLY_RETURN` and recalls the dog from `RAISER_PLACED` to `RECALLED`, with the same raiser count and timestamp effects. A recalled dog can be placed again through the same creation flow.

**Milestones and the advancement gates.** Milestones are recorded for dogs in `IN_ADVANCED_TRAINING` or `TEAM_TRAINING` — any other dog status is `ERR_INVALID_STATE`. A `Trainer` actor must be the dog's `primary_trainer_id` (otherwise `ERR_OWNERSHIP_SCOPE`); a `TrainingDirector` actor records the milestone with `recorded_by_trainer_id` set to the dog's `primary_trainer_id`. Each milestone carries a `category` of `OBEDIENCE`, `TASK_WORK`, `PUBLIC_MANNERS`, or `SOCIALIZATION`, and a `score` from 0 to 100 inclusive. `task_code` — one of the task codes from the assessment task universe — is required when the category is `TASK_WORK` and forbidden otherwise (a violation is `ERR_VALIDATION`). `recorded_at` is stamped from the logical clock and is the chronological ordering key, with `created_at` breaking ties.

Two progress figures are computed on every milestone. `rolling_avg_3` is the mean of the latest three milestone scores in chronological order — fewer when the dog has fewer than three — rounded half-up to 1 decimal place; this is the progress readout surfaced on each milestone response, and because it looks only at the recent window, a strong early history cannot rescue a recent dip. `cumulative_gate_score` is a category-weighted mean over all of the dog's milestones: half the weight on the mean of all `TASK_WORK` scores, three-tenths on the mean of all `PUBLIC_MANNERS` scores, and two-tenths on the mean of all `OBEDIENCE` and `SOCIALIZATION` scores combined; when a category is absent from the record it contributes nothing to the numerator and its weight is dropped from the denominator, renormalizing over the weights that are present; the result is rounded half-up to 1 decimal place. Because the two windows differ, an identical milestone set can satisfy the cumulative gate while failing the rolling gate. The response also surfaces a career-change-recommended flag when the latest two scores are both below 50.

Advancement is evaluated after each milestone persists. A dog in `IN_ADVANCED_TRAINING` moves to `MATCH_READY` when all five gates hold: at least 6 milestones recorded; `cumulative_gate_score` at least 80.0; `rolling_avg_3` at least 70.0; no score below 40 among the latest three milestones; and at most one recorded milestone in total with a score below 50. Separately, every `TASK_WORK` milestone scoring at least 80 adds its `task_code` to the dog's `certified_tasks` set — this set is what match proposals check task coverage against.

**Career change.** A `TrainingDirector` may career-change a dog in `RAISER_PLACED`, `RECALLED`, `IN_ADVANCED_TRAINING`, `MATCH_READY`, `MATCHED`, or `TEAM_TRAINING` — elsewhere it is `ERR_INVALID_STATE` — supplying `reason_category` (`HEALTH`, `TEMPERAMENT`, or `OTHER`) and optional `notes`; the reason is recorded as `career_change_reason` and the dog lands in the terminal state `CAREER_CHANGED`. The decision cascades through whatever program links exist. An `ACTIVE` raiser placement becomes `EARLY_RETURN`, decrementing the raiser's `current_dog_count`, stamping `last_placement_ended_at`, and dropping an `ACTIVE` raiser to `APPROVED` at count 0. From `MATCHED` or `TEAM_TRAINING`, the accepted match record becomes `DISSOLVED`, which itself reverts the waitlist entry from `MATCHED` to `ELIGIBLE` — incrementing `dissolved_match_count` and recomputing rank — and moves the applicant from `MATCHED` or `TEAM_TRAINING` to `MATCH_ELIGIBLE`. From `TEAM_TRAINING` additionally, the `ENROLLED` enrollment becomes `WITHDRAWN`, which decrements the class's `enrolled_count`. Links apply only to entities that exist; a dog career-changed from `RECALLED` with no match fires only the placement link if a placement is active.

### 3.7. Matching, Classes, and the Public Access Test

**Match proposals.** An `IntakeCoordinator` proposes a match for a dog, which must be `MATCH_READY` (otherwise `ERR_INVALID_STATE`), and the write is OCC-guarded by `expected_dog_version` as described in §2.7. The proposal may name a `waitlist_entry_id` explicitly or omit it to invoke the selector. An explicit entry must be `ELIGIBLE` (otherwise `ERR_INVALID_STATE`), and the dog's `certified_tasks` must cover every task in the applicant's `required_tasks` from the latest `FINALIZED_ACCEPTED` assessment — a coverage gap on an explicit pick is rejected with `ERR_TASK_COVERAGE_INSUFFICIENT` (HTTP 422). In selector mode the candidate pool is every `ELIGIBLE` entry whose applicant's `required_tasks` form a subset of the dog's `certified_tasks` — subset failures are silently excluded here rather than rejected — ranked by `rank_score` descending, ties broken by `listed_at` ascending (earlier listing wins) and then by the applicant's `created_at` ascending; an empty pool is rejected with `ERR_NO_ELIGIBLE_MATCH`. A created match record is `PROPOSED`, with `proposed_by_user_id` set to the acting operator id, `rank_score_at_match` capturing the entry's `rank_score` at proposal time, and the dog's `version` incrementing by 1.

Accepting a proposal requires the match still `PROPOSED`, the dog `MATCH_READY`, and the entry `ELIGIBLE` — each violation is `ERR_INVALID_STATE` — and then fires the three-way mirror: the dog moves `MATCH_READY` to `MATCHED`, the entry moves `ELIGIBLE` to `MATCHED`, and the applicant moves `MATCH_ELIGIBLE` to `MATCHED`. Rejecting a `PROPOSED` proposal moves it to the terminal `REJECTED` and leaves the dog `MATCH_READY` and the entry `ELIGIBLE` untouched. Dissolving an `ACCEPTED` match — by an `IntakeCoordinator` directly, or by the career-change, withdrawal, enrollment-withdrawal, and PAT-fail cascades — reverts the dog from `MATCHED` to `MATCH_READY` (or from `TEAM_TRAINING` to `MATCH_READY` when dissolved mid-class), reverts the entry from `MATCHED` to `ELIGIBLE` while incrementing `dissolved_match_count` and recomputing `rank_score`, and moves the applicant from `MATCHED` to `MATCH_ELIGIBLE` (or from `TEAM_TRAINING` to `MATCH_ELIGIBLE` mid-class) — skipped when the applicant is already `WITHDRAWN`, in which case the entry instead goes to `CLOSED`. A match reaches the terminal `COMPLETED` only through graduation. `REJECTED`, `DISSOLVED`, and `COMPLETED` are all terminal.

**Team training classes.** A `TrainingDirector` creates a class with `name`, `lead_trainer_id`, `starts_on` and `ends_on` as ISO dates, `capacity`, and `total_sessions`. `ends_on` must be strictly later than `starts_on`; `capacity` must be between 2 and 6 inclusive; `total_sessions` must be at least 1 — these are request-shape checks under `ERR_VALIDATION`. The lead trainer's other non-cancelled classes occupy the half-open interval from `starts_on` inclusive to `ends_on` exclusive, and two such intervals overlap when the new class's `starts_on` is earlier than the other's `ends_on` and the new class's `ends_on` is later than the other's `starts_on`; an overlap is rejected with `ERR_TRAINER_SCHEDULE_CONFLICT`, while mere adjacency — one class's `ends_on` exactly equal to the other's `starts_on` — is allowed. A new class is `PLANNED` with `enrolled_count` 0.

Opening enrollment moves `PLANNED` to `ENROLLING` and requires the lead trainer to be `CERTIFIED` (otherwise `ERR_INVALID_STATE`). Starting the class moves `ENROLLING` to `IN_SESSION` and enforces two checks: `enrolled_count` must be at least 1 (otherwise `ERR_CLASS_TOO_SMALL` — the minimum class size is one enrolled pair) and the logical date must be at least `starts_on` (otherwise `ERR_ENROLLMENT_WINDOW`). Beginning graduation review moves `IN_SESSION` to `GRADUATION_REVIEW` and requires the logical date to be strictly later than `ends_on` (otherwise `ERR_ENROLLMENT_WINDOW`). Completing the class moves `GRADUATION_REVIEW` to the terminal `COMPLETED` and requires every enrollment to be in `GRADUATED`, `FAILED`, or `WITHDRAWN` (otherwise `ERR_INVALID_STATE`). Each of these class transitions increments the class's `version` by 1.

Cancelling a class in `PLANNED`, `ENROLLING`, or `IN_SESSION` moves it to the terminal `CANCELLED` and fires the class-cancel cascade: every `ENROLLED` enrollment becomes `WITHDRAWN`; each withdrawn enrollment's dog reverts from `TEAM_TRAINING` to `MATCHED` and its applicant likewise from `TEAM_TRAINING` to `MATCHED`, with the match retained — the match record stays `ACCEPTED`, no dissolve fires; and `enrolled_count` is recomputed to 0.

**Enrollment.** A `TrainingDirector` enrolls a pair into a class by supplying `match_id` and the OCC field `expected_class_version`. The match must be `ACCEPTED`. Seat capacity is enforced at creation: enrolling succeeds while `enrolled_count` is below `capacity` — the enrollment that brings the count exactly to capacity succeeds — and is rejected with `ERR_CLASS_FULL` beyond that. A created enrollment is `ENROLLED` with `sessions_attended` 0 and `attendance_pct` 0, its `class_id` recording the owning class, and it moves the dog from `MATCHED` to `TEAM_TRAINING` and the applicant from `MATCHED` to `TEAM_TRAINING`, increments the class's `enrolled_count` by 1, and increments the class's `version`.

Attendance is recorded as an absolute count: a `TrainingDirector` or `Trainer` sets `sessions_attended` while the class is `IN_SESSION`, and `attendance_pct` is recomputed as sessions attended divided by the class's `total_sessions`, multiplied by 100, rounded half-up to 1 decimal place. Withdrawing an `ENROLLED` enrollment — directly by a `TrainingDirector`, or through the class-cancel, applicant-withdraw, and career-change cascades — decrements `enrolled_count`. When the withdrawal is actor-initiated, the accepted match dissolves (with all of the dissolve side effects), the dog reverts from `TEAM_TRAINING` to `MATCH_READY`, and the applicant from `TEAM_TRAINING` to `MATCH_ELIGIBLE`; when the withdrawal comes from class cancellation, the dog and applicant instead revert to `MATCHED` and the match is retained. Graduation is covered at the end of this subsection.

**Public access tests.** An `Evaluator` schedules a public access test for an enrollment, supplying `scheduled_at` and an optional `location`. The scheduling enforces, in evaluation order: the referenced evaluator — which is the acting `Evaluator`'s own `X-User-ID`, recorded as `evaluator_id` — must be a `Trainer` with `pat_certified` true and status `CERTIFIED` (otherwise `ERR_EVALUATOR_NOT_CERTIFIED`); the evaluator must differ from the dog's `primary_trainer_id` under segregation of duties (otherwise `ERR_EVALUATOR_CONFLICT`); the attempt cap allows fewer than 2 non-`INVALIDATED` tests already existing for the enrollment — a third attempt is rejected with `ERR_PAT_ATTEMPTS_EXHAUSTED`; and the evaluator's calendar must be free: an evaluator is occupied for the 60-minute window from `scheduled_at` up to but not including `scheduled_at` plus 60 minutes, buffered by 30 minutes on each side, and a new `SCHEDULED` or scored test for the same evaluator whose buffered window intersects another's is rejected with `ERR_EVALUATOR_SCHEDULE_CONFLICT` — windows exactly 30 minutes apart are allowed. A scheduled test is `SCHEDULED`, with `exercise_scores` empty and `attempt_number` computed as 1 plus the count of prior non-`INVALIDATED` tests for the enrollment.

Scoring is the evaluator's own act — the acting evaluator id must equal `evaluator_id`, else `ERR_OWNERSHIP_SCOPE` — over a payload `exercise_scores` of 12 entries, each an exercise code with a raw score from 0 to 3. The codes are `C1` through `C6` for the CONTROL section (maximum 18 points), `P1` through `P4` for PUBLIC_MANNERS (maximum 12), and `S1` and `S2` for SAFETY (maximum 6). The rounding order is pinned per-section-then-average, never sum-then-round: first, each section's raw scores are summed; second, each `section_percents` entry — `control`, `public_manners`, and `safety` — is computed as 100 times the section sum divided by the section maximum, rounded half-up to 1 decimal place; third, `official_score` is the mean of the three already-rounded section percents, rounded half-up to 1 decimal place. `passed_gates` holds when `official_score` is at least 80.0 inclusive, every raw score is at least 1, and both `S1` and `S2` raw scores are at least 2. When all gates hold the test becomes `SCORED_PASS`; when any gate fails it becomes `SCORED_FAIL`. Either way `section_percents`, `official_score`, and `passed_gates` are computed and stored. When the failing test's `attempt_number` is 2, the enrollment itself fails — the `ENROLLED` to `FAILED` transition — firing the PAT-fail cascade: the accepted match dissolves (with its own side effects), the dog reverts from `TEAM_TRAINING` to `MATCH_READY`, the entry reverts from `MATCHED` to `ELIGIBLE` with `dissolved_match_count` incremented and rank recomputed, the applicant moves from `TEAM_TRAINING` to `MATCH_ELIGIBLE`, and the class's `enrolled_count` decrements by 1. A `TrainingDirector` may also invalidate a `SCHEDULED` test by supplying a `reason`, moving it to `INVALIDATED`; invalidated tests do not count toward the two-attempt cap. `SCORED_PASS`, `SCORED_FAIL`, and `INVALIDATED` are terminal.

**Graduation.** A `TrainingDirector` graduates an `ENROLLED` enrollment when four conditions hold, checked in order: the enrollment is `ENROLLED`; its class is in `GRADUATION_REVIEW`; `attendance_pct` is at least 85.0 inclusive (otherwise `ERR_ATTENDANCE_BELOW_THRESHOLD`); and a public access test for the enrollment exists with status `SCORED_PASS` (otherwise `ERR_GRADUATION_REQUIREMENTS`). Graduation moves the enrollment to `GRADUATED` and fires the placement cascade: a `Partnership` is created with `status` `ACTIVE`, `activated_at` set to the current logical time, and `recert_due_at` set to `activated_at` plus 365 days; three follow-ups are auto-created in `SCHEDULED` with `due_on` at the activation date plus 90, plus 180, and plus 270 days respectively, each with `auto_generated` true; the dog moves from `TEAM_TRAINING` to `PLACED`; the applicant moves from `TEAM_TRAINING` to `PLACED`; the match record moves from `ACCEPTED` to `COMPLETED`; and the waitlist entry moves from `MATCHED` to `CLOSED`.

### 3.8. Partnerships, Follow-Ups, and Recertification

A partnership is born `ACTIVE` at graduation, with `followups_completed` 0 and `last_recert_passed_at` null, linked to its `applicant_id`, `dog_id`, and originating `enrollment_id`. The clock sweep of §2.8 moves an `ACTIVE` partnership to `RECERT_DUE` when the logical date passes `recert_due_at` without a passing recertification since activation; the transition increments the partnership's `version`.

A `TrainingDirector` may suspend a partnership in `ACTIVE` or `RECERT_DUE` by supplying a `reason`, moving it to `SUSPENDED`. Reinstating a `SUSPENDED` partnership re-evaluates the recert schedule: it lands in `ACTIVE`, unless the logical date is already later than `recert_due_at`, in which case it lands in `RECERT_DUE` instead. Retiring a partnership from `ACTIVE`, `RECERT_DUE`, or `SUSPENDED` moves it to the terminal `RETIRED`, moves the placed dog from `PLACED` to `RETIRED`, and waives every open — `SCHEDULED` — follow-up. Dissolving from the same three states moves the partnership to the terminal `DISSOLVED`, returns the dog from `PLACED` to `MATCH_READY` so it re-enters the program, and likewise waives open follow-ups. Retire and dissolve both increment the partnership's `version`, as do suspend and reinstate.

**Follow-ups.** Beyond the three auto-generated visits, a `TrainingDirector` may create a manual follow-up under a partnership — recorded on the follow-up as its `partnership_id` — by supplying `due_on`; manual entries carry `auto_generated` false. A manual `due_on` must sit at least 7 days away from the `due_on` of every other non-`WAIVED` follow-up of the same partnership — a gap of exactly 7 days is allowed, anything closer is rejected with `ERR_FOLLOWUP_TOO_SOON`. Completing a `SCHEDULED` follow-up requires the partnership to be `ACTIVE` or `RECERT_DUE` (otherwise `ERR_INVALID_STATE`), records `completed_on` as the logical date and the payload `outcome` — `SATISFACTORY` or `NEEDS_SUPPORT` — along with optional `notes`, and increments the partnership's `followups_completed` by 1. A `TrainingDirector` may waive a `SCHEDULED` follow-up, and the retire and dissolve cascades waive them wholesale. The sweep marks a still-`SCHEDULED` follow-up `MISSED` once the logical date is more than 7 days past `due_on`. `COMPLETED`, `MISSED`, and `WAIVED` are terminal.

**Recertification.** A `TrainingDirector` schedules a recertification on a partnership — recorded on the recertification as its `partnership_id` — by supplying `scheduled_on`, `evaluator_id`, and the OCC field `expected_partnership_version` (§2.7); the scheduling itself increments the partnership's `version`. Two checks guard the schedule in order: `scheduled_on` must fall within the window from 30 days before `recert_due_at` to 30 days after it, inclusive — outside the window is `ERR_RECERT_WINDOW`; and the referenced evaluator must be a `Trainer` with `pat_certified` true and status `CERTIFIED` (otherwise `ERR_EVALUATOR_NOT_CERTIFIED`) who differs from the dog's `primary_trainer_id` (otherwise `ERR_EVALUATOR_CONFLICT`). A new recertification is `SCHEDULED` with `completed_on` null.

Recording the result is the named evaluator's own act — the acting evaluator id must equal `evaluator_id`, else `ERR_OWNERSHIP_SCOPE` — and takes a payload `outcome`. A `PASS` from `SCHEDULED` or `REMEDIATION` moves the recertification to the terminal `COMPLETED_PASS`, stamps `completed_on` with the logical date, moves the partnership from `RECERT_DUE` back to `ACTIVE` (or keeps an `ACTIVE` partnership active), resets `recert_due_at` to `completed_on` plus 365 days, and records the completion timestamp as `last_recert_passed_at`. A `FAIL` from `SCHEDULED` moves the recertification to `REMEDIATION` and stamps `completed_on`. A `FAIL` from `REMEDIATION` moves it to the terminal `FAILED_FINAL`, stamps `completed_on`, and suspends the partnership.

### 3.9. Owner Support and Aftercare

Either the client themselves (as `Applicant`) or a `TrainingDirector` raises a support request on a partnership, supplying a `category` of `EQUIPMENT`, `BEHAVIOR`, `HEALTH`, `TRAVEL`, `HOUSING`, or `OTHER`, a free-text `description`, and an optional `severity` of `LOW`, `MEDIUM`, `HIGH`, or `URGENT` defaulting to `MEDIUM`. The request is `OPEN`, with `raised_by_applicant_id` set to the partnership's applicant, `priority` null, `assigned_trainer_id` null, and `resolved_at` null.

A `TrainingDirector` triages an `OPEN` request, moving it to `TRIAGED` and setting `priority` from the payload. Starting work moves from `TRIAGED` or `REOPENED` to `IN_PROGRESS` and assigns a trainer: the payload `assigned_trainer_id` must reference a `CERTIFIED` trainer, otherwise `ERR_INVALID_STATE`. Resolution — by a `TrainingDirector`, or by the assigned `Trainer` themselves (an acting trainer whose id differs from `assigned_trainer_id` is rejected with `ERR_OWNERSHIP_SCOPE`) — moves `IN_PROGRESS` to `RESOLVED` with a `resolution_note` and stamps `resolved_at` from the logical clock.

The client then has a 14-day window: the applicant who owns the partnership may reopen a `RESOLVED` request while the logical time is within 14 days of `resolved_at` — later attempts are rejected with `ERR_REOPEN_WINDOW_EXPIRED`, and acting on someone else's request is `ERR_OWNERSHIP_SCOPE`. Reopening moves the request to `REOPENED` and clears `resolved_at` to null, after which a `TrainingDirector` can start it again under the same rules as a triaged request. Alternatively, a `TrainingDirector` closes a `RESOLVED` request outright; `CLOSED` is the sole terminal state.

## 4. Endpoint Definitions

Endpoints that create a new resource return 201; endpoints that modify, transition, or read a resource return 200. All responses use the envelope of §2.2; list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Advance the logical clock (startup default exactly 2026-08-01T00:00:00Z); triggers the recert/follow-up sweep and waitlist rank recompute | ProgramAdmin |
| POST | /api/applicants | Create applicant (intake) | IntakeCoordinator, ProgramAdmin |
| GET | /api/applicants/{id} | Get applicant | IntakeCoordinator, ProgramAdmin, TrainingDirector, Applicant |
| GET | /api/applicants | List applicants with filters + pagination (`application_status?`, `placement_track?`) | IntakeCoordinator, ProgramAdmin, TrainingDirector |
| POST | /api/applicants/{id}/begin-review | SUBMITTED → IN_REVIEW | IntakeCoordinator |
| POST | /api/applicants/{id}/request-info | IN_REVIEW → NEEDS_INFO | IntakeCoordinator |
| POST | /api/applicants/{id}/resubmit | NEEDS_INFO → IN_REVIEW (applicant self-service) | Applicant |
| POST | /api/applicants/{id}/approve | IN_REVIEW → WAITLISTED; creates WaitlistEntry with provisional requirement | IntakeCoordinator |
| POST | /api/applicants/{id}/deny | IN_REVIEW or NEEDS_INFO → DENIED | IntakeCoordinator |
| POST | /api/applicants/{id}/withdraw | Non-terminal (except PLACED) → WITHDRAWN with full compensation cascade | Applicant, IntakeCoordinator |
| GET | /api/applicants/{id}/assessments | Assessments of applicant | IntakeCoordinator, ProgramAdmin, TrainingDirector, Applicant |
| GET | /api/applicants/{id}/waitlist-entries | Waitlist entries of applicant (0–1 active) | IntakeCoordinator, ProgramAdmin, TrainingDirector, Applicant |
| GET | /api/applicants/{id}/contributions | Contributions of applicant | IntakeCoordinator, ProgramAdmin, Applicant |
| GET | /api/applicants/{id}/partnerships | Partnerships of applicant | IntakeCoordinator, ProgramAdmin, TrainingDirector, Applicant |
| POST | /api/applicants/{id}/assessments | Create DRAFT task assessment | IntakeCoordinator |
| GET | /api/assessments/{id} | Get assessment | IntakeCoordinator, ProgramAdmin, TrainingDirector |
| POST | /api/assessments/{id}/finalize | DRAFT → FINALIZED_ACCEPTED or FINALIZED_REJECTED | IntakeCoordinator |
| GET | /api/waitlist-entries/{id} | Get waitlist entry (includes rank, raised amount, requirements) | IntakeCoordinator, ProgramAdmin, TrainingDirector, Applicant |
| GET | /api/waitlist-entries | List waitlist entries with filters + pagination (`status?`) | IntakeCoordinator, ProgramAdmin, TrainingDirector |
| POST | /api/waitlist-entries/{id}/recalculate | Recompute final requirement from verified income; eligibility re-evaluated | IntakeCoordinator |
| POST | /api/waitlist-entries/{id}/suspend | PENDING or ELIGIBLE → SUSPENDED | IntakeCoordinator |
| POST | /api/waitlist-entries/{id}/reinstate | SUSPENDED → PENDING or ELIGIBLE per raised vs requirement | IntakeCoordinator |
| GET | /api/waitlist-entries/{id}/matches | Match records of entry | IntakeCoordinator, ProgramAdmin, TrainingDirector, Applicant |
| POST | /api/applicants/{id}/contributions | Record a PLEDGED contribution | IntakeCoordinator |
| GET | /api/contributions/{id} | Get contribution | IntakeCoordinator, ProgramAdmin, Applicant |
| POST | /api/contributions/{id}/receive | PLEDGED → RECEIVED (segregation of duties); eligibility re-evaluated | IntakeCoordinator |
| POST | /api/contributions/{id}/refund | RECEIVED → REFUNDED with clawback | IntakeCoordinator |
| POST | /api/puppy-raisers | Recruit puppy raiser (APPLIED) | ProgramAdmin |
| GET | /api/puppy-raisers/{id} | Get raiser | ProgramAdmin, TrainingDirector, PuppyRaiser |
| GET | /api/puppy-raisers | List raisers with filters + pagination (`status?`, `region?`) | ProgramAdmin, TrainingDirector |
| POST | /api/puppy-raisers/{id}/vet | APPLIED → VETTED | ProgramAdmin |
| POST | /api/puppy-raisers/{id}/approve | VETTED → APPROVED | ProgramAdmin |
| POST | /api/puppy-raisers/{id}/hiatus | APPROVED or ACTIVE (0 dogs) → ON_HIATUS | ProgramAdmin, PuppyRaiser |
| POST | /api/puppy-raisers/{id}/resume | ON_HIATUS → APPROVED | ProgramAdmin, PuppyRaiser |
| POST | /api/puppy-raisers/{id}/deactivate | Non-terminal (0 dogs) → INACTIVE | ProgramAdmin |
| GET | /api/puppy-raisers/{id}/placements | Raiser placements | ProgramAdmin, TrainingDirector, PuppyRaiser |
| POST | /api/trainers | Create trainer (PROBATION) | ProgramAdmin |
| GET | /api/trainers/{id} | Get trainer | ProgramAdmin, TrainingDirector, Trainer, Evaluator |
| POST | /api/trainers/{id}/certify | PROBATION → CERTIFIED | ProgramAdmin |
| POST | /api/trainers/{id}/suspend | CERTIFIED → SUSPENDED | ProgramAdmin |
| POST | /api/trainers/{id}/reinstate | SUSPENDED → CERTIFIED | ProgramAdmin |
| POST | /api/trainers/{id}/deactivate | Non-terminal → INACTIVE | ProgramAdmin |
| GET | /api/trainers/{id}/dogs | Dogs whose primary trainer is this trainer | ProgramAdmin, TrainingDirector, Trainer |
| GET | /api/trainers/{id}/classes | Classes led by trainer | ProgramAdmin, TrainingDirector, Trainer |
| GET | /api/trainers/{id}/evaluations | PATs administered by trainer (as evaluator) | ProgramAdmin, TrainingDirector, Trainer, Evaluator |
| GET | /api/trainers/{id}/milestones | Milestones recorded by trainer | ProgramAdmin, TrainingDirector, Trainer |
| POST | /api/dogs | Dog intake (breeding or donation) | ProgramAdmin |
| GET | /api/dogs/{id} | Get dog | ProgramAdmin, TrainingDirector, Veterinarian, Trainer, IntakeCoordinator, PuppyRaiser |
| GET | /api/dogs | List dogs with filters + pagination (`status?`, `origin?`, `region?`) | ProgramAdmin, TrainingDirector, Veterinarian, IntakeCoordinator |
| GET | /api/dogs/{id}/offspring | Dogs whose sire or dam is this dog | ProgramAdmin, TrainingDirector, Veterinarian |
| POST | /api/dogs/{id}/begin-screening | REGISTERED → IN_HEALTH_SCREENING | Veterinarian |
| POST | /api/dogs/{id}/career-change | Career-change decision with full cascade | TrainingDirector |
| GET | /api/dogs/{id}/screenings | Health screenings of dog | ProgramAdmin, TrainingDirector, Veterinarian |
| GET | /api/dogs/{id}/milestones | Milestones of dog (chronological) | ProgramAdmin, TrainingDirector, Trainer, IntakeCoordinator |
| GET | /api/dogs/{id}/raiser-placements | Raiser placements of dog | ProgramAdmin, TrainingDirector |
| GET | /api/dogs/{id}/matches | Match records of dog | ProgramAdmin, TrainingDirector, IntakeCoordinator |
| GET | /api/dogs/{id}/partnerships | Partnerships of dog | ProgramAdmin, TrainingDirector, IntakeCoordinator |
| POST | /api/dogs/{id}/screenings | Create DRAFT screening (dog must be IN_HEALTH_SCREENING) | Veterinarian |
| GET | /api/screenings/{id} | Get screening | ProgramAdmin, TrainingDirector, Veterinarian |
| POST | /api/screenings/{id}/submit | DRAFT → CLEARED or FAILED per clearance score; dog mirrors | Veterinarian |
| POST | /api/dogs/{id}/raiser-placements | Place dog with raiser; selector when raiser omitted | TrainingDirector |
| GET | /api/raiser-placements/{id} | Get raiser placement | ProgramAdmin, TrainingDirector, PuppyRaiser |
| POST | /api/raiser-placements/{id}/complete | ACTIVE → COMPLETED; dog advances to IN_ADVANCED_TRAINING | TrainingDirector |
| POST | /api/raiser-placements/{id}/early-return | ACTIVE → EARLY_RETURN; dog RECALLED | TrainingDirector, PuppyRaiser |
| POST | /api/dogs/{id}/milestones | Record milestone; advancement gates evaluated | Trainer, TrainingDirector |
| GET | /api/milestones/{id} | Get milestone | ProgramAdmin, TrainingDirector, Trainer |
| POST | /api/dogs/{id}/match-proposals | Propose match (selector when entry omitted); OCC on dog version | IntakeCoordinator |
| GET | /api/matches/{id} | Get match | IntakeCoordinator, ProgramAdmin, TrainingDirector |
| POST | /api/matches/{id}/accept | PROPOSED → ACCEPTED; dog/entry/applicant mirror transitions | IntakeCoordinator |
| POST | /api/matches/{id}/reject | PROPOSED → REJECTED | IntakeCoordinator |
| POST | /api/matches/{id}/dissolve | ACCEPTED → DISSOLVED with reverts | IntakeCoordinator |
| GET | /api/matches/{id}/enrollments | Enrollments of match | IntakeCoordinator, ProgramAdmin, TrainingDirector |
| POST | /api/classes | Create class PLANNED; half-open trainer-overlap enforced | TrainingDirector |
| GET | /api/classes/{id} | Get class | ProgramAdmin, TrainingDirector, Trainer, IntakeCoordinator |
| GET | /api/classes | List classes with filters + pagination (`status?`, `lead_trainer_id?`) | ProgramAdmin, TrainingDirector, IntakeCoordinator |
| POST | /api/classes/{id}/open-enrollment | PLANNED → ENROLLING (lead trainer must be CERTIFIED) | TrainingDirector |
| POST | /api/classes/{id}/start | ENROLLING → IN_SESSION (minimum size; clock at least starts_on) | TrainingDirector |
| POST | /api/classes/{id}/begin-graduation-review | IN_SESSION → GRADUATION_REVIEW (clock strictly after ends_on) | TrainingDirector |
| POST | /api/classes/{id}/complete | GRADUATION_REVIEW → COMPLETED (all enrollments terminal) | TrainingDirector |
| POST | /api/classes/{id}/cancel | PLANNED, ENROLLING, or IN_SESSION → CANCELLED; enrollments withdrawn with match retained | TrainingDirector |
| GET | /api/classes/{id}/enrollments | Enrollments of class | ProgramAdmin, TrainingDirector, IntakeCoordinator |
| POST | /api/classes/{id}/enrollments | Enroll ACCEPTED match; OCC on class version | TrainingDirector |
| GET | /api/enrollments/{id} | Get enrollment | ProgramAdmin, TrainingDirector, IntakeCoordinator, Trainer |
| POST | /api/enrollments/{id}/record-attendance | Set absolute sessions_attended (class must be IN_SESSION) | TrainingDirector, Trainer |
| POST | /api/enrollments/{id}/withdraw | ENROLLED → WITHDRAWN; match dissolved | TrainingDirector |
| POST | /api/enrollments/{id}/graduate | Graduate pair; creates Partnership + auto follow-ups | TrainingDirector |
| GET | /api/enrollments/{id}/public-access-tests | PATs of enrollment | ProgramAdmin, TrainingDirector, Evaluator, IntakeCoordinator |
| GET | /api/enrollments/{id}/partnerships | Partnership created by enrollment (0–1) | ProgramAdmin, TrainingDirector, IntakeCoordinator, Applicant |
| POST | /api/enrollments/{id}/public-access-tests | Schedule PAT (attempt cap 2; evaluator SoD + buffer) | Evaluator |
| GET | /api/public-access-tests/{id} | Get PAT | ProgramAdmin, TrainingDirector, Evaluator |
| POST | /api/public-access-tests/{id}/score | Score PAT (12 exercises); computes official score; second fail fails enrollment | Evaluator |
| POST | /api/public-access-tests/{id}/invalidate | SCHEDULED → INVALIDATED (frees attempt) | TrainingDirector |
| GET | /api/partnerships/{id} | Get partnership | ProgramAdmin, TrainingDirector, IntakeCoordinator, Applicant |
| GET | /api/partnerships | List partnerships with filters + pagination (`status?`) | ProgramAdmin, TrainingDirector, IntakeCoordinator |
| POST | /api/partnerships/{id}/suspend | ACTIVE or RECERT_DUE → SUSPENDED | TrainingDirector |
| POST | /api/partnerships/{id}/reinstate | SUSPENDED → ACTIVE (or RECERT_DUE when overdue) | TrainingDirector |
| POST | /api/partnerships/{id}/retire | ACTIVE, RECERT_DUE, or SUSPENDED → RETIRED; dog retires | TrainingDirector |
| POST | /api/partnerships/{id}/dissolve | ACTIVE, RECERT_DUE, or SUSPENDED → DISSOLVED; dog returns to MATCH_READY | TrainingDirector |
| GET | /api/partnerships/{id}/follow-ups | Follow-ups of partnership | ProgramAdmin, TrainingDirector, Applicant |
| GET | /api/partnerships/{id}/recertifications | Recertifications of partnership | ProgramAdmin, TrainingDirector, Applicant, Evaluator |
| GET | /api/partnerships/{id}/support-requests | Support requests of partnership | ProgramAdmin, TrainingDirector, Applicant, Trainer |
| POST | /api/partnerships/{id}/follow-ups | Manual follow-up; 7-day minimum gap vs other due dates | TrainingDirector |
| GET | /api/follow-ups/{id} | Get follow-up | ProgramAdmin, TrainingDirector |
| POST | /api/follow-ups/{id}/complete | SCHEDULED → COMPLETED | TrainingDirector |
| POST | /api/follow-ups/{id}/waive | SCHEDULED → WAIVED | TrainingDirector |
| POST | /api/partnerships/{id}/recertifications | Schedule recertification (window ±30 days around due); OCC on partnership version | TrainingDirector |
| GET | /api/recertifications/{id} | Get recertification | ProgramAdmin, TrainingDirector, Evaluator |
| POST | /api/recertifications/{id}/record-result | SCHEDULED or REMEDIATION → COMPLETED_PASS, REMEDIATION, or FAILED_FINAL | Evaluator |
| POST | /api/partnerships/{id}/support-requests | Raise support request (client self-service or staff) | Applicant, TrainingDirector |
| GET | /api/support-requests | List support requests with filters + pagination (`status?`, `category?`, `raised_by_applicant_id?`) | ProgramAdmin, TrainingDirector, Applicant |
| GET | /api/support-requests/{id} | Get support request | ProgramAdmin, TrainingDirector, Trainer, Applicant |
| POST | /api/support-requests/{id}/triage | OPEN → TRIAGED; sets priority | TrainingDirector |
| POST | /api/support-requests/{id}/start | TRIAGED or REOPENED → IN_PROGRESS; assigns trainer | TrainingDirector |
| POST | /api/support-requests/{id}/resolve | IN_PROGRESS → RESOLVED (assigned trainer or director) | Trainer, TrainingDirector |
| POST | /api/support-requests/{id}/reopen | RESOLVED → REOPENED within 14 days (client) | Applicant |
| POST | /api/support-requests/{id}/close | RESOLVED → CLOSED | TrainingDirector |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives alongside the workflows they guard.

| Error ID | HTTP Status Code |
|---|---|
| ERR_VALIDATION | 400 |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_OWNERSHIP_SCOPE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_STALE_DOG_VERSION | 412 |
| ERR_STALE_PARTNERSHIP_VERSION | 412 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_APPLICANT_NOT_ACTIVE | 409 |
| ERR_REFUND_NOT_ALLOWED | 409 |
| ERR_EVALUATOR_CONFLICT | 409 |
| ERR_SOD_CONFLICT | 409 |
| ERR_DONOR_LINEAGE_INVALID | 422 |
| ERR_TRAINER_SCHEDULE_CONFLICT | 409 |
| ERR_EVALUATOR_SCHEDULE_CONFLICT | 409 |
| ERR_RAISER_CAPACITY | 409 |
| ERR_CLASS_FULL | 409 |
| ERR_CLASS_TOO_SMALL | 409 |
| ERR_NO_AVAILABLE_RAISER | 409 |
| ERR_NO_ELIGIBLE_MATCH | 409 |
| ERR_PAT_ATTEMPTS_EXHAUSTED | 409 |
| ERR_ATTENDANCE_BELOW_THRESHOLD | 409 |
| ERR_RECERT_WINDOW | 409 |
| ERR_FOLLOWUP_TOO_SOON | 409 |
| ERR_ENROLLMENT_WINDOW | 409 |
| ERR_REOPEN_WINDOW_EXPIRED | 409 |
| ERR_EVALUATOR_NOT_CERTIFIED | 409 |
| ERR_ASSESSMENT_REQUIRED | 409 |
| ERR_TASK_COVERAGE_INSUFFICIENT | 422 |
| ERR_GRADUATION_REQUIREMENTS | 409 |
| ERR_CONTRIBUTION_BELOW_MINIMUM | 422 |
