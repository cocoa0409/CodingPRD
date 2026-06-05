# Special Education IEP API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Special Education Individualized Education Program (IEP) Management API. The system supports the full federal special-education workflow as it unfolds for a single student: an initial eligibility evaluation, the annual IEP meeting and its placement decision, ongoing tracking of measurable goal progress, the delivery of related services such as occupational therapy, physical therapy, and speech-language services, parental consent at every gating step, computation of the student's least-restrictive-environment placement, the triennial reevaluation cycle, and transition planning for older students.

The domain is fundamentally a compliance-and-audit problem layered over a multi-party negotiation. Several distinct actors — district administrators, special-education teachers, school psychologists, and the parent or guardian — each hold a narrow, legally meaningful authority, and the system must keep them properly separated. A teacher who convenes a meeting cannot also be the administrator who activates the resulting program; an evaluator who decides eligibility cannot also turn that program on; and only a parent may grant, deny, or withdraw consent. Because evaluations, programs, and consents advance independently and may be revised in cycles, the system must reconcile derived state immediately and reject any write that is working from a stale view of the data it depends on. The sections below define the global contracts that every endpoint honours, the business logic that governs each lifecycle, the endpoint surface, and the catalogue of error identifiers.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the capacity in which that user is acting. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

The system recognizes exactly four roles, spelled precisely as follows: `SpecialEdAdmin`, `CaseManager`, `Evaluator`, and `Parent`. The `SpecialEdAdmin` is the district special-education administrator who registers students and activates or archives programs. The `CaseManager` is the special-education teacher who authors programs, opens evaluations, manages goals and related services, and convenes meetings. The `Evaluator` is the school psychologist who begins and finalizes eligibility evaluations. The `Parent` is the student's parent or guardian and is the only role that may decide or revoke consent. When a request carries a recognized role but that role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

All four roles use an **opaque** identity model. For each of `SpecialEdAdmin`, `CaseManager`, `Evaluator`, and `Parent`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity and is never compared to any entity's `id`. The server may, however, record a user identifier where a workflow step calls for it — for example, it records the requesting `CaseManager`'s `X-User-ID` when an evaluation is opened and the convening `CaseManager`'s `X-User-ID` when a meeting is held — and later uses those recorded identifiers solely to enforce segregation of duties, never as an ownership key.

Segregation of duties is itself a guard the system enforces on two operations. When an administrator activates a program, the activating `SpecialEdAdmin`'s `X-User-ID` must not equal the `X-User-ID` of the `CaseManager` recorded as having convened that program's meeting. When an evaluator finalizes an evaluation, the finalizing `Evaluator`'s `X-User-ID` must not equal the `X-User-ID` of the `CaseManager` recorded as having requested that evaluation. A violation of either rule is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. The consent-request listing is sorted by creation timestamp ascending and then by `id` ascending as a stable tiebreaker.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of system-managed fields:

- **`id`** — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- **`updated_at`** — an ISO 8601 UTC timestamp, with three fractional digits, indicating when the resource was last modified; it is refreshed on every mutation of the resource.
- **`version`** — a system-managed integer that begins at its initial value and increments by one with every modification of the resource. It is the value used for optimistic concurrency control where the workflow demands it.

These four properties are carried by `Student`, `Evaluation`, `IEP`, `Goal`, `RelatedService`, `ConsentRequest`, and `TransitionPlan`. The `ProgressReport` resource is the single exception: it is immutable after creation and therefore carries only `id` and `created_at`. A progress report has neither an `updated_at` field nor a `version` field; do not emit those fields for it.

Whenever a derived field on a resource is recomputed — for example a student's eligibility status after an evaluation finalizes, or a program's least-restrictive-environment percentage after a service is added — that recomputation is itself a mutation of the owning resource: it refreshes that resource's `updated_at` and increments its `version` by one.

### 2.5. Hierarchical Consistency and Cascades

The system maintains immediate consistency across the relationships that bind students, evaluations, programs, goals, services, consents, and transition plans. A change to a child or related resource that affects a parent's derived state is reflected on the parent in the same operation, and a change to a parent that invalidates its children is propagated down to them in the same operation. Each entity affected by such a cascade is independently mutated — its `updated_at` is refreshed and its `version` is incremented.

Three cascades are central to the domain. First, finalizing an evaluation recomputes several derived fields on the owning student and bumps the student's version. Second, withdrawing a previously granted placement consent on a program that is currently turned on forces that program back into a revision state and clears the student's pointer to its active program. Third, archiving an active program terminates every goal and every related service still attached to it that remains active. These cascades are described in full in the workflow subsections of Section 3; the principle here is that the system performs them automatically, without requiring a separate client request against each affected resource.

### 2.6. Nested Resource Retrieval and Referential Integrity

The API resolves the identifiers named in a request path from left to right. When a path names a resource that does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404); when several identifiers appear, the first one that fails to resolve is the one that produces the rejection. This existence check on path-named resources is evaluated before any business rule.

Separately, several create operations carry foreign-key references in the request body — a `student_id`, an `iep_id`, or a `goal_id`. When such a body field names a resource that does not exist, the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 404).

### 2.7. Precision and Rounding

Every derived numeric quantity in the system — composite eligibility scores, provisional and cumulative goal progress percentages, and the least-restrictive-environment percentage — is rounded to exactly two decimal places using the round-half-up method, and is stored and returned pinned to two decimals. Internal calculations should be performed with decimal arithmetic to avoid floating-point drift. Where a calculation pins a specific order of rounding (rounding individual contributions before combining them), that order is stated with the calculation in Section 3 and must be honoured exactly, because rounding then combining can differ from combining then rounding.

### 2.8. Validation Order

When more than one validation could apply to a request, the checks are evaluated in a fixed priority order, and the first failure determines the error returned. Authentication comes first: the presence and validity of the `X-User-Role` and `X-User-ID` headers is checked before anything else (`ERR_UNAUTHENTICATED`), then the acting role's permission to perform the operation (`ERR_FORBIDDEN`), and then — on the two operations that bear it — segregation of duties (`ERR_SEGREGATION_OF_DUTIES`). After authentication and authorization, existence of every resource named in the path is checked (`ERR_NOT_FOUND`), followed by the existence of every foreign key referenced in the body (`ERR_FK_NOT_FOUND`).

Structural validation of the body comes next: required fields must be present and well-typed and any enum value must be drawn from its allowed set (`ERR_INVALID_REQUEST`), and then the numeric and range constraints are checked (`ERR_INVALID_RANGE`). Only after a request is structurally sound does the system evaluate state: whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`), and then the optimistic-concurrency version check on endpoints that bear it (`ERR_STALE_VERSION`). Finally, the cross-entity business guards — consent status, student eligibility, parent-program status, transition age, and the single-active-program rule — are evaluated. The net effect is that a malformed body is rejected before a state error, and a state error is rejected before a cross-entity business error.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded against acting on a stale view of their parent program, and both target the `IEP` as the parent entity.

The first is opening an amendment cycle on a program. A request to open an amendment must carry `expected_iep_version` as a required field whose value is the program `version` the client last observed. If that value does not match the program's current `version` — for instance because the program's version was already advanced by a placement-consent withdrawal that cascaded the program out of its active state after the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so the amendment cannot apply on top of state the client never saw.

The second is adding a related service to a program. A request to add a related service must likewise carry `expected_iep_version` as a required field carrying the client's last-observed program `version`. Because each service addition recomputes the program's least-restrictive-environment percentage and bumps the program's `version`, a client whose `expected_iep_version` is outdated is working from a stale environment picture and is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints other than these two do not take a version field and are not subject to the concurrency check.

## 3. Business Logic & Workflows

### 3.1. Registering Students and Reading Their Derived Profile

The student is the hub of the system. A `SpecialEdAdmin` registers a student by supplying the student's legal name in `full_name`, a `date_of_birth` as an ISO 8601 date, and a `grade_level` integer. Grade level uses kindergarten as zero and ranges from 0 through 12 inclusive; a value outside that range is rejected as out of range. A newly registered student has an eligibility status of `NOT_EVALUATED`.

Beyond the three supplied attributes, every student carries a set of derived fields that the system maintains and that appear when the student is fetched. The `eligibility_status` reflects the student's most recently finalized evaluation: it is `NOT_EVALUATED` until the first evaluation is finalized, and `ELIGIBLE` or `INELIGIBLE` thereafter, recomputed on every finalization with the latest finalized evaluation winning (the one with the most recent finalization timestamp). The `disability_category` is copied from the proposed category of the most recently finalized evaluation whose outcome was `ELIGIBLE`, and is null while the student is `NOT_EVALUATED` or `INELIGIBLE`; its permitted values are `SLD`, `AUTISM`, `SPEECH_LANGUAGE`, `OHI`, `EMOTIONAL`, and `INTELLECTUAL`. The `active_iep_id` holds the `id` of the student's program that is currently turned on — at most one — and is null when no program is on; it is set when a program is turned on and cleared when a program leaves that state. The `next_reeval_due_date` is the triennial reevaluation deadline, computed as the finalization timestamp of the latest finalized evaluation plus three years, expressed as 1095 days, and is null while the student is `NOT_EVALUATED`.

Students may be listed with pagination, optionally filtered by `eligibility_status`, and may be fetched individually; the individual fetch returns the computed `eligibility_status`, `active_iep_id`, and `next_reeval_due_date` alongside the stored attributes.

### 3.2. The Eligibility Evaluation Lifecycle

A `CaseManager` opens an eligibility evaluation against a student by submitting the `student_id`, the `eval_type`, and the three standardized assessment scores: a `cognitive_score`, an `academic_score`, and an `adaptive_score`, together with the `proposed_category` the evaluation team puts forward. The `eval_type` is either `INITIAL`, for a student's first eligibility determination, or `TRIENNIAL`, for the three-year reevaluation. Each of the three scores is a standard score that must lie between 40 and 160 inclusive; a score outside that band is rejected as out of range. The `proposed_category` must be one of `SLD`, `AUTISM`, `SPEECH_LANGUAGE`, `OHI`, `EMOTIONAL`, or `INTELLECTUAL`. The system records the requesting `CaseManager`'s `X-User-ID` on the evaluation. A new evaluation begins in status `REQUESTED`. Each evaluation also exposes a `composite_eligibility_score`, an `outcome`, and a `finalized_at`, all of which are null until the evaluation is finalized. Evaluations may be listed (optionally filtered by `student_id`) and fetched individually.

The evaluation advances through three transitions. From `REQUESTED`, the `CaseManager` requests parental evaluation consent, moving the evaluation to `CONSENT_PENDING`; this requires the evaluation to currently be in `REQUESTED`, and as a side effect it creates a consent request of type `EVALUATION` for the same student (with no program reference) in pending status, and increments the evaluation's `version` by one. From `CONSENT_PENDING`, the `Evaluator` begins testing, moving the evaluation `CONSENT_PENDING → IN_PROGRESS`; this requires the evaluation to be in `CONSENT_PENDING` and additionally requires that the `EVALUATION` consent request for this evaluation's student be in `GRANTED` status — if it is not, the begin is rejected with `ERR_CONSENT_NOT_GRANTED` (HTTP 409). Beginning increments the evaluation's `version` by one.

The third transition is finalization. The `Evaluator` finalizes an evaluation that is `IN_PROGRESS`, moving it `IN_PROGRESS → FINALIZED`, which is a terminal state. Finalization is the operation that bears segregation of duties: the finalizing evaluator must not be the case manager who requested the evaluation, on pain of `ERR_SEGREGATION_OF_DUTIES`. On finalization the system computes the `composite_eligibility_score` (described in 3.3), sets the `outcome` to `ELIGIBLE` when that composite score is at least the eligibility threshold and to `INELIGIBLE` otherwise, and stamps `finalized_at` with the current server clock. It then reconciles the student: the student's `eligibility_status` is recomputed from this newly finalized evaluation; if the outcome is `ELIGIBLE` the student's `disability_category` is set to this evaluation's `proposed_category`, and otherwise the category is left null; and the student's `next_reeval_due_date` is set to `finalized_at` plus 1095 days. Finalization increments the evaluation's `version` by one and the student's `version` by one.

### 3.3. Deciding Eligibility — The Composite Score

The eligibility decision rests on a single weighted composite computed at finalization from only the three standard scores on the evaluation plus its `eval_type`; there are no cross-entity inputs. The computation proceeds in a pinned order. First, an ability-achievement discrepancy is formed by subtracting the `academic_score` from the `cognitive_score`; if that difference is negative it is treated as zero, so a negative gap never contributes. Next, the gap is weighted by a factor that depends on `eval_type`: for an `INITIAL` evaluation the gap weight is 0.5, and for a `TRIENNIAL` evaluation it is 0.6, the higher factor reflecting the continuity of a student who already carries an identification history. An adaptive deficit is then formed as 100 minus the `adaptive_score`, taking zero whenever that would be negative; likewise an academic deficit is formed as 100 minus the `academic_score`, again floored at zero.

The raw composite is the sum of three terms: the gap weight multiplied by the discrepancy, plus 0.30 multiplied by the adaptive deficit, plus 0.20 multiplied by the academic deficit. That raw value is rounded half-up to two decimal places to produce the `composite_eligibility_score`. The outcome is then `ELIGIBLE` when the composite score is at least 15.0, and `INELIGIBLE` when it is below 15.0. The two variants of this model — the initial model with its 0.5 gap weight and the triennial model with its 0.6 gap weight — differ only in that single factor; every other term and the threshold are identical.

### 3.4. Parental Consent — Grant, Deny, and Revocation

Consent is the parent's act, and the `Parent` role is the only one that may exercise it. A consent request carries a `student_id`, an optional `iep_id` (which is null for an `EVALUATION` consent, because evaluation consent precedes any program), a `consent_type`, a `status`, and a `decided_at` timestamp that is null until the request is decided. The `consent_type` is either `EVALUATION`, which gates an evaluation leaving `CONSENT_PENDING`, or `PLACEMENT`, which gates a program leaving `MEETING_HELD` into its active state. Consent requests are not created directly by clients; they are spawned as side effects of requesting evaluation consent and of convening a program meeting, and both are created in `PENDING` status. Consent requests may be listed — filterable by `student_id`, by `iep_id`, by `consent_type`, and by `status` — and fetched individually.

A pending consent request is resolved by the parent through a single decide operation that carries a `decision` in its body. When the `decision` is `GRANT`, the request moves `PENDING → GRANTED`; when the `decision` is `DENY`, it moves `PENDING → DENIED`. Either decision requires the request to currently be `PENDING`, stamps `decided_at` with the server clock, and increments the request's `version` by one. `DENIED` is terminal.

A granted consent may later be withdrawn. The parent revokes a request that is currently `GRANTED`, moving it `GRANTED → REVOKED`, which is terminal; this increments the request's `version` by one. Revocation carries a consequential cascade: if the revoked consent is of type `PLACEMENT` and its linked program (named by the request's `iep_id`) is currently turned on, the program is forced out of its active state into its amendment-pending state, and that program transition in turn clears the student's `active_iep_id` (and bumps the student's version). Because both `DENIED` and `REVOKED` are terminal, there is no path back to `PENDING` for the same request: to retry a consent after a denial or revocation, a fresh consent request must be created by re-running the workflow step that spawns it.

### 3.5. The IEP Lifecycle — Meeting, Activation, Amendment, and Archival

A `CaseManager` drafts a program for a student by supplying the `student_id`, the `school_day_minutes` (the total instructional minutes in the student's school day, which must be greater than zero and serves as the denominator for the environment calculation), and the `annual_review_due_date` (the ISO 8601 date the annual review is due, typically one year after activation). A drafted program begins in status `DRAFT`, with a least-restrictive-environment percentage of 100.0 and a setting of `FULL_INCLUSION`. Each program also exposes a computed `lre_general_ed_pct`, a computed `lre_setting`, and an `activated_at` timestamp that is null until the program is turned on. Programs may be listed (filterable by `student_id` and by `status`) and fetched individually; the individual fetch returns the computed environment percentage and setting.

Convening the annual meeting moves the program `DRAFT → MEETING_HELD`. The `CaseManager` performs this, and it requires the program to be in `DRAFT` and the student's `eligibility_status` to be `ELIGIBLE`; if the student is not eligible, the meeting is rejected with `ERR_STUDENT_NOT_ELIGIBLE` (HTTP 409). Holding the meeting creates a `PLACEMENT` consent request for this program (carrying the program's `student_id` and `iep_id`) in `PENDING` status, records the convening `CaseManager`'s `X-User-ID` on the program, and increments the program's `version` by one.

Turning the program on is the act of a `SpecialEdAdmin`, never the case manager who convened the meeting — this is the segregation-of-duties boundary, enforced with `ERR_SEGREGATION_OF_DUTIES`. Activation moves a program `MEETING_HELD → ACTIVE`. It has three preconditions evaluated together: the program must be in `MEETING_HELD`; the `PLACEMENT` consent request for this program must be in `GRANTED` status, failing which the activation is rejected with `ERR_CONSENT_NOT_GRANTED` (HTTP 409); and the student must have no other program already turned on, failing which the activation is rejected with `ERR_ACTIVE_IEP_EXISTS` (HTTP 409). On success, activation stamps `activated_at` with the server clock, sets the student's `active_iep_id` to this program's `id` and increments the student's `version` by one, and increments the program's `version` by one.

An active program can enter a revision round. Opening an amendment moves a program `ACTIVE → AMENDMENT_PENDING`; it may be driven explicitly by a `CaseManager` or arise as the system cascade from a placement-consent withdrawal. It requires the program to be `ACTIVE`. When opened explicitly it carries the optimistic-concurrency field `expected_iep_version` described in 2.9. Either way, leaving the active state clears the student's `active_iep_id` (sets it to null) and increments the student's `version` by one, and increments the program's `version` by one. From `AMENDMENT_PENDING`, the program is turned back on by a `SpecialEdAdmin` through the same activation action that serves `MEETING_HELD`: it moves `AMENDMENT_PENDING → ACTIVE`, subject to the same three preconditions (the program in `AMENDMENT_PENDING`, the `PLACEMENT` consent `GRANTED`, and no other active program — otherwise `ERR_CONSENT_NOT_GRANTED` or `ERR_ACTIVE_IEP_EXISTS` respectively), and on success re-sets the student's `active_iep_id` and bumps both the student's and the program's `version`. This `ACTIVE → AMENDMENT_PENDING → ACTIVE` cycle may repeat across successive revision rounds.

Archival is terminal. A `SpecialEdAdmin` archives a program that is `ACTIVE`, moving it `ACTIVE → ARCHIVED`. Archival clears the student's `active_iep_id` and increments the student's `version` by one, and increments the program's `version` by one. It also cascades to the program's children: every goal on this program whose status is `ACTIVE` transitions to `DISCONTINUED`, and every related service on this program whose status is `ACTIVE` transitions to `DISCONTINUED`. Each such child transition is an independent mutation of that child.

### 3.6. Measurable Goals and Progress Tracking

Within a program, a `CaseManager` adds a measurable goal by supplying the `iep_id`, the instructional `domain`, a `baseline_value`, and a `target_value`. The `domain` is one of `READING`, `MATH`, `WRITING`, `COMMUNICATION`, `BEHAVIOR`, or `MOTOR`. The `baseline_value` is the measured starting performance and must be at least zero; the `target_value` defines mastery and must be strictly greater than the `baseline_value`. A target that is not strictly above the baseline, or a baseline below zero, is rejected as out of range with `ERR_INVALID_RANGE`. A new goal begins in status `ACTIVE`, with a `latest_progress_pct` of 0 and a `cumulative_progress_pct` of 0. Goals may be listed (filterable by `iep_id` and by `status`) and fetched individually; the individual fetch returns both computed progress percentages.

Progress is recorded as a stream of immutable data points. A `CaseManager` records a progress report by supplying the `goal_id`, the `reporting_period`, and the `measured_value`. The `reporting_period` is the ordinal quarter within the program year and must be an integer from 1 through 4 inclusive; a value outside that range is rejected as out of range. The `measured_value` is the measured performance for that period and must be at least zero. Recording a progress report recomputes both progress figures on the goal (described in 3.7), increments the goal's `version` by one, and — when the recomputed cumulative figure reaches mastery — automatically advances the goal.

A goal can leave `ACTIVE` by two paths. The first is automatic: when, after a newly recorded progress report, the goal's cumulative progress percentage is at least 100.0, the system bubbles the goal `ACTIVE → MET` (incrementing its `version`). The second is the `CaseManager` explicitly discontinuing a goal that is `ACTIVE`, moving it `ACTIVE → DISCONTINUED` (incrementing its `version`); the same `DISCONTINUED` end state is also reached when an active program is archived and cascades its active goals. Both `MET` and `DISCONTINUED` are terminal.

### 3.7. Provisional and Cumulative Progress Computation

Each goal exposes two progress measures that diverge whenever reporting periods differ, and both are recomputed every time a progress report is recorded. Both measure distance travelled from baseline toward target, and both are pinned to two decimal places using round-half-up.

The **provisional** measure, `latest_progress_pct`, reflects only the single most recent progress report for the goal. The "most recent" report is the one with the greatest `reporting_period`; if two reports share the highest period, the tie is broken by taking them in ascending order of creation time and using the last of them. For that one report, the progress is the measured value minus the baseline, divided by the target minus the baseline, multiplied by 100; the result is clamped to lie between 0 and 100 and then rounded half-up to two decimal places.

The **cumulative** measure, `cumulative_progress_pct`, averages across all of the goal's progress reports regardless of period, and its rounding order is pinned: round each report first, then average. Concretely, for each progress report on the goal the system computes that report's progress as the measured value minus the baseline, divided by the target minus the baseline, multiplied by 100, clamps it between 0 and 100, and rounds that per-report figure half-up to two decimal places. It then sums those rounded per-report figures, divides by the number of reports, and rounds the average half-up to two decimal places. This is round-per-report-then-average, not average-then-round, and the two can differ. When the resulting cumulative percentage is at least 100.0, the goal bubbles up from `ACTIVE` to `MET` as described above.

### 3.8. Related Services and the Least Restrictive Environment

A `CaseManager` adds an OT, PT, or speech-language related service to a program by supplying the `iep_id`, the `service_type` (one of `OT`, `PT`, or `SPEECH`), the `minutes_per_week` (weekly service minutes, which must be greater than zero), the `delivered_in_general_ed` flag, and the optimistic-concurrency field `expected_iep_version` described in 2.9. The `delivered_in_general_ed` flag is true when the service is push-in, delivered inside the general-education classroom so that it counts toward general-education time, and false when it is pull-out, removing the student from general education for its minutes. A new related service begins in status `ACTIVE`. Related services may be listed (filterable by `iep_id` and by `status`) and fetched individually.

Adding a related service recomputes the parent program's least-restrictive-environment percentage and setting, increments the related service's `version` and the parent program's `version`. Discontinuing a related service does the same: a `CaseManager` may discontinue an `ACTIVE` related service, moving it `ACTIVE → DISCONTINUED` (which requires the service to be `ACTIVE` and which is terminal), and this likewise recomputes the parent program's environment percentage and setting and increments both the service's `version` and the program's `version`. The discontinue operation also carries `expected_iep_version` and is subject to the same stale-version rejection. Active services are additionally discontinued by the archival cascade described in 3.5.

The least-restrictive-environment percentage, `lre_general_ed_pct`, is the share of the school day the student spends in the general-education setting, and its rounding order is pinned. Only the program's active pull-out services participate — that is, related services on the program whose status is `ACTIVE` and whose `delivered_in_general_ed` flag is false; push-in services and discontinued services do not subtract anything. For each such pull-out service, its weekly minutes are converted to a per-school-day share by dividing `minutes_per_week` by 5 (the number of school days per week) and rounding that per-service daily contribution half-up to two decimal places. Those rounded per-service daily contributions are summed, and the sum is itself rounded half-up to two decimal places to form the total daily pull-out minutes. The percentage is then the program's `school_day_minutes` minus that total daily pull-out figure, divided by `school_day_minutes`, multiplied by 100; the result is clamped between 0 and 100 and rounded half-up to two decimal places. This is round-per-service-then-sum-then-divide, not sum-then-round. When a program has no active pull-out services, the percentage is 100.0.

The placement setting, `lre_setting`, is derived from the just-computed percentage by exact comparison against two floors, with the upper edge of each band inclusive. When the percentage is at least 80.0, the setting is `FULL_INCLUSION`. When the percentage is below 80.0 but at least 40.0, the setting is `RESOURCE`. When the percentage is below 40.0, the setting is `SEPARATE_CLASS`.

### 3.9. Transition Planning

For older students, a `CaseManager` creates a transition plan against a program by supplying the `iep_id`, a measurable `postsecondary_goal` (covering employment, education, or independent living), and a `services_summary` describing transition services and agency linkages. A transition plan may be created only when the student is old enough: the student's age at the current server-clock instant — the number of full years between the student's `date_of_birth` and the server clock — must be at least 16. A younger student is rejected with `ERR_TRANSITION_AGE_NOT_MET` (HTTP 409). A new transition plan begins in status `DRAFT`. Transition plans may be listed (filterable by `iep_id`) and fetched individually.

Adopting a transition plan moves it `DRAFT → ADOPTED`, which is terminal and is performed by a `CaseManager`. Adoption requires the plan to be in `DRAFT` and additionally requires the parent program to currently be `ACTIVE`; if the parent program is not active, adoption is rejected with `ERR_IEP_NOT_ACTIVE` (HTTP 409). Adoption increments the transition plan's `version` by one.

### 3.10. Test-Driving the Server Clock

Because finalization timestamps, consent decision timestamps, activation timestamps, the triennial reevaluation deadline, and the transition-age check all derive from the server clock, the system exposes an administrator-only test-driving capability that pins the logical clock to a supplied instant. A `SpecialEdAdmin` invokes it with a `to_iso8601` value, and the server adopts that instant as its current clock for all subsequent clock-derived computations.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the state-transition actions and the consent decisions — return a `200 OK` status code. The discontinue-related-service action is exposed as a DELETE and likewise returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/students` | Register a student | SpecialEdAdmin |
| GET | `/students` | List students (paginated, filterable by eligibility) | SpecialEdAdmin, CaseManager, Evaluator |
| GET | `/students/{id}` | Fetch a student with computed fields | SpecialEdAdmin, CaseManager, Evaluator, Parent |
| POST | `/evaluations` | Open an eligibility evaluation | CaseManager |
| GET | `/evaluations` | List evaluations (filterable by student) | SpecialEdAdmin, CaseManager, Evaluator |
| GET | `/evaluations/{id}` | Fetch one evaluation | SpecialEdAdmin, CaseManager, Evaluator |
| POST | `/evaluations/{id}/request-consent` | Request parental evaluation consent | CaseManager |
| POST | `/evaluations/{id}/begin` | Begin testing | Evaluator |
| POST | `/evaluations/{id}/finalize` | Finalize and decide eligibility | Evaluator |
| GET | `/consent-requests` | List consent requests (filterable) | SpecialEdAdmin, CaseManager, Evaluator, Parent |
| GET | `/consent-requests/{id}` | Fetch one consent request | SpecialEdAdmin, CaseManager, Evaluator, Parent |
| POST | `/consent-requests/{id}/decide` | Grant or deny a pending consent | Parent |
| POST | `/consent-requests/{id}/revoke` | Revoke a granted consent | Parent |
| POST | `/ieps` | Draft an IEP for a student | CaseManager |
| GET | `/ieps` | List IEPs (filterable by student/status) | SpecialEdAdmin, CaseManager, Evaluator, Parent |
| GET | `/ieps/{id}` | Fetch one IEP with computed LRE | SpecialEdAdmin, CaseManager, Evaluator, Parent |
| POST | `/ieps/{id}/hold-meeting` | Record the annual meeting | CaseManager |
| POST | `/ieps/{id}/activate` | Activate the IEP | SpecialEdAdmin |
| POST | `/ieps/{id}/open-amendment` | Open an amendment cycle | CaseManager |
| POST | `/ieps/{id}/archive` | Archive the IEP | SpecialEdAdmin |
| POST | `/goals` | Add a measurable goal | CaseManager |
| GET | `/goals` | List goals (filterable by IEP/status) | SpecialEdAdmin, CaseManager, Evaluator, Parent |
| GET | `/goals/{id}` | Fetch one goal with computed progress | SpecialEdAdmin, CaseManager, Evaluator, Parent |
| POST | `/goals/{id}/discontinue` | Discontinue a goal | CaseManager |
| POST | `/progress-reports` | Record a progress data point | CaseManager |
| GET | `/progress-reports` | List progress reports (filterable by goal) | SpecialEdAdmin, CaseManager, Evaluator, Parent |
| GET | `/progress-reports/{id}` | Fetch one progress report | SpecialEdAdmin, CaseManager, Evaluator, Parent |
| POST | `/related-services` | Add an OT/PT/Speech service | CaseManager |
| GET | `/related-services` | List related services (filterable by IEP/status) | SpecialEdAdmin, CaseManager, Evaluator, Parent |
| GET | `/related-services/{id}` | Fetch one related service | SpecialEdAdmin, CaseManager, Evaluator, Parent |
| DELETE | `/related-services/{id}` | Discontinue a related service | CaseManager |
| POST | `/transition-plans` | Create a transition plan | CaseManager |
| GET | `/transition-plans` | List transition plans (filterable by IEP) | SpecialEdAdmin, CaseManager, Evaluator, Parent |
| GET | `/transition-plans/{id}` | Fetch one transition plan | SpecialEdAdmin, CaseManager, Evaluator, Parent |
| POST | `/transition-plans/{id}/adopt` | Adopt a transition plan | CaseManager |
| POST | `/_clock/set_current_utc` | Set the server clock (test-driving) | SpecialEdAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_RANGE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CONSENT_NOT_GRANTED` | 409 |
| `ERR_STUDENT_NOT_ELIGIBLE` | 409 |
| `ERR_IEP_NOT_ACTIVE` | 409 |
| `ERR_TRANSITION_AGE_NOT_MET` | 409 |
| `ERR_ACTIVE_IEP_EXISTS` | 409 |
