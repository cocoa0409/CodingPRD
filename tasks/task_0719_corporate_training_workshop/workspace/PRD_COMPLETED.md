# Corporate Training & Workshop API — Product Requirements Document

## 1. Introduction

Enterprise learning-and-development teams juggle two hard problems at once: designing the right program content and then physically delivering it to learners under finite constraints. This API is the system of record for both. On the design side, it tracks catalog and bespoke programs through an iterative authoring loop, versioning each revision so that a published offering always resolves to one approved, billable specification. On the delivery side, it manages the scheduling of cohorts, the assignment of certified facilitators to virtual or onsite sessions, and — most importantly — the competition for a strictly limited pool of seats within each cohort.

The seat pool is the heart of the system. Every registration competes for a finite number of seats: a seat is provisionally held when a learner enrolls, firmly committed when they confirm, and released back to the pool (with automatic waitlist promotion) when they withdraw or when a cohort is cancelled. Because several coordinators and learners may act against the same cohort, the seat ledger is protected by optimistic concurrency control so that no operator locks a cohort against a seat count they never observed.

Layered on top of seat management is a full financial and certification pipeline. Cohorts are priced either per confirmed seat or as a flat delivery fee, and onsite delivery adds facilitator travel reimbursement. Provisional invoices are emitted when enrollment locks and finalized when delivery closes, optionally drawing down an enterprise client's contracted budget. Learners who attend and pass an assessment earn CEU-bearing certificates, and post-delivery evaluations roll up into a cohort Net Promoter Score. This document specifies every entity, state transition, calculation, and guard rule that governs that end-to-end flow.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the operational capacity under which the request is made. If either header is absent, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly five roles, spelled precisely as follows: `ProgramDesigner`, `SchedulingCoordinator`, `Facilitator`, `Learner`, and `FinanceManager`. When a request is authenticated but the acting role is not permitted to perform the requested operation, the system responds with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The five roles divide responsibility across the program design and delivery lifecycle. A `ProgramDesigner` owns catalog and custom program design, drives the version authoring and approval loop, and issues or revokes certificates. A `SchedulingCoordinator` manages facilitators, schedules cohorts and steers them through their lifecycle, adds sessions, assigns co-facilitators, and may register or withdraw learners on their behalf. A `Facilitator` delivers sessions, marks attendance, and grades assessments. A `Learner` registers for cohorts, confirms or withdraws their own seat, and submits evaluations. A `FinanceManager` owns enterprise contracts and has visibility into invoices.

Four of the five roles carry an opaque identity. When `X-User-Role` is `ProgramDesigner`, `SchedulingCoordinator`, `Learner`, or `FinanceManager`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but does not compare it to any entity's `id`. The `Facilitator` role is entity-backed: when `X-User-Role` is `Facilitator`, `X-User-ID` is the `id` of the acting `Facilitator` entity, and any ownership check on a resource that references a `Facilitator` compares the resource's facilitator foreign-key field to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. A `limit` or `offset` that is non-integer, a `limit` outside the 1-through-100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless an endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order; when two resources share an identical `created_at`, the tie is broken by their underlying creation order so that earlier-created resources sort first. Every list response includes the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in this system share a standard set of server-managed fields. The `id` is a server-minted UUID carrying no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field, formatted identically, records the most recent mutation. The `version` field is an integer that starts at 1 and increments by one on every mutation of the resource; it underpins the optimistic concurrency control described in §2.7.

One entity is deliberately leaner. The `Evaluation` resource is append-only feedback and carries only an `id` and a `created_at`; it has neither an `updated_at` nor a `version` field. All other entities — Program, ProgramVersion, Facilitator, Cohort, Session, SessionAssignment, Registration, Assessment, Certificate, EnterpriseContract, and Invoice — carry the full set of common fields.

All time-sensitive checks — enrollment windows, cohort start and end gating, session interval bounds, facilitator and room overlap — are evaluated against a **logical clock** rather than wall-clock time. The server starts with the logical clock fixed at `2026-03-01T00:00:00Z`; before any clock is set, every check reads exactly this default and never falls back to real-world time. An administrative test-driving capability advances the clock to a supplied instant via the `to_iso8601` field, after which all subsequent temporal comparisons use the new value.

### 2.5. Seat Ledger and Derived Count Reconciliation

Each `Cohort` maintains three derived seat counters that the system keeps consistent with the registrations beneath it. The `seats_reserved` field is the count of registrations currently in `ENROLLED` state. The `seats_confirmed` field is the count of registrations in either `CONFIRMED` or `ATTENDED` state. The `seats_waitlisted` field is the count of registrations in `WAITLISTED` state. These counters are never set directly by clients; they move only as a side effect of registration transitions, and every such adjustment is a mutation of the cohort that refreshes its `updated_at` and increments its `version`.

Seat availability is governed by `seat_capacity`, the maximum total of confirmed and reserved seats, and by `waitlist_capacity`, the maximum number of waitlisted registrations. A cohort's run viability is governed by `min_seats`, carried on its program version, the minimum number of confirmed seats required for the cohort to lock and run. Because confirm, withdraw, and lock all read and write the same seat ledger, the ledger is the contended resource that the concurrency control of §2.7 protects.

### 2.6. Cascading Consistency on Cohort Cancellation

The most consequential cascade in the system is cohort cancellation. When a cohort in `OPEN` or `LOCKED` state is cancelled, the system performs a three-level cascade in order. First (level one), every non-terminal `Registration` of that cohort transitions to `CANCELLED`. Second (level two), for each registration that was just cancelled and that holds an `ISSUED` `Certificate`, that certificate transitions to `REVOKED`. Third (level three), each newly revoked certificate's CEU award is removed from the learner record; because the cohort is cancelled, no contract draw is taken. In addition, any `PROVISIONAL` or `FINAL` `Invoice` attached to the cohort transitions to `VOID`, and if the cohort had reserved budget against a contract that reservation is released and the contract's available budget restored. Throughout this cascade, every entity whose state changes has its `updated_at` and `version` advanced.

A symmetric reconciliation governs the enterprise contract. When a cohort close has committed budget against a contract and that commitment is later voided or reversed, freeing the committed budget, an `EXHAUSTED` contract automatically returns to `ACTIVE`. This compensation path is the only way an exhausted contract reopens.

### 2.7. Optimistic Concurrency Control on Cohort Locking

Locking a cohort is the single operation guarded by optimistic concurrency control. The lock request must carry `expected_cohort_version` as a required input field bearing the client's last observed `version` of the target `Cohort`. The server compares that value against the cohort's current `version`. If a confirm or withdraw has bumped the cohort's version since the coordinator last read it — meaning the lock request is acting on a stale view of the seat ledger — the lock is rejected with `ERR_STALE_COHORT_VERSION` (HTTP 412). Only the cohort-lock operation takes a version field; no other endpoint accepts or requires `expected_cohort_version`.

### 2.8. Pricing, Materials, Travel, and Monetary Precision

All monetary amounts in the system are expressed and stored as integer cents; because every pricing, materials, and travel input is already an integer number of cents, the invoice arithmetic introduces no fractional cents and requires no rounding. Two calculations in the system do round: assessment percentage scores are rounded half up to two decimal places, and the cohort NPS is rounded half up to a whole integer. Each is described in §3 where the workflow that produces it lives.

Pricing is dual-variant. A program version declares a `pricing_model` of either `PER_SEAT` or `FLAT`. Under `PER_SEAT`, tuition is the per-seat price multiplied by the relevant number of seats; under `FLAT`, tuition is a single flat delivery fee independent of seat count. Materials are always charged per seat. Travel reimbursement applies only to onsite or hybrid delivery. The precise formulas, including which seat set each invoice variant uses, are specified in §3.6.

### 2.9. Reference, Existence, and State Validation Ordering

For any request, validations are applied in a fixed priority order so that the failure a client sees is deterministic. Authentication is checked first: a request missing its identity headers fails with `ERR_UNAUTHENTICATED` before anything else. Role authorization is checked second, yielding `ERR_FORBIDDEN_ROLE` when the acting role may not perform the operation. Third, the existence of every resource referenced by the path or body is verified left-to-right; the first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` (HTTP 404). Fourth, on create endpoints that carry foreign-key body fields, each foreign key must reference a resource of the correct type — for example, a `program_version_id` must resolve to a `ProgramVersion` — and a wrong-type or wrong-lifecycle reference yields `ERR_INVALID_REFERENCE` (HTTP 422). Fifth, for any state-transition endpoint, the target resource must currently be in a state from which the requested transition is defined; otherwise the request is rejected with `ERR_INVALID_STATE` (HTTP 409). A malformed body, a missing required field, or a value of the wrong type or outside an enum is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

These global checks always precede the domain-specific guards described in §3. Where a single operation carries several domain guards, the relative ordering among them is stated alongside that operation's narrative.

## 3. Business Logic & Workflows

### 3.1. Designing Programs and Versioning Their Content

A `ProgramDesigner` opens the catalog by creating a `Program`, supplying a `title`, a `category` that is one of `LEADERSHIP`, `TECHNICAL`, `COMPLIANCE`, or `SALES`, and a `delivery_mode` of `VIRTUAL`, `ONSITE`, or `HYBRID`. Two optional inputs round out the program: `ceu_credits`, the Continuing Education Units awarded on a passing outcome, which defaults to 0 and must be at least 0 and at most 40 with one decimal place of precision; and `is_custom`, a boolean that defaults to false and marks a bespoke client design as opposed to a standard catalog offering. A new program begins in `DRAFT` status with its `active_version_id` set to null. Retiring a program moves its `status` to `RETIRED`.

The substance of a program lives in its versions. A designer creates a `ProgramVersion` under a program by supplying the owning `program_id`, an author-chosen `version_label`, the total instructional `duration_hours` (which must be greater than 0), and a `pricing_model` of `PER_SEAT` or `FLAT`. The `program_id` is resolved directly against the program table, so any `program_id` that does not name an existing `Program` — whether it resolves to no resource at all or to a resource of another type — is rejected with `ERR_NOT_FOUND`. Pricing inputs are `per_seat_cents` (the price per confirmed seat in cents, used under per-seat pricing, defaulting to 0), `flat_fee_cents` (the single delivery fee in cents, used under flat pricing, defaulting to 0), and `materials_kit_cents` (the per-seat printed or onsite materials cost in cents, defaulting to 0). Two further inputs tune delivery: `min_seats`, the minimum number of confirmed seats for the cohort to run, defaulting to 1 and required to be at least 1; and `pass_threshold_pct`, the assessment percentage required to pass, defaulting to 70 and constrained to the range 0 through 100 inclusive. A version begins in `DRAFT` status.

The authoring loop is cyclic. A designer submits a draft version for review, moving it from `DRAFT` to `IN_REVIEW`. Submission is allowed only when `duration_hours` is greater than 0 and the pricing inputs are complete for the chosen model: under `PER_SEAT`, `per_seat_cents` must be greater than 0, and under `FLAT`, `flat_fee_cents` must be greater than 0. An incomplete pricing configuration is rejected with `ERR_PRICING_INCOMPLETE` (HTTP 422). From `IN_REVIEW`, the designer may request changes, sending the version back from `IN_REVIEW` to `DRAFT` for another revision pass — this is the loop that lets a version be refined repeatedly before approval.

Approving a version transitions it from `IN_REVIEW` to `APPROVED`. Approval is blocked when the owning program is `RETIRED`, in which case the request is rejected with `ERR_PROGRAM_RETIRED`. Approval carries two side effects on success. First, if another version of the same program was already `APPROVED`, that prior version is automatically moved to `SUPERSEDED` — the terminal state for a version. Second, the program's `active_version_id` is set to point at the newly approved version's id, and if the program was still in `DRAFT` its `status` advances to `PUBLISHED`. The `active_version_id` is a computed back-pointer to the currently approved version, resolvable forward by fetching that program version directly.

### 3.2. Onboarding Facilitators

A `SchedulingCoordinator` registers a `Facilitator` by providing a `full_name`, a unique `email` (no two facilitators may share an email), and a `certified_categories` array — the subset of `LEADERSHIP`, `TECHNICAL`, `COMPLIANCE`, and `SALES` program categories the facilitator is qualified to teach. An optional `travel_base_cents` records the flat travel reimbursement in cents charged whenever this facilitator leads an onsite or hybrid cohort; it defaults to 0. A facilitator starts `ACTIVE` and can be moved to `SUSPENDED`. Because the `Facilitator` role is entity-backed, the facilitator entity's `id` is what a facilitator's `X-User-ID` carries when they act on the system.

### 3.3. Scheduling and Running a Cohort

A cohort is a concrete delivery of an approved program version. A `SchedulingCoordinator` schedules a `Cohort` by supplying the `program_version_id` of the approved version to deliver, the `lead_facilitator_id` of the primary facilitator, an optional `contract_id` naming a sponsoring enterprise contract (null for open-enrollment), the `seat_capacity` (the maximum total of confirmed and reserved seats, at least 1), an optional `waitlist_capacity` (the maximum waitlisted registrations, defaulting to 0 and never negative), the cohort `delivery_mode`, and three instants: `starts_at`, `ends_at` (which must be after `starts_at`), and `enroll_deadline` (the last instant a learner may enroll, which must be at or before `starts_at`). A new cohort begins in `SCHEDULED` state with all three seat counters at 0 and its `version` at 1.

Opening a cohort advances it from `SCHEDULED` to `OPEN` and is the gate that lets registrations begin. Four preconditions guard the open, and they surface distinct errors. The referenced program version must be `APPROVED`, or the open fails with `ERR_VERSION_NOT_APPROVED`. The lead facilitator must be `ACTIVE` and must list the program's category among their certified categories, or the open fails with `ERR_FACILITATOR_NOT_CERTIFIED`. The cohort's delivery mode must be compatible with the program's delivery mode — a `HYBRID` program accepts a cohort of any mode, whereas a `VIRTUAL` program rejects an `ONSITE` cohort and an `ONSITE` program rejects a `VIRTUAL` cohort — or the open fails with `ERR_DELIVERY_MODE_MISMATCH`. Finally, the logical clock must read strictly before `enroll_deadline`, or the open fails with `ERR_ENROLL_WINDOW_CLOSED`.

Locking a cohort closes enrollment and advances it from `OPEN` to `LOCKED`. The lock requires `expected_cohort_version` and is subject to the optimistic concurrency check of §2.7, returning `ERR_STALE_COHORT_VERSION` (HTTP 412) on a version mismatch. Independently, `seats_confirmed` must be at least the program version's `min_seats`, or the lock is rejected with `ERR_MIN_SEATS_NOT_MET`. The two guards are ordered so that the stale-version check precedes the minimum-seats check: a coordinator acting on an out-of-date seat ledger is told its view is stale (`ERR_STALE_COHORT_VERSION`) before the system evaluates the seat floor against that stale ledger. On a successful lock, the cohort's `version` increments by one, no further enrollment or confirmation is accepted, and a `PROVISIONAL` invoice is emitted as described in §3.6; if the cohort names a contract, the provisional total is reserved against that contract as a soft hold without yet committing it.

Starting a cohort advances it from `LOCKED` to `RUNNING` and requires the logical clock to have reached `starts_at` (the clock must be at or after `starts_at`), failing otherwise with `ERR_BEFORE_START`. Delivering a cohort advances it from `RUNNING` to `DELIVERED` and requires the clock to have reached `ends_at` (at or after `ends_at`), failing otherwise with `ERR_BEFORE_END`. The deliver transition settles attendance: every registration still in `CONFIRMED` with no attendance mark is moved to `NO_SHOW`, and any remaining `CONFIRMED` registration that was marked attended is moved to `ATTENDED`. Closing a cohort advances it from `DELIVERED` to `CLOSED`, computes the `FINAL` invoice over attended seats, draws down the contract if any, and computes the cohort `nps_score` — all detailed in §3.6 and §3.7.

Cancelling a cohort is available from both `OPEN` and `LOCKED` and drives the three-level cascade specified in §2.6, voiding invoices and releasing any contract reservation; the cohort itself moves to `CANCELLED`. The states `CLOSED` and `CANCELLED` are both terminal for a cohort. A reader fetching a cohort sees its derived seat counters and, once it is `CLOSED`, its `nps_score`, which remains null until the cohort closes.

### 3.4. Sessions, Rooms, and Facilitator Assignments

Within a cohort, a `SchedulingCoordinator` lays out the delivery schedule as a set of sessions. Creating a `Session` under a cohort takes a `title`, a `starts_at`, an `ends_at` (which must be after the session's `starts_at`), and a `room_or_url` that is either an onsite room label or a virtual meeting URL. A session must lie entirely within the cohort window — its interval must fall within the cohort's `starts_at` and `ends_at` — or it is rejected with `ERR_SESSION_OUT_OF_RANGE` (HTTP 422). Two sessions of the same cohort that share a `room_or_url` must not overlap, and the interval is treated as closed: even adjacency at a shared boundary instant is rejected, so back-to-back sessions in the same room need a genuine gap between them. A violation yields `ERR_ROOM_CONFLICT`. A session begins in `PLANNED` status and may be recorded as `HELD` or `SKIPPED`.

Co-facilitators are attached to individual sessions. Creating a `SessionAssignment` on a session takes the `facilitator_id` and an optional `role` that is either `LEAD` or `ASSIST`, defaulting to `ASSIST`; each assignment records the `session_id` of the session it belongs to, and assignments may be listed filtered by either `facilitator_id` or `session_id`. An assignment begins `ACTIVE` and may later be `RELEASED`. A single facilitator's `ACTIVE` assignments may not overlap in time: overlap is judged on a half-open interval, so two assignments that merely touch at an endpoint are allowed but any genuine overlap is rejected with `ERR_FACILITATOR_DOUBLE_BOOKED`. The room-conflict rule and the double-booking rule differ deliberately in their boundary treatment — rooms use a closed interval that forbids touching, while facilitator schedules use a half-open interval that permits touching.

### 3.5. Registration, Confirmation, Withdrawal, and the Waitlist

A learner enters a cohort through registration. A `Learner` (or a `SchedulingCoordinator` acting on their behalf) registers by supplying a `learner_email`, unique among the non-terminal registrations of that cohort, and a `learner_name`. At enroll time the system copies the cohort's contract reference onto the registration's `contract_id` (null when the cohort is open-enrollment) and derives the `billing_mode`: `CONTRACT` when the cohort has a contract, otherwise `SELF_PAY`. A registration's `seat_price_cents` is initialized to 0 and is locked later at confirmation time.

Where a new registration lands depends on seat availability, and the system evaluates several guards in priority order. A duplicate `learner_email` already registered (non-terminally) in the cohort is rejected with `ERR_DUPLICATE_REGISTRATION`. Registration is permitted only while the logical clock is before `enroll_deadline`; a later attempt is rejected with `ERR_ENROLL_WINDOW_CLOSED`. If a seat is available — that is, the sum of `seats_reserved` and `seats_confirmed` is below `seat_capacity` — the registration is created in `ENROLLED` state and `seats_reserved` increases by one. If no seat is free, the registration goes to the waitlist instead, provided the waitlist has room (the number of waitlisted registrations is below `waitlist_capacity`), creating a `WAITLISTED` registration and increasing `seats_waitlisted` by one; if seats are full and the waitlist is at capacity, the request is rejected with `ERR_WAITLIST_FULL`. A full seat pool always routes a new registration onto the waitlist path rather than rejecting it outright, so the `ERR_COHORT_FULL` condition is never surfaced as a distinct registration error in practice; exhausted capacity is signalled only as `ERR_WAITLIST_FULL` once the waitlist too has no room. A registration's lifecycle states are `WAITLISTED`, `ENROLLED`, `CONFIRMED`, `ATTENDED`, `NO_SHOW`, `WITHDRAWN`, and `CANCELLED`, of which the last four are terminal.

Confirming a seat moves a registration from `ENROLLED` to `CONFIRMED` and is performed by the `Learner`. Confirmation requires the cohort to be `OPEN`, failing otherwise with `ERR_COHORT_NOT_OPEN`. On confirm, `seats_reserved` decreases by one and `seats_confirmed` increases by one, and the `seat_price_cents` is locked according to the seat-price rule of §3.6.

Withdrawal frees a held seat and is available from both `ENROLLED` and `CONFIRMED`, performed by the `Learner` or a `SchedulingCoordinator`; it requires the cohort to be `OPEN`, failing otherwise with `ERR_COHORT_NOT_OPEN`. Withdrawing an `ENROLLED` registration moves it to `WITHDRAWN` and decreases `seats_reserved` by one; withdrawing a `CONFIRMED` registration moves it to `WITHDRAWN` and decreases `seats_confirmed` by one. In both cases, once the seat is freed the system promotes the earliest `WAITLISTED` registration of that cohort (ordered by `created_at` ascending), if any exists. Promotion is also the automatic path by which a waitlisted registration becomes enrolled: when a seat frees while the cohort is still `OPEN` and the combined reserved-plus-confirmed count is below `seat_capacity`, the earliest waitlisted registration transitions from `WAITLISTED` to `ENROLLED`, decreasing `seats_waitlisted` by one and increasing `seats_reserved` by one.

Marking attendance moves a registration from `CONFIRMED` to `ATTENDED` and is performed by a `Facilitator`; it requires the cohort to be `RUNNING` or `DELIVERED`, failing otherwise with `ERR_COHORT_NOT_RUNNING`. The cohort deliver transition (§3.3) is the system path that converts any unmarked `CONFIRMED` registration into a `NO_SHOW` while leaving the marked ones as `ATTENDED`. Cohort cancellation is the system path that drives any non-terminal registration — whether `ENROLLED`, `CONFIRMED`, or `WAITLISTED` — to `CANCELLED`.

### 3.6. Pricing the Delivery: Seat Price and the Two Invoice Variants

The per-seat charge a learner carries is fixed at confirmation time. When a registration confirms, the system reads the cohort's program version: under `PER_SEAT` pricing the registration's `seat_price_cents` is set to the version's `per_seat_cents`; under `FLAT` pricing it is set to 0, because flat tuition is billed once at the cohort level rather than per seat.

Invoices are computed twice in a cohort's life, and the two computations share a formula but differ in which seats they count. Both variants take pricing and materials figures from the cohort's program version and the travel figure from the cohort's lead facilitator. Tuition under `PER_SEAT` pricing is the version's `per_seat_cents` multiplied by the relevant seat count; under `FLAT` pricing tuition is the version's `flat_fee_cents`, independent of seat count. The materials charge is always the version's `materials_kit_cents` multiplied by the relevant seat count. The travel charge is the lead facilitator's `travel_base_cents` when the cohort's delivery mode is `ONSITE` or `HYBRID`, and 0 otherwise. The invoice's `total_cents` is the sum of `tuition_cents`, `materials_cents`, and `travel_cents`; because every input is integer cents, no rounding occurs.

The `PROVISIONAL` invoice is produced at the lock transition and counts the seats then in `CONFIRMED` state — a snapshot of confirmed seats at lock time. The `FINAL` invoice is produced at the close transition and counts only the seats in `ATTENDED` state, deliberately excluding `NO_SHOW` seats. Each invoice records its `cohort_id`, copies the cohort's contract reference into `contract_id` (null when there is none), and carries the computed `tuition_cents`, `materials_cents`, `travel_cents`, and `total_cents`. The `variant` is `PROVISIONAL` at lock and `FINAL` at close, and the invoice `status` likewise runs `PROVISIONAL`, `FINAL`, or `VOID`. Because the provisional snapshot may include confirmed learners who later fail to attend, the final total can come in below the provisional total — the two differ precisely by the no-show seats.

### 3.7. Closing Out: Contract Draw-Down, NPS, and Settlement

Closing a cohort is where the financial commitment becomes real. The evaluation order is pinned: the `FINAL` invoice total is computed first, over attended seats, and only then drawn against the sponsoring contract. The draw equals the final invoice's `total_cents`. If the draw would exceed the contract's `remaining_cents`, the close is rejected with `ERR_CONTRACT_BUDGET_EXCEEDED`; the comparison is strict, so a draw exactly equal to the remaining budget is allowed. On a successful draw, the contract's `committed_cents` increases by the draw, its `remaining_cents` is recomputed as `budget_cents` minus `committed_cents`, and if the recomputed remaining reaches exactly 0 the contract automatically transitions to `EXHAUSTED`.

The distinction between the lock-time reservation and the close-time commitment matters. At lock, the provisional invoice total is reserved against the contract's available budget — a soft hold that decreases what new cohorts can draw on but leaves `committed_cents` at 0, and that is fully released if the cohort is later cancelled. At close, the final invoice total (over attended seats only) is committed: `committed_cents` rises permanently and exhaustion becomes possible, reversible only through the compensation path of §2.6. Because the reserved figure rides on confirmed seats and the committed figure rides on attended seats, a cohort that reserved budget at lock can still settle under budget at close once no-shows are excluded.

Closing also rolls up learner sentiment. After delivery, a `Learner` whose registration is `ATTENDED` or `NO_SHOW` within a cohort that is `DELIVERED` or `CLOSED` may submit an `Evaluation` carrying an `nps_rating` from 0 through 10 and an optional free-text `comment` (defaulting to empty). A submission from any other registration or cohort state is rejected with `ERR_EVALUATION_NOT_ALLOWED`. Each evaluation copies its `cohort_id` from the submitting registration at submit time; evaluations are append-only and are never status-filtered. At close, the cohort's `nps_score` is computed over all evaluations linked to the cohort. With the ratings collected, promoters are those rated 9 or 10 (a rating of at least 9) and detractors are those rated 6 or below (a rating of at most 6); the score is 100 multiplied by the difference of the promoter count and the detractor count, divided by the number of ratings, rounded half up to a whole integer in the range -100 through 100. When no evaluations exist, the `nps_score` is null rather than 0.

### 3.8. Assessment, Certification, and Revocation

After delivery, a `Facilitator` grades a learner by creating an `Assessment` against a registration. Grading imposes no cohort-state or registration-state precondition: any existing registration may be graded regardless of its lifecycle state or its cohort's state, so the "after delivery" framing is descriptive rather than an enforced guard. The grade supplies a `raw_score` (the points scored, at least 0) and a `max_score` (the maximum possible points, at least 1). The system computes `percent_score` as 100 multiplied by `raw_score`, divided by `max_score`, rounded half up to two decimal places; the rounded value is serialized numerically, so a result with no fractional part is emitted as a whole number (for example 80 rather than 80.00) while a fractional result carries up to two decimal places. The `outcome` is `PASS` when `percent_score` is at least the cohort's program version `pass_threshold_pct` — the comparison is boundary-inclusive, so a percentage exactly equal to the threshold passes — and `FAIL` otherwise. An assessment begins `GRADED` and may later be moved to `VOIDED`, for example when an integrity issue is found.

A certificate recognizes a learner who both attended and passed. A `ProgramDesigner` or `SchedulingCoordinator` issues a `Certificate` for a registration by referencing the passing `assessment_id`. The referenced assessment must belong to that same registration; an `assessment_id` resolving to an assessment of a different registration is rejected with `ERR_INVALID_REFERENCE`. Issuance is permitted only when the registration is `ATTENDED` and the referenced assessment's outcome is `PASS`; otherwise it is rejected with `ERR_NOT_ELIGIBLE_FOR_CERTIFICATE`. On issuance the certificate copies its `registration_id` and `assessment_id`, sets `ceu_awarded` from the program's `ceu_credits` at issuance time, assigns a human-readable `serial` that is monotone within the cohort, and starts in `ISSUED` status. A certificate's only other state is `REVOKED`.

Revoking a certificate is performed by a `ProgramDesigner` and moves it from `ISSUED` to `REVOKED`, removing the `ceu_awarded` from the learner record. Manual revocation is permitted only when the certificate is no longer backed by a clean record — that is, when the linked registration is not `ATTENDED` or the linked assessment has been `VOIDED`. If the registration is still `ATTENDED` and the assessment has not been voided, the certificate is still valid and revocation is rejected with `ERR_CERTIFICATE_STILL_VALID`. Revocation also occurs automatically as level two of the cohort-cancellation cascade (§2.6), in which case the CEU award is likewise removed.

### 3.9. Enterprise Contracts and Their Lifecycle

A `FinanceManager` creates an `EnterpriseContract` for a sponsoring client by supplying a `client_name`, a `budget_cents` (the total contracted budget, never negative), and an optional `is_recurring` boolean (defaulting to false) marking a contract that renews automatically each term. On creation the contract is `ACTIVE` with `committed_cents` at 0 and `remaining_cents` equal to the full `budget_cents`. As cohorts close against it, `committed_cents` accumulates the sum of finalized cohort invoice totals drawn against the contract and `remaining_cents` is kept equal to `budget_cents` minus `committed_cents`. A contract reaches `EXHAUSTED` automatically when committed budget reaches the full budget on a cohort close, and returns to `ACTIVE` automatically when a close is voided or reversed and frees committed budget, as described in §2.6.

A `FinanceManager` closes a contract, moving it from `ACTIVE` to `CLOSED` — the terminal contract state. A close is blocked while any cohort referencing the contract is still in `OPEN`, `LOCKED`, `RUNNING`, or `DELIVERED`; such a request is rejected with `ERR_CONTRACT_HAS_OPEN_COHORTS`.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return a `201 Created` status code. Operations that modify or transition an existing resource, and read operations, return a `200 OK` status code. Every endpoint requires the `X-User-ID` and `X-User-Role` headers described in §2.1, and read (`GET`) operations are available to the roles listed below.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/training/_clock/set_current_utc` | Set the logical clock used for all temporal checks | SchedulingCoordinator, FinanceManager, ProgramDesigner |
| POST | `/training/programs` | Create a catalog or custom program (DRAFT) | ProgramDesigner |
| GET | `/training/programs/{id}` | Get a program | ProgramDesigner, SchedulingCoordinator, FinanceManager |
| GET | `/training/programs` | List programs (paginated) | ProgramDesigner, SchedulingCoordinator, FinanceManager |
| POST | `/training/programs/{id}/retire` | Retire a program | ProgramDesigner |
| POST | `/training/program-versions` | Create a draft program version | ProgramDesigner |
| GET | `/training/program-versions/{id}` | Get a program version | ProgramDesigner, SchedulingCoordinator, FinanceManager |
| GET | `/training/program-versions` | List program versions; filter by program_id | ProgramDesigner, SchedulingCoordinator, FinanceManager |
| POST | `/training/program-versions/{id}/submit` | Submit a draft version for review | ProgramDesigner |
| POST | `/training/program-versions/{id}/request-changes` | Send a version back to DRAFT | ProgramDesigner |
| POST | `/training/program-versions/{id}/approve` | Approve a version; supersedes prior approved | ProgramDesigner |
| POST | `/training/facilitators` | Create a facilitator | SchedulingCoordinator |
| GET | `/training/facilitators/{id}` | Get a facilitator | SchedulingCoordinator, ProgramDesigner, FinanceManager |
| GET | `/training/facilitators` | List facilitators (paginated) | SchedulingCoordinator, ProgramDesigner, FinanceManager |
| POST | `/training/facilitators/{id}/suspend` | Suspend a facilitator | SchedulingCoordinator |
| POST | `/training/contracts` | Create an enterprise contract | FinanceManager |
| GET | `/training/contracts/{id}` | Get a contract | FinanceManager, SchedulingCoordinator |
| GET | `/training/contracts` | List contracts (paginated) | FinanceManager, SchedulingCoordinator |
| POST | `/training/contracts/{id}/close` | Close a contract | FinanceManager |
| POST | `/training/cohorts` | Schedule a cohort for an approved program version | SchedulingCoordinator |
| GET | `/training/cohorts/{id}` | Get a cohort (with derived seat counts) | SchedulingCoordinator, ProgramDesigner, FinanceManager, Learner, Facilitator |
| GET | `/training/cohorts` | List cohorts; filter by contract_id, lead_facilitator_id, program_version_id, status | SchedulingCoordinator, ProgramDesigner, FinanceManager |
| POST | `/training/cohorts/{id}/open` | Open a cohort for enrollment | SchedulingCoordinator |
| POST | `/training/cohorts/{id}/lock` | Lock enrollment; emit PROVISIONAL invoice (OCC-guarded) | SchedulingCoordinator |
| POST | `/training/cohorts/{id}/start` | Start delivery (clock must reach starts_at) | SchedulingCoordinator |
| POST | `/training/cohorts/{id}/deliver` | Mark delivery complete; settle attendance | SchedulingCoordinator |
| POST | `/training/cohorts/{id}/close` | Close cohort; emit FINAL invoice, draw contract, compute NPS | SchedulingCoordinator |
| POST | `/training/cohorts/{id}/cancel` | Cancel a cohort (cascading) | SchedulingCoordinator |
| POST | `/training/cohorts/{id}/sessions` | Add a session to a cohort | SchedulingCoordinator |
| GET | `/training/cohorts/{id}/sessions` | List a cohort's sessions | SchedulingCoordinator, ProgramDesigner, FinanceManager, Facilitator |
| GET | `/training/sessions/{id}` | Get a session | SchedulingCoordinator, ProgramDesigner, FinanceManager, Facilitator |
| POST | `/training/sessions/{id}/assignments` | Assign a co-facilitator to a session | SchedulingCoordinator |
| GET | `/training/sessions/{id}/assignments` | List a session's assignments | SchedulingCoordinator, ProgramDesigner, FinanceManager, Facilitator |
| GET | `/training/assignments` | List session assignments; filter by facilitator_id | SchedulingCoordinator, ProgramDesigner, FinanceManager, Facilitator |
| POST | `/training/cohorts/{id}/registrations` | Register a learner; ENROLLED if seats free else WAITLISTED | Learner, SchedulingCoordinator |
| GET | `/training/cohorts/{id}/registrations` | List a cohort's registrations | SchedulingCoordinator, ProgramDesigner, FinanceManager, Facilitator |
| GET | `/training/registrations/{id}` | Get a registration | SchedulingCoordinator, ProgramDesigner, FinanceManager, Facilitator, Learner |
| GET | `/training/registrations` | List registrations; filter by contract_id, cohort_id, status | SchedulingCoordinator, FinanceManager |
| POST | `/training/registrations/{id}/confirm` | Learner confirms an enrolled seat | Learner |
| POST | `/training/registrations/{id}/withdraw` | Learner withdraws; promotes earliest waitlisted | Learner, SchedulingCoordinator |
| POST | `/training/registrations/{id}/mark-attendance` | Facilitator marks a confirmed learner as attended | Facilitator |
| POST | `/training/registrations/{id}/assessments` | Grade a learner; computes percent_score and PASS/FAIL | Facilitator |
| GET | `/training/registrations/{id}/assessments` | List a registration's assessments | SchedulingCoordinator, ProgramDesigner, FinanceManager, Facilitator, Learner |
| GET | `/training/assessments/{id}` | Get an assessment | SchedulingCoordinator, ProgramDesigner, FinanceManager, Facilitator, Learner |
| POST | `/training/assessments/{id}/void` | Void an assessment | ProgramDesigner, Facilitator |
| POST | `/training/registrations/{id}/certificate` | Issue a CEU certificate for a passed, attended learner | ProgramDesigner, SchedulingCoordinator |
| GET | `/training/registrations/{id}/certificates` | List a registration's certificates | SchedulingCoordinator, ProgramDesigner, FinanceManager, Learner |
| GET | `/training/certificates/{id}` | Get a certificate | SchedulingCoordinator, ProgramDesigner, FinanceManager, Learner |
| GET | `/training/certificates` | List certificates; filter by assessment_id, registration_id, status | SchedulingCoordinator, ProgramDesigner, FinanceManager |
| POST | `/training/certificates/{id}/revoke` | Revoke a certificate | ProgramDesigner |
| GET | `/training/cohorts/{id}/invoices` | List a cohort's invoices | FinanceManager, SchedulingCoordinator |
| GET | `/training/invoices/{id}` | Get an invoice | FinanceManager, SchedulingCoordinator |
| GET | `/training/invoices` | List invoices; filter by contract_id, cohort_id, status | FinanceManager, SchedulingCoordinator |
| POST | `/training/registrations/{id}/evaluation` | Submit a post-delivery NPS evaluation | Learner |
| GET | `/training/registrations/{id}/evaluations` | List a registration's evaluations | SchedulingCoordinator, ProgramDesigner, FinanceManager |
| GET | `/training/evaluations` | List evaluations; filter by cohort_id, registration_id | SchedulingCoordinator, ProgramDesigner, FinanceManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_REFERENCE` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_COHORT_VERSION` | 412 Precondition Failed |
| `ERR_PRICING_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_PROGRAM_RETIRED` | 409 Conflict |
| `ERR_VERSION_NOT_APPROVED` | 409 Conflict |
| `ERR_FACILITATOR_NOT_CERTIFIED` | 409 Conflict |
| `ERR_DELIVERY_MODE_MISMATCH` | 409 Conflict |
| `ERR_ENROLL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_BEFORE_START` | 409 Conflict |
| `ERR_BEFORE_END` | 409 Conflict |
| `ERR_COHORT_FULL` | 409 Conflict |
| `ERR_WAITLIST_FULL` | 409 Conflict |
| `ERR_DUPLICATE_REGISTRATION` | 409 Conflict |
| `ERR_COHORT_NOT_OPEN` | 409 Conflict |
| `ERR_COHORT_NOT_RUNNING` | 409 Conflict |
| `ERR_MIN_SEATS_NOT_MET` | 409 Conflict |
| `ERR_SESSION_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_ROOM_CONFLICT` | 409 Conflict |
| `ERR_FACILITATOR_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_NOT_ELIGIBLE_FOR_CERTIFICATE` | 409 Conflict |
| `ERR_CERTIFICATE_STILL_VALID` | 409 Conflict |
| `ERR_CONTRACT_BUDGET_EXCEEDED` | 409 Conflict |
| `ERR_CONTRACT_HAS_OPEN_COHORTS` | 409 Conflict |
| `ERR_EVALUATION_NOT_ALLOWED` | 409 Conflict |
