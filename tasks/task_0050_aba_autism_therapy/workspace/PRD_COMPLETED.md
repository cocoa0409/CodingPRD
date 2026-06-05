# ABA Autism Therapy API — Product Requirements Document

## 1. Introduction

Applied Behavior Analysis (ABA) is the dominant evidence-based intervention for children on the autism spectrum, but the operational machinery behind it is unforgiving: a child cannot receive therapy until a Board Certified Behavior Analyst has evaluated them, a treatment plan has been approved, and an insurance payer has pre-authorized a finite pool of fifteen-minute service units. Every hour of therapy a technician delivers must draw down against that authorized pool, must be supervised at a contracted ratio, and must eventually be billed and reconciled against what the payer actually allows. When any link in that chain is mishandled — units over-consumed, supervision under-delivered, a claim double-submitted — the provider absorbs the loss and the family's continuity of care is put at risk.

This document specifies the REST API that governs the full ABA reimbursement lifecycle: diagnostic evaluation, treatment planning, unit-hour pre-authorization, therapist scheduling under BCBA supervision ratios, parent training, the insurance reimbursement cycle, and authorization renewal with carry-forward of unconsumed units. The system is built around a small set of peer entities — clients, payers, providers, evaluations, plans, authorizations, sessions, and claims — linked by foreign keys rather than deep nesting. Its hardest guarantees are quota allocation (an authorization's unit pools must always balance) and ledger reconciliation (provisional billing at scheduling time must reconcile against final delivered-unit billing). The sections that follow define the global contract first, then the scattered business rules that an implementation must satisfy, and finally the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which they are acting. If either header is missing, or if `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly five roles, spelled precisely as follows: `IntakeCoordinator`, `BCBA`, `RBT`, `BillingSpecialist`, and `Caregiver`. When a request carries valid headers but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `BCBA`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on any resource that references a `Provider` compare the resource's provider foreign-key field to `X-User-ID`. When `X-User-Role` is `RBT`, `X-User-ID` is likewise the `id` of the acting `Provider`; for an `RBT`, ownership comparisons against a resource's provider foreign key use that same `X-User-ID`. When `X-User-Role` is `IntakeCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `BillingSpecialist`, `X-User-ID` is similarly an opaque operator identifier not tied to any persisted entity, recorded but never matched against an entity `id`. When `X-User-Role` is `Caregiver`, `X-User-ID` is an opaque guardian identifier not tied to any persisted entity's primary `id`; a caregiver's read visibility into a child's record is governed by the per-endpoint authorization matrix rather than by matching `X-User-ID` to a stored key.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip before collecting the page; when omitted it defaults to 0 and is constrained to a minimum of 0. A `limit` or `offset` that is not a parseable integer, or that falls outside its permitted range, is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list response includes the following fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Request Validation Order

All primary resources — `Client`, `Payer`, `Provider`, `DiagnosticEvaluation`, `TreatmentPlan`, `Authorization`, `TherapySession`, and `Claim` — carry a standard set of system-managed fields. Every resource has an `id`, a server-minted UUID with no type prefix. Every resource has a `created_at`, an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. Because all eight of these entities are full mutable resources, each also carries an `updated_at` (an ISO 8601 UTC timestamp refreshed on every mutation) and a `version` (an integer that begins at creation and increments by one on every mutation, used for optimistic concurrency control). Whenever a computed field on a resource changes — for example, the recomputation of an authorization's pool ledger or supervision posture — that recomputation is itself a mutation: it refreshes `updated_at` and increments `version`.

Requests are validated in a fixed precedence so that the most fundamental failures surface first regardless of what else is wrong. Authentication is checked first: absent or invalid `X-User-ID` / `X-User-Role` headers yield `ERR_UNAUTHENTICATED`. Body well-formedness is checked next on every mutating endpoint — the body must be valid JSON (and must itself be a JSON object), every required input field must be present and of the correct type (a required string field must be a non-empty string of at most 500 characters, and booleans are never accepted where a string, integer, or number is required), a foreign-key reference must be a non-empty string, and every enumerated or numeric value must fall within its declared range (for instance `assessment_score` between 0 and 180 inclusive, `coinsurance_pct` between 0 and 1 inclusive, and `scheduled_units` at least 1); any violation yields `ERR_VALIDATION`. Role authorization is checked next: a role not permitted for the operation yields `ERR_UNAUTHORIZED`. Existence is checked next: every path and body foreign-key resource must exist, validated left-to-right in the order they appear, with the first missing one yielding `ERR_NOT_FOUND`. Only after these four gates do resource-ownership, state, and the domain-specific business rules described throughout §3 apply.

### 2.5. Nested and Referential Resource Resolution

Although the URL surface is flat — resources live at top-level collections such as the authorization and therapy-session collections rather than under deep parent paths — most write operations reference other resources by foreign key in their body. When a request names several foreign keys, the server resolves them left-to-right in the order listed for that operation and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. This left-to-right discipline is the same one applied to path identifiers: the resource named in the URL path is resolved before any body references are examined.

### 2.6. Optimistic Concurrency on Authorization Renewal

Renewing an authorization is the one operation in this system that is guarded by optimistic concurrency control. The renew operation requires an `expected_authorization_version` field in its body, carrying the client's last observed `version` of the target `Authorization`. The server compares that value against the authorization's current `version`. If they do not match — because some other writer has advanced the authorization's version since the client last read it — the renewal is rejected with `ERR_STALE_VERSION` and HTTP status 412. This guard exists precisely because a renewal supersedes its predecessor and carries the predecessor's unconsumed units into a successor; if a stale renewal were allowed through after the authorization had already been renewed, the successor pool would be double-issued. No other endpoint takes a version field, and no other mutating operation performs this check.

### 2.7. The Unit-Pool Quota Principle

The economic heart of the system is the authorized unit pool. Each `Authorization` carries three independently authorized pools — direct-therapy units in `authorized_direct_units`, BCBA supervision units in `authorized_supervision_units`, and parent-training units in `authorized_parent_training_units` — each measured in fifteen-minute service units. Against each pool the system tracks two computed accumulators per service line: a reserved figure (`reserved_direct_units`, `reserved_supervision_units`, `reserved_parent_training_units`) holding units committed by sessions that are still merely scheduled, and a delivered figure (`delivered_direct_units`, `delivered_supervision_units`, `delivered_parent_training_units`) holding units committed by sessions that have been rendered. For the direct-therapy line specifically, the system also exposes `remaining_direct_units`, which is the authorized direct pool minus the reserved direct units minus the delivered direct units. The invariant the system upholds at all times is that, for the direct line, reserved plus delivered plus remaining always equals the authorized direct pool. Sessions that end in no-show or cancellation contribute to neither the reserved nor the delivered figure.

### 2.8. Monetary Precision and Rounding

All monetary amounts in the system — a payer's contracted allowed amount, a claim's billed, allowed, patient-responsibility, and payer-paid figures — are integer cents. Where a calculation multiplies a whole number of units by a per-unit rate the result is exact and no rounding is required. Where a calculation takes a fraction of an amount — specifically the patient's coinsurance share of an allowed amount — the result is rounded to the nearest whole cent using the round-half-up convention (a value exactly halfway between two cents rounds up). The rounding is applied to the patient's share, and the payer's share is then computed as the remainder, so the two always sum back to the allowed amount without drift.

### 2.9. Cascading Recomputation and State Propagation

Many operations in this system mutate more than one resource. A single therapy-session transition can adjust the owning authorization's reserved and delivered accumulators, recompute its `remaining_direct_units`, recompute its `supervision_status`, and as a consequence flip the authorization's own `status` between `ACTIVE` and `EXHAUSTED`. Approving a treatment plan can bubble a status change up to the client. Closing an authorization can cascade cancellations down to its scheduled sessions. In every such case the rule is the same: each resource the operation touches is independently mutated, which refreshes its `updated_at` and increments its `version`. These propagations are computed atomically within the request that triggers them, so a reader observing any resource after the request sees a fully reconciled picture rather than a half-applied one.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Clients, Payers, and Providers

The intake workflow begins with reference data. An `IntakeCoordinator` (or, for payers, a `BillingSpecialist`) registers an insurance `Payer` by supplying its plan `name`, its contracted `allowed_rate_cents` (the allowed amount per fifteen-minute unit, in cents), its `coinsurance_pct` (the family's fractional share of the allowed amount, which must lie between 0 and 1 inclusive), and its `supervision_ratio_pct` (the minimum BCBA supervision expressed as a fraction of delivered direct-therapy units, which must be greater than 0 and at most 1). A payer record can be read back by intake, billing, and BCBA staff.

An `IntakeCoordinator` then registers a `Client` — the child — by supplying `full_name`, `date_of_birth` (an ISO date in `YYYY-MM-DD` form), `caregiver_user_id` (the opaque identifier of the guardian who acts as the `Caregiver` for this child), and `insurance_payer_id` (a reference to the child's insurance payer). A newly created client enters `INTAKE` status. A client's `status` advances to `ACTIVE` automatically the first time a treatment plan for that child is approved, and an intake coordinator may later move a client to `DISCHARGED` through the discharge capability. Clients can be listed and optionally filtered by `insurance_payer_id`; a single client record is readable by intake, BCBA, billing, and the child's caregiver.

Providers are also onboarded by an `IntakeCoordinator`. Each `Provider` is created with a `full_name`, a `credential` that is either `BCBA` or `RBT`, an `npi` (National Provider Identifier), and — for a technician — an optional `supervising_bcba_id` naming the BCBA who supervises them (a BCBA leaves this null). A provider begins in `ACTIVE` status and may later be moved to `INACTIVE` through the deactivate capability. The credential distinction is load-bearing throughout the system: a `BCBA` supervises and bills supervision and parent training, while an `RBT` delivers direct therapy. Providers can be listed and optionally filtered by `supervising_bcba_id`.

### 3.2. Diagnostic Evaluation and Severity Scoring

A child's clinical journey opens with a `DiagnosticEvaluation`, which only a `BCBA` may create. Creation supplies the `client_id` of the evaluated child, the `evaluator_bcba_id` of the BCBA performing the evaluation, and an `assessment_score` — a composite severity score from the diagnostic instrument that must fall between 0 and 180 inclusive. The evaluation is born in `DRAFT`.

Submitting an evaluation advances it from `DRAFT` to `SUBMITTED`, and only the provider identified as the `evaluator_bcba_id` may do so; an attempt by anyone else is rejected with `ERR_NOT_RESOURCE_OWNER`. The submission is where severity is computed. The system reads the `assessment_score` and assigns a `severity_level` together with a `recommended_weekly_units` figure on tiered, inclusive lower-bound thresholds: a score of 120 or more yields a `SEVERE` severity with 160 recommended weekly units (forty hours per week); a score of at least 60 but below 120 yields a `MODERATE` severity with 100 recommended weekly units (twenty-five hours per week); and any score below 60 yields a `MILD` severity with 40 recommended weekly units (ten hours per week). Both computed fields are written onto the evaluation at submission time.

Review of a submitted evaluation belongs to an `IntakeCoordinator`, who supplies a `decision`. A decision of `FINALIZE` moves the evaluation from `SUBMITTED` to `FINALIZED`, after which it becomes eligible to back a treatment plan; a decision of `REJECT` moves it from `SUBMITTED` to `REJECTED` with no further effect. Both `FINALIZED` and `REJECTED` are terminal. Evaluations can be listed and optionally filtered by `client_id` or `evaluator_bcba_id`, and a single evaluation is readable by BCBA and intake staff.

### 3.3. Treatment Planning and the Revision Loop

With a finalized evaluation in hand, a `BCBA` authors a `TreatmentPlan`, providing the `client_id` the plan covers, the `evaluation_id` of the finalized evaluation backing it, the `author_bcba_id` of the authoring BCBA, and three requested quantities: `requested_direct_units` (which must be at least 1), `requested_supervision_units` (at least 0), and `requested_parent_training_units` (at least 0). The plan starts in `DRAFT`.

Submitting a plan moves it from `DRAFT` to `SUBMITTED`, and the act is gated twice. First, only the provider named as the `author_bcba_id` may submit; otherwise the request is rejected with `ERR_NOT_RESOURCE_OWNER`. Second, the backing evaluation must already be `FINALIZED`; if it is in any other state the submission is rejected with `ERR_EVALUATION_NOT_FINALIZED`. Reviewing a submitted plan is the `IntakeCoordinator`'s responsibility and is driven by a `decision`. A decision of `APPROVE` moves the plan from `SUBMITTED` to `APPROVED`; as a side effect, if the covered client is still in `INTAKE`, the client's status bubbles up to `ACTIVE`, and any prior `APPROVED` plan for the same client is retired. A decision of `REQUEST_REVISION` moves the plan from `SUBMITTED` to `REVISION_REQUESTED`.

The revision loop lets a plan recover from a revision request: a plan in `REVISION_REQUESTED` may be resubmitted by its author, returning it to `SUBMITTED`, where it can again be approved or sent back for revision. A plan thus may cycle `SUBMITTED → REVISION_REQUESTED → SUBMITTED` any number of times. A plan reaches the terminal `RETIRED` state when a newer approved plan exists for the same client and supersedes it; retirement is performed by the system rather than requested directly. Plans can be listed and optionally filtered by `client_id`, `evaluation_id`, or `author_bcba_id`, and are readable by BCBA, intake, and billing staff.

### 3.4. Pre-Authorization: Funding the Unit Pools

Once a plan is approved, a `BillingSpecialist` creates an `Authorization` to fund it. Creation references the `treatment_plan_id` of the plan and the `payer_id` of the authorizing payer, and it sets the three authorized pools — `authorized_direct_units`, `authorized_supervision_units`, and `authorized_parent_training_units`, each at least 0 — along with the window dates `period_start` and `period_end` (inclusive ISO dates bounding the authorization). Creation validates only that the referenced `treatment_plan_id` and `payer_id` resolve to existing records (left-to-right, plan then payer); the plan's `status` is not re-checked at this step, so although the intended workflow funds an `APPROVED` plan, an authorization may in fact be created against a referenced plan in any state without a dedicated rejection. A new authorization is born `ACTIVE`, with all reserved and delivered accumulators at zero and `remaining_direct_units` equal to the authorized direct pool; its `superseded_by_id` is null until it is renewed.

An authorization's `status` reflects the live state of its pools. While direct units remain available it is `ACTIVE`. The moment the pool ledger recomputes and the direct pool is fully consumed — that is, reserved direct units plus delivered direct units equal the authorized direct pool, leaving `remaining_direct_units` at zero — the authorization flips from `ACTIVE` to `EXHAUSTED`, and any new direct-therapy session attempted against it is rejected with `ERR_UNITS_EXCEEDED`. Conversely, when a recompute frees reserved units so that remaining direct units rise above zero again, an `EXHAUSTED` authorization flips back to `ACTIVE`. Authorizations can be listed and optionally filtered by `treatment_plan_id`, `payer_id`, or `superseded_by_id`, and are readable by billing, BCBA, and intake staff with their computed pool ledger and supervision posture included.

Closing an authorization is a `BillingSpecialist` action that expires it. Close is defined only from the `ACTIVE` state; if the target authorization is in any other state (`EXHAUSTED`, `EXPIRED`, or `RENEWED`) the close is rejected with `ERR_INVALID_STATE`, and this state check is evaluated before the clock-date check. Only when the authorization is `ACTIVE` is the close permitted, and then only when the server's current clock date is strictly after `period_end`; if the window has not yet elapsed the close is rejected with `ERR_AUTHORIZATION_NOT_EXPIRABLE`. A successful close moves the authorization from `ACTIVE` to `EXPIRED` and cascades through its still-scheduled sessions, cancelling each one and freeing the reservation those sessions held; the resulting pool-ledger and supervision-posture recomputation runs against the now-`EXPIRED` authorization and does not flip it back to `ACTIVE` or `EXHAUSTED` even though freed reservations raise `remaining_direct_units`, since `EXPIRED` is terminal. For deterministic time-gated testing, an authorized operator may set the server's current UTC clock by supplying a `to_iso8601` instant; this clock drives both the close check and the session-window check described below.

### 3.5. Authorization Renewal and Carry-Forward

Renewal extends coverage when an authorization is running low, and it is the system's optimistic-concurrency-protected operation. A `BillingSpecialist` initiates a renewal against an `ACTIVE` authorization, supplying `expected_authorization_version` (the version they last observed, which must be an integer), new pool figures `authorized_direct_units`, `authorized_supervision_units`, and `authorized_parent_training_units` (each at least 0), and a fresh `period_start` and `period_end`. The `ACTIVE`-state precondition is checked before the version is compared: if the target authorization is not `ACTIVE` (for example because it has already been renewed and is now in the terminal `RENEWED` state), the renewal is rejected with `ERR_INVALID_STATE` regardless of the supplied `expected_authorization_version`. Only when the authorization is `ACTIVE` is the version examined, and if `expected_authorization_version` then does not match the predecessor's current `version`, the renewal is rejected with `ERR_STALE_VERSION` — a guard against a second renewal double-issuing the successor pool after another writer has already renewed.

When the version matches, the system creates a successor `Authorization`. The successor's direct pool is the sum of the direct units supplied in the renewal body plus the predecessor's `remaining_direct_units`, so unconsumed direct units carry forward rather than being lost; the supervision and parent-training pools of the successor are taken from the renewal body verbatim, with no carry-forward. The predecessor's `superseded_by_id` is set to the successor's `id`, the predecessor moves from `ACTIVE` to the terminal `RENEWED` state, and the predecessor's `version` increments by one. Both `EXPIRED` and `RENEWED` are terminal states from which no further transition is possible.

### 3.6. Scheduling Therapy Sessions

Therapy is delivered through a `TherapySession`, which either an `RBT` or a `BCBA` may schedule. Scheduling supplies the `authorization_id` whose pool the session draws from, the `provider_id` of the therapist, a `service_line` of `DIRECT_THERAPY`, `SUPERVISION`, or `PARENT_TRAINING`, the `scheduled_start` and `scheduled_end` (ISO 8601 UTC instants, with the interval treated as the half-open range from start up to but not including end), and `scheduled_units` (the fifteen-minute units reserved at scheduling, at least 1; eight units, for instance, is two hours). The session is created `SCHEDULED`, its `scheduled_units` are added to the owning authorization's reserved accumulator for that service line, the direct remaining figure is recomputed, and the authorization may flip to `EXHAUSTED` if the direct pool reaches zero.

Scheduling is the most heavily guarded operation in the system, and its checks live alongside the safety and quota rules they enforce. The provider's `credential` must match the `service_line`: direct therapy must be scheduled to an `RBT`, while supervision and parent training must be scheduled to a `BCBA`; a mismatch is rejected with `ERR_CREDENTIAL_MISMATCH`. The session date must fall within the authorization window — the date of `scheduled_start` must be on or after `period_start` and on or before `period_end` — or the request is rejected with `ERR_OUTSIDE_AUTH_WINDOW`. The therapist must be free: if the provider already has a `SCHEDULED` or `DELIVERED` session whose interval overlaps the new half-open `[scheduled_start, scheduled_end)` interval, the request is rejected with `ERR_PROVIDER_DOUBLE_BOOKED`. The child must also be free with a margin: if the client has any `SCHEDULED` or `DELIVERED` session within fifteen minutes of the new interval (a buffered overlap extending the new interval by a quarter hour on each side and testing that buffered interval for half-open overlap against the existing session), the request is rejected with `ERR_CLIENT_BUFFER_CONFLICT`. The buffer boundary is itself half-open: a session that begins exactly fifteen minutes after an existing session ends (or ends exactly fifteen minutes before one begins) does not conflict and is accepted. Finally, scheduling must not push the reserved-plus-delivered total above the authorized pool for the session's service line; an attempt to over-commit the pool is rejected with `ERR_UNITS_EXCEEDED`.

Sessions can be listed and optionally filtered by `authorization_id` or `provider_id`, and a single session is readable by RBT, BCBA, and billing staff.

### 3.7. Delivering, No-Showing, and Cancelling Sessions

Marking a session `DELIVERED` is how units move from merely reserved to committed, and either a `BCBA` or an `RBT` may perform it. The deliver request supplies `delivered_units`, the actual units rendered (which must be present and an integer, else `ERR_VALIDATION`). The domain checks then apply in a fixed order: the session must be in `SCHEDULED` (otherwise `ERR_INVALID_STATE`); the owning authorization must be `ACTIVE` or `EXHAUSTED`, and if it has been expired or renewed delivery is rejected with `ERR_AUTHORIZATION_NOT_ACTIVE`; `delivered_units` must be greater than zero and no greater than the session's `scheduled_units`, and a value outside that range is rejected with `ERR_DELIVERED_UNITS_INVALID`; and for a `SUPERVISION` session specifically, the acting provider's credential must be `BCBA`, or the deliver is rejected with `ERR_CREDENTIAL_MISMATCH`. (The authorization-active check is thus evaluated before the delivered-units range check.)

On a successful delivery the session moves from `SCHEDULED` to `DELIVERED` and the pool ledger synchronizes: the session's `scheduled_units` are removed from the authorization's reserved accumulator for that service line, and its `delivered_units` are added to the delivered accumulator for that line. Because reserved drops by the full scheduled amount while delivered rises only by the actual amount, the difference between what was scheduled and what was delivered returns to the remaining pool whenever fewer units were rendered than reserved. Delivery also recomputes the authorization's supervision posture, and if the pools are now fully consumed the authorization flips from `ACTIVE` to `EXHAUSTED`.

A scheduled session that does not occur is closed out as either a no-show or a cancellation, both of which an `RBT` or `BCBA` may record and both of which release the held reservation. Marking a session `NO_SHOW` moves it from `SCHEDULED` to `NO_SHOW`, and cancelling moves it from `SCHEDULED` to `CANCELLED`; in either case the session's reserved units for its service line are released back to remaining, and if the owning authorization had been `EXHAUSTED` and now has remaining units available, it flips from `EXHAUSTED` back to `ACTIVE`. All three of `DELIVERED`, `NO_SHOW`, and `CANCELLED` are terminal.

### 3.8. Supervision Posture

A core compliance obligation of ABA is that a BCBA must supervise a contracted fraction of the direct therapy a technician delivers, and the system tracks this continuously as the authorization's `supervision_status`, which is either `COMPLIANT` or `DEFICIENT`. The required supervision is computed against delivered direct work: the system takes the authorization's `delivered_direct_units`, multiplies by the payer's `supervision_ratio_pct`, and rounds that product up to the next whole unit to obtain the required supervision units. If the authorization's `delivered_supervision_units` is greater than or equal to that required figure, the supervision status is `COMPLIANT`; otherwise it is `DEFICIENT`. The comparison is inclusive at the boundary — meeting the required figure exactly is compliant. This posture is recomputed every time a session is delivered against the authorization, and it is read again at claim adjudication as the gate on payment.

### 3.9. The Billing and Reimbursement Cycle

Billing begins once a session has been delivered. A `BillingSpecialist` creates a `Claim` for a session by supplying its `session_id`; the claim may only be created for a session whose status is `DELIVERED`, otherwise it is rejected with `ERR_SESSION_NOT_DELIVERED`. At most one claim may be live for a given session: if another claim for the same `session_id` already exists in a `SUBMITTED` or `PAID` state, both claim creation and claim submission are rejected with `ERR_DUPLICATE_CLAIM` (a `DENIED` or still-`DRAFT` claim does not block a new one). On creation the claim is `DRAFT`, its `payer_id` is copied from the session's authorization payer, and its `billed_cents` is set to a provisional amount.

The billed figure is computed from a per-service-line rate: direct therapy bills at 3200 cents per unit, supervision at 4800 cents per unit, and parent training at 2400 cents per unit. The provisional billed amount set at claim creation is the session's `scheduled_units` multiplied by that line's rate — the reserved estimate. When a `BillingSpecialist` submits the claim, moving it from `DRAFT` to `SUBMITTED`, `billed_cents` is refinalized to the session's `delivered_units` multiplied by that line's rate — the actuals. The provisional and final figures diverge precisely when fewer units were delivered than were scheduled. Claims can be listed and optionally filtered by `session_id` or `payer_id`, and are readable by billing and BCBA staff.

Adjudication settles a submitted claim and is a `BillingSpecialist` action driven by a `decision`. A decision of `PAY` is gated on supervision: the owning authorization's `supervision_status` must be `COMPLIANT`, or the payment is rejected with `ERR_SUPERVISION_DEFICIENT`. On payment the claim moves from `SUBMITTED` to `PAID` and the remittance is computed: `allowed_cents` is the session's `delivered_units` multiplied by the payer's `allowed_rate_cents`; `patient_responsibility_cents` is that allowed amount multiplied by the payer's `coinsurance_pct`, rounded half up to whole cents; and `payer_paid_cents` is the allowed amount minus the patient responsibility. A decision of `DENY` moves the claim from `SUBMITTED` to `DENIED`, sets the `denial_reason` from the body (one of `NONE`, `NOT_AUTHORIZED`, `SUPERVISION_DEFICIENT`, or `DUPLICATE`, where `NONE` is the default carried on a fresh claim), and zeroes the money fields so that `allowed_cents`, `patient_responsibility_cents`, and `payer_paid_cents` are all zero. The `denial_reason` field is optional on a `DENY` request: when it is omitted (or null) the denial records the default `NONE`. The `denial_reason` field is read only for `DENY`; any value supplied alongside a `PAY` decision is ignored, and a `decision` value other than `PAY` or `DENY` is rejected with `ERR_VALIDATION`. Both `PAID` and `DENIED` are terminal.

### 3.10. State, Ownership, and the Order of Domain Checks

Across every state-changing operation in §3, a transition is only attempted from a state in which it is defined; a request to drive a transition that the resource's current state does not permit is rejected with `ERR_INVALID_STATE`. This applies uniformly to evaluation submit and review, plan submit and review, session deliver, no-show, and cancel, claim submit and adjudicate, and authorization close and renew. Where an operation is owner-gated — evaluation submit and treatment-plan submit — the resource-ownership check (`ERR_NOT_RESOURCE_OWNER`) is the gate that the acting provider be the resource's evaluator or author. The domain-specific business checks layered on top of these — finalized-evaluation backing, credential matching, the authorization window, double-booking, the client buffer, delivered-unit validity, the active-authorization requirement, pool sufficiency, supervision compliance, duplicate claims, delivered-session requirement, and authorization expirability — each guard the specific workflow described in the subsections above, and each carries the dedicated error identifier named there.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code; this includes creating a payer, client, provider, evaluation, plan, authorization, therapy session, or claim, and creating the successor authorization produced by a renewal. All other operations — reads, list retrievals, state transitions on an existing resource, and the clock-setting capability — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock for time-gated checks | BillingSpecialist, IntakeCoordinator |
| POST | `/payers` | Create an insurance Payer | IntakeCoordinator, BillingSpecialist |
| GET | `/payers/{id}` | Get a Payer | IntakeCoordinator, BillingSpecialist, BCBA |
| POST | `/clients` | Create a Client in INTAKE status | IntakeCoordinator |
| GET | `/clients/{id}` | Get a Client | IntakeCoordinator, BCBA, BillingSpecialist, Caregiver |
| GET | `/clients` | List Clients, optionally filtered by payer | IntakeCoordinator, BCBA, BillingSpecialist |
| POST | `/clients/{id}/discharge` | Discharge a Client | IntakeCoordinator |
| POST | `/providers` | Create a Provider (BCBA or RBT) | IntakeCoordinator |
| GET | `/providers/{id}` | Get a Provider | IntakeCoordinator, BCBA, RBT, BillingSpecialist |
| POST | `/providers/{id}/deactivate` | Deactivate a Provider | IntakeCoordinator |
| GET | `/providers` | List Providers, optionally filtered by supervising BCBA | IntakeCoordinator, BCBA, BillingSpecialist |
| POST | `/diagnostic-evaluations` | Create a DiagnosticEvaluation in DRAFT | BCBA |
| GET | `/diagnostic-evaluations/{id}` | Get a DiagnosticEvaluation | BCBA, IntakeCoordinator |
| GET | `/diagnostic-evaluations` | List DiagnosticEvaluations | BCBA, IntakeCoordinator |
| POST | `/diagnostic-evaluations/{id}/submit` | Submit an evaluation for review | BCBA |
| POST | `/diagnostic-evaluations/{id}/review` | Finalize or reject a submitted evaluation | IntakeCoordinator |
| POST | `/treatment-plans` | Create a TreatmentPlan in DRAFT | BCBA |
| GET | `/treatment-plans/{id}` | Get a TreatmentPlan | BCBA, IntakeCoordinator, BillingSpecialist |
| GET | `/treatment-plans` | List TreatmentPlans | BCBA, IntakeCoordinator, BillingSpecialist |
| POST | `/treatment-plans/{id}/submit` | Submit or resubmit a TreatmentPlan | BCBA |
| POST | `/treatment-plans/{id}/review` | Approve or request revision of a plan | IntakeCoordinator |
| POST | `/authorizations` | Create an Authorization for a treatment plan (plan status not re-checked) | BillingSpecialist |
| GET | `/authorizations/{id}` | Get an Authorization with pool ledger | BillingSpecialist, BCBA, IntakeCoordinator |
| GET | `/authorizations` | List Authorizations | BillingSpecialist, BCBA, IntakeCoordinator |
| POST | `/authorizations/{id}/renew` | Renew an Authorization (OCC-guarded) | BillingSpecialist |
| POST | `/authorizations/{id}/close` | Close (expire) an Authorization past its window | BillingSpecialist |
| POST | `/therapy-sessions` | Schedule a TherapySession, reserving units | RBT, BCBA |
| GET | `/therapy-sessions/{id}` | Get a TherapySession | RBT, BCBA, BillingSpecialist |
| GET | `/therapy-sessions` | List TherapySessions | RBT, BCBA, BillingSpecialist |
| POST | `/therapy-sessions/{id}/deliver` | Mark a session DELIVERED with actual units | BCBA, RBT |
| POST | `/therapy-sessions/{id}/no-show` | Mark a session NO_SHOW, releasing its reservation | RBT, BCBA |
| POST | `/therapy-sessions/{id}/cancel` | Cancel a scheduled session, releasing its reservation | RBT, BCBA |
| POST | `/claims` | Create a DRAFT Claim for a DELIVERED session | BillingSpecialist |
| GET | `/claims/{id}` | Get a Claim | BillingSpecialist, BCBA |
| GET | `/claims` | List Claims | BillingSpecialist, BCBA |
| POST | `/claims/{id}/submit` | Submit a Claim, finalizing billed_cents | BillingSpecialist |
| POST | `/claims/{id}/adjudicate` | Adjudicate a submitted Claim (pay or deny) | BillingSpecialist |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_EVALUATION_NOT_FINALIZED` | 409 |
| `ERR_CREDENTIAL_MISMATCH` | 409 |
| `ERR_OUTSIDE_AUTH_WINDOW` | 409 |
| `ERR_PROVIDER_DOUBLE_BOOKED` | 409 |
| `ERR_CLIENT_BUFFER_CONFLICT` | 409 |
| `ERR_DELIVERED_UNITS_INVALID` | 422 |
| `ERR_UNITS_EXCEEDED` | 409 |
| `ERR_AUTHORIZATION_NOT_ACTIVE` | 409 |
| `ERR_SUPERVISION_DEFICIENT` | 409 |
| `ERR_DUPLICATE_CLAIM` | 409 |
| `ERR_SESSION_NOT_DELIVERED` | 409 |
| `ERR_AUTHORIZATION_NOT_EXPIRABLE` | 409 |
| `ERR_STALE_VERSION` | 412 |
