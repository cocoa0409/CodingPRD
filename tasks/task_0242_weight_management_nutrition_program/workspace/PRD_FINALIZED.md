# Weight Management & Nutrition Program API — Product Requirements Document

## 1. Introduction

The Weight Management & Nutrition Program API coordinates the full participant journey of a clinically supervised weight-loss program — from the first intake assessment, through plan selection across coaching, prescription, and meal tiers, to weigh-in and biometric tracking, milestone and goal attainment, coach assignment and messaging, recurring billing with HSA/FSA reimbursement classification, and ultimately program graduation. It is built for organizations that must reconcile two ordinarily separate concerns at once: the clinical care pathway (who is medically cleared, who is prescribed medication, who has hit their targets) and the commercial billing pathway (what is owed, what is reimbursable, what is refunded on early exit). These two pathways advance on independent timelines for the same enrollment, and the system must keep each internally consistent without conflating them.

A central design tension addressed here is determinism. Progress calculations, billing periods, milestone achievement, and proration all depend on time, yet the program operates on a deterministic logical clock rather than wall-clock time. Every program owns its own clock, advanced only by explicit administrative action, so that the same sequence of operations always yields the same weigh-in timestamps, billing periods, and prorated credits. Layered on top of this are the program's defining hard problems: two distinct progress metrics computed for the same member from the same weigh-ins, a combinatorial eligibility score that gates reimbursement and prescription, deep cascades when an enrollment ends, conserved-quantity invariants for coach load and member account balances, and optimistic concurrency control on the enrollment aggregate so that concurrent weigh-in and prescription writers cannot silently overwrite one another.

This document specifies the system-wide contracts in Section 2, the business workflows in Section 3, the endpoint surface in Section 4, and the error catalogue in Section 5. Section 2 is precise and binding; Section 3 carries the domain narrative from which the complete request and response behaviour of each endpoint must be reconstructed.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The entire surface is mounted under the `/wm` path prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes exactly five roles, spelled precisely as follows: `ProgramAdmin`, `Clinician`, `BillingAgent`, `Coach`, and `Member`. If either header is missing or invalid, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. Authentication is evaluated before authorization: a missing-header failure always takes precedence over a permission failure.

The relationship between `X-User-ID` and persisted entities differs by role, and this binding is part of the contract. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same is true for `Clinician` and `BillingAgent`: in both cases `X-User-ID` is an opaque operator identifier with no entity backing, although the server may record it where a workflow captures the acting operator — for example, the issuing clinician's identifier is stored as `clinician_user_id` on an `RxAuthorization` at issuance, and a message sender's identifier is stored as `sender_user_id` on a `Message`. By contrast, when `X-User-Role` is `Coach`, `X-User-ID` is the `id` of the acting `Coach` entity, and any ownership check on a resource that references a coach compares that resource's coach foreign key to `X-User-ID`. Likewise, when `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` entity, and ownership checks on resources that reference a member compare the resource's member foreign key to `X-User-ID`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Deterministic Program Clock

Most resources in this system carry a standard set of system-managed fields. Each such resource has an `id`, a unique server-minted UUID with no type prefix; a `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created; an `updated_at`, an ISO 8601 UTC timestamp with three fractional digits recording the last modification; and a `version`, an integer that begins at its initial value and increments by one on every mutation of the resource. These four fields apply to programs, plans, members, coaches, intake assessments, enrollments, goals, milestones, coach assignments, message threads, invoices, eligibility determinations, and Rx authorizations.

Two entity types are append-only event records and deliberately carry **only** `id` and `created_at` — they have neither an `updated_at` nor a `version` field. The first is the weigh-in: once recorded, a weigh-in is never modified. The second is the individual message posted within a thread. For these two, the absence of `updated_at` and `version` is intentional and must be reflected in their responses.

Wall-clock time is never consulted for business logic. Instead, every `Program` owns a deterministic clock exposed as `current_utc`, which is initialized to the Unix epoch instant `1970-01-01T00:00:00.000Z` at program creation. The clock advances only through the administrative clock-setting capability, which writes a supplied instant into `current_utc`; the supplied instant must be greater than or equal to the program's prior `current_utc`, so the clock can hold steady or move forward but can never move backward. Every timestamp the business logic stamps — a weigh-in's `recorded_utc`, an assignment's `assigned_at_utc` and `ended_at_utc`, a message's `posted_utc`, an enrollment's `billing_anchor_utc`, an invoice's period boundaries, a determination's `determined_utc`, a milestone's `achieved_at_utc` — is read from the owning program's `current_utc` at the moment of the operation, not from the host machine's clock.

### 2.5. Hierarchical Consistency, Cascades, and Nested Retrieval

All collections are peers under `/wm`; relationships are expressed through foreign keys carried in request bodies and surfaced through filtered list endpoints rather than through nested URL paths. Path-based retrieval therefore validates a single resource identifier at a time, and when a path identifier does not resolve, the request is rejected with the not-found error specific to that resource type before any further work is attempted. When a request carries multiple identifiers (a path identifier together with body foreign keys), they are validated left-to-right, and the first unresolved identifier determines the rejection. For create operations whose body carries foreign-key identifiers, those identifiers are validated against existing resources in the same program, and an unresolved foreign key yields the not-found error for the referenced type.

The not-found code is specific to the referenced entity type: an unresolved program reference (path or body `program_id`) yields `ERR_PROGRAM_NOT_FOUND`; an unresolved plan reference (path or body `plan_id`) yields `ERR_PLAN_NOT_FOUND`; an unresolved member reference (path or body `member_id`) yields `ERR_MEMBER_NOT_FOUND`; an unresolved coach reference (path or body `coach_id`) yields `ERR_COACH_NOT_FOUND`; an unresolved intake assessment reference (path or body `intake_assessment_id`) yields `ERR_INTAKE_NOT_FOUND`; an unresolved enrollment reference (path or body `enrollment_id`) yields `ERR_ENROLLMENT_NOT_FOUND`; an unresolved goal reference (path or body `goal_id`) yields `ERR_GOAL_NOT_FOUND`; an unresolved milestone reference yields `ERR_MILESTONE_NOT_FOUND`; an unresolved coach-assignment reference (path or body `coach_assignment_id`) yields `ERR_ASSIGNMENT_NOT_FOUND`; an unresolved message-thread reference yields `ERR_THREAD_NOT_FOUND`; an unresolved invoice reference yields `ERR_INVOICE_NOT_FOUND`; an unresolved eligibility-determination reference (path or body `eligibility_determination_id`) yields `ERR_ELIGIBILITY_NOT_FOUND`; and an unresolved Rx-authorization reference yields `ERR_RX_NOT_FOUND`.

When a parent resource undergoes a terminating transition, the system propagates the consequences down the hierarchy automatically, without requiring the client to act on each child. Every such automatic mutation independently advances the affected resource's `version` and refreshes its `updated_at`, exactly as a direct mutation would. The specific cascades — closing goals, voiding milestones, ending coach assignments, archiving threads, and issuing settlement invoices — are described in the enrollment-termination narrative in Section 3. The governing rule is that the state surfaced on any resource always reflects the most recent transition applied to it, whether that transition was client-initiated or system-initiated.

### 2.6. Numeric Precision and Rounding

Several quantities in this system are computed and must follow precise rounding rules. Body Mass Index is rounded to one decimal place using the round-half-up method. All progress percentages — the scale-weight progress, the lean-mass-adjusted progress, and each goal's progress — are rounded to two decimal places using round-half-up. The eligibility composite score is rounded to two decimal places using round-half-up. All monetary amounts are integer cents; where a monetary computation involves division (for example, deriving a daily rate from a monthly fee), the intermediate result is rounded to whole cents using round-half-up **before** any subsequent multiplication, and invoice totals are formed by rounding each line item to whole cents independently and then summing the already-rounded line amounts. Summing raw amounts and rounding once at the end is not permitted.

### 2.7. Optimistic Concurrency Control on the Enrollment Aggregate

The enrollment is the concurrency-controlled aggregate of this system, and exactly two write operations participate in optimistic concurrency control against it. Both require a non-optional input field, `expected_enrollment_version`, carrying the client's last observed `version` of the target `Enrollment`. The check runs after authentication, authorization, and existence checks but before any business logic. If `expected_enrollment_version` does not equal the enrollment's current `version`, the operation is rejected with `ERR_STALE_ENROLLMENT_VERSION` at HTTP status 412, and no state change occurs.

The first guarded operation is recording a weigh-in. Because a counted weigh-in recomputes the member's latest weight and progress metrics, recomputes goal progress, may auto-achieve milestones, and may recompute graduation eligibility — all of which advance the enrollment's `version` — a client holding a stale view of the enrollment must re-read it before posting another weigh-in. If the enrollment's `version` has advanced since the client last read it, the create is rejected with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412), preventing the client from layering a weigh-in on top of an enrollment state it has not observed.

The second guarded operation is issuing an Rx authorization. Issuance advances the enrollment's `version`, so a client that last observed the enrollment before another writer issued an authorization, denied one, or recorded a weigh-in is working from a stale view. Issuance therefore requires `expected_enrollment_version` to match the enrollment's current `version`; on mismatch the request is rejected with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412). No other endpoint accepts or requires a version field; endpoints not named here perform their mutations without any concurrency-version input.

### 2.8. Conserved Quantities: Coach Load and Member Account Balance

Two quantities in this system are invariants that must always equal a derivable truth. A coach's `active_member_count` must at all times equal the number of that coach's coach assignments currently in `ACTIVE` status. An assignment created in `ACTIVE` status increments it by one; an assignment leaving `ACTIVE` for `ENDED` — whether ended directly or as part of an enrollment cascade — decrements it by one. An assignment created and later ended therefore leaves the count exactly where it began.

A member's `account_balance_cents` is a credit ledger denominated in cents, where a positive value represents credit owed back to the member. It begins at zero on registration and changes only through the well-defined credit events described in Section 3 — proration credits on early enrollment exit and reversal credits when a non-initial invoice is voided. The balance is a conserved quantity: every credit added to it corresponds to a specific settlement or reversal event, and no operation silently adjusts it outside those events.

### 2.9. Plan Tiers, Risk Bands, and Clinical Gating

Plans are categorized by `tier`, which is exactly one of `COACHING`, `RX`, or `MEAL`. A plan's `requires_rx` flag is computed as true exactly when its tier is `RX` and false otherwise, and RX-tier plans cannot be clinically activated for an enrollment until a prescription authorization has been issued. Intake assessments carry a computed `risk_band` of `LOW`, `MODERATE`, or `HIGH`. Coaches carry a `specialty` of `GENERAL`, `DIETITIAN`, or `CLINICAL`. These enumerations are fixed; any request supplying a value outside the permitted set for its field is malformed and rejected with `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Founding a Program and Its Catalog

A `ProgramAdmin` establishes a program by supplying a `name` and, optionally, a `description`. At creation the program's deterministic clock `current_utc` is set to the epoch instant, and the program records a `coach_max_active_members` cap that bounds how many active assignments any single coach may simultaneously hold; if the administrator does not supply this cap it defaults to 50. The administrator may later advance the program's logical clock by supplying a target instant via the field `to_iso8601`; the new instant must not predate the current `current_utc`.

Against a program, the administrator builds a catalog of plan offerings. Each plan carries its owning `program_id`, a `tier`, a display `name`, a recurring `monthly_fee_cents` charged each cycle, and an optional one-time `enrollment_fee_cents` charged on the very first invoice (defaulting to 0 when omitted). A plan also carries `hsa_fsa_default_eligible`, an optional flag (defaulting to false) marking whether its recurring fee is presumptively reimbursable ahead of any per-member determination. Both fee fields must be zero or greater. On creation the plan's `requires_rx` is computed from its tier and the plan begins life with `active` set to true. A plan may later be retired, which sets `active` to false; a retired plan rejects new enrollments and cannot be activated, surfacing `ERR_PLAN_RETIRED`.

### 3.2. Registering Members and Coaches

A member is registered — by a `ProgramAdmin`, or by a `Member` registering themselves — with an owning `program_id`, a `full_name`, an `email`, and a `height_cm` that must be strictly greater than zero. The email must be unique within the program when compared case-insensitively; a collision against an existing member in the same program is rejected with `ERR_DUPLICATE_EMAIL`. A newly registered member begins in `REGISTERED` status with `account_balance_cents` of zero. Several of the member's most important fields are not supplied at registration but accrue later as computed values: `baseline_weight_kg` (null until intake approval), `latest_weight_kg` and `latest_lean_mass_kg` (null until the appropriate counted weigh-ins exist), `scale_progress_pct` and `lean_adjusted_progress_pct` (both starting at zero), and the member `status` itself, which the system advances through `REGISTERED`, `INTAKE_PENDING`, `ENROLLED`, and finally `GRADUATED` or `WITHDRAWN`.

A coach is created by a `ProgramAdmin` with an owning `program_id`, a `full_name`, an `email`, an optional `specialty` (defaulting to `GENERAL`), and an optional `accepting` flag (defaulting to true). Coach email is likewise unique within the program case-insensitively, with collisions rejected as `ERR_DUPLICATE_EMAIL`. A coach's `active_member_count` starts at zero. A coach record may be updated — by a `ProgramAdmin` or by the coach themselves — to change `accepting` and `specialty`; setting `accepting` to false suspends new assignments without disturbing existing ones.

### 3.3. The Intake Assessment Lifecycle

Intake is a clinically reviewed cycle that establishes a member's baseline. A `ProgramAdmin` or `Member` creates an assessment for a member by supplying the `member_id`, a reported `weight_kg`, and an optional `comorbidity_count` (defaulting to 0). The new assessment begins in `DRAFT`, its `program_id` is copied from the member, and registering the assessment moves the member to `INTAKE_PENDING`. The assessment also carries `review_notes`, a `revision_round` counter that starts at zero, a computed `bmi`, and a computed `risk_band`.

Submitting an assessment — by a `ProgramAdmin` or `Member` — advances it from `DRAFT` to `SUBMITTED` and may optionally update `weight_kg` and `comorbidity_count`. Submission is permitted only from `DRAFT` (otherwise `ERR_INVALID_STATE`) and requires the reported weight to be strictly greater than zero (otherwise `ERR_INVALID_REQUEST`). On submission the assessment's `bmi` is computed from the assessment's reported weight and the parent member's height: divide the weight in kilograms by the square of the member's height expressed in metres (the height in centimetres divided by 100), and round the result to one decimal place using round-half-up. The `risk_band` is then derived: it is `HIGH` when the BMI is at least 35.0 or the comorbidity count is at least 2; otherwise it is `MODERATE` when the BMI is at least 30.0 or the comorbidity count is exactly 1; otherwise it is `LOW`.

A `Clinician` begins review, advancing the assessment from `SUBMITTED` to `UNDER_REVIEW` (permitted only from `SUBMITTED`, else `ERR_INVALID_STATE`). From `UNDER_REVIEW` the clinician has three exits. The clinician may request a revision, moving the assessment to `NEEDS_REVISION`; this requires non-empty `review_notes` (else `ERR_INVALID_REQUEST`), which are stored on the assessment. The clinician may approve the assessment, moving it from `UNDER_REVIEW` to the terminal `APPROVED` state, whose sole side effect is to copy the assessment's `weight_kg` onto the member as `baseline_weight_kg`. Or the clinician may reject the assessment, moving it from `UNDER_REVIEW` to the terminal `REJECTED` state; rejection, like revision-request, requires non-empty `review_notes`, which are stored. Each of `start-review`, `request-revision`, `approve`, and `reject` is valid only from `UNDER_REVIEW` except start-review, which is valid only from `SUBMITTED`; any attempt from another state is `ERR_INVALID_STATE`.

The revision path is a cycle. From `NEEDS_REVISION`, the member resubmits — the same submit action — returning the assessment to `SUBMITTED`. Resubmission requires the current state to be `NEEDS_REVISION` (else `ERR_INVALID_STATE`) and weight strictly greater than zero (else `ERR_INVALID_REQUEST`). On each resubmission the `revision_round` counter increases by one, and the `bmi` and `risk_band` are recomputed from the possibly updated inputs. An assessment can therefore traverse `NEEDS_REVISION → SUBMITTED → UNDER_REVIEW → NEEDS_REVISION` repeatedly until it terminates in `APPROVED` or `REJECTED`.

### 3.4. Enrollment, Clinical Activation, and the First Invoice

A `ProgramAdmin` creates an enrollment by supplying a `member_id`, a `plan_id`, an `intake_assessment_id`, and an optional `cycle_length_days` (defaulting to 30, and constrained to the inclusive range 1 through 90). The enrollment's `program_id` is copied from the member. A new enrollment begins with parallel statuses: `clinical_status` of `PENDING_CLINICAL` and `billing_status` of `UNBILLED`, with `cycles_billed` at zero and `graduation_eligible` false. The referenced intake assessment must belong to the same member named by `member_id`, or the create is rejected with `ERR_INTAKE_MEMBER_MISMATCH`; and the chosen plan must be active, or the create is rejected with `ERR_PLAN_RETIRED`.

The two status dimensions evolve independently. `clinical_status` tracks the care pathway (`PENDING_CLINICAL → ACTIVE → GRADUATED` or `WITHDRAWN`); `billing_status` tracks the commercial pathway (`UNBILLED → CURRENT → PAST_DUE` or `CLOSED`). A change to one dimension does not, by itself, move the other except where a transition explicitly states so.

Clinical activation is performed by a `ProgramAdmin` and is the system's most heavily gated transition. It is permitted only when `clinical_status` is `PENDING_CLINICAL` (else `ERR_INVALID_STATE`). The referenced intake assessment must be in `APPROVED` status (else `ERR_INTAKE_NOT_APPROVED`). If the chosen plan's tier is `RX`, there must exist an `RxAuthorization` for this enrollment in `ISSUED` status (else `ERR_RX_AUTHORIZATION_REQUIRED`). And the plan must still be active (else `ERR_PLAN_RETIRED`). When all gates pass, activation advances `clinical_status` to `ACTIVE`, sets the member's `status` to `ENROLLED`, stamps `billing_anchor_utc` from the program's `current_utc`, automatically advances `billing_status` from `UNBILLED` to `CURRENT`, and generates the cycle-0 invoice with `cycles_billed` becoming 1.

The cycle-0 invoice carries the recurring fee and, when applicable, the enrollment fee. Its total is formed line by line: a `RECURRING_FEE` line equal to the plan's `monthly_fee_cents` rounded to whole cents; and, only on this first invoice (cycle index 0) and only when the plan's enrollment fee is greater than zero, an additional `ENROLLMENT_FEE` line equal to the plan's `enrollment_fee_cents` rounded to whole cents. The `subtotal_cents` is the sum of these already-rounded line amounts. This is the provisional, full-cycle billing variant: the full monthly fee is charged for the entire cycle ahead, regardless of how many days are actually used — a forward-looking charge that the proration logic later reconciles if the cycle ends early.

### 3.5. Recurring Billing and the Invoice Lifecycle

A `BillingAgent` generates each subsequent recurring invoice for an enrollment. A new invoice takes its `cycle_index` from the enrollment's current `cycles_billed` count, and generating it increments `cycles_billed` by one. Each invoice records a half-open period: `period_start_utc` inclusive and `period_end_utc` exclusive, where the end equals the start plus `cycle_length_days`. A new cycle's half-open period must not overlap the period of any existing non-void invoice for the enrollment; periods that merely touch at the shared boundary instant are adjacent and allowed, but any genuine overlap is rejected with `ERR_BILLING_PERIOD_OVERLAP`. The recurring invoice's `line_items` again carry a single `RECURRING_FEE` line at the plan's monthly fee rounded to whole cents, with no enrollment-fee line because that applies only to cycle 0; the `subtotal_cents` is the rounded line total.

Each invoice also exposes `hsa_fsa_eligible_cents`, the reimbursable portion of its subtotal, and a `prorated` flag (defaulting to false) that is true only when the invoice carries a proration credit line from early exit. An invoice begins in `ISSUED` status and moves to either `PAID` or `VOID`. Paying an invoice is a `BillingAgent` action requiring the invoice to be in `ISSUED` status (else `ERR_INVOICE_NOT_ISSUED`); it sets the invoice to `PAID`, and if the enrollment's `billing_status` was `PAST_DUE`, paying restores it to `CURRENT`. Voiding an invoice is also a `BillingAgent` action requiring `ISSUED` status (else `ERR_INVOICE_NOT_ISSUED`), and additionally requires the invoice's `cycle_index` to be greater than zero — the cycle-0 enrollment invoice is immutable and any attempt to void it is rejected with `ERR_CANNOT_VOID_INITIAL_INVOICE`. A successful void adds the invoice's `subtotal_cents` back to the member's `account_balance_cents` as a reversal credit and decrements the enrollment's `cycles_billed` by one.

The billing dimension also has a past-due path. A `BillingAgent` may mark an enrollment's billing past due against a target invoice; this requires the enrollment's `billing_status` to be `CURRENT` (else `ERR_INVALID_STATE`) and the target invoice to be in `ISSUED` status (else `ERR_INVOICE_NOT_ISSUED`), and it advances `billing_status` from `CURRENT` to `PAST_DUE` while leaving `clinical_status` untouched, since the two dimensions are parallel. The complementary recovery occurs when a `BillingAgent` pays the outstanding invoice, which returns `billing_status` from `PAST_DUE` to `CURRENT`.

### 3.6. Weigh-Ins, Progress Metrics, and Goal Attainment

Weigh-ins are append-only records of a member's weight over time, recorded by a `ProgramAdmin`, `Coach`, or `Member`. A weigh-in is created against an `enrollment_id` with a `weight_kg` strictly greater than zero, an optional `body_fat_pct` in the inclusive range 0 through 70, an optional `counts` flag (defaulting to true), and the mandatory `expected_enrollment_version` described under optimistic concurrency. The weigh-in copies its `member_id` from the enrollment, stamps `recorded_utc` from the program's clock, and — when `body_fat_pct` is supplied — computes `lean_mass_kg` as the weight multiplied by one minus the body-fat fraction (the percent divided by 100), rounded to two decimal places using round-half-up; when no body fat is supplied, `lean_mass_kg` is null. When `counts` is false the weigh-in is retained for the audit trail but excluded from every baseline, latest-weight, progress, and graduation computation.

A counted weigh-in refreshes the member's derived figures and bumps the enrollment's `version`. The member's `latest_weight_kg` becomes the weight of the most recent counted weigh-in, and `latest_lean_mass_kg` becomes the lean mass of the most recent counted weigh-in that carried a body-fat reading (null otherwise). From these the member's two progress metrics are recomputed — the same member, the same baseline, but two deliberately different algorithms that generally yield different numbers.

The first metric, **scale-weight progress** (`scale_progress_pct`), credits raw scale-weight loss and ignores body composition entirely. It is zero whenever the member's baseline weight or latest weight is still null. Otherwise, let the weight lost be the baseline weight minus the latest weight, and let the nominal target band be the baseline weight multiplied by 0.10 (a ten-percent-of-body-weight goal band). The metric is the weight lost divided by that target band, multiplied by 100, clamped to the range 0 through 100, and rounded to two decimal places using round-half-up.

The second metric, **lean-mass-adjusted progress** (`lean_adjusted_progress_pct`), credits only fat-mass loss rather than total scale loss, and therefore diverges from the scale metric for the same member. It is zero whenever the member's baseline weight or latest lean mass is null. Otherwise, the baseline lean mass is taken as the baseline weight multiplied by one minus an assumed baseline body-fat fraction of 0.30. The fat lost is computed as the baseline fat mass (baseline weight minus baseline lean mass) minus the latest fat mass (latest weight minus latest lean mass). The denominator is again the baseline weight multiplied by 0.10. The metric is the fat lost divided by that denominator, multiplied by 100, clamped to the range 0 through 100, and rounded to two decimal places using round-half-up.

Goals capture concrete targets. A `ProgramAdmin` or `Coach` creates a goal against an `enrollment_id` with a `kind` of either `PRIMARY` or `SECONDARY` and a `target_weight_kg`. The goal copies its `member_id` from the enrollment and begins `OPEN` with `progress_pct` zero. The target weight must be strictly greater than zero and strictly below the member's `baseline_weight_kg`; if the baseline is null or the target is not strictly below it, the create is rejected with `ERR_TARGET_NOT_BELOW_BASELINE`. A goal's `progress_pct` is zero while the member's latest weight is null; otherwise let the span be the baseline weight minus the target weight (always positive by the target validation) and the weight lost be the baseline weight minus the member's latest weight, and the progress is the weight lost divided by the span, multiplied by 100, clamped to 0 through 100, and rounded to two decimal places using round-half-up. When a goal's progress reaches at least 100.0 — exactly 100 is enough — after a counted weigh-in, the goal automatically transitions from `OPEN` to `ACHIEVED`. That achievement transitions every still-pending milestone of the goal whose threshold is at most 100 to `ACHIEVED`, and when the achieved goal's kind is `PRIMARY` it recomputes the enrollment's graduation eligibility.

### 3.7. Milestones

Milestones mark fractional progress toward a goal. A `ProgramAdmin` or `Coach` defines a milestone against a `goal_id` with a `threshold_pct` that must be one of 25, 50, 75, or 100; any other value is `ERR_INVALID_REQUEST`. The milestone copies its `enrollment_id` from the goal and begins `PENDING`, with `achieved_at_utc` and `achieved_weight_kg` null. A pending milestone automatically transitions to `ACHIEVED` when its owning goal's progress reaches at least its `threshold_pct` — the comparison is inclusive, so reaching the threshold exactly is sufficient — following a counted weigh-in. On achievement the milestone stamps `achieved_at_utc` from the program clock and snapshots `achieved_weight_kg` from the member's current latest weight. A milestone may also be voided rather than achieved: when its owning goal is closed as part of an enrollment-ending cascade, the still-pending milestone transitions to `VOIDED`.

### 3.8. Coaching Assignment, Capacity, and Messaging

A `ProgramAdmin` assigns a coach to an enrollment by supplying the `enrollment_id` and `coach_id`. The assignment copies its `member_id` from the enrollment, stamps `assigned_at_utc` from the program clock, begins in `ACTIVE` status with `ended_at_utc` null, and increments the coach's `active_member_count` by one. Two guards protect this operation. An enrollment may carry at most one active assignment at a time, so assigning a coach to an enrollment that already has an active assignment is rejected with `ERR_ENROLLMENT_ALREADY_ASSIGNED`. And the assignment must not push the coach's active load above the program's cap: if accepting the assignment would make the coach's `active_member_count` strictly greater than the program's `coach_max_active_members`, it is rejected with `ERR_COACH_CAPACITY_EXCEEDED`.

Ending an assignment is performed by a `ProgramAdmin`, or by the system as part of an enrollment cascade. It requires the assignment to be `ACTIVE` (else `ERR_INVALID_STATE`), and it transitions the assignment from `ACTIVE` to `ENDED`, stamps `ended_at_utc` from the program clock, decrements the coach's `active_member_count` by one, and archives the assignment's still-open message threads.

Messaging runs over an assignment. A `ProgramAdmin`, `Coach`, or `Member` opens a thread on a coach assignment by supplying the `coach_assignment_id` and a `subject`. The thread copies its `enrollment_id` from the assignment, begins `OPEN` with `message_count` zero, and may later be archived — by a `ProgramAdmin` or `Coach`, or automatically when the owning assignment ends — moving it from `OPEN` to `ARCHIVED` (a direct archive requires the thread to be `OPEN`, else `ERR_INVALID_STATE`). A `Coach` or `Member` posts a message to a thread by supplying a `body` of 1 to 4000 characters; the message takes its `message_thread_id` from the thread it is posted under, records its `sender_role` (`MEMBER` or `COACH`, derived from the caller's role) and `sender_user_id` from the caller, stamps `posted_utc` from the program clock, and increments the thread's `message_count` by one. Messages may be listed for a given thread by filtering on that `message_thread_id`. Posting is permitted only when the owning coach assignment is `ACTIVE` and the thread is `OPEN`; otherwise it is rejected with `ERR_THREAD_NOT_OPEN`, and a body outside the 1-to-4000 character range is `ERR_INVALID_REQUEST`.

### 3.9. Eligibility Determination and HSA/FSA Classification

Reimbursement eligibility is established per enrollment. A `ProgramAdmin` or `Clinician` creates a determination by supplying the `member_id` and the `enrollment_id` whose plan eligibility is being assessed; the determination copies its `program_id` from the member, begins `PENDING` with `determined_utc` null and `hsa_fsa_eligible` false, and computes a `composite_score` at creation.

The composite score combines three contributions, rounded together to two decimal places using round-half-up at the end. The BMI contribution starts from the member's approved-intake BMI: subtract a base of 25.0 from the BMI, take whichever is larger of that difference and zero, multiply by a per-point weight of 4, and cap the result at 40. The comorbidity contribution multiplies the member's approved-intake comorbidity count by a weight of 15 and caps the result at 30. The tier contribution is 20 when the enrollment's plan tier is `RX`, 10 when it is `COACHING`, and 5 otherwise (that is, for `MEAL`). The composite score is the sum of these three contributions.

A `Clinician` resolves a pending determination. Approval requires the composite score to be at least the eligibility threshold of 35 (else `ERR_ELIGIBILITY_SCORE_BELOW_THRESHOLD`); a successful approval moves the determination to `APPROVED`, sets `hsa_fsa_eligible` to true, and stamps `determined_utc` from the program clock. Denial is always permitted from `PENDING`; it moves the determination to `DENIED`, sets `hsa_fsa_eligible` to false, and stamps `determined_utc`. Both transitions are valid only from `PENDING`, else `ERR_INVALID_STATE`.

An approved, eligible determination governs how much of each of the enrollment's invoices is reimbursable. When no approved determination with eligibility flagged true exists for the enrollment, an invoice's `hsa_fsa_eligible_cents` is zero. When such a determination does exist, the reimbursable amount is the sum of the invoice's `RECURRING_FEE` line amounts plus the sum of its `PRORATION_CREDIT` line amounts (which are negative), with the final figure floored at zero so it can never go negative. Enrollment-fee lines are never reimbursable and are excluded from this computation.

### 3.10. Prescription Authorization

Prescription authorization is the clinical gate for RX-tier plans. A `ProgramAdmin` or `Clinician` requests an authorization by supplying the `enrollment_id` and the `eligibility_determination_id` it rests on; the authorization copies its `member_id` from the enrollment and begins in `REQUESTED` status with `qualifying_bmi` null. A clinician then resolves it.

Issuing an authorization moves it from `REQUESTED` to `ISSUED` and is the more demanding transition. It is permitted only from `REQUESTED` (else `ERR_INVALID_STATE`). It is optimistic-concurrency-controlled: the request carries `expected_enrollment_version`, which must equal the enrollment's current `version`, or the request is rejected with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412). The referenced eligibility determination must be `APPROVED` (else `ERR_ELIGIBILITY_NOT_APPROVED`). And the member must clear the BMI gate: the member's BMI must be at least 30.0, or at least 27.0 provided the member's approved intake records a comorbidity count of at least 1; failing both, the request is rejected with `ERR_BMI_BELOW_RX_THRESHOLD`. A successful issuance snapshots the qualifying BMI into `qualifying_bmi`, records the issuing clinician's identifier into `clinician_user_id`, and advances the enrollment's `version` by one.

Denying an authorization moves it from `REQUESTED` to `DENIED` and is permitted only from `REQUESTED` (else `ERR_INVALID_STATE`). Revoking an authorization moves it from `ISSUED` to `REVOKED` and is permitted only from `ISSUED` (else `ERR_INVALID_STATE`); revocation additionally requires that the authorization's enrollment is not clinically `ACTIVE`, because an active RX enrollment relies on its issued authorization — attempting to revoke under an active enrollment is rejected with `ERR_ENROLLMENT_ACTIVE_RX_LOCKED`.

### 3.11. Graduation, Withdrawal, and the Settlement Cascade

Two transitions terminate the clinical pathway of an active enrollment, and both are `ProgramAdmin` actions that fan out into a cascade.

Graduation requires the enrollment's `clinical_status` to be `ACTIVE` (else `ERR_INVALID_STATE`) and the enrollment to be graduation-eligible (else `ERR_GRADUATION_CRITERIA_NOT_MET`). An enrollment is graduation-eligible exactly when at least one `PRIMARY` goal has reached `ACHIEVED` status and the enrollment has at least three counted weigh-ins (weigh-ins recorded with `counts` true). On graduation, `clinical_status` becomes `GRADUATED` and the member's `status` becomes `GRADUATED`. The cascade then runs in order: every `OPEN` goal of the enrollment transitions to `CLOSED`; each such goal-closure voids that goal's still-`PENDING` milestones; the goal-closure step then ends every `ACTIVE` coach assignment of the enrollment (each ending decrements the relevant coach's `active_member_count` by one); and each coach-assignment ending archives that assignment's still-`OPEN` message threads. Finally, a settlement invoice is issued: if the current cycle is unfinished, it carries a `PRORATION_CREDIT` line, the proration credit is added to the member's `account_balance_cents`, and the enrollment's `billing_status` becomes `CLOSED`.

Withdrawal from an `ACTIVE` enrollment requires `clinical_status` to be `ACTIVE` (else `ERR_INVALID_STATE`); unlike graduation it imposes no eligibility criterion. It sets `clinical_status` to `WITHDRAWN` and the member's `status` to `WITHDRAWN`, then runs the same cascade: every `OPEN` goal becomes `CLOSED`, each closure voids that goal's still-`PENDING` milestones, every `ACTIVE` coach assignment becomes `ENDED` (decrementing the coach's `active_member_count`), and the affected assignments' `OPEN` message threads are archived. A final settlement invoice with a `PRORATION_CREDIT` line for the unused days is issued, the proration credit is added to the member's `account_balance_cents` as a refund, and `billing_status` becomes `CLOSED`.

An enrollment that is still only `PENDING_CLINICAL` may also be withdrawn directly; this requires `clinical_status` to be `PENDING_CLINICAL` (else `ERR_INVALID_STATE`). Because no invoice was ever issued for such an enrollment (its `cycles_billed` is zero), there is no proration, no refund, and no change to `account_balance_cents` — it simply moves `clinical_status` to `WITHDRAWN`, sets the member's `status` to `WITHDRAWN`, and moves `billing_status` to `CLOSED`.

The proration credit on an early exit is computed chronologically against the current issued invoice's period. The elapsed days are the difference between the program's `current_utc` and the invoice's `period_start_utc`, divided by the number of seconds in a day (86400) and floored to a whole number of days, then clamped to the range 0 through `cycle_length_days`. The unused days are `cycle_length_days` minus the elapsed days. The daily rate is the plan's `monthly_fee_cents` divided by `cycle_length_days`, rounded to whole cents using round-half-up before any multiplication. The proration credit is that rounded daily rate multiplied by the unused days, and it is added to the member's `account_balance_cents`. The settlement invoice carries this as a `PRORATION_CREDIT` line whose amount is the negative of the credit, and the invoice's `prorated` flag is true. This final, day-counted proration variant deliberately differs from the provisional full-cycle charge taken at activation and at each recurring cycle: the provisional variant charges the whole monthly fee forward, while the final variant credits back only the unused whole days at the rounded daily rate.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions and updates — return a `200 OK` status code, with the single exception of generating the next recurring invoice, which creates a new Invoice resource and therefore returns `201 Created`. The full request payload and side effects of each operation are specified in the Section 3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/wm/programs` | Create a program | ProgramAdmin |
| GET | `/wm/programs` | List programs | ProgramAdmin, Clinician, BillingAgent, Coach, Member |
| GET | `/wm/programs/{programId}` | Get a program | ProgramAdmin, Clinician, BillingAgent, Coach, Member |
| POST | `/wm/programs/{programId}/clock-set` | Set the deterministic program clock | ProgramAdmin |
| POST | `/wm/plans` | Create a plan catalog item | ProgramAdmin |
| GET | `/wm/plans` | List plans (filter by program/tier) | ProgramAdmin, Clinician, BillingAgent, Coach, Member |
| GET | `/wm/plans/{planId}` | Get a plan | ProgramAdmin, Clinician, BillingAgent, Coach, Member |
| POST | `/wm/plans/{planId}/retire` | Retire a plan | ProgramAdmin |
| POST | `/wm/members` | Register a member | ProgramAdmin, Member |
| GET | `/wm/members` | List members (filter by program/status) | ProgramAdmin, Clinician, BillingAgent, Coach |
| GET | `/wm/members/{memberId}` | Get a member | ProgramAdmin, Clinician, BillingAgent, Coach, Member |
| POST | `/wm/coaches` | Create a coach | ProgramAdmin |
| GET | `/wm/coaches` | List coaches (filter by program) | ProgramAdmin, Clinician, BillingAgent, Coach, Member |
| GET | `/wm/coaches/{coachId}` | Get a coach | ProgramAdmin, Clinician, BillingAgent, Coach, Member |
| PATCH | `/wm/coaches/{coachId}` | Update coach accepting / specialty | ProgramAdmin, Coach |
| POST | `/wm/intake-assessments` | Create a DRAFT intake assessment | ProgramAdmin, Member |
| GET | `/wm/intake-assessments` | List intake assessments (filter by member/program/status) | ProgramAdmin, Clinician, Member |
| GET | `/wm/intake-assessments/{assessmentId}` | Get an intake assessment | ProgramAdmin, Clinician, Member |
| POST | `/wm/intake-assessments/{assessmentId}/submit` | Submit / resubmit an assessment | ProgramAdmin, Member |
| POST | `/wm/intake-assessments/{assessmentId}/start-review` | Begin clinical review | Clinician |
| POST | `/wm/intake-assessments/{assessmentId}/request-revision` | Request a revision | Clinician |
| POST | `/wm/intake-assessments/{assessmentId}/approve` | Approve intake | Clinician |
| POST | `/wm/intake-assessments/{assessmentId}/reject` | Reject intake | Clinician |
| POST | `/wm/enrollments` | Create a PENDING_CLINICAL enrollment | ProgramAdmin |
| GET | `/wm/enrollments` | List enrollments (filter by member/program/plan/intake/status) | ProgramAdmin, Clinician, BillingAgent, Coach, Member |
| GET | `/wm/enrollments/{enrollmentId}` | Get an enrollment | ProgramAdmin, Clinician, BillingAgent, Coach, Member |
| POST | `/wm/enrollments/{enrollmentId}/activate` | Clinically activate; issue cycle-0 invoice | ProgramAdmin |
| POST | `/wm/enrollments/{enrollmentId}/bill-next-cycle` | Generate the next recurring invoice | BillingAgent |
| POST | `/wm/enrollments/{enrollmentId}/graduate` | Graduate the program (cascade) | ProgramAdmin |
| POST | `/wm/enrollments/{enrollmentId}/withdraw` | Withdraw (cascade + refund) | ProgramAdmin |
| POST | `/wm/weigh-ins` | Record a weigh-in | ProgramAdmin, Coach, Member |
| GET | `/wm/weigh-ins` | List weigh-ins (filter by enrollment/member/counts) | ProgramAdmin, Clinician, Coach, Member |
| GET | `/wm/weigh-ins/{weighInId}` | Get a weigh-in | ProgramAdmin, Clinician, Coach, Member |
| POST | `/wm/goals` | Create a goal | ProgramAdmin, Coach |
| GET | `/wm/goals` | List goals (filter by enrollment/member/kind/status) | ProgramAdmin, Clinician, Coach, Member |
| GET | `/wm/goals/{goalId}` | Get a goal | ProgramAdmin, Clinician, Coach, Member |
| POST | `/wm/milestones` | Define a milestone on a goal | ProgramAdmin, Coach |
| GET | `/wm/milestones` | List milestones (filter by goal/enrollment/status) | ProgramAdmin, Clinician, Coach, Member |
| GET | `/wm/milestones/{milestoneId}` | Get a milestone | ProgramAdmin, Clinician, Coach, Member |
| POST | `/wm/coach-assignments` | Assign a coach to an enrollment | ProgramAdmin |
| GET | `/wm/coach-assignments` | List coach assignments (filter by coach/enrollment/member/status) | ProgramAdmin, Clinician, Coach, Member |
| GET | `/wm/coach-assignments/{assignmentId}` | Get a coach assignment | ProgramAdmin, Clinician, Coach, Member |
| POST | `/wm/coach-assignments/{assignmentId}/end` | End an assignment | ProgramAdmin |
| POST | `/wm/message-threads` | Open a message thread on an assignment | ProgramAdmin, Coach, Member |
| GET | `/wm/message-threads` | List threads (filter by assignment/enrollment/status) | ProgramAdmin, Clinician, Coach, Member |
| GET | `/wm/message-threads/{threadId}` | Get a message thread | ProgramAdmin, Clinician, Coach, Member |
| POST | `/wm/message-threads/{threadId}/archive` | Archive a thread | ProgramAdmin, Coach |
| POST | `/wm/message-threads/{threadId}/messages` | Post a message | Coach, Member |
| GET | `/wm/messages` | List messages (filter by thread) | ProgramAdmin, Clinician, Coach, Member |
| GET | `/wm/messages/{messageId}` | Get a message | ProgramAdmin, Clinician, Coach, Member |
| GET | `/wm/invoices` | List invoices (filter by enrollment/member/status) | ProgramAdmin, BillingAgent, Member |
| GET | `/wm/invoices/{invoiceId}` | Get an invoice | ProgramAdmin, BillingAgent, Member |
| POST | `/wm/invoices/{invoiceId}/pay` | Mark an invoice paid | BillingAgent |
| POST | `/wm/invoices/{invoiceId}/mark-past-due` | Mark enrollment billing past due | BillingAgent |
| POST | `/wm/invoices/{invoiceId}/void` | Void a non-initial invoice | BillingAgent |
| POST | `/wm/eligibility-determinations` | Create a PENDING eligibility determination | ProgramAdmin, Clinician |
| GET | `/wm/eligibility-determinations` | List determinations (filter by member/program/enrollment/status) | ProgramAdmin, Clinician, BillingAgent, Member |
| GET | `/wm/eligibility-determinations/{determinationId}` | Get a determination | ProgramAdmin, Clinician, BillingAgent, Member |
| POST | `/wm/eligibility-determinations/{determinationId}/approve` | Approve determination | Clinician |
| POST | `/wm/eligibility-determinations/{determinationId}/deny` | Deny determination | Clinician |
| POST | `/wm/rx-authorizations` | Request an Rx authorization | ProgramAdmin, Clinician |
| GET | `/wm/rx-authorizations` | List Rx authorizations (filter by enrollment/member/determination/status) | ProgramAdmin, Clinician, Member |
| GET | `/wm/rx-authorizations/{rxId}` | Get an Rx authorization | ProgramAdmin, Clinician, Member |
| POST | `/wm/rx-authorizations/{rxId}/issue` | Issue an Rx authorization (BMI gate, OCC) | Clinician |
| POST | `/wm/rx-authorizations/{rxId}/deny` | Deny an Rx authorization | Clinician |
| POST | `/wm/rx-authorizations/{rxId}/revoke` | Revoke an issued Rx authorization | Clinician |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 Unauthorized |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_COACH_NOT_FOUND` | 404 Not Found |
| `ERR_INTAKE_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_GOAL_NOT_FOUND` | 404 Not Found |
| `ERR_MILESTONE_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_THREAD_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_ELIGIBILITY_NOT_FOUND` | 404 Not Found |
| `ERR_RX_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_STALE_ENROLLMENT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVOICE_NOT_ISSUED` | 409 Conflict |
| `ERR_CANNOT_VOID_INITIAL_INVOICE` | 409 Conflict |
| `ERR_INTAKE_MEMBER_MISMATCH` | 409 Conflict |
| `ERR_INTAKE_NOT_APPROVED` | 409 Conflict |
| `ERR_TARGET_NOT_BELOW_BASELINE` | 409 Conflict |
| `ERR_PLAN_RETIRED` | 409 Conflict |
| `ERR_ENROLLMENT_ALREADY_ASSIGNED` | 409 Conflict |
| `ERR_COACH_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_BILLING_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_THREAD_NOT_OPEN` | 409 Conflict |
| `ERR_RX_AUTHORIZATION_REQUIRED` | 409 Conflict |
| `ERR_ELIGIBILITY_NOT_APPROVED` | 409 Conflict |
| `ERR_BMI_BELOW_RX_THRESHOLD` | 409 Conflict |
| `ERR_ELIGIBILITY_SCORE_BELOW_THRESHOLD` | 409 Conflict |
| `ERR_GRADUATION_CRITERIA_NOT_MET` | 409 Conflict |
| `ERR_ENROLLMENT_ACTIVE_RX_LOCKED` | 409 Conflict |
