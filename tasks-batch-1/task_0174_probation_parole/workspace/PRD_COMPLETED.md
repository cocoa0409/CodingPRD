# Probation & Parole Case Management API — Product Requirements Document

## 1. Introduction

Community supervision agencies carry a workload that is simultaneously clinical, financial, and judicial. A single supervisee on probation or parole is, at any given moment, the subject of a risk-classification instrument, a slate of court-ordered conditions, a recurring schedule of office check-ins and drug screens, an accumulating ledger of restitution and supervision fees, and — when things go wrong — a chain of violations, sanctions, and possible revocation. The officers and judges who manage these cases need a system that keeps every one of those threads consistent with the others, so that a positive drug test, a missed appointment, or a paid-down restitution balance immediately and correctly moves the case to its proper supervision posture.

This document specifies the Probation & Parole Case Management API: the authoritative back-end for opening supervision cases, scoring risk with the LSI-R instrument, tracking conditions and check-ins, adjudicating violations through a sanction matrix, maintaining restitution and fee ledgers, producing court reports, processing interstate-compact transfers, and ruling on early termination. The system is built around a derived **supervision level** posture that is recomputed whenever a new risk assessment is adopted and that gates which conditions and operations are permitted. It enforces a strict segregation of duties between the officers who file findings and the judges who sustain them, and it preserves exact arithmetic across two distinct accounting conventions for money owed and two distinct conventions for risk scoring.

The reader should treat this document as the single source of truth for the system's behavior. Every entity attribute, state transition, calculation, and validation described below is contractual: the test suite that grades an implementation is derived from these requirements, and ambiguity in the prose is the implementer's risk to resolve in favor of the rules as written.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint. Where a later business-logic subsection in §3 appears to assume one of these conventions, the convention defined here governs.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. If either header is missing or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the declared role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly three roles, spelled precisely as follows: `Officer`, `SupervisingJudge`, and `CompactAdministrator`.

An `Officer` is a probation or parole officer. Officers open and drive supervision cases, draft and adopt risk assessments, propose and activate conditions, schedule and resolve check-ins, record drug-test results, file violations and appeal sustained ones, tender payments, request and withdraw interstate transfers, and petition for early termination. When `X-User-Role` is `Officer`, `X-User-ID` is the `id` of the acting `Officer` entity; ownership and segregation-of-duties checks on any resource that references an officer (for example, the `filed_by_officer_id` recorded on a violation) compare that foreign-key field to `X-User-ID`.

A `SupervisingJudge` is a judicial officer. Judges sustain or dismiss violations, rule on revocation and reinstatement, grant or deny early-termination petitions, waive conditions, discharge financial obligations, and complete cases. When `X-User-Role` is `SupervisingJudge`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as the `sustained_by_actor_id` written onto a violation when it is sustained) but does not compare it to any entity's `id` — except where a segregation-of-duties rule explicitly compares it against a stored officer id.

A `CompactAdministrator` administers the interstate compact. Compact administrators register officers and accept or reject interstate-transfer requests. When `X-User-Role` is `CompactAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

All three roles may perform every read (GET) operation in the system. Write operations are restricted as described throughout §3 and summarized in the §4 endpoint table.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0 with no upper bound beyond the size of the collection. These bounds are validated rather than clamped: a `limit` below 1 or above 100, a negative `offset`, or a non-integer value supplied for either parameter is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order.

Each list response carries the pagination bookkeeping inside the `meta` object of the envelope, namely `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of records matching the query before pagination and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties and Versioning

Every persisted resource is assigned a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp that is an ISO 8601 UTC value carrying three fractional-second digits, fixed at the moment the resource is first created.

Most resources additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is an ISO 8601 UTC timestamp (also with three fractional digits) refreshed on every mutation of the resource, and `version` is an integer that begins at the resource's initial value and increments by one on each mutation. The `version` field is the basis for optimistic concurrency control described in §2.6. These four common properties apply to the `Officer`, `Supervisee`, `RiskAssessment`, `SupervisionCondition`, `CheckIn`, `DrugTest`, `Violation`, `Sanction`, `FinancialObligation`, `CourtReport`, `InterstateTransfer`, and `EarlyTermination` resources.

The `Payment` resource is the sole exception: it is an immutable posting record. A `Payment` carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field, because once a payment is allocated it is never modified.

Whenever an operation mutates a resource — whether a direct state transition or an automatic recomputation triggered as a side effect of some other action — that resource's `updated_at` is refreshed and its `version` is incremented by one. This is true even when the field that changed is a computed value such as `cumulative_violation_points`, `restitution_balance_cents`, or `supervision_level` on a supervisee: a recomputation that changes the stored value is a mutation and bumps the version exactly as the state machines specify.

### 2.5. Nested Resource Retrieval and Existence Ordering

Most resources in this system live beneath a supervisee, and their canonical paths nest the supervisee identifier ahead of the child identifier. When a request path contains more than one resource identifier, the system validates each identifier's existence in left-to-right order: the supervisee is resolved before any child, and a child is resolved before its own grandchild (for example, a check-in is resolved before a drug test recorded under it). The first identifier in the path that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404), before any deeper identifier or any business rule is evaluated.

Beyond path identifiers, the system also resolves foreign-key references carried in request bodies. When a create request names a related resource — for instance an `assigned_officer_id`, a `supervisee_id`, a `parent_obligation_id`, a `source_drug_test_id`, a `violation_id`, or a `check_in_id` — and that reference does not point to an existing record, the request is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 422). Path-existence (404) is evaluated before body-reference existence (422).

For discovery, the system also exposes flat top-level collections for each child entity type that can be filtered by their owning foreign keys (for example, listing all risk assessments for a given `supervisee_id`, all drug tests for a given `check_in_id`, or all sanctions for a given `violation_id`). These reverse-reachability reads return the same resource shapes as their nested counterparts. List collections may additionally be narrowed by their resources' own attributes — for example, filtering check-ins, conditions, violations, obligations, transfers, court reports, or petitions by their `status`, filtering risk assessments by their `assessment_status`, filtering officers by `role_type`, filtering drug tests by `result`, or filtering obligations by `obligation_type` — and these filters compose with the owning foreign-key filter and with pagination.

### 2.6. Optimistic Concurrency Control on Supervisee-Superseding Writes

Opening an interstate-transfer request is the one write in this system that must be guarded against acting on a stale supervisee. A request to create an `InterstateTransfer` for a supervisee must carry an `expected_supervisee_version` field whose value is the `version` of the parent `Supervisee` that the requester last observed. This field is mandatory on transfer creation; it is not an optional optimistic check.

If `expected_supervisee_version` does not equal the supervisee's current `version`, the create is rejected with `ERR_STALE_SUPERVISEE_VERSION` (HTTP 412). The rationale is that a transfer request legitimately reflects the supervisee's current eligibility posture — status and cumulative violation points — and if another writer has advanced the supervisee's version since the requester last read it (by adopting a new risk assessment, sustaining a violation, or any other versioning mutation), the requester's view is stale and the transfer must be re-evaluated against a fresh snapshot rather than written blindly. No other endpoint in the system accepts or requires a version field; only interstate-transfer creation participates in optimistic concurrency control.

### 2.7. The Supervision-Level Posture and Its Ordering

Each supervisee carries a derived `supervision_level` posture, one of `ADMINISTRATIVE`, `MINIMUM`, `MEDIUM`, or `MAXIMUM`. These four levels are strictly ordered from lowest to highest as `ADMINISTRATIVE` < `MINIMUM` < `MEDIUM` < `MAXIMUM`. Wherever the system compares two levels — to decide whether a condition may be activated, or whether an override may legally raise a derived band — this ordering is the comparison basis. A newly opened supervisee defaults to `MINIMUM` until its first risk assessment is adopted, at which point the level is recomputed from the adopted assessment as described in §3.

The supervision level is never set directly by a client. It is always a computed projection of the latest adopted risk assessment, and it propagates downward to the supervisee's conditions: a condition cannot remain `ACTIVE` while the supervisee's level sits below the condition's `minimum_level_required`.

### 2.8. Monetary Ledgers and Two Accounting Conventions

All money in the system is tracked in integer cents; there is no rounding of currency, because cents are the smallest unit and every amount is stored and computed as a whole number of cents. A supervisee carries two posted ledger balances: `restitution_balance_cents`, the chronological balance of all `RESTITUTION` obligations net of applied payments, and `fee_balance_cents`, the chronological balance of all `FEE` obligations net of applied payments. Both are computed fields; clients never write them directly.

The system distinguishes two accounting conventions for the same set of obligations, and the difference between them is deliberate. The **posted (chronological) balances** — `restitution_balance_cents` and `fee_balance_cents` — sum only currently-outstanding amounts: for each open obligation, its principal plus any fee accrual already earned up to the present moment, minus what has been paid. The **forward-looking projected payoff**, by contrast, additionally projects future fee accrual through a caller-supplied date. For a supervisee with recurring fees, the projected figure is larger than the posted balance for the same obligations. The posted balances drive case-closure gates (early termination and completion); the projected payoff is a read-only quote used for planning. Their full formulas appear in §3.

### 2.9. Risk Scoring: Actuarial Band and Clinical Override

The LSI-R instrument produces two valid supervision levels from the same domain scores depending on whether an officer exercises professional discretion. Under the **actuarial-band** convention, the supervisee's supervision level is taken straight from the band table that maps the total score to a level. Under the **clinical-override** convention, the officer supplies an `override_level` (with a mandatory `override_reason`), and the effective level becomes the override. The override may only raise the level relative to the derived band, never lower it: an override that sits below the derived band by the level ordering is rejected. The detailed band boundaries and the override rule live in §3.

### 2.10. Cascading Side Effects and Hierarchical Consistency

The supervisee is the aggregate root of the case. Many operations on its children bubble effects up to the root, and many root transitions cascade effects down to children. Adopting a risk assessment can supersede a prior assessment, recompute the root's supervision level, and force-suspend conditions that the new level no longer supports. Sustaining a violation assigns points, advances the root's cumulative point total, selects a sanction from the matrix, and — when that sanction is a revocation referral — can flip the supervisee's status. Revoking, completing, granting early termination, or accepting an interstate transfer each cascades a status change onto the supervisee's active conditions. Every one of these cascades is mandatory and immediate; each resource the cascade touches has its `updated_at` refreshed and its `version` incremented as described in §2.4. The complete cascade chains, including their depth and ordering, are specified in §3 alongside the workflows that trigger them.

### 2.11. Validation Ordering

When more than one validation could apply to a single request, the checks are evaluated in a fixed priority order, and the first failure determines the error returned. The order is: authentication (`ERR_UNAUTHENTICATED`) first; then authorization (`ERR_UNAUTHORIZED`); then path existence, validated left-to-right (`ERR_NOT_FOUND`); then body foreign-key existence (`ERR_REFERENCE_NOT_FOUND`); then request well-formedness — required fields present and well-typed, enum members valid, integer cents and months at or above their declared minimums (`ERR_INVALID_REQUEST`); then the domain-specific semantic checks. Among the domain-specific checks the relative ordering matters wherever two could fire on the same request, and those orderings are called out where the workflows are described in §3. The general principle is that structural problems (who you are, whether the thing exists, whether the payload is well-formed) are always reported before business-rule problems (whether the action is allowed in the current state).

## 3. Business Logic & Workflows

This section narrates how the system actually behaves across the life of a supervision case. The rules are organized by the natural arc of a case rather than by entity, so a single endpoint's inputs and effects are sometimes described in more than one place; readers should treat the whole of §3 as one specification.

### 3.1. Registering Officers and Opening a Case

Before any case can be supervised, the officers who supervise it must exist. A `CompactAdministrator` registers an officer by supplying the officer's `full_name`, a `badge_number`, and a `role_type` that is one of `PROBATION` or `PAROLE`; an optional `active` flag defaults to `true` when omitted and governs whether the officer may be assigned new cases. Badge numbers are unique across all officers, and an attempt to register a second officer with an existing `badge_number` is rejected with `ERR_DUPLICATE_KEY` (HTTP 409).

An `Officer` opens a supervision case, minting a `Supervisee`. The opening payload provides the supervisee's `full_name`, a `docket_number`, a `supervision_type` of either `PROBATION` or `PAROLE`, the `assigned_officer_id` of the supervising officer, a two-letter uppercase `sentence_state_code` naming the sending state where the sentence originates, an `ordered_term_months` value (the total court-ordered supervision term in whole months, which must be at least 1), and a `supervision_start_date` (the ISO date supervision began, which anchors the term and early-termination math). Docket numbers are unique across all supervisees; a duplicate `docket_number` is rejected with `ERR_DUPLICATE_KEY` (HTTP 409).

The assigned officer must be a fit for the case. At case-open time the system verifies that the officer named by `assigned_officer_id` has a `role_type` equal to the supervisee's `supervision_type` and is currently active; if the officer's role does not match the supervision track or the officer is not active, the request is rejected with `ERR_OFFICER_ROLE_MISMATCH` (HTTP 422). When all checks pass, the supervisee is minted in `INTAKE` status with a default `supervision_level` of `MINIMUM`, a `cumulative_violation_points` of 0, and both `restitution_balance_cents` and `fee_balance_cents` at 0.

A newly opened case sits in `INTAKE` and cannot yet operate. To move it to `ACTIVE`, an `Officer` activates the case, but activation is permitted only when the supervisee is in `INTAKE` and at least one risk assessment for the supervisee has already been adopted (so that the supervision level reflects a real assessment rather than the bare default). Activation from any state other than `INTAKE` is rejected with `ERR_INVALID_STATE` (HTTP 409); activation while no assessment has been adopted is likewise refused on the same ground. Activation changes no balances — it only opens the case — and increments the supervisee's `version` by one.

### 3.2. Risk Assessment, the LSI-R Score, and the Supervision-Level Posture

The supervision level is established by the LSI-R risk-assessment instrument. An `Officer` creates a risk assessment for a supervisee, supplying a `domain_scores` object and, optionally, an `instrument` (which defaults to `LSI_R` and may only be `LSI_R`), an `override_level`, and an `override_reason`. The `domain_scores` object maps each of the ten LSI-R domain names to a raw non-negative integer sub-score. The ten domain keys are exactly `criminal_history`, `education_employment`, `financial`, `family_marital`, `accommodation`, `leisure_recreation`, `companions`, `alcohol_drug`, `emotional_personal`, and `attitudes_orientation`. If `domain_scores` does not contain exactly these ten keys, or if any value is negative, the request is rejected with `ERR_INCOMPLETE_LSIR_DOMAINS` (HTTP 422).

The assessment's `total_score` is the sum of all ten domain sub-scores; it ranges from 0 to 54 and is never rounded (the figures are integers throughout). The `derived_level` is then looked up from the total by these actuarial bands: a total of 13 or below derives `ADMINISTRATIVE`; a total from 14 through 23 derives `MINIMUM`; a total from 24 through 33 derives `MEDIUM`; and a total of 34 or above (up through the maximum of 54) derives `MAXIMUM`. When the assessment is created it is minted with its `assessment_status` at `DRAFT` and with `total_score` and `derived_level` computed as a preview.

When an `override_level` is supplied, the officer is exercising clinical discretion to raise the posture above the actuarial band. An override is legal only when it is greater than or equal to the `derived_level` by the level ordering `ADMINISTRATIVE` < `MINIMUM` < `MEDIUM` < `MAXIMUM` — that is, the override may raise the level or leave it equal, but it may never lower it below the derived band — and only when a non-empty `override_reason` accompanies it. An override below the derived level, an override supplied without a reason, or an `override_level` that is not one of the four supervision-level enum members, is rejected with `ERR_INVALID_OVERRIDE` (HTTP 422) — this override-specific check supersedes the general enum well-formedness check for the `override_level` field. The effective level the assessment will impose is the higher of the derived band and the override: when no override is given, the effective level equals `derived_level`; when an override is given, the effective level equals `override_level` (which by the rule above is at least the derived band).

Adopting an assessment is what actually moves the case posture. An `Officer` adopts a `DRAFT` assessment, permitted only when the assessment is in `DRAFT` status and the supervisee is in one of `INTAKE`, `ACTIVE`, or `ABSCONDED`. Adoption from a non-`DRAFT` assessment is rejected with `ERR_INVALID_STATE` (HTTP 409). On adoption the system recomputes the assessment's `total_score` and `derived_level` from the domain scores, then performs a cascade: any other assessment for the same supervisee that was previously `ADOPTED` transitions to `SUPERSEDED`; the supervisee's `supervision_level` is recomputed from this assessment's effective level (the `override_level` when set, otherwise the `derived_level`); and any condition that is currently `ACTIVE` but whose `minimum_level_required` now exceeds the new supervision level is force-suspended to `SUSPENDED`. The newly adopted assessment moves to `ADOPTED` status, and the supervisee's `version` is incremented by one. A `SUPERSEDED` assessment is terminal and can never be adopted again.

### 3.3. Court-Ordered Conditions and the Posture Gate

Conditions are the concrete obligations a court places on a supervisee. An `Officer` proposes a condition by supplying its `condition_type` — one of `DRUG_TESTING`, `CURFEW`, `NO_CONTACT`, `EMPLOYMENT`, `TREATMENT`, `ELECTRONIC_MONITORING`, or `TRAVEL_RESTRICTION` — together with an optional free-text `description` and an optional `minimum_level_required`, the lowest supervision level at which the condition becomes enforceable. The `minimum_level_required` defaults to `MINIMUM` when omitted and is one of the four supervision levels. A proposed condition is minted in `PROPOSED` status.

A condition becomes enforceable only when it is activated, and activation is gated by the supervisee's posture. An `Officer` activates a condition, which is permitted only when the condition is in `PROPOSED` status (or in `SUSPENDED` status, for re-activation after a posture recovery), the supervisee is in `ACTIVE` status, and the supervisee's current `supervision_level` is greater than or equal to the condition's `minimum_level_required` by the level ordering. These three preconditions are evaluated in that order: the condition's own status is checked first, then the supervisee's status, then the level gate. Attempting to activate a condition that is not in `PROPOSED` or `SUSPENDED` status is rejected with `ERR_INVALID_STATE` (HTTP 409); activating while the supervisee is not in `ACTIVE` status is likewise rejected with `ERR_INVALID_STATE` (HTTP 409); and only once both of those pass, if the supervisee's level sits below the condition's `minimum_level_required`, activation is refused with `ERR_LEVEL_TOO_LOW_FOR_CONDITION` (HTTP 409). A successful activation moves the condition to `ACTIVE` and increments the condition's `version` by one.

A condition's later life takes one of several paths. An `Officer` may satisfy an `ACTIVE` condition, moving it to the terminal `SATISFIED` status and incrementing its `version` by one; satisfying a condition that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. A `SupervisingJudge` may waive a `PROPOSED` condition, moving it to the terminal `WAIVED` status and incrementing its `version`; waiving a condition that is not `PROPOSED` is rejected with `ERR_INVALID_STATE`. Separately, the system itself may suspend an `ACTIVE` condition — never by direct client request — when the supervisee's supervision level drops below the condition's `minimum_level_required` (as a downstream effect of adopting a lower-posture assessment) or when the supervisee is revoked; suspension moves the condition to `SUSPENDED` and increments its `version`. A `SUSPENDED` condition can be brought back to `ACTIVE` by an officer once the supervisee's posture again meets or exceeds the condition's `minimum_level_required`, under the same activation rules described above.

### 3.4. Check-Ins, Punctuality, and Drug Testing

Supervisees report to their officer on a schedule of check-ins. An `Officer` schedules a check-in by supplying the `scheduled_for` timestamp (the start of the appointment window), an optional `window_minutes` value (the length in minutes of the on-time window after `scheduled_for`, defaulting to 60 and required to be at least 1), and an optional `requires_drug_test` flag (defaulting to `false`) indicating whether a drug test must accompany the visit. A scheduled check-in is minted in `SCHEDULED` status.

Two check-ins for the same supervisee may not have overlapping appointment windows. Each check-in occupies the half-open interval that begins at its `scheduled_for` and ends at `scheduled_for` plus `window_minutes`; the interval includes its start instant but excludes its end instant. Two such intervals overlap when one begins strictly before the other ends and ends strictly after the other begins; pure adjacency, where one window begins exactly at the instant a prior window closes, is permitted. A new check-in whose window would overlap an existing window for the same supervisee is rejected with `ERR_CHECKIN_WINDOW_OVERLAP` (HTTP 409).

When the supervisee appears, an `Officer` marks the check-in attended, supplying the `attended_at` timestamp at which the supervisee actually arrived. Attendance is permitted only from `SCHEDULED` status, and if the check-in `requires_drug_test`, a drug test bearing a result must already exist for the check-in before it can be attended; attempting to attend without the required test (or from a non-`SCHEDULED` status) is rejected with `ERR_INVALID_STATE` (HTTP 409). On attendance the system records `attended_at`, derives the `punctuality`, moves the check-in to `ATTENDED`, and increments the check-in's `version` by one. Punctuality is determined by comparing `attended_at` against the close of the on-time window: let the window close be `scheduled_for` plus `window_minutes` minutes; if `attended_at` is at or before the window close, `punctuality` is `ON_TIME`, and otherwise it is `LATE`. The boundary is inclusive — arriving exactly at the window-close instant counts as `ON_TIME`. Until a check-in is attended, its `punctuality` is null.

A check-in that the supervisee misses is handled differently. An `Officer` may mark a `SCHEDULED` check-in as missed, but only after the on-time window has fully closed — that is, only when the server's current clock time is strictly greater than `scheduled_for` plus `window_minutes`. The `SCHEDULED` status is checked first: attempting to mark missed from a non-`SCHEDULED` status is rejected with `ERR_INVALID_STATE` (HTTP 409); only then is the window examined, and attempting to mark a still-`SCHEDULED` check-in missed before its window has closed is rejected with `ERR_WINDOW_NOT_CLOSED` (HTTP 409). Marking a check-in missed moves it to `MISSED` and, as a cross-entity side effect, auto-creates a `Violation` of class `TECHNICAL` filed by the acting officer (its `filed_by_officer_id` set to the acting officer's id) in `FILED` status; the check-in's `version` is incremented by one. Alternatively, an `Officer` may excuse a `SCHEDULED` check-in, moving it to the terminal `EXCUSED` status with no violation created and incrementing its `version`.

Drug tests are recorded against a check-in. An `Officer` records a drug-test result for a check-in by supplying the `result` — one of `NEGATIVE`, `POSITIVE`, `DILUTE`, or `REFUSED` — along with an optional `panel` (one of `FIVE_PANEL` or `TEN_PANEL`, defaulting to `FIVE_PANEL`) and an optional `substances` array of detected substance codes. The `substances` list carries the detected codes when the result is `POSITIVE` and is otherwise empty; supplying a non-empty `substances` list when the result is not `POSITIVE` is a semantic error rejected with `ERR_VALIDATION` (HTTP 422). The drug test is linked to its check-in via `check_in_id`. A recorded positive or refused test may later be cited as the originating cause of a violation through that violation's `source_drug_test_id`.

### 3.5. Violations, Adjudication, and the Sanction Matrix

A violation is the formal record that a supervisee has breached a condition or the law. An `Officer` files a violation by supplying its `violation_class` — one of `TECHNICAL`, `MISDEMEANOR`, `FELONY`, or `ABSCOND` — and the `filed_by_officer_id` identifying the filing officer, optionally citing an originating `source_drug_test_id` when the violation stems from a positive or refused drug test (this field is null for non-test violations). A filed violation is minted in `FILED` status, and its `points` remain at 0 until and unless it is sustained.

Adjudication is reserved to the judiciary and is governed by a strict separation between filing and finding. A `SupervisingJudge` may sustain a `FILED` violation, but the acting judge — identified by `X-User-ID` — must differ from the violation's `filed_by_officer_id`. This is the segregation-of-duties rule: the actor who filed a violation may not also be the actor who sustains it. If the sustaining actor equals the violation's `filed_by_officer_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). Sustaining a violation that is not in `FILED` status is rejected with `ERR_INVALID_STATE` (HTTP 409). Furthermore, a violation may be sustained only while its parent supervisee is not in a terminal status: if the supervisee is `REVOKED`, `TERMINATED_EARLY`, `COMPLETED`, or `TRANSFERRED_OUT`, the sustain is rejected with `ERR_SUPERVISEE_CLOSED` (HTTP 409). Where more than one of these could fire on the same sustain request, the closed-supervisee guard is evaluated before the segregation-of-duties check, which in turn is evaluated after the state check that confirms the violation is `FILED`.

Sustaining a violation triggers a chain of effects whose order is fixed. First, the violation is assigned `points` according to its class: a `TECHNICAL` violation is worth 2 points, a `MISDEMEANOR` 4 points, a `FELONY` 6 points, and an `ABSCOND` 12 points. Second, the supervisee's `cumulative_violation_points` is recomputed as the exact sum of `points` across all of that supervisee's violations currently in `SUSTAINED` status — a full recompute rather than an increment, so that later appeals leave the total exact. Third, the system selects and auto-creates a `Sanction` for this violation from the sanction matrix, using the violation's class and the supervisee's resulting cumulative tier. Fourth, when the matrix selects a revocation referral and the supervisee was `ACTIVE`, the sanction's creation flips the supervisee's status from `ACTIVE` to `REVOCATION_PENDING`. Finally, the violation's `sustained_by_actor_id` is set to the acting judge's id, the violation moves to `SUSTAINED`, and both the violation's `version` and the supervisee's `version` are incremented by one.

The sanction matrix selects a sanction from three inputs: the `violation_class`, the supervisee's resulting cumulative point tier, and the implicit prior history captured in that running total. Begin from the cumulative total the supervisee would have after this sustain — that is, the cumulative point total including the points just assigned. That post-sustain cumulative places the case in a tier: a total of 4 or below is the first tier; a total from 5 through 8 is the second tier; a total from 9 through 11 is the third tier; and a total of 12 or above is the fourth tier. The matrix then chooses as follows. If the violation's class is `ABSCOND`, or the post-sustain total reaches the fourth tier (12 or more), the `sanction_type` is `REVOCATION_REFERRAL` with `imposed_days` of 0. Otherwise, in the third tier (9 through 11), the `sanction_type` is `JAIL_SHOCK` and the `imposed_days` is computed as the post-sustain cumulative total minus 9, multiplied by 2 (so a total of 9 yields 0 days, 10 yields 2 days, and 11 yields 4 days). Otherwise, in the second tier (5 through 8), the `sanction_type` is `CURFEW_IMPOSITION` when the violation class is `MISDEMEANOR` or `FELONY`, and `INCREASED_REPORTING` when it is any other class, with `imposed_days` of 0 in either case. Otherwise, in the first tier (4 or below), the `sanction_type` is `VERBAL_WARNING` with `imposed_days` of 0. Every minted sanction begins in `IMPOSED` status and references the sustained violation through its `violation_id`.

A sustained violation can be challenged. An `Officer` may appeal a `SUSTAINED` violation, moving it to `APPEALED` status; appealing a violation that is not `SUSTAINED` is rejected with `ERR_INVALID_STATE`. An appeal is a compensating action that conserves the point total: it subtracts that violation's `points` from the supervisee's `cumulative_violation_points` (equivalently, the cumulative is recomputed over the remaining `SUSTAINED` violations and so falls by exactly those points), and any `Sanction` tied to the appealed violation transitions to `VACATED`. If that sanction had previously flipped the supervisee to `REVOCATION_PENDING`, and the supervisee is still `REVOCATION_PENDING` and the recomputed cumulative now sits below the revocation-referral threshold of 12 points, the appeal reverts the supervisee's status from `REVOCATION_PENDING` back to `ACTIVE`. Both the violation's `version` and the supervisee's `version` are incremented by one on appeal.

A filed violation may also be dismissed rather than sustained. A `SupervisingJudge` dismisses a `FILED` violation, moving it to the terminal `DISMISSED` status; dismissal assigns no points and makes no change to the supervisee's cumulative total, and it increments the violation's `version` by one. Dismissing a violation that is not `FILED` is rejected with `ERR_INVALID_STATE`.

The sanctions attached to a violation are readable on their own as a sub-collection of that violation, addressable by the violation's identifier.

### 3.6. Financial Obligations, Fee Accrual, and Payment Allocation

Money owed by a supervisee is recorded as financial obligations. Either an `Officer` or a `SupervisingJudge` may record an obligation, supplying its `obligation_type` (one of `RESTITUTION` or `FEE`), a `principal_cents` value (the original amount owed in cents, which must be at least 1), and optionally a `parent_obligation_id`, a `monthly_accrual_cents`, and a `recurring` flag. The `parent_obligation_id` references a master obligation when this row is one installment of a split restitution order; it is null for standalone obligations. The `monthly_accrual_cents` value (defaulting to 0) is the monthly supervision-fee accrual in cents and is only meaningful for `FEE` obligations whose `recurring` flag is `true`; `recurring` itself defaults to `false`. A newly recorded obligation is minted in `OPEN` status with `paid_cents` at 0, and the supervisee's posted balances are recomputed to include it.

A recurring fee accrues over time. For a `FEE` obligation whose `recurring` flag is `true`, the obligation accrues `monthly_accrual_cents` for each whole month that has elapsed since its `created_at`. Partial months never accrue: the number of accruing months is the whole-month count between `created_at` and the moment of evaluation, taking the floor (so an obligation two-and-a-half months old has accrued exactly two months of fees). The outstanding amount of an obligation at any moment is its `principal_cents`, plus any accrual it has earned up to that moment, minus its `paid_cents`.

The supervisee's two posted ledger balances follow directly from these obligations. The `restitution_balance_cents` is the sum, over every `RESTITUTION` obligation that is still `OPEN` or `PARTIALLY_PAID`, of that obligation's outstanding amount measured to the present moment (principal plus accrual-to-now minus paid); `RESTITUTION` obligations carry no recurring accrual, so for them the outstanding amount is simply principal minus paid. The `fee_balance_cents` is the corresponding sum over `FEE` obligations that are still `OPEN` or `PARTIALLY_PAID`, including each recurring fee's accrual earned up to now. Obligations that are `PAID` or `DISCHARGED` contribute nothing to either balance. These posted balances never project future accrual; they reflect only what is outstanding as of the present moment.

A `SupervisingJudge` may discharge an obligation, forgiving its remaining balance. Discharge is permitted only when the obligation is `OPEN` or `PARTIALLY_PAID`; it moves the obligation to the terminal `DISCHARGED` status, recomputes the supervisee's posted balances so the discharged obligation's outstanding amount no longer counts, and increments the obligation's `version` by one. Discharging an obligation in any other status is rejected with `ERR_INVALID_STATE`.

Payments are applied through a waterfall. An `Officer` tenders a payment by supplying an `amount_cents` (the tendered amount in cents, which must be at least 1) and an optional `allocation_policy` (one of `RESTITUTION_FIRST` or `OLDEST_FIRST`, defaulting to `RESTITUTION_FIRST`) that selects the ordering in which obligations are paid down. The payment is distributed across the supervisee's obligations that are `OPEN` or `PARTIALLY_PAID`, in a deterministic order. Under `RESTITUTION_FIRST`, obligations are ordered first by type with restitution ahead of fees, then by ascending `created_at`, then by ascending `parent_obligation_id` as the final tie-break. Under `OLDEST_FIRST`, obligations are ordered first by ascending `created_at`, then by type with restitution ahead of fees, then by ascending `parent_obligation_id`. Creation time in ascending order is the sole chronological tie-break; the obligation's own `id` is never used to order allocation.

Walking the obligations in that order, the system takes from each the smaller of the payment's remaining amount and that obligation's current outstanding amount (principal plus accrual-to-now minus already-paid, never less than zero), records that taken amount in the payment's `applied_breakdown` keyed by obligation id, adds it to the obligation's `paid_cents`, and reduces the remaining payment by that amount; it stops once the remaining amount reaches zero. As each obligation's `paid_cents` advances, the obligation's status moves accordingly: an `OPEN` obligation that receives a partial payment becomes `PARTIALLY_PAID`, an `OPEN` obligation fully covered by a single payment becomes `PAID`, and a `PARTIALLY_PAID` obligation whose cumulative `paid_cents` reaches its full outstanding-with-accrual total becomes `PAID`. Each such status change recomputes the supervisee's posted balances. The payment's `posted_at` records the server timestamp at which the payment posted and is the tie-break basis for ordering payments.

A payment may never exceed what is owed. Before any allocation is posted, the payment's `amount_cents` is checked against the supervisee's total currently-outstanding balance across all `OPEN` and `PARTIALLY_PAID` obligations, measured chronologically with no future projection. If the tendered amount exceeds that total — meaning some money would remain after every obligation is filled — the entire payment is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422); the system never posts a partial payment and never leaves an overpayment unallocated. Each payment also carries the `supervisee_id` of the supervisee whose payment it is.

For reporting, payments are discoverable both as the supervisee's full payment list and, for a given obligation, as the set of payments that applied money to that obligation through their `applied_breakdown`.

### 3.7. Absconding, Revocation, and Case Closure

A case can go off the rails. When a supervisee stops reporting, an `Officer` marks the case absconded, which is permitted only when the supervisee is `ACTIVE`. Absconding moves the supervisee from `ACTIVE` to `ABSCONDED` and, as the first link of the abscond cascade, auto-creates a `Violation` of class `ABSCOND` filed by the acting officer (its `filed_by_officer_id` set to that officer's id) in `FILED` status; the supervisee's `version` is incremented by one. The abscond violation is adjudicated separately like any other. When the supervisee resurfaces, an `Officer` returns the case to supervision, permitted only when the supervisee is `ABSCONDED`; this rebound moves the supervisee back from `ABSCONDED` to `ACTIVE` and increments the `version` by one, and it deliberately does not dismiss the outstanding abscond violation, which remains for separate adjudication.

Revocation proceedings can be opened from either an active or an absconded posture. An `Officer` refers a case for revocation. From the `ACTIVE` state, referral is permitted only when the supervisee's `cumulative_violation_points` is at or above the revocation-referral threshold of 12 points; from the `ABSCONDED` state, an absconder may be referred regardless of point total. Either way the supervisee moves to `REVOCATION_PENDING` and its `version` is incremented by one. A referral attempted from a state other than `ACTIVE` or `ABSCONDED` is rejected with `ERR_INVALID_STATE`, as is an `ACTIVE`-state referral whose point total is below the threshold.

The judiciary resolves a pending revocation. A `SupervisingJudge` may revoke a `REVOCATION_PENDING` case, which is terminal: it moves the supervisee to `REVOKED`, freezes the ledger, cascades all of the supervisee's `PROPOSED` and `ACTIVE` conditions to `SUSPENDED`, and increments the supervisee's `version` by one. Alternatively, a `SupervisingJudge` may reinstate a `REVOCATION_PENDING` case — declining revocation — which moves the supervisee back to `ACTIVE` and increments the `version` by one. Either action attempted from a non-`REVOCATION_PENDING` status is rejected with `ERR_INVALID_STATE`.

A case may close cleanly by completion. A `SupervisingJudge` completes an `ACTIVE` case, but completion requires that the case be fully squared away: both the `restitution_balance_cents` and the `fee_balance_cents` must be exactly zero, and the supervisee must have no violation in `FILED` or `APPEALED` status. If either balance is non-zero, completion is rejected with `ERR_OUTSTANDING_BALANCE` (HTTP 409); if any violation remains in `FILED` or `APPEALED`, completion is refused on state grounds. Completion is terminal: it moves the supervisee to `COMPLETED`, cascades all `ACTIVE` conditions to `SATISFIED`, and increments the supervisee's `version` by one. Completing a case that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`.

### 3.8. Interstate Transfers Under the Compact

A supervisee may be moved to another state's supervision under the interstate compact. An `Officer` requests a transfer, supplying the two-letter uppercase `receiving_state_code` of the destination state and the `expected_supervisee_version` optimistic-concurrency token described in §2.6. The receiving state must differ from the supervisee's `sentence_state_code`; a transfer whose `receiving_state_code` equals the sending state's code is a semantic error rejected with `ERR_VALIDATION` (HTTP 422). Only one live compact claim may exist at a time: if a transfer for this supervisee is already in `REQUESTED` or `ACCEPTED` status, a new transfer request is rejected with `ERR_TRANSFER_ALREADY_OPEN` (HTTP 409). And as established in §2.6, the request's `expected_supervisee_version` must equal the supervisee's current `version`, or the create is rejected with `ERR_STALE_SUPERVISEE_VERSION` (HTTP 412). A successful request mints the transfer in `REQUESTED` status and increments the supervisee's `version` by one.

The receiving state decides the request. A `CompactAdministrator` may accept a `REQUESTED` transfer, supplying the `decided_at` timestamp at which the receiving state ruled. Acceptance is permitted only when the transfer is `REQUESTED`, the supervisee is `ACTIVE`, and the supervisee's `cumulative_violation_points` is strictly below the revocation-referral threshold of 12 points; these are checked in that order. An acceptance attempted on a transfer that is not `REQUESTED`, or on a transfer whose supervisee is not in `ACTIVE` status, is rejected with `ERR_INVALID_STATE` (HTTP 409); and only once those pass, an acceptance for a supervisee whose points are at or above 12 — high-risk, absconding-prone cases that cannot be exported — is rejected with `ERR_TRANSFER_BLOCKED_HIGH_RISK` (HTTP 409). Acceptance moves the transfer to `ACCEPTED` and bubbles up to the root: the supervisee transitions from `ACTIVE` to the terminal `TRANSFERRED_OUT`, all of the supervisee's `ACTIVE` conditions cascade to `SATISFIED` on the sending side, and both the transfer's `version` and the supervisee's `version` are incremented by one. Alternatively, a `CompactAdministrator` may reject a `REQUESTED` transfer, also supplying `decided_at`; rejection moves the transfer to `REJECTED`, makes no change to the supervisee, and increments the transfer's `version`. The originating `Officer` may instead withdraw a `REQUESTED` transfer, which moves it to `WITHDRAWN`, makes no change to the supervisee, and increments the transfer's `version`. Any of these decisions attempted on a transfer that is not `REQUESTED` is rejected with `ERR_INVALID_STATE`.

### 3.9. Early Termination

A supervisee who has served enough of their term and cleared their restitution may petition to end supervision early. An `Officer` files an early-termination petition, supplying the `requested_on` date the petition was filed. On filing, the system freezes the petition's eligibility snapshot. It computes `months_served` as the whole months elapsed from the supervisee's `supervision_start_date` to `requested_on`, taking the floor. It then computes `percent_served` as the integer floor of `months_served` multiplied by 100 and divided by `ordered_term_months`. The frozen `eligibility` object records `percent_served`, whether balances are clear, whether there are no open violations, and the overall `eligible` verdict. A petition is `eligible` exactly when all three of the following hold: `percent_served` is at least 50 (so exactly half the term served qualifies on the time axis); the `restitution_balance_cents` is exactly zero (fees may remain — only restitution must be clear for early termination); and the count of violations in `FILED` or `APPEALED` status is zero. A filed petition is minted in `SUBMITTED` status.

The judiciary rules on the petition. A `SupervisingJudge` grants a `SUBMITTED` petition only when its frozen `eligibility.eligible` is `true` and the supervisee is `ACTIVE`; these are checked in that order after the petition's own state is confirmed `SUBMITTED`, so a grant attempted while the petition's eligibility verdict is false is rejected with `ERR_NOT_ELIGIBLE_FOR_TERMINATION` (HTTP 409) before the supervisee's `ACTIVE` status is examined, and a grant of an eligible petition whose supervisee is not `ACTIVE` is rejected with `ERR_INVALID_STATE` (HTTP 409). Granting drives the supervisee from `ACTIVE` to the terminal `TERMINATED_EARLY`, sets the petition's status to `GRANTED`, cascades all `ACTIVE` conditions to `SATISFIED`, and increments both the petition's `version` and the supervisee's `version` by one. Alternatively, a `SupervisingJudge` may deny a `SUBMITTED` petition, which moves it to `DENIED`, makes no change to the supervisee, and increments the petition's `version`. Either ruling on a petition that is not `SUBMITTED` is rejected with `ERR_INVALID_STATE`.

### 3.10. Compliance Reporting, Payoff Quotes, and the Logical Clock

Two computed reads summarize a case. The compliance snapshot reports the supervisee's `compliance_rate`, `restitution_balance_cents`, `fee_balance_cents`, `cumulative_violation_points`, and `supervision_level`. The compliance rate is measured over the supervisee's terminal check-ins — those in `ATTENDED`, `MISSED`, or `EXCUSED` status, with `SCHEDULED` check-ins excluded. Let the denominator be the count of terminal check-ins and the numerator be the count of check-ins that are `ATTENDED` with `punctuality` of `ON_TIME`. When there are no terminal check-ins, the rate is exactly 100.0 (an empty history is vacuously compliant). Otherwise the system computes the exact ratio of numerator to denominator, multiplies that ratio by 100, and only then rounds the product half-up to one decimal place. The rounding order is pinned: the ratio is multiplied by 100 before rounding, never rounded first, so that repeating decimals do not drift the result.

A court report freezes that same compliance picture at a chosen date. Either an `Officer` files the report directly, or it is drafted and later filed; in either case an `Officer` creates the report by supplying its `report_type` (one of `PROGRESS`, `VIOLATION_SUMMARY`, `EARLY_TERMINATION`, or `REVOCATION`) and an `as_of_date` (the ISO date the report snapshots). On creation the report is minted in `DRAFT` status with a frozen `snapshot` capturing the `restitution_balance_cents`, `fee_balance_cents`, `cumulative_violation_points`, `supervision_level`, and `compliance_rate` at filing, computed by the same compliance-rate rule above. Either an `Officer` or a `SupervisingJudge` may then file a `DRAFT` report, moving it to the terminal `FILED` status (which locks the snapshot) and incrementing its `version` by one; filing a report that is not `DRAFT` is rejected with `ERR_INVALID_STATE`.

The payoff quote is the forward-looking projection described in §2.8. A read of the supervisee's payoff quote accepts an optional `as_of` date and reports `projected_restitution_cents`, `projected_fee_cents`, `projected_total_cents`, and the `as_of` value used; when the caller omits `as_of`, the server's current clock instant is used. The returned `as_of` is always rendered as a full ISO 8601 UTC timestamp with three fractional-second digits (the same format as other timestamps), echoing back the instant used rather than a bare date. The quote considers only obligations that are `OPEN` or `PARTIALLY_PAID`; `PAID` and `DISCHARGED` obligations are excluded. For each such obligation it starts from the outstanding amount (principal minus paid), and for a `FEE` obligation that is recurring it additionally projects future accrual: it takes the whole-month count from the obligation's `created_at` to the `as_of` date, taking the floor and never less than zero, multiplies that month count by the obligation's `monthly_accrual_cents`, and adds the result to the outstanding amount. Each obligation's projected outstanding (never less than zero) is added to its type's bucket. The `projected_restitution_cents` is the restitution bucket, the `projected_fee_cents` is the fee bucket, and the `projected_total_cents` is their sum. Because this projection adds future accrual that the posted balances do not, the projected figure for a supervisee with recurring fees is larger than the posted `fee_balance_cents` for the same obligations — that divergence is the intended difference between the projected and chronological conventions, and all figures remain integer cents with no rounding beyond the whole-month floor.

Finally, because windows, fee accrual, and months-served math all depend on the passage of time, the system exposes an administrative test-driving capability that sets the server's current UTC clock. Any of the three roles may invoke it, supplying a `to_iso8601` instant; the server adopts that instant as its current UTC time, reports the new `current_utc`, and uses it thereafter for the missed-check-in window comparison, recurring-fee accrual, and months-served calculations.

### 3.11. Terminal-Status Protection Across the Case

One safety rule cuts across several of the workflows above and deserves a consolidated statement. Once a supervisee reaches a terminal status — `REVOKED`, `TERMINATED_EARLY`, `COMPLETED`, or `TRANSFERRED_OUT` — the case is closed to further activity. Filing a violation, sustaining a violation, creating a condition, scheduling a check-in, and tendering a payment are all blocked on a closed supervisee and rejected with `ERR_SUPERVISEE_CLOSED` (HTTP 409). This guard is in addition to, and evaluated ahead of, the per-resource state checks that each individual operation already enforces.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions and the test-driving clock — return a `200 OK` status code. Read operations return `200 OK`. The request bodies, response bodies, and side effects of each endpoint are not repeated here; they are specified in the §3 narratives, and readers should reconstruct each operation's full contract from the relevant workflow subsection.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/officers` | Register a probation/parole officer | CompactAdministrator |
| GET | `/officers/{id}` | Fetch one officer | CompactAdministrator, Officer, SupervisingJudge |
| GET | `/officers` | List officers | CompactAdministrator, Officer, SupervisingJudge |
| POST | `/supervisees` | Open a supervision case | Officer |
| GET | `/supervisees/{id}` | Fetch one supervisee with computed posture and balances | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/supervisees` | List supervisees | Officer, SupervisingJudge, CompactAdministrator |
| POST | `/supervisees/{id}/activate` | Move case from INTAKE to ACTIVE | Officer |
| POST | `/supervisees/{id}/abscond` | Move case to ABSCONDED; auto-file ABSCOND violation | Officer |
| POST | `/supervisees/{id}/return-to-supervision` | Rebound from ABSCONDED to ACTIVE | Officer |
| POST | `/supervisees/{id}/refer-revocation` | Refer case to REVOCATION_PENDING | Officer |
| POST | `/supervisees/{id}/revoke` | Revoke a pending case (terminal) | SupervisingJudge |
| POST | `/supervisees/{id}/reinstate` | Decline revocation; return to ACTIVE | SupervisingJudge |
| POST | `/supervisees/{id}/complete` | Complete a case when clear of balances and open violations | SupervisingJudge |
| GET | `/supervisees/{id}/compliance` | Computed compliance snapshot | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/supervisees/{id}/payoff-quote` | Forward-looking projected payoff | Officer, SupervisingJudge, CompactAdministrator |
| POST | `/supervisees/{sid}/risk-assessments` | Create an LSI-R risk assessment (DRAFT) | Officer |
| GET | `/supervisees/{sid}/risk-assessments` | List a supervisee's risk assessments | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/supervisees/{sid}/risk-assessments/{id}` | Fetch one risk assessment | Officer, SupervisingJudge, CompactAdministrator |
| POST | `/supervisees/{sid}/risk-assessments/{id}/adopt` | Adopt an assessment; recompute posture cascade | Officer |
| POST | `/supervisees/{sid}/conditions` | Propose a supervision condition (PROPOSED) | Officer |
| GET | `/supervisees/{sid}/conditions` | List a supervisee's conditions | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/supervisees/{sid}/conditions/{id}` | Fetch one condition | Officer, SupervisingJudge, CompactAdministrator |
| POST | `/supervisees/{sid}/conditions/{id}/activate` | Activate a condition (gated by supervision level) | Officer |
| POST | `/supervisees/{sid}/conditions/{id}/satisfy` | Satisfy an active condition | Officer |
| POST | `/supervisees/{sid}/conditions/{id}/waive` | Waive a proposed condition | SupervisingJudge |
| POST | `/supervisees/{sid}/check-ins` | Schedule a check-in (overlap-checked) | Officer |
| GET | `/supervisees/{sid}/check-ins` | List check-ins | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/supervisees/{sid}/check-ins/{id}` | Fetch one check-in | Officer, SupervisingJudge, CompactAdministrator |
| POST | `/supervisees/{sid}/check-ins/{id}/attend` | Mark a check-in attended; derive punctuality | Officer |
| POST | `/supervisees/{sid}/check-ins/{id}/mark-missed` | Mark a check-in missed; auto-file TECHNICAL violation | Officer |
| POST | `/supervisees/{sid}/check-ins/{id}/excuse` | Excuse a check-in | Officer |
| POST | `/supervisees/{sid}/check-ins/{cid}/drug-tests` | Record a drug-test result for a check-in | Officer |
| GET | `/supervisees/{sid}/check-ins/{cid}/drug-tests` | List drug tests for a check-in | Officer, SupervisingJudge, CompactAdministrator |
| POST | `/supervisees/{sid}/violations` | File a violation (FILED) | Officer |
| GET | `/supervisees/{sid}/violations` | List violations | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/supervisees/{sid}/violations/{id}` | Fetch one violation | Officer, SupervisingJudge, CompactAdministrator |
| POST | `/supervisees/{sid}/violations/{id}/sustain` | Sustain a filed violation; fire sanction matrix | SupervisingJudge |
| POST | `/supervisees/{sid}/violations/{id}/dismiss` | Dismiss a filed violation | SupervisingJudge |
| POST | `/supervisees/{sid}/violations/{id}/appeal` | Appeal a sustained violation; reverse points and sanction | Officer |
| GET | `/supervisees/{sid}/violations/{vid}/sanctions` | List sanctions for a violation | Officer, SupervisingJudge, CompactAdministrator |
| POST | `/supervisees/{sid}/obligations` | Record a restitution or fee obligation (OPEN) | Officer, SupervisingJudge |
| GET | `/supervisees/{sid}/obligations` | List obligations | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/supervisees/{sid}/obligations/{id}` | Fetch one obligation | Officer, SupervisingJudge, CompactAdministrator |
| POST | `/supervisees/{sid}/obligations/{id}/discharge` | Discharge remaining balance of an obligation | SupervisingJudge |
| POST | `/supervisees/{sid}/payments` | Tender a payment; waterfall-allocated | Officer |
| GET | `/supervisees/{sid}/payments` | List payments | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/supervisees/{sid}/obligations/{oid}/payments` | List payments that applied to a given obligation | Officer, SupervisingJudge, CompactAdministrator |
| POST | `/supervisees/{sid}/court-reports` | File a court report; freeze compliance snapshot (DRAFT) | Officer |
| GET | `/supervisees/{sid}/court-reports` | List court reports | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/supervisees/{sid}/court-reports/{id}` | Fetch one court report | Officer, SupervisingJudge, CompactAdministrator |
| POST | `/supervisees/{sid}/court-reports/{id}/file` | File a draft report (locks the snapshot) | Officer, SupervisingJudge |
| POST | `/supervisees/{sid}/transfers` | Request an interstate compact transfer (OCC) | Officer |
| GET | `/supervisees/{sid}/transfers` | List transfers | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/supervisees/{sid}/transfers/{id}` | Fetch one transfer | Officer, SupervisingJudge, CompactAdministrator |
| POST | `/supervisees/{sid}/transfers/{id}/accept` | Accept a transfer; bubble to TRANSFERRED_OUT | CompactAdministrator |
| POST | `/supervisees/{sid}/transfers/{id}/reject` | Reject a transfer | CompactAdministrator |
| POST | `/supervisees/{sid}/transfers/{id}/withdraw` | Withdraw a transfer | Officer |
| POST | `/supervisees/{sid}/early-terminations` | File an early-termination petition (SUBMITTED) | Officer |
| GET | `/supervisees/{sid}/early-terminations` | List petitions | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/supervisees/{sid}/early-terminations/{id}` | Fetch one petition | Officer, SupervisingJudge, CompactAdministrator |
| POST | `/supervisees/{sid}/early-terminations/{id}/grant` | Grant a petition; drive TERMINATED_EARLY | SupervisingJudge |
| POST | `/supervisees/{sid}/early-terminations/{id}/deny` | Deny a petition | SupervisingJudge |
| GET | `/risk-assessments/{id}` | Fetch one risk assessment (flat) | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/risk-assessments` | Filtered list of risk assessments | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/conditions/{id}` | Fetch one condition (flat) | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/conditions` | Filtered list of conditions | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/check-ins/{id}` | Fetch one check-in (flat) | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/check-ins` | Filtered list of check-ins | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/drug-tests/{id}` | Fetch one drug test (flat) | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/drug-tests` | Filtered list of drug tests | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/violations/{id}` | Fetch one violation (flat) | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/violations` | Filtered list of violations | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/sanctions/{id}` | Fetch one sanction (flat) | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/sanctions` | Filtered list of sanctions | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/obligations/{id}` | Fetch one obligation (flat) | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/obligations` | Filtered list of obligations | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/payments/{id}` | Fetch one payment (flat) | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/payments` | Filtered list of payments | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/court-reports/{id}` | Fetch one court report (flat) | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/court-reports` | Filtered list of court reports | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/transfers/{id}` | Fetch one transfer (flat) | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/transfers` | Filtered list of transfers | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/early-terminations/{id}` | Fetch one petition (flat) | Officer, SupervisingJudge, CompactAdministrator |
| GET | `/early-terminations` | Filtered list of petitions | Officer, SupervisingJudge, CompactAdministrator |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC clock | Officer, SupervisingJudge, CompactAdministrator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INCOMPLETE_LSIR_DOMAINS` | 422 |
| `ERR_INVALID_OVERRIDE` | 422 |
| `ERR_OFFICER_ROLE_MISMATCH` | 422 |
| `ERR_DUPLICATE_KEY` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_LEVEL_TOO_LOW_FOR_CONDITION` | 409 |
| `ERR_WINDOW_NOT_CLOSED` | 409 |
| `ERR_CHECKIN_WINDOW_OVERLAP` | 409 |
| `ERR_TRANSFER_ALREADY_OPEN` | 409 |
| `ERR_SUPERVISEE_CLOSED` | 409 |
| `ERR_NOT_ELIGIBLE_FOR_TERMINATION` | 409 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_OUTSTANDING_BALANCE` | 409 |
| `ERR_TRANSFER_BLOCKED_HIGH_RISK` | 409 |
| `ERR_STALE_SUPERVISEE_VERSION` | 412 |
| `ERR_VALIDATION` | 422 |
