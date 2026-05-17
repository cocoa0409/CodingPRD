# ABA Therapy API — Product Requirements Document

## 1. Introduction

Applied Behavior Analysis (ABA) is the dominant evidence-based intervention for children diagnosed with Autism Spectrum Disorder, and clinics that deliver it operate under a peculiar combination of pressures. Each patient's care is shaped first by a diagnostic evaluation performed by a Board Certified Behavior Analyst, then translated into a long-running treatment plan, and finally executed through dozens of weekly therapy sessions — most delivered one-on-one by Registered Behavior Technicians, with periodic BCBA supervision interleaved to satisfy both clinical best practice and payer contracts. Layered on top of this clinical workflow is an insurance reimbursement cycle in which every minute of therapy is converted into 15-minute billing units, packaged into claims, adjudicated by a payer, and either paid or pushed back through an appeal loop.

This API exists to model that entire lifecycle as a single, internally-consistent system. Three concerns run through it. **First**, the system must enforce a strict unit-quota economy: each Authorization grants a finite pool of approved units, and the same hour of therapy must be visible both *provisionally* (the moment a session completes) and *adjudicatedly* (only after the payer pays the containing claim), with the two numbers allowed to diverge whenever a claim is denied or appealed. **Second**, the system must enforce the supervision-ratio invariant at multiple touchpoints — at plan activation, at claim payment, and on demand — because dropping below the contractual minimum has both clinical and financial consequences. **Third**, the system runs on a deterministic logical clock that the test harness advances explicitly, so that the time-gated transitions (an authorization becoming active when its start date arrives, expiring when its end date passes, a treatment plan auto-expiring after one year) are reproducible rather than wall-clock dependent.

The implementer should treat the patient as the unit of aggregation, the authorization as the unit of fiscal capacity, the session as the unit of clinical delivery, the claim as the unit of reimbursement, and the BillingLedgerEntry as the append-only audit trail tying it all together.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` and `X-User-Role`. If either is missing or empty, the response is `ERR_AUTH_REQUIRED` with HTTP 401. If the role string is not one of the four recognised values, the same code applies. If the role is recognised but is not in the RBAC matrix for the requested endpoint, the response is `ERR_FORBIDDEN` with HTTP 403.

The system distinguishes four roles, spelled exactly as follows:

- **`BCBA`** — the Board Certified Behavior Analyst. Performs diagnostic evaluations, drafts and activates treatment plans, supervises RBTs, disputes and resolves sessions, and may run any session type. When `X-User-Role` is `BCBA`, `X-User-ID` is the `id` of the acting `Therapist` row whose `credential` equals `BCBA`; ownership checks on any resource that references a Therapist compare the resource's foreign-key field (for example, an evaluation's `evaluator_therapist_id` or a session's `therapist_id`) to `X-User-ID`.
- **`RBT`** — the Registered Behavior Technician. Runs direct-therapy sessions assigned to them but cannot manage plans or claims. When `X-User-Role` is `RBT`, `X-User-ID` is the `id` of the acting `Therapist` row whose `credential` equals `RBT`; the same ownership rule applies — a session's `therapist_id` is compared against `X-User-ID` whenever the RBT acts on it.
- **`ClinicAdmin`** — the clinic-side operations user. Creates clinics, patients, therapists, authorizations and claims; submits and appeals claims; cancels sessions; advances the logical clock. When `X-User-Role` is `ClinicAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but never compares it to any entity's `id`.
- **`PayerAdmin`** — the insurance payer-side operator. Approves and denies authorizations, adjudicates claims, and pays or denies adjudicated claims. When `X-User-Role` is `PayerAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is never compared to any entity's `id`.

When a `BCBA` or `RBT` attempts a therapist-specific transition on a session or evaluation whose therapist-of-record is a different therapist, the response is `ERR_NOT_THERAPIST_OF_RECORD` with HTTP 403. Ownership therefore precedes state checks but follows generic role-permission checks.

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

All list endpoints accept `limit` and `offset` query parameters. The default `limit` is 10; the minimum accepted value is 1 and the maximum accepted value is 100. The default `offset` is 0; values less than 0 are rejected. When either is violated, the response is `ERR_PAGINATION_PARAMS` with HTTP 422. List results are sorted by `created_at` in ascending order. The `meta` object for list responses exposes `limit`, `offset`, `total_count` (the unfiltered count after `status`, `session_type`, or other filters are applied but before paging), and `has_more` (true when more rows remain after the current page).

### 2.4. Common Resource Properties

Every resource carries an `id`, which is a server-minted UUID. The `id` has no type prefix — it is the bare canonical UUID string. Resources also carry `created_at`, an ISO 8601 UTC timestamp with three fractional digits, captured at the moment of creation. Most entities — `Clinic`, `Patient`, `DiagnosticEvaluation`, `TreatmentPlan`, `Authorization`, `Therapist`, `TherapySession`, and `InsuranceClaim` — additionally carry `updated_at` (also an ISO 8601 UTC timestamp with three fractional digits, refreshed on every state-changing mutation) and `version` (a non-negative integer initialised to 1 at creation and incremented by exactly one on each state-changing mutation). The append-only `BillingLedgerEntry` is the single exception: each entry carries only `id` and `created_at` — it has no `updated_at` and no `version`, because ledger rows are immutable once written.

### 2.5. The Deterministic Clinic Clock

The system does not consult wall-clock time. Each `Clinic` carries a logical clock field, `now_ts`, that advances only through the test-driver capability that posts a forward delta in seconds against a particular clinic. On clinic creation, `now_ts` is set to the deterministic epoch `2025-01-01T00:00:00.000Z`. Every time-gated transition — an Authorization moving from `APPROVED` to `ACTIVE` when its `effective_start` arrives, an Authorization moving from `ACTIVE` to `EXPIRED` when its `effective_end` is crossed, a `TreatmentPlan` moving from `ACTIVE` to `EXPIRED` after one year of activation — fires only when the clock-advance capability advances `now_ts` past the relevant threshold. The clock-advance body carries the `clinic_id` and the `seconds` field; `seconds` must be a strictly positive integer.

### 2.6. Optimistic Concurrency Control

Mutating endpoints accept an optional `version` field in the request body. When supplied, it is compared against the current resource version; a mismatch is rejected with `ERR_VERSION_CONFLICT` and HTTP 409. When the `version` field is omitted from the body, the version check is skipped — the request proceeds without an optimistic-concurrency precondition. Every successful state-changing mutation increments `version` by one and refreshes `updated_at` to the clinic's current `now_ts`.

### 2.7. Path Resolution and Existence Checks

Nested path parameters are validated strictly left to right. For a path such as `/patients/{patient_id}/sessions`, the `patient_id` segment is resolved before any later segment. The first missing segment along the path causes the request to fail with `ERR_NOT_FOUND` and HTTP 404 — later segments are not consulted. After the path is fully resolved, foreign-key fields in the request body (for example `treatment_plan_id`, `authorization_id`, the elements of `session_ids`, `evaluator_therapist_id`) are then resolved; any unresolved body FK yields the same `ERR_NOT_FOUND` outcome with HTTP 404.

### 2.8. Validation Precedence

When more than one rule could reject a request, validations are evaluated in a fixed order so that the most foundational failure is reported first. Authentication is checked before role permission; role permission is checked before therapist-of-record ownership; ownership is checked before path existence; path existence is checked before body foreign-key existence; existence is checked before state preconditions; and only when the request has cleared all of the above does the system evaluate domain checks — safety/supervision compliance, referential consistency across entities, temporal admissibility of session intervals, fiscal/quota capacity against the authorization budget, structural constraints such as treatment-plan uniqueness or appeal-round caps, and finally optimistic-concurrency comparison and pagination-parameter parsing. In particular, an `ERR_INVALID_STATE` rejection takes precedence over a downstream supervision-ratio or fiscal-capacity check; conversely, supervision-ratio compliance is evaluated before optimistic-concurrency comparison. Generic body-shape failures — a missing required field, a wrong type, or an enum value outside the documented set — that are not covered by any of the more specific business codes above are surfaced as `ERR_VALIDATION` with HTTP 422.

### 2.9. The Unit-Hour Economy and the Provisional/Adjudicated Split

The system tracks therapy in 15-minute billing units, never in fractional units. Whenever a real-world duration must be converted into units, the minute-count is divided by 15 and rounded up to the next whole unit. Because billing decisions take time to settle, two parallel pictures of consumption are maintained for every Authorization: the **provisional** picture, which updates the instant a session completes and reverses the instant the session is disputed or its containing claim is denied; and the **adjudicated** picture, which moves only when a claim is paid. Both numbers are computed by aggregation over the `BillingLedgerEntry` rows for the Authorization and are exposed on every read of the Authorization as `provisional_units_consumed` and `adjudicated_units_consumed`. A read additionally exposes the two derived balances — provisional balance (approved units minus provisional consumption) and adjudicated balance (approved units minus adjudicated consumption).

Concretely, `provisional_units_consumed` is the sum of the unit-deltas (sign-flipped to positive consumption) across every ledger entry on this authorization whose `entry_type` is either `PROVISIONAL_DEBIT` or `PROVISIONAL_CREDIT`. `adjudicated_units_consumed` is the analogous sum across every ledger entry whose `entry_type` is either `ADJUDICATED_DEBIT` or `ADJUDICATED_CREDIT`. Because each ledger entry stores a signed `units_delta` (negative for debits, positive for credits), the consumption figure is simply the negated sum of all `units_delta` values in the relevant subset. The provisional picture is used for the pre-session unit-hold gate at session creation and at session start, and for the dispute/resolve cycle; the adjudicated picture drives the automatic `ACTIVE → EXHAUSTED` transition on the Authorization when its adjudicated balance reaches zero or below.

### 2.10. The Supervision-Ratio Invariant

A patient's care plan must allocate at least one-tenth of an hour of BCBA supervision for every hour of direct RBT therapy. This invariant is enforced at three distinct moments, and the formula is identical at all three.

At plan activation, the static ratio of `weekly_supervision_hours_target` to `weekly_direct_hours_target` is computed. The plan may only activate when this ratio is greater than or equal to `0.10` — the boundary is inclusive, so a ratio of exactly `0.10` passes, but `0.099999` fails. A failure here yields `ERR_PLAN_RATIO_INSUFFICIENT` with HTTP 422.

At claim payment, and on the explicit on-demand read, a *dynamic* ratio is computed against the actual sessions delivered in the trailing 30 days ending at the clinic's current `now_ts`. The dynamic computation sums the real elapsed minutes (`actual_end` minus `actual_start`) across the patient's `DIRECT_RBT` sessions whose status is `COMPLETED` or `BILLED` and whose `actual_end` falls inside the open-closed window from 30 days before `now_ts` (exclusive) up to `now_ts` (inclusive). The same sum is computed over the patient's `BCBA_SUPERVISION` sessions in the same status set and window. If the RBT minute-total is zero the ratio is treated as exactly `1.0` (vacuously compliant — there is no RBT therapy to supervise). Otherwise the ratio is BCBA-supervision-minutes divided by RBT-minutes. Compliance requires the ratio to be greater than or equal to `0.10`. At claim payment, a violation rejects with `ERR_SUPERVISION_RATIO_BREACH` and HTTP 422; the read capability simply returns the computed `ratio`, the boolean `compliant`, the `rbt_minutes`, the `bcba_supervision_minutes`, the `window_start`, and the `window_end`.

### 2.11. Cascading Side Effects and Ledger Causality

Several transitions cascade across entities. Submitting a claim flips each referenced session from `COMPLETED` to `BILLED`. Denying an adjudicated claim flips each referenced session back from `BILLED` to `COMPLETED` and appends a `PROVISIONAL_CREDIT` ledger entry with `reason_code` of `CLAIM_DENIED`. Appealing a denied claim again flips each referenced session from `COMPLETED` to `BILLED`. Paying an adjudicated claim appends an `ADJUDICATED_DEBIT` entry with `reason_code` of `CLAIM_PAID`, recomputes the Authorization's `adjudicated_units_consumed`, and if the recomputed adjudicated balance is at or below zero the Authorization auto-transitions from `ACTIVE` to `EXHAUSTED` in the same operation. An Authorization moving from `ACTIVE` to `EXPIRED` cascades each of its `SCHEDULED` sessions to `CANCELLED`. A `TreatmentPlan` moving from `ACTIVE` to `EXPIRED` cascades each of the patient's `ACTIVE` Authorizations to `EXPIRED`, which in turn cascades the `SCHEDULED` sessions of those Authorizations to `CANCELLED`. Every such cascade refreshes `updated_at` and bumps `version` on the affected rows.

The `BillingLedgerEntry` is the single source of truth for the unit-hour ledger. Every entry carries the originating `authorization_id`; a session-driven entry carries the originating `session_id`; a claim-driven entry carries the originating `claim_id`; each entry's `entry_type` is one of `PROVISIONAL_DEBIT`, `PROVISIONAL_CREDIT`, `ADJUDICATED_DEBIT`, or `ADJUDICATED_CREDIT`; its `reason_code` is one of `SESSION_COMPLETED`, `SESSION_CANCELLED`, `SESSION_DISPUTED`, `CLAIM_PAID`, `CLAIM_DENIED`, or `CLAIM_APPEAL_PAID`; and its `units_delta` carries the signed unit movement (negative for debits, positive for credits). Ledger rows are append-only — there is no update path and no delete path.

### 2.12. Rounding, Precision, and Boundary Inclusivity

Money is stored as integer cents — there is no fractional cent anywhere. Whenever a dollar amount must be converted to cents, the conversion uses **round half up** to the nearest cent. The patient clinical progress score, conversely, is stored to two decimal places and is also rounded half up.

Boundary inclusivity matters for several thresholds: the supervision-ratio threshold of `0.10` is inclusive (passes at exactly `0.10`); the unit-hour balance check is inclusive (a session whose `planned_units` equals the current provisional balance passes — only strictly greater than fails); the authorization window is closed on both ends (`effective_start` and `effective_end` are both inclusive bounds for billable sessions); the authorization's transition to `EXPIRED` fires on a strict greater-than comparison of `now_ts` against `effective_end`; the supervision-ratio computation window is open on its lower bound and closed on its upper bound (sessions whose `actual_end` is strictly later than `now_ts - 30 days` and at or before `now_ts` are included); and session-overlap checks use half-open intervals on `[planned_start, planned_end)` for therapist conflicts, but closed-closed intervals with a 15-minute buffer on each side for parent-training conflicts.

### 2.13. Concurrency Outcomes

Several races have specific named outcomes. When two BCBAs simultaneously activate two `DRAFT` plans of the same patient, first-writer-wins on the patient's `ACTIVE`-plan slot — the loser is rejected with `ERR_TREATMENT_PLAN_CONFLICT` and HTTP 409. When two therapists race to create overlapping sessions for the same `therapist_id`, first-writer-wins on the half-open interval and the loser is rejected with `ERR_SESSION_THERAPIST_OVERLAP` and HTTP 409. When two BCBAs race to submit two claims that share even one session, first-writer-wins on the session-membership claim — the loser is rejected with `ERR_SESSION_ALREADY_CLAIMED` and HTTP 409. When a `PayerAdmin` pays an adjudicated claim while a `ClinicAdmin` simultaneously appeals after a concurrent denial, first-writer-wins on the claim status — the loser is rejected with `ERR_CLAIM_STATE_INVALID` and HTTP 409. When two `PayerAdmin` operators race to approve a renewal Authorization that points at the same parent Authorization via `renewed_from_id`, first-writer-wins on `renewed_from_id` — the loser is rejected with `ERR_RENEWAL_CONFLICT` and HTTP 409.

## 3. Business Logic & Workflows

### 3.1. Clinic Bootstrap and Therapist Roster

A clinic is brought into existence by a `ClinicAdmin` posting a clinic creation request that carries a single field — the clinic's display `name`. The server mints the clinic identifier, sets the clinic's logical clock `now_ts` to the deterministic epoch `2025-01-01T00:00:00.000Z`, and returns the new row. Reads of the clinic include this `now_ts` so that operators and tests can observe the current logical wall.

With the clinic in place, the `ClinicAdmin` registers therapists. A therapist row carries the owning `clinic_id`, the therapist's `legal_name`, their `credential` (one of `BCBA` or `RBT`), and their `license_number`. Each therapist also carries a `status` of either `ACTIVE` or `SUSPENDED`; therapists are created `ACTIVE`. The therapist's `id` is what the system stores as `X-User-ID` for clinical actors, so it is what every ownership check compares against.

Patient records are created either by a `ClinicAdmin` or by a `BCBA`. A patient carries the owning `clinic_id`, the patient's `legal_name`, their `date_of_birth`, and the payer-issued `insurance_member_id`. Each patient also carries two computed score fields — `clinical_progress_score_provisional` and `clinical_progress_score_adjudicated` — both initialised to `0.0`, and a `status` of `ACTIVE` or `DISCHARGED`; patients are created `ACTIVE`. Reads of the patient return both score fields. The patient list endpoint accepts the `status` query filter and the usual `limit` and `offset` parameters.

### 3.2. Diagnostic Evaluation Lifecycle

Treatment begins with a diagnostic evaluation. A BCBA or a ClinicAdmin schedules the evaluation against a patient; the request body carries the `evaluator_therapist_id` (which must resolve to a `BCBA`-credentialled therapist of the same clinic) and the `scheduled_at` instant. The new evaluation enters `SCHEDULED` status and carries the resolved `patient_id`.

When the evaluation's scheduled instant has arrived — that is, the clinic's `now_ts` is at or after the evaluation's `scheduled_at` — the evaluating BCBA can begin the session. Starting the evaluation moves it from `SCHEDULED` to `IN_PROGRESS`; this is permitted only when the actor is the BCBA whose identifier equals the evaluation's `evaluator_therapist_id`, otherwise the request is rejected with `ERR_NOT_THERAPIST_OF_RECORD`. If the request is made before the scheduled instant — that is, the clinic's `now_ts` is strictly earlier than `scheduled_at` — it is rejected with `ERR_INVALID_STATE`.

Finishing the evaluation requires a body containing the `diagnosis_code` (the ICD-10 code, for example `F84.0`), the `severity_level` (one of `LEVEL_1`, `LEVEL_2`, `LEVEL_3`), and the `recommended_weekly_hours`. The recommended hours must be an integer in the inclusive range from 5 to 40. On the `IN_PROGRESS → COMPLETED` transition, `completed_at` is set to the clinic's current `now_ts`. The evaluation can also be voided by a `ClinicAdmin` from either `SCHEDULED` or `IN_PROGRESS`, terminating it in the `VOID` status.

### 3.3. Treatment Plan Drafting, Activation, and Supersession

Once an evaluation reaches `COMPLETED`, a BCBA drafts a treatment plan against the patient. The draft body carries the `source_evaluation_id` (the id of the completed evaluation it derives from), the `weekly_direct_hours_target`, the `weekly_supervision_hours_target`, and the `weekly_parent_training_hours_target`. At creation, `weekly_direct_hours_target` must equal the source evaluation's `recommended_weekly_hours`; `weekly_parent_training_hours_target` must fall in the closed range from 0.5 to 4.0; and the plan's `plan_version` is set to `1`. The plan enters `DRAFT` status. A patient may have at most one `TreatmentPlan` in `DRAFT` or `ACTIVE` status at any time; a second draft is rejected with `ERR_TREATMENT_PLAN_CONFLICT`.

Activating a plan moves it from `DRAFT` to `ACTIVE`. Activation is gated by three preconditions: the patient must have no other plan currently in `ACTIVE`; the plan's `source_evaluation_id` must still resolve to a diagnostic evaluation in `COMPLETED`; and the static plan ratio — the supervision target divided by the direct target — must be at least `0.10`. A breach of the first yields `ERR_TREATMENT_PLAN_CONFLICT`; a breach of the second yields `ERR_INVALID_STATE`; a breach of the third yields `ERR_PLAN_RATIO_INSUFFICIENT`. On the successful `DRAFT → ACTIVE` transition, the plan's `activated_at` is set to the clinic's current `now_ts`.

A plan can be replaced by a newer plan via the supersede capability. A BCBA prepares a new plan in `DRAFT` for the same patient and then invokes the supersede capability on the new plan, supplying the body field `previous_plan_id` that names the older `ACTIVE` plan. The supersede capability is atomic: the old plan transitions from `ACTIVE` to `SUPERSEDED`, its `superseded_by_id` is set to the new plan's `id`, the new plan's `plan_version` is set to the old plan's `plan_version` plus one, and the new plan transitions from `DRAFT` to `ACTIVE`. The new plan's activation still re-evaluates the supervision-target ratio precondition; the uniqueness check passes because the old plan transitions out of `ACTIVE` in the same step.

A plan moves to `EXPIRED` automatically when the clinic's `now_ts` advances past 365 days after its `activated_at`. This auto-transition cascades every Authorization for the patient that is currently in `ACTIVE` to `EXPIRED`, which itself cascades the `SCHEDULED` sessions of those Authorizations to `CANCELLED`. Every entity along that cascade chain refreshes `updated_at` and bumps `version`.

### 3.4. Authorizations: The Unit-Hour Quota

An authorization is the fiscal contract that funds a patient's care. A `ClinicAdmin` submits the authorization request, carrying a `treatment_plan_id` (which must be `ACTIVE`), a `payer_name`, a `cpt_code` (one of `97151` for evaluation, `97153` for direct RBT therapy, `97155` for BCBA supervision, or `97156` for parent training), the integer `approved_units` (in the inclusive range 1 to 4000 — recall that one unit equals 15 minutes), the `effective_start`, the `effective_end`, and optionally a `renewed_from_id` if this authorization is a renewal of a prior one. The two computed consumption fields `provisional_units_consumed` and `adjudicated_units_consumed` are initialised to zero.

The window must satisfy `effective_end` strictly later than `effective_start`, and the elapsed span between them must be at least 90 days and at most 366 days (both bounds inclusive). The `cpt_code` must be from the closed set listed above. When `renewed_from_id` is supplied, it must resolve to an existing Authorization, and that prior Authorization's `cpt_code` must equal this new one's `cpt_code`; a mismatch is rejected with `ERR_RENEWAL_CPT_MISMATCH`.

A new authorization enters `PENDING`. A `PayerAdmin` resolves it either to `APPROVED` (when the backing `TreatmentPlan` is `ACTIVE` — otherwise the request fails the state precondition) or to `DENIED` (without further precondition). When the clinic's `now_ts` later crosses at or past the authorization's `effective_start`, the Authorization auto-transitions from `APPROVED` to `ACTIVE` on the next clock-advance. When `now_ts` later strictly exceeds the authorization's `effective_end`, the Authorization auto-transitions from `ACTIVE` to `EXPIRED`, cascading every `SCHEDULED` session under it to `CANCELLED`. The Authorization may also reach `EXHAUSTED` automatically when a claim payment drives its adjudicated balance to zero or below; that auto-transition is the third hop of the claim-pay cascade.

A renewal is recognised by the same approval capability. When a `PayerAdmin` approves a `PENDING` Authorization whose `renewed_from_id` points at an `ACTIVE` parent Authorization, the system performs a system-event transition on the parent: the parent's `renewed_to_id` is set to the new Authorization's `id`, and the parent moves from `ACTIVE` to `RENEWED`. Two simultaneous approvals of two renewal Authorizations pointing at the same parent serialize to first-writer-wins on the parent's `renewed_from_id` slot; the loser receives `ERR_RENEWAL_CONFLICT`.

The supervision-ratio read capability for an Authorization returns the computed `ratio`, the boolean `compliant`, the `rbt_minutes`, the `bcba_supervision_minutes`, the `window_start`, and the `window_end` for the trailing 30-day window ending at the clinic's current `now_ts`. The ledger read capability for an Authorization lists its `BillingLedgerEntry` rows in `created_at` ascending order, with the standard pagination parameters.

### 3.5. Scheduling and Running a Therapy Session

A therapy session is scheduled by a `ClinicAdmin` or a `BCBA` against a patient. The request body carries the `authorization_id` (the Authorization that will be debited), the `therapist_id` (the therapist who will conduct the session), the `session_type` (one of `DIRECT_RBT`, `BCBA_SUPERVISION`, or `PARENT_TRAINING`), the `planned_start`, the `planned_end`, and, only when the session is a supervision session, the `supervising_therapist_id` (the id of the RBT being supervised). For non-supervision session types, `supervising_therapist_id` is omitted and is stored as null.

The planned interval must satisfy `planned_end` strictly later than `planned_start`, and its length in minutes — `planned_end` minus `planned_start` measured in whole minutes — must be in the inclusive range from 15 to 480 minutes (that is, between 1 and 32 units inclusive). The system computes `planned_units` by dividing the minute-count by 15 and rounding up to the next whole unit. The Authorization must be `ACTIVE`, and its `cpt_code` must align with the session type: `DIRECT_RBT` requires `97153`, `BCBA_SUPERVISION` requires `97155`, `PARENT_TRAINING` requires `97156`. A mismatch is rejected with `ERR_CPT_CODE_MISMATCH`.

The planned interval must fit inside the Authorization's window: `planned_start` must be at or after the Authorization's `effective_start`, `planned_end` must be at or before its `effective_end`, and `planned_start` must not be in the past relative to the clinic's `now_ts`. A violation of any of these is rejected with `ERR_SESSION_OUTSIDE_AUTH_WINDOW`. The session's `planned_units` must also be at most the Authorization's current provisional balance — at-most is inclusive, so the case where `planned_units` equals the remaining balance passes; only a strict excess is rejected with `ERR_AUTH_UNITS_EXHAUSTED`.

For the same `therapist_id`, no two sessions in any of the statuses `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, `BILLED`, or `DISPUTED` may share any wall-clock minute. The conflict check uses half-open intervals: two sessions whose intervals merely touch at the boundary are permitted, but any positive overlap is rejected with `ERR_SESSION_THERAPIST_OVERLAP`. Parent-training sessions impose an additional restriction on the patient — the planned interval expanded by 15 minutes on each side must not collide with any other session of the same patient in those same statuses; this buffer rule treats touching as a conflict, and a violation is rejected with `ERR_PARENT_TRAINING_BUFFER`.

When the session type is `BCBA_SUPERVISION`, the `supervising_therapist_id` must resolve to an `ACTIVE` `RBT` therapist of the same clinic who has at least one session in `COMPLETED` or `BILLED` with the same patient in the trailing 30 days; otherwise the request is rejected with `ERR_NO_RBT_TO_SUPERVISE`.

Starting a scheduled session moves it from `SCHEDULED` to `IN_PROGRESS` and records `actual_start` as the clinic's `now_ts`. The acting therapist must be the session's `therapist_id`, and the Authorization must still be `ACTIVE`, with the clinic's `now_ts` inside the Authorization window inclusive of both bounds. The CPT-to-session-type alignment is re-evaluated at start time as well.

Completing the session moves it from `IN_PROGRESS` to `COMPLETED`. The body must carry the `progress_rating`, an integer in the inclusive range from 1 to 5. The clinic's `now_ts` must be strictly later than the session's `actual_start`. On the transition, `actual_end` is set to `now_ts`, `billed_units` is computed by dividing the elapsed minutes (`actual_end` minus `actual_start`) by 15 and rounding up to the next whole unit, the `progress_rating` from the body is copied onto the session, a `PROVISIONAL_DEBIT` is appended to the ledger with `units_delta` equal to the negative of `billed_units` and `reason_code` of `SESSION_COMPLETED`, and the Authorization's `provisional_units_consumed` is recomputed from the ledger; the patient's `clinical_progress_score_provisional` is also recomputed.

A completed session can be disputed by a BCBA, who supplies a free-text `dispute_reason` in the body. The dispute is permitted only when the session is not referenced by any `InsuranceClaim` in `SUBMITTED`, `ADJUDICATED`, `PAID`, or `APPEALED`. On `COMPLETED → DISPUTED`, the `dispute_reason` is stored on the session and a `PROVISIONAL_CREDIT` is appended to the ledger with `units_delta` equal to the positive of `billed_units` and `reason_code` of `SESSION_DISPUTED`; the Authorization's `provisional_units_consumed` is recomputed. Resolving the dispute returns the session from `DISPUTED` to `COMPLETED` and re-debits the units: a `PROVISIONAL_DEBIT` is appended with `units_delta` equal to the negative of `billed_units` and `reason_code` of `SESSION_COMPLETED`, and the Authorization's `provisional_units_consumed` is recomputed.

A `SCHEDULED` session may be cancelled by a `ClinicAdmin` or a `BCBA`, terminating it in `CANCELLED`. A session also cascades to `CANCELLED` automatically when its Authorization transitions from `ACTIVE` to `EXPIRED`. The patient-scoped session list endpoint accepts the `status`, `session_type`, and `therapist_id` query filters in addition to the standard pagination parameters.

### 3.6. Claims, Adjudication, and the Appeal Cycle

A claim packages a set of completed sessions for reimbursement. A `ClinicAdmin` drafts the claim under a patient, supplying the body field `authorization_id` and the array `session_ids`. Each element of `session_ids` must reference a session in `COMPLETED`, and no session may already appear in another claim that is `SUBMITTED`, `ADJUDICATED`, `PAID`, or `APPEALED`. Every referenced session's own `authorization_id` must equal the claim's `authorization_id` — a claim is single-auth; a mismatch is rejected with `ERR_SESSION_AUTH_MISMATCH`. At creation, `appeal_round` is `0`, `submitted_amount_cents` and `reimbursed_amount_cents` are `0`, `denial_reason` is null, and the claim's `status` is `DRAFT`.

Submitting the claim moves it from `DRAFT` to `SUBMITTED`. Submission re-verifies that every referenced session is in `COMPLETED` (otherwise `ERR_SESSION_NOT_COMPLETED`) and re-verifies single-auth membership. The sum of `billed_units` across the referenced sessions must be strictly greater than zero — a sum of exactly zero is rejected with `ERR_EMPTY_CLAIM`. On submission, each referenced session cascades from `COMPLETED` to `BILLED`, and `submitted_amount_cents` is computed as follows.

For each session in `session_ids`, iterated in `TherapySession.id` ascending order, the system looks up the per-unit cents rate by `session_type` — `DIRECT_RBT` is reimbursed at `3333` cents per unit (approximately $33.33 per 15 minutes), `BCBA_SUPERVISION` at `6800` cents per unit, and `PARENT_TRAINING` at `5000` cents per unit. The system also resolves the patient-responsibility percentage from the Authorization's `payer_name`; when the payer has no specific entry, the default patient-responsibility percentage is fifteen one-hundredths. The session's per-line dollar amount is computed by multiplying the session's `billed_units` by the per-unit cents rate, dividing by 100 to obtain dollars, and multiplying by one minus the patient-responsibility percentage. That dollar amount is converted to cents by multiplying by 100 and applying round-half-up to obtain an integer cent amount for the line. The claim's `submitted_amount_cents` is then the integer sum of those per-line cent amounts. The rounding order is pinned: round each line to whole cents *first*, then sum — summing first and rounding once would diverge by up to one cent for typical inputs and is not the contract.

A `PayerAdmin` adjudicates the claim by posting the adjudicate capability with an optional body field `denial_reason`. The capability transitions the claim from `SUBMITTED` (or from `APPEALED` in the appeal-cycle case) to `ADJUDICATED`. When `denial_reason` is supplied, it is recorded on the claim; permitted values are `SUPERVISION_RATIO_BREACH`, `UNITS_OUT_OF_AUTH`, `MISSING_PROGRESS_NOTE`, or `DUPLICATE_LINE`.

Paying an adjudicated claim moves it to the terminal `PAID` status. Payment is permitted only when `denial_reason` is null and the patient's supervision ratio over the trailing 30-day window is at least `0.10` at the moment of payment — a breach is rejected with `ERR_SUPERVISION_RATIO_BREACH`. On payment, `reimbursed_amount_cents` is computed (see below), an `ADJUDICATED_DEBIT` is appended to the ledger with `units_delta` equal to the negated sum of `billed_units` across the claim and `reason_code` of `CLAIM_PAID`, the Authorization's `adjudicated_units_consumed` is recomputed, and if the recomputed adjudicated balance is at or below zero the Authorization auto-transitions from `ACTIVE` to `EXHAUSTED` in the same operation; the patient's `clinical_progress_score_adjudicated` is also recomputed.

`reimbursed_amount_cents` is computed per line in the same `TherapySession.id` ascending order as the submitted-amount calculation. For an original submission — where `appeal_round` equals zero — each line's reimbursed amount is exactly the corresponding line's submitted amount. For an appeal cycle — where `appeal_round` is at least one — a per-round haircut is applied: the haircut factor is `(1 − 0.05)` raised to the power of `appeal_round`, so the first appeal pays at 95% of the base line amount, the second appeal pays at 90.25% of the base line amount, and so on. The haircut is applied per line: each base line cents amount is multiplied by the haircut factor and rounded half-up to whole cents *before* the per-line amounts are summed. The same per-line-rounding ordering applies as in the submitted-amount calculation.

Denying an adjudicated claim moves it to `DENIED` and is permitted only when `denial_reason` is already recorded on the claim. The denial cascades each referenced session from `BILLED` back to `COMPLETED`, appends a `PROVISIONAL_CREDIT` to the ledger with `units_delta` equal to the positive of the summed `billed_units` and `reason_code` of `CLAIM_DENIED`, and recomputes the Authorization's `provisional_units_consumed`.

A denied claim can be appealed by a `ClinicAdmin`, moving it from `DENIED` to `APPEALED`. The appeal is permitted only when `appeal_round` is strictly less than 2 — a third appeal attempt is rejected with `ERR_APPEAL_LIMIT_REACHED`. On appeal, `appeal_round` is incremented by one, `denial_reason` is cleared, and the referenced sessions cascade from `COMPLETED` back to `BILLED`. The cycle then re-enters adjudication: the same adjudicate capability moves the claim from `APPEALED` to `ADJUDICATED`, and from there it may be paid (at the haircut-adjusted reimbursement) or denied again.

The patient-scoped claim list and the single-claim read return the same claim shape, including `appeal_round`, `submitted_amount_cents`, `reimbursed_amount_cents`, and `denial_reason`.

### 3.7. The Patient Clinical Progress Score

Every patient carries two computed progress scores. Both are weighted averages of `progress_rating` values weighted by `billed_units`, computed over the trailing 90-day window ending at the clinic's current `now_ts` (sessions whose `actual_end` is strictly later than `now_ts - 90 days` and at or before `now_ts` are included; sessions are iterated in `actual_end` ascending order with `TherapySession.id` ascending as the tie-break).

The provisional score considers any session whose status is `COMPLETED` or `BILLED` and whose `session_type` is either `DIRECT_RBT` or `BCBA_SUPERVISION`, regardless of any claim outcome. It is the sum, over each such session, of `billed_units` multiplied by `progress_rating`, divided by the sum of `billed_units` across those sessions; when the denominator would be zero, the score is taken as zero. The result is rounded half-up to two decimal places and stored on the patient's `clinical_progress_score_provisional`. It is recomputed every time a session completes (and whenever a downstream claim transition affects which sessions qualify).

The adjudicated score considers a strictly narrower set: only sessions whose `session_type` is `BCBA_SUPERVISION` and that are referenced by some claim currently in `PAID`. The same weighted-average formula and the same two-decimal round-half-up rule apply. It is stored on the patient's `clinical_progress_score_adjudicated` and is recomputed on every claim payment for the patient. Because the adjudicated score considers only the supervision sessions inside paid claims, while the provisional score considers all completed direct and supervision sessions, the two figures may diverge sharply when direct-therapy ratings disagree with supervision ratings, or when supervision sessions are not yet paid.

### 3.8. The Logical Clock and Time-Driven Cascades

The deterministic clock-advance capability is the only mechanism that moves time forward. It is admin-only — invoked by a `ClinicAdmin` — and its body carries the target `clinic_id` and the positive integer `seconds` to advance. On every invocation, the system re-evaluates time-gated transitions against the new `now_ts`: every Authorization that was previously `APPROVED` and whose `effective_start` is now at or earlier than `now_ts` advances to `ACTIVE`; every Authorization that is `ACTIVE` and whose `effective_end` is now strictly earlier than `now_ts` advances to `EXPIRED`, cascading its `SCHEDULED` sessions to `CANCELLED`; every `TreatmentPlan` that is `ACTIVE` and whose `activated_at` plus 365 days is now strictly earlier than `now_ts` advances to `EXPIRED`, cascading the patient's `ACTIVE` Authorizations through the same expiration chain. All cascaded rows refresh `updated_at` and bump `version`.

## 4. Endpoint Definitions

All endpoints return HTTP 201 when they create a brand-new resource and HTTP 200 for every other successful operation, including state transitions, computed reads, and list reads. Validation, ownership, and state failures use the HTTP codes documented in section 5. Implementations must not invent additional success codes. Request bodies and response bodies are derived from the workflow narrative in section 3; this table provides only the routing surface.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/advance | Advance a clinic's logical `now_ts` and re-evaluate time-gated transitions. | ClinicAdmin |
| POST | /clinics | Create a clinic. | ClinicAdmin |
| GET | /clinics/{clinic_id} | Read a clinic, including its `now_ts`. | BCBA, RBT, ClinicAdmin, PayerAdmin |
| POST | /patients | Create a patient. | ClinicAdmin, BCBA |
| GET | /patients | List patients for the caller's clinic. | ClinicAdmin, BCBA, RBT |
| GET | /patients/{patient_id} | Read a patient, including both clinical progress scores. | ClinicAdmin, BCBA, RBT, PayerAdmin |
| POST | /therapists | Register a therapist. | ClinicAdmin |
| GET | /therapists/{therapist_id} | Read a therapist. | ClinicAdmin, BCBA, RBT, PayerAdmin |
| POST | /patients/{patient_id}/evaluations | Schedule a diagnostic evaluation. | BCBA, ClinicAdmin |
| POST | /evaluations/{evaluation_id}/start | Begin the evaluation. | BCBA |
| POST | /evaluations/{evaluation_id}/complete | Finish the evaluation with diagnosis. | BCBA |
| POST | /evaluations/{evaluation_id}/void | Void a scheduled or in-progress evaluation. | ClinicAdmin |
| POST | /patients/{patient_id}/treatment-plans | Draft a treatment plan from a completed evaluation. | BCBA |
| POST | /treatment-plans/{plan_id}/activate | Activate a draft treatment plan. | BCBA |
| POST | /treatment-plans/{plan_id}/supersede | Atomically supersede a prior active plan with this draft plan. | BCBA |
| GET | /patients/{patient_id}/treatment-plans | List a patient's treatment plans. | BCBA, ClinicAdmin, RBT, PayerAdmin |
| POST | /patients/{patient_id}/authorizations | Submit an authorization request. | ClinicAdmin |
| POST | /authorizations/{authorization_id}/approve | Approve a pending authorization (also flips parent on renewal). | PayerAdmin |
| POST | /authorizations/{authorization_id}/deny | Deny a pending authorization. | PayerAdmin |
| GET | /authorizations/{authorization_id} | Read an authorization, including both consumption balances. | ClinicAdmin, BCBA, RBT, PayerAdmin |
| GET | /authorizations/{authorization_id}/supervision-ratio | Compute and return the current supervision-ratio snapshot. | ClinicAdmin, BCBA, PayerAdmin |
| GET | /authorizations/{authorization_id}/ledger | List ledger entries for the authorization. | ClinicAdmin, BCBA, PayerAdmin |
| POST | /patients/{patient_id}/sessions | Schedule a therapy session. | ClinicAdmin, BCBA |
| POST | /sessions/{session_id}/start | Begin a scheduled session. | BCBA, RBT |
| POST | /sessions/{session_id}/complete | Finish the session, capturing progress and provisional debit. | BCBA, RBT |
| POST | /sessions/{session_id}/dispute | Mark a completed session as disputed. | BCBA |
| POST | /sessions/{session_id}/resolve-dispute | Return a disputed session to completed. | BCBA |
| POST | /sessions/{session_id}/cancel | Cancel a scheduled session. | ClinicAdmin, BCBA |
| GET | /patients/{patient_id}/sessions | List sessions for a patient. | BCBA, RBT, ClinicAdmin, PayerAdmin |
| POST | /patients/{patient_id}/claims | Draft a claim referencing completed sessions. | ClinicAdmin |
| POST | /claims/{claim_id}/submit | Submit a draft claim. | ClinicAdmin |
| POST | /claims/{claim_id}/adjudicate | Adjudicate a submitted or appealed claim. | PayerAdmin |
| POST | /claims/{claim_id}/pay | Pay an adjudicated claim. | PayerAdmin |
| POST | /claims/{claim_id}/deny | Deny an adjudicated claim with a recorded reason. | PayerAdmin |
| POST | /claims/{claim_id}/appeal | Appeal a denied claim. | ClinicAdmin |
| GET | /patients/{patient_id}/claims | List a patient's claims. | ClinicAdmin, BCBA, PayerAdmin |
| GET | /claims/{claim_id} | Read a single claim. | ClinicAdmin, BCBA, PayerAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_THERAPIST_OF_RECORD | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_SESSION_NOT_COMPLETED | 409 |
| ERR_SESSION_THERAPIST_OVERLAP | 409 |
| ERR_PARENT_TRAINING_BUFFER | 409 |
| ERR_TREATMENT_PLAN_CONFLICT | 409 |
| ERR_CLAIM_STATE_INVALID | 409 |
| ERR_RENEWAL_CONFLICT | 409 |
| ERR_SESSION_ALREADY_CLAIMED | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_SUPERVISION_RATIO_BREACH | 422 |
| ERR_PLAN_RATIO_INSUFFICIENT | 422 |
| ERR_SESSION_AUTH_MISMATCH | 422 |
| ERR_CPT_CODE_MISMATCH | 422 |
| ERR_NO_RBT_TO_SUPERVISE | 422 |
| ERR_SESSION_OUTSIDE_AUTH_WINDOW | 422 |
| ERR_AUTH_UNITS_EXHAUSTED | 422 |
| ERR_EMPTY_CLAIM | 422 |
| ERR_RENEWAL_CPT_MISMATCH | 422 |
| ERR_APPEAL_LIMIT_REACHED | 422 |
| ERR_PAGINATION_PARAMS | 422 |
| ERR_VALIDATION | 422 |
