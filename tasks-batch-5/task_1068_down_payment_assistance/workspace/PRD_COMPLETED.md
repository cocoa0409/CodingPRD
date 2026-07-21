# Down-Payment Assistance API — Product Requirements Document

## 1. Introduction

Housing agencies that operate down-payment assistance and shared-equity programs juggle two hard problems at once: they must decide who qualifies for public subsidy, and they must account for every cent of appropriated money as it is reserved, disbursed, and eventually recaptured on resale. This API is the system of record for both. It carries a household from first application through income and Area-Median-Income (AMI) eligibility screening, homebuyer-education completion, an assistance award, the layered draw of that award against one or more appropriations, the purchase closing, and finally the long tail of servicing and recapture when the home is sold years later.

The design goals are auditability and fiscal conservation. Every award is pinned to a recapture algorithm at the moment it is created, so a later change to program policy cannot retroactively rewrite what a homebuyer owes. Every funding appropriation maintains a strict ledger whose buckets must always sum to the original amount, and every allocation drawn against it moves money between those buckets rather than creating or destroying it. Because multiple case managers may draw against the same appropriation, the system uses optimistic concurrency to prevent one writer from silently overwriting the committed balance another writer has already consumed. Separation of duties is enforced throughout: the staff member who reviews an application to an eligible outcome is barred from approving the award that flows from it.

This document specifies the complete contract: the global conventions every endpoint honours (Section 2), the business workflows and calculations that govern each entity's lifecycle (Section 3), the endpoint catalogue (Section 4), and the error code catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request other than the two public/test-driving exceptions noted below must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity under which they act. If either header is absent, or if `X-User-Role` is not one of the roles enumerated here, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Authentication (header presence and role recognition) is checked before authorization (whether that role may call this endpoint).

The system recognizes six roles: `Anonymous`, `Applicant`, `CaseManager`, `ProgramAdmin`, `ClosingCoordinator`, and `Servicer`.

Two endpoints are exempt from the authentication-header requirement. Applicant self-registration is a public operation performed under the `Anonymous` role and requires no headers. Setting the server logical clock is a test-driving capability that likewise does not require authentication headers. Every other endpoint requires valid headers.

Role identities bind to resources as follows. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`; ownership checks on any resource that references an `Applicant` compare the resource's applicant foreign key to `X-User-ID`. The other five roles carry opaque operator identifiers not tied to any persisted entity. Specifically, when `X-User-Role` is `Anonymous`, `CaseManager`, `ProgramAdmin`, `ClosingCoordinator`, or `Servicer`, `X-User-ID` is an opaque identifier that the server does not compare to any entity's `id`. The server does, however, record two such operator identifiers where the workflow demands an audit trail: the reviewing case manager's identifier is written to `reviewed_by_user_id` on an application when it is reviewed to an eligible or ineligible outcome, and the approving case manager's identifier is written to `approved_by_user_id` on an award when it is approved. These recorded values drive the separation-of-duties check described in Section 3.4, but they are never treated as entity identities.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific workflow states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources in this system are addressable, mutable records and carry a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix, unique across all resources.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that starts at 1 and increments by one on every mutation. It underpins the optimistic-concurrency mechanism described in Section 2.9.

Two entities are exceptions. An `IncomeLimit` row is an immutable reference record: it carries only `id` and `created_at`, and it has neither an `updated_at` nor a `version`. All other entities — `Program`, `Applicant`, `Property`, `Application`, `EducationSession`, `Enrollment`, `Certificate`, `Award`, `FundingSource`, `FundingAllocation`, `Closing`, `ServicingAccount`, and `SaleEvent` — carry the full complement of common fields. Whenever the server derives or recomputes a field on a resource (for example, refreshing a funding source's ledger buckets), that counts as a mutation: `updated_at` is refreshed and `version` is incremented.

### 2.5. Monetary Values and Precision

Every monetary amount in this system is an integer number of cents; there are no fractional cents and no floating-point money. Where a calculation produces a rounded value, the rounding method is round-half-up unless a step explicitly calls for rounding up (ceiling) or down (floor). The two AMI figures illustrate the split: the reporting percentage `ami_pct` is rounded half-up to two decimal places, while the eligibility ceiling is computed with an integer floor and compared exactly. The minimum-contribution component of the assistance calculation rounds up to the next whole cent, and the funding gap is floored at zero. Recapture forgiveness is produced with a single round-half-up applied to the whole product, never by rounding per-month figures and summing them — the two approaches yield different cents, and only the single-final-rounding result is correct.

### 2.6. The Logical Clock and Temporal Rules

The server maintains a logical clock that is the sole source of "now" for every time-dependent rule: certificate issuance and expiry, education-session start gating, closing-window overlap, sale-date validation, and the months-held count used in declining-balance recapture. At startup the clock reads exactly `2026-07-01T00:00:00Z`; until the clock is explicitly set it holds that default and never falls back to wall-clock time. An administrative test-driving capability advances the clock to a supplied instant carried in the `to_iso8601` field. All temporal comparisons in this document are evaluated against this logical clock, not the host system time.

### 2.7. Cascading Consistency and Automatic Transitions

Several operations mutate more than one entity in a single atomic request, and the server resolves the entire cascade before responding — there are no partially applied cascades. A funding draw that fully reserves an award advances that award automatically, without a separate client request. Completing a closing drives a four-hop chain: it recomputes the award's final assistance, releases any over-reserved allocation, disburses the remaining reservations, moves money between the funding sources' ledger buckets, and opens a servicing account. Cancelling an award releases its still-reserved allocations and credits the money back. Closing a servicing account after a sale settles drives the award to its terminal recaptured or repaid outcome. Each of these secondary mutations independently refreshes the affected resource's `updated_at` and increments its `version`, exactly as a direct edit would. The specific triggers, preconditions, and side effects of each cascade are given in the workflow subsections of Section 3.

### 2.8. Nested Resource Retrieval and Existence Ordering

Many endpoints name a resource in the path and additionally reference other resources by foreign key in the body. Existence is validated left-to-right: the resource identified in the path is checked first, then each foreign key in the body in the order it appears. The first identifier that does not resolve produces that resource's specific not-found error — for example a missing program yields `ERR_PROGRAM_NOT_FOUND`, a missing applicant `ERR_APPLICANT_NOT_FOUND`, a missing application `ERR_APPLICATION_NOT_FOUND`, a missing property `ERR_PROPERTY_NOT_FOUND`, a missing education session `ERR_SESSION_NOT_FOUND`, a missing enrollment `ERR_ENROLLMENT_NOT_FOUND`, a missing certificate `ERR_CERTIFICATE_NOT_FOUND`, a missing award `ERR_AWARD_NOT_FOUND`, a missing funding source `ERR_FUNDING_SOURCE_NOT_FOUND`, a missing funding allocation `ERR_ALLOCATION_NOT_FOUND`, a missing closing `ERR_CLOSING_NOT_FOUND`, or a missing servicing account `ERR_SERVICING_NOT_FOUND` — each with HTTP 404. Existence checks precede all business-rule checks so that an invalid container is caught before any deeper processing.

The overall order in which every request is screened is: authentication (`ERR_UNAUTHENTICATED`), then authorization (`ERR_UNAUTHORIZED`), then existence of path and body references (the not-found family above), then structural validity of the body (`ERR_INVALID_REQUEST` — required fields present, enum values valid members, integer amounts within their declared ranges), then the generic state-machine guard (`ERR_INVALID_STATE`, when the target resource is not in a state from which the requested transition is defined), and finally the endpoint-specific business rules described in Section 3.

### 2.9. Optimistic Concurrency on Funding Draws

Reserving a funding allocation is the one operation in this system guarded by optimistic concurrency control, because two case managers may legitimately draw against the same appropriation and each draw reduces its uncommitted balance. A request to reserve an allocation must carry `expected_funding_source_version`, which is not optional, holding the `version` of the target `FundingSource` as the client last observed it. If another writer has drawn against that source in the interim, the source's `version` will have advanced past the value the client supplied; the client's view of the remaining balance is therefore stale, and the reservation is rejected with `ERR_STALE_VERSION` (HTTP 412). Only when `expected_funding_source_version` equals the funding source's current `version` may the draw proceed. No other endpoint accepts or requires a version field.

### 2.10. The Funding Source Ledger Invariant

Each `FundingSource` maintains three ledger buckets — `available_cents` (uncommitted), `reserved_cents` (committed but not yet paid out), and `disbursed_cents` (permanently paid out) — whose sum must always equal `total_appropriation_cents`. Money is never created or destroyed by an allocation; it only moves between buckets. When an allocation is reserved, `available_cents` is debited and `reserved_cents` credited by the drawn amount. When an allocation is released, the same amount moves back from `reserved_cents` to `available_cents`. When an allocation is disbursed, the amount moves from `reserved_cents` to `disbursed_cents`. A source begins `ACTIVE` with `available_cents` equal to `total_appropriation_cents` and both `reserved_cents` and `disbursed_cents` at zero; it becomes `FULLY_COMMITTED` at the moment both `available_cents` and `reserved_cents` reach zero after a disbursement. The award-side mirror of this ledger, `allocated_cents`, is the sum of `amount_cents` over the award's allocations that are in `RESERVED` or `DISBURSED` status, and it is kept consistent with those allocation rows on every change.

## 3. Business Logic & Workflows

### 3.1. Programs, Income Limits, and AMI Eligibility

A `ProgramAdmin` establishes a **Program**, the top-level policy container, by supplying a human-readable `name`, an AMI ceiling `ami_limit_pct` expressed as a whole-number percent of Area Median Income between 1 and 120 (so a value of 80 admits households at or below 80% AMI), and a `max_assistance_cents` ceiling of at least zero that caps the assistance any single award under the program may reserve or disburse. The program also fixes its recapture policy. The `recapture_model` is either `SHARED_APPRECIATION`, under which the program later recaptures a share of the home's appreciation on resale, or `DECLINING_BALANCE`, under which the disbursed principal is forgiven pro-rata over a term. Two further inputs parameterize those models: `recapture_term_months`, the number of months over which a declining-balance award is fully forgiven (at least 1, defaulting to 120, and ignored for shared-appreciation), and `appreciation_share_pct`, the whole-number percent of appreciation the program recaptures for shared-appreciation awards between 0 and 100 (defaulting to 30, and ignored for declining-balance). A new program opens in `OPEN` status, which accepts applications. A program admin may later close it, moving `status` from `OPEN` to `CLOSED`; a closed program no longer accepts new submissions.

Against each program the admin defines **income-limit** rows, one per household size. Each row records the `program_id` it belongs to, the `household_size` it applies to (an integer from 1 to 12), and `ami_100_income_cents`, the annual income in cents that equals exactly 100% of Area Median Income for that household size (at least 1). At most one income-limit row may exist for a given program and household size; an attempt to define a second row for the same pair is rejected with `ERR_DUPLICATE_INCOME_LIMIT` (HTTP 409).

Eligibility rests on the single income-limit row that matches an application's program and the applicant's household size. Two figures are derived from it. The **reporting figure** `ami_pct` is the applicant's `annual_income_cents` divided by that row's `ami_100_income_cents`, multiplied by 100, and rounded half-up to two decimal places; it is informational and feeds the assistance tiering, but it does not itself decide eligibility. The **eligibility test** is an exact integer-cents comparison that does not use the rounded percentage: the income ceiling is `ami_100_income_cents` multiplied by the program's `ami_limit_pct`, divided by 100, then floored to whole cents, and the applicant qualifies when their `annual_income_cents` is less than or equal to that ceiling. The boundary is inclusive — income exactly equal to the ceiling passes.

### 3.2. Applicants, Properties, and the Application Lifecycle

A prospective homebuyer registers themselves as an **Applicant** through the public self-registration operation, supplying `full_name`, a contact `email` that must be unique across all applicants (a registration whose email duplicates an existing applicant is rejected with `ERR_INVALID_REQUEST`, HTTP 400), a `household_size` from 1 to 12, and `annual_income_cents` of at least zero. An optional `first_time_buyer` flag records whether they are a first-time buyer and defaults to true when omitted. Once registered, an applicant's own `id` is the `X-User-ID` they act under.

A `CaseManager` registers the **Property** a household intends to buy, providing its `address`, a `county_code` used for reporting, and a `purchase_price_cents` of at least 1. An optional `unit_type` classifies the dwelling as `SINGLE_FAMILY`, `CONDO`, or `TOWNHOME`, defaulting to `SINGLE_FAMILY`. The appraised value is not known at registration: `appraised_value_cents` is null until a case manager records an appraisal, at which point it is set to the supplied value (at least 1). Recording an appraisal is a prerequisite for completing the eventual closing.

An **Application** ties a household to a program and a property. It is created — by either the applicant themselves or a case manager acting on their behalf — with `applicant_id`, `program_id`, `property_id`, an estimated `first_mortgage_amount_cents` of at least zero, and the `buyer_contribution_cents` the buyer states they will bring, also at least zero. A freshly created application is in `DRAFT`. It also carries two computed reporting fields, `ami_pct` and `estimated_assistance_cents`, which are empty in draft and populated at submit, and a system field `reviewed_by_user_id` that stays null until a reviewer reaches a decision.

Submitting an application moves it from `DRAFT` to `SUBMITTED`, an action reserved to the applicant. Submission requires the program to be `OPEN` (a submission against a closed program is rejected with `ERR_INVALID_STATE`) and requires that an income-limit row already exists for the application's program and the applicant's household size; if none exists, the submission is rejected with `ERR_INCOME_LIMIT_UNDEFINED` (HTTP 422). On success the system computes the reporting `ami_pct` and the provisional `estimated_assistance_cents` (the provisional assistance calculation of Section 3.4) from the application's estimated inputs.

Review is a case-manager action whose `decision` field selects the transition; an optional `review_notes` string may accompany it. A decision of `START` moves a `SUBMITTED` application to `UNDER_REVIEW`. From `UNDER_REVIEW`, a decision of `NEEDS_INFO` sends the application to `NEEDS_INFO` and records the `review_notes`; the applicant then resubmits, which returns the application from `NEEDS_INFO` to `UNDER_REVIEW` and recomputes `ami_pct` and `estimated_assistance_cents` from the application's current inputs. Resubmission, like the original submission, requires that an income-limit row exists for the application's program and the applicant's household size; if none exists it is rejected with `ERR_INCOME_LIMIT_UNDEFINED` (HTTP 422). This `NEEDS_INFO`-to-`UNDER_REVIEW` loop may repeat. A decision of `ELIGIBLE` moves an `UNDER_REVIEW` application to `ELIGIBLE`, but only if the eligibility test of Section 3.1 passes — the applicant's `annual_income_cents` must be at or below the floored income ceiling; otherwise the decision is rejected with `ERR_INCOME_OVER_LIMIT` (HTTP 422). A decision of `INELIGIBLE` moves an `UNDER_REVIEW` application to `INELIGIBLE`. Both the `ELIGIBLE` and `INELIGIBLE` outcomes record the reviewing case manager's `X-User-ID` into `reviewed_by_user_id`; this recorded identity is what later enforces separation of duties at award approval. `INELIGIBLE` is terminal.

At any point while an application is in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO`, the applicant may withdraw it, moving it to the terminal `WITHDRAWN` state.

### 3.3. Homebuyer Education, Enrollment, and Certificates

Every award requires proof that the household completed homebuyer education. A `ProgramAdmin` schedules an **Education Session** for a program, supplying the owning `program_id`, a `title`, a `start_at` and `end_at` instant (both ISO 8601 UTC), and a `capacity` of at least 1. The `end_at` must be strictly later than `start_at`; a session whose end is at or before its start is rejected with `ERR_SESSION_TIME_INVALID` (HTTP 400). Each session tracks `enrolled_count`, which begins at zero and is maintained as the number of its enrollments currently in `ENROLLED` or `ATTENDED` status.

An applicant enrolls themselves into a session, creating an **Enrollment** that names the `session_id` and the `applicant_id` and starts in `ENROLLED`. Two guards protect enrollment, evaluated in this order. First, a scheduling-conflict check: the applicant must not already be `ENROLLED` or `ATTENDED` in another session whose time interval falls within 30 minutes of this session's interval. Treating both intervals as closed and this 30-minute buffer as the separation, two sessions conflict when the other session's `start_at` is earlier than this session's `end_at` plus 30 minutes and this session's `start_at` is earlier than the other session's `end_at` plus 30 minutes; a conflict is rejected with `ERR_SESSION_TIME_CONFLICT` (HTTP 409). Only sessions the applicant is already `ENROLLED` or `ATTENDED` in count toward the conflict; cancelled or no-show enrollments do not. Second, if the conflict check passes, capacity is enforced: the session's `enrolled_count` must be strictly less than its `capacity`, otherwise the enrollment is rejected with `ERR_SESSION_FULL` (HTTP 409). A successful enrollment increments the session's `enrolled_count`.

A program admin resolves each enrollment. Marking attendance moves an `ENROLLED` enrollment to `ATTENDED`, but only once the session has begun — the logical clock must be at or after the session's `start_at`; an attempt to mark attendance before the session start is rejected with `ERR_INVALID_STATE` (HTTP 409). Because `enrolled_count` counts both `ENROLLED` and `ATTENDED` rows, attendance does not change the count. Marking attendance also mints the applicant's **Certificate** as a single-hop side effect: a certificate is created for the applicant with `status` `VALID`, its `source_enrollment_id` pointing back to the `ATTENDED` enrollment that produced it, `issued_at` set to the current logical-clock instant, and `expires_at` set to `issued_at` plus 365 days. Alternatively, a program admin may mark an `ENROLLED` enrollment as `NO_SHOW`, and an applicant may cancel their own `ENROLLED` enrollment to `CANCELLED`; each of these two outcomes decrements the session's `enrolled_count` by one. `ATTENDED`, `NO_SHOW`, and `CANCELLED` are all terminal.

A **Certificate** carries the holder's `applicant_id`, its `source_enrollment_id`, its `issued_at` and `expires_at` instants, and a `status` of `VALID` or `EXPIRED`. The certificate is `VALID` while the current logical clock is at or before `expires_at`; once the clock passes `expires_at` it is treated as `EXPIRED`, a status derived on read rather than by an explicit transition.

### 3.4. Awards, the Assistance Calculation, and Approval

Once an application reaches `ELIGIBLE`, a `CaseManager` creates an **Award** from it; the award records the originating application in its `application_id` field. The only client-supplied input is the `assistance_type`, the product form of the assistance, which is one of `GRANT`, `LOAN`, or `SHARED_APPRECIATION`. Creation is permitted only when the funding application is `ELIGIBLE`; against any other application state it is rejected with `ERR_INVALID_STATE` (HTTP 409). At creation the award copies the program's `recapture_model` onto its own `recapture_model` field so that the recapture algorithm is pinned even if the program's policy later changes; it sets `assistance_amount_cents` to the application's `estimated_assistance_cents`; and it enters `PENDING_EDUCATION`. The award also declares four fields that stay empty until the closing settles them: `assistance_amount_final_cents`, `original_disbursed_cents`, and `basis_value_cents` are all null until the closing completes, and `allocated_cents` starts at zero and tracks reserved and disbursed funding as described in Section 3.5.

**The assistance amount.** The provisional assistance stored on `estimated_assistance_cents` at submit — and copied to the award's `assistance_amount_cents` at creation — is computed as follows, in whole cents. First, a minimum-contribution tier is selected from the reporting `ami_pct`: at or below 50.00 the tier percentage is 0; above 50.00 and at or below 65.00 it is 1 percent; above 65.00 and at or below 80.00 it is 3 percent; and above 80.00 the highest tier carries forward, so the tier percentage remains 3. The required buyer contribution is the greater of the buyer's stated contribution and the tier percentage of the basis rounded up to the next whole cent (the tier percentage of the basis, divided by 100, taking the ceiling). The funding gap is then the basis minus the first-mortgage amount minus that required buyer contribution. The assistance is the funding gap floored at zero (never negative) and then capped at the program's `max_assistance_cents` — that is, the smaller of `max_assistance_cents` and the non-negative funding gap. In the provisional computation performed at submit and at each resubmit, the basis is the property's `purchase_price_cents`, the first-mortgage amount is the application's `first_mortgage_amount_cents`, the stated contribution is `buyer_contribution_cents`, and `ami_pct` is the value recorded on the application; no appraised-value cap applies to the basis in the provisional variant. The final variant, recomputed at closing (Section 3.6), differs only in its inputs and can move the amount in either direction.

**Approval.** Approving an award moves it from `PENDING_EDUCATION` to `APPROVED` and is a case-manager action. Beyond the generic state guard (approval is defined only from `PENDING_EDUCATION`, else `ERR_INVALID_STATE`), the underlying application must still be `ELIGIBLE`. Three further conditions are then checked in this order. First, separation of duties: the approving `X-User-ID` must differ from the `reviewed_by_user_id` recorded on the underlying application; if the same operator who reviewed the application to eligibility attempts the approval, it is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Second, the education requirement: the applicant must have at least one certificate that was ever issued — in either `VALID` or `EXPIRED` status — confirming that education was completed at some point; if the applicant has no certificate at all, approval is rejected with `ERR_EDUCATION_INCOMPLETE` (HTTP 422). Third, certificate currency: the certificate must still be in-date, meaning the current logical clock is at or before its `expires_at`; when the applicant holds more than one certificate, currency is satisfied as long as at least one of them is in-date, and only if none is in-date is the approval rejected with `ERR_CERTIFICATE_EXPIRED` (HTTP 422). Note that the education-completeness check and the currency check are distinct — the former is satisfied by an expired certificate, the latter is not. On success the award records the approving operator's `X-User-ID` in `approved_by_user_id` and enters `APPROVED`.

**Cancellation.** A case manager may cancel an award while it is `APPROVED` or `FUNDED`, moving it to the terminal `CANCELLED` state. Cancellation drives a cascade: every one of the award's still-`RESERVED` funding allocations is released (moved to `RELEASED`), and for each such allocation the reserved amount is credited back from the funding source's `reserved_cents` to its `available_cents`, preserving the ledger invariant of Section 2.10.

### 3.5. Layered Funding, Subordination, and Reservation

A `ProgramAdmin` establishes each **Funding Source** (an appropriation) with a `name`, a `priority`, and a `total_appropriation_cents` of at least zero. The `priority` is the subordination rank: a lower number denotes a more senior lien position that is drawn first, and priority values must be unique across active funding sources; an attempt to create a source whose `priority` collides with an existing `ACTIVE` source is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A new source opens `ACTIVE` with `available_cents` equal to its `total_appropriation_cents` and `reserved_cents` and `disbursed_cents` both at zero.

Assistance is funded by layering one or more **Funding Allocations** against an award — a design that lets a single award draw from several appropriations in a defined lien order. A `CaseManager` reserves an allocation by supplying the `award_id`, the `funding_source_id` to draw from, the `amount_cents` to draw (at least 1), the `lien_position` to record on the allocation (at least 1, where 1 is most senior), and the `expected_funding_source_version` for the concurrency check of Section 2.9. The allocation is created in `RESERVED`.

The reservation is screened in a fixed order. After the existence and structural checks, the award must be in `APPROVED` status — this state gate is evaluated before any concurrency or fiscal check, and a draw against an award in any other status is rejected with `ERR_AWARD_NOT_APPROVED` (HTTP 409). Next comes the optimistic-concurrency check on the funding source's `version`: a stale `expected_funding_source_version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Then the subordination check: the supplied `lien_position` must be at least as large as the maximum `lien_position` among the award's existing `RESERVED` or `DISBURSED` allocations, and it must be non-decreasing with respect to the drawn source's `priority` so that the award's allocations preserve senior-to-junior order; a violation is rejected with `ERR_LIEN_ORDER_INVALID` (HTTP 422). Then the award-ceiling check: the award's current `allocated_cents` plus the new `amount_cents` must not exceed the award's `assistance_amount_cents`, otherwise the draw is rejected with `ERR_ALLOCATION_EXCEEDS_AWARD` (HTTP 422). Finally, the fiscal check, evaluated only after the award-approved state gate: the `amount_cents` must not exceed the funding source's `available_cents`, otherwise `ERR_INSUFFICIENT_FUNDS` (HTTP 409) is returned.

On a successful reservation the source's `available_cents` is debited and its `reserved_cents` credited by `amount_cents`, the source's `version` is incremented by one, and the award's `allocated_cents` is recomputed as the sum of `amount_cents` over its `RESERVED` and `DISBURSED` allocations. If that recomputed `allocated_cents` now equals the award's `assistance_amount_cents`, the award auto-advances from `APPROVED` to `FUNDED` in the same request — a fully-reserved award needs no separate client action to become funded.

### 3.6. Purchase Closing and the Disbursement Cascade

A `ClosingCoordinator` schedules a **Closing** for an award, naming the target `property_id`, a `scheduled_date` (the start of the occupation window), and an optional `window_days` giving the length in days of the exclusive property-occupation window, which defaults to 7 and must be at least 1. The window is the half-open interval running from `scheduled_date` up to but not including `scheduled_date` plus `window_days`. A new closing must not collide with another: if any other non-`CANCELLED` closing on the same property has an occupation window that overlaps this one, the schedule is rejected with `ERR_CLOSING_WINDOW_CONFLICT` (HTTP 409). Because the windows are half-open, exact adjacency — a new window that starts precisely when a prior window ends — is allowed and does not conflict. A new closing enters `SCHEDULED`. Its `final_purchase_price_cents` and `final_first_mortgage_cents` are null until completion.

The coordinator advances a `SCHEDULED` closing to `DOCS_PENDING`, and may cancel a closing that is `SCHEDULED` or `DOCS_PENDING`, moving it to the terminal `CANCELLED` state. Completing a closing is the pivotal fiscal event and is permitted only from `DOCS_PENDING`. Completion supplies the actual `final_purchase_price_cents` (at least 1) and `final_first_mortgage_cents` (at least zero). Two further preconditions guard it: the award must be in `FUNDED` status (otherwise `ERR_INVALID_STATE`, HTTP 409), and the property must have a recorded appraisal — its `appraised_value_cents` must be set — otherwise the completion is rejected with `ERR_APPRAISAL_MISSING` (HTTP 422).

A successful completion moves the closing to `COMPLETED` and drives a four-hop cascade that carries the award from `FUNDED` to `SERVICING`:

1. **Recompute final assistance.** The award's `assistance_amount_final_cents` is recomputed with the assistance calculation of Section 3.4 in its final variant. Here the basis is the smaller of the closing's `final_purchase_price_cents` and the property's `appraised_value_cents`; the first-mortgage amount is `final_first_mortgage_cents`; the stated contribution is the application's `buyer_contribution_cents`; and `ami_pct` is the value recorded on the application. The award's `basis_value_cents` is set to that same basis — the smaller of `final_purchase_price_cents` and `appraised_value_cents` — captured as the basis for later appreciation.
2. **Reconcile over-reservation.** If the recomputed `assistance_amount_final_cents` is less than the award's `allocated_cents`, the excess (the difference between `allocated_cents` and `assistance_amount_final_cents`) is released from the still-`RESERVED` allocations, most-junior first. Allocations are processed in order of descending `lien_position` (most junior first), breaking ties by descending `created_at` (newest first). Each release reduces the remaining excess by the smaller of the excess and that allocation's `amount_cents`; an allocation whose amount exceeds the remaining excess is only partially released, its `amount_cents` reduced to the still-reserved remainder and the released portion credited back to its funding source's `available_cents`. The `id` field is never used for this ordering.
3. **Disburse the remainder.** Every allocation still `RESERVED` after reconciliation transitions to `DISBURSED`. For each, the amount moves from that funding source's `reserved_cents` to its `disbursed_cents`; and if the source's `available_cents` and `reserved_cents` have both reached zero, the source flips to `FULLY_COMMITTED`. The award's `original_disbursed_cents` is set equal to `assistance_amount_final_cents`, the true total disbursed and the basis for recapture.
4. **Open servicing.** A **Servicing Account** is created for the award with `lifecycle_status` `ACTIVE`, `payment_status` `CURRENT`, `principal_balance_cents` equal to the award's `original_disbursed_cents`, and `opened_at` set to the current logical-clock instant, which anchors the months-held count used in declining-balance recapture.

### 3.7. Servicing, Sale Reporting, and Recapture

Once opened, a **Servicing Account** tracks the disbursed award over its life. Its `principal_balance_cents` holds the outstanding assistance principal — equal to the award's `original_disbursed_cents` at open and unchanged until a sale settles — while `recapture_amount_cents` and `forgiven_amount_cents` stay null until a sale is reported. A servicing account carries two independent dimensions. The primary `lifecycle_status` runs `ACTIVE`, then `IN_SALE`, then `CLOSED`. A separate `payment_status` dimension runs between `CURRENT` and `DELINQUENT` and evolves independently of the lifecycle.

A `Servicer` may toggle the payment dimension at will: moving an account from `CURRENT` to `DELINQUENT`, or back from `DELINQUENT` to `CURRENT`, by supplying the target value in the `to` field. The toggle is permitted as long as the account is not `CLOSED`, and it never alters `lifecycle_status` — the two dimensions move independently. A toggle whose `to` value equals the account's current `payment_status` is a no-op transition and is rejected with `ERR_INVALID_STATE` (HTTP 409).

When the home is sold, the servicer reports the sale against an `ACTIVE` account, supplying the `sale_price_cents` (at least 1) and the `sale_date`. The sale date must not precede the account's `opened_at`; a sale reported earlier than the account opened is rejected with `ERR_SALE_BEFORE_OPEN` (HTTP 422). Reporting a sale creates a **Sale Event** recording the `servicing_account_id`, `sale_price_cents`, and `sale_date`, computes the recapture figures, copies `recapture_amount_cents` and `forgiven_amount_cents` onto the servicing account, and advances `lifecycle_status` from `ACTIVE` to `IN_SALE`.

**Recapture calculation.** The sale event's `appreciation_cents` is the sale price minus the award's captured `basis_value_cents`, floored at zero (never negative). The rest depends on the award's pinned `recapture_model`, and both branches work in whole cents from the award's `original_disbursed_cents` as the principal:

- Under `SHARED_APPRECIATION`, the program recaptures its principal plus its share of appreciation. The recapture amount is the original disbursed principal plus the program's `appreciation_share_pct` percent of the appreciation (the share percentage divided by 100, multiplied by `appreciation_cents`, rounded half-up), and the forgiven amount is always zero. Because it adds an appreciation share on top of principal, the recapture can exceed the original disbursed amount.
- Under `DECLINING_BALANCE`, the principal is forgiven pro-rata over the program's `recapture_term_months`. First count the months held: the number of full calendar months from the account's `opened_at` to the sale's `sale_date`, taking the floor (whole months only). The forgiven amount is the original principal multiplied by the smaller of the months held and `recapture_term_months`, divided by `recapture_term_months`, with a single round-half-up applied to that whole product. This single final rounding is required: rounding a per-month figure and then summing across months would produce a different cents result and is not used. The recapture amount is the original principal minus the forgiven amount, which lands somewhere between zero and the full original amount.

The computed `recapture_amount_cents` and `forgiven_amount_cents` are stored on both the sale event and the servicing account.

**Closing out servicing.** After the sale settles, the servicer closes the account, which is permitted only when the account is `IN_SALE` and a sale event exists for it. Closing sets `principal_balance_cents` to zero, moves `lifecycle_status` to the terminal `CLOSED`, and drives the award out of `SERVICING` to its terminal outcome: if the account's `recapture_amount_cents` is greater than zero the award becomes `RECAPTURED`, and if it is exactly zero the award becomes `REPAID`. A shared-appreciation award, which always recaptures at least its principal, therefore settles as `RECAPTURED`; a fully-forgiven declining-balance award settles as `REPAID`.

### 3.8. Portfolio Reporting

A `ProgramAdmin` may pull a portfolio-summary report, an aggregation across the whole system. It returns `total_awards`, the exact count of all awards; `total_reserved_cents`, the sum of `amount_cents` over all funding allocations currently in `RESERVED` status; `total_disbursed_cents`, the sum of `amount_cents` over all funding allocations currently in `DISBURSED` status; and `total_recaptured_cents`, the sum of `recapture_amount_cents` over all servicing accounts whose `lifecycle_status` is `CLOSED`. The report additionally breaks down the award count grouped by award status in an `awards_by_status` field — an object mapping each award status string that currently occurs to its exact integer count (statuses with no awards are omitted). All sums are whole-cent integers and all counts are exact; because they are order-independent sums and counts, the result does not depend on any ordering.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. This includes creating programs, income limits, applicants, properties, applications, education sessions, enrollments, awards, funding sources, funding allocations, and closings, as well as reporting a sale (which creates a new sale event). Operations that modify an existing resource — including all state-transition actions such as submitting, reviewing, approving, cancelling, completing, closing, and toggling payment status, along with recording an appraisal and setting the logical clock — return `200 OK`. The request and response bodies for each endpoint are governed by the workflows in Section 3; the table below lists only the method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/v1/programs` | Create a program | ProgramAdmin |
| POST | `/api/v1/programs/{id}/close` | Close a program to new applications | ProgramAdmin |
| GET | `/api/v1/programs/{id}` | Fetch a program | ProgramAdmin, CaseManager, Applicant, ClosingCoordinator, Servicer |
| GET | `/api/v1/programs` | List programs | ProgramAdmin, CaseManager, Applicant, ClosingCoordinator, Servicer |
| POST | `/api/v1/programs/{id}/income-limits` | Define an income-limit row | ProgramAdmin |
| GET | `/api/v1/programs/{id}/income-limits` | List income-limit rows for a program | ProgramAdmin, CaseManager |
| GET | `/api/v1/programs/{id}/education-sessions` | List education sessions of a program | ProgramAdmin, CaseManager, Applicant |
| POST | `/api/v1/applicants` | Self-register an applicant | Anonymous |
| GET | `/api/v1/applicants/{id}` | Fetch an applicant | Applicant, CaseManager, ProgramAdmin |
| POST | `/api/v1/properties` | Register a property | CaseManager |
| GET | `/api/v1/properties/{id}` | Fetch a property | CaseManager, ClosingCoordinator, ProgramAdmin |
| POST | `/api/v1/properties/{id}/appraisal` | Record an appraised value on a property | CaseManager |
| POST | `/api/v1/applications` | Create an application in DRAFT | Applicant, CaseManager |
| GET | `/api/v1/applications/{id}` | Fetch an application | Applicant, CaseManager, ProgramAdmin |
| GET | `/api/v1/applications` | List/filter applications | CaseManager, ProgramAdmin |
| POST | `/api/v1/applications/{id}/submit` | Submit an application | Applicant |
| POST | `/api/v1/applications/{id}/review` | Review an application (decision-driven) | CaseManager |
| POST | `/api/v1/applications/{id}/resubmit` | Resubmit after NEEDS_INFO | Applicant |
| POST | `/api/v1/applications/{id}/withdraw` | Withdraw a non-terminal application | Applicant |
| POST | `/api/v1/education-sessions` | Create a homebuyer-education session | ProgramAdmin |
| GET | `/api/v1/education-sessions/{id}` | Fetch a session | ProgramAdmin, CaseManager, Applicant |
| POST | `/api/v1/education-sessions/{id}/enrollments` | Enroll an applicant into a session | Applicant |
| GET | `/api/v1/education-sessions/{id}/enrollments` | List enrollments of a session | ProgramAdmin, CaseManager |
| GET | `/api/v1/enrollments/{id}` | Fetch an enrollment | ProgramAdmin, CaseManager, Applicant |
| GET | `/api/v1/enrollments` | List/filter enrollments | ProgramAdmin, CaseManager |
| POST | `/api/v1/enrollments/{id}/attend` | Mark attendance; mints the certificate | ProgramAdmin |
| POST | `/api/v1/enrollments/{id}/no-show` | Mark an enrollment as a no-show | ProgramAdmin |
| POST | `/api/v1/enrollments/{id}/cancel` | Cancel an enrollment | Applicant |
| GET | `/api/v1/certificates/{id}` | Fetch a certificate | ProgramAdmin, CaseManager, Applicant |
| GET | `/api/v1/certificates` | List/filter certificates | ProgramAdmin, CaseManager |
| POST | `/api/v1/applications/{id}/awards` | Create an award from an ELIGIBLE application | CaseManager |
| GET | `/api/v1/awards/{id}` | Fetch an award | CaseManager, ProgramAdmin, ClosingCoordinator, Servicer |
| GET | `/api/v1/awards` | List/filter awards | CaseManager, ProgramAdmin |
| POST | `/api/v1/awards/{id}/approve` | Approve an award | CaseManager |
| POST | `/api/v1/awards/{id}/cancel` | Cancel an award; releases reserved allocations | CaseManager |
| POST | `/api/v1/funding-sources` | Create a funding source | ProgramAdmin |
| GET | `/api/v1/funding-sources/{id}` | Fetch a funding source | ProgramAdmin, CaseManager |
| GET | `/api/v1/funding-sources` | List funding sources | ProgramAdmin, CaseManager |
| POST | `/api/v1/funding-allocations` | Reserve a funding draw against an award | CaseManager |
| GET | `/api/v1/funding-allocations/{id}` | Fetch a funding allocation | CaseManager, ProgramAdmin |
| GET | `/api/v1/funding-allocations` | List/filter funding allocations | CaseManager, ProgramAdmin |
| POST | `/api/v1/awards/{id}/closings` | Schedule a closing for an award | ClosingCoordinator |
| GET | `/api/v1/closings/{id}` | Fetch a closing | ClosingCoordinator, CaseManager, ProgramAdmin |
| GET | `/api/v1/closings` | List/filter closings | ClosingCoordinator, CaseManager, ProgramAdmin |
| POST | `/api/v1/closings/{id}/docs-pending` | Move a closing to DOCS_PENDING | ClosingCoordinator |
| POST | `/api/v1/closings/{id}/complete` | Complete a closing; drives disbursement cascade | ClosingCoordinator |
| POST | `/api/v1/closings/{id}/cancel` | Cancel a scheduled/docs-pending closing | ClosingCoordinator |
| GET | `/api/v1/servicing-accounts/{id}` | Fetch a servicing account | Servicer, CaseManager, ProgramAdmin |
| GET | `/api/v1/servicing-accounts` | List/filter servicing accounts | Servicer, ProgramAdmin |
| POST | `/api/v1/servicing-accounts/{id}/report-sale` | Report a sale; computes recapture | Servicer |
| GET | `/api/v1/servicing-accounts/{id}/sale-events` | List sale events for an account | Servicer, ProgramAdmin, CaseManager |
| POST | `/api/v1/servicing-accounts/{id}/close` | Close servicing after sale settles | Servicer |
| POST | `/api/v1/servicing-accounts/{id}/payment-status` | Toggle the payment dimension | Servicer |
| GET | `/api/v1/reports/portfolio-summary` | Aggregate portfolio report | ProgramAdmin |
| POST | `/api/v1/_clock/set_current_utc` | Set the server logical clock | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_APPLICANT_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_PROPERTY_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 |
| `ERR_AWARD_NOT_FOUND` | 404 |
| `ERR_FUNDING_SOURCE_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_CLOSING_NOT_FOUND` | 404 |
| `ERR_SERVICING_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_AWARD_NOT_APPROVED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_EDUCATION_INCOMPLETE` | 422 |
| `ERR_CERTIFICATE_EXPIRED` | 422 |
| `ERR_INCOME_OVER_LIMIT` | 422 |
| `ERR_INCOME_LIMIT_UNDEFINED` | 422 |
| `ERR_SESSION_TIME_CONFLICT` | 409 |
| `ERR_SESSION_FULL` | 409 |
| `ERR_CLOSING_WINDOW_CONFLICT` | 409 |
| `ERR_APPRAISAL_MISSING` | 422 |
| `ERR_LIEN_ORDER_INVALID` | 422 |
| `ERR_ALLOCATION_EXCEEDS_AWARD` | 422 |
| `ERR_INSUFFICIENT_FUNDS` | 409 |
| `ERR_SALE_BEFORE_OPEN` | 422 |
| `ERR_SESSION_TIME_INVALID` | 400 |
| `ERR_DUPLICATE_INCOME_LIMIT` | 409 |
