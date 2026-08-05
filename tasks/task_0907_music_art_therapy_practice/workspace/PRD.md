# Music & Art Therapy Practice API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Music & Art Therapy Practice API, a back-office platform for a clinical practice that delivers both music therapy and art therapy to patients and students. The practice must carry a client from an initial referral, through a clinical assessment, into a plan of care with measurable goals, and onward into a calendar of individual and group sessions delivered by credentialed therapists in shared rooms with finite instruments and art supplies. Every delivered session ultimately becomes either a superbill against a client's insurance or self-pay obligation, or a charge drawn against a facility or school contract budget.

The domain is unusually cross-cutting. A single session simultaneously reserves a therapist's calendar, a room's calendar (with a sterilization-style turnaround buffer between bookings), an instrument or art-supply reservation, and — optionally — a slice of a contract's budget. Scheduling and billing evolve as two independent axes: a session can be completed long before it is billed, and can be re-billed after a superbill is voided without ever changing its scheduling outcome. Financial figures are computed twice by design — an estimated superbill at billing time and a final, remittance-driven figure at adjudication — and self-pay clients are charged on a sliding scale keyed to federal-poverty-level math. The sections below define the global contract that every endpoint honors, then the business workflows where the rules that make this domain hard are deliberately distributed across the narrative.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, headers, envelopes, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or if `X-User-Role` is not one of the four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles:

- `IntakeCoordinator` — front-office intake. Registers therapists, clients, referrals, rooms, materials, and contracts.
- `Therapist` — the clinician. Assesses referrals and owns and operates their own sessions, enrollments, and progress notes.
- `ClinicalDirector` — supervises plans of care. Creates, activates, and revises treatment plans and goals, and discharges clients.
- `BillingSpecialist` — revenue cycle. Creates superbills, posts remittance (adjudication), and voids superbills.

All four roles may call the logical-clock endpoint and every read (GET) endpoint. Each write operation is otherwise restricted to the single role named in its endpoint definition (§4).

Role identity binds to resources as follows. When `X-User-Role` is `Therapist`, `X-User-ID` is the `id` of the acting `Therapist`; ownership checks compare a resource's therapist foreign key to `X-User-ID`. Concretely, when a referral is assessed, the acting therapist's `X-User-ID` is stored as the referral's `assessed_by_therapist_id`; and any write against a session (scheduling, completing, cancelling, enrolling a client, or writing a progress note under one of its enrollments) requires that the session's `therapist_id` equal the acting `X-User-ID`, otherwise the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `IntakeCoordinator`, `ClinicalDirector`, or `BillingSpecialist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server accepts it for authentication and authorization but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope. List endpoints also accept the filter query parameters named in their endpoint definitions (for example `client_id`, `session_id`, `status`), which narrow the result set by exact match before pagination is applied.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities in this system are mutable and therefore additionally carry an `updated_at` timestamp (same format as `created_at`, refreshed on every mutation) and an integer `version` that begins at 1 on creation and increments by exactly 1 on every mutation of that resource. Computed fields count as mutations: when a session completion refreshes a goal's `progress_attendance`, or a superbill create advances a client's `insurance_visits_used`, the affected resource's `updated_at` and `version` both advance.

### 2.5. The Logical Clock

The server keeps a logical clock rather than reading wall-clock time. Before any clock is set, the current instant defaults to `2026-05-01T00:00:00Z`; the server never falls back to wall-clock time. Any of the four roles may advance or set the clock by supplying a `to_iso8601` instant to the clock endpoint, after which the server's notion of "now" (`current_utc`) equals that value. This clock gates session completion: a session may only be completed once `current_utc` has reached or passed the session's scheduled start.

### 2.6. Left-to-Right Resource Resolution

When a request references resources — through path identifiers or through foreign-key fields in the body — the server validates their existence before applying any business rule. Path identifiers are checked left to right; the first identifier that does not resolve produces that entity's specific not-found error (for example `ERR_CLIENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_SUPERBILL_NOT_FOUND`). Body foreign keys are checked after the path, each mapping to its own not-found error: a missing `therapist_id` yields `ERR_THERAPIST_NOT_FOUND`, a missing `room_id` yields `ERR_ROOM_NOT_FOUND`, a missing `goal_id` yields `ERR_GOAL_NOT_FOUND`, a missing `material_item_id` yields `ERR_MATERIAL_NOT_FOUND`, a missing `contract_id` yields `ERR_CONTRACT_NOT_FOUND`, a missing `referral_id` yields `ERR_REFERRAL_NOT_FOUND`, and a missing `client_id` yields `ERR_CLIENT_NOT_FOUND`. All not-found errors carry HTTP 404.

### 2.7. Validation Order and Precedence

When several conditions could reject a single request, the server evaluates them in a fixed priority order and returns the error of the first failing check. The order is:

1. Authentication — headers present and role known (`ERR_UNAUTHENTICATED`, 401).
2. Authorization — the role may perform this operation (`ERR_UNAUTHORIZED`, 403).
3. Existence — every referenced resource exists, path before body as described in §2.6 (the entity-specific 404).
4. Ownership — for session write, complete, cancel, enroll, and progress-note operations, the acting therapist owns the session (`ERR_NOT_RESOURCE_OWNER`, 403).
5. Field validation — required fields present, types correct, enum members valid, numeric ranges satisfied, and `end_utc` strictly later than `start_utc` (`ERR_VALIDATION`, 422).
6. Optimistic concurrency — on plan creation, the supplied client version matches (`ERR_STALE_CLIENT_VERSION`, 412; see §2.8).
7. State — the target resource is in a state that permits the requested transition (`ERR_REFERRAL_INVALID_STATE`, `ERR_PLAN_INVALID_STATE`, `ERR_SESSION_INVALID_STATE`, `ERR_SUPERBILL_INVALID_STATE`, or `ERR_SESSION_NOT_COMPLETED`, each 409).
8. Plan-active gate — scheduling a session requires the referenced plan to be `ACTIVE` (`ERR_PLAN_NOT_ACTIVE`, 409).
9. Referential coherence — the session's goal belongs to the session's plan, and a client is not already enrolled (`ERR_GOAL_PLAN_MISMATCH` or `ERR_CLIENT_ALREADY_ENROLLED`, each 409).
10. Therapist calendar (`ERR_THERAPIST_UNAVAILABLE`, 409).
11. Room calendar (`ERR_ROOM_UNAVAILABLE`, 409).
12. Group capacity (`ERR_SESSION_FULL`, 409).
13. Material availability (`ERR_INSUFFICIENT_MATERIAL`, 409).
14. Contract budget (`ERR_CONTRACT_BUDGET_EXCEEDED`, 402).
15. Insurance authorization (`ERR_AUTH_VISITS_EXHAUSTED`, 402).

Not every check applies to every endpoint; each applies only where its guarded operation lives, as detailed in §3. But wherever two of them could both fire on the same request, the lower-numbered check wins.

### 2.8. Optimistic Concurrency and Plan Supersession

Treatment-plan creation is guarded by optimistic concurrency on the owning client. A request to create a treatment plan for a client must carry `expected_client_version` as a mandatory field whose value is the client's `version` as the caller last observed it. If `expected_client_version` does not equal the client's current `version`, the create is rejected with `ERR_STALE_CLIENT_VERSION` (HTTP 412). This matters because creating a new plan supersedes the client's prior plan and advances the client's `version`: a caller whose `expected_client_version` is stale has not observed a plan that another writer already created against this client, and would otherwise overwrite it. Only the plan-create endpoint takes a client-version field; no other endpoint accepts or requires a version input.

### 2.9. Monetary and Progress Precision

All monetary amounts are stored and computed in integer cents. Wherever a formula requires rounding to whole cents, the system uses round-half-up. A critical, non-obvious rule governs multi-component superbill math: the therapy component and the materials component are each rounded to whole cents *before* they are summed — rounding the raw sum once is explicitly not the rule. Progress ratios (`progress_attendance` and `progress_rubric`) are stored as numbers rounded half-up to exactly two decimal places. The sliding-scale poverty ratio is compared against its band boundaries using exact real division, not a rounded intermediate.

### 2.10. Cascading Consistency

Some operations mutate more than one resource, and the secondary effects are as much a part of the contract as the primary transition. The two largest cascades are client discharge (which flows down through plans, goals, sessions, enrollments, material reservations, and contract spend) and superbill voiding (which reverts the linked session's billing axis and, for insurance clients, refunds an authorized visit). Each resource touched by a cascade is independently mutated: its `updated_at` refreshes and its `version` increments. The precise cascade chains are specified in §3.8 and §3.9. Whenever a session is removed from the active schedule — by cancellation or by the discharge cascade — its material reservation is released and, if it was charged to a contract, that contract's committed spend is refunded.

## 3. Business Logic & Workflows

### 3.1. Intake: Clients, Referrals, and Assessment

The practice begins with people and paperwork. An `IntakeCoordinator` registers a `Therapist` by supplying a `full_name`, a `discipline` of either `MUSIC` or `ART`, and a `credential` string such as a board certification. Clients enter through intake as well: a client is created with a `full_name`, a `dob` in `YYYY-MM-DD` form, and a `payer_type` of either `INSURANCE` or `SELF_PAY`. Self-pay clients supply the sliding-scale inputs — `household_income_cents` (at least 0) and `household_size` (at least 1, defaulting to 1). Insurance clients supply `insurance_payer_name`, an `insurance_coinsurance_pct` between 0.0 and 1.0 inclusive (defaulting to 0.20), an `insurance_contracted_rate_cents` (at least 0) that anchors the estimated superbill, and `insurance_visits_authorized` (at least 0, defaulting to 0). A newly created client starts in `INTAKE` status with `insurance_visits_used` at 0 and `insurance_visits_remaining` equal to `insurance_visits_authorized`; `insurance_visits_remaining` is always the authorized count minus the used count. A client's `status` moves `INTAKE → ACTIVE → DISCHARGED` over its lifetime, and an optional `discharge_reason` is captured when the client is discharged.

Each prospective episode of care is recorded as a `Referral`. The coordinator creates one against a `client_id`, noting the `referral_source` (school, physician, or self), the presenting `reason`, and the `referred_discipline` of `MUSIC` or `ART`. A referral opens in `RECEIVED` status. A `Therapist` then assesses it, which is a branching fork: the therapist submits a `recommendation` — either `THERAPY_RECOMMENDED` or `NOT_APPROPRIATE` — together with a `baseline_score` between 0 and 100 inclusive. Assessment is only permitted while the referral is `RECEIVED`; otherwise the transition is rejected with `ERR_REFERRAL_INVALID_STATE`. On assessment the referral records `assessed_by_therapist_id` as the acting therapist's identity and stores the recommendation and baseline. A recommendation of `THERAPY_RECOMMENDED` advances the referral `RECEIVED → ASSESSED`; a recommendation of `NOT_APPROPRIATE` instead routes it `RECEIVED → DECLINED`, a terminal outcome. Referrals can also be listed with optional filters on `client_id`, `assessed_by_therapist_id`, and `status`.

### 3.2. Treatment Plans and the Revision Cycle

A `ClinicalDirector` builds the plan of care. Creating a treatment plan for a client requires a `referral_id`, a `discipline` (`MUSIC` or `ART`), a `weekly_frequency` of at least 1 planned session per week, and the `expected_client_version` described in §2.8. The new plan opens in `DRAFT` status with `revision_count` at 0. Creation has three coupled effects beyond minting the plan. First, if the named referral is currently `ASSESSED` with a recommendation of `THERAPY_RECOMMENDED`, that referral advances `ASSESSED → CONVERTED`. Second, any plan the client already holds in `DRAFT` or `ACTIVE` status is superseded — it transitions to `SUPERSEDED`. Third, the client's `version` advances by 1, which is precisely why a stale `expected_client_version` is rejected before any of this occurs.

Activation moves a plan `DRAFT → ACTIVE`, and is also the transition that promotes a fresh client into care: if the plan's owning client is still in `INTAKE`, activation bubbles the client up `INTAKE → ACTIVE`. A plan may only be activated from `DRAFT` or from `UNDER_REVISION`; attempting it from any other state yields `ERR_PLAN_INVALID_STATE`. The revision loop is cyclic: an `ACTIVE` plan may be opened for revision, moving it `ACTIVE → UNDER_REVISION`, incrementing `revision_count` by 1, and recording the optional `revision_note`; revising is only permitted from `ACTIVE`, and a violation raises `ERR_PLAN_INVALID_STATE`. Re-activating then returns it `UNDER_REVISION → ACTIVE`, and the plan may cycle between these two states any number of times. Beyond `SUPERSEDED`, the only other terminal fate of a plan is `DISCHARGED`, reached solely through the discharge cascade of §3.9. Plans can be listed with optional filters on `client_id`, `referral_id`, and `status`.

### 3.3. Goals and Progress Measurement

Within a plan, the `ClinicalDirector` defines one or more goals, each carrying a `description`, a `target_sessions` count of at least 1 (the number of attended sessions that would fully satisfy the goal), and a `weight` greater than 0.0 and at most 1.0 expressing its relative importance within the plan. A goal is created under its parent plan, which fixes its `plan_id`; it opens in `OPEN` status with both progress measures — `progress_attendance` and `progress_rubric` — at 0.0. Goals may be listed under their plan.

Progress is measured two independent ways, and the two can diverge for identical session history — this is intentional. The **attendance** view answers "how many of the targeted sessions were actually attended?" It counts the distinct sessions tied to this goal that have reached `COMPLETED` and in which at least one client belonging to the plan has an enrollment marked `ATTENDED`; `progress_attendance` is that attended-session count divided by `target_sessions`, capped at 1.0, and rounded half-up to two decimal places. This measure is recomputed each time a session for the goal is completed, and if it reaches 1.0 while the goal is still `OPEN`, the goal transitions `OPEN → MET`. The **rubric** view answers "what do the signed clinical notes say?" It takes every progress note that has been signed and whose enrollment traces back to a session on this goal, averages their `rubric_score` values, divides the mean by 100, and rounds half-up to two decimal places; when there are no signed notes, `progress_rubric` is 0.0. The rubric measure is recomputed whenever a relevant note is signed. A goal's only other terminal state, `DISCONTINUED`, is reached through discharge (§3.9).

### 3.4. Practice Resources: Rooms, Materials, and Contracts

Three supporting resources are registered by the `IntakeCoordinator` and consumed by sessions. A `Room` has a `name` and a `capacity` of at least 1 concurrent occupant. A `MaterialItem` — an instrument or an art supply — has a `name`, a `category` of `INSTRUMENT` or `ART_SUPPLY`, an `on_hand_quantity` of total units owned (at least 0), a `unit_charge_cents` per-unit charge used when materials appear on a superbill (at least 0), and two computed counters: `reserved_quantity`, the units currently held by scheduled sessions (starting at 0), and `available_quantity`, defined as `on_hand_quantity` minus `reserved_quantity`. The available count is a conserved invariant: reserved plus available always equals on-hand, and available never goes negative. A material may be fetched to read its live counters.

A `Contract` represents a facility or school engagement. It carries a `party_name`, a `contract_type` of `FACILITY` or `SCHOOL`, a `budget_cents` total (at least 0), and a `rate_cents_per_session` (at least 0) charged to the contract for each delivered session. Its computed `spent_cents` starts at 0 and equals the per-session rate multiplied by the count of non-cancelled sessions charged to the contract. Contract spend is committed when a session that names the contract is scheduled and released when such a session is cancelled or swept up in a discharge.

### 3.5. Scheduling a Session

A `Therapist` schedules a `Session`, and this is where the calendar, capacity, material, and budget constraints converge. The scheduling payload names the `therapist_id`, `room_id`, `plan_id`, and `goal_id`, a `modality` of `INDIVIDUAL` or `GROUP`, and the interval `start_utc`/`end_utc`. It may optionally set a `capacity` (maximum enrollments; an individual session defaults to 1), a `material_item_id` with a `material_qty` of units to reserve (defaulting to 0 when no material is used), and a `contract_id` binding the session to a contract budget. A new session opens with `scheduling_status` at `SCHEDULED` and `billing_status` at `UNBILLED`; its `attended_count` begins at 0. Because a therapist may only operate their own sessions, the acting `X-User-ID` must equal the payload's `therapist_id`, or the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

The checks that guard scheduling fire in the priority order of §2.7. After field validation — which requires `end_utc` to be strictly after `start_utc` — the referenced plan must be `ACTIVE`, or the request is rejected with `ERR_PLAN_NOT_ACTIVE`; a plan in `DRAFT`, `UNDER_REVISION`, `SUPERSEDED`, or `DISCHARGED` cannot host new sessions. Next, the chosen `goal_id` must belong to the chosen `plan_id`, otherwise `ERR_GOAL_PLAN_MISMATCH`. The therapist's calendar is then checked: the requested half-open interval, from `start_utc` up to but not including `end_utc`, must not overlap any other non-cancelled session for the same therapist; two sessions that merely touch at a boundary (one ending exactly when the next begins) do not conflict, but any true overlap raises `ERR_THERAPIST_UNAVAILABLE`. The room calendar is stricter because rooms need turnaround time between bookings: the practice enforces a fifteen-minute turnaround buffer, so a new booking conflicts with any non-cancelled session in the same room whose interval, expanded by fifteen minutes both before its start and after its end, overlaps the new session's interval; a conflict raises `ERR_ROOM_UNAVAILABLE`.

Material and budget reservations complete the scheduling picture. If a `material_item_id` is named, the requested `material_qty` must not exceed that item's `available_quantity`; if it would, the request is rejected with `ERR_INSUFFICIENT_MATERIAL`, and otherwise the item's `reserved_quantity` rises by `material_qty` (and its `available_quantity` falls correspondingly). If a `contract_id` is named, the session is charged to the contract rather than superbilled, and the budget is checked by projecting the contract's `spent_cents` plus its `rate_cents_per_session`: if that projected total would exceed `budget_cents` the request is rejected with `ERR_CONTRACT_BUDGET_EXCEEDED`, where the boundary is strict — a projection exactly equal to the budget is allowed. When it passes, the contract's `spent_cents` is raised to that projected total, reserving the charge at scheduling time. Sessions can be fetched individually and listed with optional filters on `therapist_id`, `room_id`, `plan_id`, `goal_id`, `material_item_id`, `contract_id`, and `status`.

### 3.6. Enrollment, Attendance, and Completion

Clients join a session through enrollment, and only the owning therapist may enroll them. Enrolling a `client_id` creates an `Enrollment` under the session in `ENROLLED` status. Two guards apply: a client who already holds a non-cancelled enrollment in the session cannot be enrolled again (`ERR_CLIENT_ALREADY_ENROLLED`), and enrollment is refused once the non-cancelled enrollment count has reached the session's `capacity` (`ERR_SESSION_FULL`). An individual session, defaulting to a capacity of 1, therefore admits exactly one active enrollee, while a group session admits up to its stated capacity. Enrollments can be listed or fetched, with list filters on `client_id`, `session_id`, and `status`.

Completion is driven by the owning therapist and gated by the logical clock: a session can only be completed once `current_utc` has reached or passed its `start_utc`, and only while it is still `SCHEDULED`; a premature or wrongly-stated attempt is rejected with `ERR_SESSION_INVALID_STATE`. The therapist supplies `attended_client_ids`, and every id listed must be an `ENROLLED` enrollee of this session. The outcome forks on that list. When at least one client attended, the session advances `SCHEDULED → COMPLETED`: each named enrollment moves `ENROLLED → ATTENDED`, every other still-`ENROLLED` enrollment moves `ENROLLED → NO_SHOW`, and `attended_count` is set to the number of attendees. When the list is empty, the whole session is a wash and advances `SCHEDULED → NO_SHOW`, moving all `ENROLLED` enrollments to `NO_SHOW`. Either way, the session's material reservation is released — the item's `reserved_quantity` drops by `material_qty` — because the instruments and supplies are no longer held. Only on a genuine completion does the goal recompute: `progress_attendance` for the session's `goal_id` is recalculated per §3.3, and if it reaches 1.0 the goal transitions `OPEN → MET`.

A `Therapist` may instead cancel a still-`SCHEDULED` session, optionally noting a `cancel_reason`. Cancellation advances the session `SCHEDULED → CANCELLED`, moves all its non-terminal enrollments to `CANCELLED`, releases the material reservation (dropping `reserved_quantity` by `material_qty`), and — if the session was charged to a contract — refunds the contract by lowering its `spent_cents` by `rate_cents_per_session`. Cancelling anything not in `SCHEDULED` raises `ERR_SESSION_INVALID_STATE`.

### 3.7. Progress Notes and Clinical Outcomes

Under an enrollment, the owning therapist writes a `ProgressNote` capturing a clinical `narrative`, a structured `rubric_score` between 0 and 100 inclusive, and an `outcome_rating` of `IMPROVED`, `MAINTAINED`, or `DECLINED`. A note is created in `DRAFT` status and does not yet influence any goal. Signing the note advances it `DRAFT → SIGNED`, a terminal state, and only then does it feed clinical outcomes: signing triggers a recompute of `progress_rubric` for the goal that the note's enrollment ultimately belongs to, following the rubric formula of §3.3. Notes may be listed under their enrollment or created there; the note's `enrollment_id` is fixed by the enrollment it is written under.

### 3.8. Billing: Superbills, Adjudication, and Voiding

Billing runs on the session's second, independent axis. A session may be billed only after it has been completed and while its `billing_status` is `UNBILLED`; a `BillingSpecialist` creates a `Superbill` naming the `session_id` and a `client_id` that must be an `ATTENDED` enrollee of that session. If the session is not `COMPLETED`, the create is rejected with `ERR_SESSION_NOT_COMPLETED`. For an insurance client, the superbill also consumes authorization: `insurance_visits_remaining` must be at least 1, or the create is rejected with `ERR_AUTH_VISITS_EXHAUSTED`. On success the session advances `UNBILLED → BILLED`, a new superbill opens in `SUBMITTED` status, and — for an insurance client — the client's `insurance_visits_used` rises by 1.

At creation the superbill snapshots and computes its money. It copies the client's `payer_type`, and for insurance the client's coinsurance into `coinsurance_pct`. The `therapy_charge_cents` is the individual rate of 12503 cents when the session modality is `INDIVIDUAL` and the group rate of 6503 cents when it is `GROUP`. The `materials_charge_cents` is the session's `material_qty` multiplied by the material item's `unit_charge_cents`, and is 0 when no material was used. The `billed_amount_cents` is the therapy charge plus the materials charge.

The patient's share is computed one of two ways. For an **insurance** client, the estimated variant is used at creation: the therapy component's allowed amount is the lesser of `therapy_charge_cents` and the client's `insurance_contracted_rate_cents`, the materials component's allowed amount is the full `materials_charge_cents`, and `allowed_amount_cents` is their sum. The `patient_responsibility_cents` is computed per component and then summed: the therapy component's allowed amount times `coinsurance_pct`, rounded half-up to whole cents, plus the materials component's allowed amount times `coinsurance_pct`, rounded half-up to whole cents. The `plan_paid_cents` is `allowed_amount_cents` minus `patient_responsibility_cents`, and `adjustment_cents` is 0 at this estimated stage. For a **self-pay** client, the sliding scale sets the responsibility directly. First compute the household's federal poverty level as 1560000 cents plus 550000 cents for each additional household member beyond the first — that is, `1560000 + 550000 × (household_size − 1)`. Divide `household_income_cents` by that poverty level using exact real division to get the income ratio. A ratio at or below 1.50 earns a 75% discount; above 1.50 and at or below 2.50 earns 50%; above 2.50 and at or below 4.00 earns 25%; above 4.00 earns no discount. Take the base rate for the session's modality (the individual rate of 12503 cents or the group rate of 6503 cents), multiply it by one minus the discount, and round half-up to whole cents; then clamp the result so it is never below the 2000-cent minimum fee and never above the undiscounted base rate. That clamped figure is the self-pay `patient_responsibility_cents`; `plan_paid_cents` is 0, and `adjustment_cents` is the `billed_amount_cents` minus the patient responsibility (the sliding-scale write-off).

Adjudication posts the real remittance. The `BillingSpecialist` supplies the remittance `allowed_amount_cents`, permitted only while the superbill is `SUBMITTED` (otherwise `ERR_SUPERBILL_INVALID_STATE`) and while the session's billing axis is `BILLED`. The superbill advances `SUBMITTED → ADJUDICATED` and the session advances `BILLED → ADJUDICATED`. In this final variant, `allowed_amount_cents` becomes the posted remittance figure, and `adjustment_cents` becomes `billed_amount_cents` minus that allowed amount. The patient responsibility is recomputed by apportioning the allowed amount across the two components in proportion to their billed charges — the therapy component's share is the remittance allowed amount times `therapy_charge_cents` divided by `billed_amount_cents`, and the materials component's share is the remittance allowed amount times `materials_charge_cents` divided by `billed_amount_cents` — then taking each component's share times `coinsurance_pct`, rounding each half-up to whole cents, and summing the two. The `plan_paid_cents` is the allowed amount minus the recomputed `patient_responsibility_cents`.

Voiding unwinds a superbill. A `BillingSpecialist` may void a superbill that is either `SUBMITTED` or `ADJUDICATED`, driving it to the terminal `VOIDED` state; any other starting state raises `ERR_SUPERBILL_INVALID_STATE`. Voiding cascades to the linked session, reverting its billing axis to `UNBILLED` (from either `BILLED` or `ADJUDICATED`), which frees the session to be billed again later. If the client is an insurance client, the void also refunds the authorization by lowering `insurance_visits_used` by 1, so `insurance_visits_remaining` recovers. Superbills can be fetched individually and listed with filters on `client_id`, `session_id`, and `status`.

### 3.9. Discharge and the Consistency Cascade

Discharge is the largest cascade in the system, performed by a `ClinicalDirector` on a client that is currently `ACTIVE` (attempting to discharge a client that is not `ACTIVE` raises `ERR_PLAN_INVALID_STATE` for the associated plan-level guard, and the client itself will not transition). The director may supply an optional `discharge_reason`, which is recorded as the client moves `ACTIVE → DISCHARGED`. From there the cascade flows down five levels. The client's plan that is currently `ACTIVE` or `UNDER_REVISION` transitions to `DISCHARGED`. Each `OPEN` goal of that plan transitions to `DISCONTINUED`. Each still-`SCHEDULED` session tied to such a goal transitions `SCHEDULED → CANCELLED`. Each non-terminal enrollment of those cancelled sessions transitions to `CANCELLED`. And every cancelled session releases its held resources exactly as a manual cancellation would: its material reservation is returned (the item's `reserved_quantity` drops by `material_qty`), and if it was charged to a contract, that contract's `spent_cents` is lowered by `rate_cents_per_session`. Every resource touched along this chain has its `updated_at` refreshed and its `version` incremented, keeping the whole hierarchy consistent in a single discharge operation.

## 4. Endpoint Definitions

Operations that create a new resource return HTTP 201 Created; operations that modify an existing resource, including state-transition and clock endpoints, return HTTP 200 OK. All GET endpoints return 200. "Any" in the authorized-role column means all four roles (`IntakeCoordinator`, `Therapist`, `ClinicalDirector`, `BillingSpecialist`).

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Any |
| POST | `/therapists` | Register a therapist | IntakeCoordinator |
| POST | `/clients` | Create a client (intake) | IntakeCoordinator |
| GET | `/clients/{id}` | Get a client (status, version, visit counters) | Any |
| POST | `/clients/{id}/discharge` | Discharge a client; cascades to plan/goals/sessions/enrollments/materials/contracts | ClinicalDirector |
| POST | `/referrals` | Create a referral for a client | IntakeCoordinator |
| GET | `/referrals` | List referrals | Any |
| GET | `/referrals/{id}` | Get a referral | Any |
| POST | `/referrals/{id}/assess` | Record assessment; forks to ASSESSED or DECLINED | Therapist |
| POST | `/clients/{id}/treatment-plans` | Create a treatment plan (supersedes prior plan; OCC on client version) | ClinicalDirector |
| GET | `/treatment-plans` | List treatment plans | Any |
| GET | `/treatment-plans/{id}` | Get a treatment plan | Any |
| POST | `/treatment-plans/{id}/activate` | Activate a plan (DRAFT or UNDER_REVISION to ACTIVE) | ClinicalDirector |
| POST | `/treatment-plans/{id}/revise` | Open a plan for revision (ACTIVE to UNDER_REVISION) | ClinicalDirector |
| POST | `/treatment-plans/{id}/goals` | Add a goal to a plan | ClinicalDirector |
| GET | `/treatment-plans/{id}/goals` | List goals of a plan | Any |
| POST | `/rooms` | Create a room | IntakeCoordinator |
| POST | `/materials` | Create a material (instrument or art supply) | IntakeCoordinator |
| GET | `/materials/{id}` | Get a material (available/reserved quantities) | Any |
| POST | `/contracts` | Create a facility/school contract | IntakeCoordinator |
| POST | `/sessions` | Schedule a session (reserves therapist+room calendar and any material) | Therapist |
| GET | `/sessions/{id}` | Get a session | Any |
| GET | `/sessions` | List sessions | Any |
| POST | `/sessions/{id}/complete` | Complete a session; marks attendance, releases materials, updates goal progress | Therapist |
| POST | `/sessions/{id}/cancel` | Cancel a scheduled session (releases reservations) | Therapist |
| POST | `/sessions/{id}/enrollments` | Enroll a client into a session | Therapist |
| GET | `/enrollments` | List enrollments | Any |
| GET | `/enrollments/{id}` | Get an enrollment | Any |
| POST | `/enrollments/{id}/progress-notes` | Write a progress note for an enrollment | Therapist |
| GET | `/enrollments/{id}/progress-notes` | List progress notes of an enrollment | Any |
| POST | `/progress-notes/{id}/sign` | Sign a progress note (DRAFT to SIGNED); feeds goal rubric progress | Therapist |
| POST | `/superbills` | Create a superbill for a completed session's attended client (ESTIMATED variant) | BillingSpecialist |
| GET | `/superbills` | List superbills | Any |
| GET | `/superbills/{id}` | Get a superbill | Any |
| POST | `/superbills/{id}/adjudicate` | Post remittance; recompute FINAL variant | BillingSpecialist |
| POST | `/superbills/{id}/void` | Void a superbill (reverts billing; refunds insurance visit) | BillingSpecialist |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_THERAPIST_NOT_FOUND` | 404 |
| `ERR_REFERRAL_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_GOAL_NOT_FOUND` | 404 |
| `ERR_ROOM_NOT_FOUND` | 404 |
| `ERR_MATERIAL_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_SUPERBILL_NOT_FOUND` | 404 |
| `ERR_REFERRAL_INVALID_STATE` | 409 |
| `ERR_PLAN_INVALID_STATE` | 409 |
| `ERR_PLAN_NOT_ACTIVE` | 409 |
| `ERR_SESSION_INVALID_STATE` | 409 |
| `ERR_SESSION_NOT_COMPLETED` | 409 |
| `ERR_SUPERBILL_INVALID_STATE` | 409 |
| `ERR_GOAL_PLAN_MISMATCH` | 409 |
| `ERR_CLIENT_ALREADY_ENROLLED` | 409 |
| `ERR_SESSION_FULL` | 409 |
| `ERR_THERAPIST_UNAVAILABLE` | 409 |
| `ERR_ROOM_UNAVAILABLE` | 409 |
| `ERR_AUTH_VISITS_EXHAUSTED` | 402 |
| `ERR_CONTRACT_BUDGET_EXCEEDED` | 402 |
| `ERR_INSUFFICIENT_MATERIAL` | 409 |
| `ERR_STALE_CLIENT_VERSION` | 412 |
