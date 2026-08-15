# SIU Fraud API — Product Requirements Document

## 1. Introduction

Insurance carriers maintain Special Investigation Units (SIUs) to detect, investigate, and deter fraudulent claims. The function operates under tightening regulatory scrutiny: state fraud bureaus impose mandatory referral rules and filing deadlines, statutes cap how long an insurer may delay payment while a claim is under review, examinations under oath carry minimum notice windows, and departments of insurance expect periodic activity reporting. Coordinating all of this across adjusters, investigators, managers, and compliance staff — while preserving an auditable chain of custody and segregation of duties — is the problem this product solves.

This document specifies the SIU Fraud API, mounted under the `/siu` prefix. The API manages the full investigative lifecycle: red-flag referral intake and weighted suspicion scoring, case opening and investigator assignment under caseload and certification constraints, evidence gathering with a formal review loop, examinations under oath, claim payment coordination with the owning adjuster, state fraud-bureau referral with per-state deadlines, restitution and recovery accounting, organized provider-ring pattern analysis, investigator training currency, and regulatory reporting. Four roles interact with the system — `Adjuster`, `SIUManager`, `SIUInvestigator`, and `SIUComplianceOfficer` — and two doctrines cut across everything they do: segregation of duties (the actor who performs one step may not perform the step that checks it) and statutory time discipline (every deadline, window, and cap is evaluated against a deterministic logical clock).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request with a missing or malformed header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles:

- `Adjuster` — a front-line claim adjuster who registers claims, submits red-flag referrals, and coordinates payment delay and release. When `X-User-Role` is `Adjuster`, `X-User-ID` is the `id` of the acting `Adjuster` resource; ownership checks on any resource that references an adjuster (for example, a claim's `adjuster_id`) compare that foreign-key field to `X-User-ID`.
- `SIUManager` — an SIU manager who triages referrals, opens and closes cases, assigns investigators, adjudicates evidence, files bureau referrals, administers restitution, and manages provider patterns. When `X-User-Role` is `SIUManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `assigned_by_user_id` on an `Assignment`) but does not compare it to any entity's `id`, except where a segregation-of-duties rule compares it to another user's identifier.
- `SIUInvestigator` — a field investigator who logs evidence, schedules and conducts examinations under oath, submits cases for decision, and logs training. When `X-User-Role` is `SIUInvestigator`, `X-User-ID` is the `id` of the acting `Investigator` resource; ownership checks on any resource that references an investigator (for example, `submitted_by_investigator_id` on an evidence item, or `investigator_id` on an assignment) compare that field to `X-User-ID`.
- `SIUComplianceOfficer` — a compliance officer who owns regulatory reporting and otherwise has read-only audit visibility. When `X-User-Role` is `SIUComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`.

Read access is broad: all four roles may fetch and list cases, claims, and referrals. Write access is deliberately narrow and is enumerated per endpoint in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order — oldest first.

List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — claims, adjusters, referrals, cases, investigators, assignments, evidence, EUO sessions, bureau referrals, provider patterns, restitution ledgers, recovery payments, training records, and regulatory reports — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it is refreshed on every mutation.
- `version` (integer): a system-managed counter that increments by one on every mutation to the resource. It is the basis for the optimistic concurrency control described in §2.8.

Because these fields are universal, any mutation described in §3 — including automatic, system-driven ones such as status propagation — refreshes `updated_at` and increments `version` on each resource it touches.

### 2.5. Nested Resource Retrieval and Reference Resolution

Requests that target nested resources are validated left to right along the path. Each path identifier — `claimId`, `adjusterId`, `referralId`, `caseId`, `investigatorId`, `recordId`, `assignmentId`, `evidenceId`, `euoId`, `patternId`, `ledgerId`, `paymentId`, or `reportId` — is resolved in the order it appears, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve. A request aimed at evidence beneath a non-existent case therefore fails on the case before the evidence is ever looked up.

Identifiers supplied in the request body rather than the path are checked separately. When a payload references another resource — for example `claim_id` on a referral, `adjuster_id` on a claim, `investigator_id` on an assignment, `duplicate_of_referral_id` on a duplicate linkage, or `parent_pattern_id` on a pattern merge — and that reference does not resolve, the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 404).

### 2.6. Order of Validation

Every request is evaluated against an ordered sequence of checks. When several checks would fail on the same request, the response carries the error produced by the earliest check in the sequence — later failures are masked by earlier ones. The order is:

1. Authentication — missing or malformed `X-User-ID` or `X-User-Role` yields `ERR_UNAUTHENTICATED`.
2. Authorization — a role not permitted on the endpoint yields `ERR_UNAUTHORIZED`.
3. Path existence — the first unresolvable path identifier yields `ERR_NOT_FOUND`.
4. Body references — an unresolvable foreign key in the payload yields `ERR_FK_NOT_FOUND`.
5. Target state — a failing state-machine precondition on the addressed resource yields `ERR_INVALID_STATE`. The claim-guard on referral acceptance (`ERR_CLAIM_ALREADY_UNDER_SIU`) is evaluated with this state-check group.
6. Cross-entity state — a guard that depends on the parent case's status (for example, admitting evidence while the case is frozen for an examination) yields `ERR_CASE_NOT_IN_REQUIRED_STATE`.
7. Business, temporal, fiscal, and constraint checks, in this relative order: segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); investigator eligibility (`ERR_INVESTIGATOR_INELIGIBLE`); EUO notice window (`ERR_EUO_NOTICE_WINDOW_VIOLATION`); EUO temporal conflict (`ERR_EUO_TEMPORAL_CONFLICT`); payment-delay window (`ERR_DELAY_WINDOW_EXCEEDED`); duplicate open case (`ERR_CASE_ALREADY_OPEN`); EUO-not-required (`ERR_EUO_NOT_REQUIRED`); materiality-amount consistency (`ERR_MATERIALITY_AMOUNT_MISMATCH`); duplicate-link integrity (`ERR_DUPLICATE_LINK_INVALID`); pattern-merge integrity (`ERR_PATTERN_MERGE_INVALID`); recovery-exceeds-outstanding (`ERR_RECOVERY_EXCEEDS_OUTSTANDING`); restitution-target validity (`ERR_RESTITUTION_TARGET_INVALID`); training window (`ERR_TRAINING_WINDOW_INVALID`); report period (`ERR_REPORT_PERIOD_INVALID`).
8. Stale version — an optimistic-concurrency mismatch yields `ERR_STALE_VERSION`.
9. Bureau deadline enforcement — a strict-mode filing past the deadline yields `ERR_BUREAU_DEADLINE_PASSED`; this check runs last.

Structurally malformed requests — a missing required field, a wrong-typed value, or an enum value outside its allowed set — are rejected with `ERR_INVALID_REQUEST` (HTTP 400) as part of request parsing, before any business-rule evaluation.

Two worked examples make the ordering concrete. An evidence-admission request whose evidence is in the wrong state and whose `expected_case_version` is stale is rejected with `ERR_INVALID_STATE`, because the state check outranks the version check; had the state been valid but the manager the same user who logged the evidence, `ERR_SEGREGATION_OF_DUTIES` would surface instead of the stale-version error. An EUO scheduling request whose window overlaps another active session, made against a case whose `euo_required` flag is false, is rejected with `ERR_EUO_TEMPORAL_CONFLICT`, because the temporal check outranks the requirement check.

### 2.7. Segregation of Duties

Investigations carry legal weight, so the system enforces separation between the person who performs a step and the person who verifies it. Three enforcement points exist, each rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422) when violated:

- A manager may not admit an evidence item that they themselves logged; the admission request's `X-User-ID` must differ from the evidence's `submitted_by_investigator_id`.
- A manager may not close a case on which they are the assigned investigator; the closure request's `X-User-ID` must differ from the case's assigned investigator.
- A manager may not record a bureau acknowledgement on a referral they filed; the acknowledgement request's `X-User-ID` must differ from the filing manager's identifier.

For audit, every assignment records the assigning manager's header value in `assigned_by_user_id`, so the chain of custody over case ownership is reconstructable after the fact.

### 2.8. Optimistic Concurrency Control

Four write operations are guarded by optimistic concurrency control. Each requires a non-optional field carrying the version of the parent aggregate that the client last observed; if that value does not match the parent resource's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated.

- Assigning an investigator to a case requires `expected_case_version`, compared against the case's current `version`.
- Admitting evidence requires `expected_case_version`, compared against the case's current `version`.
- Filing a bureau referral requires `expected_referral_version`, compared against the referral's current `version`.
- Clearing a recovery payment requires `expected_ledger_version`, compared against the ledger's current `version`.

Endpoints not named above do not accept a version field. Because both assignment creation and evidence admission increment the case's `version` (§3.3, §3.4), a client holding a previously observed version must re-read the case before retrying; the same discipline applies to bureau filings and payment clears, which increment the referral's and the ledger's `version` respectively.

### 2.9. Monetary Values, Scores, and Precision

All monetary amounts are integers denominated in cents — `claimed_amount_cents`, `paid_amount_cents`, `fraud_amount_cents`, `substantiated_fraud_cents`, `target_amount_cents`, `recovered_amount_cents`, `outstanding_amount_cents`, `amount_cents`, and `total_restitution_recovered_cents`. Integer-cent arithmetic is exact, so no rounding ever applies to money, and derived balances are never permitted to drift below zero.

Suspicion and pattern scores are integers as well. The single place rounding occurs is the high-value multiplier in the referral score: after multiplication by 1.25, the result is rounded half-up to a whole number. The provider pattern score is capped at 100.

Deadline and window computations operate on timestamps at second precision, and one calendar day of any statutory window means exactly 86,400 seconds.

### 2.10. The Logical Clock and Statutory Time Discipline

Every occurrence of "now" in this document refers to the server's logical clock, never the host wall clock. The logical clock starts at `2026-08-01T00:00:00Z` before it has ever been set, and it is deterministic: it never falls back to wall-clock time. An administrative clock-setting capability — restricted to `SIUManager` and `SIUComplianceOfficer` — advances the logical clock to a supplied `to_iso8601` instant and answers with the resulting `now_iso8601`.

Boundary inclusivity is uniform across the statute-style windows: a bureau referral filed exactly at its deadline is on time; a payment delay ending exactly at the state cap is permitted; an EUO notice sent exactly the statutory minimum number of days before the scheduled start satisfies the window. Violations begin strictly beyond the boundary.

### 2.11. Cross-Entity Status Propagation

The case is the investigative hub, and events on it propagate outward automatically. Accepting a referral places its claim under review; closing a case denies or releases the claim and completes the active assignment; filing a bureau referral advances the case itself. Propagation also runs upward from children: clearing a recovery payment updates its ledger's totals and status, admitting substantive evidence updates the case's substantiated total, and terminating an assignment demotes a case that was under active investigation. Each of these automatic reconciliations is a real mutation on the affected resource — it refreshes `updated_at` and increments `version` — so observers holding an optimistic-concurrency token see it advance.

## 3. Business Logic & Workflows

### 3.1. Claims, Adjusters, and Payment Coordination

Work begins with people and claims. A manager registers an adjuster with `full_name`, a unique `email`, and the `state_licenses` array listing the two-letter state codes in which the adjuster is licensed; the `active` flag defaults to true while the adjuster remains employed. An adjuster then registers a claim by supplying the insured's `policy_number`, the two-letter `state_code` that will govern the claim's bureau and delay rules, the owning `adjuster_id`, and the total `claimed_amount_cents`. A new claim starts in `PENDING` with `paid_amount_cents` at zero and `payment_hold_reason` unset.

From `PENDING`, a claim normally travels one of two roads. The adjuster may mark it paid, which is permitted only while the claim is still `PENDING` and no non-terminal SIU case exists for it — a claim under active investigation cannot be paid. Attempting payment against a claim that is already `UNDER_SIU_REVIEW` or `PAYMENT_DELAYED` is rejected with `ERR_INVALID_STATE`; attempting it while a non-terminal case exists for the claim is rejected with `ERR_CASE_NOT_IN_REQUIRED_STATE`. A successful payment moves the claim to `PAID` and sets `paid_amount_cents` equal to `claimed_amount_cents`, since payouts increment the paid total only at that transition. Alternatively, the adjuster may close the claim without payment, moving it from `PENDING` to `CLOSED`. `DENIED`, `PAID`, and `CLOSED` are terminal.

Once a claim is under SIU review, payment coordination becomes a statutory instrument. An adjuster may delay payment, moving the claim from `UNDER_SIU_REVIEW` to `PAYMENT_DELAYED`, by supplying a `delay_until` timestamp and a `reason`. Delay is permitted only while the claim's case is in `UNDER_INVESTIGATION`, `EUO_PENDING`, or `DECISION_PENDING` — otherwise `ERR_CASE_NOT_IN_REQUIRED_STATE` — and the requested `delay_until` must not exceed now plus the claim state's statutory cap: 30 days for California and New York, 90 days for Florida, 60 days for New Jersey, 45 days for Texas, and 30 days for every other state. A `delay_until` exactly at the cap is allowed; anything later is rejected with `ERR_DELAY_WINDOW_EXCEEDED`. When the investigation no longer justifies the hold, the adjuster releases the delay, returning the claim from `PAYMENT_DELAYED` to `UNDER_SIU_REVIEW`.

Claims may be listed with optional `status`, `state_code`, and `adjuster_id` filters, and each claim exposes nested lists of its cases and its referrals.

### 3.2. Red-Flag Referrals: Intake, Scoring, and Triage

Suspicion enters the system as a red-flag referral. An adjuster or an investigator submits one with the flagged `claim_id`, a `submitted_by_role` of `ADJUSTER`, `PROVIDER`, `EXTERNAL_TIP`, or `AUTOMATED_RULE`, an array of `red_flag_codes`, and a free-text `narrative`. The referral is born in `SUBMITTED`, and the server immediately computes a provisional `suspicion_score` and `score_band`.

The score is a weighted sum. Each code in `red_flag_codes` contributes a fixed weight: `PRIOR_FRAUD_CONVICTION` adds 35, `DUPLICATE_CLAIM_CROSS_INSURER` adds 30, `PROVIDER_ON_WATCHLIST` adds 28, `STAGED_ACCIDENT_PATTERN` adds 25, `PHANTOM_TREATMENT` adds 22, `INFLATED_BILLING` adds 20, `IDENTITY_MISMATCH` adds 18, `POST_POLICY_BIND_CLAIM` adds 15, `EXCESSIVE_TREATMENT_FREQUENCY` adds 14, and `UNWITNESSED_LOSS` adds 12. When three or more codes are present, a combination bonus of 15 points is added on top of the summed weights. Finally, when the flagged claim's `claimed_amount_cents` is at least 25,000,000 cents — a quarter of a million dollars — the running score is multiplied by 1.25 and rounded half-up to a whole number. The `score_band` is then read from the final score: below 20 is `LOW`, 20 up to but not including 40 is `MEDIUM`, 40 up to but not including 70 is `HIGH`, and 70 or more is `CRITICAL`.

A manager triages a `SUBMITTED` referral, moving it to `TRIAGED` and recomputing the score and band. During triage the manager may pass `modifier_overrides`, a map from red-flag code to replacement weight; for that recompute only, any code named in the map contributes the supplied weight instead of its standard weight, so the triage-adjusted score can differ from the provisional intake score even for an identical list of codes.

From `TRIAGED`, the manager disposes of the referral in one of three ways. Accepting it requires the claim still be `PENDING` — a claim already under review or beyond is rejected with `ERR_CLAIM_ALREADY_UNDER_SIU` — and requires that no non-terminal case already exist for the claim, since at most one open investigation per claim is allowed; a violation is rejected with `ERR_CASE_ALREADY_OPEN`. Acceptance creates a new SIU case in `INTAKE`, stamped with `opened_by_referral_id` pointing back to the referral, moves the referral to `ACCEPTED`, and shifts the claim from `PENDING` to `UNDER_SIU_REVIEW` with `payment_hold_reason` set to `SIU_INVESTIGATION`. Declining the referral moves it to `DECLINED` and requires a non-empty `decline_reason`; a missing or empty reason is a malformed request rejected with `ERR_INVALID_REQUEST`. Linking the referral as a duplicate moves it to `DUPLICATE_LINKED` and requires `duplicate_of_referral_id`: the target must resolve (else `ERR_FK_NOT_FOUND`), must itself be an `ACCEPTED` referral, and must flag the same claim — otherwise `ERR_DUPLICATE_LINK_INVALID`. `ACCEPTED`, `DECLINED`, and `DUPLICATE_LINKED` are all terminal.

Referrals can be listed with `status`, `claim_id`, `score_band`, and `duplicate_of_referral_id` filters.

### 3.3. Case Opening and Investigator Assignment

A case created by referral acceptance sits in `INTAKE` until a manager formally opens it. The case carries a server-minted `case_number` in the format SIU-YYYY-NNNNNN, a `priority` band inherited from the referral's `score_band` (`LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`), and an `assigned_investigator_id` that remains null until the first assignment. Opening requires the originating referral to be `ACCEPTED` and no other non-terminal case to exist for the same claim; a violation of either precondition is rejected with `ERR_INVALID_STATE`. At open, the server snapshots `suspicion_score` from the referral — a cached copy that is never recomputed afterwards — sets `investigation_deadline_at` to 45 days after the open transition, computes the `euo_required` flag (true when the snapshotted score meets or exceeds the EUO score threshold; the flag can also turn true later if evidence admitted during the investigation raises the case above that threshold), confirms the claim in `UNDER_SIU_REVIEW` with the `SIU_INVESTIGATION` hold, and increments the case's `version`. The case is now `OPEN`.

Investigators are registered by a manager with `full_name`, a unique `email`, a unique `badge_number`, the `state_certifications` array of states they may operate in, and a `max_active_cases` capacity ceiling that must be at least 1 and at most 20 — a value outside that range is rejected as `ERR_INVALID_REQUEST`. A new investigator starts `ACTIVE` with `active_case_count` at zero and `training_current_through` null. Suspension (`SUSPENDED`) records a `reason` and leaves existing assignments untouched, but a suspended or `TERMINATED` investigator fails every eligibility check below; reinstatement returns them to `ACTIVE`.

Assignment is the moment investigation actually begins, and it is concurrency-guarded: the request carries `investigator_id` and `expected_case_version`, and if the case's `version` has advanced since the client last read it — because another manager has just reassigned the case, for instance — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a case state it never observed. Eligibility is checked before the version, per §2.6: the investigator must be `ACTIVE`, their `state_certifications` must contain the claim's `state_code`, and their `active_case_count` must be below `max_active_cases`; any failure is `ERR_INVESTIGATOR_INELIGIBLE`. Assignment creation is valid only while the case is `OPEN` or `UNDER_INVESTIGATION`; against any other case status it is rejected with `ERR_INVALID_STATE`.

The first `ACTIVE` assignment on a case moves it from `OPEN` to `UNDER_INVESTIGATION`, sets `assigned_investigator_id` to the investigator, raises that investigator's `active_case_count` by one, and increments the case's `version`. When a case already has an `ACTIVE` assignment, posting a new one automatically flips the existing assignment to `REASSIGNED`, decrements the previous investigator's `active_case_count` by one, activates the new assignment, and raises the new investigator's count by one — the handoff is atomic, and each assignment records its `assigned_at` timestamp. A manager may also terminate an active assignment outright, providing a `reason`, so long as the case is not in a terminal status; termination moves the assignment to `TERMINATED`, decrements the investigator's count, clears the case's `assigned_investigator_id` to null, and — when the case was `UNDER_INVESTIGATION` — demotes it back to `OPEN`. `REASSIGNED`, `COMPLETED`, and `TERMINATED` are terminal for an assignment; `COMPLETED` is reached only automatically, when the case itself closes (§3.6), which also stamps `completed_at`.

Cases are listed with `status`, `state_code`, `assigned_investigator_id`, `priority`, `claim_id`, and `opened_by_referral_id` filters; assignments are listed per case or per investigator, and globally with `case_id`, `investigator_id`, and `status` filters; investigators are listed with an optional `status` filter.

### 3.4. Evidence Gathering and Admissibility

Evidence is the substance of an investigation. An investigator logs an item against a case by supplying its `evidence_type` — `STATEMENT`, `SURVEILLANCE`, `RECORDS`, `SOCIAL_MEDIA`, or `PRIOR_CLAIM_HISTORY` — the `collected_at` timestamp (which must not lie in the future; a future collection time is rejected as `ERR_INVALID_REQUEST`), the chain-of-custody `custodian` name, a `materiality` of `IMMATERIAL`, `SUPPORTING`, or `SUBSTANTIVE`, and the `fraud_amount_cents` attributable to the item, which is zero for non-monetary evidence. Materiality and amount must agree: a `SUBSTANTIVE` item with a zero amount, or an `IMMATERIAL` item with a positive amount, is rejected with `ERR_MATERIALITY_AMOUNT_MISMATCH`. The new item starts `LOGGED`, stamped with its parent `case_id` and the logging investigator's `submitted_by_investigator_id` taken from the request header.

Review follows a deliberate loop. The investigator submits an item for review, moving it from `LOGGED` to `UNDER_REVIEW`. A manager then adjudicates it: admitting moves it to `ADMITTED`, excluding moves it to `EXCLUDED` with a `reason`, and returning it for more work moves it back to `LOGGED` with a `note` — the review loop is cyclic, and an item may pass through `UNDER_REVIEW` more than once.

Admission is the most heavily guarded write in the system. The manager must not be the investigator who logged the item, per §2.7 (`ERR_SEGREGATION_OF_DUTIES`); the case must not be `EUO_PENDING`, because admissions are frozen while an examination is pending (`ERR_CASE_NOT_IN_REQUIRED_STATE`); and the request must carry `expected_case_version` matching the case's current `version`, else `ERR_STALE_VERSION`. On admission, if the item's `materiality` is `SUBSTANTIVE`, its `fraud_amount_cents` is added to the case's `substantiated_fraud_cents`; the case's `bureau_referral_required` flag is then recomputed, and the case's `version` increments by one. That running total is exactly the sum of `fraud_amount_cents` over the case's evidence that is both `ADMITTED` and `SUBSTANTIVE`: admissions while the case is open or under investigation update the running figure without gating anything, and the figure only becomes binding at closure, where it locks the restitution target. The recomputed bureau flag is true when the total reaches 500,000 cents (five thousand dollars), or whenever the total is merely positive and the claim's state is California, Florida, New York, or New Jersey — states with mandatory-referral statutes.

Sealing is the epilogue: once — and only once — the case is `CLOSED_SUBSTANTIATED`, a manager may seal an `ADMITTED` item, stamping `sealed_at` and moving it to `SEALED`. Sealed evidence is immutable and is excluded from any future recomputation of `substantiated_fraud_cents` — in effect its amount is subtracted from the total. `ADMITTED`, `EXCLUDED`, and `SEALED` are terminal for evidence.

Evidence is listed per case with `status` and `evidence_type` filters, and globally with `case_id`, `submitted_by_investigator_id`, `status`, and `evidence_type` filters.

### 3.5. Examinations Under Oath

When a case's `euo_required` flag is true, the investigator schedules an examination under oath, supplying `scheduled_start_at`, `scheduled_end_at`, a physical or virtual `location`, and the `insured_attendee_name` of the insured required to appear. Scheduling is possible only while the case is `UNDER_INVESTIGATION`, and only when at least one of the case's evidence items is already `ADMITTED` — the examination needs admitted substance to examine. If the flag is false, scheduling is rejected with `ERR_EUO_NOT_REQUIRED`; if the state or evidence preconditions fail, with `ERR_INVALID_STATE`. The window itself must be coherent: the start must lie in the future (a past start is `ERR_INVALID_REQUEST`), the end must be later than the start, and the window must not overlap another active session for the same case — violations are `ERR_EUO_TEMPORAL_CONFLICT`. The first session on a case moves it from `UNDER_INVESTIGATION` to `EUO_PENDING`, and while the case is in that status no evidence may transition to `ADMITTED`, preserving the testimony context until a session concludes or the insured fails to appear.

Notice is statutory. The investigator dispatches notice, moving the session from `SCHEDULED` to `NOTICE_SENT` and stamping `notice_sent_at`, only when at least 10 full days remain before the scheduled start; inside that window the dispatch is rejected with `ERR_EUO_NOTICE_WINDOW_VIOLATION`.

From `NOTICE_SENT` a session resolves in one of two ways. Once now has reached the scheduled start, the investigator may mark it conducted: the session moves to `CONDUCTED`, `conducted_at` and `transcript_received` are set (the court reporter's transcript is treated as received on completion), and the case returns from `EUO_PENDING` to `UNDER_INVESTIGATION`, unfreezing admissions. Alternatively, once now has passed the scheduled end, the investigator may record a no-show: the session moves to `NO_SHOW`, its `no_show_count` increments by one, and the case likewise returns to `UNDER_INVESTIGATION`. When a session's `no_show_count` reaches two, the claim's `payment_hold_reason` becomes `EUO_NONAPPEARANCE` and the claim itself moves to `PAYMENT_DELAYED` — statutory cover for the continued hold.

Two administrative paths exist while the session is still ahead of its start. The investigator may reschedule a `SCHEDULED` session before its start, which creates a brand-new session with the new `scheduled_start_at`, `scheduled_end_at`, and `location` and marks the old one `RESCHEDULED`, a terminal disposition for the superseded record. A manager may instead cancel a `NOTICE_SENT` session before its start with a `reason`, moving it to `CANCELLED` and returning the case to `UNDER_INVESTIGATION`. `CONDUCTED`, `NO_SHOW`, and `CANCELLED` are terminal.

Sessions are listed per case or globally, with `status` and `case_id` filters available.

### 3.6. Decision, Closure, and Fraud-Bureau Referral

With the investigation complete, the investigator submits the case for decision, moving it from `UNDER_INVESTIGATION` to `DECISION_PENDING`. Submission requires at least one `ADMITTED` evidence item; additionally, when `euo_required` is true, at least one session must have reached `CONDUCTED` or accumulated a `no_show_count` of two or more — the examination obligation must be discharged or exhausted first. An attempt that fails either precondition is rejected with `ERR_INVALID_STATE`. At submission the server sets `decision_due_at` to 30 days out, the window in which the manager must record a decision.

Closure is a manager's act and takes a `closed_reason` of `SUBSTANTIATED`, `UNSUBSTANTIATED`, `INSUFFICIENT_EVIDENCE`, or `WITHDRAWN_BY_ADJUSTER`. Whichever path is taken, closure enforces segregation of duties: the closing manager must not be the same user as the case's assigned investigator, on pain of `ERR_SEGREGATION_OF_DUTIES`. Closure from any status other than `DECISION_PENDING` or — for the insufficient-evidence path — `OPEN` is rejected with `ERR_INVALID_STATE`.

A substantiated closure (`DECISION_PENDING` → `CLOSED_SUBSTANTIATED`) additionally requires `substantiated_fraud_cents` to be greater than zero. Its consequences fan out across the system: the claim moves from `UNDER_SIU_REVIEW` or `PAYMENT_DELAYED` to `DENIED` with `payment_hold_reason` set to `FRAUD_CONFIRMED`; a restitution ledger is auto-created in `OPEN` with `target_amount_cents` locked to the substantiated total at closure; when `bureau_referral_required` is true, a bureau referral is auto-created in `DRAFT`, carrying the claim's `state_code` and a `deadline_at` computed from the closure timestamp; and each provider pattern associated with evidence on the case gains the case in its `linked_case_ids` and has its `pattern_score` recomputed (§3.8). An unsubstantiated closure (`CLOSED_UNSUBSTANTIATED`) instead releases the claim back to `PENDING` and clears `payment_hold_reason` to null, as does an insufficient-evidence closure (`CLOSED_INSUFFICIENT`); the insufficient-evidence path is also available directly from `OPEN`, but only while the case has no `ADMITTED` evidence. On every terminal closure, the case's active assignment is completed automatically: the assignment moves to `COMPLETED`, its `completed_at` is stamped, and the investigator's `active_case_count` drops by one. `CLOSED_SUBSTANTIATED`, `CLOSED_UNSUBSTANTIATED`, `CLOSED_INSUFFICIENT`, and — after a bureau filing — `REFERRED_TO_BUREAU` are the case's terminal states.

The bureau referral lifecycle is short but deadline-bound. The filing window depends on the claim's state: 30 days for California, New York, and Texas; 60 days for Florida; 45 days for New Jersey; and 45 days for every other state. `deadline_at` is the closure timestamp plus that many 86,400-second days. Filing requires the case to be `CLOSED_SUBSTANTIATED` (otherwise `ERR_CASE_NOT_IN_REQUIRED_STATE`) and the referral to be `DRAFT` (otherwise `ERR_INVALID_STATE`), and it is concurrency-guarded by `expected_referral_version` against the referral's current `version` (`ERR_STALE_VERSION`). Filing stamps `filed_at` and increments the referral's `version`; a filing exactly at `deadline_at` is on time, and the `late_filing` flag is set only when `filed_at` is strictly later. A late referral lands in `LATE_FILED` and an on-time one in `FILED`, but either way the case advances from `CLOSED_SUBSTANTIATED` to `REFERRED_TO_BUREAU` — lateness never blocks the filing. By default lateness is merely flagged; a manager may pass `enforce_bureau_deadline` as true in the filing body to request strict mode, under which a filing attempted after the deadline is instead rejected with `ERR_BUREAU_DEADLINE_PASSED` — the last check evaluated, after even the version check. After filing, a manager records the bureau's acknowledgement, moving `FILED` to `ACKNOWLEDGED` and stamping `ack_received_at` — an act segregated from the filing itself (§2.7) — or records the bureau's rejection with a `reason`, moving `FILED` to `REJECTED_BY_BUREAU`.

Bureau referrals are listed per case, or globally with `case_id`, `status`, and `state_code` filters.

### 3.7. Restitution Ledgers and Recovery Payments

Restitution is tracked on a ledger per case. Most ledgers arrive automatically at substantiated closure (§3.6), but a manager may also create one manually against a case by supplying `target_amount_cents` — the court-ordered or agreed restitution total. The target must be greater than zero and no more than the claim's `claimed_amount_cents`; otherwise the creation is rejected with `ERR_RESTITUTION_TARGET_INVALID`. A new ledger starts `OPEN` with `recovered_amount_cents` at zero and `outstanding_amount_cents` equal to the target; the outstanding balance is always the target minus the recovered total and is never negative.

Recovery arrives as payments recorded by a manager with an `amount_cents` greater than zero, a `received_at` timestamp, and a `method` of `CHECK`, `ACH`, `WIRE`, `WAGE_GARNISHMENT`, or `POLICY_OFFSET`. Each payment carries its parent `ledger_id` and starts `PENDING`. Clearing a payment moves it to `CLEARED` and is guarded two ways: `expected_ledger_version` must match the ledger's current `version` (`ERR_STALE_VERSION`), and the payment's amount must not exceed the ledger's outstanding balance at the moment of clearing (`ERR_RECOVERY_EXCEEDS_OUTSTANDING`). On a successful clear the ledger's `recovered_amount_cents` — the running sum of cleared payments net of reversals — grows by the payment amount, the outstanding balance is recomputed, and the ledger's `version` increments by one. The first cleared payment moves the ledger from `OPEN` to `PARTIALLY_RECOVERED`, and when the outstanding balance reaches zero the ledger moves on to `FULLY_RECOVERED`. A payment that cannot be cleared is returned with a `reason`, moving `PENDING` to `RETURNED`.

Reversal unwinds a cleared payment: the payment moves from `CLEARED` to `REVERSED` with a `reason` and a `reversed_at` timestamp, the ledger's recovered total is reduced by the amount, and a ledger that had reached `FULLY_RECOVERED` falls back to `PARTIALLY_RECOVERED`. Finally, a manager may write off a ledger with a `reason`: from `OPEN` this requires a positive outstanding balance, and from either `OPEN` or `PARTIALLY_RECOVERED` it requires the case to be in a terminal status. `FULLY_RECOVERED` and `WRITTEN_OFF` are terminal for a ledger; `CLEARED`, `RETURNED`, and `REVERSED` are terminal for a payment.

Ledgers are listed per case or globally with `case_id` and `status` filters; payments are listed per ledger or globally with `ledger_id`, `status`, and `method` filters.

### 3.8. Provider Patterns and Organized-Ring Analysis

Fraud is frequently organized, so investigators and managers register provider patterns to cluster suspicious activity. Registration supplies the `provider_npi` National Provider Identifier, the `provider_name`, and a `ring_signature` — a hash of linked attributes such as address, phone, and bank details that ties members of a ring together. A new pattern starts in `MONITORING` with `linked_case_ids` empty, `parent_pattern_id` null, and a `pattern_score` computed over its (initially empty) linkage.

The score rewards breadth and coordination. It starts at twelve points per linked case; reaching at least three linked cases adds a twenty-point ring bonus; linked cases whose claims span at least two distinct states add fifteen more; and each distinct evidence type represented among admitted evidence across the linked cases adds four points. The result is capped at 100. Patterns accumulate links automatically when a case closes substantiated with provider evidence (§3.6), at which point the score is recomputed.

Escalation and resolution are manager decisions. A pattern in `MONITORING` may be escalated to `ESCALATED_TO_NICB` once its `pattern_score` reaches the escalation threshold of 60 — below the threshold the attempt is rejected with `ERR_INVALID_STATE`. It may instead be cleared to `CLEARED` once every linked case is in a terminal status. Or it may be merged into a sibling ring: the manager supplies `parent_pattern_id`, which must resolve (`ERR_FK_NOT_FOUND`), must name a different pattern that is itself still `MONITORING`, and must carry the identical `ring_signature` — otherwise `ERR_PATTERN_MERGE_INVALID`. A successful merge moves the pattern to `MERGED_INTO_RING`, appends its `linked_case_ids` to the parent's list, and recomputes the parent's score over the combined linkage, so merged children count toward the parent's ring. `ESCALATED_TO_NICB`, `CLEARED`, and `MERGED_INTO_RING` are terminal.

Patterns are listed with `escalation_status`, `ring_signature`, and `parent_pattern_id` filters.

### 3.9. Training Records and Regulatory Reporting

Regulators expect SIU staff to stay current. An investigator or a manager logs a training record with a `course_code` such as SIU-ANNUAL-2026, a `completed_at` timestamp, a `valid_until` expiration, and `credit_hours`. The record is rejected with `ERR_TRAINING_WINDOW_INVALID` when `valid_until` is not later than `completed_at` or when `credit_hours` is below 1. Each record carries its `investigator_id`, and logging one recomputes the investigator's `training_current_through` as the latest `valid_until` across their completed records — the currency timestamp consulted when eligibility for high-priority case assignments is reviewed. Records are listed per investigator or globally with `investigator_id` and `course_code` filters, and fetched individually by `recordId`.

Regulatory reporting belongs to the compliance officer. A report is created with an inclusive `period_start_at`, an exclusive `period_end_at`, the `state_code` the report covers, and a `report_type` of `QUARTERLY_SIU_ACTIVITY`, `ANNUAL_ANTI_FRAUD_PLAN`, or `BUREAU_LATE_FILING_SUMMARY`. The period is rejected with `ERR_REPORT_PERIOD_INVALID` when the end is not after the start or lies in the future. A new report is a `DRAFT` with all four metrics at zero: `total_cases_opened`, `total_cases_closed_substantiated`, `total_restitution_recovered_cents`, and `late_bureau_filings`.

Computation runs on demand and fills those four fields from the period and state. `total_cases_opened` counts cases created within the period for claims in the report's state. `total_cases_closed_substantiated` counts cases in `CLOSED_SUBSTANTIATED` whose last update fell within the period. `total_restitution_recovered_cents` sums the amounts of recovery payments in `CLEARED` status received within the period on ledgers belonging to cases whose claims sit in the report's state. `late_bureau_filings` counts bureau referrals with `late_filing` true that were filed within the period for that state. Submitting the report moves it from `DRAFT` to `SUBMITTED` and requires the metrics to have been computed — otherwise `ERR_INVALID_STATE`. The regulator's verdict is then recorded: acceptance moves `SUBMITTED` to `ACCEPTED`, and rejection moves it to `REJECTED_BY_REGULATOR` with a `reason`.

Reports are listed with `status`, `state_code`, and `report_type` filters. For deterministic testing and statutory-window verification, managers and compliance officers also have the logical-clock capability described in §2.10.

## 4. Endpoint Definitions

Endpoints that create a new resource — a claim, an adjuster, a referral, an investigator, a training record, an assignment, an evidence item, an EUO session (including the successor session produced by a reschedule), a provider pattern, a restitution ledger, a recovery payment, or a regulatory report — return `201 Created`. Referral acceptance also returns `201 Created`, because it creates the SIU case it responds with. All other operations, including state transitions on existing resources, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/siu/claims` | Register a new claim | Adjuster |
| GET | `/siu/claims/{claimId}` | Fetch claim | All roles |
| GET | `/siu/claims` | List claims (filterable) | All roles |
| POST | `/siu/claims/{claimId}/pay` | Mark claim paid | Adjuster |
| POST | `/siu/claims/{claimId}/close-claim` | Close claim without payment | Adjuster |
| POST | `/siu/claims/{claimId}/delay-payment` | Adjuster-driven payment delay under SIU coordination | Adjuster |
| POST | `/siu/claims/{claimId}/release-delay` | Release payment delay | Adjuster |
| GET | `/siu/claims/{claimId}/cases` | Cases for a claim | All roles |
| GET | `/siu/claims/{claimId}/referrals` | Referrals for a claim | All roles |
| POST | `/siu/adjusters` | Register adjuster | SIUManager |
| GET | `/siu/adjusters/{adjusterId}` | Fetch adjuster | Adjuster, SIUManager, SIUComplianceOfficer |
| POST | `/siu/referrals` | Submit red-flag referral | Adjuster, SIUInvestigator |
| GET | `/siu/referrals/{referralId}` | Fetch referral | All roles |
| GET | `/siu/referrals` | List referrals (filterable) | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| POST | `/siu/referrals/{referralId}/triage` | Triage referral | SIUManager |
| POST | `/siu/referrals/{referralId}/accept` | Accept referral; creates SIUCase | SIUManager |
| POST | `/siu/referrals/{referralId}/decline` | Decline referral | SIUManager |
| POST | `/siu/referrals/{referralId}/link-duplicate` | Link as duplicate | SIUManager |
| GET | `/siu/cases/{caseId}` | Fetch case | All roles |
| GET | `/siu/cases` | List cases | All roles |
| POST | `/siu/cases/{caseId}/open` | Open an INTAKE case | SIUManager |
| POST | `/siu/cases/{caseId}/submit-for-decision` | Investigator submits case for decision | SIUInvestigator |
| POST | `/siu/cases/{caseId}/close` | Close case | SIUManager |
| POST | `/siu/investigators` | Register investigator | SIUManager |
| GET | `/siu/investigators/{investigatorId}` | Fetch investigator | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| GET | `/siu/investigators` | List investigators | SIUManager, SIUComplianceOfficer |
| GET | `/siu/investigators/{investigatorId}/assignments` | Assignments for investigator | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| GET | `/siu/investigators/{investigatorId}/training-records` | Training records | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| GET | `/siu/training-records` | List all training records (filterable) | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| GET | `/siu/training-records/{recordId}` | Fetch training record by id | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| POST | `/siu/investigators/{investigatorId}/training-records` | Log training | SIUInvestigator, SIUManager |
| POST | `/siu/investigators/{investigatorId}/suspend` | Suspend investigator | SIUManager |
| POST | `/siu/investigators/{investigatorId}/reinstate` | Reinstate investigator | SIUManager |
| POST | `/siu/cases/{caseId}/assignments` | Assign investigator (OCC on case) | SIUManager |
| GET | `/siu/assignments/{assignmentId}` | Fetch assignment | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| GET | `/siu/cases/{caseId}/assignments` | Assignments for case | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| GET | `/siu/assignments` | List assignments (filterable) | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| POST | `/siu/assignments/{assignmentId}/terminate` | Terminate active assignment | SIUManager |
| POST | `/siu/cases/{caseId}/evidence` | Log evidence | SIUInvestigator |
| GET | `/siu/cases/{caseId}/evidence/{evidenceId}` | Fetch evidence | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| GET | `/siu/cases/{caseId}/evidence` | List evidence for case | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| GET | `/siu/evidence` | List all evidence (filterable) | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| GET | `/siu/evidence/{evidenceId}` | Fetch evidence by id | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| POST | `/siu/cases/{caseId}/evidence/{evidenceId}/submit-review` | Submit for review | SIUInvestigator |
| POST | `/siu/cases/{caseId}/evidence/{evidenceId}/admit` | Admit evidence (OCC on case) | SIUManager |
| POST | `/siu/cases/{caseId}/evidence/{evidenceId}/exclude` | Exclude evidence | SIUManager |
| POST | `/siu/cases/{caseId}/evidence/{evidenceId}/return-for-more-work` | Return evidence to LOGGED | SIUManager |
| POST | `/siu/cases/{caseId}/evidence/{evidenceId}/seal` | Seal admitted evidence post-closure | SIUManager |
| POST | `/siu/cases/{caseId}/euo-sessions` | Schedule EUO | SIUInvestigator |
| GET | `/siu/cases/{caseId}/euo-sessions` | List EUOs for case | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| GET | `/siu/euo-sessions` | List all EUO sessions (filterable) | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| GET | `/siu/euo-sessions/{euoId}` | Fetch EUO session by id | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| GET | `/siu/cases/{caseId}/euo-sessions/{euoId}` | Fetch EUO | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| POST | `/siu/cases/{caseId}/euo-sessions/{euoId}/send-notice` | Send EUO notice | SIUInvestigator |
| POST | `/siu/cases/{caseId}/euo-sessions/{euoId}/conduct` | Mark EUO conducted | SIUInvestigator |
| POST | `/siu/cases/{caseId}/euo-sessions/{euoId}/no-show` | Mark EUO no-show | SIUInvestigator |
| POST | `/siu/cases/{caseId}/euo-sessions/{euoId}/reschedule` | Reschedule EUO (creates new session) | SIUInvestigator |
| POST | `/siu/cases/{caseId}/euo-sessions/{euoId}/cancel` | Cancel EUO | SIUManager |
| GET | `/siu/cases/{caseId}/bureau-referrals` | List bureau referrals for case | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| GET | `/siu/bureau-referrals` | List all bureau referrals (filterable) | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| GET | `/siu/bureau-referrals/{referralId}` | Fetch bureau referral by id | SIUManager, SIUComplianceOfficer |
| GET | `/siu/cases/{caseId}/bureau-referrals/{referralId}` | Fetch bureau referral | SIUManager, SIUComplianceOfficer |
| POST | `/siu/cases/{caseId}/bureau-referrals/{referralId}/file` | File bureau referral (OCC on referral) | SIUManager |
| POST | `/siu/cases/{caseId}/bureau-referrals/{referralId}/acknowledge` | Record bureau ack | SIUManager |
| POST | `/siu/cases/{caseId}/bureau-referrals/{referralId}/reject` | Record bureau rejection | SIUManager |
| POST | `/siu/provider-patterns` | Register provider pattern | SIUInvestigator, SIUManager |
| GET | `/siu/provider-patterns/{patternId}` | Fetch pattern | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| GET | `/siu/provider-patterns` | List patterns | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| POST | `/siu/provider-patterns/{patternId}/escalate` | Escalate to NICB | SIUManager |
| POST | `/siu/provider-patterns/{patternId}/clear` | Clear pattern | SIUManager |
| POST | `/siu/provider-patterns/{patternId}/merge` | Merge into another pattern | SIUManager |
| POST | `/siu/cases/{caseId}/restitution-ledgers` | Manually create restitution ledger (when not auto-created) | SIUManager |
| GET | `/siu/cases/{caseId}/restitution-ledgers` | List ledgers for case | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| GET | `/siu/ledgers` | List all ledgers (filterable) | SIUManager, SIUInvestigator, SIUComplianceOfficer |
| GET | `/siu/ledgers/{ledgerId}` | Fetch ledger | SIUManager, SIUComplianceOfficer |
| GET | `/siu/ledgers/{ledgerId}/payments` | List payments | SIUManager, SIUComplianceOfficer |
| GET | `/siu/recovery-payments` | List all recovery payments (filterable) | SIUManager, SIUComplianceOfficer |
| GET | `/siu/recovery-payments/{paymentId}` | Fetch recovery payment by id | SIUManager, SIUComplianceOfficer |
| POST | `/siu/ledgers/{ledgerId}/payments` | Record recovery payment | SIUManager |
| POST | `/siu/ledgers/{ledgerId}/payments/{paymentId}/clear` | Clear payment (OCC on ledger) | SIUManager |
| POST | `/siu/ledgers/{ledgerId}/payments/{paymentId}/return` | Return payment | SIUManager |
| POST | `/siu/ledgers/{ledgerId}/payments/{paymentId}/reverse` | Reverse cleared payment | SIUManager |
| POST | `/siu/cases/{caseId}/restitution-ledgers/{ledgerId}/write-off` | Write off outstanding | SIUManager |
| POST | `/siu/reports` | Create regulatory report (DRAFT) | SIUComplianceOfficer |
| GET | `/siu/reports/{reportId}` | Fetch report | SIUManager, SIUComplianceOfficer |
| GET | `/siu/reports` | List reports | SIUManager, SIUComplianceOfficer |
| POST | `/siu/reports/{reportId}/compute` | Compute metrics | SIUComplianceOfficer |
| POST | `/siu/reports/{reportId}/submit` | Submit report | SIUComplianceOfficer |
| POST | `/siu/reports/{reportId}/accept` | Record regulator acceptance | SIUComplianceOfficer |
| POST | `/siu/reports/{reportId}/reject` | Record regulator rejection | SIUComplianceOfficer |
| POST | `/siu/_clock/set_current_utc` | Set logical clock (default: 2026-08-01T00:00:00Z before any set) | SIUManager, SIUComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_FK_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CASE_NOT_IN_REQUIRED_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_INVESTIGATOR_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_EUO_NOTICE_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_EUO_TEMPORAL_CONFLICT` | 422 Unprocessable Entity |
| `ERR_DELAY_WINDOW_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CASE_ALREADY_OPEN` | 409 Conflict |
| `ERR_CLAIM_ALREADY_UNDER_SIU` | 409 Conflict |
| `ERR_EUO_NOT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_MATERIALITY_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_LINK_INVALID` | 422 Unprocessable Entity |
| `ERR_PATTERN_MERGE_INVALID` | 422 Unprocessable Entity |
| `ERR_RECOVERY_EXCEEDS_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_RESTITUTION_TARGET_INVALID` | 422 Unprocessable Entity |
| `ERR_TRAINING_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_REPORT_PERIOD_INVALID` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_BUREAU_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
