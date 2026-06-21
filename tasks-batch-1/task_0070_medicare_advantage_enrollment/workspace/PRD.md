# Medicare Advantage Enrollment API — Product Requirements Document

## 1. Introduction

The Medicare Advantage Enrollment API is the system of record for the way an aging beneficiary moves through the four parts of Medicare — hospital insurance (Part A), medical insurance (Part B), Medicare Advantage (Part C), and prescription drug coverage (Part D) — together with the private Medigap supplements that sit alongside them. Enrollment in this world is governed less by what a person wants and more by *when* they are allowed to ask: every coverage decision is gated by a calendar of enrollment windows, the Initial Enrollment Period derived from a beneficiary's date of birth, the fixed Annual Enrollment Period each autumn, a Special Enrollment Period that opens only for the very best-rated plans, and a narrow guaranteed-issue window for Medigap. Filing inside the wrong window, or a moment too late, is the difference between coverage and a denial.

This API exists to make those temporal and compliance rules enforceable rather than advisory. It serves two operational audiences — enrollment operations staff who build the beneficiary record and drive each coverage lifecycle, and compliance staff who freeze suspect accounts and assess the late-enrollment penalties that Medicare law attaches to procrastination. Because penalties compound, drug costs accumulate across coverage phases, and a single recorded death must unwind every active policy at once, the system treats consistency as non-negotiable: each mutation is versioned, cascades are immediate, and a confirmation filed against a beneficiary record that has moved underneath the caller is rejected rather than allowed to silently clobber a competing decision. The sections that follow specify the global contract first, then the business logic that ties windows, penalties, and drug-phase accounting together.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This applies to every endpoint without exception — even the administrative clock-setting capability still requires both headers to be present.

The system recognizes exactly two roles, spelled precisely as `EnrollmentAdmin` and `ComplianceOfficer`. An `EnrollmentAdmin` is operations staff: they create beneficiaries, plans, and enrollment periods, and they drive every enrollment lifecycle — filing and activating Part B, filing and confirming Part C and Part D, posting drug claims, and applying and lapsing Medigap policies. A `ComplianceOfficer` is audit staff: they place and clear fraud holds, and they assess and waive late-enrollment penalties. Both roles may perform all read (GET) operations and both may set the system clock. When a request's `X-User-Role` is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Both `EnrollmentAdmin` and `ComplianceOfficer` are opaque operator identifiers: `X-User-ID` is not tied to any persisted entity. The server may treat the value as an audit actor, but it never compares `X-User-ID` to any entity's `id` for ownership purposes — authorization is decided purely by the role string, not by which beneficiary, plan, or enrollment is being touched.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_VALIDATION_PAGINATION` (HTTP 422).

Unless stated otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. The System Clock and Temporal Authority

Medicare enrollment is fundamentally a question of timing, and the entire API reads "now" from a single server-held logical clock rather than wall-clock time. An administrative test-driving capability sets that clock to a supplied instant, accepting a `to_iso8601` value; both roles may invoke it. Every window check, every `requested_at` stamp, and every uncovered-month computation reads the clock as it stands at the moment the operation executes. Setting the clock returns no resource body. Because all temporal rules below resolve against this clock, a window that is "open" depends entirely on where the clock has been positioned.

### 2.5. Common Resource Properties and Versioning

Most top-level resources — `Beneficiary`, `Plan`, `PartBEnrollment`, `PartCEnrollment`, `PartDEnrollment`, `MedigapPolicy`, and `PenaltyAssessment` — carry a standard system-managed field set. The `id` is a server-minted UUID with no type prefix, serving as identity only and never as a business-decision input. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording first creation, and `updated_at` is an ISO 8601 UTC timestamp refreshed on every modification. The `version` field is an integer that begins at creation and increments by one on every mutation of that resource; it is the basis for optimistic concurrency control described below.

Two entities are deliberately leaner. An `EnrollmentPeriod` and a `DrugClaim` are immutable computed records: each carries only an `id` (UUID) and a `created_at` timestamp. Neither has an `updated_at` field and neither has a `version` field, because once written they are never mutated in place.

### 2.6. Optimistic Concurrency Control on Part C Confirmation

Confirming a Part C enrollment is the one write in this system that is guarded by optimistic concurrency control, because confirmation reads and rewrites the beneficiary's coverage picture. The confirm request must carry `expected_beneficiary_version`, a required field whose value is the beneficiary's `version` as the client last observed it. The server compares that value against the beneficiary's current `version`. If another writer has advanced the beneficiary's version since the client last read it — for example, by confirming a different Part C enrollment for the same beneficiary, which legitimately supersedes any prior active enrollment — the client's view of which enrollment is active is stale, and the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts or requires a version field; confirmation is the sole OCC-guarded write, and `expected_beneficiary_version` is not optional on it.

### 2.7. Death, Holds, and Cascading Consistency

When a beneficiary's posture changes, the change must propagate consistently to everything that depends on it. Recording a death is the most far-reaching event: it is terminal and, in a single cascade, voids every piece of active coverage the beneficiary holds. Placing a fraud hold is narrower — it freezes the *creation* of new coverage but leaves every existing enrollment untouched. In both cases the beneficiary's own `version` increments and its `updated_at` refreshes, and every child record the cascade touches likewise has its own `version` incremented. The precise membership of each cascade and the states each child lands in are specified in §3, where the death cascade is described in full alongside the lifecycles it unwinds.

### 2.8. Nested Resource Retrieval and Referential Existence

Several endpoints address a resource through a path that names a parent before a child — listing a beneficiary's enrollment periods, or posting and listing the drug claims of a Part D enrollment. The system validates path identifiers strictly left-to-right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not resolve to an existing resource. The same existence discipline applies to body references: when a create request names a foreign resource by `beneficiary_id`, `plan_id`, `enrollment_period_id`, or `part_d_enrollment_id`, a reference to a non-existent resource is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.9. Monetary Precision and Penalty Rounding

All monetary amounts in the system are stored and exchanged as integer cents, never as decimal dollars. Premiums, penalties, drug list prices, and accumulators are all whole numbers of cents. The two late-enrollment penalty calculations apply distinct rounding disciplines — the Part D penalty rounds to the nearest dime using round-half-up, while the Part B penalty floors after an integer-percentage step — and the drug-phase cost-share rounds each coverage segment to whole cents with round-half-up before the segments are summed. The exact mechanics of each calculation live in §3 next to the workflow that triggers it; what is fixed system-wide is that every amount that leaves or enters the API is an integer count of cents.

### 2.10. The Calendar of Enrollment Windows

Coverage cannot be filed in a vacuum: every Part B, Part C, Part D, and Medigap enrollment is justified by an `EnrollmentPeriod` of a particular kind, and the kinds differ sharply in how their windows are computed and how their boundaries behave. There are four `period_type` values: `IEP` (the Initial Enrollment Period, derived from the beneficiary's date of birth), `AEP` (the Annual Enrollment Period, a fixed autumn window), `SEP_5STAR` (a Special Enrollment Period that exists only to move a beneficiary into a top-rated plan), and `GI_MEDIGAP` (the Medigap guaranteed-issue window). The `IEP` and `AEP` windows are **closed intervals**: an action whose clock time equals `window_end` to the second is still inside the window, and likewise an action exactly at `window_start` is inside it. The way each window's `window_start` and `window_end` are derived, and the strict ordering in which window membership is checked against everything else, are detailed in §3. The principle to hold here is that window boundaries are inclusive on both ends for `IEP` and `AEP`.

## 3. Business Logic & Workflows

### 3.1. Building the Beneficiary Record

Every workflow begins with a **Beneficiary**, created by an `EnrollmentAdmin` with a legal `full_name` and a `date_of_birth`. The date of birth is supplied as an ISO 8601 UTC date-time and carries one hard constraint: its day-of-month must not be the 1st. A beneficiary born on the first of any month is rejected with `ERR_INVALID_REQUEST` (HTTP 422), because the "first-of-month" Medicare birthday nuance is deliberately out of scope. The caller may optionally supply `part_d_creditable_since`, the date from which the beneficiary already held creditable prescription-drug coverage through an employer or the VA; it is left null if the beneficiary never had such coverage, and it later anchors the Part D penalty count.

At creation a beneficiary's `status` is `ACTIVE`, its `part_a_status` and `part_b_status` are both `NONE`, its `part_b_effective_date` is null, and its `enrollment_lock` is false. The `id` is a server-minted UUID. Hospital insurance is established as a separate step: an `EnrollmentAdmin` invokes the establish-Part-A capability, which sets `part_a_status` to `ENROLLED` and increments the beneficiary's `version`. This is a prerequisite gate for Part B activation, not for Part B filing.

A beneficiary's posture is itself a small state machine. From `ACTIVE`, a `ComplianceOfficer` may place a fraud hold, moving `status` to `FRAUD_HOLD`; this requires the beneficiary to currently be `ACTIVE`, otherwise it is rejected with `ERR_INVALID_STATE` (HTTP 409). The hold sets `enrollment_lock` to true and increments `version`. The same officer may later clear the hold, moving `FRAUD_HOLD` back to `ACTIVE` (requiring the beneficiary to currently be in `FRAUD_HOLD`, else `ERR_INVALID_STATE`); clearing sets `enrollment_lock` back to false and increments `version`. While `enrollment_lock` is true, no new Part B, Part C, Part D, or Medigap enrollment may be created for that beneficiary — such attempts are rejected with `ERR_ENROLLMENT_LOCKED` (HTTP 409). Existing enrollments are entirely unaffected by a hold.

### 3.2. Recording Death: The Voiding Cascade

Recording a beneficiary's death is performed by an `EnrollmentAdmin` and is permitted from either `ACTIVE` or `FRAUD_HOLD` (the precondition is simply that the beneficiary is in whichever of those two states it currently occupies; a request against an already-`DECEASED` beneficiary fails with `ERR_INVALID_STATE`, HTTP 409). The transition moves `status` to `DECEASED`, which is terminal, and triggers one atomic cascade that unwinds every active commitment:

- Every `PartCEnrollment` of this beneficiary currently in `PENDING` or `ACTIVE` transitions to `VOIDED`, each incrementing its own `version`.
- Every `PartDEnrollment` of this beneficiary currently in `PENDING` or `ACTIVE` transitions to `VOIDED`, each incrementing its own `version`.
- Every `MedigapPolicy` of this beneficiary currently in `ISSUED` transitions to `VOIDED`, each incrementing its own `version`.
- Every `PartBEnrollment` of this beneficiary currently in `FILED` or `ACTIVE` transitions to `VOIDED`. When a `PartBEnrollment` that was `ACTIVE` is voided this way, the beneficiary's `part_b_status` is reset to `NONE`. Each voided Part B record increments its own `version`.

The beneficiary's own `version` increments once for the death event. The cascade is the only path by which these records reach `VOIDED`; there is no client endpoint that voids a single enrollment directly.

### 3.3. Plans and Their Star Ratings

A **Plan** is the product a beneficiary enrolls into, created by an `EnrollmentAdmin` with a marketing `name`, a `part_type`, a `monthly_premium_cents`, a `star_rating`, and an optional `includes_drug_coverage` flag. The `part_type` is either `PART_C` (a Medicare Advantage plan that bundles medical coverage) or `PART_D` (a standalone prescription-drug plan). The `monthly_premium_cents` is an integer of cents that must be at least 0. The `star_rating` is the CMS rating and must be one of the values `1.0`, `1.5`, `2.0`, `2.5`, `3.0`, `3.5`, `4.0`, `4.5`, or `5.0`; a rating of exactly `5.0` is what later qualifies a plan for the five-star Special Enrollment Period.

The `includes_drug_coverage` flag distinguishes a Medicare Advantage plan that bundles Part D (an MAPD) from a bare medical-only Part C plan. A `PART_D` plan must set this flag to true; a bare `PART_C` plan sets it to false, which is also its default when omitted. At creation a plan's `status` is `ACTIVE`. An `EnrollmentAdmin` may later retire a plan, moving `status` to `RETIRED` and incrementing its `version`; retirement removes the plan from new enrollment but leaves every existing enrollment intact. A confirmation that references a `RETIRED` plan is rejected with `ERR_PLAN_RETIRED` (HTTP 409).

### 3.4. Deriving Enrollment Periods

An `EnrollmentAdmin` computes and persists an `EnrollmentPeriod` for a beneficiary by supplying a `period_type` and, depending on the kind, an `aep_year` or a `source_event_date`. The window's `window_start` and `window_end` are server-derived and recorded on the period; an `EnrollmentPeriod` also stores the `beneficiary_id` it belongs to and, for guaranteed-issue periods only, a `source_event_date`.

The four kinds derive their windows distinctly. An `IEP` window is computed from the beneficiary's date of birth: its `window_start` is the first-of-month three months before the birth month. An `AEP` window is fixed to the supplied `aep_year`: `window_start` is October 15 of that year and `window_end` is December 7 of that year. A `SEP_5STAR` window runs from December 8 of `aep_year` through November 30 of the following year — `window_start` is December 8 of `aep_year` and `window_end` is November 30 of `aep_year` plus one. A `GI_MEDIGAP` window is anchored to the qualifying event: `window_start` is the supplied `source_event_date` and `window_end` is that date plus 63 days. Creating a `GI_MEDIGAP` period without a `source_event_date` is rejected with `ERR_MISSING_SOURCE_EVENT_DATE` (HTTP 422); for all other period types `source_event_date` is null.

A guard protects the integrity of the calendar. A newly created `IEP` or `AEP` period for a beneficiary may not overlap an existing period of the *same type* for that same beneficiary. Overlap here uses closed-interval semantics on `[window_start, window_end]`: two periods that merely touch at a single instant — where one period's `window_end` equals the other's `window_start` — do collide, and the create is rejected with `ERR_PERIOD_OVERLAP` (HTTP 409). Enrollment periods are immutable once written and carry only `id` and `created_at`.

### 3.5. Part B: Filing, Activation, and Dropping

Part B is the medical-insurance leg, and it is the foundation Part C builds on. An `EnrollmentAdmin` files a Part B enrollment by naming a `beneficiary_id` and an `enrollment_period_id`. The enrollment is created in `FILED` status, its `requested_at` stamped from the system clock, and its `effective_date` computed as a first-of-month date under the IEP effective-date rule. The period named on a Part B filing must be an `IEP` period; if the period's `period_type` is anything else the filing is rejected with `ERR_WRONG_PERIOD_TYPE` (HTTP 422).

Activation is a distinct step driven by an `EnrollmentAdmin`, advancing the enrollment from `FILED` to `ACTIVE`. Activation has three preconditions, each guarded by its own error. The enrollment must currently be `FILED`, otherwise `ERR_INVALID_STATE` (HTTP 409). The beneficiary must be `ACTIVE` — a deceased beneficiary cannot be activated. And critically, the beneficiary's `part_a_status` must be `ENROLLED`: Part A must be established before Part B can activate, and an attempt to activate before Part A is in place is rejected with `ERR_PART_A_REQUIRED` (HTTP 409). On success, activation sets the beneficiary's `part_b_status` to `ENROLLED`, copies the enrollment's `effective_date` onto the beneficiary's `part_b_effective_date` (the anchor later used for Medigap prior-coverage reasoning), and increments the `PartBEnrollment.version`.

A beneficiary may voluntarily drop active Part B. An `EnrollmentAdmin` drives the drop, which requires the enrollment to currently be `ACTIVE` and the beneficiary not to be `DECEASED`; it moves the enrollment from `ACTIVE` to `DROPPED`, resets the beneficiary's `part_b_status` to `NONE`, and increments the `PartBEnrollment.version`. Dropping Part B does not auto-open any guaranteed-issue window. A `PartBEnrollment` reaches `VOIDED` only through the death cascade described in §3.2.

### 3.6. Part C: Filing, Confirmation, and the Supersede Cascade

Part C — Medicare Advantage — is filed by an `EnrollmentAdmin` naming a `beneficiary_id`, a `plan_id` for the chosen plan, and an `enrollment_period_id`. The enrollment is created `PENDING`, with `requested_at` from the clock and a computed `effective_date`. The justifying period may be an `IEP`, `AEP`, or `SEP_5STAR` period; a Part C filing under any other period type is rejected with `ERR_WRONG_PERIOD_TYPE` (HTTP 422). The plan named must be a `PART_C` plan; naming a `PART_D` plan is rejected with `ERR_DRUG_COVERAGE_CONFLICT` (HTTP 409).

Confirmation advances a `PENDING` enrollment to `ACTIVE` and is the system's most consequential write. It is driven by an `EnrollmentAdmin` and, as described in §2.6, requires `expected_beneficiary_version` to match the beneficiary's current `version`, failing with `ERR_STALE_VERSION` (HTTP 412) on a mismatch. Beyond the version check, confirmation has these preconditions, each with its own rejection: the enrollment must currently be `PENDING` (`ERR_INVALID_STATE`, HTTP 409); the beneficiary must be `ACTIVE`; the beneficiary's `part_b_status` must be `ENROLLED`, because Part C requires active Part B, and a confirm attempted otherwise is rejected with `ERR_PART_B_REQUIRED` (HTTP 409); and the plan must be `ACTIVE`, with a `RETIRED` plan triggering `ERR_PLAN_RETIRED` (HTTP 409).

On success, confirmation enforces that a beneficiary holds at most one active Medicare Advantage enrollment. Any *other* `PartCEnrollment` of the same beneficiary currently in `ACTIVE` is transitioned to `SUPERSEDED`, incrementing that superseded enrollment's `version`. The supersede has a secondary cascade of its own: if the superseded plan was an MAPD — that is, its `includes_drug_coverage` was true — then the beneficiary's `ACTIVE` bundled drug enrollment, if any, transitions to `DISENROLLED` (incrementing its `version`), since the bundled drug coverage ends with the plan that carried it. If the superseded plan was a bare `PART_C` with `includes_drug_coverage` false, there is no further drug-side cascade. Confirmation itself increments both the `PartCEnrollment.version` of the newly confirmed enrollment and the `Beneficiary.version` (the increment that makes any concurrent confirm's `expected_beneficiary_version` stale). An `EnrollmentAdmin` may also voluntarily disenroll an `ACTIVE` Part C enrollment, requiring it to be `ACTIVE` and the beneficiary not `DECEASED`, moving it to `DISENROLLED` and incrementing its `version`. A `PartCEnrollment` reaches `VOIDED` only via the death cascade.

### 3.7. Part D: Drug Enrollment and the Late Enrollment Penalty

Part D drug coverage is filed by an `EnrollmentAdmin` naming a `beneficiary_id`, a `plan_id`, and an `enrollment_period_id`. The enrollment is created `PENDING`, with `requested_at` from the clock and its accumulators `total_drug_cost_cents`, `member_oop_cents`, and `lep_premium_cents` all initialized to 0. The justifying period may be `IEP`, `AEP`, or `SEP_5STAR` (otherwise `ERR_WRONG_PERIOD_TYPE`, HTTP 422), and the plan must be a `PART_D` plan (a non-`PART_D` plan is rejected with `ERR_DRUG_COVERAGE_CONFLICT`, HTTP 409). A standalone Part D enrollment is forbidden when the beneficiary already holds an `ACTIVE` `PartCEnrollment` whose plan bundles drug coverage (`includes_drug_coverage` true): a member cannot stack a standalone drug plan on top of an MAPD, and the attempt is rejected with `ERR_DRUG_COVERAGE_CONFLICT` (HTTP 409).

Confirmation, driven by an `EnrollmentAdmin`, advances a `PENDING` Part D enrollment to `ACTIVE`, requiring the enrollment to be `PENDING` (`ERR_INVALID_STATE`, HTTP 409), the beneficiary to be `ACTIVE`, and the plan to be `ACTIVE`. At confirmation the system computes `uncovered_months` once and from it the `lep_premium_cents`, then increments the `PartDEnrollment.version`.

The uncovered-month count is computed as follows. The counting anchor is the beneficiary's `part_d_creditable_since`; if that is null — the beneficiary never held creditable drug coverage — the anchor instead becomes the last instant of the beneficiary's `IEP` window, that is, the `window_end` of their `IEP` `EnrollmentPeriod`. The effective month is the first day of the month of the system clock at the moment of confirmation. The count is the number of whole calendar months strictly between the anchor's month and the effective month: take the effective year times twelve plus the effective month index, subtract the anchor year times twelve plus the anchor month index, then subtract one more, and floor the result at zero so it can never go negative.

The Part D penalty itself derives from that count. The raw penalty is one percent of the national base beneficiary premium — fixed at 3,470 cents — multiplied by the number of uncovered months. That raw amount is then rounded to the nearest dime: divide the raw cents by ten, round half up to the nearest whole dime, then multiply back by ten, yielding `lep_premium_cents` as an integer number of cents. If there are no uncovered months the penalty is 0.

An `EnrollmentAdmin` may voluntarily disenroll an `ACTIVE` Part D enrollment, moving it to `DISENROLLED` and incrementing its `version`; the same `ACTIVE`-to-`DISENROLLED` transition is also what the Part C supersede cascade triggers on a bundled MAPD drug enrollment. A `PartDEnrollment` reaches `VOIDED` only through the death cascade.

### 3.8. Posting Drug Claims and the Donut-Hole Phases

Once a Part D enrollment is `ACTIVE`, an `EnrollmentAdmin` posts a **DrugClaim** against it by supplying a `list_price_cents` (the full negotiated list price, an integer greater than 0) and an `incurred_at` date (when the prescription was filled). A claim may post only to a Part D enrollment in `ACTIVE` status; a claim against any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). Each claim records the `part_d_enrollment_id` it posts against, a computed `phase_at_post`, and a computed `member_share_cents`. A `DrugClaim` is immutable and carries only `id` and `created_at` beyond its computed fields. Claims are processed in chronological `incurred_at` order, with creation timestamp (`created_at` ascending) as the tie-break, so that the running accumulators advance in the correct sequence.

Drug benefits move through four coverage phases as the year's spending grows, tracked against the enrollment's two running accumulators: `total_drug_cost_cents` (the cumulative list price posted so far, call it T) and `member_oop_cents` (the cumulative true out-of-pocket the member has paid, call it O). The phase boundaries are fixed: the deductible threshold is 54,500 cents, the initial-coverage-limit threshold is 503,000 cents, and the true-out-of-pocket catastrophic threshold is 800,000 cents. A claim's `phase_at_post` records the phase of its very first cent. A single claim's `list_price_cents` is consumed cent-by-cent and may straddle a boundary, so its cost is split into segments and the member share is computed per segment.

The four phases and their cost-share rules are:

- **`DEDUCTIBLE`** phase, while T is below 54,500 cents: the member pays 100% of the segment.
- **`INITIAL`** phase, while T is at least 54,500 cents and below 503,000 cents: the member pays 25% of the segment.
- **`GAP`** phase, while T is at least 503,000 cents and O is below 800,000 cents: the member pays 25% of the segment.
- **`CATASTROPHIC`** phase, while O is at least 800,000 cents: the member pays 0% of the segment.

The boundary crossings are evaluated as the segment advances: the deductible is crossed when T reaches 54,500 cents (at or above), the initial-to-gap crossing occurs when T reaches 503,000 cents (at or above), and the gap-to-catastrophic crossing occurs when O reaches 800,000 cents (at or above). For each segment that carries a 25% coinsurance (the initial and gap phases), the member share for that segment is the segment's cents multiplied by 25%, rounded half up to whole cents. The claim's `member_share_cents` is the sum of the per-segment member shares — each segment rounded first, then the rounded segment shares summed (round-per-segment-then-sum, not sum-then-round). After a claim posts, T is advanced by the claim's full `list_price_cents` and O is advanced by the claim's `member_share_cents`, and the `PartDEnrollment.version` increments.

### 3.9. Medigap Guaranteed Issue

A **MedigapPolicy** is a private supplement applied for by an `EnrollmentAdmin` under a guaranteed-issue window. The application names a `beneficiary_id`, an `enrollment_period_id`, a `coverage_start`, and a `coverage_end`, and is created with `status` `ISSUED`, `requested_at` from the clock, and `guaranteed_issue` true. The period named must be a `GI_MEDIGAP` period; any other period type is rejected with `ERR_WRONG_PERIOD_TYPE` (HTTP 422).

Guaranteed issue is the heart of the Medigap rule. The application is accepted only when the system clock at the moment of application falls within the 63-day window that runs from the period's `source_event_date`: the clock must be at or after `source_event_date` and at or before `source_event_date` plus 63 days (day 63 inclusive). An application landing outside that window is rejected with `ERR_GI_WINDOW_EXPIRED` (HTTP 422); because such applications are turned away, any persisted policy always has `guaranteed_issue` true.

The supplement's coverage interval, `[coverage_start, coverage_end)`, is half-open: `coverage_start` is the inclusive first instant and `coverage_end` is the exclusive last instant. A new policy may not overlap an existing `ISSUED` policy of the same beneficiary. Under half-open semantics, two policies that merely touch at a single instant — where one policy's `coverage_end` equals the next policy's `coverage_start` — do *not* overlap and are allowed; a genuine overlap is rejected with `ERR_MEDIGAP_OVERLAP` (HTTP 409). An `EnrollmentAdmin` may lapse an `ISSUED` policy, requiring it to be `ISSUED` and the beneficiary not `DECEASED`, moving `status` to `LAPSED` and incrementing its `version`. A `MedigapPolicy` reaches `VOIDED` only through the death cascade.

### 3.10. Penalty Assessment and Waiver

Late-enrollment penalties are assessed by a `ComplianceOfficer`, who has independently counted the uncovered months off the record. Assessment names a `beneficiary_id`, a `penalty_type`, and an `uncovered_months` count (an integer of at least 0). The `penalty_type` is either `PART_B` or `PART_D`, and it selects which penalty formula applies. The assessment is created with `status` `ASSESSED` and a computed `monthly_penalty_cents`.

When `penalty_type` is `PART_D`, the penalty uses the same Part D formula as drug confirmation but with the caller-supplied `uncovered_months` taken verbatim rather than computed: one percent of the national base beneficiary premium of 3,470 cents, multiplied by the uncovered months, rounded to the nearest dime (divide by ten, round half up, multiply by ten) to yield integer cents.

When `penalty_type` is `PART_B`, the penalty is ten percent of the standard Part B premium — fixed at 17,470 cents — for *each full twelve-month period* the beneficiary was uncovered; partial twelve-month periods do not count. Compute the number of full periods by integer-dividing the uncovered months by twelve (so thirteen uncovered months yield one full period). The penalty percentage is ten times that number of full periods. Then `monthly_penalty_cents` is the standard Part B premium multiplied by that integer percentage, integer-divided by 100 (floored). For example, one full period gives a ten-percent penalty.

A `ComplianceOfficer` may waive an `ASSESSED` penalty, which requires the assessment to currently be `ASSESSED`, moves `status` to `WAIVED`, sets `monthly_penalty_cents` to 0, and increments the `version`.

### 3.11. Window Membership and the Order of Enrollment Checks

Every Part B, Part C, and Part D enrollment creation must occur while the system clock falls inside the named period's window. For `IEP`, `AEP`, and `SEP_5STAR` periods this is the closed interval `[window_start, window_end]`: the clock must be at or after `window_start` and at or before `window_end`, inclusive on both ends. A creation attempted while the clock lies outside that interval is rejected with `ERR_OUTSIDE_ENROLLMENT_WINDOW` (HTTP 422).

A further constraint governs the five-star Special Enrollment Period: a `SEP_5STAR` period may justify a Part C enrollment only if the chosen plan's `star_rating` is exactly `5.0`, and likewise a Part D enrollment under a `SEP_5STAR` period requires its `PART_D` plan's `star_rating` to be exactly `5.0`. A non-five-star plan used under a five-star period is rejected with `ERR_NOT_FIVE_STAR` (HTTP 422).

Several checks share these enrollment-create endpoints, and they are evaluated in a fixed priority order so that the *first* applicable failure is the one reported. Authentication comes first: a missing `X-User-ID` or `X-User-Role` header yields `ERR_UNAUTHENTICATED` (HTTP 401). Authorization is next: a role not permitted for the operation yields `ERR_UNAUTHORIZED` (HTTP 403). Then path-referenced resources are checked for existence left-to-right (`ERR_NOT_FOUND`, HTTP 404), followed by body-referenced foreign keys such as `beneficiary_id`, `plan_id`, and `enrollment_period_id` (also `ERR_NOT_FOUND`, HTTP 404). Next the request body itself is validated — required fields present and well-typed, enums in range, the `date_of_birth` day-of-month not the 1st, cents fields integer and within bounds — failing with `ERR_INVALID_REQUEST` (HTTP 422). For action and transition endpoints, the target's from-state is checked next (`ERR_INVALID_STATE`, HTTP 409), and on Part C confirmation specifically the OCC version match is checked at this stage (`ERR_STALE_VERSION`, HTTP 412).

After those structural checks, the business-referential and business-rule checks apply in order: first that the `enrollment_period_id` belongs to the same `beneficiary_id` named on the enrollment, failing with `ERR_PERIOD_BENEFICIARY_MISMATCH` (HTTP 422); then that the period is of the type required for the enrollment kind (`ERR_WRONG_PERIOD_TYPE`, HTTP 422); then that the beneficiary's `enrollment_lock` is false (`ERR_ENROLLMENT_LOCKED`, HTTP 409); then that the clock falls within the period window (`ERR_OUTSIDE_ENROLLMENT_WINDOW`, HTTP 422); then, for Medigap, the 63-day guaranteed-issue window check (`ERR_GI_WINDOW_EXPIRED`, HTTP 422); then the five-star plan check for `SEP_5STAR` enrollments (`ERR_NOT_FIVE_STAR`, HTTP 422); and then the drug-coverage conflict checks for Part C/Part D plan-type and MAPD-stacking (`ERR_DRUG_COVERAGE_CONFLICT`, HTTP 409). The period-overlap guard on creating a same-type `IEP`/`AEP` period (`ERR_PERIOD_OVERLAP`, HTTP 409) and the Medigap coverage-overlap guard (`ERR_MEDIGAP_OVERLAP`, HTTP 409) apply to their respective creation endpoints. This ordering matters because it determines which single error a multiply-invalid request surfaces.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify or transition an existing resource — including lifecycle actions, the clock-setting capability, and reads — return a `200 OK` status code. All requests require the `X-User-ID` and `X-User-Role` headers.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/beneficiaries` | Create a beneficiary | EnrollmentAdmin |
| GET | `/beneficiaries` | List beneficiaries (paginated) | EnrollmentAdmin, ComplianceOfficer |
| GET | `/beneficiaries/{id}` | Fetch a beneficiary | EnrollmentAdmin, ComplianceOfficer |
| POST | `/beneficiaries/{id}/establish-part-a` | Establish Part A (hospital) coverage | EnrollmentAdmin |
| POST | `/beneficiaries/{id}/fraud-hold` | Place beneficiary on FRAUD_HOLD | ComplianceOfficer |
| POST | `/beneficiaries/{id}/clear-hold` | Clear FRAUD_HOLD back to ACTIVE | ComplianceOfficer |
| POST | `/beneficiaries/{id}/record-death` | Record death; cascades VOIDED to all active coverage | EnrollmentAdmin |
| POST | `/beneficiaries/{id}/enrollment-periods` | Compute and persist an enrollment period | EnrollmentAdmin |
| GET | `/beneficiaries/{id}/enrollment-periods` | List a beneficiary's enrollment periods | EnrollmentAdmin, ComplianceOfficer |
| GET | `/enrollment-periods/{id}` | Fetch an enrollment period | EnrollmentAdmin, ComplianceOfficer |
| POST | `/plans` | Create a plan offering | EnrollmentAdmin |
| GET | `/plans/{id}` | Fetch a plan | EnrollmentAdmin, ComplianceOfficer |
| POST | `/plans/{id}/retire` | Retire a plan | EnrollmentAdmin |
| POST | `/part-b-enrollments` | File a Part B enrollment under an IEP window | EnrollmentAdmin |
| GET | `/part-b-enrollments` | List/filter Part B enrollments | EnrollmentAdmin, ComplianceOfficer |
| GET | `/part-b-enrollments/{id}` | Fetch a Part B enrollment | EnrollmentAdmin, ComplianceOfficer |
| POST | `/part-b-enrollments/{id}/activate` | Activate a FILED Part B enrollment | EnrollmentAdmin |
| POST | `/part-b-enrollments/{id}/drop` | Voluntarily drop active Part B | EnrollmentAdmin |
| POST | `/part-c-enrollments` | File a Part C (Medicare Advantage) enrollment | EnrollmentAdmin |
| GET | `/part-c-enrollments` | List/filter Part C enrollments | EnrollmentAdmin, ComplianceOfficer |
| GET | `/part-c-enrollments/{id}` | Fetch a Part C enrollment | EnrollmentAdmin, ComplianceOfficer |
| POST | `/part-c-enrollments/{id}/confirm` | Confirm a PENDING Part C enrollment; OCC-guarded | EnrollmentAdmin |
| POST | `/part-c-enrollments/{id}/disenroll` | Voluntarily disenroll an active Part C enrollment | EnrollmentAdmin |
| POST | `/part-d-enrollments` | File a Part D (drug) enrollment | EnrollmentAdmin |
| GET | `/part-d-enrollments` | List/filter Part D enrollments | EnrollmentAdmin, ComplianceOfficer |
| GET | `/part-d-enrollments/{id}` | Fetch a Part D enrollment | EnrollmentAdmin, ComplianceOfficer |
| POST | `/part-d-enrollments/{id}/confirm` | Confirm a PENDING Part D enrollment; computes LEP | EnrollmentAdmin |
| POST | `/part-d-enrollments/{id}/disenroll` | Voluntarily disenroll an active Part D enrollment | EnrollmentAdmin |
| POST | `/part-d-enrollments/{id}/claims` | Post a DrugClaim against an ACTIVE Part D enrollment | EnrollmentAdmin |
| GET | `/part-d-enrollments/{id}/claims` | List drug claims for an enrollment | EnrollmentAdmin, ComplianceOfficer |
| POST | `/medigap-policies` | Apply for a Medigap policy under a GI_MEDIGAP window | EnrollmentAdmin |
| GET | `/medigap-policies` | List/filter Medigap policies | EnrollmentAdmin, ComplianceOfficer |
| GET | `/medigap-policies/{id}` | Fetch a Medigap policy | EnrollmentAdmin, ComplianceOfficer |
| POST | `/medigap-policies/{id}/lapse` | Lapse an issued Medigap policy | EnrollmentAdmin |
| POST | `/penalty-assessments` | Assess a Part B or Part D late enrollment penalty | ComplianceOfficer |
| GET | `/penalty-assessments` | List/filter penalty assessments | EnrollmentAdmin, ComplianceOfficer |
| GET | `/penalty-assessments/{id}` | Fetch a penalty assessment | EnrollmentAdmin, ComplianceOfficer |
| POST | `/penalty-assessments/{id}/waive` | Waive an assessed penalty | ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Set the system clock | EnrollmentAdmin, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PERIOD_BENEFICIARY_MISMATCH` | 422 |
| `ERR_WRONG_PERIOD_TYPE` | 422 |
| `ERR_ENROLLMENT_LOCKED` | 409 |
| `ERR_OUTSIDE_ENROLLMENT_WINDOW` | 422 |
| `ERR_GI_WINDOW_EXPIRED` | 422 |
| `ERR_NOT_FIVE_STAR` | 422 |
| `ERR_DRUG_COVERAGE_CONFLICT` | 409 |
| `ERR_PART_A_REQUIRED` | 409 |
| `ERR_PART_B_REQUIRED` | 409 |
| `ERR_PLAN_RETIRED` | 409 |
| `ERR_VALIDATION_PAGINATION` | 422 |
| `ERR_MISSING_SOURCE_EVENT_DATE` | 422 |
| `ERR_PERIOD_OVERLAP` | 409 |
| `ERR_MEDIGAP_OVERLAP` | 409 |
